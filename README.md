# task26100331

关键词库列表翻页库（Python + SQLite，纯库，无接口层）。

## 用法

```python
from keywordlib import KeywordStore, CollectionRecord

store = KeywordStore("keywords.sqlite")

# 导入采集记录（所有记录都保留进历史）
store.import_records([
    CollectionRecord("跑鞋 男", 5000, 2.0, 0.4, "2026-09-20"),
])

# 翻页：第一页固定此刻的快照，之后凭 next_cursor 取下一页
page = store.first_page()          # 默认每页 50 条
while page.next_cursor is not None:
    page = store.next_page(page.next_cursor)
```

一次翻页（第一页到最后一页）读到的是取第一页那一刻的列表快照，
翻页过程中的导入不会出现在结果里，不重不漏。

## 规则

- 当前值 = 采集日期最新的记录；同日期时后导入的为准；旧日期补录只进历史。
- 机会分 = `40×min(1,log10(月搜索量+1)/6) + 35×(1−竞争度) + 25×(1/(1+CPC))`，保留两位小数。
- 排序：机会分降序，同分按短语升序。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
