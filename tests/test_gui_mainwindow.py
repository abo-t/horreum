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


@pytest.fixture(autouse=True)
def _pola_inline(monkeypatch):
    """Pokrycie pól Zbiorów INLINE (seam `MainWindow._pola_poza_watkiem`): testy tego pliku liczą
    odświeżenia i wejścia w `refresh`, a pierwszy wynik z wątku tła, doręczony w nieznanej chwili,
    dokładałby przeładowanie zbioru w środku pomiaru. Drogę produkcyjną (wątek, odcisk kart,
    sprzątanie przy zamknięciu i przełączeniu bazy) sprawdza `test_gui_pola_w_tle.py`."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


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


def test_otwarte_na_bazie_montuje_widoki(qapp, tmp_path):
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert win.stack.count() == 4                  # Dostawa + Zbiory + Porządki (F5) + Planer (T5)
        assert win.nav.count() == 4 and not win.nav.isHidden()
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
        assert win.stack.count() == 4                  # przemontowane 4 miejsca, nie nadmontowane
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


def test_menu_widok_przelacza_motyw(qapp, tmp_path, ustawienia):
    """F6 §7: menu Widok odbija bieżący motyw bez klikania (default ciemny — recenzja #6);
    `_on_theme` podmienia kolory stanów gridu na żywo i utrwala wybór w QSettings (recenzja #7)."""
    from PySide6.QtGui import QColor
    from horreum.gui import grid as grid_mod, theme
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
        assert win.nav.item(NAV_PORZADKI).text() == "Housekeeping (4)"    # nav.porzadki_count EN (app)
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
        assert tasks.height() < 300                        # treść, nie cały pion strony
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
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (4)", "w biegu - jeszcze stary stan"
        win._on_pipeline_running(False)
        assert _task_row(win, "telescopes_unlabeled") == ("Teleskopy bez etykiety", "0  ›")
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (3)"   # klatki + duplikaty + zniknięte
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
    from horreum.gui import pipeline as pipeline_mod

    def _pada(con, now):
        raise RuntimeError("etap padł")
    monkeypatch.setattr(pipeline_mod, "run_grouper", _pada)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        licznik = _licz_przeladowania(win, monkeypatch)
        for row in win.con.execute("SELECT id FROM telescope WHERE merged_into IS NULL").fetchall():
            repo.label_telescope(win.con, telescope_id=row[0], label=f"T{row[0]}", now=NOW)
        etapy = []
        win.pipeline_view.stage_finished.connect(etapy.append)
        _przebieg_w_watku(win, lambda: win.pipeline_view.run_stage("group"))
        assert etapy == [], "etap padł - bez sygnału końca etapu"
        assert "etap padł" in win.pipeline_view.lbl_error.text()
        assert licznik == {"grid": 1, "obiekt": 1}
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (3)", "plakietka ze stanu bazy"
    finally:
        win.close()


def test_wyjatek_w_odswiezeniu_po_przebiegu_gasi_faze(qapp, tmp_path, monkeypatch):
    """Faza „Odświeżam widoki po etapie…" gaśnie KAŻDĄ drogą: wyjątek w odświeżeniu któregoś
    widoku zostawiał ją na pasku, czyli opis roboty, która już się skończyła - do następnej fazy.
    Straż ponownego wejścia też wraca do spoczynku, inaczej kolejny przebieg nie odświeżyłby nic.

    Falsyfikator: wynieś `_end_phase()` z `finally` → asercja o etykiecie fazy pada."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        def _pada():
            raise RuntimeError("odświeżenie padło")
        monkeypatch.setattr(win.grid_view, "refresh", _pada)
        with pytest.raises(RuntimeError, match="odświeżenie padło"):
            win._odswiez_widoki_po_przebiegu()
        assert not win.phase_label.text(), win.phase_label.text()
        assert win._odswiezam_widoki is False
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

        def _refresh():
            stan["glebokosc"] += 1
            stan["wejscia"] += 1
            stan["max"] = max(stan["max"], stan["glebokosc"])
            if stan["wejscia"] == 1:
                win._on_pipeline_running(False)        # prośba doręczona w środku odświeżenia
            oryginal()
            stan["glebokosc"] -= 1
        monkeypatch.setattr(grid, "refresh", _refresh)
        win._on_pipeline_running(False)
        assert stan["max"] == 1, "odświeżenia nie zagnieżdżają się"
        assert stan["wejscia"] == 2, "prośba z środka dała jeden obrót więcej, po bieżącym"
        assert win._odswiezam_widoki is False and not win.phase_label.text()
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
        # klatki bez obiektu + teleskopy + duplikaty + „a plik wrócił" (zniknięte spadły do 0)
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (4)"
        win._show_view(NAV_ZBIORY)
        grid = win.grid_view
        grid.apply_perspective(grid_mod.PRESET_RETIRED_CONFLICT)
        assert grid._frame_ids == [fid]
        grid.table.selectRow(0)
        grid._on_frame_restore()

        assert win.con.execute("SELECT retired_at FROM frame WHERE id = ?",
                               (fid,)).fetchone()[0] is None, "gest się odbył"
        assert win.stack.currentIndex() == NAV_ZBIORY, "Porządków nikt nie otworzył"
        assert win.nav.item(NAV_PORZADKI).text() == "Porządki (3)"
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


def test_zadanie_rodowodu_otwiera_perspektywe(qapp, tmp_path):
    """0808: klik w „Obrazy bez rodowodu" prowadzi do Zbiorów z perspektywą `PRESET_LINEAGE`,
    a grid pokazuje DOKŁADNIE obrazy czekające na gest. Wiersz celuje w perspektywę, nie
    w podstronę, bo gest (potwierdź / odrzuć wejście / wskaż odniesienie) mieszka w panelu
    „Rodowód" TAM — i do tej zmiany dojście do niego wiodło przez przeklikanie archiwum stosów."""
    from horreum.gui.grid import PRESET_LINEAGE
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    try:
        fid = con.execute("SELECT id FROM frame ORDER BY id LIMIT 1").fetchone()[0]
        con.execute("INSERT INTO integration (master_frame_id, created_at, unresolved_reason) "
                    "VALUES (?, '2026-08-08T20:00:00', 'degenerate_window')", (fid,))
        con.commit()
    finally:
        con.close()
    win = MainWindow(path)
    try:
        assert _task_row(win, "stacks_lineage_pending")[0] == "Obrazy bez rodowodu"
        win.tasks_view.tasks.itemClicked.emit(_task_item(win, "stacks_lineage_pending"))
        assert win.stack.currentIndex() == NAV_ZBIORY
        assert win.grid_view._only_lineage is True
        assert win.grid_view.combo_persp.currentData() == ("preset", PRESET_LINEAGE)
        widoczne = set(win.grid_view._frame_ids)          # to, co WIDAĆ po trimie perspektywy
        assert widoczne == queries.lineage_pending_frame_ids(win.con) == {fid}
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

    Falsyfikator: zawróć `_say_phase` na `showMessage` → `currentMessage()` przestanie być pusty
    i raport zniknie."""
    win = MainWindow(_seeded_db(tmp_path))
    try:
        win._say_phase("Czytam bazę…")
        assert win.phase_label.text() == "Czytam bazę…"
        assert win.statusBar().currentMessage() != "Czytam bazę…"   # raport ma własne pole

        win.statusBar().showMessage("Etap Rozwiąż zakończony")
        win._say_phase("Odświeżam widoki po etapie…")
        assert win.statusBar().currentMessage() == "Etap Rozwiąż zakończony"   # faza go NIE zjadła
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
    Ta sama pułapka przewróciła wcześniej sondę pomiarową na platformie natywnej."""
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
        widoczne = win.statusBar().currentMessage()

        assert widoczne != dlugie and len(widoczne) < len(dlugie), "raport nie został przycięty"
        assert widoczne.endswith("…"), f"przycięcie bez znaku - ciche kłamstwo: {widoczne!r}"
        assert win.statusBar().toolTip() == dlugie, "pełna treść przepadła bezpowrotnie"

        # …a zdanie, które się MIEŚCI, zostaje nietknięte - PODPOWIEDŹ ZOSTAJE MIMO TO. Bramka
        # pakietu (obie soczewki) wskazała trzy drogi, którymi treść ginęła przy warunkowym
        # tooltipie: gałąź „za wąsko na elizję", zwężenie okna w trakcie życia komunikatu
        # i recepta przezroczysta dla myszy. Podpowiedź bezwarunkowa zdejmuje wszystkie trzy.
        win._flash("Nazwano 12 z 12 klatek: NGC 7000")
        assert win.statusBar().currentMessage() == "Nazwano 12 z 12 klatek: NGC 7000"
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
        bez_recepty = win.statusBar().currentMessage()

        recepta = "potem przywrócisz: Obiekt → Przywróć cofnięte przypisanie"
        win._pokaz_recepte(recepta)
        assert win.recipe_label.isVisible(), "recepta nie ma nośnika"
        assert "Przywróć cofnięte przypisanie" in win.recipe_label.text()
        assert len(win.statusBar().currentMessage()) < len(bez_recepty), \
            "raport nie oddał miejsca recepcie - przy realnym zdaniu wystawałby pod nią"
        # PODPOWIEDŹ PASKA NIESIE OBA CZŁONY, a recepta nie ma własnej: jest przezroczysta dla
        # myszy (uczciwy „nieklikalny"), więc `QEvent::ToolTip` do niej nie dociera i własna
        # podpowiedź byłaby na niej martwa - bramka pakietu, soczewka repo.
        assert win.statusBar().toolTip() == f"{dlugie} · {recepta}", "pełne zdanie przepadło"
        assert win.recipe_label.toolTip() == "", "martwa podpowiedź udaje spełnioną obietnicę"
    finally:
        win.close()


def test_recepta_NIE_KLIKA_dopoki_niczego_nie_wykonuje(qapp, tmp_path):
    """FH-2, granica wariantu „e". Nośnik jest `QToolButton`em, żeby dopięcie akcji było później
    jedną zmianą - ale DZIŚ nie prowadzi nigdzie, więc nie ma prawa zachowywać się jak przycisk.
    Kontrolka, która podnosi się pod kursorem i nic nie robi, kłamie bardziej niż etykieta.

    Falsyfikator: zdejmij `WA_TransparentForMouseEvents` przed podpięciem akcji → bramka
    czerwienieje i przypomina, że obie połowy wariantu „e" idą razem."""
    from PySide6.QtWidgets import QToolButton
    win = MainWindow(_seeded_db(tmp_path))
    try:
        assert isinstance(win.recipe_label, QToolButton), "nośnik nie jest gotowy pod wariant e"
        assert win.recipe_label.testAttribute(Qt.WA_TransparentForMouseEvents), \
            "przycisk bez akcji ma być nieklikalny"
        assert win.recipe_label.focusPolicy() == Qt.NoFocus, "recepta nie jest przystankiem Taba"
        # …i ma WYGLĄDAĆ na tekst, nie na przycisk. Firsthand zmierzył ramkę 31,31,31 z gradientem
        # 79-81 na kontrolce całkowicie bezwładnej: wypukłość obiecywała klik, którego nie ma.
        assert win.recipe_label.autoRaise(), "recepta rysuje się jako przycisk, którym nie jest"
        # Własność roli byłaby tu MARTWA (selektor motywu to `QLabel[role=…]`), a gdyby ożyła,
        # zeszłaby recepcie do 3,67:1 - poniżej progu 4,5:1. Nie zostawiamy jej naładowanej.
        assert win.recipe_label.property("role") is None, "martwa własność roli czeka na ożywienie"
    finally:
        win.close()


def test_recepta_STOI_PRZY_RAPORCIE_a_faza_przy_uchwycie(qapp, tmp_path):
    """FH-2, kolejność na belce. Widżety stałe idą OD LEWEJ w kolejności dodawania, więc faza
    dodana pierwsza wchodziła MIĘDZY raport a receptę - dwa człony jednego zdania rozdzielone
    komunikatem trzeciej sprawy (firsthand, `K_faza.png`). Recepta ma się kleić do swojego raportu.

    Falsyfikator: zamień kolejność `addPermanentWidget` → recepta odjeżdża na prawo od fazy."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte("przywrócisz: Obiekt → Przywróć cofnięte przypisanie")
        win._say_phase("Odświeżam widoki po etapie…")
        QApplication.processEvents()

        assert win.recipe_label.x() < win.phase_label.x(), \
            "faza rozdziela raport od jego recepty"
    finally:
        win.close()


def test_recepta_GASNIE_razem_ze_swoim_raportem_I_przy_cudzym(qapp, tmp_path):
    """FH-2. Recepta należy do JEDNEGO gestu: zdanie po nim znika po 5 s, a instrukcja powrotu
    wisząca dłużej mówiłaby o czymś, po czym nie ma już śladu na ekranie. Oba wyjścia mają
    właściciela - wygaśnięcie łapie `messageChanged` z pustym łańcuchem, cudzy raport gasi ją
    w `_flash`.

    Falsyfikator: zdejmij `_ustaw_recepte("")` z `_flash` → recepta przeżywa cudzy komunikat."""
    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    try:
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte("przywrócisz: Obiekt → Przywróć cofnięte przypisanie")
        assert win.recipe_label.isVisible()

        win.statusBar().clearMessage()                 # …to samo robi timeout 5 s
        assert not win.recipe_label.isVisible(), "recepta przeżyła swój raport"
        assert win.statusBar().toolTip() == ""

        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte("przywrócisz: Obiekt → Przywróć cofnięte przypisanie")
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
        win.grid_view.status_recipe.emit("przywrócisz: Obiekt → Przywróć cofnięte przypisanie")
        assert win.recipe_label.isVisible()
        assert "Przywróć cofnięte przypisanie" in win.recipe_label.text()
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
    w pozycję, którą nazywa. Otwarty popup jest jedynym dostępnym rozróżnieniem - stan paska mają
    te dwa zdarzenia identyczny.

    Falsyfikator: zdejmij warunek `activePopupWidget()` z `_on_status_changed` → recepta gaśnie
    przy pierwszym dotknięciu menu, choć gest wciąż czeka na dokończenie."""
    from PySide6.QtGui import QStatusTipEvent
    from PySide6.QtWidgets import QMenu

    win = _pokazane(MainWindow(_seeded_db(tmp_path)))
    popup = QMenu(win)
    try:
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte("przywrócisz: Obiekt → Przywróć cofnięte przypisanie")
        assert win.recipe_label.isVisible()

        popup.addAction("Przywróć cofnięte przypisanie")
        popup.popup(win.mapToGlobal(win.rect().center()))
        QApplication.processEvents()
        assert QApplication.activePopupWidget() is not None, "popup się nie otworzył - brak układu"

        QApplication.sendEvent(win, QStatusTipEvent(""))
        QApplication.processEvents()
        assert win.recipe_label.isVisible(), "recepta zgasła w trakcie otwierania własnego menu"

        # …a warunek jest WĄSKI: to samo zdarzenie BEZ otwartego menu gasi receptę jak dawniej.
        # Bez tej połowy bramka przepuściłaby „wyłączmy gaszenie w ogóle", czyli receptę wiszącą
        # nad nieistniejącym raportem.
        popup.close()
        QApplication.processEvents()
        assert QApplication.activePopupWidget() is None, "menu się nie zamknęło - brak układu"
        win._flash("Cofnięto przypisanie na 2 z 2 klatek")
        win._pokaz_recepte("przywrócisz: Obiekt → Przywróć cofnięte przypisanie")
        QApplication.sendEvent(win, QStatusTipEvent(""))
        QApplication.processEvents()
        assert not win.recipe_label.isVisible(), "warunek popupu wyłączył gaszenie w ogóle"
    finally:
        popup.deleteLater()
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
        win._pokaz_recepte("przywrócisz: " + "bardzo długa etykieta pozycji menu " * 20)

        sufit = int(win.statusBar().width() * _PASEK_UDZIAL_RECEPTY)
        assert win.recipe_label.sizeHint().width() <= sufit + 4, "recepta przebiła swój sufit"
        assert win.recipe_label.text().endswith("…"), "przycięcie recepty bez znaku"
        assert win.statusBar().currentMessage(), "raport zniknął z paska przez szerokość recepty"
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
