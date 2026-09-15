"""
Phone number pool with per-number lockout tracking.
Lockout durations come from config (site: 60s OTP resend, 10 min login lockout).
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

from . import config

POOL_STATE_FILE = "phone_pool_state.json"
OTP_RESEND_LOCKOUT_S = config.OTP_RESEND_LOCKOUT_S
LOGIN_LOCKOUT_S = config.LOGIN_LOCKOUT_S


class PhonePool:
    def __init__(self, numbers: list[str] | None = None):
        self.numbers = list(numbers or config.PHONE_NUMBERS)
        self._state: dict = {}
        self._load()

    def get_available(self) -> Optional[str]:
        now = time.time()
        for num in self.numbers:
            s = self._state.get(num, {})
            if now > s.get("otp_blocked_until", 0) and now > s.get("login_blocked_until", 0):
                return num
        return None

    def soonest_recovery_secs(self) -> float:
        now = time.time()
        earliest = float("inf")
        for num in self.numbers:
            s = self._state.get(num, {})
            unblock = max(s.get("otp_blocked_until", now), s.get("login_blocked_until", now))
            earliest = min(earliest, unblock - now)
        if earliest == float("inf"):
            return 0.0
        return max(0.0, earliest)

    def mark_otp_locked(self, number: str, duration_s: int | None = None):
        duration_s = OTP_RESEND_LOCKOUT_S if duration_s is None else duration_s
        print(f"[PhonePool] Marking {number} OTP-locked for {duration_s}s.")
        self._state.setdefault(number, {})
        self._state[number]["otp_blocked_until"] = time.time() + duration_s
        self._save()

    def mark_login_locked(self, number: str, duration_s: int | None = None):
        duration_s = LOGIN_LOCKOUT_S if duration_s is None else duration_s
        print(f"[PhonePool] Marking {number} login-locked for {duration_s // 60} min.")
        self._state.setdefault(number, {})
        self._state[number]["login_blocked_until"] = time.time() + duration_s
        self._save()

    def mark_failure(self, number: str):
        self._state.setdefault(number, {})
        n = self._state[number].get("failures", 0) + 1
        self._state[number]["failures"] = n
        print(f"[PhonePool] {number} failure count: {n}")
        if n >= 3:
            self.mark_otp_locked(number)
        self._save()

    def mark_success(self, number: str):
        self._state.setdefault(number, {})
        self._state[number]["failures"] = 0
        self._state[number]["otp_blocked_until"] = 0
        self._state[number]["login_blocked_until"] = 0
        print(f"[PhonePool] {number} reset — success.")
        self._save()

    def status(self) -> str:
        now = time.time()
        lines = ["Phone Pool Status:"]
        for num in self.numbers:
            s = self._state.get(num, {})
            otp_rem = max(0, s.get("otp_blocked_until", 0) - now)
            login_rem = max(0, s.get("login_blocked_until", 0) - now)
            failures = s.get("failures", 0)
            if otp_rem > 0:
                lines.append(f"  {num}: OTP blocked {otp_rem:.0f}s remaining")
            elif login_rem > 0:
                lines.append(f"  {num}: Login blocked {login_rem / 60:.0f}m remaining")
            else:
                lines.append(f"  {num}: AVAILABLE (failures={failures})")
        return "\n".join(lines)

    def _load(self):
        p = Path(POOL_STATE_FILE)
        if p.exists():
            try:
                self._state = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                self._state = {}

    def _save(self):
        path = Path(POOL_STATE_FILE)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        os.replace(tmp, path)
