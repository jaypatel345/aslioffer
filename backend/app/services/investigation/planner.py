"""
Deterministic adaptive investigation planner for AsliOffer (Task 11 & Task 12).

Examines unresolved or conflicting findings from initial checks and generates
targeted, prioritized follow-up search steps with explicit rationale.
"""
from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from app.schemas.contract import CaseInput, Claim, ClaimKind, ExtractionStatus
from app.schemas.analysis import AgentFinding
from app.services.investigation.claim_builder import is_redaction_placeholder
from app.services.agents.recruiter_agent import GENERIC_TITLES, FREE_EMAIL_DOMAINS
from app.services.investigation.corroborator import is_public_job_reference


@dataclass
class PlanStep:
    """A single deterministic adaptive follow-up search step."""
    target_claim_id: str
    strategy: str  # "EMPLOYER_CONTEXT", "AGENCY_AUTHORIZATION", "RECRUITER_AFFILIATION", "RECRUITMENT_FEE_POLICY", "JOB_ROLE_CORROBORATION", "JOB_REFERENCE_CORROBORATION", "CONFIRMATION_ROUTE_DISCOVERY"
    trigger: str
    query: str
    information_gain: str
    priority: int  # 1 = highest, 6 = lowest
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
        careers_url: Optional[str] = None,
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
        ref_claim = claim_map.get(ClaimKind.JOB_REFERENCE)

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

        # --------------------------------------------------------------------
        # Determine Careers Scope for Strategies E, F, G
        # --------------------------------------------------------------------
        scope = None
        if careers_url:
            p_careers = urlparse(careers_url)
            if p_careers.netloc:
                scope = p_careers.netloc.lower()
                if scope.startswith("www."):
                    scope = scope[4:]
        if not scope and canonical_domain:
            scope = canonical_domain

        # --------------------------------------------------------------------
        # Strategy E: Job Role Corroboration (Priority 5)
        # --------------------------------------------------------------------
        # Bounded query scoping claimed role to established employer/careers sources
        if company_name and usable(role_claim) and (canonical_domain or careers_url):
            role_val = role_claim.value.strip()
            candidate_query = f'site:{scope} "{role_val}"' if scope else f'"{company_name}" "{role_val}" official careers'
            if candidate_query.lower() not in executed_queries:
                plan.append(
                    PlanStep(
                        target_claim_id=role_claim.claim_id,
                        strategy="JOB_ROLE_CORROBORATION",
                        trigger="Role claimed in offer document; corroborating vacancy existence on established employer careers sources.",
                        query=candidate_query,
                        information_gain="Corroborates public vacancy existence, title alignment, and role location.",
                        priority=5,
                        stop_condition="Stop if matching vacancy is corroborated on employer careers sources or query yields no matches.",
                        rationale="Checking the claimed role against established employer careers sources.",
                    )
                )

        # --------------------------------------------------------------------
        # Strategy F: Public Job Reference Corroboration (Priority 5)
        # --------------------------------------------------------------------
        # Safe public requisition code check; strictly abstains from private candidate references
        if company_name and usable(ref_claim) and (canonical_domain or careers_url):
            is_pub, _ = is_public_job_reference(ref_claim.value, ref_claim.source_quote)
            if is_pub:
                ref_val = ref_claim.value.strip()
                candidate_query = f'site:{scope} "{ref_val}"' if scope else f'"{company_name}" "{ref_val}" job requisition'
                if candidate_query.lower() not in executed_queries:
                    plan.append(
                        PlanStep(
                            target_claim_id=ref_claim.claim_id,
                            strategy="JOB_REFERENCE_CORROBORATION",
                            trigger="Public job requisition reference detected; checking against public hiring records.",
                            query=candidate_query,
                            information_gain="Corroborates exact public vacancy requisition code.",
                            priority=5,
                            stop_condition="Stop if requisition code matches public vacancy or query yields zero matches.",
                            rationale=f"Checking public requisition reference '{ref_val}' against public hiring records for '{company_name}'.",
                        )
                    )

        # --------------------------------------------------------------------
        # Strategy G: Confirmation Route Discovery (Priority 6)
        # --------------------------------------------------------------------
        # Looks for employer-published offer verification guidance or careers contact
        if company_name and (canonical_domain or careers_url) and (usable(role_claim) or usable(ref_claim)):
            candidate_query = f'"{company_name}" recruitment verification contact site:{canonical_domain}' if canonical_domain else f'"{company_name}" careers offer verification contact'
            if candidate_query.lower() not in executed_queries:
                plan.append(
                    PlanStep(
                        target_claim_id=emp_claim.claim_id if emp_claim else "c1",
                        strategy="CONFIRMATION_ROUTE_DISCOVERY",
                        trigger="Checking for employer-published offer verification channel or careers contact guidance.",
                        query=candidate_query,
                        information_gain="Identifies official HR/careers verification channels to confirm offer issuance.",
                        priority=6,
                        stop_condition="Stop if official verification route is discovered or query yields no published contacts.",
                        rationale="Looking for employer-published guidance for confirming offer issuance.",
                    )
                )

        # Sort steps strictly by priority (1 to 6)
        plan.sort(key=lambda s: s.priority)
        return plan
