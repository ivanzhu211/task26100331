"""关键词库列表翻页库。

数据与采集历史存于同一个 SQLite 文件，由上层 API 服务以库的方式调用。
"""

from .models import CollectionRecord, KeywordEntry, Page
from .scoring import opportunity_score
from .store import KeywordStore

__all__ = [
    "CollectionRecord",
    "KeywordEntry",
    "KeywordStore",
    "Page",
    "opportunity_score",
]
