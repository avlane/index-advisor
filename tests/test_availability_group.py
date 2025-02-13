import io
import unittest

from index_advisor.analysis import AG_WARNING, DROP, REVIEW, analyse_database
from index_advisor.cli import main
from index_advisor.config import Config
from index_advisor.queries import fetch_availability_databases

from .fakes import FakeConnection, connection_from_fixture, load_fixture
from .helpers import by_name, ix, server


class AvailabilityGroupAnalysisTest(unittest.TestCase):
    def analyse(self, ag):
        indexes = [ix("IX_Unused", ["A"], reads=0, updates=900), ix("IX_Dup1", ["B"], reads=5), ix("IX_Dup2", ["B"], reads=1)]
        return analyse_database("Sales", indexes, server(), Config(), (), ag)

    def test_unused_becomes_review_in_an_availability_group(self):
        result = self.analyse(True)
        rec = by_name(result)["IX_Unused"]
        self.assertEqual(rec.action, REVIEW)
        self.assertIn("availability group", rec.reasons[0])
        self.assertEqual(result.warnings, [AG_WARNING])

    def test_structural_findings_are_unaffected(self):
        self.assertEqual(by_name(self.analyse(True))["IX_Dup2"].action, DROP)

    def test_normal_databases_are_unchanged(self):
        result = self.analyse(False)
        self.assertEqual(by_name(result)["IX_Unused"].action, DROP)
        self.assertEqual(result.warnings, [])


class AvailabilityGroupQueryTest(unittest.TestCase):
    def fixture_with_ag(self):
        doc = load_fixture("sales_long")
        doc["availability_databases"] = ["Sales"]
        return FakeConnection(doc)

    def test_fetch(self):
        self.assertEqual(fetch_availability_databases(self.fixture_with_ag()), ["Sales"])
        self.assertEqual(fetch_availability_databases(connection_from_fixture("sales_long")), [])

    def test_cli_marks_only_the_databases_in_a_group(self):
        out = io.StringIO()
        main(["--server", "SQLPROD01"], connect=lambda a: self.fixture_with_ag(), stdout=out)
        text = out.getvalue()
        sales, hr = text.split("Database Sales")[1], text.split("Database HR")[1].split("Database Sales")[0]
        self.assertIn("availability group", sales)
        self.assertNotIn("availability group", hr)

    def test_missing_view_is_not_fatal(self):
        class Old:
            def __init__(self):
                self.conn = connection_from_fixture("sales_long")

            def cursor(self):
                cur = self.conn.cursor()
                real = cur.execute

                def execute(sql, *params):
                    if "availability_databases_cluster" in sql:
                        raise RuntimeError("Invalid object name 'sys.availability_databases_cluster'")
                    return real(sql, *params)

                cur.execute = execute
                return cur

            def close(self):
                self.conn.close()

        out = io.StringIO()
        code = main(["--server", "SQLPROD01"], connect=lambda a: Old(), stdout=out)
        self.assertEqual(code, 0)
