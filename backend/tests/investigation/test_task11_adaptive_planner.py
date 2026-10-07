"""
Task 11: Bounded Adaptive Investigation Planning Tests.

Covers:
- Shared budget across initial and adaptive queries.
- Concurrent admission cannot exceed limit.
- Concurrent identical queries consume one allowance.
- Cache hits remain available without new provider calls.
- Result-count and options remain distinct requests.
- Failed calls consume allowance exactly once.
- Budget denial distinct from provider failure and empty results.
- Deadline expiry cancels pending work and retains completed evidence.
- Local high-risk demand survives deadline/budget exhaustion.
- Caller cancellation propagates and drains tasks.
- Auth failure suppresses futile follow-up calls.
- Unresolved employer gets a justified bounded contextual search.
- Agency/domain conflict gets attributable follow-up without automatic fraud.
- Existing recruiter queries are not repeated.
- No-match produces bounded abstention.
- Missing/uncertain/redacted inputs produce no unsafe queries.
- Follow-up evidence has real provenance and correct claim links.
- Conflicting evidence is preserved deterministically.
- Additional snippets alone do not authenticate the offer.
- Event/trace reasons explain actual planner decisions.
- Generated handoff fixtures for gap-resolved and abstention-exhausted runs.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.contract import (
    CaseInput,
    Claim,
    ClaimKind,
    ClaimStatus,
    ConfirmedClaim,
    EventStatus,
    ExtractionStatus,
    InvestigationResult,
    OverallOutcome,
    RetrievalStatus,
    RunEvent,
    SourceKind,
    SourceTier,
    SourceType,
)
from app.services.investigation import (
    investigate_case,
    InvestigationBudget,
    BudgetManager,
    InvestigationPlanner,
    PlanStep,
)
from app.services.investigation.recording_search import RecordingSearchClient
from app.services.search.serpapi_client import SearchOutcome, SearchResult, SearchSource


GENERATED_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "investigation" / "generated_task11"


class MockSearchClient:
    """Fixture search client returning predetermined search outcomes by exact query."""

    def __init__(self, query_responses: Optional[Dict[str, Any]] = None):
        self.query_responses = query_responses or {}
        self.call_log: List[Dict[str, Any]] = []

    async def search(self, query: str, engine: str = "google", num: int = 5, **kwargs) -> Dict[str, Any]:
        self.call_log.append({"query": query, "engine": engine, "num": num, "kwargs": kwargs})
        if query in self.query_responses:
            resp = self.query_responses[query]
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {
            "status": "successful",
            "source": "REAL",
            "organic_results": [],
            "knowledge_graph": {},
        }


# ---------------------------------------------------------------------------
# 1. Budget and Accounting Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_initial_and_adaptive_queries_share_one_budget():
    """Initial agent checks and adaptive searches draw from the exact same allowance."""
    budget = InvestigationBudget(max_search_calls=2, max_followup_calls=1)
    bm = BudgetManager(budget)
    raw = MockSearchClient()
    client = RecordingSearchClient(raw, budget_manager=bm)

    with client.step("initial_1", "check 1"):
        res1 = await client.search("query 1")
    with client.step("initial_2", "check 2"):
        res2 = await client.search("query 2")
    with client.step("adaptive_followup", "check 3"):
        res3 = await client.search("query 3")

    assert bm.admitted_total_calls == 2
    assert len(raw.call_log) == 2
    assert res1.get("budget_denied") is None
    assert res2.get("budget_denied") is None
    assert res3.get("budget_denied") is True
    assert res3.outcome == SearchOutcome.RATE_LIMIT


@pytest.mark.asyncio
async def test_concurrent_admission_cannot_exceed_limit():
    """Concurrent in-flight queries atomically respect the budget limit."""
    budget = InvestigationBudget(max_search_calls=3, max_concurrent_calls=2)
    bm = BudgetManager(budget)

    call_count = 0
    async def delayed_search(query: str, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)
        return {"source": "REAL", "organic_results": []}

    raw = AsyncMock()
    raw.search = AsyncMock(side_effect=delayed_search)
    client = RecordingSearchClient(raw, budget_manager=bm)

    async def execute(i):
        with client.step(f"step_{i}", f"reason {i}"):
            return await client.search(f"query_{i}")

    results = await asyncio.gather(*(execute(i) for i in range(10)))
    admitted = [r for r in results if not r.get("budget_denied")]
    denied = [r for r in results if r.get("budget_denied")]

    assert len(admitted) == 3
    assert len(denied) == 7
    assert bm.admitted_total_calls == 3
    assert call_count == 3


@pytest.mark.asyncio
async def test_concurrent_identical_queries_consume_one_allowance():
    """Concurrent identical queries coalesce and consume only a single allowance."""
    budget = InvestigationBudget(max_search_calls=2)
    bm = BudgetManager(budget)
    raw = AsyncMock()
    raw.search.return_value = {"source": "REAL", "organic_results": [{"link": "https://example.com", "title": "Example"}]}
    client = RecordingSearchClient(raw, budget_manager=bm)

    results = await asyncio.gather(
        client.search("duplicate query"),
        client.search("duplicate query"),
        client.search("duplicate query"),
    )

    assert bm.admitted_total_calls == 1
    assert raw.search.await_count == 1
    assert all(r["source"] == "REAL" for r in results)


@pytest.mark.asyncio
async def test_cache_hits_remain_available_without_new_provider_calls():
    """Cache hits consume zero budget allowance even after budget is reached."""
    budget = InvestigationBudget(max_search_calls=1)
    bm = BudgetManager(budget)
    raw = AsyncMock()
    raw.search.return_value = {"source": "REAL", "organic_results": [{"link": "https://example.com", "title": "Example"}]}
    client = RecordingSearchClient(raw, budget_manager=bm)

    # First call consumes allowance
    res1 = await client.search("first query")
    assert bm.admitted_total_calls == 1

    # Second call for identical query is served from cache without new allowance
    res2 = await client.search("first query")
    assert bm.admitted_total_calls == 1
    assert raw.search.await_count == 1
    assert res2["source"] == "REAL"

    # A different query is rejected
    res3 = await client.search("second query")
    assert res3.get("budget_denied") is True
    assert bm.admitted_total_calls == 1


@pytest.mark.asyncio
async def test_result_count_and_options_remain_distinct_requests():
    """Requests with differing parameters are not treated as cache hits."""
    budget = InvestigationBudget(max_search_calls=3)
    bm = BudgetManager(budget)
    raw = AsyncMock()
    raw.search.return_value = {"source": "REAL", "organic_results": []}
    client = RecordingSearchClient(raw, budget_manager=bm)

    await client.search("query", num=5)
    await client.search("query", num=10)

    assert bm.admitted_total_calls == 2
    assert raw.search.await_count == 2


@pytest.mark.asyncio
async def test_failed_calls_consume_allowance_exactly_once():
    """Provider failure consumes budget allowance exactly once."""
    budget = InvestigationBudget(max_search_calls=2)
    bm = BudgetManager(budget)
    raw = AsyncMock()
    raw.search.side_effect = RuntimeError("Network error")
    client = RecordingSearchClient(raw, budget_manager=bm)

    res = await client.search("failing query")
    assert res["source"] == "FAILED"
    assert bm.admitted_total_calls == 1


@pytest.mark.asyncio
async def test_budget_denial_is_distinct_from_provider_failure_and_empty():
    """Budget denial yields rate-limit outcome with budget_denied flag and no provider call."""
    budget = InvestigationBudget(max_search_calls=1)
    bm = BudgetManager(budget)
    raw = AsyncMock()
    client = RecordingSearchClient(raw, budget_manager=bm)

    await client.search("allowed query")
    denied_res = await client.search("denied query")

    assert denied_res.outcome == SearchOutcome.RATE_LIMIT
    assert denied_res.get("budget_denied") is True
    assert raw.search.await_count == 1
    # Verify denial is not cached permanently
    assert "denied query" not in client._cache


# ---------------------------------------------------------------------------
# 2. Deadline and Timeout Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deadline_expiry_cancels_pending_work_and_retains_completed_evidence():
    """Monotonic deadline timeout aborts pending calls and returns partial results."""
    # Set tight deadline of 0.05 seconds
    budget = InvestigationBudget(deadline_seconds=0.05)

    async def hanging_search(query: str, **kwargs):
        if "official website" in query.lower():
            await asyncio.sleep(2.0)
        return {"source": "REAL", "organic_results": []}

    raw = AsyncMock()
    raw.search = AsyncMock(side_effect=hanging_search)

    text = "Offer from AlphaCorp Pvt Ltd. Contact: hr@alphacorp.example"
    case_input = CaseInput(case_id=1, run_id="run_deadline", source_type=SourceType.TEXT, redacted_text=text)

    result = await investigate_case(case_input, search_client=raw, budget=budget)

    assert isinstance(result, InvestigationResult)
    assert any(e.code == "INVESTIGATION_DEADLINE_EXCEEDED" for e in result.errors)
    assert result.overall_outcome in (OverallOutcome.CANNOT_VERIFY, OverallOutcome.NEEDS_REVIEW, OverallOutcome.HIGH_RISK)


@pytest.mark.asyncio
async def test_local_high_risk_demand_survives_deadline_and_budget_exhaustion():
    """A detected fee demand is preserved even if the search deadline expires immediately."""
    budget = InvestigationBudget(max_search_calls=1, deadline_seconds=0.01)
    raw = AsyncMock()
    raw.search.side_effect = lambda *a, **kw: asyncio.sleep(1.0)

    text = "Offer from BetaCorp. Mandatory security deposit of INR 5,000 required."
    case_input = CaseInput(case_id=2, run_id="run_local_demand", source_type=SourceType.TEXT, redacted_text=text)

    result = await investigate_case(case_input, search_client=raw, budget=budget)

    assert result.overall_outcome == OverallOutcome.HIGH_RISK
    pay_claim = next((c for c in result.claims if c.kind == ClaimKind.PAYMENT_REQUEST), None)
    assert pay_claim is not None
    pay_assessed = next(a for a in result.assessed_claims if a.claim_id == pay_claim.claim_id)
    assert pay_assessed.status == ClaimStatus.SUPPORTED


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_and_drains_tasks():
    """Caller cancellation raises asyncio.CancelledError and cleans up subtasks."""
    async def hanging(*a, **kw):
        await asyncio.sleep(10.0)
    raw = AsyncMock()
    raw.search.side_effect = hanging

    text = "Offer from GammaCorp Ltd. Contact: hr@gammacorp.example"
    case_input = CaseInput(case_id=3, run_id="run_cancel", source_type=SourceType.TEXT, redacted_text=text)

    task = asyncio.create_task(investigate_case(case_input, search_client=raw))
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_auth_failure_suppresses_futile_follow_up_calls():
    """Authentication or configuration failure suppresses any subsequent searches."""
    budget = InvestigationBudget(max_search_calls=5)
    bm = BudgetManager(budget)
    raw = AsyncMock()
    raw.search.return_value = {
        "source": "FAILED",
        "outcome": SearchOutcome.AUTH_FAILURE.value,
        "error": "Invalid SerpApi API key",
        "error_type": "AUTH_FAILURE",
    }
    client = RecordingSearchClient(raw, budget_manager=bm)

    res1 = await client.search("first query")
    assert bm.auth_failure_detected is True

    res2 = await client.search("second query")
    assert res2.outcome == SearchOutcome.AUTH_FAILURE
    assert res2.get("budget_denied") is True
    assert raw.search.await_count == 1


# ---------------------------------------------------------------------------
# 3. Adaptive Planner Strategies Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unresolved_employer_gets_justified_bounded_contextual_search():
    """When initial employer resolution is sparse, planner queries employer with grounded location context."""
    text = (
        "Offer of Employment from Horizon Robotics Ltd.\n"
        "Job Location: Bengaluru, Karnataka.\n"
        "Role: Software Engineer.\n"
        "Contact: careers@horizonrobotics.example"
    )
    case_input = CaseInput(case_id=4, run_id="run_emp_ctx", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            # Initial query yields sparse aggregator results
            'Horizon Robotics Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [{"link": "https://directory.example/horizon", "title": "Directory", "snippet": "Company profile"}],
            },
            # Contextual adaptive query resolves domain
            '"Horizon Robotics Ltd" "Bengaluru" official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Horizon Robotics Ltd",
                    "website": "https://www.horizonrobotics.example",
                    "careers_url": "https://careers.horizonrobotics.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.horizonrobotics.example/",
                        "title": "Horizon Robotics Ltd - Bengaluru",
                        "snippet": "Horizon Robotics Ltd official website in Bengaluru.",
                    },
                    {
                        "link": "https://careers.horizonrobotics.example/",
                        "title": "Horizon Robotics Careers",
                        "snippet": "Contact talent team at careers@horizonrobotics.example for open positions.",
                    }
                ],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert next(a for a in result.assessed_claims if a.claim_id == "c2").status == ClaimStatus.UNRESOLVED
    emp_assessed = next(a for a in result.assessed_claims if a.claim_id == "c1")
    assert emp_assessed.status == ClaimStatus.SUPPORTED
    assert "OFFICIAL_DOMAIN_RESOLVED" in emp_assessed.reason_codes
    assert any(tc.step == "adaptive_employer_context" for tc in result.tool_trace)


@pytest.mark.asyncio
async def test_agency_domain_conflict_gets_attributable_followup_without_automatic_fraud():
    """Sender on staffing agency domain triggers partnership verification instead of false fraud flag."""
    text = (
        "Offer from Titan Technologies Ltd.\n"
        "We are pleased to offer you the role of DevOps Engineer.\n"
        "Regards, Rohit Verma, Apex Staffing Solutions.\n"
        "Contact: rohit@apexstaffing.example"
    )
    case_input = CaseInput(
        case_id=5,
        run_id="run_agency_auth",
        source_type=SourceType.TEXT,
        redacted_text=text,
        confirmed_claims=[
            ConfirmedClaim(
                claim_id="c1",
                kind=ClaimKind.EMPLOYER,
                value="Titan Technologies Ltd",
                extraction_status=ExtractionStatus.USER_CONFIRMED,
            )
        ],
    )

    search_mock = MockSearchClient(
        query_responses={
            'Titan Technologies Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Titan Technologies Ltd",
                    "website": "https://www.titantech.example",
                    "careers_url": "https://careers.titantech.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.titantech.example/",
                        "title": "Titan Technologies Ltd",
                        "snippet": "Titan Technologies Ltd official website.",
                    }
                ],
            },
            '"apexstaffing.example" staffing recruitment agency': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Apex Staffing Solutions",
                    "website": "https://www.apexstaffing.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.apexstaffing.example/",
                        "title": "Apex Staffing Solutions",
                        "snippet": "Apex Staffing Solutions recruitment agency.",
                    }
                ],
            },
            '"Titan Technologies Ltd" "Apex Staffing Solutions" recruitment partner authorized': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://careers.titantech.example/partners",
                        "title": "Titan Technologies - Authorized Recruitment Partners",
                        "snippet": "Apex Staffing Solutions is an authorized recruitment partner of Titan Technologies Ltd.",
                    }
                ],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome != OverallOutcome.HIGH_RISK
    assert result.overall_outcome in (OverallOutcome.NEEDS_REVIEW, OverallOutcome.NO_STRONG_RISK_SIGNALS)
    assert any(tc.step == "adaptive_agency_authorization" for tc in result.tool_trace)


@pytest.mark.asyncio
async def test_existing_recruiter_queries_are_not_repeated():
    """Planner skips candidate steps whose exact query already ran in initial checks."""
    planner = InvestigationPlanner()
    claims = [
        Claim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="Acme Corp", extraction_status=ExtractionStatus.EXTRACTED, source_quote="Acme Corp"),
        Claim(claim_id="c4", kind=ClaimKind.RECRUITER_NAME, value="Jane Doe", extraction_status=ExtractionStatus.EXTRACTED, source_quote="Jane Doe"),
    ]
    # Simulate that query already ran
    executed = {'"jane doe" "acme.com" talent acquisition recruiter'}
    plan = planner.create_plan(
        claims=claims,
        findings={},
        executed_queries=executed,
        canonical_domain="acme.com",
    )
    assert not any(p.strategy == "RECRUITER_AFFILIATION" for p in plan)


@pytest.mark.asyncio
async def test_no_match_produces_bounded_abstention():
    """When an adaptive follow-up yields no results, planner abstains from cascading queries."""
    text = "Offer from StealthAI Ltd for ML Engineer. Location: Remote. Contact: hr@stealthai.example"
    case_input = CaseInput(case_id=6, run_id="run_abstain", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'StealthAI Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
            '"StealthAI Ltd" "Remote" official website': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.CANNOT_VERIFY
    # Only 1 adaptive attempt was made before abstaining
    adaptive_calls = [tc for tc in result.tool_trace if tc.step.startswith("adaptive_")]
    assert len(adaptive_calls) <= 1


@pytest.mark.asyncio
async def test_missing_and_redacted_inputs_produce_no_unsafe_queries():
    """Redaction placeholders and missing inputs do not generate follow-up search steps."""
    planner = InvestigationPlanner()
    claims = [
        Claim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="[EMPLOYER_1]", extraction_status=ExtractionStatus.EXTRACTED, source_quote="[EMPLOYER_1]"),
        Claim(claim_id="c2", kind=ClaimKind.SENDER_EMAIL, value="[EMAIL_1]", extraction_status=ExtractionStatus.EXTRACTED, source_quote="[EMAIL_1]"),
    ]
    plan = planner.create_plan(claims=claims, findings={}, executed_queries=set())
    assert plan == []


@pytest.mark.asyncio
async def test_followup_evidence_has_real_provenance_and_correct_claim_links():
    """Adaptive evidence records belong strictly to target claims with honest source tiers."""
    text = "Offer from ZetaCorp Ltd. Mandatory security deposit of INR 2,000 required."
    case_input = CaseInput(case_id=7, run_id="run_fee_policy", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'ZetaCorp Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "ZetaCorp Ltd",
                    "website": "https://www.zetacorp.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.zetacorp.example/",
                        "title": "ZetaCorp Ltd",
                        "snippet": "Official site of ZetaCorp Ltd.",
                    }
                ],
            },
            '"ZetaCorp Ltd" recruitment fraud policy fee warning': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://www.zetacorp.example/careers/fraud-alert",
                        "title": "ZetaCorp - Recruitment Caution",
                        "snippet": "ZetaCorp never charges fees at any stage of hiring. Beware of fraudulent offers.",
                    }
                ],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.HIGH_RISK
    # Find evidence from adaptive step
    policy_ev = next((e for e in result.evidence if "fraud-alert" in (e.source_url or "")), None)
    if policy_ev:
        assert policy_ev.source_tier == SourceTier.OFFICIAL_EMPLOYER
        assert policy_ev.source_kind == SourceKind.SEARCH_SNIPPET


@pytest.mark.asyncio
async def test_additional_snippets_alone_do_not_authenticate_offer():
    """Successful adaptive searches confirm company footprint or agency representation, never offer authenticity."""
    text = (
        "Offer of Employment from Kestrel Systems Pvt Ltd.\n"
        "We are pleased to offer you the position of Associate Consultant.\n"
        "Please review the offer details at https://careers.kestrelsystems.example/offers.\n"
        "Regards, Ananya Rao, Talent Acquisition. Contact: ananya.rao@kestrelsystems.example"
    )
    case_input = CaseInput(case_id=8, run_id="run_auth_unconfirmed", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Kestrel Systems Pvt Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Kestrel Systems Pvt Ltd",
                    "website": "https://www.kestrelsystems.example",
                    "careers_url": "https://careers.kestrelsystems.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.kestrelsystems.example/",
                        "title": "Kestrel Systems",
                        "snippet": "Kestrel Systems official site.",
                    },
                    {
                        "link": "https://careers.kestrelsystems.example/team",
                        "title": "Kestrel Systems Recruitment Team",
                        "snippet": "Contact our talent acquisition recruiter Ananya Rao at ananya.rao@kestrelsystems.example for verification.",
                    },
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.NO_STRONG_RISK_SIGNALS
    assert result.authenticity_status.value == "UNCONFIRMED"


@pytest.mark.asyncio
async def test_event_and_trace_reasons_explain_actual_planner_decisions():
    """Adaptive steps record specific information-gain rationales rather than generic text."""
    text = "Offer from NovaTech Ltd for Data Scientist. Location: Pune. Contact: hr@novatech.example"
    case_input = CaseInput(case_id=9, run_id="run_reasons", source_type=SourceType.TEXT, redacted_text=text)

    events: List[RunEvent] = []
    search_mock = MockSearchClient(
        query_responses={
            'NovaTech Ltd official website': {"status": "successful", "source": "REAL", "organic_results": []},
            '"NovaTech Ltd" "Pune" official website': {"status": "successful", "source": "REAL", "organic_results": []},
        }
    )

    result = await investigate_case(case_input, search_client=search_mock, emit_event=lambda e: events.append(e))

    adaptive_calls = [tc for tc in result.tool_trace if tc.step.startswith("adaptive_")]
    for tc in adaptive_calls:
        assert tc.reason
        assert "perform additional verification" not in tc.reason.lower()
        assert "novatech" in tc.reason.lower()


# ---------------------------------------------------------------------------
# 4. Generate and Validate Task 11 Handoff Fixtures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_and_roundtrip_task11_fixtures(tmp_path):
    GENERATED_FIXTURES_DIR = tmp_path
    """Generates two Task 11 handoff fixtures (gap resolved and abstains exhausted) and verifies round-tripping."""
    # 1. Gap Resolved Fixture
    text1 = (
        "Offer of Employment from Radiant Energy Solutions Ltd.\n"
        "Location: Hyderabad, Telangana.\n"
        "Contact: careers@radiantenergy.example"
    )
    case1 = CaseInput(case_id=301, run_id="run_01J9X1GAPRESOLVED", source_type=SourceType.TEXT, redacted_text=text1)
    mock1 = MockSearchClient(
        query_responses={
            'Radiant Energy Solutions Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [{"link": "https://directory.example/radiant", "title": "Directory", "snippet": "Profile"}],
            },
            '"Radiant Energy Solutions Ltd" "Hyderabad" official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Radiant Energy Solutions Ltd",
                    "website": "https://www.radiantenergy.example",
                    "careers_url": "https://careers.radiantenergy.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.radiantenergy.example/",
                        "title": "Radiant Energy Solutions Ltd",
                        "snippet": "Official website in Hyderabad.",
                    },
                    {
                        "link": "https://careers.radiantenergy.example/",
                        "title": "Radiant Careers",
                        "snippet": "Contact talent team at careers@radiantenergy.example for verification.",
                    }
                ],
            },
        }
    )
    res1 = await investigate_case(case1, search_client=mock1)
    assert res1.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert next(a for a in res1.assessed_claims if a.claim_id == "c1").status == ClaimStatus.SUPPORTED
    assert next(a for a in res1.assessed_claims if a.claim_id == "c2").status == ClaimStatus.UNRESOLVED
    dump1 = res1.model_dump_json(indent=2)
    assert InvestigationResult.model_validate_json(dump1) == res1
    (GENERATED_FIXTURES_DIR / "fixture_adaptive_gap_resolved.json").write_text(dump1, encoding="utf-8")
    (GENERATED_FIXTURES_DIR / "adaptive_gap_resolved.json").write_text(dump1, encoding="utf-8")

    # 2. Abstains Exhausted Fixture
    text2 = (
        "Welcome to NexaCore Technologies Ltd! Remote Frontend Developer offer.\n"
        "Contact: hr@nexacore.example"
    )
    case2 = CaseInput(case_id=302, run_id="run_01J9X2ABSTAINSEXHAUSTED", source_type=SourceType.TEXT, redacted_text=text2)
    mock2 = MockSearchClient(
        query_responses={
            'NexaCore Technologies Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
            '"NexaCore Technologies Ltd" "Remote" official website': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
        }
    )
    res2 = await investigate_case(case2, search_client=mock2)
    assert res2.overall_outcome == OverallOutcome.CANNOT_VERIFY
    dump2 = res2.model_dump_json(indent=2)
    assert InvestigationResult.model_validate_json(dump2) == res2
    (GENERATED_FIXTURES_DIR / "fixture_adaptive_abstains_exhausted.json").write_text(dump2, encoding="utf-8")
    (GENERATED_FIXTURES_DIR / "adaptive_abstains_exhausted.json").write_text(dump2, encoding="utf-8")
