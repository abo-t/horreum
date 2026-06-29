"""Read-model osi TELESKOP (PLAN_gui §5 — read path). Czyste funkcje `con → list[Row]`,
testowalne BEZ Qt. ODCZYT nie jest „jedną klingą" (klinga dotyczy ZAPISU emitującego event) —
SELECT wolno wszędzie; zapis usera idzie WYŁĄCZNIE przez `horreum.repo`.

TWARDE OGRANICZENIE (PLAN_gui §4, rec. nr 6): wyłącznie **SQL-LITERAŁY + parametry `?`** oraz
wyłącznie **`con.execute`** (bez pandas/ORM/`read_sql` — ścieżki niewidziane przez meta-test AST,
`EXEC_METHODS=execute*`). Dynamiczny SQL (f-string) w tym pliku WYSADZIŁBY bramkę §7.1, mimo że to
czysty odczyt: `_first_sql_verb` zwraca `None` dla nie-literału, a `None` poza `repo.py`/`db.py`
= offender. Warianty/filtry => parametry `?` w stałym literale albo OSOBNE literały w gałęziach `if`,
NIGDY składanie stringa SQL.
"""


def active_telescopes(con):
    """Aktywne (KANONICZNE) teleskopy z licznością klatek — lista główna GUI.

    Filtr kanoniczności JAWNY (`WHERE t.merged_into IS NULL`, rec.R2 nr 2): widok
    `telescope_canonical` zwraca WSZYSTKIE wiersze (kanon + scalone z ich `canon_id`), więc sam join
    przez widok nie odsiewa scalonych — bez tego WHERE scalony `approved` wyciekłby jako osobny wiersz
    (§3b). Licznik agreguje po `canon_id` ścieżką `telescope_canonical → config → frame` (rec. nr 7):
    klatki scalonych członków rolują się pod kanon, kolizja kamery (dwa configi tej samej kamery)
    sumuje się pod jednym kanonem. `LEFT JOIN` => teleskop bez klatek ma `frame_count=0` (nie znika).
    Frame z `config_id IS NULL` (review) NIE dołącza się do żadnego configu => poza sumą (poprawne —
    jest w delcie, nie na osi). Zwraca wiersze: id, label, status, f_ratio_nominal, focal_nominal,
    frame_count."""
    return con.execute(
        "SELECT t.id, t.label, t.status, t.f_ratio_nominal, t.focal_nominal, "
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
    id, label, status, f_ratio_nominal, focal_nominal (puste, gdy `canon_id` nic nie scala)."""
    return con.execute(
        "SELECT id, label, status, f_ratio_nominal, focal_nominal "
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


# ============================================================ oś OBIEKT (PLAN_gui_object §3, read-only)
# Read-model biblioteki + kolejki przeglądu. KIND-AWARE: obiekt liczony TYLKO na light/master_light
# (kalibracja nie ma obiektu z definicji — memory horreum-object-resolution-kind-aware). Filtr teleskopu
# ZAWSZE przez `telescope_canonical` (rolowanie scalonych pod kanon). Filtry opcjonalne realizowane
# wzorcem `(? IS NULL OR kol = ?)` w JEDNYM stałym literale (R#5) — NIE rozgałęzieniem 8 SELECT-ów:
# literał stały (bramka AST §7.1 widzi `SELECT`), wartość wiązana DWUKROTNIE per filtr.


def library_objects(con, *, telescope_id=None, camera_id=None, filter_canon=None):
    """Biblioteka: kanoniczne obiekty z licznością klatek (light/master_light), z OPCJONALNYMI filtrami
    osi. PREDYKAT = `frame.kind` (R#1: `object.kind` to inne pole, zawsze `deep_sky` — NIE zwracane).
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
    widoczny — tożsamość = sha1, nie obecność; „baza=autorytet"). `telescope_label` + `f_ratio_nominal`/
    `focal_nominal` z kanonicznego teleskopu (sygnatura = fallback etykiety, gdy teleskop nienazwany —
    wizytator P1 #1). Zwraca: frame_id, sha1, filter_canon, telescope_label, f_ratio_nominal,
    focal_nominal, camera_model, date_obs, exptime, path, drive_letter, present."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1, f.filter_canon, "
        "       t.label AS telescope_label, t.f_ratio_nominal, t.focal_nominal, "
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
        wydobyty spod fałszywego config-review.
    Zwraca dict: {object_review: [Row(object_raw, n)], config_review_count: int, headerless_count: int}."""
    object_review = con.execute(
        "SELECT h.object_raw AS object_raw, COUNT(*) AS n "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind IN ('light','master_light') AND f.object_id IS NULL "
        "  AND h.object_raw IS NOT NULL "
        "GROUP BY h.object_raw ORDER BY n DESC, object_raw"
    ).fetchall()
    config_review_count = con.execute(
        "SELECT COUNT(*) FROM frame f "
        "WHERE f.config_id IS NULL AND EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)"
    ).fetchone()[0]
    headerless_count = con.execute(
        "SELECT COUNT(*) FROM frame f "
        "WHERE NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)"
    ).fetchone()[0]
    return {"object_review": object_review, "config_review_count": config_review_count,
            "headerless_count": headerless_count}


def object_review_frames(con, object_raw):
    """Drążenie pojedynczej pozycji obiekt-review: klatki o danym `object_raw`, wciąż nierozwiązane
    (`object_id IS NULL`). JOIN header (object_raw mieszka w header, R#3). Zwraca: frame_id, sha1,
    telescope_label, f_ratio_nominal, focal_nominal, camera_model, date_obs, path."""
    return con.execute(
        "SELECT f.id AS frame_id, f.sha1, t.label AS telescope_label, "
        "       t.f_ratio_nominal, t.focal_nominal, "
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


def telescope_facets(con):
    """Distinct KANONICZNE teleskopy (`merged_into IS NULL`) do kontrolki filtra — żeby filtr pokazywał
    realnie istniejące osie. `f_ratio_nominal`/`focal_nominal` służą za etykietę zastępczą, gdy `label`
    pusty (teleskop jeszcze nienazwany — proposed). Zwraca: id, label, f_ratio_nominal, focal_nominal."""
    return con.execute(
        "SELECT id, label, f_ratio_nominal, focal_nominal FROM telescope "
        "WHERE merged_into IS NULL ORDER BY id"
    ).fetchall()


def filter_facets(con):
    """Distinct realnie występujące `filter_canon` do kontrolki filtra. Zwraca: filter_canon."""
    return con.execute(
        "SELECT DISTINCT filter_canon FROM frame WHERE filter_canon IS NOT NULL ORDER BY filter_canon"
    ).fetchall()
