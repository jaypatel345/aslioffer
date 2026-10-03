import re
from typing import Optional, List
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchResult
from app.services.search.domain_resolver import DomainResolver, DomainResolutionState
from app.core.logging import logger

FREE_EMAIL_DOMAINS = {
    "gmail.com", "outlook.com", "yahoo.com", "hotmail.com",
    "rediffmail.com", "protonmail.com", "live.com", "icloud.com",
}


class RecruiterAgent:
    """
    Investigates recruiter identity, email domain alignment, and phone number
    legitimacy against live public search data.
    Uses DomainResolver for evidence-backed domain resolution before comparing email domains.
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
        logger.info("RecruiterAgent investigation started")
        evidence_list: List[EvidenceItem] = []
        is_free_email = False
        domain_match = None
        phone_flagged = False
        checks = {}

        def record(name, result):
            checks[name] = {
                "provider_status": "SUCCESS" if result.is_live else "FAILED",
                "search_status": result.outcome.value if result.is_live or result.get("source") == "FAILED" else "DEMO",
                "search_source": result.get("source"),
                "error": result.error if result.is_live or result.get("source") == "FAILED" else "Synthetic results cannot verify an offer",
            }

        if recruiter_email and "@" in recruiter_email:
            email_domain = recruiter_email.split("@")[-1].lower().strip()
            is_free_email = email_domain in FREE_EMAIL_DOMAINS
            if is_free_email:
                evidence_list.append(EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Free Webmail Domain Used for Corporate Recruitment",
                    description="The submitted recruiter contact uses a public webmail domain; employer affiliation requires confirmation.",
                    evidence_type="RECRUITER",
                    confidence=0.98,
                ))
            else:
                query = f'"{company_name}" official website careers'
                search_res = SearchResult.from_dict_or_result(await self.search_client.search(query), query=query)
                record("company_domain", search_res)
                resolution = DomainResolver.resolve(company_name, search_res)
                checks["company_domain"].update({
                    "resolution_state": resolution.state.value,
                    "resolution_basis": resolution.basis,
                    "resolution_diagnostics": resolution.diagnostics,
                    "canonical_domain": resolution.canonical_domain,
                    "rejected_candidates": resolution.rejected_candidates,
                })
                if search_res.is_live:
                    if resolution.state == DomainResolutionState.RESOLVED and resolution.canonical_domain:
                        domain_match = DomainResolver.is_matching_domain(email_domain, resolution.canonical_domain)
                        evidence_list.append(EvidenceItem(
                            source_url=resolution.canonical_url or f"https://{resolution.canonical_domain}",
                            title="Corporate Email Domain Matched" if domain_match else "Recruiter Email Domain Does Not Match Official Company Domain",
                            description="Submitted recruiter email domain matches the official company domain found in search."
                            if domain_match else f"Submitted recruiter email domain '@{email_domain}' differs from the resolved company domain '{resolution.canonical_domain}'.",
                            evidence_type="RECRUITER",
                            confidence=0.88 if domain_match else 0.90,
                        ))
                    else:
                        domain_match = None

        if recruiter_phone:
            phone_query = f'"{recruiter_phone}" scam fraud complaint'
            phone_search = SearchResult.from_dict_or_result(await self.search_client.search(phone_query), query=phone_query)
            record("phone_reports", phone_search)
            if phone_search.is_live:
                digits = re.sub(r"\D", "", recruiter_phone)[-10:]
                scam_hit = next((r for r in phone_search.organic_results
                    if digits and digits in re.sub(r"\D", "", f"{r.get('title', '')} {r.get('snippet', '')}")), None)
                if scam_hit:
                    phone_flagged = True
                    evidence_list.append(EvidenceItem(
                        source_url=scam_hit["link"],
                        title=scam_hit["title"],
                        description=scam_hit.get("snippet", "Public report found for the submitted phone number."),
                        evidence_type="RECRUITER",
                        confidence=0.90,
                    ))
                checks["phone_reports"]["phone_flagged"] = phone_flagged
                checks["phone_reports"]["identity_verified"] = False

        failed = [check for check in checks.values() if check["provider_status"] == "FAILED"]
        provider_status = "PARTIAL" if failed and len(failed) < len(checks) else "FAILED" if failed else "SUCCESS" if checks else "NOT_CHECKED"
        details = {
            "domain_match": domain_match,
            "is_free_email": is_free_email,
            "phone_flagged": phone_flagged,
            "contact_provided": bool(recruiter_email or recruiter_phone),
            "provider_status": provider_status,
            "checks": checks,
            "search_status": "PARTIAL" if provider_status == "PARTIAL" else failed[0]["search_status"] if failed
                else "SUCCESSFUL_EMPTY" if checks and all(c["search_status"] == "ZERO_RESULTS" for c in checks.values())
                else "SUCCESS" if checks else "NOT_CHECKED",
        }
        if failed:
            details["error"] = failed[0]["error"]

        # An adverse warning signal flags HIGH_RISK
        if is_free_email or domain_match is False or phone_flagged:
            reasons = []
            if is_free_email:
                reasons.append("used a personal webmail address")
            if domain_match is False:
                reasons.append("used a domain different from the company domain found in search")
            if phone_flagged:
                reasons.append("used a phone number appearing in a public scam report")
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="HIGH_RISK",
                confidence=0.95,
                summary="Recruiter warning signals: " + "; ".join(reasons) + ".",
                evidence=evidence_list,
                details=details,
            )

        if failed or domain_match is not True:
            return AgentFinding(
                agent_name="RecruiterAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.0,
                summary="Recruiter identity could not be confirmed. Missing matches and unavailable checks do not establish fraud or legitimacy.",
                evidence=evidence_list,
                details=details,
            )

        return AgentFinding(
            agent_name="RecruiterAgent",
            verdict="VERIFIED",
            confidence=0.85,
            summary="Submitted recruiter email domain matches the resolved company domain; this establishes domain alignment only and does not authenticate the individual or offer.",
            evidence=evidence_list,
            details=details,
        )
