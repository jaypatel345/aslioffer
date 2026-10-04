# Task 7: Grounded, Role-Aware Entity Extraction

## 1. Overview & Service Methods

Task 7 implements grounded, role-aware entity extraction in AsliOffer according to the requirements established in Task 2 (`docs/extraction-requirements.md`, contract version 1.0.1), while maintaining full regression compatibility with Tasks 3–6.

Extraction identifies **document claims**, not verified facts.

### Exposed Service Methods

In [`EntityExtractor`](file:///c:/Users/dyara/aslioffer/backend/app/services/extractor/entity_extractor.py):

1. **`extract_claims(text: str, source_type: str = "text") -> ExtractionResult`**:
   - Primary Task 7 entry point.
   - Returns a validated [`ExtractionResult`](file:///c:/Users/dyara/aslioffer/backend/app/services/extractor/claim_models.py) complying with contract v1.0.1.
   - Performs secret sanitization, exact Unicode span offset verification, contextual employer/agency separation, contact role attribution, base unit compensation parsing, and explicit ambiguity recording.

2. **`extract_regex(text: str) -> ExtractedData`**:
   - Backward-compatible regex extractor returning strongly-typed `ExtractedData`.
   - Internally delegates to `extract_claims(text)` and adapts via `result.to_extracted_data()`.

3. **`extract(text: str) -> ExtractedEntities`**:
   - Synchronous legacy wrapper returning `ExtractedEntities` for existing callers.

4. **`async extract_entities(text: str) -> ExtractedData`**:
   - Model-assisted extraction path with automated deterministic fallback on error, timeout, or model hallucination (e.g., if Gemini invents an employer name absent from the document).

5. **`async extract_from_document(file_bytes: bytes, mime_type: str) -> Dict[str, Any]`**:
   - Privacy-preserving document extractor.
   - Automatically parses PDFs locally via `pypdf` without external network transmission.
   - Rejects unsupported binary formats before attempting any external vision API calls.

---

## 2. Result Structure (Contract v1.0.1)

The service result is modeled by [`ExtractionResult`](file:///c:/Users/dyara/aslioffer/backend/app/services/extractor/claim_models.py):

```python
class ExtractionResult(BaseModel):
    contract_version: str = "1.0.1"
    source_type: str  # text, email, pdf, screenshot
    extraction_method: str  # regex, deterministic_contextual, hybrid, etc.
    sanitized_source_buffer: str  # sanitized text buffer with redacted secrets
    raw_text: Optional[str] = None
    ocr_text: Optional[str] = None
    redacted_text: Optional[str] = None
    claims: List[Claim] = Field(default_factory=list)
    unresolved_ambiguities: List[UnresolvedAmbiguity] = Field(default_factory=list)
    warnings: List[ExtractionWarning] = Field(default_factory=list)
```

Each [`Claim`](file:///c:/Users/dyara/aslioffer/backend/app/services/extractor/claim_models.py) contains:
- `claim_id`: Unique stable identifier (e.g. `CLM-01-01`).
- `kind`: Standardized claim kind (e.g. `claimed_employer`, `sender_recruiter`, `candidate_contact`, `compensation`, `meeting_platform`, etc.).
- `value`: Grounded claim value.
- `source_quote`: Exact substring match in `sanitized_source_buffer`.
- `source_span`: Unicode code-point offsets `[start_offset, end_offset)`.
- `extraction_status`: `"extracted"`, `"ambiguous"`, `"absent"`, or `"user_corrected"`.
- `confidence_tier`: Extraction clarity (`HIGH`, `MEDIUM`, `LOW` — describes clarity of text, not fraud probability).
- `attributes`: Kind-specific attributes.

---

## 3. Role Attribution & Ambiguity Rules

### Contact Role Attribution
1. **Candidate Destination (`candidate_contact`)**:
   - Grounded via `To:` headers, candidate-directed greetings (`"Dear John"`), or explicit candidate labels (`"Candidate Email:"`).
   - Kept distinct from recruiter contact.
2. **Sender / Recruiter (`sender_recruiter`)**:
   - Grounded via `From:` headers, explicit recruiter signatures (`"Regards, HR Team"`), or confirmation destinations (`"Send your acceptance to ..."`).
   - Only grounded recruiter contacts are forwarded to legacy `recruiter_email` / `recruiter_phone`.
3. **Unknown Contacts (`contact`)**:
   - Emails without sender or candidate cues (e.g. `"For inquiries, contact support@thirdparty.org"`) remain `contact` with `semantic_role="unknown"`.
   - Never arbitrarily promoted to recruiter.
4. **Multiple Recruiter Candidates**:
   - When multiple candidate addresses exist (e.g. `"Reply to hr1@corp.com or hr2@corp.com"`), both are marked `ambiguous` and an [`UnresolvedAmbiguity`](file:///c:/Users/dyara/aslioffer/backend/app/services/extractor/claim_models.py) is recorded.

### Contextual Employer & Agency Attribution
1. **Meeting Tools vs Real Employers**:
   - Google Meet, Microsoft Teams, Zoom, Google Forms, Drive, and Docs are classified as `meeting_platform` or tool URLs.
   - They never displace the actual employer (e.g. in `"Interview via Google Meet for V-Guard"`, V-Guard is the employer).
   - Real employers named Google or Microsoft are preserved when hiring directly.
2. **Staffing Agencies vs Client Employers**:
   - Relationships like `"Apex Staffing Solutions is hiring on behalf of client Infosys Limited"` extract `Apex Staffing Solutions` as `recruiting_agency` (`role="staffing_agency"`) and `Infosys Limited` as `claimed_employer` (`role="client_employer"`).
3. **Competing Employers**:
   - Competing employer entities produce explicit `AMBIGUOUS` claims with unresolved ambiguity records.

---

## 4. Legacy Compatibility & Monetary Units

### Monetary Units & Compensation Strategy
- **Claim Model**: Uses base currency units. For example, `INR 7.2 LPA` is parsed into:
  - `amount`: `720000.0`
  - `currency`: `"INR"`
  - `period`: `"ANNUAL"`
  - `amount_unit`: `"currency_base_unit"`
- **Frequency Ambiguity**: Unspecified frequency (e.g. `CTC INR 7,50,000` or `Stipend INR 15,000`) leaves `period=None`, flags status as `AMBIGUOUS`, and generates an unresolved ambiguity record.
- **Legacy Adapter (`to_extracted_data()`)**:
  - Automatically translates `720000.0` annual base units into legacy `salary_amount=7.2` and `salary_period="LPA"` to maintain 100% compatibility with downstream agents (`SalaryAgent`, `RiskEngine`) and existing test suites.

### Removal of Fabricated Location Fallback
- `ExtractedData.to_extracted_entities()` previously defaulted missing address to `"Remote / India"`.
- This has been removed: if address is null, `location` remains `None`.

### URL Purpose Separation
- Separates `interview_url`, `application_destination`, and `official_domain_reference`.
- Meeting room URLs (e.g. `https://meet.google.com/...`) are tagged with `purpose="interview_platform"`.
- Legacy `website` field only receives genuine company web addresses, never meeting links.

---

## 5. Provenance, Secret Redaction & User Corrections

### Provenance & Unicode Code Points
- Offsets in `SourceSpan` (`start_offset`, `end_offset`) are Unicode code-point indices.
- Verified on creation: `sanitized_source_buffer[start:end] == source_quote`.

### Secret Redaction
- OTPs, PINs, and passwords are unconditionally replaced with `[REDACTED_SECRET]`, `[REDACTED_OTP]`, or `[REDACTED_PASSWORD]` before model submission or logging.
- Routine onboarding identity document submissions (`PAN card`, `Aadhaar card`) are distinguished from financial credential theft demands.

### Attributable User Corrections
- Service-level corrections via `result.apply_user_correction()`:
  - The original claim remains completely intact to preserve raw document evidence.
  - A new `user_correction` claim is appended referencing `target_claim_id`.
  - `result.get_effective_claims()` returns the updated claims reflecting user adjustments.

---

## 6. Document Processing & Privacy

1. **Local PDF Text Extraction**:
   - Standard PDF files are read locally using `pypdf`.
   - Text is sanitized and passed to deterministic parsing with 0 network calls.
2. **Unsupported Document Safety**:
   - Documents with unsupported MIME types (e.g. binary streams, `.bin`, executables) are rejected immediately with `ocr_text=""`, preventing transmission to external vision models.

---

## 7. Remaining Integration Work (For Jay)

The following items are outside Task 7 scope and owned by Jay:

1. **API Router & Database Persistence (`backend/app/api/v1/routers/offers.py`)**:
   - `upload_offer()` and `analyze_offer()` endpoints currently return `ExtractedEntities` and store raw user text/payloads.
   - Jay will need to update the database schema and public router endpoints to persist full `ExtractionResult` JSON if claim provenance and ambiguities are to be exposed in the public API.
2. **User Correction UI & Persistence**:
   - Exposing `apply_user_correction` via a REST endpoint (`POST /api/v1/offers/{id}/correct`) and persisting corrections in SQLite/PostgreSQL.
3. **Frontend Integration**:
   - Displaying claim badges, role annotations (candidate vs recruiter email), and inline ambiguity resolution prompts in the Next.js frontend.

---

## 8. Known Limitations

1. **Scanned Images Without Vision Credentials**:
   - Raster images (PNG, JPG) without embedded text require Groq or Gemini vision credentials; if neither API key is set, the document cannot be locally OCR'd unless Tesseract is installed on the host.
2. **Complex Multi-Party Contracts**:
   - Documents with deeply nested subcontracting networks without standard grammatical cues (`"on behalf of"`, `"client"`, `"recruiting for"`) may flag multiple employers as ambiguous rather than discerning client hierarchy.
