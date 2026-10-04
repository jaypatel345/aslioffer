"""
Optional live evaluation runner for AsliOffer (Task 13).

Requires explicit --live flag.
Uses synthetic candidate inputs against real well-known public employers.
Reuses existing search configuration (SerpApiClient).
Respects shared search and deadline budgets.
Strips credentials from persisted outputs.
Stores results separately from offline evaluation in live_evaluation_results.json.
Not executed in automated tests.
"""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.contract import (
    CaseInput,
    InvestigationResult,
    SourceType,
    CONTRACT_VERSION,
)
from app.services.investigation.budget import InvestigationBudget
from app.services.investigation.pipeline import investigate_case
from app.services.search.serpapi_client import SerpApiClient
from app.evaluation.invariants import run_all_invariants
from app.evaluation.checks import redact_diagnostic

LIVE_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def get_live_test_cases() -> List[Dict[str, Any]]:
    """Safe synthetic candidate inputs targeting prominent public organizations."""
    return [
        {
            "case_id": "LIVE-01-TCS-SYSTEMS-ANALYST",
            "title": "Live Public Footprint: Tata Consultancy Services",
            "company_name": "Tata Consultancy Services Ltd",
            "input": CaseInput(
                contract_version=CONTRACT_VERSION,
                case_id=401,
                run_id="live_run_01_tcs",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Tata Consultancy Services Ltd.\n"
                    "We are pleased to offer you the position of Systems Analyst.\n"
                    "Location: Mumbai / Pune.\n"
                    "Please verify your offer on our official portal: https://www.tcs.com/careers.\n"
                    "Candidate: [redacted_candidate_name]."
                ),
                demo_mode=False,
            ),
            "expected_outcome": "CANNOT_VERIFY",  # Individual offer unauthenticated
            "allowed_outcomes": ["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        },
        {
            "case_id": "LIVE-02-INFOSYS-SYSTEMS-ENGINEER",
            "title": "Live Public Footprint: Infosys Limited",
            "company_name": "Infosys Limited",
            "input": CaseInput(
                contract_version=CONTRACT_VERSION,
                case_id=402,
                run_id="live_run_02_infosys",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Infosys Limited, Bangalore.\n"
                    "Employment Offer for Systems Engineer.\n"
                    "Careers site: https://www.infosys.com/careers.\n"
                    "Candidate: [redacted_candidate_name]."
                ),
                demo_mode=False,
            ),
            "expected_outcome": "CANNOT_VERIFY",
            "allowed_outcomes": ["CANNOT_VERIFY", "NO_STRONG_RISK_SIGNALS"],
        },
    ]


async def run_live_evaluation(
    output_dir: Optional[Path] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes live evaluation against SerpApi using live credentials.
    Returns machine-readable summary.
    """
    out_dir = output_dir or LIVE_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "live_evaluation_results.json"

    key = api_key or os.getenv("SERPAPI_API_KEY") or getattr(settings, "SERPAPI_API_KEY", "")
    if not key or key.strip() in ("", "mock_key", "your_serpapi_api_key_here"):
        report = {
            "mode": "live",
            "status": "SKIPPED",
            "reason": "SERPAPI_API_KEY not provided or invalid. Live evaluation requires a live SerpApi key.",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "results": [],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return report

    client = SerpApiClient(api_key=key, demo_mode=False)
    live_cases = get_live_test_cases()
    results = []

    budget = InvestigationBudget(
        max_search_calls=4,
        max_followup_calls=1,
        max_concurrent_calls=2,
        deadline_seconds=25.0,
    )

    for item in live_cases:
        cid = item["case_id"]
        case_input = item["input"]
        try:
            res = await investigate_case(case_input, search_client=client, budget=budget)
            res_dict = json.loads(res.model_dump_json())

            # Scrub any credentials from the output
            serialized = json.dumps(res_dict)
            if key in serialized:
                serialized = serialized.replace(key, "[REDACTED_API_KEY]")
                res_dict = json.loads(serialized)

            inv_results = run_all_invariants(res, demo_mode=False)
            inv_passed = all(i.passed for i in inv_results)

            results.append({
                "case_id": cid,
                "title": item["title"],
                "status": "COMPLETED",
                "overall_outcome": res.overall_outcome.value,
                "authenticity_status": res.authenticity_status.value,
                "invariants_passed": inv_passed,
                "outcome_matched": res.overall_outcome.value in item["allowed_outcomes"],
                "failed_invariants": [i.invariant_name for i in inv_results if not i.passed],
                "provider_calls": len(res.tool_trace),
                "errors_count": len(res.errors),
                "result": res_dict,
            })
        except Exception as e:
            results.append({
                "case_id": cid,
                "title": item["title"],
                "status": "FAILED",
                "error": redact_diagnostic(str(e).replace(key, "[REDACTED_API_KEY]")),
            })

    report = {
        "mode": "live",
        "status": "COMPLETED" if results and all(r.get("status") == "COMPLETED" and r.get("invariants_passed") and r.get("outcome_matched") for r in results) else "FAILED",
        "disclaimer": "Live evaluation reflects dynamic third-party search engine state. Results and latency vary across runs.",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(live_cases),
        "successful_cases": sum(1 for r in results if r["status"] == "COMPLETED"),
        "results": results,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report
