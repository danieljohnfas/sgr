"""
Seat availability searcher.

Prefers a continuous browser session (form filled once, Search clicked
repeatedly) so the Angular login does not idle out. Direct API polling is
a fallback and never disables TLS.
"""
import asyncio
import random
from datetime import datetime
from typing import Optional

from . import config, selectors
from .browser_utils import dump_debug, safe_goto
from .captcha import is_blocked_response


class SeatResult:
    def __init__(self, trip: dict, car: dict):
        self.trip = trip
        self.car = car
        self.trip_id = trip.get("tripId")
        self.route_id = trip.get("routeId")
        self.start_time = trip.get("startTime")
        self.car_type_name = car.get("typeName")
        self.empty_seats = car.get("emptyStandardSeats", car.get("emptySeats", 0))

    def __str__(self):
        return (
            f"Train {self.start_time} | "
            f"Class: {self.car_type_name} | "
            f"Empty seats: {self.empty_seats} | "
            f"tripId={self.trip_id}"
        )


class AuthExpiredError(Exception):
    pass


async def poll_api(cookies: Optional[list] = None) -> Optional[SeatResult]:
    try:
        import aiohttp
    except ImportError:
        print("[Searcher] aiohttp not installed.")
        return None

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": random.choice(config.USER_AGENTS),
        "Origin": config.SGR_BASE_URL,
        "Referer": config.JOURNEY_PAGE_URL,
    }
    if cookies:
        cookie_header = "; ".join(
            f"{c['name']}={c['value']}"
            for c in cookies
            if str(c.get("domain", "")).endswith("trc.co.tz")
        )
        if cookie_header:
            headers["Cookie"] = cookie_header

    payload = {
        "boardingStationId": config.BOARDING_STATION_ID,
        "landingStationId": config.LANDING_STATION_ID,
        "date": config.TRAVEL_DATE,
        "isOneWay": True,
        "passengerCount": 1,
        "departureDate": f"{config.TRAVEL_DATE}T00:00:00.000Z",
        "returnDate": f"{config.TRAVEL_DATE}T00:00:00.000Z",
        "isReservation": False,
        "loginType": 2,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(config.SEARCH_TRIP_URL, json=payload, headers=headers) as resp:
                if await is_blocked_response(resp):
                    print(f"[Searcher] API blocked: HTTP {resp.status}")
                    return None
                if resp.status == 401:
                    raise AuthExpiredError()
                data = await resp.json(content_type=None)
                return _find_target_seat(data)
    except AuthExpiredError:
        raise
    except Exception as e:
        print(f"[Searcher] API poll error: {e}")
        return None


async def poll_browser(page) -> Optional[SeatResult]:
    ok = await safe_goto(page, config.JOURNEY_PAGE_URL)
    if not ok:
        return None
    if not await fill_search_form(page):
        return None
    return await search_once(page)


async def fill_search_form(page) -> bool:
    try:
        print(f"[Searcher] Filling form {config.BOARDING_STATION_NAME} -> "
              f"{config.LANDING_STATION_NAME} on {config.TRAVEL_DATE}...")
        await page.wait_for_timeout(1500)

        await page.locator(selectors.BOARDING_SELECT).click()
        await page.wait_for_timeout(500)
        await page.keyboard.type(config.BOARDING_STATION_NAME)
        await page.wait_for_timeout(400)
        opt = page.locator(f".ng-option:has-text('{config.BOARDING_STATION_NAME}')").first
        try:
            await opt.click(timeout=5000)
        except Exception:
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(400)

        await page.locator(selectors.LANDING_SELECT).click()
        await page.wait_for_timeout(500)
        await page.keyboard.type(config.LANDING_STATION_NAME)
        await page.wait_for_timeout(400)
        opt = page.locator(f".ng-option:has-text('{config.LANDING_STATION_NAME}')").first
        try:
            await opt.click(timeout=5000)
        except Exception:
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(400)

        await page.click(selectors.CALENDAR_BTN)
        await page.wait_for_timeout(500)
        dt = datetime.strptime(config.TRAVEL_DATE, "%Y-%m-%d")
        picked = await page.evaluate(
            """({day, month, year}) => {
                const cells = document.querySelectorAll('[role="gridcell"]');
                for (const c of cells) {
                    const label = (c.getAttribute('aria-label') || '').toLowerCase();
                    if (label.includes(month.toLowerCase())
                        && label.includes(String(year))
                        && (label.includes(day) || label.split(/\\D/).includes(day))) {
                        c.click();
                        return true;
                    }
                }
                for (const c of cells) {
                    if (c.innerText.trim() === day && !c.classList.contains('text-muted')) {
                        c.click();
                        return true;
                    }
                }
                return false;
            }""",
            {"day": str(dt.day), "month": dt.strftime("%B"), "year": dt.year},
        )
        if not picked:
            print("[Searcher] Could not click travel date in calendar.")
            return False
        await page.wait_for_timeout(400)
        await page.mouse.click(0, 0)
        return True
    except Exception as e:
        print(f"[Searcher] Form fill error: {e}")
        await dump_debug(page, "searcher_form_fail")
        return False


async def _dismiss_swal(page):
    try:
        btn = page.locator(".swal2-container .swal2-confirm").first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(timeout=1000)
            await page.wait_for_timeout(400)
    except Exception:
        pass


async def search_once(page) -> Optional[SeatResult]:
    await _dismiss_swal(page)
    async with page.expect_response(
        lambda r: "SearchTrip" in r.url, timeout=30_000
    ) as resp_info:
        await page.click(selectors.SEARCH_BTN, timeout=10_000)
    resp = await resp_info.value
    if await is_blocked_response(resp):
        print(f"[Searcher] Search blocked: HTTP {resp.status}")
        return None
    if resp.status == 401:
        raise AuthExpiredError()
    data = await resp.json()
    result = _find_target_seat(data)
    if result is None:
        for trip in data.get("data", []) if isinstance(data.get("data"), list) else []:
            seats = sum(
                c.get("emptyStandardSeats", c.get("emptySeats", 0))
                for c in trip.get("railwayCars", [])
            )
            t = str(trip.get("startTime", "?"))[:5]
            print(f"  Train {t} | seats: {seats}")
    return result


def _find_target_seat(data: dict) -> Optional[SeatResult]:
    if not isinstance(data, dict):
        return None
    target = config.TARGET_TRAIN_TIME
    trips = data.get("data", [])
    if not isinstance(trips, list):
        return None
    for trip in trips:
        start = str(trip.get("startTime") or "")
        if target:
            needle = target[:5] if len(target) >= 5 else target
            if start != target and not start.startswith(needle):
                continue
        for car in trip.get("railwayCars", []):
            empty = car.get("emptyStandardSeats", car.get("emptySeats", 0))
            if empty > 0:
                result = SeatResult(trip, car)
                print(f"[Searcher] SEAT FOUND: {result}")
                return result
    return None


async def wait_for_seat(context, page, proxy_pool=None) -> SeatResult:
    """Poll in the live browser until a seat is found. proxy_pool is unused."""
    del proxy_pool  # authenticated session must not rotate onto public proxies
    attempt = 0
    form_filled = False

    while True:
        attempt += 1
        print(f"\n[Searcher] Poll attempt #{attempt} (browser)...")
        try:
            if not form_filled:
                if "journey-selection" not in (page.url or ""):
                    await safe_goto(page, config.JOURNEY_PAGE_URL)
                form_filled = await fill_search_form(page)
                if not form_filled:
                    await asyncio.sleep(5)
                    continue

            result = await search_once(page)
            if result:
                return result
        except AuthExpiredError:
            print("[Searcher] Auth expired during polling.")
            raise
        except Exception as e:
            print(f"[Searcher] Browser poll error: {e}")
            await dump_debug(page, "searcher_error")
            form_filled = False
            try:
                await page.reload(wait_until="commit")
            except Exception:
                pass

        if config.MAX_POLL_ATTEMPTS and attempt >= config.MAX_POLL_ATTEMPTS:
            raise RuntimeError(f"Max poll attempts ({config.MAX_POLL_ATTEMPTS}) reached.")

        interval = random.uniform(config.POLL_INTERVAL_MIN_S, config.POLL_INTERVAL_MAX_S)
        print(f"[Searcher] No seats yet. Waiting {interval:.1f}s...")
        await asyncio.sleep(interval)
