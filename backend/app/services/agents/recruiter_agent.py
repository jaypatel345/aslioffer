import re
from typing import Optional, List
from urllib.parse import urlparse
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient
from app.core.logging import logger

FREE_EMAIL_DOMAINS = {
    "gmail.com", "outlook.com", "yahoo.com", "hotmail.com",
    "rediffmail.com", "protonmail.com", "live.com", "icloud.com",
}

# Generic platforms that are never a company's own official domain, even if
# they happen to rank first for "<company> official website".
NON_OFFICIAL_DOMAINS = {
    "youtube.com", "facebook.com", "linkedin.com", "twitter.com", "x.com",
    "instagram.com", "wikipedia.org", "indeed.com", "glassdoor.com",
    "naukri.com", "reddit.com", "quora.com",
}


class RecruiterAgent:
    """
    Investigates recruiter identity, email domain alignment, and phone number
    legitimacy against live public search data.
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
        logger.info(
            "RecruiterAgent investigating: company=%s, email=%s, phone=%s",
            company_name,
            recruiter_email,
            recruiter_phone,
        )

        evidence_list: List[EvidenceItem] = []
        is_free_email = False
        domain_mismatch = False
        phone_flagged = False

        if recruiter_email and "@" in recruiter_email:
            email_domain = recruiter_email.split("@")[-1].lower()

            if email_domain in FREE_EMAIL_DOMAINS:
                is_free_email = True
                evidence_list.append(
                    EvidenceItem(
                        source_url="https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                        title="Free Webmail Domain Used for Corporate Recruitment",
                        description=f"Recruiter contacted using '{recruiter_email}'. Legitimate corporate recruiters from {company_name} use official corporate email addresses, not generic @{email_domain} accounts.",
                        evidence_type="RECRUITER",
                        confidence=0.98,
                    )
                )
            else:
                search_res = await self.search_client.search(f'"{company_name}" official website careers')
                official_domains = self._extract_domains(search_res, company_name)

                if official_domains and not any(self._same_domain(email_domain, d) for d in official_domains):
                    domain_mismatch = True
                    evidence_list.append(
                        EvidenceItem(
                            source_url=f"https://{email_domain}",
                            title="Recruiter Email Domain Does Not Match Official Company Domain",
                            description=f"Recruiter emailed from '@{email_domain}', but {company_name}'s verified official domain is '{official_domains[0]}'.",
                            evidence_type="RECRUITER",
                            confidence=0.90,
                        )
                    )
                else:
                    evidence_list.append(
                        EvidenceItem(
                            source_url=f"https://{email_domain}",
                            title="Corporate Email Domain Verified",
                            description=f"Recruiter email domain '@{email_domain}' matches {company_name}'s official public domain."
                            if official_domains
                            else f"Recruiter email domain '@{email_domain}' is not a free webmail provider, but no official domain could be independently confirmed for {company_name}.",
                            evidence_type="RECRUITER",
                            confidence=0.88 if official_domains else 0.55,
                        )
                    )

        if recruiter_phone:
            phone_search = await self.search_client.search(f'"{recruiter_phone}" scam fraud complaint')
            digits = re.sub(r"\D", "", recruiter_phone)[-10:]
            scam_hit = next(
                (
                    r for r in phone_search.get("organic_results", [])
                    if digits and digits in re.sub(r"\D", "", f"{r.get('title', '')} {r.get('snippet', '')}")
                ),
                None,
            )
            if scam_hit:
                phone_flagged = True
                evidence_list.append(
                    EvidenceItem(
                        source_url=scam_hit.get("link", ""),
                        title=scam_hit.get("title", "Scam Report Found"),
                        description=scam_hit.get("snippet", f"Public report found flagging {recruiter_phone} as a suspected scam number."),
                        evidence_type="RECRUITER",
                        confidence=0.90,
                    )
                )
            else:
                evidence_list.append(
                    EvidenceItem(
                        source_url="https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                        title="No Public Scam Reports Found",
                        description=f"No public scam or fraud reports found for {recruiter_phone} at time of check.",
                        evidence_type="RECRUITER",
                        confidence=0.55,
                    )
                )

        if is_free_email or domain_mismatch or phone_flagged:
            reasons = []
            if is_free_email:
                reasons.append(f"sent communications from a personal webmail address ({recruiter_email})")
            if domain_mismatch:
                reasons.append("used an email domain that does not match the company's official domain")
            if phone_flagged:
                reasons.append("used a phone number with existing public scam reports")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="HIGH_RISK",
                confidence=0.95,
                summary=f"Red flag: Recruiter claims to represent {company_name} but {', and '.join(reasons)}.",
                evidence=evidence_list,
                details={"domain_match": not domain_mismatch, "is_free_email": is_free_email, "phone_flagged": phone_flagged},
            )

        return AgentFinding(
            agent_name="RecruiterAgent",
            verdict="VERIFIED",
            confidence=0.85,
            summary=f"Recruiter credentials appear consistent with corporate email standards for {company_name}.",
            evidence=evidence_list,
            details={"domain_match": True, "is_free_email": False, "phone_flagged": False},
        )

    @staticmethod
    def _extract_domains(search_res: dict, company_name: str) -> List[str]:
        name_token = re.sub(r"[^a-z0-9]", "", company_name.lower())
        acronym = "".join(w[0] for w in company_name.split() if w).lower()

        def is_official(netloc: str) -> bool:
            if not netloc or netloc in NON_OFFICIAL_DOMAINS:
                return False
            bare = re.sub(r"[^a-z0-9]", "", netloc)
            return name_token in bare or (len(acronym) >= 2 and acronym in bare)

        domains = []
        kg_website = (search_res.get("knowledge_graph") or {}).get("website")
        if kg_website:
            domains.append(urlparse(kg_website).netloc.lower())
        for result in search_res.get("organic_results", [])[:5]:
            netloc = urlparse(result.get("link", "")).netloc.lower()
            if is_official(netloc) and netloc not in domains:
                domains.append(netloc)
        return domains

    @staticmethod
    def _same_domain(email_domain: str, candidate_netloc: str) -> bool:
        strip_www = lambda d: d[4:] if d.startswith("www.") else d
        return strip_www(email_domain) == strip_www(candidate_netloc)
