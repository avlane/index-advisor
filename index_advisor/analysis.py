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


STATS_RESET_WARNING = (
    "SQL Server started on %s (%.1f days ago). Index usage counters are cleared by a restart, "
    "so they only describe that period; an index used by a month-end or quarterly job can look "
    "unused. Drop recommendations are downgraded to review until the server has been up for at "
    "least %g days.")


def _check_unused(rec, thresholds, uptime_days):
    ix = rec.index
    if ix.reads == 0 and ix.user_updates > 0:
        if uptime_days < thresholds.min_uptime_days:
            rec.action = REVIEW
            rec.reasons.append("no reads recorded, but the counters only cover %.1f days since the last "
                               "restart" % uptime_days)
        else:
            rec.action = DROP
            rec.reasons.append("no reads recorded, but %s updates keep it maintained" % format(ix.user_updates, ","))


def analyse_database(database, indexes, server, config):
    th = config.thresholds
    warnings = []
    if server.uptime_days < th.min_uptime_days:
        warnings.append(STATS_RESET_WARNING % (
            server.start_time.strftime("%Y-%m-%d %H:%M"), server.uptime_days, th.min_uptime_days))
    recs = []
    for ix in indexes:
        rec = Recommendation(ix)
        _check_unused(rec, th, server.uptime_days)
        if rec.action == KEEP:
            rec.reasons.append("%s reads, %s updates" % (format(ix.reads, ","), format(ix.user_updates, ",")))
        recs.append(rec)
    return DatabaseAnalysis(database, recs, warnings)
