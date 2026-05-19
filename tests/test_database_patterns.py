import io
import unittest

from index_advisor.cli import main

from .fakes import FakeConnection, load_fixture


def run(*argv):
    doc = load_fixture("sales_long")
    doc["databases"] = ["HR", "Sales", "Sales_Archive"]
    doc["per_database"]["Sales_Archive"] = doc["per_database"]["HR"]
    out = io.StringIO()
    code = main(["--server", "SQLPROD01", *argv], connect=lambda a: FakeConnection(doc), stdout=out)
    return code, out.getvalue()


class DatabasePatternTest(unittest.TestCase):
    def names(self, out):
        return [line.split()[1].rstrip(":") for line in out.splitlines() if line.startswith("Database ")]

    def test_wildcard(self):
        code, out = run("-d", "Sales*")
        self.assertEqual(self.names(out), ["Sales", "Sales_Archive"])

    def test_exact_names_still_work_and_order_is_kept(self):
        code, out = run("-d", "sales", "-d", "hr")
        self.assertEqual(self.names(out), ["Sales", "HR"])

    def test_overlapping_patterns_do_not_repeat_a_database(self):
        code, out = run("-d", "Sales*", "-d", "Sales")
        self.assertEqual(self.names(out), ["Sales", "Sales_Archive"])

    def test_question_mark(self):
        code, out = run("-d", "H?")
        self.assertEqual(self.names(out), ["HR"])

    def test_pattern_without_a_match_is_an_error(self):
        self.assertEqual(run("-d", "Nope*")[0], 3)
