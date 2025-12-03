# executor/executor.py
"""
Main executor that applies cost optimization changes.

Executes:
- Storage class transitions
- Lifecycle policy additions
- Incomplete multipart upload aborts
- Stale object deletions (with extra confirmation)

Safety features:
- Pre-execution validation
- State snapshots for rollback
- Automatic halt on too many failures
- Detailed audit logging
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable
import time

import boto3
from botocore.exceptions import ClientError

from models import Recommendation, RecommendationType, RiskLevel
from scoring import RiskScore
from .state_tracker import StateTracker, StateSnapshot, ExecutionStatus
from .validator import PreExecutionValidator, ValidationStatus
from .rollback import RollbackManager


class ExecutionMode(Enum):
    DRY_RUN = "dry_run"           # Log only, no changes
    SAFE = "safe"                  # Only low-risk, auto-approved
    STANDARD = "standard"          # Low and medium risk
    FULL = "full"                  # All including high-risk (requires confirmation)


@dataclass
class ExecutionConfig:
    """Configuration for execution run."""
    
    mode: ExecutionMode = ExecutionMode.SAFE
    
    # Safety limits
    max_failures: int = 3           # Stop after this many failures
    max_actions: int = 100          # Max actions per run
    
    # Delays
    delay_between_actions: float = 0.5   # Seconds between actions
    delay_after_failure: float = 2.0     # Seconds to wait after failure
    
    # Confirmation
    require_confirmation: bool = True    # Prompt before high-risk actions
    
    # Rollback
    auto_rollback_on_failure: bool = False  # Rollback all on failure


@dataclass
class ExecutionSummary:
    """Summary of an execution run."""
    
    batch_id: str
    mode: ExecutionMode
    
    total: int
    executed: int
    successful: int
    failed: int
    skipped: int
    
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    
    errors: list[str]
    
    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "mode": self.mode.value,
            "total": self.total,
            "executed": self.executed,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "errors": self.errors,
        }


class Executor:
    """
    Executes cost optimization recommendations.
    
    Handles the actual S3 API calls to make changes,
    with full state tracking and rollback support.
    """
    
    def __init__(
        self, 
        config: Optional[ExecutionConfig] = None,
        region: Optional[str] = None,
        confirm_callback: Optional[Callable[[str], bool]] = None
    ):
        self.config = config or ExecutionConfig()
        self.s3 = boto3.client("s3", region_name=region)
        
        self.state_tracker = StateTracker()
        self.validator = PreExecutionValidator(region)
        self.rollback_manager = RollbackManager(region)
        
        # Callback for confirmation prompts
        self.confirm_callback = confirm_callback or self._default_confirm
        
        # Execution stats
        self.failure_count = 0
        self.errors: list[str] = []
    
    def execute(
        self,
        recommendations: list[Recommendation],
        risk_scores: dict[str, RiskScore],
    ) -> ExecutionSummary:
        """
        Execute a list of recommendations.
        
        Args:
            recommendations: Recommendations to execute
            risk_scores: Risk scores for each recommendation
            
        Returns:
            ExecutionSummary with results
        """
        started_at = datetime.now(timezone.utc)
        self.failure_count = 0
        self.errors = []
        
        # Filter based on mode
        to_execute = self._filter_by_mode(recommendations, risk_scores)
        
        # Limit actions
        if len(to_execute) > self.config.max_actions:
            to_execute = to_execute[:self.config.max_actions]
        
        # Start batch tracking
        batch = self.state_tracker.start_batch(
            total_actions=len(to_execute),
            dry_run=(self.config.mode == ExecutionMode.DRY_RUN),
            skip_high_risk=(self.config.mode != ExecutionMode.FULL),
        )
        
        executed = 0
        successful = 0
        failed = 0
        skipped = len(recommendations) - len(to_execute)
        
        try:
            for rec in to_execute:
                # Check failure threshold
                if self.failure_count >= self.config.max_failures:
                    self.errors.append(f"Stopped: exceeded {self.config.max_failures} failures")
                    break
                
                # Get risk score
                score = risk_scores.get(rec.id)
                
                # Execute single recommendation
                success = self._execute_single(rec, score)
                
                executed += 1
                if success:
                    successful += 1
                else:
                    failed += 1
                    time.sleep(self.config.delay_after_failure)
                
                # Delay between actions
                time.sleep(self.config.delay_between_actions)
        
        except KeyboardInterrupt:
            self.errors.append("Execution interrupted by user")
        
        except Exception as e:
            self.errors.append(f"Unexpected error: {str(e)}")
        
        finally:
            # Complete batch tracking
            self.state_tracker.complete_batch()
        
        completed_at = datetime.now(timezone.utc)
        
        return ExecutionSummary(
            batch_id=batch.id,
            mode=self.config.mode,
            total=len(recommendations),
            executed=executed,
            successful=successful,
            failed=failed,
            skipped=skipped,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            errors=self.errors,
        )
    
    def _filter_by_mode(
        self,
        recommendations: list[Recommendation],
        risk_scores: dict[str, RiskScore]
    ) -> list[Recommendation]:
        """Filter recommendations based on execution mode."""
        if self.config.mode == ExecutionMode.DRY_RUN:
            return recommendations  # Process all for logging
        
        filtered = []
        
        for rec in recommendations:
            score = risk_scores.get(rec.id)
            
            if self.config.mode == ExecutionMode.SAFE:
                # Only auto-approved, low-risk items
                if score and score.safe_to_automate:
                    filtered.append(rec)
            
            elif self.config.mode == ExecutionMode.STANDARD:
                # Low and medium risk
                if score and score.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM]:
                    filtered.append(rec)
            
            elif self.config.mode == ExecutionMode.FULL:
                # Everything
                filtered.append(rec)
        
        return filtered
    
    def _execute_single(
        self,
        rec: Recommendation,
        score: Optional[RiskScore]
    ) -> bool:
        """
        Execute a single recommendation.
        
        Returns True if successful, False otherwise.
        """
        # Validate first
        validation = self.validator.validate(rec)
        
        if validation.status == ValidationStatus.FAILED:
            self.state_tracker.record_skip(
                recommendation_id=rec.id,
                action_type=rec.recommendation_type.value,
                bucket=rec.bucket,
                key=rec.key,
                reason=f"Validation failed: {validation.checks_failed}"
            )
            return True  # Skip isn't a failure
        
        # Check for confirmation on high-risk
        if score and score.requires_approval and self.config.require_confirmation:
            if not self.confirm_callback(
                f"Execute HIGH-RISK action: {rec.recommended_action}?"
            ):
                self.state_tracker.record_skip(
                    recommendation_id=rec.id,
                    action_type=rec.recommendation_type.value,
                    bucket=rec.bucket,
                    key=rec.key,
                    reason="User declined confirmation"
                )
                return True
        
        # Capture pre-state
        pre_state = self._capture_state(rec)
        
        # Determine rollback availability
        rollback_available = rec.recommendation_type in [
            RecommendationType.CHANGE_STORAGE_CLASS,
            RecommendationType.ADD_LIFECYCLE_POLICY,
        ]
        
        rollback_action = None
        if rollback_available:
            if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
                rollback_action = f"Restore to {pre_state.storage_class if pre_state else 'STANDARD'}"
            elif rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
                rollback_action = "Remove added lifecycle rules"
        
        # Start tracking
        record = self.state_tracker.record_start(
            recommendation_id=rec.id,
            action_type=rec.recommendation_type.value,
            bucket=rec.bucket,
            key=rec.key,
            pre_state=pre_state,
            rollback_available=rollback_available,
            rollback_action=rollback_action,
        )
        
        # Dry run - just log
        if self.config.mode == ExecutionMode.DRY_RUN:
            self.state_tracker.record_success(
                record.id,
                post_state={"dry_run": True, "would_execute": rec.recommended_action}
            )
            return True
        
        # Execute based on type
        try:
            if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
                success, result = self._execute_storage_change(rec)
            
            elif rec.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
                success, result = self._execute_multipart_abort(rec)
            
            elif rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
                success, result = self._execute_lifecycle_add(rec)
            
            elif rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
                success, result = self._execute_deletion(rec)
            
            elif rec.recommendation_type == RecommendationType.DELETE_OLD_VERSION:
                success, result = self._execute_version_deletion(rec)
            
            else:
                success = False
                result = f"Unknown action type: {rec.recommendation_type}"
            
            if success:
                self.state_tracker.record_success(record.id, post_state=result)
            else:
                self.state_tracker.record_failure(record.id, result)
                self.failure_count += 1
                self.errors.append(f"{rec.bucket}/{rec.key}: {result}")
            
            return success
        
        except Exception as e:
            self.state_tracker.record_failure(record.id, str(e))
            self.failure_count += 1
            self.errors.append(f"{rec.bucket}/{rec.key}: {str(e)}")
            return False
    
    def _capture_state(self, rec: Recommendation) -> Optional[StateSnapshot]:
        """Capture current state before modification."""
        try:
            if rec.key:
                response = self.s3.head_object(Bucket=rec.bucket, Key=rec.key)
                
                # Get tags
                tags = {}
                try:
                    tag_response = self.s3.get_object_tagging(
                        Bucket=rec.bucket, Key=rec.key
                    )
                    tags = {t["Key"]: t["Value"] for t in tag_response.get("TagSet", [])}
                except ClientError:
                    pass
                
                return StateSnapshot(
                    bucket=rec.bucket,
                    key=rec.key,
                    storage_class=response.get("StorageClass", "STANDARD"),
                    size_bytes=response.get("ContentLength", 0),
                    etag=response.get("ETag"),
                    last_modified=response.get("LastModified").isoformat() if response.get("LastModified") else None,
                    version_id=response.get("VersionId"),
                    tags=tags,
                )
            else:
                # Bucket-level action
                lifecycle_rules = []
                try:
                    response = self.s3.get_bucket_lifecycle_configuration(Bucket=rec.bucket)
                    lifecycle_rules = response.get("Rules", [])
                except ClientError:
                    pass
                
                return StateSnapshot(
                    bucket=rec.bucket,
                    key=None,
                    metadata={"lifecycle_rules": lifecycle_rules}
                )
        
        except ClientError:
            return None
    
    def _execute_storage_change(self, rec: Recommendation) -> tuple[bool, dict]:
        """Execute storage class transition."""
        target_class = self._parse_target_class(rec.recommended_action)
        
        try:
            # Copy object to itself with new storage class
            copy_source = {"Bucket": rec.bucket, "Key": rec.key}
            
            self.s3.copy_object(
                Bucket=rec.bucket,
                Key=rec.key,
                CopySource=copy_source,
                StorageClass=target_class,
                MetadataDirective="COPY",
                TaggingDirective="COPY",
            )
            
            return True, {
                "action": "storage_class_changed",
                "new_class": target_class,
            }
        
        except ClientError as e:
            return False, str(e)
    
    def _execute_multipart_abort(self, rec: Recommendation) -> tuple[bool, dict]:
        """Abort incomplete multipart uploads."""
        try:
            # List uploads for this key
            response = self.s3.list_multipart_uploads(
                Bucket=rec.bucket,
                Prefix=rec.key
            )
            
            uploads = [u for u in response.get("Uploads", []) if u["Key"] == rec.key]
            aborted = 0
            
            for upload in uploads:
                self.s3.abort_multipart_upload(
                    Bucket=rec.bucket,
                    Key=upload["Key"],
                    UploadId=upload["UploadId"]
                )
                aborted += 1
            
            return True, {
                "action": "multipart_aborted",
                "uploads_aborted": aborted,
            }
        
        except ClientError as e:
            return False, str(e)
    
    def _execute_lifecycle_add(self, rec: Recommendation) -> tuple[bool, dict]:
        """Add lifecycle policy to bucket."""
        try:
            # Get existing rules
            existing_rules = []
            try:
                response = self.s3.get_bucket_lifecycle_configuration(Bucket=rec.bucket)
                existing_rules = response.get("Rules", [])
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchLifecycleConfiguration":
                    raise
            
            # Create new rule
            new_rule = {
                "ID": "CostOptimizer-AutoArchive",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Transitions": [
                    {
                        "Days": 90,
                        "StorageClass": "GLACIER_IR"
                    }
                ],
                "AbortIncompleteMultipartUpload": {
                    "DaysAfterInitiation": 7
                }
            }
            
            # Check if similar rule exists
            rule_exists = any(r.get("ID") == "CostOptimizer-AutoArchive" for r in existing_rules)
            
            if rule_exists:
                return True, {
                    "action": "lifecycle_already_exists",
                    "message": "Rule already exists"
                }
            
            # Add new rule
            all_rules = existing_rules + [new_rule]
            
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=rec.bucket,
                LifecycleConfiguration={"Rules": all_rules}
            )
            
            return True, {
                "action": "lifecycle_added",
                "rule_id": "CostOptimizer-AutoArchive",
                "total_rules": len(all_rules),
            }
        
        except ClientError as e:
            return False, str(e)
    
    def _execute_deletion(self, rec: Recommendation) -> tuple[bool, dict]:
        """Delete a stale object. THIS IS IRREVERSIBLE."""
        try:
            # Add a marker tag before deletion for audit
            try:
                self.s3.put_object_tagging(
                    Bucket=rec.bucket,
                    Key=rec.key,
                    Tagging={
                        "TagSet": [
                            {"Key": "CostOptimizer-MarkedForDeletion", "Value": "true"},
                            {"Key": "CostOptimizer-DeletedAt", "Value": datetime.now(timezone.utc).isoformat()},
                        ]
                    }
                )
            except ClientError:
                pass  # Continue even if tagging fails
            
            # Delete the object
            response = self.s3.delete_object(Bucket=rec.bucket, Key=rec.key)
            
            return True, {
                "action": "object_deleted",
                "version_id": response.get("VersionId"),
                "delete_marker": response.get("DeleteMarker", False),
            }
        
        except ClientError as e:
            return False, str(e)
    
    def _execute_version_deletion(self, rec: Recommendation) -> tuple[bool, dict]:
        """Delete an old object version."""
        try:
            # We need the version ID - try to extract from recommendation
            # or list versions to find old ones
            response = self.s3.list_object_versions(
                Bucket=rec.bucket,
                Prefix=rec.key,
                MaxKeys=10
            )
            
            versions = response.get("Versions", [])
            deleted = 0
            
            # Keep the latest, delete the rest
            if len(versions) > 1:
                for version in versions[1:]:  # Skip first (latest)
                    self.s3.delete_object(
                        Bucket=rec.bucket,
                        Key=rec.key,
                        VersionId=version["VersionId"]
                    )
                    deleted += 1
            
            return True, {
                "action": "versions_deleted",
                "versions_deleted": deleted,
            }
        
        except ClientError as e:
            return False, str(e)
    
    def _parse_target_class(self, action: str) -> str:
        """Parse target storage class from action string."""
        action_upper = action.upper()
        
        for storage_class in [
            "DEEP_ARCHIVE", "GLACIER_IR", "GLACIER",
            "INTELLIGENT_TIERING", "STANDARD_IA", "ONEZONE_IA"
        ]:
            if storage_class.replace("_", "") in action_upper.replace("_", "").replace("-", ""):
                return storage_class
        
        return "GLACIER_IR"  # Default
    
    def _default_confirm(self, message: str) -> bool:
        """Default confirmation callback (always False for safety)."""
        print(f"\n⚠️  {message}")
        print("   [Confirmation disabled - skipping]")
        return False
    
    def rollback_batch(self, batch_id: str) -> list:
        """
        Rollback all successful actions from a batch.
        
        Args:
            batch_id: ID of the batch to rollback
            
        Returns:
            List of rollback results
        """
        batch = self.state_tracker.load_batch(batch_id)
        if not batch:
            return []
        
        # Get rollback candidates
        candidates = [
            r for r in batch.records
            if r.rollback_available and r.success
        ]
        
        results = self.rollback_manager.rollback_batch(candidates)
        
        # Update state tracker
        for result in results:
            if result.success:
                self.state_tracker.record_rollback(result.record_id)
        
        return results