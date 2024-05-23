import json
import unittest

from index_advisor.analysis import Report, analyse_database
from index_advisor.config import Config
from index_advisor.queries import fetch_indexes, fetch_server_info
from index_advisor.report import render, render_markdown, render_text

from .fakes import connection_from_fixture


def build_report(fixture="sales_long"):
    conn = connection_from_fixture(fixture)
    server = fetch_server_info(conn)
    dbs = [analyse_database(name, fetch_indexes(conn, name), server, Config()) for name in ("HR", "Sales")]
    return Report(server, dbs)


class TextReportTest(unittest.TestCase):
    def setUp(self):
        self.text = render_text(build_report())

    def test_header_has_start_time(self):
        self.assertIn("index-advisor report for SQLPROD01", self.text)
        self.assertIn("SQL Server started 2023-04-21 04:00 (80.2 days ago)", self.text)

    def test_database_summary_line(self):
        self.assertIn("Database HR: 3 indexes analysed - 0 drop, 0 consolidate, 0 review, 3 keep", self.text)
        self.assertIn("Database Sales: 15 indexes analysed - 3 drop, 1 consolidate, 2 review, 9 keep", self.text)

    def test_drop_candidates_come_first_with_reasons(self):
        sales = self.text.split("Database Sales")[1]
        self.assertLess(sales.index("DROP"), sales.index("CONSOLIDATE"))
        self.assertLess(sales.index("CONSOLIDATE"), sales.index("REVIEW"))
        self.assertIn("DROP        dbo.Orders.IX_Orders_Date_Copy (39.1 MB)", self.text)
        self.assertIn("      - exact duplicate of IX_Orders_Date (same keys, includes and filter)", self.text)

    def test_keep_recommendations_are_hidden_by_default(self):
        self.assertNotIn("PK_Orders", self.text)
        self.assertIn("PK_Orders", render_text(build_report(), show_keep=True))

    def test_short_uptime_warning_is_shown(self):
        text = render_text(build_report("sales_short"))
        self.assertIn("  WARNING: SQL Server started on 2023-06-28 04:00", text)

    def test_unreadable_database_is_listed(self):
        report = build_report()
        report.errors.append(("Broken", "permission denied"))
        self.assertIn("Database Broken could not be read: permission denied", render_text(report))

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            render(build_report(), "xml")


class JsonReportTest(unittest.TestCase):
    def test_structure(self):
        doc = json.loads(render(build_report(), "json"))
        self.assertEqual(doc["server"]["name"], "SQLPROD01")
        self.assertEqual(doc["server"]["started"], "2023-04-21T04:00:00")
        self.assertEqual(doc["server"]["uptime_days"], 80.2)
        self.assertEqual([d["name"] for d in doc["databases"]], ["HR", "Sales"])
        self.assertEqual(doc["totals"]["by_action"]["drop"], 3)
        self.assertEqual(doc["errors"], [])

    def test_all_recommendations_are_included_and_worst_first(self):
        sales = json.loads(render(build_report(), "json"))["databases"][1]
        self.assertEqual(len(sales["recommendations"]), 15)
        self.assertEqual(sales["recommendations"][0]["action"], "drop")
        self.assertEqual(sales["recommendations"][-1]["action"], "keep")
        first = sales["recommendations"][0]
        self.assertEqual(set(first), {"schema", "table", "index", "index_id", "type", "action", "reasons",
                                      "related", "reads", "updates", "size_mb", "last_read"})

    def test_errors_are_reported(self):
        report = build_report()
        report.errors.append(("Broken", "denied"))
        doc = json.loads(render(report, "json"))
        self.assertEqual(doc["errors"], [{"database": "Broken", "message": "denied"}])


class MarkdownReportTest(unittest.TestCase):
    def setUp(self):
        self.text = render(build_report(), "markdown")

    def test_headings_and_summary(self):
        self.assertTrue(self.text.startswith("# Index review: SQLPROD01\n"))
        self.assertIn("## Sales", self.text)
        self.assertIn("15 indexes analysed: 3 drop, 1 consolidate, 2 review, 9 keep.", self.text)

    def test_table_row(self):
        self.assertIn("| drop | `dbo.Orders.IX_Orders_Date_Copy` | 39.1 MB | 0 | 480 | "
                      "no reads recorded, but 480 updates keep it maintained<br>exact duplicate of IX_Orders_Date "
                      "(same keys, includes and filter) |", self.text)

    def test_keep_rows_are_optional(self):
        self.assertNotIn("PK_Orders", self.text)
        self.assertIn("`dbo.Orders.PK_Orders`", render_markdown(build_report(), show_keep=True))

    def test_warning_is_a_quote(self):
        self.assertIn("> **Warning:** SQL Server started on 2023-06-28 04:00", render(build_report("sales_short"), "markdown"))

    def test_pipes_in_names_do_not_break_the_table(self):
        report = build_report()
        rec = [r for r in report.databases[1].recommendations if r.action == "drop"][0]
        rec.reasons.append("a | b")
        self.assertIn("a \\| b", render(report, "markdown"))
