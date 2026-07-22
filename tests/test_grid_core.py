"""Grid „Klatki" (PLAN_gui_grid) — rdzeń Qt-wolny: silnik filtra (algebra zbiorów), pivot, read-model.

Mała REALNA baza (frame + cards + location + header) — testuje SQL literały (json_each, joiny) ORAZ
semantykę operatorów 1:1 z dawcą. Must-fixy recenzji pokryte: F1 (uniwersum = wszystkie frame, XISF bez
cards w `not_exists`/`OR`), F3 (`present` kolumna, klatka zniknięta widoczna), F6 (pusta grupa = wszystko).
Wstawianie wierszy surowym SQL dozwolone w `tests/` (meta-test AST skanuje tylko pakiet `horreum`)."""
import pytest

from horreum import db, filter_engine, pivot
from horreum.gui import facet_model, portfolio, queries

NOW = "2026-07-03T12:00:00"


@pytest.fixture
def grid_db(tmp_path):
    """Baza gridu: 4 frame'y. f1,f2,f4 = FITS z cards; f3 = XISF BEZ cards (F1). f1 ma 2 obecne
    lokalizacje (Duplikaty); f4 ma lokalizację znikniętą (present=0, F3). Cards:
      f1: OBJECT=M51, EXPTIME=300, GAIN=100   f2: OBJECT=NGC891, EXPTIME=60, GAIN=100
      f4: OBJECT=M51, EXPTIME=120 (BEZ GAIN)  f3: — (XISF, 0 cards)."""
    con = db.open_db(str(tmp_path / "grid.db"))
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
        [(1, "d1", "light", "fits", NOW), (2, "d2", "light", "fits", NOW),
         (3, "d3", "master_flat", "xisf", NOW), (4, "d4", "light", "fits", NOW)],
    )
    cards = [
        (1, "OBJECT", 0, "M51", None, "str"), (1, "EXPTIME", 0, "300", 300.0, "float"),
        (1, "GAIN", 0, "100", 100.0, "int"),
        (2, "OBJECT", 0, "NGC891", None, "str"), (2, "EXPTIME", 0, "60", 60.0, "float"),
        (2, "GAIN", 0, "100", 100.0, "int"),
        (4, "OBJECT", 0, "M51", None, "str"), (4, "EXPTIME", 0, "120", 120.0, "float"),
        # duplikat idx dla HISTORY — pivot bierze pierwszy (idx=0)
        (1, "HISTORY", 0, "first", None, "str"), (1, "HISTORY", 1, "second", None, "str"),
    ]
    con.executemany(
        "INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) VALUES (?,?,?,?,?,?)",
        cards,
    )
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(1, "V", "/a/f1.fits", 1), (1, "V", "/b/f1_copy.fits", 1),   # f1: 2 obecne → Duplikaty
         (2, "V", "/a/f2.fits", 1),
         (3, "V", "/a/f3.xisf", 1),
         (4, "V", "/a/f4.fits", 0)],                                   # f4: zniknięta (present=0)
    )
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, object_raw, exptime) VALUES (?,?,?,?)",
        [(1, "{}", "M51", 300.0), (2, "{}", "NGC891", 60.0), (4, "{}", "M51", 120.0)],
    )
    con.commit()
    yield con
    con.close()


def _run(con, tree):
    return filter_engine.run(
        tree,
        leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(con, k, kw, p1, p2),
        universe_fn=lambda: queries.all_frame_ids(con),
    )


# ---------- uniwersum / F1 ----------

def test_universe_zawiera_xisf_i_zniknięte(grid_db):
    """Uniwersum = WSZYSTKIE frame, w tym XISF bez cards (f3) i zniknięte (f4). NIE z cards (F1)."""
    assert queries.all_frame_ids(grid_db) == {1, 2, 3, 4}


def test_filter_none_to_uniwersum(grid_db):
    assert _run(grid_db, None) == {1, 2, 3, 4}


def test_not_exists_łapie_xisf_bez_cards(grid_db):
    """not_exists GAIN → f3 (XISF, 0 cards) i f4 (brak GAIN). F1: bez uniwersum z `frame` gubiłoby f3."""
    assert _run(grid_db, {"keyword": "GAIN", "operator": "not_exists"}) == {3, 4}


def test_or_z_not_exists_nie_gubi_xisf(grid_db):
    """OR(OBJECT=NGC891, not_exists GAIN) → {2,3,4}. XISF f3 wchodzi przez not_exists (F1)."""
    tree = {"op": "OR", "conditions": [
        {"keyword": "OBJECT", "operator": "eq", "value": "NGC891"},
        {"keyword": "GAIN", "operator": "not_exists"},
    ]}
    assert _run(grid_db, tree) == {2, 3, 4}


# ---------- operatory (parytet dawcy) ----------

def test_exists(grid_db):
    assert _run(grid_db, {"keyword": "GAIN", "operator": "exists"}) == {1, 2}


def test_eq_tekst(grid_db):
    assert _run(grid_db, {"keyword": "OBJECT", "operator": "eq", "value": "M51"}) == {1, 4}


def test_ne_wymaga_karty(grid_db):
    """ne OBJECT=M51 → {2} (klatka z kartą OBJECT≠M51). f3 (bez OBJECT) NIE wchodzi — parytet, F7."""
    assert _run(grid_db, {"keyword": "OBJECT", "operator": "ne", "value": "M51"}) == {2}


def test_eq_liczbopodobny_trafia_raw_i_num(grid_db):
    """GAIN eq 100 (liczbo-podobny) → value_raw='100' OR value_num=100 → {1,2}."""
    assert _run(grid_db, {"keyword": "GAIN", "operator": "eq", "value": 100}) == {1, 2}


def test_num_ge(grid_db):
    assert _run(grid_db, {"keyword": "EXPTIME", "operator": "ge", "value": 120}) == {1, 4}


def test_num_gt(grid_db):
    assert _run(grid_db, {"keyword": "EXPTIME", "operator": "gt", "value": 120}) == {1}


def test_contains(grid_db):
    assert _run(grid_db, {"keyword": "OBJECT", "operator": "contains", "value": "GC"}) == {2}


def test_and(grid_db):
    tree = {"op": "AND", "conditions": [
        {"keyword": "OBJECT", "operator": "eq", "value": "M51"},
        {"keyword": "EXPTIME", "operator": "gt", "value": 200},
    ]}
    assert _run(grid_db, tree) == {1}


def test_pusta_grupa_to_wszystko(grid_db):
    """Pusta grupa → uniwersum (parytet dawcy build_where→'1', F6)."""
    assert _run(grid_db, {"op": "AND", "conditions": []}) == {1, 2, 3, 4}


# ---------- NOT (F1 redesignu — PLAN_ux_redesign §2) ----------

def test_not_lisc(grid_db):
    """NOT(liść) = uniwersum − liść. Zawiera XISF f3 (bez cards) i znikniętą f4 — uniwersum z frame."""
    tree = {"op": "NOT", "conditions": [{"keyword": "OBJECT", "operator": "eq", "value": "M51"}]}
    assert _run(grid_db, tree) == {2, 3}  # uniwersum {1,2,3,4} − {1,4}


def test_not_nad_grupa_or(grid_db):
    """NOT nad grupą OR — negacja całego podwyrażenia."""
    tree = {"op": "NOT", "conditions": [{"op": "OR", "conditions": [
        {"keyword": "OBJECT", "operator": "eq", "value": "M51"},
        {"keyword": "OBJECT", "operator": "eq", "value": "NGC891"},
    ]}]}
    assert _run(grid_db, tree) == {3}     # tylko XISF bez OBJECT


def test_not_not_to_identycznosc(grid_db):
    """NOT(NOT(x)) == x — podwójna negacja wraca do wyniku x (algebra, nie przypadek)."""
    x = {"keyword": "GAIN", "operator": "exists"}
    tree = {"op": "NOT", "conditions": [{"op": "NOT", "conditions": [x]}]}
    assert _run(grid_db, tree) == _run(grid_db, x) == {1, 2}


def test_not_pustej_grupy_to_zbior_pusty(grid_db):
    """NOT(pusta-grupa) = ∅: pusta grupa to uniwersum, różnica daje zbiór pusty (semantyka brzegowa R#2)."""
    tree = {"op": "NOT", "conditions": [{"op": "AND", "conditions": []}]}
    assert _run(grid_db, tree) == set()


def test_not_zla_licznosc_dzieci(grid_db):
    """NOT z 0 lub 2 dziećmi → ValueError (EXPECT)."""
    with pytest.raises(ValueError, match="NOT"):
        _run(grid_db, {"op": "NOT", "conditions": []})
    with pytest.raises(ValueError, match="NOT"):
        _run(grid_db, {"op": "NOT", "conditions": [
            {"keyword": "GAIN", "operator": "exists"},
            {"keyword": "OBJECT", "operator": "exists"},
        ]})


def test_regex_odrzucony(grid_db):
    with pytest.raises(ValueError, match="regex"):
        _run(grid_db, {"keyword": "OBJECT", "operator": "regex", "value": ".*"})


def test_zły_keyword_odrzucony(grid_db):
    with pytest.raises(ValueError, match="keyword"):
        _run(grid_db, {"keyword": "BAD KW;", "operator": "exists"})


# ---------- pivot (3 stany + pierwszy idx) ----------

def test_pivot_trzy_stany(grid_db):
    rows = queries.cards_pivot(grid_db, [1, 2, 3], ["OBJECT", "GAIN"])
    pv = pivot.build_pivot([1, 2, 3], ["OBJECT", "GAIN"], rows)
    by_id = {r.frame_id: r.cells for r in pv.rows}
    assert by_id[1]["OBJECT"] == pivot.PivotCell("M51", None)
    assert by_id[1]["GAIN"] == pivot.PivotCell("100", 100.0)
    # f3 XISF: obie kolumny MISSING (0 cards)
    assert by_id[3]["OBJECT"] is pivot.MISSING
    assert by_id[3]["GAIN"] is pivot.MISSING


def test_pivot_pierwszy_idx(grid_db):
    rows = queries.cards_pivot(grid_db, [1], ["HISTORY"])
    pv = pivot.build_pivot([1], ["HISTORY"], rows)
    assert pv.rows[0].cells["HISTORY"] == pivot.PivotCell("first", None)  # idx=0, nie 'second'


def test_pivot_zły_keyword_kolumny(grid_db):
    with pytest.raises(ValueError, match="keyword kolumny"):
        pivot.build_pivot([1], ["BAD KW"], [])


# ---------- base_rows (F3: present kolumna, Duplikaty) ----------

def test_base_rows_zawiera_zniknięte(grid_db):
    """F3: f4 (wszystkie location present=0) MUSI być w wyniku; present to kolumna statusu."""
    rows = {r["frame_id"]: r for r in queries.base_rows(grid_db, [1, 2, 3, 4])}
    assert set(rows) == {1, 2, 3, 4}
    assert rows[4]["present"] == 0
    assert rows[4]["n_present"] == 0


def test_base_rows_duplikaty(grid_db):
    """f1 ma 2 obecne lokalizacje → n_present=2 (perspektywa Duplikaty). f2 = 1."""
    rows = {r["frame_id"]: r for r in queries.base_rows(grid_db, [1, 2])}
    assert rows[1]["n_present"] == 2
    assert rows[2]["n_present"] == 1
    assert rows[1]["path"]  # MIN(id) location, niezależnie od present


def test_base_rows_xisf_kolumny(grid_db):
    rows = {r["frame_id"]: r for r in queries.base_rows(grid_db, [3])}
    assert rows[3]["kind"] == "master_flat"
    assert rows[3]["filetype"] == "xisf"


# ---------- describe — kryteria zbioru SŁOWAMI (F3, PLAN_ux_redesign §4) ----------

def test_describe_none_i_pusta_grupa():
    assert filter_engine.describe(None) == "wszystkie klatki"
    assert filter_engine.describe({"op": "AND", "conditions": []}) == "wszystkie klatki"


def test_describe_lisc_kazdego_opa():
    d = filter_engine.describe
    assert d({"keyword": "EXPTIME", "operator": "eq", "value": 300}) == "EXPTIME = 300"
    assert d({"keyword": "GAIN", "operator": "ne", "value": 100}) == "GAIN ≠ 100"
    assert d({"keyword": "EXPTIME", "operator": "gt", "value": 60}) == "EXPTIME > 60"
    assert d({"keyword": "EXPTIME", "operator": "lt", "value": 60}) == "EXPTIME < 60"
    assert d({"keyword": "EXPTIME", "operator": "ge", "value": 60}) == "EXPTIME ≥ 60"
    assert d({"keyword": "EXPTIME", "operator": "le", "value": 60}) == "EXPTIME ≤ 60"
    assert d({"keyword": "OBJECT", "operator": "contains", "value": "M5"}) == "OBJECT zawiera M5"
    assert d({"keyword": "OBJECT", "operator": "startswith", "value": "NGC"}) == "OBJECT zaczyna się od NGC"
    assert d({"keyword": "DATE-OBS", "operator": "exists"}) == "ma DATE-OBS"
    assert d({"keyword": "DATE-OBS", "operator": "not_exists"}) == "bez DATE-OBS"


def test_describe_bool_parytet_TF():
    """Bool renderuje się jak semantyka eq ('T'/'F'), nie 'True'/'False'."""
    assert filter_engine.describe({"keyword": "SIMPLE", "operator": "eq", "value": True}) == "SIMPLE = T"
    assert filter_engine.describe({"keyword": "SIMPLE", "operator": "eq", "value": False}) == "SIMPLE = F"


def test_describe_and_or_nawiasy():
    """Grupa zagnieżdżona o >1 dzieciach dostaje nawiasy; korzeń bez nich."""
    tree = {"op": "AND", "conditions": [
        {"keyword": "EXPTIME", "operator": "eq", "value": 300},
        {"op": "OR", "conditions": [
            {"keyword": "FILTER", "operator": "contains", "value": "Ha"},
            {"keyword": "FILTER", "operator": "not_exists"},
        ]},
    ]}
    assert filter_engine.describe(tree) == "EXPTIME = 300 i (FILTER zawiera Ha lub bez FILTER)"


def test_describe_grupa_1_dziecko_bez_nawiasow():
    tree = {"op": "AND", "conditions": [{"op": "OR", "conditions": [
        {"keyword": "GAIN", "operator": "eq", "value": 100}]}]}
    assert filter_engine.describe(tree) == "GAIN = 100"


def test_describe_not_poza():
    tree = {"op": "NOT", "conditions": [{"keyword": "OBJECT", "operator": "eq", "value": "M51"}]}
    assert filter_engine.describe(tree) == "poza (OBJECT = M51)"
    nested = {"op": "AND", "conditions": [
        {"keyword": "IMAGETYP", "operator": "eq", "value": "Light"}, tree]}
    assert filter_engine.describe(nested) == "IMAGETYP = Light i poza (OBJECT = M51)"


def test_describe_nieznany_op_fallback():
    """describe = prezentacja: nieznany op renderuje się surowo (wykonanie i tak podnosi ValueError)."""
    assert filter_engine.describe({"keyword": "A", "operator": "regex", "value": "x"}) == "A regex x"
    with pytest.raises(ValueError):
        filter_engine.run({"keyword": "A", "operator": "regex", "value": "x"},
                          leaf_fn=lambda *a: set(), universe_fn=lambda: set())


# ============================================================ FACETY (F4 — PLAN_ux_redesign §5)
# Liście relacyjne (rel_*), składacz/cykl (facet_model), describe facetów, literały licznikowe,
# sety trimów. Przypadki brzegowe nocy: przed/na granicy południa, ułamek 7-cyfrowy, klatka bez header.


@pytest.fixture
def facet_db(tmp_path):
    """Baza facetów: 2 obiekty, 3 teleskopy (rc8bis SCALONY pod RC8), 3 configi, noce z granicami.
      f1: M51,     Ha,   config RC8,        2025-08-14T22:00:00.123        → noc 2025-08-14; 2 OBECNE lokacje (dup)
      f2: NGC7000, OIII, config rc8bis(→RC8) 2025-08-15T11:59:59.999       → noc 2025-08-14 (przed południem)
      f3: NGC7000, Ha,   config ED80,       2025-08-15T12:00:00            → noc 2025-08-15 (granica WŁĄCZNIE)
      f4: master_flat XISF BEZ header/obiektu/configu (przeżywa ⊖ nocy — F4R#3)
      f5: M51,     filter NULL, config RC8, 2025-08-14T23:30:00.1234567    → noc 2025-08-14 (ułamek 7 cyfr)
      f6: light BEZ obiektu/header (kolejka review — `review_frame_ids`).
    exptime (F7 portfel): f1=3600, f2=7200, f3=3600, f5=NULL (grupa „(bez filtra)" cała bez exptime)."""
    con = db.open_db(str(tmp_path / "facet.db"))
    con.executemany("INSERT INTO object (id, canon, catalog) VALUES (?,?,?)",
                    [(1, "M51", "Messier"), (2, "NGC7000", "NGC")])
    con.executemany(
        "INSERT INTO telescope (id, telescop_canon, label, status, merged_into, created_at) "
        "VALUES (?,?,?,?,?,?)",
        [(1, "RC8", "RC8 8cala", "approved", None, NOW),
         (2, "rc8bis", None, "proposed", 1, NOW),
         (3, "ED80", None, "proposed", None, NOW)])
    con.execute("INSERT INTO camera (id, model_canon, created_at) VALUES (1, 'ASI2600MM', ?)", (NOW,))
    con.executemany(
        "INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES (?,?,?,?,?)",
        [(1, 1, 1, "proposed", NOW), (2, 2, 1, "proposed", NOW), (3, 3, 1, "proposed", NOW)])
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, config_id, object_id, filter_canon, "
        "first_seen_at) VALUES (?,?,?,?,?,?,?,?)",
        [(1, "f1", "light", "fits", 1, 1, "Ha", NOW),
         (2, "f2", "light", "fits", 2, 2, "OIII", NOW),
         (3, "f3", "light", "fits", 3, 2, "Ha", NOW),
         (4, "f4", "master_flat", "xisf", None, None, None, NOW),
         (5, "f5", "light", "fits", 1, 1, None, NOW),
         (6, "f6", "light", "fits", 1, None, None, NOW)])
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, date_obs, exptime) VALUES (?,?,?,?)",
        [(1, "{}", "2025-08-14T22:00:00.123", 3600.0),
         (2, "{}", "2025-08-15T11:59:59.999", 7200.0),
         (3, "{}", "2025-08-15T12:00:00", 3600.0),
         (5, "{}", "2025-08-14T23:30:00.1234567", None)])
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(1, "V", "/a/1.fits", 1), (1, "V", "/b/1c.fits", 1),
         (2, "V", "/a/2.fits", 1), (3, "V", "/a/3.fits", 1),
         (4, "V", "/a/4.xisf", 1), (5, "V", "/a/5.fits", 0),
         (6, "V", "/a/6.fits", 1)])
    con.commit()
    yield con
    con.close()


# ---------- liście relacyjne (rel_*) ----------

def test_rel_object(facet_db):
    assert _run(facet_db, {"facet": "object", "value": 1}) == {1, 5}
    assert _run(facet_db, {"facet": "object", "value": 2}) == {2, 3}


def test_rel_filter(facet_db):
    assert _run(facet_db, {"facet": "filter", "value": "Ha"}) == {1, 3}


def test_rel_kind(facet_db):
    assert _run(facet_db, {"facet": "kind", "value": "master_flat"}) == {4}


def test_rel_telescope_roluje_scalonego_pod_kanon(facet_db):
    """f2 stoi na configu SCALONEGO rc8bis → roluje się pod kanon RC8 (telescope_canonical)."""
    assert _run(facet_db, {"facet": "telescope", "value": 1}) == {1, 2, 5, 6}
    assert _run(facet_db, {"facet": "telescope", "value": 3}) == {3}


def test_rel_night_granice_poludnia(facet_db):
    """Noc D = [D 12:00, D+1 12:00): 11:59:59.999 następnego dnia WCHODZI (przed południem),
    12:00:00 zaczyna nową noc (granica włącznie); ułamek 7-cyfrowy porównuje się leksykalnie."""
    assert _run(facet_db, {"facet": "night", "value": "2025-08-14"}) == {1, 2, 5}
    assert _run(facet_db, {"facet": "night", "value": "2025-08-15"}) == {3}


def test_not_night_zachowuje_klatki_bez_date_obs(facet_db):
    """⊖ nocy (F4R#3): klatka BEZ header/date_obs (f4 XISF, f6) PRZEŻYWA wykluczenie każdej nocy —
    „nieznana data ≠ ta noc" (uniwersum − zakres; konsekwencja algebry jak NOT(pusta-grupa)=∅)."""
    tree = {"op": "NOT", "conditions": [{"facet": "night", "value": "2025-08-14"}]}
    assert _run(facet_db, tree) == {3, 4, 6}


def test_facet_label_czysta_prezentacja(facet_db):
    """`label` nie wpływa na eval (perspektywa ze stale-label daje ten sam zbiór)."""
    bez = _run(facet_db, {"facet": "object", "value": 1})
    z = _run(facet_db, {"facet": "object", "value": 1, "label": "STARA-NAZWA"})
    assert bez == z == {1, 5}


def test_nieznany_facet_i_zla_noc(facet_db):
    with pytest.raises(ValueError, match="facet"):
        _run(facet_db, {"facet": "tag", "value": "x"})
    for zla in ("2025-8-4", "sroda", None, "2025-08-14T00:00:00"):
        with pytest.raises(ValueError, match="noc"):
            _run(facet_db, {"facet": "night", "value": zla})


def test_night_bounds_przelom_miesiaca():
    assert filter_engine.night_bounds("2025-08-31") == ("2025-08-31T12:00:00", "2025-09-01T12:00:00")


# ---------- facet_model: cykl / sibling / compose ----------

def test_cycle_none_in_ex_none():
    s0 = facet_model.empty_state()
    s1 = facet_model.cycle(s0, "kind", "light", "light")
    assert s1 == {"kind": {"in": [["light", "light"]]}}
    assert facet_model.selection(s1, "kind", "light") == "in"
    s2 = facet_model.cycle(s1, "kind", "light", "light")
    assert s2 == {"kind": {"ex": [["light", "light"]]}}   # in→ex zachowuje label
    assert facet_model.selection(s2, "kind", "light") == "ex"
    s3 = facet_model.cycle(s2, "kind", "light", "light")
    assert s3 == {}                                        # normalizacja: pusta grupa znika
    assert s0 == {}                                        # wejścia niemutowane


def test_cycle_nieznany_facet():
    with pytest.raises(ValueError, match="facet"):
        facet_model.cycle({}, "tag", "x", "x")


def test_sibling_state_usuwa_cala_wlasna_grupe():
    s = {"object": {"in": [[1, "M51"]], "ex": [[2, "NGC7000"]]}, "kind": {"in": [["light", "light"]]}}
    assert facet_model.sibling_state(s, "object") == {"kind": {"in": [["light", "light"]]}}
    assert facet_model.sibling_state(s, "night") == s      # brak grupy → stan bez zmian


def test_compose_pusty_i_advanced():
    adv = {"keyword": "EXPTIME", "operator": "exists"}
    assert facet_model.compose({}, None) is None
    assert facet_model.compose({}, adv) is adv             # advanced NIEPRZEZROCZYSTE (identyczność)


def test_compose_jedno_dziecko_bez_and():
    s = {"object": {"in": [[1, "M51"]]}}
    assert facet_model.compose(s, None) == {"facet": "object", "value": 1, "label": "M51"}


def test_compose_or_wewnatrz_and_miedzy_not_wykluczen(facet_db):
    """AND( OR(in-wartości facetu), NOT(ex)…, advanced ) — i wynik na realnej bazie."""
    s = {"object": {"in": [[1, "M51"], [2, "NGC7000"]]},
         "night": {"ex": [["2025-08-14", "2025-08-14"]]}}
    adv = {"keyword": "EXPTIME", "operator": "exists"}
    tree = facet_model.compose(s, adv)
    assert tree["op"] == "AND"
    assert tree["conditions"][0] == {"op": "OR", "conditions": [
        {"facet": "object", "value": 1, "label": "M51"},
        {"facet": "object", "value": 2, "label": "NGC7000"}]}
    assert tree["conditions"][1] == {"op": "NOT", "conditions": [
        {"facet": "night", "value": "2025-08-14", "label": "2025-08-14"}]}
    assert tree["conditions"][2] is adv                    # advanced OSTATNIE, nietknięte
    # eval bez advanced: obiekty {1,2,3,5} − noc-14 {1,2,5} = {3}
    assert _run(facet_db, facet_model.compose(s, None)) == {3}


# ---------- describe facetów ----------

def test_describe_facet_lisc():
    d = filter_engine.describe
    assert d({"facet": "object", "value": 1, "label": "M51"}) == "Obiekt: M51"
    assert d({"facet": "object", "value": 1}) == "Obiekt: 1"          # bez label → value
    assert d({"facet": "night", "value": "2025-08-14"}) == "Noc: 2025-08-14"
    # F4R#7: facet-liść NIE wpada w fallback pustej grupy
    assert d({"facet": "kind", "value": "light"}) != "wszystkie klatki"
    not_tree = {"op": "NOT", "conditions": [{"facet": "night", "value": "2025-08-14"}]}
    assert d(not_tree) == "poza (Noc: 2025-08-14)"


# ---------- literały licznikowe + sety trimów ----------

def test_facet_objects_kubelki_order_canon(facet_db):
    ids = list(queries.all_frame_ids(facet_db))
    rows = [(r["id"], r["canon"], r["n"]) for r in queries.facet_objects(facet_db, ids)]
    assert rows == [(1, "M51", 2), (2, "NGC7000", 2)]      # f6 bez obiektu POZA (JOIN)


def test_facet_filters_null_wypada(facet_db):
    ids = list(queries.all_frame_ids(facet_db))
    rows = [(r["filter_canon"], r["n"]) for r in queries.facet_filters(facet_db, ids)]
    assert rows == [("Ha", 2), ("OIII", 1)]                # NULL (f4,f5,f6) bez fantomowego kubełka


def test_facet_kinds(facet_db):
    ids = list(queries.all_frame_ids(facet_db))
    rows = [(r["kind"], r["n"]) for r in queries.facet_kinds(facet_db, ids)]
    assert rows == [("light", 5), ("master_flat", 1)]


def test_facet_telescopes_rollup(facet_db):
    ids = list(queries.all_frame_ids(facet_db))
    rows = {r["id"]: (r["label"], r["telescop_canon"], r["n"])
            for r in queries.facet_telescopes(facet_db, ids)}
    assert rows[1] == ("RC8 8cala", "RC8", 4)              # f2 spod scalonego rc8bis pod kanonem
    assert rows[3] == (None, "ED80", 1)                    # label NULL → etykietę składa wołający
    assert 2 not in rows                                   # scalony NIE jest osobnym kubełkiem


def test_facet_nights_order_desc(facet_db):
    ids = list(queries.all_frame_ids(facet_db))
    rows = [(r["night"], r["n"]) for r in queries.facet_nights(facet_db, ids)]
    assert rows == [("2025-08-15", 1), ("2025-08-14", 3)]  # najnowsze pierwsze; bez header POZA


def test_facet_liczniki_na_podzbiorze_json_each(facet_db):
    rows = [(r["id"], r["n"]) for r in queries.facet_objects(facet_db, [1, 3])]
    assert rows == [(1, 1), (2, 1)]                        # json_each honoruje podzbiór


def test_property_kubelek_nocy_rowna_sie_liscowi(facet_db):
    """WŁASNOŚĆ (spójność dwóch derywacji nocy): dla KAŻDEGO kubełka `facet_nights`
    count(rel_night(D)) == n — etykieta `date(−12h)` i liść string-range znaczą to samo."""
    ids = list(queries.all_frame_ids(facet_db))
    buckets = queries.facet_nights(facet_db, ids)
    assert buckets                                          # fixture ma noce (test nie jest pusty)
    for r in buckets:
        assert len(_run(facet_db, {"facet": "night", "value": r["night"]})) == r["n"]


def test_dup_i_review_sets(facet_db):
    """Sety trimów (F4R2#2): JEDNA derywacja dla zbioru głównego i sibling-setów (SPOT)."""
    assert queries.dup_frame_ids(facet_db) == {1}           # 2 OBECNE lokacje; present=0 się nie liczy
    assert queries.review_frame_ids(facet_db) == {6}        # light bez obiektu; master_flat f4 POZA


# ---------- portfel naświetleń (F7, PLAN_ux_redesign §8) ----------

def test_object_exposure_kind_aware_kubelki(facet_db):
    """`object_exposure`: godziny per (obiekt, filtr). KIND-AWARE (`kind='light'`) → master_flat f4
    POZA; light-bez-obiektu f6 (object_id NULL) i light-bez-header POZA JOIN. JAWNE-NULL: f5 (M51,
    filtr NULL, exptime NULL) → grupa „(bez filtra)" z `secs=NULL` i `n_null=1`. ORDER secs DESC
    (NULL ostatni). f5 present=0 wliczony (parytet z n)."""
    rows = [(r["object_id"], r["filter_canon"], r["secs"], r["n_null"])
            for r in queries.object_exposure(facet_db, list(queries.all_frame_ids(facet_db)))]
    assert rows == [
        (1, "Ha", 3600.0, 0),      # M51: f1
        (1, None, None, 1),        # M51: f5 „(bez filtra)", cała-NULL exptime → secs NULL, n_null=1
        (2, "OIII", 7200.0, 0),    # NGC7000: f2 (secs DESC → OIII przed Ha)
        (2, "Ha", 3600.0, 0),      # NGC7000: f3
    ]


def test_object_exposure_honoruje_podzbior(facet_db):
    """`json_each` zawęża — tylko f1 (M51/Ha) w podzbiorze → jedna grupa."""
    rows = [(r["object_id"], r["filter_canon"], r["secs"]) for r in queries.object_exposure(facet_db, [1])]
    assert rows == [(1, "Ha", 3600.0)]


def test_portfolio_summarize_i_formatowanie():
    """Agregat Qt-wolny: grupowanie per obiekt, `secs=NULL`→0 s, sufiks/tooltip ze słownictwem F7."""
    rows = [
        {"object_id": 1, "filter_canon": "Ha", "secs": 3600.0, "n_null": 0},
        {"object_id": 1, "filter_canon": None, "secs": None, "n_null": 2},   # grupa cała bez exptime
        {"object_id": 2, "filter_canon": "OIII", "secs": 7200.0, "n_null": 0},
    ]
    summ = portfolio.summarize(rows)
    assert summ[1]["total_secs"] == 3600.0                   # NULL → 0 s
    assert summ[1]["n_null"] == 2
    assert summ[1]["per_filter"] == [("Ha", 3600.0, 0), (None, 0.0, 2)]
    assert portfolio.format_hours(3600) == "1.0 h"
    assert portfolio.format_hours(None) == "0.0 h"           # brak → 0, nie wyjątek
    assert portfolio.object_suffix(summ[1]) == " · 1.0 h (+2 bez exptime)"
    assert portfolio.object_tooltip(summ[1]) == "Ha: 1.0 h\n(bez filtra): 0.0 h\n+2 klatek bez exptime"
    assert portfolio.object_suffix(summ[2]) == " · 2.0 h"    # bez ogona n_null gdy n_null=0
    assert portfolio.object_tooltip(summ[2]) == "OIII: 2.0 h"


def test_run_bez_filtra_oddaje_uniwersum_wprost():
    """TRIPWIR PRZESŁANKI (wizytator P5 #2): `filter_engine.run(None, …)` zwraca obiekt uniwersum
    WPROST — nie kopię. To jest powód, dla którego każdy trim perspektywy w `grid.refresh` MUSI
    budować nowy set (`a & b`), a nie przycinać w miejscu (`a &= b`): w miejscu truł memoizację
    refreshu i grid twierdził „Baza pusta" na pełnej bazie.

    Gdyby `run` zaczęło kiedyś zwracać kopię, ten test padnie — i wtedy komentarz w `grid.refresh`
    przestanie być prawdą, więc trzeba go poprawić razem z tym testem. Objaw pilnuje osobno
    `test_gui_mainwindow.py::test_pusta_perspektywa_nie_klamie_ze_baza_pusta`."""
    uniwersum = {1, 2, 3}
    wynik = filter_engine.run(None, leaf_fn=lambda *a: set(), universe_fn=lambda: uniwersum)
    assert wynik is uniwersum
