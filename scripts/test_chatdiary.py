#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("chatdiary.py")
SKILL_ROOT = SCRIPT.parents[1]


def run_cmd(args: list[str], env: dict[str, str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return json.loads(result.stdout)


def run_script(script: Path, args: list[str], env: dict[str, str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return json.loads(result.stdout)


def run_adapter(script: Path, payload: dict, env: dict[str, str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload, ensure_ascii=False),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return json.loads(result.stdout)


def run_shell_adapter(command: str, payload: dict, env: dict[str, str]) -> dict:
    result = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False),
        shell=True,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return json.loads(result.stdout)


def copy_skill(target: Path) -> None:
    shutil.copytree(
        SKILL_ROOT,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".chatdiary", "tmp", "*.pyc", ".DS_Store"),
    )


def assert_installed_config(skill_dir: Path, diary_dir: Path) -> None:
    config = json.loads((skill_dir / "chatdiary.config.json").read_text(encoding="utf-8"))
    assert config["diary_dir"] == str(diary_dir)
    assert config["user_label"] == "Tester"
    assert str(skill_dir / ".chatdiary") in config["tmp_dir"]
    assert str(skill_dir / ".chatdiary") in config["state_file"]
    assert str(skill_dir / ".chatdiary") in config["adapter_state_dir"]


def assert_full_diary(diary_dir: Path) -> None:
    diary_files = list(diary_dir.glob("*.md"))
    assert len(diary_files) == 1
    text = diary_files[0].read_text(encoding="utf-8")
    assert "- **" in text
    assert "开场正文" in text
    assert "中间正文" in text
    assert "最后正文" in text
    assert "开启日记" not in text
    assert "不讲了" not in text
    assert "# 话题\n-" in text


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="chatdiary-test-"))
    try:
        diary_dir = root / "diary"
        tmp_dir = root / "tmp"
        state_file = root / "state" / "state.json"
        media_dir = root / "media"
        media_dir.mkdir(parents=True)
        image = media_dir / "a.jpg"
        image.write_bytes(b"fakeimage")

        env = os.environ.copy()
        env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(diary_dir)
        env["CHATDIARY_TMP_DIR"] = str(tmp_dir)
        env["CHATDIARY_STATE_FILE"] = str(state_file)
        env["CHATDIARY_USER_LABEL"] = "User"
        env["CHATDIARY_IDLE_TIMEOUT_MINUTES"] = "10"
        env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"

        start = run_cmd(["start", "--date", "2026-06-09", "--time", "15:40"], env)
        assert start["recording"] is True

        append = run_cmd(
            [
                "append",
                "--date",
                "2026-06-09",
                "--time",
                "15:41",
                "--text",
                "开启日记 今天聊一下Hermes技能",
                "--reply",
                "好，咱们边看边改。",
            ],
            env,
        )
        assert append["user_turns"] == 1
        assert "今天聊一下Hermes技能" in append["transcript"]

        finalize = run_cmd(
            [
                "finalize",
                "--date",
                "2026-06-09",
                "--time",
                "15:42",
                "--text",
                f"MEDIA:{image}",
                "--reply",
                "行，今天先记到这。",
            ],
            env,
        )
        assert finalize["attachments"] == 1

        diary = diary_dir / "2026-06-09.md"
        text = diary.read_text(encoding="utf-8")
        assert "- **15:41 User：今天聊一下Hermes技能**" in text
        assert "- **15:41 AI：** 好，咱们边看边改。" in text
        assert "![[附件/2026-06-09-1.jpg]]" in text

        topics = run_cmd(["set-topics", "--date", "2026-06-09", "Hermes技能"], env)
        assert topics["topics"] == ["Hermes技能"]

        hook_root = Path(tempfile.mkdtemp(prefix="chatdiary-hook-test-"))
        shutil.rmtree(hook_root, ignore_errors=True)
        hook_diary = root / "hook-diary"
        hook_tmp = root / "hook-tmp"
        hook_state = root / "hook-state" / "state.json"
        hook_env = env.copy()
        hook_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(hook_diary)
        hook_env["CHATDIARY_TMP_DIR"] = str(hook_tmp)
        hook_env["CHATDIARY_STATE_FILE"] = str(hook_state)

        start_turn = run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "20:00",
                "--text",
                "开启日记 今天聊一个公开版技能",
                "--reply",
                "那咱们就按公开版这个方向聊。",
                "--turn-id",
                "turn-1",
                "--now",
                "2026-06-09T20:00:00+08:00",
            ],
            hook_env,
        )
        assert start_turn["start"]["recording"] is True
        assert start_turn["append"]["written_lines"] == 2
        assert "开启日记" not in (hook_tmp / "2026-06-09-2000.txt").read_text(encoding="utf-8")

        duplicate = run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "20:00",
                "--text",
                "开启日记 今天聊一个公开版技能",
                "--reply",
                "那咱们就按公开版这个方向聊。",
                "--turn-id",
                "turn-1",
                "--now",
                "2026-06-09T20:00:30+08:00",
            ],
            hook_env,
        )
        assert duplicate["append"]["deduped"] is True

        end_turn = run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "20:03",
                "--text",
                "这个版本主要是让Hook别漏记，不讲了",
                "--reply",
                "行，这段我给你收住。",
                "--turn-id",
                "turn-2",
                "--now",
                "2026-06-09T20:03:00+08:00",
            ],
            hook_env,
        )
        assert end_turn["close"]["closed"] is True
        hook_text = (hook_diary / "2026-06-09.md").read_text(encoding="utf-8")
        assert "- **20:00 User：今天聊一个公开版技能**" in hook_text
        assert "- **20:03 User：这个版本主要是让Hook别漏记**" in hook_text
        assert "不讲了" not in hook_text
        assert "# 话题\n-" in hook_text

        timeout_diary = root / "timeout-diary"
        timeout_tmp = root / "timeout-tmp"
        timeout_state = root / "timeout-state" / "state.json"
        timeout_env = env.copy()
        timeout_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(timeout_diary)
        timeout_env["CHATDIARY_TMP_DIR"] = str(timeout_tmp)
        timeout_env["CHATDIARY_STATE_FILE"] = str(timeout_state)
        run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "21:00",
                "--text",
                "开启日记 今天测试超时关闭",
                "--reply",
                "好，咱们测这个。",
                "--turn-id",
                "timeout-1",
                "--now",
                "2026-06-09T21:00:00+08:00",
            ],
            timeout_env,
        )
        state = json.loads(timeout_state.read_text(encoding="utf-8"))
        timeout = run_cmd(
            [
                "timeout-check",
                "--token",
                state["idle_token"],
                "--now",
                "2026-06-09T21:11:00+08:00",
                "--no-sleep",
            ],
            timeout_env,
        )
        assert timeout["closed"] is True
        assert json.loads(timeout_state.read_text(encoding="utf-8"))["recording"] is False

        stale_diary = root / "stale-diary"
        stale_tmp = root / "stale-tmp"
        stale_state = root / "stale-state" / "state.json"
        stale_env = env.copy()
        stale_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(stale_diary)
        stale_env["CHATDIARY_TMP_DIR"] = str(stale_tmp)
        stale_env["CHATDIARY_STATE_FILE"] = str(stale_state)
        pure_start = run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "22:00",
                "--text",
                "开启日记",
                "--reply",
                "开好了，咱们慢慢聊。",
                "--turn-id",
                "pure-start",
                "--now",
                "2026-06-09T22:00:00+08:00",
            ],
            stale_env,
        )
        assert pure_start["pure_start"] is True
        pure_tmp = stale_tmp / "2026-06-09-2200.txt"
        assert pure_tmp.read_text(encoding="utf-8") == ""
        token1 = json.loads(stale_state.read_text(encoding="utf-8"))["idle_token"]

        run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "22:05",
                "--text",
                "这轮用来刷新计时器",
                "--reply",
                "好，这轮会刷新。",
                "--turn-id",
                "refresh-turn",
                "--now",
                "2026-06-09T22:05:00+08:00",
            ],
            stale_env,
        )
        stale = run_cmd(
            [
                "timeout-check",
                "--token",
                token1,
                "--now",
                "2026-06-09T22:11:00+08:00",
                "--no-sleep",
            ],
            stale_env,
        )
        assert stale["closed"] is False
        assert stale["reason"] == "stale token"
        assert json.loads(stale_state.read_text(encoding="utf-8"))["recording"] is True

        attach_deadline_before = json.loads(stale_state.read_text(encoding="utf-8"))["idle_deadline_at"]
        run_cmd(["attach", "--date", "2026-06-09", "--source", str(image), "--now", "2026-06-09T22:08:00+08:00"], stale_env)
        attach_deadline_after = json.loads(stale_state.read_text(encoding="utf-8"))["idle_deadline_at"]
        assert attach_deadline_after > attach_deadline_before

        token2 = json.loads(stale_state.read_text(encoding="utf-8"))["idle_token"]
        timeout2 = run_cmd(
            [
                "timeout-check",
                "--token",
                token2,
                "--now",
                "2026-06-09T22:19:00+08:00",
                "--no-sleep",
            ],
            stale_env,
        )
        assert timeout2["closed"] is True

        doctor = run_cmd(["doctor", "--fix"], timeout_env)
        assert doctor["ok"] is True

        unconfigured_env = env.copy()
        unconfigured_env.pop("CHATDIARY_OBSIDIAN_DAILY_DIR", None)
        unconfigured_env["CHATDIARY_STATE_FILE"] = str(root / "unconfigured-state.json")
        unconfigured_env["CHATDIARY_CONFIG_FILE"] = str(root / "empty-config.json")
        setup_required = run_cmd(
            [
                "handle-turn",
                "--source",
                "test",
                "--date",
                "2026-06-09",
                "--time",
                "23:00",
                "--text",
                "开启日记 这句不会被记录",
                "--reply",
                "需要先设置路径。",
            ],
            unconfigured_env,
        )
        assert setup_required["setup_required"] is True
        unconfigured_status = run_cmd(["status"], unconfigured_env)
        assert unconfigured_status["configured"] is False
        assert unconfigured_status["setup_required"] is True
        assert unconfigured_status["config_exists"] is False
        assert unconfigured_status["config_source"] == "none"

        reject_diary = root / "reject-diary"
        reject_tmp = root / "reject-tmp"
        reject_state = root / "reject-state.json"
        reject_env = env.copy()
        reject_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(reject_diary)
        reject_env["CHATDIARY_TMP_DIR"] = str(reject_tmp)
        reject_env["CHATDIARY_STATE_FILE"] = str(reject_state)
        rejected = run_cmd(
            [
                "handle-turn",
                "--date",
                "2026-06-09",
                "--time",
                "23:10",
                "--text",
                "开启日记 这句不应该被手动伪造回复记录",
                "--reply",
                "这是一段没有真实平台Hook来源的回复。",
            ],
            reject_env,
        )
        assert rejected["manual_turn_rejected"] is True
        assert rejected["manual_reply_rejected"] is True
        assert not reject_state.exists()
        assert not reject_tmp.exists()
        assert not reject_diary.exists()

        adapter_env = env.copy()
        adapter_env["CHATDIARY_SKILL_DIR"] = str(SKILL_ROOT)

        hermes_env = adapter_env.copy()
        hermes_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(root / "hermes-diary")
        hermes_env["CHATDIARY_TMP_DIR"] = str(root / "hermes-tmp")
        hermes_env["CHATDIARY_STATE_FILE"] = str(root / "hermes-state.json")
        hermes = run_adapter(
            SKILL_ROOT / "adapters" / "hermes" / "handler.py",
            {
                "event": "agent:end",
                "context": {
                    "session_id": "h1",
                    "message": "开启日记 Hermes适配器测试",
                    "response": "可以，先测Hermes。",
                    "timestamp": "2026-06-10T10:00:00+08:00",
                },
            },
            hermes_env,
        )
        assert hermes["start"]["recording"] is True
        assert hermes["append"]["written_lines"] == 2

        claude_env = adapter_env.copy()
        claude_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(root / "claude-diary")
        claude_env["CHATDIARY_TMP_DIR"] = str(root / "claude-tmp")
        claude_env["CHATDIARY_STATE_FILE"] = str(root / "claude-state.json")
        claude_env["CHATDIARY_ADAPTER_STATE_DIR"] = str(root / "claude-adapter")
        run_adapter(
            SKILL_ROOT / "adapters" / "claude-code" / "user_prompt_submit.py",
            {"session_id": "c1", "prompt": "开启日记 Claude适配器测试", "timestamp": "2026-06-10T10:01:00+08:00"},
            claude_env,
        )
        claude = run_adapter(
            SKILL_ROOT / "adapters" / "claude-code" / "stop.py",
            {"session_id": "c1", "last_assistant_message": "可以，先测Claude。", "timestamp": "2026-06-10T10:01:00+08:00"},
            claude_env,
        )
        assert claude["start"]["recording"] is True
        assert claude["append"]["written_lines"] == 2

        openclaw_env = adapter_env.copy()
        openclaw_env["CHATDIARY_OBSIDIAN_DAILY_DIR"] = str(root / "openclaw-diary")
        openclaw_env["CHATDIARY_TMP_DIR"] = str(root / "openclaw-tmp")
        openclaw_env["CHATDIARY_STATE_FILE"] = str(root / "openclaw-state.json")
        openclaw_env["CHATDIARY_ADAPTER_STATE_DIR"] = str(root / "openclaw-adapter")
        run_adapter(
            SKILL_ROOT / "adapters" / "openclaw" / "message_received.py",
            {"session_id": "o1", "message": "开启日记 OpenClaw适配器测试", "timestamp": "2026-06-10T10:02:00+08:00"},
            openclaw_env,
        )
        openclaw = run_adapter(
            SKILL_ROOT / "adapters" / "openclaw" / "message_sent.py",
            {"session_id": "o1", "message": "可以，先测OpenClaw。", "timestamp": "2026-06-10T10:02:00+08:00"},
            openclaw_env,
        )
        assert openclaw["start"]["recording"] is True
        assert openclaw["append"]["written_lines"] == 2

        install_root = root / "install-tests"
        install_root.mkdir()

        # Hermes: setup installs copied hook files; copied handler uses local adapter config.
        hermes_skill = install_root / "hermes-skill"
        copy_skill(hermes_skill)
        hermes_hooks = install_root / "hermes-hooks"
        hermes_diary = install_root / "hermes-diary"
        (hermes_skill / "chatdiary.config.json").write_text(
            json.dumps(
                {
                    "diary_dir": str(hermes_diary),
                    "user_label": "Tester",
                    "idle_timeout_minutes": 10,
                    "agent": "hermes",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        hermes_setup_env = os.environ.copy()
        hermes_setup_env["CHATDIARY_HERMES_HOOKS_DIR"] = str(hermes_hooks)
        hermes_setup_env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"
        hermes_status = run_script(hermes_skill / "scripts" / "chatdiary.py", ["status"], hermes_setup_env)
        assert hermes_status["configured"] is True
        assert hermes_status["setup_required"] is False
        assert hermes_status["config_source"] == "config"
        hermes_setup = run_script(
            hermes_skill / "scripts" / "chatdiary.py",
            ["setup"],
            hermes_setup_env,
        )
        assert hermes_setup["hooks"][0]["installed"] is True
        assert_installed_config(hermes_skill, hermes_diary)
        hermes_handler = hermes_hooks / "chatdiary-auto-log" / "handler.py"
        hermes_run_env = os.environ.copy()
        hermes_run_env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"
        for minute, message, response in [
            ("10:00:00", "开启日记 开场正文", "开场回复"),
            ("10:01:00", "中间正文", "中间回复"),
            ("10:02:00", "最后正文 不讲了", "收尾回复"),
        ]:
            run_adapter(
                hermes_handler,
                {
                    "event": "agent:end",
                    "context": {
                        "session_id": f"h-{minute}",
                        "message": message,
                        "response": response,
                        "timestamp": f"2026-06-10T{minute}+08:00",
                    },
                },
                hermes_run_env,
            )
        assert_full_diary(hermes_diary)
        assert json.loads((hermes_skill / ".chatdiary" / "state.json").read_text(encoding="utf-8"))["recording"] is False

        # Claude Code: setup merges UserPromptSubmit and Stop hooks into settings.json.
        claude_skill = install_root / "claude-skill"
        copy_skill(claude_skill)
        claude_settings = install_root / "claude-settings.json"
        claude_diary = install_root / "claude-diary"
        claude_setup_env = os.environ.copy()
        claude_setup_env["CHATDIARY_AGENT"] = "claude-code"
        claude_setup_env["CHATDIARY_CLAUDE_SETTINGS_FILE"] = str(claude_settings)
        claude_setup_env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"
        claude_setup = run_script(
            claude_skill / "scripts" / "chatdiary.py",
            ["setup", "--diary-dir", str(claude_diary), "--user-label", "Tester"],
            claude_setup_env,
        )
        assert claude_setup["hooks"][0]["installed"] is True
        assert_installed_config(claude_skill, claude_diary)
        claude_hooks = json.loads(claude_settings.read_text(encoding="utf-8"))["hooks"]
        claude_user_cmd = claude_hooks["UserPromptSubmit"][-1]["hooks"][0]["command"]
        claude_stop_cmd = claude_hooks["Stop"][-1]["hooks"][0]["command"]
        claude_run_env = os.environ.copy()
        claude_run_env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"
        for idx, (message, response) in enumerate([
            ("开启日记 开场正文", "开场回复"),
            ("中间正文", "中间回复"),
            ("最后正文 不讲了", "收尾回复"),
        ], start=1):
            payload_base = {"session_id": "claude-session", "timestamp": f"2026-06-10T11:0{idx}:00+08:00"}
            run_shell_adapter(claude_user_cmd, {**payload_base, "prompt": message}, claude_run_env)
            run_shell_adapter(claude_stop_cmd, {**payload_base, "last_assistant_message": response}, claude_run_env)
        assert_full_diary(claude_diary)
        assert json.loads((claude_skill / ".chatdiary" / "state.json").read_text(encoding="utf-8"))["recording"] is False

        # OpenClaw: setup merges message:received and message:sent hooks.
        openclaw_skill = install_root / "openclaw-skill"
        copy_skill(openclaw_skill)
        openclaw_hooks_file = install_root / "openclaw-hooks.json"
        openclaw_diary = install_root / "openclaw-diary"
        openclaw_setup_env = os.environ.copy()
        openclaw_setup_env["CHATDIARY_AGENT"] = "openclaw"
        openclaw_setup_env["CHATDIARY_OPENCLAW_HOOKS_FILE"] = str(openclaw_hooks_file)
        openclaw_setup_env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"
        openclaw_setup = run_script(
            openclaw_skill / "scripts" / "chatdiary.py",
            ["setup", "--diary-dir", str(openclaw_diary), "--user-label", "Tester"],
            openclaw_setup_env,
        )
        assert openclaw_setup["hooks"][0]["installed"] is True
        assert_installed_config(openclaw_skill, openclaw_diary)
        openclaw_hooks = json.loads(openclaw_hooks_file.read_text(encoding="utf-8"))["hooks"]
        openclaw_received_cmd = openclaw_hooks["message:received"][-1]["command"]
        openclaw_sent_cmd = openclaw_hooks["message:sent"][-1]["command"]
        openclaw_run_env = os.environ.copy()
        openclaw_run_env["CHATDIARY_DISABLE_TIMEOUT_ARM"] = "1"
        for idx, (message, response) in enumerate([
            ("开启日记 开场正文", "开场回复"),
            ("中间正文", "中间回复"),
            ("最后正文 不讲了", "收尾回复"),
        ], start=1):
            payload_base = {"session_id": "openclaw-session", "timestamp": f"2026-06-10T12:0{idx}:00+08:00"}
            run_shell_adapter(openclaw_received_cmd, {**payload_base, "message": message}, openclaw_run_env)
            run_shell_adapter(openclaw_sent_cmd, {**payload_base, "message": response}, openclaw_run_env)
        assert_full_diary(openclaw_diary)
        assert json.loads((openclaw_skill / ".chatdiary" / "state.json").read_text(encoding="utf-8"))["recording"] is False

        print("chatdiary smoke tests passed")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
