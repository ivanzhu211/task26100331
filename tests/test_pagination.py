"""关键词库翻页一致性测试。"""

from __future__ import annotations

import random
import unittest

from keywordlib import CollectionRecord, KeywordStore
from keywordlib.scoring import opportunity_score


def expected_list(records: list[CollectionRecord]) -> list[tuple]:
    """独立实现：由采集记录算出 (phrase, score, volume, cpc, competition, date) 排名列表。"""
    current: dict[str, CollectionRecord] = {}
    for rec in records:  # 按导入顺序，同日期后导入覆盖
        old = current.get(rec.phrase)
        if old is None or rec.collected_date >= old.collected_date:
            current[rec.phrase] = rec
    rows = [
        (
            rec.phrase,
            opportunity_score(rec.monthly_volume, rec.avg_cpc, rec.competition),
            rec.monthly_volume,
            rec.avg_cpc,
            rec.competition,
            rec.collected_date,
        )
        for rec in current.values()
    ]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows


def page_tuples(items) -> list[tuple]:
    return [
        (
            item.phrase,
            item.opportunity_score,
            item.monthly_volume,
            item.avg_cpc,
            item.competition,
            item.collected_date,
        )
        for item in items
    ]


def collect_all_pages(store: KeywordStore, page_size: int, on_page=None) -> list[tuple]:
    """翻完整个列表；on_page(已翻页数) 可在翻页间隙导入数据。"""
    result = []
    page = store.first_page(page_size)
    page_no = 1
    while True:
        result.extend(page_tuples(page.items))
        if on_page is not None:
            on_page(page_no)
        if page.next_cursor is None:
            return result
        page = store.next_page(page.next_cursor)
        page_no += 1


class ScoringTest(unittest.TestCase):
    def test_formula(self):
        # 40*min(1,log10(v+1)/6) + 35*(1-c) + 25*(1/(1+cpc))
        self.assertEqual(opportunity_score(999999, 1.0, 0.5), 70.0)
        self.assertEqual(opportunity_score(0, 0.0, 0.0), 60.0)
        self.assertEqual(opportunity_score(0, 0.0, 1.0), 25.0)

    def test_volume_capped_at_six_digits(self):
        self.assertEqual(
            opportunity_score(999999, 1.0, 0.0),
            opportunity_score(10**12, 1.0, 0.0),
        )


class CurrentValueTest(unittest.TestCase):
    def setUp(self):
        self.store = KeywordStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_backfilled_older_date_goes_to_history_only(self):
        self.store.import_records(
            [CollectionRecord("跑鞋 男", 5000, 2.0, 0.4, "2026-09-20")]
        )
        self.store.import_records(
            [CollectionRecord("跑鞋 男", 100, 9.9, 0.9, "2026-09-01")]
        )
        page = self.store.first_page()
        self.assertEqual(len(page.items), 1)
        item = page.items[0]
        self.assertEqual(item.collected_date, "2026-09-20")
        self.assertEqual(item.monthly_volume, 5000)

    def test_same_date_later_import_wins(self):
        self.store.import_records(
            [CollectionRecord("瑜伽垫", 800, 1.0, 0.2, "2026-09-15")]
        )
        self.store.import_records(
            [CollectionRecord("瑜伽垫", 1200, 0.8, 0.1, "2026-09-15")]
        )
        page = self.store.first_page()
        self.assertEqual(page.items[0].monthly_volume, 1200)

    def test_newer_date_replaces_current(self):
        self.store.import_records(
            [CollectionRecord("咖啡机", 300, 3.0, 0.6, "2026-09-10")]
        )
        self.store.import_records(
            [CollectionRecord("咖啡机", 9000, 1.2, 0.3, "2026-09-25")]
        )
        page = self.store.first_page()
        self.assertEqual(page.items[0].collected_date, "2026-09-25")
        self.assertEqual(page.items[0].monthly_volume, 9000)


class OrderingTest(unittest.TestCase):
    def test_score_desc_then_phrase_asc(self):
        store = KeywordStore(":memory:")
        self.addCleanup(store.close)
        # 构造两条同分记录验证短语升序
        store.import_records(
            [
                CollectionRecord("b 词", 100, 1.0, 0.5, "2026-09-01"),
                CollectionRecord("a 词", 100, 1.0, 0.5, "2026-09-01"),
                CollectionRecord("z 高分", 900000, 0.1, 0.0, "2026-09-01"),
            ]
        )
        phrases = [item.phrase for item in store.first_page().items]
        self.assertEqual(phrases, ["z 高分", "a 词", "b 词"])


class PaginationConsistencyTest(unittest.TestCase):
    """边翻页边导入：结果必须等于取第一页那一刻的列表。"""

    def test_pagination_isolated_from_imports(self):
        rng = random.Random(20261002)
        store = KeywordStore(":memory:")
        self.addCleanup(store.close)

        # 初始数据：120 个词，页大小 25 → 5 页
        seed = [
            CollectionRecord(
                phrase=f"关键词 {i:03d}",
                monthly_volume=rng.randint(0, 2_000_000),
                avg_cpc=round(rng.uniform(0.01, 20.0), 2),
                competition=round(rng.uniform(0.0, 1.0), 3),
                collected_date="2026-09-20",
            )
            for i in range(120)
        ]
        store.import_records(seed)
        baseline = expected_list(seed)

        def mid_imports(page_no: int) -> None:
            if page_no == 1:
                # 已翻过区域的词分数变更高（往前跳）
                store.import_records(
                    [
                        CollectionRecord(baseline[0][0], 1_900_000, 0.05, 0.0, "2026-09-28"),
                        CollectionRecord(baseline[1][0], 1_800_000, 0.05, 0.0, "2026-09-28"),
                    ]
                )
            elif page_no == 2:
                # 未翻到区域的词分数变更低（往后掉）+ 新词
                store.import_records(
                    [
                        CollectionRecord(baseline[-1][0], 0, 19.9, 0.99, "2026-09-28"),
                        CollectionRecord("全新词 A", 1_500_000, 0.1, 0.05, "2026-09-28"),
                    ]
                )
            elif page_no == 3:
                # 补录旧日期记录（只进历史）+ 同日期覆盖
                store.import_records(
                    [
                        CollectionRecord(baseline[10][0], 5, 9.9, 0.9, "2026-09-01"),
                        CollectionRecord(baseline[10][0], 1_700_000, 0.1, 0.0, "2026-09-20"),
                    ]
                )
            elif page_no == 4:
                # 更多新词，分数插到各区域
                store.import_records(
                    [
                        CollectionRecord(f"全新词 B{i}", rng.randint(0, 2_000_000), 1.0, 0.5, "2026-09-29")
                        for i in range(30)
                    ]
                )

        got = collect_all_pages(store, page_size=25, on_page=mid_imports)

        self.assertEqual(got, baseline)
        phrases = [row[0] for row in got]
        self.assertEqual(len(phrases), len(set(phrases)), "翻页结果出现重复词")
        self.assertNotIn("全新词 A", phrases)
        self.assertFalse(any(p.startswith("全新词 B") for p in phrases))

    def test_default_page_size_is_50(self):
        store = KeywordStore(":memory:")
        self.addCleanup(store.close)
        store.import_records(
            [
                CollectionRecord(f"词 {i:03d}", 100 * (i + 1), 1.0, 0.5, "2026-09-20")
                for i in range(120)
            ]
        )
        page = store.first_page()
        self.assertEqual(len(page.items), 50)
        self.assertIsNotNone(page.next_cursor)

    def test_last_page_cursor_is_none_and_counts_exact(self):
        store = KeywordStore(":memory:")
        self.addCleanup(store.close)
        records = [
            CollectionRecord(f"词 {i:03d}", 100 * (i + 1), 1.0, 0.5, "2026-09-20")
            for i in range(120)
        ]
        store.import_records(records)
        got = collect_all_pages(store, page_size=50)
        self.assertEqual(got, expected_list(records))
        self.assertEqual(len(got), 120)

    def test_empty_library(self):
        store = KeywordStore(":memory:")
        self.addCleanup(store.close)
        page = store.first_page()
        self.assertEqual(page.items, [])
        self.assertIsNone(page.next_cursor)

    def test_invalid_cursor_rejected(self):
        store = KeywordStore(":memory:")
        self.addCleanup(store.close)
        with self.assertRaises(ValueError):
            store.next_page("not-a-cursor")

    def test_persistent_sqlite_file(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            store = KeywordStore(path)
            store.import_records(
                [CollectionRecord("持久化词", 100, 1.0, 0.5, "2026-09-20")]
            )
            first = store.first_page(page_size=10)
            store.close()
            # 重新打开文件后凭据仍然可用
            store2 = KeywordStore(path)
            self.addCleanup(store2.close)
            page = store2.next_page(first.next_cursor) if first.next_cursor else None
            self.assertIsNone(page)  # 只有 1 条，第一页即最后一页
            again = store2.first_page()
            self.assertEqual(again.items[0].phrase, "持久化词")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
