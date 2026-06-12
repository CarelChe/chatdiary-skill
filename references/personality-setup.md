# 日记角色设定配置（2026-05-12）

## 背景

用户希望日记 Skill 触发时，AI 的回复风格符合 SKILL.md 中的角色设定：
> 用聊天的形式回复，像好朋友一样，有话直说，理性有主见，不恭维附和，可以从多角度分析问题，适当引导深层讨论。

这条设定原本只写在 SKILL.md 的文档里，AI 读取 skill 时遵守，但没有配置为系统的 `ephemeral_system_prompt`。

## 配置方式

### 1. Gateway 启动时自动加载

`$HERMES_DATA_DIR/config.yaml` 中：

```yaml
agent:
  system_prompt: "用聊天的形式回复，像好朋友一样..."
  personalities:
    diary-buddy:
      system_prompt: "用聊天的形式回复，像好朋友一样..."
      style: 亲切自然，朋友聊天语气
display:
  personality: diary-buddy
```

`agent.system_prompt` 被 `gateway/run.py` 的 `_load_ephemeral_system_prompt()` 读取，启动后即生效。

### 2. `/personality` 命令切换

Gateway 支持通过 `/personality` 命令切换人格。读取 `agent.personalities` 中的定义。

- `/personality` — 列出所有可用的 personality
- `/personality diary-buddy` — 切换到日记角色
- `/personality none` — 清除

命令处理函数：`gateway/run.py` 的 `_handle_personality_command()`（第 9181 行）

## 架构

```
config.yaml
  agent.personalities.diary-buddy.system_prompt
    ↓
gateway/run.py: _load_ephemeral_system_prompt()
  → self._ephemeral_system_prompt
      ↓
run_agent.py: 附加到系统提示的尾部
```

## 注意

- 用户说"切换回 MiniMax"指的是切换**模型配置**（`model.default`/`model.provider`），不是人格设定。两者独立配置。
- 模型切换需要重启 Gateway 才能生效，人格切换通过 `/personality` 命令实时生效（不需要重启）。
