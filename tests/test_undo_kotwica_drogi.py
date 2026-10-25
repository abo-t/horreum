"""Kotwica odtworzenia obiektu po cofnięciu commitu kart na KAŻDEJ drodze zapisu (AR-319): znacznik
`header.card_applied` z parą (commit, plik) przy każdym przejściu wpisu `OBJECT` w 'applied'.

Co pilnujemy:
  * drogi bez re-syncu pisarza: śmierć po podmianie + skan + rekoncyliacja backupu (`_potwierdz_z_dysku`),
    re-sync padł + skan potwierdzający, zapis wstrzymany + „Ta kopia prowadzi” - „Rozwiąż”, cofnięcie,
    klatka wraca do stanu sprzed zapisu, spis ręki bez ubytku;
  * „Rozwiąż” PRZED późnym rozliczeniem: klatka zostaje i zdanie ją liczy (`objects_kept`);
  * decyzja ręki między zapisem a rozliczeniem zostaje po cofnięciu (spis ręki po decyzji = po cofnięciu);
  * znacznik zwykłego zapisu (atomowo, w miejscu): jeden na plik, aktor `writeback`, poza gestem ręki Domu;
  * zapis wstrzymany znacznika nie dostaje; EXPECT pary (lokacja innej klatki → odmowa, zero zdarzeń);
  * dowód sprzed znacznika (para w `header.refreshed`) dalej jest kotwicą.
Pliki prawdziwe (astropy) w `tmp_path`."""
from __future__ import annotations

import json
import shutil

import pytest

from horreum import db, lead_copy, repo, resolver, scan, writeback
from horreum.gui import queries
from test_undo_obiekt_karty import INPLACE, NOW, _karta, _plik, _skan, _spis_reki, _stan


class _Smierc(BaseException):
    """Śmierć procesu w punkcie wstrzyknięcia - przechodzi przez każde `except Exception` pisarza."""


def _znaczniki(con):
    return [(r["actor"], r["target"], json.loads(r["payload"])) for r in con.execute(
        "SELECT actor, target, payload FROM event WHERE verb = ? ORDER BY id",
        (repo.ZNACZNIK_ZAPISU_KARTY,))]


def _baza(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path)
    loc = _skan(con, p)
    return con, p, loc


def _smierc_po_podmianie(monkeypatch):
    prawdziwy = writeback._podmien

    def _f(tmp, path, replace_guard, odcisk, po_podmianie=None, **kw):
        prawdziwy(tmp, path, replace_guard, odcisk, None, **kw)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)


def _reka(con, fid):
    """Decyzja ręki: obiekt `COS` przypisany jawnie (źródło ręki)."""
    g = repo.user_assign_object(con, alias_norm=None, canon="COS", catalog=None, kind="own",
                                frame_ids=[fid], now=NOW)
    assert g.assigned == 1, g


def _droga_b(con, p, loc, monkeypatch, *, reka=None, rozwiaz_przed=False):
    """Śmierć po podmianie → skan (zeznanie bez pary) → [ręka] → [„Rozwiąż”] → rekoncyliacja następnym
    commitem (`_potwierdz_z_dysku`; re-sync nie widzi zmiany nagłówka)."""
    _karta(con, "R", loc["id"], "NGC 7635")
    _smierc_po_podmianie(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW, inplace=False)
    monkeypatch.undo()
    _skan(con, p)
    if reka is not None:
        reka()
    if rozwiaz_przed:
        resolver.run_resolver(con, NOW)
    assert con.execute("SELECT status FROM pending_changes").fetchone()[0] != "applied"
    writeback.commit(con, "R", now=NOW, inplace=False)
    assert con.execute("SELECT status, reason_code FROM pending_changes").fetchone()[:] == \
        ("applied", "confirmed_from_disk_cut")
    return con.execute("SELECT max(commit_id) FROM header_backups").fetchone()[0]


def _droga_c(con, p, loc, monkeypatch, *, reka=None):
    """Re-sync zapisu atomowego pada → [ręka] → skan potwierdza commit (`confirm_failed_commit_by_scan`)."""
    _karta(con, "R", loc["id"], "NGC 7635")

    def _pada(*a, **kw):
        raise OSError(5, "zerwany udział")
    monkeypatch.setattr(writeback, "_resync", _pada)
    c = writeback.commit(con, "R", now=NOW, inplace=False)
    monkeypatch.undo()
    assert len(c.failed) == 1, c
    if reka is not None:
        reka()
    _skan(con, p)
    assert con.execute("SELECT status, reason_code FROM pending_changes").fetchone()[:] == \
        ("applied", "confirmed_by_scan")
    return c.commit_id


def _droga_wstrzymania(con, p, loc, tmp_path, *, inplace=False, reka=None):
    """Druga kopia wjeżdża po stagingu → zapis wstrzymany → [ręka] → „Ta kopia prowadzi” na kopii zapisu
    (`_settle_withheld_tx` → `completed`)."""
    _karta(con, "R", loc["id"], "NGC 7635")
    m = tmp_path / "B" / p.name
    m.parent.mkdir(parents=True)
    shutil.copyfile(p, m)
    _skan(con, m)
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    assert len(c.withheld) == 1, c
    if reka is not None:
        reka()
    assert lead_copy.lead_copy_gesture(con, loc["id"], NOW).verdict == "adopted"
    assert con.execute("SELECT settled_how FROM withheld_write").fetchone()[0] == "completed"
    return c.commit_id


DROGI = pytest.mark.parametrize("droga", ["skan_rekoncyliacja", "skan_potwierdza", "wstrzymanie"])


def _przez(droga, con, p, loc, monkeypatch, tmp_path, **kw):
    if droga == "skan_rekoncyliacja":
        return _droga_b(con, p, loc, monkeypatch, **kw)
    if droga == "skan_potwierdza":
        return _droga_c(con, p, loc, monkeypatch, **kw)
    return _droga_wstrzymania(con, p, loc, tmp_path, **kw)


# ============================================================ drogi bez re-syncu pisarza


@DROGI
def test_kotwica_na_drodze_bez_resyncu_odtwarza_obiekt(tmp_path, monkeypatch, droga):
    """Zapis karty przeszedł w 'applied' drogą inną niż re-sync pisarza: znacznik z parą (commit, plik)
    stoi, „Rozwiąż” przypisuje obiekt z karty, cofnięcie oddaje klatkę do stanu sprzed zapisu (bez
    obiektu), klatka policzona jako powrót, spis ręki sprzed zapisu bez ubytku (kod 0). Falsyfikatory:
    znacznik zdjęty z `settle_backup_attempt` / `confirm_failed_commit_by_scan` / `_settle_withheld_tx`."""
    con, p, loc = _baza(tmp_path)
    fid = loc["frame_id"]
    odniesienie = _spis_reki(str(tmp_path / "h.db"))
    cid = _przez(droga, con, p, loc, monkeypatch, tmp_path)
    assert [(a, t, (z["commit_id"], z["location_id"])) for a, t, z in _znaczniki(con)] == \
        [("writeback", f"frame:{fid}", (cid, loc["id"]))]
    resolver.run_resolver(con, NOW)
    assert _stan(con, fid) == ("NGC7635", "header", None)
    u = writeback.undo(con, cid, now=NOW)
    assert u.complete and u.objects_restored == (fid,) and u.objects_kept == (), u
    assert _stan(con, fid) == (None, None, None)
    con.close()
    assert _spis_reki(str(tmp_path / "h.db"), odniesienie) == 0


def test_rozwiaz_przed_rekoncyliacja_klatka_zostaje_policzona(tmp_path, monkeypatch):
    """Podmiana, śmierć, skan, „Rozwiąż”, rekoncyliacja, cofnięcie: przypisanie z karty wyprzedziło
    znacznik, więc obiektu nie odtwarzamy (kotwica od zdarzenia zeznania - rejestr), ale klatka przy obiekcie
    ze źródłem `header`, którego nagłówek po cofnięciu nie mówi, jest liczona jako „zostaje”. Falsyfikator:
    brak reguły „bez zdarzenia osi po kotwicy” - `objects_kept == ()`, zdanie milczy."""
    con, p, loc = _baza(tmp_path)
    fid = loc["frame_id"]
    cid = _droga_b(con, p, loc, monkeypatch, rozwiaz_przed=True)
    assert _stan(con, fid) == ("NGC7635", "header", None)
    u = writeback.undo(con, cid, now=NOW)
    assert u.complete and u.objects_restored == () and u.objects_kept == (fid,), u
    assert _stan(con, fid) == ("NGC7635", "header", None)
    con.close()


@DROGI
def test_decyzja_reki_miedzy_zapisem_a_rozliczeniem_zostaje(tmp_path, monkeypatch, droga):
    """Człowiek przypisuje obiekt ręką MIĘDZY zapisem karty a jego rozliczeniem (skan, rekoncyliacja,
    dokończenie wstrzymania). Spis ręki po tej decyzji = spis po rozliczeniu, „Rozwiąż” i cofnięciu (kod 0);
    klatka zostaje przy obiekcie ręki, zdanie wyniku o obiekcie nie mówi (karta niczego w osi nie zmieniła)."""
    con, p, loc = _baza(tmp_path)
    fid = loc["frame_id"]
    spis = {}

    def _decyzja():
        _reka(con, fid)
        spis["po_decyzji"] = _spis_reki(str(tmp_path / "h.db"))
    cid = _przez(droga, con, p, loc, monkeypatch, tmp_path, reka=_decyzja)
    resolver.run_resolver(con, NOW)
    u = writeback.undo(con, cid, now=NOW)
    assert u.complete and len(u.restored) == 1, u
    assert u.objects_restored == () and u.objects_kept == (), u
    assert _stan(con, fid)[0] == "COS"
    con.close()
    assert _spis_reki(str(tmp_path / "h.db"), spis["po_decyzji"]) == 0


# ============================================================ znacznik zwykłego zapisu, wstrzymanie, EXPECT


@INPLACE
def test_znacznik_zwyklego_zapisu_jeden_na_plik_poza_gestem_reki(tmp_path, inplace):
    """Zwykły zapis karty (re-sync pisarza): jeden znacznik z parą (commit, plik) na klatkę, aktor
    `writeback` - ostatni gest ręki Domu (`queries.last_hand_gesture`) go nie liczy. Falsyfikatory:
    znacznik zdjęty z `clear_tombstone_after_write` (atomowo) / z `finish_inplace_op` (w miejscu)."""
    con, _p, loc = _baza(tmp_path)
    _karta(con, "R", loc["id"], "NGC 7635")
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    assert len(c.applied) == 1 and bool(c.in_place) == inplace, c
    assert [(a, t, (z["commit_id"], z["location_id"])) for a, t, z in _znaczniki(con)] == \
        [("writeback", f"frame:{loc['frame_id']}", (c.commit_id, loc["id"]))]
    gest = queries.last_hand_gesture(con)
    assert gest is None or repo.ZNACZNIK_ZAPISU_KARTY not in gest["verbs"], gest
    con.close()


def test_zapis_wstrzymany_bez_znacznika(tmp_path):
    """Zapis wstrzymany (zeznanie przy innej kopii) to nie 'applied' - znacznika nie ma, dopóki zapis się
    nie dokończy."""
    con, p, loc = _baza(tmp_path)
    _karta(con, "R", loc["id"], "NGC 7635")
    m = tmp_path / "B" / p.name
    m.parent.mkdir(parents=True)
    shutil.copyfile(p, m)
    _skan(con, m)
    assert len(writeback.commit(con, "R", now=NOW, inplace=False).withheld) == 1
    assert _znaczniki(con) == []
    con.close()


def test_znacznik_odmawia_lokacji_innej_klatki(tmp_path):
    """EXPECT pary: lokacja `location_id` innej klatki niż `frame_id` - `ValueError`, zero zdarzeń."""
    con = db.open_db(str(tmp_path / "h.db"))
    a = _skan(con, _plik(tmp_path, "NGC7635_a.fits", seed=1))
    b = _skan(con, _plik(tmp_path, "NGC7635_b.fits", seed=2))
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    with pytest.raises(ValueError, match="nie należy do klatki"):
        with repo.atomic(con):
            repo._zapis_karty_obiektu_tx(con, frame_id=a["frame_id"], hand_version=0, commit_id=1,
                                         location_id=b["id"], now=NOW, actor="user:local")
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    con.close()


# ============================================================ dowód sprzed znacznika


@INPLACE
def test_para_w_header_refreshed_sprzed_znacznika_jest_kotwica(tmp_path, inplace):
    """Baza zapisana kodem, który niósł parę (commit, plik) w `header.refreshed` re-syncu, a znacznika nie
    znał (emulacja: znacznik zamieniony w bazie testu na tamten kształt): po „Rozwiąż” cofnięcie odtwarza
    obiekt. Falsyfikator: kotwica czyta wyłącznie znacznik."""
    con, _p, loc = _baza(tmp_path)
    fid = loc["frame_id"]
    _karta(con, "R", loc["id"], "NGC 7635")
    c = writeback.commit(con, "R", now=NOW, inplace=inplace)
    ostatnie = con.execute("SELECT max(id) FROM event WHERE target = ? AND verb = 'header.refreshed'",
                           (f"frame:{fid}",)).fetchone()[0]
    con.execute("UPDATE event SET payload = json_set(payload, '$.commit_id', ?, '$.location_id', ?) "
                "WHERE id = ?", (c.commit_id, loc["id"], ostatnie))
    con.execute("DELETE FROM event WHERE verb = ?", (repo.ZNACZNIK_ZAPISU_KARTY,))
    con.commit()
    resolver.run_resolver(con, NOW)
    u = writeback.undo(con, c.commit_id, now=NOW)
    assert u.objects_restored == (fid,), u
    assert _stan(con, fid) == (None, None, None)
    con.close()


def test_scan_ingest_bez_parametru_pary():
    """Para pochodzenia nie jedzie już przez wjazd rekordu skanu - jedna reguła (znacznik)."""
    import inspect
    assert "zapis_commitu" not in inspect.signature(scan.ingest_record).parameters
    assert "zapis_commitu" not in inspect.signature(repo.refresh_location).parameters
