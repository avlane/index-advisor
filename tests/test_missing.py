import unittest

from index_advisor.config import parse_config
from index_advisor.missing import suggest
from index_advisor.model import MissingIndex
from index_advisor.queries import fetch_missing_indexes

from .fakes import connection_from_fixture


def entry(equality, inequality=(), includes=(), table="Orders", seeks=1000, cost=10.0, impact=50.0):
    return MissingIndex("Sales", "dbo", table, list(equality), list(inequality), list(includes),
                        seeks=seeks, avg_cost=cost, avg_impact=impact)


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
        self.assertEqual([s.name for s in found], ["IX_Orders_CustomerID_Status_OrderDate"])

    def test_keys_are_equality_then_inequality(self):
        first = suggest(self.missing, self.th, "Sales")[0]
        self.assertEqual(first.keys, ["CustomerID", "Status", "OrderDate"])
        self.assertEqual(first.includes, ["Total"])

    def test_threshold_is_configurable(self):
        th = parse_config({"thresholds": {"min_missing_score": 100}}).thresholds
        self.assertEqual([s.missing.table for s in suggest(self.missing, th, "Sales")], ["Orders", "Customers"])

    def test_database_filter_is_case_insensitive(self):
        self.assertEqual([s.missing.table for s in suggest(self.missing, self.th, "hr")], ["Employees"])


class MergeSimilarTest(unittest.TestCase):
    th = parse_config({}).thresholds

    def test_left_prefix_request_is_folded_into_the_larger_one(self):
        small = entry(["A"], includes=["X"], seeks=500)
        large = entry(["A", "B"], includes=["Y"], seeks=2000)
        (merged,) = suggest([small, large], self.th)
        self.assertEqual(merged.keys, ["A", "B"])
        self.assertEqual(merged.includes, ["Y", "X"])
        self.assertEqual(merged.merged, 1)
        self.assertAlmostEqual(merged.score, small.score + large.score)
        self.assertEqual(merged.notes, ["also satisfies a request for (A) INCLUDE (X), score 250,000"])

    def test_unrelated_requests_stay_separate(self):
        found = suggest([entry(["A"]), entry(["B"]), entry(["A"], table="Other")], self.th)
        self.assertEqual(len(found), 3)

    def test_different_key_order_is_not_a_prefix(self):
        found = suggest([entry(["A", "B"]), entry(["B", "A"])], self.th)
        self.assertEqual(len(found), 2)

    def test_columns_already_in_the_larger_index_are_not_repeated(self):
        (merged,) = suggest([entry(["A"], includes=["B"]), entry(["A", "B"])], self.th)
        self.assertEqual(merged.includes, [])
