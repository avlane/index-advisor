"""Command line interface for index-advisor."""
import argparse
import os
import sys
from dataclasses import replace

from . import __version__
from .collect import analyse_collection, collect
from .config import Config, ConfigError, load_config
from .connection import DEFAULT_DRIVER
from .dump import DumpError, dump_collection, load_collection
from .history import HistoryError, apply_history, record_history
from .report import render
from .scripts import generate_scripts

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR, EXIT_PARTIAL = 0, 1, 3, 4


class _Parser(argparse.ArgumentParser):
    """Usage errors exit with 3, the same code as other errors."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, "%s: error: %s\n" % (self.prog, message))


def build_parser():
    p = _Parser(
        prog="index-advisor",
        description="Read index usage statistics and recommend which indexes to keep, drop or consolidate. "
                    "Read-only: nothing is changed on the server.",
        epilog="Exit codes: 0 done, 1 recommendations exist (only with --exit-code), 3 usage/config/connection "
               "error, 4 done but some databases could not be read.",
    )
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    p.add_argument("--server", help="instance to analyse, e.g. SQLPROD01 or SQLPROD01,1433")
    p.add_argument("--from-dump", metavar="FILE", help="analyse a file written by --dump instead of connecting")
    p.add_argument("--config", help="TOML file with thresholds and exclusions")
    p.add_argument("-d", "--database", action="append", default=[], metavar="NAME",
                   help="only analyse this database (repeatable)")
    p.add_argument("--format", choices=("text", "json", "markdown"), default="text", help="report format (default: text)")
    p.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    p.add_argument("--show-keep", action="store_true", help="also list the indexes that should be kept")
    p.add_argument("--top", type=int, default=0, metavar="N",
                   help="list at most N recommendations per database in the text and Markdown reports "
                        "(default: all); the JSON report always has everything")
    p.add_argument("--physical", action="store_true",
                   help="also read index fragmentation (sys.dm_db_index_physical_stats, LIMITED mode); "
                        "slow on large databases")
    p.add_argument("--min-pages", type=int, default=1000, metavar="N",
                   help="with --physical, ignore indexes smaller than N pages (default: %(default)s)")
    p.add_argument("--exit-code", action="store_true",
                   help="exit with 1 when there is at least one drop or consolidate recommendation")
    p.add_argument("--min-size-mb", type=float, metavar="MB",
                   help="never recommend changes to indexes smaller than this (overrides the config file)")
    p.add_argument("--dump", metavar="FILE",
                   help="save everything read from the server in FILE, to repeat the analysis offline")
    p.add_argument("--history", metavar="FILE",
                   help="record the usage counters of this run in FILE (see the README)")
    p.add_argument("--scripts-dir", metavar="DIR",
                   help="write review scripts (drop candidates, rollback, consolidation) into DIR; nothing is run")
    p.add_argument("--user", help="SQL login; the password is read from INDEX_ADVISOR_PASSWORD")
    p.add_argument("--driver", default=DEFAULT_DRIVER, help="ODBC driver name (default: %(default)s)")
    p.add_argument("--no-encrypt", action="store_true", help="connect without encryption")
    p.add_argument("--trust-server-certificate", action="store_true",
                   help="accept the server certificate without validating it")
    return p


def default_connect(args):
    from .connection import connect

    return connect(
        args.server,
        driver=args.driver,
        user=args.user,
        password=os.environ.get("INDEX_ADVISOR_PASSWORD"),
        encrypt=not args.no_encrypt,
        trust_server_certificate=args.trust_server_certificate,
    )


def _error(message):
    print("index-advisor: %s" % message, file=sys.stderr)
    return EXIT_ERROR


def _select(names, wanted, config):
    """Explicitly named databases win over [exclude] databases."""
    if not wanted:
        return [n for n in names if not config.database_excluded(n)]
    lookup = {n.lower(): n for n in names}
    missing = [w for w in wanted if w.lower() not in lookup]
    if missing:
        raise LookupError("database not found (or not online): %s" % ", ".join(missing))
    return [lookup[w.lower()] for w in wanted]


def _acquire(args, config, connect):
    """The Collection to analyse, read from a dump or from the server. Raises LookupError or Exception."""
    if args.from_dump:
        collection = load_collection(args.from_dump)
        chosen = set(_select([d.name for d in collection.databases], args.database, config))
        collection.databases = [d for d in collection.databases if d.name in chosen]
        return collection
    conn = (connect or default_connect)(args)
    try:
        return collect(conn, lambda names: _select(names, args.database, config),
                       physical=args.physical, min_pages=args.min_pages)
    finally:
        conn.close()


def main(argv=None, connect=None, stdout=None):
    stdout = stdout or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.server) == bool(args.from_dump):
        parser.error("give exactly one of --server and --from-dump")
    if args.from_dump and (args.dump or args.physical):
        parser.error("--dump and --physical need a live connection (--server)")
    try:
        config = load_config(args.config) if args.config else Config()
    except ConfigError as exc:
        return _error(exc)
    if args.min_size_mb is not None:
        config.thresholds = replace(config.thresholds, min_size_mb=args.min_size_mb)
    try:
        collection = _acquire(args, config, connect)
    except LookupError as exc:
        return _error(exc)
    except DumpError as exc:
        return _error(exc)
    except Exception as exc:  # driver errors are not importable without the driver
        return _error("cannot read %s: %s" % (args.server, exc))
    if args.dump:
        try:
            dump_collection(args.dump, collection)
        except OSError as exc:
            return _error("cannot write the dump: %s" % exc)
    if args.history:
        try:
            apply_history(record_history(args.history, collection), collection)
        except HistoryError as exc:
            return _error(exc)
    report = analyse_collection(collection, config)
    if args.scripts_dir:
        files = generate_scripts(report)
        os.makedirs(args.scripts_dir, exist_ok=True)
        for name, content in files.items():
            with open(os.path.join(args.scripts_dir, name), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
        print("index-advisor: wrote %d script(s) to %s" % (len(files), args.scripts_dir), file=sys.stderr)
    text = render(report, args.format, show_keep=args.show_keep, top=args.top)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        stdout.write(text)
    if report.errors:
        return EXIT_PARTIAL
    by_action = report.totals()["by_action"]
    if args.exit_code and by_action["drop"] + by_action["consolidate"]:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
