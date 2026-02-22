"""Edge-case unit tests for RollbackService — supplements test_rollback.py.

Focus: all non-EXECUTED action_status values, the "no rollback handler" dead code
path, empty record list, and mixed batch result integrity.
"""

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
) -> ExecutionAuditRecord:
    if pre_change_state is None:
        pre_change_state = {"bucket": "test-bucket", "storage_class": "STANDARD"}
    return ExecutionAuditRecord(
        audit_id=str(uuid.uuid4()),
        execution_id="exec-001",
        run_id="run-001",
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
        post_change_state=None,
        rollback_available=rollback_available,
        rollback_status=RollbackStatus.PENDING if rollback_available else RollbackStatus.NOT_APPLICABLE,
        rolled_back_at=None,
        created_at=datetime.now(timezone.utc),
    )


def _req(dry_run: bool = False) -> RollbackRequest:
    return RollbackRequest(run_id="run-001", execution_id="exec-001", dry_run=dry_run)


# ---------------------------------------------------------------------------
# Non-EXECUTED action statuses → all SKIPPED by eligibility check
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNonExecutedStatusesAreSkipped:
    def test_blocked_action_is_skipped(self):
        """BLOCKED action_status → not EXECUTED → _rollback_eligible returns False."""
        record = _audit(action_status=ExecutionActionStatus.BLOCKED, rollback_available=True)
        resp = svc.rollback(_req(), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED
        assert resp.skipped == 1

    def test_skipped_action_is_skipped(self):
        """SKIPPED action_status → not EXECUTED → _rollback_eligible returns False."""
        record = _audit(action_status=ExecutionActionStatus.SKIPPED, rollback_available=True)
        resp = svc.rollback(_req(), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED
        assert resp.skipped == 1

    def test_failed_action_is_skipped(self):
        """FAILED action_status → not EXECUTED → _rollback_eligible returns False."""
        record = _audit(action_status=ExecutionActionStatus.FAILED, rollback_available=True)
        resp = svc.rollback(_req(), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED
        assert resp.skipped == 1

    def test_dry_run_action_status_is_skipped(self):
        """DRY_RUN action_status → not EXECUTED → _rollback_eligible returns False."""
        record = _audit(action_status=ExecutionActionStatus.DRY_RUN, rollback_available=True)
        resp = svc.rollback(_req(), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED

    def test_skipped_message_is_ineligible(self):
        """All ineligible skips use the same message."""
        record = _audit(action_status=ExecutionActionStatus.BLOCKED, rollback_available=True)
        resp = svc.rollback(_req(), [record], "exec-001")
        assert "not eligible" in resp.results[0].message.lower()


# ---------------------------------------------------------------------------
# "No rollback handler" path via direct _rollback_action call
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNoRollbackHandler:
    def test_rollback_action_falls_through_for_unlisted_type(self):
        """_rollback_action returns False/'No rollback handler' for a type not
        explicitly handled (e.g. DELETE_STALE_OBJECT when called directly, bypassing
        _rollback_eligible which would have blocked it)."""
        record = _audit(
            rec_type=RecommendationType.DELETE_STALE_OBJECT,
            pre_change_state={"bucket": "test-bucket", "key": "some/key"},
        )
        success, message = svc._rollback_action(record)
        assert success is False
        assert "No rollback handler" in message

    def test_rollback_action_falls_through_for_delete_incomplete_upload(self):
        record = _audit(
            rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
            pre_change_state={"bucket": "test-bucket"},
        )
        success, message = svc._rollback_action(record)
        assert success is False
        assert "No rollback handler" in message


# ---------------------------------------------------------------------------
# Empty audit records list
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEmptyAuditRecords:
    def test_empty_list_all_counters_zero(self):
        resp = svc.rollback(_req(), [], "exec-001")
        assert resp.attempted == 0
        assert resp.rolled_back == 0
        assert resp.skipped == 0
        assert resp.failed == 0

    def test_empty_list_results_is_empty(self):
        resp = svc.rollback(_req(), [], "exec-001")
        assert resp.results == []

    def test_empty_list_dry_run_flag_preserved(self):
        resp = svc.rollback(_req(dry_run=True), [], "exec-001")
        assert resp.dry_run is True


# ---------------------------------------------------------------------------
# rollback_available=False combined with eligible type/status
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRollbackAvailableFalseGates:
    def test_rollback_available_false_skips_even_when_executed(self):
        """rollback_available=False is the first gate; type/status don't matter."""
        record = _audit(
            rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
            action_status=ExecutionActionStatus.EXECUTED,
            rollback_available=False,
        )
        resp = svc.rollback(_req(), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED
        assert resp.skipped == 1
        assert resp.rolled_back == 0

    def test_rollback_available_false_and_wrong_status_still_skipped(self):
        record = _audit(
            rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
            action_status=ExecutionActionStatus.DRY_RUN,
            rollback_available=False,
        )
        resp = svc.rollback(_req(), [record], "exec-001")
        assert resp.results[0].status == RollbackActionStatus.SKIPPED


# ---------------------------------------------------------------------------
# Mixed batch: EXECUTED + BLOCKED + FAILED + DRY_RUN → all non-EXECUTED skipped
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMixedBatch:
    def test_only_executed_records_get_rolled_back(self):
        records = [
            _audit(action_status=ExecutionActionStatus.EXECUTED),   # eligible
            _audit(action_status=ExecutionActionStatus.BLOCKED),     # skip
            _audit(action_status=ExecutionActionStatus.FAILED),      # skip
            _audit(action_status=ExecutionActionStatus.SKIPPED),     # skip
            _audit(action_status=ExecutionActionStatus.DRY_RUN),    # skip
        ]
        resp = svc.rollback(_req(), records, "exec-001")
        assert resp.rolled_back == 1
        assert resp.skipped == 4
        assert resp.failed == 0
        assert resp.attempted == 5

    def test_mixed_types_and_statuses(self):
        records = [
            _audit(rec_type=RecommendationType.CHANGE_STORAGE_CLASS, action_status=ExecutionActionStatus.EXECUTED),
            _audit(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, action_status=ExecutionActionStatus.EXECUTED),
            _audit(rec_type=RecommendationType.CHANGE_STORAGE_CLASS, action_status=ExecutionActionStatus.BLOCKED),
        ]
        resp = svc.rollback(_req(), records, "exec-001")
        assert resp.rolled_back == 2
        assert resp.skipped == 1
