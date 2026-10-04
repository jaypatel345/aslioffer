"""
Coverage calculator for AsliOffer investigation pipeline (Task 10).

Computes contract-v1 Coverage:
- total_claims = number of returned claims
- checked_claims = claims whose relevant assessment check actually executed
- unresolved_claims = claims whose status is UNRESOLVED
- failed_checks = count of actual failed checks, counted once
"""

from typing import List

from app.schemas.contract import AssessedClaim, Claim, ClaimStatus, Coverage


def compute_coverage(
    claims: List[Claim],
    assessed_claims: List[AssessedClaim],
    failed_check_count: int = 0,
    checked_claim_ids=None,
) -> Coverage:
    total = len(claims)
    assessed_by_id = {a.claim_id: a for a in assessed_claims}

    checked_count = 0
    unresolved_count = 0

    for c in claims:
        a = assessed_by_id.get(c.claim_id)
        if not a:
            continue
        if (c.claim_id in checked_claim_ids if checked_claim_ids is not None else a.status in (ClaimStatus.SUPPORTED, ClaimStatus.CONTRADICTED)) and c.value is not None:
            checked_count += 1
        if a.status in (ClaimStatus.UNRESOLVED, ClaimStatus.NOT_CHECKED):
            unresolved_count += 1

    checked_count = min(checked_count, total)
    unresolved_count = min(unresolved_count, total)
    failed_count = max(0, failed_check_count)

    return Coverage(
        checked_claims=checked_count,
        total_claims=total,
        unresolved_claims=unresolved_count,
        failed_checks=failed_count,
    )
