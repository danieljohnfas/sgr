"""
SGR Bot orchestrator.

    python -m sgr_bot              # poll and book
    python -m sgr_bot --relogin    # force a new OTP login
    python -m sgr_bot --warmup     # login / refresh session only
    python -m sgr_bot --status     # phone and session pool
"""
import argparse
import asyncio
import sys
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

from . import config
from .auth import is_session_valid, login
from .booker import book
from .browser_utils import dump_debug, make_stealth_context
from .login_engine import login_with_bypass
from .phone_pool import PhonePool
from .searcher import AuthExpiredError, wait_for_seat
from .session_pool import SessionPool


def _print_banner(title: str):
    print("=" * 60)
    print(f"  {title}")
    print(f"  Route  : {config.BOARDING_STATION_NAME} -> {config.LANDING_STATION_NAME}")
    print(f"  Date   : {config.TRAVEL_DATE}")
    print(f"  Train  : {config.TARGET_TRAIN_TIME or 'any available'}")
    print(f"  Proxy  : {config.PROXY_SERVER or 'disabled'}")
    print("=" * 60 + "\n")


def _phone_from_state_path(path: str | None) -> str:
    if not path:
        return ""
    stem = Path(path).stem
    return stem.replace("state_", "") if stem.startswith("state_") else ""


async def _login_fresh(page, context, phone_pool: PhonePool, session_pool: SessionPool) -> bool:
    ok, _phone = await login_with_bypass(
        page, context, phone_pool, session_pool, config.JOURNEY_PAGE_URL
    )
    return ok


async def run_relogin():
    _print_banner("SGR Bot — Session Refresh")
    async with async_playwright() as p:
        browser, context, page = await make_stealth_context(p, load_state=False)
        try:
            success = await login(context, page)
            if success:
                print("\nOK Session refreshed.")
                print(f"  State saved to: {config.STATE_FILE}")
            else:
                print("\nFAIL Login failed. Check otp_prompt_current.png.")
                sys.exit(1)
        finally:
            await browser.close()


async def run_warmup():
    _print_banner("SGR Bot — Session Warmup")
    phone_pool = PhonePool()
    session_pool = SessionPool()
    cached = session_pool.get_valid_session()
    async with async_playwright() as p:
        browser, context, page = await make_stealth_context(
            p, load_state=True, storage_state=cached
        )
        try:
            if await is_session_valid(page):
                await context.storage_state(path=config.STATE_FILE)
                print("[Main] Cached session is live. Warmup complete.")
                return
            phone = _phone_from_state_path(cached)
            if phone:
                session_pool.invalidate(phone)
            print("[Main] Cache invalid. Logging in...")
            if not await _login_fresh(page, context, phone_pool, session_pool):
                print("[Main] Warmup login failed.")
                sys.exit(1)
            print("[Main] Warmup complete.")
        finally:
            await browser.close()


async def run_status():
    print(PhonePool().status())
    print()
    print(SessionPool().status())


async def run_booking():
    _print_banner("SGR Ticket Bot")
    phone_pool = PhonePool()
    session_pool = SessionPool()
    cached = session_pool.get_valid_session()

    outer_attempts = 0
    max_outer = 10

    while outer_attempts < max_outer:
        outer_attempts += 1
        print(f"\n[Main] === Browser session #{outer_attempts} ===")
        browser = context = page = None
        try:
            async with async_playwright() as p:
                browser, context, page = await make_stealth_context(
                    p, load_state=True, storage_state=cached
                )
                try:
                    print("[Main] Checking session...")
                    authenticated = await is_session_valid(page)
                    if not authenticated:
                        phone = _phone_from_state_path(cached)
                        if phone:
                            session_pool.invalidate(phone)
                        cached = None
                        print("[Main] Logging in...")
                        authenticated = await _login_fresh(
                            page, context, phone_pool, session_pool
                        )
                    if not authenticated:
                        print("[Main] Could not authenticate. Exiting.")
                        sys.exit(1)

                    print("[Main] Starting seat availability polling...")
                    result = await wait_for_seat(context, page)
                    print(f"\n[Main] Seat available! Booking: {result}")
                    control_number = await book(page, result)

                    if control_number:
                        print("\n[Main] OK BOOKING COMPLETE")
                        print(f"[Main]   Control Number : {control_number}")
                        print(f"[Main]   Saved to       : {config.CONTROL_NUMBER_FILE}")
                        return
                    print("[Main] Booking returned no control number. Retrying...")
                    await dump_debug(page, "main_no_ctrl")

                except AuthExpiredError:
                    print("[Main] Auth expired during run. Relogging in...")
                    cached = None
                    try:
                        if not await _login_fresh(page, context, phone_pool, session_pool):
                            print("[Main] Relogin failed.")
                    except Exception as e:
                        print(f"[Main] Relogin error: {e}")

                except Exception as e:
                    print(f"[Main] Unexpected error: {e}")
                    traceback.print_exc()
                    if page:
                        await dump_debug(page, "main_unexpected")
                finally:
                    try:
                        if context:
                            await context.storage_state(path=config.STATE_FILE)
                    except Exception:
                        pass
                    if browser:
                        await browser.close()
        except Exception as e:
            print(f"[Main] Outer loop error: {e}")
            traceback.print_exc()

        backoff = min(5 * outer_attempts, 60)
        print(f"[Main] Sleeping {backoff}s before retry #{outer_attempts + 1}...")
        await asyncio.sleep(backoff)

    print("[Main] FAIL Max retries reached. Giving up.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="SGR Ticket Bot")
    parser.add_argument("--relogin", action="store_true", help="Force a new OTP login")
    parser.add_argument("--warmup", action="store_true", help="Refresh session only, do not book")
    parser.add_argument("--status", action="store_true", help="Show phone/session pool status")
    parser.add_argument("--phone", help="Phone digits without leading 0 (prepended to pool)")
    args = parser.parse_args()

    if args.phone:
        digits = "".join(ch for ch in args.phone if ch.isdigit())
        if digits.startswith("0"):
            digits = digits[1:]
        if digits:
            config.PHONE_NUMBERS = [digits] + [n for n in config.PHONE_NUMBERS if n != digits]
            config.PHONE_NUMBER = digits

    if not args.status and not config.PHONE_NUMBERS:
        print("[Main] No phone number configured. Set SGR_PHONE or SGR_PHONES "
              "(see README) or pass --phone.")
        sys.exit(1)

    if args.status:
        asyncio.run(run_status())
    elif args.relogin:
        asyncio.run(run_relogin())
    elif args.warmup:
        asyncio.run(run_warmup())
    else:
        asyncio.run(run_booking())


if __name__ == "__main__":
    main()
