"""Authentication: session validation and login (delegates to login_engine)."""
from . import config, selectors
from .login_engine import login_with_bypass
from .phone_pool import PhonePool
from .session_pool import SessionPool


async def is_session_valid(page) -> bool:
    try:
        await page.goto(
            config.JOURNEY_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        login_visible = await page.locator(selectors.LOGIN_LINK).count() > 0
        if login_visible:
            print("[Auth] Session EXPIRED — login link visible.")
            return False

        user_info = await page.evaluate("() => localStorage.getItem('USER_INFO')")
        if not user_info:
            print("[Auth] Session EXPIRED — USER_INFO missing from localStorage.")
            return False

        print("[Auth] Session is VALID.")
        return True
    except Exception as e:
        print(f"[Auth] Session check error: {e}")
        return False


async def login(context, page) -> bool:
    ok, _phone = await login_with_bypass(
        page, context, PhonePool(), SessionPool(), config.JOURNEY_PAGE_URL
    )
    return ok


async def ensure_authenticated(context, page) -> bool:
    if await is_session_valid(page):
        return True
    print("[Auth] Session expired. Attempting login...")
    return await login(context, page)
