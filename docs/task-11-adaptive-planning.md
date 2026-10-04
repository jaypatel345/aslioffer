# Task 11: Bounded Adaptive Investigation Planning

## Overview

Task 11 adds a deterministic planner to the AsliOffer investigation pipeline. The planner:
1. Examines unresolved or conflicting findings after initial checks.
2. Selects a bounded number of prioritized follow-up searches.
3. Explains the exact information-gain rationale for each search.
4. Enforces a single shared budget and monotonic deadline across both initial and adaptive searches.
5. Stops conservatively when further queries are unneeded, unavailable, or unproductive.

No LLM, external hosted model, or database dependency is introduced. The public `investigate_case` signature remains backward-compatible while accepting an optional `budget` parameter.

---

## 1. Shared Run Budget & Accounting

All initial agent queries and adaptive follow-up queries draw from a single shared `InvestigationBudget` managed by `BudgetManager`.

### Budget Model Defaults & Validation
Configured via `InvestigationBudget`:
- `max_search_calls: int = 8` (Validated positive integer): Upper bound on unique search operations admitted to the search provider.
- `max_followup_calls: int = 3` (Validated non-negative integer): Upper bound on adaptive follow-up searches. Automatically clamped to `min(max_followup_calls, max_search_calls)`.
- `max_concurrent_calls: int = 3` (Validated positive integer): Maximum concurrent in-flight external provider calls (enforced by an `asyncio.Semaphore`).
- `deadline_seconds: float = 15.0` (Validated finite positive number): Monotonic deadline for external provider calls and concurrency waits.

### Search Operations vs. Physical HTTP Attempts
- **Search Operation (Budget Allowance):** One admitted call to the underlying search client (e.g. SerpApi). Exactly one allowance is reserved per admitted operation.
- **Physical HTTP Attempts:** `SerpApiClient` may execute multiple HTTP attempts (initial + bounded retries for 429/5xx). Physical retry loops live inside `SerpApiClient` and do not consume additional search operation allowances. Both bounds are enforced independently.

### Strict Accounting Rules
- **Cache Hits:** Exact identical requests served from the local cache consume 0 search-call allowance.
- **Concurrent In-Flight Queries:** Coalescing locks ensure that identical concurrent requests execute once and consume exactly 1 allowance.
- **Failed Provider Calls:** Failed external network calls consume their 1 reserved allowance upon execution.
- **Budget Denial:** Requests exceeding the budget are denied immediately before network dispatch. Denied requests make no network calls, consume 0 provider-call allowance, and return `SearchOutcome.RATE_LIMIT` with `budget_denied=True`. Denied calls are not cached permanently.
- **Atomic Reservation:** `BudgetManager.try_admit()` atomically checks capacity and reserves allowance under concurrency.

---

## 2. Enforcement Gate (`RecordingSearchClient`)

`RecordingSearchClient` wraps all search calls for both initial agents and adaptive follow-ups:
- Denied queries emit a `RunError` (`INVESTIGATION_BUDGET_EXCEEDED` or `INVESTIGATION_DEADLINE_EXCEEDED`).
- Claims affected by denied or unavailable searches remain `NOT_CHECKED` or `UNRESOLVED`.
- Denied calls add zero adverse risk points and record no fabricated tool calls.
- Task-local step contexts, provenance recording, secret redaction, and demo isolation are preserved.

---

## 3. Monotonic Deadline & Partial Result Preservation

Execution bounds use `time.monotonic()`:
- `BudgetManager.remaining_deadline()` bounds concurrency waits and provider calls. If time has expired, calls fail fast without network access.
- When the deadline expires, in-flight work is cancelled and awaited.
- Completed observations, claims, and local document scam detections (such as upfront fee or credential theft demands) are retained.
- The pipeline returns a valid partial `InvestigationResult` with explicit errors and gaps.
- Caller cancellation via `asyncio.CancelledError` is cleanly propagated and drains tasks. It is never conflated with timeout reports.

---

## 4. Deterministic Planner Strategies & Priorities

`InvestigationPlanner` evaluates extracted claims and initial agent findings to generate prioritized `PlanStep` records:

### Priority 1: Employer Contextual Search (`EMPLOYER_CONTEXT`)
- **Trigger:** Claimed employer corporate domain is unresolved after initial search (`official_domain_resolved=False`), provider is healthy, and grounded location or role context exists.
- **Query:** `"{company_name}" "{location_city}" official website` or `"{company_name}" "{role}" official careers`.
- **Information Gain:** Uses grounded geography/role to resolve canonical employer domain.
- **Stop Condition:** `DomainResolver` resolves official domain or query yields 0 candidate domains.
- **Safety:** Redaction placeholders or uncertain/ambiguous extractions never generate queries.

### Priority 2: Staffing Agency Representation & Authorization (`AGENCY_AUTHORIZATION`)
- **Trigger:** Recruiter email domain differs from resolved employer domain, is not a free webmail, and sender represents a recognized staffing agency.
- **Query:** `"{company_name}" "{agency_name}" recruitment partner authorized`.
- **Information Gain:** Verifies contractual partnership or representation mandate rather than falsely flagging corporate email mismatch as fraud.
- **Stop Condition:** Employer-published authorization page located or query yields no partnership evidence.
- **Assessment Effect:** Does not produce `HIGH_RISK`. Retains `NEEDS_REVIEW` for secondary human confirmation without false fraud accusation.

### Priority 3: Recruiter Affiliation Check (`RECRUITER_AFFILIATION`)
- **Trigger:** Usable recruiter name or sender contact is present with resolved employer domain, but public professional affiliation is unverified.
- **Query:** `"{recruiter_name}" "{canonical_domain}" talent acquisition recruiter`.
- **Information Gain:** Verifies employer-published affiliation.
- **Stop Condition:** Official listing found or zero matches returned.
- **Safety:** Self-described social profiles do not authenticate individual offer authority.

### Priority 4: Grounded Recruitment Fee Policy Check (`RECRUITMENT_FEE_POLICY`)
- **Trigger:** Upfront fee or security deposit was detected in the document, resolved employer domain is available, and budget permits.
- **Query:** `"{company_name}" recruitment fraud policy fee warning`.
- **Information Gain:** Slices official employer careers portal for explicit zero-fee advisories.
- **Stop Condition:** Official caution advisory found or no policy matches.
- **Safety:** Missing policy results never erase local high-risk document demands.

### Priority 5: Job Role Corroboration (`JOB_ROLE_CORROBORATION`) - Task 12
- **Trigger:** Grounded usable role claim, resolved canonical domain or ATS tenant, and job role corroboration check not yet executed.
- **Query:** Scoped search against employer careers sources (`site:{canonical_domain} "{role}"` or `"{company_name}" "{role}" job careers`).
- **Information Gain:** Verifies public vacancy existence and title/location alignment.

### Priority 5 (Tied): Job Reference Corroboration (`JOB_REFERENCE_CORROBORATION`) - Task 12
- **Trigger:** Grounded usable job reference passing `is_public_job_reference()` (rejects private candidate/offer codes), and check not yet executed.
- **Query:** `site:{canonical_domain} "{ref_val}"` or `"{company_name}" "{ref_val}" requisition`.
- **Information Gain:** Searches for exact public requisition ID matches.

### Priority 6: Offer Confirmation Route Discovery (`CONFIRMATION_ROUTE_DISCOVERY`) - Task 12
- **Trigger:** Grounded role or ref claim present, but no direct official recruitment email/phone yet corroborated.
- **Query:** `"{company_name}" recruitment verification contact site:{canonical_domain}` or `"{company_name}" official careers HR contact`.
- **Information Gain:** Discovers independent verification contact channels published by the employer.

---

## 5. Stop and Abstention Rules

Adaptive follow-ups stop or abstain when:
1. Inputs are missing, uncertain, or redacted.
2. The candidate query was already executed (case-insensitive deduplication).
3. Existing evidence already answers the question (e.g. domain already resolved).
4. Total run budget (`max_search_calls`) or follow-up budget (`max_followup_calls`) is reached.
5. External deadline (`deadline_seconds`) has expired.
6. Search provider authentication failure (`AUTH_FAILURE`) occurs, immediately suppressing futile follow-up queries.
7. A bounded follow-up yields no matching domains or records (prevents recursive query cascades).

---

## 6. Evidence Merging & Assessment

Follow-up results adhere to strict grounding rules:
- Sourced with genuine provenance (`SEARCH_SNIPPET`, actual query, engine, retrieved timestamp).
- Source tiers are deterministically assigned (`OFFICIAL_EMPLOYER` only for verified matching domains).
- Findings are merged deterministically; earlier observations and contradictions are preserved.
- Overall outcome is evaluated exclusively by `AssessmentEngine` structured policy. No second scoring engine is used.
- Additional snippets alone never authenticate an offer; `authenticity_status` remains strictly `UNCONFIRMED`.

---

## 7. Progress Events and Tool Tracing

`ToolCall` records document specific planner rationale:
- Example: `"Employer identity remains unresolved; checking 'Radiant Energy Solutions Ltd' with grounded context 'Hyderabad'."`
- Example: `"Sender domain differs from the employer; checking supported agency representation for 'Apex Staffing Solutions'."`
- Adaptive planning stages emit `RunEvent` updates: `STARTED`, `COMPLETED`, `SKIPPED`, or `FAILED`.
- Events and tool traces contain zero unredacted personal secrets or candidate contact details.

---

## 8. Handoff & Fixtures

Two reproducible Task 11 handoff fixtures are committed in `backend/tests/fixtures/investigation/generated_task11/`:
1. `fixture_adaptive_gap_resolved.json`: Initial sparse employer resolution is resolved by contextual adaptive search, leading to `NO_STRONG_RISK_SIGNALS` with `UNCONFIRMED` authenticity.
2. `fixture_adaptive_abstains_exhausted.json`: Sparse startup footprint with zero matching results leads to clean bounded abstention with `CANNOT_VERIFY`.

Both fixtures validate against `InvestigationResult` schema and round-trip through JSON.

---

## 9. Remaining Limitations (Scope Exclusions)

- Active confirmation routing, deep careers application API corroboration, and applicant corroboration belong to Task 12.
- Jay owns database persistence (J3), HTTP route integration, polling, and frontend migration.

## Cleanup semantics

Concurrency waits are bounded by the remaining deadline. Admission is reserved only after a slot is acquired, immediately before dispatch; cancelled or expired waiters create no provider call or failed-retrieval observation. Booleans, fractional call limits and non-finite deadlines are rejected. Cached observations remain readable without another admission. Denial metadata is checked before canonical SearchResult normalization can discard internal fields; denied adaptive steps are SKIPPED and stop the queue. Public failures use fixed messages rather than raw provider errors.

Recruiter and scam checks complete before optional compensation begins, so optional salary calls do not race essential initial checks for the last available allowance. Employer context resolution replans subsequent strategies against new evidence without replaying attempted queries. Supported dimension updates retain earlier observations, adverse findings and unresolved dimensions; domain alignment alone never upgrades recruiter identity to VERIFIED. Actual employer-published affiliation can be assessed separately. Agency metadata reads the existing nested raw_facts/status fields. Uncertain contacts/names and ungrounded payment values do not trigger follow-ups. A generic advisory is not labelled an explicit no-fee policy.

The gap-resolved fixture demonstrates resolution of employer identity while recruiter affiliation remains unresolved; its conservative overall outcome is CANNOT_VERIFY. Normal tests generate fixtures in temporary directories. Committed examples are regenerated explicitly. Final local assembly and awaited event callbacks remain outside an externally enforced wall-clock guarantee: elapsed time spent in them can exhaust the remaining external deadline, but they are not forcibly interrupted by that deadline.
