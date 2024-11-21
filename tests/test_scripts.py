import unittest

from index_advisor.analysis import Report, analyse_database
from index_advisor.config import Config
from index_advisor.scripts import (create_statement, drop_script, drop_statement, generate_scripts, one_line,
                                   recreate_script, safe_filename)

from .helpers import NOW, analyse, ix, server


def report_for(indexes):
    srv = server()
    return Report(srv, [analyse_database("Sales", indexes, srv, Config())])


class StatementTest(unittest.TestCase):
    def test_drop(self):
        self.assertEqual(drop_statement(ix("IX_Old", ["A"])), "DROP INDEX [IX_Old] ON [dbo].[Orders];")

    def test_names_are_quoted(self):
        statement = drop_statement(ix("IX]Odd", ["A"], table="Or]ders"))
        self.assertEqual(statement, "DROP INDEX [IX]]Odd] ON [dbo].[Or]]ders];")

    def test_create_with_includes_filter_and_fillfactor(self):
        index = ix("IX_A", ["Cust", "Date DESC"], ["Status", "Total"], is_unique=True,
                   filter_definition="([Status]<>(9))", fill_factor=90)
        self.assertEqual(create_statement(index),
                         "CREATE UNIQUE NONCLUSTERED INDEX [IX_A] ON [dbo].[Orders] ([Cust], [Date] DESC) "
                         "INCLUDE ([Status], [Total]) WHERE ([Status]<>(9)) WITH (FILLFACTOR = 90);")

    def test_plain_create(self):
        self.assertEqual(create_statement(ix("IX_A", ["Cust"])),
                         "CREATE NONCLUSTERED INDEX [IX_A] ON [dbo].[Orders] ([Cust]);")

    def test_helpers(self):
        self.assertEqual(safe_filename("My DB/1"), "My_DB_1")
        self.assertEqual(one_line("a\nb"), "a b")


class DropScriptTest(unittest.TestCase):
    def setUp(self):
        self.analysis = report_for([
            ix("IX_Unused", ["A"], reads=0, updates=900),
            ix("IX_Used", ["B"], reads=500, updates=900),
        ]).databases[0]
        self.text = drop_script(self.analysis, server())

    def test_header_and_database(self):
        self.assertIn("for SQLPROD01, database [Sales], on 2023-07-10 10:00.", self.text)
        self.assertIn("REVIEW BEFORE RUNNING", self.text)
        self.assertIn("\nUSE [Sales];\nGO\n", self.text)

    def test_every_drop_is_commented_out(self):
        drops = [line for line in self.text.splitlines() if "DROP INDEX" in line and "IX_" in line]
        self.assertEqual(drops, ["-- DROP INDEX [IX_Unused] ON [dbo].[Orders];"])

    def test_reasons_are_listed(self):
        self.assertIn("--   - no reads recorded, but 900 updates keep it maintained", self.text)

    def test_only_drop_candidates_appear(self):
        self.assertNotIn("IX_Used", self.text)

    def test_stats_reset_warning_is_in_the_header(self):
        short = analyse([ix("IX_A", ["A"], updates=900)], uptime_days=3)
        text = drop_script(short, server(3))
        self.assertIn("-- WARNING: SQL Server started on", text)


class RecreateScriptTest(unittest.TestCase):
    def test_creates_the_dropped_indexes_uncommented(self):
        analysis = report_for([ix("IX_Unused", ["A", "B DESC"], ["C"], updates=900, fill_factor=80),
                               ix("IX_Used", ["Z"], reads=9)]).databases[0]
        text = recreate_script(analysis, server())
        self.assertIn("CREATE NONCLUSTERED INDEX [IX_Unused] ON [dbo].[Orders] ([A], [B] DESC) "
                      "INCLUDE ([C]) WITH (FILLFACTOR = 80);", text)
        self.assertNotIn("IX_Used", text)
        self.assertIn("Not captured: per-partition compression", text)


class GenerateScriptsTest(unittest.TestCase):
    def test_file_names(self):
        files = generate_scripts(report_for([ix("IX_Unused", ["A"], updates=900)]))
        self.assertEqual(sorted(files), ["Sales.drop-candidates.sql", "Sales.recreate-dropped.sql"])

    def test_nothing_to_propose_no_files(self):
        self.assertEqual(generate_scripts(report_for([ix("IX_Used", ["A"], reads=5)])), {})
