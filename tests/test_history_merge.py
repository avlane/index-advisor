import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

from index_advisor.cli import main
from index_advisor.history import totals

from .fakes import connection_from_fixture


def snap(start, taken, **indexes):
    return {"start_time": start, "taken": taken,
            "indexes": {k: dict(seeks=v[0], scans=0, lookups=0, updates=v[1]) for k, v in indexes.items()}}


class TotalsTest(unittest.TestCase):
    def test_runs_of_the_instance_are_added_up(self):
        doc = {"snapshots": [
            snap("2023-01-01T00:00:00", "2023-01-10T00:00:00", A=(10, 100)),
            snap("2023-01-01T00:00:00", "2023-01-20T00:00:00", A=(40, 400)),
            snap("2023-02-01T00:00:00", "2023-02-05T00:00:00", A=(5, 50)),
        ]}
        result, observed = totals(doc)
        self.assertEqual(result["A"], {"seeks": 45, "scans": 0, "lookups": 0, "updates": 450})
        self.assertAlmostEqual(observed, 19 + 4)

    def test_indexes_that_appear_later_are_included(self):
        doc = {"snapshots": [snap("2023-01-01T00:00:00", "2023-01-02T00:00:00", A=(1, 1)),
                            snap("2023-01-01T00:00:00", "2023-01-03T00:00:00", A=(2, 1), B=(7, 3))]}
        result, _ = totals(doc)
        self.assertEqual(result["B"]["seeks"], 7)

    def test_empty_history(self):
        self.assertEqual(totals({"snapshots": []}), ({}, 0.0))


class HistoryCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "history.json")
        self.earlier = {"version": 1, "server": "SQLPROD01", "snapshots": [
            snap("2023-01-01T00:00:00", "2023-03-02T00:00:00", **{"Sales.dbo.Orders.IX_Orders_Date": (7, 10)})]}

    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(["--server", "SQLPROD01", "--history", self.path, *argv],
                    connect=lambda a: connection_from_fixture("sales_short"), stdout=out)
        return code, out.getvalue()

    def test_without_earlier_history_a_young_instance_is_not_trusted(self):
        code, out = self.run_cli()
        self.assertIn("REVIEW      dbo.Orders.IX_Orders_Date (39.1 MB)", out)
        self.assertIn("Usage history covers 12.2 days across restarts", out)
        self.assertIn("The recorded usage history covers only 12.2 days", out)

    def test_earlier_runs_extend_the_observation_window_and_the_counters(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.earlier, fh)
        code, out = self.run_cli()
        self.assertIn("Usage history covers 72.", out)
        self.assertNotIn("The recorded usage history covers only", out)
        # 7 earlier reads: no longer unused. Its duplicate is still a drop.
        self.assertNotIn("REVIEW      dbo.Orders.IX_Orders_Date (", out)
        self.assertIn("DROP        dbo.Orders.IX_Orders_Date_Copy", out)

    def test_other_unused_indexes_become_drop_candidates_with_enough_history(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.earlier, fh)
        code, out = self.run_cli()
        self.assertNotIn("REVIEW      dbo.Orders.IX_Orders_Date_Copy", out)

    def test_json_reports_the_observed_days(self):
        code, out = self.run_cli("--format", "json")
        self.assertEqual(json.loads(out)["server"]["observed_days"], 12.2)


class ResetWithinARunTest(unittest.TestCase):
    def test_a_fall_in_the_counter_is_a_reset(self):
        doc = {"snapshots": [
            snap("2023-01-01T00:00:00", "2023-01-10T00:00:00", A=(100, 0)),
            snap("2023-01-01T00:00:00", "2023-01-11T00:00:00", A=(150, 0)),
            snap("2023-01-01T00:00:00", "2023-01-12T00:00:00", A=(10, 0)),   # database was detached and attached
            snap("2023-01-01T00:00:00", "2023-01-13T00:00:00", A=(40, 0)),
        ]}
        self.assertEqual(totals(doc)[0]["A"]["seeks"], 190)

    def test_an_index_missing_from_a_snapshot_counts_as_reset_to_zero(self):
        doc = {"snapshots": [
            snap("2023-01-01T00:00:00", "2023-01-10T00:00:00", A=(100, 0)),
            snap("2023-01-01T00:00:00", "2023-01-11T00:00:00", B=(1, 0)),
            snap("2023-01-01T00:00:00", "2023-01-12T00:00:00", A=(20, 0), B=(2, 0)),
        ]}
        self.assertEqual(totals(doc)[0]["A"]["seeks"], 120)

    def test_a_new_instance_start_is_a_reset_even_if_the_counter_is_higher(self):
        doc = {"snapshots": [
            snap("2023-01-01T00:00:00", "2023-01-10T00:00:00", A=(10, 0)),
            snap("2023-02-01T00:00:00", "2023-02-10T00:00:00", A=(500, 0)),
        ]}
        self.assertEqual(totals(doc)[0]["A"]["seeks"], 510)

    def test_snapshots_are_ordered_by_time_not_by_position(self):
        doc = {"snapshots": [
            snap("2023-01-01T00:00:00", "2023-01-12T00:00:00", A=(40, 0)),
            snap("2023-01-01T00:00:00", "2023-01-10T00:00:00", A=(10, 0)),
        ]}
        self.assertEqual(totals(doc)[0]["A"]["seeks"], 40)
