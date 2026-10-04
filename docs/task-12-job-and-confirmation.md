# Task 12: Job/Application Corroboration & Independently Sourced Offer-Confirmation Routes

## Overview

Task 12 enhances the AsliOffer unified investigation pipeline by answering two bounded questions:
1. **Do independent public records corroborate the claimed job and application destination?**
2. **Is there an independently sourced channel through which the candidate can ask the employer whether this specific offer was issued?**

A matching vacancy or careers portal does not authenticate an individual employment offer. Authenticity status remains strictly `UNCONFIRMED`.

---

## 1. Focused Corroboration Service (`corroborator.py`)

Rather than adding a second general pipeline, search client, scoring engine, or wire contract, Task 12 creates a focused internal module:
`backend/app/services/investigation/corroborator.py`.

### Components
- `JobCorroborationService`: Orchestrates conservative evaluation of job role, location, requisition ID, application destination, and confirmation route discovery.
- `JobCorroborationResult`: Structured internal container carrying observations, executed/failed checks, and an optional evidence-grounded `ConfirmationRoute`.
- `CorroborationObservation`: Claim-specific evaluation carrying claim ID, status (`SUPPORTED`, `UNRESOLVED`, `CONTRADICTED`, `NOT_CHECKED`), reason codes, explanation, and attributable evidence items.
- Utility functions: `normalize_job_title()`, `is_public_job_reference()`, `evaluate_application_destination()`, and `generate_confirmation_draft()`.

### Pipeline Integration
Integrated into `investigate_case()` in `backend/app/services/investigation/pipeline.py`:
- Executed after initial agent checks (Company, Recruiter, Scam, Salary) and adaptive planner follow-ups.
- Consumes all recorded search observations (`snippets_by_url`), company identity, and resolved employer/careers domain.
- Adapts observations to contract-v1 `EvidenceRecord` models with exact query/engine/timestamp provenance.
- Removes the unconditional `CORROBORATION_DEFERRED` branch in `ClaimAssessor` for checked claims (`ROLE`, `LOCATION`, `JOB_REFERENCE`, `APPLICATION_URL`).

---

## 2. Bounded Query Strategies & Budget Priorities

Task 12 extends `InvestigationPlanner` (`planner.py`) with three targeted strategies:

| Strategy | Priority | Max Calls | Rationale / Prompt String | Condition |
| :--- | :---: | :---: | :--- | :--- |
| `JOB_ROLE_CORROBORATION` | 5 | 1 | `"Checking the claimed role against established employer careers sources."` | Grounded usable role claim + resolved canonical domain/ATS tenant |
| `JOB_REFERENCE_CORROBORATION` | 5 | 1 | `"Checking the claimed requisition reference against established employer careers sources."` | Grounded usable reference + passes `is_public_job_reference()` |
| `CONFIRMATION_ROUTE_DISCOVERY` | 6 | 1 | `"Looking for employer-published guidance for confirming offer issuance."` | Grounded role or ref claim + no direct official email/phone confirmed |

### Safety & Abstention Rules
- **Private References:** Offer letters frequently include candidate-specific references (e.g., `OFFER/2026/4102`, `OL-BLR-092`, UUIDs, candidate IDs). `is_public_job_reference()` strictly classifies them as private, suppressing external search to protect candidate privacy.
- **Uncertain / Redacted Inputs:** Values marked `UNCERTAIN`, `MISSING`, or containing redaction placeholders (`[REDACTED_...]`) are never queried.
- **Sensitive Secrets:** Candidate identities, signed URL parameters, OTPs, and private tokens are strictly excluded from queries and search traces.
- **Budget Respect:** Follow-ups draw directly from the single shared `InvestigationBudget`. When capacity is reached or the monotonic deadline expires, checks skip cleanly.

---

## 3. Claim Matching & Corroboration Rules

Each claim is evaluated individually; one job posting may provide separate evidence records for distinct claims.

### ROLE (`c6`)
- **Support Criteria:** Requires attributable hiring records from the official employer domain or an established employer ATS tenant containing a contiguous whole-token role match in a public hiring record. Closed, expired, filled and explicitly non-hiring records cannot support an open vacancy.
- **Conservative Normalization (`normalize_job_title`):** Normalizes punctuation, known formatting labels such as `(m/f/d)` and common abbreviations (`sr`/`jr`). Preserves seniority, specialization and meaningful parenthetical levels; an intern listing does not corroborate a senior position. Snippets establish a public listing observation, not current availability.
- **Unresolved Semantics:** A completed relevant check without a match remains `UNRESOLVED` (`VACANCY_NOT_FOUND`, `NO_MATCHING_VACANCY`). Skipped or budget-denied checks are `NOT_CHECKED`; failed targeted searches remain unresolved with `SEARCH_UNAVAILABLE`. None proves fraud.

### LOCATION (`c7`)
- **Support Criteria:** Supported *only* when the corroborated vacancy or specific hiring record names the claimed city/region.
- **Headquarters Exclusion:** Mentions of employer corporate headquarters, registered office, or corporate campus alone do *not* corroborate a job location claim (`HEADQUARTERS_ONLY_NOT_JOB_LOCATION`).
- **Remote / Hybrid:** Remote and hybrid descriptions are not interpreted as arbitrary city matches.

### JOB_REFERENCE (`c8`)
- **Public vs. Private:** Requires an exact attributable public requisition match on an employer-controlled or associated ATS source.
- **Abstention on Private References:** Private or ambiguous codes remain `NOT_CHECKED` (`NOT_PUBLIC_REQUISITION`). Bare numbers and generic ID/REF prefixes are not public search candidates. Candidate/offer-reference context overrides a public-looking code. An eligible syntax is permission to check a candidate public requisition, not proof of its public provenance.
- **No False Contradiction:** A different reference number in search results does not contradict the claim, nor does it imply an internal ATS offer-verification API exists.

### APPLICATION_URL (`c5`)
- **Separation of Destination and Form:** An employer-domain URL proves domain association without proving that its specific path is a valid job application or verification page.
- **Strong Support:** Requires observed public records identifying that specific destination path or an established employer ATS tenant.
- **Lookalike & Credential URLs:** Lookalike domains or URLs with embedded credentials/unsafe schemes return `CONTRADICTED` (`SUSPECTED_LOOKALIKE_DESTINATION`, `MALFORMED_OR_CREDENTIAL_URL`).
- **Unresolved Third-Party:** General job boards or unassociated external domains remain `UNRESOLVED` without automatically triggering `HIGH_RISK`.

---

## 4. Conservative Hosted ATS Tenant Handling

Reuses `DomainResolver` safe parsing and tenant extraction (`DomainResolver.is_hosted_careers_platform` and `_is_associated_hosted_careers`):

- **Established ATS Tenant:** A hosted careers platform (e.g. `wipro.wd3.myworkdayjobs.com`, `tcs.taleo.net`, `acme.greenhouse.io`, `acme.lever.co`) must match the employer identity and be associated through an independently retrieved employer-domain record publishing the resolved careers link. A similarly spelled tenant and an ATS search result alone are insufficient. Association is restricted to that published portal path, including its child job pages.
- **Honest Source Tier:** ATS platforms are classified as `SourceTier.ESTABLISHED_THIRD_PARTY` with documented employer association; they are *never* mislabeled `OFFICIAL_EMPLOYER` simply to satisfy a filter.
- **Unrelated ATS Tenants:** An ATS platform hosting an unrelated company remains `UNRESOLVED` (`UNRELATED_ATS_TENANT`).
- **Untrusted Plausibility:** Familiar ATS hostnames without verified tenants, embedded company names in arbitrary query parameters, or lookalike subdomains are rejected.

---

## 5. Independently Sourced Offer-Confirmation Routes

`JobCorroborationService` discovers independent verification routes based strictly on retrieved live search snippets:

### Selection Hierarchy (Deterministic Priority)
1. **Dedicated Verification Channel (`official_email`):** Employer-published email dedicated to hiring verification (e.g., `careers@`, `recruitment@`, `talent@`, `verify@`, `offer-verification@`).
2. **Official Recruitment Phone (`official_phone`):** Dedicated recruitment switchboard published on employer domain.
3. **Careers Portal (`careers_portal`):** An observed official careers URL or independently associated ATS portal. The draft instructs the candidate to find published recruitment contacts; it does not claim an offer-verification API exists.

### Evidence & Provenance Requirements
- A route **must cite the exact retrieved observation** that published the destination and its purpose. Another snippet at the same URL cannot substitute for it. Original title/snippet/query/engine/search ID/time are retained; generated assessment explanations are never promoted into search citations.
- Channels are chosen deterministically by type, destination and source observation. Negative contact instructions, personal mailbox substring matches and ATS-published email/phone contacts are excluded. An unobserved careers URL cannot become a fallback route.
- **Prohibited:** Inventing `hr@company.com`, reusing submitted-only recruiter contacts without independent publication, promoting generic homepage URLs into HR contacts, or treating profile pages as employer authorization.
- **DEMO Isolation:** Observations with `RetrievalStatus.DEMO` never yield a production confirmation route.
- If no route meets evidence requirements, `confirmation_route=None`.

### Restrained Neutral Confirmation Draft (`draft_message`)
When a supported route exists, `draft_message` provides a neutral, template inquiry:
- Inquires whether the employer issued the specific offer and authorized the contacting recruiter.
- Cites non-sensitive context (role title, public requisition if verified).
- Uses safe placeholders (`[Your Full Name]`, `[Your Phone Number]`, `[Candidate/Offer Reference]`) that the candidate must manually review and fill.
- Contains zero OTPs, bank details, credentials, or sensitive secrets.
- Avoids accusations of fraud against the employer or recruiter.
- Strictly for user review; no automated dispatch or network calls.

---

## 6. Coverage & Recommendation Integration

- **Coverage Accounting:** Checked claims (`checked_claims`) count completed relevant searches or actual attributable records evaluated for that claim, even when the result is unresolved. Local unsafe-URL analysis is counted separately through the same executed-check set. Missing values, skipped queries, budget denials and failed searches do not inflate checked coverage. A partial provider outage does not erase already retrieved claim-specific evidence.
- **Outcome Precedence Preserved:** Vacancy corroboration does not erase upfront fee warnings, credential theft demands, adverse reports, recruiter domain mismatches, or provider outages.
- **Deterministic Recommendations:** Recommendations distinguish between:
  - Found job corroboration.
  - Unresolved vacancy, job reference, or application destination.
  - Supported confirmation route with draft message.
  - Absence of an independently sourced verification route.
  - Provider or budget limitations.

---

## 7. Frontend Handoff for Jay

For Jay's UI and frontend integration:
- `InvestigationResult.confirmation_route`: Optional `ConfirmationRoute` model containing:
  - `channel`: `"official_email" | "official_phone" | "careers_portal"`
  - `destination`: URL, email address, or phone number.
  - `evidence_id`: ID of the attributable `EvidenceRecord` proving this channel.
  - `draft_message`: Ready-to-review neutral verification inquiry with safe placeholders.
- `InvestigationResult.assessed_claims`:
  - `ROLE` (`c6`), `LOCATION` (`c7`), `JOB_REFERENCE` (`c8`), and `APPLICATION_URL` (`c5`) now return real claim assessments (`SUPPORTED`, `UNRESOLVED`, `CONTRADICTED`, `NOT_CHECKED`) citing attributable evidence when available. Unsupported proposed support/contradiction is downgraded with an unresolved explanation and `NO_ATTRIBUTABLE_CITATION`.
- Authenticity status remains strictly `UNCONFIRMED`.

---

## 8. Handoff Fixtures

Four validated contract-v1 handoff fixtures are generated in `backend/tests/fixtures/investigation/generated_task12/`:
1. `fixture_corroborated_with_route.json`: Corroborated vacancy with supported confirmation route and draft message.
2. `fixture_unresolved_no_route.json`: Unresolved vacancy with unlisted postings and no independent confirmation route (`confirmation_route=None`).
3. `fixture_associated_ats_destination.json`: Corroborated application link directing to an established Workday ATS tenant.
4. `fixture_local_warning_with_vacancy.json`: Strong upfront fee demand (`HIGH_RISK`) preserving safety warnings despite a matching public vacancy.

## 9. Cleanup validation

Run from the repository root:

```bash
python -m pytest backend/tests/ -q
```

`test_task12_cleanup.py` covers false role/seniority matches, closed postings, exact requisition boundaries, unrelated employers, ATS publication requirements, private reference context, source tiers, confirmation citation binding, private draft fields, and denied/failed checks. Existing strong-warning and recruiter-uncertainty tests continue to protect prior outcomes.

Fixture generation tests write exclusively under pytest's temporary directory. The four committed samples are independently validated as contract-v1 fixtures; ordinary tests do not overwrite them. Confirmation drafts remain review-only and never send messages. No route, persistence, frontend, or wire-schema changes are required for this cleanup.
