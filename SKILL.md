---
name: chatdiary
description: 'Use when recording chat conversations into daily Obsidian diary files. Supports trigger-controlled recording, 10-minute idle close, and hook adapters for Hermes, Claude Code, and OpenClaw.'
argument-hint: 'Chat conversation logging to Obsidian diary'
user-invocable: true
disable-model-invocation: false
---

# ChatDiary 执行清单

这是用于把聊天对话写入 Obsidian 日记的 Skill。开始和结束必须由用户触发词控制；平台 hook 只负责自动记录每轮对话，不能因为 session 结束而关闭日记。只有遇到补录、迁移、图片、周复盘、memory 提炼等特殊场景时，再读取对应 `references/` 文件。

所有命令默认从 skill 根目录执行，脚本路径使用相对路径 `scripts/chatdiary.py`。

## 角色语气

日记模式中的所有回复都要像朋友聊天：有话直说、理性、有主见，不切成客服或操作员风格。

禁止在用户可见回复里使用：
- 表格
- 加粗分点列表
- "建议/提醒/注意" 开头
- 客服式排版和术语解释
- "作为朋友/作为一个..." 这类话头
- 长括号解释

开启、关闭、补录、报错汇报也要保持这个语气。不要用「日记关了。」这种操作员句子，改成「行，今天先记到这。」这种自然说法。

用户代词混用时不要追问。用户写 "他""她""它" 前后不一致时，按上下文判断或统一用 "他" 继续聊。

## 核心流程

### 初次设置

首次使用前，用户必须手动编辑 Skill 根目录下的 `chatdiary.config.json`：

```json
{
  "user_label": "User",
  "diary_dir": "/path/to/Obsidian/Daily",
  "idle_timeout_minutes": 10,
  "agent": "auto"
}
```

- `user_label`：写入日记时显示的用户昵称，默认 `User`
- `diary_dir`：Obsidian 日记文件夹路径，必须由用户填写
- `idle_timeout_minutes`：空闲自动关闭分钟数，`0` 表示关闭这个功能
- `agent`：通常保留 `auto`；需要强制时可填 `hermes`、`claude-code`、`openclaw` 或 `all`

`.chatdiary/` 只保存临时状态、tmp 和 adapter 状态。用户删除 `.chatdiary/` 不会清除 `chatdiary.config.json` 里的昵称和笔记库路径。

硬性规则：用户第一次触发开始词，或用户说自己删除了 `.chatdiary`，必须先运行：

```bash
python3 scripts/chatdiary.py status
```

如果返回 `setup_required=true` 或 `configured=false`，不要调用 `start`、`append`、`finalize`、`close` 或 `handle-turn`，也不要用记忆里的旧路径代替用户确认。直接让用户编辑 `chatdiary.config.json`，至少填好 `diary_dir`。用户确认已经编辑后，再运行：

```bash
python3 scripts/chatdiary.py setup \
  --agent hermes
```

`setup` 会读取 `chatdiary.config.json`，创建运行目录，并尽可能安装对应 hook：

- Hermes：安装 `agent:end` hook
- Claude Code：合并 `UserPromptSubmit` 和 `Stop` hooks
- OpenClaw：合并 `message:received` 和 `message:sent` hooks

如需强制安装指定平台，可加 `--agent hermes`、`--agent claude-code`、`--agent openclaw` 或 `--agent all`。如需把临时转录文件放到 skill 目录外，才额外传 `--tmp-dir "/path/to/chatdiary/tmp"`。

也可以用环境变量覆盖配置：

```bash
CHATDIARY_OBSIDIAN_DAILY_DIR="/path/to/Obsidian/Daily" \
CHATDIARY_USER_LABEL="User" \
CHATDIARY_IDLE_TIMEOUT_MINUTES=10 \
python3 scripts/chatdiary.py status
```

初始化后可运行诊断：

```bash
python3 scripts/chatdiary.py doctor --fix
```

`doctor` 用于检查配置、路径权限、状态文件、平台 adapters 是否存在。`--fix` 只创建运行目录，不会修改日记内容。

如果用户第一次用开始触发词但还没配置路径，`handle-turn` 会返回 `setup_required=true`；此时让用户编辑 `chatdiary.config.json`，再运行 `setup`。运行 `setup` 后需要重启 Hermes gateway，让新 hook 和新配置生效。

### 开启日记

用户说「开启日记」「记日记」「写日记」「讲故事」「开始讲故事」时：

先检查 `status`。如果 `setup_required=true`，先完成初次设置，不要创建空日记文件。

```bash
python3 scripts/chatdiary.py handle-turn \
  --date YYYY-MM-DD \
  --time HH:MM \
  --text "开启日记 用户正文" \
  --reply "AI回复" \
  --source hermes-hook
```

正常模式下只能由平台 adapter 在 AI 回复后调用 `handle-turn`。不要让 AI 手动执行 `handle-turn`，否则可能把没有真实发送给用户的内容写进日记；脚本默认会拒绝这种手动写入。Hermes、Claude Code、OpenClaw adapter 会分别使用 `--source hermes-hook`、`--source claude-code-hook`、`--source openclaw-hook`。

如果用户只说纯开始触发词，只开启 recording，不记录本轮确认语；如果开始触发词后面还有正文，脚本会删掉触发词并记录正文和平台 Hook 捕获到的 AI 回复。

默认不要手动传 `--date`，让脚本用当天日期。只有用户明确要求记到指定日期时才传。

### 记录一轮对话

每轮用户消息和 AI 回复完成后，由 hook adapter 一次性调用 `handle-turn`：

```bash
python3 scripts/chatdiary.py handle-turn \
  --date YYYY-MM-DD \
  --time HH:MM \
  --text "用户说的内容" \
  --reply "AI回复内容" \
  --source claude-code-hook
```

不要先写用户消息再单独写 AI 回复。旧命令 `append` 仍保留给明确补救使用，但正常 hook 流程应统一调用 `handle-turn`，并且整轮内容必须来自平台 Hook 捕获到的真实用户消息和真实 AI 输出。

Hermes、Claude Code、OpenClaw 的 adapters 见 `references/platform-hooks.md`。

### 收到图片

录制中收到图片时，只保存附件，不查看、不分析、不追问图片内容。

```bash
python3 scripts/chatdiary.py attach \
  --date YYYY-MM-DD \
  --source /path/to/image.jpg
```

聊天平台图片通常不是 `MEDIA:` 格式，优先从平台缓存或上传文件路径找源文件。图片处理细节见 `references/image-handling.md`。

### 关闭日记

用户说「不讲了」「关闭日记」「停止讲故事」时：

```bash
python3 scripts/chatdiary.py handle-turn \
  --date YYYY-MM-DD \
  --time HH:MM \
  --text "最后一段正文 不讲了" \
  --reply "AI结束语" \
  --source openclaw-hook
```

如果用户只说纯结束触发词，不记录本轮关闭确认语；如果结束触发词前面还有正文，脚本会删掉结束触发词，记录正文和平台 Hook 捕获到的 AI 最后一条回复，然后关闭并写入日记。

旧命令 `finalize` 仍保留给手动补救使用；正常 hook 流程使用 `handle-turn` 或 `close`。

### 设置话题

`handle-turn` 遇到结束触发词时会原子完成关闭和话题写入，不要再让 AI 额外确认话题。

```bash
python3 scripts/chatdiary.py close \
  --date YYYY-MM-DD \
  --time HH:MM \
  --source manual-close
```

旧命令 `set-topics` 仍保留给补救或人工修正使用。话题默认 1 个。只有用户明确说「还有一件」「两件事」「三个话题」等，才扩展到 2-3 个。

当前脚本会把 topic 截到约 18 字；为避免截断，topic 尽量控制在 15 字以内。`set-topics` 后立刻检查：

```bash
grep -A2 "话题" "$CHATDIARY_OBSIDIAN_DAILY_DIR/YYYY-MM-DD.md"
```

如果发现被截断，用文件编辑整体修正话题区。不要覆盖用户明确拒绝的话题；用户说「不进去」「不要」「不用了」时跳过或撤回本轮 topic。

### 空闲关闭

recording 开启后，每次成功记录一轮对话或保存附件，都会刷新空闲计时器。默认 10 分钟内没有新的文字或图片，脚本会按 `idle-timeout` 自动关闭本轮日记、写入 Obsidian、提取话题，并把 `recording` 改回 `false`。

这不是 session 自动关闭：平台 session 结束、窗口关闭、模型停止回复都不能直接 finalize。只有两种关闭路径有效：
- 用户发送结束触发词
- recording 已开启后达到配置的空闲分钟数

## 触发词

- 开始：开启日记、记日记、写日记、讲故事、开始讲故事
- 结束：不讲了、关闭日记、停止讲故事
- 日记提炼：帮我看最近日记哪些值得记、把最近日记存一下、提炼记忆、日记里 X 事记一下、哪些值得存到 memory
- 会话存档：保存会话。这属于 session-save，不走 chatdiary。

「开启日记」和「保存会话」不能混。前者写入 Obsidian 日记目录下的 `YYYY-MM-DD.md`，后者写入 session 目录。

## 格式和路径

日记主文件：

```text
$CHATDIARY_OBSIDIAN_DAILY_DIR/YYYY-MM-DD.md
```

附件目录：

```text
$CHATDIARY_OBSIDIAN_DAILY_DIR/附件/
```

tmp 文件：

```text
<skill>/.chatdiary/tmp/YYYY-MM-DD-HHMM.txt
```

脚本入口：

```text
scripts/chatdiary.py
```

平台 adapters：

```text
adapters/hermes/
adapters/claude-code/
adapters/openclaw/
```

对话格式：

```markdown
- **HH:MM User：用户内容**
- **HH:MM AI：** AI内容
----
## 附件
```

上一条是 AI、当前条是用户时，中间空一行。

## 补录和迁移

finalize 后发现漏录，不要直接 append。先查 tmp 和日记文件当前状态：

```bash
cat .chatdiary/tmp/YYYY-MM-DD-HHMM.txt
grep "User：" "$CHATDIARY_OBSIDIAN_DAILY_DIR/YYYY-MM-DD.md"
```

判断：
- tmp 有完整内容，日记无该时段记录：可用 `append_transcript` 补录
- tmp 有内容，日记已有部分或完整记录：整体重写对应区块
- tmp 为空，日记有部分记录：整体重写对应区块

今天录的内容如果全是昨天发生的事，finalize 后整体迁移到昨天日记；保留记录时间戳，清空今天文件内容，清理对应 tmp。完整流程见 `references/diary-date-migration.md`。

图片漏录或 finalize 返回 `user_turns=0` 但用户实际发图，见 `references/image-handling.md`。

## 日记到记忆

用户明确要求「看最近日记」「哪些值得记」「存到 memory」时，读取最近 7 天日记，挑长期有用的信息写入 memory。

存：长期身份/状态、家属关系、后续还会提到的事、复查日期、项目交接、阶段性截止日期。

不存：一次性事件细节、普通行程、吃了什么、临时小插曲、情绪感叹。

优先 replace 已有同主题 memory，少用 add 制造冗余。阶段性信息要标注「过期可删」。更完整流程见 `references/memory-review-workflow.md`。

## 参考资料

- `references/image-handling.md`：图片缓存、`MEDIA:` 与手动 attach
- `references/date-parsing-patterns.md`：视频记录文件名到日期的解析模式
- `references/diary-date-migration.md`：finalize 后跨日期迁移
- `references/diary-format.md`：Obsidian 日记格式
- `references/topic-rejection-handling.md`：用户拒绝话题追加后的处理
- `references/memory-review-workflow.md`：结构化审查 memory
- `references/personality-setup.md`：日记模式的人格和语气设定
- `references/platform-hooks.md`：Hermes、Claude Code、OpenClaw hook adapters
- `references/trigger-filter-tests.md`：触发词清洗规则测试样例
