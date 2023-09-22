import unittest

from index_advisor.analysis import KEEP, REVIEW, analyse_database
from index_advisor.config import Config
from index_advisor.queries import fetch_indexes

from .fakes import connection_from_fixture
from .helpers import analyse, by_name, ix, server


class ProtectedIndexTest(unittest.TestCase):
    def test_constraint_backed_and_special_indexes_are_never_dropped(self):
        result = analyse([
            ix("PK_Orders", ["OrderID"], type_desc="CLUSTERED", is_unique=True, is_primary_key=True, updates=900),
            ix("UQ_Number", ["Number"], is_unique=True, is_unique_constraint=True, updates=900),
            ix("IX_Email", ["Email"], is_unique=True, updates=900),
            ix("CIX_Orders", ["OrderID"], type_desc="CLUSTERED", updates=900),
            ix("CCI_Audit", [], type_desc="CLUSTERED COLUMNSTORE", updates=900),
            ix("XML_Doc", ["Doc"], type_desc="XML", updates=900),
        ])
        for name, rec in by_name(result).items():
            self.assertEqual(rec.action, KEEP, name)
            self.assertTrue(rec.protected, name)
        self.assertIn("primary key; 0 reads, 900 updates", by_name(result)["PK_Orders"].reasons[0])
        self.assertIn("columnstore", by_name(result)["CCI_Audit"].reasons[0])

    def test_disabled_index_is_a_review_item(self):
        rec = by_name(analyse([ix("IX_Off", ["A"], is_disabled=True)]))["IX_Off"]
        self.assertEqual(rec.action, REVIEW)
        self.assertIn("disabled", rec.reasons[0])

    def test_fixture_database(self):
        indexes = fetch_indexes(connection_from_fixture("sales_long"), "Sales")
        recs = by_name(analyse_database("Sales", indexes, server(80), Config()))
        self.assertEqual(recs["UQ_Orders_Number"].action, KEEP)
        self.assertEqual(recs["CCI_AuditLog"].action, KEEP)
        self.assertEqual(recs["PK_Orders"].action, KEEP)
        self.assertEqual(recs["IX_Customers_Old"].action, REVIEW)
        self.assertEqual(recs["IX_Customers_Region"].action, REVIEW)
        self.assertIn("no reads or writes", recs["IX_Customers_Region"].reasons[0])
