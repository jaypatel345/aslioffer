import re
from typing import Optional, List, Dict, Any, Tuple
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchResult, SearchOutcome
from app.services.search.domain_resolver import DomainResolutionResult, DomainResolver, DomainResolutionState, resolve_employer_domain
from app.core.logging import logger

FREE_EMAIL_DOMAINS = {
    "gmail.com", "outlook.com", "yahoo.com", "hotmail.com",
    "rediffmail.com", "protonmail.com", "live.com", "icloud.com",
    "zoho.com", "yandex.com", "gmx.com", "mail.com",
}

GENERIC_TITLES = {
    "hr", "recruiter", "talent acquisition", "onboarding coordinator",
    "hiring manager", "admin", "recruitment team", "coordinator",
    "team hr", "talent team", "hr team", "hiring team", "hr manager",
    "people operations", "talent lead", "talent specialist",
}

ADVERSE_KEYWORDS = {
    "scam", "fraud", "complaint", "fake", "cheated", "victim", "reported",
    "cybercrime", "extortion", "phishing", "scammer", "impersonat", "illegal",
    "unauthorized", "beware", "warning", "police", "fir", "ncrp", "cyberdost",
}

BENIGN_OFFICIAL_KEYWORDS = {
    "official customer care", "customer care", "customer support", "helpline",
    "toll free", "toll-free", "contact us", "registered office", "head office",
    "corporate office", "switchboard", "official directory", "directory",
}

RECRUITMENT_ROLE_KEYWORDS = {
    "recruiter", "recruitment", "talent acquisition", "hr", "human resources",
    "people team", "hiring", "talent", "staffing", "onboarding", "specialist",
    "partner", "lead", "manager", "head of talent", "head of hr",
}


from enum import Enum

class AssessmentStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNCONFIRMED = "UNCONFIRMED"
    NO_MATCH = "NO_MATCH"
    CONFLICTING = "CONFLICTING"
    CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"
    NOT_CHECKED = "NOT_CHECKED"


class RecruiterAgent:
    """
    Investigates recruiter identity, email domain alignment, agency footprint,
    and adverse contact reports against public search data.
    Uses DomainResolver for evidence-backed domain resolution.
    Never equates domain alignment, agency existence, or absence of complaints
    with authentication of the individual or offer.
    """

    def __init__(
        self,
        search_client: Optional[SerpApiClient] = None,
        *,
        domain_resolver: Optional[Any] = None,
        serpapi_client: Optional[SerpApiClient] = None,
    ):
        self.search_client = search_client or serpapi_client or SerpApiClient()
        self.domain_resolver = domain_resolver

    @staticmethod
    def _validate_email(email: Optional[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validates email format and domain using DomainResolver.
        Returns (is_valid, local_part, domain).
        Rejects malformed emails as unusable input, not proof of fraud.
        """
        if not email or not isinstance(email, str):
            return False, None, None
        email = email.strip()
        if "@" not in email or email.count("@") != 1:
            return False, None, None
        local, domain = email.split("@")
        domain = domain.strip().lower()
        if not local or not domain or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+", local) or local.startswith(".") or local.endswith(".") or ".." in local:
            return False, None, None
        if any(c in domain for c in "/:@?#\\ "):
            return False, None, None
        parsed = DomainResolver.normalize_and_parse_url("https://" + domain)
        if not parsed.is_valid or not parsed.registrable_domain:
            return False, None, None
        return True, local, parsed.hostname

    @staticmethod
    def _normalize_phone(phone: Optional[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validates and extracts digits from phone string.
        Returns (is_valid, canonical_digits, raw_input).
        Does not treat invalid phone format as fraud evidence.
        """
        if not phone or not isinstance(phone, str):
            return False, None, None
        if not re.fullmatch(r"\+?[0-9().\s-]+", phone.strip()):
            return False, None, phone.strip()
        digits = re.sub(r"\D", "", phone)
        # Bounded between 7 and 15 digits (ITU-T E.164 recommendation)
        if len(digits) < 7 or len(digits) > 15:
            return False, None, phone.strip()
        return True, digits, phone.strip()

    @staticmethod
    def _find_exact_phone_match(phone_digits: str, text: str) -> bool:
        """
        Token/boundary-aware search for exact phone number in text.
        Avoids unsafe substring matching or joining digits across unrelated text fragments.
        """
        if not text or not phone_digits:
            return False
        # Full numeric tokens only; country codes must not be guessed.
        for match in re.finditer(r"(?<![\w+])\+?\d(?:[\d ().-]*\d)?(?!\w)", text):
            if re.sub(r"\D", "", match.group()) == phone_digits:
                return True
        return False

    @staticmethod
    def _email_match(email: Optional[str], text: str) -> bool:
        return bool(email and re.search(
            r"(?<![\w.+-])" + re.escape(email.strip()) + r"(?![\w@+-]|\.[\w-])",
            text, re.IGNORECASE,
        ))

    @staticmethod
    def _role_match(text: str) -> bool:
        return bool(re.search(r"\b(?:recruiter|recruitment|talent acquisition|hr|human resources|staffing|hiring)\b", text, re.I))


    @classmethod
    def _evaluate_contact_adverse_context(cls, title: str, snippet: str) -> Tuple[bool, str]:
        """
        Contextual analysis distinguishing official contact listings and generic advice
        from specific adverse fraud reports alleging misuse of this exact contact.
        """
        combined = f"{title} {snippet}".lower()

        has_benign = any(kw in combined for kw in BENIGN_OFFICIAL_KEYWORDS)
        has_adverse = bool(re.search(r"\b(?:scam|fraud|fraudulent|scammer|scammed|cheated|phishing|extortion|impersonator)\b", combined))

        # Specific misuse allegation indicators:
        misuse_indicators = [
            "caller claimed", "received call from", "received call", "fake hr", "scammed by",
            "cheated by", "demanded fee", "asking for fee", "fraudulent call", "fake offer from",
            "fake recruiter", "impersonator", "money demanded", "stolen", "loss of",
            "scam number", "scammer using", "reported as scam", "complaint against",
        ]
        has_specific_misuse = any(ind in combined for ind in misuse_indicators)

        # Check for generic advisory / official reporting / contact verification context
        helpline_patterns = [
            r"report.*to.*helpline",
            r"call.*helpline",
            r"fraud.*reporting.*number",
            r"cyber.*helpline",
            r"contact.*to.*verify",
            r"verify.*with",
            r"verify.*immediately",
            r"beware.*fake",
            # The contact is where fraud is reported to: "report suspected fraud: hr@x.com"
            # (present tense only: "reported fraud from <number>" is a complaint, not a notice)
            r"\breport(?:ing)?\s+(?:any\s+|all\s+|such\s+|suspected\s+|suspicious\s+)*(?:fraud|scam|incident|activity)s?(?:\s+to|\s+at|\s+on|\s*:|\s+-)\s*(?:[\w.+-]+@|\+?\d)",
            # Employer fraud-prevention notices
            r"\b(?:fraud|scam)\s+(?:alert|awareness|advisory|notice)\b",
            r"\bresponsible\s+recruitment\b",
            r"\bofficial\s+hiring\s+notice\b",
        ]
        is_advisory_or_official = (
            has_benign
            or any(re.search(p, combined) for p in helpline_patterns)
            or any(ind in combined for ind in ["customer care", "customer support", "helpline", "toll free", "toll-free", "contact us"])
        )

        if is_advisory_or_official and not has_specific_misuse:
            return False, "Incidental mention in official contact listing or fraud-prevention advisory."

        if has_specific_misuse and has_adverse and not re.search(r"\b(?:no|not|never|without|prevent|prevention|avoid|protect)\b", combined):
            return True, "Public report alleges fraudulent activity or impersonation associated with this contact."

        if has_adverse and not re.search(r"\b(?:no|not|never|without|prevent|prevention|avoid|protect)\b", combined):
            return True, "Public report alleges fraudulent activity associated with this contact."

        return False, "Contact mentioned without specific adverse allegations."

    @classmethod
    def _evaluate_affiliation_evidence(
        cls,
        search_res: SearchResult,
        recruiter_name: Optional[str],
        recruiter_email: Optional[str],
        company_name: str,
        canonical_domain: Optional[str],
    ) -> Tuple[str, Optional[str], List[EvidenceItem], Optional[str]]:
        """
        Evaluates affiliation evidence strength:
        - Employer-published exact contact/team info (strongest)
        - Corroborated public professional profile (supporting, but does not authenticate offer)
        - Unconfirmed / generic / no match
        Returns (status, explanation, evidence_items, evidence_strength).
        """
        evidence_items: List[EvidenceItem] = []
        if not search_res or not search_res.is_live:
            return "CHECK_UNAVAILABLE", "Search results unavailable or synthetic.", evidence_items, None

        results = search_res.organic_results or []
        company_lower = company_name.lower().strip()
        rec_name_lower = recruiter_name.lower().strip() if recruiter_name else None

        is_generic_name = rec_name_lower in GENERIC_TITLES if rec_name_lower else False

        # 1. Employer-published contact or team information
        if canonical_domain:
            for r in results:
                link = r.get("link", "")
                parsed_link = DomainResolver.normalize_and_parse_url(link)
                if parsed_link.is_valid and parsed_link.registrable_domain:
                    if DomainResolver.is_matching_domain(parsed_link.hostname, canonical_domain):
                        text = f"{r.get('title', '')} {r.get('snippet', '')}".lower()
                        name_hit = bool(rec_name_lower and not is_generic_name and rec_name_lower in text)
                        email_hit = cls._email_match(recruiter_email, text)
                        if email_hit or (not recruiter_email and name_hit):
                            # The recruiting context may be the page itself: the employer's own
                            # recruitment section (e.g. acnrecruitment.accenture.com).
                            in_hiring_section = "recruit" in link.lower()
                            role_hit = (cls._role_match(text) or in_hiring_section) and not re.search(r"\b(?:former|retired|no longer|not a recruiter)\b", text)
                            if role_hit:
                                ev = EvidenceItem(
                                    source_url=link,
                                    title=r.get("title") or f"{company_name} Official Recruiter Directory",
                                    description=r.get("snippet") or f"Employer-published listing on {canonical_domain} corroborates affiliation.",
                                    evidence_type="RECRUITER",
                                    confidence=0.92,
                                )
                                evidence_items.append(ev)
                                return (
                                    "SUPPORTED",
                                    f"Employer-published directory on '{canonical_domain}' corroborates recruiter affiliation.",
                                    evidence_items,
                                    "strong_employer_published",
                                )

        # 2. Public professional profiles (e.g. LinkedIn, professional directory)
        if rec_name_lower and not is_generic_name:
            for r in results:
                link = r.get("link", "")
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                text = f"{title} {snippet}".lower()

                parsed_profile = DomainResolver.normalize_and_parse_url(link)
                if parsed_profile.is_valid and parsed_profile.registrable_domain in {"linkedin.com", "xing.com", "crunchbase.com"}:
                    if re.search(r"\b" + re.escape(rec_name_lower) + r"\b", text):
                        if company_lower in text or (canonical_domain and canonical_domain in text):
                            if cls._role_match(text):
                                ev = EvidenceItem(
                                    source_url=link,
                                    title=title or f"Public Professional Profile: {recruiter_name}",
                                    description=snippet or f"Public professional profile associates {recruiter_name} with {company_name}.",
                                    evidence_type="RECRUITER",
                                    confidence=0.75,
                                )
                                evidence_items.append(ev)
                                return (
                                    "SUPPORTED",
                                    f"Public professional profile supports claimed affiliation with '{company_name}'; self-described profiles cannot independently authenticate an offer.",
                                    evidence_items,
                                    "corroborated_profile",
                                )

        return "UNCONFIRMED", "No employer-published or corroborated public profile evidence found linking recruiter to employer.", evidence_items, None

    @classmethod
    def _evaluate_agency_authorization(
        cls,
        company_search_res: SearchResult,
        agency_name: str,
        agency_domain: Optional[str],
        company_name: str,
        employer_domain: Optional[str] = None,
    ) -> Tuple[str, str, List[EvidenceItem], Optional[str]]:
        """
        Distinguishes agency public footprint from employer authorization to recruit.
        Employer-published partner info can support authorization; generic partnership
        evidence or agency self-claims remain UNCONFIRMED.
        Returns (status, explanation, evidence_items, evidence_strength).
        """
        evidence_items: List[EvidenceItem] = []
        if not company_search_res or not company_search_res.is_live:
            return "CHECK_UNAVAILABLE", "Employer search results unavailable to verify agency authorization mandate.", evidence_items, None

        agency_name_clean = agency_name.lower().strip()
        results = company_search_res.organic_results or []
        for r in results:
            parsed = DomainResolver.normalize_and_parse_url(r.get("link", ""))
            if not employer_domain or not parsed.is_valid or not DomainResolver.is_matching_domain(parsed.hostname, employer_domain):
                continue
            text = f"{r.get('title', '')} {r.get('snippet', '')}".lower()
            if agency_name_clean in text or (agency_domain and agency_domain.lower() in text):
                if cls._role_match(text.replace(agency_name_clean, "")) and re.search(r"\b(?:partner|authorized|work|empaneled|vendor)\b", text) and not re.search(r"\b(?:not|no|unauthorized|never|former|terminated)\b", text):
                    ev = EvidenceItem(
                        source_url=r.get("link", ""),
                        title=r.get("title") or f"{company_name} Authorized Partner Listing",
                        description=r.get("snippet") or f"Employer search evidence lists {agency_name} as a staffing partner.",
                        evidence_type="RECRUITER",
                        confidence=0.88,
                    )
                    evidence_items.append(ev)
                    return (
                        "SUPPORTED",
                        f"Employer records list '{agency_name}' as a recruitment partner.",
                        evidence_items,
                        "employer_published_partner",
                    )

        return "UNCONFIRMED", f"Recruiter operates under third-party staffing agency '{agency_name}'. Agency footprint verified, but client representation mandate requires confirmation.", evidence_items, None

    async def investigate(
        self,
        company_name: str,
        recruiter_name: Optional[str] = None,
        recruiter_email: Optional[str] = None,
        recruiter_phone: Optional[str] = None,
        *,
        agency_name: Optional[str] = None,
    ) -> AgentFinding:
        logger.info("RecruiterAgent investigation started")
        evidence_list: List[EvidenceItem] = []
        checks: Dict[str, Any] = {}

        # Validate inputs
        is_valid_email, email_local, email_domain = self._validate_email(recruiter_email)
        is_valid_phone, phone_digits, raw_phone = self._normalize_phone(recruiter_phone)
        has_usable_contact = is_valid_email or is_valid_phone

        is_free_email = email_domain in FREE_EMAIL_DOMAINS if (is_valid_email and email_domain) else False
        domain_match: Optional[bool] = None
        phone_flagged = False
        email_flagged = False

        resolved_employer_domain: Optional[str] = None
        company_search_res: Optional[SearchResult] = None

        # Agency state
        is_agency = False
        agency_domain: Optional[str] = None
        agency_domain_match: Optional[bool] = None

        # 6 Assessment dimensions
        employer_domain_status = "NOT_CHECKED"
        employer_domain_expl = "Employer domain was not checked."
        employer_domain_urls: List[str] = []
        employer_domain_facts: Dict[str, Any] = {}

        recruiter_email_status = "NOT_CHECKED"
        recruiter_email_expl = "Recruiter email domain was not evaluated."
        recruiter_email_urls: List[str] = []
        recruiter_email_facts: Dict[str, Any] = {"input_email_provided": bool(recruiter_email), "is_valid": is_valid_email}

        recruiter_affiliation_status = "NOT_CHECKED"
        recruiter_affiliation_expl = "Recruiter affiliation was not evaluated."
        recruiter_affiliation_urls: List[str] = []
        recruiter_affiliation_facts: Dict[str, Any] = {"recruiter_name": recruiter_name}

        agency_identity_status = "NOT_CHECKED"
        agency_identity_expl = "No recruitment agency specified."
        agency_identity_urls: List[str] = []
        agency_identity_facts: Dict[str, Any] = {"agency_name": agency_name}

        agency_authorization_status = "NOT_CHECKED"
        agency_authorization_expl = "No agency authorization check performed."
        agency_authorization_urls: List[str] = []
        agency_authorization_facts: Dict[str, Any] = {}
        agency_authorization_strength: Optional[str] = None

        recruiter_affiliation_strength: Optional[str] = None

        adverse_reports_status = "NOT_CHECKED"
        adverse_reports_expl = "No adverse contact reports evaluated."
        adverse_reports_urls: List[str] = []
        adverse_reports_facts: Dict[str, Any] = {}

        def record(name: str, result: SearchResult):
            checks[name] = {
                "provider_status": "SUCCESS" if result.is_live else "FAILED",
                "search_status": result.outcome.value if result.is_live or result.get("source") == "FAILED" else "DEMO",
                "search_source": result.get("source"),
                "error": result.error if result.is_live or result.get("source") == "FAILED" else "Synthetic results cannot verify an offer",
            }

        # 1. Employer Domain Resolution
        if is_valid_email and email_domain:
            recruiter_email_facts["email_domain"] = email_domain
            if is_free_email:
                recruiter_email_status = "CONFLICTING"
                recruiter_email_expl = f"Recruiter contact uses public webmail domain '@{email_domain}'."
                recruiter_email_facts["is_free_webmail"] = True
                evidence_list.append(EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Free Webmail Domain Used for Corporate Recruitment",
                    description="The submitted recruiter contact uses a public webmail domain; employer affiliation requires confirmation.",
                    evidence_type="RECRUITER",
                    confidence=0.85,
                ))

            # Same shared resolution as CompanyAgent; the run's search cache makes the repeat free.
            # With no employer name there is nothing to resolve (and nothing to search for).
            if (company_name or "").strip():
                company_search_res, resolution, _ = await resolve_employer_domain(self.search_client, company_name)
                record("company_domain", company_search_res)
            else:
                company_search_res = None
                resolution = DomainResolutionResult(state=DomainResolutionState.UNRESOLVED,
                                                    basis="No employer name was given to resolve.")
            checks.setdefault("company_domain", {"provider_status": "NOT_CHECKED", "search_status": "NOT_CHECKED"}).update({
                "resolution_state": resolution.state.value,
                "resolution_basis": resolution.basis,
                "resolution_diagnostics": resolution.diagnostics,
                "canonical_domain": resolution.canonical_domain,
                "rejected_candidates": resolution.rejected_candidates,
            })
            employer_domain_facts = {
                "resolution_state": resolution.state.value,
                "canonical_domain": resolution.canonical_domain,
                "basis": resolution.basis,
            }
            if company_search_res is None:
                employer_domain_status = "UNCONFIRMED"
                employer_domain_expl = "No employer name was given, so no employer domain could be checked."
                domain_match = None
            elif company_search_res.is_live:
                if resolution.state == DomainResolutionState.RESOLVED and resolution.canonical_domain:
                    parsed_emp = DomainResolver.normalize_and_parse_url("https://" + resolution.canonical_domain)
                    resolved_employer_domain = parsed_emp.registrable_domain or resolution.canonical_domain
                    employer_domain_status = "SUPPORTED"
                    employer_domain_expl = f"Employer official domain resolved to '{resolution.canonical_domain}' via {resolution.basis}."
                    if resolution.canonical_url:
                        employer_domain_urls.append(resolution.canonical_url)

                    domain_match = DomainResolver.is_matching_domain(email_domain, resolution.canonical_domain)
                    if domain_match:
                        if not is_free_email:
                            recruiter_email_status = "SUPPORTED"
                            recruiter_email_expl = f"Submitted recruiter email domain '@{email_domain}' matches resolved company domain '{resolution.canonical_domain}'."
                            evidence_list.append(EvidenceItem(
                                source_url=resolution.canonical_url or f"https://{resolution.canonical_domain}",
                                title="Corporate Email Domain Matched",
                                description="Submitted recruiter email domain matches the official company domain found in search.",
                                evidence_type="RECRUITER",
                                confidence=0.88,
                            ))
                    else:
                        recruiter_email_status = "CONFLICTING"
                        recruiter_email_facts["is_mismatch"] = True
                        if not is_free_email:
                            recruiter_email_expl = f"Submitted recruiter email domain '@{email_domain}' differs from resolved company domain '{resolution.canonical_domain}'."
                            evidence_list.append(EvidenceItem(
                                source_url=resolution.canonical_url or f"https://{resolution.canonical_domain}",
                                title="Recruiter Email Domain Does Not Match Official Company Domain",
                                description=f"Submitted recruiter email domain '@{email_domain}' differs from the resolved company domain '{resolution.canonical_domain}'.",
                                evidence_type="RECRUITER",
                                confidence=0.90,
                            ))
                elif resolution.state == DomainResolutionState.AMBIGUOUS:
                    employer_domain_status = "CONFLICTING"
                    employer_domain_expl = f"Employer domain is ambiguous among: {', '.join(resolution.diagnostics.get('competing_domains', []))}."
                    domain_match = None
                else:
                    employer_domain_status = "UNCONFIRMED"
                    employer_domain_expl = "Employer domain could not be corroborated from search results."
                    domain_match = None
            else:
                employer_domain_status = "CHECK_UNAVAILABLE"
                employer_domain_expl = "Employer domain check unavailable due to provider failure or synthetic source."
                domain_match = None
        elif recruiter_email and not is_valid_email:
            recruiter_email_status = "NO_MATCH"
            recruiter_email_facts["is_invalid"] = True
            recruiter_email_expl = "Malformed or unusable email address supplied; rejected as unusable input, not fraud."
            domain_match = None

        # A custom sender domain can identify an agency even before extraction
        # supports agency_name. Require a full identity card plus staffing context;
        # never manufacture an organization name from the hostname.
        agency_search_res = None
        if not agency_name and domain_match is False and not is_free_email:
            discovery_query = f'"{email_domain}" staffing recruitment agency'
            agency_search_res = SearchResult.from_dict_or_result(
                await self.search_client.search(discovery_query), query=discovery_query)
            record("agency_discovery", agency_search_res)
            card = agency_search_res.get("knowledge_graph") or {}
            candidate_name = card.get("title")
            if agency_search_res.is_live and isinstance(candidate_name, str) and candidate_name.strip():
                candidate_resolution = DomainResolver.resolve(candidate_name, agency_search_res)
                staffing_text = " ".join(str(r.get("title", "")) + " " + str(r.get("snippet", ""))
                                         for r in agency_search_res.organic_results or []
                                         if DomainResolver.is_matching_domain(
                                             DomainResolver.normalize_and_parse_url(r.get("link", "")).hostname or "", email_domain))
                if (candidate_resolution.state == DomainResolutionState.RESOLVED
                    and DomainResolver.is_matching_domain(email_domain, candidate_resolution.canonical_domain or "")
                    and self._role_match(staffing_text)):
                    agency_name = candidate_name.strip()
            if not agency_name:
                agency_identity_status = "UNCONFIRMED" if agency_search_res.is_live else "CHECK_UNAVAILABLE"
                agency_identity_expl = "Sender domain did not establish a corroborated staffing agency identity."

        # 2. Agency Investigation (explicit or independently discovered identity)
        if agency_name and isinstance(agency_name, str) and agency_name.strip():
            clean_agency = agency_name.strip()
            agency_query = f'"{clean_agency}" official website'
            if agency_search_res is None:
                agency_search_res = SearchResult.from_dict_or_result(await self.search_client.search(agency_query), query=agency_query)
            record("agency_identity", agency_search_res)
            agency_res = DomainResolver.resolve(clean_agency, agency_search_res)
            checks["agency_identity"].update({
                "resolution_state": agency_res.state.value,
                "canonical_domain": agency_res.canonical_domain,
            })
            agency_identity_facts = {
                "agency_name": clean_agency,
                "resolution_state": agency_res.state.value,
                "canonical_domain": agency_res.canonical_domain,
            }
            if agency_search_res.is_live and agency_res.state == DomainResolutionState.RESOLVED and agency_res.canonical_domain:
                parsed_ag = DomainResolver.normalize_and_parse_url("https://" + agency_res.canonical_domain)
                agency_domain = parsed_ag.registrable_domain or agency_res.canonical_domain
                agency_identity_status = "SUPPORTED"
                agency_identity_expl = f"Staffing agency '{clean_agency}' web presence verified on '{agency_domain}'."
                if agency_res.canonical_url:
                    agency_identity_urls.append(agency_res.canonical_url)

                if is_valid_email and email_domain:
                    agency_domain_match = DomainResolver.is_matching_domain(email_domain, agency_domain)
                    if agency_domain_match:
                        is_agency = True
                        evidence_list.append(EvidenceItem(
                            source_url=agency_res.canonical_url or f"https://{agency_domain}",
                            title="Recruitment Agency Domain Matched",
                            description=f"Submitted recruiter email operates on verified staffing agency domain '{agency_domain}'.",
                            evidence_type="RECRUITER",
                            confidence=0.85,
                        ))

                # Check employer authorization for this agency
                if company_search_res:
                    auth_status, auth_expl, auth_ev, auth_strength = self._evaluate_agency_authorization(
                        company_search_res, clean_agency, agency_domain, company_name, resolved_employer_domain
                    )
                    agency_authorization_status = auth_status
                    agency_authorization_expl = auth_expl
                    agency_authorization_strength = auth_strength
                    agency_authorization_facts = {"agency_name": clean_agency, "employer": company_name}
                    for ev in auth_ev:
                        evidence_list.append(ev)
                        agency_authorization_urls.append(ev.source_url)
                else:
                    agency_authorization_status = "UNCONFIRMED"
                    agency_authorization_expl = f"Agency footprint verified on '{agency_domain}', but client representation mandate requires secondary confirmation."
                    agency_authorization_strength = None
            else:
                agency_identity_status = "UNCONFIRMED" if agency_search_res.is_live else "CHECK_UNAVAILABLE"
                agency_identity_expl = f"Staffing agency '{clean_agency}' public footprint could not be verified."
                agency_authorization_status = "UNCONFIRMED"
                agency_authorization_expl = "Agency authorization unconfirmed because agency footprint is unverified."

        # 3. Adverse Contact Reports (Phone & Email)
        if is_valid_phone and phone_digits:
            phone_query = f'"{raw_phone}" scam fraud complaint'
            phone_search = SearchResult.from_dict_or_result(await self.search_client.search(phone_query), query=phone_query)
            record("phone_reports", phone_search)
            if phone_search.is_live:
                for r in phone_search.organic_results or []:
                    title = r.get("title", "")
                    snippet = r.get("snippet", "")
                    # Match title and snippet independently without cross-concatenation
                    if self._find_exact_phone_match(phone_digits, title) or self._find_exact_phone_match(phone_digits, snippet):
                        matched_parts = [part for field in (title, snippet)
                                         for part in re.split(r"(?<=[.!?])\s+|[;\n]", field)
                                         if self._find_exact_phone_match(phone_digits, part)]
                        is_adv, expl = self._evaluate_contact_adverse_context("", " ".join(matched_parts))
                        if is_adv:
                            phone_flagged = True
                            adverse_reports_status = "SUPPORTED"
                            adverse_reports_expl = "Public complaints allege fraudulent activity associated with the submitted phone number."
                            link = r.get("link", "https://cybercrime.gov.in")
                            adverse_reports_urls.append(link)
                            evidence_list.append(EvidenceItem(
                                source_url=link,
                                title=title or "Adverse Public Report for Phone Number",
                                description=snippet or "Public report alleges fraudulent activity for this phone contact.",
                                evidence_type="RECRUITER",
                                confidence=0.90,
                            ))
                            break
            checks["phone_reports"]["phone_flagged"] = phone_flagged
            checks["phone_reports"]["identity_verified"] = False
            adverse_reports_facts["phone_flagged"] = phone_flagged

        if is_valid_email and email_domain and not phone_flagged:
            email_adv_query = f'"{recruiter_email}" scam fraud complaint'
            email_search = SearchResult.from_dict_or_result(await self.search_client.search(email_adv_query), query=email_adv_query)
            record("email_reports", email_search)
            if email_search.is_live:
                for r in email_search.organic_results or []:
                    title = r.get("title", "")
                    snippet = r.get("snippet", "")
                    if self._email_match(recruiter_email, title) or self._email_match(recruiter_email, snippet):
                        matched_parts = [part for field in (title, snippet)
                                         for part in re.split(r"(?<=[.!?])\s+|[;\n]", field)
                                         if self._email_match(recruiter_email, part)]
                        is_adv, expl = self._evaluate_contact_adverse_context("", " ".join(matched_parts))
                        if is_adv:
                            email_flagged = True
                            adverse_reports_status = "SUPPORTED"
                            adverse_reports_expl = "Public complaints allege fraudulent activity associated with the submitted email contact."
                            link = r.get("link", "https://cybercrime.gov.in")
                            adverse_reports_urls.append(link)
                            evidence_list.append(EvidenceItem(
                                source_url=link,
                                title=title or "Adverse Public Report for Recruiter Email",
                                description=snippet or "Public report alleges fraudulent activity for this email contact.",
                                evidence_type="RECRUITER",
                                confidence=0.90,
                            ))
                            break
            checks["email_reports"]["email_flagged"] = email_flagged
            adverse_reports_facts["email_flagged"] = email_flagged

        if not phone_flagged and not email_flagged:
            if "phone_reports" in checks or "email_reports" in checks:
                has_search_live = any(
                    checks[k]["provider_status"] == "SUCCESS"
                    for k in ("phone_reports", "email_reports") if k in checks
                )
                if has_search_live and all(checks[k]["provider_status"] == "SUCCESS" for k in ("phone_reports", "email_reports") if k in checks):
                    adverse_reports_status = "NO_MATCH"
                    adverse_reports_expl = "No matching adverse scam or fraud reports found for submitted contacts; empty search does not verify identity."
                else:
                    adverse_reports_status = "CHECK_UNAVAILABLE"
                    adverse_reports_expl = "Adverse contact search was unavailable."

        # 4. Recruiter Affiliation Check
        # Run bounded affiliation check when domain matched or agency resolved and no adverse report
        if not phone_flagged and not email_flagged and (recruiter_name or is_valid_email):
            # First check company search results if available
            aff_status = "UNCONFIRMED"
            aff_expl = "Recruiter affiliation could not be confirmed from available evidence."
            affiliation_domain = agency_domain if is_agency else resolved_employer_domain
            affiliation_company = clean_agency if is_agency else company_name
            initial_affiliation_search = agency_search_res if is_agency else company_search_res
            if initial_affiliation_search and initial_affiliation_search.is_live and affiliation_domain:
                aff_status, aff_expl, aff_ev, aff_str = self._evaluate_affiliation_evidence(
                    initial_affiliation_search, recruiter_name, recruiter_email, affiliation_company, affiliation_domain
                )
                if aff_str:
                    recruiter_affiliation_strength = aff_str
                for ev in aff_ev:
                    evidence_list.append(ev)
                    recruiter_affiliation_urls.append(ev.source_url)

            # If unconfirmed and recruiter_name provided (and not generic), perform bounded affiliation search
            if aff_status != "SUPPORTED" and (affiliation_company or "").strip() and (is_valid_email or (recruiter_name and recruiter_name.lower().strip() not in GENERIC_TITLES)):
                aff_subject = recruiter_name.strip() if recruiter_name and recruiter_name.lower().strip() not in GENERIC_TITLES else recruiter_email.strip()
                if aff_subject == (recruiter_email or "").strip() and affiliation_domain:
                    # Is this exact address published on the employer's own site (e.g. an
                    # official hiring-notice page)? Unscoped "<email>" "<company>" searches
                    # are dominated by forum and job-board chatter about the company.
                    aff_query = f'site:{affiliation_domain} "{aff_subject}"'
                else:
                    aff_query = f'"{aff_subject}" "{affiliation_company.strip()}"'
                aff_search = SearchResult.from_dict_or_result(await self.search_client.search(aff_query), query=aff_query)
                record("recruiter_affiliation", aff_search)
                if aff_search.is_live:
                    aff_status, aff_expl, aff_ev, aff_str = self._evaluate_affiliation_evidence(
                        aff_search, recruiter_name, recruiter_email, affiliation_company, affiliation_domain
                    )
                    if aff_str:
                        recruiter_affiliation_strength = aff_str
                    for ev in aff_ev:
                        evidence_list.append(ev)
                        recruiter_affiliation_urls.append(ev.source_url)
                else:
                    checks["recruiter_affiliation"]["provider_status"] = "FAILED"
                    aff_status = "CHECK_UNAVAILABLE"
                    aff_expl = "Recruiter affiliation search unavailable or synthetic."

            recruiter_affiliation_status = aff_status
            recruiter_affiliation_expl = aff_expl
            recruiter_affiliation_facts = {
                "recruiter_name": recruiter_name,
                "company_name": affiliation_company,
                "affiliation_status": aff_status,
                "evidence_strength": recruiter_affiliation_strength,
            }

        # 5. Synthesize provider status
        failed = [check for check in checks.values() if check.get("provider_status") == "FAILED"]
        provider_status = (
            "PARTIAL" if failed and len(failed) < len(checks)
            else "FAILED" if failed
            else "SUCCESS" if checks
            else "NOT_CHECKED"
        )
        search_status = (
            "PARTIAL" if provider_status == "PARTIAL"
            else failed[0]["search_status"] if failed
            else "SUCCESSFUL_EMPTY" if checks and all(c.get("search_status") == "ZERO_RESULTS" for c in checks.values())
            else "SUCCESS" if checks
            else "NOT_CHECKED"
        )

        # Build details payload
        details: Dict[str, Any] = {
            "offer_authenticated": False,
            "domain_match": domain_match,
            "is_free_email": is_free_email,
            "phone_flagged": phone_flagged,
            "email_flagged": email_flagged,
            "contact_provided": bool(recruiter_email or recruiter_phone),
            "provider_status": provider_status,
            "checks": checks,
            "search_status": search_status,
            "is_agency": is_agency,
            "agency_name": clean_agency if (agency_name and clean_agency) else None,
            "agency_domain": agency_domain,
            "agency_domain_match": agency_domain_match,
            "email_domain": email_domain,
            "official_domain": resolved_employer_domain,
            "employer_domain_status": employer_domain_status,
            "recruiter_email_status": recruiter_email_status,
            "recruiter_affiliation_status": recruiter_affiliation_status,
            "agency_identity_status": agency_identity_status,
            "agency_authorization_status": agency_authorization_status,
            "adverse_reports_status": adverse_reports_status,
            "assessment_dimensions": {
                "employer_domain_resolution": {
                    "status": employer_domain_status,
                    "explanation": employer_domain_expl,
                    "source_urls": employer_domain_urls,
                    "raw_facts": employer_domain_facts,
                },
                "recruiter_email_domain": {
                    "status": recruiter_email_status,
                    "explanation": recruiter_email_expl,
                    "source_urls": recruiter_email_urls,
                    "raw_facts": recruiter_email_facts,
                    "is_free_webmail": is_free_email,
                },
                "recruiter_affiliation": {
                    "status": recruiter_affiliation_status,
                    "explanation": recruiter_affiliation_expl,
                    "source_urls": recruiter_affiliation_urls,
                    "raw_facts": recruiter_affiliation_facts,
                    "evidence_strength": recruiter_affiliation_strength,
                },
                "agency_identity": {
                    "status": agency_identity_status,
                    "explanation": agency_identity_expl,
                    "source_urls": agency_identity_urls,
                    "raw_facts": agency_identity_facts,
                },
                "agency_authorization": {
                    "status": agency_authorization_status,
                    "explanation": agency_authorization_expl,
                    "source_urls": agency_authorization_urls,
                    "raw_facts": agency_authorization_facts,
                    "evidence_strength": agency_authorization_strength,
                },
                "adverse_contact_reports": {
                    "status": adverse_reports_status,
                    "explanation": adverse_reports_expl,
                    "source_urls": adverse_reports_urls,
                    "raw_facts": adverse_reports_facts,
                    "has_adverse_reports": bool(phone_flagged or email_flagged),
                    "reports": adverse_reports_urls,
                },
            },
        }
        # Direct access to assessment dimensions
        for dim_name, dim_val in details["assessment_dimensions"].items():
            details[dim_name] = dim_val

        if failed:
            details["error"] = failed[0]["error"]

        # Deduplicate evidence
        seen_keys = set()
        unique_evidence: List[EvidenceItem] = []
        for ev in evidence_list:
            key = (ev.source_url, ev.title)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_evidence.append(ev)

        # =========================================================================
        # 6. Evidence-Appropriate Verdict Decision Policy
        # =========================================================================

        # HIGH_RISK: Supported adverse reports or supported impersonation
        if phone_flagged or email_flagged:
            reasons = []
            if phone_flagged:
                reasons.append("used a phone number appearing in a public scam report")
            if email_flagged:
                reasons.append("used an email address appearing in a public scam report")
            reason_code = "ADVERSE_PHONE_REPORT" if phone_flagged else "ADVERSE_EMAIL_REPORT"
            details["reason_code"] = reason_code
            verdict_summary = "Recruiter warning signals: " + "; ".join(reasons) + "."
            logger.info("RecruiterAgent completed with verdict=HIGH_RISK")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="HIGH_RISK",
                confidence=0.95,
                summary=verdict_summary,
                evidence=unique_evidence,
                details=details,
            )

        # NEEDS_REVIEW: Free webmail, domain mismatch, or agency mandate uncertainty
        if is_free_email:
            details["reason_code"] = "FREE_WEBMAIL_DOMAIN"
            verdict_summary = (
                f"Recruiter contact uses personal webmail domain '@{email_domain}' for corporate hiring; "
                "employer affiliation requires secondary confirmation."
            )
            logger.info("RecruiterAgent completed with verdict=NEEDS_REVIEW (free webmail)")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="NEEDS_REVIEW",
                confidence=0.85,
                summary=verdict_summary,
                evidence=unique_evidence,
                details=details,
            )

        if domain_match is False:
            if is_agency:
                details["reason_code"] = "AGENCY_AFFILIATION_UNCONFIRMED" if agency_authorization_status == "SUPPORTED" else "AGENCY_MANDATE_UNCONFIRMED"
                agency_display = clean_agency if (agency_name and clean_agency) else agency_domain
                verdict_summary = (
                    f"Recruiter operates under third-party staffing agency '{agency_display}'. "
                    + ("Employer partnership is supported; verify this contact and the specific offer directly with the employer." if agency_authorization_status == "SUPPORTED" else "Agency footprint verified, but client representation mandate requires confirmation.")
                )
            else:
                details["reason_code"] = "RECRUITER_DOMAIN_MISMATCH"
                cmp_domain = resolved_employer_domain or company_name
                verdict_summary = (
                    f"Sender domain '@{email_domain}' does not match {company_name}'s official domain '{cmp_domain}'."
                )
            logger.info("RecruiterAgent completed with verdict=NEEDS_REVIEW (domain mismatch / agency)")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="NEEDS_REVIEW",
                confidence=0.85,
                summary=verdict_summary,
                evidence=unique_evidence,
                details=details,
            )

        if is_agency and agency_authorization_status == "UNCONFIRMED":
            details["reason_code"] = "AGENCY_MANDATE_UNCONFIRMED"
            agency_display = clean_agency if (agency_name and clean_agency) else agency_domain
            verdict_summary = (
                f"Recruiter operates under third-party staffing agency '{agency_display}'. "
                "Agency footprint verified, but client representation mandate requires confirmation."
            )
            logger.info("RecruiterAgent completed with verdict=NEEDS_REVIEW (agency mandate)")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="NEEDS_REVIEW",
                confidence=0.85,
                summary=verdict_summary,
                evidence=unique_evidence,
                details=details,
            )

        # VERIFIED: Corporate domain aligns AND recruiter affiliation is supported by evidence
        if domain_match is True and recruiter_affiliation_status == "SUPPORTED" and recruiter_affiliation_strength == "strong_employer_published":
            details["reason_code"] = "RECRUITER_AFFILIATION_VERIFIED"
            verdict_summary = (
                f"Recruiter credentials and employer affiliation with '{company_name}' verified against "
                "public records; this establishes professional affiliation and does not authenticate the individual offer."
            )
            logger.info("RecruiterAgent completed with verdict=VERIFIED")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="VERIFIED",
                confidence=0.85,
                summary=verdict_summary,
                evidence=unique_evidence,
                details=details,
            )

        # CANNOT_VERIFY: Insufficient evidence, domain match alone without affiliation, missing contact, or provider failure
        if domain_match is True:
            details["reason_code"] = "DOMAIN_MATCH_AFFILIATION_UNCONFIRMED"
            verdict_summary = (
                f"Submitted recruiter email domain matches the resolved company domain '{resolved_employer_domain}'; "
                "recruiter identity/affiliation could not be confirmed. Domain alignment alone does not authenticate the individual or offer."
            )
        elif not has_usable_contact:
            if recruiter_email and not is_valid_email:
                details["reason_code"] = "INVALID_CONTACT_INPUT"
            else:
                details["reason_code"] = "NO_CONTACT_PROVIDED"
            verdict_summary = "No valid recruiter contact provided for independent verification."
        else:
            details["reason_code"] = "INSUFFICIENT_RECRUITER_EVIDENCE"
            verdict_summary = "Recruiter identity could not be confirmed. Missing matches and unavailable checks do not establish fraud or legitimacy."

        logger.info("RecruiterAgent completed with verdict=CANNOT_VERIFY")
        return AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary=verdict_summary,
            evidence=unique_evidence,
            details=details,
        )
