"""Read everything the analysis needs from a connection, and analyse it."""
from dataclasses import dataclass, field

from .analysis import KEEP, REVIEW, Report, analyse_database
from .missing import suggest
from .queries import (attach_physical, fetch_availability_databases, fetch_databases, fetch_foreign_keys,
                      fetch_indexes, fetch_missing_indexes, fetch_server_info)


@dataclass
class DatabaseData:
    name: str
    indexes: list
    foreign_keys: list = field(default_factory=list)
    in_availability_group: bool = False


@dataclass
class Collection:
    """Everything read from one server, before any analysis."""

    server: object
    databases: list
    missing: list = field(default_factory=list)
    errors: list = field(default_factory=list)  # (database, message)

    def all_indexes(self):
        return [ix for data in self.databases for ix in data.indexes]


def collect(conn, select, physical=False, min_pages=1000):
    """Read the server, the chosen databases and the missing-index DMVs.

    `select` receives the names of all online databases and returns the ones to read.
    Problems with a single database or with the missing-index DMVs are collected in
    `errors`; problems with the server query itself raise.
    """
    server = fetch_server_info(conn)
    names = select(fetch_databases(conn))
    errors = []
    try:
        missing = fetch_missing_indexes(conn)
    except Exception as exc:
        missing = []
        errors.append(("(missing-index DMVs)", str(exc)))
    try:
        in_group = {n.lower() for n in fetch_availability_databases(conn)}
    except Exception:
        in_group = set()  # the view does not exist before SQL Server 2012, or is not readable
    databases = []
    for name in names:
        try:
            indexes = fetch_indexes(conn, name)
            foreign_keys = fetch_foreign_keys(conn, name)
            if physical:
                attach_physical(conn, name, indexes, min_pages)
        except Exception as exc:
            errors.append((name, str(exc)))
            continue
        databases.append(DatabaseData(name, indexes, foreign_keys, name.lower() in in_group))
    return Collection(server, databases, missing, errors)


def analyse_collection(collection, config):
    analyses = []
    for data in collection.databases:
        analysis = analyse_database(data.name, data.indexes, collection.server, config,
                                    data.foreign_keys, data.in_availability_group)
        survivors = [r.index for r in analysis.recommendations if r.action in (KEEP, REVIEW)]
        analysis.suggestions = suggest(collection.missing, config.thresholds, data.name, survivors)
        analyses.append(analysis)
    return Report(collection.server, analyses, list(collection.errors))
