from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.schemas.analysis import (
    VerificationReport,
    ExtractedEntities,
    AgentFinding,
    RiskLevel,
    VerdictReason,
)
from app.services.risk.assessment_engine import AssessmentEngine
from app.services.risk.assessment_models import (
    OverallOutcome,
    AuthenticityStatus,
    WarningBand,
    StructuredAssessment,
)
from app.services.report.presentation_helper import (
    derive_green_flags,
    derive_official_company_info,
    derive_summary,
    derive_recommended_actions,
    derive_reasons_and_details,
)
from app.core.logging import logger


class ReportGenerator:
    """
    Assembles a comprehensive, human-readable forensic verification report.
    Produces evidence citations, official company contacts, and specific safety advisories.
    Separates warning signals, check coverage, and offer authenticity (Task 8 & 9).
    
    TODO: Add automated draft generation for NCRP (National Cyber Crime Reporting Portal - cybercrime.gov.in)
    TODO: Add Community Intelligence submission hook
    """

    def generate(
        self,
        offer_id: int,
        title: str,
        risk_score: float,
        risk_level: RiskLevel,
        extracted_entities: ExtractedEntities,
        findings: List[AgentFinding],
        red_flags: List[str],
        green_flags: List[str],
        reason_details: Optional[List[VerdictReason]] = None,
        structured_assessment: Optional[StructuredAssessment] = None,
    ) -> VerificationReport:
        logger.info("ReportGenerator compiling report for offer_id=%d (risk_level=%s)", offer_id, risk_level.value)

        # Derive canonical structured assessment from findings
        assessment = AssessmentEngine().assess(findings)
        risk_score = assessment.warning_strength
        risk_level = {
            OverallOutcome.HIGH_RISK: RiskLevel.HIGH_RISK,
            OverallOutcome.NEEDS_REVIEW: RiskLevel.NEEDS_REVIEW,
            OverallOutcome.CANNOT_VERIFY: RiskLevel.CANNOT_VERIFY,
            OverallOutcome.NO_STRONG_RISK_SIGNALS: RiskLevel.VERIFIED,
        }[assessment.overall_outcome]

        # Grounded red flags
        red_flags = [s.description for s in assessment.supported_warning_signals + assessment.review_only_concerns]

        # Grounded positive flags (only completed, supported checks)
        green_flags = derive_green_flags(assessment)

        company_name = extracted_entities.company_name or "Company"

        # Official company info strictly from supported CompanyAgent results
        official_info = derive_official_company_info(findings, company_name, assessment)

        # Ground summary in assessment findings and unconfirmed authenticity
        summary = derive_summary(assessment, company_name, extracted_entities)

        # Signal-specific, deduplicated actions
        actions = derive_recommended_actions(assessment, extracted_entities)

        # Canonical reason details (stale caller reasons cannot contradict assessment)
        _, canonical_reason_details = derive_reasons_and_details(
            assessment=assessment,
            findings=findings,
            evidence_count=len(assessment.supporting_evidence_refs),
        )

        return VerificationReport(
            offer_id=offer_id,
            title=title,
            risk_level=risk_level,
            risk_score=risk_score,
            summary=summary,
            extracted_entities=extracted_entities,
            findings=findings,
            red_flags=red_flags,
            green_flags=green_flags,
            official_company_info=official_info,
            recommended_actions=actions,
            reason_details=canonical_reason_details,
            overall_outcome=assessment.overall_outcome,
            authenticity_status=assessment.authenticity_status,
            warning_band=assessment.warning_band,
            structured_assessment=assessment,
            generated_at=datetime.now(timezone.utc),
        )

