"""CLI Horreum — wejście plastra B: `init` (utwórz/zmigruj bazę) + `scan` (wciągnij drzewo)."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, db


def main(argv=None):
    parser = argparse.ArgumentParser(prog="horreum", description="Horreum — biblioteka astrofoto deep-sky")
    parser.add_argument("--version", action="version", version=f"horreum {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="utwórz/zmigruj bazę Horreum")
    p_init.add_argument("path", help="ścieżka pliku bazy (np. horreum.db)")

    p_scan = sub.add_parser("scan", help="zeskanuj drzewo (FITS+XISF) do bazy")
    p_scan.add_argument("root", help="katalog do przeskanowania")
    p_scan.add_argument("db", help="ścieżka pliku bazy")
    p_scan.add_argument("--volume", default="?",
                        help="trwały identyfikator wolumenu (domyślnie placeholder '?')")
    p_scan.add_argument("--tier", default=None, help="cold|scratch")

    args = parser.parse_args(argv)
    if args.cmd == "init":
        con = db.open_db(args.path)
        version = db._user_version(con)
        con.close()
        print(f"Horreum: baza {args.path} gotowa (schemat v{version}).")
        return 0
    if args.cmd == "scan":
        from .scan import scan_tree                      # lazy: nie ładuj astropy dla init/--version
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        summary = scan_tree(con, args.root, volume=args.volume,
                            drive_letter=(Path(args.root).drive or None), tier=args.tier, now=now)
        con.close()
        print(f"Horreum scan {args.root} -> {args.db}: {summary}")   # ASCII: konsola Windows = cp1250
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
