# AsliOffer Investigation Regression Fixture Corpus

This directory contains a reproducible, labeled fixture corpus of 16 synthetic investigation cases. The corpus establishes the regression baseline for AsliOffer's offer verification pipeline, capturing the investigation problems and failure modes identified during the competitive review.

## Purpose and Scope

AsliOffer evaluates employment offers and recruiter communications. A robust evaluation corpus must satisfy the following principles:
1. **Honest uncertainty**: Missing public evidence is recorded as uncertainty (`CANNOT_VERIFY` / unconfirmed coverage), NOT manufactured into proof of fraud.
2. **No false reassurance**: Plausible salary, authentic corporate logos, or clean phone search hits must not authenticate an offer.
3. **No brand-in-domain certification**: A domain merely containing a company name (e.g., `tcs-careers-portal.example`) is a potential lookalike, never proof of ownership.
4. **Context-aware fee detection**: Negated fees ("We never charge a deposit") and quoted scam warnings must not be flagged as fee demands.
5. **Direct threat sensitivity**: Explicit bank OTP demands, account password requests, and unlock-earnings task scams must produce immediate grounded warnings.
6. **Provider failure isolation**: Provider timeouts, rate limits (HTTP 429), or empty results must be preserved as status codes and never masked with canned mock evidence.

> **Privacy and Safety Note**: All fixtures use reserved example domains (RFC 2606 / RFC 6761, such as `.example`) and synthetic personal details. No private letters, live credentials, or real API keys are present.

---

## Fixture Schema Format

Each fixture is a readable JSON file structured as follows:

```json
{
  "case_id": "CASE-LOOKALIKE-DOMAIN-01",
  "category": "lookalike_domain",
  "title": "Short descriptive scenario title",
  "description": "Detailed explanation of the input context and failure mode",
  "synthetic": true,
  "unresolved_facts": [
    "List of facts that cannot be resolved from available evidence"
  ],
  "labels": {
    "data_type": "synthetic",
    "threat_category": "domain_impersonation",
    "expected_verdict": "SUSPECTED_LOOKALIKE"
  },
  "raw_text": "Full synthetic offer letter or recruiter message text...",
  "structured_input": {
    "company_name": "Claimed Employer Name",
    "recruiter_name": "Recruiter Name or null",
    "recruiter_email": "recruiter@domain.example or null",
    "recruiter_phone": "+919876543210 or null",
    "job_role": "Role Title or null",
    "salary": "INR 6.5 LPA or null",
    "demanded_fee": "Demanded amount or null",
    "payment_method": "UPI / Bank Transfer / null",
    "application_url": "URL or null",
    "flags": []
  },
  "provider_status": "successful", // "successful" | "empty" | "failed"
  "search_mock": {
    "query_responses": {
      "\"Exact Query String\"": {
        "status": "successful",
        "source": "mock",
        "knowledge_graph": {},
        "organic_results": []
      }
    },
    "default_response": {
      "status": "successful",
      "source": "mock",
      "organic_results": []
    }
  },
  "expected_observations": {
    "company_assessment": { ... },
    "recruiter_assessment": { ... },
    "scam_assessment": { ... },
    "overall_outcome": "HIGH_RISK | CANNOT_VERIFY | NEEDS_REVIEW | NO_STRONG_RISK_SIGNALS",
    "authenticity_status": "UNCONFIRMED",
    "risk_level": "HIGH_RISK | NEEDS_REVIEW | VERIFIED"
  },
  "rationale": "Clear technical rationale distinguishing genuine signals from defects."
}
```

---

## Scenario Index

| Index | Case ID | Category | Scenario Description | Expected Outcome |
|---|---|---|---|---|
| 1 | `CASE-LOOKALIKE-DOMAIN-01` | Lookalike Domain | Real company name with a lookalike application domain | `HIGH_RISK` / Suspected lookalike |
| 2 | `CASE-UNKNOWN-CORP-RECRUITER-02` | Unresolved Recruiter | Unknown corporate-looking recruiter email with no official company domain | `CANNOT_VERIFY` |
| 3 | `CASE-PHONE-ONLY-NO-MATCH-03` | Phone Recruiter | Phone-only recruiter with 0 public search complaints | `CANNOT_VERIFY` |
| 4 | `CASE-LEGIT-POLICY-NEGATED-FEE-04` | Negated Fee Policy | Legitimate policy saying "We never charge a security deposit" | `NO_STRONG_RISK_SIGNALS` |
| 5 | `CASE-QUOTED-SCAM-WARNING-05` | Quoted Scam Warning | Quoted anti-scam advisory containing fee keywords | `NO_STRONG_RISK_SIGNALS` |
| 6 | `CASE-ORDINARY-TELEGRAM-06` | Ordinary Telegram | Informational Telegram channel mention without payment demands | `NEEDS_REVIEW` |
| 7 | `CASE-EXPLICIT-UPFRONT-FEE-07` | Upfront Fee Demand | Explicit mandatory security deposit demanded via UPI | `HIGH_RISK` |
| 8 | `CASE-EXPLICIT-BANK-OTP-DEMAND-08` | Credential Theft | Explicit bank OTP or password demand for payroll activation | `HIGH_RISK` |
| 9 | `CASE-PAYMENT-TO-UNLOCK-JOB-09` | Task Scam | Payment required to unlock earned task salary | `HIGH_RISK` |
| 10 | `CASE-SMALL-EMPLOYER-SPARSE-10` | Sparse Employer | Early-stage small startup with sparse public presence | `CANNOT_VERIFY` |
| 11 | `CASE-SUCCESSFUL-SEARCH-EMPTY-11` | Empty Search | Search executes successfully with 0 results | `CANNOT_VERIFY` |
| 12 | `CASE-PROVIDER-OUTAGE-TIMEOUT-12` | Provider Outage | Upstream search returns HTTP 429 rate limit or timeout | `CANNOT_VERIFY` |
| 13 | `CASE-REALISTIC-IMPERSONATION-13` | Impersonation | Plausible salary & copied corporate address with lookalike contact | `HIGH_RISK` / Unconfirmed |
| 14 | `CASE-LEGIT-AGENCY-RECRUITMENT-14` | Staffing Agency | Legitimate third-party agency hiring on behalf of corporate client | `NEEDS_REVIEW` |
| 15 | `CASE-CANDIDATE-AND-RECRUITER-EMAILS-15` | Role Separation | Message contains candidate (@gmail.com) and recruiter corporate email | `NO_STRONG_RISK_SIGNALS` |
| 16 | `CASE-EXTRACTION-TRAP-PLATFORM-16` | Tooling Platform Trap | Message mentions Google Meet / Microsoft Teams for interview slot | `NO_STRONG_RISK_SIGNALS` |

---

## How to Run Checks

All tests are lightweight, execute in milliseconds, and make **zero live network calls**.

Run the fixture validation and behavioral regression tests using `pytest` via `python -m pytest`:

```bash
# Run fixture corpus structure and schema validation tests
python -m pytest backend/tests/investigation/test_fixture_corpus.py -v

# Run behavioral regression tests exposing current defects
python -m pytest backend/tests/investigation/test_behavioral_regression.py -v

# Run all investigation tests together
python -m pytest backend/tests/investigation/ -v
```

Known defects are tracked with `@pytest.mark.xfail(strict=True, reason="...")`. When running the test suite, expected failures will show as `XFAIL`. If a defect is unexpectedly fixed or altered without updating the test, it will result in `XPASS` and fail the suite.
