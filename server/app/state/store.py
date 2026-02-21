from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Optional
import uuid

from app.models import (
    ExecuteResponse,
    ExecutionActionResult,
    ExecutionAuditRecord,
    Recommendation,
    RollbackStatus,
    RiskScore,
    RunStatus,
    SavingsEstimate,
    SavingsSummary,
)


@dataclass
class RunRecord:
    run_id: str
    status: RunStatus
    recommendations: list[Recommendation]
    scores: list[RiskScore] = field(default_factory=list)
    savings_details: list[SavingsEstimate] = field(default_factory=list)
    savings_summary: Optional[SavingsSummary] = None
    execution: Optional[ExecuteResponse] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RunStore:
    def __init__(self, db_path: str = "data/runs.db") -> None:
        self._lock = Lock()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, recommendations: list[Recommendation]) -> RunRecord:
        with self._lock:
            run_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            record = RunRecord(
                run_id=run_id,
                status=RunStatus.SCANNED,
                recommendations=recommendations,
                created_at=now,
                updated_at=now,
            )
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id,
                        status,
                        recommendations_json,
                        scores_json,
                        savings_details_json,
                        savings_summary_json,
                        execution_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.run_id,
                        record.status.value,
                        self._serialize_models(record.recommendations),
                        self._serialize_models(record.scores),
                        self._serialize_models(record.savings_details),
                        self._serialize_model(record.savings_summary),
                        self._serialize_model(record.execution),
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                    ),
                )
            return record

    def get(self, run_id: str) -> Optional[RunRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    run_id,
                    status,
                    recommendations_json,
                    scores_json,
                    savings_details_json,
                    savings_summary_json,
                    execution_json,
                    created_at,
                    updated_at
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list(self) -> list[RunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    status,
                    recommendations_json,
                    scores_json,
                    savings_details_json,
                    savings_summary_json,
                    execution_json,
                    created_at,
                    updated_at
                FROM runs
                ORDER BY updated_at DESC
                """
            ).fetchall()

        return [self._row_to_record(row) for row in rows]

    def set_scores(
        self,
        run_id: str,
        scores: list[RiskScore],
        savings_details: list[SavingsEstimate],
        savings_summary: SavingsSummary,
    ) -> Optional[RunRecord]:
        with self._lock:
            record = self.get(run_id)
            if not record:
                return None
            record.scores = scores
            record.savings_details = savings_details
            record.savings_summary = savings_summary
            record.status = RunStatus.SCORED
            record.updated_at = datetime.now(timezone.utc)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET
                        status = ?,
                        scores_json = ?,
                        savings_details_json = ?,
                        savings_summary_json = ?,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        record.status.value,
                        self._serialize_models(record.scores),
                        self._serialize_models(record.savings_details),
                        self._serialize_model(record.savings_summary),
                        record.updated_at.isoformat(),
                        run_id,
                    ),
                )
            return record

    def set_execution(self, run_id: str, execution: ExecuteResponse) -> Optional[RunRecord]:
        with self._lock:
            record = self.get(run_id)
            if not record:
                return None
            record.execution = execution
            record.status = RunStatus.EXECUTED
            record.updated_at = datetime.now(timezone.utc)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET
                        status = ?,
                        execution_json = ?,
                        updated_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        record.status.value,
                        self._serialize_model(record.execution),
                        record.updated_at.isoformat(),
                        run_id,
                    ),
                )
                self._insert_execution_audit(conn, run_id, execution.execution_id, execution.action_results)
            return record

    def list_execution_audit(
        self,
        run_id: str,
        execution_id: Optional[str] = None,
        audit_ids: Optional[list[str]] = None,
    ) -> list[ExecutionAuditRecord]:
        query = """
            SELECT
                audit_id,
                execution_id,
                run_id,
                recommendation_id,
                recommendation_type,
                bucket,
                key,
                action_status,
                message,
                risk_level,
                requires_approval,
                permitted,
                required_permissions_json,
                missing_permissions_json,
                simulated,
                pre_change_state_json,
                post_change_state_json,
                rollback_available,
                rollback_status,
                rolled_back_at,
                created_at
            FROM execution_audit
            WHERE run_id = ?
        """
        params: list = [run_id]

        if execution_id:
            query += " AND execution_id = ?"
            params.append(execution_id)

        if audit_ids:
            placeholders = ",".join(["?"] * len(audit_ids))
            query += f" AND audit_id IN ({placeholders})"
            params.extend(audit_ids)

        query += " ORDER BY created_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_audit_record(row) for row in rows]

    def update_rollback_status(
        self,
        audit_id: str,
        rollback_status: RollbackStatus,
        message: Optional[str] = None,
    ) -> bool:
        with self._lock:
            rolled_back_at = datetime.now(timezone.utc).isoformat() if rollback_status == RollbackStatus.ROLLED_BACK else None
            with self._connect() as conn:
                run_row = conn.execute(
                    "SELECT run_id FROM execution_audit WHERE audit_id = ?",
                    (audit_id,),
                ).fetchone()
                cursor = conn.execute(
                    """
                    UPDATE execution_audit
                    SET
                        rollback_status = ?,
                        rolled_back_at = COALESCE(?, rolled_back_at),
                        message = COALESCE(?, message)
                    WHERE audit_id = ?
                    """,
                    (
                        rollback_status.value,
                        rolled_back_at,
                        message,
                        audit_id,
                    ),
                )
                if cursor.rowcount > 0 and run_row:
                    conn.execute(
                        "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                        (datetime.now(timezone.utc).isoformat(), run_row["run_id"]),
                    )
                return cursor.rowcount > 0

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    recommendations_json TEXT NOT NULL,
                    scores_json TEXT NOT NULL,
                    savings_details_json TEXT NOT NULL,
                    savings_summary_json TEXT,
                    execution_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runs_updated_at
                ON runs(updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_audit (
                    audit_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    recommendation_type TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    key TEXT,
                    action_status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL,
                    permitted INTEGER NOT NULL,
                    required_permissions_json TEXT NOT NULL,
                    missing_permissions_json TEXT NOT NULL,
                    simulated INTEGER NOT NULL,
                    pre_change_state_json TEXT NOT NULL,
                    post_change_state_json TEXT,
                    rollback_available INTEGER NOT NULL,
                    rollback_status TEXT NOT NULL,
                    rolled_back_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_audit_run_id
                ON execution_audit(run_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_audit_execution_id
                ON execution_audit(execution_id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        recommendations = self._deserialize_models(row["recommendations_json"], Recommendation)
        scores = self._deserialize_models(row["scores_json"], RiskScore)
        savings_details = self._deserialize_models(row["savings_details_json"], SavingsEstimate)
        savings_summary = self._deserialize_model(row["savings_summary_json"], SavingsSummary)
        execution = self._deserialize_model(row["execution_json"], ExecuteResponse)

        return RunRecord(
            run_id=row["run_id"],
            status=RunStatus(row["status"]),
            recommendations=recommendations,
            scores=scores,
            savings_details=savings_details,
            savings_summary=savings_summary,
            execution=execution,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _serialize_models(self, data: list) -> str:
        return json.dumps([item.model_dump(mode="json") for item in data])

    def _serialize_model(self, data) -> Optional[str]:
        if data is None:
            return None
        return json.dumps(data.model_dump(mode="json"))

    def _deserialize_models(self, payload: str, model_type):
        if not payload:
            return []
        raw_items = json.loads(payload)
        return [model_type.model_validate(item) for item in raw_items]

    def _deserialize_model(self, payload: Optional[str], model_type):
        if not payload:
            return None
        return model_type.model_validate(json.loads(payload))

    def _insert_execution_audit(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        execution_id: str,
        action_results: list[ExecutionActionResult],
    ) -> None:
        for action in action_results:
            conn.execute(
                """
                INSERT OR REPLACE INTO execution_audit (
                    audit_id,
                    execution_id,
                    run_id,
                    recommendation_id,
                    recommendation_type,
                    bucket,
                    key,
                    action_status,
                    message,
                    risk_level,
                    requires_approval,
                    permitted,
                    required_permissions_json,
                    missing_permissions_json,
                    simulated,
                    pre_change_state_json,
                    post_change_state_json,
                    rollback_available,
                    rollback_status,
                    rolled_back_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.audit_id,
                    execution_id,
                    run_id,
                    action.recommendation_id,
                    action.recommendation_type.value,
                    action.bucket,
                    action.key,
                    action.status.value,
                    action.message,
                    action.risk_level.value,
                    int(action.requires_approval),
                    int(action.permitted),
                    json.dumps(action.required_permissions),
                    json.dumps(action.missing_permissions),
                    int(action.simulated),
                    json.dumps(action.pre_change_state),
                    json.dumps(action.post_change_state) if action.post_change_state is not None else None,
                    int(action.rollback_available),
                    action.rollback_status.value,
                    None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _row_to_audit_record(self, row: sqlite3.Row) -> ExecutionAuditRecord:
        return ExecutionAuditRecord(
            audit_id=row["audit_id"],
            execution_id=row["execution_id"],
            run_id=row["run_id"],
            recommendation_id=row["recommendation_id"],
            recommendation_type=row["recommendation_type"],
            bucket=row["bucket"],
            key=row["key"],
            action_status=row["action_status"],
            message=row["message"],
            risk_level=row["risk_level"],
            requires_approval=bool(row["requires_approval"]),
            permitted=bool(row["permitted"]),
            required_permissions=json.loads(row["required_permissions_json"]) if row["required_permissions_json"] else [],
            missing_permissions=json.loads(row["missing_permissions_json"]) if row["missing_permissions_json"] else [],
            simulated=bool(row["simulated"]),
            pre_change_state=json.loads(row["pre_change_state_json"]) if row["pre_change_state_json"] else {},
            post_change_state=json.loads(row["post_change_state_json"]) if row["post_change_state_json"] else None,
            rollback_available=bool(row["rollback_available"]),
            rollback_status=row["rollback_status"],
            rolled_back_at=datetime.fromisoformat(row["rolled_back_at"]) if row["rolled_back_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
