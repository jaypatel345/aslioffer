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


def get_demo_case_definitions() -> List[DemoCaseDefinition]:
    """Demos reuse the executable corpus; there is no second mock-response set."""
    from app.evaluation.corpus import load_evaluation_corpus
    cases = {c.case_id[:7]: c for c in load_evaluation_corpus()}
    descriptions = [
        (1, 1, 'grounded_scam_warning', 'A grounded payment demand produces a strong risk warning.'),
        (2, 5, 'plausible_impersonation', 'A fee demand remains high risk despite plausible corporate branding.'),
        (3, 6, 'legit_confirmation_guidance', 'Public employer/recruiter observations provide an independently sourced confirmation route.'),
        (4, 8, 'sparse_footprint_unverified', 'Sparse public evidence remains inconclusive without a fraud accusation.'),
        (5, 21, 'provider_outage_failsafe', 'Provider failure yields structured retryable errors and an inconclusive outcome.'),
    ]
    demos = []
    for demo_num, case_num, suffix, establishes in descriptions:
        case = cases[f'EVAL-{case_num:02d}']
        demos.append(DemoCaseDefinition(
            demo_id=f'DEMO-{demo_num:02d}', filename=f'demo_{demo_num:02d}_{suffix}.json',
            title=case.title, scenario_summary=case.description,
            input_text=case.case_input.redacted_text,
            search_setup_description='Offline synthetic replay of ' + case.case_id,
            expected_outcome=case.expected_outcome,
            highlight_evidence='Inspect assessed claims and their cited evidence; authenticity remains UNCONFIRMED.',
            what_it_establishes=establishes,
            what_it_does_not_establish='This synthetic scenario does not establish real-world accuracy or authenticate an individual offer.',
            reproduction_steps=[f'python -m backend.app.evaluation.runner --case EVAL-{case_num:02d} --output-dir evaluation_artifacts',
                'python -m backend.app.evaluation.runner --generate-demos --output-dir evaluation_artifacts'],
            case_input=case.case_input.to_case_input(),
            search_responses=case.search_mock.get('query_responses', {}),
            default_response=case.search_mock.get('default_response', {}),
        ))
    return demos


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
        from app.evaluation.runner import EvaluationMockSearchClient
        from app.evaluation.invariants import run_all_invariants
        from app.evaluation.corpus import load_evaluation_corpus
        from app.evaluation.checks import check_case_behaviors, check_case_expectations
        mock_client = EvaluationMockSearchClient(
            query_responses=demo.search_responses,
            default_response=demo.default_response,
        )
        result = await investigate_case(demo.case_input, search_client=mock_client)
        case = next(c for c in load_evaluation_corpus() if c.case_input.run_id == demo.case_input.run_id)
        failures = check_case_behaviors(case, result) + check_case_expectations(case, result)
        assessed = {c.kind.value: next((a.status.value for a in result.assessed_claims if a.claim_id == c.claim_id), None) for c in result.claims}
        failures += [f'Claim expectation failed: {kind}' for kind, status in case.expected_claim_statuses.items() if assessed.get(kind) != status]
        failures += [i.invariant_name for i in run_all_invariants(result, case.labels, case.planted_secrets,
            retrieved_observations=mock_client.retrieved_observations) if not i.passed]
        if result.overall_outcome.value != demo.expected_outcome or failures:
            raise ValueError(f'Demo {demo.demo_id} failed acceptance: ' + ', '.join(failures))

        result_dict = json.loads(result.model_dump_json(indent=2))
        results_map[demo.demo_id] = {
            "metadata": {
                "demo_id": demo.demo_id,
                "mode": "offline_synthetic_replay",
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
                "mode": "offline_synthetic_replay",
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
