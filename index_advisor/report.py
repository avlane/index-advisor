"""Render a Report as text, JSON or Markdown."""
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


RENDERERS = {"text": render_text}


def render(report, fmt="text", show_keep=False):
    try:
        renderer = RENDERERS[fmt]
    except KeyError:
        raise ValueError("unknown report format: %s" % fmt) from None
    return renderer(report, show_keep=show_keep)
