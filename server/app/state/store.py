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
    Recommendation,
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
            return record

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
