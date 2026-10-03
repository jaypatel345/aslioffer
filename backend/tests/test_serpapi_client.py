import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.services.search.serpapi_client import (
    SerpApiClient,
    SearchResult,
    SearchOutcome,
    SearchSource,
    sanitize_search_text,
)
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.salary_agent import SalaryAgent
from app.services.agents.scam_agent import ScamAgent
from app.services.risk.risk_engine import RiskEngine
from app.schemas.analysis import AgentFinding, RiskLevel


# ===========================================================================
# 1. Search Client Unit & Outcome Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_successful_populated_search():
    """1. Successful search with usable results returns outcome SUCCESS."""
    client = SerpApiClient(api_key="valid_test_key")

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "organic_results": [
            {"title": "Tata Consultancy Services", "link": "https://www.tcs.com", "snippet": "Official site"}
        ],
        "knowledge_graph": {"website": "https://www.tcs.com"},
        "search_metadata": {"status": "Success"},
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await client.search("TCS official careers")

        assert res.outcome == SearchOutcome.SUCCESS
        assert res.is_success is True
        assert res.is_available is True
        assert res.is_empty is False
        assert res["source"] == SearchSource.REAL.value
        assert len(res.organic_results) == 1
        assert res.knowledge_graph["website"] == "https://www.tcs.com"
        assert res.error is None
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_successful_empty_search():
    """2. Successful search with zero results returns outcome ZERO_RESULTS, not an error."""
    client = SerpApiClient(api_key="valid_test_key")

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "organic_results": [],
        "knowledge_graph": {},
        "search_metadata": {"total_results": 0, "status": "Success"},
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await client.search("NonExistentUnknownOrg12345 official website")

        assert res.outcome == SearchOutcome.ZERO_RESULTS
        assert res.is_empty is True
        assert res.is_available is True
        assert res.is_success is False
        assert res["source"] == SearchSource.REAL.value
        assert res.organic_results == []
        assert res.error is None


@pytest.mark.asyncio
async def test_timeout():
    """3. Timeout failure returns outcome TIMEOUT with bounded execution."""
    client = SerpApiClient(api_key="valid_test_key", timeout=1.0, max_retries=1, retry_backoff=0.01)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ReadTimeout("Read timed out after 1.0s")
        res = await client.search("Wipro careers")

        assert res.outcome == SearchOutcome.TIMEOUT
        assert res.is_available is False
        assert res["status"] == "failed"
        assert res["source"] == SearchSource.FAILED.value
        assert "timed out" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_rate_limit():
    """4. HTTP 429 returns outcome RATE_LIMIT without fabricated fallbacks."""
    client = SerpApiClient(api_key="valid_test_key", max_retries=0)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 429
    mock_resp.headers = {}
    mock_resp.text = "Too Many Requests"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await client.search("Infosys careers")

        assert res.outcome == SearchOutcome.RATE_LIMIT
        assert res.is_available is False
        assert res.status_code == 429
        assert res.organic_results == []


@pytest.mark.asyncio
async def test_missing_or_invalid_credentials():
    """5. Missing or invalid credentials returns AUTH_FAILURE immediately."""
    # Case A: Unconfigured API key (never calls network)
    client_empty = SerpApiClient(api_key="")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        res_empty = await client_empty.search("Google careers")
        assert res_empty.outcome == SearchOutcome.AUTH_FAILURE
        assert res_empty.status_code == 401
        assert res_empty.is_available is False
        mock_get.assert_not_called()

    # Case B: HTTP 401 Unauthorized
    client_bad = SerpApiClient(api_key="invalid_token", max_retries=1)
    mock_401 = MagicMock(spec=httpx.Response)
    mock_401.status_code = 401
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_401
        res_401 = await client_bad.search("Google careers")
        assert res_401.outcome == SearchOutcome.AUTH_FAILURE
        assert res_401.status_code == 401
        # Permanent failure must not be retried
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_http_provider_server_failure():
    """6. Upstream server failure (HTTP 500/503) returns PROVIDER_FAILURE."""
    client = SerpApiClient(api_key="valid_key", max_retries=1, retry_backoff=0.01)

    mock_503 = MagicMock(spec=httpx.Response)
    mock_503.status_code = 503
    mock_503.text = "Service Unavailable"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_503
        res = await client.search("Accenture careers")

        assert res.outcome == SearchOutcome.PROVIDER_FAILURE
        assert res.status_code == 503
        assert res.is_available is False


@pytest.mark.asyncio
async def test_serpapi_error_payload_with_http_200():
    """7. HTTP 200 with SerpApi error payload is properly recognized."""
    client = SerpApiClient(api_key="valid_key", max_retries=0)

    # Auth error in JSON
    mock_resp_auth = MagicMock(spec=httpx.Response)
    mock_resp_auth.status_code = 200
    mock_resp_auth.json.return_value = {"error": "Invalid API key."}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_auth
        res_auth = await client.search("TCS careers")
        assert res_auth.outcome == SearchOutcome.AUTH_FAILURE
        assert "invalid api key" in (res_auth.error or "").lower()

    # Rate limit in JSON
    mock_resp_rl = MagicMock(spec=httpx.Response)
    mock_resp_rl.status_code = 200
    mock_resp_rl.json.return_value = {"error": "Your account has run out of searches."}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_rl
        res_rl = await client.search("TCS careers")
        assert res_rl.outcome == SearchOutcome.RATE_LIMIT


@pytest.mark.asyncio
async def test_malformed_response():
    """8. Malformed or invalid response shapes return MALFORMED_RESPONSE."""
    client = SerpApiClient(api_key="valid_key", max_retries=0)

    # Non-JSON content
    mock_resp_bad_json = MagicMock(spec=httpx.Response)
    mock_resp_bad_json.status_code = 200
    mock_resp_bad_json.json.side_effect = ValueError("Invalid JSON")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_bad_json
        res_bad = await client.search("Query")
        assert res_bad.outcome == SearchOutcome.MALFORMED_RESPONSE

    # Non-dict JSON (e.g. JSON list)
    mock_resp_list = MagicMock(spec=httpx.Response)
    mock_resp_list.status_code = 200
    mock_resp_list.json.return_value = ["not", "a", "dict"]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_list
        res_list = await client.search("Query")
        assert res_list.outcome == SearchOutcome.MALFORMED_RESPONSE

    # organic_results is not a list
    mock_resp_invalid_field = MagicMock(spec=httpx.Response)
    mock_resp_invalid_field.status_code = 200
    mock_resp_invalid_field.json.return_value = {"organic_results": "invalid_string_not_list"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_invalid_field
        res_field = await client.search("Query")
        assert res_field.outcome == SearchOutcome.MALFORMED_RESPONSE


@pytest.mark.asyncio
async def test_transient_failure_followed_by_success():
    """9. Transient network failure followed by success recovers cleanly."""
    client = SerpApiClient(api_key="valid_key", max_retries=2, retry_backoff=0.01)

    mock_success = MagicMock(spec=httpx.Response)
    mock_success.status_code = 200
    mock_success.json.return_value = {
        "organic_results": [{"title": "Infosys", "link": "https://www.infosys.com"}],
        "knowledge_graph": {},
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # First call fails with transient ConnectTimeout, second call succeeds
        mock_get.side_effect = [
            httpx.ConnectTimeout("Connection dropped"),
            mock_success,
        ]

        res = await client.search("Infosys careers")
        assert res.outcome == SearchOutcome.SUCCESS
        assert mock_get.call_count == 2
        assert len(res.organic_results) == 1


@pytest.mark.asyncio
async def test_exhausted_retries():
    """10. Repeated transient failures exhaust retries and return failure."""
    client = SerpApiClient(api_key="valid_key", max_retries=2, retry_backoff=0.01)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Network unreachable")

        res = await client.search("Query")
        assert res.outcome == SearchOutcome.PROVIDER_FAILURE
        # Initial attempt + 2 retries = 3 calls total
        assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_permanent_failures_are_not_retried():
    """11. Permanent failures (HTTP 401, 403, 400) are never retried."""
    client = SerpApiClient(api_key="valid_key", max_retries=3, retry_backoff=0.01)

    mock_403 = MagicMock(spec=httpx.Response)
    mock_403.status_code = 403

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_403
        res = await client.search("Query")

        assert res.outcome == SearchOutcome.AUTH_FAILURE
        assert mock_get.call_count == 1  # Exactly 1 call, zero retries


# ===========================================================================
# 2. Agent & System Integration Regression Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_partial_success_across_multiple_checks():
    """12. Preserves evidence from successful checks when one external check fails."""
    # Mock client where company search succeeds but phone scam search times out
    class MockPartialClient:
        async def search(self, query: str, **kwargs):
            if "official website" in query:
                return SearchResult(
                    query=query,
                    provider="serpapi",
                    outcome=SearchOutcome.SUCCESS,
                    results=[{"title": "Wipro", "link": "https://www.wipro.com", "snippet": "Official site"}],
                    knowledge_graph={"website": "https://www.wipro.com"},
                )
            else:
                return SearchResult(
                    query=query,
                    provider="serpapi",
                    outcome=SearchOutcome.TIMEOUT,
                    error="Phone search timed out",
                )

    client = MockPartialClient()
    company_agent = CompanyAgent(search_client=client)
    recruiter_agent = RecruiterAgent(search_client=client)

    comp_finding = await company_agent.investigate("Wipro Limited")
    rec_finding = await recruiter_agent.investigate(
        company_name="Wipro Limited",
        recruiter_name="Anita",
        recruiter_email="anita@wipro.com",
        recruiter_phone="+919876543210",
    )

    # Company search succeeded and evidence is fully preserved
    assert comp_finding.verdict == "VERIFIED"
    assert len(comp_finding.evidence) > 0
    assert comp_finding.details.get("official_domain") == "https://www.wipro.com"

    # Phone check timed out and failure is reported honestly
    assert rec_finding.details.get("provider_status") == "FAILED"
    assert rec_finding.verdict == "CANNOT_VERIFY"


@pytest.mark.asyncio
async def test_provider_failure_does_not_trigger_fabricated_evidence_or_verification():
    """13. Provider failure produces no fake evidence and never confirms identity."""
    class FailingClient:
        async def search(self, query: str, **kwargs):
            return SearchResult(
                query=query,
                provider="serpapi",
                outcome=SearchOutcome.PROVIDER_FAILURE,
                error="SerpApi service down",
            )

    client = FailingClient()
    comp_agent = CompanyAgent(search_client=client)
    sal_agent = SalaryAgent(search_client=client)
    scam_agent = ScamAgent(search_client=client)

    comp_finding = await comp_agent.investigate("Unknown Startup Pvt Ltd")
    sal_finding = await sal_agent.investigate("Unknown Startup Pvt Ltd", "Engineer", "INR 6 LPA")
    scam_finding = await scam_agent.investigate("Unknown Startup Pvt Ltd", None, None, [], "Legitimate letter")

    # CompanyAgent produces empty evidence (no fake MCA URLs)
    assert comp_finding.verdict == "CANNOT_VERIFY"
    assert comp_finding.evidence == []
    assert comp_finding.details.get("provider_status") == "FAILED"

    # SalaryAgent produces empty evidence (no fake Ambitionbox baselines)
    assert sal_finding.verdict == "CANNOT_VERIFY"
    assert sal_finding.evidence == []
    assert sal_finding.details.get("provider_status") == "FAILED"

    # ScamAgent records provider failure honestly
    assert scam_finding.details.get("provider_status") == "FAILED"


def test_missing_evidence_does_not_independently_increase_fraud_risk():
    """14. Inconclusive coverage / missing evidence does not independently condemn an offer as fraud."""
    from app.services.risk.verdict_reasoner import VerdictReasoner

    reasoner = VerdictReasoner()

    # All checks inconclusive due to lack of public footprint or search outage
    comp = AgentFinding(
        agent_name="CompanyAgent",
        verdict="CANNOT_VERIFY",
        confidence=0.0,
        summary="External search unavailable due to provider outage",
        evidence=[],
    )
    rec = AgentFinding(
        agent_name="RecruiterAgent",
        verdict="CANNOT_VERIFY",
        confidence=0.0,
        summary="Recruiter verification incomplete: search unavailable",
        evidence=[],
    )
    sal = AgentFinding(
        agent_name="SalaryAgent",
        verdict="CANNOT_VERIFY",
        confidence=0.0,
        summary="Salary benchmark search unavailable",
        evidence=[],
    )
    scam = AgentFinding(
        agent_name="ScamAgent",
        verdict="VERIFIED",
        confidence=0.8,
        summary="No advance fee requests or known scam patterns detected",
        evidence=[],
    )

    # Neither empty search nor provider failure independently establishes fraud or confirms identity
    assert comp.verdict not in ("HIGH_RISK", "VERIFIED")
    assert rec.verdict not in ("HIGH_RISK", "VERIFIED")
    assert sal.verdict not in ("HIGH_RISK", "VERIFIED")

    # In the final verdict reasoning layer, missing evidence produces CANNOT_VERIFY, NOT HIGH_RISK
    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.30,
    )

    assert result.verdict == RiskLevel.CANNOT_VERIFY
    assert result.verdict != RiskLevel.HIGH_RISK


def test_sanitize_search_text():
    """Ensure API keys and credentials are never exposed in logs or errors."""
    text = "Error connecting to https://serpapi.com/search.json?q=test&api_key=secret_12345_token"
    sanitized = sanitize_search_text(text, api_key="secret_12345_token")
    assert "secret_12345_token" not in sanitized
    assert "[REDACTED]" in sanitized


@pytest.mark.asyncio
async def test_consumer_backwards_compatibility():
    """Ensure dictionary access patterns and property access patterns remain 100% compatible."""
    res = SearchResult(
        query="Infosys official website careers",
        provider="serpapi",
        outcome=SearchOutcome.SUCCESS,
        results=[{"title": "Infosys", "link": "https://www.infosys.com", "snippet": "Official site"}],
        knowledge_graph={"website": "https://www.infosys.com"},
    )

    # Direct dict indexing & get
    assert res.get("knowledge_graph") == {"website": "https://www.infosys.com"}
    assert res.get("organic_results")[0]["link"] == "https://www.infosys.com"
    assert res["source"] == SearchSource.REAL.value
    assert res["status"] == "successful"

    # Property access
    assert res.outcome == SearchOutcome.SUCCESS
    assert res.is_success is True
    assert res.is_available is True
    assert res.results[0]["title"] == "Infosys"
