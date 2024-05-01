import io
import os
import tempfile
import unittest

from index_advisor.cli import main

from .fakes import connection_from_fixture


class ScriptsDirTest(unittest.TestCase):
    def run_cli(self, directory):
        conns = []

        def connect(args):
            conns.append(connection_from_fixture("sales_long"))
            return conns[0]

        code = main(["--server", "SQLPROD01", "--scripts-dir", directory], connect=connect, stdout=io.StringIO())
        return code, conns[0]

    def test_scripts_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "scripts")
            code, conn = self.run_cli(target)
            self.assertEqual(code, 0)
            self.assertEqual(sorted(os.listdir(target)), [
                "Sales.consolidate.sql", "Sales.drop-candidates.sql", "Sales.recreate-dropped.sql"])
            with open(os.path.join(target, "Sales.drop-candidates.sql"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("-- DROP INDEX [IX_Orders_Date_Copy] ON [dbo].[Orders];", text)
            self.assertIn("-- DROP INDEX [IX_Orders_Customer] ON [dbo].[Orders];", text)

    def test_only_read_queries_reach_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, conn = self.run_cli(tmp)
        for sql, params in conn.executed:
            first = sql.strip().split()[0].upper()
            self.assertIn(first, {"SELECT", "USE"}, sql)
