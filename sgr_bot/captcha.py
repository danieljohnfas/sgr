"""
CAPTCHA / Cloudflare challenge detection and handling.
"""
import asyncio
from typing import Optional

from . import selectors


# ── Detection ─────────────────────────────────────────────────────────────────

async def is_challenge_page(page) -> bool:
    """Return True if the current page looks like a bot-check or block page."""
    try:
        content = (await page.content()).lower()
        return any(kw in content for kw in selectors.CHALLENGE_KEYWORDS)
    except Exception:
        return False


async def is_blocked_response(response) -> bool:
    """Return True if an HTTP response status signals a rate-limit or block."""
    return response.status in selectors.BLOCK_HTTP_CODES


# ── Auto-resolution ───────────────────────────────────────────────────────────

async def wait_for_challenge_resolution(page, max_wait_s: int = None) -> bool:
    """
    Cloudflare JS challenges typically auto-clear within 3-5 seconds when a
    stealth-patched browser is used.  Wait up to `max_wait_s` seconds, polling
    every 2 s.  Returns True if the challenge cleared, False on timeout.
    """
    from . import config
    if max_wait_s is None:
        max_wait_s = config.CAPTCHA_WAIT_S

    print(f"[CAPTCHA] Challenge detected. Waiting up to {max_wait_s}s for auto-resolution...")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait_s
    while loop.time() < deadline:
        await page.wait_for_timeout(2000)
        if not await is_challenge_page(page):
            print("[CAPTCHA] Challenge cleared!")
            return True
    print("[CAPTCHA] Challenge did NOT auto-clear.")
    return False


# ── 2captcha fallback ────────────────────────────────────────────────────────

async def solve_captcha_2captcha(page) -> bool:
    """
    If a hCaptcha or reCAPTCHA widget is present and a 2captcha API key is
    configured, solve it programmatically.  Returns True on success.
    """
    from . import config
    api_key = config.TWOCAPTCHA_API_KEY
    if not api_key:
        print("[CAPTCHA] No 2captcha key configured. Skipping solver.")
        return False

    try:
        from twocaptcha import TwoCaptcha  # pip install 2captcha-python
    except ImportError:
        print("[CAPTCHA] twocaptcha package not installed. Run: pip install 2captcha-python")
        return False

    # Detect widget type and sitekey
    sitekey = await page.evaluate("""
        () => {
            const el = document.querySelector('[data-sitekey]');
            return el ? el.dataset.sitekey : null;
        }
    """)
    if not sitekey:
        print("[CAPTCHA] No sitekey found on page. Cannot solve.")
        return False

    # Detect hcaptcha vs recaptcha
    is_hcaptcha = await page.locator("iframe[src*='hcaptcha']").count() > 0

    print(f"[CAPTCHA] Solving {'hCaptcha' if is_hcaptcha else 'reCAPTCHA'} via 2captcha...")
    try:
        solver = TwoCaptcha(api_key)
        loop = asyncio.get_running_loop()
        if is_hcaptcha:
            result = await loop.run_in_executor(
                None, lambda: solver.hcaptcha(sitekey=sitekey, url=page.url)
            )
        else:
            result = await loop.run_in_executor(
                None, lambda: solver.recaptcha(sitekey=sitekey, url=page.url)
            )

        token = result["code"]
        await page.evaluate(
            """(token) => {
                const fields = ['h-captcha-response', 'g-recaptcha-response'];
                for (const name of fields) {
                    const el = document.querySelector(`[name="${name}"]`);
                    if (el) el.value = token;
                }
                document.dispatchEvent(new Event('submit', {bubbles: true}));
            }""",
            token,
        )
        print("[CAPTCHA] Token injected.")
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        print(f"[CAPTCHA] 2captcha solver error: {e}")
        return False


# ── Unified handler ───────────────────────────────────────────────────────────

async def handle_if_challenged(page) -> bool:
    """
    Full pipeline: detect -> auto-wait -> 2captcha fallback.
    Returns True if the challenge was resolved (page is safe to proceed).
    Returns False if the page is still blocked.
    """
    if not await is_challenge_page(page):
        return True  # Not challenged

    # Step 1: wait for JS auto-clear
    if await wait_for_challenge_resolution(page):
        return True

    # Step 2: try 2captcha
    if await solve_captcha_2captcha(page):
        await page.wait_for_timeout(2000)
        return not await is_challenge_page(page)

    return False
