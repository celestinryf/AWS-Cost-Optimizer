"""Unit tests for RollbackService."""

import uuid
import pytest
from datetime import datetime, timezone

from app.executor.rollback import RollbackService
from app.models import (
    ExecutionActionStatus,
    ExecutionAuditRecord,
    RecommendationType,
    RiskLevel,
    RollbackActionStatus,
    RollbackRequest,
    RollbackStatus,
)

svc = RollbackService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit(
    rec_type: RecommendationType = RecommendationType.CHANGE_STORAGE_CLASS,
    action_status: ExecutionActionStatus = ExecutionActionStatus.EXECUTED,
    rollback_available: bool = True,
    pre_change_state: dict | None = None,
    run_id: str = "run-001",
    execution_id: str = "exec-001",
) -> ExecutionAuditRecord:
    if pre_change_state is None:
        pre_change_state = {"bucket": "test-bucket", "key": "test/key", "storage_class": "STANDARD"}
    return ExecutionAuditRecord(
        audit_id=str(uuid.uuid4()),
        execution_id=execution_id,
        run_id=run_id,
        recommendation_id=str(uuid.uuid4()),
        recommendation_type=rec_type,
        bucket="test-bucket",
        key="test/key",
        action_status=action_status,
        message="executed",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        permitted=True,
        required_permissions=[],
        missing_permissions=[],
        simulated=False,
        pre_change_state=pre_change_state,
        post_change_state={"action": "change_storage_class"},
        rollback_available=rollback_available,
        rollback_status=RollbackStatus.PENDING if rollback_available else RollbackStatus.NOT_APPLICABLE,
        rolled_back_at=None,
        created_at=datetime.now(timezone.utc),
    )


def _req(
    run_id: str = "run-001",
    execution_id: str = "exec-001",
    dry_run: bool = True,
    audit_ids: list[str] | None = None,
) -> RollbackRequest:
    return RollbackRequest(
        run_id=run_id,
        execution_id=execution_id,
        dry_run=dry_run,
        audit_ids=audit_ids or [],
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRollbackEligibility:
    def test_eligible_change_storage_class_is_rolled_back(self):
        record = _audit(rec_type=RecommendationType.CHANGE_STORAGE_CLASS)
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.ROLLED_BACK

    def test_eligible_lifecycle_policy_is_rolled_back(self):
        record = _audit(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY)
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.ROLLED_BACK

    def test_rollback_available_false_causes_skip(self):
        record = _audit(rollback_available=False)
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED
        assert resp.skipped == 1

    def test_not_executed_status_causes_skip(self):
        record = _audit(action_status=ExecutionActionStatus.DRY_RUN, rollback_available=True)
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED

    def test_delete_incomplete_upload_causes_skip(self):
        record = _audit(
            rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
            rollback_available=False,
        )
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED

    def test_delete_stale_object_causes_skip(self):
        record = _audit(
            rec_type=RecommendationType.DELETE_STALE_OBJECT,
            rollback_available=False,
        )
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDryRun:
    def test_dry_run_returns_dry_run_status(self):
        record = _audit()
        resp = svc.rollback(_req(dry_run=True), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.DRY_RUN

    def test_dry_run_rolled_back_count_is_zero(self):
        records = [_audit(), _audit()]
        resp = svc.rollback(_req(dry_run=True), records, "exec-001")
        assert resp.rolled_back == 0

    def test_dry_run_response_flag_is_true(self):
        record = _audit()
        resp = svc.rollback(_req(dry_run=True), [record], "exec-001")
        assert resp.dry_run is True


# ---------------------------------------------------------------------------
# Rollback actions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRollbackActions:
    def test_change_storage_class_restores_original(self):
        record = _audit(pre_change_state={"storage_class": "STANDARD_IA"})
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert "STANDARD_IA" in resp.results[0].message

    def test_change_storage_class_defaults_to_standard_if_missing(self):
        # Non-empty dict without storage_class key: .get("storage_class") or "STANDARD" → "STANDARD"
        record = _audit(pre_change_state={"bucket": "test-bucket"})
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert "STANDARD" in resp.results[0].message

    def test_lifecycle_rollback_succeeds(self):
        record = _audit(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY)
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].rolled_back is True

    def test_missing_pre_change_state_causes_failure(self):
        # Empty dict {} is falsy → _rollback_action returns (False, "Missing pre-change state snapshot.")
        record = _audit(pre_change_state=None)
        record.pre_change_state = {}
        resp = svc.rollback(_req(dry_run=False), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.FAILED
        assert "Missing pre-change state" in resp.results[0].message


# ---------------------------------------------------------------------------
# Response integrity
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRollbackResponseIntegrity:
    def test_attempted_equals_total_records(self):
        records = [_audit(), _audit(rollback_available=False), _audit()]
        resp = svc.rollback(_req(dry_run=False), records, "exec-001")
        assert resp.attempted == 3

    def test_counts_sum_to_attempted(self):
        records = [_audit(), _audit(rollback_available=False)]
        resp = svc.rollback(_req(dry_run=False), records, "exec-001")
        assert resp.rolled_back + resp.skipped + resp.failed == resp.attempted

    def test_run_id_propagated(self):
        record = _audit(run_id="my-run")
        resp = svc.rollback(_req(run_id="my-run", dry_run=True), [record], "exec-001")
        assert resp.run_id == "my-run"

    def test_execution_id_propagated(self):
        record = _audit(execution_id="my-exec")
        resp = svc.rollback(_req(execution_id="my-exec", dry_run=True), [record], "my-exec")
        assert resp.execution_id == "my-exec"

    def test_mixed_eligible_and_ineligible(self):
        records = [
            _audit(rec_type=RecommendationType.CHANGE_STORAGE_CLASS),   # eligible
            _audit(rollback_available=False),                            # skipped
            _audit(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY),   # eligible
        ]
        resp = svc.rollback(_req(dry_run=False), records, "exec-001")
        assert resp.rolled_back == 2
        assert resp.skipped == 1
