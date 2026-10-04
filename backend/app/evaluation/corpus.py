"""
Offline evaluation corpus loader and definitions for AsliOffer (Task 13).

Defines the EvaluationCase data structure and provides deterministic loading
and serialization for the 24 offline evaluation cases covering all required scenarios:
- Explicit upfront payment demands
- Credential or OTP demands
- Plausible employer impersonation
- Lookalike application destinations
- Legitimate recruitment with corroborated public records
- Authorized recruitment agencies
- Small employers with sparse public footprints
- Negated payment demands and quoted scam warnings
- Candidate/recruiter contact separation
- Matching vacancies that do not authenticate individual offers
- Different role seniority and specializations
- Closed or expired vacancies
- Exact versus partial requisition matches
- Private offer references
- Associated versus unestablished ATS tenants
- Independently published confirmation contacts
- Submitted-only or negatively described contacts
- Empty successful searches
- Provider failure
- Search-budget exhaustion
- Investigation deadlines
- Strong warnings surviving vacancy corroboration
"""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.contract import (
    CaseInput,
    ClaimKind,
    ConfirmedClaim,
    ExtractionStatus,
    OverallOutcome,
    SourceType,
    CONTRACT_VERSION,
)
from app.services.investigation.budget import InvestigationBudget

CORPUS_DATA_DIR = Path(__file__).resolve().parent / "data"


class CaseInputSpec(BaseModel):
    case_id: int
    run_id: str
    source_type: SourceType = SourceType.TEXT
    redacted_text: str
    confirmed_claims: List[ConfirmedClaim] = Field(default_factory=list)
    demo_mode: bool = False

    def to_case_input(self) -> CaseInput:
        return CaseInput(
            contract_version=CONTRACT_VERSION,
            case_id=self.case_id,
            run_id=self.run_id,
            source_type=self.source_type,
            redacted_text=self.redacted_text,
            confirmed_claims=self.confirmed_claims,
            demo_mode=self.demo_mode,
        )


class BudgetSpec(BaseModel):
    max_search_calls: int = 8
    max_followup_calls: int = 3
    max_concurrent_calls: int = 3
    deadline_seconds: float = 15.0

    def to_investigation_budget(self) -> InvestigationBudget:
        return InvestigationBudget(
            max_search_calls=self.max_search_calls,
            max_followup_calls=self.max_followup_calls,
            max_concurrent_calls=self.max_concurrent_calls,
            deadline_seconds=self.deadline_seconds,
        )


class EvaluationCase(BaseModel):
    case_id: str
    title: str
    description: str
    labels: Dict[str, Any] = Field(default_factory=dict)
    case_input: CaseInputSpec
    budget: Optional[BudgetSpec] = None
    search_mock: Dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str
    allowed_outcomes: List[str] = Field(default_factory=list)
    expected_claim_statuses: Dict[str, str] = Field(default_factory=dict)
    required_behaviors: List[str] = Field(default_factory=list)
    forbidden_behaviors: List[str] = Field(default_factory=list)
    planted_secrets: List[str] = Field(default_factory=list)
    rationale: str

    def get_allowed_outcomes(self) -> List[str]:
        if self.allowed_outcomes:
            return self.allowed_outcomes
        return [self.expected_outcome]


def get_default_corpus_cases() -> List[EvaluationCase]:
    """Constructs the canonical 24 evaluation cases deterministically."""
    cases = []

    # -------------------------------------------------------------------------
    # 1. EVAL-01: Explicit Upfront Payment Demand
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-01-UPFRONT-FEE-DEMAND",
        title="Explicit Upfront Fee Demand",
        description="Candidate offered a Graduate Engineer Trainee position but instructed to pay refundable laptop security deposit via UPI.",
        labels={
            "scenario_group": "threat_cases",
            "category": "upfront_fee_demand",
            "threat_category": "advance_fee_fraud",
            "primary_entity": "Nimbus Infotech Ltd",
        },
        case_input=CaseInputSpec(
            case_id=101,
            run_id="run_eval_01_fee",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Nimbus Infotech Ltd. Congratulations! You have been selected for Graduate Engineer Trainee.\n"
                "Deposit a refundable laptop security fee of INR 15,000 via UPI to nimbus.onboarding@okaxis within 24 hours.\n"
                "Contact: priya.nimbus@gmail.com"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Nimbus Infotech Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://www.nimbusinfotech.example/", "title": "Nimbus Infotech Ltd", "snippet": "IT services provider."}],
                },
                "Nimbus Infotech Ltd recruitment fraud email domain fee": {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.nimbusinfotech.example/fraud-alert", "title": "Fraud Alert", "snippet": "Nimbus never asks for security deposits."}],
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="HIGH_RISK",
        allowed_outcomes=["HIGH_RISK"],
        expected_claim_statuses={"payment_request": "CONTRADICTED"},
        required_behaviors=["authenticity_unconfirmed", "strong_warning_present"],
        forbidden_behaviors=["fake_verification"],
        rationale="Mandatory upfront fee demands must result in HIGH_RISK outcome.",
    ))

    # -------------------------------------------------------------------------
    # 2. EVAL-02: Credential or OTP Demands
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-02-BANK-OTP-CREDENTIAL-DEMAND",
        title="Explicit Bank OTP / Credential Theft Demand",
        description="Recruiter letter instructs candidate to provide NetBanking password and confirm bank OTP for salary account activation.",
        labels={
            "scenario_group": "threat_cases",
            "category": "credential_otp_theft",
            "threat_category": "credential_theft",
            "primary_entity": "Horizon Dynamics",
        },
        case_input=CaseInputSpec(
            case_id=102,
            run_id="run_eval_02_otp",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Horizon Dynamics HR onboarding.\n"
                "To activate your payroll direct deposit, provide your NetBanking password and the 6-digit OTP sent to your phone.\n"
                "Contact: onboarding@horizondynamics.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Horizon Dynamics" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://horizondynamics.example/", "title": "Horizon Dynamics", "snippet": "Enterprise software."}],
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="HIGH_RISK",
        allowed_outcomes=["HIGH_RISK"],
        required_behaviors=["authenticity_unconfirmed", "credential_theft_warning"],
        forbidden_behaviors=["fake_verification"],
        rationale="Credential or OTP demands constitute high-risk financial threats.",
    ))

    # -------------------------------------------------------------------------
    # 3. EVAL-03: Task Scam / Payment to Unlock Earnings
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-03-TASK-SCAM-UNLOCK-EARNINGS",
        title="Payment to Unlock Job / Task Scam Extortion",
        description="Candidate invited to complete tasks and told to deposit money to unlock accumulated salary.",
        labels={
            "scenario_group": "threat_cases",
            "category": "payment_to_unlock_earnings",
            "threat_category": "task_scam_extortion",
            "primary_entity": "Global Media Task Hub",
        },
        case_input=CaseInputSpec(
            case_id=103,
            run_id="run_eval_03_task",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Global Media Task Hub. You completed 30 rating tasks and earned INR 8,500.\n"
                "To withdraw your salary balance, pay INR 2,500 security deposit to upgrade to VIP level.\n"
                "UPI payment to taskmgr@okicici."
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {},
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="HIGH_RISK",
        allowed_outcomes=["HIGH_RISK"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Demands to pay money to unlock salary represent advance fee extortion.",
    ))

    # -------------------------------------------------------------------------
    # 4. EVAL-04: Lookalike Application Destination
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-04-LOOKALIKE-APPLICATION-DESTINATION",
        title="Lookalike Application Portal Destination",
        description="Offer letter mimics a major IT employer but directs candidate to upload documents at lookalike domain tcs-careers-portal.example.",
        labels={
            "scenario_group": "ambiguous_unresolved",
            "category": "lookalike_domain",
            "threat_category": "domain_impersonation",
            "primary_entity": "Tata Consultancy Services Ltd",
        },
        case_input=CaseInputSpec(
            case_id=104,
            run_id="run_eval_04_lookalike",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Tata Consultancy Services Ltd. Offer Reference: TCS/2026/0912.\n"
                "Role: Systems Analyst. Package: INR 6,50,000 per annum.\n"
                "Submit all onboarding documents exclusively through our official recruitment portal at https://tcs-careers-portal.example/apply.\n"
                "Recruiter: r.verma@tcs-careers-portal.example"
            ),
            confirmed_claims=[
                ConfirmedClaim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="Tata Consultancy Services Ltd", extraction_status=ExtractionStatus.USER_CONFIRMED)
            ],
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Tata Consultancy Services Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://tcs-careers-portal.example/apply", "title": "TCS Portal", "snippet": "Careers portal."}],
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NEEDS_REVIEW"],
        expected_claim_statuses={"application_url": "CONTRADICTED"},
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Lookalike domain must be rejected and application destination marked CONTRADICTED.",
    ))

    # -------------------------------------------------------------------------
    # 5. EVAL-05: Plausible Employer Impersonation
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-05-PLAUSIBLE-EMPLOYER-IMPERSONATION",
        title="Plausible Employer Impersonation with Payment Demand",
        description="Offer uses plausible corporate details from Infosys Limited but demands registration fee.",
        labels={
            "scenario_group": "threat_cases",
            "category": "realistic_impersonation",
            "threat_category": "corporate_impersonation",
            "primary_entity": "Infosys Limited",
        },
        case_input=CaseInputSpec(
            case_id=105,
            run_id="run_eval_05_impersonation",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Infosys Limited, Electronics City, Hosur Road, Bangalore.\n"
                "Appointment for Systems Engineer. Compensation: INR 4,80,000 per annum.\n"
                "Pay an onboarding document verification fee of INR 6,500 to infosys-hr@upi within 48 hours.\n"
                "Contact: recruitment@infosys-careers.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Infosys Limited" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.infosys.example", "careers_url": "https://careers.infosys.example"},
                    "organic_results": [{"link": "https://www.infosys.example", "title": "Infosys - Official Website", "snippet": "Global consulting and IT services."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="HIGH_RISK",
        allowed_outcomes=["HIGH_RISK"],
        required_behaviors=["authenticity_unconfirmed", "strong_warning_present"],
        forbidden_behaviors=["fake_verification"],
        rationale="Fee demand overrides corporate plausibility, producing HIGH_RISK.",
    ))

    # -------------------------------------------------------------------------
    # 6. EVAL-06: Legitimate Recruitment with Corroborated Public Records
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-06-LEGITIMATE-CORROBORATED-PUBLIC-RECORDS",
        title="Legitimate Recruitment with Corroborated Records",
        description="Established employer, verified recruiter email, and active careers portal with independently sourced confirmation route.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "corroborated_recruitment",
            "threat_category": "clean_public_consistency",
            "primary_entity": "Kestrel Systems Pvt Ltd",
        },
        case_input=CaseInputSpec(
            case_id=106,
            run_id="run_eval_06_legit",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Offer of Employment from Kestrel Systems Pvt Ltd.\n"
                "We are pleased to offer you the position of Associate Consultant.\n"
                "Please review the offer details at https://careers.kestrelsystems.example/offers.\n"
                "Regards, Ananya Rao, Talent Acquisition. Contact: ananya.rao@kestrelsystems.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Kestrel Systems Pvt Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {
                        "title": "Kestrel Systems Pvt Ltd",
                        "website": "https://www.kestrelsystems.example",
                        "careers_url": "https://careers.kestrelsystems.example",
                    },
                    "organic_results": [
                        {"link": "https://www.kestrelsystems.example/", "title": "Kestrel Systems — Official Website", "snippet": "Kestrel Systems Pvt Ltd is a technology consulting firm."},
                        {"link": "https://careers.kestrelsystems.example/", "title": "Kestrel Systems Careers Portal", "snippet": "Careers and job offers at Kestrel Systems."},
                        {"link": "https://careers.kestrelsystems.example/team", "title": "Recruitment Team", "snippet": "Contact our talent acquisition recruiter Ananya Rao at ananya.rao@kestrelsystems.example for verification."},
                    ],
                },
                '"ananya.rao@kestrelsystems.example" scam fraud complaint': {
                    "status": "successful", "source": "REAL", "organic_results": []
                },
                '"ananya.rao@kestrelsystems.example" "Kestrel Systems Pvt Ltd"': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.kestrelsystems.example/team", "title": "Ananya Rao", "snippet": "Ananya Rao is Senior Recruiter at Kestrel Systems Pvt Ltd."}]
                },
                '"Kestrel Systems Pvt Ltd" "Associate Consultant" careers job opening': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.kestrelsystems.example/jobs/assoc-consultant", "title": "Associate Consultant", "snippet": "Associate Consultant opening at Kestrel Systems Pvt Ltd."}]
                },
                "Kestrel Systems Pvt Ltd recruitment fraud email domain fee": {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.kestrelsystems.example/policy", "title": "Policy", "snippet": "Kestrel Systems never charges fees."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="NO_STRONG_RISK_SIGNALS",
        allowed_outcomes=["NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed", "has_confirmation_route"],
        forbidden_behaviors=["fake_verification"],
        rationale="Corroborated public records yield NO_STRONG_RISK_SIGNALS while keeping authenticity UNCONFIRMED.",
    ))

    # -------------------------------------------------------------------------
    # 7. EVAL-07: Authorized Recruitment Agencies
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-07-AUTHORIZED-RECRUITMENT-AGENCY",
        title="Authorized Staffing Agency Representation",
        description="Legitimate third-party staffing agency hiring on behalf of corporate client.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "agency_recruitment",
            "threat_category": "third_party_recruitment",
            "primary_entity": "Apex Staffing Solutions",
        },
        case_input=CaseInputSpec(
            case_id=107,
            run_id="run_eval_07_agency",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Apex Staffing Solutions on behalf of Radiant Energy Solutions Ltd.\n"
                "We are processing your application for Software Engineer.\n"
                "Agency contact: contact@apexstaffing.example. Client portal: https://careers.radiantenergy.example."
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions provider."}]
                },
                '"Apex Staffing Solutions" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://www.apexstaffing.example", "title": "Apex Staffing", "snippet": "Licensed recruitment partner for Radiant Energy Solutions Ltd."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NEEDS_REVIEW", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Agency representation requires verification without premature fraud conviction.",
    ))

    # -------------------------------------------------------------------------
    # 8. EVAL-08: Small Employers with Sparse Public Footprints
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-08-SMALL-EMPLOYER-SPARSE-FOOTPRINT",
        title="Small Employer with Sparse Footprint",
        description="Early-stage startup with no corporate website or news footprint, but no adverse reports.",
        labels={
            "scenario_group": "ambiguous_unresolved",
            "category": "sparse_footprint_startup",
            "threat_category": "sparse_evidence",
            "primary_entity": "Acme Pixel Labs",
        },
        case_input=CaseInputSpec(
            case_id=108,
            run_id="run_eval_08_sparse",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Acme Pixel Labs offer for Junior 3D Artist.\n"
                "Monthly stipend: INR 25,000. Start date: November 1.\n"
                "Contact: dev@acmepixellabs.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {},
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Sparse public footprint must yield CANNOT_VERIFY, never a false conviction of fraud.",
    ))

    # -------------------------------------------------------------------------
    # 9. EVAL-09: Negated Payment Demands
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-09-NEGATED-PAYMENT-POLICY",
        title="Negated Payment Policy Statement",
        description="Legitimate company policy explicitly negating fees: 'We never charge a deposit or fee.'",
        labels={
            "scenario_group": "benign_policy",
            "category": "negated_fee_policy",
            "threat_category": "benign_policy_negation",
            "primary_entity": "Apex Global Services",
        },
        case_input=CaseInputSpec(
            case_id=109,
            run_id="run_eval_09_negated",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Apex Global Services employment letter.\n"
                "Important notice: We never charge a security deposit, equipment charge, or registration fee.\n"
                "HR inquiries: hr@apexglobal.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Apex Global Services" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://apexglobal.example/", "title": "Apex Global", "snippet": "Official site."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Negated fee policies must not be misinterpreted as active fee demands.",
    ))

    # -------------------------------------------------------------------------
    # 10. EVAL-10: Quoted Scam Warnings
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-10-QUOTED-SCAM-WARNING",
        title="Quoted Anti-Scam Advisory",
        description="Email footer quotes security advisory warning against impostors demanding money.",
        labels={
            "scenario_group": "benign_policy",
            "category": "quoted_scam_warning",
            "threat_category": "benign_quoted_advisory",
            "primary_entity": "Zenith Global Tech",
        },
        case_input=CaseInputSpec(
            case_id=110,
            run_id="run_eval_10_quoted",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Zenith Global Tech interview invitation.\n"
                "Advisory: Fraudulent individuals may claim to represent Zenith and ask for INR 5,000 for training. Zenith never collects fees.\n"
                "Recruiter: talent@zenithtech.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Zenith Global Tech" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://zenithtech.example/", "title": "Zenith", "snippet": "Zenith Tech careers."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Quoted scam advisories must be distinguished from active extortion.",
    ))

    # -------------------------------------------------------------------------
    # 11. EVAL-11: Candidate vs Recruiter Role Separation
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-11-CANDIDATE-RECRUITER-ROLE-SEPARATION",
        title="Candidate / Recruiter Contact Role Separation",
        description="Message contains candidate personal email and recruiter corporate email; personal email must not be checked as recruiter.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "contact_role_separation",
            "threat_category": "extraction_ambiguity",
            "primary_entity": "Kestrel Systems Pvt Ltd",
        },
        case_input=CaseInputSpec(
            case_id=111,
            run_id="run_eval_11_separation",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Sent to candidate suresh.kumar99@gmail.com by recruiter ananya.rao@kestrelsystems.example.\n"
                "Employer: Kestrel Systems Pvt Ltd. Role: Associate Consultant.\n"
                "Portal: https://careers.kestrelsystems.example."
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Kestrel Systems Pvt Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.kestrelsystems.example", "careers_url": "https://careers.kestrelsystems.example"},
                    "organic_results": [{"link": "https://www.kestrelsystems.example/", "title": "Kestrel Systems", "snippet": "IT consulting."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Candidate personal email must not be evaluated as a recruiter webmail risk.",
    ))

    # -------------------------------------------------------------------------
    # 12. EVAL-12: Matching Vacancies Preserve UNCONFIRMED
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-12-VACANCY-MATCH-PRESERVES-UNCONFIRMED",
        title="Public Vacancy Match Preserves UNCONFIRMED Authenticity",
        description="Matching public vacancy record corroborates role claim while strictly preserving authenticity_status=UNCONFIRMED.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "vacancy_corroboration",
            "threat_category": "corroboration_semantics",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=112,
            run_id="run_eval_12_unconfirmed",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Employment Offer from Radiant Energy Solutions Ltd.\n"
                "Role: Senior DevOps Engineer in Bengaluru.\n"
                "Official careers portal: https://careers.radiantenergy.example/jobs/devops-blr.\n"
                "Recruiter: hr@radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                },
                '"Radiant Energy Solutions Ltd" "Senior DevOps Engineer" careers job opening': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.radiantenergy.example/jobs/devops-blr", "title": "Senior DevOps Engineer", "snippet": "Senior DevOps Engineer opening in Bengaluru."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Public vacancy matches support the role claim but cannot authenticate individual offer issuance.",
    ))

    # -------------------------------------------------------------------------
    # 13. EVAL-13: Role Seniority and Specialization Mismatch
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-13-ROLE-SENIORITY-SPECIALIZATION-MISMATCH",
        title="Role Seniority and Specialization Mismatch",
        description="Offer claims Principal AI Research Scientist, but public careers search only finds Junior Web Developer.",
        labels={
            "scenario_group": "ambiguous_unresolved",
            "category": "role_mismatch",
            "threat_category": "corroboration_distinction",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=113,
            run_id="run_eval_13_seniority",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Offer of employment for Principal AI Research Scientist in Bengaluru.\n"
                "Careers: https://careers.radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                },
                '"Radiant Energy Solutions Ltd" "Principal AI Research Scientist" careers job opening': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.radiantenergy.example/jobs/junior-web", "title": "Junior Web Developer", "snippet": "Entry-level HTML/CSS role."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Material differences in seniority and specialization must prevent false vacancy corroboration.",
    ))

    # -------------------------------------------------------------------------
    # 14. EVAL-14: Closed or Expired Vacancies
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-14-CLOSED-EXPIRED-VACANCY",
        title="Closed or Expired Vacancy Listing",
        description="Search snippet indicates job listing has expired or position has already been closed.",
        labels={
            "scenario_group": "ambiguous_unresolved",
            "category": "expired_vacancy",
            "threat_category": "corroboration_freshness",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=114,
            run_id="run_eval_14_expired",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Offer for Associate Systems Engineer in Bengaluru.\n"
                "Careers: https://careers.radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                },
                '"Radiant Energy Solutions Ltd" "Associate Systems Engineer" careers job opening': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.radiantenergy.example/jobs/assoc-sys", "title": "Job Closed", "snippet": "This vacancy has expired and is no longer accepting applications."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Expired listings do not authenticate active recruitment offers.",
    ))

    # -------------------------------------------------------------------------
    # 15. EVAL-15: Exact Requisition Match
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-15-EXACT-REQUISITION-MATCH",
        title="Exact Requisition Match",
        description="Offer letter contains unique requisition ID REQ-2026-9942 matching official employer careers posting.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "requisition_match",
            "threat_category": "exact_corroboration",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=115,
            run_id="run_eval_15_req",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Job Offer: Software Engineer. Requisition ID: REQ-2026-9942.\n"
                "Apply at https://careers.radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                },
                '"Radiant Energy Solutions Ltd" "REQ-2026-9942"': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.radiantenergy.example/jobs/9942", "title": "REQ-2026-9942 Software Engineer", "snippet": "Requisition REQ-2026-9942 for Software Engineer at Radiant Energy."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Exact requisition match corroborates requisition claim while keeping authenticity UNCONFIRMED.",
    ))

    # -------------------------------------------------------------------------
    # 16. EVAL-16: Private Offer Reference Leak Prevention
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-16-PRIVATE-OFFER-REFERENCE-LEAK-PREVENTION",
        title="Private Offer Reference Protection",
        description="Offer letter contains private token SECRET_TOKEN_77291B which must not be queried or leaked.",
        labels={
            "scenario_group": "ambiguous_unresolved",
            "category": "privacy_leak_prevention",
            "threat_category": "confidential_reference",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=116,
            run_id="run_eval_16_privacy",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd offer.\n"
                "Private verification token: SECRET_TOKEN_77291B. Do not disclose.\n"
                "Contact: hr@radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["leak_secret"],
        planted_secrets=["SECRET_TOKEN_77291B"],
        rationale="Planted confidential tokens must never leak into queries, tool traces, or drafts.",
    ))

    # -------------------------------------------------------------------------
    # 17. EVAL-17: Associated ATS Tenant
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-17-ATS-TENANT-ASSOCIATION",
        title="Associated ATS Tenant Verification",
        description="Application URL uses a known third-party ATS (radiantenergy.greenhouse.io) linked from official employer careers page.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "ats_tenant_association",
            "threat_category": "tenant_association",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=117,
            run_id="run_eval_17_ats",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Submit your onboarding application at https://radiantenergy.greenhouse.io/jobs/401928.\n"
                "Official website: https://www.radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [
                        {"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."},
                        {"link": "https://radiantenergy.greenhouse.io/jobs/401928", "title": "Radiant Energy Greenhouse", "snippet": "Careers powered by Greenhouse for Radiant Energy."}
                    ]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Known employer ATS tenant is corroborated through documented association.",
    ))

    # -------------------------------------------------------------------------
    # 18. EVAL-18: Independently Published Confirmation Contacts
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-18-INDEPENDENT-CONFIRMATION-CONTACT",
        title="Independently Published Offer Confirmation Channel",
        description="Employer publishes dedicated verification email verify-offers@radiantenergy.example on official website.",
        labels={
            "scenario_group": "legitimate_corroborated",
            "category": "confirmation_route",
            "threat_category": "independent_route",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=118,
            run_id="run_eval_18_confirm",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Role: Software Engineer.\n"
                "Careers: https://careers.radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [
                        {"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."},
                        {"link": "https://careers.radiantenergy.example/verify", "title": "Offer Verification", "snippet": "Verify offer letters by emailing verify-offers@radiantenergy.example directly."}
                    ]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed", "has_confirmation_route"],
        forbidden_behaviors=["fake_verification"],
        rationale="Confirmation route correctly targets independently published employer channel.",
    ))

    # -------------------------------------------------------------------------
    # 19. EVAL-19: Submitted-Only Contact Does Not Become Route
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-19-SUBMITTED-CONTACT-DOES-NOT-BECOME-ROUTE",
        title="Submitted Recruiter Contact Excluded from Confirmation Route",
        description="Recruiter email in document (temp-recruiter@unverified.example) is not published by employer and must not be used as confirmation route.",
        labels={
            "scenario_group": "ambiguous_unresolved",
            "category": "route_safety",
            "threat_category": "contact_provenance",
            "primary_entity": "Kestrel Systems Pvt Ltd",
        },
        case_input=CaseInputSpec(
            case_id=119,
            run_id="run_eval_19_submitted_route",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Kestrel Systems Pvt Ltd.\n"
                "Offer of employment. Contact recruiter at temp-recruiter@unverified.example.\n"
                "Official site: https://www.kestrelsystems.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Kestrel Systems Pvt Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://www.kestrelsystems.example", "title": "Kestrel Systems", "snippet": "Official site."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NEEDS_REVIEW", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Unverified recruiter contacts submitted in the document must never become confirmation routes.",
    ))

    # -------------------------------------------------------------------------
    # 20. EVAL-20: Empty Successful Searches
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-20-EMPTY-SUCCESSFUL-SEARCH",
        title="Empty Successful Search Results",
        description="Search provider executes cleanly (HTTP 200) but returns 0 organic results across all queries.",
        labels={
            "scenario_group": "system_and_limits",
            "category": "empty_search_results",
            "threat_category": "unresolved_coverage",
            "primary_entity": "Nexus Horizon Tech Ltd",
        },
        case_input=CaseInputSpec(
            case_id=120,
            run_id="run_eval_20_empty",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Nexus Horizon Tech Ltd.\n"
                "Offer for Cloud Infrastructure Specialist in Hyderabad.\n"
                "Contact: hr@nexushorizon.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {},
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Empty search results indicate missing public records, leading to CANNOT_VERIFY.",
    ))

    # -------------------------------------------------------------------------
    # 21. EVAL-21: Provider Failure Resilience
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-21-PROVIDER-FAILURE-RESILIENCE",
        title="Provider Failure / Rate Limit Resilience",
        description="Search provider experiences outage (HTTP 429 rate limit or timeout); pipeline handles error gracefully.",
        labels={
            "scenario_group": "system_and_limits",
            "category": "provider_failure_or_rate_limit",
            "threat_category": "provider_outage",
            "primary_entity": "Vertex Dynamics Ltd",
        },
        case_input=CaseInputSpec(
            case_id=121,
            run_id="run_eval_21_outage",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Vertex Dynamics Ltd.\n"
                "Offer for Senior Database Administrator.\n"
                "Contact: hr@vertexdynamics.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {},
            "default_response": {"status": "failed", "source": "FAILED", "error": "HTTP 429 Rate limit exceeded; provider unavailable"}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Provider failures must record retryable errors and conclude CANNOT_VERIFY without crashing.",
    ))

    # -------------------------------------------------------------------------
    # 22. EVAL-22: Search Budget Exhaustion
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-22-SEARCH-BUDGET-EXHAUSTION",
        title="Search Budget Exhaustion",
        description="Investigation configured with tight call limit (max_search_calls=1); subsequent calls denied gracefully.",
        labels={
            "scenario_group": "system_and_limits",
            "category": "budget_exhaustion",
            "threat_category": "budget_limit",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=122,
            run_id="run_eval_22_budget",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd offer.\n"
                "Software Engineer position in Bengaluru.\n"
                "Contact: hr@radiantenergy.example"
            ),
            demo_mode=False,
        ),
        budget=BudgetSpec(
            max_search_calls=1,
            max_followup_calls=0,
            max_concurrent_calls=1,
            deadline_seconds=15.0,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Budget exhaustion triggers INVESTIGATION_BUDGET_EXCEEDED error and completes cleanly.",
    ))

    # -------------------------------------------------------------------------
    # 23. EVAL-23: Investigation Deadline Timeout
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-23-INVESTIGATION-DEADLINE-TIMEOUT",
        title="Investigation Monotonic Deadline Timeout",
        description="Investigation configured with expired/tight deadline; provider calls abort cleanly.",
        labels={
            "scenario_group": "system_and_limits",
            "category": "deadline_timeout",
            "threat_category": "deadline_exceeded",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=123,
            run_id="run_eval_23_deadline",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Offer of Employment. Contact: hr@radiantenergy.example"
            ),
            demo_mode=False,
        ),
        budget=BudgetSpec(
            max_search_calls=8,
            max_followup_calls=3,
            max_concurrent_calls=3,
            deadline_seconds=0.001,
        ),
        search_mock={
            "query_responses": {},
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="CANNOT_VERIFY",
        allowed_outcomes=["CANNOT_VERIFY"],
        required_behaviors=["authenticity_unconfirmed"],
        forbidden_behaviors=["fake_verification"],
        rationale="Investigation deadline expiry records INVESTIGATION_DEADLINE_EXCEEDED error without unhandled exception.",
    ))

    # -------------------------------------------------------------------------
    # 24. EVAL-24: Strong Warning Survives Vacancy Match
    # -------------------------------------------------------------------------
    cases.append(EvaluationCase(
        case_id="EVAL-24-STRONG-WARNING-SURVIVES-VACANCY-MATCH",
        title="Strong Warning Signal Survives Matching Vacancy",
        description="Matching public vacancy exists for legitimate employer, but letter demands mandatory deposit; outcome MUST remain HIGH_RISK.",
        labels={
            "scenario_group": "threat_cases",
            "category": "threat_precedence",
            "threat_category": "advance_fee_fraud",
            "primary_entity": "Radiant Energy Solutions Ltd",
        },
        case_input=CaseInputSpec(
            case_id=124,
            run_id="run_eval_24_override",
            source_type=SourceType.TEXT,
            redacted_text=(
                "Radiant Energy Solutions Ltd.\n"
                "Selected for Senior DevOps Engineer in Bengaluru.\n"
                "Vacancy reference: https://careers.radiantenergy.example/jobs/devops-blr.\n"
                "Deposit a refundable laptop security fee of INR 10,000 via UPI to radiant.training@okicici.\n"
                "Recruiter: hr@radiantenergy.example"
            ),
            demo_mode=False,
        ),
        search_mock={
            "query_responses": {
                '"Radiant Energy Solutions Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.radiantenergy.example", "careers_url": "https://careers.radiantenergy.example"},
                    "organic_results": [{"link": "https://www.radiantenergy.example", "title": "Radiant Energy", "snippet": "Energy solutions."}]
                },
                '"Radiant Energy Solutions Ltd" "Senior DevOps Engineer" careers job opening': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.radiantenergy.example/jobs/devops-blr", "title": "Senior DevOps Engineer", "snippet": "DevOps Engineer opening at Radiant Energy."}]
                }
            },
            "default_response": {"status": "successful", "source": "REAL", "organic_results": []}
        },
        expected_outcome="HIGH_RISK",
        allowed_outcomes=["HIGH_RISK"],
        required_behaviors=["authenticity_unconfirmed", "strong_warning_present"],
        forbidden_behaviors=["fake_verification"],
        rationale="Vacancy matching must NEVER override an explicit fee demand. Strong threat strictly takes precedence.",
    ))

    return cases


def save_evaluation_corpus(cases: List[EvaluationCase], target_dir: Optional[Path] = None) -> List[Path]:
    """Writes all evaluation cases to separate JSON files in target_dir."""
    dest = target_dir or CORPUS_DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for c in cases:
        file_path = dest / f"{c.case_id.lower().replace('-', '_')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(c.model_dump_json(indent=2))
        saved_paths.append(file_path)
    return saved_paths


def load_evaluation_corpus(source_dir: Optional[Path] = None) -> List[EvaluationCase]:
    """Loads all evaluation cases from source_dir, falling back to default cases if empty or missing."""
    src = source_dir or CORPUS_DATA_DIR
    cases = []
    if src.exists():
        for json_file in sorted(src.glob("eval_*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cases.append(EvaluationCase.model_validate(data))
            except Exception as e:
                pass

    if not cases:
        cases = get_default_corpus_cases()
        # Save them so files are persisted
        save_evaluation_corpus(cases, src)

    return cases
