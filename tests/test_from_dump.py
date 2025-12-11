import io
import os
import tempfile
import unittest

from index_advisor.cli import main

from .fakes import connection_from_fixture


class FromDumpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "dump.json")
        main(["--server", "SQLPROD01", "--dump", self.path, "-o", os.devnull],
             connect=lambda a: connection_from_fixture("sales_long"))

    def run_cli(self, *argv):
        out = io.StringIO()
        code = main([*argv], stdout=out)
        return code, out.getvalue()

    def test_same_report_as_the_live_run(self):
        live = io.StringIO()
        main(["--server", "SQLPROD01"], connect=lambda a: connection_from_fixture("sales_long"), stdout=live)
        code, offline = self.run_cli("--from-dump", self.path)
        self.assertEqual(code, 0)
        self.assertEqual(offline, live.getvalue())

    def test_another_config_can_be_tried_without_a_server(self):
        cfg = os.path.join(self.tmp.name, "advisor.toml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write('[exclude]\ndatabases = ["HR"]\n')
        code, out = self.run_cli("--from-dump", self.path, "--config", cfg)
        self.assertNotIn("Database HR", out)

    def test_database_filter_applies_to_the_dump(self):
        code, out = self.run_cli("--from-dump", self.path, "-d", "hr")
        self.assertIn("Database HR", out)
        self.assertNotIn("Database Sales", out)
        self.assertEqual(self.run_cli("--from-dump", self.path, "-d", "Nope")[0], 3)

    def test_exactly_one_source(self):
        for argv in ([], ["--server", "A", "--from-dump", self.path]):
            with self.assertRaises(SystemExit) as ctx:
                self.run_cli(*argv)
            self.assertEqual(ctx.exception.code, 3)

    def test_options_that_need_a_connection_are_refused(self):
        for extra in ("--physical", "--dump"):
            argv = ["--from-dump", self.path, extra] + (["x.json"] if extra == "--dump" else [])
            with self.assertRaises(SystemExit) as ctx:
                self.run_cli(*argv)
            self.assertEqual(ctx.exception.code, 3)

    def test_unusable_dump(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.assertEqual(self.run_cli("--from-dump", bad)[0], 3)
        self.assertEqual(self.run_cli("--from-dump", os.path.join(self.tmp.name, "none.json"))[0], 3)
