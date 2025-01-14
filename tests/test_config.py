import os
import tempfile
import unittest

from index_advisor.config import Config, ConfigError, load_config, parse_config


class ParseConfigTest(unittest.TestCase):
    def test_defaults(self):
        th = parse_config({}).thresholds
        self.assertEqual((th.min_uptime_days, th.min_updates, th.low_read_ratio), (30.0, 1000, 0.01))

    def test_overrides(self):
        th = parse_config({"thresholds": {"min_uptime_days": 14, "low_read_ratio": 0.05}}).thresholds
        self.assertEqual((th.min_uptime_days, th.min_updates, th.low_read_ratio), (14, 1000, 0.05))

    def test_unknown_keys_are_rejected(self):
        for bad in ({"threshold": {}}, {"thresholds": {"min_uptime": 3}}):
            with self.assertRaises(ConfigError):
                parse_config(bad)

    def test_bad_values_are_rejected(self):
        for bad in (-1, "30", True):
            with self.assertRaises(ConfigError):
                parse_config({"thresholds": {"min_uptime_days": bad}})
        with self.assertRaises(ConfigError):
            parse_config({"thresholds": {"min_updates": 1.5}})


class LoadConfigTest(unittest.TestCase):
    def write(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "advisor.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_load(self):
        cfg = load_config(self.write("[thresholds]\nmin_uptime_days = 7\n"))
        self.assertEqual(cfg.thresholds.min_uptime_days, 7)

    def test_invalid_toml(self):
        with self.assertRaises(ConfigError):
            load_config(self.write("[thresholds"))

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config("/nonexistent/advisor.toml")

    def test_default_config_object(self):
        self.assertEqual(Config().thresholds.min_updates, 1000)


class ExclusionTest(unittest.TestCase):
    def cfg(self):
        return parse_config({
            "exclude": {"databases": ["ReportServer*", "SSISDB"], "tables": ["dbo.Staging_*", "audit.*"]},
            "keep": {"indexes": ["Sales.dbo.Orders.IX_Orders_Customer", "*.IX_Reporting_*"]},
        })

    def test_database_patterns(self):
        cfg = self.cfg()
        self.assertTrue(cfg.database_excluded("reportservertempdb"))
        self.assertTrue(cfg.database_excluded("SSISDB"))
        self.assertFalse(cfg.database_excluded("Sales"))

    def test_table_patterns(self):
        cfg = self.cfg()
        self.assertTrue(cfg.table_excluded("dbo", "Staging_Orders"))
        self.assertTrue(cfg.table_excluded("audit", "Anything"))
        self.assertFalse(cfg.table_excluded("dbo", "Orders"))

    def test_keep_patterns_match_the_full_index_name(self):
        from .helpers import ix

        cfg = self.cfg()
        self.assertTrue(cfg.index_kept(ix("IX_Orders_Customer", ["A"])))
        self.assertTrue(cfg.index_kept(ix("IX_Reporting_Month", ["A"], table="Other")))
        self.assertFalse(cfg.index_kept(ix("IX_Other", ["A"])))

    def test_bad_sections(self):
        for bad in ({"exclude": {"databases": "Sales"}}, {"exclude": {"views": []}}, {"keep": []},
                    {"keep": {"indexes": [""]}}):
            with self.assertRaises(ConfigError):
                parse_config(bad)

    def test_defaults_exclude_nothing(self):
        cfg = Config()
        self.assertFalse(cfg.database_excluded("Sales"))
        self.assertFalse(cfg.table_excluded("dbo", "Orders"))
