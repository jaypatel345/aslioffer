"""Executable case requirements independent of the pipeline's aggregate verdict."""
import re
from app.schemas.contract import ClaimKind, ClaimStatus, EvidenceRelation, OverallOutcome
from app.evaluation.invariants import check_privacy_and_secret_leakage


def redact_diagnostic(message, secrets=()):
    for secret in secrets:
        if secret:
            message = message.replace(secret, '[REDACTED_SECRET]')
    message = re.sub(r'(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)[^\s,;]+', r'\1\2[REDACTED_SECRET]', message)
    return message


def check_case_behaviors(case, result):
    kinds = {c.claim_id: c.kind for c in result.claims}
    grounded = lambda kind: any(a.status == ClaimStatus.SUPPORTED and kinds.get(a.claim_id) == kind
        and any(e.evidence_id in a.evidence_ids and e.relation == EvidenceRelation.SUPPORTS for e in result.evidence)
        for a in result.assessed_claims)
    predicates = {
        'authenticity_unconfirmed': result.authenticity_status.value == 'UNCONFIRMED',
        'strong_warning_present': result.overall_outcome == OverallOutcome.HIGH_RISK and
            (grounded(ClaimKind.PAYMENT_REQUEST) or grounded(ClaimKind.CREDENTIAL_REQUEST)),
        'credential_theft_warning': result.overall_outcome == OverallOutcome.HIGH_RISK and grounded(ClaimKind.CREDENTIAL_REQUEST),
        'has_confirmation_route': result.confirmation_route is not None,
        'fake_verification': result.authenticity_status.value != 'UNCONFIRMED',
        'leak_secret': not check_privacy_and_secret_leakage(result, case.planted_secrets).passed,
    }
    failures = []
    for name in case.required_behaviors:
        if name not in predicates:
            failures.append(f'Unknown required behavior: {name}')
        elif not predicates[name]:
            failures.append(f'Required behavior missing: {name}')
    for name in case.forbidden_behaviors:
        if name not in predicates:
            failures.append(f'Unknown forbidden behavior: {name}')
        elif predicates[name]:
            failures.append(f'Forbidden behavior observed: {name}')
    return failures


def check_case_expectations(case, result, agent_dimensions=None):
    """Check positive feature execution, negative boundaries and scenario limits."""
    failures = []
    claims = {c.kind.value: c for c in result.claims}
    assessed = {a.claim_id: a for a in result.assessed_claims}
    checks = case.expectations
    known = {'claim_values', 'reason_codes', 'min_provider_calls', 'max_provider_calls',
             'required_steps', 'required_error_codes', 'confirmation_channel', 'confirmation_destination',
             'no_confirmation_route', 'forbidden_queries', 'required_query_terms', 'max_checked_claims',
             'required_evidence_terms', 'agent_dimensions'}
    for key in set(checks) - known:
        failures.append(f'Unknown expectation: {key}')
    for name, status in checks.get('agent_dimensions', {}).items():
        if (agent_dimensions or {}).get(name) != status:
            failures.append(f'Recruiter assessment dimension {name} did not establish {status}')
    for kind, value in checks.get('claim_values', {}).items():
        if kind not in claims or claims[kind].value != value:
            failures.append(f'Claim value mismatch: {kind}')
    for kind, codes in checks.get('reason_codes', {}).items():
        a = assessed.get(claims[kind].claim_id) if kind in claims else None
        if not a or not set(codes).issubset(a.reason_codes):
            failures.append(f'Missing assessment reason codes for {kind}: {codes}')
    count = len(result.tool_trace)
    if count < checks.get('min_provider_calls', 0) or count > checks.get('max_provider_calls', float('inf')):
        failures.append('Provider call count outside the case limits')
    if result.coverage.checked_claims > checks.get('max_checked_claims', float('inf')):
        failures.append('Checked coverage exceeds the case execution limit')
    steps = {c.step for c in result.tool_trace if c.status.value == 'COMPLETED'}
    for step in checks.get('required_steps', []):
        if step not in steps:
            failures.append(f'Required completed tool step missing: {step}')
    errors = {e.code for e in result.errors}
    for code in checks.get('required_error_codes', []):
        if code not in errors:
            failures.append(f'Required structured error missing: {code}')
    queries = [c.query or '' for c in result.tool_trace]
    for term in checks.get('forbidden_queries', []):
        if any(term.lower() in q.lower() for q in queries):
            failures.append('Forbidden input was searched')
    for term in checks.get('required_query_terms', []):
        if not any(term.lower() in q.lower() for q in queries):
            failures.append(f'Required query term missing: {term}')
    for field in ('confirmation_channel', 'confirmation_destination'):
        if field in checks:
            attr = field.removeprefix('confirmation_')
            if not result.confirmation_route or getattr(result.confirmation_route, attr) != checks[field]:
                failures.append(f'{field} differs from the specified route')
    if checks.get('no_confirmation_route') and result.confirmation_route:
        failures.append('Unexpected confirmation route')
    for term in checks.get('required_evidence_terms', []):
        if not any(term.lower() in (e.title + ' ' + e.quote_or_snippet).lower() for e in result.evidence):
            failures.append(f'Required published evidence missing: {term}')
    return failures
