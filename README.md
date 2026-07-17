# index-advisor

Reads SQL Server index usage statistics and produces a keep / drop / consolidate report with the
reasons for each recommendation, plus scripts to review. It never changes anything on the server:
the scripts it writes have every DROP and CREATE commented out, and the tool has no option to run them.

## What it looks at

Per database:

* `sys.indexes`, `sys.index_columns`, `sys.data_spaces`, `sys.partitions` and `sys.dm_db_partition_stats`:
  keys, included columns, filters, filegroup or partition scheme, compression, size
* `sys.dm_db_index_usage_stats`: seeks, scans, lookups and updates since the instance started
* `sys.foreign_keys`: so the only index supporting a foreign key is not proposed for dropping
* `sys.availability_databases_cluster`: databases in an availability group
* `sys.dm_db_index_physical_stats` (only with `--physical`): fragmentation

Per server:

* `sys.dm_os_sys_info.sqlserver_start_time`: when the usage counters were last cleared
* `sys.dm_db_missing_index_details` and friends: missing-index suggestions
* `SERVERPROPERTY('EngineEdition')`: whether index rebuilds can run online

## Recommendations

| action | when |
| --- | --- |
| keep | the index is used, or backs a constraint, or is not a rowstore index, or is listed under `[keep]` |
| drop | exact duplicate; left prefix of an index that already covers its columns; written but never read (with enough observed time) |
| consolidate | left prefix of an index that lacks some of its included columns: add them to the wider index, then drop the narrow one |
| review | disabled; no usage recorded at all; reads far below writes; counters too young to trust; in an availability group; the only index supporting a foreign key |

Primary keys, unique constraints, unique indexes and the clustered index are never dropped, however
little they are read. Indexes smaller than `min_size_mb` are left alone.

### The usage counters reset

`sys.dm_db_index_usage_stats` is cleared when the instance restarts (and when a database is detached
or closed). Right after a restart every index looks unused, and indexes that serve month-end or
quarterly jobs look unused until the job has run. The report therefore prints `sqlserver_start_time`,
and `min_uptime_days` (default 30) decides how long the counters must have been observed before
"never read" becomes a drop recommendation; before that it is a review item and a warning is added to
the report and the scripts. With `--history` the observation window can span restarts, see below.

In an availability group the counters are per replica, so reads on readable secondaries are not
included. "Unused" is a review item for those databases.

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
index-advisor --server SQLPROD01 -d Sales -d "Report*" --show-keep
index-advisor --server SQLPROD01 --config advisor.toml --format json -o review.json
index-advisor --server SQLPROD01 --format markdown --top 10 -o review.md
index-advisor --server SQLPROD01 --scripts-dir review/
index-advisor --server SQLPROD01 --physical --min-pages 5000
index-advisor --server SQLPROD01 --history history.json --exit-code
index-advisor --from-dump dump.json --config advisor.toml
index-advisor --help
```

The account needs `VIEW SERVER STATE` and `VIEW DATABASE STATE` (`VIEW SERVER PERFORMANCE STATE` on SQL
Server 2022) and `VIEW DEFINITION` in the databases. For a SQL login pass `--user NAME` and set
`INDEX_ADVISOR_PASSWORD`.

| option | meaning |
| --- | --- |
| `--server NAME` | instance to analyse, for example `SQLPROD01` or `SQLPROD01,1433` |
| `--from-dump FILE` | analyse a file written by `--dump` instead of connecting |
| `--config FILE` | TOML thresholds and exclusions |
| `-d`, `--database NAME` | only these databases; wildcards work; overrides `[exclude]` |
| `--format` | `text` (default), `json` or `markdown` |
| `-o`, `--output FILE` | write the report to a file |
| `--show-keep` | also list indexes that should be kept |
| `--top N` | at most N recommendations per database in text and Markdown (JSON is never cut) |
| `--scripts-dir DIR` | write the review scripts |
| `--physical`, `--min-pages N` | read fragmentation for indexes of at least N pages |
| `--history FILE` | accumulate usage counters across runs |
| `--min-size-mb MB` | leave smaller indexes alone |
| `--exit-code` | exit with 1 when there is a drop or consolidate recommendation |
| `--dump FILE` | save everything read from the server |
| `--user`, `--driver`, `--no-encrypt`, `--trust-server-certificate` | connection options |

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
  CONSOLIDATE dbo.OrderLines.IX_OrderLines_Product (187.5 MB)
      - it is a left prefix of IX_OrderLines_Product_Price; merge it by adding INCLUDE (Quantity) to IX_OrderLines_Product_Price, then drop it
  ...
  By table:
    dbo.Orders: 3 drop, 0 consolidate, 118.8 MB
    dbo.OrderLines: 0 drop, 1 consolidate, 0.0 MB
  Missing index suggestions (not applied):
    IX_Orders_CustomerID_Status_OrderDate ON dbo.Orders (CustomerID, Status, OrderDate) INCLUDE (Total)
        score 3,991,530: 2,200 uses, average cost 18.4, average impact 98%

15 indexes analysed. The 3 recommended for dropping hold 118.8 MB and absorbed 1,440 writes since the last restart.
```

(Abridged output for the fixture in `tests/fixtures`, hence the 2023 date.)

## Configuration file

`--config advisor.toml`; see `examples/advisor.toml` for every key.

* `[thresholds]`: `min_uptime_days`, `min_updates`, `low_read_ratio`, `min_missing_score`, `min_size_mb`
* `[exclude]`: `databases` and `tables` (`schema.table`) patterns that are never analysed
* `[keep]`: `indexes` patterns (`database.schema.table.index`) that are never recommended for a change

Patterns use `*` and `?` and ignore case.

## Scripts

`--scripts-dir DIR` writes, per database and only when there is something to propose:

* `NAME.drop-candidates.sql`: the DROP INDEX statements, commented out, each with its reasons
* `NAME.recreate-dropped.sql`: the matching CREATE INDEX statements, for rollback; they keep the filegroup
  or partition scheme and uniform data compression
* `NAME.consolidate.sql`: widen the kept index (`DROP_EXISTING = ON`, plus `ONLINE = ON` on editions that
  support it), drop the narrow one, and a rollback
* `NAME.missing-indexes.sql`: CREATE INDEX proposals from the missing-index DMVs, commented out. Requests
  that are left prefixes of a larger request are merged, and a request an existing index nearly covers is
  turned into a proposal to widen that index

Review them, uncomment what you accept, and run them yourself. Before dropping, search code, jobs and plan
guides for INDEX hints that name the index; they fail once it is gone.

## Counting across restarts: `--history`

`--history history.json` appends the current counters of every index to the file on each run, and the
recommendations then use the totals over all recorded runs. A restart, or a database that is detached or
closed, starts a new stretch; stretches are added up. `min_uptime_days` is compared with the days covered
by the history, so a weekly scheduled run turns "up for 4 days" into "observed for 90 days" after a few
months. The file holds counters only (no query text or data) and is trimmed to the latest 400 snapshots.
Activity between the last run before a restart and the restart itself is lost.

## Working offline: `--dump` and `--from-dump`

`--dump dump.json` saves everything read from the server. `--from-dump dump.json` repeats the analysis
from that file without a connection, for example with a different configuration, or on a machine that
cannot reach the server.

## Running it on a schedule

`examples/weekly.ps1` runs it weekly with `--history`, writes the report and the review scripts to a dated
folder, and passes `--exit-code` through so that a job step can fail when there is something to review.

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
* usage history: adding up counters, restarts and resets
* report formats and script generation (the statements are compared as text)
* the command line, with a fake connection that answers each query from a JSON fixture, and the
  `python -m index_advisor` entry point
* row mapping in `queries.py`, connection-string building, and `connect()` with a fake `pyodbc`

## Limitations

* Counters can only be added up for the time the tool actually ran (see `--history`).
* Indexes that exist to serve plan guides, index hints, or rare jobs cannot be recognised from usage numbers.
* Columnstore, XML, spatial and hash indexes are not analysed. Compression is only captured when it is the
  same for all partitions.
* The missing-index DMVs are cleared by a restart and by changes to the table, and hold at most 600 entries.

## Development

```
python3 -m unittest discover
```

See `CHANGELOG.md` for the version history.
