# Trigger Filter Test Suite (2026-05-12)

## Filter Chain Overview

```
Hook (agent:end) → writes HH:MM U/A: content to tmp
                      ↓
run_finalize → appends closing pair to tmp
                      ↓
load_tmp_transcript → parses HH:MM U/A: content into (time, speaker, content) tuples
                      ↓
filter_trigger_pairs → filters trigger words, orphan A entries
                      ↓
format_conversation_lines → formats into diary markdown
                      ↓
append_transcript → writes to diary file
```

## Complete Test Results (all 7 passed)

### 1. Pure Start Trigger
```
Input:  [("22:00","U","开启日记"), ("22:00","A","已开启")]
Output: []  ✅
```

### 2. Pure End Trigger
```
Input:  [("22:00","U","关闭日记"), ("22:00","A","已关闭")]
Output: []  ✅
```

### 3. Prefix Trigger
```
Input:  [("22:00","U","开启日记 今天聊工作"), ("22:00","A","好的")]
Output: [("22:00","U","今天聊工作"), ("22:00","A","好的")]  ✅
```

### 4. Suffix Trigger
```
Input:  [("22:00","U","今天聊工作不讲了"), ("22:00","A","好的")]
Output: [("22:00","U","今天聊工作"), ("22:00","A","好的")]  ✅
```

### 5. Mid-text (not trigger)
```
Input:  [("22:00","U","今天不讲了工作"), ("22:00","A","好的")]
Output: [("22:00","U","今天不讲了工作"), ("22:00","A","好的")]  ✅
```

### 6. Orphan A (closing message)
```
Input:  [("22:00","U","正常话题"), ("22:00","A","回复"), ("22:00","A","日记已关闭")]
Output: [("22:00","U","正常话题"), ("22:00","A","回复")]  ✅
```

### 7. Empty Input
```
Input:  []
Output: []  ✅
```

## Trigger Words (updated 2026-05-12)

```python
START_TRIGGERS = ("讲故事", "开始讲故事", "开启日记", "记日记", "写日记")
END_TRIGGERS = ("不讲了", "停止讲故事", "关闭日记")
```

## Key Code

### filter_trigger_pairs (chatdiary.py)

```
Rules:
1. U message is a bare start trigger → delete U + following A
2. U message starts with a start trigger → strip trigger + punctuation
3. U message is a bare end trigger → delete U + following A
4. U message ends with an end trigger → strip trigger + punctuation
5. Orphan A entries (no preceding U in filtered output) → filtered out
```

### Format Pipeline

| Step | Input format | Output format |
|------|-------------|---------------|
| Hook write | `(user_msg, ai_response)` | `22:00 U: content\n22:00 A: content` |
| parse_tmp_lines | Raw tmp file content | `[(time, "U", content), ...]` |
| filter_trigger_pairs | `[(time, speaker, content), ...]` | `[(time, speaker, content), ...]` |
| format_conversation_lines | `[(time, speaker, content), ...]` | `["- **HH:MM User：内容**", "- **HH:MM AI：** 内容"]` |
| append_transcript | Formatted lines | Appended to diary before `## 附件` |
