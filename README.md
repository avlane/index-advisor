# index-advisor

Reads SQL Server index usage statistics and produces a keep / drop / consolidate
report with the reasons for each recommendation, plus scripts to review. It never
changes anything on the server: the scripts it writes have every DROP and CREATE
commented out, and the tool has no option to run them.

## What it looks at

Per database:

* `sys.indexes`, `sys.index_columns` and `sys.dm_db_partition_stats`: keys, included
  columns, filters, size
* `sys.dm_db_index_usage_stats`: seeks, scans, lookups and updates since the instance started
* `sys.foreign_keys`: so the only index supporting a foreign key is not proposed for dropping
* `sys.dm_db_index_physical_stats` (only with `--physical`): fragmentation

Per server:

* `sys.dm_os_sys_info.sqlserver_start_time`: when the usage counters were last cleared
* `sys.dm_db_missing_index_details` and friends: missing-index suggestions

## Recommendations

| action | when |
| --- | --- |
| keep | the index is used, or backs a constraint, or is not a rowstore index |
| drop | exact duplicate; left prefix of an index that already covers its columns; written but never read (with enough uptime) |
| consolidate | left prefix of an index that lacks some of its included columns: add them to the wider index, then drop the narrow one |
| review | disabled; no usage recorded at all; reads far below writes; counters too young to trust; the only index supporting a foreign key |

Primary keys, unique constraints, unique indexes and the clustered index are never
dropped, however little they are read.

### The usage counters reset

`sys.dm_db_index_usage_stats` is cleared when the instance restarts (and when a database
is detached or closed). Right after a restart every index looks unused, and indexes that
serve month-end or quarterly jobs look unused until the job has run. The report
therefore prints `sqlserver_start_time`, and `min_uptime_days` (default 30) decides how
long the server must have been up before "never read" becomes a drop recommendation;
before that it is a review item and a warning is added to the report and the scripts.

## Install

```
pip install .
pip install ".[sqlserver]"      # adds pyodbc, needed to talk to a server
```

Python 3.11 or newer and the Microsoft ODBC driver for SQL Server (version 18 by default;
`--driver "ODBC Driver 17 for SQL Server"` for 17). Driver 18 encrypts by default; add
`--trust-server-certificate` for a self-signed certificate.

## Usage

```
index-advisor --server SQLPROD01
index-advisor --server SQLPROD01 -d Sales --show-keep
index-advisor --server SQLPROD01 --config advisor.toml --format json -o review.json
index-advisor --server SQLPROD01 --format markdown -o review.md
index-advisor --server SQLPROD01 --scripts-dir review/
index-advisor --server SQLPROD01 --physical --min-pages 5000
index-advisor --help
```

The account needs `VIEW SERVER STATE` and `VIEW DATABASE STATE` (`VIEW SERVER PERFORMANCE
STATE` on SQL Server 2022) and `VIEW DEFINITION` in the databases. For a SQL login pass
`--user NAME` and set `INDEX_ADVISOR_PASSWORD`.

### Example

```
index-advisor report for SQLPROD01
SQL Server started 2023-04-21 04:00 (80.2 days ago)

Database Sales: 15 indexes analysed - 3 drop, 1 consolidate, 3 review, 8 keep
  DROP        dbo.Orders.IX_Orders_Customer (40.6 MB)
      - it is a left prefix of IX_Orders_Customer_Date, which already covers its included columns
      - its 5,200 reads would be served by IX_Orders_Customer_Date (57.8 MB against 40.6 MB)
      - foreign key FK_Orders_Customers is also supported by IX_Orders_Customer_Date
  ...
```

(Generated from the fixture in `tests/fixtures`, hence the 2023 date.)

## Scripts

`--scripts-dir DIR` writes, per database and only when there is something to propose:

* `NAME.drop-candidates.sql`: the DROP INDEX statements, commented out, each with its reasons
* `NAME.recreate-dropped.sql`: the matching CREATE INDEX statements, for rollback
* `NAME.consolidate.sql`: widen the kept index (`DROP_EXISTING = ON`), drop the narrow one, and a rollback
* `NAME.missing-indexes.sql`: CREATE INDEX proposals from the missing-index DMVs, commented out

Review them, uncomment what you accept, and run them yourself. Before dropping, search
code, jobs and plan guides for INDEX hints that name the index; they fail once it is gone.

## Exit codes

| code | meaning |
| --- | --- |
| 0 | finished |
| 1 | finished, and with `--exit-code` there is at least one drop or consolidate recommendation |
| 3 | usage, configuration, connection or query error |
| 4 | finished, but some databases (or the missing-index DMVs) could not be read |

## Tests

Tested with `python3 -m unittest discover` (no pyodbc and no server needed):

* the recommendation rules, with hand-built indexes and with fixtures
* report formats and script generation (the statements are compared as text)
* the command line, with a fake connection that answers each query from a JSON fixture
* row mapping in `queries.py`, connection-string building, and `connect()` with a fake `pyodbc`

## Development

```
python3 -m unittest discover
```

## Configuration file

`--config advisor.toml`; see `examples/advisor.toml` for every key.

* `[thresholds]`: `min_uptime_days`, `min_updates`, `low_read_ratio`, `min_missing_score`, `min_size_mb`
* `[exclude]`: `databases` and `tables` (`schema.table`) patterns, never analysed (naming a database with `-d` overrides this)
* `[keep]`: `indexes` patterns (`database.schema.table.index`) that are never recommended for a change

Patterns use `*` and `?` and ignore case.

## Counting across restarts: `--history`

`--history history.json` appends the current counters of every index to the file on each run, and
the recommendations then use the totals over all recorded runs of the instance. A restart, or a
database that is detached or closed, starts a new stretch; stretches are added up. `min_uptime_days`
is compared with the days covered by the history, so a weekly scheduled run turns "up for 4 days"
into "observed for 90 days" after a few months. The file holds counters only (no query text or data).
It is trimmed to the latest 400 snapshots. It can only count what was running when the tool ran:
a restart between two runs loses the activity since the previous run.

## Working offline: `--dump` and `--from-dump`

`--dump dump.json` saves everything read from the server. `--from-dump dump.json` repeats the
analysis from that file, without a connection, for example with a different configuration, or on a
machine that cannot reach the server.

## Running it on a schedule

`examples/weekly.ps1` runs it weekly with `--history`, writes the report and the review scripts to a
dated folder, and passes `--exit-code` through so that a job step can fail when there is something to
review.
