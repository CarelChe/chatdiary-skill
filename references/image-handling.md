# 图片处理（ChatDiary 场景）

## 微信图片接收流程

1. 用户在微信发送图片 → Hermes 收到 `/path/to/image-cache/img_<hash>.jpg`
2. **录制状态下** → 直接调用 `attach` → 复制到 `附件/` → 日记正文插入 `![[附件/...]]`
3. **非录制状态** → 图片留在缓存，不处理

## 核心原则：微信图片不走 MEDIA: 路径

`append` 和 `finalize` 的 `auto_attach` 只匹配 `MEDIA:/绝对路径` 格式（如 `MEDIA:/path/to/photo.jpg`）。

微信图片的缓存路径是 `/path/to/image-cache/img_<hash>.jpg`，**不是** `MEDIA:` 格式，所以 `auto_attach` 永远匹配不到。微信图片必须**手动调用 `attach`**。

## 处理方式

| 场景 | 做法 |
|------|------|
| 录制中收到微信图片 | 直接 `attach`，回复"图片已保存"。**禁止** `vision_analyze`，**禁止**询问内容，**禁止**询问是否需要查看 |

## 录制时收到图片的标准流程

```bash
# 图片已缓存到 /path/to/image-cache/img_<hash>.jpg
# 直接 attach，不要 vision_analyze
CHATDIARY_OBSIDIAN_DAILY_DIR="$CHATDIARY_OBSIDIAN_DAILY_DIR" \
  python3 scripts/chatdiary.py attach \
  --date 2026-05-08 --source /path/to/image-cache/img_<hash>.jpg
```

返回：
```json
{
  "copied": "$CHATDIARY_OBSIDIAN_DAILY_DIR/附件/2026-05-08-2.jpg",
  "embed": "![[附件/2026-05-08-2.jpg]]",
  "sequence": 2
}
```

告知用户："图片已保存"，不要追问内容，不要问"要不要看"。

## attach 脚本返回字段

```json
{
  "copied": "$CHATDIARY_OBSIDIAN_DAILY_DIR/附件/2026-05-08-1.jpg",
  "embed": "![[附件/2026-05-08-1.jpg]]",
  "sequence": 1
}
```

返回后立即回复用户"图片已保存"。此回复**不记录**到日记。禁止询问图片内容或是否需要查看。

## 附件命名规则

- 格式：`YYYY-MM-DD-N.jpg`（N = 当天该附件的序号，从1开始）
- 排序：`ls -la $CHATDIARY_OBSIDIAN_DAILY_DIR/附件/` 查看当天已有附件数量
- sequence 计算：`len(existing) + 1`（脚本自动处理）
