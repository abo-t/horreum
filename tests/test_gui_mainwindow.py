"""Okno aplikacji `MainWindow` (PLAN_gui_pipeline §2 + UX-redesign F5) — powłoka: menu Plik
(Otwórz/Nowa baza), SIDEBAR 3 miejsc (Dostawa / Zbiory / Porządki) prowadzący `QStackedWidget`,
własność połączenia (zamyka swoje `con` przy zmianie bazy i zamknięciu okna). Osie teleskop/
obserwatorium/obiekt to PODSTRONY Porządków (`TasksView`), ALIASOWANE na oknie — kontrakt
`axis_view`/`observatory_view`/`object_view`/`grid_view` przeżywa przemontowanie (R#10).
Sterujemy oknem bez pytest-qt (offscreen, QApplication ręcznie).

`importorskip` na poziomie modułu — bez PySide6 plik się pomija (czyni §7.2 prawdziwym)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo
from horreum.gui import queries
from horreum.gui.app import (
    NAV_DOSTAWA, NAV_PORZADKI, NAV_ZBIORY, MainWindow, ObjectAxisView, ObservatoryAxisView,
    TelescopeAxisView,
)
from horreum.gui.grid import PRESET_DUPS

from fixture_s8 import NOW, build, seed

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seeded_db(tmp_path, name="s8.db", *, object_axis=False):
    path = str(tmp_path / name)
    if object_axis:
        build(path, object_axis=True)                  # §8 + oś obiektu (liczniki zadań F5)
    else:
        con = db.open_db(path)
        seed(con)
        con.close()                                    # MainWindow otwiera własne połączenie
    return path


def _task_item(win, key):
    """Pozycja listy zadań po kluczu stanu (UserRole) — bez sprzęgania testu z numerem wiersza."""
    tasks = win.tasks_view.tasks
    for i in range(tasks.count()):
        if tasks.item(i).data(Qt.UserRole) == key:
            return tasks.item(i)
    raise AssertionError(f"brak pozycji zadania {key!r}")


def _task_row(win, key):
    """(etykieta, człon drugi) wiersza zadania — kontrakt renderu `rows.TwoPartDelegate` (P1)."""
    from horreum.gui import rows
    it = _task_item(win, key)
    return it.text(), it.data(rows.SECONDARY)


def test_otwarte_na_bazie_montuje_widoki(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert win.stack.count() == 3                  # Dostawa + Zbiory + Porządki (F5)
        assert win.nav.count() == 3 and not win.nav.isHidden()
        # kontrakt aliasów (R#10): osie żyją jako podstrony Porządków, atrybuty zostają
        assert isinstance(win.axis_view, TelescopeAxisView)
        assert isinstance(win.observatory_view, ObservatoryAxisView)
        assert isinstance(win.object_view, ObjectAxisView)
        assert win.grid_view is not None and win.tasks_view is not None
        assert win.axis_view is win.tasks_view.axis_view
        assert win.axis_view.table.rowCount() == 4     # read-model odbity w osadzonym widoku
        assert win.tasks_view.axis_view._now is win._now   # forward now_fn (F5R#2)
        assert win.nav.currentRow() == NAV_DOSTAWA     # start w Dostawie
    finally:
        win.close()                                    # closeEvent zamyka con (własność okna)


def test_brak_bazy_startuje_pusto_z_podpowiedzia(qapp):
    win = MainWindow(None)
    try:
        assert win.stack.count() == 0                  # bez bazy brak widoków
        assert win.nav.count() == 0 and win.nav.isHidden()
        assert not win.empty_note.isHidden()           # pusty stan ODKRYWALNY w centrum (wiz F5 #3)
        assert "brak baz" in win.statusBar().currentMessage().lower()
    finally:
        win.close()


def test_sidebar_przelacza_stack(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win._show_view(NAV_ZBIORY)
        assert win.stack.currentIndex() == NAV_ZBIORY and win.nav.currentRow() == NAV_ZBIORY
        win._show_view(NAV_PORZADKI)                   # wejście w Porządki nie wybucha (refresh)
        assert win.stack.currentIndex() == NAV_PORZADKI
    finally:
        win.close()


def test_zmiana_bazy_przemontowuje_i_zamyka_stara(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path, "a.db"))
    con_a = win.con
    try:
        assert win.axis_view.table.rowCount() == 4
        win._open_path(str(tmp_path / "b.db"))         # nowa, pusta baza
        assert win.con is not con_a                    # przejęta nowa baza
        assert win.db_path.endswith("b.db")            # ścieżka aktualna (worker jej potrzebuje)
        assert win.axis_view.table.rowCount() == 0     # pusta → 0 teleskopów
        assert win.stack.count() == 3                  # przemontowane 3 miejsca, nie nadmontowane
        with pytest.raises(Exception):                 # stare połączenie zamknięte
            con_a.execute("SELECT 1")
    finally:
        win.close()


def test_closeevent_zamyka_polaczenie(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    con = win.con
    win.close()
    assert win.con is None
    with pytest.raises(Exception):
        con.execute("SELECT 1")


def test_zapamietuje_ostatnia_baze_przez_callback(qapp, tmp_path):
    """Każdy wybór bazy woła wstrzyknięte `on_db_changed(path)` — to nim `main` zapisuje ostatnią
    bazę do trwałych ustawień. Start z bazą zapamiętuje ją; późniejsze „Otwórz" nadpisuje."""
    zapamietane = []
    win = MainWindow(_seeded_db(tmp_path, "a.db"), on_db_changed=zapamietane.append)
    try:
        assert zapamietane[-1].endswith("a.db")        # start z bazą → zapamiętana
        win._open_path(str(tmp_path / "b.db"))         # zmiana bazy → nadpisanie
        assert zapamietane[-1].endswith("b.db")
    finally:
        win.close()


def test_etap_pipeline_wylacza_akcje_osi_R5(qapp, tmp_path):
    """R5: w trakcie etapu pipeline'u (running_changed True) akcje ZAPISU osi są wyłączone (szczery
    disabled — worker pisze do bazy w tle). Po etapie (False) szczere stany wracają (proposed →
    approve znów aktywny)."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win.axis_view.table.selectRow(0)               # zaznacz proposed → approve normalnie aktywny
        win._on_pipeline_running(True)
        assert not win.axis_view.btn_approve.isEnabled()
        assert not win.axis_view.btn_merge.isEnabled()
        assert not win.axis_view.btn_unmerge.isEnabled()
        assert not win.observatory_view.btn_merge.isEnabled()   # oś obserwatorium też wyciszona
        win._on_pipeline_running(False)
        assert win.axis_view.btn_approve.isEnabled()   # szczery stan przywrócony (proposed)
    finally:
        win.close()


def test_menu_widok_przelacza_motyw(qapp, tmp_path, monkeypatch):
    """F6 §7: menu Widok odbija bieżący motyw bez klikania (default ciemny — recenzja #6);
    `_on_theme` podmienia kolory stanów gridu na żywo i utrwala wybór w QSettings (recenzja #7)."""
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QColor
    from horreum.gui import grid as grid_mod, theme
    store = {}
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: store.__setitem__(k, v))
    win = MainWindow(_seeded_db(tmp_path))
    try:
        # menu odbija DEFAULT (ciemny) — zaznaczony „Ciemny", nie „Jasny"
        assert win._theme_actions["dark"].isChecked()
        assert not win._theme_actions["light"].isChecked()
        # przełącz na jasny: kolory gridu podmienione, wybór utrwalony (po apply — recenzja #7)
        win._on_theme("light")
        assert grid_mod._COLORS["group_bg"] == QColor(theme.grid_colors("light")["group_bg"])
        assert store["ui/theme"] == "light"
        # z powrotem na ciemny — kolory wracają, facet refresh_theme nie wybucha
        win._on_theme("dark")
        assert grid_mod._COLORS["group_bg"] == QColor(theme.grid_colors("dark")["group_bg"])
        assert store["ui/theme"] == "dark"
    finally:
        win.close()
        grid_mod.use_theme(theme.DEFAULT)              # przywróć globalny stan modułu dla innych testów


def test_menu_widok_wybor_jezyka(qapp, tmp_path, monkeypatch):
    """#1: menu &Widok niesie sekcję języka (endonimy), zaznaczenie odbija ŻYWY język sesji
    (D-L1 restart-required: `_on_lang` utrwala `ui/lang`, NIE stosuje na żywo — nota w statusbarze)."""
    from PySide6.QtCore import QSettings
    from horreum.gui import i18n
    store = {}
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: store.__setitem__(k, v))
    i18n.set_lang("pl")                                  # symuluj żywy język sesji (ustawia go `main`)
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert set(win._lang_actions) == {"pl", "en"}
        assert win._lang_actions["pl"].isChecked()       # menu odbija żywy PL bez klikania
        assert not win._lang_actions["en"].isChecked()
        win._on_lang("en")                               # wybór EN — utrwalony, sesja NIE przełącza
        assert store["ui/lang"] == "en"
        assert i18n.current_lang() == "pl"               # D-L1: zmiana zadziała po restarcie
    finally:
        win.close()


# --- PORZĄDKI: lista zadań, badge, nawigacja do powierzchni (F5) ---

def test_badge_zywy_od_montazu(qapp, tmp_path):
    """F5R#1: badge liczony przy montażu, zanim user wejdzie w Porządki. s8+obiekt → 4 zadania
    akcyjne z n>0 (klatki bez obiektu 3, teleskopy 4, duplikaty 1, zniknięte 1; stanowiska 0 poza
    badge). „Zniknięte" doszły do badge'a wraz z passem obecności (P5) — wcześniej liczba istniała,
    ale była informacyjna, bo nie było przebiegu, który by ją wytwarzał."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (4)"
        # Wiersz DWUCZŁONOWY (P1, wiz F5 #6): etykieta w `text()`, liczba + chevron „›" w prawej
        # kolumnie (`rows.SECONDARY`) — liczby ustawiają się w kolumnę i dają się skanować.
        assert _task_row(win, "unresolved_lights") == ("Klatki bez obiektu", "3  ›")
        assert _task_row(win, "telescopes_unlabeled") == ("Teleskopy bez etykiety", "4  ›")
        assert _task_row(win, "dup_frames") == ("Duplikaty (>1 kopia)", "1  ›")
    finally:
        win.close()


def test_badge_zero_to_gole_porzadki(qapp, tmp_path):
    """F5R#8: N=0 → gołe „Porządki" (nie „(0)" — ten sam szum, co wieczny XISF w badge)."""
    path = str(tmp_path / "empty.db")
    db.open_db(path).close()                           # świeża pusta baza: wszystkie liczniki 0
    win = MainWindow(path)
    try:
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki"
    finally:
        win.close()


def test_zadanie_n_zero_wyszarzone_ale_klikalne(qapp, tmp_path):
    """Wiz F5 #6: „nic do zrobienia" ma być widać BEZ czytania liczby → wiersz akcyjny z n=0
    wyszarzony. Klikalność ZOSTAJE (podstrona osi to jedyna droga do niej po przemontowaniu
    nawigacji) — wyszarzenie jest sygnałem stanu, nie wyłączeniem. Odwrót po zmianie stanu
    (n=0 → n>0) MUSI zdjąć szarość, inaczej UI kłamie po pierwszym skanie."""
    from horreum.gui.tasks import _DIM
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        zero = _task_item(win, "observatories_unnamed")        # s8+obiekt: 0 stanowisk bez nazwy
        niezero = _task_item(win, "telescopes_unlabeled")      # 4 teleskopy bez etykiety
        assert _task_row(win, "observatories_unnamed")[1] == "0  ›"
        assert zero.foreground().color() == _DIM
        assert niezero.foreground().color() != _DIM
        assert zero.flags() & Qt.ItemIsEnabled                 # wciąż klikalny
        win.tasks_view.tasks.itemClicked.emit(zero)
        assert win.tasks_view.pages.currentIndex() != 0        # klik zaprowadził na podstronę osi
        # OBA kierunki muszą działać, inaczej UI kłamie po pierwszym skanie: n>0 → szarość zapala się,
        # a raz wyszarzony wiersz musi umieć wrócić do koloru z palety (QBrush(), nie „jaśniejszy szary").
        win.con.execute("INSERT INTO observatory (name, lat, lon, status, created_at) "
                        "VALUES (NULL, 50.0, 19.0, 'proposed', ?)", (NOW,))
        win.con.commit()
        win.tasks_view.refresh_counts()
        assert zero.foreground().color() != _DIM                  # dim → normalny
        for row in win.con.execute("SELECT id FROM telescope WHERE merged_into IS NULL").fetchall():
            repo.label_telescope(win.con, telescope_id=row[0], label=f"T{row[0]}", now=NOW)
        win.tasks_view.refresh_counts()
        assert niezero.foreground().color() == _DIM               # normalny → dim
    finally:
        win.close()


def test_klik_duplikaty_otwiera_zbiory_z_perspektywa(qapp, tmp_path):
    """Zadanie „Duplikaty" → Zbiory z USTAWIONĄ perspektywą (flaga `only_dups`, NIE drzewo filtra —
    R#14); nazwa presetu przez stałą PRESET_DUPS (F5R#11)."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "dup_frames"))
        assert win.stack.currentIndex() == NAV_ZBIORY
        assert win.grid_view._only_dups is True
        assert win.grid_view.combo_persp.currentText() == PRESET_DUPS
    finally:
        win.close()


def test_podstrona_osi_i_powrot_odswieza_licznik(qapp, tmp_path):
    """Klik w zadanie osi → podstrona; „← Porządki" wraca na listę i ODŚWIEŻA liczniki (user mógł
    nazwać teleskop w podstronie — świadomy cykl F5)."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "telescopes_unlabeled"))
        assert win.tasks_view.pages.currentIndex() != 0        # podstrona osi teleskopu
        first = win.axis_view.table.item(0, 0).data(Qt.UserRole)
        repo.label_telescope(win.con, telescope_id=first, label="Nazwany", now=NOW)
        win.tasks_view._on_back()
        assert win.tasks_view.pages.currentIndex() == 0
        assert _task_row(win, "telescopes_unlabeled") == ("Teleskopy bez etykiety", "3  ›")
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (4)"   # wciąż 4 (klatki/tel/dup/zniknięte)
    finally:
        win.close()


def test_stage_finished_odswieza_liczniki_zadan(qapp, tmp_path):
    """`_on_stage_finished` (po etapie pipeline'u) przeładowuje też liczniki zadań — badge maleje,
    gdy stan się poprawił (tu: wszystkie teleskopy nazwane poza GUI)."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        for row in win.con.execute("SELECT id FROM telescope WHERE merged_into IS NULL").fetchall():
            repo.label_telescope(win.con, telescope_id=row[0], label=f"T{row[0]}", now=NOW)
        win._on_stage_finished("resolve")
        assert _task_row(win, "telescopes_unlabeled") == ("Teleskopy bez etykiety", "0  ›")
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (3)"   # klatki + duplikaty + zniknięte
    finally:
        win.close()


def test_zadanie_zniknietych_otwiera_perspektywe(qapp, tmp_path):
    """P5c: klik w „Zniknięte z dysku" prowadzi do Zbiorów z perspektywą `PRESET_VANISHED`, a grid
    pokazuje DOKŁADNIE klatki bez ani jednej obecnej kopii. Bez tego licznik byłby liczbą, której
    nie da się rozwinąć w listę (ten sam dług, co kubełek `unreadable` przed drążeniem)."""
    from horreum.gui.grid import PRESET_VANISHED
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "vanished_frames"))
        assert win.stack.currentIndex() == NAV_ZBIORY
        assert win.grid_view._only_vanished is True
        assert win.grid_view.combo_persp.currentText() == PRESET_VANISHED
        widoczne = set(win.grid_view._frame_ids)               # to, co WIDAĆ po trimie perspektywy
        assert widoczne == queries.vanished_frame_ids(win.con) and len(widoczne) == 1
    finally:
        win.close()


def test_kazdy_wiersz_porzadkow_prowadzi_do_powierzchni(qapp, tmp_path):
    """Po P6c KAŻDY wiersz Porządków jest AKCYJNY: ostatnia pozycja informacyjna („XISF — nagłówki
    tylko do odczytu") zniknęła razem z pisarzem XISF, który uczynił ją nieprawdą. Lista nie ma
    już wiersza, który wygląda jak zadanie, a nigdzie nie prowadzi.

    Bezpiecznik na pozycję BEZ akcji zostaje w kodzie i jest tu pinowany wprost (klik w element bez
    `UserRole` = cisza, nie wyjątek) — tabela `_TASKS` jest DANYMI, więc kolejna pozycja
    informacyjna nie może wywalić okna tylko dlatego, że dziś takiej nie ma."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = win.tasks_view.tasks
        assert tasks.count() and all(tasks.item(i).data(Qt.UserRole) is not None
                                     for i in range(tasks.count()))
        win.tasks_view._on_task_clicked(QListWidgetItem("bez akcji"))   # UserRole = None
        assert win.tasks_view.pages.currentIndex() == 0
        assert win.stack.currentIndex() == NAV_DOSTAWA
    finally:
        win.close()


def test_pusta_perspektywa_nie_klamie_ze_baza_pusta(qapp, tmp_path):
    """P1 (wizytator P5 #2): perspektywa z trimem, która daje ZERO klatek, mówiła „Baza pusta —
    przyjmij dostawę" NA PEŁNEJ BAZIE, wysyłając usera po nieistniejącą dostawę zamiast po zmianę
    perspektywy. Przyczyna: `filter_engine.run(None, …)` oddaje uniwersum WPROST (ten sam obiekt, co
    memoizacja refreshu), więc `frame_ids &= trim` przycinało cache W MIEJSCU — a `grid.py` pyta
    potem `universe_fn()`, żeby odróżnić „filtr nic nie wpuścił" od „w bazie nic nie ma".

    Baza §8 bez osi obiektu nie ma zniknięć, więc „Zniknięte" są tu pustą perspektywą. Ten sam błąd
    dotyczył Duplikatów i Do przeglądu — P5 tylko doprowadził do niego przyciskiem."""
    from horreum.gui.grid import PRESET_VANISHED, _EMPTY_DB, _EMPTY_FILTER
    from horreum.gui import i18n                          # _EMPTY_* to KLUCZE (rollout i18n) — rozwiąż t()
    win = MainWindow(_seeded_db(tmp_path))               # bez object_axis → zero present=0
    try:
        win._show_view(NAV_ZBIORY)
        wszystkie = len(win.grid_view._frame_ids)
        assert wszystkie > 1
        win.grid_view.apply_perspective(PRESET_VANISHED)
        assert win.grid_view._frame_ids == []            # pusto — i to jest PRAWDA o tej bazie
        assert win.grid_view.empty.text() == i18n.t(_EMPTY_FILTER)
        assert win.grid_view.empty.text() != i18n.t(_EMPTY_DB)   # baza ma klatki; grid nie kłamie
        win.grid_view.apply_perspective("Przegląd")
        assert len(win.grid_view._frame_ids) == wszystkie
    finally:
        win.close()
