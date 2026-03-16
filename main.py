"""
Entry point for the job application agent.

Polls the Google Sheet every N minutes for rows with status = Pending,
then hands them off to the processing pipeline.

Usage:
    uv run python main.py

Environment variables (or set in a .env file):
    GOOGLE_CREDENTIALS_PATH   Path to service account JSON  (default: credentials.json)
    SPREADSHEET_NAME          Exact name of the Google Sheet
    POLL_INTERVAL_MINUTES     Polling interval in minutes    (default: 5)
    ANTHROPIC_API_KEY         Your Anthropic API key
"""

import asyncio
import logging
import os
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from modules.job_intelligence import process as intelligence_process
from modules.application_executor import execute as application_execute
from sheets.client import SheetsClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))


async def process_row(row: dict, sheets: SheetsClient) -> None:
    """Run the full intelligence pipeline for a single pending row."""
    url = row.get("application_url", "").strip()
    row_num = row["_row"]

    if not url:
        log.warning("Row %d has no URL — skipping.", row_num)
        sheets.set_status(row_num, "Failed")
        return

    log.info("Processing row %d: %s", row_num, url)
    await intelligence_process(url, row_num, sheets)


async def poll(sheets: SheetsClient) -> None:
    log.info("Polling sheet for pending rows…")
    try:
        pending = sheets.get_pending_rows()
    except Exception as exc:
        log.error("Failed to read sheet: %s", exc)
        return

    if not pending:
        log.info("No pending rows found.")
    else:
        log.info("Found %d pending row(s).", len(pending))
        for row in pending:
            try:
                await process_row(row, sheets)
            except Exception as exc:
                log.error("Error processing row %d: %s", row["_row"], exc)
                sheets.set_status(row["_row"], "Failed")

    # ---- Phase 3: execute Ready rows ----
    try:
        ready_rows = sheets.get_rows_by_status("Ready")
    except Exception as exc:
        log.error("Failed to read Ready rows: %s", exc)
        return

    if not ready_rows:
        log.info("No ready rows to apply.")
        return

    log.info("Found %d ready row(s) to apply.", len(ready_rows))
    for row in ready_rows:
        try:
            await application_execute(row, sheets)
        except Exception as exc:
            log.error("Error executing application for row %d: %s", row["_row"], exc)
            sheets.set_status(row["_row"], "Failed")


async def main_async() -> None:
    if not SPREADSHEET_NAME:
        raise ValueError("SPREADSHEET_NAME environment variable is not set.")

    sheets = SheetsClient(CREDENTIALS_PATH, SPREADSHEET_NAME)
    log.info("Connected to sheet '%s'. Polling every %d minute(s).", SPREADSHEET_NAME, POLL_INTERVAL)

    # Run once immediately.
    await poll(sheets)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(poll, "interval", minutes=POLL_INTERVAL, args=[sheets])
    scheduler.start()

    try:
        # Keep the event loop alive.
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down.")
        scheduler.shutdown()


def main() -> None:
    # On Windows, ProactorEventLoop is required for Playwright subprocess spawning.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
