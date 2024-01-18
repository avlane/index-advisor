"""Render a Report as text, JSON or Markdown."""
import json

from .analysis import ACTION_ORDER, KEEP


def _mb(value):
    return "%.1f GB" % (value / 1024.0) if value >= 1024 else "%.1f MB" % value


def _ordered(recs, show_keep):
    shown = [r for r in recs if show_keep or r.action != KEEP]
    return sorted(shown, key=lambda r: (ACTION_ORDER[r.action], -r.index.size_mb, r.index.full_name))


def render_text(report, show_keep=False):
    server = report.server
    lines = [
        "index-advisor report for %s" % (server.server_name or "(unknown server)"),
        "SQL Server started %s (%.1f days ago)" % (server.start_time.strftime("%Y-%m-%d %H:%M"), server.uptime_days),
    ]
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
    for database, message in report.errors:
        lines.append("")
        lines.append("Database %s could not be read: %s" % (database, message))
    totals = report.totals()
    lines.append("")
    lines.append("%d indexes analysed. Indexes recommended for dropping hold %s." % (
        totals["indexes"], _mb(totals["drop_size_mb"])))
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
        },
        "totals": report.totals(),
        "databases": [
            {
                "name": db.database,
                "counts": db.counts(),
                "warnings": db.warnings,
                "recommendations": [_recommendation_doc(r) for r in _ordered(db.recommendations, True)],
            }
            for db in report.databases
        ],
        "errors": [{"database": name, "message": message} for name, message in report.errors],
    }
    return json.dumps(doc, indent=2) + "\n"


RENDERERS = {"text": render_text, "json": render_json}


def render(report, fmt="text", show_keep=False):
    try:
        renderer = RENDERERS[fmt]
    except KeyError:
        raise ValueError("unknown report format: %s" % fmt) from None
    return renderer(report, show_keep=show_keep)
