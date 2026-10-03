# Task 4: Evidence-Backed Official Company Domain Resolution

Base commit: `9300c5c`.

## 1. Goal and Problem Summary

Previous implementations in `CompanyAgent` and `RecruiterAgent` suffered from critical domain-matching vulnerabilities:
1. Punctuation stripping and substring/acronym matching (`name_token in netloc` or `netloc in name_token`), which treated deceptive lookalikes (such as `tcs-careers-portal.example`) as verified corporate domains.
2. Independent and diverging domain resolution logic across `CompanyAgent` and `RecruiterAgent`.
3. Unconditional trust in `knowledge_graph.website` without verifying that the knowledge graph entity actually matches the queried company.
4. Acceptance of arbitrary search result titles containing "career" as the official careers URL.
5. Ingress of unrelated search results into the verified company finding.
6. Treatment of non-free email domains as verified identities without a resolved employer domain.

Task 4 introduces a unified, deterministic, offline-capable `DomainResolver` service (`backend/app/services/search/domain_resolver.py`), eliminates independent substring matching, and enforces evidence-backed identity verification.

---

## 2. Resolution States and Evidence Requirements

The resolver represents four explicit states:

| Resolution State | Meaning | Resolution Criteria | Details / Diagnostics |
| :--- | :--- | :--- | :--- |
| `RESOLVED` | Conclusive official company web footprint identified. | Verified Knowledge Graph entity card matching company title AND/OR top organic result matching company identity SLD and corroborated by page titles. | `official_domain` contains normalized canonical website URL. `careers_url` populated if verified. |
| `UNRESOLVED` | Search completed, but no candidate established verified ownership. | Zero results, or all candidates were platforms, lookalikes, or unrelated entities. | `official_domain = None`, `careers_url = None`. Reasons for each candidate rejection in diagnostics. |
| `AMBIGUOUS` | Multiple distinct plausible corporate domains competed without decisive corroboration. | Two or more separate registrable domains (e.g. `apex.example` vs `apextechnologies.example`) matched company brand without a decisive entity card. | `official_domain = None`. Competing domains documented in diagnostics and summary. |
| `SEARCH_UNAVAILABLE` | Search failed or was non-live (demo/mock). | Provider outage, timeout, auth failure, rate limit, or synthetic fixture source without live validation. | `official_domain = None`. Provider failure or demo source recorded honestly. |

### Ownership vs Footprint
A resolved domain establishes a public company footprint only. It does **not** authenticate submitted offer letters, job roles, recruiters, or salary promises.

### Independent Evidence Corroboration
Multiple links from the same registrable domain (e.g., `wipro.com/` and `wipro.com/careers`) represent a single domain host origin, not independent external confirmations. Independent corroboration requires alignment between a verified Knowledge Graph entity card and organic search results, or across distinct verified search citations.

---

## 3. Normalization and Public Suffix Handling

### URL & Hostname Normalization
- **Schemes**: Only `http` and `https` schemes are accepted. Non-web schemes (`ftp`, `javascript`, `data`, `file`) are rejected.
- **Credentials**: URLs containing embedded credentials (`user:pass@host`) are rejected as unsafe.
- **Port Stripping**: Non-standard ports are preserved in base URL normalization, but stripped when evaluating hostname identity.
- **Case and Trailing Dots**: Hostnames are lowercased and stripped of trailing dots (`WIPRO.COM.` -> `wipro.com`).
- **Paths and Queries**: Paths, queries, and fragments are stripped for domain canonicalization, while source links are retained for provenance.
- **Unicode / IDNA**: Hostnames are normalized using IDNA (`encode("idna").decode("ascii")`). Punycode visual homoglyphs (`xn--...`) are rejected as suspected spoofing attacks rather than treated as company ownership.

### Offline Public Suffix Architecture
The universal "last two hostname labels" rule is mathematically incorrect for multi-label country-code second-level domains (ccSLDs) such as `.co.in`, `.gov.in`, `.co.uk`, `.com.au`, `.org.za`.
To ensure 100% offline determinism and zero network dependencies during tests and runtime, `DomainResolver` embeds a curated, comprehensive table of multi-label public suffixes (`MULTI_PART_PUBLIC_SUFFIXES`).
- Given `careers.tcs.co.in`:
  - Suffix recognized: `co.in`
  - SLD extracted: `tcs`
  - Registrable domain: `tcs.co.in`
  - Subdomain: `careers`
- Given `tcs.com.attacker.example`:
  - Suffix recognized: `example`
  - SLD extracted: `attacker`
  - Registrable domain: `attacker.example`
  - Subdomain: `tcs.com` (attacker-controlled subdomain)

---

## 4. Lookalike and Ambiguity Handling

### Lookalike Defenses
1. **Recruiting Keyword Splicing**: Hostnames that concatenate company brands with hiring keywords (`-careers`, `-portal`, `-jobs`, `-recruitment`, `-apply`, `-onboarding`, `-verify`) in the SLD (e.g., `tcs-careers-portal.example`) are flagged as `SUSPECTED_LOOKALIKE` and rejected.
2. **Subdomain Suffix Attacks**: Attackers creating subdomains on third-party domains (e.g., `tcs.com.attacker.example`) have registrable domain `attacker.example`. The resolver detects that the company identity is sequestered in an attacker subdomain and rejects the domain.
3. **Path-Based Deception**: Domains embedding the brand name solely in the URL path (`attacker.example/tcs.com`) are rejected because the registrable domain (`attacker.example`) has no identity alignment.
4. **Acronym & Substring Traps**: Substring matching (`name_token in netloc`) is completely removed. Brand tokens must match whole SLD labels or approved hyphenated company word combinations.

### Excluded Platforms
Third-party platforms, social networks, directories, and job aggregators are matched using strict hostname boundaries (exact match or subdomain `*.domain.com`), preventing arbitrary substring false positives:
- Social / Community: `linkedin.com`, `facebook.com`, `twitter.com`, `x.com`, `instagram.com`, `youtube.com`, `reddit.com`, `quora.com`.
- Encyclopedias & Registries: `wikipedia.org`, `mca.gov.in`, `cybercrime.gov.in`.
- Aggregators & Job Boards: `indeed.com`, `naukri.com`, `glassdoor.com`, `foundit.in`, `shine.com`, `ambitionbox.com`.

---

## 5. Careers Platform Association Rules

Hosted Applicant Tracking Systems (ATS) such as `greenhouse.io`, `lever.co`, `workday.com`, `myworkdayjobs.com`, `smartrecruiters.com`, `bamboohr.com`, `taleo.net`, and `ashbyhq.com`:
- **Never** serve as an employer's corporate canonical domain.
- **Can** be accepted as an associated `careers_url` **only** if the URL explicitly includes the employer's verified tenant slug in its subdomain (e.g., `wipro.wd3.myworkdayjobs.com`) or initial path segment (e.g., `boards.greenhouse.io/wipro`).
- Generic or unrelated job links whose titles happen to contain the word "career" are strictly rejected.

---

## 6. Internal Diagnostics and Integration Notes for Jay

- **Public API Schemas and Database Models**: Unchanged.
- **Agent Outputs**:
  - `CompanyAgent`:
    - `details["official_domain"]`: String URL (`https://...`) if `RESOLVED`, else `None`.
    - `details["careers_url"]`: String URL if verified, else `None`.
    - `details["canonical_domain"]`: Hostname string (e.g., `"wipro.com"`).
    - `details["official_domain_resolved"]`: Boolean `True` if `RESOLVED`, `False` otherwise.
    - `details["resolution_basis"]`: Human-readable explanation of why the domain was resolved or why candidates were rejected.
    - `details["rejected_candidates"]`: Array of rejected candidate objects with URL, source, and exact rejection reason.
    - `verdict`: `VERIFIED` when domain resolved, `CANNOT_VERIFY` when unresolved or ambiguous.
    - `evidence`: Verified company sources only. Rejected candidates are kept in `details`, never in `evidence`.
  - `RecruiterAgent`:
    - `details["domain_match"]`: `True` if email matches resolved company domain; `False` if employer domain resolved but email differs; `None` if employer domain is unresolved, ambiguous, or search failed.
    - Never verifies recruiter identity without a resolved employer domain.
    - Preserves Task 3 partial provider status and phone report checks.
  - `ReportGenerator`:
    - Continues reading `details["official_domain"]` as the company website URL.

---

## 7. Validation Results and Remaining Limitations

### Test Suite Execution
- **Investigation Suite**: `python -m pytest backend/tests/investigation/ -q`
  - Result: **32 passed, 9 expected failures** (Case 01 lookalike regression now passes!).
- **Domain Resolver Suite**: `python -m pytest backend/tests/test_domain_resolver.py -v`
  - Result: **22 passed, 0 failed** (all 18 Task 4 regression cases verified).
- **Complete Backend Suite**: `cd backend; python -m pytest tests/ -q`
  - Result: **160 passed, 9 expected failures**.

### Remaining Expected Failures (Deferred to Future Tasks)
The 9 remaining expected failures belong to subsequent tasks:
1. `test_case_04_negated_security_deposit_must_not_trigger_fee_demand` (Task 5: contextual scam fee parsing).
2. `test_case_06_ordinary_telegram_mention_must_not_be_high_risk` (Task 5: communication platform parsing).
3. `test_case_07_upfront_fee_must_be_high_risk` (Task 5: fee demand classification).
4. `test_case_08_credential_theft_must_be_critical_risk` (Task 5: OTP theft severity).
5. `test_case_09_payment_to_unlock_job_must_be_high_risk` (Task 5: fee demand classification).
6. `test_case_10_sparse_employer_must_not_be_condemned_as_high_risk` (Task 7: risk engine synthesis).
7. `test_case_13_plausible_details_do_not_confirm_offer_or_fraud` (Task 5: agency vs impersonation review).
8. `test_case_14_agency_recruitment_must_not_be_high_risk_impersonation` (Task 5: recruitment agency review).
9. `test_case_15_candidate_and_recruiter_email_role_separation` (Task 2: entity extraction roles).
