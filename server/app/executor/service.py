from datetime import datetime, timezone
from typing import Any
import os
import uuid

import boto3
from botocore.exceptions import ClientError

from app.models import (
    ExecuteRequest,
    ExecuteResponse,
    ExecutionActionResult,
    ExecutionActionStatus,
    ExecutionMode,
    Recommendation,
    RecommendationType,
    RollbackStatus,
    RiskScore,
    RunStatus,
)


class ExecutionService:
    def __init__(self, s3_client: Any = None) -> None:
        self._s3 = s3_client

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            self._s3 = boto3.client("s3")
        return self._s3

    REVERSIBLE_ACTIONS = {
        RecommendationType.CHANGE_STORAGE_CLASS,
        RecommendationType.ADD_LIFECYCLE_POLICY,
    }

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
        execution_id = str(uuid.uuid4())
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
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score_by_id.get(recommendation.id),
                        status=ExecutionActionStatus.SKIPPED,
                        message=f"Skipped due to max_actions={request.max_actions} limit.",
                        permitted=True,
                        required_permissions=[],
                        missing_permissions=[],
                        simulated=dry_run,
                        pre_change_state=self._capture_pre_change_state(recommendation),
                        post_change_state=None,
                    )
                )
                continue

            score = score_by_id.get(recommendation.id)
            if score is None:
                failed += 1
                action_results.append(
                    self._result(
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=None,
                        status=ExecutionActionStatus.FAILED,
                        message="Missing risk score for recommendation.",
                        permitted=False,
                        required_permissions=[],
                        missing_permissions=[],
                        simulated=dry_run,
                        pre_change_state=self._capture_pre_change_state(recommendation),
                        post_change_state=None,
                    )
                )
                continue

            if not self._is_mode_eligible(effective_mode, score):
                skipped += 1
                action_results.append(
                    self._result(
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.SKIPPED,
                        message=f"Skipped by mode '{effective_mode.value}' risk policy.",
                        permitted=True,
                        required_permissions=[],
                        missing_permissions=[],
                        simulated=dry_run,
                        pre_change_state=self._capture_pre_change_state(recommendation),
                        post_change_state=None,
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
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.BLOCKED,
                        message="Blocked: set ALLOW_DESTRUCTIVE_EXECUTION=true to allow deletes.",
                        permitted=False,
                        required_permissions=required_permissions,
                        missing_permissions=missing_permissions,
                        simulated=dry_run,
                        pre_change_state=self._capture_pre_change_state(recommendation),
                        post_change_state=None,
                    )
                )
                continue

            if missing_permissions:
                blocked += 1
                action_results.append(
                    self._result(
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.BLOCKED,
                        message="Blocked: missing required permissions.",
                        permitted=False,
                        required_permissions=required_permissions,
                        missing_permissions=missing_permissions,
                        simulated=dry_run,
                        pre_change_state=self._capture_pre_change_state(recommendation),
                        post_change_state=None,
                    )
                )
                continue

            if dry_run:
                executed += 1
                action_results.append(
                    self._result(
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.DRY_RUN,
                        message="Dry run: validation passed, action would execute.",
                        permitted=True,
                        required_permissions=required_permissions,
                        missing_permissions=[],
                        simulated=True,
                        pre_change_state=self._capture_pre_change_state(recommendation),
                        post_change_state=self._capture_post_change_state(recommendation, simulated=True),
                    )
                )
                continue

            success, message, extra_state = self._execute_action(recommendation)
            pre_state = {**self._capture_pre_change_state(recommendation), **extra_state}
            if success:
                executed += 1
                action_results.append(
                    self._result(
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.EXECUTED,
                        message=message,
                        permitted=True,
                        required_permissions=required_permissions,
                        missing_permissions=[],
                        simulated=False,
                        pre_change_state=pre_state,
                        post_change_state=self._capture_post_change_state(recommendation, simulated=False),
                    )
                )
            else:
                failed += 1
                action_results.append(
                    self._result(
                        audit_id=str(uuid.uuid4()),
                        recommendation=recommendation,
                        score=score,
                        status=ExecutionActionStatus.FAILED,
                        message=message,
                        permitted=True,
                        required_permissions=required_permissions,
                        missing_permissions=[],
                        simulated=False,
                        pre_change_state=pre_state,
                        post_change_state=None,
                    )
                )

        return ExecuteResponse(
            execution_id=execution_id,
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

    def _execute_action(self, recommendation: Recommendation) -> tuple[bool, str, dict]:
        rec = recommendation
        try:
            if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
                target = rec.recommended_action.split()[-1]
                self.s3.copy_object(
                    Bucket=rec.bucket,
                    Key=rec.key,
                    CopySource={"Bucket": rec.bucket, "Key": rec.key},
                    StorageClass=target,
                    MetadataDirective="COPY",
                    TaggingDirective="COPY",
                )
                return True, f"Transitioned {rec.key} to {target}.", {}

            if rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
                # Capture existing rules before mutating (needed for rollback)
                try:
                    existing_rules = self.s3.get_bucket_lifecycle_configuration(
                        Bucket=rec.bucket
                    )["Rules"]
                except ClientError as e:
                    if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
                        existing_rules = None
                    else:
                        raise

                extra = {"existing_lifecycle_rules": existing_rules}

                new_rules = [
                    {
                        "ID": "aws-cost-optimizer-archive",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "Transitions": [{"Days": 90, "StorageClass": "GLACIER_IR"}],
                    },
                    {
                        "ID": "aws-cost-optimizer-multipart-cleanup",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                    },
                ]
                existing_ids = {r["ID"] for r in (existing_rules or [])}
                merged = (existing_rules or []) + [
                    r for r in new_rules if r["ID"] not in existing_ids
                ]
                self.s3.put_bucket_lifecycle_configuration(
                    Bucket=rec.bucket,
                    LifecycleConfiguration={"Rules": merged},
                )
                return True, f"Applied lifecycle policy to {rec.bucket}.", extra

            if rec.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
                # upload_id stored in storage_class field by scanner
                upload_id = rec.storage_class or ""
                self.s3.abort_multipart_upload(
                    Bucket=rec.bucket,
                    Key=rec.key,
                    UploadId=upload_id,
                )
                return True, f"Aborted incomplete upload for {rec.key}.", {}

            if rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
                self.s3.delete_object(Bucket=rec.bucket, Key=rec.key)
                return True, f"Deleted stale object {rec.key}.", {}

        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            return False, f"S3 error ({code}): {msg}", {}

        return False, "Unsupported recommendation type.", {}

    def _result(
        self,
        audit_id: str,
        recommendation: Recommendation,
        score: RiskScore | None,
        status: ExecutionActionStatus,
        message: str,
        permitted: bool,
        required_permissions: list[str],
        missing_permissions: list[str],
        simulated: bool,
        pre_change_state: dict,
        post_change_state: dict | None,
    ) -> ExecutionActionResult:
        requires_approval = score.requires_approval if score else True
        risk_level = score.risk_level if score else recommendation.risk_level
        rollback_available = (
            status == ExecutionActionStatus.EXECUTED
            and recommendation.recommendation_type in self.REVERSIBLE_ACTIONS
            and not simulated
        )
        rollback_status = RollbackStatus.PENDING if rollback_available else RollbackStatus.NOT_APPLICABLE

        return ExecutionActionResult(
            audit_id=audit_id,
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
            pre_change_state=pre_change_state,
            post_change_state=post_change_state,
            rollback_available=rollback_available,
            rollback_status=rollback_status,
        )

    def _capture_pre_change_state(self, recommendation: Recommendation) -> dict:
        last_modified = recommendation.last_modified.isoformat() if recommendation.last_modified else None
        return {
            "bucket": recommendation.bucket,
            "key": recommendation.key,
            "storage_class": recommendation.storage_class,
            "size_bytes": recommendation.size_bytes,
            "last_modified": last_modified,
            "risk_level": recommendation.risk_level.value,
        }

    def _capture_post_change_state(self, recommendation: Recommendation, simulated: bool) -> dict:
        if recommendation.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            return {
                "action": "change_storage_class",
                "target": recommendation.recommended_action,
                "simulated": simulated,
            }
        if recommendation.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
            return {
                "action": "add_lifecycle_policy",
                "target": recommendation.recommended_action,
                "simulated": simulated,
            }
        if recommendation.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            return {
                "action": "delete_incomplete_upload",
                "target": recommendation.key,
                "simulated": simulated,
            }
        if recommendation.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            return {
                "action": "delete_stale_object",
                "target": recommendation.key,
                "simulated": simulated,
            }
        return {"action": "unknown", "simulated": simulated}
