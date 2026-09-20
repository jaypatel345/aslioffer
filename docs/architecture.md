# AsliOffer System Architecture & Technical Specification

## 1. System Vision & Objective

**AsliOffer** is an evidence-backed job and internship offer verification platform specifically engineered to defend Indian freshers, college placement candidates, and vulnerable job seekers against employment fraud.

Rather than relying purely on LLM hallucinations or static pattern matching, AsliOffer operationalizes a fundamental truth:

> **Scammers can copy a corporate logo, but they cannot fake a company's entire public footprint.**

A genuine offer leaves an immutable public footprint across multiple authoritative surfaces:
- Official corporate domains (`@company.com` vs `@gmail.com` or lookalike domains).
- Ministry of Corporate Affairs (MCA) active registration and Corporate Identification Number (CIN).
- Live careers portal listings and published anti-fraud recruitment policies.
- Realistic salary bands cross-checked against market registries (AmbitionBox, Glassdoor).
- Zero monetary demands (legitimate employers strictly comply with Ministry of Labour guidelines prohibiting candidate fees).

---

## 2. End-to-End Pipeline Architecture

```
                 ┌────────────────────────────────────────────────┐
                 │                  User Input                    │
                 │  (PDF Offer Letter, Screenshot, Email, Text)   │
                 └───────────────────────┬────────────────────────┘
                                         │
                                         ▼
                 ┌────────────────────────────────────────────────┐
                 │                Extraction Layer                │
                 │  (EntityExtractor / Gemini 2.5 Flash Multimodal)│
                 │  - Target Company & CIN                        │
                 │  - Recruiter Name, Phone, Email Domain         │
                 │  - Role Title, CTC, Job Location               │
                 │  - Advance Fee Demands & Payment Rails (UPI)   │
                 └───────────────────────┬────────────────────────┘
                                         │
                                         ▼
                     Investigation Agent Federation
         ┌───────────────────────────────┼───────────────────────────────┐
         │                               │                               │
         ▼                               ▼                               ▼
 ┌───────────────┐               ┌───────────────┐               ┌───────────────┐
 │ CompanyAgent  │               │RecruiterAgent │               │  SalaryAgent  │
 │ - SerpApi Web │               │ - Domain MX   │               │ - AmbitionBox │
 │ - MCA Portal  │               │ - Webmail vs  │               │   Benchmark   │
 │ - Careers URL │               │   Corp Domain │               │ - CTC Anomaly │
 └───────┬───────┘               └───────┬───────┘               └───────┬───────┘
         │                               │                               │
         └───────────────────────┬───────┴───────────────────────────────┘
                                 │
                                 ▼
                         ┌───────────────┐
                         │   ScamAgent   │
                         │ - Fee Demands │
                         │ - UPI / QR    │
                         │ - CyberDost   │
                         └───────┬───────┘
                                 │
                                 ▼
                 ┌────────────────────────────────────────────────┐
                 │                  Risk Engine                   │
                 │  - Evidence-weighted deterministic scoring     │
                 │  - VERIFIED / NEEDS_REVIEW / HIGH_RISK tiers  │
                 └───────────────────────┬────────────────────────┘
                                         │
                                         ▼
                 ┌────────────────────────────────────────────────┐
                 │           Evidence & Action Report             │
                 │  - Red & Green Flag Audit                      │
                 │  - Live Source Citations (URLs)                │
                 │  - Official Employer HR Contacts               │
                 │  - NCRP 1930 Cyber Helpline & Guidance         │
                 └────────────────────────────────────────────────┘
```

---

## 3. Investigation Agents Specification

Each agent operates on a strict contract (`investigate(...) -> AgentFinding`), enabling parallel asynchronous dispatch and independent caching:

### 1. `CompanyAgent`
- **Objective:** Verify whether the purported employer has an authentic corporate footprint.
- **Search Queries:**
  - `"{company_name} official website careers"`
  - `"{company_name} MCA CIN registration status"`
- **Verdicts:** `VERIFIED`, `UNVERIFIED`

### 2. `RecruiterAgent`
- **Objective:** Detect impersonation through domain discrepancy and unverified webmail addresses.
- **Rules:**
  - If communication originates from free email providers (`gmail.com`, `outlook.com`, `yahoo.com`) for an established enterprise -> **Immediate `HIGH_RISK` flag**.
  - If sender domain matches corporate MX record -> **`VERIFIED`**.

### 3. `SalaryAgent`
- **Objective:** Detect inflated compensation packages used as emotional hooks.
- **Rules:**
  - Benchmarks entry-level compensation against AmbitionBox / Glassdoor percentile data.
  - Flags unrealistic promises (e.g., ₹50,000/day or ₹60 LPA for freshers) as `NEEDS_REVIEW`.

### 4. `ScamAgent`
- **Objective:** Detect illegal monetary solicitations and known scam syndicate signatures.
- **Rules:**
  - Advance fee demand (laptop deposit, training fee, gate pass, processing charge) -> **Deterministic `HIGH_RISK`**.
  - UPI / QR code payment instructions -> **Immediate scam warning**.
  - Cross-checks against Ministry of Home Affairs CyberDost advisories.

---

## 4. Risk Classification Matrix

To prevent misleading reassurance or unwarranted accusations, AsliOffer rejects simplistic binary labels ("Definitely Real" / "Definitely Fake") in favor of three evidence-backed tiers:

| Tier | Risk Score Band | Meaning | Primary Trigger Conditions |
|---|---|---|---|
| **`VERIFIED`** | 0.00 – 0.24 | Consistent public footprint | Official email domain, registered MCA entity, zero fees, realistic salary |
| **`NEEDS_REVIEW`** | 0.25 – 0.49 | Ambiguous credentials | Unverified third-party recruitment agency, salary outlier, incomplete contact info |
| **`HIGH_RISK`** | 0.50 – 1.00 | Severe scam hallmarks detected | Advance fee demand, UPI payment link, free webmail for enterprise recruiter |

---

## 5. Future Extensibility Roadmap

1. **Gmail OAuth Ingestion:** Direct 1-click verification of recruiter emails from the candidate's inbox.
2. **Neo4j Syndicate Graph Database:**
   - Map relationships: `(:Recruiter)-[:USES_PHONE]->(:Phone)` and `(:Offer)-[:DEMANDS_UPI]->(:UPI)`.
   - Run Louvain community clustering to detect organized scam syndicates using rotating company identities.
3. **Automated NCRP Filing:**
   - 1-click generation of structured complaint drafts for the National Cyber Crime Reporting Portal ([cybercrime.gov.in](https://cybercrime.gov.in)).
4. **Community Intelligence Hub:**
   - Allow candidates to report fraudulent numbers and handles with crowdsourced verification.
