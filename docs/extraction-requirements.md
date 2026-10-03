# AsliOffer extraction requirements: Task 2 handoff

Version **1.0.1**, 3 October 2026. **Proposed contract, pending agreement with Jay.**

Shriraj owns extraction/investigation services; Jay owns shared Python schemas,
API models, persistence and frontend types. This document specifies later
extraction implementation; **Task 3 remains search failure handling**. No
application implementation or shared schema changes are part of this task.

The repository's [architecture](architecture.md) describes the current pipeline.
Treat every document-derived field as an unverified claim. Employer identity,
recruiter affiliation, official-domain ownership and public footprint are assessed
by investigation, never inferred by extraction. A stated corporate email is not
authenticated sender-origin evidence. Sample outcomes are contract requirements,
not evidence that the current application satisfies them.

## Existing-field migration

| Existing field | Proposed claim/attribute | Required migration |
|---|---|---|
| company / company_name | claimed_employer.value | Preserve candidates; never substitute meeting platforms |
| recruiter_name | sender_recruiter.attributes.recruiter_name | Use attributed source context |
| recruiter_email / recruiter_phone | contact or sender_recruiter | Extract every contact; assign roles only with supporting context |
| job_role / role_title | job_role.value | Preserve source wording |
| website | official_domain_reference.value | Currently dropped by adapter; preserve as claimed URL |
| joining_date | joining_date.value | Currently dropped; normalize date only when unambiguous |
| address / location | location.value | Preserve address; remove invented Remote / India default |
| salary / offered_salary | compensation.value | Original amount text retained |
| salary_amount / salary_period | compensation.attributes | Currently dropped; convert to base currency units and explicit period |
| payment_amount / payment_method | payment_request.attributes | Actor/action/recipient/purpose/modality retained |
| No existing equivalent | recruiting_agency, candidate_contact, meeting_platform, job_reference_id, application_destination, credential_request | New extraction claims |

## Envelope and claim definitions

Example envelope: contract_version, example_id, title, description, synthetic=true,
raw_text, optional ocr_text/redacted_text and extraction. Extraction contains
source_type (`text`, `email`, `pdf`, `screenshot`), extraction_method (runtime:
`regex`, `model`, `ocr_model`, `hybrid`; examples: `contract_example`), claims,
unresolved_ambiguities and warnings. Each ambiguity references an existing claim
and field; each warning has code/message. Missing information is not verified.

| Claim field | Type / nullability | Semantics |
|---|---|---|
| claim_id | Nonempty string, CLM-number-number | Unique within run; references remain stable |
| kind | Enum below | Semantic claim category |
| value | String/number/object; null only for absent claim | Claimed or user-supplied value; never verified identity |
| source_quote | String or null | Verbatim substring of the identified sanitized source buffer |
| source_span | Object or null | Optional located provenance; not required when only a quote is available |
| extraction_status | extracted / ambiguous / absent / user_corrected | Ambiguity stays explicit; no unsupported inferred facts |
| confidence_tier | HIGH / MEDIUM / LOW / null | Extraction clarity only, not probability; null for absent fields |
| attributes | Object | Kind-specific fields below |

Kinds: `claimed_employer`, `recruiting_agency`, `sender_recruiter`,
`candidate_contact`, `contact`, `meeting_platform`, `job_role`, `job_reference_id`,
`location`, `joining_date`, `compensation`, `payment_request`, `credential_request`,
`interview_url`, `application_destination`, `official_domain_reference`,
`user_correction`.

Absent fields can be omitted or represented explicitly with status=absent,
value=null, quote/span=null and confidence_tier=null. Do not invent defaults.
Ambiguous employer candidates may coexist; attributes.candidate_group links them,
and an ambiguity records that selection is unresolved. Unknown contact role uses
kind=contact and semantic_role=unknown, never sender_recruiter by default.

## Kind-specific fields and interpretation

Contacts: channel=email/phone, semantic_role=sender_contact/candidate_destination/
recruiter_contact/employer_reference/unknown. Candidate personal email must not
trigger recruiter-webmail checks. Document headers state claimed sender identity;
authenticated delivery evidence, if ever supplied, is a separate investigation
input. Software names used as tools stay meeting_platform; do not globally strip
those names when the software company actually is the claimed employer.

Compensation attributes: amount (number/null), amount_range (two ordered numbers/
null), amount_unit=`currency_base_unit`, currency (ISO currency string/null),
period (`ANNUAL`, `MONTHLY`, `HOURLY`, `DAILY`, `TOTAL`, or null), pay_type
(`salary`, `stipend`, `bonus`, `accumulated_earnings`, `unknown`). INR 7.2 LPA
becomes amount=720000, currency=INR, period=ANNUAL; original text stays in value
and source_quote. “CTC INR 7,50,000” and “Stipend INR 15,000” do not explicitly
state frequency: period=null, status=ambiguous. CTC alone is not a period. A
currency symbol with multiple possible currencies remains ambiguous. Unknown
range endpoints remain null rather than made-up bounds. Accumulated earnings
are a pay_type, not a payment period. Monetary amounts are not probabilities.

Joining dates: retain original text; optional attributes.normalized_date is an
ISO date or null. Resolve ambiguous date formats via user confirmation, not a
locale guess. Location retains original place/address with no default country.

Payment requests: modality=`active_demand`, `negated_policy`, `quoted_advisory`,
`hypothetical_or_conditional`, `ambiguous`; is_active_demand=true/false/null.
Active demand is true; negated policy and advisory are false; ambiguous wording
is null. Include requested_action, actor, recipient, recipient_type, amount,
currency, payment_method, purpose and urgency when grounded; unknown fields are
null. Money units use base currency units. Preserve the surrounding demand
context, not just a fee keyword. A conditional requirement to pay to receive an
offer/withdraw wages is an active demand; “conditional” must not conceal it.

Credential requests use the same modality rules and include requested_action,
actor, recipient, credential_categories, stated_pretext,
secret_values_omitted=true and secret_payload=null. OTP/password/PIN/bank-login
solicitation differs from an ordinary ID-document request. Record ID-document
requests with requested_action=request_identity_document and a separate category;
do not automatically classify routine onboarding document submission as theft.
Actual secret values must not be retained in any claims, quotes or outputs.

## Provenance, OCR and corrections

SourceSpan fields: start_offset/end_offset are nullable integers, target_text is
raw_text/ocr_text/redacted_text, page_number and bounding_box are nullable.
Text offsets, if supplied, are zero-based, inclusive start/exclusive end, measured
in **Unicode code points**, before no further normalization. JavaScript UTF-16
indices must be converted before highlighting. The selected named buffer slice
must exactly equal source_quote. Define a new buffer/version if normalization
changes its contents. Quote-only provenance is allowed when reliable offsets
are unavailable; do not fabricate a position.

OCR offsets locate text in the OCR buffer, not coordinates in a PDF/image.
Page and bounding-box fields are null unless returned with trustworthy OCR
metadata; coordinates must identify their units and source image/page dimensions.
Never guess coordinates or page numbers from text. Plain text has neither.

A user correction is a new user_correction claim with status=user_corrected,
quote/span=null. Attributes include target_claim_id, corrected_field,
corrected_value and attribution containing source=user_interactive_confirmation,
timestamp (ISO-8601 timezone specified) and target_claim_id. Target must exist
and may not be the correction itself. Preserve original claim and correction;
consumer computes effective value without replacing original document evidence.
User confirmation does not independently authenticate the employer. Resolved
corrections can close a field ambiguity, retaining its audit history.

## Privacy boundary and redaction

One policy applies consistently: **raw unredacted documents/text are local,
transient inputs; model/API/front-end report outputs use sanitized buffers.**
Do not return raw_text in upload responses. Return redacted_text, claims,
ambiguities, warnings, contract_version and offer_id. The example raw_text is
synthetic input data, not a proposed public API field.

| Data | Internal | Stored / frontend | Model | Search |
|---|---|---|---|---|
| Original document/text | Transient local input | No by default | No | Never |
| Sanitized OCR/redacted text | Yes | Case-owner access only | Yes | Never wholesale |
| Employer/role/location | Yes | Yes | Yes | Relevant structured terms |
| Recruiter custom-domain email | Yes | Owner-visible | As needed | Domain only by default |
| Recruiter phone | Yes | Owner-visible or masked | Mask unless needed | Only explicit consent |
| Candidate contact/IDs | Local redaction only | Masked | Masked | Never |
| Payment recipient | Yes | Mask where appropriate | As needed | Only explicit consent for exact-identifier search |
| OTP/password/token values | Redactor may encounter input | Never retain | Never | Never |

Redact before external model processing, including source_quote and warning text.
For screenshots/PDFs, prefer local text/OCR; do not send unsanitized binaries to
vision as an automatic fallback. If privacy-preserving local handling is not yet
implemented, return a clear unsupported/consent-required state and allow pasted
redacted text. Any explicitly approved external document processing is a future
separate flow with disclosed provider/retention, not an exception hidden here.

Transient raw-to-redacted mappings stay internal. Persist provenance in the
sanitized buffer so stored quotes do not leak removed identifiers. Candidate
contact detection can originate locally and emit a masked candidate_contact
claim. A raw_text span is allowed internally/in synthetic fixtures only when its
quote contains no sensitive material. No raw offset map or raw secret appears in
public responses. Examples 7–8 show Unicode and sanitized OCR references.

## Handoff to Jay and compatibility decisions

No committed docs/api-contract.md was present at the inspected Task 2 base.
These names are proposals, not unilateral freezing of the shared wire schema.
Jay implements Claim/SourceSpan/enums in backend/app/schemas; Shriraj implements
service adapters using the agreed models, not methods added to Jay-owned files.

1. Agree kind/status enums, unit convention and source-buffer identity first.
2. Jay publishes matching Python/TypeScript schemas and versioned payload examples.
3. Retain legacy ExtractedEntities temporarily if tests/routes need it; its adapter
   must not upgrade ambiguous contacts or fabricate default location/period.
4. Keep compensation base units consistent across extraction, wire types and salary
   consumers. A breaking change needs versioned adapters and a consumer test.
5. Persistence as a versioned JSON result is recommended for this sprint; Jay
   chooses implementation. Original quote and correction history must survive.
6. InvestigationResult uses contract_version, run_id, claims, evidence,
   overall_outcome, authenticity_status, coverage, recommended_actions,
   confirmation_route (nullable), tool_trace and errors. Outcomes:
   HIGH_RISK/NEEDS_REVIEW/CANNOT_VERIFY/NO_STRONG_RISK_SIGNALS; authenticity is
   UNCONFIRMED absent authorized employer confirmation. No fraud probability.
7. Agree local OCR availability and consent boundary before enabling vision upload.

## Examples and later implementation acceptance

See [example manifest](../backend/tests/fixtures/investigation/extraction_contract/index.json).
Eight synthetic examples cover contact order, platform/employer distinction,
negated/quoted fees, active payment demand, credential solicitation, ambiguous
pay/user correction, unknown contact/absent employer, and sanitized OCR spans.
Fictional identifiers use reserved domains; payment handle ending upi.example is
an illustrative non-routable identifier, not a real UPI rail or valid bank handle.

Tests validate the **contract examples**, not application compliance. Later
implementation must preserve contact roles and dropped fields, ground every
claim in a supplied source or attributable correction, keep ambiguity/nulls,
distinguish contextual demands, omit secret values, honor redaction buffers,
and provide deterministic offline fallback where supported. It must never
attach external footprint findings to extraction alone.

Run from repository root:

```bash
python -m pytest backend/tests/investigation/test_extraction_contract.py -q
```

Or from backend/:

```bash
python -m pytest tests/investigation/test_extraction_contract.py -q
```
