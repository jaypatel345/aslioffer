# Role: Backend/API Dev

**Owner:** Soyab
**Goal:** Connect Frontend → AI Agent → SerpApi, handle input parsing and response formatting.

## Tasks

- [ ] Define API route(s): e.g. `POST /verify-offer`
- [ ] Build mock response endpoint FIRST (fake JSON) so Frontend can build against it immediately
- [ ] Handle input parsing: pasted text
- [ ] Handle input parsing: screenshot upload (OCR)
- [ ] Handle input parsing: PDF upload
- [ ] Wire Extraction Layer output → Investigation Agents call
- [ ] Wire Agent results → Risk Engine → final response
- [ ] Define final API response shape: `{verdict, confidence, reasons[], evidence[], official_contact}`
- [ ] Add error handling (bad upload, empty input, API timeout)
- [ ] Add basic request logging for debugging demo runs
- [ ] Deploy/host backend (or run locally for demo — decide early)
- [ ] Integrate real AI Agent + SerpApi logic once ready (replace mocks)
- [ ] End-to-end test with Frontend

## Blockers
_(list anything blocking you)_

## Status
Not started / In progress / Done

## Last updated
_(date)_
