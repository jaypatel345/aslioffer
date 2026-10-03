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
    """Verify suspiciously high salary triggers NEEDS_REVIEW, anomaly=True, and only retrieved baseline evidence."""
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

    # Only the actual search result is cited; no invented government warning.
    assert len(finding.evidence) == 1
    assert finding.evidence[0].source_url == "https://www.glassdoor.co.in/Salaries/data-entry-operator-salary"
    assert all("cybercrime.gov.in" not in ev.source_url for ev in finding.evidence)


@pytest.mark.asyncio
async def test_no_search_results_is_inconclusive():
    """Empty search results must not invent a benchmark or verify salary."""
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

    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details["anomaly"] is None
    assert finding.details["search_status"] == "SUCCESSFUL_EMPTY"
    assert finding.evidence == []


@pytest.mark.asyncio
async def test_mock_search_source():
    """Synthetic results are tracked but cannot verify a real salary."""
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

    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details["search_source"] == SearchSource.MOCK.value
    assert finding.evidence == []
