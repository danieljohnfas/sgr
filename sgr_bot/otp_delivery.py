"""
OTP delivery. Strategy is config.OTP_STRATEGY (auto | manual | file | email | adb).

Env names: SGR_IMAP_*, SGR_AT_*, SGR_TWILIO_* (unprefixed aliases still work).
"""
import asyncio
import email
import imaplib
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import config

_OTP_RE = re.compile(r"\b(\d{6})\b")


def _sanitize_imap_atom(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9 ._@+-]', "", value)[:80]


# ── ADB ───────────────────────────────────────────────────────────────────────

def _adb_available() -> bool:
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=5
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return any("device" in line and not line.startswith("List") for line in lines)
    except Exception:
        return False


def _adb_read_otp(sender_keyword: str = "TRC", timeout_s: int = 120) -> Optional[str]:
    print("[OTP/ADB] Waiting for SMS from TRC...")
    deadline = time.time() + timeout_s
    seen: set[str] = set()
    while time.time() < deadline:
        try:
            result = subprocess.run(
                [
                    "adb", "shell",
                    "content", "query",
                    "--uri", "content://sms/inbox",
                    "--projection", "body,date,address",
                    "--sort", "date DESC",
                ],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines()[:20]:
                if sender_keyword.upper() not in line.upper():
                    continue
                match = _OTP_RE.search(line)
                if not match:
                    continue
                code = match.group(1)
                if code in seen:
                    continue
                seen.add(code)
                date_match = re.search(r"date=(\d+)", line)
                if date_match:
                    raw = int(date_match.group(1))
                    msg_ts = raw / 1000 if raw > 10_000_000_000 else raw
                    if time.time() - msg_ts >= 180:
                        continue
                print("[OTP/ADB] Found OTP.")
                return code
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"[OTP/ADB] Error: {e}")
        time.sleep(3)
    return None


# ── Africa's Talking / Twilio ─────────────────────────────────────────────────

async def _africastalking_read_otp(timeout_s: int) -> Optional[str]:
    try:
        import africastalking
        africastalking.initialize(config.AT_USERNAME, config.AT_API_KEY)
        sms = africastalking.SMS
    except ImportError:
        print("[OTP/AT] africastalking package not installed.")
        return None
    except Exception as e:
        print(f"[OTP/AT] Init error: {e}")
        return None

    print("[OTP/AT] Polling Africa's Talking inbox...")
    deadline = time.time() + timeout_s
    sender = (config.AT_SHORT_CODE or "TRC").upper()
    while time.time() < deadline:
        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: sms.fetchMessages(lastReceivedId=0))
            messages = resp.get("SMSMessageData", {}).get("Messages", [])
            for msg in sorted(messages, key=lambda m: m.get("date", ""), reverse=True)[:10]:
                text = msg.get("text", "")
                from_ = str(msg.get("from", "")).upper()
                if sender not in from_ and sender not in text.upper():
                    continue
                match = _OTP_RE.search(text)
                if match:
                    print("[OTP/AT] OTP found.")
                    return match.group(1)
        except Exception as e:
            print(f"[OTP/AT] Error: {e}")
        await asyncio.sleep(5)
    return None


async def _twilio_read_otp(timeout_s: int) -> Optional[str]:
    try:
        from twilio.rest import Client
    except ImportError:
        print("[OTP/Twilio] twilio package not installed.")
        return None

    print("[OTP/Twilio] Polling Twilio inbox...")
    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    deadline = time.time() + timeout_s
    seen: set[str] = set()
    while time.time() < deadline:
        try:
            msgs = client.messages.list(to=config.TWILIO_NUMBER, limit=5)
            for msg in msgs:
                if msg.sid in seen:
                    continue
                seen.add(msg.sid)
                body = msg.body or ""
                match = _OTP_RE.search(body)
                if match:
                    print("[OTP/Twilio] OTP found.")
                    return match.group(1)
        except Exception as e:
            print(f"[OTP/Twilio] Error: {e}")
        await asyncio.sleep(5)
    return None


# ── IMAP ──────────────────────────────────────────────────────────────────────

def _email_body(msg) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    parts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
                except Exception:
                    pass
        return " ".join(parts)
    try:
        return msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _imap_read_otp(timeout_s: int) -> Optional[str]:
    host, user, passwd = config.IMAP_HOST, config.IMAP_USER, config.IMAP_PASS
    sender = _sanitize_imap_atom(config.IMAP_SENDER or "TRC")
    if not user or not passwd:
        print("[OTP/IMAP] Credentials not configured.")
        return None

    print(f"[OTP/IMAP] Polling {host} for OTP from '{sender}'...")
    deadline = time.time() + timeout_s
    try:
        with imaplib.IMAP4_SSL(host) as mail:
            mail.login(user, passwd)
            mail.select("inbox")
            while time.time() < deadline:
                _, msgs = mail.search(None, f'(UNSEEN FROM "{sender}")')
                for num in msgs[0].split():
                    _, data = mail.fetch(num, "(RFC822)")
                    raw = data[0][1]
                    msg = email.message_from_bytes(raw)
                    match = _OTP_RE.search(_email_body(msg))
                    if match:
                        print("[OTP/IMAP] OTP found.")
                        return match.group(1)
                time.sleep(4)
    except Exception as e:
        print(f"[OTP/IMAP] Error: {e}")
    return None


# ── File / stdin ──────────────────────────────────────────────────────────────

async def _otp_from_file(timeout_s: int) -> Optional[str]:
    p = Path(config.OTP_FILE)
    if p.exists():
        p.unlink()
    print(f"[OTP] Waiting for OTP in {p} (timeout {timeout_s}s)...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
            match = _OTP_RE.search(text)
            if match:
                p.unlink(missing_ok=True)
                print("[OTP] OTP read from file.")
                return match.group(1)
        await asyncio.sleep(2)
    print("[OTP] Timed out waiting for OTP file.")
    return None


async def _otp_manual() -> Optional[str]:
    print("\n" + "=" * 50)
    print("WAITING FOR OTP — check your phone and type it here:")
    print("=" * 50)
    loop = asyncio.get_running_loop()
    otp = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
    match = _OTP_RE.search(otp) if otp else None
    return match.group(1) if match else (otp or None)


async def _try_auto(timeout_s: int) -> Optional[str]:
    loop = asyncio.get_running_loop()
    if _adb_available():
        print("[OTP] Using ADB backend.")
        code = await loop.run_in_executor(None, lambda: _adb_read_otp(timeout_s=timeout_s))
        if code:
            return code
    if config.AT_API_KEY and config.AT_USERNAME:
        print("[OTP] Using Africa's Talking backend.")
        code = await _africastalking_read_otp(timeout_s)
        if code:
            return code
    if config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_NUMBER:
        print("[OTP] Using Twilio backend.")
        code = await _twilio_read_otp(timeout_s)
        if code:
            return code
    if config.IMAP_USER and config.IMAP_PASS:
        print("[OTP] Using IMAP backend.")
        code = await loop.run_in_executor(None, lambda: _imap_read_otp(timeout_s))
        if code:
            return code
    return None


async def get_otp(timeout_s: int | None = None) -> Optional[str]:
    timeout = timeout_s if timeout_s is not None else config.OTP_TIMEOUT_S
    strategy = (config.OTP_STRATEGY or "auto").lower()

    if strategy == "manual":
        return await _otp_manual()
    if strategy == "file":
        return await _otp_from_file(timeout)
    if strategy == "email":
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: _imap_read_otp(timeout))
    if strategy == "adb":
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: _adb_read_otp(timeout_s=timeout))

    code = await _try_auto(timeout)
    if code:
        return code
    print("[OTP] Auto backends empty — waiting on otp.txt, then stdin.")
    code = await _otp_from_file(min(timeout, 60))
    if code:
        return code
    return await _otp_manual()
