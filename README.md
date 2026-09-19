# AsliOffer — Evidence-Backed Job Offer Verification

[![SerpApi Hackathon 2026](https://img.shields.io/badge/SerpApi%20India%20Hackathon-2026-emerald.svg)](https://serpapi.com)
[![Track](https://img.shields.io/badge/Track-AI%20Agents-blue.svg)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Scammers can copy a company's name, but they cannot fake the company's entire public footprint.**
> 
> AsliOffer is an AI-powered job offer verification platform that cross-references employment claims against live public search data to protect Indian freshers and job seekers from employment fraud in under a minute — with proof.

---

## 1. Problem Statement

Every year, lakhs of students, final-year undergraduates, and fresh graduates in India receive fraudulent job and internship offers via WhatsApp, Telegram, email, and LinkedIn. 

These scams are devastatingly effective because they **borrow the brand names of legitimate, trusted enterprises** (e.g. TCS, Infosys, Wipro, Accenture, India Post, or fast-growing startups).

### The Typical Scam Pattern:
1. **Unsolicited Shortlisting:** Candidate receives an unsolicited message claiming their profile was shortlisted.
2. **Superficial Chat Interview:** A perfunctory chat interview takes place over WhatsApp or Telegram.
3. **Official-Looking Offer:** An offer letter is issued on forged corporate letterhead with realistic CTC figures.
4. **The Catch (Advance Fee Fraud):** The recruiter demands a "refundable laptop security deposit," "screening fee," "gate pass charge," or "training deposit" via UPI or QR code.
5. **Disappearance:** Once payment is made, the recruiter blocks the victim.

Victims lose substantial savings and risk identity theft through shared Aadhaar and bank details. In 2025 alone, the Ministry of Home Affairs recorded over 11,000 online job fraud incidents on the National Cyber Crime Reporting Portal.

---

## 2. Our Core Insight

A genuine job offer leaves an immutable public trail across the internet:

| Verification Surface | Genuine Offer | Fraudulent Offer Pattern |
|---|---|---|
| **Sender Email** | Official corporate domain (`@company.com`) | Free webmail (`@gmail.com`, `@outlook.com`) or lookalikes |
| **Corporate Existence** | Verified MCA registration & active CIN | Unregistered entity or hijacked name |
| **Careers Portal** | Verifiable listing or recruiter registry | No matching openings on official careers site |
| **Compensation** | Realistic market salary bands | Inflated salary bait to induce emotional compliance |
| **Fee Demanded** | **Strictly ₹0** (Complies with Ministry of Labour) | Demands advance deposit for laptop, badge, or training |
| **Public Reports** | Zero fraud advisories | Flagged on CyberDost or scam registries |

A scam almost always breaks **at least one** of these pillars. AsliOffer automates checking all of them in seconds using live public search data.

---

## 3. Architecture Overview

```
User Upload
    │
    ▼
Extraction Layer
    │
    ▼
Entity Extraction
    │
    ▼
Investigation Agents
 ├── Company Agent
 ├── Recruiter Agent
 ├── Salary Agent
 └── Scam Agent
    │
    ▼
Risk Engine
    │
    ▼
Evidence Report
```

### Risk Classification Matrix:
To avoid misleading binary reassurance, AsliOffer classifies offers into three evidence-backed tiers:
- **`VERIFIED`**: Credentials match the company's authentic public footprint, legitimate domain, no advance fees.
- **`NEEDS_REVIEW`**: Ambiguous third-party agency, unverified recruiter identity, or salary anomaly.
- **`HIGH_RISK`**: Advance fee demand detected, personal webmail used for corporate hiring, or known fraud pattern.

> **Note on Current MVP Version:** The current release is an initial production-grade MVP featuring clean architectural interfaces, SQLModel database models, responsive frontend UI, and mocked agent investigation responses. Live SerpApi and Gemini 2.5 Flash keys can be configured in `.env` to test live endpoints.

---

## 4. Repository Structure

```
aslioffer/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── routers/
│   │   │           ├── analysis.py        # POST /analysis/run
│   │   │           ├── offers.py          # POST /offers/upload, GET /offers/{id}, /report
│   │   │           └── health.py          # GET /health
│   │   ├── core/
│   │   │   ├── config.py                  # Pydantic Settings & environment variables
│   │   │   └── logging.py                 # Structured application logging
│   │   ├── db/
│   │   │   ├── session.py                 # Engine & Session generator (Postgres/SQLite)
│   │   │   └── models/
│   │   │       ├── offer.py               # Offer model
│   │   │       ├── company.py             # Company model
│   │   │       ├── recruiter.py           # Recruiter model
│   │   │       └── evidence.py            # Evidence model
│   │   ├── schemas/
│   │   │   ├── offer.py                   # Request/response schemas
│   │   │   └── analysis.py                # Agent findings & report schemas
│   │   ├── services/
│   │   │   ├── extractor/
│   │   │   │   └── entity_extractor.py    # Regex & NLP entity extraction
│   │   │   ├── agents/
│   │   │   │   ├── company_agent.py       # Corporate & MCA verification
│   │   │   │   ├── recruiter_agent.py     # Email domain & contact audit
│   │   │   │   ├── salary_agent.py        # Compensation benchmark checks
│   │   │   │   └── scam_agent.py          # Advance fee & fraud detection
│   │   │   ├── search/
│   │   │   │   └── serpapi_client.py      # SerpApi client contract & fallback
│   │   │   ├── ai/
│   │   │   │   └── gemini_client.py       # Gemini 2.5 Flash client contract
│   │   │   ├── graph/
│   │   │   │   └── graph_builder.py       # Graph entity linking & cluster stub
│   │   │   ├── risk/
│   │   │   │   └── risk_engine.py         # Evidence-weighted scoring engine
│   │   │   └── report/
│   │   │       └── report_generator.py    # Forensic report compilation
│   │   └── main.py                        # FastAPI application entrypoint
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── EvidenceCard.tsx           # Verifiable live source citations
│   │   │   ├── FileUpload.tsx             # Drag-drop & text input with presets
│   │   │   ├── EntityPanel.tsx            # Extracted claims & flag badges
│   │   │   ├── RiskBadge.tsx              # VERIFIED / NEEDS_REVIEW / HIGH_RISK
│   │   │   └── Navbar.tsx                 # Brand navigation & status
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx              # Verification overview & case studies
│   │   │   ├── Upload.tsx                 # Offer ingestion & agent pipeline
│   │   │   └── OfferReport.tsx            # Comprehensive forensic report
│   │   ├── services/
│   │   │   └── api.ts                     # Typed API client with mock fallbacks
│   │   ├── types/
│   │   │   └── index.ts                   # TypeScript interfaces
│   │   ├── App.tsx                        # Client routing
│   │   ├── main.tsx                       # React DOM entrypoint
│   │   └── index.css                      # Tailwind styling & glassmorphism
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── docker/
│   ├── Dockerfile.backend                 # Multi-stage Python 3.12 image
│   └── Dockerfile.frontend                # Multi-stage Node 22 + Nginx image
├── docs/
│   └── architecture.md                    # In-depth architectural blueprint
├── docker-compose.yml                     # Full orchestration (App, DB, Redis)
├── .env.example
├── .gitignore
└── README.md
```

---

## 5. Local Setup Instructions

### Prerequisites
- **Python 3.12+**
- **Node.js 20+** and **npm**
- (Optional) **Docker** & **Docker Compose**

---

### Option A: Running with Docker Compose (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/jaypatel345/aslioffer.git
   cd aslioffer
   ```

2. Configure environment variables:
   ```bash
   cp .env.example .env
   ```

3. Launch all services:
   ```bash
   docker compose up --build
   ```

4. Access the application:
   - **Frontend UI:** [http://localhost:3000](http://localhost:3000) (or `http://localhost:5173`)
   - **Backend API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

### Option B: Running Locally for Development

#### 1. Backend Setup:
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

# Run FastAPI dev server (default SQLite local storage requires zero DB setup)
uvicorn app.main:app --reload --port 8000
```

#### 2. Frontend Setup:
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 6. Environment Variables

| Variable | Description | Default / Example |
|---|---|---|
| `SERPAPI_API_KEY` | SerpApi key for live Google web/jobs search | `""` (Uses mock engine when blank) |
| `GEMINI_API_KEY` | Google Gemini API key for multimodal extraction | `""` (Uses mock engine when blank) |
| `GEMINI_MODEL` | Gemini model version | `gemini-2.5-flash` |
| `DATABASE_URL` | SQLModel database connection string | `sqlite:///./aslioffer.db` or PostgreSQL |
| `REDIS_URL` | Redis instance for search caching | `redis://localhost:6379/0` |
| `VITE_API_BASE_URL` | API base URL for frontend client | `http://localhost:8000` |

---

## 7. API Endpoints Specification

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System health check and service status |
| `POST` | `/offers/upload` | Ingest offer document (PDF/screenshot) or text payload |
| `POST` | `/analysis/run` | Execute multi-agent forensic verification |
| `GET` | `/offers/{id}` | Fetch offer metadata by ID |
| `GET` | `/offers/{id}/report` | Retrieve complete forensic evidence report |

Interactive Swagger documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## 8. Future Roadmap

- [ ] **Gmail Ingestion:** 1-click Chrome extension / OAuth integration to audit recruiter emails directly from inboxes.
- [ ] **Neo4j Syndicate Graph:** Graph-based correlation of phone numbers, UPI handles, and domains across reported scam syndicates.
- [ ] **Automated NCRP Filing:** 1-click generation of formatted incident complaint drafts for the National Cyber Crime Portal ([cybercrime.gov.in](https://cybercrime.gov.in)).
- [ ] **Community Intelligence Hub:** Crowdsourced scam registry allowing freshers to verify burner numbers and Telegram handles.
- [ ] **WhatsApp & Telegram Bot:** Direct forwarding of suspicious messages for instant mobile verification.

---

## 9. Acknowledgments

Developed for the **SerpApi India Hackathon 2026** under the **AI Agents Track**.  
National Cyber Crime Reporting Portal helpline: **1930** | [cybercrime.gov.in](https://cybercrime.gov.in).
