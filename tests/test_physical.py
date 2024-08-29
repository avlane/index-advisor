import io
import unittest

from index_advisor.analysis import DROP, KEEP, analyse_database
from index_advisor.cli import main
from index_advisor.config import Config
from index_advisor.queries import attach_physical, fetch_indexes

from .fakes import connection_from_fixture
from .helpers import by_name, ix, server


class AttachPhysicalTest(unittest.TestCase):
    def setUp(self):
        self.conn = connection_from_fixture("sales_long")
        self.indexes = {i.name: i for i in fetch_indexes(self.conn, "Sales")}
        attach_physical(self.conn, "Sales", self.indexes.values(), min_pages=1000)

    def test_fragmentation_and_pages(self):
        ix_ = self.indexes["IX_Orders_Customer"]
        self.assertAlmostEqual(ix_.fragmentation, 62.0)
        self.assertEqual(ix_.page_count, 5200)

    def test_indexes_without_a_row_stay_unknown(self):
        self.assertIsNone(self.indexes["IX_Customers_Email"].fragmentation)

    def test_min_pages_is_a_parameter(self):
        sql, params = self.conn.executed[-1]
        self.assertIn("dm_db_index_physical_stats", sql)
        self.assertEqual(params, (1000,))

    def test_partitions_are_combined_by_page_weight(self):
        class Rows:
            def __init__(self):
                self.executed = []

            def cursor(self):
                outer = self

                class Cur:
                    description = [(c, None, None, None, None, None, None) for c in
                                   ("object_id", "index_id", "avg_fragmentation_in_percent", "page_count")]

                    def execute(self, sql, *params):
                        outer.executed.append(sql)

                    def fetchall(self):
                        return [(7, 2, 10.0, 3000), (7, 2, 50.0, 1000)] if len(outer.executed) > 1 else []

                    def close(self):
                        pass

                return Cur()

        index = ix("IX_P", ["A"])
        index.object_id, index.index_id = 7, 2
        attach_physical(Rows(), "Sales", [index])
        self.assertAlmostEqual(index.fragmentation, 20.0)
        self.assertEqual(index.page_count, 4000)


class PhysicalNotesTest(unittest.TestCase):
    def analyse(self, **kw):
        index = ix("IX_A", ["A"], **kw)
        index.fragmentation, index.page_count = 55.0, 12000
        return by_name(analyse_database("Sales", [index], server(), Config()))["IX_A"]

    def test_kept_fragmented_index_gets_a_maintenance_hint(self):
        rec = self.analyse(reads=50)
        self.assertEqual(rec.action, KEEP)
        self.assertEqual(rec.reasons[-1], "55% fragmented over 12,000 pages: a candidate for REBUILD or REORGANIZE")

    def test_drop_candidates_are_not_worth_a_rebuild(self):
        rec = self.analyse(reads=0, updates=900)
        self.assertEqual(rec.action, DROP)
        self.assertIn("do not spend a rebuild on it before the change", rec.reasons[-1])

    def test_lightly_fragmented_index_has_no_note(self):
        index = ix("IX_A", ["A"], reads=5)
        index.fragmentation, index.page_count = 10.0, 5000
        rec = by_name(analyse_database("Sales", [index], server(), Config()))["IX_A"]
        self.assertEqual(rec.reasons, ["5 reads, 0 updates"])


class PhysicalCliTest(unittest.TestCase):
    def run_cli(self, *argv):
        conns = []

        def connect(args):
            conns.append(connection_from_fixture("sales_long"))
            return conns[0]

        out = io.StringIO()
        main(["--server", "SQLPROD01", *argv], connect=connect, stdout=out)
        return conns[0], out.getvalue()

    def test_physical_stats_are_not_read_by_default(self):
        conn, out = self.run_cli()
        self.assertFalse(any("dm_db_index_physical_stats" in sql for sql, _ in conn.executed))
        self.assertNotIn("fragmented", out)

    def test_flag_reads_them_for_every_database(self):
        conn, out = self.run_cli("--physical", "--min-pages", "500")
        calls = [params for sql, params in conn.executed if "dm_db_index_physical_stats" in sql]
        self.assertEqual(calls, [(500,), (500,)])
        self.assertIn("62% fragmented over 5,200 pages: do not spend a rebuild on it", out)
