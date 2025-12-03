# executor/validator.py
"""
Pre-execution validation to ensure changes are safe.

Performs additional checks before any action is executed:
- Validates current state matches expected state
- Checks for conflicting operations
- Ensures rollback capability
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from models import Recommendation, RecommendationType


class ValidationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class ValidationResult:
    """Result of pre-execution validation."""
    
    recommendation_id: str
    status: ValidationStatus
    
    checks_passed: list[str]
    checks_failed: list[str]
    warnings: list[str]
    
    # Is it safe to proceed?
    safe_to_execute: bool
    
    # Current state snapshot (for rollback reference)
    state_snapshot: dict
    
    validated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "status": self.status.value,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "warnings": self.warnings,
            "safe_to_execute": self.safe_to_execute,
            "state_snapshot": self.state_snapshot,
            "validated_at": self.validated_at.isoformat(),
        }


class PreExecutionValidator:
    """
    Validates recommendations immediately before execution.
    
    This is the last safety check before making changes.
    """
    
    def __init__(self, region: Optional[str] = None):
        self.s3 = boto3.client("s3", region_name=region)
    
    def validate(self, rec: Recommendation) -> ValidationResult:
        """
        Run all validation checks for a recommendation.
        
        Returns ValidationResult with pass/fail status.
        """
        checks_passed = []
        checks_failed = []
        warnings = []
        state_snapshot = {}
        
        # Run type-specific validation
        if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            result = self._validate_storage_change(rec)
        elif rec.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            result = self._validate_multipart_abort(rec)
        elif rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
            result = self._validate_lifecycle_add(rec)
        elif rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            result = self._validate_deletion(rec)
        else:
            result = {
                "passed": [],
                "failed": ["Unknown recommendation type"],
                "warnings": [],
                "snapshot": {},
                "safe": False,
            }
        
        checks_passed = result["passed"]
        checks_failed = result["failed"]
        warnings = result["warnings"]
        state_snapshot = result["snapshot"]
        safe = result["safe"]
        
        # Determine overall status
        if checks_failed:
            status = ValidationStatus.FAILED
        elif warnings:
            status = ValidationStatus.WARNING
        else:
            status = ValidationStatus.PASSED
        
        return ValidationResult(
            recommendation_id=rec.id,
            status=status,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            warnings=warnings,
            safe_to_execute=safe,
            state_snapshot=state_snapshot,
        )
    
    def _validate_storage_change(self, rec: Recommendation) -> dict:
        """Validate storage class change is safe."""
        passed = []
        failed = []
        warnings = []
        snapshot = {}
        
        try:
            # Get current object state
            response = self.s3.head_object(Bucket=rec.bucket, Key=rec.key)
            
            snapshot = {
                "bucket": rec.bucket,
                "key": rec.key,
                "storage_class": response.get("StorageClass", "STANDARD"),
                "size": response.get("ContentLength"),
                "etag": response.get("ETag"),
                "last_modified": response.get("LastModified").isoformat() if response.get("LastModified") else None,
            }
            
            passed.append("Object exists")
            
            # Check size hasn't changed dramatically
            current_size = response.get("ContentLength", 0)
            if rec.size_bytes > 0:
                size_diff = abs(current_size - rec.size_bytes) / rec.size_bytes
                if size_diff > 0.1:  # >10% change
                    warnings.append(f"Object size changed by {size_diff*100:.1f}%")
                else:
                    passed.append("Object size consistent")
            
            # Check not already in target class
            current_class = response.get("StorageClass", "STANDARD")
            if "GLACIER" in current_class.upper():
                failed.append(f"Already in archival storage: {current_class}")
            else:
                passed.append(f"Current storage class eligible: {current_class}")
            
            # Check object isn't locked
            try:
                lock = self.s3.get_object_retention(Bucket=rec.bucket, Key=rec.key)
                if lock.get("Retention"):
                    failed.append("Object has retention lock")
            except ClientError as e:
                if e.response["Error"]["Code"] != "ObjectLockConfigurationNotFoundError":
                    passed.append("No object lock")
            
            safe = len(failed) == 0
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                failed.append("Object no longer exists")
            else:
                failed.append(f"Access error: {e.response['Error']['Code']}")
            safe = False
        
        return {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "snapshot": snapshot,
            "safe": safe,
        }
    
    def _validate_multipart_abort(self, rec: Recommendation) -> dict:
        """Validate multipart upload can be aborted."""
        passed = []
        failed = []
        warnings = []
        snapshot = {}
        
        try:
            response = self.s3.list_multipart_uploads(
                Bucket=rec.bucket, 
                Prefix=rec.key
            )
            uploads = [u for u in response.get("Uploads", []) if u["Key"] == rec.key]
            
            if not uploads:
                failed.append("No incomplete uploads found for this key")
                safe = False
            else:
                snapshot = {
                    "bucket": rec.bucket,
                    "key": rec.key,
                    "upload_ids": [u["UploadId"] for u in uploads],
                    "initiated": [u["Initiated"].isoformat() for u in uploads],
                }
                passed.append(f"Found {len(uploads)} incomplete upload(s)")
                safe = True
                
        except ClientError as e:
            failed.append(f"Access error: {e.response['Error']['Code']}")
            safe = False
        
        return {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "snapshot": snapshot,
            "safe": safe,
        }
    
    def _validate_lifecycle_add(self, rec: Recommendation) -> dict:
        """Validate lifecycle policy can be added."""
        passed = []
        failed = []
        warnings = []
        snapshot = {"bucket": rec.bucket, "existing_rules": []}
        
        try:
            # Check bucket exists and we have access
            self.s3.head_bucket(Bucket=rec.bucket)
            passed.append("Bucket exists and accessible")
            
            # Get existing lifecycle
            try:
                response = self.s3.get_bucket_lifecycle_configuration(Bucket=rec.bucket)
                existing_rules = response.get("Rules", [])
                snapshot["existing_rules"] = [
                    {"id": r.get("ID"), "status": r.get("Status")} 
                    for r in existing_rules
                ]
                
                if existing_rules:
                    warnings.append(f"Bucket has {len(existing_rules)} existing rules")
                    
                passed.append("Can read lifecycle configuration")
                
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
                    passed.append("No existing lifecycle - clean slate")
                else:
                    raise
            
            safe = len(failed) == 0
            
        except ClientError as e:
            failed.append(f"Bucket access error: {e.response['Error']['Code']}")
            safe = False
        
        return {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "snapshot": snapshot,
            "safe": safe,
        }
    
    def _validate_deletion(self, rec: Recommendation) -> dict:
        """Validate object deletion is safe."""
        passed = []
        failed = []
        warnings = []
        snapshot = {}
        
        # Deletions always require extra scrutiny
        warnings.append("⚠️ DELETION IS PERMANENT AND IRREVERSIBLE")
        
        try:
            response = self.s3.head_object(Bucket=rec.bucket, Key=rec.key)
            
            snapshot = {
                "bucket": rec.bucket,
                "key": rec.key,
                "size": response.get("ContentLength"),
                "storage_class": response.get("StorageClass", "STANDARD"),
                "etag": response.get("ETag"),
                "last_modified": response.get("LastModified").isoformat() if response.get("LastModified") else None,
            }
            
            passed.append("Object exists")
            
            # Check for object lock
            try:
                lock = self.s3.get_object_retention(Bucket=rec.bucket, Key=rec.key)
                if lock.get("Retention"):
                    failed.append("Object has retention lock - cannot delete")
            except ClientError:
                passed.append("No retention lock")
            
            # Check for legal hold
            try:
                hold = self.s3.get_object_legal_hold(Bucket=rec.bucket, Key=rec.key)
                if hold.get("LegalHold", {}).get("Status") == "ON":
                    failed.append("Object has legal hold - cannot delete")
            except ClientError:
                passed.append("No legal hold")
            
            # Require explicit approval for large objects
            size = response.get("ContentLength", 0)
            if size > 1024 * 1024 * 1024:  # > 1 GB
                warnings.append(f"Large object: {size / (1024**3):.2f} GB")
            
            safe = len(failed) == 0
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                passed.append("Object already deleted - no action needed")
                safe = False  # Nothing to do
            else:
                failed.append(f"Access error: {e.response['Error']['Code']}")
                safe = False
        
        return {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "snapshot": snapshot,
            "safe": safe,
        }
    
    def validate_batch(self, recommendations: list[Recommendation]) -> list[ValidationResult]:
        """Validate a batch of recommendations."""
        return [self.validate(rec) for rec in recommendations]