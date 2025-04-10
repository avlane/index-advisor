import unittest

from index_advisor.analysis import DROP, REVIEW
from index_advisor.config import parse_config

from .helpers import analyse, by_name, ix


class StatsResetTest(unittest.TestCase):
    def indexes(self):
        return [ix("IX_Unused", ["A"], reads=0, updates=5000)]

    def test_short_uptime_downgrades_drop_to_review(self):
        result = analyse(self.indexes(), uptime_days=5)
        rec = by_name(result)["IX_Unused"]
        self.assertEqual(rec.action, REVIEW)
        self.assertIn("only covers 5.0 days", rec.reasons[0])

    def test_short_uptime_adds_a_warning_with_the_start_time(self):
        (warning,) = analyse(self.indexes(), uptime_days=5).warnings
        self.assertIn("SQL Server started on 2023-07-05 10:00", warning)
        self.assertIn("5.0 days ago", warning)
        self.assertIn("30 days", warning)

    def test_long_uptime_has_no_warning_and_allows_drops(self):
        result = analyse(self.indexes(), uptime_days=45)
        self.assertEqual(result.warnings, [])
        self.assertEqual(by_name(result)["IX_Unused"].action, DROP)

    def test_threshold_is_configurable(self):
        cfg = parse_config({"thresholds": {"min_uptime_days": 3}})
        result = analyse(self.indexes(), uptime_days=5, config=cfg)
        self.assertEqual(by_name(result)["IX_Unused"].action, DROP)
        self.assertEqual(result.warnings, [])

    def test_exactly_at_the_threshold_is_trusted(self):
        self.assertEqual(by_name(analyse(self.indexes(), uptime_days=30))["IX_Unused"].action, DROP)
