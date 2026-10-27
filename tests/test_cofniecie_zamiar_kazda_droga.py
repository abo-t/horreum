"""AR-360: zamiar cofnięcia z KAŻDEJ drogi (jedno ciało `writeback._cofnij_zakres` dla `undo` i `undo_run`), znacznik
domknięcia `run.undo_finished` po cofnięciu domkniętym, warunek konieczny `_czeka_na_dokonczenie` w odczycie zbiorczym
wiersza Porządków „Dokończ cofnięcie” (`gui.queries.niedokonczone_cofniecia_kart`) i jedna migawka tego odczytu,
`header-fix --undo 1,2` przez rdzeń przebiegu oraz kontrakt publicznego `undo` dla commitu spoza bazy.

Stany do parytetu wyniku z warunkiem i bez - z PRAWDZIWYCH `writeback.undo`/`undo_run` na plikach FITS w `tmp_path`
(prawdziwe ślady `inplace_op`/`atomic_undo`), bez atrapy rdzenia."""
from __future__ import annotations

import json

import pytest

from horreum import cli, db, repo, scan, writeback
from horreum.gui import queries

from test_writeback_cofniecie_przebiegu import (NOW, _BarieraOdczytu, _baza, _dwa_commity_dwa_pliki, _klatki,
                                                _makro, _tel)

_WARUNEK = "l.header_hash IS hb.post_hash"          # zapytanie warunku koniecznego w `niedokonczone_cofniecia_kart`


class _Wynik(list):
    def fetchall(self):
        return list(self)


class _Podgladacz:
    """Połączenie, które zapamiętuje zbiór zamiarów (wiersze zapytania `run.undo_started`) i kandydatów (parametr
    zapytania warunku koniecznego) - wejście odniesienia parytetu."""

    def __init__(self, con):
        self._con, self.zamiar, self.kandydaci = con, None, None

    def execute(self, sql, *args):
        if "run.undo_started" in sql:
            wiersze = _Wynik(self._con.execute(sql, *args).fetchall())
            self.zamiar = {int(r[0]) for r in wiersze}
            return wiersze
        if _WARUNEK in sql:
            self.kandydaci = json.loads(args[0][0])
        return self._con.execute(sql, *args)

    def __getattr__(self, nazwa):
        return getattr(self._con, nazwa)


def _odniesienie(con):
    """`niedokonczone_cofniecia_kart` BEZ warunku koniecznego i BEZ rozstrzygania per lokacja: pętla po wszystkich
    backupach wszystkich kandydatów (te same zbiory zamiarów i kandydatów) regułami rdzenia - kształt sprzed AR-360."""
    podglad = _Podgladacz(con)
    queries.niedokonczone_cofniecia_kart(podglad)
    wynik = []
    for commit_id in podglad.kandydaci:
        backupy = writeback.backups_for_commit(con, commit_id)
        if commit_id not in podglad.zamiar and not any(
                writeback._slad_proby_cofniecia(con, commit_id, b) for b in backupy):
            continue
        n = sum(1 for b in backupy if writeback._czeka_na_dokonczenie(con, commit_id, b))
        if n:
            wynik.append((commit_id, n))
    return wynik


def _zdarzenia(con, verb):
    return [(r["ts"], r["actor"], r["target"], json.loads(r["payload"])) for r in con.execute(
        "SELECT ts, actor, target, payload FROM event WHERE verb = ? ORDER BY id", (verb,))]


def _po(n):
    """`should_cancel`, które przerywa przed backupem numer `n` (0 = przed pierwszym)."""
    licz = []
    return lambda: licz.append(1) or len(licz) > n


def _jeden_commit(tmp_path, n=2, *, inplace=True):
    con, pliki = _baza(tmp_path, n)
    _makro(con, "R", "EQ6")
    assert writeback.commit(con, "R", now=NOW, inplace=inplace).commit_id == 1
    return con, pliki


# ============================================================ zamiar i znacznik z każdej drogi


def test_pojedyncze_undo_przerwane_przed_pierwszym_plikiem_ma_wiersz(tmp_path):
    """`writeback.undo` jednego commitu (pasek, okna kart, CLI) przerwane przed pierwszym plikiem: zamiar w dzienniku,
    wiersz „Dokończ cofnięcie” ze wszystkimi plikami. Dawniej zamiar stawiał wyłącznie `undo_run` (szuflada) - wiersza
    nie było. Falsyfikator: `undo` bez wspólnego ciała (zamiaru)."""
    con, pliki = _jeden_commit(tmp_path)
    u = writeback.undo(con, 1, now=NOW, should_cancel=lambda: True)
    assert u.cancelled and u.commit_id == 1 and [_tel(p) for p in pliki] == ["EQ6", "EQ6"], u
    assert _zdarzenia(con, "run.undo_started") == [(NOW, "writeback:undo", "run:R", {"commity": [1]})]
    assert queries.niedokonczone_cofniecia_kart(con) == [(1, 2)]
    con.close()


def test_znacznik_domkniecia_tylko_przy_complete(tmp_path, monkeypatch):
    """Znacznik `run.undo_finished` (zakres, aktor księgowy, `ts` = `now`) wyłącznie po cofnięciu domkniętym: nie po
    przerwaniu, nie po porażce pliku (wyjątek drugiego pliku), nie po blokadzie `undo_newer_write`. Falsyfikator:
    znacznik bezwarunkowy po pętli."""
    con, pliki = _jeden_commit(tmp_path)
    writeback.undo(con, 1, now="2026-10-26T13:00:00+00:00", should_cancel=_po(1))
    assert _zdarzenia(con, "run.undo_finished") == []
    prawdziwe = writeback._cofnij_lokacje

    def _drugi_pada(con_, cid, b, *, now):
        if b["location_id"] == 2:
            raise RuntimeError("drugi plik padł")
        return prawdziwe(con_, cid, b, now=now)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_cofnij_lokacje", _drugi_pada)
        with pytest.raises(RuntimeError):
            writeback.undo(con, 1, now="2026-10-26T13:30:00+00:00")
    assert _zdarzenia(con, "run.undo_finished") == []
    u = writeback.undo(con, 1, now="2026-10-26T14:00:00+00:00")
    assert u.complete and [_tel(p) for p in pliki] == ["RC8", "RC8"], u
    assert _zdarzenia(con, "run.undo_finished") == [
        ("2026-10-26T14:00:00+00:00", "writeback:undo", "run:R", {"commity": [1]})]
    con.close()


def test_blokada_nowszego_zapisu_bez_znacznika(tmp_path):
    """Cofnięcie starszego commitu, którego lokację nadpisał nowszy żywy zapis, nie jest domknięte - zamiar bez
    znacznika. Falsyfikator: znacznik przy `undo_newer_write`."""
    con, pliki = _baza(tmp_path, 1)
    _makro(con, "R", "EQ6")
    writeback.commit(con, "R", now=NOW, inplace=True)
    _makro(con, "S", "EQ8")
    writeback.commit(con, "S", now=NOW, inplace=True)
    u = writeback.undo(con, 1, now=NOW)
    assert not u.complete and [fr.reason.code for fr in u.blocked] == ["undo_newer_write"], u
    assert len(_zdarzenia(con, "run.undo_started")) == 1 and _zdarzenia(con, "run.undo_finished") == []
    con.close()


def test_zamiar_po_znaczniku_znow_sie_liczy(tmp_path):
    """Odczyt zamiaru: znacznik zdejmuje WYŁĄCZNIE commity ze swojego zakresu i wyłącznie zamiary sprzed siebie -
    zamiar późniejszy znów jest kandydatem. Klingi wprost (zamiar przerwany przed pierwszym plikiem nie zostawia
    śladu per plik), pliki nietknięte. Falsyfikatory: znacznik po samym celu (zdejmuje oba commity); znacznik bez
    warunku kolejności (`f.id > e.id`)."""
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    repo.zamiar_cofniecia_przebiegu(con, run_id="R", commity=(1, 2), now=NOW)
    assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1), (2, 1)]
    repo.domkniecie_cofniecia_przebiegu(con, run_id="R", commity=(2,), now=NOW)
    assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1)]
    repo.domkniecie_cofniecia_przebiegu(con, run_id="R", commity=(1,), now=NOW)
    assert queries.niedokonczone_cofniecia_kart(con) == []
    repo.zamiar_cofniecia_przebiegu(con, run_id="R", commity=(1,), now=NOW)
    assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1)]
    con.close()


def test_przebieg_cofniety_przez_undo_run_zakres_bez_zmian(tmp_path):
    """Szew szuflady (C): przebieg cofnięty `undo_run` - `przebieg_do_cofniecia` mówi „nie ma czego cofać” z trwałych
    śladów, jak przed znacznikiem (znacznik nie jest klasą cofnięcia). Falsyfikator: zakres liczony ze znacznika."""
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    przed = writeback.przebieg_do_cofniecia(con, "R")
    assert przed is not None and przed.commity == (1, 2), przed
    assert writeback.undo_run(con, (1, 2), now=NOW).complete
    assert writeback.przebieg_do_cofniecia(con, "R") is None
    assert writeback.zakresy_cofniecia(con, "R", (1, 2)) == (None, None)
    con.close()


# ============================================================ warunek konieczny przed pętlą - parytet i koszt


def _pelne_w_miejscu(tmp_path, monkeypatch):
    con, _p = _jeden_commit(tmp_path, inplace=True)
    assert writeback.undo(con, 1, now=NOW).complete
    return con, []


def _pelne_atomowo(tmp_path, monkeypatch):
    con, _p = _jeden_commit(tmp_path, inplace=False)
    assert writeback.undo(con, 1, now=NOW).complete
    return con, []


def _przerwane(tmp_path, monkeypatch):
    con, _p = _jeden_commit(tmp_path, n=3)
    writeback.undo(con, 1, now=NOW, should_cancel=_po(1))
    return con, [(1, 2)]


def _wyjatek(tmp_path, monkeypatch):
    con, _p = _jeden_commit(tmp_path, n=3)
    prawdziwe = writeback._cofnij_lokacje

    def _drugi_pada(con_, cid, b, *, now):
        if b["location_id"] == 2:
            raise RuntimeError("drugi plik padł")
        return prawdziwe(con_, cid, b, now=now)
    with monkeypatch.context() as m:
        m.setattr(writeback, "_cofnij_lokacje", _drugi_pada)
        with pytest.raises(RuntimeError):
            writeback.undo(con, 1, now=NOW)
    return con, [(1, 2)]


def _plik_wrocil(tmp_path, monkeypatch):
    """Cofnięcie atomowe domknięte, potem plik wraca do bajtów po zapisie spoza Horreum i skan to wciąga."""
    con, pliki = _jeden_commit(tmp_path, n=1, inplace=False)
    po_zapisie = pliki[0].read_bytes()
    assert writeback.undo(con, 1, now=NOW).complete
    pliki[0].write_bytes(po_zapisie)
    scan.ingest_record(con, scan.scan_file(str(pliki[0])), volume="V", now=NOW, summary=scan.ScanSummary())
    return con, [(1, 1)]


def _plik_wrocil_w_miejscu(tmp_path, monkeypatch):
    """Cofnięcie w miejscu domknięte (`undo` w `synced` - dowód zakończenia), potem plik wraca do stanu po zapisie."""
    con, pliki = _jeden_commit(tmp_path, n=1, inplace=True)
    po_zapisie = pliki[0].read_bytes()
    assert writeback.undo(con, 1, now=NOW).complete
    pliki[0].write_bytes(po_zapisie)
    scan.ingest_record(con, scan.scan_file(str(pliki[0])), volume="V", now=NOW, summary=scan.ScanSummary())
    return con, []


def _zmiana_obiektu(tmp_path, monkeypatch):
    con, _p = _jeden_commit(tmp_path, n=3)
    con.execute("INSERT INTO object_change_run (run_id, mode, created_at, status) VALUES ('R', 'align', ?, "
                "'applied')", (NOW,))
    con.commit()
    writeback.undo(con, 1, now=NOW, should_cancel=_po(1))
    return con, []


def _granica_przebiegu(tmp_path, monkeypatch):
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    writeback.undo_run(con, (1, 2), now=NOW, should_cancel=_po(1))
    return con, [(1, 1)]


def _nowszy_zapis(tmp_path, monkeypatch):
    con, pliki = _jeden_commit(tmp_path, n=2)
    writeback.undo(con, 1, now=NOW, should_cancel=_po(1))
    f0, f1 = _klatki(con)
    _makro(con, "S", "EQ8", [f1])
    assert writeback.commit(con, "S", now=NOW, inplace=True).applied
    return con, []


def _powtorzony_zapis(tmp_path, monkeypatch):
    """Ta sama karta trzy razy na tych samych plikach (A → B → A; cofnięcia domknięte w miejscu, atomowo, w miejscu),
    czwarty zapis cofany przerwaniem po pierwszym pliku - czeka reszta czwartego, a starsze commity o tym samym odcisku
    nie (nowszy żywy zapis)."""
    con, _p = _baza(tmp_path, 3)
    for i, inplace in enumerate((True, False, True)):
        _makro(con, f"R{i}", "EQ6")
        c = writeback.commit(con, f"R{i}", now=NOW, inplace=inplace)
        assert writeback.undo(con, c.commit_id, now=NOW).complete
    _makro(con, "R3", "EQ6")
    c = writeback.commit(con, "R3", now=NOW, inplace=False)
    writeback.undo(con, c.commit_id, now=NOW, should_cancel=_po(1))
    return con, [(c.commit_id, 2)]


def _nowszy_zakonczony_starszy_zywy(tmp_path, monkeypatch):
    """C1 atomowo i C2 w miejscu - ta sama karta (ten sam odcisk), oba cofnięte; plik wraca spoza Horreum do stanu po
    zapisie: C2 ma dowód zakończenia (`undo` w `synced`), C1 (ślad atomowy z innym wynikiem) nie - czeka C1, choć
    lokacja ma nowszy backup o tym samym odcisku (rozstrzygnięcie per lokacja pomija zakończone)."""
    con, pliki = _baza(tmp_path, 1)
    _makro(con, "R1", "EQ6")
    c1 = writeback.commit(con, "R1", now=NOW, inplace=False)
    po_zapisie = pliki[0].read_bytes()
    assert writeback.undo(con, c1.commit_id, now=NOW).complete
    _makro(con, "R2", "EQ6")
    c2 = writeback.commit(con, "R2", now=NOW, inplace=True)
    assert writeback.undo(con, c2.commit_id, now=NOW).complete
    pliki[0].write_bytes(po_zapisie)
    scan.ingest_record(con, scan.scan_file(str(pliki[0])), volume="V", now=NOW, summary=scan.ScanSummary())
    hasze = [r[0] for r in con.execute("SELECT post_hash FROM header_backups ORDER BY id")]
    assert len(set(hasze)) == 1, hasze
    return con, [(c1.commit_id, 1)]


def _ponowny_zapis_bez_cofniecia(tmp_path, monkeypatch):
    """C1 cofnięty atomowo, C2 pisze TĘ SAMĄ kartę i zostaje - C1 (kandydat ze śladu, odcisk bazy = jego wynik zapisu)
    nie czeka: nowszym żywym zapisem jest C2 spoza kandydatów."""
    con, _p = _baza(tmp_path, 2)
    _makro(con, "R1", "EQ6")
    c1 = writeback.commit(con, "R1", now=NOW, inplace=False)
    assert writeback.undo(con, c1.commit_id, now=NOW).complete
    _makro(con, "R2", "EQ6")
    assert writeback.commit(con, "R2", now=NOW, inplace=True).applied
    return con, []


_STANY = [_pelne_w_miejscu, _pelne_atomowo, _przerwane, _wyjatek, _plik_wrocil, _plik_wrocil_w_miejscu,
          _zmiana_obiektu, _granica_przebiegu, _nowszy_zapis, _powtorzony_zapis, _nowszy_zakonczony_starszy_zywy,
          _ponowny_zapis_bez_cofniecia]


@pytest.mark.parametrize("stan", _STANY, ids=[s.__name__.lstrip("_") for s in _STANY])
def test_odczyt_zbiorczy_nie_zmienia_wyniku(tmp_path, monkeypatch, stan):
    """Parytet: wynik z warunkiem koniecznym i rozstrzyganiem per lokacja = pętla po WSZYSTKICH backupach wszystkich
    kandydatów regułami rdzenia (`_odniesienie`), na stanach z prawdziwych cofnięć: pełne w miejscu i atomowo,
    przerwane, wyjątek w połowie, plik, który wrócił do stanu po zapisie (po cofnięciu atomowym i w miejscu), przebieg
    zmiany obiektu, granica commitów przebiegu, nowszy zapis lokacji, ta sama karta powtarzana (A → B → A), nowszy
    zakończony obok starszego żywego, ponowny zapis bez cofnięcia. Falsyfikatory: warunek, który nie jest konieczny
    (bez `unreplaced_at IS NULL`, `=` zamiast `IS`); rozstrzyganie lokacji bez pomijania zakończonych."""
    con, oczek = stan(tmp_path, monkeypatch)
    try:
        assert _odniesienie(con) == oczek
        assert queries.niedokonczone_cofniecia_kart(con) == oczek
    finally:
        con.close()


@pytest.mark.parametrize("inplace", [True, False], ids=["w_miejscu", "atomowo"])
def test_domkniete_cofniecie_nie_czyta_backupow(tmp_path, monkeypatch, inplace):
    """Cofnięcie domknięte zostawia ślad próby (`inplace_op`/`atomic_undo`), więc commit jest kandydatem - ale rachunek
    Porządków nie czyta już jego backupów ani nie woła predykatów per backup (warunek konieczny odsiewa go jednym
    zapytaniem). Falsyfikator: odczyt bez warunku (każde udane cofnięcie dokłada na zawsze N odczytów)."""
    con, _p = _jeden_commit(tmp_path, inplace=inplace)
    assert writeback.undo(con, 1, now=NOW).complete
    wolania = []
    prawdziwe = writeback.backups_for_commit
    monkeypatch.setattr(writeback, "backups_for_commit", lambda c, cid: wolania.append(cid) or prawdziwe(c, cid))
    czeka = writeback._czeka_na_dokonczenie
    monkeypatch.setattr(writeback, "_czeka_na_dokonczenie",
                        lambda c, cid, b: wolania.append(("czeka", cid)) or czeka(c, cid, b))
    zakonczone = writeback._cofniecie_zakonczone
    monkeypatch.setattr(writeback, "_cofniecie_zakonczone",
                        lambda c, cid, b: wolania.append(("zakonczone", cid)) or zakonczone(c, cid, b))
    assert queries.niedokonczone_cofniecia_kart(con) == []
    assert wolania == [], wolania
    con.close()


def test_powtorzony_zapis_rozstrzyga_lokacje_raz(tmp_path, monkeypatch):
    """Ta sama karta powtarzana na tych samych plikach (A → B → A, każdy zapis cofnięty, ostatni przerwany): wszystkie
    commity mają odcisk bazy = swój wynik zapisu na lokacjach czekających, ale regułę czekania (`_czeka_na_dokonczenie`,
    z przeglądem nowszych zapisów) woła się RAZ na lokację - starsze rozstrzyga najnowszy niezakończony. Falsyfikator:
    pętla po wszystkich backupach (wołań tyle, ile commitów razy plików)."""
    con, oczek = _powtorzony_zapis(tmp_path, monkeypatch)
    wolania = []
    czeka = writeback._czeka_na_dokonczenie
    monkeypatch.setattr(writeback, "_czeka_na_dokonczenie",
                        lambda c, cid, b: wolania.append((cid, b["location_id"])) or czeka(c, cid, b))
    assert queries.niedokonczone_cofniecia_kart(con) == oczek
    assert sorted(wolania) == [(oczek[0][0], 2), (oczek[0][0], 3)], wolania
    con.close()


def test_rachunek_czyta_jedna_migawke(tmp_path):
    """Drugie połączenie domyka cofnięcie MIĘDZY odczytem kandydatów a warunkiem koniecznym (bariera przed trzecim
    SELECT-em): wynik z migawki sprzed - commit 1 dalej czeka - a własna transakcja odczytu po wyjściu zamknięta.
    Falsyfikator: odczyty bez `BEGIN` (warunek widzi plik już cofnięty → `[]`)."""
    con, pliki = _dwa_commity_dwa_pliki(tmp_path)
    writeback.undo_run(con, (1, 2), now=NOW, should_cancel=_po(1))
    assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1)]
    con2 = db.connect(str(tmp_path / "p.db"))
    try:
        bariera = _BarieraOdczytu(con, 3, lambda: writeback.undo(con2, 1, now=NOW))
        assert queries.niedokonczone_cofniecia_kart(bariera) == [(1, 1)]
        assert not con.in_transaction
        assert [_tel(p) for p in pliki] == ["RC8", "RC8"]
        assert queries.niedokonczone_cofniecia_kart(con) == []
    finally:
        con2.close()
        con.close()


def test_rachunek_w_transakcji_wolajacego_jej_nie_zamyka(tmp_path):
    """Rachunek liczników w tle czyta w swojej transakcji `BEGIN`: funkcja idzie w niej, bez własnego `BEGIN` i bez
    zamykania. Falsyfikatory: `BEGIN` w cudzej transakcji (błąd SQLite); zamknięcie cudzej transakcji."""
    con, _p = _dwa_commity_dwa_pliki(tmp_path)
    writeback.undo_run(con, (1, 2), now=NOW, should_cancel=_po(1))
    con.execute("BEGIN")
    try:
        assert queries.niedokonczone_cofniecia_kart(con) == [(1, 1)]
        assert con.in_transaction
    finally:
        con.rollback()
        con.close()


# ============================================================ CLI `header-fix --undo` przez rdzeń przebiegu


def _cli(capsys, *argv):
    kod = cli.main(list(argv))
    return kod, capsys.readouterr().out


@pytest.mark.parametrize("zapis", ["1,2", "1, 2", "2,1"])
def test_cli_undo_lista_cofa_caly_przebieg(tmp_path, capsys, zapis):
    """`header-fix --undo 1,2` (zapis z kotwicy szuflady, ze spacją i w dowolnej kolejności) cofa CAŁY przebieg
    prawdziwym rdzeniem: kod 0, bajty obu plików sprzed przebiegu, jeden zamiar `[1, 2]` i jeden znacznik. Dawniej
    `type=int` odmawiał listy (kod 2). Falsyfikator: lista cofana po kolei od najstarszego (`undo_newer_write`)."""
    con, pliki = _baza(tmp_path, 2)
    przed = [p.read_bytes() for p in pliki]
    f0, f1 = _klatki(con)
    _makro(con, "R", "EQ6", [f0])
    writeback.commit(con, "R", now=NOW, inplace=True)
    _makro(con, "R", "EQ6", [f1])
    writeback.commit(con, "R", now=NOW, inplace=True)
    con.close()
    kod, out = _cli(capsys, "header-fix", str(tmp_path / "p.db"), "--undo", zapis)
    assert kod == 0 and "(UNDO commity 1, 2): przywrocone 2" in out, out
    assert [p.read_bytes() for p in pliki] == przed
    con = db.connect(str(tmp_path / "p.db"))
    try:
        assert [z[3] for z in _zdarzenia(con, "run.undo_started")] == [{"commity": [1, 2]}]
        assert [z[3] for z in _zdarzenia(con, "run.undo_finished")] == [{"commity": [1, 2]}]
    finally:
        con.close()


@pytest.mark.parametrize("zapis", ["2,3", "99"])
def test_cli_undo_odmawia_dwoch_przebiegow_i_nieznanego_commitu(tmp_path, capsys, zapis):
    """Zakres z dwóch przebiegów i commit spoza bazy: odmowa z kodem 2 PRZED jakimkolwiek zapisem - pliki bez zmian,
    zero zamiarów. Falsyfikator: walidacja po zamiarze albo po pierwszym pliku."""
    con, pliki = _dwa_commity_dwa_pliki(tmp_path)
    _makro(con, "S", "EQ8", [_klatki(con)[1]])
    assert writeback.commit(con, "S", now=NOW, inplace=True).commit_id == 3
    con.close()
    bajty = [p.read_bytes() for p in pliki]
    kod, out = _cli(capsys, "header-fix", str(tmp_path / "p.db"), "--undo", zapis)
    assert kod == 2 and ": odmowa - " in out, out
    assert [p.read_bytes() for p in pliki] == bajty
    con = db.connect(str(tmp_path / "p.db"))
    try:
        assert _zdarzenia(con, "run.undo_started") == []
    finally:
        con.close()


def test_cli_undo_zly_zapis_listy_blad_parsera(tmp_path, capsys):
    """`--undo 1,x` - błąd parsera (kod 2) zanim cokolwiek otworzy bazę."""
    with pytest.raises(SystemExit) as info:
        cli.main(["header-fix", str(tmp_path / "brak.db"), "--undo", "1,x"])
    assert info.value.code == 2 and not (tmp_path / "brak.db").exists()


def test_cli_undo_jednego_commitu_zostawia_zamiar_i_znacznik(tmp_path, capsys):
    """`header-fix --undo N` jednego commitu idzie tą samą drogą: zamiar i znacznik w dzienniku, nagłówek wiersza
    „UNDO commit N”. Falsyfikator: CLI omija wspólne ciało."""
    con, pliki = _jeden_commit(tmp_path)
    con.close()
    kod, out = _cli(capsys, "header-fix", str(tmp_path / "p.db"), "--undo", "1")
    assert kod == 0 and "(UNDO commit 1): przywrocone 2" in out, out
    assert [_tel(p) for p in pliki] == ["RC8", "RC8"]
    con = db.connect(str(tmp_path / "p.db"))
    try:
        assert [z[3] for z in _zdarzenia(con, "run.undo_started")] == [{"commity": [1]}]
        assert [z[3] for z in _zdarzenia(con, "run.undo_finished")] == [{"commity": [1]}]
    finally:
        con.close()


# ============================================================ kontrakt `undo` dla commitu spoza bazy


def test_undo_commitu_spoza_bazy_pusty_wynik_domkniety_bez_zdarzen(tmp_path):
    """Publiczne `writeback.undo` commitu, którego w bazie nie ma: pusty wynik domknięty, zero zdarzeń (kontrakt sprzed
    zamiaru) - nie `ValueError` walidacji zakresu przebiegu. Falsyfikator: `undo` wprost na `_cofnij_zakres`."""
    con, _p = _jeden_commit(tmp_path)
    zdarzen = con.execute("SELECT count(*) FROM event").fetchone()[0]
    u = writeback.undo(con, 99, now=NOW)
    assert u.complete and u.commit_id == 99 and (u.restored, u.blocked, u.failed) == ([], [], []), u
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == zdarzen
    con.close()


def test_wykonawca_GUI_undo_commitu_spoza_bazy_konczy_bez_bledu(tmp_path):
    """Wykonawca okien i paska (`WritebackRunner`, operacja `undo`) dla commitu spoza bazy: `done` z wynikiem
    domkniętym, bez `failed` (błąd programu w oknie). Falsyfikator: `ValueError` z walidacji zakresu."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from horreum.gui.wb_worker import WritebackRunner
    QApplication.instance() or QApplication([])
    con, _p = _jeden_commit(tmp_path)
    con.close()
    runner = WritebackRunner(str(tmp_path / "p.db"), now_fn=lambda: NOW)
    runner.async_ok = False
    wyniki, bledy = [], []
    assert runner.start("undo", 99, on_progress=lambda *a: None, on_done=lambda op, res: wyniki.append(res),
                        on_failed=lambda op, zdanie, podpowiedz: bledy.append(zdanie))
    assert bledy == [] and len(wyniki) == 1 and wyniki[0].complete and wyniki[0].restored == [], (wyniki, bledy)
