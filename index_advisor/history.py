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


def totals(doc):
    """({index key: {counter: total}}, days observed) over all recorded instance runs.

    Within one run of the instance the counters only grow, so the last snapshot of
    that run holds its total; the runs are added up.
    """
    runs = {}
    for snap in doc["snapshots"]:
        runs.setdefault(snap["start_time"], []).append(snap)
    result, observed = {}, 0.0
    for start, snaps in runs.items():
        observed += (max(_parse(s["taken"]) for s in snaps) - _parse(start)).total_seconds() / 86400.0
        peak = {}
        for snap in snaps:
            for key, counters in snap["indexes"].items():
                best = peak.setdefault(key, dict.fromkeys(COUNTERS, 0))
                for name in COUNTERS:
                    best[name] = max(best[name], counters[name])
        for key, best in peak.items():
            total = result.setdefault(key, dict.fromkeys(COUNTERS, 0))
            for name in COUNTERS:
                total[name] += best[name]
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
