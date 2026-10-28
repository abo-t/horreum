"""AR-421: rodowód stanu lokacji (`location_state`, 0048) - kto i w jakiej kolejności postawił odcisk pliku. Każda
transakcja, w której baza poznaje wynik pisarza (zapis kart, cofnięcie, odzysk) albo odczyt zmienia odcisk lokacji
(`file_sha1`, `header_hash`), dopisuje jeden wiersz z pochodzeniem i identyfikatorami operacji.

Pinuje:
  * kształt pochodzenia (`repo.Pochodzenie`): walidacja, etykieta pisarza wyłącznie przy zgodności odczytanego odcisku
    z wynikiem operacji (inaczej odczyt zewnętrzny), parametr wymagany w całym kanale (bramka AST);
  * każdą drogę pisarza na prawdziwym pisarzu (syntetyczne FITS w `tmp_path`): zapis i cofnięcie obu dróg,
    dokończenie operacji w miejscu, rekoncyliacja backupu niepotwierdzonego, odzysk rozdarcia, zwrot wersji innego
    pisarza, skan;
  * okna śmierci procesu i przypisanie „już cofnięte”, obcą wersję w oknie przed re-synciem, co najwyżej jeden
    wiersz `commit` na backup (także po cofnięciu tego zapisu w innym procesie), brak powtórzonych obserwacji;
  * kolejność: `id` porządkuje zatwierdzone obserwacje (wycofana transakcja, stary odczyt skanu, odzysk przerwany
    przed fazą `recovered`), sekwencje wierszy scen łańcucha cofnięć jak w czystej regule klasy.
Tor reguły klasy czyta te wiersze - tu nie zmienia się żadna klasa ani zdanie."""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest
from astropy.io import fits

import horreum
from horreum import db, repo, scan, writeback
from horreum.gui import queries

from test_rodowod_falsyfikatory import _scena, _skan, _zapis
from test_writeback_cofniecie_atomowe import _commit
from test_writeback_cofniecie_przebiegu import NOW, _baza, _makro, _tel
from test_writeback_inplace import (_baza_z_plikiem, _commit_z_padem_resyncu, _fits, _fits_dwa_hdu,
                                    _otwarta_operacja, _scan_in, _stary_commit)
from test_writeback_zamiar import _po_smierci_z_obcym

H40 = "a" * 40                    # odciski syntetyczne do testów klingi (długość jak sha1)
S40 = "b" * 40


class _Smierc(BaseException):
    """Śmierć procesu w punkcie wstrzyknięcia - przechodzi przez każde `except Exception` pisarza."""


# ============================================================ pomocniki


def _wiersze(con):
    return [dict(r) for r in con.execute("SELECT * FROM location_state ORDER BY id")]


def _krotki(con):
    """`(origin, backup_id, inplace_op_id, atomic_undo_id)` wierszy rodowodu po `id`."""
    return [(w["origin"], w["backup_id"], w["inplace_op_id"], w["atomic_undo_id"]) for w in _wiersze(con)]


def _backup(con, commit_id):
    (b,) = con.execute("SELECT id FROM header_backups WHERE commit_id = ?", (commit_id,)).fetchall()
    return b[0]


def _operacja(con, commit_id, rodzaj):
    (o,) = con.execute("SELECT id FROM inplace_op WHERE commit_id = ? AND kind = ?",
                       (commit_id, rodzaj)).fetchall()
    return o[0]


def _slady_backupu(con, backup_id):
    return [dict(r) for r in con.execute("SELECT * FROM atomic_undo WHERE backup_id = ? ORDER BY id",
                                         (backup_id,))]


def _odcisk(con, location_id=None):
    sql = "SELECT file_sha1, header_hash FROM location" + (" WHERE id = ?" if location_id else "")
    return tuple(con.execute(sql, (location_id,) if location_id else ()).fetchone())


def _odcisk_najnowszego_zgodny(con):
    """Niezmiennik rodowodu: lokacja z wierszami ma odcisk swojego najnowszego wiersza (każda zmiana odcisku
    przez klingę faktów kopii zostawia wiersz)."""
    for lid, sha1, naglowek in con.execute("SELECT id, file_sha1, header_hash FROM location").fetchall():
        ost = con.execute("SELECT file_sha1, header_hash FROM location_state WHERE location_id = ? "
                          "ORDER BY id DESC LIMIT 1", (lid,)).fetchone()
        assert ost is None or tuple(ost) == (sha1, naglowek), (lid, tuple(ost), (sha1, naglowek))


def _smierc_po_podmianie(monkeypatch, *, z_potwierdzeniem):
    """Podmiana zaszła (z potwierdzeniem backupu w transakcji straży albo bez), proces ginie przed re-synciem."""
    prawdziwy = writeback._podmien

    def _f(tmp, path, replace_guard, odcisk, po_podmianie=None, **kw):
        prawdziwy(tmp, path, replace_guard, odcisk, po_podmianie if z_potwierdzeniem else None, **kw)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)


def _jeden_plik(tmp_path):
    con, pliki = _baza(tmp_path, 1)
    return con, pliki[0]


# ============================================================ kształt pochodzenia (czysty)


@pytest.mark.parametrize("budowa", [
    lambda: repo.Pochodzenie("zly"),
    lambda: repo.Pochodzenie("external", backup_id=1),
    lambda: repo.Pochodzenie("external", wyniki=(repo.WynikPisarza(H40),)),
    lambda: repo.Pochodzenie("commit", wyniki=(repo.WynikPisarza(H40),)),
    lambda: repo.Pochodzenie.zapis(1, ()),
    lambda: repo.Pochodzenie("rollback", wyniki=(repo.WynikPisarza(H40),)),
    lambda: repo.Pochodzenie("rollback", backup_id=1, inplace_op_id=2, wyniki=(repo.WynikPisarza(H40),)),
    lambda: repo.Pochodzenie("commit", backup_id=1, wyniki=(repo.WynikPisarza(H40),), slad=3),
    lambda: repo.Pochodzenie.zapis(1, ((H40, None),)),
])
def test_pochodzenie_odrzuca_niespojne(budowa):
    """Niespójne pola pochodzenia to błąd wołającego (lustro CHECK-ów 0048): zły rodzaj, odczyt zewnętrzny
    z identyfikatorami albo wynikiem, zapis bez backupu albo bez wyniku, powrót bez operacji albo z backupem, ślad
    cofnięcia przy zapisie, wynik spoza `WynikPisarza`."""
    with pytest.raises(ValueError):
        budowa()


def test_etykieta_pisarza_wymaga_zgodnosci_odcisku():
    """Wiersz pisarza tylko przy zgodności odczytu z wynikiem: ten sam nagłówek i - gdy wynik zna sha1 pliku - ten
    sam sha1; rozjazd i nagłówek NULL dają odczyt zewnętrzny bez identyfikatorów."""
    p = repo.Pochodzenie.cofniecie(7, (repo.WynikPisarza(H40, S40), repo.WynikPisarza("c" * 40)),
                                   inplace_op_id=3)
    assert p.dla(S40, H40) == ("undo", 7, 3)
    assert p.dla("d" * 40, H40) == ("external", None, None)            # para śladu: inny sha1
    assert p.dla("e" * 40, "c" * 40) == ("undo", 7, 3)                 # wynik bez sha1: sam nagłówek
    assert p.dla(None, None) == ("external", None, None)
    assert repo.ZEWNETRZNE.dla(S40, H40) == ("external", None, None)


@pytest.mark.parametrize("funkcja", [scan.ingest_record, scan._ingest_in_tx, repo.refresh_location,
                                     writeback._resync])
def test_parametr_pochodzenia_wymagany(funkcja):
    """Kanał pochodzenia bez wartości domyślnej - zapomniane pochodzenie to `TypeError`, nie ciche `external`."""
    par = inspect.signature(funkcja).parameters["pochodzenie"]
    assert par.kind is inspect.Parameter.KEYWORD_ONLY and par.default is inspect.Parameter.empty


def test_klinga_odrzuca_pochodzenie_innego_typu(tmp_path):
    con, p = _jeden_plik(tmp_path)
    lok = con.execute("SELECT * FROM location").fetchone()
    with pytest.raises(TypeError):
        repo.refresh_location(con, location_id=lok["id"], frame_id=lok["frame_id"], mtime="m",
                              file_sha1=lok["file_sha1"], header_hash=lok["header_hash"], hdu_index=0,
                              compressed=0, size_bytes=1, unreadable_since=None, unreadable_kind=None,
                              unreadable_reason=None, present=1, now=NOW, pochodzenie="external")
    assert _wiersze(con) == []
    con.close()


@pytest.mark.parametrize("cudze", ["backup_innej_lokacji", "backup_nieistniejacy", "operacja_innej_lokacji",
                                   "operacja_innego_commitu", "powrot_operacji_innej_lokacji",
                                   "slad_innego_backupu"])
def test_straz_pochodzenia_odrzuca_identyfikatory_spoza_lokacji(tmp_path, cudze):
    """Pochodzenie pisarza z backupem, operacją albo śladem spoza lokacji wiersza (także operacja innego commitu niż
    backup i ślad innego backupu) to błąd wołającego: klinga odmawia (`ValueError`) w transakcji wjazdu - zero
    wiersza i fakty lokacji bez zmian, choć odczyt pasuje do wyniku. Ten sam rekord odczytem zewnętrznym wjeżdża."""
    con, pliki = _baza(tmp_path, 2)
    l0, l1 = [r[0] for r in con.execute("SELECT id FROM location ORDER BY id")]
    f0 = con.execute("SELECT frame_id FROM location WHERE id = ?", (l0,)).fetchone()[0]
    _makro(con, "R1", "EQ6")
    c1 = writeback.commit(con, "R1", now=NOW, inplace=True).commit_id
    _makro(con, "R2", "EQ8", [f0])
    c2 = writeback.commit(con, "R2", now=NOW, inplace=True).commit_id

    def _b(cid, lid):
        return con.execute("SELECT id FROM header_backups WHERE commit_id = ? AND location_id = ?",
                           (cid, lid)).fetchone()[0]

    def _op(cid, lid):
        return con.execute("SELECT id FROM inplace_op WHERE commit_id = ? AND location_id = ? AND kind = 'commit'",
                           (cid, lid)).fetchone()[0]
    au = repo.record_atomic_undo(con, backup_id=_b(c1, l0), result_sha1=S40, result_size=1, result_hash=H40,
                                 byte_exact=0, source_sha1=S40, source_size=1, displaced_path=str(pliki[0]) + ".k",
                                 prepared_path=str(pliki[0]) + ".t", now=NOW)
    lid, plik = (l1, pliki[1]) if cudze == "backup_innej_lokacji" else (l0, pliki[0])
    fits.setval(str(plik), "TELESCOP", value="EQ9")
    rec = scan.scan_file(str(plik))
    wyniki = (repo.WynikPisarza(rec.header_hash, rec.file_sha1),)
    pochodzenie = {
        "backup_innej_lokacji": lambda: repo.Pochodzenie.zapis(_b(c1, l0), wyniki),
        "backup_nieistniejacy": lambda: repo.Pochodzenie.zapis(10 ** 6, wyniki),
        "operacja_innej_lokacji": lambda: repo.Pochodzenie.zapis(_b(c1, l0), wyniki, inplace_op_id=_op(c1, l1)),
        "operacja_innego_commitu": lambda: repo.Pochodzenie.cofniecie(_b(c1, l0), wyniki,
                                                                       inplace_op_id=_op(c2, l0)),
        "powrot_operacji_innej_lokacji": lambda: repo.Pochodzenie.powrot(_op(c1, l1), wyniki),
        "slad_innego_backupu": lambda: repo.Pochodzenie.cofniecie(_b(c2, l0), wyniki, slad=au),
    }[cudze]()
    przed = (_krotki(con), _odcisk(con, lid))
    with pytest.raises(ValueError, match="nie należy"):
        scan.ingest_record(con, rec, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=pochodzenie)
    assert (_krotki(con), _odcisk(con, lid)) == przed
    scan.ingest_record(con, rec, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=repo.ZEWNETRZNE)
    assert _krotki(con) == przed[0] + [("external", None, None, None)]
    con.close()


# ============================================================ bramka AST kanału pochodzenia

_KANAL = {"ingest_record", "_resync", "refresh_location", "_ingest_in_tx"}


def _naruszenia_pochodzenia(nazwa, drzewo):
    """`(naruszenia, liczniki wywołań)` modułu: wywołanie funkcji kanału bez jawnego `pochodzenie=` (także samo
    `**kw`) i odwołanie do niej poza wywołaniem (alias, przekazanie funkcji) - droga, której testy nie wykonują,
    nie zgubi etykiety."""
    zle, wolania, funkcje = [], Counter(), set()
    for w in ast.walk(drzewo):
        if isinstance(w, ast.Call):
            funkcje.add(id(w.func))
            n = w.func.attr if isinstance(w.func, ast.Attribute) else getattr(w.func, "id", None)
            if n in _KANAL:
                wolania[n] += 1
                if not any(k.arg == "pochodzenie" for k in w.keywords):
                    zle.append(f"{nazwa}:{w.lineno} {n}(...) bez pochodzenie=")
    for w in ast.walk(drzewo):
        n = w.id if isinstance(w, ast.Name) else (w.attr if isinstance(w, ast.Attribute) else None)
        if n in _KANAL and isinstance(w.ctx, ast.Load) and id(w) not in funkcje:
            zle.append(f"{nazwa}:{w.lineno} odwołanie do {n} poza wywołaniem")
    return zle, wolania


def test_bramka_ast_pochodzenia():
    """Każde wywołanie `ingest_record`, `_resync`, `refresh_location`, `_ingest_in_tx` w `horreum/` i `scripts/` niesie
    jawne `pochodzenie=`; każda z czterech funkcji ma co najmniej jedno wywołanie (bramka nie przechodzi pusto)."""
    pakiet = Path(horreum.__file__).parent
    pliki = sorted(pakiet.rglob("*.py")) + sorted((pakiet.parent / "scripts").rglob("*.py"))
    zle, wolania = [], Counter()
    for src in pliki:
        z, w = _naruszenia_pochodzenia(src.name, ast.parse(src.read_text(encoding="utf-8")))
        zle += z
        wolania += w
    assert not zle, zle
    assert set(wolania) == _KANAL, wolania


@pytest.mark.parametrize("zrodlo", [
    "scan.ingest_record(con, rec, now=n, summary=s)",
    "ingest_record(con, rec, now=n, summary=s, **kw)",
    "f = scan.ingest_record\n",
    "repo.refresh_location(con, location_id=1, now=n)",
])
def test_bramka_ast_lapie_obejscia(zrodlo):
    assert _naruszenia_pochodzenia("x.py", ast.parse(zrodlo))[0]


def test_bramka_ast_bez_falszywego_alarmu():
    assert _naruszenia_pochodzenia("x.py", ast.parse(
        "scan.ingest_record(con, rec, now=n, summary=s, pochodzenie=repo.ZEWNETRZNE)"))[0] == []


# ============================================================ kontrakt tabeli (0048)


def test_ddl_location_state(tmp_path):
    """Migracja dokłada pustą tabelę z trzema indeksami; CHECK-i odbijają niespójne wiersze, a indeks unikalny -
    drugi wiersz `commit` tego samego backupu."""
    con, p = _jeden_plik(tmp_path)
    assert _wiersze(con) == []
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'index' "
                                      "AND tbl_name = 'location_state'")} == {
        "idx_location_state_location", "idx_location_state_backup", "idx_location_state_commit"}
    c1 = _zapis(con, "R1", "EQ6")
    b1 = _backup(con, c1)
    lid = con.execute("SELECT id FROM location").fetchone()[0]
    wstaw = ("INSERT INTO location_state(location_id, origin, backup_id, inplace_op_id, atomic_undo_id, "
             "file_sha1, header_hash, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
    for wiersz in [(lid, "zly", None, None, None, S40, H40, NOW), (lid, "commit", None, None, None, S40, H40, NOW),
                   (lid, "external", b1, None, None, S40, H40, NOW),
                   (lid, "rollback", None, None, None, S40, H40, NOW),
                   (lid, "commit", b1, None, None, S40, H40, NOW),             # drugi `commit` backupu b1
                   (lid, "external", None, None, None, S40, H40, "")]:
        with pytest.raises(sqlite3.IntegrityError):
            with con:
                con.execute(wstaw, wiersz)
    con.close()


# ============================================================ drogi pisarza: jeden wiersz na obserwację


def test_droga_commit_atomowy(tmp_path):
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6")
    assert _krotki(con) == [("commit", _backup(con, c1), None, None)]
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_droga_commit_w_miejscu(tmp_path):
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6", inplace=True)
    assert _krotki(con) == [("commit", _backup(con, c1), _operacja(con, c1, "commit"), None)]
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_droga_cofniecie_atomowe(tmp_path):
    """Cofnięcie atomowe: wiersz `undo` z wciągniętym śladem - tym samym, który dostaje `synced_at`."""
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6")
    b1 = _backup(con, c1)
    assert writeback.undo(con, c1, now=NOW).complete and _tel(p) == "RC8"
    (slad,) = _slady_backupu(con, b1)
    assert slad["synced_at"] is not None
    assert _krotki(con) == [("commit", b1, None, None), ("undo", b1, None, slad["id"])]
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_droga_cofniecie_w_miejscu(tmp_path):
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6", inplace=True)
    b1 = _backup(con, c1)
    assert writeback.undo(con, c1, now=NOW).complete and _tel(p) == "RC8"
    assert _krotki(con) == [("commit", b1, _operacja(con, c1, "commit"), None),
                            ("undo", b1, _operacja(con, c1, "undo"), None)]
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_droga_cofniecie_semantyczne(tmp_path):
    """Cofnięcie semantyczne (backup tekstowy: nagłówek odtworzony z treści, bajty pliku inne niż przed zapisem, ślad
    z `byte_exact` fałszywym) to cofnięcie pisarza: wiersz `undo` ze śladem i odciskiem wyniku tego śladu."""
    p = _fits(tmp_path / "s.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    b = _backup(con, cid)
    u = writeback.undo(con, cid, now=NOW)
    assert len(u.restored) == 1 and u.semantic and u.complete, u
    (slad,) = _slady_backupu(con, b)
    assert slad["byte_exact"] == 0
    assert _krotki(con) == [("commit", b, None, None), ("undo", b, None, slad["id"])]
    ost = _wiersze(con)[-1]
    assert (ost["file_sha1"], ost["header_hash"]) == (slad["result_sha1"], slad["result_hash"])
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_droga_dokonczenie_operacji_w_miejscu(tmp_path, monkeypatch):
    """Re-sync zapisu w miejscu padł (czkawka odczytu) - operacja `written`, wiersza nie ma; „Dokończ zapis”
    (`finish_inplace`) dopisuje wiersz `commit` z operacją."""
    con, p = _jeden_plik(tmp_path)
    _makro(con, "R1", "EQ6")
    _commit_z_padem_resyncu(monkeypatch, con, "R1")
    (cid,) = [r[0] for r in con.execute("SELECT id FROM commits")]
    op = _operacja(con, cid, "commit")
    assert repo.inplace_op_phase(con, op) == "written" and _wiersze(con) == []
    assert writeback.finish_inplace(con, op, now=NOW).status == "applied"
    assert _krotki(con) == [("commit", _backup(con, cid), op, None)]
    con.close()


def test_droga_rekoncyliacja_backupu_niepotwierdzonego(tmp_path, monkeypatch):
    """Proces zginął po podmianie, przed potwierdzeniem: backup niepotwierdzony, pod ścieżką wynik zapisu. Cofnięcie
    najpierw rekoncyliuje backup z dyskiem (`_potwierdz_z_dysku` - wiersz `commit`), potem cofa (wiersz `undo`)."""
    con, p = _jeden_plik(tmp_path)
    _makro(con, "R1", "EQ6")
    _smierc_po_podmianie(monkeypatch, z_potwierdzeniem=False)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    (cid,) = [r[0] for r in con.execute("SELECT id FROM commits")]
    b1 = _backup(con, cid)
    assert _wiersze(con) == [] and _tel(p) == "EQ6"
    assert writeback.undo(con, cid, now=NOW).complete and _tel(p) == "RC8"
    (slad,) = _slady_backupu(con, b1)
    assert _krotki(con) == [("commit", b1, None, None), ("undo", b1, None, slad["id"])]
    con.close()


def test_droga_zwrot_wersji_innego_pisarza(tmp_path, monkeypatch):
    """Wersja innego pisarza wraca spod kopii wypartej (`_odswiez_po_powrocie`): odczyt zewnętrzny z jej odciskiem
    - nie powrót pisarza."""
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)
    assert [w["origin"] for w in _wiersze(con)] == ["external"]
    writeback.commit(con, "R", now=NOW)
    assert p.read_bytes() == cudzy["bajty"]
    wiersze = _wiersze(con)
    assert [w["origin"] for w in wiersze] == ["external", "external"]
    assert (wiersze[-1]["file_sha1"], wiersze[-1]["header_hash"]) == (
        scan.scan_file(str(p)).file_sha1, scan.scan_file(str(p)).header_hash)
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_droga_skan_ze_zmiana_i_bez(tmp_path):
    """Skan pliku zmienionego spoza Horreum - jeden wiersz zewnętrzny; skan bez zmiany odcisku - zero wierszy:
    na lokacji bez historii, po zapisie pisarza i przy zmianie samego `mtime` (ładunek `location.refreshed` bez
    klucza rodowodu)."""
    con, p = _jeden_plik(tmp_path)
    p.write_bytes(p.read_bytes())                                  # nowy `mtime`, lokacja bez historii
    _skan(con, p)
    assert _wiersze(con) == []
    c1 = _zapis(con, "R1", "EQ6")
    p.write_bytes(p.read_bytes())
    _skan(con, p)
    assert _krotki(con) == [("commit", _backup(con, c1), None, None)]
    fits.setval(str(p), "TELESCOP", value="EQ8")
    _skan(con, p)
    assert _krotki(con) == [("commit", _backup(con, c1), None, None), ("external", None, None, None)]
    _odcisk_najnowszego_zgodny(con)
    ladunek = json.loads(con.execute("SELECT payload FROM event WHERE verb = 'location.refreshed' "
                                     "AND actor = 'scan' ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert ladunek["location_state"] == {"id": _wiersze(con)[-1]["id"], "origin": "external", "backup_id": None,
                                         "inplace_op_id": None, "atomic_undo_id": None}
    _skan(con, p)
    p.write_bytes(p.read_bytes())                                  # nowy `mtime`, te same bajty
    _skan(con, p)
    assert len(_wiersze(con)) == 2
    ostatni = json.loads(con.execute("SELECT payload FROM event WHERE verb = 'location.refreshed' "
                                     "ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert set(ostatni) == {"mtime"}, ostatni
    con.close()


def test_zdarzenie_niesie_wiersz_rodowodu(tmp_path):
    """Ładunek `location.refreshed` re-syncu pisarza niesie wiersz rodowodu (id, pochodzenie, backup)."""
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6")
    (wiersz,) = _wiersze(con)
    ladunek = json.loads(con.execute("SELECT payload FROM event WHERE verb = 'location.refreshed' "
                                     "AND actor = 'user:local' ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert ladunek["location_state"] == {"id": wiersz["id"], "origin": "commit", "backup_id": _backup(con, c1),
                                         "inplace_op_id": None, "atomic_undo_id": None}
    con.close()


# ============================================================ okna śmierci procesu i przypisanie „już cofnięte”


def test_okno_po_potwierdzeniu_podmiany_skan_bez_przypisania(tmp_path, monkeypatch):
    """Śmierć po potwierdzeniu podmiany, przed re-synciem zapisu: wpisy stagingu czekają, a skan wciąga wynik zapisu
    odczytem zewnętrznym - bez spóźnionego wiersza `commit`. Cofnięcie potem - zwykły wiersz `undo`."""
    con, p = _jeden_plik(tmp_path)
    _makro(con, "R1", "EQ6")
    _smierc_po_podmianie(monkeypatch, z_potwierdzeniem=True)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    (cid,) = [r[0] for r in con.execute("SELECT id FROM commits")]
    b1 = _backup(con, cid)
    assert con.execute("SELECT pending_since FROM header_backups").fetchone()[0] is None
    assert _wiersze(con) == []
    _skan(con, p)
    assert {r[0] for r in con.execute("SELECT status FROM pending_changes")} == {"pending"}
    (wiersz,) = _wiersze(con)
    post = con.execute("SELECT post_hash FROM header_backups").fetchone()[0]
    assert (wiersz["origin"], wiersz["header_hash"]) == ("external", post)
    assert writeback.undo(con, cid, now=NOW).complete and _tel(p) == "RC8"
    (slad,) = _slady_backupu(con, b1)
    assert _krotki(con) == [("external", None, None, None), ("undo", b1, None, slad["id"])]
    con.close()


def _umiera_po_podmianie_cofniecia(tmp_path, monkeypatch):
    """Zapis C1 atomowo, cofnięcie ginie po podmianie (ślad zatwierdzony, bez `synced_at`), baza po zapisie."""
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6")
    b1 = _backup(con, c1)
    _smierc_po_podmianie(monkeypatch, z_potwierdzeniem=False)
    with pytest.raises(_Smierc):
        writeback.undo(con, c1, now=NOW)
    monkeypatch.undo()
    (slad,) = _slady_backupu(con, b1)
    assert slad["synced_at"] is None and _tel(p) == "RC8"
    assert _krotki(con) == [("commit", b1, None, None)]
    return con, p, c1, b1, slad["id"]


@pytest.mark.parametrize("skan", [True, False], ids=["skan", "bez_skanu"])
def test_okno_po_podmianie_cofniecia(tmp_path, monkeypatch, skan):
    """Śmierć po podmianie cofnięcia atomowego, przed re-synciem. Ze skanem: wynik cofnięcia wchodzi odczytem
    zewnętrznym, a ponowne „Cofnij” rozlicza „już cofnięte” przypisaniem `undo` tego śladu (para pełnych odcisków).
    Bez skanu: ponowne „Cofnij” dokańcza re-sync - wiersz `undo` z tym samym śladem. Ślad wiersza = ślad `synced_at`."""
    con, p, c1, b1, au = _umiera_po_podmianie_cofniecia(tmp_path, monkeypatch)
    if skan:
        _skan(con, p)
    u = writeback.undo(con, c1, now=NOW)
    assert u.complete and _tel(p) == "RC8", u
    oczekiwane = [("commit", b1, None, None)] + ([("external", None, None, None)] if skan else []) + [
        ("undo", b1, None, au)]
    assert _krotki(con) == oczekiwane
    assert _slady_backupu(con, b1)[0]["synced_at"] is not None
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.state_attributed'").fetchone()[0] == (
        1 if skan else 0)
    _odcisk_najnowszego_zgodny(con)
    con.close()


def test_przypisanie_nie_jest_gestem_reki(tmp_path, monkeypatch):
    """Zdarzenie przypisania to księgowość pisarza: aktor spoza `user%`, a ostatni gest ręki Domu go nie liczy."""
    con, p, c1, b1, au = _umiera_po_podmianie_cofniecia(tmp_path, monkeypatch)
    _skan(con, p)
    writeback.undo(con, c1, now=NOW)
    (aktor,) = con.execute("SELECT actor FROM event WHERE verb = 'location.state_attributed'").fetchone()
    assert aktor == repo.AKTOR_RODOWODU and not aktor.startswith("user")
    gest = queries.last_hand_gesture(con)
    assert gest is None or "location.state_attributed" not in gest["verbs"], gest
    con.close()


def test_przypisanie_juz_cofniete_w_jednej_transakcji(tmp_path, monkeypatch):
    """Przypisanie wchodzi w transakcję rozliczenia „już cofnięte”: błąd przy jego zdarzeniu wycofuje całość -
    zero nowego wiersza i zdarzenia, ślad bez `synced_at`; ponowienie wykonuje całość raz."""
    con, p, c1, b1, au = _umiera_po_podmianie_cofniecia(tmp_path, monkeypatch)
    _skan(con, p)
    zdarzenia = "SELECT count(*) FROM event WHERE verb NOT LIKE 'run.undo_%'"    # zamiar cofnięcia - osobno
    przed = (_krotki(con), con.execute(zdarzenia).fetchone()[0])
    prawdziwe = repo.emit_event

    def _pada(con_, **kw):
        if kw.get("verb") == "location.state_attributed":
            raise sqlite3.OperationalError("disk I/O error")
        return prawdziwe(con_, **kw)
    monkeypatch.setattr(repo, "emit_event", _pada)
    u = writeback.undo(con, c1, now=NOW)
    monkeypatch.undo()
    assert not u.complete and u.failed, u
    assert (_krotki(con), con.execute(zdarzenia).fetchone()[0]) == przed
    assert _slady_backupu(con, b1)[0]["synced_at"] is None
    assert writeback.undo(con, c1, now=NOW).complete
    assert _krotki(con) == przed[0] + [("undo", b1, None, au)]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.state_attributed'").fetchone()[0] == 1
    con.close()


def test_commit_failed_potwierdzony_skanem_zostaje_zewnetrzny(tmp_path, monkeypatch):
    """Re-sync zapisu atomowego padł, skan potwierdza zapis (`confirm_failed_commit_by_scan`): w rodowodzie odczyt
    zewnętrzny z wynikiem zapisu, bez wiersza `commit` dopisanego po fakcie."""
    con, p = _jeden_plik(tmp_path)
    _makro(con, "R1", "EQ6")

    def _pada(*a, **kw):
        raise OSError(5, "zerwany udział")
    monkeypatch.setattr(writeback, "_resync", _pada)
    c = writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    assert len(c.failed) == 1 and _wiersze(con) == []
    _skan(con, p)
    assert {r[0] for r in con.execute("SELECT status FROM pending_changes")} == {"applied"}
    assert _krotki(con) == [("external", None, None, None)]
    con.close()


# ============================================================ obca wersja w oknie przed re-synciem


def _plik_dwa_hdu(tmp_path):
    p, drugi = _fits_dwa_hdu(tmp_path / "d.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    return con, p, drugi


def _zmien_bajt(p, offset):
    dane = bytearray(p.read_bytes())
    dane[offset] ^= 0x01
    p.write_bytes(bytes(dane))


@pytest.mark.parametrize("obca", ["drugie_hdu", "naglowek"])
def test_obca_wersja_przed_resynciem_zapisu_atomowego(tmp_path, monkeypatch, obca):
    """Re-sync zapisu atomowego biegnie poza blokadą pliku: obca wersja z tym samym obrazem (`sha1_data`) - inny bajt
    drugiego HDU albo inny nagłówek - wjeżdża do bazy, ale w rodowodzie jako odczyt zewnętrzny, nie zapis."""
    con, p, drugi = _plik_dwa_hdu(tmp_path)
    prawdziwy = writeback._resync

    def _okno(*a, **kw):
        if obca == "drugie_hdu":
            _zmien_bajt(p, drugi + 7)
        else:
            fits.setval(str(p), "TELESCOP", value="OBCY")
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_resync", _okno)
    writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert _krotki(con) == [("external", None, None, None)]
    assert _odcisk(con) == (scan.scan_file(str(p)).file_sha1, scan.scan_file(str(p)).header_hash)
    con.close()


def test_obca_wersja_przy_backupie_tekstowym_bez_sladu(tmp_path):
    """Cofnięcie backupu tekstowego sprzed śladów rozpoznaje plik samym nagłówkiem, poza blokadą i bez dowodu całego
    pliku: obca wersja z nagłówkiem sprzed zapisu i tym samym obrazem, a innym drugim HDU, dostaje w rodowodzie
    odczyt zewnętrzny, nie cofnięcie."""
    p, drugi = _fits_dwa_hdu(tmp_path / "t.fits")
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    b = _backup(con, cid)
    assert _krotki(con) == [("commit", b, None, None)]
    obca = bytearray(przed)
    obca[drugi + 7] ^= 0x01
    p.write_bytes(bytes(obca))
    writeback.undo(con, cid, now=NOW)
    assert _krotki(con) == [("commit", b, None, None), ("external", None, None, None)]
    con.close()


def test_juz_cofniete_backupu_tekstowego_bez_wiersza(tmp_path):
    """Backup tekstowy sprzed śladów, plik sprzed zapisu wrócił spoza Horreum i skan go opisał: „Cofnij” rozlicza „już
    cofnięte” samym nagłówkiem i bazą (`undo_already_text`) - bez wiersza rodowodu (wynik zna już odczyt zewnętrzny
    skanu, a nagłówek nie dowodzi cofnięcia), plik bez zmian; ponowione „Cofnij” - tak samo."""
    p = _fits(tmp_path / "s.fits")
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    b = _backup(con, cid)
    p.write_bytes(przed)
    _skan(con, p)
    stan = _krotki(con)
    assert stan == [("commit", b, None, None), ("external", None, None, None)]
    for _ in range(2):
        u = writeback.undo(con, cid, now=NOW)
        assert [getattr(f.reason, "code", None) for f in u.already] == ["undo_already_text"] and u.complete, u
        assert _krotki(con) == stan and p.read_bytes() == przed
    con.close()


@pytest.mark.parametrize("droga", ["cofniecie_atomowe", "dokonczenie_w_miejscu"])
def test_obca_wersja_w_drodze_z_kontrola_nie_daje_wiersza_pisarza(tmp_path, monkeypatch, droga):
    """Drogi z kontrolą całego pliku pod blokadą odmawiają obcej wersji przed wjazdem - zero wiersza pisarza; skan
    potem wciąga ją odczytem zewnętrznym."""
    if droga == "cofniecie_atomowe":
        con, p, zmiana, cid, _n = _commit(tmp_path, "fits2hdu")
        b = _backup(con, cid)
        prawdziwy = writeback._podmien

        def _f(*a, **kw):
            wynik = prawdziwy(*a, **kw)
            zmiana(p)
            return wynik
        monkeypatch.setattr(writeback, "_podmien", _f)
        u = writeback.undo(con, cid, now=NOW)
        monkeypatch.undo()
        assert u.failed and _krotki(con) == [("commit", b, None, None)], u
    else:
        con, p, drugi = _plik_dwa_hdu(tmp_path)
        prawdziwy = writeback._dokoncz

        def _f(con_, op_id, **kw):
            _zmien_bajt(p, drugi + 7)
            return prawdziwy(con_, op_id, **kw)
        monkeypatch.setattr(writeback, "_dokoncz", _f)
        c = writeback.commit(con, "R", now=NOW, inplace=True)
        monkeypatch.undo()
        assert c.failed and _wiersze(con) == [], c
    przed = len(_wiersze(con))
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)
    nowe = _wiersze(con)[przed:]
    assert [w["origin"] for w in nowe] == ["external"]
    con.close()


# ============================================================ co najwyżej jeden `commit` na backup


@pytest.mark.parametrize("objazd", [False, True], ids=["wprost", "z_objazdem_z_zewnatrz"])
def test_jeden_commit_na_backup_po_utracie_potwierdzenia(tmp_path, monkeypatch, objazd):
    """Potwierdzenie podmiany przepadło: zapis i tak robi re-sync (wiersz `commit`), a cofnięcie najpierw rekoncyliuje
    backup z dyskiem drugi raz - ta sama obserwacja wyniku nie daje drugiego wiersza `commit`, także gdy między
    obserwacjami plik zmieniono z zewnątrz i przywrócono bajt w bajt (najnowszy wiersz nie jest wtedy zapisem)."""
    con, p = _jeden_plik(tmp_path)
    _makro(con, "R1", "EQ6")

    def _pada(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(repo, "confirm_backup_replaced", _pada)
    c = writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    b1 = _backup(con, c.commit_id)
    assert con.execute("SELECT pending_since FROM header_backups").fetchone()[0] is not None
    assert _krotki(con) == [("commit", b1, None, None)]
    if objazd:
        wynik = p.read_bytes()
        fits.setval(str(p), "TELESCOP", value="EQ8")
        _skan(con, p)
        p.write_bytes(wynik)
        _skan(con, p)
    assert writeback.undo(con, c.commit_id, now=NOW).complete and _tel(p) == "RC8"
    (slad,) = _slady_backupu(con, b1)
    assert _krotki(con) == [("commit", b1, None, None)] + [("external", None, None, None)] * (2 if objazd else 0) + [
        ("undo", b1, None, slad["id"])]
    con.close()


def test_obserwacja_zapisu_po_jego_commicie_albo_cofnieciu_jest_zewnetrzna(tmp_path, monkeypatch):
    """Klinga: re-sync z pochodzeniem zapisu backupu, który ma już wiersz `commit` albo `undo` (także bez wiersza
    `commit` - zapis poznany skanem po śmierci procesu), rozstrzyga się jak odczyt zewnętrzny: wiersz wyłącznie przy
    zmianie odcisku, bez etykiety zapisu - ta sama zasada dla każdej drogi zapisu (atomowej, rekoncyliacji,
    dokończenia w miejscu)."""
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6")
    b1 = _backup(con, c1)
    fits.setval(str(p), "TELESCOP", value="EQ8")
    rec = scan.scan_file(str(p))
    pisarz = repo.Pochodzenie.zapis(b1, (repo.WynikPisarza(rec.header_hash, rec.file_sha1),))
    scan.ingest_record(con, rec, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=pisarz)
    assert _krotki(con) == [("commit", b1, None, None), ("external", None, None, None)]
    con.close()
    (tmp_path / "u").mkdir()
    con, p = _jeden_plik(tmp_path / "u")
    _makro(con, "R1", "EQ6")
    _smierc_po_podmianie(monkeypatch, z_potwierdzeniem=True)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    (c1,) = [r[0] for r in con.execute("SELECT id FROM commits")]
    b1 = _backup(con, c1)
    _skan(con, p)
    assert writeback.undo(con, c1, now=NOW).complete
    stan = _krotki(con)
    assert [k[0] for k in stan] == ["external", "undo"]
    rec = scan.scan_file(str(p))
    pisarz = repo.Pochodzenie.zapis(b1, (repo.WynikPisarza(rec.header_hash, rec.file_sha1),))
    scan.ingest_record(con, rec, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=pisarz)
    assert _krotki(con) == stan
    con.close()


def _cofnij_i_zapisz_w_drugim_procesie(sciezka_bazy, c1):
    """Drugi proces: cofnięcie C1 i zapis C2 tych samych bajtów (EQ6) na tym samym pliku."""
    con2 = db.connect(sciezka_bazy)
    try:
        assert writeback.undo(con2, c1, now=NOW).complete
        _makro(con2, "R2", "EQ6")
        assert writeback.commit(con2, "R2", now=NOW).applied
    finally:
        con2.close()


@pytest.mark.parametrize("chwila", ["przed_resynciem", "po_odczycie_rekordu"])
def test_spozniony_resync_zapisu_cofnietego_w_innym_procesie(tmp_path, monkeypatch, chwila):
    """Proces 1 potwierdził podmianę C1 i stoi przed re-synciem (albo po odczycie rekordu, przed transakcją wjazdu);
    proces 2 cofa C1 i zapisuje C2 tymi samymi bajtami. Spóźniony re-sync C1 nie dopisuje wiersza `commit` C1 nad
    cofnięciem C1 ani fałszywego odczytu zewnętrznego (odcisk już znany). Scena: przeplot zachodzi dokładnie raz,
    w jedynym wywołaniu procesu 1, przy backupie C1 już potwierdzonym i bez wiersza rodowodu."""
    con, p = _jeden_plik(tmp_path)
    sciezka = str(tmp_path / "p.db")
    _makro(con, "R1", "EQ6")
    wywolania_p1, przy_przeplocie, w_drugim = [], [], []

    def _przeplot():
        wywolania_p1.append(1)
        if len(wywolania_p1) > 1:
            return
        przy_przeplocie.append(([r[0] for r in con.execute("SELECT pending_since FROM header_backups")],
                                len(_wiersze(con))))
        w_drugim.append(1)
        try:
            _cofnij_i_zapisz_w_drugim_procesie(sciezka, _commity(con)[0])
        finally:
            w_drugim.clear()
    if chwila == "przed_resynciem":
        prawdziwy = writeback._resync

        def _okno(con_, *a, **kw):
            if con_ is con:
                _przeplot()
            return prawdziwy(con_, *a, **kw)
        monkeypatch.setattr(writeback, "_resync", _okno)
    else:
        prawdziwy = writeback._skan_kontrolny

        def _okno(path, kontrola):
            rec = prawdziwy(path, kontrola)
            if not w_drugim:
                _przeplot()
            return rec
        monkeypatch.setattr(writeback, "_skan_kontrolny", _okno)
    writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    assert (len(wywolania_p1), przy_przeplocie) == (1, [([None], 0)])
    c1, c2 = _commity(con)
    b1, b2 = _backup(con, c1), _backup(con, c2)
    assert repo.wynik_zapisu(con, b1).file_sha1 == _odcisk(con)[0], "scena: C2 zapisał inne bajty niż C1"
    (slad,) = _slady_backupu(con, b1)
    assert _krotki(con) == [("undo", b1, None, slad["id"]), ("commit", b2, None, None)]
    con.close()


def _commity(con):
    return [r[0] for r in con.execute("SELECT id FROM commits ORDER BY id")]


# ============================================================ ślad cofnięcia atomowego: jedno rozstrzygnięcie


def _dopisz_drugi_slad(con, slad):
    return repo.record_atomic_undo(
        con, backup_id=slad["backup_id"], result_sha1=slad["result_sha1"], result_size=slad["result_size"],
        result_hash=slad["result_hash"], byte_exact=slad["byte_exact"], source_sha1=slad["source_sha1"],
        source_size=slad["source_size"], displaced_path=slad["displaced_path"] + ".2",
        prepared_path=slad["prepared_path"] + ".2", now=NOW)


@pytest.mark.parametrize("droga", ["wlasny_slad", "ponowienie"])
def test_slad_wiersza_rozstrzygany_w_transakcji(tmp_path, monkeypatch, droga):
    """Drugi ślad z tą samą parą odcisków dopisany między zbudowaniem pochodzenia a transakcją re-syncu: wiersz
    rodowodu i oznaczenie `synced_at` wskazują ten sam ślad albo żaden. Re-sync własnej próby - nowszy cudzy ślad nie
    jest jej, więc żaden; ponowienie rozpoznaje najnowszy ślad pary - oba wskazują go."""
    if droga == "wlasny_slad":
        con, p = _jeden_plik(tmp_path)
        c1 = _zapis(con, "R1", "EQ6")
    else:
        con, p, c1, _b, _au = _umiera_po_podmianie_cofniecia(tmp_path, monkeypatch)
    b1 = _backup(con, c1)
    prawdziwy = writeback._resync
    drugi = []

    def _okno(con_, *a, **kw):
        if not drugi and kw["pochodzenie"].origin == "undo":
            drugi.append(_dopisz_drugi_slad(con_, _slady_backupu(con_, b1)[-1]))
        return prawdziwy(con_, *a, **kw)
    monkeypatch.setattr(writeback, "_resync", _okno)
    assert writeback.undo(con, c1, now=NOW).complete
    monkeypatch.undo()
    (wiersz,) = [w for w in _wiersze(con) if w["origin"] == "undo"]
    oznaczone = [s["id"] for s in _slady_backupu(con, b1) if s["synced_at"] is not None]
    assert ([wiersz["atomic_undo_id"]] if wiersz["atomic_undo_id"] else []) == oznaczone
    assert wiersz["atomic_undo_id"] == (None if droga == "wlasny_slad" else drugi[0])
    con.close()


# ============================================================ cofnięcie bez własnego śladu (dowód całego pliku)


def test_region_sprzed_bez_sladu_daje_cofniecie(tmp_path):
    """C1 A → B, C2 B → A (osobne przebiegi), cofnięcie C2; potem cały plik sprzed C1 wraca bez skanu i pierwsze
    cofnięcie C1 idzie dowodem całego pliku bez własnego śladu (`_region_sprzed` → re-sync): wiersz `undo` C1 z
    nagłówkiem A - nie odczyt zewnętrzny, który przeciąłby łańcuch cofnięć."""
    con, p = _jeden_plik(tmp_path)
    oryginal = p.read_bytes()
    c1 = _zapis(con, "R1", "EQ6")
    c2 = _zapis(con, "R2", "RC8")
    assert writeback.undo(con, c2, now=NOW).complete and _tel(p) == "EQ6"
    p.write_bytes(oryginal)
    b1, b2 = _backup(con, c1), _backup(con, c2)
    assert writeback.undo(con, c1, now=NOW).complete
    assert _slady_backupu(con, b1) == []
    wiersze = _wiersze(con)
    assert [(w["origin"], w["backup_id"]) for w in wiersze] == [("commit", b1), ("commit", b2), ("undo", b2),
                                                               ("undo", b1)]
    assert (wiersze[-1]["header_hash"], wiersze[-1]["atomic_undo_id"]) == (wiersze[1]["header_hash"], None)
    con.close()


def test_pochodzenie_cofniecia_niesie_pary_sladow_i_naglowek_kontroli(tmp_path, monkeypatch):
    """`_sync` buduje wynik cofnięcia z par WSZYSTKICH własnych śladów backupu i nagłówka kontroli bez sha1 - plik
    pasujący do pary starszego śladu z innym nagłówkiem jest cofnięciem, a plik dowiedziony podstawieniem regionu
    (sha1 inny niż kotwica i niż ślady) - też, po nagłówku."""
    con, p = _jeden_plik(tmp_path)
    c1 = _zapis(con, "R1", "EQ6")
    b1 = _backup(con, c1)
    repo.record_atomic_undo(con, backup_id=b1, result_sha1=S40, result_size=1, result_hash=H40, byte_exact=0,
                            source_sha1=S40, source_size=1, displaced_path=str(p) + ".k",
                            prepared_path=str(p) + ".t", now=NOW)
    prawdziwy = writeback._resync
    zbudowane = []

    def _szpieg(*a, **kw):
        zbudowane.append(kw["pochodzenie"])
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_resync", _szpieg)
    assert writeback.undo(con, c1, now=NOW).complete
    monkeypatch.undo()
    (pochodzenie,) = [x for x in zbudowane if x.origin == "undo"]
    slady = _slady_backupu(con, b1)
    naglowek = _odcisk(con)[1]
    assert set(pochodzenie.wyniki) == {repo.WynikPisarza(s["result_hash"], s["result_sha1"]) for s in slady} | {
        repo.WynikPisarza(naglowek)}
    assert pochodzenie.dla(S40, H40) == ("undo", b1, None)                 # para starszego śladu, inny nagłówek
    assert pochodzenie.dla("f" * 40, naglowek) == ("undo", b1, None)       # region podstawiony, sha1 obcy
    con.close()


# ============================================================ powtórzone obserwacje i przypisanie z dowodem


def test_powtorzona_obserwacja_bez_zmiany_nie_dubluje(tmp_path, monkeypatch):
    """Obserwacja pisarza bez zmiany odcisku identyczna z najnowszym wierszem lokacji (to samo pochodzenie, backup
    i odcisk) nie dopisuje wiersza - powtórzone cofnięcie nie jest nowym przejściem stanu."""
    con, p, c1, b1, au = _umiera_po_podmianie_cofniecia(tmp_path, monkeypatch)
    _skan(con, p)
    writeback.undo(con, c1, now=NOW)
    lid = con.execute("SELECT id FROM location").fetchone()[0]
    stan = _krotki(con)
    assert repo.attribute_undo_state(con, location_id=lid, atomic_undo_id=au, now=NOW) is None
    sha1, naglowek = _odcisk(con)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.Pochodzenie.cofniecie(b1, (repo.WynikPisarza(naglowek, sha1),),
                                                              slad=au, rozpoznaj_slad=True))
    assert _krotki(con) == stan
    con.close()


def test_przypisanie_wymaga_pary_sladu(tmp_path):
    """Przypisanie „już cofnięte” tylko dla lokacji, która opisuje DOKŁADNIE parę odcisków śladu; ślad innej lokacji
    to błąd wołającego."""
    con, pliki = _baza(tmp_path, 2)
    _makro(con, "R1", "EQ6")
    c1 = writeback.commit(con, "R1", now=NOW).commit_id
    assert writeback.undo(con, c1, now=NOW).complete
    l0, l1 = [r[0] for r in con.execute("SELECT id FROM location ORDER BY id")]

    def _slad_lokacji(lid):
        (au,) = con.execute("SELECT au.id FROM atomic_undo au JOIN header_backups hb ON hb.id = au.backup_id "
                            "WHERE hb.location_id = ?", (lid,)).fetchone()
        return au
    au0, au1 = _slad_lokacji(l0), _slad_lokacji(l1)
    fits.setval(str(pliki[0]), "TELESCOP", value="EQ8")
    _skan(con, pliki[0])
    stan = _krotki(con)
    assert repo.attribute_undo_state(con, location_id=l0, atomic_undo_id=au0, now=NOW) is None
    with pytest.raises(ValueError):
        repo.attribute_undo_state(con, location_id=l0, atomic_undo_id=au1, now=NOW)
    assert _krotki(con) == stan
    con.close()


def test_przypisanie_wymaga_sha1_pary_sladu(tmp_path, monkeypatch):
    """Cofnięcie zginęło po podmianie, potem bajt drugiego HDU zmieniono, a skan wciągnął plik: nagłówek i obraz są
    wynikiem śladu, cały plik nie. Przypisanie „już cofnięte” odmawia - para śladu wymaga też sha1 pliku."""
    con, p, drugi = _plik_dwa_hdu(tmp_path)
    c = writeback.commit(con, "R", now=NOW)
    b1 = _backup(con, c.commit_id)
    _smierc_po_podmianie(monkeypatch, z_potwierdzeniem=False)
    with pytest.raises(_Smierc):
        writeback.undo(con, c.commit_id, now=NOW)
    monkeypatch.undo()
    (slad,) = _slady_backupu(con, b1)
    _zmien_bajt(p, drugi + 7)
    _skan(con, p)
    lid = con.execute("SELECT id FROM location").fetchone()[0]
    sha1, naglowek = _odcisk(con)
    assert naglowek == slad["result_hash"] and sha1 != slad["result_sha1"]
    stan = _krotki(con)
    assert stan == [("commit", b1, None, None), ("external", None, None, None)]
    assert repo.attribute_undo_state(con, location_id=lid, atomic_undo_id=slad["id"], now=NOW) is None
    assert _krotki(con) == stan
    con.close()


# ============================================================ kolejność: zatwierdzone obserwacje


def test_wycofana_transakcja_nie_zostawia_wiersza(tmp_path, monkeypatch):
    """Błąd w transakcji re-syncu zapisu (rozliczenie wpisów stagingu) wycofuje wjazd razem z wierszem rodowodu."""
    con, p = _jeden_plik(tmp_path)
    _makro(con, "R1", "EQ6")
    przed = _odcisk(con)
    prawdziwy = repo.set_pending_status

    def _pada(con_, **kw):
        if kw.get("status") == "applied":
            raise sqlite3.OperationalError("disk I/O error")
        return prawdziwy(con_, **kw)
    monkeypatch.setattr(repo, "set_pending_status", _pada)
    c = writeback.commit(con, "R1", now=NOW)
    monkeypatch.undo()
    assert c.failed and _tel(p) == "EQ6", c
    assert _wiersze(con) == [] and _odcisk(con) == przed
    con.close()


def test_stary_odczyt_skanu_nie_zostawia_wiersza(tmp_path, monkeypatch):
    """Strażnik generacji w klindze faktów kopii odmawia odczytowi starszemu niż operacja zapisu w miejscu - zero
    zapisu, także wiersza rodowodu."""
    con, p = _jeden_plik(tmp_path)
    gen = repo.inplace_generation(con)
    _zapis(con, "R1", "EQ6", inplace=True)
    stan = _krotki(con)
    fits.setval(str(p), "TELESCOP", value="EQ8")
    monkeypatch.setattr(scan, "_odmow_staremu_odczytowi", lambda *a, **kw: None)
    with pytest.raises(repo.StaleScanRecord):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                           inplace_gen=gen, pochodzenie=repo.ZEWNETRZNE)
    assert _krotki(con) == stan
    con.close()


def _odzysk_przy_bazie_znajacej_stan_rozdarty(tmp_path, monkeypatch):
    p = _fits(tmp_path / "r.fits")
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)                     # z pominięciem bramki izolacji skanu
    assert [w["origin"] for w in _wiersze(con)] == ["external"]
    return con, p, op, przed


@pytest.mark.parametrize("baza_zna_rozdarcie", [False, True], ids=["bez_zmiany_odcisku", "ze_zmiana"])
def test_odzysk_rozdarcia(tmp_path, monkeypatch, baza_zna_rozdarcie):
    """Odzysk przywraca stan sprzed operacji. Baza opisuje plik sprzed niej (re-sync zapisu nie zaszedł) - odcisk bez
    zmiany, zero wierszy; baza znała odcisk zapisu - wiersz powrotu pisarza z operacją i nagłówkiem sprzed niej."""
    if baza_zna_rozdarcie:
        con, p, op, przed = _odzysk_przy_bazie_znajacej_stan_rozdarty(tmp_path, monkeypatch)
    else:
        p = _fits(tmp_path / "r.fits")
        con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
    assert p.read_bytes() == przed
    if baza_zna_rozdarcie:
        assert _krotki(con) == [("external", None, None, None), ("rollback", None, op["id"], None)]
        assert _wiersze(con)[-1]["header_hash"] == op["pre_hash"]
    else:
        assert _wiersze(con) == []
    con.close()


def test_wynik_odzysku_niesie_kotwice_pliku(tmp_path, monkeypatch):
    """Wynik powrotu pisarza to nagłówek sprzed operacji RAZEM z kotwicą (sha1 pliku sprzed niej): obca wersja
    z tym samym nagłówkiem starego regionu, ale innym plikiem, wchodzi odczytem zewnętrznym, nie wierszem
    `rollback`."""
    con, p, op, przed = _odzysk_przy_bazie_znajacej_stan_rozdarty(tmp_path, monkeypatch)
    prawdziwy = writeback._resync
    zbudowane = []

    def _szpieg(*a, **kw):
        zbudowane.append(kw["pochodzenie"])
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_resync", _szpieg)
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
    monkeypatch.undo()
    (pochodzenie,) = zbudowane
    kotwica = hashlib.sha1(przed).hexdigest()
    assert pochodzenie.wyniki == (repo.WynikPisarza(op["pre_hash"], kotwica),)
    assert pochodzenie.dla("f" * 40, op["pre_hash"]) == ("external", None, None)
    stan = _krotki(con)
    assert stan[-1] == ("rollback", None, op["id"], None)
    obcy = dataclasses.replace(scan.scan_file(str(p)), file_sha1="f" * 40)
    scan.ingest_record(con, obcy, volume="V", now=NOW, summary=scan.ScanSummary(), pochodzenie=pochodzenie)
    assert _krotki(con) == stan + [("external", None, None, None)]
    con.close()


def test_odzysk_przerwany_przed_faza_recovered(tmp_path, monkeypatch):
    """`id` porządkuje zatwierdzone obserwacje, nie zakończenia operacji: re-sync odzysku zatwierdzony, faza
    `recovered` padła - wiersz powrotu zostaje, operacja otwarta; ponowienie domyka fazę bez drugiego wiersza."""
    con, p, op, przed = _odzysk_przy_bazie_znajacej_stan_rozdarty(tmp_path, monkeypatch)
    prawdziwa = repo.set_inplace_op_phase

    def _pada(con_, **kw):
        if kw.get("phase") == "recovered":
            raise sqlite3.OperationalError("disk I/O error")
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "set_inplace_op_phase", _pada)
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "failed"
    monkeypatch.undo()
    assert [w["origin"] for w in _wiersze(con)] == ["external", "rollback"]
    assert repo.inplace_op_phase(con, op["id"]) in repo.INPLACE_OPEN_PHASES
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
    assert [w["origin"] for w in _wiersze(con)] == ["external", "rollback"]
    assert repo.inplace_op_phase(con, op["id"]) == "recovered"
    con.close()


# Sekwencje czystej reguły klasy (wiersze `location_state` scen łańcucha cofnięć; `c X` - zapis commitu X, `u X` -
# cofnięcie, `e` - odczyt zewnętrzny) i wzór nagłówków (ta sama litera = ten sam odcisk nagłówka).
_SEKWENCJE = {
    "H1a": ([("commit", "c1"), ("commit", "c2"), ("undo", "c2"), ("undo", "c1")], "BABA"),
    "H1m": ([("commit", "c1"), ("commit", "c2"), ("undo", "c2"), ("undo", "c1")], "BABA"),
    "Z1": ([("commit", "c1"), ("commit", "c2"), ("undo", "c2"), ("external", None), ("external", None),
            ("undo", "c1")], "BABCBA"),
    "K2": ([("commit", "c1"), ("commit", "c2"), ("commit", "c3"), ("undo", "c3"), ("undo", "c2"), ("undo", "c1"),
            ("external", None), ("external", None), ("undo", "c3")], "BACABADCA"),
}


@pytest.mark.parametrize("kod", list(_SEKWENCJE))
def test_kolejnosc_wierszy_scen(tmp_path, kod):
    """Sceny łańcucha cofnięć na prawdziwym pisarzu dają w rodowodzie dokładnie sekwencję, na której sprawdzono
    regułę klasy: pochodzenia, commity i wzór nagłówków po `id`; najnowszy wiersz ma odcisk lokacji."""
    sc = _scena(tmp_path, kod)
    try:
        commit_backupu = {_backup(sc.con, getattr(sc, c)): c for c in ("c1", "c2", "c3") if hasattr(sc, c)}
        wiersze = _wiersze(sc.con)
        sekwencja, wzor = _SEKWENCJE[kod]
        assert [(w["origin"], commit_backupu.get(w["backup_id"])) for w in wiersze] == sekwencja
        litery = {}
        for w, litera in zip(wiersze, wzor):
            litery.setdefault(litera, w["header_hash"])
            assert w["header_hash"] == litery[litera], (kod, w["id"], litera)
        assert len(set(litery.values())) == len(litery), (kod, litery)
        _odcisk_najnowszego_zgodny(sc.con)
    finally:
        sc.con.close()
