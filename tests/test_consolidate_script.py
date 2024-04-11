import unittest

from index_advisor.scripts import consolidate_script, generate_scripts, merge_plans

from .helpers import ix, server
from .test_scripts import report_for


def sample():
    return report_for([
        ix("IX_Prod", ["ProductID"], ["Quantity"], table="OrderLines", reads=900, updates=50),
        ix("IX_Prod_Price", ["ProductID", "UnitPrice"], ["Discount"], table="OrderLines", reads=40, updates=50),
    ])


class ConsolidateScriptTest(unittest.TestCase):
    def test_plan(self):
        ((target, sources),) = merge_plans(sample().databases[0])
        self.assertEqual(target.index.name, "IX_Prod_Price")
        self.assertEqual([s.index.name for s in sources], ["IX_Prod"])

    def test_widens_the_target_then_drops_the_source(self):
        text = consolidate_script(sample().databases[0], server())
        lines = [line for line in text.splitlines() if line.startswith("-- CREATE") or line.startswith("-- DROP")]
        self.assertEqual(lines, [
            "-- CREATE NONCLUSTERED INDEX [IX_Prod_Price] ON [dbo].[OrderLines] ([ProductID], [UnitPrice]) "
            "INCLUDE ([Discount], [Quantity]) WITH (DROP_EXISTING = ON);",
            "-- DROP INDEX [IX_Prod] ON [dbo].[OrderLines];",
        ])

    def test_rollback_restores_both_definitions(self):
        text = consolidate_script(sample().databases[0], server())
        self.assertIn("--   CREATE NONCLUSTERED INDEX [IX_Prod_Price] ON [dbo].[OrderLines] ([ProductID], "
                      "[UnitPrice]) INCLUDE ([Discount]) WITH (DROP_EXISTING = ON);", text)
        self.assertIn("--   CREATE NONCLUSTERED INDEX [IX_Prod] ON [dbo].[OrderLines] ([ProductID]) INCLUDE ([Quantity]);", text)

    def test_no_executable_statements(self):
        text = consolidate_script(sample().databases[0], server())
        for line in text.splitlines():
            if line.startswith(("CREATE", "DROP")):
                self.fail(line)

    def test_file_is_generated_only_with_a_consolidation(self):
        self.assertIn("Sales.consolidate.sql", generate_scripts(sample()))
        self.assertEqual(generate_scripts(report_for([ix("IX_A", ["A"], reads=5)])), {})
