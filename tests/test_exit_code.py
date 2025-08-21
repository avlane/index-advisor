import io
import unittest

from index_advisor.cli import main

from .fakes import connection_from_fixture


class ExitCodeTest(unittest.TestCase):
    def run_cli(self, *argv, fixture="sales_long", database=("-d", "Sales")):
        return main(["--server", "SQLPROD01", *database, *argv],
                    connect=lambda a: connection_from_fixture(fixture), stdout=io.StringIO())

    def test_advice_alone_does_not_change_the_exit_code(self):
        self.assertEqual(self.run_cli(), 0)

    def test_exit_code_option_reports_drop_and_consolidate_recommendations(self):
        self.assertEqual(self.run_cli("--exit-code"), 1)

    def test_nothing_to_do_is_zero_even_with_the_option(self):
        self.assertEqual(self.run_cli("--exit-code", database=("-d", "HR")), 0)

    def test_unreadable_databases_take_precedence(self):
        class Broken:
            def __init__(self, conn):
                self.conn = conn

            def cursor(self):
                cur = self.conn.cursor()
                real = cur.execute

                def execute(sql, *params):
                    if sql.strip() == "USE [HR]":
                        raise RuntimeError("denied")
                    return real(sql, *params)

                cur.execute = execute
                return cur

            def close(self):
                self.conn.close()

        code = main(["--server", "SQLPROD01", "--exit-code"],
                    connect=lambda a: Broken(connection_from_fixture("sales_long")), stdout=io.StringIO())
        self.assertEqual(code, 4)
