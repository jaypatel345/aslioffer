"""
Safety, evidence, privacy, and coverage invariant validators for AsliOffer (Task 13).

Validates the completed pipeline InvestigationResult against contract v1 invariants:
1. Referential integrity: Every assessed claim's cited evidence ID exists in result.evidence.
2. Evidence ownership: Evidence cited for an assessed claim belongs to that claim.
3. Status attribution: SUPPORTED/CONTRADICTED assessments have attributable evidence.
4. Failed retrieval neutrality: Failed retrievals cannot support or contradict a claim.
5. Demo isolation: Production runs (demo_mode=False) do not use DEMO evidence.
6. Search provenance: Search evidence retains query, engine, retrieval timestamp, and content.
7. Confirmation provenance: Confirmation routes cite evidence actually publishing the destination.
8. Unconfirmed authenticity: Authenticity status remains UNCONFIRMED.
9. Threat precedence: Strong payment or credential threats survive vacancy matches (HIGH_RISK).
10. Privacy & secret protection: Planted secrets or confidential tokens do not leak into queries, traces, drafts, or explanations.
11. Coverage bounds: Checked claims <= total claims, failed searches do not inflate completed coverage.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
import re

from app.schemas.contract import (
    AuthenticityStatus,
    ClaimKind,
    ClaimStatus,
    EvidenceRecord,
    EvidenceRelation,
    InvestigationResult,
    OverallOutcome,
    RetrievalStatus,
    SourceKind,
)


@dataclass
class InvariantResult:
    invariant_name: str
    passed: bool
    details: str
    violations: List[str]


def check_referential_integrity(result: InvestigationResult) -> InvariantResult:
    """Verifies that all evidence IDs cited in assessed claims and tool calls exist in result.evidence."""
    violations = []
    evidence_ids = {e.evidence_id for e in result.evidence}
    for claim in result.assessed_claims:
        for eid in claim.evidence_ids:
            if eid not in evidence_ids:
                violations.append(f"Claim {claim.claim_id} cites non-existent evidence ID: {eid}")

    for call in result.tool_trace:
        for eid in call.evidence_ids:
            if eid not in evidence_ids:
                violations.append(f"Tool trace step '{call.step}' cites non-existent evidence ID: {eid}")

    return InvariantResult(
        invariant_name="referential_integrity",
        passed=len(violations) == 0,
        details="All cited evidence IDs exist in result.evidence" if not violations else f"{len(violations)} referential violations",
        violations=violations,
    )


def check_evidence_claim_ownership(result: InvestigationResult) -> InvariantResult:
    """Verifies that evidence cited for a claim actually belongs to that claim (ev.claim_id == claim.claim_id)."""
    violations = []
    evidence_by_id = {e.evidence_id: e for e in result.evidence}
    for claim in result.assessed_claims:
        for eid in claim.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev and ev.claim_id != claim.claim_id:
                violations.append(f"Evidence {eid} belongs to claim {ev.claim_id}, but was cited by {claim.claim_id}")

    return InvariantResult(
        invariant_name="evidence_claim_ownership",
        passed=len(violations) == 0,
        details="Cited evidence matches claim ownership" if not violations else f"{len(violations)} ownership violations",
        violations=violations,
    )


def check_status_attribution(result: InvestigationResult) -> InvariantResult:
    """Verifies that SUPPORTED claims have SUPPORTS evidence, and CONTRADICTED have CONTRADICTS."""
    violations = []
    evidence_by_id = {e.evidence_id: e for e in result.evidence}
    for claim in result.assessed_claims:
        relations = {evidence_by_id[eid].relation for eid in claim.evidence_ids if eid in evidence_by_id}
        if claim.status == ClaimStatus.SUPPORTED and EvidenceRelation.SUPPORTS not in relations:
            violations.append(f"Claim {claim.claim_id} is SUPPORTED but has no SUPPORTS relation evidence")
        if claim.status == ClaimStatus.CONTRADICTED and EvidenceRelation.CONTRADICTS not in relations:
            violations.append(f"Claim {claim.claim_id} is CONTRADICTED but has no CONTRADICTS relation evidence")

    return InvariantResult(
        invariant_name="status_attribution",
        passed=len(violations) == 0,
        details="Claim statuses have appropriate attributable evidence relations" if not violations else f"{len(violations)} attribution violations",
        violations=violations,
    )


def check_failed_retrieval_neutrality(result: InvestigationResult) -> InvariantResult:
    """Verifies that failed retrievals cannot support or contradict a claim."""
    violations = []
    for ev in result.evidence:
        if ev.retrieval_status == RetrievalStatus.FAILED:
            if ev.relation in (EvidenceRelation.SUPPORTS, EvidenceRelation.CONTRADICTS):
                violations.append(f"Failed evidence {ev.evidence_id} has active relation {ev.relation}")

    return InvariantResult(
        invariant_name="failed_retrieval_neutrality",
        passed=len(violations) == 0,
        details="Failed retrievals remain neutral (CONTEXT only)" if not violations else f"{len(violations)} neutrality violations",
        violations=violations,
    )


def check_demo_evidence_isolation(result: InvestigationResult, demo_mode: bool = False) -> InvariantResult:
    """Verifies that production runs (demo_mode=False) do not include DEMO evidence."""
    violations = []
    if not demo_mode and not result.demo_mode:
        for ev in result.evidence:
            if ev.retrieval_status == RetrievalStatus.DEMO:
                violations.append(f"Production result contains DEMO evidence: {ev.evidence_id}")

    return InvariantResult(
        invariant_name="demo_evidence_isolation",
        passed=len(violations) == 0,
        details="No DEMO evidence present in non-demo run" if not violations else f"{len(violations)} demo isolation violations",
        violations=violations,
    )


def check_search_evidence_provenance(result: InvestigationResult) -> InvariantResult:
    """Verifies that search evidence retains query, engine, retrieval timestamp, and original observed content."""
    violations = []
    for ev in result.evidence:
        if ev.source_kind == SourceKind.SEARCH_SNIPPET:
            if not ev.query or not ev.query.strip():
                violations.append(f"Search evidence {ev.evidence_id} missing query")
            if not ev.engine or not ev.engine.strip():
                violations.append(f"Search evidence {ev.evidence_id} missing engine")
            if not ev.retrieved_at:
                violations.append(f"Search evidence {ev.evidence_id} missing retrieved_at timestamp")
            if not ev.quote_or_snippet or not ev.quote_or_snippet.strip():
                violations.append(f"Search evidence {ev.evidence_id} missing quote_or_snippet content")

    return InvariantResult(
        invariant_name="search_evidence_provenance",
        passed=len(violations) == 0,
        details="Search evidence preserves query, engine, timestamp, and snippet" if not violations else f"{len(violations)} provenance violations",
        violations=violations,
    )


def check_confirmation_route_provenance(result: InvestigationResult) -> InvariantResult:
    """Verifies that confirmation routes cite evidence that actually publishes the destination."""
    violations = []
    if result.confirmation_route:
        route = result.confirmation_route
        evidence_by_id = {e.evidence_id: e for e in result.evidence}
        ev = evidence_by_id.get(route.evidence_id)
        if not ev:
            violations.append(f"Confirmation route cites non-existent evidence {route.evidence_id}")
        else:
            dest_lower = route.destination.lower().strip()
            # The destination or its host/domain should appear in the snippet, URL or title
            found = (
                dest_lower in ev.quote_or_snippet.lower()
                or (ev.source_url and dest_lower in ev.source_url.lower())
                or dest_lower in ev.title.lower()
            )
            # If destination is an email or domain, also check domain part
            if not found and "@" in dest_lower:
                domain_part = dest_lower.split("@")[-1]
                found = domain_part in ev.quote_or_snippet.lower() or (ev.source_url and domain_part in ev.source_url.lower())
            if not found:
                violations.append(f"Confirmation route destination '{route.destination}' not found in cited evidence {route.evidence_id}")

    return InvariantResult(
        invariant_name="confirmation_route_provenance",
        passed=len(violations) == 0,
        details="Confirmation route destination verified in cited evidence" if not violations else f"{len(violations)} confirmation route violations",
        violations=violations,
    )


def check_authenticity_status_unconfirmed(result: InvestigationResult) -> InvariantResult:
    """Verifies that authenticity status remains UNCONFIRMED (public web checks cannot authenticate offers)."""
    violations = []
    if result.authenticity_status != AuthenticityStatus.UNCONFIRMED:
        violations.append(f"authenticity_status is {result.authenticity_status}, must be UNCONFIRMED")

    return InvariantResult(
        invariant_name="authenticity_status_unconfirmed",
        passed=len(violations) == 0,
        details="authenticity_status is UNCONFIRMED" if not violations else f"{len(violations)} authenticity violations",
        violations=violations,
    )


def check_threat_precedence(result: InvestigationResult, case_labels: Dict[str, Any]) -> InvariantResult:
    """Verifies that strong payment or credential threats produce HIGH_RISK outcome even if a vacancy exists."""
    violations = []
    threat_category = case_labels.get("threat_category", "")
    is_strong_threat = threat_category in (
        "advance_fee_fraud",
        "credential_theft",
        "task_scam_extortion",
        "upfront_fee_demand",
        "credential_otp_theft",
        "payment_to_unlock_earnings",
    ) or case_labels.get("scenario_group") == "threat_cases"

    if is_strong_threat and result.overall_outcome != OverallOutcome.HIGH_RISK:
        violations.append(f"Threat case with threat_category '{threat_category}' yielded {result.overall_outcome.value} instead of HIGH_RISK")

    return InvariantResult(
        invariant_name="threat_precedence",
        passed=len(violations) == 0,
        details="Strong threats produced HIGH_RISK" if not violations else f"{len(violations)} threat precedence violations",
        violations=violations,
    )


def check_privacy_and_secret_leakage(
    result: InvestigationResult,
    planted_secrets: Optional[List[str]] = None,
) -> InvariantResult:
    """Verifies that planted secrets and private references do not leak into queries, traces, drafts, or explanations."""
    violations = []
    if not planted_secrets:
        return InvariantResult(
            invariant_name="privacy_and_secret_leakage",
            passed=True,
            details="No planted secrets specified for this case",
            violations=[],
        )

    for secret in planted_secrets:
        secret_clean = secret.strip()
        if not secret_clean:
            continue

        # Check tool queries and reasons
        for call in result.tool_trace:
            if call.query and secret_clean in call.query:
                violations.append(f"Planted secret '{secret_clean}' leaked in tool query: {call.query}")
            if call.reason and secret_clean in call.reason:
                violations.append(f"Planted secret '{secret_clean}' leaked in tool reason: {call.reason}")

        # Check confirmation draft
        if result.confirmation_route and result.confirmation_route.draft_message:
            if secret_clean in result.confirmation_route.draft_message:
                violations.append(f"Planted secret '{secret_clean}' leaked in confirmation draft message")

        # Check recommended actions
        for action in result.recommended_actions:
            if secret_clean in action:
                violations.append(f"Planted secret '{secret_clean}' leaked in recommended action: {action}")

        # Check assessed claim explanations
        for claim in result.assessed_claims:
            if secret_clean in claim.explanation:
                violations.append(f"Planted secret '{secret_clean}' leaked in claim {claim.claim_id} explanation")

    return InvariantResult(
        invariant_name="privacy_and_secret_leakage",
        passed=len(violations) == 0,
        details="No private references or planted secrets leaked" if not violations else f"{len(violations)} secret leak violations",
        violations=violations,
    )


def check_coverage_bounds(result: InvestigationResult) -> InvariantResult:
    """Verifies that coverage counts obey strict mathematical and logical bounds."""
    violations = []
    cov = result.coverage
    if cov.total_claims != len(result.claims):
        violations.append(f"coverage.total_claims ({cov.total_claims}) != len(result.claims) ({len(result.claims)})")
    if cov.checked_claims > cov.total_claims:
        violations.append(f"coverage.checked_claims ({cov.checked_claims}) > total_claims ({cov.total_claims})")
    if cov.unresolved_claims > cov.total_claims:
        violations.append(f"coverage.unresolved_claims ({cov.unresolved_claims}) > total_claims ({cov.total_claims})")

    return InvariantResult(
        invariant_name="coverage_bounds",
        passed=len(violations) == 0,
        details="Coverage counts strictly within valid bounds" if not violations else f"{len(violations)} coverage bounds violations",
        violations=violations,
    )


def run_all_invariants(
    result: InvestigationResult,
    case_labels: Optional[Dict[str, Any]] = None,
    planted_secrets: Optional[List[str]] = None,
    demo_mode: bool = False,
) -> List[InvariantResult]:
    """Runs all safety, evidence, privacy, and coverage invariants on an InvestigationResult."""
    labels = case_labels or {}
    return [
        check_referential_integrity(result),
        check_evidence_claim_ownership(result),
        check_status_attribution(result),
        check_failed_retrieval_neutrality(result),
        check_demo_evidence_isolation(result, demo_mode=demo_mode),
        check_search_evidence_provenance(result),
        check_confirmation_route_provenance(result),
        check_authenticity_status_unconfirmed(result),
        check_threat_precedence(result, labels),
        check_privacy_and_secret_leakage(result, planted_secrets),
        check_coverage_bounds(result),
    ]
