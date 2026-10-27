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
    NAV_DOM, NAV_DOSTAWA, NAV_PORZADKI, NAV_ZBIORY, STRONA_DOM, STRONA_PORZADKI, STRONA_ZBIORY,
    MainWindow, ObjectAxisView, ObservatoryAxisView, TelescopeAxisView,
)
from horreum.gui.grid import PRESET_DUPS, Recepta

from fixture_s8 import NOW, build, seed

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _pola_inline(monkeypatch):
    """Pokrycie pól Zbiorów INLINE (seam `MainWindow._pola_poza_watkiem`): testy tego pliku liczą
    odświeżenia i wejścia w `refresh`, a pierwszy wynik z wątku tła, doręczony w nieznanej chwili,
    dokładałby przeładowanie zbioru w środku pomiaru. Drogę produkcyjną (wątek, odcisk kart,
    sprzątanie przy zamknięciu i przełączeniu bazy) sprawdza `test_gui_pola_w_tle.py`.

    Osie Porządków WCZYTANE OD RAZU (`_osie_leniwie`, AR-326 - osobny przełącznik): testy tego pliku czytają
    tabele osi zaraz po `open_path`; osie leniwe w trybie bez wątków pinuje
    `test_osie_leniwe_bez_watkow_tla_czytaja_baze_przy_wejsciu`."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    monkeypatch.setattr(MainWindow, "_osie_leniwie", False)


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


def test_tytul_okna_niesie_numer_wersji(qapp, tmp_path):
    """Wydanie jedzie do użytkownika jako JEDEN `horreum-gui.exe` (onefile — CLI `--version` tam
    nie powstaje), więc TYTUŁ jest jedyną powierzchnią, na której da się sprawdzić, co się ma.
    Numer czytany z jedynego właściciela (`pyproject.toml`) — bramka klasy: `tests/test_version.py`."""
    import horreum
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert win.windowTitle() == f"Horreum {horreum.__version__}"
    finally:
        win.close()


def test_zapis_naglowkow_do_plikow_gasi_etapy_Dostawy(qapp, tmp_path):
    """Trzecia strona mutexu writebacku: zapis z gridu ALBO z okna naprawy nagłówka gasi przyciski
    etapów Dostawy, a publiczne `run_stage` odmawia z powodem. Bez tego „Przyjmij nowe” czytało plik
    zapisywany obok w miejscu. Anulowanie biegnącego etapu i powrót po zapisie działają."""
    from horreum.gui import i18n
    win = MainWindow(_seeded_db(tmp_path))
    try:
        p = win.pipeline_view
        assert p.btn_group.isEnabled()
        for zrodlo in (win.grid_view.writeback_busy, win.object_view.writeback_busy):
            zrodlo.emit(True)
            assert not p.btn_group.isEnabled() and not p.btn_receive.isEnabled()
            assert p.run_stage("resolve") == i18n.t("pipeline.refuse.writeback")
            assert p._thread is None                   # odmowa nie startuje etapu
            zrodlo.emit(False)
            assert p.btn_group.isEnabled() and p.btn_receive.isEnabled()
    finally:
        win.close()


def test_zamkniecie_okna_zbiera_watki_okien_dialogowych(qapp, tmp_path):
    """Zamknięte okno dialogowe zostaje ukrytym dzieckiem okna głównego razem ze swoim wątkiem tła
    (lista wydań w oknie żniw nie ma punktu przerwania), więc zamknięcie aplikacji zbiera i jego
    wątki - `QThread` niszczony w biegu to twardy abort. Okno bez `zatrzymaj_pola` jest pomijane."""
    from PySide6.QtWidgets import QDialog

    class _OknoZWatkiem(QDialog):
        def __init__(self, parent):
            super().__init__(parent)
            self.zatrzymania = 0

        def zatrzymaj_pola(self):
            self.zatrzymania += 1

    win = MainWindow(_seeded_db(tmp_path))
    okno = _OknoZWatkiem(win)
    zwykle = QDialog(win)                              # bez metody: nic do zebrania
    try:
        win._zatrzymaj_watki_widokow()
        assert okno.zatrzymania == 1
    finally:
        win.close()
    assert okno.zatrzymania == 2 and zwykle.parent() is win


def test_otwarte_na_bazie_montuje_widoki(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    try:
        # strony: Dom + zbiory (Znajdź/klasyczne) + Dostawa + Porządki (F5) + Planer (T5);
        # wiersze: te same miejsca + drugi wiersz zbiorów + nagłówek „Więcej"
        assert win.stack.count() == 5
        assert win.nav.count() == 7 and not win.nav.isHidden()
        # kontrakt aliasów (R#10): osie żyją jako podstrony Porządków, atrybuty zostają
        assert isinstance(win.axis_view, TelescopeAxisView)
        assert isinstance(win.observatory_view, ObservatoryAxisView)
        assert isinstance(win.object_view, ObjectAxisView)
        assert win.grid_view is not None and win.tasks_view is not None
        assert win.axis_view is win.tasks_view.axis_view
        assert win.axis_view.table.rowCount() == 4     # read-model odbity w osadzonym widoku
        assert win.tasks_view.axis_view._now is win._now   # forward now_fn (F5R#2)
        assert win.nav.currentRow() == NAV_DOM         # start na Domu
        assert win.stack.currentIndex() == STRONA_DOM
    finally:
        win.close()                                    # closeEvent zamyka con (własność okna)


def test_brak_bazy_startuje_pusto_z_podpowiedzia(qapp):
    win = MainWindow(None)
    try:
        assert win.stack.count() == 0                  # bez bazy brak widoków
        assert win.nav.count() == 0 and win.nav.isHidden()
        assert not win.empty_note.isHidden()           # pusty stan ODKRYWALNY w centrum (wiz F5 #3)
        assert "brak baz" in win.report_label.text().lower()
    finally:
        win.close()


def test_sidebar_przelacza_stack(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win._show_view(NAV_ZBIORY)
        assert win.stack.currentIndex() == STRONA_ZBIORY and win.nav.currentRow() == NAV_ZBIORY
        win._show_view(NAV_PORZADKI)                   # wejście w Porządki nie wybucha (refresh)
        assert win.stack.currentIndex() == STRONA_PORZADKI
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
        assert win.stack.count() == 5                  # przemontowane 5 stron, nie nadmontowane
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


@pytest.mark.zmienia_motyw          # przełącza motyw świadomie (stan zastany wraca też w `finally`)
def test_menu_widok_przelacza_motyw(qapp, tmp_path, ustawienia):
    """F6 §7: menu Widok odbija bieżący motyw bez klikania (default ciemny — recenzja #6);
    `_on_theme` podmienia kolory stanów gridu na żywo i utrwala wybór w QSettings (recenzja #7)."""
    from PySide6.QtGui import QColor
    from horreum.gui import grid as grid_mod, theme
    # `_on_theme` stosuje motyw do CAŁEJ aplikacji (QSS, paleta, styl) - stan zastany wraca w
    # `finally`, inaczej arkusz motywu zmienia metryki testom puszczonym później w tej sesji
    # (rząd facetów liczony pod innym fontem).
    qss0, paleta0, styl0 = qapp.styleSheet(), qapp.palette(), qapp.style().name()
    win = MainWindow(_seeded_db(tmp_path))
    try:
        # menu odbija DEFAULT (ciemny) — zaznaczony „Ciemny", nie „Jasny"
        assert win._theme_actions["dark"].isChecked()
        assert not win._theme_actions["light"].isChecked()
        # przełącz na jasny: kolory gridu podmienione, wybór utrwalony (po apply — recenzja #7)
        win._on_theme("light")
        assert grid_mod._COLORS["group_bg"] == QColor(theme.grid_colors("light")["group_bg"])
        assert ustawienia.value("ui/theme") == "light"
        # P-C: `apply_theme` przełącza TEŻ kolory nagłówka raportu projekcji — moduł ma własne
        # `_COLORS` (QSS ról nie sięga QPlainTextEdit), więc pominięcie go w apply zostawiłoby
        # dialog na kolorach ciemnych w jasnej skórce (ta sama pułapka co planer, wiz T5 R2).
        from horreum.gui import projection_dialog as pd_mod
        assert pd_mod._COLORS["ok"] == QColor(theme.accents("light")["ok_green"])
        # z powrotem na ciemny — kolory wracają, facet refresh_theme nie wybucha
        win._on_theme("dark")
        assert grid_mod._COLORS["group_bg"] == QColor(theme.grid_colors("dark")["group_bg"])
        assert ustawienia.value("ui/theme") == "dark"
    finally:
        win.close()
        grid_mod.use_theme(theme.DEFAULT)              # przywróć globalny stan modułu dla innych testów
        qapp.setStyle(styl0)
        qapp.setPalette(paleta0)
        qapp.setStyleSheet(qss0)


def test_menu_widok_wybor_jezyka(qapp, tmp_path, ustawienia):
    """#1: menu &Widok niesie sekcję języka (endonimy), zaznaczenie odbija ŻYWY język sesji
    (D-L1 restart-required: `_on_lang` utrwala `ui/lang`, NIE stosuje na żywo — nota w statusbarze)."""
    from horreum.gui import i18n
    i18n.set_lang("pl")                                  # symuluj żywy język sesji (ustawia go `main`)
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert set(win._lang_actions) == {"pl", "en"}
        assert win._lang_actions["pl"].isChecked()       # menu odbija żywy PL bez klikania
        assert not win._lang_actions["en"].isChecked()
        win._on_lang("en")                               # wybór EN — utrwalony, sesja NIE przełącza
        assert ustawienia.value("ui/lang") == "en"
        assert i18n.current_lang() == "pl"               # D-L1: zmiana zadziała po restarcie
    finally:
        win.close()


# --- PORZĄDKI: lista zadań, badge, nawigacja do powierzchni (F5) ---

def test_badge_zywy_od_montazu(qapp, tmp_path):
    """F5R#1: badge liczony przy montażu, zanim user wejdzie w Porządki. s8+obiekt → 4 zadania
    akcyjne z n>0 (klatki bez obiektu 3, teleskopy 4, duplikaty 1, zniknięte 1; stanowiska 0 poza
    badge). „Zniknięte" doszły do badge'a wraz z passem obecności (P5) — wcześniej liczba istniała,
    ale była informacyjna, bo nie było przebiegu, który by ją wytwarzał.

    Siódma pozycja (AR-135): fikstura zakłada obiekt o kanonie `M42` z klatkami - stara tożsamość
    `NGC1976` z pary `catalog_xref` - więc wiersz „Nazwa katalogowa wskazuje inny obiekt” liczy jego
    klatki. Ta pozycja nie zależy od żadnego gestu niżej w tym pliku, plakietka niesie ją stale."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (7)"
        assert _task_row(win, "xref_reconcile_frames") == (
            "Nazwa katalogowa wskazuje inny obiekt", "3  ›")
        tip = _task_item(win, "xref_reconcile_frames").toolTip()
        assert "M42 → NGC1976" in tip and "„Zmień obiekt…”" in tip      # zdanie NAZYWA cel
        cele = []
        win.tasks_view.open_collection.connect(cele.append)
        win.tasks_view._on_task_clicked(_task_item(win, "xref_reconcile_frames"))
        from horreum.gui.grid_model import PRESET_XREF_RECONCILE
        assert cele == [PRESET_XREF_RECONCILE]
        # Wiersz DWUCZŁONOWY (P1, wiz F5 #6): etykieta w `text()`, liczba + chevron „›" w prawej
        # kolumnie (`rows.SECONDARY`) — liczby ustawiają się w kolumnę i dają się skanować.
        assert _task_row(win, "unresolved_lights") == ("Klatki bez obiektu", "3  ›")
        assert _task_row(win, "telescopes_unlabeled") == ("Teleskopy bez etykiety", "4  ›")
        assert _task_row(win, "dup_frames") == ("Duplikaty (>1 kopia)", "1  ›")
    finally:
        win.close()


def test_en_render_zadania(qapp, tmp_path):
    """§5 (rollout drobne): `set_lang('en')` PRZED budową okna → etykiety zadań Porządków (stała
    `_TASKS` trzyma KLUCZE) renderują EN z katalogu; człon drugi (liczba + „›") bez zmian. Tożsamość
    klucza stanu (`unresolved_lights`) niezmienna → nawigacja działa pod EN. Autouse-fixture wraca na PL."""
    from horreum.gui import i18n
    i18n.set_lang("en")
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        assert _task_row(win, "unresolved_lights") == ("Frames without object", "3  ›")
        assert _task_row(win, "dup_frames") == ("Duplicates (>1 copy)", "1  ›")
        assert win.nav.item(NAV_PORZADKI).text() == "Housekeeping (7)"    # nav.porzadki_count EN (app)
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
    (n=0 → n>0) MUSI zdjąć szarość, inaczej UI kłamie po pierwszym skanie.

    Wiz P1 #6: razem z szarością gaśnie POGRUBIENIE liczby (rola `rows.STRONG` per wiersz). Gdy
    `strong` było ustawieniem CAŁEJ listy, „0" na wyszarzonym wierszu zostawało pogrubione —
    krzyczało dokładnie tam, gdzie nie ma nic do zrobienia."""
    from horreum.gui import rows
    # `_DIM` jest DICT-em od P-C (kolor przeniesiony do motywu — wcześniej sztywne
    # `QColor(0x88,0x88,0x88)` miało w motywie jasnym 3,54:1, poniżej AA).
    from horreum.gui.tasks import _DIM
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        zero = _task_item(win, "observatories_unnamed")        # s8+obiekt: 0 stanowisk bez nazwy
        niezero = _task_item(win, "telescopes_unlabeled")      # 4 teleskopy bez etykiety
        assert _task_row(win, "observatories_unnamed")[1] == "0  ›"
        assert zero.foreground().color() == _DIM["fg"]
        assert niezero.foreground().color() != _DIM["fg"]
        assert zero.data(rows.STRONG) is False                 # n=0 → liczba bez pogrubienia
        assert niezero.data(rows.STRONG) is True               # n>0 → liczba jest treścią
        assert zero.flags() & Qt.ItemIsEnabled                 # wciąż klikalny
        win.tasks_view.tasks.itemClicked.emit(zero)
        assert win.tasks_view.pages.currentIndex() != 0        # klik zaprowadził na podstronę osi
        # OBA kierunki muszą działać, inaczej UI kłamie po pierwszym skanie: n>0 → szarość zapala się,
        # a raz wyszarzony wiersz musi umieć wrócić do koloru z palety (QBrush(), nie „jaśniejszy szary").
        win.con.execute("INSERT INTO observatory (name, lat, lon, status, created_at) "
                        "VALUES (NULL, 50.0, 19.0, 'proposed', ?)", (NOW,))
        win.con.commit()
        win.tasks_view.refresh_counts()
        assert zero.foreground().color() != _DIM["fg"]                  # dim → normalny
        assert zero.data(rows.STRONG) is True                     # …a z nim wraca pogrubienie
        for row in win.con.execute("SELECT id FROM telescope WHERE merged_into IS NULL").fetchall():
            repo.label_telescope(win.con, telescope_id=row[0], label=f"T{row[0]}", now=NOW)
        win.tasks_view.refresh_counts()
        assert niezero.foreground().color() == _DIM["fg"]               # normalny → dim
        assert niezero.data(rows.STRONG) is False
    finally:
        win.close()


def test_lista_zadan_hugguje_tresc(qapp, tmp_path):
    """Wizytator P1 tura 2: lista zadań dostawała CAŁY pion strony — przy oknie 1400×900 ramka miała
    807 px na 60 px treści (~750 px obramowanej pustki, zmierzone na żywej pf4), co czyta się jako
    „coś tu miało być". Wysokość idzie z POMIARU (`sizeHintForRow(0) × liczba wierszy` + ramka),
    a nie ze stałej — inaczej rozjedzie się przy innym DPI/foncie. Reszta pionu zostaje pusta,
    ale BEZ ramki (stretch pod listą).

    Falsyfikator: gdyby lista nadal rosła z oknem, dwa razy wyższe okno dałoby wyższą listę."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.resize(1400, 900)
        win.show()
        qapp.processEvents()
        tasks = win.tasks_view.tasks
        win.tasks_view.refresh_counts()
        oczekiwana = tasks.sizeHintForRow(0) * tasks.count() + 2 * tasks.frameWidth()
        assert tasks.height() == oczekiwana
        # treść, nie cały pion strony - niezmiennik zamiast liczbowego sufitu (ten rósł z każdym
        # nowym wierszem: optyka AR-128/AR-129, cofnięcie niedokończone AR-318); falsyfikator
        # „lista rośnie z oknem" niżej zostaje bez zmian
        assert tasks.height() < tasks.parentWidget().height()
        win.resize(1400, 1800)                             # dwa razy wyższe okno…
        qapp.processEvents()
        assert tasks.height() == oczekiwana                # …lista tej samej wysokości
    finally:
        win.close()


def test_klik_duplikaty_otwiera_zbiory_z_perspektywa(qapp, tmp_path):
    """Zadanie „Duplikaty" → Zbiory z USTAWIONĄ perspektywą (flaga `only_dups`, NIE drzewo filtra —
    R#14); nazwa presetu przez stałą PRESET_DUPS (F5R#11)."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "dup_frames"))
        assert win.stack.currentIndex() == STRONA_ZBIORY
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
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (7)"   # wciąż 7 (klatki/tel/dup/zniknięte + bez zestawu/stanowiska + nazwa M42)
    finally:
        win.close()


def test_koniec_przebiegu_odswieza_liczniki_zadan(qapp, tmp_path):
    """Koniec przebiegu Dostawy (`running_changed(False)`) przeładowuje też liczniki zadań - badge
    maleje, gdy stan się poprawił (tu: wszystkie teleskopy nazwane poza GUI). Bez żadnego
    `stage_finished` po drodze: tak kończy się przebieg, którego jedyny etap padł błędem, a zapis
    sprzed błędu i tak musi dojść do ekranu."""
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win._on_pipeline_running(True)
        for row in win.con.execute("SELECT id FROM telescope WHERE merged_into IS NULL").fetchall():
            repo.label_telescope(win.con, telescope_id=row[0], label=f"T{row[0]}", now=NOW)
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (7)", "w biegu - jeszcze stary stan"
        win._on_pipeline_running(False)
        assert _task_row(win, "telescopes_unlabeled") == ("Teleskopy bez etykiety", "0  ›")
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (6)"   # klatki + duplikaty + zniknięte + bez zestawu/stanowiska + nazwa M42
    finally:
        win.close()


def _licz_przeladowania(win, monkeypatch):
    """Licznik wywołań `_load_facets` obu widoków, które je mają (grid, oś obiektu) - to one
    kosztowały po etapie najwięcej (8,4 s z 11,7 s na kopii żywej bazy)."""
    licznik = {"grid": 0, "obiekt": 0}
    for klucz, widok in (("grid", win.grid_view), ("obiekt", win.object_view)):
        oryginal = widok._load_facets

        def _licz(_k=klucz, _o=oryginal):
            licznik[_k] += 1
            _o()
        monkeypatch.setattr(widok, "_load_facets", _licz)
    return licznik


def _zapis_paska(win):
    """Historia raportów postawionych na etykiecie paska (pełna treść, przed elizją) - lista, która
    rośnie z każdym `_wyswietl`. Raport ma własną etykietę (AR-76), więc `messageChanged`
    `QStatusBar` już o nim nie mówi."""
    pasek, wyswietl = [], win._wyswietl
    win._wyswietl = lambda msg: (pasek.append(msg), wyswietl(msg))[1]
    return pasek


def _przebieg_w_watku(win, start):
    """Puść przebieg Dostawy w PRAWDZIWYM wątku i odczekaj jego koniec. Pętla kończy się na
    `running_changed(False)`, a slot okna jest podpięty PRZED naszym, więc odświeżenie widoków
    zdążyło się wykonać, zanim wracamy do asercji."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    win.pipeline_view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(60000, loop.quit)                # bezpiecznik, gdyby coś zawisło
    start()
    assert win.pipeline_view._thread is not None, "przebieg ruszył w wątku"
    loop.exec()
    assert win.pipeline_view._thread is None, "przebieg się skończył (nie bezpiecznik)"


def test_przebieg_Dostawy_przeladowuje_widoki_RAZ_nie_raz_na_etap(qapp, tmp_path, monkeypatch):
    """„Przetwórz wszystko" to łańcuch kilku etapów w jednym wątku. Przeładowanie widoków szło po
    KAŻDYM etapie: zmierzone na kopii żywej bazy 11,7 s na etap (8,4 s samo `_load_facets` gridu),
    ~88 s nieruchomego okna na przebieg, a `processEvents` fazy doręczał w środku odświeżenia
    koniec kolejnego etapu, więc odświeżenia zagnieżdżały się w odwróconej kolejności.

    Pomiar przed/po w jednym teście: liczba `stage_finished` przebiegu to liczba przeładowań
    SPRZED naprawy (po jednym na sygnał); po naprawie przeładowanie jest jedno. Stan końcowy
    widoków ma odpowiadać bazie - nic się nie zgubiło po drodze.

    Falsyfikator: podepnij z powrotem `stage_finished` pod przeładowanie widoków → licznik
    przeładowań równa się liczbie etapów."""
    from test_copy_facts import _fits
    root = tmp_path / "ARCH"
    _fits(root / "Ha" / "a.fits", "Ha", n=1)
    _fits(root / "OIII" / "b.fits", "OIII", n=2)
    path = str(tmp_path / "p.db")
    db.open_db(path).close()
    win = MainWindow(path)
    try:
        assert win.grid_view.count_label.text() == "0 klatek"
        licznik = _licz_przeladowania(win, monkeypatch)
        etapy = []
        win.pipeline_view.stage_finished.connect(etapy.append)
        win.pipeline_view._set_root(str(root))
        _przebieg_w_watku(win, win.pipeline_view._on_all)

        assert len(etapy) >= 5, f"łańcuch ma kilka etapów: {etapy}"
        assert etapy[:2] == ["scan", "group"], "etapy kończą się w kolejności łańcucha"
        assert licznik == {"grid": 1, "obiekt": 1}, \
            f"przeładowanie RAZ na przebieg (przed naprawą: {len(etapy)} na widok)"
        assert win.grid_view.count_label.text() == "2 klatki", "widoki pokazują stan bazy"
        assert not win.phase_label.text(), "faza zgasła po odświeżeniu"
    finally:
        win.close()


def test_przebieg_zakonczony_bledem_tez_odswieza_widoki(qapp, tmp_path, monkeypatch):
    """Błąd etapu nie emituje `stage_finished` - a zapisy sprzed błędu (w łańcuchu: etapy przed
    nim) są w bazie. Koniec przebiegu przychodzi w tej drodze tak samo (`_cleanup_thread`), więc
    widoki i plakietka liczą się ze stanu także tu."""
    from horreum import grouper
    from horreum.gui import i18n

    def _pada(con, now):
        raise RuntimeError("etap padł")
    monkeypatch.setattr(grouper, "run_grouper", _pada)   # rdzeń woła przez moduł (`derive`)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        licznik = _licz_przeladowania(win, monkeypatch)
        for row in win.con.execute("SELECT id FROM telescope WHERE merged_into IS NULL").fetchall():
            repo.label_telescope(win.con, telescope_id=row[0], label=f"T{row[0]}", now=NOW)
        etapy = []
        win.pipeline_view.stage_finished.connect(etapy.append)
        _przebieg_w_watku(win, lambda: win.pipeline_view.run_stage("group"))
        assert etapy == [], "etap padł - bez sygnału końca etapu"
        # błąd programu jednym zdaniem w języku UI, surowy tekst wyjątku w szczególe (AR-264)
        assert i18n.t("objchg.item.prog_error").split(" - ")[0] in win.pipeline_view.lbl_error.text()
        assert "etap padł" in win.pipeline_view.lbl_error.toolTip()
        assert licznik == {"grid": 1, "obiekt": 1}
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (6)", "plakietka ze stanu bazy"
    finally:
        win.close()


def test_sonda_katalogu_nie_odswieza_ani_nie_wygasza_widokow(qapp, tmp_path, monkeypatch,
                                                            ustawienia):
    """Z13: „Wskaż katalog…" puszcza sondę serialu w wątku tła - etap bez połączenia z bazą. Gospodarz
    nie wygasza w jej trakcie widoków innych stron i po niej NIE odświeża read-modeli (na kopii
    żywej bazy okno stało 751-860 ms po każdym wyborze katalogu). Zwykły przebieg w tym samym oknie
    dalej robi jedno i drugie - prawdziwe wątki, bez wołania slotu wprost.

    Falsyfikator: zdejmij warunek `self._bieg_pisze` z `PipelineView._set_running` → pierwsza
    połowa widzi odświeżenie i `set_busy(True)` gridu."""
    import time
    from PySide6.QtWidgets import QFileDialog
    kat = tmp_path / "zrodlo"
    kat.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(kat)))
    win = MainWindow(_seeded_db(tmp_path))
    try:
        odswiezenia, zajetosc = [], []
        oryginal = win._odswiez_widoki_po_przebiegu
        monkeypatch.setattr(win, "_odswiez_widoki_po_przebiegu",
                            lambda: (odswiezenia.append(1), oryginal()))
        for nazwa, widok in (("grid", win.grid_view), ("obiekt", win.object_view),
                             ("planer", win.planner_view)):
            org = widok.set_busy
            monkeypatch.setattr(widok, "set_busy",
                                lambda b, _n=nazwa, _o=org: (zajetosc.append((_n, b)), _o(b)))
        pv = win.pipeline_view
        pv._on_pick_dir()
        assert pv._thread is not None, "sonda ruszyła w wątku tła"
        for _ in range(2000):                          # koniec sondy: `_cleanup_thread`
            QApplication.processEvents()
            if pv._thread is None:
                break
            time.sleep(0.01)
        assert pv._thread is None and pv._root == str(kat)
        assert odswiezenia == [] and zajetosc == [], (odswiezenia, zajetosc)

        _przebieg_w_watku(win, lambda: pv.run_stage("group"))
        assert odswiezenia == [1], "zwykły przebieg dalej odświeża widoki raz"
        # Oś obiektu zwalnia się po odświeżeniu widoków (AR-296: recepta odłożona przez etap stoi ostatnia).
        assert ("grid", True) in zajetosc and zajetosc[-2:] == [("planer", False), ("obiekt", False)], zajetosc
    finally:
        win.close()


def test_wyjatek_w_odswiezeniu_po_przebiegu_gasi_faze(qapp, tmp_path, monkeypatch):
    """Faza „Odświeżam widoki po etapie…" gaśnie KAŻDĄ drogą: wyjątek w odświeżeniu któregoś
    widoku zostawiał ją na pasku, czyli opis roboty, która już się skończyła - do następnej fazy.
    Straż ponownego wejścia też wraca do spoczynku, inaczej kolejny przebieg nie odświeżyłby nic.

    Falsyfikator: wynieś `_end_phase()` z `finally` → asercja o etykiecie fazy pada."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        def _pada(**_kw):                              # `w_tle` - gospodarz zleca skład w tle (AR-27)
            raise RuntimeError("odświeżenie padło")
        monkeypatch.setattr(win.grid_view, "refresh", _pada)
        with pytest.raises(RuntimeError, match="odświeżenie padło"):
            win._odswiez_widoki_po_przebiegu()
        assert not win.phase_label.text(), win.phase_label.text()
        assert win._odswiezam_widoki is False
    finally:
        win.close()


def test_wyjatek_w_odswiezeniu_po_przebiegu_zwalnia_os_obiektu(qapp, tmp_path, monkeypatch):
    """Oś obiektu zwalnia się po odświeżeniu widoków (AR-296), ale KAŻDĄ drogą: wyjątek odświeżenia nie zostawia
    „Przypisz obiekt…” i „Napraw nagłówek…” wygaszonych do następnego przebiegu.

    Falsyfikator: `object_view.set_busy(False)` za odświeżeniem bez `finally` → oś zostaje zajęta."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win._on_pipeline_running(True)
        assert win.object_view._busy is True

        def _pada(**_kw):
            raise RuntimeError("odświeżenie padło")
        monkeypatch.setattr(win.grid_view, "refresh", _pada)
        with pytest.raises(RuntimeError, match="odświeżenie padło"):
            win._on_pipeline_running(False)
        assert win.object_view._busy is False
    finally:
        win.close()


def test_odswiezenie_po_przebiegu_nie_zagniezdza_sie(qapp, tmp_path, monkeypatch):
    """STRAŻ PONOWNEGO WEJŚCIA. Druga prośba o odświeżenie, doręczona W ŚRODKU pierwszego (tak
    doręczał je `processEvents` fazy), nie zagnieżdża się: pierwszy obrót kończy się w całości,
    a druga prośba daje jeden pełny obrót PO nim - ostatni odczyt jest nowszy niż ostatnia prośba.

    Falsyfikator: zdejmij strażnika → wejścia w `grid.refresh` zagnieżdżają się (głębokość 2)."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        grid = win.grid_view
        oryginal = grid.refresh
        stan = {"glebokosc": 0, "max": 0, "wejscia": 0}

        def _refresh(**kw):
            stan["glebokosc"] += 1
            stan["wejscia"] += 1
            stan["max"] = max(stan["max"], stan["glebokosc"])
            if stan["wejscia"] == 1:
                win._on_pipeline_running(False)        # prośba doręczona w środku odświeżenia
            oryginal(**kw)
            stan["glebokosc"] -= 1
        monkeypatch.setattr(grid, "refresh", _refresh)
        win._on_pipeline_running(False)
        assert stan["max"] == 1, "odświeżenia nie zagnieżdżają się"
        assert stan["wejscia"] == 2, "prośba z środka dała jeden obrót więcej, po bieżącym"
        assert win._odswiezam_widoki is False and not win.phase_label.text()
    finally:
        win.close()


def test_koniec_przebiegu_w_srodku_odswiezenia_zwalnia_os_obiektu_po_ostatnim_obrocie(qapp, tmp_path, monkeypatch):
    """AR-296: koniec przebiegu doręczony W ŚRODKU odświeżenia (nowy krótki przebieg pod `processEvents` fazy)
    zamawia kolejny obrót, ale osi obiektu NIE zwalnia - zwolnienie (które podaje receptę cofnięcia odłożoną
    przez etap) przychodzi raz, po ostatnim obrocie; inaczej raporty osi z drugiego obrotu gasiłyby receptę.

    Falsyfikator: `object_view.set_busy(False)` w `finally` bez warunku końca odświeżeń."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        grid = win.grid_view
        oryginal = grid.refresh
        zdarzenia = []
        prawdziwe = win.object_view.set_busy
        monkeypatch.setattr(win.object_view, "set_busy",
                            lambda b: (zdarzenia.append(("os", b)), prawdziwe(b)))

        def _refresh(**kw):
            zdarzenia.append(("obrot", None))
            if zdarzenia.count(("obrot", None)) == 1:
                win._on_pipeline_running(True)          # nowy krótki przebieg rusza i kończy się
                win._on_pipeline_running(False)         # w środku pierwszego obrotu
            oryginal(**kw)
        monkeypatch.setattr(grid, "refresh", _refresh)
        win._on_pipeline_running(True)
        zdarzenia.clear()
        win._on_pipeline_running(False)
        assert zdarzenia.count(("obrot", None)) == 2, zdarzenia
        assert [z for z in zdarzenia if z == ("os", False)] == [("os", False)], zdarzenia
        assert zdarzenia[-1] == ("os", False), zdarzenia
        assert win.object_view._busy is False
    finally:
        win.close()


def test_gest_osi_zywotnosci_w_Zbiorach_odswieza_plakietke_Porzadkow(qapp, tmp_path):
    """Plakietka nawigacji „Porządki (N)" jest stanem widocznym BEZ klikania, więc ma iść za gestem,
    który zmienił jej populację - także za gestem osi żywotności klatki. Zmierzone na realnym oknie:
    po „Przywróć" plakietka zostawała przy starej liczbie i poprawiała się dopiero po wejściu
    w Porządki, bo odświeżenie wisiało wyłącznie na sygnale osi OBIEKTU.

    Stan drogą programu, przed otwarciem okna: jedyna kopia `present0` zniknęła (fikstura), ręka
    wycofuje klatkę, a re-skan znajduje plik pod nową ścieżką - wiersz akcyjny „Wycofane, a plik
    wrócił" liczy 1. Gest „Przywróć" z Zbiorów zamyka go; plakietka ma spaść o jeden, choć
    Porządków nikt nie otworzył.

    Falsyfikator: zdejmij emisję `stan_porzadkow_changed` z `_po_gescie_klatki` - plakietka
    zostaje przy (4)."""
    from horreum.gui import grid as grid_mod
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    (fid,) = queries.vanished_frame_ids(con)
    assert repo.retire_frames(con, frame_ids=[fid], now=NOW).done == 1
    repo.add_location(con, frame_id=fid, volume="vol3", path="/astro/wrocil/present0.fits", now=NOW)
    con.close()

    win = MainWindow(path)
    try:
        # klatki bez obiektu + teleskopy + duplikaty + „a plik wrócił" + bez zestawu i bez stanowiska
        # + nazwa katalogowa M42 (AR-135; zniknięte spadły do 0)
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (7)"
        win._show_view(NAV_ZBIORY)
        grid = win.grid_view
        grid.apply_perspective(grid_mod.PRESET_RETIRED_CONFLICT)
        assert grid._frame_ids == [fid]
        grid.table.selectRow(0)
        grid._on_frame_restore()

        assert win.con.execute("SELECT retired_at FROM frame WHERE id = ?",
                               (fid,)).fetchone()[0] is None, "gest się odbył"
        assert win.stack.currentIndex() == STRONA_ZBIORY, "Porządków nikt nie otworzył"
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (6)"
    finally:
        win.close()


def test_gest_osi_obiektu_odswieza_plakietke_JEDEN_raz(qapp, tmp_path):
    """Druga strona tej samej zmiany: plakietka wisi teraz na JEDNYM sygnale stanu Porządków,
    a gest osi obiektu emituje oba swoje sygnały (kolejka przeglądu osi + stan Porządków).
    Gdyby stare podpięcie pod `object_axis_changed` zostało obok nowego, każdy gest osi obiektu
    liczyłby `tasks_state` dwa razy - pełny koszt zapytań za nic. Liczymy emisje `counts_changed`,
    czyli wykonania `refresh_counts`."""
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    # cel gestu: light z obiektem nadanym RĘKĄ - „Cofnij przypisanie" zdejmuje tylko rękę i ścieżkę
    fid = con.execute(
        "SELECT id FROM frame WHERE object_id IS NULL AND kind IN ('light', 'master_light') "
        "ORDER BY id LIMIT 1").fetchone()[0]
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[fid], now=NOW)
    con.close()
    win = MainWindow(path)
    try:
        win._show_view(NAV_ZBIORY)
        grid = win.grid_view
        grid.refresh()
        wiersz = next(i for i, r in enumerate(grid.model._rows)
                      if isinstance(r, dict) and r.get("frame_id") == fid)
        grid.table.selectRow(wiersz)
        odswiezenia = []
        win.tasks_view.counts_changed.connect(odswiezenia.append)
        grid._on_object_clear()
        assert win.con.execute("SELECT object_id FROM frame WHERE id = ?",
                               (fid,)).fetchone()[0] is None, "gest się odbył"
        assert len(odswiezenia) == 1, f"plakietka liczona {len(odswiezenia)} razy"
    finally:
        win.close()


def test_gest_osi_przy_niewidocznej_osi_obiektu_przeladowuje_ja_przy_pokazaniu(qapp, tmp_path,
                                                                              monkeypatch):
    """AR-84: gest osi obiektu pada w Zbiorach, a kolejka przeglądu osi obiektu (~0,4 s na wątku GUI
    na kopii pf4) jest wtedy niewidoczna - przy geście się NIE przeładowuje, dostaje znacznik.
    Pokazanie podstrony (tu: wiersz zadania Porządków) przeładowuje ją RAZ, a kolejka jest ta
    sama, co w widoku zbudowanym od nowa na bazie po geście. Ponowne wejście bez nowego gestu
    już nie liczy.

    Falsyfikator: podepnij `grid.object_axis_changed` wprost pod `object_view.refresh` → przy
    geście jedno przeładowanie; zdejmij `showEvent` → po wejściu kolejka sprzed gestu."""
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    # cel: klatka grupy przeglądu (ma `object_raw`), nadana ręką - po cofnięciu wraca do kolejki
    raw = queries.review_queue(con)["object_review"][0]["object_raw"]
    fid = queries.object_review_frames(con, raw)[0]["frame_id"]
    repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                            kind="deep_sky", frame_ids=[fid], now=NOW)
    con.close()
    win = _pokazane(MainWindow(path))
    try:
        win._show_view(NAV_ZBIORY)
        grid, v = win.grid_view, win.object_view
        grid.refresh()
        wiersz = next(i for i, r in enumerate(grid.model._rows)
                      if isinstance(r, dict) and r.get("frame_id") == fid)
        grid.table.selectRow(wiersz)

        def _kolejka(widok):                          # nazwa i liczba (człon drugi) każdej pozycji
            from horreum.gui import rows
            return [(widok.review.item(i).text(), widok.review.item(i).data(rows.SECONDARY))
                    for i in range(widok.review.count())]
        przed = _kolejka(v)
        odswiezenia = []
        oryginal = ObjectAxisView.refresh
        monkeypatch.setattr(ObjectAxisView, "refresh",
                            lambda self, **kw: odswiezenia.append(1) or oryginal(self, **kw))
        grid._on_object_clear()
        assert win.con.execute("SELECT object_source FROM frame WHERE id = ?",
                               (fid,)).fetchone()[0] == "user_cleared", "gest się odbył"
        assert odswiezenia == [] and v._nieaktualny, "niewidoczna oś nie liczy się przy geście"
        win._show_view(NAV_PORZADKI)
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "unresolved_lights"))
        QApplication.processEvents()
        assert v.isVisible() and odswiezenia == [1], odswiezenia
        assert not v._nieaktualny
        win.tasks_view._on_back()
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "unresolved_lights"))
        QApplication.processEvents()
        assert odswiezenia == [1], "wejście bez nowego gestu nie przeładowuje"
        swiezy = ObjectAxisView(win.con)
        try:
            assert _kolejka(v) == _kolejka(swiezy) != przed, "kolejka po wejściu = stan po geście"
        finally:
            swiezy.deleteLater()
        # Droga z KUBEŁKIEM sama przeładowuje kolejkę (`_zaznacz_kubelek`) - pokazanie po obrocie
        # pętli widzi zdjęty znacznik i nie liczy drugi raz tego samego stanu.
        win.tasks_view._on_back()
        win._show_view(NAV_ZBIORY)
        grid.refresh()
        grid._przywroc_zaznaczenie([fid])
        grid._on_object_restore()
        assert v._nieaktualny
        przed_kubelkiem = len(odswiezenia)
        win._show_view(NAV_PORZADKI)
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "config_review_frames"))
        QApplication.processEvents()
        assert len(odswiezenia) == przed_kubelkiem + 1, odswiezenia
    finally:
        win.close()


def test_wejscie_w_Porzadki_bez_zmiany_bazy_nie_liczy_licznikow(qapp, tmp_path, monkeypatch):
    """AR-84: wejście w Porządki liczyło liczniki synchronicznie (0,7-1,9 s na kopii pf4), choć tło
    po geście już je przeliczyło. Odcisk bazy (`queries.odcisk_bazy`) bez zmiany od ostatniego
    przyłożonego rachunku = lista bez rachunku; zapis z DRUGIEGO połączenia (jak worker Dostawy)
    zmienia odcisk i wejście liczy od nowa - prawda na wejściu.

    Falsyfikator: `_on_nav_changed` woła `refresh_counts()` wprost → rachunek przy każdym wejściu."""
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    try:
        rachunki = []
        prawdziwe = queries.tasks_state
        monkeypatch.setattr(queries, "tasks_state", lambda c: rachunki.append(1) or prawdziwe(c))
        przed = _task_row(win, "unresolved_lights")
        win._show_view(NAV_PORZADKI)
        assert rachunki == [], "baza bez zmian od montażu - bez rachunku"
        win._show_view(NAV_DOM)
        con = db.connect(path)
        try:
            fid = con.execute(
                "SELECT id FROM frame WHERE object_id IS NULL AND kind = 'light' ORDER BY id LIMIT 1"
            ).fetchone()[0]
            repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                                    kind="deep_sky", frame_ids=[fid], now=NOW)
        finally:
            con.close()
        win._show_view(NAV_PORZADKI)
        assert rachunki == [1], "zapis drugiego połączenia - wejście liczy od nowa"
        assert _task_row(win, "unresolved_lights") != przed, "lista mówi o stanie po zapisie"
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
        assert win.stack.currentIndex() == STRONA_ZBIORY
        assert win.grid_view._only_vanished is True
        assert win.grid_view.combo_persp.currentText() == PRESET_VANISHED
        widoczne = set(win.grid_view._frame_ids)               # to, co WIDAĆ po trimie perspektywy
        assert widoczne == queries.vanished_frame_ids(win.con) and len(widoczne) == 1
    finally:
        win.close()


def test_zadanie_rodowodu_otwiera_perspektywe(qapp, tmp_path):
    """0808: klik w „Rodowód do potwierdzenia" prowadzi do Zbiorów z perspektywą `PRESET_LINEAGE`,
    a grid pokazuje DOKŁADNIE obrazy czekające na gest. Wiersz celuje w perspektywę, nie
    w podstronę, bo gest (potwierdź / odrzuć wejście / wskaż odniesienie) mieszka w panelu
    „Rodowód" TAM - i do tej zmiany dojście do niego wiodło przez przeklikanie archiwum stosów.
    Wiersz i perspektywa mówią JEDNĄ nazwą (dawniej wiersz „Obrazy bez rodowodu").

    AR-219: prawdziwy klik wiersza stawia gest od razu - pierwszy obraz w zaznaczeniu, panel
    „Rodowód” otwarty na nim, bez recepty gestu zbiorczego (ten mieszka tylko w perspektywie
    nowszych). Falsyfikator: `_po_perspektywie` bez wejścia w kolejkę dla tej perspektywy."""
    import time
    from PySide6.QtTest import QTest
    from horreum.gui import i18n
    from horreum.gui.grid import PRESET_LINEAGE
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    try:
        fid = con.execute("SELECT id FROM frame ORDER BY id LIMIT 1").fetchone()[0]
        # Powód z WŁASNĄ receptą (karta teleskopu) - czeka na gest bez materiału; powód okna bez
        # materiału w propozycji z kubełka wypada (AR-154).
        con.execute("INSERT INTO integration (master_frame_id, created_at, unresolved_reason) "
                    "VALUES (?, '2026-08-08T20:00:00', 'telescope_mismatch')", (fid,))
        # Gotowy obraz - panel „Rodowód” mówi o stosie tylko przy `master_light` (AR-219).
        con.execute("UPDATE frame SET kind = 'master_light' WHERE id = ?", (fid,))
        con.commit()
    finally:
        con.close()
    win = MainWindow(path)
    try:
        win.show()
        win._show_view(NAV_PORZADKI)
        assert _task_row(win, "stacks_lineage_pending")[0] == "Rodowód do potwierdzenia"
        recepty = []
        win.grid_view.status_recipe.connect(recepty.append)
        lista = win.tasks_view.tasks
        wiersz = lista.visualItemRect(_task_item(win, "stacks_lineage_pending"))
        QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, wiersz.center())
        v = win.grid_view
        koniec = time.monotonic() + 30
        while v._zbior_w_drodze() and time.monotonic() < koniec:
            QApplication.processEvents()
            time.sleep(0.01)
        assert not v._zbior_w_drodze(), "zbiór perspektywy nie dojechał"
        assert win.stack.currentIndex() == STRONA_ZBIORY
        assert v._only_lineage is True
        assert v.combo_persp.currentData() == ("preset", PRESET_LINEAGE)
        assert v.combo_persp.currentText() == "Rodowód do potwierdzenia"
        widoczne = set(v._frame_ids)                      # to, co WIDAĆ po trimie perspektywy
        assert widoczne == queries.lineage_pending_frame_ids(win.con) == {fid}
        assert [r["frame_id"] for r in v._selected_data_rows()] == [fid]
        assert v._lineage_panel_open() and v._lineage_frame_id == fid
        zbiorczy = i18n.t("grid.lin.reject_newer_all")
        assert not any(zbiorczy in str(r) for r in recepty), recepty
    finally:
        win.close()


def test_wejscie_w_Klatki_bez_obiektu_zaznacza_pierwszy_niepusty_kubelek(qapp, tmp_path):
    """Porządki → „Klatki bez obiektu": podstrona zaznaczała pierwszy obiekt BIBLIOTEKI (na żywej
    kopii kometę z 4 klatkami), a do klatek z kolejki trzeba było kliknąć wiersz kolejki - trzy
    interakcje zamiast dwóch. Wejście zaznacza pierwszy niepusty kubełek osi obiektu (wzór
    `tasks._KUBELEK_PODSTRONY`): lista klatek kubełka i gest stoją od razu, biblioteka bez wyboru.

    Falsyfikator: zdejmij gałąź `unresolved_lights` z `TasksView._on_task_clicked` → zaznaczony
    zostaje wiersz biblioteki, a kolejka stoi bez wyboru."""
    from horreum.gui.app import _REVIEW_TAG
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    try:
        win._show_view(NAV_PORZADKI)
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "unresolved_lights"))
        QApplication.processEvents()
        v = win.object_view
        lista = v.review
        tagi = [lista.item(i).data(_REVIEW_TAG) for i in range(lista.count())]
        pierwszy = next(i for i, t in enumerate(tagi) if t in ObjectAxisView.KUBELKI_OSI_OBIEKTU)
        assert lista.currentRow() == pierwszy and lista.item(pierwszy).isSelected(), tagi
        assert not v.objects.selectionModel().selectedRows(), "biblioteka dalej trzyma obiekt"
        assert v.frames.rowCount() > 0, "kubełek zaznaczony, a klatki nie przyszły"
        # Kubełki innych osi (kopie nieczytelne, zestaw) nie są celem tego wiersza.
        assert not ({"unreadable", "config_review", "config_focal"}
                    & ObjectAxisView.KUBELKI_OSI_OBIEKTU)
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
        assert win.stack.currentIndex() == STRONA_DOM      # okno zostało na stronie startu
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
    from horreum.gui.grid import PRESET_VANISHED, _EMPTY_DB, _EMPTY_PERSP
    from horreum.gui import i18n                          # _EMPTY_* to KLUCZE (rollout i18n) — rozwiąż t()
    win = MainWindow(_seeded_db(tmp_path))               # bez object_axis → zero present=0
    try:
        win._show_view(NAV_ZBIORY)
        wszystkie = len(win.grid_view._frame_ids)
        assert wszystkie > 1
        win.grid_view.apply_perspective(PRESET_VANISHED)
        assert win.grid_view._frame_ids == []            # pusto — i to jest PRAWDA o tej bazie
        assert win.grid_view.empty.text() == i18n.t(_EMPTY_PERSP)   # FH-4: zbiór przycina TRIM
        assert win.grid_view.empty.text() != i18n.t(_EMPTY_DB)   # baza ma klatki; grid nie kłamie
        win.grid_view.apply_perspective("Przegląd")
        assert len(win.grid_view._frame_ids) == wszystkie
    finally:
        win.close()


# ═════════════════════════ P-K / F-1 — OKNO NIE MILCZY PRZY DŁUGIEJ ROBOCIE


def test_faza_startu_MA_WLASNY_KANAL_a_nie_pasek_raportow(qapp, tmp_path):
    """F-1: opis roboty i raport nie mogą dzielić jednego miejsca.

    `statusBar().showMessage` ma jedno pole, więc faza „Odświeżam widoki po etapie…" wypychałaby
    z niego raport, który właśnie padł („Etap Rozwiąż zakończony") — a to raport jest tym, po co
    user czekał. Stąd `phase_label` jako STAŁY widżet paska: dwa kanały, zero kolizji.

    Falsyfikator: zawróć `_say_phase` na etykietę raportu → raport zniknie pod fazą."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win._say_phase("Czytam bazę…")
        assert win.phase_label.text() == "Czytam bazę…"
        assert win.report_label.text() != "Czytam bazę…"   # raport ma własne pole

        win._flash("Etap Rozwiąż zakończony")
        win._say_phase("Odświeżam widoki po etapie…")
        assert win.report_label.text() == "Etap Rozwiąż zakończony"   # faza go NIE zjadła
    finally:
        win.close()


def test_faza_GASNIE_po_zakonczeniu_roboty(qapp, tmp_path):
    """F-1: opis operacji, która się skończyła, jest kłamstwem — pasek nie ma prawa go trzymać.
    `_end_phase` gasi etykietę i przywraca środek okna do zdania o STANIE."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win._say_phase("Buduję widoki…")
        assert win.phase_label.text()
        win._end_phase()
        assert win.phase_label.text() == ""
    finally:
        win.close()


def test_otwarcie_bazy_NAZYWA_FAZY_po_kolei(qapp, tmp_path):
    """F-1, sedno żądania Zdzinia („czytam bazę / czytam nagłówki"): najdłuższa operacja aplikacji
    ma mówić, CO ROBI, i to czasownikiem — zmierzone **4 649 ms** na żywej `pf4` (otwarcie bazy
    + montaż czterech widoków), przez które do tej zmiany na ekranie nie było niczego.

    Bramka zbiera KOLEJNOŚĆ faz, bo jedna faza na całość byłaby tym samym co żadna: user ma
    widzieć, że robota POSTĘPUJE, a nie że stoi na jednym zdaniu."""
    win = MainWindow()
    fazy = []
    try:
        oryginal = win._say_phase
        win._say_phase = lambda t: (fazy.append(t), oryginal(t))[1]
        win.open_path(_seeded_db(tmp_path))
        assert len(fazy) >= 2, f"start ma nazwać co najmniej dwie fazy, było: {fazy}"
        assert any("Otwieram bazę" in f for f in fazy), fazy
        assert any("Buduję widoki" in f for f in fazy), fazy
        assert win.phase_label.text() == ""              # …i po wszystkim gaśnie
        assert win.con is not None                       # baza realnie otwarta
    finally:
        win.close()


def _nowsza_baza(tmp_path):
    """Baza s8 z numerem schematu o jeden WYŻSZYM niż zna ten kod (AR-69)."""
    path = _seeded_db(tmp_path, name="nowsza.db")
    con = db.connect(path)
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    con.close()
    return path


def test_baza_z_nowszego_horreum_okno_odmawia_i_zostaje_przy_swojej(qapp, tmp_path, monkeypatch):
    """AR-69: „Otwórz bazę…” na bazie z nowszego Horreum mówi odmowę oknem komunikatu, a okno
    zostaje przy bazie, którą miało - dotąd wyjątek ginął w slocie menu (w wydaniu bez konsoli:
    nic na ekranie), a otwarty uchwyt trzymał plik. Nowsza ścieżka NIE zostaje zapamiętana jako
    ostatnia baza, faza otwierania gaśnie."""
    from PySide6.QtWidgets import QMessageBox

    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    zapamietane = []
    win = MainWindow(on_db_changed=zapamietane.append)
    try:
        swoja = _seeded_db(tmp_path)
        win.open_path(swoja)
        con = win.con
        nowsza = _nowsza_baza(tmp_path)
        win.open_path(nowsza)
        (zdanie,) = ostrzezenia
        assert "nowsza.db" in zdanie and f"v{db.SCHEMA_VERSION + 1}" in zdanie
        assert f"v{db.SCHEMA_VERSION}" in zdanie and "nietknięta" in zdanie
        assert win.con is con and win.db_path == swoja and zapamietane == [swoja]
        assert win.con.execute("SELECT count(*) FROM frame").fetchone()[0] > 0
        assert win.phase_label.text() == ""
    finally:
        win.close()


@pytest.mark.zmienia_motyw          # `main()` stawia motyw na aplikacji - część startu, którą test przechodzi
def test_start_z_zapamietana_nowsza_baza_stoi_bez_bazy(qapp, tmp_path, monkeypatch):
    """AR-69, ścieżka startu: `main` otwiera zapamiętaną bazę przed `app.exec()`, więc odmowa
    jako wyjątek wywracała program przy KAŻDYM uruchomieniu, zanim cokolwiek pokazał. Teraz okno
    stoi bez bazy, z pustym stanem „Brak bazy”, a odmowa padła oknem komunikatu."""
    from PySide6.QtWidgets import QMessageBox
    from horreum.gui import app as app_mod, i18n

    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    okna = []
    prawdziwy_show = app_mod.MainWindow.show

    def _show(self):
        okna.append(self)
        return prawdziwy_show(self)

    monkeypatch.setattr(app_mod.MainWindow, "show", _show)
    monkeypatch.setattr(app_mod.QApplication, "exec", lambda self: 0)
    try:
        assert app_mod.main([_nowsza_baza(tmp_path)]) == 0
        (win,) = okna
        assert len(ostrzezenia) == 1
        assert win.con is None and win.empty_note.text() == i18n.t("main.no_db")
    finally:
        for w in okna:
            w.close()


def _zepsute_bazy(tmp_path):
    """Trzy pliki, których `open_db` nie otworzy, każdy innym wyjątkiem (AR-124): śmieci
    (`DatabaseError`), baza sprzed przejścia fitsmirror (`RuntimeError`), katalog
    (`OperationalError`)."""
    import sqlite3

    smieci = tmp_path / "smieci.db"
    smieci.write_bytes(b"to nie jest baza Horreum" * 200)
    stara = tmp_path / "stara.db"
    con = sqlite3.connect(stara)
    con.execute("CREATE TABLE x (a)")
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    katalog = tmp_path / "katalog.db"
    katalog.mkdir()
    return [str(smieci), str(stara), str(katalog)]


def test_kazdy_blad_otwarcia_bazy_okno_komunikatu_i_zostaje_przy_swojej(qapp, tmp_path,
                                                                        monkeypatch):
    """AR-124: dotąd okno łapało wyłącznie odmowę bazy z nowszego Horreum, a każdy inny błąd
    otwarcia ginął w slocie menu (w wydaniu bez konsoli: nic na ekranie). Teraz jedno okno
    komunikatu z nazwą pliku i powodem; okno zostaje przy swojej bazie, ścieżka nie zostaje
    zapamiętana, faza gaśnie, plik da się przenieść zaraz po odmowie.
    Falsyfikator: zdejmij klauzulę `except Exception` z `_open_path` → wyjątek z `open_path`."""
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    zapamietane = []
    win = MainWindow(on_db_changed=zapamietane.append)
    try:
        swoja = _seeded_db(tmp_path)
        win.open_path(swoja)
        con = win.con
        for zepsuta in _zepsute_bazy(tmp_path):
            win.open_path(zepsuta)
            zdanie = ostrzezenia.pop()
            assert Path(zepsuta).name in zdanie and "Nie udało się otworzyć" in zdanie
            assert "Powód: " in zdanie and "Powód: \n" not in zdanie
            assert win.con is con and win.db_path == swoja and zapamietane == [swoja]
            assert win.phase_label.text() == ""
            Path(zepsuta).rename(zepsuta + ".przeniesiona")
        assert ostrzezenia == []
        assert win.con.execute("SELECT count(*) FROM frame").fetchone()[0] > 0
    finally:
        win.close()


@pytest.mark.zmienia_motyw          # `main()` stawia motyw na aplikacji
def test_start_z_zepsuta_baza_stoi_bez_bazy(qapp, tmp_path, monkeypatch):
    """AR-124, ścieżka startu: zapamiętany plik, który nie jest bazą, wywracał program przed
    `app.exec()` śladem stosu (w wydaniu onefile - bez okna). Teraz okno stoi bez bazy
    z pustym stanem i jednym oknem komunikatu."""
    from PySide6.QtWidgets import QMessageBox
    from horreum.gui import app as app_mod, i18n

    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    okna = []
    prawdziwy_show = app_mod.MainWindow.show

    def _show(self):
        okna.append(self)
        return prawdziwy_show(self)

    monkeypatch.setattr(app_mod.MainWindow, "show", _show)
    monkeypatch.setattr(app_mod.QApplication, "exec", lambda self: 0)
    try:
        smieci = _zepsute_bazy(tmp_path)[0]
        assert app_mod.main([smieci]) == 0
        (win,) = okna
        (zdanie,) = ostrzezenia
        assert "smieci.db" in zdanie and "Nie udało się otworzyć" in zdanie
        assert win.con is None and win.empty_note.text() == i18n.t("main.no_db")
    finally:
        for w in okna:
            w.close()


@pytest.mark.zmienia_motyw          # `main()` stawia motyw na aplikacji
def test_start_aplikacji_POKAZUJE_OKNO_ZANIM_czyta_baze(qapp, tmp_path, monkeypatch):
    """F-1, cała naprawa siedzi w KOLEJNOŚCI: do tej zmiany `MainWindow(start)` otwierał bazę
    i montował cztery widoki W KONSTRUKTORZE, a `show()` szedł dopiero po nim — 4,65 s czarnego
    ekranu, w wydaniu onefile plus rozpakowanie bootloadera. User pytał wtedy nie „czy trwa",
    tylko „czy ono w ogóle wstało".

    Bramka pilnuje porządku zdarzeń: `show()` MUSI paść przed pierwszym dotknięciem bazy.
    Falsyfikator: wróć do `MainWindow(start)` + `win.show()` → `kolejnosc` zacznie się od 'open'."""
    from horreum.gui import app as app_mod

    kolejnosc = []
    prawdziwy_open = app_mod.MainWindow.open_path
    prawdziwy_show = app_mod.MainWindow.show
    okna = []

    def _open(self, path):
        kolejnosc.append("open")
        return prawdziwy_open(self, path)

    def _show(self):
        kolejnosc.append("show")
        okna.append(self)
        return prawdziwy_show(self)

    monkeypatch.setattr(app_mod.MainWindow, "open_path", _open)
    monkeypatch.setattr(app_mod.MainWindow, "show", _show)
    monkeypatch.setattr(app_mod.QApplication, "exec", lambda self: 0)

    try:
        app_mod.main([_seeded_db(tmp_path)])
        assert kolejnosc == ["show", "open"], f"okno stanęło po odczycie bazy: {kolejnosc}"
    finally:
        for w in okna:
            w.close()


@pytest.mark.skipif(os.name != "nt", reason="rejestr = natywne QSettings tylko na Windows")
@pytest.mark.zmienia_motyw          # `main()` i `_on_theme` stawiają motyw na aplikacji
def test_main_NIE_rusza_rejestru_usera(qapp, tmp_path, monkeypatch, ustawienia, zrzut_rejestru):
    """Bateria pisała do PRAWDZIWYCH ustawień usera: 2026-09-26 `ostatnia_baza` w rejestrze
    wskazywała `...\\pytest-1976\\test_start_aplikacji_POKAZUJE_0\\s8.db`, więc zwykły start
    Horreum otwierał bazę z katalogu pytesta. Izolację trzyma autouse `_izoluj_qsettings`
    (`conftest.py`); ta bramka mierzy JEJ skutek na żywym rejestrze, a nie lekturą kodu.

    Ścieżka: `main()` z bazą (zapis `ostatnia_baza`) + zmiana języka i motywu z menu (zapis
    `ui/lang`, `ui/theme`). Druga połowa dowodu: zapis REALNIE zaszedł - w ustawieniach testu.
    Falsyfikator: zdejmij fixture `_izoluj_qsettings` → zrzut rejestru po ≠ przed."""
    from horreum.gui import app as app_mod, theme

    okna = []
    prawdziwy_show = app_mod.MainWindow.show

    def _show(self):
        okna.append(self)
        return prawdziwy_show(self)

    monkeypatch.setattr(app_mod.MainWindow, "show", _show)
    monkeypatch.setattr(app_mod.QApplication, "exec", lambda self: 0)

    przed = zrzut_rejestru()
    baza = _seeded_db(tmp_path)
    try:
        app_mod.main([baza])
        (win,) = okna
        win._on_lang("en")
        win._on_theme(theme.DEFAULT)
        assert zrzut_rejestru() == przed, "test zapisał do prawdziwych ustawień usera (rejestr)"

        assert ustawienia.value("ostatnia_baza") == baza, "zapis ostatniej bazy w ogóle nie zaszedł"
        assert ustawienia.value("ui/lang") == "en"
        assert not ustawienia.fileName().startswith("\\HKEY_"), ustawienia.fileName()
    finally:
        for w in okna:
            w.close()


# ═════════════════════════ FH-2 — ZDANIE PO GEŚCIE I JEGO NOŚNIK


def _pokazane(win):
    """Okno z REALNĄ geometrią i WYCZERPANĄ kolejką zdarzeń.

    Elizja mierzy się do szerokości paska, a ta przed `show()` jest zastępcza (domyślne 640 px) -
    bramka bez tego mierzyłaby okno, którego nie ma.

    ⚠ DWA OBROTY PĘTLI, NIE JEDEN, i to jest pomiar, nie ostrożność: montaż widoków zostawia
    OPÓŹNIONE komunikaty (planer melduje „baza nie ma stanowiska z pozycją GPS…"), które docierają
    dopiero w drugim obrocie. Pierwsza wersja tych bramek przyjmowała jeden - i pierwszy raport
    testu gasła recepta, którą przed chwilą postawiła, bo cudzy komunikat wchodził w środek.
    Ta sama pułapka przewróciła wcześniej sondę pomiarową na platformie natywnej.

    WSZYSTKIE STRONY ZBUDOWANE (`zbuduj_strony`, AR-325): bramki tego bloku liczą pasek okna, którego minimum
    trzyma strona Zbiorów, a raporty wczytania gridu - z gridem, który istnieje w trakcie przebiegu Dostawy.
    Strony leniwe zdejmowałyby jedno i drugie do pierwszego wejścia w Zbiory."""
    win.zbuduj_strony()
    win.resize(1400, 800)
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    return win


def test_dlugi_raport_dostaje_WIELOKROPEK_i_pelna_tresc_w_podpowiedzi(qapp, tmp_path):
    """FH-2, człon (a). `QStatusBar` przy nadmiarze tnie BEZ znaku i w środku słowa: zmierzone
    zdanie po geście osi miało 252 znaki = 1336 px przy 1459 px dostępnych (przy skalowaniu 125 %
    1695/1672), a na zrzucie kończyło się na „…Przywróć c" - czyli wyglądało na kompletne.

    Elizja nie odzyskuje treści i nie ma udawać, że odzyskuje; zdejmuje CICHE kłamstwo, a pełne
    zdanie oddaje podpowiedź. Bramka pyta o oba człony naraz, bo sam wielokropek bez tooltipu
    zamieniłby ciche ucięcie na jawne, ale dalej bezpowrotne.

    Falsyfikator: zwróć w `_zwezone` sam `msg` → obie asercje czerwienieją."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        dlugie = "Cofnięto przypisanie na 229 z 711 klatek" + " · kalibracja: 6" * 40
        win._flash(dlugie)
        widoczne = win.report_label.text()

        assert widoczne != dlugie and len(widoczne) < len(dlugie), "raport nie został przycięty"
        assert widoczne.endswith("…"), f"przycięcie bez znaku - ciche kłamstwo: {widoczne!r}"
        assert win.statusBar().toolTip() == dlugie, "pełna treść przepadła bezpowrotnie"

        # …a zdanie, które się MIEŚCI, zostaje nietknięte - PODPOWIEDŹ ZOSTAJE MIMO TO. Bramka
        # pakietu (obie soczewki) wskazała trzy drogi, którymi treść ginęła przy warunkowym
        # tooltipie: gałąź „za wąsko na elizję", zwężenie okna w trakcie życia komunikatu
        # i recepta przezroczysta dla myszy. Podpowiedź bezwarunkowa zdejmuje wszystkie trzy.
        win._flash("Nazwano 12 z 12 klatek: NGC 7000")
        assert win.report_label.text() == "Nazwano 12 z 12 klatek: NGC 7000"
        assert win.statusBar().toolTip() == "Nazwano 12 z 12 klatek: NGC 7000"
    finally:
        win.close()


def test_recepta_ma_WLASNY_nosnik_i_ZABIERA_szerokosc_raportowi(qapp, tmp_path):
    """FH-2, człon (b) WRAZ z pomiarem, który wiąże go z członem (a). `addPermanentWidget` zabiera
    szerokość jedynemu `showMessage`, więc sam rozdział sprawiłby, że raport ucina się WCZEŚNIEJ
    niż przed naprawą - dlatego elizja liczy się PONOWNIE, gdy recepta wchodzi na pasek.

    Falsyfikator: zdejmij ponowny `showMessage` z `_pokaz_recepte` → raport zostaje przycięty do
    zapasu SPRZED recepty i wystaje pod nią, czyli wraca ucięcie bez znaku."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        dlugie = "Cofnięto przypisanie na 229 z 711 klatek" + " · kalibracja: 6" * 40
        win._flash(dlugie)
        bez_recepty = win.report_label.text()

        recepta = "potem przywrócisz: Obiekt → Przywróć cofnięte przypisanie"
        win._pokaz_recepte(Recepta([recepta]))
        assert win.recipe_label.isVisible(), "recepta nie ma nośnika"
        assert "Przywróć cofnięte przypisanie" in win.recipe_label.text()
        assert len(win.report_label.text()) < len(bez_recepty), \
            "raport nie oddał miejsca recepcie - przy realnym zdaniu wystawałby pod nią"
        # PODPOWIEDŹ PASKA NIESIE OBA CZŁONY. Od FH-2e recepta jest klikalna, więc `QEvent::ToolTip`
        # do niej dociera - jej własna podpowiedź niesie pełną receptę (przycięty napis jej nie zgubi).
        assert win.statusBar().toolTip() == f"{dlugie} · {recepta}", "pełne zdanie przepadło"
        assert win.recipe_label.toolTip() == recepta, "przycięta recepta bez pełnej treści"
    finally:
        win.close()


def test_FH2e_recepta_KLIKA_i_wykonuje_czlon_PIERWSZY_a_potem_jest_wygaszona(qapp, tmp_path):
    """FH-2e. Recepta WYKONUJE powrót, a nie tylko go opisuje: klik robi człon pierwszy (kolejność
    członów jest kolejnością w czasie). Obie połowy wariantu „e" idą razem - przycisk przyjmuje
    mysz i wygląda na przycisk (`autoRaise` zdjęte), bo teraz klik naprawdę coś robi.

    Wariant „potem" (człon bez wykonawcy) zostawia przycisk WYGASZONY, nie chowa go: zdanie dalej
    mówi prawdę o drugim kroku, a klikalny napis bez akcji kłamałby afordancją.

    Falsyfikator: zostaw `WA_TransparentForMouseEvents` albo nie podepnij `clicked` → klik nic nie
    robi; ustaw `setEnabled(True)` bezwarunkowo → człon „potem" udaje wykonalny."""
    from PySide6.QtWidgets import QToolButton
    from horreum.gui.grid import CzlonRecepty, Recepta
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        assert isinstance(win.recipe_label, QToolButton)
        assert not win.recipe_label.testAttribute(Qt.WA_TransparentForMouseEvents), \
            "recepta z wykonawcą nie przyjmuje kliknięcia"
        assert not win.recipe_label.autoRaise(), "klikalna recepta rysuje się jak tekst"
        assert win.recipe_label.focusPolicy() == Qt.NoFocus, "recepta nie jest przystankiem Taba"
        # Własność roli byłaby tu MARTWA (selektor motywu to `QLabel[role=…]`), a gdyby ożyła,
        # zeszłaby recepcie do 3,67:1 - poniżej progu 4,5:1. Nie zostawiamy jej naładowanej.
        assert win.recipe_label.property("role") is None, "martwa własność roli czeka na ożywienie"

        wykonane = []
        win._pokaz_recepte(Recepta([CzlonRecepty("odsłoni je „× Wyczyść zbiór”",
                                                  lambda: wykonane.append("odslon")),
                                     CzlonRecepty("potem przywrócisz: Obiekt → Przywróć", None)]))
        assert win.recipe_label.isVisible() and win.recipe_label.isEnabled()
        win.recipe_label.click()
        assert wykonane == ["odslon"], "klik nie wykonał członu pierwszego"

        win._pokaz_recepte(Recepta([CzlonRecepty("potem przywrócisz: Obiekt → Przywróć", None)]))
        assert win.recipe_label.isVisible(), "recepta „potem” zniknęła zamiast zgasnąć"
        assert not win.recipe_label.isEnabled(), "człon bez wykonawcy udaje wykonalny"
        win._wykonaj_recepte()                       # druga linia obrony: sygnał wołany wprost
        assert wykonane == ["odslon"]
    finally:
        win.close()


def test_recepta_STOI_PRZY_RAPORCIE_a_faza_przy_uchwycie(qapp, tmp_path):
    """FH-2, kolejność na belce. Widżety stałe idą OD LEWEJ w kolejności dodawania, więc faza
    dodana pierwsza wchodziła MIĘDZY raport a receptę - dwa człony jednego zdania rozdzielone
    komunikatem trzeciej sprawy (firsthand, `K_faza.png`). Recepta ma się kleić do swojego raportu.

    AR-76: recepta stoi ZARAZ ZA RAPORTEM, nie przy prawej krawędzi. Firsthand mierzył raport od
    x≈8 i receptę od x≈1290 - dwa człony jednego zdania ~700 px od siebie, bo raport malował się
    w polu komunikatu, a recepta mogła stać wyłącznie wśród widżetów stałych. Raport ma własną
    etykietę, recepta jest następnym widżetem: odstęp między nimi to odstęp układu paska. Przy
    raporcie dłuższym niż pasek oba człony mieszczą się przed fazą (elizja liczy receptę).

    Falsyfikator: wróć recepcie `addPermanentWidget` → odstęp rośnie do szerokości wolnego paska;
    wróć raport na `showMessage` → etykieta raportu jest pusta, a recepta ląduje na x≈2."""
    from horreum.gui.app import _PASEK_ODSTEP
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    bar = win.statusBar()

    def x_na_pasku(w):
        return w.mapTo(bar, w.rect().topLeft()).x()

    try:
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte(Recepta(["przywrócisz: Obiekt → Przywróć cofnięte przypisanie"]))
        win._say_phase("Odświeżam widoki po etapie…")
        QApplication.processEvents()

        assert x_na_pasku(win.recipe_label) < x_na_pasku(win.phase_label), \
            "faza rozdziela raport od jego recepty"
        koniec_raportu = x_na_pasku(win.report_label) + win.report_label.width()
        assert win.report_label.text() == "Cofnięto przypisanie na 2 z 2 klatek"
        assert x_na_pasku(win.recipe_label) - koniec_raportu == _PASEK_ODSTEP, \
            "recepta odjechała od raportu"
        assert win.report_label.width() <= win.report_label.sizeHint().width() + 1, \
            "etykieta raportu rozlała się na pusty pasek"

        win._flash("Cofnięto przypisanie na 229 z 711 klatek" + " · kalibracja: 6" * 40)
        win._pokaz_recepte(Recepta(["przywrócisz: Obiekt → Przywróć cofnięte przypisanie"]))
        QApplication.processEvents()
        assert win.report_label.text().endswith("…")
        assert win.report_label.width() >= win.report_label.sizeHint().width(), \
            "elizja liczona do zapasu większego niż pole - wielokropek ucięty bez znaku"
        assert x_na_pasku(win.recipe_label) + win.recipe_label.width() <= x_na_pasku(win.phase_label), \
            "długi raport wypchnął receptę pod fazę"
        assert x_na_pasku(win.recipe_label) - (x_na_pasku(win.report_label)
                                               + win.report_label.width()) == _PASEK_ODSTEP
    finally:
        win.close()


def test_recepta_PRZEZYWA_wygasniecie_raportu_a_GASNIE_przy_cudzym(qapp, tmp_path):
    """FH-2e. Recepta stoi na STANIE, nie na zegarze raportu: odwracalność trwa, dopóki jest co
    przywracać, więc timeout zdania po geście jej nie gasi (dawniej przy dwóch członach umierała po
    wykonaniu pierwszego). Gasi ją cudzy raport (`_flash`) - zdanie o innej sprawie z instrukcją
    starego gestu obok mówiłoby o czymś, po czym nie ma śladu - a wygaśnięty raport zostawia
    w podpowiedzi paska samą receptę.

    Falsyfikator: wróć do `_ustaw_recepte("")` w `_on_status_changed` → recepta znika z zegarem;
    zdejmij `_ustaw_recepte("")` z `_flash` → recepta przeżywa cudzy komunikat."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        recepta = "przywrócisz: Obiekt → Przywróć cofnięte przypisanie"
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte(Recepta([recepta]))
        assert win.recipe_label.isVisible()

        win._wygas_raport()                            # …to samo robi zegar raportu po 5 s
        assert win.recipe_label.isVisible(), "recepta umarła z zegarem raportu"
        assert win.statusBar().toolTip() == recepta, "podpowiedź niesie wygasły raport"

        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte(Recepta([recepta]))
        win._flash("Grid: 16 901 klatek, 0 kolumn-keywordów")
        assert not win.recipe_label.isVisible(), "recepta przeżyła CUDZY raport"
    finally:
        win.close()


def test_gest_osi_dowozi_recepte_NA_PASEK_przez_gospodarza(qapp, tmp_path):
    """SZEW, nie widok. Rozdział członów robi `FramesView`, a nośnik trzyma `MainWindow` - bramki
    po obu stronach przechodziłyby także wtedy, gdyby sygnał nie był podpięty. Ten test emituje
    kanał recepty z gridu i patrzy na PASEK OKNA.

    Falsyfikator: zdejmij `grid.status_recipe.connect(...)` z `_mount_views` → recepta nigdzie nie
    dojeżdża, choć oba końce działają."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path, object_axis=True)))
    try:
        win._show_view(NAV_ZBIORY)
        win.grid_view.status_recipe.emit(
            Recepta(["przywrócisz: Obiekt → Przywróć cofnięte przypisanie"]))
        assert win.recipe_label.isVisible()
        assert "Przywróć cofnięte przypisanie" in win.recipe_label.text()
    finally:
        win.close()


def test_raport_gridu_GASNIE_przy_zmianie_miejsca_nawigacji(qapp, tmp_path):
    """AR-34. „Grid: N klatek…" mówi o Zbiorach: po przejściu na Porządki albo do Dostawy wisiał
    dalej (do timeoutu) nad ekranem, którego nie dotyczy. Raport widoku gaśnie z wyjściem z niego,
    a cudzy komunikat (bez powiązania z miejscem) przeżywa przełączenie.

    Falsyfikator: zdejmij gaszenie z `_on_nav_changed` albo podepnij grid pod gołe `_flash` →
    pasek niesie raport gridu po zmianie widoku."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        win._show_view(NAV_ZBIORY)
        win.grid_view.load_report.emit("Grid: 16 901 klatek, 0 kolumn-keywordów")
        assert win.report_label.text().startswith("Grid:")
        win._show_view(NAV_PORZADKI)
        assert win.report_label.text() == "", "raport gridu przeżył zmianę miejsca"
        win._show_view(NAV_ZBIORY)
        win.grid_view.load_report.emit("Grid: 3 klatki, 0 kolumn-keywordów")
        win._show_view(NAV_DOSTAWA)
        assert win.report_label.text() == ""
        # raport spoza gridu nie jest związany z miejscem
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._show_view(NAV_ZBIORY)
        assert win.report_label.text().startswith("Cofnięto")
    finally:
        win.close()


def test_raport_wczytania_gridu_POZA_Zbiorami_nie_przykrywa_statusu_etapu(qapp, tmp_path):
    """AR-34 domknięte: raport WCZYTANIA zbioru („Grid: N klatek…") pada też wtedy, gdy Zbiorów
    nie widać - odświeżenie widoków po przebiegu Dostawy. Szedł wtedy na pasek bez powiązania
    z miejscem i przykrywał status etapu, po który user patrzy w Dostawie (wizytacja: „Grid: 16901
    klatek" nad Dostawą i nad Porządkami). Teraz czeka na wejście w Zbiory i dopiero tam pada.

    Falsyfikator: podepnij `grid.load_report` pod `_flash_grid` → pasek Dostawy niesie raport
    gridu zamiast statusu etapu; zdejmij odłożenie z `_on_nav_changed` → wejście w Zbiory nie
    pokazuje raportu."""
    from horreum.gui import i18n
    win = _pokazane(MainWindow(_seeded_db(tmp_path, object_axis=True)))
    try:
        win._show_view(NAV_DOSTAWA)
        pasek = _zapis_paska(win)
        _przebieg_w_watku(win, lambda: win.pipeline_view.run_stage("group"))
        status_etapu = i18n.t("pipeline.stage_done_status", stage=i18n.t("pipeline.stage.group"))
        assert status_etapu in pasek, pasek
        # Po statusie etapu odświeżenie widoków przeładowało grid - i jego raport na pasek nie wszedł.
        # (Inne widoki mówią tam własnymi zdaniami, np. pusta oś stanowisk w tej fiksturze;
        # ten test pilnuje wyłącznie raportu wczytania Zbiorów.)
        po_etapie = pasek[pasek.index(status_etapu):]
        assert not any(m.startswith("Grid:") or m == i18n.t("busy.read_frames")
                       for m in po_etapie), po_etapie
        win._show_view(NAV_PORZADKI)
        assert not win.report_label.text().startswith("Grid:")
        win._show_view(NAV_ZBIORY)
        assert win.report_label.text().startswith("Grid:"), \
            "raport wczytania czekał na wejście w Zbiory"
        # odłożony raport pada RAZ - kolejne wejście nie powtarza starego zdania
        win._show_view(NAV_DOSTAWA)
        win._flash("inny raport")
        win._show_view(NAV_ZBIORY)
        assert win.report_label.text() == "inny raport"
    finally:
        win.close()


def test_wynik_GESTU_gridu_poza_Zbiorami_dalej_pada_na_pasek(qapp, tmp_path):
    """Granica poprawki raportu wczytania: wynik GESTU gridu (np. gest panelu rodowodu, który sam
    przełącza widok na Dostawę) zostaje na pasku także poza Zbiorami - to zdanie o akcji usera.

    Falsyfikator: odłóż `status_message` gridu jak raport wczytania → pasek Dostawy milczy."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        win._show_view(NAV_DOSTAWA)
        win.grid_view.status_message.emit("Zapisano odniesienie czasu")
        assert win.report_label.text() == "Zapisano odniesienie czasu"
    finally:
        win.close()


def test_recepta_PRZEZYWA_otwarcie_menu_ktore_sama_wskazuje(qapp, tmp_path):
    """FH-2, pułapka ZMIERZONA w bramce pakietu (soczewka architektury, hipoteza potwierdzona).

    Każda pozycja menu wysyła przy podświetleniu `QStatusTipEvent`, a pozycja bez własnego opisu -
    a takich w tym repo są wszystkie, `setStatusTip` nie pada ani razu - wysyła go PUSTEGO. Okno
    przepisuje to na `showMessage("")`, pasek melduje `messageChanged("")` i wygląda to identycznie
    jak timeout. Zmierzone przed naprawą: gest → `QStatusTipEvent("")` → recepta gaśnie.

    Trafiało to najdotkliwiej w receptę „Obiekt ▾ → Przywróć cofnięte przypisanie", bo jej
    WYKONANIE zaczyna się od otwarcia tego właśnie menu: instrukcja znikała w trakcie celowania
    w pozycję, którą nazywa. Do FH-2e otwarty popup był jedynym rozróżnieniem, a ogon klasy
    (najechanie na menubar bez otwierania) zostawał. Od FH-2e recepta stoi na STANIE, więc pusty
    `QStatusTipEvent` nie gasi jej ani przy otwartym menu, ani bez niego.

    Falsyfikator: wróć do gaszenia recepty w `_on_status_changed` → recepta gaśnie przy pierwszym
    dotknięciu menu albo menubaru, choć gest wciąż czeka na dokończenie."""
    from PySide6.QtGui import QStatusTipEvent
    from PySide6.QtWidgets import QMenu

    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    popup = QMenu(win)
    try:
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte(Recepta(["przywrócisz: Obiekt → Przywróć cofnięte przypisanie"]))
        assert win.recipe_label.isVisible()

        popup.addAction("Przywróć cofnięte przypisanie")
        popup.popup(win.mapToGlobal(win.rect().center()))
        QApplication.processEvents()
        assert QApplication.activePopupWidget() is not None, "popup się nie otworzył - brak układu"

        QApplication.sendEvent(win, QStatusTipEvent(""))
        QApplication.processEvents()
        assert win.recipe_label.isVisible(), "recepta zgasła w trakcie otwierania własnego menu"

        # …i OGON KLASY ZAMKNIĘTY: to samo zdarzenie BEZ otwartego menu (najechanie na menubar)
        # też jej nie gasi - recepta nie wisi już na czasie życia komunikatu.
        popup.close()
        QApplication.processEvents()
        assert QApplication.activePopupWidget() is None, "menu się nie zamknęło - brak układu"
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte(Recepta(["przywrócisz: Obiekt → Przywróć cofnięte przypisanie"]))
        QApplication.sendEvent(win, QStatusTipEvent(""))
        QApplication.processEvents()
        assert win.recipe_label.isVisible(), "pusty podgląd pozycji menubaru zgasił receptę"
    finally:
        popup.deleteLater()
        win.close()


def test_AR97_zdanie_etapu_CZEKA_na_koniec_okna_raportu_gestu(qapp, tmp_path):
    """AR-97. Wizytacja natywna: odmowa kafla Przyjmij w biegu żyła na pasku 0,39 s, bo
    „Grupowanie: gotowe.” wypierało ją od razu; zdanie żniw - 0,38 s („Skan: gotowe.”). Raport
    gestu otwiera okno priorytetu, w którym zdanie etapu czeka, a po oknie staje na pasku.
    Granice: zdanie etapu bez okna pada od razu i samo okna nie otwiera; nowszy raport zastępuje
    czekające zdanie (jest od niego starsze); wygaśnięcie raportu gestu kończy okno; stan okna
    („Baza wczytana”) okna nie otwiera.

    Falsyfikator: podepnij `stage_status` wprost pod `_flash` → po odmowie na pasku stoi zdanie
    etapu; zostaw okno po wygaśnięciu raportu → zdanie etapu czeka nad pustym paskiem."""
    from horreum.gui import i18n
    from horreum.gui.app import _PRIORYTET_GESTU_MS
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    etap = win.pipeline_view.stage_status
    gotowe = i18n.t("pipeline.stage_done_status", stage=i18n.t("pipeline.stage.group"))
    try:
        assert win._zegar_priorytetu.interval() == _PRIORYTET_GESTU_MS == 5000
        etap.emit(gotowe)                                   # bez okna - od razu
        assert win.report_label.text() == gotowe
        assert not win._zegar_priorytetu.isActive(), "zdanie etapu otworzyło okno"

        win._flash("Dostawa w biegu - poczekaj na koniec etapu")
        etap.emit(gotowe)
        assert win.report_label.text() == "Dostawa w biegu - poczekaj na koniec etapu", \
            "zdanie etapu wyparło odmowę gestu w oknie priorytetu"
        win._wypusc_raport_etapu()                          # koniec okna (zegar)
        assert win.report_label.text() == gotowe, "zdanie etapu przepadło zamiast poczekać"

        win._flash("Odmowa")
        etap.emit(gotowe)
        win._flash("Wciągnięto 1 master")                   # nowszy raport w oknie
        win._wypusc_raport_etapu()
        assert win.report_label.text() == "Wciągnięto 1 master", "starsze zdanie etapu wróciło"

        win._flash("Odmowa")
        etap.emit(gotowe)
        win._wygas_raport()                                 # raport gestu zgasł przed końcem okna
        assert win.report_label.text() == gotowe and not win._zegar_priorytetu.isActive()

        win._flash("Baza wczytana", gest=False)
        etap.emit(gotowe)
        assert win.report_label.text() == gotowe, "stan okna trzymał zdanie etapu"
    finally:
        win.close()


def test_recepta_MA_SUFIT_szerokosci_i_nie_zjada_pola_raportu(qapp, tmp_path):
    """FH-2. Sufit recepty jest strażnikiem na przyszłość, nie ograniczeniem stanu dzisiejszego:
    bez niego długość instrukcji zależy wyłącznie od zawartości katalogu i18n, więc dłuższa
    etykieta menu w kolejnym tłumaczeniu zjadłaby pole raportu bez żadnego sygnału (bramka
    pakietu, soczewka architektury).

    Falsyfikator: zdejmij elizję z `_ustaw_recepte` → widżet rośnie z tekstem bez granicy."""
    from horreum.gui.app import _PASEK_UDZIAL_RECEPTY
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte(Recepta(["przywrócisz: " + "bardzo długa etykieta pozycji menu " * 20]))

        sufit = int(win.statusBar().width() * _PASEK_UDZIAL_RECEPTY)
        assert win.recipe_label.sizeHint().width() <= sufit + 4, "recepta przebiła swój sufit"
        assert win.recipe_label.text().endswith("…"), "przycięcie recepty bez znaku"
        assert win.report_label.text(), "raport zniknął z paska przez szerokość recepty"
    finally:
        win.close()


# ═════════════════════════ W-3 — KOLEJKA PRZEGLĄDU NIE REZERWUJE PUSTKI


def test_kolejka_przegladu_ZWIJA_SIE_do_tresci_z_sufitem(qapp, tmp_path):
    """W-3. Lista dostawała 340 px ramki na 80 px treści (76 % pustki), stojąc nad tabelą
    „Biblioteka", której tego pionu brakowało. Bliźniacza lista Porządków zamknęła ten sam dług
    pomiarem (`tasks._fit_task_list`) - tu dochodzi SUFIT, bo kolejka rośnie do ~45 pozycji
    i dopasowanie bez niego zabrałoby bibliotekę w całości.

    Falsyfikator: zdejmij `_dopasuj_kolejke()` z `_load_review` → wysokość wraca do sufitu widżetu
    (bardzo duża liczba) i pierwsza asercja czerwienieje."""
    from horreum.gui.app import _KOLEJKA_SUFIT_WIERSZY
    win = _pokazane(MainWindow(_seeded_db(tmp_path, object_axis=True)))
    try:
        v = win.object_view
        v.refresh()
        lista = v.review
        n = lista.count()
        assert n, "kolejka pusta - bramka nie ma czego mierzyć"

        def _wysokosci(ile):
            return sum(lista.sizeHintForIndex(lista.model().index(i, 0)).height()
                       for i in range(min(ile, lista.count())))

        assert lista.maximumHeight() == _wysokosci(_KOLEJKA_SUFIT_WIERSZY) + 2 * lista.frameWidth(), \
            "lista nie zeszła do wysokości swojej treści"

        # …a SUFIT jest realny: lista dłuższa niż próg przestaje rosnąć i dostaje przewijanie
        for i in range(_KOLEJKA_SUFIT_WIERSZY * 2):
            lista.addItem(QListWidgetItem(f"dopisana pozycja {i}"))
        v._dopasuj_kolejke()
        assert lista.count() > _KOLEJKA_SUFIT_WIERSZY
        assert lista.maximumHeight() == _wysokosci(_KOLEJKA_SUFIT_WIERSZY) + 2 * lista.frameWidth(), \
            "sufit nie zadziałał - długa kolejka zabiera pion bibliotece"
    finally:
        win.close()


# ═════════════════════════ BP-1 — SUROWY KLUCZ i18n NA CAŁYM OKNIE


def _napisy_okna(win):
    """Wszystko, co okno POKAZUJE słowami - z KOMPLETU widoków, nie z jednego (BP-1).

    Bramka klasy „napis widoczny w oknie nie jest kluczem" mieszkała dotąd w `FramesView`, bo tam
    siedział defekt, który ją wywołał. Widoków jest jednak sześć, a `i18n.t` na nieznanym kluczu
    nie rzuca - renderuje surowe `object.foo` na ekranie. Fikstura całego okna jest przy tej paczce
    darmowa, więc bramka schodzi tam, gdzie klasa naprawdę żyje.

    DWIE POWIERZCHNIE DOŁOŻONE do zbioru z `test_gui_grid`: `placeholderText()` (napis W POLU, przez
    `text()` niewidoczny) i statyczne `toolTip()` (podpowiedź bywa jedynym miejscem, gdzie recepta
    jest zapisana - patrz cztery tooltipy-recepty paczki „Cofnij"). Tooltipy liczone per indeks
    modelu zostają poza zbiorem: nie są własnością widżetu i mają własne bramki."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QAbstractButton, QComboBox, QLabel, QLineEdit, QListWidget, QWidget,
    )

    napisy = set()
    for w in win.findChildren(QLabel) + win.findChildren(QAbstractButton):
        napisy.add(w.text())
    for w in win.findChildren(QLineEdit):
        napisy.add(w.placeholderText())
    for c in win.findChildren(QComboBox):
        napisy |= {c.itemText(i) for i in range(c.count())}
    # POZYCJE LIST TEŻ SĄ NAPISAMI - i to nie jest dopełnienie dla kompletu: tą drogą mówią do usera
    # sidebar nawigacji, kolejka przeglądu i lista zadań, czyli trzy powierzchnie, których żadna
    # z pozostałych pętli nie widzi (`QListWidgetItem` nie jest widżetem).
    for lw in win.findChildren(QListWidget):
        napisy |= {lw.item(i).text() for i in range(lw.count())}
    for a in win.findChildren(QAction):
        napisy.add(a.text())
    for w in win.findChildren(QWidget):
        napisy.add(w.toolTip())
    napisy.add(win.windowTitle())
    return {n for n in napisy if n}


def test_ZADNE_okno_nie_pokazuje_surowego_klucza_i18n(qapp, tmp_path):
    """BRAMKA KLASY NAD CAŁYM OKNEM (BP-1). Bliźniaczka bramki z `test_gui_grid`, tylko że tamta
    chodzi po JEDNYM widoku z sześciu i nie zna ani placeholderów, ani tooltipów - a klucz
    z literówką renderuje się surowo przez fallback `i18n.t` i przechodzi obok kolektora literałów,
    gdy klucz idzie do `t()` zmienną.

    Zbiór kluczy bierzemy z katalogu, więc bramka rośnie razem z nim, a fałszywy trafiony jest
    strukturalnie niemożliwy: klucze mają kropki i ASCII, etykiety nie.

    Falsyfikator: podmień w dowolnym widoku `i18n.t("object.library")` na goły literał klucza
    → bramka czerwienieje, zanim zobaczy to użytkownik."""
    from horreum.gui.i18n_catalog import CATALOG

    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win._show_view(NAV_PORZADKI)               # …podstrony osi też mają być zbudowane
        napisy = _napisy_okna(win)

        surowe = sorted(napisy & set(CATALOG))
        assert not surowe, f"kontrolka pokazuje KLUCZ zamiast napisu: {surowe}"
        # …i bramka NIE JEST ŚLEPA: zbiera realne napisy z co najmniej dwóch różnych widoków
        assert "Dostawa" in napisy or "Zbiory" in napisy, "kolektor nie widzi nawigacji"
        assert any("Horreum" in n for n in napisy), "kolektor nie widzi tytułu okna"
    finally:
        win.close()


# --- Plik → „Folder roboczy WBPP…" ---

def _akcja_menu_plik(win, klucz):
    """Akcja menu Plik po etykiecie z katalogu (bez sprzęgania testu z kolejnością wierszy)."""
    from horreum.gui import i18n
    from PySide6.QtWidgets import QMenu
    # `QAction.menu()` oddaje wrapper już skasowany po stronie C++ (menu należy do paska, nie do
    # Pythona) - dzieci paska są pewną drogą.
    menu = next(m for m in win.menuBar().findChildren(QMenu) if m.title() == i18n.t("menu.file"))
    for akcja in menu.actions():
        if akcja.text() == i18n.t(klucz):
            return akcja
    raise AssertionError(f"brak akcji {klucz!r} w menu Plik")


def test_menu_plik_folder_roboczy_stoi_za_nowa_baza(qapp):
    from horreum.gui import i18n
    win = MainWindow()
    try:
        akcje = [_akcja_menu_plik(win, k) for k in ("menu.open_db", "menu.new_db", "menu.work_root")]
        menu = akcje[0].parent()
        assert menu.actions()[:3] == akcje                # „Folder roboczy WBPP…" tuż za „Nowa baza…"
    finally:
        win.close()


def test_menu_folder_roboczy_karta_pipeline_i_zero_dysku(qapp, tmp_path, ustawienia, monkeypatch):
    """Wybór folderu roboczego: zapis `work/root` (jedyny właściciel: gospodarz), karta celu wydania
    `_WBPP` pod wskazanym katalogiem (zaznaczona jako ostatnio użyta), folder podany widokowi
    Dostawy i zdanie na pasku. ZERO DYSKU w slocie: wskazany katalog nie istnieje, a szpieg nie
    łapie `makedirs`/`mkdir`/`exists`/`isdir` na nim - `_WBPP`, `OBJECTS\\<obiekt>` i `out` zakłada
    dopiero wydanie obiektu. Ponowny wybór tego samego katalogu inaczej zapisanego (`/`, wielkość
    liter) nie dokłada drugiej karty. Anulowanie dialogu nie zmienia niczego."""
    import json
    import threading
    from pathlib import Path
    from horreum.gui import i18n, projection_dialog
    from PySide6.QtWidgets import QFileDialog

    i18n.set_lang("pl")
    wybrany = tmp_path / "ASTRO_PRACA"
    wbpp = str(wybrany / "_WBPP")
    dotkniecia = []

    def szpieg(nazwa, prawdziwa):
        def _f(sciezka=None, *a, **kw):
            if threading.current_thread() is threading.main_thread() and "ASTRO_PRACA" in str(sciezka):
                dotkniecia.append((nazwa, str(sciezka)))
            return prawdziwa(sciezka, *a, **kw)
        return _f

    for modul, atrybut in ((os, "makedirs"), (os, "mkdir"), (os, "stat"),
                           (os.path, "exists"), (os.path, "isdir"), (Path, "mkdir"),
                           (Path, "exists"), (Path, "is_dir")):
        monkeypatch.setattr(modul, atrybut, szpieg(atrybut, getattr(modul, atrybut)))

    odpowiedzi = [str(wybrany), "", str(wybrany).replace("\\", "/").upper()]
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: odpowiedzi.pop(0)))

    win = MainWindow()                                    # bez bazy: menu działa przed otwarciem bazy
    try:
        assert win.pipeline_view is None
        _akcja_menu_plik(win, "menu.work_root").trigger()
        assert ustawienia.value("work/root") == str(wybrany)
        cele = json.loads(ustawienia.value("projection/targets"))
        assert cele == [{"name": "Folder roboczy", "path": wbpp}]
        assert ustawienia.value("projection/last_target") == wbpp
        assert win._pelny_komunikat == (
            f"Folder roboczy: {wbpp} - powstanie przy pierwszym wydaniu; "
            "stąd okno żniw bierze wyniki WBPP")

        _akcja_menu_plik(win, "menu.work_root").trigger()  # anulowanie dialogu
        assert ustawienia.value("work/root") == str(wybrany)

        _akcja_menu_plik(win, "menu.work_root").trigger()  # ten sam katalog, inny zapis
        assert len(json.loads(ustawienia.value("projection/targets"))) == 1
        assert projection_dialog.target_roots() == [wbpp.upper()]
    finally:
        win.close()
    assert dotkniecia == [], dotkniecia
    assert not wybrany.exists()                           # nic nie założone


def test_folder_roboczy_trafia_do_pipeline_przy_starcie_i_po_wyborze(qapp, tmp_path, ustawienia,
                                                                    monkeypatch):
    """Start okna z zapamiętanym `work/root` podaje `_WBPP` widokowi Dostawy (każda baza montuje nowy
    widok, folder roboczy jest jeden); wybór z menu przy otwartej bazie podaje go od ręki, bez
    przemontowania."""
    from PySide6.QtWidgets import QFileDialog
    ustawienia.setValue("work/root", str(tmp_path / "praca"))
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert win.pipeline_view._work_root == str(tmp_path / "praca" / "_WBPP")
        inny = tmp_path / "inna_praca" / "_WBPP"          # wskazanie samego `_WBPP`: bez drugiego w środku
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(inny)))
        _akcja_menu_plik(win, "menu.work_root").trigger()
        assert win.pipeline_view._work_root == str(inny)
        assert ustawienia.value("work/root") == str(inny)
    finally:
        win.close()
    win2 = MainWindow(_seeded_db(tmp_path, "druga.db"))
    try:
        assert win2.pipeline_view._work_root == str(inny)  # pamięć przeżywa okno
    finally:
        win2.close()


# ═════════════════════════ AR-175 - OKNO NIE STOI: liczniki montażu w tle, dwa kanały fazy, motyw

from PySide6.QtGui import QColor  # noqa: E402 - blok AR-175 (porównania kolorów motywu)

# Bezpiecznik bram rachunku liczników - test, który zgubił bramę, czerwienieje, zamiast wisieć.
_BEZPIECZNIK_LICZNIKOW_S = 15


def _w_tle(monkeypatch):
    """Tryb produkcyjny okna (wątki tła, osie leniwe) - autouse `_pola_inline` stawia tryb bez wątków i osie
    wczytane od razu."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", True)
    monkeypatch.setattr(MainWindow, "_osie_leniwie", True)


def _brama_rachunku(monkeypatch, *, baza=None, pada=None):
    """Rachunek liczników Porządków (`tasks._stan_licznikow`) POZA wątkiem GUI czeka na bramę i zapisuje
    wątek KAŻDEGO wywołania. `baza` - nazwa pliku bazy, której rachunek czeka (inne liczą od razu);
    `pada` - wyjątek rzucany po bramie zamiast rachunku. Zwraca `(brama, wszedl, watki, glowny)`."""
    import threading
    from horreum.gui import tasks as tasks_mod
    brama, wszedl, watki = threading.Event(), threading.Event(), []
    glowny = threading.get_ident()
    prawdziwy = tasks_mod._stan_licznikow

    def _stan(con):
        watki.append(threading.get_ident())
        if threading.get_ident() != glowny and (
                baza is None or os.path.basename(queries.db_path_of(con)) == baza):
            wszedl.set()
            brama.wait(_BEZPIECZNIK_LICZNIKOW_S)
            if pada is not None:
                raise pada
        return prawdziwy(con)
    monkeypatch.setattr(tasks_mod, "_stan_licznikow", _stan)
    return brama, wszedl, watki, glowny


def _czekaj_na(warunek, opis):
    """Pompuj pętlę zdarzeń (`processEvents` + `sleep`, nie `qWait`), aż `warunek()`; bezpiecznik."""
    import time
    from PySide6.QtCore import QCoreApplication, QEventLoop
    koniec = time.monotonic() + _BEZPIECZNIK_LICZNIKOW_S
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {_BEZPIECZNIK_LICZNIKOW_S} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.005)


def _pompuj(n=5):
    """Kilka obrotów pętli zdarzeń (`processEvents` + `sleep`) - doręcza `singleShot(0)` i sygnały
    kolejkowane, bez warunku."""
    import time
    from PySide6.QtCore import QCoreApplication, QEventLoop
    for _ in range(n):
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.005)


def _po_rachunku(win):
    """Okno po rachunku montażu: wątek liczników zebrany, faza tła zgasła."""
    _czekaj_na(lambda: win.tasks_view._liczniki_thread is None and win.phase_label.text() == "",
               "rachunek montażu nie skończył albo faza tła nie zgasła")


def _plakietka(win, n):
    from horreum.gui import i18n
    return i18n.t("nav.porzadki") if n == 0 else i18n.t("nav.porzadki_count", n=n)


def test_otwarcie_bazy_liczy_Porzadki_w_tle_a_petla_bije(qapp, tmp_path, monkeypatch):
    """AR-175: rachunek liczników Porządków przy montażu stał na wątku GUI ~1,5 s z ~3 s otwarcia bazy
    (kopia pf4). Teraz liczy go wątek tła: konstruktor okna wraca, gdy rachunek wciąż czeka na bramie
    (wątek GUI wolny - ten test biegnie na nim dalej), plakietka i kafel Domu mówią „liczę”, pasek - fazę
    tła; wynik zdejmuje oba, faza gaśnie.
    Mutant: `refresh_counts()` bez `w_tle` w `_mount_views` - rachunek na wątku GUI, brama nie łapie."""
    from horreum.gui import i18n
    _w_tle(monkeypatch)
    brama, wszedl, watki, glowny = _brama_rachunku(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S), "rachunek montażu nie ruszył w tle"
        assert not brama.is_set() and win.tasks_view.liczy_w_tle(), "okno wróciło przed końcem rachunku"
        assert win.nav.item(NAV_PORZADKI).text() == i18n.t("nav.porzadki_count", n="…")
        assert win.home_view.tile_popraw.text() == i18n.t("home.tile.fix_count", n="…")
        assert win.home_view.tile_popraw.toolTip() == i18n.t("busy.counting_tasks")
        assert win.phase_label.text() == i18n.t("busy.counting_tasks")
        brama.set()
        _po_rachunku(win)
        assert watki and glowny not in watki, "liczył wątek tła"
        n = win.tasks_view.refresh_counts()
        assert win.nav.item(NAV_PORZADKI).text() == _plakietka(win, n)
        assert "…" not in win.home_view.tile_popraw.text()
        assert win.home_view.tile_popraw.toolTip() == i18n.t("home.tile.fix_tip")
    finally:
        brama.set()
        win.close()


def test_przelaczenie_bazy_w_trakcie_licznikow_nie_przyklada_starego_wyniku(qapp, tmp_path,
                                                                          monkeypatch):
    """AR-175: przełączenie bazy w czasie rachunku montażu - wynik starej bazy nie trafia ani na listę,
    ani na plakietkę nowej; plakietka i faza mówią o nowej bazie.
    Bez zegara: rachunek starej bazy liczy wynik PRZED bramą, a bramę zdejmuje pierwsze `request_cancel`
    (demontaż widoku) - wynik wychodzi z wątku dokładnie wtedy, gdy stary widok już podbił generację.
    Mutant: `_on_liczniki` bez sprawdzenia generacji - stary widok przykłada wynik po przełączeniu."""
    import threading
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    brama, wszedl = threading.Event(), threading.Event()
    glowny = threading.get_ident()
    prawdziwy = tasks_mod._stan_licznikow

    def _stan(con):
        wynik = prawdziwy(con)                       # policzony przed bramą - po niej zero SQL
        if threading.get_ident() != glowny and os.path.basename(queries.db_path_of(con)) == "a.db":
            wszedl.set()
            brama.wait(_BEZPIECZNIK_LICZNIKOW_S)
        return wynik
    monkeypatch.setattr(tasks_mod, "_stan_licznikow", _stan)
    anuluj = tasks_mod._LicznikiWorker.request_cancel
    monkeypatch.setattr(tasks_mod._LicznikiWorker, "request_cancel",
                        lambda self: (brama.set(), anuluj(self))[1])
    druga = _seeded_db(tmp_path, "b.db")
    win = MainWindow(_seeded_db(tmp_path, "a.db", object_axis=True))
    try:
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        stary, stare = win.tasks_view, []
        stary.counts_changed.connect(stare.append)
        win.open_path(druga)
        assert win.tasks_view is not stary
        _po_rachunku(win)
        assert stare == [], "wynik starej bazy przyłożony po przełączeniu"
        n = win.tasks_view.refresh_counts()
        assert win.nav.item(NAV_PORZADKI).text() == _plakietka(win, n)
    finally:
        brama.set()
        win.close()


def test_klik_w_wiersz_Porzadkow_przed_pierwszym_rachunkiem_czeka(qapp, tmp_path, monkeypatch):
    """AR-175: do pierwszego rachunku wiersze akcyjne są wygaszone z podpowiedzią „liczę” - prawdziwy
    klik niczego nie otwiera (wiersz „?” bez rachunku poszedłby do perspektywy zamiast do Dostawy).
    Wejście w Porządki w czasie rachunku montażu nie liczy drugi raz - ani na wątku GUI, ani drugim
    biegiem w tle (AR-337): czeka na bieg w drodze, do wyniku jest jeden rachunek. Klik w czasie
    rachunku NIE przepada: po wyniku prowadzi sam, bez drugiego kliku.
    Mutanty: wiersze aktywne od budowy (klik otwiera perspektywę); wejście bez czekania na bieg
    w drodze (drugi rachunek: na wątku GUI albo w tle); klik czekający zgubiony."""
    from PySide6.QtTest import QTest
    from horreum.gui import i18n
    _w_tle(monkeypatch)
    brama, wszedl, watki, glowny = _brama_rachunku(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.resize(1200, 800)
        win.show()
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        win._show_view(NAV_PORZADKI)
        tasks = win.tasks_view
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        it = _task_item(win, "dup_frames")
        assert it.toolTip() == i18n.t("busy.counting_tasks")

        def _klik():
            rect = tasks.tasks.visualItemRect(it)
            QTest.mouseClick(tasks.tasks.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
            _pompuj()
        _klik()
        assert otwarte == [] and tasks.pages.currentIndex() == 0
        assert glowny not in watki, "wejście liczyło na wątku GUI zamiast czekać na bieg w drodze"
        brama.set()
        _po_rachunku(win)
        _pompuj()
        assert it.toolTip() != i18n.t("busy.counting_tasks")
        assert otwarte == [PRESET_DUPS], "klik sprzed wyniku wykonany po pierwszym rachunku"
        assert len(watki) == 1, "wejście w trakcie rachunku montażu policzyło drugi raz"
    finally:
        brama.set()
        win.close()


def test_porazka_licznikow_montazu_zdejmuje_faze_tla_i_stan_licze(qapp, tmp_path, monkeypatch):
    """AR-175, AR-326: rachunek montażu pada dwa razy (ponowienie w tle, AR-302) - faza tła gaśnie, plakietka
    i kafel nie obiecują liczby („(…)” schodzi) ani nie mówią zera: „Porządki (!)” i „Popraw · !” z podpowiedzią
    = zdanie błędu; wiersze zapalone, wiersz błędu mówi zdaniem.
    Mutanty: koniec serii bez obsługi w gospodarzu (`liczenie_w_toku(False)`) - faza wisi; gospodarz daje gołe
    „Porządki” (`_on_tasks_counts(0)`, stan sprzed AR-326)."""
    import sqlite3
    from horreum.gui import i18n
    _w_tle(monkeypatch)
    brama, _wsz, watki, glowny = _brama_rachunku(
        monkeypatch, pada=sqlite3.OperationalError("database is locked"))
    brama.set()
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        _czekaj_na(lambda: win.tasks_view._liczniki_thread is None, "seria rachunku nie skończyła")
        _pompuj()
        assert len([w for w in watki if w != glowny]) == 2, watki
        assert win.phase_label.text() == ""
        zdanie = win.tasks_view.blad_licznikow.text()
        assert zdanie
        assert win.nav.item(NAV_PORZADKI).text() == i18n.t("nav.porzadki_count", n="!")
        assert win.nav.item(NAV_PORZADKI).toolTip() == zdanie
        assert win.home_view.tile_popraw.text() == i18n.t("home.tile.fix_count", n="!")
        assert win.home_view.tile_popraw.toolTip() == zdanie
        assert not win.tasks_view.blad_licznikow.isHidden()
        assert _task_item(win, "dup_frames").flags() & Qt.ItemIsEnabled
    finally:
        win.close()


def test_porazka_rachunku_bez_watkow_daje_wykrzyknik_a_wynik_go_zdejmuje(qapp, tmp_path, monkeypatch):
    """AR-326: pierwszy rachunek liczników w trybie bez wątków (rachunek synchroniczny montażu) pada - plakietka
    „Porządki (!)” i kafel „Popraw · !” z podpowiedzią = zdanie błędu (dawniej plakietka zostawała gołe
    „Porządki”, czytane jak zero); następny udany rachunek (wejście w Porządki) daje liczbę i zdejmuje
    podpowiedź. Falsyfikatory: brak sygnału `rachunek_padl` z rachunku synchronicznego; brak zdjęcia podpowiedzi
    przy liczbie."""
    import sqlite3
    from horreum.gui import i18n, tasks as tasks_mod
    prawdziwy = tasks_mod._stan_licznikow
    pada = {"tak": True}

    def _stan(con):
        if pada["tak"]:
            raise sqlite3.OperationalError("database is locked")
        return prawdziwy(con)
    monkeypatch.setattr(tasks_mod, "_stan_licznikow", _stan)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        item = win.nav.item(NAV_PORZADKI)
        zdanie = win.tasks_view.blad_licznikow.text()
        assert zdanie and item.text() == i18n.t("nav.porzadki_count", n="!"), item.text()
        assert item.toolTip() == zdanie
        assert win.home_view.tile_popraw.text() == i18n.t("home.tile.fix_count", n="!")
        pada["tak"] = False
        win._show_view(NAV_PORZADKI)
        assert win.tasks_view.ma_rachunek()
        assert "!" not in item.text() and item.toolTip() == ""
        assert win.home_view.tile_popraw.toolTip() == i18n.t("home.tile.fix_tip")
    finally:
        win.close()


def test_rachunek_padl_starego_widoku_nie_rusza_plakietki_nowej_bazy(qapp, tmp_path):
    """AR-326: sygnał porażki z tokenem montażu sprzed przełączenia bazy nie stawia „!” na plakietce nowej bazy.
    Falsyfikator: gospodarz bez porównania tokenu w `_on_rachunek_padl`."""
    from horreum.gui import i18n
    win = MainWindow(_seeded_db(tmp_path, "a.db", object_axis=True))
    try:
        stary = win.tasks_view
        win.open_path(_seeded_db(tmp_path, "b.db", object_axis=True))
        przed = win.nav.item(NAV_PORZADKI).text()
        stary.rachunek_padl.emit(stary.montaz, "stare zdanie")
        assert win.nav.item(NAV_PORZADKI).text() == przed != i18n.t("nav.porzadki_count", n="!")
        win.tasks_view.rachunek_padl.emit(win.tasks_view.montaz, "nowe zdanie")
        assert win.nav.item(NAV_PORZADKI).text() == i18n.t("nav.porzadki_count", n="!")
    finally:
        win.close()


def test_faza_tla_odrzuca_koniec_starego_widoku_i_ustepuje_fazie_pierwszego_planu(qapp, tmp_path,
                                                                                monkeypatch):
    """AR-175, dwa kanały fazy: spóźnione `liczenie_w_toku(False)` widoku sprzed przełączenia bazy nie
    gasi fazy tła nowej bazy; koniec tła w czasie fazy pierwszego planu nie zdejmuje jej - etykieta
    wraca do pustej dopiero po `_end_phase`.
    Mutanty: slot bez sprawdzenia tokenu montażu (stary widok gasi fazę nowej, AR-326); koniec tła pisze
    etykietę wprost (faza pierwszego planu znika)."""
    from horreum.gui import i18n
    _w_tle(monkeypatch)
    brama, wszedl, _w, _g = _brama_rachunku(monkeypatch, baza="b.db")
    win = MainWindow(_seeded_db(tmp_path, "a.db", object_axis=True))
    try:
        _po_rachunku(win)
        stary = win.tasks_view
        seria = stary._seria
        win.open_path(_seeded_db(tmp_path, "b.db", object_axis=True))
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        assert win.phase_label.text() == i18n.t("busy.counting_tasks")
        assert stary.montaz != win.tasks_view.montaz
        stary.liczenie_w_toku.emit(stary.montaz, seria, False)   # spóźniony koniec serii starej bazy
        assert win.phase_label.text() == i18n.t("busy.counting_tasks")
        win._say_phase(i18n.t("busy.refresh_views"))
        assert win.phase_label.text() == i18n.t("busy.refresh_views")   # pierwszy plan przed tłem
        brama.set()
        _czekaj_na(lambda: win.tasks_view._liczniki_thread is None, "rachunek nie skończył")
        _pompuj()
        assert win.phase_label.text() == i18n.t("busy.refresh_views")
        win._end_phase()
        assert win.phase_label.text() == ""
    finally:
        brama.set()
        win.close()


@pytest.mark.parametrize("rodzaj", ["nowsza", "zepsuta"])
def test_start_w_trybie_watkow_z_baza_odmowiona_stoi_bez_fazy(qapp, tmp_path, monkeypatch, rodzaj):
    """AR-175 (AR-69, AR-124): kanał fazy tła stoi przed pierwszym `_open_path` - konstruktor z bazą
    nowszą albo uszkodzoną kończy się `_end_phase` bez montażu i bez wyjątku; okno bez bazy, pasek
    pusty. Mutant: stan fazy tła zakładany dopiero w montażu (wyjątek z konstruktora)."""
    from PySide6.QtWidgets import QMessageBox
    from horreum.gui import i18n
    _w_tle(monkeypatch)
    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    sciezka = _nowsza_baza(tmp_path) if rodzaj == "nowsza" else _zepsute_bazy(tmp_path)[0]
    win = MainWindow(sciezka)
    try:
        assert len(ostrzezenia) == 1
        assert win.con is None and win.phase_label.text() == ""
        assert win.empty_note.text() == i18n.t("main.no_db")
    finally:
        win.close()


_ZAPYTANIE_BEZ_KONCA = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
                        "SELECT count(*) FROM c")


@pytest.mark.parametrize("droga", ["przelaczenie", "zamkniecie"])
def test_przelaczenie_i_zamkniecie_przerywaja_rachunek_w_locie(qapp, tmp_path, monkeypatch, droga):
    """AR-175: przełączenie bazy i zamknięcie okna czekały na koniec rachunku liczników (bez punktu
    przerwania). Rachunek tu = zapytanie SQLite, które kończy WYŁĄCZNIE `Connection.interrupt`; stróż
    przerywa je po bezpieczniku, więc regresja daje czerwień (czas), nie zawis.
    Mutant: `zatrzymaj_pola` bez `request_cancel` - czeka na stróża."""
    import threading
    import time
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    glowny = threading.get_ident()
    prawdziwy = tasks_mod._stan_licznikow
    w_locie = threading.Event()

    def _stan(con):
        if threading.get_ident() == glowny:
            return prawdziwy(con)
        stroz = threading.Timer(_BEZPIECZNIK_LICZNIKOW_S, con.interrupt)
        stroz.start()
        try:
            w_locie.set()
            con.execute(_ZAPYTANIE_BEZ_KONCA).fetchone()
        finally:
            stroz.cancel()
        return prawdziwy(con)
    monkeypatch.setattr(tasks_mod, "_stan_licznikow", _stan)
    win = MainWindow(_seeded_db(tmp_path, "a.db", object_axis=True))
    try:
        assert w_locie.wait(_BEZPIECZNIK_LICZNIKOW_S)
        time.sleep(0.2)                                  # zapytanie w biegu, nie przed nim
        t0 = time.monotonic()
        if droga == "przelaczenie":
            monkeypatch.setattr(tasks_mod, "_stan_licznikow", prawdziwy)
            win.open_path(_seeded_db(tmp_path, "b.db"))
        else:
            win.close()
        trwalo = time.monotonic() - t0
        assert trwalo < 5, f"{droga} czekało na rachunek {trwalo:.1f} s"
    finally:
        win.close()


def test_worker_licznikow_anulowany_przed_polaczeniem_nie_liczy(tmp_path):
    """AR-175: `request_cancel` przed otwarciem połączenia (przełączenie tuż po starcie wątku) - bieg
    nie liczy: flaga sprawdzana po otwarciu połączenia. Mutant: bez sprawdzenia flagi - pełny rachunek."""
    from horreum.gui.tasks import _LicznikiWorker
    w = _LicznikiWorker(3, _seeded_db(tmp_path, object_axis=True))
    gotowe, bledy = [], []
    w.done.connect(lambda gen, wynik: gotowe.append(gen))
    w.failed.connect(lambda gen, powod: bledy.append(gen))
    w.request_cancel()
    w.run()
    assert gotowe == [] and bledy == [3]
    assert w._con is None


def test_osie_porzadkow_w_trybie_watkow_czytaja_baze_przy_pokazaniu(qapp, tmp_path, monkeypatch):
    """AR-175: w trybie wątków osie teleskopu i obiektu nie czytają bazy w montażu (zmierzone ~0,3 s
    i ~0,64 s na kopii pf4); pierwsze pokazanie podstrony czyta ją. Widok samodzielny - jak dotąd, od
    razu.
    Mutanty: `TasksView` bez `leniwie` (odczyt w montażu); `showEvent` bez odczytu (pusta tabela)."""
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    odczyty = []
    prawdziwy = queries.active_telescopes
    monkeypatch.setattr(queries, "active_telescopes", lambda con: odczyty.append(1) or prawdziwy(con))
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        os_tel = win.axis_view
        assert odczyty == [] and os_tel._nieaktualny and os_tel.table.rowCount() == 0
        assert win.object_view._nieaktualny and win.object_view.review.count() == 0   # oś obiektu też
        win.resize(1200, 800)
        win.show()
        win._show_view(NAV_PORZADKI)
        win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_TELESCOPE)
        _czekaj_na(lambda: odczyty, "pokazanie osi nie przeczytało bazy")
        assert not os_tel._nieaktualny and os_tel.table.rowCount() > 0
    finally:
        win.close()
    con = db.connect(_seeded_db(tmp_path, "samodzielny.db", object_axis=True))
    try:
        sam = TelescopeAxisView(con)
        assert not sam._nieaktualny and sam.table.rowCount() > 0
    finally:
        con.close()


# ---- zmiana motywu: kolory wypalone z roli rodzaju, bez rachunku stanu bazy (AR-175) ----

@pytest.mark.zmienia_motyw
def test_zmiana_motywu_bez_rachunku_stanu_bazy_na_watku_GUI(qapp, tmp_path, monkeypatch):
    """AR-175: `_on_theme` liczył CAŁY rachunek liczników Porządków i kolejkę osi obiektu na wątku GUI
    tylko po to, żeby wypalić nową szarość (1,8-3,0 s na kopii pf4). Teraz przemalowuje elementy z roli
    rodzaju koloru - zero odczytów stanu, także osi teleskopu (`refresh` czyta trzy zapytania).
    Mutanty: `refresh_counts()` / `_load_review()` / `axis_view.refresh()` w `_on_theme`."""
    from horreum.gui import theme
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        wolania = []
        for nazwa in ("tasks_state", "review_queue", "active_telescopes", "optics_from_files",
                      "open_telescope_adds"):
            prawdziwa = getattr(queries, nazwa)
            monkeypatch.setattr(queries, nazwa,
                                lambda *a, _n=nazwa, _p=prawdziwa, **k: wolania.append(_n) or _p(*a, **k))
        win._theme_actions["light"].trigger()
        win._theme_actions["dark"].trigger()
        assert wolania == []
        assert win.planner_view.model._dim == QColor(theme.accents("dark")["secondary_text"])
    finally:
        win.close()


@pytest.mark.zmienia_motyw
def test_zmiana_motywu_przemalowuje_kazdy_rodzaj_wiersza_Porzadkow(qapp, tmp_path):
    """AR-175 (rola rodzaju koloru): żywy i „?” w kolorze tekstu, zero i historia - szarością motywu,
    po ciemny → jasny → ciemny. `rows.STRONG` tego nie odróżnia („?” i zero mają je oba `False`).
    Mutant: przemalowanie z `rows.STRONG` - „?” szarzeje."""
    from PySide6.QtGui import QBrush
    from horreum.gui import tasks as tasks_mod, theme
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = win.tasks_view
        stan, _k = tasks_mod._stan_licznikow(win.con)
        stan = dict(stan, unresolved_lights=3, copy_conflict_frames=0, superseded_frames=5,
                    dup_frames=0)
        tasks._przyloz_liczniki(stan, [{"hdr_hash": None, "hdr_rule": None}])
        oczekiwane = {"unresolved_lights": None, "copy_conflict_frames": None,
                      "superseded_frames": "secondary_text", "dup_frames": "secondary_text"}
        for motyw in ("dark", "light", "dark"):
            win._on_theme(motyw)
            for klucz, rola in oczekiwane.items():
                pedzel = _task_item(win, klucz).foreground()
                if rola is None:
                    assert pedzel == QBrush(), (motyw, klucz)
                else:
                    assert pedzel.color() == QColor(theme.accents(motyw)[rola]), (motyw, klucz)
    finally:
        win.close()


@pytest.mark.zmienia_motyw
def test_zmiana_motywu_przemalowuje_kolejke_osi_obiektu_i_optyke_osi_teleskopu(qapp, tmp_path):
    """AR-175: wiersze informacyjne kolejki przeglądu (szarość) i komórka optyki z ręki osi teleskopu
    (kolor werdyktu) idą za motywem w obie strony. Oś teleskopu dotąd zostawała w kolorze motywu
    poprzedniego (~1,9:1 na białej bazie) do najbliższego `refresh`.
    Mutanty: `_on_theme` bez osi teleskopu; `odswiez_motyw` osi obiektu bez wierszy informacyjnych."""
    from horreum.gui import theme
    from horreum.gui.app import COL_FOCAL, ROLA_RODZAJU_KOLORU
    sciezka = _seeded_db(tmp_path, object_axis=True)
    con = db.connect(sciezka)
    tid = con.execute("SELECT id FROM telescope ORDER BY id LIMIT 1").fetchone()[0]
    repo.set_telescope_focal(con, telescope_id=tid, focal_mm=1234.0, now=NOW)
    con.close()
    win = MainWindow(sciezka)

    def _kolory(rodzaj):
        kolejka, tabela = win.object_view.review, win.axis_view.table
        info = {kolejka.item(i).foreground().color().name() for i in range(kolejka.count())
                if kolejka.item(i).data(ROLA_RODZAJU_KOLORU) == rodzaj}
        reka = {tabela.item(r, COL_FOCAL).foreground().color().name()
                for r in range(tabela.rowCount())
                if tabela.item(r, COL_FOCAL).data(ROLA_RODZAJU_KOLORU) == rodzaj}
        return info, reka
    try:
        assert _kolory("szary")[0] and _kolory("werdykt")[1]
        for motyw in ("light", "dark", "light"):
            win._on_theme(motyw)
            a = theme.accents(motyw)
            assert _kolory("szary")[0] == {QColor(a["secondary_text"]).name()}, motyw
            assert _kolory("werdykt")[1] == {QColor(a["warn"]).name()}, motyw
    finally:
        win._on_theme(theme.DEFAULT)       # przed `close` - zamknięte okno ma zamknięte połączenie
        win.close()


@pytest.mark.zmienia_motyw
def test_zmiana_motywu_nie_zapisuje_werdyktu_optyki_osi_teleskopu(qapp, tmp_path, monkeypatch):
    """AR-175: `odswiez_motyw` osi teleskopu przemalowuje komórki optyki - `setForeground` emituje
    `itemChanged`, a ten w komórce optyki ZAPISUJE werdykt ręki (`_on_item_changed` → `_on_optics_edited`).
    Komórka ręki i komórka „nieaktualne” (kolumna automatu inna niż moda plików): zmiana motywu tam
    i z powrotem - zero zapisów optyki, zero odczytów osi, zero komunikatów, zdarzeń `telescope.*_user_set`
    tyle samo, kolory z motywu. Mutant: `odswiez_motyw` bez `_loading` RAZEM z podpięciem `itemChanged` zamiast
    filtra ról `dataChanged` (AR-326 - każda z dwóch straży sama trzyma test zielonym; filtr pinuje
    `test_gui_optyka_teleskopu.py::test_przemalowanie_komorki_optyki_poza_straza_nie_zapisuje_reki`)."""
    from horreum.gui import theme
    from horreum.gui.app import COL_FOCAL, ROLA_RODZAJU_KOLORU
    sciezka = _seeded_db(tmp_path, object_axis=True)
    con = db.connect(sciezka)
    repo.set_telescope_focal(con, telescope_id=1, focal_mm=1234.0, now=NOW)
    con.close()
    prawdziwe = queries.optics_from_files

    def _pliki(c):                                  # teleskop 2: moda plików 800 mm, kolumna 794 mm
        out = dict(prawdziwe(c))
        from horreum.grouper import FilesOptics
        out[2] = FilesOptics(focal=800.0, focal_n=3, f_ratio=None, f_ratio_n=0, lights=3,
                                     lights_without_focal=0)
        return out
    monkeypatch.setattr(queries, "optics_from_files", _pliki)
    win = MainWindow(sciezka)
    tabela = win.axis_view.table

    def _rodzaje():
        return {tabela.item(r, COL_FOCAL).data(ROLA_RODZAJU_KOLORU): tabela.item(r, COL_FOCAL)
                for r in range(tabela.rowCount())}

    def _zdarzenia():
        return win.con.execute("SELECT count(*) FROM event WHERE verb LIKE 'telescope.%_user_set'"
                               ).fetchone()[0]
    try:
        assert {"werdykt", "szary"} <= set(_rodzaje())
        przed = _zdarzenia()
        wolania, komunikaty = [], []
        for modul, nazwa in ((repo, "set_telescope_focal"), (repo, "set_telescope_f_ratio"),
                             (queries, "active_telescopes")):
            p = getattr(modul, nazwa)
            monkeypatch.setattr(modul, nazwa,
                                lambda *a, _n=nazwa, _p=p, **k: wolania.append(_n) or _p(*a, **k))
        win.axis_view.status_message.connect(komunikaty.append)
        for motyw in ("light", "dark"):
            win._on_theme(motyw)
            a = theme.accents(motyw)
            r = _rodzaje()
            assert r["werdykt"].foreground().color() == QColor(a["warn"]), motyw
            assert r["szary"].foreground().color() == QColor(a["secondary_text"]), motyw
        assert wolania == [] and komunikaty == [] and _zdarzenia() == przed
    finally:
        win._on_theme(theme.DEFAULT)
        win.close()


def test_powrot_z_podstrony_osi_bez_zmian_nie_liczy_Porzadkow(qapp, tmp_path, monkeypatch):
    """AR-175: „← Porządki” z podstrony idzie drogą wejścia (`odswiez_przy_wejsciu`) - bez rachunku, gdy
    odcisk bazy się nie zmienił (rachunek ~0,76 s na kopii pf4). Mutant: `_on_back` z `refresh_counts()`."""
    from horreum.gui import tasks as tasks_mod
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = win.tasks_view
        wolania = []
        prawdziwy = tasks_mod._stan_licznikow
        monkeypatch.setattr(tasks_mod, "_stan_licznikow",
                            lambda con: wolania.append(1) or prawdziwy(con))
        tasks.pages.setCurrentIndex(tasks_mod._PAGE_TELESCOPE)
        tasks._on_back()
        assert tasks.pages.currentIndex() == tasks_mod._PAGE_LIST and wolania == []
    finally:
        win.close()


def test_wejscie_z_wiersza_czyta_os_teleskopu_raz(qapp, tmp_path, monkeypatch):
    """AR-175: oś leniwa, wejście z wiersza Porządków (`otworz_os_teleskopu`: `refresh`, potem pokazanie
    podstrony) czyta bazę RAZ - `refresh` zdejmuje znacznik odłożonego odczytu, więc `showEvent` nie czyta
    drugi raz. Mutant: `refresh` bez zdjęcia znacznika (dwa odczyty)."""
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.resize(1200, 800)
        win.show()
        win._show_view(NAV_PORZADKI)
        _pompuj()
        odczyty = []
        prawdziwy = queries.optics_from_files
        monkeypatch.setattr(queries, "optics_from_files", lambda c: odczyty.append(1) or prawdziwy(c))
        win.tasks_view.otworz_os_teleskopu()
        for _ in range(5):
            _pompuj()
        assert win.tasks_view.pages.currentIndex() == tasks_mod._PAGE_TELESCOPE
        assert odczyty == [1], odczyty
    finally:
        win.close()


def test_TasksView_samodzielny_czyta_osie_od_razu(qapp, tmp_path):
    """AR-175: domyślne `TasksView(leniwie=False)` - widok samodzielny (testy, okno osi) czyta osie
    w konstruktorze, jak przed zmianą. Mutant: domyślne `leniwie=True`."""
    from horreum.gui.tasks import TasksView
    con = db.connect(_seeded_db(tmp_path, object_axis=True))
    try:
        tv = TasksView(con)
        assert not tv.axis_view._nieaktualny and tv.axis_view.table.rowCount() > 0
        assert not tv.object_view._nieaktualny and tv.object_view.review.count() > 0
        tv.zatrzymaj_pola()
    finally:
        con.close()


@pytest.mark.zmienia_motyw
def test_apply_theme_bez_stylu_zmienia_palete_i_arkusz(qapp, monkeypatch):
    """AR-175: `_on_theme` woła `apply_theme(styl=False)` - Fusion stoi od `main`, a ponowne `setStyle`
    to zdarzenie stylu do każdego widżetu. Paleta i arkusz motywu MUSZĄ się zmienić mimo to.
    Mutant: `styl=False` pomija też paletę albo arkusz."""
    from horreum.gui import app as app_mod, theme
    style = []
    monkeypatch.setattr(type(qapp), "setStyle", lambda self, *a: style.append(a))
    app_mod.apply_theme(qapp, "light", styl=False)
    assert style == []
    assert qapp.styleSheet() == theme.qss("light")
    assert qapp.palette().color(app_mod.QPalette.Window) == QColor(theme.palette_spec("light")["window"])
    app_mod.apply_theme(qapp, "dark", styl=False)
    assert qapp.styleSheet() == theme.qss("dark")
    assert qapp.palette().color(app_mod.QPalette.Window) == QColor(theme.palette_spec("dark")["window"])
    app_mod.apply_theme(qapp, "dark")
    assert len(style) == 1, "pełne `apply_theme` (start w `main`) stawia styl jak dotąd"


def test_klik_odlozony_przepada_z_porazka_rachunku(qapp, tmp_path, monkeypatch):
    """AR-175: klik w wygaszony wiersz przed pierwszym rachunkiem czeka na wynik - ale gdy rachunek
    padnie (druga porażka serii), klik przepada razem z nim. Następny UDANY rachunek nie otwiera
    perspektywy sam, bez gestu.
    Mutant: porażka nie czyści odłożonego kliku - perspektywa otwiera się po kolejnym rachunku."""
    import sqlite3
    from PySide6.QtTest import QTest
    from horreum.gui import tasks as tasks_mod
    prawdziwy = tasks_mod._stan_licznikow
    _w_tle(monkeypatch)
    brama, wszedl, _watki, _glowny = _brama_rachunku(
        monkeypatch, pada=sqlite3.OperationalError("database is locked"))
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        win.resize(1200, 800)
        win.show()
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        win._show_view(NAV_PORZADKI)
        tasks = win.tasks_view
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        it = _task_item(win, "dup_frames")
        rect = tasks.tasks.visualItemRect(it)
        QTest.mouseClick(tasks.tasks.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        _pompuj()
        brama.set()
        _czekaj_na(lambda: tasks._liczniki_thread is None and not tasks.blad_licznikow.isHidden(),
                   "seria rachunku nie padła")
        assert otwarte == []
        monkeypatch.setattr(tasks_mod, "_stan_licznikow", prawdziwy)
        tasks.refresh_counts(w_tle=True)
        _po_rachunku(win)
        assert otwarte == [], "klik sprzed porażki odpalił się sam przy następnym rachunku"
        assert tasks.pages.currentIndex() == 0
    finally:
        brama.set()
        win.close()


# ======================================================================== AR-326: osie leniwe osobnym przełącznikiem

@pytest.mark.zmienia_motyw
def test_osie_leniwe_bez_watkow_tla_czytaja_baze_przy_wejsciu(qapp, tmp_path, monkeypatch):
    """AR-326: `_osie_leniwie` jest osobnym przełącznikiem - w trybie BEZ wątków tła (`_pola_poza_watkiem=False`)
    osie mogą być leniwe: montaż ich nie czyta, klik w wiersz „Teleskopy bez etykiety” (prawdziwy `mouseClick`)
    czyta oś teleskopu, a zmiana motywu przemalowuje wczytaną oś bez zapisu werdyktu ręki.
    Falsyfikator: `TasksView(..., leniwie=self._pola_poza_watkiem)` (stan sprzed AR-326 - oś czyta w montażu)."""
    from PySide6.QtTest import QTest
    from horreum.gui import theme
    monkeypatch.setattr(MainWindow, "_osie_leniwie", True)
    sciezka = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(sciezka)
    try:
        os_tel = win.axis_view
        assert os_tel._nieaktualny and os_tel.table.rowCount() == 0
        assert win.object_view._nieaktualny
        win.resize(1200, 800)
        win.show()
        win._show_view(NAV_PORZADKI)
        tasks = win.tasks_view
        rect = tasks.tasks.visualItemRect(_task_item(win, "telescopes_unlabeled"))
        QTest.mouseClick(tasks.tasks.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        _pompuj()
        assert not os_tel._nieaktualny and os_tel.table.rowCount() > 0
        przed = win.con.execute("SELECT count(*) FROM event WHERE verb LIKE 'telescope.%_user_%'").fetchone()[0]
        for motyw in ("light", "dark"):
            win._on_theme(motyw)
        assert win.con.execute("SELECT count(*) FROM event WHERE verb LIKE 'telescope.%_user_%'"
                               ).fetchone()[0] == przed
    finally:
        win._on_theme(theme.DEFAULT)
        win.close()


# ======================================================================== AR-327: raport paska bez cichego ucięcia

def test_dlugi_raport_po_krotkim_ma_szerokosc_etykiety_od_razu(qapp, tmp_path):
    """AR-327 („Baza: …” ucięte bez wielokropka tuż po otwarciu): zaraz po `_flash`, BEZ
    obrotu pętli zdarzeń, etykieta raportu mieści swój tekst albo tekst kończy się wielokropkiem - układ paska
    przeliczony przed malowaniem. Zmierzone natywnie przed zmianą: 259 px etykiety przy 626 px tekstu do
    pierwszego `processEvents`. Kontrakt geometryczny bez pikseli (pierwszą klatkę mierzy sonda natywna).
    Falsyfikator: `_wyswietl` bez `layout().activate()`."""
    from PySide6.QtGui import QFontMetrics
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win.resize(1600, 800)
        win.show()
        _pompuj()
        win._flash("krótko", gest=False)
        _pompuj()
        # Zdanie dłuższe od poprzedniego, ale mieszczące się w pasku - bez elizji (zdanie za długie kończyłoby
        # się wielokropkiem i test nie mierzyłby szerokości etykiety).
        win._flash("Baza: X:\\katalog\\podkatalog\\pf4.db", gest=False)
        rl = win.report_label
        tekst = rl.text()
        szerokosc = QFontMetrics(rl.font()).horizontalAdvance(tekst)
        assert not tekst.endswith("…") and szerokosc < win.statusBar().width() // 2, "test nie mierzy etykiety"
        assert rl.width() >= szerokosc, (rl.width(), szerokosc)
    finally:
        win.close()


# ═════════════ AR-337: wejście i powrót liczą w tle, lista nieaktualna do wyniku, klik odłożony w wizycie listy

def _zapis_drugim_polaczeniem(path):
    """Zapis zatwierdzony z DRUGIEGO połączenia (jak worker Dostawy albo CLI): pierwsza klatka bez obiektu dostaje
    obiekt - odcisk bazy okna się zmienia, a liczba „Klatek bez obiektu” spada o 1."""
    con = db.connect(path)
    try:
        fid = con.execute(
            "SELECT id FROM frame WHERE object_id IS NULL AND kind = 'light' ORDER BY id LIMIT 1").fetchone()[0]
        repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC", kind="deep_sky",
                                frame_ids=[fid], now=NOW)
    finally:
        con.close()


def _klik_nav(win, wiersz, *, pompuj=True):
    """Prawdziwy klik w wiersz sidebara (`QTest.mouseClick`) - wejście gospodarza `_on_nav_changed`."""
    from PySide6.QtTest import QTest
    rect = win.nav.visualItemRect(win.nav.item(wiersz))
    QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    if pompuj:
        _pompuj()


def _klik_wiersz(win, klucz):
    """Prawdziwy klik w wiersz listy Porządków."""
    from PySide6.QtTest import QTest
    lista = win.tasks_view.tasks
    rect = lista.visualItemRect(_task_item(win, klucz))
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    _pompuj()


def _wiersze_akcyjne(win):
    from horreum.gui import tasks as tasks_mod
    return [win.tasks_view.tasks.item(r) for r, (_k, _l, akcja) in enumerate(tasks_mod._TASKS) if akcja is not None]


def _lista_nieaktualna(win):
    """Wygląd montażu (AR-175) na każdym wierszu akcyjnym: wygaszony, z podpowiedzią „liczę”, bez liczby i bez pędzla
    koloru (szarość „nic do zrobienia” przeszłaby przez wygaszenie)."""
    from horreum.gui import i18n, rows
    return all(not it.flags() & Qt.ItemIsEnabled and it.data(rows.SECONDARY) is None
               and it.data(Qt.ForegroundRole) is None and it.toolTip() == i18n.t("busy.counting_tasks")
               for it in _wiersze_akcyjne(win))


def _lista_czynna(win):
    return all(it.flags() & Qt.ItemIsEnabled for it in _wiersze_akcyjne(win))


def _okno_po_montazu(win):
    """Okno pokazane, rachunek montażu przyłożony, jedno wejście w Porządki (skrót - baza bez zmian) i powrót na Dom."""
    win.resize(1200, 800)
    win.show()
    _po_rachunku(win)
    tasks = win.tasks_view
    _klik_nav(win, NAV_PORZADKI)
    _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista po pierwszym wejściu")
    _klik_nav(win, NAV_DOM)
    return tasks


def _po_wyniku(tasks):
    return tasks._liczniki_thread is None and tasks._odcisk_licznikow == queries.odcisk_bazy(tasks.con)


def test_wejscie_po_zapisie_liczy_w_tle_lista_nieaktualna_klik_po_wyniku(qapp, tmp_path, monkeypatch):
    """AR-337 (rachunek wejścia w tle): wejście w Porządki po zapisie drugim połączeniem liczyło synchronicznie - okno
    stało (natywnie 825-1091 ms na kopii pf4 v47). Teraz rachunek idzie w tle, a lista do wyniku wygląda jak przed
    pierwszym rachunkiem (AR-175): wiersze akcyjne wygaszone z podpowiedzią „liczę”, kolumna liczb pusta, bez pędzla
    koloru, faza przy tytule. Prawdziwy klik w wiersz w tym czasie czeka i wykonuje się po wyniku na świeżej liście.
    Wynik zdejmuje stan nieaktualny: następny bieg gestu (AR-84) trzyma listę czynną, bez fazy przy tytule.
    Mutanty: wejście bez gałęzi `w_tle` (rachunek na wątku GUI); gospodarz bez `w_tle=`; wygaszenie bez zdjęcia
    liczby; bez zdjęcia `ForegroundRole`; wynik bez wykonania kliku odłożonego; `_przyloz_liczniki` bez
    `_nieaktualny = False`."""
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        przed = _task_row(win, "unresolved_lights")
        brama, wszedl, watki, glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        _klik_nav(win, NAV_PORZADKI)
        assert glowny not in watki, "wejście liczyło na wątku GUI"
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S), "rachunek wejścia nie ruszył w tle"
        assert _lista_nieaktualna(win)
        assert tasks.faza_licznikow.isVisible()
        _klik_wiersz(win, "dup_frames")
        assert otwarte == [] and tasks.pages.currentIndex() == 0
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek wejścia nie przyłożony")
        _pompuj()
        assert _task_row(win, "unresolved_lights") != przed, "lista mówi o stanie po zapisie"
        assert tasks.faza_licznikow.isHidden()
        assert otwarte == [PRESET_DUPS], "klik czekający wykonany na świeżej liście"
        assert glowny not in watki
        # Klik przełączył okno na Zbiory - stan fazy czytany z flagi widżetu (`isHidden`), nie z widoczności strony.
        brama.clear()
        wszedl.clear()
        tasks.refresh_counts(w_tle=True)                 # gest Zbiorów (AR-84) przy liście po wyniku wejścia
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        assert _lista_czynna(win) and tasks.faza_licznikow.isHidden(), "wynik nie zdjął stanu nieaktualnego"
        brama.set()
        _czekaj_na(lambda: tasks._liczniki_thread is None, "bieg gestu nie skończył")
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_powrot_z_podstrony_po_zapisie_liczy_w_tle(qapp, tmp_path, monkeypatch):
    """AR-337 (rachunek wejścia w tle): „← Porządki” idzie drogą wejścia TYM SAMYM trybem co wejście gospodarza
    (`_wejscie_w_tle`) - po zapisie w trakcie pracy w podstronie liczy w tle z listą nieaktualną (prawdziwy klik
    przycisku powrotu).
    Mutant: `_on_back` bez trybu wejścia (rachunek na wątku GUI)."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from horreum.gui import i18n, tasks as tasks_mod
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        _klik_wiersz(win, "telescopes_unlabeled")
        assert tasks.pages.currentIndex() == tasks_mod._PAGE_TELESCOPE
        brama, wszedl, watki, glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        wstecz = next(b for b in tasks.pages.currentWidget().findChildren(QPushButton)
                      if b.text() == i18n.t("tasks.back"))
        QTest.mouseClick(wstecz, Qt.LeftButton)
        _pompuj()
        assert tasks.pages.currentIndex() == tasks_mod._PAGE_LIST
        assert glowny not in watki, "powrót liczył na wątku GUI"
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        assert _lista_nieaktualna(win) and tasks.faza_licznikow.isVisible()
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek powrotu nie przyłożony")
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_wejscie_w_trakcie_biegu_gestu_gasi_stare_liczby(qapp, tmp_path, monkeypatch):
    """AR-337 (gałąź „bieg w drodze”): gest Zbiorów po zapisie liczy w tle, a lista trzyma stan poprzedni (AR-84).
    Wejście w Porządki w trakcie tego biegu na tym samym stanie bazy czekało na jego wynik, pokazując stare liczby
    jako czynne, bez znaku. Teraz czeka z listą nieaktualną; wynik zapala ją z liczbami po zapisie. Zapis PRZED
    biegiem - inaczej wejście skróciłoby po niezmienionym odcisku i nie doszło do gałęzi. Do końca - jeden rachunek
    (wejście nie zamawia drugiego biegu).
    Mutanty: gałąź „bieg w drodze” bez `_wygas_wiersze`; bez całej gałęzi „bieg w drodze”; `_start_licznikow` bez
    `_bieg_czeka_na_wynik = True` (wejście nie rozpoznaje biegu w drodze)."""
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        przed = _task_row(win, "unresolved_lights")
        brama, wszedl, watki, glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        tasks.refresh_counts(w_tle=True)                 # gest Zbiorów (AR-84) - bieg w drodze na stanie po zapisie
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        assert _task_row(win, "unresolved_lights") == przed and _lista_czynna(win), "gest nie gasi listy (AR-84)"
        _klik_nav(win, NAV_PORZADKI)
        assert _lista_nieaktualna(win) and tasks.faza_licznikow.isVisible()
        assert glowny not in watki and len(watki) == 1, "wejście czeka na bieg w drodze, nie liczy drugi raz"
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "wynik biegu gestu nie przyłożony")
        _pompuj()
        assert _task_row(win, "unresolved_lights") != przed
        assert len(watki) == 1, "wejście w trakcie biegu policzyło drugi raz"
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_wejscie_po_drugiej_porazce_przed_sprzataniem_watku_nie_zostawia_listy_wygaszonej(qapp, tmp_path,
                                                                                          monkeypatch):
    """AR-337: po obsłużonej drugiej porażce biegu w tle wątek żyje jeszcze do `_sprzataj_liczniki`. Wejście w tej
    przerwie nie może czekać na „bieg w drodze” - ten już nic nie przyniesie, a lista zostałaby wygaszona na zawsze,
    bez rachunku i bez zdania błędu. Kolejność wymuszona: sprzątanie wątku (zdarzenie kolejki zaraz po porażce) najpierw
    wchodzi w Porządki prawdziwym klikiem, potem sprząta. Wynik: lista czynna ze stanem poprzednim i zdaniem błędu.
    Mutant: gałąź „bieg w drodze” bez `_bieg_czeka_na_wynik`."""
    import sqlite3
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        przed = _task_row(win, "unresolved_lights")
        brama, _wszedl, _watki, _glowny = _brama_rachunku(
            monkeypatch, pada=sqlite3.OperationalError("database is locked"))
        brama.set()
        prawdziwe = tasks_mod.TasksView._sprzataj_liczniki
        wejscia = []

        def _sprzataj(self):
            if not wejscia and not self.blad_licznikow.isHidden():
                wejscia.append(1)
                _klik_nav(win, NAV_PORZADKI, pompuj=False)    # druga porażka obsłużona, wątek jeszcze żyje
            prawdziwe(self)
        monkeypatch.setattr(tasks_mod.TasksView, "_sprzataj_liczniki", _sprzataj)
        _zapis_drugim_polaczeniem(path)
        tasks.refresh_counts(w_tle=True)                 # gest po zapisie - bieg pada dwa razy (ponowienie, AR-302)
        _czekaj_na(lambda: wejscia and tasks._liczniki_thread is None and not tasks._liczniki_ponow,
                   "seria po wejściu nie skończyła")
        _pompuj()
        assert _lista_czynna(win), "lista wygaszona bez rachunku"
        assert not tasks.blad_licznikow.isHidden(), "seria po wejściu skończyła się bez zdania"
        assert _task_row(win, "unresolved_lights") == przed, "stan poprzedni wrócił"
        assert not tasks.faza_licznikow.isVisible()
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_wejscie_po_porazce_chowa_wiersz_bledu_i_pokazuje_faze(qapp, tmp_path, monkeypatch):
    """AR-337: wejście po porażce rachunku (wiersz błędu nad listą ze stanem poprzednim) liczy od nowa w tle - lista
    nieaktualna chowa wiersz błędu poprzedniej porażki i pokazuje fazę przy tytule; inaczej obok siebie stałyby
    zdanie „nie policzyłem” i lista wygaszona, a faza czekałaby na schowanie wiersza błędu. Wynik zapala listę bez
    błędu. Mutant: `_wygas_wiersze` bez schowania wiersza błędu."""
    import sqlite3
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    bramy = []
    try:
        tasks = _okno_po_montazu(win)
        prawdziwy = tasks_mod._stan_licznikow
        brama_pada, _w, _wt, _g = _brama_rachunku(monkeypatch, pada=sqlite3.OperationalError("database is locked"))
        bramy.append(brama_pada)
        brama_pada.set()
        tasks.refresh_counts(w_tle=True)                 # gest Zbiorów - bieg pada dwa razy (ponowienie, AR-302)
        _czekaj_na(lambda: tasks._liczniki_thread is None and not tasks.blad_licznikow.isHidden(),
                   "bieg gestu nie padł")
        monkeypatch.setattr(tasks_mod, "_stan_licznikow", prawdziwy)
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        bramy.append(brama)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        assert tasks.blad_licznikow.isHidden(), "wiersz błędu poprzedniej porażki obok listy nieaktualnej"
        assert tasks.faza_licznikow.isVisible() and _lista_nieaktualna(win)
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek wejścia nie przyłożony")
        assert tasks.blad_licznikow.isHidden() and not tasks.faza_licznikow.isVisible()
    finally:
        for b in bramy:
            b.set()
        win.close()


def test_klik_odlozony_przepada_z_koncem_wizyty_listy(qapp, tmp_path, monkeypatch):
    """AR-337: klik w wiersz wygaszony czeka na wynik - ale tylko w TEJ wizycie listy. Klik → Dom →
    powrót do Porządków → wynik otwierał cel kliku w nowej wizycie, bez gestu. Prawdziwe kliknięcia.
    Mutant: wejście bez skasowania kliku odłożonego."""
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S) and _lista_nieaktualna(win)
        _klik_wiersz(win, "dup_frames")
        _klik_nav(win, NAV_DOM)
        _klik_nav(win, NAV_PORZADKI)
        assert _lista_nieaktualna(win)
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek wejścia nie przyłożony")
        _pompuj()
        assert otwarte == [] and tasks.pages.currentIndex() == 0, "klik z poprzedniej wizyty wykonany"
        assert win.stack.currentIndex() == STRONA_PORZADKI
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_porazka_rachunku_wejscia_wraca_do_stanu_poprzedniego(qapp, tmp_path, monkeypatch):
    """AR-337 (porażka rachunku wejścia): rachunek pada dwa razy (ponowienie w tle, AR-302) - lista NIEAKTUALNA wraca
    do stanu POPRZEDNIEGO: liczby ostatniego przyłożonego rachunku, wiersze czynne, zdanie błędu nad listą, plakietka
    bez zmian; klik odłożony przepada (nic się nie otwiera ani teraz, ani po następnym udanym rachunku).
    Mutanty: `_pokaz_blad_licznikow` bez `_przyloz_liczniki(*self._ostatni_stan)` (liczby puste); kasowanie kliku
    w `_pokaz_blad_licznikow` (jedyne miejsce, obie drogi porażki) zdjęte - przywrócenie wykonuje klik od razu."""
    import sqlite3
    from horreum.gui import tasks as tasks_mod
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        przed = _task_row(win, "unresolved_lights")
        plakietka = win.nav.item(NAV_PORZADKI).text()
        prawdziwy = tasks_mod._stan_licznikow
        brama, wszedl, _watki, _glowny = _brama_rachunku(
            monkeypatch, pada=sqlite3.OperationalError("database is locked"))
        _zapis_drugim_polaczeniem(path)
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S) and _lista_nieaktualna(win)
        _klik_wiersz(win, "dup_frames")
        brama.set()
        _czekaj_na(lambda: tasks._liczniki_thread is None and not tasks.blad_licznikow.isHidden(),
                   "seria rachunku wejścia nie padła")
        _pompuj()
        assert tasks.blad_licznikow.text()
        assert _task_row(win, "unresolved_lights") == przed and _lista_czynna(win)
        assert not tasks.faza_licznikow.isVisible()
        assert win.nav.item(NAV_PORZADKI).text() == plakietka
        assert otwarte == []
        monkeypatch.setattr(tasks_mod, "_stan_licznikow", prawdziwy)
        tasks.refresh_counts(w_tle=True)
        _czekaj_na(lambda: _po_wyniku(tasks), "następny rachunek nie przyłożony")
        _pompuj()
        assert otwarte == [], "klik sprzed porażki odpalił się sam przy następnym rachunku"
        assert _task_row(win, "unresolved_lights") != przed and tasks.blad_licznikow.isHidden()
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_porazka_rachunku_awaryjnego_w_stanie_nieaktualnym_wraca_do_stanu_poprzedniego(qapp, tmp_path, monkeypatch):
    """AR-337 (porażka rachunku wejścia, droga synchroniczna): lista nieaktualna z klikiem odłożonym, a następny bieg
    nie rusza, bo połączenie okna nie czyta odcisku - rachunek awaryjny `refresh_counts` pada na wątku GUI
    (`_start_licznikow`, PRAWDZIWY błąd SQLite: plik nie jest bazą). Ta sama semantyka co porażka w tle: stan
    poprzedni, zdanie klasy błędu, klik przepada. Mutant: kasowanie kliku w `_pokaz_blad_licznikow` zdjęte
    (przywrócenie stanu poprzedniego wykonuje klik)."""
    import sqlite3
    from horreum.gui import i18n
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    smieci = tmp_path / "smieci.db"
    smieci.write_bytes(b"to nie jest baza" * 512)
    zla = sqlite3.connect(str(smieci))
    win = MainWindow(path)
    brama = None
    tasks = None
    prawdziwe = None
    try:
        tasks = _okno_po_montazu(win)
        prawdziwe = tasks.con
        przed = _task_row(win, "unresolved_lights")
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S) and _lista_nieaktualna(win)
        _klik_wiersz(win, "dup_frames")
        tasks.con = zla
        tasks.refresh_counts(w_tle=True)                 # zlecenie w trakcie biegu - bieg po nim, generacja nowsza
        brama.set()                                      # wynik biegu do kosza, następny bieg nie czyta odcisku
        _czekaj_na(lambda: tasks._liczniki_thread is None and not tasks.blad_licznikow.isHidden(),
                   "rachunek awaryjny nie padł")
        _pompuj()
        assert tasks.blad_licznikow.text() == i18n.t(
            "tasks.counts_failed", msg=i18n.t("objchg.item.db_damaged", db_code="SQLITE_NOTADB"))
        assert _task_row(win, "unresolved_lights") == przed and _lista_czynna(win)
        assert otwarte == [], "przywrócenie stanu poprzedniego wykonało klik odłożony"
    finally:
        if tasks is not None and prawdziwe is not None:
            tasks.con = prawdziwe
        if brama is not None:
            brama.set()
        win.close()
        zla.close()


@pytest.mark.zmienia_motyw
def test_zmiana_motywu_w_stanie_nieaktualnym_nie_maluje_szarosci_rodzaju(qapp, tmp_path, monkeypatch):
    """AR-337: lista nieaktualna nie ma rodzaju koloru (`ROLA_RODZAJU_KOLORU` zdjęta razem z liczbą), więc zmiana
    motywu w czasie rachunku (`odswiez_motyw`, AR-175) nie maluje szarości „nic do zrobienia” na wierszach wygaszonych.
    Mutant: wygaszenie bez zdjęcia rodzaju koloru."""
    from horreum.gui import theme
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S) and _lista_nieaktualna(win)
        for motyw in ("light", "dark"):
            win._on_theme(motyw)
            assert _lista_nieaktualna(win), motyw
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek wejścia nie przyłożony")
    finally:
        if brama is not None:
            brama.set()
        win._on_theme(theme.DEFAULT)
        win.close()


def test_rachunek_w_tle_czyta_jedna_migawke(qapp, tmp_path, monkeypatch):
    """AR-337: `_LicznikiWorker` liczy w JEDNEJ migawce (`BEGIN`) - zapis zatwierdzony drugim połączeniem zaraz po
    PIERWSZEJ instrukcji SELECT rachunku (wtrącenie śladem instrukcji połączenia workera, niezależnie od tego, która
    funkcja czyta pierwsza) nie wchodzi do dalszych odczytów TEGO rachunku: ani liczba „Klatek bez obiektu”, ani
    kandydaci faktów kopii czytani na samym końcu (`scan.copy_facts_candidates`). Prawdziwy rachunek, prawdziwe
    połączenia. Bez transakcji każdy SELECT widział swoją chwilę - wiersz i jego podpowiedź z dwóch stanów bazy.
    Mutant: `run` bez `BEGIN`."""
    import sys
    from horreum import scan
    from horreum.gui.tasks import _LicznikiWorker
    path = _seeded_db(tmp_path, object_axis=True)

    def _odczyt():
        con = db.connect(path)
        try:
            return (queries.tasks_state(con)["unresolved_lights"],
                    len(scan.copy_facts_candidates(con, porownywalne=True)))
        finally:
            con.close()
    przed = _odczyt()

    def _zapis():
        _zapis_drugim_polaczeniem(path)                  # „Klatki bez obiektu” - 1
        con = db.connect(path)
        try:
            fid = con.execute("SELECT min(id) FROM frame").fetchone()[0]
            for nazwa in ("kopia_a", "kopia_b"):         # kopie bez faktów klatki o >1 lokacji - kandydaci + 2
                repo.add_location(con, frame_id=fid, volume="V", path=f"X:\\L\\{nazwa}.fits",
                                  header_hash=f"h_{nazwa}", now=NOW)
        finally:
            con.close()

    prawdziwe_connect = db.connect
    selecty = []

    def _slad(sql):
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            selecty.append(sql)
            if len(selecty) == 2:                        # pierwsza instrukcja odczytu już przeszła
                _zapis()

    def _connect(sciezka):
        con = prawdziwe_connect(sciezka)
        if sys._getframe(1).f_code.co_name == "run":     # wyłącznie połączenie workera liczników
            con.set_trace_callback(_slad)
        return con
    monkeypatch.setattr(db, "connect", _connect)
    w = _LicznikiWorker(1, path)
    wyniki, bledy = [], []
    w.done.connect(lambda _gen, wynik: wyniki.append(wynik))
    w.failed.connect(lambda _gen, powod: bledy.append(powod))
    w.run()
    assert len(selecty) > 2 and bledy == [], bledy
    ((stan, kandydaci),) = wyniki
    monkeypatch.setattr(db, "connect", prawdziwe_connect)
    po = _odczyt()
    assert po == (przed[0] - 1, przed[1] + 2), (przed, po)
    assert (stan["unresolved_lights"], len(kandydaci)) == przed, "rachunek po pierwszym odczycie widział cudzy zapis"


@pytest.mark.parametrize("droga", ["wynik", "wyjatek", "przerwanie"])
def test_migawka_rachunku_w_tle_zwolniona_kazda_droga(qapp, tmp_path, monkeypatch, droga):
    """AR-337: migawka rachunku w tle wstrzymuje checkpoint WAL ponad siebie, więc musi zniknąć KAŻDĄ drogą końca
    biegu: wynik, wyjątek w rachunku, przerwanie zapytania w locie (`request_cancel` z innego wątku). Dowód z zewnątrz:
    zapis drugim połączeniem w trakcie rachunku, a po końcu biegu `wal_checkpoint(TRUNCATE)` połączenia bez
    `busy_timeout` przechodzi bez `busy`. Mutant: połączenie workera niezamykane (`finally` bez `close`)."""
    import sqlite3
    import threading
    from horreum import resolver
    from horreum.gui.tasks import _LicznikiWorker
    path = _seeded_db(tmp_path, object_axis=True)
    prawdziwe = resolver.nonprintable_unread_locations
    w = _LicznikiWorker(1, path)

    def _wtracenie(c):
        wynik = prawdziwe(c)
        _zapis_drugim_polaczeniem(path)
        if droga == "wyjatek":
            raise RuntimeError("rachunek padł")
        if droga == "przerwanie":
            threading.Timer(0.2, w.request_cancel).start()
            c.execute(_ZAPYTANIE_BEZ_KONCA).fetchone()
        return wynik
    monkeypatch.setattr(resolver, "nonprintable_unread_locations", _wtracenie)
    wyniki, bledy = [], []
    w.done.connect(lambda _gen, wynik: wyniki.append(wynik))
    w.failed.connect(lambda _gen, powod: bledy.append(powod))
    w.run()
    assert (len(wyniki), len(bledy)) == ((1, 0) if droga == "wynik" else (0, 1)), (wyniki, bledy)
    surowe = sqlite3.connect(path)
    try:
        busy, _log, _przeniesione = surowe.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        surowe.close()
    assert busy == 0, "migawka rachunku wisi po końcu biegu"


def test_montaz_policzony_synchronicznie_nie_oddaje_serii_montazu_gestowi(qapp, tmp_path, monkeypatch):
    """AR-337 (szew `M` z serią montażu): gdy rachunek montażu w trybie wątków tła policzy się synchronicznie (odcisk
    nieczytelny przy starcie biegu, `_start_licznikow`), pierwsza późniejsza seria w tle (gest Zbiorów, wejście
    w Porządki) była przyjmowana za serię montażu: pasek mówił „Liczę Porządki…” przy geście, a koniec serii stawiał
    drugi raz kotwicę dobudowy Zbiorów. Mutant: `_mount_views` bez `_seria_montazu = 0`."""
    import sqlite3
    import sys
    _w_tle(monkeypatch)
    prawdziwy = queries.odcisk_bazy
    padl = []

    def _odcisk(con):
        if not padl and sys._getframe(1).f_code.co_name == "_start_licznikow":
            padl.append(1)
            raise sqlite3.OperationalError("database is locked")
        return prawdziwy(con)
    monkeypatch.setattr(queries, "odcisk_bazy", _odcisk)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    brama = None
    try:
        tasks = win.tasks_view
        assert padl and tasks.ma_rachunek() and not tasks.liczy_w_tle(), "montaż policzony synchronicznie"
        kotwice = []
        monkeypatch.setattr(win, "_po_licznikach_montazu", lambda: kotwice.append(1))
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        tasks.refresh_counts(w_tle=True)                 # gest Zbiorów - pierwsza seria w tle po montażu
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        _pompuj()
        assert win.phase_label.text() == "", "gest dostał fazę montażu"
        brama.set()
        _czekaj_na(lambda: tasks._liczniki_thread is None, "seria gestu nie skończyła")
        _pompuj()
        assert kotwice == [], "koniec serii gestu postawił kotwicę montażu"
    finally:
        if brama is not None:
            brama.set()
        win.close()
