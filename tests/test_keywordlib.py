"""关键词库翻页与快照一致性测试。"""

from __future__ import annotations

import datetime as dt

import pytest

from keywordlib import CollectionRecord, KeywordStore, opportunity_score

BASE_DATE = dt.date(2026, 9, 1)


def make_record(
    phrase: str,
    searches: int,
    cpc: float,
    competition: float,
    date: dt.date = BASE_DATE,
) -> CollectionRecord:
    return CollectionRecord(phrase, searches, cpc, competition, date)


def collect_all_pages(store: KeywordStore, page_size: int, imports=None):
    """翻完整个列表；imports 为 {翻完第几页后: [记录]} 的导入计划。"""
    imports = imports or {}
    items = []
    page = store.first_page(page_size=page_size)
    page_no = 1
    while True:
        items.extend(page.items)
        if page_no in imports:
            store.import_records(imports[page_no])
        if page.cursor is None:
            return items
        page = store.next_page(page.cursor)
        page_no += 1


def expected_list(records):
    """用取第一页之前的数据独立算出的期望列表。"""
    current = {}
    for record in records:
        key = record.phrase
        if key not in current or record.collected_date >= current[key].collected_date:
            current[key] = record
    entries = [
        (
            opportunity_score(r.monthly_searches, r.avg_cpc, r.competition),
            r.phrase,
            r,
        )
        for r in current.values()
    ]
    entries.sort(key=lambda e: (-e[0], e[1]))
    return entries


class TestOpportunityScore:
    def test_formula(self):
        assert opportunity_score(1_000_000, 1.0, 0.5) == 70.0
        assert opportunity_score(0, 0.0, 0.0) == 60.0
        assert opportunity_score(999, 0.5, 1.0) == 36.67

    def test_volume_capped_at_million(self):
        assert opportunity_score(1_000_000, 1.0, 0.5) == opportunity_score(
            10_000_000, 1.0, 0.5
        )

    def test_rounded_to_two_decimals(self):
        score = opportunity_score(12345, 0.37, 0.42)
        assert round(score, 2) == score


class TestCurrentValue:
    def test_latest_collected_date_wins(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records([make_record("瑜伽垫", 1000, 1.0, 0.5, dt.date(2026, 9, 1))])
        store.import_records([make_record("瑜伽垫", 2000, 2.0, 0.2, dt.date(2026, 9, 5))])
        page = store.first_page()
        assert page.items[0].monthly_searches == 2000
        store.close()

    def test_later_import_with_older_date_goes_to_history_only(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records([make_record("瑜伽垫", 2000, 2.0, 0.2, dt.date(2026, 9, 5))])
        store.import_records([make_record("瑜伽垫", 999, 9.9, 0.9, dt.date(2026, 8, 15))])
        page = store.first_page()
        assert page.items[0].monthly_searches == 2000
        assert page.items[0].collected_date == dt.date(2026, 9, 5)
        store.close()

    def test_same_date_reimport_overrides(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records([make_record("瑜伽垫", 1000, 1.0, 0.5)])
        store.import_records([make_record("瑜伽垫", 3000, 0.5, 0.1)])
        page = store.first_page()
        assert page.items[0].monthly_searches == 3000
        store.close()

    def test_history_all_kept(self, tmp_path):
        db_file = tmp_path / "kw.db"
        store = KeywordStore(str(db_file))
        store.import_records([make_record("瑜伽垫", 1000, 1.0, 0.5, dt.date(2026, 9, 1))])
        store.import_records([make_record("瑜伽垫", 2000, 2.0, 0.2, dt.date(2026, 9, 5))])
        store.import_records([make_record("瑜伽垫", 999, 9.9, 0.9, dt.date(2026, 8, 15))])
        count = store._conn.execute("SELECT COUNT(*) FROM collection_history").fetchone()[0]
        assert count == 3
        store.close()


class TestPagination:
    def test_sorted_by_score_then_phrase(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records(
            [
                make_record("香蕉", 100, 1.0, 0.5),
                make_record("苹果", 100, 1.0, 0.5),  # 同分，按短语升序
                make_record("西瓜", 100000, 0.1, 0.1),
            ]
        )
        page = store.first_page()
        phrases = [item.phrase for item in page.items]
        assert phrases == ["西瓜", "苹果", "香蕉"]
        store.close()

    def test_default_page_size_is_50(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records(
            [make_record(f"词{i:03d}", i * 10, 1.0, 0.5) for i in range(120)]
        )
        page = store.first_page()
        assert len(page.items) == 50
        assert page.cursor is not None
        store.close()

    def test_full_pagination_covers_all_exactly_once(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        records = [make_record(f"词{i:03d}", i * 137, 0.5, 0.4) for i in range(123)]
        store.import_records(records)
        items = collect_all_pages(store, page_size=50)
        phrases = [item.phrase for item in items]
        assert len(phrases) == 123
        assert len(set(phrases)) == 123
        scores = [item.score for item in items]
        assert scores == sorted(scores, reverse=True)
        store.close()

    def test_invalid_cursor_rejected(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records([make_record("瑜伽垫", 1000, 1.0, 0.5)])
        with pytest.raises(ValueError):
            store.next_page("not-a-valid-cursor")
        store.close()


class TestSnapshotConsistency:
    """验收场景：边翻页边导入，翻页结果必须等于取第一页那一刻的列表。"""

    def test_pagination_isolated_from_concurrent_imports(self, tmp_path):
        store = KeywordStore(str(tmp_path / "kw.db"))

        # 初始数据：120 个词，搜索量拉开梯度使分数分布均匀。
        initial = [
            make_record(f"关键词{i:03d}", (i + 1) * 500, 0.4 + (i % 7) * 0.3, (i % 10) / 10)
            for i in range(120)
        ]
        store.import_records(initial)

        later = dt.date(2026, 9, 20)
        earlier = dt.date(2026, 8, 1)
        imports_during_pagination = {
            1: [
                # 还没翻到的词分数暴涨，跳进已翻过的头部区域
                make_record("关键词119", 5_000_000, 0.01, 0.0, later),
                # 已翻过的词分数暴跌
                make_record("关键词000", 1, 99.0, 1.0, later),
                # 全新词，高分
                make_record("全新词A", 900_000, 0.05, 0.05, later),
            ],
            2: [
                # 补录旧日期记录：只进历史，不改当前值
                make_record("关键词060", 1, 99.0, 1.0, earlier),
                # 同日期再次导入：以后导入的为准
                make_record("关键词030", 123, 4.2, 0.9, BASE_DATE),
                # 全新词，低分
                make_record("全新词B", 10, 5.0, 0.95, later),
            ],
        }

        items = collect_all_pages(store, page_size=50, imports=imports_during_pagination)

        expected = expected_list(initial)
        assert len(items) == len(expected) == 120
        for item, (score, phrase, record) in zip(items, expected):
            assert item.phrase == phrase
            assert item.score == score
            assert item.monthly_searches == record.monthly_searches
            assert item.avg_cpc == record.avg_cpc
            assert item.competition == record.competition
            assert item.collected_date == record.collected_date

        # 翻页期间导入的数据一律不出现
        phrases = {item.phrase for item in items}
        assert "全新词A" not in phrases
        assert "全新词B" not in phrases
        store.close()

    def test_new_first_page_sees_imported_data(self, tmp_path):
        """新一轮翻页（新的第一页）则按新的时刻计算。"""
        store = KeywordStore(str(tmp_path / "kw.db"))
        store.import_records([make_record("旧词", 1000, 1.0, 0.5)])
        first = store.first_page()
        store.import_records([make_record("新词", 500_000, 0.1, 0.1, dt.date(2026, 9, 10))])
        assert [i.phrase for i in first.items] == ["旧词"]
        second = store.first_page()
        assert [i.phrase for i in second.items] == ["新词", "旧词"]
        store.close()
