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
- **Support Criteria:** Requires attributable hiring records from the official employer domain or an established employer ATS tenant containing the core role tokens.
- **Conservative Normalization (`normalize_job_title`):** Strips parentheticals `(m/f/d)`, punctuation, and seniority modifiers (`senior`, `jr`, `lead`, `associate`, `intern`, `trainee`, `graduate`) to compare core functional disciplines without broad fuzzy matching that would falsely equate different professions (e.g., Frontend Developer vs. Backend Engineer).
- **Unresolved Semantics:** Unlisted or expired postings remain `UNRESOLVED` (`VACANCY_NOT_FOUND`, `UNLISTED_OR_EXPIRED`, `NO_MATCHING_VACANCY`), never proof of fraud.

### LOCATION (`c7`)
- **Support Criteria:** Supported *only* when the corroborated vacancy or specific hiring record names the claimed city/region.
- **Headquarters Exclusion:** Mentions of employer corporate headquarters, registered office, or corporate campus alone do *not* corroborate a job location claim (`HEADQUARTERS_ONLY_NOT_JOB_LOCATION`).
- **Remote / Hybrid:** Remote and hybrid descriptions are not interpreted as arbitrary city matches.

### JOB_REFERENCE (`c8`)
- **Public vs. Private:** Requires an exact attributable public requisition match on an employer-controlled or associated ATS source.
- **Abstention on Private References:** Private offer codes remain `NOT_CHECKED` / `UNRESOLVED` (`PRIVATE_OFFER_REFERENCE`).
- **No False Contradiction:** A different reference number in search results does not contradict the claim, nor does it imply an internal ATS offer-verification API exists.

### APPLICATION_URL (`c5`)
- **Separation of Destination and Form:** An employer-domain URL proves domain association without proving that its specific path is a valid job application or verification page.
- **Strong Support:** Requires observed public records identifying that specific destination path or an established employer ATS tenant.
- **Lookalike & Credential URLs:** Lookalike domains or URLs with embedded credentials/unsafe schemes return `CONTRADICTED` (`SUSPECTED_LOOKALIKE_DESTINATION`, `MALFORMED_OR_CREDENTIAL_URL`).
- **Unresolved Third-Party:** General job boards or unassociated external domains remain `UNRESOLVED` without automatically triggering `HIGH_RISK`.

---

## 4. Conservative Hosted ATS Tenant Handling

Reuses `DomainResolver` safe parsing and tenant extraction (`DomainResolver.is_hosted_careers_platform` and `_is_associated_hosted_careers`):

- **Established ATS Tenant:** A hosted careers platform (e.g. `wipro.wd3.myworkdayjobs.com`, `tcs.taleo.net`, `acme.greenhouse.io`, `acme.lever.co`) is verified against the employer identity.
- **Honest Source Tier:** ATS platforms are classified as `SourceTier.ESTABLISHED_THIRD_PARTY` with documented employer association; they are *never* mislabeled `OFFICIAL_EMPLOYER` simply to satisfy a filter.
- **Unrelated ATS Tenants:** An ATS platform hosting an unrelated company remains `UNRESOLVED` (`UNRELATED_ATS_TENANT`).
- **Untrusted Plausibility:** Familiar ATS hostnames without verified tenants, embedded company names in arbitrary query parameters, or lookalike subdomains are rejected.

---

## 5. Independently Sourced Offer-Confirmation Routes

`JobCorroborationService` discovers independent verification routes based strictly on retrieved live search snippets:

### Selection Hierarchy (Deterministic Priority)
1. **Dedicated Verification Channel (`official_email`):** Employer-published email dedicated to hiring verification (e.g., `careers@`, `recruitment@`, `talent@`, `verify@`, `offer-verification@`).
2. **Official Recruitment Phone (`official_phone`):** Dedicated recruitment switchboard published on employer domain.
3. **Established ATS Portal (`ats_portal`):** Verified ATS tenant careers portal for the employer.
4. **General Careers Portal (`careers_portal`):** General official careers portal URL.

### Evidence & Provenance Requirements
- A route **must cite a real `EvidenceRecord`** retrieved in this run that actually published the destination and its purpose.
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

- **Coverage Accounting:** Checked claims (`checked_claims`) count completed corroborated checks even when the vacancy is unresolved. Missing values, skipped queries, and budget denials do not inflate checked coverage.
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
  - `route_type`: `"official_email" | "official_phone" | "careers_portal" | "ats_portal"`
  - `destination`: URL, email address, or phone number.
  - `evidence_id`: ID of the attributable `EvidenceRecord` proving this channel.
  - `instructions`: Clear guidance on how to reach out independently.
  - `draft_message`: Ready-to-review neutral verification inquiry with safe placeholders.
- `InvestigationResult.assessed_claims`:
  - `ROLE` (`c6`), `LOCATION` (`c7`), `JOB_REFERENCE` (`c8`), and `APPLICATION_URL` (`c5`) now return real claim assessments (`SUPPORTED`, `UNRESOLVED`, `CONTRADICTED`) citing specific evidence IDs.
- Authenticity status remains strictly `UNCONFIRMED`.

---

## 8. Handoff Fixtures

Four validated contract-v1 handoff fixtures are generated in `backend/tests/fixtures/investigation/generated_task12/`:
1. `fixture_corroborated_with_route.json`: Corroborated vacancy with supported confirmation route and draft message.
2. `fixture_unresolved_no_route.json`: Unresolved vacancy with unlisted postings and no independent confirmation route (`confirmation_route=None`).
3. `fixture_associated_ats_destination.json`: Corroborated application link directing to an established Workday ATS tenant.
4. `fixture_local_warning_with_vacancy.json`: Strong upfront fee demand (`HIGH_RISK`) preserving safety warnings despite a matching public vacancy.
