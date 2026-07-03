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
    liczbo-podobne trafiają oba; `like` po `value_raw LIKE ? ESCAPE`. Semantyka 1:1 z dawcą `query.py`."""
    if kind == "exists":
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
    (XISF bez cards — D-G). Zwraca wiersze: keyword, n (COUNT DISTINCT frame_id), malejąco po pokryciu."""
    return con.execute(
        "SELECT keyword, COUNT(DISTINCT frame_id) AS n FROM cards GROUP BY keyword ORDER BY n DESC, keyword"
    ).fetchall()


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
