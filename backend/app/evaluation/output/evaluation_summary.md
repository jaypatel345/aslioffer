# AsliOffer Evaluation Report (Task 13)

**Date:** `2026-10-04T10:17:35.638482+00:00` | **Commit:** `2533cb7d` | **Mode:** `offline_deterministic` | **Cases:** `24`

## Status: PASS

- **Outcome Agreement:** 24/24 (100.0%)
- **False Positive Rate:** 0/9 (0.0%)
- **False Negative Rate:** 0/5 (0.0%)
- **Uncertainty Retention:** 18/18 (100.0%)
- **Safety Invariant Pass Rate:** 24/24 (100.0%)
- **Pipeline Latency (mock):** Median: `9.2ms` | p95: `24.7ms`

## Honest Metrics & Explicit Denominators

| Metric | Formula / Denominator | Measured Value | Standard / Requirement |
|---|---|---|---|
| **Outcome Agreement** | `agreed_outcomes / total_cases` (24/24) | `24/24 (100.0%)` | High agreement on specified cases |
| **False Positive Rate** | `legit_marked_high_risk / legit_cases` (0/9) | `0/9 (0.0%)` | **0.0%** (zero legitimate offers marked HIGH_RISK) |
| **False Negative Rate** | `threats_missing_warning / threat_cases` (0/5) | `0/5 (0.0%)` | **0.0%** (all fee/OTP threats flagged) |
| **Uncertainty Retention** | `actual_cannot_verify / expected_cannot_verify` (18/18) | `18/18 (100.0%)` | Honest restraint on sparse/missing records |
| **Claim Status Agreement** | `matching_claims / expected_claims` (1/2) | `1/2 (50.0%)` | Fine-grained extraction & corroboration alignment |
| **Invariant Pass Rate** | `cases_with_all_invariants / total_cases` (24/24) | `24/24 (100.0%)` | **100.0%** (strictly zero invariant violations) |
| **Coverage Completeness** | Mean `checked_claims / total_claims` | `49.7%` (min: `0%`, max: `100%`) | Completeness measurement |
| **Tool Provider Calls** | Actual external queries from tool trace | Mean: `3.0` | Median: `3` | p95: `5` |

## Scenario Group Breakdown

| Scenario Group | Cases | Passed | Agreement | Invariants | Avg Calls | Avg Latency |
|---|---|---|---|---|---|---|
| `ambiguous_unresolved` | 6 | 6 | 100.0% | 100.0% | 3.7 | 11.8ms |
| `benign_policy` | 2 | 2 | 100.0% | 100.0% | 2.0 | 17.5ms |
| `legitimate_corroborated` | 7 | 7 | 100.0% | 100.0% | 2.7 | 11.6ms |
| `system_and_limits` | 4 | 4 | 100.0% | 100.0% | 2.2 | 6.9ms |
| `threat_cases` | 5 | 5 | 100.0% | 100.0% | 3.8 | 10.6ms |

## Per-Case Evaluation Results

| Case ID | Group | Expected | Actual | Invariants | Calls | Coverage | Result |
|---|---|---|---|---|---|---|---|
| `EVAL-01-UPFRONT-FEE-DEMAND` | `threat_cases` | `HIGH_RISK` | `HIGH_RISK` | YES | 5 | 100% | **PASS** |
| `EVAL-02-BANK-OTP-CREDENTIAL-DEMAND` | `threat_cases` | `HIGH_RISK` | `HIGH_RISK` | YES | 2 | 50% | **PASS** |
| `EVAL-03-TASK-SCAM-UNLOCK-EARNINGS` | `threat_cases` | `HIGH_RISK` | `HIGH_RISK` | YES | 0 | 50% | **PASS** |
| `EVAL-04-LOOKALIKE-APPLICATION-DESTINATION` | `ambiguous_unresolved` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 5 | 80% | **PASS** |
| `EVAL-05-PLAUSIBLE-EMPLOYER-IMPERSONATION` | `threat_cases` | `HIGH_RISK` | `HIGH_RISK` | YES | 7 | 80% | **PASS** |
| `EVAL-06-LEGITIMATE-CORROBORATED-PUBLIC-RECORDS` | `legitimate_corroborated` | `NO_STRONG_RISK_SIGNALS` | `NO_STRONG_RISK_SIGNALS` | YES | 3 | 67% | **PASS** |
| `EVAL-07-AUTHORIZED-RECRUITMENT-AGENCY` | `legitimate_corroborated` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 0 | 0% | **PASS** |
| `EVAL-08-SMALL-EMPLOYER-SPARSE-FOOTPRINT` | `ambiguous_unresolved` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 50% | **PASS** |
| `EVAL-09-NEGATED-PAYMENT-POLICY` | `benign_policy` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 2 | 50% | **PASS** |
| `EVAL-10-QUOTED-SCAM-WARNING` | `benign_policy` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 2 | 33% | **PASS** |
| `EVAL-11-CANDIDATE-RECRUITER-ROLE-SEPARATION` | `legitimate_corroborated` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 67% | **PASS** |
| `EVAL-12-VACANCY-MATCH-PRESERVES-UNCONFIRMED` | `legitimate_corroborated` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 67% | **PASS** |
| `EVAL-13-ROLE-SENIORITY-SPECIALIZATION-MISMATCH` | `ambiguous_unresolved` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 2 | 50% | **PASS** |
| `EVAL-14-CLOSED-EXPIRED-VACANCY` | `ambiguous_unresolved` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 3 | 33% | **PASS** |
| `EVAL-15-EXACT-REQUISITION-MATCH` | `legitimate_corroborated` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 3 | 33% | **PASS** |
| `EVAL-16-PRIVATE-OFFER-REFERENCE-LEAK-PREVENTION` | `ambiguous_unresolved` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 67% | **PASS** |
| `EVAL-17-ATS-TENANT-ASSOCIATION` | `legitimate_corroborated` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 2 | 50% | **PASS** |
| `EVAL-18-INDEPENDENT-CONFIRMATION-CONTACT` | `legitimate_corroborated` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 3 | 33% | **PASS** |
| `EVAL-19-SUBMITTED-CONTACT-DOES-NOT-BECOME-ROUTE` | `ambiguous_unresolved` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 67% | **PASS** |
| `EVAL-20-EMPTY-SUCCESSFUL-SEARCH` | `system_and_limits` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 67% | **PASS** |
| `EVAL-21-PROVIDER-FAILURE-RESILIENCE` | `system_and_limits` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 4 | 0% | **PASS** |
| `EVAL-22-SEARCH-BUDGET-EXHAUSTION` | `system_and_limits` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 1 | 25% | **PASS** |
| `EVAL-23-INVESTIGATION-DEADLINE-TIMEOUT` | `system_and_limits` | `CANNOT_VERIFY` | `CANNOT_VERIFY` | YES | 0 | 0% | **PASS** |
| `EVAL-24-STRONG-WARNING-SURVIVES-VACANCY-MATCH` | `threat_cases` | `HIGH_RISK` | `HIGH_RISK` | YES | 5 | 75% | **PASS** |

## Honest Limitations and Disclaimers

1. **Synthetic Corpus Scope:** These evaluation metrics are derived from a synthetic, offline regression corpus. They measure algorithmic correctness and adherence to safety policies; they do not represent real-world accuracy on arbitrary in-the-wild documents.
2. **Uncertainty is Not Legitimacy:** `CANNOT_VERIFY` outcomes reflect missing public records or provider limits. They are never counted as legitimate or verified.
3. **Offline Mock Latency:** The measured latency (9.2ms median) represents local pipeline execution over recorded mock responses. Production latency will be dominated by external network I/O.
