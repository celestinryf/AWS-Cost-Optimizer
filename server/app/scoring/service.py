from app.models import Recommendation, RecommendationType, RiskLevel, RiskScore


class ScoringService:
    def score(self, recommendations: list[Recommendation]) -> list[RiskScore]:
        scores: list[RiskScore] = []

        for rec in recommendations:
            risk_score = self._risk_score(rec)
            confidence_score = self._confidence_score(rec)
            requires_approval = (
                risk_score >= 50 or rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT
            )
            safe_to_automate = (
                risk_score < 30
                and confidence_score >= 70
                and rec.recommendation_type != RecommendationType.DELETE_STALE_OBJECT
            )

            scores.append(
                RiskScore(
                    recommendation_id=rec.id,
                    risk_score=risk_score,
                    confidence_score=confidence_score,
                    requires_approval=requires_approval,
                    safe_to_automate=safe_to_automate,
                )
            )

        return scores

    def _risk_score(self, rec: Recommendation) -> int:
        base_by_level = {
            RiskLevel.LOW: 20,
            RiskLevel.MEDIUM: 45,
            RiskLevel.HIGH: 80,
        }
        base = base_by_level.get(rec.risk_level, 50)

        if rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            base = max(base, 85)
        if rec.size_bytes >= 10 * 1024 * 1024 * 1024:
            base = min(base + 10, 100)

        return base

    def _confidence_score(self, rec: Recommendation) -> int:
        if rec.last_modified is None:
            return 55
        return 80

