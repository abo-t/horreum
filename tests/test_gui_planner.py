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
def settings_store(monkeypatch):
    """QSettings na SŁOWNIKU (wzorzec `test_gui_grid`). Od czasu, gdy progi są pamiętane między
    sesjami, ekran REALNIE pisze do rejestru — bez tej izolacji bateria wstawiłaby użytkownikowi
    swoje wartości skrajne (zmierzone: `min_size=600`, `min_hours=0`) i sama zaczęłaby czytać je
    zamiast domyślnych, więc test progów przechodziłby albo nie zależnie od poprzedniego przebiegu."""
    from PySide6.QtCore import QSettings
    store = {}
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: store.__setitem__(k, v))
    return store


@pytest.fixture
def view(qapp, tmp_path, settings_store):
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


def test_noc_wybiera_rdzen_dopoki_user_nie_tknie_daty(qapp, tmp_path, settings_store):
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


def test_tooltip_pokrycia_wygrywa_na_swojej_kolumnie(view):
    """I-2e: ścieżki gotowych obrazów mieszkają w tooltipie kolumny „Pokrycie" i BIJĄ tam notę
    „ten cel dziś nie wschodzi" — tamta powtarza się w dziesięciu innych komórkach tego samego
    wiersza, a ścieżka do obrazu jest tylko tutaj. Indeks kolumny liczony z `_COLUMNS`, więc
    przestawienie kolumn nie przeniesie tooltipu na cudzą komórkę."""
    import dataclasses

    from PySide6.QtCore import Qt

    from horreum.gui import i18n
    from horreum.gui import planner as P
    assert P._COLUMNS[P._COL_COVERAGE][0] == "planner.col_coverage"
    rows = [view.model.row_at(r) for r in range(view.model.rowCount())]
    niewidoczny = next(r for r in rows if not r.visible)
    tip = "Gotowe obrazy (1):\nR:\\m.xisf"
    view.model.set_rows([dataclasses.replace(niewidoczny, coverage_tip=tip)])
    assert view.model.data(view.model.index(0, P._COL_COVERAGE), Qt.ToolTipRole) == tip
    assert view.model.data(view.model.index(0, 0), Qt.ToolTipRole) == \
        i18n.t("planner.not_visible_tip")


def test_pasek_progow_zwija_sie_i_niesie_stan(view):
    """Wiz T5 #3 (P1): zwijamy PRZYCISKIEM ze strzałką, nie `checkable QGroupBox` — odznaczony
    checkbox przy DZIAŁAJĄCYCH progach czyta się w Qt jak „grupa wyłączona". Tytuł niesie STAN,
    więc zwinięty pasek nadal mówi, czym tniesz listę."""
    body = view._controls_body
    assert body.isHidden() is False       # `isVisible` byłoby False także dla niepokazanego okna
    assert "6′" in view.controls_toggle.text() and "13.0" in view.controls_toggle.text()
    view.controls_toggle.setChecked(False)
    assert body.isHidden() is True
    assert "Progi" in view.controls_toggle.text()          # stan widoczny MIMO zwinięcia
    assert view.find_edit.isHidden() is False              # „Szukaj" przeżywa zwinięcie progów
    view.min_size.setValue(20.0)
    assert "20′" in view.controls_toggle.text()            # tytuł podąża za progiem
    view.controls_toggle.setChecked(True)
    assert body.isHidden() is False


def test_progi_przezywaja_zamkniecie_ekranu(qapp, tmp_path, settings_store):
    """Dług P-A #5: progi są PAMIĘTANE między sesjami (`QSettings`, klasa D-B). D-0731-10 zabrania
    pieczenia ich w ASSECIE — nie zapamiętywania w profilu maszyny; zerowanie co start kazało
    powtarzać te same ruchy każdego wieczoru."""
    con = _seed(str(tmp_path / "progi.db"))
    first = PlannerView(con, db_path=None)
    first.min_size.setValue(9.0)
    first.max_cost_on.setChecked(True)
    first.close()
    assert settings_store["planner/min_size"] == 9.0

    second = PlannerView(con, db_path=None)
    try:
        assert second.min_size.value() == 9.0
        assert second.max_cost_on.isChecked() is True
        assert second.max_cost.isEnabled() is True     # stan checkboxa i pola nie mogą się rozjechać
        assert second.min_dark.value() == 15.0         # nietknięty próg zostaje domyślny
    finally:
        second.close()
        con.close()


def test_przywroc_domyslne_cofa_wszystkie_progi(view):
    """Zapamiętane progi bez drogi powrotnej byłyby pułapką: wartości domyślnych nie ma na ekranie,
    więc user nie ma skąd ich znać. Reset jest JEDNYM re-planem, nie pięcioma."""
    view.min_size.setValue(9.0)
    view.min_hours.setValue(4.0)
    view.max_cost_on.setChecked(True)
    gen = view._gen
    view._on_reset_thresholds()
    assert (view.min_size.value(), view.min_dark.value(), view.max_mag.value(),
            view.min_alt.value(), view.min_hours.value()) == (6.0, 15.0, 13.0, 30.0, 1.0)
    assert view.max_cost_on.isChecked() is False and view.max_cost.isEnabled() is False
    assert view._gen == gen + 1                        # dokładnie jeden bieg, nie pięć
    assert "6′" in view.controls_toggle.text()         # tytuł zwiniętego paska mówi prawdę


def test_porzadek_po_soczewce_przestawia_liste_bez_re_planu(view):
    """Dług P-A #3: chip zmieniał radę, ale NIE porządek — „patrzę oczami RC8" zostawiało na górze
    cele wybrane dla A140R. Sort żyje w WIDOKU: `targets._sort_key` (pięć członów, D-T4-c) i CLI
    zostają nietknięte, a przełącznik nie liczy nocy od nowa."""
    from horreum.gui import planner_model as pm
    view._on_chip("RC8")
    core = [view.model.row_at(r).canon for r in range(view.model.rowCount())]
    before, gen = view._result, view._gen

    view.order_combo.setCurrentIndex(view.order_combo.findData(pm.ORDER_LENS))
    assert view._result is before and view._gen == gen        # zero nowych rachunków nocy
    lens = [view.model.row_at(r).canon for r in range(view.model.rowCount())]
    assert sorted(lens) == sorted(core) and lens != core      # ten sam zbiór, inny porządek
    # Pierwszy wiersz mieści się w JEDNYM kadrze — porządek soczewki zaczyna od kadrowalnych.
    assert "1 kadr" in view.model.row_at(0).rig

    view.order_combo.setCurrentIndex(view.order_combo.findData(pm.ORDER_CORE))
    assert [view.model.row_at(r).canon for r in range(view.model.rowCount())] == core


def test_panel_nie_przenosi_statusu_na_kolejny_cel(view):
    """Wiz T5 #1 (P1) — NAJDROŻSZY defekt wizytacji: combo trzymało status POPRZEDNIEGO celu,
    więc jeden klik w „Zapisz" wpisywał do bazy zdanie, którego user nie wybrał, a kolumna „Plan"
    pokazywała w tej samej chwili „—"."""
    view.table.selectRow(0)
    a = view.selected_row().canon
    view.panel_status.setCurrentIndex(view.panel_status.findData("done"))
    view._on_save_mark()

    view.table.selectRow(1)                                # cel NIETKNIĘTY
    b = view.selected_row().canon
    assert b != a
    assert view.panel_status.currentData() is None         # panel odbija „—" z kolumny, nie cudze zdanie
    assert view.save_btn.isEnabled() is False              # nie ma czego zapisać (szczery disabled)
    view._on_save_mark()                                   # klik i tak nic nie zapisze
    assert view.con.execute("SELECT count(*) FROM target_plan WHERE canon = ?", (b,)).fetchone()[0] == 0
    view.panel_status.setCurrentIndex(view.panel_status.findData("planned"))
    assert view.save_btn.isEnabled() is True


def test_zapisz_nie_jest_martwym_przyciskiem_od_startu(view):
    """Wiz T5 R1 (P1, regresja MOJEJ poprawki #1): `_sync_save_enabled` wisiało tylko na
    `currentIndexChanged`, a `setCurrentIndex(0)` na indeksie JUŻ zerowym nie emituje sygnału —
    więc „Zapisz" zostawał aktywny (bold + pierścień domyślnego) od startu do pierwszej zmiany
    statusu. Trafiało to w 392/429 celów i w PIERWSZY klik każdej sesji."""
    assert view.save_btn.isEnabled() is False          # zanim cokolwiek zaznaczono
    view.table.selectRow(0)                            # cel nietknięty (fixture nic nie oznacza)
    assert view.panel_status.currentData() is None
    assert view.save_btn.isEnabled() is False          # ...i nadal, BEZ zmiany indeksu
    view.table.clearSelection()
    assert view.save_btn.isEnabled() is False


def test_akcenty_ida_za_motywem(view):
    """Wiz T5 R2: kolory wisiały na `theme.DEFAULT` (ciemnym), a `main` ustawia motyw PRZED budową
    okna — jasny start dostawał akcenty ciemne (wyszarzenie 2,38:1 na białym, gorzej niż sztywne
    128 sprzed „naprawy")."""
    from horreum.gui import theme
    view.use_theme("light")
    assert view.model._dim.name().lower() == theme.accents("light")["secondary_text"].lower()
    # ⚠ nota kolorem OSTRZEGAWCZYM (wiz T5 N5) — złoto spichlerza miało w jasnym 2,72:1
    assert theme.palette_spec("light")["bright_text"] in view.warn_label.styleSheet()
    assert theme.palette_spec("light")["highlight"] in view._chip_qss
    view.use_theme("dark")
    assert view.model._dim.name().lower() == theme.accents("dark")["secondary_text"].lower()


def test_stara_generacja_nie_trafia_na_ekran(view):
    """Wynik w locie unieważniamy generacją (przerwanie BEZ haka w rdzeniu — kontrakt T3 nietknięty)."""
    stale = view._gen - 1
    before = [view.model.row_at(r).canon for r in range(view.model.rowCount())]
    view._on_done(stale, "PODMIENIONY WYNIK")
    assert [view.model.row_at(r).canon for r in range(view.model.rowCount())] == before
    view._on_failed(stale, "stary błąd")
    assert view.night_label.text() != "stary błąd"


def test_baza_bez_stanowiska_mowi_wprost(qapp, tmp_path, settings_store):
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
        from horreum import sky
        assert sky.park(view.con) == ("A140R",)
        dlg._on_pick(1, combo)                           # to samo zdanie drugi raz = brak zmiany
        assert dlg.changed == 1
    finally:
        dlg.close()


def test_dialog_parku_umie_wycofac_zdanie_do_null(view, qapp):
    """Dług P-A #7: trójstan `in_park` (1 · 0 · NULL) miał w UI drogę tylko w jedną stronę —
    pozycja „nie wypowiedziałeś się" znikała po pierwszym wyborze, więc raz wypowiedziane zdanie
    dawało się zmienić, ale nie WYCOFAĆ. „Historyczny" (park przejrzany) i „nie wypowiedziano"
    (baza świeża) to różne fakty i powierzchnia musi umieć oba."""
    from horreum.gui.planner import _PARK_UNSAID, ParkDialog
    dlg = ParkDialog(view.con, view._now)
    try:
        combo = dlg._combos[1]
        combo.setCurrentIndex(combo.findData(0))         # najpierw: jawnie historyczny
        dlg._on_pick(1, combo)
        assert view.con.execute("SELECT in_park FROM telescope WHERE id = 1").fetchone()[0] == 0

        assert combo.findData(_PARK_UNSAID) >= 0         # pozycja ZOSTAJE na liście
        combo.setCurrentIndex(combo.findData(_PARK_UNSAID))
        dlg._on_pick(1, combo)
        assert view.con.execute("SELECT in_park FROM telescope WHERE id = 1").fetchone()[0] is None
        assert dlg.changed == 2
        # Ślad w dzienniku, nie ciche UPDATE — `after: None` odróżnia wycofanie od odrzucenia.
        ev = view.con.execute("SELECT payload FROM event WHERE verb = 'telescope.parked' "
                              "ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert '"after": null' in ev
    finally:
        dlg.close()


def test_dialog_parku_pokazuje_nazwe_usera_a_kanon_w_tooltipie(view, qapp):
    """P-C: kolumna „Teleskop" pokazywała surowy `telescop_canon` — czyli napis Z NAGŁÓWKA, cudze
    słowo o własnym sprzęcie usera. Teraz idzie przez `queries.telescope_label` (właściciel reguły
    label→kanon, P-B), a kanon — tożsamość zestawu i token `horreum park --add` — schodzi do
    tooltipu, żeby wiersz dialogu dało się połączyć z wierszem CLI."""
    from horreum.gui.planner import ParkDialog
    view.con.execute("UPDATE telescope SET label = 'Askar na tarasie' WHERE id = 1")
    view.con.commit()
    dlg = ParkDialog(view.con, view._now)
    try:
        row = next(r for r in range(dlg.table.rowCount())
                   if dlg.table.item(r, ParkDialog.COL_CANON).text() == "Askar na tarasie")
        assert "A140R" in dlg.table.item(row, ParkDialog.COL_CANON).toolTip()
        # Teleskop NIENAZWANY zostaje przy kanonie i BEZ tooltipu — nie ma czego rozróżniać.
        other = next(r for r in range(dlg.table.rowCount())
                     if dlg.table.item(r, ParkDialog.COL_CANON).text() == "RC8")
        assert dlg.table.item(other, ParkDialog.COL_CANON).toolTip() == ""
    finally:
        dlg.close()


def test_ekran_deklaruje_podloge_szerokosci(view):
    """Dług P-A #2 (decyzja Zdzinia 2026-08-01): kolumny NIE ustępują, ustępuje okno. Zmierzone
    realnym fontem: 11 kolumn zajmuje 981 px treści, więc przy dawnej podłodze 1073 px tabela
    scrollowała się w poziomie o 375 px. Test pilnuje deklaracji, nie pikseli renderu — te zależą
    od fontu maszyny (offscreen podawał wartości zawyżone o ~45%)."""
    from horreum.gui.planner import _MIN_W
    assert view.minimumWidth() == _MIN_W
    assert view.minimumSizeHint().width() >= _MIN_W


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

def test_watek_tla_liczy_i_sprzata_bez_zawisu(qapp, tmp_path, settings_store):
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


# ───────────────────────────────────────── sekcja sierot kurateli (R-S0-7)
#
# Populacja tej sekcji jest w żywym archiwum ZEROWA i ma prawo taka zostać — powstaje dopiero przy
# przebudowie assetu katalogu. Dlatego bateria jest tu jedyną obroną kodu, a każdy test wytwarza
# sierotę wprost w bazie (inaczej się nie da: obie drogi zapisu walidują nazwę wobec assetu).

def _osierocone(view, canon, status="planned", priority=None, note=None):
    view.con.execute(
        "INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", (canon, status, priority, note, NOW, NOW))
    view.con.commit()
    view.replan()


def test_sekcja_sierot_milczy_przy_zerze(view):
    """Zero pikseli, dopóki nie ma o czym mówić — ekran planera nie ma zapasu w pionie (D-0801-1).

    `isHidden()`, nie `isVisible()`: przy oknie bez `show()` to drugie jest ZAWSZE False, więc
    asercja przechodziłaby także dla sekcji, którą kod pokazał (konwencja repo — STANDING)."""
    assert view._orphan_box.isHidden()
    assert view.orphan_list.count() == 0


def test_sekcja_pokazuje_sie_dopiero_z_populacja(view):
    _osierocone(view, "NGC0000_NIEISTNIEJE")
    assert not view._orphan_box.isHidden()
    assert view.orphan_list.count() == 1
    assert "NGC0000_NIEISTNIEJE" in view.orphan_list.item(0).text()


def test_zdejmij_kasuje_wlasny_kanon_a_nie_zaznaczony_wiersz_listy(view):
    """SEDNO: `_selected_canon()` czyta zaznaczenie TABELI planu. Gdyby sekcja go współdzieliła,
    gest kasowałby kuratelę CUDZEGO celu — tego zaznaczonego na liście nocy."""
    view.table.selectRow(0)
    view.panel_status.setCurrentIndex(view.panel_status.findData("planned"))
    view._on_save_mark()
    zywy = view.selected_row().canon
    _osierocone(view, "NGC0000_NIEISTNIEJE")
    view.table.selectRow(0)
    view.orphan_list.setCurrentRow(0)
    view._on_orphan_clear()
    assert view.con.execute("SELECT count(*) FROM target_plan WHERE canon = ?",
                            ("NGC0000_NIEISTNIEJE",)).fetchone()[0] == 0
    assert view.con.execute("SELECT count(*) FROM target_plan WHERE canon = ?",
                            (zywy,)).fetchone()[0] == 1


def test_zdjecie_sieroty_ma_droge_powrotu_z_kompletem_pol(view):
    """Bez tego paczka domykająca grupę „gest bez drogi powrotu" wnosiłaby własny taki gest:
    sieroty NIE DA SIĘ odtworzyć inaczej, bo każdy zapis waliduje nazwę wobec assetu."""
    _osierocone(view, "NGC0000_NIEISTNIEJE", status="active", priority=3, note="SII")
    view.orphan_list.setCurrentRow(0)
    assert view.orphan_undo_btn.isEnabled() is False      # nie ma jeszcze czego cofać
    view._on_orphan_clear()
    assert view.orphan_undo_btn.isEnabled() is True
    view._on_orphan_undo()
    row = view.con.execute("SELECT * FROM target_plan WHERE canon = ?",
                           ("NGC0000_NIEISTNIEJE",)).fetchone()
    assert (row["status"], row["priority"], row["note"]) == ("active", 3, "SII")
    assert view.orphan_undo_btn.isEnabled() is False      # pamięć skonsumowana


def test_sekcja_zostaje_widoczna_gdy_jest_co_cofnac(view):
    """Inaczej „Cofnij zdjęcie" znikałoby razem z ostatnią sierotą — czyli dokładnie w chwili,
    w której bywa potrzebne."""
    _osierocone(view, "NGC0000_NIEISTNIEJE")
    view.orphan_list.setCurrentRow(0)
    view._on_orphan_clear()
    assert view.orphan_list.count() == 0
    assert not view._orphan_box.isHidden()


def test_przeniesienie_zywe_tylko_dla_kanonu_ktory_katalog_przejal(view):
    _osierocone(view, "NGC0000_NIEISTNIEJE")
    view.orphan_list.setCurrentRow(0)
    assert view.orphan_move_btn.isEnabled() is False
    view.con.execute("DELETE FROM target_plan")
    _osierocone(view, "LBN529")                          # żywy alias katalogowy rekordu C9
    view.orphan_list.setCurrentRow(0)
    assert view.orphan_move_btn.isEnabled() is True


def test_przeniesienie_zachowuje_cala_decyzje_czlowieka(view):
    """Przenosimy CUDZĄ decyzję, a nie zakładamy nowej — status, priorytet i nota idą w komplecie."""
    _osierocone(view, "LBN529", status="active", priority=1, note="domknac SII")
    view.orphan_list.setCurrentRow(0)
    view._on_orphan_move()
    assert view.con.execute("SELECT count(*) FROM target_plan WHERE canon = 'LBN529'"
                            ).fetchone()[0] == 0
    row = view.con.execute("SELECT * FROM target_plan WHERE canon = 'C9'").fetchone()
    assert (row["status"], row["priority"], row["note"]) == ("active", 1, "domknac SII")
    assert view._orphan_box.isHidden()                    # populacja zeszła do zera


def test_przeniesienie_NIE_nadpisuje_zywej_kurateli_celu(view):
    """SEDNO, złapane bramką pakietu (Fable Z2): cel docelowy może mieć WŁASNĄ, świeższą kuratelę —
    i to jest GŁÓWNY scenariusz tego stanu, nie brzeg. Przebudowa assetu przenosi nazwę, człowiek
    oznacza cel od nowa pod nazwą bieżącą, a stara sierota zostaje. `set_target_plan` pisze po
    kanonie, więc bez guarda „Przenieś" nadpisałoby świeższą decyzję STARSZYM wierszem —
    bezgłośnie i bez drogi powrotu w GUI."""
    view.con.execute(
        "INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
        "VALUES ('C9', 'active', 1, 'swieza decyzja', ?, ?)", (NOW, NOW))
    view.con.commit()
    _osierocone(view, "LBN529", status="planned", priority=9, note="stara sierota")
    view.orphan_list.setCurrentRow(0)
    view._on_orphan_move()
    row = view.con.execute("SELECT * FROM target_plan WHERE canon = 'C9'").fetchone()
    assert (row["status"], row["priority"], row["note"]) == ("active", 1, "swieza decyzja")
    # …a sierota ZOSTAJE — gest odmówił, więc niczego nie zgubił
    assert view.con.execute("SELECT count(*) FROM target_plan WHERE canon = 'LBN529'"
                            ).fetchone()[0] == 1


def test_guzik_przeniesienia_gasnie_gdy_cel_ma_wlasna_kuratele(view):
    """G2-9d - zapowiedź nie ma prawa obiecywać gestu, który guard zaraz odmówi (rejestr długów):
    do S0 guzik stał aktywny nawet nad kolizją z `test_przeniesienie_NIE_nadpisuje_zywej_kurateli_celu`
    powyżej, a tooltip obiecywał przeniesienie, które `_on_orphan_move` i tak odrzuca. Teraz
    `_sync_orphan_buttons` czyta TEN SAM predykat co guard (`_orphan_move_blocked`) i gasi guzik
    z powodem, zanim dojdzie do kliknięcia."""
    from horreum.gui import i18n
    view.con.execute(
        "INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
        "VALUES ('C9', 'active', 1, 'swieza decyzja', ?, ?)", (NOW, NOW))
    view.con.commit()
    _osierocone(view, "LBN529", status="planned", priority=9, note="stara sierota")
    view.orphan_list.setCurrentRow(0)
    assert view.orphan_move_btn.isEnabled() is False
    assert view.orphan_move_btn.toolTip() == i18n.t("planner.orphan_move_tip_taken", where="C9")


def test_guzik_przeniesienia_aktywny_bez_kolizji_niesie_zapowiedz_gestu(view):
    """Kontrast do testu powyżej: gdy cel `gdzie` NIE ma własnej kurateli, guzik zostaje aktywny
    jak dotąd, a tooltip niesie zapowiedź gestu (`planner.orphan_move_tip`), nie powód odmowy."""
    from horreum.gui import i18n
    _osierocone(view, "LBN529", status="planned", priority=9, note="sierota bez kolizji")
    view.orphan_list.setCurrentRow(0)
    assert view.orphan_move_btn.isEnabled() is True
    assert view.orphan_move_btn.toolTip() == i18n.t("planner.orphan_move_tip", where="C9")
