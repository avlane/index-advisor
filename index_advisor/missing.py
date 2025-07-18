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
    merged: int = 0  # how many smaller requests were folded into this one


def _index_name(table, keys):
    columns = "_".join(re.sub(r"\W+", "", key) for key in keys[:3])
    return "IX_%s_%s" % (re.sub(r"\W+", "", table), columns)


def _covered(ix):
    return {c.name.lower() for c in ix.keys} | {c.lower() for c in ix.includes}


def _find_existing(missing, indexes):
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


def _same_table(a, b):
    return (a.missing.database.lower(), a.missing.schema.lower(), a.missing.table.lower()) == (
        b.missing.database.lower(), b.missing.schema.lower(), b.missing.table.lower())


def _merge_similar(found):
    """Fold a request whose keys are a left prefix of another request on the same table into it.

    The optimizer records one entry per query shape, so a handful of near-identical
    entries is common; creating an index for each would mostly add write overhead.
    """
    kept = []
    for s in sorted(found, key=lambda s: (-len(s.keys), -s.score)):
        wanted = [k.lower() for k in s.keys]
        home = next((t for t in kept if _same_table(s, t) and [k.lower() for k in t.keys[:len(wanted)]] == wanted), None)
        if home is None:
            kept.append(s)
            continue
        have = {c.lower() for c in home.keys + home.includes}
        home.includes += [c for c in s.includes if c.lower() not in have]
        home.score += s.score
        home.merged += 1
        home.notes.append("also satisfies a request for (%s)%s, score %s" % (
            ", ".join(s.keys), " INCLUDE (%s)" % ", ".join(s.includes) if s.includes else "", format(round(s.score), ",")))
    return kept


def suggest(missing, thresholds, database=None, indexes=()):
    """Suggestions above the score threshold, best first. Keys are equality columns, then inequality.

    Requests that are left prefixes of a larger request on the same table are merged into it.
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
        found.append(Suggestion(m, _index_name(m.table, keys), keys, includes, m.score))
    found = _merge_similar(found)
    for s in found:
        existing = _find_existing(s.missing, indexes)
        if existing is None:
            continue
        s.extends = existing
        # a clustered index already holds every column of the table
        s.add_columns = [] if existing.type_desc == "CLUSTERED" else [
            c for c in s.keys + s.includes if c.lower() not in _covered(existing)]
        if s.add_columns:
            s.notes.append(
                "%s already leads with the equality columns; consider adding INCLUDE (%s) to it instead of a new index"
                % (existing.name, ", ".join(s.add_columns)))
        else:
            s.notes.append(
                "%s already covers this request; check for implicit conversions, hints or stale statistics "
                "before adding an index" % existing.name)
    found.sort(key=lambda s: -s.score)
    return found
