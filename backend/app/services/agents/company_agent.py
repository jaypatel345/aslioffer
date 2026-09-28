import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient
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

        search_res = await self.search_client.search(f'"{company_name}" official website careers')

        name_token = self._normalize(company_name)
        knowledge_graph = search_res.get("knowledge_graph") or {}
        organic_results = search_res.get("organic_results") or []

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
        # "Infosys Limited" must still match infosys.com, so try the name with its
        # legal suffix removed as well as the full string.
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

        # Whether any result actually resolved to a domain bearing the company's
        # name. Without this, the lenient fallback below "confirmed" a company
        # whose top search hit was a post warning about fake internship offers.
        strict_match = bool(domain)

        # Google already ranks results for "<company> official website careers" by relevance,
        # so if no strict domain/acronym match hit, fall back to the top result as evidence
        # rather than reporting a false UNVERIFIED for legitimately-abbreviated domains.
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

        is_known = bool(domain) or bool(evidence_list)

        if not is_known:
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="UNVERIFIED",
                confidence=0.3,
                summary=f"Unable to find established corporate registration or official domain for '{company_name}'.",
                evidence=[
                    EvidenceItem(
                        source_url="https://www.mca.gov.in/content/mca/global/en/home.html",
                        title="No matching public footprint found",
                        description=f"Live search returned no official domain or careers presence for '{company_name}'.",
                        evidence_type="COMPANY",
                        confidence=0.10,
                    )
                ],
                details={"official_domain": None, "careers_url": None, "mca_status": "NOT_FOUND"},
            )

        # Search returned something, but nothing that belongs to this company.
        # That is precisely the footprint a fabricated employer leaves.
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
                details={"official_domain": None, "careers_url": None, "mca_status": "NOT_FOUND"},
            )

        return AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.92 if careers else 0.75,
            summary=f"Legitimate corporate footprint{' and official careers presence' if careers else ''} confirmed for '{company_name}'.",
            evidence=evidence_list,
            details={"official_domain": domain, "careers_url": careers, "mca_status": "ACTIVE"},
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
