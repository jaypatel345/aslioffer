"""Task 3 acceptance checks at provider, consumer, and scoring boundaries."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.schemas.analysis import AgentFinding, RiskLevel, ExtractedEntities
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.salary_agent import SalaryAgent
from app.services.agents.scam_agent import ScamAgent
from app.services.report.report_generator import ReportGenerator
from app.services.risk.risk_engine import RiskEngine
from app.services.risk.verdict_reasoner import VerdictReasoner
from app.services.search.serpapi_client import SerpApiClient, SearchOutcome, SearchResult


@pytest.fixture(autouse=True)
def offline_http(monkeypatch):
    """Fail closed if a test forgets to mock network requests; ignore host proxies."""
    for key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(httpx.AsyncClient, "get", AsyncMock(side_effect=AssertionError("Live network forbidden")))


class FixedSearch:
    def __init__(self, outcome):
        self.outcome = outcome

    async def search(self, query, **kwargs):
        return SearchResult(query=query, outcome=self.outcome,
                            error="Provider unavailable" if self.outcome not in (SearchOutcome.SUCCESS, SearchOutcome.ZERO_RESULTS) else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [SearchOutcome.ZERO_RESULTS, SearchOutcome.TIMEOUT, SearchOutcome.AUTH_FAILURE,
                                    SearchOutcome.RATE_LIMIT, SearchOutcome.PROVIDER_FAILURE])
async def test_unavailable_or_empty_investigation_uses_real_scoring(outcome):
    client = FixedSearch(outcome)
    findings = [
        await CompanyAgent(client).investigate("Example Ltd"),
        await RecruiterAgent(client).investigate("Example Ltd", None, "hr@example.com", "9876543210"),
        await SalaryAgent(client).investigate("Example Ltd", "Engineer", "6 LPA"),
        await ScamAgent(client).investigate("Example Ltd", None, None, [], "Welcome. Your role is engineer."),
    ]
    assert all(f.verdict == "CANNOT_VERIFY" for f in findings[:3])
    assert all(f.evidence == [] for f in findings)
    if outcome != SearchOutcome.ZERO_RESULTS:
        assert findings[3].verdict == "CANNOT_VERIFY"
    score, level, red, green = RiskEngine().compute_risk(findings)
    final = VerdictReasoner().evaluate(*findings, initial_risk_score=score, initial_risk_level=level)
    assert score < 0.25
    assert level == final.verdict == RiskLevel.CANNOT_VERIFY
    assert red == []
    assert not any("Recruiter credentials" in flag for flag in green)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [SearchOutcome.ZERO_RESULTS, SearchOutcome.TIMEOUT])
async def test_local_fee_signal_survives_unavailable_search(outcome):
    finding = await ScamAgent(FixedSearch(outcome)).investigate(
        "Example Ltd", "registration fee", None, [], "Pay a registration fee before joining.")
    assert finding.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]
    assert finding.evidence
    assert all(e.source_url == "document://submitted-offer" for e in finding.evidence)
    assert not any("regulations" in e.description for e in finding.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [SearchOutcome.ZERO_RESULTS, SearchOutcome.TIMEOUT])
async def test_salary_document_anomaly_survives_without_fake_benchmark(outcome):
    finding = await SalaryAgent(FixedSearch(outcome)).investigate("Example Ltd", "Data Entry", "50,000 per day")
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.details["anomaly"] is True
    assert finding.evidence == []
    assert "benchmark_range" not in finding.details


@pytest.mark.asyncio
async def test_adverse_phone_evidence_survives_company_outage():
    class PartialSearch:
        async def search(self, query, **kwargs):
            if "official website" in query:
                return SearchResult(query=query, outcome=SearchOutcome.TIMEOUT, error="Timed out")
            return SearchResult(query=query, results=[{
                "title": "Fraud complaint 9876543210", "snippet": "Scam report naming 9876543210",
                "link": "https://reports.example/complaint"}])

    finding = await RecruiterAgent(PartialSearch()).investigate("Example Ltd", None, "hr@example.com", "9876543210")
    assert finding.verdict == "HIGH_RISK"
    assert finding.details["phone_flagged"] is True
    assert finding.details["domain_match"] is None
    assert finding.details["provider_status"] == "PARTIAL"
    assert finding.details["checks"]["company_domain"]["search_status"] == "TIMEOUT"
    assert finding.evidence[0].source_url == "https://reports.example/complaint"


@pytest.mark.asyncio
async def test_domain_mismatch_survives_phone_outage():
    class PartialSearch:
        async def search(self, query, **kwargs):
            if "official website" in query:
                return SearchResult(query=query, knowledge_graph={"title": "Example Ltd", "website": "https://example.com"},
                    results=[{"title": "Example Ltd", "link": "https://example.com", "snippet": "Company website"}])
            return SearchResult(query=query, outcome=SearchOutcome.TIMEOUT, error="Timed out")
    finding = await RecruiterAgent(PartialSearch()).investigate("Example Ltd", None, "hr@other.example", "9876543210")
    assert finding.verdict == "HIGH_RISK"
    assert finding.details["domain_match"] is False
    assert finding.details["provider_status"] == "PARTIAL"
    assert finding.evidence


@pytest.mark.asyncio
async def test_unsupported_knowledge_graph_without_identity_remains_unresolved():
    """Knowledge graph website without matching title must remain unresolved (domain_match is None)."""
    class PartialSearch:
        async def search(self, query, **kwargs):
            if "official website" in query:
                return SearchResult(query=query, knowledge_graph={"website": "https://example.com"})
            return SearchResult(query=query, outcome=SearchOutcome.TIMEOUT, error="Timed out")
    finding = await RecruiterAgent(PartialSearch()).investigate("Example Ltd", None, "hr@other.example", "9876543210")
    assert finding.details["domain_match"] is None



@pytest.mark.asyncio
async def test_free_webmail_signal_survives_phone_outage():
    finding = await RecruiterAgent(FixedSearch(SearchOutcome.TIMEOUT)).investigate(
        "Example Ltd", None, "hr@gmail.com", "9876543210")
    assert finding.verdict == "HIGH_RISK"
    assert finding.details["is_free_email"] is True
    assert finding.details["provider_status"] == "FAILED"


@pytest.mark.asyncio
async def test_scam_partial_search_preserves_retrieved_evidence():
    class PartialSearch:
        async def search(self, query, **kwargs):
            if '"registration fee"' in query:
                return SearchResult(query=query, outcome=SearchOutcome.TIMEOUT, error="Timed out")
            return SearchResult(query=query, results=[{
                "title": "Example Ltd recruitment advisory", "link": "https://reports.example/advisory",
                "snippet": "Check recruitment contacts independently."}])
    finding = await ScamAgent(PartialSearch()).investigate(
        "Example Ltd", "registration fee", None, [], "Pay registration fee.")
    assert finding.verdict == "HIGH_RISK"
    assert finding.details["provider_status"] == "PARTIAL"
    assert finding.details["checks"]["payment_reports"]["search_status"] == "TIMEOUT"
    assert any(e.source_url == "https://reports.example/advisory" for e in finding.evidence)


@pytest.mark.asyncio
async def test_successful_phone_search_is_not_identity_verification():
    finding = await RecruiterAgent(FixedSearch(SearchOutcome.ZERO_RESULTS)).investigate(
        "Example Ltd", None, None, "9876543210")
    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details["checks"]["phone_reports"]["identity_verified"] is False
    assert finding.evidence == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"organic_results": [None]}, {"organic_results": ["invalid"]},
    {"organic_results": [{"title": 7, "link": "https://example.com"}]},
    {"organic_results": [{"title": "Example", "link": ["https://example.com"]}]},
    {"organic_results": [{"title": "Example", "link": "javascript:alert(1)"}]},
    {"organic_results": [{"title": "Example", "link": "https://example.com", "snippet": []}]},
    {"knowledge_graph": {"website": ["https://example.com"]}},
    {"knowledge_graph": {"careers_url": 42}}, {"search_metadata": []},
    {"search_information": {"total_results": "0"}}, {"search_metadata": {"status": []}},
])
async def test_malformed_consumed_fields_never_reach_agents(payload):
    response = httpx.Response(200, json=payload)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as request:
        result = await SerpApiClient(api_key="test_key", max_retries=2).search("Example")
    assert result.outcome == SearchOutcome.MALFORMED_RESPONSE
    assert request.call_count == 1
    replay = type("Replay", (), {"search": AsyncMock(return_value=result)})()
    finding = await CompanyAgent(replay).investigate("Example")
    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.evidence == []


@pytest.mark.asyncio
async def test_empty_information_is_read_even_when_metadata_exists():
    payload = {"search_metadata": {"status": "Success"},
               "search_information": {"total_results": 0, "organic_results_state": "Fully empty"}}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=httpx.Response(200, json=payload)):
        result = await SerpApiClient(api_key="test_key").search("Example")
    assert result.outcome == SearchOutcome.ZERO_RESULTS
    assert result.is_available


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"search_metadata": {"status": "Success"}}])
async def test_missing_result_shape_is_not_an_empty_search(payload):
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=httpx.Response(200, json=payload)):
        result = await SerpApiClient(api_key="test_key").search("Example")
    assert result.outcome == SearchOutcome.MALFORMED_RESPONSE


@pytest.mark.asyncio
async def test_total_deadline_bounds_slow_requests_and_cancels_them():
    cancelled = asyncio.Event()
    async def slow_request(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    client = SerpApiClient(api_key="test_key", timeout=8, total_timeout=0.03, max_retries=2)
    with patch("httpx.AsyncClient.get", side_effect=slow_request) as request:
        result = await asyncio.wait_for(client.search("Example"), timeout=1)
    assert result.outcome == SearchOutcome.TIMEOUT
    assert cancelled.is_set()
    assert request.call_count == 1


@pytest.mark.asyncio
async def test_total_deadline_bounds_retry_sleep():
    response = httpx.Response(503)
    client = SerpApiClient(api_key="test_key", total_timeout=0.03, retry_backoff=1, max_retries=2)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as request:
        result = await asyncio.wait_for(client.search("Example"), timeout=1)
    assert result.outcome == SearchOutcome.TIMEOUT
    assert request.call_count == 1


@pytest.mark.asyncio
async def test_caller_cancellation_is_not_swallowed():
    entered = asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    with patch("httpx.AsyncClient.get", side_effect=blocked):
        task = asyncio.create_task(SerpApiClient(api_key="test_key").search("Example"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["10", format_datetime(datetime.now(timezone.utc) + timedelta(minutes=5), usegmt=True)])
async def test_long_retry_after_is_not_ignored(header):
    response = httpx.Response(429, headers={"Retry-After": header})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as request:
        result = await SerpApiClient(api_key="test_key").search("Example")
    assert result.outcome == SearchOutcome.RATE_LIMIT
    assert request.call_count == 1


@pytest.mark.asyncio
async def test_short_retry_after_then_success():
    responses = [httpx.Response(429, headers={"Retry-After": "0.01"}),
                 httpx.Response(200, json={"organic_results": []})]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=responses) as request:
        result = await SerpApiClient(api_key="test_key").search("Example")
    assert result.outcome == SearchOutcome.ZERO_RESULTS
    assert request.call_count == 2


@pytest.mark.asyncio
async def test_transient_error_payload_can_recover():
    responses = [httpx.Response(200, json={"error": "Service temporarily unavailable. Try again."}),
                 httpx.Response(200, json={"organic_results": []})]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=responses) as request:
        result = await SerpApiClient(api_key="test_key", retry_backoff=0).search("Example")
    assert result.outcome == SearchOutcome.ZERO_RESULTS
    assert request.call_count == 2


@pytest.mark.asyncio
async def test_demo_requires_explicit_flag_and_cannot_supply_live_evidence():
    live = await SerpApiClient(api_key="mock_key", demo_mode=False).search("Example scam", fallback_to_mock=True)
    assert live.outcome == SearchOutcome.AUTH_FAILURE
    assert live.results == []
    demo = await SerpApiClient(api_key="", demo_mode=True).search("Example scam")
    assert demo["source"] == "DEMO"
    assert demo.results
    assert not demo.is_live
    replay = type("Replay", (), {"search": AsyncMock(return_value=demo)})()
    findings = [await CompanyAgent(replay).investigate("Example"),
                await RecruiterAgent(replay).investigate("Example", None, "hr@example.com", None),
                await SalaryAgent(replay).investigate("Example", "Engineer", "6 LPA"),
                await ScamAgent(replay).investigate("Example", None, None, [], "Welcome to your new role.")]
    assert all(f.verdict == "CANNOT_VERIFY" and f.evidence == [] for f in findings)


@pytest.mark.asyncio
async def test_query_and_provider_error_do_not_leak_private_data(caplog):
    caplog.set_level(logging.INFO)
    query = '"private.person@example.com" "9876543210" sensitive-offer-fragment'
    key = "secret_key_12345"
    payload = {"error": f"Failure at https://serpapi.com/search?q={query}&api_key={key}"}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=httpx.Response(200, json=payload)):
        result = await SerpApiClient(api_key=key, max_retries=0).search(query)
    for value in ("private.person@example.com", "9876543210", "sensitive-offer-fragment", key, "https://serpapi.com"):
        assert value not in caplog.text
        assert value not in (result.error or "")
    assert result.query == query  # Internal query provenance is preserved, not logged.


@pytest.mark.asyncio
async def test_private_contacts_are_not_logged_by_recruiter_agent(caplog):
    caplog.set_level(logging.INFO)
    await RecruiterAgent(FixedSearch(SearchOutcome.TIMEOUT)).investigate(
        "Example", None, "private.person@example.com", "9876543210")
    assert "private.person@example.com" not in caplog.text
    assert "9876543210" not in caplog.text


@pytest.mark.asyncio
async def test_raw_request_metadata_is_not_retained():
    payload = {"organic_results": [], "search_metadata": {
        "status": "Success", "raw_html_file": "https://provider.example?api_key=secret_key"}}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=httpx.Response(200, json=payload)):
        result = await SerpApiClient(api_key="secret_key").search("Example")
    assert "secret_key" not in str(result)
    assert "raw_response" not in result


def test_inconclusive_identity_cannot_be_overridden_by_many_unrelated_sources():
    from app.schemas.analysis import EvidenceItem
    evidence = [EvidenceItem(source_url=f"https://source.example/{i}", title="Company record",
                description="Company information", evidence_type="COMPANY", confidence=0.95) for i in range(4)]
    comp = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.95, summary="Company footprint found", evidence=evidence)
    rec = AgentFinding(agent_name="RecruiterAgent", verdict="CANNOT_VERIFY", confidence=0, summary="Identity unavailable")
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.9, summary="Salary source found")
    scam = AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.9, summary="Local scan completed")
    score, level, red, _ = RiskEngine().compute_risk([comp, rec, sal, scam])
    result = VerdictReasoner().evaluate(comp, rec, sal, scam, score, level)
    assert result.verdict == RiskLevel.CANNOT_VERIFY
    assert red == []


@pytest.mark.asyncio
async def test_http_client_setup_failure_is_reported_without_exception_details(caplog):
    caplog.set_level(logging.INFO)
    with patch("httpx.AsyncClient", side_effect=RuntimeError("private.person@example.com secret-setup-value")):
        result = await SerpApiClient(api_key="test_key").search("Example")
    assert result.outcome == SearchOutcome.PROVIDER_FAILURE
    assert "secret-setup-value" not in caplog.text + result.error
    assert "private.person@example.com" not in caplog.text + result.error


def test_report_does_not_describe_outage_as_sparse_footprint():
    report = ReportGenerator().generate(
        offer_id=1, title="Offer", risk_score=0.05, risk_level=RiskLevel.CANNOT_VERIFY,
        extracted_entities=ExtractedEntities(company_name="Example Ltd"), findings=[], red_flags=[], green_flags=[])
    assert "unavailable" in report.summary
    assert "sparse" not in report.summary
    assert report.official_company_info["mca_status"] == "Not independently checked"


@pytest.mark.parametrize("response", [{}, {"status": "successful"},
    {"outcome": "unknown", "organic_results": []},
    {"organic_results": None, "results": [None]}])
def test_legacy_adapter_does_not_turn_invalid_shapes_into_completed_searches(response):
    result = SearchResult.from_dict_or_result(response)
    assert result.outcome == SearchOutcome.MALFORMED_RESPONSE
    assert not result.is_available
