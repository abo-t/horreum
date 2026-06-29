"""CLI Horreum — wejście plastra B: `init` (utwórz/zmigruj bazę) + `scan` (wciągnij drzewo) +
`group` (teleskopy/config) + `resolve` (obiekt/filtr) + `delta` (read-only review)."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, db


def main(argv=None):
    # Konsola Windows bywa cp1250; `delta` wypisuje surowe object_raw (dane usera — mogą mieć znaki
    # spoza cp1250). Przełącz stdout na UTF-8 (best-effort), by `print` nie wywalił się na nazwie
    # obiektu PO odczycie z bazy. Dla wyjścia ASCII (scan/group) bajty bez zmian.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

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

    p_group = sub.add_parser("group", help="grouper teleskopów + config (krok zbiorczy po skanie)")
    p_group.add_argument("db", help="ścieżka pliku bazy")

    p_resolve = sub.add_parser("resolve", help="resolver obiektu + filtra (krok zbiorczy po skanie)")
    p_resolve.add_argument("db", help="ścieżka pliku bazy")

    p_delta = sub.add_parser("delta", help="delta do review (read-only): %% obiektu + nierozstrzygnięte")
    p_delta.add_argument("db", help="ścieżka pliku bazy")

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
    if args.cmd == "group":
        from .grouper import run_grouper                 # lazy: nie ładuj resolve/astropy dla init
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        summary = run_grouper(con, now=now)
        con.close()
        print(f"Horreum group {args.db}: {summary}")     # ASCII (cp1250)
        return 0
    if args.cmd == "resolve":
        from .resolver import run_resolver               # lazy: nie ładuj resolve dla init
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        summary = run_resolver(con, now=now)
        con.close()
        print(f"Horreum resolve {args.db}: {summary}")   # ASCII (cp1250)
        return 0
    if args.cmd == "delta":
        from .resolver import delta_report               # read-only
        con = db.open_db(args.db)
        rep = delta_report(con)
        con.close()
        print(_format_delta(args.db, rep))               # ASCII (cp1250)
        return 0
    parser.print_help()
    return 0


def _format_delta(db_path, rep):
    """Sformatuj DeltaReport do czytelnego ASCII (konsola Windows = cp1250 — bez znaków spoza ASCII)."""
    lines = [f"Horreum delta {db_path}:"]
    lines.append(f"  obiekt (light/master_light): {rep.object_resolved}/"
                 f"{rep.object_resolved + rep.object_unresolved} rozwiazane ({rep.object_pct}%); "
                 f"delta {rep.object_unresolved} w {len(rep.object_delta)} distinct")
    for raw, n in rep.object_delta:
        lines.append(f"    {raw} -> {n}")
    lines.append(f"  filter_canon ustawione: {rep.filters_canon}")
    review = " ".join(f"{v}={n}" for v, n in rep.review_counts.items())
    lines.append(f"  review: {review}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
