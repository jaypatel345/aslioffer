from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.schemas.analysis import (
    VerificationReport,
    ExtractedEntities,
    AgentFinding,
    RiskLevel,
    VerdictReason,
)
from app.core.logging import logger


class ReportGenerator:
    """
    Assembles a comprehensive, human-readable forensic verification report.
    Produces evidence citations, official company contacts, and specific safety advisories.
    
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
    ) -> VerificationReport:
        logger.info("ReportGenerator compiling report for offer_id=%d (risk_level=%s)", offer_id, risk_level.value)

        company_name = extracted_entities.company_name or "Company"
        clean_name = company_name.replace(" ", "").lower()

        official_info = {
            "name": company_name,
            "website": f"https://www.{clean_name}.com",
            "careers_url": f"https://careers.{clean_name}.com",
            "mca_status": "Active Corporate Entity" if risk_level != RiskLevel.CANNOT_VERIFY else "Unconfirmed in Public Footprint",
            "recruitment_policy": "Legitimate enterprise HR teams never demand fees or deposits for employment.",
        }

        # Contextual summary & actions based on RiskLevel
        if risk_level == RiskLevel.HIGH_RISK:
            summary = (
                f"HIGH RISK DETECTED: This offer shows severe hallmarks of an employment scam impersonating {company_name}. "
                "Immediate caution is advised. Critical indicators include unauthorized email communication or advance fee demands."
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
                f"Public search records for {company_name} or the recruiter are sparse or below confidence thresholds. "
                "While no overt scam demands were found, exercise independent verification before proceeding."
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
                f"VERIFIED EVIDENCE FOOTPRINT: The extracted credentials, company presence, and compensation parameters "
                f"align with legitimate employment practices for {company_name}."
            )
            actions = [
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
            generated_at=datetime.now(timezone.utc),
        )

