"""Widżet osi OBSERWATORIUM (`horreum.gui.app.ObservatoryAxisView`) — testy STERUJĄCE realnym oknem Qt
(offscreen) na scenie budowanej wprost przez `repo` (propose + assign, bez FITS). Sprawdzają glue
widget↔baza: lista odbija read-model (licznik rolowany pod kanon), akcje (label/merge/unmerge) idą przez
`repo` (event przyrasta, `actor=user:local`), guardy surfują jako SZCZERY stan przycisków (UI nie kłamie).
BEZ „Zatwierdź" (v1 osi obserwatorium nie ma approve). `importorskip` — bez PySide6 plik się pomija (§7.2)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo
from horreum.gui import app as appmod
from horreum.gui import queries
from horreum.gui.app import (
    OBS_COL_FRAMES, OBS_COL_ID, OBS_COL_LAT, OBS_COL_NAME, ObservatoryAxisView,
)

from PySide6.QtWidgets import QApplication

NOW = "2026-07-03T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path):
    """Świeże okno osi obserwatorium na bazie z 2 stanowiskami (DOM 2 klatki, PRACA 1 klatka). Punkty
    >4 km od siebie → dwa osobne stanowiska. `now_fn` stały (eventy deterministyczne)."""
    con = db.open_db(str(tmp_path / "h.db"))
    dom, _ = repo.propose_observatory(con, lat=53.4, lon=114.4, now=NOW)
    praca, _ = repo.propose_observatory(con, lat=42.1, lon=123.7, now=NOW)   # >4 km → osobne
    for i, oid in enumerate([dom, dom, praca]):
        fid, _ = repo.upsert_frame(con, sha1_data=f"s{i}", kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        repo.assign_observatory(con, frame_id=fid, observatory_id=oid, now=NOW)
    w = ObservatoryAxisView(con, now_fn=lambda: NOW)
    yield w, con, {"dom": dom, "praca": praca}
    w.close()
    con.close()


def _row_of(w, oid):
    for r in range(w.table.rowCount()):
        if w.table.item(r, OBS_COL_ID).data(0x0100) == oid:    # Qt.UserRole
            return r
    return -1


def _active_ids(w):
    return {w.table.item(r, OBS_COL_ID).data(0x0100) for r in range(w.table.rowCount())}


def _events(con, verb=None):
    if verb is None:
        return con.execute("SELECT count(*) FROM event").fetchone()[0]
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _select_target(w, oid):
    for i in range(w.combo_target.count()):
        if w.combo_target.itemData(i) == oid:
            w.combo_target.setCurrentIndex(i)
            return
    raise AssertionError(f"target #{oid} nie ma w combo")


# --- lista główna: stan widoczny bez klikania ---

def test_lista_stanowisk_z_licznoscia(win):
    w, con, ids = win
    assert _active_ids(w) == {ids["dom"], ids["praca"]}
    r = _row_of(w, ids["dom"])
    assert w.table.item(r, OBS_COL_NAME).text() == ""            # proposed bez nazwy
    assert w.table.item(r, OBS_COL_LAT).text() == "53.4000"      # stała precyzja .4f (wizytator #2)
    assert w.table.item(r, OBS_COL_FRAMES).text() == "2"         # DOM = 2 klatki
    assert w.table.item(_row_of(w, ids["praca"]), OBS_COL_FRAMES).text() == "1"
    assert w.obs_empty.isHidden()                               # są stanowiska → nota schowana


def test_pusty_stan_nota_w_widoku(qapp, tmp_path):
    """Wizytator #1: pusta oś pokazuje NOTĘ w obszarze widoku (nie gołe nagłówki + ulotny flash, który
    gospodarz nadpisuje) — wzorzec 1:1 z ObjectAxisView.lib_empty."""
    con = db.open_db(str(tmp_path / "empty.db"))
    w = ObservatoryAxisView(con, now_fn=lambda: NOW)
    try:
        assert not w.obs_empty.isHidden()                      # nota odkrywalna w widoku
        assert w.table.isHidden()                              # gołe nagłówki schowane
    finally:
        w.close()
        con.close()


# --- label in-line → repo (jedna klinga) ---

def test_label_inline_idzie_przez_repo(win):
    w, con, ids = win
    before = _events(con, "observatory.named")
    w.table.selectRow(_row_of(w, ids["dom"]))
    w.table.item(_row_of(w, ids["dom"]), OBS_COL_NAME).setText("Dom")   # edycja in-line = itemChanged
    assert _events(con, "observatory.named") == before + 1
    assert con.execute("SELECT name FROM observatory WHERE id=?", (ids["dom"],)).fetchone()[0] == "Dom"
    assert w.table.item(_row_of(w, ids["dom"]), OBS_COL_NAME).text() == "Dom"


def test_label_pusty_odrzucony_bez_eventu(win):
    w, con, ids = win
    before = _events(con)
    w.table.item(_row_of(w, ids["dom"]), OBS_COL_NAME).setText("   ")   # pusty po strip → ValueError
    assert _events(con) == before                                       # zero nowych eventów
    assert con.execute("SELECT name FROM observatory WHERE id=?", (ids["dom"],)).fetchone()[0] is None
    assert w.table.item(_row_of(w, ids["dom"]), OBS_COL_NAME).text() == ""   # widok wrócił do prawdy


# --- merge / unmerge przez UI ---

def test_merge_combo_rolluje_i_chowa_source(win):
    w, con, ids = win
    dom, praca = ids["dom"], ids["praca"]
    before = _events(con, "observatory.merged")
    w.table.selectRow(_row_of(w, praca))
    _select_target(w, dom)
    w._on_merge()
    assert _events(con, "observatory.merged") == before + 1
    assert praca not in _active_ids(w)                          # source zniknął z aktywnych
    assert w.table.item(_row_of(w, dom), OBS_COL_FRAMES).text() == "3"   # 2+1 pod kanonem DOM


def test_combo_nie_zawiera_zrodla_selfmerge_niemozliwy(win):
    w, _, ids = win
    w.table.selectRow(_row_of(w, ids["dom"]))
    assert ids["dom"] not in {w.combo_target.itemData(i) for i in range(w.combo_target.count())}


def test_merge_wymaga_swiadomego_celu(win):
    w, _, ids = win
    w.table.selectRow(_row_of(w, ids["praca"]))
    assert w.combo_target.currentData() is None                 # placeholder na wejściu
    assert not w.btn_merge.isEnabled()                          # bez celu — nie scala na ślepo
    _select_target(w, ids["dom"])
    assert w.btn_merge.isEnabled()


def test_merge_zrodla_z_czlonkami_wylaczony(win):
    """Inwariant głębokość ≤ 1 jako SZCZERY stan UI: po praca→dom stanowisko DOM ma członka, więc
    merge DOM-jako-źródło jest wyłączony (zamiast klik→ValueError)."""
    w, con, ids = win
    dom, praca = ids["dom"], ids["praca"]
    w.table.selectRow(_row_of(w, praca))
    _select_target(w, dom)
    w._on_merge()
    w.table.selectRow(_row_of(w, dom))
    assert not w.btn_merge.isEnabled()


def test_unmerge_z_panelu_wraca_kanoniczny(win):
    w, con, ids = win
    dom, praca = ids["dom"], ids["praca"]
    w.table.selectRow(_row_of(w, praca))
    _select_target(w, dom)
    w._on_merge()
    assert praca not in _active_ids(w)
    before = _events(con, "observatory.unmerged")
    w.table.selectRow(_row_of(w, dom))                          # zaznacz kanon → panel pokazuje członka
    assert w.members.count() == 1
    w.members.setCurrentRow(0)
    assert w.btn_unmerge.isEnabled()
    w._on_unmerge()
    assert _events(con, "observatory.unmerged") == before + 1
    assert praca in _active_ids(w)                              # wrócił jako kanoniczny
    assert con.execute("SELECT merged_into FROM observatory WHERE id=?", (praca,)).fetchone()[0] is None


# --- audyt + render + brak zapisu poza repo ---

def test_panel_audytu_pokazuje_eventy(win):
    w, con, ids = win
    w.table.selectRow(_row_of(w, ids["dom"]))
    w.table.item(_row_of(w, ids["dom"]), OBS_COL_NAME).setText("Dom")
    w.table.selectRow(_row_of(w, ids["dom"]))
    verbs = [w.events.item(i).text() for i in range(w.events.count())]
    assert any("observatory.named" in v for v in verbs)
    assert any("user:local" in v for v in verbs)


def test_render_offscreen_niepusty(win):
    w, _, _ = win
    img = w.grab()
    assert img.width() > 0 and img.height() > 0


def test_widget_nie_pisze_do_bazy_z_pominieciem_repo(win):
    w, con, ids = win
    before = _events(con)
    w.refresh()
    w.grab()
    w.table.selectRow(_row_of(w, ids["praca"]))
    queries.active_observatories(con)
    assert _events(con) == before


# --- mapa stanowisk (F8) ---

def test_mapa_dostaje_stanowiska_z_refresh(win):
    w, _, ids = win
    # mapa karmiona TYMI SAMYMI wierszami co tabela (SPOT); oba stanowiska trafiają do scatteru.
    assert {s[0] for s in w.map_view._sites} == {ids["dom"], ids["praca"]}


def test_mapa_render_niejednolity(win):
    """F8 F10: paintEvent połyka wyjątki (stderr, nie fail) — smoke asertuje, że mapa COŚ namalowała
    (tło + kontury + punkty), nie tylko że obraz ma wymiary."""
    w, _, _ = win
    w.map_view.resize(320, 240)                    # resizeEvent → _refit (transform + cache konturów)
    img = w.map_view.grab().toImage()
    colors = {img.pixel(x, y) for y in range(0, img.height(), 4) for x in range(0, img.width(), 4)}
    assert len(colors) >= 2, "mapa jednolita — nic nie namalowane (rzut/paint padł cicho)"


def test_osm_przycisk_szczery_disabled_i_link(win, monkeypatch):
    """Przycisk OSM wyłączony bez zaznaczenia, włączony po; klik otwiera URL z GPS zaznaczonego
    stanowiska (F8 F8 — źródło współrzędnych z `_obs_coords`). QDesktopServices podmieniony, by test
    NIE otwierał przeglądarki."""
    w, _, ids = win
    opened = []

    class _FakeQDS:
        @staticmethod
        def openUrl(url):
            opened.append(url.toString())

    monkeypatch.setattr(appmod, "QDesktopServices", _FakeQDS)
    w.table.clearSelection()
    assert not w.btn_osm.isEnabled()               # bez zaznaczenia — brak celu (szczery disabled)
    w.table.selectRow(_row_of(w, ids["dom"]))
    assert w.btn_osm.isEnabled()
    w._on_open_osm()
    assert opened and "mlat=53.400000" in opened[0]   # lat DOM = 53.4 (fixture), format .6f


# --- interakcja z mapą: hit-test klik + hover (#10) ---

def _press(w, px, py):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(px, py), Qt.LeftButton, Qt.LeftButton,
                     Qt.NoModifier)
    w.map_view.mousePressEvent(ev)


def test_mapa_klik_w_punkt_emituje_siteclicked(win):
    """Hit-test: klik lewym w punkt → sygnał `siteClicked(oid)` klikniętego stanowiska."""
    w, _, ids = win
    w.map_view.resize(320, 240)                    # resizeEvent → _refit ustawia transform
    got = []
    w.map_view.siteClicked.connect(got.append)
    px, py = w.map_view._xf.to_px(53.4, 114.4)     # pozycja DOM
    _press(w, px, py)
    assert got == [ids["dom"]]


def test_mapa_klik_poza_punktem_nie_emituje(win):
    """Klik w tło (poza progiem `_HIT_PX`) nie emituje — mapa nie zgaduje, tabela zostaje właścicielem."""
    w, _, _ = win
    w.map_view.resize(320, 240)
    got = []
    w.map_view.siteClicked.connect(got.append)
    _press(w, 2.0, 2.0)                            # narożnik = margines, daleko od punktów
    assert got == []


def test_mapa_klik_zaznacza_wiersz_tabeli(win):
    """Wpięcie mapa→tabela: `siteClicked` → `selectRow` → kaskada `_on_selection_changed`
    (wyróżnienie mapy + stan OSM). Tabela zostaje SPOT selekcji."""
    w, _, ids = win
    w.table.selectRow(_row_of(w, ids["praca"]))
    assert w._selected_observatory_id() == ids["praca"]
    w.map_view.siteClicked.emit(ids["dom"])        # symuluj klik w DOM
    assert w._selected_observatory_id() == ids["dom"]   # tabela przeskoczyła (mapa→tabela)
    assert w.map_view._selected == ids["dom"]           # wyróżnienie mapy zsynchronizowane
    assert w.btn_osm.isEnabled()                        # OSM wskazuje nowy cel


def test_mapa_hover_ustawia_i_gasi(win):
    """Hover nad punktem ustawia `_hover` (etykieta pod kursorem); zejście kursora gasi."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    w, _, ids = win
    w.map_view.resize(320, 240)
    px, py = w.map_view._xf.to_px(53.4, 114.4)     # DOM
    w.map_view.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(px, py), Qt.NoButton,
                                          Qt.NoButton, Qt.NoModifier))
    assert w.map_view._hover == ids["dom"]
    w.map_view.leaveEvent(QEvent(QEvent.Leave))
    assert w.map_view._hover is None


def test_mapa_hover_render_niejednolity(win):
    """Smoke dekolizji: paintEvent ze stackiem etykiet hover COŚ maluje (bez wyjątku, non-uniform)."""
    w, _, ids = win
    w.map_view.resize(320, 240)
    w.map_view._hover = ids["dom"]
    img = w.map_view.grab().toImage()
    colors = {img.pixel(x, y) for y in range(0, img.height(), 4) for x in range(0, img.width(), 4)}
    assert len(colors) >= 2


# --- sort po kliku nagłówka (decyzja CEO 2026-10-20) ---

@pytest.fixture
def sort_win(qapp, tmp_path):
    """Cztery stanowiska pod sort: o1 Dom 53.4/114.4 - 9 klatek, o2 „działka” -33.9/18.4 - 10 klatek
    (szerokość ujemna; 9 < 10 liczbowo, „10” < „9” tekstowo), o3 bez nazwy 42.1/123.7 - 2 klatki,
    o4 „Bieszczady” 50.0/-5.0 - 0 klatek. Okno pokazane - nagłówek ma geometrię pod realny klik."""
    con = db.open_db(str(tmp_path / "sort.db"))
    oids, n = [], 0
    for (lat, lon), nazwa, klatki in (((53.4, 114.4), "Dom", 9), ((-33.9, 18.4), "działka", 10),
                                      ((42.1, 123.7), None, 2), ((50.0, -5.0), "Bieszczady", 0)):
        oid, _ = repo.propose_observatory(con, lat=lat, lon=lon, now=NOW)
        oids.append(oid)
        if nazwa:
            repo.label_observatory(con, observatory_id=oid, name=nazwa, now=NOW)
        for _ in range(klatki):
            fid, _ = repo.upsert_frame(con, sha1_data=f"sort{n}", kind="light", filetype="fits",
                                       camera_id=None, now=NOW)
            repo.assign_observatory(con, frame_id=fid, observatory_id=oid, now=NOW)
            n += 1
    w = ObservatoryAxisView(con, now_fn=lambda: NOW)
    w.resize(900, 700)
    w.show()
    QApplication.processEvents()
    yield w, con, oids
    w.close()
    con.close()


def _klik_naglowka(w, col):
    """Realny klik myszą w sekcję nagłówka - nagłówek sam przełącza kolumnę i kierunek."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    hdr = w.table.horizontalHeader()
    x = hdr.sectionViewportPosition(col) + hdr.sectionSize(col) // 2
    QTest.mouseClick(hdr.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, hdr.height() // 2))


def _kolejnosc(w):
    return [w.table.item(r, OBS_COL_ID).data(0x0100) for r in range(w.table.rowCount())]


def _nazwy(con):
    return dict(con.execute("SELECT id, name FROM observatory").fetchall())


def test_sort_domyslnie_porzadek_read_modelu(sort_win):
    """Bez kliku - porządek read-modelu, bez strzałki. Mutant: domyślny sort po kolumnie."""
    w, con, o = sort_win
    assert _kolejnosc(w) == [r["id"] for r in queries.active_observatories(con)]
    assert w.table.horizontalHeader().sortIndicatorSection() == -1


def test_sort_klatki_liczbowo_i_odwrocenie(sort_win):
    """Klik „Klatki” → 0, 2, 9, 10 (liczbowo), drugi klik → odwrotnie, strzałka idzie za kierunkiem.
    Mutant: sort po tekście komórki („10” przed „9”)."""
    from PySide6.QtCore import Qt
    w, con, o = sort_win
    _klik_naglowka(w, OBS_COL_FRAMES)
    assert _kolejnosc(w) == [o[3], o[2], o[0], o[1]]
    _klik_naglowka(w, OBS_COL_FRAMES)
    assert _kolejnosc(w) == [o[1], o[0], o[2], o[3]]
    assert w.table.horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder


def test_sort_wspolrzedne_liczbowo(sort_win):
    """Szerokość: -33.9, 42.1, 50.0, 53.4; długość: -5.0, 18.4, 114.4, 123.7 - liczbowo.
    Mutant: sort po tekście komórki („114.4000” przed „18.4000”)."""
    from horreum.gui.app import OBS_COL_LON
    w, con, o = sort_win
    _klik_naglowka(w, OBS_COL_LAT)
    assert _kolejnosc(w) == [o[1], o[2], o[3], o[0]]
    _klik_naglowka(w, OBS_COL_LON)
    assert _kolejnosc(w) == [o[3], o[1], o[0], o[2]]


def test_sort_nazwa_bez_wielkosci_liter_nienazwane_na_koncu(sort_win):
    """Nazwa: Bieszczady, Dom, działka (bez wielkości liter), stanowisko bez nazwy na końcu w obu
    kierunkach. Mutanty: porównanie z wielkością liter; puste odwracane razem z resztą."""
    w, con, o = sort_win
    _klik_naglowka(w, OBS_COL_NAME)
    assert _kolejnosc(w) == [o[3], o[0], o[1], o[2]]
    _klik_naglowka(w, OBS_COL_NAME)
    assert _kolejnosc(w) == [o[1], o[0], o[3], o[2]]


def test_sort_przezywa_refresh_a_mapa_stoi_w_porzadku_read_modelu(sort_win):
    """Porządek i kierunek stoją po `refresh()`; mapa dostaje ten sam zbiór stanowisk w porządku
    read-modelu (kolejność rysowania i klik w nakładające się punkty nie zależą od sortu tabeli).
    Mutanty: `refresh` bez sortu; mapa karmiona wierszami posortowanymi."""
    w, con, o = sort_win
    _klik_naglowka(w, OBS_COL_FRAMES)
    _klik_naglowka(w, OBS_COL_FRAMES)
    w.refresh()
    assert _kolejnosc(w) == [o[1], o[0], o[2], o[3]]
    assert [s[0] for s in w.map_view._sites] == [r["id"] for r in queries.active_observatories(con)]


def test_sort_edycja_nazwy_trafia_wlasciwe_stanowisko_i_zaznaczenie_idzie_za_nim(sort_win):
    """Po sorcie nazw zmiana nazwy w kolumnie sortu: zapis do stanowiska z wiersza (baza), wiersz
    staje na nowym miejscu z zaznaczeniem. Mutant: id z pozycji w read-modelu."""
    w, con, o = sort_win
    _klik_naglowka(w, OBS_COL_NAME)                                           # o4, o1, o2, o3
    r = _row_of(w, o[3])
    assert r == 0
    w.table.selectRow(r)
    przed = _nazwy(con)
    w.table.item(r, OBS_COL_NAME).setText("Zakopane")
    assert _nazwy(con) == {**przed, o[3]: "Zakopane"}
    assert _kolejnosc(w) == [o[0], o[1], o[3], o[2]]
    assert w._selected_observatory_id() == o[3]


# --- refresh przy otwartym edytorze mówi na pasku (decyzja CEO 2026-10-20) ---

def _otworz_edytor_nazwy(w, oid, tekst):
    """Realny edytor nazwy (`table.edit`) na wierszu `oid` z wpisanym `tekst`."""
    from PySide6.QtWidgets import QAbstractItemView
    idx = w.table.model().index(_row_of(w, oid), OBS_COL_NAME)
    w.table.setCurrentIndex(idx)
    w.table.edit(idx)
    QApplication.processEvents()
    assert w.table.state() == QAbstractItemView.EditingState
    w.table.focusWidget().setText(tekst)


def test_refresh_przy_otwartym_edytorze_nazwy_mowi_ze_wpis_przepadl(sort_win):
    """Edytor nazwy otwarty, przeładowanie z zewnątrz: zero zapisu, zdanie na pasku.
    Mutant: `refresh` bez pytania o otwarty edytor."""
    from horreum.gui import i18n
    w, con, o = sort_win
    msgs = []
    w.status_message.connect(msgs.append)
    przed = _nazwy(con)
    _otworz_edytor_nazwy(w, o[0], "w-trakcie")
    w.refresh()
    assert msgs[-1] == i18n.t("axis.edit_interrupted")
    assert _nazwy(con) == przed


def test_refresh_bez_edytora_i_z_zatwierdzenia_nazwy_milczy(sort_win):
    """Bez edytora - bez zdania; zatwierdzenie Enterem - „zapisano”, nie „przepadło”.
    Mutant: zdanie bez wyciszenia drogi zatwierdzenia."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from horreum.gui import i18n
    w, con, o = sort_win
    msgs = []
    w.status_message.connect(msgs.append)
    w.refresh()
    assert i18n.t("axis.edit_interrupted") not in msgs
    _otworz_edytor_nazwy(w, o[0], "Ogród")
    QTest.keyClick(w.table.focusWidget(), Qt.Key_Return)
    QApplication.processEvents()
    assert _nazwy(con)[o[0]] == "Ogród"
    assert i18n.t("axis.edit_interrupted") not in msgs
    assert msgs[-1] == i18n.t("axis.obs.name_saved")


def test_mapa_i_tabela_sprzezone_po_sorcie(sort_win):
    """Po sorcie malejącym klik w punkt mapy stanowiska, które zmieniło wiersz (o1: wiersz 0 → 1),
    zaznacza JEGO wiersz; zaznaczenie, mapa i panel prawy mówią o nim. Potem zaznaczenie innego
    wiersza tabeli przestawia wyróżnienie mapy. Mutant: mapa→tabela po pozycji w read-modelu
    (wiersz 0 = o2 po sorcie)."""
    w, con, o = sort_win
    assert _row_of(w, o[0]) == 0
    _klik_naglowka(w, OBS_COL_FRAMES)
    _klik_naglowka(w, OBS_COL_FRAMES)                                         # o2, o1, o3, o4
    assert _row_of(w, o[0]) == 1
    w.map_view.siteClicked.emit(o[0])
    assert w.table.selectionModel().selectedRows()[0].row() == 1
    assert w._selected_observatory_id() == o[0]
    assert w.map_view._selected == o[0]
    cele = {w.combo_target.itemData(i) for i in range(w.combo_target.count())}
    assert cele == {None, o[1], o[2], o[3]}                                   # panel: cel ≠ źródło o1
    assert any("observatory.named" in w.events.item(i).text() for i in range(w.events.count()))
    w.table.selectRow(_row_of(w, o[2]))
    assert w.map_view._selected == o[2]
    assert w._selected_observatory_id() == o[2]
    assert all("observatory.named" not in w.events.item(i).text()            # o3 bez nazwy
               for i in range(w.events.count()))
