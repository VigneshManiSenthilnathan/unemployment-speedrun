"""
Application Executor — Phase 3

Reads portal_type from a sheet row (already populated by Phase 2) and routes to the
correct handler. Also invokes the cover letter generator when relevant.

Status flow handled here:
    Ready → Applying → Applied / Failed / Needs Review
"""

import logging
import os
import re
from datetime import date

from sheets.client import SheetsClient
import modules.cover_letter as cover_letter_mod

log = logging.getLogger(__name__)

COVER_LETTER_OUTPUT_DIR = "cover_letters"

_URL_PORTAL_MAP = [
    (r"greenhouse\.io|job-boards\.greenhouse\.io", "greenhouse"),
    (r"lever\.co", "lever"),
    (r"workday\.com|myworkdayjobs\.com", "workday"),
    (r"icims\.com", "icims"),
    (r"taleo\.net", "taleo"),
]


def _detect_portal_from_url(url: str) -> str | None:
    """Return portal type inferred from the URL, or None if unrecognised."""
    for pattern, portal in _URL_PORTAL_MAP:
        if re.search(pattern, url, re.IGNORECASE):
            return portal
    return None


async def execute(row: dict, sheets: SheetsClient, profile_path: str = "applicant_profile.json") -> None:
    """
    Route a Ready row to the appropriate handler and write results back to the sheet.

    Args:
        row:  dict from SheetsClient (includes _row key)
        sheets: active SheetsClient instance
    """
    row_num = row["_row"]
    url = row.get("application_url", "").strip()
    portal_type_llm = row.get("portal_type", "unknown").strip().lower()
    portal_type_url = _detect_portal_from_url(url)
    portal_type = portal_type_url or portal_type_llm
    if portal_type_url and portal_type_url != portal_type_llm:
        log.info("Portal override: LLM said '%s', URL says '%s' — using URL.", portal_type_llm, portal_type_url)
    company = row.get("company", "unknown")
    role = row.get("role", "unknown")
    jd_summary = row.get("jd_summary", "")

    log.info("Executing application — row %d | portal: %s | %s @ %s", row_num, portal_type, role, company)
    sheets.set_status(row_num, "Applying")

    # ---- Generate cover letter ----
    cl_text = ""
    cl_pdf = ""
    safe_name = f"{company}_{role}".replace(" ", "_").replace("/", "-")[:60]
    cl_output = f"{COVER_LETTER_OUTPUT_DIR}/{safe_name}.pdf"

    try:
        cl_text, cl_pdf = cover_letter_mod.generate(
            company=company,
            role=role,
            jd_summary=jd_summary,
            output_path=cl_output,
            profile_path=profile_path,
        )
        log.info("Cover letter generated: %s", cl_pdf)
    except Exception as exc:
        log.warning("Cover letter generation failed (continuing without): %s", exc)

    # ---- Route to handler ----
    result = await _dispatch(portal_type, url, cl_text, cl_pdf, profile_path)

    # ---- Write results back ----
    if result["success"]:
        sheets.update_row(row_num, {
            "status": "Applied",
            "date_applied": date.today().isoformat(),
            "notes": result.get("notes", ""),
        })
        log.info("Row %d → Applied", row_num)
    else:
        sheets.update_row(row_num, {
            "status": "Needs Review",
            "notes": result.get("notes", "Submission could not be confirmed — check screenshot."),
        })
        log.warning("Row %d → Needs Review", row_num)


async def _dispatch(
    portal_type: str,
    url: str,
    cl_text: str,
    cl_pdf: str,
    profile_path: str,
) -> dict:
    """Dispatch to the correct portal handler."""

    if portal_type == "greenhouse":
        from handlers.greenhouse import apply
        return await apply(url, cover_letter_text=cl_text, cover_letter_pdf=cl_pdf, profile_path=profile_path)

    if portal_type == "lever":
        from handlers.lever import apply
        return await apply(url, cover_letter_text=cl_text, cover_letter_pdf=cl_pdf, profile_path=profile_path)

    # Unknown / unsupported portal
    log.warning("Unsupported portal type '%s' for URL %s — marking Needs Review.", portal_type, url)
    return {
        "success": False,
        "screenshot_path": "",
        "notes": f"Unsupported portal type: {portal_type}",
    }
