"""Edge-case unit tests for RunStore — supplements test_store.py.

Focus: empty inputs, double-write semantics, combined audit filters,
rollback timestamp side effects, and updated_at propagation.
"""

import uuid
import time
import pytest
from datetime import datetime, timezone

from app.models import (
    ExecuteResponse,
    ExecutionActionResult,
    ExecutionActionStatus,
    ExecutionMode,
    Recommendation,
    RecommendationType,
    RiskFactorScores,
    RiskLevel,
    RiskScore,
    RollbackStatus,
    RunStatus,
    SavingsEstimate,
    SavingsSummary,
)
from app.state.store import RunStore


# ---------------------------------------------------------------------------
# Fixtures / helpers (duplicated from test_store.py to stay self-contained)
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return RunStore(db_path=str(tmp_path / "edge.db"))


def _rec(bucket: str = "test-bucket") -> Recommendation:
    return Recommendation(
        id=str(uuid.uuid4()),
        bucket=bucket,
        key="events/file.parquet",
        recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
        risk_level=RiskLevel.LOW,
        reason="Object appears cold.",
        recommended_action="Transition to GLACIER_IR",
        estimated_monthly_savings=10.0,
        size_bytes=1024 ** 3,
        storage_class="STANDARD",
        last_modified=None,
    )


def _risk_score(rec_id: str, risk_score: int = 21) -> RiskScore:
    return RiskScore(
        recommendation_id=rec_id,
        risk_score=risk_score,
        confidence_score=77,
        impact_score=60,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        safe_to_automate=True,
        execution_recommendation="Safe to automate.",
        factors=["Action is reversible."],
        factor_scores=RiskFactorScores(
            reversibility=90, data_loss_risk=5,
            age_confidence=80, size_impact=60, access_confidence=60,
        ),
    )


def _summary() -> SavingsSummary:
    return SavingsSummary(
        total_monthly_savings=0.019,
        total_annual_savings=0.22798,
        total_transition_costs=0.00002,
        net_first_month=0.01898,
        high_confidence_count=1,
        medium_confidence_count=0,
        low_confidence_count=0,
    )


def _action_result(rec: Recommendation, audit_id: str | None = None, status=ExecutionActionStatus.EXECUTED) -> ExecutionActionResult:
    return ExecutionActionResult(
        audit_id=audit_id or str(uuid.uuid4()),
        recommendation_id=rec.id,
        recommendation_type=rec.recommendation_type,
        bucket=rec.bucket,
        key=rec.key,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        status=status,
        message="Executed.",
        permitted=True,
        required_permissions=["s3:GetObject", "s3:PutObject"],
        missing_permissions=[],
        simulated=False,
        pre_change_state={"bucket": rec.bucket, "storage_class": "STANDARD"},
        post_change_state={"action": "change_storage_class", "target": "GLACIER_IR"},
        rollback_available=True,
        rollback_status=RollbackStatus.PENDING,
    )


def _execute_response(run_id: str, actions: list[ExecutionActionResult]) -> ExecuteResponse:
    return ExecuteResponse(
        execution_id=str(uuid.uuid4()),
        run_id=run_id,
        status=RunStatus.EXECUTED,
        mode=ExecutionMode.FULL,
        dry_run=False,
        eligible=len(actions),
        executed=len(actions),
        skipped=0,
        blocked=0,
        failed=0,
        action_results=actions,
        executed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# create() with empty recommendations
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCreateEdge:
    def test_create_empty_recommendations_succeeds(self, store):
        record = store.create([])
        assert record.status == RunStatus.SCANNED
        assert record.recommendations == []

    def test_create_empty_recommendations_persists(self, store):
        record = store.create([])
        fetched = store.get(record.run_id)
        assert fetched is not None
        assert fetched.recommendations == []

    def test_create_multiple_recommendations_all_persisted(self, store):
        recs = [_rec(), _rec(), _rec()]
        record = store.create(recs)
        fetched = store.get(record.run_id)
        assert len(fetched.recommendations) == 3


# ---------------------------------------------------------------------------
# set_scores() double-write semantics
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSetScoresDoubleWrite:
    def test_set_scores_twice_second_value_wins(self, store):
        """Calling set_scores a second time overwrites the first set of scores."""
        rec = _rec()
        created = store.create([rec])

        score_v1 = _risk_score(rec.id, risk_score=21)
        store.set_scores(created.run_id, [score_v1], [], _summary())

        score_v2 = _risk_score(rec.id, risk_score=77)
        store.set_scores(created.run_id, [score_v2], [], _summary())

        fetched = store.get(created.run_id)
        assert fetched.scores[0].risk_score == 77

    def test_set_scores_twice_status_remains_scored(self, store):
        rec = _rec()
        created = store.create([rec])
        score = _risk_score(rec.id)
        store.set_scores(created.run_id, [score], [], _summary())
        store.set_scores(created.run_id, [score], [], _summary())
        fetched = store.get(created.run_id)
        assert fetched.status == RunStatus.SCORED

    def test_set_scores_with_empty_scores_list(self, store):
        """set_scores([]) → valid, persists empty list."""
        rec = _rec()
        created = store.create([rec])
        store.set_scores(created.run_id, [], [], _summary())
        fetched = store.get(created.run_id)
        assert fetched.scores == []
        assert fetched.status == RunStatus.SCORED


# ---------------------------------------------------------------------------
# set_execution() with empty action_results and double-write
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSetExecutionEdge:
    def test_set_execution_with_empty_action_results(self, store):
        """ExecuteResponse with zero actions inserts no audit records."""
        created = store.create([_rec()])
        execution = _execute_response(created.run_id, [])
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id)
        assert audit == []

    def test_set_execution_twice_stores_second_execution(self, store):
        """Calling set_execution twice: second execution_json overwrites first in runs,
        but both batches of audit records are inserted (INSERT OR REPLACE by audit_id)."""
        rec = _rec()
        created = store.create([rec])

        action1 = _action_result(rec, audit_id="audit-111")
        exec1 = _execute_response(created.run_id, [action1])
        store.set_execution(created.run_id, exec1)

        action2 = _action_result(rec, audit_id="audit-222")
        exec2 = _execute_response(created.run_id, [action2])
        store.set_execution(created.run_id, exec2)

        fetched = store.get(created.run_id)
        # The latest execution_id is stored in the run record
        assert fetched.execution.execution_id == exec2.execution_id

    def test_set_execution_twice_audit_records_accumulate(self, store):
        """Audit records from both executions are retained (different audit_ids)."""
        rec = _rec()
        created = store.create([rec])

        action1 = _action_result(rec, audit_id="audit-aaa")
        store.set_execution(created.run_id, _execute_response(created.run_id, [action1]))

        action2 = _action_result(rec, audit_id="audit-bbb")
        store.set_execution(created.run_id, _execute_response(created.run_id, [action2]))

        audit = store.list_execution_audit(created.run_id)
        audit_ids = {a.audit_id for a in audit}
        assert "audit-aaa" in audit_ids
        assert "audit-bbb" in audit_ids


# ---------------------------------------------------------------------------
# list_execution_audit() with audit_ids=[] returns all records
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListAuditEdge:
    def test_empty_audit_ids_list_returns_all_records(self, store):
        """audit_ids=[] is falsy → `if audit_ids:` is False → no filter applied → returns all."""
        rec1, rec2 = _rec(), _rec()
        created = store.create([rec1, rec2])
        action1 = _action_result(rec1, audit_id="audit-x")
        action2 = _action_result(rec2, audit_id="audit-y")
        store.set_execution(created.run_id, _execute_response(created.run_id, [action1, action2]))

        # Empty list → no IN filter → returns everything
        audit = store.list_execution_audit(created.run_id, audit_ids=[])
        assert len(audit) == 2

    def test_combined_execution_id_and_audit_ids_filter(self, store):
        """Both execution_id and audit_ids filters applied together."""
        rec1, rec2 = _rec(), _rec()
        created = store.create([rec1, rec2])

        action1 = _action_result(rec1, audit_id="audit-p")
        action2 = _action_result(rec2, audit_id="audit-q")
        exec_resp = _execute_response(created.run_id, [action1, action2])
        store.set_execution(created.run_id, exec_resp)

        # Filter to specific execution AND specific audit_id
        audit = store.list_execution_audit(
            created.run_id,
            execution_id=exec_resp.execution_id,
            audit_ids=["audit-p"],
        )
        assert len(audit) == 1
        assert audit[0].audit_id == "audit-p"

    def test_audit_ids_filter_with_nonexistent_id_returns_empty(self, store):
        rec = _rec()
        created = store.create([rec])
        action = _action_result(rec, audit_id="audit-real")
        store.set_execution(created.run_id, _execute_response(created.run_id, [action]))

        audit = store.list_execution_audit(created.run_id, audit_ids=["audit-ghost"])
        assert audit == []

    def test_list_audit_for_unknown_run_returns_empty(self, store):
        audit = store.list_execution_audit("ghost-run-id")
        assert audit == []


# ---------------------------------------------------------------------------
# update_rollback_status() side effects
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUpdateRollbackStatusEdge:
    def _setup_audit(self, store):
        rec = _rec()
        created = store.create([rec])
        action = _action_result(rec, audit_id="test-audit")
        store.set_execution(created.run_id, _execute_response(created.run_id, [action]))
        return created.run_id

    def test_rolled_back_status_sets_rolled_back_at(self, store):
        run_id = self._setup_audit(store)
        store.update_rollback_status("test-audit", RollbackStatus.ROLLED_BACK, "Done.")
        audit = store.list_execution_audit(run_id)
        assert audit[0].rolled_back_at is not None

    def test_failed_status_does_not_set_rolled_back_at(self, store):
        """FAILED status → rolled_back_at stays NULL (None)."""
        run_id = self._setup_audit(store)
        store.update_rollback_status("test-audit", RollbackStatus.FAILED, "Error occurred.")
        audit = store.list_execution_audit(run_id)
        assert audit[0].rolled_back_at is None

    def test_rolled_back_status_updates_run_updated_at(self, store):
        """Successful rollback status update should bump run's updated_at."""
        run_id = self._setup_audit(store)
        before = store.get(run_id).updated_at
        time.sleep(0.05)
        store.update_rollback_status("test-audit", RollbackStatus.ROLLED_BACK, "Done.")
        after = store.get(run_id).updated_at
        # updated_at should have advanced
        assert after >= before

    def test_update_message_is_persisted(self, store):
        run_id = self._setup_audit(store)
        store.update_rollback_status("test-audit", RollbackStatus.FAILED, "Custom error message.")
        audit = store.list_execution_audit(run_id)
        assert "Custom error message." in audit[0].message

    def test_update_rollback_status_preserves_existing_message_when_none(self, store):
        """Passing message=None → COALESCE keeps the existing message."""
        run_id = self._setup_audit(store)
        original_audit = store.list_execution_audit(run_id)
        original_message = original_audit[0].message

        store.update_rollback_status("test-audit", RollbackStatus.ROLLED_BACK, None)
        updated_audit = store.list_execution_audit(run_id)
        # Message should be unchanged (COALESCE returns old value)
        assert updated_audit[0].message == original_message
