from datetime import datetime, timezone

from app.models import ExecuteRequest, ExecuteResponse, ExecutionMode, Recommendation, RiskScore, RunStatus


class ExecutionService:
    def execute(
        self,
        request: ExecuteRequest,
        recommendations: list[Recommendation],
        scores: list[RiskScore],
    ) -> ExecuteResponse:
        score_by_id = {score.recommendation_id: score for score in scores}

        executable = 0
        skipped = 0
        failed = 0

        for recommendation in recommendations:
            score = score_by_id.get(recommendation.id)
            if not score:
                skipped += 1
                continue

            if self._is_executable(request.mode, score):
                executable += 1
            else:
                skipped += 1

        return ExecuteResponse(
            run_id=request.run_id,
            status=RunStatus.EXECUTED,
            mode=request.mode,
            dry_run=request.dry_run,
            executed=executable,
            skipped=skipped,
            failed=failed,
            executed_at=datetime.now(timezone.utc),
        )

    def _is_executable(self, mode: ExecutionMode, score: RiskScore) -> bool:
        if mode == ExecutionMode.SAFE:
            return score.safe_to_automate
        if mode == ExecutionMode.STANDARD:
            return not score.requires_approval
        return True

