from typing import Optional, Dict, Any, List
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchResult
from app.services.search.domain_resolver import DomainResolutionState, resolve_employer_domain
from app.core.logging import logger


class CompanyAgent:
    """
    Investigates whether the claimed company exists, has an official public domain,
    an associated careers portal, and registered business presence (e.g. MCA CIN in India).
    Uses DomainResolver for evidence-backed domain resolution.
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()

    async def investigate(self, company_name: str) -> AgentFinding:
        """
        Investigate company public footprint using live SerpApi search results.
        """
        logger.info("CompanyAgent investigation started")

        search_res, resolution, _ = await resolve_employer_domain(self.search_client, company_name)

        # 1. Handle provider outage, rate limits, timeouts, auth failures
        if not search_res.is_live:
            logger.warning("CompanyAgent search unavailable (outcome=%s)", search_res.outcome.value)
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.0,
                summary="External investigation aborted due to upstream search provider outage / rate limit. No external claims verified.",
                evidence=[],
                details={
                    "official_domain": None,
                    "careers_url": None,
                    "mca_status": "NOT_CHECKED",
                    "provider_status": "FAILED",
                    "error": search_res.error or "Live search evidence unavailable",
                    "search_status": search_res.outcome.value if search_res.get("source") == "FAILED" else "DEMO",
                    "official_domain_resolved": False,
                    "resolution_state": DomainResolutionState.SEARCH_UNAVAILABLE.value,
                },
            )

        # 2. Handle successful search with zero results
        if search_res.is_empty:
            logger.info("CompanyAgent: search yielded zero results")
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.30,
                summary=f"Search completed successfully but returned no indexed public footprint for '{company_name}'.",
                evidence=[],
                details={
                    "official_domain": None,
                    "careers_url": None,
                    "mca_status": "NOT_CHECKED",
                    "provider_status": "SUCCESS",
                    "search_status": "SUCCESSFUL_EMPTY",
                    "official_domain_resolved": False,
                    "resolution_state": DomainResolutionState.UNRESOLVED.value,
                },
            )

        # 3. Official domain, as resolved by the shared DomainResolver above
        if resolution.state == DomainResolutionState.RESOLVED:
            evidence_list: List[EvidenceItem] = [
                EvidenceItem(
                    source_url=item["source_url"],
                    title=item.get("title", f"{company_name} Official Domain"),
                    description=item.get("description", ""),
                    evidence_type="COMPANY",
                    confidence=item.get("confidence", resolution.confidence),
                )
                for item in resolution.evidence
            ]
            if resolution.careers_url and not any(e.source_url == resolution.careers_url for e in evidence_list):
                evidence_list.append(
                    EvidenceItem(
                        source_url=resolution.careers_url,
                        title=f"{company_name} Official Careers Portal",
                        description=f"Verified careers presence associated with '{company_name}'.",
                        evidence_type="COMPANY",
                        confidence=0.85,
                    )
                )

            summary = (
                f"Public company website{' and official careers presence' if resolution.careers_url else ''} "
                f"confirmed for '{company_name}'; this establishes a public company footprint and does not "
                f"authenticate submitted offers or recruiters."
            )

            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="VERIFIED",
                confidence=resolution.confidence,
                summary=summary,
                evidence=evidence_list,
                details={
                    "official_domain": resolution.canonical_url,
                    "careers_url": resolution.careers_url,
                    "canonical_domain": resolution.canonical_domain,
                    "official_domain_resolved": True,
                    "mca_status": "NOT_CHECKED",
                    "provider_status": "SUCCESS",
                    "search_status": "SUCCESS",
                    "resolution_basis": resolution.basis,
                    "resolution_state": resolution.state.value,
                    "resolution_diagnostics": resolution.diagnostics,
                    "rejected_candidates": resolution.rejected_candidates,
                },
            )

        # Unresolved or Ambiguous: corporate footprint unconfirmed
        if resolution.state == DomainResolutionState.AMBIGUOUS:
            summary = (
                f"Domain resolution for '{company_name}' is ambiguous. {resolution.basis} "
                "External corporate footprint could not be conclusively confirmed."
            )
        else:
            summary = (
                f"No official company website or careers portal could be matched to '{company_name}'. "
                f"{resolution.basis} External corporate footprint remains unconfirmed."
            )

        return AgentFinding(
            agent_name="CompanyAgent",
            verdict="CANNOT_VERIFY",
            confidence=resolution.confidence,
            summary=summary,
            evidence=[],  # Rejected candidates kept in details, not verified evidence
            details={
                "official_domain": None,
                "careers_url": None,
                "canonical_domain": None,
                "official_domain_resolved": False,
                "mca_status": "NOT_CHECKED",
                "provider_status": "SUCCESS",
                "search_status": "SUCCESS",
                "resolution_basis": resolution.basis,
                "resolution_state": resolution.state.value,
                "resolution_diagnostics": resolution.diagnostics,
                "rejected_candidates": resolution.rejected_candidates,
            },
        )
