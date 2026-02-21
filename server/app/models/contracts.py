from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendationType(str, Enum):
    CHANGE_STORAGE_CLASS = "change_storage_class"
    ADD_LIFECYCLE_POLICY = "add_lifecycle_policy"
    DELETE_INCOMPLETE_UPLOAD = "delete_incomplete_upload"
    DELETE_STALE_OBJECT = "delete_stale_object"


class ExecutionMode(str, Enum):
    SAFE = "safe"
    STANDARD = "standard"
    FULL = "full"


class RunStatus(str, Enum):
    SCANNED = "scanned"
    SCORED = "scored"
    EXECUTED = "executed"


class Recommendation(BaseModel):
    id: str
    bucket: str
    key: Optional[str] = None
    recommendation_type: RecommendationType
    risk_level: RiskLevel
    reason: str
    recommended_action: str
    estimated_monthly_savings: float = Field(ge=0)
    size_bytes: int = Field(ge=0)
    storage_class: Optional[str] = None
    last_modified: Optional[datetime] = None


class RiskScore(BaseModel):
    recommendation_id: str
    risk_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    requires_approval: bool
    safe_to_automate: bool


class ScanRequest(BaseModel):
    include_buckets: list[str] = Field(default_factory=list)
    exclude_buckets: list[str] = Field(default_factory=list)
    max_objects_per_bucket: int = Field(default=1000, ge=1, le=100000)


class ScanResponse(BaseModel):
    run_id: str
    status: RunStatus
    recommendations: list[Recommendation]
    estimated_monthly_savings: float
    scanned_at: datetime


class ScoreRequest(BaseModel):
    run_id: str


class ScoreResponse(BaseModel):
    run_id: str
    status: RunStatus
    scores: list[RiskScore]
    safe_to_automate: int
    requires_approval: int
    scored_at: datetime


class ExecuteRequest(BaseModel):
    run_id: str
    mode: ExecutionMode = ExecutionMode.SAFE
    dry_run: bool = True


class ExecuteResponse(BaseModel):
    run_id: str
    status: RunStatus
    mode: ExecutionMode
    dry_run: bool
    executed: int
    skipped: int
    failed: int
    executed_at: datetime


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    recommendation_count: int
    estimated_monthly_savings: float
    updated_at: datetime


class RunDetails(BaseModel):
    run_id: str
    status: RunStatus
    recommendations: list[Recommendation]
    scores: list[RiskScore] = Field(default_factory=list)
    execution: Optional[ExecuteResponse] = None
    created_at: datetime
    updated_at: datetime

