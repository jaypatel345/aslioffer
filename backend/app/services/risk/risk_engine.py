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
        green_flags: List[str] = []
        check_dict = {c.check_id: c for c in assessment.individual_checks}

        local_scan = check_dict.get("LOCAL_DOCUMENT_SCAN")
        ext_scam = check_dict.get("EXTERNAL_SCAM_REPORTS")
        if (
            local_scan
            and local_scan.execution_status == ExecutionStatus.COMPLETED
            and local_scan.resolution_status == ResolutionStatus.NO_MATCH
            and ext_scam
            and ext_scam.execution_status == ExecutionStatus.COMPLETED
        ):
            green_flags.append("No advance fee demands, security deposits, or OTP requests found.")

        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if comp_check and comp_check.execution_status == ExecutionStatus.COMPLETED and comp_check.resolution_status == ResolutionStatus.SUPPORTED:
            green_flags.append("Company public web presence matched; registration has not been checked.")

        rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
        if rec_aff and rec_aff.execution_status == ExecutionStatus.COMPLETED and rec_aff.resolution_status == ResolutionStatus.SUPPORTED:
            green_flags.append("Recruiter credentials consistent with corporate domain standards; does not authenticate individual offer.")

        sal_check = check_dict.get("COMPENSATION_BENCHMARK")
        if sal_check and sal_check.execution_status == ExecutionStatus.COMPLETED and sal_check.resolution_status == ResolutionStatus.SUPPORTED:
            green_flags.append("Compensation package falls within expected market baseline.")

        logger.info("RiskEngine assessment complete: outcome=%s, score=%.2f, level=%s",
                    assessment.overall_outcome.value, risk_score, risk_level.value)
        return risk_score, risk_level, red_flags, green_flags

