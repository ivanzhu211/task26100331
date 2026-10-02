"""KeywordStore：导入采集记录 + 快照一致性翻页。"""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime, timezone

from .db import connect
from .models import CollectionRecord, KeywordItem, Page
from .scoring import opportunity_score

DEFAULT_PAGE_SIZE = 50

# 每个关键词的当前值：采集日期最新；同日期时后导入（id 大）的为准。
_CURRENT_VALUES_SQL = """
SELECT phrase, monthly_volume, avg_cpc, competition, collected_date
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY phrase
               ORDER BY collected_date DESC, id DESC
           ) AS rn
    FROM collection_history
)
WHERE rn = 1
"""


def _encode_cursor(snapshot_id: int, offset: int) -> str:
    payload = json.dumps({"s": snapshot_id, "o": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[int, int]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return int(payload["s"]), int(payload["o"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("无效的翻页凭据") from exc


class KeywordStore:
    def __init__(self, db_path: str) -> None:
        self._conn = connect(db_path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "KeywordStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def import_records(self, records: list[CollectionRecord]) -> int:
        """批量导入采集记录，返回导入条数。所有记录都进历史。"""
        with self._conn:
            self._conn.executemany(
                "INSERT INTO collection_history"
                " (phrase, monthly_volume, avg_cpc, competition, collected_date)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (r.phrase, r.monthly_volume, r.avg_cpc, r.competition, r.collected_date)
                    for r in records
                ],
            )
        return len(records)

    def first_page(self, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
        """取第一页；同时固定此刻的列表快照。"""
        if page_size <= 0:
            raise ValueError("page_size 必须为正整数")
        snapshot_id = self._create_snapshot(page_size)
        return self._read_page(snapshot_id, 0, page_size)

    def next_page(self, cursor: str) -> Page:
        """凭上一页返回的翻页凭据取下一页。"""
        snapshot_id, offset = _decode_cursor(cursor)
        return self._read_page(snapshot_id, offset, self._page_size(snapshot_id))

    def _create_snapshot(self, page_size: int) -> int:
        """把此刻的完整排名列表物化到 snapshot_items，返回快照 id。"""
        rows = self._conn.execute(_CURRENT_VALUES_SQL).fetchall()
        ranked = sorted(
            (
                (
                    phrase,
                    volume,
                    cpc,
                    competition,
                    collected_date,
                    opportunity_score(volume, cpc, competition),
                )
                for phrase, volume, cpc, competition, collected_date in rows
            ),
            key=lambda item: (-item[5], item[0]),
        )
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO snapshots (created_at, page_size) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(), page_size),
            )
            snapshot_id = int(cur.lastrowid)
            self._conn.executemany(
                "INSERT INTO snapshot_items"
                " (snapshot_id, position, phrase, monthly_volume, avg_cpc,"
                "  competition, collected_date, score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (snapshot_id, position, *item)
                    for position, item in enumerate(ranked)
                ],
            )
        return snapshot_id

    def _page_size(self, snapshot_id: int) -> int:
        row = self._conn.execute(
            "SELECT page_size FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise ValueError("翻页凭据对应的快照不存在")
        return int(row[0])

    def _read_page(self, snapshot_id: int, offset: int, page_size: int) -> Page:
        rows = self._conn.execute(
            "SELECT phrase, monthly_volume, avg_cpc, competition, collected_date, score"
            " FROM snapshot_items"
            " WHERE snapshot_id = ? AND position >= ?"
            " ORDER BY position LIMIT ?",
            (snapshot_id, offset, page_size),
        ).fetchall()
        total = self._conn.execute(
            "SELECT COUNT(*) FROM snapshot_items WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()[0]
        items = [
            KeywordItem(
                phrase=phrase,
                monthly_volume=volume,
                avg_cpc=cpc,
                competition=competition,
                collected_date=collected_date,
                opportunity_score=score,
            )
            for phrase, volume, cpc, competition, collected_date, score in rows
        ]
        next_offset = offset + len(items)
        next_cursor = _encode_cursor(snapshot_id, next_offset) if next_offset < total else None
        return Page(items=items, next_cursor=next_cursor)
