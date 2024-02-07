"""A fake DB-API connection that answers the index queries from a JSON fixture."""
import json
import os

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, *params):
        self.conn.executed.append((sql, params))
        text = sql.strip()
        if text.startswith("USE "):
            self.conn.current_db = text[4:].strip().strip("[]").replace("]]", "]")
            self.description, self._rows = None, []
            return self
        for marker, supplier in self.conn.responders:
            if marker in sql:
                rows = supplier(self.conn)
                cols = list(rows[0]) if rows else []
                self.description = [(c, None, None, None, None, None, None) for c in cols]
                self._rows = [tuple(r[c] for c in cols) for r in rows]
                return self
        raise AssertionError("no fake response for: " + text[:60])

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, doc):
        self.doc = doc
        self.executed = []
        self.current_db = None
        self.closed = False
        self.responders = [
            ("sys.dm_os_sys_info", lambda c: [c.doc["server"]]),
            ("FROM sys.databases", lambda c: [{"name": n} for n in c.doc["databases"]]),
            ("sys.dm_db_index_usage_stats", lambda c: c.db_rows("indexes")),
            ("sys.index_columns", lambda c: c.db_rows("columns")),
            ("sys.dm_db_missing_index_details", lambda c: c.doc["missing"]),
        ]

    def db_rows(self, key):
        return self.doc["per_database"][self.current_db][key]

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def load_fixture(name):
    with open(os.path.join(FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def connection_from_fixture(name):
    return FakeConnection(load_fixture(name))
