# config.py
# Configuration settings for AWS Cost Optimizer

from dataclasses import dataclass
from typing import Optional

@dataclass
class ScannerConfig:
    # Days since last access to consider object "stale"
    stale_days_threshold: int = 90
    
    # Minimum object size (bytes) to consider for optimization
    # Objects smaller than this aren't worth optimizing
    min_object_size_bytes: int = 1024 * 1024  # 1 MB
    
    # Large object threshold for Intelligent-Tiering recommendation
    large_object_threshold_bytes: int = 128 * 1024  # 128 KB
    
    # Days for incomplete multipart uploads to be flagged
    multipart_age_days: int = 7
    
    # Maximum objects to scan per bucket (None = unlimited)
    max_objects_per_bucket: Optional[int] = 1000
    
    # Skip buckets with these prefixes
    skip_bucket_prefixes: tuple = ("aws-", "elasticbeanstalk-")
    
    # AWS region (None = use default from credentials)
    aws_region: Optional[str] = None


# S3 Storage class pricing (us-east-1, per GB/month)
# Update these based on your region
STORAGE_PRICING = {
    "STANDARD": 0.023,
    "INTELLIGENT_TIERING": 0.023,  # Frequent tier
    "STANDARD_IA": 0.0125,
    "ONEZONE_IA": 0.01,
    "GLACIER_IR": 0.004,
    "GLACIER": 0.0036,
    "DEEP_ARCHIVE": 0.00099,
}

# Potential savings when moving between storage classes
def calculate_monthly_savings(size_bytes: int, from_class: str, to_class: str) -> float:
    """Calculate monthly savings in dollars for moving an object."""
    size_gb = size_bytes / (1024 ** 3)
    from_cost = STORAGE_PRICING.get(from_class, 0.023)
    to_cost = STORAGE_PRICING.get(to_class, 0.023)
    return round((from_cost - to_cost) * size_gb, 4)