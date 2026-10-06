"""Układ i pamięć widoku: kolumny gridu po zapisie perspektywy i po przebiegu Dostawy (BP-6),
wybory widoku, które przeżywają restart (AR-36), kolumna podglądu renamu w kadrze (AR-57) i godziny
materiału w bibliotece obiektów (FH-10). Testy STERUJĄCE realnym oknem Qt (offscreen).

`importorskip` na poziomie modułu: bez PySide6 plik się POMIJA."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db
from horreum.gui import grid as grid_mod

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog

NOW = "2026-07-03T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed(con):
    """4 klatki z trzema keywordami (OBJECT, EXPTIME, GAIN) - wszystkie trzy są domyślnymi kolumnami."""
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
        [(1, "d1", "light", "fits", NOW), (2, "d2", "light", "fits", NOW),
         (3, "d3", "master_flat", "xisf", NOW), (4, "d4", "light", "fits", NOW)])
    con.executemany(
        "INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) VALUES (?,?,?,?,?,?)",
        [(1, "OBJECT", 0, "M51", None, "str"), (1, "EXPTIME", 0, "300", 300.0, "float"),
         (1, "GAIN", 0, "100", 100.0, "int"),
         (2, "OBJECT", 0, "NGC891", None, "str"), (2, "EXPTIME", 0, "60", 60.0, "float"),
         (2, "GAIN", 0, "100", 100.0, "int"),
         (4, "OBJECT", 0, "M51", None, "str"), (4, "EXPTIME", 0, "120", 120.0, "float")])
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(1, "V", "/a/f1.fits", 1), (1, "V", "/b/f1c.fits", 1), (2, "V", "/a/f2.fits", 1),
         (3, "V", "/a/f3.xisf", 1), (4, "V", "/a/f4.fits", 0)])
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, object_raw, exptime) VALUES (?,?,?,?)",
        [(1, "{}", "M51", 300.0), (2, "{}", "NGC891", 60.0), (4, "{}", "M51", 120.0)])
    con.commit()


@pytest.fixture
def gcon(tmp_path):
    con = db.open_db(str(tmp_path / "g.db"))
    _seed(con)
    yield con
    con.close()


@pytest.fixture
def view(qapp, gcon):
    v = grid_mod.FramesView(gcon, now_fn=None)
    v._writeback_async = False
    yield v
    v.close()


def _rail_item(view, facet, value):
    lw = view.facet_rail._lists[facet]
    for i in range(lw.count()):
        it = lw.item(i)
        if it.data(Qt.UserRole)[1] == value:
            return it
    raise AssertionError(f"brak wartości {value!r} w facecie {facet}")


def _zapisz_perspektywe(view, monkeypatch, nazwa):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (nazwa, True)))
    view._save_perspective()


# ---------- BP-6: kolumny usera po zapisie perspektywy i po przebiegu Dostawy ----------

def test_BP6_kolumny_usera_przezywaja_zapis_perspektywy_i_klik_w_facet(view, monkeypatch):
    """Hipoteza BP-6: `_save_perspective` wołał `_load_facets`, a ten ustawiał `self._columns`
    na sześć domyślnych - najbliższy `refresh()` (klik w facet) budował siatkę z domyślnych, choć
    zapisany spec niósł wybór usera. Strażnik: kolumny modelu po kliku == wybór sprzed zapisu,
    a spec w bazie niesie ten sam wybór.

    Falsyfikator: przywróć w `_save_perspective` wołanie pełnego `_load_facets` z resetem kolumn
    do domyślnych (stan sprzed `4c4b22d`) - model po kliku pokaże EXPTIME, OBJECT, GAIN."""
    domyslne = list(view.model._keywords)
    wybor = ["GAIN"]
    assert wybor != domyslne
    view.fields.columnsChanged.emit(wybor)
    assert view.model._keywords == wybor
    _zapisz_perspektywe(view, monkeypatch, "Tylko GAIN")
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view.model._keywords == wybor
    from horreum.gui import queries
    assert dict(queries.perspectives(view.con))["Tylko GAIN"]["columns"] == wybor


def test_BP6_kolumny_usera_przezywaja_przebieg_dostawy_takze_gdy_karty_sie_zmienily(view, gcon):
    """Drugi wariant hipotezy: gospodarz po przebiegu Dostawy woła `grid_view._load_facets()`
    i `grid_view.refresh()` (`MainWindow._odswiez_widoki_po_przebiegu`). Dostawa dopisała karty
    z NOWYM keywordem, więc pokrycie liczy się naprawdę od nowa (inny odcisk kart) - i dopiero
    wtedy reset kolumn miałby okazję się wydarzyć. Wybór usera zostaje; nowy keyword trafia
    do „Pól" bez zaznaczenia.

    Falsyfikator: w `_zastosuj_pola` wybieraj domyślne przy KAŻDYM wyniku, nie tylko pierwszym."""
    view.fields.columnsChanged.emit(["OBJECT"])
    gcon.execute("INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) "
                 "VALUES (2, 'FOCUSPOS', 0, '1234', 1234.0, 'int')")
    gcon.commit()
    view._load_facets()
    view.refresh()
    assert view.model._keywords == ["OBJECT"]
    assert "FOCUSPOS" in view._all_keywords


# ---------- AR-36: wybory widoku przeżywają restart ----------

def _wybierz_zapisana(view, nazwa):
    idx = next(i for i in range(view.combo_persp.count())
               if view.combo_persp.itemData(i) == ("saved", nazwa))
    view.combo_persp.setCurrentIndex(idx)


def test_AR36_wybor_obrazow_jedzie_ze_spec_em_perspektywy_do_nowego_okna(view, gcon, monkeypatch):
    """Wybór ręki kolumny „Obrazy" żył w pamięci widoku i ginął z restartem. Zapisana perspektywa
    niesie go kluczem spec-a; nowe okno nad tą samą bazą (restart w miniaturze) pokazuje kolumnę
    po wejściu w perspektywę.

    Falsyfikator: zdejmij klucz `view` z `_save_perspective` albo jego odczyt z `_on_perspective` -
    kolumna w drugim oknie zostaje schowana."""
    from horreum.gui import queries
    assert view.table.isColumnHidden(view.model.base_col("_images"))
    view.fields.images.click()
    _zapisz_perspektywe(view, monkeypatch, "Z obrazami")
    spec = dict(queries.perspectives(gcon))["Z obrazami"]
    assert spec[grid_mod._SPEC_WIDOK][grid_mod._SPEC_OBRAZY] is True
    assert grid_mod._SPEC_SZEROKOSC_SCIEZKI not in spec[grid_mod._SPEC_WIDOK], (
        "szerokość nietknięta ręką nie trafia do spec-a")
    assert grid_mod._nieznane_warunki(spec) == [], "wygląd nie jest obcym warunkiem"

    drugie = grid_mod.FramesView(gcon, now_fn=None)
    try:
        assert drugie.table.isColumnHidden(drugie.model.base_col("_images"))
        _wybierz_zapisana(drugie, "Z obrazami")
        assert not drugie.table.isColumnHidden(drugie.model.base_col("_images"))
        assert drugie.fields.images.isChecked()
    finally:
        drugie.close()


def test_AR36_szerokosc_sciezki_zapisana_z_perspektywa_przezywa_restart_i_przeladowanie(
        view, gcon, monkeypatch):
    """Szerokość ścieżki w perspektywach z treścią liczyła się od nowa przy każdym wejściu
    i każdym przeładowaniu - ręczne poszerzenie ginęło. Zapisana perspektywa niesie szerokość
    z chwili zapisu; drugie okno ją odtwarza, a przeładowanie zbioru (klik w facet) jej nie zjada.
    Preset „Duplikaty" dalej liczy z treści - szerokość zapisanej nie przecieka.

    Falsyfikator: wołaj `kolumna_z_tresci` w `_uloz_kolumny` bez względu na `_szerokosc_sciezki` -
    szerokość po kliku w facet wraca do treści."""
    from horreum.gui import queries
    view.apply_perspective(grid_mod.PRESET_DUPS)
    sciezka = view.model.base_col("path")
    z_tresci = view.table.columnWidth(sciezka)
    reczna = z_tresci + 77
    view.table.setColumnWidth(sciezka, reczna)
    _zapisz_perspektywe(view, monkeypatch, "Duble szerokie")
    zapisana = dict(queries.perspectives(gcon))["Duble szerokie"]
    assert zapisana[grid_mod._SPEC_WIDOK][grid_mod._SPEC_SZEROKOSC_SCIEZKI] == reczna
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view.table.columnWidth(sciezka) == reczna, "zapis obowiązuje od razu, nie po restarcie"

    drugie = grid_mod.FramesView(gcon, now_fn=None)
    try:
        _wybierz_zapisana(drugie, "Duble szerokie")
        kol = drugie.model.base_col("path")
        assert drugie.table.columnWidth(kol) == reczna
        assert isinstance(drugie.table.itemDelegateForColumn(kol), grid_mod._ElizjaWSrodku)
        drugie.facet_rail._on_item_clicked(_rail_item(drugie, "kind", "light"))
        assert drugie.table.columnWidth(kol) == reczna
        drugie.apply_perspective(grid_mod.PRESET_DUPS)
        assert drugie.table.columnWidth(kol) == z_tresci, "preset liczy z treści"
    finally:
        drugie.close()


def test_AR36_spec_bez_kluczy_wygladu_albo_z_nieczytelnymi_zostawia_wybor_reki(view, gcon):
    """Perspektywa zapisana starszym wydaniem (bez kluczy wyglądu) albo z wartością spoza kontraktu
    (ręczna edycja bazy) zostawia wybór ręki i szerokość z treści - bez wyjątku i bez zgadywania."""
    from horreum import repo
    repo.save_perspective(gcon, name="Stara", spec={"filter": None, "only_dups": True}, now=NOW)
    repo.save_perspective(gcon, name="Krzywa", spec={
        "filter": None, "only_dups": True, grid_mod._SPEC_WIDOK: {
            grid_mod._SPEC_OBRAZY: "tak", grid_mod._SPEC_SZEROKOSC_SCIEZKI: -5}}, now=NOW)
    repo.save_perspective(gcon, name="Plaska", spec={
        "filter": None, "only_dups": True, grid_mod._SPEC_WIDOK: "nie-slownik"}, now=NOW)
    view._odbuduj_perspektywy()
    view.fields.images.click()
    for nazwa in ("Stara", "Krzywa", "Plaska"):
        _wybierz_zapisana(view, nazwa)
        assert not view.table.isColumnHidden(view.model.base_col("_images"))
        assert view._szerokosc_sciezki is None


def test_AR36_nieznane_pole_WEWNATRZ_view_nie_jest_warunkiem():
    """Wygląd nie zmienia zbioru, więc `view` jest znany w całości - także pole, które doda dopiero
    nowsze wydanie. Ostrzeżenie „pominięto warunki" (D-V-9f) nie może o nie pytać.

    Falsyfikator: usuń `_SPEC_WIDOK` z `_ZNANE_KLUCZE_SPECU` - lista zwróci `view`."""
    spec = {"filter": None, "only_dups": True,
            grid_mod._SPEC_WIDOK: {"kolejnosc_kolumn": ["OBJECT"], grid_mod._SPEC_OBRAZY: True}}
    assert grid_mod._nieznane_warunki(spec) == []
    assert grid_mod._nieznane_warunki({**spec, "only_przyszle": True}) == ["only_przyszle"]


def test_AR36_wybor_obrazow_z_perspektywy_nie_jest_gestem_reki_i_nie_przecieka(
        view, gcon, monkeypatch):
    """Wybór „Obrazów" zapisany w perspektywie żyje osobno od gestu ręki: nie przepisuje go,
    znika po wyjściu z perspektywy (preset „Duplikaty" pokazuje kolumnę, bo tak ma domyślnie)
    i nie trafia do perspektywy zapisanej później gdzie indziej - zapis bierze wybór efektywny
    bieżącego widoku. Gest ręki PO wejściu bije wybór perspektywy.

    Falsyfikator: zapisuj wybór perspektywy do `_obrazy_reka` - „Duplikaty" chowają kolumnę,
    a „Inna" dziedziczy `False`."""
    from horreum import repo
    from horreum.gui import queries
    repo.save_perspective(gcon, name="Bez obrazow", spec={
        "filter": None, "only_dups": True,
        grid_mod._SPEC_WIDOK: {grid_mod._SPEC_OBRAZY: False}}, now=NOW)
    view._odbuduj_perspektywy()
    _wybierz_zapisana(view, "Bez obrazow")
    kol = view.model.base_col("_images")
    assert view.table.isColumnHidden(kol)
    assert view._obrazy_reka is None, "perspektywa nie pisze gestu ręki"
    view.apply_perspective(grid_mod.PRESET_DUPS)
    assert not view.table.isColumnHidden(view.model.base_col("_images"))
    _zapisz_perspektywe(view, monkeypatch, "Inna")
    assert dict(queries.perspectives(gcon))["Inna"][grid_mod._SPEC_WIDOK][grid_mod._SPEC_OBRAZY] is True
    _wybierz_zapisana(view, "Bez obrazow")
    view.fields.images.click()                         # gest po wejściu
    assert not view.table.isColumnHidden(view.model.base_col("_images"))


def test_AR36_gest_reki_skonsumowany_przez_zapis_nie_przechodzi_na_preset(view, monkeypatch):
    """Firsthand: ukrycie „Obrazów" gestem ręki w Duplikatach → zapis perspektywy → preset
    „Duplikaty" - kolumna dalej ukryta, bo gest sesji przeżył zapis. Zapis konsumuje gest: wybór
    należy od teraz do zapisanej perspektywy, preset pokazuje swoją domyślną, a powrót na zapisaną
    znów chowa kolumnę.

    Falsyfikator: zostaw `_obrazy_reka` po `_save_perspective` - preset „Duplikaty" bez kolumny."""
    view.apply_perspective(grid_mod.PRESET_DUPS)
    assert not view.table.isColumnHidden(view.model.base_col("_images"))
    view.fields.images.click()                         # gest ręki: ukryj
    assert view.table.isColumnHidden(view.model.base_col("_images"))
    _zapisz_perspektywe(view, monkeypatch, "Duble bez obrazow")
    assert view._obrazy_reka is None
    assert view.table.isColumnHidden(view.model.base_col("_images")), "zapis niczego nie pokazuje"
    view.apply_perspective(grid_mod.PRESET_DUPS)
    assert not view.table.isColumnHidden(view.model.base_col("_images"))
    _wybierz_zapisana(view, "Duble bez obrazow")
    assert view.table.isColumnHidden(view.model.base_col("_images"))


def test_AR36_przeskok_etykiety_na_preset_zdejmuje_wyglad_zapisanej(view, gcon):
    """„× Wyczyść zbiór" zdejmuje facet zapisanej perspektywy i etykieta przeskakuje na preset
    BEZ `_on_perspective` (właściciel etykiety). Wygląd zapisanej nie może jechać dalej pod
    etykietą presetu: ścieżka wraca do szerokości z treści, „Obrazy" do domyślnej presetu.

    Falsyfikator: zdejmij `_wyglad_z_perspektywy` z `_etykieta_perspektywy_za_stanem` - zostaje
    zapisana szerokość i schowana kolumna."""
    from horreum import repo
    view.apply_perspective(grid_mod.PRESET_DUPS)
    z_tresci = view.table.columnWidth(view.model.base_col("path"))
    repo.save_perspective(gcon, name="Duble lightow", spec={
        "filter": None, "only_dups": True, "facets": {"kind": {"in": [["light", "light"]]}},
        grid_mod._SPEC_WIDOK: {grid_mod._SPEC_OBRAZY: False,
                               grid_mod._SPEC_SZEROKOSC_SCIEZKI: z_tresci + 55}}, now=NOW)
    view._odbuduj_perspektywy()
    _wybierz_zapisana(view, "Duble lightow")
    assert view.table.columnWidth(view.model.base_col("path")) == z_tresci + 55
    view._on_clear_selection()
    assert view.combo_persp.currentData() == ("preset", grid_mod.PRESET_DUPS)
    assert view._szerokosc_sciezki is None and view._obrazy_perspektywy is None
    assert view.table.columnWidth(view.model.base_col("path")) == z_tresci
    assert not view.table.isColumnHidden(view.model.base_col("_images"))


def test_AR36_chip_soczewki_planera_przezywa_restart_i_wraca_do_domyslnego_bez_zestawu(
        qapp, tmp_path, ustawienia):
    """Chip soczewki wracał po restarcie do „najlepsze dopasowanie". Wybór idzie do `QSettings`
    i nowe okno planera startuje z nim. Zapamiętany zestaw, którego nie ma w parku, daje best-fit,
    a wpis zostaje - zestaw może wrócić (inna baza, inny park).

    Falsyfikator: zdejmij odczyt `rig_chip` z `_rebuild_chips` - drugie okno startuje z best-fit."""
    from test_gui_planner import _seed as seed_planera
    from horreum.gui import planner_model as pm
    from horreum.gui.planner import PlannerView
    from PySide6.QtCore import QDate
    con = seed_planera(str(tmp_path / "planer.db"))
    widoki = []

    def _okno():
        v = PlannerView(con, db_path=None)
        v.night_edit.setDate(QDate(2026, 8, 15))
        v.replan()
        widoki.append(v)
        return v

    try:
        pierwsze = _okno()
        wybor = next(n for n in pm.rig_choices(pierwsze._result) if n.startswith("RC8"))
        pierwsze._on_chip(wybor)
        drugie = _okno()
        assert drugie._rig_chip == wybor
        assert [b.text() for b in drugie._chip_group.buttons() if b.isChecked()] == [wybor]
        ustawienia.setValue("planner/rig_chip", "ZESTAW-KTOREGO-NIE-MA")
        trzecie = _okno()
        assert trzecie._rig_chip is None
        assert ustawienia.value("planner/rig_chip") == "ZESTAW-KTOREGO-NIE-MA"
        trzecie._on_chip(None)
        assert _okno()._rig_chip is None
    finally:
        for v in widoki:
            v.close()
        con.close()


# ---------- AR-57: podgląd renamu w kadrze ----------

def _run_renamu(*pary):
    from types import SimpleNamespace
    return SimpleNamespace(
        touched=[SimpleNamespace(frame_id=fid, old_path=stara, new_path=nowa)
                 for fid, stara, nowa in pary],
        skipped=[])


_NOWA_NAZWA = "CTB1_20260801_220000_" + "x" * 40 + "_FLATGRP_.fits"


def _okno_z_podgladem(view, qapp):
    view.resize(1400, 800)
    view.show()
    qapp.processEvents()
    view._show_rename_preview(_run_renamu((1, "/a/f1.fits", "/a/" + _NOWA_NAZWA)))
    qapp.processEvents()


def _w_kadrze(t, c):
    x = t.columnViewportPosition(c)
    return 0 <= x and x + t.columnWidth(c) <= t.viewport().width()


def test_AR57_podglad_renamu_logicznie_ostatni_wizualnie_obok_sciezki_i_w_kadrze(view, qapp):
    """Kolumna „nazwa →" stała ostatnia (indeks 14 z 15, x=1300 przy viewporcie 1076 px). Zostaje
    LOGICZNIE ostatnia (keywordy, sort i szerokości nie jadą), a wizualnie staje ZARAZ ZA „Ścieżką"
    - stara i nowa nazwa obok siebie, obie w kadrze przy oknie 1400 px. Szerokość z treści,
    elizja w środku zostawia oba końce nazwy.

    Falsyfikator: postaw podgląd w `_uloz_belki_i_wersje` po bazowych zamiast na pozycji 1 -
    między nazwami stoi siedem kolumn."""
    from horreum.gui import i18n
    m, t = view.model, view.table
    h = t.horizontalHeader()
    _okno_z_podgladem(view, qapp)
    kol = m._preview_col()
    sciezka = m.base_col("path")
    assert kol == m.columnCount() - 1, "logicznie ostatnia"
    assert h.visualIndex(kol) == h.visualIndex(sciezka) + 1, "bezpośredni sąsiad „Ścieżki”"
    assert m.headerData(kol, Qt.Horizontal) == i18n.t("grid.preview.name")
    nr = next(i for i, r in enumerate(m._rows) if r.get("frame_id") == 1)
    assert m.data(m.index(nr, kol), Qt.DisplayRole) == _NOWA_NAZWA
    assert isinstance(t.itemDelegateForColumn(kol), grid_mod._ElizjaWSrodku)
    assert h.defaultSectionSize() < t.columnWidth(kol) <= grid_mod._SUFIT_KOLUMNY_Z_TRESCI
    assert _w_kadrze(t, sciezka) and _w_kadrze(t, kol), "stara i nowa nazwa w kadrze"
    view._on_rename_clear()
    assert all(h.visualIndex(c) == c for c in range(h.count())), "bez podglądu bez przesunięć"


def test_AR57_przewiniety_widok_wraca_do_sciezki_nie_do_samego_podgladu(view, qapp):
    """Gdy para „Ścieżka" + podgląd nie stoi w kadrze (widok przewinięty w bok), kadr wraca tak,
    by „Ścieżka" była lewą krawędzią - przewinięcie do samej kolumny podglądu wypychało starą
    nazwę z kadru i porównanie było niemożliwe.

    Falsyfikator: przewijaj do kolumny podglądu (`scrollTo` na nią) - „Ścieżka" zostaje za
    lewą krawędzią."""
    m, t = view.model, view.table
    view.resize(900, 600)
    view.show()
    qapp.processEvents()
    for c in range(len(grid_mod.BASE_COLS), m.columnCount()):
        t.setColumnWidth(c, 400)
    qapp.processEvents()
    t.horizontalScrollBar().setValue(t.horizontalScrollBar().maximum())
    assert t.horizontalScrollBar().value() > 0
    view._show_rename_preview(_run_renamu((1, "/a/f1.fits", "/a/" + _NOWA_NAZWA)))
    qapp.processEvents()
    assert t.columnViewportPosition(m.base_col("path")) == 0, "„Ścieżka” lewą krawędzią"
    assert _w_kadrze(t, m._preview_col())


def test_AR57_podglad_makra_tez_obok_sciezki_z_szerokoscia_z_tresci(view, qapp):
    """Podgląd makra i edycji komórki („makro →") stał ostatni, ~130 px - zmianę dwóch kart
    widać było dopiero po przewinięciu. Ta sama reguła co rename: logicznie ostatni, wizualnie
    za „Ścieżką", szerokość z treści z sufitem i elizją w środku.

    Falsyfikator: stawiaj w `_uloz_belki_i_wersje` z przodu tylko podgląd renamu - makro na końcu."""
    m, t = view.model, view.table
    h = t.horizontalHeader()
    view.resize(1400, 800)
    view.show()
    qapp.processEvents()
    nowa = "M51 " + "y" * 60
    m.set_preview({1: {"keyword": "OBJECT", "old": "M51", "new": nowa, "op": "set"}})
    try:
        kol = m._preview_col()
        assert kol == m.columnCount() - 1
        assert h.visualIndex(kol) == h.visualIndex(m.base_col("path")) + 1
        assert isinstance(t.itemDelegateForColumn(kol), grid_mod._ElizjaWSrodku)
        assert h.defaultSectionSize() < t.columnWidth(kol) <= grid_mod._SUFIT_KOLUMNY_Z_TRESCI
        assert _w_kadrze(t, kol)
    finally:
        m.set_preview({})


def test_AR57_sort_i_szerokosc_keywordu_przezywaja_podglad_renamu(view, qapp):
    """Strzałka sortu stoi nad posortowanym keywordem po wejściu i po zdjęciu podglądu, a szerokość
    keywordu ustawiona ręką przed podglądem wraca na TEN keyword.

    Falsyfikator: wstaw podgląd logicznie przed keywordy - strzałka i szerokość zostają pod starym
    numerem, czyli nad podglądem albo nad sąsiednim keywordem."""
    m, t = view.model, view.table
    h = t.horizontalHeader()
    kw = view._columns[0]
    kol_kw = len(grid_mod.BASE_COLS) + view._columns.index(kw)
    t.sortByColumn(kol_kw, Qt.DescendingOrder)
    t.setColumnWidth(kol_kw, h.defaultSectionSize() + 41)
    _okno_z_podgladem(view, qapp)
    assert m.headerData(h.sortIndicatorSection(), Qt.Horizontal) == kw
    assert m.headerData(kol_kw, Qt.Horizontal) == kw
    assert t.columnWidth(kol_kw) == h.defaultSectionSize() + 41
    view._on_rename_clear()
    assert m.headerData(h.sortIndicatorSection(), Qt.Horizontal) == kw
    assert t.columnWidth(kol_kw) == h.defaultSectionSize() + 41


def test_AR57_wersja_wchodzaca_w_trakcie_podgladu_nie_przenosi_jego_szerokosci(view, qapp):
    """„Wersja" wchodzi przed keywordy, więc numery keywordów i podglądu rosną o jeden, a nagłówek
    gubi przesunięcia, zostawiając szerokości na pozycjach wizualnych. Szerokość ustawiona ręką
    na keywordzie jedzie za tym keywordem, nie zostaje pod starym numerem ani nie przechodzi na
    sąsiada; stary numer podglądu (teraz keyword) traci elizję. Podgląd stoi wizualnie zaraz za
    „Ścieżką", „Wersja" za nim.

    Falsyfikator: zdejmij przywracanie szerokości po znaczeniu z `_uloz_belki_i_wersje` - szerokość
    ręki zostaje pod starym numerem, czyli na kolumnie „Wersja"."""
    m, t = view.model, view.table
    h = t.horizontalHeader()
    baza = len(grid_mod.BASE_COLS)
    kw = view._columns[0]
    t.setColumnWidth(baza, h.defaultSectionSize() + 37)
    _okno_z_podgladem(view, qapp)
    stary = m._preview_col()
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    nowy = m._preview_col()
    assert nowy == stary + 1 and m._version_col() == baza
    assert h.visualIndex(nowy) == 1, "zaraz za „Ścieżką”"
    assert h.visualIndex(m._version_col()) == 2
    assert m.headerData(baza + 1, Qt.Horizontal) == kw
    assert t.columnWidth(baza + 1) == h.defaultSectionSize() + 37, "szerokość jedzie za keywordem"
    assert t.itemDelegateForColumn(stary) is None
    assert isinstance(t.itemDelegateForColumn(nowy), grid_mod._ElizjaWSrodku)


def test_AR57_rozciagnieta_ostatnia_kolumna_nie_trafia_do_migawki_szerokosci(view, qapp):
    """Ostatnia widoczna sekcja rozciąga się do viewportu (`setStretchLastSection`). Migawka
    szerokości po znaczeniu nie może tej szerokości utrwalić: keyword, który był ostatni, po
    dołożeniu kolejnego pola wraca do szerokości domyślnej, zamiast nieść pół ekranu - seria
    zmian „Pól" zostawiałaby kilka nadmiernie szerokich kolumn i przewijanie w bok.

    Falsyfikator: zapisuj w `_zapamietaj_szerokosci` także ostatnią widoczną sekcję - pierwszy
    keyword zostaje szeroki na resztę viewportu."""
    t = view.table
    h = t.horizontalHeader()
    view.fields.columnsChanged.emit(["OBJECT"])
    view.resize(1400, 800)
    view.show()
    qapp.processEvents()
    kol = len(grid_mod.BASE_COLS)
    assert h.visualIndex(kol) == h.count() - 1
    assert t.columnWidth(kol) > t.viewport().width() // 2, "rozciągnięta do viewportu"
    view.fields.columnsChanged.emit(["OBJECT", "GAIN"])
    qapp.processEvents()
    assert view.model.headerData(kol, Qt.Horizontal) == "OBJECT"
    assert t.columnWidth(kol) == h.defaultSectionSize()


# ---------- FH-10: godziny materiału w bibliotece obiektów ----------

@pytest.fixture
def obiekty(qapp, tmp_path):
    from fixture_s8 import seed_object_axis
    from horreum.gui.app import ObjectAxisView
    con = db.open_db(str(tmp_path / "obj.db"))
    ids = seed_object_axis(con)
    fr = ids["frames"]
    for nazwa, exptime in (("a1", 600.0), ("a2", 600.0), ("c1", 300.0)):
        con.execute("UPDATE header SET exptime = ? WHERE frame_id = ?", (exptime, fr[nazwa]))
    con.commit()
    v = ObjectAxisView(con)
    yield v, con
    v.close()
    con.close()


def _komorka_obiektu(v, canon, kol):
    from horreum.gui.app import OBJ_COL_CANON
    for r in range(v.objects.rowCount()):
        if v.objects.item(r, OBJ_COL_CANON).text() == canon:
            return v.objects.item(r, kol)
    raise AssertionError(f"obiekt {canon} nie ma w bibliotece")


def test_FH10_biblioteka_mowi_godziny_materialu_pod_filtrem_w_kadrze(obiekty, qapp):
    """Biblioteka miała trzy kolumny i pas pustki obok. Czwarta mówi, ile materiału jest per obiekt:
    suma EXPTIME lightów pod tymi samymi filtrami co biblioteka (`queries.library_exposure`),
    format, sufiks lightów bez EXPTIME i rozbicie per filtr z `portfolio`. Obiekt, którego lighty
    nie mają EXPTIME wcale, mówi „0.0 h (+n ...)", nie gołe „0.0 h". Przy realnym oknie 1400 px
    kolumna stoi w kadrze bez przewijania i mieści swój tekst bez elizji.

    Falsyfikator: licz godziny bez filtrów osi - po wyborze „Ha" NGC7000 pokaże też sekundy c1;
    składaj komórkę z samego `format_hours` - M42 powie „0.0 h" bez ogona."""
    from horreum.gui import i18n, portfolio
    from horreum.gui.app import OBJ_COL_HOURS
    v, con = obiekty
    v.resize(1400, 800)
    v.show()
    qapp.processEvents()
    ngc = _komorka_obiektu(v, "NGC7000", OBJ_COL_HOURS)
    assert ngc.text() == (portfolio.format_hours(1500.0)
                          + i18n.t("portfolio.plus_no_exptime", n=2))   # c2 + present0
    assert "Ha: " + portfolio.format_hours(1200.0) in ngc.toolTip()
    assert i18n.t("portfolio.frames_no_exptime", n=2) in ngc.toolTip()
    m42 = _komorka_obiektu(v, "M42", OBJ_COL_HOURS)                      # b1..b3 bez EXPTIME
    assert m42.text() == portfolio.format_hours(0) + i18n.t("portfolio.plus_no_exptime", n=3)
    assert v.objects.horizontalHeaderItem(OBJ_COL_HOURS).text() == i18n.t("object.col.hours")
    h = v.objects.horizontalHeader()
    assert v.objects.horizontalScrollBar().maximum() == 0, "biblioteka bez przewijania w bok"
    assert 0 <= h.sectionViewportPosition(OBJ_COL_HOURS)
    assert (h.sectionViewportPosition(OBJ_COL_HOURS) + h.sectionSize(OBJ_COL_HOURS)
            <= v.objects.viewport().width())
    najdluzszy = max(v.objects.fontMetrics().horizontalAdvance(c.text()) for c in (ngc, m42))
    assert h.sectionSize(OBJ_COL_HOURS) > najdluzszy, "tekst godzin mieści się bez elizji"
    v.combo_filter.setCurrentIndex(v.combo_filter.findData("Ha"))
    assert _komorka_obiektu(v, "NGC7000", OBJ_COL_HOURS).text() == portfolio.format_hours(1200.0)
