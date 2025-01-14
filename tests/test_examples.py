import os
import unittest

from index_advisor.config import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ExampleConfigTest(unittest.TestCase):
    def test_example_parses(self):
        cfg = load_config(os.path.join(ROOT, "examples", "advisor.toml"))
        self.assertEqual(cfg.thresholds.min_uptime_days, 30)
        self.assertTrue(cfg.database_excluded("ReportServer"))
        self.assertTrue(cfg.table_excluded("audit", "Log"))
        self.assertEqual(len(cfg.keep_indexes), 2)
