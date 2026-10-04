# AsliOffer: competitive review and two-person implementation plan

Reviewed 3 October 2026. Repository: https://github.com/jaypatel345/aslioffer
Pinned main commit: b5f3918ba9340be4a6cffdbcb7a449fae7b12fd3, 28 September 2026, “Make Gemini document reading work: current model, retries, model fallback”. This is the default-branch head returned at review time; other branches are outside scope.

Plan revised 3 October 2026 for **Shriraj and Jay**. The application audit remains pinned to the commit above; repository head was rechecked before publishing this plan and was unchanged.

## Assessment

The problem is worthwhile and the repository provides a usable architectural foundation. It is not yet a strong evidence-backed offer verifier. Its most important weakness is confusing a plausible company/recruiter footprint with authentication of the specific offer. More features or more named agents will not solve this. Stronger identity resolution, honest uncertainty, adaptive searches, and demonstrable evaluation will.

The preceding commit fixed company extraction errors, invented company domains, several fail-open cases, and misleading summaries. Those improvements are present in the current code. However, significant false reassurance and false accusation paths remain.

Scope: source inspection across backend, frontend, tests, setup and architecture documentation; six controlled behavioral probes of existing agent/risk code. No application code was changed during the original audit. This revision adds the two-person implementation plan as repository documentation. Full pytest execution was attempted but could not start because pytest was absent; httpx was also absent. Controlled probes used real agent/risk implementations and Pydantic schemas, with injected search fixtures and minimal import stubs for unavailable HTTP/config dependencies. These are isolated logic reproductions, not end-to-end/live-provider validation. OCR quality, live API credentials, production deployment, frontend rendering, and actual model availability were not verified.

## Hackathon alignment

Official homepage: https://serpapi.github.io/serpapi-india-hackathon-2026/
Official rules: https://serpapi.github.io/serpapi-india-hackathon-2026/rules.html

Deadline: 10 October 2026, 23:59 IST. Teams may contain one to five contributing members, all India residents aged at least 18. AI Agents describes agents that plan, search, compare and act; its suggested search-tools/MCP integrations are recommendations, not mandatory dependencies. Judging considers idea strength, originality, technical complexity, usefulness and meaningful SerpApi use without fixed percentage weights. Submission needs public code, reproducible instructions, an explanation of material SerpApi use, AI-tool disclosures and a public/unlisted video under three minutes showing local functionality. A saved draft must explicitly be submitted.

AsliOffer fits the intended track if investigation becomes adaptive. Today its four investigation agents are mostly deterministic checks with fixed searches; Gemini supplies extraction/OCR. That is a legitimate pipeline, but weak evidence for agent planning and decision-making. The product also overlaps Knowledge & Public Interest; the organizers can reclassify entries. Demonstrate the agent behavior clearly rather than relying on agent class names.

## Current implementation and material gaps

| Priority | Finding | Evidence in pinned code | Required change |
|---|---|---|---|
| P0 | Report failures substitute unrelated demo results | frontend/src/services/api.ts: getOfferReport catches errors and returns the Infosys/TCS fixture; runAnalysis can enter the same path | Explicit demo mode only; real failures show partial/failed status. Never replace a user's case with a fixture. |
| P0 | Unknown IDs fabricate offers and analyze a built-in TCS message | backend/app/api/v1/routers/offers.py: get_offer and get_offer_report | Return 404 for missing IDs. Keep presets as explicitly created sample offers. |
| P0 | Lookalike domains can be treated as official | company_agent.py: _domain_matches uses normalized hostname substring/acronym matching | Resolve canonical domains using independent authoritative evidence; normalize registrable domains, detect lookalikes, and retain candidates until resolved. Brand text in a hostname is insufficient. |
| P0 | Recruiters can pass without an independently resolved official domain | recruiter_agent.py: unmatched domain with no official candidates falls through to VERIFIED; phone-only clean search also passes | Unknown identity becomes CANNOT_VERIFY. A domain alignment observation must not certify an individual recruiter or sender. |
| P0 | Missing evidence becomes alleged danger | risk_engine.py adds .30/.25/.05 for three CANNOT_VERIFY findings; verdict_reasoner.py treats scores >= .50 as scam markers | Keep evidence coverage separate from adverse evidence. Search failure and sparse startup footprint should cause abstention, unless independent risk signals exist. |
| P0 | Keyword checks ignore context and omit important threats | scam_agent.py: any fee phrase/Telegram mention triggers HIGH_RISK; no explicit OTP demand detector | Extract actor, action, recipient and negation; distinguish a payment demand from a no-fee policy and a quoted warning. Add OTP/password/payment-to-unlock demands. |
| P0 | Unsupported registry and advisory claims | CompanyAgent sets mca_status ACTIVE from website presence; RiskEngine/ReportGenerator claim corporate registration; static portal URLs accompany generated advisory/legal text | Website existence is not registry verification. Report NOT_CHECKED unless an actual registry record was obtained. Replace unsupported legal assertions with observed signals and directly supporting sources. |
| P1 | Mock evidence is still mixed into investigations | serpapi_client.py returns canned scam warnings on failure; ScamAgent gives these evidence confidence .85 | Propagate REAL/FAILED/DEMO status per item. Provider failure must not create evidence. |
| P1 | Salary conclusions are not derived from retrieved pay data | salary_agent.py cites snippets but uses fixed bands and a ₹25 lakh annual cutoff; monthly stipends abstain | Deprioritize salary; if retained, compare currency/period/location/seniority and show sample size. Without comparable data, abstain. |
| P1 | Claims from the offer are lost before investigation | ExtractedData has website, joining date and salary period; to_extracted_entities drops them; no job ID/application URL/recipient handle schema | Preserve claim fields and exact source spans. Extract all contacts with semantic roles, not simply the first email. |
| P1 | Investigation is fixed and duplicated | offers.py asyncio.gather starts four fixed investigators; CompanyAgent and RecruiterAgent repeat the company query | Shared case state and bounded planner; resolve employer first, then adapt recruiter/job/policy searches. |
| P1 | No evidence snapshot or actual job-status stream | Evidence model is imported but not written in the report route; GET report recomputes; force_refresh is ignored; Upload.tsx advances steps every 700ms | Persist versioned reports/evidence; POST creates runs, GET reads snapshots; SSE/polling reports actual tool completion. |
| P2 | Graph and cache claims exceed implementation | GraphBuilder is a stub outside report path; no cross-case lookup; Redis is configured without cache usage | Remove claims or implement one narrow useful function. Do not prioritize graph algorithms this week. |
| P1 | Privacy and public-service controls need work | Uploaded raw content persists; offers accessible through sequential IDs without ownership checks; recruiter contacts/search queries logged; no explicit upload size limit | Ephemeral mode/deletion, protected case access if hosted, redaction before model/search, upload bounds, retention rules and scrubbed logs. |
| P1 | Submission/setup documentation is stale | README calls the MVP production-grade, advertises MIT without a LICENSE in the returned tree, and describes checks not implemented; Compose overrides the new model default with gemini-2.5-flash | Document only working features; align model configuration, verify provider model availability, supply a real license if desired, and test fresh setup. |

The current score is a heuristic sum, not a calibrated probability. Displaying “60% Risk” and fixed confidence values suggests statistical evidence the repository does not provide. Repeated generic citations also inflate VerdictReasoner confidence through evidence count. Use risk bands, evidence coverage and source quality separately; deduplicate supporting sources by claim and independence.

## Controlled reproductions

| Input/fixture | Existing behavior | Desired behavior |
|---|---|---|
| Company Infosys; only search result https://infosys-careers-scam.example/jobs | CompanyAgent VERIFIED | Unresolved or suspected lookalike; independent canonical-domain check required |
| Unknown startup; hr@unresolved.example; search FAILED with no results | RecruiterAgent VERIFIED, domain_match true | Cannot verify; domain match unknown |
| Phone-only recruiter; no search results | RecruiterAgent VERIFIED, domain_match true | No identity confirmation; no public reports is not proof of legitimacy |
| “We never charge a security deposit.” | ScamAgent HIGH_RISK, UPFRONT_FEE_DEMAND | No payment demand from that sentence |
| “Send your bank OTP to activate your offer.” with empty extracted flags | ScamAgent VERIFIED | Critical credential demand detected; end-to-end extraction may add other flags, but the agent itself misses this |
| “Please join our Telegram channel for interview updates.” | ScamAgent HIGH_RISK | Contextual weak signal, not sufficient alone |
| Company/recruiter/salary all CANNOT_VERIFY; scam check VERIFIED | RiskEngine 0.60, HIGH_RISK | Inconclusive coverage absent adverse evidence |

## Recommended USP

Positioning: **AsliOffer investigates whether the recruiter, job link and payment request belong to the real employer, shows the evidence for each claim, and finds an independent route to confirm the offer.**

Target final-year students, freshers and internship applicants in India first. A second user is the college placement coordinator helping students verify offers.

The differentiator is an offer-specific, auditable chain from claimed employer to resolved official domain to recruiter contact to application destination to payment demand. It should expose contradictions even when a letter uses a real company, realistic salary and copied corporate contact details. It must also avoid accusing a small legitimate startup merely because its footprint is sparse.

This is a proposed differentiator, not a proven first-of-its-kind claim. Public competitors already advertise message/screenshot offer checks, explanations and next steps. For example https://scamoffer.com/ presents those capabilities and labels its illustrative analysis as based on message text rather than external verification. https://scamguard.live/job-offer-scam-checker and https://scamdekho.in/fake-offer-letter-checker also advertise this category. Their marketing was inspected, not their internal systems or accuracy. “AI + four agents + upload + score” is therefore not sufficient differentiation.

Use three product pillars:

1. **Claim versus evidence:** each claim is supported, contradicted, unresolved, or not checked. Show the offer quote, query, retrieved source and timestamp. A retrieved snippet is labeled as a snippet unless the page itself was checked.
2. **Adaptive investigation:** a conflict generates a targeted follow-up search; sparse results lead to a clarifying question or abstention. The agent visibly explains why it searched again and stops under a defined budget.
3. **Independent confirmation:** find an employer-published careers/contact route and draft a minimal inquiry about the role/reference code. User reviews and sends it; no automatic recruiter contact. Export the case evidence for the student or placement cell.

Avoid “verified offer” unless an authorized employer actually confirms it. “No strong risk signals found; offer authenticity remains unconfirmed” is a much more defensible positive outcome.

## Implementation design

Create CaseClaim, EntityCandidate, EvidenceRecord and InvestigationRun schemas. Evidence records hold claim_id, quote/source span, source_url, title, extracted snippet, retrieval time, engine, query, SerpApi search ID, live/cache/demo/error status, source tier and whether they support or contradict the claim. Store only the redacted subset needed; provider keys never enter persisted URLs. Include page/location references for documents where available.

Run sequence:

1. Extract structured claims plus source spans. Present editable employer, sender, role, location, job/reference ID, application URL and payment recipient fields before search when extraction is uncertain.
2. Planner lists verification questions and selects allowed tools. Employer-domain resolution feeds recruiter and URL checks rather than running independently with inconsistent candidates.
3. Search official careers/contact/policy pages, then Google Jobs for matching role/location/application destination. SerpApi Google Jobs supports structured jobs_results and application options: https://serpapi.com/google-jobs-api . Match corroborates a public vacancy, not issuance of this letter. No match is unresolved because jobs can be private, expired or unindexed.
4. Detect email/application-domain contradictions with registrable-domain parsing, IDNA normalization and lookalike checks. Corporate email text in an uploaded letter is a claim; it does not prove actual sending/authentication. Optional .eml headers can add limited context later, without claiming unauthenticated headers prove delivery identity.
5. Read payment requests contextually and, when present, search exact recipient identifiers after user consent/redaction rules. A matching complaint requires entity match, adverse context, date and source reliability; shared numbers alone do not prove fraud.
6. Targeted follow-up if evidence conflicts. Allow roughly 6–8 logical searches initially, with measured credit use and an explicit ceiling. Use India region/language/location parameters where appropriate. Cache shared employer resolution with a TTL and deduplicate concurrent identical requests; the current code does neither.
7. Deterministic policy combines concrete risk findings separately from coverage. The LLM proposes structured claims/questions and explains evidence; it cannot invent citations, overwrite evidence or certify authenticity.
8. Persist a report snapshot; stream real step/tool events. Give a grounded confirmation action and show remaining unknowns.

Prompt-injection resistance belongs here: uploaded letters and retrieved snippets are untrusted data. Restrict tools, validate structured outputs, require existing evidence IDs for citations, and never let document text alter policy. If adding source-page fetches, block private/local destinations and unsafe redirects and enforce time/size limits.

## Two-person delivery plan: Shriraj and Jay

This plan replaces the earlier 4–5-person allocation. Active implementers are Shriraj and Jay. Assignments are a concrete proposed working split, not a claim about either person's existing skills or consent. Swap whole workstreams if necessary before starting; preserve single ownership of files. The goal is a trustworthy competitive MVP by 9 October, leaving 10 October for contingencies. Completing every earlier aspirational feature is not realistic for two people in one week.

### Scope and priority rules

**Must ship:** honest failure/uncertainty states; no fabricated reports; canonical-domain and recruiter checks; contextual fee/credential signals; evidence provenance; one bounded adaptive follow-up; claim/evidence UI; stored report snapshots; reproducible setup and evaluation.

**Ship if core is stable by 7 October:** Google Jobs corroboration with application destinations; employer-sourced confirmation draft; downloadable redacted JSON/text report. Job matching is valuable to the USP, but a weak implementation must abstain rather than pretend to verify a vacancy.

**Defer:** registry integrations, sophisticated salary benchmarking, Neo4j/community graphs, Redis deployment/cache infrastructure, automatic messages, .eml authentication analysis, extensions, multilingual promises and automatic complaint submission. Remove unimplemented claims. In-process per-run query deduplication is enough initially. Employer contact discovery can remain an unresolved field when a suitable official source is unavailable.

The first-week agent can use a small rule-constrained planner with structured LLM input if dependable. Do not spend the week migrating frameworks. It must choose a follow-up based on evidence, record the reason and obey tool/query limits; a fixed list of searches relabeled as planning does not satisfy the design goal.

### Single-owner file map

| Owner | Files/directories exclusively edited | Responsibility |
|---|---|---|
| **Shriraj** | backend/app/services/extractor/**, backend/app/services/ai/** | Claim extraction, document reading, source spans, contextual interpretation |
| **Shriraj** | backend/app/services/search/**, backend/app/services/agents/** | Search client, provenance, company/recruiter/job/policy investigation and domain checks |
| **Shriraj** | backend/app/services/risk/**; new backend/app/services/investigation/** | Verdict policy, shared case state, bounded planner, investigate_case entry point |
| **Shriraj** | New backend/tests/investigation/** and backend/tests/fixtures/investigation/** | Investigator unit tests and labeled fixture corpus |
| **Shriraj** | Existing test_gemini_extractor.py, test_salary_agent.py, test_scam_agent.py, test_serpapi_client.py, test_verdict_reasoner.py | Adjust existing logic tests to new honest outcomes |
| **Jay** | backend/app/schemas/** | Sole Python contract/model owner; implements agreed schema, adds fields rather than letting both edit it |
| **Jay** | backend/app/api/**, backend/app/db/**, backend/app/main.py, backend/app/core/** | Routes, run status, persistence, upload/access limits, logging configuration and lifecycle |
| **Jay** | backend/app/services/report/** | Compose presentation from Shriraj's assessed claims; no duplicate risk or identity logic |
| **Jay** | frontend/** | Typed client, extraction confirmation UI, actual status, claim table, errors and explicit sample mode |
| **Jay** | backend/tests/test_api.py; new backend/tests/integration/** | API persistence/access/error contracts and integrated smoke tests |
| **Jay** | backend/requirements.txt, .env.example, backend/.env.example, docker/**, docker-compose.yml, .gitignore | Dependencies and reproducible configuration; adds packages requested by Shriraj |
| **Jay** | README.md, docs/architecture.md; new docs/api-contract.md, docs/evaluation-results.md | Public truthfulness, runnable setup, API contract, measured evaluation summary |
| **Shriraj** | docs/competitive-review-and-two-person-plan.md (this document after publication) | Task status and scope decisions; Jay requests changes instead of editing concurrently |

Leave graph files untouched and describe the graph as future work. This ownership map covers existing and planned code; a new module outside these boundaries needs an owner assigned before it is created. Private .env files are never committed. Ownership is a coordination rule, not a restriction on review: both review everything, but only the owner implements edits in their files.

### Shared contract: agree first, then build independently

Jay writes docs/api-contract.md and Python models on 3–4 October; Shriraj reviews required semantics once. Freeze contract v1 before merging dependent changes. Shriraj supplies examples and model requirements, and Jay performs schema edits. Jay also mirrors the wire schema in frontend/src/types/index.ts. Contract changes require an explicit update note and a sample payload; no unannounced renames.

The following is a **proposed interface**, not an API already present in the repository:

| Object | Required contract fields and rules |
|---|---|
| CaseInput | case_id, run_id, contract_version, source_type, redacted_text, confirmed_claims, demo_mode; include raw input internally only where extraction requires it and never send identifiers wholesale to search |
| Claim | claim_id, kind, value, source_quote, start_offset/end_offset or page reference if known, extraction_status; kind includes employer, sender_email, contact_phone, role, location, job_reference, application_url, payment_request, credential_request |
| EvidenceRecord | evidence_id, claim_id, source_kind (DOCUMENT/SEARCH_SNIPPET/CHECKED_PAGE), source_url nullable, title, quote_or_snippet, retrieved_at, query nullable, engine nullable, search_id nullable, retrieval_status (LIVE/CACHED/DEMO/FAILED), source_tier, relation (SUPPORTS/CONTRADICTS/CONTEXT) |
| AssessedClaim | claim_id, status (SUPPORTED/CONTRADICTED/UNRESOLVED/NOT_CHECKED), explanation, evidence_ids, reason_codes; all referenced evidence must exist in this run |
| InvestigationResult | contract_version, run_id, claims, evidence, overall_outcome, authenticity_status, coverage, recommended_actions, confirmation_route nullable, tool_trace, errors; overall_outcome is HIGH_RISK/NEEDS_REVIEW/CANNOT_VERIFY/NO_STRONG_RISK_SIGNALS and authenticity_status remains UNCONFIRMED without employer confirmation |
| Coverage | checked_claims, total_claims, unresolved_claims, failed_checks; this is completeness, not fraud probability |
| RunEvent | run_id, sequence, step, status, public_message, timestamp; public messages contain no keys or unnecessary personal details |
| RunSnapshot | run_id, case_id, status (QUEUED/RUNNING/COMPLETED/PARTIAL/FAILED), timestamps, progress/events, report nullable, errors; latest finished snapshot is distinguishable from a currently running refresh |

Do not introduce a “fraud_probability” field. If retaining the old risk_score temporarily for compatibility, explicitly label it a heuristic, suppress percentage claims in the UI and remove it after migration. New evidence models allow source_url=null for document-local observations; do not attach a generic government homepage merely to fill a required URL.

Backend function handoff:

- Shriraj exposes `async investigate_case(case_input, search_client=None, emit_event=None) -> InvestigationResult` in backend/app/services/investigation/pipeline.py. Search client injection supports reproducible fixtures. The orchestrator contains extraction/investigation/policy logic and no database, FastAPI or frontend imports.
- `emit_event` is an optional async callback supplied by Jay, awaited with a validated RunEvent payload. It must not change the verdict. Jay stores/publishes events and manages run state.
- Jay's run service builds CaseInput, invokes this function, validates and stores the result, then passes it to ReportGenerator. ReportGenerator may format explanations but cannot re-run checks or upgrade UNRESOLVED to SUPPORTED.
- Shriraj catches tool-specific failures, records structured errors and returns partial evidence where usable. An exception in one search must not silently abort unrelated checks or fabricate a successful result. Jay catches unexpected top-level errors, marks the run FAILED and exposes a safe error response.
- Jay can build the full frontend against clearly labeled contract fixtures before Shriraj's live investigator is ready. Fixtures are selected explicitly, never triggered by backend/network failures.

Suggested external API behavior (Jay owns final documented URLs and compatibility adapters):

- POST /offers/upload: creates case/extraction result; returns case identifier, extracted editable claims and unreadable-file errors. User corrections remain distinguishable from extracted quotes.
- POST /analysis/run: starts or reuses a run for offer_id; returns run_id/status/report location. force_refresh=false reuses a completed compatible report or existing active run; true creates a new version while preserving the prior snapshot. Lock/unique run logic prevents accidental duplicate searches.
- GET /analysis/runs/{run_id}: reads status/events and report reference. Polling is acceptable for the two-person MVP; SSE is optional. Status must be backed by real events.
- GET /offers/{id}/report: reads the stored completed/partial report; never starts searches. A case that exists but has no report returns documented 409/status response, and an unknown case returns 404.
- GET /offers/{id}: returns only the requested accessible case or 404. For a public hosted instance, enforce a per-case secret/session authorization boundary; sequential IDs alone are not authorization.

Keep current endpoints working through Jay-owned adapters while migrating, or update both client and API in one integration merge. No branch should independently invent a second contract.

### Shriraj's ordered task list

| ID | Task and implementation boundary | Dependency | Done when |
|---|---|---|---|
| S1 | Write adversarial fixtures and extraction requirements; preserve website/job/reference/payment/credential claims and semantic contact roles | Can start immediately; new model use after J1 | Wrong company from platform names is avoided; first candidate email is not automatically recruiter email; source quotes are retained; uncertain fields remain editable |
| S2 | Fix SerpApi failure propagation and canonical employer resolution; add shared resolution result and safe domain normalization | J1 contract; request packages from Jay | Mock warnings never enter real evidence; lookalike fixture cannot become official; empty/failed searches remain distinguishable; official_domain unknown unless resolved |
| S3 | Repair recruiter and contextual scam checks | S1/S2 interfaces; can implement fixture-first | Unresolved corporate email and phone-only no-hit cases abstain; fee negation and quoted policies pass; direct OTP/password and payment-to-unlock demands are detected; Telegram alone is not critical |
| S4 | Replace risk/coverage conflation and unsupported confidence | J1; S3 outputs | Sparse startup plus no adverse signal is CANNOT_VERIFY; concrete threats remain HIGH_RISK; duplicates do not boost confidence; no company-registration claim from website presence |
| S5 | Implement one adaptive investigation path and budget | S2–S4; fixture-first | Canonical-domain conflict causes a targeted partner/policy search with recorded reason; fallback is bounded and abstains if unresolved; duplicate company queries are shared; tool calls are measured |
| S6 | Add job/application corroboration and confirmation discovery if core stable | S5 | Compare employer/role/location/application domains, label no-match unresolved, return an independently sourced confirmation route or null; no-match does not imply fraud |
| S7 | Run investigator evaluation and deliver final bundle | S1–S5 required; S6 if implemented | Provide reproducible results, fixtures, source links and known limits; no unsupported accuracy percentage |

Salary work this week: Shriraj removes automatic salary “verified” conclusions from fixed bands and returns unresolved when no comparable data exists. Do not implement a full pay intelligence subsystem.

Shriraj's handoff bundle: stable entry point, one supported/one contradictory/one sparse/one outage result fixture, seven reproduced regressions fixed or explicitly documented, passing investigator tests, query-budget behavior and installation requests. No DB/schema/frontend edits.

### Jay's ordered task list

| ID | Task and implementation boundary | Dependency | Done when |
|---|---|---|---|
| J1 | Publish API contract, implement Python schemas and TypeScript wire models; provide investigator result fixtures | Immediate; one review of field semantics with Shriraj | Both sides can parse same versioned examples; optional/null fields and error/status shapes documented |
| J2 | Remove fabricated API/client reports and implement honest errors | Immediate; independent of S work | Unknown IDs 404; real report/network failures never return TCS/Infosys fixtures; presets create explicitly labeled sample cases |
| J3 | Implement run/report persistence, status and polling | J1; use stub result until S5 ready | POST invokes a run; GET only reads snapshots; force_refresh versioning works; duplicate active requests do not multiply tool calls; restarts retain completed reports |
| J4 | Implement claim confirmation/report UI with actual progress | J1 fixtures; parallel with J3/S work | Shows quotes, statuses, evidence sources/times, coverage and unresolved checks; no timer-based completion or misleading risk/confidence percentages |
| J5 | Render confirmation draft and export if scope permits | J4; accepts null route before S6 | Contact destination comes from returned official evidence, not user-supplied recruiter link; user reviews draft; no auto-send; export strips sensitive identifiers as needed |
| J6 | Apply upload/privacy/config controls and fresh setup verification | Can start immediately; Shriraj sends dependency requests | Upload size/type bounded; scrubbed logs; deletion/retention documented; hosted case access protected; all model defaults aligned and actual configured provider model tested |
| J7 | Integrate, run API/smoke checks, document, record and submit | S handoff + J2–J6 | Fresh clone works, stored report reload does not issue searches, partial failures display correctly, demo meets published requirements |

Jay's handoff bundle: contract models/examples, run endpoint behavior, status/error fixtures, schema migration instructions, frontend walkthrough, fresh-setup commands and integrated verification results. No agent/extractor/risk implementation changes.

### Dependency handoffs and daily merge checkpoints

| Date (IST) | Shriraj lane | Jay lane | Merge/handoff gate |
|---|---|---|---|
| 3 Oct evening | Fixture corpus, S1 requirements, S2/S3 reproductions | J1 contract/examples; J2 fallback/404 removal | Agree models and ownership; merge contract first; both pull it |
| 4 Oct | S1/S2/S3 fixes | J2 complete; J3 run storage design; J4 fixture-based UI | Fixtures exercise failure/uncertainty; J1 parses all required examples |
| 5 Oct | S4 policy and investigator entry point | J3 persistence/status; J4 claim table/progress | First full fixture-driven upload→run→report path; no live keys needed |
| 6 Oct | S5 bounded adaptive follow-up | Integrate real investigator; error/persistence/access tests | Live company-domain conflict generates real follow-up; no invented evidence |
| 7 Oct | S6 only if core passes; investigator regressions | J5 confirmation/export only if core passes; J6 setup | Core scope freeze; remove/defer unstable optional features explicitly |
| 8 Oct | S7 evaluation, held-out cases and fixes in owned files | Integrated smoke tests, fresh setup, docs/results | Joint acceptance gate; agree unresolved limits and actual claims |
| 9 Oct | Review results/pitch, verify agent sources and failure cases | Final setup rehearsal, record video, prepare and submit entry | Submit working version before final day; verify public links |
| 10 Oct | Available for investigator fixes only | Final submission/link checks and contingency | No speculative features; deadline 23:59 IST |

This is a planning target, not a guarantee. If the contract or core fixes slip, cut J5 export and S6 job corroboration before cutting honest uncertainty, evidence provenance or regression coverage. Aim for a smaller reliable demo rather than an unfinished broad product.

### Git workflow to prevent overlapping work

1. Pull main and branch before editing. Use `shriraj/investigation-core` and `jay/platform-report-ui`; smaller task branches from these are fine. No shared checkout or shared working branch.
2. Jay lands the contract first; Shriraj rebases/pulls before adopting the new schema. Each task PR names its task IDs and confirms the changed files are in the owner's lane.
3. Do not rewrite the other person's files to make a test pass. Request a specific contract/adapter change with an example input and expected output; the file owner implements it.
4. Dependency/config requests from Shriraj go to Jay with package name, purpose and version constraints. Jay alone updates requirements/setup files.
5. Keep PRs small enough for the other person to review the behavior and test evidence. Integrate daily. Avoid feature-branch merges only on deadline day.
6. For conflicts, the file owner resolves their files; neither accepts an entire incoming version blindly. Rerun relevant tests after resolution.
7. Review each other's PRs; the implementer may merge after the agreed checks. Repository ownership is not a reason to assign all deployment or coding work to one person.
8. Update this plan's task status through Shriraj. Jay reports J-task statuses in PR descriptions instead of both editing the document. Main contains the canonical plan; do not maintain competing copies.

### Verification responsibilities and measurable gates

Use 24–30 labeled fixture cases initially, expanding toward 40–60 only if time allows. Shriraj owns fixture files and labels; Jay tests the same fixtures through the API without editing them. Reserve a held-out subset before tuning. Cover realistic impersonation, direct fees/credentials, lookalikes, legitimate no-fee text, sparse employers, agency recruitment, missing metadata and provider failure. Synthetic examples are labeled as such and do not establish employer-authenticated ground truth.

Shriraj runs agent/extraction/policy tests and supplies outputs. Jay runs API/frontend build and smoke tests plus fresh-clone setup. Both inspect one live case, one sparse case and one failed-search case. Record commands, dates and actual results in docs/evaluation-results.md; do not publish “all tests pass” without executing them. Review limitations from the original audit remain historical until these checks are done.

Required regressions:

- Lookalike brand-containing domain is not a resolved official domain.
- Unknown corporate-looking sender and phone-only no-hit contact do not verify recruiter identity.
- No-fee policy/quoted advisory is not a fee demand; ordinary Telegram mention alone is not critical.
- Explicit OTP/password request produces a grounded severe signal.
- Sparse employer/empty search/provider failure causes uncertainty absent independent adverse evidence.
- Unknown case is 404; report GET cannot fabricate a case or initiate search.
- Real network failure never yields a demo report; partial failures remain visible.
- Unsupported registry/legal assertions do not appear; document observations and search evidence are distinct.
- Reload reads identical persisted snapshot; force refresh creates a traceable new version.
- Actual follow-up depends on observed conflict and obeys query limits.

Benchmark outputs: false reassurance and false warnings with denominators, abstention rate, unsupported-citation count, latency samples and calls/credits per run. Small samples must be described as preliminary. Live and cached/fixture timing must be separated. Do not equate the two-person delivery target with production readiness.

### Task board: start here

All implementation tasks below are initially **TODO**; writing this plan does not complete them. Current Jay status: J1–J6 done; J7 remaining (see *Jay's task status* below).

| Owner | Immediate start | Next after dependency | Final deliverable |
|---|---|---|---|
| Shriraj | S1 fixtures/claim requirements; S2/S3 isolated logic fixes | Adopt J1; S4 verdict; S5 planner | S7 evaluated investigator handoff |
| Jay | J1 contract and J2 honest route/client failures | J3 snapshots; J4 fixture-based UI | J6/J7 setup, integration and submission |

Shared decisions requiring a short sync: contract v1, scope cut on 7 October, final benchmark interpretation and submission claims. Everything else follows file ownership. The two workstreams can proceed concurrently without editing the same modules.

#### Jay's task status

Updated 4 October 2026 by Jay. Only J-tasks are listed here; Shriraj's S-task status is tracked in his own task docs (`docs/task-*.md`).

| ID | Status | Delivered | Verification |
|---|---|---|---|
| J1 | **DONE**: contract v1 published. Needs Shriraj's one-time semantics review before freeze. | `docs/api-contract.md`; `backend/app/schemas/contract.py`; TS mirror in `frontend/src/types/index.ts`; 12 example payloads in `docs/contract/v1/examples/`, including the supported, contradictory, sparse and outage results | `backend/tests/integration/test_contract_v1.py` (33 tests): every example parses and round-trips in Python and type-checks against the TS types; each enforced rule has a negative test |
| J2 | **DONE** | Unknown IDs return 404 on `/offers/{id}`, `/offers/{id}/report` and `/analysis/run`, and no search runs. The frontend has no fallback data: network/404/5xx failures show an error with retry. Samples are explicit (`/samples/:key` with a banner), and presets create real cases titled `Sample: …` | `backend/tests/test_api.py` (404s, no search on unknown IDs, former demo IDs 101/102, sample labels); full backend suite 426 passed; `npm run build` passes; browser checks of the 404, invalid-ID, offline-backend, sample and preset flows |
| J3 | **DONE** | `investigation_runs` table and run service (`app/services/runs/run_service.py`). `POST /analysis/run` returns a `RunSnapshot` (202 queued / 200 reused), and runs execute in the background through the real `investigate_case`. `GET /analysis/runs/{id}` is for polling and `GET /offers/{id}/runs` lists versions. `GET /offers/{id}/report` reads the stored snapshot only (409 if none). `force_refresh` creates version n+1 and keeps n. Active runs are always reused. Interrupted runs are marked FAILED on restart. | `backend/tests/test_api.py`: lifecycle, read-only report GET (no search, identical reloads), reuse, versioning, active-run dedupe, PARTIAL, crash → FAILED with no fallback, restart recovery, survival across app instances, and a real-pipeline run with no SerpApi key (honest PARTIAL, HIGH_RISK from the local fee demand). Full backend suite: 634 passed |
| J4 | **DONE** | Upload → claim review (`/offers/:id/review`, backed by `GET /offers/{id}/claims`; uncertain claims must be confirmed or edited; scam-signal claims are read-only) → progress built only from real `RunEvent`s → v1 report. The report shows outcome, coverage counts, per-claim quotes/status/explanation, each evidence record's source kind, tier, relation, retrieval status, URL, time and query, partial-failure errors, and the search trace. No risk or confidence percentages anywhere. The legacy report UI is removed. Samples (`/samples/:key`) render the v1 example payloads under a banner | `npm run build` passes. Browser walkthrough against the live backend: preset → review → progress → report, reload of a stored report, re-run creating v2 alongside v1, sample page, unknown-case 404 |
| J5 | **DONE** | Confirmation panel: the destination comes only from `confirmation_route` and shows its cited evidence. A null route explains how to find the official contact. The editable draft has copy and "open in my email app" actions only (no auto-send) and warns if it mentions OTPs or passwords. Markdown export removes emails, phones and UPI IDs unless the user opts in for a cybercrime complaint (the official destination is kept). Print/save PDF also works | Browser checks of the null-route panel on a live run and the cited route on the impersonation sample. A Markdown export downloaded in the browser had the Gmail and UPI ID removed and the official destination kept |
| J6 | **DONE** | Per-case access token (`X-Case-Token`; hash stored; wrong or missing token gives 404). Uploads are limited to PDF/PNG/JPG/WEBP up to 5 MB and text to 20,000 chars. Candidate identifiers are redacted before investigation. The logger scrubs contacts and keys. `DELETE /offers/{id}` plus 7-day retention purge. Model defaults are aligned across config, both `.env.example` files, compose (now also passes Groq) and render. The frontend API URL is now a real build arg. `python -m app.core.provider_check` tests the configured keys and models | Tests for token isolation, 415/413/400, delete, retention, redaction and log scrubbing. `provider_check` verified to skip unset keys and fail on a bad one. **Not yet run with real keys**; run it before the demo |
| J7 | TODO | | |

Notes for Shriraj:
- `InvestigationResult` reuses `OverallOutcome` and `AuthenticityStatus` from `risk/assessment_models.py`, so the two cannot drift.
- Each `EvidenceRecord` belongs to exactly one claim. When one page supports two claims, emit two records.
- The legacy `VerificationReport` stays the live response shape until J3.


## Evaluation and demonstration

For this two-person sprint, start with 24–30 labeled cases and expand toward 40–60 only after core reliability is stable. Include obvious fee scams, realistic impersonations, lookalike links, legitimate companies, sparse-footprint startups, staffing agencies, no-fee/quoted warnings, OTP theft, ambiguous stipends and provider failures. Use synthetic/redacted examples, disclose their origin and labeling limits, and freeze a held-out portion before tuning. Do not call self-labeled plausible letters employer-authenticated ground truth.

Report false reassurance rate on scam cases, false warning rate on benign cases, abstention rate, claim/source correctness, unsupported-citation rate, latency percentiles and credits per investigation. Compare text-only heuristics against live search + adaptive checks on the same cases, plus fixtures for reproducibility. Include outages and empty search separately. No accuracy claims until measured; confidence labels must not be mistaken for measured probability.

Three-minute demo: 0–20s introduce the fresher's problem; 20–80s investigate a realistic impersonation and show a targeted follow-up resolving a contradiction; 80–120s show a legitimate sparse startup leading to uncertainty rather than accusation; 120–150s show claim evidence and employer-sourced confirmation draft; 150–175s show evaluation results, latency and actual SerpApi use. Clearly identify synthetic examples and recorded fixtures. At least one core investigation should visibly use live SerpApi.

Defer browser extensions, automatic WhatsApp/email integrations, blockchain certificates, large graph infrastructure, many more agents and broad multilingual promises. A simple cross-case identifier lookup can be a later extension after evidence quality and privacy are solved; the current graph stub is not a competitive feature.

## Submission acceptance gate

- No real-case response ever silently becomes a demo fixture.
- Unknown IDs return 404 and reports read stored snapshots.
- Lookalikes, unresolved recruiters, negated fees and explicit OTP demands pass regression probes.
- Sparse footprint and search outage produce honest uncertainty.
- Every asserted external fact has directly supporting retrieved evidence; registry status is not inferred from website existence.
- A follow-up query changes the investigation based on observed evidence.
- Fresh setup, provider configuration and at least one live SerpApi run work.
- README accurately separates implemented, demo-only and future functionality; check the actual model configured by every setup route.
- Public links, video length/local functionality, team details and AI-tool disclosures meet the rules; submit explicitly before the deadline.

Recommendation: retain the product and narrow it around offer-specific impersonation investigation. The competitive opportunity is the quality and transparency of the evidence chain, paired with a practical confirmation action and measured reliability. Winning cannot be predicted without seeing the competing entries; this plan addresses the project's current weaknesses against the published criteria.
