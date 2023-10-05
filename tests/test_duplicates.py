import unittest

from index_advisor.analysis import DROP, KEEP, analyse_database
from index_advisor.config import Config
from index_advisor.queries import fetch_indexes

from .fakes import connection_from_fixture
from .helpers import analyse, by_name, ix, server


class DuplicateIndexTest(unittest.TestCase):
    def test_exact_duplicates_keep_the_most_used(self):
        result = analyse([ix("IX_A", ["Col"], reads=10, updates=50), ix("IX_B", ["Col"], reads=900, updates=50)])
        recs = by_name(result)
        self.assertEqual(recs["IX_A"].action, DROP)
        self.assertEqual(recs["IX_A"].related, ["IX_B"])
        self.assertIn("exact duplicate of IX_B", recs["IX_A"].reasons[0])
        self.assertIn("10 reads can be served by IX_B", recs["IX_A"].reasons[1])
        self.assertEqual(recs["IX_B"].action, KEEP)
        self.assertIn("IX_A is an exact duplicate", recs["IX_B"].reasons[-1])

    def test_ties_keep_the_oldest_index(self):
        recs = by_name(analyse([ix("IX_New", ["C"], reads=5, index_id=9), ix("IX_Old", ["C"], reads=5, index_id=3)]))
        self.assertEqual(recs["IX_Old"].action, KEEP)
        self.assertEqual(recs["IX_New"].action, DROP)

    def test_a_unique_index_is_kept_over_its_duplicate(self):
        recs = by_name(analyse([ix("IX_Plain", ["Email"], reads=1000), ix("UQ_Email", ["Email"], is_unique=True)]))
        self.assertEqual(recs["UQ_Email"].action, KEEP)
        self.assertEqual(recs["IX_Plain"].action, DROP)

    def test_two_protected_duplicates_are_both_kept(self):
        recs = by_name(analyse([ix("UQ_1", ["Email"], is_unique=True), ix("UQ_2", ["Email"], is_unique=True)]))
        self.assertEqual({r.action for r in recs.values()}, {KEEP})

    def test_includes_are_compared_as_a_set(self):
        recs = by_name(analyse([ix("IX_A", ["K"], ["x", "y"], reads=5), ix("IX_B", ["K"], ["Y", "X"], reads=1)]))
        self.assertEqual(recs["IX_B"].action, DROP)

    def test_different_includes_keys_direction_filter_or_table_are_not_duplicates(self):
        result = analyse([
            ix("IX_1", ["K"], ["x"], reads=1),
            ix("IX_3", ["K DESC"], reads=1), ix("IX_4", ["K"], reads=1, filter_definition="([a]=(1))"),
            ix("IX_5", ["K"], reads=1, table="Other"),
        ])
        self.assertEqual({r.action for r in by_name(result).values()}, {KEEP})

    def test_disabled_indexes_are_not_duplicates(self):
        recs = by_name(analyse([ix("IX_A", ["K"], reads=1), ix("IX_B", ["K"], is_disabled=True)]))
        self.assertEqual(recs["IX_A"].action, KEEP)

    def test_duplicate_wins_over_a_downgraded_unused_review(self):
        result = analyse([ix("IX_A", ["K"], reads=0, updates=900), ix("IX_B", ["K"], reads=0, updates=900)],
                         uptime_days=3)
        self.assertEqual(by_name(result)["IX_B"].action, DROP)

    def test_fixture(self):
        indexes = fetch_indexes(connection_from_fixture("sales_long"), "Sales")
        recs = by_name(analyse_database("Sales", indexes, server(80), Config()))
        self.assertEqual(recs["IX_Orders_Date"].action, DROP)  # unused
        self.assertEqual(recs["IX_Orders_Date_Copy"].action, DROP)
        self.assertEqual(recs["IX_Orders_Date_Copy"].related, ["IX_Orders_Date"])
        self.assertEqual(sum(1 for r in recs.values() if "exact duplicate" in " ".join(r.reasons)), 2)
