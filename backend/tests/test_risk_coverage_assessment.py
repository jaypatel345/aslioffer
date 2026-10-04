import pytest
from app.schemas.analysis import (
    RiskLevel,
    AgentFinding,
    EvidenceItem,
    ExtractedEntities,
    VerificationReport,
)
from app.services.risk.assessment_engine import AssessmentEngine, canonicalize_url
from app.services.risk.assessment_models import (
    OverallOutcome,
    AuthenticityStatus,
    WarningBand,
    ExecutionStatus,
    ResolutionStatus,
)
from app.services.risk.risk_engine import RiskEngine
from app.services.risk.verdict_reasoner import VerdictReasoner
from app.services.report.report_generator import ReportGenerator


@pytest.fixture
def engine():
    return AssessmentEngine()


@pytest.fixture
def risk_engine():
    return RiskEngine()


@pytest.fixture
def reasoner():
    return VerdictReasoner()


# 1. All providers unavailable: CANNOT_VERIFY with zero invented adverse signals
def test_all_providers_unavailable_cannot_verify_zero_invented_signals(engine, risk_engine, reasoner):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Provider outage",
            evidence=[],
            details={"provider_status": "FAILED", "error": "Search provider timeout"},
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Provider outage",
            evidence=[],
            details={"provider_status": "FAILED", "error": "Search provider timeout"},
        ),
        AgentFinding(
            agent_name="SalaryAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Provider outage",
            evidence=[],
            details={"provider_status": "FAILED", "error": "Search provider timeout", "offered_salary": "10 LPA"},
        ),
        AgentFinding(
            agent_name="ScamAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="External search failed",
            evidence=[],
            details={"provider_status": "FAILED", "local_scan_completed": True, "error": "Search provider timeout"},
        ),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert assessment.warning_strength == 0.0  # Zero invented adverse points!
    assert assessment.warning_band == WarningBand.NONE
    assert assessment.supported_warning_signals == []
    assert assessment.review_only_concerns == []
    assert assessment.authenticity_status == AuthenticityStatus.UNCONFIRMED
    assert assessment.coverage_summary.unavailable_checks > 0

    score, level, red_flags, green_flags = risk_engine.compute_risk(findings)
    assert score == 0.0
    assert level == RiskLevel.CANNOT_VERIFY
    # Task 9: A successful local document scan is described even when external search is unavailable.
    assert green_flags == ["Document text scan found no upfront fee demands, deposit requests, or credential solicitation."]

    verdict_res = reasoner.evaluate(*findings, initial_risk_score=score, initial_risk_level=level)
    assert verdict_res.verdict == RiskLevel.CANNOT_VERIFY
    assert verdict_res.overall_outcome == OverallOutcome.CANNOT_VERIFY


# 2. Successful empty searches: completed/no_match, not authenticated
def test_successful_empty_searches_completed_no_match_not_authenticated(engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Zero results for company",
            evidence=[],
            details={"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"},
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="No contact matches",
            evidence=[],
            details={"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"},
        ),
        AgentFinding(
            agent_name="SalaryAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="No salary matches",
            evidence=[],
            details={"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS", "offered_salary": "10 LPA"},
        ),
        AgentFinding(
            agent_name="ScamAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Zero results for scam search",
            evidence=[],
            details={"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS", "local_scan_completed": True},
        ),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert assessment.warning_strength == 0.0
    assert assessment.authenticity_status == AuthenticityStatus.UNCONFIRMED

    comp_check = next(c for c in assessment.individual_checks if c.check_id == "COMPANY_IDENTITY_CHECK")
    assert comp_check.execution_status == ExecutionStatus.COMPLETED
    assert comp_check.resolution_status == ResolutionStatus.NO_MATCH


# 3. Explicit credential/fee demand plus search outage: HIGH_RISK with partial or unavailable external coverage
def test_explicit_credential_fee_demand_plus_search_outage(engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Search provider outage",
            evidence=[],
            details={"provider_status": "FAILED", "error": "SerpApi connection refused"},
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Search provider outage",
            evidence=[],
            details={"provider_status": "FAILED", "error": "SerpApi connection refused"},
        ),
        AgentFinding(
            agent_name="SalaryAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Search provider outage",
            evidence=[],
            details={"provider_status": "FAILED", "offered_salary": "12 LPA"},
        ),
        AgentFinding(
            agent_name="ScamAgent",
            verdict="HIGH_RISK",
            confidence=0.98,
            summary="Critical threat: Explicit solicitation of bank OTP and account passwords.",
            evidence=[
                EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Bank OTP / Credential Theft Demand",
                    description="The submitted document solicits candidate bank OTPs.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.99,
                )
            ],
            details={
                "provider_status": "FAILED",
                "local_scan_completed": True,
                "risk_signals": ["CREDENTIAL_THEFT_DEMAND"],
                "reason_code": "CREDENTIAL_THEFT_DETECTED",
                "otp_requested": True,
            },
        ),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.HIGH_RISK
    assert assessment.warning_strength >= 0.90
    assert assessment.warning_band == WarningBand.HIGH
    assert assessment.authenticity_status == AuthenticityStatus.UNCONFIRMED

    local_check = next(c for c in assessment.individual_checks if c.check_id == "LOCAL_DOCUMENT_SCAN")
    assert local_check.execution_status == ExecutionStatus.COMPLETED
    assert local_check.resolution_status == ResolutionStatus.SUPPORTED

    comp_check = next(c for c in assessment.individual_checks if c.check_id == "COMPANY_IDENTITY_CHECK")
    assert comp_check.execution_status == ExecutionStatus.UNAVAILABLE


# 4. Personal email alone: review concern, not critical fraud
def test_personal_email_alone_is_review_concern_not_critical_fraud(engine, risk_engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="TCS website verified",
            evidence=[
                EvidenceItem(source_url="https://tcs.com", title="TCS", description="Official domain", evidence_type="COMPANY", confidence=0.95)
            ],
            details={"official_domain": "tcs.com"},
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="NEEDS_REVIEW",
            confidence=0.85,
            summary="Recruiter contact uses personal webmail domain '@gmail.com' for corporate hiring.",
            evidence=[],
            details={"is_free_email": True, "reason_code": "FREE_WEBMAIL_DOMAIN"},
        ),
        AgentFinding(
            agent_name="SalaryAgent",
            verdict="VERIFIED",
            confidence=0.80,
            summary="Salary fits expected salary bands",
            evidence=[
                EvidenceItem(source_url="https://ambitionbox.com/salary", title="TCS Salary", description="Market baseline", evidence_type="SALARY", confidence=0.85)
            ],
            details={"offered_salary": "4.5 LPA"},
        ),
        AgentFinding(
            agent_name="ScamAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="No local scam indicators detected",
            evidence=[],
            details={"local_scan_completed": True},
        ),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.NEEDS_REVIEW
    assert assessment.warning_strength == 0.25  # Review concern alone is bounded at 0.25
    assert assessment.warning_band == WarningBand.MEDIUM
    assert assessment.supported_warning_signals == []
    assert len(assessment.review_only_concerns) == 1
    assert assessment.review_only_concerns[0].code in ("FREE_WEBMAIL_DOMAIN", "PERSONAL_EMAIL_DOMAIN")

    score, level, red_flags, green_flags = risk_engine.compute_risk(findings)
    assert score == 0.25
    assert level == RiskLevel.NEEDS_REVIEW
    assert level != RiskLevel.HIGH_RISK


# 5. Agency identity supported but mandate unresolved
def test_agency_identity_supported_but_mandate_unresolved(engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="Client company verified",
            evidence=[EvidenceItem(source_url="https://wipro.com", title="Wipro", description="Domain", evidence_type="COMPANY", confidence=0.9)],
            details={"official_domain": "wipro.com"},
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="NEEDS_REVIEW",
            confidence=0.85,
            summary="Recruiter operates under third-party staffing agency. Mandate requires confirmation.",
            evidence=[EvidenceItem(source_url="https://adecco.com", title="Adecco", description="Agency site", evidence_type="RECRUITER", confidence=0.9)],
            details={
                "is_agency": True,
                "agency_authorization_status": "UNCONFIRMED",
                "reason_code": "AGENCY_MANDATE_UNCONFIRMED",
            },
        ),
        AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.80, summary="Normal pay", evidence=[]),
        AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.90, summary="Clean", evidence=[], details={"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.NEEDS_REVIEW
    assert assessment.warning_band == WarningBand.MEDIUM
    agency_check = next(c for c in assessment.individual_checks if c.check_id == "AGENCY_AUTHORIZATION_CHECK")
    assert agency_check.applicability is True
    assert agency_check.resolution_status == ResolutionStatus.UNCONFIRMED


# 6. Matched employer domain without recruiter affiliation
def test_matched_employer_domain_without_recruiter_affiliation(engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="Infosys verified",
            evidence=[EvidenceItem(source_url="https://infosys.com", title="Infosys", description="Site", evidence_type="COMPANY", confidence=0.95)],
            details={"official_domain": "infosys.com"},
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Domain match alone does not authenticate recruiter identity/affiliation.",
            evidence=[],
            details={
                "domain_match": True,
                "recruiter_affiliation_status": "UNCONFIRMED",
                "reason_code": "DOMAIN_MATCH_AFFILIATION_UNCONFIRMED",
            },
        ),
        AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.80, summary="Normal", evidence=[]),
        AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.90, summary="Clean", evidence=[], details={"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert assessment.warning_strength == 0.0
    rec_aff = next(c for c in assessment.individual_checks if c.check_id == "RECRUITER_AFFILIATION_CHECK")
    assert rec_aff.resolution_status == ResolutionStatus.UNCONFIRMED


# 7. Salary anomaly combined with weak recruiter concerns: no automatic fraud
def test_salary_anomaly_combined_with_weak_recruiter_concerns_no_automatic_fraud(engine, risk_engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="Company exists",
            evidence=[EvidenceItem(source_url="https://hcl.com", title="HCL", description="Site", evidence_type="COMPANY", confidence=0.9)],
        ),
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="NEEDS_REVIEW",
            confidence=0.85,
            summary="Free webmail used",
            evidence=[],
            details={"is_free_email": True, "reason_code": "FREE_WEBMAIL_DOMAIN"},
        ),
        AgentFinding(
            agent_name="SalaryAgent",
            verdict="NEEDS_REVIEW",
            confidence=0.85,
            summary="The stated compensation of '50,000 per day' is unusually high.",
            evidence=[],
            details={"anomaly": True, "offered_salary": "50,000 per day", "reason_code": "SALARY_OUTLIER"},
        ),
        AgentFinding(
            agent_name="ScamAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="No local scam indicators",
            evidence=[],
            details={"local_scan_completed": True},
        ),
    ]

    assessment = engine.assess(findings)
    # Combined weak concerns must NEVER cross into HIGH_RISK without supported strong adverse signal
    assert assessment.overall_outcome == OverallOutcome.NEEDS_REVIEW
    assert assessment.overall_outcome != OverallOutcome.HIGH_RISK
    assert assessment.warning_strength == 0.35  # Bounded below 0.45
    assert assessment.warning_band == WarningBand.MEDIUM

    score, level, red_flags, green_flags = risk_engine.compute_risk(findings)
    assert level == RiskLevel.NEEDS_REVIEW
    assert score < 0.50


# 8. Missing essential input versus genuinely optional checks
def test_missing_essential_input_versus_genuinely_optional_checks(engine):
    findings_missing_essential = [
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="No valid recruiter contact provided",
            evidence=[],
            details={"reason_code": "NO_CONTACT_PROVIDED"},
        ),
        AgentFinding(
            agent_name="SalaryAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Monthly stipend",
            evidence=[],
            details={"interpreted_as": "monthly stipend", "offered_salary": "15,000"},
        ),
    ]

    assessment = engine.assess(findings_missing_essential)
    check_dict = {c.check_id: c for c in assessment.individual_checks}

    # Recruiter check was essential -> applicability is True, execution_status is NOT_CHECKED (visible gap)
    rec_check = check_dict["RECRUITER_CONTACT_REPUTATION"]
    assert rec_check.applicability is True
    assert rec_check.execution_status == ExecutionStatus.NOT_CHECKED
    assert rec_check.missing_input is not None

    # Agency check was not mentioned -> genuinely optional -> applicability is False
    agency_check = check_dict["AGENCY_AUTHORIZATION_CHECK"]
    assert agency_check.applicability is False
    assert agency_check.execution_status == ExecutionStatus.NOT_APPLICABLE

    # Monthly stipend cannot be benchmarked -> optional benchmark -> applicability is False
    salary_check = check_dict["COMPENSATION_BENCHMARK"]
    assert salary_check.applicability is False
    assert salary_check.execution_status == ExecutionStatus.NOT_APPLICABLE


# 9. Partial recruiter checks preserving both success and failure
def test_partial_recruiter_checks_preserving_both_success_and_failure(engine):
    findings = [
        AgentFinding(
            agent_name="RecruiterAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="Partial query failure",
            evidence=[EvidenceItem(source_url="https://infosys.com", title="Infosys MX", description="Domain match", evidence_type="RECRUITER", confidence=0.9)],
            details={
                "provider_status": "PARTIAL",
                "domain_match": True,
                "adverse_reports": {"status": "CHECK_UNAVAILABLE"},
                "checks": {
                    "domain_search": {"provider_status": "SUCCESS"},
                    "adverse_phone_search": {"provider_status": "FAILED", "error": "Search timed out"},
                },
            },
        ),
    ]

    assessment = engine.assess(findings)
    check_dict = {c.check_id: c for c in assessment.individual_checks}

    rep_check = check_dict["RECRUITER_CONTACT_REPUTATION"]
    assert rep_check.execution_status == ExecutionStatus.UNAVAILABLE
    assert "unavailable" in rep_check.failure_reason.lower()


# 10. Local scan completion surviving provider failure
def test_local_scan_completion_survives_provider_failure(engine):
    findings = [
        AgentFinding(
            agent_name="ScamAgent",
            verdict="CANNOT_VERIFY",
            confidence=0.0,
            summary="No local scam indicators; external checks failed",
            evidence=[],
            details={
                "local_scan_completed": True,
                "provider_status": "FAILED",
                "error": "External SerpApi unreachable",
            },
        )
    ]

    assessment = engine.assess(findings)
    check_dict = {c.check_id: c for c in assessment.individual_checks}

    local_check = check_dict["LOCAL_DOCUMENT_SCAN"]
    assert local_check.execution_status == ExecutionStatus.COMPLETED
    assert local_check.resolution_status == ResolutionStatus.NO_MATCH

    ext_check = check_dict["EXTERNAL_SCAM_REPORTS"]
    assert ext_check.execution_status == ExecutionStatus.UNAVAILABLE


# 11. Demo results excluded from public verification evidence
def test_demo_results_excluded_from_public_verification_evidence(engine):
    findings = [
        AgentFinding(
            agent_name="CompanyAgent",
            verdict="VERIFIED",
            confidence=0.85,
            summary="Demo company result",
            evidence=[EvidenceItem(source_url="https://demo.example.com", title="Demo", description="Demo result", evidence_type="COMPANY", confidence=0.8)],
            details={"search_source": "DEMO"},
        )
    ]

    assessment = engine.assess(findings)
    comp_check = next(c for c in assessment.individual_checks if c.check_id == "COMPANY_IDENTITY_CHECK")
    assert comp_check.execution_status == ExecutionStatus.UNAVAILABLE
    assert "demo" in comp_check.failure_reason.lower()


# 12. Duplicate findings/evidence not raising strength or coverage
def test_duplicate_findings_and_evidence_not_raising_strength_or_coverage(engine):
    ev1 = EvidenceItem(source_url="https://tcs.com/about", title="About TCS", description="Site", evidence_type="COMPANY", confidence=0.9)
    ev1_dup = EvidenceItem(source_url="https://tcs.com/about/", title="About TCS", description="Site duplicate", evidence_type="COMPANY", confidence=0.9)

    finding1 = AgentFinding(
        agent_name="CompanyAgent",
        verdict="VERIFIED",
        confidence=0.9,
        summary="Company exists",
        evidence=[ev1, ev1_dup],
    )
    # Duplicate finding in the list
    finding2 = AgentFinding(
        agent_name="CompanyAgent",
        verdict="VERIFIED",
        confidence=0.9,
        summary="Company exists duplicate",
        evidence=[ev1],
    )

    assessment = engine.assess([finding1, finding2])
    # The duplicate URL should be deduplicated
    assert len(assessment.supporting_evidence_refs) == 1


# 13. Findings reordered without changing the result
def test_findings_reordered_without_changing_result(engine):
    f_comp = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.9, summary="Comp", evidence=[EvidenceItem(source_url="https://a.com", title="A", description="A", evidence_type="COMPANY", confidence=0.9)])
    f_rec = AgentFinding(agent_name="RecruiterAgent", verdict="NEEDS_REVIEW", confidence=0.8, summary="Free email", evidence=[], details={"is_free_email": True})
    f_sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.8, summary="Sal", evidence=[])
    f_scam = AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.9, summary="Scam", evidence=[], details={"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})

    order_1 = [f_comp, f_rec, f_sal, f_scam]
    order_2 = [f_scam, f_sal, f_rec, f_comp]

    res_1 = engine.assess(order_1)
    res_2 = engine.assess(order_2)

    assert res_1.overall_outcome == res_2.overall_outcome == OverallOutcome.NEEDS_REVIEW
    assert res_1.warning_strength == res_2.warning_strength
    assert res_1.warning_band == res_2.warning_band
    assert res_1.coverage_summary.completion_ratio == res_2.coverage_summary.completion_ratio


# 14. A repeated URL not treated as independent corroboration
def test_repeated_url_not_treated_as_independent_corroboration():
    url = "https://example.com/careers"
    evs = [
        EvidenceItem(source_url=url, title="Title 1", description="Snippet 1", evidence_type="COMPANY", confidence=0.8),
        EvidenceItem(source_url=url, title="Title 2", description="Snippet 2", evidence_type="RECRUITER", confidence=0.8),
    ]
    finding = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.85, summary="Comp", evidence=evs)
    assessment = AssessmentEngine().assess([finding])
    assert len(assessment.supporting_evidence_refs) == 1


# 15. Empty finding list not becoming VERIFIED or fully covered
def test_empty_finding_list_not_becoming_verified_or_fully_covered(engine, risk_engine):
    assessment = engine.assess([])
    assert assessment.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert assessment.overall_outcome != OverallOutcome.NO_STRONG_RISK_SIGNALS
    assert assessment.coverage_summary.completion_ratio == 0.0

    score, level, red, green = risk_engine.compute_risk([])
    assert level == RiskLevel.CANNOT_VERIFY
    assert score == 0.0


# 16. Consistent results from RiskEngine, VerdictReasoner and report integration
def test_consistent_results_from_risk_engine_verdict_reasoner_and_report():
    comp = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.95, summary="Infosys exists", evidence=[EvidenceItem(source_url="https://infosys.com", title="Site", description="Valid", evidence_type="COMPANY", confidence=0.95)])
    rec = AgentFinding(agent_name="RecruiterAgent", verdict="VERIFIED", confidence=0.90, summary="Infosys email", evidence=[EvidenceItem(source_url="https://infosys.com", title="MX", description="Aligns", evidence_type="RECRUITER", confidence=0.90)])
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.85, summary="Pay matches", evidence=[])
    scam = AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.95, summary="Clean", evidence=[], details={"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})

    findings = [comp, rec, sal, scam]

    score, level, red, green = RiskEngine().compute_risk(findings)
    reasoner_res = VerdictReasoner().evaluate(comp, rec, sal, scam, score, level)

    assert level == reasoner_res.verdict == RiskLevel.VERIFIED
    assert reasoner_res.overall_outcome == OverallOutcome.NO_STRONG_RISK_SIGNALS
    assert reasoner_res.authenticity_status == AuthenticityStatus.UNCONFIRMED

    report = ReportGenerator().generate(
        offer_id=1,
        title="Infosys Offer",
        risk_score=score,
        risk_level=level,
        extracted_entities=ExtractedEntities(company_name="Infosys"),
        findings=findings,
        red_flags=red,
        green_flags=green,
        reason_details=reasoner_res.reason_details,
        structured_assessment=reasoner_res.structured_assessment,
    )

    assert report.risk_level == RiskLevel.VERIFIED
    assert report.overall_outcome == OverallOutcome.NO_STRONG_RISK_SIGNALS
    assert report.authenticity_status == AuthenticityStatus.UNCONFIRMED
    assert "employer has not authenticated this individual offer" in report.summary.lower()


# 17. Additive API/schema compatibility
def test_additive_api_schema_compatibility():
    report = VerificationReport(
        offer_id=10,
        title="Test Report",
        risk_level=RiskLevel.NEEDS_REVIEW,
        risk_score=0.25,
        summary="Summary",
        extracted_entities=ExtractedEntities(),
        findings=[],
        red_flags=["Flag 1"],
        green_flags=[],
        official_company_info={},
        recommended_actions=["Action 1"],
        overall_outcome=OverallOutcome.NEEDS_REVIEW,
        authenticity_status=AuthenticityStatus.UNCONFIRMED,
        warning_band=WarningBand.MEDIUM,
    )

    json_dict = report.model_dump()
    assert json_dict["risk_level"] == "NEEDS_REVIEW"
    assert json_dict["overall_outcome"] == "NEEDS_REVIEW"
    assert json_dict["authenticity_status"] == "UNCONFIRMED"
    assert json_dict["warning_band"] == "MEDIUM"


# 18. NO_STRONG_RISK_SIGNALS still carrying authenticity_status=UNCONFIRMED
def test_no_strong_risk_signals_carries_authenticity_unconfirmed(engine):
    findings = [
        AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.9, summary="Comp", evidence=[EvidenceItem(source_url="https://google.com", title="Site", description="Site", evidence_type="COMPANY", confidence=0.9)]),
        AgentFinding(agent_name="RecruiterAgent", verdict="VERIFIED", confidence=0.9, summary="Rec", evidence=[EvidenceItem(source_url="https://google.com", title="Domain", description="Domain", evidence_type="RECRUITER", confidence=0.9)]),
        AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.8, summary="Sal", evidence=[]),
        AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.9, summary="Scam", evidence=[], details={"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}),
    ]

    assessment = engine.assess(findings)
    assert assessment.overall_outcome == OverallOutcome.NO_STRONG_RISK_SIGNALS
    assert assessment.authenticity_status == AuthenticityStatus.UNCONFIRMED
    assert "unconfirmed" in assessment.policy_explanation.lower()
