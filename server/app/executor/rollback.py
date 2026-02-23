from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.models import (
    ExecutionActionStatus,
    ExecutionAuditRecord,
    RecommendationType,
    RollbackActionResult,
    RollbackActionStatus,
    RollbackRequest,
    RollbackResponse,
)


class RollbackService:
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

    def rollback(
        self,
        request: RollbackRequest,
        audit_records: list[ExecutionAuditRecord],
        execution_id: str,
    ) -> RollbackResponse:
        attempted = 0
        rolled_back = 0
        skipped = 0
        failed = 0
        results: list[RollbackActionResult] = []

        for record in audit_records:
            attempted += 1

            if not self._rollback_eligible(record):
                skipped += 1
                results.append(
                    RollbackActionResult(
                        audit_id=record.audit_id,
                        recommendation_id=record.recommendation_id,
                        recommendation_type=record.recommendation_type,
                        status=RollbackActionStatus.SKIPPED,
                        message="Action is not eligible for rollback.",
                        rolled_back=False,
                    )
                )
                continue

            if request.dry_run:
                results.append(
                    RollbackActionResult(
                        audit_id=record.audit_id,
                        recommendation_id=record.recommendation_id,
                        recommendation_type=record.recommendation_type,
                        status=RollbackActionStatus.DRY_RUN,
                        message="Dry run: rollback would be attempted.",
                        rolled_back=False,
                    )
                )
                continue

            success, message = self._rollback_action(record)
            if success:
                rolled_back += 1
                results.append(
                    RollbackActionResult(
                        audit_id=record.audit_id,
                        recommendation_id=record.recommendation_id,
                        recommendation_type=record.recommendation_type,
                        status=RollbackActionStatus.ROLLED_BACK,
                        message=message,
                        rolled_back=True,
                    )
                )
            else:
                failed += 1
                results.append(
                    RollbackActionResult(
                        audit_id=record.audit_id,
                        recommendation_id=record.recommendation_id,
                        recommendation_type=record.recommendation_type,
                        status=RollbackActionStatus.FAILED,
                        message=message,
                        rolled_back=False,
                    )
                )

        return RollbackResponse(
            run_id=request.run_id,
            execution_id=execution_id,
            dry_run=request.dry_run,
            attempted=attempted,
            rolled_back=rolled_back,
            skipped=skipped,
            failed=failed,
            results=results,
            processed_at=datetime.now(timezone.utc),
        )

    def _rollback_eligible(self, record: ExecutionAuditRecord) -> bool:
        if not record.rollback_available:
            return False
        if record.action_status != ExecutionActionStatus.EXECUTED:
            return False
        if record.recommendation_type not in self.REVERSIBLE_ACTIONS:
            return False
        return True

    def _rollback_action(self, record: ExecutionAuditRecord) -> tuple[bool, str]:
        if not record.pre_change_state:
            return False, "Missing pre-change state snapshot."

        bucket = record.pre_change_state.get("bucket") or record.bucket
        key = record.pre_change_state.get("key") or record.key

        try:
            if record.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
                original_class = record.pre_change_state.get("storage_class") or "STANDARD"
                self.s3.copy_object(
                    Bucket=bucket,
                    Key=key,
                    CopySource={"Bucket": bucket, "Key": key},
                    StorageClass=original_class,
                    MetadataDirective="COPY",
                    TaggingDirective="COPY",
                )
                return True, f"Restored {key} to {original_class}."

            if record.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
                original_rules = record.pre_change_state.get("existing_lifecycle_rules")
                if original_rules is None:
                    self.s3.delete_bucket_lifecycle(Bucket=bucket)
                    return True, f"Removed lifecycle policy from {bucket}."
                else:
                    self.s3.put_bucket_lifecycle_configuration(
                        Bucket=bucket,
                        LifecycleConfiguration={"Rules": original_rules},
                    )
                    return True, f"Restored original lifecycle policy on {bucket}."

        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            return False, f"S3 error ({code}): {msg}"

        return False, "No rollback handler for recommendation type."

