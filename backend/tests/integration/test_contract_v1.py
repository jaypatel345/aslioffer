"""Contract v1: every canonical example parses, and the rules the contract
promises are enforced by the models rather than only by documentation."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.contract import (
    CONTRACT_VERSION,
    CaseInput,
    ErrorResponse,
    InvestigationResult,
    RunEvent,
    RunSnapshot,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "contract" / "v1" / "examples"
MODELS = {
    "investigation_result": InvestigationResult,
    "run_snapshot": RunSnapshot,
    "run_event": RunEvent,
    "case_input": CaseInput,
    "error": ErrorResponse,
}


def _model_for(name: str):
    return next(model for prefix, model in MODELS.items() if name.startswith(prefix))


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


EXAMPLE_FILES = sorted(p.name for p in EXAMPLES.glob("*.json"))


def test_examples_present():
    # One supported, one contradictory, one sparse and one outage result, per the plan.
    results = [n for n in EXAMPLE_FILES if n.startswith("investigation_result")]
    assert len(results) >= 4
    assert {"run_snapshot_completed.json", "run_snapshot_failed.json", "case_input.json"} <= set(EXAMPLE_FILES)


@pytest.mark.parametrize("name", EXAMPLE_FILES)
def test_example_parses_and_round_trips(name):
    raw = _load(name)
    model = _model_for(name)
    parsed = model.model_validate(raw)
    again = model.model_validate_json(parsed.model_dump_json())
    assert again == parsed
    if "contract_version" in raw:
        assert raw["contract_version"] == CONTRACT_VERSION


@pytest.mark.parametrize("name", [n for n in EXAMPLE_FILES if n.startswith("investigation_result")])
def test_results_never_claim_authenticity(name):
    assert _load(name)["authenticity_status"] == "UNCONFIRMED"


def _result():
    return copy.deepcopy(_load("investigation_result_high_risk_impersonation.json"))


def _rejects(model, data, fragment):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    assert fragment in str(exc.value)


def test_rejects_unknown_fields_like_fraud_probability():
    data = _result()
    data["fraud_probability"] = 0.94
    _rejects(InvestigationResult, data, "fraud_probability")


def test_rejects_citation_of_missing_evidence():
    data = _result()
    data["assessed_claims"][0]["evidence_ids"].append("e999")
    _rejects(InvestigationResult, data, "unknown evidence e999")


def test_rejects_evidence_cited_for_the_wrong_claim():
    data = _result()
    data["assessed_claims"][0]["evidence_ids"] = ["e2"]  # e2 belongs to c2
    _rejects(InvestigationResult, data, "belongs to c2")


def test_rejects_supported_claim_without_supporting_evidence():
    data = _result()
    data["assessed_claims"][3]["status"] = "SUPPORTED"  # role claim has no evidence
    _rejects(InvestigationResult, data, "needs supporting evidence")


def test_failed_search_cannot_be_evidence():
    data = copy.deepcopy(_load("investigation_result_cannot_verify_provider_outage.json"))
    data["evidence"][0]["relation"] = "CONTRADICTS"
    _rejects(InvestigationResult, data, "FAILED retrieval cannot support or contradict")


def test_demo_evidence_only_in_demo_mode():
    data = _result()
    data["evidence"][0]["retrieval_status"] = "DEMO"
    _rejects(InvestigationResult, data, "DEMO evidence is only allowed")
    data["demo_mode"] = True
    InvestigationResult.model_validate(data)


def test_document_observation_needs_no_url_but_search_evidence_does():
    data = _result()
    data["evidence"][0]["source_url"] = None
    _rejects(InvestigationResult, data, "needs a source_url")


def test_provider_keys_never_in_urls():
    data = _result()
    data["evidence"][0]["source_url"] = "https://serpapi.com/search?q=x&api_key=secret"
    _rejects(InvestigationResult, data, "provider keys")


def test_only_unconfirmed_authenticity_exists():
    data = _result()
    data["authenticity_status"] = "CONFIRMED"
    _rejects(InvestigationResult, data, "authenticity_status")


def test_coverage_must_match_claims():
    data = _result()
    data["coverage"]["total_claims"] = 9
    _rejects(InvestigationResult, data, "total_claims")


def test_completed_snapshot_requires_report():
    data = copy.deepcopy(_load("run_snapshot_completed.json"))
    data["report"] = None
    _rejects(RunSnapshot, data, "must carry its report")


def test_running_snapshot_cannot_carry_report():
    data = copy.deepcopy(_load("run_snapshot_running.json"))
    data["report"] = _result()
    _rejects(RunSnapshot, data, "unfinished run has no report")


def test_failed_snapshot_must_explain():
    data = copy.deepcopy(_load("run_snapshot_failed.json"))
    data["errors"] = []
    _rejects(RunSnapshot, data, "must say why")


def test_events_must_be_ordered():
    data = copy.deepcopy(_load("run_snapshot_running.json"))
    data["events"].reverse()
    _rejects(RunSnapshot, data, "increasing sequence")


def test_event_message_cannot_leak_keys():
    data = _load("run_event.json")
    data["public_message"] = "Calling SerpApi with api_key=abc"
    _rejects(RunEvent, data, "provider keys")


def test_case_input_confirmed_claims_are_user_decisions():
    data = copy.deepcopy(_load("case_input.json"))
    data["confirmed_claims"][0]["extraction_status"] = "EXTRACTED"
    _rejects(CaseInput, data, "USER_CONFIRMED or USER_EDITED")
