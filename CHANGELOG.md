# Changelog

This is the first changelog. Releases before 0.4.0 were not tagged; their changes are summarised here.

## 0.5.0 - 2026-07-16

* `--dump` and `--from-dump` to repeat an analysis without a connection
* Per-table summary, `--top`, wildcards in `--database`
* README rewritten

## 0.4.0 - 2025-10-30

* Exclusions and a keep list in the configuration file (`[exclude]`, `[keep]`)
* Availability-group databases: "unused" becomes a review item because reads on secondaries are invisible
* `--history FILE` records usage counters between runs so recommendations can span instance restarts;
  `min_size_mb` / `--min-size-mb` keeps small indexes out of the recommendations
* Missing-index requests that are left prefixes of a larger request on the same table are merged
* `--exit-code`, and `ONLINE = ON` in generated statements on editions that support it

## Earlier

* Keep / drop / consolidate / review recommendations: unused, duplicate, left-prefix and low-value indexes
* Stats-reset warning based on `sqlserver_start_time`
* Foreign key protection, fragmentation notes (`--physical`), missing-index suggestions
* Text, JSON and Markdown reports; drop, rollback, consolidation and missing-index scripts
* Recreate scripts keep filegroup, partition scheme and data compression
