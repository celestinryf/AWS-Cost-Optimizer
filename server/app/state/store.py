from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[str, RunRecord] = {}

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
            self._runs[run_id] = record
            return record

    def get(self, run_id: str) -> Optional[RunRecord]:
        return self._runs.get(run_id)

    def list(self) -> list[RunRecord]:
        return sorted(
            self._runs.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    def set_scores(
        self,
        run_id: str,
        scores: list[RiskScore],
        savings_details: list[SavingsEstimate],
        savings_summary: SavingsSummary,
    ) -> Optional[RunRecord]:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return None
            record.scores = scores
            record.savings_details = savings_details
            record.savings_summary = savings_summary
            record.status = RunStatus.SCORED
            record.updated_at = datetime.now(timezone.utc)
            return record

    def set_execution(self, run_id: str, execution: ExecuteResponse) -> Optional[RunRecord]:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return None
            record.execution = execution
            record.status = RunStatus.EXECUTED
            record.updated_at = datetime.now(timezone.utc)
            return record
