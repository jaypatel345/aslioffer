"""
Evaluation metrics calculation for AsliOffer investigation pipeline (Task 13).

Measures accuracy, evidence quality, coverage, latency, and search usage honestly:
- Every metric has an explicit definition and denominator.
- CANNOT_VERIFY is treated as honest uncertainty, NOT as a legitimate or fraudulent verdict.
- Offline mock latency is explicitly identified as mock pipeline overhead, NOT production performance.
- Cached requests consume 0 provider calls.
- Handles empty denominators safely without ZeroDivisionError.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional


@dataclass
class MetricSummary:
    name: str
    description: str
    numerator: float
    denominator: float
    value: float  # numerator / denominator, or 0.0 if denominator is 0
    formatted: str
    interpretation: str


@dataclass
class ScenarioGroupMetrics:
    group_name: str
    case_count: int
    passed_cases: int
    outcome_agreement_rate: float
    invariant_pass_rate: float
    avg_provider_calls: float
    avg_latency_ms: float


@dataclass
class EvaluationMetricsReport:
    total_cases: int
    successful_runs: int
    exceptional_failures: int

    # Core outcome metrics
    outcome_agreement: MetricSummary
    false_positive_rate: MetricSummary
    false_negative_rate: MetricSummary
    uncertainty_retention_rate: MetricSummary
    claim_status_agreement: MetricSummary
    invariant_pass_rate: MetricSummary

    # Coverage metrics
    avg_coverage_ratio: float
    min_coverage_ratio: float
    max_coverage_ratio: float
    total_failed_checks: int
    cases_with_failed_checks: int

    # Provider call metrics
    total_provider_calls: int
    min_provider_calls_per_case: int
    avg_provider_calls_per_case: float
    median_provider_calls_per_case: float
    p95_provider_calls_per_case: float
    max_provider_calls_per_case: int

    # Latency metrics (offline mock pipeline latency)
    min_latency_ms: float
    avg_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    max_latency_ms: float

    # Scenario breakdowns
    group_breakdowns: Dict[str, ScenarioGroupMetrics] = field(default_factory=dict)


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    """Safely divides two numbers, returning default if denominator is zero."""
    if den == 0 or not math.isfinite(den):
        return default
    return num / den


def percentile(values: List[float], p: float) -> float:
    """Computes the p-th percentile (0 <= p <= 100) using linear interpolation."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_v[int(k)]
    d0 = sorted_v[int(f)] * (c - k)
    d1 = sorted_v[int(c)] * (k - f)
    return d0 + d1


def compute_evaluation_metrics(case_results: List[Dict[str, Any]]) -> EvaluationMetricsReport:
    """
    Computes honest, rigorous evaluation metrics from a list of case execution records.

    Each case_result dict contains:
    - case_id: str
    - scenario_group: str
    - outcome_matched: bool
    - actual_outcome: str
    - expected_outcome: str
    - claim_matches: int
    - claim_total: int
    - invariants_passed: bool
    - failed_invariants: List[str]
    - coverage_ratio: float
    - failed_checks_count: int
    - provider_calls_count: int
    - latency_ms: float
    - exception_occurred: bool
    """
    total = len(case_results)
    if total == 0:
        empty_metric = lambda n, d: MetricSummary(
            name=n, description=d, numerator=0, denominator=0, value=0.0,
            formatted="N/A (no cases)", interpretation="Empty denominator"
        )
        return EvaluationMetricsReport(
            total_cases=0,
            successful_runs=0,
            exceptional_failures=0,
            outcome_agreement=empty_metric("outcome_agreement", "Agreement with specified expected outcomes"),
            false_positive_rate=empty_metric("false_positive_rate", "Legitimate cases classified as HIGH_RISK"),
            false_negative_rate=empty_metric("false_negative_rate", "Threat cases failing to produce HIGH_RISK"),
            uncertainty_retention_rate=empty_metric("uncertainty_retention_rate", "Inconclusive cases staying CANNOT_VERIFY"),
            claim_status_agreement=empty_metric("claim_status_agreement", "Claim status agreement where expectation was defined"),
            invariant_pass_rate=empty_metric("invariant_pass_rate", "Cases passing 100% of safety and evidence invariants"),
            avg_coverage_ratio=0.0,
            min_coverage_ratio=0.0,
            max_coverage_ratio=0.0,
            total_failed_checks=0,
            cases_with_failed_checks=0,
            total_provider_calls=0,
            min_provider_calls_per_case=0,
            avg_provider_calls_per_case=0.0,
            median_provider_calls_per_case=0.0,
            p95_provider_calls_per_case=0.0,
            max_provider_calls_per_case=0,
            min_latency_ms=0.0,
            avg_latency_ms=0.0,
            median_latency_ms=0.0,
            p95_latency_ms=0.0,
            max_latency_ms=0.0,
            group_breakdowns={},
        )

    successful_runs = sum(1 for r in case_results if not r.get("exception_occurred"))
    exceptional_failures = sum(1 for r in case_results if r.get("exception_occurred"))

    # 1. Outcome agreement
    agreed_outcomes = sum(1 for r in case_results if r.get("outcome_matched"))
    outcome_agreement_val = safe_div(agreed_outcomes, total)
    outcome_agreement = MetricSummary(
        name="outcome_agreement",
        description="Fraction of cases where pipeline outcome matches independently specified expected outcome",
        numerator=agreed_outcomes,
        denominator=total,
        value=outcome_agreement_val,
        formatted=f"{agreed_outcomes}/{total} ({outcome_agreement_val * 100:.1f}%)",
        interpretation="Agreement against specified ground-truth targets (does not claim real-world accuracy)",
    )

    # 2. False Positive Rate (Legitimate cases misclassified as HIGH_RISK)
    legit_cases = [r for r in case_results if r.get("scenario_group") in ("legitimate_corroborated", "benign_policy")]
    legit_total = len(legit_cases)
    legit_high_risk = sum(1 for r in legit_cases if r.get("actual_outcome") == "HIGH_RISK")
    fpr_val = safe_div(legit_high_risk, legit_total)
    false_positive_rate = MetricSummary(
        name="false_positive_rate",
        description="Legitimate recruitment or benign policy cases incorrectly convicted as HIGH_RISK",
        numerator=legit_high_risk,
        denominator=legit_total,
        value=fpr_val,
        formatted=f"{legit_high_risk}/{legit_total} ({fpr_val * 100:.1f}%)" if legit_total > 0 else "0/0 (N/A)",
        interpretation="Zero false positives required: legitimate employers/policies must never be marked HIGH_RISK",
    )

    # 3. False Negative Rate (Threat cases failing to produce HIGH_RISK)
    threat_cases = [r for r in case_results if r.get("scenario_group") == "threat_cases"]
    threat_total = len(threat_cases)
    threat_non_high_risk = sum(1 for r in threat_cases if r.get("actual_outcome") != "HIGH_RISK")
    fnr_val = safe_div(threat_non_high_risk, threat_total)
    false_negative_rate = MetricSummary(
        name="false_negative_rate",
        description="Explicit upfront fee or credential theft cases that failed to yield HIGH_RISK",
        numerator=threat_non_high_risk,
        denominator=threat_total,
        value=fnr_val,
        formatted=f"{threat_non_high_risk}/{threat_total} ({fnr_val * 100:.1f}%)" if threat_total > 0 else "0/0 (N/A)",
        interpretation="Zero false negatives required: explicit payment and OTP demands must produce HIGH_RISK",
    )

    # 4. Uncertainty Retention Rate (Honest uncertainty)
    uncertain_cases = [r for r in case_results if r.get("expected_outcome") == "CANNOT_VERIFY"]
    uncertain_total = len(uncertain_cases)
    uncertain_actual = sum(1 for r in uncertain_cases if r.get("actual_outcome") == "CANNOT_VERIFY")
    urr_val = safe_div(uncertain_actual, uncertain_total)
    uncertainty_retention_rate = MetricSummary(
        name="uncertainty_retention_rate",
        description="Cases designed to remain inconclusive (sparse footprint, empty search, provider failure) correctly yielding CANNOT_VERIFY",
        numerator=uncertain_actual,
        denominator=uncertain_total,
        value=urr_val,
        formatted=f"{uncertain_actual}/{uncertain_total} ({urr_val * 100:.1f}%)" if uncertain_total > 0 else "0/0 (N/A)",
        interpretation="High retention indicates honest restraint: missing evidence is NOT turned into proof of fraud",
    )

    # 5. Claim status agreement
    total_claim_expectations = sum(r.get("claim_total", 0) for r in case_results)
    total_claim_matches = sum(r.get("claim_matches", 0) for r in case_results)
    csa_val = safe_div(total_claim_matches, total_claim_expectations)
    claim_status_agreement = MetricSummary(
        name="claim_status_agreement",
        description="Agreement between actual and expected claim statuses for explicitly evaluated claims",
        numerator=total_claim_matches,
        denominator=total_claim_expectations,
        value=csa_val,
        formatted=f"{total_claim_matches}/{total_claim_expectations} ({csa_val * 100:.1f}%)" if total_claim_expectations > 0 else "0/0 (N/A)",
        interpretation="Evaluates fine-grained claim status accuracy (employer, recruiter, role, compensation, payment)",
    )

    # 6. Invariant pass rate
    invariants_passed_cases = sum(1 for r in case_results if r.get("invariants_passed"))
    ipr_val = safe_div(invariants_passed_cases, total)
    invariant_pass_rate = MetricSummary(
        name="invariant_pass_rate",
        description="Cases satisfying all 11 safety, evidence integrity, privacy, and coverage bounds invariants",
        numerator=invariants_passed_cases,
        denominator=total,
        value=ipr_val,
        formatted=f"{invariants_passed_cases}/{total} ({ipr_val * 100:.1f}%)",
        interpretation="Strict safety and integrity check: 100% required for acceptance",
    )

    # 7. Coverage distribution
    coverage_ratios = [r.get("coverage_ratio", 0.0) for r in case_results]
    avg_coverage = sum(coverage_ratios) / total if total > 0 else 0.0
    min_coverage = min(coverage_ratios) if coverage_ratios else 0.0
    max_coverage = max(coverage_ratios) if coverage_ratios else 0.0

    total_failed_checks = sum(r.get("failed_checks_count", 0) for r in case_results)
    cases_with_failed = sum(1 for r in case_results if r.get("failed_checks_count", 0) > 0)

    # 8. Provider calls distribution
    provider_calls = [r.get("provider_calls_count", 0) for r in case_results]
    total_calls = sum(provider_calls)
    min_calls = min(provider_calls) if provider_calls else 0
    max_calls = max(provider_calls) if provider_calls else 0
    avg_calls = total_calls / total if total > 0 else 0.0
    med_calls = percentile(provider_calls, 50)
    p95_calls = percentile(provider_calls, 95)

    # 9. Latency distribution (ms)
    latencies = [r.get("latency_ms", 0.0) for r in case_results]
    min_lat = min(latencies) if latencies else 0.0
    max_lat = max(latencies) if latencies else 0.0
    avg_lat = sum(latencies) / total if total > 0 else 0.0
    med_lat = percentile(latencies, 50)
    p95_lat = percentile(latencies, 95)

    # 10. Group breakdowns
    group_names = sorted(list({r.get("scenario_group", "default") for r in case_results}))
    group_breakdowns: Dict[str, ScenarioGroupMetrics] = {}
    for g_name in group_names:
        g_cases = [r for r in case_results if r.get("scenario_group") == g_name]
        g_total = len(g_cases)
        g_passed = sum(1 for r in g_cases if r.get("outcome_matched") and r.get("invariants_passed"))
        g_agreement = safe_div(sum(1 for r in g_cases if r.get("outcome_matched")), g_total)
        g_inv = safe_div(sum(1 for r in g_cases if r.get("invariants_passed")), g_total)
        g_calls = sum(r.get("provider_calls_count", 0) for r in g_cases) / g_total if g_total > 0 else 0.0
        g_lat = sum(r.get("latency_ms", 0.0) for r in g_cases) / g_total if g_total > 0 else 0.0

        group_breakdowns[g_name] = ScenarioGroupMetrics(
            group_name=g_name,
            case_count=g_total,
            passed_cases=g_passed,
            outcome_agreement_rate=g_agreement,
            invariant_pass_rate=g_inv,
            avg_provider_calls=g_calls,
            avg_latency_ms=g_lat,
        )

    return EvaluationMetricsReport(
        total_cases=total,
        successful_runs=successful_runs,
        exceptional_failures=exceptional_failures,
        outcome_agreement=outcome_agreement,
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        uncertainty_retention_rate=uncertainty_retention_rate,
        claim_status_agreement=claim_status_agreement,
        invariant_pass_rate=invariant_pass_rate,
        avg_coverage_ratio=avg_coverage,
        min_coverage_ratio=min_coverage,
        max_coverage_ratio=max_coverage,
        total_failed_checks=total_failed_checks,
        cases_with_failed_checks=cases_with_failed,
        total_provider_calls=total_calls,
        min_provider_calls_per_case=min_calls,
        avg_provider_calls_per_case=avg_calls,
        median_provider_calls_per_case=med_calls,
        p95_provider_calls_per_case=p95_calls,
        max_provider_calls_per_case=max_calls,
        min_latency_ms=min_lat,
        avg_latency_ms=avg_lat,
        median_latency_ms=med_lat,
        p95_latency_ms=p95_lat,
        max_latency_ms=max_lat,
        group_breakdowns=group_breakdowns,
    )
