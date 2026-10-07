# AsliOffer — Case Study

**Context:** SerpApi India Hackathon 2026, AI Agents track.
**Team:** Built with a teammate. Git history shows two contributors: Jay Patel (19 commits) and shriza1991 (34 commits).
**Status:** Runs locally with Docker Compose or separate dev servers. A Render blueprint (`render.yaml`) is in the repo, but I found no live URL, so it is not listed as deployed.

## Problem
Indian freshers get fake job offers that ask for upfront "fees" or bank OTPs, and they have no quick way to check if an offer is real.

## What I built
An AI agent that reads a job offer (pasted text or an uploaded document) and checks the company, the recruiter, the salary and the wording against live public search data from SerpApi.
It returns a verdict of `VERIFIED`, `NEEDS_REVIEW` or `HIGH_RISK`, and shows the evidence behind it. When the evidence is too thin, it says it cannot verify the offer instead of guessing.

## Features
- Company, recruiter, salary and scam agents each check one part of the offer against live search results.
- A domain resolver flags lookalike domains and personal webmail used for "corporate" hiring.
- A scam classifier spots fee demands, OTP/credential requests and task scams. It understands context, so "we never charge fees" or a quoted scam warning is not flagged.
- An adaptive planner runs extra searches to fill evidence gaps, within a set search budget and time limit.
- The report links each claim to its source and suggests an independent way to confirm the offer with the employer.
- Document reading uses Groq vision first and falls back to Gemini.
- *Planned only (README roadmap):* Gmail ingestion, WhatsApp/Telegram bot, automatic NCRP complaint drafts, a community scam registry, and a Neo4j graph of scam syndicates.

## Stack
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, React Router
- **Backend:** Python 3.12, FastAPI, SQLite (default local storage)
- **Data and AI:** SerpApi (live search), Groq (main LLM and vision), Gemini (fallback)
- **Delivery:** Docker / Docker Compose, Render blueprint (`render.yaml`), versioned API contract (`docs/api-contract.md`)

## Result
The repo's offline evaluation runs 24 labelled scenarios and passes all 24: no legitimate offer marked `HIGH_RISK` (0/9) and every fee/OTP threat flagged (0/5 missed). Source: `backend/app/evaluation/output/evaluation_summary.md`. These are deterministic test cases with mocked search, not results from real users.
