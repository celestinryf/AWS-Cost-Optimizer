"""Unit tests for RunStore SQLite persistence."""

import time
import uuid
import pytest
from datetime import datetime, timedelta, timezone

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
# Fixture: fresh store per test via temp file
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return RunStore(db_path=str(tmp_path / "test.db"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(bucket: str = "test-bucket") -> Recommendation:
    return Recommendation(
        id=str(uuid.uuid4()),
        bucket=bucket,
        key="events/2024/file.parquet",
        recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
        risk_level=RiskLevel.LOW,
        reason="Object appears cold based on age and path.",
        recommended_action="Transition to GLACIER_IR",
        estimated_monthly_savings=12.6,
        size_bytes=8 * 1024 ** 3,
        storage_class="STANDARD",
        last_modified=datetime.now(timezone.utc) - timedelta(days=220),
    )


def _rec_no_key_no_date() -> Recommendation:
    return Recommendation(
        id=str(uuid.uuid4()),
        bucket="test-bucket",
        key=None,
        recommendation_type=RecommendationType.ADD_LIFECYCLE_POLICY,
        risk_level=RiskLevel.LOW,
        reason="Bucket missing lifecycle policy.",
        recommended_action="Add lifecycle rules.",
        estimated_monthly_savings=3.1,
        size_bytes=0,
        storage_class=None,
        last_modified=None,
    )


def _risk_score(rec_id: str) -> RiskScore:
    return RiskScore(
        recommendation_id=rec_id,
        risk_score=21,
        confidence_score=77,
        impact_score=60,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        safe_to_automate=True,
        execution_recommendation="Safe to automate.",
        factors=["Action is reversible.", "Low data loss risk."],
        factor_scores=RiskFactorScores(
            reversibility=90, data_loss_risk=5,
            age_confidence=80, size_impact=60, access_confidence=60,
        ),
    )


def _savings_estimate(rec_id: str) -> SavingsEstimate:
    return SavingsEstimate(
        recommendation_id=rec_id,
        current_monthly_cost=0.023,
        projected_monthly_cost=0.004,
        monthly_savings=0.019,
        transition_cost=0.00002,
        minimum_duration_risk=0.012,
        net_first_month=0.01898,
        net_annual_savings=0.22798,
        break_even_days=0,
        estimate_confidence="high",
        assumptions=["Transition STANDARD -> GLACIER_IR", "Object size 8.00 GB"],
    )


def _savings_summary() -> SavingsSummary:
    return SavingsSummary(
        total_monthly_savings=0.019,
        total_annual_savings=0.22798,
        total_transition_costs=0.00002,
        net_first_month=0.01898,
        high_confidence_count=1,
        medium_confidence_count=0,
        low_confidence_count=0,
    )


def _execution_result(rec: Recommendation, audit_id: str | None = None) -> ExecutionActionResult:
    return ExecutionActionResult(
        audit_id=audit_id or str(uuid.uuid4()),
        recommendation_id=rec.id,
        recommendation_type=rec.recommendation_type,
        bucket=rec.bucket,
        key=rec.key,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        status=ExecutionActionStatus.EXECUTED,
        message="Storage class transition executed.",
        permitted=True,
        required_permissions=["s3:GetObject", "s3:PutObject"],
        missing_permissions=[],
        simulated=False,
        pre_change_state={"bucket": rec.bucket, "storage_class": "STANDARD"},
        post_change_state={"action": "change_storage_class", "target": "GLACIER_IR"},
        rollback_available=True,
        rollback_status=RollbackStatus.PENDING,
    )


def _execute_response(run_id: str, rec: Recommendation) -> ExecuteResponse:
    action = _execution_result(rec)
    return ExecuteResponse(
        execution_id=str(uuid.uuid4()),
        run_id=run_id,
        status=RunStatus.EXECUTED,
        mode=ExecutionMode.FULL,
        dry_run=False,
        eligible=1,
        executed=1,
        skipped=0,
        blocked=0,
        failed=0,
        action_results=[action],
        executed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCreate:
    def test_create_returns_record_with_scanned_status(self, store):
        rec = _rec()
        record = store.create([rec])
        assert record.status == RunStatus.SCANNED

    def test_create_assigns_run_id(self, store):
        record = store.create([_rec()])
        assert record.run_id is not None
        assert len(record.run_id) > 0

    def test_create_and_get_round_trip(self, store):
        rec = _rec()
        created = store.create([rec])
        fetched = store.get(created.run_id)
        assert fetched is not None
        assert fetched.run_id == created.run_id
        assert fetched.status == RunStatus.SCANNED

    def test_create_assigns_unique_run_ids(self, store):
        ids = [store.create([_rec()]).run_id for _ in range(3)]
        assert len(ids) == len(set(ids))

    def test_create_persists_recommendation_fields(self, store):
        rec = _rec()
        created = store.create([rec])
        fetched = store.get(created.run_id)
        r = fetched.recommendations[0]
        assert r.id == rec.id
        assert r.bucket == rec.bucket
        assert r.key == rec.key
        assert r.size_bytes == rec.size_bytes
        assert r.storage_class == rec.storage_class


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGet:
    def test_get_nonexistent_returns_none(self, store):
        assert store.get("does-not-exist") is None

    def test_get_nullable_key_survives_round_trip(self, store):
        rec = _rec_no_key_no_date()
        created = store.create([rec])
        fetched = store.get(created.run_id)
        assert fetched.recommendations[0].key is None

    def test_get_nullable_last_modified_survives_round_trip(self, store):
        rec = _rec_no_key_no_date()
        created = store.create([rec])
        fetched = store.get(created.run_id)
        assert fetched.recommendations[0].last_modified is None

    def test_get_datetime_with_timezone_survives_round_trip(self, store):
        rec = _rec()
        created = store.create([rec])
        fetched = store.get(created.run_id)
        lm = fetched.recommendations[0].last_modified
        assert lm is not None
        # Pydantic may strip tzinfo on deserialisation; check the datetime value is close
        assert abs((lm.replace(tzinfo=timezone.utc) - rec.last_modified).total_seconds()) < 1


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestList:
    def test_list_empty_returns_empty_list(self, store):
        assert store.list() == []

    def test_list_returns_all_runs(self, store):
        store.create([_rec()])
        store.create([_rec()])
        assert len(store.list()) == 2

    def test_list_ordered_by_updated_at_desc(self, store):
        first = store.create([_rec()])
        time.sleep(0.01)
        second = store.create([_rec()])
        records = store.list()
        # Most recently created appears first
        assert records[0].run_id == second.run_id
        assert records[1].run_id == first.run_id


# ---------------------------------------------------------------------------
# set_scores()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSetScores:
    def test_set_scores_updates_status_to_scored(self, store):
        rec = _rec()
        created = store.create([rec])
        score = _risk_score(rec.id)
        estimate = _savings_estimate(rec.id)
        summary = _savings_summary()
        updated = store.set_scores(created.run_id, [score], [estimate], summary)
        assert updated.status == RunStatus.SCORED

    def test_set_scores_nonexistent_run_returns_none(self, store):
        score = _risk_score("x")
        result = store.set_scores("ghost", [score], [], _savings_summary())
        assert result is None

    def test_set_scores_persists_risk_scores(self, store):
        rec = _rec()
        created = store.create([rec])
        score = _risk_score(rec.id)
        store.set_scores(created.run_id, [score], [], _savings_summary())
        fetched = store.get(created.run_id)
        s = fetched.scores[0]
        assert s.recommendation_id == rec.id
        assert s.risk_score == 21
        assert s.factor_scores.reversibility == 90

    def test_set_scores_persists_savings_summary(self, store):
        rec = _rec()
        created = store.create([rec])
        summary = _savings_summary()
        store.set_scores(created.run_id, [_risk_score(rec.id)], [_savings_estimate(rec.id)], summary)
        fetched = store.get(created.run_id)
        assert fetched.savings_summary.total_monthly_savings == pytest.approx(0.019, rel=1e-6)
        assert fetched.savings_summary.high_confidence_count == 1


# ---------------------------------------------------------------------------
# set_execution()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSetExecution:
    def test_set_execution_updates_status_to_executed(self, store):
        rec = _rec()
        created = store.create([rec])
        execution = _execute_response(created.run_id, rec)
        updated = store.set_execution(created.run_id, execution)
        assert updated.status == RunStatus.EXECUTED

    def test_set_execution_inserts_audit_records(self, store):
        rec = _rec()
        created = store.create([rec])
        execution = _execute_response(created.run_id, rec)
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id)
        assert len(audit) == 1

    def test_set_execution_nonexistent_run_returns_none(self, store):
        rec = _rec()
        execution = _execute_response("ghost", rec)
        result = store.set_execution("ghost", execution)
        assert result is None


# ---------------------------------------------------------------------------
# list_execution_audit()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListExecutionAudit:
    def test_list_audit_by_run_id(self, store):
        rec = _rec()
        created = store.create([rec])
        execution = _execute_response(created.run_id, rec)
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id)
        assert len(audit) == 1
        assert audit[0].run_id == created.run_id

    def test_list_audit_filtered_by_execution_id(self, store):
        rec = _rec()
        created = store.create([rec])
        execution = _execute_response(created.run_id, rec)
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id, execution_id=execution.execution_id)
        assert len(audit) == 1

    def test_list_audit_wrong_execution_id_returns_empty(self, store):
        rec = _rec()
        created = store.create([rec])
        execution = _execute_response(created.run_id, rec)
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id, execution_id="wrong-id")
        assert audit == []

    def test_list_audit_filtered_by_audit_ids(self, store):
        rec1, rec2 = _rec(), _rec()
        created = store.create([rec1, rec2])
        action1 = _execution_result(rec1, "audit-aaa")
        action2 = _execution_result(rec2, "audit-bbb")
        execution = ExecuteResponse(
            execution_id=str(uuid.uuid4()),
            run_id=created.run_id,
            status=RunStatus.EXECUTED,
            mode=ExecutionMode.FULL,
            dry_run=False,
            eligible=2, executed=2, skipped=0, blocked=0, failed=0,
            action_results=[action1, action2],
            executed_at=datetime.now(timezone.utc),
        )
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id, audit_ids=["audit-aaa"])
        assert len(audit) == 1
        assert audit[0].audit_id == "audit-aaa"

    def test_list_audit_empty_before_execution(self, store):
        created = store.create([_rec()])
        assert store.list_execution_audit(created.run_id) == []


# ---------------------------------------------------------------------------
# update_rollback_status()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUpdateRollbackStatus:
    def test_update_rollback_status_to_rolled_back(self, store):
        rec = _rec()
        created = store.create([rec])
        execution = _execute_response(created.run_id, rec)
        store.set_execution(created.run_id, execution)
        audit = store.list_execution_audit(created.run_id)
        audit_id = audit[0].audit_id

        result = store.update_rollback_status(audit_id, RollbackStatus.ROLLED_BACK, "Done.")
        assert result is True

        updated_audit = store.list_execution_audit(created.run_id)
        assert updated_audit[0].rollback_status == RollbackStatus.ROLLED_BACK
        assert updated_audit[0].rolled_back_at is not None

    def test_update_nonexistent_audit_id_returns_false(self, store):
        result = store.update_rollback_status("ghost-audit", RollbackStatus.ROLLED_BACK)
        assert result is False
