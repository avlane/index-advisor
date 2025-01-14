"""Command line interface for index-advisor."""
import argparse
import os
import sys

from . import __version__
from .analysis import KEEP, REVIEW, Report, analyse_database
from .config import Config, ConfigError, load_config
from .connection import DEFAULT_DRIVER
from .missing import suggest
from .queries import (attach_physical, fetch_databases, fetch_foreign_keys, fetch_indexes,
                      fetch_missing_indexes, fetch_server_info)
from .report import render
from .scripts import generate_scripts

EXIT_OK, EXIT_ERROR, EXIT_PARTIAL = 0, 3, 4


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
        epilog="Exit codes: 0 done, 3 usage/config/connection error, 4 done but some databases could not be read.",
    )
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    p.add_argument("--server", required=True, help="instance to analyse, e.g. SQLPROD01 or SQLPROD01,1433")
    p.add_argument("--config", help="TOML file with thresholds")
    p.add_argument("-d", "--database", action="append", default=[], metavar="NAME",
                   help="only analyse this database (repeatable)")
    p.add_argument("--format", choices=("text", "json", "markdown"), default="text", help="report format (default: text)")
    p.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    p.add_argument("--show-keep", action="store_true", help="also list the indexes that should be kept")
    p.add_argument("--physical", action="store_true",
                   help="also read index fragmentation (sys.dm_db_index_physical_stats, LIMITED mode); "
                        "slow on large databases")
    p.add_argument("--min-pages", type=int, default=1000, metavar="N",
                   help="with --physical, ignore indexes smaller than N pages (default: %(default)s)")
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


def main(argv=None, connect=None, stdout=None):
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config) if args.config else Config()
    except ConfigError as exc:
        return _error(exc)
    try:
        conn = (connect or default_connect)(args)
    except Exception as exc:  # driver errors are not importable without the driver
        return _error("cannot connect to %s: %s" % (args.server, exc))
    try:
        try:
            server = fetch_server_info(conn)
            names = _select(fetch_databases(conn), args.database, config)
        except LookupError as exc:
            return _error(exc)
        except Exception as exc:
            return _error("query failed: %s" % exc)
        analyses, errors = [], []
        try:
            missing = fetch_missing_indexes(conn)
        except Exception as exc:
            missing = []
            errors.append(("(missing-index DMVs)", str(exc)))
        for name in names:
            try:
                indexes = fetch_indexes(conn, name)
                foreign_keys = fetch_foreign_keys(conn, name)
                if args.physical:
                    attach_physical(conn, name, indexes, args.min_pages)
            except Exception as exc:
                errors.append((name, str(exc)))
                continue
            analysis = analyse_database(name, indexes, server, config, foreign_keys)
            survivors = [r.index for r in analysis.recommendations if r.action in (KEEP, REVIEW)]
            analysis.suggestions = suggest(missing, config.thresholds, name, survivors)
            analyses.append(analysis)
    finally:
        conn.close()
    report = Report(server, analyses, errors)
    if args.scripts_dir:
        files = generate_scripts(report)
        os.makedirs(args.scripts_dir, exist_ok=True)
        for name, content in files.items():
            with open(os.path.join(args.scripts_dir, name), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
        print("index-advisor: wrote %d script(s) to %s" % (len(files), args.scripts_dir), file=sys.stderr)
    text = render(report, args.format, show_keep=args.show_keep)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        stdout.write(text)
    return EXIT_PARTIAL if errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
