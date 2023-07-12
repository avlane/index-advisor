import unittest

from index_advisor.queries import fetch_databases, fetch_indexes, fetch_server_info

from .fakes import connection_from_fixture


class ServerInfoTest(unittest.TestCase):
    def test_start_time_and_uptime(self):
        info = fetch_server_info(connection_from_fixture("sales_long"))
        self.assertEqual(info.server_name, "SQLPROD01")
        self.assertEqual(info.start_time.isoformat(), "2023-04-21T04:00:00")
        self.assertAlmostEqual(info.uptime_days, 80.25, places=2)
        self.assertIn("Enterprise", info.edition)

    def test_short_uptime(self):
        info = fetch_server_info(connection_from_fixture("sales_short"))
        self.assertAlmostEqual(info.uptime_days, 12.25, places=2)


class DatabasesTest(unittest.TestCase):
    def test_database_names(self):
        self.assertEqual(fetch_databases(connection_from_fixture("sales_long")), ["HR", "Sales"])


class FetchIndexesTest(unittest.TestCase):
    def setUp(self):
        self.conn = connection_from_fixture("sales_long")
        self.indexes = {i.name: i for i in fetch_indexes(self.conn, "Sales")}

    def test_database_is_selected_first(self):
        self.assertEqual(self.conn.executed[0][0], "USE [Sales]")

    def test_all_indexes_are_mapped(self):
        self.assertEqual(len(self.indexes), 15)
        ix = self.indexes["IX_Orders_Customer"]
        self.assertEqual((ix.schema, ix.table, ix.index_id), ("dbo", "Orders", 2))
        self.assertEqual(ix.full_name, "dbo.Orders.IX_Orders_Customer")
        self.assertEqual(ix.type_desc, "NONCLUSTERED")

    def test_usage_counters(self):
        ix = self.indexes["IX_Orders_Customer"]
        self.assertEqual((ix.user_seeks, ix.user_scans, ix.user_lookups, ix.user_updates), (5200, 0, 0, 480))
        self.assertEqual(ix.reads, 5200)
        self.assertTrue(ix.has_usage_row)
        self.assertIsNotNone(ix.last_user_read)

    def test_index_without_usage_row_has_zero_counters(self):
        ix = self.indexes["IX_Customers_Region"]
        self.assertFalse(ix.has_usage_row)
        self.assertEqual((ix.reads, ix.user_updates), (0, 0))
        self.assertIsNone(ix.last_user_read)

    def test_constraint_flags_and_size(self):
        self.assertTrue(self.indexes["PK_Orders"].is_primary_key)
        self.assertTrue(self.indexes["UQ_Orders_Number"].is_unique_constraint)
        self.assertTrue(self.indexes["IX_Customers_Old"].is_disabled)
        self.assertAlmostEqual(self.indexes["IX_Orders_Customer"].size_mb, 40.625)

    def test_other_database(self):
        self.assertEqual([i.name for i in fetch_indexes(self.conn, "HR")],
                         ["PK_Employees", "IX_Employees_Dept", "IX_Employees_Hire"])
