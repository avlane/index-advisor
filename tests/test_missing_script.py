import unittest

from index_advisor.analysis import Report, analyse_database
from index_advisor.config import Config, parse_config
from index_advisor.missing import suggest
from index_advisor.queries import fetch_missing_indexes
from index_advisor.scripts import generate_scripts, missing_script, new_index_statement

from .fakes import connection_from_fixture
from .helpers import ix, server


def analysis_with(indexes):
    srv = server()
    analysis = analyse_database("Sales", indexes, srv, Config())
    missing = fetch_missing_indexes(connection_from_fixture("sales_long"))
    analysis.suggestions = suggest(missing, parse_config({}).thresholds, "Sales", [r.index for r in analysis.recommendations])
    return analysis


class MissingScriptTest(unittest.TestCase):
    def test_new_index_statement(self):
        (first,) = analysis_with([]).suggestions
        self.assertEqual(new_index_statement(first),
                         "CREATE NONCLUSTERED INDEX [IX_Orders_CustomerID_Status_OrderDate] ON [dbo].[Orders] "
                         "([CustomerID], [Status], [OrderDate]) INCLUDE ([Total]);")

    def test_everything_is_commented_out(self):
        text = missing_script(analysis_with([]), server())
        for line in text.splitlines():
            self.assertFalse(line.startswith("CREATE"), line)
        self.assertIn("-- CREATE NONCLUSTERED INDEX [IX_Orders_CustomerID_Status_OrderDate]", text)
        self.assertIn("-- dbo.Orders: score 3,991,530, 2,200 uses, average cost 18.4, average impact 98%", text)
        self.assertIn("--   also satisfies a request for (CustomerID) INCLUDE (Status, OrderDate)", text)

    def test_suggestion_that_extends_an_index_widens_it_and_has_a_rollback(self):
        existing = ix("IX_Orders_Cust_Status", ["CustomerID", "Status"], table="Orders", reads=100)
        text = missing_script(analysis_with([existing]), server())
        self.assertIn("-- CREATE NONCLUSTERED INDEX [IX_Orders_Cust_Status] ON [dbo].[Orders] ([CustomerID], [Status]) "
                      "INCLUDE ([OrderDate], [Total]) WITH (DROP_EXISTING = ON);", text)
        self.assertIn("-- Rollback: CREATE NONCLUSTERED INDEX [IX_Orders_Cust_Status] ON [dbo].[Orders] "
                      "([CustomerID], [Status]) WITH (DROP_EXISTING = ON);", text)

    def test_covered_request_gets_a_note_and_no_statement(self):
        existing = ix("IX_Cov", ["CustomerID", "Status", "OrderDate"], ["Total"], table="Orders", reads=100)
        text = missing_script(analysis_with([existing]), server())
        self.assertIn("--   IX_Cov already covers this request", text)
        self.assertNotIn("[IX_Orders_CustomerID_Status_OrderDate]", text)

    def test_generate_scripts_adds_the_file_when_there_are_suggestions(self):
        report = Report(server(), [analysis_with([])])
        self.assertIn("Sales.missing-indexes.sql", generate_scripts(report))
        report.databases[0].suggestions = []
        self.assertNotIn("Sales.missing-indexes.sql", generate_scripts(report))
