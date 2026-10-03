# Task 5: Evidence-Backed Recruiter Affiliation & Agency Assessment

## Overview

Task 5 implements evidence-backed recruiter verification and recruitment-agency assessment for AsliOffer.
It resolves several architectural defects where:
1. `RecruiterAgent` automatically returned `HIGH_RISK` for free webmail domains.
2. An employer domain mismatch automatically condemned recruiters as impersonators, breaking legitimate third-party staffing workflows.
3. Domain alignment alone returned `VERIFIED` without verifying the individual's affiliation or contact credibility.
4. `recruiter_name` was extracted but never investigated against employer team or professional directories.
5. Phone matching joined arbitrary snippet digits and treated any number mention (including helpline advisories and corporate switchboards) as scam reports.
6. `ScamAgent` independently treated free webmail as enterprise fraud, undoing `RecruiterAgent` nuances.
7. `VerdictReasoner` did not handle recruiter `NEEDS_REVIEW` properly in its review branch, causing review findings to risk collapsing into `VERIFIED`.

---

## 1. Assessment Dimensions & Status Model

To avoid conflating distinct facts, `RecruiterAgent` evaluates six decoupled assessment dimensions stored in `details["assessment_dimensions"]` and mirrored directly on `details`:

1. **`employer_domain_resolution`**: Identifies whether the claimed employer's corporate domain can be corroborated from public search results using Task 4's `DomainResolver`.
2. **`recruiter_email_domain`**: Evaluates email validity, public webmail vs enterprise domain, and domain alignment with the employer.
3. **`recruiter_affiliation`**: Investigates whether public records (employer talent directories, official team listings, or corroborated public profiles) link the named individual/contact to the employer.
4. **`agency_identity`**: Validates whether a stated or discovered staffing agency has an authentic, verifiable corporate web presence on its own domain.
5. **`agency_authorization`**: Examines whether the employer publicly recognizes the staffing agency as an authorized recruitment vendor/partner.
6. **`adverse_contact_reports`**: Assesses whether exact submitted contacts (phone, email) are the subject of credible, specific public scam/fraud reports.

### Standardized Status Vocabulary

Each dimension reports one of six explicit statuses:
- **`SUPPORTED`**: Positive corroborating evidence was found in authoritative or independent search results.
- **`UNCONFIRMED`**: Claimed or plausible, but available search evidence does not substantiate the claim.
- **`NO_MATCH`**: Search completed successfully, and no matching records or allegations were found (or contact input was invalid).
- **`CONFLICTING`**: Evidence directly contradicts the claim (e.g. sender domain differs from employer domain, or competing ambiguous candidates exist).
- **`CHECK_UNAVAILABLE`**: Search provider failure, network timeout, rate limit, or synthetic fixture source prevented an authentic check.
- **`NOT_CHECKED`**: Input was omitted, or pre-requisite conditions were not met.

Each dimension records:
- `status`: One of the 6 canonical statuses above.
- `explanation`: Clear human-readable rationale.
- `source_urls`: List of corroborating source URLs.
- `raw_facts`: Structured fact dictionary cleanly decoupled from inferences.

---

## 2. Verdict Decision Policy

`RecruiterAgent` never equates domain alignment, agency existence, or the mere absence of complaints with authentication of the individual or offer letter.

| Verdict | Conditions | Meaning & Semantics |
| :--- | :--- | :--- |
| **`HIGH_RISK`** | Specific adverse contact report (phone or email) alleging fraud/impersonation, or supported impersonation findings. | Specific evidence indicates malicious activity or known scam contact. Free webmail or domain mismatch alone **never** produces `HIGH_RISK`. |
| **`NEEDS_REVIEW`** | Domain mismatch (`domain_match=False`), free webmail domain (`is_free_email=True`), agency client representation mandate unconfirmed (`agency_authorization="UNCONFIRMED"`), or conflicting affiliation. | Legitimate anomaly or third-party representation requiring secondary verification. Does not condemn the recruiter as fraudulent. |
| **`CANNOT_VERIFY`** | Insufficient identity evidence, unconfirmed recruiter affiliation despite domain alignment, malformed/unusable contacts, or essential checks unavailable. | Identity cannot be confirmed from open public web sources. Clearly states that an uncorroborated check does not imply fraud. |
| **`VERIFIED`** | Employer domain aligns (`domain_match=True`) **AND** recruiter affiliation is corroborated by employer-published talent listings or verified profiles. | Affiliation and credentials are confirmed against public records. Explicitly caveats that **the specific offer letter remains unauthenticated**. |

### Domain Match Tri-State

`details["domain_match"]` preserves strict tri-state semantics:
- `True`: Resolved employer domain strictly aligns with the recruiter's registrable domain.
- `False`: Resolved employer domain differs from the recruiter's domain.
- `None` (Null): Employer ownership is unresolved, ambiguous, search unavailable, or contact input is malformed/missing.

---

## 3. Evidence Strength & Source Hierarchy

Searches are bounded and prioritized by source authority:

1. **Employer-Published Direct Evidence (Strongest)**:
   - Pages hosted on the resolved canonical employer domain (`acme.com/team`, `acme.com/careers/partners`).
   - Mentioning the specific recruiter name, email, or telephone in a recruitment/talent role.
   - Sets `evidence_strength="strong_employer_published"`.

2. **Corroborated Public Professional Profiles (Supporting)**:
   - Structured public profiles (e.g., LinkedIn, Xing, Crunchbase) associating the recruiter name with the employer and recruitment role.
   - Sets `evidence_strength="corroborated_profile"`.
   - A self-described profile supports claimed affiliation but **cannot independently authenticate an offer**.

3. **Same-Name / Unrelated Traps (Rejected)**:
   - Matches for common names without corporate context, or associated with unrelated companies, are rejected as `UNCONFIRMED`.

4. **Empty Search Inference**:
   - An empty search means no matching records were retrieved. It does **not** establish a clean record, certify honesty, or verify identity.

---

## 4. Recruitment Agencies: Footprint vs. Authorization

A recruiter domain different from the employer's is not inherently fraudulent. Many legitimate hires occur through staffing agencies (e.g., Apex Staffing recruiting for Starlight Media).

- **Agency Identity Footprint**: Resolved via `DomainResolver` on the agency's own domain (`apexstaffing.com`).
- **Employer Representation Mandate**: A distinct dimension (`agency_authorization`).
  - An agency's self-claim to be an "authorized recruitment partner" remains `UNCONFIRMED` unless corroborated by employer records.
  - Employer-published vendor lists (`acme.com/partners`) can promote `agency_authorization` to `SUPPORTED` (`evidence_strength="employer_published_partner"`).
  - An agency with a verified footprint but unconfirmed mandate returns `NEEDS_REVIEW` (`reason_code="AGENCY_MANDATE_UNCONFIRMED"`), **not** `HIGH_RISK`.
- **Domain Match Isolation**: Agencies never force `domain_match=True` on the employer check. The employer domain match remains `False`, while agency domain alignment is recorded separately as `agency_domain_match=True`.

---

## 5. Contact Validation & Contextual Adverse Reports

### Input Hygiene
- **Email Validation**: Validated using `DomainResolver.normalize_and_parse_url`. Malformed addresses (e.g. `@@@`, missing `@`, spaces) are rejected as unusable input with `reason_code="INVALID_CONTACT_INPUT"`, **not** evidence of fraud.
- **Phone Normalization**: Normalized with token and word-boundary awareness. Subsequence matching, partial last-seven-digits matching, and digit joining across titles and snippets are strictly rejected to prevent false positives (e.g., `555-1234` matching `555-12345`).

### Contextual Adverse Report Analysis
An exact phone number appearing in a search snippet is not inherently adverse. The engine distinguishes:
- **Official Contact Listings**: Headquarters switchboard, HR directory, or customer support lines.
- **Generic Scam Advisories**: Security notices advising candidates to call an official helpline or reporting number (e.g. "Beware of scams, contact HR at +1-800-555-0199").
- **Specific Adverse Reports**: Consumer fraud complaint boards, cybercrime reports, or candidate testimonies alleging that callers from this exact number demanded fees or issued fraudulent letters.
- **Cautious Attribution**: Language uses objective phrasing ("public report alleges fraudulent activity") rather than definitive criminality.

---

## 6. Search Budget, Concurrency & Private Logging

- **Search Budget**: Strictly bounded to at most 4–5 targeted queries per investigation:
  1. `"{company_name}" official website careers` (Employer domain)
  2. `"{agency_name}" official website` (Agency identity, only if agency provided)
  3. `"{recruiter_name}" "{company_name}"` (Affiliation, only if non-generic name provided)
  4. `"{phone}" scam OR fraud OR complaint` (Adverse phone check, only if phone provided)
  5. `"{email}" scam OR fraud OR complaint` (Adverse email check, only if non-free email provided)
- **Graceful Partial Degradation**: If one search provider call times out or fails (e.g. phone adverse check), successful checks (domain resolution, agency verification) are preserved. The finding records `provider_status="PARTIAL"` and carries forward valid evidence.
- **Privacy & PII Protection**: Raw recruiter emails, phone numbers, and candidate details are never logged in cleartext in debug/info statements.
- **Demo Isolation**: When `is_demo=True` or synthetic fixtures are detected, mock data is prevented from manufacturing `VERIFIED` affiliation or fraud convictions.

---

## 7. RiskEngine & VerdictReasoner Integration

- **Authority Delegation**: `RecruiterAgent` is established as the sole authority for email domain alignment and recruiter affiliation.
- **Removal of Duplicate Condemnation**: The duplicate `PERSONAL_EMAIL_ENTERPRISE` signal in `ScamAgent` was removed, preventing free email from being unilaterally branded as enterprise fraud.
- **Propagation of `NEEDS_REVIEW`**:
  - `RiskEngine` maps recruiter `NEEDS_REVIEW` to a 0.20 score increment without overwhelming other findings.
  - `VerdictReasoner` explicitly recognizes recruiter `NEEDS_REVIEW` reason codes (`FREE_WEBMAIL_DOMAIN`, `RECRUITER_DOMAIN_MISMATCH`, `AGENCY_MANDATE_UNCONFIRMED`).
  - **Invariance Rule**: A finding containing a review flag can **never** collapse into a final `VERIFIED` verdict.

---

## 8. Structured Detail Fields for UI Consumption

The frontend can inspect existing structured keys within `AgentFinding.details`:

```json
{
  "domain_match": false,
  "is_free_email": false,
  "is_agency": true,
  "agency_name": "Apex Staffing",
  "agency_domain": "apexstaffing.example",
  "agency_domain_match": true,
  "official_domain": "starlightmedia.example",
  "reason_code": "AGENCY_MANDATE_UNCONFIRMED",
  "assessment_dimensions": {
    "employer_domain_resolution": {
      "status": "SUPPORTED",
      "explanation": "Employer official domain resolved to 'starlightmedia.example'.",
      "source_urls": ["https://starlightmedia.example"]
    },
    "recruiter_email_domain": {
      "status": "CONFLICTING",
      "explanation": "Submitted recruiter email domain '@apexstaffing.example' differs from resolved company domain 'starlightmedia.example'.",
      "source_urls": []
    },
    "recruiter_affiliation": {
      "status": "UNCONFIRMED",
      "explanation": "Recruiter affiliation could not be confirmed from available evidence.",
      "source_urls": []
    },
    "agency_identity": {
      "status": "SUPPORTED",
      "explanation": "Staffing agency 'Apex Staffing' web presence verified on 'apexstaffing.example'.",
      "source_urls": ["https://apexstaffing.example"]
    },
    "agency_authorization": {
      "status": "UNCONFIRMED",
      "explanation": "Recruiter operates under third-party staffing agency 'Apex Staffing'. Agency footprint verified, but client representation mandate requires confirmation.",
      "source_urls": []
    },
    "adverse_contact_reports": {
      "status": "NO_MATCH",
      "explanation": "No matching adverse scam or fraud reports found for submitted contacts; empty search does not verify identity.",
      "has_adverse_reports": false,
      "source_urls": []
    }
  }
}
```

---

## 9. Verification & Deferred Limitations

### Test Suite Execution
- **Behavioral Regression Suite**: `backend/tests/investigation/`
  - Baseline: 32 passed, 9 expected failures (`xfail`).
  - Result: **34 passed, 7 expected failures** (`xfail`).
  - Successfully activated and resolved `test_case_13_plausible_details_do_not_confirm_offer_or_fraud` and `test_case_14_agency_recruitment_must_not_be_high_risk_impersonation`.
- **Dedicated Task 5 Suite**: `backend/tests/test_recruiter_agent_task5.py`
  - **17 passed**, covering all 17 specific edge cases and integration flows.
- **Full Backend Suite**:
  - All Task 3 search reliability, Task 4 domain resolver, and core API regression tests pass without regression.

### Deferred Limitations (Out of Scope for Task 5)
- **Live DNS/MX Verification**: Mail server exchange records and SPF/DKIM verification remain deferred (mail infrastructure does not authenticate individual hiring authority).
- **Payment & Messaging Extraction**: WhatsApp/Telegram interview channels, upfront payment parsing, and document tamper detection belong to Task 6 (Scam Detection) and Task 7 (Risk Redesign).
