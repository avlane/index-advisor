"""Save a Collection as JSON and load it again, so that an analysis can be repeated offline."""
import json
from dataclasses import asdict
from datetime import datetime

from .collect import Collection, DatabaseData
from .model import ForeignKey, Index, IndexColumn, MissingIndex, ServerInfo

FORMAT = 1


class DumpError(ValueError):
    """The dump file cannot be read."""


def _default(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    raise TypeError("cannot serialise %r" % (value,))


def dump_collection(path, collection):
    doc = {"format": FORMAT, "collection": asdict(collection)}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, default=_default, indent=1)
        fh.write("\n")


def _dt(value):
    return None if value is None else datetime.fromisoformat(value)


def _index(data):
    data = dict(data)
    data["keys"] = [IndexColumn(**key) for key in data["keys"]]
    data["last_user_read"] = _dt(data["last_user_read"])
    data["last_user_update"] = _dt(data["last_user_update"])
    return Index(**data)


def _missing(data):
    data = dict(data)
    data["last_use"] = _dt(data["last_use"])
    return MissingIndex(**data)


def load_collection(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("format") != FORMAT:
            raise DumpError("%s is not an index-advisor dump (format %d)" % (path, FORMAT))
        data = doc["collection"]
        server = dict(data["server"])
        server["start_time"], server["now"] = _dt(server["start_time"]), _dt(server["now"])
        databases = [
            DatabaseData(
                name=d["name"],
                indexes=[_index(i) for i in d["indexes"]],
                foreign_keys=[ForeignKey(**f) for f in d["foreign_keys"]],
                in_availability_group=d["in_availability_group"],
            )
            for d in data["databases"]
        ]
        return Collection(ServerInfo(**server), databases, [_missing(m) for m in data["missing"]],
                          [tuple(e) for e in data["errors"]])
    except OSError as exc:
        raise DumpError("cannot read %s: %s" % (path, exc)) from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, DumpError):
            raise
        raise DumpError("%s is not a usable dump: %s" % (path, exc)) from exc
