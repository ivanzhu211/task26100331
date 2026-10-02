"""SQLite 存储与快照翻页。"""

from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
import uuid
from collections.abc import Iterable

from .models import CollectionRecord, KeywordEntry, Page
from .scoring import opportunity_score

DEFAULT_PAGE_SIZE = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT NOT NULL,
    monthly_searches INTEGER NOT NULL,
    avg_cpc REAL NOT NULL,
    competition REAL NOT NULL,
    collected_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_phrase_date
    ON collection_history (phrase, collected_date DESC, id DESC);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    phrase TEXT NOT NULL,
    monthly_searches INTEGER NOT NULL,
    avg_cpc REAL NOT NULL,
    competition REAL NOT NULL,
    collected_date TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (snapshot_id, position)
);
"""

_CURRENT_VALUES_SQL = """
SELECT phrase, monthly_searches, avg_cpc, competition, collected_date
FROM collection_history AS h
WHERE id = (
    SELECT id FROM collection_history AS newer
    WHERE newer.phrase = h.phrase
    ORDER BY collected_date DESC, id DESC
    LIMIT 1
)
"""


class KeywordStore:
    """关键词库：导入采集记录、按机会分快照翻页。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "KeywordStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def import_records(self, records: Iterable[CollectionRecord]) -> int:
        """导入一批采集记录，全部保留进历史。返回导入条数。"""
        rows = []
        for record in records:
            _validate(record)
            rows.append(
                (
                    record.phrase,
                    record.monthly_searches,
                    record.avg_cpc,
                    record.competition,
                    record.collected_date.isoformat(),
                )
            )
        with self._conn:
            self._conn.executemany(
                "INSERT INTO collection_history"
                " (phrase, monthly_searches, avg_cpc, competition, collected_date)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def first_page(self, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
        """取第一页，并固定当前时刻的列表快照。"""
        if page_size < 1:
            raise ValueError("page_size 必须为正整数")
        snapshot_id = uuid.uuid4().hex
        # BEGIN IMMEDIATE 保证快照计算期间没有其他写入，列表固定在取第一页这一刻。
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            rows = self._conn.execute(_CURRENT_VALUES_SQL).fetchall()
            entries = [
                (
                    opportunity_score(r[1], r[2], r[3]),
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                )
                for r in rows
            ]
            entries.sort(key=lambda e: (-e[0], e[1]))
            self._conn.executemany(
                "INSERT INTO snapshots"
                " (snapshot_id, position, phrase, monthly_searches, avg_cpc,"
                " competition, collected_date, score)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (snapshot_id, pos, e[1], e[2], e[3], e[4], e[5], e[0])
                    for pos, e in enumerate(entries)
                ],
            )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return self._read_page(snapshot_id, 0, page_size, len(entries))

    def next_page(self, cursor: str) -> Page:
        """凭上一页返回的翻页凭据取下一页。"""
        snapshot_id, offset, page_size = _decode_cursor(cursor)
        total = self._conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()[0]
        if total == 0 and offset > 0:
            raise ValueError("翻页凭据无效或快照已不存在")
        return self._read_page(snapshot_id, offset, page_size, total)

    def _read_page(
        self, snapshot_id: str, offset: int, page_size: int, total: int
    ) -> Page:
        rows = self._conn.execute(
            "SELECT phrase, monthly_searches, avg_cpc, competition,"
            " collected_date, score FROM snapshots"
            " WHERE snapshot_id = ? AND position >= ? AND position < ?"
            " ORDER BY position",
            (snapshot_id, offset, offset + page_size),
        ).fetchall()
        items = tuple(
            KeywordEntry(
                phrase=r[0],
                monthly_searches=r[1],
                avg_cpc=r[2],
                competition=r[3],
                collected_date=dt.date.fromisoformat(r[4]),
                score=r[5],
            )
            for r in rows
        )
        next_offset = offset + len(items)
        next_cursor = (
            _encode_cursor(snapshot_id, next_offset, page_size)
            if next_offset < total
            else None
        )
        return Page(items=items, cursor=next_cursor)


def _validate(record: CollectionRecord) -> None:
    if not record.phrase:
        raise ValueError("关键词短语不能为空")
    if record.monthly_searches < 0:
        raise ValueError("月搜索量不能为负")
    if record.avg_cpc < 0:
        raise ValueError("平均CPC不能为负")
    if not 0.0 <= record.competition <= 1.0:
        raise ValueError("竞争度必须在 0 到 1 之间")


def _encode_cursor(snapshot_id: str, offset: int, page_size: int) -> str:
    payload = json.dumps({"s": snapshot_id, "o": offset, "p": page_size})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, int, int]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return str(payload["s"]), int(payload["o"]), int(payload["p"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("翻页凭据无效") from exc
