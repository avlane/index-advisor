"""Plain data objects for index metadata and usage."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ServerInfo:
    server_name: str
    start_time: datetime  # sys.dm_os_sys_info.sqlserver_start_time
    now: datetime
    edition: str = ""
    version: str = ""
    observed_days: Optional[float] = None  # days covered by a --history file, when one is used

    @property
    def uptime_days(self):
        return (self.now - self.start_time).total_seconds() / 86400.0

    @property
    def trusted_days(self):
        """How long the usage counters have been observed: the history if there is one, else the uptime."""
        return self.uptime_days if self.observed_days is None else max(self.uptime_days, self.observed_days)


@dataclass
class IndexColumn:
    name: str
    descending: bool = False

    def sql(self):
        return "[%s]%s" % (self.name.replace("]", "]]"), " DESC" if self.descending else "")


@dataclass
class Index:
    """One row-store, columnstore or other index of a user table or indexed view."""

    database: str
    schema: str
    table: str
    name: str
    object_id: int
    index_id: int
    type_desc: str
    is_unique: bool = False
    is_primary_key: bool = False
    is_unique_constraint: bool = False
    is_disabled: bool = False
    filter_definition: Optional[str] = None
    fill_factor: int = 0
    data_space: Optional[str] = None  # filegroup or partition scheme name
    data_space_type: Optional[str] = None  # "FG" or "PS"
    data_space_is_default: bool = True
    partition_column: Optional[str] = None
    compression: Optional[str] = None  # NONE, ROW, PAGE, or MIXED when partitions differ
    row_count: int = 0
    used_pages: int = 0
    user_seeks: int = 0
    user_scans: int = 0
    user_lookups: int = 0
    user_updates: int = 0
    last_user_read: Optional[datetime] = None
    last_user_update: Optional[datetime] = None
    has_usage_row: bool = False
    fragmentation: Optional[float] = None  # percent, from --physical
    page_count: int = 0  # leaf pages seen by --physical
    keys: list = field(default_factory=list)  # IndexColumn, in key order
    includes: list = field(default_factory=list)  # column names

    @property
    def reads(self):
        return self.user_seeks + self.user_scans + self.user_lookups

    @property
    def size_mb(self):
        return self.used_pages * 8 / 1024.0

    @property
    def table_name(self):
        return "%s.%s" % (self.schema, self.table)

    @property
    def full_name(self):
        return "%s.%s.%s" % (self.schema, self.table, self.name)


@dataclass
class MissingIndex:
    """One entry of sys.dm_db_missing_index_details with its group statistics."""

    database: str
    schema: str
    table: str
    equality: list
    inequality: list
    includes: list
    seeks: int = 0
    scans: int = 0
    avg_cost: float = 0.0
    avg_impact: float = 0.0  # percent
    compiles: int = 0
    last_use: Optional[datetime] = None

    @property
    def score(self):
        """The usual improvement measure: cost * impact * number of uses."""
        return self.avg_cost * self.avg_impact * (self.seeks + self.scans)

    @property
    def table_name(self):
        return "%s.%s" % (self.schema, self.table)


@dataclass
class ForeignKey:
    """A foreign key on a child table; the index that supports it leads with `columns`."""

    name: str
    object_id: int
    columns: list
    referenced_table: str
