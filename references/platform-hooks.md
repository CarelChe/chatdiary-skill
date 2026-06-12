# Platform Hook Adapters

ChatDiary 的核心脚本是 `scripts/chatdiary.py`。正常情况下用户先编辑 `chatdiary.config.json`，再运行 `python3 scripts/chatdiary.py setup`；脚本会自动识别 Agent 并安装 hook。平台 hook 不实现日记规则，只负责把一轮对话交给统一入口：

```bash
python3 scripts/chatdiary.py handle-turn --time HH:MM --text "用户原文" --reply "AI回复" --source hermes-hook
```

`handle-turn` 统一处理开始触发词、结束触发词、长句触发词清洗、去重、空闲计时器和原子关闭。

`handle-turn` 必须来自真实平台 hook 事件。手动调用 `handle-turn` 默认会被拒绝，原因是 AI 可能把“准备写入的回复”和“实际发给用户的回复”弄混，导致日记内容与聊天窗口不一致。三个可信来源是 `hermes-hook`、`claude-code-hook`、`openclaw-hook`。

## Hermes

文件：

```text
adapters/hermes/HOOK.yaml
adapters/hermes/handler.py
```

自动安装：

```bash
python3 scripts/chatdiary.py setup
```

如果自动识别不到 Hermes，可强制：

```bash
python3 scripts/chatdiary.py setup --agent hermes
```

安装细节：

1. 把 `HOOK.yaml` 和 `handler.py` 放到 Hermes hook 目录。
2. 写入 `chatdiary_adapter_config.json`，让复制到 Hermes 目录里的 handler 找到原 skill。
3. 如果 Hermes 有完整 session jsonl，设置 `HERMES_DATA_DIR` 或 `HERMES_SESSION_DIR`，handler 会优先读取完整 session，避免事件字段截断。
4. 重启 Hermes gateway 让 hook 生效。

事件：`agent:end`。

关闭规则：不要监听 `session:end` 自动关闭。只有用户结束触发词或 idle timeout 能关闭。

## Claude Code

文件：

```text
adapters/claude-code/settings.example.json
adapters/claude-code/user_prompt_submit.py
adapters/claude-code/stop.py
```

自动安装：

```bash
python3 scripts/chatdiary.py setup --agent claude-code
```

安装细节：

1. 自动定位 Claude Code settings；也可用 `CHATDIARY_CLAUDE_SETTINGS_FILE=/path/to/settings.json` 指定。
2. 自动合并 `UserPromptSubmit` 和 `Stop` hooks。
3. hook 命令会带上 `CHATDIARY_CONFIG_FILE` 和 adapter state 路径，不需要用户手动改 JSON。

事件：

- `UserPromptSubmit`：暂存用户消息。
- `Stop`：拿到最后一条 AI 回复，配对用户消息后调用 `handle-turn`。

关闭规则：`Stop` 只表示 AI 回复完了，不等于关闭日记。只有用户结束触发词或 idle timeout 能关闭。

## OpenClaw

文件：

```text
adapters/openclaw/hooks.example.json
adapters/openclaw/message_received.py
adapters/openclaw/message_sent.py
```

自动安装：

```bash
python3 scripts/chatdiary.py setup --agent openclaw
```

安装细节：

1. 自动定位 OpenClaw hooks 配置；也可用 `CHATDIARY_OPENCLAW_HOOKS_FILE=/path/to/hooks.json` 指定。
2. 自动合并 `message:received` 和 `message:sent` hooks。
3. hook 命令会带上 `CHATDIARY_CONFIG_FILE` 和 adapter state 路径，不需要用户手动合并 JSON。

事件：

- `message:received`：暂存用户消息。
- `message:sent`：拿到 AI 回复，配对用户消息后调用 `handle-turn`。

关闭规则：不要用会话结束事件关闭日记。只有用户结束触发词或 idle timeout 能关闭。

## Shared Environment Variables

```text
CHATDIARY_SKILL_DIR=/path/to/chatdiary
CHATDIARY_SCRIPT=/path/to/chatdiary/scripts/chatdiary.py
CHATDIARY_CONFIG_FILE=<skill>/chatdiary.config.json
CHATDIARY_ADAPTER_STATE_DIR=<skill>/.chatdiary/adapters/<platform>
CHATDIARY_DISABLE_TIMEOUT_ARM=1
```

`CHATDIARY_DISABLE_TIMEOUT_ARM=1` 只用于测试，正常使用不要设置。
