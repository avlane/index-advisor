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
    notes: list = field(default_factory=list)


def _index_name(table, keys):
    columns = "_".join(re.sub(r"\W+", "", key) for key in keys[:3])
    return "IX_%s_%s" % (re.sub(r"\W+", "", table), columns)


def suggest(missing, thresholds, database=None):
    """Suggestions above the score threshold, best first. Keys are equality columns, then inequality."""
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
    found.sort(key=lambda s: -s.score)
    return found
