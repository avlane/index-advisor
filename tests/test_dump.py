import json
import os
import tempfile
import unittest

from index_advisor.cli import main
from index_advisor.collect import collect
from index_advisor.dump import DumpError, dump_collection, load_collection

from .fakes import connection_from_fixture


def collected(fixture="sales_long"):
    return collect(connection_from_fixture(fixture), lambda names: names, physical=True)


class DumpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "dump.json")

    def test_round_trip_is_lossless(self):
        original = collected()
        dump_collection(self.path, original)
        self.assertEqual(load_collection(self.path), original)

    def test_the_dump_is_plain_json_with_a_format_marker(self):
        dump_collection(self.path, collected())
        with open(self.path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["format"], 1)
        self.assertEqual(doc["collection"]["server"]["server_name"], "SQLPROD01")
        self.assertEqual([d["name"] for d in doc["collection"]["databases"]], ["HR", "Sales"])

    def test_errors_survive_the_round_trip(self):
        original = collected()
        original.errors.append(("Broken", "denied"))
        dump_collection(self.path, original)
        self.assertEqual(load_collection(self.path).errors, [("Broken", "denied")])

    def test_bad_files(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2")
        with self.assertRaises(DumpError):
            load_collection(self.path)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"format": 2}, fh)
        with self.assertRaises(DumpError):
            load_collection(self.path)
        with self.assertRaises(DumpError):
            load_collection(os.path.join(self.tmp.name, "missing.json"))


class DumpOptionTest(unittest.TestCase):
    def test_dump_option_writes_the_file_next_to_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dump.json")
            code = main(["--server", "SQLPROD01", "--dump", path, "-o", os.devnull],
                        connect=lambda a: connection_from_fixture("sales_long"))
            self.assertEqual(code, 0)
            self.assertEqual(len(load_collection(path).databases), 2)
