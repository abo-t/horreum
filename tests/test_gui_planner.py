"""Ekran PLANERA (`horreum.gui.planner`, T5c) — testy STERUJĄCE realnym oknem Qt (offscreen)
na bazie T4 (trzy zestawy o różnych ogniskowych + stanowisko z GPS).

Sprawdzają glue widget↔rdzeń, nie rachunek nieba (ten ma własną baterię T1/T3/T4): plan się liczy
i lista jest niepusta, chip przełącza SOCZEWKĘ bez re-planu, stara generacja NIE trafia na ekran,
baza bez stanowiska GPS kończy się szczerym komunikatem zamiast crashu, a wątek tła sprząta się
bez zawisu (deadlock AB-BA GIL × ~QThread, `08992c4`).

`importorskip` na poziomie MODUŁU (PLAN_gui §4); `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo, targets
from horreum.gui.planner import PlannerView

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

NOW = "2026-07-31T12:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed(path):
    """Baza T4 na PLIKU (worker otwiera własne połączenie po ścieżce)."""
    con = db.open_db(path)
    con.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
                "VALUES ('ASI2600MM', 3.76, 1, ?)", (NOW,))
    for tel in ("A140R", "RC8", "ED120R"):
        con.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, ?, ?)",
                    (tel, "proposed", NOW))
    for tel_id in (1, 2, 3):
        con.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                    "VALUES (?, 1, 'proposed', ?)", (tel_id, NOW))
    con.execute("INSERT INTO observatory(name, lat, lon, status, created_at) "
                "VALUES ('Będargowo', 53.3890, 14.4424, 'proposed', ?)", (NOW,))
    con.commit()
    for cfg, focal in ((1, 784.0), (2, 1600.0), (3, 789.0)):
        for i in range(4):
            sha = f"c{cfg}-{i}"
            con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, "
                        "observatory_id, first_seen_at) VALUES (?, 'light', 'fits', 1, ?, 1, ?)",
                        (sha, cfg, NOW))
            fid = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha,)).fetchone()["id"]
            con.execute("INSERT INTO header(frame_id, raw_json, date_obs, focallen, xpixsz, exptime)"
                        " VALUES (?, '{\"NAXIS1\": 6248, \"NAXIS2\": 4176}', "
                        "'2026-01-02T22:00:00', ?, 3.76, 600.0)", (fid, focal))
    con.commit()
    return con


@pytest.fixture
def view(qapp, tmp_path):
    """Ekran INLINE (bez `db_path`) — plan liczy się synchronicznie, więc test widzi wynik od razu."""
    con = _seed(str(tmp_path / "planer.db"))
    v = PlannerView(con, db_path=None)
    v.night_edit.setDate(QDate(2026, 8, 15))       # noc jawna = wynik deterministyczny
    v.replan()
    yield v
    v.close()
    con.close()


# ─────────────────────────────────────────────────────────────── plan na ekranie

def test_plan_liczy_sie_i_lista_niepusta(view):
    assert view.model.rowCount() > 0
    assert "2026-08-15" in view.night_label.text()
    assert view.counts_label.text()
    first = view.model.row_at(0)
    assert first.canon and first.cost and first.rig


def test_noc_wybiera_rdzen_dopoki_user_nie_tknie_daty(qapp, tmp_path):
    """Wartość specjalna kalendarza = „bieżąca noc": `night=None` → dobę liczy `targets.default_night`
    z DŁUGOŚCI stanowiska. Podstawienie dzisiejszej daty w widżecie byłoby DRUGIM właścicielem faktu."""
    con = _seed(str(tmp_path / "auto.db"))
    v = PlannerView(con, db_path=None)
    try:
        assert v._params()["night"] is None
        expected = targets.default_night(v._result.site)
        assert v._result.night_date == expected
    finally:
        v.close()
        con.close()


def test_chip_to_soczewka_bez_re_planu(view):
    """Przełączenie chipa NIE liczy nocy od nowa (ten sam `PlanResult`), a mimo to zmienia kolumnę
    zestawu — dowód, że soczewka jest prezentacją, nie nowym zapytaniem."""
    before = view._result
    gen = view._gen
    view._on_chip("RC8")
    assert view._result is before and view._gen == gen        # zero nowych biegów
    assert all(view.model.row_at(r).rig.startswith("RC8")
               for r in range(view.model.rowCount()))
    view._on_chip(None)
    assert view.model.rowCount() > 0


def test_niewidoczny_wiersz_zostaje_wyszarzony_nie_ukryty(view):
    """D-0731-14: Księżyc i horyzont WYCENIAJĄ, nie wycinają — wiersz pod horyzontem musi zostać
    na liście (z szarym tekstem i tooltipem), inaczej ekran milczy o tym, czego nie pokazał."""
    from PySide6.QtCore import Qt
    rows = [view.model.row_at(r) for r in range(view.model.rowCount())]
    hidden = [i for i, r in enumerate(rows) if not r.visible]
    assert hidden, "fixture bez celów pod horyzontem — test straciłby sens"
    idx = view.model.index(hidden[0], 0)
    assert view.model.data(idx, Qt.ForegroundRole) is not None
    assert view.model.data(idx, Qt.ToolTipRole)


def test_panel_wyszukiwania_zwija_sie(view):
    """Firsthand T5f: rozwinięty panel zjada ~100 px pionu, a przy podłodze okna 1146×760 lista
    schodzi do kilkunastu wierszy. Zwinięcie chowa TREŚĆ, tytuł zostaje — user wie, że progi żyją."""
    box = view.min_hours.parent().parent()               # QGroupBox „Wyszukiwanie"
    assert box.isCheckable() and box.isChecked()
    body = view.min_hours.parent()
    box.setChecked(False)
    assert body.isHidden() is True        # `isVisible` byłoby False także dla niepokazanego okna
    box.setChecked(True)
    assert body.isHidden() is False


def test_stara_generacja_nie_trafia_na_ekran(view):
    """Wynik w locie unieważniamy generacją (przerwanie BEZ haka w rdzeniu — kontrakt T3 nietknięty)."""
    stale = view._gen - 1
    before = [view.model.row_at(r).canon for r in range(view.model.rowCount())]
    view._on_done(stale, "PODMIENIONY WYNIK")
    assert [view.model.row_at(r).canon for r in range(view.model.rowCount())] == before
    view._on_failed(stale, "stary błąd")
    assert view.night_label.text() != "stary błąd"


def test_baza_bez_stanowiska_mowi_wprost(qapp, tmp_path):
    """`targets.plan` rzuca `ValueError` bez stanowiska z GPS — ekran ma to POWIEDZIEĆ, nie paść
    (podstawienie „środka Polski" byłoby kłamstwem)."""
    con = db.open_db(str(tmp_path / "pusta.db"))
    v = PlannerView(con, db_path=None)
    try:
        assert "GPS" in v.night_label.text()
        assert v.model.rowCount() == 0
        assert v._pending_gen() is False          # błąd to STAN, nie powód do zapętlonego biegu
    finally:
        v.close()
        con.close()


def test_szukanie_pomija_progi_i_mowi_o_tym(view):
    """`find` ma semantykę WYSZUKIWANIA: cel spoza progów ma się znaleźć, a nota nad listą mówi,
    że progi nie działają — inaczej lista wygląda na sprzeczną z suwakami."""
    def canons():
        return {view.model.row_at(r).canon for r in range(view.model.rowCount())}

    assert "NGC7000" in canons()
    view.min_size.setValue(600.0)                 # próg, przez który NGC7000 (~120′) nie przejdzie
    view.replan()
    assert "NGC7000" not in canons()
    view.find_edit.setText("NGC7000")
    view.replan()
    assert "NGC7000" in canons()                  # pytanie wprost bije próg
    assert "POMIJA" in view.notes_label.text().upper()


def test_status_filtruje_a_kuratela_widac_w_kolumnie(view):
    canon = view.model.row_at(0).canon
    repo.set_target_plan(view.con, canon=canon, status="planned", priority=1, now=NOW)
    view.status_combo.setCurrentIndex(view.status_combo.findData("planned"))
    view.replan()
    assert [view.model.row_at(r).canon for r in range(view.model.rowCount())] == [canon]
    assert view.model.row_at(0).plan == "zaplanowany 1"


# ─────────────────────────────────────────────────────────────── kuratela i park (ZAPIS, T5d)

def _events(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def test_panel_zapisuje_kuratel_i_wraca_na_ten_sam_cel(view):
    view.table.selectRow(0)
    canon = view.selected_row().canon
    view.panel_status.setCurrentIndex(view.panel_status.findData("planned"))
    view.panel_priority.setValue(2)
    view.panel_note.setText("domknac SII")
    view._on_save_mark()
    row = view.con.execute("SELECT * FROM target_plan WHERE canon = ?", (canon,)).fetchone()
    assert (row["status"], row["priority"], row["note"]) == ("planned", 2, "domknac SII")
    assert view.selected_row().canon == canon            # zaznaczenie wróciło na ten sam cel
    assert view.selected_row().plan == "zaplanowany 2"   # lista odbija zapis


def test_powtorzony_zapis_nie_puchnie_dziennika(view):
    view.table.selectRow(0)
    view.panel_status.setCurrentIndex(view.panel_status.findData("active"))
    view._on_save_mark()
    before = _events(view.con, "target_plan.set")
    view._on_save_mark()                                 # ten sam komplet → idempotencja repo
    assert _events(view.con, "target_plan.set") == before


def test_skip_znika_z_listy_a_panel_mowi_prawde(view):
    view.table.selectRow(0)
    canon = view.selected_row().canon
    view.panel_status.setCurrentIndex(view.panel_status.findData("skip"))
    view._on_save_mark()
    canons = {view.model.row_at(r).canon for r in range(view.model.rowCount())}
    assert canon not in canons                           # `skip` chowa cel (z licznikiem w nagłówku)
    assert view.selected_row() is None                   # pusty panel = uczciwa odpowiedź
    assert not view.panel.isEnabled()
    assert "pominięty" in view.notes_label.text() or view._result.counts["hidden_by_status"] == 1


def test_zdjecie_oznaczenia_kasuje_wiersz(view):
    view.table.selectRow(0)
    canon = view.selected_row().canon
    view.panel_status.setCurrentIndex(view.panel_status.findData("planned"))
    view._on_save_mark()
    view._on_clear_mark()
    assert view.con.execute("SELECT count(*) FROM target_plan WHERE canon = ?",
                            (canon,)).fetchone()[0] == 0
    assert _events(view.con, "target_plan.cleared") == 1


def test_bez_luk_to_informacja_a_nie_zapis(view):
    """D-T4-d: „✓ bez luk" podpowiada, ale statusu NIE stawia — automat czyniłby trwały status
    funkcją suwaka `min_hours`."""
    view.min_hours.setValue(0.0)                         # przy zerze nikt nie ma luk
    view.replan()
    view.table.selectRow(0)
    assert view.no_gaps_label.text() == "✓ bez luk"
    assert view.con.execute("SELECT count(*) FROM target_plan").fetchone()[0] == 0


def test_dialog_parku_zapisuje_zdanie_uzytkownika(view, qapp):
    from horreum.gui.planner import ParkDialog
    dlg = ParkDialog(view.con, view._now)
    try:
        combo = dlg._combos[1]
        combo.setCurrentIndex(combo.findData(1))
        dlg._on_pick(1, combo)
        assert dlg.changed == 1
        assert combo.findData(None) == -1                # etykieta „nie wypowiedziałeś się" znika
        from horreum import sky
        assert sky.park(view.con) == ("A140R",)
        dlg._on_pick(1, combo)                           # to samo zdanie drugi raz = brak zmiany
        assert dlg.changed == 1
    finally:
        dlg.close()


# ─────────────────────────────────────────────────────────────── most do gridu (T5e)

def test_most_emituje_kanony_celu_z_pokryciem(view):
    from horreum import repo as _repo
    canon = view.model.row_at(0).canon
    got = []
    view.show_frames_for.connect(got.append)
    view.table.selectRow(0)
    view._on_show_frames()
    assert got == []                                     # cel bez klatek nie ma czego pokazać
    assert not view.frames_btn.isEnabled()

    # daj celowi pokrycie: obiekt + light z godzinami
    oid, _ = _repo.upsert_object(view.con, canon=canon, catalog="NGC", kind="deep_sky", now=NOW)
    view.con.execute("UPDATE frame SET object_id = ?, filter_canon = 'Ha' WHERE id = 1", (oid,))
    view.con.commit()
    view.replan()
    idx = next(r for r in range(view.model.rowCount()) if view.model.row_at(r).canon == canon)
    view.table.selectRow(idx)
    assert view.frames_btn.isEnabled()
    view._on_show_frames()
    assert got == [(canon,)]


# ─────────────────────────────────────────────────────────────── wątek tła

def test_watek_tla_liczy_i_sprzata_bez_zawisu(qapp, tmp_path):
    """Realny `QThread` (jak w oknie): plan przychodzi sygnałem, a cleanup idzie ŚWIĘTĄ kolejnością
    `worker.deleteLater()` → `thread.wait()` → `thread.deleteLater()` (deadlock AB-BA, `08992c4`)."""
    from PySide6.QtCore import QDeadlineTimer, QEventLoop, QTimer
    path = str(tmp_path / "watek.db")
    con = _seed(path)
    v = PlannerView(con, db_path=path)
    try:
        loop = QEventLoop()
        QTimer.singleShot(15_000, loop.quit)                  # sufit czasu — zawis nie zawiesi baterii
        v.model.modelReset.connect(loop.quit)
        if v.model.rowCount() == 0:
            loop.exec()
        assert v.model.rowCount() > 0
        assert v.busy.isVisible() is False
        deadline = QDeadlineTimer(5000)
        while (v._thread is not None or v._worker is not None) and not deadline.hasExpired():
            qapp.processEvents()
        assert v._thread is None and v._worker is None        # posprzątane, nic nie wisi
    finally:
        v.close()
        con.close()
