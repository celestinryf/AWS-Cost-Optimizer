# executor/rollback.py
"""
Rollback manager for reverting executed changes.

Supports rolling back:
- Storage class changes (copy back to original class)
- Lifecycle policy additions (remove added rules)
- Object tagging changes

Does NOT support rolling back:
- Deletions (data is gone)
- Multipart upload aborts (upload is gone)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from .state_tracker import ExecutionRecord, StateSnapshot, ExecutionStatus


class RollbackStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"
    ALREADY_ROLLED_BACK = "already_rolled_back"


@dataclass
class RollbackResult:
    """Result of a rollback attempt."""
    
    record_id: str
    status: RollbackStatus
    
    action_taken: str
    
    success: bool
    error_message: Optional[str] = None
    
    rolled_back_at: datetime = None
    
    def __post_init__(self):
        if self.rolled_back_at is None:
            self.rolled_back_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "status": self.status.value,
            "action_taken": self.action_taken,
            "success": self.success,
            "error_message": self.error_message,
            "rolled_back_at": self.rolled_back_at.isoformat(),
        }


class RollbackManager:
    """
    Manages rollback of executed actions.
    
    Uses pre-state snapshots to restore original state.
    """
    
    def __init__(self, region: Optional[str] = None):
        self.s3 = boto3.client("s3", region_name=region)
    
    def rollback(self, record: ExecutionRecord) -> RollbackResult:
        """
        Attempt to rollback a single execution record.
        
        Args:
            record: The execution record to rollback
            
        Returns:
            RollbackResult indicating success or failure
        """
        # Check if rollback is possible
        if not record.rollback_available:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.NOT_AVAILABLE,
                action_taken="None - rollback not available for this action type",
                success=False,
                error_message="This action type cannot be rolled back",
            )
        
        if record.status == ExecutionStatus.ROLLED_BACK:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.ALREADY_ROLLED_BACK,
                action_taken="None - already rolled back",
                success=False,
                error_message="Action was already rolled back",
            )
        
        if not record.success:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.NOT_AVAILABLE,
                action_taken="None - original action failed",
                success=False,
                error_message="Original action failed, nothing to rollback",
            )
        
        # Dispatch to appropriate rollback handler
        if record.action_type == "change_storage_class":
            return self._rollback_storage_class(record)
        elif record.action_type == "add_lifecycle_policy":
            return self._rollback_lifecycle_policy(record)
        elif record.action_type == "add_tags":
            return self._rollback_tags(record)
        else:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.NOT_AVAILABLE,
                action_taken=f"None - no rollback handler for {record.action_type}",
                success=False,
                error_message=f"No rollback handler for action type: {record.action_type}",
            )
    
    def _rollback_storage_class(self, record: ExecutionRecord) -> RollbackResult:
        """
        Rollback a storage class change by copying object back to original class.
        
        Note: This creates a new copy - the original versioned object may still exist.
        """
        if not record.pre_state:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.FAILED,
                action_taken="Cannot rollback - no pre-state snapshot",
                success=False,
                error_message="Pre-state snapshot not available",
            )
        
        pre_state = record.pre_state
        original_class = pre_state.storage_class or "STANDARD"
        
        try:
            # Copy object to itself with original storage class
            # This is the standard way to change storage class in S3
            copy_source = {
                "Bucket": record.bucket,
                "Key": record.key,
            }
            
            self.s3.copy_object(
                Bucket=record.bucket,
                Key=record.key,
                CopySource=copy_source,
                StorageClass=original_class,
                MetadataDirective="COPY",  # Preserve metadata
                TaggingDirective="COPY",   # Preserve tags
            )
            
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.SUCCESS,
                action_taken=f"Restored storage class to {original_class}",
                success=True,
            )
            
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            
            # Handle Glacier retrieval requirement
            if error_code == "InvalidObjectState":
                return RollbackResult(
                    record_id=record.id,
                    status=RollbackStatus.FAILED,
                    action_taken="Rollback failed - object in Glacier",
                    success=False,
                    error_message="Object is in Glacier. Initiate restore first, then retry rollback.",
                )
            
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.FAILED,
                action_taken=f"Rollback failed: {error_code}",
                success=False,
                error_message=str(e),
            )
    
    def _rollback_lifecycle_policy(self, record: ExecutionRecord) -> RollbackResult:
        """
        Rollback lifecycle policy addition by removing added rules.
        """
        if not record.pre_state:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.FAILED,
                action_taken="Cannot rollback - no pre-state snapshot",
                success=False,
                error_message="Pre-state snapshot not available",
            )
        
        try:
            # Get current lifecycle configuration
            try:
                response = self.s3.get_bucket_lifecycle_configuration(Bucket=record.bucket)
                current_rules = response.get("Rules", [])
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
                    # Already no lifecycle - nothing to rollback
                    return RollbackResult(
                        record_id=record.id,
                        status=RollbackStatus.SUCCESS,
                        action_taken="Lifecycle already removed",
                        success=True,
                    )
                raise
            
            # If there were no original rules, delete the entire lifecycle config
            original_rules = record.pre_state.metadata.get("lifecycle_rules", [])
            
            if not original_rules:
                self.s3.delete_bucket_lifecycle(Bucket=record.bucket)
                return RollbackResult(
                    record_id=record.id,
                    status=RollbackStatus.SUCCESS,
                    action_taken="Removed lifecycle configuration",
                    success=True,
                )
            
            # Otherwise, restore original rules
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=record.bucket,
                LifecycleConfiguration={"Rules": original_rules}
            )
            
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.SUCCESS,
                action_taken=f"Restored {len(original_rules)} original lifecycle rules",
                success=True,
            )
            
        except ClientError as e:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.FAILED,
                action_taken="Rollback failed",
                success=False,
                error_message=str(e),
            )
    
    def _rollback_tags(self, record: ExecutionRecord) -> RollbackResult:
        """
        Rollback tag changes by restoring original tags.
        """
        if not record.pre_state:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.FAILED,
                action_taken="Cannot rollback - no pre-state snapshot",
                success=False,
                error_message="Pre-state snapshot not available",
            )
        
        try:
            original_tags = record.pre_state.tags or {}
            
            if not original_tags:
                # Delete all tags
                self.s3.delete_object_tagging(
                    Bucket=record.bucket,
                    Key=record.key,
                )
                return RollbackResult(
                    record_id=record.id,
                    status=RollbackStatus.SUCCESS,
                    action_taken="Removed all tags",
                    success=True,
                )
            
            # Restore original tags
            tag_set = [{"Key": k, "Value": v} for k, v in original_tags.items()]
            self.s3.put_object_tagging(
                Bucket=record.bucket,
                Key=record.key,
                Tagging={"TagSet": tag_set}
            )
            
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.SUCCESS,
                action_taken=f"Restored {len(original_tags)} original tags",
                success=True,
            )
            
        except ClientError as e:
            return RollbackResult(
                record_id=record.id,
                status=RollbackStatus.FAILED,
                action_taken="Rollback failed",
                success=False,
                error_message=str(e),
            )
    
    def rollback_batch(
        self, 
        records: list[ExecutionRecord],
        stop_on_failure: bool = False
    ) -> list[RollbackResult]:
        """
        Rollback multiple records.
        
        Args:
            records: List of execution records to rollback
            stop_on_failure: If True, stop on first failure
            
        Returns:
            List of rollback results
        """
        results = []
        
        for record in records:
            result = self.rollback(record)
            results.append(result)
            
            if stop_on_failure and not result.success:
                break
        
        return results
    
    def initiate_glacier_restore(
        self,
        bucket: str,
        key: str,
        days: int = 7,
        tier: str = "Standard"
    ) -> dict:
        """
        Initiate restore of an object from Glacier.
        
        Required before rollback of Glacier transitions.
        
        Args:
            bucket: Bucket name
            key: Object key
            days: Number of days to keep restored copy
            tier: Retrieval tier (Expedited, Standard, Bulk)
            
        Returns:
            Dict with restore status
        """
        try:
            self.s3.restore_object(
                Bucket=bucket,
                Key=key,
                RestoreRequest={
                    "Days": days,
                    "GlacierJobParameters": {
                        "Tier": tier
                    }
                }
            )
            
            return {
                "success": True,
                "message": f"Restore initiated. Object will be available in Glacier {tier} retrieval time.",
                "retrieval_tier": tier,
                "available_days": days,
            }
            
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            
            if error_code == "RestoreAlreadyInProgress":
                return {
                    "success": True,
                    "message": "Restore already in progress",
                    "retrieval_tier": tier,
                }
            
            return {
                "success": False,
                "message": str(e),
                "error_code": error_code,
            }