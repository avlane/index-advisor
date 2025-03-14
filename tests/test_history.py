import json
import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from index_advisor import history
from index_advisor.cli import main
from index_advisor.history import HistoryError, load_history, record_history

from .fakes import connection_from_fixture


class RecordHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "history.json")

    def run_cli(self, fixture="sales_long"):
        return main(["--server", "SQLPROD01", "--history", self.path, "--format", "json", "-o", os.devnull],
                    connect=lambda a: connection_from_fixture(fixture))

    def test_first_run_creates_the_file(self):
        self.assertEqual(self.run_cli(), 0)
        doc = load_history(self.path)
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["server"], "SQLPROD01")
        (snap,) = doc["snapshots"]
        self.assertEqual(snap["start_time"], "2023-04-21T04:00:00")
        self.assertEqual(snap["taken"], "2023-07-10T10:00:00")

    def test_counters_are_recorded_per_index(self):
        self.run_cli()
        (snap,) = load_history(self.path)["snapshots"]
        self.assertEqual(snap["indexes"]["Sales.dbo.Orders.IX_Orders_Customer"],
                         {"seeks": 5200, "scans": 0, "lookups": 0, "updates": 480})

    def test_indexes_without_a_usage_row_are_not_recorded(self):
        self.run_cli()
        (snap,) = load_history(self.path)["snapshots"]
        self.assertNotIn("Sales.dbo.Customers.IX_Customers_Region", snap["indexes"])

    def test_every_run_appends_a_snapshot(self):
        self.run_cli()
        self.run_cli("sales_short")
        self.assertEqual(len(load_history(self.path)["snapshots"]), 2)

    def test_history_of_another_server_is_refused(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "server": "OTHER", "snapshots": []}, fh)
        self.assertEqual(self.run_cli(), 3)

    def test_unreadable_or_foreign_files_are_refused(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2")
        self.assertEqual(self.run_cli(), 3)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 99}, fh)
        with self.assertRaises(HistoryError):
            load_history(self.path)

    def test_old_snapshots_are_trimmed(self):
        server = SimpleNamespace(server_name="S", start_time=datetime(2024, 1, 1), now=datetime(2024, 1, 1))
        collection = SimpleNamespace(server=server, all_indexes=lambda: [])
        with mock.patch.object(history, "MAX_SNAPSHOTS", 3):
            for _ in range(5):
                record_history(self.path, collection)
        self.assertEqual(len(load_history(self.path)["snapshots"]), 3)

    def test_no_temporary_file_is_left_behind(self):
        self.run_cli()
        self.assertEqual(os.listdir(self.tmp.name), ["history.json"])
