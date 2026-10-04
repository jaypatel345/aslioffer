from typing import List, Tuple, Optional
from app.schemas.analysis import AgentFinding, RiskLevel
from app.services.risk.assessment_engine import AssessmentEngine
from app.services.risk.assessment_models import (
    OverallOutcome,
    ExecutionStatus,
    ResolutionStatus,
    StructuredAssessment,
)
from app.core.logging import logger


class RiskEngine:
    """
    Synthesizes findings from CompanyAgent, RecruiterAgent, SalaryAgent, and ScamAgent.
    Delegates to the unified AssessmentEngine (Task 8) to maintain a single coherent policy
    across RiskEngine and VerdictReasoner.
    
    Warning index (risk_score) is an uncalibrated signal metric (0.0 to 1.0), never a fraud probability.
    Artificial minimum of 0.05 is removed: clean or unavailable checks with zero supported
    adverse signals yield warning strength 0.0.
    """

    def __init__(self, assessment_engine: Optional[AssessmentEngine] = None):
        self.engine = assessment_engine or AssessmentEngine()

    def assess(self, findings: List[AgentFinding]) -> StructuredAssessment:
        """New structured assessment entrypoint."""
        return self.engine.assess(findings)

    def compute_risk(self, findings: List[AgentFinding]) -> Tuple[float, RiskLevel, List[str], List[str]]:
        """
        Backward-compatible risk calculation entrypoint.
        Returns (risk_score, risk_level, red_flags, green_flags).
        """
        logger.info("RiskEngine evaluating %d agent findings via unified AssessmentEngine", len(findings))

        assessment = self.engine.assess(findings)

        # Map overall outcome to legacy RiskLevel
        outcome_map = {
            OverallOutcome.HIGH_RISK: RiskLevel.HIGH_RISK,
            OverallOutcome.NEEDS_REVIEW: RiskLevel.NEEDS_REVIEW,
            OverallOutcome.CANNOT_VERIFY: RiskLevel.CANNOT_VERIFY,
            OverallOutcome.NO_STRONG_RISK_SIGNALS: RiskLevel.VERIFIED,
        }
        risk_level = outcome_map[assessment.overall_outcome]
        risk_score = assessment.warning_strength

        # Red flags: from supported strong signals and review concerns
        red_flags: List[str] = []
        for s in assessment.supported_warning_signals:
            red_flags.append(s.description)
        for c in assessment.review_only_concerns:
            red_flags.append(c.description)

        # Green flags: generated ONLY for checks that genuinely ran and were supported/clean
        from app.services.report.presentation_helper import derive_green_flags
        green_flags: List[str] = derive_green_flags(assessment)

        logger.info("RiskEngine assessment complete: outcome=%s, score=%.2f, level=%s",
                    assessment.overall_outcome.value, risk_score, risk_level.value)
        return risk_score, risk_level, red_flags, green_flags

