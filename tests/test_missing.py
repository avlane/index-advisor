import unittest

from index_advisor.config import parse_config
from index_advisor.missing import suggest
from index_advisor.queries import fetch_missing_indexes

from .fakes import connection_from_fixture


class FetchMissingTest(unittest.TestCase):
    def setUp(self):
        self.missing = fetch_missing_indexes(connection_from_fixture("sales_long"))

    def test_rows_are_mapped(self):
        self.assertEqual(len(self.missing), 4)
        first = self.missing[0]
        self.assertEqual((first.database, first.schema, first.table), ("Sales", "dbo", "Orders"))
        self.assertEqual(first.equality, ["CustomerID", "Status"])
        self.assertEqual(first.inequality, ["OrderDate"])
        self.assertEqual(first.includes, ["Total"])
        self.assertEqual((first.seeks, first.scans), (2200, 0))
        self.assertIsNotNone(first.last_use)

    def test_empty_column_lists(self):
        customers = [m for m in self.missing if m.table == "Customers"][0]
        self.assertEqual((customers.inequality, customers.includes), ([], []))

    def test_score_is_cost_times_impact_times_uses(self):
        self.assertAlmostEqual(self.missing[0].score, 18.4 * 97.5 * 2200)


class SuggestTest(unittest.TestCase):
    def setUp(self):
        self.missing = fetch_missing_indexes(connection_from_fixture("sales_long"))
        self.th = parse_config({}).thresholds

    def test_best_first_and_below_threshold_dropped(self):
        found = suggest(self.missing, self.th, "Sales")
        self.assertEqual([s.name for s in found], ["IX_Orders_CustomerID_Status_OrderDate", "IX_Orders_CustomerID"])

    def test_keys_are_equality_then_inequality(self):
        first = suggest(self.missing, self.th, "Sales")[0]
        self.assertEqual(first.keys, ["CustomerID", "Status", "OrderDate"])
        self.assertEqual(first.includes, ["Total"])

    def test_columns_that_are_keys_are_not_repeated_as_includes(self):
        second = suggest(self.missing, self.th, "Sales")[1]
        self.assertEqual(second.keys, ["CustomerID"])
        self.assertEqual(second.includes, ["Status", "OrderDate"])

    def test_threshold_is_configurable(self):
        th = parse_config({"thresholds": {"min_missing_score": 100}}).thresholds
        self.assertEqual(len(suggest(self.missing, th, "Sales")), 3)

    def test_database_filter_is_case_insensitive(self):
        self.assertEqual([s.missing.table for s in suggest(self.missing, self.th, "hr")], ["Employees"])
