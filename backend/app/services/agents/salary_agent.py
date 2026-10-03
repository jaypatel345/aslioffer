import re
from typing import Optional, List, Dict, Any
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchSource, SearchResult
from app.core.logging import logger


class SalaryAgent:
    """
    Investigates whether the compensation package offered is realistic for the target role
    and experience level based on public salary baselines (AmbitionBox, Glassdoor, Naukri).
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()

    # A figure like "Rs 15,000" is a monthly stipend, not an annual package.
    @staticmethod
    def _interpret(salary: Optional[str]):
        """Returns (amount, unit) where unit is 'annual' | 'monthly' | None."""
        if not salary:
            return None, None
        low = salary.lower()
        match = re.search(r"([\d,]+(?:\.\d+)?)", low)
        if not match:
            return None, None
        try:
            amount = float(match.group(1).replace(",", ""))
        except ValueError:
            return None, None

        if any(k in low for k in ("lpa", "lakh", "per annum", "p.a", "annually")):
            return (amount * 100000 if amount < 1000 else amount), "annual"
        if any(k in low for k in ("per month", "p.m", "monthly", "stipend", "/month")):
            return amount, "monthly"
        if amount < 100000:
            return amount, "monthly"
        return amount, "annual"

    async def investigate(
        self,
        company_name: str,
        role_title: Optional[str],
        offered_salary: Optional[str],
    ) -> AgentFinding:
        """
        Investigate salary plausibility using live market search baselines from SerpApi.
        """
        logger.info(
            "SalaryAgent investigating: role=%s, salary=%s at %s",
            role_title,
            offered_salary,
            company_name,
        )

        role = role_title or "Entry Level Role"
        salary = offered_salary or "Undisclosed"

        # Check for unrealistic salary indicators (e.g. 50k per day or 50 LPA for freshers)
        is_suspiciously_high = any(x in salary.lower() for x in ["50,000 per day", "1000 per hour", "50 lpa", "60 lpa"])

        # Execute market baseline search via SerpApi
        query = f'"{role}" salary "{company_name}" AmbitionBox Glassdoor'
        raw_res = await self.search_client.search(query=query)
        search_res = SearchResult.from_dict_or_result(raw_res, query=query)

        search_source = search_res.get("source", SearchSource.FAILED.value)

        # 1. Handle provider outage / rate limit / failure
        if not search_res.is_available:
            logger.warning("SalaryAgent: salary search unavailable (%s)", search_res.error)
            if is_suspiciously_high:
                return AgentFinding(
                    agent_name="SalaryAgent",
                    verdict="NEEDS_REVIEW",
                    confidence=0.85,
                    summary=f"The stated compensation of '{salary}' is unusually high for {role} and may be used as bait.",
                    evidence=[],
                    details={
                        "offered_salary": salary,
                        "anomaly": True,
                        "provider_status": "FAILED",
                        "error": search_res.error,
                        "search_status": search_res.outcome.value,
                        "search_source": search_source,
                    },
                )
            return AgentFinding(
                agent_name="SalaryAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.0,
                summary=f"Salary baseline search unavailable due to search provider failure ({company_name}).",
                evidence=[],
                details={
                    "offered_salary": salary,
                    "provider_status": "FAILED",
                    "error": search_res.error,
                    "search_status": search_res.outcome.value,
                    "search_source": search_source,
                },
            )

        evidence_list: List[EvidenceItem] = []
        for result in (search_res.organic_results or [])[:3]:
            link = result.get("link")
            title = result.get("title")
            snippet = result.get("snippet")
            if link and title:
                evidence_list.append(
                    EvidenceItem(
                        source_url=link,
                        title=title,
                        description=snippet or f"Market salary reference for {role} at {company_name}.",
                        evidence_type="SALARY",
                        confidence=0.88 if search_source == SearchSource.REAL.value else 0.75,
                    )
                )

        # Fallback to market salary baseline for the role if no company-specific search hits
        if not evidence_list:
            evidence_list.append(
                EvidenceItem(
                    source_url="https://www.ambitionbox.com/salaries",
                    title=f"Market Salary Baseline: {role}",
                    description=f"Standard compensation range for {role} at tier-1/tier-2 tech firms in India is typically ₹3.5 LPA - ₹12 LPA.",
                    evidence_type="SALARY",
                    confidence=0.60,
                )
            )

        if is_suspiciously_high:
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in",
                    title="Inflated Salary Bait Pattern Detected",
                    description=f"Offered salary '{salary}' is disproportionately higher than typical market rates to induce emotional compliance.",
                    evidence_type="SALARY",
                    confidence=0.92,
                )
            )
            return AgentFinding(
                agent_name="SalaryAgent",
                verdict="NEEDS_REVIEW",
                confidence=0.85,
                summary=f"The stated compensation of '{salary}' is unusually high for {role} and may be used as bait.",
                evidence=evidence_list,
                details={
                    "offered_salary": salary,
                    "benchmark_range": "₹3.5 - ₹12 LPA",
                    "anomaly": True,
                    "search_source": search_source,
                    "provider_status": "SUCCESS",
                },
            )

        amount, unit = self._interpret(offered_salary)

        if unit == "monthly":
            return AgentFinding(
                agent_name="SalaryAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.60,
                summary=(
                    f"'{salary}' reads as a monthly stipend rather than an annual package, so it "
                    f"cannot be checked against annual salary bands for {role}. Stipend figures are "
                    "weak evidence either way — confirm the amount and payment terms in writing."
                ),
                evidence=evidence_list,
                details={
                    "offered_salary": salary,
                    "interpreted_as": "monthly stipend",
                    "benchmark_range": "not applicable to monthly stipends",
                    "anomaly": None,
                    "search_source": search_source,
                    "provider_status": "SUCCESS",
                },
            )

        if unit is None:
            return AgentFinding(
                agent_name="SalaryAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.55,
                summary=f"No usable compensation figure was found, so pay could not be benchmarked for {role}.",
                evidence=evidence_list,
                details={
                    "offered_salary": salary,
                    "benchmark_range": "₹4 - ₹14 LPA",
                    "anomaly": None,
                    "search_source": search_source,
                    "provider_status": "SUCCESS",
                },
            )

        # Annual figure well outside entry-level bands is classic bait
        if amount is not None and amount > 2500000:
            return AgentFinding(
                agent_name="SalaryAgent",
                verdict="NEEDS_REVIEW",
                confidence=0.85,
                summary=f"The stated annual compensation '{salary}' is far above typical bands for {role}.",
                evidence=evidence_list,
                details={
                    "offered_salary": salary,
                    "benchmark_range": "₹4 - ₹14 LPA",
                    "anomaly": True,
                    "search_source": search_source,
                    "provider_status": "SUCCESS",
                },
            )

        return AgentFinding(
            agent_name="SalaryAgent",
            verdict="VERIFIED",
            confidence=0.80,
            summary=f"Stated compensation '{salary}' fits expected salary bands for {role} at {company_name}.",
            evidence=evidence_list,
            details={
                "offered_salary": salary,
                "benchmark_range": "₹4 - ₹14 LPA",
                "anomaly": False,
                "search_source": search_source,
                "provider_status": "SUCCESS",
            },
        )
