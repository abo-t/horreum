"""CLI Horreum — wejście plastra B: `init` (utwórz/zmigruj bazę) + `scan` (wciągnij drzewo) +
`group` (teleskopy/config) + `resolve` (obiekt/filtr) + `delta` (read-only review) +
`import-fitsmirror` (zasilenie świeżej bazy z dawcy — PF-3, brief §4)."""
import argparse
import json
import sys
import uuid
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

    p_imp = sub.add_parser("import-fitsmirror",
                           help="zasil ŚWIEŻĄ bazę z bazy dawcy fitsmirror (dawca read-only)")
    p_imp.add_argument("donor", help="ścieżka bazy dawcy (fitsmirror.db)")
    p_imp.add_argument("db", help="ścieżka ŚWIEŻEJ bazy Horreum (utworzy ją migracja)")

    p_ren = sub.add_parser("rename", help="rename plików z faktów (DRY domyślnie; --apply/--undo)")
    p_ren.add_argument("db", help="ścieżka pliku bazy")
    p_ren.add_argument("--source", choices=["date-obs", "filename"], default="date-obs",
                       help="źródło czasu w nazwie (domyślnie date-obs)")
    p_ren.add_argument("--offset-hours", type=int, default=0,
                       help="całkowity offset godzin (BEZ założenia strefy; domyślnie 0)")
    p_ren.add_argument("--no-fallback", action="store_true",
                       help="wyłącz fallback na drugie źródło przy braku czasu")
    p_ren.add_argument("--filter-json", default=None,
                       help="drzewo filtra JSON (jak grid); brak = całe uniwersum")
    grp = p_ren.add_mutually_exclusive_group()
    grp.add_argument("--apply", action="store_true", help="WYKONAJ rename (destrukcyjne — ruch na dysku)")
    grp.add_argument("--undo", metavar="RUN_ID", help="cofnij rename przebiegu o podanym run_id")
    p_ren.add_argument("--limit", type=int, default=20, help="ile par stary->nowy wypisać (DRY; domyślnie 20)")

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
    if args.cmd == "import-fitsmirror":
        from .import_fitsmirror import ImportAbort, import_fitsmirror   # lazy (astropy)
        now = datetime.now(timezone.utc).isoformat()

        def heartbeat(done, total, _path):               # długi przebieg — puls co 1000 plików
            if done % 1000 == 0 or done == total:
                print(f"  import: {done}/{total}")
        try:
            summary = import_fitsmirror(args.donor, args.db, now=now, progress=heartbeat)
        except ImportAbort as exc:
            print(f"Horreum import-fitsmirror: ABORT — {exc}")
            if exc.summary is not None:
                print(_format_import(args.donor, args.db, exc.summary))
            return 1
        print(_format_import(args.donor, args.db, summary))
        return 0
    if args.cmd == "rename":
        # Qt-wolne: naming/filter_engine/queries (astropy-free); writeback/repo lazy tylko przy --apply/--undo.
        from . import filter_engine, naming
        from .gui import queries
        now = datetime.now(timezone.utc).isoformat()
        source = "date_obs" if args.source == "date-obs" else "filename"
        con = db.open_db(args.db)
        if args.undo:
            from . import writeback
            res = writeback.undo_renames(con, args.undo, now=now)
            con.close()
            print(_format_rename_undo(args.db, args.undo, res))
            return 0
        tree = json.loads(args.filter_json) if args.filter_json else None      # SPOT: drzewo filtra jak grid
        frame_ids = filter_engine.run(
            tree,
            leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(con, k, kw, p1, p2),
            universe_fn=lambda: queries.all_frame_ids(con))
        run_id = uuid.uuid4().hex if args.apply else None
        run = naming.run_rename(
            sorted(frame_ids), targets_fn=lambda ids: queries.rename_frame_targets(con, ids),
            source=source, offset_hours=args.offset_hours, fallback=not args.no_fallback, run_id=run_id)
        if not args.apply:
            con.close()
            print(_format_rename_dry(args.db, run, limit=args.limit))          # DRY: zero mutacji
            return 0
        from . import repo, writeback
        for p in run.touched:
            repo.stage_rename(con, run_id=run_id, location_id=p.location_id, old_path=p.old_path,
                              new_path=p.new_path, expected_mtime=p.mtime)

        def heartbeat(done, total, _path, _status):      # puls co 100 (rename na NAS wolniejszy niż import, R1 #10)
            if done % 100 == 0 or done == total:
                print(f"  rename: {done}/{total}")
        res = writeback.commit_renames(con, run_id, now=now, progress=heartbeat)
        con.close()
        print(_format_rename_apply(args.db, run, res, run_id))
        return 0
    parser.print_help()
    return 0


def _format_import(donor_path, db_path, s):
    """Sformatuj ImportSummary do czytelnego ASCII (konsola Windows = cp1250)."""
    pf = s.preflight
    lines = [f"Horreum import-fitsmirror {donor_path} -> {db_path}:"]
    if pf is not None:
        lines.append(f"  pre-flight: root {pf.root} volume {pf.volume}; "
                     f"dawca {pf.files_total} plikow; nadwyzka dysku {pf.surplus}; "
                     f"falsyfikator OK ({len(pf.verified)} plikow)")
        for note in pf.notes:
            lines.append(f"    {note}")
    lines.append(f"  import: {s.imported}/{s.files_total} (skipped {s.skipped}, "
                 f"przeliczone z dysku {s.recomputed}); {s.scan}")
    if s.skipped_paths:
        lines.append("  skipped (brief 4.3):")
        for p in s.skipped_paths:
            lines.append(f"    {p}")
    lines.append(f"  grouper: {s.group}")
    lines.append(f"  resolver: {s.resolve}")
    status = "OK" if not s.gate_failures else "FAIL"
    gates = " ".join(f"{k}={a}" for k, (_, a) in s.gates.items())
    lines.append(f"  bramki 4.6 {status}: {gates}")
    for fail in s.gate_failures:
        lines.append(f"    FAIL {fail}")
    return "\n".join(lines)


def _format_rename_dry(db_path, run, *, limit):
    """DRY-raport renamu: liczby + zagregowane powody skipów + lista `stary -> nowy` (basename, do limitu).
    ASCII-safe glify (`->`, bez `→`/`Δ`); polskie znaki w powodach przechodzą przez utf-8 reconfigure."""
    lines = [f"Horreum rename {db_path} (DRY -- bez zmian na dysku):",
             f"  do zmiany: {len(run.touched)}; pominieto: {len(run.skipped)}"]
    reasons = {}
    for s in run.skipped:
        reasons[s.reason] = reasons.get(s.reason, 0) + 1
    for reason, n in sorted(reasons.items()):
        lines.append(f"    pominieto {n}: {reason}")
    for p in run.touched[:limit]:
        lines.append(f"    {Path(p.old_path).name} -> {Path(p.new_path).name}")
    if len(run.touched) > limit:
        lines.append(f"    ... (+{len(run.touched) - limit} wiecej; zwieksz --limit)")
    return "\n".join(lines)


def _format_rename_apply(db_path, run, res, run_id):
    """Raport --apply: wynik commitu + osobno skipy podglądu; run_id i GOTOWA komenda undo (R2 #7)."""
    lines = [f"Horreum rename {db_path} --apply:",
             f"  przemianowano: {len(res.applied)}; zablokowane: {len(res.blocked)}; "
             f"bledy: {len(res.failed)}; pominiete(commit): {len(res.skipped)}; "
             f"pominiete(podglad): {len(run.skipped)}"]
    for fr in res.blocked:
        lines.append(f"    BLOCKED {Path(fr.path).name}: {fr.reason}")
    for fr in res.failed:
        lines.append(f"    FAILED {Path(fr.path).name}: {fr.reason}")
    lines.append(f"  run_id: {run_id}")
    lines.append(f"  cofnij: horreum rename {db_path} --undo {run_id}")
    return "\n".join(lines)


def _format_rename_undo(db_path, run_id, res):
    """Raport --undo: przywrócone/zablokowane/błędy."""
    lines = [f"Horreum rename {db_path} --undo {run_id}:",
             f"  przywrocono: {len(res.restored)}; zablokowane: {len(res.blocked)}; bledy: {len(res.failed)}"]
    for fr in res.blocked:
        lines.append(f"    BLOCKED {Path(fr.path).name}: {fr.reason}")
    return "\n".join(lines)


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
