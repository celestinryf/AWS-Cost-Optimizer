# analyzers/storage_class.py
"""
Analyzes objects for storage class optimization opportunities.
Recommends moving objects to cheaper storage classes based on access patterns.
"""

import uuid
from datetime import datetime, timezone
from typing import Generator

from config import ScannerConfig, calculate_monthly_savings
from models import Recommendation, RecommendationType, RiskLevel


class StorageClassAnalyzer:
    """Identifies objects that could use a cheaper storage class."""
    
    def __init__(self, config: ScannerConfig):
        self.config = config
    
    def analyze(
        self, 
        bucket: str, 
        obj: dict, 
        days_since_modified: int
    ) -> Generator[Recommendation, None, None]:
        """
        Analyze an object for storage class optimization.
        
        Args:
            bucket: Bucket name
            obj: Object metadata from S3 list_objects_v2
            days_since_modified: Days since object was last modified
        
        Yields:
            Recommendation objects for potential optimizations
        """
        size = obj.get("Size", 0)
        key = obj.get("Key", "")
        storage_class = obj.get("StorageClass", "STANDARD")
        last_modified = obj.get("LastModified")
        
        # Skip small objects - not worth optimizing
        if size < self.config.min_object_size_bytes:
            return
        
        # Skip if already in an optimized storage class
        if storage_class in ("GLACIER", "DEEP_ARCHIVE", "GLACIER_IR"):
            return
        
        # Recommendation: Move to Glacier if not accessed in 90+ days
        if (
            storage_class == "STANDARD" 
            and days_since_modified >= self.config.stale_days_threshold
        ):
            savings = calculate_monthly_savings(size, "STANDARD", "GLACIER_IR")
            
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=key,
                recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
                risk_level=RiskLevel.MEDIUM,
                current_state=f"Storage class: {storage_class}",
                recommended_action=f"Move to GLACIER_IR (not modified in {days_since_modified} days)",
                estimated_monthly_savings=savings,
                size_bytes=size,
                last_modified=last_modified,
                storage_class=storage_class,
                reason=f"Object hasn't been modified in {days_since_modified} days"
            )
        
        # Recommendation: Use Intelligent-Tiering for large objects with unknown access patterns
        elif (
            storage_class == "STANDARD"
            and size >= self.config.large_object_threshold_bytes
            and days_since_modified >= 30
            and days_since_modified < self.config.stale_days_threshold
        ):
            # Intelligent-Tiering has same base cost but auto-moves to cheaper tiers
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=key,
                recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
                risk_level=RiskLevel.LOW,
                current_state=f"Storage class: {storage_class}",
                recommended_action="Move to INTELLIGENT_TIERING for automatic optimization",
                estimated_monthly_savings=0.0,  # Potential savings, not guaranteed
                size_bytes=size,
                last_modified=last_modified,
                storage_class=storage_class,
                reason="Large object with infrequent access pattern - let AWS optimize automatically"
            )