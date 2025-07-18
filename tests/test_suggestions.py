import io
import json
import unittest

from index_advisor.cli import main
from index_advisor.config import parse_config
from index_advisor.missing import suggest
from index_advisor.model import MissingIndex

from .fakes import connection_from_fixture
from .helpers import ix


def request(equality, inequality=(), includes=(), table="Orders"):
    return MissingIndex("Sales", "dbo", table, list(equality), list(inequality), list(includes),
                        seeks=1000, avg_cost=10.0, avg_impact=50.0)


class ExistingIndexTest(unittest.TestCase):
    th = parse_config({}).thresholds

    def suggestions(self, indexes, *requests):
        return suggest(list(requests), self.th, "Sales", indexes)

    def test_new_index_when_nothing_matches(self):
        (s,) = self.suggestions([], request(["A", "B"]))
        self.assertIsNone(s.extends)
        self.assertEqual(s.notes, [])

    def test_existing_index_with_the_same_leading_columns_is_extended(self):
        existing = ix("IX_AB", ["B", "A"], table="Orders")
        (s,) = self.suggestions([existing], request(["A", "B"], ["C"], ["D"]))
        self.assertIs(s.extends, existing)
        self.assertEqual(s.add_columns, ["C", "D"])
        self.assertEqual(s.notes, ["IX_AB already leads with the equality columns; consider adding INCLUDE (C, D) "
                                   "to it instead of a new index"])

    def test_fully_covering_index_means_the_suggestion_is_suspect(self):
        existing = ix("IX_ABC", ["A", "B", "C"], ["D"], table="Orders")
        (s,) = self.suggestions([existing], request(["A", "B"], ["C"], ["D"]))
        self.assertEqual(s.add_columns, [])
        self.assertIn("IX_ABC already covers this request", s.notes[0])

    def test_clustered_index_covers_everything(self):
        pk = ix("PK", ["A"], table="Orders", type_desc="CLUSTERED", is_unique=True, is_primary_key=True)
        (s,) = self.suggestions([pk], request(["A"], includes=["Z"]))
        self.assertEqual(s.add_columns, [])

    def test_other_tables_and_disabled_indexes_do_not_match(self):
        others = [ix("IX_X", ["A"], table="Other"), ix("IX_Off", ["A"], table="Orders", is_disabled=True)]
        (s,) = self.suggestions(others, request(["A"]))
        self.assertIsNone(s.extends)

    def test_requests_without_equality_columns_never_match(self):
        (s,) = self.suggestions([ix("IX_A", ["A"], table="Orders")], request([], ["A"]))
        self.assertIsNone(s.extends)


class SuggestionReportTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        main(["--server", "SQLPROD01", *argv], connect=lambda a: connection_from_fixture("sales_long"), stdout=out)
        return out.getvalue()

    def test_text_section(self):
        text = self.run_cli()
        self.assertIn("  Missing index suggestions (not applied):", text)
        self.assertIn("    IX_Orders_CustomerID_Status_OrderDate ON dbo.Orders (CustomerID, Status, OrderDate) INCLUDE (Total)", text)
        self.assertIn("        score 3,991,530: 2,200 uses, average cost 18.4, average impact 98%", text)
        self.assertIn("        - also satisfies a request for (CustomerID) INCLUDE (Status, OrderDate), score 44,730", text)
        self.assertIn("    IX_Employees_Email ON dbo.Employees (Email)", text)

    def test_json(self):
        doc = json.loads(self.run_cli("--format", "json"))
        sales = [d for d in doc["databases"] if d["name"] == "Sales"][0]
        (suggestion,) = sales["suggestions"]
        self.assertEqual(suggestion["name"], "IX_Orders_CustomerID_Status_OrderDate")
        self.assertEqual(suggestion["score"], 3991530)
        self.assertIsNone(suggestion["extends"])

    def test_markdown(self):
        text = self.run_cli("--format", "markdown")
        self.assertIn("Missing index suggestions (not applied):", text)
        self.assertIn("| `IX_Orders_CustomerID_Status_OrderDate` on `dbo.Orders` | CustomerID, Status, OrderDate | Total | 3,991,530 |", text)

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
