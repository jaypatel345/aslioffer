"""
Offline and live evaluation runner for AsliOffer (Task 13).

Provides a unified command-line entry point to execute the evaluation corpus:
- Offline and deterministic by default.
- Zero network calls and zero API keys required.
- Executes real investigate_case() entry point.
- Does not modify tracked fixtures during ordinary execution.
- Generates machine-readable JSON results and readable Markdown summary.
- Enforces strict safety and evidence invariants.
- Returns nonzero exit code upon acceptance check failure.
"""

import argparse
import hashlib
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure backend and repo root are in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
for _p in [str(_BACKEND_DIR), str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.schemas.contract import (
    ClaimKind,
    InvestigationResult,
    OverallOutcome,
)
from app.services.investigation.pipeline import investigate_case
from app.services.agents.recruiter_agent import RecruiterAgent
from app.evaluation.corpus import EvaluationCase, load_evaluation_corpus
from app.evaluation.invariants import run_all_invariants, InvariantResult
from app.evaluation.metrics import compute_evaluation_metrics, EvaluationMetricsReport
from app.evaluation.demo_cases import generate_demo_outputs
from app.evaluation.live import run_live_evaluation
from app.evaluation.checks import check_case_behaviors, check_case_expectations, redact_diagnostic
from unittest.mock import patch

DEFAULT_OUTPUT_DIR = _REPO_ROOT / "evaluation_artifacts"


class EvaluationMockSearchClient:
    """Isolated, deterministic search client replaying responses per evaluation case."""

    def __init__(self, query_responses: Dict[str, Any], default_response: Optional[Dict[str, Any]] = None):
        self.query_responses = query_responses or {}
        self.default_response = default_response or {"status": "successful", "source": "REAL", "organic_results": []}
        self.recorded_queries: List[str] = []
        self.retrieved_observations = []
        self.delay_seconds = 0.0

    async def search(self, query: str, engine: str = "google", num: int = 5, **kwargs) -> Dict[str, Any]:
        self.recorded_queries.append(query)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if query in self.query_responses:
            return self._replay(self.query_responses[query], query, engine)

        query_clean = query.strip()
        for q_key, resp in self.query_responses.items():
            if q_key.strip() == query_clean:
                return self._replay(resp, query, engine)

        return self._replay(self.default_response, query, engine)

    def _replay(self, response, query, engine):
        res = deepcopy(response)
        if isinstance(res, dict) and res.get("status") == "successful" and res.get("source") not in ("DEMO", "MOCK", "FAILED"):
            for item in res.get("organic_results", []):
                if item.get("link"):
                    self.retrieved_observations.append(dict(item, query=query, engine=engine))
            kg = res.get("knowledge_graph") or {}
            for field in ("website", "careers_url"):
                if kg.get(field):
                    self.retrieved_observations.append(dict(link=kg[field], title=kg.get("title", ""),
                        snippet=json.dumps(kg, ensure_ascii=False), query=query, engine=engine))
        return res


def get_git_commit_sha() -> str:
    """Retrieves current git commit SHA or returns unknown."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown_or_dirty"


def working_tree_dirty():
    try:
        return bool(subprocess.run(['git', 'status', '--porcelain'], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=5, check=True).stdout.strip())
    except Exception:
        return None


def evaluation_code_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def case_passes(result):
    return (not result.get("exception_occurred") and result.get("outcome_matched", False)
            and result.get("invariants_passed", False)
            and result.get("claim_matches", 0) == result.get("claim_total", 0)
            and not result.get("behavior_failures") and not result.get("expectation_failures"))


async def evaluate_single_case(case: EvaluationCase) -> Dict[str, Any]:
    """Runs one evaluation case through the real investigate_case pipeline and checks invariants."""
    mock_client = EvaluationMockSearchClient(
        query_responses=case.search_mock.get("query_responses", {}),
        default_response=case.search_mock.get("default_response"),
    )
    mock_client.delay_seconds = case.search_mock.get("delay_seconds", 0.0)

    agent_dimensions = {}
    original_recruiter = RecruiterAgent.investigate
    async def record_recruiter(agent, *args, **kwargs):
        finding = await original_recruiter(agent, *args, **kwargs)
        for name, dimension in (finding.details.get('assessment_dimensions') or {}).items():
            if isinstance(dimension, dict) and dimension.get('status'):
                agent_dimensions[name] = dimension['status']
        return finding

    t0 = time.perf_counter()
    try:
        case_in = case.case_input.to_case_input()
        budget = case.budget.to_investigation_budget() if case.budget else None
        with patch("socket.socket.connect", side_effect=RuntimeError("Offline evaluation forbids network access")), \
             patch("socket.getaddrinfo", side_effect=RuntimeError("Offline evaluation forbids DNS access")), \
             patch.object(RecruiterAgent, "investigate", record_recruiter):
            result = await investigate_case(case_in, search_client=mock_client, budget=budget)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert isinstance(result, InvestigationResult)

        # 1. Outcome check
        allowed = case.get_allowed_outcomes()
        outcome_matched = result.overall_outcome.value in allowed

        # 2. Claim status checks
        assessed_map = {a.claim_id: a for a in result.assessed_claims}
        claim_kind_map = {c.claim_id: c.kind.value for c in result.claims}

        claim_matches = 0
        claim_total = len(case.expected_claim_statuses)
        claim_details = []

        for expected_kind, expected_status in case.expected_claim_statuses.items():
            # Find matching claim
            matching_claim_id = next((cid for cid, k in claim_kind_map.items() if k == expected_kind), None)
            if matching_claim_id and matching_claim_id in assessed_map:
                actual_status = assessed_map[matching_claim_id].status.value
                matched = (actual_status == expected_status)
                if matched:
                    claim_matches += 1
                claim_details.append({
                    "kind": expected_kind,
                    "expected": expected_status,
                    "actual": actual_status,
                    "matched": matched,
                })
            else:
                claim_details.append({
                    "kind": expected_kind,
                    "expected": expected_status,
                    "actual": "NOT_ASSESSED",
                    "matched": False,
                })

        # 3. Invariants checks
        invariants = run_all_invariants(
            result,
            case_labels=case.labels,
            planted_secrets=case.planted_secrets,
            demo_mode=case.case_input.demo_mode,
            retrieved_observations=mock_client.retrieved_observations,
        )
        inv_passed = all(i.passed for i in invariants)
        failed_inv_msgs = [redact_diagnostic(f"{i.invariant_name}: {'; '.join(i.violations)}", case.planted_secrets) for i in invariants if not i.passed]

        behavior_failures = [redact_diagnostic(f, case.planted_secrets) for f in check_case_behaviors(case, result)]
        expectation_failures = [redact_diagnostic(f, case.planted_secrets) for f in check_case_expectations(case, result, agent_dimensions)]
        case_passed = outcome_matched and inv_passed and claim_matches == claim_total and not behavior_failures and not expectation_failures

        # 4. Coverage and provider calls
        total_claims = len(result.claims)
        checked_claims = result.coverage.checked_claims
        coverage_ratio = checked_claims / max(1, total_claims)
        provider_calls = len(result.tool_trace)

        return {
            "case_id": case.case_id,
            "title": case.title,
            "scenario_group": case.labels.get("scenario_group", "default"),
            "category": case.labels.get("category", "default"),
            "exception_occurred": False,
            "case_passed": case_passed,
            "agent_dimensions": agent_dimensions,
            "behavior_failures": behavior_failures,
            "expectation_failures": expectation_failures,
            "outcome_matched": outcome_matched,
            "actual_outcome": result.overall_outcome.value,
            "expected_outcome": case.expected_outcome,
            "allowed_outcomes": allowed,
            "authenticity_status": result.authenticity_status.value,
            "claim_matches": claim_matches,
            "claim_total": claim_total,
            "claim_details": claim_details,
            "invariants_passed": inv_passed,
            "failed_invariants": failed_inv_msgs,
            "coverage_ratio": coverage_ratio,
            "total_claims": total_claims,
            "checked_claims": checked_claims,
            "unresolved_claims": result.coverage.unresolved_claims,
            "failed_checks_count": result.coverage.failed_checks,
            "provider_calls_count": provider_calls,
            "latency_ms": elapsed_ms,
            "errors_count": len(result.errors),
            "confirmation_route_present": result.confirmation_route is not None,
        }

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "case_id": case.case_id,
            "title": case.title,
            "scenario_group": case.labels.get("scenario_group", "default"),
            "category": case.labels.get("category", "default"),
            "exception_occurred": True,
            "case_passed": False,
            "behavior_failures": [],
            "expectation_failures": [],
            "exception_type": type(exc).__name__,
            "error_message": redact_diagnostic(str(exc), case.planted_secrets),
            "outcome_matched": False,
            "actual_outcome": "EXCEPTION",
            "expected_outcome": case.expected_outcome,
            "allowed_outcomes": case.get_allowed_outcomes(),
            "claim_matches": 0,
            "claim_total": len(case.expected_claim_statuses),
            "invariants_passed": False,
            "failed_invariants": [f"Exception occurred: {type(exc).__name__}: {redact_diagnostic(str(exc), case.planted_secrets)}"],
            "coverage_ratio": 0.0,
            "failed_checks_count": 0,
            "provider_calls_count": 0,
            "latency_ms": elapsed_ms,
        }


def format_markdown_summary(
    report: EvaluationMetricsReport,
    metadata: Dict[str, Any],
    case_results: List[Dict[str, Any]],
) -> str:
    """Renders a readable GitHub-flavored Markdown report."""
    md = []
    md.append(f"# AsliOffer Evaluation Report (Task 13)")
    md.append(f"")
    md.append(f"**Date:** `{metadata['executed_at']}` | **Commit:** `{metadata['commit_sha'][:8]}` | **Mode:** `{metadata['mode']}` | **Cases:** `{report.total_cases}`")
    md.append(f"")

    # Executive Summary Box
    all_passed = bool(case_results) and all(case_passes(r) for r in case_results)
    status_emoji = "PASS" if all_passed else "FAIL"
    md.append(f"## Status: {status_emoji}")
    md.append(f"")
    md.append(f"- **Outcome Agreement:** {report.outcome_agreement.formatted}")
    md.append(f"- **False Positive Rate:** {report.false_positive_rate.formatted}")
    md.append(f"- **False Negative Rate:** {report.false_negative_rate.formatted}")
    md.append(f"- **Uncertainty Retention:** {report.uncertainty_retention_rate.formatted}")
    md.append(f"- **Safety Invariant Pass Rate:** {report.invariant_pass_rate.formatted}")
    md.append(f"- **Pipeline Latency (mock):** Median: `{report.median_latency_ms:.1f}ms` | p95: `{report.p95_latency_ms:.1f}ms`")
    md.append(f"")

    # Metrics Table
    md.append(f"## Honest Metrics & Explicit Denominators")
    md.append(f"")
    md.append(f"| Metric | Formula / Denominator | Measured Value | Standard / Requirement |")
    md.append(f"|---|---|---|---|")
    md.append(f"| **Outcome Agreement** | `agreed_outcomes / total_cases` ({report.outcome_agreement.numerator}/{report.outcome_agreement.denominator}) | `{report.outcome_agreement.formatted}` | High agreement on specified cases |")
    md.append(f"| **False Positive Rate** | `legit_marked_high_risk / legit_cases` ({report.false_positive_rate.numerator}/{report.false_positive_rate.denominator}) | `{report.false_positive_rate.formatted}` | **0.0%** (zero legitimate offers marked HIGH_RISK) |")
    md.append(f"| **False Negative Rate** | `threats_missing_warning / threat_cases` ({report.false_negative_rate.numerator}/{report.false_negative_rate.denominator}) | `{report.false_negative_rate.formatted}` | **0.0%** (all fee/OTP threats flagged) |")
    md.append(f"| **Uncertainty Retention** | `actual_cannot_verify / expected_cannot_verify` ({report.uncertainty_retention_rate.numerator}/{report.uncertainty_retention_rate.denominator}) | `{report.uncertainty_retention_rate.formatted}` | Honest restraint on sparse/missing records |")
    md.append(f"| **Claim Status Agreement** | `matching_claims / expected_claims` ({report.claim_status_agreement.numerator}/{report.claim_status_agreement.denominator}) | `{report.claim_status_agreement.formatted}` | Fine-grained extraction & corroboration alignment |")
    md.append(f"| **Invariant Pass Rate** | `cases_with_all_invariants / total_cases` ({report.invariant_pass_rate.numerator}/{report.invariant_pass_rate.denominator}) | `{report.invariant_pass_rate.formatted}` | **100.0%** (strictly zero invariant violations) |")
    md.append(f"| **Coverage Completeness** | Mean `checked_claims / total_claims` | `{report.avg_coverage_ratio * 100:.1f}%` (min: `{report.min_coverage_ratio*100:.0f}%`, max: `{report.max_coverage_ratio*100:.0f}%`) | Completeness measurement |")
    md.append(f"| **Tool Provider Calls** | Actual external queries from tool trace | Mean: `{report.avg_provider_calls_per_case:.1f}`, median: `{report.median_provider_calls_per_case:.0f}`, p95: `{report.p95_provider_calls_per_case:.0f}` | Each recorded provider invocation; cached lookups excluded |")
    md.append(f"")

    # Scenario Group Breakdown
    md.append(f"## Scenario Group Breakdown")
    md.append(f"")
    md.append(f"| Scenario Group | Cases | Passed | Agreement | Invariants | Avg Calls | Avg Latency |")
    md.append(f"|---|---|---|---|---|---|---|")
    for g_name, g_met in report.group_breakdowns.items():
        md.append(f"| `{g_name}` | {g_met.case_count} | {g_met.passed_cases} | {g_met.outcome_agreement_rate*100:.1f}% | {g_met.invariant_pass_rate*100:.1f}% | {g_met.avg_provider_calls:.1f} | {g_met.avg_latency_ms:.1f}ms |")
    md.append(f"")

    # Per-Case Results
    md.append(f"## Per-Case Evaluation Results")
    md.append(f"")
    md.append(f"| Case ID | Group | Expected | Actual | Invariants | Calls | Coverage | Result |")
    md.append(f"|---|---|---|---|---|---|---|---|")
    for r in case_results:
        passed = case_passes(r)
        sym = "PASS" if passed else "FAIL"
        calls = r.get("provider_calls_count", 0)
        cov = f"{r.get('coverage_ratio', 0.0)*100:.0f}%"
        md.append(f"| `{r['case_id']}` | `{r['scenario_group']}` | `{r['expected_outcome']}` | `{r['actual_outcome']}` | {'YES' if r['invariants_passed'] else 'NO'} | {calls} | {cov} | **{sym}** |")

    # Failures / Actionable diagnostics
    failed_cases = [r for r in case_results if not (case_passes(r))]
    if failed_cases:
        md.append(f"")
        md.append(f"## Failed Case Explanations & Root Causes")
        md.append(f"")
        for f in failed_cases:
            md.append(f"### `{f['case_id']}`: {f['title']}")
            if f.get("exception_occurred"):
                md.append(f"- **Exception:** `{f.get('exception_type')}`: {f.get('error_message')}")
            if not f.get("outcome_matched"):
                md.append(f"- **Outcome Mismatch:** Expected `{f['expected_outcome']}` (allowed: `{f['allowed_outcomes']}`), but got `{f['actual_outcome']}`")
            for detail in f.get("claim_details", []):
                if not detail["matched"]:
                    md.append(f"- **Claim mismatch:** {detail['kind']}: expected {detail['expected']}, got {detail['actual']}")
            for detail in f.get("behavior_failures", []) + f.get("expectation_failures", []):
                md.append(f"- **Requirement failed:** {detail}")
            if not f.get("invariants_passed"):
                md.append(f"- **Invariant Violations:**")
                for v in f.get("failed_invariants", []):
                    md.append(f"  - {v}")
            md.append(f"")

    # Limitations & Disclaimers
    md.append(f"")
    md.append(f"## Honest Limitations and Disclaimers")
    md.append(f"")
    md.append(f"1. **Synthetic Corpus Scope:** These evaluation metrics are derived from a synthetic, offline regression corpus. They measure algorithmic correctness and adherence to safety policies; they do not represent real-world accuracy on arbitrary in-the-wild documents.")
    md.append(f"2. **Uncertainty is Not Legitimacy:** `CANNOT_VERIFY` outcomes reflect missing public records or provider limits. They are never counted as legitimate or verified.")
    md.append(f"3. **Offline Mock Latency:** The measured latency ({report.median_latency_ms:.1f}ms median) represents local pipeline execution over recorded mock responses. Production latency will be dominated by external network I/O.")
    md.append(f"")

    return "\n".join(md)


async def run_evaluation(
    corpus_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    case_filter: Optional[str] = None,
    live_mode: bool = False,
    generate_demos: bool = False,
) -> Tuple[int, Dict[str, Any], str]:
    """
    Main evaluation workflow.
    Returns (exit_code, json_results, markdown_summary).
    """
    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if generate_demos:
        print("Generating hackathon demo outputs...")
        try:
            demo_results = await generate_demo_outputs(target_dirs=[out_dir / "demos"])
        except Exception as exc:
            message = f"Demo generation failed: {type(exc).__name__}"
            return 1, {"status": "FAIL", "error": message}, message
        print(f"Generated {len(demo_results)} demo cases.")

    if live_mode:
        print("Running live evaluation...")
        live_report = await run_live_evaluation(output_dir=out_dir)
        print(f"Live evaluation completed with status: {live_report.get('status')}")
        code = 0 if live_report.get("status") == "COMPLETED" and all(r.get("status") == "COMPLETED" and r.get("invariants_passed") and r.get("outcome_matched") for r in live_report.get("results", [])) and live_report.get("results") else 1
        return code, live_report, "Live evaluation completed."

    # Offline evaluation
    try:
        corpus = load_evaluation_corpus(corpus_dir)
    except ValueError as exc:
        message = f"Corpus validation failed: {exc}"
        print(message)
        return 1, {"status": "FAIL", "error": message}, message
    if case_filter:
        corpus = [c for c in corpus if case_filter.lower() in c.case_id.lower()]
        if not corpus:
            print(f"No cases found matching filter '{case_filter}'")
            return 1, {}, f"No cases found matching filter '{case_filter}'"

    print(f"Starting offline evaluation on {len(corpus)} cases...")
    case_results = []

    for idx, case in enumerate(corpus, 1):
        print(f"  [{idx:02d}/{len(corpus):02d}] Evaluating {case.case_id}...", end="", flush=True)
        res = await evaluate_single_case(case)
        case_results.append(res)
        status_str = "OK" if (case_passes(res)) else "FAIL"
        print(f" -> {res['actual_outcome']} ({status_str})")

    # Compute metrics
    report = compute_evaluation_metrics(case_results)

    # Compile run metadata
    metadata = {
        "commit_sha": get_git_commit_sha(),
        "mode": "offline_deterministic",
        "corpus_version": "1.1.0",
        "corpus_sha256": hashlib.sha256(json.dumps([c.model_dump(mode="json") for c in corpus], sort_keys=True).encode()).hexdigest(),
        "evaluation_code_sha256": evaluation_code_hash(),
        "working_tree_dirty": working_tree_dirty(),
        "total_cases": len(corpus),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    }

    # Serialization
    json_payload = {
        "metadata": metadata,
        "summary": {
            "total_cases": report.total_cases,
            "successful_runs": report.successful_runs,
            "exceptional_failures": report.exceptional_failures,
            "outcome_agreement_rate": report.outcome_agreement.value,
            "false_positive_rate": report.false_positive_rate.value,
            "false_negative_rate": report.false_negative_rate.value,
            "uncertainty_retention_rate": report.uncertainty_retention_rate.value,
            "invariant_pass_rate": report.invariant_pass_rate.value,
            "median_latency_ms": report.median_latency_ms,
            "p95_latency_ms": report.p95_latency_ms,
            "avg_provider_calls": report.avg_provider_calls_per_case,
        },
        "metrics": {
            "outcome_agreement": report.outcome_agreement.__dict__,
            "false_positive_rate": report.false_positive_rate.__dict__,
            "false_negative_rate": report.false_negative_rate.__dict__,
            "uncertainty_retention_rate": report.uncertainty_retention_rate.__dict__,
            "claim_status_agreement": report.claim_status_agreement.__dict__,
            "invariant_pass_rate": report.invariant_pass_rate.__dict__,
        },
        "coverage": {
            "avg_ratio": report.avg_coverage_ratio,
            "min_ratio": report.min_coverage_ratio,
            "max_ratio": report.max_coverage_ratio,
            "total_failed_checks": report.total_failed_checks,
            "cases_with_failed_checks": report.cases_with_failed_checks,
        },
        "latency": {
            "min_ms": report.min_latency_ms,
            "avg_ms": report.avg_latency_ms,
            "median_ms": report.median_latency_ms,
            "p95_ms": report.p95_latency_ms,
            "max_ms": report.max_latency_ms,
        },
        "provider_calls": {
            "total": report.total_provider_calls,
            "min": report.min_provider_calls_per_case,
            "avg": report.avg_provider_calls_per_case,
            "median": report.median_provider_calls_per_case,
            "p95": report.p95_provider_calls_per_case,
            "max": report.max_provider_calls_per_case,
        },
        "scenario_groups": {k: v.__dict__ for k, v in report.group_breakdowns.items()},
        "cases": case_results,
    }

    markdown_summary = format_markdown_summary(report, metadata, case_results)

    # Write files
    json_path = out_dir / "evaluation_results.json"
    md_path = out_dir / "evaluation_summary.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_summary)

    print(f"\nWrote results to:\n  - {json_path}\n  - {md_path}\n")

    # Evaluate Acceptance Checks
    acceptance_passed = True
    failure_reasons = []

    failed_required_cases = [r["case_id"] for r in case_results if not case_passes(r)]
    if failed_required_cases:
        acceptance_passed = False
        failure_reasons.append("Required case checks failed: " + ", ".join(failed_required_cases))

    if report.exceptional_failures > 0:
        acceptance_passed = False
        failure_reasons.append(f"{report.exceptional_failures} case(s) threw an unhandled exception")

    if report.false_positive_rate.value > 0.0:
        acceptance_passed = False
        failure_reasons.append(f"False Positive Rate > 0: {report.false_positive_rate.formatted}")

    if report.false_negative_rate.value > 0.0:
        acceptance_passed = False
        failure_reasons.append(f"False Negative Rate > 0: {report.false_negative_rate.formatted}")

    if report.invariant_pass_rate.value < 1.0:
        acceptance_passed = False
        failure_reasons.append(f"Invariant pass rate < 100%: {report.invariant_pass_rate.formatted}")

    if report.outcome_agreement.value < 0.90:
        acceptance_passed = False
        failure_reasons.append(f"Outcome agreement < 90%: {report.outcome_agreement.formatted}")

    if acceptance_passed:
        print("ALL ACCEPTANCE CHECKS PASSED (exit code 0)")
        return 0, json_payload, markdown_summary
    else:
        print("ACCEPTANCE CHECKS FAILED:")
        for r in failure_reasons:
            print(f"  - {r}")
        return 1, json_payload, markdown_summary


def main():
    parser = argparse.ArgumentParser(description="AsliOffer Evaluation & Demo Runner (Task 13)")
    parser.add_argument("--corpus-dir", type=Path, default=None, help="Path to evaluation corpus directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Path to output directory")
    parser.add_argument("--case", type=str, default=None, help="Filter to run a specific case by ID")
    parser.add_argument("--live", action="store_true", help="Execute live evaluation using SerpApiClient")
    parser.add_argument("--generate-demos", action="store_true", help="Generate hackathon demonstration payloads")

    args = parser.parse_args()

    exit_code, _, _ = asyncio.run(
        run_evaluation(
            corpus_dir=args.corpus_dir,
            output_dir=args.output_dir,
            case_filter=args.case,
            live_mode=args.live,
            generate_demos=args.generate_demos,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
