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
