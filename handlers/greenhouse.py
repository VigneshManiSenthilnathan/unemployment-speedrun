"""
Greenhouse Application Handler — Phase 3

Supports both Greenhouse embed variants:
  - job-boards.greenhouse.io  (modern embed)
  - boards.greenhouse.io      (classic embed)

Fields are filled from applicant_profile.json.
Custom question dropdowns are handled via fuzzy select_option matching.
"""

import json
import logging
import re
from pathlib import Path

from browser.tools import (
    navigate, get_text, click, fill, select_option, upload, screenshot,
    init_browser, close_browser, get_page,
)

log = logging.getLogger(__name__)

RESUME_PATH = "assets/resume.pdf"

# Set to True to pause before clicking Submit — safe for live testing
DRY_RUN = True


def _load_profile(profile_path: str = "applicant_profile.json") -> dict:
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def _try_fill(selectors: "list[str] | str", value: str, label: str = "") -> bool:
    if isinstance(selectors, str):
        selectors = [selectors]
    for sel in selectors:
        try:
            await fill(sel, value, timeout=4_000)
            log.debug("Filled '%s' via %s", label, sel)
            return True
        except Exception:
            pass
    log.debug("Field not found (skipping): %s", label)
    return False


async def _try_upload(selectors: "list[str] | str", path: str, label: str = "") -> bool:
    if isinstance(selectors, str):
        selectors = [selectors]
    for sel in selectors:
        try:
            await upload(sel, path, timeout=4_000)
            log.debug("Uploaded '%s' via %s", label, sel)
            return True
        except Exception:
            pass
    log.debug("Upload field not found (skipping): %s", label)
    return False


async def _try_select(selector: str, value: str, label: str = "") -> bool:
    """Select a <select> dropdown option. Tries exact value, then partial label match."""
    page = await get_page()
    try:
        await page.wait_for_selector(selector, timeout=4_000)
    except Exception:
        log.debug("Dropdown not found (skipping): %s", label)
        return False

    locator = page.locator(selector)

    # Try exact value/label match first
    try:
        await locator.select_option(value, timeout=3_000)
        log.debug("Selected '%s' in %s", value, label)
        return True
    except Exception:
        pass

    # Try partial label match — get all options and find the best one
    try:
        options = await locator.evaluate(
            "el => Array.from(el.options).map(o => ({value: o.value, text: o.text.trim()}))"
        )
        value_lower = value.lower()
        best = None
        for opt in options:
            if opt["value"] == "" or opt["text"].lower() in ("select", "-- select --", ""):
                continue
            if value_lower in opt["text"].lower() or opt["text"].lower() in value_lower:
                best = opt["value"]
                break
        if best:
            await locator.select_option(best, timeout=3_000)
            log.debug("Partial-matched '%s' → '%s' in %s", value, best, label)
            return True
        else:
            log.debug("No option matched '%s' in %s (options: %s)", value, label,
                      [o["text"] for o in options[:10]])
    except Exception as exc:
        log.debug("Dropdown select error for %s: %s", label, exc)

    return False


async def _try_typeahead(selector: str, value: str, label: str = "") -> bool:
    """
    Fill a JS typeahead/autocomplete widget:
    1. Type the search string into the input
    2. Wait for a suggestion list to appear
    3. Click the first matching option
    """
    page = await get_page()
    try:
        await page.wait_for_selector(selector, timeout=4_000)
    except Exception:
        log.debug("Typeahead not found (skipping): %s", label)
        return False

    try:
        locator = page.locator(selector)
        await locator.click()
        await locator.fill("")  # clear first
        # Type slowly so the autocomplete JS fires
        await locator.type(value[:8], delay=80)

        # Wait for suggestion list — GH uses li[role='option'] or .select2-results__option
        suggestion_sel = "li[role='option'], .select2-results__option, [class*='autocomplete'] li, [class*='dropdown'] li"
        try:
            await page.wait_for_selector(suggestion_sel, timeout=5_000)
        except Exception:
            log.debug("No suggestion list appeared for %s", label)
            return False

        # Click the first suggestion that contains our value (case-insensitive)
        suggestions = page.locator(suggestion_sel)
        count = await suggestions.count()
        value_lower = value.lower()
        for i in range(count):
            text = (await suggestions.nth(i).inner_text()).strip().lower()
            if value_lower[:6].lower() in text or text in value_lower:
                await suggestions.nth(i).click()
                log.debug("Typeahead selected '%s' for %s", text, label)
                return True

        # Fallback: click first non-empty option
        if count > 0:
            await suggestions.first.click()
            log.debug("Typeahead fallback: clicked first option for %s", label)
            return True

    except Exception as exc:
        log.debug("Typeahead error for %s: %s", label, exc)

    return False


async def _fill_education(edu: dict) -> None:
    """Fill the Education section — handles typeahead autocompletes and native selects."""
    university = edu.get("university", "")
    degree = edu.get("degree", "")
    major = edu.get("major", "")
    gpa = edu.get("gpa", "")  # e.g. "4.34/5.0"
    grad_date = edu.get("graduation_date", "")  # "06/2026"

    # School — GH modern embed uses a typeahead (text input + JS dropdown)
    # Try typeahead first, fall back to native select, then plain text
    school_input_sel = "input[name*='school'], input[id*='school']"
    school_select_sel = "select[name*='school'], select[id*='school']"
    if not await _try_typeahead(school_input_sel, university, "school_typeahead"):
        if not await _try_select(school_select_sel, university, "school_select"):
            log.warning("Could not fill school field with '%s'", university)

    # Degree — native select on most GH forms
    degree_map = {
        "bachelor": "Bachelor's Degree",
        "b.eng": "Bachelor's Degree",
        "b.sc": "Bachelor's Degree",
        "b.s.": "Bachelor's Degree",
    }
    mapped_degree = next((v for k, v in degree_map.items() if k in degree.lower()), "Bachelor's Degree")
    degree_sel = "select[name*='degree'], select[id*='degree']"
    if not await _try_select(degree_sel, mapped_degree, "degree_select"):
        await _try_select(degree_sel, degree, "degree_select_raw")

    # Discipline / Major — native select
    disc_sel = "select[name*='discipline'], select[id*='discipline']"
    if not await _try_select(disc_sel, major, "discipline_select"):
        await _try_fill("input[name*='discipline'], input[id*='discipline']", major, "discipline_text")

    # Graduation date → end date month + year selects
    if grad_date:
        try:
            parts = grad_date.split("/")
            month_num = parts[0].lstrip("0") if len(parts) >= 1 else ""
            year = parts[1] if len(parts) >= 2 else ""

            month_names = {
                "1": "January", "2": "February", "3": "March", "4": "April",
                "5": "May", "6": "June", "7": "July", "8": "August",
                "9": "September", "10": "October", "11": "November", "12": "December",
            }
            month_name = month_names.get(month_num, "")
            await _try_select(
                "select[name*='end_date_month'], select[id*='end_date_month']",
                month_name or month_num, "end_date_month",
            )
            await _try_select(
                "select[name*='end_date_year'], select[id*='end_date_year']",
                year, "end_date_year",
            )
        except Exception as exc:
            log.debug("Education date fill error: %s", exc)

    # GPA select
    if gpa:
        try:
            gpa_val = float(gpa.split("/")[0])
            gpa_str = str(round(gpa_val, 1))
            gpa_sel = "select[name*='gpa'], select[id*='gpa'], select[name*='grade'], select[id*='grade']"
            await _try_select(gpa_sel, gpa_str, "gpa_select")
        except Exception:
            pass


async def _fill_custom_questions(profile: dict) -> None:
    """
    Handle common yes/no and dropdown custom questions on Greenhouse forms.
    Reads all <select> elements on the page and tries to answer based on known patterns.
    """
    page = await get_page()
    p = profile["personal"]

    # Work authorization / sponsorship — answer based on profile
    work_auth = p.get("work_authorization", "")
    sponsorship_needed = "no"  # Singaporean citizen, no sponsorship needed

    # Map of label keywords → answer value/label to select
    yesno_map = [
        (["sponsor", "visa", "authoriz", "work permit"], sponsorship_needed),
        (["currently employed", "currently work"], "no"),
        (["outstanding offer", "other offer"], "no"),
        (["interviewed.*virtu", "virtu.*before"], "no"),
        (["multiple jobs", "multiple roles"], "no"),
    ]

    try:
        # Get all select elements with their labels
        selects_info = await page.evaluate("""() => {
            const results = [];
            document.querySelectorAll('select').forEach((sel, idx) => {
                // Try to find associated label
                let label = '';
                if (sel.id) {
                    const lbl = document.querySelector('label[for="' + sel.id + '"]');
                    if (lbl) label = lbl.innerText.trim();
                }
                if (!label) {
                    const parent = sel.closest('div, li, fieldset');
                    if (parent) {
                        const lbl = parent.querySelector('label, legend');
                        if (lbl) label = lbl.innerText.trim();
                    }
                }
                results.push({
                    selector: sel.name ? 'select[name="' + sel.name + '"]' : null,
                    id: sel.id,
                    name: sel.name,
                    label: label.toLowerCase(),
                    options: Array.from(sel.options).map(o => ({value: o.value, text: o.text.trim()}))
                });
            });
            return results;
        }""")

        for sel_info in selects_info:
            label_text = sel_info.get("label", "")
            sel_name = sel_info.get("name", "")
            sel_id = sel_info.get("id", "")

            if not label_text and not sel_name:
                continue

            # Skip already-handled education selects
            if any(kw in sel_name.lower() for kw in ["school", "degree", "discipline", "gpa", "date"]):
                continue

            # Build a usable CSS selector
            if sel_name:
                css = f'select[name="{sel_name}"]'
            elif sel_id:
                css = f'select#{sel_id}'
            else:
                continue

            # Try each pattern
            for keywords, answer in yesno_map:
                if any(kw in label_text for kw in keywords):
                    await _try_select(css, answer, f"custom: {label_text[:50]}")
                    break

    except Exception as exc:
        log.debug("Custom question fill error: %s", exc)


async def apply(
    url: str,
    cover_letter_text: str = "",
    cover_letter_pdf: str = "",
    profile_path: str = "applicant_profile.json",
) -> dict:
    """
    Fill and submit a Greenhouse application.
    Returns dict: success (bool), screenshot_path (str), notes (str).
    """
    profile = _load_profile(profile_path)
    p = profile["personal"]
    edu = profile["education"][0] if profile["education"] else {}

    await init_browser(headless=False)
    await navigate(url)

    page = await get_page()

    # Wait for form to load
    try:
        await page.wait_for_selector(
            "input#first_name, input[name='job_application[first_name]']",
            timeout=15_000,
        )
    except Exception:
        log.warning("Form fields did not appear within 15s — attempting to fill anyway.")

    # ---- Personal Information ----
    await _try_fill(
        ["input#first_name", "input[name='job_application[first_name]']"],
        p.get("first_name", ""), "first_name",
    )
    await _try_fill(
        ["input#last_name", "input[name='job_application[last_name]']"],
        p.get("last_name", ""), "last_name",
    )
    await _try_fill(
        ["input#email", "input[name='job_application[email]']"],
        p.get("email", ""), "email",
    )
    # Country code dropdown for phone (select by country name or dial code)
    country = p.get("country", "Singapore")
    await _try_select(
        "select#country, select[name='job_application[phone_country_code]'], select[name*='country_code']",
        country, "phone_country_code",
    )
    await _try_fill(
        ["input#phone", "input[name='job_application[phone]']"],
        p.get("phone", ""), "phone",
    )

    await _try_fill(
        ["input[name='job_application[linkedin_url]']", "input[placeholder*='LinkedIn']"],
        p.get("linkedin_url", ""), "linkedin",
    )

    # Location — GH uses input#job_application_location with a city autocomplete
    location_val = p.get("city", "")
    loc_filled = await _try_typeahead(
        "input#job_application_location, input[name='job_application[location]']",
        location_val, "location_typeahead",
    )
    if not loc_filled:
        await _try_fill(
            ["input#job_application_location", "input[name='job_application[location]']"],
            location_val, "location_text",
        )

    # ---- Resume upload ----
    resume_path = profile.get("files", {}).get("resume_pdf", RESUME_PATH)
    if Path(resume_path).exists():
        await _try_upload(
            ["input#resume", "input[name='resume']", "input[type='file'][name*='resume']"],
            resume_path, "resume",
        )
    else:
        log.warning("Resume not found at %s — skipping upload.", resume_path)

    # ---- Cover letter ----
    if cover_letter_text:
        await _try_fill(
            ["textarea#cover_letter_text", "textarea[name='job_application[cover_letter_text]']"],
            cover_letter_text, "cover_letter_text",
        )
    if cover_letter_pdf and Path(cover_letter_pdf).exists():
        await _try_upload(
            ["input#cover_letter", "input[type='file'][name*='cover']"],
            cover_letter_pdf, "cover_letter_file",
        )

    # ---- Education section (dropdowns) ----
    await _fill_education(edu)

    # ---- Custom yes/no questions ----
    await _fill_custom_questions(profile)

    # ---- Screenshot before submit ----
    safe_slug = re.sub(r"[^\w\-]", "_", url.rstrip("/").split("/")[-1].split("?")[0])[:60]
    ss_path = f"screenshots/greenhouse_{safe_slug}.png"
    await screenshot(ss_path)
    log.info("Screenshot saved: %s", ss_path)

    if DRY_RUN:
        log.info("DRY_RUN=True — skipping submit. Review screenshot: %s", ss_path)
        await close_browser()
        return {"success": False, "screenshot_path": ss_path, "notes": "Dry run — submit skipped."}

    # ---- Submit ----
    submitted = False
    notes = ""
    try:
        submit_sel = "button[type='submit'], input[type='submit']"
        await page.wait_for_selector(submit_sel, timeout=10_000)
        await page.locator(submit_sel).first.click()
        log.info("Clicked submit button.")

        await page.wait_for_load_state("domcontentloaded", timeout=20_000)
        final_url = page.url
        body = await get_text()

        confirmed_url = any(kw in final_url.lower() for kw in ["confirmation", "thank", "submitted", "success"])
        confirmed_body = any(kw in body.lower() for kw in [
            "thank you", "application submitted", "application received",
            "we've received", "successfully submitted",
        ])
        submitted = confirmed_url or confirmed_body
        notes = f"Final URL: {final_url}"
        log.info("Submission result — submitted=%s, url=%s", submitted, final_url)
    except Exception as exc:
        notes = f"Submit error: {exc}"
        log.error("Submit failed: %s", exc)

    await close_browser()
    return {"success": submitted, "screenshot_path": ss_path, "notes": notes}
