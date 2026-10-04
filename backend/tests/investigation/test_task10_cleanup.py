import asyncio
from unittest.mock import AsyncMock
import pytest
from app.schemas.contract import (CaseInput, Claim, ClaimKind, ClaimStatus, ConfirmedClaim,
    EventStatus, ExtractionStatus, SourceType, SourceTier)
from app.services.investigation.recording_search import RecordingSearchClient
from app.services.investigation.claim_builder import ClaimBuilder
from app.services.investigation.evidence_adapter import EvidenceAdapter, determine_source_tier
from app.services.investigation.pipeline import investigate_case
from app.services.investigation.events import EventEmitter
from app.schemas.analysis import AgentFinding, EvidenceItem


def case(text='', **kwargs):
    return CaseInput(case_id=1, run_id='cleanup', source_type=SourceType.TEXT, redacted_text=text, **kwargs)


@pytest.mark.asyncio
async def test_concurrent_context_is_task_local_and_identical_calls_coalesce():
    class Client:
        def __init__(self): self.calls = []
        async def search(self, query, **kw):
            self.calls.append(query)
            await asyncio.sleep(.01)
            return {'source': 'REAL', 'organic_results': []}
    raw = Client()
    client = RecordingSearchClient(raw)
    async def run(name, query):
        with client.step(name, name):
            return await client.search(query)
    await asyncio.gather(run('first', 'a'), run('second', 'b'), run('third', 'a'))
    assert sorted(raw.calls) == ['a', 'b']
    assert {c.query: c.step for c in client.tool_calls} == {'a': 'first', 'b': 'second'}


@pytest.mark.asyncio
async def test_cache_includes_result_count_and_defends_against_mutation():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'REAL', 'organic_results': [{'link': 'https://example.org', 'title': 'A', 'snippet': 'B'}]}
    client = RecordingSearchClient(raw)
    first = await client.search('q', num=1)
    first['organic_results'].clear()
    assert len((await client.search('q', num=1))['organic_results']) == 1
    await client.search('q', num=2)
    assert raw.search.await_count == 2


@pytest.mark.asyncio
async def test_demo_rejected_before_agent_can_use_it_and_failure_is_safe():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'DEMO', 'organic_results': [{'link': 'https://example.org', 'title': 'Fake'}]}
    client = RecordingSearchClient(raw)
    result = await client.search('q')
    assert result['source'] == 'FAILED' and not result['organic_results']
    assert not client.snippets_by_url
    raw.search.side_effect = RuntimeError('api_key=secret credentialpayload')
    result = await client.search('other')
    assert 'secret' not in str(result) + str(client.failed_searches)


def test_unknown_source_and_parent_domain_are_not_promoted():
    assert determine_source_tier('https://unfamiliar.example') == SourceTier.UNKNOWN
    assert determine_source_tier('https://example.com', 'division.example.com') != SourceTier.OFFICIAL_EMPLOYER
    assert determine_source_tier('https://careers.example.com', 'www.example.com') == SourceTier.OFFICIAL_EMPLOYER


def test_unrecorded_finding_does_not_fabricate_provenance():
    claim = Claim(claim_id='c1', kind=ClaimKind.EMPLOYER, value='Example', extraction_status=ExtractionStatus.USER_CONFIRMED)
    finding = AgentFinding(agent_name='CompanyAgent', verdict='VERIFIED', confidence=.9, summary='', details={'official_domain_resolved': True}, evidence=[EvidenceItem(source_url='https://example.com', title='A', description='B', evidence_type='COMPANY', confidence=.9)])
    records = EvidenceAdapter().adapt_evidence([claim], {'CompanyAgent': finding}, RecordingSearchClient(), [], 'example.com')
    assert records == []


def test_confirmations_reject_duplicate_kinds_and_changed_confirmed_values():
    with pytest.raises(ValueError, match='multiple values'):
        ClaimBuilder().build_claims(case(confirmed_claims=[ConfirmedClaim(claim_id='c1', kind=ClaimKind.EMPLOYER, value='A', extraction_status=ExtractionStatus.USER_EDITED), ConfirmedClaim(claim_id='c2', kind=ClaimKind.EMPLOYER, value='B', extraction_status=ExtractionStatus.USER_EDITED)]))
    builder = ClaimBuilder()
    original, _, _ = builder.build_claims(case('Offer from Acme Technologies Pvt Ltd.'))
    employer = next(c for c in original if c.kind == ClaimKind.EMPLOYER)
    assert employer.value
    with pytest.raises(ValueError, match='USER_EDITED'):
        builder.build_claims(case('Offer from Acme Technologies Pvt Ltd.', confirmed_claims=[ConfirmedClaim(claim_id=employer.claim_id, kind=ClaimKind.EMPLOYER, value='Different Corp', extraction_status=ExtractionStatus.USER_CONFIRMED)]))


@pytest.mark.asyncio
async def test_missing_employer_keeps_local_risk_without_placeholder_searches():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'REAL', 'organic_results': []}
    result = await investigate_case(case('Pay the mandatory laptop security deposit of INR 5000.'), raw)
    assert result.overall_outcome.value == 'HIGH_RISK'
    raw.search.assert_not_awaited()
    assert result.coverage.failed_checks == 0
    assert result.coverage.checked_claims == 1
    payment = next(c for c in result.claims if c.kind == ClaimKind.PAYMENT_REQUEST)
    assert next(a for a in result.assessed_claims if a.claim_id == payment.claim_id).status == ClaimStatus.SUPPORTED


@pytest.mark.asyncio
async def test_empty_case_does_not_inflate_checked_coverage():
    raw = AsyncMock()
    result = await investigate_case(case(), raw)
    assert result.coverage.checked_claims == 0
    assert result.coverage.unresolved_claims == len(result.claims)
    assert result.overall_outcome.value == 'CANNOT_VERIFY'
    raw.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_future_is_awaited():
    async def callback(event):
        await asyncio.sleep(0)
        delivered.append(event)
    delivered = []
    emitter = EventEmitter('run', lambda e: asyncio.create_task(callback(e)))
    await emitter.emit('test', EventStatus.STARTED, 'Starting')
    assert len(delivered) == 1


@pytest.mark.asyncio
async def test_unknown_contract_version_rejected_before_search():
    raw = AsyncMock()
    with pytest.raises(ValueError, match='Unsupported'):
        await investigate_case(case(contract_version='2.0'), raw)
    raw.search.assert_not_awaited()

@pytest.mark.asyncio
async def test_provider_failures_count_actual_calls_once_and_have_failed_events():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'FAILED', 'error': 'api_key=secret', 'organic_results': []}
    events = []
    result = await investigate_case(case('Offer from Acme Technologies Pvt Ltd. Contact HR: hr@acme.example'), raw, lambda e: events.append(e))
    failed_calls = [c for c in result.tool_trace if c.status == EventStatus.FAILED]
    assert result.coverage.failed_checks == len(failed_calls)
    assert result.errors
    assert 'secret' not in result.model_dump_json()
    assert any(e.step == 'check_scam_signals' and e.status == EventStatus.FAILED for e in events)


@pytest.mark.asyncio
async def test_known_snippet_never_attaches_to_an_unrelated_phone_claim():
    raw = AsyncMock()
    raw.search.return_value = {'source': 'REAL', 'organic_results': [{'link': 'https://complaints.example/a', 'title': 'Scam reports', 'snippet': 'Complaints about hr@acme.example'}]}
    client = RecordingSearchClient(raw)
    with client.step('check_recruiter_contact', 'Check contacts'):
        await client.search('hr@acme.example')
    claims = [Claim(claim_id='c2', kind=ClaimKind.SENDER_EMAIL, value='hr@acme.example', extraction_status=ExtractionStatus.USER_CONFIRMED), Claim(claim_id='c3', kind=ClaimKind.CONTACT_PHONE, value='9876543210', extraction_status=ExtractionStatus.USER_CONFIRMED)]
    finding = AgentFinding(agent_name='RecruiterAgent', verdict='HIGH_RISK', confidence=.9, summary='', details={}, evidence=[EvidenceItem(source_url='https://complaints.example/a', title='Scam reports', description='Unrelated report', evidence_type='RECRUITER', confidence=.9)])
    records = EvidenceAdapter().adapt_evidence(claims, {'RecruiterAgent': finding}, client, [])
    assert records and all(e.claim_id == 'c2' for e in records)
    assert all(e.relation.value == 'CONTEXT' for e in records)


@pytest.mark.asyncio
async def test_events_complete_when_each_stage_finishes_and_cancellation_drains_tasks():
    from unittest.mock import patch
    finished = asyncio.Event()
    slow_started = asyncio.Event()
    async def slow(**kw):
        slow_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    async def fast(**kw):
        return AgentFinding(agent_name='ScamAgent', verdict='CANNOT_VERIFY', confidence=0, summary='', details={'local_scan_completed': True, 'provider_status': 'SUCCESS'})
    raw = AsyncMock()
    raw.search.return_value = {'source': 'REAL', 'organic_results': []}
    delivered = asyncio.Event()
    def callback(e):
        if e.step == 'check_scam_signals' and e.status == EventStatus.COMPLETED:
            delivered.set()
    with patch('app.services.investigation.pipeline.SalaryAgent.investigate', side_effect=slow), patch('app.services.investigation.pipeline.ScamAgent.investigate', side_effect=fast):
        task = asyncio.create_task(investigate_case(case('Offer from Acme Technologies Pvt Ltd.', confirmed_claims=[ConfirmedClaim(claim_id='c9', kind=ClaimKind.COMPENSATION, value='10 LPA', extraction_status=ExtractionStatus.USER_EDITED)]), raw, callback))
        await asyncio.wait_for(slow_started.wait(), 1)
        await asyncio.wait_for(delivered.wait(), 1)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()


def test_stable_ids_do_not_shift_when_optional_fields_are_added():
    first, _, _ = ClaimBuilder().build_claims(case('Offer from Acme Technologies Pvt Ltd. Pay registration fee INR 5000 before joining.'))
    second, _, _ = ClaimBuilder().build_claims(case('Offer from Acme Technologies Pvt Ltd. Contact HR: hr@acme.example. Pay registration fee INR 5000 before joining.'))
    assert next(c.claim_id for c in first if c.kind == ClaimKind.PAYMENT_REQUEST) == next(c.claim_id for c in second if c.kind == ClaimKind.PAYMENT_REQUEST) == 'c10'

@pytest.mark.asyncio
async def test_concurrent_event_callbacks_are_delivered_in_sequence_order():
    delivered = []
    async def callback(event):
        if event.sequence == 0:
            await asyncio.sleep(.01)
        delivered.append(event.sequence)
    emitter = EventEmitter('run', callback)
    await asyncio.gather(emitter.emit('first', EventStatus.COMPLETED, 'Done'), emitter.emit('second', EventStatus.COMPLETED, 'Done'))
    assert delivered == [0, 1]
