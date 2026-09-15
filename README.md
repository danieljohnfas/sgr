# SGR Ticket Bot

Single entry point. All route, date, phone, and OTP settings live in `sgr_bot/config.py` (overridable by env).

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m sgr_bot --warmup
python -m sgr_bot
```

`python run.py` is the same as `python -m sgr_bot`.

## Commands

| Command | What it does |
|---|---|
| `python -m sgr_bot` | Poll until a seat appears, then book |
| `python -m sgr_bot --warmup` | Validate or create a session; do not book |
| `python -m sgr_bot --relogin` | Ignore cache; OTP login from scratch |
| `python -m sgr_bot --status` | Phone lockouts and cached sessions |
| `python -m sgr_bot --phone 712345678` | Prepend a number to the pool |

## Configuration

`SGR_PHONE` (or `SGR_PHONES`) is required — no phone number is committed as a
default. Edit `sgr_bot/config.py` or set env vars:

```powershell
$env:SGR_PHONE = "712345678"
$env:SGR_PHONES = "712345678,798765432"
$env:SGR_TRAVEL_DATE = "2026-08-21"
$env:SGR_TRAVEL_DAY = "21"
$env:SGR_TRAIN_TIME = "16:25:00"
$env:SGR_BOARDING_NAME = "Morogoro"
$env:SGR_LANDING_NAME = "Dar Es Salaam"
$env:SGR_OTP_STRATEGY = "auto"   # auto | manual | file | email | adb
```

Trusted proxy only (never a free public list on a logged-in session):

```powershell
$env:SGR_PROXY = "http://user:pass@host:port"
```

## OTP

| Strategy | Behavior |
|---|---|
| `auto` (default) | ADB → Africa's Talking → Twilio → IMAP → `otp.txt` → stdin |
| `manual` | Type the code in the terminal |
| `file` | Write a 6-digit code to `otp.txt` |
| `email` | IMAP (`SGR_IMAP_HOST`, `SGR_IMAP_USER`, `SGR_IMAP_PASS`) |
| `adb` | USB-connected Android SMS inbox |

IMAP aliases without the `SGR_` prefix still work.

## Layout

```
sgr_bot/
  main.py            Orchestrator
  config.py          Single config
  login_engine.py    OTP login + phone rotation
  auth.py            Session validity
  searcher.py        Browser SearchTrip polling
  booker.py          Class / seat / payment
  otp_delivery.py    OTP backends
  phone_pool.py      Lockout tracking (60s resend, 10m login)
  session_pool.py    Cached storage_state
  selectors.py       DOM selectors
archive/scratch/     Old exploration scripts (not used, not tracked in git)
```

## Output

`control_number.txt` is gitignored. Failure dumps (`*.html`, `*.png`) are gitignored.
`archive/` (old one-off scripts and captured debug pages) is gitignored too —
several of those scripts embedded real phone numbers from earlier manual runs.
