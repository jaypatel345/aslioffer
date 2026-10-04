# Task 13: evaluation and demo readiness

## Scope and commands

Task 13 evaluates the existing `investigate_case()` pipeline. It changes evaluation code, synthetic test data, demo artifacts and documentation; it does not change the investigation implementation, frontend, routes, persistence or contract-v1 schema.

From the repository root, on Windows or Linux:

```bash
python -m backend.app.evaluation.runner
python -m backend.app.evaluation
python -m backend.app.evaluation.runner --case EVAL-12
python -m backend.app.evaluation.runner --generate-demos --output-dir evaluation_artifacts
python -m pytest backend/tests/ -q
```

The default output directory is ignored `evaluation_artifacts/`, not a tracked source directory. `--output-dir` controls both reports and generated demos (`<output-dir>/demos/`). Ordinary evaluation does not overwrite committed samples. Missing, empty, malformed, duplicate-ID or invalid-schema corpora fail rather than being silently skipped or regenerated. `--corpus-dir` selects a different corpus without modifying it.

Offline evaluation needs no API key. It uses isolated search clients and blocks socket connections and DNS during case execution. Synthetic successful responses retain `source="REAL"` to exercise the production retrieval path; report metadata and demo manifests explicitly identify offline simulation. DEMO responses are not relabeled as live evidence.

## Executable corpus

The single source of truth is [backend/app/evaluation/data](../backend/app/evaluation/data). `get_default_corpus_cases()` reads this same corpus; there is no second Python copy that can drift from JSON.

Version 1.1.0 contains 27 cases. The original 24 cover fee/credential demands, impersonation, legitimate recruitment, agency representation, sparse employers, contextual warnings, extraction/contact separation, vacancy and location corroboration, seniority, expired postings, public/private references, ATS association, contact discovery, empty results, provider failures, budget limits, deadlines and warning precedence. Three new cases explicitly test partial requisition matches, unestablished ATS tenants and negative contact instructions.

Every case specifies expected/allowed outcomes before execution. Fine-grained expectations require claim statuses, claim values, published evidence, completed queries/steps, internal agency dimension statuses, routes or structured errors as relevant. Unknown behaviors and expectation keys fail. Getting `CANNOT_VERIFY` alone cannot demonstrate a matching vacancy or ATS association.

Some verification cases deliberately supply reviewed claims through the existing confirmation contract. They are labeled `input_mode=reviewed_claims` and test verification after candidate review, not raw extraction accuracy. `USER_EDITED` is used because these reviewed values may differ from the extractor's proposal. Other cases retain raw extraction, including candidate/recruiter separation. Existing Task 7 tests remain the extraction regression suite.

Important repaired cases:

| Case | Required behavior |
|---|---|
| EVAL-01 | Payment demand `SUPPORTED`: the demand exists, without legitimizing it |
| EVAL-06 | Employer, recruiter and role `SUPPORTED`; observed careers route |
| EVAL-07 | Employer supported, agency discovery executed, agency identity and authorization dimensions `SUPPORTED` |
| EVAL-11 | Correct recruiter email; candidate email never searched |
| EVAL-12 | Matching role and vacancy location `SUPPORTED` |
| EVAL-13/14 | Completed role query; incompatible/expired vacancy remains `UNRESOLVED` |
| EVAL-15 | Exact public `REQ-9942` requisition `SUPPORTED` |
| EVAL-16 | Private reference `NOT_CHECKED`, absent from external queries and public guidance |
| EVAL-17 | Observed application URL `SUPPORTED` through employer-published ATS association |
| EVAL-18/19 | Exact published email route versus no submitted-only route |
| EVAL-21/22/23 | Actual unavailable/budget/deadline errors and independently bounded completed coverage |
| EVAL-24 | Role supported while a grounded payment demand preserves `HIGH_RISK` |
| EVAL-25/26/27 | Partial IDs, tenant spelling and negative email guidance cannot establish support/routes |

The deadline case deliberately delays the mock provider beyond a bounded deadline. It does not depend on a machine coincidentally exceeding a one-millisecond deadline.

## Acceptance and diagnostics

Every required case must pass. Any outcome mismatch, explicit claim mismatch, unmet required behavior, observed forbidden behavior, expectation failure, invariant violation or exception produces exit code 1. The JSON `case_passed`, Markdown status, per-case results, scenario-group passed counts and CLI exit code use the same criteria. Case setup exceptions are recorded and subsequent cases continue. Diagnostics explain failures without echoing planted secrets.

The runner retains aggregate outcome statistics but does not use a 90% outcome threshold to excuse a failed required case. Live failure, skipped credentials and failed demo generation also return a nonzero status.

## Metrics and measured offline results

These results were generated from actual pipeline execution on base commit `f220802` plus the Task 13 cleanup. Saved metadata includes the base SHA, dirty-worktree state, corpus version/hash, evaluation-code hash, runtime and execution time. Re-run after committing to record the new clean SHA.

| Metric | Definition | Measured result |
|---|---|---|
| Outcome agreement | Actual outcome in each case's predefined allowed set / all attempted cases | 27/27 (100%) |
| False-positive rate | HIGH_RISK cases in predefined legitimate/benign groups / those groups | 0/9 (0%) |
| False-negative rate | Threat-group cases failing HIGH_RISK / threat-group cases | 0/5 (0%) |
| Uncertainty retention | CANNOT_VERIFY within the expected-CANNOT_VERIFY subset / that subset | 20/21 (95.2%) |
| Claim agreement | Matching explicit claim-status expectations / all specified expectations | 21/21 (100%) |
| Invariant pass rate | Cases satisfying every applicable invariant / all attempted cases | 27/27 (100%) |
| Completed coverage | Mean checked claims / returned claims per case | 59.1%, range 0–100% |
| Recorded provider invocations | Actual tool-trace entries, including failed attempts, excluding cache hits | 107 total; mean 3.96; median 4; p95 7.7; max 8 |
| Offline pipeline latency | Local wall-clock time over synthetic replay, including intentional timeout | Median 6.6 ms; p95 14.4 ms in the saved run |
| Exceptional case failures | Cases throwing unexpected exceptions | 0 |

The agency case produces allowed `NEEDS_REVIEW`, rather than CANNOT_VERIFY: the staffing mandate is supported but individual recruiter affiliation remains unconfirmed. This is why uncertainty retention is 20/21; the number is not rounded into a perfect score.

CANNOT_VERIFY is not counted as proof of legitimacy or fraud. Empty metric denominators display N/A. Exceptions remain in aggregate denominators rather than disappearing. Provider call counts describe calls admitted through the pipeline recorder, not every low-level HTTP retry inside a provider adapter. Failed-check count is separate from completed coverage.

The saved machine-readable and Markdown reports are in [backend/app/evaluation/output](../backend/app/evaluation/output). Timing varies by runtime and machine. These are synthetic regression results, not real-world accuracy, and mock latency is not production latency.

## Evidence, privacy and coverage checks

The runner validates:

- Evidence IDs exist and cited evidence belongs to the assessed claim.
- SUPPORTED/CONTRADICTED statuses cite the corresponding evidence relation.
- Failed retrievals remain neutral; production results contain no DEMO evidence.
- Search provenance fields exist. In offline execution, source URL, query, engine, original title and sanitized original snippet must match an observation actually returned by that case's mock client. Nonempty invented text is insufficient.
- Confirmation evidence publishes the exact destination. Employer domain alone cannot prove an email mailbox exists. Email/phone guidance must have relevant purpose, official source tier and no negative contact instruction; portal destinations require the actual observed URL/publication. Failed/production-demo evidence is rejected.
- Public-record checks keep authenticity UNCONFIRMED, and grounded threats retain HIGH_RISK.
- Planted secrets/private references do not appear in searches, tool reasons, drafts, guidance, public evidence, errors or assessment explanations. Diagnostics do not repeat the secret. Input claim values are candidate-provided data, not an external verification channel.
- Coverage respects bounds and an independently evidenced execution ceiling based on completed relevant tool calls, attributable evidence and local document observations. Scenario-specific limits additionally test failed providers, denied calls and deadlines. This is an execution ceiling, not a claim that every internal count can be reconstructed perfectly from the public contract.

## Demo reproduction and Jay's handoff

Generate the five synthetic demos:

```bash
python -m backend.app.evaluation.runner --generate-demos --output-dir evaluation_artifacts
```

Each JSON file is a bare contract-v1 `InvestigationResult` for Jay to render. The accompanying `demo_manifest.json` identifies simulation mode, expected/actual outcomes and highlights. Generation enforces case requirements and invariants before exporting a passing result. Demos reuse the same executable corpus rather than a separate response set.

| Demo file | Corpus case | Expected result | Highlight |
|---|---|---|---|
| demo_01_grounded_scam_warning.json | EVAL-01 | HIGH_RISK | Grounded fee demand with claim-specific document evidence |
| demo_02_plausible_impersonation.json | EVAL-05 | HIGH_RISK | Payment warning survives plausible corporate branding |
| demo_03_legit_confirmation_guidance.json | EVAL-06 | NO_STRONG_RISK_SIGNALS | Employer/recruiter/role consistency and observed careers route |
| demo_04_sparse_footprint_unverified.json | EVAL-08 | CANNOT_VERIFY | Missing evidence does not accuse a small employer |
| demo_05_provider_outage_failsafe.json | EVAL-21 | CANNOT_VERIFY | Retryable structured errors; no completed external coverage |

Committed frontend samples are available in [docs/demo](demo) and [backend/app/evaluation/demo_outputs](../backend/app/evaluation/demo_outputs). Normal execution writes new outputs outside those tracked directories. There is no `--demo` CLI option; use `--generate-demos` or `--case EVAL-XX`.

Jay should display `overall_outcome`, always-UNCONFIRMED authenticity, claim-specific citations, completed coverage and the actual confirmation destination. The legitimate demo's route is the retrieved careers root; it is not an invented offers API. Drafts remain review-only. HIGH_RISK indicates strong risk signals; these synthetic runs neither prove a real employer fraudulent nor authenticate a specific offer.

## Optional live mode

```bash
python -m backend.app.evaluation.runner --live --output-dir evaluation_artifacts/live
```

Live mode requires an explicit flag and valid configured SerpApi credentials. It uses synthetic inputs about public employers, the existing shared per-case call/deadline budgets and separate `live_evaluation_results.json`. Missing credentials, exceptions, failed invariants and disallowed outcomes do not exit successfully. Credentials are redacted from persisted errors/results. Live mode was not executed during this cleanup and is never part of default tests.

## Validation and limitations

Validation on the cleanup: **616 backend tests passed**, including 26 added cleanup tests. Run all backend tests and the offline evaluation before submission. The cleanup tests cover strict claim/behavior acceptance, malformed corpora, exact mailbox provenance, original snippet binding, secret-safe diagnostics, failed-check coverage, agency authorization, exceptions, blocked networking, full-corpus repeatability, deterministic deadlines and output-directory behavior.

Passing this corpus establishes regression behavior on these specified synthetic scenarios. It does not establish general document extraction accuracy, production latency, real employer ownership or individual offer issuance. Jay's frontend integration and deployed end-to-end verification remain separate work.
