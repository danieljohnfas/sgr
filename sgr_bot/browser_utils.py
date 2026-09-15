"""
Shared browser/page utilities: stealth context creation, human delays,
safe clicking, debug dumps, and challenge-aware navigation.
"""
import datetime
import random
from pathlib import Path
from typing import Optional

from . import config, selectors
from .captcha import handle_if_challenged


# ── Stealth Browser Factory ───────────────────────────────────────────────────

async def make_stealth_context(playwright, proxy: Optional[str] = None,
                               load_state: bool = True,
                               storage_state: Optional[str] = None):
    """
    Launch Chromium with stealth patches. Proxy is only applied when an
    explicit trusted proxy is passed or config.PROXY_SERVER is set — never
    a free public list.
    """
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-plugins-discovery",
    ]
    launch_kwargs = dict(headless=config.HEADLESS, args=launch_args)
    proxy = proxy or (config.PROXY_SERVER if config.USE_PROXY else None)
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    browser = await playwright.chromium.launch(**launch_kwargs)

    viewport  = random.choice(config.VIEWPORT_OPTIONS)
    ua        = random.choice(config.USER_AGENTS)
    ctx_kwargs = dict(
        viewport=viewport,
        user_agent=ua,
        locale="en-US",
        timezone_id="Africa/Dar_es_Salaam",
        java_script_enabled=True,
    )

    state_path = Path(storage_state) if storage_state else Path(config.STATE_FILE)
    if load_state and state_path.exists():
        ctx_kwargs["storage_state"] = str(state_path)

    context = await browser.new_context(**ctx_kwargs)
    page    = await context.new_page()

    # Apply playwright-stealth to hide automation fingerprints
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except ImportError:
        # Fallback: manually patch the most obvious tells
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = { runtime: {} };
        """)

    return browser, context, page


# ── Human-Like Delays ─────────────────────────────────────────────────────────

async def human_delay(page, min_ms: int = 300, max_ms: int = 1000):
    await page.wait_for_timeout(random.randint(min_ms, max_ms))


async def set_angular_input(page, css_selector: str, value: str) -> bool:
    """Set an Angular form input via the native value setter + input/change."""
    return await page.evaluate(
        """({selector, value}) => {
            const inp = document.querySelector(selector);
            if (!inp) return false;
            const desc = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            );
            if (desc && desc.set) desc.set.call(inp, value);
            else inp.value = value;
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }""",
        {"selector": css_selector, "value": value},
    )


# ── Safe Navigation ───────────────────────────────────────────────────────────

async def safe_goto(page, url: str, retries: int = 3, timeout_ms: int = 30_000) -> bool:
    """
    Navigate to a URL, handle challenges, retry on transient failures.
    Returns True if the page loaded cleanly.
    """
    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if await handle_if_challenged(page):
                return True
            print(f"[Nav] Challenge not resolved on attempt {attempt}")
        except Exception as e:
            print(f"[Nav] goto error (attempt {attempt}/{retries}): {e}")
        await human_delay(page, 1500, 3000)
    return False


# ── Safe Click ────────────────────────────────────────────────────────────────

async def safe_click(page, selector: str, retries: int = 3,
                     timeout_ms: int = 10_000, force: bool = False) -> bool:
    """
    Wait for selector to be visible, scroll into view, then click.
    Retries on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.scroll_into_view_if_needed()
            await locator.click(force=force, timeout=timeout_ms)
            return True
        except Exception as e:
            print(f"[Click] Attempt {attempt}/{retries} failed for '{selector}': {e}")
            await human_delay(page, 800, 1500)
    return False


# ── Debug Dump ────────────────────────────────────────────────────────────────

async def dump_debug(page, prefix: str = "debug", out_dir: str = "."):
    """Save a full-page screenshot + HTML to help diagnose failures."""
    ts = datetime.datetime.now().strftime("%H%M%S")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(out / f"{prefix}_{ts}.png"), full_page=True)
    except Exception:
        pass
    try:
        html = await page.content()
        (out / f"{prefix}_{ts}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass
    print(f"[Debug] Dump saved: {out}/{prefix}_{ts}.*")
