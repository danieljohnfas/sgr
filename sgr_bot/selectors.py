"""
Centralized CSS/Playwright selectors.
Update here when SGR's Angular template changes — nowhere else.
"""

# ── Login / Auth ─────────────────────────────────────────────────────────────
LOGIN_LINK          = "a.login"
MOBILE_TAB_BTN      = "button:has-text('Mobile')"
PHONE_INPUT         = "input[formcontrolname='mobile'], input[mask='000000000'], .modal input[type='text']"
LOGIN_MODAL_BTN     = ".modal button:has-text('Login')"
OTP_INPUT           = "input[formcontrolname='code'], input[mask='A A A A A A']"
OTP_SUBMIT_BTN      = ".modal button:has-text('Submit'), .modal button:has-text('Verify')"
OTP_SUBMIT_ENABLED  = ".modal button.cursorEnableTopButton, ngb-modal-window button.cursorEnableTopButton"
SEND_AGAIN_BTN      = ".cursorEnable:has-text('Send Again'), span.cursorEnable:has-text('Send Again')"

# Tried in order (not combined into one CSS selector) so the first structurally
# matching field wins even when several selectors could technically match.
PHONE_INPUT_CANDIDATES = [
    'input[formcontrolname="mobile"]',
    'input[mask="000000000"]',
    'ngb-modal-window input[type="text"]',
]
OTP_INPUT_CANDIDATES = [
    'input[formcontrolname="code"]',
    'input[mask="A A A A A A"]',
    'app-phone-confirm input',
    'ngb-modal-window input[type="text"]',
]

# ── Journey Search Form ───────────────────────────────────────────────────────
BOARDING_SELECT     = "ng-select[formcontrolname='boardingStationId']"
LANDING_SELECT      = "ng-select[formcontrolname='landingStationId']"
CALENDAR_BTN        = "button.calendar, .input-group-append, button[class*='calendar'], .date-picker-btn"
SEARCH_BTN          = "button.btn-search"

# ── Results / Trip Selection ──────────────────────────────────────────────────
DROPDOWN_TOGGLE     = "button.dropdown-toggle"
DROPDOWN_ITEM       = ".dropdown-item"
NEXT_BTN            = "button.ticket-navigation__next"

# ── Seat Map ──────────────────────────────────────────────────────────────────
WAGON_BTN           = ".wagon-btn, .nav-link.wagon-item, .wagon-item"
AVAILABLE_SEAT      = ".slot-box:not(.unavailable-seat):not(.disabled):not(.seat-unavailable):not(.legend)"

# ── Payment ───────────────────────────────────────────────────────────────────
PAYMENT_BTN         = "button:has-text('Payment')"
CONTROL_NUMBER_BTN  = "button:has-text('Get Control Number')"
PAYMENT_BTN_LABELS  = ["Payment", "Make Payment", "Pay Now", "Proceed to Pay"]
CONTROL_NUMBER_BTN_LABELS = ["Get Control Number", "Get Control No", "Control Number", "Generate Bill"]

# ── Block / Challenge Detection ───────────────────────────────────────────────
CHALLENGE_KEYWORDS  = [
    "checking your browser",
    "just a moment",
    "cf-browser-verification",
    "hcaptcha",
    "recaptcha",
    "enable javascript",
    "access denied",
    "too many requests",
]
BLOCK_HTTP_CODES    = {429, 403, 503, 502}
