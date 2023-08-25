"""Turn index metadata and usage statistics into recommendations."""
from dataclasses import dataclass, field

KEEP, DROP, CONSOLIDATE, REVIEW = "keep", "drop", "consolidate", "review"
ACTION_ORDER = {DROP: 0, CONSOLIDATE: 1, REVIEW: 2, KEEP: 3}


@dataclass
class Recommendation:
    index: object
    action: str = KEEP
    reasons: list = field(default_factory=list)
    related: list = field(default_factory=list)  # names of the indexes this one is compared with


@dataclass
class DatabaseAnalysis:
    database: str
    recommendations: list
    warnings: list = field(default_factory=list)

    def counts(self):
        counts = {KEEP: 0, DROP: 0, CONSOLIDATE: 0, REVIEW: 0}
        for rec in self.recommendations:
            counts[rec.action] += 1
        return counts


def _check_unused(rec, thresholds):
    ix = rec.index
    if ix.reads == 0 and ix.user_updates > 0:
        rec.action = DROP
        rec.reasons.append("no reads recorded, but %s updates keep it maintained" % format(ix.user_updates, ","))


def analyse_database(database, indexes, server, config):
    recs = []
    for ix in indexes:
        rec = Recommendation(ix)
        _check_unused(rec, config.thresholds)
        if rec.action == KEEP:
            rec.reasons.append("%s reads, %s updates" % (format(ix.reads, ","), format(ix.user_updates, ",")))
        recs.append(rec)
    return DatabaseAnalysis(database, recs)
