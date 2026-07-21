"""Krok ZBIORCZY po skanie — resolver osi OBIEKT + filtr (PLAN §Etap 6, OSTATNI pierwszego przebiegu).

Domyka płaskie sortowanie o dwie interpretacje pochodne (jak grouper domknął teleskop/config):
czyta przez SELECT, rozwiązuje, a WSZYSTKIE zapisy idą przez `repo` (jedna klinga) — ten moduł nie
wykonuje DML. (Nazwa: `resolver` = orkiestracja; czyste funkcje wiedzy mieszkają w pakiecie
`resolve.*`, tak jak grouper↔`resolve.telescopes`.)

KIND-AWARENESS (firsthand Zdzinia): OBIEKT dotyczy WYŁĄCZNIE light/master_light — kalibracja
(flat/dark/bias/master_*) nie ma obiektu z definicji, więc jej `object_id=NULL` to POPRAWNY STAN, nie
delta (inaczej ~2333 FlatWizard-flatów = fałszywe „nierozwiązane"). Light nierozpoznany = delta: stan
(`object_id NULL`) jest deltą zapytywalną wprost; do tego JEDEN zbiorczy `object.review_summary`
(audyt bez szumu, jak backfill focratio). FILTR jest kind-AGNOSTYCZNY (flat też ma filtr) → backfill
zbiorczy `frame.filter_canon`; brak/pusty → NULL (W2, bez kanału review).
"""
from dataclasses import dataclass, field

from . import repo
from .resolve._coerce import _to_text
from .resolve._text import norm_alnum
from .resolve.filters import normalize_filter
from .resolve.objects import resolve_object
from .resolve.observatory import site_coords
from .resolve.regions import resolve_region
from .resolve.solar import resolve_solar

# Klatki, które MAJĄ obiekt nieba (kandydaci osi OBIEKT). Reszta (kalibracja, unknown) → object_id
# NULL bez review. `unknown` świadomie poza — sygnalizuje go osobny kanał `kind.unmapped` (§Etap 4).
LIGHT_KINDS = frozenset({"light", "master_light"})


@dataclass
class ResolveSummary:
    """Zliczenia jednego przebiegu `run_resolver` — do firsthand-weryfikacji."""
    frames: int = 0                       # wszystkie frame'y z nagłówkiem
    light_frames: int = 0                 # light/master_light (kandydaci osi OBIEKT)
    objects_new: int = 0                  # nowe wiersze object (distinct kanon)
    objects_assigned: int = 0             # light'y z przypisanym object_id
    objects_by_alias: int = 0             # z tego: przypisane przez ZAPISANY ALIAS (#8, P4)
    objects_by_region: int = 0            # z tego: przypisane ze WSPÓŁRZĘDNYCH (kompleks, #5)
    objects_review: int = 0               # light'y obecne-ale-nierozpoznane (delta, per-frame)
    objects_unresolved_distinct: int = 0  # distinct object_raw w delcie
    filters_set: int = 0                  # frame'y z niepustym filter_canon
    observatories_new: int = 0            # nowe stanowiska (seed z propose_observatory, created=True)
    observatories_assigned: int = 0       # klatki z przypisanym observatory_id
    gps_unparseable: int = 0              # klatki z GPS OBECNYM ale nieparsowalnym (→ review_summary)


def run_resolver(con, now):
    """Po skanie: dla każdego frame'a z nagłówkiem rozwiąż OBIEKT (tylko light/master_light) i FILTR
    (wszystkie). Obiekt rozpoznany → `upsert_object`+`assign_object` (+`add_object_alias`, gdy
    rozpoznanie pochodzi z NAZWY — region rozpoznaje ze współrzędnych i aliasu nie ma). Drabina
    szczebli: `resolve_solar`/`resolve_object` (header-primary ŚWIĘTE) → **ALIAS** (`object_alias`
    zapisany wcześniej — #8, P4; jawna wiedza o nazwie, `object_source='alias'`) → `resolve_region`
    (inferencja z geometrii, ostatni). **`object_source='user'` pomija CAŁĄ drabinę** (P4): decyzja
    człowieka nie jest re-derywowana ani nadpisywana przez żaden szczebel automatyczny. Light
    nierozpoznany → delta (jeden zbiorczy `object.review_summary`, liczony ze STANU
    `object_id IS NULL` — D5); kalibracja → pomijana (poprawny NULL). Filtr → backfill zbiorczy
    `filter_canon`. Zwraca `ResolveSummary`. Idempotentny."""
    s = ResolveSummary()
    rows = con.execute(
        "SELECT f.id AS fid, f.kind AS kind, f.object_id AS oid, f.object_source AS osrc, "
        "h.object_raw AS obj, h.filter_raw AS filt, h.ra_deg AS ra, h.dec_deg AS dec "
        "FROM frame f JOIN header h ON h.frame_id = f.id").fetchall()
    s.frames = len(rows)

    # Szczebel ALIASU (P4, D-P4-1): preload WSZYSTKICH aliasów raz na przebieg (literał — resolver
    # już czyta literałami). Snapshot z STARTU przebiegu jest bezpieczny (R#12): alias zapisany W TYM
    # przebiegu dotyczy nazwy, która właśnie trafiła wcześniejszym szczeblem deterministycznie.
    aliases = {}
    for a in con.execute(
            "SELECT a.alias_norm AS key, a.object_id AS oid FROM object_alias a").fetchall():
        aliases[a["key"]] = a["oid"]

    unresolved = {}        # object_raw -> liczba (tylko light/master_light, obecny-nierozpoznany)
    filter_items = []      # (frame_id, filter_canon) do backfillu zbiorczego
    for r in rows:
        # --- oś OBIEKT: kind-aware (kalibracja nie ma obiektu z definicji) ---
        if r["kind"] in LIGHT_KINDS:
            s.light_frames += 1
            if r["osrc"] == "user":
                # PRECEDENCJA `user` na WSZYSTKIE szczeble (P4): ręczne przypisanie pomija drabinę
                # — frame zachowuje obiekt usera, zero re-derywacji, zero nadpisywania. (Wcześniej
                # guard objmował tylko region; uogólniony na solar/deep-sky/alias/region.)
                pass
            else:
                # solar/komety PRZED deep-sky: mają własne ID (nie katalogi mgławic), krok 5a.
                ident = resolve_solar(r["obj"]) or resolve_object(r["obj"])
                alias_oid = None
                if ident is None:
                    # ALIAS po katalogu, PRZED regionem (#8, P4): alias = jawna wiedza o NAZWIE,
                    # region = inferencja z geometrii. Pusty klucz (norm_alnum("---") == "") pomija
                    # lookup — alias "" łapałby KAŻDĄ niealfanumeryczną nazwę (D-P4-2, R#3).
                    key = norm_alnum(r["obj"])
                    alias_oid = aliases.get(key) if key else None
                # REGION = OSTATNI szczebel (#5, P3): dopiero gdy zeznanie nagłówka i alias nic nie
                # dały — 547 klatek `NGC6992` leży WEWNĄTRZ promienia Veil i chroni je kolejność.
                if ident is None and alias_oid is None:
                    ident = resolve_region(r["ra"], r["dec"])
                if alias_oid is not None:
                    # Trafienie aliasu: obiekt i alias ISTNIEJĄ z definicji — BEZ upsert_object i
                    # BEZ zapisu aliasu; `object_source='alias'` (D-P4-6: klatka z aliasu zostaje
                    # re-derywowalna, 'user' rezerwuje się dla jawnego przypisania).
                    if repo.assign_object(con, frame_id=r["fid"], object_id=alias_oid,
                                          object_source="alias", now=now):
                        s.objects_assigned += 1
                        s.objects_by_alias += 1
                elif ident is not None:
                    oid, created = repo.upsert_object(
                        con, canon=ident.canon, catalog=ident.catalog, kind=ident.kind, now=now)
                    s.objects_new += created
                    if ident.alias_norm:    # region NIE aliasuje — rozpoznanie nie pochodzi z nazwy
                        repo.add_object_alias(con, alias_norm=ident.alias_norm, object_id=oid,
                                              source=ident.source, now=now)
                    if repo.assign_object(con, frame_id=r["fid"], object_id=oid,
                                          object_source=ident.source, now=now):
                        s.objects_assigned += 1
                        s.objects_by_region += ident.source == "region"
                elif r["oid"] is None:
                    # D5: delta ze STANU (`object_id IS NULL`), nie z rederywacji — frame przypisany
                    # (ręcznie lub wcześniej), którego nagłówek dziś się nie rozwiązuje, NIE wraca
                    # do review_summary (zgodnie z delta_report/review_queue, oba ze stanu).
                    raw = _to_text(r["obj"])
                    if raw is not None:              # obecny ale nierozpoznany → delta
                        unresolved[raw] = unresolved.get(raw, 0) + 1
                        s.objects_review += 1
            # obj brak (None) na lightcie → object_id NULL bez review (brak zeznania do rozwiązania)

        # --- oś FILTR: kind-agnostyczna (flat też ma filtr); brak/pusty → NULL (W2) ---
        fc = normalize_filter(r["filt"])
        if fc is not None:
            filter_items.append((r["fid"], fc))

    s.filters_set = len(filter_items)
    s.objects_unresolved_distinct = len(unresolved)
    repo.backfill_filter_canon(con, filter_items, now=now)        # no-op gdy pusto
    repo.flag_object_review_summary(
        con, sorted(unresolved.items(), key=lambda kv: (-kv[1], kv[0])), now=now)  # no-op gdy pusto

    # oś OBSERWATORIUM foldnięta tu (SPOT — jeden wjazd; callerzy bez zmian). GPS z `cards`, nie z pętli
    # `header` powyżej (osobny SELECT — SITELAT/SITELONG nie są polami gorącymi `header`).
    s.observatories_new, s.observatories_assigned, s.gps_unparseable = resolve_observatory(con, now)
    return s


def resolve_observatory(con, now):
    """Oś OBSERWATORIUM (PLAN_os_obserwatorium §2b): dla każdej klatki z GPS w `cards` (SITELAT/SITELONG,
    `value_raw` — string dla obu formatów) wyłoń stanowisko przez `repo.propose_observatory` (kotwica
    GEOMETRYCZNA, member-id) i przypisz. Brak GPS (oba raw None) → `observatory_id` NULL cicho (świadomy
    brak, jak 326 XISF). GPS OBECNY-ale-nieparsowalny → NULL + zliczenie do JEDNEGO `observatory.review_
    summary`. Iteracja `ORDER BY f.id` = pierwszy przebieg powtarzalny (§5 D4). Zwraca (new, assigned,
    gps_unparseable). Idempotentny: re-run zwraca te same id (anchor stabilny), zero nowych eventów."""
    rows = con.execute(
        "SELECT f.id AS fid, "
        "  (SELECT value_raw FROM cards WHERE frame_id = f.id AND keyword = 'SITELAT' "
        "   ORDER BY idx LIMIT 1) AS lat_raw, "
        "  (SELECT value_raw FROM cards WHERE frame_id = f.id AND keyword = 'SITELONG' "
        "   ORDER BY idx LIMIT 1) AS lon_raw "
        "FROM frame f ORDER BY f.id").fetchall()
    new = assigned = 0
    unparseable = {}          # (lat_raw, lon_raw) -> liczba (GPS obecny ale nieparsowalny)
    for r in rows:
        pt = site_coords(r["lat_raw"], r["lon_raw"])
        if pt is None:
            if r["lat_raw"] or r["lon_raw"]:            # raw OBECNE ale śmieciowe → delta (review)
                key = (r["lat_raw"], r["lon_raw"])
                unparseable[key] = unparseable.get(key, 0) + 1
            continue                                    # oba raw None → observatory_id NULL cicho
        obs_id, created = repo.propose_observatory(con, lat=pt[0], lon=pt[1], now=now)
        new += created
        if repo.assign_observatory(con, frame_id=r["fid"], observatory_id=obs_id, now=now):
            assigned += 1
    # klucz sortu = str(para) — pary raw mogą zawierać None (nieporównywalne z str inaczej), det.
    repo.flag_observatory_review_summary(
        con, sorted(unparseable.items(), key=lambda kv: (-kv[1], str(kv[0]))), now=now)  # no-op gdy pusto
    return new, assigned, sum(unparseable.values())


@dataclass
class ReviewState:
    """Kolejka przeglądu wyprowadzona ze STANU tabel — NIE ze zliczania eventów (#12).

    `flag_config_review` i pokrewne emitują BEZWARUNKOWO przy każdym przebiegu (grouper iteruje
    WSZYSTKIE klatki z nagłówkiem), więc `count(event)` mnożył licznik przez liczbę dostaw: 7 klatek
    czekających na decyzję pokazywało się jako 35 po pięciu przebiegach. Stan jest idempotentny —
    ta sama derywacja, co kolejka osi obiektu w `gui.queries.review_queue`.

    Kubełki NIE są rozłączne: klatka bez kamery nie da się złożyć w config, więc liczy się w
    `no_camera` I `no_config`. `total` to DISTINCT klatek — NIGDY suma pól.

    `unreadable` (#13) to fakt o KOPII (location.unreadable_since), zliczany PO KLATKACH (DISTINCT
    frame z ≥1 taką kopią — spójnie z resztą liczników, które są per-klatka). Kubełek zachodzi z
    innymi jak dotychczasowe (kopia nieczytelna może być frame'em-szkieletem = też `headerless`)."""
    no_config: int = 0        # config_id NULL mimo zeznania (bez EXISTS(header) zlałby się headerless)
    headerless: int = 0       # brak wiersza `header` — plik nieczytelny przy skanie (frame-szkielet)
    no_camera: int = 0        # camera_id NULL mimo zeznania (brak INSTRUME/XPIXSZ)
    kind_unknown: int = 0     # zeznanie JEST, rodzaju nie dało się zmapować
    unreadable: int = 0       # ≥1 kopia z unreadable_since NOT NULL (kopia stała się nieczytelna; #13)
    total: int = 0            # DISTINCT klatek w KTÓRYMKOLWIEK kubełku (nie suma — kubełki zachodzą)


def review_state(con):
    """Policz kolejkę przeglądu ze STANU (read-only, zero zapisu). Po co i dlaczego DISTINCT — zob.
    `ReviewState`.

    `kind_unknown` idzie po `EXISTS(header)`, NIE po karcie IMAGETYP: `cards` są FITS-only (klatki
    XISF nie mają kart), więc predykat na kartach byłby ślepy na XISF. Predykat jest przy tym
    świadomie SZERSZY od dawnego eventu `kind.unmapped` (ten wymagał NIEPUSTEGO IMAGETYP): czytelne
    zeznanie z nierozpoznanym rodzajem wymaga decyzji tak samo jak zeznanie z rodzajem niezmapowanym
    — brak IMAGETYP był dotąd cichym NULL-em, którego raport nie pokazywał.

    `unreadable` (#13) idzie po `location.unreadable_since IS NOT NULL` (join po kopii, DISTINCT po
    klatce) i dokłada TRZECI dyzjunkt do `total` — kopia, która stała się nieczytelna, wchodzi do
    kolejki jak „bez nagłówka", nawet gdy frame ma poprawne zeznanie (marker gaśnie po udanym odczycie)."""
    no_config = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    headerless = con.execute(
        "SELECT count(*) FROM frame f "
        "WHERE NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    no_camera = con.execute(
        "SELECT count(*) FROM frame f WHERE f.camera_id IS NULL "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    kind_unknown = con.execute(
        "SELECT count(*) FROM frame f WHERE f.kind = 'unknown' "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    # #13: DISTINCT klatek z ≥1 kopią oznaczoną nieczytelną (fakt o KOPII zliczony po klatkach —
    # spójność z resztą liczników). Join po location; DISTINCT bo frame 1:N location.
    unreadable = con.execute(
        "SELECT count(DISTINCT f.id) FROM frame f JOIN location l ON l.frame_id = f.id "
        "WHERE l.unreadable_since IS NOT NULL").fetchone()[0]
    total = con.execute(
        "SELECT count(*) FROM frame f WHERE "
        "NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id) "
        "OR ((f.config_id IS NULL OR f.camera_id IS NULL OR f.kind = 'unknown') "
        "    AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)) "
        "OR EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id "
        "           AND l.unreadable_since IS NOT NULL)").fetchone()[0]
    return ReviewState(no_config=no_config, headerless=headerless, no_camera=no_camera,
                       kind_unknown=kind_unknown, unreadable=unreadable, total=total)


@dataclass
class DeltaReport:
    """Read-only delta do review (§Etap 6/§4.7) — wejście do przyszłego import-legacy. Liczy obiekt
    na light/master_light (kalibracja świadomie poza — nie ma obiektu)."""
    object_resolved: int = 0
    object_unresolved: int = 0
    object_pct: float = 0.0
    object_delta: list = field(default_factory=list)   # [(object_raw, count)] nierozpoznane light'y
    review: ReviewState = field(default_factory=ReviewState)   # kolejka ze STANU (#12), nie z eventów
    filters_canon: int = 0


def delta_report(con, top=30):
    """Zbierz deltę nierozstrzygniętych (read-only, zero zapisu). % obiektu liczone NA light'ach
    (mianownik = light/master_light z obecnym object_raw); kalibracja nie zaniża wyniku."""
    resolved = con.execute(
        "SELECT count(*) FROM frame WHERE kind IN ('light','master_light') "
        "AND object_id IS NOT NULL").fetchone()[0]
    unresolved = con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "AND h.object_raw IS NOT NULL").fetchone()[0]
    total = resolved + unresolved
    pct = round(100.0 * resolved / total, 1) if total else 0.0
    delta = con.execute(
        "SELECT h.object_raw AS raw, count(*) AS n FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "AND h.object_raw IS NOT NULL GROUP BY h.object_raw ORDER BY n DESC, raw LIMIT ?",
        (top,)).fetchall()
    filters_canon = con.execute(
        "SELECT count(*) FROM frame WHERE filter_canon IS NOT NULL").fetchone()[0]
    return DeltaReport(
        object_resolved=resolved, object_unresolved=unresolved, object_pct=pct,
        object_delta=[(r["raw"], r["n"]) for r in delta], review=review_state(con),
        filters_canon=filters_canon)
