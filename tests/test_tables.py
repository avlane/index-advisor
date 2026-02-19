import json
import unittest

from index_advisor.analysis import analyse_database
from index_advisor.config import Config
from index_advisor.report import render

from .helpers import analyse, ix, server
from .test_report import build_report


class TableSummaryTest(unittest.TestCase):
    def test_summary_orders_tables_by_reclaimable_space(self):
        result = analyse([
            ix("IX_1", ["A"], table="Small", updates=900, used_pages=100),
            ix("IX_2", ["A"], table="Big", updates=900, used_pages=10000),
            ix("IX_3", ["B"], table="Big", updates=900, used_pages=10000),
            ix("IX_4", ["C"], table="Idle", reads=5),
        ])
        self.assertEqual([(t, d, c) for t, d, c, mb in result.table_summary()],
                         [("dbo.Big", 2, 0), ("dbo.Small", 1, 0)])
        self.assertAlmostEqual(result.table_summary()[0][3], 2 * 10000 * 8 / 1024)

    def test_consolidations_are_counted_without_space(self):
        result = analyse([ix("IX_A", ["A"], ["x"], reads=5), ix("IX_AB", ["A", "B"], reads=5)])
        self.assertEqual(result.table_summary(), [("dbo.Orders", 0, 1, 0.0)])

    def test_text_json_and_markdown(self):
        report = build_report()
        text = render(report, "text")
        self.assertIn("  By table:\n    dbo.Orders: 3 drop, 0 consolidate, 118.8 MB\n    dbo.OrderLines: 0 drop, 1 consolidate, 0.0 MB", text)
        doc = json.loads(render(report, "json"))
        self.assertEqual(doc["databases"][1]["tables"][0], {"table": "dbo.Orders", "drop": 3, "consolidate": 0, "drop_size_mb": 118.8})
        self.assertIn("| `dbo.Orders` | 3 | 0 | 118.8 MB |", render(report, "markdown"))

    def test_databases_without_changes_have_no_table_section(self):
        self.assertNotIn("By table", render(build_report(), "text").split("Database Sales")[0])
