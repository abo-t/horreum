"""Cofnięcie commitu kart PRZERWANE - fakt rdzenia o plikach, których bieg nie dotknął, i droga powrotu
ze STANU (AR-318).

Co pilnujemy:
  * przerwanie liczy w rdzeniu pliki NIETKNIĘTE (`UndoResult.untouched`): bez śladu próby cofnięcia,
    bez nowszego żywego zapisu, baza opisuje wynik commitu, a ślad musiałby powstać (droga w miejscu
    albo commit atomowy od chwili, w której każde cofnięcie atomowe zostawia ślad); reszta „wymaga
    sprawdzenia”;
  * wiersz Porządków (`queries.niedokonczone_cofniecia_kart`) - commit z JAKIMKOLWIEK śladem próby
    i plikami, które wciąż są wynikiem commitu; bez przebiegów zmiany obiektu i bez lokacji nadpisanych
    nowszym zapisem;
  * NOWSZY ŻYWY ZAPIS (A → B → A tą samą kartą): cofnięcie starszego commitu odmawia z kodem
    `undo_newer_write`, bajty lokacji bez zmian.
Pliki prawdziwe (astropy) w `tmp_path`."""
from __future__ import annotations

import hashlib
import shutil

import pytest
from astropy.io import fits

from horreum import db, repo, writeback
from horreum.gui import queries
from test_writeback_inplace import _fits, _loc, _scan_in

# Granica śladu cofnięcia to chwila migracji TEJ bazy (`writeback._granica_sladu`, `migration_log`) -
# baza testu powstaje przy biegu testu, więc zegar commitów „po granicy” stoi w przyszłości, a „przed
# granicą” - przed dniem, w którym ten kod powstał.
NOW = "2100-01-01T10:00:00+00:00"
PRZED_SLADEM = "2026-10-01T10:00:00+00:00"


def _sha(p):
    return hashlib.sha1(p.read_bytes()).hexdigest()


def _karta(con, run_id, lid, wartosc):
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=wartosc, new_type="str", new_comment=None,
                       expected_header_hash=hh)


def _baza(tmp_path, *, n=3, inplace, now=NOW):
    """`(con, commit_id, pliki, lokacje, bajty sprzed commitu)` - `n` plików jednym commitem kart."""
    con = db.open_db(str(tmp_path / "h.db"))
    pliki, lokacje, przed = [], [], []
    for i in range(n):
        p = _fits(tmp_path / f"f{i}.fits", seed=i)
        _scan_in(con, p)
        lid = _loc(con, p)["id"]
        _karta(con, "R", lid, "NGC 6992 X")
        pliki.append(p)
        lokacje.append(lid)
        przed.append(p.read_bytes())
    res = writeback.commit(con, "R", now=now, inplace=inplace)
    assert len(res.applied) == n and res.commit_id is not None, res
    assert bool(res.in_place) == inplace, res
    return con, res.commit_id, pliki, lokacje, przed


def _po(n):
    """`should_cancel`, które przerywa przed backupem numer `n` (0 = przed pierwszym)."""
    pytania = []

    def _pytaj():
        pytania.append(1)
        return len(pytania) > n
    return _pytaj


INPLACE = pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])


# ============================================================ fakt rdzenia: pliki nietknięte


def _baza_z_wersji(sciezka, wersja):
    """Baza zmigrowana do `wersja` WCZEŚNIEJSZYM przebiegiem (bez dziennika), potem `db.open_db` - przebieg,
    w którym wchodzi dziennik migracji."""
    con = db.connect(str(sciezka))
    for v, plik in db.MIGRATIONS:
        if v <= wersja:
            db._apply_migration(con, v, db._migration_sql(plik))
    con.close()
    return db.open_db(str(sciezka))


@pytest.mark.parametrize("z_wersji", [43, 46])
def test_granica_sladu_to_chwila_migracji_tej_bazy(tmp_path, z_wersji):
    """Dziennik migracji (0047): baza z v43 dostaje 0044..0047 jednym przebiegiem - jedna chwila,
    granica = chwila 0047, równa chwili 0044; baza z v46 nie ma chwili 0044 - granica = chwila 0047. Commit
    zapisany PO granicy, bez śladu próby → „nietknięty”; zapisany po dacie powstania kodu, ale PRZED
    migracją tej bazy → „wymaga sprawdzenia”. Falsyfikator: granica ze stałej daty kodu zamiast z bazy
    (commit z 2026-10-20 byłby „nietknięty”)."""
    con = _baza_z_wersji(tmp_path / "h.db", z_wersji)
    dziennik = dict(con.execute("SELECT version, applied_at FROM migration_log").fetchall())
    oczekiwane = set(range(44, 49)) if z_wersji == 43 else {47, 48}
    assert set(dziennik) == oczekiwane, dziennik
    assert len(set(dziennik.values())) == 1, dziennik       # jeden przebieg - jedna chwila
    assert writeback._granica_sladu(con) == dziennik[min(oczekiwane)]
    con.close()
    for kiedy, oczekiwany in (("2026-10-20T00:00:00+00:00", 0), (NOW, 1)):
        kat = tmp_path / kiedy[:4]
        kat.mkdir()
        shutil.copy2(tmp_path / "h.db", kat / "h.db")
        con = db.open_db(str(kat / "h.db"))
        p = _fits(kat / "f.fits", seed=1)
        _scan_in(con, p)
        _karta(con, "R", _loc(con, p)["id"], "NGC 6992 X")
        c = writeback.commit(con, "R", now=kiedy, inplace=False)
        u = writeback.undo(con, c.commit_id, now=NOW, should_cancel=_po(0))
        assert u.remaining == 1 and u.untouched == oczekiwany, (kiedy, u)
        con.close()


@INPLACE
def test_przerwane_cofniecie_liczy_pliki_nietkniete(tmp_path, inplace):
    """Przerwanie przed pierwszym backupem: 3 z 3 nietknięte; po pierwszym pliku: 2 z 2 - ten bieg ich
    nie dotknął, śladu wcześniejszej próby nie ma, a baza opisuje wynik commitu. Bez przerwania
    `untouched` = `None`. Falsyfikator: `untouched` niepoliczone albo liczone bez warunku nagłówka."""
    con, cid, pliki, _l, przed = _baza(tmp_path, inplace=inplace)
    calosc = writeback.undo(con, cid, now=NOW, should_cancel=_po(0))
    assert calosc.cancelled and calosc.remaining == 3 and calosc.untouched == 3, calosc
    czesc = writeback.undo(con, cid, now=NOW, should_cancel=_po(1))
    assert len(czesc.restored) == 1 and czesc.remaining == 2 and czesc.untouched == 2, czesc
    assert pliki[0].read_bytes() == przed[0]
    pelne = writeback.undo(con, cid, now=NOW)
    assert pelne.complete and pelne.untouched is None, pelne
    con.close()


def test_commit_atomowy_sprzed_sladu_cofniecia_wymaga_sprawdzenia(tmp_path):
    """Commit atomowy zapisany przed chwilą, od której każde cofnięcie atomowe zostawia ślad: jego
    cofnięcie mogło umrzeć między podmianą a re-synciem bez śladu, więc „nietknięty” byłby obietnicą
    bez dowodu - wszystkie trzy „wymagają sprawdzenia”. Falsyfikator: brak warunku granicy →
    `untouched == 3`."""
    con, cid, _p, _l, _b = _baza(tmp_path, inplace=False, now=PRZED_SLADEM)
    u = writeback.undo(con, cid, now=NOW, should_cancel=_po(0))
    assert u.remaining == 3 and u.untouched == 0, u
    con.close()


def test_commit_w_miejscu_sprzed_sladu_cofniety_przez_fallback_wymaga_sprawdzenia(tmp_path, monkeypatch):
    """Commit zapisany W MIEJSCU przed granicą śladu: plik dostał nowy inode (ta sama treść), więc jego
    cofnięcie poszło drogą atomową (`restore_inplace` → `Fallback` przed dziennikiem operacji), podmieniło
    plik i umarło przed re-synciem; ślad tej drogi usunięty - tak wyglądało cofnięcie sprzed 0044. Na
    dysku leży plik sprzed zapisu, baza dalej opisuje wynik commitu, śladu brak. Przerwanie przed
    pierwszym backupem: nic nie jest „nietknięte”. Falsyfikator: „nietknięty” z samej operacji `commit`
    w miejscu → `untouched == 3`, a plik 0 jest już cofnięty."""
    import os
    import shutil

    class _Smierc(BaseException):
        """Śmierć procesu - nie `Exception`, więc pisarz jej nie łapie."""

    con, cid, pliki, _l, przed = _baza(tmp_path, inplace=True, now=PRZED_SLADEM)
    kopia = pliki[0].with_suffix(".kopia")
    shutil.copy2(pliki[0], kopia)
    os.replace(kopia, pliki[0])                         # ta sama treść, nowy plik (inny inode)

    def _umiera(*_a, **_kw):
        raise _Smierc()
    with monkeypatch.context() as m:
        m.setattr(writeback, "_resync", _umiera)
        with pytest.raises(_Smierc):
            writeback.undo(con, cid, now=NOW)
    assert pliki[0].read_bytes() == przed[0], "cofnięcie nie poszło drogą atomową do podmiany"
    assert con.execute("SELECT count(*) FROM inplace_op WHERE kind = 'undo'").fetchone()[0] == 0
    con.execute("DELETE FROM atomic_undo")
    con.commit()
    u = writeback.undo(con, cid, now=NOW, should_cancel=_po(0))
    assert u.remaining == 3 and u.untouched == 0, u
    con.close()


def _slad_w_miejscu(con, cid, lid):
    op_c = writeback._ostatnia_operacja(con, cid, lid, "commit")
    repo.begin_inplace_undo(con, commit_id=cid, location_id=lid,
                            spec=writeback._spec_z_operacji(op_c), now=NOW)


def _slad_atomowy(con, cid, lid, p, wynik):
    """Ślad cofnięcia atomowego BEZ `synced_at` - śmierć między podmianą a re-synciem: na dysku leży
    plik sprzed commitu (`wynik`), baza dalej opisuje wynik commitu."""
    b = con.execute("SELECT id FROM header_backups WHERE commit_id = ? AND location_id = ?",
                    (cid, lid)).fetchone()
    zrodlo = p.read_bytes()
    p.write_bytes(wynik)
    repo.record_atomic_undo(
        con, backup_id=b["id"], result_sha1=hashlib.sha1(wynik).hexdigest(), result_size=len(wynik),
        result_hash=writeback._post_hash(str(p)), byte_exact=1,
        source_sha1=hashlib.sha1(zrodlo).hexdigest(), source_size=len(zrodlo),
        displaced_path=str(p) + ".brak-k", prepared_path=str(p) + ".brak-t", now=NOW)


@pytest.mark.parametrize("slad", ["undo_w_miejscu", "slad_atomowy", "plik_zmieniony"])
def test_slad_wczesniejszej_proby_to_do_sprawdzenia(tmp_path, slad):
    """Backup ze śladem próby bez dowodu zakończenia (operacja `undo` w miejscu otwarta; ślad drogi
    atomowej bez `synced_at`) albo plik, który baza opisuje inaczej niż wynik commitu (zmiana i skan):
    rdzeń nie wie, w jakim stanie jest plik - „wymaga sprawdzenia”, pozostałe dwa nietknięte.
    Falsyfikator: każda gałąź śladu zdjęta osobno → `untouched == 3`."""
    con, cid, pliki, lokacje, przed = _baza(tmp_path, inplace=slad == "undo_w_miejscu")
    if slad == "undo_w_miejscu":
        _slad_w_miejscu(con, cid, lokacje[0])
    elif slad == "slad_atomowy":
        _slad_atomowy(con, cid, lokacje[0], pliki[0], przed[0])
    else:
        fits.setval(str(pliki[0]), "OBSERVER", value="ktos")
        _scan_in(con, pliki[0])
    u = writeback.undo(con, cid, now=NOW, should_cancel=_po(0))
    assert u.remaining == 3 and u.untouched == 2, u
    con.close()


# ============================================================ wiersz Porządków ze STANU


@INPLACE
def test_wiersz_porzadkow_cofniecie_niedokonczone(tmp_path, inplace):
    """Commit bez próby cofnięcia - wiersza nie ma; przerwane po 1 z 3 → `[(C, 2)]` (po restarcie
    to samo - odczyt ze stanu); dokończone → `[]`. Falsyfikator: bez warunku „zaczęte” commit bez
    cofnięcia wpada do wiersza; bez warunku nagłówka - cofnięty plik liczy się jako czekający."""
    con, cid, _p, _l, _b = _baza(tmp_path, inplace=inplace)
    assert queries.niedokonczone_cofniecia_kart(con) == []
    writeback.undo(con, cid, now=NOW, should_cancel=_po(1))
    assert queries.niedokonczone_cofniecia_kart(con) == [(cid, 2)]
    con.close()
    con = db.open_db(str(tmp_path / "h.db"))
    assert queries.niedokonczone_cofniecia_kart(con) == [(cid, 2)]
    assert writeback.undo(con, cid, now=NOW).complete
    assert queries.niedokonczone_cofniecia_kart(con) == []
    con.close()


@INPLACE
def test_wiersz_po_pierwszym_niesynchronizowanym_sladzie_i_dokonczenie(tmp_path, monkeypatch, inplace):
    """Restart po PIERWSZYM śladzie próby, zanim jakikolwiek plik się domknął (w miejscu: śmierć procesu
    po zapisie regionu pierwszego pliku, operacja cofnięcia w fazie `written`; atomowo: ślad bez
    `synced_at`, plik sprzed commitu na dysku) - w ŚWIEŻYM procesie ślad jest w bazie, wiersz już jest,
    dokończenie cofa wszystkie trzy i wiersz gaśnie. Falsyfikator: „zaczęte” tylko po zakończonym pliku (`synced`) → wiersz pusty i droga ginie
    z programem."""
    con, cid, pliki, lokacje, przed = _baza(tmp_path, inplace=inplace)
    if inplace:
        class _Smierc(BaseException):
            """Śmierć procesu - nie `Exception`, więc pisarz jej nie łapie."""

        def _umiera(*_a, **_kw):
            raise _Smierc()
        with monkeypatch.context() as m:
            m.setattr(writeback, "_dokoncz", _umiera)
            with pytest.raises(_Smierc):
                writeback.undo(con, cid, now=NOW)
        assert [r["phase"] for r in con.execute(
            "SELECT phase FROM inplace_op WHERE kind = 'undo'")] == ["written"]
    else:
        _slad_atomowy(con, cid, lokacje[0], pliki[0], przed[0])
    con.close()
    # RESTART: odczyt wiersza i dokończenie w ŚWIEŻYM procesie - ze stanu bazy i dysku, nie z pamięci.
    wynik = _w_swiezym_procesie(tmp_path / "h.db", cid)
    assert wynik["slady"] == 1, wynik                   # trwały ślad próby przeżył proces
    assert wynik["wiersz_przed"] == [[cid, 3]], wynik
    assert wynik["complete"] and wynik["wiersz_po"] == [], wynik
    assert [p.read_bytes() for p in pliki] == przed
    con = db.connect(str(tmp_path / "h.db"))
    assert queries.niedokonczone_cofniecia_kart(con) == []
    con.close()


_PROCES_RESTARTU = r'''
import json, sys
from horreum import db, writeback
from horreum.gui import queries
con = db.connect(sys.argv[1])
cid = int(sys.argv[2])
slady = con.execute("SELECT count(*) FROM inplace_op WHERE kind = 'undo'").fetchone()[0] \
    + con.execute("SELECT count(*) FROM atomic_undo").fetchone()[0]
przed = queries.niedokonczone_cofniecia_kart(con)
u = writeback.undo(con, cid, now=sys.argv[3])
print(json.dumps({"slady": slady, "wiersz_przed": przed, "complete": u.complete,
                  "wiersz_po": queries.niedokonczone_cofniecia_kart(con)}))
con.close()
'''


def _w_swiezym_procesie(baza, cid):
    """Odczyt wiersza i dokończenie cofnięcia w nowym procesie Pythona (ten sam kod `horreum`, co test)."""
    import json
    import os
    import subprocess
    import sys
    import horreum
    korzen = os.path.dirname(os.path.dirname(os.path.abspath(horreum.__file__)))
    r = subprocess.run([sys.executable, "-c", _PROCES_RESTARTU, str(baza), str(cid), NOW], cwd=korzen,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@INPLACE
def test_pelne_cofniecie_i_ponowny_zapis_tej_samej_karty_bez_wiersza(tmp_path, inplace):
    """Pełne cofnięcie, potem ponowny zapis TEJ SAMEJ karty nowym commitem: baza znów opisuje
    `post_hash` starego commitu, ale lokację zapisał nowszy, żywy commit - nie jest resztą starego
    cofnięcia. Wiersz pusty; cofnięcie starego commitu nie rusza nowszego zapisu. Falsyfikator: wiersz
    bez straży nowszego zapisu → `[(C, 3)]` i zaproszenie do cofnięcia cudzej decyzji."""
    con, cid, pliki, lokacje, _b = _baza(tmp_path, inplace=inplace)
    assert writeback.undo(con, cid, now=NOW).complete
    for lid in lokacje:
        _karta(con, "R2", lid, "NGC 6992 X")
    c2 = writeback.commit(con, "R2", now=NOW, inplace=inplace)
    assert len(c2.applied) == 3, c2
    po_zapisie = [p.read_bytes() for p in pliki]
    assert queries.niedokonczone_cofniecia_kart(con) == []
    writeback.undo(con, cid, now=NOW)
    assert [p.read_bytes() for p in pliki] == po_zapisie
    con.close()


def test_przebieg_zmiany_obiektu_poza_wierszem(tmp_path):
    """Commit przebiegu „Zmień obiekt…”/„Uzgodnij pliki…” przerwany w połowie cofnięcia - drogą powrotu
    jest wiersz przebiegów przerwanych, nie ten. Falsyfikator: bez wyłączenia → `[(C, 2)]`."""
    con, cid, _p, _l, _b = _baza(tmp_path, inplace=True)
    con.execute("INSERT INTO object_change_run (run_id, mode, created_at, status) "
                "VALUES ('R', 'align', ?, 'applied')", (NOW,))
    con.commit()
    writeback.undo(con, cid, now=NOW, should_cancel=_po(1))
    assert queries.niedokonczone_cofniecia_kart(con) == []
    con.close()


# ============================================================ nowszy żywy zapis lokacji (A → B → A)


@INPLACE
def test_nowszy_zapis_ta_sama_karta_nie_jest_cofany(tmp_path, inplace):
    """Commit C na L1 i L2; cofnięcie przerwane po L1; C2 pisze na L2 inną kartę, C3 - z powrotem kartę
    C (ten sam nagłówek co wynik C). Wiersz Porządków pusty, cofnięcie C odmawia na L2 z kodem
    `undo_newer_write` i numerem C3, bajty L2 bez zmian; przerwanie liczy L2 do sprawdzenia, nie jako
    nietknięty. Falsyfikatory: bez straży w predykacie wiersza → `[(C, 1)]`; bez straży w rdzeniu →
    cofnięcie nadpisuje zapis C3."""
    con, cid, pliki, lokacje, _b = _baza(tmp_path, n=2, inplace=inplace)
    post_c = con.execute("SELECT post_hash FROM header_backups WHERE commit_id = ? AND location_id = ?",
                         (cid, lokacje[1])).fetchone()[0]
    writeback.undo(con, cid, now=NOW, should_cancel=_po(1))
    _karta(con, "R2", lokacje[1], "NGC 1")
    assert writeback.commit(con, "R2", now=NOW, inplace=inplace).applied
    _karta(con, "R3", lokacje[1], "NGC 6992 X")
    c3 = writeback.commit(con, "R3", now=NOW, inplace=inplace)
    assert c3.applied, c3
    assert con.execute("SELECT header_hash FROM location WHERE id = ?",
                       (lokacje[1],)).fetchone()[0] == post_c
    zapis_c3 = pliki[1].read_bytes()
    assert queries.niedokonczone_cofniecia_kart(con) == []
    przerwane = writeback.undo(con, cid, now=NOW, should_cancel=_po(0))
    assert przerwane.untouched == 0 and przerwane.remaining == 1, przerwane
    u = writeback.undo(con, cid, now=NOW)
    odmowy = [fr for fr in u.blocked if fr not in u.already]       # L1 - „już cofnięte”
    assert [fr.reason.code for fr in odmowy] == ["undo_newer_write"], u
    assert dict(odmowy[0].reason.params)["commit_id"] == c3.commit_id
    assert not u.complete and pliki[1].read_bytes() == zapis_c3
    con.close()


def test_nowszy_zapis_cofniety_bez_sladu_nie_blokuje(tmp_path):
    """Nowszy commit C2 cofnięty drogą atomową BEZ ŚLADU (emulacja cofnięcia sprzed migracji śladu:
    wiersze `atomic_undo` usunięte) - dowodu zakończenia nie ma, ale baza opisuje plik sprzed C2,
    czyli wynik C. Cofnięcie C idzie. Falsyfikator: straż bez warunku „baza opisuje wynik nowszego”
    → wieczna blokada `undo_newer_write`."""
    con, cid, pliki, lokacje, przed = _baza(tmp_path, n=1, inplace=False)
    _karta(con, "R2", lokacje[0], "NGC 1")
    c2 = writeback.commit(con, "R2", now=NOW, inplace=False)
    assert writeback.undo(con, c2.commit_id, now=NOW).complete
    con.execute("DELETE FROM location_state")       # cofnięcie sprzed śladu (0044) jest też sprzed rodowodu (0048)
    con.execute("DELETE FROM atomic_undo")
    con.commit()
    u = writeback.undo(con, cid, now=NOW)
    assert u.complete and len(u.restored) == 1, u
    assert pliki[0].read_bytes() == przed[0]
    con.close()


def test_odmowa_nowszego_zapisu_mowi_zdaniem_z_katalogu():
    """Zdanie złote PL i EN kodu `undo_newer_write` (zdanie rdzenia = wpis katalogu)."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import PowodPozycji
    powod = PowodPozycji("lokacja ma nowszy zapis (commit 7) - cofnij najpierw jego",
                         "undo_newer_write", commit_id=7)
    i18n.set_lang("pl")
    assert tekst_powodu(powod) == "lokacja ma nowszy zapis (commit 7) - cofnij najpierw jego"
    i18n.set_lang("en")
    try:
        assert tekst_powodu(powod) == "the location has a newer write (commit 7) - undo that one first"
    finally:
        i18n.set_lang("pl")


# ============================================================ granica śladu: chwila dziennika, sekunda, strefa (AR-320)


def _chwila_dziennika(con):
    from datetime import datetime
    return datetime.strptime(con.execute(
        "SELECT applied_at FROM migration_log WHERE version = 47").fetchone()[0],
        "%Y-%m-%dT%H:%M:%SZ")


def test_granica_sladu_to_wiersz_dziennika_47(tmp_path):
    """Baza z v43 ma wiersze 0044..0047 jedną chwilą; granicą jest wiersz 0047 czytany wprost, nie 0044
    (tu przestawiony w bazie testu o dzień wstecz, żeby je rozróżnić). Falsyfikator: `coalesce(44, 47)`."""
    con = _baza_z_wersji(tmp_path / "h.db", 43)
    con.execute("UPDATE migration_log SET applied_at = '2000-01-01T00:00:00Z' WHERE version = 44")
    con.commit()
    assert writeback._granica_sladu(con) == con.execute(
        "SELECT applied_at FROM migration_log WHERE version = 47").fetchone()[0]
    con.close()


@pytest.mark.parametrize("przesuniecie, zapis, oczekiwany", [
    (-1.0, "+00:00", 0),       # sekunda przed migracją
    (0.0, "+00:00", 0),        # sekunda migracji - commit mógł ją wyprzedzić (granica konserwatywna)
    (0.0, "Z", 0),
    (0.5, "+00:00", 0),        # wciąż sekunda migracji
    (1.0, "+00:00", 1),        # pierwsza pełna sekunda po migracji
    (1.0, "Z", 1),
    (3600.0, "+02:00", 0),     # 1 h po migracji w zapisie lokalnym = 1 h PRZED nią w UTC
    (3600.0, "+0000", 0),      # 1 h po migracji, strefa bez dwukropka - `julianday` go nie czyta (NULL)
], ids=["T-1s", "T", "T_Z", "T+0,5s", "T+1s", "T+1s_Z", "strefa+02", "nieczytelny"])
def test_klasa_nietkniety_od_sekundy_po_chwili_dziennika(tmp_path, przesuniecie, zapis, oczekiwany):
    """Commit atomowy z zegarem względem chwili T dziennika tej bazy (wiersz 0047, sekundy): „nietknięty”
    wyłącznie od T + 1 s; T - 1 s, T i T + 0,5 s - „wymaga sprawdzenia” (dziennik gubi ułamek sekundy, więc
    commit z sekundy migracji mógł ją wyprzedzić). Zapis w strefie `+02:00` porównany w UTC. Zapis, którego
    `julianday` nie czyta (strefa `+0000` bez dwukropka, T + 1 h) - „wymaga sprawdzenia”, nie „nietknięty”.
    Falsyfikatory: `>` zamiast `>=` (T + 1 s), bez `+1 second` (T), porównanie tekstem `[:19]` (strefa),
    tekstem bez `[:19]` (sufiks `Z`), NULL `julianday` liczony jak „po granicy” (zapis nieczytelny)."""
    from datetime import timedelta, timezone
    con = db.open_db(str(tmp_path / "h.db"))
    t = _chwila_dziennika(con).replace(tzinfo=timezone.utc) + timedelta(seconds=przesuniecie)
    if zapis == "+02:00":                  # cyfry T + 1 h, ale w strefie +02:00 - w UTC to T - 1 h
        kiedy = t.replace(tzinfo=None).isoformat() + "+02:00"
    elif zapis == "+0000":                 # T + 1 h w UTC, ale zapis, którego `julianday` nie czyta
        kiedy = t.strftime("%Y-%m-%dT%H:%M:%S") + "+0000"
    elif zapis == "Z":
        kiedy = t.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    else:
        kiedy = t.isoformat()
    p = _fits(tmp_path / "f.fits", seed=1)
    _scan_in(con, p)
    _karta(con, "R", _loc(con, p)["id"], "NGC 6992 X")
    c = writeback.commit(con, "R", now=kiedy, inplace=False)
    assert con.execute("SELECT applied_at FROM commits WHERE id = ?",
                       (c.commit_id,)).fetchone()[0] == kiedy
    u = writeback.undo(con, c.commit_id, now=NOW, should_cancel=_po(0))
    assert u.remaining == 1 and u.untouched == oczekiwany, (kiedy, u)
    con.close()


def test_wiersz_dziennika_w_transakcji_migracji(tmp_path, monkeypatch):
    """Wpis `migration_log` pada (wyzwalacz `RAISE` w skrypcie 0047): migracja cofa się CAŁA - `user_version`
    zostaje 46, tabeli dziennika nie ma; ponowne otwarcie bez awarii dochodzi do 47 z wierszem. Falsyfikator:
    zatwierdzenie skryptu przed wpisem (wpis poza transakcją migracji)."""
    pelne = list(db.MIGRATIONS)
    path = str(tmp_path / "h.db")
    monkeypatch.setattr(db, "MIGRATIONS", [m for m in pelne if m[0] <= 46])
    db.open_db(path).close()
    monkeypatch.setattr(db, "MIGRATIONS", pelne)
    prawdziwy = db._migration_sql

    def _z_awaria(filename):
        sql = prawdziwy(filename)
        if filename.startswith("0047"):
            sql += ("\nCREATE TRIGGER stop BEFORE INSERT ON migration_log "
                    "BEGIN SELECT RAISE(ABORT, 'stop wpisu'); END;")
        return sql
    monkeypatch.setattr(db, "_migration_sql", _z_awaria)
    con = db.connect(path)
    with pytest.raises(Exception, match="stop wpisu"):
        db.migrate(con)
    assert not con.in_transaction and db._user_version(con) == 46
    assert con.execute("SELECT count(*) FROM sqlite_master WHERE name = 'migration_log'").fetchone()[0] == 0
    con.close()
    monkeypatch.setattr(db, "_migration_sql", prawdziwy)
    con = db.open_db(path)
    assert db._user_version(con) == db.SCHEMA_VERSION
    assert [r[0] for r in con.execute("SELECT version FROM migration_log")] == [47, 48]
    con.close()
