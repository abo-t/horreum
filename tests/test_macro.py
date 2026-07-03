"""Testy `horreum.macro` — czysty silnik makra nad frame_ids (widok gridu) z wstrzykiwanymi
akcesorami (`queries.writeback_frame_targets`/`frame_cards`). Pokrycie: przyklady A/B, reguly
set/add + idx (parytet dawcy), oraz NOWE bramki Horreum (D-W1 n_present, D-W2 XISF, T6 compressed,
header_hash NULL). Karty/lokacje wstawiamy wprost SQL (testy poza bramka AST) — makro dziala na
wierszach niezaleznie od zrodla.

Makro NIE zapisuje (zwraca MacroRun); test sprawdza podglad, nie DML."""

from __future__ import annotations

from functools import partial

from horreum import db, macro
from horreum.gui import queries


def _con(tmp_path):
    return db.open_db(str(tmp_path / "m.db"))


def _frame(con, *, sha1, filetype="fits", cards=None, locations=None):
    """Wstaw frame + location(y) + cards wprost. `locations` = lista dict(path, header_hash='h',
    compressed=0, present=1). Domyslnie jedna obecna kopia FITS. Zwraca frame_id."""
    fid = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?)",
        (sha1, "light", filetype, "t")).lastrowid
    for loc in (locations or [{"path": f"R:/{sha1}.fits"}]):
        con.execute(
            "INSERT INTO location(frame_id, volume, path, header_hash, hdu_index, compressed, "
            "present) VALUES (?,?,?,?,?,?,?)",
            (fid, "V", loc["path"], loc.get("header_hash", "h"), loc.get("hdu_index", 0),
             loc.get("compressed", 0), loc.get("present", 1)))
    for c in (cards or []):
        con.execute(
            "INSERT INTO cards(frame_id, keyword, idx, value_raw, value_num, value_type, comment) "
            "VALUES (?,?,?,?,?,?,?)", (fid, *c))
    con.commit()
    return fid


def _run(con, md, frame_ids, **kw):
    return macro.run_macro(
        md, frame_ids,
        targets_fn=partial(queries.writeback_frame_targets, con),
        cards_fn=partial(queries.frame_cards, con), **kw)


def _num(keyword, raw, num, idx=0):
    return (keyword, idx, raw, num, "float", None)


def _txt(keyword, raw, idx=0, comment=None):
    return (keyword, idx, raw, None, "str", comment)


# --- Przyklad A: compute new=FOCALLEN/FOCRATIO ; assign FOCRATIO=round(new,2) ---

def test_example_a_compute_and_set(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="a", cards=[_num("FOCALLEN", "600.0", 600.0), _num("FOCRATIO", "150.0", 150.0)])
    md = {
        "name": "fix-focratio",
        "computes": [{"name": "new", "expr": "FOCALLEN / FOCRATIO"}],
        "assign": {"keyword": "FOCRATIO", "op": "set", "expr": "round(new, 2)"},
    }
    run = _run(con, md, [a], run_id="A")
    assert len(run.touched) == 1 and not run.skipped
    p = run.touched[0]
    assert p.keyword == "FOCRATIO" and p.op == "set" and p.idx == 0
    assert p.old_value == "150.0" and p.new_value == "4.0" and p.new_type == "float"
    # cel = OBECNA location frame'a (nie frame)
    loc = con.execute("SELECT id, header_hash FROM location WHERE frame_id=?", (a,)).fetchone()
    assert p.location_id == loc["id"] and p.expected_header_hash == loc["header_hash"]


# --- Przyklad B: assign literalny (wartosc naglowka jako tekst, nie wyrazenie) ---

def test_example_b_literal_assign(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="b", cards=[_txt("TELESCOP", "EQ6")])
    md = {"assign": {"keyword": "TELESCOP", "op": "set", "expr": "SkyWatcher EQ6-R"}}
    run = _run(con, md, [a])
    assert len(run.touched) == 1 and not run.skipped
    assert run.touched[0].new_value == "SkyWatcher EQ6-R" and run.touched[0].new_type == "str"


# --- Reguly operacji ---

def test_set_without_card_skips(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="c", cards=[_txt("OBJECT", "M51")])
    run = _run(con, {"assign": {"keyword": "GAIN", "op": "set", "expr": "100"}}, [a])
    assert not run.touched and len(run.skipped) == 1 and "brak karty" in run.skipped[0].reason


def test_add_when_card_exists_skips(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="d", cards=[_txt("OBJECT", "M51")])
    run = _run(con, {"assign": {"keyword": "OBJECT", "op": "add", "expr": "NGC"}}, [a])
    assert not run.touched and "juz istnieje" in run.skipped[0].reason


def test_add_when_absent(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="e", cards=[_txt("OBJECT", "M51")])
    run = _run(con, {"assign": {"keyword": "FOCALLEN", "op": "add", "expr": "600"}}, [a])
    assert len(run.touched) == 1 and run.touched[0].op == "add" and run.touched[0].old_value is None


def test_multi_occurrence_requires_idx(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="f", cards=[_txt("COMMENT", "x", idx=0), _txt("COMMENT", "y", idx=1)])
    run = _run(con, {"assign": {"keyword": "COMMENT", "op": "set", "expr": "z"}}, [a])
    assert not run.touched and "wiele wystapien" in run.skipped[0].reason


def test_int_fractional_result_skips(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="g", cards=[("GAIN", 0, "100", 100.0, "int", None)])
    run = _run(con, {"assign": {"keyword": "GAIN", "op": "set", "expr": "100 / 3"}}, [a])
    assert not run.touched and "niecalkowit" in run.skipped[0].reason


# --- NOWE bramki celu (brief §6) ---

def test_xisf_skipped_dw2(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="x", filetype="xisf",
               locations=[{"path": "R:/x.xisf", "header_hash": None}])
    run = _run(con, {"assign": {"keyword": "TELESCOP", "op": "add", "expr": "ED"}}, [a])
    assert not run.touched and "XISF" in run.skipped[0].reason


def test_multi_present_location_skipped_dw1(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="m", cards=[_txt("OBJECT", "M51")],
               locations=[{"path": "R:/m1.fits"}, {"path": "R:/m2.fits"}])  # 2 obecne kopie
    run = _run(con, {"assign": {"keyword": "OBJECT", "op": "set", "expr": "NGC"}}, [a])
    assert not run.touched and "wiele obecnych kopii" in run.skipped[0].reason


def test_zero_present_location_skipped(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="z", cards=[_txt("OBJECT", "M51")],
               locations=[{"path": "R:/z.fits", "present": 0}])
    run = _run(con, {"assign": {"keyword": "OBJECT", "op": "set", "expr": "NGC"}}, [a])
    assert not run.touched and "brak obecnej kopii" in run.skipped[0].reason


def test_compressed_master_skipped_t6(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="k", cards=[_txt("OBJECT", "M51")],
               locations=[{"path": "R:/k.fits", "compressed": 1}])
    run = _run(con, {"assign": {"keyword": "OBJECT", "op": "set", "expr": "NGC"}}, [a])
    assert not run.touched and "skompresowany" in run.skipped[0].reason


def test_header_hash_null_skipped(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="n", cards=[_txt("OBJECT", "M51")],
               locations=[{"path": "R:/n.fits", "header_hash": None}])
    run = _run(con, {"assign": {"keyword": "OBJECT", "op": "set", "expr": "NGC"}}, [a])
    assert not run.touched and "header_hash" in run.skipped[0].reason


# --- Serializacja + edycja reczna ---

def test_macro_roundtrip_serialization():
    md = macro.MacroDef.from_dict({
        "name": "n", "filter": {"keyword": "K", "operator": "gt", "value": 1},
        "computes": [{"name": "x", "expr": "A + 1"}],
        "assign": {"keyword": "K", "op": "set", "expr": "x"}})
    assert macro.MacroDef.from_dict(md.to_dict()).to_dict() == md.to_dict()


def test_manual_set_keeps_type(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="man", cards=[_num("FOCRATIO", "150.0", 150.0)])
    cards = queries.frame_cards(con, a)
    res = macro.evaluate_manual_change(cards, "FOCRATIO", "4")
    assert res.ok and res.op == "set" and res.idx == 0
    assert res.old_value == "150.0" and res.new_value == "4.0" and res.new_type == "float"


def test_manual_add_when_absent(tmp_path):
    con = _con(tmp_path)
    a = _frame(con, sha1="man2", cards=[_txt("OBJECT", "M51")])
    cards = queries.frame_cards(con, a)
    res = macro.evaluate_manual_change(cards, "FOCALLEN", "600")
    assert res.ok and res.op == "add" and res.new_value == "600" and res.new_type == "int"
