r"""ZAPIS GESTU „Zmień obiekt…” (AR-17 krok 3, D-1011-5) - klinga ręki dla lightów i stosów, staging
przebiegu, sterownik `writeback.commit_object_change` (baza → przeniesienie → karta per pozycja, razem
albo wcale) i cofnięcie `writeback.undo_object_change` (karta → plik → baza, faza w bazie), katalogi
gestu w `run_dir`.

Pliki FITS, XISF i RAW-atrapa w `tmp_path`; plan budowany ręcznie z dataclass kontraktu
(`horreum.object_change`), nie planerem - te testy pytają o zapis, nie o regułę celu. Awarie procesu
symuluje wyjątek spoza `Exception` (`_Smierc`): przechodzi przez wszystkie obrony warstwy zapisu tak,
jak przeszłaby śmierć procesu, a ponowne wywołanie sterownika odtwarza przebieg wyłącznie z bazy.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import audit, db, repo, scan, writeback
from horreum import object_change as oc
from test_exif import build_raw

NOW = "2026-10-11T12:00:00+00:00"
KOMENTARZ = "Name of the object of interest"


class _Smierc(BaseException):
    """Śmierć procesu w środku przebiegu: nie łapie jej żadne `except Exception` warstwy zapisu."""


# ============================================================ pliki i baza


def _fits(path, obj="Sh2-229", seed=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=(np.arange(64, dtype=np.int16).reshape(8, 8) + seed).astype(np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = (obj, KOMENTARZ)
    hdu.writeto(path)
    return path


def _xisf(path, obj="Sh2-229", seed=2, pad=64):
    """Monolityczny XISF z rezerwą `pad` po XML (zapis karty w miejscu) i danymi zależnymi od `seed`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = bytes([seed]) * 32

    def body(start):
        kw = (f'<FITSKeyword name="IMAGETYP" value="\'Light\'" comment=""/>'
              f'<FITSKeyword name="OBJECT" value="\'{obj}\'" comment="nazwa obiektu"/>')
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{start:08d}:{len(payload)}">{kw}</Image></xisf>').encode("utf-8")
    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    path.write_bytes(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + b"\x00" * pad
                     + payload)
    return path


def _raw(path, dto="2019:02:25 01:01:09"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_raw(dto=dto))
    return path


def _sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _wczytaj(con, path):
    rec = scan.scan_file(str(path))
    scan.ingest_record(con, rec, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=repo.ZEWNETRZNE)


def _wiersz(con, path):
    return con.execute(
        "SELECT l.id, l.frame_id, l.header_hash, l.mtime, l.path, f.object_id, f.object_source, "
        "       f.object_cleared_id "
        "FROM location l JOIN frame f ON f.id = l.frame_id WHERE l.path = ?", (str(path),)).fetchone()


def _oid(con, canon):
    r = con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()
    return None if r is None else r[0]


def _ev(con):
    return con.execute("SELECT count(*) FROM event").fetchone()[0]


def _bilans_osi(con):
    [p] = [p for p in audit.entity_event_parity(con) if p.name == "frame.object_id"]
    return p.ok


def _karta(path):
    return {c.keyword: c.value_raw for c in scan.scan_file(str(path)).cards or []}.get("OBJECT")


class _Scena:
    """LIGHTS\\Sh2-229\\RC8 z trzema plikami (FITS, XISF, RAW) obiektu `Sh2-229` (FITS i XISF ze
    źródła `header`, RAW ze ścieżki) - gest zmienia obiekt na IC405 i przenosi pliki do
    LIGHTS\\IC405\\RC8 z nową nazwą (jeden `os.rename` zmienia folder i nazwę)."""

    def __init__(self, tmp_path, *, obj_pliku="Sh2-229", obj_bazy="Sh2-229", dodatkowy=False):
        self.root = tmp_path / "LIGHTS"
        self.zrodlo = self.root / "Sh2-229" / "RC8"
        self.cel = self.root / "IC405" / "RC8"
        self.stare = [_fits(self.zrodlo / "a.fits", obj=obj_pliku),
                      _xisf(self.zrodlo / "b.xisf", obj=obj_pliku),
                      _raw(self.zrodlo / "c.dng")]
        if dodatkowy:
            _fits(self.zrodlo / "obcy.fits", obj=obj_pliku, seed=9)
        self.nowe = [self.cel / f"IC405_{p.name}" for p in self.stare]
        self.con = db.open_db(str(tmp_path / "h.db"))
        for p in self.stare:
            _wczytaj(self.con, p)
        obj, _ = repo.upsert_object(self.con, canon=obj_bazy, catalog=obj_bazy[:2], kind="deep_sky",
                                    now=NOW)
        for p in self.stare:
            w = _wiersz(self.con, p)
            repo.assign_object(self.con, frame_id=w["frame_id"], object_id=obj,
                               object_source="path" if p.suffix == ".dng" else "header", now=NOW)
        self.sha1 = [_sha1(p) for p in self.stare]
        self.ino = [os.stat(p).st_ino for p in self.stare]

    def pozycja(self, i, *, karta=True, object_change=True, nowa=True):
        w = _wiersz(self.con, self.stare[i])
        z_karta = karta and self.stare[i].suffix != ".dng"
        return oc.ObjectChangeItem(
            frame_id=w["frame_id"], location_id=w["id"], old_path=str(self.stare[i]),
            new_path=str(self.nowe[i]) if nowa else None,
            mkdirs=(str(self.root / "IC405"), str(self.cel)) if nowa else (),
            card_op="set" if z_karta else None, card_old="Sh2-229" if z_karta else None,
            card_new="IC 405" if z_karta else None,
            expected_header_hash=w["header_hash"] if z_karta else None, expected_mtime=w["mtime"],
            expected_object=(w["object_id"], w["object_source"], w["object_cleared_id"]),
            object_change=object_change)

    def plan(self, run_id="R1", *, cel=True, pozycje=None):
        target = oc.ObjectTarget(canon="IC405", catalog="IC", kind="deep_sky", alias_norm=None,
                                 card_form="IC 405") if cel else None
        items = tuple(pozycje if pozycje is not None else (self.pozycja(i) for i in range(3)))
        return oc.ObjectChangePlan(run_id=run_id, target=target, items=items, skipped=())

    def stage(self, plan):
        repo.stage_object_change(self.con, plan=plan, now=NOW)
        return plan.run_id


def _pozycje(con, run_id="R1"):
    return con.execute("SELECT * FROM pending_object_change WHERE run_id = ? ORDER BY id",
                       (run_id,)).fetchall()


def _katalogi(con, run_id="R1"):
    return {(Path(r["path"]).name, r["action"]): (r["done_at"] is not None, r["undone_at"] is not None)
            for r in con.execute("SELECT * FROM run_dir WHERE run_id = ?", (run_id,))}


# ============================================================ cykl zapis → cofnięcie → ponowienie


def test_cykl_zapis_cofniecie_ponowienie_bajt_w_bajt(tmp_path):
    """Pełny cykl na trzech formatach: baza dostaje IC405 ręką (para verbów `object_change`), pliki
    przechodzą do LIGHTS\\IC405\\RC8 z nową nazwą (`st_ino` bez zmian), karta FITS/XISF = `IC 405`
    zapisana w miejscu, RAW sam ruch; katalogi celu założone i zapisane, źródłowe opróżnione usunięte.
    Cofnięcie: CAŁY plik wraca bajt w bajt (sha1), stary katalog odtworzony, założone usunięte, baza
    do stanu sprzed; drugie cofnięcie = nic; nowy gest na tym samym materiale przechodzi znowu."""
    s = _Scena(tmp_path)
    con = s.con
    sh2 = _oid(con, "Sh2-229")
    run = s.stage(s.plan())
    postep = []
    wynik = writeback.commit_object_change(con, run, now=NOW,
                                           progress=lambda *a: postep.append(a))
    assert (len(wynik.applied), wynik.blocked, wynik.failed, wynik.skipped) == (3, [], [], [])
    assert [a[:2] for a in postep] == [(1, 3), (2, 3), (3, 3)]
    ic = _oid(con, "IC405")
    assert ic is not None and _bilans_osi(con)
    for i, nowa in enumerate(s.nowe):
        assert nowa.exists() and not s.stare[i].exists()
        assert os.stat(nowa).st_ino == s.ino[i]                     # rename nie podmienia pliku
        w = _wiersz(con, nowa)
        assert (w["object_id"], w["object_source"], w["object_cleared_id"]) == (ic, "user", None)
    assert _karta(s.nowe[0]) == "IC 405" and _karta(s.nowe[1]) == "IC 405"
    assert con.execute("SELECT count(*) FROM inplace_op WHERE kind = 'commit' AND phase = 'synced'"
                       ).fetchone()[0] == 2                          # karta W MIEJSCU (AR-117)
    assert not (tmp_path / "LIGHTS" / "Sh2-229").exists()           # źródło opróżnione - usunięte
    assert (wynik.dirs_created, wynik.dirs_removed, wynik.dirs_uncertain) == (2, 2, 0)
    assert len(wynik.commit_ids) == 1 and not wynik.warnings
    assert _katalogi(con) == {("IC405", "created"): (True, False), ("RC8", "created"): (True, False),
                              ("Sh2-229", "removed"): (True, False), ("RC8", "removed"): (True, False)}
    assert {r["status"] for r in _pozycje(con)} == {"applied"}
    powody = [json.loads(r[0]).get("reason") for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'location.renamed' ORDER BY id")]
    assert powody == ["object_change"] * 3
    przypisania = [json.loads(r[0]) for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'object.assigned' AND actor = 'user:local'")]
    assert {p["reason"] for p in przypisania} == {"object_change"}
    assert con.execute("SELECT status FROM object_change_run").fetchone()[0] == "applied"

    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert (len(cofniecie.applied), cofniecie.blocked, cofniecie.failed) == (3, [], [])
    assert {r.status for r in cofniecie.applied} == {"restored"}
    assert con.execute("SELECT count(*) FROM inplace_op WHERE kind = 'undo' AND phase = 'synced'"
                       ).fetchone()[0] == 2                          # karta wróciła w miejscu
    for i, stara in enumerate(s.stare):
        assert stara.exists() and not s.nowe[i].exists()
        assert _sha1(stara) == s.sha1[i] and os.stat(stara).st_ino == s.ino[i]
        w = _wiersz(con, stara)
        zrodlo = "path" if stara.suffix == ".dng" else "header"
        assert (w["object_id"], w["object_source"], w["object_cleared_id"]) == (sh2, zrodlo, None)
    assert not (tmp_path / "LIGHTS" / "IC405").exists()             # założone przez gest - usunięte
    assert (cofniecie.dirs_created, cofniecie.dirs_removed, cofniecie.dirs_uncertain) == (2, 2, 0)
    assert _bilans_osi(con)
    assert {(r["status"], r["undo_phase"]) for r in _pozycje(con)} == {("undone", "db")}
    assert con.execute("SELECT status FROM object_change_run").fetchone()[0] == "undone"
    powody = [json.loads(r[0]).get("reason") for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'location.renamed' ORDER BY id")]
    assert powody == ["object_change"] * 3 + ["object_change_undo"] * 3

    przed = _ev(con)
    drugie = writeback.undo_object_change(con, run, now=NOW)
    assert (drugie.applied, drugie.blocked, drugie.failed, drugie.skipped) == ([], [], [], [])
    assert (drugie.dirs_created, drugie.dirs_removed) == (0, 0) and _ev(con) == przed
    with pytest.raises(ValueError, match="cofnięty"):
        writeback.commit_object_change(con, run, now=NOW)

    ponownie = writeback.commit_object_change(con, s.stage(s.plan("R2")), now=NOW)
    assert len(ponownie.applied) == 3 and all(p.exists() for p in s.nowe)
    assert _karta(s.nowe[0]) == "IC 405" and _bilans_osi(con)


def test_katalog_zrodlowy_z_innym_plikiem_zostaje(tmp_path):
    """Gest opróżnia katalog źródłowy tylko częściowo (w folderze leży plik spoza gestu): katalog
    zostaje, wiersza `removed` nie ma, a cofnięcie nie musi niczego odtwarzać."""
    s = _Scena(tmp_path, dodatkowy=True)
    run = s.stage(s.plan())
    wynik = writeback.commit_object_change(s.con, run, now=NOW)
    assert len(wynik.applied) == 3 and wynik.dirs_removed == 0
    assert (s.zrodlo / "obcy.fits").exists()
    assert ("RC8", "removed") not in _katalogi(s.con)
    cofniecie = writeback.undo_object_change(s.con, run, now=NOW)
    assert len(cofniecie.applied) == 3 and cofniecie.dirs_created == 0
    assert all(_sha1(p) == h for p, h in zip(s.stare, s.sha1))


# ============================================================ razem albo wcale, dryf, kotwice


def test_karta_odbita_bez_zapisu_plik_wraca_a_baza_do_stanu_sprzed(tmp_path):
    """Karta odbita przez pisarza BEZ zapisu (wartość spoza ASCII - reguły karty): przeniesiony plik
    wraca pod starą ścieżkę, baza przez CAS do stanu sprzed, pozycja 'blocked' z powodem pisarza;
    katalogi celu, które przeniesienie założyło, są puste i giną na końcu przebiegu."""
    s = _Scena(tmp_path)
    con = s.con
    sh2 = _oid(con, "Sh2-229")
    pozycja = s.pozycja(0)
    zla = oc.ObjectChangeItem(**{**pozycja.__dict__, "card_new": "IC 405\u0142"})
    run = s.stage(s.plan(pozycje=[zla]))
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert (wynik.applied, len(wynik.blocked)) == ([], 1)
    assert "karta odbita bez zapisu" in wynik.blocked[0].reason
    assert s.stare[0].exists() and _sha1(s.stare[0]) == s.sha1[0]
    w = _wiersz(con, s.stare[0])
    assert (w["object_id"], w["object_source"]) == (sh2, "header") and _bilans_osi(con)
    p = _pozycje(con)[0]
    assert (p["status"], p["object_id"], p["before_source"]) == ("blocked", None, None)
    assert con.execute("SELECT status FROM pending_renames").fetchone()[0] == "skipped"
    assert not (tmp_path / "LIGHTS" / "IC405").exists() and wynik.dirs_removed == 2
    assert _katalogi(con)[("IC405", "created")] == (True, True)
    # odmowa jest czysta - cofnięcie nie ma czego cofać, ale o pozycji mówi
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert (cofniecie.applied, cofniecie.blocked, cofniecie.failed) == ([], [], [])
    assert [r.reason for r in cofniecie.skipped] == ["odmówione przy zapisie - nic do cofnięcia"]
    assert s.stare[0].exists() and _sha1(s.stare[0]) == s.sha1[0]


def test_dryf_obiektu_pomija_pozycje_bez_ruchu_pliku(tmp_path):
    """Obiekt klatki zmieniony między podglądem a zapisem (CAS na trójcy): pozycja 'skipped', plik
    nietknięty, katalogi nie powstają, wpisy stagingu 'skipped', zero eventów obiektu."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    m42, _ = repo.upsert_object(con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=_wiersz(con, s.stare[0])["frame_id"], object_id=m42,
                       object_source="header", now=NOW)
    przed = _ev(con)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert (wynik.applied, len(wynik.skipped)) == ([], 1) and "dryf" in wynik.skipped[0].reason
    assert s.stare[0].exists() and not (tmp_path / "LIGHTS" / "IC405").exists()
    assert _ev(con) == przed and _oid(con, "IC405") is None          # pusty obiekt nie powstaje
    assert con.execute("SELECT status FROM pending_renames").fetchone()[0] == "skipped"
    assert {r[0] for r in con.execute("SELECT status FROM pending_changes")} == {"skipped"}


def test_uzgodnij_tez_pyta_o_stan_z_podgladu(tmp_path):
    """„Uzgodnij” (cel None) nie zmienia obiektu, ale plik dogania obiekt, który klatka miała
    w podglądzie: klatka z innym obiektem w chwili zapisu = dryf, plik zostaje."""
    s = _Scena(tmp_path, obj_pliku="IC 405", obj_bazy="IC405")
    con = s.con
    run = s.stage(s.plan(cel=False, pozycje=[s.pozycja(0, karta=False, object_change=False)]))
    m42, _ = repo.upsert_object(con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=_wiersz(con, s.stare[0])["frame_id"], object_id=m42,
                       object_source="header", now=NOW)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.skipped) == 1 and s.stare[0].exists()


def test_uzgodnij_przenosi_bez_zmiany_bazy_i_cofa_sie(tmp_path):
    """„Uzgodnij” (stan Sh2-229 → IC405 z pf4: karta i baza już IC 405, folder stary): sam ruch
    pliku, baza nietknięta (zero eventów osi), cofnięcie zwraca plik bajt w bajt."""
    s = _Scena(tmp_path, obj_pliku="IC 405", obj_bazy="IC405")
    con = s.con
    ic = _oid(con, "IC405")
    run = s.stage(s.plan(cel=False, pozycje=[s.pozycja(i, karta=False, object_change=False)
                                             for i in range(3)]))
    przed = con.execute("SELECT count(*) FROM event WHERE verb LIKE 'object.%'").fetchone()[0]
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.applied) == 3 and wynik.commit_ids == ()
    assert con.execute("SELECT count(*) FROM event WHERE verb LIKE 'object.%'").fetchone()[0] == przed
    assert {_wiersz(con, p)["object_id"] for p in s.nowe} == {ic}
    assert con.execute("SELECT mode FROM object_change_run").fetchone()[0] == "align"
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 3
    assert all(_sha1(p) == h for p, h in zip(s.stare, s.sha1))


def test_kopia_bez_kotwicy_mtime_blokuje_przeniesienie(tmp_path):
    """Kotwica `mtime` obowiązkowa: pozycja z `expected_mtime` NULL → 'blocked', plik nietknięty,
    baza nietknięta (bramka stoi przed krokiem bazy)."""
    s = _Scena(tmp_path)
    p = s.pozycja(2)
    run = s.stage(s.plan(pozycje=[oc.ObjectChangeItem(**{**p.__dict__, "expected_mtime": None})]))
    przed = _ev(s.con)
    wynik = writeback.commit_object_change(s.con, run, now=NOW)
    assert len(wynik.blocked) == 1 and "mtime" in wynik.blocked[0].reason
    assert s.stare[2].exists() and _ev(s.con) == przed


def test_anulowanie_przed_pozycja_zostawia_reszte_oczekujaca(tmp_path):
    """Anulowanie sprawdzane PRZED pozycją: po pierwszej reszta 'pending' i nietknięta, przebieg nie
    jest 'applied'; ponowne wywołanie dokańcza. Cofnięcie przebiegu przerwanego: pozycje bez śladu
    zapisu → 'skipped' bez mutacji, zapisane wracają."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan())
    pytania = iter([False, True])
    wynik = writeback.commit_object_change(con, run, now=NOW, should_cancel=lambda: next(pytania))
    assert wynik.cancelled and len(wynik.applied) == 1
    assert [r["status"] for r in _pozycje(con)] == ["applied", "pending", "pending"]
    assert s.stare[1].exists() and s.stare[2].exists()
    assert con.execute("SELECT status FROM object_change_run").fetchone()[0] == "staged"
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert (len(cofniecie.applied), len(cofniecie.skipped)) == (1, 2)
    assert [r["status"] for r in _pozycje(con)] == ["undone", "skipped", "skipped"]
    assert all(_sha1(p) == h for p, h in zip(s.stare, s.sha1))


# ============================================================ awarie w środku pozycji → ponowienie


def _smierc_po(monkeypatch, cel, nazwa, *, raz=True):
    """`cel.nazwa` wykonuje się naprawdę, a potem proces „ginie” (raz)."""
    prawdziwa = getattr(cel, nazwa)
    stan = {"padlo": False}

    def _po(*a, **kw):
        wynik = prawdziwa(*a, **kw)
        if not (raz and stan["padlo"]):
            stan["padlo"] = True
            raise _Smierc(nazwa)
        return wynik
    monkeypatch.setattr(cel, nazwa, _po)
    return prawdziwa


def test_smierc_po_mkdir_katalog_niepewny_nigdy_nie_usuwany(tmp_path, monkeypatch):
    """Proces ginie między `os.mkdir` a potwierdzeniem katalogu: baza pozycji już zmieniona, zamiar
    katalogu bez `done_at`. Ponowienie dokańcza pozycję (krok bazy się nie powtarza), a katalog
    o własności niepewnej NIGDY nie jest usuwany automatycznie - zostaje do oka i jest w raporcie."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    _smierc_po(monkeypatch, writeback.os, "mkdir")
    with pytest.raises(_Smierc):
        writeback.commit_object_change(con, run, now=NOW)
    monkeypatch.undo()
    p = _pozycje(con)[0]
    assert (p["status"], p["object_id"] is not None) == ("pending", True)
    assert _katalogi(con) == {("IC405", "created"): (False, False)}
    przypisania = con.execute("SELECT count(*) FROM event WHERE verb = 'object.assigned'").fetchone()[0]

    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.applied) == 1 and s.nowe[0].exists()
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'object.assigned'").fetchone()[0] \
        == przypisania                                               # krok bazy się nie powtórzył
    assert wynik.dirs_uncertain == 1 and any("IC405" in w for w in wynik.warnings)

    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 1 and _sha1(s.stare[0]) == s.sha1[0]
    assert not s.cel.exists()                                         # nasz (potwierdzony) - usunięty
    assert (tmp_path / "LIGHTS" / "IC405").is_dir()                   # niepewny - zostaje
    assert cofniecie.dirs_uncertain == 1 and _bilans_osi(con)


def test_smierc_po_os_rename_rekoncyliacja_przepina_i_ponowienie_konczy(tmp_path, monkeypatch):
    """Proces ginie po `os.rename`, przed przepięciem bazy (zamiar renamu otwarty): ponowienie
    rekoncyliuje zamiar (plik pod nową ścieżką = przeniesienie zaszło), dokańcza kartę, a cofnięcie
    zwraca plik bajt w bajt."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    _smierc_po(monkeypatch, writeback, "rename_file")
    with pytest.raises(_Smierc):
        writeback.commit_object_change(con, run, now=NOW)
    monkeypatch.undo()
    assert s.nowe[0].exists() and _wiersz(con, s.stare[0]) is not None    # baza pod starą ścieżką
    assert con.execute("SELECT in_flight FROM pending_renames").fetchone()[0] == "commit"

    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.applied) == 1 and _karta(s.nowe[0]) == "IC 405"
    assert _wiersz(con, s.nowe[0])["object_source"] == "user"
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 1 and _sha1(s.stare[0]) == s.sha1[0] and _bilans_osi(con)


def test_smierc_po_karcie_ponowienie_rozlicza_pozycje(tmp_path, monkeypatch):
    """Proces ginie po zapisie karty, przed rozliczeniem pozycji: ponowienie widzi kartę 'applied'
    i domyka pozycję bez drugiego zapisu; cofnięcie bierze commit tamtej próby."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(1)]))
    _smierc_po(monkeypatch, writeback, "_zapisz_lokacje")
    with pytest.raises(_Smierc):
        writeback.commit_object_change(con, run, now=NOW)
    monkeypatch.undo()
    assert _pozycje(con)[0]["status"] == "pending" and _karta(s.nowe[1]) == "IC 405"

    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.applied) == 1 and len(wynik.commit_ids) == 1
    assert con.execute("SELECT count(*) FROM inplace_op").fetchone()[0] == 1   # karta raz
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 1 and _sha1(s.stare[1]) == s.sha1[1]


def test_karta_rozdarta_plik_zostaje_a_cofniecie_czeka_na_odzysk(tmp_path, monkeypatch):
    """Karta zapisana w miejscu, ale weryfikacja po zapisie pada (zapis częściowy): pozycja 'failed',
    plik ZOSTAJE pod nową ścieżką (lokacja izolowana), powód niesie drogę naprawy. Cofnięcie
    zatrzymuje się na karcie z receptą odzysku; po `recover_torn` ponowienie domyka pozycję
    i zwraca plik bajt w bajt."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    prawdziwy = os.fsync

    def _fsync(fd):
        prawdziwy(fd)
        raise OSError(64, "The specified network name is no longer available")
    monkeypatch.setattr(writeback.os, "fsync", _fsync)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    monkeypatch.undo()
    assert len(wynik.failed) == 1 and f"„{writeback._GEST_PRZYWROC}”" in wynik.failed[0].reason
    assert wynik.failed[0].reason.startswith("karta zapisana częściowo")
    assert s.nowe[0].exists() and _pozycje(con)[0]["status"] == "failed"
    assert _wiersz(con, s.nowe[0])["object_source"] == "user"         # baza zostaje przy pliku

    stop = writeback.undo_object_change(con, run, now=NOW)
    assert len(stop.failed) == 1 and f"„{writeback._GEST_PRZYWROC}”" in stop.failed[0].reason
    assert s.nowe[0].exists() and _pozycje(con)[0]["undo_phase"] is None
    assert con.execute("SELECT status FROM object_change_run").fetchone()[0] == "undoing"
    with pytest.raises(ValueError, match="cofany"):
        writeback.commit_object_change(con, run, now=NOW)            # cofanego zapis nie wznawia
    [op] = con.execute("SELECT id FROM inplace_op WHERE phase = 'unverified'").fetchall()
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"

    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 1 and _sha1(s.stare[0]) == s.sha1[0] and _bilans_osi(con)
    assert con.execute("SELECT status FROM object_change_run").fetchone()[0] == "undone"


# ============================================================ klinga ręki i księgowość


def test_klinga_nadpisuje_light_z_naglowka_i_zaklada_obiekt_z_aliasem_przy_zapisie(tmp_path):
    """Uogólniona klinga dla `LIGHT_KINDS`: light ze źródłem `header` dostaje obiekt ręką; obiekt
    i alias wpisanej nazwy powstają W tej transakcji (nie przy stagingu), stan sprzed trafia do
    pozycji; powtórny krok = bez zapisu."""
    s = _Scena(tmp_path)
    con = s.con
    sh2 = _oid(con, "Sh2-229")
    plan = s.plan(pozycje=[s.pozycja(0)])
    plan = oc.ObjectChangePlan(plan.run_id, oc.ObjectTarget("IC405", "IC", "deep_sky", "flamingstar",
                                                            "IC 405"), plan.items, ())
    repo.stage_object_change(con, plan=plan, now=NOW)
    assert _oid(con, "IC405") is None                                # staging nie zakłada obiektu
    [p] = _pozycje(con)
    przed = _ev(con)
    assert repo.apply_object_change_item(con, item_id=p["id"], now=NOW) == "assigned"
    ic = _oid(con, "IC405")
    verby = [r[0] for r in con.execute("SELECT verb FROM event WHERE id > ? ORDER BY id", (przed,))]
    assert verby == ["object.upserted", "object.aliased", "object.unassigned", "object.assigned"]
    assert con.execute("SELECT object_id FROM object_alias WHERE alias_norm = 'flamingstar'"
                       ).fetchone()[0] == ic
    [p] = _pozycje(con)
    assert (p["object_id"], p["before_object_id"], p["before_source"], p["before_cleared_id"]) == \
        (ic, sh2, "header", None)
    po = _ev(con)
    assert repo.apply_object_change_item(con, item_id=p["id"], now=NOW) == "assigned"
    assert _ev(con) == po and _bilans_osi(con)


def test_konflikt_aliasu_to_zero_zapisu(tmp_path):
    s = _Scena(tmp_path)
    con = s.con
    m42, _ = repo.upsert_object(con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="flamingstar", object_id=m42, source="user", now=NOW)
    plan = s.plan(pozycje=[s.pozycja(0)])
    plan = oc.ObjectChangePlan(plan.run_id, oc.ObjectTarget("IC405", "IC", "deep_sky", "flamingstar",
                                                            "IC 405"), plan.items, ())
    repo.stage_object_change(con, plan=plan, now=NOW)
    przed = _ev(con)
    wynik = writeback.commit_object_change(con, plan.run_id, now=NOW)
    assert len(wynik.blocked) == 1 and "konflikt" in wynik.blocked[0].reason
    assert _ev(con) == przed and _oid(con, "IC405") is None and s.stare[0].exists()


def test_klinga_odmawia_kalibracji_i_cel_bez_rodzaju(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (1, 'dark', 'fits', 'd1', ?), (2, 'light', 'fits', 'l2', ?)", (NOW, NOW))
    con.commit()
    for kw in ({"frame_id": 1, "kind": "deep_sky"}, {"frame_id": 2, "kind": None},
               {"frame_id": 2, "kind": "deep_sky", "alias_norm": ""}):
        with pytest.raises(ValueError):
            repo.user_override_object(con, canon="NGC1", expected=(None, None, None),
                                      reason="object_change", now=NOW, **kw)
    assert _ev(con) == 0 and _oid(con, "NGC1") is None
    assert repo.user_override_object(con, frame_id=2, canon="NGC1", kind="deep_sky",
                                     expected=(None, None, None), reason="object_change",
                                     now=NOW) == "assigned"


def test_staging_jedna_transakcja_i_bramki(tmp_path):
    """Staging pisze przebieg, pozycje, przeniesienia i karty jedną transakcją; EXPECT odbija plan
    sprzeczny z trybem, a drugi staging tego samego przebiegu łamie klucz."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan())
    assert con.execute("SELECT count(*) FROM pending_object_change").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM pending_renames WHERE run_id = ?", (run,)).fetchone()[0] == 3
    karty = con.execute("SELECT op, idx, old_value, new_value FROM pending_changes").fetchall()
    assert [tuple(k) for k in karty] == [("set", 0, "Sh2-229", "IC 405")] * 2   # RAW bez karty
    assert json.loads(_pozycje(con)[0]["mkdirs"]) == [str(tmp_path / "LIGHTS" / "IC405"), str(s.cel)]
    with pytest.raises(sqlite3.IntegrityError):
        s.stage(s.plan())
    bez_formy = oc.ObjectChangePlan("R3", oc.ObjectTarget("IC405", "IC", "deep_sky", None, None), (), ())
    zmiana_w_uzgodnij = s.plan("R4", cel=False, pozycje=[s.pozycja(0)])
    katalogi_bez_ruchu = s.plan("R5", pozycje=[oc.ObjectChangeItem(
        **{**s.pozycja(0).__dict__, "new_path": None})])
    obcy_katalog = s.plan("R6", pozycje=[oc.ObjectChangeItem(
        **{**s.pozycja(0).__dict__, "mkdirs": (str(tmp_path / "LIGHTS" / "M42"), str(s.cel))})])
    odwrotnie = s.plan("R7", pozycje=[oc.ObjectChangeItem(
        **{**s.pozycja(0).__dict__, "mkdirs": (str(s.cel), str(tmp_path / "LIGHTS" / "IC405"))})])
    for zly in (bez_formy, zmiana_w_uzgodnij, katalogi_bez_ruchu, obcy_katalog, odwrotnie):
        with pytest.raises(ValueError):
            repo.stage_object_change(con, plan=zly, now=NOW)
    assert con.execute("SELECT count(*) FROM object_change_run").fetchone()[0] == 1


def test_faza_cofniecia_tylko_po_kolei_i_baza_dopiero_po_pliku(tmp_path):
    s = _Scena(tmp_path)
    s.stage(s.plan(pozycje=[s.pozycja(0)]))
    [p] = _pozycje(s.con)
    with pytest.raises(ValueError):
        repo.set_object_change_undo_phase(s.con, item_id=p["id"], phase="file")
    with pytest.raises(ValueError):
        repo.undo_object_change_db(s.con, item_id=p["id"], now=NOW)
    repo.set_object_change_undo_phase(s.con, item_id=p["id"], phase="card")
    with pytest.raises(ValueError):
        repo.set_object_change_undo_phase(s.con, item_id=p["id"], phase="card")


def test_katalog_gestu_bez_wielkosci_liter_jeden_wiersz(tmp_path):
    """`run_dir.path COLLATE NOCASE` + `UNIQUE(run_id, path, action)`: `IC405` i `ic405` to ten sam
    katalog udziału - zamiar niezakończony wraca jako TEN SAM wiersz, a zakończonego (`done_at`) nie
    otwieramy ponownie: ślad gestu zostaje, katalog pod tą ścieżką jest już cudzy."""
    s = _Scena(tmp_path)
    run = s.stage(s.plan())
    a = repo.open_run_dir(s.con, run_id=run, path=r"R:\L\IC405", action="created", now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        s.con.execute("UPDATE run_dir SET undone_at = ? WHERE id = ?", (NOW, a))   # bez `done_at`
    s.con.rollback()
    b = repo.open_run_dir(s.con, run_id=run, path=r"r:\l\ic405", action="created", now=NOW)
    assert a == b
    repo.finish_run_dir(s.con, dir_id=a, now=NOW)
    with pytest.raises(ValueError, match="zamknięty"):
        repo.open_run_dir(s.con, run_id=run, path=r"r:\l\ic405", action="created", now=NOW)
    assert s.con.execute("SELECT done_at FROM run_dir WHERE id = ?", (a,)).fetchone()[0] == NOW


# ============================================================ wznowienie, kotwice podglądu, kolizje


def _pad_przed(monkeypatch, cel, nazwa):
    """`cel.nazwa` nie wykonuje się wcale - proces „ginie” tuż przed nią."""
    def _pad(*a, **kw):
        raise _Smierc(nazwa)
    monkeypatch.setattr(cel, nazwa, _pad)


def _reka_na_m42(con, path, ic):
    """Nowsza decyzja ręki po kroku bazy gestu: klatka z IC405 (ręka gestu) przechodzi na M42."""
    fid = _wiersz(con, path)["frame_id"]
    assert repo.user_override_object(con, frame_id=fid, canon="M42", kind="deep_sky",
                                     expected=(ic, "user", None), reason="object_change",
                                     now=NOW) == "assigned"
    return _oid(con, "M42")


def test_wznowienie_po_zmianie_reka_to_dryf_bez_ruchu_pliku(tmp_path, monkeypatch):
    """Krok bazy zapisany, proces ginie przed przeniesieniem, ręka zmienia potem obiekt klatki.
    Ponowienie NIE idzie dalej za obiektem gestu: dryf, plik nietknięty, nowsza decyzja ręki stoi,
    starsza nie wraca; z gestu nic nie zostało - pozycja 'skipped' i bez wyniku w bazie."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    _smierc_po(monkeypatch, repo, "apply_object_change_item")
    with pytest.raises(_Smierc):
        writeback.commit_object_change(con, run, now=NOW)
    monkeypatch.undo()
    m42 = _reka_na_m42(con, s.stare[0], _oid(con, "IC405"))
    przed = _ev(con)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert (wynik.applied, len(wynik.skipped)) == ([], 1) and "przed awarią" in wynik.skipped[0].reason
    assert _sha1(s.stare[0]) == s.sha1[0] and not (tmp_path / "LIGHTS" / "IC405").exists()
    w = _wiersz(con, s.stare[0])
    assert (w["object_id"], w["object_source"]) == (m42, "user") and _ev(con) == przed
    assert (_pozycje(con)[0]["status"], _pozycje(con)[0]["object_id"]) == ("skipped", None)
    assert con.execute("SELECT status FROM pending_renames").fetchone()[0] == "skipped"


def test_wznowienie_po_przeniesieniu_i_zmianie_reka_zostawia_reszte_cofnieciu(tmp_path, monkeypatch):
    """Proces ginie po przeniesieniu, przed kartą; ręka zmienia obiekt. Ponowienie: karta NIE idzie
    za obiektem gestu (plik dalej ruszany nie jest), pozycja 'failed'; cofnięcie zwraca plik bajt
    w bajt, a nowsza decyzja ręki w bazie zostaje."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    _pad_przed(monkeypatch, writeback, "_zapisz_lokacje")
    with pytest.raises(_Smierc):
        writeback.commit_object_change(con, run, now=NOW)
    monkeypatch.undo()
    assert s.nowe[0].exists()
    m42 = _reka_na_m42(con, s.nowe[0], _oid(con, "IC405"))
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.failed) == 1 and "przed awarią" in wynik.failed[0].reason
    assert _karta(s.nowe[0]) == "Sh2-229" and s.nowe[0].exists()
    assert con.execute("SELECT status FROM pending_changes").fetchone()[0] == "skipped"
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 1 and _sha1(s.stare[0]) == s.sha1[0]
    w = _wiersz(con, s.stare[0])
    assert (w["object_id"], w["object_source"]) == (m42, "user")


def test_ponowienie_zapisanego_przebiegu_nie_rusza_katalogu_odtworzonego_pozniej(tmp_path):
    """Przebieg zapisany (katalog źródłowy opróżniony i usunięty), potem ktoś odtwarza pusty katalog
    pod tą samą ścieżką; ponowne wywołanie zapisu = nic (brak pozycji oczekujących): katalog stoi,
    wpisy `run_dir` co do bajtu jak przed."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan())
    writeback.commit_object_change(con, run, now=NOW)
    assert not s.zrodlo.exists()
    s.zrodlo.mkdir(parents=True)
    przed = [tuple(r) for r in con.execute("SELECT * FROM run_dir ORDER BY id")]
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert (wynik.applied, wynik.blocked, wynik.failed, wynik.skipped, wynik.dirs_removed,
            wynik.warnings) == ([], [], [], [], 0, ())                # bez pozycji = cisza
    assert s.zrodlo.is_dir()
    assert [tuple(r) for r in con.execute("SELECT * FROM run_dir ORDER BY id")] == przed


@pytest.mark.parametrize("i, nowa", [(2, True), (0, False)],
                         ids=["raw_przeniesienie_bez_karty", "fits_sama_karta"])
def test_plik_zmieniony_na_dysku_od_skanu_blokuje_przed_zapisem(tmp_path, i, nowa):
    """`mtime` na dysku inny niż w podglądzie (zmiana, której skan jeszcze nie wciągnął) - także dla
    pozycji bez karty: odmowa przed krokiem bazy, plik i baza nietknięte."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(i, nowa=nowa)]))
    st = os.stat(s.stare[i])
    os.utime(s.stare[i], ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    przed = _ev(con)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.blocked) == 1 and "od ostatniego skanu" in wynik.blocked[0].reason
    assert _sha1(s.stare[i]) == s.sha1[i] and _ev(con) == przed and _oid(con, "IC405") is None


def test_pozycja_bez_przeniesienia_pilnuje_sciezki_z_podgladu(tmp_path):
    """Pozycja „sama karta” (plik już w folderze): kopia przemianowana między podglądem a zapisem
    (zwykły rename, ten sam nagłówek i `mtime`) - odmowa bez zapisu, karta nie trafia pod nazwę,
    której podgląd nie pokazał."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0, nowa=False)]))
    inna = s.zrodlo / "inna_nazwa.fits"
    lid = _wiersz(con, s.stare[0])["id"]
    os.rename(s.stare[0], inna)
    repo.relocate_location(con, location_id=lid, new_path=str(inna), now=NOW)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.blocked) == 1 and "inną ścieżką" in wynik.blocked[0].reason
    assert _karta(inna) == "Sh2-229" and _oid(con, "IC405") is None


def test_druga_obecna_kopia_po_podgladzie_blokuje_przed_krokiem_bazy(tmp_path):
    """Skan dopisał drugą obecną kopię tej samej klatki po podglądzie: ręka zmieniłaby obiekt całej
    klatki, a plik i kartę dostałaby jedna kopia - odmowa pod blokadą kroku bazy, zero zapisu."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    kopia = tmp_path / "KOPIA" / "a.fits"
    kopia.parent.mkdir()
    kopia.write_bytes(s.stare[0].read_bytes())
    _wczytaj(con, kopia)
    assert _wiersz(con, kopia)["frame_id"] == _wiersz(con, s.stare[0])["frame_id"]
    przed = _ev(con)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert len(wynik.blocked) == 1 and "jednej obecnej kopii" in wynik.blocked[0].reason
    assert _sha1(s.stare[0]) == s.sha1[0] and _ev(con) == przed and _oid(con, "IC405") is None
    assert not (tmp_path / "LIGHTS" / "IC405").exists()


def test_cel_zajety_inna_wielkoscia_liter_takze_przez_kopie_nieobecna(tmp_path):
    """Kolizja celu po ścieżce FIZYCZNEJ w sterowniku: inna lokacja (nieobecna) pod nową ścieżką
    zapisaną inną wielkością liter → odmowa, plik nietknięty."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    obca = _wiersz(con, s.stare[1])["id"]
    con.execute("UPDATE location SET path = ?, present = 0 WHERE id = ?",
                (str(s.nowe[0]).upper(), obca))
    con.commit()
    wynik = writeback.commit_object_change(con, run, now=NOW)
    assert [r.reason for r in wynik.blocked] == [f"cel zajęty w bazie (location:{obca})"]
    assert s.stare[0].exists() and not s.nowe[0].exists()


def test_straz_relokacji_kolizja_bez_wielkosci_liter_a_wlasna_zmiana_liter_przechodzi(tmp_path):
    """Straż renamu (wspólna dla „Nazw” i gestu) porównuje ścieżki fizycznie: cudza lokacja pod tą
    samą ścieżką w innej wielkości liter - obecna albo nie - to kolizja; zmiana samej wielkości
    liter WŁASNEJ lokacji kolizją nie jest."""
    s = _Scena(tmp_path)
    con = s.con
    a, b = _wiersz(con, s.stare[0])["id"], _wiersz(con, s.stare[1])["id"]
    for _ in range(2):
        with pytest.raises(ValueError, match="cel zajęty"):
            with repo.guard_file_rename(con, location_id=a, new_path=str(s.stare[1]).swapcase(),
                                        generation=repo.inplace_generation(con), now=NOW):
                pass
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (b,))
        con.commit()
    with repo.guard_file_rename(con, location_id=a, new_path=str(s.stare[0]).upper(),
                                generation=repo.inplace_generation(con), now=NOW):
        pass
    assert _wiersz(con, str(s.stare[0]).upper())["id"] == a


def test_cofniecie_wraca_przy_sciezce_bazy_w_innej_wielkosci_liter(tmp_path):
    """Powrót pliku porównuje ścieżkę bazy z nową ścieżką przebiegu fizycznie: pisownia w bazie
    zmieniona tylko wielkością liter nie zatrzymuje cofnięcia."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(2)]))
    assert len(writeback.commit_object_change(con, run, now=NOW).applied) == 1
    con.execute("UPDATE location SET path = ? WHERE id = ?",
                (str(s.nowe[2]).upper(), _wiersz(con, s.nowe[2])["id"]))
    con.commit()
    cofniecie = writeback.undo_object_change(con, run, now=NOW)
    assert len(cofniecie.applied) == 1 and _sha1(s.stare[2]) == s.sha1[2]


# ============================================================ powód pozycji z kodem w bazie (AR-141)


def _trojka(con, run_id="R1"):
    """`(reason, reason_code, reason_args)` pierwszej pozycji przebiegu."""
    return tuple(con.execute("SELECT reason, reason_code, reason_args FROM pending_object_change "
                             "WHERE run_id = ? ORDER BY id", (run_id,)).fetchone())


def _powod_bazy(con, run_id="R1"):
    from horreum import item_reasons
    return item_reasons.z_bazy(*_trojka(con, run_id))


def _args(powod):
    return dict(powod.params)


@pytest.mark.parametrize("scena", ["karta", "dryf", "mtime", "alias"])
def test_powod_pozycji_w_bazie_ma_kod_a_proza_to_proza_wyniku(tmp_path, scena):
    """AR-141: odmowy sterownika zapisują w pozycji KOD z parametrami obok prozy (0041). Proza
    w bazie = proza wyniku biegu (CLI, log), a powód z bazy wraca z tym samym kodem i tymi samymi
    parametrami - także powodem niższej warstwy w `inner` (odmowa klingi z kodem; reguła karty
    z kodem - AR-158). Falsyfikator: `settle_object_change_item` bez trójki - kod NULL."""
    s = _Scena(tmp_path)
    con = s.con
    pozycja = s.pozycja(0)
    target = None
    if scena == "karta":
        pozycja = oc.ObjectChangeItem(**{**pozycja.__dict__, "card_new": "IC 405ł"})
    elif scena == "mtime":
        pozycja = oc.ObjectChangeItem(**{**pozycja.__dict__, "expected_mtime": None})
    elif scena == "alias":
        m42, _ = repo.upsert_object(con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
        repo.add_object_alias(con, alias_norm="flamingstar", object_id=m42, source="user", now=NOW)
        target = oc.ObjectTarget("IC405", "IC", "deep_sky", "flamingstar", "IC 405")
    plan = s.plan(pozycje=[pozycja])
    if target is not None:
        plan = oc.ObjectChangePlan(plan.run_id, target, plan.items, ())
    run = s.stage(plan)
    if scena == "dryf":
        m42, _ = repo.upsert_object(con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
        repo.assign_object(con, frame_id=_wiersz(con, s.stare[0])["frame_id"], object_id=m42,
                           object_source="header", now=NOW)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    (fr,) = wynik.blocked + wynik.skipped
    oczekiwany = {"karta": "card_refused", "dryf": "drift", "mtime": "no_mtime_anchor",
                  "alias": "db_refused"}[scena]
    z_bazy = _powod_bazy(con)
    assert _trojka(con)[0] == fr.reason and fr.reason.code == z_bazy.code == oczekiwany
    assert _args(z_bazy) == _args(fr.reason)
    if scena == "alias":                       # odmowa klingi z kodem w `inner` (Q6)
        inner = _args(z_bazy)["inner"]
        assert (inner.code, _args(inner)) == ("alias_conflict",
                                              {"alias": "flamingstar", "object_id": m42})
    if scena == "karta":                       # reguła karty z kodem w `inner` (AR-158)
        inner = _args(z_bazy)["inner"]
        assert (inner.code, _args(inner)) == ("card_value_chars",
                                              {"keyword": "OBJECT", "char": repr("ł")})
        cof = writeback.undo_object_change(con, run, now=NOW)
        assert [r.reason.code for r in cof.skipped] == ["undo_refused_earlier"]


def test_doklejka_CAS_reki_to_nota_z_kodem_a_proza_bez_zmian(tmp_path, monkeypatch):
    """Odmowa karty po kroku bazy, gdy klatka niesie już nowszą decyzję ręki: wycofanie CAS-em
    odmawia, klinga dokleja zdanie „baza: … zostaje” - w bazie jako nota `hand_newer_kept` przy
    kodzie odmowy, proza znak w znak jak dotąd (`; ` + zdanie)."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))

    def _reka_i_odmowa(con_, stan, lid, rows, **kw):
        _reka_na_m42(con_, s.nowe[0], _oid(con_, "IC405"))
        return writeback._ZapisLokacji(writeback.FileResult(lid, str(s.nowe[0]), "blocked",
                                                            "odmowa pisarza"))
    monkeypatch.setattr(writeback, "_zapisz_lokacje", _reka_i_odmowa)
    wynik = writeback.commit_object_change(con, run, now=NOW)
    (fr,) = wynik.blocked
    z_bazy = _powod_bazy(con)
    assert str(z_bazy) == (f"{fr.reason}; baza: klatka niesie już nowszą decyzję niż gest - "
                           f"zostaje")
    assert z_bazy.code == "card_refused" and _args(z_bazy)["inner"] == "odmowa pisarza"
    assert [n.code for n in _args(z_bazy)["notes"]] == ["hand_newer_kept"]


def test_plik_ktory_nie_wrocil_niesie_kod_odmowy_i_kod_powrotu(tmp_path, monkeypatch):
    """Odmowa karty po przeniesieniu, a powrót pliku odbity: pozycja 'failed' z kodem
    `file_not_back` - `outer` = odmowa karty, `inner` = powód warstwy renamu Z KODEM."""
    from horreum.item_reasons import PowodPozycji
    s = _Scena(tmp_path)
    con = s.con
    zla = oc.ObjectChangeItem(**{**s.pozycja(0).__dict__, "card_new": "IC 405ł"})
    run = s.stage(s.plan(pozycje=[zla]))
    monkeypatch.setattr(writeback, "_przenies_wstecz", lambda *a, **kw: writeback.RenameFileResult(
        "blocked", PowodPozycji("plik nie stoi na ścieżce z przebiegu", "not_on_run_path")))
    (fr,) = writeback.commit_object_change(con, run, now=NOW).failed
    z_bazy = _powod_bazy(con)
    assert str(z_bazy) == fr.reason and z_bazy.code == "file_not_back"
    assert (_args(z_bazy)["outer"].code, _args(z_bazy)["inner"].code) == ("card_refused",
                                                                          "not_on_run_path")
    assert _args(z_bazy)["path"] == str(s.stare[0])


def test_cofniecie_zatrzymane_ma_kod_a_awans_fazy_czysci_trojke(tmp_path, monkeypatch):
    """Cofnięcie zatrzymane na powrocie pliku: powód `undo_file` z kodem renamu w `inner` (faza
    `card`). Ponowienie przy nowszej decyzji ręki w bazie domyka pozycję z `undo_hand_newer`, a awans
    fazy czyści CAŁĄ trójkę (kod nie zostaje przy pozycji bez powodu)."""
    from horreum.item_reasons import PowodPozycji
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    assert len(writeback.commit_object_change(con, run, now=NOW).applied) == 1
    prawdziwy = writeback._przenies_wstecz
    monkeypatch.setattr(writeback, "_przenies_wstecz", lambda *a, **kw: writeback.RenameFileResult(
        "blocked", PowodPozycji("plik nie stoi na ścieżce z przebiegu", "not_on_run_path")))
    (fr,) = writeback.undo_object_change(con, run, now=NOW).blocked
    z_bazy = _powod_bazy(con)
    assert str(z_bazy) == fr.reason and z_bazy.code == "undo_file"
    assert _args(z_bazy)["inner"].code == "not_on_run_path"
    monkeypatch.setattr(writeback, "_przenies_wstecz", prawdziwy)
    _reka_na_m42(con, s.nowe[0], _oid(con, "IC405"))
    (fr,) = writeback.undo_object_change(con, run, now=NOW).applied
    assert fr.reason.code == "undo_hand_newer" and _powod_bazy(con).code == "undo_hand_newer"
    con.execute("UPDATE pending_object_change SET undo_phase = NULL, status = 'applied'")
    con.commit()
    repo.set_object_change_undo_phase(con, item_id=_pozycje(con)[0]["id"], phase="card")
    assert _trojka(con) == (None, None, None)


def test_powod_przezywa_copy_deepcopy_i_pickle_z_zagniezdzeniem():
    """AR-141 (S2): `PowodPozycji` to podklasa `str` z obowiązkowym kodem - dawny protokół `str`
    odtwarzał obiekt samym tekstem (`TypeError` w `copy`, `deepcopy`, `pickle`, `dataclasses.asdict`).
    Odtworzenie zachowuje tekst, kod, parametry, powód zagnieżdżony i uwagi."""
    import copy
    import dataclasses
    import pickle
    from horreum.item_reasons import PowodPozycji, dopisz
    inner = PowodPozycji("źródło nie istnieje na dysku", "src_missing")
    powod = dopisz(PowodPozycji("plik nie wrócił: źródło nie istnieje na dysku", "undo_file",
                                inner=inner),
                   PowodPozycji("nowsza decyzja ręki o obiekcie klatki zostaje", "hand_newer"))
    # pickle wyłącznie na obiekcie zbudowanym w tym teście (round-trip protokołu), bez danych z zewnątrz
    kopie = [copy.copy(powod), copy.deepcopy(powod),
             pickle.loads(pickle.dumps(powod, protocol=pickle.HIGHEST_PROTOCOL)),
             pickle.loads(pickle.dumps(powod, protocol=0)),
             dataclasses.asdict(writeback.FileResult(1, "p", "blocked", powod))["reason"]]
    for k in kopie:
        assert type(k) is PowodPozycji and str(k) == str(powod) and k.code == "undo_file"
        p = dict(k.params)
        assert (p["inner"].code, str(p["inner"])) == ("src_missing", str(inner))
        assert [(n.code, str(n)) for n in p["notes"]] == [
            ("hand_newer", "nowsza decyzja ręki o obiekcie klatki zostaje")]


def test_dopisz_noty_z_kodem_do_prozy_to_jawna_granica():
    """AR-141 (K1): nota z kodem doklejona do prozy bez kodu gubiła kod po cichu. `dopisz` odmawia
    (`ValueError`, EXPECT); pisarz (`writeback._dopisz`) i doklejka klingi owijają prozę w kopertę
    `prose` - zdanie znak w znak, nota z kodem zostaje na liście uwag."""
    from horreum.item_reasons import PowodPozycji, dopisz
    nota = PowodPozycji("baza: klatka niesie już nowszą decyzję niż gest - zostaje",
                        "hand_newer_kept")
    with pytest.raises(ValueError, match="kopert"):
        dopisz("proza systemu", nota)
    assert dopisz(None, nota) is nota and dopisz("a", "b") == "a; b" and dopisz("a", None) == "a"
    wynik = writeback._dopisz("proza pisarza", nota)
    assert str(wynik) == f"proza pisarza; {nota}" and wynik.code == "prose"
    assert dict(wynik.params)["text"] == "proza pisarza"
    assert [n.code for n in dict(wynik.params)["notes"]] == ["hand_newer_kept"]
    assert writeback._dopisz("a", "b") == "a; b" and type(writeback._dopisz("a", "b")) is str


def test_doklejka_CAS_reki_do_prozy_bez_kodu_idzie_w_kopercie(tmp_path, monkeypatch):
    """K1 na prawdziwej klindze: odmowa pozycji gołą prozą (tekst spoza warstw z kodem) po kroku
    bazy przy nowszej decyzji ręki - doklejka nie wywraca rozliczenia, proza znak w znak jak dotąd,
    a w bazie koperta `prose` z notą `hand_newer_kept`."""
    s = _Scena(tmp_path)
    con = s.con
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))

    def _reka_i_proza(con_, run_id, katalogi, *, now, akcja):
        _reka_na_m42(con_, s.stare[0], _oid(con_, "IC405"))
        return "odmowa prozą", 0
    monkeypatch.setattr(writeback, "_zaloz_katalogi", _reka_i_proza)
    (fr,) = writeback.commit_object_change(con, run, now=NOW).blocked
    z_bazy = _powod_bazy(con)
    assert fr.reason == "odmowa prozą"
    assert str(z_bazy) == "odmowa prozą; baza: klatka niesie już nowszą decyzję niż gest - zostaje"
    assert z_bazy.code == "prose" and [n.code for n in _args(z_bazy)["notes"]] == ["hand_newer_kept"]


def test_meta_powod_pozycji_bez_golej_prozy_i_jeden_pisarz_trojki():
    """AR-141 (Z7): (1) sterownik zapisu oddaje powód pozycji wyłącznie jako `PowodPozycji` albo
    zmienną - żadne wywołanie rozliczenia pozycji (`repo.settle_object_change_item`,
    `set_object_change_undo_phase`, `_odmowa`, `_stop`, `_wycofaj_pozycje`) nie bierze literału ani
    f-stringu (nowe miejsce z gołą prozą = zdanie, którego okno nie powie w języku UI); (2) w `repo`
    powód pozycji ustawia WYŁĄCZNIE `_set_object_change_reason_tx` - żaden inny SQL nie pisze
    `reason` tabeli `pending_object_change` (proza i kod nie mogą się rozjechać)."""
    import ast
    import inspect
    import re
    rozliczenia = {"settle_object_change_item": "reason", "set_object_change_undo_phase": "reason",
                   "_odmowa": 1, "_stop": 2, "_wycofaj_pozycje": 3}
    wywolania = 0
    for w in ast.walk(ast.parse(inspect.getsource(writeback))):
        if not isinstance(w, ast.Call):
            continue
        nazwa = w.func.attr if isinstance(w.func, ast.Attribute) else getattr(w.func, "id", None)
        if nazwa not in rozliczenia:
            continue
        wywolania += 1
        gdzie = rozliczenia[nazwa]
        arg = (next((k.value for k in w.keywords if k.arg == gdzie), None) if isinstance(gdzie, str)
               else (w.args[gdzie] if len(w.args) > gdzie else None))
        assert not isinstance(arg, (ast.JoinedStr, ast.Constant)) or (
            isinstance(arg, ast.Constant) and arg.value is None), ast.unparse(w)
    assert wywolania > 25, wywolania
    zapis_powodu = re.compile(r"UPDATE pending_object_change SET[^;]*\breason\b")
    trafienia = []
    for f in (n for n in ast.walk(ast.parse(inspect.getsource(repo)))
              if isinstance(n, ast.FunctionDef)):
        for c in ast.walk(f):
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and zapis_powodu.search(
                    c.value):
                trafienia.append(f.name)
    assert trafienia == ["_set_object_change_reason_tx"], trafienia


# ============================================================ AR-177: karta obiektu-regionu (Veil)

VEIL_RA, VEIL_DEC = 312.75, 30.67          # środek regionu Veil (`resolve/data/regions.json`)
M31_RA, M31_DEC = 10.68, 41.27             # poza każdym regionem


def _fits_nieba(path, *, obj=None, seed=1, ra=VEIL_RA, dec=VEIL_DEC, stos=False):
    """FITS lighta (albo stosu - `stos`) z kartą `obj` (None = bez karty) i współrzędnymi
    nagłówka (`ra` None = bez współrzędnych)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=(np.arange(16, dtype=np.int16).reshape(4, 4) + seed).astype(np.int16))
    hdu.header["IMAGETYP"] = "Master Light" if stos else "Light"
    if obj is not None:
        hdu.header["OBJECT"] = (obj, KOMENTARZ)
    if ra is not None:
        hdu.header["RA"] = ra
        hdu.header["DEC"] = dec
    hdu.writeto(path)
    return path


def _kanon(con, fid):
    r = con.execute("SELECT o.canon FROM frame f LEFT JOIN object o ON o.id = f.object_id "
                    "WHERE f.id = ?", (fid,)).fetchone()
    return r[0]


def test_uzgodnij_regionu_pisze_karte_blizniakow_a_przebieg_ja_utrzymuje(tmp_path):
    """AR-177 na PRAWDZIWYM rdzeniu: klatka Veil z regionu bez karty dostaje w „Uzgodnij” kartę
    bliźniaków folderu (`'veil'` z kopii obok), bez ruchu pliku; zapis, a potem przebieg resolvera
    zostawiają ją przy Veil szczeblem regionu, a wiersz „Plik nie zgadza się z obiektem” pustoszeje.
    Falsyfikator: forma regionu, którą drabina oddaje innemu obiektowi (`M 31`) - pozycja i przebieg
    odprowadzają klatkę od Veil."""
    from horreum import resolver
    from horreum.gui import queries
    folder = tmp_path / "ASTRO_" / "LIGHTS" / "Veil" / "cam"
    blizniak = _fits_nieba(folder / "Veil_1.fits", obj="veil", seed=1)
    bez = _fits_nieba(folder / "Veil_2.fits", seed=2)
    con = db.open_db(str(tmp_path / "h.db"))
    for p in (blizniak, bez):
        _wczytaj(con, p)
    resolver.run_resolver(con, NOW)
    fb, fz = _wiersz(con, blizniak)["frame_id"], _wiersz(con, bez)["frame_id"]
    assert queries.file_object_mismatch_frame_ids(con) == {fz}
    rows = queries.object_change_rows(con, [fb, fz], target=None)
    plan = oc.plan_object_change(rows, target=None, library_root=resolver.library_root_from_db(con),
                                 location_at=queries.location_lookup(con))
    (it,) = plan.items
    assert (it.frame_id, it.card_op, it.card_new, it.new_path) == (fz, "add", "veil", None)
    assert [(s.frame_id, s.code) for s in plan.skipped] == [(fb, oc.SKIP_UNCHANGED)]
    repo.stage_object_change(con, plan=plan, now=NOW)
    res = writeback.commit_object_change(con, plan.run_id, now=NOW)
    assert len(res.applied) == 1 and not (res.blocked or res.failed), res
    assert _karta(bez) == "veil"
    resolver.run_resolver(con, NOW)
    zrodlo = con.execute("SELECT object_source FROM frame WHERE id = ?", (fz,)).fetchone()[0]
    assert (_kanon(con, fz), zrodlo) == ("Veil", "region")
    assert queries.file_object_mismatch_frame_ids(con) == set()
    con.close()


def test_karta_wraca_rownowazna_przebiegowi_po_zdjeciu_reki(tmp_path):
    """AR-177: `resolver.karta_wraca` mówi to samo, co PRAWDZIWY następny przebieg, gdy karta zostaje
    sama. Macierz: nazwa katalogowa, region w środku, ręka poza regionem, ręka bez współrzędnych,
    ręka w regionie, wariant stosu z oryginałem przy Veil (sam poza regionem) i wariant z ręką,
    którego oryginał leży poza regionem. Karta idzie do pliku drogą pisarza (staging + `commit`),
    ręka schodzi klingą („Cofnij przypisanie” + zgaszenie nagrobka), potem `run_resolver`.
    Falsyfikator: `karta_wraca` bez szczebla bliźniaka - oba warianty dostają przewidywanie z regionu
    i rozjeżdżają się z przebiegiem."""
    from horreum import resolver
    korzen = tmp_path / "ASTRO_"
    lighty, stosy = korzen / "LIGHTS" / "Veil" / "cam", korzen / "STACKS" / "Veil" / "cam"
    przypadki = {           # nazwa: (plik, karta do zapisu, ręka przed zapisem)
        "nazwa": (_fits_nieba(lighty / "k1.fits", obj="NGC6992", seed=1), "NGC 7000", False),
        "region": (_fits_nieba(lighty / "k2.fits", seed=2), "veil", False),
        "reka_poza": (_fits_nieba(lighty / "k3.fits", seed=3, ra=M31_RA, dec=M31_DEC), "veil", True),
        "reka_bez_wsp": (_fits_nieba(lighty / "k4.fits", seed=4, ra=None), "veil", True),
        "reka_w_regionie": (_fits_nieba(lighty / "k5.fits", seed=5), "veil", True),
        "wariant_oryginal_veil": (_fits_nieba(stosy / "w6.fits", seed=6, ra=M31_RA, dec=M31_DEC,
                                              stos=True), "veil", False),
        "wariant_oryginal_m31": (_fits_nieba(stosy / "w7.fits", seed=7, stos=True), "veil", True),
    }
    o6 = _fits_nieba(stosy / "o6.fits", seed=8, stos=True)
    o7 = _fits_nieba(stosy / "o7.fits", obj="M 31", seed=9, ra=M31_RA, dec=M31_DEC, stos=True)
    con = db.open_db(str(tmp_path / "h.db"))
    for p in [p for p, _, _ in przypadki.values()] + [o6, o7]:
        _wczytaj(con, p)
    fid = {k: _wiersz(con, p)["frame_id"] for k, (p, _, _) in przypadki.items()}
    for wariant, oryginal in (("wariant_oryginal_veil", o6), ("wariant_oryginal_m31", o7)):
        repo.link_stack_variant(con, variant_frame_id=fid[wariant],
                                original_frame_id=_wiersz(con, oryginal)["frame_id"],
                                variant="autocrop", source="user", now=NOW)
    reka = [fid[k] for k, (_, _, r) in przypadki.items() if r]
    repo.user_assign_object(con, alias_norm=None, canon="Veil", catalog="region", kind="region",
                            frame_ids=reka, now=NOW)
    resolver.run_resolver(con, NOW)

    for k, (p, karta, _) in przypadki.items():         # karta do pliku drogą pisarza
        w = _wiersz(con, p)
        stara = _karta(p)
        repo.stage_pending(con, run_id="K", location_id=w["id"], keyword="OBJECT",
                           idx=0 if stara is not None else None,
                           op="set" if stara is not None else "add", old_value=stara,
                           new_value=karta, new_type="str", new_comment=None,
                           expected_header_hash=w["header_hash"])
    wynik = writeback.commit(con, "K", now=NOW, inplace=True)
    assert len(wynik.applied) == len(przypadki) and not wynik.failed, wynik
    repo.clear_object_assignment(con, frame_ids=reka, now=NOW)
    for f in reka:
        assert repo.clear_object_tombstone(con, frame_id=f, now=NOW)

    lookup = resolver.alias_snapshot(con).get
    przewidziane = {}
    for k, (p, karta, _) in przypadki.items():
        assert _karta(p) == karta
        ra, dec = con.execute("SELECT ra_deg, dec_deg FROM header WHERE frame_id = ?",
                              (fid[k],)).fetchone()
        blizniak = con.execute(
            "SELECT o.canon FROM stack_variant v JOIN frame f ON f.id = v.original_frame_id "
            "LEFT JOIN object o ON o.id = f.object_id WHERE v.variant_frame_id = ?",
            (fid[k],)).fetchone()
        przewidziane[k] = resolver.karta_wraca(lookup, karta, "Veil", ra, dec,
                                               twin_canon=blizniak[0] if blizniak else None)
    resolver.run_resolver(con, NOW)
    po = {k: _kanon(con, fid[k]) for k in przypadki}
    assert przewidziane == {k: kanon == "Veil" for k, kanon in po.items()}, (przewidziane, po)
    assert po == {"nazwa": "NGC7000", "region": "Veil", "reka_poza": None, "reka_bez_wsp": None,
                  "reka_w_regionie": "Veil", "wariant_oryginal_veil": "Veil",
                  "wariant_oryginal_m31": "NGC224"}
    con.close()
