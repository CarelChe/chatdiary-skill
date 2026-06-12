#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

START_TRIGGERS = ("讲故事", "开始讲故事", "开启日记", "记日记", "写日记")
END_TRIGGERS = ("不讲了", "停止讲故事", "关闭日记")
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"
# 话题数量策略：默认1个，用户明确要求时才扩展，最多不超过3个
TOPIC_LIMIT = 3
TOPIC_DEFAULT = 1
TOPIC_LINE_LIMIT = 18
DEFAULT_IDLE_TIMEOUT_MINUTES = 10
TRUSTED_REPLY_SOURCES = {"hermes-hook", "claude-code-hook", "openclaw-hook", "test"}
USER_CONFIG_FILENAME = "chatdiary.config.json"


@dataclass
class Paths:
    script_path: Path
    workspace_root: Path
    skill_root: Path
    config_file: Path
    tmp_dir: Path
    diary_dir: Path | None
    attachment_dir: Path
    state_file: Path
    adapter_state_dir: Path
    user_label: str
    idle_timeout_minutes: int


def read_config(config_file: Path) -> dict:
    if not config_file.exists():
        return {}
    content = config_file.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid ChatDiary config file: {config_file}") from exc


def write_config(config_file: Path, config: dict) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config_file.with_suffix(".tmp")
    temp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(config_file)


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    return json.loads(content)


def write_json_file(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def configured_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith("/path/to/"):
        return None
    return text


def shell_command(parts: list[str], env: dict[str, str] | None = None) -> str:
    prefix = ""
    if env:
        prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items()) + " "
    return prefix + " ".join(shlex.quote(part) for part in parts)


def resolve_paths() -> Paths:
    script_path = Path(__file__).resolve()
    skill_root = script_path.parents[1]
    runtime_root = skill_root / ".chatdiary"
    user_config_file = skill_root / USER_CONFIG_FILENAME
    legacy_runtime_config_file = runtime_root / "config.json"
    if ".hermes" in script_path.parts:
        workspace_root = Path.home()
    elif ".github" in script_path.parts:
        workspace_root = skill_root.parents[3]
    else:
        workspace_root = skill_root.parents[3]
    explicit_config_file = os.environ.get("CHATDIARY_CONFIG_FILE")
    if explicit_config_file:
        config_file = Path(explicit_config_file).expanduser()
    elif user_config_file.exists():
        config_file = user_config_file
    else:
        config_file = legacy_runtime_config_file
    config = read_config(config_file)
    diary_root_text = configured_text(os.environ.get("CHATDIARY_OBSIDIAN_DAILY_DIR")) or configured_text(config.get("diary_dir"))
    diary_root = Path(diary_root_text).expanduser() if diary_root_text else None
    user_label = configured_text(os.environ.get("CHATDIARY_USER_LABEL")) or configured_text(config.get("user_label")) or "User"
    state_file_text = configured_text(os.environ.get("CHATDIARY_STATE_FILE")) or configured_text(config.get("state_file"))
    tmp_dir_text = configured_text(os.environ.get("CHATDIARY_TMP_DIR")) or configured_text(config.get("tmp_dir"))
    adapter_state_text = configured_text(os.environ.get("CHATDIARY_ADAPTER_STATE_DIR")) or configured_text(config.get("adapter_state_dir"))
    idle_timeout_text = configured_text(os.environ.get("CHATDIARY_IDLE_TIMEOUT_MINUTES")) or configured_text(config.get("idle_timeout_minutes"))
    try:
        idle_timeout_minutes = int(idle_timeout_text) if idle_timeout_text is not None else DEFAULT_IDLE_TIMEOUT_MINUTES
    except (TypeError, ValueError):
        idle_timeout_minutes = DEFAULT_IDLE_TIMEOUT_MINUTES
    return Paths(
        script_path=script_path,
        workspace_root=workspace_root,
        skill_root=skill_root,
        config_file=config_file,
        tmp_dir=Path(tmp_dir_text).expanduser() if tmp_dir_text else runtime_root / "tmp",
        diary_dir=diary_root,
        attachment_dir=diary_root / "附件" if diary_root else Path(),
        state_file=Path(state_file_text).expanduser()
        if state_file_text
        else runtime_root / "state.json",
        adapter_state_dir=Path(adapter_state_text).expanduser()
        if adapter_state_text
        else runtime_root / "adapters",
        user_label=user_label,
        idle_timeout_minutes=max(0, idle_timeout_minutes),
    )


def require_diary_dir(paths: Paths) -> Path:
    if paths.diary_dir is None:
        raise SystemExit(
            f"ChatDiary is not configured. Edit {USER_CONFIG_FILENAME}, set diary_dir, "
            "then run: python3 scripts/chatdiary.py setup"
        )
    return paths.diary_dir


def detect_agents() -> list[str]:
    requested = os.environ.get("CHATDIARY_AGENT", "").strip().lower()
    if requested and requested not in {"auto", "detect"}:
        if requested == "all":
            return ["hermes", "claude-code", "openclaw"]
        aliases = {
            "claude": "claude-code",
            "claudecode": "claude-code",
            "open-claw": "openclaw",
        }
        return [aliases.get(item.strip(), item.strip()) for item in requested.split(",") if item.strip()]

    agents: list[str] = []
    if os.environ.get("HERMES_DATA_DIR") or os.environ.get("HERMES_HOME") or os.environ.get("CHATDIARY_HERMES_HOOKS_DIR") or os.environ.get("CHATDIARY_HERMES_HOOK_DIR"):
        agents.append("hermes")
    elif (Path.home() / ".hermes" / "hooks").exists():
        agents.append("hermes")
    if os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CHATDIARY_CLAUDE_SETTINGS_FILE") or (Path.home() / ".claude").exists():
        agents.append("claude-code")
    if os.environ.get("OPENCLAW_CONFIG_DIR") or os.environ.get("OPENCLAW_HOME") or os.environ.get("CHATDIARY_OPENCLAW_HOOKS_FILE") or (Path.home() / ".openclaw").exists():
        agents.append("openclaw")
    return agents


def hermes_hook_dir() -> Path | None:
    exact = os.environ.get("CHATDIARY_HERMES_HOOK_DIR")
    if exact:
        return Path(exact).expanduser()
    hooks_root = os.environ.get("CHATDIARY_HERMES_HOOKS_DIR")
    if hooks_root:
        return Path(hooks_root).expanduser() / "chatdiary-auto-log"
    data_root = os.environ.get("HERMES_DATA_DIR")
    if data_root:
        return Path(data_root).expanduser() / "hooks" / "chatdiary-auto-log"
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home).expanduser() / "hooks" / "chatdiary-auto-log"
    default_hooks = Path.home() / ".hermes" / "hooks"
    if default_hooks.exists() or (Path.home() / ".hermes").exists():
        return default_hooks / "chatdiary-auto-log"
    return None


def install_hermes_hook(paths: Paths) -> dict:
    target = hermes_hook_dir()
    if target is None:
        return {"agent": "hermes", "installed": False, "reason": "Hermes hook directory not found"}
    source_dir = paths.skill_root / "adapters" / "hermes"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dir / "HOOK.yaml", target / "HOOK.yaml")
    shutil.copy2(source_dir / "handler.py", target / "handler.py")
    write_json_file(
        target / "chatdiary_adapter_config.json",
        {
            "skill_root": str(paths.skill_root),
            "script": str(paths.script_path),
            "config_file": str(paths.config_file),
            "adapter_state_dir": str(paths.adapter_state_dir / "hermes"),
        },
    )
    return {"agent": "hermes", "installed": True, "path": str(target)}


def claude_settings_file() -> Path:
    explicit = os.environ.get("CHATDIARY_CLAUDE_SETTINGS_FILE") or os.environ.get("CLAUDE_CODE_SETTINGS_FILE")
    if explicit:
        return Path(explicit).expanduser()
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser() / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def merge_claude_hook(settings: dict, event: str, command: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault(event, [])
    for entry in entries:
        for hook in entry.get("hooks", []):
            if hook.get("command") == command:
                return settings
    entries.append({"matcher": "", "hooks": [{"type": "command", "command": command}]})
    return settings


def install_claude_hook(paths: Paths) -> dict:
    settings_file = claude_settings_file()
    settings = read_json_file(settings_file)
    env = {
        "CHATDIARY_SKILL_DIR": str(paths.skill_root),
        "CHATDIARY_CONFIG_FILE": str(paths.config_file),
        "CHATDIARY_ADAPTER_STATE_DIR": str(paths.adapter_state_dir / "claude-code"),
    }
    user_cmd = shell_command([sys.executable, str(paths.skill_root / "adapters" / "claude-code" / "user_prompt_submit.py")], env)
    stop_cmd = shell_command([sys.executable, str(paths.skill_root / "adapters" / "claude-code" / "stop.py")], env)
    merge_claude_hook(settings, "UserPromptSubmit", user_cmd)
    merge_claude_hook(settings, "Stop", stop_cmd)
    write_json_file(settings_file, settings)
    return {"agent": "claude-code", "installed": True, "path": str(settings_file)}


def openclaw_hooks_file() -> Path:
    explicit = os.environ.get("CHATDIARY_OPENCLAW_HOOKS_FILE") or os.environ.get("OPENCLAW_HOOKS_FILE")
    if explicit:
        return Path(explicit).expanduser()
    config_dir = os.environ.get("OPENCLAW_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser() / "hooks.json"
    home = os.environ.get("OPENCLAW_HOME")
    if home:
        return Path(home).expanduser() / "hooks.json"
    return Path.home() / ".openclaw" / "hooks.json"


def merge_openclaw_hook(settings: dict, event: str, command: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault(event, [])
    for entry in entries:
        if entry.get("command") == command:
            return settings
    entries.append({"command": command})
    return settings


def install_openclaw_hook(paths: Paths) -> dict:
    hooks_file = openclaw_hooks_file()
    settings = read_json_file(hooks_file)
    env = {
        "CHATDIARY_SKILL_DIR": str(paths.skill_root),
        "CHATDIARY_CONFIG_FILE": str(paths.config_file),
        "CHATDIARY_ADAPTER_STATE_DIR": str(paths.adapter_state_dir / "openclaw"),
    }
    received_cmd = shell_command([sys.executable, str(paths.skill_root / "adapters" / "openclaw" / "message_received.py")], env)
    sent_cmd = shell_command([sys.executable, str(paths.skill_root / "adapters" / "openclaw" / "message_sent.py")], env)
    merge_openclaw_hook(settings, "message:received", received_cmd)
    merge_openclaw_hook(settings, "message:sent", sent_cmd)
    write_json_file(hooks_file, settings)
    return {"agent": "openclaw", "installed": True, "path": str(hooks_file)}


def install_hooks(paths: Paths, requested_agent: str = "auto") -> list[dict]:
    if requested_agent == "all":
        agents = ["hermes", "claude-code", "openclaw"]
    elif requested_agent in {"auto", "detect"}:
        if ".hermes" in paths.skill_root.parts and "skills" in paths.skill_root.parts:
            agents = ["hermes"]
        else:
            agents = detect_agents()
    else:
        agents = detect_agents() if requested_agent == "" else [requested_agent]
    results: list[dict] = []
    for agent in agents:
        if agent == "hermes":
            results.append(install_hermes_hook(paths))
        elif agent == "claude-code":
            results.append(install_claude_hook(paths))
        elif agent == "openclaw":
            results.append(install_openclaw_hook(paths))
        else:
            results.append({"agent": agent, "installed": False, "reason": "unknown agent"})
    if not results:
        results.append({"agent": "auto", "installed": False, "reason": "no supported agent detected"})
    return results


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def format_date(value: dt.date) -> str:
    return value.strftime(DATE_FORMAT)


def format_time(value: dt.datetime | dt.time) -> str:
    if isinstance(value, dt.datetime):
        return value.strftime(TIME_FORMAT)
    return value.strftime(TIME_FORMAT)


def now_date_and_time(date_text: str | None, time_text: str | None) -> tuple[dt.date, str]:
    today = parse_date(date_text) if date_text else dt.date.today()
    current_time = time_text or dt.datetime.now().strftime(TIME_FORMAT)
    return today, current_time


def now_datetime(now_text: str | None = None) -> dt.datetime:
    if now_text:
        value = dt.datetime.fromisoformat(now_text)
        if value.tzinfo is None:
            return value.astimezone()
        return value
    return dt.datetime.now().astimezone()


def format_datetime(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.isoformat(timespec="seconds")


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def default_state() -> dict:
    return {
        "recording": False,
        "date": None,
        "tmp_file": None,
        "topics": [],
        "attachments": 0,
        "last_activity_at": None,
        "idle_deadline_at": None,
        "idle_timeout_minutes": DEFAULT_IDLE_TIMEOUT_MINUTES,
        "idle_token": None,
        "turn_ids": [],
    }


def read_state(paths: Paths) -> dict:
    if not paths.state_file.exists():
        state = default_state()
    else:
        state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    merged = default_state()
    merged.update(state)
    return merged


def write_state(paths: Paths, state: dict) -> None:
    paths.state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = paths.state_file.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(paths.state_file)


def arm_idle_timer(paths: Paths, state: dict) -> None:
    if os.environ.get("CHATDIARY_DISABLE_TIMEOUT_ARM") == "1":
        return
    if not state.get("recording"):
        return
    token = state.get("idle_token")
    deadline = state.get("idle_deadline_at")
    timeout_minutes = int(state.get("idle_timeout_minutes") or 0)
    if not token or not deadline or timeout_minutes <= 0:
        return
    env = os.environ.copy()
    env["CHATDIARY_CONFIG_FILE"] = str(paths.config_file)
    subprocess.Popen(
        [sys.executable, str(paths.script_path), "timeout-check", "--token", token],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )


def touch_activity(paths: Paths, state: dict, now_text: str | None = None, arm_timer: bool = True) -> dict:
    current = now_datetime(now_text)
    timeout_minutes = int(state.get("idle_timeout_minutes") or paths.idle_timeout_minutes)
    state["last_activity_at"] = format_datetime(current)
    state["idle_timeout_minutes"] = timeout_minutes
    if timeout_minutes > 0:
        state["idle_deadline_at"] = format_datetime(current + dt.timedelta(minutes=timeout_minutes))
        state["idle_token"] = uuid.uuid4().hex
    else:
        state["idle_deadline_at"] = None
        state["idle_token"] = None
    write_state(paths, state)
    if arm_timer:
        arm_idle_timer(paths, state)
    return state


def ensure_dirs(paths: Paths) -> None:
    paths.tmp_dir.mkdir(parents=True, exist_ok=True)
    require_diary_dir(paths).mkdir(parents=True, exist_ok=True)
    paths.attachment_dir.mkdir(parents=True, exist_ok=True)


def diary_path(paths: Paths, date_value: dt.date) -> Path:
    return require_diary_dir(paths) / f"{format_date(date_value)}.md"


def tmp_path(paths: Paths, date_value: dt.date, time_text: str) -> Path:
    compact = time_text.replace(":", "")
    return paths.tmp_dir / f"{format_date(date_value)}-{compact}.txt"


def weekly_cleanup(paths: Paths, today: dt.date) -> list[str]:
    removed: list[str] = []
    cutoff = today - dt.timedelta(days=7)
    if not paths.tmp_dir.exists():
        return removed
    for tmp_file in paths.tmp_dir.glob("*.txt"):
        try:
            match = re.match(r"^(\d{4}-\d{2}-\d{2})-\d{4}$", tmp_file.stem)
            if not match:
                continue
            file_date = parse_date(match.group(1))
        except ValueError:
            continue
        if file_date <= cutoff:
            tmp_file.unlink(missing_ok=True)
            removed.append(str(tmp_file))
    return removed


def weekday_cn(date_value: dt.date) -> str:
    names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return names[date_value.weekday()]


def week_label(date_value: dt.date) -> str:
    iso_year, iso_week, _ = date_value.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def diary_frontmatter(date_value: dt.date) -> str:
    return (
        "---\n"
        f"date: {format_date(date_value)}\n"
        f"week: {week_label(date_value)}\n"
        f"weekday: {weekday_cn(date_value)}\n"
        "tags:\n"
        "  - 日记\n"
        "---\n\n"
    )


def diary_template(date_value: dt.date) -> str:
    return (
        diary_frontmatter(date_value)
        + "# 话题\n\n"
        + "# 对话记录\n\n"
        + "## 附件\n"
    )


def ensure_diary_file(paths: Paths, date_value: dt.date) -> Path:
    target = diary_path(paths, date_value)
    if not target.exists():
        target.write_text(diary_template(date_value), encoding="utf-8")
        return target
    text = target.read_text(encoding="utf-8")
    changed = False
    if "# 话题" not in text:
        text = text + ("\n" if not text.endswith("\n") else "") + "# 话题\n\n"
        changed = True
    if "# 对话记录" not in text:
        text = text + ("\n" if not text.endswith("\n") else "") + "# 对话记录\n\n"
        changed = True
    if "## 附件" not in text:
        text = text.rstrip() + "\n\n## 附件\n"
        changed = True
    if changed:
        target.write_text(text, encoding="utf-8")
    return target


def split_trigger_prefix(text: str) -> str:
    cleaned = text
    for trigger in START_TRIGGERS:
        if cleaned.startswith(trigger):
            cleaned = cleaned[len(trigger):]
            cleaned = re.sub(r"^[\s，,。.!！？、:：;；-]+", "", cleaned)
            return cleaned
    return cleaned


def split_trigger_suffix(text: str) -> str:
    cleaned = text
    for trigger in END_TRIGGERS:
        escaped = re.escape(trigger)
        match = re.match(rf"^(.*?)[\s，,、;；:：-]*{escaped}[\s，,。.!！？、:：;；-]*$", cleaned)
        if match:
            return match.group(1)
    return cleaned


def analyze_message(text: str) -> dict:
    starts = any(text.startswith(trigger) for trigger in START_TRIGGERS)
    ends = any(text.endswith(trigger) for trigger in END_TRIGGERS)
    cleaned = split_trigger_suffix(split_trigger_prefix(text))
    return {
        "raw_text": text,
        "normalized_text": cleaned,
        "starts_recording": starts,
        "ends_recording": ends,
        "start_trigger": next((trigger for trigger in START_TRIGGERS if text.startswith(trigger)), None),
        "end_trigger": next((trigger for trigger in END_TRIGGERS if text.endswith(trigger)), None),
    }


def parse_tmp_lines(lines: Iterable[str]) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    for line in lines:
        stripped = line.rstrip("\n")
        if not stripped:
            continue
        # 格式1: HH:MM U: content
        match = re.match(r"^(\d{2}:\d{2}) ([UA]): (.*)$", stripped)
        if match:
            items.append((match.group(1), match.group(2), match.group(3)))
            continue
        # 格式2: 钩子旧格式 - **HH:MM User/AI：content**（兼容已存 tmp）
        match2 = re.match(r"^- \*\*(\d{2}:\d{2}) ([^：:]+)[：:] (.+?)\*\*$", stripped)
        if match2:
            speaker = "A" if match2.group(2) == "AI" else "U"
            items.append((match2.group(1), speaker, match2.group(3)))
            continue
        # 格式3: 钩子旧格式 AI（无末尾 **）
        match3 = re.match(r"^- \*\*(\d{2}:\d{2}) (AI)[：:] (.+)$", stripped)
        if match3:
            items.append((match3.group(1), "A", match3.group(3)))
    return items


def filter_trigger_pairs(items: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """
    过滤触发词对话对。
    
    规则：
    1. U 消息是纯开始触发词（如单独一句"开启日记"）：删除本条 U 及紧随的 A
    2. U 消息以开始触发词开头：删除触发词及紧跟的标点/空格，保留
    3. U 消息是纯结束触发词（如单独一句"关闭日记"）：删除本条 U 及紧随的 A
    4. U 消息以结束触发词结尾：删除触发词及前面的标点/空格，保留
    """
    filtered: list[tuple[str, str, str]] = []
    skip_next_a = False

    for time, speaker, content in items:
        if speaker == "U":
            stripped = content.strip()

            # 规则1: 纯开始触发词
            if stripped in START_TRIGGERS:
                skip_next_a = True
                continue

            # 规则3: 纯结束触发词
            if stripped in END_TRIGGERS:
                skip_next_a = True
                continue

            # 规则2: 以开始触发词开头 → 去掉
            clean = content
            for trigger in START_TRIGGERS:
                if clean.startswith(trigger):
                    clean = clean[len(trigger):]
                    clean = re.sub(r"^[\s，,。.!！？、:：;；-]+", "", clean)
                    break

            # 规则4: 以结束触发词结尾 → 去掉
            for trigger in END_TRIGGERS:
                escaped = re.escape(trigger)
                match = re.match(rf"^(.*?)[\s，,、;；:：-]*{escaped}[^\w]*$", clean)
                if match:
                    clean = match.group(1)
                    break

            filtered.append((time, "U", clean))
            skip_next_a = False
        else:
            if not skip_next_a:
                # 只保留有对应 U 的 A 条目（过滤孤立 A——如 finalize 的关闭语）
                # 改为判断 filtered 中是否至少有一条 U，而非仅检查最后一条
                if filtered and any(s == "U" for _, s, _ in filtered):
                    filtered.append((time, "A", content))
            skip_next_a = False

    return filtered


def format_conversation_lines(items: list[tuple[str, str, str]], user_label: str) -> list[str]:
    formatted: list[str] = []
    prev_speaker = None
    for time_text, speaker, content in items:
        # 将转义的 \n 转换为真实换行再分割
        paragraphs = content.replace("\\n", "\n").split("\n")
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # 上一条是 AI，当前是用户 → 插入空行分隔
            if prev_speaker == "A" and speaker == "U":
                formatted.append("")
            if speaker == "U":
                formatted.append(f"- **{time_text} {user_label}：{para}**")
            else:
                formatted.append(f"- **{time_text} AI：** {para}")
            prev_speaker = speaker
    return formatted


def read_diary_sections(path: Path) -> tuple[list[str], list[str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    attachment_index = next((index for index, line in enumerate(lines) if line.strip() == "## 附件"), len(lines))
    topic_index = next((index for index, line in enumerate(lines) if line.strip() == "# 话题"), -1)
    record_index = next((index for index, line in enumerate(lines) if line.strip() == "# 对话记录"), -1)
    if topic_index == -1 or record_index == -1:
        return lines, [], []
    header_end = attachment_index if attachment_index != len(lines) else len(lines)
    return lines[:header_end], lines[header_end:attachment_index], lines[attachment_index:]


def diary_has_transcript(lines: list[str]) -> bool:
    return any(line.startswith("- **") for line in lines)


def append_transcript(paths: Paths, date_value: dt.date, items: list[tuple[str, str, str]]) -> Path:
    diary = ensure_diary_file(paths, date_value)
    all_lines = diary.read_text(encoding="utf-8").splitlines()
    conversation_lines = format_conversation_lines(items, paths.user_label)
    if not conversation_lines:
        return diary
    # 找到对话记录区块的结束位置：最后一个 "----" 之后，或 ## 附件之前
    # 优先找最后一个 ----，这是上一条记录的结尾
    last_sep = -1
    for i in range(len(all_lines) - 1, -1, -1):
        if all_lines[i].strip() == "----":
            last_sep = i
            break
    if last_sep >= 0:
        insert_at = last_sep + 1
    else:
        # 没有分隔线，在 ## 附件前插入
        attachment_index = next((index for index, line in enumerate(all_lines) if line.strip() == "## 附件"), len(all_lines))
        insert_at = attachment_index
    # 在新记录前加空行（如果上一行不是空行）
    while insert_at < len(all_lines) and all_lines[insert_at].strip() == "":
        insert_at += 1
    if insert_at > 0 and all_lines[insert_at - 1].strip():
        all_lines.insert(insert_at, "")
        insert_at += 1
    # 插入新记录
    for line in conversation_lines:
        all_lines.insert(insert_at, line)
        insert_at += 1
    # 插入分隔线
    all_lines.insert(insert_at, "----")
    diary.write_text("\n".join(all_lines).rstrip() + "\n", encoding="utf-8")
    return diary


def normalize_topic_candidate(text: str) -> str:
    candidate = re.sub(r"\s+", "", text)
    candidate = re.sub(
        r"^(?:五一好像有个什么|好像有个什么|有个什么|有个|今天下午|今天晚上|今天上午|今天中午|昨天晚上|昨天上午|昨天中午|今天|昨天|刚才|然后|其实|就是|感觉|比较|还是|有点|一个|一些|那边|这边|这里|那里|我到的还是比较早的|我到的还是比较晚的|我|我们|你|他|她|它|都|也|就|从|在|到|去|和|跟|与|相比于)+",
        "",
        candidate,
    )
    candidate = re.sub(
        r"(?:五一好像有个什么|好像有个什么|有个什么|有个|转了一圈|逛了一圈|走了一圈|玩了一圈|看了一圈|聊了一会儿|聊了一会|待了一会儿|待了一会|待了一阵|回到家|回家|到家|在一起舒服|在一起|的时间来看|的时间|的地方|的生活|的夜生活的地方|的夜生活|比较早的|比较晚的|比较早|比较晚|了|过|着|呢|吧|啊|呀|嘛|吗)+$",
        "",
        candidate,
    )
    candidate = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", candidate)
    return candidate[:TOPIC_LINE_LIMIT]


def infer_topics_from_transcript(transcript: list[tuple[str, str, str]]) -> list[str]:
    transcript_text = "\n".join(content for _, speaker, content in transcript if speaker == "U")
    raw_candidates: list[str] = []
    for _, speaker, content in transcript:
        if speaker != "U":
            continue
        for clause in re.split(r"[，,。.!！？、;；\n]+", content):
            clause = clause.strip()
            if not clause:
                continue
            raw_candidates.append(clause)
            for keyword in ("从", "去", "到", "在", "和", "跟", "与", "相比于"):
                for match in re.finditer(rf"{keyword}([^，,。.!！？、;；\n]{{1,24}})", clause):
                    raw_candidates.append(match.group(1))

    normalized_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        cleaned = normalize_topic_candidate(candidate)
        if not cleaned:
            continue
        normalized = re.sub(r"\s+", "", cleaned)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_candidates.append(cleaned)

    merged_candidates = dedupe_topics_semantically([], normalized_candidates)
    if not merged_candidates:
        return []
    limit = topics_should_expand(merged_candidates, transcript_text)
    if limit <= 0:
        limit = min(len(merged_candidates), TOPIC_LIMIT)
    return extract_topics_value(merged_candidates[:limit])


def extract_topics_value(raw_topics: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for topic in raw_topics:
        cleaned = topic.strip()
        if not cleaned:
            continue
        normalized = re.sub(r"\s+", "", cleaned)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned[:TOPIC_LINE_LIMIT])
        if len(deduped) >= TOPIC_LIMIT:
            break
    return deduped


def topics_should_expand(raw_topics: list[str], transcript_text: str = "") -> int:
    """决定本轮对话提取多少个话题。
    默认只提取 1 个——除非用户明确要求多个（如"还有一件""再说一件""两件事"等），
    才扩展为 2 个或 3 个。最多不超过 TOPIC_LIMIT（3个）。
    """
    if not raw_topics:
        return 0
    candidates = [t.strip() for t in raw_topics if t.strip()]
    if len(candidates) == 1:
        return 1

    text = transcript_text or ""
    wants_three = bool(re.search(r"(?:第三个|第三件|第三点|第三条|三件事|三件事情|三个话题|三点|总结三个)", text))
    wants_two = bool(
        re.search(
            r"(?:还有一件|还有一个|还有一点|还有一条|另外一件|另外一个|再说一件|再补充一件|再讲一件|第二个|第二件|第二点|第二条|两件事|两件事情|两个话题|两点|另一件|另一个话题)",
            text,
        )
    )

    if wants_three:
        return min(3, len(candidates), TOPIC_LIMIT)
    if wants_two:
        return min(2, len(candidates), TOPIC_LIMIT)
    return 1


def dedupe_topics_semantically(existing: list[str], new_topics: list[str]) -> list[str]:
    """
    Compare new topics with existing topics using Jaccard similarity.
    Only add new topics that are not semantically similar (> 0.6) to existing ones.
    Preserves order: existing topics first, then new non-duplicate topics.
    """
    def jaccard(a: str, b: str) -> float:
        sa = set(re.sub(r"\s+", "", a))
        sb = set(re.sub(r"\s+", "", b))
        if not sa or not sb:
            return 0.0
        inter = sa & sb
        uni = sa | sb
        return len(inter) / len(uni)
    
    merged = list(existing)  # Start with existing topics
    
    for new_topic in new_topics:
        new_clean = new_topic.strip()
        if not new_clean:
            continue
        
        # Check if semantically similar to any existing topic (threshold 0.4)
        is_duplicate = False
        for existing_topic in merged:
            if jaccard(new_clean.lower(), existing_topic.lower()) > 0.4:
                is_duplicate = True
                break
        
        # If not a duplicate, add it (truncate to TOPIC_LINE_LIMIT)
        if not is_duplicate:
            merged.append(new_clean[:TOPIC_LINE_LIMIT])
    
    return merged


def write_topics(paths: Paths, date_value: dt.date, topics: list[str]) -> Path:
    diary = ensure_diary_file(paths, date_value)
    content = diary.read_text(encoding="utf-8")
    topic_match = re.search(r"(?ms)^# 话题\n(.*?)(?=^# 对话记录|\Z)", content)
    if not topic_match:
        raise SystemExit("diary file missing # 话题 section")
    
    # Extract existing topics from diary
    existing_block = topic_match.group(1).strip()
    existing_topics = [line.strip("- ").strip() for line in existing_block.split("\n") if line.strip().startswith("-")]
    
    # Merge incoming topics with existing ones (Hermes agent should pre-dedupe; script just appends)
    merged_topics = existing_topics + [t.strip() for t in topics if t.strip()]
    # Remove duplicates while preserving order, cap at TOPIC_LIMIT (3)
    seen = set()
    unique_topics = []
    for topic in merged_topics:
        if topic not in seen:
            seen.add(topic)
            unique_topics.append(topic[:TOPIC_LINE_LIMIT])
            if len(unique_topics) >= TOPIC_LIMIT:
                break
    
    # Build new topic block
    topic_block = "# 话题\n"
    if unique_topics:
        topic_block += "".join(f"- {topic}\n" for topic in unique_topics)
    topic_block += "\n"
    start, end = topic_match.span()
    content = content[:start] + topic_block + content[end:]
    diary.write_text(content, encoding="utf-8")
    return diary


def append_attachment(paths: Paths, date_value: dt.date, source: Path) -> dict:
    ensure_dirs(paths)
    ensure_diary_file(paths, date_value)
    existing = sorted(paths.attachment_dir.glob(f"{format_date(date_value)}-*"))
    existing = [path for path in existing if path.is_file()]
    sequence = len(existing) + 1
    target_name = f"{format_date(date_value)}-{sequence}{source.suffix.lower()}"
    target = paths.attachment_dir / target_name
    shutil.copy2(source, target)
    diary = diary_path(paths, date_value)
    embed_line = f"![[附件/{target.name}]]"
    content_lines = diary.read_text(encoding="utf-8").splitlines()
    marker_index = next((index for index, line in enumerate(content_lines) if line.strip() == "## 附件"), len(content_lines))
    head = content_lines[:marker_index + 1]
    tail = content_lines[marker_index + 1:]
    if embed_line not in tail:
        # Remove trailing blank lines before appending new embed
        while tail and not tail[-1].strip():
            tail.pop()
        tail.append(embed_line)
        diary.write_text("\n".join(head + tail).rstrip() + "\n", encoding="utf-8")
    return {"copied": str(target), "embed": embed_line, "sequence": sequence}


def load_tmp_transcript(paths: Paths, tmp_file: Path) -> list[tuple[str, str, str]]:
    if not tmp_file.exists():
        raise SystemExit(f"tmp file not found: {tmp_file}")
    return parse_tmp_lines(tmp_file.read_text(encoding="utf-8").splitlines())


def prepare_start(paths: Paths, date_value: dt.date, time_text: str) -> dict:
    ensure_dirs(paths)
    removed = weekly_cleanup(paths, date_value)
    diary = ensure_diary_file(paths, date_value)
    tmp_file = tmp_path(paths, date_value, time_text)
    if tmp_file.exists():
        tmp_file.unlink()
    tmp_file.write_text("", encoding="utf-8")
    state = {
        "recording": True,
        "date": format_date(date_value),
        "tmp_file": str(tmp_file),
        "topics": [],
        "attachments": 0,
        "last_activity_at": None,
        "idle_deadline_at": None,
        "idle_timeout_minutes": paths.idle_timeout_minutes,
        "idle_token": None,
        "turn_ids": [],
    }
    state = touch_activity(paths, state)
    return {
        "recording": True,
        "diary_file": str(diary),
        "tmp_file": str(tmp_file),
        "removed_tmp_files": removed,
        "idle_deadline_at": state.get("idle_deadline_at"),
        "idle_timeout_minutes": state.get("idle_timeout_minutes"),
    }


def run_start(paths: Paths, args: argparse.Namespace) -> None:
    date_value, time_text = now_date_and_time(args.date, args.time)
    state = read_state(paths)
    if state.get("recording"):
        print(json.dumps({"recording": True, "ignored": True, "state": state}, ensure_ascii=False, indent=2))
        return
    result = prepare_start(paths, date_value, time_text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_analyze(_: Paths, args: argparse.Namespace) -> None:
    result = analyze_message(args.text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def auto_attach(paths: Paths, date_value: dt.date, text: str) -> list[dict]:
    """从文本中提取 MEDIA: 路径并保存为附件。返回已保存文件的列表。"""
    results = []
    for source_path_str in re.findall(r"MEDIA:\s*/([^\s\]]+)", text):
        source = Path("/" + source_path_str)
        if source.exists():
            result = append_attachment(paths, date_value, source)
            results.append(result)
            # 更新附件计数
            state = read_state(paths)
            if state.get("recording"):
                state["attachments"] = int(state.get("attachments", 0)) + 1
                write_state(paths, state)
    return results


def make_turn_id(time_text: str, text: str, reply: str) -> str:
    digest = hashlib.sha256(f"{time_text}\0{text}\0{reply}".encode("utf-8")).hexdigest()
    return digest[:24]


def append_turn(
    paths: Paths,
    state: dict,
    time_text: str,
    text: str,
    reply: str,
    turn_id: str | None = None,
    now_text: str | None = None,
) -> dict:
    if not state.get("recording"):
        raise SystemExit("not recording")
    tmp_file = Path(state["tmp_file"])
    if not tmp_file.exists():
        raise SystemExit(f"tmp file not found: {tmp_file}")

    turn_id = turn_id or make_turn_id(time_text, text, reply)
    known_turns = list(state.get("turn_ids") or [])
    if turn_id in known_turns:
        return {"tmp_file": str(tmp_file), "turn_id": turn_id, "deduped": True, "written_lines": 0}

    existing_content = tmp_file.read_text(encoding="utf-8")
    written_lines = 0

    def write_lines(prefix: str, value: str) -> None:
        nonlocal existing_content, written_lines
        paragraphs = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        with tmp_file.open("a", encoding="utf-8") as handle:
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                line = f"{time_text} {prefix}: {para}"
                if line not in existing_content:
                    handle.write(f"{line}\n")
                    existing_content += f"{line}\n"
                    written_lines += 1

    if text:
        write_lines("U", text)
    if reply:
        write_lines("A", reply)

    known_turns.append(turn_id)
    state["turn_ids"] = known_turns[-200:]
    state = touch_activity(paths, state, now_text=now_text)
    return {"tmp_file": str(tmp_file), "turn_id": turn_id, "deduped": False, "written_lines": written_lines}


def run_append(paths: Paths, args: argparse.Namespace) -> None:
    date_value = parse_date(args.date)
    state = read_state(paths)
    normalized = split_trigger_suffix(split_trigger_prefix(args.text))
    append_result = append_turn(paths, state, args.time, normalized, args.reply)

    # Include full transcript in output so Hermes can read and extract topics
    state = read_state(paths)
    tmp_file = Path(state["tmp_file"])
    transcript = load_tmp_transcript(paths, tmp_file)
    transcript = filter_trigger_pairs(transcript)
    user_lines = [(t, c) for t, s, c in transcript if s == "U" and c.strip()]
    transcript_for_hermes = "\n".join(f"[{t}] {c}" for t, c in user_lines)
    print(json.dumps({
        "transcript": transcript_for_hermes,
        "user_turns": len(user_lines),
        "append": append_result,
    }, ensure_ascii=False, indent=2))


def read_topics_from_diary(diary: Path) -> list[str]:
    content = diary.read_text(encoding="utf-8")
    topic_match = re.search(r"(?ms)^# 话题\n(.*?)(?=^# 对话记录|\Z)", content)
    if not topic_match:
        return []
    existing_block = topic_match.group(1).strip()
    return [line.strip("- ").strip() for line in existing_block.split("\n") if line.strip().startswith("-")]


def close_recording(paths: Paths, date_value: dt.date, source: str, closing: str = "", auto_topics: bool = True) -> dict:
    state = read_state(paths)
    if not state.get("recording"):
        raise SystemExit("not recording")
    tmp_file = Path(state["tmp_file"])
    if not tmp_file.exists():
        raise SystemExit(f"tmp file not found: {tmp_file}")

    transcript = load_tmp_transcript(paths, tmp_file)
    transcript = filter_trigger_pairs(transcript)
    diary = append_transcript(paths, date_value, transcript)
    inferred_topics = infer_topics_from_transcript(transcript) if auto_topics else []
    if inferred_topics:
        write_topics(paths, date_value, inferred_topics)
    final_topics = read_topics_from_diary(diary)
    user_lines = [(t, c) for t, s, c in transcript if s == "U" and c.strip()]
    transcript_for_agent = "\n".join(f"[{t}] {c}" for t, c in user_lines)
    attachment_count = int(state.get("attachments", 0))
    write_state(
        paths,
        {
            **state,
            "recording": False,
            "date": format_date(date_value),
            "tmp_file": None,
            "topics": final_topics,
            "attachments": attachment_count,
            "last_activity_at": state.get("last_activity_at"),
            "idle_deadline_at": None,
            "idle_token": None,
        },
    )
    return {
        "closed": True,
        "source": source,
        "diary": str(diary),
        "transcript": transcript_for_agent,
        "user_turns": len(user_lines),
        "topics": final_topics,
        "inferred_topics": inferred_topics,
        "closing": closing,
        "attachments": attachment_count,
    }


def append_end_turn_if_needed(
    paths: Paths,
    state: dict,
    time_text: str,
    text: str,
    reply: str,
    turn_id: str | None,
    now_text: str | None,
) -> dict | None:
    cleaned = split_trigger_suffix(split_trigger_prefix(text)).strip()
    if not cleaned:
        return None
    return append_turn(paths, state, time_text, cleaned, reply, turn_id=turn_id, now_text=now_text)


def run_close(paths: Paths, args: argparse.Namespace) -> None:
    state = read_state(paths)
    if not state.get("recording"):
        raise SystemExit("not recording")
    date_value = parse_date(args.date) if args.date else parse_date(state["date"])
    append_result = None
    if args.text or args.reply:
        append_result = append_end_turn_if_needed(
            paths,
            state,
            args.time or dt.datetime.now().strftime(TIME_FORMAT),
            args.text or "",
            args.reply or "",
            args.turn_id,
            args.now,
        )
    result = close_recording(paths, date_value, source=args.source, closing=args.reply or "", auto_topics=not args.no_topics)
    if append_result:
        result["append"] = append_result
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_finalize(paths: Paths, args: argparse.Namespace) -> None:
    date_value = parse_date(args.date)
    state = read_state(paths)
    if not state.get("recording"):
        raise SystemExit("not recording")
    tmp_file = Path(state["tmp_file"])
    if not tmp_file.exists():
        raise SystemExit(f"tmp file not found: {tmp_file}")

    # 自动保存文本中的 MEDIA: 路径
    attachments_saved = auto_attach(paths, date_value, args.text)
    state = read_state(paths)

    # 读取并过滤 transcript
    transcript = load_tmp_transcript(paths, tmp_file)
    transcript = filter_trigger_pairs(transcript)
    diary = append_transcript(paths, date_value, transcript)

    # 关闭录制状态
    final_topics = [topic.strip() for topic in state.get("topics", []) if topic.strip()]
    attachment_count = int(state.get("attachments", 0))
    write_state(
        paths,
        {
            "recording": False,
            "date": format_date(date_value),
            "tmp_file": None,
            "topics": final_topics,
            "attachments": attachment_count,
        },
    )

    # 输出供 Hermes 读取
    user_lines = [(t, c) for t, s, c in transcript if s == "U" and c.strip()]
    transcript_for_hermes = "\n".join(f"[{t}] {c}" for t, c in user_lines)
    print(json.dumps({
        "diary": str(diary),
        "transcript": transcript_for_hermes,
        "user_turns": len(user_lines),
        "topics": final_topics,
        "closing": args.reply,
        "attachments": attachment_count,
    }, ensure_ascii=False, indent=2))


def run_handle_turn(paths: Paths, args: argparse.Namespace) -> None:
    text = args.text or ""
    reply = args.reply or ""
    source = args.source or "manual"
    time_text = args.time or dt.datetime.now().strftime(TIME_FORMAT)
    date_value = parse_date(args.date) if args.date else dt.date.today()
    analysis = analyze_message(text)
    starts = bool(analysis["starts_recording"])
    ends = bool(analysis["ends_recording"])
    state = read_state(paths)
    result: dict = {
        "recording_before": bool(state.get("recording")),
        "source": source,
        "starts_recording": starts,
        "ends_recording": ends,
        "ignored": False,
        "append": None,
        "close": None,
    }

    if starts and paths.diary_dir is None:
        result["ignored"] = True
        result["setup_required"] = True
        result["reason"] = "diary directory is not configured"
        result["setup_command"] = f"Edit {USER_CONFIG_FILENAME}, set diary_dir, then run: python3 scripts/chatdiary.py setup"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if source not in TRUSTED_REPLY_SOURCES and not args.allow_manual_reply:
        result["ignored"] = True
        result["manual_turn_rejected"] = True
        result["manual_reply_rejected"] = bool(reply)
        result["reason"] = (
            "handle-turn is reserved for platform hook adapters. "
            "Manual handle-turn calls are rejected to avoid recording text "
            "that was not actually delivered by the chat platform."
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if starts and not state.get("recording"):
        start_result = prepare_start(paths, date_value, time_text)
        result["start"] = start_result
        state = read_state(paths)

    if not state.get("recording"):
        result["ignored"] = True
        result["reason"] = "not recording and no start trigger"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    cleaned = split_trigger_suffix(split_trigger_prefix(text)).strip()
    if cleaned:
        result["append"] = append_turn(
            paths,
            state,
            time_text,
            cleaned,
            reply,
            turn_id=args.turn_id,
            now_text=args.now,
        )
        state = read_state(paths)
    elif starts:
        result["pure_start"] = True
    elif ends:
        result["pure_end"] = True
    elif not starts and not ends:
        result["append"] = append_turn(
            paths,
            state,
            time_text,
            text,
            reply,
            turn_id=args.turn_id,
            now_text=args.now,
        )
        state = read_state(paths)

    if ends:
        close_date = parse_date(state["date"]) if state.get("date") else date_value
        result["close"] = close_recording(paths, close_date, source="end-trigger", closing=reply)

    result["state"] = read_state(paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_attach(paths: Paths, args: argparse.Namespace) -> None:
    if args.date:
        date_value = parse_date(args.date)
    else:
        state = read_state(paths)
        if state.get("recording") and state.get("date"):
            date_value = parse_date(state["date"])
        else:
            date_value = dt.date.today()
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    result = append_attachment(paths, date_value, source)
    state = read_state(paths)
    if state.get("recording"):
        state["attachments"] = int(state.get("attachments", 0)) + 1
        touch_activity(paths, state, now_text=getattr(args, "now", None))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_set_topics(paths: Paths, args: argparse.Namespace) -> None:
    date_value = parse_date(args.date)
    raw_topics = [value for value in args.topics if value.strip()]
    # Pass all new topics to write_topics; it handles deduplication with existing topics
    diary = write_topics(paths, date_value, raw_topics)
    # Read final topic list from diary to get merged result
    content = diary.read_text(encoding="utf-8")
    topic_match = re.search(r"(?ms)^# 话题\n(.*?)(?=^# 对话记录|\Z)", content)
    if topic_match:
        existing_block = topic_match.group(1).strip()
        final_topics = [line.strip("- ").strip() for line in existing_block.split("\n") if line.strip().startswith("-")]
    else:
        final_topics = []
    state = read_state(paths)
    state["topics"] = final_topics
    write_state(paths, state)
    print(json.dumps({"diary_file": str(diary), "topics": final_topics}, ensure_ascii=False, indent=2))


def run_setup(paths: Paths, args: argparse.Namespace) -> None:
    config = read_config(paths.config_file)
    if not args.diary_dir and not configured_text(config.get("diary_dir")):
        raise SystemExit(
            f"setup requires diary_dir. Edit {paths.skill_root / USER_CONFIG_FILENAME} "
            'or pass --diary-dir "/path/to/Obsidian/Daily"'
        )
    runtime_root = paths.skill_root / ".chatdiary"
    if args.diary_dir:
        config["diary_dir"] = str(Path(args.diary_dir).expanduser())
    if args.user_label:
        config["user_label"] = args.user_label.strip() or "User"
    config["state_file"] = str(Path(args.state_file).expanduser()) if args.state_file else configured_text(config.get("state_file")) or str(runtime_root / "state.json")
    config["tmp_dir"] = str(Path(args.tmp_dir).expanduser()) if args.tmp_dir else configured_text(config.get("tmp_dir")) or str(runtime_root / "tmp")
    config["adapter_state_dir"] = configured_text(config.get("adapter_state_dir")) or str(runtime_root / "adapters")
    if args.idle_timeout_minutes is not None:
        config["idle_timeout_minutes"] = max(0, int(args.idle_timeout_minutes))
    if "user_label" not in config:
        config["user_label"] = "User"
    if "idle_timeout_minutes" not in config:
        config["idle_timeout_minutes"] = DEFAULT_IDLE_TIMEOUT_MINUTES
    if "agent" not in config:
        config["agent"] = "auto"
    write_config(paths.config_file, config)
    updated_paths = resolve_paths()
    updated_paths.tmp_dir.mkdir(parents=True, exist_ok=True)
    updated_paths.adapter_state_dir.mkdir(parents=True, exist_ok=True)
    hook_agent = args.agent or config.get("agent") or "auto"
    hook_results = [] if args.no_install_hooks else install_hooks(updated_paths, hook_agent)
    print(json.dumps({"config_file": str(paths.config_file), "config": config, "hooks": hook_results}, ensure_ascii=False, indent=2))


def run_status(paths: Paths, _: argparse.Namespace) -> None:
    config_exists = paths.config_file.exists()
    has_env_diary_dir = bool(os.environ.get("CHATDIARY_OBSIDIAN_DAILY_DIR"))
    config_source = "env" if has_env_diary_dir else ("config" if config_exists else "none")
    result = {
        "config_file": str(paths.config_file),
        "config_exists": config_exists,
        "configured": paths.diary_dir is not None,
        "setup_required": paths.diary_dir is None,
        "config_source": config_source,
        "diary_dir": str(paths.diary_dir) if paths.diary_dir else None,
        "tmp_dir": str(paths.tmp_dir),
        "user_label": paths.user_label,
        "idle_timeout_minutes": paths.idle_timeout_minutes,
        "state": read_state(paths),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def check_writable_dir(path: Path) -> tuple[bool, str | None]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".chatdiary-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, None
    except OSError as exc:
        return False, str(exc)


def run_doctor(paths: Paths, args: argparse.Namespace) -> None:
    checks = []

    def add(name: str, ok: bool, detail: str = "", fix: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "fix": fix})

    add("config_file", True, str(paths.config_file))
    add(
        "diary_dir_configured",
        paths.diary_dir is not None,
        str(paths.diary_dir) if paths.diary_dir else "",
        f"edit {USER_CONFIG_FILENAME}, set diary_dir, then run setup",
    )
    if paths.diary_dir:
        ok, detail = check_writable_dir(paths.diary_dir) if args.fix else (paths.diary_dir.exists() and os.access(paths.diary_dir, os.W_OK), "")
        add("diary_dir_writable", ok, str(paths.diary_dir) if not detail else detail)
    ok, detail = check_writable_dir(paths.tmp_dir) if args.fix else (paths.tmp_dir.exists() and os.access(paths.tmp_dir, os.W_OK), "")
    add("tmp_dir_writable", ok, str(paths.tmp_dir) if not detail else detail, "set --tmp-dir or create the directory")
    state = read_state(paths)
    add("state_readable", True, str(paths.state_file))
    add("user_label", bool(paths.user_label.strip()), paths.user_label, '--user-label "User"')
    add("idle_timeout", paths.idle_timeout_minutes >= 0, f"{paths.idle_timeout_minutes} minute(s)")
    add("script_exists", paths.script_path.exists(), str(paths.script_path))
    add("adapters_dir", (paths.skill_root / "adapters").exists(), str(paths.skill_root / "adapters"))
    ok, detail = check_writable_dir(paths.adapter_state_dir) if args.fix else (paths.adapter_state_dir.exists() and os.access(paths.adapter_state_dir, os.W_OK), "")
    add("adapter_state_dir", ok, str(paths.adapter_state_dir) if not detail else detail)
    detected = detect_agents()
    add("detected_agents", True, ",".join(detected) if detected else "none")
    if args.fix:
        hook_results = install_hooks(paths, args.agent)
    else:
        hook_results = []
    add("recording_state", True, f"recording={bool(state.get('recording'))}, deadline={state.get('idle_deadline_at')}")
    ok = all(item["ok"] for item in checks)
    print(json.dumps({"ok": ok, "checks": checks, "hooks": hook_results}, ensure_ascii=False, indent=2))


def run_timeout_check(paths: Paths, args: argparse.Namespace) -> None:
    state = read_state(paths)
    if not state.get("recording"):
        print(json.dumps({"closed": False, "reason": "not recording"}, ensure_ascii=False, indent=2))
        return
    if args.token and state.get("idle_token") != args.token:
        print(json.dumps({"closed": False, "reason": "stale token"}, ensure_ascii=False, indent=2))
        return
    deadline = parse_datetime(state.get("idle_deadline_at"))
    if not deadline:
        print(json.dumps({"closed": False, "reason": "no deadline"}, ensure_ascii=False, indent=2))
        return
    if not args.no_sleep:
        seconds = (deadline - now_datetime()).total_seconds()
        if seconds > 0:
            time.sleep(seconds)
        state = read_state(paths)
        if not state.get("recording"):
            print(json.dumps({"closed": False, "reason": "not recording after sleep"}, ensure_ascii=False, indent=2))
            return
        if args.token and state.get("idle_token") != args.token:
            print(json.dumps({"closed": False, "reason": "stale token after sleep"}, ensure_ascii=False, indent=2))
            return
        deadline = parse_datetime(state.get("idle_deadline_at"))
    current = now_datetime(args.now)
    if deadline and current < deadline:
        print(json.dumps({"closed": False, "reason": "deadline not reached", "deadline": format_datetime(deadline)}, ensure_ascii=False, indent=2))
        return
    date_value = parse_date(state["date"])
    result = close_recording(paths, date_value, source="idle-timeout", closing="")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_disambiguate(_: Paths, args: argparse.Namespace) -> None:
    """Decide whether a user message is a story-telling request or a diary-recording trigger."""
    text = args.text
    pure_trigger = text.strip() in START_TRIGGERS or text.strip() in END_TRIGGERS
    has_story_content = len(text.strip()) > len("讲故事") + 2
    if pure_trigger and not has_story_content:
        result = {"intent": "recording_trigger", "trigger": text.strip(), "reason": "bare trigger phrase"}
    else:
        result = {"intent": "story_request", "trigger": None, "reason": "has story content or not a bare trigger"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatDiary workflow helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup")
    setup_parser.add_argument("--diary-dir", help="Path to the Obsidian daily diary directory")
    setup_parser.add_argument("--user-label", help='Display name written before user messages, default: "User"')
    setup_parser.add_argument("--state-file", help="Optional path for ChatDiary recording state")
    setup_parser.add_argument("--tmp-dir", help="Optional path for temporary transcript files")
    setup_parser.add_argument("--idle-timeout-minutes", type=int, help="Auto-close after this many idle minutes; 0 disables")
    setup_parser.add_argument("--agent", help="Agent hook target: auto, all, hermes, claude-code, openclaw; defaults to chatdiary.config.json")
    setup_parser.add_argument("--no-install-hooks", action="store_true", help="Only write ChatDiary config; do not install agent hooks")
    setup_parser.set_defaults(func=run_setup)

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--date")
    start_parser.add_argument("--time")
    start_parser.set_defaults(func=run_start)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("text")
    analyze_parser.set_defaults(func=run_analyze)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--date", required=True)
    append_parser.add_argument("--time", required=True)
    append_parser.add_argument("--text", required=True)
    append_parser.add_argument("--reply", required=True)
    append_parser.set_defaults(func=run_append)

    handle_parser = subparsers.add_parser("handle-turn")
    handle_parser.add_argument("--date")
    handle_parser.add_argument("--time")
    handle_parser.add_argument("--text", required=True)
    handle_parser.add_argument("--reply", default="")
    handle_parser.add_argument("--source", default="manual", help="Trusted caller source, normally set by platform hook adapters")
    handle_parser.add_argument("--allow-manual-reply", action="store_true", help="Permit manual --reply for explicit repair/testing only")
    handle_parser.add_argument("--turn-id")
    handle_parser.add_argument("--now")
    handle_parser.set_defaults(func=run_handle_turn)

    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("--date")
    close_parser.add_argument("--time")
    close_parser.add_argument("--text", default="")
    close_parser.add_argument("--reply", default="")
    close_parser.add_argument("--turn-id")
    close_parser.add_argument("--source", default="manual-close")
    close_parser.add_argument("--now")
    close_parser.add_argument("--no-topics", action="store_true")
    close_parser.set_defaults(func=run_close)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--date", required=True)
    finalize_parser.add_argument("--time", required=True)
    finalize_parser.add_argument("--text", required=True)
    finalize_parser.add_argument("--reply", required=True)
    finalize_parser.add_argument("--force-write", action="store_true")
    finalize_parser.set_defaults(func=run_finalize)

    attach_parser = subparsers.add_parser("attach")
    attach_parser.add_argument("--date")
    attach_parser.add_argument("--source", required=True)
    attach_parser.add_argument("--now")
    attach_parser.set_defaults(func=run_attach)

    topics_parser = subparsers.add_parser("set-topics")
    topics_parser.add_argument("--date", required=True)
    topics_parser.add_argument("topics", nargs="+")
    topics_parser.set_defaults(func=run_set_topics)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=run_status)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--fix", action="store_true", help="Create writable runtime directories when possible")
    doctor_parser.add_argument("--agent", default="auto", help="Agent hook target for --fix: auto, all, hermes, claude-code, openclaw")
    doctor_parser.set_defaults(func=run_doctor)

    timeout_parser = subparsers.add_parser("timeout-check")
    timeout_parser.add_argument("--token")
    timeout_parser.add_argument("--now")
    timeout_parser.add_argument("--no-sleep", action="store_true")
    timeout_parser.set_defaults(func=run_timeout_check)

    disambiguate_parser = subparsers.add_parser("disambiguate")
    disambiguate_parser.add_argument("text")
    disambiguate_parser.set_defaults(func=run_disambiguate)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    paths = resolve_paths()
    args.func(paths, args)


if __name__ == "__main__":
    main()
