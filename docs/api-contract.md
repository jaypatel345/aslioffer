# AsliOffer API contract

**Contract version:** `1.0.0` (v1) · **Owner:** Jay · **Semantics reviewer:** Shriraj · **Status:** draft until Shriraj's one-time semantics review, then frozen

This is the single wire format shared by the investigator (`investigate_case`), the API/run service and the frontend. It implements task **J1** in [AsliOffer-Competitive-Review.md](../AsliOffer-Competitive-Review.md).

| Where | What |
|---|---|
| `backend/app/schemas/contract.py` | Pydantic models — the source of truth. Rules below are enforced by validators, not only documented. |
| `frontend/src/types/index.ts` | TypeScript mirror (bottom section, "API contract v1"). |
| `docs/contract/v1/examples/*.json` | Canonical example payloads. Every file must parse in both languages. |
| `backend/tests/integration/test_contract_v1.py` | Parses every example and checks each enforced rule. |

All companies, people, domains (`*.example`) and search IDs in the examples are **synthetic**.

## Change rules

1. No unannounced renames. Any change needs: a version bump in `CONTRACT_VERSION` (Python and TS), an entry in the change log below, and an updated or new example payload.
2. Models reject unknown fields (`extra="forbid"`). An ad-hoc field fails loudly instead of drifting silently.
3. Shriraj sends model requirements with an example; Jay makes the schema edit. Nobody else edits `backend/app/schemas/**`.
4. Additive optional fields are a minor bump (`1.x.0`). Renames, removals, or a change in meaning are a major bump (`2.0.0`) and need a short sync.

## Semantics that never change

- **No fraud probability.** There is no `fraud_probability` field, and coverage is not a probability. The UI must not show percentages derived from heuristics.
- **Authenticity stays `UNCONFIRMED`.** Only the employer can confirm an offer, so v1 has no other value. The best positive outcome is `NO_STRONG_RISK_SIGNALS`.
- **Missing evidence is not adverse evidence.** A sparse footprint, empty search or provider outage leads to `UNRESOLVED` claims and `CANNOT_VERIFY`, unless an independent risk signal exists.
- **A failed retrieval is never evidence.** `retrieval_status: FAILED` can only use `relation: CONTEXT`.
- **Demo data is labelled.** `DEMO` evidence is only valid when `demo_mode: true`. Network or provider failures never switch a run into demo mode.
- **Citations must resolve.** Every `evidence_ids` entry (in assessments, tool trace and confirmation route) must exist in the same run and belong to the same claim.
- **The report layer cannot upgrade.** `ReportGenerator` formats `InvestigationResult`; it cannot change a claim's status or re-run checks.

## Objects

### CaseInput — run service → `investigate_case`

| Field | Type | Notes |
|---|---|---|
| `contract_version` | string | `"1.0.0"` |
| `case_id` | int | Offer ID |
| `run_id` | string | Unique per run |
| `source_type` | `pdf` \| `screenshot` \| `email` \| `text` | |
| `redacted_text` | string | The only document text that may reach search or hosted models. Identifiers are replaced by placeholders such as `[EMAIL_1]`. |
| `confirmed_claims` | ConfirmedClaim[] | User decisions from the extraction screen. `extraction_status` is `USER_CONFIRMED` or `USER_EDITED` only. |
| `demo_mode` | bool | Set only when the user explicitly starts a sample |

### Claim

| Field | Type | Notes |
|---|---|---|
| `claim_id` | string | Unique within the run (`c1`, `c2`, …) |
| `kind` | enum | `employer`, `sender_email`, `contact_phone`, `recruiter_name`, `role`, `location`, `job_reference`, `application_url`, `compensation`, `payment_request`, `credential_request` |
| `value` | string \| null | Null only when `MISSING` |
| `source_quote` | string \| null | Exact document span. Required when `EXTRACTED`. |
| `start_offset`, `end_offset` | int \| null | Character offsets into the document text. Both or neither. |
| `page` | int \| null | 1-based, for PDFs where known |
| `extraction_status` | enum | `EXTRACTED`, `UNCERTAIN` (UI asks the user), `USER_CONFIRMED`, `USER_EDITED`, `MISSING` |

### EvidenceRecord

| Field | Type | Notes |
|---|---|---|
| `evidence_id` | string | Unique within the run |
| `claim_id` | string | The claim this record is about. Use one record per claim, even when the source is the same. |
| `source_kind` | `DOCUMENT` \| `SEARCH_SNIPPET` \| `CHECKED_PAGE` | A snippet is labelled as a snippet unless the page itself was fetched |
| `source_url` | string \| null | Null for `DOCUMENT` observations and failed retrievals. Never a generic homepage used as filler. Never contains `api_key=`. |
| `title`, `quote_or_snippet` | string | |
| `retrieved_at` | ISO-8601 datetime | |
| `query`, `engine`, `search_id` | string \| null | `query` and `engine` are required for `SEARCH_SNIPPET` |
| `retrieval_status` | `LIVE` \| `CACHED` \| `DEMO` \| `FAILED` | |
| `source_tier` | enum | `OFFICIAL_EMPLOYER`, `GOVERNMENT`, `ESTABLISHED_THIRD_PARTY`, `USER_GENERATED`, `OFFER_DOCUMENT` (required for `DOCUMENT`), `UNKNOWN` |
| `relation` | `SUPPORTS` \| `CONTRADICTS` \| `CONTEXT` | |

### AssessedClaim

| Field | Type | Notes |
|---|---|---|
| `claim_id` | string | Each claim is assessed at most once |
| `status` | `SUPPORTED` \| `CONTRADICTED` \| `UNRESOLVED` \| `NOT_CHECKED` | `SUPPORTED` needs at least one `SUPPORTS` record; `CONTRADICTED` needs at least one `CONTRADICTS` record |
| `explanation` | string | Plain language. States what the evidence does and does not show. |
| `evidence_ids` | string[] | Must resolve to evidence for the same claim |
| `reason_codes` | string[] | Machine-readable, e.g. `SENDER_DOMAIN_MISMATCH` |

### Coverage — completeness, not risk

`checked_claims`, `total_claims` (must equal the number of claims), `unresolved_claims`, `failed_checks`. All are non-negative integers.

### InvestigationResult — `investigate_case` → run service

| Field | Type | Notes |
|---|---|---|
| `contract_version`, `run_id`, `demo_mode` | | |
| `claims` | Claim[] | Everything extracted, including `MISSING` |
| `assessed_claims` | AssessedClaim[] | |
| `evidence` | EvidenceRecord[] | |
| `overall_outcome` | `HIGH_RISK` \| `NEEDS_REVIEW` \| `CANNOT_VERIFY` \| `NO_STRONG_RISK_SIGNALS` | Same enum as `risk/assessment_models.OverallOutcome` |
| `authenticity_status` | `UNCONFIRMED` | |
| `coverage` | Coverage | |
| `recommended_actions` | string[] | |
| `confirmation_route` | ConfirmationRoute \| null | `channel`, `destination`, `evidence_id` (must exist), optional `draft_message`. The destination comes from employer-published evidence, never from the letter. |
| `tool_trace` | ToolCall[] | `step`, `tool`, `query`, `reason` (why the planner chose it), `status`, `started_at`, `duration_ms`, `evidence_ids` |
| `errors` | RunError[] | `code`, `message`, `step`, `retryable`. Tool failures go here; the run still returns partial evidence. |

### RunEvent

`run_id`, `sequence` (strictly increasing within a run), `step`, `status` (`STARTED`, `COMPLETED`, `SKIPPED`, `FAILED`), `public_message`, `timestamp`. Messages are shown to the user. They never contain keys and contain no more personal detail than necessary.

### RunSnapshot

| Field | Notes |
|---|---|
| `run_id`, `case_id`, `contract_version` | |
| `version`, `previous_run_id` | `force_refresh=true` creates version n+1 and keeps version n. This lets the UI tell the latest finished report apart from a refresh that is still running. |
| `status` | `QUEUED`, `RUNNING` (no `report`), `COMPLETED` / `PARTIAL` (`report` required), `FAILED` (`errors` required) |
| `created_at`, `started_at`, `finished_at` | `finished_at` is required once the run has finished |
| `events` | RunEvent[], in sequence order |
| `report` | InvestigationResult \| null. `report.run_id` must equal `run_id`. |
| `errors` | RunError[] |

### ErrorResponse

Every non-2xx response has the body `{"detail": "<human-readable reason>"}` (FastAPI's standard shape). See `examples/error_404.json`.

## Backend function handoff

```python
# backend/app/services/investigation/pipeline.py   (Shriraj)
async def investigate_case(
    case_input: CaseInput,
    search_client=None,          # injected for fixtures
    emit_event=None,             # async callable(RunEvent) supplied by the run service; cannot change the verdict
) -> InvestigationResult: ...
```

Shriraj catches tool-level failures and records them in `errors`. Jay's run service catches unexpected top-level exceptions and marks the run `FAILED`.

## HTTP endpoints

All routes are served at the root and also under `/api/v1`.

### Case access (J6)

`POST /offers/upload` returns `access_token` once (only its SHA-256 hash is stored). Every case-scoped route below needs it in the `X-Case-Token` header. A missing or wrong token gets the **same 404** as an unknown ID, so neither the existence of a case nor another person's case is revealed. The frontend keeps tokens in the uploading browser's `localStorage`.

### Routes (after J3)

| Method & path | Success | Errors | Notes |
|---|---|---|---|
| `GET /health` | 200 | | |
| `POST /offers/upload` (multipart: `title`, `source_type`, `raw_content` or `file`, `sample`) | 201 `OfferUploadResponse` (`offer_id`, `access_token`, `expires_at`, …) | 400 no content · 413 too large · 415 file type · 422 unreadable file | Files: PDF, PNG, JPG, WEBP up to `MAX_UPLOAD_BYTES` (5 MB). Text up to `MAX_TEXT_CHARS` (20,000). No search runs. |
| `GET /offers/{id}` | 200 `OfferRead` | 404 | |
| `GET /offers/{id}/claims` | 200 `ClaimPreview` (`case_id`, `text`, `claims: Claim[]`) | 404 | Local and deterministic: the claim builder runs on the redacted text, with no search or hosted-model call. `text` is the redacted text that offsets refer to. |
| `POST /analysis/run` (`RunRequest`: `offer_id`, `force_refresh`, `confirmed_claims`) | **202** `RunSnapshot` (new run queued) · **200** `RunSnapshot` (existing run reused) | 404 · 422 invalid confirmation | See run rules below. |
| `GET /analysis/runs/{run_id}` | 200 `RunSnapshot` | 404 | Poll this every 1–2 s while `QUEUED`/`RUNNING`. Events are the ones the investigator emitted. |
| `GET /offers/{id}/report` | 200 latest `RunSnapshot` with a report (`COMPLETED` or `PARTIAL`) | 404 · **409** case exists but has no report | Reads only. Never starts extraction or search. |
| `GET /offers/{id}/runs` | 200 `RunSnapshot[]`, newest version first | 404 | Version history, including `FAILED` runs. |
| `DELETE /offers/{id}` | 204 | 404 | Deletes the offer text, all runs and reports. |

The legacy compute-on-read `VerificationReport` routes were removed in J3, together with the UI that showed `risk_score` and agent confidence percentages.

### Run rules

- **Inputs.** The run service builds `CaseInput` from the stored text after redaction (`app/services/privacy/redaction.py`: Aadhaar, PAN, labelled passport/account numbers, card numbers, OTPs and passwords are replaced). Employer, recruiter contacts, role and links stay, because they are what is being checked. `demo_mode` is always false for user cases.
- **Confirmations.** `confirmed_claims` come from the review screen and use the stable claim IDs from `/claims`. They are validated with the investigator's claim builder before a run is created; an invalid one is a 422 and no run starts.
- **Reuse.** An active (`QUEUED`/`RUNNING`) run for the case is always returned, with or without `force_refresh`, so repeated requests never multiply searches. Without `force_refresh`, a finished run with a report and the **same inputs** (text + confirmations) is returned. Otherwise a new run is created.
- **Versions.** Each new run gets `version = latest + 1` and `previous_run_id = latest.run_id`. Earlier versions are kept and listed by `/runs`.
- **Status.** `COMPLETED` when the result has no `errors`, `PARTIAL` when it has tool errors (the report is still shown, with failures visible). `FAILED` only when the investigator raises, exceeds `RUN_TIMEOUT_SECONDS` (90 s) or returns a mismatched `run_id`. A failed run has no report and nothing is filled in for it.
- **Restarts.** Runs execute in-process as background tasks. On startup, any run left `QUEUED`/`RUNNING` is marked `FAILED` with `RUN_INTERRUPTED` (retryable). Completed reports are in the database and survive restarts. Deduplication is per process, so run the API with one worker.

### Retention and privacy (J6)

- Cases are deleted `CASE_RETENTION_DAYS` (default 7) after upload, at startup and hourly. Users can delete a case at any time (`DELETE /offers/{id}`, "Delete case" in the report).
- The `aslioffer` logger scrubs emails, phone numbers, 12-digit ID numbers and `key=`/`token=` values from every record. Log lines name case IDs and counts, not offer content.
- Report export (frontend) removes emails, phone numbers and UPI IDs unless the user opts in (for a cybercrime complaint). The employer-published confirmation destination is kept.
- The confirmation draft is only ever copied or opened in the user's own mail app. Nothing is sent by AsliOffer. Its destination comes only from `confirmation_route`, which must cite evidence retrieved in the run.

### Schema migration

New table `investigation_runs` is created automatically. The new nullable column `offers.access_token_hash` is added at startup by `init_db()` if missing (`_ADDED_COLUMNS` in `app/db/session.py`). Offers uploaded before this change have no token and can no longer be opened; they are purged by retention.

## Samples and demo mode

Built-in samples are explicit. The upload page presets submit the sample text as a real case whose title starts with `Sample:`, and the Dashboard's static sample report lives at `/samples/:key` with a visible "illustrative sample" banner. A network failure, 404 or 5xx is shown to the user as an error and is never replaced by a sample.

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 4 Oct 2026 | Initial contract (J1). Awaiting Shriraj's semantics review. |
| 1.0.0 (HTTP only) | 4 Oct 2026 | J3/J6: run, report, claims, runs and delete routes; `X-Case-Token`; `RunRequest`, `ClaimPreview` and `OfferUploadResponse.access_token` in `app/schemas/runs.py` / `offer.py`. The investigator objects (`CaseInput` … `RunSnapshot`) are unchanged, so `CONTRACT_VERSION` stays 1.0.0. Legacy `VerificationReport` routes removed. |
