"""Drogi ręki bez Qt: przeniesienie faktów ręki gestem (AR-41) i edycja jednej komórki do szuflady
(AR-61) - rdzeń, klinga stagingu i zdania z katalogu. Testy okna leżą w `test_gui_drogi_reki.py`."""
import ast
from pathlib import Path

import pytest

from horreum import db, macro, repo, supersede, writeback
from horreum.gui import i18n
from horreum.gui.i18n_catalog import CATALOG

NOW = "2026-10-06T10:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _klatka(con, sha, *, kind="light"):
    return repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype="raw", camera_id=None,
                             now=NOW)[0]


def _zastap(con, stara, nowa, path):
    """Podmiana treści pod ścieżką i ogniwo zastąpienia - ta sama droga, co w `test_supersede`."""
    lid = repo.add_location(con, frame_id=stara, volume="TESTVOL", path=path, now=NOW)[0]
    repo.rebind_location(con, location_id=lid, frame_after=nowa, now=NOW)
    assert repo.mark_superseded(con, frame_id=stara, superseded_by=nowa, now=NOW)


def _obiekt(con, canon="IC443"):
    return repo.upsert_object(con, canon=canon, catalog="IC", kind=None, now=NOW)[0]


# ---------------------------------------------------------------- AR-41: fakt zatrzymany

def test_fakt_zatrzymany_to_lustro_object_kept_klingi():
    """Predykat wiersza Porządków i klinga mówią o tej samej populacji: para trafia do
    `kept_object_facts` dokładnie wtedy, gdy przeniesienie odda `object_kept=True`. Para z lightem
    po drugiej stronie jest w `pending_transfer`, nie tutaj - zbiory rozłączne.

    Falsyfikator: zdejmij warunek `n_kind not in LIGHT_KINDS` z predykatu - para light→light wpada
    do obu zbiorów naraz."""
    con = _baza()
    oid = _obiekt(con)
    a, b = _klatka(con, "a"), _klatka(con, "b", kind="flat")        # następczyni-kalibracja
    c, d = _klatka(con, "c"), _klatka(con, "d")                     # następczyni-light
    e, f = _klatka(con, "e"), _klatka(con, "f", kind="unknown")     # rodzaj nieustalony
    for stara in (a, c, e):
        repo.assign_object(con, frame_id=stara, object_id=oid, object_source="user", now=NOW)
    _zastap(con, a, b, r"R:\X\a.fits")
    _zastap(con, c, d, r"R:\X\c.fits")
    _zastap(con, e, f, r"R:\X\e.fits")

    zatrzymane = supersede.kept_object_facts(con)
    assert zatrzymane == [(a, b), (e, f)]
    assert {s for s, _n, _co in supersede.pending_transfer(con)} == {c}
    for stara, _nowa in zatrzymane:
        assert repo.transfer_human_facts(con, frame_id=stara, now=NOW).object_kept is True
    # Ręka nietykalna: werdykt został na zastąpionej, następczyni bez obiektu.
    assert con.execute("SELECT object_id FROM frame WHERE id=?", (a,)).fetchone()[0] == oid
    assert con.execute("SELECT object_id FROM frame WHERE id=?", (b,)).fetchone()[0] is None


def test_fakt_zatrzymany_bez_faktu_reki_milczy():
    """Źródło automatu (nagłówek) nie jest faktem ręki - zastąpienie lightu flatem nie daje
    wiersza „zatrzymany", bo nic z ręki nie zostało."""
    con = _baza()
    a, b = _klatka(con, "a"), _klatka(con, "b", kind="flat")
    repo.assign_object(con, frame_id=a, object_id=_obiekt(con), object_source="header", now=NOW)
    _zastap(con, a, b, r"R:\X\a.fits")
    assert supersede.kept_object_facts(con) == []


# ---------------------------------------------------------------- AR-41: gest przeniesienia

def test_gest_przeniesienia_liczy_osie_zatrzymane_i_pominiecia():
    """Gest na zaznaczeniu: oś obiektu przechodzi na light, werdykt zostaje przy kalibracji
    (`object_kept`), klatka bez faktów ręki i klatka niezastąpiona mają własne człony - nic nie
    znika z rachunku: `done + skipped + kalibracja + not_superseded == total`."""
    con = _baza()
    oid = _obiekt(con)
    a, b = _klatka(con, "a"), _klatka(con, "b")                     # przeniesie obiekt
    c, d = _klatka(con, "c"), _klatka(con, "d", kind="flat")        # obiekt zostaje
    e, f = _klatka(con, "e"), _klatka(con, "f")                     # bez faktów ręki
    zywa = _klatka(con, "z")                                        # nie jest zastąpiona
    for stara in (a, c):
        repo.assign_object(con, frame_id=stara, object_id=oid, object_source="user", now=NOW)
    _zastap(con, a, b, r"R:\X\a.dng")
    _zastap(con, c, d, r"R:\X\c.fits")
    _zastap(con, e, f, r"R:\X\e.dng")

    g = supersede.transfer_gesture(con, frame_ids=[a, c, e, zywa], now=NOW)
    assert (g.total, g.done, g.object_moved, g.object_kept, g.not_superseded) == (4, 1, 1, 1, 1)
    assert g.skipped == {"none": 1}
    assert g.frame_ids == (a,)
    assert con.execute("SELECT object_id, object_source FROM frame WHERE id=?",
                       (b,)).fetchone()[:] == (oid, "user")
    # Powtórzenie: klinga idempotentna, nic nie przechodzi drugi raz.
    g2 = supersede.transfer_gesture(con, frame_ids=[a], now=NOW)
    assert (g2.done, g2.skipped) == (0, {"own": 1})


def test_zdanie_przeniesienia_renderuje_object_kept(monkeypatch):
    """Zdanie paska mówi o werdykcie zatrzymanym osobnym członem - nie chowa go w „pominięto".
    Falsyfikator: usuń człon `object_kept` z `zdanie_przeniesienia` - asercja o „został" pada."""
    i18n.set_lang("pl")
    g = supersede.TransferGesture(total=3, done=1, object_moved=1, object_kept=2,
                                  skipped={"none": 1})
    msg = supersede.zdanie_przeniesienia(g)
    assert msg.startswith("Przeniesienie faktów ręki: 1 z 3 klatek (obiekt: 1)")
    assert "2 werdykty obiektu zostały na klatkach zastąpionych" in msg
    assert "1 klatka bez faktów ręki" in msg
    i18n.set_lang("en")
    assert "2 object verdicts stayed on the superseded frames" in supersede.zdanie_przeniesienia(g)


def test_nieznany_powod_klingi_to_blad_wolajacego(monkeypatch):
    """EXPECT: powód dopisany w klindze bez wpisu w mapie zdania nie może zniknąć z rozbicia."""
    con = _baza()
    a, b = _klatka(con, "a"), _klatka(con, "b")
    _zastap(con, a, b, r"R:\X\a.dng")
    monkeypatch.setattr(repo, "transfer_human_facts",
                        lambda con, **kw: repo.FactTransfer(skipped="nowy powod"))
    with pytest.raises(KeyError):
        supersede.transfer_gesture(con, frame_ids=[a], now=NOW)


def _dwie_pary_z_obiektem(con):
    oid = _obiekt(con)
    a, b = _klatka(con, "a"), _klatka(con, "b")
    c, d = _klatka(con, "c"), _klatka(con, "d")
    for stara in (a, c):
        repo.assign_object(con, frame_id=stara, object_id=oid, object_source="user", now=NOW)
    _zastap(con, a, b, r"R:\X\a.dng")
    _zastap(con, c, d, r"R:\X\c.dng")
    return oid, a, b, c, d


def test_ogniwo_zgaszone_miedzy_odczytem_a_klinga_to_powod_nie_wyjatek(monkeypatch):
    """Skan gasi ogniwo drugiej klatki między odczytem gestu a klingą (treść wróciła) - klinga
    odmawia `ValueError`, a gest liczy to jako jawny powód i kończy z pełnym raportem; pierwsza
    klatka przeniesiona. Falsyfikator: zdejmij `except ValueError` w `transfer_gesture`."""
    con = _baza()
    oid, a, b, c, d = _dwie_pary_z_obiektem(con)
    prawdziwa = repo.transfer_human_facts

    def _skan_w_trakcie(con, *, frame_id, now, actor):
        if frame_id == c:
            repo.clear_superseded(con, frame_id=c, now=now)
        return prawdziwa(con, frame_id=frame_id, now=now, actor=actor)
    monkeypatch.setattr(repo, "transfer_human_facts", _skan_w_trakcie)
    g = supersede.transfer_gesture(con, frame_ids=[a, c], now=NOW)
    assert (g.done, g.no_longer_superseded, g.frame_ids) == (1, 1, (a,))
    i18n.set_lang("pl")
    assert "1 klatka przestała być zastąpiona w trakcie gestu" in supersede.zdanie_przeniesienia(g)


def test_inny_blad_klingi_niesie_raport_czesciowy(monkeypatch):
    """Błąd klingi na drugiej klatce (nie zgaszone ogniwo) leci dalej, ale niesie raport tego, co
    już zapisano - wołający ma odświeżyć widok i o tym powiedzieć."""
    con = _baza()
    oid, a, b, c, d = _dwie_pary_z_obiektem(con)
    prawdziwa = repo.transfer_human_facts

    def _pada_na_drugiej(con, *, frame_id, now, actor):
        if frame_id == c:
            raise ValueError("frame:999 (następczyni) nie istnieje")
        return prawdziwa(con, frame_id=frame_id, now=now, actor=actor)
    monkeypatch.setattr(repo, "transfer_human_facts", _pada_na_drugiej)
    with pytest.raises(ValueError) as exc:
        supersede.transfer_gesture(con, frame_ids=[a, c], now=NOW)
    assert (exc.value.przeniesienie.done, exc.value.przeniesienie.frame_ids) == (1, (a,))
    assert con.execute("SELECT object_id FROM frame WHERE id=?", (b,)).fetchone()[0] == oid


def test_inny_blad_klingi_przy_zgaszonym_ogniwie_dalej_leci(monkeypatch):
    """Klinga rzuca ZWYKŁY `ValueError`, a skan zdążył zgasić ogniwo tej klatki: gest nie ma prawa
    przepisać błędu na powód „przestała być zastąpiona". Łapany jest wyłącznie
    `repo.KlatkaNieJestZastapiona`. Falsyfikator: wróć do `except ValueError` + ponownego odczytu."""
    con = _baza()
    oid, a, b, c, d = _dwie_pary_z_obiektem(con)

    def _gasi_i_pada(con, *, frame_id, now, actor):
        repo.clear_superseded(con, frame_id=frame_id, now=now)
        raise ValueError("frame:999 (następczyni) nie istnieje")
    monkeypatch.setattr(repo, "transfer_human_facts", _gasi_i_pada)
    with pytest.raises(ValueError, match="następczyni"):
        supersede.transfer_gesture(con, frame_ids=[a], now=NOW)


def test_klinga_rzuca_wlasny_typ_dla_klatki_niezastapionej():
    con = _baza()
    a = _klatka(con, "a")
    with pytest.raises(repo.KlatkaNieJestZastapiona):
        repo.transfer_human_facts(con, frame_id=a, now=NOW)


def test_klucze_zdania_przeniesienia_sa_w_katalogu():
    """Bramka call-site katalogu skanuje `gui/` i `filter_engine.py`; `supersede.py` mówi do UI
    także kluczami dynamicznymi (oś, powód pominięcia) - oba rodzaje sprawdzamy tu wprost."""
    drzewo = ast.parse(Path(supersede.__file__).read_text(encoding="utf-8"))
    literalne = {n.args[0].value for n in ast.walk(drzewo)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("t", "t_plural") and n.args
                 and isinstance(n.args[0], ast.Constant)}
    dynamiczne = ({f"supersede.transfer.axis_{k}" for k in ("object", "config", "site", "lineage")}
                  | {f"supersede.transfer.skip_{s}" for s in supersede._POWODY_POMINIECIA.values()
                     if s is not None})
    assert literalne and literalne <= set(CATALOG)
    assert dynamiczne <= set(CATALOG)


@pytest.mark.parametrize("n, forma", [(1, "one"), (2, "few"), (4, "few"), (5, "many"),
                                      (12, "many"), (13, "many"), (14, "many"), (22, "few"),
                                      (25, "many")])
def test_odmiana_polska_nowych_kluczy_takze_nascie(n, forma):
    """Odmiana po polsku, z -naście (12-14 zawsze „many") i 22 („few") - każdy nowy klucz mnogi."""
    i18n.set_lang("pl")
    for klucz in ("grid.cell.macro_blocked", "supersede.transfer.done",
                  "supersede.transfer.object_kept", "supersede.transfer.lineage_dropped",
                  "supersede.transfer.skip_own", "supersede.transfer.skip_config_mismatch",
                  "supersede.transfer.skip_none", "supersede.transfer.not_superseded",
                  "supersede.transfer.no_longer_superseded"):
        oczekiwane = CATALOG[klucz]["pl"][forma].format(n=n, done=0)
        assert i18n.t_plural(klucz, n, done=0) == oczekiwane, klucz
    assert i18n.t_plural("supersede.transfer.skip_none", 13) == ". 13 klatek bez faktów ręki"
    assert i18n.t_plural("supersede.transfer.skip_none", 22) == ". 22 klatki bez faktów ręki"


# ---------------------------------------------------------------- AR-61: edycja komórki

def _cel(**kw):
    """Wiersz `queries.writeback_frame_targets` jednej klatki z jedną obecną kopią."""
    w = {"frame_id": 1, "filetype": "fits", "sha1_data_uncomputable": 0, "location_id": 7,
         "path": "/a/f1.fits", "header_hash": "hh", "hdu_index": 0, "compressed": 0}
    w.update(kw)
    return w


_KARTY = [{"keyword": "TELESCOP", "idx": 0, "value_raw": "RC8", "value_num": None,
           "value_type": "str", "comment": None}]


def test_plan_edycji_komorki_ma_ksztalt_wpisu_makra():
    """Cel i zmiana z bramek makra: kopia, kotwica `header_hash`, typ karty, komentarz z pola."""
    pv, powod = macro.plan_manual_change([_cel()], "TELESCOP", "EQ6", comment="  krotki ",
                                         cards_fn=lambda lid: _KARTY)
    assert powod is None
    assert (pv.location_id, pv.keyword, pv.op, pv.idx, pv.old_value, pv.new_value, pv.new_type,
            pv.comment, pv.expected_header_hash) == (7, "TELESCOP", "set", 0, "RC8", "EQ6", "str",
                                                     "krotki", "hh")


@pytest.mark.parametrize("wiersze, kawalek", [
    ([_cel(filetype="raw")], "RAW"),
    ([_cel(), _cel(location_id=8)], "wiele obecnych kopii"),
    ([_cel(compressed=1)], "skompresowany"),
    ([_cel(header_hash=None)], "header_hash"),
    ([], "nieobecny"),
])
def test_plan_edycji_komorki_odmawia_tam_gdzie_makro(wiersze, kawalek):
    """Komórka nie obiecuje niczego, czego makro na tej samej klatce by nie zrobiło."""
    pv, powod = macro.plan_manual_change(wiersze, "TELESCOP", "EQ6", cards_fn=lambda lid: _KARTY)
    assert pv is None and kawalek in powod


def test_komentarz_edycji_liczy_sie_w_regulach_karty():
    """Komentarz z polskim znakiem łamie regułę znaków FITS - odmowa w podglądzie, nie przy commicie
    (AR-9), tak samo jak w makrze. Pusty komentarz = zastany zostaje (None)."""
    zla = macro.evaluate_manual_change(_KARTY, "TELESCOP", "EQ6", comment="zażółć")
    assert not zla.ok and "komentarz" in zla.reason
    dobra = macro.evaluate_manual_change(_KARTY, "TELESCOP", "EQ6", comment="   ")
    assert dobra.ok and dobra.comment is None


def test_druga_edycja_tej_samej_karty_zastepuje_pierwsza():
    """Klinga stagingu edycji: ta sama karta tej samej kopii w tym samym przebiegu - jeden wpis.
    Inna karta - drugi wpis. Wpis rozstrzygnięty (`applied`) nie jest ruszany."""
    con = _baza()
    fid = _klatka(con, "a")
    lid = repo.add_location(con, frame_id=fid, volume="V", path="/a/f1.fits", now=NOW)[0]
    pv, _ = macro.plan_manual_change([_cel(location_id=lid)], "TELESCOP", "EQ6",
                                     cards_fn=lambda _l: _KARTY)
    assert repo.stage_pending_replacing(con, run_id="r1", preview=pv)[1] == 0
    pv2, _ = macro.plan_manual_change([_cel(location_id=lid)], "TELESCOP", "EQ8",
                                      cards_fn=lambda _l: _KARTY)
    _id2, zastapione = repo.stage_pending_replacing(con, run_id="r1", preview=pv2)
    assert zastapione == 1
    wpisy = writeback.pending_for_run(con, "r1")
    assert [(w["keyword"], w["new_value"], w["status"]) for w in wpisy] == [
        ("TELESCOP", "EQ8", "pending")]
    repo.set_pending_status(con, pending_id=_id2, status="applied")
    pv3, _ = macro.plan_manual_change([_cel(location_id=lid)], "TELESCOP", "EQ9",
                                      cards_fn=lambda _l: _KARTY)
    assert repo.stage_pending_replacing(con, run_id="r1", preview=pv3)[1] == 0
    assert [w["status"] for w in writeback.pending_for_run(con, "r1")] == ["applied", "pending"]
