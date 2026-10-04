"""
Hackathon demo cases and reproducible output generator for AsliOffer (Task 13).

Defines 5 core hackathon demo scenarios demonstrating key platform capabilities:
1. Grounded scam warning: Advance fee demand flagged with grounded evidence.
2. Plausible impersonation: Real company branding overridden by fraudulent fee demand.
3. Legitimate recruitment guidance: Sourced confirmation route with UNCONFIRMED authenticity.
4. Sparse footprint startup: Honest uncertainty without false accusations.
5. Search provider outage: Graceful failure preserving partial evidence and retryable error.

Executes real pipeline runs to produce contract-compatible v1 JSON outputs for Jay's frontend.
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.contract import (
    CaseInput,
    ConfirmedClaim,
    ClaimKind,
    ExtractionStatus,
    InvestigationResult,
    OverallOutcome,
    SourceType,
)
from app.services.investigation.pipeline import investigate_case

DEMO_OUTPUTS_DIR = Path(__file__).resolve().parent / "demo_outputs"
DOCS_DEMO_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "demo"


class DemoCaseDefinition(BaseModel):
    demo_id: str
    filename: str
    title: str
    scenario_summary: str
    input_text: str
    search_setup_description: str
    expected_outcome: str
    highlight_evidence: str
    what_it_establishes: str
    what_it_does_not_establish: str
    reproduction_steps: List[str]
    case_input: CaseInput
    search_responses: Dict[str, Any]
    default_response: Dict[str, Any]


class MockDemoSearchClient:
    """Deterministic search client for demo execution."""

    def __init__(self, query_responses: Dict[str, Any], default_response: Optional[Dict[str, Any]] = None):
        self.query_responses = query_responses or {}
        self.default_response = default_response or {"status": "successful", "source": "REAL", "organic_results": []}

    async def search(self, query: str, engine: str = "google", num: int = 5, **kwargs) -> Dict[str, Any]:
        if query in self.query_responses:
            return deepcopy(self.query_responses[query])
        for q, resp in self.query_responses.items():
            if q.strip() == query.strip():
                return deepcopy(resp)
        return deepcopy(self.default_response)


def get_demo_case_definitions() -> List[DemoCaseDefinition]:
    """Returns the 5 canonical hackathon demonstration cases."""
    return [
        # Demo 1: Grounded Scam Warning
        DemoCaseDefinition(
            demo_id="DEMO-01",
            filename="demo_01_grounded_scam_warning.json",
            title="Grounded Advance Fee Scam Warning",
            scenario_summary="Candidate offered Graduate Engineer Trainee but told to pay INR 15,000 refundable laptop deposit via UPI.",
            input_text=(
                "Nimbus Infotech Ltd. Congratulations! You have been selected for Graduate Engineer Trainee.\n"
                "Deposit a refundable laptop security fee of INR 15,000 via UPI to nimbus.onboarding@okaxis within 24 hours.\n"
                "Contact: priya.nimbus@gmail.com"
            ),
            search_setup_description="Real company website found; search for fraud notices retrieves employer advisory stating Nimbus never charges security deposits.",
            expected_outcome="HIGH_RISK",
            highlight_evidence="ScamAgent flags active UPI payment request; official fraud alert cites employer policy forbidding deposits.",
            what_it_establishes="Direct advance-fee extortion pattern corroborated by conflicting official employer hiring policy.",
            what_it_does_not_establish="Does not imply the real Nimbus Infotech Ltd is fraudulent; establishes that this specific letter is a scam.",
            reproduction_steps=[
                "Run `python -m backend.app.evaluation.runner --demo 1`",
                "Inspect overall_outcome=HIGH_RISK and payment_request claim CONTRADICTED.",
            ],
            case_input=CaseInput(
                case_id=301,
                run_id="demo_run_01_scam",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Nimbus Infotech Ltd. Congratulations! You have been selected for Graduate Engineer Trainee.\n"
                    "Deposit a refundable laptop security fee of INR 15,000 via UPI to nimbus.onboarding@okaxis within 24 hours.\n"
                    "Contact: priya.nimbus@gmail.com"
                ),
                demo_mode=False,
            ),
            search_responses={
                '"Nimbus Infotech Ltd" official website careers': {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://www.nimbusinfotech.example/", "title": "Nimbus Infotech Ltd", "snippet": "IT services provider."}],
                },
                "Nimbus Infotech Ltd recruitment fraud email domain fee": {
                    "status": "successful", "source": "REAL",
                    "organic_results": [{"link": "https://careers.nimbusinfotech.example/fraud-alert", "title": "Fraud Alert", "snippet": "Nimbus never asks candidates for money or security deposits."}],
                }
            },
            default_response={"status": "successful", "source": "REAL", "organic_results": []},
        ),

        # Demo 2: Plausible Impersonation
        DemoCaseDefinition(
            demo_id="DEMO-02",
            filename="demo_02_plausible_impersonation.json",
            title="Plausible Employer Impersonation with Fee Demand",
            scenario_summary="Offer copies real corporate branding and address of Infosys Limited, but recruiter uses personal email and demands INR 6,500 document fee.",
            input_text=(
                "Infosys Limited, Electronics City, Hosur Road, Bangalore.\n"
                "Appointment for Systems Engineer. Compensation: INR 4,80,000 per annum.\n"
                "Pay an onboarding document verification fee of INR 6,500 to infosys-hr@upi within 48 hours.\n"
                "Contact: recruitment@infosys-careers.example"
            ),
            search_setup_description="Company website and careers portal resolved, but recruiter email domain is unverified lookalike and document contains upfront fee demand.",
            expected_outcome="HIGH_RISK",
            highlight_evidence="Advance fee demand strictly overrides corporate name recognition and realistic salary figures.",
            what_it_establishes="Impersonators often copy authentic addresses and salary ranges; fee demand reveals the scam.",
            what_it_does_not_establish="Does not authenticate the communication even though corporate address and company exist.",
            reproduction_steps=[
                "Run `python -m backend.app.evaluation.runner --demo 2`",
                "Verify that high-profile corporate branding does NOT dilute the HIGH_RISK outcome.",
            ],
            case_input=CaseInput(
                case_id=302,
                run_id="demo_run_02_impersonation",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Infosys Limited, Electronics City, Hosur Road, Bangalore.\n"
                    "Appointment for Systems Engineer. Compensation: INR 4,80,000 per annum.\n"
                    "Pay an onboarding document verification fee of INR 6,500 to infosys-hr@upi within 48 hours.\n"
                    "Contact: recruitment@infosys-careers.example"
                ),
                demo_mode=False,
            ),
            search_responses={
                '"Infosys Limited" official website careers': {
                    "status": "successful", "source": "REAL",
                    "knowledge_graph": {"website": "https://www.infosys.example", "careers_url": "https://careers.infosys.example"},
                    "organic_results": [{"link": "https://www.infosys.example", "title": "Infosys - Official Website", "snippet": "Global consulting and IT services."}],
                }
            },
            default_response={"status": "successful", "source": "REAL", "organic_results": []},
        ),

        # Demo 3: Legitimate Recruitment with Confirmation Guidance
        DemoCaseDefinition(
            demo_id="DEMO-03",
            filename="demo_03_legit_confirmation_guidance.json",
            title="Legitimate Recruitment with Sourced Confirmation Guidance",
            scenario_summary="Offer from Kestrel Systems Pvt Ltd with verified recruiter email, active vacancy, and independently sourced confirmation route.",
            input_text=(
                "Offer of Employment from Kestrel Systems Pvt Ltd.\n"
                "We are pleased to offer you the position of Associate Consultant.\n"
                "Please review the offer details at https://careers.kestrelsystems.example/offers.\n"
                "Regards, Ananya Rao, Talent Acquisition. Contact: ananya.rao@kestrelsystems.example"
            ),
            search_setup_description="Official domain resolved, recruiter verified on team page, careers portal resolved, clean fraud history.",
            expected_outcome="NO_STRONG_RISK_SIGNALS",
            highlight_evidence="ConfirmationRoute provides independently published HR verification channel with draft message; authenticity_status stays UNCONFIRMED.",
            what_it_establishes="Public records corroborate employer identity and recruiter affiliation with no risk signals.",
            what_it_does_not_establish="Cannot authenticate that this specific offer letter was issued without the candidate contacting the employer directly.",
            reproduction_steps=[
                "Run `python -m backend.app.evaluation.runner --demo 3`",
                "Verify confirmation_route is populated and authenticity_status is UNCONFIRMED.",
            ],
            case_input=CaseInput(
                case_id=303,
                run_id="demo_run_03_legit",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Offer of Employment from Kestrel Systems Pvt Ltd.\n"
                    "We are pleased to offer you the position of Associate Consultant.\n"
                    "Please review the offer details at https://careers.kestrelsystems.example/offers.\n"
                    "Regards, Ananya Rao, Talent Acquisition. Contact: ananya.rao@kestrelsystems.example"
                ),
                demo_mode=False,
            ),
            search_responses={
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
            default_response={"status": "successful", "source": "REAL", "organic_results": []},
        ),

        # Demo 4: Sparse Footprint Startup
        DemoCaseDefinition(
            demo_id="DEMO-04",
            filename="demo_04_sparse_footprint_unverified.json",
            title="Sparse Footprint Startup (Honest Uncertainty)",
            scenario_summary="Early-stage startup with no public website or search hits, but zero fraud complaints.",
            input_text=(
                "Acme Pixel Labs offer for Junior 3D Artist.\n"
                "Monthly stipend: INR 25,000. Start date: November 1.\n"
                "Contact: dev@acmepixellabs.example"
            ),
            search_setup_description="Search executes successfully but returns zero corporate records or reviews.",
            expected_outcome="CANNOT_VERIFY",
            highlight_evidence="Coverage summary clearly marks corporate identity as unresolved; recommended actions guide safe verification without accusing the employer.",
            what_it_establishes="Public evidence is insufficient to verify or refute this offer.",
            what_it_does_not_establish="Does NOT classify the offer as fraud or scam; honest uncertainty is preserved.",
            reproduction_steps=[
                "Run `python -m backend.app.evaluation.runner --demo 4`",
                "Verify outcome=CANNOT_VERIFY and absence of false fraud accusations.",
            ],
            case_input=CaseInput(
                case_id=304,
                run_id="demo_run_04_sparse",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Acme Pixel Labs offer for Junior 3D Artist.\n"
                    "Monthly stipend: INR 25,000. Start date: November 1.\n"
                    "Contact: dev@acmepixellabs.example"
                ),
                demo_mode=False,
            ),
            search_responses={},
            default_response={"status": "successful", "source": "REAL", "organic_results": []},
        ),

        # Demo 5: Provider Outage Failsafe
        DemoCaseDefinition(
            demo_id="DEMO-05",
            filename="demo_05_provider_outage_failsafe.json",
            title="Provider Outage Resilience (Graceful Degradation)",
            scenario_summary="Upstream search provider returns HTTP 429 rate limit or timeout during investigation.",
            input_text=(
                "Vertex Dynamics Ltd.\n"
                "Offer for Senior Database Administrator.\n"
                "Contact: hr@vertexdynamics.example"
            ),
            search_setup_description="Underlying search client returns rate limit failure on external queries.",
            expected_outcome="CANNOT_VERIFY",
            highlight_evidence="RunError recorded with code SEARCH_CHECK_UNAVAILABLE and retryable=True; local pattern scan results preserved.",
            what_it_establishes="Pipeline handles infrastructure outages gracefully without crashing or fabricating mock data.",
            what_it_does_not_establish="Does not render a substantive verdict on the offer due to incomplete external checks.",
            reproduction_steps=[
                "Run `python -m backend.app.evaluation.runner --demo 5`",
                "Verify error recorded in results.errors and outcome=CANNOT_VERIFY.",
            ],
            case_input=CaseInput(
                case_id=305,
                run_id="demo_run_05_outage",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Vertex Dynamics Ltd.\n"
                    "Offer for Senior Database Administrator.\n"
                    "Contact: hr@vertexdynamics.example"
                ),
                demo_mode=False,
            ),
            search_responses={},
            default_response={"status": "failed", "source": "FAILED", "error": "HTTP 429 Rate limit exceeded; provider unavailable"},
        ),
    ]


async def generate_demo_outputs(
    target_dirs: Optional[List[Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Executes the 5 demo cases through the real investigate_case pipeline
    and saves contract-v1 JSON outputs to target_dirs.
    """
    dirs = target_dirs or [DEMO_OUTPUTS_DIR, DOCS_DEMO_DIR]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    demo_defs = get_demo_case_definitions()
    results_map: Dict[str, Dict[str, Any]] = {}

    for demo in demo_defs:
        mock_client = MockDemoSearchClient(
            query_responses=demo.search_responses,
            default_response=demo.default_response,
        )
        result = await investigate_case(demo.case_input, search_client=mock_client)
        assert isinstance(result, InvestigationResult)

        result_dict = json.loads(result.model_dump_json(indent=2))
        results_map[demo.demo_id] = {
            "metadata": {
                "demo_id": demo.demo_id,
                "title": demo.title,
                "filename": demo.filename,
                "expected_outcome": demo.expected_outcome,
                "actual_outcome": result.overall_outcome.value,
                "authenticity_status": result.authenticity_status.value,
                "highlight_evidence": demo.highlight_evidence,
                "what_it_establishes": demo.what_it_establishes,
                "what_it_does_not_establish": demo.what_it_does_not_establish,
                "reproduction_steps": demo.reproduction_steps,
            },
            "result": result_dict,
        }

        # Write to each target directory
        for d in dirs:
            out_file = d / demo.filename
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2)

    # Also save an index file in demo outputs
    for d in dirs:
        manifest_file = d / "demo_manifest.json"
        manifest = [
            {
                "demo_id": d_def.demo_id,
                "filename": d_def.filename,
                "title": d_def.title,
                "expected_outcome": d_def.expected_outcome,
                "actual_outcome": results_map[d_def.demo_id]["metadata"]["actual_outcome"],
                "highlight": d_def.highlight_evidence,
            }
            for d_def in demo_defs
        ]
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    return results_map
