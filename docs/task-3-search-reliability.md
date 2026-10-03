# Task 3: Reliable Search Handling and Honest Reporting of Unavailable Evidence

## Overview and Goal
In AsliOffer, external search (SerpApi) verifies corporate web presence, official careers portals, recruiter identity alignment, salary baselines, and public fraud advisories.

Prior to Task 3, a missing API key or upstream search outage resulted in fabricated mock search results (e.g. inventing synthetic corporate domains or injecting canned scam advisories) or collapsed into ambiguous failure modes where unavailable searches were conflated with clean/verified records or fraud convictions.

Task 3 establishes search reliability across the integration boundary:
1. **Explicit Outcome Representation:** A failed search never looks like a successful search with zero results.
2. **Strict Validation:** Upstream responses are checked for HTTP 200 error payloads and malformed shapes.
3. **Bounded Failure Handling:** Explicit request timeouts, bounded transient retries with exponential backoff, immediate short-circuiting on permanent errors (missing/bad credentials), and preserved async cancellation.
4. **Zero Fabricated Evidence:** Production code never synthesizes fake domains, recruiters, or evidence when search is unavailable. Demo mode is strictly isolated.
5. **Honest Consumer Reporting:** Inconclusive searches propagate as `CANNOT_VERIFY` with `provider_status` and error details recorded. Missing evidence never independently inflates fraud risk or confirms identities.
6. **Partial Investigation Preservation:** A failure in one external check (e.g. phone search timeout) preserves evidence gathered by successful checks (e.g. company domain verification).

---

## 1. Internal Outcome Structure & Meanings

The system defines `SearchOutcome` (`app.services.search.serpapi_client.SearchOutcome`) and `SearchResult` (`app.services.search.serpapi_client.SearchResult`), a dict-compatible data structure ensuring 100% backward compatibility for existing callers while exposing structured status properties.

### Outcome Enum (`SearchOutcome`)
| Outcome | Description | HTTP Status / Trigger | Consumer Meaning |
|---|---|---|---|
| `SUCCESS` | Search executed cleanly with usable organic or knowledge graph results | HTTP 200 with organic results or knowledge graph | Real public footprint found and parsed |
| `ZERO_RESULTS` | Search executed cleanly, but the search index contains zero hits for query | HTTP 200 with `total_results == 0` or empty results | No public footprint indexed; inconclusive coverage |
| `TIMEOUT` | Request timed out across all bounded retry attempts | `httpx.TimeoutException` | Provider unavailable due to timeout; check could not run |
| `RATE_LIMIT` | Provider rate limit exceeded (HTTP 429) or plan exhausted | HTTP 429 or JSON `error` containing rate limit message | Provider unavailable due to quota/rate limit |
| `AUTH_FAILURE` | Missing, empty, or invalid API credentials | Unconfigured key, HTTP 401/403, or JSON `error` ("Invalid API key") | Permanent configuration or authentication failure |
| `PROVIDER_FAILURE` | Upstream provider server error or network connection drop | HTTP 5xx, `httpx.ConnectError`, or generic upstream error | Provider unavailable due to server-side outage |
| `MALFORMED_RESPONSE` | Non-JSON response, invalid JSON type, or invalid field types | Unparseable body, JSON non-dict, or non-list `organic_results` | Provider returned corrupted or incompatible data |

### Unified `SearchResult` Class
`SearchResult` inherits from Python's standard `dict` to preserve compatibility with existing code:
- Compatible dict keys: `res["source"]`, `res.get("organic_results")`, `res.get("knowledge_graph")`, `res["status"]`, `res.get("error")`
- Explicit object properties: `res.outcome`, `res.is_success`, `res.is_empty`, `res.is_available`, `res.results`, `res.error`, `res.status_code`
- Adapter method: `SearchResult.from_dict_or_result(res, query=...)` converts legacy dictionary fixtures or replayed mocks into canonical `SearchResult` instances.

---

## 2. Timeout and Retry Policy

All external network operations through `SerpApiClient` are bounded:
- **Per-Attempt Timeout:** Configured via `settings.SEARCH_TIMEOUT_SECONDS` (default: `8.0` seconds).
- **Maximum Retries:** Configured via `settings.SEARCH_MAX_RETRIES` (default: `2` retries, meaning maximum 3 attempts total).
- **Backoff Schedule:** Configured via `settings.SEARCH_RETRY_BACKOFF_SECONDS` (default: `0.5` seconds). Doubles on subsequent attempts (`0.5s`, `1.0s`).
- **Async Event Loop:** All delays use non-blocking `await asyncio.sleep(...)`. `asyncio.CancelledError` is preserved and immediately propagated to ensure cooperative task cancellation.

### Retry Rules
1. **Transient Errors (Retryable up to limit):**
   - `httpx.ConnectTimeout`, `httpx.ReadTimeout`
   - `httpx.ConnectError`, `httpx.NetworkError`
   - HTTP 500 Internal Server Error, HTTP 502 Bad Gateway, HTTP 503 Service Unavailable, HTTP 504 Gateway Timeout
   - HTTP 429 Rate Limit (retried if `Retry-After` header indicates `<= 2.0s` delay within task time budget).
2. **Permanent Errors (Short-circuit immediately, never retried):**
   - Unconfigured, empty, or whitespace API key.
   - HTTP 401 Unauthorized or HTTP 403 Forbidden.
   - JSON response payload containing "Invalid API key" or "Unauthorized".
   - HTTP 400 Bad Request or malformed response shapes.

### Data Privacy & Sanitization
All error messages and logs pass through `sanitize_search_text`:
- API keys are redacted (`[REDACTED]`).
- Sensitive URL query parameters (`api_key=...`) are sanitized.
- No raw applicant resume text, passwords, or PII are written to search error logs.

---

## 3. How Agents Handle Empty and Unavailable Searches

### `CompanyAgent`
- **Provider Failure (`not search_res.is_available`):**
  - Verdict: `CANNOT_VERIFY`
  - Evidence: `[]` (strictly empty; no fabricated MCA links or dummy domains)
  - Details: `provider_status: "FAILED"`, `official_domain: None`, `error: search_res.error`
  - Summary: `"External investigation aborted due to upstream search provider outage / rate limit. No external claims verified."`
- **Empty Search (`search_res.is_empty`):**
  - Verdict: `CANNOT_VERIFY`
  - Evidence: `[]`
  - Details: `provider_status: "SUCCESS"`, `search_status: "SUCCESSFUL_EMPTY"`, `official_domain_resolved: False`
  - Summary: `"Search completed successfully but returned no indexed public footprint for '{company_name}'."`
- **Successful Search with Results:**
  - Evaluates matching official domain; returns `VERIFIED` if official presence matched, or `CANNOT_VERIFY` if results exist but none belong to the company.

### `RecruiterAgent`
- **Provider Failure:**
  - Verdict: `CANNOT_VERIFY`
  - Details: `provider_status: "FAILED"`, `domain_match: None`
  - Does NOT flag corporate recruiters as fraudulent impersonators when official domain search failed.
- **Empty Search / Unresolved Official Domain:**
  - If recruiter uses free webmail (`@gmail.com`): `HIGH_RISK` (direct signal in offer).
  - If recruiter uses custom corporate domain but official company domain is unresolved: `CANNOT_VERIFY`, `domain_match: None`.
- **Phone Number Check:**
  - If search is empty (clean): does NOT claim identity is verified or inject fake cybercrime registry URLs.
  - If adverse reports found: flags `HIGH_RISK` with evidence.

### `SalaryAgent`
- **Provider Failure:**
  - Verdict: `CANNOT_VERIFY` (or `NEEDS_REVIEW` if document itself contained extreme bait figures like ₹50,000/day)
  - Evidence: `[]` (no fabricated baseline evidence injected)
  - Details: `provider_status: "FAILED"`, `error: search_res.error`
- **Successful Search without Company Hits:**
  - Uses role-level baseline (`https://www.ambitionbox.com/salaries`, confidence 0.60) to evaluate whether compensation is realistic.

### `ScamAgent`
- **Preservation of Document-Level Scam Indicators:**
  - Upfront fee demands (`UPFRONT_FEE_DEMAND`), direct UPI requests (`UPI_PAYMENT_REQUEST`), and password/OTP demands present in the offer text trigger `HIGH_RISK` regardless of whether external searches fail or succeed.
- **Search Provider Failure:**
  - Recorded in details: `provider_status: "FAILED"`.
  - If the offer itself has no scam markers, returns `VERIFIED` (clean offer document) with `provider_status: "FAILED"`.

### `RiskEngine` & `VerdictReasoner`
- Missing evidence from `CANNOT_VERIFY` agent findings is treated as uncertainty/unresolved coverage.
- In `VerdictReasoner`, when evidence is insufficient (< 2 items or search outage) and there are no scam markers, the final verdict is `RiskLevel.CANNOT_VERIFY` with reason codes `COMPANY_NOT_VERIFIED` and `RECRUITER_NOT_VERIFIED`.
- Missing evidence alone never produces `RiskLevel.HIGH_RISK`.

---

## 4. Configuration Variables Introduced

The following environment variables are supported in `Settings` (`backend/app/core/config.py`) and documented in `.env.example`:

| Environment Variable | Type | Default | Description |
|---|---|---|---|
| `SERPAPI_API_KEY` | `str` | `""` | SerpApi API key for live search queries |
| `SEARCH_TIMEOUT_SECONDS` | `float` | `8.0` | Timeout per HTTP request to SerpApi (seconds) |
| `SEARCH_MAX_RETRIES` | `int` | `2` | Maximum retry attempts for transient search failures (5xx, timeouts) |
| `SEARCH_RETRY_BACKOFF_SECONDS` | `float` | `0.5` | Initial backoff delay between retries; doubles on subsequent retries |
| `SEARCH_DEMO_MODE` | `bool` | `false` | Explicit offline demo mode returning isolated demo fixtures |

---

## 5. Integration Notes for Jay (Frontend & Shared Schemas)

1. **API Contract Compatibility:**
   - No breaking changes were made to public API schemas (`VerificationReport`, `AgentFinding`, `EvidenceItem`, `RiskLevel`).
   - The database models and endpoints (`/offers/upload`, `/offers/{id}`, `/offers/{id}/report`, `/analysis/run`) remain 100% compatible.
2. **New Status Fields in Finding Details:**
   - `finding.details["provider_status"]`: `"SUCCESS"` or `"FAILED"`.
   - `finding.details["search_status"]`: Detailed machine-readable outcome (`"SUCCESS"`, `"SUCCESSFUL_EMPTY"`, `"TIMEOUT"`, `"RATE_LIMIT"`, `"AUTH_FAILURE"`, `"PROVIDER_FAILURE"`, `"MALFORMED_RESPONSE"`).
   - `finding.details["error"]`: Sanitized error description when search provider is unavailable.
3. **Proposed Frontend Enhancements for Jay (Optional / Non-breaking):**
   - In the investigation report UI, when `finding.details.provider_status === "FAILED"`, display an informative banner: `"External search check temporarily unavailable (Search provider offline)"` rather than presenting it as an absent corporate footprint.
   - For `CANNOT_VERIFY` findings with `search_status === "SUCCESSFUL_EMPTY"`, display: `"No indexed public presence found"`.

---

## 6. Test Results and Remaining Limitations

### Investigation Corpus Test Results
Running `python -m pytest backend/tests/investigation/ -q`:
- **28 passed, 13 xfailed in 0.87s**
- `test_case_11_empty_search_is_uncertainty`: **PASSED** (enabled, xfail removed).
- `test_case_12_provider_failure_is_not_evidence[rate_limit]`: **PASSED** (enabled, xfail removed).
- `test_case_12_provider_failure_is_not_evidence[authentication]`: **PASSED** (enabled, xfail removed).
- `test_case_12_provider_failure_is_not_evidence[timeout]`: **PASSED** (enabled, xfail removed).
- All Task 2 extraction contract tests: **13 passed**.
- All Task 1 fixture corpus tests: **11 passed**.

### SerpApi Reliability Regression Suite
Running `python -m pytest backend/tests/test_serpapi_client.py -v`:
- **16 passed in 9.13s**
- Covers all 14 specified regression scenarios:
  1. Successful populated search
  2. Successful empty search
  3. Timeout handling
  4. HTTP 429 rate limit handling
  5. Missing and invalid credentials
  6. HTTP 500/503 provider server failure
  7. HTTP 200 with SerpApi error payload
  8. Malformed JSON and schema responses
  9. Transient failure followed by success
  10. Exhausted retries after repeated failures
  11. Permanent failures are not retried
  12. Partial success across multiple checks
  13. Provider failure does not trigger fabricated evidence or verification claims
  14. Missing evidence does not independently increase fraud risk
  15. Sanitization of sensitive keys in logs and errors
  16. Dictionary and property backward compatibility

### Remaining Limitations (Deferred to Later Tasks)
- **Task 4 (Official Domain Resolution):** Domain lookalike detection (e.g. brand name substring in third-party lookalike domain `tcs-careers-portal.example`) is addressed in Task 4.
- **Task 5 (Recruiter Verification Redesign):** Agency recruitment mandate checking and deeper domain MX validation are addressed in Task 5.
- **Task 6 (Contextual Scam Detection):** Negated security deposit policies and quoted advisory parsing are addressed in Task 6.
- **Task 7 (Risk Synthesis & Coverage Redesign):** Decoupling risk score from coverage breadth for startups with sparse web footprints is addressed in Task 7.
