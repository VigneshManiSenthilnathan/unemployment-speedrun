# Phase 1 Setup Guide

## 1. Install dependencies

```bash
# Install uv if you don't have it
pip install uv

# Create venv and install all deps
uv sync

# Install Playwright browsers (only needed once)
uv run playwright install chromium
```

## 2. Google Cloud service account setup

### 2a. Create a project and enable APIs

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. `job-agent`)
3. In the left menu → **APIs & Services → Library**
4. Enable these two APIs:
   - **Google Sheets API**
   - **Google Drive API**

### 2b. Create a service account

1. **APIs & Services → Credentials → Create Credentials → Service Account**
2. Name it anything (e.g. `job-agent-bot`)
3. Skip optional role/user steps — click Done
4. Click the service account you just created → **Keys** tab → **Add Key → Create new key → JSON**
5. Save the downloaded file as `credentials.json` in the repo root

> `credentials.json` is in `.gitignore` — never commit it.

### 2c. Share your Google Sheet with the service account

1. Open `credentials.json` and copy the `client_email` field (looks like `job-agent-bot@your-project.iam.gserviceaccount.com`)
2. Open your Google Sheet → **Share** → paste that email → give **Editor** access

## 3. Create your Google Sheet

Create a new Google Sheet with exactly this header row in row 1:

```
application_url | company | role | location | employment_type | jd_summary | fit_score | fit_reasoning | portal_type | status | date_applied | notes
```

Name the sheet whatever you like — you'll set that name in `.env`.

## 4. Configure environment variables

Copy the example env file and fill it in:

```bash
cp .env.example .env
```

Edit `.env`:

```
GOOGLE_CREDENTIALS_PATH=credentials.json
SPREADSHEET_NAME=Your Exact Sheet Name
POLL_INTERVAL_MINUTES=5
ANTHROPIC_API_KEY=sk-ant-...
```

## 5. Fill in your applicant profile

Open [applicant_profile.json](applicant_profile.json) and fill in your real data.

Place your files in `assets/`:
- `assets/resume.pdf`
- `assets/transcript.pdf` (if needed)

## 6. Verify Phase 1 is working

**Test Playwright (browser automation):**

```bash
uv run python -c "
import asyncio
from browser.tools import init_browser, navigate, get_text, close_browser

async def test():
    await init_browser(headless=False)
    await navigate('https://boards.greenhouse.io/anthropic/jobs/4020305008')
    text = await get_text()
    print(text[:500])
    await close_browser()

asyncio.run(test())
"
```

You should see the first 500 characters of the Greenhouse job page text.

**Test Google Sheets polling:**

```bash
uv run python -c "
from sheets.client import SheetsClient
import os
from dotenv import load_dotenv
load_dotenv()

s = SheetsClient(os.getenv('GOOGLE_CREDENTIALS_PATH'), os.getenv('SPREADSHEET_NAME'))
print('Pending rows:', s.get_pending_rows())
"
```

Add a row to your sheet with `status = Pending` and a URL — it should appear in the output.

**Run the full agent:**

```bash
uv run python main.py
```

---

## File structure after Phase 1

```
unemployment-speedrun/
├── applicant_profile.json   # Your personal data (fill this in)
├── assets/
│   ├── resume.pdf
│   └── transcript.pdf
├── browser/
│   └── tools.py             # Playwright atomic actions
├── sheets/
│   └── client.py            # Google Sheets polling
├── main.py                  # Entry point + scheduler
├── credentials.json         # Service account key (never commit)
├── .env                     # Environment variables (never commit)
├── pyproject.toml
└── SETUP.md
```
