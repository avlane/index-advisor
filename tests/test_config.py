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
