"""Builders for small, hand-made index lists used by the unit tests."""
import itertools
from datetime import datetime, timedelta

from index_advisor.config import Config
from index_advisor.model import Index, IndexColumn, ServerInfo

NOW = datetime(2023, 7, 10, 10, 0, 0)
_ids = itertools.count(1)


def server(uptime_days=90):
    return ServerInfo("SQLPROD01", NOW - timedelta(days=uptime_days), NOW, "Enterprise Edition", "15.0")


def ix(name, keys, includes=(), table="Orders", reads=0, updates=0, index_id=None, **kw):
    """An index; `keys` entries are column names, optionally followed by ' DESC'."""
    columns = []
    for key in keys:
        col, _, direction = key.partition(" ")
        columns.append(IndexColumn(col, direction == "DESC"))
    fields = dict(
        database="Sales", schema="dbo", table=table, name=name, object_id=sum(ord(ch) for ch in table),
        index_id=index_id or next(_ids) + 1, type_desc="NONCLUSTERED", keys=columns, includes=list(includes),
        user_seeks=reads, user_updates=updates, used_pages=1000, row_count=100000, has_usage_row=True,
    )
    fields.update(kw)
    return Index(**fields)


def analyse(indexes, uptime_days=90, config=None):
    from index_advisor.analysis import analyse_database

    return analyse_database("Sales", indexes, server(uptime_days), config or Config())


def by_name(result):
    return {rec.index.name: rec for rec in result.recommendations}
