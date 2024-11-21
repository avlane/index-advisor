import unittest

from index_advisor.queries import attach_columns, fetch_indexes
from index_advisor.scripts import create_statement, recreate_script

from .fakes import connection_from_fixture
from .helpers import analyse, ix, server


class StorageClauseTest(unittest.TestCase):
    def test_non_default_filegroup(self):
        index = ix("IX_A", ["A"], data_space="IDX", data_space_type="FG", data_space_is_default=False)
        self.assertEqual(create_statement(index), "CREATE NONCLUSTERED INDEX [IX_A] ON [dbo].[Orders] ([A]) ON [IDX];")

    def test_default_filegroup_is_not_written(self):
        index = ix("IX_A", ["A"], data_space="PRIMARY", data_space_type="FG", data_space_is_default=True)
        self.assertNotIn(" ON [PRIMARY]", create_statement(index))

    def test_partition_scheme_with_partition_column(self):
        index = ix("IX_A", ["A"], data_space="ps_Orders", data_space_type="PS", partition_column="OrderDate")
        self.assertEqual(create_statement(index),
                         "CREATE NONCLUSTERED INDEX [IX_A] ON [dbo].[Orders] ([A]) ON [ps_Orders]([OrderDate]);")

    def test_compression_goes_into_the_with_clause_before_the_on_clause(self):
        index = ix("IX_A", ["A"], fill_factor=90, compression="PAGE", data_space="IDX", data_space_type="FG",
                   data_space_is_default=False)
        self.assertEqual(create_statement(index),
                         "CREATE NONCLUSTERED INDEX [IX_A] ON [dbo].[Orders] ([A]) "
                         "WITH (FILLFACTOR = 90, DATA_COMPRESSION = PAGE) ON [IDX];")
        self.assertTrue(create_statement(index, drop_existing=True).endswith(
            "WITH (FILLFACTOR = 90, DATA_COMPRESSION = PAGE, DROP_EXISTING = ON) ON [IDX];"))

    def test_mixed_compression_is_flagged_not_guessed(self):
        index = ix("IX_A", ["A"], updates=900, compression="MIXED")
        text = recreate_script(analyse([index]), server())
        self.assertIn("NOTE: the partitions use different compression settings", text)
        self.assertNotIn("DATA_COMPRESSION", text.replace("DATA_COMPRESSION per partition", ""))

    def test_none_compression_adds_nothing(self):
        self.assertNotIn("WITH", create_statement(ix("IX_A", ["A"], compression="NONE")))


class StorageMappingTest(unittest.TestCase):
    def test_fixture_rows_carry_storage_information(self):
        indexes = {i.name: i for i in fetch_indexes(connection_from_fixture("sales_long"), "Sales")}
        self.assertEqual(indexes["IX_Orders_Date_Copy"].compression, "PAGE")
        self.assertEqual(indexes["IX_Orders_Date"].compression, "NONE")
        self.assertEqual(indexes["IX_Orders_Date"].data_space, "PRIMARY")
        self.assertTrue(indexes["IX_Orders_Date"].data_space_is_default)

    def test_partition_column_is_not_added_as_a_key(self):
        index = ix("IX_A", ["A"])
        rows = [
            dict(object_id=index.object_id, index_id=index.index_id, column_name="OrderDate", key_ordinal=0,
                 is_descending_key=0, is_included_column=0, partition_ordinal=1),
        ]
        attach_columns([index], rows)
        self.assertEqual(index.partition_column, "OrderDate")
        self.assertEqual([c.name for c in index.keys], ["A"])
        self.assertEqual(index.includes, [])

    def test_recreate_script_for_the_fixture_keeps_page_compression(self):
        from index_advisor.analysis import analyse_database
        from index_advisor.config import Config

        indexes = fetch_indexes(connection_from_fixture("sales_long"), "Sales")
        text = recreate_script(analyse_database("Sales", indexes, server(80), Config()), server(80))
        self.assertIn("CREATE NONCLUSTERED INDEX [IX_Orders_Date_Copy] ON [dbo].[Orders] ([OrderDate]) "
                      "WITH (DATA_COMPRESSION = PAGE);", text)
