"""A rolling history of index usage counters.

sys.dm_db_index_usage_stats starts again from zero whenever the instance restarts.
With --history FILE every run appends the current counters to FILE, so that later
runs can look at more than the time since the last restart.
"""
import json
import os

VERSION = 1
MAX_SNAPSHOTS = 400  # about a year of daily runs
COUNTERS = ("seeks", "scans", "lookups", "updates")


class HistoryError(ValueError):
    """The history file cannot be used."""


def index_key(ix):
    return "%s.%s" % (ix.database, ix.full_name)


def snapshot_of(collection):
    server = collection.server
    return {
        "start_time": server.start_time.isoformat(timespec="seconds"),
        "taken": server.now.isoformat(timespec="seconds"),
        "indexes": {
            index_key(ix): {
                "seeks": ix.user_seeks, "scans": ix.user_scans,
                "lookups": ix.user_lookups, "updates": ix.user_updates,
            }
            for ix in collection.all_indexes() if ix.has_usage_row
        },
    }


def load_history(path):
    """The history document, or None when the file does not exist yet."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryError("cannot read history %s: %s" % (path, exc)) from exc
    if not isinstance(doc, dict) or doc.get("version") != VERSION or not isinstance(doc.get("snapshots"), list):
        raise HistoryError("%s is not an index-advisor history file (version %d)" % (path, VERSION))
    return doc


def save_history(path, doc):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    os.replace(temporary, path)


def record_history(path, collection):
    """Add this run's counters to the history file and return the updated document."""
    name = collection.server.server_name
    doc = load_history(path) or {"version": VERSION, "server": name, "snapshots": []}
    if doc.get("server", "").lower() != name.lower():
        raise HistoryError("%s holds the history of %s, not %s" % (path, doc.get("server"), name))
    doc["snapshots"].append(snapshot_of(collection))
    del doc["snapshots"][:-MAX_SNAPSHOTS]
    save_history(path, doc)
    return doc
