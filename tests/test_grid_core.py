"""Grid „Klatki" (PLAN_gui_grid) — rdzeń Qt-wolny: silnik filtra (algebra zbiorów), pivot, read-model.

Mała REALNA baza (frame + cards + location + header) — testuje SQL literały (json_each, joiny) ORAZ
semantykę operatorów 1:1 z dawcą. Must-fixy recenzji pokryte: F1 (uniwersum = wszystkie frame, XISF bez
cards w `not_exists`/`OR`), F3 (`present` kolumna, klatka zniknięta widoczna), F6 (pusta grupa = wszystko).
Wstawianie wierszy surowym SQL dozwolone w `tests/` (meta-test AST skanuje tylko pakiet `horreum`)."""
import pytest

from horreum import db, filter_engine, pivot
from horreum.gui import queries

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
