import unittest
from dataclasses import replace

from index_advisor.queries import fetch_server_info
from index_advisor.scripts import consolidate_script, create_statement, missing_script

from .fakes import connection_from_fixture
from .helpers import ix, server
from .test_consolidate_script import sample
from .test_missing_script import analysis_with


class OnlineRebuildTest(unittest.TestCase):
    def test_engine_edition_is_read(self):
        info = fetch_server_info(connection_from_fixture("sales_long"))
        self.assertEqual(info.engine_edition, 3)
        self.assertTrue(info.online_rebuild)

    def test_editions(self):
        for edition, online in ((1, False), (2, False), (3, True), (4, False), (5, True), (8, True), (0, False)):
            self.assertEqual(replace(server(), engine_edition=edition).online_rebuild, online, edition)

    def test_create_statement_option(self):
        index = ix("IX_A", ["A"])
        self.assertEqual(create_statement(index, drop_existing=True, online=True),
                         "CREATE NONCLUSTERED INDEX [IX_A] ON [dbo].[Orders] ([A]) WITH (DROP_EXISTING = ON, ONLINE = ON);")
        self.assertNotIn("ONLINE", create_statement(index, drop_existing=True))

    def test_consolidation_script_uses_online_on_enterprise(self):
        text = consolidate_script(sample().databases[0], replace(server(), engine_edition=3))
        self.assertIn("WITH (DROP_EXISTING = ON, ONLINE = ON);", text)
        self.assertIn("-- ONLINE = ON is used because this edition supports online index operations.", text)

    def test_standard_edition_gets_a_warning_instead(self):
        text = consolidate_script(sample().databases[0], replace(server(), engine_edition=2))
        self.assertNotIn("ONLINE = ON);", text)
        self.assertIn("This edition cannot rebuild indexes online", text)

    def test_missing_index_script_follows_the_edition(self):
        existing = ix("IX_Orders_Cust_Status", ["CustomerID", "Status"], table="Orders", reads=100)
        enterprise = missing_script(analysis_with([existing]), replace(server(), engine_edition=3))
        self.assertIn("WITH (DROP_EXISTING = ON, ONLINE = ON);", enterprise)
        standard = missing_script(analysis_with([existing]), replace(server(), engine_edition=2))
        self.assertNotIn("ONLINE = ON);", standard)
