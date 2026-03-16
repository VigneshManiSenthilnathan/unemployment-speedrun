"""
Lever Application Handler — Phase 3

Fills and submits applications on jobs.lever.co using deterministic Playwright selectors.
"""

import json
import logging
from pathlib import Path

from browser.tools import (
    navigate, get_text, click, fill, upload, screenshot, init_browser, close_browser, get_page,
)

log = logging.getLogger(__name__)

RESUME_PATH = "assets/resume.pdf"


def _load_profile(profile_path: str = "applicant_profile.json") -> dict:
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def _try_fill(selector: str, value: str, label: str = "") -> bool:
    try:
        await fill(selector, value, timeout=5_000)
        return True
    except Exception:
        if label:
            log.debug("Field not found (skipping): %s", label)
        return False


async def _try_upload(selector: str, path: str, label: str = "") -> bool:
    try:
        await upload(selector, path, timeout=5_000)
        return True
    except Exception:
        if label:
            log.debug("Upload field not found (skipping): %s", label)
        return False


async def apply(
    url: str,
    cover_letter_text: str = "",
    cover_letter_pdf: str = "",
    profile_path: str = "applicant_profile.json",
) -> dict:
    """
    Fill and submit a Lever application.

    Returns:
        dict with keys: success (bool), screenshot_path (str), notes (str)
    """
    profile = _load_profile(profile_path)
    p = profile["personal"]

    await init_browser(headless=False)
    await navigate(url)

    # Lever's apply form is usually at /apply appended to the job URL
    page = await get_page()
    current = page.url
    if "/apply" not in current:
        # Try clicking the Apply button first
        try:
            await click("a[href*='/apply']", timeout=8_000)
            log.info("Clicked Apply link.")
        except Exception:
            log.warning("Could not find /apply link — filling form on current page.")

    # ---- Personal Information ----
    # Lever uses name="name", name="email", name="phone", name="org" (current company)
    await _try_fill("input[name='name']", p.get("full_name", ""), "full_name")
    await _try_fill("input[name='email']", p.get("email", ""), "email")
    await _try_fill("input[name='phone']", p.get("phone", ""), "phone")

    # Org / current company — leave blank for students
    await _try_fill("input[name='org']", "", "org")

    # LinkedIn URL (custom question on many Lever forms)
    await _try_fill("input[name='urls[LinkedIn]']", p.get("linkedin_url", ""), "linkedin")
    await _try_fill("input[placeholder*='LinkedIn']", p.get("linkedin_url", ""), "linkedin placeholder")

    # ---- Resume upload ----
    resume_path = profile.get("files", {}).get("resume_pdf", RESUME_PATH)
    if Path(resume_path).exists():
        await _try_upload("input[name='resume']", resume_path, "resume")
    else:
        log.warning("Resume not found at %s — skipping upload.", resume_path)

    # ---- Cover letter ----
    if cover_letter_text:
        await _try_fill("textarea[name='comments']", cover_letter_text, "cover_letter")
        await _try_fill("textarea[name='coverLetter']", cover_letter_text, "coverLetter")

    # ---- Screenshot before submit ----
    import re as _re
    safe_slug = _re.sub(r"[^\w\-]", "_", url.rstrip("/").split("/")[-1].split("?")[0])[:60]
    ss_path = f"screenshots/lever_{safe_slug}.png"
    await screenshot(ss_path)
    log.info("Screenshot saved: %s", ss_path)

    # ---- Submit ----
    submitted = False
    notes = ""
    try:
        # Lever's submit button is typically: <button type="submit"> or class "postings-btn"
        await click("button[type='submit']", timeout=10_000)
        log.info("Clicked submit button.")
        await page.wait_for_load_state("domcontentloaded", timeout=20_000)
        final_url = page.url
        body = await get_text()
        submitted = any(
            kw in body.lower() for kw in ["thank you", "application submitted", "application received", "we've received"]
        )
        notes = f"Final URL: {final_url}"
        log.info("Submission result — submitted=%s, url=%s", submitted, final_url)
    except Exception as exc:
        notes = f"Submit error: {exc}"
        log.error("Submit failed: %s", exc)

    await close_browser()

    return {
        "success": submitted,
        "screenshot_path": ss_path,
        "notes": notes,
    }
