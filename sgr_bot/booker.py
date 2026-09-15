"""
Booker: class → seat → payment → GePG control number.
Aborts if class or seat cannot be selected.
"""
from pathlib import Path
from typing import Optional

from . import config, selectors
from .browser_utils import dump_debug, human_delay
from .searcher import SeatResult


async def book(page, result: SeatResult) -> Optional[str]:
    print(f"\n[Booker] Starting booking for: {result}")

    print("[Booker] Step 1: Selecting train class...")
    if not await _select_class(page, result):
        print("[Booker] Could not select class. Aborting.")
        await dump_debug(page, "booker_class_fail")
        return None
    await human_delay(page, 400, 800)
    if await _auth_modal_visible(page):
        return None

    print("[Booker] Step 2: Next to seat map...")
    if not await _click_next(page):
        await dump_debug(page, "booker_next1_fail")
        return None
    try:
        await page.wait_for_selector(".slot-box", state="visible", timeout=10_000)
    except Exception:
        pass
    await human_delay(page, 400, 800)
    await page.screenshot(path="booker_step2_passenger.png")
    if await _auth_modal_visible(page):
        return None

    print("[Booker] Step 3: Selecting available seat...")
    if not await _select_seat(page):
        print("[Booker] Could not select seat. Aborting.")
        await dump_debug(page, "booker_seat_fail")
        return None
    await human_delay(page, 400, 800)

    print("[Booker] Step 4: Next to payment...")
    if not await _click_next(page):
        await dump_debug(page, "booker_next2_fail")
        return None
    await human_delay(page, 3000, 5000)
    await page.screenshot(path="booker_step4_payment.png")
    if await _auth_modal_visible(page):
        return None

    print("[Booker] Step 5: Payment...")
    if not await _click_by_labels(page, selectors.PAYMENT_BTN_LABELS):
        print("[Booker] Payment button not found — trying Next.")
        await _click_next(page)
    await human_delay(page, 4000, 6000)
    if await _auth_modal_visible(page):
        return None

    print("[Booker] Step 6: Get control number...")
    if not await _click_by_labels(page, selectors.CONTROL_NUMBER_BTN_LABELS):
        await dump_debug(page, "booker_ctrl_fail")
        return None

    await human_delay(page, 8000, 12000)
    await page.screenshot(path="booker_step6_control.png")

    print("[Booker] Step 7: Extracting control number...")
    control_number = await _extract_control_number(page)
    if control_number:
        Path(config.CONTROL_NUMBER_FILE).write_text(control_number, encoding="utf-8")
        print(f"\n{'=' * 50}")
        print(f"  CONTROL NUMBER: {control_number}")
        print(f"{'=' * 50}\n")
    else:
        print("[Booker] Could not extract control number from page.")
        await dump_debug(page, "booker_no_ctrl_num")
    return control_number


async def _auth_modal_visible(page) -> bool:
    try:
        content = await page.evaluate("() => document.body ? document.body.innerText : ''")
        text = (content or "").lower()
        if "you should login" in text or "login for this operation" in text:
            print("[Booker] Auth modal — session lost.")
            try:
                await page.locator("button:has-text('Ok'), button:has-text('OK')").first.click()
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


async def _select_class(page, result: SeatResult) -> bool:
    display_time = (result.start_time or "")[:5]
    if not display_time:
        display_time = (config.TARGET_TRAIN_TIME or "")[:5]
    try:
        row = page.locator("tr").filter(has_text=display_time).first
        toggle = row.locator(selectors.DROPDOWN_TOGGLE).first
        await toggle.wait_for(state="visible", timeout=10_000)
        await toggle.click()
        await human_delay(page, 200, 400)

        items = row.locator(selectors.DROPDOWN_ITEM)
        count = await items.count()
        for i in range(count):
            text = await items.nth(i).inner_text()
            if result.car_type_name and result.car_type_name not in text:
                continue
            parts = text.strip().split()
            try:
                if int(parts[-1]) > 0:
                    print(f"[Booker] Clicking class item: {text.strip()}")
                    await items.nth(i).click()
                    return True
            except (ValueError, IndexError):
                pass

        for i in range(count):
            text = await items.nth(i).inner_text()
            parts = text.strip().split()
            try:
                if int(parts[-1]) > 0:
                    print(f"[Booker] Fallback class item: {text.strip()}")
                    await items.nth(i).click()
                    return True
            except (ValueError, IndexError):
                pass
    except Exception as e:
        print(f"[Booker] Class selection error: {e}")
    return False


async def _click_next(page) -> bool:
    try:
        btn = page.locator(selectors.NEXT_BTN).first
        await btn.wait_for(state="visible", timeout=10_000)
        try:
            await btn.click(timeout=5_000)
            return True
        except Exception:
            clicked = await page.evaluate("""
                () => {
                    const b = document.querySelector('button.ticket-navigation__next');
                    if (!b) return false;
                    b.removeAttribute('disabled');
                    b.click();
                    return true;
                }
            """)
            return bool(clicked)
    except Exception as e:
        print(f"[Booker] Next button error: {e}")
        return False


async def _select_seat(page) -> bool:
    try:
        try:
            await page.wait_for_selector(selectors.WAGON_BTN, state="visible", timeout=10_000)
        except Exception:
            pass

        wagons = page.locator(selectors.WAGON_BTN)
        wagon_count = await wagons.count()
        loops = wagon_count if wagon_count > 0 else 1

        for w in range(loops):
            if wagon_count > 0:
                print(f"[Booker] Checking wagon {w + 1}/{wagon_count}...")
                try:
                    await wagons.nth(w).scroll_into_view_if_needed()
                    await wagons.nth(w).click(timeout=3000)
                    await human_delay(page, 800, 1500)
                except Exception:
                    continue
            if await _click_first_available_seat(page):
                return True
        return False
    except Exception as e:
        print(f"[Booker] Seat selection error: {e}")
        return False


async def _click_first_available_seat(page) -> bool:
    try:
        slots = page.locator(selectors.AVAILABLE_SEAT)
        count = await slots.count()
        for i in range(count):
            slot = slots.nth(i)
            is_legend = await slot.evaluate(
                "el => !!(el.closest('.legend') || el.closest('.seat-legend') || el.closest('.legends'))"
            )
            title = await slot.get_attribute("title") or ""
            if is_legend or "Wc" in title or "Luggage" in title:
                continue
            text = (await slot.inner_text()).strip()
            if not text and not title:
                continue
            print(f"[Booker] Clicking seat: {text or title}")
            await slot.scroll_into_view_if_needed()
            await slot.click(timeout=5000, force=True)
            await human_delay(page, 500, 900)
            taken = page.locator("text='This seat is taken'")
            if await taken.count() > 0:
                print("[Booker] Seat taken — trying next.")
                ok_btn = page.locator("button:has-text('Ok')")
                if await ok_btn.count() > 0:
                    await ok_btn.first.click()
                continue
            return True
    except Exception as e:
        print(f"[Booker] Seat click error: {e}")
    return False


async def _click_by_labels(page, labels: list[str]) -> bool:
    for text in labels:
        try:
            btn = page.locator(f"button:has-text('{text}')").first
            if await btn.count() == 0:
                continue
            await btn.wait_for(state="visible", timeout=5_000)
            await btn.click()
            return True
        except Exception:
            continue
    for text in labels:
        clicked = await page.evaluate(
            """(label) => {
                for (const b of document.querySelectorAll('button')) {
                    if (b.innerText.trim() === label) { b.click(); return true; }
                }
                return false;
            }""",
            text,
        )
        if clicked:
            return True
    return False


async def _extract_control_number(page) -> Optional[str]:
    return await page.evaluate(r"""
        () => {
            const body = document.body.innerText || '';
            const labeled = body.match(/control\s*number\s*[:\s]+(9\d{11})/i);
            if (labeled) return labeled[1];
            const match = body.match(/\b9\d{11}\b/);
            return match ? match[0] : null;
        }
    """)
