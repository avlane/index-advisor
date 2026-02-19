"""Render a Report as text, JSON or Markdown."""
import json

from .analysis import ACTION_ORDER, KEEP


def _mb(value):
    return "%.1f GB" % (value / 1024.0) if value >= 1024 else "%.1f MB" % value


def _ordered(recs, show_keep):
    shown = [r for r in recs if show_keep or r.action != KEEP]
    return sorted(shown, key=lambda r: (ACTION_ORDER[r.action], -r.index.size_mb, r.index.full_name))


def _totals_sentence(totals):
    return "%d indexes analysed. The %d recommended for dropping hold %s and absorbed %s writes since the last restart." % (
        totals["indexes"], totals["by_action"]["drop"], _mb(totals["drop_size_mb"]), format(totals["drop_updates"], ","))


def render_text(report, show_keep=False):
    server = report.server
    lines = [
        "index-advisor report for %s" % (server.server_name or "(unknown server)"),
        "SQL Server started %s (%.1f days ago)" % (server.start_time.strftime("%Y-%m-%d %H:%M"), server.uptime_days),
    ]
    if server.observed_days is not None:
        lines.append("Usage history covers %.1f days across restarts" % server.observed_days)
    for db in report.databases:
        counts = db.counts()
        lines.append("")
        lines.append("Database %s: %d indexes analysed - %d drop, %d consolidate, %d review, %d keep" % (
            db.database, len(db.recommendations), counts["drop"], counts["consolidate"], counts["review"], counts["keep"]))
        for warning in db.warnings:
            lines.append("  WARNING: " + warning)
        for rec in _ordered(db.recommendations, show_keep):
            lines.append("  %-11s %s (%s)" % (rec.action.upper(), rec.index.full_name, _mb(rec.index.size_mb)))
            for reason in rec.reasons:
                lines.append("      - " + reason)
        tables = db.table_summary()
        if tables:
            lines.append("  By table:")
            for table, drops, merges, mb in tables:
                lines.append("    %s: %d drop, %d consolidate, %s" % (table, drops, merges, _mb(mb)))
        if db.suggestions:
            lines.append("  Missing index suggestions (not applied):")
            for s in db.suggestions:
                lines.append("    %s ON %s.%s (%s)%s" % (
                    s.name, s.missing.schema, s.missing.table, ", ".join(s.keys),
                    " INCLUDE (%s)" % ", ".join(s.includes) if s.includes else ""))
                lines.append("        score %s: %s uses, average cost %.1f, average impact %.0f%%" % (
                    format(round(s.score), ","), format(s.missing.seeks + s.missing.scans, ","),
                    s.missing.avg_cost, s.missing.avg_impact))
                for note in s.notes:
                    lines.append("        - " + note)
    for database, message in report.errors:
        lines.append("")
        lines.append("Database %s could not be read: %s" % (database, message))
    totals = report.totals()
    lines.append("")
    lines.append(_totals_sentence(totals))
    return "\n".join(lines) + "\n"


def _recommendation_doc(rec):
    ix = rec.index
    return {
        "schema": ix.schema,
        "table": ix.table,
        "index": ix.name,
        "index_id": ix.index_id,
        "type": ix.type_desc,
        "action": rec.action,
        "reasons": rec.reasons,
        "related": rec.related,
        "reads": ix.reads,
        "updates": ix.user_updates,
        "size_mb": round(ix.size_mb, 1),
        "last_read": ix.last_user_read.isoformat(timespec="seconds") if ix.last_user_read else None,
    }


def _suggestion_doc(s):
    m = s.missing
    return {
        "name": s.name,
        "schema": m.schema,
        "table": m.table,
        "keys": s.keys,
        "includes": s.includes,
        "score": round(s.score),
        "uses": m.seeks + m.scans,
        "avg_cost": m.avg_cost,
        "avg_impact": m.avg_impact,
        "extends": s.extends.name if s.extends else None,
        "add_columns": s.add_columns,
        "notes": s.notes,
    }


def render_json(report, show_keep=False):
    """All recommendations, including keep: consumers filter on `action` themselves."""
    server = report.server
    doc = {
        "server": {
            "name": server.server_name,
            "version": server.version,
            "edition": server.edition,
            "started": server.start_time.isoformat(timespec="seconds"),
            "now": server.now.isoformat(timespec="seconds"),
            "uptime_days": round(server.uptime_days, 1),
            "observed_days": None if server.observed_days is None else round(server.observed_days, 1),
        },
        "totals": report.totals(),
        "databases": [
            {
                "name": db.database,
                "counts": db.counts(),
                "warnings": db.warnings,
                "recommendations": [_recommendation_doc(r) for r in _ordered(db.recommendations, True)],
                "tables": [{"table": t, "drop": d, "consolidate": c, "drop_size_mb": round(mb, 1)}
                           for t, d, c, mb in db.table_summary()],
                "suggestions": [_suggestion_doc(s) for s in db.suggestions],
            }
            for db in report.databases
        ],
        "errors": [{"database": name, "message": message} for name, message in report.errors],
    }
    return json.dumps(doc, indent=2) + "\n"


def _cell(value):
    """Escape text for a Markdown table cell."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_markdown(report, show_keep=False):
    server = report.server
    lines = [
        "# Index review: %s" % (server.server_name or "(unknown server)"),
        "",
        "SQL Server started %s (%.1f days ago)." % (server.start_time.strftime("%Y-%m-%d %H:%M"), server.uptime_days),
    ]
    for db in report.databases:
        counts = db.counts()
        lines += ["", "## %s" % db.database, "",
                  "%d indexes analysed: %d drop, %d consolidate, %d review, %d keep." % (
                      len(db.recommendations), counts["drop"], counts["consolidate"], counts["review"], counts["keep"])]
        for warning in db.warnings:
            lines += ["", "> **Warning:** " + _cell(warning)]
        recs = _ordered(db.recommendations, show_keep)
        if recs:
            lines += ["", "| Action | Index | Size | Reads | Updates | Reasons |", "| --- | --- | ---: | ---: | ---: | --- |"]
            for rec in recs:
                ix = rec.index
                lines.append("| %s | `%s` | %s | %s | %s | %s |" % (
                    rec.action, ix.full_name, _mb(ix.size_mb), format(ix.reads, ","), format(ix.user_updates, ","),
                    "<br>".join(_cell(r) for r in rec.reasons)))
        tables = db.table_summary()
        if tables:
            lines += ["", "| Table | Drop | Consolidate | Space held by drops |", "| --- | ---: | ---: | ---: |"]
            lines += ["| `%s` | %d | %d | %s |" % (t, d, c, _mb(mb)) for t, d, c, mb in tables]
        if db.suggestions:
            lines += ["", "Missing index suggestions (not applied):", "",
                      "| Suggested index | Keys | Include | Score | Notes |", "| --- | --- | --- | ---: | --- |"]
            for s in db.suggestions:
                lines.append("| `%s` on `%s.%s` | %s | %s | %s | %s |" % (
                    s.name, s.missing.schema, s.missing.table, _cell(", ".join(s.keys)),
                    _cell(", ".join(s.includes)), format(round(s.score), ","), "<br>".join(_cell(n) for n in s.notes)))
    for database, message in report.errors:
        lines += ["", "**%s could not be read:** %s" % (_cell(database), _cell(message))]
    totals = report.totals()
    lines += ["", _totals_sentence(totals)]
    return "\n".join(lines) + "\n"


RENDERERS = {"text": render_text, "json": render_json, "markdown": render_markdown}


def render(report, fmt="text", show_keep=False):
    try:
        renderer = RENDERERS[fmt]
    except KeyError:
        raise ValueError("unknown report format: %s" % fmt) from None
    return renderer(report, show_keep=show_keep)
