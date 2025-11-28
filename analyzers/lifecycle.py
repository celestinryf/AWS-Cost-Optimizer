# analyzers/lifecycle.py
"""
Analyzes buckets for missing or suboptimal lifecycle policies.
"""

import uuid
from typing import Generator, Optional

from config import ScannerConfig
from models import Recommendation, RecommendationType, RiskLevel


class LifecycleAnalyzer:
    """Identifies buckets missing lifecycle policies."""
    
    def __init__(self, config: ScannerConfig):
        self.config = config
    
    def analyze(
        self, 
        bucket: str, 
        lifecycle_rules: Optional[list],
        total_size_bytes: int,
        object_count: int
    ) -> Generator[Recommendation, None, None]:
        """
        Analyze a bucket's lifecycle configuration.
        
        Args:
            bucket: Bucket name
            lifecycle_rules: Current lifecycle rules (None if not configured)
            total_size_bytes: Total size of objects in bucket
            object_count: Number of objects in bucket
        
        Yields:
            Recommendations for lifecycle policy improvements
        """
        # Skip tiny buckets
        if total_size_bytes < 1024 * 1024 * 100:  # 100 MB
            return
        
        has_transition_rule = False
        has_expiration_rule = False
        has_multipart_cleanup = False
        has_version_cleanup = False
        
        if lifecycle_rules:
            for rule in lifecycle_rules:
                if rule.get("Status") != "Enabled":
                    continue
                    
                if rule.get("Transitions"):
                    has_transition_rule = True
                if rule.get("Expiration"):
                    has_expiration_rule = True
                if rule.get("AbortIncompleteMultipartUpload"):
                    has_multipart_cleanup = True
                if rule.get("NoncurrentVersionExpiration"):
                    has_version_cleanup = True
        
        # No lifecycle rules at all
        if not lifecycle_rules:
            size_gb = total_size_bytes / (1024 ** 3)
            # Estimate 10% savings from proper lifecycle management
            estimated_savings = round(size_gb * 0.023 * 0.1, 4)
            
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=None,
                recommendation_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                risk_level=RiskLevel.LOW,
                current_state="No lifecycle policy configured",
                recommended_action="Add lifecycle policy for automatic storage optimization",
                estimated_monthly_savings=estimated_savings,
                size_bytes=total_size_bytes,
                reason=f"Bucket has {object_count} objects ({size_gb:.1f} GB) with no lifecycle management"
            )
            return
        
        # Missing multipart upload cleanup
        if not has_multipart_cleanup:
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=None,
                recommendation_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                risk_level=RiskLevel.LOW,
                current_state="No multipart upload cleanup rule",
                recommended_action="Add AbortIncompleteMultipartUpload rule (7 days)",
                estimated_monthly_savings=0.0,  # Hard to estimate
                size_bytes=0,
                reason="Incomplete multipart uploads waste storage indefinitely"
            )
        
        # Missing transition rules on large bucket
        if not has_transition_rule and total_size_bytes > 1024 * 1024 * 1024:  # 1 GB
            size_gb = total_size_bytes / (1024 ** 3)
            estimated_savings = round(size_gb * 0.023 * 0.3, 4)  # 30% potential
            
            yield Recommendation(
                id=str(uuid.uuid4()),
                bucket=bucket,
                key=None,
                recommendation_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                risk_level=RiskLevel.LOW,
                current_state="No storage class transition rules",
                recommended_action="Add transition rules to move old objects to cheaper storage",
                estimated_monthly_savings=estimated_savings,
                size_bytes=total_size_bytes,
                reason="Large bucket without automatic storage class transitions"
            )