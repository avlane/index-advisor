import io
import unittest

from index_advisor.analysis import DROP, KEEP
from index_advisor.cli import main
from index_advisor.config import ConfigError, parse_config

from .fakes import connection_from_fixture
from .helpers import analyse, by_name, ix


class MinSizeTest(unittest.TestCase):
    def indexes(self):
        return [ix("IX_Small", ["A"], updates=900, used_pages=50), ix("IX_Big", ["B"], updates=900, used_pages=5000)]

    def test_default_has_no_minimum(self):
        self.assertEqual(by_name(analyse(self.indexes()))["IX_Small"].action, DROP)

    def test_small_indexes_are_left_alone(self):
        cfg = parse_config({"thresholds": {"min_size_mb": 10}})
        recs = by_name(analyse(self.indexes(), config=cfg))
        self.assertEqual(recs["IX_Small"].action, KEEP)
        self.assertTrue(recs["IX_Small"].protected)
        self.assertIn("only 0.4 MB, below min_size_mb (10)", recs["IX_Small"].reasons[0])
        self.assertEqual(recs["IX_Big"].action, DROP)

    def test_negative_value_is_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config({"thresholds": {"min_size_mb": -1}})

    def test_command_line_option(self):
        def run(*argv):
            out = io.StringIO()
            main(["--server", "SQLPROD01", *argv], connect=lambda a: connection_from_fixture("sales_long"), stdout=out)
            return out.getvalue()

        self.assertIn("IX_Orders_Date_Copy", run())
        self.assertNotIn("IX_Orders_Date_Copy", run("--min-size-mb", "100").split("Database Sales")[1].split("Missing")[0])
