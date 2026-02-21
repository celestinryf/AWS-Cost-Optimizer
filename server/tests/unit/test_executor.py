"""Unit tests for ExecutionService."""

import uuid
import pytest
from datetime import datetime, timezone

from app.executor.service import ExecutionService
from app.models import (
    ExecuteRequest,
    ExecutionActionStatus,
    ExecutionMode,
    Recommendation,
    RecommendationType,
    RiskFactorScores,
    RiskLevel,
    RiskScore,
    RollbackStatus,
)

svc = ExecutionService()
GB = 1024 ** 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(
    rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
    size_bytes=1024 * 1024,
    storage_class="STANDARD",
    last_modified=None,
    reason="Object appears cold based on age and path.",
    recommended_action="Transition to GLACIER_IR",
) -> Recommendation:
    return Recommendation(
        id=str(uuid.uuid4()),
        bucket="test-bucket",
        key="test/key.parquet",
        recommendation_type=rec_type,
        risk_level=RiskLevel.LOW,
        reason=reason,
        recommended_action=recommended_action,
        estimated_monthly_savings=10.0,
        size_bytes=size_bytes,
        storage_class=storage_class,
        last_modified=last_modified,
    )


def _score(
    recommendation_id: str,
    safe_to_automate: bool = True,
    requires_approval: bool = False,
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_score: int = 20,
) -> RiskScore:
    return RiskScore(
        recommendation_id=recommendation_id,
        risk_score=risk_score,
        confidence_score=80,
        impact_score=60,
        risk_level=risk_level,
        requires_approval=requires_approval,
        safe_to_automate=safe_to_automate,
        execution_recommendation="Safe to automate.",
        factors=[],
        factor_scores=RiskFactorScores(
            reversibility=90, data_loss_risk=5,
            age_confidence=80, size_impact=60, access_confidence=60,
        ),
    )


def _req(
    mode: ExecutionMode = ExecutionMode.DRY_RUN,
    dry_run=None,
    max_actions: int = 100,
) -> ExecuteRequest:
    return ExecuteRequest(run_id="run-001", mode=mode, dry_run=dry_run, max_actions=max_actions)


def _execute(recs, scores, req):
    return svc.execute(req, recs, scores)


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModeResolution:
    def test_dry_run_mode_always_sets_dry_true(self):
        mode, dry = svc._resolve_mode(_req(mode=ExecutionMode.DRY_RUN))
        assert mode == ExecutionMode.DRY_RUN
        assert dry is True

    def test_explicit_dry_run_true_overrides_mode(self):
        mode, dry = svc._resolve_mode(_req(mode=ExecutionMode.SAFE, dry_run=True))
        assert mode == ExecutionMode.SAFE
        assert dry is True

    def test_explicit_dry_run_false_enables_live(self):
        mode, dry = svc._resolve_mode(_req(mode=ExecutionMode.SAFE, dry_run=False))
        assert mode == ExecutionMode.SAFE
        assert dry is False

    def test_safe_mode_with_no_dry_run_flag_is_live(self):
        """mode=SAFE, dry_run=None → falls to `return mode, mode == DRY_RUN` → (SAFE, False)."""
        mode, dry = svc._resolve_mode(_req(mode=ExecutionMode.SAFE, dry_run=None))
        assert dry is False

    def test_full_mode_with_no_dry_run_flag_is_live(self):
        mode, dry = svc._resolve_mode(_req(mode=ExecutionMode.FULL, dry_run=None))
        assert dry is False


# ---------------------------------------------------------------------------
# Mode eligibility
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModeEligibility:
    def test_dry_run_mode_all_eligible(self):
        score = _score("x", safe_to_automate=False, requires_approval=True)
        assert svc._is_mode_eligible(ExecutionMode.DRY_RUN, score) is True

    def test_safe_mode_safe_to_automate_true_eligible(self):
        score = _score("x", safe_to_automate=True)
        assert svc._is_mode_eligible(ExecutionMode.SAFE, score) is True

    def test_safe_mode_safe_to_automate_false_not_eligible(self):
        score = _score("x", safe_to_automate=False)
        assert svc._is_mode_eligible(ExecutionMode.SAFE, score) is False

    def test_standard_mode_not_requires_approval_eligible(self):
        score = _score("x", requires_approval=False)
        assert svc._is_mode_eligible(ExecutionMode.STANDARD, score) is True

    def test_standard_mode_requires_approval_not_eligible(self):
        score = _score("x", requires_approval=True)
        assert svc._is_mode_eligible(ExecutionMode.STANDARD, score) is False

    def test_full_mode_always_eligible(self):
        score = _score("x", safe_to_automate=False, requires_approval=True)
        assert svc._is_mode_eligible(ExecutionMode.FULL, score) is True


# ---------------------------------------------------------------------------
# DRY_RUN mode outcomes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDryRunExecution:
    def test_all_actions_get_dry_run_status(self):
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False, requires_approval=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert len(resp.action_results) == 1
        assert resp.action_results[0].status == ExecutionActionStatus.DRY_RUN

    def test_dry_run_actions_are_simulated(self):
        rec = _rec()
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].simulated is True

    def test_dry_run_response_has_dry_run_true(self):
        rec = _rec()
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.dry_run is True

    def test_dry_run_post_change_state_is_set(self):
        rec = _rec()
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].post_change_state is not None


# ---------------------------------------------------------------------------
# SAFE / STANDARD / FULL mode filtering
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModeFiltering:
    def test_safe_mode_skips_non_safe_to_automate(self):
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.SKIPPED

    def test_safe_mode_executes_safe_to_automate(self):
        rec = _rec()
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED

    def test_standard_mode_skips_requires_approval(self):
        rec = _rec()
        score = _score(rec.id, requires_approval=True, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.STANDARD, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.SKIPPED

    def test_full_mode_executes_all_eligible(self):
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False, requires_approval=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED


# ---------------------------------------------------------------------------
# Permission guards
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPermissionGuards:
    def test_missing_all_permissions_causes_blocked(self, no_permissions):
        rec = _rec()
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.BLOCKED
        assert result.permitted is False
        assert len(result.missing_permissions) > 0

    def test_correct_permissions_required_for_change_storage_class(self, no_permissions):
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert "s3:GetObject" in result.required_permissions
        assert "s3:PutObject" in result.required_permissions

    def test_correct_permissions_required_for_lifecycle_policy(self, no_permissions):
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=0)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert "s3:GetLifecycleConfiguration" in resp.action_results[0].required_permissions
        assert "s3:PutLifecycleConfiguration" in resp.action_results[0].required_permissions

    def test_correct_permissions_required_for_multipart_upload(self, no_permissions):
        rec = _rec(rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert "s3:ListBucketMultipartUploads" in resp.action_results[0].required_permissions

    def test_correct_permissions_required_for_delete_stale(self, no_permissions, allow_destructive):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert "s3:DeleteObject" in resp.action_results[0].required_permissions


# ---------------------------------------------------------------------------
# Destructive guard
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDestructiveGuard:
    def test_delete_stale_blocked_by_default(self, deny_destructive):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True, requires_approval=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.BLOCKED
        assert "ALLOW_DESTRUCTIVE_EXECUTION" in result.message

    def test_delete_stale_executes_with_allow_destructive(self, allow_destructive, monkeypatch):
        # Also must grant s3:DeleteObject — it is NOT in the default EXECUTOR_GRANTED_PERMISSIONS.
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True, requires_approval=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED

    def test_non_delete_type_not_blocked(self, deny_destructive):
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status != ExecutionActionStatus.BLOCKED


# ---------------------------------------------------------------------------
# max_actions limit
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMaxActionsLimit:
    def test_max_actions_skips_excess(self):
        recs = [_rec() for _ in range(3)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(max_actions=2))
        skipped = [r for r in resp.action_results if r.status == ExecutionActionStatus.SKIPPED]
        assert len(skipped) == 1

    def test_skipped_message_includes_max_actions(self):
        recs = [_rec() for _ in range(2)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(max_actions=1))
        skipped = [r for r in resp.action_results if r.status == ExecutionActionStatus.SKIPPED]
        assert "max_actions=1" in skipped[0].message


# ---------------------------------------------------------------------------
# Missing score
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMissingScore:
    def test_missing_score_results_in_failed(self):
        rec = _rec()
        resp = _execute([rec], [], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].status == ExecutionActionStatus.FAILED
        assert "Missing risk score" in resp.action_results[0].message


# ---------------------------------------------------------------------------
# Rollback availability
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRollbackAvailability:
    def test_rollback_available_for_executed_change_storage_class(self):
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.EXECUTED
        assert result.rollback_available is True
        assert result.rollback_status == RollbackStatus.PENDING

    def test_rollback_available_for_executed_lifecycle_policy(self):
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=0)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.EXECUTED
        assert result.rollback_available is True

    def test_rollback_not_available_for_dry_run(self):
        rec = _rec()
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].rollback_available is False

    def test_rollback_not_available_for_delete_stale(self, allow_destructive):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].rollback_available is False
        assert resp.action_results[0].rollback_status == RollbackStatus.NOT_APPLICABLE

    def test_rollback_not_available_for_skipped(self):
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=False))
        assert resp.action_results[0].rollback_available is False


# ---------------------------------------------------------------------------
# Pre/post change state
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestChangeState:
    def test_pre_change_state_captures_fields(self):
        rec = _rec()
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        state = resp.action_results[0].pre_change_state
        assert state["bucket"] == "test-bucket"
        assert state["key"] == "test/key.parquet"
        assert state["storage_class"] == "STANDARD"
        assert state["size_bytes"] == 1024 * 1024
        assert "risk_level" in state

    def test_pre_change_state_handles_null_last_modified(self):
        rec = _rec(last_modified=None)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].pre_change_state["last_modified"] is None

    def test_post_change_state_none_for_blocked(self, deny_destructive):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].post_change_state is None

    def test_post_change_state_action_for_lifecycle(self):
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=0)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        state = resp.action_results[0].post_change_state
        assert state["action"] == "add_lifecycle_policy"


# ---------------------------------------------------------------------------
# Response count integrity
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestResponseCounts:
    def test_counts_sum_to_total(self):
        recs = [_rec() for _ in range(3)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(mode=ExecutionMode.DRY_RUN))
        total = resp.executed + resp.skipped + resp.blocked + resp.failed
        assert total == len(recs)

    def test_executed_count_matches_action_results(self):
        recs = [_rec() for _ in range(3)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(mode=ExecutionMode.FULL, dry_run=False))
        executed_actions = [r for r in resp.action_results
                            if r.status == ExecutionActionStatus.EXECUTED]
        assert resp.executed == len(executed_actions)
