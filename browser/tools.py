"""Atomic Playwright browser tools used by all application handlers."""

import asyncio
import base64
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None


async def init_browser(headless: bool = False) -> Page:
    """Launch browser and return the active page."""
    global _browser, _context, _page

    playwright = await async_playwright().start()
    _browser = await playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    _context = await _browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    _page = await _context.new_page()
    return _page


async def get_page() -> Page:
    """Return the current page, initialising the browser if needed."""
    if _page is None:
        return await init_browser()
    return _page


async def close_browser() -> None:
    global _browser, _context, _page
    if _browser:
        await _browser.close()
    _browser = None
    _context = None
    _page = None


# ---------------------------------------------------------------------------
# Atomic actions
# ---------------------------------------------------------------------------

async def navigate(url: str, wait_until: str = "domcontentloaded") -> None:
    page = await get_page()
    await page.goto(url, wait_until=wait_until, timeout=30_000)


async def get_text(selector: Optional[str] = None) -> str:
    """Return visible text — full page if no selector given."""
    page = await get_page()
    if selector:
        await page.wait_for_selector(selector, timeout=10_000)
        element = page.locator(selector)
        return await element.inner_text()
    return await page.evaluate("() => document.body.innerText")


async def click(selector: str, timeout: int = 10_000) -> None:
    page = await get_page()
    await page.wait_for_selector(selector, timeout=timeout)
    await page.locator(selector).click()


async def fill(selector: str, value: str, timeout: int = 10_000) -> None:
    page = await get_page()
    await page.wait_for_selector(selector, timeout=timeout)
    await page.locator(selector).fill(value)


async def select_option(selector: str, value: str, timeout: int = 10_000) -> None:
    page = await get_page()
    await page.wait_for_selector(selector, timeout=timeout)
    await page.locator(selector).select_option(value)


async def upload(selector: str, file_path: str, timeout: int = 10_000) -> None:
    """Set a file input's value."""
    page = await get_page()
    await page.wait_for_selector(selector, timeout=timeout)
    await page.locator(selector).set_input_files(file_path)


async def screenshot(save_path: Optional[str] = None) -> bytes:
    """Take a full-page screenshot. Returns raw PNG bytes."""
    page = await get_page()
    png = await page.screenshot(full_page=True)
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_bytes(png)
    return png


async def screenshot_b64() -> str:
    """Return screenshot as base64 string (for LLM vision calls)."""
    png = await screenshot()
    return base64.b64encode(png).decode()


async def wait_for_url(pattern: str, timeout: int = 15_000) -> None:
    page = await get_page()
    await page.wait_for_url(pattern, timeout=timeout)


async def current_url() -> str:
    page = await get_page()
    return page.url
