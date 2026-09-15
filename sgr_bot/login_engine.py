"""
Login engine: phone rotation, OTP backends, resend-cooldown awareness.

Site timers (localStorage CONFIGURATION):
  phoneLoginValidationResendBloackageTime = 60 seconds
  loginLockoutDuration                    = 10 minutes
  phoneLoginPeriodValidity                = 180 seconds
"""
import asyncio
import random
import time
from typing import Tuple

from . import config, selectors
from .browser_utils import set_angular_input
from .otp_delivery import get_otp
from .phone_pool import PhonePool
from .session_pool import SessionPool

OTP_SELECTOR = selectors.OTP_INPUT
PHONE_SELECTORS = selectors.PHONE_INPUT_CANDIDATES


async def login_with_bypass(page, context,
                             phone_pool: PhonePool,
                             session_pool: SessionPool,
                             journey_url: str | None = None) -> Tuple[bool, str]:
    journey_url = journey_url or config.JOURNEY_PAGE_URL
    max_outer = 5
    for outer in range(max_outer):
        phone = phone_pool.get_available()
        if phone is None:
            wait_s = phone_pool.soonest_recovery_secs()
            print(f"\n[Auth] All phone numbers locked. Waiting {wait_s:.0f}s...")
            await asyncio.sleep(wait_s + 5)
            phone = phone_pool.get_available()
            if phone is None:
                print("[Auth] Still no available number. Giving up.")
                return False, ""

        print(f"\n[Auth] Attempting login with phone ending …{phone[-4:]} (attempt {outer + 1})")

        result, why = await _do_login(page, context, phone, journey_url)
        if result:
            phone_pool.mark_success(phone)
            session_pool.save_session(config.STATE_FILE, phone)
            return True, phone

        print(f"[Auth] Login failed: {why}")
        if "lockout" in why.lower():
            phone_pool.mark_login_locked(phone)
        elif "resend" in why.lower() or "blocked" in why.lower():
            phone_pool.mark_otp_locked(phone)
        elif "navigation error" in why.lower():
            print("[Auth] Navigation timeout — not counting as phone failure")
        else:
            phone_pool.mark_failure(phone)

    return False, ""


async def _do_login(page, context, phone: str, journey_url: str) -> Tuple[bool, str]:
    try:
        await page.goto(journey_url, wait_until="commit", timeout=30000)
        try:
            await page.locator("a.login, app-root, .navbar").first.wait_for(
                state="visible", timeout=30000
            )
        except Exception:
            pass
    except Exception as e:
        return False, f"navigation error: {e}"

    try:
        await page.locator(selectors.LOGIN_LINK).first.click()
        await _human(page, 1500, 2200)
    except Exception as e:
        return False, f"login link click failed: {e}"

    try:
        await page.locator(selectors.MOBILE_TAB_BTN).first.click()
        await _human(page, 700, 1200)
    except Exception:
        pass

    entered = await _enter_phone(page, phone)
    if not entered:
        return False, "phone input not found"
    await _human(page, 600, 1000)

    print("[Auth] Clicking Login (OTP send)...")
    await page.evaluate("""
        () => {
            for (let b of document.querySelectorAll('ngb-modal-window button, .modal button')) {
                if (b.innerText.trim() === 'Login') { b.click(); return; }
            }
        }
    """)
    otp_sent_at = time.time()

    print("[Auth] Waiting for OTP input field...")
    try:
        await page.locator('input[formcontrolname="code"]').first.wait_for(
            state="visible", timeout=15000
        )
    except Exception:
        await page.screenshot(path="lockout_debug.png")
        content = await page.content()
        with open("lockout.html", "w", encoding="utf-8") as f:
            f.write(content)
        if "account is locked" in content.lower() or "too many failed" in content.lower():
            return False, "account lockout detected"
        return False, "OTP input did not appear — possibly no SMS sent"

    await page.screenshot(path="otp_prompt_current.png")
    print("[Auth] OTP prompt visible. Getting OTP code...")

    remaining_s = max(10, config.OTP_VALIDITY_S - int(time.time() - otp_sent_at) - 15)
    otp = await get_otp(timeout_s=remaining_s)
    if not otp:
        print("[Auth] OTP not received — trying Send Again...")
        if await wait_for_resend_and_retry(page):
            otp_sent_at = time.time()
            remaining_s = max(10, config.OTP_VALIDITY_S - 15)
            otp = await get_otp(timeout_s=remaining_s)
        if not otp:
            return False, "OTP not received in time"

    print(f"[Auth] OTP received after {time.time() - otp_sent_at:.0f}s")

    submit_enabled = await _wait_for_submit_enabled(page, timeout_s=10)
    if not submit_enabled:
        print("[Auth] Submit button not enabled — proceeding anyway.")

    if not await _type_otp(page, otp):
        return False, "OTP input field not found/clickable"
    await _human(page, 600, 1000)

    print("[Auth] Submitting OTP...")
    if not await _click_submit(page):
        return False, "Submit button not found"
    await _human(page, 4000, 6000)

    await page.screenshot(path="logged_in_current.png")
    content = await page.content()

    if "AUTH119" in content or "Verification code is not correct" in content:
        return False, "AUTH119 — wrong OTP"
    if "account is locked" in content.lower() or "too many failed" in content.lower() or "account locked" in content.lower():
        return False, "lockout — too many failed attempts"

    modal_count = await page.locator("ngb-modal-window").count()
    login_visible = await page.locator(selectors.LOGIN_LINK).count()
    user_info = await page.evaluate("() => localStorage.getItem('USER_INFO')")

    if modal_count == 0 or login_visible == 0 or (user_info and '"ip"' in user_info):
        await context.storage_state(path=config.STATE_FILE)
        print("[Auth] Login SUCCESS.")
        return True, ""

    await page.wait_for_timeout(3000)
    modal_count = await page.locator("ngb-modal-window").count()
    if modal_count == 0:
        await context.storage_state(path=config.STATE_FILE)
        print("[Auth] Login SUCCESS — modal dismissed after extra wait.")
        return True, ""

    content2 = await page.content()
    if "AUTH119" in content2 or "Verification code is not correct" in content2:
        return False, "AUTH119 — wrong OTP (delayed)"

    return False, "unknown post-OTP state"


async def wait_for_resend_and_retry(page) -> bool:
    print("[Auth] Checking if 'Send Again' is available...")
    deadline = time.time() + config.OTP_RESEND_LOCKOUT_S + 10
    while time.time() < deadline:
        enabled = await page.locator(selectors.SEND_AGAIN_BTN).count()
        if enabled > 0:
            print("[Auth] 'Send Again' is enabled. Requesting new OTP...")
            await page.locator(selectors.SEND_AGAIN_BTN).first.click()
            await _human(page, 2000, 3000)
            return True
        remaining = await page.evaluate("""
            () => {
                const el = document.querySelector('.counter');
                if (el) {
                    const m = el.innerText.match(/[0-9]+/);
                    return m ? parseInt(m[0]) : null;
                }
                return null;
            }
        """)
        if remaining is not None:
            print(f"[Auth] Send Again locked ({remaining}s). Waiting...")
        await asyncio.sleep(5)
    return False


async def _enter_phone(page, phone: str) -> bool:
    for sel in PHONE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                if await set_angular_input(page, sel, phone):
                    return True
        except Exception:
            continue
    return False


async def _type_otp(page, otp: str) -> bool:
    for sel in selectors.OTP_INPUT_CANDIDATES:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.wait_for(state="visible", timeout=5000)
                await loc.click()
                print(f"[Auth] OTP input found: {sel}")
                await _human(page, 200, 400)
                for digit in otp:
                    await page.keyboard.type(digit, delay=random.randint(80, 200))
                return True
        except Exception as e:
            print(f"[Auth] OTP selector miss ({sel}): {e}")
    return False


async def _wait_for_submit_enabled(page, timeout_s: int = 15) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if await page.locator(selectors.OTP_SUBMIT_ENABLED).count() > 0:
            return True
        await asyncio.sleep(0.5)
    return False


async def _click_submit(page) -> bool:
    for sel in [selectors.OTP_SUBMIT_ENABLED, selectors.OTP_SUBMIT_BTN]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                return True
        except Exception:
            pass
    return await page.evaluate("""
        () => {
            for (let b of document.querySelectorAll('button')) {
                if (b.innerText.trim() === 'Submit') { b.click(); return true; }
            }
            return false;
        }
    """)


async def _human(page, lo=300, hi=900):
    await page.wait_for_timeout(random.randint(lo, hi))
