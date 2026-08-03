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
import json
from dataclasses import dataclass, field

from . import repo
from .grouper import NO_TELESCOPE_KINDS
from .resolve._coerce import _to_text
from .resolve._text import norm_alnum
from .resolve.filters import normalize_filter
from .resolve.objects import load_own_objects, resolve_object
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
    own_aliases_seeded: int = 0           # nowe równoważności ze słownika obiektów własnych (S1)
    own_aliases_retired: int = 0          # równoważności zdjęte po edycji słownika (migracja)
    own_frames_unassigned: int = 0        # klatki odpięte razem z wycofaną równoważnością
    own_alias_conflicts: int = 0          # nazwy zajęte przez INNY obiekt (pominięte, → review)


def sync_own_aliases(con, now, s=None):
    """Zsynchronizuj `object_alias` ze słownikiem obiektów własnych — DIFF-FIRST (D-OW-4/A′).

    Nazwy potoczne z assetu (`n`) stają się równoważnościami, żeby szukajka i „Napraw nagłówek…"
    znały „Large Magellanic Cloud", nie tylko kanon `LMC`. Zasiew jest przywiązany do TOŻSAMOŚCI,
    nie do szczebla: liczy się to, że obiekt o tym kanonie ISTNIEJE — nieważne, którędy jego klatki
    kanon dostały.

    ZAKRES = OBIEKTY ISTNIEJĄCE, nigdy wpisy assetu (`object_alias.object_id` to `NOT NULL
    REFERENCES object(id)` przy `foreign_keys=ON`): dopóki żadna klatka nie ma `LMC`, nie ma czego
    aliasować i nie ma to skutku — asset opisuje klasę, baza opisuje archiwum.

    DIFF-FIRST, nie kasuj-i-wstaw: liczymy zestaw docelowy, porównujemy z istniejącym i przy zerowej
    różnicy NIE wykonujemy DML ani nie emitujemy (wzorzec `repo.backfill_filter_canon`). Naiwne
    DELETE+INSERT emitowałoby przy każdym przebiegu i churnowało `id`.

    KOLIZJA MA TRZY GAŁĘZIE, NIE WYJĄTEK: `alias_norm` jest UNIQUE i może już należeć do TEGO
    obiektu (zostaw — nic do zrobienia) albo do INNEGO (pomiń + jeden ZBIORCZY event przeglądu).
    Sprawdzamy to SELECT-em PRZED `repo.add_object_alias`, bo ta funkcja zwraca istniejący wiersz
    BEZ porównania `object_id` — „jest idempotentna, więc wystarczy ją zawołać" nigdy nie odpaliłoby
    gałęzi kolizji i przegrany ginąłby cicho. Wyjątku tu nie rzucamy: ta funkcja biegnie w passie
    masowym Dostawy, a `gui/pipeline` zamieniłby go w `failed` i urwał `calibrate`/`lineage`/`delta`
    z powodu danych, które user miał prawo stworzyć."""
    s = s if s is not None else ResolveSummary()

    obiekty = {r["canon"]: r["id"] for r in con.execute("SELECT id, canon FROM object").fetchall()}
    chciane = {}                                   # alias_norm -> object_id (tylko istniejące obiekty)
    for rec in load_own_objects():
        oid = obiekty.get(_to_text(rec.get("c")))
        if oid is None:
            continue
        for name in (rec.get("c"), *(rec.get("n") or ())):
            key = norm_alnum(name or "")
            if key:
                chciane[key] = oid

    istniejace = {r["key"]: r["oid"] for r in con.execute(
        "SELECT alias_norm AS key, object_id AS oid FROM object_alias").fetchall()}
    zasiane = {r["key"]: r["oid"] for r in con.execute(
        "SELECT alias_norm AS key, object_id AS oid FROM object_alias "
        "WHERE source = 'curated'").fetchall()}

    kolizje = []
    for key, oid in sorted(chciane.items()):
        czyj = istniejace.get(key)
        if czyj == oid:
            continue                               # już jest (nasz albo cudzym szczeblem) — zostaw
        if czyj is not None:
            kolizje.append([key, czyj, oid])       # nazwa zajęta przez INNY obiekt — pomiń
            continue
        _, created = repo.add_object_alias(con, alias_norm=key, object_id=oid,
                                           source="curated", now=now)
        s.own_aliases_seeded += created

    # WYCOFANIE: równoważności zasiane wcześniej, których asset już nie zna. Grupujemy po obiekcie,
    # bo klinga odpina klatki tego obiektu jednym przebiegiem.
    zbedne = {}
    for key, oid in sorted(zasiane.items()):
        if chciane.get(key) != oid:
            zbedne.setdefault(oid, []).append(key)
    for oid, keys in zbedne.items():
        wycofane, odpiete = repo.retire_alias_and_unassign(
            con, object_id=oid, alias_norms=keys, now=now)
        s.own_aliases_retired += wycofane
        s.own_frames_unassigned += odpiete

    if kolizje:
        s.own_alias_conflicts += len(kolizje)
        repo.flag_object_alias_conflicts(con, kolizje, now)
    return s


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
    `filter_canon`. Zwraca `ResolveSummary`. Idempotentny.

    SŁOWNIK OBIEKTÓW WŁASNYCH siedzi WEWNĄTRZ `resolve_object` (ostatni jego szczebel), więc stoi
    przed aliasem i regionem — jest jawną wiedzą o NAZWIE, jak `_COMMON`, a nie inferencją. Dzięki
    temu widzi go też `name_resolves`, czyli walidacja dialogu „Napraw nagłówek…". Zasiew nazw
    potocznych tego słownika domyka przebieg (`sync_own_aliases`)."""
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

    # ZASIEW NAZW POTOCZNYCH — PO pętli, i to jest jedyna kolejność, która działa na świeżej bazie:
    # zasiew wymaga ISTNIEJĄCEGO obiektu, a `LMC` powstaje dopiero, gdy szczebel słownika przypisze
    # pierwszą klatkę. Idempotentny, więc drugi przebieg jest ciszą.
    sync_own_aliases(con, now, s)

    # oś OBSERWATORIUM foldnięta tu (SPOT — jeden wjazd; callerzy bez zmian). GPS z `cards`, nie z pętli
    # `header` powyżej (osobny SELECT — SITELAT/SITELONG nie są polami gorącymi `header`).
    s.observatories_new, s.observatories_assigned, s.gps_unparseable = resolve_observatory(con, now)
    return s


def resolve_observatory(con, now):
    """Oś OBSERWATORIUM (PLAN_os_obserwatorium §2b): dla każdej klatki z GPS w `cards` (SITELAT/SITELONG,
    `value_raw` — string dla obu formatów) wyłoń stanowisko przez `repo.propose_observatory` (kotwica
    GEOMETRYCZNA, member-id) i przypisz. Brak GPS (oba raw None) → `observatory_id` NULL cicho (świadomy
    brak — kalibracja i klatki sprzed montażu GPS; XISF-y już tu NIE należą: od P6a/P6b mają karty,
    więc 202 z nich wchodzą na oś). GPS OBECNY-ale-nieparsowalny → NULL + zliczenie do JEDNEGO `observatory.review_
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
    no_config: int = 0        # config_id NULL mimo zeznania, POZA kalibracją bez osi (kind-scoping)
    headerless: int = 0       # brak wiersza `header` — plik nieczytelny przy skanie (frame-szkielet)
    no_camera: int = 0        # camera_id NULL mimo zeznania (brak INSTRUME/XPIXSZ)
    kind_unknown: int = 0     # zeznanie JEST, rodzaju nie dało się zmapować
    unreadable: int = 0       # ≥1 kopia z unreadable_since NOT NULL (kopia stała się nieczytelna; #13)
    total: int = 0            # DISTINCT klatek w KTÓRYMKOLWIEK kubełku (nie suma — kubełki zachodzą)


def review_state(con):
    """Policz kolejkę przeglądu ze STANU (read-only, zero zapisu). Po co i dlaczego DISTINCT — zob.
    `ReviewState`.

    `kind_unknown` idzie po `EXISTS(header)`, NIE po karcie IMAGETYP: kolejka przeglądu pyta o ZEZNANIE
    (jeden wiersz na klatkę), nie o jego lustro. Do P6a `cards` były w dodatku FITS-only, więc predykat
    na nich był wprost ŚLEPY na 326 XISF-ów — dziś karty ma już każdy czytelny format, ale reguła
    zostaje: lustro może być niekompletne (plik nieparsowalny, lokacja sprzed backfillu), zeznanie
    rozstrzyga. Predykat jest przy tym
    świadomie SZERSZY od dawnego eventu `kind.unmapped` (ten wymagał NIEPUSTEGO IMAGETYP): czytelne
    zeznanie z nierozpoznanym rodzajem wymaga decyzji tak samo jak zeznanie z rodzajem niezmapowanym
    — brak IMAGETYP był dotąd cichym NULL-em, którego raport nie pokazywał.

    `unreadable` (#13) idzie po `location.unreadable_since IS NOT NULL` (join po kopii, DISTINCT po
    klatce) i dokłada TRZECI dyzjunkt do `total` — kopia, która stała się nieczytelna, wchodzi do
    kolejki jak „bez nagłówka", nawet gdy frame ma poprawne zeznanie (marker gaśnie po udanym odczycie).

    `no_config` jest KIND-AWARE (`grouper.NO_TELESCOPE_KINDS`): dark/bias nie mają osi teleskopu, więc
    ich `config_id IS NULL` to stan docelowy, nie delta — tak jak `object_id IS NULL` dla kalibracji.
    Lista rodzajów idzie do SQL przez `json_each(?)` (literał stały + jeden parametr), żeby zbiór miał
    JEDNEGO właściciela w `grouper` zamiast kopii wklejonej w predykat."""
    off_axis = json.dumps(sorted(NO_TELESCOPE_KINDS))
    no_config = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.kind NOT IN (SELECT value FROM json_each(?)) "
        "AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)", (off_axis,)).fetchone()[0]
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
        "OR (((f.config_id IS NULL "
        "      AND f.kind NOT IN (SELECT value FROM json_each(?))) "
        "     OR f.camera_id IS NULL OR f.kind = 'unknown') "
        "    AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)) "
        "OR EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id "
        "           AND l.unreadable_since IS NOT NULL)", (off_axis,)).fetchone()[0]
    return ReviewState(no_config=no_config, headerless=headerless, no_camera=no_camera,
                       kind_unknown=kind_unknown, unreadable=unreadable, total=total)


NO_OBJECT_CARD_FILETYPES = ("raw",)
"""Formaty, które NIE MAJĄ JAK zeznać o obiekcie — JEDYNY właściciel tego faktu.

EXIF nie zna pola `OBJECT` ani RA/DEC, więc RAW-owy light nie dostanie obiektu ANI z nagłówka,
ANI z regionu po współrzędnych: milczenie tego pliku jest STANEM DOCELOWYM formatu, nie luką
do naprawienia. Zmierzone na realnym archiwum 2026-08-01: **0 z 763** RAW-lightów ma `object_raw`.

To ta sama figura myślowa, co `grouper.NO_TELESCOPE_KINDS` na osi teleskopu i „kalibracja nie ma
obiektu" na osi obiektu (kind-aware) — tyle że oś podziału jest tu FORMAT, nie rodzaj klatki.
Konsumenci biorą TĘ stałą przez `json_each(?)`; kopiowanie listy do predykatu jest zakazane
(#12 „jeden właściciel").

Czego ta stała NIE mówi: że RAW nie wymaga przeglądu. Wymaga — tylko drogą RĘCZNĄ
(„Przypisz obiekt…"), nie kartą w pliku (`macro.resolve_target` odmawia RAW: read-only).
Dlatego populacja idzie do WŁASNEGO kubełka (`nameless_raw_lights`), a nie znika z rachunku."""


def name_resolves(con, text):
    """Czy przebieg resolvera rozpozna TĘ NAZWĘ po wpisaniu jej do nagłówka — pytanie bramki dialogu
    „Napraw nagłówek…" (P-D), zadane TĄ SAMĄ drabiną, którą pójdzie `run_resolver`. Read-only.

    Szczeble zależne od NAZWY, w kolejności przebiegu: `resolve_solar` → `resolve_object` → **ALIAS**
    (`object_alias` — jawna wiedza usera z „Przypisz obiekt…"). Region świadomie POZA drabiną: on
    rozpoznaje ze WSPÓŁRZĘDNYCH, więc od wpisanego tekstu nie zależy, a dla każdej klatki wchodzącej
    do dialogu (`object_id IS NULL`) już się nie odezwał.

    Dlaczego nie sam `resolve_object` (adjudykacja bramki, 2026-08-01): pytanie „czy po zapisie oś
    się wypełni" ma w przebiegu TRZY odpowiedzi twierdzące, a bramka znała jedną. Zmierzone odmowy
    fałszywe: `Moon`/`Jupiter`/`C/2023 A3` (solar — archiwum ma `_COMETS` i `_SOLAR` jako realne
    lighty) oraz nazwa świeżo nauczona aliasem (`WR134` — cel z `data/curated.json`, bez numeru
    katalogowego). Obie populacje resolver rozwiązuje, więc odmowa zapisu była nieprawdą o własnym
    zachowaniu."""
    if resolve_solar(text) is not None or resolve_object(text) is not None:
        return True
    key = norm_alnum(text)
    if not key:      # pusty klucz łapałby KAŻDĄ niealfanumeryczną nazwę (D-P4-2, R#3)
        return False
    return con.execute(
        "SELECT 1 FROM object_alias WHERE alias_norm = ?", (key,)).fetchone() is not None


def nameless_lights(con):
    """Lighty, których nagłówek MILCZY o obiekcie, a format POZWALAŁBY mu mówić: `object_id IS NULL`,
    wiersz `header` JEST, `object_raw IS NULL`, `filetype` spoza `NO_OBJECT_CARD_FILETYPES` (P-D).
    Rdzeniowy właściciel predykatu — read-only, zero zapisu.

    Po co osobno od `object_unresolved`: mianownik delty WYMAGA `object_raw NOT NULL`
    (`delta_report` niżej), więc raport dostawy był na tę populację ŚLEPY — bramka akceptacji
    świeciła zielono o klatkach, których nie widzi, a pierwsza nowa dostawa bez `OBJECT`
    przeszłaby bez śladu. To jest KOTWICA NAWROTU: P-D naprawiła 25 plików na `R:` (pilot
    2026-08-01), a ta liczba pilnuje, żeby populacja nie odrosła po cichu.

    ŚWIADOMA FORMATU od 2026-08-01: bez tego warunku kotwica mieszała 25 klatek FITS (naprawialnych
    kartą) z 763 RAW-ami, których naprawić się NIE DA — jedna liczba na dwie populacje nie pilnuje
    żadnej z nich, bo ruch jednej maskuje ruch drugiej. RAW liczy `nameless_raw_lights`.

    Drążenie do klatek (grupy, cel writebacku) daje `gui.queries.nameless_frames` — TEN SAM
    predykat, znak w znak. Dwa literały, bo warstwy są dwie i zależność idzie w jedną stronę
    (`gui.queries` importuje ten moduł, nie odwrotnie); równość obu pinuje test.

    ZAWĘŻONY DO `kind='light'` od 2026-08-01 (I-2b/D-P-I-5): gotowe stacki wciągnięte drogą
    „Stosy" są `master_light` i mają WŁASNY kubełek (`nameless_stacks`) — ta sama zasada, co przy
    RAW-ach, tylko oś inna. Bez zawężenia 22 stacki bez `OBJECT` dopisałyby się do 25 klatek
    archiwum i kotwica nawrotu przestałaby pilnować tej, dla której powstała.

    Literał PEŁNY, mimo że bliźniaki niżej różnią się jednym słowem: wspólny prefiks + sklejenie
    czyni SQL nie-literałem, a `_first_sql_verb` zwraca wtedy `None` = offender bramki AST §8.1
    (złapane przebiegiem 2026-08-01 — bramka zadziałała dokładnie tak, jak miała)."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "AND h.object_raw IS NULL "
        "AND f.filetype NOT IN (SELECT value FROM json_each(?))",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchone()[0]


def nameless_raw_lights(con):
    """Lighty bez obiektu w formacie, który NIE MA JAK go podać (`NO_OBJECT_CARD_FILETYPES`).

    Osobny kubełek, nie odjęcie: te klatki zostają w perspektywie „Do przeglądu" (`object_id IS
    NULL`), więc partycja kolejki musi je gdzieś policzyć — inaczej `review_queue` przestałaby
    domykać się do `review_frame_ids` dokładnie o tę populację. Droga naprawy jest inna niż dla
    `nameless_lights`: ręczne „Przypisz obiekt…", nigdy karta w pliku.

    `kind='light'` jest tu STRUKTURALNIE równoważne dawnemu `IN ('light','master_light')`, nie
    zawężeniem: `filetype='raw'` bierze rodzaj z FOLDERU (`kind_from_path`), a ta mapa zna
    wyłącznie light/dark/flat/bias — RAW-owy `master_light` nie ma jak powstać. Napisane wprost,
    żeby trzy kubełki były rozłączne z WIDOKU, nie z rozumowania."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "AND h.object_raw IS NULL "
        "AND f.filetype IN (SELECT value FROM json_each(?))",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchone()[0]


def nameless_stacks(con):
    """GOTOWE STACKI, których nagłówek milczy o obiekcie (I-2b/D-P-I-5): `kind='master_light'`,
    `object_id IS NULL`, wiersz `header` JEST, `object_raw IS NULL`.

    TRZECI kubełek tej samej partycji, z tego samego powodu co RAW-owy: `review_frame_ids` pyta
    o sam brak obiektu, więc stacki w nim SĄ — wycięcie ich z `nameless_lights` bez policzenia
    tutaj rozspójniłoby kolejkę dokładnie o tę populację.

    DROGA NAPRAWY JEST TA SAMA CO U LIGHTÓW od D-0802-1 (2026-08-02): karta `OBJECT` wraca do
    PLIKU, oknem „Napraw nagłówek…". Do tego dnia kubełek był INFORMACYJNY z powodu, który
    przestał obowiązywać — pisarz XISF nie umiał dopisać karty (D-X-12), więc akcja kończyłaby się
    'blocked' na każdej pozycji; P6d go tego nauczyła (`scan.build_fits_keyword_element`).

    OSOBNY kubełek zostaje, bo to osobna POPULACJA: gotowy obraz po integracji nie jest klatką
    z teleskopu, a partycja kolejki musi liczyć oba zbiory rozłącznie (`review_frame_ids` pyta
    o sam brak obiektu, więc stacki w nim SĄ). Drążenie do klatek =
    `gui.queries.nameless_stack_frames` — ten sam predykat, znak w znak; równość pinuje test."""
    return con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'master_light' AND f.object_id IS NULL "
        "AND h.object_raw IS NULL").fetchone()[0]


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
    object_nameless: int = 0   # lighty BEZ `object_raw` — poza mianownikiem delty (P-D/D-PD-10)
    # …a te BEZ `object_raw` i bez SZANSY na niego (format nie zna karty; `NO_OBJECT_CARD_FILETYPES`).
    # Osobne pole, bo osobna droga naprawy: ręczne przypisanie, nigdy zapis karty do pliku.
    object_nameless_raw: int = 0
    # …a te są GOTOWYMI OBRAZAMI po integracji (I-2b/D-P-I-5). Osobne pole, bo osobna POPULACJA —
    # droga naprawy jest od D-0802-1 TA SAMA co u lightów (karta `OBJECT` do pliku, P6d).
    object_nameless_stacks: int = 0
    # Klatki, które obiekt MAJĄ, choć nazwy w nagłówku nie było — rozwiązane innym świadkiem niż
    # nazwa (dziś: region). Do `object_pct` NIE wchodzą, bo procent mierzy rozpoznanie NAZWY, a te
    # klatki nazwy nie mają. Stoją obok, żeby zawężenie licznika niczego nie schowało.
    # ŚWIADOMIE `LEFT JOIN`, wbrew symetrii z bliźniakami (one mają INNER): pole ma pokazać CAŁĄ
    # populację wypchniętą z procentu, a wypada z niego również klatka bez wiersza `header` w ogóle.
    # Dwie klasy pod jedną liczbą — dziś druga jest pusta (szkielety mają `kind='unknown'`, więc nie
    # są lightem), ale gdyby przestała być, to TU się pokaże, zamiast zniknąć między predykatami.
    object_resolved_no_raw: int = 0


def delta_report(con, top=30):
    """Zbierz deltę nierozstrzygniętych (read-only, zero zapisu). % obiektu liczone NA light'ach
    (mianownik = light/master_light z obecnym object_raw); kalibracja nie zaniża wyniku.

    LICZNIK STOI NA TEJ SAMEJ POPULACJI CO MIANOWNIK — `object_raw NOT NULL` po obu stronach.
    Wcześniej licznik brał każdą klatkę z obiektem, także rozwiązaną REGIONEM bez nazwy w nagłówku,
    więc procent rósł o klatki, których mianownik nie widział, i **maskował spadek rozpoznania**:
    napływ klatek nierozpoznanych rozcieńczał się o stałą premię. Wypchnięta populacja nie znika
    z raportu — ma własne pole `object_resolved_no_raw`.

    `object_nameless` stoi OBOK procentu, nie w nim: klatka bez `object_raw` nie ma jak być
    „nierozpoznana pod nazwą" (nie ma nazwy), więc do mianownika nie wchodzi — ale musi być
    WIDOCZNA, inaczej raport milczy o całej klasie (P-D/D-PD-10).

    `object_nameless_raw` i `object_nameless_stacks` idą OSOBNO od `object_nameless`, bo to trzy
    różne POPULACJE pod jednym objawem: light archiwum i gotowy stos naprawia karta w pliku
    (stos od D-0802-1/P6d — wcześniej nie naprawiało go nic), RAW-a wyłącznie ręka. Zlanie ich
    w jedną liczbę sprawia, że kotwica nawrotu nie pilnuje żadnej — 763 RAW-y przykryłyby każdy
    ruch w populacji FITS, a 22 stacki przykryłyby ruch w niej po raz drugi."""
    resolved = con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NOT NULL "
        "AND h.object_raw IS NOT NULL").fetchone()[0]
    resolved_no_raw = con.execute(
        "SELECT count(*) FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NOT NULL "
        "AND h.object_raw IS NULL").fetchone()[0]
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
        object_resolved_no_raw=resolved_no_raw,
        object_delta=[(r["raw"], r["n"]) for r in delta], review=review_state(con),
        filters_canon=filters_canon, object_nameless=nameless_lights(con),
        object_nameless_raw=nameless_raw_lights(con),
        object_nameless_stacks=nameless_stacks(con))
