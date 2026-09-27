"""Pokrycie panelu „Pola" (Zbiory) liczone POZA wątkiem GUI i wyłącznie wtedy, gdy zmieniły się karty.

Firsthand na kopii żywej bazy (16 901 klatek, ~1 mln wierszy `cards`): po każdym przebiegu Dostawy
okno stało jednym blokiem 3,9-6,3 s, otwarcie bazy 6,2 s, a 5,6-5,9 s z tego to jedno zapytanie
`queries.keyword_facets` - wołane także wtedy, gdy przebieg nie zmienił ani jednej karty.

Testy idą drogą PRODUKCYJNĄ: `MainWindow` z prawdziwym `QThread` (seam `_pola_poza_watkiem`
zostaje w domyślnym True). Każde czekanie ma bezpiecznik czasowy, więc zawieszenie kończy się
porażką z opisem, a nie wiszącą baterią. Okno offscreen, bazy w `tmp_path`."""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt
from PySide6.QtWidgets import QApplication

from horreum import db
from horreum.gui import grid as grid_mod, i18n, queries, rows
from horreum.gui.app import MainWindow

NOW = "2026-07-03T14:00:00"
_BEZPIECZNIK_S = 30


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _baza(tmp_path, nazwa="p.db", keywordy=("OBJECT", "EXPTIME", "GAIN")):
    path = str(tmp_path / nazwa)
    con = db.open_db(path)
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
        [(i, f"d{i}", "light", "fits", NOW) for i in (1, 2, 3)])
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(i, "V", f"/a/f{i}.fits", 1) for i in (1, 2, 3)])
    con.executemany(
        "INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) "
        "VALUES (?,?,?,?,?,?)",
        [(i, kw, 0, "x", None, "str") for i in (1, 2, 3) for kw in keywordy])
    con.commit()
    con.close()
    return path


def _czekaj(warunek, opis):
    """Pompuj pętlę zdarzeń, aż `warunek()`; bezpiecznik zamiast wiszenia. `sleep` oddaje GIL
    wątkowi tła, `processEvents` doręcza jego sygnały (połączenia kolejkowane do wątku GUI)."""
    koniec = time.monotonic() + _BEZPIECZNIK_S
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {_BEZPIECZNIK_S} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.005)


def _czekaj_na_pola(grid):
    _czekaj(lambda: grid._pola_thread is None and grid._pola_worker is None,
            "wątek pokrycia pól nie skończył")


def _pola_listy(grid):
    """`{keyword: "(pokrycie)"}` panelu Pól - to, co widać w listwie."""
    lst = grid.fields.list
    return {lst.item(i).data(Qt.UserRole): lst.item(i).data(rows.SECONDARY)
            for i in range(lst.count())}


def _szpieg(monkeypatch, *, brama=None):
    """Podmień `queries.keyword_facets`: zapisuje wątek KAŻDEGO wywołania; z `brama` (Event)
    czeka na nią przed liczeniem (najwyżej bezpiecznik - brama zapomniana nie wiesza baterii)."""
    wywolania = []
    prawdziwe = queries.keyword_facets

    def _kf(con):
        wywolania.append(threading.get_ident())
        if brama is not None:
            brama.wait(_BEZPIECZNIK_S)
        return prawdziwe(con)
    monkeypatch.setattr(queries, "keyword_facets", _kf)
    return wywolania


def _dopisz_karte(path, keyword):
    """Zapis przez DRUGIE połączenie - tak pisze worker Dostawy (WAL)."""
    con = db.connect(path)
    con.execute("INSERT INTO cards (frame_id, keyword, idx, value_raw, value_type) "
                "VALUES (1, ?, 0, 'x', 'str')", (keyword,))
    con.commit()
    con.close()


def test_otwarcie_bazy_liczy_pokrycie_w_tle_i_dobiera_kolumny(qapp, tmp_path, monkeypatch):
    """Otwarcie bazy (montaż widoków) NIE liczy pokrycia na wątku GUI: `keyword_facets` woła
    wyłącznie wątek tła, a pierwszy wynik dobiera kolumny domyślne i przeładowuje nimi tabelę.

    Falsyfikator: `pola_poza_watkiem=False` w `_mount_views` → wątek wywołania = wątek GUI."""
    wywolania = _szpieg(monkeypatch)
    win = MainWindow(_baza(tmp_path))
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        assert wywolania and threading.get_ident() not in wywolania, wywolania
        assert set(_pola_listy(grid)) == {"OBJECT", "EXPTIME", "GAIN"}
        assert set(grid._columns) == {"OBJECT", "EXPTIME", "GAIN"}, "kolumny z pierwszego wyniku"
        assert grid.model.columnCount() == len(grid_mod.BASE_COLS) + 3, "tabela je pokazuje"
        assert grid.fields.title.text() == i18n.t("grid.fields.title")
    finally:
        win.close()


def test_przebieg_bez_zmiany_kart_nie_liczy_pokrycia(qapp, tmp_path, monkeypatch):
    """Przebieg Dostawy, który nie ruszył ani jednej karty, NIE woła `keyword_facets` (5,6-5,9 s na
    żywej bazie) - odcisk kart się zgadza, listwa zostaje, jaka była.

    Falsyfikator: zdejmij porównanie odcisku w `PolaWorker._policz` → licznik wywołań = 1."""
    path = _baza(tmp_path)
    win = MainWindow(path)
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        przed = _pola_listy(grid)
        wywolania = _szpieg(monkeypatch)
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)               # koniec przebiegu → odświeżenie widoków
        _czekaj_na_pola(grid)
        assert wywolania == [], "karty bez zmian - pokrycia nie liczymy"
        assert _pola_listy(grid) == przed
        assert grid.fields.title.text() == i18n.t("grid.fields.title")
    finally:
        win.close()


def test_zmiana_kart_liczy_pokrycie_w_tle_a_listwa_trzyma_stan_poprzedni(qapp, tmp_path,
                                                                          monkeypatch):
    """Przebieg, który dopisał kartę, liczy pokrycie W WĄTKU TŁA: odświeżenie widoków wraca, zanim
    liczenie się skończy (brama trzyma workera), listwa w tym czasie pokazuje stan POPRZEDNI
    z tytułem „liczę…" - nie pustkę udającą archiwum bez pól - a po powrocie dostaje wynik
    z nowym keywordem. Zaznaczenia usera (kolumny) przeżywają przeliczenie.

    Falsyfikator: licz pokrycie w `_load_facets` wprost → odświeżenie czeka na bramę (bezpiecznik)
    i wątek wywołania = wątek GUI."""
    path = _baza(tmp_path)
    win = MainWindow(path)
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        grid._on_columns(["GAIN"])                    # wybór człowieka - ma przeżyć przeliczenie
        przed = _pola_listy(grid)
        _dopisz_karte(path, "NOWYKW")
        brama = threading.Event()
        wywolania = _szpieg(monkeypatch, brama=brama)

        t0 = time.monotonic()
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)
        assert time.monotonic() - t0 < _BEZPIECZNIK_S / 2, "odświeżenie nie czekało na pokrycie"
        _czekaj(lambda: bool(wywolania), "worker nie doszedł do liczenia")
        assert grid.fields.title.text() == i18n.t("grid.fields.title_counting")
        assert _pola_listy(grid) == przed, "w trakcie - stan poprzedni, nie pustka"

        brama.set()
        _czekaj_na_pola(grid)
        assert threading.get_ident() not in wywolania, "liczył wątek tła"
        assert _pola_listy(grid)["NOWYKW"] == "(1)", "listwa dostała wynik"
        assert "NOWYKW" in grid._all_keywords, "keywordy filtra i makra też"
        assert grid.fields.title.text() == i18n.t("grid.fields.title")
        assert grid._columns == ["GAIN"], "zaznaczenie człowieka przeżyło przeliczenie"
        assert grid.fields.checked_keywords() == ["GAIN"]
    finally:
        win.close()


def test_wynik_spozniony_po_przelaczeniu_bazy_nie_jest_aplikowany(qapp, tmp_path, monkeypatch):
    """Przełączenie bazy w trakcie liczenia: stary widok zbiera swój wątek, a jego wynik - policzony
    na STAREJ bazie - trafia do kosza (generacja), nie do listwy. Nowy widok pokazuje pokrycie
    nowej bazy.

    Falsyfikator: zdejmij `self._pola_gen += 1` z `zatrzymaj_pola` → stary wynik („SPOZNIONY")
    zostaje zastosowany w starym widoku, zanim ten zniknie."""
    stara = _baza(tmp_path, "a.db")
    nowa = _baza(tmp_path, "b.db", keywordy=("FILTER",))
    zastosowane = []
    oryginal = grid_mod.FramesView._zastosuj_pola

    def _spy(self, facets):
        zastosowane.append([f["keyword"] for f in facets])
        return oryginal(self, facets)
    monkeypatch.setattr(grid_mod.FramesView, "_zastosuj_pola", _spy)

    win = MainWindow(stara)
    try:
        _czekaj_na_pola(win.grid_view)
        _dopisz_karte(stara, "NOWYKW")                # odcisk inny → worker policzy
        wystartowal = threading.Event()
        prawdziwe = queries.keyword_facets

        def _spozniony(con):
            if not wystartowal.is_set():              # tylko bieg starej bazy jest spóźniony
                wystartowal.set()
                time.sleep(0.5)
                return [{"keyword": "SPOZNIONY", "n": 1}]
            return prawdziwe(con)
        monkeypatch.setattr(queries, "keyword_facets", _spozniony)
        zastosowane.clear()
        win.grid_view._load_facets()
        assert wystartowal.wait(_BEZPIECZNIK_S), "bieg starej bazy ruszył"

        win.open_path(nowa)                           # przełączenie W TRAKCIE liczenia
        _czekaj_na_pola(win.grid_view)
        for _ in range(20):                           # doręcz wszystko, co jeszcze w kolejce
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert all("SPOZNIONY" not in z for z in zastosowane), zastosowane
        assert set(_pola_listy(win.grid_view)) == {"FILTER"}, "nowy widok - pokrycie nowej bazy"
    finally:
        win.close()


def test_zamkniecie_okna_w_trakcie_liczenia_przerywa_zapytanie(qapp, tmp_path, monkeypatch):
    """Zamknięcie okna w trakcie liczenia nie czeka do końca zapytania i nie zostawia żywego
    `QThread` pod kasowanym widokiem (to byłby twardy abort aplikacji). Zapytanie w teście jest
    naprawdę długie (rekurencyjne CTE po stronie SQLite), więc kończy je wyłącznie
    `Connection.interrupt` z wątku GUI - flaga sprawdzana między krokami by tu nie zdążyła.

    Falsyfikator: zdejmij `interrupt` z `PolaWorker.request_cancel` → zamknięcie czeka do końca
    CTE (~14 s na tej maszynie: 2·10⁷ kroków = 4,7 s, zmierzone) i asercja czasu pada. CTE ma
    koniec właśnie po to, żeby falsyfikator kończył się porażką, a nie wiszącą baterią."""
    wystartowal = threading.Event()

    def _dlugie(con):
        wystartowal.set()
        con.execute("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
                    "WHERE x < 60000000) SELECT count(*) FROM c").fetchone()
        return []
    monkeypatch.setattr(queries, "keyword_facets", _dlugie)
    win = MainWindow(_baza(tmp_path))
    grid = win.grid_view
    assert wystartowal.wait(_BEZPIECZNIK_S), "liczenie ruszyło w tle"
    assert grid._pola_thread is not None and grid._pola_thread.isRunning()
    t0 = time.monotonic()
    win.close()
    assert time.monotonic() - t0 < 5, "zamknięcie przerwało zapytanie, nie czekało na nie"
    assert grid._pola_thread is None and grid._pola_worker is None, "wątek zebrany przy zamknięciu"
    for _ in range(10):                               # spóźnione sygnały nie mają dokąd trafić
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
    assert grid.fields.title.text() == i18n.t("grid.fields.title_counting"), \
        "przerwany bieg nie udaje ani wyniku, ani błędu"


def test_przelaczenie_perspektywy_z_kolumnami_nie_liczy_pokrycia(qapp, tmp_path, monkeypatch):
    """Perspektywa niosąca kolumny zmienia wyłącznie zaznaczenia pól - bierze je z ostatniego
    pokrycia, zamiast liczyć je dla całego archiwum na wątku GUI.

    Falsyfikator: wróć do `self.fields.load(queries.keyword_facets(...))` w `_on_perspective`."""
    from horreum import repo
    path = _baza(tmp_path)
    con = db.connect(path)
    try:
        view = grid_mod.FramesView(con, now_fn=lambda: NOW)     # inline - jak w testach gridu
        repo.save_perspective(con, name="Tylko GAIN", now=NOW,
                              spec={"filter": None, "group_by": None, "columns": ["GAIN"]})
        view._odbuduj_perspektywy()
        wywolania = _szpieg(monkeypatch)
        view.apply_perspective("Tylko GAIN")
        assert wywolania == []
        assert view.fields.checked_keywords() == ["GAIN"]
        assert set(_pola_listy(view)) == {"OBJECT", "EXPTIME", "GAIN"}, "lista pól nietknięta"
        view.close()
    finally:
        con.close()
