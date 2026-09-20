from typing import Optional
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
        Investigate company public footprint.
        Returns mocked investigation results for MVP.
        """
        logger.info("CompanyAgent investigating company: %s", company_name)

        # Query public footprint
        search_res = await self.search_client.search(f"{company_name} official website careers")

        is_known = company_name.lower() not in ["unknown company", "fraud corp", "fake tech"]
        clean_name = company_name.replace(" ", "").lower()
        domain = f"https://www.{clean_name}.com" if is_known else "https://notfound.domain"
        careers = f"https://careers.{clean_name}.com" if is_known else None

        evidence_list = [
            EvidenceItem(
                source_url=domain,
                title=f"{company_name} Official Domain Footprint",
                description=f"Verified public web domain with SSL certificate and corporate history for {company_name}.",
                evidence_type="COMPANY",
                confidence=0.95 if is_known else 0.20,
            ),
            EvidenceItem(
                source_url="https://www.mca.gov.in/content/mca/global/en/home.html",
                title="Ministry of Corporate Affairs (MCA) Registration",
                description=f"Active company registration verified in Ministry of Corporate Affairs database.",
                evidence_type="COMPANY",
                confidence=0.90 if is_known else 0.10,
            ),
        ]

        if not is_known:
            return AgentFinding(
                agent_name="CompanyAgent",
                verdict="UNVERIFIED",
                confidence=0.3,
                summary=f"Unable to find established corporate registration or official domain for '{company_name}'.",
                evidence=evidence_list,
                details={"official_domain": None, "careers_url": None, "mca_status": "NOT_FOUND"},
            )

        return AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.92,
            summary=f"Legitimate corporate footprint and official careers presence confirmed for '{company_name}'.",
            evidence=evidence_list,
            details={"official_domain": domain, "careers_url": careers, "mca_status": "ACTIVE"},
        )
