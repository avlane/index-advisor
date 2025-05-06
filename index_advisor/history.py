"""A rolling history of index usage counters.

sys.dm_db_index_usage_stats starts again from zero whenever the instance restarts.
With --history FILE every run appends the current counters to FILE, so that later
runs can look at more than the time since the last restart.
"""
import json
import os
from dataclasses import replace
from datetime import datetime

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


def _parse(text):
    return datetime.fromisoformat(text)


def _run_total(points):
    """Total of a counter that starts again from zero at a reset.

    `points` is [(instance start, value)] in time order. A new instance start, or a
    value lower than the one before, closes the previous stretch; stretches are added up.
    """
    total, previous, start = 0, 0, None
    for run, value in points:
        if (start is not None and run != start) or value < previous:
            total += previous
        previous, start = value, run
    return total + previous


def totals(doc):
    """({index key: {counter: total}}, days observed) over all recorded snapshots.

    Counters also restart without an instance restart: a database that is detached,
    set offline or closed by AUTO_CLOSE loses its index usage rows. A fall in a
    counter is therefore treated as a reset, like a new instance start.
    """
    snaps = sorted(doc["snapshots"], key=lambda s: s["taken"])
    runs = {}
    for snap in snaps:
        runs.setdefault(snap["start_time"], []).append(snap)
    observed = sum((max(_parse(s["taken"]) for s in group) - _parse(start)).total_seconds() / 86400.0
                   for start, group in runs.items())
    keys = {key for snap in snaps for key in snap["indexes"]}
    zero = dict.fromkeys(COUNTERS, 0)
    result = {}
    for key in keys:
        result[key] = {
            name: _run_total([(snap["start_time"], snap["indexes"].get(key, zero)[name]) for snap in snaps])
            for name in COUNTERS
        }
    return result, observed


def apply_history(doc, collection):
    """Replace the current counters of the collected indexes with the totals over the history."""
    summed, observed = totals(doc)
    for ix in collection.all_indexes():
        total = summed.get(index_key(ix))
        if total is None:
            continue
        ix.user_seeks, ix.user_scans = total["seeks"], total["scans"]
        ix.user_lookups, ix.user_updates = total["lookups"], total["updates"]
        ix.has_usage_row = True
    collection.server = replace(collection.server, observed_days=observed)
