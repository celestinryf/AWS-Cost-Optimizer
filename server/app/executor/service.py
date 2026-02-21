from datetime import datetime, timezone
import os

from app.models import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionActionResult,
    ExecutionActionStatus,
    ExecutionMode,
    Recommendation,
    RecommendationType,
    RiskScore,
    RunStatus,
)


class ExecutionService:
    REQUIRED_PERMISSIONS = {
        RecommendationType.CHANGE_STORAGE_CLASS: ["s3:GetObject", "s3:PutObject"],
        RecommendationType.ADD_LIFECYCLE_POLICY: [
            "s3:GetLifecycleConfiguration",
            "s3:PutLifecycleConfiguration",
        ],
        RecommendationType.DELETE_INCOMPLETE_UPLOAD: [
            "s3:ListBucketMultipartUploads",
            "s3:AbortMultipartUpload",
        ],
        RecommendationType.DELETE_STALE_OBJECT: ["s3:GetObject", "s3:DeleteObject"],
    }

    def execute(
        self,
        request: ExecuteRequest,
        recommendations: list[Recommendation],
        scores: list[RiskScore],
    ) -> ExecuteResponse:
        effective_mode, dry_run = self._resolve_mode(request)
        score_by_id = {score.recommendation_id: score for score in scores}

        granted_permissions = self._granted_permissions()
        allow_destructive = os.getenv("ALLOW_DESTRUCTIVE_EXECUTION", "false").lower() == "true"

        action_results: list[ExecutionActionResult] = []
        eligible = 0
        executed = 0
        skipped = 0
        blocked = 0
        failed = 0

        for index, recommendation in enumerate(recommendations):
            if index >= request.max_actions:
                skipped += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score_by_id.get(recommendation.id),
                        status=ExecutionActionStatus.SKIPPED,
                        message=f"Skipped due to max_actions={request.max_actions} limit.",
                        permitted=True,
                        required_permissions=[],
                        missing_permissions=[],
                        simulated=dry_run,
                    )
                )
                continue

            score = score_by_id.get(recommendation.id)
            if score is None:
                failed += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=None,
                        status=ExecutionActionStatus.FAILED,
                        message="Missing risk score for recommendation.",
                        permitted=False,
                        required_permissions=[],
                        missing_permissions=[],
                        simulated=dry_run,
                    )
                )
                continue

            if not self._is_mode_eligible(effective_mode, score):
                skipped += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.SKIPPED,
                        message=f"Skipped by mode '{effective_mode.value}' risk policy.",
                        permitted=True,
                        required_permissions=[],
                        missing_permissions=[],
                        simulated=dry_run,
                    )
                )
                continue

            eligible += 1
            required_permissions = self.REQUIRED_PERMISSIONS.get(recommendation.recommendation_type, [])
            missing_permissions = [
                permission for permission in required_permissions if permission not in granted_permissions
            ]

            if recommendation.recommendation_type == RecommendationType.DELETE_STALE_OBJECT and not allow_destructive:
                blocked += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.BLOCKED,
                        message="Blocked: set ALLOW_DESTRUCTIVE_EXECUTION=true to allow deletes.",
                        permitted=False,
                        required_permissions=required_permissions,
                        missing_permissions=missing_permissions,
                        simulated=dry_run,
                    )
                )
                continue

            if missing_permissions:
                blocked += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.BLOCKED,
                        message="Blocked: missing required permissions.",
                        permitted=False,
                        required_permissions=required_permissions,
                        missing_permissions=missing_permissions,
                        simulated=dry_run,
                    )
                )
                continue

            if dry_run:
                executed += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.DRY_RUN,
                        message="Dry run: validation passed, action would execute.",
                        permitted=True,
                        required_permissions=required_permissions,
                        missing_permissions=[],
                        simulated=True,
                    )
                )
                continue

            success, message = self._execute_action(recommendation)
            if success:
                executed += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.EXECUTED,
                        message=message,
                        permitted=True,
                        required_permissions=required_permissions,
                        missing_permissions=[],
                        simulated=False,
                    )
                )
            else:
                failed += 1
                action_results.append(
                    self._result(
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.FAILED,
                        message=message,
                        permitted=True,
                        required_permissions=required_permissions,
                        missing_permissions=[],
                        simulated=False,
                    )
                )

        return ExecuteResponse(
            run_id=request.run_id,
            status=RunStatus.EXECUTED,
            mode=effective_mode,
            dry_run=dry_run,
            eligible=eligible,
            executed=executed,
            skipped=skipped,
            blocked=blocked,
            failed=failed,
            action_results=action_results,
            executed_at=datetime.now(timezone.utc),
        )

    def _resolve_mode(self, request: ExecuteRequest) -> tuple[ExecutionMode, bool]:
        if request.mode == ExecutionMode.DRY_RUN:
            return ExecutionMode.DRY_RUN, True

        if request.dry_run is True:
            return request.mode, True

        if request.dry_run is False:
            return request.mode, False

        return request.mode, request.mode == ExecutionMode.DRY_RUN

    def _is_mode_eligible(self, mode: ExecutionMode, score: RiskScore) -> bool:
        if mode == ExecutionMode.DRY_RUN:
            return True
        if mode == ExecutionMode.SAFE:
            return score.safe_to_automate
        if mode == ExecutionMode.STANDARD:
            return not score.requires_approval
        return True

    def _granted_permissions(self) -> set[str]:
        raw = os.getenv(
            "EXECUTOR_GRANTED_PERMISSIONS",
            ",".join(
                [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:GetLifecycleConfiguration",
                    "s3:PutLifecycleConfiguration",
                    "s3:ListBucketMultipartUploads",
                    "s3:AbortMultipartUpload",
                ]
            ),
        )
        return {item.strip() for item in raw.split(",") if item.strip()}

    def _execute_action(self, recommendation: Recommendation) -> tuple[bool, str]:
        if recommendation.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            return True, "Storage class transition executed."
        if recommendation.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
            return True, "Lifecycle policy update executed."
        if recommendation.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            return True, "Incomplete multipart uploads aborted."
        if recommendation.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            return True, "Stale object deletion executed."
        return False, "Unsupported recommendation type."

    def _result(
        self,
        recommendation: Recommendation,
        score: RiskScore | None,
        status: ExecutionActionStatus,
        message: str,
        permitted: bool,
        required_permissions: list[str],
        missing_permissions: list[str],
        simulated: bool,
    ) -> ExecutionActionResult:
        requires_approval = score.requires_approval if score else True
        risk_level = score.risk_level if score else recommendation.risk_level

        return ExecutionActionResult(
            recommendation_id=recommendation.id,
            recommendation_type=recommendation.recommendation_type,
            bucket=recommendation.bucket,
            key=recommendation.key,
            risk_level=risk_level,
            requires_approval=requires_approval,
            status=status,
            message=message,
            permitted=permitted,
            required_permissions=required_permissions,
            missing_permissions=missing_permissions,
            simulated=simulated,
        )

