# AsliOffer: Extraction Requirements & Schema Contract (Task 2 Handoff)

**Document Version:** 1.0.0  
**Date:** 3 October 2026  
**Author:** Shriraj (Investigation & Extraction Lane)  
**Recipient:** Jay (Platform, API & Schema Lane)  
**Status:** Frozen Contract Specification for Task J1 / S3  

---

## 1. Executive Summary & Architectural Purpose

This document defines the structured extraction requirements, claim schema models, provenance tracking, and privacy boundaries for AsliOffer. 

As established in [AsliOffer-Competitive-Review.md](file:///c:/Users/dyara/aslioffer/AsliOffer-Competitive-Review.md), the core architectural vulnerability of AsliOffer is confusing a plausible company/recruiter footprint with authentication of the specific offer. Document extraction is the first stage in this chain: **everything parsed from an uploaded offer letter or message is an unverified assertion (a Claim), never ground truth or proof of authenticity.**

By freezing this extraction contract:
1. **Shriraj** can build adaptive investigation logic, domain normalization, and contextual scam reasoners without changing shared database or route schemas.
2. **Jay** can implement versioned Pydantic schemas in `backend/app/schemas/`, database migrations, FastAPI response models, and TypeScript types for the UI.

---

## 2. Analysis of Existing Implementation & Information Loss

### 2.1 Current Models
Currently, the codebase contains two extraction models in [`backend/app/schemas/analysis.py`](file:///c:/Users/dyara/aslioffer/backend/app/schemas/analysis.py):
- `ExtractedData`: Produced by `EntityExtractor.extract_entities()` (Gemini structured extraction or regex fallback).
- `ExtractedEntities`: Backward-compatible legacy model created by `ExtractedData.to_extracted_entities()` and passed to downstream agents and report generators.

### 2.2 Material Gaps & Lost Fields in Existing Code
1. **Adapter Information Loss**: When `to_extracted_entities()` converts `ExtractedData` to `ExtractedEntities`, the following fields are silently discarded:
   - `website`: Official employer website stated in the letter is dropped.
   - `joining_date`: Reported reporting date is dropped.
   - `salary_amount` and `salary_period`: Extracted numeric float (e.g. `7.5`) and unit (e.g. `LPA`) are dropped, collapsing back into a single unparsed string `salary`.
   - `address`: Address is collapsed into `location = self.address or "Remote / India"`.
2. **Lack of Semantic Role Distinction**:
   - `recruiter_email` is extracted using a greedy regex that matches the **first email** in the document. When a student's own email (`@gmail.com`) appears in a `To:` header, it is assigned as the recruiter email, triggering false `PUBLIC_EMAIL_DOMAIN_USED` scam flags against legitimate offers.
3. **Entity Traps**:
   - Mention of communication tooling ("interview via Google Meet / Microsoft Teams / Zoom") frequently traps extractors into classifying "Google" or "Microsoft" as the employer.
4. **Modality Blindness**:
   - Fee detection is purely keyword-driven (`"security deposit" in raw_lower`). Legitimate no-fee policies ("We never charge a security deposit") and quoted anti-scam warnings are falsely classified as `UPFRONT_FEE_DEMAND`.
5. **No Credential Theft Category**:
   - Demands for bank OTPs, account passwords, or banking logins are completely omitted from the schema and detector.
6. **Zero Provenance & Spans**:
   - Neither `ExtractedData` nor `ExtractedEntities` record source quotes, character offsets (`start_offset`, `end_offset`), or page/bounding box references. Downstream reports cannot audit where an extracted fact originated.

---

## 3. Claim-Based Extraction Schema

To eliminate these failure modes, extraction will produce a list of granular, typed `Claim` records.

### 3.1 The `Claim` Object Specification

| Field | Type | Nullable | Allowed Values / Format | Description |
|---|---|---|---|---|
| `claim_id` | `str` | No | `CLM-[0-9]{2,}-[0-9]{2,}` (e.g. `CLM-01-01`) | Stable, unique identifier for the claim within the investigation run. |
| `kind` | `str` | No | Enum (see Section 3.2) | Semantic classification of what kind of fact or demand this claim represents. |
| `value` | `Any` | No | `str`, `float`, `int`, `dict` | Normalized representation of the claim value. |
| `source_quote` | `str` | Yes | Verbatim substring | Exact quote from document text. **Must be `null` for `user_corrected` claims.** |
| `source_span` | `SourceSpan` | Yes | Object or `null` | Zero-based offsets in referenced text. **Must be `null` for `user_corrected` claims.** |
| `extraction_status` | `str` | No | `extracted`, `user_corrected`, `ambiguous`, `inferred` | Lifecycle status of this claim. |
| `confidence_tier` | `str` | No | `HIGH`, `MEDIUM`, `LOW` | Extraction clarity tier. (Never presented as a statistical probability). |
| `attributes` | `dict` | No | Key-value mapping | Kind-specific structured details (e.g. currency, rails, recipient type). |

### 3.2 Supported `ClaimKind` Enum Values

1. `claimed_employer`: Organization named as the hiring entity.
2. `recruiting_agency`: Third-party staffing firm hiring on behalf of a client.
3. `sender_recruiter`: Contact details attributed to the sender/recruiter.
4. `candidate_contact`: Contact details attributed to the job applicant/recipient.
5. `meeting_platform`: Third-party interview tooling (Google Meet, Teams, Zoom).
6. `job_role`: Title or designation of the position.
7. `job_reference_id`: Offer letter reference number or requisition ID.
8. `compensation`: Monetary offer, stipend, salary, or task wages.
9. `payment_request`: Any request for funds, deposits, registration fees, or task unlocking.
10. `credential_request`: Any solicitation of bank OTPs, passwords, PINs, or ID uploads.
11. `interview_url`: Video link or screening test portal.
12. `application_destination`: Web portal or form URL where candidate is directed to register.
13. `official_domain_reference`: Domain cited in footer or body as official company domain.
14. `user_correction`: A field value supplied or adjusted directly by the user.

### 3.3 `SourceSpan` Specification
```json
{
  "start_offset": 169,
  "end_offset": 179,
  "target_text": "raw_text",
  "page_number": null,
  "bounding_box": null
}
```
- `start_offset`: Integer, zero-based, inclusive.
- `end_offset`: Integer, zero-based, exclusive.
- `target_text`: String identifying which text buffer the offsets index (`raw_text` vs `ocr_text` vs `redacted_text`).
- Strict Invariant: `raw_text[start_offset:end_offset] == source_quote`.
- For plain text, `page_number` and `bounding_box` are strictly `null`. For OCR, coordinates are only populated when the vision/OCR engine directly returns bounding boxes; they are **never synthesized or guessed**.

---

## 4. Domain & Category Handling Rules

### 4.1 Employer vs. Agency vs. Platform Disambiguation
- **Platform Mentions**: Software used to conduct interviews (Google Meet, Microsoft Teams, Zoom, Webex, Google Drive, Google Forms) must be labeled `meeting_platform`. They must be stripped from employer extraction candidates to prevent investigating Google or Microsoft instead of the true employer.
- **Recruitment Agencies**: When an agency hires for a client ("ABC Staffing hiring for Wipro"), the extractor must generate two distinct claims:
  - `claimed_employer`: "Wipro"
  - `recruiting_agency`: "ABC Staffing"
  This prevents `RecruiterAgent` from accusing the staffing partner of impersonation simply because their email domain `@abcstaffing.example` differs from `@wipro.com`.
- **Claim vs. Verified Entity**: An extracted company name is merely `claimed_employer`. Authoritative corporate identity (`canonical_domain`, MCA registration) is determined during investigation (Task 4), never during extraction.

### 4.2 Contact Role Separation
- **Recipient vs. Sender**: In email headers (`To:`, `From:`), body greetings ("Dear Sneha... Contact Rahul Verma"), and application footers, the extractor must classify:
  - Recipient email/phone -> `candidate_contact` (`semantic_role: "candidate_destination"`)
  - Sender email/phone -> `sender_recruiter` (`semantic_role: "sender_contact"`)
- Invariant: A candidate's personal `@gmail.com` address must never be assigned as `recruiter_email`, and must never trigger `PUBLIC_EMAIL_DOMAIN_USED`.
- If an email has an ambiguous role, it must be marked `sender_recruiter` with `attributes.semantic_role: "ambiguous"` and surfaced in `unresolved_ambiguities`.

### 4.3 Compensation Parsing & Ambiguity
- Format: Represent compensation with original quote, numeric amount (or range), currency, and frequency period (`ANNUAL`, `MONTHLY`, `HOURLY`, `STIPEND_TOTAL`, `ACCUMULATED_EARNINGS`).
- Ambiguity Rule: If the document states "Stipend: INR 15,000" without indicating frequency:
  - `period` must be set to `null` (not guessed as annual or monthly).
  - `extraction_status` is marked `ambiguous`.
  - An entry is logged in `unresolved_ambiguities`.
  - The UI presents this to the user for interactive confirmation before salary analysis executes.

### 4.4 Payment Demands vs. Negations vs. Quoted Advisories
Every `payment_request` claim must include a `modality` attribute:
1. `active_demand` (`is_active_demand: true`): Candidate is asked to remit funds (e.g. "Pay ₹4,500 laptop deposit via UPI").
2. `negated_policy` (`is_active_demand: false`): Disclaimer stating company does not charge fees (e.g. "We never charge a security deposit").
3. `quoted_advisory` (`is_active_demand: false`): Security warning warning candidates about third-party fraudsters (e.g. "Beware of fraudsters asking for ₹2,500 registration fee").
4. `hypothetical_or_conditional`: Ambiguous wording where money is mentioned in an unrelated context.

### 4.5 Credential & Secret Protection
- **No Secret Retention**: When an offer solicits credentials (bank OTP, net-banking password, debit card PIN):
  - Extractor records `kind: "credential_request"`.
  - `attributes.requested_action: "solicit_credentials"`.
  - `attributes.credential_categories: ["bank_otp", "netbanking_password"]`.
  - `attributes.secret_values_omitted: true`.
  - `attributes.secret_payload: null`.
- Critical Safety Rule: Neither actual OTP numbers, nor sample passwords, nor private applicant PAN/Aadhaar numbers may be stored in attributes, logs, or search payloads.

### 4.6 User Corrections & Attributable Provenance
- User corrections occur when the candidate edits an extracted field in the UI prior to investigation.
- Rules:
  1. A user correction produces a new claim or update with `extraction_status: "user_corrected"`.
  2. `source_quote` and `source_span` must be `null` because the value originated from the user, not the source document.
  3. `attributes.attribution` must record `source: "user_interactive_confirmation"`, timestamp, and target claim ID.
  4. User corrections are never passed off as document quotes.

---

## 5. Field Mapping: Existing vs. Proposed Schema

| Existing Model Field (`ExtractedData` / `ExtractedEntities`) | Proposed Contract Entity & Kind | Destination in Proposed Schema | Disposition / Resolution of Defect |
|---|---|---|---|
| `company` / `company_name` | `Claim(kind='claimed_employer')` | `claims[].value` | Retains raw quote and offsets; strips platform names. |
| *None* (Platform Trap) | `Claim(kind='meeting_platform')` | `claims[].value` | **NEW**: Identifies Google Meet/Teams so it is not analyzed as employer. |
| *None* (Agency) | `Claim(kind='recruiting_agency')` | `claims[].value` | **NEW**: Prevents false impersonation flags for third-party recruiters. |
| `recruiter_name` | `Claim(kind='sender_recruiter')` | `attributes.recruiter_name` | Attributed to recruiter sender role. |
| `recruiter_email` | `Claim(kind='sender_recruiter')` | `claims[].value` | Disambiguated from candidate email. |
| *None* (Candidate Email) | `Claim(kind='candidate_contact')` | `claims[].value` | **NEW**: Preserves candidate email without triggering webmail flags. |
| `recruiter_phone` | `Claim(kind='sender_recruiter')` | `claims[].value` | Tagged with `channel: "phone"`. |
| `job_role` / `role_title` | `Claim(kind='job_role')` | `claims[].value` | Retains exact title quote and offsets. |
| `salary` / `offered_salary` | `Claim(kind='compensation')` | `claims[].value` | Retains exact original string. |
| `salary_amount` (dropped by adapter) | `Claim(kind='compensation')` | `attributes.amount` | **RESCUED**: Preserved as float across all downstream components. |
| `salary_period` (dropped by adapter) | `Claim(kind='compensation')` | `attributes.period` | **RESCUED**: Explicit `ANNUAL`, `MONTHLY`, or `null` if ambiguous. |
| `joining_date` (dropped by adapter) | `Claim(kind='joining_date')` | `claims[].value` | **RESCUED**: Retains date string for timeline checks. |
| `address` (flattened by adapter) | `Claim(kind='location')` | `claims[].value` | **RESCUED**: Preserves raw address quote; no dummy `"Remote / India"`. |
| `website` (dropped by adapter) | `Claim(kind='official_domain_reference')` | `claims[].value` | **RESCUED**: Document-stated website preserved as claim for investigation. |
| `payment_amount`, `payment_method` | `Claim(kind='payment_request')` | `attributes.amount`, `attributes.payment_method` | Decomposed with modality (`active_demand` vs `negated_policy`). |
| *None* (Payment Recipient) | `Claim(kind='payment_request')` | `attributes.recipient` | **NEW**: Captures UPI ID (`hr@okaxis`) or bank account number. |
| *None* (OTP / Password Demands) | `Claim(kind='credential_request')` | `claims[].value` | **NEW**: Grounded signal for financial credential theft. |
| *None* (Provenance Spans) | `SourceSpan` | `claims[].source_span` | **NEW**: Start/end offsets indexing exact text quotes. |

---

## 6. Privacy & Redaction Boundaries

Untrusted user documents contain sensitive personal and financial identifiers. The pipeline enforces four strict privacy isolation boundaries:

```
[Uploaded Document] 
       │ (1. Raw text in-memory only)
       ▼
 [Redaction Engine] ──────▶ [Redacted Text Snapshot]
       │                            │
       │ (2. Only stripped claims)   │ (3. Verified Safe Queries Only)
       ▼                            ▼
[LLM Structured Extractor]    [SerpApi External Search]
```

### 6.1 Privacy Data Classifications

| Data Element | Internal Engine | Stored DB Snapshot | User Frontend | LLM Extractor | SerpApi External Search |
|---|---|---|---|---|---|
| Raw Document Text | Yes (in-memory) | Encrypted / Opt-in | Viewable by owner | Yes (truncated) | **NEVER** |
| Redacted Document Text | Yes | Yes | Yes | Yes | **NEVER** |
| Claimed Employer Name | Yes | Yes | Yes | Yes | **YES** (quoted query) |
| Recruiter Corporate Email | Yes | Yes | Yes | Yes | **Domain only** (`@domain.com`) |
| Recruiter Phone Number | Yes | Yes | Yes | Yes | **YES** (with user consent) |
| Candidate Name & Email | Yes | Redacted/Masked | Masked to owner | Redacted | **NEVER** |
| Payment Recipient (UPI ID) | Yes | Yes | Yes | Yes | **YES** (reputation check) |
| Bank OTP / Password values | **NEVER** | **NEVER** | **NEVER** | **NEVER** | **NEVER** |
| Live API Keys / Auth Tokens| **NEVER** | **NEVER** | **NEVER** | **NEVER** | **NEVER** |

### 6.2 Redaction and Provenance Survival
- Redaction replaces sensitive candidate personal data with tokens: `[CANDIDATE_NAME]`, `[CANDIDATE_EMAIL]`, `[PHONE_REDACTED]`.
- Provenance spans (`start_offset`, `end_offset`) index the **original raw text** during initial extraction.
- If a redacted text view is displayed, a character offset mapping table (`OriginalToRedactedOffsetMap`) translates coordinates so UI highlight overlays do not drift.
- Search queries are constructed **exclusively from structured entity attributes** (e.g. `f'"{company_name}" official website careers'`). The raw text of the letter is **never sent to search engines**.

---

## 7. Requests and Invariants for Jay (Platform & Schema Lane)

As agreed in the two-person plan, Jay is the sole owner of Python models in `backend/app/schemas/` and wire contracts in `frontend/src/types/index.ts`. Shriraj requests the following additions and compatibility boundaries for Task J1:

### 7.1 Schema Additions Requested
1. **`Claim` Model**: Implement `Claim`, `SourceSpan`, and `ClaimKind` in `backend/app/schemas/investigation.py` matching Section 3.
2. **Preserve Dropped Fields**: In `ExtractedData` and any shared wire types, preserve `website`, `joining_date`, `salary_amount`, `salary_period`, and `payment_recipient`.
3. **Editable Claims Wire Model**:
   - The response for `POST /offers/upload` should return `{ offer_id, raw_text, claims: List[Claim], ambiguities: List[str] }` so the frontend can render an interactive confirmation card before investigation starts.
4. **Investigation Hand-off Result (`InvestigationResult`)**:
   - Matches proposed contract in `AsliOffer-Competitive-Review.md` line 140:
     `InvestigationResult(contract_version, run_id, claims, evidence, overall_outcome, authenticity_status, coverage, recommended_actions, tool_trace, errors)`.
   - `overall_outcome` must be one of: `HIGH_RISK`, `NEEDS_REVIEW`, `CANNOT_VERIFY`, `NO_STRONG_RISK_SIGNALS`.
   - `authenticity_status` defaults to `UNCONFIRMED` without direct employer confirmation.
5. **No Synthetic Risk Percentage**:
   - Suppress `risk_score` as a calibrated probability. Retain only for backward compatibility if needed, but display risk tiers (`RiskLevel`) and coverage indicators.

### 7.2 Open Compatibility Questions for Jay
1. **Database Persistence**: Does Jay prefer persisting `claims` as a JSON column in `offers` / `runs` table, or as a normalized `claims` relational table? (Shriraj recommendation: JSON column `claims` in SQLite/Postgres for sprint velocity).
2. **Backward Compatibility Adapter**: Should `EntityExtractor.extract()` continue to output `ExtractedEntities` for legacy tests while `extract_claims()` outputs `List[Claim]`, or should `ExtractedData` carry a `.to_claims()` method? (Shriraj can implement `.to_claims()` on `ExtractedData`).

---

## 8. Reference Examples (Fixture Artifacts)

Six comprehensive, validated JSON fixtures are committed under [`backend/tests/fixtures/investigation/extraction_contract/`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract):

| Example ID | File | Scenario & Purpose |
|---|---|---|
| `EXTRACT-EX-01` | [`example_01_candidate_before_recruiter_email.json`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract/example_01_candidate_before_recruiter_email.json) | Candidate email (`sneha.student@gmail.com`) appears before recruiter corporate email (`talent.acquisition@tata-elxsi.example`). Demonstrates semantic role assignment. |
| `EXTRACT-EX-02` | [`example_02_platform_mention_vs_employer.json`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract/example_02_platform_mention_vs_employer.json) | V-Guard Industries offer mentions interview on Google Meet. Demonstrates entity disambiguation between employer and video platform. |
| `EXTRACT-EX-03` | [`example_03_no_fee_policy_and_quoted_warning.json`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract/example_03_no_fee_policy_and_quoted_warning.json) | Policy says "We never charge a security deposit" + advisory says "Beware of fake letters asking for ₹2,500 fee". Demonstrates `negated_policy` and `quoted_advisory` modalities. |
| `EXTRACT-EX-04` | [`example_04_explicit_fee_demand_with_recipient.json`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract/example_04_explicit_fee_demand_with_recipient.json) | Mandatory ₹4,500 laptop deposit demanded via UPI ID `hr-deposit@okaxis`. Demonstrates payment decomposition with recipient identifier. |
| `EXTRACT-EX-05` | [`example_05_explicit_credential_demand_secrets_omitted.json`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract/example_05_explicit_credential_demand_secrets_omitted.json) | Recruiter message solicits bank OTP and net-banking password. Demonstrates credential theft detection with secret values strictly omitted. |
| `EXTRACT-EX-06` | [`example_06_ambiguous_compensation_unresolved_employer.json`](file:///c:/Users/dyara/aslioffer/backend/tests/fixtures/investigation/extraction_contract/example_06_ambiguous_compensation_unresolved_employer.json) | "Stipend: INR 15,000" with unspecified frequency and unconfirmed startup. Demonstrates non-guessing ambiguity and user correction attribution. |

---

## 9. Acceptance Criteria for Task 3 Implementation

When implementing the updated extraction pipeline in Task 3:
1. **Contact Role Integrity**: In messages with multiple emails, `candidate_contact` and `sender_recruiter` are never conflated.
2. **Zero Platform Conflation**: Meeting platforms (Google Meet, Microsoft Teams, Zoom) never displace the claimed employer.
3. **Zero False Positives on Negated Fees**: Offers containing "never charge fees" or quoted scam warnings pass with `is_active_demand: false`.
4. **100% Offset Accuracy**: For text inputs, `raw_text[start:end] == source_quote` for all generated claims.
5. **Credential Safety**: Demands for OTPs or passwords trigger `credential_request` flags while keeping secret values null.
6. **No Fake Probabilities**: Confidence tiers (`HIGH`, `MEDIUM`, `LOW`) describe evidence clarity; no uncalibrated percentages are produced.
7. **Offline Deterministic Fallback**: In the absence of live Gemini credentials, regex/heuristic parsing successfully generates the structured `Claim` list.
