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
def view(qapp, tmp_path, ustawienia):
    """Ekran INLINE (bez `db_path`) - plan liczy się synchronicznie, więc test widzi wynik od razu. Zegar widoku
    z `NOW`: minimum pola nocy to „dziś minus rok” (AR-365), więc noc jawna z 2026 nie spadnie na klamrę w 2027."""
    con = _seed(str(tmp_path / "planer.db"))
    v = PlannerView(con, db_path=None, now_fn=lambda: NOW)
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


def test_noc_wybiera_rdzen_dopoki_user_nie_tknie_daty(qapp, tmp_path, ustawienia):
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
    assert "6′" in view.controls_toggle.text() and "mag ≤13," in view.controls_toggle.text()   # AR-375: jedna forma
    view.controls_toggle.setChecked(False)
    assert body.isHidden() is True
    assert "Progi" in view.controls_toggle.text()          # stan widoczny MIMO zwinięcia
    assert view.find_edit.isHidden() is False              # „Szukaj" przeżywa zwinięcie progów
    view.min_size.setValue(20.0)
    assert "20′" in view.controls_toggle.text()            # tytuł podąża za progiem
    view.controls_toggle.setChecked(True)
    assert body.isHidden() is False


def test_progi_przezywaja_zamkniecie_ekranu(qapp, tmp_path, ustawienia):
    """Dług P-A #5: progi są PAMIĘTANE między sesjami (`QSettings`, klasa D-B). D-0731-10 zabrania
    pieczenia ich w ASSECIE — nie zapamiętywania w profilu maszyny; zerowanie co start kazało
    powtarzać te same ruchy każdego wieczoru."""
    con = _seed(str(tmp_path / "progi.db"))
    first = PlannerView(con, db_path=None)
    first.min_size.setValue(9.0)
    first.max_cost_on.setChecked(True)
    first.close()
    assert float(ustawienia.value("planner/min_size")) == 9.0

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
    # Tytuł zwiniętego paska mówi prawdę: po resecie bez dopisku wartości domyślnej (AR-371) - sam „6′” byłby pusty,
    # bo nieudany reset dałby „≥9′ (domyślnie 6′)”.
    assert "≥6′" in view.controls_toggle.text() and "(domyślnie" not in view.controls_toggle.text()


def test_filtr_kadru_domyslnie_wylaczony_a_kolumna_wypelnienia_jest(view):
    """PL-1/PL-2: oba progi domyślnie WYŁĄCZONE (wzór progu kosztu, D-0731-14): rachunek bez
    nich; kolumna „Wypełnienie" stoi w tabeli i niesie procent soczewki."""
    from PySide6.QtCore import Qt
    from horreum.gui import i18n
    assert view.min_fill_on.isChecked() is False and view.min_fill.isEnabled() is False
    assert view.max_panels_on.isChecked() is False and view.max_panels.isEnabled() is False
    p = view._params()
    assert p["min_fill"] is None and p["max_panels"] is None
    assert view._result.rig_filter == "off"
    headers = [view.model.headerData(c, Qt.Horizontal) for c in range(view.model.columnCount())]
    col = headers.index(i18n.t("planner.col_fill"))
    assert view.model.data(view.model.index(0, col)).endswith("%")
    assert view.model.data(view.model.index(0, col), Qt.TextAlignmentRole) is not None


def test_filtr_kadru_wlaczony_tnie_liste_i_mowi_to_w_naglowku(view):
    """Włączenie progu re-planuje z ułamkiem (ekran mówi procentami), licznik zmienia napis,
    tytuł zwiniętego paska nazywa filtr. Park jawny w bazie: przy nieustawionym filtr nie działa."""
    repo.set_telescope_park(view.con, telescope_id=1, in_park=1, now=NOW)
    repo.set_telescope_park(view.con, telescope_id=2, in_park=1, now=NOW)
    view.replan()
    base = view.model.rowCount()
    view.min_fill.setValue(30.0)
    view.min_fill_on.setChecked(True)
    view.max_panels_on.setChecked(True)
    view.replan()
    assert view._params()["min_fill"] == pytest.approx(0.3) and view._params()["max_panels"] == 1
    assert view._result.rig_filter == "on"
    assert 0 < view.model.rowCount() < base
    assert "twoim sprzętem" in view.counts_label.text()
    assert "wypełnienie ≥30%" in view.controls_toggle.text()


def test_filtr_kadru_przezywa_zamkniecie_i_reset_go_gasi(qapp, tmp_path, ustawienia):
    """Wartość i przełącznik pamiętane w `QSettings` jak sąsiednie progi; „Przywróć domyślne"
    wyłącza oba filtry kadru jednym re-planem."""
    con = _seed(str(tmp_path / "kadr.db"))
    first = PlannerView(con, db_path=None)
    first.min_fill.setValue(45.0)
    first.min_fill_on.setChecked(True)
    first.max_panels.setValue(2)
    first.max_panels_on.setChecked(True)
    first.close()
    second = PlannerView(con, db_path=None)
    try:
        assert second.min_fill.value() == 45.0 and second.min_fill_on.isChecked() is True
        assert second.max_panels.value() == 2 and second.max_panels.isEnabled() is True
        gen = second._gen
        second._on_reset_thresholds()
        assert second.min_fill_on.isChecked() is False and second.min_fill.isEnabled() is False
        assert second.max_panels_on.isChecked() is False and second.max_panels.value() == 1
        assert second._gen == gen + 1
    finally:
        second.close()
        con.close()


def test_filtr_kadru_nieczynny_tytul_paska_mowi_to_wprost(view):
    """Poproszony filtr przy nieustawionym parku NIE tnie (`rig_filter == 'no_park'`), więc tytuł
    zwiniętego paska nie ma prawa głosić cięcia bez dopisku; przy ustawionym parku dopisek znika."""
    view.min_fill_on.setChecked(True)
    view.replan()
    assert view._result.rig_filter == "no_park"
    assert "filtr kadru" in view.controls_toggle.text()
    assert view.controls_toggle.text().endswith("(nieczynny)")
    repo.set_telescope_park(view.con, telescope_id=1, in_park=1, now=NOW)
    view.replan()
    assert view._result.rig_filter == "on"
    assert "filtr kadru" in view.controls_toggle.text()
    assert "(nieczynny)" not in view.controls_toggle.text()


def test_licznik_przy_soczewce_mowi_ile_wierszy_widac(view):
    """Licznik nad listą mówi to, co widać: soczewka, która przy filtrze kadru chowa wiersze,
    dopisuje swoją liczbę; „najlepsze dopasowanie" zostawia napis bez dopisku."""
    from horreum.gui import planner_model as pm
    for tel_id in (1, 2, 3):
        repo.set_telescope_park(view.con, telescope_id=tel_id, in_park=1, now=NOW)
    view.min_fill_on.setChecked(True)
    view.max_panels_on.setChecked(True)
    view.replan()
    rows = view._result.counts["rows"]
    hiding = 0
    for name in pm.rig_choices(view._result):
        view._on_chip(name)
        shown = view.model.rowCount()
        if shown < rows:
            hiding += 1
            assert f"w soczewce {name}: {shown})" in view.counts_label.text()
        else:
            assert "w soczewce" not in view.counts_label.text()
    assert hiding, "żadna soczewka nie chowa - test straciłby sens"
    view._on_chip(None)
    assert "w soczewce" not in view.counts_label.text()


def test_mozaika_w_kolumnie_wypelnienia_przygaszona_z_podpowiedzia(view):
    """„100%" mozaiki i „100%" idealnego kadru nie mogą wyglądać tak samo: komórka mozaiki dostaje
    szarość motywu i podpowiedź; komórka jednego kadru - nie."""
    from PySide6.QtCore import Qt
    from horreum.gui import i18n
    from horreum.gui.planner import _COL_FILL
    m = view.model
    mosaic = [r for r in range(m.rowCount()) if m.row_at(r).fill_mosaic and m.row_at(r).visible]
    single = [r for r in range(m.rowCount()) if not m.row_at(r).fill_mosaic and m.row_at(r).visible]
    assert mosaic and single
    idx = m.index(mosaic[0], _COL_FILL)
    assert m.data(idx, Qt.ForegroundRole) is not None
    assert m.data(idx, Qt.ToolTipRole) == i18n.t("planner.fill_mosaic_tip")
    idx = m.index(single[0], _COL_FILL)
    assert m.data(idx, Qt.ForegroundRole) is None and m.data(idx, Qt.ToolTipRole) is None


def test_pola_progow_jednej_szerokosci_a_wypelnienie_z_jednostka(view):
    """Kolumna pól jest kolumną: progi, próg kosztu i oba pola filtra kadru mają TĘ SAMĄ, stałą
    szerokość (porównanie między polami, nie piksele). Wypełnienie niesie „%" w polu, a etykieta
    już nie."""
    from horreum.gui import i18n
    spins = list(view._spins.values()) + [view.max_cost, view.min_fill, view.max_panels]
    assert all(w.minimumWidth() == w.maximumWidth() for w in spins)
    assert len({w.maximumWidth() for w in spins}) == 1
    assert view.min_fill.suffix() == "%" and "%" in view.min_fill.text()
    assert "%" not in i18n.t("planner.min_fill")


def test_skrocony_naglowek_wypelnienia_niesie_pelna_nazwe_w_podpowiedzi(view):
    from PySide6.QtCore import Qt
    from horreum.gui import i18n
    from horreum.gui.planner import _COL_FILL
    assert view.model.headerData(_COL_FILL, Qt.Horizontal) == i18n.t("planner.col_fill")
    assert view.model.headerData(_COL_FILL, Qt.Horizontal, Qt.ToolTipRole) == \
        i18n.t("planner.col_fill_tip")
    assert view.model.headerData(0, Qt.Horizontal, Qt.ToolTipRole) is None


def test_porzadek_po_soczewce_przestawia_liste_bez_re_planu(view):
    """Dług P-A #3: chip zmieniał radę, ale NIE porządek — „patrzę oczami RC8" zostawiało na górze
    cele wybrane dla A140R. Sort żyje w WIDOKU: `targets._sort_key` (klucz rady, D-T4-c, z kubełkiem
    kadru PL-1) i CLI zostają nietknięte, a przełącznik nie liczy nocy od nowa."""
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


def test_baza_bez_stanowiska_mowi_wprost(qapp, tmp_path, ustawienia):
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


def test_szukanie_po_kanonie_i_zdanie_dla_nazwy_spoza_puli(view):
    """AR-146 na ekranie: „M 27” trafia jak „M27”, a „M 13” zamiast „nie znam celu” mówi, że to
    NGC6205 i że planer świadomie go nie bierze."""
    view.find_edit.setText("M 27")
    view.replan()
    assert [view.model.row_at(r).canon for r in range(view.model.rowCount())] == ["NGC6853"]
    view.find_edit.setText("M 13")
    view.replan()
    assert view.model.rowCount() == 0 and not view.empty_note.isHidden()
    assert view.empty_note.text() == "„M 13” = NGC6205, poza celami planera."


def test_przelacznik_pn_domyslnie_wylaczony_wlaczony_tnie_i_nazywa_sie(view):
    """Q14: przełącznik kandydatek i mimik PN na wzór filtra kadru - domyślnie wyłączony, włączony
    tnie listę, tytuł zwiniętego paska go nazywa, nota mówi ile schował; w trybie szukania
    tytuł mówi „nieczynny"."""
    assert view.hide_pn.isChecked() is False and view._params()["hide_doubtful_pn"] is False
    assert view._result.pn_filter == "off"
    assert "PN" not in view.controls_toggle.text()
    base = view.model.rowCount()
    kandydatka = next(view.model.row_at(r).canon for r in range(base)
                      if view.model.row_at(r).source.target.status == "candidate")
    view.hide_pn.setChecked(True)
    view.replan()
    assert view._result.pn_filter == "on"
    assert 0 < view.model.rowCount() < base
    assert kandydatka not in {view.model.row_at(r).canon for r in range(view.model.rowCount())}
    assert "bez kandydatek i mimik PN" in view.controls_toggle.text()
    assert "Przełącznik PN schował" in view.notes_label.text()
    view.find_edit.setText(kandydatka)
    view.replan()
    assert [view.model.row_at(r).canon for r in range(view.model.rowCount())][0] == kandydatka
    assert view.controls_toggle.text().endswith("bez kandydatek i mimik PN (nieczynny)")


def test_przelacznik_pn_przezywa_zamkniecie_i_reset_go_gasi(qapp, tmp_path, ustawienia):
    con = _seed(str(tmp_path / "pn.db"))
    first = PlannerView(con, db_path=None)
    first.hide_pn.setChecked(True)
    first.close()
    assert float(ustawienia.value("planner/hide_pn")) == 1.0
    second = PlannerView(con, db_path=None)
    try:
        assert second.hide_pn.isChecked() is True and second._params()["hide_doubtful_pn"] is True
        second._on_reset_thresholds()
        assert second.hide_pn.isChecked() is False
        assert float(ustawienia.value("planner/hide_pn")) == 0.0
    finally:
        second.close()
        con.close()


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
    """Dług P-A #2 (decyzja Zdzinia 2026-08-01): kolumny NIE ustępują, ustępuje okno. Liczby
    pomiaru (12 kolumn, platforma natywna) stoją przy `_MIN_W`. Test pilnuje deklaracji, nie pikseli
    renderu - te zależą od fontu maszyny (offscreen podawał wartości zawyżone o ~45%)."""
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

def test_watek_tla_liczy_i_sprzata_bez_zawisu(qapp, tmp_path, ustawienia):
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


def test_zatrzymaj_pola_zbiera_watek_w_trakcie_rachunku_bez_petli_zdarzen(qapp, tmp_path,
                                                                         ustawienia, monkeypatch):
    """P-K: okno zamykane w trakcie rachunku nocy woła `zatrzymaj_pola` i po powrocie wątku już
    nie ma - bez kręcenia pętli zdarzeń (`finished -> quit` idzie kolejką, więc bez jawnego `quit`
    wątek wisiałby w `exec()`, a `~QThread` na żywym wątku to 0xC0000409). Spóźniony wynik nie
    trafia na ekran, sygnał `finished` z kolejki nie wywraca `_cleanup_thread`, a zatrzymany widok
    nie zakłada nowego wątku.

    Falsyfikator: zdejmij `self._thread.quit()` z `zatrzymaj_pola` → `wait()` nie wraca."""
    import threading
    import time
    path = str(tmp_path / "stop.db")
    con = _seed(path)
    ruszyl = threading.Event()
    prawdziwy = targets.plan

    def _wolny(*a, **kw):
        ruszyl.set()
        time.sleep(0.5)
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(targets, "plan", _wolny)
    v = PlannerView(con, db_path=path)
    try:
        v.replan()
        assert ruszyl.wait(10), "rachunek ruszył w wątku tła"
        assert v._thread is not None
        t0 = time.monotonic()
        v.zatrzymaj_pola()
        assert time.monotonic() - t0 < 10
        assert v._thread is None and v._worker is None
        assert not v.busy.isVisible()
        for _ in range(20):                       # doręcz wszystko z kolejki: done, finished
            qapp.processEvents()
        assert v.model.rowCount() == 0, "spóźniony wynik nie trafił na ekran"
        v.replan()
        assert v._thread is None, "zatrzymany widok nie liczy od nowa"
        v.zatrzymaj_pola()                        # idempotentne
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


# ============================================================ AR-198: błąd bazy klasą w nagłówku

@pytest.mark.parametrize("lang", ["pl", "en"])
def test_planer_baza_niedostepna_klasa_i_szczegol(view, tmp_path, lang):
    """Rachunek nocy czyta bazę i dane pakietu - realna awaria to błąd SQLite: tu PRAWDZIWY, plik
    bazy niedostępny (katalog odpięty, SQLITE_CANTOPEN). Nagłówek i pasek stanu mówią klasą bazy
    w języku UI, surowy tekst SQLite w szczególe nagłówka; udany rachunek zdejmuje szczegół.
    Falsyfikator: `PlanWorker.run` z `f"{type(exc).__name__}: {exc}"`."""
    from horreum.gui import i18n
    i18n.set_lang(lang)
    pasek = []
    view.status_message.connect(pasek.append)
    try:
        prawdziwa = view._db_path
        view._db_path = str(tmp_path / "odpiety" / "planer.db")
        view._off_thread = False
        view.replan()
        zdanie = i18n.t("objchg.item.db_unavailable", db_code="SQLITE_CANTOPEN")
        assert view.night_label.text() == zdanie and pasek[-1] == zdanie
        assert view.night_label.toolTip() == zdanie + "\n" + i18n.t(
            "wb.os_detail_tip", detail="OperationalError: unable to open database file")
        if lang == "en":
            assert not set(zdanie) & set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"), zdanie
        view._db_path = prawdziwa
        view.replan()
        assert "2026-08-15" in view.night_label.text() and view.night_label.szczegol() == ""
    finally:
        i18n.set_lang("pl")


# ============================================================ AR-214: EXPECT rdzenia planera

@pytest.mark.parametrize("lang", ["pl", "en"])
def test_planer_blad_programu_rdzenia_zdanie_w_jezyku_UI_szczegol_techniczny(view, tmp_path,
                                                                            monkeypatch, lang):
    """PRAWDZIWY rdzeń: rekord assetu planera bez pola rozmiaru - `targets._target` rzuca goły
    `ValueError` z prozą PL (EXPECT: asset pakietu pilnują testy assetu). Nagłówek nocy i pasek
    mówią zdaniem błędu programu w języku UI, proza rdzenia z typem stoi wyłącznie w szczególe
    technicznym, a zdanie na pasek jedzie razem ze szczegółem (`ZdanieZeSzczegolem`).
    Falsyfikator: gałąź `ValueError` `PlanWorker.run` z `str(exc)` - proza PL na ekranie i w EN."""
    import json
    from horreum.gui import i18n, planner as planner_mod
    from horreum.gui.wb_worker import szczegol_zdania
    zly = tmp_path / "targets_core.json"
    zly.write_text(json.dumps({"targets": [{"c": "X1", "t": "G", "r": 10.0, "d": 41.0}]}),
                   encoding="utf-8")
    prawdziwy_asset = targets._asset_file
    monkeypatch.setattr(targets, "_asset_file",
                        lambda layer: zly if layer == "core" else prawdziwy_asset(layer))
    wyjatki, regula = [], planner_mod.powod_okna
    monkeypatch.setattr(planner_mod, "powod_okna", lambda exc: wyjatki.append(exc) or regula(exc))
    pasek = []
    view.status_message.connect(pasek.append)
    i18n.set_lang(lang)
    try:
        view.replan()
        (exc,) = wyjatki
        assert type(exc) is ValueError and "X1" in str(exc), exc       # rdzeń, nie atrapa
        zdanie = i18n.t("objchg.item.prog_error")
        # + miejsce w kodzie (AR-237): linia rdzenia, która odrzuciła rekord assetu
        import re
        wzor = re.escape(i18n.t("objchg.st.detail_tip", detail=f"ValueError: {exc}")
                         + " @ horreum/targets.py:") + r"\d+"
        assert view.night_label.text() == zdanie and re.fullmatch(wzor, view.night_label.szczegol())
        assert pasek[-1] == zdanie and re.fullmatch(wzor, szczegol_zdania(pasek[-1]))
        assert view.model.rowCount() == 0 and not view.bez_stanowiska
        if lang == "en":
            assert not set(zdanie) & set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"), zdanie
    finally:
        i18n.set_lang("pl")


# ============================================================ AR-253 - bezpiecznik pętli z miejscem w kodzie


def test_brak_stanowiska_przy_obecnym_stanowisku_szczegol_z_miejscem_rdzenia(qapp, tmp_path, monkeypatch):
    """AR-253: bezpiecznik pętli (`no_site` przy stanowisku, które ekran widzi) na PRAWDZIWYM wątku tła
    i prawdziwym rdzeniu - `targets.plan` rzuca `BrakStanowiska`, bo w wątku workera `sky.default_site`
    stanowiska nie widzi (rozjazd predykatów), a w wątku ekranu widzi. Po ponowieniu błąd idzie na ekran
    błędem programu, a szczegół niesie miejsce w kodzie: linię rdzenia, która rzuciła (powód liczony
    w handlerze wątku, pełny ślad). Falsyfikator: wyjątek sygnałem bez śladu (`with_traceback(None)`)
    i powód liczony dopiero w slocie - szczegół bez miejsca."""
    import re
    import threading
    import time
    from pathlib import Path

    import horreum
    from horreum import sky
    from horreum.gui import i18n
    path = str(tmp_path / "rozjazd.db")
    con = _seed(path)
    prawdziwa = sky.default_site
    wolania = []

    def _rozjazd(c):
        w_watku = threading.current_thread() is not threading.main_thread()
        wolania.append(w_watku)
        return None if w_watku else prawdziwa(c)
    monkeypatch.setattr(sky, "default_site", _rozjazd)
    view = PlannerView(con, db_path=path)
    try:
        view.replan()
        assert view._thread is not None                                  # bieg w wątku tła
        koniec = time.monotonic() + 30
        while not (view._thread is None and view.night_label.szczegol()):
            assert time.monotonic() < koniec, "bezpiecznik 30 s: błąd bezpiecznika z wątku tła"
            QApplication.processEvents()
            time.sleep(0.005)
        assert True in wolania and False in wolania, wolania             # obie strony rozjazdu
        assert view.night_label.text() == i18n.t("objchg.item.prog_error") and not view.bez_stanowiska
        glowa = i18n.t("objchg.st.detail_tip", detail="BrakStanowiska: ")
        miejsce = re.fullmatch(re.escape(glowa) + r".+ @ (horreum/[\w/]+\.py):(\d+)", view.night_label.szczegol())
        assert miejsce, view.night_label.szczegol()
        plik, nr = miejsce.group(1), int(miejsce.group(2))
        linia = (Path(horreum.__file__).parent.parent / plik).read_text(encoding="utf-8").splitlines()[nr - 1]
        assert plik == "horreum/targets.py" and "raise BrakStanowiska(" in linia, (plik, linia)
    finally:
        koniec = time.monotonic() + 30
        while view._thread is not None and time.monotonic() < koniec:
            QApplication.processEvents()
            time.sleep(0.005)
        view.close()
        con.close()


# ───────────────────────── AR-175: szerokości kolumn raz na wynik, trafienie szukajki aliasem

def _pompuj(n=20):
    from PySide6.QtCore import QCoreApplication, QEventLoop
    for _ in range(n):
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)


@pytest.fixture
def licznik_data(monkeypatch):
    """Licznik wywołań `PlannerTableModel.data` - podmiana metody KLASY przed budową widoku."""
    from horreum.gui import planner as P
    licz = [0]
    prawdziwe = P.PlannerTableModel.data

    def _data(self, *a, **k):
        licz[0] += 1
        return prawdziwe(self, *a, **k)
    monkeypatch.setattr(P.PlannerTableModel, "data", _data)
    return licz


@pytest.fixture
def widoczny(qapp, tmp_path, ustawienia, licznik_data):
    """Ekran INLINE pokazany (offscreen) - rysuje komórki, jak ekran na wierzchu."""
    con = _seed(str(tmp_path / "planer.db"))
    v = PlannerView(con, db_path=None, now_fn=lambda: NOW)       # minimum nocy z zegara widoku (AR-365)
    v.night_edit.setDate(QDate(2026, 8, 15))
    v.replan()
    v.resize(1400, 800)
    v.show()
    _pompuj()
    yield v
    v.close()
    con.close()


@pytest.mark.zmienia_motyw
def test_zmiana_motywu_nie_przelicza_szerokosci_kolumn_planera(qapp, widoczny, licznik_data):
    """AR-175: `ResizeToContents` przeliczał szerokości przejściem po WSZYSTKICH komórkach przy każdym
    zdarzeniu stylu i `dataChanged` - zmiana motywu to było ~341 tys. wywołań `data` i 5,3-5,8 s okna
    na kopii pf4. Teraz model pyta się tylko o komórki rysowane - mniej wywołań niż komórek listy.
    Mutant: `ResizeToContents` z powrotem (pełne przejście, ~7 ról na komórkę)."""
    from horreum.gui import app as app_mod
    from horreum.gui import planner as P
    komorki = widoczny.model.rowCount() * len(P._COLUMNS)
    assert widoczny.model.rowCount() > 100, "fixture za mała - próg bez sensu"
    for motyw in ("light", "dark"):
        licznik_data[0] = 0
        app_mod.apply_theme(qapp, motyw, styl=False)
        widoczny.use_theme(motyw)
        _pompuj()
        assert licznik_data[0] < komorki, (motyw, licznik_data[0], komorki)


def test_przeliczenie_planu_nie_pyta_modelu_o_szerokosci(widoczny, licznik_data):
    """AR-175: przeliczenie planu przy planerze na wierzchu kosztowało ~1 s przejścia Qt po komórkach;
    szerokości liczy metryka fontu (`szerokosci_kolumn`). Mutant: `resizeColumnsToContents()`
    w `_render_rows` (przejście po wszystkich komórkach)."""
    from horreum.gui import planner as P
    licznik_data[0] = 0
    widoczny.min_size.setValue(widoczny.min_size.value() + 1)
    widoczny.replan()
    _pompuj()
    assert 0 < licznik_data[0] < widoczny.model.rowCount() * len(P._COLUMNS), licznik_data[0]


def test_szerokosci_kolumn_z_metryka_wstrzyknieta():
    """AR-175, czysta funkcja szerokości (offscreen nie ma bazy fontów - metryka podana z zewnątrz):
    najszerszy tekst + margines elementu, nie mniej niż podpowiedź nagłówka; pusta lista - podpowiedź.
    Mutanty: margines zgubiony; podpowiedź nagłówka zgubiona (wąska kolumna liczb pod szerokim
    nagłówkiem)."""
    from types import SimpleNamespace

    from horreum.gui.szerokosci import szerokosci_kolumn
    wiersze = [SimpleNamespace(a="abc", b="1"), SimpleNamespace(a="abcdef", b="22")]
    metryka = lambda w, k: 7 * len(getattr(w, k))       # noqa: E731 - metryka testowa
    assert szerokosci_kolumn(metryka, wiersze, ["a", "b"], 5, [10, 40]) == [47, 40]
    assert szerokosci_kolumn(metryka, [], ["a", "b"], 5, [10, 40]) == [10, 40]


def test_zmiana_fontu_przelicza_kolumny_raz_na_serie_zdarzen(widoczny):
    """AR-175: sekcje `Fixed` nie idą za fontem same - `FontChange` zamawia przeliczenie RAZ na serię
    zdarzeń (`QTimer.singleShot(0)`), a szerokość kolumny „Cel” rośnie z większym fontem.
    Mutanty: przeliczenie przy każdym zdarzeniu (dwa); bez obsługi `FontChange` (zero)."""
    hh = widoczny.table.horizontalHeader()
    przed = hh.sectionSize(0)
    wolania = []
    prawdziwe = widoczny._dopasuj_kolumny
    widoczny._dopasuj_kolumny = lambda: (wolania.append(1), prawdziwe())
    f = widoczny.font()
    f.setPointSizeF(f.pointSizeF() * 1.5)
    widoczny.setFont(f)
    f.setPointSizeF(f.pointSizeF() * 1.2)
    widoczny.setFont(f)
    _pompuj()
    assert wolania == [1]
    assert hh.sectionSize(0) > przed


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_szukanie_M_4_na_ekranie_planera(view, lang):
    """AR-175 (wizytacja natywna): „M 4” trafia M42/M43/M49 podciągiem - kolumna „Cel” mówi alias, którym
    trafiło („NGC1976 (M 42)”), a pierwsza nota mówi, że samo M4 (NGC6121) jest poza celami planera.
    Zaznaczenie i kuratela zostają na kanonie. Prawdziwe pisanie i Enter w polu szukania.
    Mutant: kolumna czyta `canon` (alias znika)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from horreum.gui import i18n
    i18n.set_lang(lang)
    try:
        QTest.keyClicks(view.find_edit, "M 4")
        QTest.keyClick(view.find_edit, Qt.Key_Return)
        etykiety = {view.model.row_at(r).canon: view.model.data(view.model.index(r, 0))
                    for r in range(view.model.rowCount())}
        assert etykiety["NGC1976"] == "NGC1976 (M 42)" and etykiety["NGC4472"] == "NGC4472 (M 49)"
        pierwsza = view.notes_label.text().splitlines()[0]
        assert "NGC6121" in pierwsza and "M 4" in pierwsza
        assert pierwsza == i18n.t("planner.find_hits_outside",
                                  name=i18n.t("planner.find_as", needle="M 4", canon="NGC6121"),
                                  needle="M 4")
        r = next(r for r in range(view.model.rowCount()) if view.model.row_at(r).canon == "NGC1976")
        view.table.selectRow(r)
        assert view._selected_canon() == "NGC1976"
        assert view.panel.title() == i18n.t("planner.panel_of", canon="NGC1976")
    finally:
        i18n.set_lang("pl")


# ───────────────────────── AR-371: tytuł paska progów z wartością domyślną, próg kosztu i status w tytule

_ODCHYLENIA = (("min_size", 8.0, "≥8′ (domyślnie 6′)", "≥8′ (default 6′)"),
               ("min_dark", 20.0, "≥20′ (domyślnie 15′)", "≥20′ (default 15′)"),
               ("max_mag", 12.5, "≤12.5 (domyślnie 13)", "≤12.5 (default 13)"),
               ("min_alt", 35.0, "≥35° (domyślnie 30°)", "≥35° (default 30°)"),
               ("min_hours", 2.0, "2 h/kanał (domyślnie 1)", "2 h/channel (default 1)"))


def _widok_inline(tmp_path, nazwa="tytul.db"):
    con = _seed(str(tmp_path / nazwa))
    return PlannerView(con, db_path=None, now_fn=lambda: NOW), con


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_tytul_progow_dopisuje_wartosc_domyslna_przy_odchyleniu(qapp, tmp_path, ustawienia, lang):
    """AR-371 (`O1`): próg różny od domyślnego dopisuje domyślną za wartością (godziny - za „/kanał”); każdy próg
    odchylony osobno daje dokładnie jeden dopisek, powrót do domyślnej go zdejmuje. Tytuł bez pauzy, pełny tekst
    w podpowiedzi przycisku. Falsyfikatory: tytuł bez dopisków; dopisek przy każdym progu."""
    from horreum.gui import i18n
    i18n.set_lang(lang)
    v, con = _widok_inline(tmp_path)
    znacznik = "(domyślnie" if lang == "pl" else "(default"
    try:
        assert znacznik not in v.controls_toggle.text()
        for prog, wartosc, pl, en in _ODCHYLENIA:
            pole = v._spins[prog]
            domyslna = pole.value()
            pole.setValue(wartosc)
            tytul = v.controls_toggle.text()
            assert (pl if lang == "pl" else en) in tytul, tytul
            assert tytul.count(znacznik) == 1, tytul
            assert chr(0x2014) not in tytul and v.controls_toggle.toolTip() == tytul     # bez pauzy
            pole.setValue(domyslna)
            assert znacznik not in v.controls_toggle.text(), v.controls_toggle.text()
    finally:
        i18n.set_lang("pl")
        v.close()
        con.close()


def test_tytul_progow_odchylenie_na_tekscie_sformatowanym(view):
    """AR-375 (decyzja Zdzinia: prawdziwa precyzja wpisu, jedna forma liczby): próg 6,5 tytuł pokazuje „≥6.5′” z dopiskiem
    domyślnej - dawniej „≥6′” bez dopisku udawał domyślną; 6,6 to „≥6.6′”, nie „≥7′”. Tekst jest dokładny, więc
    odchylenie liczone na tekście = odchylenie wartości. Falsyfikator: format z zaokrągleniem do jedności."""
    view.min_size.setValue(6.5)
    assert "≥6.5′ (domyślnie 6′)" in view.controls_toggle.text()
    view.min_size.setValue(6.6)
    assert "≥6.6′ (domyślnie 6′)" in view.controls_toggle.text()
    view.min_size.setValue(6.0)
    assert "≥6′," in view.controls_toggle.text() and "(domyślnie" not in view.controls_toggle.text()


def test_tytul_progow_mowi_o_progu_kosztu_i_statusie(view):
    """AR-371: próg kosztu i filtr statusu tną listę jak progi, więc włączone stoją w tytule zwiniętego paska;
    wyłączone go nie zmieniają. Sygnały kontrolek, nie wołanie slotu. Falsyfikatory: przełącznik kosztu, pole kosztu
    albo zmiana statusu bez odświeżenia tytułu."""
    domyslny = view.controls_toggle.text()
    view.max_cost_on.setChecked(True)
    assert view.controls_toggle.text() == domyslny + " · koszt ≤3"
    view.max_cost.setValue(4.5)
    assert view.controls_toggle.text() == domyslny + " · koszt ≤4.5"
    view.status_combo.setCurrentIndex(view.status_combo.findData("planned"))
    assert view.controls_toggle.text() == domyslny + " · koszt ≤4.5 · status: zaplanowany"
    view.status_combo.setCurrentIndex(0)                  # „(dowolny)” - `findData(None)` w Qt daje -1
    view.max_cost_on.setChecked(False)
    assert view.controls_toggle.text() == domyslny


def test_przywroc_domyslne_podpowiedz_z_jednego_zrodla(view):
    """AR-371: podpowiedź „Przywróć domyślne” formatowana z wartości rdzenia, z członem przełącznika PN, który
    reset gasi; progi GUI biorą domyślne z `targets.DEFAULT_THRESHOLDS`. Liczby w asercji to pin decyzji, nie kopia
    stałej - ta sama forma co w tytule paska (AR-375). Człon filtra statusu: reset go zdejmuje (AR-385). Falsyfikator:
    proza z liczbami przepisanymi ręcznie, bez PN, bez statusu."""
    from horreum.gui import i18n
    from horreum.gui import planner as P
    assert view.reset_btn.toolTip() == i18n.t("planner.reset_thresholds_tip", size="6", dark="15", mag="13",
                                              alt="30", hours="1")
    assert "PN" in view.reset_btn.toolTip() and "filtr statusu" in view.reset_btn.toolTip()
    assert {n: spec[1] for n, spec in P._THRESHOLDS.items()} == dict(targets.DEFAULT_THRESHOLDS)


# ───────────────────────── AR-365: pole „Noc” - przełącznik „bieżąca noc”

@pytest.fixture
def pokazany(qapp, tmp_path, ustawienia):
    """Planer INLINE pokazany offscreen, noc programu (przełącznik zaznaczony), zegar widoku `NOW`."""
    con = _seed(str(tmp_path / "pokazany.db"))
    v = PlannerView(con, db_path=None, now_fn=lambda: NOW)
    v.resize(1400, 800)
    v.show()
    v.activateWindow()
    _pompuj()
    yield v
    v.zatrzymaj_pola()
    v.close()
    con.close()


def _czekaj_na(warunek, opis, limit_s=10):
    import time
    koniec = time.monotonic() + limit_s
    while not warunek():
        assert time.monotonic() < koniec, opis
        QApplication.processEvents()
        time.sleep(0.01)


def _opcja_pola_daty(pole):
    """Opcja stylu pola daty z kalendarzem - `QDateTimeEdit` trafia klik stylem combo (`hitTestComplexControl`)."""
    from PySide6.QtWidgets import QStyle, QStyleOptionComboBox
    opt = QStyleOptionComboBox()
    opt.initFrom(pole)
    opt.editable = True
    opt.frame = True
    opt.subControls = QStyle.SC_All
    return opt


def _klik_strzalki_daty(pole):
    """Klik w strzałkę kalendarza pola daty - punkt trafienia stylem, jak `QDateTimeEdit::mousePressEvent` (kalendarza
    nie otwiera ani F4, ani Alt+strzałka w dół - ta druga przestawia datę)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle
    opt = _opcja_pola_daty(pole)
    xs = [x for x in range(pole.width() // 2, pole.width())
          if pole.style().hitTestComplexControl(QStyle.CC_ComboBox, opt, QPoint(x, pole.height() // 2), pole)
          == QStyle.SC_ComboBoxArrow]
    assert xs, "pole daty bez strzałki kalendarza"
    punkt = QPoint(xs[len(xs) // 2], pole.height() // 2)
    QTest.mousePress(pole, Qt.LeftButton, Qt.NoModifier, punkt)
    _pompuj()
    QTest.mouseRelease(pole, Qt.LeftButton, Qt.NoModifier, punkt)
    _pompuj()


def test_noc_tab_wychodzi_z_pola(pokazany):
    """AR-365: Tab z pola „Noc” przechodzi przez sekcje daty i wychodzi do „cirrus” (dawniej przy wartości specjalnej
    „(bieżąca noc)” zostawał w polu 10/10). Tab nie wybiera daty - przełącznik stoi. Prawdziwe klawisze.
    Falsyfikator: wartość specjalna na minimum pola."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    QTest.mouseClick(v.night_edit.lineEdit(), Qt.LeftButton)
    _pompuj()
    assert QApplication.focusWidget() in (v.night_edit, v.night_edit.lineEdit())
    for _ in range(4):
        if QApplication.focusWidget() is v.cirrus:
            break
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
        _pompuj()
    assert QApplication.focusWidget() is v.cirrus
    assert v.night_auto.isChecked() and v._params()["night"] is None


def test_noc_kalendarz_na_nocy_rdzenia_bez_zmiany_wartosci(pokazany):
    """AR-365: przy przełączniku pole pokazuje noc policzonego planu, więc kalendarz otwiera się na niej (dawniej na
    1970-01) i samo otwarcie niczego nie wybiera. Zegar widoku (`NOW`, lipiec 2026) jest w innym miesiącu niż noc
    rdzenia z zegara rdzenia - strona z daty startowej pola nie przeszłaby. Falsyfikator: `_render_header` bez wpisania
    nocy rdzenia w pole."""
    v = pokazany
    noc = v._result.night_date
    assert (v.night_edit.date().year(), v.night_edit.date().month(), v.night_edit.date().day()) == \
        (noc.year, noc.month, noc.day)
    _klik_strzalki_daty(v.night_edit)
    kalendarz = v.night_edit.calendarWidget()
    try:
        assert kalendarz.isVisible()
        assert (kalendarz.yearShown(), kalendarz.monthShown()) == (noc.year, noc.month)
        assert v.night_auto.isChecked() and v._params()["night"] is None
    finally:
        kalendarz.window().hide()
        _pompuj()


def test_noc_wybor_daty_zdejmuje_przelacznik_a_przelacznik_wraca_do_nocy_rdzenia(pokazany):
    """AR-365: wybór daty w polu (strzałka klawiatury) zdejmuje przełącznik - noc jawna; klik w przełącznik wraca do nocy
    programu: rachunek z `night=None`, pole z nocą rdzenia, a wynik nie zdejmuje przełącznika. Prawdziwe klawisze
    i klik. Falsyfikatory: `dateChanged` bez zdjęcia przełącznika; wpis nocy rdzenia w pole bez `blockSignals`;
    przełącznik bez re-planu."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDateTimeEdit
    v = pokazany
    QTest.mouseClick(v.night_edit.lineEdit(), Qt.LeftButton)
    _pompuj()
    v.night_edit.setCurrentSection(QDateTimeEdit.Section.YearSection)   # sekcja bez sufitu - strzałka zawsze zmienia
    QTest.keyClick(v.night_edit, Qt.Key_Up)
    _pompuj()
    wybrana = v.night_edit.date()
    assert not v.night_auto.isChecked()
    jawna = date(wybrana.year(), wybrana.month(), wybrana.day())
    assert v._params()["night"] == jawna
    gen = v._gen
    # Rachunek wyboru daty (debounce) dochodzi PRZED klikiem w przełącznik - inaczej jego zegar policzyłby noc programu
    # za przełącznik bez re-planu.
    _czekaj_na(lambda: v._gen > gen and not v._pending_gen(), "re-plan po wyborze daty")
    assert v._result.night_date == jawna
    gen = v._gen
    QTest.mouseClick(v.night_auto, Qt.LeftButton)
    _czekaj_na(lambda: v._gen > gen and not v._pending_gen(), "re-plan po zaznaczeniu przełącznika")
    noc = v._result.night_date
    assert v.night_auto.isChecked() and v._params()["night"] is None
    assert (v.night_edit.date().year(), v.night_edit.date().month(), v.night_edit.date().day()) == \
        (noc.year, noc.month, noc.day)


def test_noc_minimum_rok_wstecz_od_zegara_widoku(pokazany):
    """AR-365: minimum pola to „dziś minus rok” z zegara WIDOKU (`now_fn`) - wpis z 1970 nie liczy planu bez słowa,
    a testy z nocą jawną nie spadają na klamrę wraz z upływem lat. Falsyfikator: minimum z zegara maszyny."""
    from PySide6.QtCore import QDate
    assert pokazany.night_edit.minimumDate() == QDate(2025, 7, 31)


def _trafienie_pola_daty(okno, pole, punkt, *, wprost=False):
    """Klik w `punkt` pola daty: przez okno (Qt wybiera widżet pod kursorem) albo doręczony wprost polu. Zwraca
    pod-kontrolkę stylu combo pod punktem i PIERWSZEGO odbiorcę wciśnięcia (`"pole"` albo `"tekst"` - pole linii)."""
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle

    class _Odbiorca(QObject):
        def __init__(self):
            super().__init__()
            self.kto = []

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.MouseButtonPress:
                self.kto.append("pole" if obj is pole else "tekst")
            return False
    filtr = _Odbiorca()
    pole.installEventFilter(filtr)
    pole.lineEdit().installEventFilter(filtr)
    try:
        kontrolka = pole.style().hitTestComplexControl(QStyle.CC_ComboBox, _opcja_pola_daty(pole), punkt, pole)
        if wprost:
            QTest.mouseClick(pole, Qt.LeftButton, Qt.NoModifier, punkt)
        else:
            QTest.mouseClick(okno.windowHandle(), Qt.LeftButton, Qt.NoModifier, pole.mapTo(okno, punkt))
        _pompuj()
    finally:
        pole.removeEventFilter(filtr)
        pole.lineEdit().removeEventFilter(filtr)
    return kontrolka, (filtr.kto[0] if filtr.kto else None)


@pytest.mark.parametrize("miejsce", ["srodek", "lewa", "gorna", "dolna", "wprost"])
def test_noc_klik_w_pole_nie_przestawia_daty_ani_przelacznika(pokazany, miejsce):
    """Klik myszą w pole „Noc” poza strzałką kalendarza nie robi kroku daty: pole z kalendarzem trafia klik stylem combo,
    a krok myszą spinboxa porównywał wynik ze stałymi spinboxa (ramka combo = „w górę”, pole tekstu = „w dół”). Prawdziwa
    droga przez okno: środek tekstu (dostaje go pole linii) i ramka pola - lewa, górna, dolna (dostaje ją samo pole);
    do tego klik doręczony wprost polu w środek tekstu. Każdy punkt osobno, z asercją pod-kontrolki stylu i odbiorcy
    wciśnięcia (punkt, który trafiłby gdzie indziej, nie dowodzi niczego). Po kliku: data, przełącznik i noc programu
    bez zmian, zero rachunków. Falsyfikator: pole bez `setButtonSymbols(NoButtons)` (ramka: noc +1 doba albo +1 rok,
    przełącznik zdjęty; tekst doręczony polu: noc -1 doba)."""
    import time

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QStyle
    v = pokazany
    pole = v.night_edit
    data, gen = pole.date(), v._gen
    tekst = pole.style().subControlRect(QStyle.CC_ComboBox, _opcja_pola_daty(pole), QStyle.SC_ComboBoxEditField, pole)
    srodek = tekst.center()
    punkt, kontrolka, odbiorca = {
        "srodek": (srodek, QStyle.SC_ComboBoxEditField, "tekst"),
        "lewa": (QPoint(0, srodek.y()), QStyle.SC_ComboBoxFrame, "pole"),
        "gorna": (QPoint(srodek.x(), 0), QStyle.SC_ComboBoxFrame, "pole"),
        "dolna": (QPoint(srodek.x(), pole.height() - 1), QStyle.SC_ComboBoxFrame, "pole"),
        "wprost": (srodek, QStyle.SC_ComboBoxEditField, "pole"),
    }[miejsce]
    assert _trafienie_pola_daty(v, pole, punkt, wprost=miejsce == "wprost") == (kontrolka, odbiorca)
    assert (pole.date(), v.night_auto.isChecked(), v._params()["night"]) == (data, True, None)
    time.sleep(0.4)                                      # debounce (300 ms) miałby czas odpalić
    _pompuj()
    assert v._gen == gen and not v._pending_gen()


def test_noc_kolko_z_fokusem_dalej_zmienia_date(pokazany):
    """Pole „Noc” bez przycisków kroku dalej przyjmuje kółko z fokusem (`kolko`, AR-349): ząbek po kliknięciu w pole
    zmienia datę i zdejmuje przełącznik. Falsyfikator: wyłączenie kroków, które zabiera też kółko."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDateTimeEdit
    v = pokazany
    pole = v.night_edit
    QTest.mouseClick(pole.lineEdit(), Qt.LeftButton)
    _pompuj()
    assert pole.hasFocus()
    pole.setCurrentSection(QDateTimeEdit.Section.YearSection)   # sekcja bez sufitu - ząbek zawsze zmienia
    przed = pole.date()
    srodek = pole.rect().center()
    ev = QWheelEvent(QPointF(srodek), QPointF(pole.mapToGlobal(srodek)), QPoint(), QPoint(0, 120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(pole, ev)
    _pompuj()
    assert pole.date() > przed and not v.night_auto.isChecked()


# ───────────────────────── AR-366: „Porządek” i chipy budowane raz

def test_porzadek_przezywa_przeliczenie_z_fokusem_i_otwarta_lista(pokazany):
    """AR-366: „Porządek” to TO SAMO combo po przeliczeniu - fokus zostaje na nim, a lista otwarta Alt+strzałką w dół
    przeżywa rachunek (dawniej combo powstawało przy każdym wyniku: fokus `None`, lista zamknięta). Prawdziwe klik,
    Escape i Alt+strzałka. Falsyfikator: combo budowane w `_rebuild_chips`."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    c = v.order_combo
    QTest.mouseClick(c, Qt.LeftButton)
    _pompuj()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape)
    _pompuj()
    assert QApplication.focusWidget() is c
    v.refresh()
    _pompuj()
    assert v.order_combo is c and QApplication.focusWidget() is c
    QTest.keyClick(c, Qt.Key_Down, Qt.AltModifier)
    _pompuj()
    try:
        assert c.view().isVisible()
        v.refresh()
        _pompuj()
        assert v.order_combo is c and c.view().isVisible()
    finally:
        c.hidePopup()
        _pompuj()


def test_jedna_grupa_chipow_a_chipy_bez_przebudowy_przy_tych_samych_zestawach(view):
    """AR-366: jedna `QButtonGroup` na widok (dawniej +1 przy każdym rachunku); przy tych samych zestawach chipy
    to te same przyciski, a zmiana parku (inny zbiór zestawów) daje nowe chipy w tej samej grupie.
    Falsyfikatory: nowa grupa przy wyniku; przebudowa chipów przy każdym wyniku."""
    from PySide6.QtWidgets import QButtonGroup
    from horreum.gui import i18n
    from horreum.gui import planner_model as pm
    chipy = view._chip_group.buttons()
    assert len(view.findChildren(QButtonGroup)) == 1
    for _ in range(3):
        view.replan()
    assert len(view.findChildren(QButtonGroup)) == 1
    assert view._chip_group.buttons() == chipy
    repo.set_telescope_park(view.con, telescope_id=1, in_park=1, now=NOW)
    view.replan()
    nowe = view._chip_group.buttons()
    assert [b.text() for b in nowe] == [i18n.t("planner.chip_best"), *pm.rig_choices(view._result)]
    assert len(nowe) < len(chipy) and not set(nowe) & set(chipy)
    assert len(view.findChildren(QButtonGroup)) == 1


def test_podpowiedz_chipow_idzie_za_filtrem_kadru_bez_przebudowy(view):
    """AR-366: chipy nie powstają od nowa przy tych samych zestawach, ale podpowiedź idzie za filtrem kadru (przy
    włączonym chip CHOWA wiersze). Falsyfikator: podpowiedź ustawiana tylko przy budowie chipów."""
    from horreum.gui import i18n
    repo.set_telescope_park(view.con, telescope_id=1, in_park=1, now=NOW)
    repo.set_telescope_park(view.con, telescope_id=2, in_park=1, now=NOW)
    view.replan()
    chipy = view._chip_group.buttons()
    assert all(b.toolTip() == i18n.t("planner.chip_tip") for b in chipy)
    view.min_fill_on.setChecked(True)
    view.replan()
    assert view._result.rig_filter == "on" and view._chip_group.buttons() == chipy
    assert all(b.toolTip() == i18n.t("planner.chip_tip_filter") for b in chipy)


# ───────────────────────── AR-350: rachunek w wątku czyta jedną migawkę

def test_rachunek_planera_w_watku_czyta_jedna_migawke(qapp, tmp_path, ustawienia, monkeypatch):
    """Rachunek na własnym połączeniu workera czyta bazę JEDNĄ migawką: zapis innego połączenia między odczytem
    pokrycia a odczytem kurateli nie trafia do wyniku (wynik opisuje stan sprzed zapisu, nie mieszankę), choć baza
    zapis ma. Prawdziwy rdzeń, podsłuch na odczycie pokrycia. Falsyfikator: `_compute` bez `BEGIN`."""
    from horreum.gui.planner import PlanWorker
    sciezka = str(tmp_path / "migawka.db")
    con = _seed(sciezka)
    cel = targets.plan(con, night=date(2026, 8, 15)).rows[0].target.canon
    prawdziwe = targets.archive_coverage

    def _zapis_w_srodku(c):
        wynik = prawdziwe(c)
        inne = db.connect(sciezka)
        inne.execute("INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
                     "VALUES (?, 'planned', NULL, NULL, ?, ?)", (cel, NOW, NOW))
        inne.commit()
        inne.close()
        return wynik
    monkeypatch.setattr(targets, "archive_coverage", _zapis_w_srodku)
    try:
        wynik = PlanWorker(sciezka, {"night": date(2026, 8, 15)}, 1)._compute()
        assert next(r for r in wynik.rows if r.target.canon == cel).plan_status is None
        assert targets.plan_marks(con)[cel]["status"] == "planned"
    finally:
        con.close()


# ───────────────────────── AR-376: cel i niezapisane pola panelu przeżywają chip, porządek i przeliczenie

def _klik_wiersz(v, r):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    rect = v.table.visualRect(v.model.index(r, 0))
    QTest.mouseClick(v.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    _pompuj()


def _wpisz_w_panel(v, notatka):
    """Niezapisane pola panelu prawdziwymi klawiszami: status o pozycję w dół („zaplanowany” przy celu bez
    oznaczenia), priorytet o krok w górę (1), notatka."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(v.panel_status, Qt.Key_Down)
    QTest.keyClick(v.panel_priority, Qt.Key_Up)
    QTest.mouseClick(v.panel_note, Qt.LeftButton)
    QTest.keyClicks(v.panel_note, notatka)
    _pompuj()


def _panel(v):
    row = v.selected_row()
    return (row.canon if row else None, v.panel.isEnabled(), v.panel_status.currentData(),
            v.panel_priority.value(), v.panel_note.text(), v.panel_note.isModified())


@pytest.mark.parametrize("gest", ["chip", "porzadek"])
def test_chip_i_porzadek_zostawiaja_cel_i_niezapisany_panel(pokazany, gest):
    """AR-376: klik chipa soczewki i zmiana „Porządku” to przerysowanie tego samego wyniku - zaznaczony cel zostaje,
    a niezapisane status, priorytet i notatka stoją w CZYNNYM panelu przy tym celu („Zapisz” czynne). Dwa
    przerysowania z rzędu: notatka zostaje niezapisana także po drugim. Prawdziwe kliki i klawisze. Falsyfikatory:
    przerysowanie bez celu (panel wygaszony - stan sprzed AR-376); zwrot bez statusu albo priorytetu; notatka
    oddana bez znacznika `isModified` (drugie przerysowanie ją gubi)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    _klik_wiersz(v, 1)
    cel = v.selected_row().canon
    _wpisz_w_panel(v, "domknac SII")
    oczekiwany = (cel, True, "planned", 1, "domknac SII", True)
    assert _panel(v) == oczekiwany
    for krok in range(2):
        if gest == "chip":
            QTest.mouseClick(v._chip_group.buttons()[1 - krok], Qt.LeftButton)
        else:
            QTest.keyClick(v.order_combo, Qt.Key_Down if krok == 0 else Qt.Key_Up)
        _pompuj()
        assert _panel(v) == oczekiwany, krok
        assert v.save_btn.isEnabled()


def test_przeliczenie_zostawia_cel_i_niezapisany_status_i_priorytet(pokazany):
    """AR-376: przeliczenie nocy (próg zmieniony klawiszem) zostawia cel z niezapisanym statusem i priorytetem -
    dawniej przeżywała je sama notatka. Falsyfikator: zwrot pól panelu bez statusu i priorytetu."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    _klik_wiersz(v, 1)
    cel = v.selected_row().canon
    _wpisz_w_panel(v, "x")
    gen = v._shown_gen
    QTest.keyClick(v.min_hours, Qt.Key_Up)               # próg godzin nie tnie listy - zmienia luki
    _czekaj_na(lambda: v._shown_gen > gen and not v._pending_gen(), "przeliczenie po zmianie progu")
    assert _panel(v) == (cel, True, "planned", 1, "x", True)


def test_zdjecie_oznaczenia_pokazuje_stan_bazy(pokazany):
    """AR-376: niezapisane wraca WYŁĄCZNIE, gdy różni się od kurateli wiersza - jedną regułą dla statusu, priorytetu
    i notatki: po „Zapisz” wartości zapisane są nowym stanem (notatka już nie „niezapisana”), a po „Zdejmij” panel mówi
    „(bez oznaczenia)” bez notatki, nie stan sprzed zdjęcia nad wierszem bez oznaczenia (status, którego użytkownik
    nie wybrał, czekałby na „Zapisz”). Falsyfikatory: zwrot pól bez porównania z kuratelą wiersza; notatka porównywana
    znacznikiem edycji, nie źródłem."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    _klik_wiersz(v, 0)
    cel = v.selected_row().canon
    QTest.keyClick(v.panel_status, Qt.Key_Down)
    QTest.keyClick(v.panel_priority, Qt.Key_Up)
    QTest.keyClick(v.panel_priority, Qt.Key_Up)
    QTest.mouseClick(v.panel_note, Qt.LeftButton)
    QTest.keyClicks(v.panel_note, "domknac SII")
    QTest.mouseClick(v.save_btn, Qt.LeftButton)
    _pompuj()
    assert _panel(v) == (cel, True, "planned", 2, "domknac SII", False)
    assert v.selected_row().plan == "zaplanowany 2"
    QTest.mouseClick(v.clear_btn, Qt.LeftButton)
    _pompuj()
    assert _panel(v) == (cel, True, None, 0, "", False)
    assert not v.save_btn.isEnabled() and not v.clear_btn.isEnabled()
    assert v.con.execute("SELECT count(*) FROM target_plan WHERE canon = ?", (cel,)).fetchone()[0] == 0


@pytest.mark.parametrize("zapisana, edycja", [(" nota ", False), ("nota", True)])
def test_zdjecie_oznaczenia_z_notatka_o_tej_samej_tresci_czysci_panel(pokazany, zapisana, edycja):
    """AR-376: notatka w panelu o TEJ SAMEJ treści co kuratela wiersza nie jest niezapisana, więc po „Zdejmij” panel
    zostaje bez notatki i bez znacznika zmiany - także gdy notatkę zapisała konsola ze spacjami brzegowymi (porównanie
    obcina je po obu stronach) i gdy człowiek dopisał znak i go skasował (znacznik edycji stoi, treść ta sama).
    Falsyfikatory: obcięcie spacji tylko po stronie panelu; notatka niezapisana po znaczniku edycji, nie po treści."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    cel = v.model.row_at(0).canon
    repo.set_target_plan(v.con, canon=cel, status="planned", priority=None, note=zapisana, now=NOW)
    v.refresh()
    _klik_wiersz(v, next(r for r in range(v.model.rowCount()) if v.model.row_at(r).canon == cel))
    assert _panel(v) == (cel, True, "planned", 0, zapisana, False)
    if edycja:
        QTest.mouseClick(v.panel_note, Qt.LeftButton)
        QTest.keyClick(v.panel_note, Qt.Key_End)
        QTest.keyClicks(v.panel_note, "x")
        QTest.keyClick(v.panel_note, Qt.Key_Backspace)
        assert v.panel_note.text() == zapisana and v.panel_note.isModified()
    QTest.mouseClick(v.clear_btn, Qt.LeftButton)
    _pompuj()
    assert _panel(v) == (cel, True, None, 0, "", False)
    assert v.con.execute("SELECT count(*) FROM target_plan WHERE canon = ?", (cel,)).fetchone()[0] == 0


def test_notatka_wpisana_wraca_bez_znacznika_gdy_baza_ma_te_sama_tresc(pokazany):
    """AR-376: notatka wpisana w panelu wraca po przeliczeniu; gdy w tym czasie konsola zapisała celowi tę samą treść ze
    spacjami brzegowymi, wraca jako ZGODNA z bazą (bez znacznika zmiany) - porównanie zwrotu obcina spacje po obu
    stronach. Falsyfikator: obcięcie spacji tylko po stronie panelu przy zwrocie."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = pokazany
    _klik_wiersz(v, 1)
    cel = v.selected_row().canon
    QTest.mouseClick(v.panel_note, Qt.LeftButton)
    QTest.keyClicks(v.panel_note, "nota")
    repo.set_target_plan(v.con, canon=cel, status="planned", priority=None, note=" nota ", now=NOW)   # konsola
    v.refresh()
    assert _panel(v) == (cel, True, "planned", 0, "nota", False)


def test_notatka_po_bledzie_rachunku_wraca_na_ten_sam_cel(pokazany, monkeypatch):
    """AR-376: rachunek, który padł (błąd bazy), opróżnia listę, ale panel dalej trzyma swój cel - następny udany
    rachunek oddaje mu wpisaną notatkę. Falsyfikator: zrzut pól po zaznaczeniu tabeli zamiast po celu panelu (po
    błędzie zaznaczenia nie ma, notatka przepada)."""
    import sqlite3
    v = pokazany
    _klik_wiersz(v, 1)
    cel = v.selected_row().canon
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(v.panel_note, Qt.LeftButton)
    QTest.keyClicks(v.panel_note, "po bledzie")
    prawdziwy = targets.plan

    def _pada(_con, **_kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(targets, "plan", _pada)
    v.refresh()
    assert v.model.rowCount() == 0 and v._result is None
    monkeypatch.setattr(targets, "plan", prawdziwy)
    v.refresh()
    assert _panel(v) == (cel, True, None, 0, "po bledzie", True)


def test_zaznaczenie_w_trakcie_rachunku_zostaje_z_notatka(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-376: rachunek w wątku tła trwa, człowiek zaznacza inny cel i pisze notatkę - wynik zostawia TEN cel z jego
    notatką. Dawniej cel zatrzaśnięty przy starcie rachunku wracał, a notatka drugiego celu lądowała w jego panelu
    („Zapisz” wpisałby ją cudzemu celowi). Rachunek wstrzymany bramą. Falsyfikatory: zatrzask celu w `replan`;
    zrzut notatki pod celem zatrzaśniętym zamiast celu panelu."""
    import threading
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    sciezka = str(tmp_path / "wyscig.db")
    con = _seed(sciezka)
    v = PlannerView(con, db_path=sciezka, now_fn=lambda: NOW)
    v.resize(1400, 800)
    v.show()
    brama = threading.Event()
    try:
        _czekaj_na(lambda: v._worker is None and v._result is not None and not v._pending_gen(), "plan nocy", 30)
        _klik_wiersz(v, 0)
        prawdziwy = targets.plan

        def _plan(c, **kw):
            brama.wait(20)
            return prawdziwy(c, **kw)
        monkeypatch.setattr(targets, "plan", _plan)
        v.refresh()                                       # rachunek w wątku, wstrzymany
        assert v._worker is not None
        _klik_wiersz(v, 2)
        cel = v.selected_row().canon
        QTest.mouseClick(v.panel_note, Qt.LeftButton)
        QTest.keyClicks(v.panel_note, "dla tego celu")
        brama.set()
        _czekaj_na(lambda: v._worker is None and not v._pending_gen(), "wynik rachunku", 30)
        _pompuj()
        assert _panel(v) == (cel, True, None, 0, "dla tego celu", True)
    finally:
        brama.set()
        v.zatrzymaj_pola()
        v.close()
        con.close()


def test_wybor_po_zapisie_w_trakcie_rachunku_bije_cel_zapisu(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-376: „Zapisz” przy celu A odkłada A jako cel przerysowania (`_replan_keeping`), rachunek w wątku tła trwa,
    człowiek zaznacza B i pisze notatkę - wynik zostawia B z notatką: wybór człowieka bije cel odłożony przez zapis.
    Rachunek wstrzymany bramą, prawdziwe kliki i klawisze. Falsyfikator: zaznaczenie bez zdjęcia odłożonego celu (wynik
    wraca na A, notatka B przepada)."""
    import threading
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    sciezka = str(tmp_path / "zapis_wybor.db")
    con = _seed(sciezka)
    v = PlannerView(con, db_path=sciezka, now_fn=lambda: NOW)
    v.resize(1400, 800)
    v.show()
    brama = threading.Event()
    try:
        _czekaj_na(lambda: v._worker is None and v._result is not None and not v._pending_gen(), "plan nocy", 30)
        _klik_wiersz(v, 0)
        a = v.selected_row().canon
        QTest.keyClick(v.panel_status, Qt.Key_Down)
        prawdziwy = targets.plan

        def _plan(c, **kw):
            brama.wait(20)
            return prawdziwy(c, **kw)
        monkeypatch.setattr(targets, "plan", _plan)
        QTest.mouseClick(v.save_btn, Qt.LeftButton)       # zapis A, rachunek w wątku wstrzymany
        assert v._worker is not None and v._keep_canon == a
        _klik_wiersz(v, 2)
        b = v.selected_row().canon
        QTest.mouseClick(v.panel_note, Qt.LeftButton)
        QTest.keyClicks(v.panel_note, "dla B")
        brama.set()
        _czekaj_na(lambda: v._worker is None and not v._pending_gen(), "wynik rachunku", 30)
        _pompuj()
        assert b != a and _panel(v) == (b, True, None, 0, "dla B", True)
        assert targets.plan_marks(con)[a]["status"] == "planned"
    finally:
        brama.set()
        v.zatrzymaj_pola()
        v.close()
        con.close()


def test_precyzja_liczby_progu_z_jednego_zrodla(view):
    """AR-375: tytuł paska, podpowiedź resetu i pusty stan formatują liczbę progu precyzją `planner_model.MIEJSCA_PROGU`
    - tą samą, którą trzymają pola progów i progu kosztu (wpis z klawiatury dostaje dokładnie tyle miejsc), a formater
    nie ma precyzji domyślnej. Falsyfikator: pole o innej precyzji niż stała (tytuł przekłamałby wpis)."""
    import inspect

    from horreum.gui import planner_model as pm
    assert {w.decimals() for w in list(view._spins.values()) + [view.max_cost]} == {pm.MIEJSCA_PROGU}
    assert inspect.signature(pm.tekst_progu).parameters["miejsc"].default is inspect.Parameter.empty


def test_przeniesienie_sieroty_nie_niesie_notatki_innego_celu(qapp, tmp_path, ustawienia):
    """AR-376: „Przenieś” sieroty wraca zaznaczeniem na cel, który przejął nazwę (jawny cel przerysowania), a notatka
    wpisana przy INNYM celu nie przechodzi do jego panelu - pola wracają wyłącznie na cel, którego panel je trzymał.
    Falsyfikator: zwrot niezapisanych pól bez sprawdzenia celu (notatka trafia do panelu celu przeniesienia)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    con = _seed(str(tmp_path / "sierota.db"))
    con.execute("INSERT INTO target_plan(canon, status, priority, note, created_at, updated_at) "
                "VALUES ('LBN529', 'planned', NULL, NULL, ?, ?)", (NOW, NOW))
    con.commit()
    v = PlannerView(con, db_path=None, now_fn=lambda: NOW)
    v.resize(1400, 800)
    v.show()
    _pompuj()
    try:
        r = next(i for i in range(v.model.rowCount()) if v.model.row_at(i).canon != "C9")
        _klik_wiersz(v, r)
        inny = v.selected_row().canon
        QTest.mouseClick(v.panel_note, Qt.LeftButton)
        QTest.keyClicks(v.panel_note, "notatka innego celu")
        v.orphan_list.setCurrentRow(0)                   # LBN529 - alias katalogowy C9
        QTest.mouseClick(v.orphan_move_btn, Qt.LeftButton)
        _pompuj()
        assert v.selected_row().canon == "C9" != inny
        assert v.panel_note.text() == "" and v.panel_status.currentData() == "planned"
    finally:
        v.zatrzymaj_pola()
        v.close()
        con.close()


# ───────────────────────── AR-385: pusta lista przy filtrze statusu nazywa go, a „Przywróć domyślne” go zdejmuje

def test_pusta_lista_przy_filtrze_statusu_nazywa_go_a_reset_go_zdejmuje(pokazany):
    """AR-385: filtr „zrobiony” bez oznaczeń (u Zdzinia 0 oznaczeń `done`) daje pustą listę, a zdanie w jej miejscu
    nazywa filtr statusu i liczbę celów, które schował - nie „poluzuj rozmiar…”. „Przywróć domyślne” zdejmuje filtr
    statusu (tytuł paska nazywa go cięciem) i lista wraca jednym klikiem. Prawdziwe klawisze i klik. Falsyfikatory:
    zdanie progów przy filtrze statusu; reset bez filtra statusu."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from horreum.gui import i18n
    v = pokazany
    wiersze = v.model.rowCount()
    assert wiersze > 0
    for _ in range(4):
        if v.status_combo.currentData() == "done":
            break
        QTest.keyClick(v.status_combo, Qt.Key_Down)
    assert v.status_combo.currentData() == "done"
    gen = v._shown_gen
    _czekaj_na(lambda: v._shown_gen > gen and not v._pending_gen(), "rachunek z filtrem statusu")
    assert v.model.rowCount() == 0 and not v.empty_note.isHidden() and v.table.isHidden()
    n = v._result.counts["above_horizon"]
    assert v.empty_note.text() == i18n.t_plural("planner.empty_by_status", n, status="zrobiony", any="(dowolny)")
    QTest.mouseClick(v.reset_btn, Qt.LeftButton)
    _pompuj()
    assert v.status_combo.currentData() is None
    assert v.model.rowCount() == wiersze and v.empty_note.isHidden()
    assert "status:" not in v.controls_toggle.text()


# ───────────────────────── AR-375: tytuł paska progów mówi wartość wpisaną z klawiatury

@pytest.mark.parametrize("calk, ulamek, czlon", [("6", "5", "≥6.5′ (domyślnie 6′)"), ("7", "5", "≥7.5′ (domyślnie 6′)"),
                                                ("6", "25", "≥6.25′ (domyślnie 6′)")])
def test_tytul_progow_wpis_z_klawiatury_mowi_prawdziwa_wartosc(pokazany, calk, ulamek, czlon):
    """AR-375: próg wpisany klawiszami z separatorem dziesiętnym pola (locale pola, nie stała kropka) stoi w tytule
    paska z prawdziwą precyzją wpisu - dawniej 6,5 dawało „≥6′” bez dopisku, a 7,5 „≥8′ (domyślnie 6′)”. Pełny tekst
    w podpowiedzi przycisku. Falsyfikator: format z zaokrągleniem do jedności."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    pole = pokazany.min_size
    QTest.mouseClick(pole.lineEdit(), Qt.LeftButton)
    QTest.keyClick(pole.lineEdit(), Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(pole.lineEdit(), calk)
    QTest.keyClicks(pole.lineEdit(), pole.locale().decimalPoint())
    QTest.keyClicks(pole.lineEdit(), ulamek)
    QTest.keyClick(pole.lineEdit(), Qt.Key_Return)
    _pompuj()
    tytul = pokazany.controls_toggle.text()
    assert czlon in tytul and pokazany.controls_toggle.toolTip() == tytul
