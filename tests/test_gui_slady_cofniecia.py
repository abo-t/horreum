"""AR-231: przegląd śladów cofnięcia bez werdyktu przy montażu Porządków (`TasksView`). Wątek tła
(`_przeglad_watek`) i timer odczytu (`_przeglad_timer`) startują wyłącznie przy śladach bez werdyktu;
zamknięcie okna i zmiana bazy NIE czekają na przegląd zawieszony na `stat`; resztka martwej próby trafia
do wiersza „Kopie zostawione do oka” bez dotyku lokacji; porażka przeglądu stoi w wierszu pasywnym
z ponowieniem, a przycisk ponowienia gaśnie do wyniku. Rdzeń przeglądu:
`test_writeback_cofniecie_atomowe.py` (blok AR-231).

AR-246, AR-252, AR-260 (blok na końcu): `stat` archiwum robi wyłącznie przegląd tła - jeden na bazę, ponad
limit mówi „trwa”, odczyt „nie wiem” mówi zdaniem z ponowieniem; czytelnik kopii zostawionych do oka czyta
nietrwałą pamięć obecności (`queries.zapamietaj_obecnosc`) bez I/O, a starszy odczyt nie cofa nowszego."""
import ast
import json
import os
import sqlite3
import threading
import time
import types
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from horreum import db, repo, scan, writeback  # noqa: E402
from horreum.gui import i18n, queries  # noqa: E402
from test_writeback_inplace import NOW, _baza_z_plikiem, _fits  # noqa: E402

_WATEK = "horreum-przeglad-sladow"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _baza_ze_sladem(tmp_path, *, z_kopia=True):
    """Baza w pliku (`h.db`) z commitem drogą atomową i śladem cofnięcia bez werdyktu; `z_kopia` - kopia
    wyparta K martwej próby leży obok ścieżki. `(con, nazwy K/Z/T, frame_id)`."""
    p = _fits(tmp_path / "a.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    assert len(writeback.commit(con, "R", now=NOW).applied) == 1
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    s = "a" * 40
    k, t = str(p) + ".0000abcd.horreum-kopia", str(tmp_path / "tmp1.tmp")
    repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                            byte_exact=True, source_sha1=s, source_size=1, displaced_path=k,
                            prepared_path=t, now=NOW)
    if z_kopia:
        with open(k, "wb") as fh:
            fh.write(b"K" * 64)
    return con, writeback._nazwy_sladu(k, t), loc["frame_id"]


def _czekaj(warunek, opis, limit=15.0):
    """Warunek po pętli zdarzeń (`processEvents` + `sleep`) - jeden `processEvents` mierzyłby fikcję."""
    koniec = time.monotonic() + limit
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"nie doczekano: {opis}")
        QApplication.processEvents()
        time.sleep(0.02)


def _widok(con):
    from horreum.gui.tasks import TasksView
    return TasksView(con, now_fn=lambda: NOW)


def _zwolnij(widok, con):
    widok.zatrzymaj_pola()
    widok.close()
    con.close()


def test_montaz_Porzadkow_przeglada_slady_w_tle(qapp, tmp_path):
    """Montaż Porządków przy śladzie bez werdyktu: wątek przeglądu i timer stoją od razu, po wyniku ślad
    ma `kept` (wiersz „Kopie zostawione do oka” bez dotyku lokacji), wiersz porażki schowany, a widok
    zleca rachunek liczników w tle (plakietka). Falsyfikator: start przeglądu zdjęty z `__init__`."""
    con, nazwy, fid = _baza_ze_sladem(tmp_path)
    widok = _widok(con)
    try:
        assert widok._przeglad_watek is not None and widok._przeglad_timer is not None
        assert widok._przeglad_timer.isActive()
        rachunki = []
        widok.refresh_counts = lambda **kw: rachunki.append(kw)
        _czekaj(lambda: widok._przeglad_watek is None, "wynik przeglądu")
        assert queries.kept_copy_frame_ids(con) == {fid}
        assert queries.tasks_state(con)["kept_copy_frames"] == 1
        assert widok.wiersz_sladow.isHidden() and not widok._przeglad_timer.isActive()
        assert rachunki == [{"w_tle": True}], rachunki
    finally:
        _zwolnij(widok, con)


def test_bez_sladow_przeglad_nie_startuje(qapp, tmp_path):
    """Baza bez śladów bez werdyktu (jeden SELECT przy montażu): ani wątku przeglądu, ani timera.
    Falsyfikator: przegląd startowany bezwarunkowo."""
    con, _loc = _baza_z_plikiem(tmp_path, _fits(tmp_path / "a.fits"))
    widok = _widok(con)
    try:
        assert widok._przeglad_watek is None and widok._przeglad_timer is None
    finally:
        _zwolnij(widok, con)


def test_zatrzymanie_przy_zawieszonym_stat_wraca_od_razu(qapp, tmp_path, monkeypatch):
    """Zerwany udział: `scan.path_gone` (prawdziwy szew rdzenia przeglądu) wisi na nazwach śladu.
    Zmiana bazy (`MainWindow._mount_views` → `_clear_views` → `zatrzymaj_pola`) i zamknięcie okna
    wracają bez czekania na przegląd; wątki kończą same po zwolnieniu `stat`.

    PRÓG 3 s: montaż buduje komplet widoków (Dostawa, Zbiory, Porządki, Planer, Dom) na maszynie
    współdzielonej z innymi bateriami - 0,5 s bywałoby fikcyjną czerwienią. Mutant (`join` wątku albo
    `QThread.wait()` w zatrzymaniu) czeka do limitu zawieszenia (20 s) - daleko nad progiem.
    Falsyfikator: zatrzymanie, które czeka na przegląd."""
    from horreum.gui.app import MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    con, nazwy, _fid = _baza_ze_sladem(tmp_path)
    con.close()
    zwolnij, wszedl = threading.Event(), threading.Event()
    prawdziwa = scan.path_gone

    def _wisi(x):
        if x in nazwy:
            wszedl.set()
            zwolnij.wait(20)
        return prawdziwa(x)
    monkeypatch.setattr(scan, "path_gone", _wisi)
    win = MainWindow(str(tmp_path / "h.db"))
    try:
        assert wszedl.wait(10), "przegląd nie doszedł do stat"
        t0 = time.perf_counter()
        win._mount_views()
        zmiana_bazy = time.perf_counter() - t0
        t0 = time.perf_counter()
        win.close()
        zamkniecie = time.perf_counter() - t0
        assert zmiana_bazy < 3.0 and zamkniecie < 3.0, (zmiana_bazy, zamkniecie)
    finally:
        zwolnij.set()
        for t in threading.enumerate():
            if t.name == _WATEK:
                t.join(30)
                assert not t.is_alive(), "wątek przeglądu nie skończył po zwolnieniu stat"


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_przegladu_stan_pasywny_i_ponow(qapp, tmp_path, monkeypatch, lang):
    """Zapis werdyktu pada prawdziwym `SQLITE_BUSY`: wiersz pasywny nad listą mówi zdaniem klasy błędu
    (`db_busy`) w języku UI, szczegół systemu pod kursorem, bez okna; „Ponów sprawdzenie” (prawdziwy klik)
    gaśnie od kliknięcia do wyniku, a udane ponowienie chowa wiersz i stawia `kept`.
    Falsyfikatory: porażka połknięta (wiersz schowany); przycisk aktywny w biegu ponowienia."""
    from test_writeback_cofniecie_atomowe import _prawdziwy_blad_zajetej_bazy
    con, _nazwy, fid = _baza_ze_sladem(tmp_path)
    zajeta = _prawdziwy_blad_zajetej_bazy(tmp_path)
    prawdziwa = repo.settle_atomic_undo

    def _pada(*a, **kw):
        raise zajeta
    monkeypatch.setattr(repo, "settle_atomic_undo", _pada)
    i18n.set_lang(lang)
    widok = _widok(con)
    try:
        widok.show()
        _czekaj(lambda: widok._przeglad_watek is None, "wynik przeglądu")
        assert not widok.wiersz_sladow.isHidden()
        tekst = widok.blad_sladow.text()
        assert tekst.startswith(i18n.t("tasks.traces_failed", msg="")), tekst
        assert i18n.t("objchg.item.db_busy", db_code="SQLITE_BUSY") in tekst, tekst
        assert "database is locked" in widok.blad_sladow.szczegol(), widok.blad_sladow.szczegol()
        assert widok.ponow_slady.isEnabled() and queries.kept_copy_frame_ids(con) == set()
        wolno = threading.Event()

        def _czeka(*a, **kw):
            wolno.wait(10)
            return prawdziwa(*a, **kw)
        monkeypatch.setattr(repo, "settle_atomic_undo", _czeka)
        QTest.mouseClick(widok.ponow_slady, Qt.LeftButton)
        assert not widok.ponow_slady.isEnabled(), "ponowienie w biegu - przycisk zgaszony"
        wolno.set()
        _czekaj(lambda: widok._przeglad_watek is None, "wynik ponowienia")
        assert widok.wiersz_sladow.isHidden() and widok.ponow_slady.isEnabled()
        assert queries.kept_copy_frame_ids(con) == {fid}
    finally:
        i18n.set_lang("pl")
        _zwolnij(widok, con)


@pytest.mark.parametrize("watek", ["baza_wraca", "baza_dalej_zablokowana"])
def test_baza_zablokowana_przy_montazu_nie_wywraca_widoku(qapp, tmp_path, monkeypatch, watek):
    """Zapytanie montażu „czy są ślady” pada prawdziwym `SQLITE_BUSY` (baza zablokowana ponad
    `busy_timeout`): widok się buduje, a „nie wiem, czy są ślady” zleca przegląd, który sam rozstrzyga -
    baza wróciła → `kept`; dalej zablokowana → wiersz pasywny ze zdaniem klasy `db_busy`.
    Falsyfikator: zapytanie montażu bez ochrony → wyjątek z `__init__` (`_mount_views` pada)."""
    from test_writeback_cofniecie_atomowe import _prawdziwy_blad_zajetej_bazy
    con, _nazwy, fid = _baza_ze_sladem(tmp_path)
    zajeta = _prawdziwy_blad_zajetej_bazy(tmp_path)
    prawdziwe = repo.unsettled_atomic_undos
    wolania = []

    def _zablokowana(*a, **kw):
        wolania.append(1)
        if len(wolania) == 1 or watek == "baza_dalej_zablokowana":
            raise zajeta
        return prawdziwe(*a, **kw)
    monkeypatch.setattr(repo, "unsettled_atomic_undos", _zablokowana)
    widok = _widok(con)
    try:
        assert widok._przeglad_watek is not None, "„nie wiem” zleca przegląd"
        _czekaj(lambda: widok._przeglad_watek is None, "wynik przeglądu")
        if watek == "baza_wraca":
            assert widok.wiersz_sladow.isHidden()
            assert queries.kept_copy_frame_ids(con) == {fid}
        else:
            assert not widok.wiersz_sladow.isHidden()
            assert i18n.t("objchg.item.db_busy", db_code="SQLITE_BUSY") in widok.blad_sladow.text()
    finally:
        _zwolnij(widok, con)


def test_blad_programu_w_zapytaniu_montazu_leci_dalej(qapp, tmp_path, monkeypatch):
    """Błąd spoza klas bazy (operacja na zamkniętym połączeniu - `ProgrammingError`) w zapytaniu montażu
    to błąd programu, nie „nie wiem”: leci z `__init__` (EXPECT). Falsyfikator: ochrona łapiąca każdy
    `sqlite3.Error`."""
    import sqlite3
    from horreum.gui.tasks import TasksView
    con, _nazwy, _fid = _baza_ze_sladem(tmp_path)

    def _zamkniete(*a, **kw):
        raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
    monkeypatch.setattr(repo, "unsettled_atomic_undos", _zamkniete)
    try:
        with pytest.raises(sqlite3.ProgrammingError):
            TasksView(con, now_fn=lambda: NOW)
    finally:
        con.close()


# ============================================================ AR-246, AR-252, AR-260: przegląd jako jedyny stat


@pytest.fixture(autouse=True)
def _pamiec_obecnosci_od_zera():
    """Pamięć obecności kopii jest modułowa (przeżywa test) - każdy test zaczyna i kończy od zera."""
    queries.zapomnij_obecnosc()
    yield
    queries.zapomnij_obecnosc()


def _baza_z_kept(katalog, polowa="slad_0045", *, kopia=None):
    """Baza `katalog/h.db` z commitem drogą atomową i werdyktem `kept` jednej połowy wiersza „Kopie
    zostawione do oka” - ślad cofnięcia (0045, trzy nazwy) albo zamiar podmiany commitu (0038, sama K);
    K (domyślnie obok pliku, albo `kopia`) leży na dysku. `(con, K, frame_id)`."""
    from test_writeback_cofniecie_atomowe import _commit, _klatka
    con, p, _zmiana, _cid, _n = _commit(katalog, "fits")
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    k = kopia or str(p) + ".0000abcd.horreum-kopia"
    with open(k, "wb") as fh:
        fh.write(b"K" * 64)
    if polowa == "slad_0045":
        s, t = "a" * 40, str(katalog / "tmp1.tmp")
        u = repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                                    byte_exact=True, source_sha1=s, source_size=1, displaced_path=k,
                                    prepared_path=t, now=NOW)
        repo.settle_atomic_undo(con, undo_id=u, outcome="kept", kept_paths=writeback._nazwy_sladu(k, t),
                                now=NOW)
    else:
        n = con.execute("UPDATE replace_intent SET outcome = 'kept', kept_paths = ? WHERE backup_id = ?",
                        (json.dumps([k]), b)).rowcount
        con.commit()
        assert n == 1, "commit bez zamiaru podmiany"
    return con, k, _klatka(con)


class _Stat:
    """Atrapa `scan.path_gone` na prawdziwym szwie przeglądu: nazwy z `wisza` czekają na `zwolnij` (limit
    20 s - zerwany udział), potem oddają `odpowiedz(nazwa)` (domyślnie prawdziwy odczyt). Każde wołanie
    zapisuje wątek, który pytał."""

    def __init__(self, monkeypatch, wisza=(), odpowiedz=None):
        self.zwolnij, self.wszedl = threading.Event(), threading.Event()
        self.wolania = []
        self.wisza = set(wisza)
        self.odpowiedz = odpowiedz
        self.prawdziwa = scan.path_gone
        monkeypatch.setattr(scan, "path_gone", self)

    def __call__(self, x):
        self.wolania.append((threading.current_thread().name, x))
        if x in self.wisza:
            self.wszedl.set()
            self.zwolnij.wait(20)
        return self.odpowiedz(x) if self.odpowiedz is not None else self.prawdziwa(x)


def _dokoncz(stat):
    """Zwolnij zawieszone odczyty i doczekaj wątków przeglądu (każdy kończy sam po zwolnieniu)."""
    stat.zwolnij.set()
    for t in threading.enumerate():
        if t.name == _WATEK:
            t.join(30)
            assert not t.is_alive(), "wątek przeglądu nie skończył po zwolnieniu stat"


def _wynik(widok, opis="wynik przeglądu"):
    _czekaj(lambda: widok._przeglad_watek is None, opis)


def _czlon_kopii(widok):
    """Człon drugi (liczba) wiersza „Kopie zostawione do oka” na LIŚCIE widoku."""
    from horreum.gui import rows, tasks as tasks_mod
    i = next(i for i, (klucz, _e, _a) in enumerate(tasks_mod._TASKS) if klucz == "kept_copy_frames")
    return widok.tasks.item(i).data(rows.SECONDARY)


def _rachunek(widok, n, opis="rachunek liczników w tle"):
    _czekaj(lambda: widok._liczniki_thread is None and _czlon_kopii(widok) == f"{n}  ›", opis)


def _widoczne(widok):
    """Etykiety wiersza pasywnego, które nie są schowane - a schowana ma być pusta."""
    widoczne = [e for e in (widok.blad_sladow, widok.stan_sladow) if not e.isHidden()]
    assert all(e.text() == "" for e in (widok.blad_sladow, widok.stan_sladow) if e.isHidden())
    return widoczne


def test_montaz_zmiana_bazy_i_zamkniecie_przy_kept_nie_statuja(qapp, tmp_path, monkeypatch):
    """AR-246: kopia zostawiona do oka (werdykt `kept`), a `scan.path_gone` wisi na jej nazwie (zerwany
    udział). Montaż okna, rachunek liczników w tle, zmiana bazy i zamknięcie wracają bez czekania: `stat`
    woła WYŁĄCZNIE wątek przeglądu - ani wątek GUI (rachunek synchroniczny montażu), ani wątek liczników.

    PRÓG 3 s: montaż buduje komplet widoków (Dostawa, Zbiory, Porządki, Planer, Dom) na maszynie
    współdzielonej z innymi bateriami - 0,5 s bywałoby fikcyjną czerwienią; mutant (czytelnik statujący
    dysk) stoi do limitu zawieszenia (20 s), daleko nad progiem. Właściwą asercją jest zbiór wątków, które
    pytały o dysk. Falsyfikator: czytelnik `kept_copy_frame_ids` z `scan.path_gone`."""
    from horreum.gui.app import MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    con, k, _fid = _baza_z_kept(tmp_path)
    con.close()
    stat = _Stat(monkeypatch, {k})
    try:
        t0 = time.perf_counter()
        win = MainWindow(str(tmp_path / "h.db"))
        montaz = time.perf_counter() - t0
        assert stat.wszedl.wait(10), "przegląd nie doszedł do stat"
        tasks = win.tasks_view
        tasks.refresh_counts(w_tle=True)
        _czekaj(lambda: tasks._liczniki_thread is None, "rachunek liczników w tle")
        t0 = time.perf_counter()
        win._mount_views()
        zmiana_bazy = time.perf_counter() - t0
        t0 = time.perf_counter()
        win.close()
        zamkniecie = time.perf_counter() - t0
        assert montaz < 3.0 and zmiana_bazy < 3.0 and zamkniecie < 3.0, (montaz, zmiana_bazy, zamkniecie)
        assert {w for w, _x in stat.wolania} == {_WATEK}, stat.wolania
    finally:
        _dokoncz(stat)


def test_wynik_po_zatrzymaniu_nie_dotyka_widoku(qapp, tmp_path, monkeypatch):
    """AR-246: widok zatrzymany (zmiana bazy, zamknięcie) przy wiszącym przeglądzie - po powrocie udziału
    przegląd kończy sam i jego odczyt trafia do pamięci obecności (fakt o dysku), ale stary widok nie liczy
    liczników i nie zmienia wiersza pasywnego. Falsyfikator: zatrzymanie, które nie puszcza zlecenia."""
    from horreum.gui import tasks as tasks_mod
    con, k, _fid = _baza_z_kept(tmp_path)
    stat = _Stat(monkeypatch, {k}, odpowiedz=lambda x: True)
    widok = _widok(con)
    try:
        assert stat.wszedl.wait(10)
        rachunki, przylozone = [], []
        widok.refresh_counts = lambda **kw: rachunki.append(kw)
        widok._przyloz_liczniki = lambda *a: przylozone.append(a)
        zlecenie = tasks_mod._PRZEGLADY[queries.klucz_bazy(str(tmp_path / "h.db"))]
        widok.zatrzymaj_pola()
        stat.zwolnij.set()
        assert zlecenie.gotowe.wait(10)
        koniec = time.monotonic() + 1.0
        while time.monotonic() < koniec:
            QApplication.processEvents()
            time.sleep(0.02)
        assert rachunki == [] and przylozone == [] and widok.wiersz_sladow.isHidden()
        assert queries.obecnosc_kopii([k]) == {k: True}
    finally:
        _dokoncz(stat)
        _zwolnij(widok, con)


def test_jeden_przeglad_na_baze_i_niezalezne_bazy(qapp, tmp_path, monkeypatch):
    """AR-252: przegląd bazy A wisi na `stat` - trzy montaże A i wejście w Porządki przy wierszu „trwa”
    podpinają się pod JEDEN wątek (ponowienie jest wtedy zgaszone); baza B w tym czasie ma własny przegląd,
    który kończy i przykłada wynik. Falsyfikatory: wątek na każde zlecenie; rejestr bez klucza bazy (B pod
    wiszącym A)."""
    from horreum.gui import tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "_PRZEGLAD_LIMIT_S", 0.2)
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    con_a, k_a, _fid_a = _baza_z_kept(tmp_path / "A")
    con_b, k_b, fid_b = _baza_z_kept(tmp_path / "B")
    przed = {t for t in threading.enumerate() if t.name == _WATEK}
    stat = _Stat(monkeypatch, {k_a})
    widoki = []
    try:
        for _ in range(3):
            if widoki:
                widoki[-1].zatrzymaj_pola()
            widoki.append(_widok(con_a))
        assert stat.wszedl.wait(10)
        widok = widoki[-1]
        widok.show()
        _czekaj(lambda: widok._stan_sladow == "trwa", "wiersz „trwa”")
        assert not widok.ponow_slady.isEnabled()
        widok.odswiez_przy_wejsciu()
        assert widok._przeglad is tasks_mod._PRZEGLADY[queries.klucz_bazy(str(tmp_path / "A" / "h.db"))]
        zywe = {t for t in threading.enumerate() if t.name == _WATEK and t.is_alive()} - przed
        assert len(zywe) == 1, zywe
        widoki.append(_widok(con_b))
        _wynik(widoki[-1], "wynik przeglądu bazy B")
        assert queries.obecnosc_kopii([k_b]) == {k_b: False}
        assert queries.kept_copy_frame_ids(con_b) == {fid_b} and widoki[-1].wiersz_sladow.isHidden()
        assert widok._przeglad_watek is not None and widok._stan_sladow == "trwa"
    finally:
        _dokoncz(stat)
        for w in widoki:
            w.zatrzymaj_pola()
            w.close()
        con_a.close()
        con_b.close()


def test_podpiecie_w_chwili_zakonczenia_wpisu(qapp, tmp_path, monkeypatch):
    """AR-252: (a) widok podpięty pod żywe zlecenie, które kończy się przed jego pierwszym taktem, przykłada
    wynik i zatrzymuje timer; (b) zlecenie już gotowe w chwili kolejnego zlecenia nie jest podpinane - rusza
    nowe (nowy wątek, nowy odczyt dysku). Falsyfikator: podpięcie pod zlecenie gotowe (stary wynik zamiast
    odczytu)."""
    from horreum.gui import tasks as tasks_mod
    con, k, _fid = _baza_z_kept(tmp_path)
    stat = _Stat(monkeypatch, {k})
    pierwszy = _widok(con)
    widoki = [pierwszy]
    try:
        assert stat.wszedl.wait(10)
        klucz = queries.klucz_bazy(str(tmp_path / "h.db"))
        zywe = tasks_mod._PRZEGLADY[klucz]
        pierwszy.zatrzymaj_pola()
        drugi = _widok(con)
        widoki.append(drugi)
        assert drugi._przeglad is zywe, "podpięcie pod żywe zlecenie"
        stat.zwolnij.set()
        assert zywe.gotowe.wait(10)
        _wynik(drugi, "wynik podpiętego zlecenia")
        assert not drugi._przeglad_timer.isActive() and drugi.wiersz_sladow.isHidden()
        wolania = len(stat.wolania)
        drugi._przejrzyj_slady()
        assert tasks_mod._PRZEGLADY[klucz] is not zywe
        assert drugi._przeglad is tasks_mod._PRZEGLADY[klucz]
        _wynik(drugi, "wynik nowego zlecenia")
        assert len(stat.wolania) > wolania, "nowe zlecenie czyta dysk od nowa"
    finally:
        _dokoncz(stat)
        for w in widoki:
            w.zatrzymaj_pola()
            w.close()
        con.close()


def test_zastapienie_gotowego_wpisu_przed_odbiorem(qapp, tmp_path, monkeypatch):
    """AR-252: widok V1 obserwuje zlecenie E1, które skończyło się odczytem „nie wiem”, ale V1 jeszcze go nie
    odebrał (bez pętli zdarzeń); nowe zlecenie (V2) zastępuje gotowe E1 w rejestrze zleceniem E2 (odczyt
    „jest”). Każdy widok przykłada SWÓJ wynik, raz: V1 - „nie wiem”, V2 - wiersz schowany. Falsyfikator:
    widok czyta zlecenie z rejestru zamiast własnego."""
    from horreum.gui import tasks as tasks_mod
    con, k, _fid = _baza_z_kept(tmp_path)
    odczyt = {k: None}
    stat = _Stat(monkeypatch)
    stat.odpowiedz = lambda x: odczyt[x] if x in odczyt else stat.prawdziwa(x)
    klucz = queries.klucz_bazy(str(tmp_path / "h.db"))
    v1 = _widok(con)
    widoki = [v1]
    try:
        e1 = tasks_mod._PRZEGLADY[klucz]
        assert e1.gotowe.wait(10)
        odczyt[k] = False
        v2 = _widok(con)
        widoki.append(v2)
        e2 = tasks_mod._PRZEGLADY[klucz]
        assert e2 is not e1 and v1._przeglad is e1 and v2._przeglad is e2
        assert e2.gotowe.wait(10)
        _czekaj(lambda: v1._przeglad_watek is None and v2._przeglad_watek is None, "oba wyniki")
        assert v1._stan_sladow == "nie_wiem" and v1.stan_sladow.szczegol() == k
        assert v2._stan_sladow == "schowany" and v2.wiersz_sladow.isHidden()
    finally:
        _dokoncz(stat)
        for w in widoki:
            w.zatrzymaj_pola()
            w.close()
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_przeglad_ponad_limit_mowi_trwa(qapp, tmp_path, monkeypatch, lang):
    """AR-252: przegląd dłuższy niż próg (`_PRZEGLAD_LIMIT_S`, tu 0,2 s) mówi w wierszu pasywnym „trwa” -
    zdanie `tasks.traces_pending` w języku UI, rola `warn`, etykieta porażki schowana i pusta, ponowienie
    zgaszone (prawdziwy klik nie zakłada wątku); powrót udziału z odczytem „jest” chowa wiersz i zapala
    ponowienie. Falsyfikator: brak gałęzi limitu - wiszący przegląd z zewnątrz wygląda jak „brak śladów”."""
    from horreum.gui import tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "_PRZEGLAD_LIMIT_S", 0.2)
    con, k, _fid = _baza_z_kept(tmp_path)
    stat = _Stat(monkeypatch, {k})
    i18n.set_lang(lang)
    widok = _widok(con)
    try:
        widok.show()
        _czekaj(lambda: widok._stan_sladow == "trwa", "wiersz „trwa”")
        assert not widok.wiersz_sladow.isHidden() and _widoczne(widok) == [widok.stan_sladow]
        assert widok.stan_sladow.text() == i18n.t("tasks.traces_pending")
        assert widok.stan_sladow.property("role") == "warn" and not widok.ponow_slady.isEnabled()
        przed = [t for t in threading.enumerate() if t.name == _WATEK]
        QTest.mouseClick(widok.ponow_slady, Qt.LeftButton)
        assert [t for t in threading.enumerate() if t.name == _WATEK] == przed
        stat.zwolnij.set()
        _wynik(widok)
        assert widok.wiersz_sladow.isHidden() and widok.ponow_slady.isEnabled() and _widoczne(widok) == []
    finally:
        i18n.set_lang("pl")
        _dokoncz(stat)
        _zwolnij(widok, con)


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("zrodlo", ["kopia", "slad"])
def test_przeglad_konczy_sie_nie_wiem(qapp, tmp_path, monkeypatch, zrodlo, lang):
    """AR-252: zawieszony `stat` wraca bez rozstrzygnięcia (`None` - brak dostępu, udział nie odpowiada) dla
    kopii zostawionej do oka albo dla śladu bez werdyktu. Wiersz pasywny NIE chowa się: zdanie
    `tasks.traces_unknown` (rola `warn`), pod kursorem nazwy z odczytem „nie wiem” (kopii albo śladu), ponowienie
    aktywne; prawdziwy klik po powrocie udziału rozstrzyga i chowa wiersz. Falsyfikatory: „nie wiem” liczone jak
    przegląd kompletny; szczegół bez nazw śladu."""
    if zrodlo == "kopia":
        con, k, _fid = _baza_z_kept(tmp_path)
        wisza, szczegol = {k}, k
    else:
        con, nazwy, _fid = _baza_ze_sladem(tmp_path)
        wisza, szczegol = set(nazwy), "\n".join(nazwy)
    stat = _Stat(monkeypatch, wisza)
    stat.odpowiedz = lambda x: None if x in wisza else stat.prawdziwa(x)
    i18n.set_lang(lang)
    widok = _widok(con)
    try:
        widok.show()
        assert stat.wszedl.wait(10)
        stat.zwolnij.set()
        _wynik(widok)
        assert widok._stan_sladow == "nie_wiem" and _widoczne(widok) == [widok.stan_sladow]
        assert widok.stan_sladow.text() == i18n.t("tasks.traces_unknown")
        assert widok.stan_sladow.szczegol() == szczegol
        assert widok.ponow_slady.isEnabled()
        stat.odpowiedz = None                      # udział wrócił - prawdziwy odczyt (K jest na dysku)
        QTest.mouseClick(widok.ponow_slady, Qt.LeftButton)
        _wynik(widok, "wynik ponowienia")
        assert widok._stan_sladow == "schowany" and widok.wiersz_sladow.isHidden()
    finally:
        i18n.set_lang("pl")
        _dokoncz(stat)
        _zwolnij(widok, con)


def test_trzy_braki_bez_werdyktu_chowaja_wiersz(qapp, tmp_path, monkeypatch):
    """Wybór (AR-247 - obserwator i przegląd piszą wyłącznie `kept`): ślad bez werdyktu, którego trzy nazwy
    mają dowiedziony brak, wiersza pasywnego NIE zapala - obok ścieżki nic nie ma (człowiek nie ma czego
    porównać ani usunąć), a `clean` pisze wyłącznie właściciel śladu, więc ostrzeżenie świeciłoby na zawsze
    bez gestu, który je gasi. Ślad zostaje bez werdyktu do wariantu rozwojowego AR-247. Droga: „trwa” →
    trzy „nie ma” → wiersz schowany, ZERO zapisu `clean`. Falsyfikatory: trzy braki liczone jak „nie wiem”
    (wiersz świeci); przegląd zapisujący `clean`."""
    from horreum.gui import tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "_PRZEGLAD_LIMIT_S", 0.2)
    con, nazwy, _fid = _baza_ze_sladem(tmp_path, z_kopia=False)
    stat = _Stat(monkeypatch, set(nazwy))
    widok = _widok(con)
    try:
        _czekaj(lambda: widok._stan_sladow == "trwa", "wiersz „trwa”")
        stat.zwolnij.set()
        _wynik(widok)
        assert widok._stan_sladow == "schowany" and widok.wiersz_sladow.isHidden()
        assert [tuple(r) for r in con.execute("SELECT outcome, settled_at FROM atomic_undo")] == [
            (None, None)]
    finally:
        _dokoncz(stat)
        _zwolnij(widok, con)


@pytest.mark.parametrize("od", ["porazka", "nie_wiem"])
def test_ponowienie_przechodzi_w_trwa_z_jedna_etykieta(qapp, tmp_path, monkeypatch, od):
    """Jeden setter stanu wiersza pasywnego: z porażki i z „nie wiem” prawdziwy klik „Ponów sprawdzenie”, gdy
    przegląd znów wisi, przechodzi OD RAZU w „trwa” - w każdym stanie widocznym dokładnie jedna etykieta ze
    zdaniem, druga pusta i schowana. Falsyfikatory: start zlecenia bez ustawienia stanu (stare zdanie do
    wyniku); etykieta porażki niezdjęta w „trwa”."""
    if od == "porazka":
        from test_writeback_cofniecie_atomowe import _prawdziwy_blad_zajetej_bazy
        con, nazwy, _fid = _baza_ze_sladem(tmp_path)
        zajeta = _prawdziwy_blad_zajetej_bazy(tmp_path)

        def _pada(*a, **kw):
            raise zajeta
        monkeypatch.setattr(repo, "settle_atomic_undo", _pada)
        wisza = {nazwy[0]}
    else:
        con, k, _fid = _baza_z_kept(tmp_path)
        wisza = {k}
    stat = _Stat(monkeypatch)
    if od == "nie_wiem":
        stat.odpowiedz = lambda x: None if x in wisza else stat.prawdziwa(x)
    widok = _widok(con)
    try:
        widok.show()
        _wynik(widok)
        assert widok._stan_sladow == od
        assert _widoczne(widok) == [widok.blad_sladow if od == "porazka" else widok.stan_sladow]
        stat.wisza = set(wisza)
        QTest.mouseClick(widok.ponow_slady, Qt.LeftButton)
        assert widok._stan_sladow == "trwa" and _widoczne(widok) == [widok.stan_sladow]
        assert widok.stan_sladow.text() == i18n.t("tasks.traces_pending")
        assert not widok.ponow_slady.isEnabled()
        stat.zwolnij.set()
        _wynik(widok, "wynik ponowienia")
        assert widok._stan_sladow == od and len(_widoczne(widok)) == 1
    finally:
        _dokoncz(stat)
        _zwolnij(widok, con)


@pytest.mark.parametrize("polowa", ["zamiar_0038", "slad_0045"])
def test_kopia_usunieta_i_przywrocona(qapp, tmp_path, polowa):
    """AR-260 (wynik przeglądu nietrwały): kopia zostawiona do oka obu połów (zamiar podmiany 0038, ślad
    cofnięcia 0045). Przed pierwszym przeglądem - widoczna (nigdy niesprawdzona); kopia jest - widoczna;
    człowiek ją usuwa - wejście w Porządki zleca przegląd i wiersz z perspektywą ją zdejmują; kopia wraca -
    następne wejście pokazuje ją znowu (odczyt, nie werdykt w bazie). Liczba stoi na LIŚCIE widoku (człon
    drugi wiersza po rachunku w tle), a plakietka (`counts_changed`) traci i odzyskuje ten wiersz.
    Falsyfikatory: wejście bez zlecenia przeglądu; zapis „nie ma” trwały; rachunek po przeglądzie tylko przy
    werdykcie `kept` śladu (zmiana odczytu kopii bez rachunku)."""
    con, k, fid = _baza_z_kept(tmp_path, polowa)
    assert queries.kept_copy_frame_ids(con) == {fid}
    widok = _widok(con)
    plakietki = []
    widok.counts_changed.connect(plakietki.append)
    try:
        _wynik(widok)
        _rachunek(widok, 1)
        assert queries.obecnosc_kopii([k]) == {k: False}
        assert queries.tasks_state(con)["kept_copy_frames"] == 1
        z_kopia = plakietki[-1]
        os.remove(k)
        widok.odswiez_przy_wejsciu()
        _wynik(widok, "przegląd po usunięciu kopii")
        _rachunek(widok, 0)
        assert queries.kept_copy_frame_ids(con) == set()
        assert queries.tasks_state(con)["kept_copy_frames"] == 0 and plakietki[-1] == z_kopia - 1
        Path(k).write_bytes(b"K" * 64)
        widok.odswiez_przy_wejsciu()
        _wynik(widok, "przegląd po powrocie kopii")
        _rachunek(widok, 1)
        assert queries.kept_copy_frame_ids(con) == {fid} and plakietki[-1] == z_kopia
    finally:
        _zwolnij(widok, con)


def test_starszy_odczyt_nie_cofa_nowszego(qapp, tmp_path, monkeypatch):
    """Pamięć obecności z biletem: przegląd bazy A zaczyna `stat` nazwy X i wisi, przegląd bazy B (ta sama
    nazwa w jej wierszu `kept`) kończy odczytem „jest”, potem A wraca z „nie ma” - wygrywa odczyt rozpoczęty
    później (B): pamięć mówi „jest”, czytelnik obu baz pokazuje X, a rachunek liczników w tle (wątek
    liczników) po obu wynikach liczy wiersz „Kopie zostawione do oka” = 1. Falsyfikator: zapis bez porównania
    biletów (późny odczyt A ukrywa istniejącą kopię)."""
    for katalog in ("A", "B", "wspolny"):
        (tmp_path / katalog).mkdir()
    x = str(tmp_path / "wspolny" / "a.fits.0000abcd.horreum-kopia")
    con_a, _k, fid_a = _baza_z_kept(tmp_path / "A", kopia=x)
    con_b, _k, fid_b = _baza_z_kept(tmp_path / "B", kopia=x)
    zwolnij_a, wszedl_a, odczyty_x = threading.Event(), threading.Event(), []
    stat = _Stat(monkeypatch)

    def _odczyt(n):
        if n != x:
            return stat.prawdziwa(n)
        odczyty_x.append(threading.current_thread().ident)
        if len(odczyty_x) == 1:                    # pierwszy odczyt X (przegląd A) - wisi, potem „nie ma”
            wszedl_a.set()
            zwolnij_a.wait(20)
            return True
        return False
    stat.odpowiedz = _odczyt
    widok_a = _widok(con_a)
    widoki = [widok_a]
    try:
        assert wszedl_a.wait(10)
        widok_b = _widok(con_b)
        widoki.append(widok_b)
        _wynik(widok_b, "przegląd B")
        assert queries.obecnosc_kopii([x]) == {x: False}
        zwolnij_a.set()
        _wynik(widok_a, "przegląd A")
        assert queries.obecnosc_kopii([x]) == {x: False}
        assert queries.kept_copy_frame_ids(con_a) == {fid_a} and queries.kept_copy_frame_ids(con_b) == {fid_b}
        stany = []
        widok_a._przyloz_liczniki = lambda state, _kandydaci: stany.append(state["kept_copy_frames"])
        widok_a.refresh_counts(w_tle=True)
        _czekaj(lambda: widok_a._liczniki_thread is None and stany, "rachunek liczników w tle")
        assert stany[-1] == 1, stany
    finally:
        zwolnij_a.set()
        _dokoncz(stat)
        for w in widoki:
            w.zatrzymaj_pola()
            w.close()
        con_a.close()
        con_b.close()


# Bramka AST (AR-246): rachunek liczników i czytelnik kopii zostawionych bez I/O pliku.
_KORZENIE_BEZ_IO = (("horreum.gui.tasks", "_stan_licznikow"), ("horreum.gui.tasks", "_liczniki_osi"),
                    ("horreum.gui.queries", "kept_copy_frame_ids"))
_OS_IO = {"stat", "lstat", "scandir", "listdir", "walk", "open", "access", "fstat"}
_OS_PATH_IO = {"exists", "lexists", "isfile", "isdir", "getsize", "getmtime", "realpath", "samefile"}
_METODY_IO = {"stat", "lstat", "exists", "is_file", "is_dir", "iterdir", "glob", "rglob", "open",
              "read_bytes", "read_text"}


def _drzewa_pakietu(mutacje):
    """`{moduł: ast}` pakietu `horreum`; `mutacje` = `{(moduł, funkcja): kod}` - instrukcja wstawiona na
    początek ciała funkcji (po docstringu), w pamięci, bez pliku."""
    import horreum
    pakiet = Path(horreum.__file__).parent
    drzewa = {}
    for plik in sorted(pakiet.rglob("*.py")):
        modul = ".".join(plik.relative_to(pakiet.parent).with_suffix("").parts)
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        for wezel in drzewo.body:
            if isinstance(wezel, ast.FunctionDef) and (modul, wezel.name) in mutacje:
                wezel.body.insert(1 if ast.get_docstring(wezel) else 0,
                                  ast.parse(mutacje[(modul, wezel.name)]).body[0])
        drzewa[modul] = drzewo
    return drzewa


def _importy_modulu(drzewo, modul, drzewa):
    """Lokalna nazwa → moduł pakietu (`str`) albo `(moduł, nazwa)` - także importy leniwe w funkcjach."""
    out = {}
    for n in ast.walk(drzewo):
        if isinstance(n, ast.ImportFrom):
            baza = n.module or ""
            if n.level:
                baza = ".".join(modul.split(".")[:-n.level] + ([baza] if baza else []))
            for a in n.names:
                pelna = f"{baza}.{a.name}"
                out[a.asname or a.name] = pelna if pelna in drzewa else (baza, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in drzewa:
                    out[a.asname or a.name.split(".")[0]] = a.name
    return out


def _z_zasobu_pakietu(wywolanie):
    """Czy odbiorca TEGO wywołania metody wyprowadza się z literalnego `resources.files("<pakiet>")` -
    zasób pakietu, nie archiwum. Wyjątek dotyczy wyłącznie tego węzła, nie funkcji ani reszty łańcucha."""
    n = wywolanie.func.value
    while isinstance(n, (ast.Call, ast.Attribute)):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr == "files" and isinstance(f.value, ast.Name)
                    and f.value.id == "resources" and len(n.args) == 1
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                return True
            n = f
        else:
            n = n.value
    return False


def _io_w_funkcji(fn):
    for c in ast.walk(fn):
        if not isinstance(c, ast.Call):
            continue
        f = c.func
        if isinstance(f, ast.Name) and f.id in ("open", "path_gone"):
            yield f"{f.id}(...)"
        elif isinstance(f, ast.Attribute):
            b = f.value
            if isinstance(b, ast.Name) and b.id == "os" and f.attr in _OS_IO:
                yield f"os.{f.attr}(...)"
            elif (isinstance(b, ast.Attribute) and isinstance(b.value, ast.Name) and b.value.id == "os"
                  and b.attr == "path" and f.attr in _OS_PATH_IO):
                yield f"os.path.{f.attr}(...)"
            elif f.attr == "path_gone":
                yield ".path_gone(...)"
            elif isinstance(b, ast.Name) and b.id == "fits" and f.attr == "open":
                yield "fits.open(...)"
            elif f.attr in _METODY_IO and not _z_zasobu_pakietu(c):
                yield f".{f.attr}(...)"


def _io_z_korzeni(mutacje):
    """Znaleziska I/O pliku w grafie wołań od `_KORZENIE_BEZ_IO`: funkcje modułów pakietu wołane po nazwie
    albo przez importowany moduł (metody obiektów są poza grafem). `[(moduł.funkcja: opis)]`."""
    drzewa = _drzewa_pakietu(mutacje)
    funkcje = {(m, w.name): w for m, d in drzewa.items() for w in d.body if isinstance(w, ast.FunctionDef)}
    importy = {m: _importy_modulu(d, m, drzewa) for m, d in drzewa.items()}
    widziane, stos, znaleziska = set(), list(_KORZENIE_BEZ_IO), []
    while stos:
        wezel = stos.pop()
        if wezel in widziane or wezel not in funkcje:
            continue
        widziane.add(wezel)
        modul, _nazwa = wezel
        fn, imp = funkcje[wezel], importy[modul]
        znaleziska += [f"{modul}.{_nazwa}: {opis}" for opis in _io_w_funkcji(fn)]
        for c in ast.walk(fn):
            if not isinstance(c, ast.Call):
                continue
            f = c.func
            if isinstance(f, ast.Name):
                cel = (modul, f.id) if (modul, f.id) in funkcje else imp.get(f.id)
                if isinstance(cel, tuple):
                    stos.append(cel)
            elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                  and isinstance(imp.get(f.value.id), str)):
                stos.append((imp[f.value.id], f.attr))
    assert len(widziane) > 50, f"graf wołań nie chodzi: {len(widziane)} funkcji"
    return znaleziska


@pytest.mark.parametrize("mutacja", [
    None,
    ("horreum.gui.queries", "kept_copy_frame_ids", "Path(p).stat()"),
    ("horreum.resolve.objects", "_own_stamp", "Path(p).stat()"),
    ("horreum.gui.queries", "tasks_state", "scan.path_gone(p)"),
])
def test_rachunek_i_czytelnik_bez_io_archiwum(mutacja):
    """AR-246 (AST): z rachunku liczników Porządków (`tasks._stan_licznikow`, `_liczniki_osi`) i czytelnika
    kopii zostawionych (`queries.kept_copy_frame_ids`) nie da się dojść do I/O pliku: `os.*`, `os.path.*`,
    `open`, `fits.open`, `path_gone` ani metod ścieżek (`.stat()`, `.exists()`, `.read_text()`…). Wyjątek
    wyłącznie dla KONKRETNEGO wywołania na łańcuchu od literalnego `resources.files("<pakiet>")` (zasób
    pakietu - dziś stempel słownika obiektów i czytniki danych resolvera), nigdy dla całej funkcji. Mutacje
    w pamięci: `Path(p).stat()` w czytelniku, `Path(p).stat()` w funkcji z dozwolonym odczytem zasobu
    (`objects._own_stamp`), `scan.path_gone` w `tasks_state` - każda daje znalezisko w swojej funkcji."""
    mutacje = {} if mutacja is None else {(mutacja[0], mutacja[1]): mutacja[2]}
    znaleziska = _io_z_korzeni(mutacje)
    if mutacja is None:
        assert znaleziska == [], znaleziska
    else:
        assert any(z.startswith(f"{mutacja[0]}.{mutacja[1]}: ") for z in znaleziska), znaleziska


def test_wejscie_w_Porzadki_nie_przeglada_sladu_zywego_cofniecia(qapp, tmp_path, monkeypatch):
    """Cofnięcie drogą atomową w biegu (wątek z własnym połączeniem) zatrzymane tuż po utrwaleniu śladu - plik
    tymczasowy T na dysku, przed podmianą. Wejście w Porządki przegląda WYŁĄCZNIE kopie zostawione do oka, więc
    ślad żywego właściciela nie dostaje `kept` obserwatora: właściciel kończy i zapisuje `clean`, zdarzeń
    `location.displaced_kept` zero. Falsyfikator: wejście z pełnym przeglądem (obserwator śladów)."""
    from test_writeback_cofniecie_atomowe import _commit
    con, _p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    widok = _widok(con)                            # montaż: ani śladów, ani kopii - bez przeglądu
    po_sladzie, dalej, wyniki = threading.Event(), threading.Event(), []
    prawdziwy = writeback._podmien

    def _podmien(*a, **kw):
        po_sladzie.set()
        dalej.wait(20)
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_podmien", _podmien)

    def _cofnij():
        c = db.connect(str(tmp_path / "h.db"))
        try:
            wyniki.append(writeback.undo(c, cid, now=NOW))
        finally:
            c.close()
    wlasciciel = threading.Thread(target=_cofnij)
    wlasciciel.start()
    try:
        assert po_sladzie.wait(20), "cofnięcie nie doszło do podmiany"
        widok.odswiez_przy_wejsciu()
        _wynik(widok, "przegląd wejścia")
        dalej.set()
        wlasciciel.join(30)
        (u,) = wyniki
        assert u.complete, u
        assert [r[0] for r in con.execute("SELECT outcome FROM atomic_undo")] == ["clean"]
        assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.displaced_kept'"
                           ).fetchone()[0] == 0
    finally:
        dalej.set()
        wlasciciel.join(30)
        _zwolnij(widok, con)


def test_przeglad_wiszacy_nie_ukrywa_kopii_przywroconej(qapp, tmp_path, monkeypatch):
    """Próg zaufania: kopia X miała przy dawnym przeglądzie „nie ma”, człowiek ją przywrócił, a nowy przegląd
    wisi na INNEJ nazwie (Y, przed X) ponad limit - czytelnik tej bazy nie ufa „nie ma” sprzed startu
    wiszącego przeglądu: X widoczna na liście i w wierszu Porządków (2 klatki), zanim udział wróci. Po wyniku
    próg znika, a odczyty są świeże. Falsyfikator: czytelnik ufający dawnemu „nie ma” (X ukryta do powrotu
    udziału, choć zdanie „trwa” mówi, że wiersz pokazuje każdą kopię bez dowodu w tym sprawdzaniu)."""
    from horreum.gui import tasks as tasks_mod
    from test_writeback_cofniecie_atomowe import _slady_trzech_lokacji
    monkeypatch.setattr(tasks_mod, "_PRZEGLAD_LIMIT_S", 0.2)
    con, pliki, slady = _slady_trzech_lokacji(tmp_path)
    y, x = str(pliki[0]) + ".y.horreum-kopia", str(pliki[1]) + ".x.horreum-kopia"
    repo.settle_atomic_undo(con, undo_id=slady[0], outcome="kept", kept_paths=[y], now=NOW)
    repo.settle_atomic_undo(con, undo_id=slady[1], outcome="kept", kept_paths=[x], now=NOW)
    Path(y).write_bytes(b"y")
    fid_x = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(pliki[1]),)).fetchone()[0]
    queries.zapamietaj_obecnosc(x, queries.bilet_obecnosci(), True)     # dawny przegląd: X usunięta
    Path(x).write_bytes(b"x")                                           # człowiek ją przywrócił
    assert fid_x not in queries.kept_copy_frame_ids(con)
    stat = _Stat(monkeypatch, {y})
    widok = _widok(con)
    try:
        assert stat.wszedl.wait(10)
        widok.odswiez_przy_wejsciu()
        _czekaj(lambda: widok._stan_sladow == "trwa", "wiersz „trwa”")
        assert fid_x in queries.kept_copy_frame_ids(con)
        _rachunek(widok, 2, "rachunek z progiem zaufania")
        stat.zwolnij.set()
        _wynik(widok)
        assert queries.obecnosc_kopii([x, y]) == {x: False, y: False}
        assert fid_x in queries.kept_copy_frame_ids(con)
    finally:
        _dokoncz(stat)
        _zwolnij(widok, con)


def test_ponowienie_wiszace_ponad_limit_stawia_prog(qapp, tmp_path, monkeypatch):
    """Próg zaufania także na drodze ponowienia: przegląd kończy się „nie wiem” (Y bez odpowiedzi), człowiek
    przywraca X, którą wcześniejszy odczyt widział jako usuniętą, i klika „Ponów” - ponowienie wchodzi od razu
    w „trwa” i wisi na Y ponad limit. Próg i tak powstaje (należy do zlecenia, nie do stanu wiersza), więc
    X jest widoczna, zanim udział wróci. Falsyfikator: próg stawiany tylko przy wejściu w „trwa” z innego stanu
    (ponowienie zaczyna w „trwa”, więc próg nigdy by nie powstał, a X zostałaby ukryta)."""
    from horreum.gui import tasks as tasks_mod
    from test_writeback_cofniecie_atomowe import _slady_trzech_lokacji
    monkeypatch.setattr(tasks_mod, "_PRZEGLAD_LIMIT_S", 0.2)
    con, pliki, slady = _slady_trzech_lokacji(tmp_path)
    y, x = str(pliki[0]) + ".y.horreum-kopia", str(pliki[1]) + ".x.horreum-kopia"
    repo.settle_atomic_undo(con, undo_id=slady[0], outcome="kept", kept_paths=[y], now=NOW)
    repo.settle_atomic_undo(con, undo_id=slady[1], outcome="kept", kept_paths=[x], now=NOW)
    Path(y).write_bytes(b"y")
    fid_x = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(pliki[1]),)).fetchone()[0]
    stat = _Stat(monkeypatch)
    stat.odpowiedz = lambda n: None if n == y else stat.prawdziwa(n)
    widok = _widok(con)
    try:
        _wynik(widok, "przegląd montażu")
        assert widok._stan_sladow == "nie_wiem" and widok.ponow_slady.isEnabled()
        queries.zapamietaj_obecnosc(x, queries.bilet_obecnosci(), True)  # odczyt: X usunięta
        Path(x).write_bytes(b"x")                                       # człowiek ją przywrócił
        assert fid_x not in queries.kept_copy_frame_ids(con)
        stat.odpowiedz, stat.wisza = None, {y}
        QTest.mouseClick(widok.ponow_slady, Qt.LeftButton)
        assert widok._stan_sladow == "trwa"
        assert stat.wszedl.wait(10)
        _czekaj(lambda: fid_x in queries.kept_copy_frame_ids(con), "próg zaufania przy ponowieniu")
        stat.zwolnij.set()
        _wynik(widok, "wynik ponowienia")
        assert fid_x in queries.kept_copy_frame_ids(con)
    finally:
        _dokoncz(stat)
        _zwolnij(widok, con)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_zlecenie_konczy_sie_mimo_porazki_klasyfikacji(qapp, tmp_path, monkeypatch):
    """Przegląd pada, a klasyfikacja jego porażki (`powod_okna`) też pada: zlecenie i tak kończy się (`gotowe`
    w `finally`), widok mówi porażkę klasą błędu programu z aktywnym ponowieniem - zamiast „trwa” na zawsze ze
    zgaszonym przyciskiem, przenoszonym rejestrem na następne widoki. Falsyfikator: `gotowe` poza `finally`."""
    from horreum.gui import tasks as tasks_mod
    con, _nazwy, _fid = _baza_ze_sladem(tmp_path)

    def _pada(*a, **kw):
        raise sqlite3.OperationalError("przegląd padł")
    monkeypatch.setattr(writeback, "przejrzyj_slady_cofniecia", _pada)
    prawdziwa, wolania = tasks_mod.powod_okna, []

    def _klasyfikacja(exc):
        wolania.append(exc)
        if len(wolania) == 1:
            raise RuntimeError("klasyfikacja porażki padła")
        return prawdziwa(exc)
    monkeypatch.setattr(tasks_mod, "powod_okna", _klasyfikacja)
    widok = _widok(con)
    try:
        _wynik(widok)
        assert widok._stan_sladow == "porazka" and widok.ponow_slady.isEnabled()
        assert widok.blad_sladow.text().startswith(i18n.t("tasks.traces_failed", msg=""))
    finally:
        _zwolnij(widok, con)


def test_rejestr_bez_wpisu_po_nieudanym_starcie_watku(qapp, tmp_path, monkeypatch):
    """Wątek przeglądu nie startuje (system odmawia wątku): błąd leci do wołającego (EXPECT), a rejestr
    `_PRZEGLADY` nie dostaje wpisu, pod który następne widoki podpinałyby się na zawsze. Falsyfikator: wpis
    do rejestru przed `start()`."""
    from horreum.gui import tasks as tasks_mod
    con, _k, _fid = _baza_z_kept(tmp_path)

    class _NieStartuje(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(tasks_mod, "threading", types.SimpleNamespace(Thread=_NieStartuje,
                                                                      Event=threading.Event))
    try:
        with pytest.raises(RuntimeError):
            _widok(con)
        assert queries.klucz_bazy(str(tmp_path / "h.db")) not in tasks_mod._PRZEGLADY
    finally:
        con.close()


def test_wejscie_przy_bledzie_bazy_oddaje_mowe_rachunkowi(qapp, tmp_path):
    """Błąd bazy w pytaniu wejścia „czy są kopie do przeglądu” (tu `ProgrammingError` - połączenie zamknięte):
    wejście nie rzuca, zlecenia nie ma, a o błędzie mówi zdaniem rachunek liczników (AR-198) - ta sama polityka
    co przed falą na wejściu. Falsyfikator: pytanie wejścia bez ochrony (wyjątek z `odswiez_przy_wejsciu`)."""
    con, _k, _fid = _baza_z_kept(tmp_path)
    widok = _widok(con)
    zamkniete = db.connect(str(tmp_path / "h.db"))
    zamkniete.close()
    try:
        _wynik(widok)
        widok.con = zamkniete
        przed = [t for t in threading.enumerate() if t.name == _WATEK]
        widok.odswiez_przy_wejsciu()
        assert not widok.blad_licznikow.isHidden() and widok._przeglad_watek is None
        assert [t for t in threading.enumerate() if t.name == _WATEK] == przed
    finally:
        widok.con = con
        _zwolnij(widok, con)


def test_odczyt_odrzucony_biletem_przeczacy_nie_ma_obniza_do_nie_wiem():
    """Kolejność biletów nie musi być kolejnością `stat` (bilet pod zamkiem, `stat` poza nim): odczyt
    z niższym biletem, który przeczy zapisanemu „nie ma”, obniża wpis do „nie wiem” (nazwa widoczna); zgodny
    albo przeczący zapisanemu „jest” - odrzucony bez zmiany. Zwrot = czy zmieniła się wartość.
    Falsyfikator: odrzucenie bez obniżenia (późniejsze „jest” przegrywa z wcześniejszym „nie ma”)."""
    x, y = "X:/L/a.fits.0000abcd.horreum-kopia", "X:/L/b.fits.0000abcd.horreum-kopia"
    stary, nowy = queries.bilet_obecnosci(), queries.bilet_obecnosci()
    assert queries.zapamietaj_obecnosc(x, nowy, True)
    assert queries.zapamietaj_obecnosc(x, stary, False)
    assert queries.obecnosc_kopii([x]) == {x: None}
    assert not queries.zapamietaj_obecnosc(x, stary, True)
    assert queries.zapamietaj_obecnosc(y, nowy, False)
    assert not queries.zapamietaj_obecnosc(y, stary, True)
    assert not queries.zapamietaj_obecnosc(y, queries.bilet_obecnosci(), False)
    assert queries.obecnosc_kopii([x, y]) == {x: None, y: False}


def test_przeglad_bez_zmiany_odczytu_nie_liczy_licznikow(qapp, tmp_path):
    """Wejście w Porządki przy kopii, której odczyt się nie zmienił: przegląd idzie, ale rachunku liczników
    w tle po nim nie ma - skrót wejścia (AR-84, rachunek 0,7-1,9 s na kopii pf4) zostaje. Falsyfikator:
    rachunek po każdym przeglądzie z kopiami."""
    con, _k, _fid = _baza_z_kept(tmp_path)
    widok = _widok(con)
    try:
        _wynik(widok)
        _rachunek(widok, 1)
        rachunki = []
        widok.refresh_counts = lambda **kw: rachunki.append(kw)
        widok.odswiez_przy_wejsciu()
        assert widok._przeglad_watek is not None, "wejście zleca przegląd kopii"
        _wynik(widok, "przegląd wejścia")
        assert {"w_tle": True} not in rachunki, rachunki
    finally:
        _zwolnij(widok, con)


def test_wejscie_bez_niczego_do_przegladu_gasi_wiersz(qapp, tmp_path, monkeypatch):
    """Wiersz pasywny „nie wiem” z poprzedniego przeglądu, a baza nie ma już ani kopii zostawionych do oka, ani
    śladów bez werdyktu: wejście w Porządki nie zleca przeglądu i chowa wiersz - nie ma czego ponawiać.
    Falsyfikator: gałąź „nic do przeglądu” bez zgaszenia (stare zdanie stoi nad listą)."""
    con, _k, _fid = _baza_z_kept(tmp_path, "zamiar_0038")
    _Stat(monkeypatch, odpowiedz=lambda x: None)
    widok = _widok(con)
    try:
        _wynik(widok)
        assert widok._stan_sladow == "nie_wiem"
        con.execute("UPDATE replace_intent SET outcome = 'replaced', kept_paths = '[]'")
        con.commit()
        widok.odswiez_przy_wejsciu()
        assert widok._stan_sladow == "schowany" and widok.wiersz_sladow.isHidden()
        assert widok._przeglad_watek is None
    finally:
        _zwolnij(widok, con)


def test_montaz_podpiety_pod_przeglad_kopii_nie_przeglada_sladow_sam(qapp, tmp_path, monkeypatch):
    """Przegląd samych kopii z wejścia wisi; montaż tej bazy (zmiana bazy na nią) podpina się pod niego, bo
    drugiego wątku na bazę nie ma - i po jego wyniku NIE zleca sam przeglądu pełnego: ślad mógł w tym czasie
    utrwalić żywy właściciel cofnięcia tego procesu, a obserwator odebrałby mu `clean` (ten sam wyścig, dla
    którego wejście w Porządki śladów nie przegląda). Ślad bez werdyktu czeka na ponowienie albo następny
    montaż - ponowienie daje `kept`. Falsyfikator: pełny przegląd odpalany sam po wyniku podpiętego montażu."""
    from horreum.gui import tasks as tasks_mod
    con, k, _fid = _baza_z_kept(tmp_path)
    v1 = _widok(con)
    widoki = [v1]
    stat = _Stat(monkeypatch)
    try:
        _wynik(v1)
        b = con.execute("SELECT id FROM header_backups").fetchone()[0]
        k2 = k.replace(".0000abcd.", ".0000beef.")
        Path(k2).write_bytes(b"K" * 64)
        s = "a" * 40
        u2 = repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                                     byte_exact=True, source_sha1=s, source_size=1, displaced_path=k2,
                                     prepared_path=str(tmp_path / "tmp2.tmp"), now=NOW)
        stat.wisza = {k}
        v1.odswiez_przy_wejsciu()                  # wejście: wyłącznie przegląd kopii, wisi na K
        assert stat.wszedl.wait(10)
        zlecenie = tasks_mod._PRZEGLADY[queries.klucz_bazy(str(tmp_path / "h.db"))]
        v2 = _widok(con)
        widoki.append(v2)
        assert v2._przeglad is zlecenie and not zlecenie.pelny
        assert con.execute("SELECT outcome FROM atomic_undo WHERE id = ?", (u2,)).fetchone()[0] is None
        stat.zwolnij.set()
        _wynik(v1)
        _wynik(v2)
        koniec = time.monotonic() + 1.0             # okno, w którym pełny przegląd „po wyniku” by ruszył
        while time.monotonic() < koniec:
            QApplication.processEvents()
            time.sleep(0.01)
        assert v2._przeglad_watek is None and not any(
            t.name == _WATEK and t.is_alive() for t in threading.enumerate())
        assert con.execute("SELECT outcome FROM atomic_undo WHERE id = ?", (u2,)).fetchone()[0] is None
        v2._przejrzyj_slady()                      # ponowienie (przycisk) - przegląd pełny
        _czekaj(lambda: con.execute("SELECT outcome FROM atomic_undo WHERE id = ?",
                                    (u2,)).fetchone()[0] == "kept", "ślad po ponowieniu")
    finally:
        _dokoncz(stat)
        for w in widoki:
            w.zatrzymaj_pola()
            w.close()
        con.close()


def test_perspektywa_kopii_zostawionych_przed_i_po_przegladzie(qapp, tmp_path, monkeypatch):
    """Perspektywa Zbiorów „Kopie zostawione do oka” (prawdziwy widok, przycięcie przez `_TRIMY`): kopia jest -
    klatka w perspektywie; człowiek ją usuwa - po przeglądzie z wejścia w Porządki ponowne wejście
    w perspektywę jej nie ma. Perspektywa nie pyta o dysk - pyta wyłącznie wątek przeglądu. Falsyfikator:
    przycięcie perspektywy statujące dysk albo czytające co innego niż pamięć obecności."""
    from horreum.gui import grid as grid_mod
    con, k, _fid = _baza_z_kept(tmp_path)
    stat = _Stat(monkeypatch)
    widok = _widok(con)
    zbiory = grid_mod.FramesView(con, now_fn=lambda: NOW)
    try:
        _wynik(widok)
        zbiory.apply_perspective(grid_mod.PRESET_KEPT_COPIES)
        assert zbiory.model.rowCount() == 1
        os.remove(k)
        widok.odswiez_przy_wejsciu()
        _wynik(widok, "przegląd po usunięciu kopii")
        zbiory.apply_perspective(grid_mod.PRESET_KEPT_COPIES)
        assert zbiory.model.rowCount() == 0
        assert {w for w, _x in stat.wolania} == {_WATEK}, stat.wolania
    finally:
        zbiory.close()
        _dokoncz(stat)
        _zwolnij(widok, con)


def test_wejscie_przez_nawigacje_pyta_o_dysk_tylko_przegladem(qapp, tmp_path, monkeypatch):
    """Wejście w Porządki PRAWDZIWĄ nawigacją okna (`nav` → `_on_nav_changed` → `odswiez_przy_wejsciu`) przy
    kopii usuniętej przez człowieka: przegląd idzie, wiersz traci kopię, a o dysk pyta wyłącznie wątek
    przeglądu - ani wątek GUI, ani wątek liczników. Falsyfikator: drogi wejścia statujące dysk."""
    from horreum.gui.app import NAV_PORZADKI, MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    con, k, _fid = _baza_z_kept(tmp_path)
    con.close()
    stat = _Stat(monkeypatch)
    win = MainWindow(str(tmp_path / "h.db"))
    try:
        tasks = win.tasks_view
        _wynik(tasks, "przegląd montażu")
        _rachunek(tasks, 1)
        przed = len(stat.wolania)
        os.remove(k)
        win.nav.setCurrentRow(NAV_PORZADKI)
        _wynik(tasks, "przegląd wejścia")
        _rachunek(tasks, 0)
        assert len(stat.wolania) > przed
        assert {w for w, _x in stat.wolania} == {_WATEK}, stat.wolania
    finally:
        win.close()
        _dokoncz(stat)
