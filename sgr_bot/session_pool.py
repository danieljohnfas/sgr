"""Session pool — cache Playwright storage_state files keyed by phone."""
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from . import config

SESSION_DIR = Path("sessions")
SESSION_META = SESSION_DIR / "meta.json"


class SessionPool:
    def __init__(self):
        SESSION_DIR.mkdir(exist_ok=True)
        self._meta: dict = self._load_meta()

    def get_valid_session(self) -> Optional[str]:
        now = time.time()
        for name, info in self._meta.items():
            path = SESSION_DIR / name
            if not path.exists():
                continue
            created = info.get("created", 0)
            if now - created < config.SESSION_TTL_S:
                print(f"[SessionPool] Candidate cached session: {name} "
                      f"(age {(now - created) / 60:.0f}m) — still needs live validation")
                return str(path)
        print("[SessionPool] No valid cached session found.")
        return None

    def save_session(self, state_path: str, phone: str):
        name = f"state_{phone}.json"
        dest = SESSION_DIR / name
        tmp = dest.with_suffix(".tmp")
        shutil.copy(state_path, tmp)
        os.replace(tmp, dest)
        self._meta[name] = {"phone": phone, "created": time.time()}
        self._save_meta()
        print(f"[SessionPool] Session saved: {name}")

    def invalidate(self, phone: str):
        name = f"state_{phone}.json"
        if name in self._meta:
            self._meta[name]["created"] = 0
            self._save_meta()
            print(f"[SessionPool] Session invalidated: {name}")

    def status(self) -> str:
        now = time.time()
        lines = ["Session Pool Status:"]
        for name, info in self._meta.items():
            age = now - info.get("created", 0)
            ttl = config.SESSION_TTL_S - age
            if ttl > 0:
                lines.append(f"  {name}: VALID ({ttl / 60:.0f}m remaining)")
            else:
                lines.append(f"  {name}: EXPIRED")
        if not self._meta:
            lines.append("  (empty)")
        return "\n".join(lines)

    def _load_meta(self) -> dict:
        if SESSION_META.exists():
            try:
                return json.loads(SESSION_META.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_meta(self):
        tmp = SESSION_META.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._meta, indent=2), encoding="utf-8")
        os.replace(tmp, SESSION_META)
