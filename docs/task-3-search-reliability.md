# Task 3: reliable search outcomes and honest evidence handling

Cleanup base: `f9c914e47ec944f2b88dc5f3a3b03cece5a5cbae`.

## Search outcomes

`SearchResult` remains dictionary-compatible. It carries the query, provider,
source, outcome, organic results, knowledge graph, and safe error/status fields.
The query is internal provenance and must not be logged.

| Outcome | Meaning |
| --- | --- |
| SUCCESS | Completed search with results |
| ZERO_RESULTS | Completed search with no results |
| TIMEOUT | Request timeout or overall deadline expired |
| RATE_LIMIT | HTTP 429 or provider quota error |
| AUTH_FAILURE | Missing/invalid credentials, HTTP 401/403, auth error payload |
| PROVIDER_FAILURE | Network/server failure or incomplete provider operation |
| MALFORMED_RESPONSE | Invalid JSON, missing response shape, or invalid consumed fields |

`is_available` identifies completed searches, including empty searches.
`is_live` additionally requires `source=REAL`. Agents use `is_live` before using
external evidence. Explicit DEMO and legacy MOCK results cannot verify live
investigations. `SEARCH_DEMO_MODE=true` is the only switch enabling generated
demo fixtures. The legacy `mock_key` value and `fallback_to_mock` argument do
not enable demo data.

Organic result items must be objects with string titles and HTTP(S) links;
optional snippets must be strings. Consumed knowledge-graph fields and search
metadata are checked too. Successful empty `search_information` is inspected
independently of `search_metadata`. An unexplained missing result shape is not
classified as an empty search.

## Timeouts, retries, and privacy

| Setting | Default | Bounds |
| --- | --- | --- |
| SEARCH_TIMEOUT_SECONDS | 8 seconds | greater than 0, at most 60 |
| SEARCH_TOTAL_TIMEOUT_SECONDS | 25 seconds | greater than 0, at most 120 |
| SEARCH_MAX_RETRIES | 2 | 0 through 5 |
| SEARCH_RETRY_BACKOFF_SECONDS | 0.5 seconds | 0 through 5 |
| SEARCH_DEMO_MODE | false | explicit boolean |

The overall deadline encloses client setup, HTTP requests, response handling,
and retry sleeps for one search operation. It is separate from HTTP transport
phase timeouts. Independent searches in the same investigation each have their
own budget; this is not a global deadline for extraction and the entire offer.

Timeouts, network errors, transient HTTP 500/502/503/504 responses, and explicit
transient provider error payloads can retry. Delays double with the attempt
number. Authentication errors, malformed responses, other permanent failures,
and exhausted quotas do not retry. HTTP 429 supports both numeric and HTTP-date
Retry-After. Delays above two seconds return RATE_LIMIT immediately instead of
retrying before the provider's requested time. All remaining waits are bounded
by the overall deadline. Caller cancellation is preserved.

Provider errors are mapped to fixed safe messages. Raw response payloads and
request URLs are not retained. Logs do not include queries, private recruiter
contacts, exception text, or API keys. The standalone sanitizer also redacts
keys, URLs, email addresses, and phone-like sequences.

## Agent behavior

- Company: unavailable or empty searches return CANNOT_VERIFY without external
  evidence. A web result does not establish MCA registration; that remains
  NOT_CHECKED.
- Recruiter: no resolved official domain or a phone search without complaint
  hits cannot verify identity. Domain-match results and phone flags are retained
  if a different check fails. Existing adverse signals remain active; Task 5
  will improve their interpretation and agency handling.
- Salary: empty/unavailable searches and knowledge-graph-only results do not
  generate generic AmbitionBox benchmarks. Document-level salary anomalies can
  still require review, without invented citations.
- Scam: local document signals survive outages and are cited as
  `document://submitted-offer`, not retrieved government warnings. If external
  checks fail and no local signals are found, the verdict is CANNOT_VERIFY.
  A completed check with no detected signals does not authenticate the offer.
- Risk: CANNOT_VERIFY/UNVERIFIED coverage gaps add no fraud points and are not
  inserted into red_flags. They remain visible in findings. The existing 0.05
  baseline floor is retained. An unresolved investigation remains inconclusive
  even if unrelated successful checks provide many evidence items.
- Report: inconclusive evidence is described as unavailable or insufficient,
  rather than automatically claiming a sparse employer footprint.

## Integration notes for Jay

Public API schemas, database models, and endpoints are unchanged.
`provider_status` can now be SUCCESS, FAILED, PARTIAL, or NOT_CHECKED. Recruiter
and scam findings expose a `checks` mapping with each subcheck's outcome, source,
and safe error. PARTIAL means successful results have been retained alongside
unavailable checks. Do not render it as wholly successful or wholly failed.
The UI should display local `document://submitted-offer` evidence as a document
observation instead of an external clickable citation. These additions use the
existing free-form details and string source_url fields.

Keep SEARCH_DEMO_MODE=false on the deployed backend. The new total timeout has
a default, so existing deployments do not need a configuration change to run.

## Validation

From the repository root:

```bash
python -m pytest backend/tests/investigation/ -q
python -m pytest backend/tests/investigation/ backend/tests/test_serpapi_client.py backend/tests/test_task3_cleanup.py -q
```

For the complete backend suite from the repository root, set PYTHONPATH to
`backend` (or run `python -m pytest tests/ -q` from inside backend).

New regressions exercise actual agents -> RiskEngine -> VerdictReasoner rather
than supplying an invented risk score. They cover empty and unavailable
investigations, preservation of partial warning signals, malformed item fields,
empty search metadata, deadlines for requests and backoff, cancellation,
Retry-After handling, explicit demo isolation, and private logging.

Three previously expected failures are enabled: unresolved recruiter domain,
phone-only no-hits, and sparse-employer uncertainty. Remaining expected failures
are genuine later-task defects: lookalike domains, recruitment agencies,
contextual fee/channel detection, credential/unlock-payment detection, and
entity extraction. The corpus replay helper models live provider responses
while retaining the fixture files' synthetic provenance labels; demo isolation
must not bypass these behavioral tests.

Still deferred: authoritative domain ownership (Task 4), deeper recruiter
identity checks (Task 5), contextual scam parsing (Task 6), extraction
implementation (Task 7), the broader risk/coverage redesign (Task 8), and removal
of other unsupported successful-search conclusions (Task 9). Existing salary
heuristics on populated searches are not a validated market benchmarking model.

Validated cleanup result (Python 3.12): **127 passed, 10 xfailed** across the
complete backend suite, including 46 new cleanup checks. The one dependency
warning is a FastAPI/Starlette test-client deprecation, not a failed test.
Live SerpApi calls were not used to validate these failure-path regressions.
