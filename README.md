# ChatDiary Skill

ChatDiary is a trigger-controlled diary skill for saving conversational journal sessions into Obsidian daily notes. It is designed for agent environments where hooks can reliably capture the real user message and the real assistant reply after each turn.

## Features

- Start and stop diary recording with trigger phrases.
- Save multi-turn chat sessions into daily Obsidian Markdown files.
- Insert a short topic at the top of the daily note when a session closes.
- Strip start and stop trigger words from long messages before saving.
- Keep temporary transcripts under the skill folder in `.chatdiary/`.
- Auto-close an active diary session after an idle timeout, default 10 minutes.
- Install hook adapters for Hermes, Claude Code, and OpenClaw.
- Reject manual `handle-turn` writes by default so the diary cannot record an assistant reply that was not actually sent by the platform.

## Supported Agents

ChatDiary currently includes hook adapters for:

- Hermes: `agent:end`
- Claude Code: `UserPromptSubmit` + `Stop`
- OpenClaw: `message:received` + `message:sent`

Codex is not optimized in this package because this project depends on platform hooks for reliable transcript capture.

## Installation

Copy the `chatdiary` folder into your agent's skill directory.

For Hermes, a typical location is:

```bash
~/.hermes/skills/chatdiary
```

Then edit:

```bash
chatdiary.config.json
```

Example:

```json
{
  "user_label": "User",
  "diary_dir": "/path/to/Obsidian/Daily",
  "idle_timeout_minutes": 10,
  "agent": "auto"
}
```

Configuration fields:

- `user_label`: display name for user messages in the diary.
- `diary_dir`: Obsidian daily note directory. This must be set before use.
- `idle_timeout_minutes`: idle auto-close timeout. Use `0` to disable.
- `agent`: `auto`, `hermes`, `claude-code`, `openclaw`, or `all`.

After editing the config, run:

```bash
cd /path/to/chatdiary
python3 scripts/chatdiary.py setup
```

If needed, force a specific adapter:

```bash
python3 scripts/chatdiary.py setup --agent hermes
```

For Hermes, restart the Hermes gateway after setup so the hook is reloaded.

## Usage

Start recording with one of these trigger phrases:

- `开启日记`
- `记日记`
- `写日记`
- `讲故事`
- `开始讲故事`

Stop recording with one of these trigger phrases:

- `不讲了`
- `关闭日记`
- `停止讲故事`

The trigger can be part of a longer message. For example:

```text
开启日记 今天下班路上突然想到一件事
```

ChatDiary removes the trigger and saves the remaining message plus the assistant's real reply captured by the hook.

For an ending message:

```text
今天就先聊到这里，不讲了
```

ChatDiary removes the stop trigger, saves the remaining final user message and final assistant reply, then writes the transcript into the daily note.

## Runtime Files

User-editable configuration:

```text
chatdiary.config.json
```

Generated runtime files:

```text
.chatdiary/
  state.json
  tmp/
  adapters/
```

Deleting `.chatdiary/` clears runtime state and temporary transcripts, but it does not clear `chatdiary.config.json`.

## Diagnostics

Check configuration and runtime state:

```bash
python3 scripts/chatdiary.py status
```

Run diagnostics:

```bash
python3 scripts/chatdiary.py doctor --fix
```

Run smoke tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_chatdiary.py
```

## Privacy Notes

Before publishing, make sure `chatdiary.config.json` does not contain your real Obsidian path or personal nickname. The public template should keep `diary_dir` empty or set to `/path/to/Obsidian/Daily`.

Do not commit generated runtime state:

```text
.chatdiary/
tmp/
__pycache__/
*.pyc
.DS_Store
```

These are already listed in `.gitignore`.

---

# ChatDiary Skill（中文）

ChatDiary 是一个用触发词控制的日记 Skill，用来把一轮聊天式日记记录保存到 Obsidian 每日日记中。它依赖 Agent 平台的 Hook 来稳定捕获真实的用户消息和真实的 AI 回复，避免 AI 忘记记录或记录到未实际发送的回复。

## 功能

- 用触发词开始和结束日记记录。
- 将多轮对话保存到 Obsidian 每日 Markdown 日记。
- 结束时自动提取简短话题，写入当天日记顶部。
- 开始/结束触发词可以夹在长句里，保存时会自动删除触发词。
- 临时转录文件默认保存在 Skill 文件夹的 `.chatdiary/` 下。
- 支持空闲超时自动关闭，默认 10 分钟。
- 支持 Hermes、Claude Code、OpenClaw 的 Hook 适配器。
- 默认拒绝手动写入 `handle-turn`，避免把没有真实发出的 AI 回复写进日记。

## 支持的平台

当前包含以下 Hook 适配器：

- Hermes：`agent:end`
- Claude Code：`UserPromptSubmit` + `Stop`
- OpenClaw：`message:received` + `message:sent`

Codex 暂未优化，因为这个项目依赖平台 Hook 来保证对话记录不遗漏。

## 安装

把 `chatdiary` 文件夹复制到对应 Agent 的 Skill 目录。

Hermes 的常见位置是：

```bash
~/.hermes/skills/chatdiary
```

然后编辑：

```bash
chatdiary.config.json
```

示例：

```json
{
  "user_label": "User",
  "diary_dir": "/path/to/Obsidian/Daily",
  "idle_timeout_minutes": 10,
  "agent": "auto"
}
```

配置项：

- `user_label`：写入日记时显示的用户昵称。
- `diary_dir`：Obsidian 日记文件夹路径，使用前必须填写。
- `idle_timeout_minutes`：空闲自动关闭分钟数，填 `0` 表示关闭。
- `agent`：可填 `auto`、`hermes`、`claude-code`、`openclaw` 或 `all`。

编辑配置后运行：

```bash
cd /path/to/chatdiary
python3 scripts/chatdiary.py setup
```

如需强制安装到某个平台：

```bash
python3 scripts/chatdiary.py setup --agent hermes
```

Hermes 安装后需要重启 Hermes gateway，让 Hook 重新加载。

## 使用方式

用以下触发词开始记录：

- `开启日记`
- `记日记`
- `写日记`
- `讲故事`
- `开始讲故事`

用以下触发词结束记录：

- `不讲了`
- `关闭日记`
- `停止讲故事`

触发词可以放在长句中，例如：

```text
开启日记 今天下班路上突然想到一件事
```

ChatDiary 会删除触发词，保存后面的正文和 Hook 捕获到的 AI 真实回复。

结束时也可以这样说：

```text
今天就先聊到这里，不讲了
```

ChatDiary 会删除结束触发词，保存最后一段正文和 AI 最后一条真实回复，然后把整轮记录写入日记。

## 运行文件

用户需要编辑的配置文件：

```text
chatdiary.config.json
```

自动生成的运行文件：

```text
.chatdiary/
  state.json
  tmp/
  adapters/
```

删除 `.chatdiary/` 会清除运行状态和临时转录，但不会删除 `chatdiary.config.json` 中的昵称和日记路径。

## 诊断和测试

查看配置和状态：

```bash
python3 scripts/chatdiary.py status
```

运行诊断：

```bash
python3 scripts/chatdiary.py doctor --fix
```

运行测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_chatdiary.py
```

## 隐私说明

发布到 GitHub 前，确认 `chatdiary.config.json` 里没有你的真实 Obsidian 路径和个人昵称。公开模板应保持 `diary_dir` 为空，或使用 `/path/to/Obsidian/Daily`。

不要提交自动生成的运行文件：

```text
.chatdiary/
tmp/
__pycache__/
*.pyc
.DS_Store
```

这些已经写入 `.gitignore`。
