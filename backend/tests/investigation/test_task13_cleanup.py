"""Failures the original Task 13 acceptance gate silently accepted."""
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from app.evaluation.corpus import load_evaluation_corpus
from app.evaluation.runner import evaluate_single_case, run_evaluation, EvaluationMockSearchClient
from app.evaluation.invariants import (check_confirmation_route_provenance,
    check_coverage_bounds, check_search_evidence_provenance, check_privacy_and_secret_leakage)
from app.services.investigation.pipeline import investigate_case
from app.schemas.contract import ConfirmationRoute, ClaimStatus, Coverage


def case(number):
    return next(c for c in load_evaluation_corpus() if c.case_id.startswith(f'EVAL-{number:02d}'))


async def actual(c):
    client = EvaluationMockSearchClient(c.search_mock.get('query_responses', {}), c.search_mock.get('default_response'))
    return await investigate_case(c.case_input.to_case_input(), search_client=client,
        budget=c.budget.to_investigation_budget() if c.budget else None)


@pytest.mark.asyncio
async def test_any_claim_failure_fails_case_markdown_and_exit(tmp_path):
    corpus = load_evaluation_corpus()
    corpus[0].expected_claim_statuses['payment_request'] = 'CONTRADICTED'
    with patch('app.evaluation.runner.load_evaluation_corpus', return_value=corpus):
        code, payload, markdown = await run_evaluation(output_dir=tmp_path)
    assert code == 1
    assert payload['summary']['outcome_agreement_rate'] == 1.0
    assert payload['cases'][0]['case_passed'] is False
    assert '## Status: FAIL' in markdown
    assert '**Claim mismatch:** payment_request' in markdown
    assert payload['scenario_groups']['threat_cases']['passed_cases'] == 4


@pytest.mark.asyncio
async def test_missing_required_route_fails_despite_correct_outcome():
    c = case(6)
    result = (await actual(c)).model_copy(update={'confirmation_route': None})
    with patch('app.evaluation.runner.investigate_case', return_value=result):
        checked = await evaluate_single_case(c)
    assert checked['outcome_matched']
    assert not checked['case_passed']
    assert any('has_confirmation_route' in f for f in checked['behavior_failures'])


@pytest.mark.asyncio
async def test_forbidden_and_unknown_behaviors_fail():
    c = case(6)
    c.forbidden_behaviors = ['has_confirmation_route']
    c.required_behaviors.append('misspelled_requirement')
    checked = await evaluate_single_case(c)
    assert not checked['case_passed']
    assert any('Unknown' in f for f in checked['behavior_failures'])
    assert any('Forbidden' in f for f in checked['behavior_failures'])


@pytest.mark.parametrize('mode', ['malformed', 'duplicate', 'unknown_field', 'invalid_claim_kind'])
def test_corrupt_corpus_rejected_without_rewriting(tmp_path, mode):
    payload = case(1).model_dump(mode='json')
    good = tmp_path / 'eval_good.json'
    good.write_text(json.dumps(payload))
    bad = tmp_path / 'eval_bad.json'
    if mode == 'malformed':
        bad.write_text('{bad json')
    else:
        if mode == 'unknown_field':
            payload['unexpected_field'] = True
        elif mode == 'invalid_claim_kind':
            payload['expected_claim_statuses'] = {'imaginary_claim': 'SUPPORTED'}
        bad.write_text(json.dumps(payload))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        load_evaluation_corpus(tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_missing_or_empty_explicit_corpus_does_not_generate_defaults(tmp_path):
    missing = tmp_path / 'missing'
    with pytest.raises(ValueError):
        load_evaluation_corpus(missing)
    assert not missing.exists()
    with pytest.raises(ValueError):
        load_evaluation_corpus(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_loader_error_returns_nonzero(tmp_path):
    code, payload, markdown = await run_evaluation(corpus_dir=tmp_path / 'absent', output_dir=tmp_path / 'results')
    assert code == 1 and payload['status'] == 'FAIL'
    assert 'Corpus validation failed' in markdown


@pytest.mark.asyncio
async def test_invented_same_domain_email_is_rejected():
    result = await actual(case(6))
    ev = next(e for e in result.evidence if e.source_url and 'kestrelsystems.example' in e.source_url)
    bad = result.model_copy(update={'confirmation_route': ConfirmationRoute(channel='official_email',
        destination='invented@kestrelsystems.example', evidence_id=ev.evidence_id)})
    assert not check_confirmation_route_provenance(bad).passed


@pytest.mark.asyncio
async def test_unpublished_generated_snippet_is_rejected():
    result = await actual(case(6))
    assert not check_search_evidence_provenance(result, retrieved_observations=[]).passed


@pytest.mark.asyncio
async def test_failed_checks_do_not_count_completed_coverage():
    c = case(21)
    result = await actual(c)
    assert check_coverage_bounds(result).passed
    bad = result.model_copy(update={'coverage': result.coverage.model_copy(update={'checked_claims': 1})})
    assert not check_coverage_bounds(bad).passed


@pytest.mark.asyncio
async def test_private_evidence_is_detected_without_echoing_secret():
    result = await actual(case(6))
    secret = 'PRIVATE_SECRET_TEST'
    result.evidence[0] = result.evidence[0].model_copy(update={'quote_or_snippet': secret})
    check = check_privacy_and_secret_leakage(result, [secret])
    assert not check.passed
    assert secret not in json.dumps(check.__dict__)


@pytest.mark.asyncio
async def test_exception_recording_continues_and_redacts(tmp_path):
    corpus = [case(1), case(6)]
    corpus[0].planted_secrets = ['PRIVATE_EXCEPTION_TOKEN']
    async def failing_first(case_input, **kwargs):
        if case_input.case_id == corpus[0].case_input.case_id:
            raise RuntimeError('PRIVATE_EXCEPTION_TOKEN')
        return await investigate_case(case_input, **kwargs)
    with patch('app.evaluation.runner.load_evaluation_corpus', return_value=corpus), \
         patch('app.evaluation.runner.investigate_case', side_effect=failing_first):
        code, payload, markdown = await run_evaluation(output_dir=tmp_path)
    assert code == 1 and len(payload['cases']) == 2
    assert payload['cases'][1]['case_passed']
    assert 'PRIVATE_EXCEPTION_TOKEN' not in json.dumps(payload) + markdown


@pytest.mark.asyncio
async def test_offline_client_preserves_demo_status():
    client = EvaluationMockSearchClient({}, {'status': 'successful', 'source': 'DEMO', 'organic_results': []})
    assert (await client.search('Example'))['source'] == 'DEMO'
    assert not client.retrieved_observations


@pytest.mark.asyncio
async def test_positive_scenarios_have_executable_claim_expectations():
    expected = {7: 'employer', 12: 'role', 15: 'job_reference', 17: 'application_url', 24: 'role'}
    for number, kind in expected.items():
        c = case(number)
        assert c.expected_claim_statuses[kind] == 'SUPPORTED'
        result = await evaluate_single_case(c)
        assert result['case_passed'], result
        assert result['provider_calls_count'] > 0


@pytest.mark.asyncio
async def test_deadline_fixture_forces_timeout_reproducibly():
    for _ in range(3):
        result = await evaluate_single_case(case(23))
        assert result['case_passed'], result
        assert result['checked_claims'] == 0


@pytest.mark.asyncio
async def test_full_corpus_does_not_mutate_any_committed_evaluation_asset(tmp_path):
    root = Path(__file__).resolve().parents[2] / 'app' / 'evaluation'
    def hashes():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.suffix in ('.json', '.md')}
    before = hashes()
    code, payload, _ = await run_evaluation(output_dir=tmp_path)
    assert code == 0 and len(payload['cases']) == 27
    assert before == hashes()


@pytest.mark.asyncio
async def test_live_failure_does_not_exit_successfully(tmp_path):
    with patch('app.evaluation.runner.run_live_evaluation', return_value={'status': 'FAILED', 'results': []}):
        code, _, _ = await run_evaluation(output_dir=tmp_path, live_mode=True)
    assert code == 1


@pytest.mark.asyncio
async def test_agency_case_requires_authorization_not_just_an_unverified_verdict():
    c = case(7)
    original = __import__('app.services.agents.recruiter_agent', fromlist=['RecruiterAgent']).RecruiterAgent.investigate
    async def drop_authorization(agent, *args, **kwargs):
        finding = await original(agent, *args, **kwargs)
        finding.details['assessment_dimensions']['agency_authorization']['status'] = 'UNCONFIRMED'
        return finding
    with patch('app.services.agents.recruiter_agent.RecruiterAgent.investigate', drop_authorization):
        checked = await evaluate_single_case(c)
    assert not checked['case_passed']
    assert any('agency_authorization' in f for f in checked['expectation_failures'])


@pytest.mark.asyncio
async def test_input_setup_exception_is_recorded_and_next_case_runs(tmp_path):
    corpus = [case(1), case(6)]
    with patch('app.evaluation.runner.load_evaluation_corpus', return_value=corpus), \
         patch('app.evaluation.corpus.CaseInputSpec.to_case_input', side_effect=[ValueError('invalid setup'), corpus[1].case_input.to_case_input()]):
        code, payload, _ = await run_evaluation(output_dir=tmp_path)
    assert code == 1
    assert payload['cases'][0]['exception_occurred']
    assert payload['cases'][1]['case_passed']


@pytest.mark.asyncio
async def test_offline_network_attempt_is_blocked():
    import socket
    reached = False
    async def accidental_network(*args, **kwargs):
        nonlocal reached
        reached = True
        with socket.socket() as connection:
            connection.connect(('127.0.0.1', 9))
    with patch('app.evaluation.runner.EvaluationMockSearchClient.search', accidental_network):
        checked = await evaluate_single_case(case(6))
    assert reached
    assert not checked['case_passed']


@pytest.mark.asyncio
async def test_demo_generation_respects_output_directory(tmp_path):
    code, _, _ = await run_evaluation(output_dir=tmp_path, case_filter='EVAL-06', generate_demos=True)
    assert code == 0
    manifest = json.loads((tmp_path / 'demos' / 'demo_manifest.json').read_text())
    assert len(manifest) == 5
    assert all(d['mode'] == 'offline_synthetic_replay' for d in manifest)
    assert all((tmp_path / 'demos' / d['filename']).exists() for d in manifest)


@pytest.mark.asyncio
async def test_repeated_evaluation_semantics_match_for_entire_corpus():
    for c in load_evaluation_corpus():
        a, b = await evaluate_single_case(c), await evaluate_single_case(c)
        for key in ('case_passed', 'actual_outcome', 'claim_details', 'invariants_passed',
                    'behavior_failures', 'expectation_failures', 'checked_claims', 'agent_dimensions'):
            assert a.get(key) == b.get(key), (c.case_id, key)


@pytest.mark.asyncio
@pytest.mark.parametrize('destination', ['invalid-phone', '123'])
async def test_confirmation_phone_requires_a_complete_published_number(destination):
    result = await actual(case(6))
    ev = result.evidence[0].model_copy(update={'quote_or_snippet': 'Recruitment office phone: +91 9876543210 for verification.'})
    bad = result.model_copy(update={'evidence': [ev] + result.evidence[1:],
        'confirmation_route': ConfirmationRoute(channel='official_phone', destination=destination, evidence_id=ev.evidence_id)})
    assert not check_confirmation_route_provenance(bad).passed
