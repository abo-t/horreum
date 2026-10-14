"""Współdzielone fixture'y pytest. `s8` = deterministyczna baza §8 (PLAN_gui §8) - jeden builder
dla testów logiki read-modelu (5.2) i przyszłych testów GUI; bez Qt, bez plików na dysku."""
import sys

import pytest

from fixture_s8 import seed, seed_object_axis

from horreum import db
from horreum.gui import i18n   # Qt-wolny (słownik) - import bezpieczny bez PySide6

ZMIENIA_MOTYW = "zmienia_motyw"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", f"{ZMIENIA_MOTYW}: test ŚWIADOMIE zmienia wygląd całej aplikacji (arkusz, styl, paleta, "
        "font aplikacji, kolory modułów z `use_theme`); `_przywroc_wyglad_aplikacji` przywraca go bez alarmu")


@pytest.fixture(autouse=True)
def _reset_i18n_lang():
    """`i18n._LANG` to jedyny PROCESOWO-GLOBALNY stan wpływający na czyste funkcje prezentacji
    (`t`/`t_plural`); test z `set_lang('en')` bez resetu skaziłby kolejne (porażki zależne od
    KOLEJNOŚCI - łamią determinizm baterii). Reset PRZED każdym testem (R-i18n #4). `_missing`
    (zbiór już-zalogowanych braków - log raz) też zerowany: przyszły test „warn raz na klucz"
    inaczej stałby się order-dependent (recenzja fundamentu #1)."""
    i18n.set_lang(i18n.DEFAULT)
    i18n._missing.clear()
    yield


@pytest.fixture(autouse=True)
def _izoluj_qsettings(tmp_path_factory, monkeypatch):
    """Żaden test nie pisze do PRAWDZIWYCH ustawień usera (Windows: rejestr
    `HKCU\\Software\\Horreum\\Horreum`). Dowód defektu 2026-09-26: `ostatnia_baza` wskazywała bazę
    z katalogu pytesta, bo `main()` w teście zapamiętał ją w rejestrze - zwykły start Horreum
    otwierał potem śmieć z `C:\\Temp`.

    Podmiana `QSettings.__init__`, a nie `setDefaultFormat`+`setPath` ani
    `QStandardPaths.setTestModeEnabled`: konstruktor `QSettings(org, app)` na Windows idzie do
    rejestru i oba te mechanizmy ignoruje (sonda 2026-09-26, PySide6 6.9.2). Podmiana łapie KAŻDE
    utworzenie - w każdym module, także importowanym leniwie - i kieruje je do pliku INI w katalogu
    TEGO testu (świeże ustawienia per test, poza `tmp_path`, żeby nie mieszać testom listingu
    katalogu). Test, który chce czytać albo wstawiać ustawienia, bierze fixture `ustawienia`.
    Bramki: `test_main_NIE_rusza_rejestru_usera` (ścieżka `main()`) i `_straznik_rejestru_usera`
    (cała bateria)."""
    try:
        from PySide6.QtCore import QSettings
    except ImportError:                 # `.venv` bez Qt - nie ma czego izolować
        yield
        return
    ini = str(tmp_path_factory.mktemp("qsettings") / "horreum.ini")
    prawdziwy_init = QSettings.__init__

    def _init_w_pliku(self, *args, **kwargs):
        prawdziwy_init(self, ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(QSettings, "__init__", _init_w_pliku)
    yield


def _kolory_modulow():
    """Słowniki kolorów, które `app.apply_theme` stawia przez `use_theme` modułów warstwy widżetów:
    `{moduł: {nazwa: słownik}}`. Spis z `sys.modules`, nie ręczny (AR-136): moduł `horreum.gui.*`
    z WŁASNYM `use_theme` na poziomie modułu i jego słowniki wartości `QColor` - nowy moduł z kolorami
    motywu wchodzi do straży sam. `grid` z `use_theme` wziętym z `grid_model` się nie liczy: słownik
    ma jednego właściciela, moduł, który funkcję definiuje."""
    from PySide6.QtGui import QColor
    out = {}
    for nazwa, mod in list(sys.modules.items()):
        if mod is None or not nazwa.startswith("horreum.gui."):
            continue
        funkcja = getattr(mod, "use_theme", None)
        if not callable(funkcja) or getattr(funkcja, "__module__", None) != nazwa:
            continue
        out[nazwa] = {k: v for k, v in vars(mod).items()
                      if isinstance(v, dict) and v and all(isinstance(c, QColor) for c in v.values())}
    return out


def _odbitka(slowniki):
    from PySide6.QtGui import QColor
    return {k: {klucz: QColor(c) for klucz, c in d.items()} for k, d in slowniki.items()}


def _kolory_domyslne(nazwa, slowniki):
    """Kolory modułu zaimportowanego dopiero W teście - stan z importu, czyli `use_theme(DEFAULT)`.
    Liczone próbnym wołaniem na żywych słownikach, które od razu wracają: wzór bierze się z tej samej
    funkcji, którą woła produkcja, a nie z drugiego spisu kolorów."""
    from horreum.gui import theme
    zapis = _odbitka(slowniki)
    sys.modules[nazwa].use_theme(theme.DEFAULT)
    wzor = _odbitka(slowniki)
    for k, d in slowniki.items():
        d.clear()
        d.update(zapis[k])
    return wzor


@pytest.fixture(autouse=True)
def _przywroc_wyglad_aplikacji(request):
    """Wygląd CAŁEJ aplikacji - arkusz QSS, styl, paleta, font aplikacji i kolory modułów, czyli to,
    co stawia `app.apply_theme` (plus `QApplication.setFont`) - wraca po teście do stanu sprzed niego
    (AR-79, AR-136). `main()` i `_on_theme` stawiają motyw na `QApplication`, która żyje całą sesję,
    więc motyw zostawał testom z kolejnych plików. Dowód 2026-10-13: po `test_gui_mainwindow.py`
    zostawał arkusz motywu (821 znaków), a przy arkuszu aplikacji `setFont` rodzica nie schodzi do
    list dzieci - bramka listwy facetów mierzyła dwa razy ten sam wiersz 12 px.

    Przywrócenie NIE jest ciche (AR-136): test, który zmienił wygląd bez markera `zmienia_motyw`,
    pada przy teardownie z listą zmienionych członów. Przeciek motywu był detektorem, który znalazł
    AR-79 - samo przywrócenie gasiłoby taki sygnał bez śladu. Test zmieniający wygląd ŚWIADOMIE nosi
    marker i zostawia sprzątanie tej fixture.

    Arkusz wraca pierwszy: przy czynnym arkuszu `style().name()` zwraca pusty napis (styl
    opakowany), więc styl porównujemy dopiero po nim. Aplikacja powstała W teście - stan zastany
    to świeża aplikacja: pusty arkusz i paleta bazowa (`QPalette()` bez ustawionych ról rozwiązuje
    się do niej); styl i font zostają, bo ich wartości domyślnych nie znamy przed powstaniem
    aplikacji."""
    try:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication
    except ImportError:                 # `.venv` bez Qt - nie ma czego przywracać
        yield
        return
    app = QApplication.instance()
    zastany = None if app is None else (app.styleSheet(), app.style().name(), app.palette(),
                                        QApplication.font())
    kolory = {nazwa: _odbitka(slowniki) for nazwa, slowniki in _kolory_modulow().items()}
    yield
    zmiany = []
    for nazwa, slowniki in _kolory_modulow().items():
        wzor = kolory[nazwa] if nazwa in kolory else _kolory_domyslne(nazwa, slowniki)
        for k, d in slowniki.items():
            if k in wzor and d != wzor[k]:
                zmiany.append(f"{nazwa}.{k}")
                d.clear()
                d.update(wzor[k])
    app = QApplication.instance()
    if app is not None:
        arkusz, styl, paleta, font = zastany or ("", "", QPalette(), None)
        if app.styleSheet() != arkusz:
            zmiany.append("arkusz")
            app.setStyleSheet(arkusz)
        if styl and app.style().name() != styl:
            zmiany.append("styl")
            app.setStyle(styl)
        if zastany is None or app.palette() != paleta:
            if zastany is not None:
                zmiany.append("paleta")
            app.setPalette(paleta)
        if font is not None and QApplication.font() != font:
            zmiany.append("font aplikacji")
            QApplication.setFont(font)
    if zmiany and request.node.get_closest_marker(ZMIENIA_MOTYW) is None:
        pytest.fail(f"test zmienił wygląd aplikacji bez markera `{ZMIENIA_MOTYW}` (przywrócone): "
                    + ", ".join(zmiany))


_LIMIT_WATKU_MS = 10_000


@pytest.fixture(autouse=True)
def _skasuj_okna_testu(_izoluj_qsettings, _przywroc_wyglad_aplikacji):
    """Okna najwyższego poziomu, które test zostawił, kasujemy po nim (AR-11). `win.close()` tylko
    chowa okno, a `gc` go nie zbierze: sloty-lambdy trzymają `self` przez połączenia Qt, których
    cykl jest poza zasięgiem Pythona. Dowód 2026-10-03: przed `test_main_NIE_rusza_rejestru_usera`
    żyło 24 131 widgetów (950 okien) z samego `test_gui_mainwindow.py`, a `apply_theme`
    (`setStyleSheet`/`setPalette`/`setStyle` na CAŁĄ aplikację) przepoleruje każdy z nich - koszt
    liniowy, ~0,3 ms na widget na platformie natywnej. Pełna bateria: 94 s + 51 s na dwóch testach
    motywu przy 0,24 s dla jednego okna. To koszt baterii, nie produktu (jedno okno, ~750 widgetów).

    Zależność od `_izoluj_qsettings` ustawia kolejność: sprzątanie biegnie PRZED zdjęciem podmiany
    ustawień, więc kasowane okno nie ma jak sięgnąć rejestru usera. Zależność od
    `_przywroc_wyglad_aplikacji` stawia przywrócenie motywu PO kasowaniu okien - przepolerowanie
    nie idzie po widgetach, które i tak giną. `~QThread` w biegu to `qFatal`
    (0xC0000409 - zmierzone na planerze, który liczy noc w tle od montażu). Worker kończy rachunek
    w milisekundach, ale `finished -> QThread.quit` idzie KOLEJKĄ do wątku głównego, a test nie
    kręci pętli - wątek wisi w `exec()` bez końca. Stąd jawne `quit()` (bezpieczne z innego wątku;
    przed `exec()` Qt 6 je zapamiętuje) i `wait` z limitem; okno z wątkiem, który nie skończył
    w limicie, zostaje żywe. Kasujemy wyłącznie okna bez rodzica powstałe w TYM teście;
    widgety fixture'ów o szerszym zasięgu powstały przed zrzutem i zostają."""
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QThread
        from PySide6.QtWidgets import QApplication
    except ImportError:                 # `.venv` bez Qt - nie ma czego sprzątać
        yield
        return
    app = QApplication.instance()
    przed = set(app.topLevelWidgets()) if app is not None else set()
    yield
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if w in przed or w.parentWidget() is not None:
            continue
        watki = w.findChildren(QThread)
        for t in watki:
            t.quit()
        if not all(t.wait(_LIMIT_WATKU_MS) for t in watki):
            continue
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def ustawienia(_izoluj_qsettings):
    """Ustawienia aplikacji widziane przez test - te same, które czyta i pisze kod produktu
    (`QSettings("Horreum", "Horreum")`), już w pliku INI tego testu. Zamiast słownika podstawionego
    pod `value`/`setValue`: test przechodzi przez prawdziwy zapis i odczyt Qt."""
    from PySide6.QtCore import QSettings
    return QSettings("Horreum", "Horreum")


def _rejestr_horreum():
    """Płaski zrzut `HKCU\\Software\\Horreum\\Horreum` z podkluczami: `{"ui/theme": (wartość, typ)}`;
    `{}`, gdy klucza nie ma albo system nie ma rejestru."""
    try:
        import winreg
    except ImportError:
        return {}

    def _zbierz(klucz, prefiks, out):
        n_pod, n_wart, _ = winreg.QueryInfoKey(klucz)
        for i in range(n_wart):
            nazwa, wartosc, typ = winreg.EnumValue(klucz, i)
            out[prefiks + nazwa] = (wartosc, typ)
        for i in range(n_pod):
            nazwa = winreg.EnumKey(klucz, i)
            with winreg.OpenKey(klucz, nazwa) as k:
                _zbierz(k, prefiks + nazwa + "/", out)

    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Horreum\Horreum") as k:
            _zbierz(k, "", out)
    except FileNotFoundError:
        pass
    return out


@pytest.fixture
def zrzut_rejestru():
    """Funkcja zrzutu rejestru usera dla bramek, które mierzą go przed i po geście."""
    return _rejestr_horreum


@pytest.fixture(scope="session", autouse=True)
def _straznik_rejestru_usera():
    """Strażnik CAŁEJ baterii: rejestr usera po ostatnim teście ma być taki jak przed pierwszym.
    Łapie wyciek z dowolnego testu, także przyszłego i omijającego `_izoluj_qsettings`; porażka
    wychodzi jako ERROR przy teardownie ostatniego testu, z nazwami zmienionych kluczy.
    Fałszywy alarm: prawdziwy Horreum uruchomiony W TRAKCIE baterii też zapisuje rejestr."""
    przed = _rejestr_horreum()
    yield
    po = _rejestr_horreum()
    zmiany = {k: (przed.get(k), po.get(k)) for k in sorted(przed.keys() | po.keys())
              if przed.get(k) != po.get(k)}
    assert not zmiany, f"bateria zmieniła prawdziwe ustawienia usera (klucz: przed, po): {zmiany}"


@pytest.fixture
def s8(tmp_path):
    """(con, ids) świeżej bazy §8. `ids` = dict id-ków (A/B/C/D, cam1/cam2, cfg_*, frames)."""
    con = db.open_db(str(tmp_path / "s8.db"))
    ids = seed(con)
    yield con, ids
    con.close()


@pytest.fixture
def s8_obj(tmp_path):
    """(con, ids) bazy §8 rozszerzonej o oś OBIEKT (PLAN_gui_object §8). `ids` dodatkowo: `objects`
    (NGC7000/M42) + frame'y obiektowe (objrev1/2, calib_flat, present0). Telescope-liczniki bez zmian."""
    con = db.open_db(str(tmp_path / "s8_obj.db"))
    ids = seed_object_axis(con)
    yield con, ids
    con.close()
