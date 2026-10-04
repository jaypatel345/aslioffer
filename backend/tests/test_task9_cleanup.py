from app.schemas.analysis import AgentFinding
from app.services.risk.assessment_engine import AssessmentEngine
from app.services.risk.assessment_models import ExecutionStatus, ResolutionStatus
from app.services.report.presentation_helper import (
    derive_summary, derive_green_flags, derive_reasons_and_details,
    derive_official_company_info, derive_recommended_actions,
)


def finding(agent, details, verdict='CANNOT_VERIFY'):
    return AgentFinding(agent_name=agent, verdict=verdict, confidence=.5, summary='', details=details)


def test_local_no_match_is_not_described_as_an_empty_public_search():
    assessment = AssessmentEngine().assess([finding('ScamAgent', {'local_scan_completed': True, 'provider_status': 'FAILED'})])
    summary = derive_summary(assessment, 'Example')
    assert 'Public searches completed but found no matching records (Local' not in summary
    assert 'Document text scan' in ' '.join(derive_green_flags(assessment))


def test_authentication_failure_is_not_invented_as_service_outage():
    assessment = AssessmentEngine().assess([finding('CompanyAgent', {'provider_status': 'FAILED', 'search_status': 'AUTH_FAILURE'})])
    text = derive_summary(assessment, 'Example') + ' '.join(derive_recommended_actions(assessment))
    assert 'outage' not in text.lower()
    assert 'unavailable' in text.lower()


def test_every_outcome_reasons_include_authenticity_and_all_failed_checks():
    assessment = AssessmentEngine().assess([finding('ScamAgent', {'local_scan_completed': True, 'signal_assessments': [{'signal_code': 'UPFRONT_FEE_DEMAND', 'modality': 'active_demand', 'contributes_to_verdict': True, 'source_quote': 'Pay deposit'}], 'provider_status': 'FAILED'}, 'HIGH_RISK')])
    _, details = derive_reasons_and_details(assessment)
    assert any(d.code == 'OFFER_AUTHENTICITY_UNCONFIRMED' for d in details)
    for check in assessment.individual_checks:
        if check.applicability and check.execution_status in (ExecutionStatus.UNAVAILABLE, ExecutionStatus.NOT_CHECKED):
            assert any(check.check_name in d.reason for d in details)
    assert any('confirm that this specific offer' in a for a in derive_recommended_actions(assessment))


def test_supported_affiliation_does_not_invent_email_domain_alignment():
    assessment = AssessmentEngine().assess([])
    check = next(c for c in assessment.individual_checks if c.check_id == 'RECRUITER_AFFILIATION_CHECK')
    check.execution_status = ExecutionStatus.COMPLETED
    check.resolution_status = ResolutionStatus.SUPPORTED
    flags = derive_green_flags(assessment)
    assert any('affiliation' in f for f in flags)
    assert not any('domain aligns' in f for f in flags)


def test_conflicting_careers_urls_are_not_arbitrarily_selected():
    a = finding('CompanyAgent', {'provider_status': 'SUCCESS', 'official_domain': 'https://example.com', 'careers_url': 'https://example.com/jobs'}, 'VERIFIED')
    b = finding('CompanyAgent', {'provider_status': 'SUCCESS', 'official_domain': 'https://example.com', 'careers_url': 'https://example.com/careers'}, 'VERIFIED')
    assert derive_official_company_info([a, b], 'Example')['careers_url'] is None
    assert derive_official_company_info([b, a], 'Example')['careers_url'] is None


def test_mock_and_missing_provider_metadata_do_not_publish_official_contacts():
    for details in ({'search_source': 'MOCK', 'provider_status': 'SUCCESS'}, {}):
        comp = finding('CompanyAgent', {**details, 'official_domain': 'https://example.com'}, 'VERIFIED')
        assert derive_official_company_info([comp], 'Example')['website'] is None
