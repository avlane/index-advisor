import io
import json
import os
import tempfile
import unittest

from index_advisor.cli import main

from .fakes import connection_from_fixture


def run(*argv, fixture="sales_long", connect=None):
    out = io.StringIO()
    code = main(["--server", "SQLPROD01", *argv],
                connect=connect or (lambda args: connection_from_fixture(fixture)), stdout=out)
    return code, out.getvalue()


class CliTest(unittest.TestCase):
    def test_text_report(self):
        code, out = run()
        self.assertEqual(code, 0)
        self.assertIn("index-advisor report for SQLPROD01", out)
        self.assertIn("Database Sales:", out)
        self.assertIn("Database HR:", out)

    def test_database_filter_is_case_insensitive(self):
        code, out = run("-d", "hr")
        self.assertIn("Database HR:", out)
        self.assertNotIn("Database Sales", out)

    def test_unknown_database(self):
        code, out = run("-d", "Nope")
        self.assertEqual(code, 3)

    def test_output_file_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "advisor.toml")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write("[thresholds]\nmin_uptime_days = 100\n")
            target = os.path.join(tmp, "report.txt")
            code, out = run("--config", cfg, "-o", target)
            self.assertEqual((code, out), (0, ""))
            with open(target, encoding="utf-8") as fh:
                self.assertIn("WARNING: SQL Server started on", fh.read())

    def test_bad_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "advisor.toml")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write("[thresholds]\nbogus = 1\n")
            code, out = run("--config", cfg)
        self.assertEqual(code, 3)

    def test_connection_failure(self):
        def boom(args):
            raise OSError("login timeout")

        self.assertEqual(run(connect=boom)[0], 3)

    def test_a_database_that_cannot_be_read_gives_partial_exit_code(self):
        class Broken:
            def __init__(self, conn):
                self.conn = conn

            def cursor(self):
                cur = self.conn.cursor()
                real = cur.execute

                def execute(sql, *params):
                    if sql.strip() == "USE [HR]":
                        raise RuntimeError("The server principal is not able to access the database")
                    return real(sql, *params)

                cur.execute = execute
                return cur

            def close(self):
                self.conn.close()

        code, out = run(connect=lambda args: Broken(connection_from_fixture("sales_long")))
        self.assertEqual(code, 4)
        self.assertIn("Database HR could not be read: The server principal", out)
        self.assertIn("Database Sales:", out)

    def test_usage_error_exit_code(self):
        with self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 3)

    def test_help_and_version(self):
        for flag in ("--help", "--version"):
            with self.assertRaises(SystemExit) as ctx:
                main([flag])
            self.assertEqual(ctx.exception.code, 0)
