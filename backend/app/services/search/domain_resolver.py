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
from urllib.parse import urlsplit
import ipaddress

import idna
import tldextract

from app.services.search.serpapi_client import SearchResult


class DomainResolutionState(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"


# Use the maintained package's bundled PSL snapshot, including private tenants,
# wildcard rules, and exceptions. No cache files, downloads, or startup requests.
_PSL = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, fallback_to_snapshot=True,
    include_psl_private_domains=True, extra_suffixes=("example",),
)

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


def company_website_query(company_name: str) -> str:
    """Query for the employer's own website. Unquoted on purpose: quoting the full
    legal name plus "careers" ranks job-board pages above the employer's own site."""
    return f"{company_name} official website"


def company_entity_query(company_name: str) -> str:
    """Bare-name query, which is what returns Google's knowledge panel for an entity."""
    return company_name


async def resolve_employer_domain(search_client: Any, company_name: str
                                  ) -> Tuple[SearchResult, "DomainResolutionResult", Optional[SearchResult]]:
    """Search for the employer's website and resolve it, shared by every agent.

    A second, bare-name search is made only when one brand-matching domain already
    dominates the website results but has no other corroboration. Agents share a
    per-run search cache, so repeating this in another agent costs no extra calls.
    Returns (website_search, resolution, entity_search_or_None).
    """
    query = company_website_query(company_name)
    search_res = SearchResult.from_dict_or_result(await search_client.search(query), query=query)
    resolution = DomainResolver.resolve(company_name, search_res)
    entity_res = None
    if (search_res.is_live and not search_res.is_empty
            and resolution.state != DomainResolutionState.RESOLVED
            and DomainResolver.dominant_brand_domain(company_name, search_res) is not None):
        entity_query = company_entity_query(company_name)
        entity_res = SearchResult.from_dict_or_result(await search_client.search(entity_query), query=entity_query)
        if entity_res.is_live:
            resolution = DomainResolver.resolve(company_name, search_res, entity_res)
    return search_res, resolution, entity_res


class DomainResolver:
    """Deterministic search-evidence inference, not proof of domain ownership."""

    # A dominant domain must hold the top organic result and this many of the top five.
    # Two is enough because resolution additionally needs a matching entity card and no
    # rival brand-named domain; live results for big brands are often padded with noise.
    DOMINANCE_TOP_N = 5
    DOMINANCE_MIN_HITS = 2

    @classmethod
    def resolve(cls, company_name: str, search_res: SearchResult,
                entity_res: Optional[SearchResult] = None) -> DomainResolutionResult:
        base = cls._resolve_from_website_search(company_name, search_res)
        if entity_res is None or base.state not in (DomainResolutionState.AMBIGUOUS, DomainResolutionState.UNRESOLVED):
            return base
        return cls._resolve_by_entity_and_dominance(company_name, SearchResult.from_dict_or_result(search_res),
                                                    SearchResult.from_dict_or_result(entity_res), base)

    @classmethod
    def _brand_candidate(cls, link: str, identity: Dict[str, Any]) -> Optional[ParsedDomain]:
        """The parsed URL when its registrable name *is* the brand (infosys.com, tcs.com), else None."""
        parsed = cls.normalize_and_parse_url(link or "")
        if not parsed.is_valid or cls.is_excluded_platform(parsed.hostname) or cls.is_hosted_careers_platform(parsed.hostname):
            return None
        if cls._check_lookalike(parsed, identity)[0] or not cls._sld_matches_identity(parsed.sld, identity):
            return None
        return parsed

    @classmethod
    def dominant_brand_domain(cls, company_name: str, search_res: SearchResult
                              ) -> Optional[Tuple[str, List[Tuple[int, ParsedDomain, Dict[str, Any]]]]]:
        """One brand-named domain that owns the website search: it is the top organic
        result, fills most of the top five, is the only brand-named domain in the top
        five, and at least one of its pages names the company. Lower-ranked brand-named
        sites (e.g. a parent group's tata.com under tcs.com) do not compete. A ranking
        alone is never enough to resolve; it only qualifies the domain for the entity check."""
        search_res = SearchResult.from_dict_or_result(search_res)
        identity = cls._extract_company_identity(company_name)
        if not identity["bare_words"]:
            return None
        domains: Dict[str, List[Tuple[int, ParsedDomain, Dict[str, Any]]]] = {}
        for rank, item in enumerate(search_res.organic_results[:cls.DOMINANCE_TOP_N], start=1):
            parsed = cls._brand_candidate(item.get("link") or "", identity)
            if parsed is not None:
                domains.setdefault(parsed.registrable_domain, []).append((rank, parsed, item))
        if len(domains) != 1:
            return None
        domain, hits = next(iter(domains.items()))
        if hits[0][0] != 1 or len(hits) < cls.DOMINANCE_MIN_HITS:
            return None
        if not any(cls._title_or_snippet_corroborates(item.get("title") or "", item.get("snippet") or "", identity)
                   for _, _, item in hits):
            return None
        return domain, hits

    @classmethod
    def _resolve_by_entity_and_dominance(cls, company_name: str, search_res: SearchResult,
                                         entity_res: SearchResult, base: DomainResolutionResult
                                         ) -> DomainResolutionResult:
        """Resolve a well-known employer whose search card carries no website link.

        Requires both (1) a single brand-named domain dominating the website search and
        (2) a search entity card for exactly this company, with no conflicting website
        and no other brand-named domain in the entity card search's top five. A newly registered or
        fake company can dominate its own name search, but does not get an entity card.
        """
        dominant = cls.dominant_brand_domain(company_name, search_res)
        if dominant is None or not entity_res.is_live:
            return base
        domain, hits = dominant
        identity = cls._extract_company_identity(company_name)
        kg = entity_res.knowledge_graph or {}
        title = kg.get("title") or ""
        if not title or not cls._title_matches_identity(title, identity):
            return base
        if kg.get("website"):
            kg_site = cls.normalize_and_parse_url(kg["website"])
            if kg_site.is_valid and kg_site.registrable_domain != domain:
                return base
        for item in entity_res.organic_results[:cls.DOMINANCE_TOP_N]:
            parsed = cls._brand_candidate(item.get("link") or "", identity)
            if parsed is not None and parsed.registrable_domain != domain:
                return base

        top_parsed = hits[0][1]
        entity_label = f"{title} ({kg['type']})" if kg.get("type") else title
        evidence = []
        seen = set()
        for _, _, item in hits:
            if item["link"] in seen:
                continue
            seen.add(item["link"])
            evidence.append(cls._evidence(
                item["link"], item.get("title") or f"{company_name} website",
                (item.get("snippet") or "Top search result on the employer's own domain.")
                + f" Google's entity card identifies '{entity_label}'; ownership is inferred, not authenticated.",
                0.80))
        careers = cls._find_careers_url(domain, [(p, i, True) for _, p, i in hits], None, [])
        return DomainResolutionResult(
            state=DomainResolutionState.RESOLVED, canonical_domain=top_parsed.hostname,
            canonical_url=top_parsed.normalized_url, careers_url=careers, confidence=0.80,
            basis=(f"'{domain}' is the only brand-named domain and leads the employer website search, "
                   f"and a search entity card identifies '{entity_label}'."),
            evidence=evidence, rejected_candidates=base.rejected_candidates,
            diagnostics={**base.diagnostics, "resolution_method": "entity_card_and_search_dominance",
                         "registrable_domain": domain, "domain_hits": len(hits),
                         "entity_title": title, "entity_type": kg.get("type"),
                         "prior_state": base.state.value, "same_domain_pages_are_independent": False})

    @classmethod
    def _resolve_from_website_search(cls, company_name: str, search_res: SearchResult) -> DomainResolutionResult:
        search_res = SearchResult.from_dict_or_result(search_res)
        if not search_res.is_live:
            return DomainResolutionResult(
                state=DomainResolutionState.SEARCH_UNAVAILABLE,
                basis="Live search evidence is unavailable.",
                diagnostics={"provider_status": "FAILED", "outcome": search_res.outcome.value})
        if search_res.is_empty:
            return DomainResolutionResult(
                state=DomainResolutionState.UNRESOLVED, confidence=0.30,
                basis="Search completed with no results.", diagnostics={"search_status": "SUCCESSFUL_EMPTY"})
        identity = cls._extract_company_identity(company_name)
        if not identity["bare_words"]:
            return DomainResolutionResult(state=DomainResolutionState.UNRESOLVED,
                                          basis="No usable company identity was supplied.")
        rejected = []
        groups = {}
        context = []
        hosted = []
        kg = search_res.knowledge_graph or {}
        kg_parsed = None
        kg_evidence = None

        def reject(url, source, reason):
            rejected.append({"url": url, "source": source, "reason": reason})

        website = kg.get("website") or ""
        if website:
            parsed = cls.normalize_and_parse_url(website)
            title = kg.get("title") or ""
            if not parsed.is_valid:
                reject(website, "knowledge_graph", parsed.rejection_reason)
            elif cls.is_excluded_platform(parsed.hostname) or cls.is_hosted_careers_platform(parsed.hostname):
                reject(website, "knowledge_graph", "Excluded third-party or hosted careers platform")
            elif not title:
                reject(website, "knowledge_graph", "Knowledge graph lacks entity title to confirm company identity")
            elif not cls._title_matches_identity(title, identity):
                reject(website, "knowledge_graph", "Knowledge graph entity does not match claimed company")
            elif cls._check_lookalike(parsed, identity)[0]:
                reject(website, "knowledge_graph", cls._check_lookalike(parsed, identity)[1])
            else:
                kg_parsed = parsed
                # Preserve the actual URL, including any original path, as provenance.
                kg_evidence = cls._evidence(website, title,
                    "Company-aligned search entity card identifies this website; ownership is inferred, not independently authenticated.", 0.85)

        for rank, item in enumerate(search_res.organic_results, start=1):
            link = item.get("link") or ""
            title, snippet = item.get("title") or "", item.get("snippet") or ""
            parsed = cls.normalize_and_parse_url(link)
            source = f"organic_rank_{rank}"
            if not parsed.is_valid:
                reject(link, source, parsed.rejection_reason)
                continue
            if cls.is_hosted_careers_platform(parsed.hostname):
                if cls._is_associated_hosted_careers(parsed, identity) and cls._title_or_snippet_corroborates(title, snippet, identity):
                    hosted.append((parsed, item))
                else:
                    reject(link, source, "Hosted careers platform lacks exact employer/tenant identity")
                continue
            if cls.is_excluded_platform(parsed.hostname):
                # Context can link a corporate site, but never becomes that site.
                context.append((parsed, item))
                reject(link, source, "Excluded third-party platform or aggregator")
                continue
            lookalike, reason = cls._check_lookalike(parsed, identity)
            if lookalike:
                reject(link, source, reason)
                continue
            strong = cls._full_identity_mentioned(f"{title} {snippet}", identity)
            discoverable = cls._title_or_snippet_corroborates(title, snippet, identity)
            if not discoverable or (not strong and not cls._sld_matches_identity(parsed.sld, identity)):
                reject(link, source, "Candidate domain does not align with sufficient company identity evidence")
                continue
            groups.setdefault(parsed.registrable_domain, []).append((parsed, item, strong))

        plausible = set(groups)
        if kg_parsed:
            plausible.add(kg_parsed.registrable_domain)
        candidates = sorted(plausible)
        diagnostics = {"candidate_domains": candidates, "distinct_organic_hosts": len(groups),
                       "evidence_scope": "search inference; no domain-control authentication"}
        if len(plausible) > 1:
            # Rank and duplicate pages never override contradictory candidates.
            return DomainResolutionResult(state=DomainResolutionState.AMBIGUOUS, confidence=0.40,
                basis="Ambiguous domain resolution: multiple plausible domains remain; search ranking and repeated pages cannot resolve the conflict.",
                rejected_candidates=rejected, diagnostics={**diagnostics, "competing_domains": candidates})
        if not plausible:
            return DomainResolutionResult(state=DomainResolutionState.UNRESOLVED, confidence=0.30,
                basis="No supported corporate-domain candidate was found.", rejected_candidates=rejected, diagnostics=diagnostics)

        domain = next(iter(plausible))
        items = groups.get(domain, [])
        full_items = [(parsed, item) for parsed, item, strong in items if strong]
        references = []
        for parsed, item in context:
            # Search snippets must explicitly identify both the employer and URL.
            if cls._full_identity_mentioned(f"{item.get('title', '')} {item.get('snippet', '')}", identity):
                for url in cls._mentioned_urls(item.get("snippet") or ""):
                    target = cls.normalize_and_parse_url(url)
                    if target.is_valid and target.registrable_domain == domain:
                        references.append(item)
                        break
        kg_supported = kg_parsed is not None and kg_parsed.registrable_domain == domain and bool(full_items)
        independently_referenced = bool(full_items and references)
        if not kg_supported and not independently_referenced:
            return DomainResolutionResult(state=DomainResolutionState.UNRESOLVED, confidence=0.40,
                basis="A candidate was discovered, but matching hostnames, titles, or repeated self-described pages do not establish an official company website.",
                rejected_candidates=rejected, diagnostics=diagnostics)

        chosen = kg_parsed if kg_supported else full_items[0][0]
        evidence = [kg_evidence] if kg_supported else []
        seen = {kg_evidence["source_url"]} if kg_supported else set()
        for _, item in full_items:
            if item["link"] not in seen:
                evidence.append(cls._evidence(item["link"], item["title"], item.get("snippet") or "Company-identifying result on the candidate domain.", 0.80))
                seen.add(item["link"])
        for item in references:
            if item["link"] not in seen:
                evidence.append(cls._evidence(item["link"], item["title"], item.get("snippet") or "External reference identifies the company website.", 0.80))
                seen.add(item["link"])
        careers = cls._find_careers_url(domain, items, kg.get("careers_url") if kg_supported else None, hosted)
        method = "knowledge_graph_corroborated" if kg_supported else "explicit_external_reference"
        return DomainResolutionResult(
            state=DomainResolutionState.RESOLVED, canonical_domain=chosen.hostname,
            canonical_url=chosen.normalized_url, careers_url=careers, confidence=0.90 if kg_supported else 0.80,
            basis="Company identity and website association are supported by a search entity card and company-identifying results."
                if kg_supported else "A company-identifying website result is corroborated by an explicit external website reference.",
            evidence=evidence, rejected_candidates=rejected,
            diagnostics={**diagnostics, "resolution_method": method, "registrable_domain": domain,
                         "domain_hits": len(items), "independent_reference_hosts": len({cls.normalize_and_parse_url(i["link"]).registrable_domain for i in references}),
                         "same_domain_pages_are_independent": False})

    @staticmethod
    def _evidence(url, title, description, confidence):
        return {"source_url": url, "title": title, "description": description,
                "evidence_type": "COMPANY", "confidence": confidence}

    @classmethod
    def normalize_and_parse_url(cls, url: str) -> ParsedDomain:
        def invalid(reason):
            return ParsedDomain(raw_url=str(url), rejection_reason=reason)
        if not isinstance(url, str) or not url.strip():
            return invalid("empty_url")
        clean = url.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in clean) or "\\" in clean:
            return invalid("malformed_url_control_chars")
        try:
            if clean.startswith("//"):
                parsed = urlsplit("https:" + clean)
            elif "://" in clean:
                parsed = urlsplit(clean)
            else:
                parsed = urlsplit("https://" + clean)
            scheme = parsed.scheme.lower()
            if scheme not in ("http", "https"):
                return invalid("unsupported_scheme_" + scheme)
            if parsed.username is not None or parsed.password is not None:
                return invalid("credential_bearing_url")
            host = parsed.hostname
            port = parsed.port  # Access can raise ValueError; never leak it to agents.
            if not host:
                return invalid("missing_hostname")
            host = host.removesuffix(".")
            ascii_host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii").lower()
        except (ValueError, UnicodeError, idna.IDNAError):
            return invalid("malformed_hostname_or_port")
        if len(ascii_host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in ascii_host.split(".")):
            return invalid("invalid_hostname_label")
        try:
            ipaddress.ip_address(ascii_host)
            return invalid("ip_address_not_company_domain")
        except ValueError:
            pass
        extracted = _PSL(ascii_host)
        if not extracted.suffix:
            return invalid("unknown_public_suffix")
        if not extracted.domain:
            return invalid("public_suffix_only")
        suffix = extracted.suffix
        domain = extracted.domain + "." + suffix
        default_port = 80 if scheme == "http" else 443
        port_suffix = f":{port}" if port is not None and port != default_port else ""
        return ParsedDomain(raw_url=url, normalized_url=f"{scheme}://{ascii_host}{port_suffix}",
            hostname=ascii_host, registrable_domain=domain, subdomain=extracted.subdomain or None,
            sld=extracted.domain, public_suffix=suffix, is_valid=True)

    @staticmethod
    def is_excluded_platform(hostname: str) -> bool:
        h = hostname.lower().rstrip(".")
        return any(h == platform or h.endswith("." + platform) for platform in EXCLUDED_HOSTNAMES)

    @staticmethod
    def is_hosted_careers_platform(hostname: str) -> bool:
        h = hostname.lower().rstrip(".")
        return any(h == platform or h.endswith("." + platform) for platform in HOSTED_CAREERS_PLATFORMS)

    @staticmethod
    def _words(text):
        return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text or "").casefold(), flags=re.UNICODE)

    @classmethod
    def _extract_company_identity(cls, company_name: str) -> Dict[str, Any]:
        words = cls._words(company_name)
        for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
            ending = cls._words(suffix)
            if len(words) > len(ending) and words[-len(ending):] == ending:
                words = words[:-len(ending)]
                break
        brand = list(words)
        for suffix in sorted(BUSINESS_DESCRIPTORS, key=len, reverse=True):
            ending = cls._words(suffix)
            if len(brand) > len(ending) and brand[-len(ending):] == ending:
                brand = brand[:-len(ending)]
                break
        acronym = "".join(word[0] for word in words)
        return {"raw": company_name, "bare_words": words, "brand_words": brand,
                "bare_token": "".join(words), "brand_token": "".join(brand), "acronym": acronym,
                "brand_tokens": {"".join(words), "".join(brand), acronym} - {""}}

    @classmethod
    def _full_identity_mentioned(cls, text: str, identity: Dict[str, Any]) -> bool:
        words, name = cls._words(text), identity["bare_words"]
        return bool(name) and any(words[i:i + len(name)] == name for i in range(len(words) - len(name) + 1))

    @classmethod
    def _title_matches_identity(cls, title: str, identity: Dict[str, Any]) -> bool:
        title_id = cls._extract_company_identity(title)
        return bool(identity["bare_words"]) and title_id["bare_words"] == identity["bare_words"]

    @classmethod
    def _title_or_snippet_corroborates(cls, title: str, snippet: str, identity: Dict[str, Any]) -> bool:
        text = f"{title} {snippet}"
        if cls._full_identity_mentioned(text, identity):
            return True
        words, brand = cls._words(text), identity["brand_words"]
        if brand and any(words[i:i + len(brand)] == brand for i in range(len(words) - len(brand) + 1)):
            return True
        return len(identity["acronym"]) >= 3 and identity["acronym"] in words

    @classmethod
    def _sld_matches_identity(cls, sld: str, identity: Dict[str, Any]) -> bool:
        try:
            decoded = idna.decode(sld) if sld.startswith("xn--") else sld
        except idna.IDNAError:
            return False
        return "".join(cls._words(decoded)) in identity["brand_tokens"]

    @classmethod
    def _check_lookalike(cls, parsed: ParsedDomain, identity: Dict[str, Any]) -> Tuple[bool, str]:
        if (parsed.sld or "").startswith("xn--") and not cls._sld_matches_identity(parsed.sld, identity):
            return True, "IDNA candidate lacks exact Unicode company identity alignment; visual similarity is not evidence"
        if parsed.subdomain and not cls._sld_matches_identity(parsed.sld, identity):
            labels = parsed.subdomain.split(".")
            if any(label in identity["brand_tokens"] for label in labels):
                return True, "Suspected lookalike: company name occurs in an unrelated registrable domain's subdomain"
        parts = set((parsed.sld or "").split("-"))
        suspicious = parts & SUSPICIOUS_PORTAL_KEYWORDS - set(identity["bare_words"])
        if suspicious:
            return True, "Suspected lookalike: recruitment/portal keyword in candidate domain"
        return False, ""

    @classmethod
    def _is_associated_hosted_careers(cls, parsed: ParsedDomain, identity: Dict[str, Any]) -> bool:
        # A matching slug only discovers a candidate, never proves association.
        words = identity["brand_tokens"]
        subdomain = (parsed.subdomain or "").split(".")
        path = urlsplit(parsed.raw_url).path.strip("/").split("/")[0]
        return any(label in words for label in subdomain) or "".join(cls._words(path)) in words

    @staticmethod
    def _mentioned_urls(text):
        return [url.rstrip(".,);]}") for url in re.findall(r"https?://[^\s<>\"']+", text or "")]

    @classmethod
    def _url_key(cls, url):
        parsed = cls.normalize_and_parse_url(url)
        if not parsed.is_valid:
            return None
        raw = urlsplit(url if "://" in url or url.startswith("//") else "https://" + url)
        return (parsed.normalized_url, raw.path.rstrip("/"), raw.query)

    @classmethod
    def _find_careers_url(cls, resolved_registrable, candidate_items, kg_careers, hosted):
        if kg_careers:
            parsed = cls.normalize_and_parse_url(kg_careers)
            if parsed.is_valid and parsed.registrable_domain == resolved_registrable:
                return kg_careers
        for parsed, item, strong in candidate_items:
            if strong:
                path_words = set(cls._words(urlsplit(item["link"]).path))
                if path_words & {"career", "careers", "jobs", "opportunities"} or {"join", "us"}.issubset(path_words):
                    return item["link"]
        references = []
        if kg_careers:
            references.append(kg_careers)
        for _, item, strong in candidate_items:
            if strong:
                references.extend(cls._mentioned_urls(item.get("snippet") or ""))
        linked = {cls._url_key(url) for url in references if cls._url_key(url) is not None}
        for parsed, item in hosted:
            if cls._url_key(item["link"]) in linked:
                return item["link"]
        return None

    @classmethod
    def is_matching_domain(cls, email_domain: str, canonical_domain: str) -> bool:
        # Only hostname inputs are accepted; validate before any equality shortcut.
        def parse_host(value):
            if not isinstance(value, str) or any(c in value for c in "/:@?#\\"):
                return None
            parsed = cls.normalize_and_parse_url("https://" + value.strip())
            return parsed if parsed.is_valid else None
        email = parse_host(email_domain)
        canonical = parse_host(canonical_domain)
        return bool(email and canonical and email.registrable_domain == canonical.registrable_domain)
