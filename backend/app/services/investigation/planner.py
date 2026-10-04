"""
Deterministic adaptive investigation planner for AsliOffer (Task 11).

Examines unresolved or conflicting findings from initial checks and generates
targeted, prioritized follow-up search steps with explicit rationale.
"""
from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Set

from app.schemas.contract import CaseInput, Claim, ClaimKind, ExtractionStatus
from app.schemas.analysis import AgentFinding
from app.services.investigation.claim_builder import is_redaction_placeholder
from app.services.agents.recruiter_agent import GENERIC_TITLES, FREE_EMAIL_DOMAINS


@dataclass
class PlanStep:
    """A single deterministic adaptive follow-up search step."""
    target_claim_id: str
    strategy: str  # "EMPLOYER_CONTEXT", "AGENCY_AUTHORIZATION", "RECRUITER_AFFILIATION", "RECRUITMENT_FEE_POLICY"
    trigger: str
    query: str
    information_gain: str
    priority: int  # 1 = highest, 4 = lowest
    stop_condition: str
    rationale: str  # Specific explanation recorded in tool trace and events


class InvestigationPlanner:
    """
    Evaluates initial investigation findings and constructs bounded adaptive search steps.
    """

    def create_plan(
        self,
        claims: List[Claim],
        findings: Dict[str, Optional[AgentFinding]],
        executed_queries: Set[str],
        canonical_domain: Optional[str] = None,
        case_input: Optional[CaseInput] = None,
    ) -> List[PlanStep]:
        """
        Generates candidate follow-up steps ordered by priority.
        Enforces strict stop conditions:
        - Missing or uncertain inputs produce no follow-ups.
        - Redaction placeholders and 'Unknown Company' are never queried.
        - Previously executed queries are skipped.
        - Questions already resolved are skipped.
        """
        def usable(claim):
            return bool(claim and claim.value and claim.extraction_status != ExtractionStatus.UNCERTAIN
                        and not is_redaction_placeholder(claim.value))

        plan: List[PlanStep] = []

        finding_comp = findings.get("CompanyAgent")
        finding_rec = findings.get("RecruiterAgent")
        finding_sal = findings.get("SalaryAgent")
        finding_scam = findings.get("ScamAgent")

        # Map claims by kind
        claim_map = {c.kind: c for c in claims}
        emp_claim = claim_map.get(ClaimKind.EMPLOYER)
        email_claim = claim_map.get(ClaimKind.SENDER_EMAIL)
        phone_claim = claim_map.get(ClaimKind.CONTACT_PHONE)
        name_claim = claim_map.get(ClaimKind.RECRUITER_NAME)
        role_claim = claim_map.get(ClaimKind.ROLE)
        loc_claim = claim_map.get(ClaimKind.LOCATION)
        pay_claim = claim_map.get(ClaimKind.PAYMENT_REQUEST)

        company_name = (
            emp_claim.value.strip()
            if (emp_claim and emp_claim.value and emp_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(emp_claim.value))
            else None
        )

        # --------------------------------------------------------------------
        # Strategy A: Employer Contextual Search (Priority 1)
        # --------------------------------------------------------------------
        # Triggered when employer name was supplied and initial search completed successfully,
        # but corporate domain remained UNRESOLVED (e.g. sparse startup, generic name).
        if company_name and not canonical_domain:
            comp_failed = finding_comp and finding_comp.details.get("provider_status") == "FAILED"
            comp_unresolved = bool(finding_comp and finding_comp.details.get("provider_status") == "SUCCESS" and not finding_comp.details.get("official_domain_resolved", False))

            if comp_unresolved and not comp_failed:
                # Seek grounded location or role context to disambiguate
                loc_val = (
                    loc_claim.value.strip()
                    if (loc_claim and loc_claim.value and loc_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(loc_claim.value))
                    else None
                )
                role_val = (
                    role_claim.value.strip()
                    if (role_claim and role_claim.value and role_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(role_claim.value))
                    else None
                )

                candidate_query = None
                context_used = None
                if loc_val:
                    loc_clean = loc_val.split(",")[0].strip() if "," in loc_val else loc_val
                    candidate_query = f'"{company_name}" "{loc_clean}" official website'
                    context_used = loc_clean
                elif role_val:
                    candidate_query = f'"{company_name}" "{role_val}" official careers'
                    context_used = role_val

                if candidate_query and candidate_query.lower() not in executed_queries:
                    plan.append(
                        PlanStep(
                            target_claim_id=emp_claim.claim_id if emp_claim else "c1",
                            strategy="EMPLOYER_CONTEXT",
                            trigger="Employer corporate domain unresolved after initial query; grounded context available in offer document.",
                            query=candidate_query,
                            information_gain="Resolves canonical corporate domain and official careers presence with regional/role context.",
                            priority=1,
                            stop_condition="Stop if DomainResolver resolves official corporate domain or query yields zero candidate domains.",
                            rationale=f"Employer identity remains unresolved; checking '{company_name}' with grounded context '{context_used}'.",
                        )
                    )

        # --------------------------------------------------------------------
        # Strategy B: Sender/Employer Domain Discrepancy & Agency Check (Priority 2)
        # --------------------------------------------------------------------
        # Triggered when sender domain differs from resolved employer domain,
        # is not a free webmail, and staffing agency representation is unconfirmed.
        if company_name and canonical_domain and usable(email_claim):
            email_val = email_claim.value.strip()
            if "@" in email_val:
                email_domain = email_val.split("@")[-1].lower().strip()
                is_free_mail = email_domain in FREE_EMAIL_DOMAINS
                domain_mismatch = finding_rec and finding_rec.details.get("domain_match") is False

                if domain_mismatch and not is_free_mail:
                    # Check if an agency was identified or discovered
                    agency_name = None
                    if finding_rec:
                        agency_name = (
                            finding_rec.details.get("assessment_dimensions", {}).get("agency_identity", {}).get("raw_facts", {}).get("agency_name")
                            or finding_rec.details.get("agency_identity_facts", {}).get("agency_name")
                            or finding_rec.details.get("agency_name")
                        )
                    clean_agency = (agency_name or email_domain).strip()

                    auth_status = (finding_rec.details.get("assessment_dimensions", {}).get("agency_authorization", {}).get("status") or finding_rec.details.get("agency_authorization_status")) if finding_rec else None
                    if auth_status != "SUPPORTED":
                        candidate_query = f'"{company_name}" "{clean_agency}" recruitment partner authorized'
                        if candidate_query.lower() not in executed_queries:
                            plan.append(
                                PlanStep(
                                    target_claim_id=email_claim.claim_id,
                                    strategy="AGENCY_AUTHORIZATION",
                                    trigger="Sender domain differs from employer; staffing agency representation mandate requires verification.",
                                    query=candidate_query,
                                    information_gain="Identifies authoritative employer-published confirmation of third-party agency hiring mandate.",
                                    priority=2,
                                    stop_condition="Stop if employer-published agency partner citation is found or query yields no partnership evidence.",
                                    rationale=f"Sender domain differs from the employer; checking supported agency representation for '{clean_agency}'.",
                                )
                            )

        # --------------------------------------------------------------------
        # Strategy C: Recruiter Affiliation Check (Priority 3)
        # --------------------------------------------------------------------
        # Triggered when recruiter name is supplied (not generic), employer domain is resolved,
        # but affiliation with the employer remains unconfirmed.
        if company_name and canonical_domain and usable(name_claim):
            name_val = name_claim.value.strip()
            is_generic = name_val.lower() in GENERIC_TITLES

            if not is_generic:
                aff_status = (finding_rec.details.get("assessment_dimensions", {}).get("recruiter_affiliation", {}).get("status") or finding_rec.details.get("recruiter_affiliation_status")) if finding_rec else None
                if aff_status in ("UNCONFIRMED", "NOT_CHECKED", None):
                    candidate_query = f'"{name_val}" "{canonical_domain}" talent acquisition recruiter'
                    if candidate_query.lower() not in executed_queries:
                        plan.append(
                            PlanStep(
                                target_claim_id=name_claim.claim_id,
                                strategy="RECRUITER_AFFILIATION",
                                trigger="Recruiter name stated in document, but affiliation with resolved employer remains unconfirmed.",
                                query=candidate_query,
                                information_gain="Corroborates recruiter identity and talent acquisition role on employer-published channels.",
                                priority=3,
                                stop_condition="Stop if recruiter listing on employer domain is corroborated or query yields zero relevant hits.",
                                rationale=f"Recruiter affiliation unconfirmed; searching for employer-published verification for '{name_val}' at '{company_name}'.",
                            )
                        )

        # --------------------------------------------------------------------
        # Strategy D: Grounded Payment Demand Fee Policy Check (Priority 4)
        # --------------------------------------------------------------------
        # Triggered when offer document contains a payment request and employer domain is resolved.
        # Checks if employer explicitly publishes a no-fee policy.
        if company_name and canonical_domain and usable(pay_claim) and pay_claim.source_quote:
            candidate_query = f'"{company_name}" recruitment fraud policy fee warning'
            if candidate_query.lower() not in executed_queries:
                plan.append(
                    PlanStep(
                        target_claim_id=pay_claim.claim_id,
                        strategy="RECRUITMENT_FEE_POLICY",
                        trigger="Grounded payment demand detected in offer; checking employer's official recruitment fee policy.",
                        query=candidate_query,
                        information_gain="Identifies employer's published applicant caution regarding recruitment fees and fraudulent offers.",
                        priority=4,
                        stop_condition="Stop if official employer fraud caution is found or query yields no policy documentation.",
                        rationale=f"Grounded payment demand detected; checking whether '{company_name}' publishes an explicit no-fee policy.",
                    )
                )

        # Sort steps strictly by priority (1 to 4)
        plan.sort(key=lambda s: s.priority)
        return plan
