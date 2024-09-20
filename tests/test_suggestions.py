import io
import json
import unittest

from index_advisor.cli import main
from index_advisor.config import parse_config
from index_advisor.missing import suggest
from index_advisor.queries import fetch_indexes, fetch_missing_indexes
from index_advisor.report import render

from .fakes import connection_from_fixture
from .helpers import ix


class ExistingIndexTest(unittest.TestCase):
    def suggestions(self, indexes):
        missing = fetch_missing_indexes(connection_from_fixture("sales_long"))
        return suggest(missing, parse_config({}).thresholds, "Sales", indexes)

    def test_new_index_when_nothing_matches(self):
        first = self.suggestions([])[0]
        self.assertIsNone(first.extends)
        self.assertEqual(first.notes, [])

    def test_existing_index_with_the_same_leading_columns_is_extended(self):
        existing = ix("IX_Orders_Customer", ["CustomerID"], table="Orders")
        second = [s for s in self.suggestions([existing]) if s.name == "IX_Orders_CustomerID"][0]
        self.assertIs(second.extends, existing)
        self.assertEqual(second.add_columns, ["Status", "OrderDate"])
        self.assertIn("consider adding INCLUDE (Status, OrderDate) to it instead of a new index", second.notes[0])

    def test_fully_covering_index_means_the_suggestion_is_suspect(self):
        existing = ix("IX_Orders_Customer_Date", ["CustomerID", "OrderDate"], ["Status"], table="Orders")
        second = [s for s in self.suggestions([existing]) if s.name == "IX_Orders_CustomerID"][0]
        self.assertEqual(second.add_columns, [])
        self.assertIn("already covers this request", second.notes[0])

    def test_other_tables_and_disabled_indexes_do_not_match(self):
        others = [ix("IX_X", ["CustomerID"], table="Other"), ix("IX_Off", ["CustomerID"], table="Orders", is_disabled=True)]
        self.assertTrue(all(s.extends is None for s in self.suggestions(others)))


class SuggestionReportTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        main(["--server", "SQLPROD01", *argv], connect=lambda a: connection_from_fixture("sales_long"), stdout=out)
        return out.getvalue()

    def test_text_section(self):
        text = self.run_cli()
        self.assertIn("  Missing index suggestions (not applied):", text)
        self.assertIn("    IX_Orders_CustomerID_Status_OrderDate ON dbo.Orders (CustomerID, Status, OrderDate) INCLUDE (Total)", text)
        self.assertIn("        score 3,946,800: 2,200 uses, average cost 18.4, average impact 98%", text)
        self.assertIn("    IX_Employees_Email ON dbo.Employees (Email)", text)

    def test_suggestions_against_surviving_indexes_only(self):
        # IX_Orders_Customer is a drop candidate, IX_Orders_Customer_Date stays and covers the request
        text = self.run_cli()
        self.assertIn("IX_Orders_Customer_Date already covers this request", text)

    def test_json(self):
        doc = json.loads(self.run_cli("--format", "json"))
        sales = [d for d in doc["databases"] if d["name"] == "Sales"][0]
        self.assertEqual([s["name"] for s in sales["suggestions"]],
                         ["IX_Orders_CustomerID_Status_OrderDate", "IX_Orders_CustomerID"])
        self.assertEqual(sales["suggestions"][0]["score"], 3946800)
        self.assertEqual(sales["suggestions"][1]["extends"], "IX_Orders_Customer_Date")

    def test_markdown(self):
        text = self.run_cli("--format", "markdown")
        self.assertIn("Missing index suggestions (not applied):", text)
        self.assertIn("| `IX_Orders_CustomerID_Status_OrderDate` on `dbo.Orders` | CustomerID, Status, OrderDate | Total | 3,946,800 |", text)

    def test_unreadable_missing_index_dmvs_are_reported_but_do_not_stop_the_run(self):
        class NoDmv:
            def __init__(self, conn):
                self.conn = conn

            def cursor(self):
                cur = self.conn.cursor()
                real = cur.execute

                def execute(sql, *params):
                    if "dm_db_missing_index_details" in sql:
                        raise RuntimeError("VIEW SERVER STATE permission was denied")
                    return real(sql, *params)

                cur.execute = execute
                return cur

            def close(self):
                self.conn.close()

        out = io.StringIO()
        code = main(["--server", "SQLPROD01"], connect=lambda a: NoDmv(connection_from_fixture("sales_long")), stdout=out)
        self.assertEqual(code, 4)
        self.assertIn("Database (missing-index DMVs) could not be read: VIEW SERVER STATE permission was denied", out.getvalue())
        self.assertIn("Database Sales:", out.getvalue())
