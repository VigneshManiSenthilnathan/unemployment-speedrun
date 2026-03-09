"""
Job Intelligence Module — Phase 2

Given a job URL, this module:
1. Fetches the page text via Playwright
2. Sends it to Claude for structured extraction
3. Scores fit against the applicant's preference profile
4. Writes all metadata + fit score back to the Google Sheet
"""

import json
import logging
import os
import re

import anthropic

from browser.tools import init_browser, navigate, get_text, close_browser
from prompts.extraction import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    FIT_SCORING_SYSTEM,
    FIT_SCORING_USER,
)
from sheets.client import SheetsClient

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_PAGE_CHARS = 12_000  # trim page text to keep prompt within token budget


def _load_profile(profile_path: str = "applicant_profile.json") -> dict:
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _candidate_summary(profile: dict) -> str:
    """Build a concise text summary of the candidate for the fit scoring prompt."""
    p = profile["personal"]
    edu = profile["education"][0] if profile["education"] else {}
    exps = profile.get("experience", [])
    skills = profile.get("skills", [])

    exp_lines = "\n".join(
        f"  - {e['role']} at {e['company']} ({e['start_date']} – {e['end_date']}): {e['description'] if isinstance(e['description'], str) else ' '.join(e['description'])}"
        for e in exps
    )

    return (
        f"Name: {p.get('full_name', '')}\n"
        f"Education: {edu.get('degree', '')} at {edu.get('university', '')} — GPA {edu.get('gpa', '')}, graduating {edu.get('graduation_date', '')}\n"
        f"Experience:\n{exp_lines}\n"
        f"Skills: {', '.join(skills[:20])}"
    )


def _call_claude(client: anthropic.Anthropic, system: str, user: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


def _parse_json(raw: str) -> dict:
    """Extract JSON from the model response, stripping any accidental markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    return json.loads(cleaned.strip())


async def _fetch_page_text(url: str) -> str:
    await init_browser(headless=True)
    await navigate(url)
    text = await get_text()
    await close_browser()
    return text[:MAX_PAGE_CHARS]


def extract_job_metadata(client: anthropic.Anthropic, page_text: str) -> dict:
    raw = _call_claude(
        client,
        EXTRACTION_SYSTEM,
        EXTRACTION_USER.format(page_text=page_text),
    )
    try:
        return _parse_json(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse extraction response:\n%s", raw)
        raise


def score_fit(client: anthropic.Anthropic, metadata: dict, profile: dict) -> dict:
    prefs = profile.get("preferences", {})
    requirements = "\n".join(f"  - {r}" for r in metadata.get("requirements", []))

    raw = _call_claude(
        client,
        FIT_SCORING_SYSTEM,
        FIT_SCORING_USER.format(
            candidate_summary=_candidate_summary(profile),
            company=metadata.get("company", ""),
            role=metadata.get("role", ""),
            location=metadata.get("location", ""),
            employment_type=metadata.get("employment_type", ""),
            requirements=requirements,
            jd_summary=metadata.get("jd_summary", ""),
            target_roles=", ".join(prefs.get("target_roles", [])) or "Any",
            locations=", ".join(prefs.get("locations", [])) or "Any",
            remote_preference=prefs.get("remote_preference", "hybrid"),
            excluded_companies=", ".join(prefs.get("excluded_companies", [])) or "None",
        ),
    )
    try:
        return _parse_json(raw)
    except json.JSONDecodeError:
        log.error("Failed to parse fit scoring response:\n%s", raw)
        raise


async def process(url: str, row: int, sheets: SheetsClient, profile_path: str = "applicant_profile.json") -> dict:
    """
    Full pipeline for one pending row.
    Returns the combined metadata + fit result dict.
    """
    profile = _load_profile(profile_path)
    prefs = profile.get("preferences", {})
    threshold = prefs.get("fit_score_threshold", 6)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # --- Step 1: fetch page ---
    log.info("Fetching page: %s", url)
    sheets.set_status(row, "Extracting")
    page_text = await _fetch_page_text(url)

    # --- Step 2: extract metadata ---
    log.info("Extracting job metadata...")
    metadata = extract_job_metadata(client, page_text)
    log.info("Extracted: %s @ %s (%s)", metadata.get("role"), metadata.get("company"), metadata.get("portal_type"))

    # --- Step 3: score fit ---
    log.info("Scoring fit...")
    fit = score_fit(client, metadata, profile)
    fit_score = fit.get("fit_score", 0)
    log.info("Fit score: %s/10 — %s", fit_score, fit.get("fit_reasoning", ""))

    # --- Step 4: write back to sheet ---
    result = {
        "company": metadata.get("company", ""),
        "role": metadata.get("role", ""),
        "location": metadata.get("location", ""),
        "employment_type": metadata.get("employment_type", ""),
        "jd_summary": metadata.get("jd_summary", ""),
        "portal_type": metadata.get("portal_type", "unknown"),
        "fit_score": str(fit_score),
        "fit_reasoning": fit.get("fit_reasoning", ""),
    }

    if fit_score < threshold:
        result["status"] = "Low Fit"
        log.info("Row %d marked Low Fit (score %d < threshold %d).", row, fit_score, threshold)
    else:
        result["status"] = "Ready"

    sheets.update_row(row, result)
    return result
