# Job Application Agent — Progress & Handoff

## What has been built

### Phase 1 — Foundation ✅
- **`browser/tools.py`** — Async Playwright wrappers: `init_browser`, `navigate`, `get_text`, `click`, `fill`, `select_option`, `upload`, `screenshot`, `screenshot_b64`, `wait_for_url`, `current_url`, `close_browser`
  - Uses a single global browser/context/page instance
  - Windows `ProactorEventLoop` is required and set in `main.py` — do NOT set `WindowsSelectorEventLoopPolicy` anywhere (breaks Playwright subprocess spawning)
- **`sheets/client.py`** — `SheetsClient` class: connects via service account JSON, polls for `status = Pending` rows, `update_row`, `set_status`
- **`main.py`** — Fully async entry point using `AsyncIOScheduler` (APScheduler). Single `asyncio.run(main_async())` call keeps one `ProactorEventLoop` alive for the whole process
- **`applicant_profile.json`** — Populated with real profile data (Vignesh)
- **`pyproject.toml`** — uv project, all deps installed
- **`SETUP.md`** — Google Cloud service account setup instructions
- **`.env`** — Contains real credentials (gitignored)
- **`assets/resume.pdf`**, **`assets/resume.json`** — Present locally (gitignored)

### Phase 2 — Job Intelligence Module ✅
- **`prompts/extraction.py`** — Two Claude prompt templates:
  - `EXTRACTION_SYSTEM/USER` — structured extraction of company, role, location, employment_type, requirements, jd_summary, portal_type
  - `FIT_SCORING_SYSTEM/USER` — 1–10 fit score + reasoning sentence against applicant preferences
- **`modules/job_intelligence.py`** — Full async pipeline:
  1. Fetch page via headless Playwright (up to 12k chars)
  2. Claude `claude-sonnet-4-6` extraction call → JSON
  3. Claude fit scoring call → `{ fit_score, fit_reasoning }`
  4. Writeback all fields to Google Sheet
  5. Status → `Ready` if score ≥ threshold, `Low Fit` if below

**Verified working:** Partners Group job URL extracted and scored correctly, all fields written back to sheet.

---

## What is left to build

### Phase 3 — Application Execution: Greenhouse + Lever
Files to create:
- `handlers/__init__.py`
- `handlers/greenhouse.py` — Deterministic field-by-field handler for `boards.greenhouse.io`
- `handlers/lever.py` — Deterministic handler for `jobs.lever.co`
- `modules/application_executor.py` — Routing logic: detect portal type from `portal_type` field → dispatch to correct handler
- `modules/cover_letter.py` — Claude cover letter generator (3-paragraph) + `weasyprint` PDF export

Test plan: Submit to real applications using a test email first.

### Phase 4 — Generic LLM Handler + Account Creation
- `handlers/generic_llm.py` — perceive → reason → act loop (screenshot + DOM → Claude → Playwright action)
- `modules/account_manager.py` — detect login walls, Google OAuth, email/password signup, `keyring` credential storage

### Phase 5 — Review UI + Logging
- `ui/review_app.py` — Streamlit review gate: shows cover letter, screenshot, fit score; Approve / Edit / Skip / Mark Failed
- `modules/logger.py` — SQLite logger: action log, screenshots, cover letter text per application
- Sheet writeback: `status`, `date_applied`, `notes` after each attempt

### Phase 6 — Workday + Edge Cases
- `handlers/workday.py` — Dynamic React shell, aggressive `wait_for_selector`, possibly vision-based
- CAPTCHA detection → pause + alert (never auto-solve)
- Multi-page pagination handling
- Session timeout recovery + retry logic

---

## Key technical context

### Project structure
```
unemployment-speedrun/
├── applicant_profile.json   # Personal data — source of truth for all field filling
├── assets/
│   ├── resume.pdf           # For upload fields
│   ├── resume.json          # Structured resume for LLM context
│   └── transcript.pdf
├── browser/tools.py         # All Playwright actions
├── handlers/                # (Phase 3+) Platform-specific application handlers
├── modules/
│   └── job_intelligence.py  # Phase 2 — fetch, extract, score, writeback
├── prompts/extraction.py    # Claude prompt templates
├── sheets/client.py         # Google Sheets polling + writeback
├── main.py                  # Async entry point + scheduler
├── pyproject.toml           # uv project
├── .env                     # GOOGLE_CREDENTIALS_PATH, SPREADSHEET_NAME, ANTHROPIC_API_KEY
└── credentials.json         # Google service account key (gitignored)
```

### Google Sheet column order (row 1 header)
`application_url | company | role | location | employment_type | jd_summary | fit_score | fit_reasoning | portal_type | status | date_applied | notes`

### Status flow
`Pending` → `Extracting` → `Ready` / `Low Fit` → `Applying` → `Applied` / `Failed` / `Needs Review`

### Model
`claude-sonnet-4-6` for all LLM calls.

### Critical Windows gotcha
Always use `asyncio.WindowsProactorEventLoopPolicy()` (set in `main.py`). Never set `WindowsSelectorEventLoopPolicy` — it breaks Playwright's subprocess spawning for Chromium.

### Phase 3 starting point
When the next session begins, start from `modules/application_executor.py`. It should:
1. Read `portal_type` from the sheet row (already extracted by Phase 2)
2. Route to `handlers/greenhouse.py` or `handlers/lever.py`
3. Each handler imports browser tools directly and fills fields from `applicant_profile.json`
4. After submission, call `modules/cover_letter.py` if a cover letter field was detected
