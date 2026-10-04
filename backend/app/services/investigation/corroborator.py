"""
Job and application destination corroboration service for AsliOffer (Task 12).

Corroborates:
1. Public vacancy existence and role/location alignment.
2. Public requisition IDs vs private offer references.
3. Application destination URLs and employer-associated ATS tenants.
4. Independently sourced offer-confirmation channels and restrained draft messages.

Preserves UNCONFIRMED authenticity: public vacancy matches never authenticate individual offers.
"""
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit, urlparse

from app.schemas.contract import (
    Claim,
    ClaimKind,
    ClaimStatus,
    ConfirmationRoute,
    EvidenceRecord,
    EvidenceRelation,
    ExtractionStatus,
    RetrievalStatus,
    SourceKind,
    SourceTier,
)
from app.services.investigation.claim_builder import is_redaction_placeholder
from app.services.search.domain_resolver import (
    DomainResolver,
    HOSTED_CAREERS_PLATFORMS,
    EXCLUDED_HOSTNAMES,
)
from app.services.risk.assessment_engine import canonicalize_url


# Seniority and level modifiers stripped during conservative title comparison
SENIORITY_MODIFIERS: Set[str] = {
    "senior", "sr", "junior", "jr", "lead", "principal", "staff", "associate",
    "intern", "trainee", "fresher", "entry", "level", "graduate", "chief", "head",
}

# Words indicating private candidate or offer references rather than public job requisitions
PRIVATE_REF_KEYWORDS: Set[str] = {
    "offer", "cand", "candidate", "appl", "applicant", "student", "employee",
    "letter", "appointment", "loi", "ol", "joining",
}

# Standard patterns for public job requisition IDs
PUBLIC_REQ_PATTERNS = [
    re.compile(r"^(?:REQ|JOB|JR|ID|POS|R|REF)?[_-]?\d{3,10}[A-Z]?$", re.IGNORECASE),
    re.compile(r"^\d{4}-[A-Z0-9]+-\d+$", re.IGNORECASE),
    re.compile(r"^[A-Z]{2,5}-\d{3,8}$", re.IGNORECASE),
]

# Relevant keywords indicating recruitment verification / confirmation channels
CONFIRMATION_EMAIL_PREFIXES: Tuple[str, ...] = (
    "careers", "recruitment", "talent", "jobs", "hiring", "hr", "verify",
    "verification", "offer-verification", "talentacquisition",
)


def normalize_job_title(title: str) -> List[str]:
    """
    Normalizes a job title for conservative comparison without broad fuzzy matching.
    Removes parentheticals, punctuation, and level modifiers.
    Returns core title tokens.
    """
    if not title or not isinstance(title, str):
        return []
    # Strip parentheticals like (m/f/d), (Remote), (Full Time)
    clean = re.sub(r"\([^)]*\)", " ", title)
    clean = re.sub(r"\[[^\]]*\]", " ", clean)
    # Split on hyphens/slashes to isolate role from team/department
    clean = clean.replace("-", " ").replace("/", " ").replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", clean.lower())
    # Filter out seniority modifiers
    core = [t for t in tokens if t not in SENIORITY_MODIFIERS]
    return core if core else tokens


def is_public_job_reference(ref_val: str) -> Tuple[bool, str]:
    """
    Distinguishes usable public job requisition IDs from private candidate/offer references.
    Returns (is_public, reason).
    """
    if not ref_val or not isinstance(ref_val, str) or is_redaction_placeholder(ref_val):
        return False, "missing_or_redacted"

    clean = ref_val.strip()
    lower = clean.lower()

    # Check for private offer reference indicators
    if any(kw in lower for kw in PRIVATE_REF_KEYWORDS):
        return False, "private_offer_reference"
    if "/" in clean and any(p in lower for p in ("ol/", "loi/", "off/", "ref/")):
        return False, "private_offer_reference"
    if len(clean) > 30 or " " in clean:
        return False, "complex_or_private_reference"
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", lower):
        return False, "uuid_token_private"

    # Check against public requisition patterns
    for pat in PUBLIC_REQ_PATTERNS:
        if pat.match(clean):
            return True, "public_requisition_pattern"

    return False, "ambiguous_reference_abstain"


def evaluate_application_destination(
    url_str: str,
    company_name: str,
    canonical_domain: Optional[str],
    observed_urls: Set[str],
) -> Dict[str, Any]:
    """
    Conservatively classifies an application destination URL without trusting plausibility alone.
    Reuses DomainResolver's URL parsing and tenant association logic.
    """
    parsed = DomainResolver.normalize_and_parse_url(url_str)
    if not parsed.is_valid:
        return {
            "status": ClaimStatus.CONTRADICTED,
            "classification": "MALFORMED_OR_CREDENTIAL",
            "reason_code": "MALFORMED_OR_CREDENTIAL_URL",
            "explanation": f"The application destination '{url_str}' contains malformed structure, control characters, or embedded credentials.",
            "source_tier": SourceTier.UNKNOWN,
            "relation": EvidenceRelation.CONTRADICTS,
        }

    identity = DomainResolver._extract_company_identity(company_name)

    # 1. Check official employer domain
    canon_host = canonical_domain
    if canon_host and "://" in canon_host:
        canon_host = urlparse(canon_host).hostname or canon_host
    if canon_host and DomainResolver.is_matching_domain(parsed.hostname, canon_host):
        # Exact observed path vs unobserved path
        norm_key = canonicalize_url(url_str)
        is_observed = any(canonicalize_url(u) == norm_key for u in observed_urls)
        if is_observed:
            return {
                "status": ClaimStatus.SUPPORTED,
                "classification": "OFFICIAL_DOMAIN_OBSERVED",
                "reason_code": "DESTINATION_VERIFIED",
                "explanation": f"The application destination uses the official employer domain '{canon_host}' and was corroborated in public records.",
                "source_tier": SourceTier.OFFICIAL_EMPLOYER,
                "relation": EvidenceRelation.SUPPORTS,
            }
        return {
            "status": ClaimStatus.UNRESOLVED,
            "classification": "OFFICIAL_DOMAIN_UNOBSERVED_PATH",
            "reason_code": "DOMAIN_ASSOCIATED_PATH_UNVERIFIED",
            "explanation": f"The application link uses the employer's official domain '{canon_host}', but the specific path or application form was not independently observed.",
            "source_tier": SourceTier.OFFICIAL_EMPLOYER,
            "relation": EvidenceRelation.CONTEXT,
        }

    # 2. Check hosted ATS platforms (before lookalike check to avoid false lookalike on valid ATS subdomains)
    if DomainResolver.is_hosted_careers_platform(parsed.hostname):
        is_associated = DomainResolver._is_associated_hosted_careers(parsed, identity)
        if is_associated:
            norm_key = canonicalize_url(url_str)
            is_observed = any(canonicalize_url(u) == norm_key for u in observed_urls)
            if is_observed:
                return {
                    "status": ClaimStatus.SUPPORTED,
                    "classification": "ESTABLISHED_ATS_TENANT_OBSERVED",
                    "reason_code": "ESTABLISHED_ATS_TENANT",
                    "explanation": f"The application link directs to an established ATS tenant ({parsed.hostname}) verified for '{company_name}'.",
                    "source_tier": SourceTier.ESTABLISHED_THIRD_PARTY,
                    "relation": EvidenceRelation.SUPPORTS,
                }
            return {
                "status": ClaimStatus.UNRESOLVED,
                "classification": "ESTABLISHED_ATS_TENANT_UNOBSERVED",
                "reason_code": "ATS_TENANT_UNCONFIRMED_PATH",
                "explanation": f"The application link matches an established ATS tenant ({parsed.hostname}) for '{company_name}', but the specific posting was not independently observed.",
                "source_tier": SourceTier.ESTABLISHED_THIRD_PARTY,
                "relation": EvidenceRelation.CONTEXT,
            }
        else:
            return {
                "status": ClaimStatus.UNRESOLVED,
                "classification": "UNRELATED_ATS_TENANT",
                "reason_code": "UNRELATED_ATS_TENANT",
                "explanation": f"The application link directs to a hosted ATS platform ({parsed.hostname}), but the tenant identifier does not match '{company_name}'.",
                "source_tier": SourceTier.ESTABLISHED_THIRD_PARTY,
                "relation": EvidenceRelation.CONTEXT,
            }

    # 3. Check for lookalike domains
    is_lookalike, lookalike_reason = DomainResolver._check_lookalike(parsed, identity)
    if is_lookalike:
        return {
            "status": ClaimStatus.CONTRADICTED,
            "classification": "SUSPECTED_LOOKALIKE",
            "reason_code": "SUSPECTED_LOOKALIKE_DESTINATION",
            "explanation": f"The application URL '{url_str}' uses a suspected lookalike domain ({lookalike_reason}).",
            "source_tier": SourceTier.UNKNOWN,
            "relation": EvidenceRelation.CONTRADICTS,
        }

    # Check general job boards
    if DomainResolver.is_excluded_platform(parsed.hostname):
        return {
            "status": ClaimStatus.UNRESOLVED,
            "classification": "THIRD_PARTY_JOB_BOARD",
            "reason_code": "THIRD_PARTY_DESTINATION",
            "explanation": f"The application link directs to a general third-party job board ({parsed.hostname}) rather than an employer-controlled portal.",
            "source_tier": SourceTier.ESTABLISHED_THIRD_PARTY,
            "relation": EvidenceRelation.CONTEXT,
        }

    # Generic unresolved third party
    return {
        "status": ClaimStatus.UNRESOLVED,
        "classification": "UNRESOLVED_THIRD_PARTY",
        "reason_code": "UNASSOCIATED_DESTINATION",
        "explanation": f"The application link directs to an external third-party destination ('{parsed.hostname}') with no established employer association.",
        "source_tier": SourceTier.UNKNOWN,
        "relation": EvidenceRelation.CONTEXT,
    }


def generate_confirmation_draft(
    channel: str,
    company_name: str,
    role: Optional[str] = None,
    job_ref: Optional[str] = None,
    recruiter_name: Optional[str] = None,
) -> str:
    """
    Constructs a restrained, neutral inquiry draft for the candidate to independently verify offer issuance.
    Uses safe placeholders and contains zero accusations or sensitive credentials.
    """
    role_str = role if role else "[Position / Role Title]"
    ref_clause = f" (Requisition/Reference: {job_ref})" if job_ref else " (Reference: [Candidate/Offer Reference])"
    recruiter_clause = f" purportedly from {recruiter_name}" if recruiter_name else " from a recruitment representative"

    if channel == "official_email":
        return (
            f"Subject: Employment Offer Verification Inquiry - {role_str} - [Your Name]\n\n"
            f"Dear {company_name} Talent Acquisition Team,\n\n"
            f"I have received an employment offer for the position of {role_str}{ref_clause}{recruiter_clause}.\n\n"
            f"Could you please confirm whether this offer was formally issued by {company_name}, and whether the contacting representative is authorized to conduct recruitment for this role?\n\n"
            f"Candidate Name: [Your Full Name]\n"
            f"Application Reference: [Your Reference if provided]\n\n"
            f"Thank you for your assistance.\n\n"
            f"Sincerely,\n"
            f"[Your Name]\n"
            f"[Your Phone Number]"
        )
    elif channel == "official_phone":
        return (
            f"Hello, I am contacting {company_name} to verify an employment offer I received for the position of "
            f"{role_str}{ref_clause}{recruiter_clause}. Could you please connect me with Human Resources or the "
            f"Talent Acquisition department to confirm if this offer was officially issued? "
            f"My name is [Your Name] and my reference number is [Your Reference ID]."
        )
    else:  # careers_portal or ats_portal
        return (
            f"Navigate to {company_name}'s official portal and locate their published human resources or recruitment contact. "
            f"Inquire neutrally: 'I have received an employment offer for {role_str}{ref_clause}; could you please verify whether this offer was officially issued?' "
            f"State your name ([Your Name]) but do not disclose banking details, account passwords, or OTPs."
        )


@dataclass
class CorroborationObservation:
    claim_id: str
    kind: ClaimKind
    status: ClaimStatus
    reason_codes: List[str]
    explanation: str
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class JobCorroborationResult:
    observations: Dict[str, CorroborationObservation] = field(default_factory=dict)
    confirmation_route: Optional[ConfirmationRoute] = None
    executed_checks: Set[ClaimKind] = field(default_factory=set)
    failed_checks: Set[ClaimKind] = field(default_factory=set)


class JobCorroborationService:
    """
    Focused service evaluating job, location, requisition, and destination corroboration
    alongside independent confirmation route discovery.
    """

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode

    def corroborate(
        self,
        claims: List[Claim],
        company_name: Optional[str] = None,
        canonical_domain: Optional[str] = None,
        careers_url: Optional[str] = None,
        snippets_by_url: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        executed_steps: Optional[Set[str]] = None,
        findings: Optional[Dict[str, Any]] = None,
        recording_client: Optional[Any] = None,
    ) -> JobCorroborationResult:
        result = JobCorroborationResult()
        claim_map = {c.kind: c for c in claims}

        if recording_client is not None:
            if snippets_by_url is None:
                snippets_by_url = recording_client.snippets_by_url
            if executed_steps is None:
                executed_steps = {c.step for c in recording_client.tool_calls}
        if snippets_by_url is None:
            snippets_by_url = {}
        if executed_steps is None:
            executed_steps = set()

        if company_name is None:
            emp_c = claim_map.get(ClaimKind.EMPLOYER)
            if emp_c and emp_c.value and not is_redaction_placeholder(emp_c.value):
                company_name = emp_c.value.strip()

        emp_name = company_name or "the employer"

        # Collect all observed URLs from search snippets
        observed_urls: Set[str] = set()
        for url_key, entries in snippets_by_url.items():
            observed_urls.add(url_key)
            for m in entries:
                if m.get("source_url"):
                    observed_urls.add(m["source_url"])

        # --------------------------------------------------------------------
        # 1. APPLICATION_URL Corroboration
        # --------------------------------------------------------------------
        app_url_claim = claim_map.get(ClaimKind.APPLICATION_URL)
        if app_url_claim and app_url_claim.value and app_url_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(app_url_claim.value):
            dest_eval = evaluate_application_destination(
                url_str=app_url_claim.value,
                company_name=emp_name,
                canonical_domain=canonical_domain,
                observed_urls=observed_urls,
            )
            ev_items: List[Dict[str, Any]] = []
            if dest_eval["status"] == ClaimStatus.SUPPORTED:
                ev_items.append({
                    "source_url": app_url_claim.value,
                    "title": f"{emp_name} Verified Application Destination",
                    "description": dest_eval["explanation"],
                    "source_tier": dest_eval["source_tier"],
                    "relation": EvidenceRelation.SUPPORTS,
                })
            elif dest_eval["status"] == ClaimStatus.CONTRADICTED:
                ev_items.append({
                    "source_url": app_url_claim.value,
                    "title": "Suspicious or Lookalike Application Destination",
                    "description": dest_eval["explanation"],
                    "source_tier": dest_eval["source_tier"],
                    "relation": EvidenceRelation.CONTRADICTS,
                })
            elif dest_eval["status"] == ClaimStatus.UNRESOLVED:
                ev_items.append({
                    "source_url": app_url_claim.value,
                    "title": f"{emp_name} Application Destination Evaluation",
                    "description": dest_eval["explanation"],
                    "source_tier": dest_eval["source_tier"],
                    "relation": EvidenceRelation.CONTEXT,
                })
            result.observations[app_url_claim.claim_id] = CorroborationObservation(
                claim_id=app_url_claim.claim_id,
                kind=ClaimKind.APPLICATION_URL,
                status=dest_eval["status"],
                reason_codes=[dest_eval["reason_code"]],
                explanation=dest_eval["explanation"],
                evidence_items=ev_items,
            )
            result.executed_checks.add(ClaimKind.APPLICATION_URL)

        # --------------------------------------------------------------------
        # 2. ROLE & LOCATION Corroboration from Vacancy Snippets
        # --------------------------------------------------------------------
        role_claim = claim_map.get(ClaimKind.ROLE)
        loc_claim = claim_map.get(ClaimKind.LOCATION)

        role_supported = False
        role_evidence_item: Optional[Dict[str, Any]] = None
        matching_vacancy_snippet: Optional[str] = None
        matching_vacancy_text: Optional[str] = None
        matching_vacancy_url: Optional[str] = None

        if role_claim and role_claim.value and role_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(role_claim.value):
            role_val = role_claim.value.strip()
            core_role_tokens = normalize_job_title(role_val)

            # Search all collected snippets for attributable role vacancy
            for url_key, entries in snippets_by_url.items():
                parsed_url = DomainResolver.normalize_and_parse_url(url_key)
                if not parsed_url.is_valid:
                    continue

                # Must be official employer or established ATS tenant
                is_official = canonical_domain and DomainResolver.is_matching_domain(parsed_url.hostname, canonical_domain)
                is_ats = DomainResolver.is_hosted_careers_platform(parsed_url.hostname) and DomainResolver._is_associated_hosted_careers(parsed_url, DomainResolver._extract_company_identity(emp_name))

                if not (is_official or is_ats):
                    continue

                for meta in entries:
                    text = f"{meta.get('title', '')} {meta.get('snippet', '')}".lower()
                    # Check if all core role tokens appear in the vacancy listing
                    if core_role_tokens and all(token in text for token in core_role_tokens):
                        # Ensure not an entirely different profession
                        # (e.g. if looking for Software Engineer, check we aren't matching Sales or HR)
                        role_supported = True
                        matching_vacancy_snippet = meta.get("snippet", "")
                        matching_vacancy_text = f"{meta.get('title', '')} {meta.get('snippet', '')}"
                        matching_vacancy_url = meta.get("source_url") or url_key
                        tier = SourceTier.OFFICIAL_EMPLOYER if is_official else SourceTier.ESTABLISHED_THIRD_PARTY
                        role_evidence_item = {
                            "source_url": matching_vacancy_url,
                            "title": meta.get("title") or f"{emp_name} Career Opportunity",
                            "description": meta.get("snippet") or f"Public vacancy for {role_val} at {emp_name}.",
                            "source_tier": tier,
                            "relation": EvidenceRelation.SUPPORTS,
                        }
                        break
                if role_supported:
                    break

            result.executed_checks.add(ClaimKind.ROLE)
            if role_supported and role_evidence_item:
                result.observations[role_claim.claim_id] = CorroborationObservation(
                    claim_id=role_claim.claim_id,
                    kind=ClaimKind.ROLE,
                    status=ClaimStatus.SUPPORTED,
                    reason_codes=["ROLE_CORROBORATED", "PUBLIC_VACANCY_LISTED", "PUBLIC_VACANCY_MATCH"],
                    explanation=f"Public hiring records for {emp_name} corroborate an active vacancy for '{role_val}'. This does not authenticate the individual offer.",
                    evidence_items=[role_evidence_item],
                )
            else:
                result.observations[role_claim.claim_id] = CorroborationObservation(
                    claim_id=role_claim.claim_id,
                    kind=ClaimKind.ROLE,
                    status=ClaimStatus.UNRESOLVED,
                    reason_codes=["VACANCY_NOT_FOUND", "UNLISTED_OR_EXPIRED", "NO_MATCHING_VACANCY"],
                    explanation=f"No active public vacancy matching '{role_val}' was identified for {emp_name}. Unlisted or closed postings do not prove fraud.",
                    evidence_items=[],
                )

        # LOCATION Corroboration
        if loc_claim and loc_claim.value and loc_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(loc_claim.value):
            loc_val = loc_claim.value.strip()
            city = loc_val.split(",")[0].strip().lower()
            result.executed_checks.add(ClaimKind.LOCATION)

            loc_supported = False
            loc_evidence_item: Optional[Dict[str, Any]] = None

            # Location is supported ONLY from the relevant vacancy or hiring record
            # Employer headquarters alone do NOT corroborate location!
            if matching_vacancy_text and city in matching_vacancy_text.lower():
                # Check that it is not explicitly marked as headquarters-only
                hq_patterns = ["headquartered in", "corporate office:", "hq in", "registered office:"]
                is_hq_only = any(f"{pat} {city}" in matching_vacancy_text.lower() for pat in hq_patterns)
                if not is_hq_only:
                    loc_supported = True
                    loc_evidence_item = {
                        "source_url": matching_vacancy_url,
                        "title": f"{emp_name} Job Location Record",
                        "description": matching_vacancy_snippet or matching_vacancy_text,
                        "source_tier": SourceTier.OFFICIAL_EMPLOYER,
                        "relation": EvidenceRelation.SUPPORTS,
                    }

            if loc_supported and loc_evidence_item:
                result.observations[loc_claim.claim_id] = CorroborationObservation(
                    claim_id=loc_claim.claim_id,
                    kind=ClaimKind.LOCATION,
                    status=ClaimStatus.SUPPORTED,
                    reason_codes=["LOCATION_CORROBORATED", "VACANCY_LOCATION_MATCH"],
                    explanation=f"Public hiring records corroborate the specified job location '{loc_val}'.",
                    evidence_items=[loc_evidence_item],
                )
            else:
                result.observations[loc_claim.claim_id] = CorroborationObservation(
                    claim_id=loc_claim.claim_id,
                    kind=ClaimKind.LOCATION,
                    status=ClaimStatus.UNRESOLVED,
                    reason_codes=["LOCATION_NOT_CORROBORATED", "LOCATION_UNCORROBORATED", "HEADQUARTERS_ONLY_NOT_JOB_LOCATION"],
                    explanation=f"Identified records for {emp_name} do not corroborate '{loc_val}' as the active hiring location for this position.",
                    evidence_items=[],
                )

        # --------------------------------------------------------------------
        # 3. JOB_REFERENCE Corroboration
        # --------------------------------------------------------------------
        ref_claim = claim_map.get(ClaimKind.JOB_REFERENCE)
        if ref_claim and ref_claim.value and ref_claim.extraction_status != ExtractionStatus.UNCERTAIN and not is_redaction_placeholder(ref_claim.value):
            ref_val = ref_claim.value.strip()
            is_pub, reason = is_public_job_reference(ref_val)

            if not is_pub:
                # Private offer/candidate reference: abstain from searching
                result.observations[ref_claim.claim_id] = CorroborationObservation(
                    claim_id=ref_claim.claim_id,
                    kind=ClaimKind.JOB_REFERENCE,
                    status=ClaimStatus.NOT_CHECKED,
                    reason_codes=["PRIVATE_OFFER_REFERENCE", "NOT_PUBLIC_REQUISITION"],
                    explanation=f"The job reference '{ref_val}' appears to be an internal offer identifier or candidate tracking code, which cannot be checked in public requisition listings.",
                    evidence_items=[],
                )
            else:
                result.executed_checks.add(ClaimKind.JOB_REFERENCE)
                ref_matched = False
                ref_evidence_item: Optional[Dict[str, Any]] = None

                # Search snippets for exact public requisition ID
                for url_key, entries in snippets_by_url.items():
                    for meta in entries:
                        text = f"{meta.get('title', '')} {meta.get('snippet', '')}"
                        if ref_val.lower() in text.lower():
                            ref_matched = True
                            ref_evidence_item = {
                                "source_url": meta.get("source_url") or url_key,
                                "title": meta.get("title") or f"{emp_name} Requisition Listing",
                                "description": meta.get("snippet") or f"Requisition {ref_val} identified.",
                                "source_tier": SourceTier.OFFICIAL_EMPLOYER,
                                "relation": EvidenceRelation.SUPPORTS,
                            }
                            break
                    if ref_matched:
                        break

                if ref_matched and ref_evidence_item:
                    result.observations[ref_claim.claim_id] = CorroborationObservation(
                        claim_id=ref_claim.claim_id,
                        kind=ClaimKind.JOB_REFERENCE,
                        status=ClaimStatus.SUPPORTED,
                        reason_codes=["JOB_REFERENCE_MATCHED", "PUBLIC_REQUISITION_VERIFIED"],
                        explanation=f"Exact public job requisition ID '{ref_val}' was corroborated in employer hiring records.",
                        evidence_items=[ref_evidence_item],
                    )
                else:
                    result.observations[ref_claim.claim_id] = CorroborationObservation(
                        claim_id=ref_claim.claim_id,
                        kind=ClaimKind.JOB_REFERENCE,
                        status=ClaimStatus.UNRESOLVED,
                        reason_codes=["REQUISITION_NOT_FOUND"],
                        explanation=f"Public requisition ID '{ref_val}' was not found in active listings for {emp_name}.",
                        evidence_items=[],
                    )

        # --------------------------------------------------------------------
        # 4. Confirmation Route Discovery
        # --------------------------------------------------------------------
        route = self._discover_route(
            company_name=emp_name,
            canonical_domain=canonical_domain,
            careers_url=careers_url,
            snippets_by_url=snippets_by_url,
            claims=claims,
        )
        result.confirmation_route = route

        return result

    def _discover_route(
        self,
        company_name: str,
        canonical_domain: Optional[str],
        careers_url: Optional[str],
        snippets_by_url: Dict[str, List[Dict[str, Any]]],
        claims: List[Claim],
    ) -> Optional[ConfirmationRoute]:
        """
        Discovers an independent, employer-published confirmation route citing retrieved evidence.
        Strictly excludes DEMO data unless demo_mode is True.
        """
        claim_map = {c.kind: c for c in claims}
        role_claim = claim_map.get(ClaimKind.ROLE)
        ref_claim = claim_map.get(ClaimKind.JOB_REFERENCE)
        rec_name_claim = claim_map.get(ClaimKind.RECRUITER_NAME)
        email_claim = claim_map.get(ClaimKind.SENDER_EMAIL)

        role_val = role_claim.value if role_claim and role_claim.value else None
        ref_val = ref_claim.value if ref_claim and ref_claim.value else None
        rec_name_val = rec_name_claim.value if rec_name_claim and rec_name_claim.value else None

        canon_host = canonical_domain
        if canon_host and "://" in canon_host:
            canon_host = urlparse(canon_host).hostname or canon_host

        candidate_email_route: Optional[Tuple[str, str]] = None  # (email, evidence_id or source_url)
        candidate_phone_route: Optional[Tuple[str, str]] = None  # (phone, evidence_id or source_url)
        candidate_portal_route: Optional[Tuple[str, str]] = None  # (url, evidence_id or source_url)
        submitted_email = email_claim.value.lower().strip() if (email_claim and email_claim.value) else None

        # Scan all retrieved snippets from official employer / ATS sources
        for url_key, entries in snippets_by_url.items():
            parsed_url = DomainResolver.normalize_and_parse_url(url_key)
            if not parsed_url.is_valid:
                continue

            is_official = bool(canon_host and DomainResolver.is_matching_domain(parsed_url.hostname, canon_host))
            is_ats = bool(DomainResolver.is_hosted_careers_platform(parsed_url.hostname) and DomainResolver._is_associated_hosted_careers(parsed_url, DomainResolver._extract_company_identity(company_name)))

            if not (is_official or is_ats):
                continue

            for meta in entries:
                # Exclude demo evidence in non-demo mode
                if meta.get("retrieval_status") == RetrievalStatus.DEMO and not self.demo_mode:
                    continue
                if meta.get("retrieval_status") == RetrievalStatus.FAILED:
                    continue

                snippet_text = f"{meta.get('title', '')} {meta.get('snippet', '')}"

                # Look for published recruitment email
                email_matches = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", snippet_text)
                for email in email_matches:
                    email_lower = email.lower()
                    email_domain = email_lower.split("@")[-1]
                    # Must be corporate domain matching canonical domain
                    if canon_host and DomainResolver.is_matching_domain(email_domain, canon_host):
                        prefix = email_lower.split("@")[0]
                        # A submitted recruiter contact cannot become an independent verification route
                        if submitted_email and email_lower == submitted_email:
                            continue
                        # An individual recruiter listing is not an offer verification channel.
                        # Require dedicated recruitment/verification mailbox.
                        if any(p in prefix for p in CONFIRMATION_EMAIL_PREFIXES) and any(w in snippet_text.lower() for w in ("verify", "verification", "recruitment", "careers", "contact hr", "fraud", "hiring")):
                            if not candidate_email_route:
                                candidate_email_route = (email_lower, meta.get("source_url") or url_key)
                                break

                # Look for published recruitment phone
                phone_match = re.search(r"(?:\+91|0)?[-\s]?[6-9]\d{9}|\+?[1-9]\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4,6}", snippet_text)
                if phone_match and any(w in snippet_text.lower() for w in ("switchboard", "board line", "contact careers", "recruitment office", "office phone")):
                    if not candidate_phone_route:
                        candidate_phone_route = (phone_match.group(0).strip(), meta.get("source_url") or url_key)

                # Look for careers portal
                if careers_url and canonicalize_url(meta.get("source_url") or url_key) == canonicalize_url(careers_url):
                    if not candidate_portal_route:
                        candidate_portal_route = (careers_url, meta.get("source_url") or url_key)
                elif is_ats and not candidate_portal_route:
                    candidate_portal_route = (url_key, meta.get("source_url") or url_key)

        # Prioritize route type: official_email > official_phone > careers_portal
        if candidate_email_route:
            email, ev_url = candidate_email_route
            draft = generate_confirmation_draft(
                channel="official_email",
                company_name=company_name,
                role=role_val,
                job_ref=ref_val,
                recruiter_name=rec_name_val,
            )
            return ConfirmationRoute(
                channel="official_email",
                destination=email,
                evidence_id=ev_url,  # Replaced with actual evidence_id during evidence adaptation
                draft_message=draft,
            )
        elif candidate_phone_route:
            phone, ev_url = candidate_phone_route
            draft = generate_confirmation_draft(
                channel="official_phone",
                company_name=company_name,
                role=role_val,
                job_ref=ref_val,
                recruiter_name=rec_name_val,
            )
            return ConfirmationRoute(
                channel="official_phone",
                destination=phone,
                evidence_id=ev_url,
                draft_message=draft,
            )
        elif candidate_portal_route or careers_url:
            portal_url = candidate_portal_route[0] if candidate_portal_route else careers_url
            ev_url = candidate_portal_route[1] if candidate_portal_route else careers_url
            draft = generate_confirmation_draft(
                channel="careers_portal",
                company_name=company_name,
                role=role_val,
                job_ref=ref_val,
                recruiter_name=rec_name_val,
            )
            return ConfirmationRoute(
                channel="careers_portal",
                destination=portal_url,
                evidence_id=ev_url,
                draft_message=draft,
            )

        return None
