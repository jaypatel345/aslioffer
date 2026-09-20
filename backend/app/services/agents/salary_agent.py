from typing import Optional
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient
from app.core.logging import logger


class SalaryAgent:
    """
    Investigates whether the compensation package offered is realistic for the target role
    and experience level based on public salary baselines (AmbitionBox, Glassdoor, Naukri).
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()

    async def investigate(
        self,
        company_name: str,
        role_title: Optional[str],
        offered_salary: Optional[str],
    ) -> AgentFinding:
        """
        Investigate salary plausibility.
        Returns mocked investigation results for MVP.
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

        evidence_list = [
            EvidenceItem(
                source_url="https://www.ambitionbox.com/salaries",
                title=f"Market Salary Baseline: {role}",
                description=f"Standard compensation range for {role} at tier-1/tier-2 tech firms in India is typically ₹3.5 LPA - ₹12 LPA.",
                evidence_type="SALARY",
                confidence=0.88,
            )
        ]

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
                details={"offered_salary": salary, "benchmark_range": "₹3.5 - ₹12 LPA", "anomaly": True},
            )

        return AgentFinding(
            agent_name="SalaryAgent",
            verdict="VERIFIED",
            confidence=0.80,
            summary=f"Stated compensation '{salary}' fits expected salary bands for {role} at {company_name}.",
            evidence=evidence_list,
            details={"offered_salary": salary, "benchmark_range": "₹4 - ₹14 LPA", "anomaly": False},
        )
