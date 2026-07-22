"""Read-model osi TELESKOP (PLAN_gui §5 — read path). Czyste funkcje `con → list[Row]`,
testowalne BEZ Qt. ODCZYT nie jest „jedną klingą" (klinga dotyczy ZAPISU emitującego event) —
SELECT wolno wszędzie; zapis usera idzie WYŁĄCZNIE przez `horreum.repo`.

TWARDE OGRANICZENIE (PLAN_gui §4, rec. nr 6): wyłącznie **SQL-LITERAŁY + parametry `?`** oraz
wyłącznie **`con.execute`** (bez pandas/ORM/`read_sql` — ścieżki niewidziane przez meta-test AST,
`EXEC_METHODS=execute*`). Dynamiczny SQL (f-string) w tym pliku WYSADZIŁBY bramkę §7.1, mimo że to
czysty odczyt: `_first_sql_verb` zwraca `None` dla nie-literału, a `None` poza `repo.py`/`db.py`
= offender. Warianty/filtry => parametry `?` w stałym literale albo OSOBNE literały w gałęziach `if`,
NIGDY składanie stringa SQL. Listy zmiennej długości (id/keywordy) idą jako TABLICA JSON przez
`json_each(?)` — literał stały, jeden parametr (zamiast dynamicznych `?` — PLAN_gui_grid §3).
"""

import json

from horreum.resolver import review_state


def active_telescopes(con):
    """Aktywne (KANONICZNE) teleskopy z licznością klatek — lista główna GUI.

    Filtr kanoniczności JAWNY (`WHERE t.merged_into IS NULL`, rec.R2 nr 2): widok
    `telescope_canonical` zwraca WSZYSTKIE wiersze (kanon + scalone z ich `canon_id`), więc sam join
    przez widok nie odsiewa scalonych — bez tego WHERE scalony `approved` wyciekłby jako osobny wiersz
    (§3b). Licznik agreguje po `canon_id` ścieżką `telescope_canonical → config → frame` (rec. nr 7):
    klatki scalonych członków rolują się pod kanon, kolizja kamery (dwa configi tej samej kamery)
    sumuje się pod jednym kanonem. `LEFT JOIN` => teleskop bez klatek ma `frame_count=0` (nie znika).
    Frame z `config_id IS NULL` (review) NIE dołącza się do żadnego configu => poza sumą (poprawne —
    jest w delcie, nie na osi). Zwraca wiersze: id, telescop_canon, label, status, f_ratio_nominal,
    focal_nominal, frame_count."""
    return con.execute(
        "SELECT t.id, t.telescop_canon, t.label, t.status, t.f_ratio_nominal, t.focal_nominal, "
        "       COUNT(fr.id) AS frame_count "
        "FROM telescope t "
        "LEFT JOIN telescope_canonical tc ON tc.canon_id = t.id "
        "LEFT JOIN config c ON c.telescope_id = tc.id "
        "LEFT JOIN frame fr ON fr.config_id = c.id "
        "WHERE t.merged_into IS NULL "
        "GROUP BY t.id "
        "ORDER BY t.id"
    ).fetchall()


def merged_under(con, canon_id):
    """Teleskopy scalone „pod" danym kanonem (widok szczegółu — co zwinięto w ten teleskop). Dzięki
    inwariantowi głębokość ≤ 1 (§3a) wszystkie są BEZPOŚREDNIMI członkami (`merged_into = canon_id`),
    więc prosty filtr po kolumnie wystarcza — nie ma głębszych łańcuchów do rozwijania. Zwraca wiersze:
    id, telescop_canon, label, status, f_ratio_nominal, focal_nominal (puste, gdy nic nie scala)."""
    return con.execute(
        "SELECT id, telescop_canon, label, status, f_ratio_nominal, focal_nominal "
        "FROM telescope WHERE merged_into = ? ORDER BY id",
        (canon_id,),
    ).fetchall()


def axis_events(con, telescope_id=None, limit=200):
    """Podgląd eventów osi teleskopu (audyt — kto/kiedy/before→after). `telescope_id=None` => cała oś
    (`target LIKE 'telescope:%'`, w tym `telescope.proposed/review` od groupera); inaczej historia
    JEDNEGO teleskopu (`target = 'telescope:<id>'`). Najnowsze pierwsze (`id DESC`), ucięte do `limit`.

    Dwie OSOBNE gałęzie z literałami SQL (nie jeden f-string) — wariant filtra przez parametr `?`
    w stałym literale, zgodnie z §4 (dynamiczny SQL wysadziłby bramkę). `target` składamy w Pythonie
    i wiążemy jako `?` — to wartość parametru, nie tekst SQL (literał pozostaje stały)."""
    if telescope_id is None:
        return con.execute(
            "SELECT id, ts, actor, verb, target, payload, reason FROM event "
            "WHERE target LIKE 'telescope:%' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return con.execute(
        "SELECT id, ts, actor, verb, target, payload, reason FROM event "
        "WHERE target = ? ORDER BY id DESC LIMIT ?",
        (f"telescope:{telescope_id}", limit),
    ).fetchall()


# ============================================================ oś OBSERWATORIUM (PLAN_os_obserwatorium §3)
# Read-model osi stanowisk — mirror osi teleskopu (lista→scal→nazwij). RÓŻNICA: licznik klatek liczony
# ścieżką `observatory_canonical → frame` BEZPOŚREDNIO przez `frame.observatory_id` (obserwatorium NIE ma
# configu — inaczej niż teleskop). Filtr kanoniczności JAWNY (`WHERE merged_into IS NULL`), jak teleskop.


def active_observatories(con):
    """Aktywne (KANONICZNE) stanowiska z licznością klatek — lista główna osi OBSERWATORIUM.

    Filtr kanoniczności JAWNY (`WHERE o.merged_into IS NULL`, jak `active_telescopes`): widok
    `observatory_canonical` zwraca WSZYSTKIE wiersze (kanon + scalone), więc sam join go nie odsiewa —
    bez WHERE scalony wyciekłby jako osobny wiersz. Licznik agreguje po `canon_id` ścieżką
    `observatory_canonical → frame` BEZPOŚREDNIO przez `frame.observatory_id` (BEZ configu): klatki
    scalonych członków rolują się pod kanon. `LEFT JOIN` => stanowisko bez klatek ma `frame_count=0`
    (nie znika). Zwraca: id, name, lat, lon, elev, status, frame_count."""
    return con.execute(
        "SELECT o.id, o.name, o.lat, o.lon, o.elev, o.status, "
        "       COUNT(fr.id) AS frame_count "
        "FROM observatory o "
        "LEFT JOIN observatory_canonical oc ON oc.canon_id = o.id "
        "LEFT JOIN frame fr ON fr.observatory_id = oc.id "
        "WHERE o.merged_into IS NULL "
        "GROUP BY o.id "
        "ORDER BY o.id"
    ).fetchall()


def merged_under_observatory(con, canon_id):
    """Stanowiska scalone „pod" danym kanonem (widok szczegółu — co zwinięto w to stanowisko). Dzięki
    inwariantowi głębokość ≤ 1 (gwardy `merge_observatory`) wszystkie są BEZPOŚREDNIMI członkami
    (`merged_into = canon_id`). Zwraca: id, name, lat, lon, elev, status (puste, gdy nic nie scala)."""
    return con.execute(
        "SELECT id, name, lat, lon, elev, status "
        "FROM observatory WHERE merged_into = ? ORDER BY id",
        (canon_id,),
    ).fetchall()


def observatory_axis_events(con, observatory_id=None, limit=200):
    """Podgląd eventów osi obserwatorium (audyt — kto/kiedy/before→after). `observatory_id=None` =>
    cała oś (`target LIKE 'observatory:%'`: proposed/named/merged/unmerged); inaczej historia JEDNEGO
    stanowiska. Najnowsze pierwsze (`id DESC`), ucięte do `limit`. Dwie OSOBNE gałęzie z literałami SQL
    (§4 — dynamiczny SQL wysadziłby bramkę); `target` składany w Pythonie i wiązany jako `?`.
    (`observatory.assigned` celuje w `frame:<id>` — per-klatka, świadomie poza audytem osi, jak
    `config.assigned` przy teleskopie.)"""
    if observatory_id is None:
        return con.execute(
            "SELECT id, ts, actor, verb, target, payload, reason FROM event "
            "WHERE target LIKE 'observatory:%' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return con.execute(
        "SELECT id, ts, actor, verb, target, payload, reason FROM event "
        "WHERE target = ? ORDER BY id DESC LIMIT ?",
        (f"observatory:{observatory_id}", limit),
    ).fetchall()


# ============================================================ oś OBIEKT (PLAN_gui_object §3, read-only)
# Read-model biblioteki + kolejki przeglądu. KIND-AWARE: obiekt liczony TYLKO na light/master_light
# (kalibracja nie ma obiektu z definicji — memory horreum-object-resolution-kind-aware). Filtr teleskopu
# ZAWSZE przez `telescope_canonical` (rolowanie scalonych pod kanon). Filtry opcjonalne realizowane
# wzorcem `(? IS NULL OR kol = ?)` w JEDNYM stałym literale (R#5) — NIE rozgałęzieniem 8 SELECT-ów:
# literał stały (bramka AST §7.1 widzi `SELECT`), wartość wiązana DWUKROTNIE per filtr.


def library_objects(con, *, telescope_id=None, camera_id=None, filter_canon=None):
    """Biblioteka: kanoniczne obiekty z licznością klatek (light/master_light), z OPCJONALNYMI filtrami
    osi. PREDYKAT = `frame.kind` (R#1: `object.kind` to inne pole — `deep_sky|solar_system|comet` po
    kroku 5a — i NIE jest zwracane ani używane jako predykat; widok renderuje `canon`/`catalog`).
    `telescope_id` = id KANONICZNEGO teleskopu (dopasowanie przez `telescope_canonical.canon_id`, więc
    klatki spod scalonych członków rolują się pod kanon). JOIN (nie LEFT) frame→object: obiekt bez
    klatek po filtrze znika z widoku (poprawne — filtr zawęża). Zwraca: id, canon, catalog, frame_count."""
    return con.execute(
        "SELECT o.id, o.canon, o.catalog, COUNT(f.id) AS frame_count "
        "FROM object o "
        "JOIN frame f ON f.object_id = o.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind IN ('light','master_light') "
        "  AND (? IS NULL OR tc.canon_id = ?) "
        "  AND (? IS NULL OR f.camera_id = ?) "
        "  AND (? IS NULL OR f.filter_canon = ?) "
        "GROUP BY o.id "
        "ORDER BY o.canon",
        (telescope_id, telescope_id, camera_id, camera_id, filter_canon, filter_canon),
    ).fetchall()


def object_frames(con, object_id, *, telescope_id=None, camera_id=None, filter_canon=None):
    """Klatki danego obiektu (light/master_light) z tymi samymi filtrami co biblioteka. Location przez
    `MIN(id)` (R#3: frame 1:N location — bez tego N lokalizacji zduplikowałoby klatkę). `present` to
    KOLUMNA statusu, NIE predykat (R#7: frame, którego wszystkie lokalizacje mają present=0, MUSI być
    widoczny — tożsamość = sha1_data, nie obecność; „baza=autorytet"). `telescope_label` +
    `telescop_canon` z kanonicznego teleskopu (canon = fallback etykiety, gdy teleskop nienazwany).
    Zwraca: frame_id, sha1_data, filter_canon, telescope_label, telescop_canon, f_ratio_nominal,
    focal_nominal, camera_model, date_obs, exptime, path, drive_letter, present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, f.filter_canon, "
        "       t.label AS telescope_label, t.telescop_canon, t.f_ratio_nominal, t.focal_nominal, "
        "       cam.model_canon AS camera_model, "
        "       h.date_obs, h.exptime, loc.path, loc.drive_letter, loc.present "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location loc ON loc.id = (SELECT MIN(id) FROM location WHERE frame_id = f.id) "
        "WHERE f.object_id = ? "
        "  AND f.kind IN ('light','master_light') "
        "  AND (? IS NULL OR tc.canon_id = ?) "
        "  AND (? IS NULL OR f.camera_id = ?) "
        "  AND (? IS NULL OR f.filter_canon = ?) "
        "ORDER BY f.id",
        (object_id, telescope_id, telescope_id, camera_id, camera_id, filter_canon, filter_canon),
    ).fetchall()


def review_queue(con):
    """Kolejka przeglądu osi obiektu ze STANU (NIE z `count(event)` — R#2/R#4: `flag_config_review`/
    `object.review_summary` mnożą eventy przy re-skanie, stan jest idempotentny). Trzy kanały:
      - `object_review`: light/master_light z `object_id IS NULL` i obecnym `object_raw` (JOIN header,
        GROUP BY object_raw) — co user zostawił nierozpoznane;
      - `config_review_count`: `config_id IS NULL AND EXISTS(header)` — KONIECZNY `EXISTS(header)`
        (R#2): grouper iteruje `frame JOIN header`, więc klatka bez nagłówka nigdy nie jest flagowana
        i cicho zostaje config NULL; bez tego predykatu licznik zlałby trzy stany;
      - `headerless_count`: frame BEZ wiersza `header` (`NOT EXISTS`) — osobny realny kubełek
        wydobyty spod fałszywego config-review;
      - `unreadable_count`: klatki z ≥1 kopią, która STAŁA SIĘ nieczytelna (`location.unreadable_since
        NOT NULL`, #13) — drążenie do dokładnych kopii daje `unreadable_copies` (Z6/P4).
    Liczniki poza obiekt-review liczy `resolver.review_state` — JEDEN właściciel predykatu stanu
    (#12): ta sama derywacja zasila raport dostawy, więc kolejka i raport nie mogą się rozjechać.
    Zwraca dict: {object_review: [Row(object_raw, n)], config_review_count: int, headerless_count: int,
    unreadable_count: int}."""
    object_review = con.execute(
        "SELECT h.object_raw AS object_raw, COUNT(*) AS n "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "  AND h.object_raw IS NOT NULL "
        "GROUP BY h.object_raw ORDER BY n DESC, object_raw"
    ).fetchall()
    st = review_state(con)
    return {"object_review": object_review, "config_review_count": st.no_config,
            "headerless_count": st.headerless, "unreadable_count": st.unreadable}


def object_review_frames(con, object_raw):
    """Drążenie pojedynczej pozycji obiekt-review: klatki o danym `object_raw`, wciąż nierozwiązane
    (`object_id IS NULL`). JOIN header (object_raw mieszka w header, R#3). Zwraca: frame_id,
    sha1_data, telescope_label, telescop_canon, f_ratio_nominal, focal_nominal, camera_model,
    date_obs, path."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1_data, t.label AS telescope_label, "
        "       t.telescop_canon, t.f_ratio_nominal, t.focal_nominal, "
        "       cam.model_canon AS camera_model, h.date_obs, loc.path "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN location loc ON loc.id = (SELECT MIN(id) FROM location WHERE frame_id = f.id) "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL AND h.object_raw = ? "
        "ORDER BY f.id",
        (object_raw,),
    ).fetchall()


def alias_target(con, alias_norm):
    """Pre-check konfliktu aliasu w dialogu przypisania (#8, P4): `object_id`, na który wskazuje
    `alias_norm`, albo None (alias nieznany — zapis go utworzy). Ostateczny guard i tak siedzi
    w `repo.user_assign_object` (w `_immediate`, TOCTOU) — to czytnik UX, nie bramka."""
    row = con.execute(
        "SELECT object_id FROM object_alias WHERE alias_norm = ?", (alias_norm,)).fetchone()
    return row["object_id"] if row is not None else None


def unreadable_copies(con):
    """Drążenie kubełka `unreadable` (#13, Z6/P4): DOKŁADNE KOPIE (location) z markerem
    `unreadable_since` — nie klatki (klatka z 2 oznaczonymi kopiami = 2 wiersze). `present`
    pokazane per kopia: oznaczona kopia może być `present=0` (znikła po oznaczeniu — forward-guard
    #13) i to MA być widoczne. `sha1_data` = kontekst tożsamości klatki (UI skraca do 12).
    ORDER: najnowsze oznaczenie na górze, potem ścieżka. Zwraca: frame_id, sha1_data, volume,
    path, present, unreadable_since."""
    return con.execute(
        "SELECT l.frame_id, f.sha1_data, l.volume, l.path, l.present, l.unreadable_since "
        "FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE l.unreadable_since IS NOT NULL "
        "ORDER BY l.unreadable_since DESC, l.path"
    ).fetchall()


def telescope_facets(con):
    """Distinct KANONICZNE teleskopy (`merged_into IS NULL`) do kontrolki filtra — żeby filtr pokazywał
    realnie istniejące osie. `telescop_canon` służy za etykietę zastępczą, gdy `label` pusty (teleskop
    jeszcze nienazwany — proposed). Zwraca: id, telescop_canon, label, f_ratio_nominal, focal_nominal."""
    return con.execute(
        "SELECT id, telescop_canon, label, f_ratio_nominal, focal_nominal FROM telescope "
        "WHERE merged_into IS NULL ORDER BY id"
    ).fetchall()


def filter_facets(con):
    """Distinct realnie występujące `filter_canon` do kontrolki filtra. Zwraca: filter_canon."""
    return con.execute(
        "SELECT DISTINCT filter_canon FROM frame WHERE filter_canon IS NOT NULL ORDER BY filter_canon"
    ).fetchall()


# ============================================================ GRID „Klatki" (PLAN_gui_grid §3, read-only)
# Read-model gridu nad EAV `cards`. Silnik filtra (`horreum.filter_engine`) woła `leaf_frame_ids`
# (predykat-liść → zbiór) i `all_frame_ids` (uniwersum); pivot (`horreum.pivot`) dostaje wiersze z
# `cards_pivot`; kolumny bazowe z `base_rows`. Każdy predykat-liść = OSOBNY literał w gałęzi `if`
# (skill ast-write-gate-read-model-sql-literals) — NIGDY f-string. `kind` wybiera literał; wartości `?`.


def all_frame_ids(con):
    """UNIWERSUM filtra = WSZYSTKIE frame (w tym XISF bez cards i zniknięte present=0 — F1). Baza dla
    `not_exists` i `filter=None`. NIGDY z `DISTINCT frame_id FROM cards` (gubiłoby XISF). Zwraca set[int]."""
    return {int(r[0]) for r in con.execute("SELECT id FROM frame").fetchall()}


def leaf_frame_ids(con, kind, keyword, p1=None, p2=None):
    """Predykat-liść filtra → set[frame_id]. `kind` (z `filter_engine`) wybiera OSOBNY literał; keyword i
    wartości wiązane `?`. Numeryczne po `value_num` (wiersze NULL wypadają same); tekstowe po `value_raw`;
    liczbo-podobne trafiają oba; `like` po `value_raw LIKE ? ESCAPE`. Semantyka 1:1 z dawcą `query.py`.
    Liście RELACYJNE `rel_*` (F4, facety — PLAN_ux_redesign §5) chodzą po frame/config/header zamiast
    cards; `keyword` dla nich nieużywany (silnik podaje None). `rel_telescope` = canon_id kanonicznego
    teleskopu (scaleni członkowie rolują się pod kanon przez `telescope_canonical`, jak
    `active_telescopes`). `rel_night` = zakres `[p1, p2)` na `header.date_obs` — OBA parametry pełne
    datetime (granice liczy `filter_engine.night_bounds`); klatka bez header/date_obs nie wpada."""
    if kind == "rel_object":
        cur = con.execute("SELECT id FROM frame WHERE object_id = ?", (p1,))
    elif kind == "rel_filter":
        cur = con.execute("SELECT id FROM frame WHERE filter_canon = ?", (p1,))
    elif kind == "rel_kind":
        cur = con.execute("SELECT id FROM frame WHERE kind = ?", (p1,))
    elif kind == "rel_telescope":
        cur = con.execute(
            "SELECT f.id FROM frame f "
            "JOIN config c ON c.id = f.config_id "
            "JOIN telescope_canonical tc ON tc.id = c.telescope_id "
            "WHERE tc.canon_id = ?",
            (p1,),
        )
    elif kind == "rel_night":
        cur = con.execute(
            "SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id "
            "WHERE h.date_obs >= ? AND h.date_obs < ?",
            (p1, p2),
        )
    elif kind == "exists":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ?", (keyword,))
    elif kind == "num_gt":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num > ?", (keyword, p1))
    elif kind == "num_lt":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num < ?", (keyword, p1))
    elif kind == "num_ge":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num >= ?", (keyword, p1))
    elif kind == "num_le":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_num <= ?", (keyword, p1))
    elif kind == "eq_raw":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_raw = ?", (keyword, p1))
    elif kind == "ne_raw":
        cur = con.execute("SELECT frame_id FROM cards WHERE keyword = ? AND value_raw <> ?", (keyword, p1))
    elif kind == "eq_rawnum":
        cur = con.execute(
            "SELECT frame_id FROM cards WHERE keyword = ? AND (value_raw = ? OR value_num = ?)",
            (keyword, p1, p2),
        )
    elif kind == "ne_rawnum":
        cur = con.execute(
            "SELECT frame_id FROM cards "
            "WHERE keyword = ? AND value_raw <> ? AND (value_num IS NULL OR value_num <> ?)",
            (keyword, p1, p2),
        )
    elif kind == "like":
        cur = con.execute(
            "SELECT frame_id FROM cards WHERE keyword = ? AND value_raw LIKE ? ESCAPE '\\'", (keyword, p1)
        )
    else:
        raise ValueError(f"nieznany kind liścia: {kind!r}")
    return {int(r[0]) for r in cur.fetchall()}


def keyword_facets(con):
    """Distinct keywordy z `cards` + pokrycie (ile klatek ma daną kartę) do panelu Pól. Cards są FITS-only
    (XISF bez cards — D-G). Zwraca wiersze: keyword, n (COUNT DISTINCT frame_id), malejąco po pokryciu.
    UWAGA nazewnicza: „facets" tu = pokrycie KEYWORDÓW (kolumny gridu); listwa facetów F4 (Obiekt/Filtr/
    Rodzaj/Teleskop/Noc) to funkcje `facet_*` niżej — INNY fakt (F4R#9)."""
    return con.execute(
        "SELECT keyword, COUNT(DISTINCT frame_id) AS n FROM cards GROUP BY keyword ORDER BY n DESC, keyword"
    ).fetchall()


# ============================================================ LISTWA FACETÓW (F4, PLAN_ux_redesign §5)
# Liczniki wymiarów dla FacetRail: liczność wartości w podanym zbiorze frame_ids (SIBLING-SET —
# FramesView liczy zbiór per facet BEZ własnej grupy, F4R#1). Wszystko STAŁE LITERAŁY + `json_each(?)`.
# JAWNE predykaty NULL (F4R#10): żaden literał nie może urodzić fantomowego kubełka NULL (kubełki NULL
# świadomie poza v1 — kalibracja bez obiektu POPRAWNA, kind-aware).


def facet_objects(con, frame_ids):
    """Kubełki facetu Obiekt: kanoniczne obiekty w zbiorze + liczność. `object_id IS NULL` wypada
    JOIN-em (kalibracja bez obiektu — poprawnie poza listą). ORDER canon (lista pod szukajkę).
    Zwraca: id, canon, n."""
    return con.execute(
        "SELECT o.id, o.canon, COUNT(*) AS n "
        "FROM frame f JOIN object o ON o.id = f.object_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY o.id ORDER BY o.canon",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_filters(con, frame_ids):
    """Kubełki facetu Filtr: `filter_canon` w zbiorze + liczność; JAWNIE `IS NOT NULL` (F4R#10).
    Zwraca: filter_canon, n (n DESC — najczęstsze na górze)."""
    return con.execute(
        "SELECT filter_canon, COUNT(*) AS n FROM frame "
        "WHERE filter_canon IS NOT NULL "
        "  AND id IN (SELECT value FROM json_each(?)) "
        "GROUP BY filter_canon ORDER BY n DESC, filter_canon",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_kinds(con, frame_ids):
    """Kubełki facetu Rodzaj: `kind` w zbiorze + liczność (`kind` NOT NULL w schemacie — bez predykatu).
    Zwraca: kind, n (n DESC)."""
    return con.execute(
        "SELECT kind, COUNT(*) AS n FROM frame "
        "WHERE id IN (SELECT value FROM json_each(?)) "
        "GROUP BY kind ORDER BY n DESC, kind",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_telescopes(con, frame_ids):
    """Kubełki facetu Teleskop: KANONICZNE teleskopy w zbiorze + liczność; klatki scalonych członków
    rolują się pod kanon (`telescope_canonical`, jak `active_telescopes`); frame bez configu wypada
    JOIN-em. Etykietę składa wołający (label→telescop_canon fallback, wzorzec `_tel_label`).
    Zwraca: id (canon_id), label, telescop_canon, n (n DESC)."""
    return con.execute(
        "SELECT t.id, t.label, t.telescop_canon, COUNT(*) AS n "
        "FROM frame f "
        "JOIN config c ON c.id = f.config_id "
        "JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "JOIN telescope t ON t.id = tc.canon_id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY t.id ORDER BY n DESC, t.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def facet_nights(con, frame_ids):
    """Kubełki facetu Noc: noc = `date(date_obs, '-12 hours')` (D-UX-1) + liczność; JAWNIE
    `date_obs IS NOT NULL` (F4R#10). INWARIANT (F4R#6): `date_obs` = NAIWNE ISO z `T`, bez sufiksu
    strefy — sufiks `Z`/`+HH:MM` rozjechałby tę derywację (konwersja UTC) z liściem `rel_night`
    (porównanie leksykalne); spójność kubełek↔liść pinuje test własności. Zwraca: night, n
    (night DESC — najnowsze na górze)."""
    return con.execute(
        "SELECT date(h.date_obs, '-12 hours') AS night, COUNT(*) AS n "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE h.date_obs IS NOT NULL "
        "  AND f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY night ORDER BY night DESC",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def vanished_frame_ids(con):
    """Zbiór frame_id ZNIKNIĘTYCH: klatka MA lokacje, ale ŻADNEJ obecnej (perspektywa „Zniknięte",
    P5/#7). Guard `EXISTS` odróżnia „zniknęła" od „nigdy nie miała lokalizacji" (frame osierocony
    przez `rebind_location` — inny stan, inna robota). JEDEN właściciel predykatu: liczy z niego
    zarówno licznik Porządków (`tasks_state`), jak i trim gridu — jak `dup_frame_ids`. Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f "
        "WHERE EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id) "
        "  AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1)"
    ).fetchall()}


def dup_frame_ids(con):
    """Zbiór frame_id z >1 OBECNĄ lokacją (perspektywa „Duplikaty"). JEDNA derywacja trimu dla zbioru
    głównego i sibling-setów facetów (SPOT — trim w Pythonie na `n_present` i ten literał muszą znaczyć
    to samo; por. `base_rows` n_present). Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT frame_id FROM location WHERE present = 1 GROUP BY frame_id HAVING COUNT(*) > 1"
    ).fetchall()}


def review_frame_ids(con):
    """Zbiór frame_id perspektywy „Do przeglądu": light/master_light z `object_id IS NULL`
    (równoważne trimowi `object_canon is None` — `object.canon` NOT NULL, LEFT JOIN daje NULL
    wyłącznie przy braku obiektu). Zwraca set[int]."""
    return {int(r[0]) for r in con.execute(
        "SELECT id FROM frame WHERE object_id IS NULL AND kind IN ('light','master_light')"
    ).fetchall()}


# ============================================================ PORTFEL NAŚWIETLEŃ (F7, PLAN_ux_redesign §8)
# „Ile mam godzin na obiekt, per filtr?". STAŁY literał + `json_each(?)`. Godziny z `header.exptime`
# przez `frame JOIN header` — NIE z cards (cards FITS-only, `rec.cards=None` dla XISF → zaniżenie o XISF,
# R#8). KIND-AWARE `kind='light'` (EXPTIME masterlighta = czas ZINTEGROWANY → wliczony podwoiłby godziny).
# header 1:1 z frame (PK frame_id) → frame w >1 present location = JEDEN wiersz, `SUM` bez inflacji.


def object_exposure(con, frame_ids):
    """Naświetlenie per (obiekt, filtr) w zbiorze: `SUM(exptime)` sekund + liczba lightów BEZ exptime.
    JAWNE-NULL: `exptime IS NULL` u lighta → `n_null` (nie ciche pominięcie); `filter_canon IS NULL`
    → własna grupa (kubełek „(bez filtra)"). Grupa cała bez exptime → `secs=NULL` (agregat = 0 s).
    `object_id IS NOT NULL` (kalibracja/bez-obiektu poza facetem Obiekt); XISF/light bez header wypada
    JOIN-em. Godziny — jak licznik facetu — obejmują klatki `present=0` (parytet z `facet_objects`).
    Zwraca wiersze: object_id, filter_canon, secs, n_null."""
    return con.execute(
        "SELECT f.object_id, f.filter_canon, "
        "       SUM(h.exptime)         AS secs, "
        "       SUM(h.exptime IS NULL) AS n_null "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NOT NULL "
        "  AND f.id IN (SELECT value FROM json_each(?)) "
        "GROUP BY f.object_id, f.filter_canon "
        "ORDER BY f.object_id, secs DESC",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


# ============================================================ PORZĄDKI (F5, PLAN_ux_redesign §6)
# Liczniki listy zadań `TasksView` — bieżący STAN tabel, nigdy `count(event)` (REVIEW-ZE-STANU,
# memory horreum-review-queue-from-state). Zbiory dups/review REUŻYWANE z derywacji perspektyw
# (SPOT — osobny literał COUNT byłby drugim właścicielem predykatu).


def tasks_state(con):
    """Liczniki Porządków ze STANU. `unresolved_lights`/`dup_frames` = len() zbiorów perspektyw
    „Do przeglądu"/„Duplikaty" (JEDNA derywacja z gridem). `telescopes_unlabeled`/
    `observatories_unnamed`: NULL = nienazwane (`label_telescope`/`label_observatory` odrzucają pusty
    string, więc pustych stringów w bazie nie ma); tylko kanoniczne (`merged_into IS NULL`).
    `xisf_frames` — informacyjny (writeback nagłówków pomija XISF, D-W2). `vanished_frames` = len()
    zbioru perspektywy „Zniknięte" (P5 — ta sama derywacja co grid; przed passem obecności był to
    osobny literał COUNT, czyli drugi właściciel predykatu). Zwraca dict sześciu liczników."""
    telescopes_unlabeled = con.execute(
        "SELECT COUNT(*) FROM telescope WHERE label IS NULL AND merged_into IS NULL"
    ).fetchone()[0]
    observatories_unnamed = con.execute(
        "SELECT COUNT(*) FROM observatory WHERE name IS NULL AND merged_into IS NULL"
    ).fetchone()[0]
    xisf_frames = con.execute(
        "SELECT COUNT(*) FROM frame WHERE filetype = 'xisf'"
    ).fetchone()[0]
    return {
        "unresolved_lights": len(review_frame_ids(con)),
        "dup_frames": len(dup_frame_ids(con)),
        "telescopes_unlabeled": telescopes_unlabeled,
        "observatories_unnamed": observatories_unnamed,
        "xisf_frames": xisf_frames,
        "vanished_frames": len(vanished_frame_ids(con)),
    }


def has_real_volume_locations(con):
    """Czy baza zna JAKĄKOLWIEK lokację z realnym serialem (`volume != '?'`)? Guard mieszania
    serialu (F5R#3): skan z serialem `'?'` do takiej bazy PODWOIŁBY lokacje znanych klatek (brama
    `(volume,path,mtime)` nie trafi, `UNIQUE(volume,path)` wpuści drugą). `location.volume` jest
    NOT NULL — porównanie bez pułapki trójwartościowej. Zwraca bool."""
    return con.execute(
        "SELECT 1 FROM location WHERE volume != '?' LIMIT 1"
    ).fetchone() is not None


def cards_pivot(con, frame_ids, keywords):
    """Wiersze cards dla pivota: literał `json_each` — listy id/keywordów jako TABLICE JSON (jeden param
    każda), bez dynamicznych `?` ani chunkowania (F4: plan po indeksie PK, ~53 ms/4000 klatek). ORDER BY
    frame_id,keyword,idx (pivot bierze pierwszy idx). Zwraca: frame_id, keyword, idx, value_raw, value_num."""
    return con.execute(
        "SELECT frame_id, keyword, idx, value_raw, value_num FROM cards "
        "WHERE keyword IN (SELECT value FROM json_each(?)) "
        "  AND frame_id IN (SELECT value FROM json_each(?)) "
        "ORDER BY frame_id, keyword, idx",
        (json.dumps(list(keywords)), json.dumps(list(frame_ids))),
    ).fetchall()


# ============================================================ WRITEBACK / makro (krok 4, read-model)
# Read-model stagingu writebacku. Wszystko STAŁE LITERAŁY SELECT + `?` (bramka §7.1). Makro
# (`horreum.macro`) woła te czytniki, sam nie dotyka DB; zapis idzie przez `repo`. Cel writebacku =
# LOCATION (fizyczny plik), więc topologia present-location jest tu, nie na frame.


def writeback_frame_targets(con, frame_ids):
    """Dla zbioru frame_id: filetype (frame) + KAŻDA OBECNA (`present=1`) location z faktami kopii
    potrzebnymi do zapisu (header_hash/hdu_index/compressed). Frame BEZ obecnej kopii → wiersz z
    location_id NULL (makro odróżni „brak kopii" od wielu kopii licząc wiersze per frame). frame_ids
    jako TABLICA JSON (`json_each`, jeden param). Wybór celu (D-W1: dokładnie 1 present; D-W2: nie XISF)
    robi makro, nie ten czytnik. ORDER BY frame_id, location_id. Zwraca: frame_id, filetype,
    location_id, path, header_hash, hdu_index, compressed."""
    return con.execute(
        "SELECT f.id AS frame_id, f.filetype, "
        "       l.id AS location_id, l.path, l.header_hash, l.hdu_index, l.compressed "
        "FROM frame f "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def rename_frame_targets(con, frame_ids):
    """Dla zbioru frame_id: fakty do `compose_name` (kind/filter_canon/object_canon/object_raw/
    sha1_data/date_obs/exptime — frame+header) + KAŻDA OBECNA (`present=1`) location z `path`+`mtime`
    (kotwica anty-stale renamu). Frame BEZ obecnej kopii → wiersz z location_id NULL (silnik odróżni
    „brak kopii" od wielu, licząc wiersze per frame). Rename DOZWOLONY dla XISF (nie tyka nagłówka),
    więc BEZ `header_hash`/`compressed` (nieistotne). frame_ids jako TABLICA JSON (`json_each`, jeden
    param — §4). ORDER BY frame_id, location_id. Zwraca: frame_id, filetype, kind, filter_canon,
    sha1_data, object_canon, object_raw, date_obs, exptime, location_id, path, mtime."""
    return con.execute(
        "SELECT f.id AS frame_id, f.filetype, f.kind, f.filter_canon, f.sha1_data, "
        "       obj.canon AS object_canon, h.object_raw, h.date_obs, h.exptime, "
        "       l.id AS location_id, l.path, l.mtime "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN object obj ON obj.id = f.object_id "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def frame_for_location(con, location_id):
    """frame_id stojący pod daną LOCATION — mapowanie podglądu makra (touched niesie location_id,
    grid kluczuje frame). Zwraca int albo None."""
    row = con.execute("SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
    return row["frame_id"] if row else None


def frame_cards(con, frame_id):
    """Wszystkie karty jednego frame'a (lustro EAV) do budowy `env` makra i reguł set/add. Sort po
    (keyword, idx) — makro bierze pierwsze wystąpienie jako env, liczy kardynalność. Zwraca:
    keyword, idx, value_raw, value_num, value_type, comment."""
    return con.execute(
        "SELECT keyword, idx, value_raw, value_num, value_type, comment "
        "FROM cards WHERE frame_id = ? ORDER BY keyword, idx",
        (frame_id,),
    ).fetchall()


def location_cards(con, location_id):
    """Karty frame'a stojącego pod daną LOCATION (dla ręcznej edycji komórki gridu — grid=frame,
    ale cel edycji = fizyczny plik = location). Zwraca jak `frame_cards`."""
    return con.execute(
        "SELECT c.keyword, c.idx, c.value_raw, c.value_num, c.value_type, c.comment "
        "FROM cards c JOIN location l ON l.frame_id = c.frame_id "
        "WHERE l.id = ? ORDER BY c.keyword, c.idx",
        (location_id,),
    ).fetchall()


def present_locations(con, frame_ids):
    """ŹRÓDŁO linku PROJEKCJI (krok 6) — dla zbioru frame_id KAŻDA OBECNA (`present=1`) location z
    `path`+`volume`+`drive_letter`+`size_bytes`. Rozszerza wzorzec `writeback_frame_targets` (już
    `present=1`) o `volume`/`drive_letter` (R#1: `base_rows` daje `MIN(id)` BEZ `present`/`volume` →
    ścieżka bywa `present=0` → `os.link` na nieistniejące źródło; brak `volume` → EXDEV nierozstrzygalny
    z góry → NIE nadaje się na cel linku) oraz o `size_bytes` (F2 redesignu: suma rozmiaru kopii po TEJ
    SAMEJ lokacji, którą wybiera plan — R#5). Frame BEZ obecnej kopii → wiersz z location_id NULL (silnik
    projekcji: `skipped`-kwarantanna). Wiele obecnych → wiele wierszy; silnik bierze pierwszą (D-P5).
    `base_rows` zostaje TYLKO do segmentów layoutu (object/filter/telescope). frame_ids jako TABLICA
    JSON (`json_each`, jeden param — §4). ORDER BY frame_id, location_id. Zwraca: frame_id,
    location_id, path, volume, drive_letter, size_bytes."""
    return con.execute(
        "SELECT f.id AS frame_id, l.id AS location_id, l.path, l.volume, l.drive_letter, l.size_bytes "
        "FROM frame f "
        "LEFT JOIN location l ON l.frame_id = f.id AND l.present = 1 "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id, l.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()


def db_path_of(con):
    """Ścieżka pliku bazy z żywego połączenia (`PRAGMA database_list` → 'main'). Worker off-thread
    (writeback gridu, auto-DRY projekcji) otwiera po niej WŁASNE połączenie w swoim wątku — `con` nie
    przechodzi między wątkami (check_same_thread). `:memory:` → '' → seam wymusza tryb inline."""
    for _seq, name, file in con.execute("PRAGMA database_list"):
        if name == "main":
            return file
    return None


def base_rows(con, frame_ids):
    """Kolumny BAZOWE gridu (warstwa interpretacji NAD lustrem cards) dla zbioru frame_id. Location przez
    `MIN(id)` BEZ odsiewania po `present` — `present` to KOLUMNA, nie predykat (F3: klatka zniknięta MUSI
    zostać w gridzie; baza=autorytet). `n_present` = liczba obecnych lokalizacji (perspektywa „Duplikaty"
    = n_present > 1). Teleskop przez config→telescope_canonical→kanon (jak `object_frames`). frame_ids jako
    tablica JSON (`json_each`). Zwraca: frame_id, kind, filetype, filter_canon, camera_model,
    telescope_label, telescop_canon, object_canon, object_raw, date_obs, exptime, path, present, n_present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.kind, f.filetype, f.filter_canon, "
        "       cam.model_canon AS camera_model, "
        "       t.label AS telescope_label, t.telescop_canon, "
        "       obj.canon AS object_canon, h.object_raw, "
        "       h.date_obs, h.exptime, loc.path, loc.present, "
        "       (SELECT COUNT(*) FROM location lp WHERE lp.frame_id = f.id AND lp.present = 1) AS n_present "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN telescope t ON t.id = tc.canon_id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "LEFT JOIN object obj ON obj.id = f.object_id "
        "LEFT JOIN location loc ON loc.id = (SELECT MIN(id) FROM location WHERE frame_id = f.id) "
        "WHERE f.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY f.id",
        (json.dumps(list(frame_ids)),),
    ).fetchall()
