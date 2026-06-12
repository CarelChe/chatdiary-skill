# 日记视频记录文件名 → 日期解析模式

来源：处理 `日记/视频记录/原版/` 92个文件时发现，文件名格式混乱，需解析为标准 `YYYY-MM-DD` 后匹配日记条目。

## 解析函数（Python regex）

```python
import re

def parse_video_date(name):
    """Convert messy video filename to YYYY-MM-DD date list."""
    name = name.replace('.md', '')
    
    # YYYYMMDD.n → 202410.12.2 → 2024-10-12 (.n是日的后缀)
    m = re.match(r'^(\d{4})(\d{2})\.(\d{2})\.(\d+)$', name)
    if m:
        return [f"{m.group(1)}-{m.group(2)}-{m.group(3)}"]
    
    # YYYYMM.DD → 202410.15 → 2024-10-15 (一点)
    m = re.match(r'^(\d{4})(\d{2})\.(\d+)$', name)
    if m:
        return [f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"]
    
    # YYYYMMDD → 20240914 → 2024-09-14 (无点)
    m = re.match(r'^(\d{8})$', name)
    if m:
        return [f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"]
    
    # YYYYMM.DD-n → 20241015-1 → 2024-10-15 (8位数字-序号)
    m = re.match(r'^(\d{8})-(\d+)$', name)
    if m:
        return [f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"]
    
    # YYYYMMDD n → 20240917 1 → 2024-09-17 (空格分隔序号)
    m = re.match(r'^(\d{4})(\d{2})(\d{2}) (\d+)$', name)
    if m:
        return [f"{m.group(1)}-{m.group(2)}-{m.group(3)}"]
    
    # YYYYMM.D-D.D → 202410.1-10.7 → 假期范围
    m = re.match(r'^(\d{4})(\d{2})\.(\d+)-(\d+)\.(\d+)$', name)
    if m:
        year, month = m.group(1), m.group(2)
        start = int(m.group(3))
        end_month, end_day = int(m.group(4)), int(m.group(5))
        if month == f"{end_month:02d}":
            return [f"{year}-{month}-{d:02d}" for d in range(start, end_day + 1)]
    
    # YYYYMMDD-YYYY-DD-n → 20251231-0101-1 → 2025-12-31
    m = re.match(r'^(\d{4})(\d{2})(\d{2})-(\d{4})-(\d+)$', name)
    if m:
        return [f"{m.group(1)}-{m.group(2)}-{m.group(3)}"]
    
    # YYYYMM.D前 → 202410.1前 → 2024-10-01
    m = re.match(r'^(\d{4})(\d{2})\.(\d+)前$', name)
    if m:
        return [f"{m.group(1)}-{m.group(2)}-{int(m.group(3)):02d}"]
    
    # 特殊文件名
    if '遗嘱' in name:
        return ['2025-12-31']
    if '熟醉罗氏虾' in name:
        return ['2025-12-22']
    
    return []
```

## 常见格式对照表

| 文件名 | 解析结果 | 说明 |
|--------|----------|------|
| `20240914` | 2024-09-14 | 8位纯数字 |
| `202410.12` | 2024-10-12 | 年月.日（一点） |
| `202410.15` | 2024-10-15 | 同上 |
| `202410.12.2` | 2024-10-12 | 年月.日.序号 |
| `20240917 1` | 2024-09-17 | 日期后空格+序号 |
| `202410.1-10.7` | 2024-10-01~07 | 假期范围 |
| `20250808-1` | 2025-08-08 | 8位-序号 |
| `20251231-0101-1` | 2025-12-31 | 跨年日期-序号 |
| `202410.1前` | 2024-10-01 | "前"后缀 |
| `2025年遗嘱` | 2025-12-31 | 特殊处理 |
| `20251222-熟醉罗氏虾` | 2025-12-22 | 特殊处理 |

## 匹配逻辑

解析出日期后，与日记文件夹中的文件名做前缀匹配：

```python
for date in dates:
    for diary_name, diary_path in diary_files.items():
        if diary_name.startswith(date):
            found_path = diary_path
            break
```

日记文件夹结构：`日记/YYYY/YYYY-MM-DD 标题.md`，前缀匹配即可命中。

## 关键陷阱

1. `202410.12` vs `20241012` — 前者是一点（`.`），后者无点，都存在
2. `202410.12.2` — 三部分，`.2`是日的后缀，不是独立部分
3. `202410.1-10.7` — 范围格式，需特殊处理
4. 匹配用 `startswith` 而非精确匹配（因为日记标题可能有后缀）
