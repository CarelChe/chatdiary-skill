#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def pending_dir() -> Path:
    default_root = Path(os.environ.get("CHATDIARY_SKILL_DIR", str(Path(__file__).resolve().parents[2]))) / ".chatdiary" / "adapters" / "openclaw"
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
    return str(value)


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    sid = session_id(payload)
    text = text_from(payload.get("message") or payload.get("text") or payload.get("content"))
    pending = {"session_id": sid, "text": text, "timestamp": payload.get("timestamp") or payload.get("created_at")}
    (pending_dir() / f"{sid}.json").write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "stored": bool(text)}))


if __name__ == "__main__":
    main()
