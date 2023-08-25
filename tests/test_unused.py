import unittest

from index_advisor.analysis import DROP, KEEP

from .helpers import analyse, by_name, ix


class UnusedIndexTest(unittest.TestCase):
    def test_index_that_is_written_but_never_read_is_a_drop_candidate(self):
        recs = by_name(analyse([ix("IX_Unused", ["A"], reads=0, updates=5000)]))
        self.assertEqual(recs["IX_Unused"].action, DROP)
        self.assertIn("no reads", recs["IX_Unused"].reasons[0])
        self.assertIn("5,000 updates", recs["IX_Unused"].reasons[0])

    def test_index_with_reads_is_kept(self):
        recs = by_name(analyse([ix("IX_Used", ["A"], reads=120, updates=5000)]))
        self.assertEqual(recs["IX_Used"].action, KEEP)
        self.assertEqual(recs["IX_Used"].reasons, ["120 reads, 5,000 updates"])

    def test_counts(self):
        result = analyse([ix("IX_A", ["A"], reads=1, updates=1), ix("IX_B", ["B"], updates=9)])
        self.assertEqual(result.counts(), {"keep": 1, "drop": 1, "consolidate": 0, "review": 0})
