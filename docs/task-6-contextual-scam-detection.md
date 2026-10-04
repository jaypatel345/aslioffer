# Task 6: Contextual Scam Detection in AsliOffer

Version **1.0.0**, October 2026.
Implementation documentation for Task 6: Evidence-backed contextual scam detection.

---

## 1. Overview and Problem Statement

Prior to Task 6, AsliOffer relied on unconditional keyword matching in `ScamAgent`. Substring hits such as `"security deposit"`, `"registration fee"`, or `"telegram"` unconditionally triggered `HIGH_RISK` fraud verdicts. This introduced critical defects and false positives:
- Legitimate corporate anti-fraud disclaimers (e.g. *"We never charge a security deposit"*) were incorrectly flagged as fee extortion demands (Case 04).
- Quoted security advisories alerting candidates against third-party fraud (e.g. *"Beware of fraudsters asking for registration fees"*) were convicted as scam offers (Case 05).
- Ordinary recruitment communication or announcement channels (e.g. joining an informational Telegram channel for campus webinar updates) triggered critical fraud alerts (Case 06).
- Real, urgent threats like explicit bank OTP or net-banking password solicitation (Case 08) and task-scam unlock-earnings extortion (Case 09) were not classified accurately.

Task 6 replaces unconditional keyword detection with an evidence-backed contextual classifier (`ScamClassifier`) that analyzes localized clauses, syntax framing, payment direction, and secret redaction.

---

## 2. Contextual Signal Classification & Modalities

Every candidate clause or structured hint is assigned one of four explicit modalities:

| Modality | Definition | Examples | Effect on Verdict |
|---|---|---|---|
| `active_demand` | An affirmative command or conditional demand requiring the candidate to remit payment, unlock wages, or disclose sensitive authentication credentials. | *"Pay the mandatory laptop deposit of INR 5,000."*<br>*"To unlock your earnings, pay INR 2,200 wallet release charge."*<br>*"Share your bank OTP and net-banking password with HR."* | Grounded basis for `HIGH_RISK` |
| `negated_policy` | An explicit corporate policy stating that the company does NOT charge fees, request deposits, or solicit account secrets. | *"We never charge a security deposit, registration fee, or onboarding deposit."*<br>*"Wipro does not solicit payments or training fees."*<br>*"Do not share your bank OTP with anyone."* | Suppresses fee/theft triggers; auditable in structured assessments |
| `quoted_advisory` | Scam phrasing quoted within an anti-fraud advisory or public warning cautioning candidates against third-party scammers. | *"Security Advisory: Fraudsters are circulating fake letters stating 'Pay INR 2,500 registration fee via UPI'."* | Recognized as prevention guidance; does not elevate offer risk |
| `ambiguous` | Uncorroborated structured hints (e.g., fee present in metadata but absent from text), unclear payment terms, or informational platform channels without active demands. | *"All webinar links will be posted on our Telegram channel."*<br>*Demanded fee present in structured input but contradicted or uncorroborated by text.* | Triggers `NEEDS_REVIEW` |

### Key Detection Rules:
1. **Localized Negation Scope**:
   Negation only applies to its surrounding clause/sentence. For example:
   > *"We do not charge registration fees. Pay the mandatory laptop deposit."*
   The first clause is recognized as `negated_policy` for registration fees, while the second clause independently triggers an active `UPFRONT_FEE_DEMAND`.
2. **Quotation Marks Attribution**:
   Quotation marks alone do not suppress an actual demand. Forwarded recruiter messages within quotes (e.g., *The recruiter stated: "Deposit INR 3,000 before joining"*) remain active demands. Conversely, quotes embedded in advisory contexts (e.g., *Warning: Fraudsters asking "Pay deposit"*) are classified as `quoted_advisory`.
3. **Payment Direction (Employer-to-Candidate vs Candidate-to-Recruiter)**:
   Mentions of payment channels (UPI, bank transfer) in the context of salary receipt (e.g., *"Salary will be credited through bank transfer"*) do not constitute a fee demand. Payment rails are only flagged when associated with a candidate-to-recruiter demand.
4. **Credential Theft vs Self-Service Verification**:
   Instructing candidates to enter an OTP themselves on an official portal (*"Enter the OTP on the official portal yourself"*) is legitimate self-service. Soliciting candidate bank OTPs, net-banking passwords, or ATM PINs via email/chat to HR represents critical credential theft.

---

## 3. Stable Signal Codes & Verdict Mapping

### Signal Codes

| Signal Code | Modality | Severity | Description |
|---|---|---|---|
| `UPFRONT_FEE_DEMAND` | `active_demand` | `CRITICAL` | Registration, onboarding, training, document verification, equipment/laptop fee, or refundable security deposit. |
| `UNLOCK_PAYMENT_DEMAND` | `active_demand` | `CRITICAL` | Payment or wallet recharge demanded to unlock tasks, accumulated earnings, wages, or withdrawals. |
| `CREDENTIAL_THEFT_DEMAND` | `active_demand` | `CRITICAL` | Direct solicitation of bank OTPs, net-banking passwords, ATM PINs, or account-access secrets. |
| `UPI_PAYMENT_REQUEST` | `active_demand` | `HIGH` | Candidate payment requested through UPI, GPay, PhonePe, Paytm, or VPA handles (`@okaxis`). |
| `TELEGRAM_COMMUNICATION` | `ambiguous` | `LOW` / `MEDIUM` | Telegram channel or task group mentioned in recruitment communication without active payment demands. |
| `WHATSAPP_RECRUITMENT_CHANNEL` | `ambiguous` / `active_demand` | `MEDIUM` / `HIGH` | WhatsApp referenced for recruitment tasks or communication. |
| `NEGATED_FEE_POLICY` | `negated_policy` | `INFO` | Explicit anti-fraud disclaimer stating company never charges fees. |
| `QUOTED_SCAM_ADVISORY` | `quoted_advisory` | `LOW` | Quoted scam language inside security advisory cautioning candidates. |
| `UNSUPPORTED_STRUCTURED_HINT` | `ambiguous` / `negated_policy` | `LOW` / `MEDIUM` | Extracted structured hint uncorroborated or contradicted by raw text. |

### Verdict Mapping

- **`HIGH_RISK`** (`confidence = 0.98`, `scam_flagged = True`):
  Triggered when at least one active demand (`UPFRONT_FEE_DEMAND`, `UNLOCK_PAYMENT_DEMAND`, or `CREDENTIAL_THEFT_DEMAND`) is grounded in the text. External search failure or demo mode does not suppress active document scam demands.
- **`NEEDS_REVIEW`** (`confidence = 0.70`, `scam_flagged = False`):
  Triggered when document contains ambiguous requests, uncorroborated structured hints, or ordinary platform cautions (e.g. Telegram announcement link).
- **`VERIFIED`** (`confidence = 0.90`, `scam_flagged = False`):
  No local scam indicators detected and external searches completed cleanly. Explicit summary states that searches completed but do not authenticate the offer.
- **`CANNOT_VERIFY`** (`confidence = 0.0`, `scam_flagged = False`):
  No local scam indicators detected, but external search provider checks were unavailable (outage, rate limit, timeout).

---

## 4. Evidence Handling & Secret Redaction

1. **Local Evidence Source**:
   All local document findings cite `source_url = "document://submitted-offer"`. Local platform mentions are never falsely described as CyberDost/NCRP advisories unless returned by actual external search sources.
2. **Zero-Secret Retention**:
   Actual numeric OTPs (e.g. 6-digit verification codes) and plaintext passwords are unconditionally redacted using `sanitize_and_redact_secrets()` prior to storing in quotes, evidence descriptions, or logs.
3. **Quote & Span Consistency**:
   When `source_span` is provided in `signal_assessments`, it locates offsets within the sanitized buffer `target_text: "sanitized_buffer"`, guaranteeing `sanitized_text[start:end] == source_quote`. If exact provenance cannot be verified, `source_span` is omitted (`None`).
4. **Structured Signal Assessments**:
   Every assessment is preserved in `details["signal_assessments"]` (including suppressed policies and quoted advisories) for auditability. Active verdict-contributing signals are populated in `details["risk_signals"]`.

---

## 5. VerdictReasoner Integration

`VerdictReasoner` was updated to accurately represent distinct scam modalities:
- **Credential Theft**: Assigned reason code `CREDENTIAL_THEFT_DETECTED` (never conflated with `ADVANCE_FEE_DETECTED`).
- **Unlock Payment Demands**: Assigned reason code `UNLOCK_PAYMENT_DETECTED`.
- **Advance Fees**: Assigned reason code `ADVANCE_FEE_DETECTED`.
- **Multiple Supported Scam Reasons**: When both advance fee and credential theft (or unlock payment) are present, all applicable `VerdictReason` entries are preserved in `reason_details`.
- **ScamAgent `NEEDS_REVIEW` Propagation**: ScamAgent review explanations are preserved and visible in `VerdictReasoner` outputs, both in the `NEEDS_REVIEW` tier and when insufficient evidence results in `CANNOT_VERIFY`.

---

## 6. Search Budget & Relevance

- **Search Budget**:
  - Scam search queries: 1 general company scam query (`"{safe_company}" job scam fraud complaint telegram`) + 1 payment-specific query (`"{safe_company}" "{payment_term}" recruitment scam`).
  - Strict result capping: maximum 2 organic results per query.
- **Relevance Filtering**:
  - Search hits are evaluated for entity relevance before citing as evidence.
  - Generic internet safety tips and broad consumer advisories are distinguished from attributable adverse reports and do not independently condemn an innocent offer.
- **Demo Isolation**:
  - Synthetic search mocks/demo results are isolated and excluded from live evidence citations.

---

## 7. Deferred Items

As specified in the project scope:
- **Entity Extraction**: Extraction regex rules (Cases 15 and 16 regarding candidate/recruiter email separation and meeting platform traps) remain deferred to Task 2 handoff.
- **Risk Weights**: Deterministic weights in `RiskEngine` remain unchanged.
- **Shared Schemas**: No breaking changes to `AgentFinding`, `EvidenceItem`, or wire contracts.
