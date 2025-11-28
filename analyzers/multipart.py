# analyzers/multipart.py
"""
Analyzes incomplete multipart uploads that waste storage.
"""

import uuid
from datetime import datetime, timezone
from typing import Generator

from config import ScannerConfig, STORAGE_PRICING
from models import Recommendation, RecommendationType, RiskLevel


class MultipartUploadAnalyzer:
    """Identifies incomplete multipart uploads wasting storage."""
    
    def __init__(self, config: ScannerConfig):
        self.config = config
    
    def analyze(
        self, 
        bucket: str, 
        uploads: list[dict]
    ) -> Generator[Recommendation, None, None]:
        """
        Analyze incomplete multipart uploads.
        
        Args:
            bucket: Bucket name
            uploads: List of incomplete multipart uploads from list_multipart_uploads
        
        Yields:
            Recommendations for cleaning up old uploads
        """
        now = datetime.now(timezone.utc)
        
        for upload in uploads:
            key = upload.get("Key", "")
            upload_id = upload.get("UploadId", "")
            initiated = upload.get("Initiated")
            
            if not initiated:
                continue
            
            days_old = (now - initiated).days
            
            if days_old >= self.config.multipart_age_days:
                yield Recommendation(
                    id=str(uuid.uuid4()),
                    bucket=bucket,
                    key=key,
                    recommendation_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
                    risk_level=RiskLevel.LOW,  # Safe to delete incomplete uploads
                    current_state=f"Incomplete multipart upload started {days_old} days ago",
                    recommended_action=f"Abort incomplete upload (ID: {upload_id[:8]}...)",
                    estimated_monthly_savings=0.01,  # Estimate, hard to know actual size
                    size_bytes=0,  # Unknown until we list parts
                    last_modified=initiated,
                    reason=f"Multipart upload has been incomplete for {days_old} days"
                )
    
    def analyze_with_parts(
        self, 
        bucket: str, 
        upload: dict,
        parts: list[dict]
    ) -> Generator[Recommendation, None, None]:
        """
        Analyze a specific multipart upload with its parts for accurate sizing.
        
        Args:
            bucket: Bucket name
            upload: Multipart upload metadata
            parts: List of uploaded parts
        
        Yields:
            Recommendation with accurate size information
        """
        now = datetime.now(timezone.utc)
        
        key = upload.get("Key", "")
        upload_id = upload.get("UploadId", "")
        initiated = upload.get("Initiated")
        
        if not initiated:
            return
        
        days_old = (now - initiated).days
        
        if days_old >= self.config.multipart_age_days:
            total_size = sum(part.get("Size", 0) for part in parts)
            size_gb = total_size / (1024 ** 3)
            monthly_cost = STORAGE_PRICING["STANDARD"] * size_gb
            
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=key,
                recommendation_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
                risk_level=RiskLevel.LOW,
                current_state=f"Incomplete upload: {len(parts)} parts, {total_size / (1024*1024):.1f} MB",
                recommended_action=f"Abort incomplete upload (ID: {upload_id[:8]}...)",
                estimated_monthly_savings=round(monthly_cost, 4),
                size_bytes=total_size,
                last_modified=initiated,
                reason=f"Incomplete upload wasting {total_size / (1024*1024):.1f} MB for {days_old} days"
            )