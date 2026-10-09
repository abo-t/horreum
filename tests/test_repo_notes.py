"""Uwagi klatki (0032) - klinga `repo.set_frame_note` / `clear_frame_note` / `restore_frame_notes`.

Pilnujemy: (1) normalizacja i limity mieszkają w klindze i odmawiają PRZED zapisem, (2) gest jest
idempotentny i jeden - jedna transakcja, jeden `ts`, event tylko przy realnej zmianie, (3) `before`
gestu jest drogą powrotu, która oddaje treść bajt w bajt także zaznaczeniu mieszanemu, (4) parytet
`frame_note` z dziennikiem widzi ubytek, wstrzyknięcie i podmianę treści gołym SQL-em.
"""
import json

import pytest

from horreum import audit, db, repo

NOW = "2026-10-09T10:00:00+00:00"
LATER = "2026-10-09T11:00:00+00:00"
LATEST = "2026-10-09T12:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _klatki(con, n):
    return [repo.upsert_frame(con, sha1_data=f"s{i}", kind="light", filetype="raw",
                              camera_id=None, now=NOW)[0] for i in range(n)]


def _uwagi(con):
    return {r[0]: r[1] for r in con.execute("SELECT frame_id, body FROM frame_note")}


def _eventy(con):
    return [(r["ts"], r["actor"], r["verb"], r["target"], json.loads(r["payload"]), r["reason"])
            for r in con.execute("SELECT ts, actor, verb, target, payload, reason FROM event "
                                 "WHERE verb LIKE 'note.%' ORDER BY id")]


def _parytet(con):
    return {p.name: p for p in audit.entity_event_parity(con)
            if p.name in ("frame_note", "frame_note.body")}


# ---------------------------------------------------------------- ustawienie

def test_ustawienie_pisze_wiersz_i_event_per_klatka_z_jednym_ts():
    con = _baza()
    a, b = _klatki(con, 2)
    g = repo.set_frame_note(con, frame_ids=[b, a, a], body="chmury po 2:00", now=NOW)
    assert g == repo.NoteGesture(changed=(a, b), unchanged=(), before={a: None, b: None})
    assert _uwagi(con) == {a: "chmury po 2:00", b: "chmury po 2:00"}
    assert {r[0] for r in con.execute("SELECT updated_at FROM frame_note")} == {NOW}
    assert _eventy(con) == [
        (NOW, "user:local", "note.set", f"frame:{a}", {"before": None, "after": "chmury po 2:00"},
         None),
        (NOW, "user:local", "note.set", f"frame:{b}", {"before": None, "after": "chmury po 2:00"},
         None)]


def test_powtorzenie_tej_samej_tresci_bez_eventu():
    """Idempotencja: przeklikanie okna nie puchnie dziennika. Klatka z tą samą treścią idzie do
    `unchanged`, druga (bez uwagi) do `changed` - jeden gest, dwa stany zastane."""
    con = _baza()
    a, b = _klatki(con, 2)
    repo.set_frame_note(con, frame_ids=[a], body="flat zmieniony", now=NOW)
    g = repo.set_frame_note(con, frame_ids=[a, b], body="  flat   zmieniony ", now=LATER)
    assert (g.changed, g.unchanged, g.before) == ((b,), (a,), {b: None})
    assert len(_eventy(con)) == 2
    assert con.execute("SELECT updated_at FROM frame_note WHERE frame_id=?",
                       (a,)).fetchone()[0] == NOW                     # nietknięty wiersz
    assert repo.set_frame_note(con, frame_ids=[a, b], body="flat zmieniony",
                               now=LATEST).changed == ()
    assert len(_eventy(con)) == 2


def test_nadpisanie_niesie_poprzednia_tresc_w_payloadzie():
    con = _baza()
    (a,) = _klatki(con, 1)
    repo.set_frame_note(con, frame_ids=[a], body="księżyc 80%", now=NOW)
    g = repo.set_frame_note(con, frame_ids=[a], body="księżyc 90%", now=LATER)
    assert g.before == {a: "księżyc 80%"}
    assert _eventy(con)[-1][4] == {"before": "księżyc 80%", "after": "księżyc 90%"}
    assert con.execute("SELECT body, updated_at FROM frame_note").fetchone()[:] == \
        ("księżyc 90%", LATER)


def test_normalizacja_zwija_biale_znaki_takze_nowe_linie():
    con = _baza()
    (a,) = _klatki(con, 1)
    repo.set_frame_note(con, frame_ids=[a], body="\t chmury\r\n po \n\n 2:00  ", now=NOW)
    assert _uwagi(con) == {a: "chmury po 2:00"}
    assert repo.normalize_note(None) == "" and repo.normalize_note(" a  b ") == "a b"


@pytest.mark.parametrize("body", ["", "   ", "\n\t \r\n", None])
def test_pusta_po_normalizacji_odmowa_bez_zapisu(body):
    con = _baza()
    (a,) = _klatki(con, 1)
    with pytest.raises(ValueError, match="clear_frame_note"):
        repo.set_frame_note(con, frame_ids=[a], body=body, now=NOW)
    assert _uwagi(con) == {} and _eventy(con) == []


def test_limit_liczony_po_normalizacji():
    """`NOTE_MAX` to znaki PO normalizacji: dokładnie limit przechodzi, znak więcej - odmowa;
    tekst rozdęty spacjami ponad limit przechodzi, gdy po zwinięciu się mieści."""
    con = _baza()
    a, b, c = _klatki(con, 3)
    repo.set_frame_note(con, frame_ids=[a], body="x" * repo.NOTE_MAX, now=NOW)
    with pytest.raises(ValueError, match=str(repo.NOTE_MAX)):
        repo.set_frame_note(con, frame_ids=[b], body="x" * (repo.NOTE_MAX + 1), now=NOW)
    rozdety = "  ".join(["ab"] * 100)                 # 398 znaków, po zwinięciu 299
    assert len(rozdety) > repo.NOTE_MAX
    repo.set_frame_note(con, frame_ids=[c], body=rozdety, now=NOW)
    assert set(_uwagi(con)) == {a, c} and len(_uwagi(con)[c]) == 299


def test_nieistniejaca_klatka_odmowa_przed_jakimkolwiek_zapisem():
    """Klatka spoza bazy wywraca CAŁY gest, także klatki istniejące z tego samego zaznaczenia -
    transakcja jedna, odmowa przed pierwszym zapisem."""
    con = _baza()
    a, b = _klatki(con, 2)
    repo.set_frame_note(con, frame_ids=[b], body="stara", now=NOW)
    for gest in (lambda: repo.set_frame_note(con, frame_ids=[a, 999], body="x", now=LATER),
                 lambda: repo.clear_frame_note(con, frame_ids=[b, 999], now=LATER),
                 lambda: repo.restore_frame_notes(con, before={a: "y", 999: None}, now=LATER)):
        with pytest.raises(ValueError, match="999"):
            gest()
    assert _uwagi(con) == {b: "stara"} and len(_eventy(con)) == 1


def test_uid_trafia_do_aktora():
    con = _baza()
    (a,) = _klatki(con, 1)
    repo.set_frame_note(con, frame_ids=[a], body="x", now=NOW, uid="zdzich")
    repo.clear_frame_note(con, frame_ids=[a], now=LATER, uid="zdzich")
    assert {e[1] for e in _eventy(con)} == {"user:zdzich"}


# ---------------------------------------------------------------- zdjęcie

def test_zdjecie_kasuje_wiersz_a_klatka_bez_uwagi_jest_bez_zmian():
    con = _baza()
    a, b = _klatki(con, 2)
    repo.set_frame_note(con, frame_ids=[a], body="do zdjęcia", now=NOW)
    g = repo.clear_frame_note(con, frame_ids=[a, b], now=LATER)
    assert g == repo.NoteGesture(changed=(a,), unchanged=(b,), before={a: "do zdjęcia"})
    assert _uwagi(con) == {}
    assert _eventy(con)[-1] == (LATER, "user:local", "note.cleared", f"frame:{a}",
                                {"before": "do zdjęcia"}, None)
    assert repo.clear_frame_note(con, frame_ids=[a, b], now=LATEST).changed == ()
    assert len(_eventy(con)) == 2


# ---------------------------------------------------------------- cofnięcie

def test_cofniecie_gestu_mieszanego_oddaje_stan_bajt_w_bajt():
    """Zaznaczenie mieszane: dwie klatki z RÓŻNĄ uwagą, jedna bez. Gest „zapisz jedną” zmienia
    wszystkie trzy; cofnięcie ma oddać każdą z osobna - tekst z polskimi znakami bajt w bajt,
    a klatce bez uwagi zdjąć uwagę (nie zostawić pustego wiersza). Te same czasowniki z powodem."""
    con = _baza()
    a, b, c, d = _klatki(con, 4)
    repo.set_frame_note(con, frame_ids=[a], body="Mgła, księżyc 80% - ŻÓŁĆ", now=NOW)
    repo.set_frame_note(con, frame_ids=[c], body="wiatr", now=NOW)
    repo.set_frame_note(con, frame_ids=[d], body="poza gestem", now=NOW)
    przed = {k: v.encode("utf-8") for k, v in _uwagi(con).items()}

    g = repo.set_frame_note(con, frame_ids=[a, b, c], body="jedna", now=LATER)
    assert g.before == {a: "Mgła, księżyc 80% - ŻÓŁĆ", b: None, c: "wiatr"}
    n_przed_cofnieciem = len(_eventy(con))

    cof = repo.restore_frame_notes(con, before=g.before, now=LATEST)
    assert {k: v.encode("utf-8") for k, v in _uwagi(con).items()} == przed
    assert cof.changed == (a, b, c) and cof.before == {a: "jedna", b: "jedna", c: "jedna"}
    nowe = _eventy(con)[n_przed_cofnieciem:]
    assert [(e[2], e[3], e[5]) for e in nowe] == [
        ("note.set", f"frame:{a}", "cofnięcie"), ("note.cleared", f"frame:{b}", "cofnięcie"),
        ("note.set", f"frame:{c}", "cofnięcie")]
    assert nowe[0][4] == {"before": "jedna", "after": "Mgła, księżyc 80% - ŻÓŁĆ"}
    assert {e[0] for e in nowe} == {LATEST}                         # jeden gest = jeden ts


def test_drugie_cofniecie_nic_nie_pisze_a_cofniecie_cofniecia_wraca():
    con = _baza()
    a, b = _klatki(con, 2)
    g = repo.set_frame_note(con, frame_ids=[a, b], body="x", now=NOW)
    cof = repo.restore_frame_notes(con, before=g.before, now=LATER)
    n = len(_eventy(con))
    assert repo.restore_frame_notes(con, before=g.before, now=LATEST).changed == ()
    assert len(_eventy(con)) == n
    repo.restore_frame_notes(con, before=cof.before, now=LATEST)
    assert _uwagi(con) == {a: "x", b: "x"}


@pytest.mark.parametrize("zly", ["", "  ", 7])
def test_cofniecie_odmawia_stanu_ktory_nie_jest_uwaga(zly):
    con = _baza()
    a, b = _klatki(con, 2)
    repo.set_frame_note(con, frame_ids=[a], body="zostaje", now=NOW)
    with pytest.raises(ValueError):
        repo.restore_frame_notes(con, before={a: None, b: zly}, now=LATER)
    assert _uwagi(con) == {a: "zostaje"} and len(_eventy(con)) == 1


def test_cofniecie_z_expected_nie_nadpisuje_zapisu_z_drugiego_polaczenia(tmp_path):
    """Okno TOCTOU cofnięcia: wołający sprawdził, że uwagi celu są wciąż tymi z gestu, a zanim
    jego transakcja wzięła blokadę, drugie połączenie zmieniło jedną z nich. Guard `expected`
    rozstrzyga POD blokadą: klatka z cudzą, nowszą treścią zostaje `unchanged` bez eventu,
    reszta celu wraca do stanu sprzed gestu.

    Falsyfikator: zdejmij warunek `expected` z `_note_gesture` → „cudza" przepada na rzecz `None`."""
    sciezka = str(tmp_path / "uwagi.db")
    con = db.open_db(sciezka)
    a, b = _klatki(con, 2)
    g = repo.set_frame_note(con, frame_ids=[a, b], body="x", now=NOW)
    oczekiwane = {fid: "x" for fid in g.before}             # odczyt wołającego PRZED transakcją
    drugie = db.open_db(sciezka)
    try:
        repo.set_frame_note(drugie, frame_ids=[a], body="cudza", now=LATER)
    finally:
        drugie.close()
    n = len(_eventy(con))
    cof = repo.restore_frame_notes(con, before=g.before, expected=oczekiwane, now=LATEST)
    assert _uwagi(con) == {a: "cudza"}
    assert cof.changed == (b,) and cof.unchanged == (a,) and cof.before == {b: "x"}
    assert [(e[2], e[3]) for e in _eventy(con)[n:]] == [("note.cleared", f"frame:{b}")]
    con.close()


def test_cofniecie_z_expected_musi_pokryc_caly_cel():
    con = _baza()
    a, b = _klatki(con, 2)
    g = repo.set_frame_note(con, frame_ids=[a, b], body="x", now=NOW)
    with pytest.raises(ValueError):
        repo.restore_frame_notes(con, before=g.before, expected={a: "x"}, now=LATER)
    assert _uwagi(con) == {a: "x", b: "x"}


# ---------------------------------------------------------------- parytet z dziennikiem

def test_parytet_zielony_po_kazdej_drodze_klingi():
    con = _baza()
    a, b, c = _klatki(con, 3)
    assert all(p.ok and p.entities == 0 for p in _parytet(con).values())
    g = repo.set_frame_note(con, frame_ids=[a, b], body="x", now=NOW)
    repo.set_frame_note(con, frame_ids=[a], body="y", now=LATER)
    repo.clear_frame_note(con, frame_ids=[b], now=LATER)
    repo.set_frame_note(con, frame_ids=[c], body="z", now=LATER)
    repo.restore_frame_notes(con, before=g.before, now=LATEST)
    p = _parytet(con)
    assert all(r.ok for r in p.values()), p
    assert p["frame_note"].entities == len(_uwagi(con)) == 1          # tylko `c`


def test_parytet_lapie_podmiane_tresci_ubytek_i_wstrzykniecie():
    """Licznik nie widzi podmiany tekstu (wiersz zostaje) - widzi ją drugi wiersz parytetu.
    Ubytek i wstrzyknięcie z pominięciem klingi łapie licznik."""
    con = _baza()
    a, b, c = _klatki(con, 3)
    repo.set_frame_note(con, frame_ids=[a, b], body="x", now=NOW)
    con.execute("UPDATE frame_note SET body = 'podmiana' WHERE frame_id = ?", (a,))
    p = _parytet(con)
    assert p["frame_note"].ok and not p["frame_note.body"].ok
    con.execute("UPDATE frame_note SET body = 'x' WHERE frame_id = ?", (a,))
    con.execute("DELETE FROM frame_note WHERE frame_id = ?", (b,))
    assert not _parytet(con)["frame_note"].ok
    con.execute("INSERT INTO frame_note(frame_id, body, updated_at) VALUES (?, 'x', ?)", (b, NOW))
    assert all(r.ok for r in _parytet(con).values())
    con.execute("INSERT INTO frame_note(frame_id, body, updated_at) VALUES (?, 'bez gestu', ?)",
                (c, NOW))
    assert not _parytet(con)["frame_note"].ok
