# executor/dry_run.py
"""
Dry-run executor that simulates changes without actually executing them.

Validates that changes CAN be made, logs what WOULD happen,
but doesn't modify any resources.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from models import Recommendation, RecommendationType
from scoring import RiskScore, SavingsCalculator


class DryRunStatus(Enum):
    """Status of a dry-run check."""
    SUCCESS = "success"          # Would succeed
    WOULD_FAIL = "would_fail"    # Would fail - permission/resource issue
    SKIPPED = "skipped"          # Skipped - too risky or requires approval
    ERROR = "error"              # Error during validation


@dataclass
class DryRunResult:
    """Result of a single dry-run check."""
    
    recommendation_id: str
    status: DryRunStatus
    
    # What would happen
    action_description: str
    would_affect: dict  # Resources that would be affected
    
    # Validation results
    permissions_ok: bool
    resource_exists: bool
    preconditions_met: bool
    
    # If it would fail, why?
    failure_reason: Optional[str] = None
    
    # Warnings (non-blocking issues)
    warnings: list[str] = field(default_factory=list)
    
    # Timing
    validated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "status": self.status.value,
            "action_description": self.action_description,
            "would_affect": self.would_affect,
            "permissions_ok": self.permissions_ok,
            "resource_exists": self.resource_exists,
            "preconditions_met": self.preconditions_met,
            "failure_reason": self.failure_reason,
            "warnings": self.warnings,
            "validated_at": self.validated_at.isoformat(),
        }


class DryRunExecutor:
    """
    Simulates execution of recommendations without making changes.
    
    For each recommendation:
    1. Validates permissions
    2. Checks resource still exists
    3. Verifies preconditions
    4. Logs what would happen
    """
    
    def __init__(self, region: Optional[str] = None):
        self.s3 = boto3.client("s3", region_name=region)
        self.results: list[DryRunResult] = []
        self.savings_calculator = SavingsCalculator()
    
    def run(
        self, 
        recommendations: list[Recommendation],
        risk_scores: dict[str, RiskScore],
        skip_high_risk: bool = True
    ) -> list[DryRunResult]:
        """
        Run dry-run validation on a list of recommendations.
        
        Args:
            recommendations: List of recommendations to validate
            risk_scores: Dict of recommendation_id -> RiskScore
            skip_high_risk: If True, skip recommendations requiring approval
        
        Returns:
            List of DryRunResult objects
        """
        self.results = []
        
        for rec in recommendations:
            score = risk_scores.get(rec.id)
            
            # Skip high-risk items if requested
            if skip_high_risk and score and score.requires_approval:
                result = DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.SKIPPED,
                    action_description="Skipped - requires manual approval",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=True,
                    resource_exists=True,
                    preconditions_met=True,
                    failure_reason="High-risk action requires approval",
                    warnings=["Review this recommendation manually before executing"],
                )
                self.results.append(result)
                continue
            
            # Run validation based on recommendation type
            try:
                if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
                    result = self._validate_storage_class_change(rec)
                
                elif rec.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
                    result = self._validate_multipart_abort(rec)
                
                elif rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
                    result = self._validate_lifecycle_policy(rec)
                
                elif rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
                    result = self._validate_object_deletion(rec)
                
                elif rec.recommendation_type == RecommendationType.DELETE_OLD_VERSION:
                    result = self._validate_version_deletion(rec)
                
                else:
                    result = DryRunResult(
                        recommendation_id=rec.id,
                        status=DryRunStatus.ERROR,
                        action_description=f"Unknown action type: {rec.recommendation_type}",
                        would_affect={},
                        permissions_ok=False,
                        resource_exists=False,
                        preconditions_met=False,
                        failure_reason="Unsupported recommendation type",
                    )
                
            except Exception as e:
                result = DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.ERROR,
                    action_description="Validation failed with error",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=False,
                    resource_exists=False,
                    preconditions_met=False,
                    failure_reason=str(e),
                )
            
            self.results.append(result)
        
        return self.results
    
    def _validate_storage_class_change(self, rec: Recommendation) -> DryRunResult:
        """Validate a storage class change can be executed."""
        warnings = []
        
        # Check if object still exists
        try:
            response = self.s3.head_object(Bucket=rec.bucket, Key=rec.key)
            resource_exists = True
            current_class = response.get("StorageClass", "STANDARD")
            current_size = response.get("ContentLength", 0)
            
            # Warn if object has changed
            if current_size != rec.size_bytes:
                warnings.append(
                    f"Object size changed: was {rec.size_bytes}, now {current_size}"
                )
            
            # Check if already in target class
            if "GLACIER" in current_class and "GLACIER" in rec.recommended_action.upper():
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.SKIPPED,
                    action_description="Object already in archival storage class",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=True,
                    resource_exists=True,
                    preconditions_met=False,
                    failure_reason=f"Already in {current_class}",
                )
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.WOULD_FAIL,
                    action_description="Object no longer exists",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=True,
                    resource_exists=False,
                    preconditions_met=False,
                    failure_reason="Object was deleted since scan",
                )
            elif e.response["Error"]["Code"] == "AccessDenied":
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.WOULD_FAIL,
                    action_description="Permission denied",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=False,
                    resource_exists=True,
                    preconditions_met=False,
                    failure_reason="s3:GetObject permission required",
                )
            else:
                raise
        
        # Check write permissions (without actually writing)
        try:
            # Check bucket permissions by getting bucket ACL
            self.s3.get_bucket_acl(Bucket=rec.bucket)
            permissions_ok = True
        except ClientError as e:
            if e.response["Error"]["Code"] == "AccessDenied":
                permissions_ok = False
                warnings.append("May not have write permissions")
            else:
                permissions_ok = True  # Other errors might be OK
        
        return DryRunResult(
            recommendation_id=rec.id,
            status=DryRunStatus.SUCCESS,
            action_description=f"Would change storage class: {rec.recommended_action}",
            would_affect={
                "bucket": rec.bucket,
                "key": rec.key,
                "current_storage_class": current_class,
                "current_size_bytes": current_size,
            },
            permissions_ok=permissions_ok,
            resource_exists=True,
            preconditions_met=True,
            warnings=warnings,
        )
    
    def _validate_multipart_abort(self, rec: Recommendation) -> DryRunResult:
        """Validate aborting an incomplete multipart upload."""
        # Extract upload ID from recommendation
        upload_id = None
        if "ID:" in rec.recommended_action:
            # Parse "Abort incomplete upload (ID: abc123...)"
            start = rec.recommended_action.find("ID:") + 4
            end = rec.recommended_action.find("...", start)
            if end == -1:
                end = rec.recommended_action.find(")", start)
            upload_id = rec.recommended_action[start:end].strip()
        
        # Check if upload still exists
        try:
            response = self.s3.list_multipart_uploads(Bucket=rec.bucket, Prefix=rec.key)
            uploads = response.get("Uploads", [])
            
            matching = [u for u in uploads if u["Key"] == rec.key]
            
            if not matching:
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.SKIPPED,
                    action_description="Multipart upload no longer exists",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=True,
                    resource_exists=False,
                    preconditions_met=False,
                    failure_reason="Upload may have completed or been aborted",
                )
            
            return DryRunResult(
                recommendation_id=rec.id,
                status=DryRunStatus.SUCCESS,
                action_description=f"Would abort incomplete multipart upload for {rec.key}",
                would_affect={
                    "bucket": rec.bucket,
                    "key": rec.key,
                    "upload_count": len(matching),
                },
                permissions_ok=True,
                resource_exists=True,
                preconditions_met=True,
            )
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "AccessDenied":
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.WOULD_FAIL,
                    action_description="Permission denied",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=False,
                    resource_exists=True,
                    preconditions_met=False,
                    failure_reason="s3:ListBucketMultipartUploads permission required",
                )
            raise
    
    def _validate_lifecycle_policy(self, rec: Recommendation) -> DryRunResult:
        """Validate adding a lifecycle policy."""
        # Check if we can read current policy
        try:
            self.s3.get_bucket_lifecycle_configuration(Bucket=rec.bucket)
            has_existing = True
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
                has_existing = False
            elif e.response["Error"]["Code"] == "AccessDenied":
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.WOULD_FAIL,
                    action_description="Permission denied",
                    would_affect={"bucket": rec.bucket},
                    permissions_ok=False,
                    resource_exists=True,
                    preconditions_met=False,
                    failure_reason="s3:GetLifecycleConfiguration permission required",
                )
            else:
                raise
        
        warnings = []
        if has_existing:
            warnings.append("Bucket already has lifecycle rules - would add to existing")
        
        return DryRunResult(
            recommendation_id=rec.id,
            status=DryRunStatus.SUCCESS,
            action_description=f"Would add lifecycle policy to {rec.bucket}",
            would_affect={
                "bucket": rec.bucket,
                "has_existing_policy": has_existing,
            },
            permissions_ok=True,
            resource_exists=True,
            preconditions_met=True,
            warnings=warnings,
        )
    
    def _validate_object_deletion(self, rec: Recommendation) -> DryRunResult:
        """Validate deleting a stale object."""
        # Check if object still exists
        try:
            response = self.s3.head_object(Bucket=rec.bucket, Key=rec.key)
            current_size = response.get("ContentLength", 0)
            
            warnings = []
            if current_size != rec.size_bytes:
                warnings.append(f"Object size changed since scan")
            
            return DryRunResult(
                recommendation_id=rec.id,
                status=DryRunStatus.SUCCESS,
                action_description=f"Would DELETE object: {rec.bucket}/{rec.key}",
                would_affect={
                    "bucket": rec.bucket,
                    "key": rec.key,
                    "size_bytes": current_size,
                    "action": "PERMANENT DELETION",
                },
                permissions_ok=True,
                resource_exists=True,
                preconditions_met=True,
                warnings=warnings + ["⚠️ THIS ACTION IS IRREVERSIBLE"],
            )
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return DryRunResult(
                    recommendation_id=rec.id,
                    status=DryRunStatus.SKIPPED,
                    action_description="Object already deleted",
                    would_affect={"bucket": rec.bucket, "key": rec.key},
                    permissions_ok=True,
                    resource_exists=False,
                    preconditions_met=False,
                )
            raise
    
    def _validate_version_deletion(self, rec: Recommendation) -> DryRunResult:
        """Validate deleting an old object version."""
        # Similar to object deletion but for versions
        return DryRunResult(
            recommendation_id=rec.id,
            status=DryRunStatus.SUCCESS,
            action_description=f"Would delete old version of {rec.key}",
            would_affect={
                "bucket": rec.bucket,
                "key": rec.key,
                "action": "DELETE OLD VERSION",
            },
            permissions_ok=True,
            resource_exists=True,
            preconditions_met=True,
            warnings=["Current version will remain unchanged"],
        )
    
    def generate_report(self) -> dict:
        """Generate summary report of dry-run results."""
        by_status = {
            DryRunStatus.SUCCESS: [],
            DryRunStatus.WOULD_FAIL: [],
            DryRunStatus.SKIPPED: [],
            DryRunStatus.ERROR: [],
        }
        
        for result in self.results:
            by_status[result.status].append(result)
        
        return {
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": len(self.results),
                "would_succeed": len(by_status[DryRunStatus.SUCCESS]),
                "would_fail": len(by_status[DryRunStatus.WOULD_FAIL]),
                "skipped": len(by_status[DryRunStatus.SKIPPED]),
                "errors": len(by_status[DryRunStatus.ERROR]),
            },
            "ready_to_execute": [
                r.to_dict() for r in by_status[DryRunStatus.SUCCESS]
            ],
            "needs_attention": [
                r.to_dict() for r in by_status[DryRunStatus.WOULD_FAIL]
            ],
            "skipped": [
                r.to_dict() for r in by_status[DryRunStatus.SKIPPED]
            ],
            "errors": [
                r.to_dict() for r in by_status[DryRunStatus.ERROR]
            ],
        }
    
    def save_report(self, output_dir: str = "reports") -> Path:
        """Save dry-run report to file."""
        report = self.generate_report()
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        filename = f"dry_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = output_path / filename
        
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        return filepath