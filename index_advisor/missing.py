"""Turn missing-index DMV entries into reviewable suggestions."""
import re
from dataclasses import dataclass, field


@dataclass
class Suggestion:
    missing: object
    name: str
    keys: list
    includes: list
    score: float
    extends: object = None  # an existing index that already leads with the equality columns
    add_columns: list = field(default_factory=list)  # what that index lacks
    notes: list = field(default_factory=list)


def _index_name(table, keys):
    columns = "_".join(re.sub(r"\W+", "", key) for key in keys[:3])
    return "IX_%s_%s" % (re.sub(r"\W+", "", table), columns)


def _covered(ix):
    return {c.name.lower() for c in ix.keys} | {c.lower() for c in ix.includes}


def _find_existing(missing, keys, includes, indexes):
    """An existing index on the table whose leading keys are the equality columns of the request."""
    equality = {c.lower() for c in missing.equality}
    if not equality:
        return None
    for ix in indexes:
        if ix.schema.lower() != missing.schema.lower() or ix.table.lower() != missing.table.lower():
            continue
        if ix.is_disabled or ix.type_desc not in ("CLUSTERED", "NONCLUSTERED"):
            continue
        lead = [k.name.lower() for k in ix.keys[:len(equality)]]
        if len(lead) == len(equality) and set(lead) == equality:
            return ix
    return None


def suggest(missing, thresholds, database=None, indexes=()):
    """Suggestions above the score threshold, best first. Keys are equality columns, then inequality.

    `indexes` should be the indexes that will still exist after the recommendations; a
    request that an existing index nearly satisfies is flagged instead of presented as new.
    """
    found = []
    for m in missing:
        if database is not None and m.database.lower() != database.lower():
            continue
        if m.score < thresholds.min_missing_score:
            continue
        keys = m.equality + m.inequality
        lowered = {k.lower() for k in keys}
        includes = [c for c in m.includes if c.lower() not in lowered]
        suggestion = Suggestion(m, _index_name(m.table, keys), keys, includes, m.score)
        existing = _find_existing(m, keys, includes, indexes)
        if existing is not None:
            suggestion.extends = existing
            # a clustered index already holds every column of the table
            suggestion.add_columns = [] if existing.type_desc == "CLUSTERED" else [
                c for c in keys + includes if c.lower() not in _covered(existing)]
            if suggestion.add_columns:
                suggestion.notes.append(
                    "%s already leads with the equality columns; consider adding INCLUDE (%s) to it instead of a new index"
                    % (existing.name, ", ".join(suggestion.add_columns)))
            else:
                suggestion.notes.append(
                    "%s already covers this request; check for implicit conversions, hints or stale statistics "
                    "before adding an index" % existing.name)
        found.append(suggestion)
    found.sort(key=lambda s: -s.score)
    return found
