#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def pending_dir() -> Path:
    default_root = Path(os.environ.get("CHATDIARY_SKILL_DIR", str(Path(__file__).resolve().parents[2]))) / ".chatdiary" / "adapters" / "claude-code"
    path = Path(os.environ.get("CHATDIARY_ADAPTER_STATE_DIR", str(default_root)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_id(payload: dict[str, Any]) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or "default")


def prompt_text(payload: dict[str, Any]) -> str:
    for key in ("prompt", "message", "user_prompt", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    sid = session_id(payload)
    pending = {
        "session_id": sid,
        "text": prompt_text(payload),
        "timestamp": payload.get("timestamp") or payload.get("created_at"),
    }
    (pending_dir() / f"{sid}.json").write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "stored": bool(pending["text"])}))


if __name__ == "__main__":
    main()
