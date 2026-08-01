"""CLI Horreum — wejście plastra B: `init` (utwórz/zmigruj bazę) + `scan` (wciągnij drzewo) +
`group` (teleskopy/config) + `resolve` (obiekt/filtr) + `calibrate` (oś przepisu) +
`delta` (read-only review) + `import-fitsmirror` (zasilenie świeżej bazy z dawcy — PF-3, brief §4)."""
import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from . import db


class _VersionAction(argparse.Action):
    """`--version` sięga po numer DOPIERO przy użyciu flagi. `importlib.metadata` (jedyny
    właściciel numeru — patrz `horreum/__init__.py`) kosztuje ~45 ms, czyli więcej niż cały
    import CLI; ta sama dyscyplina leniwości co `_layout` niżej."""

    def __init__(self, option_strings, dest, help=None):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        from . import __version__
        print(f"horreum {__version__}")
        parser.exit()


def _layout(name):
    """Nazwa układu projekcji — walidacja LENIWA, bo jedynym właścicielem listy jest
    `projection.LAYOUTS` (layout = DANE, D-P1), a import `projection` przy BUDOWIE parsera
    kosztowałby ~0,26 s na KAŻDE wywołanie CLI (ciągnie `scan`). `type=` argparse woła dopiero
    przy parsowaniu, więc `horreum --version` nadal nic nie płaci. Komunikat ASCII — leci na
    stderr, którego `main` nie przełącza na UTF-8 (konsola bywa cp1250)."""
    from .projection import LAYOUTS
    if name not in LAYOUTS:
        raise argparse.ArgumentTypeError(
            f"nieznany uklad {name!r}; dostepne: {', '.join(sorted(LAYOUTS))}")
    return name


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
    parser.add_argument("--version", action=_VersionAction, help="wypisz wersję i zakończ")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="utwórz/zmigruj bazę Horreum")
    p_init.add_argument("path", help="ścieżka pliku bazy (np. horreum.db)")

    p_scan = sub.add_parser("scan", help="zeskanuj drzewo (FITS+XISF+RAW) do bazy")
    p_scan.add_argument("root", help="katalog do przeskanowania")
    p_scan.add_argument("db", help="ścieżka pliku bazy")
    p_scan.add_argument("--volume", default="?",
                        help="trwały identyfikator wolumenu (domyślnie placeholder '?')")
    p_scan.add_argument("--tier", default=None, help="cold|scratch")

    # Droga „Stosy" (I-2b, P-I / D-P-I-1 wariant A) — OSOBNA od `scan` z decyzji, nie z wygody:
    # drzewo obróbki nie jest archiwum, więc wskazuje się je świadomym gestem, a standing-op
    # doskanu zostaje nietknięty.
    p_stk = sub.add_parser("stacks",
                           help="wciągnij GOTOWE OBRAZY po integracji (`masterLight*.xisf`) ze "
                                "wskazanego drzewa obróbki — read-only, poza skanem archiwum")
    p_stk.add_argument("root", help="korzeń drzewa obróbki")
    p_stk.add_argument("db", help="ścieżka pliku bazy")
    p_stk.add_argument("--volume", default="?",
                       help="trwały identyfikator wolumenu (bez niego brama przyrostowa OFF)")
    p_stk.add_argument("--tier", default=None, help="cold|scratch")
    p_stk.add_argument("--limit", type=int, default=10,
                       help="ile odrzuconych/nieudanych ścieżek wypisać (domyślnie 10)")

    p_group = sub.add_parser("group", help="grouper teleskopów + config (krok zbiorczy po skanie)")
    p_group.add_argument("db", help="ścieżka pliku bazy")

    p_resolve = sub.add_parser("resolve", help="resolver obiektu + filtra (krok zbiorczy po skanie)")
    p_resolve.add_argument("db", help="ścieżka pliku bazy")

    p_cal = sub.add_parser("calibrate",
                           help="oś przepisu klatek kalibracyjnych (krok zbiorczy PO `resolve` — "
                                "przepis flata zna filtr dopiero po resolverze)")
    p_cal.add_argument("db", help="ścieżka pliku bazy")

    p_lin = sub.add_parser("lineage",
                           help="rodowód light<->master po przepisie (krok zbiorczy PO `calibrate` — "
                                "wymaga zapełnionej osi przepisu)")
    p_lin.add_argument("db", help="ścieżka pliku bazy")

    p_delta = sub.add_parser("delta", help="delta do review (read-only): %% obiektu + nierozstrzygnięte")
    p_delta.add_argument("db", help="ścieżka pliku bazy")

    p_plan = sub.add_parser("plan",
                            help="planer celów (read-only): co dziś na niebie, w jakim kadrze, "
                                 "czego brakuje i ile kosztuje Księżyc")
    p_plan.add_argument("db", help="ścieżka pliku bazy")
    p_plan.add_argument("--night", help="data WIECZORU (YYYY-MM-DD); domyślnie noc, która ma sens teraz")
    p_plan.add_argument("--park", help="lista teleskopów po przecinku; BIJE park z bazy "
                                       "(bez flagi: `telescope.in_park`, a gdy pusty — wszystkie)")
    p_plan.add_argument("--layers", default="core",
                        help="warstwy katalogu: core|cirrus|core,cirrus (curated ZAWSZE)")
    p_plan.add_argument("--min-size", type=float, default=6.0, help="próg rozmiaru [']")
    p_plan.add_argument("--min-dark", type=float, default=15.0, help="próg rozmiaru ciemnej [']")
    p_plan.add_argument("--max-mag", type=float, default=13.0, help="próg magnitudo GALAKTYK")
    p_plan.add_argument("--min-alt", type=float, default=30.0, help="próg wysokości [deg]")
    p_plan.add_argument("--min-hours", type=float, default=1.0, help="ile godzin kanału to pokrycie")
    p_plan.add_argument("--max-cost", type=float, default=None,
                        help="odetnij cele droższe niż N× (domyślnie BEZ progu — D-0731-14)")
    p_plan.add_argument("--overlap", type=float, default=0.10, help="zakładka mozaiki (0..1)")
    p_plan.add_argument("--gaps", action="store_true", help="tylko cele z luką")
    p_plan.add_argument("--new", action="store_true", help="tylko cele nigdy nie fotografowane")
    p_plan.add_argument("--status", choices=("planned", "active", "done", "skip"),
                        help="tylko cele o tym statusie kuratelii (bez flagi: 'skip' ukryty)")
    p_plan.add_argument("--find", help="szukaj po kanonie ORAZ nazwach potocznych (pomija progi)")
    p_plan.add_argument("--limit", type=int, default=30, help="ile wierszy (domyślnie 30)")
    p_plan.add_argument("--all", action="store_true", help="bez limitu wierszy")
    p_plan.add_argument("--json", action="store_true", help="wyjście maszynowe")

    # Park i kuratela = jedyne komendy planera, które PISZĄ (T4). Stąd `open_db`, nie `connect`.
    p_park = sub.add_parser("park",
                            help="park aktualny: czym Zdzin BĘDZIE fotografował (nie da się "
                                 "wyprowadzić z archiwum — ono opisuje przeszłość)")
    p_park.add_argument("db", help="ścieżka pliku bazy")
    p_park.add_argument("--add", action="append", default=[], metavar="TELESKOP",
                        help="wstaw teleskop do parku (powtarzalne)")
    p_park.add_argument("--drop", action="append", default=[], metavar="TELESKOP",
                        help="oznacz teleskop jako historyczny (powtarzalne)")
    p_park.add_argument("--clear", action="append", default=[], metavar="TELESKOP",
                        help="wycofaj zdanie o teleskopie — stan wraca do nie-wypowiedzianego "
                             "(NULL, inny fakt niz historyczny; powtarzalne)")

    p_tgt = sub.add_parser("target",
                           help="kuratela celów: status/priorytet/notatka na celu z katalogu")
    p_tgt.add_argument("db", help="ścieżka pliku bazy")
    p_tgt.add_argument("canon", nargs="?",
                       help="kanon albo alias celu (bez argumentu = lista oznaczonych)")
    p_tgt.add_argument("--status", choices=("planned", "active", "done", "skip"),
                       help="stan celu; przy liście = filtr")
    p_tgt.add_argument("--priority", type=int, default=None, help="mniejsza = pilniejsza")
    p_tgt.add_argument("--note", default=None, help="notatka własna")
    p_tgt.add_argument("--clear", action="store_true", help="zdejmij oznaczenie celu")

    p_bx = sub.add_parser("backfill-xisf",
                          help="doczytaj cards+header_hash do lokacji XISF sprzed P6a (jednorazowo)")
    p_bx.add_argument("db", help="ścieżka pliku bazy")
    p_bx.add_argument("--limit", type=int, default=20,
                      help="ile nieudanych odczytów wypisać (domyślnie 20)")

    p_imp = sub.add_parser("import-fitsmirror",
                           help="zasil ŚWIEŻĄ bazę z bazy dawcy fitsmirror (dawca read-only)")
    p_imp.add_argument("donor", help="ścieżka bazy dawcy (fitsmirror.db)")
    p_imp.add_argument("db", help="ścieżka ŚWIEŻEJ bazy Horreum (utworzy ją migracja)")
    p_imp.add_argument("--live-db", default=None,
                       help="żywa baza Horreum — rejestr napraw writebacku (ścieżki naprawione "
                            "przez tę instalację nie wywołają abortu falsyfikatora; D-0722-2)")

    p_ren = sub.add_parser("rename", help="rename plików z faktów (DRY domyślnie; --apply/--undo)")
    p_ren.add_argument("db", help="ścieżka pliku bazy")
    p_ren.add_argument("--source", choices=["date-obs", "filename"], default="date-obs",
                       help="źródło czasu w nazwie (domyślnie date-obs)")
    p_ren.add_argument("--offset-hours", type=int, default=0,
                       help="całkowity offset godzin (BEZ założenia strefy; domyślnie 0)")
    p_ren.add_argument("--no-fallback", action="store_true",
                       help="wyłącz fallback na drugie źródło przy braku czasu")
    p_ren.add_argument("--filter-json", default=None,
                       help="drzewo filtra JSON (jak grid): ścieżka pliku LUB inline; brak = całe uniwersum")
    p_ren.add_argument("--template-json", default=None,
                       help="wzór nazwy JSON (ścieżka pliku LUB inline): lista specyfikacji tokenów ALBO "
                            "dict per typ pliku; brak = wzór domyślny")
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
    p_proj.add_argument("--layout", type=_layout, default="po-obiektach",
                        help="układ katalogów (domyślnie po-obiektach; zła nazwa wypisze dostępne)")
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
    if args.cmd == "stacks":
        from .scan import scan_stacks                    # lazy: nie ładuj astropy dla init/--version
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        s = scan_stacks(con, args.root, volume=args.volume,
                        drive_letter=(Path(args.root).drive or None), tier=args.tier, now=now)
        con.close()
        print(_format_stacks(args.root, args.db, s, limit=args.limit))   # ASCII (cp1250)
        # Odmowa NIE jest błędem drogi (plik po prostu nie jest stackiem), ale kod wyjścia ma ją
        # nieść: skrypt, który woła tę komendę, nie ma czytać prozy, żeby dowiedzieć się o brakach.
        return 1 if (s.rejected_kind or s.rejected_unreadable or s.failed) else 0
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
    if args.cmd == "calibrate":
        from .calibration import run_calibration         # lazy: nie ładuj resolve dla init
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        summary = run_calibration(con, now=now)
        con.close()
        print(f"Horreum calibrate {args.db}: {summary}")  # ASCII (cp1250)
        return 0
    if args.cmd == "lineage":
        from .lineage import run_lineage                  # lazy: nie ładuj resolve dla init
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)
        summary = run_lineage(con, now=now)
        con.close()
        print(f"Horreum lineage {args.db}: {summary}")    # ASCII (cp1250)
        return 0
    if args.cmd == "delta":
        from .resolver import delta_report               # read-only
        con = db.open_db(args.db)
        rep = delta_report(con)
        con.close()
        print(_format_delta(args.db, rep))               # ASCII (cp1250)
        return 0
    if args.cmd == "plan":
        from . import targets                             # lazy: Qt-wolne, astropy niepotrzebne
        # READ-ONLY: `connect`, NIE `open_db` — komenda czytająca nie ma prawa podnieść schematu
        # żywego archiwum (T3 §0). Niezgodna wersja = jawny błąd, nie milcząca migracja.
        con = db.connect(args.db)
        version = db._user_version(con)
        if version != db.SCHEMA_VERSION:
            con.close()
            print(f"Horreum plan: baza {args.db} ma schemat v{version}, kod oczekuje "
                  f"v{db.SCHEMA_VERSION} — uruchom `horreum init {args.db}` (plan nie migruje).")
            return 2
        try:
            result = targets.plan(
                con,
                night=date.fromisoformat(args.night) if args.night else None,
                park=[p.strip() for p in args.park.split(",")] if args.park else None,
                layers=tuple(x.strip() for x in args.layers.split(",") if x.strip()),
                min_size=args.min_size, min_dark=args.min_dark, max_mag=args.max_mag,
                min_alt=args.min_alt, min_hours=args.min_hours, max_cost=args.max_cost,
                overlap=args.overlap, only_gaps=args.gaps, only_new=args.new,
                status=args.status, find=args.find,
                limit=None if args.all else args.limit)
        except ValueError as e:                           # brak stanowiska z GPS / zła warstwa
            con.close()
            print(f"Horreum plan: {e}")
            return 2
        con.close()
        print(json.dumps(_plan_json(result), ensure_ascii=False, indent=1) if args.json
              else _format_plan(args.db, result))
        return 0
    if args.cmd == "park":
        return _cmd_park(args)
    if args.cmd == "target":
        return _cmd_target(args)
    if args.cmd == "backfill-xisf":
        from .scan import backfill_xisf_headers          # lazy (astropy przez scan)
        now = datetime.now(timezone.utc).isoformat()
        con = db.open_db(args.db)

        def heartbeat(done, total, _path):               # puls co 50 (odczyt nagłówków z NAS)
            if done % 50 == 0 or done == total:
                print(f"  backfill: {done}/{total}")
        s = backfill_xisf_headers(con, now=now, progress=heartbeat)
        con.close()
        print(_format_backfill_xisf(args.db, s, limit=args.limit))
        # Kod wyjscia mowi o KOMPLETNOSCI: 1 = zostali kandydaci (pliki nie do przeczytania),
        # wiec „przebieg sie udal" nie znaczy „nic nie zostalo".
        return 1 if s.remaining else 0
    if args.cmd == "import-fitsmirror":
        from .import_fitsmirror import ImportAbort, import_fitsmirror   # lazy (astropy)
        now = datetime.now(timezone.utc).isoformat()

        def heartbeat(done, total, _path):               # długi przebieg — puls co 1000 plików
            if done % 1000 == 0 or done == total:
                print(f"  import: {done}/{total}")
        try:
            summary = import_fitsmirror(args.donor, args.db, now=now,
                                        repaired_db=args.live_db, progress=heartbeat)
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
        tree = _load_filter_tree(args.filter_json)             # ścieżka pliku LUB inline (SPOT z gridem)
        template = _load_filter_tree(args.template_json) or naming.DEFAULT_TEMPLATE   # file-or-inline; brak→domyślny
        frame_ids = filter_engine.run(
            tree,
            leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(con, k, kw, p1, p2),
            universe_fn=lambda: queries.all_frame_ids(con))
        run_id = uuid.uuid4().hex if args.apply else None
        try:
            run = naming.run_rename(
                sorted(frame_ids), targets_fn=lambda ids: queries.rename_frame_targets(con, ids),
                source=source, offset_hours=args.offset_hours, template=template,
                fallback=not args.no_fallback, run_id=run_id)
        except ValueError as e:                                # zły regex orig w szablonie (INFORMUJ)
            con.close()
            print(f"Horreum rename: błąd wzoru nazwy: {e}")
            return 2
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
    if s.calibration is not None:
        c = s.calibration
        lines.append(f"  kalibracja: klatki {c.frames}; przepisy {c.profiles_proposed}; "
                     f"przypisania {c.profiles_assigned}; fakty ze sciezki {c.facts_recorded}; "
                     f"bez kompletu {c.incomplete}")
    if s.lineage is not None:
        li = s.lineage
        linked = " ".join(f"{rel}={li.linked.get(rel, 0)}" for rel in sorted(li.linked)) or "-"
        lines.append(f"  rodowod: lighty {li.lights}; z kalibratorem {linked}")
    status = "OK" if not s.gate_failures else "FAIL"
    gates = " ".join(f"{k}={a}" for k, (_, a) in s.gates.items())
    lines.append(f"  bramki 4.6 {status}: {gates}")
    for fail in s.gate_failures:
        lines.append(f"    FAIL {fail}")
    return "\n".join(lines)


def _format_backfill_xisf(db_path, s, *, limit):
    """Raport backfillu XISF (ASCII — konsola cp1250). Liczba wiodaca = KANDYDACI PO przebiegu:
    0 znaczy „komplet", a nie „nic nie zostalo do zrobienia" — to dwie rozne rzeczy."""
    sc = s.scan
    lines = [f"Horreum backfill-xisf {db_path}:",
             f"  kandydaci: {s.rows}; odczytane: {s.read}; nieudane odczyty: {s.failed}",
             f"  odswiezone kopie: {sc.locations_refreshed}; odswiezone zeznania: {sc.headers_refreshed}",
             f"  ZOSTALO kandydatow: {s.remaining}"]
    for p in s.failed_paths[:limit]:
        lines.append(f"    NIEUDANY {p}")
    if len(s.failed_paths) > limit:
        lines.append(f"    ... (+{len(s.failed_paths) - limit} wiecej; zwieksz --limit)")
    if s.remaining:
        lines.append("  UWAGA: kandydaci zostali -- pliki, ktorych naglowka nie da sie sparsowac "
                     "(P6 ich NIE naprawia) albo kopie nie do odczytania")
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
    if res.drift:
        # Rozjazd manifestu PRZED liczbami: stare drzewo nie daje `conflict` (lezy pod INNA sciezka),
        # wiec liczniki wygladaja czysto, a korzen dostaje DRUGIE drzewo obok starego.
        lines.append(f"  UWAGA: w korzeniu stoi juz drzewo o innym ukladzie ({res.drift}) -- "
                     "ponowne wydanie dolozy drugie obok niego")
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


def _hhmm(dt):
    return "--:--" if dt is None else dt.strftime("%H:%M")


def _coverage_text(row):
    """Pokrycie jednym zdaniem: co jest (godziny per kanał) i czego brakuje. Nazwa, POD KTÓRĄ
    użytkownik ma klatki, jedzie wprost, gdy różni się od kanonu wiersza (D-T2-d)."""
    from . import targets as T
    cov = row.coverage
    if not cov.known:
        return "nigdy"
    parts = []
    alien = [c for c in cov.archive_canons if c != row.target.canon]
    if alien:
        parts.append("u Ciebie: " + "/".join(alien))
    for ch in (T.RGB,) + T.NARROW_CHANNELS:
        hours = cov.hours_by_channel.get(ch, 0.0)
        if hours > 0:
            parts.append(f"{ch} {hours:.1f}h")
    if cov.gaps:
        parts.append("brak " + "/".join(cov.gaps))
    return ", ".join(parts)


def _cmd_park(args):
    """`horreum park` — przegląd i oznaczanie parku aktualnego (D-T3-d).

    Bez `--add`/`--drop`/`--clear` to czysty przegląd: kanon, lighty, ostatnia klatka, stan parku.
    Teleskop nieznany bazie kończy się kodem 2 i LISTĄ kanonicznych — park nie powołuje osi (oś
    wyłania się ze skanu), więc literówka nie ma prawa utworzyć wiersza.

    TRZY OZNACZENIA, BO `in_park` MA TRZY STANY: `--add` → 1, `--drop` → 0 (jawnie historyczny),
    `--clear` → NULL (wycofuję zdanie). „Historyczny" i „nie wypowiedziałem się" to różne fakty —
    pierwszy znaczy park przejrzany, drugi bazę świeżą — i różnią raport (`-` vs `historyczny`)."""
    from . import repo
    from .gui import queries          # leniwie: `gui.queries` ciągnie `resolver` (koszt startu CLI)
    now = datetime.now(timezone.utc).isoformat()
    con = db.open_db(args.db)
    known = {r["telescop_canon"]: r["id"] for r in con.execute(
        "SELECT id, telescop_canon FROM telescope WHERE merged_into IS NULL").fetchall()}
    changed = 0
    for name, value in ([(n, 1) for n in args.add] + [(n, 0) for n in args.drop]
                        + [(n, None) for n in args.clear]):
        match = next((k for k in known if k.casefold() == name.strip().casefold()), None)
        if match is None:
            con.close()
            print(f"Horreum park: teleskop {name!r} nieznany bazie. Kanoniczne: "
                  f"{', '.join(sorted(known))}")
            return 2
        if repo.set_telescope_park(con, telescope_id=known[match], in_park=value, now=now):
            changed += 1
    # Literał przeniesiony do `gui.queries.park_overview` (T5b) — ten sam przegląd karmi dialog
    # „Park…" ekranu planera; dwie powierzchnie jednej decyzji liczą lighty JEDNYM zapytaniem.
    rows = queries.park_overview(con)
    con.close()
    lines = [f"Horreum park {args.db}:" + (f" zmieniono {changed}" if changed else "")]
    lines.append(f"  {'teleskop':<12}{'lighty':>8}  {'ostatnia klatka':<20}park")
    for r in rows:
        state = {1: "TAK", 0: "historyczny"}.get(r["in_park"], "-")
        # KANON, nie nazwa usera — to on jest tokenem `--add/--drop/--clear`; raport CLI ma
        # wypisywać dokładnie to, co da się wpisać z powrotem. (Dialog „Park…" pokazuje nazwę
        # usera, bo tam się nic nie wpisuje — klika się wiersz.)
        lines.append(f"  {r['telescop_canon']:<12}{r['lights']:>8}  "
                     f"{(r['last_seen'] or '-')[:19]:<20}{state}")
    if not any(r["in_park"] == 1 for r in rows):
        lines.append("  park NIEUSTAWIONY — planer liczy WSZYSTKIE teleskopy, takze historyczne "
                     "(`horreum park <db> --add <teleskop>`)")
    print("\n".join(lines))
    return 0


def _cmd_target(args):
    """`horreum target` — kuratela celów katalogu (status/priorytet/notatka).

    Bez kanonu = lista oznaczonych. Kanon walidowany wobec ASSETU (`targets.resolve_plan_canon`):
    literówka albo nazwa dwuznaczna kończy się kodem 2 i listą kandydatów, nigdy cichym zapisem
    na losowym rekordzie. Cel oznaczony, którego katalog już nie zna (podmiana assetu), zostaje
    na liście z etykietą — kasowanie cudzej decyzji to nie sprzątanie."""
    from . import repo, targets
    now = datetime.now(timezone.utc).isoformat()
    con = db.open_db(args.db)
    if args.canon:
        canon, candidates = targets.resolve_plan_canon(args.canon)
        if canon is None:
            con.close()
            hint = (f" Kandydaci: {', '.join(candidates)}" if candidates
                    else " Brak podobnych w katalogu.")
            print(f"Horreum target: {args.canon!r} nie wskazuje jednego celu katalogu.{hint}")
            return 2
        if args.clear:
            done = repo.clear_target_plan(con, canon=canon, now=now)
            con.close()
            print(f"Horreum target {canon}: " + ("oznaczenie zdjete" if done else "nie bylo oznaczenia"))
            return 0
        if args.status is None:
            con.close()
            print(f"Horreum target {canon}: podaj --status (planned|active|done|skip) albo --clear")
            return 2
        repo.set_target_plan(con, canon=canon, status=args.status, priority=args.priority,
                             note=args.note, now=now)
        con.close()
        print(f"Horreum target {canon}: {args.status}"
              + (f", priorytet {args.priority}" if args.priority is not None else "")
              + (f", nota {args.note!r}" if args.note else ""))
        return 0
    rows = con.execute(
        "SELECT canon, status, priority, note FROM target_plan ORDER BY canon").fetchall()
    con.close()
    known = {t.canon for t in targets.load_targets(targets.ALL_LAYERS)}
    rows = [r for r in rows if args.status is None or r["status"] == args.status]
    if not rows:
        print(f"Horreum target {args.db}: brak oznaczonych celow.")
        return 0
    lines = [f"Horreum target {args.db}: {len(rows)} oznaczonych",
             f"  {'cel':<16}{'status':<9}{'prio':>5}  nota"]
    for r in rows:
        orphan = "" if r["canon"] in known else "  [poza katalogiem]"
        prio = "-" if r["priority"] is None else str(r["priority"])
        lines.append(f"  {r['canon']:<16}{r['status']:<9}{prio:>5}  {r['note'] or ''}{orphan}")
    print("\n".join(lines))
    return 0


def _format_plan(db_path, res):
    """Plan nocy do czytelnego ASCII (konsola Windows = cp1250 — bez znaków spoza ASCII)."""
    site = res.site
    lines = [f"Horreum plan {db_path}: noc {res.night_date}, {site.name or 'stanowisko'} "
             f"({site.lat_deg:.2f}N {site.lon_deg:.2f}E)"]
    nw = res.night
    astro = (f" (astronomiczna {_hhmm(nw.astro_start)}-{_hhmm(nw.astro_end)})"
             if nw.astro_idx else " (bez nocy astronomicznej)")
    lines.append(f"  ciemnosc zeglarska {_hhmm(nw.dark_start)}-{_hhmm(nw.dark_end)} UTC{astro}, "
                 f"Ksiezyc {res.moon.illumination * 100:.0f}% alt {res.moon.alt_deg:.0f}")
    c = res.counts
    lines.append(f"  cele: {c['pool']} -> {c['feasible']} po progach -> {c['above_horizon']} "
                 f"nad horyzontem -> {c['visible']} widocznych")
    for rig in res.rigs:
        lines.append(f"  zestaw {rig.telescope}: kadr {rig.fov_x_arcmin:.0f}'x{rig.fov_y_arcmin:.0f}'"
                     f", kamery {'/'.join(rig.cameras)}{'' if rig.mono else ' (tylko OSC)'}")
    for rig in res.skipped_rigs:
        lines.append(f"  zestaw {rig.telescope} POZA planem: {rig.reason}")
    if res.park_source == "none":
        lines.append("  park NIEUSTAWIONY: liczone WSZYSTKIE teleskopy bazy, takze historyczne "
                     "(`horreum park <db> --add <teleskop>`)")
    else:
        lines.append(f"  park ({'z bazy' if res.park_source == 'db' else 'z flagi'}): "
                     f"{', '.join(res.park)}")
    if res.park_without_rigs:
        lines.append(f"  UWAGA: w parku bez zestawu (brak lightow): "
                     f"{', '.join(res.park_without_rigs)}")
    if res.counts.get("hidden_by_status"):
        lines.append(f"  ukrytych jako 'skip': {res.counts['hidden_by_status']} "
                     f"(`--status skip` pokazuje ktore)")
    if res.unfiltered_mono:
        lines.append(f"  UWAGA: {res.unfiltered_mono} lightow bez filtra na kamerze mono — "
                     f"kubelek RGB moze byc zanieczyszczony")
    lines.append("")
    lines.append(f"  {'cel':<14}{'typ':<6}{'rozm':>6}{'kulm':>6}{'h>':>5}  {'zestaw':<17}"
                 f"{'koszt B/D/N':<14}{'rada':<6}{'plan':<10}pokrycie")
    for row in res.rows:
        rig = row.best_rig
        fr = row.framing.get(rig.telescope) if rig is not None else None
        rig_txt = "-" if fr is None else (
            f"{rig.telescope} " + ("1 kadr" if fr.panels == 1 else f"mozaika {fr.panels}"))
        cost = row.cost
        cost_txt = (f"{cost['broadband']:.1f}/{cost['duoband']:.1f}/{cost['narrowband']:.1f}")
        plan_txt = "-" if row.plan_status is None else (
            row.plan_status + ("" if row.priority is None else f" {row.priority}"))
        lines.append(
            f"  {row.target.canon:<14}{row.target.type:<6}"
            f"{row.target.major_arcmin:>5.0f}'{row.window.max_alt_deg:>6.1f}"
            f"{row.window.hours_above:>5.1f}  {rig_txt:<17}{cost_txt:<14}"
            f"{row.recommend or '-':<6}{plan_txt:<10}{_coverage_text(row)}")
    if res.hidden:
        lines.append(f"  ... {res.hidden} wierszy ukrytych limitem (--all zdejmuje)")
    if res.unmatched:
        top = sorted(res.unmatched.items(), key=lambda kv: -kv[1])
        shown = ", ".join(f"{k} {v:.1f}h" for k, v in top[:5])
        lines.append(f"  godziny bez celu w katalogu: {shown}"
                     + (f" (+{len(top) - 5})" if len(top) > 5 else ""))
    return "\n".join(lines)


def _plan_json(res):
    """Ten sam materiał maszynowo — wejście dla T5 i dla firsthandu."""
    return {
        "night": res.night_date.isoformat(),
        "site": {"name": res.site.name, "lat": res.site.lat_deg, "lon": res.site.lon_deg},
        "dark": {"start": res.night.dark_start.isoformat() if res.night.dark_start else None,
                 "end": res.night.dark_end.isoformat() if res.night.dark_end else None,
                 "darkness": res.night.darkness},
        "moon": {"illumination": res.moon.illumination, "alt_deg": res.moon.alt_deg},
        "counts": res.counts,
        "hidden": res.hidden,
        "park": {"telescopes": list(res.park), "source": res.park_source,
                 "without_rigs": list(res.park_without_rigs)},
        "rigs": [{"telescope": r.telescope, "fov_x": r.fov_x_arcmin, "fov_y": r.fov_y_arcmin,
                  "cameras": list(r.cameras), "mono": r.mono, "lights": r.lights}
                 for r in res.rigs],
        "skipped_rigs": [{"telescope": r.telescope, "reason": r.reason} for r in res.skipped_rigs],
        "unmatched": {k: round(v, 3) for k, v in sorted(res.unmatched.items())},
        "rows": [{
            "canon": row.target.canon, "type": row.target.type,
            "major_arcmin": row.target.major_arcmin, "minor_arcmin": row.target.minor_arcmin,
            "ra_deg": row.target.ra_deg, "dec_deg": row.target.dec_deg, "layer": row.target.layer,
            "max_alt_deg": round(row.window.max_alt_deg, 2),
            "hours_above": row.window.hours_above, "visible": row.window.visible,
            "framing": {k: {"panels": v.panels, "fill": round(v.fill, 3)}
                        for k, v in row.framing.items()},
            "best_rig": row.best_rig.telescope if row.best_rig else None,
            "cost": {k: round(v, 3) for k, v in row.cost.items()},
            "recommend": row.recommend, "recommend_reason": row.recommend_reason,
            "plan_status": row.plan_status, "priority": row.priority, "note": row.note,
            "archive_canons": list(row.coverage.archive_canons),
            "hours_by_channel": {k: round(v, 3) for k, v in row.coverage.hours_by_channel.items()},
            "gaps": list(row.coverage.gaps),
        } for row in res.rows],
    }


def _format_stacks(root, db_path, s, limit=10):
    """Sformatuj `StackScanSummary` do ASCII (konsola Windows = cp1250).

    Raport nazywa ODMOWY, nie tylko sukcesy: droga wpuszczajaca 128 plikow z 259 pasujacych nazwie
    musi powiedziec, co zostawila i dlaczego — inaczej licznik „wciagnieto 128" jest twierdzeniem
    bez dowodu. Sciezki ucinane do `limit`, ale liczniki ZAWSZE pelne (ucinanie listy nie ma prawa
    ucinac faktu)."""
    lines = [f"Horreum stacks {root} -> {db_path}:"]
    lines.append(f"  kandydaci: {s.candidates} (pochodne obrobki pominiete: {s.derived_skipped})")
    lines.append(f"  wciagniete: {s.ingested}; pominiete brama (mtime): {s.skipped}")
    lines.append(f"  nowe klatki: {s.scan.frames_new}; znane: {s.scan.frames_existing}; "
                 f"nowe kopie: {s.scan.locations_new}; odswiezone: {s.scan.locations_refreshed}")
    if s.rejected_kind:
        lines.append(f"  ODRZUCONE (zeznanie != master_light): {s.rejected_kind} {s.kinds_rejected}")
    if s.rejected_unreadable:
        lines.append(f"  ODRZUCONE (naglowek nieczytelny): {s.rejected_unreadable}")
    for p in s.rejected_paths[:limit]:
        lines.append(f"    {p}")
    if len(s.rejected_paths) > limit:
        lines.append(f"    ... i {len(s.rejected_paths) - limit} wiecej")
    if s.failed:
        lines.append(f"  BLEDY I/O (zero zapisu): {s.failed}")
        for p in s.failed_paths[:limit]:
            lines.append(f"    {p}")
    if s.cancelled:
        lines.append("  PRZERWANE na granicy pliku — baza spojna, ponowny przebieg dokonczy")
    return "\n".join(lines)


def _format_delta(db_path, rep):
    """Sformatuj DeltaReport do czytelnego ASCII (konsola Windows = cp1250 — bez znaków spoza ASCII)."""
    lines = [f"Horreum delta {db_path}:"]
    lines.append(f"  obiekt (light/master_light): {rep.object_resolved}/"
                 f"{rep.object_resolved + rep.object_unresolved} rozwiazane ({rep.object_pct}%); "
                 f"delta {rep.object_unresolved} w {len(rep.object_delta)} distinct")
    for raw, n in rep.object_delta:
        lines.append(f"    {raw} -> {n}")
    # POZA procentem wyzej: klatka bez `object_raw` nie ma nazwy, wiec nie wchodzi do mianownika —
    # ale musi byc widoczna, inaczej raport milczy o calej klasie (P-D, kotwica nawrotu).
    lines.append(f"  bez nazwy w naglowku (light/master_light): {rep.object_nameless}")
    # Osobna pozycja i TYLKO gdy jest co pokazac: RAW nie ma karty OBJECT z natury
    # (`resolver.NO_OBJECT_CARD_FILETYPES`), wiec droga naprawy jest inna — reka, nie writeback.
    if rep.object_nameless_raw:
        lines.append(f"    z tego format bez karty (RAW, do przypisania recznie): "
                     f"{rep.object_nameless_raw}")
    # Gotowe obrazy po integracji (D-P-I-5). Od D-0802-1 droga naprawy jest TA SAMA co u lightow
    # (karta OBJECT do pliku, GUI „Napraw naglowek…"), wiec wiersz nazywa populacje, nie zakaz.
    if rep.object_nameless_stacks:
        lines.append(f"    z tego gotowe stosy (po integracji): "
                     f"{rep.object_nameless_stacks}")
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
