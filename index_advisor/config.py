"""Thresholds and exclusions for the recommendations, read from a TOML file."""
import fnmatch
import tomllib
from dataclasses import dataclass, field, replace


class ConfigError(ValueError):
    """The configuration file is unreadable or invalid."""


@dataclass(frozen=True)
class Thresholds:
    min_uptime_days: float = 30.0  # below this the usage counters are not trusted
    min_updates: int = 1000  # writes needed before a low read/write ratio is worth a look
    low_read_ratio: float = 0.01  # reads divided by writes below this is "low value"
    min_missing_score: float = 10000.0  # cost * impact * uses below this is not worth a suggestion
    min_size_mb: float = 0.0  # smaller indexes are never recommended for a change


def _matches(value, patterns):
    value = value.lower()
    return any(fnmatch.fnmatchcase(value, pattern.lower()) for pattern in patterns)


@dataclass
class Config:
    thresholds: Thresholds = field(default_factory=Thresholds)
    exclude_databases: list = field(default_factory=list)  # patterns for database names
    exclude_tables: list = field(default_factory=list)  # patterns for schema.table
    keep_indexes: list = field(default_factory=list)  # patterns for database.schema.table.index

    def database_excluded(self, name):
        return _matches(name, self.exclude_databases)

    def table_excluded(self, schema, table):
        return _matches("%s.%s" % (schema, table), self.exclude_tables)

    def index_kept(self, ix):
        return _matches("%s.%s" % (ix.database, ix.full_name), self.keep_indexes)


_THRESHOLD_TYPES = {
    "min_uptime_days": (int, float),
    "min_updates": (int,),
    "low_read_ratio": (int, float),
    "min_missing_score": (int, float),
    "min_size_mb": (int, float),
}


def _table(data, key, allowed):
    section = data.get(key, {})
    if not isinstance(section, dict):
        raise ConfigError("[%s] must be a table" % key)
    unknown = set(section) - set(allowed)
    if unknown:
        raise ConfigError("[%s]: unknown key(s): %s" % (key, ", ".join(sorted(unknown))))
    return section


def _patterns(section, key, where):
    value = section.get(key, [])
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
        raise ConfigError("%s %s must be a list of non-empty patterns" % (where, key))
    return list(value)


def parse_config(data):
    if not isinstance(data, dict):
        raise ConfigError("the top level of the config must be a table")
    unknown = set(data) - {"thresholds", "exclude", "keep"}
    if unknown:
        raise ConfigError("unknown key(s): %s" % ", ".join(sorted(unknown)))
    section = _table(data, "thresholds", _THRESHOLD_TYPES)
    for key, value in section.items():
        if isinstance(value, bool) or not isinstance(value, _THRESHOLD_TYPES[key]) or value < 0:
            raise ConfigError("[thresholds] %s must be a non-negative number" % key)
    exclude = _table(data, "exclude", ("databases", "tables"))
    keep = _table(data, "keep", ("indexes",))
    return Config(
        replace(Thresholds(), **section),
        exclude_databases=_patterns(exclude, "databases", "[exclude]"),
        exclude_tables=_patterns(exclude, "tables", "[exclude]"),
        keep_indexes=_patterns(keep, "indexes", "[keep]"),
    )


def load_config(path):
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc)) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("%s is not valid TOML: %s" % (path, exc)) from exc
    return parse_config(data)
