# AsliOffer — Is this job offer real?

> An AI agent that checks a job or internship offer against live public search data and tells Indian freshers, in under a minute, whether the offer is genuine or a scam — with proof.

**Hackathon:** SerpApi India Hackathon 2026
**Track:** AI Agents
**Submission deadline:** October 5, 2026, 23:59 IST

---

## The Problem

Every year, lakhs of students and freshers in India receive job and internship "offers" on WhatsApp, Telegram, email and even LinkedIn. Many of them are fake.

These scams are hard to spot because they **borrow the name of a real company**. The message looks like it came from TCS, Infosys, Accenture, India Post, or a well-known startup. The salary sounds realistic. The recruiter is polite and professional. Sometimes there is even an offer letter on what looks like official company letterhead.

A typical scam goes like this:

1. A "recruiter" messages you saying your profile has been shortlisted.
2. You get a quick "interview" over chat or call.
3. You receive an offer letter that looks official.
4. Then comes the catch: pay a "registration fee", "training fee", "security deposit" or "laptop charge" — or share your Aadhaar, bank details or OTP.
5. After you pay, the recruiter disappears.

By the time money is asked for, the victim is already emotionally invested and believes the job is real.

### Why this matters

- **The victims are the most vulnerable job seekers** — final-year students, fresh graduates, laid-off employees, and people looking for work-from-home income. They want the job to be real, which makes them easier to fool.
- **The losses are real** — money paid through UPI is very hard to recover after the first few hours, and shared personal documents can be misused later (for example, opening bank accounts in the victim's name).
- **The problem is growing** — the Ministry of Home Affairs reported 11,126 online job-fraud incidents in 2025 on the National Cyber Crime Reporting Portal, and that figure covered only complaints related to women, so the real total is much higher ([source](https://pulseofnoida.com/education/skill-development-careers/job-internship-scams-india-red-flags-3122/)).
- **Companies and the government keep issuing warnings** — India Post, IT companies and the government's CyberDost initiative have all warned about fake offer letters using their names.

### Why people still get fooled

The official advice is simple: *"Verify the employer before accepting the offer."*

But in practice, a fresher does not know **how** to verify. It means manually:

- finding the company's real website (not the one in the message),
- checking whether the recruiter's email actually belongs to that company,
- searching whether this job opening really exists,
- checking whether the office address in the letter is real,
- checking whether the salary makes sense for the role,
- searching whether other people have reported the same number, handle or message as a scam.

This takes time, effort and know-how. Most people skip it — especially when the "recruiter" is pressuring them to reply quickly.

---

## Our Key Insight

**A scammer can copy a company's name, but cannot fake the company's whole public footprint.**

A genuine job offer leaves a consistent trail across the internet:

| A real offer... | A fake offer usually... |
|---|---|
| comes from an email on the company's official domain | comes from Gmail, Outlook, or a look-alike domain |
| matches a real job listing from that company | has no matching opening anywhere |
| has a salary within the normal market range | offers an unusually high salary for little work |
| lists a real office address belonging to that company | lists a fake, residential or unrelated address |
| never asks for money | asks for a "fee", "deposit" or UPI payment |
| has no scam reports against it | has a phone number, handle or pattern already reported online |

A scam almost always breaks **at least one** of these. Live search data lets us check all of them automatically, in seconds.

---

## What We Are Building

**AsliOffer** is an AI agent that does this verification work for the job seeker.

**The user gives us:** the offer they received — pasted message text, a screenshot, or the offer letter PDF.

**The user gets back:**

1. **A clear verdict** — *Likely Genuine*, *Suspicious*, or *Likely Scam*.
2. **The reasons, with proof** — every red flag or green flag comes with a link to the source we found, so the user can check it themselves.
3. **The company's real contact** — the official website and careers page, so the user can confirm directly with the real HR team.
4. **What to do next** — if it looks like a scam: don't pay, don't share documents, report at [cybercrime.gov.in](https://cybercrime.gov.in) or call the national cybercrime helpline **1930**.

### Who it is for

- **Students and freshers** checking an offer before replying.
- **Job seekers** looking for work-from-home or part-time work, where task scams are common.
- **College placement cells** that want to warn students about fake recruiters using their college's or a company's name.

---

## What Success Looks Like

- A fresher can paste an offer and get a trustworthy answer in **under a minute**.
- Every verdict is **backed by evidence**, not just an AI's opinion.
- The agent **never sounds more confident than the evidence allows** — if it cannot verify something, it says so honestly.
- The user comes away knowing **how to protect themselves**, not just whether this one offer is fake.

---

## What This Project Is NOT

- It is **not a job search tool** — it does not find jobs, it verifies offers the user already has.
- It is **not a general fact-checker** — it focuses only on job and internship offers.
- It does **not** give legal advice or recover lost money — it helps people avoid losing it in the first place and points them to official reporting channels.

---

## One-Line Summary for the Team

> **Scammers borrow real company names; AsliOffer checks the company's real public footprint using live search data and tells freshers — with proof — whether an offer is genuine before they pay or share anything.**
