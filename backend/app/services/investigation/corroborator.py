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
from urllib.parse import parse_qsl, urlparse

from app.schemas.contract import (
    Claim,
    ClaimKind,
    ClaimStatus,
    ConfirmationRoute,
    EventStatus,
    EvidenceRelation,
    ExtractionStatus,
    RetrievalStatus,
    SourceTier,
)
from app.services.investigation.claim_builder import is_redaction_placeholder
from app.services.search.domain_resolver import (
    DomainResolver,
)
from app.services.risk.assessment_engine import canonicalize_url
from app.services.agents.scam_classifier import sanitize_and_redact_secrets


# Seniority and level modifiers retained during conservative title comparison
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
    re.compile(r"^(?:REQ|JOB|JR|POS)[_-]?\d{3,10}[A-Z]?$", re.IGNORECASE),
    re.compile(r"^\d{4}-[A-Z0-9]+-\d+$", re.IGNORECASE),

]

# Relevant keywords indicating recruitment verification / confirmation channels
CONFIRMATION_EMAIL_PREFIXES: Tuple[str, ...] = (
    "careers", "recruitment", "talent", "jobs", "hiring", "hr", "verify",
    "verification", "offer-verification", "talentacquisition",
)


def normalize_job_title(title: str) -> List[str]:
    """
    Normalizes a job title for conservative comparison without broad fuzzy matching.
    Removes formatting punctuation and normalizes common level abbreviations.
    Preserves seniority and specialization: an intern is not a senior vacancy.
    Returns core title tokens.
    """
    if not title or not isinstance(title, str):
        return []
    # Remove known formatting labels, preserving meaningful parenthetical levels.
    clean = re.sub(r"\((?:m/f/d|f/m/d|full time|part time|remote|hybrid)\)", " ", title, flags=re.I)
    # Split on hyphens/slashes to isolate role from team/department
    clean = clean.replace("-", " ").replace("/", " ").replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", clean.lower())
    # Retain seniority and specialization; normalize only common abbreviations.
    aliases = {"sr": "senior", "jr": "junior"}
    return [aliases.get(t, t) for t in tokens]


def is_public_job_reference(ref_val: str, source_quote: Optional[str] = None) -> Tuple[bool, str]:
    """
    Distinguishes usable public job requisition IDs from private candidate/offer references.
    Returns (safe_to_search_as_public_candidate, reason), not proof of public provenance.
    """
    if not ref_val or not isinstance(ref_val, str) or is_redaction_placeholder(ref_val):
        return False, "missing_or_redacted"

    clean = ref_val.strip()
    lower = clean.lower()
    if source_quote and re.search(r"\b(?:candidate|applicant|offer|employee|appointment|joining)\s+(?:id|reference|ref|number|code)\b", source_quote, re.I):
        return False, "private_offer_reference"

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
    established_ats_urls: Optional[Set[str]] = None,
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
            "explanation": "The application destination contains malformed structure, control characters, or embedded credentials.",
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
        established = canonicalize_url(url_str) in (established_ats_urls or set())
        if is_associated:
            norm_key = canonicalize_url(url_str)
            is_observed = any(canonicalize_url(u) == norm_key for u in observed_urls)
            if is_observed and established:
                return {
                    "status": ClaimStatus.SUPPORTED,
                    "classification": "ESTABLISHED_ATS_TENANT_OBSERVED",
                    "reason_code": "ESTABLISHED_ATS_TENANT",
                    "explanation": f"The application link directs to an established ATS tenant ({parsed.hostname}) independently associated with '{company_name}'.",
                    "source_tier": SourceTier.ESTABLISHED_THIRD_PARTY,
                    "relation": EvidenceRelation.SUPPORTS,
                }
            return {
                "status": ClaimStatus.UNRESOLVED,
                "classification": "ESTABLISHED_ATS_TENANT_UNOBSERVED",
                "reason_code": "ATS_TENANT_UNCONFIRMED_PATH",
                "explanation": f"The ATS tenant name resembles '{company_name}', but independent employer association or the specific posting has not been established.",
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
            "explanation": f"The application destination uses a suspected lookalike hostname ({parsed.hostname}); independent employer association was not established.",
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
    def safe_field(value, placeholder):
        if not value or len(value) > 160 or re.search(r"[\r\n\x00-\x1f]", value):
            return placeholder
        if "://" in value or re.search(r"\b(?:token|api[_-]?key|signature)\s*[:=]", value, re.I):
            return placeholder
        clean = sanitize_and_redact_secrets(value).strip()
        if clean != value.strip() or is_redaction_placeholder(clean):
            return placeholder
        return clean

    company_name = safe_field(company_name, "[Employer Name]")
    role = safe_field(role, "[Position / Role Title]")
    recruiter_name = safe_field(recruiter_name, "[Recruitment Representative]") if recruiter_name else None
    job_ref = job_ref if job_ref and is_public_job_reference(job_ref)[0] else None
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
    confirmation_evidence: Optional[Dict[str, Any]] = None


class JobCorroborationService:
    """Evaluate only attributable retrieved observations; public jobs never authenticate offers."""

    JOB_STEPS = {"corroborate_job_role", "adaptive_job_role_corroboration"}
    REF_STEPS = {"corroborate_job_reference", "adaptive_job_reference_corroboration"}

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode

    def corroborate(self, claims, company_name=None, canonical_domain=None, careers_url=None,
                    snippets_by_url=None, executed_steps=None, findings=None, recording_client=None):
        result = JobCorroborationResult()
        by_kind = {c.kind: c for c in claims}
        employer = by_kind.get(ClaimKind.EMPLOYER)
        company_name = company_name or (employer.value if employer else None) or "the employer"
        canon = (urlparse(canonical_domain).hostname if canonical_domain and "://" in canonical_domain else canonical_domain)
        snippets = snippets_by_url if snippets_by_url is not None else getattr(recording_client, "snippets_by_url", {})
        completed = set(executed_steps or ())
        failed = set()
        if recording_client is not None:
            completed = {c.step for c in recording_client.tool_calls if c.status == EventStatus.COMPLETED}
            failed = {c.step for c in recording_client.tool_calls if c.status == EventStatus.FAILED}

        def usable(claim):
            return bool(claim and claim.value and claim.extraction_status not in
                        (ExtractionStatus.UNCERTAIN, ExtractionStatus.MISSING) and
                        not is_redaction_placeholder(claim.value))

        # Do not infer successful retrieval from a URL or an analysis explanation.
        metas = []
        for key, entries in snippets.items():
            for meta in entries:
                status = meta.get("retrieval_status")
                if status not in (RetrievalStatus.LIVE, RetrievalStatus.CACHED) and not (self.demo_mode and status == RetrievalStatus.DEMO):
                    continue
                url = meta.get("source_url") or key
                if not DomainResolver.normalize_and_parse_url(url).is_valid:
                    continue
                if any(re.search(r"token|signature|password|secret|api[_-]?key|authorization", key, re.I)
                       for key, _ in parse_qsl(urlparse(url).query)):
                    continue
                metas.append(dict(meta, source_url=url))
        metas.sort(key=lambda m: (m["source_url"], m.get("title", ""), m.get("snippet", ""), m.get("query", "")))

        # An ATS tenant's spelling is only a candidate. Require an independently
        # retrieved employer-domain record publishing the careers portal link.
        published_ats = []
        if careers_url:
            for meta in metas:
                host = urlparse(meta["source_url"]).hostname or ""
                if canon and DomainResolver.is_matching_domain(host, canon) and careers_url in meta.get("snippet", ""):
                    published_ats.append(careers_url.rstrip("/"))
        identity = DomainResolver._extract_company_identity(company_name)

        def attributable(meta):
            parsed = DomainResolver.normalize_and_parse_url(meta["source_url"])
            if canon and DomainResolver.is_matching_domain(parsed.hostname, canon):
                return SourceTier.OFFICIAL_EMPLOYER
            if DomainResolver.is_hosted_careers_platform(parsed.hostname) and DomainResolver._is_associated_hosted_careers(parsed, identity):
                url = meta["source_url"].rstrip("/")
                if any(url == base or url.startswith(base + "/") for base in published_ats):
                    return SourceTier.ESTABLISHED_THIRD_PARTY
            return None

        hiring = [(m, attributable(m)) for m in metas if attributable(m)]
        established_ats = {canonicalize_url(m["source_url"]) for m, tier in hiring if tier == SourceTier.ESTABLISHED_THIRD_PARTY}

        def item(meta, tier, relation=EvidenceRelation.SUPPORTS):
            return {"source_url": meta["source_url"], "title": meta.get("title", ""),
                    "description": meta.get("snippet", ""), "source_tier": tier,
                    "relation": relation, "metadata": meta}

        def observe(claim, status, codes, explanation, items=()):
            result.observations[claim.claim_id] = CorroborationObservation(
                claim.claim_id, claim.kind, status, list(codes), explanation, list(items))

        def checked(claim, steps, matched=False):
            if matched or completed.intersection(steps):
                result.executed_checks.add(claim.kind)
                return ClaimStatus.UNRESOLVED
            if failed.intersection(steps):
                result.failed_checks.add(claim.kind)
                return ClaimStatus.UNRESOLVED
            return ClaimStatus.NOT_CHECKED

        def vacancy(meta):
            text = (meta.get("title", "") + " " + meta.get("snippet", "")).lower()
            path = urlparse(meta["source_url"]).path.lower()
            if re.search(r"\b(?:closed|expired|filled|no longer accepting|not hiring|no vacancies|applications closed|position filled)\b", text):
                return False
            return bool(re.search(r"\b(?:hiring|opening|vacancy|vacancies|requisition)\b", text)
                        or re.search(r"/(?:jobs?|openings)/[^/]+", path))

        role = by_kind.get(ClaimKind.ROLE)
        location = by_kind.get(ClaimKind.LOCATION)
        matches = []
        if usable(role):
            wanted = normalize_job_title(role.value)
            for meta, tier in hiring:
                # Contiguous whole-token title alignment preserves specialty and
                # seniority; exclude incompatible levels even for unqualified roles.
                title = normalize_job_title(meta.get("title", ""))
                snippet = normalize_job_title(meta.get("snippet", ""))
                text_tokens = title + snippet
                level_mismatch = (set(text_tokens) & SENIORITY_MODIFIERS) != (set(wanted) & SENIORITY_MODIFIERS)
                contiguous = any(tokens[i:i + len(wanted)] == wanted
                                 for tokens in (title, snippet)
                                 for i in range(max(0, len(tokens) - len(wanted) + 1)))
                if wanted and contiguous and not level_mismatch and vacancy(meta):
                    matches.append((meta, tier))
            state = checked(role, self.JOB_STEPS, bool(matches))
            if matches:
                observe(role, ClaimStatus.SUPPORTED, ["ROLE_CORROBORATED", "PUBLIC_VACANCY_LISTED", "PUBLIC_VACANCY_MATCH"],
                        "Retrieved public hiring records match the claimed role. Listing currency and individual offer issuance remain unconfirmed.",
                        [item(m, tier) for m, tier in matches])
            else:
                codes = ["SEARCH_UNAVAILABLE"] if role.kind in result.failed_checks else ["CHECK_NOT_EXECUTED"] if state == ClaimStatus.NOT_CHECKED else ["VACANCY_NOT_FOUND", "NO_MATCHING_VACANCY"]
                observe(role, state, codes, "No attributable matching vacancy was corroborated. Missing, unlisted or closed postings do not prove fraud.")

        if usable(location):
            city = location.value.split(",")[0].strip()
            loc_matches = []
            for meta, tier in matches:
                text = meta.get("title", "") + " " + meta.get("snippet", "")
                for sentence in re.split(r"[.;\n]", text):
                    if re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", sentence, re.I) and not re.search(r"headquarter|\bhq\b|registered office|corporate office", sentence, re.I):
                        if (re.search(r"\b(?:location|based|remote|hybrid)\b", sentence, re.I)
                                or (normalize_job_title(role.value) and
                                    " ".join(normalize_job_title(role.value)) in " ".join(normalize_job_title(sentence)))
                                or re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", meta.get("title", ""), re.I)):
                            loc_matches.append((meta, tier))
                            break
            state = checked(location, self.JOB_STEPS, bool(matches))
            if loc_matches:
                observe(location, ClaimStatus.SUPPORTED, ["LOCATION_CORROBORATED", "VACANCY_LOCATION_MATCH"],
                        "The relevant public vacancy record includes the claimed job location.", [item(m, tier) for m, tier in loc_matches])
            else:
                codes = ["SEARCH_UNAVAILABLE"] if location.kind in result.failed_checks else ["CHECK_NOT_EXECUTED"] if state == ClaimStatus.NOT_CHECKED else ["LOCATION_NOT_CORROBORATED", "LOCATION_UNCORROBORATED", "HEADQUARTERS_ONLY_NOT_JOB_LOCATION"]
                observe(location, state, codes, "The relevant hiring records do not establish the claimed job location; headquarters alone are insufficient.")

        ref = by_kind.get(ClaimKind.JOB_REFERENCE)
        if usable(ref):
            if not is_public_job_reference(ref.value, ref.source_quote)[0]:
                observe(ref, ClaimStatus.NOT_CHECKED, ["NOT_PUBLIC_REQUISITION"], "This reference is private or ambiguous and was not searched as a public requisition.")
            else:
                pattern = re.compile(r"(?<![\w-])" + re.escape(ref.value.strip()) + r"(?![\w-])", re.I)
                ref_matches = [(m, tier) for m, tier in hiring if vacancy(m) and pattern.search(m.get("title", "") + " " + m.get("snippet", ""))]
                state = checked(ref, self.REF_STEPS, bool(ref_matches))
                if ref_matches:
                    observe(ref, ClaimStatus.SUPPORTED, ["JOB_REFERENCE_MATCHED", "PUBLIC_REQUISITION_VERIFIED"],
                            "The exact public requisition appears in attributable employer hiring records; this does not authenticate an individual offer.",
                            [item(m, tier) for m, tier in ref_matches])
                else:
                    codes = ["SEARCH_UNAVAILABLE"] if ref.kind in result.failed_checks else ["CHECK_NOT_EXECUTED"] if state == ClaimStatus.NOT_CHECKED else ["REQUISITION_NOT_FOUND"]
                    observe(ref, state, codes, "No attributable exact public requisition match was corroborated.")

        app = by_kind.get(ClaimKind.APPLICATION_URL)
        if usable(app):
            evaluation = evaluate_application_destination(app.value, company_name, canon,
                {m["source_url"] for m in metas}, established_ats_urls=established_ats)
            matching = [(m, tier) for m, tier in hiring if canonicalize_url(m["source_url"]) == canonicalize_url(app.value)]
            state = checked(app, self.JOB_STEPS | self.REF_STEPS, bool(matching))
            items = [item(m, tier, evaluation["relation"]) for m, tier in matching]
            # Unsafe URL syntax and hostname concerns are local document analysis,
            # never invented search results. Ground the original submitted quote.
            if evaluation["status"] == ClaimStatus.CONTRADICTED and app.source_quote and app.value in app.source_quote:
                items = [{"document_quote": app.source_quote, "relation": EvidenceRelation.CONTRADICTS}]
                result.executed_checks.add(app.kind)
                state = ClaimStatus.CONTRADICTED
            elif matching:
                state = evaluation["status"]
            elif state != ClaimStatus.NOT_CHECKED:
                state = ClaimStatus.UNRESOLVED
            codes = [evaluation["reason_code"]] if state != ClaimStatus.NOT_CHECKED else ["CHECK_NOT_EXECUTED"]
            observe(app, state, codes, evaluation["explanation"] if state != ClaimStatus.NOT_CHECKED else "Independent application destination corroboration was not executed.", items)

        route, route_meta = self._discover_route(company_name, canon, careers_url, hiring, claims)
        result.confirmation_route = route
        result.confirmation_evidence = route_meta
        return result

    def _discover_route(self, company_name, canonical_domain, careers_url, hiring, claims):
        by_kind = {c.kind: c for c in claims}
        def value(kind):
            claim = by_kind.get(kind)
            return claim.value if claim and claim.extraction_status not in (ExtractionStatus.UNCERTAIN, ExtractionStatus.MISSING) and not is_redaction_placeholder(claim.value or "") else None
        submitted = (value(ClaimKind.SENDER_EMAIL) or "").lower().strip()
        candidates = []
        for meta, tier in hiring:
            text = meta.get("title", "") + " " + meta.get("snippet", "")
            # Official email/phone channels must be employer-published, rather
            # than inferred from a third-party tenant or a warning about a scammer.
            if tier == SourceTier.OFFICIAL_EMPLOYER:
                for sentence in re.split(r"[;\n]|(?<=[.!?])\s+(?=[A-Z])", text):
                    if re.search(r"\b(?:do not|never|avoid|fake|fraudulent|unauthorized|scammer)\b", sentence, re.I):
                        continue
                    purpose = re.search(r"\b(?:verify|verification|recruitment|careers|contact hr|hiring|switchboard|board line|office phone)\b", sentence, re.I)
                    if not purpose:
                        continue
                    for email in re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", sentence):
                        prefix, host = email.lower().split("@")
                        if canonical_domain and DomainResolver.is_matching_domain(host, canonical_domain) and email.lower() != submitted and any(re.fullmatch(re.escape(p) + r"(?:[-_.].*)?", prefix) for p in CONFIRMATION_EMAIL_PREFIXES):
                            candidates.append((0, "official_email", email.lower(), meta))
                    if re.search(r"switchboard|board line|contact careers|recruitment office|office phone", sentence, re.I):
                        phone = re.search(r"(?:switchboard|board line|contact careers|recruitment office|office phone)(?:\s+(?:phone|number))?\s*(?:[:=]|at|on|-)?\s*(?P<phone>\+91[-\s]?[6-9]\d{9}|[6-9]\d{9}|\+\d{1,3}[-\s]\d[\d -]{7,14}\d)(?!\w)", sentence, re.I)
                        if phone:
                            candidates.append((1, "official_phone", phone.group("phone").strip(), meta))
            url = meta["source_url"]
            if careers_url and canonicalize_url(url) == canonicalize_url(careers_url):
                candidates.append((2, "careers_portal", careers_url, meta))
            elif tier == SourceTier.ESTABLISHED_THIRD_PARTY and re.search(r"careers|jobs|opening|apply", text, re.I):
                candidates.append((2, "careers_portal", url, meta))
        if not candidates:
            return None, None
        _, channel, destination, meta = min(candidates, key=lambda c: (c[0], c[2], c[3]["source_url"], c[3].get("snippet", "")))
        ref = by_kind.get(ClaimKind.JOB_REFERENCE)
        public_ref = value(ClaimKind.JOB_REFERENCE) if ref and is_public_job_reference(ref.value or "", ref.source_quote)[0] else None
        draft = generate_confirmation_draft(channel, company_name, value(ClaimKind.ROLE), public_ref, value(ClaimKind.RECRUITER_NAME))
        return ConfirmationRoute(channel=channel, destination=destination, evidence_id=meta["source_url"], draft_message=draft), meta
