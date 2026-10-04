# Task 10: Unified investigator and contract-v1 handoff

## Entry point and ownership

`backend/app/services/investigation/pipeline.py` exports:

```python
async def investigate_case(case_input: CaseInput, search_client=None, emit_event=None) -> InvestigationResult:
    ...
```

Only contract version 1.0.0 is supported. This service has no database or HTTP dependencies. Existing routes remain legacy until Jay's J3 integration. Jay owns shared schema/TypeScript changes, run persistence, snapshots, polling and frontend migration. Tool failures return partial results; unexpected extraction/assembly errors propagate to the run service. No automatic demo fallback exists.

## Execution and search recording

1. Extract claims locally from supplied redacted text and apply user decisions.
2. Resolve company footprint once when a usable employer is available.
3. Run recruiter, salary and scam checks concurrently, retaining isolated failures.
4. Apply the existing AssessmentEngine policy, adapt evidence and assess claims.
5. Return contract-v1 evidence, coverage, recommendations, tool trace and errors.

RecordingSearchClient accepts an injected async `search(query, engine='google', num=5, **kwargs)` client. Responses may be SearchResult or supported legacy dictionaries. Task-local context prevents concurrent searches from borrowing each other's step/reason. Per-query locks coalesce identical concurrent requests. Cache keys include exact query, engine, result count and options; defensive copies prevent agent mutation of shared responses. The trace records actual provider calls rather than claiming cache hits made another network request.

Missing employer input does not trigger an `Unknown Company` search. Local scam detection still runs, while external company/scam checks are skipped. Redaction placeholders and empty employer queries never reach the provider. Failed and synthetic production responses are stripped of usable results. Exceptions expose fixed messages rather than raw credentials or transport payloads.

Per-search deadlines and retries remain in SerpApiClient. Task 11 adds a shared query budget (InvestigationBudget), monotonic deadline enforcement, and bounded deterministic adaptive investigation planning (see docs/task-11-adaptive-planning.md).

## Claims and confirmations

Stable kind slots are: c1 employer; c2 sender_email; c3 contact_phone; c4 recruiter_name; c5 application_url; c6 role; c7 location; c8 job_reference; c9 compensation; c10 payment_request; c11 credential_request. Optional omissions leave gaps in IDs rather than shifting subsequent IDs.

Confirmations use those IDs. Duplicate IDs, multiple confirmations for one kind and mismatched kind IDs are rejected. USER_CONFIRMED cannot silently replace an existing extracted value; changed values use USER_EDITED, which clears document quotes and offsets. User decisions do not authenticate a claim.

Only recruiter/sender semantic contacts feed recruiter checks. Extraction uncertainty remains uncertainty and cannot silently become a search input. Quotes must exist in the supplied buffer; offsets are retained only when they slice that exact buffer. Secret sanitation can make an observation uncertain; offsets from a modified buffer are not passed off as original-buffer coordinates. The service never retrieves raw persistence content or reverses caller redaction. Redacted contacts remain uncheckable unless a usable confirmed value is supplied.

## Evidence and claim assessment

- External evidence requires matching recorded retrieval provenance. There is no invented query, retrieval time, snippet or LIVE status when provenance is missing.
- Actual organic snippets and knowledge-graph observations are SEARCH_SNIPPET, not CHECKED_PAGE. Quotes preserve retrieved content rather than agent-generated explanation.
- One observation may produce separate records for distinct relevant claims. Exact per-claim observations are deduplicated; unrelated contacts do not share citations.
- Unknown hosts stay UNKNOWN. A parent domain of a resolved subdomain is not automatically the official employer. Explicit www normalization permits matched employer subdomains.
- Failed retrievals are CONTEXT only, with actual query/time/engine and no URL. DEMO is never relabelled LIVE.
- Employer footprint support does not authenticate an offer. Recruiter support requires attributable employer-published affiliation evidence; mentions of words such as scam or matches do not independently establish a relation.
- Grounded document demands use DOCUMENT/OFFER_DOCUMENT, null URLs and SUPPORTS for the presence of the demand. This does not support legitimacy. Generic external warnings are not invented employer no-fee policies.
- Role, location, reference and application corroboration remain NOT_CHECKED until targeted checks exist. Empty search results do not prove falsehood.
- Salary snippets/fixed bands are context, not comparable pay evidence. A legacy VERIFIED salary finding is conservatively adapted to CANNOT_VERIFY in this pipeline; shared agent and assessment algorithms are unchanged.
- Every returned claim receives one assessment. UNCONFIRMED authenticity remains mandatory.

## Coverage

Contract Coverage counts claims, not Task 8 checks:

- total_claims: number of returned claims.
- checked_claims: claims whose relevant check actually executed successfully; completed empty checks can count. Local demand scans count independently of external availability. Partial recruiter execution is checked at the relevant contact dimension.
- unresolved_claims: UNRESOLVED plus NOT_CHECKED claims, including missing inputs. This may overlap checked_claims when an executed check remained unresolved.
- failed_checks: actual failed provider calls plus isolated agent failures. The public error summarizing a failed retrieval does not count it again.

Missing values and deferred corroboration do not inflate checked coverage. Coverage is never an authenticity or fraud probability.

## Events, failure and cancellation

STARTED/COMPLETED/SKIPPED/FAILED events describe actual stages with increasing sequences. Concurrent checks emit their terminal event when they finish, rather than waiting for slower siblings. Unavailable/partial checks emit FAILED while retaining usable local or partial results.

Callbacks may return coroutines, Futures or other awaitables. Ordinary callback errors are isolated and logged without raw exception payloads. Cancellation propagates; downstream tasks are cancelled and awaited before the investigator exits. No timed progress simulation exists.

## Confirmation route and handoff

An existing resolved careers URL is returned only when a retrieved official-employer observation cites that exact normalized destination. A generic homepage or hostname substring is not enough. Otherwise confirmation_route is null. Full job/confirmation discovery belongs to Task 12.

Jay's run service calls investigate_case, persists its InvestigationResult and receives RunEvents through the callback. It owns RunSnapshot status/version rules, refresh deduplication and GET-only snapshot reads. The investigator does not write Offer status, rerun HTTP endpoints or upgrade claims in a formatter.

Generated fixtures live in backend/tests/fixtures/investigation/generated_task10. They are actual pipeline outputs for positive public consistency, an adverse demand, sparse employer and provider outage. The fixture-generation test verifies their intended outcomes and writes fresh output only to pytest temporary directories; normal tests do not rewrite committed examples.

Validation: `python -m pytest backend/tests/ -q`. Cleanup regressions are in tests/investigation/test_task10_cleanup.py. No new dependencies, database migrations, contract fields or frontend changes are required.
