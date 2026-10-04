"""
Claim assessor for AsliOffer investigation pipeline (Task 10).

Assesses each claim conservative-first, ensuring referential integrity:
- Exactly one AssessedClaim per returned Claim.
- All evidence citations belong to the same claim.
- SUPPORTED claims require at least one SUPPORTS evidence relation.
- CONTRADICTED claims require at least one CONTRADICTS evidence relation.
- No salary support from fixed bands alone.
- Preserves explicit explanations and machine-readable reason codes.
"""

from typing import Dict, List, Optional, Set

from app.schemas.contract import (
    AssessedClaim,
    Claim,
    ClaimKind,
    ClaimStatus,
    EvidenceRecord,
    EvidenceRelation,
    ExtractionStatus,
)
from app.schemas.analysis import AgentFinding
from app.services.agents.scam_classifier import SignalAssessment
from app.services.investigation.claim_builder import is_redaction_placeholder


class ClaimAssessor:
    """
    Produces contract-v1 AssessedClaim records for each extracted Claim.
    """

    def assess_claims(
        self,
        claims: List[Claim],
        evidence_records: List[EvidenceRecord],
        findings: Dict[str, Optional[AgentFinding]],
        scam_assessments: List[SignalAssessment],
        canonical_employer_domain: Optional[str] = None,
        provider_outage: bool = False,
    ) -> List[AssessedClaim]:
        assessed: List[AssessedClaim] = []

        # Index evidence by claim_id
        ev_by_claim: Dict[str, List[EvidenceRecord]] = {}
        for ev in evidence_records:
            ev_by_claim.setdefault(ev.claim_id, []).append(ev)

        comp_finding = findings.get("CompanyAgent")
        rec_finding = findings.get("RecruiterAgent")
        sal_finding = findings.get("SalaryAgent")
        scam_finding = findings.get("ScamAgent")

        for claim in claims:
            cid = claim.claim_id
            kind = claim.kind
            ev_list = ev_by_claim.get(cid, [])
            ev_ids = [e.evidence_id for e in ev_list]
            relations = {e.relation for e in ev_list}

            status: ClaimStatus = ClaimStatus.UNRESOLVED
            explanation: str = ""
            reason_codes: List[str] = []

            # ----------------------------------------------------------------
            # EMPLOYER
            # ----------------------------------------------------------------
            if kind == ClaimKind.EMPLOYER:
                if claim.extraction_status == ExtractionStatus.MISSING or not claim.value:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "No employer was specified in the offer."
                    reason_codes = ["NO_EMPLOYER_SPECIFIED"]
                    ev_ids = []
                elif provider_outage or (comp_finding and comp_finding.details.get("provider_status") == "FAILED"):
                    status = ClaimStatus.UNRESOLVED
                    explanation = "The search provider was unavailable, so the employer could not be checked. This says nothing about the offer either way."
                    reason_codes = ["SEARCH_UNAVAILABLE"]
                elif comp_finding and comp_finding.details.get("official_domain_resolved", False) and canonical_employer_domain:
                    if EvidenceRelation.SUPPORTS in relations:
                        status = ClaimStatus.SUPPORTED
                        explanation = (
                            f"An official employer domain ({canonical_employer_domain}) was resolved from "
                            f"independent results. This shows the employer exists; it does not show this letter came from it."
                        )
                        reason_codes = ["OFFICIAL_DOMAIN_RESOLVED"]
                    else:
                        status = ClaimStatus.UNRESOLVED
                        explanation = f"Employer records found for '{claim.value}', but without direct official domain evidence."
                        reason_codes = ["OFFICIAL_DOMAIN_UNRESOLVED"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = (
                        f"Only sparse or unverified mentions of '{claim.value}' were found, so no official domain "
                        f"could be resolved. A small footprint is common for early startups and is not a warning by itself."
                    )
                    reason_codes = ["SPARSE_FOOTPRINT", "OFFICIAL_DOMAIN_UNRESOLVED"]

            # ----------------------------------------------------------------
            # SENDER_EMAIL
            # ----------------------------------------------------------------
            elif kind == ClaimKind.SENDER_EMAIL:
                if is_redaction_placeholder(claim.value):
                    status = ClaimStatus.NOT_CHECKED
                    explanation = "Sender email is redacted in the document and could not be evaluated."
                    reason_codes = ["REDACTED_IDENTIFIER"]
                    ev_ids = []
                elif provider_outage or (comp_finding and comp_finding.details.get("provider_status") == "FAILED"):
                    status = ClaimStatus.UNRESOLVED
                    explanation = "Depends on the employer domain, which could not be resolved."
                    reason_codes = ["DEPENDENCY_UNRESOLVED"]
                    ev_ids = []
                elif not canonical_employer_domain:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "Without a resolved official domain, the sender domain cannot be checked against anything."
                    reason_codes = ["NO_REFERENCE_DOMAIN"]
                    ev_ids = []
                else:
                    if EvidenceRelation.CONTRADICTS in relations:
                        status = ClaimStatus.CONTRADICTED
                        free_webmail = False
                        if rec_finding:
                            checks = rec_finding.details.get("checks", {})
                            free_webmail = checks.get("recruiter_email", {}).get("is_free_webmail", False)
                        if free_webmail:
                            explanation = (
                                f"The sender uses a free webmail address, while the employer's recruitment email "
                                f"comes from official domain @{canonical_employer_domain}."
                            )
                            reason_codes = ["SENDER_DOMAIN_MISMATCH", "FREE_WEBMAIL_SENDER"]
                        else:
                            explanation = (
                                f"The sender's domain differs from the resolved employer domain "
                                f"@{canonical_employer_domain}."
                            )
                            reason_codes = ["SENDER_DOMAIN_MISMATCH"]
                    elif EvidenceRelation.SUPPORTS in relations:
                        status = ClaimStatus.SUPPORTED
                        explanation = (
                            f"The sender's domain matches the resolved employer domain. "
                            f"This checks the domain only; it does not prove this person sent the letter."
                        )
                        reason_codes = ["SENDER_DOMAIN_ALIGNED"]
                    else:
                        status = ClaimStatus.UNRESOLVED
                        explanation = "Recruiter email domain could not be corroborated from search results."
                        reason_codes = ["NO_REFERENCE_DOMAIN"]
                        ev_ids = []

            # ----------------------------------------------------------------
            # CONTACT_PHONE
            # ----------------------------------------------------------------
            elif kind == ClaimKind.CONTACT_PHONE:
                if is_redaction_placeholder(claim.value):
                    status = ClaimStatus.NOT_CHECKED
                    explanation = "Contact phone is redacted in the document and could not be evaluated."
                    reason_codes = ["REDACTED_IDENTIFIER"]
                    ev_ids = []
                elif EvidenceRelation.CONTRADICTS in relations:
                    status = ClaimStatus.CONTRADICTED
                    explanation = "Public reports allege fraudulent activity or complaints associated with this contact."
                    reason_codes = ["ADVERSE_CONTACT_REPORTS"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "No public scam or corporate directory matches found for this contact number. Absence of reports does not verify legitimacy."
                    reason_codes = ["NO_PUBLIC_LISTING_FOUND"]
                    ev_ids = []

            # ----------------------------------------------------------------
            # RECRUITER_NAME
            # ----------------------------------------------------------------
            elif kind == ClaimKind.RECRUITER_NAME:
                if is_redaction_placeholder(claim.value):
                    status = ClaimStatus.NOT_CHECKED
                    explanation = "Recruiter name is redacted or placeholder."
                    reason_codes = ["REDACTED_IDENTIFIER"]
                    ev_ids = []
                elif EvidenceRelation.SUPPORTS in relations:
                    status = ClaimStatus.SUPPORTED
                    explanation = "Employer records or directory corroborate this recruiter affiliation."
                    reason_codes = ["PUBLIC_LISTING_MATCH"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "No public professional listing was found corroborating this recruiter's affiliation with the employer."
                    reason_codes = ["NO_PUBLIC_LISTING_FOUND"]
                    ev_ids = []

            # ----------------------------------------------------------------
            # ROLE
            # ----------------------------------------------------------------
            elif kind == ClaimKind.ROLE:
                if provider_outage or (comp_finding and comp_finding.details.get("provider_status") == "FAILED"):
                    status = ClaimStatus.NOT_CHECKED
                    explanation = "Skipped after the provider failure."
                    reason_codes = ["SKIPPED_AFTER_FAILURE"]
                    ev_ids = []
                elif EvidenceRelation.SUPPORTS in relations:
                    status = ClaimStatus.SUPPORTED
                    explanation = "A public listing for this role exists on an official or recognized careers portal. This shows the vacancy exists, not that this letter was issued."
                    reason_codes = ["PUBLIC_LISTING_MATCH"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "No public listing for this role was found. Roles can be unlisted or expired, so this is neither support nor a warning."
                    reason_codes = ["NO_PUBLIC_LISTING_FOUND"]
                    ev_ids = []

            # ----------------------------------------------------------------
            # APPLICATION_URL
            # ----------------------------------------------------------------
            elif kind == ClaimKind.APPLICATION_URL:
                if EvidenceRelation.SUPPORTS in relations:
                    status = ClaimStatus.SUPPORTED
                    explanation = "The application link is on the employer's resolved careers domain."
                    reason_codes = ["APPLICATION_URL_ON_OFFICIAL_DOMAIN"]
                elif EvidenceRelation.CONTRADICTS in relations:
                    status = ClaimStatus.CONTRADICTED
                    explanation = "The application destination does not belong to the employer's resolved domain."
                    reason_codes = ["APPLICATION_URL_MISMATCH"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "Application URL could not be corroborated against official employer domains."
                    reason_codes = ["NO_PUBLIC_LISTING_FOUND"]
                    ev_ids = []

            # ----------------------------------------------------------------
            # COMPENSATION
            # ----------------------------------------------------------------
            elif kind == ClaimKind.COMPENSATION:
                # "Salary plausibility needs actual comparable evidence, not merely a fixed band. No salary support from fixed bands alone."
                if EvidenceRelation.SUPPORTS in relations:
                    status = ClaimStatus.SUPPORTED
                    explanation = "Compensation is consistent with comparable public market baselines."
                    reason_codes = ["MARKET_SALARY_MATCH"]
                elif EvidenceRelation.CONTRADICTS in relations:
                    status = ClaimStatus.CONTRADICTED
                    explanation = "Compensation is significantly outside normal market compensation baselines for this role."
                    reason_codes = ["SALARY_OUTLIER"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "No external market compensation baseline could be established from independent salary data."
                    reason_codes = ["NO_SALARY_BENCHMARK"]

            # ----------------------------------------------------------------
            # PAYMENT_REQUEST
            # ----------------------------------------------------------------
            elif kind == ClaimKind.PAYMENT_REQUEST:
                if claim.extraction_status == ExtractionStatus.MISSING or not claim.value:
                    status = ClaimStatus.NOT_CHECKED
                    explanation = "The message contains no payment request."
                    reason_codes = ["NOT_APPLICABLE"]
                    ev_ids = []
                else:
                    if EvidenceRelation.CONTRADICTS in relations:
                        status = ClaimStatus.CONTRADICTED
                        explanation = (
                            "The letter demands a payment to unlock joining or training. "
                            "The employer's published policy or recruitment fraud advisories indicate it never charges candidates."
                        )
                        reason_codes = ["UPFRONT_PAYMENT_DEMAND", "EMPLOYER_NO_FEE_POLICY"]
                    else:
                        status = ClaimStatus.UNRESOLVED
                        explanation = (
                            "The letter contains an upfront payment or deposit demand. "
                            "While no external employer policy page was retrieved, advance fee demands are a severe risk marker."
                        )
                        reason_codes = ["UPFRONT_PAYMENT_DEMAND"]

            # ----------------------------------------------------------------
            # CREDENTIAL_REQUEST
            # ----------------------------------------------------------------
            elif kind == ClaimKind.CREDENTIAL_REQUEST:
                if EvidenceRelation.CONTRADICTS in relations:
                    status = ClaimStatus.CONTRADICTED
                    explanation = "The document requests sensitive banking credentials or OTPs, which legitimate employers never request."
                    reason_codes = ["CREDENTIAL_THEFT_DEMAND"]
                else:
                    status = ClaimStatus.UNRESOLVED
                    explanation = "The letter solicits sensitive account credentials or bank OTPs."
                    reason_codes = ["CREDENTIAL_THEFT_DEMAND"]

            # ----------------------------------------------------------------
            # OTHER CLAIMS (LOCATION, JOB_REFERENCE)
            # ----------------------------------------------------------------
            else:
                status = ClaimStatus.UNRESOLVED
                explanation = f"No independent verification was established for {kind.value}."
                reason_codes = ["NO_PUBLIC_LISTING_FOUND"]
                ev_ids = []

            # Final referential integrity safety checks
            if status == ClaimStatus.SUPPORTED and EvidenceRelation.SUPPORTS not in relations:
                status = ClaimStatus.UNRESOLVED
            if status == ClaimStatus.CONTRADICTED and EvidenceRelation.CONTRADICTS not in relations:
                status = ClaimStatus.UNRESOLVED

            assessed.append(
                AssessedClaim(
                    claim_id=cid,
                    status=status,
                    explanation=explanation,
                    evidence_ids=ev_ids,
                    reason_codes=reason_codes,
                )
            )

        return assessed
