"""数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionRecord:
    """一条采集记录（导入用）。"""

    phrase: str
    monthly_volume: int
    avg_cpc: float
    competition: float
    collected_date: str  # YYYY-MM-DD


@dataclass(frozen=True)
class KeywordItem:
    """列表中的一个关键词当前值。"""

    phrase: str
    monthly_volume: int
    avg_cpc: float
    competition: float
    collected_date: str
    opportunity_score: float


@dataclass(frozen=True)
class Page:
    """一页结果。next_cursor 为 None 表示已是最后一页。"""

    items: list[KeywordItem]
    next_cursor: str | None
