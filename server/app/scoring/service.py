from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import (
    Recommendation,
    RecommendationType,
    RiskFactorScores,
    RiskLevel,
    RiskScore,
    SavingsEstimate,
    SavingsSummary,
)


@dataclass
class ScoringResult:
    scores: list[RiskScore]
    savings_details: list[SavingsEstimate]
    savings_summary: SavingsSummary


class ScoringService:
    WEIGHTS = {
        "reversibility": 30,
        "data_loss_risk": 25,
        "age_confidence": 20,
        "size_impact": 15,
        "access_confidence": 10,
    }

    REVERSIBILITY_SCORES = {
        RecommendationType.CHANGE_STORAGE_CLASS: 90,
        RecommendationType.ADD_LIFECYCLE_POLICY: 100,
        RecommendationType.DELETE_INCOMPLETE_UPLOAD: 100,
        RecommendationType.DELETE_STALE_OBJECT: 0,
    }

    STORAGE_PRICING = {
        "STANDARD": 0.023,
        "INTELLIGENT_TIERING": 0.023,
        "STANDARD_IA": 0.0125,
        "ONEZONE_IA": 0.01,
        "GLACIER_IR": 0.004,
        "GLACIER": 0.0036,
        "DEEP_ARCHIVE": 0.00099,
    }

    TRANSITION_COSTS = {
        "INTELLIGENT_TIERING": 0.0025,
        "STANDARD_IA": 0.01,
        "ONEZONE_IA": 0.01,
        "GLACIER_IR": 0.02,
        "GLACIER": 0.03,
        "DEEP_ARCHIVE": 0.05,
    }

    MIN_STORAGE_DURATION = {
        "STANDARD_IA": 30,
        "ONEZONE_IA": 30,
        "GLACIER_IR": 90,
        "GLACIER": 90,
        "DEEP_ARCHIVE": 180,
    }

    def score(self, recommendations: list[Recommendation]) -> ScoringResult:
        scores: list[RiskScore] = []
        savings_details: list[SavingsEstimate] = []

        for recommendation in recommendations:
            savings = self._calculate_savings(recommendation)
            factor_scores, factor_messages = self._calculate_factor_scores(recommendation)
            risk_score = self._calculate_weighted_risk(factor_scores)
            confidence_score = self._calculate_confidence(factor_scores)
            impact_score = self._calculate_impact_score(savings.monthly_savings)

            risk_level = self._risk_level_from_score(risk_score)
            requires_approval = (
                risk_score >= 55
                or recommendation.recommendation_type == RecommendationType.DELETE_STALE_OBJECT
                or recommendation.size_bytes >= 10 * 1024 * 1024 * 1024
            )
            safe_to_automate = (
                risk_score < 30
                and confidence_score >= 70
                and recommendation.recommendation_type != RecommendationType.DELETE_STALE_OBJECT
            )

            score = RiskScore(
                recommendation_id=recommendation.id,
                risk_score=risk_score,
                confidence_score=confidence_score,
                impact_score=impact_score,
                risk_level=risk_level,
                requires_approval=requires_approval,
                safe_to_automate=safe_to_automate,
                execution_recommendation=self._execution_recommendation(
                    risk_score=risk_score,
                    confidence_score=confidence_score,
                    requires_approval=requires_approval,
                    safe_to_automate=safe_to_automate,
                ),
                factors=factor_messages,
                factor_scores=factor_scores,
            )

            scores.append(score)
            savings_details.append(savings)

        summary = self._aggregate_savings(savings_details)
        return ScoringResult(scores=scores, savings_details=savings_details, savings_summary=summary)

    def _calculate_factor_scores(self, recommendation: Recommendation) -> tuple[RiskFactorScores, list[str]]:
        reversibility = self.REVERSIBILITY_SCORES.get(recommendation.recommendation_type, 50)
        data_loss_risk = self._data_loss_risk(recommendation)
        age_confidence = self._age_confidence(recommendation)
        size_impact = self._size_impact(recommendation)
        access_confidence = self._access_confidence(recommendation)

        factors: list[str] = []
        if reversibility >= 80:
            factors.append("Action is reversible.")
        elif reversibility >= 50:
            factors.append("Action is partially reversible.")
        else:
            factors.append("Action is irreversible.")

        if data_loss_risk >= 70:
            factors.append("High data loss risk.")
        elif data_loss_risk >= 35:
            factors.append("Moderate data loss risk.")
        else:
            factors.append("Low data loss risk.")

        if age_confidence >= 80:
            factors.append("Object age supports high confidence.")
        elif age_confidence >= 50:
            factors.append("Object age provides moderate confidence.")
        else:
            factors.append("Object age data is weak.")

        if size_impact >= 70:
            factors.append("Large data size increases blast radius.")
        elif size_impact >= 40:
            factors.append("Medium data size impact.")
        else:
            factors.append("Small data size impact.")

        if access_confidence >= 70:
            factors.append("Access pattern signal is strong.")
        else:
            factors.append("Access pattern signal is limited.")

        return (
            RiskFactorScores(
                reversibility=reversibility,
                data_loss_risk=data_loss_risk,
                age_confidence=age_confidence,
                size_impact=size_impact,
                access_confidence=access_confidence,
            ),
            factors,
        )

    def _calculate_weighted_risk(self, factors: RiskFactorScores) -> int:
        weighted = (
            (100 - factors.reversibility) * self.WEIGHTS["reversibility"] / 100
            + factors.data_loss_risk * self.WEIGHTS["data_loss_risk"] / 100
            + (100 - factors.age_confidence) * self.WEIGHTS["age_confidence"] / 100
            + factors.size_impact * self.WEIGHTS["size_impact"] / 100
            + (100 - factors.access_confidence) * self.WEIGHTS["access_confidence"] / 100
        )
        return max(0, min(100, int(round(weighted))))

    def _calculate_confidence(self, factors: RiskFactorScores) -> int:
        confidence = int(round((factors.reversibility + factors.age_confidence + factors.access_confidence) / 3))
        return max(0, min(100, confidence))

    def _calculate_impact_score(self, monthly_savings: float) -> int:
        if monthly_savings >= 100:
            return 100
        if monthly_savings >= 50:
            return 80
        if monthly_savings >= 10:
            return 60
        if monthly_savings >= 1:
            return 40
        return 20

    def _risk_level_from_score(self, risk_score: int) -> RiskLevel:
        if risk_score < 30:
            return RiskLevel.LOW
        if risk_score < 60:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH

    def _execution_recommendation(
        self,
        risk_score: int,
        confidence_score: int,
        requires_approval: bool,
        safe_to_automate: bool,
    ) -> str:
        if safe_to_automate:
            return "Safe to automate."
        if requires_approval:
            if risk_score >= 70:
                return "Manual review required before execution."
            return "Explicit approval required before execution."
        if confidence_score < 50:
            return "Collect more usage evidence before execution."
        return "Include in validated execution batch."

    def _data_loss_risk(self, recommendation: Recommendation) -> int:
        if recommendation.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            return 100
        if recommendation.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            return 10
        if recommendation.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            return 5
        return 0

    def _age_confidence(self, recommendation: Recommendation) -> int:
        if recommendation.last_modified is None:
            return 35

        now = datetime.now(timezone.utc)
        days_old = (now - recommendation.last_modified).days
        if days_old >= 365:
            return 95
        if days_old >= 180:
            return 80
        if days_old >= 90:
            return 65
        if days_old >= 30:
            return 45
        return 25

    def _size_impact(self, recommendation: Recommendation) -> int:
        size_gb = recommendation.size_bytes / (1024 ** 3)
        if size_gb >= 100:
            return 100
        if size_gb >= 10:
            return 80
        if size_gb >= 1:
            return 60
        if size_gb >= 0.1:
            return 35
        return 15

    def _access_confidence(self, recommendation: Recommendation) -> int:
        base = 50 if recommendation.last_modified is not None else 35
        reason = recommendation.reason.lower()
        if "infrequent" in reason or "cold" in reason or "stale" in reason:
            base += 10
        return min(100, base)

    def _calculate_savings(self, recommendation: Recommendation) -> SavingsEstimate:
        if recommendation.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            return self._storage_class_savings(recommendation)
        if recommendation.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
            return self._lifecycle_savings(recommendation)
        if recommendation.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            return self._multipart_savings(recommendation)
        if recommendation.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            return self._deletion_savings(recommendation)
        return self._fallback_savings(recommendation)

    def _storage_class_savings(self, recommendation: Recommendation) -> SavingsEstimate:
        assumptions: list[str] = []
        size_gb = recommendation.size_bytes / (1024 ** 3)
        current_class = (recommendation.storage_class or "STANDARD").upper()
        target_class = self._parse_target_class(recommendation.recommended_action)

        current_rate = self.STORAGE_PRICING.get(current_class, self.STORAGE_PRICING["STANDARD"])
        target_rate = self.STORAGE_PRICING.get(target_class, self.STORAGE_PRICING["GLACIER_IR"])

        current_monthly = size_gb * current_rate
        projected_monthly = size_gb * target_rate
        monthly_savings = max(0.0, current_monthly - projected_monthly)

        transition_rate = self.TRANSITION_COSTS.get(target_class, 0.02)
        transition_cost = transition_rate / 1000

        min_days = self.MIN_STORAGE_DURATION.get(target_class, 0)
        minimum_duration_risk = projected_monthly * (min_days / 30) if min_days else 0.0

        net_first_month = monthly_savings - transition_cost
        net_annual = (monthly_savings * 12) - transition_cost

        break_even_days = None
        if monthly_savings > 0:
            break_even_days = int((transition_cost / monthly_savings) * 30)

        assumptions.append(f"Transition {current_class} -> {target_class}")
        assumptions.append(f"Object size {size_gb:.2f} GB")
        if min_days:
            assumptions.append(f"Minimum storage duration {min_days} days")

        confidence = "high" if recommendation.last_modified and recommendation.size_bytes > 0 else "medium"
        if recommendation.size_bytes == 0:
            confidence = "low"

        return SavingsEstimate(
            recommendation_id=recommendation.id,
            current_monthly_cost=current_monthly,
            projected_monthly_cost=projected_monthly,
            monthly_savings=monthly_savings,
            transition_cost=transition_cost,
            minimum_duration_risk=minimum_duration_risk,
            net_first_month=net_first_month,
            net_annual_savings=net_annual,
            break_even_days=break_even_days,
            estimate_confidence=confidence,
            assumptions=assumptions,
        )

    def _lifecycle_savings(self, recommendation: Recommendation) -> SavingsEstimate:
        size_gb = recommendation.size_bytes / (1024 ** 3)
        baseline = recommendation.estimated_monthly_savings if recommendation.estimated_monthly_savings > 0 else 0.5

        if size_gb > 0:
            current_monthly = size_gb * self.STORAGE_PRICING["STANDARD"]
            projected_monthly = current_monthly * 0.7 + (size_gb * self.STORAGE_PRICING["GLACIER_IR"] * 0.3)
            monthly_savings = max(0.0, current_monthly - projected_monthly)
        else:
            current_monthly = baseline / 0.3
            monthly_savings = baseline
            projected_monthly = max(0.0, current_monthly - monthly_savings)

        return SavingsEstimate(
            recommendation_id=recommendation.id,
            current_monthly_cost=current_monthly,
            projected_monthly_cost=projected_monthly,
            monthly_savings=monthly_savings,
            transition_cost=0.0,
            minimum_duration_risk=0.0,
            net_first_month=monthly_savings,
            net_annual_savings=monthly_savings * 12,
            break_even_days=0,
            estimate_confidence="low",
            assumptions=[
                "Assumes 30% of data transitions to GLACIER_IR.",
                "Lifecycle rules can reduce multipart and cold storage cost.",
            ],
        )

    def _multipart_savings(self, recommendation: Recommendation) -> SavingsEstimate:
        if recommendation.size_bytes > 0:
            size_gb = recommendation.size_bytes / (1024 ** 3)
            current_monthly = size_gb * self.STORAGE_PRICING["STANDARD"]
        else:
            current_monthly = max(0.01, recommendation.estimated_monthly_savings)

        return SavingsEstimate(
            recommendation_id=recommendation.id,
            current_monthly_cost=current_monthly,
            projected_monthly_cost=0.0,
            monthly_savings=current_monthly,
            transition_cost=0.0,
            minimum_duration_risk=0.0,
            net_first_month=current_monthly,
            net_annual_savings=current_monthly * 12,
            break_even_days=0,
            estimate_confidence="medium" if recommendation.size_bytes > 0 else "low",
            assumptions=[
                "Incomplete multipart uploads are billed as STANDARD storage.",
                "Aborting upload removes only incomplete upload parts.",
            ],
        )

    def _deletion_savings(self, recommendation: Recommendation) -> SavingsEstimate:
        size_gb = recommendation.size_bytes / (1024 ** 3)
        storage_class = (recommendation.storage_class or "STANDARD").upper()
        rate = self.STORAGE_PRICING.get(storage_class, self.STORAGE_PRICING["STANDARD"])

        current_monthly = size_gb * rate
        if current_monthly <= 0:
            current_monthly = recommendation.estimated_monthly_savings

        return SavingsEstimate(
            recommendation_id=recommendation.id,
            current_monthly_cost=current_monthly,
            projected_monthly_cost=0.0,
            monthly_savings=max(0.0, current_monthly),
            transition_cost=0.0,
            minimum_duration_risk=0.0,
            net_first_month=max(0.0, current_monthly),
            net_annual_savings=max(0.0, current_monthly) * 12,
            break_even_days=0,
            estimate_confidence="high" if recommendation.size_bytes > 0 else "medium",
            assumptions=[
                "Deletion is permanent and removes storage cost to zero.",
                "Current storage class pricing used for estimate.",
            ],
        )

    def _fallback_savings(self, recommendation: Recommendation) -> SavingsEstimate:
        monthly = recommendation.estimated_monthly_savings
        return SavingsEstimate(
            recommendation_id=recommendation.id,
            current_monthly_cost=monthly,
            projected_monthly_cost=0.0,
            monthly_savings=monthly,
            transition_cost=0.0,
            minimum_duration_risk=0.0,
            net_first_month=monthly,
            net_annual_savings=monthly * 12,
            break_even_days=0,
            estimate_confidence="low",
            assumptions=["Fallback estimate using recommendation baseline."],
        )

    def _aggregate_savings(self, estimates: list[SavingsEstimate]) -> SavingsSummary:
        high = len([item for item in estimates if item.estimate_confidence == "high"])
        medium = len([item for item in estimates if item.estimate_confidence == "medium"])
        low = len([item for item in estimates if item.estimate_confidence == "low"])

        return SavingsSummary(
            total_monthly_savings=sum(item.monthly_savings for item in estimates),
            total_annual_savings=sum(item.net_annual_savings for item in estimates),
            total_transition_costs=sum(item.transition_cost for item in estimates),
            net_first_month=sum(item.net_first_month for item in estimates),
            high_confidence_count=high,
            medium_confidence_count=medium,
            low_confidence_count=low,
        )

    def _parse_target_class(self, action: str) -> str:
        normalized = action.lower().replace("-", "_")
        if "deep_archive" in normalized:
            return "DEEP_ARCHIVE"
        if "glacier_ir" in normalized:
            return "GLACIER_IR"
        if "glacier" in normalized:
            return "GLACIER"
        if "intelligent" in normalized:
            return "INTELLIGENT_TIERING"
        if "onezone" in normalized:
            return "ONEZONE_IA"
        if "standard_ia" in normalized:
            return "STANDARD_IA"
        return "GLACIER_IR"

