# Role: AI/Prompt Engineer

**Owner:** Jaswanth Kumar, Shriraj
**Goal:** Extract entities from the offer and drive the final verdict (Genuine / Suspicious / Scam) reasoning.

## Tasks

- [x] Define `ExtractedData` JSON shape: `{company, recruiter_email, salary, address, raw_text}`
- [x] Build extraction prompt for pasted text input
- [x] Build extraction prompt/flow for screenshot input (OCR text → extraction)
- [x] Build extraction prompt/flow for PDF offer letter input
- [ ] Test extraction against mock SerpApi fixture data (don't wait on real search integration)
- [x] Define `AgentResult` input shape consumed from each agent: `{flag, reason, evidence_url, confidence}`
- [x] Build Risk Engine reasoning: combine 4 agent results → final verdict
- [x] Write verdict output format: `{verdict, confidence, reasons[], evidence[]}`
- [x] Handle "cannot verify" case honestly (no false confidence)
- [ ] Integrate with real SerpApi Agent outputs (once ready)
- [ ] Test against 5+ real scam examples + 5+ real genuine examples
- [ ] Handoff to Backend Dev for API wiring

## Blockers
_(none)_

## Status
In progress

## Last updated
2026-09-21
