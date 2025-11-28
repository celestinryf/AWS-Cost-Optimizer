# models/recommendation.py
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional
from datetime import datetime


class RecommendationType(Enum):
    CHANGE_STORAGE_CLASS = "change_storage_class"
    DELETE_INCOMPLETE_UPLOAD = "delete_incomplete_upload"
    ADD_LIFECYCLE_POLICY = "add_lifecycle_policy"
    DELETE_OLD_VERSION = "delete_old_version"
    DELETE_STALE_OBJECT = "delete_stale_object"


class RiskLevel(Enum):
    LOW = "low"        # Safe to automate
    MEDIUM = "medium"  # Needs review
    HIGH = "high"      # Manual approval required


@dataclass
class Recommendation:
    """Represents a single cost optimization recommendation."""
    
    id: str
    bucket: str
    key: Optional[str]
    recommendation_type: RecommendationType
    risk_level: RiskLevel
    
    current_state: str
    recommended_action: str
    
    estimated_monthly_savings: float
    size_bytes: int
    
    last_accessed: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    storage_class: Optional[str] = None
    
    reason: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["recommendation_type"] = self.recommendation_type.value
        data["risk_level"] = self.risk_level.value
        
        if self.last_accessed:
            data["last_accessed"] = self.last_accessed.isoformat()
        if self.last_modified:
            data["last_modified"] = self.last_modified.isoformat()
            
        return data
    
    def __str__(self) -> str:
        return (
            f"[{self.risk_level.value.upper()}] {self.bucket}/{self.key or ''}: "
            f"{self.recommended_action} (saves ${self.estimated_monthly_savings:.2f}/mo)"
        )