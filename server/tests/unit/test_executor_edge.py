"""Edge-case unit tests for ExecutionService — supplements test_executor.py."""

import uuid
import pytest

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
)

svc = ExecutionService()
GB = 1024 ** 3
MB = 1024 ** 2


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_executor.py)
# ---------------------------------------------------------------------------

def _rec(
    rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
    size_bytes=MB,
    storage_class="STANDARD",
    key="test/key.parquet",
    last_modified=None,
) -> Recommendation:
    return Recommendation(
        id=str(uuid.uuid4()),
        bucket="test-bucket",
        key=key,
        recommendation_type=rec_type,
        risk_level=RiskLevel.LOW,
        reason="Object appears cold.",
        recommended_action="Transition to GLACIER_IR",
        estimated_monthly_savings=5.0,
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
# Empty inputs
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEmptyInputs:
    def test_empty_recommendations_returns_zero_counts(self):
        resp = _execute([], [], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.executed == 0
        assert resp.skipped == 0
        assert resp.blocked == 0
        assert resp.failed == 0
        assert resp.eligible == 0

    def test_empty_recommendations_has_empty_action_results(self):
        resp = _execute([], [], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results == []

    def test_multiple_recs_all_missing_score_all_failed(self):
        recs = [_rec() for _ in range(3)]
        resp = _execute(recs, [], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.failed == 3
        assert resp.executed == 0
        assert all(r.status == ExecutionActionStatus.FAILED for r in resp.action_results)

    def test_mixed_scored_and_unscored_in_same_batch(self):
        rec_with = _rec()
        rec_without = _rec()
        score = _score(rec_with.id)
        resp = _execute(
            [rec_with, rec_without],
            [score],
            _req(mode=ExecutionMode.FULL, dry_run=False),
        )
        statuses = {r.recommendation_id: r.status for r in resp.action_results}
        assert statuses[rec_with.id] == ExecutionActionStatus.EXECUTED
        assert statuses[rec_without.id] == ExecutionActionStatus.FAILED

    def test_empty_recs_run_id_propagated(self):
        req = _req(mode=ExecutionMode.DRY_RUN)
        req = ExecuteRequest(run_id="my-special-run", mode=ExecutionMode.DRY_RUN)
        resp = _execute([], [], req)
        assert resp.run_id == "my-special-run"


# ---------------------------------------------------------------------------
# ALLOW_DESTRUCTIVE_EXECUTION case sensitivity
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDestructiveGuardCaseSensitivity:
    """The guard uses `.lower() == 'true'`, so any case variant of 'true' enables
    destructive execution. Unrelated truthy strings like '1', 'yes' do NOT."""

    def test_allow_destructive_uppercase_TRUE_executes(self, monkeypatch):
        """'TRUE'.lower() == 'true' → allow_destructive=True → EXECUTED."""
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "TRUE")
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED

    def test_allow_destructive_numeric_1_is_blocked(self, monkeypatch):
        """'1'.lower() != 'true' → allow_destructive=False → BLOCKED."""
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "1")
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.BLOCKED

    def test_allow_destructive_yes_is_blocked(self, monkeypatch):
        """'yes' != 'true' → BLOCKED."""
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "yes")
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.BLOCKED

    def test_allow_destructive_True_mixed_case_executes(self, monkeypatch):
        """'True'.lower() == 'true' → allow_destructive=True → EXECUTED."""
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "True")
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED

    def test_allow_destructive_exact_lowercase_true_executes(self, monkeypatch):
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "true")
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED


# ---------------------------------------------------------------------------
# Partial permissions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPartialPermissions:
    def test_change_storage_class_needs_both_get_and_put(self, monkeypatch):
        # Grant only GetObject, not PutObject → blocked
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject")
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.BLOCKED
        assert "s3:PutObject" in result.missing_permissions
        assert "s3:GetObject" not in result.missing_permissions

    def test_delete_incomplete_upload_needs_both_list_and_abort(self, monkeypatch):
        # Grant only AbortMultipartUpload, not ListBucketMultipartUploads → blocked
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:AbortMultipartUpload")
        rec = _rec(rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD, size_bytes=0)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.BLOCKED
        assert "s3:ListBucketMultipartUploads" in result.missing_permissions

    def test_delete_stale_needs_both_get_and_delete(self, monkeypatch):
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_EXECUTION", "true")
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.BLOCKED
        assert "s3:DeleteObject" in result.missing_permissions

    def test_lifecycle_policy_needs_both_get_and_put_lifecycle(self, monkeypatch):
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetLifecycleConfiguration")
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=0)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        result = resp.action_results[0]
        assert result.status == ExecutionActionStatus.BLOCKED
        assert "s3:PutLifecycleConfiguration" in result.missing_permissions

    def test_granted_permissions_strips_whitespace(self, monkeypatch):
        # Spaces around permission names should be stripped
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", " s3:GetObject , s3:PutObject ")
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        # Should pass with cleaned-up permissions
        assert resp.action_results[0].status == ExecutionActionStatus.EXECUTED

    def test_empty_granted_permissions_blocks_all(self, monkeypatch):
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "")
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.BLOCKED

    def test_comma_only_permissions_blocks_all(self, monkeypatch):
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", ",,,")
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].status == ExecutionActionStatus.BLOCKED


# ---------------------------------------------------------------------------
# Mode + dry_run flag interaction
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModeDryRunInteraction:
    def test_safe_mode_dry_run_true_ineligible_still_skipped(self):
        """SAFE mode + explicit dry_run=True + safe_to_automate=False → SKIPPED.

        Mode eligibility is checked BEFORE the dry_run branch. Ineligible
        actions are skipped even if dry_run=True is set on the request.
        """
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=True))
        assert resp.action_results[0].status == ExecutionActionStatus.SKIPPED

    def test_standard_mode_dry_run_true_ineligible_still_skipped(self):
        rec = _rec()
        score = _score(rec.id, requires_approval=True, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.STANDARD, dry_run=True))
        assert resp.action_results[0].status == ExecutionActionStatus.SKIPPED

    def test_full_mode_dry_run_true_eligible_gives_dry_run_status(self):
        """FULL mode + dry_run=True → DRY_RUN (eligible in FULL, dry_run wins)."""
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False, requires_approval=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=True))
        assert resp.action_results[0].status == ExecutionActionStatus.DRY_RUN
        assert resp.action_results[0].simulated is True

    def test_safe_mode_dry_run_true_eligible_gives_dry_run_status(self):
        """SAFE mode + dry_run=True + safe_to_automate=True → DRY_RUN."""
        rec = _rec()
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=True))
        assert resp.action_results[0].status == ExecutionActionStatus.DRY_RUN

    def test_dry_run_mode_ignores_permission_checks(self):
        """In DRY_RUN mode permissions are checked — blocked still blocks in dry run."""
        # Permission check happens BEFORE the dry_run branch for DRY_RUN mode too
        # because DRY_RUN mode goes: eligible → destructive_guard → permission_guard → dry_run
        # So DELETE without permissions → BLOCKED even in DRY_RUN
        # Wait: DRY_RUN mode: eligible++ happens after mode_eligible check, which always
        # returns True for DRY_RUN. Then permission check. BLOCKED if missing perms.
        # So DRY_RUN mode does NOT bypass permissions — test this.
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        # Remove all permissions
        import os
        old = os.environ.get("EXECUTOR_GRANTED_PERMISSIONS", None)
        os.environ["EXECUTOR_GRANTED_PERMISSIONS"] = ""
        try:
            resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
            assert resp.action_results[0].status == ExecutionActionStatus.BLOCKED
        finally:
            if old is None:
                del os.environ["EXECUTOR_GRANTED_PERMISSIONS"]
            else:
                os.environ["EXECUTOR_GRANTED_PERMISSIONS"] = old

    def test_dry_run_mode_via_monkeypatch_no_permissions(self, no_permissions):
        """DRY_RUN mode still checks permissions — missing perms → BLOCKED."""
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].status == ExecutionActionStatus.BLOCKED


# ---------------------------------------------------------------------------
# max_actions boundary
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMaxActionsBoundary:
    def test_max_actions_1_processes_first_skips_rest(self):
        recs = [_rec() for _ in range(3)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(mode=ExecutionMode.FULL, dry_run=False, max_actions=1))
        assert resp.executed == 1
        assert resp.skipped == 2

    def test_max_actions_equals_rec_count_all_execute(self):
        recs = [_rec() for _ in range(3)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(mode=ExecutionMode.FULL, dry_run=False, max_actions=3))
        assert resp.executed == 3
        assert resp.skipped == 0

    def test_max_actions_skipped_items_have_correct_message(self):
        recs = [_rec() for _ in range(2)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(mode=ExecutionMode.FULL, dry_run=False, max_actions=1))
        skipped = [r for r in resp.action_results if r.status == ExecutionActionStatus.SKIPPED]
        assert "max_actions=1" in skipped[0].message

    def test_max_actions_does_not_count_mode_skipped(self):
        """Max-actions limit fires before mode-eligibility, so a SKIPPED-by-mode
        recommendation still advances the index and can push later ones over the limit."""
        rec_ineligible = _rec()
        rec_eligible = _rec()
        score_ineligible = _score(rec_ineligible.id, safe_to_automate=False)
        score_eligible = _score(rec_eligible.id, safe_to_automate=True)
        # max_actions=1, first rec is ineligible (SKIPPED-by-mode at index 0, which is
        # < 1 so it is NOT skipped by max_actions). Second rec (index 1 >= 1) is
        # SKIPPED by max_actions.
        resp = _execute(
            [rec_ineligible, rec_eligible],
            [score_ineligible, score_eligible],
            _req(mode=ExecutionMode.SAFE, dry_run=False, max_actions=1),
        )
        statuses = [r.status for r in resp.action_results]
        # First: SKIPPED by mode; Second: SKIPPED by max_actions
        assert statuses[0] == ExecutionActionStatus.SKIPPED  # mode-ineligible
        assert statuses[1] == ExecutionActionStatus.SKIPPED  # max_actions


# ---------------------------------------------------------------------------
# Post-change state completeness
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPostChangeStateCompleteness:
    def test_delete_incomplete_upload_post_state_has_action(self):
        rec = _rec(rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD, size_bytes=0)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        state = resp.action_results[0].post_change_state
        assert state is not None
        assert state["action"] == "delete_incomplete_upload"

    def test_delete_stale_object_post_state_has_action(self, allow_destructive, monkeypatch):
        monkeypatch.setenv("EXECUTOR_GRANTED_PERMISSIONS", "s3:GetObject,s3:DeleteObject")
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT, key="stale/obj.parquet")
        score = _score(rec.id, safe_to_automate=True)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        state = resp.action_results[0].post_change_state
        assert state is not None
        assert state["action"] == "delete_stale_object"
        assert state["target"] == "stale/obj.parquet"

    def test_post_change_state_simulated_false_on_live_execute(self):
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
        state = resp.action_results[0].post_change_state
        assert state is not None
        assert state["simulated"] is False

    def test_post_change_state_simulated_true_in_dry_run(self):
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=0)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].post_change_state["simulated"] is True

    def test_failed_action_has_null_post_change_state(self):
        """Missing score → FAILED → post_change_state is None."""
        rec = _rec()
        resp = _execute([rec], [], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.action_results[0].post_change_state is None

    def test_skipped_action_has_null_post_change_state(self):
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=False))
        assert resp.action_results[0].post_change_state is None


# ---------------------------------------------------------------------------
# eligible counter semantics
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEligibleCounter:
    def test_eligible_not_incremented_for_max_actions_skipped(self):
        """Recs skipped by max_actions limit are NOT counted as eligible."""
        recs = [_rec() for _ in range(3)]
        scores = [_score(r.id) for r in recs]
        resp = _execute(recs, scores, _req(mode=ExecutionMode.FULL, dry_run=False, max_actions=1))
        assert resp.eligible == 1  # only the first one reached the eligible counter

    def test_eligible_not_incremented_for_mode_skipped(self):
        """Recs skipped by mode policy are NOT counted as eligible."""
        rec = _rec()
        score = _score(rec.id, safe_to_automate=False)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.SAFE, dry_run=False))
        assert resp.eligible == 0

    def test_eligible_not_incremented_for_missing_score(self):
        """Recs with no score are FAILED before eligible is incremented."""
        rec = _rec()
        resp = _execute([rec], [], _req(mode=ExecutionMode.FULL, dry_run=False))
        assert resp.eligible == 0

    def test_eligible_incremented_even_when_then_blocked(self):
        """Recs that pass mode check (and become eligible) but are then permission-
        blocked ARE counted in eligible — the block is a post-eligibility gate."""
        rec = _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        score = _score(rec.id, safe_to_automate=True)
        import os
        old = os.environ.get("EXECUTOR_GRANTED_PERMISSIONS", None)
        os.environ["EXECUTOR_GRANTED_PERMISSIONS"] = ""
        try:
            resp = _execute([rec], [score], _req(mode=ExecutionMode.FULL, dry_run=False))
            # eligible was incremented (passed mode check), then blocked by permissions
            assert resp.eligible == 1
            assert resp.blocked == 1
        finally:
            if old is None:
                del os.environ["EXECUTOR_GRANTED_PERMISSIONS"]
            else:
                os.environ["EXECUTOR_GRANTED_PERMISSIONS"] = old

    def test_execution_id_is_unique_per_call(self):
        """Each call to execute() generates a fresh execution_id."""
        rec = _rec()
        score = _score(rec.id)
        req = _req(mode=ExecutionMode.DRY_RUN)
        resp1 = _execute([rec], [score], req)
        resp2 = _execute([rec], [score], req)
        assert resp1.execution_id != resp2.execution_id


# ---------------------------------------------------------------------------
# Pre-change state with null-like fields
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPreChangeStateEdges:
    def test_pre_change_state_with_null_key(self):
        rec = _rec(key=None)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].pre_change_state["key"] is None

    def test_pre_change_state_with_null_storage_class(self):
        rec = Recommendation(
            id=str(uuid.uuid4()),
            bucket="b", key="k",
            recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
            risk_level=RiskLevel.LOW,
            reason="r", recommended_action="a",
            estimated_monthly_savings=0.0,
            size_bytes=0, storage_class=None, last_modified=None,
        )
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].pre_change_state["storage_class"] is None

    def test_pre_change_state_size_bytes_zero(self):
        rec = _rec(size_bytes=0)
        score = _score(rec.id)
        resp = _execute([rec], [score], _req(mode=ExecutionMode.DRY_RUN))
        assert resp.action_results[0].pre_change_state["size_bytes"] == 0
