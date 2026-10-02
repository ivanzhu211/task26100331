# task26100331

关键词库列表翻页库（Python + SQLite，无接口层，由上层 API 服务直接调用）。

## 用法

```python
import datetime as dt
from keywordlib import CollectionRecord, KeywordStore

store = KeywordStore("keywords.db")  # 采集历史与关键词数据都在这一个 SQLite 文件里

store.import_records([
    CollectionRecord("瑜伽垫", 8000, 0.8, 0.3, dt.date(2026, 9, 1)),
])

page = store.first_page()            # 默认每页 50 条，固定当前时刻的快照
while page.cursor is not None:
    page = store.next_page(page.cursor)
```

## 规则

- 采集记录全部保留在 `collection_history` 表；关键词当前值取采集日期最新的一条，
  同日期时以后导入的为准。
- 机会分 = `40*min(1,log10(月搜索量+1)/6) + 35*(1-竞争度) + 25*(1/(1+CPC))`，保留两位小数。
- 列表按机会分降序、短语升序排列。
- `first_page()` 在 `BEGIN IMMEDIATE` 事务内把当时的完整排序列表物化到 `snapshots` 表，
  之后凭 cursor 翻页只读该快照：边翻页边导入不会重、不会漏，导入的数据也不会混入。
  下一次 `first_page()` 开始新一轮快照。快照表会随翻页次数累积，长期运行的服务可定期
  清理不再使用的 `snapshot_id`。

## 测试

```bash
python3 -m pytest tests/ -q
```
