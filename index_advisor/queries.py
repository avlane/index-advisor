"""SQL used to read index metadata and usage, and the row mapping.

Index metadata and the partition stats DMV belong to one database, so the index
queries run after a USE of that database.
"""
from datetime import datetime

from .model import Index, ServerInfo
from .sqlnames import quote_name

SERVER_SQL = """
SELECT @@SERVERNAME AS server_name,
       si.sqlserver_start_time AS start_time,
       GETDATE() AS now,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
       CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)) AS version
FROM sys.dm_os_sys_info AS si;
"""

DATABASES_SQL = """
SELECT name
FROM sys.databases
WHERE database_id > 4
  AND state_desc = 'ONLINE'
  AND source_database_id IS NULL
  AND is_distributor = 0
  AND HAS_DBACCESS(name) = 1
ORDER BY name;
"""

INDEX_SQL = """
SELECT o.object_id, s.name AS schema_name, o.name AS table_name, i.name AS index_name, i.index_id,
       i.type_desc, i.is_unique, i.is_primary_key, i.is_unique_constraint, i.is_disabled,
       i.filter_definition, i.fill_factor,
       ps.row_count, ps.used_pages,
       CASE WHEN u.index_id IS NULL THEN 0 ELSE 1 END AS has_usage_row,
       u.user_seeks, u.user_scans, u.user_lookups, u.user_updates,
       u.last_user_seek, u.last_user_scan, u.last_user_lookup, u.last_user_update
FROM sys.indexes AS i
JOIN sys.objects AS o ON o.object_id = i.object_id
JOIN sys.schemas AS s ON s.schema_id = o.schema_id
LEFT JOIN (
    SELECT object_id, index_id, SUM(row_count) AS row_count, SUM(used_page_count) AS used_pages
    FROM sys.dm_db_partition_stats
    GROUP BY object_id, index_id
) AS ps ON ps.object_id = i.object_id AND ps.index_id = i.index_id
LEFT JOIN sys.dm_db_index_usage_stats AS u
       ON u.database_id = DB_ID() AND u.object_id = i.object_id AND u.index_id = i.index_id
WHERE o.is_ms_shipped = 0
  AND o.type IN ('U', 'V')
  AND i.type > 0
  AND i.is_hypothetical = 0
ORDER BY s.name, o.name, i.index_id;
"""


def rows_as_dicts(cursor):
    names = [col[0].lower() for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _dt(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _count(value):
    return int(value or 0)


def _latest(*values):
    values = [_dt(v) for v in values if v is not None]
    return max(values) if values else None


def index_from_row(database, row):
    return Index(
        database=database,
        schema=row["schema_name"],
        table=row["table_name"],
        name=row["index_name"],
        object_id=int(row["object_id"]),
        index_id=int(row["index_id"]),
        type_desc=row["type_desc"],
        is_unique=bool(row["is_unique"]),
        is_primary_key=bool(row["is_primary_key"]),
        is_unique_constraint=bool(row["is_unique_constraint"]),
        is_disabled=bool(row["is_disabled"]),
        filter_definition=row["filter_definition"],
        fill_factor=_count(row["fill_factor"]),
        row_count=_count(row["row_count"]),
        used_pages=_count(row["used_pages"]),
        user_seeks=_count(row["user_seeks"]),
        user_scans=_count(row["user_scans"]),
        user_lookups=_count(row["user_lookups"]),
        user_updates=_count(row["user_updates"]),
        last_user_read=_latest(row["last_user_seek"], row["last_user_scan"], row["last_user_lookup"]),
        last_user_update=_latest(row["last_user_update"]),
        has_usage_row=bool(row["has_usage_row"]),
    )


def fetch_server_info(conn):
    cur = conn.cursor()
    try:
        cur.execute(SERVER_SQL)
        row = rows_as_dicts(cur)[0]
        return ServerInfo(row["server_name"], _dt(row["start_time"]), _dt(row["now"]),
                          row["edition"] or "", row["version"] or "")
    finally:
        cur.close()


def fetch_databases(conn):
    cur = conn.cursor()
    try:
        cur.execute(DATABASES_SQL)
        return [row["name"] for row in rows_as_dicts(cur)]
    finally:
        cur.close()


def fetch_indexes(conn, database):
    """Return the Index objects of one database (heaps are not included)."""
    cur = conn.cursor()
    try:
        cur.execute("USE " + quote_name(database))
        cur.execute(INDEX_SQL)
        return [index_from_row(database, row) for row in rows_as_dicts(cur)]
    finally:
        cur.close()
