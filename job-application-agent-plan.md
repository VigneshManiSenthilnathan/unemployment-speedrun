# AI Job Application Agent — Architecture & Build Plan

## Overview

You are the **job curator**. The agent is the **application executor**.

Your workflow is simple:
1. Paste a raw job application URL into a Google Sheet
2. The agent fetches the page, extracts all metadata (company, role, JD, requirements) automatically
3. It classifies the portal, fills the application, generates a cover letter if needed, and logs everything back to the sheet

No manual data entry beyond the URL.

---

## High-Level Architecture

```
[Google Sheet: URLs]
        │
        ▼
[Job Intelligence Module]
  - Fetch JD from URL
  - Extract: company, role, location, requirements, portal type
  - Score fit against your profile
  - Write metadata back to sheet
        │
        ▼
[Application Executor]
  - Classify ATS platform
  - Route to platform handler or generic LLM handler
  - Fill fields using personal data JSON
  - Handle account creation if required
  - Generate & attach cover letter
        │
        ▼
[Review Gate (Streamlit UI)]
  - Show cover letter for approval
  - Pause on uncertain pages
  - Manual override option
        │
        ▼
[Logger]
  - Write status back to Google Sheet
  - Store screenshots, cover letters, credentials in SQLite
```

---

## Google Sheet Schema

You only need to paste the URL. Everything else is auto-populated by the agent.

| Column | Input | Source |
|---|---|---|
| `application_url` | **You paste this** | Manual |
| `company` | Auto-extracted | Agent (LLM) |
| `role` | Auto-extracted | Agent (LLM) |
| `location` | Auto-extracted | Agent (LLM) |
| `employment_type` | Auto-extracted | Agent (LLM) |
| `jd_summary` | Auto-generated | Agent (LLM) |
| `fit_score` | Auto-scored (1–10) | Agent (LLM) |
| `fit_reasoning` | Auto-generated | Agent (LLM) |
| `portal_type` | Auto-detected | Agent (classifier) |
| `status` | Updated live | Agent |
| `date_applied` | Auto-filled | Agent |
| `notes` | Optional | You / Agent |

**Status values:** `Pending` → `Extracting` → `Ready` → `Applying` → `Applied` / `Failed` / `Needs Review`

---

## Module Breakdown

### Module 1: Job Intelligence Module

**Trigger:** New row with `status = Pending`

**Steps:**
1. Fetch the page HTML using Playwright (handles JS-rendered pages)
2. Extract clean text (strip nav/footer boilerplate)
3. Send to Claude API with structured extraction prompt
4. LLM returns JSON: `{ company, role, location, employment_type, requirements[], jd_summary, portal_type }`
5. Score fit against your preference profile JSON (role targets, location, seniority, industries to avoid)
6. Write all fields back to the sheet, set `status = Ready`
7. Pause if `fit_score < threshold` (configurable, e.g. 6) — flag as `Low Fit` for your review

**LLM Extraction Prompt Structure:**
```
You are a job data extractor. Given the following job page content, return a JSON object with:
- company (string)
- role (string)
- location (string)
- employment_type (full-time / internship / contract)
- requirements (list of strings)
- jd_summary (2-sentence summary)
- portal_type (greenhouse / lever / workday / custom / unknown)

Job page content:
{page_text}
```

---

### Module 2: Application Executor

**Trigger:** Rows with `status = Ready` (or manual trigger per row)

#### Step 2a: ATS Platform Classification

The agent classifies the portal on landing:

| Platform | Detection Signal | Difficulty |
|---|---|---|
| Greenhouse | `boards.greenhouse.io` in URL or DOM | ⭐ Easy |
| Lever | `jobs.lever.co` in URL | ⭐ Easy |
| Workday | `myworkdayjobs.com` or Workday React shell | ⭐⭐⭐ Hard |
| iCIMS | `icims.com` in URL | ⭐⭐ Medium |
| Taleo | `taleo.net` in URL | ⭐⭐ Medium |
| Custom portal | None of the above | ⭐⭐ Medium (LLM-driven) |

**Routing logic:**
- Known platform → use **platform-specific handler** (pre-built, deterministic)
- Unknown platform → use **generic LLM-driven handler** (observe → reason → act loop)

#### Step 2b: Platform-Specific Handlers

Pre-built handlers for Greenhouse and Lever first (highest coverage for tech roles):

```
Greenhouse Handler:
  1. Click "Apply for this job"
  2. Fill: first name, last name, email, phone, resume upload
  3. Fill: LinkedIn URL, portfolio, location fields
  4. Handle custom questions (route to LLM for open-text answers)
  5. Submit

Lever Handler:
  1. Click "Apply"
  2. Fill standard fields from personal data JSON
  3. Handle "Additional Information" free-text with LLM
  4. Submit
```

#### Step 2c: Generic LLM-Driven Handler

For custom portals, the agent uses a **perceive → reason → act loop**:

```
Loop:
  1. Take screenshot + extract visible DOM text
  2. Send to Claude:
     "You are filling a job application. Current page: {page_content}
      Applicant data available: {personal_data_keys}
      What is the single next action? Return JSON: {action, selector, value}"
  3. Execute action via Playwright
  4. Repeat until confirmation page detected or max steps reached
```

Actions the LLM can emit:
- `{ "action": "fill", "selector": "#email", "value": "..." }`
- `{ "action": "click", "selector": "button[type=submit]" }`
- `{ "action": "upload", "selector": "#resume", "file": "resume.pdf" }`
- `{ "action": "select", "selector": "#country", "value": "Singapore" }`
- `{ "action": "pause", "reason": "Unexpected CAPTCHA detected" }`
- `{ "action": "done", "reason": "Confirmation page detected" }`

#### Step 2d: Account Creation Handling

Triggered when the agent detects a login/signup wall:

1. Check SQLite credentials store — has an account for this domain already been created?
2. If yes → log in with stored credentials
3. If no → detect if "Sign in with Google" is available
   - If yes → use Playwright to handle the Google OAuth popup using a stored browser session
   - If no → fill email/password signup form using your Gmail address + a generated password
4. Store new credentials immediately: `{ domain, email, password, date_created }`
5. Continue to application form

> **Security note:** Store credentials using Python's `keyring` library (OS-level encrypted store), not plain text or SQLite.

---

### Module 3: Cover Letter Generator

**Triggered when:** Application form contains a cover letter field or upload prompt.

**Inputs:**
- Full job description text
- Your resume JSON (structured)
- Company name and role title
- Any detected "why us" or "motivation" signals from the JD

**Output:** A tailored 3-paragraph cover letter

**Prompt structure:**
```
Write a professional cover letter for the following role.

Role: {role} at {company}
Job description summary: {jd_summary}
Key requirements: {requirements}

Applicant background:
{resume_json}

Instructions:
- 3 paragraphs: hook + fit + close
- Concise, no filler phrases like "I am excited to apply"
- Reference 1–2 specific things from the JD
- Do not exceed 350 words
```

**Delivery:**
- For text fields: paste directly into form
- For file upload fields: render to PDF using `weasyprint`, upload via Playwright

---

### Module 4: Human Review Gate

Built in **Streamlit** for speed. The agent pauses and pushes a review card when:

- A cover letter has been generated (always reviewed before submission)
- The agent classifies a page as `uncertain` (confidence < threshold)
- The application is for a company flagged as `high_priority` in your preferences
- Any open-ended essay question is detected beyond a standard cover letter

**Review card shows:**
- Job title, company, fit score
- Cover letter draft (editable inline)
- Screenshot of current application state
- Approve / Edit / Skip / Mark Failed buttons

---

### Module 5: Logger

After each application attempt:

- Update Google Sheet row: `status`, `date_applied`, `notes`
- Save to SQLite: full action log, screenshots at each step, cover letter text, portal type
- Archive cover letter PDF to a local `/cover_letters/` folder named `{company}_{role}_{date}.pdf`

---

## Personal Data Store

A single `applicant_profile.json` file the agent references for all field filling:

```json
{
  "personal": {
    "full_name": "",
    "email": "",
    "phone": "",
    "address": "",
    "linkedin_url": "",
    "github_url": "",
    "portfolio_url": "",
    "nationality": "",
    "work_authorization": ""
  },
  "education": {
    "university": "",
    "degree": "",
    "major": "",
    "gpa": "",
    "graduation_date": "",
    "relevant_courses": []
  },
  "experience": [
    {
      "company": "",
      "role": "",
      "start_date": "",
      "end_date": "",
      "description": ""
    }
  ],
  "skills": [],
  "preferences": {
    "target_roles": [],
    "target_industries": [],
    "excluded_companies": [],
    "locations": [],
    "remote_preference": "hybrid",
    "min_salary": null,
    "fit_score_threshold": 6
  }
}
```

Files also needed:
- `resume.pdf` — for upload fields
- `transcript.pdf` — for portals that request it
- `resume.json` — structured version for LLM context (mirrors the profile above but narrative-form)

---

## Tech Stack

| Component | Tool | Notes |
|---|---|---|
| Job queue | Google Sheets + `gspread` | Only column you fill is the URL |
| Browser automation | `playwright` (Python) | Handles JS-heavy portals |
| LLM orchestration | Claude API (`claude-sonnet-4-6`) | Tool calling for structured actions |
| Personal data | Local JSON file | Manually maintained by you |
| Credential storage | Python `keyring` | OS-encrypted, never plaintext |
| Cover letter PDF | `weasyprint` | HTML → PDF rendering |
| Application logging | SQLite (`sqlite3`) | Job history, screenshots, cover letters |
| Review UI | Streamlit | Human checkpoint before submission |
| Scheduling | APScheduler | Poll sheet every N minutes |

---

## Build Phases

### Phase 1 — Foundation (Week 1)
- [ ] Set up Playwright environment, write atomic browser tools (`click`, `fill`, `upload`, `screenshot`, `get_text`)
- [ ] Create `applicant_profile.json` with your real data
- [ ] Connect to Google Sheets via `gspread`, implement row polling for `status = Pending`
- [ ] Test Playwright can navigate to a Greenhouse and Lever URL and extract page text

### Phase 2 — Job Intelligence (Week 1–2)
- [ ] Build the LLM extraction call: URL → `{ company, role, location, jd_summary, portal_type }`
- [ ] Implement fit scoring against your preference profile
- [ ] Write extracted metadata + fit score back to Google Sheet
- [ ] Validate on 10 real job URLs across different portal types

### Phase 3 — Application Execution: Easy Platforms (Week 2–3)
- [ ] Build Greenhouse handler (deterministic field mapping)
- [ ] Build Lever handler
- [ ] Test end-to-end on real applications (use a test email address first)
- [ ] Add cover letter generator + PDF export

### Phase 4 — Generic LLM Handler + Account Creation (Week 3–4)
- [ ] Build the observe → reason → act loop for unknown portals
- [ ] Implement account creation detection and Google OAuth flow
- [ ] Add `keyring`-based credential storage
- [ ] Test on 3–5 custom company portals

### Phase 5 — Review UI + Logging (Week 4)
- [ ] Build Streamlit review gate with approve/edit/skip actions
- [ ] Build SQLite logger (action log, cover letters, screenshots)
- [ ] Implement status writeback to Google Sheet

### Phase 6 — Workday + Edge Cases (Week 5+)
- [ ] Tackle Workday (dynamic React shell — will require extra Playwright wait logic and possibly vision-based element detection)
- [ ] Handle CAPTCHA detection (pause and alert rather than attempt to solve)
- [ ] Handle multi-step applications (pagination across multiple pages)
- [ ] Add retry logic and error recovery

---

## Known Hard Problems

| Problem | Mitigation |
|---|---|
| Workday's dynamic React UI | Use `page.wait_for_selector()` aggressively; consider vision-based approach with screenshots |
| CAPTCHAs | Detect and pause — never attempt to auto-solve |
| Session timeouts on long forms | Save progress checkpoints; re-login if session expires |
| Portals that ban automation | Use realistic mouse movement (`playwright-stealth`), randomised delays between actions |
| Multi-page applications | Track current step, loop until confirmation page signal detected |
| PDFs parsed incorrectly as JD | Fallback to LLM vision mode if text extraction fails |

---

## What This Does NOT Handle

- **LinkedIn Easy Apply** — you do this manually
- **Referral-based applications** — requires human judgment
- **Video interview scheduling** — agent flags these for your attention
- **Paid job portal subscriptions** — agent works with sessions you're already logged into
