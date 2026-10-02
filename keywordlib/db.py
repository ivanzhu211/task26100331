"""SQLite 连接与建表。"""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT NOT NULL,
    monthly_volume INTEGER NOT NULL,
    avg_cpc REAL NOT NULL,
    competition REAL NOT NULL,
    collected_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_phrase ON collection_history (phrase, collected_date, id);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    page_size INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_items (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots (id),
    position INTEGER NOT NULL,
    phrase TEXT NOT NULL,
    monthly_volume INTEGER NOT NULL,
    avg_cpc REAL NOT NULL,
    competition REAL NOT NULL,
    collected_date TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (snapshot_id, position)
);
"""


def connect(path: str) -> sqlite3.Connection:
    """打开（必要时创建）数据库并初始化表结构。"""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
