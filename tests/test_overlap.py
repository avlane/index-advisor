import unittest

from index_advisor.analysis import CONSOLIDATE, DROP, KEEP, analyse_database
from index_advisor.config import Config
from index_advisor.queries import fetch_indexes

from .fakes import connection_from_fixture
from .helpers import analyse, by_name, ix, server


class OverlapTest(unittest.TestCase):
    def test_left_prefix_that_is_covered_is_dropped(self):
        result = analyse([ix("IX_A", ["Cust"], reads=50), ix("IX_AB", ["Cust", "Date"], ["Status"], reads=900)])
        recs = by_name(result)
        self.assertEqual(recs["IX_A"].action, DROP)
        self.assertEqual(recs["IX_A"].related, ["IX_AB"])
        self.assertIn("left prefix of IX_AB, which already covers", recs["IX_A"].reasons[0])
        self.assertIn("50 reads would be served by IX_AB", recs["IX_A"].reasons[1])
        self.assertEqual(recs["IX_AB"].action, KEEP)
        self.assertIn("IX_A can be merged into this index", recs["IX_AB"].reasons[-1])

    def test_missing_included_columns_make_it_a_consolidation(self):
        result = analyse([ix("IX_A", ["Prod"], ["Qty", "Price"], reads=900), ix("IX_AB", ["Prod", "Date"], ["Price"], reads=10)])
        recs = by_name(result)
        self.assertEqual(recs["IX_A"].action, CONSOLIDATE)
        self.assertIn("adding INCLUDE (Qty) to IX_AB", recs["IX_A"].reasons[0])
        self.assertEqual(recs["IX_AB"].merge_includes, ["Qty"])

    def test_included_columns_of_the_source_that_are_keys_of_the_target_count_as_covered(self):
        result = analyse([ix("IX_A", ["Cust"], ["Date"]), ix("IX_AB", ["Cust", "Date"])])
        self.assertEqual(by_name(result)["IX_A"].action, DROP)

    def test_direction_and_filter_must_match(self):
        result = analyse([
            ix("IX_1", ["A"], reads=1), ix("IX_2", ["A DESC", "B"], reads=1),
            ix("IX_3", ["C"], reads=1), ix("IX_4", ["C", "D"], reads=1, filter_definition="([x]=(1))"),
        ])
        self.assertEqual({r.action for r in by_name(result).values()}, {KEEP})

    def test_other_tables_are_ignored(self):
        result = analyse([ix("IX_1", ["A"], reads=1), ix("IX_2", ["A", "B"], reads=1, table="Other")])
        self.assertEqual({r.action for r in by_name(result).values()}, {KEEP})

    def test_unique_and_clustered_prefixes_are_never_dropped(self):
        result = analyse([ix("UQ_A", ["A"], is_unique=True), ix("IX_AB", ["A", "B"])])
        self.assertEqual(by_name(result)["UQ_A"].action, KEEP)

    def test_a_prefix_of_the_clustered_key_is_redundant(self):
        result = analyse([
            ix("PK", ["A", "B"], type_desc="CLUSTERED", is_unique=True, is_primary_key=True),
            ix("IX_A", ["A"], ["Whatever"], reads=3),
        ])
        recs = by_name(result)
        self.assertEqual(recs["IX_A"].action, DROP)
        self.assertEqual(recs["IX_A"].related, ["PK"])

    def test_same_keys_different_includes_merge_into_the_more_used(self):
        result = analyse([ix("IX_Few", ["K"], ["x"], reads=5, index_id=2), ix("IX_Many", ["K"], ["y"], reads=500, index_id=3)])
        recs = by_name(result)
        self.assertEqual(recs["IX_Few"].action, CONSOLIDATE)
        self.assertIn("same keys as IX_Many", recs["IX_Few"].reasons[0])
        self.assertEqual(recs["IX_Many"].merge_includes, ["x"])
        self.assertEqual(recs["IX_Many"].action, KEEP)

    def test_chains_resolve_to_the_widest_index(self):
        result = analyse([ix("IX_A", ["A"], ["x"], reads=1), ix("IX_AB", ["A", "B"], reads=1), ix("IX_ABC", ["A", "B", "C"], ["x"], reads=1)])
        recs = by_name(result)
        self.assertEqual(recs["IX_A"].action, DROP)
        self.assertEqual(recs["IX_AB"].action, DROP)
        self.assertEqual(recs["IX_A"].related, ["IX_ABC"])
        self.assertEqual(recs["IX_AB"].related, ["IX_ABC"])
        self.assertEqual(recs["IX_ABC"].action, KEEP)

    def test_dropped_indexes_are_not_merge_targets(self):
        result = analyse([ix("IX_A", ["A"], reads=1), ix("IX_AB", ["A", "B"], reads=0, updates=5000)])
        recs = by_name(result)
        self.assertEqual(recs["IX_AB"].action, DROP)  # unused
        self.assertEqual(recs["IX_A"].action, KEEP)

    def test_fixture(self):
        indexes = fetch_indexes(connection_from_fixture("sales_long"), "Sales")
        recs = by_name(analyse_database("Sales", indexes, server(80), Config()))
        self.assertEqual(recs["IX_Orders_Customer"].action, DROP)
        self.assertEqual(recs["IX_Orders_Customer"].related, ["IX_Orders_Customer_Date"])
        self.assertEqual(recs["IX_OrderLines_Product"].action, CONSOLIDATE)
        self.assertEqual(recs["IX_OrderLines_Product_Price"].merge_includes, ["Quantity"])
