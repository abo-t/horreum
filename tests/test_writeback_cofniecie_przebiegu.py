"""Cofnięcie CAŁEGO przebiegu kart (AR-345): `writeback.undo_run` na zakresie zamrożonym
(`writeback.przebieg_do_cofniecia`), wspólna pętla z `writeback.undo` (wynik per lokacja, łańcuch przebiegu),
klasy backupu dla liczb szuflady, zdarzenie zamiaru i wiersz Porządków „Dokończ cofnięcie”, oraz klinga
„Ponów nieudane” (`repo.nieudane_do_ponowienia`, `repo.ponow_nieudane`, AR-347). Prawdziwy pisarz na
syntetycznych FITS w `tmp_path`; atrapy wyłącznie awarii wstrzykiwanych na czas jednego wywołania."""
import os

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, macro, repo, scan, writeback
from horreum.gui import queries

NOW = "2026-10-26T12:00:00+00:00"


def _baza(tmp_path, n, nazwa="p"):
    con = db.open_db(str(tmp_path / f"{nazwa}.db"))
    pliki = []
    for i in range(n):
        p = tmp_path / f"{nazwa}{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i + 1, dtype=np.int16))
        for k, v in (("IMAGETYP", "Light"), ("OBJECT", "NGC7000"), ("TELESCOP", "RC8"),
                     ("DATE-OBS", f"2024-03-{15 + i:02d}T21:30:45"), ("EXPTIME", 300.0)):
            hdu.header[k] = v
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                           pochodzenie=repo.ZEWNETRZNE)
        pliki.append(p)
    return con, pliki


def _klatki(con):
    return [r[0] for r in con.execute("SELECT id FROM frame ORDER BY id")]


def _makro(con, run_id, wartosc, ids=None):
    md = macro.MacroDef.from_dict({"assign": {"keyword": "TELESCOP", "op": "set", "expr": repr(wartosc)}})
    mr = macro.run_macro(md, ids or _klatki(con), targets_fn=lambda i: queries.writeback_frame_targets(con, i),
                         cards_fn=lambda fid: queries.frame_cards(con, fid), run_id=run_id)
    repo.stage_pending_many(con, run_id=run_id, previews=mr.touched)


def _tel(p):
    return fits.getheader(str(p))["TELESCOP"]


def _kody(lista):
    return [getattr(fr.reason, "code", fr.reason) for fr in lista]


def _nakladka(tmp_path, droga, nazwa="n"):
    """Przebieg `R`: C1 zapisuje L0 i L1 (RC8 → EQ6), C2 zapisuje ponownie L0 (EQ6 → EQ8). `droga` = para
    liter dróg C1/C2: `a` atomowa, `m` w miejscu."""
    con, pliki = _baza(tmp_path, 2, nazwa)
    f0, f1 = _klatki(con)
    _makro(con, "R", "EQ6", [f0, f1])
    writeback.commit(con, "R", now=NOW, inplace=droga[0] == "m")
    _makro(con, "R", "EQ8", [f0])
    writeback.commit(con, "R", now=NOW, inplace=droga[1] == "m")
    assert writeback._commity_przebiegu(con, "R") == (1, 2) and [_tel(p) for p in pliki] == ["EQ8", "EQ6"]
    return con, pliki


# ============================================================ cofnięcie przebiegu i łańcuch


def test_przebieg_przerwany_i_dokonczony_cofa_wszystkie_pliki(tmp_path):
    """Zapis przerwany po pierwszym pliku i dokończony daje dwa commity przebiegu; zakres „Cofnij” ma oba,
    a `undo_run` przywraca WSZYSTKIE trzy pliki jednym biegiem. Falsyfikator: cofnięcie samego najnowszego
    commitu (plik pierwszego zostaje EQ6)."""
    con, pliki = _baza(tmp_path, 3)
    przed = [p.read_bytes() for p in pliki]
    _makro(con, "R", "EQ6")
    licz = []
    writeback.commit(con, "R", now=NOW, inplace=True, should_cancel=lambda: licz.append(1) or len(licz) > 1)
    writeback.commit(con, "R", now=NOW, inplace=True)
    zakres = writeback.przebieg_do_cofniecia(con, "R")
    assert zakres == writeback.ZakresCofniecia((1, 2), 3, 0, 0), zakres
    wynik = writeback.undo_run(con, zakres.commity, now=NOW)
    assert [p.read_bytes() for p in pliki] == przed
    assert len(wynik.restored) == 3 and wynik.complete and wynik.commit_id == "R"
    assert writeback.przebieg_do_cofniecia(con, "R") is None
    con.close()


@pytest.mark.parametrize("droga", ["aa", "am", "ma", "mm"])
def test_nakladka_cofa_sie_i_ponowienie_domyka(tmp_path, droga):
    """Ta sama lokacja w dwóch commitach przebiegu, każda para dróg zapisu: bieg 1 przywraca oba pliki do RC8
    (od najnowszego - od najstarszego starszy odmawia `undo_newer_write`); ponowienie domyka przebieg bez
    zapisu pliku i zakres schodzi do `None`. Drogi `aa`/`ma` (nowszy atomowy) dawały dawniej przy ponowieniu
    `undo_header_changed` - łańcuch przebiegu. Falsyfikatory: kolejność od najstarszego; bez łańcucha."""
    con, pliki = _nakladka(tmp_path, droga)
    pierwszy = writeback.undo_run(con, (1, 2), now=NOW)
    assert [_tel(p) for p in pliki] == ["RC8", "RC8"] and pierwszy.complete, _kody(pierwszy.blocked)
    po = [p.read_bytes() for p in pliki]
    ponowienie = writeback.undo_run(con, (1, 2), now=NOW)
    assert ponowienie.complete and not ponowienie.restored, (_kody(ponowienie.blocked), _kody(ponowienie.failed))
    assert [p.read_bytes() for p in pliki] == po
    assert writeback.przebieg_do_cofniecia(con, "R") is None
    con.close()


def test_nakladka_atomowa_przerwana_w_starszym_ponowienie_domyka(tmp_path):
    """Wariant przerwania: cofnięcie przebiegu (obie drogi atomowe) przerwane po L0 starszego commitu (L1
    nietknięty) - ponowienie przywraca L1 i domyka przebieg; L0 to „już cofnięte” łańcuchem. Falsyfikator:
    bez łańcucha ponowienie nowszego commitu w kółko odmawia `undo_header_changed`."""
    con, pliki = _nakladka(tmp_path, "aa")
    licz = []
    przerwane = writeback.undo_run(con, (1, 2), now=NOW, should_cancel=lambda: licz.append(1) or len(licz) > 2)
    assert przerwane.cancelled and [_tel(p) for p in pliki] == ["RC8", "EQ6"]
    ponowienie = writeback.undo_run(con, (1, 2), now=NOW)
    assert ponowienie.complete and [_tel(p) for p in pliki] == ["RC8", "RC8"], _kody(ponowienie.blocked)
    con.close()


def test_lancuch_wymaga_wlasnego_cofniecia_nowszego(tmp_path):
    """Starszy commit cofnięty W MIEJSCU (faza `synced` - dowód zakończenia na zawsze), POTEM ten sam przebieg
    zapisuje lokację ponownie drogą atomową. Nowszego nikt nie cofał: jest w zakresie i `undo_run` go cofa.
    Falsyfikator: łańcuch bez warunku „własne cofnięcie domknięte” - nowszy uznany za cofnięty, plik zostaje EQ8."""
    con, (p,) = _baza(tmp_path, 1)
    _makro(con, "R", "EQ6")
    c1 = writeback.commit(con, "R", now=NOW, inplace=True).commit_id
    assert writeback.undo(con, c1, now=NOW).complete and _tel(p) == "RC8"
    _makro(con, "R", "EQ8")
    c2 = writeback.commit(con, "R", now=NOW, inplace=False).commit_id
    zakres = writeback.przebieg_do_cofniecia(con, "R")
    assert zakres is not None and zakres.commity == (c2,), zakres
    writeback.undo_run(con, zakres.commity, now=NOW)
    assert _tel(p) == "RC8"
    con.close()


def test_pojedyncze_undo_nowszego_po_cofnieciu_starszego_mowi_juz_cofniete(tmp_path):
    """`header-fix --undo N` (`writeback.undo`) nowszego commitu atomowego po cofnięciu obu: „już cofnięte”
    łańcuchem przebiegu, cofnięcie domknięte, plik nietknięty. Falsyfikator: bez łańcucha w pętli wspólnej
    `undo_header_changed` o pliku w stanie sprzed przebiegu."""
    con, pliki = _nakladka(tmp_path, "aa")
    assert writeback.undo(con, 2, now=NOW).complete and writeback.undo(con, 1, now=NOW).complete
    po = [p.read_bytes() for p in pliki]
    wynik = writeback.undo(con, 2, now=NOW)
    assert wynik.complete and _kody(wynik.already) == ["undo_already_chain"], _kody(wynik.blocked)
    assert [p.read_bytes() for p in pliki] == po
    con.close()


def test_wynik_per_lokacja_nie_per_backup(tmp_path):
    """Nakładka cofnięta w całości: `restored` liczy dwa PLIKI, nie trzy backupy - zdanie okna mówiłoby
    „3 przywrócone” o dwóch plikach. Falsyfikator: scalenie list wyników commitów."""
    con, _p = _nakladka(tmp_path, "aa")
    wynik = writeback.undo_run(con, (1, 2), now=NOW)
    assert sorted(fr.location_id for fr in wynik.restored) == [1, 2]
    con.close()


def test_lokacja_w_stanie_posrednim_jest_tylko_zablokowana(tmp_path):
    """Nowszy commit wrócił, a zanim przyszła kolej starszego, plik L0 zmienił się z zewnątrz - starszy
    odmawia. Lokacja ma JEDEN wynik (blokada), nie „przywrócona i zablokowana” naraz; L1 przywrócony.
    Falsyfikator: scalenie list (L0 w `restored` i w `blocked`)."""
    con, pliki = _nakladka(tmp_path, "aa")

    def _postep(done, total, path, status):
        if done == 1:
            fits.setval(str(pliki[0]), "OBSERVER", value="obcy")
    wynik = writeback.undo_run(con, (1, 2), now=NOW, progress=_postep)
    assert [fr.location_id for fr in wynik.restored] == [2]
    assert [fr.location_id for fr in wynik.blocked] == [1] and not wynik.complete
    con.close()


def test_obiekty_per_klatka_werdykt_najstarszego(tmp_path, monkeypatch):
    """Stan obiektu klatki (AR-311) cofany w dwóch commitach przebiegu: jeden werdykt na klatkę - najstarszego
    commitu (stan końcowy), bez powtórzeń. Atrapa werdyktu rdzenia (`repo.object_undo_verdict`), reszta
    prawdziwa. Falsyfikator: pierwszy werdykt wygrywa (`setdefault` po całym przebiegu)."""
    con, _p = _nakladka(tmp_path, "aa")
    monkeypatch.setattr(repo, "object_undo_verdict",
                        lambda con, *, commit_id, location_id: (7, "wrocil" if commit_id == 2 else "zostaje"))
    wynik = writeback.undo_run(con, (1, 2), now=NOW)
    assert wynik.objects_kept == (7,) and wynik.objects_restored == ()
    con.close()


def test_przerwanie_liczy_reszte_po_wszystkich_commitach(tmp_path):
    """Przerwanie w środku najnowszego commitu: reszta (`remaining`) obejmuje jego nieprzetworzone backupy
    I backupy starszego commitu, a postęp liczy backupy całego zakresu. Falsyfikator: reszta tylko
    z commitu, w którym pętla stanęła."""
    con, pliki = _baza(tmp_path, 3)
    f0, f1, f2 = _klatki(con)
    _makro(con, "R", "EQ6", [f0])
    writeback.commit(con, "R", now=NOW, inplace=True)
    _makro(con, "R", "EQ6", [f1, f2])
    writeback.commit(con, "R", now=NOW, inplace=True)
    postep, licz = [], []
    wynik = writeback.undo_run(con, (1, 2), now=NOW, progress=lambda d, t, p, s: postep.append((d, t)),
                               should_cancel=lambda: licz.append(1) or len(licz) > 1)
    assert wynik.cancelled and wynik.remaining == 2 and postep == [(1, 3)], (wynik.remaining, postep)
    con.close()


_J, _S, _W = "juz", "semantycznie", "wstrzymane"
# Wyniki JEDNEJ lokacji w kolejności pętli (od najnowszego commitu): (status, znak, cechy) → oczekiwany jeden wynik
# (status, znak, cechy). Hierarchia: failed > blocked spoza „już cofnięte” > restored > „już cofnięte”; porażka
# równej wagi - pierwsza (przyczyna z najnowszego commitu); przywrócenie - ostatnie (najstarszy commit, stan
# końcowy pliku), z niego `semantic` i `withheld`.
_HIERARCHIA = {
    "failed_po_restored": ([("restored", "r", ()), ("failed", "f", ())], ("failed", "f", ())),
    "failed_przed_restored": ([("failed", "f", ()), ("restored", "r", ())], ("failed", "f", ())),
    "failed_po_blocked": ([("blocked", "b", ()), ("failed", "f", ())], ("failed", "f", ())),
    "blocked_po_restored": ([("restored", "r", ()), ("blocked", "b", ())], ("blocked", "b", ())),
    "blocked_przed_restored": ([("blocked", "b", ()), ("restored", "r", ())], ("blocked", "b", ())),
    "restored_po_juz": ([("blocked", "j", (_J,)), ("restored", "r", ())], ("restored", "r", ())),
    "restored_przed_juz": ([("restored", "r", ()), ("blocked", "j", (_J,))], ("restored", "r", ())),
    "blocked_po_juz": ([("blocked", "j", (_J,)), ("blocked", "b", ())], ("blocked", "b", ())),
    "pierwsza_failed": ([("failed", "f1", ()), ("failed", "f2", ())], ("failed", "f1", ())),
    "pierwsza_blocked": ([("blocked", "b1", ()), ("blocked", "b2", ())], ("blocked", "b1", ())),
    "pelna_hierarchia": ([("blocked", "j", (_J,)), ("restored", "r", ()), ("blocked", "b", ()), ("failed", "f", ())],
                         ("failed", "f", ())),
    "restored_ostatni_bez_cech": ([("restored", "r1", (_S, _W)), ("restored", "r2", ())], ("restored", "r2", ())),
    "restored_ostatni_z_cechami": ([("restored", "r1", ()), ("restored", "r2", (_S, _W))],
                                   ("restored", "r2", (_S, _W))),
}


@pytest.mark.parametrize("sekwencja, oczek", list(_HIERARCHIA.values()), ids=list(_HIERARCHIA))
def test_wynik_lokacji_z_kilku_commitow_wedlug_hierarchii(monkeypatch, sekwencja, oczek):
    """Pętla wspólna (`_cofnij_backupy`) składa wyniki jednej lokacji z kilku commitów w JEDEN wynik według
    hierarchii (tabela `_HIERARCHIA`). Atrapa ciała cofnięcia (`_cofnij_lokacje` - wyniki ze skryptu), bez bazy.
    Falsyfikatory: każda gałąź wagi (`_waga_wyniku`) i oba remisy."""
    wyniki = iter([writeback._CofniecieLokacji(writeback.FileResult(1, "L.fits", s, znak), juz=_J in cechy,
                                               semantycznie=_S in cechy, wstrzymane=_W in cechy)
                   for s, znak, cechy in sekwencja])
    monkeypatch.setattr(writeback, "_cofnij_lokacje", lambda con, cid, b, *, now: next(wyniki))
    monkeypatch.setattr(writeback, "_skrot_juz_cofnietego", lambda con, b: None)
    monkeypatch.setattr(repo, "object_undo_verdict", lambda con, *, commit_id, location_id: (None, None))
    pozycje = [(len(sekwencja) - i, {"id": i + 1, "location_id": 1}) for i in range(len(sekwencja))]
    wynik = writeback._cofnij_backupy(None, "R", pozycje, now=NOW, progress=None, should_cancel=None)
    status, znak, cechy = oczek
    [fr] = wynik.restored + wynik.blocked + wynik.failed
    assert (fr.status, fr.reason) == (status, znak), fr
    assert (wynik.already == [fr], wynik.semantic == [fr], wynik.withheld == [fr]) == (_J in cechy, _S in cechy,
                                                                                         _W in cechy)


def test_zakres_z_dwoch_przebiegow_odmawia_przed_zapisem(tmp_path):
    """Zakres z commitami dwóch przebiegów to błąd wołającego (EXPECT): `ValueError`, zero zdarzeń i zero
    zmian plików. Falsyfikator: bieg bez strażnika."""
    con, pliki = _baza(tmp_path, 2)
    f0, f1 = _klatki(con)
    _makro(con, "R", "EQ6", [f0])
    writeback.commit(con, "R", now=NOW)
    _makro(con, "S", "EQ6", [f1])
    writeback.commit(con, "S", now=NOW)
    with pytest.raises(ValueError):
        writeback.undo_run(con, (1, 2), now=NOW)
    assert [_tel(p) for p in pliki] == ["EQ6", "EQ6"]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'run.undo_started'").fetchone()[0] == 0
    con.close()


# ============================================================ klasy backupu (liczby szuflady)


def _jeden_zapis(tmp_path, stan, monkeypatch):
    """Jeden plik, przebieg `R`, zapis zakończony w stanie `stan`; zwraca (con, plik, bajty sprzed zapisu)."""
    con, (p,) = _baza(tmp_path, 1)
    przed = p.read_bytes()
    _makro(con, "R", "EQ6")
    if stan == "atomowy":
        writeback.commit(con, "R", now=NOW, inplace=False)
    elif stan == "niepotwierdzony":
        with monkeypatch.context() as m:
            m.setattr(writeback, "_replace_file_w",
                      lambda path, tmp, kopia: (_ for _ in ()).throw(OSError(None, "awaria podmiany", None, 87)))
            writeback.commit(con, "R", now=NOW, inplace=False)
    elif stan == "przed_bajtem":
        prawdziwe = repo.begin_inplace_commit

        def _po_dzienniku(*a, **k):
            prawdziwe(*a, **k)
            raise ValueError("wyjątek po dzienniku, przed pierwszym bajtem")
        with monkeypatch.context() as m:
            m.setattr(repo, "begin_inplace_commit", _po_dzienniku)
            writeback.commit(con, "R", now=NOW, inplace=True)      # wyjątek łapie `_pod_blokada` - 'failed'
        assert [tuple(r) for r in con.execute("SELECT kind, phase FROM inplace_op")] == [("commit", "writing")]
        assert p.read_bytes() == przed
    else:                                                # `unverified`, potem ewentualnie odzysk / zwolnienie
        prawdziwa = writeback._verify_inplace

        def _rozjazd(plan, size, probka, backup_text):
            prawdziwa(plan, size, probka, backup_text)
            return writeback.WriteResult("failed", writeback.PowodPozycji("rozjazd odczytu",
                                                                           "inplace_verify_mismatch"),
                                         plan.post_hash, backup_text, in_place=True)
        with monkeypatch.context() as m:
            m.setattr(writeback, "_verify_inplace", _rozjazd)
            writeback.commit(con, "R", now=NOW, inplace=True)
        op_id = con.execute("SELECT id FROM inplace_op WHERE kind = 'commit'").fetchone()[0]
        if stan == "odzyskany":
            writeback.recover_torn(con, op_id, now=NOW)
        elif stan == "zwolniony":
            writeback.release_isolation(con, op_id, now=NOW, reason="test")
    return con, p, przed


@pytest.mark.parametrize("stan, oczek", [
    ("atomowy", (1, 0, 0)), ("niepotwierdzony", (0, 1, 0)), ("zwolniony", (0, 1, 0)),
    ("przed_bajtem", (0, 0, 1)), ("nieweryfikowany", (0, 0, 1)), ("odzyskany", None)])
def test_klasy_backupu_licza_zatwierdzone_do_sprawdzenia_i_otwarte(tmp_path, monkeypatch, stan, oczek):
    """Liczby szuflady z klasy backupu: podmiana potwierdzona → zatwierdzone; podmiana niepotwierdzona
    (atomowa po awarii podmiany - plik nietknięty) i zwolnienie ręką → do sprawdzenia (cofnięcie je
    rozstrzyga); otwarty zapis w miejscu (`writing` przed pierwszym bajtem, `unverified`) → otwarte; po
    odzysku - poza zakresem. Falsyfikatory: niepotwierdzona liczona jako zatwierdzona; otwarty liczony jako
    do sprawdzenia; odzyskany w zakresie."""
    con, p, _przed = _jeden_zapis(tmp_path, stan, monkeypatch)
    zakres = writeback.przebieg_do_cofniecia(con, "R")
    if oczek is None:
        assert zakres is None, zakres
    else:
        assert (zakres.zatwierdzone, zakres.do_sprawdzenia, zakres.otwarte) == oczek, zakres
        assert zakres.cofnij == (oczek[2] == 0)
    con.close()


def _klasy_wprost(con, run_id):
    """Wzorzec równoważności odczytu wsadowego (`writeback._klasy_przebiegu`): klasa każdego backupu zasilaczem
    POJEDYNCZYM reguły klasy (`writeback._klasa_z_bazy` - fakty jednym odczytem na backup, starsze backupy przebiegu
    osobnym odczytem), nie wsadem - drzewo klas jest jedno (`writeback.klasa_backupu`)."""
    return [(cid, int(b["location_id"]), writeback._klasa_z_bazy(con, b)[1])
            for cid in writeback._commity_przebiegu(con, run_id) for b in writeback.backups_for_commit(con, cid)]


def _fakty_wprost(con, run_id):
    """Fakty każdego backupu przebiegu zasilaczem pojedynczym (`writeback._fakty_backupu`) - wzorzec faktów wsadu."""
    return [writeback._fakty_backupu(con, b)
            for cid in writeback._commity_przebiegu(con, run_id) for b in writeback.backups_for_commit(con, cid)]


def _cofniecie_nieweryfikowane(tmp_path, monkeypatch, *, odzysk):
    """Zapis w miejscu, potem cofnięcie w miejscu z rozjazdem odczytu (operacja cofnięcia `unverified`); `odzysk`
    - odzysk tej operacji i drugie cofnięcie (dwie operacje cofnięcia jednego backupu, ostatnia `synced`)."""
    con, (p,) = _baza(tmp_path, 1)
    _makro(con, "R", "EQ6")
    writeback.commit(con, "R", now=NOW, inplace=True)
    prawdziwa = writeback._verify_inplace

    def _rozjazd(plan, size, probka, backup_text):
        prawdziwa(plan, size, probka, backup_text)
        return writeback.WriteResult("failed", writeback.PowodPozycji("rozjazd odczytu", "inplace_verify_mismatch"),
                                     plan.post_hash, backup_text, in_place=True)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_verify_inplace", _rozjazd)
        writeback.undo(con, 1, now=NOW)
    [(op_id, faza)] = con.execute("SELECT id, phase FROM inplace_op WHERE kind = 'undo'").fetchall()
    assert faza == "unverified", faza
    if odzysk:
        writeback.recover_torn(con, op_id, now=NOW)
        assert writeback.undo(con, 1, now=NOW).complete
        assert [r[0] for r in con.execute("SELECT phase FROM inplace_op WHERE kind = 'undo' ORDER BY id")] == [
            "recovered", "synced"]
    return con


_ETAPY_NAKLADKI = ("po_zapisie", "po_cofnieciu_nowszego", "zmiana_po_cofnieciu_nowszego", "po_cofnieciu_przebiegu",
                   "przerwane")


# Kilka śladów cofnięcia atomowego JEDNEGO backupu (`atomic_undo.backup_id` bez UNIQUE, 0044), w kolejności
# zapisu: (wynik z parą lokacji?, wciągnięty?) → klasa backupu z żywych predykatów.
_UKLADY_SLADOW = {
    "starszy_z_para_nowszy_bez": ([(True, True), (False, True)], "zakonczony"),
    "starszy_bez_nowszy_z_para": ([(False, True), (True, True)], "zakonczony"),
    "z_para_niewciagniety_obok_bez_pary": ([(True, False), (False, True)], "zatwierdzony"),
}


def _slady(con, uklad):
    """Dopisuje ślady cofnięcia atomowego układu `uklad` do jedynego backupu bazy (API rdzenia, bez pliku)."""
    [(bid, lid)] = con.execute("SELECT id, location_id FROM header_backups").fetchall()
    sha1, naglowek = con.execute("SELECT file_sha1, header_hash FROM location WHERE id = ?", (lid,)).fetchone()
    for z_para, wciagniety in _UKLADY_SLADOW[uklad][0]:
        uid = repo.record_atomic_undo(con, backup_id=bid, result_sha1=sha1 if z_para else "0" * 40, result_size=1,
                                      result_hash=naglowek if z_para else "1" * 40, byte_exact=True,
                                      source_sha1="2" * 40, source_size=1, displaced_path="k.fits",
                                      prepared_path="t.fits", now=NOW)
        if wciagniety:
            repo.mark_atomic_undo_synced(con, undo_id=uid, now=NOW)


PRZYPADKI_KLAS = ([f"jeden-{s}" for s in ("atomowy", "niepotwierdzony", "zwolniony", "przed_bajtem",
                                           "nieweryfikowany", "odzyskany")]
                  + ["cofniecie-nieweryfikowane", "cofniecie-po-odzysku"]
                  + [f"slady-{u}" for u in _UKLADY_SLADOW]
                  + [f"nakladka-{d}-{e}" for d in ("aa", "am", "ma", "mm") for e in _ETAPY_NAKLADKI])


def _scena_klas(tmp_path, monkeypatch, przypadek):
    """Baza przypadku `przypadek` (`PRZYPADKI_KLAS`) - przebieg `R` na prawdziwym pisarzu; zwraca połączenie."""
    rodzaj, _, reszta = przypadek.partition("-")
    if rodzaj == "jeden":
        return _jeden_zapis(tmp_path, reszta, monkeypatch)[0]
    if rodzaj == "slady":
        con = _jeden_zapis(tmp_path, "atomowy", monkeypatch)[0]
        _slady(con, reszta)
        assert [k for *_x, k in _klasy_wprost(con, "R")] == [_UKLADY_SLADOW[reszta][1]]
        return con
    if rodzaj == "cofniecie":
        return _cofniecie_nieweryfikowane(tmp_path, monkeypatch, odzysk=reszta == "po-odzysku")
    droga, etap = reszta.split("-")
    con, pliki = _nakladka(tmp_path, droga)
    if etap in ("po_cofnieciu_nowszego", "zmiana_po_cofnieciu_nowszego"):
        writeback.undo(con, 2, now=NOW)
    if etap == "zmiana_po_cofnieciu_nowszego":          # plik L0 zmieniony z zewnątrz i przeskanowany
        fits.setval(str(pliki[0]), "OBSERVER", value="obcy")
        scan.ingest_record(con, scan.scan_file(str(pliki[0])), volume="V", now=NOW, summary=scan.ScanSummary(),
                           pochodzenie=repo.ZEWNETRZNE)
    elif etap == "po_cofnieciu_przebiegu":
        writeback.undo_run(con, (1, 2), now=NOW)
    elif etap == "przerwane":
        licz = []
        writeback.undo_run(con, (1, 2), now=NOW, should_cancel=lambda: licz.append(1) or len(licz) > 2)
    return con


@pytest.mark.parametrize("przypadek", PRZYPADKI_KLAS)
def test_klasy_wsadowe_rowne_predykatom_cofniecia(tmp_path, monkeypatch, przypadek):
    """Zasilacz wsadowy reguły klasy (`_fakty_przebiegu`/`_klasy_przebiegu` - cztery zapytania na przebieg, z wierszami
    rodowodu stanu lokacji) daje te same FAKTY (z `stan_rodowodu`) i te same klasy, co zasilacz pojedynczy per backup
    (`_fakty_wprost`, `_klasy_wprost`), w każdej klasie:
    zapis zakończony w sześciu stanach, cofnięcie w miejscu nieweryfikowane i powtórzone po odzysku (dwie operacje
    cofnięcia jednego backupu), kilka śladów cofnięcia atomowego jednego backupu (z parą lokacji i bez, wciągnięte
    i nie), nakładka każdej pary dróg przed cofnięciem, po cofnięciu nowszego (także z plikiem zmienionym potem
    z zewnątrz), po cofnięciu przebiegu i po przerwaniu (łańcuch). Falsyfikatory: pierwsza operacja rodzaju zamiast
    ostatniej; dowód zakończenia bez śladu atomowego; wyłącznie najnowszy ślad atomowy; otwarta operacja cofnięcia
    pominięta; łańcuch bez starszego commitu; klasy faz commitu."""
    con = _scena_klas(tmp_path, monkeypatch, przypadek)
    try:
        wzorzec = _klasy_wprost(con, "R")
        assert wzorzec and writeback._klasy_przebiegu(con, "R") == wzorzec, wzorzec
        assert writeback._fakty_przebiegu(con, "R") == _fakty_wprost(con, "R")
    finally:
        con.close()


class _BarieraOdczytu:
    """Połączenie z barierą: PRZED `n`-tym SELECT-em wykonuje `akcja` (zapis innym połączeniem). Poprzednie
    odczyty są wtedy skonsumowane, więc bariera stoi MIĘDZY zapytaniami."""

    def __init__(self, con, n, akcja):
        self._con, self._n, self._akcja, self._licz = con, n, akcja, 0

    def execute(self, sql, *args):
        if sql.lstrip().upper().startswith("SELECT"):
            self._licz += 1
            if self._licz == self._n:
                self._akcja()
        return self._con.execute(sql, *args)

    def __getattr__(self, nazwa):
        return getattr(self._con, nazwa)


def test_klasy_wsadowe_czytaja_jedna_migawke(tmp_path):
    """Drugie połączenie (inne okno) cofa cały przebieg MIĘDZY odczytem operacji a odczytem śladów atomowych
    (bariera przed trzecim SELECT-em, baza WAL): klasy z migawki sprzed - oba pliki `zatwierdzony` - nie para
    mieszana (plik w miejscu `zatwierdzony` z odczytu sprzed, plik atomowy `zakonczony` ze śladu po), a własna
    transakcja odczytu po wyjściu zamknięta. Falsyfikatory: odczyty bez `BEGIN`; transakcja niezamknięta."""
    con, pliki = _baza(tmp_path, 2)
    f0, f1 = _klatki(con)
    _makro(con, "R", "EQ6", [f0])
    writeback.commit(con, "R", now=NOW, inplace=True)
    _makro(con, "R", "EQ6", [f1])
    writeback.commit(con, "R", now=NOW, inplace=False)
    przed = writeback._klasy_przebiegu(con, "R")
    assert [k for *_x, k in przed] == ["zatwierdzony", "zatwierdzony"], przed
    con2 = db.connect(str(tmp_path / "p.db"))
    try:
        bariera = _BarieraOdczytu(con, 3, lambda: writeback.undo_run(con2, (1, 2), now=NOW))
        assert writeback._klasy_przebiegu(bariera, "R") == przed
        assert not con.in_transaction
        assert [_tel(p) for p in pliki] == ["RC8", "RC8"]
        assert [k for *_x, k in writeback._klasy_przebiegu(con, "R")] == ["zakonczony", "zakonczony"]
    finally:
        con2.close()
        con.close()


def test_klasy_wsadowe_w_transakcji_wolajacego_jej_nie_zamykaja(tmp_path, monkeypatch):
    """Wołający w otwartej transakcji: odczyt idzie w niej, bez własnego `BEGIN` i bez zamykania - transakcja
    wołającego po odczycie dalej otwarta. Falsyfikatory: `BEGIN` w cudzej transakcji (błąd SQLite); zamknięcie
    cudzej transakcji."""
    con = _jeden_zapis(tmp_path, "atomowy", monkeypatch)[0]
    con.execute("BEGIN")
    try:
        assert [k for *_x, k in writeback._klasy_przebiegu(con, "R")] == ["zatwierdzony"]
        assert con.in_transaction
    finally:
        con.rollback()
        con.close()


@pytest.mark.parametrize("stan", ["przed_bajtem", "nieweryfikowany"])
def test_otwarty_zapis_cofniecie_odsyla_do_odzysku(tmp_path, monkeypatch, stan):
    """Plik z otwartym zapisem w miejscu: cofnięcie go nie rozstrzyga - rdzeń mówi `undo_open_op` z drogą
    „najpierw Przywróć nagłówek”, plik zostaje, jak był (przed pierwszym bajtem - bajty sprzed zapisu).
    Kotwica członu szuflady „otwarty zapis - najpierw …”."""
    con, p, przed = _jeden_zapis(tmp_path, stan, monkeypatch)
    po_zapisie = p.read_bytes()
    if stan == "przed_bajtem":
        assert po_zapisie == przed
    wynik = writeback.undo_run(con, (1,), now=NOW)
    assert _kody(wynik.failed) == ["undo_open_op"] and p.read_bytes() == po_zapisie
    con.close()


def test_niepotwierdzona_podmiana_cofniecie_rozstrzyga(tmp_path, monkeypatch):
    """Podmiana niepotwierdzona (plik nietknięty): cofnięcie rozstrzyga ją rekoncyliacją z dyskiem - „nie ma
    czego cofać”, domknięte. Kotwica członu „do sprawdzenia - „Cofnij” je sprawdzi”."""
    con, p, przed = _jeden_zapis(tmp_path, "niepotwierdzony", monkeypatch)
    wynik = writeback.undo_run(con, (1,), now=NOW)
    assert wynik.complete and _kody(wynik.already) == ["undo_not_replaced"] and p.read_bytes() == przed
    con.close()


# ============================================================ zamiar cofnięcia i Porządki


def _dwa_commity_dwa_pliki(tmp_path):
    con, pliki = _baza(tmp_path, 2)
    f0, f1 = _klatki(con)
    _makro(con, "R", "EQ6", [f0])
    writeback.commit(con, "R", now=NOW, inplace=True)
    _makro(con, "R", "EQ6", [f1])
    writeback.commit(con, "R", now=NOW, inplace=True)
    return con, pliki


def test_zamiar_powstaje_przed_pierwszym_plikiem(tmp_path, monkeypatch):
    """Zdarzenie zamiaru (`run.undo_started`, cel `run:R`, zakres w ładunku, `ts` = `now` cofnięcia, aktor
    księgowy `writeback:undo`) jest w bazie także wtedy, gdy pierwszy plik padł wyjątkiem. Falsyfikator:
    zdarzenie po pętli cofnięcia."""
    import json
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    monkeypatch.setattr(writeback, "_cofnij_lokacje",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pierwszy plik padł")))
    with pytest.raises(RuntimeError):
        writeback.undo_run(con, (1, 2), now=NOW)
    zdarzenia = [(r["ts"], r["actor"], r["target"], json.loads(r["payload"])) for r in con.execute(
        "SELECT ts, actor, target, payload FROM event WHERE verb = 'run.undo_started'")]
    assert zdarzenia == [(NOW, "writeback:undo", "run:R", {"commity": [1, 2]})], zdarzenia
    con.close()


def test_porzadki_widza_przerwanie_na_granicy_commitow(tmp_path):
    """Cofnięcie przebiegu przerwane po najnowszym commicie (starszy bez śladu próby): wiersz „Dokończ
    cofnięcie” wskazuje starszy commit. Falsyfikator: predykat bez kandydatów ze zdarzeń zamiaru (`[]`)."""
    con, pliki = _dwa_commity_dwa_pliki(tmp_path)
    licz = []
    writeback.undo_run(con, (1, 2), now=NOW, should_cancel=lambda: licz.append(1) or len(licz) > 1)
    assert [_tel(p) for p in pliki] == ["EQ6", "RC8"]
    assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1)]
    con.close()


def test_wyjatek_w_polowie_zakresu_zostawia_slad_po_ponownym_otwarciu(tmp_path, monkeypatch):
    """Wyjątek na DRUGIM backupie zakresu, po skutecznym cofnięciu pierwszego (najnowszy commit): po ponownym
    otwarciu bazy plik najnowszego commitu ma bajty sprzed przebiegu, plik starszego - bajty po zapisie, zdarzenie
    zamiaru jest w bazie, a wiersz „Dokończ cofnięcie” wskazuje starszy commit. Falsyfikatory: zdarzenie zamiaru
    po pętli; predykat Porządków bez kandydatów z zamiaru."""
    import json
    con, pliki = _baza(tmp_path, 2)
    przed = [p.read_bytes() for p in pliki]
    f0, f1 = _klatki(con)
    _makro(con, "R", "EQ6", [f0])
    writeback.commit(con, "R", now=NOW, inplace=True)
    _makro(con, "R", "EQ6", [f1])
    writeback.commit(con, "R", now=NOW, inplace=True)
    po_zapisie = [p.read_bytes() for p in pliki]
    prawdziwe = writeback._cofnij_lokacje

    def _drugi_pada(con_, cid, b, *, now):
        if cid == 1:
            raise RuntimeError("drugi backup zakresu padł")
        return prawdziwe(con_, cid, b, now=now)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_cofnij_lokacje", _drugi_pada)
        with pytest.raises(RuntimeError):
            writeback.undo_run(con, (1, 2), now=NOW)
    con.close()
    con = db.connect(str(tmp_path / "p.db"))
    try:
        assert [p.read_bytes() for p in pliki] == [po_zapisie[0], przed[1]] and po_zapisie[0] != przed[0]
        zamiar = [(r["target"], json.loads(r["payload"])) for r in con.execute(
            "SELECT target, payload FROM event WHERE verb = 'run.undo_started'")]
        assert zamiar == [("run:R", {"commity": [1, 2]})], zamiar
        assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1)]
    finally:
        con.close()


def test_porzadki_bez_falszywego_wiersza_po_cofnieciu_jednego_commitu(tmp_path):
    """Legalne cofnięcie jednego commitu przebiegu (`header-fix --undo 2`) nie robi z drugiego commitu
    „niedokończonego cofnięcia”. Falsyfikator: kandydaci „commity przebiegu, w którym inny commit ma ślad”."""
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    assert writeback.undo(con, 2, now=NOW).complete
    assert queries.niedokonczone_cofniecia_kart(con) == []
    con.close()


def test_porzadki_czytaja_zamiar_indeksem_po_celu(tmp_path):
    """Odczyt zdarzeń zamiaru w predykacie Porządków idzie indeksem `idx_event_target` (liczony przy każdej
    plakietce; filtr samym czasownikiem przegląda cały dziennik). Falsyfikator: `WHERE verb = …` bez zakresu
    celu."""
    con, _p = _baza(tmp_path, 1)
    wykonane = []
    con.set_trace_callback(wykonane.append)
    queries.niedokonczone_cofniecia_kart(con)
    con.set_trace_callback(None)
    [sql] = [s for s in wykonane if "run.undo_started" in s]
    plan = " ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql))
    assert "USING INDEX idx_event_target" in plan, plan
    con.close()


def test_dom_nie_liczy_zdarzenia_zamiaru(tmp_path):
    """Zdarzenie zamiaru ma aktora spoza `user%`: gest Domu po cofnięciu przebiegu liczy wyłącznie zdarzenia
    re-syncu (bez `run.undo_started`), a cofnięcie przerwane przed pierwszym plikiem nie zostawia gestu
    „1 zmiana” o niczym - ostatnim gestem ręki zostaje zapis. Falsyfikator: aktor `user:local`."""
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    przed = queries.last_hand_gesture(con)
    writeback.undo_run(con, (1, 2), now="2026-10-26T13:00:00+00:00", should_cancel=lambda: True)
    assert queries.last_hand_gesture(con) == przed
    writeback.undo_run(con, (1, 2), now="2026-10-26T14:00:00+00:00")
    gest = queries.last_hand_gesture(con)
    n_resync = con.execute("SELECT count(*) FROM event WHERE ts = ? AND actor = 'user:local'",
                           ("2026-10-26T14:00:00+00:00",)).fetchone()[0]
    assert "run.undo_started" not in gest["verbs"] and gest["n"] == n_resync > 0, gest
    con.close()


# ============================================================ „Ponów nieudane” (AR-347)


def _zajety_jeden(tmp_path, monkeypatch, n=2):
    """Zapis kart, w którym drugi plik jest zajęty (WinError 32 przy blokadzie, po ponowieniach) - wpis
    `failed` prozą bez kodu, plik nietknięty."""
    con, pliki = _baza(tmp_path, n)
    _makro(con, "R", "EQ6")
    prawdziwa = writeback._exclusive
    monkeypatch.setattr(writeback, "_LOCK_RETRY_DELAYS", (0,))

    def _blokada(path):
        if os.path.basename(path) == pliki[1].name:
            raise writeback._blad_windows(32, path)
        return prawdziwa(path)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_exclusive", _blokada)
        wynik = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(wynik.failed) == 1 and "WinError 32" in str(wynik.failed[0].reason), wynik.failed
    return con, pliki


def test_ponowienie_bierze_zajety_plik_i_zasania_go_po_zapisie(tmp_path, monkeypatch):
    """Wpis nieudany przez zajęty plik (bez kodu powodu) jest do ponowienia; ponowienie zakłada wpis `pending`
    w TYM SAMYM przebiegu z kotwicą stagingu i bez zdarzenia - drugie ponowienie przed zapisem nie ma już czego
    brać (nowszy wpis zasłania nieudany) - zapis go zapisuje, a potem też nie ma czego ponawiać. Falsyfikator:
    predykat bez warunku „nowszy wpis tej pary” (drugi klik przed zapisem dubluje wpis `pending`)."""
    con, pliki = _zajety_jeden(tmp_path, monkeypatch)
    [r] = repo.nieudane_do_ponowienia(con, run_id="R", klinga="karty")
    zdarzen = con.execute("SELECT count(*) FROM event").fetchone()[0]
    assert repo.ponow_nieudane(con, run_id="R", klinga="karty") == 1
    assert repo.ponow_nieudane(con, run_id="R", klinga="karty") == 0
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == zdarzen
    [czeka] = [w for w in writeback.pending_for_run(con, "R") if w["status"] == "pending"]
    assert (czeka["location_id"], czeka["expected_header_hash"]) == (r["location_id"], r["expected_header_hash"])
    writeback.commit(con, "R", now=NOW, inplace=True)
    assert [_tel(p) for p in pliki] == ["EQ6", "EQ6"]
    assert repo.nieudane_do_ponowienia(con, run_id="R", klinga="karty") == []
    con.close()


def test_ponowienie_pomija_plik_dotkniety_i_wstrzymany(tmp_path, monkeypatch):
    """Wpis `failed` po zapisie pliku (re-sync padł - backup jest) i wpis związany z zapisem wstrzymanym nie
    są do ponowienia. Falsyfikatory: predykat bez warunku backupu; bez warunku `withheld_id`."""
    con, pliki = _baza(tmp_path, 2)
    _makro(con, "R", "EQ6")
    prawdziwy = writeback._resync

    def _resync(con_, path, volume, **kw):
        if os.path.basename(path) == pliki[0].name:
            raise OSError("czkawka udziału przy re-syncu")
        return prawdziwy(con_, path, volume, **kw)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_resync", _resync)
        writeback.commit(con, "R", now=NOW, inplace=False)
    assert _kody([writeback.FileResult(0, "", "failed", writeback._powod_wiersza(w))
                  for w in writeback.pending_for_run(con, "R") if w["status"] == "failed"]) == ["backup_saved_in"]
    assert repo.nieudane_do_ponowienia(con, run_id="R", klinga="karty") == []
    con.execute("PRAGMA foreign_keys = OFF")              # atrapa wiązania wstrzymania - liczy się sam znacznik
    with con:
        lid = con.execute("SELECT id FROM location WHERE path = ?", (str(pliki[1]),)).fetchone()[0]
        con.execute("INSERT INTO pending_changes(run_id, location_id, keyword, op, status, withheld_id) "
                    "VALUES ('S', ?, 'TELESCOP', 'set', 'failed', 999)", (lid,))
    con.execute("PRAGMA foreign_keys = ON")
    assert repo.nieudane_do_ponowienia(con, run_id="S", klinga="karty") == []
    con.close()


def test_ponowienie_nazw_tylko_plik_pod_stara_nazwa_bez_zamiaru(tmp_path):
    """Nazwy: wiersz `failed` z plikiem pod starą nazwą i bez zamiaru jest do ponowienia; ten sam wiersz,
    gdy baza widzi plik pod nową nazwą (rozdarcie) albo zamiar jest otwarty - nie; ponowiony raz zasłania go
    nowszy wiersz. Falsyfikatory: predykat bez `l.path = old_path`; bez `in_flight IS NULL`; bez warunku
    „nowszy wiersz tej lokacji” (drugie ponowienie dubluje wiersz)."""
    con, (p,) = _baza(tmp_path, 1)
    lid = con.execute("SELECT id FROM location").fetchone()[0]
    rid = repo.stage_rename(con, run_id="N", location_id=lid, old_path=str(p),
                            new_path=str(p.with_name("nowa.fits")), expected_mtime=None)
    repo.set_rename_status(con, rename_id=rid, status="failed", reason="plik zajęty")
    assert [r["id"] for r in repo.nieudane_do_ponowienia(con, run_id="N", klinga="nazwy")] == [rid]
    with con:
        con.execute("UPDATE pending_renames SET in_flight = 'commit' WHERE id = ?", (rid,))
    assert repo.nieudane_do_ponowienia(con, run_id="N", klinga="nazwy") == []
    with con:
        con.execute("UPDATE pending_renames SET in_flight = NULL WHERE id = ?", (rid,))
        con.execute("UPDATE location SET path = ? WHERE id = ?", (str(p.with_name("nowa.fits")), lid))
    assert repo.nieudane_do_ponowienia(con, run_id="N", klinga="nazwy") == []
    with con:
        con.execute("UPDATE location SET path = ? WHERE id = ?", (str(p), lid))
    assert repo.ponow_nieudane(con, run_id="N", klinga="nazwy") == 1
    assert repo.ponow_nieudane(con, run_id="N", klinga="nazwy") == 0
    con.close()
