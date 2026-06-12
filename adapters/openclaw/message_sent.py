#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def skill_root() -> Path:
    env_root = os.environ.get("CHATDIARY_SKILL_DIR")
    if env_root:
        return Path(env_root).expanduser()
    return Path(__file__).resolve().parents[2]


def chatdiary_script() -> Path:
    explicit = os.environ.get("CHATDIARY_SCRIPT")
    if explicit:
        return Path(explicit).expanduser()
    return skill_root() / "scripts" / "chatdiary.py"


def pending_dir() -> Path:
    default_root = skill_root() / ".chatdiary" / "adapters" / "openclaw"
    path = Path(os.environ.get("CHATDIARY_ADAPTER_STATE_DIR", str(default_root)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_id(payload: dict[str, Any]) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or payload.get("conversation_id") or "default")


def text_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return text_from(value.get("text") or value.get("content") or value.get("message"))
    if isinstance(value, list):
        return "\n".join(text_from(item) for item in value if text_from(item))
    return str(value)


def time_text(payload: dict[str, Any]) -> str:
    raw = payload.get("timestamp") or payload.get("created_at")
    if raw:
        try:
            return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
        except ValueError:
            pass
    return dt.datetime.now().strftime("%H:%M")


def now_arg(payload: dict[str, Any]) -> str | None:
    raw = payload.get("timestamp") or payload.get("created_at")
    return str(raw) if raw else None


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    sid = session_id(payload)
    pending_file = pending_dir() / f"{sid}.json"
    if not pending_file.exists():
        print(json.dumps({"ok": True, "ignored": True, "reason": "no pending user message"}))
        return
    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    pending_file.unlink(missing_ok=True)
    user = pending.get("text", "")
    reply = text_from(payload.get("message") or payload.get("text") or payload.get("content") or payload.get("reply"))
    digest = hashlib.sha256(f"openclaw\0{sid}\0{user}\0{reply}".encode("utf-8")).hexdigest()[:24]
    cmd = [
        sys.executable,
        str(chatdiary_script()),
        "handle-turn",
        "--time",
        time_text(payload),
        "--text",
        user,
        "--reply",
        reply,
        "--source",
        "openclaw-hook",
        "--turn-id",
        f"openclaw-{digest}",
    ]
    raw_now = now_arg(payload)
    if raw_now:
        cmd.extend(["--now", raw_now])
    result = subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
