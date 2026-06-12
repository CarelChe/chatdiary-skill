from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def local_config() -> dict[str, Any]:
    path = Path(__file__).with_name("chatdiary_adapter_config.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def skill_root() -> Path:
    config = local_config()
    if config.get("skill_root"):
        return Path(str(config["skill_root"])).expanduser()
    env_root = os.environ.get("CHATDIARY_SKILL_DIR")
    if env_root:
        return Path(env_root).expanduser()
    current = Path(__file__).resolve()
    if len(current.parents) >= 3:
        candidate = current.parents[2]
        if (candidate / "scripts" / "chatdiary.py").exists():
            return candidate
    return Path.cwd()


def chatdiary_script() -> Path:
    config = local_config()
    if config.get("script"):
        return Path(str(config["script"])).expanduser()
    explicit = os.environ.get("CHATDIARY_SCRIPT")
    if explicit:
        return Path(explicit).expanduser()
    return skill_root() / "scripts" / "chatdiary.py"


def text_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(text_from(item.get("text") or item.get("content")))
            else:
                parts.append(text_from(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return text_from(value.get("text") or value.get("content") or value.get("message"))
    return str(value)


def time_text(context: dict[str, Any]) -> str:
    raw = context.get("timestamp") or context.get("created_at")
    if raw:
        try:
            return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
        except ValueError:
            pass
    return dt.datetime.now().strftime("%H:%M")


def now_arg(context: dict[str, Any]) -> str | None:
    raw = context.get("timestamp") or context.get("created_at")
    return str(raw) if raw else None


def read_session_pair(session_id: str | None) -> tuple[str, str]:
    if not session_id:
        return "", ""
    data_root = os.environ.get("HERMES_DATA_DIR")
    env_session_dir = os.environ.get("HERMES_SESSION_DIR")
    if env_session_dir:
        session_dir = Path(env_session_dir).expanduser()
    else:
        session_dir = Path(data_root) / "sessions" if data_root else Path()
    session_file = session_dir / f"{session_id}.jsonl"
    if not session_file.exists():
        return "", ""
    user = ""
    assistant = ""
    try:
        lines = session_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", ""
    for line in reversed(lines[-20:]):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = item.get("role")
        if role == "assistant" and not assistant:
            assistant = text_from(item.get("content"))
        elif role == "user" and not user:
            user = text_from(item.get("content"))
        if user and assistant:
            break
    return user, assistant


def run_chatdiary(context: dict[str, Any]) -> dict[str, Any]:
    config = local_config()
    session_id = str(context.get("session_id") or "")
    user, reply = read_session_pair(session_id)
    if not user:
        user = text_from(context.get("message") or context.get("prompt"))
    if not reply:
        reply = text_from(context.get("response") or context.get("reply") or context.get("last_assistant_message"))
    digest = hashlib.sha256(f"hermes\0{session_id}\0{user}\0{reply}".encode("utf-8")).hexdigest()[:24]
    cmd = [
        sys.executable,
        str(chatdiary_script()),
        "handle-turn",
        "--time",
        time_text(context),
        "--text",
        user,
        "--reply",
        reply,
        "--source",
        "hermes-hook",
        "--turn-id",
        f"hermes-{digest}",
    ]
    raw_now = now_arg(context)
    if raw_now:
        cmd.extend(["--now", raw_now])
    env = os.environ.copy()
    if config.get("config_file"):
        env["CHATDIARY_CONFIG_FILE"] = str(config["config_file"])
    if config.get("adapter_state_dir"):
        env["CHATDIARY_ADAPTER_STATE_DIR"] = str(config["adapter_state_dir"])
    result = subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return json.loads(result.stdout)


def handle(event: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if event != "agent:end":
        return None
    return run_chatdiary(context)


if __name__ == "__main__":
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("event", "agent:end")
    context = payload.get("context", payload)
    print(json.dumps(handle(event, context), ensure_ascii=False, indent=2))
