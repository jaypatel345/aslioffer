"""
Evidence-backed official company domain resolver for AsliOffer.

Provides deterministic, offline-capable domain resolution, normalization,
and candidate evaluation shared by CompanyAgent and RecruiterAgent.
"""
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from app.services.search.serpapi_client import SearchOutcome, SearchResult


class DomainResolutionState(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"


# Comprehensive offline list of multi-label public suffixes (ccSLDs / multi-part TLDs).
# Ensures correct registrable domain extraction without network calls or external downloads.
MULTI_PART_PUBLIC_SUFFIXES: Set[str] = {
    # India (.in)
    "co.in", "com.in", "net.in", "org.in", "gen.in", "firm.in", "ind.in",
    "gov.in", "mil.in", "ac.in", "edu.in", "res.in",
    # United Kingdom (.uk)
    "co.uk", "org.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "sch.uk",
    "ac.uk", "gov.uk", "nhs.uk", "police.uk",
    # Australia (.au)
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "asn.au", "id.au", "csiro.au",
    # New Zealand (.nz)
    "co.nz", "net.nz", "org.nz", "govt.nz", "ac.nz", "geek.nz", "gen.nz", "school.nz",
    # Japan (.jp)
    "co.jp", "ne.jp", "ac.jp", "go.jp", "or.jp", "ed.jp", "gr.jp", "lg.jp",
    # South Africa (.za)
    "co.za", "gov.za", "ac.za", "org.za", "net.za",
    # Singapore (.sg)
    "com.sg", "edu.sg", "gov.sg", "org.sg", "net.sg", "per.sg",
    # Brazil (.br)
    "com.br", "org.br", "gov.br", "edu.br", "net.br", "ind.br", "inf.br",
    # Mexico (.mx)
    "com.mx", "gob.mx", "edu.mx", "org.mx", "net.mx",
    # Canada (.ca)
    "gc.ca", "qc.ca",
    # China, Hong Kong, Taiwan (.cn, .hk, .tw)
    "com.cn", "net.cn", "gov.cn", "org.cn", "edu.cn",
    "com.hk", "edu.hk", "gov.hk", "org.hk", "net.hk",
    "com.tw", "org.tw", "gov.tw", "edu.tw",
    # Malaysia, Philippines, Pakistan, Bangladesh
    "com.my", "edu.my", "gov.my", "org.my", "net.my",
    "com.ph", "gov.ph", "edu.ph", "org.ph", "net.ph",
    "com.pk", "org.pk", "edu.pk", "gov.pk", "net.pk",
    "com.bd", "edu.bd", "gov.bd", "org.bd",
    # Nigeria, Kenya, Ghana, Egypt, Saudi Arabia, UAE, Israel
    "com.ng", "gov.ng", "edu.ng", "org.ng",
    "co.ke", "or.ke", "ac.ke", "go.ke",
    "com.gh", "edu.gh", "gov.gh", "org.gh",
    "com.eg", "edu.eg", "gov.eg",
    "com.sa", "gov.sa", "edu.sa", "org.sa",
    "com.ae", "gov.ae", "net.ae", "org.ae",
    "co.il", "org.il", "gov.il", "ac.il",
    # Europe & Others
    "com.ru", "net.ru", "org.ru",
    "com.ua", "gov.ua", "edu.ua", "net.ua", "org.ua",
    "com.pl", "org.pl", "net.pl",
    "co.id", "go.id", "ac.id", "or.id", "web.id",
    "co.th", "ac.th", "go.th", "or.th", "net.th",
    "com.vn", "net.vn", "org.vn", "edu.vn", "gov.vn",
    "com.tr", "edu.tr", "gov.tr", "org.tr",
    "com.co", "co.co", "edu.co", "gov.co",
    "com.ar", "gob.ar", "edu.ar",
    "com.pe", "gob.pe", "edu.pe",
    "co.kr", "ne.kr", "re.kr", "go.kr",
}

# Platforms that provide contextual or aggregator data, but whose hostnames
# or subdomains must NEVER be accepted as an employer's canonical corporate website.
EXCLUDED_HOSTNAMES: Set[str] = {
    # Social media & community platforms
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reddit.com", "threads.net",
    "quora.com", "medium.com", "tumblr.com",
    # Encyclopedias & public reference
    "wikipedia.org", "wikimedia.org", "wikidata.org",
    # Government registries & cyber enforcement
    "cybercrime.gov.in", "mca.gov.in", "incometax.gov.in", "sebi.gov.in", "rbi.org.in",
    # Business directories & aggregators
    "crunchbase.com", "pitchbook.com", "bloomberg.com", "reuters.com", "forbes.com",
    "zaubacorp.com", "tofler.in", "instafinancials.com", "indiamart.com", "justdial.com",
    "tradeindia.com", "zoominfo.com", "consumer-forum.example", "consumercomplaints.in",
    # Job boards & review aggregators
    "indeed.com", "glassdoor.com", "naukri.com", "monster.com", "foundit.in",
    "shine.com", "hirist.com", "internshala.com", "unstop.com", "wellfound.com",
    "angel.co", "ziprecruiter.com", "simplyhired.com", "timesjobs.com",
    "ambitionbox.com", "levels.fyi", "comparably.com", "careerbliss.com",
}

# Hosted ATS (Applicant Tracking System) platforms.
# These can be accepted as associated careers URLs ONLY when explicitly linked
# to the employer via verified tenant identifier/path, but NEVER as corporate websites.
HOSTED_CAREERS_PLATFORMS: Set[str] = {
    "greenhouse.io", "lever.co", "workday.com", "myworkdayjobs.com",
    "smartrecruiters.com", "jobvite.com", "icims.com", "bamboohr.com",
    "ashbyhq.com", "taleo.net", "workable.com", "recruitee.com", "breezy.hr",
    "applytojob.com", "rippling-ats.com", "recruiterbox.com", "freshteam.com",
}

# Recruiting/portal keywords that frequently appear in lookalike hostnames
SUSPICIOUS_PORTAL_KEYWORDS: Set[str] = {
    "careers", "career", "portal", "jobs", "job", "hiring", "recruitment",
    "recruit", "apply", "onboarding", "verify", "offer", "hr", "desk",
    "work", "employment",
}

LEGAL_SUFFIXES: Tuple[str, ...] = (
    "private limited", "pvt ltd", "pvt. ltd.", "limited", "ltd", "llp",
    "incorporated", "inc", "corporation", "corp", "company", "co",
)

BUSINESS_DESCRIPTORS: Tuple[str, ...] = (
    "technologies", "technology", "tech", "infotech", "consultancy services",
    "consultancy", "solutions", "services", "enterprises", "enterprise",
    "industries", "industry", "systems", "holdings", "group", "labs",
    "studio", "software", "bpm", "bpo",
)


@dataclass
class ParsedDomain:
    raw_url: str
    normalized_url: Optional[str] = None
    hostname: Optional[str] = None
    registrable_domain: Optional[str] = None
    subdomain: Optional[str] = None
    sld: Optional[str] = None
    public_suffix: Optional[str] = None
    is_valid: bool = False
    rejection_reason: Optional[str] = None


@dataclass
class DomainResolutionResult:
    state: DomainResolutionState
    canonical_domain: Optional[str] = None
    canonical_url: Optional[str] = None
    careers_url: Optional[str] = None
    confidence: float = 0.0
    basis: str = ""
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class DomainResolver:
    """
    Evidence-backed company domain resolver.
    Normalizes candidate domains, eliminates lookalikes, applies hostname-boundary exclusions,
    and requires verified company identity before resolving an official domain.
    """

    @classmethod
    def resolve(cls, company_name: str, search_res: SearchResult) -> DomainResolutionResult:
        """
        Deterministically resolves the official company domain and optional careers portal
        from a completed search result without performing network requests.
        """
        # 1. Check for search unavailability or provider failures
        if not search_res.is_live:
            return DomainResolutionResult(
                state=DomainResolutionState.SEARCH_UNAVAILABLE,
                confidence=0.0,
                basis=f"Search provider unavailable or non-live source ({search_res.outcome.value}).",
                diagnostics={"provider_status": "FAILED", "outcome": search_res.outcome.value},
            )

        # 2. Check for empty search results
        if search_res.is_empty:
            return DomainResolutionResult(
                state=DomainResolutionState.UNRESOLVED,
                confidence=0.30,
                basis=f"Live search completed successfully but returned no results for '{company_name}'.",
                diagnostics={"search_status": "SUCCESSFUL_EMPTY"},
            )

        # 3. Extract identity tokens from company name
        identity = cls._extract_company_identity(company_name)
        rejected: List[Dict[str, Any]] = []

        # 4. Evaluate Knowledge Graph candidate (if present)
        kg_data = search_res.knowledge_graph or {}
        kg_candidate: Optional[ParsedDomain] = None
        kg_evidence_item: Optional[Dict[str, Any]] = None
        kg_website = (kg_data.get("website") or "").strip()
        kg_title = (kg_data.get("title") or "").strip()
        kg_careers = (kg_data.get("careers_url") or "").strip()

        if kg_website:
            parsed_kg = cls.normalize_and_parse_url(kg_website)
            if not parsed_kg.is_valid:
                rejected.append({
                    "url": kg_website,
                    "source": "knowledge_graph",
                    "reason": parsed_kg.rejection_reason or "invalid_url",
                })
            elif not kg_title:
                rejected.append({
                    "url": kg_website,
                    "source": "knowledge_graph",
                    "reason": "Knowledge graph lacks entity title to confirm company identity",
                })
            elif not cls._title_matches_identity(kg_title, identity):
                rejected.append({
                    "url": kg_website,
                    "source": "knowledge_graph",
                    "reason": f"Knowledge graph entity title '{kg_title}' does not match claimed company '{company_name}'",
                })
            elif cls.is_excluded_platform(parsed_kg.hostname or ""):
                rejected.append({
                    "url": kg_website,
                    "source": "knowledge_graph",
                    "reason": f"Knowledge graph points to excluded platform: {parsed_kg.hostname}",
                })
            elif not cls._sld_matches_identity(parsed_kg.sld or "", identity):
                rejected.append({
                    "url": kg_website,
                    "source": "knowledge_graph",
                    "reason": f"Knowledge graph domain '{parsed_kg.registrable_domain}' does not align with company identity",
                })
            else:
                kg_candidate = parsed_kg
                kg_evidence_item = {
                    "source_url": parsed_kg.normalized_url or kg_website,
                    "title": kg_title or f"{company_name} Official Website",
                    "description": f"Official domain listed in verified knowledge graph for '{company_name}'.",
                    "evidence_type": "COMPANY",
                    "confidence": 0.92,
                }

        # 5. Evaluate Organic Search Results
        organic_results = search_res.organic_results or []
        organic_candidates: List[Tuple[ParsedDomain, Dict[str, Any], int]] = []
        hosted_careers_candidates: List[str] = []

        for rank, res in enumerate(organic_results, start=1):
            raw_link = (res.get("link") or "").strip()
            title = (res.get("title") or "").strip()
            snippet = (res.get("snippet") or "").strip()

            if not raw_link:
                continue

            parsed = cls.normalize_and_parse_url(raw_link)
            if not parsed.is_valid:
                rejected.append({
                    "url": raw_link,
                    "source": f"organic_rank_{rank}",
                    "reason": parsed.rejection_reason or "invalid_url",
                })
                continue

            hostname = parsed.hostname or ""

            # Check if hosted careers platform (e.g., greenhouse.io, workday.com)
            if cls.is_hosted_careers_platform(hostname):
                if cls._is_associated_hosted_careers(parsed, identity):
                    hosted_careers_candidates.append(raw_link)
                else:
                    rejected.append({
                        "url": raw_link,
                        "source": f"organic_rank_{rank}",
                        "reason": f"Hosted careers platform without verified tenant association for '{company_name}'",
                    })
                continue

            # Check excluded platforms (social, job boards, aggregators)
            if cls.is_excluded_platform(hostname):
                rejected.append({
                    "url": raw_link,
                    "source": f"organic_rank_{rank}",
                    "reason": f"Excluded third-party platform or aggregator ({hostname})",
                })
                continue

            # Check lookalike keyword concatenation (e.g. tcs-careers-portal.example)
            is_lookalike, lookalike_reason = cls._check_lookalike(parsed, identity)
            if is_lookalike:
                rejected.append({
                    "url": raw_link,
                    "source": f"organic_rank_{rank}",
                    "reason": lookalike_reason,
                })
                continue

            # Check SLD alignment with company identity
            if not cls._sld_matches_identity(parsed.sld or "", identity):
                rejected.append({
                    "url": raw_link,
                    "source": f"organic_rank_{rank}",
                    "reason": f"Domain '{parsed.registrable_domain}' does not align with company identity",
                })
                continue

            # Check if title indicates an entirely unrelated entity with same acronym
            if not cls._title_or_snippet_corroborates(title, snippet, identity):
                rejected.append({
                    "url": raw_link,
                    "source": f"organic_rank_{rank}",
                    "reason": f"Result title '{title}' indicates an unrelated entity",
                })
                continue

            organic_candidates.append((parsed, res, rank))

        # 6. Group candidates by registrable domain to prevent counting multiple links
        # from the same host as independent confirmations.
        domain_groups: Dict[str, List[Tuple[ParsedDomain, Dict[str, Any], int]]] = {}
        for parsed, res, rank in organic_candidates:
            reg = parsed.registrable_domain or ""
            domain_groups.setdefault(reg, []).append((parsed, res, rank))

        # 7. Decide Resolution State
        # If KG candidate exists and aligns:
        if kg_candidate and kg_candidate.registrable_domain:
            chosen_reg = kg_candidate.registrable_domain
            chosen_url = kg_candidate.normalized_url or kg_website
            canonical_hostname = kg_candidate.hostname or chosen_reg

            evidence_items = []
            if kg_evidence_item:
                evidence_items.append(kg_evidence_item)

            # Add organic results from the same domain as corroboration
            matching_orgs = domain_groups.get(chosen_reg, [])
            for parsed, res, rank in matching_orgs:
                evidence_items.append({
                    "source_url": res.get("link"),
                    "title": res.get("title"),
                    "description": res.get("snippet", ""),
                    "evidence_type": "COMPANY",
                    "confidence": 0.88,
                })

            careers_url = cls._find_careers_url(
                chosen_reg, organic_results, kg_careers, hosted_careers_candidates
            )
            confidence = 0.95 if matching_orgs else 0.90
            basis = (
                f"Resolved via verified knowledge graph entity card for '{company_name}'"
                + (f" and corroborated by {len(matching_orgs)} organic search result(s)." if matching_orgs else ".")
            )

            return DomainResolutionResult(
                state=DomainResolutionState.RESOLVED,
                canonical_domain=canonical_hostname,
                canonical_url=chosen_url,
                careers_url=careers_url,
                confidence=confidence,
                basis=basis,
                evidence=evidence_items,
                rejected_candidates=rejected,
                diagnostics={
                    "resolution_method": "knowledge_graph_corroborated" if matching_orgs else "knowledge_graph_direct",
                    "registrable_domain": chosen_reg,
                    "distinct_organic_hosts": len(domain_groups),
                },
            )

        # No KG candidate. Evaluate organic candidate groups:
        if not domain_groups:
            basis = (
                f"No official company website could be verified for '{company_name}'. "
                "Search results contained no domain matching the company's verified identity."
            )
            return DomainResolutionResult(
                state=DomainResolutionState.UNRESOLVED,
                confidence=0.45,
                basis=basis,
                rejected_candidates=rejected,
                diagnostics={"distinct_organic_hosts": 0},
            )

        # Check for ambiguity: multiple competing distinct registrable domains
        if len(domain_groups) > 1:
            # Check if one candidate is overwhelmingly ranked #1 with exact match
            sorted_groups = sorted(
                domain_groups.items(),
                key=lambda item: min(r for _, _, r in item[1])
            )
            top_reg, top_items = sorted_groups[0]
            second_reg, second_items = sorted_groups[1]
            top_min_rank = min(r for _, _, r in top_items)
            second_min_rank = min(r for _, _, r in second_items)

            # If top is rank 1 and second is much lower, or if they are genuinely ambiguous:
            if top_min_rank == 1 and second_min_rank > 3 and len(top_items) >= 2:
                # Decisive primary candidate
                best_group = top_items
                chosen_reg = top_reg
            else:
                competing = list(domain_groups.keys())
                basis = (
                    f"Ambiguous domain resolution for '{company_name}': multiple plausible domains "
                    f"found ({', '.join(competing)}) without decisive corroborating evidence."
                )
                return DomainResolutionResult(
                    state=DomainResolutionState.AMBIGUOUS,
                    confidence=0.40,
                    basis=basis,
                    rejected_candidates=rejected,
                    diagnostics={"competing_domains": competing},
                )
        else:
            chosen_reg, best_group = next(iter(domain_groups.items()))

        # Single verified organic domain group
        first_parsed, first_res, first_rank = best_group[0]
        # Prefer the root/homepage URL of this candidate
        chosen_url = first_parsed.normalized_url or first_res.get("link")
        canonical_hostname = first_parsed.hostname or chosen_reg

        evidence_items = []
        for parsed, res, rank in best_group:
            evidence_items.append({
                "source_url": res.get("link"),
                "title": res.get("title"),
                "description": res.get("snippet", ""),
                "evidence_type": "COMPANY",
                "confidence": 0.85 if rank == 1 else 0.80,
            })

        careers_url = cls._find_careers_url(
            chosen_reg, organic_results, None, hosted_careers_candidates
        )
        confidence = 0.85 if len(best_group) > 1 or first_rank == 1 else 0.75
        basis = (
            f"Resolved via top organic search results confirming official web footprint "
            f"at '{chosen_reg}' for '{company_name}'."
        )

        return DomainResolutionResult(
            state=DomainResolutionState.RESOLVED,
            canonical_domain=canonical_hostname,
            canonical_url=chosen_url,
            careers_url=careers_url,
            confidence=confidence,
            basis=basis,
            evidence=evidence_items,
            rejected_candidates=rejected,
            diagnostics={
                "resolution_method": "organic_search_corroborated",
                "registrable_domain": chosen_reg,
                "domain_hits": len(best_group),
            },
        )

    # =========================================================================
    # URL and Hostname Normalization
    # =========================================================================

    @classmethod
    def normalize_and_parse_url(cls, url: str) -> ParsedDomain:
        """
        Normalizes a URL and extracts its hostname, registrable domain, SLD, and public suffix.
        Handles Unicode/IDNA, ports, trailing dots, and multi-label public suffixes.
        Rejects unsupported schemes, credentials, and malformed structures.
        """
        if not url or not isinstance(url, str):
            return ParsedDomain(raw_url=str(url), is_valid=False, rejection_reason="empty_url")

        clean_url = url.strip()

        # Reject control characters or newlines
        if any(ord(c) < 32 for c in clean_url):
            return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="malformed_url_control_chars")

        # Parse scheme and netloc
        if "://" in clean_url:
            parsed = urlsplit(clean_url)
            scheme = parsed.scheme.lower()
            if scheme not in ("http", "https"):
                return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason=f"unsupported_scheme_{scheme}")
        else:
            # Fallback for bare domains (e.g. "wipro.com")
            parsed = urlsplit("//" + clean_url)
            scheme = "https"

        # Reject credential-bearing URLs
        if parsed.username or parsed.password:
            return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="credential_bearing_url")

        raw_host = parsed.hostname
        if not raw_host:
            return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="missing_hostname")

        # Strip trailing dots
        raw_host = raw_host.rstrip(".")

        # Normalize Unicode/IDNA
        try:
            ascii_host = raw_host.encode("idna").decode("ascii").lower()
        except Exception:
            return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="invalid_unicode_hostname")

        # Detect visual punycode homoglyphs (e.g. xn--...)
        if ascii_host.startswith("xn--") or ".xn--" in ascii_host:
            return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="punycode_homoglyph_unsupported")

        # Check hostname labels
        labels = ascii_host.split(".")
        if len(labels) < 2:
            return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="insufficient_hostname_labels")

        # Extract registrable domain using offline public suffix table
        last_two = f"{labels[-2]}.{labels[-1]}"
        if last_two in MULTI_PART_PUBLIC_SUFFIXES:
            if len(labels) < 3:
                return ParsedDomain(raw_url=clean_url, is_valid=False, rejection_reason="public_suffix_only")
            public_suffix = last_two
            sld = labels[-3]
            registrable_domain = f"{sld}.{public_suffix}"
            subdomain = ".".join(labels[:-3]) if len(labels) > 3 else None
        else:
            public_suffix = labels[-1]
            sld = labels[-2]
            registrable_domain = f"{sld}.{public_suffix}"
            subdomain = ".".join(labels[:-2]) if len(labels) > 2 else None

        # Build normalized base URL (scheme + netloc, no path/query)
        port_suffix = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        normalized_url = f"{scheme}://{ascii_host}{port_suffix}"

        return ParsedDomain(
            raw_url=clean_url,
            normalized_url=normalized_url,
            hostname=ascii_host,
            registrable_domain=registrable_domain,
            subdomain=subdomain,
            sld=sld,
            public_suffix=public_suffix,
            is_valid=True,
        )

    # =========================================================================
    # Platform Exclusion and Hosted Careers Checks
    # =========================================================================

    @classmethod
    def is_excluded_platform(cls, hostname: str) -> bool:
        """Checks if a hostname matches an excluded third-party platform by hostname boundary."""
        h = hostname.lower().strip(".")
        for platform in EXCLUDED_HOSTNAMES:
            if h == platform or h.endswith("." + platform):
                return True
        return False

    @classmethod
    def is_hosted_careers_platform(cls, hostname: str) -> bool:
        """Checks if a hostname belongs to a known hosted careers ATS platform."""
        h = hostname.lower().strip(".")
        for platform in HOSTED_CAREERS_PLATFORMS:
            if h == platform or h.endswith("." + platform):
                return True
        return False

    @classmethod
    def _is_associated_hosted_careers(cls, parsed: ParsedDomain, identity: Dict[str, Any]) -> bool:
        """
        Confirms whether a hosted careers URL explicitly links the claimed company
        via its tenant subdomain or initial path component.
        """
        brand_tokens = identity["brand_tokens"]
        host = parsed.hostname or ""

        # Check tenant in subdomain (e.g., wipro.wd3.myworkdayjobs.com)
        subdomain = parsed.subdomain or ""
        sub_parts = subdomain.split(".")
        if any(part in brand_tokens for part in sub_parts):
            return True

        # Check tenant in path (e.g., boards.greenhouse.io/wipro, jobs.lever.co/wipro)
        path = urlsplit(parsed.raw_url).path.strip("/").lower()
        if path:
            first_segment = path.split("/")[0]
            clean_first = re.sub(r"[^a-z0-9]", "", first_segment)
            if clean_first in brand_tokens:
                return True

        return False

    # =========================================================================
    # Lookalike and Identity Checks
    # =========================================================================

    @classmethod
    def _check_lookalike(cls, parsed: ParsedDomain, identity: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Detects lookalike patterns:
        - Brand concatenated with portal/careers keywords in SLD (e.g. tcs-careers-portal.example).
        - Brand appearing in subdomain of an attacker-controlled SLD (e.g. tcs.com.attacker.example).
        """
        sld = parsed.sld or ""
        subdomain = parsed.subdomain or ""
        brand_tokens = identity["brand_tokens"]

        # Check subdomain attack: company brand in subdomain while SLD belongs to third party
        if subdomain:
            sub_clean = re.sub(r"[^a-z0-9]", "", subdomain)
            if any(t in sub_clean for t in brand_tokens if len(t) >= 3):
                if not cls._sld_matches_identity(sld, identity):
                    return True, (
                        f"Deceptive hostname structure: company identity appears in subdomain '{subdomain}', "
                        f"but registrable domain '{parsed.registrable_domain}' is third-party controlled."
                    )

        # Check SLD keyword concatenation (e.g., brand-careers-portal)
        sld_parts = re.split(r"[-_]", sld)
        has_suspicious_word = any(p in SUSPICIOUS_PORTAL_KEYWORDS for p in sld_parts)
        if has_suspicious_word:
            # If the company's own official name does NOT contain these keywords:
            company_words = identity["words"]
            suspicious_found = [p for p in sld_parts if p in SUSPICIOUS_PORTAL_KEYWORDS and p not in company_words]
            if suspicious_found:
                return True, (
                    f"Suspected lookalike domain '{parsed.hostname}': contains recruitment/portal keyword(s) "
                    f"({', '.join(suspicious_found)}) concatenated with brand text."
                )

        return False, ""

    @classmethod
    def _extract_company_identity(cls, company_name: str) -> Dict[str, Any]:
        """Extracts normalized names, bare names, brand tokens, and acronyms from company name."""
        low = company_name.lower().strip()

        # Strip legal suffix
        bare = low
        for suffix in LEGAL_SUFFIXES:
            if bare.endswith(" " + suffix):
                bare = bare[: -(len(suffix) + 1)].strip()
                break

        # Strip business descriptor if bare name has multiple words
        brand = bare
        bare_words = bare.split()
        if len(bare_words) > 1:
            for desc in BUSINESS_DESCRIPTORS:
                if brand.endswith(" " + desc):
                    brand = brand[: -(len(desc) + 1)].strip()
                    break

        words = [re.sub(r"[^a-z0-9]", "", w) for w in low.split() if w]
        bare_clean_words = [re.sub(r"[^a-z0-9]", "", w) for w in bare.split() if w]
        brand_clean_words = [re.sub(r"[^a-z0-9]", "", w) for w in brand.split() if w]

        acronym = "".join(w[0] for w in bare_clean_words if w)
        full_token = "".join(words)
        bare_token = "".join(bare_clean_words)
        brand_token = "".join(brand_clean_words)

        brand_tokens = {t for t in {full_token, bare_token, brand_token} if t}
        if len(acronym) >= 2:
            brand_tokens.add(acronym)
        for w in brand_clean_words:
            if len(w) >= 3:
                brand_tokens.add(w)

        return {
            "raw": company_name,
            "bare": bare,
            "brand": brand,
            "words": set(words),
            "bare_token": bare_token,
            "brand_token": brand_token,
            "acronym": acronym,
            "brand_tokens": brand_tokens,
            "hyphenated_bare": "-".join(bare_clean_words),
            "hyphenated_brand": "-".join(brand_clean_words),
        }

    @classmethod
    def _sld_matches_identity(cls, sld: str, identity: Dict[str, Any]) -> bool:
        """
        Validates whether a domain's SLD corresponds to the company identity.
        Requires whole-token or approved hyphenated match; rejects arbitrary brand substrings.
        """
        if not sld:
            return False

        clean_sld = re.sub(r"[^a-z0-9]", "", sld.lower())

        # Exact match with bare name token (e.g. wipro, tataconsultancyservices, vguard, infosysbpm)
        if clean_sld == identity["bare_token"]:
            return True

        # Exact match with brand name token (e.g. infosys for Infosys BPM, tata for Tata Motors)
        if clean_sld == identity["brand_token"]:
            return True

        # Exact match with hyphenated bare name (e.g. tata-elxsi, v-guard)
        if sld.lower() in (identity["hyphenated_bare"], identity["hyphenated_brand"]):
            return True

        # Exact match with company acronym (e.g. tcs for Tata Consultancy Services)
        if len(identity["acronym"]) >= 2 and clean_sld == identity["acronym"]:
            return True

        return False

    @classmethod
    def _title_matches_identity(cls, title: str, identity: Dict[str, Any]) -> bool:
        """Validates that a Knowledge Graph or page title corresponds to the company identity."""
        if not title:
            return False
        title_clean = re.sub(r"[^a-z0-9]", "", title.lower())
        if identity["bare_token"] in title_clean or identity["brand_token"] in title_clean:
            return True
        if len(identity["acronym"]) >= 2 and identity["acronym"] in title.lower().split():
            return True
        return False

    @classmethod
    def _title_or_snippet_corroborates(cls, title: str, snippet: str, identity: Dict[str, Any]) -> bool:
        """Confirms that organic result title or snippet mentions the company brand."""
        combined = f"{title} {snippet}".lower()
        if identity["bare_token"] and identity["bare_token"] in re.sub(r"[^a-z0-9]", "", combined):
            return True
        if identity["brand_token"] and identity["brand_token"] in re.sub(r"[^a-z0-9]", "", combined):
            return True
        if identity["brand"].lower() in combined:
            return True
        if identity["acronym"] and len(identity["acronym"]) >= 3 and identity["acronym"] in combined:
            return True
        return False

    # =========================================================================
    # Careers URL Extraction
    # =========================================================================

    @classmethod
    def _find_careers_url(
        cls,
        resolved_registrable: str,
        organic_results: List[Dict[str, Any]],
        kg_careers: Optional[str],
        hosted_careers_candidates: List[str],
    ) -> Optional[str]:
        """
        Extracts an associated careers URL only when explicitly verified on the resolved domain
        or on an explicitly associated hosted ATS tenant.
        """
        # 1. Knowledge graph careers URL on the same canonical domain
        if kg_careers:
            parsed_kgc = cls.normalize_and_parse_url(kg_careers)
            if parsed_kgc.is_valid and parsed_kgc.registrable_domain == resolved_registrable:
                return kg_careers

        # 2. Organic result on the resolved canonical domain containing a careers path
        for res in organic_results:
            link = res.get("link") or ""
            parsed = cls.normalize_and_parse_url(link)
            if parsed.is_valid and parsed.registrable_domain == resolved_registrable:
                path = urlsplit(link).path.lower()
                if any(w in path for w in ("career", "careers", "jobs", "join-us", "opportunities")):
                    return link

        # 3. Verified hosted ATS careers platform tenant
        if hosted_careers_candidates:
            return hosted_careers_candidates[0]

        return None

    # =========================================================================
    # Email Domain Comparison (Shared with RecruiterAgent)
    # =========================================================================

    @classmethod
    def is_matching_domain(cls, email_domain: str, canonical_domain: str) -> bool:
        """
        Compares a recruiter email domain against the resolved official company domain.
        Rules:
        - Normalizes both hostnames (lowercase, strip trailing dots, strip www).
        - Accepts exact hostname matches.
        - Accepts legitimate subdomains of the canonical domain (e.g. hr.wipro.com -> wipro.com).
        - Accepts identical registrable domains via public suffix matching.
        - Rejects deceptive suffix lookalikes (e.g. wipro.com.attacker.example -> attacker.example).
        """
        if not email_domain or not canonical_domain:
            return False

        email_clean = email_domain.lower().strip().rstrip(".")
        canon_clean = canonical_domain.lower().strip().rstrip(".")

        # Strip www
        strip_www = lambda d: d[4:] if d.startswith("www.") else d
        email_base = strip_www(email_clean)
        canon_base = strip_www(canon_clean)

        # 1. Exact base match
        if email_base == canon_base:
            return True

        # 2. Subdomain alignment: email domain is a subdomain of canonical domain
        if email_base.endswith("." + canon_base):
            return True

        # 3. Registrable domain alignment
        email_parsed = cls.normalize_and_parse_url("//" + email_clean)
        canon_parsed = cls.normalize_and_parse_url("//" + canon_clean)

        if email_parsed.is_valid and canon_parsed.is_valid:
            if email_parsed.registrable_domain and canon_parsed.registrable_domain:
                return email_parsed.registrable_domain == canon_parsed.registrable_domain

        return False
