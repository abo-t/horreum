"""CLI Horreum — minimalne wejście (plaster B: tylko `init`; skan dochodzi w kolejnym kroku)."""
import argparse

from . import __version__, db


def main(argv=None):
    parser = argparse.ArgumentParser(prog="horreum", description="Horreum — biblioteka astrofoto deep-sky")
    parser.add_argument("--version", action="version", version=f"horreum {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="utwórz/zmigruj bazę Horreum")
    p_init.add_argument("path", help="ścieżka pliku bazy (np. horreum.db)")

    args = parser.parse_args(argv)
    if args.cmd == "init":
        con = db.open_db(args.path)
        version = db._user_version(con)
        con.close()
        print(f"Horreum: baza {args.path} gotowa (schemat v{version}).")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
