# Task 13: Evaluation & Demo Readiness Report

This document records the design, implementation, and measured results of **Task 13: Evaluation and Demo Readiness** for AsliOffer. It details the offline evaluation workflow, the 24-case evaluation corpus, safety and evidence invariants, honest metric definitions, measured results, and reproducible hackathon demo cases for Jay's frontend integration.

---

## 1. Overview & Scope

### Implemented State (Tasks 1–12)
- **Tasks 1–9**: Built core agents (`CompanyAgent`, `RecruiterAgent`, `SalaryAgent`, `ScamAgent`), risk assessment policy (`AssessmentEngine`), report presentation helpers, and wire contract (`contract.py`).
- **Task 10**: Unified investigation pipeline (`investigate_case`) executing claim extraction, multi-agent dispatch, recording search client, evidence adaptation, claim assessment, and UNCONFIRMED authenticity preservation.
- **Task 11**: Bounded adaptive investigation planner (`InvestigationPlanner`) and coroutine-safe budget controller (`BudgetManager`).
- **Task 12**: Job vacancy corroboration (`JobCorroborationService`), ATS tenant evaluation, and independently published confirmation routes (`ConfirmationRoute`). Validated with 575 backend tests passing.

### What Task 13 Adds
1. **Offline Evaluation Corpus (`backend/app/evaluation/data/`)**: A canonical suite of 24 deterministic, synthetic cases covering 21 distinct investigation requirements including payment demands, OTP credential theft, lookalike application portals, legitimate recruitment records, sparse footprints, expired vacancies, ATS tenants, budget exhaustion, and deadlines.
2. **Evaluation Runner CLI (`backend/app/evaluation/runner.py`)**: A cross-platform offline runner that executes `investigate_case()`, enforces referential/evidence/privacy invariants, computes honest metrics, and produces both machine-readable JSON (`evaluation_results.json`) and readable Markdown (`evaluation_summary.md`).
3. **Safety & Evidence Invariant Suite (`backend/app/evaluation/invariants.py`)**: 11 automated invariant checks verifying referential integrity, evidence claim ownership, status attribution, failed retrieval neutrality, demo isolation, search provenance, confirmation route provenance, authenticity restraint, threat precedence, secret non-leakage, and coverage bounds.
4. **Reproducible Hackathon Demo Suite (`backend/app/evaluation/demo_cases.py` & `docs/demo/`)**: 5 contract-v1 compliant demo scenarios with pre-generated JSON payloads, highlighting grounded scam warnings, impersonation overrides, legitimate confirmation guidance, sparse-footprint uncertainty, and provider outage failsafes.
5. **Optional Live Mode (`backend/app/evaluation/live.py`)**: Gated behind `--live`, reuses `SerpApiClient` with live budgets and credential scrubbing.

---

## 2. Commands & Setup

The evaluation workflow works from the repository root on both Windows and Linux without external network access or API keys.

### Running Offline Evaluation
```bash
# Run default offline evaluation across all 24 cases
python -m backend.app.evaluation.runner

# Alternative module entrypoint
python -m backend.app.evaluation

# Filter to run a single case
python -m backend.app.evaluation.runner --case EVAL-01

# Custom output directory
python -m backend.app.evaluation.runner --output-dir ./eval_reports
```

### Generating Hackathon Demo Outputs
```bash
# Execute pipeline on 5 hackathon demo cases and output contract-v1 JSON payloads
python -m backend.app.evaluation.runner --generate-demos
```
Generated payloads are saved to [docs/demo/](file:///c:/Users/dyara/aslioffer/docs/demo) and [backend/app/evaluation/demo_outputs/](file:///c:/Users/dyara/aslioffer/backend/app/evaluation/demo_outputs).

### Running Automated Test Suite
```bash
# Run Task 13 evaluation unit and invariant tests
python -m pytest backend/tests/investigation/test_task13_evaluation.py -v

# Run entire backend test suite (588 tests)
python -m pytest backend/tests/ -q
```

---

## 3. Evaluation Corpus Design

The offline corpus consists of 24 self-contained JSON cases stored in [backend/app/evaluation/data/](file:///c:/Users/dyara/aslioffer/backend/app/evaluation/data). Every case provides:
- Stable case ID and scenario title.
- Synthetic, redacted input text and optional confirmed claims.
- Isolated search mock responses (replayed as `source="REAL"` so live provider logic is exercised without external calls).
- Independently specified expected outcome and allowed outcomes.
- Required and forbidden behaviors.
- Scenario group labels for aggregated reporting.

### Scenario Coverage Matrix

| Case ID | Scenario Name | Scenario Group | Category | Expected Outcome |
|---|---|---|---|---|
| `EVAL-01` | Explicit Upfront Fee Demand | `threat_cases` | `upfront_fee_demand` | `HIGH_RISK` |
| `EVAL-02` | Bank OTP / Password Demand | `threat_cases` | `credential_otp_theft` | `HIGH_RISK` |
| `EVAL-03` | Task Scam Unlock Earnings Extortion | `threat_cases` | `payment_to_unlock_earnings` | `HIGH_RISK` |
| `EVAL-04` | Lookalike Application Destination | `ambiguous_unresolved` | `lookalike_domain` | `CANNOT_VERIFY` |
| `EVAL-05` | Plausible Employer Impersonation | `threat_cases` | `realistic_impersonation` | `HIGH_RISK` |
| `EVAL-06` | Legitimate Corroborated Records | `legitimate_corroborated` | `corroborated_recruitment` | `NO_STRONG_RISK_SIGNALS` |
| `EVAL-07` | Authorized Staffing Agency | `legitimate_corroborated` | `agency_recruitment` | `CANNOT_VERIFY` |
| `EVAL-08` | Small Employer Sparse Footprint | `ambiguous_unresolved` | `sparse_footprint_startup` | `CANNOT_VERIFY` |
| `EVAL-09` | Negated Payment Policy | `benign_policy` | `negated_fee_policy` | `CANNOT_VERIFY` |
| `EVAL-10` | Quoted Anti-Scam Advisory | `benign_policy` | `quoted_scam_warning` | `CANNOT_VERIFY` |
| `EVAL-11` | Candidate/Recruiter Separation | `legitimate_corroborated` | `contact_role_separation` | `CANNOT_VERIFY` |
| `EVAL-12` | Vacancy Corroboration Restraint | `legitimate_corroborated` | `vacancy_corroboration` | `CANNOT_VERIFY` |
| `EVAL-13` | Seniority/Specialization Mismatch | `ambiguous_unresolved` | `role_mismatch` | `CANNOT_VERIFY` |
| `EVAL-14` | Closed or Expired Vacancy | `ambiguous_unresolved` | `expired_vacancy` | `CANNOT_VERIFY` |
| `EVAL-15` | Exact Requisition Match | `legitimate_corroborated` | `requisition_match` | `CANNOT_VERIFY` |
| `EVAL-16` | Private Reference Protection | `ambiguous_unresolved` | `privacy_leak_prevention` | `CANNOT_VERIFY` |
| `EVAL-17` | Associated ATS Tenant Verification | `legitimate_corroborated` | `ats_tenant_association` | `CANNOT_VERIFY` |
| `EVAL-18` | Independent Confirmation Route | `legitimate_corroborated` | `confirmation_route` | `CANNOT_VERIFY` |
| `EVAL-19` | Submitted Contact Route Exclusion | `ambiguous_unresolved` | `route_safety` | `CANNOT_VERIFY` |
| `EVAL-20` | Empty Successful Search (HTTP 200) | `system_and_limits` | `empty_search_results` | `CANNOT_VERIFY` |
| `EVAL-21` | Provider Failure Resilience (HTTP 429) | `system_and_limits` | `provider_failure_or_rate_limit` | `CANNOT_VERIFY` |
| `EVAL-22` | Search Budget Exhaustion | `system_and_limits` | `budget_exhaustion` | `CANNOT_VERIFY` |
| `EVAL-23` | Deadline Monotonic Expiration | `system_and_limits` | `deadline_timeout` | `CANNOT_VERIFY` |
| `EVAL-24` | Strong Warning Survives Vacancy | `threat_cases` | `threat_precedence` | `HIGH_RISK` |

---

## 4. Honest Metric Definitions

Every metric reported by the evaluation runner has an explicit definition, numerator, and denominator:

1. **Outcome Agreement Rate (`outcome_agreement`)**:
   - *Formula:* `matching_cases / total_cases`
   - *Denominator:* Total completed cases evaluated (24).
   - *Meaning:* Fraction of cases where the pipeline's `overall_outcome` falls within the independently specified `allowed_outcomes`.
2. **False Positive Rate (`false_positive_rate`)**:
   - *Formula:* `legitimate_cases_marked_HIGH_RISK / total_legitimate_cases`
   - *Denominator:* Cases belonging to `legitimate_corroborated` or `benign_policy` groups (9).
   - *Requirement:* Strictly **0.0%**. Genuine employers or benign negative policies must never receive a `HIGH_RISK` fraud verdict.
3. **False Negative Rate (`false_negative_rate`)**:
   - *Formula:* `threat_cases_failing_HIGH_RISK / total_threat_cases`
   - *Denominator:* Cases belonging to `threat_cases` (advance fee, OTP theft, task extortion) (5).
   - *Requirement:* Strictly **0.0%**. Explicit payment and credential demands must produce immediate `HIGH_RISK` warnings.
4. **Uncertainty Retention Rate (`uncertainty_retention_rate`)**:
   - *Formula:* `actual_cannot_verify / expected_cannot_verify`
   - *Denominator:* Cases where `expected_outcome == "CANNOT_VERIFY"` (18).
   - *Meaning:* Measures honest restraint. Sparse footprints, empty searches, and provider outages must remain `CANNOT_VERIFY`, never fabricated into fraud or verified legitimacy.
5. **Invariant Pass Rate (`invariant_pass_rate`)**:
   - *Formula:* `cases_passing_all_11_invariants / total_cases`
   - *Denominator:* Total completed cases evaluated (24).
   - *Requirement:* Strictly **100.0%**. Zero invariant violations permitted.
6. **Coverage Completeness Ratio**:
   - *Formula:* Mean of `checked_claims / total_claims` across all cases.
   - *Meaning:* Quantifies pipeline investigation completeness. Never conflated with fraud probability.
7. **Tool Provider Calls per Case**:
   - *Formula:* Count of unique external queries executed (excluding cache hits) recorded in `tool_trace`. Reports min, mean, median, p95, and max.
8. **Offline Mock Pipeline Latency**:
   - *Formula:* Local wall-clock execution time (ms) per case. Reports min, mean, median, and p95.
   - *Disclaimer:* Reflects internal orchestration overhead over in-memory mock responses. Production latency will depend on external SerpApi HTTP round trips.

---

## 5. Actual Measured Results

The evaluation runner was executed from the repository root:
`python -m backend.app.evaluation.runner`

### Summary Metrics

| Metric | Denominator | Measured Value | Standard / Requirement | Status |
|---|---|---|---|---|
| **Outcome Agreement** | 24/24 | **100.0%** | $\ge 90\%$ | PASS |
| **False Positive Rate** | 0/9 | **0.0%** | $0.0\%$ | PASS |
| **False Negative Rate** | 0/5 | **0.0%** | $0.0\%$ | PASS |
| **Uncertainty Retention** | 18/18 | **100.0%** | $\ge 90\%$ | PASS |
| **Invariant Pass Rate** | 24/24 | **100.0%** | $100.0\%$ | PASS |
| **Coverage Completeness** | 24 cases | **49.7%** (min: 0%, max: 100%) | N/A | PASS |
| **Tool Provider Calls** | 24 cases | **Mean: 3.0** (Median: 3, p95: 5) | $\le 8$ (budget limit) | PASS |
| **Pipeline Latency (mock)** | 24 cases | **Median: 20.3ms** (p95: 53.7ms) | N/A | PASS |
| **Unhandled Exceptions** | 24 cases | **0** | 0 | PASS |

### Scenario Group Breakdown

| Scenario Group | Cases | Passed | Agreement | Invariant Pass | Avg Calls | Avg Latency |
|---|---|---|---|---|---|---|
| `threat_cases` | 5 | 5 | 100.0% | 100.0% | 3.8 | 85.2ms |
| `legitimate_corroborated` | 7 | 7 | 100.0% | 100.0% | 2.7 | 26.1ms |
| `ambiguous_unresolved` | 6 | 6 | 100.0% | 100.0% | 3.7 | 22.1ms |
| `benign_policy` | 2 | 2 | 100.0% | 100.0% | 2.0 | 13.4ms |
| `system_and_limits` | 4 | 4 | 100.0% | 100.0% | 2.2 | 21.1ms |

---

## 6. Safety & Evidence Invariants

The evaluation runner executes [backend/app/evaluation/invariants.py](file:///c:/Users/dyara/aslioffer/backend/app/evaluation/invariants.py) on every case to verify that the pipeline strictly conforms to contract v1 rules:

1. **Referential Integrity**: Every evidence ID cited in `assessed_claims` or `tool_trace` must resolve within `result.evidence`.
2. **Evidence Claim Ownership**: Evidence cited for claim $C_i$ must have `ev.claim_id == C_i`.
3. **Status Evidence Attribution**: Claims marked `SUPPORTED` must cite at least one `SUPPORTS` evidence item; claims marked `CONTRADICTED` must cite at least one `CONTRADICTS` evidence item.
4. **Failed Retrieval Neutrality**: Any evidence item with `retrieval_status == FAILED` must have `relation == CONTEXT`. A failed search can never support or contradict a claim.
5. **Demo Evidence Isolation**: In production runs (`demo_mode=False`), no evidence item may possess `retrieval_status == DEMO`.
6. **Search Provenance**: Every `SEARCH_SNIPPET` evidence record retains query string, engine name, retrieval timestamp, and original snippet.
7. **Confirmation Route Provenance**: If a `confirmation_route` is returned, its destination must appear in the cited evidence record's snippet or URL.
8. **Unconfirmed Authenticity Restraint**: `result.authenticity_status` must strictly equal `UNCONFIRMED` on all runs. Public search cannot authenticate individual offers.
9. **Threat Precedence**: When explicit advance-fee or credential-theft demands exist, `overall_outcome` must be `HIGH_RISK` even if a matching vacancy is corroborated.
10. **Privacy & Secret Protection**: Planted confidential tokens (e.g. `SECRET_TOKEN_77291B`) must never leak into search queries, tool reasons, confirmation message drafts, or recommended actions.
11. **Coverage Bounds**: `checked_claims` and `unresolved_claims` cannot exceed `total_claims`. Failed checks cannot inflate completed coverage.

---

## 7. Hackathon Demo Cases

To enable reproducible, high-credibility demonstrations during the hackathon, 5 contract-compatible JSON example outputs were generated from real pipeline execution and stored in [docs/demo/](file:///c:/Users/dyara/aslioffer/docs/demo):

### Demo 1: Grounded Advance Fee Scam Warning
- **File:** [docs/demo/demo_01_grounded_scam_warning.json](file:///c:/Users/dyara/aslioffer/docs/demo/demo_01_grounded_scam_warning.json)
- **Input:** Offer from Nimbus Infotech Ltd selected for Graduate Engineer Trainee, demanding an upfront refundable laptop security fee of INR 15,000 via UPI.
- **Search Setup:** Official company website found; search for fraud notices retrieves employer advisory stating Nimbus never charges security deposits.
- **Expected & Actual Result:** `HIGH_RISK`, `authenticity_status=UNCONFIRMED`.
- **Key Evidence to Highlight:** Active UPI payment demand cited in claim `c5` (`CONTRADICTED`); employer's public fraud alert citing no-fee policy.
- **What It Establishes:** Demonstrates grounded detection of advance-fee scams with exact document quotes and conflicting employer policy evidence.
- **What It Does NOT Establish:** Does not claim the real Nimbus Infotech Ltd is fraudulent; proves the specific communication is a scam.
- **Reproduction:** `python -m backend.app.evaluation.runner --case EVAL-01`

### Demo 2: Plausible Impersonation Despite Real Branding
- **File:** [docs/demo/demo_02_plausible_impersonation.json](file:///c:/Users/dyara/aslioffer/docs/demo/demo_02_plausible_impersonation.json)
- **Input:** Offer copying authentic office address and realistic salary (INR 4.8 LPA) from Infosys Limited, but recruiter email uses lookalike domain `recruitment@infosys-careers.example` and demands INR 6,500 document fee.
- **Search Setup:** Real corporate website and careers portal resolved; lookalike recruiter domain detected.
- **Expected & Actual Result:** `HIGH_RISK`, `authenticity_status=UNCONFIRMED`.
- **Key Evidence to Highlight:** Strong fee demand overrides high-profile company branding and realistic salary figures.
- **What It Establishes:** Shows that AsliOffer cannot be fooled by copied corporate addresses or plausible salaries.
- **What It Does NOT Establish:** Does not authenticate the communication even though corporate address exists.
- **Reproduction:** `python -m backend.app.evaluation.runner --case EVAL-05`

### Demo 3: Legitimate Recruitment with Confirmation Guidance
- **File:** [docs/demo/demo_03_legit_confirmation_guidance.json](file:///c:/Users/dyara/aslioffer/docs/demo/demo_03_legit_confirmation_guidance.json)
- **Input:** Offer from Kestrel Systems Pvt Ltd for Associate Consultant; recruiter `ananya.rao@kestrelsystems.example`; careers portal `https://careers.kestrelsystems.example/offers`.
- **Search Setup:** Official domain resolved, recruiter verified on employer team directory, active vacancy matched, clean fraud history.
- **Expected & Actual Result:** `NO_STRONG_RISK_SIGNALS`, `authenticity_status=UNCONFIRMED`.
- **Key Evidence to Highlight:** Populated `confirmation_route` with destination `https://careers.kestrelsystems.example/offers` citing official employer evidence; safe, non-accusatory confirmation draft message.
- **What It Establishes:** Public records corroborate employer identity and recruiter affiliation with no risk signals.
- **What It Does NOT Establish:** Emphasizes that clean public consistency CANNOT authenticate that this individual offer letter was genuinely issued without direct employer confirmation.
- **Reproduction:** `python -m backend.app.evaluation.runner --case EVAL-06`

### Demo 4: Sparse Footprint Startup (Honest Uncertainty)
- **File:** [docs/demo/demo_04_sparse_footprint_unverified.json](file:///c:/Users/dyara/aslioffer/docs/demo/demo_04_sparse_footprint_unverified.json)
- **Input:** Offer from Acme Pixel Labs (early-stage boutique studio) for Junior 3D Artist; contact `dev@acmepixellabs.example`.
- **Search Setup:** Search executes cleanly (HTTP 200) but yields zero public corporate listings or reviews.
- **Expected & Actual Result:** `CANNOT_VERIFY`, `authenticity_status=UNCONFIRMED`.
- **Key Evidence to Highlight:** Coverage shows unverified employer check; recommended actions advise candidate on how to request references safely without falsely branding the startup as a scam.
- **What It Establishes:** Demonstrates algorithmic restraint: missing evidence is preserved as uncertainty.
- **What It Does NOT Establish:** Does NOT brand the offer as fraudulent.
- **Reproduction:** `python -m backend.app.evaluation.runner --case EVAL-08`

### Demo 5: Search Provider Outage Failsafe
- **File:** [docs/demo/demo_05_provider_outage_failsafe.json](file:///c:/Users/dyara/aslioffer/docs/demo/demo_05_provider_outage_failsafe.json)
- **Input:** Offer from Vertex Dynamics Ltd for Database Administrator.
- **Search Setup:** Search provider returns HTTP 429 rate limit or network timeout.
- **Expected & Actual Result:** `CANNOT_VERIFY`, `authenticity_status=UNCONFIRMED`.
- **Key Evidence to Highlight:** Result contains structured `RunError` with `code="SEARCH_CHECK_UNAVAILABLE"` and `retryable=True`; local document scan observations are retained.
- **What It Establishes:** Demonstrates graceful degradation under upstream infrastructure failure without crashing or generating fake data.
- **What It Does NOT Establish:** Does not render a substantive verdict on the offer due to search unavailability.
- **Reproduction:** `python -m backend.app.evaluation.runner --case EVAL-21`

---

## 8. Limitations & Disclaimers

1. **Synthetic Corpus Scope**: The 24 offline evaluation cases are intentionally crafted synthetic scenarios designed to stress-test failure modes, boundary semantics, and security invariants. While they provide reproducible regression protection, they do not constitute a benchmark of real-world accuracy across arbitrary web documents.
2. **Uncertainty is Not Legitimacy**: `CANNOT_VERIFY` outcomes reflect missing public records or provider limits. They are never counted as legitimate or verified.
3. **Offline Mock Latency vs Live Latency**: The recorded offline median latency (20.3ms) measures local Python pipeline execution over in-memory replayed responses. Live production latency will be dominated by external SerpApi HTTP network round trips.
4. **Authenticity Guarantee**: In accordance with the project contract, AsliOffer never claims to confirm offer authenticity without authorized employer confirmation. Authenticity status remains strictly `UNCONFIRMED` across all runs.

---

## 9. Handoff Instructions for Jay (Frontend Integration)

Jay owns the frontend UI, run persistence, and polling routes.

### Reusable Demo Payloads
Pre-computed contract-v1 JSON payloads are ready for UI rendering and testing in:
- `docs/demo/demo_01_grounded_scam_warning.json`
- `docs/demo/demo_02_plausible_impersonation.json`
- `docs/demo/demo_03_legit_confirmation_guidance.json`
- `docs/demo/demo_04_sparse_footprint_unverified.json`
- `docs/demo/demo_05_provider_outage_failsafe.json`

### Key Contract Fields for UI Presentation
1. `overall_outcome`: One of `HIGH_RISK`, `NEEDS_REVIEW`, `CANNOT_VERIFY`, `NO_STRONG_RISK_SIGNALS`. Use corresponding theme color (red, amber, neutral slate, emerald).
2. `authenticity_status`: Always `UNCONFIRMED`. Render the standard badge: *"Authenticity: Unconfirmed by Employer"*.
3. `confirmation_route`: If non-null, display the **"How to Confirm This Offer"** action card with `channel`, `destination`, and `draft_message`.
4. `coverage`: Display `checked_claims` vs `total_claims` as completeness indicators. Show `unresolved_claims` and `failed_checks` in the inspection drawer.
5. `tool_trace`: Interactive timeline showing each agent's search query, rationale, duration, and status.

### Running Evaluation in CI / Pre-commit
Add this command to backend pre-commit or CI test scripts:
```bash
python -m backend.app.evaluation.runner
```
It returns exit code `0` on success and `1` on any invariant or acceptance failure.
