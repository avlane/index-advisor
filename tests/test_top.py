import io
import json
import unittest

from index_advisor.cli import main
from index_advisor.report import render

from .fakes import connection_from_fixture
from .test_report import build_report


class TopTest(unittest.TestCase):
    def test_text_report_is_cut_after_n_recommendations(self):
        text = render(build_report(), "text", top=2)
        sales = text.split("Database Sales")[1].split("By table")[0]
        self.assertEqual(sales.count("\n  DROP") + sales.count("\n  CONSOLIDATE") + sales.count("\n  REVIEW"), 2)
        self.assertIn("  ... and 5 more (use --top 0 to list them all)", sales)

    def test_largest_recommendations_come_first(self):
        text = render(build_report(), "text", top=1)
        self.assertIn("DROP        dbo.Orders.IX_Orders_Customer (40.6 MB)", text)

    def test_top_zero_and_large_values_show_everything(self):
        self.assertNotIn("more (use", render(build_report(), "text", top=0))
        self.assertNotIn("more (use", render(build_report(), "text", top=50))

    def test_markdown(self):
        text = render(build_report(), "markdown", top=3)
        self.assertIn("_... and 4 more (use `--top 0` to list them all)._", text)

    def test_json_is_never_cut(self):
        doc = json.loads(render(build_report(), "json", top=1))
        self.assertEqual(len(doc["databases"][1]["recommendations"]), 15)

    def test_command_line(self):
        out = io.StringIO()
        main(["--server", "SQLPROD01", "--top", "1"], connect=lambda a: connection_from_fixture("sales_long"), stdout=out)
        self.assertIn("... and 6 more", out.getvalue())
