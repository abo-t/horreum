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
    gospodarz prosi o nie jeszcze raz (`ponow_raport_wczytania`). Strona Zbiorów powstaje przy pierwszym
    wejściu (AR-325) - raport pada wtedy, nie przy otwarciu bazy (bez gridu nie ma czego wczytywać).

    Falsyfikator: zdejmij `grid.ponow_raport_wczytania()` z budowy strony Zbiorów → brak raportu."""
    from horreum.gui.app import NAV_ZBIORY
    raporty = []
    oryginal = MainWindow._raport_wczytania_gridu
    monkeypatch.setattr(MainWindow, "_raport_wczytania_gridu",
                        lambda self, msg: raporty.append(msg) or oryginal(self, msg))
    brama, wszedl = _brama_na_pivot(monkeypatch)
    win = MainWindow(_baza(tmp_path))
    try:
        assert raporty == [] and win._gotowy("grid_view") is None
        win._show_view(NAV_ZBIORY)
        assert raporty[:1] == [i18n.t("busy.read_frames")], raporty
        brama.set()
        _czekaj_na_pola(win.grid_view)
    finally:
        brama.set()
        win.close()


# ---------------------------------------------------------------- AR-84: ogony gestów zapisu w tle
# Gest zapisu przeładowuje zbiór W TLE, a kroki czytające model po przeładowaniu (cel w zaznaczeniu,
# „poza widokiem", zdanie, recepta) niesie ogon `potem`. Na czas składu gesty zaznaczenia odmawiają,
# a zaznaczenie stoi - inaczej trafiałyby w zbiór, który zaraz zniknie (lekcja AR-27, 3 P1).

def _baza_obiektu(tmp_path):
    """Trzy lighty z obiektem ze ŚCIEŻKI (źródło słabe - „Cofnij przypisanie" je zdejmie)."""
    path = str(tmp_path / "obj.db")
    con = db.open_db(path)
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (5,'NGC6960','NGC','deep_sky')")
    for i in (1, 2, 3):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
                    "object_source) VALUES (?, 'light', 'raw', ?, ?, 5, 'path')", (i, f"sha{i}", NOW))
        con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (i,))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?,'V',?,1)",
                    (i, rf"R:\ASTRO_\LIGHTS\NGC6960\f{i}.ARW"))
    con.commit()
    con.close()
    return path


def _brama_na_skladzie(monkeypatch):
    """`base_rows` liczone POZA wątkiem GUI czeka na bramę (bieg w drodze); wątek GUI liczy od razu."""
    brama, wszedl = threading.Event(), threading.Event()
    glowny = threading.get_ident()
    prawdziwe = queries.base_rows

    def _br(con, ids):
        if threading.get_ident() != glowny:
            wszedl.set()
            brama.wait(_BEZPIECZNIK_S)
        return prawdziwe(con, ids)
    monkeypatch.setattr(queries, "base_rows", _br)
    return brama, wszedl


def _zaznaczone(view):
    return sorted(r["frame_id"] for r in view._selected_data_rows())


def test_gest_osi_wraca_od_razu_a_ogon_odklada_cel_zdanie_i_recepte(qapp, tmp_path, monkeypatch):
    """„Cofnij przypisanie" w widoku gospodarza: zapis od razu, skład zbioru w tle (slot wraca, choć
    brama trzyma workera). Na czas składu: zdanie gestu jeszcze nie pada (przykryłby je raport
    wczytania), drugi gest odmawia bez zapisu, a klik w tabeli nie zmienia zaznaczenia - ogon
    odłożyłby cel gestu na wybór, którego człowiek by nie zobaczył. Po przyłożeniu: cel
    w zaznaczeniu, JEDNO zdanie gestu, recepta „Przywróć" ze znacznikiem gestu z chwili zapisu
    (zdarzenie ręki dopisane w trakcie składu go nie podmienia). Recepta poprzednia schodzi od
    razu (pusta - Dom nie pokazuje wykonanej jako czynnej), a nad tabelą stoi kursor zajętości.

    Falsyfikator: `self.refresh()` zamiast `refresh(w_tle=True, potem=…)` w `_po_gescie_osi` →
    zbiór nie jest w drodze po geście (pierwsza asercja `_zbior_w_drodze`)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractItemView
    from horreum import repo
    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        view.resize(1200, 600)
        view.show()
        QApplication.processEvents()
        view._przywroc_zaznaczenie([1, 2])
        assert _zaznaczone(view) == [1, 2]
        msg, recepty = [], []
        view.status_message.connect(msg.append)
        view.status_recipe.connect(recepty.append)
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        t0 = time.monotonic()
        view._on_object_clear()
        assert time.monotonic() - t0 < _BEZPIECZNIK_S / 2, "gest nie czekał na skład"
        assert wszedl.wait(_BEZPIECZNIK_S), "skład ruszył w tle"
        assert view._zbior_w_drodze()
        assert con.execute("SELECT count(*) FROM frame WHERE object_source = 'user_cleared'"
                           ).fetchone()[0] == 2, "zapis gestu jest w bazie od razu"
        assert msg == [], "zdanie gestu czeka na przyłożenie"
        assert recepty and str(recepty[-1]) == "", "recepta poprzednia zeszła od razu"
        assert view.table.selectionMode() == QAbstractItemView.NoSelection
        assert view.table.viewport().cursor().shape() == Qt.BusyCursor
        wiersz_3 = next(i for i, r in enumerate(view.model._rows) if r.get("frame_id") == 3)
        rect = view.table.visualRect(view.model.index(wiersz_3, 0))
        QTest.mouseClick(view.table.viewport(), Qt.LeftButton, Qt.NoModifier,
                         QPoint(rect.center()))
        assert _zaznaczone(view) == [1, 2], "klik w trakcie składu nie zmienia zaznaczenia"
        view._on_object_restore()                     # drugi gest na zbiorze w drodze
        assert msg == [i18n.t("grid.sel.loading_refused")], msg
        assert con.execute("SELECT count(*) FROM frame WHERE object_source = 'user_cleared'"
                           ).fetchone()[0] == 2, "odmowa niczego nie zapisała"
        ts_gestu = con.execute("SELECT ts FROM event WHERE actor LIKE 'user%' "
                               "ORDER BY id DESC LIMIT 1").fetchone()[0]
        repo.set_frame_note(con, frame_ids=[3], body="obok", now="2026-07-03T15:00:00")
        brama.set()
        _czekaj_na_pola(view)
        assert _zaznaczone(view) == [1, 2], "cel gestu wrócił w zaznaczeniu"
        assert view.table.selectionMode() == QAbstractItemView.ExtendedSelection
        assert not view.table.viewport().testAttribute(Qt.WA_SetCursor), "kursor zajętości zdjęty"
        assert str(recepty[-1]) != "", "recepta gestu po przyłożeniu"
        assert len(msg) == 2 and msg[1].startswith(
            i18n.t_plural("grid.sel.object_cleared", 2, assigned=2)), msg
        assert view._recepta_gestu is not None and sorted(view._recepta_gestu[0]) == [1, 2]
        assert view._ts_recepty == ts_gestu, "recepta niesie znacznik gestu, nie późniejszego zdarzenia"
    finally:
        brama.set()
        _zamknij(view, con)


def test_ogon_gestu_mierzy_poza_widokiem_na_zbiorze_przylozonym(qapp, tmp_path, monkeypatch):
    """Ogon gestu leci po przyłożeniu zbioru, więc człon „poza widokiem" jest pomiarem na zbiorze,
    który widać: przy facecie `Obiekt=NGC6960` cofnięcie wypycha cel z widoku (2 z 2 poza widokiem).

    Falsyfikator: licz człon zaraz po zleceniu (przed przyłożeniem) → na starym zbiorze cel jest
    na ekranie, człon milczy."""
    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        view._on_facet_change({"object": {"in": [[5, "NGC6960"]]}})
        _czekaj_na_pola(view)
        assert view.model.rowCount() == 3
        view._przywroc_zaznaczenie([1, 2])
        msg = []
        view.status_message.connect(msg.append)
        view._on_object_clear()
        _czekaj_na_pola(view)
        assert view.model.rowCount() == 1
        assert msg[-1].endswith(i18n.t("grid.sel.out_of_view", n=2)), msg
        assert sorted(view._cel_gestu) == [1, 2], "recepta odsłonięcia odda cel w zaznaczeniu"
    finally:
        _zamknij(view, con)


def test_porazka_skladu_w_tle_czeka_na_edytor_i_nie_zatwierdza_polowy_wpisu(qapp, tmp_path,
                                                                            monkeypatch):
    """AR-83: skład w tle pada RAZ (błąd SQL w workerze), gdy edytor komórki jest otwarty z połową
    wpisu. Ponowienie (nowy bieg workera, AR-302) rusza od razu, a jego WYNIK czeka na zamknięcie edytora
    jak każdy wynik udany (AR-313): edytor żyje, w szufladzie nic, a po dokończeniu wpisu Enterem ląduje
    pełny wpis i dopiero wtedy zbiór przykłada się z ponowionego biegu - wątek GUI nie liczy składu ani razu.

    Falsyfikatory: przeładowanie synchroniczne w `_on_zbior_failed` (`refresh()`) - reset modelu domyka
    edytor z zapisem, w szufladzie „EQ”, a skład liczy wątek GUI; `_on_zbior_done` bez czekania na edytor -
    przyłożenie wyniku ponowienia domyka edytor w połowie wpisu."""
    import sqlite3
    from PySide6.QtTest import QTest
    from horreum import writeback
    from test_gui_drogi_reki import _baza_z_fitsem, _otworz_edytor
    view, con = _widok_w_tle(_baza_z_fitsem(tmp_path, "porazka"))
    view._writeback_async = False
    try:
        przylozone = _szpieg_przylozen(monkeypatch)
        glowny = threading.get_ident()
        prawdziwe = queries.cards_pivot
        porazki, na_glownym = [], []

        def _cp(c, ids, kws):
            if threading.get_ident() == glowny:
                na_glownym.append(1)
            elif not porazki:
                porazki.append(1)
                raise sqlite3.OperationalError("awaria składu w tle")
            return prawdziwe(c, ids, kws)
        monkeypatch.setattr(queries, "cards_pivot", _cp)
        idx, ed, inny = _otworz_edytor(qapp, view, "TELESCOP")
        ed.wartosc.selectAll()
        QTest.keyClicks(ed.wartosc, "EQ")
        view._on_facet_change({})
        _czekaj(lambda: view._zbior_worker is None and porazki, "skład w tle nie skończył")
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert view.table.indexWidget(idx) is ed, "edytor żyje mimo porażki składu"
        assert przylozone == [] and view._zbior_w_drodze(), "przeładowanie czeka na edytor"
        assert view._pending_count() == 0, "nic nie zatwierdzone w połowie"
        QTest.keyClicks(ed.wartosc, "6")
        QTest.keyClick(ed.wartosc, Qt.Key_Return)
        _czekaj(lambda: not view._zbior_w_drodze() and view._zbior_worker is None,
                "ponowienie po zamknięciu edytora nie przyłożyło zbioru")
        (w,) = writeback.pending_for_run(con, view._run_id)
        assert (w["keyword"], w["new_value"]) == ("TELESCOP", "EQ6")
        assert len(przylozone) >= 1 and na_glownym == [], (przylozone, na_glownym)
    finally:
        _zamknij(view, con)


def test_menu_tabeli_i_zostaw_wersje_odmawiaja_nad_zbiorem_w_drodze(qapp, tmp_path, monkeypatch):
    """Prawy klik poza zaznaczeniem, gdy zbiór jest w drodze: `NoSelection` nie przestawia
    zaznaczenia na wiersz pod kursorem, więc pozycje menu liczyłyby stan starego zaznaczenia
    („Zostaw tę wersję" kopiowała ścieżki wersji wskazanej do zostawienia). Menu nie powstaje,
    schowek nietknięty, a slot gestu (druga linia) odmawia tak samo.

    Falsyfikator: zdejmij odmowę z `_on_table_menu` → menu otwarte nad starym zaznaczeniem."""
    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        view.resize(1200, 600)
        view.show()
        QApplication.processEvents()
        view._przywroc_zaznaczenie([1])
        schowek = QApplication.clipboard()
        schowek.setText("przed")
        msg = []
        view.status_message.connect(msg.append)
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        view._on_columns([])
        assert wszedl.wait(_BEZPIECZNIK_S) and view._zbior_w_drodze()
        wiersz_3 = next(i for i, r in enumerate(view.model._rows) if r.get("frame_id") == 3)
        view._on_table_menu(view.table.visualRect(view.model.index(wiersz_3, 0)).center())
        QApplication.processEvents()
        assert not view._menu_tabeli.isVisible(), "menu nad zbiorem w drodze nie powstaje"
        view._on_keep_version()
        assert msg == [i18n.t("grid.sel.loading_refused")] * 2, msg
        assert schowek.text() == "przed" and _zaznaczone(view) == [1]
    finally:
        brama.set()
        _zamknij(view, con)


def test_ogon_starszego_gestu_nie_nadpisuje_werdyktu_panelu_rodowodu(qapp, tmp_path, monkeypatch):
    """Żeton gestu: ogon gestu A (zbiór w drodze) nie nadpisuje zdania, recepty ani zaznaczenia
    gestu, który padł po nim - tu werdyktu panelu Rodowód (panel gaśnie na czas składu, ale slot
    wołany wprost to druga linia). Po przyłożeniu zostaje zdanie i recepta werdyktu.

    Falsyfikator: zdejmij sprawdzenie żetonu z `_ogon_gestu` → ostatnie zdanie to „zdanie A",
    a recepta - ta z gestu A."""
    from test_gui_rodowod_tabela import _seed
    from horreum.gui import grid_model
    path = str(tmp_path / "r.db")
    c = db.open_db(path)
    _seed(c)
    c.close()
    view, con = _widok_w_tle(path)
    try:
        view.resize(1400, 900)
        view.show()
        QApplication.processEvents()
        view._przywroc_zaznaczenie([10])
        view._toggle_panel("lineage")
        view._date_timer.stop()
        view._refresh_lineage()
        assert view.lineage_bar.integration_id() == 5
        msg = []
        view.status_message.connect(msg.append)
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        view._po_gescie_zapisu("zdanie A", [1, 2])          # gest A - ogon czeka na przyłożenie
        assert wszedl.wait(_BEZPIECZNIK_S) and view._zbior_w_drodze()
        assert view.lineage_bar._busy, "panel Rodowód gaśnie na czas składu"
        view._on_lineage_judged([1], True)                  # nowszy gest
        werdykt = i18n.t("grid.lin.judged_excluded", n=1)
        assert msg[-1] == werdykt
        brama.set()
        _czekaj_na_pola(view)
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert "zdanie A" not in msg and msg[-1] == werdykt, msg
        assert view._recepta_gestu == ((10,), grid_model._ODWROT_WERDYKTU)
        assert _zaznaczone(view) == [10], "zaznaczenie werdyktu, nie celu gestu A"
        assert not view.lineage_bar._busy
    finally:
        brama.set()
        _zamknij(view, con)


@pytest.mark.parametrize("szuflada", ["makro", "nazwy"])
def test_ogon_starszego_gestu_nie_nadpisuje_odrzucenia_szuflady(qapp, tmp_path, monkeypatch,
                                                                szuflada):
    """Żeton gestu przy „Odrzuć" w szufladzie (makro i nazwy plików): gest A zleca skład w tle, a
    odrzucenie pada, zanim zbiór dojedzie. Po przyłożeniu zostaje zdanie odrzucenia, a ogon gestu A
    nie stawia swojej recepty jako ostatniej - ta sama klasa, co werdykt panelu Rodowód.

    Falsyfikator: zdejmij `_podbij_zeton()` z `_on_reject` / `_on_reject_rename` → ostatnie zdanie
    to „zdanie A", a recepta - ta z gestu A."""
    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        if szuflada == "makro":
            view._run_id, slot, klucz = "przebieg-makra", view._on_reject, "grid.wb.rejected"
        else:
            view._rename_run_id, slot, klucz = ("przebieg-nazw", view._on_reject_rename,
                                                "grid.rename.rejected")
        msg = []
        view.status_message.connect(msg.append)
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        view._po_gescie_zapisu("zdanie A", [1, 2])          # gest A - ogon czeka na przyłożenie
        assert wszedl.wait(_BEZPIECZNIK_S) and view._zbior_w_drodze()
        slot()                                              # „Odrzuć" w trakcie składu
        odrzucenie = i18n.t_plural(klucz, 0)               # wpis mnogi (AR-226)
        assert msg[-1] == odrzucenie
        brama.set()
        _czekaj_na_pola(view)
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert "zdanie A" not in msg and msg[-1] == odrzucenie, msg
        assert view._recepta_gestu is None, "recepta gestu A po odrzuceniu"
    finally:
        brama.set()
        _zamknij(view, con)


def test_recepta_odslaniania_oddaje_cel_w_zaznaczeniu_po_skladzie_w_tle(qapp, tmp_path,
                                                                        monkeypatch):
    """Klik członu odsłonięcia („odsłonisz 2 klatki NGC6960: „× Wyczyść zbiór””) po przeładowaniu,
    które zjadło jednorazowy cel gestu (zmiana kolumn między gestem a klikiem): zbiór składa się
    w tle, a po przyłożeniu cel stoi w zaznaczeniu z kadrem, a następny człon recepty jest czynny.
    Dawniej - cały zbiór, 0 zaznaczonych, „Obiekt → Przywróć…" wygaszone.

    Zmiana kolumn jest przeładowaniem NIE-NAWIGACYJNYM (AR-172), a przy tym przyłożeniu czeka cel
    gestu (klatki 1, 2 - już poza zbiorem). Cel bez klatki w zbiorze ustępuje zaznaczeniu człowieka:
    wraca klik w klatkę 3 (migawka), a cel schodzi (jednorazowy). Cel w zbiorze bije migawkę -
    `test_cel_gestu_bije_migawke_przeladowania`; cel wyrzucony filtrem po przebiegu Dostawy -
    `test_cel_gestu_poza_zbiorem_po_dostawie_ustepuje_zaznaczeniu_czlowieka`.

    Falsyfikator: zdejmij odłożenie celu z `wykonaj_recepte_powrotu` → zaznaczenie puste."""
    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        view.resize(1200, 600)
        view.show()
        view._on_facet_change({"object": {"in": [[5, "NGC6960"]]}})
        _czekaj_na_pola(view)
        view._przywroc_zaznaczenie([1, 2])
        recepty = []
        view.status_recipe.connect(recepty.append)
        view._on_object_clear()
        _czekaj_na_pola(view)
        assert sorted(view._frame_ids) == [3] and _zaznaczone(view) == []
        assert sorted(view._cel_gestu) == [1, 2], "cel czeka na najbliższe przyłożenie"
        _klik_komorki(view, 3, 1)
        view._on_columns([])                               # przeładowanie między gestem a klikiem
        _czekaj_na_pola(view)
        assert _zaznaczone(view) == [3], "cel bez klatki w zbiorze ustępuje zaznaczeniu człowieka"
        assert view._cel_gestu == [], "cel gestu skonsumowany przez to przyłożenie"
        odslon = recepty[-1].czlony[0]
        assert odslon.tekst.startswith("odsłonisz 2 klatki NGC6960"), odslon.tekst
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        odslon.wykonaj()
        assert wszedl.wait(_BEZPIECZNIK_S) and view._zbior_w_drodze(), "odsłonięcie składa się w tle"
        brama.set()
        _czekaj_na_pola(view)
        for _ in range(5):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert _zaznaczone(view) == [1, 2], "cel recepty wrócił w zaznaczeniu"
        assert view.table.currentIndex().row() == min(
            i for i, r in enumerate(view.model._rows) if r.get("frame_id") in (1, 2)), "kadr na celu"
        assert view.sel_bar.btn_object.isEnabled()
        nastepny = recepty[-1].czlony[0]
        assert nastepny.tekst.startswith("przywrócisz") and nastepny.wykonaj is not None, nastepny
    finally:
        brama.set()
        _zamknij(view, con)


def test_zdanie_okna_zmiany_obiektu_czeka_na_przylozenie_zbioru(qapp, tmp_path, monkeypatch):
    """Okno zmiany obiektu zapisało (sygnał `changed`) i zamyka się, gdy zbiór po zapisie składa
    się jeszcze w tle: jego zdanie idzie ogonem po przyłożeniu - wyemitowane od razu przykryłby je
    raport wczytania.

    Falsyfikator: emituj `summary` od razu po `exec` → zdanie pada, zanim zbiór dojedzie."""
    from PySide6.QtCore import QObject, Signal

    class _Okno(QObject):
        changed = Signal()
        busy_changed = Signal(bool)

        def __init__(self):
            super().__init__()
            self.summary = ""

        def exec(self):
            self.changed.emit()
            self.summary = "Zmieniono obiekt 1 klatki"
            return 1

    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        msg = []
        view.status_message.connect(msg.append)
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        view._pokaz_okno_zmiany_obiektu(_Okno(), [1])
        assert wszedl.wait(_BEZPIECZNIK_S) and view._zbior_w_drodze()
        assert msg == [], "zdanie czeka na przyłożenie"
        brama.set()
        _czekaj_na_pola(view)
        assert msg == ["Zmieniono obiekt 1 klatki"], msg
        assert _zaznaczone(view) == [1]
    finally:
        brama.set()
        _zamknij(view, con)


def test_wyjatek_skladu_synchronicznego_nie_zostawia_tabeli_w_drodze(qapp, tmp_path, monkeypatch):
    """Skład synchroniczny pada w trakcie, gdy zbiór był w drodze: tabela wraca do zwykłego stanu
    (zaznaczenie i wyzwalacze edycji), zamiast zostać w `NoSelection` bez przyłożenia, które by to
    zdjęło.

    Falsyfikator: zdejmij `try/finally` z gałęzi synchronicznej `refresh` → `NoSelection` zostaje."""
    from PySide6.QtWidgets import QAbstractItemView
    view, con = _widok_w_tle(_baza_obiektu(tmp_path))
    try:
        brama, wszedl = _brama_na_skladzie(monkeypatch)
        view._on_columns([])
        assert wszedl.wait(_BEZPIECZNIK_S) and view._zbior_w_drodze()
        assert view.table.selectionMode() == QAbstractItemView.NoSelection
        glowny = threading.get_ident()
        w_tle = queries.base_rows

        def _pada(c, ids):
            if threading.get_ident() == glowny:
                raise RuntimeError("awaria składu")
            return w_tle(c, ids)
        monkeypatch.setattr(queries, "base_rows", _pada)
        with pytest.raises(RuntimeError):
            view.refresh()
        assert view.table.selectionMode() == QAbstractItemView.ExtendedSelection
        assert view.table.editTriggers() == view._edit_triggers
        assert not view.table.viewport().testAttribute(Qt.WA_SetCursor)
    finally:
        brama.set()
        _zamknij(view, con)


# ---- liczniki Porządków po geście Zbiorów - w wątku tła (AR-84) ----

def _brama_na_licznikach(monkeypatch):
    """`tasks_state` liczone POZA wątkiem GUI czeka na bramę; zapisuje wątek KAŻDEGO wywołania."""
    brama, wszedl = threading.Event(), threading.Event()
    glowny = threading.get_ident()
    watki = []
    prawdziwe = queries.tasks_state

    def _ts(con):
        watki.append(threading.get_ident())
        if threading.get_ident() != glowny:
            wszedl.set()
            brama.wait(_BEZPIECZNIK_S)
        return prawdziwe(con)
    monkeypatch.setattr(queries, "tasks_state", _ts)
    return brama, wszedl, watki


def _liczba_wiersza(tasks, klucz):
    from horreum.gui import tasks as tasks_mod
    row = next(i for i, (k, _l, _a) in enumerate(tasks_mod._TASKS) if k == klucz)
    return tasks.tasks.item(row).data(rows.SECONDARY)


def test_gest_zbiorow_liczy_liczniki_porzadkow_w_tle(qapp, tmp_path, monkeypatch):
    """Gest Zbiorów (`stan_porzadkow_changed`) nie liczy liczników Porządków na wątku GUI: lista
    i plakietka trzymają stan poprzedni, póki worker liczy (brama), a wynik przykłada slot.

    Falsyfikator: podepnij `stan_porzadkow_changed` pod `tasks.refresh_counts` bez `w_tle` →
    `tasks_state` woła wątek GUI, a gest czeka na bramę (bezpiecznik)."""
    path = _baza_obiektu(tmp_path)
    win = MainWindow(path)
    try:
        grid, tasks = win.grid_view, win.tasks_view
        _czekaj_na_pola(grid)
        # Rachunek montażu liczy się w tle (AR-175) - brama nie może złapać jego biegu.
        _czekaj(lambda: tasks._liczniki_thread is None, "rachunek montażu nie skończył")
        przed = _liczba_wiersza(tasks, "unresolved_lights")
        badge = []
        tasks.counts_changed.connect(badge.append)
        brama, wszedl, watki = _brama_na_licznikach(monkeypatch)
        grid._przywroc_zaznaczenie([1, 2])
        t0 = time.monotonic()
        grid._on_object_clear()
        assert time.monotonic() - t0 < _BEZPIECZNIK_S / 2, "gest nie czekał na liczniki"
        assert wszedl.wait(_BEZPIECZNIK_S), "liczniki ruszyły w tle"
        assert _liczba_wiersza(tasks, "unresolved_lights") == przed and badge == [], \
            "w trakcie - stan poprzedni"
        brama.set()
        _czekaj(lambda: tasks._liczniki_thread is None, "wątek liczników nie skończył")
        _czekaj_na_pola(grid)
        assert watki and threading.get_ident() not in watki, "liczył wątek tła"
        con = db.connect(path)
        try:
            teraz = queries.tasks_state(con)["unresolved_lights"]
        finally:
            con.close()
        assert _liczba_wiersza(tasks, "unresolved_lights") == f"{teraz}  ›" != przed
        assert len(badge) == 1, "plakietka dostała wynik raz"
    finally:
        brama.set()
        win.close()


def test_koniec_przebiegu_liczy_liczniki_w_tle_a_niewidoczna_os_czeka(qapp, tmp_path, monkeypatch):
    """Koniec przebiegu Dostawy (`_odswiez_widoki_po_przebiegu`): liczniki Porządków liczy wątek
    tła (odświeżenie widoków nie czeka na bramę), a niewidoczna kolejka osi obiektu dostaje
    znacznik zamiast przeładowania - przeładuje się przy pokazaniu.

    Falsyfikator: `refresh_counts()` bez `w_tle` w `_odswiez_widoki_po_przebiegu` → odświeżenie
    czeka na bramę (bezpiecznik) i `tasks_state` woła wątek GUI."""
    from horreum.gui.app import ObjectAxisView
    win = MainWindow(_baza_obiektu(tmp_path))
    try:
        tasks = win.tasks_view
        _czekaj_na_pola(win.grid_view)
        _czekaj(lambda: tasks._liczniki_thread is None, "rachunek montażu nie skończył")   # AR-175
        odswiezenia = []
        oryginal = ObjectAxisView.refresh
        monkeypatch.setattr(ObjectAxisView, "refresh",
                            lambda self, **kw: odswiezenia.append(1) or oryginal(self, **kw))
        brama, wszedl, watki = _brama_na_licznikach(monkeypatch)
        win._on_pipeline_running(True)
        t0 = time.monotonic()
        win._on_pipeline_running(False)
        assert time.monotonic() - t0 < _BEZPIECZNIK_S / 2, "odświeżenie nie czekało na liczniki"
        assert wszedl.wait(_BEZPIECZNIK_S), "liczniki ruszyły w tle"
        assert odswiezenia == [] and win.object_view._nieaktualny, "niewidoczna oś czeka"
        brama.set()
        _czekaj(lambda: tasks._liczniki_thread is None, "wątek liczników nie skończył")
        _czekaj_na_pola(win.grid_view)
        assert watki and threading.get_ident() not in watki, "liczył wątek tła"
    finally:
        brama.set()
        win.close()


def test_zaznaczenie_gridu_przezywa_przebieg_dostawy(qapp, tmp_path):
    """Koniec przebiegu Dostawy przeładowuje zbiór gridu w tle; zaznaczenie wraca po `frame_id`
    przy przyłożeniu (przeładowanie nie-nawigacyjne, `przeladuj_z_zaznaczeniem`, AR-172), bo zbiór
    jest ten sam, a reset modelu je zabierał.

    Falsyfikator: gołe `refresh(w_tle=True)` w `_odswiez_widoki_po_przebiegu` → puste."""
    win = MainWindow(_baza_obiektu(tmp_path))
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        grid._przywroc_zaznaczenie([1, 2])
        assert _zaznaczone(grid) == [1, 2]
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)
        _czekaj(lambda: not grid._zbior_w_drodze(), "skład zbioru nie dojechał")
        _czekaj_na_pola(grid)
        assert _zaznaczone(grid) == [1, 2]
    finally:
        win.close()


def test_odczyt_synchroniczny_wyprzedza_wynik_licznikow_w_drodze(qapp, tmp_path, monkeypatch):
    """Wejście w Porządki (odczyt synchroniczny) w trakcie biegu w tle: lista dostaje stan od razu,
    a spóźniony wynik biegu sprzed wejścia NIE jest przykładany drugi raz (mógłby być starszy).

    Falsyfikator: zdejmij `self._liczniki_gen += 1` z `refresh_counts` → dwa przyłożenia."""
    from horreum.gui import tasks as tasks_mod
    win = MainWindow(_baza_obiektu(tmp_path))
    try:
        tasks = win.tasks_view
        _czekaj_na_pola(win.grid_view)
        _czekaj(lambda: tasks._liczniki_thread is None, "rachunek montażu nie skończył")   # AR-175
        przylozenia = []
        oryginal = tasks_mod.TasksView._przyloz_liczniki
        monkeypatch.setattr(tasks_mod.TasksView, "_przyloz_liczniki",
                            lambda self, s, k: przylozenia.append(1) or oryginal(self, s, k))
        brama, wszedl, _ = _brama_na_licznikach(monkeypatch)
        tasks.refresh_counts(w_tle=True)
        assert wszedl.wait(_BEZPIECZNIK_S)
        tasks.refresh_counts()                        # wejście w Porządki
        assert przylozenia == [1]
        brama.set()
        _czekaj(lambda: tasks._liczniki_thread is None, "wątek liczników nie skończył")
        for _ in range(10):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert przylozenia == [1], "wynik biegu sprzed odczytu do kosza"
    finally:
        brama.set()
        win.close()


def test_zamkniecie_okna_w_trakcie_licznikow_zbiera_watek(qapp, tmp_path, monkeypatch):
    """Zamknięcie okna w trakcie liczenia w tle: wątek liczników zebrany przed skasowaniem widoku
    (`zatrzymaj_pola` po nazwie, jak teczki Domu), a wynik nie trafia do listy.

    Falsyfikator: zdejmij `zatrzymaj_pola` z `TasksView` → `QThread` niszczony w biegu (abort)
    albo wątek żyje po zamknięciu."""
    from horreum.gui import tasks as tasks_mod
    win = MainWindow(_baza_obiektu(tmp_path))
    tasks = win.tasks_view
    _czekaj_na_pola(win.grid_view)
    _czekaj(lambda: tasks._liczniki_thread is None, "rachunek montażu nie skończył")   # AR-175
    przylozenia = []
    oryginal = tasks_mod.TasksView._przyloz_liczniki
    monkeypatch.setattr(tasks_mod.TasksView, "_przyloz_liczniki",
                        lambda self, s, k: przylozenia.append(1) or oryginal(self, s, k))
    brama, wszedl, _ = _brama_na_licznikach(monkeypatch)
    tasks.refresh_counts(w_tle=True)
    assert wszedl.wait(_BEZPIECZNIK_S)
    zegar = threading.Timer(0.3, brama.set)          # rachunek bez punktu przerwania - kończy się sam
    zegar.start()
    try:
        win.close()
        assert tasks._liczniki_thread is None and tasks._liczniki_worker is None
        for _ in range(10):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        assert przylozenia == [], "wynik po zamknięciu nie dotknął listy"
    finally:
        zegar.cancel()
        brama.set()


# ---------- AR-164: pierwszy wynik Pól zmienia kolumny i przeładowuje zbiór - zaznaczenie zostaje ----------

def _baza_ze_stosem(tmp_path):
    """`_baza` (lighty 1-3 z kartami) + gotowy obraz 10 z rodowodem z lightów 1 i 2."""
    path = _baza(tmp_path)
    con = db.connect(path)
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (10, 'm10', 'master_light', 'xisf', ?)", (NOW,))
    con.execute("INSERT INTO location (frame_id, volume, path, present) "
                "VALUES (10, 'V', '/a/S/stos.xisf', 1)")
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch) VALUES (5, 10, ?, 0, 0, 0)", (NOW,))
    con.executemany("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by) "
                    "VALUES (5, ?, 'window')", [(1,), (2,)])
    con.commit()
    con.close()
    return path


def _klik_komorki(view, frame_id, kolumna, modyfikator=Qt.NoModifier):
    """Prawdziwy klik myszą w komórkę wiersza klatki `frame_id`, kolumna `kolumna`."""
    from PySide6.QtTest import QTest
    QApplication.processEvents()
    wiersz = next(i for i, r in enumerate(view.model._rows) if r.get("frame_id") == frame_id)
    idx = view.model.index(wiersz, kolumna)
    view.table.scrollTo(idx)
    rect = view.table.visualRect(idx)
    assert rect.isValid() and view.table.viewport().rect().contains(rect.center()), "komórka poza kadrem"
    QTest.mouseClick(view.table.viewport(), Qt.LeftButton, modyfikator, rect.center())
    QApplication.processEvents()


def _klik_listy_panelu(lista, frame_id):
    from PySide6.QtTest import QTest
    QApplication.processEvents()
    it = next(lista.item(i) for i in range(lista.count()) if lista.item(i).data(Qt.UserRole) == frame_id)
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, lista.visualItemRect(it).center())
    QApplication.processEvents()


def _odczekaj_debounce():
    """Debounce panelu daty i rodowodu (150 ms) - realny czas pętli, nie wywołanie slotu."""
    koniec = time.monotonic() + 0.4
    while time.monotonic() < koniec:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.01)


def _widok_z_zaznaczeniem_przed_polami(tmp_path, monkeypatch):
    """Widok gospodarza (wątki tła), pierwszy wynik Pól TRZYMANY bramą, pierwszy skład zbioru
    przyłożony (kolumny jeszcze puste). Zaznaczenie robione myszą: stos 10, potem Ctrl+klik light 3
    w kolumnie 2 - bieżący wiersz NIE jest pierwszym zaznaczonym w kolejności modelu, bieżąca
    kolumna nie jest 0. Panel rodowodu otwarty, w jego liście zaznaczone wejście 2."""
    brama = threading.Event()
    _szpieg(monkeypatch, brama=brama)
    con = db.connect(_baza_ze_stosem(tmp_path))
    view = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    _czekaj(lambda: view._zbior_thread is None and view._zbior_worker is None
            and view._pola_worker is not None, "pierwszy skład zbioru nie dojechał")
    assert view._columns == [] and view._pola is None, "pierwszy wynik Pól jeszcze w drodze"
    view.resize(1400, 800)
    view.show()
    view._toggle_panel("lineage")
    wiersze = {r.get("frame_id"): i for i, r in enumerate(view.model._rows)}
    pierwszy, drugi = sorted((10, 3), key=wiersze.get)       # kolejność modelu
    _klik_komorki(view, pierwszy, 1)
    _klik_komorki(view, drugi, 2, Qt.ControlModifier)
    _odczekaj_debounce()
    _klik_listy_panelu(view.lineage_bar.items, 2)
    return view, con, brama, drugi


def _biezaca(view):
    idx = view.table.currentIndex()
    return view.model._rows[idx.row()].get("frame_id"), view.model._sort_id_for(idx.column())


def test_wynik_pol_zmienia_kolumny_a_zaznaczenie_biezaca_komorka_i_panel_zostaja(qapp, tmp_path,
                                                                                 monkeypatch):
    """AR-164 (wizytacja natywna): pierwszy wynik Pól 2,5-3,3 s po wejściu w Zbiory zmienia kolumny
    i przeładowuje zbiór - reset modelu zdejmował zaznaczenie, a panel rodowodu wracał do „Zaznacz
    w tabeli…". Po przeładowaniu z powodu KOLUMN wracają: zaznaczenie wielu wierszy, bieżący wiersz
    (nie pierwszy zaznaczony) i bieżąca kolumna po znaczeniu, panel rodowodu ze swoim zaznaczeniem.

    Falsyfikator: gołe `refresh(w_tle=True)` w `_zastosuj_pola` zamiast `przeladuj_z_zaznaczeniem`
    → zaznaczenie puste."""
    view, con, brama, drugi = _widok_z_zaznaczeniem_przed_polami(tmp_path, monkeypatch)
    try:
        assert _zaznaczone(view) == [3, 10]
        przed_biezaca = _biezaca(view)
        assert przed_biezaca[0] == drugi and przed_biezaca[1] == view.model._sort_id_for(2)
        przed_panel = view.lineage_bar.head.text()
        assert przed_panel == i18n.t_plural("grid.lin.head", 2, hours="0.0")
        assert view.lineage_bar.selected_frame_ids() == [2]
        kolumn_przed = view.model.columnCount()

        brama.set()
        _czekaj_na_pola(view)
        assert view.model.columnCount() == kolumn_przed + 3, "wynik Pól dołożył kolumny"
        assert _zaznaczone(view) == [3, 10], "zaznaczenie przeżyło przeładowanie z powodu kolumn"
        assert _biezaca(view) == przed_biezaca, "bieżący wiersz i kolumna - te same, nie pierwsze"
        _odczekaj_debounce()
        assert view.lineage_bar.head.text() == przed_panel, "panel nie wrócił do pustego stanu"
        assert view.lineage_bar.selected_frame_ids() == [2]
    finally:
        brama.set()
        _zamknij(view, con)


def test_zmiana_filtra_po_wyniku_pol_nie_przywraca_starego_zaznaczenia(qapp, tmp_path, monkeypatch):
    """Przywrócenie jedzie ze znacznikiem generacji, nie zwykłym `potem`: wynik Pól zleca
    przeładowanie (skład w drodze, brama), człowiek klika facet „light" - nowszy zbiór ma własne
    zaznaczenie (puste po resecie), a zaznaczenie sprzed zmiany filtra NIE wraca, choć light 3 z niego
    należy do nowego zbioru.

    Falsyfikator: w `_zastosuj_zbior` zdejmij porównanie znacznika z generacją
    (`_przeladowanie_z_zaznaczeniem is not None`) → light 3 wraca zaznaczony."""
    view, con, brama, _ = _widok_z_zaznaczeniem_przed_polami(tmp_path, monkeypatch)
    sklad, wszedl = _brama_na_skladzie(monkeypatch)
    try:
        assert _zaznaczone(view) == [3, 10]
        brama.set()                                   # wynik Pól → przeładowanie z powodu kolumn
        _czekaj(wszedl.is_set, "przeładowanie z powodu kolumn nie ruszyło w tle")
        _czekaj(lambda: view._pola_worker is None, "wynik Pól nie dojechał")
        assert view._zbior_w_drodze()
        lw = view.facet_rail._lists["kind"]
        it = next(lw.item(i) for i in range(lw.count())
                  if lw.item(i).data(Qt.UserRole) and lw.item(i).data(Qt.UserRole)[1] == "light")
        from PySide6.QtTest import QTest
        lw.scrollToItem(it)
        QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, lw.visualItemRect(it).center())
        QApplication.processEvents()
        sklad.set()
        _czekaj_na_pola(view)
        _czekaj(lambda: not view._zbior_w_drodze(), "skład po zmianie filtra nie dojechał")
        assert sorted(view._frame_ids) == [1, 2, 3], "zbiór nowego filtra"
        assert _zaznaczone(view) == [], "stara migawka nie wraca po zmianie filtra"
    finally:
        brama.set()
        sklad.set()
        _zamknij(view, con)


# ---------- AR-172: jeden mechanizm zaznaczenia dla przeładowań nie-nawigacyjnych ----------
# Wynik Pól, kolumny ręką, przebieg Dostawy, grupowanie po wersji, gest osi z innego okna: zbiór ten
# sam, a reset modelu zdejmował zaznaczenie. Zlecenie niesie znacznik generacji, migawkę (zaznaczenie,
# bieżąca komórka, wybór w panelu rodowodu) robi przyłożenie (`_zastosuj_zbior`). Kliki prawdziwe
# (`QTest.mouseClick`/`keyClick` na widżecie); na HEAD każdy test z tego bloku padał na asercji
# zaznaczenia albo panelu (sonda fazy 1).

def _klik_przycisku(btn):
    from PySide6.QtTest import QTest
    QTest.mouseClick(btn, Qt.LeftButton)
    QApplication.processEvents()


def _klik_pola(view, keyword):
    """Prawdziwy klik we wskaźnik zaznaczenia wiersza `keyword` panelu Pól - ten sam prostokąt,
    który sprawdza delegat (`SE_ItemViewItemCheckIndicator`)."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
    lst = view.fields.list
    it = next(lst.item(i) for i in range(lst.count()) if lst.item(i).data(Qt.UserRole) == keyword)
    lst.scrollToItem(it)
    QApplication.processEvents()
    opt = QStyleOptionViewItem()
    lst.initViewItemOption(opt)
    opt.rect = lst.visualItemRect(it)
    opt.features |= QStyleOptionViewItem.HasCheckIndicator
    wskaznik = lst.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, lst)
    przed = it.checkState()
    QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, wskaznik.center())
    QApplication.processEvents()
    assert it.checkState() != przed, "klik nie przełączył pola"


def _wybierz_w_combo(combo, dane):
    """Prawdziwy wybór w liście rozwijanej: klik w combo otwiera listę, klik w pozycję `dane`."""
    from PySide6.QtTest import QTest
    QTest.mouseClick(combo, Qt.LeftButton)
    QApplication.processEvents()
    lista = combo.view()
    _czekaj(lista.isVisible, "lista combo się nie otworzyła")
    # Lista combo ignoruje puszczenie przycisku tuż po otwarciu (to puszczenie kliku, który ją
    # otworzył) - okno `doubleClickInterval` realnym czasem pętli, potem klik w pozycję.
    koniec = time.monotonic() + QApplication.doubleClickInterval() / 1000 + 0.1
    while time.monotonic() < koniec:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.01)
    idx = combo.model().index(combo.findData(dane), 0)
    lista.scrollTo(idx)
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, lista.visualRect(idx).center())
    QApplication.processEvents()
    assert combo.currentData() == dane, combo.currentData()


def _baza_kalibracji(tmp_path, *, rodowod=True):
    """Light Ha z przepisem flatu, masterflat Ha (z przepisu) i OIII tej samej kamery - wzór fixture
    `test_gui_kalibrator_reki.kcon` - plus karty dla Pól; oś przepisu i rodowód policzone, więc
    panel lightu ma dwie relacje (dark - luka, flat - powiązany) i żadnej domyślnie zaznaczonej.
    `rodowod=False` - rodowód niepoliczony: flat „nie policzono”, przy nim „Policz teraz”."""
    from horreum.calibration import run_calibration
    from horreum.lineage import run_lineage
    path = str(tmp_path / "k.db")
    con = db.open_db(path)
    con.execute("INSERT INTO camera(id, model_canon, pixel_um, is_mono, created_at) "
                "VALUES (1, 'ASI2600MM', 3.76, 1, ?)", (NOW,))
    con.execute("INSERT INTO telescope(id, telescop_canon, status, created_at) "
                "VALUES (1, 'A140R', 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO config(id, telescope_id, camera_id, label, status, created_at) "
                "VALUES (1, 1, 1, 'A140R x ASI2600MM', 'proposed', ?)", (NOW,))
    for fid, kind, filtr, data, sciezka in (
            (1, "light", "Ha", "2024-06-01T22:00:00", r"X:\L\M31_Ha_0001.fits"),
            (3, "master_flat", "Ha", "2024-05-30T20:00:00", r"X:\C\MF_Ha.xisf"),
            (5, "master_flat", "OIII", "2024-05-01T20:00:00", r"X:\C\MF_OIII.xisf")):
        con.execute("INSERT INTO frame(id, sha1_data, kind, filetype, camera_id, config_id, "
                    "filter_canon, first_seen_at) VALUES (?, ?, ?, 'xisf', 1, 1, ?, ?)",
                    (fid, f"s{fid}", kind, filtr, NOW))
        con.execute("INSERT INTO header(frame_id, raw_json, date_obs, xbinning) "
                    "VALUES (?, '{}', ?, 1)", (fid, data))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, sciezka))
        for kw in ("OBJECT", "EXPTIME"):
            con.execute("INSERT INTO cards (frame_id, keyword, idx, value_raw, value_type) "
                        "VALUES (?, ?, 0, 'x', 'str')", (fid, kw))
    con.commit()
    run_calibration(con, now=NOW)
    if rodowod:
        run_lineage(con, now=NOW)
    con.close()
    return path


def _widok_gospodarza_ze_stosem(tmp_path):
    """Widok z wątkami tła po pierwszym wyniku Pól i jego składzie; kliki: stos 10, Ctrl-klik light 3
    w kolumnie 2, „Rodowód” na pasku, wiersz 2 na liście panelu."""
    con = db.connect(_baza_ze_stosem(tmp_path))
    view = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    _czekaj_na_pola(view)
    view.resize(1400, 800)
    view.show()
    _klik_komorki(view, 10, 1)
    _klik_komorki(view, 3, 2, Qt.ControlModifier)
    _klik_przycisku(view.sel_bar.btn_lineage)
    _odczekaj_debounce()
    _klik_listy_panelu(view.lineage_bar.items, 2)
    assert _zaznaczone(view) == [3, 10] and view.lineage_bar.selected_frame_ids() == [2]
    return view, con


def test_dwa_wyniki_pol_z_rzedu_przy_zbiorze_w_drodze_zaznaczenie_zostaje(qapp, tmp_path,
                                                                          monkeypatch):
    """AR-172 (a): drugi wynik Pól zmienia kolumny, gdy skład po pierwszym jest jeszcze w drodze.
    Dawniej drugie zlecenie (zbiór w drodze → bez migawki) podbijało generację i ogon pierwszego
    milkł - zaznaczenie znikało. Teraz drugie dziedziczy znacznik pierwszego.

    Falsyfikator: w `przeladuj_z_zaznaczeniem` sam warunek `not self._zbior_w_drodze()` (bez
    dziedziczenia) → zaznaczenie puste."""
    view, con, brama, _ = _widok_z_zaznaczeniem_przed_polami(tmp_path, monkeypatch)
    sklad, wszedl = _brama_na_skladzie(monkeypatch)
    try:
        przed_biezaca = _biezaca(view)
        brama.set()                                   # wynik Pól 1 → przeładowanie w drodze
        _czekaj(wszedl.is_set, "przeładowanie po wyniku Pól 1 nie ruszyło")
        _czekaj(lambda: view._pola_worker is None, "wynik Pól 1 nie dojechał")
        assert view._zbior_w_drodze()
        c2 = db.connect(view._db_path)                # Dostawa zdjęła GAIN ze wszystkich kart
        c2.execute("DELETE FROM cards WHERE keyword = 'GAIN'")
        c2.commit()
        c2.close()
        view._zamow_pola()                            # wynik Pól 2 - kolumna GAIN znika w drodze
        _czekaj(lambda: view._pola_worker is None and view._pola_thread is None, "wynik Pól 2")
        assert "GAIN" not in view._columns and view._zbior_w_drodze()
        sklad.set()
        _czekaj_na_pola(view)
        _czekaj(lambda: not view._zbior_w_drodze(), "skład nie dojechał")
        assert "GAIN" not in view.model._keywords
        assert _zaznaczone(view) == [3, 10]
        assert _biezaca(view) == przed_biezaca
        _odczekaj_debounce()
        assert view.lineage_bar.selected_frame_ids() == [2]
    finally:
        brama.set()
        sklad.set()
        _zamknij(view, con)


def test_reczna_kolumna_w_polach_klikiem_zaznaczenie_zostaje(qapp, tmp_path):
    """AR-172 (b): klik w pole kolumny w panelu Pól (`_on_columns`) przeładowywał zbiór gołym
    `refresh` - zaznaczenie, bieżąca komórka i wiersz panelu rodowodu znikały.

    Falsyfikator: `_on_columns` z gołym `refresh(w_tle=True)` → zaznaczenie puste."""
    view, con = _widok_gospodarza_ze_stosem(tmp_path)
    try:
        przed_biezaca = _biezaca(view)
        _klik_pola(view, "GAIN")
        _czekaj(lambda: not view._zbior_w_drodze() and view._zbior_thread is None, "skład")
        assert "GAIN" not in view.model._keywords, "kolumna zdjęta"
        assert _zaznaczone(view) == [3, 10]
        assert _biezaca(view) == przed_biezaca
        _odczekaj_debounce()
        assert view.lineage_bar.selected_frame_ids() == [2]
    finally:
        _zamknij(view, con)


def test_noc_panelu_przezywa_wynik_pol(qapp, tmp_path, monkeypatch):
    """AR-172 (c): panel w trybie propozycji wracał po przeładowaniu na noc mastera
    (`_set_candidates` stawia pozycję 0), więc wiersz zaznaczony na innej nocy przepadał.

    Falsyfikator: zdejmij `select_night` z `_refresh_lineage` → noc 2023-04-21, lista pusta."""
    from PySide6.QtTest import QTest
    from test_gui_grid import _seed_stos_z_kandydatami
    brama = threading.Event()
    _szpieg(monkeypatch, brama=brama)
    path = _baza(tmp_path)
    c = db.connect(path)
    _seed_stos_z_kandydatami(c)                       # stos 10, noce 2023-04-21 (20, 21) i -25 (22)
    c.close()
    con = db.connect(path)
    view = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    try:
        _czekaj(lambda: view._zbior_thread is None and view._zbior_worker is None
                and view._pola_worker is not None, "pierwszy skład zbioru nie dojechał")
        view.resize(1400, 800)
        view.show()
        _klik_komorki(view, 10, 1)
        _klik_przycisku(view.sel_bar.btn_lineage)
        _odczekaj_debounce()
        bar = view.lineage_bar
        assert bar.combo_night.currentData() == "2023-04-21"
        QTest.keyClick(bar.combo_night, Qt.Key_Down)
        QApplication.processEvents()
        assert bar.combo_night.currentData() == "2023-04-25"
        _klik_listy_panelu(bar.items, 22)
        brama.set()                                   # wynik Pól → przeładowanie z powodu kolumn
        _czekaj_na_pola(view)
        _odczekaj_debounce()
        assert len(view.model._keywords) == 3, "wynik Pól przeładował zbiór"
        assert _zaznaczone(view) == [10]
        assert bar.combo_night.currentData() == "2023-04-25"
        assert bar.selected_frame_ids() == [22]
    finally:
        brama.set()
        _zamknij(view, con)


def test_relacja_kalibracji_przezywa_przebieg_dostawy(qapp, tmp_path):
    """AR-172 (c) na drodze Dostawy: gospodarz po przebiegu woła `refresh_lineage_panel()` zaraz po
    zleceniu przeładowania - panel przebudowany bez stanu tracił wybraną relację osi kalibracji
    JESZCZE W TRAKCIE składu, a przyłożenie nie miało jej skąd wziąć.

    Falsyfikator: `refresh_lineage_panel` bez `_stan_panelu()` → relacja `None`."""
    win = MainWindow(_baza_kalibracji(tmp_path))
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        win.show_classic()
        win.resize(1500, 950)
        win.show()
        QApplication.processEvents()
        _klik_komorki(grid, 1, 1)
        _klik_przycisku(grid.sel_bar.btn_lineage)
        _odczekaj_debounce()
        bar = grid.lineage_bar
        assert bar.selected_relation() is None, "bez wyboru ręki - nic zaznaczone"
        relacje = [r["relation"] for r in bar._relacje]
        _klik_listy_panelu(bar.items, bar.items.item(relacje.index("flat")).data(Qt.UserRole))
        assert bar.selected_relation() == "flat"
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)
        assert bar.selected_relation() == "flat", "w trakcie składu"
        _czekaj(lambda: not grid._zbior_w_drodze() and grid._zbior_thread is None, "skład")
        _czekaj_na_pola(grid)
        _odczekaj_debounce()
        assert _zaznaczone(grid) == [1]
        assert bar.selected_relation() == "flat"
    finally:
        win.close()


def test_dostawa_potem_zmiana_filtra_stare_zaznaczenie_nie_wraca(qapp, tmp_path, monkeypatch):
    """AR-172 (d): ogon Dostawy był zwykłym `potem` - przechodził na nowsze zlecenie, więc po zmianie
    filtra przed końcem składu stare zaznaczenie wracało na zbiorze, którego nikt o nie nie prosił.

    Falsyfikator: w `_zastosuj_zbior` znacznik bez porównania z generacją → `[1, 2]`."""
    from PySide6.QtTest import QTest
    win = MainWindow(_baza_obiektu(tmp_path))
    sklad = None
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        win.show_classic()
        win.resize(1500, 950)
        win.show()
        QApplication.processEvents()
        _klik_komorki(grid, 1, 1)
        _klik_komorki(grid, 2, 1, Qt.ControlModifier)
        assert _zaznaczone(grid) == [1, 2]
        sklad, wszedl = _brama_na_skladzie(monkeypatch)
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)
        _czekaj(wszedl.is_set, "skład po Dostawie nie ruszył w tle")
        assert grid._zbior_w_drodze()
        lw = grid.facet_rail._lists["kind"]
        it = next(lw.item(i) for i in range(lw.count())
                  if lw.item(i).data(Qt.UserRole) and lw.item(i).data(Qt.UserRole)[1] == "light")
        lw.scrollToItem(it)
        QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, lw.visualItemRect(it).center())
        QApplication.processEvents()
        sklad.set()
        _czekaj(lambda: not grid._zbior_w_drodze() and grid._zbior_thread is None, "skład")
        _czekaj_na_pola(grid)
        assert sorted(grid._frame_ids) == [1, 2, 3], "zbiór nowego filtra"
        assert _zaznaczone(grid) == []
    finally:
        if sklad is not None:
            sklad.set()
        win.close()


def test_porazka_skladu_po_wyniku_pol_nie_gubi_zaznaczenia(qapp, tmp_path, monkeypatch):
    """Skład w tle po wyniku Pól pada RAZ - ponowienie TEGO SAMEGO zlecenia w nowym biegu workera
    (`_on_zbior_failed` → `_ponow_zbior`, AR-302) zostaje na tej samej generacji, więc znacznik
    przeładowania nie-nawigacyjnego pasuje i zaznaczenie wraca jak po udanym składzie (dawniej gubiła
    je i AR-164).

    Falsyfikator: ponowienie, które podbija generację (nowe zlecenie `refresh`) bez przeniesienia
    znacznika → zaznaczenie puste."""
    view, con, brama, _ = _widok_z_zaznaczeniem_przed_polami(tmp_path, monkeypatch)
    prawdziwe = queries.base_rows
    porazki = []

    def _pada_w_tle(c, ids):
        if not porazki:
            porazki.append(1)
            raise RuntimeError("awaria składu w tle")
        return prawdziwe(c, ids)
    monkeypatch.setattr(queries, "base_rows", _pada_w_tle)
    try:
        przed_biezaca = _biezaca(view)
        brama.set()
        _czekaj_na_pola(view)
        _czekaj(lambda: not view._zbior_w_drodze(), "ponowienie nie przyłożyło zbioru")
        assert porazki == [1], "skład padł raz i został ponowiony"
        assert view.model.columnCount() == len(grid_mod.BASE_COLS) + 3, "zbiór z kolumnami Pól"
        assert _zaznaczone(view) == [3, 10]
        assert _biezaca(view) == przed_biezaca
    finally:
        brama.set()
        _zamknij(view, con)


def test_cel_gestu_bije_migawke_przeladowania(qapp, tmp_path):
    """Cel gestu (FC-2) i migawka przeładowania nie-nawigacyjnego przy tym samym przyłożeniu: cel
    jest nowszą, jawną intencją - stoi w zaznaczeniu zamiast migawki i schodzi (jednorazowy).

    Falsyfikator: odłóż migawkę PO celu w `_zastosuj_zbior` → zaznaczenie z migawki."""
    view, con = _widok_gospodarza_ze_stosem(tmp_path)
    try:
        view._cel_gestu = [1]                         # cel gestu czeka na przyłożenie (wzór `:402`)
        _klik_pola(view, "GAIN")
        _czekaj(lambda: not view._zbior_w_drodze() and view._zbior_thread is None, "skład")
        assert _zaznaczone(view) == [1] and view._cel_gestu == []
    finally:
        _zamknij(view, con)


def test_grupowanie_po_wersji_klikiem_zaznaczenie_zostaje(qapp, tmp_path):
    """Grupowanie „Wersja stosu” przeładowuje zbiór (grupy wersji liczy skład), ale zbioru nie
    zmienia - to widok, nie nawigacja (AR-172, kontrakt „wszystkich” przeładowań nie-nawigacyjnych).

    Falsyfikator: `_on_group` z gołym `refresh(w_tle=True)` → zaznaczenie puste."""
    view, con = _widok_gospodarza_ze_stosem(tmp_path)
    try:
        przed_biezaca = _biezaca(view)
        _wybierz_w_combo(view.combo_group, grid_mod._GRUPA_WERSJI)
        _czekaj(lambda: not view._zbior_w_drodze() and view._zbior_thread is None, "skład")
        assert any("_group" in r for r in view.model._rows), "belki grup wersji stoją"
        assert _zaznaczone(view) == [3, 10]
        assert _biezaca(view) == przed_biezaca
    finally:
        _zamknij(view, con)


def test_gest_osi_z_raportu_dostawy_nie_zdejmuje_zaznaczenia_w_zbiorach(qapp, tmp_path):
    """Gest osi obiektu z raportu Dostawy (`object_axis_changed`) przeładowuje grid - zbiór ten sam,
    więc zaznaczenie w Zbiorach zostaje (AR-172).

    Falsyfikator: podłączenie `grid.refresh(w_tle=True)` zamiast `przeladuj_z_zaznaczeniem` → puste."""
    win = MainWindow(_baza_obiektu(tmp_path))
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        win.show_classic()
        win.resize(1500, 950)
        win.show()
        QApplication.processEvents()
        _klik_komorki(grid, 1, 1)
        _klik_komorki(grid, 3, 1, Qt.ControlModifier)
        win.przyjmij_view.object_axis_changed.emit()
        _czekaj(lambda: not grid._zbior_w_drodze() and grid._zbior_thread is None, "skład")
        _czekaj_na_pola(grid)
        assert _zaznaczone(grid) == [1, 3]
    finally:
        win.close()


def test_cel_gestu_poza_zbiorem_po_dostawie_ustepuje_zaznaczeniu_czlowieka(qapp, tmp_path):
    """Cel gestu „Policz teraz” (light) i migawka przeładowania po przebiegu Dostawy przy tym samym
    przyłożeniu, a przeliczenie wyrzuciło light z aktywnego filtra (facet „Ha”), master z migawki
    został. Cel bez klatki w zbiorze ustępuje zaznaczeniu człowieka - migawka wraca CAŁA
    (zaznaczony master, bieżąca komórka na nim), a cel schodzi. Pusty ekran zgubiłby wybór
    człowieka, którego AR-172 broni.

    Falsyfikator: rozstrzyganie samą obecnością celu (`if cel:` … `elif migawka`) → zaznaczenie puste."""
    from PySide6.QtTest import QTest
    path = _baza_kalibracji(tmp_path, rodowod=False)
    win = MainWindow(path)
    try:
        grid = win.grid_view
        _czekaj_na_pola(grid)
        win.show_classic()
        win.resize(1500, 950)
        win.show()
        QApplication.processEvents()
        lw = grid.facet_rail._lists["filter"]
        it = next(lw.item(i) for i in range(lw.count())
                  if lw.item(i).data(Qt.UserRole) and lw.item(i).data(Qt.UserRole)[1] == "Ha")
        lw.scrollToItem(it)
        QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, lw.visualItemRect(it).center())
        _czekaj(lambda: not grid._zbior_w_drodze() and grid._zbior_thread is None, "skład facetu")
        assert sorted(grid._frame_ids) == [1, 3], "facet Ha: light i master Ha"
        _klik_komorki(grid, 1, 1)
        _klik_komorki(grid, 3, 1, Qt.ControlModifier)
        przed_biezaca = _biezaca(grid)
        assert przed_biezaca[0] == 3, "bieżąca komórka na masterze (ostatni klik)"
        _klik_przycisku(grid.sel_bar.btn_lineage)
        _odczekaj_debounce()
        bar = grid.lineage_bar
        etapy = []
        grid.run_stage_fn = lambda etap: etapy.append(etap) or None
        assert not bar.btn_cal_count.isHidden(), "flat nieliczony - „Policz teraz” stoi"
        _klik_przycisku(bar.btn_cal_count)
        assert etapy == ["lineage"] and grid._cel_gestu == [1]
        c2 = db.connect(path)                         # przebieg przepisał light na inny filtr
        c2.execute("UPDATE frame SET filter_canon = 'OIII' WHERE id = 1")
        c2.commit()
        c2.close()
        win._on_pipeline_running(True)
        win._on_pipeline_running(False)
        _czekaj(lambda: not grid._zbior_w_drodze() and grid._zbior_thread is None, "skład")
        _czekaj_na_pola(grid)
        assert sorted(grid._frame_ids) == [3], "light wypadł z filtra Ha"
        assert _zaznaczone(grid) == [3], "cel bez klatki w zbiorze ustępuje zaznaczeniu człowieka"
        assert _biezaca(grid) == przed_biezaca, "migawka cała - także bieżąca komórka"
        assert grid._cel_gestu == []
    finally:
        win.close()


# ============================================================ AR-198: błąd bazy klasą w workerach odczytu

_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_pola_i_sklad_zbioru_mowia_klasa_bazy_w_jezyku_UI(qapp, tmp_path, lang):
    """Pokrycie Pól i skład zbioru czytają WYŁĄCZNIE bazę (zmierzone: 0 wywołań systemu plików):
    PRAWDZIWY błąd SQLite (plik bazy niedostępny, SQLITE_CANTOPEN) idzie do `grid.py` zdaniem klasy
    w języku UI, bez surowego `OperationalError: unable to open database file`. Falsyfikator:
    worker z `f"{type(exc).__name__}: {exc}"`."""
    from horreum.gui.grid_workers import PolaWorker, ZbiorWorker
    odpiety = str(tmp_path / "odpiety" / "p.db")
    i18n.set_lang(lang)
    try:
        zdanie = i18n.t("objchg.item.db_unavailable", db_code="SQLITE_CANTOPEN")
        for w in (PolaWorker(1, None, db_path=odpiety), ZbiorWorker(1, None, odpiety)):
            bledy = []
            w.failed.connect(lambda _gen, msg: bledy.append(msg))
            w.run()
            assert bledy == [zdanie], (type(w).__name__, bledy)
        if lang == "en":
            assert not set(zdanie) & _POLSKIE, zdanie
    finally:
        i18n.set_lang("pl")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_liczniki_porzadkow_druga_porazka_mowi_klasa_zamiast_wyjatku(qapp, tmp_path, lang, monkeypatch):
    """Liczniki Porządków w tle padają (plik bazy niedostępny), slot ponawia rachunek w NOWYM biegu
    workera (AR-302) i ten też pada PRAWDZIWYM błędem SQLite (plik nie jest bazą): zamiast wyjątku ze
    slotu i plakietki zamrożonej bez słowa - wiersz błędu nad listą mówi klasą DRUGIEJ porażki w języku
    UI, ze szczegółem; udany rachunek go gasi. Wątek GUI nie liczy liczników ani razu. Droga
    produkcyjna: `refresh_counts(w_tle=True)` → `QThread` → sygnał → slot → nowy bieg.
    Falsyfikator: ponowienie synchroniczne (`refresh_counts()` w slocie) - rachunek na wątku GUI."""
    from horreum.gui import tasks as tasks_mod
    i18n.set_lang(lang)
    win = MainWindow(_baza_obiektu(tmp_path))
    smieci = tmp_path / "smieci.db"
    smieci.write_bytes(b"to nie jest baza" * 512)
    tasks = win.tasks_view
    prawdziwa_sciezka = tasks._db_path
    glowny = threading.get_ident()
    na_glownym = []
    prawdziwy_stan = tasks_mod._stan_licznikow

    def _stan(con):
        if threading.get_ident() == glowny:
            na_glownym.append(1)
        return prawdziwy_stan(con)
    try:
        _czekaj_na_pola(win.grid_view)
        _czekaj(lambda: tasks._liczniki_thread is None, "rachunek montażu nie skończył")   # AR-175
        monkeypatch.setattr(tasks_mod, "_stan_licznikow", _stan)
        tasks._db_path = str(tmp_path / "odpiety" / "obj.db")
        tasks.refresh_counts(w_tle=True)
        assert tasks._liczniki_thread is not None
        # Pierwszy bieg zna już ścieżkę odpiętą; ponowienie weźmie ścieżkę z chwili startu - plik śmieci.
        tasks._db_path = str(smieci)
        _czekaj(lambda: tasks._liczniki_thread is None and not tasks.blad_licznikow.isHidden(),
                "druga porażka liczników nie doszła do wiersza błędu")
        assert na_glownym == [], "rachunek liczników na wątku GUI"
        zdanie = i18n.t("tasks.counts_failed",
                        msg=i18n.t("objchg.item.db_damaged", db_code="SQLITE_NOTADB"))
        assert tasks.blad_licznikow.text() == zdanie
        assert tasks.blad_licznikow.toolTip() == zdanie + "\n" + i18n.t(
            "wb.os_detail_tip", detail="DatabaseError: file is not a database")
        if lang == "en":
            assert not set(zdanie) & _POLSKIE, zdanie
        tasks._db_path = prawdziwa_sciezka
        tasks.refresh_counts()
        assert tasks.blad_licznikow.isHidden() and tasks.blad_licznikow.text() == ""
    finally:
        tasks._db_path = prawdziwa_sciezka
        win.close()
        i18n.set_lang("pl")


def test_worker_licznikow_niesie_powod_z_kodem(tmp_path):
    """`_LicznikiWorker` emituje POWÓD (klasa bazy z kodem), nie tekst - slot ma z czego złożyć
    zdanie w języku UI. Falsyfikator: `Signal(int, str)` / f-string `Typ: opis`."""
    from horreum.gui.tasks import _LicznikiWorker
    from horreum.item_reasons import PowodPozycji
    w = _LicznikiWorker(7, str(tmp_path / "odpiety" / "x.db"))
    bledy = []
    w.failed.connect(lambda gen, powod: bledy.append((gen, powod)))
    w.run()
    ((gen, powod),) = bledy
    assert gen == 7 and isinstance(powod, PowodPozycji) and powod.code == "db_unavailable", powod


def test_wejscie_w_porzadki_i_gest_w_tle_na_bazie_ktora_nie_jest_baza_mowia_zdaniem(qapp, tmp_path):
    """Każda droga rachunku liczników mówi zdaniem, nie wyjątkiem ze slotu: wejście w Porządki
    (`odswiez_przy_wejsciu` - skrót po odcisku też czyta bazę) i gest Zbiorów w tle (odcisk biegu
    czytany na połączeniu okna) na PRAWDZIWYM błędzie SQLite (plik nie jest bazą). Po naprawie
    połączenia wejście liczy od nowa mimo niezmienionego odcisku - skrót tylko przy schowanym
    wierszu. Falsyfikator: `refresh_counts` bez łapania albo skrót bez `isHidden()` - wiersz
    zostaje widoczny nad prawdziwą listą."""
    import sqlite3
    win = MainWindow(_baza_obiektu(tmp_path))
    smieci = tmp_path / "smieci.db"
    smieci.write_bytes(b"to nie jest baza" * 512)
    zla = sqlite3.connect(str(smieci))
    tasks = win.tasks_view
    prawdziwe = tasks.con
    try:
        _czekaj_na_pola(win.grid_view)
        _czekaj(lambda: tasks._liczniki_thread is None, "rachunek montażu nie skończył")   # AR-175
        tasks.refresh_counts()                       # odcisk przyłożonego rachunku stoi
        assert tasks._odcisk_licznikow is not None and tasks.blad_licznikow.isHidden()
        zdanie = i18n.t("tasks.counts_failed",
                        msg=i18n.t("objchg.item.db_damaged", db_code="SQLITE_NOTADB"))
        tasks.con = zla
        tasks.odswiez_przy_wejsciu()
        assert not tasks.blad_licznikow.isHidden() and tasks.blad_licznikow.text() == zdanie
        tasks.blad_licznikow.clear()
        tasks.blad_licznikow.setVisible(False)
        tasks.refresh_counts(w_tle=True)             # gest Zbiorów: odcisk biegu na połączeniu okna
        assert tasks._liczniki_thread is None and tasks.blad_licznikow.text() == zdanie
        tasks.con = prawdziwe
        tasks.odswiez_przy_wejsciu()                 # odcisk bez zmian, ale wiersz widoczny - liczy
        assert tasks.blad_licznikow.isHidden() and tasks.blad_licznikow.szczegol() == ""
    finally:
        tasks.con = prawdziwe
        win.close()
        zla.close()


def test_blad_programu_w_rachunku_licznikow_leci_dalej(qapp, tmp_path, monkeypatch):
    """EXPECT: łapany jest wyłącznie błąd bazy albo systemu; błąd programu w rachunku (tu
    `RuntimeError`) nie zostaje zdaniem „lista mówi stan poprzedni” - leci do wołającego.
    Falsyfikator: `except Exception` w `refresh_counts`."""
    from horreum.gui import tasks as tasks_mod
    win = MainWindow(_baza_obiektu(tmp_path))
    try:
        _czekaj_na_pola(win.grid_view)
        _czekaj(lambda: win.tasks_view._liczniki_thread is None, "rachunek montażu nie skończył")   # AR-175

        def _pada(con):
            raise RuntimeError("błąd programu")
        monkeypatch.setattr(tasks_mod, "_stan_licznikow", _pada)
        with pytest.raises(RuntimeError, match="błąd programu"):
            win.tasks_view.refresh_counts()
        assert win.tasks_view.blad_licznikow.isHidden()
    finally:
        win.close()


def test_porazka_skladu_przy_otwartym_edytorze_ponawia_od_razu_wynik_czeka(qapp, tmp_path, monkeypatch):
    """AR-313: porażka składu w tle przy otwartym edytorze komórki nie odkłada ZAMIARU ponowienia - ponowienie
    biegnie od razu w wątku tła, a na edytor czeka już jego WYNIK. Przy wciąż otwartym edytorze: dwa biegi
    w wątku tła (porażka i ponowienie), wynik odłożony; po Enterze przyłożenie bez trzeciego biegu i bez składu
    na wątku GUI. Falsyfikator: odłożenie samego zamiaru (ponowienie dopiero po zamknięciu edytora - jeden bieg
    w tle przed Enterem, odłożony zamiar bez wyniku)."""
    import sqlite3
    from PySide6.QtTest import QTest
    from test_gui_drogi_reki import _baza_z_fitsem, _otworz_edytor
    view, con = _widok_w_tle(_baza_z_fitsem(tmp_path, "ponowienie"))
    view._writeback_async = False
    try:
        przylozone = _szpieg_przylozen(monkeypatch)
        glowny = threading.get_ident()
        prawdziwe = queries.cards_pivot
        biegi_tla, na_glownym = [], []

        def _cp(c, ids, kws):
            if threading.get_ident() == glowny:
                na_glownym.append(1)
                return prawdziwe(c, ids, kws)
            biegi_tla.append(1)
            if len(biegi_tla) == 1:
                raise sqlite3.OperationalError("awaria składu w tle")
            return prawdziwe(c, ids, kws)
        monkeypatch.setattr(queries, "cards_pivot", _cp)
        idx, ed, _inny = _otworz_edytor(qapp, view, "TELESCOP")
        ed.wartosc.selectAll()
        QTest.keyClicks(ed.wartosc, "EQ")
        view._on_facet_change({})
        _czekaj(lambda: view._zbior_worker is None and view._zbior_odlozony is not None,
                "ponowienie w tle nie oddało wyniku przy otwartym edytorze")
        assert view.table.indexWidget(idx) is ed, "edytor żyje"
        assert len(biegi_tla) == 2 and view._zbior_odlozony[1] is not None, (biegi_tla, view._zbior_odlozony)
        assert przylozone == [] and view._pending_count() == 0
        QTest.keyClicks(ed.wartosc, "6")
        QTest.keyClick(ed.wartosc, Qt.Key_Return)
        _czekaj(lambda: not view._zbior_w_drodze() and view._zbior_worker is None, "przyłożenie po Enterze")
        assert len(przylozone) >= 1 and len(biegi_tla) == 2 and na_glownym == [], (biegi_tla, na_glownym)
    finally:
        _zamknij(view, con)


# ======================================================================== AR-327: Porządki - faza przy liście, podpowiedź gestu

def test_faza_przy_tytule_listy_do_pierwszego_wyniku_rachunku(qapp, tmp_path, monkeypatch):
    """AR-327: do pierwszego wyniku rachunku liczników w tle etykieta fazy „Liczę Porządki…” stoi przy tytule
    listy (nie tylko na pasku statusu, ~1870 px dalej - zmierzone natywnie); wynik ją chowa, porażka też (mówi
    wiersz błędu). Kontrakt stanowy (widoczność, tekst) - geometrię mierzy sonda natywna.
    Falsyfikatory: brak schowania po wyniku; etykieta widoczna bez serii biegów (tryb inline)."""
    import sqlite3
    path = _baza_obiektu(tmp_path)
    brama, wszedl, _watki = _brama_na_licznikach(monkeypatch)
    win = MainWindow(path)
    try:
        tasks = win.tasks_view
        assert wszedl.wait(_BEZPIECZNIK_S), "rachunek montażu nie ruszył w tle"
        assert not tasks.faza_licznikow.isHidden()
        assert tasks.faza_licznikow.text() == i18n.t("busy.counting_tasks")
        brama.set()
        _czekaj(lambda: tasks._liczniki_thread is None and tasks.ma_rachunek(), "rachunek montażu")
        assert tasks.faza_licznikow.isHidden()
        tasks.refresh_counts(w_tle=True)                  # kolejna seria po wyniku - faza nie wraca
        _czekaj(lambda: tasks._liczniki_thread is None, "druga seria")
        assert tasks.faza_licznikow.isHidden()
    finally:
        brama.set()
        win.close()

    def _pada(con):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(queries, "tasks_state", _pada)
    win = MainWindow(path)
    try:
        tasks = win.tasks_view
        _czekaj(lambda: tasks._liczniki_thread is None and not tasks.blad_licznikow.isHidden(), "porażka")
        assert tasks.faza_licznikow.isHidden()
    finally:
        win.close()
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win = MainWindow(path)                                # inline: rachunek w montażu, serii nie ma
    try:
        assert win.tasks_view.faza_licznikow.isHidden()
    finally:
        win.close()


def test_podpowiedz_wiersza_bajtow_nazywa_przycisk_dostawy(qapp, tmp_path, monkeypatch):
    """AR-327: podpowiedź wiersza „Nagłówek z bajtem spoza ASCII” przy kopiach niezbadanych
    nazywa PRZYCISK Dostawy jego napisem - tym samym, który stoi na `btn_copy_facts` tej bazy (fakty i bajty
    naraz: „Zbierz fakty kopii (N) i sprawdź bajty (M)”), nie etap „Fakty kopii”. Falsyfikatory: parametr `etap`
    (stan sprzed AR-327); napis liczony inaczej niż w Dostawie."""
    from test_gui_pipeline import _kopie_bez_faktow
    from horreum.gui.app import NAV_DOSTAWA
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    db_path, _kat = _kopie_bez_faktow(tmp_path)
    win = MainWindow(db_path)
    try:
        tip = _wiersz_tip(win.tasks_view, "header_nonprintable_frames")
        win._show_view(NAV_DOSTAWA)
        gest = win.pipeline_view.btn_copy_facts.text()
        assert gest and f"„{gest}”" in tip, (gest, tip)
        assert i18n.t("pipeline.stage.copy_facts") not in tip
    finally:
        win.close()


def _wiersz_tip(tasks, klucz):
    from horreum.gui import tasks as tasks_mod
    row = next(i for i, (k, _l, _a) in enumerate(tasks_mod._TASKS) if k == klucz)
    return tasks.tasks.item(row).toolTip()
