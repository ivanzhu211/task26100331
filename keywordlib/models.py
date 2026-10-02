"""数据类型定义。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionRecord:
    """一条采集记录（导入输入）。"""

    phrase: str
    monthly_searches: int
    avg_cpc: float
    competition: float
    collected_date: dt.date


@dataclass(frozen=True)
class KeywordEntry:
    """列表中的一行：关键词当前值与机会分。"""

    phrase: str
    monthly_searches: int
    avg_cpc: float
    competition: float
    collected_date: dt.date
    score: float


@dataclass(frozen=True)
class Page:
    """一页结果。cursor 为 None 表示没有下一页。"""

    items: tuple[KeywordEntry, ...]
    cursor: str | None
