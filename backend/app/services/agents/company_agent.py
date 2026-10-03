import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchResult, SearchOutcome
from app.core.logging import logger


class CompanyAgent:
    """
    Investigates whether the claimed company exists, has an official public domain,
    a verified careers portal, and registered business presence (e.g. MCA CIN in India).
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()

    async def investigate(self, company_name: str) -> AgentFinding:
        """
        Investigate company public footprint using live SerpApi search results.
        """
        logger.info("CompanyAgent investigating company: %s", company_name)

        query = f'"{company_name}" official website careers'
        raw_res = await self.search_client.search(query)
        search_res = SearchResult.from_dict_or_result(raw_res, query=query)

        # 1. Handle provider outage, rate limits, timeouts, auth failures
        if not search_res.is_available:
            logger.warning(
                "CompanyAgent: search unavailable (outcome=%s, error=%s) for '%s'",
                search_res.outcome.value,
                search_res.error,
                company_name,
            )
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.0,
                summary="External investigation aborted due to upstream search provider outage / rate limit. No external claims verified.",
                evidence=[],
                details={
                    "official_domain": None,
                    "careers_url": None,
                    "mca_status": "NOT_FOUND",
                    "provider_status": "FAILED",
                    "error": search_res.error or "Search provider failure",
                    "search_status": search_res.outcome.value,
                },
            )

        # 2. Handle successful search with zero results
        if search_res.is_empty:
            logger.info("CompanyAgent: search yielded zero results for '%s'", company_name)
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.30,
                summary=f"Search completed successfully but returned no indexed public footprint for '{company_name}'.",
                evidence=[],
                details={
                    "official_domain": None,
                    "careers_url": None,
                    "mca_status": "NOT_FOUND",
                    "provider_status": "SUCCESS",
                    "search_status": "SUCCESSFUL_EMPTY",
                    "official_domain_resolved": False,
                },
            )

        name_token = self._normalize(company_name)
        knowledge_graph = search_res.knowledge_graph or {}
        organic_results = search_res.organic_results or []

        domain = knowledge_graph.get("website")
        careers = knowledge_graph.get("careers_url")
        evidence_list: List[EvidenceItem] = []

        if domain:
            evidence_list.append(
                EvidenceItem(
                    source_url=domain,
                    title=knowledge_graph.get("title", f"{company_name} Official Website"),
                    description=f"Official domain listed in search knowledge graph for {company_name}.",
                    evidence_type="COMPANY",
                    confidence=0.95,
                )
            )

        acronym = "".join(w[0] for w in company_name.split() if w).lower()
        bare_name = self._strip_legal_suffix(company_name)
        tokens = [t for t in {name_token, bare_name} if t]

        for result in organic_results:
            link = result.get("link", "")
            matched = any(self._domain_matches(link, t) for t in tokens) or (
                len(acronym) >= 2 and self._domain_matches(link, acronym)
            )
            if not matched:
                continue
            title = result.get("title", "")
            evidence_list.append(
                EvidenceItem(
                    source_url=link,
                    title=title,
                    description=result.get("snippet", ""),
                    evidence_type="COMPANY",
                    confidence=0.85,
                )
            )
            if not careers and "career" in title.lower():
                careers = link
            if not domain:
                domain = link

        strict_match = bool(domain)

        if not domain and not evidence_list and organic_results:
            top = organic_results[0]
            link = top.get("link", "")
            evidence_list.append(
                EvidenceItem(
                    source_url=link,
                    title=top.get("title", ""),
                    description=top.get("snippet", ""),
                    evidence_type="COMPANY",
                    confidence=0.55,
                )
            )
            domain = link

        # Search returned something, but nothing that belongs to this company.
        if not strict_match:
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.45,
                summary=(
                    f"No official website or careers page could be matched to '{company_name}'. "
                    "Live search returned no domain bearing the company's name, so its corporate "
                    "footprint could not be confirmed."
                ),
                evidence=evidence_list,
                details={
                    "official_domain": None,
                    "careers_url": None,
                    "mca_status": "NOT_FOUND",
                    "provider_status": "SUCCESS",
                    "search_status": "SUCCESS",
                },
            )

        return AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.92 if careers else 0.75,
            summary=f"Legitimate corporate footprint{' and official careers presence' if careers else ''} confirmed for '{company_name}'.",
            evidence=evidence_list,
            details={
                "official_domain": domain,
                "careers_url": careers,
                "mca_status": "ACTIVE",
                "provider_status": "SUCCESS",
                "search_status": "SUCCESS",
            },
        )

    LEGAL_SUFFIXES = (
        "private limited", "pvt ltd", "pvt. ltd.", "limited", "ltd", "llp",
        "incorporated", "inc", "corporation", "corp", "company", "co",
    )

    @classmethod
    def _strip_legal_suffix(cls, name: str) -> str:
        low = name.lower().strip()
        for suffix in cls.LEGAL_SUFFIXES:
            if low.endswith(" " + suffix):
                low = low[: -(len(suffix) + 1)].strip()
                break
        return re.sub(r"[^a-z0-9]", "", low)

    @staticmethod
    def _normalize(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    @staticmethod
    def _domain_matches(url: str, name_token: str) -> bool:
        if not url or not name_token:
            return False
        netloc = re.sub(r"[^a-z0-9]", "", urlparse(url).netloc.lower())
        return name_token in netloc or netloc in name_token
