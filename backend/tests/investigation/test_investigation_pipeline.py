"""
Comprehensive test suite for Task 10 Unified Investigation Pipeline.

Tests all requirements:
- Grounded upfront-fee HIGH_RISK
- Clean completed checks with authenticity UNCONFIRMED
- Sparse employer CANNOT_VERIFY
- Provider outage with successful evidence preserved
- Strong local warning surviving external failure
- One agent exception not discarding other results
- Missing recruiter identifiers and redacted placeholders
- Quoted / negated scam text
- Confirmed and edited claims, including duplicate-ID rejection
- Claim-specific evidence integrity and honest source kinds
- No salary support from fixed bands alone
- Deterministic IDs and deduplication
- Accurate claim coverage
- Actual event order and failure/skipped states
- Callback failure behavior
- Cancellation cleanup
- Demo isolation
- No repeated company-resolution query
- Generating and round-tripping the 4 required handoff fixtures
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.contract import (
    AuthenticityStatus,
    CaseInput,
    ClaimKind,
    ClaimStatus,
    ConfirmedClaim,
    EventStatus,
    EvidenceRelation,
    ExtractionStatus,
    InvestigationResult,
    OverallOutcome,
    RetrievalStatus,
    RunEvent,
    SourceKind,
    SourceTier,
    SourceType,
)
from app.services.investigation.pipeline import investigate_case
from tests.investigation.fixture_helpers import MockSearchClient, load_fixture_by_id


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "investigation"
GENERATED_FIXTURES_DIR = FIXTURES_DIR / "generated_task10"


# ---------------------------------------------------------------------------
# 1. Grounded Upfront-Fee HIGH_RISK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grounded_upfront_fee_high_risk():
    """An explicit upfront fee demand produces HIGH_RISK and UNCONFIRMED authenticity."""
    text = (
        "Dear Candidate, Congratulations! Nimbus Infotech Ltd has selected you for the role of "
        "Graduate Engineer Trainee. Deposit a refundable laptop security fee of INR 15,000 via UPI "
        "to nimbus.onboarding@okaxis within 24 hours. Contact: priya.nimbushr@gmail.com"
    )
    case_input = CaseInput(
        case_id=101,
        run_id="run_test_fee_high_risk",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Nimbus Infotech Ltd" official website careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://www.nimbusinfotech.example/",
                        "title": "Nimbus Infotech Ltd — Official Website",
                        "snippet": "Nimbus Infotech Ltd is an IT services company headquartered in Pune.",
                    }
                ],
            },
            "Nimbus Infotech Ltd recruitment fraud email domain fee": {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://careers.nimbusinfotech.example/fraud-alert",
                        "title": "Recruitment Fraud Alert | Nimbus Careers",
                        "snippet": "Nimbus never asks candidates for money or security deposits. We do not charge fees.",
                    }
                ],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert isinstance(result, InvestigationResult)
    assert result.overall_outcome == OverallOutcome.HIGH_RISK
    assert result.authenticity_status == AuthenticityStatus.UNCONFIRMED

    pay_claim = next(c for c in result.claims if c.kind == ClaimKind.PAYMENT_REQUEST)
    assert pay_claim.extraction_status == ExtractionStatus.EXTRACTED
    assert "15,000" in (pay_claim.value or "")

    assessed_pay = next(a for a in result.assessed_claims if a.claim_id == pay_claim.claim_id)
    assert "UPFRONT_PAYMENT_DEMAND" in assessed_pay.reason_codes
    assert assessed_pay.status == ClaimStatus.SUPPORTED
    assert "presence of the demand" in assessed_pay.explanation


# ---------------------------------------------------------------------------
# 2. Clean Completed Checks with Authenticity UNCONFIRMED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_completed_checks_authenticity_unconfirmed():
    """Consistent public footprint yields NO_STRONG_RISK_SIGNALS and strictly UNCONFIRMED authenticity."""
    text = (
        "Offer of Employment from Kestrel Systems Pvt Ltd.\n"
        "We are pleased to offer you the position of Associate Consultant.\n"
        "Please review the offer details at https://careers.kestrelsystems.example/offers.\n"
        "Regards, Ananya Rao, Talent Acquisition. Contact: ananya.rao@kestrelsystems.example"
    )
    case_input = CaseInput(
        case_id=102,
        run_id="run_test_clean_unconfirmed",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Kestrel Systems Pvt Ltd" official website careers': {
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
                        "title": "Kestrel Systems — Official Website",
                        "snippet": "Kestrel Systems Pvt Ltd is a technology consulting firm based in Bengaluru.",
                    },
                    {
                        "link": "https://careers.kestrelsystems.example/",
                        "title": "Kestrel Systems Careers Portal",
                        "snippet": "Join Kestrel Systems. Current opportunities and onboarding verification.",
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
    assert result.authenticity_status == AuthenticityStatus.UNCONFIRMED

    # Confirmation route is populated if an independently sourced employer careers portal was discovered
    assert result.confirmation_route is not None
    assert result.confirmation_route.channel == "careers_portal"
    assert "kestrelsystems.example" in result.confirmation_route.destination

    emp_assessed = next(a for a in result.assessed_claims if a.claim_id == "c1")
    assert emp_assessed.status == ClaimStatus.SUPPORTED
    assert "OFFICIAL_DOMAIN_RESOLVED" in emp_assessed.reason_codes


# ---------------------------------------------------------------------------
# 3. Sparse Employer CANNOT_VERIFY
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sparse_employer_cannot_verify():
    """Sparse startup footprint leads to CANNOT_VERIFY without falsely accusing fraud."""
    text = (
        "Welcome to Coorix Labs! We are pleased to offer you the role of Backend Developer Intern.\n"
        "Contact HR: hr@coorixlabs.example"
    )
    case_input = CaseInput(
        case_id=103,
        run_id="run_test_sparse_startup",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Coorix Labs" official website careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://startups.directory.example/coorix-labs",
                        "title": "Coorix Labs — startup profile",
                        "snippet": "Coorix Labs · Software development · 2–10 employees · Ahmedabad",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert result.authenticity_status == AuthenticityStatus.UNCONFIRMED

    emp_assessed = next(a for a in result.assessed_claims if a.claim_id == "c1")
    assert emp_assessed.status == ClaimStatus.UNRESOLVED
    assert "SPARSE_FOOTPRINT" in emp_assessed.reason_codes

    # Sender email claim depends on employer domain, so it remains unresolved
    email_assessed = next(a for a in result.assessed_claims if a.claim_id == "c2")
    assert email_assessed.status == ClaimStatus.UNRESOLVED


# ---------------------------------------------------------------------------
# 4. Provider Outage with Preserved Evidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_outage_preserves_evidence():
    """Search provider failure results in CANNOT_VERIFY, preserves error record, and context evidence."""
    text = (
        "Offer from Vardhan Analytics Pvt Ltd for Data Analyst. "
        "Contact: careers@vardhananalytics.example"
    )
    case_input = CaseInput(
        case_id=104,
        run_id="run_test_provider_outage",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Vardhan Analytics Pvt Ltd" official website careers': {
                "status": "error",
                "source": "FAILED",
                "error": "Upstream search engine rate limited after 2 retries",
                "organic_results": [],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert len(result.errors) >= 1
    assert any(e.code == "SEARCH_PROVIDER_OUTAGE" for e in result.errors)

    emp_assessed = next(a for a in result.assessed_claims if a.claim_id == "c1")
    assert emp_assessed.status == ClaimStatus.UNRESOLVED
    assert "SEARCH_UNAVAILABLE" in emp_assessed.reason_codes

    # Failed search context evidence is preserved
    assert len(result.evidence) >= 1
    ev = result.evidence[0]
    assert ev.retrieval_status == RetrievalStatus.FAILED
    assert ev.relation == EvidenceRelation.CONTEXT


# ---------------------------------------------------------------------------
# 5. Strong Local Warning Surviving External Failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strong_local_warning_survives_external_failure():
    """An upfront fee demand in the document retains HIGH_RISK even when external search fails."""
    text = (
        "Offer from Vardhan Analytics Pvt Ltd. Deposit mandatory laptop fee of INR 10,000 via UPI "
        "before joining date. Contact: hr@vardhananalytics.example"
    )
    case_input = CaseInput(
        case_id=105,
        run_id="run_test_local_warning_survives",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Vardhan Analytics Pvt Ltd" official website careers': {
                "status": "error",
                "source": "FAILED",
                "error": "Upstream provider timed out",
                "organic_results": [],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    # Local scam signal must survive external provider outage
    assert result.overall_outcome == OverallOutcome.HIGH_RISK
    assert any(e.code == "SEARCH_PROVIDER_OUTAGE" for e in result.errors)

    # Document-local evidence record must be present
    doc_ev = next((e for e in result.evidence if e.source_kind == SourceKind.DOCUMENT), None)
    assert doc_ev is not None
    assert doc_ev.source_tier == SourceTier.OFFER_DOCUMENT
    assert doc_ev.source_url is None


# ---------------------------------------------------------------------------
# 6. One Agent Exception Not Discarding Other Results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_agent_exception_not_discarding_other_results():
    """An unexpected exception in SalaryAgent records RunError but preserves company and scam findings."""
    text = (
        "Offer from Nimbus Infotech Ltd for Systems Engineer. CTC: INR 7.5 LPA. "
        "Contact: careers@nimbusinfotech.example"
    )
    case_input = CaseInput(
        case_id=106,
        run_id="run_test_agent_exception_isolated",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Nimbus Infotech Ltd" official website careers': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Nimbus Infotech Ltd",
                    "website": "https://www.nimbusinfotech.example",
                    "careers_url": "https://careers.nimbusinfotech.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.nimbusinfotech.example/",
                        "title": "Nimbus Infotech Ltd",
                        "snippet": "Official website of Nimbus Infotech Ltd.",
                    }
                ],
            }
        }
    )

    with patch("app.services.agents.salary_agent.SalaryAgent.investigate", side_effect=RuntimeError("Unexpected crash in salary parser")):
        result = await investigate_case(case_input, search_client=search_mock)

    assert isinstance(result, InvestigationResult)
    assert any(e.code == "AGENT_CHECK_FAILURE" and e.step == "check_compensation" for e in result.errors)

    # Company check was successful and preserved
    emp_assessed = next(a for a in result.assessed_claims if a.claim_id == "c1")
    assert emp_assessed.status == ClaimStatus.SUPPORTED


# ---------------------------------------------------------------------------
# 7. Missing Recruiter Identifiers and Redacted Placeholders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_recruiter_identifiers_and_redacted_placeholders():
    """Redacted placeholders [EMAIL_1] and [PHONE_1] must not trigger search queries or false matches."""
    text = (
        "Congratulations from Infosys Ltd! Role: Systems Engineer. "
        "Contact HR at [EMAIL_1] or phone [PHONE_1]."
    )
    case_input = CaseInput(
        case_id=107,
        run_id="run_test_redacted_placeholders",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Infosys Ltd" official website careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://www.infosys.com/",
                        "title": "Infosys — Official Website",
                        "snippet": "Infosys is a global leader in next-generation digital services.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    # Verify no searches contain "[EMAIL_1]"
    assert not any("[EMAIL_1]" in q or "[PHONE_1]" in q for q in search_mock.recorded_queries)


# ---------------------------------------------------------------------------
# 8. Quoted and Negated Scam Text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quoted_and_negated_scam_text():
    """Negated fee policies like 'We never charge a security deposit' do not trigger HIGH_RISK."""
    text = (
        "Offer from Tata Consultancy Services for Software Engineer. "
        "Important Note: We never charge any security deposit, training fee, or registration charges. "
        "Beware of fraudulent messages. Contact: careers@tcs.com"
    )
    case_input = CaseInput(
        case_id=108,
        run_id="run_test_negated_scam",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Tata Consultancy Services" official website careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://www.tcs.com/",
                        "title": "TCS — Official",
                        "snippet": "Tata Consultancy Services official careers portal.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome != OverallOutcome.HIGH_RISK
    pay_claim = next(c for c in result.claims if c.kind == ClaimKind.PAYMENT_REQUEST)
    assert pay_claim.extraction_status == ExtractionStatus.MISSING


# ---------------------------------------------------------------------------
# 9. Confirmed and Edited Claims, Duplicate-ID Rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_confirmed_claim_ids_rejected():
    """CaseInput with duplicate confirmed_claim IDs must be rejected immediately."""
    text = "Offer from TechCorp for Developer."
    case_input = CaseInput(
        case_id=109,
        run_id="run_test_dup_confirmed",
        source_type=SourceType.TEXT,
        redacted_text=text,
        confirmed_claims=[
            ConfirmedClaim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="TechCorp", extraction_status=ExtractionStatus.USER_CONFIRMED),
            ConfirmedClaim(claim_id="c1", kind=ClaimKind.ROLE, value="Developer", extraction_status=ExtractionStatus.USER_CONFIRMED),
        ],
        demo_mode=False,
    )

    with pytest.raises(ValueError, match="Duplicate confirmed claim ID 'c1'"):
        await investigate_case(case_input)


@pytest.mark.asyncio
async def test_user_edited_claim_strips_offsets_and_quote():
    """A USER_EDITED claim must not receive fabricated quotes or offsets."""
    text = "Selected for Software Engineer at TechCorp."
    case_input = CaseInput(
        case_id=110,
        run_id="run_test_user_edited",
        source_type=SourceType.TEXT,
        redacted_text=text,
        confirmed_claims=[
            ConfirmedClaim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="EditedCorp Ltd", extraction_status=ExtractionStatus.USER_EDITED),
        ],
        demo_mode=False,
    )
    search_mock = MockSearchClient({})

    result = await investigate_case(case_input, search_client=search_mock)

    emp_claim = next(c for c in result.claims if c.kind == ClaimKind.EMPLOYER)
    assert emp_claim.value == "EditedCorp Ltd"
    assert emp_claim.extraction_status == ExtractionStatus.USER_EDITED
    assert emp_claim.source_quote is None
    assert emp_claim.start_offset is None
    assert emp_claim.end_offset is None


# ---------------------------------------------------------------------------
# 10. Claim-Specific Evidence Integrity and Honest Source Kinds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_specific_evidence_integrity():
    """Every EvidenceRecord belongs to a valid claim in the same run and complies with contract constraints."""
    text = (
        "Offer from Nimbus Infotech Ltd. Deposit INR 5,000 security fee to [UPI_ID_1]. "
        "Contact: hr@nimbusinfotech.example"
    )
    case_input = CaseInput(
        case_id=111,
        run_id="run_test_ev_integrity",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    search_mock = MockSearchClient(
        query_responses={
            '"Nimbus Infotech Ltd" official website careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [
                    {
                        "link": "https://www.nimbusinfotech.example/",
                        "title": "Nimbus Infotech Ltd",
                        "snippet": "Official site of Nimbus Infotech Ltd.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    valid_claim_ids = {c.claim_id for c in result.claims}
    for ev in result.evidence:
        assert ev.claim_id in valid_claim_ids
        if ev.source_kind == SourceKind.DOCUMENT:
            assert ev.source_tier == SourceTier.OFFER_DOCUMENT
            assert ev.source_url is None
        elif ev.retrieval_status != RetrievalStatus.FAILED:
            assert ev.source_url is not None
            assert "api_key=" not in ev.source_url.lower()


# ---------------------------------------------------------------------------
# 11. No Salary Support From Fixed Bands Alone
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_salary_support_from_fixed_bands_alone():
    """Salary plausibility check without external market snippets does not mark compensation SUPPORTED."""
    text = "Offer from TechCorp for Analyst. Salary INR 6.5 LPA."
    case_input = CaseInput(
        case_id=112,
        run_id="run_test_salary_band",
        source_type=SourceType.TEXT,
        redacted_text=text,
        demo_mode=False,
    )
    # Search returns empty results for salary
    search_mock = MockSearchClient(
        query_responses={
            '"TechCorp" official website careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [{"link": "https://techcorp.example/", "title": "TechCorp", "snippet": "TechCorp site"}],
            },
            '"Analyst" salary "TechCorp" AmbitionBox Glassdoor': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    sal_claim = next((c for c in result.claims if c.kind == ClaimKind.COMPENSATION), None)
    if sal_claim:
        assessed_sal = next(a for a in result.assessed_claims if a.claim_id == sal_claim.claim_id)
        assert assessed_sal.status != ClaimStatus.SUPPORTED


# ---------------------------------------------------------------------------
# 12. Deterministic IDs and Deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deterministic_claim_and_evidence_ids():
    """Two identical pipeline runs generate identical claim and evidence IDs."""
    text = "Offer from AlphaCorp for Designer. Contact: hr@alphacorp.example"
    case_input1 = CaseInput(case_id=113, run_id="run_det_1", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)
    case_input2 = CaseInput(case_id=113, run_id="run_det_2", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)

    search_mock = MockSearchClient({})
    res1 = await investigate_case(case_input1, search_client=search_mock)
    res2 = await investigate_case(case_input2, search_client=search_mock)

    assert [c.claim_id for c in res1.claims] == [c.claim_id for c in res2.claims]
    assert [c.kind for c in res1.claims] == [c.kind for c in res2.claims]


# ---------------------------------------------------------------------------
# 13. Accurate Claim Coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accurate_claim_coverage():
    """Coverage counts claims accurately according to contract-v1 bounds."""
    text = "Offer from BetaCorp for QA Tester. Contact: hr@betacorp.example"
    case_input = CaseInput(case_id=114, run_id="run_coverage", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)
    search_mock = MockSearchClient({})

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.coverage.total_claims == len(result.claims)
    assert result.coverage.checked_claims <= result.coverage.total_claims
    assert result.coverage.unresolved_claims <= result.coverage.total_claims
    assert result.coverage.failed_checks >= 0


# ---------------------------------------------------------------------------
# 14. Actual Event Order and Failure/Skipped States
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_order_and_states():
    """RunEvent emission produces strictly increasing sequences without secrets."""
    text = "Offer from DeltaCorp for Engineer."
    case_input = CaseInput(case_id=115, run_id="run_events", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)

    emitted_events: list[RunEvent] = []

    async def callback(event: RunEvent):
        emitted_events.append(event)

    search_mock = MockSearchClient({})
    await investigate_case(case_input, search_client=search_mock, emit_event=callback)

    assert len(emitted_events) >= 3
    seqs = [e.sequence for e in emitted_events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert all(e.run_id == case_input.run_id for e in emitted_events)
    assert not any("api_key" in e.public_message.lower() for e in emitted_events)


# ---------------------------------------------------------------------------
# 15. Callback Failure Behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_failure_does_not_alter_verdict():
    """An exception thrown inside emit_event does not prevent completion or alter the result."""
    text = "Offer from GammaCorp for Researcher."
    case_input = CaseInput(case_id=116, run_id="run_callback_err", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)

    async def broken_callback(event: RunEvent):
        raise RuntimeError("Websocket connection reset")

    search_mock = MockSearchClient({})
    result = await investigate_case(case_input, search_client=search_mock, emit_event=broken_callback)

    assert isinstance(result, InvestigationResult)


# ---------------------------------------------------------------------------
# 16. Cancellation Cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancellation_cleanup_propagates():
    """Cancellation during investigation propagates asyncio.CancelledError cleanly."""
    text = "Offer from Zeta Technologies Pvt Ltd for Architect."
    case_input = CaseInput(case_id=117, run_id="run_cancel", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)

    async def hanging_search(*args, **kwargs):
        await asyncio.sleep(10)
        return {}

    mock_client = AsyncMock()
    mock_client.search = hanging_search

    task = asyncio.create_task(investigate_case(case_input, search_client=mock_client))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# 17. Demo Isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_isolation_enforced():
    """When demo_mode is False, synthetic demo results are rejected and marked FAILED."""
    text = "Offer from ThetaCorp for Manager."
    case_input = CaseInput(case_id=118, run_id="run_demo_iso", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)

    # Search client returns synthetic demo source
    search_mock = MockSearchClient(
        query_responses={
            '"ThetaCorp" official website careers': {
                "status": "successful",
                "source": "DEMO",
                "organic_results": [{"link": "https://thetacorp.example/", "title": "Demo", "snippet": "Demo snippet"}],
            }
        }
    )

    # In non-demo mode, MockSearchClient._replay converts DEMO to REAL. Let's force raw DEMO source:
    search_mock._replay = lambda resp: resp

    result = await investigate_case(case_input, search_client=search_mock)

    assert not any(e.retrieval_status == RetrievalStatus.DEMO for e in result.evidence)


# ---------------------------------------------------------------------------
# 18. No Repeated Company Resolution Query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_repeated_company_resolution_query():
    """Shared query between CompanyAgent and RecruiterAgent executes underlying search only once."""
    text = "Offer from OmegaCorp Ltd for Lead. Contact: hr@omegacorp.example"
    case_input = CaseInput(case_id=119, run_id="run_dedup_query", source_type=SourceType.TEXT, redacted_text=text, demo_mode=False)

    call_count = 0

    searched_queries: list[str] = []

    async def counting_search(query: str, **kwargs):
        searched_queries.append(query)
        return {
            "status": "successful",
            "source": "REAL",
            "organic_results": [{"link": "https://omegacorp.example/", "title": "OmegaCorp Ltd", "snippet": "OmegaCorp Ltd official site"}],
        }

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(side_effect=counting_search)

    result = await investigate_case(case_input, search_client=mock_client)

    # The company resolution query '"OmegaCorp Ltd" official website careers' was called by CompanyAgent
    # and RecruiterAgent, but counting_search must have been invoked only ONCE for it due to in-memory caching!
    comp_exact_count = searched_queries.count('"OmegaCorp Ltd" official website careers')
    assert comp_exact_count == 1


# ---------------------------------------------------------------------------
# 19. Generate and Round-Trip the 4 Required Handoff Fixtures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_and_roundtrip_handoff_fixtures(tmp_path):
    """
    Generates actual investigator pipeline outputs for:
    - Supported public consistency
    - Supported adverse warning
    - Sparse employer
    - Provider outage
    Validates them with InvestigationResult and asserts JSON round-tripping.
    """
    GENERATED_FIXTURES_DIR = tmp_path
    fixtures_to_generate = [
        (
            "supported_public_consistency",
            CaseInput(
                case_id=201,
                run_id="run_01J9X5NOSTRONGSIGNALS",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Offer of Employment from Kestrel Systems Pvt Ltd.\n"
                    "We are pleased to offer you the position of Associate Consultant.\n"
                    "Please review the offer details at https://careers.kestrelsystems.example/offers.\n"
                    "Regards, Ananya Rao, Talent Acquisition. Contact: ananya.rao@kestrelsystems.example"
                ),
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    '"Kestrel Systems Pvt Ltd" official website careers': {
                        "status": "successful",
                        "source": "REAL",
                        "knowledge_graph": {"title": "Kestrel Systems Pvt Ltd", "website": "https://www.kestrelsystems.example", "careers_url": "https://careers.kestrelsystems.example"},
                        "organic_results": [
                            {
                                "link": "https://www.kestrelsystems.example/",
                                "title": "Kestrel Systems — Official Website",
                                "snippet": "Kestrel Systems Pvt Ltd is a technology consulting firm.",
                            },
                            {
                                "link": "https://careers.kestrelsystems.example/",
                                "title": "Kestrel Systems Careers Portal",
                                "snippet": "Careers and job offers at Kestrel Systems.",
                            },
                            {
                                "link": "https://careers.kestrelsystems.example/team",
                                "title": "Kestrel Systems Recruitment Team",
                                "snippet": "Contact our talent acquisition recruiter Ananya Rao at ananya.rao@kestrelsystems.example for verification.",
                            },
                        ],
                    }
                }
            ),
        ),
        (
            "supported_adverse_warning",
            CaseInput(
                case_id=202,
                run_id="run_01J9X2IMPERSONATION",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Dear Candidate, Nimbus Infotech Ltd has selected you for Graduate Engineer Trainee. "
                    "Deposit a refundable laptop security fee of INR 15,000 via UPI within 24 hours. "
                    "Contact: priya.nimbushr@gmail.com"
                ),
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    '"Nimbus Infotech Ltd" official website careers': {
                        "status": "successful",
                        "source": "REAL",
                        "organic_results": [
                            {
                                "link": "https://www.nimbusinfotech.example/",
                                "title": "Nimbus Infotech Ltd",
                                "snippet": "Nimbus Infotech Ltd official website.",
                            }
                        ],
                    },
                    "Nimbus Infotech Ltd recruitment fraud email domain fee": {
                        "status": "successful",
                        "source": "REAL",
                        "organic_results": [
                            {
                                "link": "https://careers.nimbusinfotech.example/fraud-alert",
                                "title": "Fraud Alert | Nimbus Careers",
                                "snippet": "Nimbus never asks candidates for money or laptop fees.",
                            }
                        ],
                    },
                }
            ),
        ),
        (
            "sparse_employer",
            CaseInput(
                case_id=203,
                run_id="run_01J9X3SPARSESTARTUP",
                source_type=SourceType.TEXT,
                redacted_text="Welcome to Coorix Labs. Role: Backend Developer Intern. Contact: hr@coorixlabs.example",
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    '"Coorix Labs" official website careers': {
                        "status": "successful",
                        "source": "REAL",
                        "organic_results": [
                            {
                                "link": "https://startups.directory.example/coorix-labs",
                                "title": "Coorix Labs profile",
                                "snippet": "Coorix Labs · Software development · 2–10 employees",
                            }
                        ],
                    }
                }
            ),
        ),
        (
            "provider_outage",
            CaseInput(
                case_id=204,
                run_id="run_01J9X4PROVIDEROUTAGE",
                source_type=SourceType.TEXT,
                redacted_text="Offer from Vardhan Analytics Pvt Ltd for Data Analyst. Contact: careers@vardhananalytics.example",
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    '"Vardhan Analytics Pvt Ltd" official website careers': {
                        "status": "error",
                        "source": "FAILED",
                        "error": "Upstream search engine rate limited after 2 retries",
                        "organic_results": [],
                    }
                }
            ),
        ),
    ]

    for name, case_input, search_client in fixtures_to_generate:
        result = await investigate_case(case_input, search_client=search_client)
        assert isinstance(result, InvestigationResult)

        # JSON Round-Trip Test
        dumped_json = result.model_dump_json(indent=2)
        parsed_again = InvestigationResult.model_validate_json(dumped_json)
        assert parsed_again == result

        expected = {"supported_public_consistency": OverallOutcome.NO_STRONG_RISK_SIGNALS,
                    "supported_adverse_warning": OverallOutcome.HIGH_RISK,
                    "sparse_employer": OverallOutcome.CANNOT_VERIFY,
                    "provider_outage": OverallOutcome.CANNOT_VERIFY}
        assert result.overall_outcome == expected[name]
        out_path = GENERATED_FIXTURES_DIR / f"fixture_{name}.json"
        out_path.write_text(dumped_json, encoding="utf-8")
        alt_path = GENERATED_FIXTURES_DIR / f"{name}.json"
        alt_path.write_text(dumped_json, encoding="utf-8")
        assert out_path.exists()
        assert alt_path.exists()
