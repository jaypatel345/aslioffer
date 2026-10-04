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
from app.core.logging import logger


class ReportGenerator:
    """
    Assembles a comprehensive, human-readable forensic verification report.
    Produces evidence citations, official company contacts, and specific safety advisories.
    Separates warning signals, check coverage, and offer authenticity (Task 8).
    
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

        # Derive or use provided structured assessment
        assessment = AssessmentEngine().assess(findings)
        risk_score = assessment.warning_strength
        risk_level = {OverallOutcome.HIGH_RISK: RiskLevel.HIGH_RISK,
                      OverallOutcome.NEEDS_REVIEW: RiskLevel.NEEDS_REVIEW,
                      OverallOutcome.CANNOT_VERIFY: RiskLevel.CANNOT_VERIFY,
                      OverallOutcome.NO_STRONG_RISK_SIGNALS: RiskLevel.VERIFIED}[assessment.overall_outcome]
        red_flags = [s.description for s in assessment.supported_warning_signals + assessment.review_only_concerns]
        from app.services.risk.risk_engine import RiskEngine
        _, _, _, green_flags = RiskEngine().compute_risk(findings)

        company_name = extracted_entities.company_name or "Company"

        # Report the domain the CompanyAgent actually matched.
        company_finding = next((f for f in findings if f.agent_name == "CompanyAgent"), None)
        company_details = (company_finding.details or {}) if company_finding else {}
        official_domain = company_details.get("official_domain")
        careers_url = company_details.get("careers_url")

        official_info = {
            "name": company_name,
            "website": official_domain,
            "careers_url": careers_url,
            "mca_status": "Not independently checked",
            "recruitment_policy": "Legitimate enterprise HR teams never demand fees or deposits for employment.",
        }

        # Contextual summary & actions based on RiskLevel
        if risk_level == RiskLevel.HIGH_RISK:
            headline = red_flags[0] if red_flags else "multiple verification checks failed"
            extra = f" ({len(red_flags) - 1} further concern(s) listed below.)" if len(red_flags) > 1 else ""
            summary = (
                f"HIGH RISK: this offer did not pass verification. {headline}{extra} "
                "Treat the offer as unsafe until you have confirmed it through the employer's "
                "own published contact details."
            )
            actions = [
                "DO NOT pay any registration fee, security deposit, or laptop charge under any circumstance.",
                "DO NOT share sensitive personal documents (Aadhaar card, PAN card, bank details, or OTPs).",
                "Contact the official employer directly using their verified careers portal or corporate switchboard.",
                "Report this incident immediately to the National Cyber Crime Reporting Portal at https://cybercrime.gov.in or call helpline 1930.",
                "Block and report the sender's phone number and Telegram/WhatsApp accounts.",
            ]
        elif risk_level == RiskLevel.CANNOT_VERIFY:
            summary = (
                f"INCONCLUSIVE PUBLIC EVIDENCE: Could not independently verify this offer from available evidence. "
                "Some checks were unavailable or did not establish sufficient evidence. "
                "This is not proof of fraud; confirm the offer independently before proceeding."
            )
            actions = [
                "Could not independently verify this offer from available evidence.",
                "Verify the employer independently through official business registries (such as MCA India).",
                "Request the recruiter to send an official confirmation from a verifiable corporate domain.",
                "Do NOT transfer any money, deposits, or share Aadhaar/PAN details until verified.",
                "Independently look up the company's registered office phone number and call their main switchboard.",
            ]
        elif risk_level == RiskLevel.NEEDS_REVIEW:
            summary = (
                f"NEEDS MANUAL REVIEW: Key aspects of this offer could not be definitively verified. "
                f"While {company_name} is an established company, the recruiter's identity or compensation structure requires independent confirmation."
            )
            actions = [
                "Verify this job opening directly on the company's official careers site before accepting.",
                "Do not send money or banking credentials until independently confirmed with corporate HR.",
                "Check LinkedIn to verify if the recruiter is an active employee at the company.",
                "Ask the recruiter to email you from their official corporate domain address.",
            ]
        else:
            summary = (
                f"NO STRONG RISK SIGNALS: The extracted credentials, company presence, and compensation parameters "
                f"align with legitimate employment practices for {company_name}. "
                "Note: The employer has not authenticated this individual offer; public web checks cannot establish offer authenticity."
            )
            actions = [
                "Confirm this specific offer with the employer through their official published careers contact.",
                "Review standard employment terms and non-disclosure agreements carefully.",
                "Verify the offer reference code on the company's internal applicant tracking system if provided.",
                "Never share bank login details or passwords during onboarding.",
            ]

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
            reason_details=reason_details or [],
            overall_outcome=assessment.overall_outcome,
            authenticity_status=assessment.authenticity_status,
            warning_band=assessment.warning_band,
            structured_assessment=assessment,
            generated_at=datetime.now(timezone.utc),
        )

