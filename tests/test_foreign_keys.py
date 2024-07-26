import unittest

from index_advisor.analysis import CONSOLIDATE, DROP, KEEP, REVIEW, analyse_database
from index_advisor.config import Config
from index_advisor.model import ForeignKey
from index_advisor.queries import fetch_foreign_keys, fetch_indexes

from .fakes import connection_from_fixture
from .helpers import by_name, ix, server


def analyse_fk(indexes, fks):
    return analyse_database("Sales", indexes, server(), Config(), fks)


class ForeignKeyTest(unittest.TestCase):
    def fk(self, *columns, name="FK_Orders_Customers"):
        return ForeignKey(name, ix("x", ["a"]).object_id, list(columns), "dbo.Customers")

    def test_only_supporting_index_is_not_dropped_automatically(self):
        recs = by_name(analyse_fk([ix("IX_Cust", ["CustomerID"], reads=0, updates=900)], [self.fk("CustomerID")]))
        self.assertEqual(recs["IX_Cust"].action, REVIEW)
        self.assertIn("only index leading with the columns of foreign key FK_Orders_Customers", recs["IX_Cust"].reasons[-1])

    def test_another_supporting_index_makes_the_drop_safe(self):
        indexes = [ix("IX_Cust", ["CustomerID"], reads=0, updates=900),
                   ix("IX_Cust_Date", ["CustomerID", "OrderDate"], reads=500)]
        recs = by_name(analyse_fk(indexes, [self.fk("CustomerID")]))
        self.assertEqual(recs["IX_Cust"].action, DROP)
        self.assertIn("foreign key FK_Orders_Customers is also supported by IX_Cust_Date", recs["IX_Cust"].reasons[-1])

    def test_composite_foreign_key_columns_match_in_any_order(self):
        recs = by_name(analyse_fk([ix("IX_AB", ["B", "A"], reads=0, updates=900)], [self.fk("A", "B")]))
        self.assertEqual(recs["IX_AB"].action, REVIEW)

    def test_index_that_does_not_lead_with_the_columns_is_not_a_supporter(self):
        recs = by_name(analyse_fk([ix("IX_XA", ["X", "A"], reads=0, updates=900)], [self.fk("A")]))
        self.assertEqual(recs["IX_XA"].action, DROP)

    def test_other_tables_are_not_affected(self):
        fk = ForeignKey("FK_Other", ix("x", ["a"], table="Other").object_id, ["A"], "dbo.P")
        recs = by_name(analyse_fk([ix("IX_A", ["A"], reads=0, updates=900)], [fk]))
        self.assertEqual(recs["IX_A"].action, DROP)

    def test_kept_indexes_get_no_note(self):
        recs = by_name(analyse_fk([ix("IX_Cust", ["CustomerID"], reads=50)], [self.fk("CustomerID")]))
        self.assertEqual(recs["IX_Cust"].action, KEEP)
        self.assertEqual(recs["IX_Cust"].reasons, ["50 reads, 0 updates"])


class ForeignKeyFixtureTest(unittest.TestCase):
    def test_fetch_groups_columns_per_constraint(self):
        fks = {fk.name: fk for fk in fetch_foreign_keys(connection_from_fixture("sales_long"), "Sales")}
        self.assertEqual(sorted(fks), ["FK_Customers_Region", "FK_OrderLines_Orders", "FK_OrderLines_Product",
                                       "FK_Orders_Customers"])
        self.assertEqual(fks["FK_Orders_Customers"].columns, ["CustomerID"])
        self.assertEqual(fks["FK_Orders_Customers"].referenced_table, "dbo.Customers")

    def test_fixture_drop_keeps_its_recommendation_with_a_note(self):
        conn = connection_from_fixture("sales_long")
        indexes = fetch_indexes(conn, "Sales")
        recs = by_name(analyse_database("Sales", indexes, server(80), Config(), fetch_foreign_keys(conn, "Sales")))
        self.assertEqual(recs["IX_Orders_Customer"].action, DROP)
        self.assertIn("foreign key FK_Orders_Customers is also supported by IX_Orders_Customer_Date",
                      recs["IX_Orders_Customer"].reasons)
        self.assertEqual(recs["IX_OrderLines_Product"].action, CONSOLIDATE)
        self.assertIn("foreign key FK_OrderLines_Product is also supported by IX_OrderLines_Product_Price",
                      recs["IX_OrderLines_Product"].reasons)
