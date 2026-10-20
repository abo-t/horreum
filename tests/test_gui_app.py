"""Widżety okna osi teleskopu (`horreum.gui.app`, PLAN_gui §5/§7) — testy STERUJĄCE realnym oknem
Qt (offscreen) na deterministycznej bazie §8. Sprawdzają glue widget↔baza: lista odbija read-model,
akcje idą przez `repo` (event przyrasta), guardy surfują jako SZCZERY stan przycisków (UI nie kłamie),
a render offscreen nie jest pusty.

`importorskip` na poziomie MODUŁU (PLAN_gui §4, rec. nr 9): w środowisku BEZ PySide6 cały plik się
POMIJA, nie wysadzając kolekcji — to czyni §7.2 (pełny pytest bez Qt) prawdziwym. `QT_QPA_PLATFORM=
offscreen` ustawiamy PRZED importem Qt. Bez pytest-qt — QApplication zarządzamy ręcznie, a akcje
wołamy jak kliknięcia (handlery `_on_*`)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db
from horreum.gui import queries
from horreum.gui.app import (
    COL_CANON, COL_FRAMES, COL_ID, COL_LABEL, COL_STATUS, TelescopeAxisWindow,
)

from fixture_s8 import seed

from PySide6.QtWidgets import QApplication

NOW = "2026-06-29T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path):
    """Świeże okno na świeżej bazie §8 (`now_fn` stały — eventy deterministyczne). Połączenie zamyka
    fixture (okno nie jest właścicielem con)."""
    con = db.open_db(str(tmp_path / "s8.db"))
    ids = seed(con)
    w = TelescopeAxisWindow(con, now_fn=lambda: NOW)
    yield w, con, ids
    w.close()
    con.close()


def _row_of(w, tid):
    for r in range(w.table.rowCount()):
        if w.table.item(r, COL_ID).data(0x0100) == tid:    # Qt.UserRole
            return r
    return -1


def _active_ids(w):
    return {w.table.item(r, COL_ID).data(0x0100) for r in range(w.table.rowCount())}


def _events(con, verb=None):
    if verb is None:
        return con.execute("SELECT count(*) FROM event").fetchone()[0]
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _select_target(w, tid):
    for i in range(w.combo_target.count()):
        if w.combo_target.itemData(i) == tid:
            w.combo_target.setCurrentIndex(i)
            return
    raise AssertionError(f"target #{tid} nie ma w combo")


# --- lista główna: stan widoczny bez klikania ---

def test_lista_aktywne_z_licznoscia(win):
    w, con, ids = win
    assert _active_ids(w) == {ids["A"], ids["B"], ids["C"], ids["D"]}
    r = _row_of(w, ids["A"])
    assert w.table.item(r, COL_CANON).text() == "A140R"          # tożsamość z nagłówka (PF-2)
    assert w.table.item(r, COL_LABEL).text() == ""               # proposed bez etykiety
    assert w.table.item(r, COL_STATUS).text() == "proposed"
    assert w.table.item(r, COL_FRAMES).text() == "2"             # A = 2 klatki
    assert w.table.item(_row_of(w, ids["D"]), COL_FRAMES).text() == "0"   # D bez klatek nie znika


# --- label in-line → repo (jedna klinga) ---

def test_label_inline_idzie_przez_repo(win):
    w, con, ids = win
    before = _events(con, "telescope.labeled")
    w.table.selectRow(_row_of(w, ids["A"]))
    w.table.item(_row_of(w, ids["A"]), COL_LABEL).setText("A140R")   # edycja in-line = itemChanged
    assert _events(con, "telescope.labeled") == before + 1
    assert con.execute("SELECT label FROM telescope WHERE id=?", (ids["A"],)).fetchone()[0] == "A140R"
    assert w.table.item(_row_of(w, ids["A"]), COL_LABEL).text() == "A140R"


def test_label_pusty_odrzucony_bez_eventu(win):
    w, con, ids = win
    before = _events(con)
    w.table.item(_row_of(w, ids["A"]), COL_LABEL).setText("   ")     # pusty po strip → ValueError
    assert _events(con) == before                                    # zero nowych eventów
    assert con.execute("SELECT label FROM telescope WHERE id=?", (ids["A"],)).fetchone()[0] is None
    assert w.table.item(_row_of(w, ids["A"]), COL_LABEL).text() == ""   # widok wrócił do prawdy bazy


# --- approve ---

def test_approve_button_i_szczery_stan(win):
    w, con, ids = win
    before = _events(con, "telescope.approved")
    w.table.selectRow(_row_of(w, ids["A"]))
    assert w.btn_approve.isEnabled()                 # proposed → można zatwierdzić
    w._on_approve()
    assert _events(con, "telescope.approved") == before + 1
    assert con.execute("SELECT status FROM telescope WHERE id=?", (ids["A"],)).fetchone()[0] == "approved"
    w.table.selectRow(_row_of(w, ids["A"]))
    assert not w.btn_approve.isEnabled()             # UI nie kłamie: już approved → wyłączony


# --- merge / unmerge przez UI ---

def test_merge_combo_rolluje_i_chowa_source(win):
    w, con, ids = win
    A, B = ids["A"], ids["B"]
    before = _events(con, "telescope.merged")
    w.table.selectRow(_row_of(w, A))
    _select_target(w, B)
    w._on_merge()
    assert _events(con, "telescope.merged") == before + 1
    assert A not in _active_ids(w)                   # source zniknął z aktywnych
    assert w.table.item(_row_of(w, B), COL_FRAMES).text() == "5"   # 2+3 pod kanonem B (kolizja kamery)


def test_combo_nie_zawiera_zrodla_selfmerge_niemozliwy(win):
    w, _, ids = win
    w.table.selectRow(_row_of(w, ids["A"]))
    assert ids["A"] not in {w.combo_target.itemData(i) for i in range(w.combo_target.count())}


def test_merge_wymaga_swiadomego_celu(win):
    """Wizytator P2: po zaznaczeniu źródła „Scal" jest WYŁĄCZONY (combo na placeholderze `None`),
    włącza się dopiero po wskazaniu realnego celu — merge nie wyzwoli się jednym klikiem w przypadkowy
    pierwszy teleskop (merge to świadoma deklaracja „to ten sam instrument")."""
    w, _, ids = win
    w.table.selectRow(_row_of(w, ids["A"]))
    assert w.combo_target.currentData() is None        # placeholder „— wybierz cel —" na wejściu
    assert not w.btn_merge.isEnabled()                 # bez wskazanego celu — nie scala na ślepo
    _select_target(w, ids["B"])
    assert w.btn_merge.isEnabled()                     # świadomy wybór celu → aktywny


def test_merge_zrodla_z_czlonkami_wylaczony(win):
    """Inwariant głębokość ≤ 1 (§3a) jako SZCZERY stan UI: po A→B teleskop B ma członka, więc merge
    B-jako-źródło jest wyłączony (zamiast klik→ValueError)."""
    w, con, ids = win
    A, B = ids["A"], ids["B"]
    w.table.selectRow(_row_of(w, A))
    _select_target(w, B)
    w._on_merge()
    w.table.selectRow(_row_of(w, B))
    assert not w.btn_merge.isEnabled()


def test_unmerge_z_panelu_wraca_kanoniczny(win):
    w, con, ids = win
    A, B = ids["A"], ids["B"]
    w.table.selectRow(_row_of(w, A))
    _select_target(w, B)
    w._on_merge()
    assert A not in _active_ids(w)
    before = _events(con, "telescope.unmerged")
    w.table.selectRow(_row_of(w, B))                 # zaznacz kanon → panel pokazuje członka A
    assert w.members.count() == 1
    w.members.setCurrentRow(0)
    assert w.btn_unmerge.isEnabled()                 # członek zaznaczony → cofnięcie dostępne
    w._on_unmerge()
    assert _events(con, "telescope.unmerged") == before + 1
    assert A in _active_ids(w)                        # wrócił jako kanoniczny
    assert con.execute("SELECT merged_into FROM telescope WHERE id=?", (A,)).fetchone()[0] is None


# --- audyt widoczny + render ---

def test_panel_audytu_pokazuje_eventy(win):
    w, con, ids = win
    w.table.selectRow(_row_of(w, ids["A"]))
    w.table.item(_row_of(w, ids["A"]), COL_LABEL).setText("A140R")
    w.table.selectRow(_row_of(w, ids["A"]))
    verbs = [w.events.item(i).text() for i in range(w.events.count())]
    assert any("telescope.labeled" in v for v in verbs)
    assert any("user:local" in v for v in verbs)     # actor user:* złożony w repo, widoczny w audycie


def test_render_offscreen_niepusty(win):
    w, _, _ = win
    img = w.grab()
    assert img.width() > 0 and img.height() > 0      # okno realnie się renderuje (offscreen)


def test_widget_nie_pisze_do_bazy_z_pominieciem_repo(win):
    """Czysty render/odczyt (refresh, grab, zmiana zaznaczenia) NIE dokłada eventu — zapis idzie
    tylko akcjami przez repo."""
    w, con, ids = win
    before = _events(con)
    w.refresh()
    w.grab()
    w.table.selectRow(_row_of(w, ids["C"]))
    queries.active_telescopes(con)
    assert _events(con) == before


# --- sort po kliku nagłówka (polecenie CEO 2026-10-20) ---

@pytest.fixture
def sort_win(qapp, tmp_path):
    """Baza §8 dociążona pod sort: C = 9 klatek, D = 10 (liczbowo 9 < 10, tekstowo „10” < „9”);
    etykiety B = „alfa”, A = „Beta” (wielka litera - sort bez wielkości liter), C i D bez etykiety.
    Okno pokazane, żeby nagłówek miał geometrię pod realny klik."""
    from fixture_s8 import NOW as SEED_NOW
    from horreum import repo
    con = db.open_db(str(tmp_path / "sort.db"))
    ids = seed(con)
    cfg_d, _ = repo.propose_config(con, telescope_id=ids["D"], camera_id=ids["cam2"], now=SEED_NOW)
    for cfg, ile, znak in ((ids["cfg_c"], 7, "c"), (cfg_d, 10, "d")):
        for i in range(ile):
            fid, _ = repo.upsert_frame(con, sha1_data=f"sha-sort-{znak}{i}", kind="light",
                                       filetype="fits", camera_id=ids["cam2"], now=SEED_NOW)
            repo.assign_config(con, frame_id=fid, config_id=cfg, now=SEED_NOW)
    repo.label_telescope(con, telescope_id=ids["B"], label="alfa", now=SEED_NOW)
    repo.label_telescope(con, telescope_id=ids["A"], label="Beta", now=SEED_NOW)
    w = TelescopeAxisWindow(con, now_fn=lambda: NOW)
    w.show()
    QApplication.processEvents()
    yield w, con, ids
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
    return [w.table.item(r, COL_ID).data(0x0100) for r in range(w.table.rowCount())]


def test_sort_domyslnie_porzadek_read_modelu_bez_strzalki(sort_win):
    """Bez kliku tabela stoi w porządku read-modelu, a nagłówek nie pokazuje strzałki.
    Mutant: domyślny sort po którejś kolumnie przy budowie widoku."""
    w, con, ids = sort_win
    assert _kolejnosc(w) == [r["id"] for r in queries.active_telescopes(con)]
    assert w.table.horizontalHeader().sortIndicatorSection() == -1
    assert not w.table.isSortingEnabled()


def test_sort_klatki_liczbowo_i_odwrocenie(sort_win):
    """Klik „Klatki” → rosnąco LICZBOWO (9 przed 10), drugi klik → malejąco; strzałka idzie za
    kierunkiem. Mutant: sort po tekście komórki („10” przed „9”)."""
    from PySide6.QtCore import Qt
    w, con, ids = sort_win
    hdr = w.table.horizontalHeader()
    _klik_naglowka(w, COL_FRAMES)
    assert _kolejnosc(w) == [ids["A"], ids["B"], ids["C"], ids["D"]]       # 2, 3, 9, 10
    assert [w.table.item(r, COL_FRAMES).text() for r in range(4)] == ["2", "3", "9", "10"]
    assert (hdr.sortIndicatorSection(), hdr.sortIndicatorOrder()) == (COL_FRAMES, Qt.AscendingOrder)
    _klik_naglowka(w, COL_FRAMES)
    assert _kolejnosc(w) == [ids["D"], ids["C"], ids["B"], ids["A"]]
    assert hdr.sortIndicatorOrder() == Qt.DescendingOrder


def test_sort_tekst_bez_wielkosci_liter_puste_na_koncu_w_obu_kierunkach(sort_win):
    """Etykieta: „alfa” < „Beta” mimo wielkiej litery; C i D bez etykiety na końcu rosnąco
    i malejąco, w porządku read-modelu. Mutanty: porównanie z wielkością liter („Beta” < „alfa”);
    puste odwracane razem z resztą (na górze malejąco)."""
    w, con, ids = sort_win
    _klik_naglowka(w, COL_LABEL)
    assert _kolejnosc(w) == [ids["B"], ids["A"], ids["C"], ids["D"]]
    _klik_naglowka(w, COL_LABEL)
    assert _kolejnosc(w) == [ids["A"], ids["B"], ids["C"], ids["D"]]


def test_sort_przezywa_refresh_i_edycje(sort_win):
    """Porządek i kierunek stoją po `refresh()` (wejście na stronę, scalanie, zapis) i po zapisie
    etykiety, który sam przeładowuje widok. Mutant: `refresh` układający wiersze z read-modelu."""
    from PySide6.QtCore import Qt
    w, con, ids = sort_win
    _klik_naglowka(w, COL_FRAMES)
    _klik_naglowka(w, COL_FRAMES)                                             # malejąco
    w.refresh()
    assert _kolejnosc(w) == [ids["D"], ids["C"], ids["B"], ids["A"]]
    w.table.item(_row_of(w, ids["C"]), COL_LABEL).setText("gamma")          # zapis → refresh
    assert _kolejnosc(w) == [ids["D"], ids["C"], ids["B"], ids["A"]]
    hdr = w.table.horizontalHeader()
    assert (hdr.sortIndicatorSection(), hdr.sortIndicatorOrder()) == (COL_FRAMES, Qt.DescendingOrder)


def test_sort_zaznaczenie_idzie_za_teleskopem_i_panel_prawy(sort_win):
    """Zaznaczenie przed sortem zostaje przy TYM SAMYM teleskopie na nowym wierszu, a wiersz
    zaznaczony po sorcie karmi panel prawy właściwym teleskopem (średnica D: 418 / 4.5).
    Mutant: zaznaczenie przywracane po numerze wiersza."""
    from horreum.gui import i18n
    w, con, ids = sort_win
    w.table.selectRow(_row_of(w, ids["B"]))
    _klik_naglowka(w, COL_FRAMES)
    _klik_naglowka(w, COL_FRAMES)                                             # D, C, B, A
    assert w._selected_telescope_id() == ids["B"] and _row_of(w, ids["B"]) == 2
    assert w.table.selectionModel().selectedRows()[0].row() == 2
    w.table.selectRow(0)
    assert w._selected_telescope_id() == ids["D"]
    assert w.aperture.text() == i18n.t("axis.tel.aperture", d="93", focal="418", f="4.5")


def test_sort_edycja_etykiety_w_kolumnie_sortu_trafia_wlasciwy_teleskop(sort_win):
    """Zmiana etykiety w kolumnie, po której stoi sort: zapis idzie do teleskopu z wiersza (baza),
    a po przeładowaniu wiersz staje na nowym miejscu z zaznaczeniem przy sobie.
    Mutant: id teleskopu z pozycji w `rows` read-modelu zamiast z kolumny ID wiersza."""
    w, con, ids = sort_win
    _klik_naglowka(w, COL_LABEL)                                              # B alfa, A Beta, C, D
    r = _row_of(w, ids["A"])
    assert r == 1
    w.table.selectRow(r)
    w.table.item(r, COL_LABEL).setText("Aaa")
    assert con.execute("SELECT label FROM telescope WHERE id=?", (ids["A"],)).fetchone()[0] == "Aaa"
    assert con.execute("SELECT label FROM telescope WHERE id=?", (ids["B"],)).fetchone()[0] == "alfa"
    assert _kolejnosc(w) == [ids["A"], ids["B"], ids["C"], ids["D"]]
    assert w._selected_telescope_id() == ids["A"]


def test_sort_wpis_optyki_trafia_teleskop_mimo_przestawienia_w_locie(sort_win):
    """Wpis edytora optyki idzie po `singleShot(0)`; gdy między zatwierdzeniem a wykonaniem tabela
    przestawi się (klik nagłówka), ogniskowa ląduje w teleskopie, którego komórkę edytowano.
    Mutant: delegat kotwiczy wpis numerem wiersza."""
    from horreum.gui.app import COL_FOCAL
    w, con, ids = sort_win
    _klik_naglowka(w, COL_FOCAL)                                              # D 418, A 784, B 794, C 1624
    idx = w.table.model().index(_row_of(w, ids["A"]), COL_FOCAL)
    ed = _edytor_optyki(w, idx, "780")
    w._optyka_delegat.setModelData(ed, w.table.model(), idx)
    _klik_naglowka(w, COL_FOCAL)                                              # malejąco, zanim wpis wejdzie
    QApplication.processEvents()
    ogn = dict(con.execute("SELECT id, focal_user FROM telescope").fetchall())
    assert ogn[ids["A"]] == 780.0
    assert [ogn[ids[k]] for k in "BCD"] == [None, None, None]


def _edytor_optyki(w, idx, tekst):
    """Edytor delegata optyki otwarty na `idx` (kotwica z `createEditor`) z wpisanym `tekst`."""
    from PySide6.QtWidgets import QStyleOptionViewItem
    ed = w._optyka_delegat.createEditor(w.table.viewport(), QStyleOptionViewItem(), idx)
    w._optyka_delegat.setEditorData(ed, idx)
    ed.setText(tekst)
    return ed


def test_edytor_optyki_kotwiczy_teleskop_z_otwarcia_mimo_refresh(sort_win):
    """Edytor otwarty na A, potem `refresh` w innym porządku (klik nagłówka, przeładowanie z innego
    widoku), dopiero potem zatwierdzenie z indeksem z chwili otwarcia: wpis trafia do A, nie do
    teleskopu, który stoi teraz w tym wierszu. Mutant: `setModelData` czyta teleskop z indeksu."""
    from horreum.gui.app import COL_FOCAL
    w, con, ids = sort_win
    _klik_naglowka(w, COL_FOCAL)                                              # D, A, B, C
    idx = w.table.model().index(_row_of(w, ids["A"]), COL_FOCAL)
    ed = _edytor_optyki(w, idx, "780")
    _klik_naglowka(w, COL_FOCAL)                                              # C, B, A, D - w wierszu A stoi B
    assert w.table.item(idx.row(), COL_ID).data(0x0100) == ids["B"]
    w._optyka_delegat.setModelData(ed, w.table.model(), idx)
    QApplication.processEvents()
    ogn = dict(con.execute("SELECT id, focal_user FROM telescope").fetchall())
    assert ogn[ids["A"]] == 780.0
    assert [ogn[ids[k]] for k in "BCD"] == [None, None, None]


def test_edytor_optyki_teleskop_zniknal_przed_wpisem_odmowa_bez_wyjatku(sort_win):
    """Teleskop scalony między otwarciem edytora a wpisem: zero zapisu, zero wyjątku, zdanie odmowy
    na pasku. Mutant: stan ręki z `_rows[tid]` (KeyError po przeładowaniu bez A)."""
    from horreum import repo
    from horreum.gui import i18n
    from horreum.gui.app import COL_FOCAL
    w, con, ids = sort_win
    msgs = []
    w.status_message.connect(msgs.append)
    idx = w.table.model().index(_row_of(w, ids["A"]), COL_FOCAL)
    ed = _edytor_optyki(w, idx, "780")
    repo.merge_telescope(con, source_id=ids["A"], target_id=ids["B"], now=NOW)
    w.refresh()
    przed = _events(con)
    w._optyka_delegat.setModelData(ed, w.table.model(), idx)
    QApplication.processEvents()
    assert _events(con) == przed
    assert [r[0] for r in con.execute("SELECT focal_user FROM telescope")] == [None] * 4
    assert msgs[-1] == i18n.t("axis.tel.optics_rejected",
                              e=i18n.t("axis.tel.optics_gone", tid=ids["A"]))
    assert ids["A"] not in _kolejnosc(w)


def _otworz_edytor_etykiety(w, tid, tekst):
    """Realny edytor etykiety (`table.edit`) na wierszu `tid` z wpisanym `tekst`."""
    from PySide6.QtWidgets import QAbstractItemView
    idx = w.table.model().index(_row_of(w, tid), COL_LABEL)
    w.table.setCurrentIndex(idx)
    w.table.edit(idx)
    QApplication.processEvents()
    assert w.table.state() == QAbstractItemView.EditingState
    w.table.focusWidget().setText(tekst)


def _etykiety(con):
    return dict(con.execute("SELECT id, label FROM telescope").fetchall())


def test_refresh_z_zewnatrz_przy_otwartym_edytorze_etykiety_nie_pisze_do_sasiada(sort_win):
    """Edytor etykiety otwarty na A, `refresh` w innym porządku BEZ zmiany fokusu (przeładowanie
    z innego widoku, koniec etapu): Qt zwalnia edytor usuwanych wierszy bez zatwierdzenia, więc
    wpis nie trafia do nikogo - ani do A, ani do teleskopu, który stanął w wierszu A.
    Mutant: `refresh` zatwierdzający otwarty edytor po przebudowie (wpis pod cudzym indeksem)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    w, con, ids = sort_win
    przed = _etykiety(con)
    _otworz_edytor_etykiety(w, ids["A"], "zly-wpis")
    w._on_sort_changed(COL_FRAMES, Qt.DescendingOrder)                        # D, C, B, A
    QApplication.processEvents()
    assert w.table.state() != QAbstractItemView.EditingState
    assert _etykiety(con) == przed


def test_klik_naglowka_przy_otwartym_edytorze_etykiety_zapisuje_w_edytowany(sort_win):
    """Klik nagłówka przy otwartym edytorze etykiety: wciśnięcie zabiera fokus i zatwierdza wpis
    PRZED sortem, więc etykieta trafia do teleskopu, na którym edycję zaczęto, a nie do sąsiada
    z nowego porządku. Mutant: id teleskopu z pozycji w porządku po sorcie."""
    w, con, ids = sort_win
    przed = _etykiety(con)
    _otworz_edytor_etykiety(w, ids["A"], "nowa")
    _klik_naglowka(w, COL_FRAMES)
    _klik_naglowka(w, COL_FRAMES)                                             # D, C, B, A
    QApplication.processEvents()
    assert _etykiety(con) == {**przed, ids["A"]: "nowa"}


# --- refresh przy otwartym edytorze mówi na pasku (decyzja CEO 2026-10-20) ---

def test_refresh_przy_otwartym_edytorze_mowi_ze_wpis_przepadl(sort_win):
    """Edytor etykiety otwarty, przeładowanie z zewnątrz: edytor zamknięty bez zapisu, a pasek mówi,
    że wpis trzeba powtórzyć. Mutant: `refresh` bez pytania o otwarty edytor."""
    from horreum.gui import i18n
    w, con, ids = sort_win
    msgs = []
    w.status_message.connect(msgs.append)
    przed = _etykiety(con)
    _otworz_edytor_etykiety(w, ids["A"], "w-trakcie")
    w.refresh()
    assert msgs[-1] == i18n.t("axis.edit_interrupted")
    assert _etykiety(con) == przed


def test_refresh_bez_edytora_i_z_zatwierdzenia_milczy(sort_win):
    """Refresh bez otwartego edytora - bez zdania o przerwanej edycji; zatwierdzenie wpisu Enterem
    (refresh z drogi zapisu zastaje edytor jeszcze otwarty) - pasek mówi „zapisano”, nie „przepadło”.
    Mutant: zdanie przy każdym refreshu albo bez wyciszenia drogi zatwierdzenia."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from horreum.gui import i18n
    w, con, ids = sort_win
    msgs = []
    w.status_message.connect(msgs.append)
    w.refresh()
    assert i18n.t("axis.edit_interrupted") not in msgs
    _otworz_edytor_etykiety(w, ids["A"], "Enterem")
    QTest.keyClick(w.table.focusWidget(), Qt.Key_Return)
    QApplication.processEvents()
    assert _etykiety(con)[ids["A"]] == "Enterem"
    assert i18n.t("axis.edit_interrupted") not in msgs
    assert msgs[-1] == i18n.t("axis.tel.label_saved")


def _ogniskowe(con):
    return dict(con.execute("SELECT id, focal_user FROM telescope").fetchall())


@pytest.mark.parametrize("zatwierdzenie", ["enter", "klik_naglowka"])
def test_realny_edytor_optyki_zapisuje_wlasciwy_teleskop_bez_zdania_o_przerwaniu(sort_win,
                                                                                 zatwierdzenie):
    """Prawdziwy edytor ogniskowej (`table.edit`, delegat optyki), zatwierdzony Enterem albo realnym
    klikiem w nagłówek (zatwierdzenie przy utracie fokusu, potem sort): wpis dochodzi do teleskopu,
    na którym edycję zaczęto, a pasek nie mówi o przerwanej edycji - wpis optyki przychodzi po
    `singleShot(0)`, gdy edytor jest już zamknięty. Mutanty: zdanie bez względu na zamknięty edytor;
    delegat kotwiczący wpis numerem wiersza."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractItemView
    from horreum.gui import i18n
    from horreum.gui.app import COL_FOCAL
    w, con, ids = sort_win
    msgs = []
    w.status_message.connect(msgs.append)
    _klik_naglowka(w, COL_FOCAL)                                              # D, A, B, C
    idx = w.table.model().index(_row_of(w, ids["A"]), COL_FOCAL)
    w.table.setCurrentIndex(idx)
    w.table.edit(idx)
    QApplication.processEvents()
    assert w.table.state() == QAbstractItemView.EditingState
    w.table.focusWidget().setText("2000")                                     # A wskoczy na koniec
    if zatwierdzenie == "enter":
        QTest.keyClick(w.table.focusWidget(), Qt.Key_Return)
    else:
        _klik_naglowka(w, COL_FOCAL)                                          # malejąco
    # Enter zatwierdza w kolejce zdarzeń (delegat Qt), a wpis optyki czeka jeszcze `singleShot(0)` -
    # jedno `processEvents` nie dociąga obu kroków; `qWait` obraca pętlę, aż oba wejdą.
    QTest.qWait(50)
    assert _ogniskowe(con) == {ids["A"]: 2000.0, ids["B"]: None, ids["C"]: None, ids["D"]: None}
    assert i18n.t("axis.edit_interrupted") not in msgs
    assert msgs[-1] == i18n.t("axis.tel.optics_saved")


# --- stabilność sortu: remis zostaje w porządku read-modelu ---

def test_posortuj_wiersze_remis_w_porzadku_read_modelu_w_obu_kierunkach():
    """Wspólna reguła obu tabel osi: wiersze o równym niepustym kluczu stoją w porządku read-modelu
    rosnąco i malejąco, puste na końcu. Mutant: malejąco przez odwrócenie listy rosnącej
    (`sorted(...)[::-1]` przestawia remis)."""
    from PySide6.QtCore import Qt
    from horreum.gui.app import _posortuj_wiersze
    rows = [{"id": 1, "n": 5}, {"id": 2, "n": 3}, {"id": 3, "n": 5}, {"id": 4, "n": None},
            {"id": 5, "n": 3}]

    def klucz(r, _col):
        return r["n"]

    def ids(order):
        return [r["id"] for r in _posortuj_wiersze(rows, (0, order), klucz)]
    assert ids(Qt.AscendingOrder) == [2, 5, 1, 3, 4]
    assert ids(Qt.DescendingOrder) == [1, 3, 2, 5, 4]
    assert [r["id"] for r in _posortuj_wiersze(rows, None, klucz)] == [1, 2, 3, 4, 5]


def test_sort_remis_klatek_w_porzadku_read_modelu(win):
    """Widok: A i C mają po 2 klatki (baza §8) - A (wcześniej w read-modelu) stoi przed C rosnąco
    i malejąco. Mutant: remis rozstrzygany odwrotnie przy sortowaniu malejącym."""
    from PySide6.QtCore import Qt
    w, con, ids = win
    w._on_sort_changed(COL_FRAMES, Qt.AscendingOrder)
    assert _kolejnosc(w) == [ids["D"], ids["A"], ids["C"], ids["B"]]          # 0, 2, 2, 3
    w._on_sort_changed(COL_FRAMES, Qt.DescendingOrder)
    assert _kolejnosc(w) == [ids["B"], ids["A"], ids["C"], ids["D"]]
