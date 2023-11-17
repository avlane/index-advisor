import unittest

from index_advisor.connection import build_connection_string, connect


class ConnectionStringTest(unittest.TestCase):
    def test_defaults(self):
        cs = build_connection_string("SQLPROD01")
        self.assertIn("DRIVER={ODBC Driver 18 for SQL Server}", cs)
        self.assertIn("SERVER=SQLPROD01;", cs)
        self.assertIn("Encrypt=yes", cs)
        self.assertIn("Trusted_Connection=yes", cs)
        self.assertNotIn("TrustServerCertificate", cs)

    def test_options(self):
        cs = build_connection_string("SQLDR02", encrypt=False, trust_server_certificate=True)
        self.assertIn("Encrypt=no", cs)
        self.assertIn("TrustServerCertificate=yes", cs)

    def test_sql_login_values_are_braced(self):
        cs = build_connection_string("SQLPROD01", user="svc_idx", password="p}ss;word")
        self.assertIn("UID={svc_idx}", cs)
        self.assertIn("PWD={p}}ss;word}", cs)
        self.assertNotIn("Trusted_Connection", cs)


class FakePyodbc:
    def __init__(self):
        self.calls = []

    def connect(self, cs, **kwargs):
        self.calls.append((cs, kwargs))
        return object()


class ConnectTest(unittest.TestCase):
    def test_connect_is_autocommit(self):
        fake = FakePyodbc()
        connect("SQLPROD01", pyodbc_module=fake, trust_server_certificate=True)
        (cs, kwargs), = fake.calls
        self.assertIn("TrustServerCertificate=yes", cs)
        self.assertEqual(kwargs, {"autocommit": True, "timeout": 15})
