"""SQL used to read index metadata and usage, and the row mapping.

Index metadata and the partition stats DMV belong to one database, so the index
queries run after a USE of that database.
"""
from datetime import datetime

from .model import Index, IndexColumn, MissingIndex, ServerInfo
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


def attach_columns(indexes, rows):
    """Fill in the key columns (with direction) and included columns of each index."""
    by_id = {(ix.object_id, ix.index_id): ix for ix in indexes}
    for row in rows:
        ix = by_id.get((int(row["object_id"]), int(row["index_id"])))
        if ix is None:
            continue
        if row["is_included_column"]:
            ix.includes.append(row["column_name"])
        else:
            ix.keys.append(IndexColumn(row["column_name"], bool(row["is_descending_key"])))


def fetch_indexes(conn, database):
    """Return the Index objects of one database (heaps are not included)."""
    cur = conn.cursor()
    try:
        cur.execute("USE " + quote_name(database))
        cur.execute(INDEX_SQL)
        indexes = [index_from_row(database, row) for row in rows_as_dicts(cur)]
        cur.execute(COLUMNS_SQL)
        attach_columns(indexes, rows_as_dicts(cur))
        return indexes
    finally:
        cur.close()


COLUMNS_SQL = """
SELECT ic.object_id, ic.index_id, c.name AS column_name, ic.key_ordinal,
       ic.is_descending_key, ic.is_included_column
FROM sys.index_columns AS ic
JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.objects AS o ON o.object_id = ic.object_id
WHERE o.is_ms_shipped = 0
  AND (ic.key_ordinal > 0 OR ic.is_included_column = 1)
ORDER BY ic.object_id, ic.index_id, ic.is_included_column, ic.key_ordinal, ic.index_column_id;
"""


MISSING_SQL = """
SELECT DB_NAME(mid.database_id) AS database_name, mid.statement AS table_statement,
       mid.equality_columns, mid.inequality_columns, mid.included_columns,
       migs.unique_compiles, migs.user_seeks, migs.user_scans,
       migs.avg_total_user_cost, migs.avg_user_impact, migs.last_user_seek, migs.last_user_scan
FROM sys.dm_db_missing_index_details AS mid
JOIN sys.dm_db_missing_index_groups AS mig ON mig.index_handle = mid.index_handle
JOIN sys.dm_db_missing_index_group_stats AS migs ON migs.group_handle = mig.index_group_handle
WHERE mid.database_id > 4
ORDER BY database_name, table_statement;
"""


def split_identifiers(text):
    """Unquote a run of bracket-quoted identifiers, as in "[a], [b]]c]" or "[db].[schema].[table]".

    Names may contain commas, dots and (doubled) closing brackets, so splitting on
    separators is not safe.
    """
    names, i = [], 0
    while i < len(text):
        if text[i] != "[":
            i += 1
            continue
        i += 1
        chars = []
        while i < len(text):
            if text[i] == "]":
                if text[i + 1:i + 2] == "]":
                    chars.append("]")
                    i += 2
                    continue
                break
            chars.append(text[i])
            i += 1
        names.append("".join(chars))
        i += 1
    return names


def parse_columns(text):
    return split_identifiers(text) if text else []


def parse_statement(statement):
    database, schema, table = split_identifiers(statement)
    return database, schema, table


def missing_from_row(row):
    database, schema, table = parse_statement(row["table_statement"])
    return MissingIndex(
        database=database, schema=schema, table=table,
        equality=parse_columns(row["equality_columns"]),
        inequality=parse_columns(row["inequality_columns"]),
        includes=parse_columns(row["included_columns"]),
        seeks=_count(row["user_seeks"]), scans=_count(row["user_scans"]),
        avg_cost=float(row["avg_total_user_cost"] or 0), avg_impact=float(row["avg_user_impact"] or 0),
        compiles=_count(row["unique_compiles"]),
        last_use=_latest(row["last_user_seek"], row["last_user_scan"]),
    )


def fetch_missing_indexes(conn):
    """Missing-index suggestions for every database on the server (the DMVs are server-wide)."""
    cur = conn.cursor()
    try:
        cur.execute(MISSING_SQL)
        return [missing_from_row(row) for row in rows_as_dicts(cur)]
    finally:
        cur.close()
