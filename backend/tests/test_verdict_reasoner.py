import pytest
from app.schemas.analysis import (
    RiskLevel,
    AgentFinding,
    EvidenceItem,
    VerdictReason,
    VerdictResult,
)
from app.services.risk.verdict_reasoner import VerdictReasoner


@pytest.fixture
def reasoner():
    return VerdictReasoner()


def test_verified_offer(reasoner):
    """
    Genuine enterprise offer:
    - Company verified (2 sources)
    - Recruiter verified (1 source)
    - Salary verified (1 source)
    - Scam check verified (1 source)
    Total 5 sources, high confidence -> VERIFIED
    """
    comp = AgentFinding(
        agent_name="CompanyAgent",
        verdict="VERIFIED",
        confidence=0.95,
        summary="Official corporate website and MCA status confirmed.",
        evidence=[
            EvidenceItem(source_url="https://infosys.com", title="Site", description="Valid", evidence_type="COMPANY", confidence=0.98),
            EvidenceItem(source_url="https://mca.gov.in", title="MCA", description="Active", evidence_type="COMPANY", confidence=0.95),
        ]
    )
    rec = AgentFinding(
        agent_name="RecruiterAgent",
        verdict="VERIFIED",
        confidence=0.92,
        summary="Recruiter email domain aligns with corporate MX record.",
        evidence=[
            EvidenceItem(source_url="https://infosys.com", title="MX", description="Matches", evidence_type="RECRUITER", confidence=0.95)
        ]
    )
    sal = AgentFinding(
        agent_name="SalaryAgent",
        verdict="VERIFIED",
        confidence=0.88,
        summary="Salary matches AmbitionBox baseline.",
        evidence=[
            EvidenceItem(source_url="https://ambitionbox.com", title="Sal", description="Aligned", evidence_type="SALARY", confidence=0.90)
        ]
    )
    scam = AgentFinding(
        agent_name="ScamAgent",
        verdict="VERIFIED",
        confidence=0.95,
        summary="No advance fee requests detected.",
        evidence=[
            EvidenceItem(source_url="https://cybercrime.gov.in", title="Clean", description="No flags", evidence_type="SCAM_REPORT", confidence=0.95)
        ]
    )

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.10,
    )

    assert result.verdict == RiskLevel.VERIFIED
    assert result.confidence >= 0.85
    codes = [rd.code for rd in result.reason_details]
    assert "LEGITIMATE_FOOTPRINT_VERIFIED" in codes
    assert "CLEAN_RECRUITMENT_RECORDS" in codes


def test_obvious_scam(reasoner):
    """
    Obvious scam:
    - ScamAgent flags upfront laptop deposit
    - RecruiterAgent flags free webmail
    - Risk score >= 0.50
    -> HIGH_RISK with explicit reasoning codes
    """
    comp = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.90, summary="TCS exists", evidence=[])
    rec = AgentFinding(
        agent_name="RecruiterAgent",
        verdict="HIGH_RISK",
        confidence=0.98,
        summary="Personal webmail rohit.tcs@gmail.com used for corporate hiring.",
        evidence=[
            EvidenceItem(source_url="https://cybercrime.gov.in", title="Webmail scam", description="Free webmail flag", evidence_type="RECRUITER", confidence=0.98)
        ]
    )
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.85, summary="Salary reasonable", evidence=[])
    scam = AgentFinding(
        agent_name="ScamAgent",
        verdict="HIGH_RISK",
        confidence=0.99,
        summary="Critical scam markers identified! Upfront fee demand (INR 15,000) detected.",
        evidence=[
            EvidenceItem(source_url="https://cybercrime.gov.in", title="Advance fee", description="Illegal deposit", evidence_type="SCAM_REPORT", confidence=0.99)
        ]
    )

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.85,
    )

    assert result.verdict == RiskLevel.HIGH_RISK
    codes = [rd.code for rd in result.reason_details]
    assert "ADVANCE_FEE_DETECTED" in codes
    assert "PERSONAL_EMAIL_DOMAIN" in codes


def test_legitimate_startup(reasoner):
    """
    Edge Case: Legitimate Startup Test
    Company: NewAI Labs Pvt Ltd
    Recruiter: hr@newailabs.ai
    No fees, reasonable salary, few public references (<2 evidence sources)
    Expected: CANNOT_VERIFY (not HIGH_RISK!)
    """
    comp = AgentFinding(
        agent_name="CompanyAgent",
        verdict="UNVERIFIED",
        confidence=0.40,
        summary="Unable to find established corporate registration for NewAI Labs Pvt Ltd.",
        evidence=[
            EvidenceItem(
                source_url="https://notfound.domain",
                title="Search Attempt",
                description="Few or no search results",
                evidence_type="COMPANY",
                confidence=0.30
            )
        ]
    )
    rec = AgentFinding(
        agent_name="RecruiterAgent",
        verdict="VERIFIED",
        confidence=0.75,
        summary="Recruiter email domain matches domain 'newailabs.ai'.",
        evidence=[]
    )
    sal = AgentFinding(
        agent_name="SalaryAgent",
        verdict="VERIFIED",
        confidence=0.80,
        summary="Salary fits expected salary bands.",
        evidence=[]
    )
    scam = AgentFinding(
        agent_name="ScamAgent",
        verdict="VERIFIED",
        confidence=0.90,
        summary="No advance fee requests detected.",
        evidence=[]
    )

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.25,  # Moderate score due to unverified company, but NOT >= 0.50
    )

    assert result.verdict == RiskLevel.CANNOT_VERIFY
    assert result.verdict != RiskLevel.HIGH_RISK
    codes = [rd.code for rd in result.reason_details]
    assert "INSUFFICIENT_SEARCH_RESULTS" in codes or "NO_PUBLIC_EVIDENCE" in codes


def test_mixed_evidence_salary_outlier(reasoner):
    """
    Mixed Evidence:
    - Company verified with 2 sources
    - Recruiter verified with 1 source
    - Salary Agent flags salary bait (50,000 per day) as NEEDS_REVIEW
    -> NEEDS_REVIEW
    """
    comp = AgentFinding(
        agent_name="CompanyAgent",
        verdict="VERIFIED",
        confidence=0.95,
        summary="Company exists",
        evidence=[
            EvidenceItem(source_url="https://example.com", title="Domain", description="Valid", evidence_type="COMPANY", confidence=0.95),
            EvidenceItem(source_url="https://mca.gov.in", title="MCA", description="Active", evidence_type="COMPANY", confidence=0.90),
        ]
    )
    rec = AgentFinding(
        agent_name="RecruiterAgent",
        verdict="VERIFIED",
        confidence=0.90,
        summary="Corporate domain verified",
        evidence=[
            EvidenceItem(source_url="https://example.com", title="MX", description="Corporate", evidence_type="RECRUITER", confidence=0.90)
        ]
    )
    sal = AgentFinding(
        agent_name="SalaryAgent",
        verdict="NEEDS_REVIEW",
        confidence=0.85,
        summary="The stated compensation of '₹50,000 per day' is unusually high and may be used as bait.",
        evidence=[
            EvidenceItem(source_url="https://ambitionbox.com", title="Bait", description="Outlier", evidence_type="SALARY", confidence=0.85)
        ]
    )
    scam = AgentFinding(
        agent_name="ScamAgent",
        verdict="VERIFIED",
        confidence=0.90,
        summary="No advance fee detected",
        evidence=[]
    )

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.30,
    )

    assert result.verdict == RiskLevel.NEEDS_REVIEW
    codes = [rd.code for rd in result.reason_details]
    assert "SALARY_OUTLIER" in codes


def test_cannot_verify_when_evidence_count_is_one(reasoner):
    """
    Rule: 1 source with 95% confidence is still weak verification.
    evidence_count < 2 triggers CANNOT_VERIFY when no scam markers exist.
    """
    comp = AgentFinding(
        agent_name="CompanyAgent",
        verdict="VERIFIED",
        confidence=0.95,
        summary="Company domain found",
        evidence=[
            EvidenceItem(source_url="https://smallco.com", title="Domain", description="Found", evidence_type="COMPANY", confidence=0.95)
        ]
    )
    rec = AgentFinding(agent_name="RecruiterAgent", verdict="VERIFIED", confidence=0.80, summary="Email matches", evidence=[])
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.80, summary="Salary normal", evidence=[])
    scam = AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.80, summary="No fee", evidence=[])

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.10,
    )

    # With only 1 evidence source, it must not be falsely declared VERIFIED
    assert result.verdict == RiskLevel.CANNOT_VERIFY


def test_no_evidence_available(reasoner):
    """Zero evidence items available -> CANNOT_VERIFY with NO_PUBLIC_EVIDENCE code."""
    comp = AgentFinding(agent_name="CompanyAgent", verdict="UNVERIFIED", confidence=0.3, summary="Nothing found", evidence=[])
    rec = AgentFinding(agent_name="RecruiterAgent", verdict="UNVERIFIED", confidence=0.3, summary="Nothing found", evidence=[])
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.8, summary="Normal", evidence=[])
    scam = AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.8, summary="No fee", evidence=[])

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.20,
    )

    assert result.verdict == RiskLevel.CANNOT_VERIFY
    codes = [rd.code for rd in result.reason_details]
    assert "NO_PUBLIC_EVIDENCE" in codes


def test_documented_confidence_formula(reasoner):
    """
    Verify confidence calculation matches documented formula:
    evidence_strength = min(evidence_count / 4.0, 1.0)
    confidence = round((average_agent_confidence + evidence_strength) / 2.0, 2)
    """
    ev1 = EvidenceItem(source_url="http://a.com", title="A", description="A", evidence_type="COMPANY", confidence=0.8)
    ev2 = EvidenceItem(source_url="http://b.com", title="B", description="B", evidence_type="RECRUITER", confidence=0.8)

    comp = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.80, summary="Comp", evidence=[ev1])
    rec = AgentFinding(agent_name="RecruiterAgent", verdict="VERIFIED", confidence=0.80, summary="Rec", evidence=[ev2])
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.80, summary="Sal", evidence=[])
    scam = AgentFinding(agent_name="ScamAgent", verdict="VERIFIED", confidence=0.80, summary="Scam", evidence=[])

    # average_agent_confidence = (0.8 + 0.8 + 0.8 + 0.8) / 4 = 0.80
    # evidence_count = 2 -> evidence_strength = 2/4 = 0.50
    # expected_confidence = (0.80 + 0.50) / 2.0 = 0.65

    result = reasoner.evaluate(
        company_result=comp,
        recruiter_result=rec,
        salary_result=sal,
        scam_result=scam,
        initial_risk_score=0.10,
    )

    assert result.confidence == 0.65
