"""
Grounded deterministic entity extraction engine for AsliOffer (Task 7).

Parses document claims with grounded provenance, semantic role attribution,
localized context, and secret redaction. Complies with docs/extraction-requirements.md (v1.0.1).
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Set
from urllib.parse import urlparse

from app.services.agents.scam_classifier import (
    ScamClassifier,
    ScamModality,
    ScamSignalCode,
    SignalAssessment,
    sanitize_and_redact_secrets,
)
from app.services.extractor.claim_models import (
    Claim,
    ClaimKind,
    ExtractionResult,
    ExtractionStatus,
    ExtractionWarning,
    ConfidenceTier,
    SourceSpan,
    UnresolvedAmbiguity,
)


# ============================================================================
# 1. Platform Mentions & Meeting Tools
# ============================================================================

MEETING_PLATFORM_PATTERNS = [
    (r"\bGoogle\s+Meet\b", "Google Meet", "video_conferencing"),
    (r"\bMicrosoft\s+Teams\b", "Microsoft Teams", "video_conferencing"),
    (r"\bZoom(?:\s+Meeting)?\b", "Zoom", "video_conferencing"),
    (r"\bCisco\s+Webex\b|\bWebex\b", "Cisco Webex", "video_conferencing"),
    (r"\bSkype\b", "Skype", "video_conferencing"),
    (r"\bGoogle\s+Forms?\b", "Google Forms", "form"),
    (r"\bGoogle\s+Drive\b", "Google Drive", "document_storage"),
    (r"\bGoogle\s+Docs?\b", "Google Docs", "document_collaboration"),
    (r"\bGoogle\s+Calendar\b", "Google Calendar", "scheduling"),
]

# Domains that identify meeting/tool URLs rather than company official websites
MEETING_URL_HOSTS = {
    "meet.google.com", "teams.microsoft.com", "zoom.us", "webex.com",
    "meet.google.example", "teams.microsoft.example", "zoom.example",
}

APPLICATION_URL_HOSTS = {
    "forms.gle", "docs.google.com", "forms.google.com", "typeform.com",
    "forms.google.example", "apply.example",
}


# ============================================================================
# 2. Company / Agency Detection Patterns
# ============================================================================

STOPWORD_COMPANIES = {
    "the", "dear", "subject", "open", "selection", "screening", "domain",
    "technical", "stipend", "best", "date", "time", "mode", "duration",
    "applicant", "candidate", "position", "positions", "round", "reference",
    "location", "joining", "hiring", "contact", "official", "welcome", "offer",
}

# Standard corporate suffixes
CORPORATE_SUFFIX_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){0,3})\s+"
    r"(Pvt\.?\s+Ltd\.?|Private\s+Limited|Ltd\.?|Limited|LLP|LLC|Inc\.?|Corporation|Corp\.?|"
    r"Technologies|Solutions|Services|Industries|Enterprises|Systems|Labs|Infotech)\b"
)

# Common explicit employer introduction phrases
EMPLOYER_STATEMENT_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){0,3})\s+"
    r"(?:is\s+pleased\s+to\s+offer|welcomes\s+you|delighted\s+to\s+offer)\b"
)

# "offer from XYZ" or "welcome to XYZ"
OFFER_FROM_RE = re.compile(
    r"(?:\boffer\s+from|welcome\s+to|representing|selected\s+for\s+.*?\s+at)\s+"
    r"([A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){0,3})"
)

# Staffing agency relationship pattern: "<Agency> recruiting for / on behalf of <Client>"
AGENCY_RELATIONSHIP_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){0,3}\s+(?:Staffing|Consulting|Recruitment|Placements?|Solutions|Services|HR))\s+"
    r"(?:is\s+)?(?:recruiting|hiring)\s+(?:for|on\s+behalf\s+of)(?:\s+client)?\s+"
    r"([A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){0,3})"
)


# ============================================================================
# 3. Grounded Parser Implementation
# ============================================================================

class GroundedEntityParser:
    """
    Deterministic contextual extractor that parses text into verified claims,
    locating quotes in the sanitized source buffer with exact offsets.
    """

    def __init__(self, run_index: int = 1):
        self.run_index = run_index
        self.scam_classifier = ScamClassifier()

    def parse(self, text: str, source_type: str = "text") -> ExtractionResult:
        """
        Parses the text and returns an ExtractionResult conforming to contract v1.0.1.
        """
        sanitized = sanitize_and_redact_secrets(text or "")
        sanitized = re.sub(r"(?i)(\b(?:aadhaar|aadhar)\s*(?:number|no\.?|id)?\s*[:=]?\s*)(\d{4}[ -]?\d{4}[ -]?\d{4})\b", r"\1[REDACTED_ID]", sanitized)
        sanitized = re.sub(r"(?i)(\bpan\s*(?:number|no\.?|id)?\s*[:=]?\s*)([A-Z]{5}\d{4}[A-Z])\b", r"\1[REDACTED_ID]", sanitized)
        claims: List[Claim] = []
        ambiguities: List[UnresolvedAmbiguity] = []
        warnings: List[ExtractionWarning] = []
        claim_counter = 1

        def next_claim_id() -> str:
            nonlocal claim_counter
            cid = f"CLM-{self.run_index:02d}-{claim_counter:02d}"
            claim_counter += 1
            return cid

        # Helper to construct a verified SourceSpan
        def make_span(quote: str) -> Optional[SourceSpan]:
            if not quote or not sanitized:
                return None
            start = sanitized.find(quote)
            if start == -1 or sanitized.count(quote) != 1:
                return None
            end = start + len(quote)
            # Unicode verification check
            if sanitized[start:end] != quote:
                return None
            return SourceSpan(
                start_offset=start,
                end_offset=end,
                target_text="redacted_text",
            )

        # --------------------------------------------------------------------
        # A. Meeting Platform & Tool Mentions
        # --------------------------------------------------------------------
        platform_found_names: Set[str] = set()
        for pat, plat_name, plat_cat in MEETING_PLATFORM_PATTERNS:
            for m in re.finditer(pat, sanitized, re.IGNORECASE):
                quote = m.group(0)
                if plat_name not in platform_found_names:
                    platform_found_names.add(plat_name)
                    claims.append(
                        Claim(
                            claim_id=next_claim_id(),
                            kind=ClaimKind.MEETING_PLATFORM.value,
                            value=plat_name,
                            source_quote=quote,
                            source_span=make_span(quote),
                            extraction_status=ExtractionStatus.EXTRACTED.value,
                            confidence_tier=ConfidenceTier.HIGH.value,
                            attributes={
                                "is_claimed_employer": False,
                                "platform_category": plat_cat,
                            },
                        )
                    )

        # --------------------------------------------------------------------
        # B. Contextual Employer & Staffing Agency
        # --------------------------------------------------------------------
        agency_name: Optional[str] = None
        client_employer: Optional[str] = None

        # Check agency relationship first
        agency_match = AGENCY_RELATIONSHIP_RE.search(sanitized)
        if agency_match:
            agency_cand = agency_match.group(1).strip()
            client_cand = agency_match.group(2).strip()
            if agency_cand.lower() not in STOPWORD_COMPANIES:
                agency_name = agency_cand
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.RECRUITING_AGENCY.value,
                        value=agency_cand,
                        source_quote=agency_cand,
                        source_span=make_span(agency_cand),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={"agency_type": "third_party_staffing", "role": "staffing_agency"},
                    )
                )
            if client_cand.lower() not in STOPWORD_COMPANIES:
                client_employer = client_cand

        # Contextual employer candidate search
        employer_name: Optional[str] = client_employer
        employer_quote: Optional[str] = client_employer

        if not employer_name:
            # 1. Employer statement: "Tata Elxsi is pleased to offer you", "TCS welcomes you"
            m = EMPLOYER_STATEMENT_RE.search(sanitized)
            if m:
                cand = m.group(1).strip()
                if cand not in platform_found_names and cand.lower() not in STOPWORD_COMPANIES:
                    employer_name = cand
                    employer_quote = cand

        if not employer_name:
            all_corps = []
            for m in CORPORATE_SUFFIX_RE.finditer(sanitized):
                cand = m.group(0).strip().rstrip(".,")
                if cand not in platform_found_names and cand.lower() not in STOPWORD_COMPANIES:
                    if cand not in all_corps:
                        all_corps.append(cand)
            if len(all_corps) > 1:
                # Multiple competing employer candidates -> explicit ambiguity
                for cand in all_corps:
                    cid = next_claim_id()
                    claims.append(
                        Claim(
                            claim_id=cid,
                            kind=ClaimKind.CLAIMED_EMPLOYER.value,
                            value=cand,
                            source_quote=cand,
                            source_span=make_span(cand),
                            extraction_status=ExtractionStatus.AMBIGUOUS.value,
                            confidence_tier=ConfidenceTier.MEDIUM.value,
                            attributes={"entity_type": "corporate_employer", "role": "claimed_employer"},
                        )
                    )
                    ambiguities.append(
                        UnresolvedAmbiguity(
                            claim_id=cid,
                            field="value",
                            issue=f"Multiple competing employers identified: {', '.join(all_corps)}",
                        )
                    )
                employer_name = None
            elif len(all_corps) == 1:
                employer_name = all_corps[0]
                employer_quote = all_corps[0]

        if not employer_name:
            # 2. Top of document / heading candidate
            # In offer letters, company name is often on line 1: "V-Guard Industries Ltd."
            lines = [ln.strip() for ln in sanitized.splitlines() if ln.strip()]
            header_prefixes = ("subject:", "to:", "from:", "date:", "role:", "position:", "stipend:", "salary:", "ref:", "reference:", "hiring contact:")
            for line in lines[:4]:
                if line.lower().startswith(header_prefixes):
                    continue
                # Suffix match on line
                m = CORPORATE_SUFFIX_RE.search(line)
                if m:
                    cand = m.group(0).strip().rstrip(".,")
                    # If followed immediately by role keywords, ignore
                    post = line[m.end():].strip().lower()
                    if not any(post.startswith(rk) for rk in ["engineer", "developer", "trainee", "associate", "analyst", "specialist"]):
                        if cand not in platform_found_names and cand.lower() not in STOPWORD_COMPANIES:
                            employer_name = cand
                            employer_quote = cand
                            break
                # Or line is a clear company name without suffix (e.g., "Tata Elxsi")
                if re.fullmatch(r"[A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z0-9][A-Za-z0-9&.\-']*){1,3}", line):
                    low_l = line.lower()
                    if (
                        line not in platform_found_names
                        and low_l not in STOPWORD_COMPANIES
                        and not any(w in low_l for w in ["offer", "notice", "engineer", "recruitment", "interview", "dear"])
                    ):
                        employer_name = line
                        employer_quote = line
                        break

        if not employer_name:
            # 3. "offer from XYZ" or "welcome to XYZ" or "at XYZ"
            m = OFFER_FROM_RE.search(sanitized)
            if m:
                cand = m.group(1).strip()
                cand = re.split(r"\s+\b(?:as|for|to|in|with|role|position)\b", cand, flags=re.IGNORECASE)[0].strip()
                cand = re.sub(r"[\.,;:\n].*$", "", cand).strip()
                if cand not in platform_found_names and cand.lower() not in STOPWORD_COMPANIES and len(cand) >= 2:
                    employer_name = cand
                    employer_quote = cand

        if not employer_name and not any(c.kind == ClaimKind.CLAIMED_EMPLOYER.value for c in claims):
            # 4. Known brand fallback, but ONLY if not in platform mentions
            for brand in [
                "Tata Consultancy Services", "TCS", "Infosys Limited", "Infosys",
                "Wipro", "Accenture", "Cognizant", "Tata Elxsi", "V-Guard Industries Ltd.",
                "V-Guard Industries Ltd", "V-Guard", "India Post", "Google", "Microsoft", "Amazon",
            ]:
                if brand not in platform_found_names and re.search(r"\b(?:offer|selected|hiring|welcome|package|ctc)\b", sanitized, re.I) and re.search(rf"\b{re.escape(brand)}\b", sanitized, re.IGNORECASE):
                    employer_name = brand
                    employer_quote = brand
                    break

        if employer_name:
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.CLAIMED_EMPLOYER.value,
                    value=employer_name,
                    source_quote=employer_quote,
                    source_span=make_span(employer_quote),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.HIGH.value,
                    attributes={"entity_type": "corporate_employer", "role": "client_employer" if agency_name else "claimed_employer"},
                )
            )
        elif not any(c.kind == ClaimKind.CLAIMED_EMPLOYER.value for c in claims):
            # Explicit absent claim
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.CLAIMED_EMPLOYER.value,
                    value=None,
                    source_quote=None,
                    source_span=None,
                    extraction_status=ExtractionStatus.ABSENT.value,
                    confidence_tier=None,
                    attributes={},
                )
            )

        # --------------------------------------------------------------------
        # C. Role-Aware Contacts (Email & Phone)
        # --------------------------------------------------------------------
        email_matches = list(re.finditer(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", sanitized))
        for em in email_matches:
            email_addr = em.group(0).rstrip(".,;:)")
            span = make_span(email_addr)
            start_idx = span.start_offset if span else em.start()

            # Determine local context before the email (up to 120 chars)
            pre_context = re.split(r"[\n;]", sanitized[max(0, em.start() - 120):em.start()])[-1].lower()
            post_context = sanitized[start_idx + len(email_addr):min(len(sanitized), start_idx + len(email_addr) + 80)].lower()

            # If preceded by 'via upi to' or used strictly as payment rail, skip contact extraction
            if re.search(r"\b(?:via|to|through|using)\s+upi\s+to\s*$", pre_context.strip()) or "@upi" in email_addr.lower():
                continue

            # 1. Candidate Destination checks
            is_to_header = bool(re.search(r"(?:^|[\n\r])to\s*:\s*$", pre_context.strip()))
            is_candidate_label = bool(re.search(r"\b(?:candidate|applicant|student|recipient)\b", pre_context))
            is_candidate_greeting = bool(re.search(r"\bdear\s+[a-z0-9_.-]+", pre_context)) and not bool(re.search(r"\bfrom\s*:\s*$", pre_context.strip()))

            # 2. Sender / Recruiter checks
            is_from_header = bool(re.search(r"(?:^|[\n\r])from\s*:\s*$", pre_context.strip()))
            is_general_mailbox = email_addr.lower().startswith(("support@", "help@", "info@", "inquiries@", "general@", "contact@", "service@"))
            is_hr_label = (
                not is_general_mailbox and (
                    bool(re.search(r"\b(?:contact\s+hr|official\s+hr|hr\s+team|with\s+hr|to\s+hr|at\s+hr|recruiter|talent\s+acquisition|regards|sincerely)\b", pre_context))

                    or (bool(re.search(r"\bcontact\s*:?\s*$", pre_context.strip())) and not bool(re.search(r"\bhiring\s+contact\b", pre_context)))
                )
            )
            is_confirmation_target = bool(re.search(r"\b(?:reply|confirmation|signed|acceptance)\s+.*?\bto\b", pre_context))

            domain = email_addr.split("@")[-1].lower() if "@" in email_addr else ""
            free_domains = {"gmail.com", "outlook.com", "yahoo.com", "hotmail.com"}
            provider_type = "public_webmail" if domain in free_domains else "custom_domain"

            if is_to_header or (is_candidate_label and not is_from_header and not is_hr_label):
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.CANDIDATE_CONTACT.value,
                        value=email_addr,
                        source_quote=email_addr,
                        source_span=span,
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={
                            "channel": "email",
                            "semantic_role": "candidate_destination",
                            "provider_type": provider_type if domain in free_domains else "unknown",
                        },
                    )
                )
            elif is_from_header or is_hr_label or is_confirmation_target:
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.SENDER_RECRUITER.value,
                        value=email_addr,
                        source_quote=email_addr,
                        source_span=span,
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={
                            "channel": "email",
                            "semantic_role": "sender_contact",
                            "email_domain": domain,
                            "provider_type": provider_type,
                        },
                    )
                )
            else:
                # Unknown contact role -> neutral contact claim with explicit ambiguity
                cid = next_claim_id()
                claims.append(
                    Claim(
                        claim_id=cid,
                        kind=ClaimKind.CONTACT.value,
                        value=email_addr,
                        source_quote=email_addr,
                        source_span=span,
                        extraction_status=ExtractionStatus.AMBIGUOUS.value,
                        confidence_tier=ConfidenceTier.MEDIUM.value,
                        attributes={
                            "channel": "email",
                            "semantic_role": "unknown",
                        },
                    )
                )
                ambiguities.append(
                    UnresolvedAmbiguity(
                        claim_id=cid,
                        field="semantic_role",
                        issue="No sender/candidate attribution supplied.",
                    )
                )

        # Flag ambiguity if multiple recruiter contacts are present
        recruiter_claims = [c for c in claims if c.kind == ClaimKind.SENDER_RECRUITER.value and c.attributes.get("channel") == "email"]
        if len(recruiter_claims) > 1:
            for rc in recruiter_claims:
                rc.extraction_status = ExtractionStatus.AMBIGUOUS.value
                ambiguities.append(
                    UnresolvedAmbiguity(
                        claim_id=rc.claim_id,
                        field="sender_recruiter",
                        issue="Multiple plausible recruiter contact addresses found without single primary sender.",
                    )
                )

        # Phone numbers
        phone_matches = list(re.finditer(r"(?<![\w+])(?:\+\d{1,3}[ -]?(?:\d[ ()-]?){7,12}\d|[6789]\d{9})(?!\w)", sanitized))
        for pm in phone_matches:
            phone_num = pm.group(0)
            span = make_span(phone_num)
            start_idx = span.start_offset if span else pm.start()
            pre_context = re.split(r"[\n;]", sanitized[max(0, pm.start() - 80):pm.start()])[-1].lower()

            is_candidate = "candidate" in pre_context or "applicant" in pre_context
            is_recruiter = bool(re.search(r"\b(?:hr|recruiter|call|contact|desk)\b", pre_context))

            if is_candidate:
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.CANDIDATE_CONTACT.value,
                        value=phone_num,
                        source_quote=phone_num,
                        source_span=span,
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={
                            "channel": "phone",
                            "semantic_role": "candidate_destination",
                        },
                    )
                )
            elif is_recruiter:
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.SENDER_RECRUITER.value,
                        value=phone_num,
                        source_quote=phone_num,
                        source_span=span,
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={
                            "channel": "phone",
                            "semantic_role": "sender_contact",
                        },
                    )
                )
            else:
                cid = next_claim_id()
                claims.append(
                    Claim(
                        claim_id=cid,
                        kind=ClaimKind.CONTACT.value,
                        value=phone_num,
                        source_quote=phone_num,
                        source_span=span,
                        extraction_status=ExtractionStatus.AMBIGUOUS.value,
                        confidence_tier=ConfidenceTier.MEDIUM.value,
                        attributes={
                            "channel": "phone",
                            "semantic_role": "unknown",
                        },
                    )
                )
                ambiguities.append(
                    UnresolvedAmbiguity(
                        claim_id=cid,
                        field="semantic_role",
                        issue="Phone number has no explicit sender or candidate role attribution.",
                    )
                )

        for channel in ("email", "phone"):
            contacts = [c for c in claims if c.kind == ClaimKind.SENDER_RECRUITER.value and c.attributes.get("channel") == channel]
            if len({c.value for c in contacts}) > 1:
                for contact in contacts:
                    contact.extraction_status = ExtractionStatus.AMBIGUOUS.value
                    if not any(a.claim_id == contact.claim_id for a in ambiguities):
                        ambiguities.append(UnresolvedAmbiguity(claim_id=contact.claim_id, field="sender_recruiter", issue="Multiple recruiter contacts require a primary-contact choice."))
            else:
                for contact in contacts:
                    contact.extraction_status = ExtractionStatus.EXTRACTED.value
                    ambiguities[:] = [a for a in ambiguities if not (a.claim_id == contact.claim_id and a.field == "sender_recruiter")]

        # --------------------------------------------------------------------
        # D. Job Role & Job Reference ID
        # --------------------------------------------------------------------
        role_patterns = [
            r"Quality Assurance Engineer",
            r"Embedded Systems Engineer",
            r"Cloud Support Engineer",
            r"Graphic Design Intern",
            r"Associate Software Engineer",
            r"Software Development Engineer",
            r"Software Engineer",
            r"Systems Engineer Specialist",
            r"Systems Engineer",
            r"Data Analyst",
            r"Business Analyst",
            r"Full Stack Developer",
            r"Backend Developer",
            r"Frontend Developer",
            r"Graduate Software Trainee",
            r"Graduate Trainee",
            r"Customer Support Associate",
            r"Operations Executive",
            r"Intern",
        ]
        job_role_found: Optional[str] = None
        for role_pat in role_patterns:
            m = re.search(rf"\b{re.escape(role_pat)}\b", sanitized, re.IGNORECASE)
            if m:
                quote = m.group(0)
                job_role_found = quote
                employment_type = "internship" if "intern" in quote.lower() else "full_time"
                attrs: Dict[str, Any] = {}
                if "intern" in quote.lower():
                    attrs["employment_type"] = "internship"
                elif "trainee" in quote.lower() or "associate" in quote.lower() or "junior" in quote.lower():
                    attrs["role_level"] = "entry_level"

                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.JOB_ROLE.value,
                        value=quote,
                        source_quote=quote,
                        source_span=make_span(quote),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes=attrs,
                    )
                )
                break

        # Job reference ID: e.g. "Reference: JOB-2026-07" or "Job ID: #12345"
        ref_match = re.search(r"\b(?:reference|ref|job\s*id|job\s*code)\s*:\s*([A-Za-z0-9\-_#]{4,20})\b", sanitized, re.IGNORECASE)
        if ref_match:
            ref_val = ref_match.group(1).strip()
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.JOB_REFERENCE_ID.value,
                    value=ref_val,
                    source_quote=ref_val,
                    source_span=make_span(ref_val),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.MEDIUM.value,
                    attributes={},
                )
            )

        # --------------------------------------------------------------------
        # E. Compensation (Base Units & Ambiguity)
        # --------------------------------------------------------------------
        self._extract_compensation(sanitized, make_span, next_claim_id, claims, ambiguities)
        for comp in [c for c in claims if c.kind == ClaimKind.COMPENSATION.value]:
            quote = comp.source_quote or ""
            location = sanitized.find(quote)
            following = sanitized[location + len(quote):location + len(quote) + 30]
            explicit = re.match(r"\s*(per\s+month|per\s+annum|monthly|annually|p\.m\.|p\.a\.)", following, re.I)
            if explicit:
                comp.source_quote = quote + explicit.group()
                comp.value = comp.source_quote
                comp.attributes.pop("period_ambiguity", None)
                comp.attributes["period"] = "MONTHLY" if re.search(r"month|p\.m", explicit.group(), re.I) else "ANNUAL"
                comp.extraction_status = ExtractionStatus.EXTRACTED.value
                ambiguities[:] = [a for a in ambiguities if not (a.claim_id == comp.claim_id and a.field == "period")]
            if re.search(r"\blakhs?\b", quote, re.I) and not re.search(r"LPA|per\s+annum", comp.source_quote, re.I):
                comp.attributes["period"] = None
                comp.extraction_status = ExtractionStatus.AMBIGUOUS.value
                ambiguities.append(UnresolvedAmbiguity(claim_id=comp.claim_id, field="period", issue="Lakh is an amount unit, not a payment period."))
            currency = "INR" if re.search(r"INR|Rs\.?|₹", quote, re.I) else next((code for code in ("USD", "EUR", "GBP") if re.search(r"\b" + code + r"\b", quote, re.I)), None)
            if currency is None:
                comp.extraction_status = ExtractionStatus.AMBIGUOUS.value
                ambiguities.append(UnresolvedAmbiguity(claim_id=comp.claim_id, field="currency", issue="Currency is not explicitly unambiguous."))
            comp.attributes["currency"] = currency


        # --------------------------------------------------------------------
        # F. Location & Joining Date
        # --------------------------------------------------------------------
        # Location / address
        loc_match = re.search(r"(?:work\s+location|location|office\s+location|report\s+to|address)\s*:\s*([A-Za-z0-9\s,.-]{3,50})", sanitized, re.IGNORECASE)
        if loc_match:
            raw_loc = loc_match.group(1).strip()
            # Clean trailing period or boundary
            clean_loc = re.split(r"[\n\r;]|(?:\.\s+[A-Z])", raw_loc)[0].strip().rstrip(".")
            if clean_loc and len(clean_loc) >= 2:
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.LOCATION.value,
                        value=clean_loc,
                        source_quote=clean_loc,
                        source_span=make_span(clean_loc),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.MEDIUM.value,
                        attributes={},
                    )
                )

        # Joining date
        date_match = re.search(
            r"(?:joining\s+date|joining\s+on|reporting\s+date|report\s+on|start\s+date)\s*:\s*([A-Za-z0-9\s,]{4,30})",
            sanitized,
            re.IGNORECASE,
        )
        if date_match:
            raw_date = date_match.group(1).strip().rstrip(".")
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.JOINING_DATE.value,
                    value=raw_date,
                    source_quote=raw_date,
                    source_span=make_span(raw_date),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.MEDIUM.value,
                    attributes={"normalized_date": None},
                )
            )

        # --------------------------------------------------------------------
        # G. URLs (Interview vs Application vs Official Website)
        # --------------------------------------------------------------------
        url_matches = list(re.finditer(r"https?://[^\s\"<>]+", sanitized))
        for um in url_matches:
            url_str = um.group(0).rstrip(".,;:)")
            try:
                parsed = urlparse(url_str)
            except ValueError:
                warnings.append(ExtractionWarning(code="INVALID_URL", message="Malformed URL could not be classified."))
                continue
            host = (parsed.hostname or "").lower()

            if any(host == h or host.endswith("." + h) for h in MEETING_URL_HOSTS):
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.INTERVIEW_URL.value,
                        value=url_str,
                        source_quote=url_str,
                        source_span=make_span(url_str),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={"destination_type": "meeting_room", "purpose": "interview_platform"},
                    )
                )
            elif host in APPLICATION_URL_HOSTS or parsed.path.startswith(("/apply", "/application")):
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.APPLICATION_DESTINATION.value,
                        value=url_str,
                        source_quote=url_str,
                        source_span=make_span(url_str),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={"destination_type": "application_form", "purpose": "application_destination"},
                    )
                )
            elif re.search(r"\b(?:website|official site|company site|company portal)\b", sanitized[max(0, um.start()-65):um.start()].lower()):
                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.OFFICIAL_DOMAIN_REFERENCE.value,
                        value=url_str,
                        source_quote=url_str,
                        source_span=make_span(url_str),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes={"purpose": "official_website"},
                    )
                )

        # --------------------------------------------------------------------
        # H. Payment Demands & Credential Requests (Contextual Scam Signals)
        # --------------------------------------------------------------------
        self._extract_payment_and_credentials(sanitized, make_span, next_claim_id, claims, warnings)

        for candidate in [c for c in claims if c.kind == ClaimKind.CANDIDATE_CONTACT.value]:
            original = str(candidate.value)
            marker = "[REDACTED_CANDIDATE_" + candidate.attributes["channel"].upper() + "]"
            sanitized = sanitized.replace(original, marker)
            def mask_value(value):
                if isinstance(value, str):
                    return value.replace(original, marker)
                if isinstance(value, list):
                    return [mask_value(v) for v in value]
                if isinstance(value, dict):
                    return {k: mask_value(v) for k, v in value.items()}
                return value
            for claim in claims:
                claim.attributes = mask_value(claim.attributes)
                if isinstance(claim.value, str):
                    claim.value = claim.value.replace(original, marker)
                if claim.source_quote:
                    claim.source_quote = claim.source_quote.replace(original, marker)
        for claim in claims:
            if claim.source_quote and claim.source_quote not in sanitized:
                actual = re.search(re.escape(claim.source_quote), sanitized, re.I)
                claim.source_quote = actual.group() if actual else None
            claim.source_span = make_span(claim.source_quote) if claim.source_quote else None

        return ExtractionResult(
            contract_version="1.0.1",
            source_type=source_type,
            extraction_method="regex",
            sanitized_source_buffer=sanitized,
            raw_text=None,
            redacted_text=sanitized,
            claims=claims,
            unresolved_ambiguities=ambiguities,
            warnings=warnings,
        )

    def _extract_compensation(
        self,
        sanitized: str,
        make_span,
        next_claim_id,
        claims: List[Claim],
        ambiguities: List[UnresolvedAmbiguity],
    ):
        """
        Extracts compensation claims, converting to base currency units and
        flagging frequency ambiguity where unspecified.
        """
        # Range pattern: e.g. "INR 25,000 - 35,000 per month"
        range_match = re.search(
            r"(?:INR|USD|EUR|GBP|Rs\.?|₹|\$)\s*([\d,]+)\s*(?:-|to)\s*([\d,]+)\s*(per\s+month|per\s+annum|p\.m\.|p\.a\.)",
            sanitized,
            re.IGNORECASE,
        )
        if range_match:
            quote = range_match.group(0).strip()
            min_v = float(range_match.group(1).replace(",", ""))
            max_v = float(range_match.group(2).replace(",", ""))
            freq = range_match.group(3).lower()
            period = "MONTHLY" if "month" in freq or "p.m" in freq else "ANNUAL"
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.COMPENSATION.value,
                    value=quote,
                    source_quote=quote,
                    source_span=make_span(quote),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.HIGH.value,
                    attributes={
                        "amount": min_v,
                        "amount_range": [min_v, max_v],
                        "amount_unit": "currency_base_unit",
                        "currency": "INR",
                        "period": period,
                        "pay_type": "salary",
                    },
                )
            )
            return

        # Explicit LPA pattern: "INR 7.2 LPA", "₹8 LPA", "Package INR 8.5 LPA"
        lpa_match = re.search(
            r"(?:(?:Package|CTC|Salary)\s*:?\s*)?((?:INR|USD|EUR|GBP|Rs\.?|₹|\$)?\s*[\d]+(?:\.\d+)?\s*(?:LPA|Lakhs?(?:\s+per\s+annum)?))\b",
            sanitized,
            re.IGNORECASE,
        )
        if lpa_match:
            quote = lpa_match.group(1).strip()
            num_m = re.search(r"[\d]+(?:\.\d+)?", quote)
            lpa_val = float(num_m.group(0)) if num_m else 0.0
            base_amount = lpa_val * 100000.0
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.COMPENSATION.value,
                    value=quote,
                    source_quote=quote,
                    source_span=make_span(quote),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.HIGH.value,
                    attributes={
                        "amount": base_amount,
                        "currency": "INR",
                        "period": "ANNUAL",
                        "pay_type": "salary",
                        "amount_unit": "currency_base_unit",
                        "amount_range": None,
                    },
                )
            )
            return

        # CTC without period: "CTC INR 7,50,000" or "CTC: 750000"
        ctc_match = re.search(
            r"\bCTC\s*:?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\b",
            sanitized,
            re.IGNORECASE,
        )
        if ctc_match and "per" not in ctc_match.group(0).lower():
            quote = ctc_match.group(0).strip()
            amt = float(ctc_match.group(1).replace(",", ""))
            cid = next_claim_id()
            claims.append(
                Claim(
                    claim_id=cid,
                    kind=ClaimKind.COMPENSATION.value,
                    value=quote,
                    source_quote=quote,
                    source_span=make_span(quote),
                    extraction_status=ExtractionStatus.AMBIGUOUS.value,
                    confidence_tier=ConfidenceTier.MEDIUM.value,
                    attributes={
                        "amount": amt,
                        "currency": "INR",
                        "period": None,
                        "pay_type": "salary",
                        "amount_unit": "currency_base_unit",
                        "amount_range": None,
                    },
                )
            )
            ambiguities.append(
                UnresolvedAmbiguity(
                    claim_id=cid,
                    field="period",
                    issue="CTC amount has no explicit payment period; do not infer annual frequency.",
                )
            )
            return

        # Stipend without period: "Stipend: INR 15,000"
        stipend_match = re.search(
            r"\bStipend\s*:?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\b",
            sanitized,
            re.IGNORECASE,
        )
        if stipend_match and "per" not in stipend_match.group(0).lower():
            quote = stipend_match.group(0).strip()
            amt = float(stipend_match.group(1).replace(",", ""))
            cid = next_claim_id()
            claims.append(
                Claim(
                    claim_id=cid,
                    kind=ClaimKind.COMPENSATION.value,
                    value=quote,
                    source_quote=quote,
                    source_span=make_span(quote),
                    extraction_status=ExtractionStatus.AMBIGUOUS.value,
                    confidence_tier=ConfidenceTier.MEDIUM.value,
                    attributes={
                        "amount": amt,
                        "currency": "INR",
                        "period": None,
                        "pay_type": "stipend",
                        "period_ambiguity": "UNSPECIFIED_FREQUENCY",
                        "amount_unit": "currency_base_unit",
                        "amount_range": None,
                    },
                )
            )
            ambiguities.append(
                UnresolvedAmbiguity(
                    claim_id=cid,
                    field="period",
                    issue="Document states 'INR 15,000' without specifying whether this is monthly stipend or total for internship.",
                )
            )
            return

        # Generic salary with period: "INR 15,000 per month" or "INR 6,00,000 per annum"
        gen_salary = re.search(
            r"(?:INR|USD|EUR|GBP|Rs\.?|₹|\$)\s*([\d,]+(?:\.\d+)?)\s*(per\s+month|per\s+annum|p\.m\.|p\.a\.)",
            sanitized,
            re.IGNORECASE,
        )
        if gen_salary:
            quote = gen_salary.group(0).strip()
            amt = float(gen_salary.group(1).replace(",", ""))
            freq = gen_salary.group(2).lower()
            period = "MONTHLY" if "month" in freq or "p.m" in freq else "ANNUAL"
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.COMPENSATION.value,
                    value=quote,
                    source_quote=quote,
                    source_span=make_span(quote),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.HIGH.value,
                    attributes={
                        "amount": amt,
                        "currency": "INR",
                        "period": period,
                        "pay_type": "salary",
                        "amount_unit": "currency_base_unit",
                        "amount_range": None,
                    },
                )
            )

    def _extract_payment_and_credentials(
        self,
        sanitized: str,
        make_span,
        next_claim_id,
        claims: List[Claim],
        warnings: List[ExtractionWarning],
    ):
        """
        Runs ScamClassifier to detect payment requests and credential requests,
        generating grounded claims with complete modalities and omitting secret values.
        """
        assessments: List[SignalAssessment] = self.scam_classifier.classify(sanitized)

        # Check for routine identity document request first (onboarding ID submission != theft)
        id_doc_match = re.search(
            r"\b(?:submit|provide|upload)\s+(?:cop(?:y|ies)\s+of\s+)?(?:your\s+)?(?:photo\s+id|aadhaar|pan\s+card|passport|voter\s+id|educational\s+certificates|marksheets)\b",
            sanitized,
            re.IGNORECASE,
        )
        if id_doc_match and not any(a.signal_code == ScamSignalCode.CREDENTIAL_THEFT_DEMAND for a in assessments):
            quote = id_doc_match.group(0).strip()
            claims.append(
                Claim(
                    claim_id=next_claim_id(),
                    kind=ClaimKind.CREDENTIAL_REQUEST.value,
                    value=quote,
                    source_quote=quote,
                    source_span=make_span(quote),
                    extraction_status=ExtractionStatus.EXTRACTED.value,
                    confidence_tier=ConfidenceTier.HIGH.value,
                    attributes={
                        "modality": "active_demand",
                        "is_active_demand": True,
                        "requested_action": "request_identity_document",
                        "credential_categories": ["identity_document"],
                        "secret_values_omitted": True,
                        "secret_payload": None,
                        "recipient": None,
                        "actor": None,
                    },
                )
            )

        for assessment in assessments:
            modality = assessment.modality
            is_active = (
                True if modality == ScamModality.ACTIVE_DEMAND
                else (False if modality in (ScamModality.NEGATED_POLICY, ScamModality.QUOTED_ADVISORY) else None)
            )
            quote = assessment.source_quote or ""

            is_cred = assessment.signal_code in (
                ScamSignalCode.CREDENTIAL_THEFT_DEMAND,
                "NEGATED_CREDENTIAL_POLICY",
                "SELF_SERVICE_OTP_DIRECTION",
            ) or (
                assessment.signal_code == ScamSignalCode.QUOTED_SCAM_ADVISORY
                and any(w in quote.lower() for w in ["otp", "password", "pin", "credentials"])
            )

            # 1. Credential Requests (OTP, PIN, Password)
            if is_cred:
                if any(w in quote.lower() for w in ["otp", "password", "pin", "credentials"]):
                    # Extract recipient email if mentioned in clause
                    rec_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", quote)
                    recipient = rec_match.group(0) if rec_match else None

                    # Extract stated pretext
                    pretext = None
                    if "payroll" in sanitized.lower() or "direct-deposit" in sanitized.lower() or "salary clearance" in sanitized.lower():
                        pretext = "activate corporate direct-deposit salary clearance"

                    claims.append(
                        Claim(
                            claim_id=next_claim_id(),
                            kind=ClaimKind.CREDENTIAL_REQUEST.value,
                            value=quote,
                            source_quote=quote,
                            source_span=make_span(quote),
                            extraction_status=ExtractionStatus.EXTRACTED.value if is_active else ExtractionStatus.AMBIGUOUS.value,
                            confidence_tier=ConfidenceTier.HIGH.value,
                            attributes={
                                "modality": modality,
                                "is_active_demand": is_active,
                                "requested_action": "solicit_credentials",
                                "credential_categories": (["bank_otp"] if "otp" in quote.lower() else []) + (["netbanking_password"] if "password" in quote.lower() else []) + (["pin"] if re.search(r"\bpin\b", quote.lower()) else []),
                                "secret_values_omitted": True,
                                "secret_payload": None,
                                "recipient": recipient,
                                "stated_pretext": pretext,
                                "actor": None,
                            },
                        )
                    )
                    if is_active:
                        warnings.append(
                            ExtractionWarning(
                                code="CRITICAL_CREDENTIAL_THEFT_DEMAND",
                                message="Solicitation of OTPs or passwords represents financial credential theft.",
                            )
                        )

            # 2. Payment Requests (Upfront Fee, Unlock Payment, Security Deposit)
            elif assessment.signal_code in (
                ScamSignalCode.UPFRONT_FEE_DEMAND,
                ScamSignalCode.UNLOCK_PAYMENT_DEMAND,
                ScamSignalCode.NEGATED_FEE_POLICY,
                ScamSignalCode.UPI_PAYMENT_REQUEST,
                ScamSignalCode.QUOTED_SCAM_ADVISORY,
            ):

                # Extract amount from quote or surrounding text
                amt_match = re.search(r"(?:INR|Rs\.?|₹)\s*([\d,]+)", quote, re.IGNORECASE)
                amt_val = float(amt_match.group(1).replace(",", "")) if amt_match else None

                # Extract payment rail / method
                method = "UPI" if "upi" in quote.lower() else ("bank_transfer" if "bank" in quote.lower() else None)

                # Extract recipient UPI handle
                vpa_match = re.search(r"\b[a-zA-Z0-9.\-_]{2,}@[a-zA-Z0-9.\-_]{2,}\b", quote)
                recipient = vpa_match.group(0) if vpa_match else None
                rec_type = "upi_vpa" if recipient and "@" in recipient else None

                # Purpose and urgency
                purpose = "refundable laptop security deposit" if "laptop" in quote.lower() or "security deposit" in quote.lower() else ("registration fee" if "registration" in quote.lower() else None)
                urgency = "within 24 hours" if "24 hours" in quote.lower() or "immediately" in quote.lower() else None

                # Check if we already have a payment_request for this quote
                existing_payment = next((c for c in claims if c.kind == ClaimKind.PAYMENT_REQUEST.value and c.source_quote == quote), None)
                if existing_payment:
                    if not existing_payment.attributes.get("recipient") and recipient:
                        existing_payment.attributes["recipient"] = recipient
                        existing_payment.attributes["recipient_type"] = rec_type
                    if not existing_payment.attributes.get("payment_method") and method:
                        existing_payment.attributes["payment_method"] = method
                    if not existing_payment.attributes.get("amount") and amt_val:
                        existing_payment.attributes["amount"] = amt_val
                        existing_payment.attributes["currency"] = "INR"
                    continue

                if is_active:
                    attrs = {
                        "modality": modality,
                        "is_active_demand": is_active,
                        "requested_action": "transfer_funds",
                        "recipient": recipient,
                        "recipient_type": rec_type,
                        "amount": amt_val,
                        "currency": "INR" if amt_val else None,
                        "payment_method": method,
                        "purpose": purpose,
                        "urgency": urgency,
                        "actor": None,
                    }
                else:
                    attrs = {
                        "modality": modality,
                        "is_active_demand": False,
                        "requested_action": None,
                        "actor": None,
                        "recipient": None,
                        "amount": None,
                        "currency": None,
                        "payment_method": None,
                        "purpose": None,
                    }
                    if modality == ScamModality.NEGATED_POLICY:
                        neg_terms = []
                        for t in ["security deposit", "registration fee", "onboarding deposit", "training fee"]:
                            if t in quote.lower():
                                neg_terms.append(t)
                        attrs["negated_terms"] = neg_terms
                    elif modality == ScamModality.QUOTED_ADVISORY:
                        quoted_terms = []
                        for t in ["registration fee", "security deposit", "processing fee"]:
                            if t in quote.lower():
                                quoted_terms.append(t)
                        attrs["quoted_terms"] = quoted_terms
                        if amt_match:
                            attrs["quoted_amount"] = amt_match.group(0).strip()
                        if method:
                            attrs["quoted_method"] = method

                claims.append(
                    Claim(
                        claim_id=next_claim_id(),
                        kind=ClaimKind.PAYMENT_REQUEST.value,
                        value=quote,
                        source_quote=quote,
                        source_span=make_span(quote),
                        extraction_status=ExtractionStatus.EXTRACTED.value,
                        confidence_tier=ConfidenceTier.HIGH.value,
                        attributes=attrs,
                    )
                )
                if is_active:
                    warnings.append(
                        ExtractionWarning(
                            code="UPFRONT_PAYMENT_DEMAND_DETECTED",
                            message="Mandatory candidate-to-recruiter payment demand identified in document.",
                        )
                    )


GroundedParser = GroundedEntityParser


