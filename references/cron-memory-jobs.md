# 每日记忆更新 Cron 任务

## Job ID
`6ee610afa4bb` — "每日记忆系统更新"

## 脚本路径
```
/usr/bin/env python3 $HERMES_DATA_DIR/cron/update_memory.py
```

## 依赖文件
- MEMORY.md: `$HERMES_DATA_DIR/memories/MEMORY.md`
- USER.md: `$HERMES_DATA_DIR/memories/USER.md`
- 日记目录: `$CHATDIARY_OBSIDIAN_DAILY_DIR/`

## ⚠️ Cron 环境特殊性

**`skip_memory=True` 导致 memory 工具不可用**

cron 容器环境默认 `skip_memory=True`，memory 工具（增删改）在 cron 上下文中完全不可用，调用会报 `⚠️ Memory 工具当前不可用`。

**解决方案**：不依赖 memory 工具，直接读写文件。

## update_memory.py 设计要点

### API 调用（MiniMax）
- thinking block 在 text block 之前 → 必须跳过 thinking 块，只取 text 块
- thinking 块内容会污染 JSON → 用正则提取 `{"key": ..., "old": ..., "new": ...}` 格式
- 模型返回格式是 `key/old/new` 不是 `keyword`

```python
import re, json

def extract_json(text):
    """从 text block 中提取 JSON，忽略 thinking block"""
    blocks = []
    current_type = None
    for line in text.split('\n'):
        if line.startswith('```json'):
            current_type = 'json'
            blocks.append(line)
        elif line.startswith('```'):
            current_type = None
        elif current_type == 'json':
            blocks.append(line)
    content = '\n'.join(blocks)
    # 提取 {..."key"...} 格式
    m = re.search(r'\{[^{}]*"key"[^{}]*\}', content)
    if m:
        return json.loads(m.group())
    return None
```

### 文件写入策略
- 不用 write_file（依赖 `cat` 命令，容器中可能不存在）
- 用 `execute_code` 的 L() helper 函数写入
- 中文路径用 `chr()` 转义避免编码问题

### NAS 权限
- 容器用户可正常读写配置的日记目录
- 路径使用 `os.path.join` 拼接，中文路径不拆分

### 日记扫描逻辑
```python
diary_dir = "$CHATDIARY_OBSIDIAN_DAILY_DIR"
entries = sorted(Path(diary_dir).glob("????-??-??.md"))
# 读取最近3个日记文件用于上下文
recent = entries[-3:]
```

### 对用户显示 "Memory 工具不可用" 时的处理

当 cron 任务执行后用户看到 `⚠️ Memory 工具当前不可用` 提示：
- **这是已知限制，不是错误**，不是需要配置的东西
- 直接告诉用户"这是 cron 环境的正常限制，不影响功能"
- **不要**引导用户去"配置环境"，以免造成不必要的担心

## 常见失败模式

| 失败现象 | 原因 | 解法 |
|----------|------|------|
| JSON 解析失败 | thinking block 在 text 前 | 只解析 text block |
| thinking 内容混入 JSON | 用 json.loads 全量解析 | 正则提取 key/old/new |
| API 返回截断 | 响应超长 | 正则提取完整 JSON 对象 |
| PermissionError | 容器用户无权写入 | 检查容器用户和挂载目录权限 |
