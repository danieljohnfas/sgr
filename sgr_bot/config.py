"""
SGR Bot — Central Configuration
Override via environment variables. Phone numbers should not be committed
in extra copies; keep them here or in SGR_PHONE / SGR_PHONES.
"""
import os


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        val = os.getenv(name)
        if val is not None and val.strip():
            return val.strip()
    return default


def _csv_phones(raw: str) -> list[str]:
    out = []
    for part in raw.split(","):
        n = "".join(ch for ch in part if ch.isdigit())
        if n.startswith("0"):
            n = n[1:]
        if n.startswith("255") and len(n) >= 12:
            n = n[3:]
        if n:
            out.append(n)
    return out


# ─── Route & Schedule ───────────────────────────────────────────────────────
BOARDING_STATION_ID   = int(_env("SGR_BOARDING_ID", "6"))   # 6 = Morogoro
LANDING_STATION_ID    = int(_env("SGR_LANDING_ID", "1"))    # 1 = Dar Es Salaam
BOARDING_STATION_NAME = _env("SGR_BOARDING_NAME", "Morogoro")
LANDING_STATION_NAME  = _env("SGR_LANDING_NAME", "Dar Es Salaam")
TRAVEL_DATE           = _env("SGR_TRAVEL_DATE", "2026-08-21")   # YYYY-MM-DD
TRAVEL_DATE_DAY       = _env("SGR_TRAVEL_DAY", "21")            # calendar cell text
TARGET_TRAIN_TIME     = _env("SGR_TRAIN_TIME", "16:25:00")      # empty = any train

# ─── Auth Credentials ────────────────────────────────────────────────────────
# Digits only, no leading 0, no country code. Set via SGR_PHONE or
# comma-separated SGR_PHONES — no default is committed here on purpose.
PHONE_NUMBERS = _csv_phones(_env_first("SGR_PHONES", "SGR_PHONE"))
PHONE_NUMBER = PHONE_NUMBERS[0] if PHONE_NUMBERS else ""

# ─── OTP Delivery ────────────────────────────────────────────────────────────
# auto   → ADB, Africa's Talking, Twilio, IMAP, then file, then stdin
# manual → type OTP in the terminal
# file   → watch otp.txt
# email  → IMAP only
# adb    → USB Android SMS inbox only
OTP_STRATEGY = _env_first("SGR_OTP_STRATEGY", default="auto").lower()

IMAP_HOST     = _env_first("SGR_IMAP_HOST", "IMAP_HOST", default="imap.gmail.com")
IMAP_USER     = _env_first("SGR_IMAP_USER", "IMAP_USER")
IMAP_PASS     = _env_first("SGR_IMAP_PASS", "IMAP_PASS")
IMAP_SENDER   = _env_first("SGR_IMAP_SENDER", "IMAP_SENDER", default="TRC")
OTP_TIMEOUT_S = int(_env("SGR_OTP_TIMEOUT", "120"))

AT_API_KEY    = _env_first("SGR_AT_API_KEY", "AT_API_KEY")
AT_USERNAME   = _env_first("SGR_AT_USERNAME", "AT_USERNAME")
AT_SHORT_CODE = _env_first("SGR_AT_SHORT_CODE", "AT_SHORT_CODE", default="TRC")

TWILIO_ACCOUNT_SID = _env_first("SGR_TWILIO_SID", "TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = _env_first("SGR_TWILIO_TOKEN", "TWILIO_AUTH_TOKEN")
TWILIO_NUMBER      = _env_first("SGR_TWILIO_NUMBER", "TWILIO_NUMBER")

# Site timers (CONFIGURATION in localStorage)
OTP_VALIDITY_S        = 180
OTP_RESEND_LOCKOUT_S  = 60          # resend cooldown is 60 seconds, not 60 minutes
LOGIN_LOCKOUT_S       = 10 * 60
SESSION_TTL_S         = int(2.5 * 3600)

# ─── API Endpoints ───────────────────────────────────────────────────────────
SGR_BASE_URL      = "https://sgrticket.trc.co.tz"
SGR_API_BASE      = "https://sgrticket-api.trc.co.tz/TICIDIS/api/v1"
SEARCH_TRIP_URL   = f"{SGR_API_BASE}/Public/SearchTrip"
JOURNEY_PAGE_URL  = f"{SGR_BASE_URL}/purchase/journey-selection"

# ─── Polling ─────────────────────────────────────────────────────────────────
POLL_INTERVAL_MIN_S  = 8
POLL_INTERVAL_MAX_S  = 15
MAX_POLL_ATTEMPTS    = 0    # 0 = poll until seats found

# ─── Proxy ───────────────────────────────────────────────────────────────────
# Only an explicit trusted proxy is used for the logged-in browser.
# Free public lists are never attached to an authenticated session.
PROXY_SERVER = _env_first("SGR_PROXY", "HTTPS_PROXY", "HTTP_PROXY")
USE_PROXY = bool(PROXY_SERVER)

# ─── Browser / Stealth ───────────────────────────────────────────────────────
HEADLESS = _env("SGR_HEADLESS", "1") not in ("0", "false", "False")
STATE_FILE = "state.json"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]
VIEWPORT_OPTIONS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

# ─── CAPTCHA ─────────────────────────────────────────────────────────────────
CAPTCHA_WAIT_S     = 30
TWOCAPTCHA_API_KEY = _env_first("SGR_2CAPTCHA_KEY")

# ─── Booking output ──────────────────────────────────────────────────────────
CONTROL_NUMBER_FILE = "control_number.txt"
OTP_FILE            = "otp.txt"
