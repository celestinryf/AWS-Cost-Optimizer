// ---------------------------------------------------------------------------
// Enums — mirror server/app/models/contracts.py
// ---------------------------------------------------------------------------

export type RunStatus = "scanned" | "scored" | "executed";

export type RecommendationType =
  | "CHANGE_STORAGE_CLASS"
  | "ADD_LIFECYCLE_POLICY"
  | "DELETE_INCOMPLETE_UPLOAD"
  | "DELETE_STALE_OBJECT";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export type ExecutionMode = "dry_run" | "safe" | "standard" | "full";

export type ExecutionActionStatus =
  | "executed"
  | "dry_run"
  | "skipped"
  | "blocked"
  | "failed";

export type RollbackStatus = "pending" | "rolled_back" | "failed" | "not_applicable";

export type RollbackActionStatus = "rolled_back" | "skipped" | "failed" | "dry_run";

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

export interface Recommendation {
  id: string;
  bucket: string;
  key: string | null;
  recommendation_type: RecommendationType;
  risk_level: RiskLevel;
  reason: string;
  recommended_action: string;
  estimated_monthly_savings: number;
  size_bytes: number;
  storage_class: string | null;
  last_modified: string | null;
}

export interface RiskFactorScores {
  reversibility: number;
  data_loss_risk: number;
  age_confidence: number;
  size_impact: number;
  access_confidence: number;
}

export interface RiskScore {
  recommendation_id: string;
  risk_score: number;
  confidence_score: number;
  impact_score: number;
  risk_level: RiskLevel;
  requires_approval: boolean;
  safe_to_automate: boolean;
  execution_recommendation: string;
  factors: string[];
  factor_scores: RiskFactorScores;
}

export interface SavingsEstimate {
  recommendation_id: string;
  recommendation_type: RecommendationType;
  bucket: string;
  key: string | null;
  current_monthly_cost: number;
  projected_monthly_cost: number;
  monthly_savings: number;
  annual_savings: number;
  transition_cost: number;
  net_first_month_savings: number;
  net_annual_savings: number;
  break_even_days: number | null;
  confidence: "high" | "medium" | "low";
}

export interface SavingsSummary {
  total_monthly_savings: number;
  total_annual_savings: number;
  total_transition_cost: number;
  net_annual_savings: number;
  high_confidence_count: number;
  medium_confidence_count: number;
  low_confidence_count: number;
}

export interface ExecutionActionResult {
  audit_id: string;
  recommendation_id: string;
  recommendation_type: RecommendationType;
  bucket: string;
  key: string | null;
  risk_level: RiskLevel;
  requires_approval: boolean;
  status: ExecutionActionStatus;
  message: string;
  permitted: boolean;
  required_permissions: string[];
  missing_permissions: string[];
  simulated: boolean;
  pre_change_state: Record<string, unknown>;
  post_change_state: Record<string, unknown> | null;
  rollback_available: boolean;
  rollback_status: RollbackStatus;
}

export interface ExecuteResponse {
  execution_id: string;
  run_id: string;
  status: RunStatus;
  mode: ExecutionMode;
  dry_run: boolean;
  eligible: number;
  executed: number;
  skipped: number;
  blocked: number;
  failed: number;
  action_results: ExecutionActionResult[];
  executed_at: string;
}

export interface ExecutionAuditRecord {
  audit_id: string;
  execution_id: string;
  run_id: string;
  recommendation_id: string;
  recommendation_type: RecommendationType;
  bucket: string;
  key: string | null;
  action_status: ExecutionActionStatus;
  message: string;
  risk_level: RiskLevel;
  requires_approval: boolean;
  permitted: boolean;
  required_permissions: string[];
  missing_permissions: string[];
  simulated: boolean;
  pre_change_state: Record<string, unknown>;
  post_change_state: Record<string, unknown> | null;
  rollback_available: boolean;
  rollback_status: RollbackStatus;
  rolled_back_at: string | null;
  created_at: string;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  recommendation_count: number;
  estimated_monthly_savings: number;
  updated_at: string;
}

export interface RunDetails {
  run_id: string;
  status: RunStatus;
  recommendations: Recommendation[];
  scores: RiskScore[];
  savings_details: SavingsEstimate[];
  savings_summary: SavingsSummary | null;
  execution: ExecuteResponse | null;
  audit_records: ExecutionAuditRecord[];
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface ScanRequest {
  include_buckets: string[];
  exclude_buckets: string[];
  max_objects: number;
}

export interface ScoreRequest {
  run_id: string;
}

export interface ExecuteRequest {
  run_id: string;
  mode: ExecutionMode;
  dry_run: boolean | null;
  max_actions: number;
}

export interface RollbackRequest {
  run_id: string;
  execution_id: string | null;
  dry_run: boolean;
  audit_ids: string[];
}

// ---------------------------------------------------------------------------
// Response wrappers
// ---------------------------------------------------------------------------

export interface ScanResponse {
  run_id: string;
  status: RunStatus;
  recommendations: Recommendation[];
  estimated_monthly_savings: number;
  scanned_at: string;
}

export interface ScoreResponse {
  run_id: string;
  status: RunStatus;
  scores: RiskScore[];
  savings_details: SavingsEstimate[];
  savings_summary: SavingsSummary;
  safe_to_automate: number;
  requires_approval: number;
  scored_at: string;
}

export interface RollbackActionResult {
  audit_id: string;
  recommendation_id: string;
  recommendation_type: RecommendationType;
  status: RollbackActionStatus;
  message: string;
  rolled_back: boolean;
}

export interface RollbackResponse {
  run_id: string;
  execution_id: string;
  dry_run: boolean;
  attempted: number;
  rolled_back: number;
  skipped: number;
  failed: number;
  results: RollbackActionResult[];
  processed_at: string;
}
