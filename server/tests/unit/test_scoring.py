"""
Unit tests for ScoringService.

All numeric assertions are derived from the actual weights and pricing tables
in app/scoring/service.py. Computed values are documented inline.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models import (
    Recommendation,
    RecommendationType,
    RiskFactorScores,
    RiskLevel,
)
from app.scoring.service import ScoringService

GB = 1024 ** 3

svc = ScoringService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(
    rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
    size_bytes=GB,
    storage_class="STANDARD",
    last_modified_days_ago=None,
    reason="Object appears cold based on age and path.",
    recommended_action="Transition to GLACIER_IR",
    estimated_monthly_savings=10.0,
) -> Recommendation:
    last_modified = None
    if last_modified_days_ago is not None:
        last_modified = datetime.now(timezone.utc) - timedelta(days=last_modified_days_ago)
    return Recommendation(
        id="rec-test",
        bucket="test-bucket",
        key="test/key.parquet",
        recommendation_type=rec_type,
        risk_level=RiskLevel.LOW,
        reason=reason,
        recommended_action=recommended_action,
        estimated_monthly_savings=estimated_monthly_savings,
        size_bytes=size_bytes,
        storage_class=storage_class,
        last_modified=last_modified,
    )


# ---------------------------------------------------------------------------
# Risk level boundaries (tested directly on private helpers)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRiskLevelBoundaries:
    def test_score_0_is_low(self):
        assert svc._risk_level_from_score(0) == RiskLevel.LOW

    def test_score_29_is_low(self):
        assert svc._risk_level_from_score(29) == RiskLevel.LOW

    def test_score_30_is_medium(self):
        assert svc._risk_level_from_score(30) == RiskLevel.MEDIUM

    def test_score_59_is_medium(self):
        assert svc._risk_level_from_score(59) == RiskLevel.MEDIUM

    def test_score_60_is_high(self):
        assert svc._risk_level_from_score(60) == RiskLevel.HIGH

    def test_score_100_is_high(self):
        assert svc._risk_level_from_score(100) == RiskLevel.HIGH


# ---------------------------------------------------------------------------
# Weighted risk calculation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWeightedRiskCalculation:
    """
    Formula: (100 - rev)*0.30 + data_loss*0.25 + (100 - age)*0.20
             + size*0.15 + (100 - access)*0.10
    """

    def test_lifecycle_policy_risk_score(self):
        # reversibility=100, data_loss=0, age_confidence=35, size_impact=15, access=35
        # (0)*0.30 + 0*0.25 + 65*0.20 + 15*0.15 + 65*0.10 = 0+0+13+2.25+6.5 = 21.75 → 22
        factors = RiskFactorScores(
            reversibility=100, data_loss_risk=0,
            age_confidence=35, size_impact=15, access_confidence=35,
        )
        assert svc._calculate_weighted_risk(factors) == 22

    def test_change_storage_class_risk_score(self):
        # reversibility=90, data_loss=5, age=80, size=60, access=60
        # 3 + 1.25 + 4 + 9 + 4 = 21.25 → 21
        factors = RiskFactorScores(
            reversibility=90, data_loss_risk=5,
            age_confidence=80, size_impact=60, access_confidence=60,
        )
        assert svc._calculate_weighted_risk(factors) == 21

    def test_delete_stale_object_risk_score(self):
        # reversibility=0, data_loss=100, age=35, size=15, access=45
        # 30 + 25 + 13 + 2.25 + 5.5 = 75.75 → 76
        factors = RiskFactorScores(
            reversibility=0, data_loss_risk=100,
            age_confidence=35, size_impact=15, access_confidence=45,
        )
        assert svc._calculate_weighted_risk(factors) == 76

    def test_result_clamped_to_0_100(self):
        factors = RiskFactorScores(
            reversibility=0, data_loss_risk=100,
            age_confidence=0, size_impact=100, access_confidence=0,
        )
        result = svc._calculate_weighted_risk(factors)
        assert 0 <= result <= 100


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfidenceCalculation:
    def test_confidence_formula(self):
        # confidence = (reversibility + age_confidence + access_confidence) / 3
        factors = RiskFactorScores(
            reversibility=90, data_loss_risk=5,
            age_confidence=80, size_impact=60, access_confidence=60,
        )
        # (90 + 80 + 60) / 3 = 76.67 → 77
        assert svc._calculate_confidence(factors) == 77

    def test_confidence_low_without_last_modified(self):
        factors = RiskFactorScores(
            reversibility=100, data_loss_risk=0,
            age_confidence=35, size_impact=15, access_confidence=35,
        )
        # (100 + 35 + 35) / 3 = 56.67 → 57
        assert svc._calculate_confidence(factors) == 57


# ---------------------------------------------------------------------------
# Impact score
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestImpactScore:
    def test_savings_below_1(self):
        assert svc._calculate_impact_score(0.5) == 20

    def test_savings_exactly_1(self):
        assert svc._calculate_impact_score(1.0) == 40

    def test_savings_below_10(self):
        assert svc._calculate_impact_score(9.99) == 40

    def test_savings_exactly_10(self):
        assert svc._calculate_impact_score(10.0) == 60

    def test_savings_below_50(self):
        assert svc._calculate_impact_score(49.99) == 60

    def test_savings_exactly_50(self):
        assert svc._calculate_impact_score(50.0) == 80

    def test_savings_below_100(self):
        assert svc._calculate_impact_score(99.99) == 80

    def test_savings_exactly_100(self):
        assert svc._calculate_impact_score(100.0) == 100


# ---------------------------------------------------------------------------
# Age confidence
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAgeConfidence:
    def test_no_last_modified_returns_35(self):
        rec = _rec(last_modified_days_ago=None)
        assert svc._age_confidence(rec) == 35

    def test_age_under_30_days_returns_25(self):
        rec = _rec(last_modified_days_ago=10)
        assert svc._age_confidence(rec) == 25

    def test_age_30_to_89_days_returns_45(self):
        rec = _rec(last_modified_days_ago=50)
        assert svc._age_confidence(rec) == 45

    def test_age_90_to_179_days_returns_65(self):
        rec = _rec(last_modified_days_ago=100)
        assert svc._age_confidence(rec) == 65

    def test_age_180_to_364_days_returns_80(self):
        rec = _rec(last_modified_days_ago=200)
        assert svc._age_confidence(rec) == 80

    def test_age_365_plus_days_returns_95(self):
        rec = _rec(last_modified_days_ago=400)
        assert svc._age_confidence(rec) == 95


# ---------------------------------------------------------------------------
# Size impact
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSizeImpact:
    def test_size_under_100mb_returns_15(self):
        rec = _rec(size_bytes=50 * 1024 * 1024)
        assert svc._size_impact(rec) == 15

    def test_size_100mb_to_1gb_returns_35(self):
        rec = _rec(size_bytes=500 * 1024 * 1024)
        assert svc._size_impact(rec) == 35

    def test_size_1gb_to_10gb_returns_60(self):
        rec = _rec(size_bytes=5 * GB)
        assert svc._size_impact(rec) == 60

    def test_size_10gb_to_100gb_returns_80(self):
        rec = _rec(size_bytes=50 * GB)
        assert svc._size_impact(rec) == 80

    def test_size_100gb_plus_returns_100(self):
        rec = _rec(size_bytes=200 * GB)
        assert svc._size_impact(rec) == 100

    def test_size_zero_returns_15(self):
        rec = _rec(size_bytes=0)
        assert svc._size_impact(rec) == 15


# ---------------------------------------------------------------------------
# Access confidence
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAccessConfidence:
    def test_no_last_modified_base_is_35(self):
        rec = _rec(last_modified_days_ago=None, reason="Unrelated reason.")
        assert svc._access_confidence(rec) == 35

    def test_last_modified_set_base_is_50(self):
        rec = _rec(last_modified_days_ago=100, reason="Unrelated reason.")
        assert svc._access_confidence(rec) == 50

    def test_cold_in_reason_adds_10(self):
        rec = _rec(last_modified_days_ago=100, reason="Object appears cold based on age.")
        assert svc._access_confidence(rec) == 60

    def test_infrequent_in_reason_adds_10(self):
        rec = _rec(last_modified_days_ago=100, reason="Object infrequently accessed.")
        assert svc._access_confidence(rec) == 60

    def test_stale_in_reason_adds_10(self):
        rec = _rec(last_modified_days_ago=None, reason="Old stale data.")
        assert svc._access_confidence(rec) == 45

    def test_access_confidence_capped_at_100(self):
        rec = _rec(last_modified_days_ago=100, reason="Object infrequently cold stale data.")
        assert svc._access_confidence(rec) <= 100


# ---------------------------------------------------------------------------
# requires_approval and safe_to_automate flags (tested through public score())
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestApprovalFlags:
    def test_delete_stale_always_requires_approval(self):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT, size_bytes=0)
        result = svc.score([rec])
        assert result.scores[0].requires_approval is True

    def test_large_object_requires_approval(self):
        # size >= 10 GB triggers requires_approval regardless of type/risk
        rec = _rec(
            rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
            size_bytes=10 * GB,
            last_modified_days_ago=200,
        )
        result = svc.score([rec])
        assert result.scores[0].requires_approval is True

    def test_small_lifecycle_policy_no_requires_approval(self):
        rec = _rec(
            rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
            size_bytes=0,
            last_modified_days_ago=None,
            reason="Bucket has no lifecycle policy.",
            recommended_action="Add lifecycle rules",
            estimated_monthly_savings=3.1,
        )
        result = svc.score([rec])
        assert result.scores[0].requires_approval is False

    def test_safe_to_automate_true_for_old_object(self):
        # ADD_LIFECYCLE_POLICY, 200 days old, no cold/stale/infrequent in reason
        # risk=11, confidence=77 → safe_to_automate=True
        rec = _rec(
            rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
            size_bytes=0,
            last_modified_days_ago=200,
            reason="Bucket has no lifecycle policy for archival.",
            recommended_action="Add lifecycle rules",
            estimated_monthly_savings=3.1,
        )
        result = svc.score([rec])
        score = result.scores[0]
        assert score.safe_to_automate is True

    def test_safe_to_automate_false_low_confidence(self):
        # ADD_LIFECYCLE_POLICY, no last_modified → confidence=57 < 70 → False
        rec = _rec(
            rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
            size_bytes=0,
            last_modified_days_ago=None,
            reason="Bucket has no lifecycle policy.",
            recommended_action="Add lifecycle rules",
            estimated_monthly_savings=3.1,
        )
        result = svc.score([rec])
        assert result.scores[0].safe_to_automate is False

    def test_safe_to_automate_false_for_delete_stale_object(self):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT, size_bytes=0)
        result = svc.score([rec])
        assert result.scores[0].safe_to_automate is False


# ---------------------------------------------------------------------------
# Target class parsing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTargetClassParsing:
    def test_parse_glacier_ir(self):
        assert svc._parse_target_class("Transition to GLACIER_IR") == "GLACIER_IR"

    def test_parse_deep_archive(self):
        assert svc._parse_target_class("Transition to DEEP_ARCHIVE") == "DEEP_ARCHIVE"

    def test_parse_glacier_plain(self):
        assert svc._parse_target_class("Move to Glacier storage") == "GLACIER"

    def test_parse_intelligent_tiering(self):
        assert svc._parse_target_class("Use Intelligent-Tiering") == "INTELLIGENT_TIERING"

    def test_parse_onezone_ia(self):
        assert svc._parse_target_class("Move to ONEZONE_IA") == "ONEZONE_IA"

    def test_parse_standard_ia(self):
        assert svc._parse_target_class("Transition to STANDARD_IA") == "STANDARD_IA"

    def test_parse_unknown_defaults_to_glacier_ir(self):
        assert svc._parse_target_class("Move to some unknown class") == "GLACIER_IR"

    def test_parse_is_case_insensitive(self):
        assert svc._parse_target_class("transition to glacier_ir") == "GLACIER_IR"


# ---------------------------------------------------------------------------
# Savings math: CHANGE_STORAGE_CLASS
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStorageClassSavings:
    def test_standard_to_glacier_ir_1gb(self):
        """
        size_gb=1.0, STANDARD→GLACIER_IR:
          current_monthly = 1.0 * 0.023 = 0.023
          projected_monthly = 1.0 * 0.004 = 0.004
          monthly_savings = 0.019
          transition_cost = 0.02 / 1000 = 0.00002
          minimum_duration_risk = 0.004 * (90/30) = 0.012
          net_first_month = 0.019 - 0.00002 = 0.01898
          net_annual = (0.019 * 12) - 0.00002 = 0.22798
          break_even_days = int(0.00002/0.019 * 30) = 0
        """
        rec = _rec(
            rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
            size_bytes=GB,
            storage_class="STANDARD",
            last_modified_days_ago=220,
            recommended_action="Transition to GLACIER_IR",
        )
        estimate = svc._storage_class_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(0.023, rel=1e-6)
        assert estimate.projected_monthly_cost == pytest.approx(0.004, rel=1e-6)
        assert estimate.monthly_savings == pytest.approx(0.019, rel=1e-6)
        assert estimate.transition_cost == pytest.approx(0.00002, rel=1e-6)
        assert estimate.minimum_duration_risk == pytest.approx(0.012, rel=1e-6)
        assert estimate.net_first_month == pytest.approx(0.01898, rel=1e-6)
        assert estimate.net_annual_savings == pytest.approx(0.22798, rel=1e-6)
        assert estimate.break_even_days == 0

    def test_standard_to_deep_archive_1gb(self):
        """
        size_gb=1.0, STANDARD→DEEP_ARCHIVE:
          current=0.023, projected=0.00099
          savings=0.02201, transition_cost=0.05/1000=0.00005
          minimum_duration_risk=0.00099*(180/30)=0.00594
        """
        rec = _rec(
            rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
            size_bytes=GB,
            storage_class="STANDARD",
            last_modified_days_ago=400,
            recommended_action="Transition to DEEP_ARCHIVE",
        )
        estimate = svc._storage_class_savings(rec)
        assert estimate.transition_cost == pytest.approx(0.00005, rel=1e-6)
        assert estimate.minimum_duration_risk == pytest.approx(0.00594, rel=1e-5)
        assert estimate.monthly_savings == pytest.approx(0.02201, rel=1e-5)

    def test_confidence_high_with_known_size_and_last_modified(self):
        rec = _rec(size_bytes=GB, last_modified_days_ago=200)
        estimate = svc._storage_class_savings(rec)
        assert estimate.estimate_confidence == "high"

    def test_confidence_low_when_size_is_zero(self):
        rec = _rec(size_bytes=0, last_modified_days_ago=200)
        estimate = svc._storage_class_savings(rec)
        assert estimate.estimate_confidence == "low"

    def test_break_even_days_is_none_when_no_savings(self):
        # STANDARD→STANDARD: same rate → monthly_savings = 0
        rec = _rec(
            size_bytes=GB,
            storage_class="STANDARD",
            recommended_action="Use INTELLIGENT_TIERING",
        )
        # INTELLIGENT_TIERING has same price as STANDARD (0.023) → savings = 0
        estimate = svc._storage_class_savings(rec)
        assert estimate.monthly_savings == pytest.approx(0.0, abs=1e-9)
        assert estimate.break_even_days is None


# ---------------------------------------------------------------------------
# Savings math: ADD_LIFECYCLE_POLICY
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLifecycleSavings:
    def test_lifecycle_with_nonzero_size(self):
        """
        size_gb=1.0:
          current_monthly = 1.0 * 0.023 = 0.023
          projected = 0.023*0.7 + 1.0*0.004*0.3 = 0.0161+0.0012 = 0.0173
          monthly_savings = 0.023 - 0.0173 = 0.0057
        """
        rec = _rec(
            rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
            size_bytes=GB,
            recommended_action="Add lifecycle rules",
            estimated_monthly_savings=3.1,
        )
        estimate = svc._lifecycle_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(0.023, rel=1e-6)
        assert estimate.monthly_savings == pytest.approx(0.0057, rel=1e-4)

    def test_lifecycle_with_zero_size_uses_baseline(self):
        """
        size=0, estimated=3.1:
          current = 3.1 / 0.3 = 10.333...
          monthly_savings = 3.1
        """
        rec = _rec(
            rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
            size_bytes=0,
            recommended_action="Add lifecycle rules",
            estimated_monthly_savings=3.1,
        )
        estimate = svc._lifecycle_savings(rec)
        assert estimate.monthly_savings == pytest.approx(3.1, rel=1e-6)
        assert estimate.current_monthly_cost == pytest.approx(3.1 / 0.3, rel=1e-6)

    def test_lifecycle_always_low_confidence(self):
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=GB)
        estimate = svc._lifecycle_savings(rec)
        assert estimate.estimate_confidence == "low"

    def test_lifecycle_zero_transition_cost(self):
        rec = _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY, size_bytes=GB)
        estimate = svc._lifecycle_savings(rec)
        assert estimate.transition_cost == 0.0


# ---------------------------------------------------------------------------
# Savings math: DELETE_INCOMPLETE_UPLOAD
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMultipartSavings:
    def test_multipart_with_known_size(self):
        """size_gb=2.0: current = 2.0 * 0.023 = 0.046, savings = 0.046."""
        rec = _rec(
            rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
            size_bytes=2 * GB,
            estimated_monthly_savings=0.0,
        )
        estimate = svc._multipart_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(0.046, rel=1e-6)
        assert estimate.monthly_savings == pytest.approx(0.046, rel=1e-6)
        assert estimate.estimate_confidence == "medium"

    def test_multipart_zero_size_uses_estimated(self):
        rec = _rec(
            rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
            size_bytes=0,
            estimated_monthly_savings=5.0,
        )
        estimate = svc._multipart_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(5.0, rel=1e-6)
        assert estimate.estimate_confidence == "low"

    def test_multipart_zero_size_zero_estimated_uses_minimum(self):
        rec = _rec(
            rec_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
            size_bytes=0,
            estimated_monthly_savings=0.0,
        )
        estimate = svc._multipart_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(0.01, rel=1e-6)


# ---------------------------------------------------------------------------
# Savings math: DELETE_STALE_OBJECT
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDeletionSavings:
    def test_deletion_standard_storage_1gb(self):
        """current = 1.0 * 0.023 = 0.023."""
        rec = _rec(
            rec_type=RecommendationType.DELETE_STALE_OBJECT,
            size_bytes=GB,
            storage_class="STANDARD",
        )
        estimate = svc._deletion_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(0.023, rel=1e-6)
        assert estimate.monthly_savings == pytest.approx(0.023, rel=1e-6)
        assert estimate.estimate_confidence == "high"

    def test_deletion_glacier_pricing(self):
        """GLACIER rate = 0.0036."""
        rec = _rec(
            rec_type=RecommendationType.DELETE_STALE_OBJECT,
            size_bytes=GB,
            storage_class="GLACIER",
        )
        estimate = svc._deletion_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(0.0036, rel=1e-6)

    def test_deletion_zero_size_uses_estimated(self):
        rec = _rec(
            rec_type=RecommendationType.DELETE_STALE_OBJECT,
            size_bytes=0,
            estimated_monthly_savings=5.0,
        )
        estimate = svc._deletion_savings(rec)
        assert estimate.current_monthly_cost == pytest.approx(5.0, rel=1e-6)
        assert estimate.estimate_confidence == "medium"

    def test_deletion_projected_cost_is_zero(self):
        rec = _rec(rec_type=RecommendationType.DELETE_STALE_OBJECT, size_bytes=GB)
        estimate = svc._deletion_savings(rec)
        assert estimate.projected_monthly_cost == 0.0


# ---------------------------------------------------------------------------
# SavingsSummary aggregation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSavingsSummary:
    def test_totals_are_summed_correctly(self):
        recs = [
            _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
                 size_bytes=GB, last_modified_days_ago=220),
            _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                 size_bytes=0, estimated_monthly_savings=3.1,
                 reason="Bucket has no lifecycle policy.",
                 recommended_action="Add lifecycle rules"),
        ]
        result = svc.score(recs)
        total = sum(e.monthly_savings for e in result.savings_details)
        assert result.savings_summary.total_monthly_savings == pytest.approx(total, rel=1e-6)

    def test_confidence_counts_are_correct(self):
        recs = [
            _rec(rec_type=RecommendationType.CHANGE_STORAGE_CLASS,
                 size_bytes=GB, last_modified_days_ago=220),   # high
            _rec(rec_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                 size_bytes=0, estimated_monthly_savings=3.1,
                 reason="Bucket has no lifecycle policy.",
                 recommended_action="Add lifecycle rules"),     # low
        ]
        result = svc.score(recs)
        summary = result.savings_summary
        assert summary.high_confidence_count + summary.medium_confidence_count + summary.low_confidence_count == len(recs)

    def test_empty_recommendations_returns_zero_summary(self):
        result = svc.score([])
        assert result.savings_summary.total_monthly_savings == 0.0
        assert result.savings_summary.high_confidence_count == 0
