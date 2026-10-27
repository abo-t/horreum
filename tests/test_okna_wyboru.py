"""AR-378 - jedna reguła katalogu startowego okien wyboru (`horreum/gui/okna_wyboru.py`): kandydat, który istnieje albo
ma istniejącego rodzica (`Scisly` - wyłącznie istniejący), sprawdzany POZA wątkiem okna z budżetem 0,25 s, jeden lot
sondy na ścieżkę i limit lotów; bramka AST „każde okno wyboru w `horreum/gui` bierze start z reguły”; start okien Plik,
Dostawy, żniw i wydania. Okno systemowe zawsze atrapą. Plik bez Qt na poziomie modułu - testy okien biorą `qapp`."""
import ast
import os
import threading
import time
from pathlib import Path

import pytest

import horreum
from horreum.gui import okna_wyboru

# Zapas na harmonogram ponad budżet 0,25 s: start wątku sondy, takt czekania 5 ms, rozdzielczość zegara Windows ~15,6 ms
# i GIL dzielony z innymi wątkami procesu testów - 0,1 s to 40 % budżetu, rząd wielkości ponad sumę tych opóźnień.
_ZAPAS_S = 0.1
_BEZPIECZNIK_S = 30


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _bez_wiszacych_lotow():
    """Każdy test zostawia rejestr lotów pusty: sondy kończą przed jego końcem (bramy zdjęte w `finally` testu)."""
    yield
    koniec = time.monotonic() + _BEZPIECZNIK_S
    while okna_wyboru._LOTY and time.monotonic() < koniec:
        time.sleep(0.01)
    assert not okna_wyboru._LOTY, okna_wyboru._LOTY


def _dom(tmp_path, monkeypatch):
    """Folder domowy procesu podmieniony na katalog testu (`os.path.expanduser` czyta `USERPROFILE`/`HOME`)."""
    dom = tmp_path / "dom"
    dom.mkdir()
    monkeypatch.setenv("USERPROFILE", str(dom))
    monkeypatch.setenv("HOME", str(dom))
    assert os.path.expanduser("~") == str(dom)
    return str(dom)


class _Isdir:
    """Atrapa `os.path.isdir` (podmieniona w module `os.path` - sonda czyta ją w chwili wołania): ścieżka z SEGMENTEM
    zaczynającym się od nazwy z `wolne` czeka na `brama` (bezpiecznik), z `opoznione` - `opoznienie_s`; każde wołanie
    zapisane z flagą wątku głównego. Segmenty, nie podłańcuch: katalog `tmp_path` nosi nazwę testu."""

    def __init__(self, monkeypatch, wolne=(), opoznione=(), opoznienie_s=0.0):
        self.prawdziwy = os.path.isdir
        self.brama = threading.Event()
        self.wolania = []
        self._zamek = threading.Lock()
        self.wolne, self.opoznione, self.opoznienie_s = wolne, opoznione, opoznienie_s
        monkeypatch.setattr(os.path, "isdir", self)

    @staticmethod
    def _ma(sciezka, nazwy):
        return any(czesc.startswith(n) for czesc in Path(sciezka).parts for n in nazwy)

    def __call__(self, sciezka):
        with self._zamek:
            self.wolania.append((str(sciezka), threading.current_thread() is threading.main_thread()))
        if self._ma(str(sciezka), self.wolne):
            self.brama.wait(_BEZPIECZNIK_S)
        if self._ma(str(sciezka), self.opoznione):
            time.sleep(self.opoznienie_s)
        return self.prawdziwy(sciezka)

    def ile(self, sciezka):
        """Ile razy sondowano DOKŁADNIE tę ścieżkę."""
        klucz = os.path.normcase(os.path.normpath(str(sciezka)))
        with self._zamek:
            return sum(os.path.normcase(os.path.normpath(s)) == klucz for s, _g in self.wolania)


def _start(*kandydaci):
    t = time.perf_counter()
    wynik = okna_wyboru.katalog_startowy(*kandydaci)
    return wynik, time.perf_counter() - t


# ═════════════════════════ reguła kandydata (bez Qt)

def test_pierwszy_istniejacy_albo_z_rodzicem_inaczej_folder_domowy(tmp_path, monkeypatch):
    """Kandydat liczy się, gdy istnieje albo istnieje jego rodzic (Qt schodzi o jeden poziom) - zwracany jest KANDYDAT,
    nie rodzic; bez rodzica odpada (Qt poszedłby do ostatnio odwiedzonego folderu procesu albo katalogu roboczego);
    pusty, `None` i względny się nie liczą; `Scisly` wyłącznie, gdy sam istnieje; nic - folder domowy.
    Mutanty: pierwszy niepusty bez sprawdzenia; bez reguły rodzica; zwrot rodzica zamiast kandydata."""
    dom = _dom(tmp_path, monkeypatch)
    jest = tmp_path / "jest"
    jest.mkdir()
    brak = tmp_path / "brak"                        # rodzic istnieje
    nie_ma = tmp_path / "nie" / "ma"                # rodzica nie ma
    assert okna_wyboru.katalog_startowy(str(nie_ma), str(jest)) == str(jest)
    assert okna_wyboru.katalog_startowy(str(brak), str(jest)) == str(brak)
    assert okna_wyboru.katalog_startowy("", None, "wzgledny", str(jest)) == str(jest)
    assert okna_wyboru.katalog_startowy(okna_wyboru.Scisly(str(brak)), str(jest)) == str(jest)
    assert okna_wyboru.katalog_startowy(okna_wyboru.Scisly(str(jest)), str(brak)) == str(jest)
    assert okna_wyboru.katalog_startowy(str(nie_ma)) == okna_wyboru.katalog_startowy() == dom
    assert type(okna_wyboru.katalog_startowy(okna_wyboru.Scisly(str(jest)))) is str


# ═════════════════════════ kolejność i budżet (sondy razem, kolejność wołającego, budżet 0,25 s)

def test_wolny_pierwszy_przegrywa_po_budzecie_z_szybkim_pozniejszym(tmp_path, monkeypatch):
    """Pierwszy kandydat wisi (udział bez odpowiedzi), późniejszy istnieje: po budżecie wygrywa późniejszy, który już
    odpowiedział „jest” - wołający nie stoi dłużej niż budżet + zapas. Sondy poza wątkiem głównym.
    Mutanty: czekanie po kolei bez budżetu (stoi do bezpiecznika); sonda w wątku wołającego."""
    szybki = tmp_path / "szybki"
    szybki.mkdir()
    isdir = _Isdir(monkeypatch, wolne=("wolny",))
    try:
        wynik, czas = _start(str(tmp_path / "wolny" / "a"), str(szybki))
        assert wynik == str(szybki)
        assert okna_wyboru._BUDZET_S * 0.8 <= czas <= okna_wyboru._BUDZET_S + _ZAPAS_S, czas
        assert not any(glowny for _s, glowny in isdir.wolania), isdir.wolania
    finally:
        isdir.brama.set()


def test_zywy_pierwszy_wygrywa_choc_pozniejszy_odpowiedzial_szybciej(tmp_path, monkeypatch):
    """Żywy udział odpowiada wolniej niż dysk lokalny, ale pierwszy w kolejności wołającego wygrywa, gdy odpowie w
    budżecie - pamięć człowieka (ostatnie źródło na `R:`) przed Dokumentami. Mutanty: pierwszy, który odpowie (bez
    kolejności); priorytet kandydatów lokalnych."""
    siec = tmp_path / "siec"
    lokalny = tmp_path / "lokalny"
    siec.mkdir()
    lokalny.mkdir()
    _Isdir(monkeypatch, opoznione=("siec",), opoznienie_s=0.03)
    wynik, czas = _start(str(siec), str(lokalny))
    assert wynik == str(siec)
    assert czas < okna_wyboru._BUDZET_S, czas


def test_martwy_jedyny_kandydat_nie_trzyma_okna_dluzej_niz_budzet(tmp_path, monkeypatch):
    """Jedyny kandydat na martwym udziale (zmierzone: 42 s do timeoutu SMB): po budżecie folder domowy, bez czekania na
    sondę. Mutant: czekanie na sondę bez limitu."""
    dom = _dom(tmp_path, monkeypatch)
    isdir = _Isdir(monkeypatch, wolne=("martwy",))
    try:
        wynik, czas = _start(str(tmp_path / "martwy" / "ASTRO_"))
        assert wynik == dom and czas <= okna_wyboru._BUDZET_S + _ZAPAS_S, (wynik, czas)
    finally:
        isdir.brama.set()


# ═════════════════════════ jeden lot na ścieżkę, limit lotów, spóźniony wynik

def test_jeden_lot_na_sciezke_i_limit_lotow(tmp_path, monkeypatch):
    """Pięć okien przy tym samym wiszącym udziale - jedna sonda na ścieżkę (kandydat i rodzic), nie pięć; dwadzieścia
    różnych wiszących ścieżek - lotów w biegu nie więcej niż `_MAKS_LOTOW`. Mutanty: bez rejestru lotów; bez limitu."""
    isdir = _Isdir(monkeypatch, wolne=("wisi",))
    przed = threading.active_count()
    try:
        for _ in range(5):
            okna_wyboru.katalog_startowy(str(tmp_path / "wisi" / "a"), budzet_s=0.01)
        time.sleep(0.05)
        assert isdir.ile(tmp_path / "wisi" / "a") == 1, isdir.wolania
        assert isdir.ile(tmp_path / "wisi") == 1, isdir.wolania          # rodzic kandydata - też jeden lot
        for i in range(20):
            okna_wyboru.katalog_startowy(str(tmp_path / f"wisi{i}" / "x" / "y"), budzet_s=0.01)
        assert len(okna_wyboru._LOTY) <= okna_wyboru._MAKS_LOTOW
        assert threading.active_count() - przed <= okna_wyboru._MAKS_LOTOW
    finally:
        isdir.brama.set()


class _ZatrzymanePoPublikacji(threading.Event):
    """`gotowe` lotu, które w wątku sondy PO publikacji wyniku staje (`w_oknie`), zanim sonda zdejmie wpis
    z rejestru."""

    def __init__(self, w_oknie, pusc):
        super().__init__()
        self._w_oknie, self._pusc = w_oknie, pusc

    def set(self):
        super().set()
        if threading.current_thread().name == "horreum-start-okna":
            self._w_oknie.set()
            self._pusc.wait(_BEZPIECZNIK_S)


def test_lot_skonczony_przed_zdjeciem_z_rejestru_oddaje_wynik_bez_drugiej_sondy(tmp_path, monkeypatch):
    """Okno między publikacją wyniku sondy a zdjęciem jej wpisu z rejestru: drugie okno wyboru tej samej ścieżki bierze
    wynik skończonego lotu i nie zakłada drugiej sondy (wpis znikał PRZED publikacją - drugie okno nie widziało wtedy
    ani lotu, ani wyniku, a limit liczył wpisy, nie wątki). Sonda zatrzymana deterministycznie w tym oknie.
    Mutant: zdjęcie wpisu przed `gotowe.set()`."""
    jest = tmp_path / "jest"
    jest.mkdir()
    w_oknie, pusc = threading.Event(), threading.Event()
    prawdziwy = okna_wyboru._Lot

    class _Lot(prawdziwy):
        def __init__(self):
            super().__init__()
            self.gotowe = _ZatrzymanePoPublikacji(w_oknie, pusc)
    monkeypatch.setattr(okna_wyboru, "_Lot", _Lot)
    isdir = _Isdir(monkeypatch)
    try:
        assert okna_wyboru.katalog_startowy(okna_wyboru.Scisly(str(jest))) == str(jest)
        assert w_oknie.wait(_BEZPIECZNIK_S), "sonda nie doszła do publikacji"
        assert okna_wyboru.katalog_startowy(okna_wyboru.Scisly(str(jest))) == str(jest)
        assert isdir.ile(jest) == 1, isdir.wolania
    finally:
        pusc.set()


def test_spozniony_wynik_nie_zmienia_startu_a_nastepne_okno_pyta_od_nowa(tmp_path, monkeypatch):
    """Sonda wolnego kandydata kończy PO zwrocie startu: zwrócony start zostaje (wynik bez czytelnika), lot schodzi
    z rejestru, a następne okno pyta dysk od nowa - wynik sprzed chwili nie jest pamięcią. Mutant: lot zostaje
    w rejestrze po końcu sondy (następne okno nie pyta)."""
    (tmp_path / "wolny").mkdir()
    wolny = tmp_path / "wolny" / "a"                # kandydat i jego rodzic wiszą razem (ten sam udział)
    drugi = tmp_path / "drugi"
    drugi.mkdir()
    isdir = _Isdir(monkeypatch, wolne=("wolny",))
    try:
        wynik = okna_wyboru.katalog_startowy(str(wolny), str(drugi))
        assert wynik == str(drugi)
    finally:
        isdir.brama.set()
    koniec = time.monotonic() + _BEZPIECZNIK_S
    while okna_wyboru._LOTY and time.monotonic() < koniec:
        time.sleep(0.01)
    assert not okna_wyboru._LOTY and wynik == str(drugi)
    isdir.wolne = ()
    przed = isdir.ile(wolny)
    assert okna_wyboru.katalog_startowy(str(wolny), str(drugi)) == str(wolny)
    assert isdir.ile(wolny) == przed + 1


# ═════════════════════════ bramka AST - każde okno wyboru w `horreum/gui` bierze start z reguły

_POMOCNIK = "katalog_startowy"


def _nazwa(wezel):
    return wezel.id if isinstance(wezel, ast.Name) else wezel.attr if isinstance(wezel, ast.Attribute) else None


def _okna_wyboru_w_zrodle(drzewo):
    """`[(linia, opis, wyrażenie startu albo None)]` każdego okna wyboru modułu: wywołania `get*` klasy `QFileDialog`
    pod KAŻDĄ nazwą (import `as`, przypisanie klasy), metody statyczne przypisane do nazw i konstruktory
    `QFileDialog(...)` (start: trzeci argument albo `dir=`/`directory=`)."""
    klasy = {"QFileDialog"}
    for _ in range(3):                                              # aliasy aliasów
        for w in ast.walk(drzewo):
            if isinstance(w, ast.ImportFrom):
                klasy |= {a.asname or a.name for a in w.names if a.name in klasy}
            elif isinstance(w, ast.Assign) and _nazwa(w.value) in klasy:
                klasy |= {t.id for t in w.targets if isinstance(t, ast.Name)}
    metody = {t.id for w in ast.walk(drzewo) if isinstance(w, ast.Assign) and isinstance(w.value, ast.Attribute)
              and _nazwa(w.value.value) in klasy and w.value.attr.startswith("get")
              for t in w.targets if isinstance(t, ast.Name)}
    okna = []
    for w in ast.walk(drzewo):
        if not isinstance(w, ast.Call):
            continue
        f = w.func
        if isinstance(f, ast.Attribute) and _nazwa(f.value) in klasy and f.attr.startswith("get"):
            opis, slowo = f"{_nazwa(f.value)}.{f.attr}", "dir"
        elif isinstance(f, ast.Name) and f.id in metody:
            opis, slowo = f.id, "dir"
        elif _nazwa(f) in klasy:
            opis, slowo = f"{_nazwa(f)}(...)", "directory"
        else:
            continue
        start = w.args[2] if len(w.args) > 2 else next((k.value for k in w.keywords if k.arg == slowo), None)
        okna.append((w.lineno, opis, start))
    return okna


def _z_pomocnika(wyrazenie, drzewo):
    """Start z reguły: wołanie `katalog_startowy` albo funkcji TEGO modułu, której każdy `return` to takie wołanie."""
    if not isinstance(wyrazenie, ast.Call):
        return False
    nazwa = _nazwa(wyrazenie.func)
    if nazwa == _POMOCNIK:
        return True
    for fn in ast.walk(drzewo):
        if isinstance(fn, ast.FunctionDef) and fn.name == nazwa:
            zwroty = [r.value for r in ast.walk(fn) if isinstance(r, ast.Return)]
            return bool(zwroty) and all(isinstance(z, ast.Call) and _nazwa(z.func) == _POMOCNIK for z in zwroty)
    return False


def _bez_reguly(zrodlo):
    drzewo = ast.parse(zrodlo)
    return [(linia, opis) for linia, opis, start in _okna_wyboru_w_zrodle(drzewo) if not _z_pomocnika(start, drzewo)]


def test_kazde_okno_wyboru_w_gui_bierze_start_z_reguly():
    """Bramka AR-378: każde okno wyboru pliku albo folderu w `horreum/gui` (10 na dziś) dostaje start z
    `okna_wyboru.katalog_startowy` - jedenaste okno z pustym startem otwierałoby katalog uruchomienia programu albo
    folder ostatniego dowolnego okna. Bramka sprawdza samą siebie: alias klasy, alias metody statycznej i konstruktor
    z `exec` bez startu są łapane, start z reguły (wprost i przez funkcję modułu) - przepuszczany."""
    gui = Path(horreum.__file__).parent / "gui"
    znalezione, bez = 0, []
    for plik in sorted(gui.rglob("*.py")):
        zrodlo = plik.read_text(encoding="utf-8")
        drzewo = ast.parse(zrodlo)
        znalezione += len(_okna_wyboru_w_zrodle(drzewo))
        bez += [(plik.relative_to(gui).as_posix(), linia, opis) for linia, opis in _bez_reguly(zrodlo)]
    assert znalezione >= 10, znalezione
    assert bez == [], bez

    alias_klasy = ("from PySide6.QtWidgets import QFileDialog as QFD\n"
                   "def f(self):\n    return QFD.getOpenFileName(self, 't')\n")
    alias_metody = ("from PySide6.QtWidgets import QFileDialog\nwybierz = QFileDialog.getExistingDirectory\n"
                    "def f(self):\n    return wybierz(self, 't', '')\n")
    konstruktor = ("from PySide6.QtWidgets import QFileDialog\n"
                   "def f(self):\n    d = QFileDialog(self, 't')\n    d.exec()\n")
    for zrodlo in (alias_klasy, alias_metody, konstruktor):
        assert len(_bez_reguly(zrodlo)) == 1, zrodlo
    dobre = ("from PySide6.QtWidgets import QFileDialog as Q\nfrom horreum.gui import okna_wyboru\n"
             "def _start(self):\n    return okna_wyboru.katalog_startowy(self.a)\n"
             "def f(self):\n    Q.getExistingDirectory(self, 't', okna_wyboru.katalog_startowy(a))\n"
             "    return Q.getSaveFileName(self, 't', self._start(), 'x')\n")
    assert _bez_reguly(dobre) == [] and len(_okna_wyboru_w_zrodle(ast.parse(dobre))) == 2


# ═════════════════════════ okna (atrapa okna systemowego)

def _atrapa(monkeypatch, klasa, metoda, wynik=""):
    """Podmiana statycznego okna wyboru: zapisuje start (trzeci argument), zwraca `wynik` (anulowanie)."""
    starty = []

    def _okno(_parent, _tytul, start="", *a, **k):
        starty.append(start)
        return wynik
    monkeypatch.setattr(klasa, metoda, staticmethod(_okno))
    return starty


def test_nowa_i_otworz_baze_startuja_przy_biezacej_bazie(qapp, tmp_path, monkeypatch):
    """„Nowa baza…” i „Otwórz bazę…” startowały z pustego napisu (katalog uruchomienia programu, potem folder ostatniego
    dowolnego okna wyboru). Teraz w katalogu bieżącej bazy - katalog, bez nazwy pliku. Prawdziwe akcje menu Plik.
    Mutant: `_on_new_db` / `_on_open_db` ze startem `""`."""
    from PySide6.QtWidgets import QFileDialog
    from horreum import db
    from horreum.gui.app import MainWindow
    from test_gui_mainwindow import _akcja_menu_plik
    (tmp_path / "a").mkdir()
    sciezka = str(tmp_path / "a" / "x.db")
    db.open_db(sciezka).close()
    nowa = _atrapa(monkeypatch, QFileDialog, "getSaveFileName", ("", ""))
    otworz = _atrapa(monkeypatch, QFileDialog, "getOpenFileName", ("", ""))
    win = MainWindow(sciezka)
    try:
        _akcja_menu_plik(win, "menu.new_db").trigger()
        _akcja_menu_plik(win, "menu.open_db").trigger()
        assert nowa == [str(tmp_path / "a")] and otworz == [str(tmp_path / "a")]
    finally:
        win.close()


def test_okno_bazy_bez_bazy_bierze_katalog_ostatniej_potem_dokumenty(qapp, tmp_path, monkeypatch, ustawienia):
    """Okno bez bazy (otwarcie się nie udało): start w katalogu ostatniej bazy, bez niej - w Dokumentach
    (`QStandardPaths` podmienione przez `_izoluj_dane_programu`). Mutant: bez kandydata ostatniej bazy."""
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui.app import MainWindow
    from test_gui_mainwindow import _akcja_menu_plik
    (tmp_path / "b").mkdir()
    ustawienia.setValue("ostatnia_baza", str(tmp_path / "b" / "skasowana.db"))
    otworz = _atrapa(monkeypatch, QFileDialog, "getOpenFileName", ("", ""))
    win = MainWindow()
    try:
        _akcja_menu_plik(win, "menu.open_db").trigger()
        ustawienia.remove("ostatnia_baza")
        _akcja_menu_plik(win, "menu.open_db").trigger()
        dokumenty = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        assert otworz == [str(tmp_path / "b"), dokumenty], otworz
    finally:
        win.close()


def test_folder_roboczy_startuje_przy_zapamietanym_albo_w_folderze_domowym(qapp, tmp_path, monkeypatch, ustawienia):
    """Plik → „Folder roboczy WBPP…”: zapamiętany folder, bez niego folder domowy (dawniej pusty start). Mutant: start
    z gołej pamięci (pusty napis bez pamięci)."""
    from PySide6.QtWidgets import QFileDialog
    from horreum.gui.app import MainWindow
    from test_gui_mainwindow import _akcja_menu_plik
    dom = _dom(tmp_path, monkeypatch)
    praca = tmp_path / "praca"
    praca.mkdir()
    starty = _atrapa(monkeypatch, QFileDialog, "getExistingDirectory")
    win = MainWindow()
    try:
        _akcja_menu_plik(win, "menu.work_root").trigger()
        ustawienia.setValue("work/root", str(praca))
        _akcja_menu_plik(win, "menu.work_root").trigger()
        assert starty == [dom, str(praca)], starty
    finally:
        win.close()


def _dostawa(tmp_path):
    from horreum import db
    from horreum.gui.pipeline import PipelineView
    sciezka = str(tmp_path / "p.db")
    db.open_db(sciezka).close()
    return PipelineView(sciezka, now_fn=lambda: "2026-10-27T12:00:00+00:00")


def test_pierwsza_dostawa_bez_pamieci_startuje_w_folderze_domowym(qapp, tmp_path, monkeypatch):
    """„Przyjmij nowe” bez zapamiętanego źródła pyta o katalog - okno startowało w katalogu uruchomienia programu
    (pierwsza dostawa nowego użytkownika). Teraz w folderze domowym. Mutant: `_pick_and_scan` bez startu."""
    from PySide6.QtWidgets import QFileDialog
    dom = _dom(tmp_path, monkeypatch)
    starty = _atrapa(monkeypatch, QFileDialog, "getExistingDirectory")
    view = _dostawa(tmp_path)
    try:
        view.btn_receive.click()
        assert starty == [dom] and view._thread is None
    finally:
        view.close()


def test_wskaz_katalog_i_obecnosc_w_startuja_przy_zrodle_dostawy(qapp, tmp_path, monkeypatch, ustawienia):
    """„Wskaż katalog…” i „Sprawdź obecność w…” startują przy źródle „Przyjmij nowe” (dawniej bez startu). Mutanty:
    `_on_pick_dir` / `_on_presence_pick` bez startu."""
    from PySide6.QtWidgets import QFileDialog
    zrodlo = tmp_path / "zrodlo"
    zrodlo.mkdir()
    ustawienia.setValue("pipeline/last_source", str(zrodlo))
    starty = _atrapa(monkeypatch, QFileDialog, "getExistingDirectory")
    view = _dostawa(tmp_path)
    try:
        view._on_pick_dir()
        view.btn_presence_in.click()
        assert starty == [str(zrodlo), str(zrodlo)], starty
    finally:
        view.close()


def test_cel_wydania_startuje_przy_zaznaczonej_karcie(qapp, tmp_path, monkeypatch, ustawienia):
    """„Dodaj cel…” okna wydania startuje przy zaznaczonej karcie (nowy cel leży zwykle obok; dawniej bez startu).
    Mutant: `_on_add_target` bez startu."""
    from horreum import db
    from horreum.gui import projection_dialog as pd_mod
    cel = tmp_path / "_WBPP" / "cel"
    cel.mkdir(parents=True)
    pd_mod.remember_target("cel", str(cel))
    starty = _atrapa(monkeypatch, pd_mod.QFileDialog, "getExistingDirectory")
    con = db.open_db(str(tmp_path / "a.db"))
    dlg = pd_mod.ProjectionDialog(con, [], now_fn=lambda: "2026-10-27T12:00:00+00:00", off_thread=False)
    try:
        assert dlg._current_root() is not None
        dlg._on_add_target()
        assert [os.path.normcase(s) for s in starty] == [os.path.normcase(str(cel))], starty
    finally:
        dlg.reject()
        con.close()


def test_wskaz_wyjscie_zniw_nie_sprawdza_dysku_w_watku_okna(qapp, tmp_path, monkeypatch, ustawienia):
    """„Wskaż…” okna żniw sprawdzało `<folder roboczy>\\OBJECTS` `isdir` w wątku okna - folder roboczy bywa na udziale,
    który odpadł (42 s zamrożenia). Teraz `OBJECTS` jest kandydatem ścisłym reguły - sprawdza go wątek sondy, a start
    jak dotąd: `OBJECTS`, gdy istnieje, inaczej ostatnie wyjście. Mutant: `isdir(OBJECTS)` w `_pick_start`."""
    from horreum import projection
    from horreum.gui import harvest_dialog as hd_mod
    from test_gui_harvest import _baza, _czytnik, _dlg
    con, _profile, _flats = _baza(tmp_path)
    _czytnik(monkeypatch, {})
    work = tmp_path / "_WBPP"
    ustawienia.setValue("harvest/last_output", str(tmp_path / "ostatnie"))
    starty = _atrapa(monkeypatch, hd_mod.QFileDialog, "getExistingDirectory")
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    try:
        (work / projection.OBJECT_NAMESPACE).mkdir(parents=True)
        isdir = _Isdir(monkeypatch)
        dlg.btn_pick.click()
        assert starty == [str(work / projection.OBJECT_NAMESPACE)], starty
        assert [s for s, glowny in isdir.wolania if glowny] == [], isdir.wolania
        assert isdir.ile(work / projection.OBJECT_NAMESPACE) == 1, isdir.wolania
    finally:
        dlg.reject()
        con.close()
