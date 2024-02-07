"""Thresholds for the recommendations, read from a TOML file."""
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


@dataclass
class Config:
    thresholds: Thresholds = field(default_factory=Thresholds)


_THRESHOLD_TYPES = {
    "min_uptime_days": (int, float),
    "min_updates": (int,),
    "low_read_ratio": (int, float),
    "min_missing_score": (int, float),
}


def parse_config(data):
    if not isinstance(data, dict):
        raise ConfigError("the top level of the config must be a table")
    unknown = set(data) - {"thresholds"}
    if unknown:
        raise ConfigError("unknown key(s): %s" % ", ".join(sorted(unknown)))
    section = data.get("thresholds", {})
    if not isinstance(section, dict):
        raise ConfigError("[thresholds] must be a table")
    unknown = set(section) - set(_THRESHOLD_TYPES)
    if unknown:
        raise ConfigError("[thresholds]: unknown key(s): %s" % ", ".join(sorted(unknown)))
    for key, value in section.items():
        if isinstance(value, bool) or not isinstance(value, _THRESHOLD_TYPES[key]) or value < 0:
            raise ConfigError("[thresholds] %s must be a non-negative number" % key)
    return Config(replace(Thresholds(), **section))


def load_config(path):
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc)) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("%s is not valid TOML: %s" % (path, exc)) from exc
    return parse_config(data)
