"""Współdzielone fixture'y pytest. `s8` = deterministyczna baza §8 (PLAN_gui §8) — jeden builder
dla testów logiki read-modelu (5.2) i przyszłych testów GUI; bez Qt, bez plików na dysku."""
import pytest

from fixture_s8 import seed, seed_object_axis

from horreum import db
from horreum.gui import i18n   # Qt-wolny (słownik) — import bezpieczny bez PySide6


@pytest.fixture(autouse=True)
def _reset_i18n_lang():
    """`i18n._LANG` to jedyny PROCESOWO-GLOBALNY stan wpływający na czyste funkcje prezentacji
    (`t`/`t_plural`); test z `set_lang('en')` bez resetu skaziłby kolejne (porażki zależne od
    KOLEJNOŚCI — łamią determinizm baterii). Reset PRZED każdym testem (R-i18n #4). `_missing`
    (zbiór już-zalogowanych braków — log raz) też zerowany: przyszły test „warn raz na klucz"
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
