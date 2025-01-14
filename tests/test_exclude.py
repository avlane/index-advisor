import io
import os
import tempfile
import unittest

from index_advisor.analysis import KEEP, analyse_database
from index_advisor.cli import main
from index_advisor.config import Config, parse_config

from .fakes import connection_from_fixture
from .helpers import analyse, by_name, ix, server


class ExcludeAndKeepTest(unittest.TestCase):
    def test_excluded_tables_are_not_analysed(self):
        cfg = parse_config({"exclude": {"tables": ["dbo.Staging_*"]}})
        result = analyse([ix("IX_A", ["A"], table="Staging_Load", updates=900), ix("IX_B", ["B"], updates=900)], config=cfg)
        self.assertEqual(sorted(by_name(result)), ["IX_B"])

    def test_kept_index_is_never_dropped(self):
        cfg = parse_config({"keep": {"indexes": ["Sales.dbo.Orders.IX_Monthly"]}})
        result = analyse([ix("IX_Monthly", ["A"], reads=0, updates=5000)], config=cfg)
        rec = by_name(result)["IX_Monthly"]
        self.assertEqual(rec.action, KEEP)
        self.assertTrue(rec.protected)
        self.assertEqual(rec.reasons, ["listed under [keep] in the configuration; 0 reads, 5,000 updates"])

    def test_kept_index_still_counts_as_a_merge_target(self):
        cfg = parse_config({"keep": {"indexes": ["Sales.dbo.Orders.IX_AB"]}})
        result = analyse([ix("IX_A", ["A"], reads=1), ix("IX_AB", ["A", "B"], reads=1)], config=cfg)
        self.assertEqual(by_name(result)["IX_A"].action, "drop")


class CliExcludeTest(unittest.TestCase):
    def run_cli(self, config_text, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "advisor.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(config_text)
            out = io.StringIO()
            code = main(["--server", "SQLPROD01", "--config", path, *argv],
                        connect=lambda a: connection_from_fixture("sales_long"), stdout=out)
        return code, out.getvalue()

    def test_excluded_database_is_skipped(self):
        code, out = self.run_cli('[exclude]\ndatabases = ["HR"]\n')
        self.assertNotIn("Database HR", out)
        self.assertIn("Database Sales", out)

    def test_naming_a_database_overrides_the_exclusion(self):
        code, out = self.run_cli('[exclude]\ndatabases = ["HR"]\n', "-d", "HR")
        self.assertIn("Database HR", out)

    def test_excluded_tables_do_not_appear(self):
        code, out = self.run_cli('[exclude]\ntables = ["dbo.Orders"]\n')
        self.assertNotIn("dbo.Orders.", out)
        self.assertIn("dbo.OrderLines.", out)

    def test_keep_pattern_removes_a_drop_candidate(self):
        code, out = self.run_cli('[keep]\nindexes = ["*.IX_Orders_Date*"]\n')
        self.assertNotIn("DROP        dbo.Orders.IX_Orders_Date", out)
