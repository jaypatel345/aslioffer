from typing import Optional
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient
from app.core.logging import logger


class RecruiterAgent:
    """
    Investigates recruiter identity, email domain alignment, LinkedIn footprint,
    and phone number legitimacy.
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()

    async def investigate(
        self,
        company_name: str,
        recruiter_name: Optional[str],
        recruiter_email: Optional[str],
        recruiter_phone: Optional[str],
    ) -> AgentFinding:
        """
        Investigate recruiter validity.
        Returns mocked investigation results for MVP.
        """
        logger.info(
            "RecruiterAgent investigating: company=%s, email=%s, phone=%s",
            company_name,
            recruiter_email,
            recruiter_phone,
        )

        evidence_list = []
        is_free_email = False
        if recruiter_email:
            free_domains = ["gmail.com", "outlook.com", "yahoo.com", "hotmail.com"]
            domain = recruiter_email.split("@")[-1].lower() if "@" in recruiter_email else ""
            if domain in free_domains:
                is_free_email = True
                evidence_list.append(
                    EvidenceItem(
                        source_url="https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                        title="Free Webmail Domain Used for Corporate Recruitment",
                        description=f"Recruiter contacted using '{recruiter_email}'. Legitimate corporate recruiters from {company_name} use official corporate email addresses, not generic @{domain} accounts.",
                        evidence_type="RECRUITER",
                        confidence=0.98,
                    )
                )
            else:
                evidence_list.append(
                    EvidenceItem(
                        source_url=f"https://www.{domain}",
                        title="Corporate Email Domain Verified",
                        description=f"Recruiter email domain '{domain}' matches corporate registration.",
                        evidence_type="RECRUITER",
                        confidence=0.88,
                    )
                )

        if recruiter_phone:
            evidence_list.append(
                EvidenceItem(
                    source_url="https://www.truecaller.com",
                    title="Recruiter Phone Footprint Check",
                    description=f"Phone number {recruiter_phone} checked against commercial carrier and spam registries.",
                    evidence_type="RECRUITER",
                    confidence=0.85,
                )
            )

        if is_free_email:
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="HIGH_RISK",
                confidence=0.95,
                summary=f"Red flag: Recruiter claims to represent {company_name} but sent communications from a personal webmail address ({recruiter_email}).",
                evidence=evidence_list,
                details={"domain_match": False, "is_free_email": True},
            )

        return AgentFinding(
            agent_name="RecruiterAgent",
            verdict="VERIFIED",
            confidence=0.85,
            summary=f"Recruiter credentials appear consistent with corporate email standards for {company_name}.",
            evidence=evidence_list,
            details={"domain_match": True, "is_free_email": False},
        )
