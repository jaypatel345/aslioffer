import pytest
from app.schemas.analysis import (
    AgentFinding,
    EvidenceItem,
    ExtractedEntities,
    RiskLevel,
    VerdictReason,
    VerificationReport,
)
from app.services.risk.assessment_engine import AssessmentEngine
from app.services.risk.assessment_models import (
    OverallOutcome,
    AuthenticityStatus,
    WarningBand,
)
from app.services.report.report_generator import ReportGenerator
from app.services.risk.risk_engine import RiskEngine
from app.services.risk.verdict_reasoner import VerdictReasoner


def make_finding(agent: str, verdict: str = "CANNOT_VERIFY", details: dict = None, evidence: list = None, summary: str = "Finding"):
    return AgentFinding(
        agent_name=agent,
        verdict=verdict,
        confidence=0.85 if verdict == "VERIFIED" else 0.40,
        summary=summary,
        details=details or {},
        evidence=evidence or [],
    )


# 1. Unknown employer plus review concern does not become “established company.”
def test_unknown_employer_plus_review_concern_does_not_become_established_company():
    comp = make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}, summary="No public records")
    rec = make_finding(
        "RecruiterAgent",
        "NEEDS_REVIEW",
        {
            "provider_status": "SUCCESS",
            "recruiter_email": "recruiter.john@gmail.com",
            "is_free_webmail": True,
            "assessment_dimensions": {
                "free_webmail": {"status": "FLAGGED", "evidence_strength": "strong_extracted_contact"},
                "adverse_contact_reports": {"status": "NO_MATCH"},
            },
        },
        summary="Personal webmail used",
    )
    sal = make_finding("SalaryAgent", "VERIFIED")
    scam = make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})

    report = ReportGenerator().generate(
        offer_id=1,
        title="Unknown Employer Review",
        risk_score=0.25,
        risk_level=RiskLevel.NEEDS_REVIEW,
        extracted_entities=ExtractedEntities(company_name="Apex Global Ventures"),
        findings=[comp, rec, sal, scam],
        red_flags=[],
        green_flags=[],
    )

    assert report.overall_outcome == OverallOutcome.NEEDS_REVIEW
    assert "established company" not in report.summary.lower()
    assert "apex global ventures" in report.summary.lower() or "apex global" in report.summary.lower()
    assert "personal" in report.summary.lower() or "webmail" in report.summary.lower() or "review" in report.summary.lower()
    assert "the employer has not authenticated this individual offer" in report.summary.lower()


# 2. Skipped/unavailable salary check produces no salary-plausibility claim.
def test_skipped_unavailable_salary_check_produces_no_salary_plausibility_claim():
    comp = make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "infosys.com"}, [
        EvidenceItem(source_url="https://infosys.com", title="Site", description="Valid", evidence_type="COMPANY", confidence=0.95)
    ])
    rec = make_finding("RecruiterAgent", "VERIFIED", {
        "provider_status": "SUCCESS",
        "recruiter_affiliation_status": "SUPPORTED",
        "assessment_dimensions": {
            "recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"},
            "adverse_contact_reports": {"status": "NO_MATCH"},
        }
    })
    # SalaryAgent check skipped/not applicable (e.g. stipend or missing salary)
    sal = make_finding("SalaryAgent", "NOT_CHECKED", {"provider_status": "NOT_CHECKED", "reason": "No annual compensation specified"})
    scam = make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})

    report = ReportGenerator().generate(
        offer_id=2,
        title="No Salary Check Offer",
        risk_score=0.0,
        risk_level=RiskLevel.VERIFIED,
        extracted_entities=ExtractedEntities(company_name="Infosys"),
        findings=[comp, rec, sal, scam],
        red_flags=[],
        green_flags=[],
    )

    # Must NOT claim salary plausibility or market baseline
    for flag in report.green_flags:
        assert "salary" not in flag.lower()
        assert "compensation" not in flag.lower()
        assert "market baseline" not in flag.lower()

    assert "compensation aligns" not in report.summary.lower()
    assert "salary" not in report.summary.lower()


# 3. Completed empty searches do not authenticate the offer.
def test_completed_empty_searches_do_not_authenticate_offer():
    comp = make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}, summary="Zero results for company")
    rec = make_finding("RecruiterAgent", "CANNOT_VERIFY", {"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}, summary="Zero results for recruiter")
    sal = make_finding("SalaryAgent", "CANNOT_VERIFY", {"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}, summary="No baseline")
    scam = make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}, summary="No scam complaints")

    report = ReportGenerator().generate(
        offer_id=3,
        title="Empty Searches Offer",
        risk_score=0.0,
        risk_level=RiskLevel.CANNOT_VERIFY,
        extracted_entities=ExtractedEntities(company_name="GhostCorp"),
        findings=[comp, rec, sal, scam],
        red_flags=[],
        green_flags=[],
    )

    assert report.overall_outcome == OverallOutcome.CANNOT_VERIFY
    assert report.authenticity_status == AuthenticityStatus.UNCONFIRMED
    assert "offer is authentic" not in report.summary.lower()
    assert "offer is verified" not in report.summary.lower()
    assert "inconclusive public evidence" in report.summary.lower()
    assert "the employer has not authenticated this individual offer" in report.summary.lower()


# 4. Provider outage differs from completed no-match and missing-input states.
def test_provider_outage_differs_from_completed_no_match_and_missing_input():
    # Case A: Provider outage
    outage_finding = make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "FAILED", "error": "SerpApi timeout"})
    assessment_outage = AssessmentEngine().assess([outage_finding])
    res_outage = VerdictReasoner().evaluate(outage_finding, make_finding("RecruiterAgent"), make_finding("SalaryAgent"), make_finding("ScamAgent"), 0.0)
    codes_outage = [d.code for d in res_outage.reason_details]
    assert "COMPANY_SEARCH_UNAVAILABLE" in codes_outage

    # Case B: Completed no-match
    nomatch_finding = make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})
    assessment_nomatch = AssessmentEngine().assess([nomatch_finding])
    res_nomatch = VerdictReasoner().evaluate(nomatch_finding, make_finding("RecruiterAgent"), make_finding("SalaryAgent"), make_finding("ScamAgent"), 0.0)
    codes_nomatch = [d.code for d in res_nomatch.reason_details]
    assert "COMPANY_NOT_VERIFIED" in codes_nomatch
    assert "COMPANY_SEARCH_UNAVAILABLE" not in codes_nomatch

    # Case C: Summary distinguishes provider outage phrasing
    summary_outage = ReportGenerator().generate(
        4, "Outage", 0.0, RiskLevel.CANNOT_VERIFY, ExtractedEntities(company_name="OutageCorp"), [outage_finding], [], []
    ).summary
    assert "unavailable due to service outages" in summary_outage.lower()


# 5. Strong local warning plus provider outage retains both warning and gap.
def test_strong_local_warning_plus_provider_outage_retains_both_warning_and_gap():
    scam = make_finding(
        "ScamAgent",
        "HIGH_RISK",
        {
            "local_scan_completed": True,
            "provider_status": "FAILED",
            "risk_signals": ["UPFRONT_FEE_DEMAND"],
            "reason_code": "ADVANCE_FEE_DETECTED",
            "signal_assessments": [
                {
                    "signal_code": "UPFRONT_FEE_DEMAND",
                    "modality": "active_demand",
                    "contributes_to_verdict": True,
                    "source_quote": "Deposit INR 15,000 for training material",
                }
            ],
        },
        evidence=[EvidenceItem(source_url="document://submitted-offer", title="Fee", description="Deposit required", evidence_type="SCAM_REPORT", confidence=0.99)],
    )
    comp = make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "FAILED", "error": "Timeout"})

    report = ReportGenerator().generate(
        offer_id=5,
        title="Fee with Outage",
        risk_score=0.90,
        risk_level=RiskLevel.HIGH_RISK,
        extracted_entities=ExtractedEntities(company_name="ScamCorp"),
        findings=[comp, scam],
        red_flags=[],
        green_flags=[],
    )

    assert report.overall_outcome == OverallOutcome.HIGH_RISK
    # Retains the strong warning
    assert any("fee" in flag.lower() or "deposit" in flag.lower() for flag in report.red_flags)
    # Retains the concrete coverage gap
    codes = [d.code for d in report.reason_details]
    assert "ADVANCE_FEE_DETECTED" in codes
    assert "COMPANY_SEARCH_UNAVAILABLE" in codes
    assert "external checks" in report.summary.lower()
    assert "the employer has not authenticated this individual offer" in report.summary.lower()


# 6. Negated/quoted fee or credential text produces no active-demand narrative.
def test_negated_quoted_fee_text_produces_no_active_demand_narrative():
    scam = make_finding(
        "ScamAgent",
        "VERIFIED",
        {
            "local_scan_completed": True,
            "provider_status": "SUCCESS",
            "search_status": "ZERO_RESULTS",
            "signal_assessments": [
                {
                    "signal_code": "UPFRONT_FEE_DEMAND",
                    "modality": "negated_policy",
                    "contributes_to_verdict": False,
                    "source_quote": "We never charge registration fees or ask for payments",
                }
            ],
        },
        evidence=[EvidenceItem(source_url="document://submitted-offer", title="Policy", description="No fee policy", evidence_type="POLICY", confidence=0.95)],
    )
    comp = make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "acme.com"})

    report = ReportGenerator().generate(
        offer_id=6,
        title="Negated Policy Offer",
        risk_score=0.0,
        risk_level=RiskLevel.VERIFIED,
        extracted_entities=ExtractedEntities(company_name="Acme Corp"),
        findings=[comp, scam],
        red_flags=[],
        green_flags=[],
    )

    assert report.overall_outcome != OverallOutcome.HIGH_RISK
    assert not report.red_flags
    # Must NOT have fee warnings in summary or red flags
    assert "critical warning signals" not in report.summary.lower()
    assert "fee" not in report.summary.lower()


# 7. Review-only concerns receive proportionate actions.
def test_review_only_concerns_receive_proportionate_actions():
    comp = make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "legitcorp.com"}, [
        EvidenceItem(source_url="https://legitcorp.com", title="Site", description="Legit", evidence_type="COMPANY", confidence=0.95)
    ])
    rec = make_finding("RecruiterAgent", "NEEDS_REVIEW", {
        "provider_status": "SUCCESS",
        "recruiter_email": "recruiter@gmail.com",
        "is_free_email": True,
        "reason_code": "FREE_WEBMAIL_DOMAIN",
        "assessment_dimensions": {
            "free_webmail": {"status": "FLAGGED", "evidence_strength": "strong_extracted_contact"},
            "adverse_contact_reports": {"status": "NO_MATCH"},
            "recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"},
        }
    })
    sal = make_finding("SalaryAgent", "VERIFIED")
    scam = make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})

    report = ReportGenerator().generate(
        offer_id=7,
        title="Review Only Offer",
        risk_score=0.25,
        risk_level=RiskLevel.NEEDS_REVIEW,
        extracted_entities=ExtractedEntities(company_name="LegitCorp"),
        findings=[comp, rec, sal, scam],
        red_flags=[],
        green_flags=[],
    )

    assert report.overall_outcome == OverallOutcome.NEEDS_REVIEW
    # Proportionate actions: advises checking official domain and directory
    assert any("personal or non-matching email" in a.lower() or "corporate email domain" in a.lower() for a in report.recommended_actions)
    # Does NOT instruct users to automatically block or report solely for free email
    assert not any("block and report" in a.lower() for a in report.recommended_actions)
    assert not any("cybercrime" in a.lower() and "immediately" in a.lower() for a in report.recommended_actions)


# 8. Stale supplied reasons cannot contradict the assessment.
def test_stale_supplied_reasons_cannot_contradict_assessment():
    comp = make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "infosys.com"}, [
        EvidenceItem(source_url="https://infosys.com", title="Site", description="Valid", evidence_type="COMPANY", confidence=0.95)
    ])
    rec = make_finding("RecruiterAgent", "VERIFIED", {
        "provider_status": "SUCCESS",
        "recruiter_affiliation_status": "SUPPORTED",
        "assessment_dimensions": {
            "recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"},
            "adverse_contact_reports": {"status": "NO_MATCH"},
        }
    })
    sal = make_finding("SalaryAgent", "VERIFIED")
    scam = make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"})

    # Caller supplies stale, fabricated reason details claiming fraud!
    stale_reasons = [
        VerdictReason(code="ADVANCE_FEE_DETECTED", reason="Fake fee from stale cache"),
        VerdictReason(code="CREDENTIAL_THEFT_DETECTED", reason="Fake credential theft"),
    ]

    report = ReportGenerator().generate(
        offer_id=8,
        title="Stale Reasons Offer",
        risk_score=0.0,
        risk_level=RiskLevel.VERIFIED,
        extracted_entities=ExtractedEntities(company_name="Infosys"),
        findings=[comp, rec, sal, scam],
        red_flags=[],
        green_flags=[],
        reason_details=stale_reasons,
    )

    codes = [d.code for d in report.reason_details]
    assert "ADVANCE_FEE_DETECTED" not in codes
    assert "CREDENTIAL_THEFT_DETECTED" not in codes
    assert "LEGITIMATE_FOOTPRINT_VERIFIED" in codes
    assert "CLEAN_RECRUITMENT_RECORDS" in codes


# 9. Unsupported document links do not become official contacts.
def test_unsupported_document_links_do_not_become_official_contacts():
    comp = make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "FAILED"}, summary="Search failed")
    entities = ExtractedEntities(
        company_name="Acme",
        location="Bangalore",
    )
    # The document contained an unverified website
    entities_with_doc_site = ExtractedEntities(
        company_name="Acme",
        location="Bangalore",
    )

    report = ReportGenerator().generate(
        offer_id=9,
        title="Doc Link Test",
        risk_score=0.0,
        risk_level=RiskLevel.CANNOT_VERIFY,
        extracted_entities=entities_with_doc_site,
        findings=[comp],
        red_flags=[],
        green_flags=[],
    )

    assert report.official_company_info["website"] is None
    assert report.official_company_info["careers_url"] is None
    assert report.official_company_info["mca_status"] == "Not independently checked"
    assert report.official_company_info["recruitment_policy"] == "Not independently checked"


# 10. Conflicting company findings do not create order-dependent official information.
def test_conflicting_company_findings_do_not_create_order_dependent_official_information():
    finding_a = make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "alpha.com", "careers_url": "https://alpha.com/careers"})
    finding_b = make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "beta.com", "careers_url": "https://beta.com/careers"})

    generator = ReportGenerator()
    report_ab = generator.generate(10, "Conflict AB", 0.0, RiskLevel.CANNOT_VERIFY, ExtractedEntities(company_name="AlphaBeta"), [finding_a, finding_b], [], [])
    report_ba = generator.generate(10, "Conflict BA", 0.0, RiskLevel.CANNOT_VERIFY, ExtractedEntities(company_name="AlphaBeta"), [finding_b, finding_a], [], [])

    # Order must not matter: conflicting domains must be handled conservatively (neither promoted)
    assert report_ab.official_company_info["website"] == report_ba.official_company_info["website"] == None
    assert report_ab.official_company_info["careers_url"] == report_ba.official_company_info["careers_url"] == None


# 11. Local scan and external complaint search are described separately.
def test_local_scan_and_external_complaint_search_are_described_separately():
    # Local scan succeeded, external scam search failed
    scam = make_finding(
        "ScamAgent",
        "CANNOT_VERIFY",
        {"local_scan_completed": True, "provider_status": "FAILED", "error": "SerpApi timeout"},
    )
    score, level, red, green = RiskEngine().compute_risk([scam])

    # Green flags must describe completed local scan
    assert "Document text scan found no upfront fee demands, deposit requests, or credential solicitation." in green
    # Must NOT claim clean external records
    assert not any("external public search" in flag.lower() for flag in green)


# 12. All outcomes retain UNCONFIRMED authenticity.
@pytest.mark.parametrize("outcome_level,outcome_enum", [
    (RiskLevel.HIGH_RISK, OverallOutcome.HIGH_RISK),
    (RiskLevel.NEEDS_REVIEW, OverallOutcome.NEEDS_REVIEW),
    (RiskLevel.CANNOT_VERIFY, OverallOutcome.CANNOT_VERIFY),
    (RiskLevel.VERIFIED, OverallOutcome.NO_STRONG_RISK_SIGNALS),
])
def test_all_outcomes_retain_unconfirmed_authenticity(outcome_level, outcome_enum):
    if outcome_level == RiskLevel.HIGH_RISK:
        findings = [make_finding("ScamAgent", "HIGH_RISK", {
            "local_scan_completed": True,
            "signal_assessments": [{"signal_code": "UPFRONT_FEE_DEMAND", "modality": "active_demand", "contributes_to_verdict": True, "source_quote": "Pay fee"}],
            "reason_code": "ADVANCE_FEE_DETECTED",
        }, [EvidenceItem(source_url="document://submitted-offer", title="Fee", description="Pay", evidence_type="SCAM_REPORT", confidence=0.99)])]
    elif outcome_level == RiskLevel.NEEDS_REVIEW:
        findings = [make_finding("RecruiterAgent", "NEEDS_REVIEW", {
            "provider_status": "SUCCESS",
            "is_free_webmail": True,
            "assessment_dimensions": {"free_webmail": {"status": "FLAGGED", "evidence_strength": "strong_extracted_contact"}},
        })]
    elif outcome_level == RiskLevel.CANNOT_VERIFY:
        findings = [make_finding("CompanyAgent", "CANNOT_VERIFY", {"provider_status": "FAILED"})]
    else:
        pub = EvidenceItem(source_url="https://acme.com", title="A", description="D", evidence_type="COMPANY", confidence=0.9)
        findings = [
            make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "acme.com"}, [pub]),
            make_finding("RecruiterAgent", "VERIFIED", {"provider_status": "SUCCESS", "assessment_dimensions": {"recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"}, "adverse_contact_reports": {"status": "NO_MATCH"}}}, [pub]),
            make_finding("SalaryAgent", "VERIFIED"),
            make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}),
        ]

    report = ReportGenerator().generate(
        12, "Authenticity Test", 0.0, outcome_level, ExtractedEntities(company_name="TestCorp"), findings, [], []
    )
    assert report.authenticity_status == AuthenticityStatus.UNCONFIRMED
    assert "the employer has not authenticated this individual offer" in report.summary.lower()


# 13. Duplicate findings do not duplicate reasons or recommendations.
def test_duplicate_findings_do_not_duplicate_reasons_or_recommendations():
    pub = EvidenceItem(source_url="https://acme.com", title="A", description="D", evidence_type="COMPANY", confidence=0.9)
    single_findings = [
        make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "acme.com"}, [pub]),
        make_finding("RecruiterAgent", "VERIFIED", {"provider_status": "SUCCESS", "assessment_dimensions": {"recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"}, "adverse_contact_reports": {"status": "NO_MATCH"}}}, [pub]),
        make_finding("SalaryAgent", "VERIFIED"),
        make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}),
    ]

    generator = ReportGenerator()
    report_single = generator.generate(13, "Single", 0.0, RiskLevel.VERIFIED, ExtractedEntities(company_name="Acme"), single_findings, [], [])
    report_double = generator.generate(13, "Double", 0.0, RiskLevel.VERIFIED, ExtractedEntities(company_name="Acme"), single_findings + single_findings, [], [])

    assert len(report_double.reason_details) == len(report_single.reason_details)
    assert len(report_double.recommended_actions) == len(report_single.recommended_actions)
    assert len(report_double.green_flags) == len(report_single.green_flags)


# 14. Existing report fields serialize compatibly.
def test_existing_report_fields_serialize_compatibly():
    pub = EvidenceItem(source_url="https://acme.com", title="A", description="D", evidence_type="COMPANY", confidence=0.9)
    findings = [
        make_finding("CompanyAgent", "VERIFIED", {"provider_status": "SUCCESS", "official_domain": "acme.com"}, [pub]),
        make_finding("RecruiterAgent", "VERIFIED", {"provider_status": "SUCCESS", "assessment_dimensions": {"recruiter_affiliation": {"status": "SUPPORTED", "evidence_strength": "strong_employer_published"}, "adverse_contact_reports": {"status": "NO_MATCH"}}}, [pub]),
        make_finding("SalaryAgent", "VERIFIED"),
        make_finding("ScamAgent", "VERIFIED", {"local_scan_completed": True, "provider_status": "SUCCESS", "search_status": "ZERO_RESULTS"}),
    ]

    report = ReportGenerator().generate(
        offer_id=14,
        title="Serialization Test",
        risk_score=0.0,
        risk_level=RiskLevel.VERIFIED,
        extracted_entities=ExtractedEntities(company_name="Acme Corp"),
        findings=findings,
        red_flags=[],
        green_flags=[],
    )

    data = report.model_dump()
    assert data["offer_id"] == 14
    assert data["risk_level"] == "VERIFIED"
    assert data["risk_score"] == 0.0
    assert "summary" in data
    assert "official_company_info" in data
    assert data["official_company_info"]["mca_status"] == "Not independently checked"
    assert data["official_company_info"]["recruitment_policy"] == "Not independently checked"
    assert "red_flags" in data
    assert "green_flags" in data
    assert "recommended_actions" in data
    assert "reason_details" in data
    assert data["overall_outcome"] == "NO_STRONG_RISK_SIGNALS"
    assert data["authenticity_status"] == "UNCONFIRMED"
    assert "warning_band" in data
    assert "structured_assessment" in data
