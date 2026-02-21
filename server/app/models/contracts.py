from datetime import datetime
from enum import Enum
from typing import Any, Optional

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
    DRY_RUN = "dry_run"
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


class RiskFactorScores(BaseModel):
    reversibility: int = Field(ge=0, le=100)
    data_loss_risk: int = Field(ge=0, le=100)
    age_confidence: int = Field(ge=0, le=100)
    size_impact: int = Field(ge=0, le=100)
    access_confidence: int = Field(ge=0, le=100)


class RiskScore(BaseModel):
    recommendation_id: str
    risk_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    impact_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    requires_approval: bool
    safe_to_automate: bool
    execution_recommendation: str
    factors: list[str] = Field(default_factory=list)
    factor_scores: RiskFactorScores


class SavingsEstimate(BaseModel):
    recommendation_id: str
    current_monthly_cost: float = Field(ge=0)
    projected_monthly_cost: float = Field(ge=0)
    monthly_savings: float = Field(ge=0)
    transition_cost: float = Field(ge=0)
    minimum_duration_risk: float = Field(ge=0)
    net_first_month: float
    net_annual_savings: float
    break_even_days: Optional[int] = Field(default=None, ge=0)
    estimate_confidence: str
    assumptions: list[str] = Field(default_factory=list)


class SavingsSummary(BaseModel):
    total_monthly_savings: float = Field(ge=0)
    total_annual_savings: float
    total_transition_costs: float = Field(ge=0)
    net_first_month: float
    high_confidence_count: int = Field(ge=0)
    medium_confidence_count: int = Field(ge=0)
    low_confidence_count: int = Field(ge=0)


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
    savings_details: list[SavingsEstimate]
    savings_summary: SavingsSummary
    safe_to_automate: int
    requires_approval: int
    scored_at: datetime


class ExecuteRequest(BaseModel):
    run_id: str
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    dry_run: Optional[bool] = None
    max_actions: int = Field(default=100, ge=1, le=10000)


class ExecutionActionStatus(str, Enum):
    DRY_RUN = "dry_run"
    EXECUTED = "executed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


class RollbackStatus(str, Enum):
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ExecutionActionResult(BaseModel):
    audit_id: str
    recommendation_id: str
    recommendation_type: RecommendationType
    bucket: str
    key: Optional[str] = None
    risk_level: RiskLevel
    requires_approval: bool
    status: ExecutionActionStatus
    message: str
    permitted: bool
    required_permissions: list[str] = Field(default_factory=list)
    missing_permissions: list[str] = Field(default_factory=list)
    simulated: bool = False
    pre_change_state: dict[str, Any] = Field(default_factory=dict)
    post_change_state: Optional[dict[str, Any]] = None
    rollback_available: bool = False
    rollback_status: RollbackStatus = RollbackStatus.NOT_APPLICABLE


class ExecuteResponse(BaseModel):
    execution_id: str
    run_id: str
    status: RunStatus
    mode: ExecutionMode
    dry_run: bool
    eligible: int
    executed: int
    skipped: int
    blocked: int
    failed: int
    action_results: list[ExecutionActionResult] = Field(default_factory=list)
    executed_at: datetime


class ExecutionAuditRecord(BaseModel):
    audit_id: str
    execution_id: str
    run_id: str
    recommendation_id: str
    recommendation_type: RecommendationType
    bucket: str
    key: Optional[str] = None
    action_status: ExecutionActionStatus
    message: str
    risk_level: RiskLevel
    requires_approval: bool
    permitted: bool
    required_permissions: list[str] = Field(default_factory=list)
    missing_permissions: list[str] = Field(default_factory=list)
    simulated: bool = False
    pre_change_state: dict[str, Any] = Field(default_factory=dict)
    post_change_state: Optional[dict[str, Any]] = None
    rollback_available: bool = False
    rollback_status: RollbackStatus = RollbackStatus.NOT_APPLICABLE
    rolled_back_at: Optional[datetime] = None
    created_at: datetime


class RollbackRequest(BaseModel):
    run_id: str
    execution_id: Optional[str] = None
    audit_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True


class RollbackActionStatus(str, Enum):
    DRY_RUN = "dry_run"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"
    FAILED = "failed"


class RollbackActionResult(BaseModel):
    audit_id: str
    recommendation_id: str
    recommendation_type: RecommendationType
    status: RollbackActionStatus
    message: str
    rolled_back: bool = False


class RollbackResponse(BaseModel):
    run_id: str
    execution_id: str
    dry_run: bool
    attempted: int
    rolled_back: int
    skipped: int
    failed: int
    results: list[RollbackActionResult] = Field(default_factory=list)
    processed_at: datetime


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
    savings_details: list[SavingsEstimate] = Field(default_factory=list)
    savings_summary: Optional[SavingsSummary] = None
    execution: Optional[ExecuteResponse] = None
    audit_records: list[ExecutionAuditRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
