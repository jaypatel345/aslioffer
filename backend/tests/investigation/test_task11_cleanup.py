import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.schemas.contract import CaseInput, SourceType, Claim, ClaimKind, ExtractionStatus, EventStatus
from app.schemas.analysis import AgentFinding
from app.services.investigation.budget import InvestigationBudget, BudgetManager
from app.services.investigation.recording_search import RecordingSearchClient
from app.services.investigation.planner import InvestigationPlanner, PlanStep
from app.services.investigation.pipeline import investigate_case


@pytest.mark.parametrize('kwargs', [{'max_search_calls': 1.2}, {'max_followup_calls': True}, {'max_concurrent_calls': float('inf')}, {'deadline_seconds': float('nan')}, {'deadline_seconds': float('inf')}])
def test_budget_rejects_nonfinite_and_noninteger_limits(kwargs):
    with pytest.raises(ValueError):
        InvestigationBudget(**kwargs)


@pytest.mark.asyncio
async def test_waiting_requests_do_not_consume_allowance_or_fabricate_calls():
    budget = BudgetManager(InvestigationBudget(max_search_calls=3, max_concurrent_calls=1, deadline_seconds=.04))
    started = asyncio.Event()
    async def hanging(**kwargs):
        started.set()
        await asyncio.Event().wait()
    raw = AsyncMock()
    raw.search.side_effect = hanging
    client = RecordingSearchClient(raw, budget_manager=budget)
    first = asyncio.create_task(client.search('first'))
    await started.wait()
    second = asyncio.create_task(client.search('second'))
    results = await asyncio.gather(first, second)
    assert budget.admitted_total_calls == raw.search.await_count == len(client.tool_calls) == 1
    assert results[1]['budget_denied'] is True
    assert len(client.failed_searches) == 1


@pytest.mark.asyncio
async def test_cancelled_semaphore_waiter_does_not_consume_budget():
    bm = BudgetManager(InvestigationBudget(max_concurrent_calls=1))
    await bm.semaphore.acquire()
    raw = AsyncMock()
    client = RecordingSearchClient(raw, budget_manager=bm)
    task = asyncio.create_task(client.search('waiting'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bm.admitted_total_calls == 0 and not client.tool_calls
    raw.search.assert_not_awaited()
    bm.semaphore.release()


def test_uncertain_contact_name_and_demand_are_not_planned():
    claims = [Claim(claim_id='c1', kind=ClaimKind.EMPLOYER, value='Acme Ltd', extraction_status=ExtractionStatus.USER_CONFIRMED)]
    for cid, kind, value in [('c2', ClaimKind.SENDER_EMAIL, 'hr@agency.example'), ('c4', ClaimKind.RECRUITER_NAME, 'Jane Doe'), ('c10', ClaimKind.PAYMENT_REQUEST, 'Pay fee')]:
        claims.append(Claim(claim_id=cid, kind=kind, value=value, source_quote=value, extraction_status=ExtractionStatus.UNCERTAIN))
    recruiter = AgentFinding(agent_name='RecruiterAgent', verdict='NEEDS_REVIEW', confidence=.5, summary='', details={'domain_match': False})
    assert InvestigationPlanner().create_plan(claims, {'RecruiterAgent': recruiter}, set(), 'acme.example') == []


@pytest.mark.asyncio
async def test_adaptive_denial_is_skipped_and_stops_queue():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'REAL', 'organic_results': []}
    steps = [PlanStep('c1', 'EMPLOYER_CONTEXT', 'gap', 'follow 1', 'identity', 1, 'stop', 'Resolve identity'), PlanStep('c1', 'EMPLOYER_CONTEXT', 'gap', 'follow 2', 'identity', 1, 'stop', 'Resolve identity')]
    events = []
    with patch('app.services.investigation.pipeline.InvestigationPlanner.create_plan', return_value=steps):
        result = await investigate_case(CaseInput(case_id=1, run_id='r', source_type=SourceType.TEXT, redacted_text='Offer from Acme Technologies Pvt Ltd.'), raw, lambda e: events.append(e), budget=InvestigationBudget(max_followup_calls=0))
    assert any(e.step.startswith('adaptive_') and e.status == EventStatus.SKIPPED for e in events)
    assert not any(c.query in ('follow 1', 'follow 2') for c in result.tool_trace)
    assert any(e.code == 'INVESTIGATION_BUDGET_EXCEEDED' for e in result.errors)
    assert len([e for e in events if e.step == 'adaptive_employer_context' and e.status == EventStatus.STARTED]) == 1


@pytest.mark.asyncio
async def test_untrusted_provider_error_does_not_escape_into_report():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'FAILED', 'error': 'api_key=secretpayload', 'organic_results': []}
    result = await investigate_case(CaseInput(case_id=1, run_id='r', source_type=SourceType.TEXT, redacted_text='Offer from Acme Technologies Pvt Ltd.'), raw)
    assert 'secretpayload' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_adaptive_affiliation_merge_preserves_adverse_recruiter_verdict():
    from app.schemas.analysis import EvidenceItem
    comp = AgentFinding(agent_name='CompanyAgent', verdict='VERIFIED', confidence=.9, summary='', details={'provider_status': 'SUCCESS', 'official_domain_resolved': True, 'canonical_domain': 'acme.example', 'official_domain': 'https://acme.example'})
    rec = AgentFinding(agent_name='RecruiterAgent', verdict='HIGH_RISK', confidence=.9, summary='', details={'provider_status': 'SUCCESS', 'phone_flagged': True, 'adverse_reports_status': 'FLAGGED', 'assessment_dimensions': {'adverse_contact_reports': {'status': 'FLAGGED'}, 'recruiter_affiliation': {'status': 'UNCONFIRMED'}}}, evidence=[EvidenceItem(source_url='https://reports.example/a', title='Adverse contact', description='Attributable contact complaint', evidence_type='RECRUITER', confidence=.9)])
    step = PlanStep('c4', 'RECRUITER_AFFILIATION', 'gap', 'Jane Acme', 'affiliation', 3, 'stop', 'Check affiliation')
    raw = AsyncMock()
    raw.search.return_value = {'source': 'REAL', 'organic_results': [{'link': 'https://acme.example/team', 'title': 'Recruitment team', 'snippet': 'Jane Doe, recruiter'}]}
    with patch('app.services.investigation.pipeline.CompanyAgent.investigate', return_value=comp), patch('app.services.investigation.pipeline.RecruiterAgent.investigate', return_value=rec), patch('app.services.investigation.pipeline.InvestigationPlanner.create_plan', return_value=[step]), patch('app.services.investigation.pipeline.RecruiterAgent._evaluate_affiliation_evidence', return_value=('SUPPORTED', 'Listing found', [], 'strong_employer_published')):
        await investigate_case(CaseInput(case_id=1, run_id='r', source_type=SourceType.TEXT, redacted_text='Offer from Acme Technologies Pvt Ltd. Contact HR: hr@acme.example'), raw)
    assert rec.verdict == 'HIGH_RISK'
    assert rec.details['assessment_dimensions']['recruiter_affiliation']['status'] == 'SUPPORTED'
