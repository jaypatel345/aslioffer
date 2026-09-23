import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.agents.salary_agent import SalaryAgent
from app.services.search.serpapi_client import SerpApiClient, SearchSource


@pytest.mark.asyncio
async def test_normal_salary_real_source():
    """Verify normal salary with REAL SerpApi search produces VERIFIED verdict and extracts live links."""
    mock_search_client = MagicMock(spec=SerpApiClient)
    mock_search_client.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [
                {
                    "title": "Software Engineer Salary at Google - AmbitionBox",
                    "link": "https://www.ambitionbox.com/salaries/google-salaries/software-engineer",
                    "snippet": "Software Engineer salary in Google ranges between ₹18 Lakhs to ₹45 Lakhs with an average of ₹28 Lakhs.",
                },
                {
                    "title": "Google Software Engineer Salaries | Glassdoor",
                    "link": "https://www.glassdoor.co.in/Salary/Google-Software-Engineer-Salaries-E9079_D_KO7,24.htm",
                    "snippet": "The estimated total pay for a Software Engineer at Google is ₹25,00,000 per year.",
                },
            ],
        }
    )

    agent = SalaryAgent(search_client=mock_search_client)
    finding = await agent.investigate(
        company_name="Google",
        role_title="Software Engineer",
        offered_salary="₹25 LPA",
    )

    assert finding.agent_name == "SalaryAgent"
    assert finding.verdict == "VERIFIED"
    assert finding.confidence == 0.80
    assert finding.details["anomaly"] is False
    assert finding.details["search_source"] == SearchSource.REAL.value
    assert len(finding.evidence) == 2
    assert finding.evidence[0].source_url == "https://www.ambitionbox.com/salaries/google-salaries/software-engineer"
    assert finding.evidence[0].confidence == 0.88
    assert "₹25 LPA" in finding.summary

    # Ensure search was called with specified query pattern
    mock_search_client.search.assert_called_once_with(
        query='"Software Engineer" salary "Google" AmbitionBox Glassdoor'
    )


@pytest.mark.asyncio
async def test_inflated_salary_triggers_anomaly():
    """Verify suspiciously high salary triggers NEEDS_REVIEW, anomaly=True, and cybercrime bait evidence."""
    mock_search_client = MagicMock(spec=SerpApiClient)
    mock_search_client.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [
                {
                    "title": "Data Entry Salaries - Glassdoor",
                    "link": "https://www.glassdoor.co.in/Salaries/data-entry-operator-salary",
                    "snippet": "Average ₹15,000 per month.",
                }
            ],
        }
    )

    agent = SalaryAgent(search_client=mock_search_client)
    finding = await agent.investigate(
        company_name="QuickCash Services",
        role_title="Data Entry Operator",
        offered_salary="50,000 per day guaranteed payout",
    )

    assert finding.agent_name == "SalaryAgent"
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.confidence == 0.85
    assert finding.details["anomaly"] is True
    assert finding.details["search_source"] == SearchSource.REAL.value
    assert any("bait" in finding.summary.lower() for _ in [1])

    # Should contain search result + cybercrime warning item
    assert len(finding.evidence) == 2
    scam_evidence = finding.evidence[-1]
    assert scam_evidence.source_url == "https://cybercrime.gov.in"
    assert "Bait" in scam_evidence.title
    assert scam_evidence.confidence == 0.92


@pytest.mark.asyncio
async def test_no_search_results_fallback():
    """Verify empty organic results fallback to baseline market evidence gracefully."""
    mock_search_client = MagicMock(spec=SerpApiClient)
    mock_search_client.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [],
        }
    )

    agent = SalaryAgent(search_client=mock_search_client)
    finding = await agent.investigate(
        company_name="Obscure Niche Startup",
        role_title="Prompt Tuning Intern",
        offered_salary="₹6 LPA",
    )

    assert finding.verdict == "VERIFIED"
    assert finding.details["anomaly"] is False
    assert len(finding.evidence) == 1
    assert finding.evidence[0].source_url == "https://www.ambitionbox.com/salaries"
    assert finding.evidence[0].confidence == 0.60


@pytest.mark.asyncio
async def test_mock_search_source():
    """Verify mock search source propagates to details and evidence confidence."""
    mock_search_client = MagicMock(spec=SerpApiClient)
    mock_search_client.search = AsyncMock(
        return_value={
            "source": SearchSource.MOCK.value,
            "organic_results": [
                {
                    "title": "Official Portal | TCS",
                    "link": "https://www.tcs.com",
                    "snippet": "Careers and roles.",
                }
            ],
        }
    )

    agent = SalaryAgent(search_client=mock_search_client)
    finding = await agent.investigate(
        company_name="TCS",
        role_title="Systems Engineer",
        offered_salary="₹4.5 LPA",
    )

    assert finding.verdict == "VERIFIED"
    assert finding.details["search_source"] == SearchSource.MOCK.value
    assert finding.evidence[0].confidence == 0.75
