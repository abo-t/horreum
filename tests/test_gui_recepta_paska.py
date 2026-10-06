"""Recepta paska stanu, która WYKONUJE powrót (FH-2e), i jej sąsiedztwo: odwracalność wycofania
klatki (FH-6) i przywrócenia przypisania (FH-9), elizja członem, nie ogonem (FH-8), kadr po
recepcie (FH-11), raport osi stanowisk po przebiegu Dostawy (AR-43) i komunikat planera bez
stanowiska (AR-48).

Testy STERUJĄ realnym oknem Qt (offscreen). `importorskip` na poziomie modułu: bez PySide6 plik
się POMIJA, więc pełny pytest bez Qt zostaje prawdziwy."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from horreum import db
from horreum.gui import grid as grid_mod, i18n

NOW = "2026-07-03T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _baza(path, n=4):
    """`n` lightów ze ŚCIEŻKI (źródło słabe) przypisanych do NGC6960 - każda klatka ma plik."""
    con = db.open_db(str(path))
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (5,'NGC6960','NGC','deep_sky')")
    for i in range(1, n + 1):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, "
                    "object_id, object_source) VALUES (?, 'light', 'raw', ?, ?, 5, 'path')",
                    (i, f"sha{i}", NOW))
        con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (i,))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?,'V',?,1)",
                    (i, rf"R:\ASTRO_\LIGHTS\NGC6960\f{i:04d}.ARW"))
    con.commit()
    return con


@pytest.fixture
def widok(qapp, tmp_path):
    from horreum.gui.grid import FramesView
    con = _baza(tmp_path / "r.db")
    v = FramesView(con, now_fn=lambda: NOW)
    yield v, con
    v.close()
    con.close()


def _zaznacz(view, frame_ids):
    """Zaznacz wiersze po KLATCE, nigdy po indeksie (grid sortuje i grupuje)."""
    from PySide6.QtCore import QItemSelectionModel
    sm = view.table.selectionModel()
    sm.clearSelection()
    chciane = set(frame_ids)
    for i, row in enumerate(view.model._rows):
        if isinstance(row, dict) and row.get("frame_id") in chciane:
            sm.select(view.model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


def _recepty(v):
    zebrane = []
    v.status_recipe.connect(zebrane.append)
    return zebrane


def _widoczne(v):
    return {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}


def _object_id(con, fid):
    return con.execute("SELECT object_id FROM frame WHERE id = ?", (fid,)).fetchone()[0]


# ═════════════════════════ Recepta - wartość (FH-8, FH-2e)


def test_Recepta_jest_zdaniem_i_lista_czlonow_naraz():
    """Zdanie dla czytelników tekstu (podpowiedź, testy), człony dla nośnika (elizja członem,
    wykonawca członu pierwszego). Milczące człony odpadają, goły tekst staje się członem bez
    wykonawcy - pusta recepta to pusty łańcuch, który gasi poprzednią.

    Falsyfikator: sklej człony bez odsiewu pustych → zdanie zaczyna się od separatora."""
    from horreum.gui.grid import CzlonRecepty, Recepta
    r = Recepta([CzlonRecepty("odsłoni je X", print), "", CzlonRecepty("potem Y", None)])
    assert r == "odsłoni je X · potem Y"
    assert [c.tekst for c in r.czlony] == ["odsłoni je X", "potem Y"]
    assert r.czlony[0].wykonaj is print and r.czlony[1].wykonaj is None
    assert Recepta(["goły tekst"]).czlony == (CzlonRecepty("goły tekst", None),)
    assert Recepta([]) == "" and not Recepta([""])


# ═════════════════════════ FH-2e - recepta WYKONUJE, składa się ze STANU


def test_FH2e_recepta_odslania_a_potem_PRZYWRACA_dwoma_kliknieciami(widok):
    """Scenariusz, który do FH-2e kończył się w pół drogi: facet „Obiekt" + cofnięcie przypisania
    wypycha cel z widoku. Recepta ma dwa człony w kolejności w czasie; pierwszy jest wykonalny,
    drugi („potem…") nie - bo kontrolka „Obiekt" stoi wtedy wygaszona.

    Wykonanie pierwszego przeładowuje zbiór, a raport wczytania gasi na pasku każdą receptę - dawniej
    razem z członem drugim, który właśnie stawał się wykonalny. Teraz `refresh()` składa receptę ze
    stanu od nowa: zostaje SAM człon powrotu, już z wykonawcą, a jego wykonanie przywraca zapis.

    Falsyfikator: zdejmij `ponow_recepte()` z końca `refresh()` → po pierwszym kroku recepta milczy;
    zostaw wykonawcę członu „potem" → przycisk obiecuje gest na wygaszonej kontrolce."""
    v, con = widok
    v.apply_object_facet([(5, "NGC6960")])
    _zaznacz(v, [1, 2])
    recepty = _recepty(v)
    v._on_object_clear()

    r = recepty[-1]
    assert len(r.czlony) == 2, r
    assert i18n.t("grid.sel.clear_set") in r.czlony[0].tekst and r.czlony[0].wykonaj is not None
    assert r.czlony[1].tekst.startswith("potem") and r.czlony[1].wykonaj is None, r
    assert not ({1, 2} & _widoczne(v)), "facet nie wypchnął celu - brak układu"

    r.czlony[0].wykonaj()                                  # klik: odsłoń
    assert {1, 2} <= _widoczne(v), "odsłonięcie nie oddało klatek"
    r = recepty[-1]
    assert len(r.czlony) == 1, f"recepta po odsłonięciu nie złożyła się ze stanu: {r!r}"
    assert r == i18n.t("grid.sel.object_clear_undo", menu=i18n.t("grid.sel.object"),
                       action=i18n.t("grid.sel.object_restore"))
    assert r.czlony[0].wykonaj is not None, "drugi krok dalej niewykonalny"

    v.table.selectionModel().clearSelection()              # user zmienił wybór w międzyczasie…
    r.czlony[0].wykonaj()                                  # klik: przywróć - na klatkach GESTU
    assert _object_id(con, 1) == 5 and _object_id(con, 2) == 5, "powrót nie przywrócił zapisu"


def test_FH2e_recepta_GASNIE_gdy_przestaje_byc_prawda_i_WRACA_po_odswiezeniu(widok):
    """Recepta żyje tyle, co jej prawda: każde przeładowanie zbioru składa ją od nowa (raport
    wczytania zdejmuje ją z paska), a gdy nie ma już czego odwracać, schodzi pusta i stan gaśnie.

    Falsyfikator: składaj receptę raz, przy geście → po zwykłym odświeżeniu recepta znika z paska
    na dobre; nie zeruj stanu przy pustej → martwa recepta wraca przy każdym odświeżeniu."""
    v, con = widok
    v.refresh()
    _zaznacz(v, [1, 2])
    recepty = _recepty(v)
    v._on_object_clear()
    assert i18n.t("grid.sel.object_restore") in recepty[-1]

    recepty.clear()
    v.refresh()                                            # np. zmiana kolumn - prawda trwa
    assert recepty and i18n.t("grid.sel.object_restore") in recepty[-1], recepty

    # Nagrobki przestają być nagrobkami INNĄ drogą niż recepta - recepta przestaje być prawdą.
    con.execute("UPDATE frame SET object_id = 5, object_source = 'user', object_cleared_id = NULL "
                "WHERE id IN (1, 2)")
    con.commit()
    recepty.clear()
    v.refresh()
    assert recepty == [""], recepty
    assert v._recepta_gestu is None, "stan martwej recepty przeżył"
    recepty.clear()
    v.refresh()
    assert recepty == [], "martwa recepta wraca przy każdym odświeżeniu"


# ═════════════════════════ FH-9 - przywrócenie przypisania jest odwracalne


def test_FH9_po_przywroceniu_recepta_mowi_COFNIESZ_i_to_wykonuje(widok):
    """„Przywróć cofnięte przypisanie" zostawiało widżet recepty pusty, choć para gest↔odwrót jest
    symetryczna. Odwrotem przywrócenia jest cofnięcie - stąd własny czasownik („cofniesz"), a nie
    „przywrócisz", które mówiłoby o kierunku, którego ten gest nie ma.

    Falsyfikator: wołaj `_po_gescie_osi` z `_on_object_restore` bez `odwrot` → recepta pusta."""
    v, con = widok
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    _zaznacz(v, [1, 2])
    recepty = _recepty(v)
    v._on_object_restore()

    oczekiwane = i18n.t("grid.sel.object_restore_undo", menu=i18n.t("grid.sel.object"),
                        action=i18n.t("grid.sel.object_clear"))
    assert recepty[-1] == oczekiwane, recepty[-1]
    assert recepty[-1].startswith("cofniesz:")
    recepty[-1].czlony[0].wykonaj()
    assert _object_id(con, 1) is None and _object_id(con, 2) is None, "odwrót nie cofnął przypisania"


def test_FH9_wariant_POTEM_gdy_przywrocenie_wypchnelo_cel(widok):
    """Przywrócona klatka ma obiekt, więc z perspektywy „Do przeglądu" wypada - człon powrotu
    dostaje wariant „potem" bez wykonawcy, a odsłonięcie idzie pierwsze."""
    v, con = widok
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    v.apply_perspective("Do przeglądu")
    _zaznacz(v, [1, 2])
    recepty = _recepty(v)
    v._on_object_restore()

    r = recepty[-1]
    assert [c.wykonaj is not None for c in r.czlony] == [True, False], r
    assert r.czlony[1].tekst == i18n.t("grid.sel.object_restore_undo_after",
                                       menu=i18n.t("grid.sel.object"),
                                       action=i18n.t("grid.sel.object_clear"))


# ═════════════════════════ FH-6 - wycofanie klatki ma receptę powrotu


def test_FH6_wycofanie_podaje_PRZYWROC_KLATKE_i_dwoma_krokami_ja_przywraca(widok, monkeypatch):
    """Wycofanie wypycha klatkę z „Zniknięte" z reguły, a droga powrotu („Klatka → Przywróć
    klatkę", `repo.restore_frames`) była dotąd tylko w pamięci człowieka. Kod składający jest
    wspólny z osią obiektu: te same dwa klucze zdania, inne etykiety, jedna deklaracja.

    Falsyfikator: wołaj `_po_gescie_klatki` z `_on_frame_retire` bez `odwrot` → recepta ma tylko
    odsłonięcie, a po nim milknie."""
    v, con = widok
    con.execute("UPDATE location SET present = 0 WHERE frame_id = 3")   # plik zniknął z dysku
    con.commit()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    v.apply_perspective(grid_mod.PRESET_VANISHED)
    _zaznacz(v, [3])
    recepty = _recepty(v)
    v._on_frame_retire()
    assert con.execute("SELECT retired_at FROM frame WHERE id = 3").fetchone()[0] is not None

    r = recepty[-1]
    potem = i18n.t("grid.sel.object_clear_undo_after", menu=i18n.t("grid.sel.frame"),
                   action=i18n.t("grid.sel.frame_restore"))
    assert [c.tekst for c in r.czlony][1:] == [potem], r
    assert r.czlony[1].wykonaj is None

    r.czlony[0].wykonaj()                                  # odsłoń
    assert 3 in _widoczne(v)
    r = recepty[-1]
    assert r == i18n.t("grid.sel.object_clear_undo", menu=i18n.t("grid.sel.frame"),
                       action=i18n.t("grid.sel.frame_restore")), r
    r.czlony[0].wykonaj()                                  # przywróć
    assert con.execute("SELECT retired_at FROM frame WHERE id = 3").fetchone()[0] is None


# ═════════════════════════ FH-11 - kadr po recepcie


def test_FH11_po_recepcie_zaznaczone_klatki_stoja_W_SRODKU_kadru(qapp, tmp_path):
    """Firsthand: po wykonaniu recepty zaznaczone klatki stały na dolnej krawędzi tabeli. Cel
    odkładał się w `_refresh` ZANIM `table.setVisible(n > 0)` pokazał tabelę, a `scrollTo` na
    ukrytym widoku nic nie robi. Pomiar na POKAZANYM widoku, po dwóch obrotach pętli: y pierwszego
    zaznaczonego wiersza ma leżeć w środkowej 1/3 kadru.

    Falsyfikator: odkładaj cel przed `setVisible` albo zdejmij centrowanie po ustaleniu układu
    (`QTimer.singleShot(0, …)`) → wiersz ląduje przy krawędzi albo poza kadrem."""
    from horreum.gui.grid import FramesView
    con = _baza(tmp_path / "kadr.db", n=240)
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (6,'M42','M','deep_sky')")
    # NGC6960 = klatki 1-41. Grid sortuje malejąco po ścieżce, więc cel stoi na DOLE zbioru
    # (wiersze 199-239) - tam, gdzie kadr na górze tabeli go nie widzi.
    con.execute("UPDATE frame SET object_id = 6 WHERE id > 41")
    con.commit()
    v = FramesView(con, now_fn=lambda: NOW)
    try:
        v.resize(1200, 700)
        v.show()
        QApplication.processEvents()
        QApplication.processEvents()
        v.apply_object_facet([(5, "NGC6960")])
        cel = list(range(1, 42))
        _zaznacz(v, cel)
        v._on_object_clear()
        QApplication.processEvents()
        # Gest wypchnął CAŁY widok - tabela jest ukryta, a pusty stan na wierzchu. To jest układ
        # z firsthandu: recepta pokazuje tabelę i odkłada cel w tym samym obrocie pętli.
        assert v._n_total == 0 and v.table.isHidden(), "brak układu: tabela nie zniknęła"
        v.wykonaj_recepte_powrotu(cel=grid_mod._CEL_GEST)       # zbiór wraca: 240 wierszy
        QApplication.processEvents()
        QApplication.processEvents()

        assert {r["frame_id"] for r in v._selected_data_rows()} == set(cel), "cel nie wrócił"
        wiersz = min(i for i, r in enumerate(v.model._rows)
                     if isinstance(r, dict) and r.get("frame_id") in set(cel))
        assert wiersz > 150, f"cel nie stoi na dole zbioru (wiersz {wiersz}) - brak układu"
        y = v.table.visualRect(v.model.index(wiersz, 0)).center().y()
        h = v.table.viewport().height()
        assert h > 0 and h / 3 <= y <= 2 * h / 3, f"wiersz celu na y={y} przy kadrze {h}"
    finally:
        v.close()
        con.close()


# ═════════════════════════ OKNO: nośnik recepty (FH-8, FH-2e), oś stanowisk (AR-43), planer (AR-48)


@pytest.fixture
def okno(qapp, tmp_path, monkeypatch):
    """Okno na bazie §8 z osią obiektu, pokazane. Pokrycie pól ZBIORÓW liczy się INLINE (jak
    w `test_gui_mainwindow`: wynik z wątku tła doręczony w nieznanej chwili przeładowywałby zbiór
    w środku pomiaru). Planer liczy noc w PRAWDZIWYM wątku tła - na jego koniec czeka
    `_czekaj_na_planer`, także tu, przed oddaniem okna testowi."""
    from horreum.gui.app import MainWindow
    from test_gui_mainwindow import _pokazane, _seeded_db
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    win = _pokazane(MainWindow(_seeded_db(tmp_path, object_axis=True)))
    _czekaj_na_planer(win)
    yield win
    win.close()


def _czekaj_na_planer(win, limit_s=20):
    """Rachunek planera idzie w wątku tła - czekamy na jego koniec I doręczenie wyniku."""
    import time
    koniec = time.monotonic() + limit_s
    while win.planner_view._thread is not None or win.planner_view._worker is not None:
        assert time.monotonic() < koniec, "planer nie skończył rachunku"
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()


def test_Z6_napis_przy_braku_miejsca_opisuje_TO_CO_ZROBI_KLIK(okno):
    """Kontrakt przycisku: widoczny tekst opisuje to, co zrobi klik. Klik robi człon pierwszy,
    a w realnych receptach człon drugi nigdy nie jest wykonalny obok pierwszego - więc przy braku
    miejsca zostaje człon PIERWSZY z „ · …", dalsze idą do podpowiedzi. Wersja, która zdejmowała
    człon pierwszy, pokazywała „potem przywrócisz: …", a klik odsłaniał zbiór.

    Falsyfikator: zdejmij człon pierwszy z napisu (dawna gałąź FH-8) → napis mówi o członie drugim,
    a klik robi pierwszy."""
    from horreum.gui.grid import CzlonRecepty, Recepta
    win = okno
    wykonane = []
    pierwszy = "odsłoni je „× Wyczyść zbiór”"
    drugi = "potem przywrócisz: Obiekt → " + "Przywróć cofnięte przypisanie " * 12
    recepta = Recepta([CzlonRecepty(pierwszy, lambda: wykonane.append(1)), CzlonRecepty(drugi, None)])
    win._flash("Cofnięto przypisanie na 12 z 12 klatek")
    win._pokaz_recepte(recepta)

    napis = win.recipe_label.text()
    assert napis == pierwszy + " · …", f"napis nie opisuje kliku: {napis!r}"
    assert win.recipe_label.toolTip() == str(recepta), "dalsze człony zgubione"
    assert win.recipe_label.isEnabled()
    win.recipe_label.click()
    assert wykonane == [1], "klik nie zrobił członu pierwszego"

    # …a gdy nie mieści się nawet człon pierwszy, tniemy go od prawej - dalej jest pierwszy.
    dlugi = "odsłoni je perspektywa „" + "Bardzo długa nazwa " * 30 + "”"
    win._pokaz_recepte(Recepta([CzlonRecepty(dlugi, lambda: None), CzlonRecepty(drugi, None)]))
    napis = win.recipe_label.text()
    assert napis.startswith("odsłoni je perspektywa") and napis.endswith("…"), napis
    assert "potem" not in napis


def test_FH2e_recepta_gridu_TYLKO_w_Zbiorach_i_WRACA_po_powrocie(okno, monkeypatch):
    """Grid składa receptę ze stanu przy każdym przeładowaniu - także po przebiegu Dostawy, gdy
    Zbiorów nie widać. Recepta mówi o Zbiorach, więc poza nimi na pasek nie wchodzi, przy wyjściu
    z nich schodzi, a przy powrocie widok podaje ją ponownie (`ponow_recepte`), o ile jest prawdą.

    Falsyfikator: podepnij `status_recipe` wprost pod `_pokaz_recepte` → recepta Zbiorów stoi nad
    Dostawą; zdejmij `ponow_recepte()` z `_on_nav_changed` → po powrocie recepty nie ma."""
    from horreum.gui.app import NAV_DOSTAWA, NAV_PORZADKI, NAV_ZBIORY
    from horreum.gui.grid import CzlonRecepty
    win = okno
    grid = win.grid_view
    czlon = CzlonRecepty("przywrócisz: Obiekt → Przywróć cofnięte przypisanie", lambda: None)
    monkeypatch.setattr(grid, "_czlony_recepty_gestu", lambda: [czlon])
    grid._recepta_gestu = ((1,), None)            # stan gestu - treść podaje podmiana wyżej

    win._show_view(NAV_DOSTAWA)
    grid.ponow_recepte()                          # np. przeładowanie po przebiegu Dostawy
    assert not win.recipe_label.isVisible(), "recepta Zbiorów weszła na pasek Dostawy"

    win._show_view(NAV_ZBIORY)
    assert win.recipe_label.isVisible() and win.recipe_label.toolTip() == czlon.tekst
    win._show_view(NAV_PORZADKI)
    assert not win.recipe_label.isVisible(), "recepta Zbiorów wyszła z nich na Porządki"
    win._show_view(NAV_ZBIORY)
    assert win.recipe_label.isVisible(), "recepta nie wróciła razem ze Zbiorami"


def test_AR43_os_stanowisk_po_przebiegu_NIE_przykrywa_statusu_etapu(okno):
    """Po każdym przebiegu Dostawy odświeżenie widoków przeładowuje oś stanowisk, a ta - przy
    pustej osi - mówi „Brak stanowisk na osi…". Zdanie szło na pasek bez powiązania z miejscem
    i przykrywało status etapu, po który user patrzy w Dostawie. Ta sama droga, co raport
    wczytania Zbiorów: odłożone do wejścia w Porządki i tam pada.

    Falsyfikator: podepnij `observatory_view.status_message` wprost pod `_flash` → zdanie osi
    stoi na pasku Dostawy po statusie etapu."""
    from horreum.gui.app import NAV_DOSTAWA, NAV_PORZADKI
    from test_gui_mainwindow import _przebieg_w_watku
    win = okno
    pusta_os = i18n.t("axis.obs.empty_status")
    win._show_view(NAV_DOSTAWA)
    pasek = []
    win.statusBar().messageChanged.connect(pasek.append)
    _przebieg_w_watku(win, lambda: win.pipeline_view.run_stage("group"))
    status_etapu = i18n.t("pipeline.stage_done_status", stage=i18n.t("pipeline.stage.group"))
    assert status_etapu in pasek, pasek
    assert pusta_os not in pasek[pasek.index(status_etapu):], pasek
    assert win.statusBar().currentMessage() != pusta_os

    win._show_view(NAV_PORZADKI)
    assert win.statusBar().currentMessage() == pusta_os, "zdanie osi nie czekało na Porządki"


def test_AR48_planer_bez_stanowiska_milczy_poza_soba_i_mowi_PUSTYM_STANEM(okno):
    """Planer liczy noc w tle także wtedy, gdy go nie widać, a przy bazie bez stanowiska GPS jego
    surowe zdanie („targets: baza nie ma stanowiska…") stało nad ekranem Dostawy. Komunikat planera
    pada wyłącznie przy widocznym planerze; ten sam stan jest na planerze PUSTYM STANEM z gestem
    „Ustaw stanowisko…", który prowadzi na oś obserwatorium.

    Falsyfikator: podepnij `planner.status_message` pod `_flash` → zdanie planera na pasku Dostawy;
    zostaw tabelę zamiast pustego stanu → ekran planera nie podaje drogi dalej."""
    from horreum.gui.app import NAV_DOSTAWA, NAV_PLANER, NAV_PORZADKI
    from horreum.gui.tasks import _PAGE_OBSERVATORY
    win = okno
    planer = win.planner_view
    assert planer.bez_stanowiska, "fikstura ma stanowisko GPS - brak układu"
    pasek = []
    win.statusBar().messageChanged.connect(pasek.append)
    win._show_view(NAV_DOSTAWA)
    planer.refresh()                               # np. po przebiegu Dostawy
    _czekaj_na_planer(win)
    tytul = i18n.t("planner.no_site_title")
    assert tytul not in pasek and not any(m.startswith("targets:") for m in pasek), pasek

    win._show_view(NAV_PLANER)
    _czekaj_na_planer(win)
    assert not planer.empty_note.isHidden() and planer.empty_note.text() == i18n.t("planner.no_site")
    assert not planer.empty_btn.isHidden() and planer.table.isHidden()
    assert planer.night_label.text() == tytul
    assert win.statusBar().currentMessage() == tytul, "przy widocznym planerze zdanie ma paść"

    planer.empty_btn.click()
    assert win.nav.currentRow() == NAV_PORZADKI
    assert win.tasks_view.pages.currentIndex() == _PAGE_OBSERVATORY, "gest nie prowadzi do stanowisk"


def test_AR48_tytul_bez_stanowiska_ma_PL_i_EN():
    """Zdania pustego stanu planera idą z katalogu w obu językach (bramka i18n łapie brak klucza,
    ta - brak tłumaczenia, które przepisałoby polski tekst do EN)."""
    _klucze_pl_en(("planner.no_site_title", "planner.no_site", "planner.no_site_action"))


def test_klucze_recepty_maja_PL_i_EN():
    """Klucze recepty paska (FH-9, odmowy Z4/Z9) - osobno od planera, żeby cofnięcie jednej
    paczki nie czerwieniło bramki drugiej z cudzego powodu."""
    _klucze_pl_en(("grid.sel.object_restore_undo", "grid.sel.object_restore_undo_after",
                   "grid.recipe.busy_stage", "grid.recipe.busy_write",
                   "grid.recipe.nothing_to_reveal"))


@pytest.mark.parametrize("motyw", ["dark", "light"])
def test_W4_wygaszona_recepta_jest_CZYTELNA_w_obu_motywach(motyw):
    """Firsthand na platformie natywnej: wygaszony przycisk recepty miał tekst `disabled_text` na
    tle przycisku - 1,63:1 w ciemnym motywie. Wariant „potem" jest zdaniem do przeczytania, więc
    tekst bierze `secondary_text`, tło - tło paska, a wygaszenie mówi ramka przerywana. Kontrast
    liczony z kolorów MOTYWU, z których składa się reguła QSS (jeden właściciel:
    `theme.recepta_wygaszona`), nie ze zrzutu.

    Falsyfikator: zdejmij regułę `QToolButton#recepta:disabled` z `theme.qss` albo podaj w niej
    `disabled_text` → asercja reguły albo kontrastu pada."""
    from horreum.gui import theme
    from test_theme import _kontrast
    tekst, tlo = theme.recepta_wygaszona(motyw)
    assert _kontrast(tekst, tlo) >= 4.5, f"{motyw}: {tekst} na {tlo} = {_kontrast(tekst, tlo):.2f}:1"
    regula = f"QToolButton#{theme.RECEPTA_OBJECT_NAME}:disabled {{ color: {tekst}; background: {tlo}; "
    q = theme.qss(motyw)
    assert regula in q, "reguła wygaszonej recepty nie niesie kolorów z motywu"
    assert "dashed" in q.split(regula, 1)[1].split("}", 1)[0], "wygaszenie bez ramki"


def test_W4_przycisk_recepty_nosi_selektor_reguly_i_kursor_stanu(okno):
    """Reguła QSS działa tylko na obiekcie o nazwie z `theme.RECEPTA_OBJECT_NAME`; kursor mówi
    o stanie obok ramki (ręka - klik coś zrobi, strzałka - wygaszony)."""
    from PySide6.QtCore import Qt
    from horreum.gui import theme
    from horreum.gui.grid import CzlonRecepty, Recepta
    win = okno
    assert win.recipe_label.objectName() == theme.RECEPTA_OBJECT_NAME
    win._pokaz_recepte(Recepta([CzlonRecepty("przywrócisz: X", lambda: None)]))
    assert win.recipe_label.isEnabled() and win.recipe_label.cursor().shape() == Qt.PointingHandCursor
    win._pokaz_recepte(Recepta([CzlonRecepty("potem przywrócisz: X", None)]))
    assert not win.recipe_label.isEnabled() and win.recipe_label.cursor().shape() == Qt.ArrowCursor


def _klucze_pl_en(klucze):
    from horreum.gui.i18n_catalog import CATALOG
    pauza = chr(0x2014)                       # DASH: nowy tekst katalogu bez pauzy
    for klucz in klucze:
        assert CATALOG[klucz]["pl"] and CATALOG[klucz]["en"], klucz
        assert CATALOG[klucz]["pl"] != CATALOG[klucz]["en"], klucz
        assert pauza not in CATALOG[klucz]["pl"] + CATALOG[klucz]["en"], klucz


# ═════════════════════════ Z1 - odwrót rusza WYŁĄCZNIE klatki, które gest zmienił


def test_Z1_wycofanie_12_z_ktorych_5_dawno_wycofanych_odwrot_przywraca_DOKLADNIE_7(qapp, tmp_path,
                                                                                    monkeypatch):
    """Zaznaczenie 12 klatek: 5 wycofanych dawno + 7 znikniętych. Gest wycofuje 7, 5 pomija jako
    „już wycofane". Recepta pamiętała całe zaznaczenie, więc klik „Przywróć klatkę" przywracał 12 -
    w tym 5, których gest świadomie nie tknął (cudza, starsza decyzja). Cel recepty to teraz
    `RetireGesture.frame_ids`.

    Falsyfikator: wróć do `zaznaczone` jako celu recepty → przywrócone są wszystkie 12."""
    from horreum import repo
    from horreum.gui.grid import FramesView
    con = _baza(tmp_path / "z1.db", n=12)
    con.execute("UPDATE location SET present = 0")                  # pliki zniknęły z dysku
    con.commit()
    repo.retire_frames(con, frame_ids=[1, 2, 3, 4, 5], now="2026-01-01T00:00:00")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    v = FramesView(con, now_fn=lambda: NOW)
    try:
        v.refresh()
        _zaznacz(v, range(1, 13))
        recepty = _recepty(v)
        v._on_frame_retire()
        r = recepty[-1]
        assert r.czlony and r.czlony[-1].wykonaj is not None, r
        r.czlony[-1].wykonaj()

        wycofane = {row[0] for row in con.execute("SELECT id FROM frame WHERE retired_at IS NOT NULL")}
        assert wycofane == {1, 2, 3, 4, 5}, f"odwrót ruszył klatki spoza gestu: {sorted(wycofane)}"
        # Zaznaczenie po odwrocie zostaje zawężone do tego, co odwrócono.
        assert {r["frame_id"] for r in v._selected_data_rows()} == set(range(6, 13))
    finally:
        v.close()
        con.close()


def test_Z1_os_obiektu_odwrot_nie_rusza_nagrobkow_sprzed_gestu_ani_cudzych_przypisan(widok):
    """Lustro na osi obiektu. „Cofnij przypisanie" na zaznaczeniu z nagrobkiem sprzed gestu (3)
    zdejmuje tylko 1, 2 - a recepta „przywrócisz" ma oddać tylko 1, 2. Potem „Przywróć" na
    zaznaczeniu 1, 2, 4 (4 ma przypisanie, nie jest nagrobkiem) oddaje 1, 2 - a recepta
    „cofniesz" ma zdjąć tylko 1, 2, nie 4.

    Falsyfikator: cel recepty = całe zaznaczenie → nagrobek 3 wraca, a 4 traci obiekt."""
    v, con = widok
    v.refresh()
    _zaznacz(v, [3])
    v._on_object_clear()                                   # nagrobek „sprzed tygodnia"
    _zaznacz(v, [1, 2, 3])
    recepty = _recepty(v)
    v._on_object_clear()
    recepty[-1].czlony[-1].wykonaj()                       # przywrócisz
    assert [_object_id(con, f) for f in (1, 2, 3)] == [5, 5, None], "nagrobek sprzed gestu wrócił"

    _zaznacz(v, [1, 2])
    v._on_object_clear()                                   # znów nagrobki 1, 2
    _zaznacz(v, [1, 2, 4])
    v._on_object_restore()
    assert [_object_id(con, f) for f in (1, 2, 4)] == [5, 5, 5]
    recepty[-1].czlony[-1].wykonaj()                       # cofniesz
    assert [_object_id(con, f) for f in (1, 2, 4)] == [None, None, 5], "odwrót zdjął cudze przypisanie"


# ═════════════════════════ Z4, Z5, Z9 - bramki wykonania recepty


def test_Z4_recepta_w_trakcie_etapu_ODMAWIA_z_powodem_i_zostaje(widok):
    """Recepta to nowe klikalne wejście do zapisu osi, a etap Dostawy pisze w tym czasie do tej
    samej bazy. Ta sama bramka co gesty izolacji (`_powod_zajetosci`): klik odmawia z powodem na
    pasku, nic nie zapisuje, a recepta zostaje (po etapie jest dalej prawdziwa).

    Falsyfikator: zdejmij `_wykonaj_czlon` z członów → klik w trakcie etapu przywraca zapis."""
    v, con = widok
    v.refresh()
    _zaznacz(v, [1, 2])
    recepty = _recepty(v)
    raporty = []
    v.status_message.connect(raporty.append)
    v._on_object_clear()
    czlon = recepty[-1].czlony[-1]

    v.set_busy(True)
    recepty.clear()
    czlon.wykonaj()
    assert raporty[-1] == i18n.t("grid.recipe.busy_stage"), raporty[-1]
    assert _object_id(con, 1) is None, "recepta zapisała w trakcie etapu"
    assert recepty and recepty[-1].czlony, "recepta zgasła po odmowie"

    v.set_busy(False)
    recepty[-1].czlony[-1].wykonaj()
    assert _object_id(con, 1) == 5


def test_odslanianie_w_trakcie_etapu_DZIALA_bo_nie_zapisuje(widok):
    """Przypadek negatywny bramki zajętości: człon ODSŁONIĘCIA to sama nawigacja (zbiór,
    perspektywa), więc w trakcie etapu działa jak każde przełączenie widoku. Bramka stoi wyłącznie
    na członie odwrotu, który pisze.

    Falsyfikator: owiń człon odsłonięcia w `_wykonaj_czlon` → klik odmawia, klatki zostają ukryte."""
    v, con = widok
    v.apply_object_facet([(5, "NGC6960")])
    _zaznacz(v, [1, 2])
    recepty = _recepty(v)
    v._on_object_clear()
    odslon = recepty[-1].czlony[0]
    assert not ({1, 2} & _widoczne(v)), "brak układu: cel nie wypadł z widoku"

    v.set_busy(True)
    try:
        odslon.wykonaj()
        assert {1, 2} <= _widoczne(v), "odsłonięcie odmówiło w trakcie etapu"
        odwrot = recepty[-1].czlony[-1]
        odwrot.wykonaj()                                   # …a odwrót dalej odmawia
        assert _object_id(con, 1) is None
    finally:
        v.set_busy(False)


def test_kazdy_powod_zajetosci_ma_zdanie_recepty(widok):
    """Parzystość `_RECEPTA_ZAJETA` z `_powod_zajetosci`: każdy powód, który metoda może zwrócić,
    ma zdanie recepty - inaczej odmowa padłaby `KeyError` dokładnie w chwili zajętości. Stany
    zajętości budowane wprost (etap, własny zapis, zapis drugiej powierzchni).

    Falsyfikator: dopisz w `_powod_zajetosci` nowy powód bez wpisu w słowniku → asercja pada."""
    v, _con = widok
    powody = set()
    v.set_busy(True)
    powody.add(v._powod_zajetosci())
    v.set_busy(False)
    v._foreign_wb = True
    powody.add(v._powod_zajetosci())
    v._foreign_wb = False
    assert v._powod_zajetosci() is None
    assert None not in powody and len(powody) == 2, powody
    assert powody == set(grid_mod._RECEPTA_ZAJETA), (powody, set(grid_mod._RECEPTA_ZAJETA))
    # …i przeciwna strona: każdy literał powodu w kodzie metody jest w słowniku.
    import inspect, re
    zrodlo = inspect.getsource(grid_mod.FramesView._powod_zajetosci)
    assert set(re.findall(r'"(grid\.[\w.]+)"', zrodlo)) <= set(grid_mod._RECEPTA_ZAJETA)


def test_Z5_podwojny_klik_wykonuje_czlon_RAZ(okno):
    """Dwuklik to jeden gest motoryczny, a wykonanie członu składa receptę odwrotną synchronicznie
    - drugi klik zrobiłby odwrót odwrotu. Po wykonaniu przycisk stoi wygaszony przez systemowy
    odstęp dwukliku i wraca do stanu bieżącej recepty.

    Falsyfikator: zdejmij blokadę `_recepta_wstrzymana` → drugi klik wykonuje człon drugi raz."""
    import time
    from horreum.gui.grid import CzlonRecepty, Recepta
    win = okno
    wykonane = []
    recepta = Recepta([CzlonRecepty("przywrócisz: X", lambda: wykonane.append(1))])
    win._pokaz_recepte(recepta)
    win.recipe_label.click()
    win._pokaz_recepte(recepta)                    # grid składa receptę w tym samym obrocie
    win._wykonaj_recepte()                         # drugi klik tego samego ruchu
    assert wykonane == [1], "dwuklik wykonał człon dwa razy"
    assert not win.recipe_label.isEnabled()

    koniec = time.monotonic() + QApplication.doubleClickInterval() / 1000 + 2
    while not win.recipe_label.isEnabled():
        assert time.monotonic() < koniec, "przycisk nie wrócił po odstępie dwukliku"
        QApplication.processEvents()
        time.sleep(0.02)
    win.recipe_label.click()
    assert wykonane == [1, 1]


def test_Z9_odslanianie_bez_zawezenia_MOWI_a_nie_milczy(widok):
    """Między podaniem recepty a kliknięciem mogło zniknąć i zawężenie zbioru, i trim. Klik bez
    skutku i bez zdania wygląda na zawieszenie - wykonawca mówi, że nie ma czego odsłaniać."""
    v, _con = widok
    v.refresh()
    raporty = []
    v.status_message.connect(raporty.append)
    v.wykonaj_recepte_powrotu(cel=grid_mod._CEL_GEST)
    assert raporty[-1] == i18n.t("grid.recipe.nothing_to_reveal"), raporty


def test_Z9_przemontowanie_widokow_zdejmuje_recepte(okno):
    """Wykonawcy członów wiszą na gridzie, który `_clear_views` oddaje do `deleteLater` - recepta
    schodzi z paska razem z nim."""
    from horreum.gui.grid import CzlonRecepty, Recepta
    win = okno
    win._pokaz_recepte(Recepta([CzlonRecepty("przywrócisz: X", lambda: None)]))
    win._clear_views()
    assert not win.recipe_label.isVisible() and win._czlony_recepty == ()


# ═════════════════════════ Z2, Z3, Z8 - planer bez stanowiska


def _stanowisko(con):
    con.execute("INSERT INTO observatory(name, lat, lon, status, created_at) "
                "VALUES ('Będargowo', 53.3890, 14.4424, 'proposed', ?)", (NOW,))
    con.commit()


def test_Z3_po_wskazaniu_stanowiska_wejscie_na_planer_LICZY_plan(okno):
    """Ścieżka powrotu AR-48 - obietnica pustego stanu („plan policzy się po powrocie tutaj"):
    stanowisko dodane gdzie indziej → wejście na planer → plan policzony, pusty stan zniknął,
    tabela widoczna.

    Falsyfikator: zdejmij `refresh()` przy wejściu na planer z `_on_nav_changed` → pusty stan
    zostaje, choć stanowisko już jest."""
    from horreum.gui.app import NAV_DOSTAWA, NAV_PLANER
    win = okno
    planer = win.planner_view
    assert planer.bez_stanowiska, "fikstura ma stanowisko GPS - brak układu"
    win._show_view(NAV_DOSTAWA)
    _stanowisko(win.con)
    win._show_view(NAV_PLANER)
    _czekaj_na_planer(win)
    assert not planer.bez_stanowiska
    assert planer._result is not None, "plan się nie policzył"
    assert planer.empty_btn.isHidden() and not planer.table.isHidden()


def test_Z2_INNY_blad_przy_bazie_bez_stanowiska_zostaje_surowym_komunikatem(qapp, tmp_path,
                                                                           ustawienia, monkeypatch):
    """Pusty stan „bez stanowiska" wchodzi WYŁĄCZNIE dla `targets.BrakStanowiska`. Blokada bazy
    przy bazie bez stanowiska przebierała się dotąd za brak stanowiska: user ustawiał stanowisko
    i dopiero wtedy dostawał prawdziwy błąd.

    Falsyfikator: rozpoznawaj stan po `sky.default_site(...) is None` → asercja pustego stanu pada."""
    import sqlite3
    from horreum import targets
    from horreum.gui.planner import PlannerView

    def _pada(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(targets, "plan", _pada)
    con = db.open_db(str(tmp_path / "pusta.db"))
    v = PlannerView(con, db_path=None)
    try:
        assert not v.bez_stanowiska
        assert v.empty_btn.isHidden() and not v.table.isHidden()
        assert "database is locked" in v.night_label.text(), v.night_label.text()
    finally:
        v.close()
        con.close()


def test_brak_stanowiska_przy_OBECNYM_stanowisku_ponawia_RAZ_i_pokazuje_blad(
        qapp, tmp_path, ustawienia, monkeypatch):
    """Bezpiecznik pętli `no_site → replan`: gdy rdzeń melduje brak stanowiska, choć ekran je
    widzi (rozjazd predykatów), ponowienie jest JEDNO, a drugi taki meldunek idzie na ekran jako
    błąd - bez pustego stanu „Ustaw stanowisko…", bo stanowisko jest.

    Falsyfikator: zdejmij flagę `_ponowiono_bez_stanowiska` → rachunek kręci się w kółko."""
    from horreum import targets
    from horreum.gui.planner import PlannerView
    wolania = []

    def _brak(*_a, **_k):
        wolania.append(1)
        raise targets.BrakStanowiska("rdzeń nie widzi stanowiska")
    monkeypatch.setattr(targets, "plan", _brak)
    con = db.open_db(str(tmp_path / "petla.db"))
    _stanowisko(con)
    v = PlannerView(con, db_path=None)
    try:
        for _ in range(5):
            QApplication.processEvents()
        assert len(wolania) == 2, f"bezpiecznik nie zadziałał: {len(wolania)} biegów"
        assert v.night_label.text() == "rdzeń nie widzi stanowiska"
        assert not v.bez_stanowiska and v.empty_btn.isHidden()
    finally:
        v.close()
        con.close()


def test_Z8_stary_blad_braku_stanowiska_gdy_stanowisko_JUZ_JEST_liczy_od_nowa(qapp, tmp_path,
                                                                            ustawienia):
    """Odwrotny wyścig: bieg ruszył bez stanowiska, a zanim jego błąd dotarł, stanowisko zostało
    wskazane. Render postawiłby pusty stan nad bazą, która stanowisko ma, a `_shown_gen`
    zablokowałby ponowny rachunek - więc ekran liczy od nowa.

    Falsyfikator: renderuj błąd bez sprawdzenia stanowiska → `bez_stanowiska` zostaje i planu nie ma."""
    from horreum.gui.planner import PlannerView
    con = db.open_db(str(tmp_path / "wyscig.db"))
    v = PlannerView(con, db_path=None)
    try:
        assert v.bez_stanowiska
        _stanowisko(con)
        v._on_no_site(v._gen, "stary błąd sprzed wskazania")
        QApplication.processEvents()
        QApplication.processEvents()
        assert not v.bez_stanowiska and v._result is not None, "ekran nie policzył planu od nowa"
    finally:
        v.close()
        con.close()
