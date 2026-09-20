# Role: SerpApi/Search Integration Dev

**Owner:** Jay
**Goal:** Run live search calls for each verification check and return structured evidence.

## Tasks

- [ ] Get SerpApi key + test basic query works
- [ ] Define shared `AgentResult` output shape: `{flag, reason, evidence_url, confidence}`
- [ ] Company Agent: search company domain + careers page + verify address
- [ ] Recruiter Agent: search whether recruiter email/domain belongs to the company
- [ ] Salary Agent: search market salary range for role/location, compare to offer
- [ ] Scam Agent: search phone number/handle/message pattern for existing scam reports
- [ ] Build mock fixture JSON (fake search results) so AI Engineer can build against it early
- [ ] Add error handling for no-results / ambiguous-results cases (return "unverifiable", not a guess)
- [ ] Rate-limit / caching so repeated demo runs don't burn API quota
- [ ] Unit test each agent function standalone (input: entity → output: AgentResult)
- [ ] Handoff functions to AI Engineer for Risk Engine integration

## Blockers
_(list anything blocking you)_

## Status
Not started / In progress / Done

## Last updated
_(date)_
