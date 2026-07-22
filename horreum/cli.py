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

    p_proj = sub.add_parser("project",
                            help="projekcja perspektywy w drzewo linków (DRY domyślnie; --apply)")
    p_proj.add_argument("db", help="ścieżka pliku bazy")
    p_proj.add_argument("--root", required=True,
                        help="korzeń projekcji — MUSI zawierać segment _WBPP/_Review (bez domyślnej "
                             "ścieżki: repo publiczne, prywatny R: poza kodem)")
    p_proj.add_argument("--layout", choices=["po-obiektach", "wbpp-feed"], default="po-obiektach",
                        help="układ katalogów (domyślnie po-obiektach)")
    p_proj.add_argument("--filter-json", default=None,
                        help="drzewo filtra JSON (jak grid): ścieżka pliku LUB inline; brak = cała baza")
    p_proj.add_argument("--copy", action="store_true",
                        help="kopiuj bajty (shutil.copy2) zamiast hardlinka — cross-wolumen / brak linków")
    p_proj.add_argument("--apply", action="store_true",
                        help="WYKONAJ: twórz linki/kopie + manifest (bez tego DRY — tylko raport)")
    p_proj.add_argument("--limit", type=int, default=20,
                        help="ile folderów kategorii / anomalii wypisać (domyślnie 20)")

    p_pres = sub.add_parser("presence",
                            help="pass obecnosci: wykryj znikniete kopie (DRY domyslnie; --apply)")
    p_pres.add_argument("db", help="ścieżka pliku bazy")
    p_pres.add_argument("--root", required=True,
                        help="korzeń drzewa do sprawdzenia (bez domyślnej ścieżki: repo publiczne)")
    p_pres.add_argument("--volume", required=True,
                        help="trwały serial woluminu — KONFRONTOWANY z zamontowanym dyskiem "
                             "(bez placeholdera '?': pass zdejmuje obecność, musi wiedzieć gdzie)")
    p_pres.add_argument("--apply", action="store_true",
                        help="WYKONAJ: oznacz potwierdzone zniknięcia (present=0) — bez tego DRY")
    p_pres.add_argument("--force", type=int, default=None, metavar="N",
                        help="deklaracja intencji: spodziewane N potwierdzonych zniknięć; "
                             "przełamuje hamulec, a rozjazd z dyskiem = abort bez zapisu")
    p_pres.add_argument("--limit", type=int, default=20,
                        help="ile ścieżek wypisać w raporcie (domyślnie 20)")

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
    if args.cmd == "project":
        # Qt-wolne: filter_engine/queries/projection (projection importuje gui.queries, Qt-free).
        from . import filter_engine, projection
        from .gui import queries
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        tree = _load_filter_tree(args.filter_json)             # ścieżka pliku LUB inline JSON (SPOT z gridem)
        frame_ids = filter_engine.run(
            tree,
            leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(con, k, kw, p1, p2),
            universe_fn=lambda: queries.all_frame_ids(con))
        proj = projection.plan(con, sorted(frame_ids), args.layout)
        manifest = {"perspektywa": args.filter_json or "cala-baza", "filter_tree": tree}

        def heartbeat(done, total, _dst, _status):            # puls co 100 (link na NAS wolniejszy, R1 #10)
            if done % 100 == 0 or done == total:
                print(f"  projekcja: {done}/{total}")
        try:
            res = projection.apply(proj, args.root, do_apply=args.apply, copy=args.copy, now=now,
                                   manifest=manifest, progress=heartbeat if args.apply else None)
        except projection.ProjectionAbort as exc:
            con.close()
            print(f"Horreum project: ABORT -- {exc}")         # sonda pierwszego linku padla (SMB kopia?)
            print(_format_project(args.root, exc.result, proj, limit=args.limit))
            return 1
        except ValueError as exc:                              # korzeń bez segmentu wykluczonego (§0)
            con.close()
            print(f"Horreum project: blad -- {exc}")
            return 1
        con.close()
        print(_format_project(args.root, res, proj, limit=args.limit))
        return 0
    if args.cmd == "presence":
        from . import presence                            # lazy: astropy dopiero tu (przez scan)
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        try:
            s = presence.check(con, args.root, volume=args.volume, apply=args.apply,
                               force=args.force, now=now)
        except (ValueError, FileNotFoundError) as exc:    # root UNC / nieistniejacy (EXPECT)
            con.close()
            print(f"Horreum presence: blad -- {exc}")
            return 1
        con.close()
        print(_format_presence(args.db, s, apply=args.apply, limit=args.limit))
        # Kod wyjscia mowi o WERDYKCIE, nie o zapisie: 1 = przebieg go NIE WYDAL (abort przeslanki
        # albo hamulec, ktory pominal potwierdzenia). Bez tego skrypt czytajacy `presence` w DRY
        # nie odrozni „nic nie zniklo" od „nie sprawdzilem" -- a to dwie rozne rzeczy.
        return 1 if (s.aborted is not None or not s.confirmed) else 0
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


def _format_presence(db_path, s, *, apply, limit):
    """Raport passa obecnosci — ASCII (konsola Windows = cp1250). Tryb w NAGLOWKU, nie w stopce:
    user ma widziec „DRY" zanim przeczyta liczby. Kubelki, ktore nie sa znikniecami (poza zasiegiem,
    wynurzone, nierozstrzygniete), wypisujemy TYLKO gdy niezerowe — cisza przy sukcesie (QUIET)."""
    tryb = "APPLY -- zapis do bazy" if apply else "DRY -- bez zmian w bazie"
    lines = [f"Horreum presence {db_path} ({tryb}):",
             f"  zakres: {s.scoped} lokacji pod {s.root} (wolumen {s.volume}); "
             f"na dysku: {s.walked} plikow"]
    if s.excluded_dirs:
        lines.append(f"  odciete prune: {len(s.excluded_dirs)} katalogow")
    if s.unreadable_dirs:
        lines.append(f"  NIEPRZECZYTANE katalogi: {len(s.unreadable_dirs)} "
                     f"(traktowane jak prune -- nie sa znikniecami)")
        for d in s.unreadable_dirs[:limit]:
            lines.append(f"    {d}")
    if s.out_of_reach:
        lines.append(f"  poza zasiegiem: {s.out_of_reach} kopii (istnieja, ale pod odcietym drzewem)")
    potwierdzone = (f"potwierdzone znikniecia: {s.confirmed_gone}" if s.confirmed
                    else "potwierdzen NIE liczono (hamulec) -- to nie znaczy 'nic nie zniklo'")
    lines.append(f"  kandydaci: {s.candidates}; {potwierdzone}")
    if s.undecided:
        lines.append(f"  NIEROZSTRZYGNIETE: {s.undecided} (stat bez odpowiedzi -- zero zapisu)")
    if s.resurfaced:
        lines.append(f"  WYNURZONE: {s.resurfaced} -- kandydat jednak istnieje. Najczesciej dryf "
                     f"wielkosci liter DB<->dysk; przyszly skan zminuje DRUGA lokacje na ten sam plik:")
        for p in s.resurfaced_paths[:limit]:
            lines.append(f"    {p}")
    for p in s.gone_paths[:limit]:
        lines.append(f"    znikl: {p}")
    if len(s.gone_paths) > limit:
        lines.append(f"    ... (+{len(s.gone_paths) - limit} wiecej; zwieksz --limit)")
    if s.cancelled:
        lines.append("  PRZERWANE -- zero zapisu (lista kandydatow niepelna)")
    if s.brake is not None and s.aborted is None:
        lines.append(f"  HAMULEC (tylko baner -- przebieg dokonczony): {s.brake}")
    if s.aborted is not None:
        lines.append(f"  ABORT -- nic nie zapisano: {s.aborted}")
    if apply and s.vanished:
        lines.append(f"  oznaczono present=0: {s.vanished} (run_id {s.run_id})")
    if s.drifted:
        lines.append(f"  pominieto przez dryf sciezki: {s.drifted} (rename miedzy planem a zapisem)")
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


def _load_filter_tree(arg):
    """--filter-json: ścieżka ISTNIEJĄCEGO pliku → wczytaj i sparsuj; inaczej potraktuj jako inline
    JSON; brak → None (cała baza). SPOT z gridem (to samo drzewo predykatów)."""
    if arg is None:
        return None
    p = Path(arg)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(arg)


def _format_project(root, res, proj, *, limit):
    """Raport projekcji (ASCII-safe — konsola cp1250: `->` nie `→`). DRY: stan celu + drzewo kategorii;
    --apply: liczności utworzenia + manifest. Anomalie (conflict/verify_bad/error) listowane do limitu."""
    from .projection import MANIFEST_NAME                    # stały literał nazwy manifestu (SPOT)
    c = res.counts
    mode = (("--apply --copy" if res.copy else "--apply") if res.do_apply
            else "DRY -- bez zmian na dysku")
    lines = [f"Horreum project {root} ({mode}; layout {res.layout}):"]
    if res.do_apply:
        lines.append(
            f"  zlinkowano: {c.get('linked',0)}; istnialo: {c.get('exists',0)}; "
            f"konflikty: {c.get('conflict',0)}; verify_bad: {c.get('verify_bad',0)}; "
            f"bledy: {c.get('error',0)}; pominieto: {c.get('skipped',0)}")
    else:
        lines.append(
            f"  do zlinkowania: {c.get('would-link',0)}; istnieje: {c.get('exists',0)}; "
            f"konflikty: {c.get('conflict',0)}; pominieto (brak kopii): {c.get('skipped',0)}")
    if proj.multi_present:
        lines.append(f"  wiele obecnych kopii: {proj.multi_present} (zlinkowano pierwsza; reszta w drzewie)")

    folders = {}
    for it in proj.items:
        key = "/".join(it.segments)
        folders[key] = folders.get(key, 0) + 1
    lines.append(f"  drzewo ({len(folders)} folderow kategorii; do {limit}):")
    for key, n in sorted(folders.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        lines.append(f"    {key}: {n}")
    if len(folders) > limit:
        lines.append(f"    ... (+{len(folders) - limit} folderow; zwieksz --limit)")

    anomalies = [r for r in res.results if r.status in ("conflict", "verify_bad", "error")]
    for r in anomalies[:limit]:
        name = Path(r.dst).name if r.dst else ""
        lines.append(f"    {r.status.upper()} {name}: {r.reason}")
    if res.do_apply:
        lines.append(f"  manifest: {Path(root) / MANIFEST_NAME}")
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
    # Liczba wiodaca = DISTINCT klatek; powody sie NAKLADAJA (brak kamery => tez brak configu),
    # wiec ich suma bywa wieksza niz klatek — swiadomie nie jest to rozbicie.
    rv = rep.review
    lines.append(f"  do przegladu: {rv.total} klatek (distinct; powody moga sie nakladac)")
    for label, n in (("bez konfiguracji", rv.no_config), ("bez naglowka", rv.headerless),
                     ("bez kamery", rv.no_camera), ("rodzaj nieznany", rv.kind_unknown),
                     ("kopia nieczytelna", rv.unreadable)):
        if n:
            lines.append(f"    {label}: {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
