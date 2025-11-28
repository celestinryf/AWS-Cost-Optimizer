# analyzers/access_patterns.py
"""
Analyzes object access patterns to identify stale/unused objects.
"""

import uuid
from datetime import datetime, timezone
from typing import Generator

from config import ScannerConfig, STORAGE_PRICING
from models import Recommendation, RecommendationType, RiskLevel


class AccessPatternAnalyzer:
    """Identifies objects that appear unused based on modification dates."""
    
    def __init__(self, config: ScannerConfig):
        self.config = config
    
    def analyze(
        self, 
        bucket: str, 
        obj: dict, 
        days_since_modified: int
    ) -> Generator[Recommendation, None, None]:
        """
        Analyze an object for potential deletion based on age.
        
        Args:
            bucket: Bucket name
            obj: Object metadata from S3 list_objects_v2
            days_since_modified: Days since object was last modified
        
        Yields:
            Recommendation objects for stale objects
        """
        size = obj.get("Size", 0)
        key = obj.get("Key", "")
        storage_class = obj.get("StorageClass", "STANDARD")
        last_modified = obj.get("LastModified")
        
        # Flag very old objects (1+ year) for potential deletion
        if days_since_modified >= 365:
            size_gb = size / (1024 ** 3)
            monthly_cost = STORAGE_PRICING.get(storage_class, 0.023) * size_gb
            
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=key,
                recommendation_type=RecommendationType.DELETE_STALE_OBJECT,
                risk_level=RiskLevel.HIGH,  # Deletion is risky
                current_state=f"Last modified: {days_since_modified} days ago",
                recommended_action=f"Review for deletion (not modified in {days_since_modified} days)",
                estimated_monthly_savings=round(monthly_cost, 4),
                size_bytes=size,
                last_modified=last_modified,
                storage_class=storage_class,
                reason=f"Object hasn't been modified in over a year ({days_since_modified} days)"
            )
    
    def analyze_prefix_patterns(
        self, 
        bucket: str, 
        objects: list[dict]
    ) -> Generator[Recommendation, None, None]:
        """
        Analyze groups of objects by prefix to find stale directories.
        
        Args:
            bucket: Bucket name
            objects: List of object metadata
        
        Yields:
            Recommendations for stale prefixes
        """
        # Group objects by top-level prefix
        prefixes: dict[str, dict] = {}
        
        for obj in objects:
            key = obj.get("Key", "")
            prefix = key.split("/")[0] if "/" in key else ""
            
            if prefix:
                if prefix not in prefixes:
                    prefixes[prefix] = {
                        "count": 0,
                        "total_size": 0,
                        "newest_modified": None
                    }
                
                prefixes[prefix]["count"] += 1
                prefixes[prefix]["total_size"] += obj.get("Size", 0)
                
                modified = obj.get("LastModified")
                if modified:
                    if (
                        prefixes[prefix]["newest_modified"] is None 
                        or modified > prefixes[prefix]["newest_modified"]
                    ):
                        prefixes[prefix]["newest_modified"] = modified
        
        # Flag prefixes where newest object is over 180 days old
        now = datetime.now(timezone.utc)
        for prefix, data in prefixes.items():
            if data["newest_modified"]:
                days_old = (now - data["newest_modified"]).days
                if days_old >= 180 and data["count"] >= 10:
                    size_gb = data["total_size"] / (1024 ** 3)
                    monthly_cost = 0.023 * size_gb  # Assume STANDARD
                    
                    yield Recommendation(
                        id=str(uuid.uuid4()),
                        bucket=bucket,
                        key=f"{prefix}/",
                        recommendation_type=RecommendationType.DELETE_STALE_OBJECT,
                        risk_level=RiskLevel.HIGH,
                        current_state=f"Prefix with {data['count']} objects, none modified in {days_old} days",
                        recommended_action=f"Review entire '{prefix}/' prefix for deletion",
                        estimated_monthly_savings=round(monthly_cost, 4),
                        size_bytes=data["total_size"],
                        last_modified=data["newest_modified"],
                        reason=f"All {data['count']} objects in this prefix are over {days_old} days old"
                    )