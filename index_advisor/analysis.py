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
    protected: bool = False  # backs a constraint or is not a rowstore index: never a drop candidate
    merge_includes: list = field(default_factory=list)  # columns other indexes want added to this one


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


def _protected_reason(ix):
    """Why an index must stay regardless of how much it is used, or None."""
    if ix.is_primary_key:
        return "primary key"
    if ix.is_unique_constraint:
        return "unique constraint"
    if ix.is_unique:
        return "unique index, enforces uniqueness"
    if ix.type_desc == "CLUSTERED":
        return "clustered index"
    if ix.type_desc != "NONCLUSTERED":
        return "%s index, not analysed" % ix.type_desc.lower()
    return None


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
    elif ix.reads == 0 and not ix.has_usage_row:
        rec.action = REVIEW
        rec.reasons.append("no reads or writes recorded at all: the table may be idle, or the index "
                           "has not been touched since the counters started")


def _escalate(rec, action):
    """Move a recommendation to a stronger action, never to a weaker one."""
    if ACTION_ORDER[action] < ACTION_ORDER[rec.action]:
        rec.action = action


def _key_tuple(ix):
    return tuple((c.name.lower(), c.descending) for c in ix.keys)


def _filter_key(ix):
    return " ".join((ix.filter_definition or "").lower().split())


def _check_duplicates(recs):
    """Indexes on the same table with identical keys, includes and filter are redundant."""
    groups = {}
    for rec in recs:
        ix = rec.index
        if ix.type_desc != "NONCLUSTERED" or ix.is_disabled:
            continue
        key = (ix.schema.lower(), ix.table.lower(), _key_tuple(ix),
               frozenset(c.lower() for c in ix.includes), _filter_key(ix))
        groups.setdefault(key, []).append(rec)
    for group in groups.values():
        if len(group) < 2:
            continue
        # keep the index that backs a constraint, then the most used, then the oldest
        group.sort(key=lambda r: (not r.protected, -r.index.reads, r.index.index_id))
        keeper = group[0]
        for rec in group[1:]:
            if rec.protected:
                continue
            _escalate(rec, DROP)
            rec.reasons.append("exact duplicate of %s (same keys, includes and filter)" % keeper.index.name)
            rec.related.append(keeper.index.name)
            if rec.index.reads:
                rec.reasons.append("its %s reads can be served by %s" % (format(rec.index.reads, ","), keeper.index.name))
            keeper.reasons.append("%s is an exact duplicate of this index" % rec.index.name)


def _add_usage_notes(recs):
    for rec in recs:
        if rec.action == KEEP and not rec.protected:
            ix = rec.index
            rec.reasons.insert(0, "%s reads, %s updates" % (format(ix.reads, ","), format(ix.user_updates, ",")))


def _covered(ix):
    """Lower-case names of the columns an index can return without a lookup."""
    return {c.name.lower() for c in ix.keys} | {c.lower() for c in ix.includes}


def _outranks(a, b):
    """For two indexes with the same keys: does `a` win as the merge target?"""
    return (a.reads, -a.index_id) > (b.reads, -b.index_id)


def _merge_candidates(src, table_recs):
    ix = src.index
    n = len(ix.keys)
    found = []
    for tgt in table_recs:
        t = tgt.index
        if tgt is src or t.is_disabled or tgt.action == DROP:
            continue
        if t.type_desc not in ("CLUSTERED", "NONCLUSTERED") or _filter_key(t) != _filter_key(ix):
            continue
        if len(t.keys) < n or _key_tuple(t)[:n] != _key_tuple(ix):
            continue
        if len(t.keys) == n and not _outranks(t, ix):
            continue
        found.append(tgt)
    return found


def _check_overlaps(recs):
    """An index whose keys are a left prefix of another index can usually be dropped.

    If it has included columns the wider index lacks, they are added to the wider
    index instead (consolidate).
    """
    tables = {}
    for rec in recs:
        tables.setdefault((rec.index.schema.lower(), rec.index.table.lower()), []).append(rec)
    targets = {}
    for table_recs in tables.values():
        for src in table_recs:
            ix = src.index
            if src.protected or ix.type_desc != "NONCLUSTERED" or ix.is_disabled or not ix.keys or src.action == DROP:
                continue
            options = _merge_candidates(src, table_recs)
            if options:
                wanted = {c.lower() for c in ix.includes}
                targets[id(src)] = min(options, key=lambda r: (
                    not (r.index.type_desc == "CLUSTERED" or wanted <= _covered(r.index)),
                    -r.index.reads, len(r.index.keys) + len(r.index.includes), r.index.index_id))
    by_id = {id(r): r for r in recs}
    for key, tgt in list(targets.items()):
        seen = {key}
        while id(tgt) in targets and id(tgt) not in seen:  # the target is itself merged into something wider
            seen.add(id(tgt))
            tgt = targets[id(tgt)]
        targets[key] = tgt
    for key, tgt in targets.items():
        src, t = by_id[key], tgt.index
        wanted = [c for c in src.index.includes]
        missing = [] if t.type_desc == "CLUSTERED" else [c for c in wanted if c.lower() not in _covered(t)]
        same = len(t.keys) == len(src.index.keys)
        how = "has the same keys as" if same else "is a left prefix of"
        extra = " (%.1f MB against %.1f MB)" % (t.size_mb, src.index.size_mb)
        src.related.append(t.name)
        if src.index.reads:
            src.reasons.append("its %s reads would be served by %s%s" % (format(src.index.reads, ","), t.name, extra))
        if missing:
            _escalate(src, CONSOLIDATE)
            src.reasons.insert(0, "%s %s; merge it by adding INCLUDE (%s) to %s, then drop it" % (
                "it " + how, t.name, ", ".join(missing), t.name))
            for column in missing:
                if column not in tgt.merge_includes:
                    tgt.merge_includes.append(column)
        else:
            _escalate(src, DROP)
            src.reasons.insert(0, "it %s %s, which already covers its included columns" % (how, t.name))
        tgt.reasons.append("%s can be merged into this index" % src.index.name)


def _check_low_value(rec, thresholds):
    """Reads that are a tiny fraction of the writes: probably costs more than it saves."""
    ix = rec.index
    if rec.action != KEEP or ix.reads == 0 or ix.user_updates < thresholds.min_updates:
        return
    ratio = ix.reads / ix.user_updates
    if ratio < thresholds.low_read_ratio:
        rec.action = REVIEW
        rec.reasons.append("reads are only %.2f%% of writes (%s reads, %s updates); it may cost more than it saves" % (
            ratio * 100, format(ix.reads, ","), format(ix.user_updates, ",")))


def _supports(ix, fk):
    """Does the index lead with the foreign key columns (in any order)?"""
    n = len(fk.columns)
    lead = [c.name.lower() for c in ix.keys[:n]]
    return ix.object_id == fk.object_id and len(lead) == n and set(lead) == {c.lower() for c in fk.columns}


def _check_foreign_keys(recs, foreign_keys):
    """Dropping the only index that leads with a foreign key's columns slows deletes and updates of the parent."""
    for rec in recs:
        if rec.action not in (DROP, CONSOLIDATE):
            continue
        for fk in foreign_keys:
            if not _supports(rec.index, fk):
                continue
            others = [o for o in recs if o is not rec and o.action not in (DROP, CONSOLIDATE) and _supports(o.index, fk)]
            if others:
                rec.reasons.append("foreign key %s is also supported by %s" % (fk.name, others[0].index.name))
            else:
                rec.action = REVIEW
                rec.reasons.append(
                    "it is the only index leading with the columns of foreign key %s (to %s); without it, deletes and "
                    "updates of the referenced rows scan this table" % (fk.name, fk.referenced_table))


def analyse_database(database, indexes, server, config, foreign_keys=()):
    th = config.thresholds
    warnings = []
    if server.uptime_days < th.min_uptime_days:
        warnings.append(STATS_RESET_WARNING % (
            server.start_time.strftime("%Y-%m-%d %H:%M"), server.uptime_days, th.min_uptime_days))
    recs = []
    for ix in indexes:
        rec = Recommendation(ix)
        reason = _protected_reason(ix)
        if reason:
            rec.protected = True
            rec.reasons.append("%s; %s reads, %s updates" % (reason, format(ix.reads, ","), format(ix.user_updates, ",")))
        elif ix.is_disabled:
            rec.action = REVIEW
            rec.reasons.append("disabled: it holds no data and is not maintained; drop it, or rebuild it on purpose")
        else:
            _check_unused(rec, th, server.uptime_days)
            _check_low_value(rec, th)
        recs.append(rec)
    _check_duplicates(recs)
    _check_overlaps(recs)
    _check_foreign_keys(recs, foreign_keys)
    _add_usage_notes(recs)
    return DatabaseAnalysis(database, recs, warnings)


@dataclass
class Report:
    """The result for a whole server."""

    server: object
    databases: list
    errors: list = field(default_factory=list)  # (database, message) for databases that could not be read

    def totals(self):
        counts = {KEEP: 0, DROP: 0, CONSOLIDATE: 0, REVIEW: 0}
        reclaimable = 0.0
        writes = 0
        for db in self.databases:
            for action, n in db.counts().items():
                counts[action] += n
            reclaimable += sum(r.index.size_mb for r in db.recommendations if r.action == DROP)
            writes += sum(r.index.user_updates for r in db.recommendations if r.action == DROP)
        return {"indexes": sum(counts.values()), "by_action": counts, "drop_size_mb": round(reclaimable, 1),
                "drop_updates": writes}
