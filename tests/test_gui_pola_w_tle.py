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
    """Pola I skład zbioru, który pierwszy wynik pól zamawia (AR-27: oba w tle w widoku gospodarza)."""
    _czekaj(lambda: grid._pola_thread is None and grid._pola_worker is None
            and grid._zbior_thread is None and grid._zbior_worker is None,
            "wątki tła Zbiorów nie skończyły")


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


# ---------------------------------------------------------------- AR-27: skład zbioru w tle
# Ten sam przełącznik co pola (`pola_poza_watkiem=True`): widok gospodarza liczy zbiór w `ZbiorWorker`.

def _widok_w_tle(path):
    con = db.connect(path)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    _czekaj_na_pola(view)
    return view, con


def _zamknij(view, con):
    view.zatrzymaj_pola()
    view.close()
    con.close()


def _szpieg_przylozen(monkeypatch):
    """Każde przyłożenie wyniku do widoku: keywordy wyniku (rozróżniają zlecenia w testach)."""
    przylozone = []
    oryginal = grid_mod.FramesView._zastosuj_zbior

    def _spy(self, wynik):
        przylozone.append(list(wynik["keywords"]))
        return oryginal(self, wynik)
    monkeypatch.setattr(grid_mod.FramesView, "_zastosuj_zbior", _spy)
    return przylozone


def _brama_na_pivot(monkeypatch):
    """Pierwsze `cards_pivot` czeka na bramę (bieg w drodze); kolejne liczą od razu."""
    brama, wszedl = threading.Event(), threading.Event()
    prawdziwe = queries.cards_pivot

    def _cp(con, ids, kws):
        if not wszedl.is_set():
            wszedl.set()
            brama.wait(_BEZPIECZNIK_S)
        return prawdziwe(con, ids, kws)
    monkeypatch.setattr(queries, "cards_pivot", _cp)
    return brama, wszedl


def test_zlecenie_w_tle_wraca_od_razu_a_wynik_przyklada_slot(qapp, tmp_path, monkeypatch):
    """Klik facetu w widoku gospodarza nie liczy zbioru na wątku GUI: zlecenie wraca, zanim skład
    się skończy (brama trzyma workera), tabela trzyma zbiór poprzedni, a wynik przykłada slot.

    Falsyfikator: `_on_facet_change` → `self.refresh()` (bez `w_tle`) → zlecenie czeka na bramę."""
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        przylozone = _szpieg_przylozen(monkeypatch)
        brama, wszedl = _brama_na_pivot(monkeypatch)
        przed = view.model.rowCount()
        watki = []
        prawdziwe_br = queries.base_rows
        monkeypatch.setattr(queries, "base_rows",
                            lambda c, ids: watki.append(threading.get_ident()) or prawdziwe_br(c, ids))
        t0 = time.monotonic()
        view._on_columns(["GAIN"])
        assert time.monotonic() - t0 < _BEZPIECZNIK_S / 2, "zlecenie nie czekało na skład"
        assert wszedl.wait(_BEZPIECZNIK_S), "worker doszedł do pivota"
        assert przylozone == [] and view.model.rowCount() == przed, "w trakcie - zbiór poprzedni"
        brama.set()
        _czekaj_na_pola(view)
        assert przylozone == [["GAIN"]]
        assert view.model._keywords == ["GAIN"]
        assert watki and threading.get_ident() not in watki, "skład liczył wątek tła"
    finally:
        _zamknij(view, con)


def test_starszy_wynik_po_nowszym_zleceniu_trafia_do_kosza(qapp, tmp_path, monkeypatch):
    """Szybkie klikanie: zlecenie A w drodze, zlecenie B w tym czasie. Wynik A, który dotrze
    (przerwanie wyłączone - bieg liczy do końca), NIE jest przykładany; przykłada się wyłącznie B,
    i to jeden raz.

    Falsyfikator: zdejmij porównanie generacji z `_on_zbior_done` → przyłożone [OBJECT], [GAIN]."""
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        monkeypatch.setattr(grid_mod.ZbiorWorker, "request_cancel", lambda self: None)
        przylozone = _szpieg_przylozen(monkeypatch)
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view._on_columns(["OBJECT"])                  # A
        assert wszedl.wait(_BEZPIECZNIK_S)
        view._on_columns(["GAIN"])                    # B - w trakcie A
        brama.set()
        _czekaj_na_pola(view)
        assert przylozone == [["GAIN"]], przylozone
        assert view.model._keywords == ["GAIN"]
    finally:
        _zamknij(view, con)


def test_synchroniczne_przeladowanie_uniewaznia_wynik_w_drodze(qapp, tmp_path, monkeypatch):
    """Gest (odświeżenie synchroniczne) w trakcie składu w tle: gest dostaje świeży zbiór od razu,
    a spóźniony wynik zlecenia sprzed gestu NIE nadpisuje go po fakcie i nie rusza drugiego biegu
    (reset modelu zgubiłby zaznaczenie celu gestu).

    Falsyfikator: zdejmij `self._zbior_gen += 1` z gałęzi synchronicznej `refresh` → przyłożone
    na końcu [OBJECT]."""
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        monkeypatch.setattr(grid_mod.ZbiorWorker, "request_cancel", lambda self: None)
        przylozone = _szpieg_przylozen(monkeypatch)
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view._on_columns(["OBJECT"])
        assert wszedl.wait(_BEZPIECZNIK_S)
        view._columns = ["GAIN"]
        view.refresh()                                # droga gestu
        assert przylozone == [["GAIN"]] and view.model._keywords == ["GAIN"]
        brama.set()
        _czekaj_na_pola(view)
        for _ in range(10):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert przylozone == [["GAIN"]], przylozone
        assert view.model._keywords == ["GAIN"]
    finally:
        _zamknij(view, con)


def test_cel_gestu_wraca_w_zaznaczeniu_po_skladzie_w_tle(qapp, tmp_path):
    """Cel gestu (FC-2) odkłada się w zaznaczeniu także wtedy, gdy zbiór dojeżdża z wątku tła -
    recepta powrotu (perspektywa, „× Wyczyść zbiór") idzie drogą `w_tle`.

    Falsyfikator: konsumuj `_cel_gestu` w `refresh` zamiast w `_zastosuj_zbior` → zaznaczenie puste."""
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        view._cel_gestu = [2, 3]
        view._on_facet_change({})
        _czekaj_na_pola(view)
        assert sorted(r["frame_id"] for r in view._selected_data_rows()) == [2, 3]
        assert view._cel_gestu == []
    finally:
        _zamknij(view, con)


def test_perspektywa_w_tle_konczy_ogonem_po_przylozeniu(qapp, tmp_path, monkeypatch):
    """Ogon `_on_perspective` (szerokość ścieżki, recepta perspektywy izolacji - czyta `_frame_ids`)
    leci PO przyłożeniu zbioru perspektywy, nie zaraz po zleceniu - inaczej czytałby zbiór
    poprzedni - i leci raz.

    Falsyfikator: wołaj `_po_perspektywie` wprost po `refresh` → widzi keywordy sprzed perspektywy."""
    from horreum import repo
    path = _baza(tmp_path)
    view, con = _widok_w_tle(path)
    try:
        repo.save_perspective(con, name="Szeroka", now=NOW,
                              spec={"filter": None, "group_by": None, "columns": ["GAIN"],
                                    "view": {"path_width": 333}})
        view._odbuduj_perspektywy()
        widziane = []
        oryginal = grid_mod.FramesView._po_perspektywie
        monkeypatch.setattr(grid_mod.FramesView, "_po_perspektywie",
                            lambda self: widziane.append(list(self.model._keywords)) or oryginal(self))
        view.apply_perspective("Szeroka")
        _czekaj_na_pola(view)
        assert widziane == [["GAIN"]], widziane
        assert view.table.columnWidth(view.model.base_col("path")) == 333
    finally:
        _zamknij(view, con)


def test_ogon_wyprzedzonego_zlecenia_przechodzi_na_nowsze(qapp, tmp_path, monkeypatch):
    """Perspektywa w drodze, a w tym czasie klik facetu: wynik perspektywy idzie do kosza, ale jej
    ogon (recepta, szerokość) leci raz - po przyłożeniu zbioru nowszego zlecenia.

    Falsyfikator: czyść ogony przy każdym zleceniu → ogon perspektywy nie leci wcale."""
    from horreum import repo
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        repo.save_perspective(con, name="Tylko GAIN", now=NOW,
                              spec={"filter": None, "group_by": None, "columns": ["GAIN"]})
        view._odbuduj_perspektywy()
        widziane = []
        oryginal = grid_mod.FramesView._po_perspektywie
        monkeypatch.setattr(grid_mod.FramesView, "_po_perspektywie",
                            lambda self: widziane.append(dict(self._facet_state)) or oryginal(self))
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view.apply_perspective("Tylko GAIN")
        assert wszedl.wait(_BEZPIECZNIK_S)
        view._on_facet_change({"kind": {"in": [["light", "light"]]}})
        assert widziane == []
        brama.set()
        _czekaj_na_pola(view)
        assert widziane == [{"kind": {"in": [["light", "light"]]}}], widziane
    finally:
        _zamknij(view, con)


def test_edycja_otwarta_w_trakcie_skladu_w_tle_trafia_do_szuflady(qapp, tmp_path):
    """Edytor komórki otwarty przez widok, wpis z klawiatury, w tym czasie klik facetu. Wynik
    z wątku tła czeka na edytor; wyjście fokusem zatwierdza wpis do szuflady z podglądem, a zbiór
    dojeżdża dopiero PO zamknięciu edytora.

    Falsyfikator: zdejmij podpięcie `closeEditor` → `_przyloz_odlozony` → zbiór nie dojeżdża."""
    from PySide6.QtTest import QTest
    from horreum import writeback
    from test_gui_drogi_reki import _baza_z_fitsem, _otworz_edytor
    view, con = _widok_w_tle(_baza_z_fitsem(tmp_path, "edycja"))
    view._writeback_async = False
    try:
        idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
        QTest.keyClicks(ed.wartosc, "EQ6")
        otwarty_przy_przylozeniu = []
        oryginal = view._zastosuj_zbior

        def _spy(wynik):
            otwarty_przy_przylozeniu.append(view._edytor_otwarty())
            return oryginal(wynik)
        view._zastosuj_zbior = _spy
        view._on_facet_change({})
        assert view.table.indexWidget(idx) is ed, "zlecenie w tle nie zamyka edytora"
        _czekaj(lambda: view._zbior_worker is None, "skład w tle nie skończył")
        assert otwarty_przy_przylozeniu == [], "wynik czeka na edytor"
        inny.setFocus()                               # wyjście z edytora = zatwierdzenie
        for _ in range(5):                            # podgląd i zbiór idą `singleShot(0)`
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert otwarty_przy_przylozeniu == [False], "zbiór dojechał po zamknięciu edytora"
        (w,) = writeback.pending_for_run(con, view._run_id)
        assert (w["keyword"], w["new_value"]) == ("TELESCOP", "EQ6")
        pcol = view.model._preview_col()
        assert view.model.data(view.model.index(0, pcol), Qt.DisplayRole) == "RC8 → EQ6"
    finally:
        _zamknij(view, con)


def test_zamkniecie_okna_w_trakcie_skladu_przerywa_zapytanie(qapp, tmp_path, monkeypatch):
    """Zamknięcie okna w trakcie składu w tle: zapytanie przerwane (`interrupt`), wątek zebrany
    przed skasowaniem widoku, a spóźniony wynik nie trafia do widoku ani zamkniętego połączenia.

    Falsyfikator: zdejmij `self._zatrzymaj_zbior()` z `zatrzymaj_pola` → `QThread` niszczony
    w biegu (abort) albo zamknięcie czeka na koniec zapytania."""
    path = _baza(tmp_path)
    win = MainWindow(path)
    grid = win.grid_view
    _czekaj_na_pola(grid)
    przylozone = _szpieg_przylozen(monkeypatch)
    wystartowal = threading.Event()

    def _dlugie(con, ids):
        wystartowal.set()
        con.execute("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
                    "WHERE x < 60000000) SELECT count(*) FROM c").fetchone()
        return []
    monkeypatch.setattr(queries, "base_rows", _dlugie)
    grid._on_facet_change({})
    assert wystartowal.wait(_BEZPIECZNIK_S), "skład ruszył w tle"
    assert grid._zbior_thread is not None and grid._zbior_thread.isRunning()
    t0 = time.monotonic()
    win.close()
    assert time.monotonic() - t0 < 5, "zamknięcie przerwało zapytanie, nie czekało na nie"
    assert grid._zbior_thread is None and grid._zbior_worker is None, "wątek zebrany przy zamknięciu"
    for _ in range(10):
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
    assert przylozone == [], "przerwany bieg niczego nie przyłożył"


# ---- zbiór w drodze: gesty, edycja i menu nie działają na zbiorze, który zaraz zniknie ----

def _akcje_calego_widoku(view):
    return (view.macro_bar.btn_prev, view.macro_bar.btn_stage, view.rename_bar.btn_prev,
            view.rename_bar.btn_stage, view.sel_bar.btn_proj)


def test_w_drodze_akcje_calego_widoku_gasna_a_sloty_odmawiaja(qapp, tmp_path, monkeypatch):
    """Zlecenie w tle w drodze: Podgląd/Do stagingu makra i renamu oraz „Wydaj na stół…" gasną
    z tooltipem, a ich sloty (droga obok przycisku) odmawiają ze zdaniem i niczego nie stage'ują.
    Po przyłożeniu wracają. Zbiór w drodze w biegu etapu Dostawy nie włącza tego, co zgasił etap.

    Falsyfikator: zdejmij `_sync_zbioru_w_drodze()` z gałęzi tła `refresh` → przyciski aktywne."""
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        assert all(b.isEnabled() for b in _akcje_calego_widoku(view))
        msg = []
        view.status_message.connect(msg.append)
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view._on_columns(["GAIN"])
        assert wszedl.wait(_BEZPIECZNIK_S)
        assert view._zbior_w_drodze()
        tip = i18n.t("grid.sel.loading_tip")
        for b in _akcje_calego_widoku(view):
            assert not b.isEnabled() and b.toolTip() == tip, b.text()
        view._on_macro_stage({})
        view._on_macro_preview({})
        view._on_rename_stage({})
        view._open_projection()
        assert msg == [i18n.t("grid.sel.loading_refused")] * 4, msg
        assert view._pending_count() == 0 and view._run_id is None
        view.set_busy(True)                           # etap Dostawy rusza w trakcie składu
        brama.set()
        _czekaj_na_pola(view)
        assert not view._zbior_w_drodze()
        assert not any(b.isEnabled() for b in _akcje_calego_widoku(view)), "etap trzyma swoje"
        view.set_busy(False)
        assert all(b.isEnabled() for b in _akcje_calego_widoku(view))
        assert view.macro_bar.btn_stage.toolTip() == ""
    finally:
        _zamknij(view, con)


def test_w_drodze_nowa_edycja_sie_nie_otwiera(qapp, tmp_path, monkeypatch):
    """Zbiór w drodze zdejmuje wyzwalacze edycji: wiersz pod kursorem za chwilę zniknie. Po
    przyłożeniu edycja wraca.

    Falsyfikator: zdejmij `_zbior_w_drodze()` z `_sync_edycji` → edytor się otwiera."""
    from test_gui_drogi_reki import _baza_z_fitsem, _kol
    view, con = _widok_w_tle(_baza_z_fitsem(tmp_path, "bez_edycji"))
    try:
        view.resize(1200, 600)
        view.show()
        QApplication.processEvents()
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view._on_facet_change({})
        assert wszedl.wait(_BEZPIECZNIK_S)
        idx = view.model.index(0, _kol(view, "TELESCOP"))
        view.table.setCurrentIndex(idx)
        view.table.edit(idx)
        QApplication.processEvents()
        assert view.table.indexWidget(idx) is None, "edytor otwarty nad zbiorem w drodze"
        brama.set()
        _czekaj_na_pola(view)
        idx = view.model.index(0, _kol(view, "TELESCOP"))
        view.table.edit(idx)
        QApplication.processEvents()
        assert view.table.indexWidget(idx) is not None, "po przyłożeniu edycja wraca"
    finally:
        _zamknij(view, con)


def test_wynik_czeka_na_zamkniecie_edytora_i_nie_zatwierdza_polowy_wpisu(qapp, tmp_path,
                                                                        monkeypatch):
    """Edytor otwarty przez widok, pół wpisu z klawiatury, w tym czasie klik facetu. Wynik z wątku
    tła NIE resetuje modelu pod piszącym (reset zatwierdziłby „EQ"); człowiek dopisuje i kończy
    Enterem - w szufladzie ląduje pełny wpis, a odłożony zbiór dojeżdża dopiero po zamknięciu.

    Falsyfikator: przykładaj wynik w `_on_zbior_done` bez pytania o edytor → w szufladzie „EQ"."""
    from PySide6.QtTest import QTest
    from horreum import writeback
    from test_gui_drogi_reki import _baza_z_fitsem, _otworz_edytor
    view, con = _widok_w_tle(_baza_z_fitsem(tmp_path, "polowa"))
    view._writeback_async = False
    try:
        przylozone = _szpieg_przylozen(monkeypatch)
        idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
        ed.wartosc.selectAll()
        QTest.keyClicks(ed.wartosc, "EQ")
        view._on_facet_change({})
        _czekaj(lambda: view._zbior_worker is None, "skład w tle nie skończył")
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert view.table.indexWidget(idx) is ed, "edytor żyje mimo wyniku"
        assert przylozone == [] and view._zbior_w_drodze(), "wynik czeka na edytor"
        assert view._pending_count() == 0, "nic nie zatwierdzone w połowie"
        QTest.keyClicks(ed.wartosc, "6")
        QTest.keyClick(ed.wartosc, Qt.Key_Return)
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        (w,) = writeback.pending_for_run(con, view._run_id)
        assert (w["keyword"], w["new_value"]) == ("TELESCOP", "EQ6")
        assert len(przylozone) == 1 and not view._zbior_w_drodze(), "odłożony zbiór dojechał"
    finally:
        _zamknij(view, con)


def test_odlozony_wynik_wyprzedzony_nowszym_zleceniem_idzie_do_kosza(qapp, tmp_path, monkeypatch):
    """Wynik A czeka na edytor, w tym czasie rusza zlecenie B. Edytor zamyka się (Esc), gdy B jest
    jeszcze w drodze: A NIE jest przykładany (B go wyprzedziło), a B przykłada się raz, po swoim końcu.

    Falsyfikator: zdejmij `self._zbior_odlozony = None` z `refresh` i sprawdzenie generacji
    w `_przyloz_odlozony` → przyłożone A, potem B."""
    from PySide6.QtTest import QTest
    from test_gui_drogi_reki import _baza_z_fitsem, _otworz_edytor
    view, con = _widok_w_tle(_baza_z_fitsem(tmp_path, "kosz"))
    try:
        przylozone = _szpieg_przylozen(monkeypatch)
        idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
        view._on_columns(["TELESCOP"])                      # A
        _czekaj(lambda: view._zbior_worker is None, "A nie skończył")
        assert view._zbior_odlozony is not None, "A czeka na edytor"
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view._on_columns(["TELESCOP", "IMAGETYP"])          # B - w drodze
        assert wszedl.wait(_BEZPIECZNIK_S)
        QTest.keyClick(ed.wartosc, Qt.Key_Escape)
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert przylozone == [], "A wyprzedzone przez B - do kosza"
        brama.set()
        _czekaj_na_pola(view)
        assert przylozone == [["TELESCOP", "IMAGETYP"]], przylozone
    finally:
        _zamknij(view, con)


def test_przylozenie_zamyka_menu_tabeli_otwarte_nad_starym_zbiorem(qapp, tmp_path, monkeypatch):
    """Menu prawego kliku otwarte w trakcie składu w tle: przyłożenie wyniku zmienia wiersze
    i zaznaczenie, więc menu (liczone z zaznaczenia w chwili pokazania) zamyka się, zanim klik
    zapisze na innych klatkach.

    Falsyfikator: zdejmij zamykanie menu z `_zastosuj_zbior` → menu dalej widoczne."""
    view, con = _widok_w_tle(_baza(tmp_path))
    try:
        view.resize(1200, 600)
        view.show()
        QApplication.processEvents()
        brama, wszedl = _brama_na_pivot(monkeypatch)
        view._on_columns(["GAIN"])
        assert wszedl.wait(_BEZPIECZNIK_S)
        view._cel_gestu = [3]                         # przyłożenie zmieni zaznaczenie
        view._menu_tabeli.popup(view.table.viewport().mapToGlobal(view.table.viewport().rect().center()))
        QApplication.processEvents()
        assert view._menu_tabeli.isVisible()
        brama.set()
        _czekaj_na_pola(view)
        QApplication.processEvents()
        assert not view._menu_tabeli.isVisible(), "menu nad starym zbiorem zamknięte"
    finally:
        _zamknij(view, con)


def test_start_okna_mowi_wczytuje_mimo_raportu_przed_podpieciem(qapp, tmp_path, monkeypatch):
    """Pierwsze „Wczytuję…" leci z `FramesView.__init__`, zanim gospodarz podepnie `load_report` -
    gospodarz prosi o nie jeszcze raz (`ponow_raport_wczytania`).

    Falsyfikator: zdejmij `grid.ponow_raport_wczytania()` z `_mount_views` → brak raportu."""
    raporty = []
    oryginal = MainWindow._raport_wczytania_gridu
    monkeypatch.setattr(MainWindow, "_raport_wczytania_gridu",
                        lambda self, msg: raporty.append(msg) or oryginal(self, msg))
    brama, wszedl = _brama_na_pivot(monkeypatch)
    win = MainWindow(_baza(tmp_path))
    try:
        assert raporty[:1] == [i18n.t("busy.read_frames")], raporty
        brama.set()
        _czekaj_na_pola(win.grid_view)
    finally:
        brama.set()
        win.close()
