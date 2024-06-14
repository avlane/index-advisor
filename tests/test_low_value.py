import unittest

from index_advisor.analysis import KEEP, REVIEW
from index_advisor.config import parse_config

from .helpers import analyse, by_name, ix


class LowValueTest(unittest.TestCase):
    def test_few_reads_against_many_writes(self):
        rec = by_name(analyse([ix("IX_Rare", ["A"], reads=12, updates=9000)]))["IX_Rare"]
        self.assertEqual(rec.action, REVIEW)
        self.assertEqual(rec.reasons, ["reads are only 0.13% of writes (12 reads, 9,000 updates); "
                                       "it may cost more than it saves"])

    def test_ratio_above_the_threshold_is_kept(self):
        self.assertEqual(by_name(analyse([ix("IX_A", ["A"], reads=200, updates=9000)]))["IX_A"].action, KEEP)

    def test_few_writes_are_not_worth_a_review(self):
        self.assertEqual(by_name(analyse([ix("IX_A", ["A"], reads=1, updates=500)]))["IX_A"].action, KEEP)

    def test_thresholds_come_from_the_config(self):
        cfg = parse_config({"thresholds": {"low_read_ratio": 0.5, "min_updates": 100}})
        self.assertEqual(by_name(analyse([ix("IX_A", ["A"], reads=100, updates=500)], config=cfg))["IX_A"].action, REVIEW)

    def test_unused_indexes_keep_their_stronger_action(self):
        from index_advisor.analysis import DROP

        self.assertEqual(by_name(analyse([ix("IX_A", ["A"], reads=0, updates=9000)]))["IX_A"].action, DROP)
