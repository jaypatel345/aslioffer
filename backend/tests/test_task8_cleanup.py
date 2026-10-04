"""Task 8 policy regressions using actual agent dimension and query keys."""
import pytest
from app.schemas.analysis import AgentFinding, EvidenceItem, ExtractedEntities, RiskLevel
from app.services.risk.assessment_engine import AssessmentEngine, canonicalize_url
from app.services.risk.verdict_reasoner import VerdictReasoner
from app.services.risk.risk_engine import RiskEngine
from app.services.report.report_generator import ReportGenerator


def finding(agent, verdict="CANNOT_VERIFY", details=None, evidence=None):
    return AgentFinding(agent_name=agent, verdict=verdict, confidence=0, summary="Assessment", details=details or {}, evidence=evidence or [])


def local_evidence():
    return EvidenceItem(source_url="document://submitted-offer", title="Demand", description="Pay the registration fee before joining.", evidence_type="SCAM_REPORT", confidence=.99)


def clean_findings():
    public = EvidenceItem(source_url="https://acme.com/team", title="Team", description="Official directory", evidence_type="RECRUITER", confidence=.9)
    return [finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS"}, [public]),
            finding("RecruiterAgent", "VERIFIED", {"provider_status": "SUCCESS", "recruiter_affiliation_status": "SUPPORTED", "assessment_dimensions": {"recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"}, "adverse_contact_reports": {"status": "NO_MATCH"}}}, [public]),
            finding("SalaryAgent", "VERIFIED"),
            finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})]


def test_local_scan_is_not_invented_for_bare_legacy_verdict():
    assessment = AssessmentEngine().assess([finding("ScamAgent", "VERIFIED")])
    scan = next(c for c in assessment.individual_checks if c.check_id == "LOCAL_DOCUMENT_SCAN")
    assert scan.execution_status != "completed"
    assert assessment.overall_outcome == "CANNOT_VERIFY"


def test_structured_negated_signal_cannot_be_overridden_by_high_risk_summary():
    scam = finding("ScamAgent", "HIGH_RISK", {"local_scan_completed": True, "risk_signals": ["UPFRONT_FEE_DEMAND"], "reason_code": "ADVANCE_FEE_DETECTED", "signal_assessments": [{"signal_code": "UPFRONT_FEE_DEMAND", "modality": "negated_policy", "contributes_to_verdict": False, "source_quote": "We never charge fees"}]}, [local_evidence()])
    assessment = AssessmentEngine().assess([scam])
    assert not assessment.supported_warning_signals
    assert assessment.overall_outcome != "HIGH_RISK"


def test_unsupported_legacy_high_risk_cannot_establish_fraud():
    scam = finding("ScamAgent", "HIGH_RISK", {"risk_signals": ["CREDENTIAL_THEFT_DEMAND"]})
    assessment = AssessmentEngine().assess([scam])
    assert not assessment.supported_warning_signals
    assert assessment.warning_strength == 0


def test_upi_only_structured_demand_remains_review_concern():
    scam = finding("ScamAgent", "HIGH_RISK", {"local_scan_completed": True, "risk_signals": ["UPI_PAYMENT_REQUEST"], "reason_code": "CANDIDATE_PAYMENT_DETECTED", "signal_assessments": [{"signal_code": "UPI_PAYMENT_REQUEST", "modality": "active_demand", "contributes_to_verdict": True, "source_quote": "Pay via UPI"}]}, [local_evidence()])
    assessment = AssessmentEngine().assess([scam])
    assert assessment.overall_outcome == "NEEDS_REVIEW"
    assert not assessment.supported_warning_signals


def test_recruiter_actual_dimension_keys_keep_failed_query_visible():
    rec = finding("RecruiterAgent", "VERIFIED", {"provider_status": "PARTIAL", "assessment_dimensions": {"adverse_contact_reports": {"status": "CHECK_UNAVAILABLE", "explanation": "phone timeout"}, "recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"}}, "checks": {"phone_reports": {"provider_status": "FAILED", "search_status": "TIMEOUT"}, "email_reports": {"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}}})
    assessment = AssessmentEngine().assess([rec])
    checks = {c.check_id: c for c in assessment.individual_checks}
    assert checks["RECRUITER_CONTACT_REPUTATION"].execution_status == "unavailable"
    assert checks["RECRUITER_CONTACT_REPUTATION:phone_reports"].execution_status == "unavailable"
    assert checks["RECRUITER_CONTACT_REPUTATION:email_reports"].execution_status == "completed"
    assert checks["RECRUITER_AFFILIATION_CHECK"].resolution_status == "supported"
    parents = {c.parent_check_id for c in assessment.individual_checks if c.parent_check_id}
    applicable = [c for c in assessment.individual_checks if c.applicability and c.check_id not in parents]
    assert assessment.coverage_summary.applicable_checks == len(applicable)


def test_conflicting_findings_are_order_invariant_and_not_clean():
    first = finding("RecruiterAgent", "VERIFIED", {"domain_match": True})
    second = finding("RecruiterAgent", "NEEDS_REVIEW", {"domain_match": False})
    engine = AssessmentEngine()
    assert engine.assess([first, second]).model_dump() == engine.assess([second, first]).model_dump()
    assert any(c.code == "CONFLICTING_AGENT_FINDINGS" for c in engine.assess([first, second]).review_only_concerns)


def test_exact_duplicates_do_not_change_coverage_or_warning_strength():
    findings = clean_findings()
    engine = AssessmentEngine()
    assert engine.assess(findings).model_dump() == engine.assess(findings + findings).model_dump()


def test_stale_initial_verdict_cannot_override_structured_policy():
    findings = clean_findings()
    result = VerdictReasoner().evaluate(*findings, initial_risk_score=.9, initial_risk_level=RiskLevel.CANNOT_VERIFY)
    score, level, _, _ = RiskEngine().compute_risk(findings)
    assert result.verdict == level
    assert result.overall_outcome == "NO_STRONG_RISK_SIGNALS"


def test_report_drops_stale_risk_and_invented_flags():
    findings = clean_findings()
    report = ReportGenerator().generate(1, "Offer", .95, RiskLevel.HIGH_RISK, ExtractedEntities(), findings, ["invented adverse signal"], ["invented green flag"])
    assert report.risk_level == RiskLevel.VERIFIED
    assert report.risk_score == 0
    assert "invented adverse signal" not in report.red_flags
    assert "invented green flag" not in report.green_flags
    assert report.authenticity_status == "UNCONFIRMED"


def test_demo_evidence_is_absent_from_assessment_and_reasoner():
    demo = EvidenceItem(source_url="https://demo.example", title="Synthetic", description="fake", evidence_type="COMPANY", confidence=.99)
    findings = [finding("CompanyAgent", "VERIFIED", {"search_source": "DEMO"}, [demo]), finding("RecruiterAgent"), finding("SalaryAgent"), finding("ScamAgent")]
    assessment = AssessmentEngine().assess(findings)
    assert "https://demo.example" not in assessment.supporting_evidence_refs
    assert not VerdictReasoner().evaluate(*findings, 0).evidence


def test_url_identity_retains_nontracking_query_parameters():
    assert canonicalize_url("https://example.com/report?id=1&utm_source=test") == "https://example.com/report?id=1"
    assert canonicalize_url("https://example.com/report?id=1") != canonicalize_url("https://example.com/report?id=2")


def test_applicable_salary_outage_prevents_clean_overall_outcome():
    findings = clean_findings()
    findings[2] = finding("SalaryAgent", "CANNOT_VERIFY", {"offered_salary": "INR 7 LPA", "provider_status": "FAILED"})
    assert AssessmentEngine().assess(findings).overall_outcome == "CANNOT_VERIFY"
