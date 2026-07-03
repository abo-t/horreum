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
