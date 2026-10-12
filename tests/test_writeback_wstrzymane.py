"""AR-82: ZAPIS Z ZEZNANIEM WSTRZYMANYM - plik zapisany, a zeznanie klatki (`header`/`cards`) nie
przyjęło jego nagłówka, bo głosem klatki mówi inna obecna kopia (reguła kopii wiodącej, AR-4).

Dawniej commit meldował 'applied', wpisy stagingu 'applied', nagrobek ręki gasł - przy zeznaniu,
które zostało przy drugiej kopii. Teraz: wynik 'withheld' (`CommitResult.withheld`), wpisy 'failed'
z wiązaniem `withheld_id`, nagrobek żyje, a dokończenie przychodzi z dowodem zeznania (gest „Ta kopia
prowadzi”, Dostawa, pełny odczyt kopii wiodącej). Pełny odczyt, który dowodzi nowszego stanu lokacji,
zamyka wstrzymanie jako `superseded`; cofnięcie commitu - jako `undone`.

Scena: plik L ma staging karty `OBJECT`, a ZANIM commit ruszy, druga kopia tej samej klatki (M,
identyczne bajty w innym katalogu) wjeżdża skanem - dwie obecne kopie o tym samym zeznaniu, więc
kopii wiodącej nie ma (`repo.lead_location` → None) i zapis L nie może przepisać zeznania klatki.
Prawdziwe pliki FITS, jak reszta baterii pisarza."""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, lead_copy, repo, scan, writeback
from horreum.gui import i18n

NOW = "2026-10-12T00:00:00+00:00"
KOMENTARZ = "Name of the object of interest"


class _Smierc(BaseException):
    """Śmierć procesu w punkcie wstrzyknięcia - przechodzi przez każde `except Exception` pisarza."""


def _fits(path, *, obj="NGC6992", seed=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=(np.arange(64, dtype=np.int16).reshape(8, 8) + seed).astype(np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = (obj, KOMENTARZ)
    hdu.writeto(path, overwrite=True)
    return path


def _wczytaj(con, path):
    """Pełny odczyt pliku i wjazd rekordu (bez bramy `mtime` - odczyt wymuszony)."""
    scan.ingest_record(con, scan.scan_file(str(path)), volume="V", now=NOW,
                       summary=scan.ScanSummary())


def _lok(con, path):
    return con.execute("SELECT id, frame_id, header_hash FROM location WHERE path = ?",
                       (str(path),)).fetchone()


def _nagrobek(con, fid):
    """Ręka przypisuje obiekt `COS` (jawnie, także na nagrobku - `overwrite_weak`) i go wyklucza -
    klatka `user_cleared` z NOWYM `object.cleared` (nowa wersja decyzji ręki)."""
    g = repo.user_assign_object(con, alias_norm=None, canon="COS", catalog=None, kind="own",
                                frame_ids=[fid], now=NOW, overwrite_weak=True)
    assert g.assigned == 1, g
    repo.clear_object_assignment(con, frame_ids=[fid], now=NOW)


def _scena(tmp_path, *, nagrobek=False, wartosc="NGC 7000", run="R"):
    con = db.open_db(str(tmp_path / "h.db"))
    L = _fits(tmp_path / "A" / "a.fits")
    _wczytaj(con, L)
    lok = _lok(con, L)
    if nagrobek:
        _nagrobek(con, lok["frame_id"])
    _stage(con, run, lok["id"], wartosc)
    M = tmp_path / "B" / "a.fits"
    M.parent.mkdir(parents=True)
    shutil.copyfile(L, M)                     # druga kopia klatki wjeżdża PO stagingu
    _wczytaj(con, M)
    return SimpleNamespace(con=con, L=L, M=M, lid=lok["id"], mid=_lok(con, M)["id"],
                           fid=lok["frame_id"])


def _stage(con, run, lid, wartosc):
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id=run, location_id=lid, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=hh)


def _zeznanie(con, fid):
    """OBJECT w zeznaniu klatki: pole gorące `header.object_raw` i lustro `cards`."""
    h = con.execute("SELECT object_raw FROM header WHERE frame_id = ?", (fid,)).fetchone()[0]
    k = con.execute("SELECT value_raw FROM cards WHERE frame_id = ? AND keyword = 'OBJECT'",
                    (fid,)).fetchone()[0]
    return h, k


def _wstrzymania(con):
    return con.execute("SELECT * FROM withheld_write ORDER BY id").fetchall()


def _wpisy(con, run="R"):
    return con.execute("SELECT status, withheld_id, reason FROM pending_changes WHERE run_id = ? "
                       "ORDER BY id", (run,)).fetchall()


def _zrodlo(con, fid):
    return con.execute("SELECT object_source FROM frame WHERE id = ?", (fid,)).fetchone()[0]


def _ev(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _bez_M(s):
    """Druga kopia znika (plik precz, obecność zdjęta) - L zostaje jedyną obecną kopią."""
    s.M.unlink()
    s.con.execute("UPDATE location SET present = 0 WHERE id = ?", (s.mid,))
    s.con.commit()


# ============================================================ zapis wstrzymany


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_zapis_z_wstrzymanym_zeznaniem_to_withheld_nie_applied(tmp_path, inplace):
    """Sedno AR-82 w obu drogach pisarza: plik zapisany (karta na dysku, fakty kopii L nowe,
    `commit_id` do cofnięcia), zeznanie klatki stare, wpisy 'failed' z wiązaniem, nagrobek żyje.
    Falsyfikatory: `_zamknij` bez warunku `zeznanie` (atomowo) albo `finish_inplace_op` ignorujący
    `testimony_ok` (w miejscu) - wynik 'applied', nagrobek zgaszony."""
    s = _scena(tmp_path, nagrobek=True)
    res = writeback.commit(s.con, "R", now=NOW, inplace=inplace)
    assert not res.applied and not res.failed and len(res.withheld) == 1, res
    (fr,) = res.withheld
    assert fr.status == "withheld" and fr.code == writeback.CODE_ZEZNANIE_WSTRZYMANE
    assert "zeznanie klatki NIE przyjęło zapisu" in fr.reason and "Ta kopia prowadzi" in fr.reason
    assert res.commit_id is not None
    assert fits.getheader(str(s.L))["OBJECT"] == "NGC 7000"           # plik ZAPISANY
    assert s.con.execute("SELECT hdr_object FROM location WHERE id = ?",
                         (s.lid,)).fetchone()[0] == "NGC 7000"        # fakty kopii nowe
    assert _zeznanie(s.con, s.fid) == ("NGC6992", "NGC6992")          # zeznanie stare
    (w,) = _wstrzymania(s.con)
    assert (w["kind"], w["settled_at"], w["object_written"]) == ("commit", None, 1)
    assert [(r["status"], r["withheld_id"]) for r in _wpisy(s.con)] == [("failed", w["id"])]
    assert _zrodlo(s.con, s.fid) == "user_cleared" and _ev(s.con, "object.tombstone_cleared") == 0
    if inplace:
        assert s.con.execute("SELECT phase FROM inplace_op").fetchone()[0] == "synced"
        assert not scan._isolated(s.con, str(s.L))
    s.con.close()


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_gest_ta_kopia_prowadzi_dokancza_zapis(tmp_path, inplace):
    """Z4: zalecana droga naprawy (gest „Ta kopia prowadzi” na L) dokańcza zapis bez ręcznych
    statusów: zeznanie = karta L, wpisy 'applied', nagrobek zgaszony z parą commit/plik (cofnięcie go
    odtworzy), wstrzymanie `completed`. Falsyfikator: zdejmij `_settle_withheld_tx` z
    `adopt_testimony` - wpisy zostają 'failed', nagrobek żyje."""
    s = _scena(tmp_path, nagrobek=True)
    res = writeback.commit(s.con, "R", now=NOW, inplace=inplace)
    assert len(res.withheld) == 1, res
    wynik = lead_copy.lead_copy_gesture(s.con, s.lid, NOW)
    assert wynik.verdict == "adopted", wynik
    assert _zeznanie(s.con, s.fid) == ("NGC 7000", "NGC 7000")
    assert [r["status"] for r in _wpisy(s.con)] == ["applied"]
    assert _wstrzymania(s.con)[0]["settled_how"] == "completed"
    # Nagrobek zgaszony; pochodne gestu przypisały już obiekt z karty (źródło `header`).
    assert _zrodlo(s.con, s.fid) != "user_cleared" and _ev(s.con, "object.tombstone_cleared") == 1
    ures = writeback.undo(s.con, res.commit_id, now=NOW)            # cofnięcie odtwarza wykluczenie
    assert len(ures.restored) == 1, ures
    assert _zrodlo(s.con, s.fid) == "user_cleared"
    s.con.close()


def test_dostawa_dokancza_po_zniknieciu_drugiej_kopii(tmp_path):
    """Z4, droga automatu: druga kopia znika, etap Dostawy przejmuje zeznanie jedynej obecnej kopii -
    w tej samej transakcji rozlicza wstrzymanie. Falsyfikator jak w teście gestu."""
    s = _scena(tmp_path, nagrobek=True)
    assert len(writeback.commit(s.con, "R", now=NOW).withheld) == 1
    _bez_M(s)
    scan.adopt_orphan_testimony(s.con, now=NOW)
    assert _zeznanie(s.con, s.fid) == ("NGC 7000", "NGC 7000")
    assert [r["status"] for r in _wpisy(s.con)] == ["applied"]
    assert _wstrzymania(s.con)[0]["settled_how"] == "completed"
    assert _zrodlo(s.con, s.fid) is None
    s.con.close()


def test_pelny_odczyt_dociaga_zeznanie_z_kopii_wiodacej(tmp_path):
    """Z3/Z7: odcisk L w bazie jest już nowy, więc `refresh_location` przy kolejnym odczycie nie
    widzi zmiany. Przy żywej M odczyt L niczego nie domyka (dowód: zeznanie nadal nie jest L). Po
    zniknięciu M bramka wyboru wybiera L, a skan JAWNIE przepisuje zeznanie (event
    `header.refreshed` z powodem) i dopiero wtedy domyka. Falsyfikator: `dociagnij=False` w gałęzi
    skanu - zeznanie zostaje stare, wstrzymanie otwarte."""
    s = _scena(tmp_path, nagrobek=True)
    writeback.commit(s.con, "R", now=NOW)
    _wczytaj(s.con, s.L)                                          # M żyje - nic do domknięcia
    (w,) = _wstrzymania(s.con)              # skan potwierdzający nie dubluje wstrzymania (F10)
    assert w["settled_at"] is None
    assert _zeznanie(s.con, s.fid) == ("NGC6992", "NGC6992")
    _bez_M(s)
    przed = _ev(s.con, "header.refreshed")
    _wczytaj(s.con, s.L)
    assert _ev(s.con, "header.refreshed") == przed + 1
    assert "dociągnięte" in s.con.execute(
        "SELECT payload FROM event WHERE verb = 'header.refreshed' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert _zeznanie(s.con, s.fid) == ("NGC 7000", "NGC 7000")
    assert _wstrzymania(s.con)[0]["settled_how"] == "completed"
    assert [r["status"] for r in _wpisy(s.con)] == ["applied"] and _zrodlo(s.con, s.fid) is None
    s.con.close()


def test_nowsza_decyzja_reki_po_wstrzymaniu_zostaje(tmp_path):
    """Z5: przy otwartym wstrzymaniu człowiek przypisuje obiekt i wyklucza go PONOWNIE (nowe
    `object.cleared`). Dokończenie (pełny odczyt po zniknięciu M) domyka wpisy, ale nagrobka NIE gasi -
    to nowsza decyzja ręki, a powód to mówi. Falsyfikator: zdejmij porównanie `hand_version`
    w `_settle_withheld_tx` - nowy nagrobek gaśnie."""
    s = _scena(tmp_path, nagrobek=True)
    writeback.commit(s.con, "R", now=NOW)
    _nagrobek(s.con, s.fid)
    _bez_M(s)
    _wczytaj(s.con, s.L)
    (wpis,) = _wpisy(s.con)
    assert wpis["status"] == "applied" and "nowsza decyzja ręki" in wpis["reason"]
    assert _zrodlo(s.con, s.fid) == "user_cleared"
    assert _ev(s.con, "object.tombstone_cleared") == 0
    s.con.close()


def test_decyzja_reki_miedzy_zapisem_a_resynciem_nie_jest_gaszona(tmp_path, monkeypatch):
    """Z8: wersja decyzji ręki utrwalona PRZED pierwszym bajtem (backup), nie przy wstrzymaniu.
    Człowiek wyklucza obiekt ponownie dokładnie między podmianą pliku a re-synciem - wstrzymanie
    dziedziczy wersję z backupu (starszą), więc dokończenie gestem nie gasi nowego nagrobka.
    Falsyfikator: `_withhold_write_tx` liczy wersję ręki w chwili wstrzymania - dokończenie gasi."""
    s = _scena(tmp_path, nagrobek=True)
    prawdziwy = writeback._resync

    def _okno(*a, **kw):
        _nagrobek(s.con, s.fid)                                  # ręka w oknie zapis → re-sync
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_resync", _okno)
    res = writeback.commit(s.con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.withheld) == 1, res
    (w,) = _wstrzymania(s.con)
    kopia = s.con.execute("SELECT hand_version FROM header_backups").fetchone()[0]
    assert w["hand_version"] == kopia is not None
    assert lead_copy.lead_copy_gesture(s.con, s.lid, NOW).verdict == "adopted"
    assert _wstrzymania(s.con)[0]["settled_how"] == "completed"
    assert _zrodlo(s.con, s.fid) == "user_cleared"
    assert _ev(s.con, "object.tombstone_cleared") == 0
    s.con.close()


def test_przepiecie_lokacji_na_inna_klatke_nie_domyka(tmp_path):
    """Z9: po wstrzymaniu dane obrazu L zmieniają się przy tym samym nagłówku - skan przepina
    lokację na nową klatkę F2 (z zeznaniem z tego pliku). Kolejny pełny odczyt NIE domyka starego
    wstrzymania F1 (wpisy zostają 'failed', nagrobek F1 żyje), tylko zamyka je jako `superseded`.
    Falsyfikator: zdejmij CAS tożsamości w `_settle_withheld_tx` - wpisy F1 'applied'."""
    s = _scena(tmp_path, nagrobek=True)
    writeback.commit(s.con, "R", now=NOW)
    bajty = bytearray(s.L.read_bytes())
    bajty[2880] ^= 0xFF                       # pierwszy bajt danych - nagłówek bajt w bajt ten sam
    s.L.write_bytes(bytes(bajty))
    _wczytaj(s.con, s.L)                                          # przepięcie na F2
    assert _lok(s.con, s.L)["frame_id"] != s.fid
    assert _lok(s.con, s.L)["header_hash"] == _wstrzymania(s.con)[0]["header_hash"]
    _wczytaj(s.con, s.L)                                          # ta sama tożsamość F2
    assert _wstrzymania(s.con)[0]["settled_how"] == "superseded"
    assert [r["status"] for r in _wpisy(s.con)] == ["failed"]
    assert _zrodlo(s.con, s.fid) == "user_cleared"
    s.con.close()


def test_nowszy_zapis_zastepuje_stare_wstrzymanie(tmp_path):
    """Z10: W1 wstrzymany, potem (M zniknęła) W2 zapisuje ten sam plik skutecznie. Re-sync W2 to
    pełny odczyt z innym nagłówkiem niż W1 - W1 zamyka się jako `superseded` (wpisy W1 zostają
    'failed', nic nie udaje 'applied'), a nie wisi w otwartych na zawsze. Falsyfikator: zdejmij
    gałąź „odcisk odczytu ≠ odcisk zapisu” - W1 zostaje otwarte."""
    s = _scena(tmp_path)
    writeback.commit(s.con, "R", now=NOW)
    _bez_M(s)
    _stage(s.con, "R2", s.lid, "NGC 7001")
    res = writeback.commit(s.con, "R2", now=NOW)
    assert len(res.applied) == 1 and not res.withheld, res
    (w1,) = _wstrzymania(s.con)
    assert w1["settled_how"] == "superseded"
    assert [r["status"] for r in _wpisy(s.con, "R")] == ["failed"]
    assert _zeznanie(s.con, s.fid) == ("NGC 7001", "NGC 7001")
    s.con.close()


# ============================================================ rekoncyliacja i skan potwierdzający


def test_rekoncyliacja_po_smierci_po_podmianie_wstrzymuje_zamiast_applied(tmp_path, monkeypatch):
    """F8: proces ginie po podmianie (AR-40), druga kopia już jest. Ponowny commit rozstrzyga backup
    z dyskiem - dawniej 'applied' „potwierdzony z dysku” i zgaszony nagrobek przed wjazdem rekordu.
    Teraz wpisy próby rozlicza `settle_backup_attempt` PO wjeździe: 'withheld', nagrobek żyje,
    zero zdarzeń-widm. Falsyfikator: `settle_backup_attempt` traktuje każdy wjazd jak dowód."""
    s = _scena(tmp_path, nagrobek=True)
    prawdziwy = writeback._podmien

    def _f(tmp, path, replace_guard, odcisk, po_podmianie=None, **kw):
        prawdziwy(tmp, path, replace_guard, odcisk, None, **kw)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)
    with pytest.raises(_Smierc):
        writeback.commit(s.con, "R", now=NOW)
    monkeypatch.undo()
    res = writeback.commit(s.con, "R", now=NOW)
    assert not res.applied and len(res.withheld) == 1, res
    assert [r["status"] for r in _wpisy(s.con)] == ["failed"]
    assert s.con.execute("SELECT pending_since FROM header_backups").fetchone()[0] is None
    assert _zrodlo(s.con, s.fid) == "user_cleared" and _ev(s.con, "object.tombstone_cleared") == 0
    s.con.close()


def test_skan_potwierdzajacy_bez_dowodu_zeznania_wstrzymuje(tmp_path, monkeypatch):
    """F10: commit drogą atomową, którego re-sync padł ('failed' po podmianie), potwierdza później
    skan (AR-38 (2)). Przy drugiej kopii bez dowodu zeznania nie wolno zrobić 'applied' z gaszeniem
    nagrobka - wpisy przechodzą w wstrzymanie. Falsyfikator: `confirm_failed_commit_by_scan`
    ignoruje `testimony_ok`."""
    s = _scena(tmp_path, nagrobek=True)
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    res = writeback.commit(s.con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.failed) == 1, res
    assert [(r["status"], r["withheld_id"]) for r in _wpisy(s.con)] == [("failed", None)]
    _wczytaj(s.con, s.L)
    (wpis,) = _wpisy(s.con)
    assert wpis["status"] == "failed" and wpis["withheld_id"] is not None
    assert _zrodlo(s.con, s.fid) == "user_cleared"
    s.con.close()


# ============================================================ cofnięcie


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_cofniecie_przy_kopii_ktora_przestala_prowadzic(tmp_path, inplace):
    """Q2: commit przy jedynej kopii przechodzi do zeznania; potem wjeżdża druga kopia o zeznaniu
    po commicie. Cofnięcie przywraca nagłówek L, ale zeznanie zostaje przy M - wynik 'restored'
    z kodem, `UndoResult.withheld`, wstrzymanie cofnięcia otwarte. Falsyfikator: hook cofnięcia
    ignoruje dowód zeznania - cofnięcie milczy o tym, że zeznanie nie wróciło."""
    con = db.open_db(str(tmp_path / "h.db"))
    L = _fits(tmp_path / "A" / "a.fits")
    _wczytaj(con, L)
    lok = _lok(con, L)
    _stage(con, "R", lok["id"], "NGC 7000")
    res = writeback.commit(con, "R", now=NOW, inplace=inplace)
    assert len(res.applied) == 1 and _zeznanie(con, lok["frame_id"]) == ("NGC 7000", "NGC 7000")
    M = tmp_path / "B" / "a.fits"
    M.parent.mkdir(parents=True)
    shutil.copyfile(L, M)
    _wczytaj(con, M)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and ures.withheld == ures.restored, ures
    assert ures.withheld[0].code == writeback.CODE_ZEZNANIE_WSTRZYMANE
    assert "zeznanie klatki NIE wróciło" in ures.withheld[0].reason
    assert fits.getheader(str(L))["OBJECT"] == "NGC6992"
    (w,) = _wstrzymania(con)
    assert (w["kind"], w["settled_at"]) == ("undo", None)
    con.close()


def test_cofniecie_commitu_wstrzymanego_zamyka_go_bez_ostrzezenia(tmp_path):
    """Cofnięcie commitu, którego zeznanie nigdy nie przyjęło: nic z zeznania nie trzeba cofać -
    'restored' bez kodu, wstrzymanie `undone` (nie `superseded`), żadnego wstrzymania cofnięcia.
    Falsyfikator: zdejmij `cofany_commit` z re-syncu cofnięcia - wstrzymanie zamyka rozliczenie
    skanu jako `superseded`."""
    s = _scena(tmp_path)
    res = writeback.commit(s.con, "R", now=NOW)
    ures = writeback.undo(s.con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.withheld, ures
    assert ures.restored[0].code is None
    assert [w["settled_how"] for w in _wstrzymania(s.con)] == ["undone"]
    s.con.close()


# ============================================================ „Zmień obiekt…” i jego cofnięcie


def _scena_gestu(tmp_path):
    from test_object_change_write import _Scena
    s = _Scena(tmp_path)
    plan = s.plan(pozycje=[s.pozycja(0)])                         # sam FITS
    return s, s.stage(plan)


def test_zmien_obiekt_karta_wstrzymana_dokonczona_gestem(tmp_path, monkeypatch):
    """Z4/Z6: druga kopia wjeżdża między krokiem bazy a kartą. Pozycja 'failed' (stan częściowy
    w Porządkach) z prawdziwym powodem, wynik gestu w kubełku `withheld`; gest „Ta kopia prowadzi”
    na przeniesionym pliku domyka i wpisy, i pozycję - przebieg znika z Porządków. Falsyfikator:
    wstrzymanie bez `item_id` - pozycja zostaje 'failed', przebieg wisi."""
    from horreum.gui import queries
    s, run = _scena_gestu(tmp_path)
    prawdziwa = repo.apply_object_change_item

    def _baza_potem_kopia(con, **kw):
        wynik = prawdziwa(con, **kw)
        kopia = tmp_path / "INNE" / "a.fits"
        kopia.parent.mkdir(exist_ok=True)
        shutil.copyfile(s.stare[0], kopia)
        _wczytaj(con, kopia)
        return wynik
    monkeypatch.setattr(repo, "apply_object_change_item", _baza_potem_kopia)
    wynik = writeback.commit_object_change(s.con, run, now=NOW)
    monkeypatch.undo()
    assert not wynik.applied and len(wynik.withheld) == 1, wynik
    assert "zeznanie klatki NIE przyjęło zapisu" in wynik.withheld[0].reason
    (poz,) = s.con.execute("SELECT status FROM pending_object_change").fetchall()
    assert poz[0] == "failed" and run in queries.interrupted_object_change_runs(s.con)
    lid = _lok(s.con, s.nowe[0])["id"]
    assert lead_copy.lead_copy_gesture(s.con, lid, NOW).verdict == "adopted"
    assert s.con.execute("SELECT status FROM pending_object_change").fetchone()[0] == "applied"
    assert run not in queries.interrupted_object_change_runs(s.con)
    s.con.close()


def test_cofniecie_gestu_niesie_wstrzymanie_po_wznowieniu(tmp_path, monkeypatch):
    """Z6: cofnięcie gestu, którego karta wraca do pliku, a zeznanie zostaje przy drugiej kopii.
    Proces ginie po fazie karty (przy powrocie pliku); wznowienie cofnięcia nie ma już wyniku fazy
    karty, a mimo to pozycja wraca z kodem wstrzymania, a wynik gestu niesie ją w `withheld`.
    Falsyfikator: `_cofnij_pozycje` bez odczytu wstrzymania z bazy - wynik po wznowieniu milczy."""
    s, run = _scena_gestu(tmp_path)
    assert len(writeback.commit_object_change(s.con, run, now=NOW).applied) == 1
    kopia = tmp_path / "INNE" / "a.fits"
    kopia.parent.mkdir()
    shutil.copyfile(s.nowe[0], kopia)                             # druga kopia PO zapisie gestu
    _wczytaj(s.con, kopia)
    prawdziwy = writeback._przenies_wstecz

    def _smierc(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_przenies_wstecz", _smierc)
    with pytest.raises(_Smierc):
        writeback.undo_object_change(s.con, run, now=NOW)
    monkeypatch.setattr(writeback, "_przenies_wstecz", prawdziwy)
    assert s.con.execute("SELECT undo_phase FROM pending_object_change").fetchone()[0] == "card"
    cof = writeback.undo_object_change(s.con, run, now=NOW)
    assert len(cof.applied) == 1 and cof.withheld == cof.applied, cof
    assert cof.withheld[0].code == writeback.CODE_ZEZNANIE_WSTRZYMANE
    s.con.close()


# ============================================================ zdania powierzchni


def test_zdanie_wyniku_mowi_o_zapisie_wstrzymanym(tmp_path):
    """Z4: plik zapisany z zeznaniem wstrzymanym nie może dać samego „0 zapisanych” - zdanie niesie
    człon wstrzymania i jego powód; cofnięcie - człon „bez powrotu zeznania”. Falsyfikator: człon
    zdjęty z `zdanie_wyniku_zapisu` / `zdanie_undo_kart`."""
    pytest.importorskip("PySide6")
    from horreum.gui.wb_worker import zdanie_undo_kart, zdanie_wyniku_zapisu
    fr = writeback.FileResult(1, "a.fits", "withheld", "plik ZAPISANY, ale zeznanie…",
                              code=writeback.CODE_ZEZNANIE_WSTRZYMANE)
    zdanie = zdanie_wyniku_zapisu(writeback.CommitResult("r", 3, [], [], [], [], withheld=[fr]),
                                  "grid.wb.applied")
    assert i18n.t("grid.wb.withheld", n=1) in zdanie and "plik ZAPISANY" in zdanie, zdanie
    cof = zdanie_undo_kart(writeback.UndoResult(3, [fr], [], [], withheld=[fr]))
    assert i18n.t("grid.wb.undo_withheld", n=1) in cof, cof


# ============================================================ poprawki bramki (B1..B12)


def test_nan_w_polu_goracym_nie_wstrzymuje_jedynej_kopii(tmp_path):
    """B7: XISF z `CCD-TEMP='NaN'` - koercja daje `nan`, SQLite trzyma NULL. Porównanie w Pythonie
    (`nan != None`) uznawało zeznanie za niezgodne zawsze: zapis JEDYNEJ kopii kończył się
    wiecznym wstrzymaniem. Dowód porównuje teraz w SQLite (bindowanie jak przy zapisie).
    Falsyfikator: porównanie pól gorących wraca do Pythona - wynik 'withheld'."""
    from test_writeback import _xisf
    con = db.open_db(str(tmp_path / "h.db"))
    p = _xisf(tmp_path, "n.xisf", props="", pad=512,
              keywords=(("IMAGETYP", "'Light'"), ("OBJECT", "'NGC6992'"), ("CCD-TEMP", "NaN")))
    _wczytaj(con, p)
    lok = _lok(con, p)
    _stage(con, "R", lok["id"], "NGC 7000")
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and not res.withheld, res
    assert _wstrzymania(con) == []
    con.close()


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_cofniecie_po_dokonczonym_wstrzymaniu_ostrzega(tmp_path, inplace):
    """B2: zapis L wstrzymany, potem dokończony gestem (`completed`); M zmienia nagłówek poza
    programem i człowiek wskazuje M. Cofnięcie L przywraca plik, a zeznanie zostaje przy M - to jest
    cofnięcie z zeznaniem wstrzymanym, mimo że commit MA historię wstrzymania. Falsyfikator: wyjątek
    cofnięcia wiązany z samym istnieniem wstrzymania commitu - wynik zwykłe 'restored'."""
    s = _scena(tmp_path)
    res = writeback.commit(s.con, "R", now=NOW, inplace=inplace)
    assert lead_copy.lead_copy_gesture(s.con, s.lid, NOW).verdict == "adopted"
    fits.setval(str(s.M), "OBJECT", value="M31")
    _wczytaj(s.con, s.M)
    assert lead_copy.lead_copy_gesture(s.con, s.mid, NOW).verdict == "adopted"
    ures = writeback.undo(s.con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and ures.withheld == ures.restored, ures
    assert [(w["kind"], w["settled_how"]) for w in _wstrzymania(s.con)] == [
        ("commit", "completed"), ("undo", None)]
    s.con.close()


def _stage_karte(con, run, lid, keyword, wartosc):
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id=run, location_id=lid, keyword=keyword, idx=0, op="set",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=hh)


def test_wstrzymanie_widoczne_w_porzadkach_i_w_gescie(tmp_path):
    """B3: karta spoza ośmiu pól porównania kopii (`OBSERVER`) - kopie zostają „zgodne”, więc ani
    „Kopie niezgodne”, ani „Zeznanie z nieobecnej kopii” klatki nie widzą. Otwarte wstrzymanie ma
    własny wiersz Porządków (licznik ze stanu) i otwiera gest „Ta kopia prowadzi”; gest domyka je
    i wiersz pustoszeje. Falsyfikator: `lead_copy.awaiting_hand` bez predykatu wstrzymań - gest
    niedostępny, zapis bez drogi domknięcia."""
    from horreum.gui import queries
    con = db.open_db(str(tmp_path / "h.db"))
    L = _fits(tmp_path / "A" / "a.fits")
    _wczytaj(con, L)
    lok = _lok(con, L)
    _stage_karte(con, "R", lok["id"], "OBSERVER", "ZS")
    M = tmp_path / "B" / "a.fits"
    M.parent.mkdir(parents=True)
    shutil.copyfile(L, M)
    _wczytaj(con, M)
    assert len(writeback.commit(con, "R", now=NOW).withheld) == 1
    fid = lok["frame_id"]
    assert fid not in queries.copy_conflict_frame_ids(con)
    assert queries.withheld_testimony_frame_ids(con) == {fid}
    assert queries.tasks_state(con)["withheld_testimony_frames"] == 1
    assert lead_copy.awaiting_hand(con, fid)
    assert lead_copy.lead_copy_gesture(con, lok["id"], NOW).verdict == "adopted"
    assert queries.withheld_testimony_frame_ids(con) == set()
    assert not lead_copy.awaiting_hand(con, fid)
    con.close()


def _gest_z_druga_kopia(tmp_path, monkeypatch, s):
    """Druga kopia klatki wjeżdża między krokiem bazy gestu a kartą."""
    prawdziwa = repo.apply_object_change_item

    def _baza_potem_kopia(con, **kw):
        wynik = prawdziwa(con, **kw)
        kopia = tmp_path / "INNE" / "a.fits"
        kopia.parent.mkdir(exist_ok=True)
        shutil.copyfile(s.stare[0], kopia)
        _wczytaj(con, kopia)
        return wynik
    monkeypatch.setattr(repo, "apply_object_change_item", _baza_potem_kopia)


def test_pozycja_gestu_nie_jest_nadpisana_po_dokonczeniu(tmp_path, monkeypatch):
    """B4: dokończenie (gest na zapisanej kopii) przychodzi między utworzeniem wstrzymania a powrotem
    sterownika gestu. Status pozycji powstaje razem ze wstrzymaniem, a sterownik go nie przestawia -
    pozycja zostaje 'applied'. Falsyfikator: sterownik ustawia 'failed' po zapisie karty - pozycja
    'failed' na zawsze (wstrzymanie już zamknięte, przebieg wisi w Porządkach)."""
    from horreum.gui import queries
    s, run = _scena_gestu(tmp_path)
    _gest_z_druga_kopia(tmp_path, monkeypatch, s)
    prawdziwy = writeback._zapisz_lokacje

    def _dokonczenie_w_oknie(con, stan, location_id, rows, **kw):
        zapis = prawdziwy(con, stan, location_id, rows, **kw)
        if zapis.wynik.status == "withheld":
            assert lead_copy.lead_copy_gesture(con, location_id, NOW).verdict == "adopted"
        return zapis
    monkeypatch.setattr(writeback, "_zapisz_lokacje", _dokonczenie_w_oknie)
    wynik = writeback.commit_object_change(s.con, run, now=NOW)
    monkeypatch.undo()
    assert len(wynik.withheld) == 1, wynik
    assert s.con.execute("SELECT status FROM pending_object_change").fetchone()[0] == "applied"
    assert run not in queries.interrupted_object_change_runs(s.con)
    s.con.close()


def test_cli_finish_melduje_wstrzymanie_i_kod_1(tmp_path, monkeypatch, capsys):
    """B5: `object-change finish` z kartą wstrzymaną - osobny kubeł w raporcie, droga naprawy
    i kod wyjścia 1 (jak `header-fix`). Falsyfikator: raport bez kubła - „0 zmienionych” i kod 0."""
    from horreum import cli
    s, run = _scena_gestu(tmp_path)
    s.con.close()
    _gest_z_druga_kopia(tmp_path, monkeypatch, s)
    kod = cli.main(["object-change", "finish", str(tmp_path / "h.db"), run])
    out = capsys.readouterr().out
    assert kod == 1, out
    assert "z zeznaniem wstrzymanym 1" in out and "Ta kopia prowadzi" in out, out


def test_zdanie_gestu_dokonczenia_mowi_o_wstrzymaniu():
    """B6: wynik gestu „Dokończ zapis” ze wstrzymanym zeznaniem to człon `grid.wb.withheld`, nie
    „nieudany”. Falsyfikator: 'withheld' liczone jako błąd w `_zdanie_gestu_zapisu`."""
    pytest.importorskip("PySide6")
    from horreum.gui.grid_model import _zdanie_gestu_zapisu
    fr = writeback.FileResult(1, "A\\a.fits", "withheld", "plik ZAPISANY, ale zeznanie…",
                              code=writeback.CODE_ZEZNANIE_WSTRZYMANE)
    zdanie = _zdanie_gestu_zapisu("finish_inplace", SimpleNamespace(results=[fr], cancelled=False))
    assert i18n.t("grid.wb.withheld", n=1) in zdanie, zdanie
    assert i18n.t_plural("grid.inplace.failed", 1) not in zdanie, zdanie


def test_dociagniecie_nie_przeglosowuje_reki(tmp_path):
    """B8: wstrzymanie → człowiek wskazuje M („Ta kopia prowadzi”) → M znika → pełny odczyt L.
    Skan nie przepisuje zeznania z L ponad decyzję ręki (AR-4): zeznanie M i fakt ręki zostają,
    wstrzymanie czeka na człowieka (wiersz Porządków). Falsyfikator: dociągnięcie bez pytania
    o zeznanie z ręki - zeznanie L, fakt ręki przesłonięty."""
    from horreum.gui import queries
    s = _scena(tmp_path)
    writeback.commit(s.con, "R", now=NOW)
    assert lead_copy.lead_copy_gesture(s.con, s.mid, NOW).verdict in ("adopted", "confirmed")
    _bez_M(s)
    _wczytaj(s.con, s.L)
    assert _zeznanie(s.con, s.fid) == ("NGC6992", "NGC6992")
    assert queries.hand_testimony_frame_ids(s.con, [s.fid]) == {s.fid}
    assert _wstrzymania(s.con)[0]["settled_at"] is None
    s.con.close()


def test_rekoncyliacja_backupu_nie_bierze_wpisow_wstrzymanych(tmp_path):
    """B9: jeden właściciel stanu - wpis z wiązaniem wstrzymania nie jest kandydatem rekoncyliacji
    backupu (`settle_pending_backup`), nawet gdy backup niepotwierdzony go wymienia. Falsyfikator:
    zdejmij `withheld_id IS NULL` - wpis wraca do 'pending' i wypada spod wstrzymania."""
    s = _scena(tmp_path)
    writeback.commit(s.con, "R", now=NOW)
    wpisy = writeback.pending_for_run(s.con, "R")
    drugi = repo.insert_commit(s.con, run_id="R", now=NOW, summary="run R")
    bid = repo.insert_header_backup(s.con, commit_id=drugi, location_id=s.lid, hdu_index=0,
                                    header_text="x", post_hash="p", pending_since=NOW,
                                    pending_rows=tuple(wpisy))
    assert repo.settle_pending_backup(s.con, backup_id=bid, replaced=True, now=NOW) == []
    assert [(r["status"], r["withheld_id"] is not None) for r in _wpisy(s.con)] == [
        ("failed", True)]
    s.con.close()


def test_wersja_reki_nieznana_mowi_prawde(tmp_path):
    """B10: wstrzymanie z backupu sprzed 0037 (wersja decyzji ręki nieznana) przy klatce
    `user_cleared` - dokończenie zostawia nagrobek z powodem „sprzed aktualizacji nieznana”, nie
    „nowsza decyzja”. Falsyfikator: brak wersji traktowany jak nowsza decyzja."""
    s = _scena(tmp_path, nagrobek=True)
    writeback.commit(s.con, "R", now=NOW)
    s.con.execute("UPDATE withheld_write SET hand_version = NULL")
    s.con.commit()
    assert lead_copy.lead_copy_gesture(s.con, s.lid, NOW).verdict == "adopted"
    (wpis,) = _wpisy(s.con)
    assert wpis["status"] == "applied" and "sprzed aktualizacji nieznana" in wpis["reason"], wpis
    assert _zrodlo(s.con, s.fid) == "user_cleared"
    s.con.close()


def _jedna_kopia_z_nagrobkiem(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    L = _fits(tmp_path / "A" / "a.fits")
    _wczytaj(con, L)
    lok = _lok(con, L)
    _nagrobek(con, lok["frame_id"])
    _stage(con, "R", lok["id"], "NGC 7000")
    return con, L, lok


def test_skan_potwierdzajacy_nie_gasi_nowszej_decyzji_reki(tmp_path, monkeypatch):
    """B12, droga AR-38 (2): commit padł po podmianie (re-sync), człowiek wyklucza obiekt ponownie,
    skan potwierdza zapis z dowodem zeznania - wpisy 'applied', ale nowszy nagrobek ŻYJE, a powód to
    mówi. Falsyfikator: gaszenie nagrobka w `confirm_failed_commit_by_scan` bez wersji ręki."""
    con, L, lok = _jedna_kopia_z_nagrobkiem(tmp_path)
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    assert len(writeback.commit(con, "R", now=NOW).failed) == 1
    monkeypatch.undo()
    _nagrobek(con, lok["frame_id"])
    _wczytaj(con, L)
    (wpis,) = _wpisy(con)
    assert wpis["status"] == "applied" and "nowsza decyzja ręki" in wpis["reason"], wpis
    assert _zrodlo(con, lok["frame_id"]) == "user_cleared"
    assert _ev(con, "object.tombstone_cleared") == 0
    con.close()


def test_rekoncyliacja_nie_gasi_nowszej_decyzji_reki(tmp_path, monkeypatch):
    """B12, droga AR-40: proces zginął po podmianie, człowiek wyklucza obiekt ponownie, ponowny commit
    rozstrzyga backup z dyskiem (dowód zeznania jest) - wpisy 'applied', nowszy nagrobek ŻYJE.
    Falsyfikator: gaszenie w `settle_backup_attempt` bez wersji ręki."""
    con, L, lok = _jedna_kopia_z_nagrobkiem(tmp_path)
    prawdziwy = writeback._podmien

    def _f(tmp, path, replace_guard, odcisk, po_podmianie=None, **kw):
        prawdziwy(tmp, path, replace_guard, odcisk, None, **kw)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    _nagrobek(con, lok["frame_id"])
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1, res
    (wpis,) = _wpisy(con)
    assert "nowsza decyzja ręki" in wpis["reason"], wpis
    assert _zrodlo(con, lok["frame_id"]) == "user_cleared"
    assert _ev(con, "object.tombstone_cleared") == 0
    con.close()


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
@pytest.mark.parametrize("okno, zdanie", [
    ("nowa_decyzja", "nowsza decyzja ręki"),
    ("wersja_nieznana", "sprzed aktualizacji nieznana"),
])
def test_zwykly_zapis_nie_gasi_decyzji_reki_z_okna(tmp_path, monkeypatch, inplace, okno, zdanie):
    """Z8 na zwykłej ścieżce 'applied' (jedna kopia, zeznanie przechodzi): między zapisem pliku
    a transakcją re-syncu człowiek wyklucza obiekt ponownie (nowe `object.cleared`) albo backup nie
    niesie wersji decyzji ręki (sprzed 0037). Zapis 'applied', ale nagrobek ŻYJE, a powód wpisu
    i wyniku mówi prawdę. Falsyfikator: bezwarunkowe zgaszenie w `_zamknij` (atomowo) albo
    w `finish_inplace_op` (w miejscu) - nagrobek zgaszony mimo nowszej/nieznanej decyzji."""
    con, L, lok = _jedna_kopia_z_nagrobkiem(tmp_path)
    prawdziwy = writeback._resync

    def _okno(*a, **kw):
        if okno == "nowa_decyzja":
            _nagrobek(con, lok["frame_id"])
        else:
            con.execute("UPDATE header_backups SET hand_version = NULL")
            con.commit()
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_resync", _okno)
    res = writeback.commit(con, "R", now=NOW, inplace=inplace)
    monkeypatch.undo()
    (fr,) = res.applied
    assert bool(res.in_place) is inplace and zdanie in (fr.reason or ""), res
    (wpis,) = _wpisy(con)
    assert wpis["status"] == "applied" and zdanie in wpis["reason"], wpis
    assert _zrodlo(con, lok["frame_id"]) == "user_cleared"
    assert _ev(con, "object.tombstone_cleared") == 0
    con.close()
