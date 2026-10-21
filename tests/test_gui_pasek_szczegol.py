"""Pasek gospodarza ze szczegółem systemu (AR-218), podgląd pozostałych zmian po zapisie przerwanym
anulowaniem (AR-220), ścieżka łamana w malowaniu pola zdania (AR-221), zdania paska szuflady bez
żargonu (AR-227) i odmiana liczby zmian (AR-226). Wejście w „Rodowód do potwierdzenia” (AR-219)
pinuje prawdziwy klik wiersza Porządków w `test_gui_mainwindow.py`.

Testy sterują realnym oknem Qt (offscreen), kliki i klawisze prawdziwe; wątki tła prawdziwe tam,
gdzie test mówi o kolejności zdarzeń (anulowanie zapisu, awaria etapu Dostawy przed końcem biegu)."""
import ast
import os
import pathlib
import stat
import sys
import threading
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, QRect, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from horreum import db, scan, writeback
from horreum.gui import i18n, queries
from horreum.gui.app import NAV_DOM, NAV_DOSTAWA, NAV_ZBIORY, STRONA_ZBIORY, MainWindow
from horreum.gui.i18n_catalog import CATALOG
from horreum.gui.wb_worker import (EtykietaBledu, WritebackWorker, ZdanieZeSzczegolem, podpowiedz_kart,
                                   szczegol_zdania, wiersz_systemu, zlacz_zdania)
from horreum.item_reasons import SYSTEM_REASON_CODES, blad_systemu, powod_okna

from test_gui_app_object import sciezka_karty  # noqa: F401  (oś obiektu z propozycją i plikami kart)
from test_gui_planner import view  # noqa: F401  (fikstura planera - prawdziwy rachunek nocy)
from test_gui_pola_w_tle import _klik_komorki
from test_gui_powody_pisarza import _widok_nad
from prawy_klik import menu_pola_otwarte, prawy_klik
from test_gui_protokol_zdania import _odmowa_systemu, _tip

NOW = "2026-10-18T12:00:00"
_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_LAMANIE = "\u200b"
_POL = {"source": "date_obs", "offset_hours": 0, "fallback": True}


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def jezyk():
    yield i18n.set_lang
    i18n.set_lang("pl")


@pytest.fixture
def pola_inline(monkeypatch):
    """Pokrycie pól Zbiorów w oknie bez wątku tła - przewidywalny skład (jak `test_gui_mainwindow`)."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


def _czekaj(warunek, opis, s=30):
    """Pętla zdarzeń do warunku - `processEvents` + `sleep`, nie `qWait` (trzyma GIL)."""
    koniec = time.monotonic() + s
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {s} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.005)


def _fits(p, i, dobs):
    import numpy as np
    from astropy.io import fits
    hdu = fits.PrimaryHDU(data=np.full((4, 4), i + 1, dtype=np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = "NGC7000"
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["FILTER"] = "Ha"
    hdu.header["DATE-OBS"] = dobs
    hdu.header["EXPTIME"] = 300.0
    hdu.writeto(str(p), overwrite=True)


def _baza_z_plikami(tmp_path, n):
    """Baza w pliku nad `n` prawdziwymi FITS (różne dane i czasy - różne klatki i nazwy)."""
    path = tmp_path / "pasek.db"
    con = db.open_db(str(path))
    pliki = []
    for i in range(n):
        p = tmp_path / f"raw{i}.fits"
        _fits(p, i, f"2024-03-{15 + i:02d}T21:30:45")
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
        pliki.append(p)
    return path, con, pliki


@pytest.fixture
def trzy(qapp, tmp_path):
    """Widok Zbiorów nad trzema plikami, z PRAWDZIWYM wątkiem zapisu (baza w pliku)."""
    from horreum.gui.grid import FramesView
    _path, con, pliki = _baza_z_plikami(tmp_path, 3)
    v = FramesView(con, now_fn=lambda: NOW)
    assert v._writeback_async
    v.resize(1400, 800)
    v.show()
    QApplication.processEvents()
    yield v, con, pliki
    _czekaj(lambda: not v._wb.is_busy, "wątek zapisu przed zamknięciem")
    v.close()
    con.close()


def _staging_makra(view, wartosc="EQ6"):
    bar = view.macro_bar
    bar.asg_kw.setCurrentText("TELESCOP")
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText(wartosc)
    bar._emit_stage()


def _komunikaty(view):
    out = []
    view.status_message.connect(out.append)
    return out


# ============================================================ AR-218 - nośnik zdania ze szczegółem


def test_zlacz_zdania_czyta_generator_raz_i_zbiera_szczegoly(qapp):
    """Złączenie zdań ze szczegółem: wejście bywa JEDNORAZOWYM generatorem (gospodarz składa raport
    żniw i rodowodu wyrażeniem generatora), więc zdanie i szczegóły z jednego przebiegu po wejściu;
    puste zdania odpadają. Falsyfikator: złączenie, które czyta wejście dwa razy (drugi przebieg
    pusty - szczegół znika)."""
    zdania = (z for z in (ZdanieZeSzczegolem("a", "s1"), "", "b", ZdanieZeSzczegolem("c", "s2")))
    z = zlacz_zdania(" - ", zdania)
    assert z == "a - b - c" and isinstance(z, ZdanieZeSzczegolem)
    assert z.szczegol == "s1\ns2"
    assert szczegol_zdania("goły tekst") == "" and szczegol_zdania(z) == "s1\ns2"


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_blad_programu_ma_wiersz_szczegolu_technicznego(qapp, jezyk, lang):
    """Błąd programu z kodem (`prog_error`, `powod_okna`) to nie błąd systemu, ale jego zdanie odsyła
    pod kursor - wiersz „Szczegół techniczny: Typ: opis”. Falsyfikator: gałąź `prog_error` zdjęta z
    `wiersz_systemu` → pusty wiersz."""
    jezyk(lang)
    powod = powod_okna(KeyError("brak klucza"))
    assert powod.code == "prog_error" and "prog_error" not in SYSTEM_REASON_CODES
    assert wiersz_systemu(powod) == i18n.t("objchg.st.detail_tip", detail="KeyError: 'brak klucza'")
    if lang == "en":
        assert not set(wiersz_systemu(powod)) & _POLSKIE


def test_blad_programu_bez_szczegolu_tekstem_daje_pusty_wiersz(qapp):
    """Gałąź `prog_error` TOTALNA jak `_surowy_systemu`: powód odtworzony z bazy kodekiem bez `detail`
    albo z `detail` nie-tekstem daje pusty wiersz, nie wyjątek w oknie. Falsyfikator:
    `dict(params)["detail"]` (`KeyError`)."""
    from horreum.item_reasons import PowodPozycji
    zdanie = "błąd programu - szczegół w podpowiedzi"
    assert wiersz_systemu(PowodPozycji(zdanie, "prog_error")) == ""
    assert wiersz_systemu(PowodPozycji(zdanie, "prog_error", detail=None)) == ""
    assert wiersz_systemu(PowodPozycji(zdanie, "prog_error", detail="")) == ""


def test_sygnal_paska_ze_szczegolem_jest_object(qapp):
    """Bramka cichej utraty szczegółu: `Signal(str)` zamienia `ZdanieZeSzczegolem` na goły `str`.
    Klasy z `status_message`, które budują nośnik, to DOKŁADNIE ten zbiór (jawny, nie wyprowadzony
    z kodu) i każda deklaruje `Signal(object)`; klasa z `Signal(str)` nośnika nie buduje.
    Falsyfikator: `FramesView.status_message = Signal(str)` albo emisja nośnika w nowej klasie."""
    oczekiwane = {"FramesView", "ObjectAxisView", "PipelineView", "PlannerView"}
    root = pathlib.Path(__file__).resolve().parent.parent / "horreum" / "gui"
    klasy = {}
    for plik in root.rglob("*.py"):
        for wezel in ast.walk(ast.parse(plik.read_text(encoding="utf-8"))):
            if not isinstance(wezel, ast.ClassDef):
                continue
            sygnal = next((ast.unparse(st.value) for st in wezel.body
                           if isinstance(st, ast.Assign)
                           and any(getattr(t, "id", None) == "status_message" for t in st.targets)), None)
            buduje = any(isinstance(w, ast.Call) and getattr(w.func, "id", None) == "ZdanieZeSzczegolem"
                         for w in ast.walk(wezel))
            if sygnal is not None:
                klasy[wezel.name] = (sygnal, buduje)
    assert {k for k, (_s, b) in klasy.items() if b} == oczekiwane, klasy
    for k in oczekiwane:
        assert klasy[k][0] == "Signal(object)", (k, klasy[k])
    assert not [k for k, (s, b) in klasy.items() if s == "Signal(str)" and b]


# ============================================================ AR-218 - pasek gospodarza


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_pasek_gospodarza_zdanie_ze_szczegolem(qapp, jezyk, lang):
    """Raport ze szczegółem: JEDNA podpowiedź - paska (zdanie + szczegół wierszem niżej), pole raportu
    własnej nie ma; glif wskaźnika i menu „Kopiuj zdanie” (PEŁNE zdanie, także gdy pasek je uciął) /
    „Kopiuj szczegół” z treścią zamrożoną przy otwarciu menu - raport, który wygasł między prawym
    klikiem a wyborem pozycji, dalej daje się skopiować. Następny raport bez szczegółu go zdejmuje.
    Falsyfikatory: `_flash` bez szczegółu, podpowiedź pola zostawiona, „Kopiuj zdanie” ze skrótu,
    menu czytające pole przy kliknięciu pozycji."""
    jezyk(lang)
    win = MainWindow()
    try:
        win.resize(700, 400)
        win.show()
        QApplication.processEvents()
        dlugie = "Zapis zmian do plików nie powiódł się: " + "udział sieciowy nie odpowiada · " * 12
        win._flash(ZdanieZeSzczegolem(dlugie, _tip()))
        assert win.report_label.text().endswith("…") and win.report_label.text() != dlugie
        assert win.statusBar().toolTip() == dlugie + "\n" + _tip()
        assert win.report_label.toolTip() == ""                       # podpowiedź jest jedna - paska
        assert win.report_label.szczegol() == _tip() and win.report_label.indent() > 0
        prawy_klik(win.report_label)
        pozycje = menu_pola_otwarte(win.report_label)
        assert list(pozycje) == [i18n.t("wb.copy_sentence"), i18n.t("wb.copy_detail")]
        win._wygas_raport()                                           # raport gaśnie przy otwartym menu
        assert win.report_label.szczegol() == "" and win.statusBar().toolTip() == ""
        pozycje[i18n.t("wb.copy_sentence")].trigger()
        assert QGuiApplication.clipboard().text() == dlugie
        pozycje[i18n.t("wb.copy_detail")].trigger()
        assert QGuiApplication.clipboard().text() == _tip()
        win.report_label._menu.hide()
        win._flash(ZdanieZeSzczegolem("zdanie", _tip()))
        win._flash("inne zdanie")
        assert win.report_label.szczegol() == "" and win.statusBar().toolTip() == "inne zdanie"
    finally:
        win.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_zapisu_szuflady_szczegol_na_pasku_gospodarza(qapp, tmp_path, jezyk, lang, monkeypatch,
                                                              pola_inline):
    """Klik „Zatwierdź” w oknie gospodarza, cała operacja pada `OSError` 5 w wątku zapisu: pasek mówi
    zdaniem operacji, a surowy tekst systemu (plik, który padł) stoi w podpowiedzi paska i w polu
    raportu - nie tylko w szufladzie. Falsyfikator: ogon gestu emituje gołe zdanie."""
    jezyk(lang)
    path, con, _pliki = _baza_z_plikami(tmp_path, 1)
    con.close()
    win = MainWindow(str(path))
    try:
        win.resize(1400, 900)
        win.show()
        win._show_view(NAV_ZBIORY)
        v = win.grid_view
        _czekaj(lambda: not v._zbior_w_drodze() and v._frame_ids, "zbiór startu")
        _staging_makra(v)

        def _odmowa(*_a, **_k):
            raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _odmowa)
        QTest.mouseClick(v.drawer.btn_commit, Qt.LeftButton)
        oczek = i18n.t("grid.wb.op.commit", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
        _czekaj(lambda: win._pelny_komunikat == oczek, f"zdanie awarii: {win._pelny_komunikat!r}")
        assert szczegol_zdania(win._pelny_komunikat) == _tip()
        assert win.report_label.szczegol() == _tip()
        assert win.statusBar().toolTip() == oczek + "\n" + _tip()
    finally:
        _czekaj(lambda: not win.grid_view._wb.is_busy, "wątek zapisu")
        win.close()


def test_ogony_szuflady_niosa_szczegol_zdania_na_pasek(qapp, tmp_path):
    """Zapis z plikiem tylko do odczytu (prawdziwa odmowa dostępu), cofnięcie z błędem systemu
    i gest izolacji: zdanie paska to `ZdanieZeSzczegolem` ze szczegółem szuflady. Falsyfikator:
    `szczegol=` zdjęty z jednej z dróg."""
    path, con, pliki = _baza_z_plikami(tmp_path, 2)
    from horreum.gui.grid import FramesView
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    v.resize(1400, 800)
    v.show()
    zdania = _komunikaty(v)
    try:
        _staging_makra(v)
        os.chmod(pliki[0], stat.S_IREAD)
        try:
            QTest.mouseClick(v.drawer.btn_commit, Qt.LeftButton)
            _czekaj(lambda: not v._zbior_w_drodze() and zdania
                    and zdania[-1].startswith(i18n.t("grid.wb.status", summary="")), "zdanie zapisu")
        finally:
            os.chmod(pliki[0], stat.S_IREAD | stat.S_IWRITE)
        assert isinstance(zdania[-1], ZdanieZeSzczegolem)
        assert zdania[-1].szczegol and zdania[-1].szczegol == v.drawer.result.szczegol()
        assert i18n.t("wb.os_detail_tip", detail="") in zdania[-1].szczegol
        fr = writeback.FileResult(1, r"X:\L\a.fits", "failed", _odmowa_systemu())
        v._after_undo("undo", writeback.UndoResult(1, [], [], [fr]))
        _czekaj(lambda: not v._zbior_w_drodze()
                and zdania[-1].startswith(i18n.t("grid.wb.undo_status", msg="")), "zdanie cofnięcia")
        assert szczegol_zdania(zdania[-1]) == _tip()
        v._po_gescie_zapisu("zdanie gestu", [], _tip())
        _czekaj(lambda: not v._zbior_w_drodze() and zdania[-1].startswith("zdanie gestu"), "gest")
        assert szczegol_zdania(zdania[-1]) == _tip()
    finally:
        v.close()
        con.close()


def test_okno_sciezki_po_zamknieciu_zdanie_i_awaria_kart_na_pasku(sciezka_karty, monkeypatch):
    """Prawdziwe „Zatwierdź ze ścieżki…” (klik przycisku osi, klik „Zatwierdź” w oknie): baza nazwana,
    zapis kart pada `OSError` 5 (podmieniony rdzeń zapisu w miejscu). Po zamknięciu okna na pasek
    jedzie zdanie pola wyniku ORAZ pola błędu, ze szczegółem systemu - awaria kart żyła tylko w polu
    `error` zamkniętego okna. Falsyfikator: emisja samego pola `status`."""
    from horreum.gui import app as app_mod
    v, _con, _pliki, _fid = sciezka_karty

    def _odmowa(*_a, **_k):
        raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _odmowa)
    okna = []

    def _exec(dlg):
        """Modalne okno prowadzone ręką testu: prawdziwy klik „Zatwierdź”, zapis kart inline."""
        okna.append(dlg)
        dlg._runner.async_ok = False
        dlg.show()
        QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton)
        return QDialog.Accepted
    monkeypatch.setattr(app_mod.ConfirmPathObjectsDialog, "exec", _exec)
    v.resize(1200, 800)
    v.show()
    wiersz = next(r for r in range(v.review.count())                 # wiersz propozycji spod STOSÓW
                  if v.review.item(r).data(app_mod._REVIEW_PAYLOAD) == app_mod.PATH_STACKS_PAYLOAD)
    v.review.setCurrentRow(wiersz)
    zdania = _komunikaty(v)
    QTest.mouseClick(v.confirm_path_btn, Qt.LeftButton)
    dlg = okna[-1]
    blad = i18n.t("grid.wb.error", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
    assert dlg.assigned and dlg.error.text() == blad and dlg.status.text()
    assert zdania[-1] == dlg.status.text() + " - " + blad
    assert _tip() in szczegol_zdania(zdania[-1]).split("\n")


def test_szczegol_zyje_tyle_co_zdanie_przy_zmianie_miejsca(qapp, tmp_path, pola_inline):
    """Raport Zbiorów ze szczegółem gaśnie przy wejściu na Dom razem z podpowiedzią; raport ze
    szczegółem, któremu wołający nie podał miejsca, wiąże się z bieżącą stroną (AR-236) - gaśnie przy
    wejściu w Zbiory razem ze szczegółem. Falsyfikator: szczegół zdejmowany osobno od zdania."""
    path, con, _pliki = _baza_z_plikami(tmp_path, 1)
    con.close()
    win = MainWindow(str(path))
    try:
        win.show()
        win._show_view(NAV_ZBIORY)
        assert win._strona() == STRONA_ZBIORY
        win._flash_grid(ZdanieZeSzczegolem("wynik gestu", _tip()))
        assert win.report_label.szczegol() == _tip()
        win._show_view(NAV_DOM)
        assert win.report_label.text() == "" and win.report_label.szczegol() == ""
        assert win.statusBar().toolTip() == ""
        win._flash(ZdanieZeSzczegolem("bez miejsca", _tip()))
        assert win.report_label.text() == "bez miejsca" and win.report_label.szczegol() == _tip()
        win._show_view(NAV_ZBIORY)
        assert win.report_label.text() == "" and win.report_label.szczegol() == ""
    finally:
        win.close()


def _awaria_skanu(monkeypatch):
    """Skan Dostawy pada zerwanym udziałem (64) w PRAWDZIWYM wątku etapów; zwraca szczegół."""
    from horreum.gui import pipeline as pipeline_mod

    def _pada(*_a, **_k):
        raise OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)
    monkeypatch.setattr(pipeline_mod, "scan_tree", _pada)
    return i18n.t("wb.os_detail_tip", detail=r"OSError: [WinError 64] Komunikat systemu: 'X:\L\a.fits'")


def _drzewo(tmp_path):
    t = tmp_path / "dostawa"
    t.mkdir()
    _fits(t / "l0.fits", 0, "2024-03-15T21:30:45")
    return str(t)


def test_awaria_etapu_dostawy_szczegol_na_pasku_i_wyjscie_z_dostawy(qapp, tmp_path, monkeypatch,
                                                                     pola_inline):
    """Bieg „Przyjmij” pada na skanie: `PipelineView._on_failed` emituje `ZdanieZeSzczegolem` (zdanie
    etapu + szczegół systemu), pasek przy Dostawie mówi je z podpowiedzią; wyjście na Dom zdejmuje
    zdanie i szczegół z paska (raport związany z Dostawą), a błąd zostaje w polu Dostawy. Zdanie
    nazywa ETAP, który padł (skan), nie bieg łańcucha. Falsyfikatory: `_on_failed` z gołym zdaniem;
    `pipeline.status_message` wprost pod `_flash`; `failed` z nazwą biegu (`all`)."""
    szczegol = _awaria_skanu(monkeypatch)
    path = tmp_path / "d.db"
    db.open_db(str(path)).close()
    win = MainWindow(str(path))
    try:
        win.show()
        win._show_view(NAV_DOSTAWA)
        pv = win.pipeline_view
        odebrane = _komunikaty(pv)
        assert pv.run_all_on(_drzewo(tmp_path)) is None
        _czekaj(lambda: pv._thread is None and pv.last_run["failed"], "bieg Dostawy")
        from horreum.gui import pipeline as pipeline_mod
        zdanie = next(z for z in odebrane if isinstance(z, ZdanieZeSzczegolem))
        assert type(zdanie) is ZdanieZeSzczegolem and zdanie.szczegol == szczegol
        assert zdanie == i18n.t("pipeline.stage_failed_status", stage=pipeline_mod._stage_label("scan"))
        assert pv.last_run["failed"].startswith(
            i18n.t("pipeline.stage_failed_line", stage=pipeline_mod._stage_label("scan"), msg=""))
        assert win._pelny_komunikat == zdanie and win.report_label.szczegol() == szczegol
        win._show_view(NAV_DOM)
        assert win.report_label.text() == "" and win.report_label.szczegol() == ""
        assert pv.lbl_error.szczegol() == szczegol
    finally:
        win.close()


def test_planer_awaria_rachunku_niesie_szczegol_na_pasek(view, tmp_path):
    """Prawdziwa awaria bazy planera (plik bazy niedostępny): sygnał paska niesie `ZdanieZeSzczegolem`
    ze szczegółem SQLite z nagłówka. Falsyfikator: `_pokaz_blad` emituje gołe zdanie."""
    pasek = _komunikaty(view)
    view._db_path = str(tmp_path / "odpiety" / "planer.db")
    view._off_thread = False
    view.replan()
    zdanie = i18n.t("objchg.item.db_unavailable", db_code="SQLITE_CANTOPEN")
    assert type(pasek[-1]) is ZdanieZeSzczegolem and pasek[-1] == zdanie
    assert pasek[-1].szczegol == view.night_label.szczegol() != ""


def test_zniwa_przerwane_przebiegiem_dostawy_niosa_szczegol_awarii(qapp, tmp_path, monkeypatch,
                                                                   pola_inline):
    """Klik „Wciągnij z WBPP…”, żniwa ze stosem do rodowodu, potem bieg Dostawy pada na etapie: raport
    awarii Dostawy pada PRZED `run_finished`, a zdanie utraty rodowodu, które go zastępuje, mówi NA
    POCZĄTKU instrukcję ratunku, za nią wiersz awarii z jego szczegółem z zapisu przebiegu i
    podsumowanie okna żniw. Falsyfikatory: gałąź `failed` z gołym `status.harvest_lineage_lost`;
    wiersz awarii przed instrukcją."""
    from horreum import harvest
    szczegol = _awaria_skanu(monkeypatch)
    path = tmp_path / "z.db"
    db.open_db(str(path)).close()
    drzewo = _drzewo(tmp_path)

    class _OknoZniw:
        def __init__(self, *_a, **_k):
            self.summary = "Wciągnięto 1"
            self.harvested_root = drzewo
            self.harvested_stacks = [("sha-stosu", (1,), "NGC7000")]

        def exec(self):
            return QDialog.Accepted

    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    monkeypatch.setattr(harvest, "archive_root_from_db", lambda con: str(tmp_path), raising=False)
    win = MainWindow(str(path))
    try:
        win.show()
        win._show_view(NAV_DOSTAWA)
        pv = win.pipeline_view
        QTest.mouseClick(pv.btn_harvest, Qt.LeftButton)
        utrata = i18n.t("status.harvest_lineage_lost", n=1)
        _czekaj(lambda: pv._thread is None and utrata in win._pelny_komunikat, "raport po biegu")
        assert win._pelny_komunikat == " - ".join((utrata, pv.last_run["failed"], "Wciągnięto 1"))
        assert szczegol_zdania(win._pelny_komunikat) == szczegol
        assert win.statusBar().toolTip().endswith("\n" + szczegol)
    finally:
        win.close()


def test_zniwa_blad_biegu_szczegol_w_zdaniu_paska(qapp, tmp_path, ustawienia, monkeypatch, pola_inline):
    """Prawdziwe okno żniw, klik „Wciągnij”, wyjątek podmienionego rdzenia klasą systemu: `summary`
    mówi błąd klasą i niesie surowy tekst systemu w szczególe; gospodarz po zamknięciu okna (klik
    „Wciągnij z WBPP…” w Dostawie, prawdziwy szew `_on_open_harvest`) kładzie go w podpowiedzi
    paska. Falsyfikator: `_set_summary` bez szczegółu."""
    from horreum import harvest
    from test_gui_harvest import _baza, _czytnik, _dlg, _flat_cls, _wyjscie
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    dlg.show()
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def boom(*_a, **_kw):
        raise blad
    monkeypatch.setattr(harvest, "apply", boom)
    QTest.mouseClick(dlg.btn_apply, Qt.LeftButton)
    szczegol = wiersz_systemu(blad_systemu(blad))
    assert szczegol and dlg.summary.startswith(i18n.t("harvest.status_error", msg=""))
    assert szczegol_zdania(dlg.summary) == szczegol
    dlg.exec = lambda: QDialog.Rejected
    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = lambda *_a, **_k: dlg
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    path = tmp_path / "gosp.db"
    db.open_db(str(path)).close()
    win = MainWindow(str(path))
    try:
        win.show()
        win._show_view(NAV_DOSTAWA)
        QTest.mouseClick(win.pipeline_view.btn_harvest, Qt.LeftButton)
        assert win._pelny_komunikat == dlg.summary
        assert win.statusBar().toolTip() == str(dlg.summary) + "\n" + szczegol
    finally:
        win.close()
        con.close()


def test_zniwa_niezapisane_zeznanie_w_zdaniu_paska(qapp, tmp_path, ustawienia, monkeypatch):
    """Zeznanie biegu niezapisane (błąd systemu klasą), kopie leżą: zdanie paska mówi o tym członem
    (dawniej tylko notka zamkniętego okna) i niesie szczegół systemu. Falsyfikator: `_summary_tail`
    bez członu zeznania."""
    from horreum import projection
    from test_gui_harvest import _baza, _cel, _czytnik, _dlg, _flat_cls, _wyjscie
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    dlg.show()
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def zeznanie_pada(*_a, **_kw):
        raise blad
    monkeypatch.setattr(projection, "write_harvest_manifest", zeznanie_pada)
    QTest.mouseClick(dlg.btn_apply, Qt.LeftButton)
    czlon = i18n.t("harvest.manifest_error", err=i18n.t("objchg.item.os_share_lost", os_code="WinError 64"))
    assert dlg.summary == (i18n.t_plural("harvest.status_placed", 1, root=str(_cel(archive).parent))
                           + " · " + czlon)
    assert szczegol_zdania(dlg.summary) == wiersz_systemu(blad_systemu(blad)) != ""
    dlg.reject()
    con.close()


def test_zniwa_zeznanie_niezapisane_bez_kopii_nie_mowi_ze_kopie_leza(qapp, tmp_path, ustawienia,
                                                                     monkeypatch):
    """Bieg bez ani jednej kopii (kopia pada w rdzeniu) i niezapisane zeznanie: notka i zdanie paska
    mówią „zeznania nie zapisano”, NIE „Kopie leżą w archiwum, ale…” - zeznanie pisze się zawsze,
    także bez kopii. Falsyfikator: jeden klucz zeznania bez względu na kopie."""
    from horreum import harvest, projection
    from test_gui_harvest import _baza, _czytnik, _dlg, _flat_cls, _wyjscie
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    dlg.show()
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def _pada(*_a, **_kw):
        raise blad
    prawdziwy = harvest.apply
    monkeypatch.setattr(harvest, "apply", lambda plan, **kw: prawdziwy(plan, copy=_pada, **kw))
    monkeypatch.setattr(projection, "write_harvest_manifest", _pada)
    QTest.mouseClick(dlg.btn_apply, Qt.LeftButton)
    czlon = i18n.t("harvest.manifest_error_none", err=i18n.t("objchg.item.os_share_lost", os_code="WinError 64"))
    assert dlg.notice.text() == czlon
    assert (" · " + czlon) in dlg.summary and i18n.t("harvest.manifest_error", err="") not in dlg.summary
    assert szczegol_zdania(dlg.summary) == wiersz_systemu(blad_systemu(blad)) != ""
    dlg.reject()
    con.close()


def test_zniwa_zwykle_zamknij_po_bledzie_biegu_niesie_szczegol(qapp, tmp_path, ustawienia, monkeypatch):
    """Kopie położone, potem wyjątek rdzenia klasą systemu, klik „Zamknij” (bez przyjęcia): zdanie
    zwykłego zamknięcia (`done` - instrukcja przyjęcia, ścieżka na końcu) niesie błąd biegu i jego
    szczegół. Falsyfikator: `done` bez nośnika szczegółu."""
    from horreum import harvest
    from test_gui_harvest import _baza, _czytnik, _dlg, _flat_cls, _flat_ha, _wyjscie
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    dlg.show()
    prawdziwy = harvest.apply
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def po_kopiach(plan, **kw):
        prawdziwy(plan, **kw)
        raise blad
    monkeypatch.setattr(harvest, "apply", po_kopiach)
    QTest.mouseClick(dlg.btn_apply, Qt.LeftButton)
    przed = dlg.summary
    QTest.mouseClick(dlg.btn_close, Qt.LeftButton)
    klasa = i18n.t("objchg.item.os_share_lost", os_code="WinError 64")
    assert dlg.summary != przed and i18n.t("harvest.status_error", msg=klasa) in dlg.summary
    assert szczegol_zdania(dlg.summary) == wiersz_systemu(blad_systemu(blad)) != ""
    con.close()


def test_zniwa_stosy_do_rodowodu_i_blad_biegu_zdanie_mowi_blad(qapp, tmp_path, ustawienia, monkeypatch):
    """Okno ze stosami do rodowodu i bez kopii położonych w tym oknie, klik „Wciągnij” nowego mastera
    i wyjątek podmienionego rdzenia: zdanie paska mówi stosy ORAZ błąd, szczegół systemu w podpowiedzi.
    Dawniej zdanie główne mówiło stosy, a błąd znikał. Falsyfikator: człon błędu w `_summary_tail`
    tylko przy kopiach."""
    from horreum import harvest
    from test_gui_harvest import (_baza, _czytnik, _dlg, _dostawa_po_zwyklym_zamknij, _flat_ha, _pulpit,
                                  _wydanie_ic1795, _wyjscie)
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, _out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _czytnik(monkeypatch, zeznania)
    _pulpit(monkeypatch)
    ustawienia.setValue("pipeline/last_source", str(archive))
    dlg = _dlg(con, archive, work_root=str(work))
    dlg._on_apply()
    dlg.reject()
    seat = _dostawa_po_zwyklym_zamknij(con, archive)
    # Nowy master spoza wydania w innym wyjściu WBPP: stosy do rodowodu to fakt o archiwum okna,
    # więc zostają przy zmianie wyjścia, a „Wciągnij” ma co wciągnąć.
    _czytnik(monkeypatch, {**zeznania, "masterFlat_B.xisf": _flat_ha()})
    inne = _wyjscie(tmp_path, {"masterFlat_B.xisf": b"B"}, sub=("WBPP2", "master"))
    dlg2 = _dlg(con, archive, work_root=str(work))
    dlg2.show()
    dlg2._set_output(str(inne))
    stosy = f"Stosy do rodowodu dokładnego po Dostawie: 2 → {seat}"
    assert dlg2.summary == stosy and dlg2.btn_apply.isEnabled()
    blad = OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)

    def boom(*_a, **_kw):
        raise blad
    monkeypatch.setattr(harvest, "apply", boom)
    QTest.mouseClick(dlg2.btn_apply, Qt.LeftButton)
    klasa = i18n.t("objchg.item.os_share_lost", os_code="WinError 64")
    assert dlg2.summary == stosy + " · " + i18n.t("harvest.status_error", msg=klasa)
    assert szczegol_zdania(dlg2.summary) == wiersz_systemu(blad_systemu(blad)) != ""
    dlg2.reject()
    con.close()


# ============================================================ AR-220 - podgląd pozostałych po przerwaniu


def _brama_po_pierwszym_pliku(monkeypatch):
    """Wątek zapisu staje po postępie PIERWSZEGO pliku, aż test zwolni bramę (klik „Anuluj” trafia
    w bieg, nie przed nim i nie po nim)."""
    brama, doszlo = threading.Event(), threading.Event()
    prawdziwy = WritebackWorker._emit_progress

    def _postep(self, done, total, path, status):
        prawdziwy(self, done, total, path, status)
        if done == 1:
            doszlo.set()
            brama.wait(30)
    monkeypatch.setattr(WritebackWorker, "_emit_progress", _postep)
    return brama, doszlo


def _anuluj_w_biegu(view, brama, doszlo, stary):
    _czekaj(lambda: doszlo.is_set() and view.drawer.btn_cancel.isVisible(), "pierwszy plik")
    QTest.mouseClick(view.drawer.btn_cancel, Qt.LeftButton)
    brama.set()
    _czekaj(lambda: not view._wb.is_busy and not view._zbior_w_drodze()
            and view.model._preview is not stary, "ogon zapisu przerwanego")


def test_zapis_przerwany_anulowaniem_podglad_pozostalych_makra(trzy, monkeypatch):
    """Staging makra na trzech plikach, „Zatwierdź”, po pierwszym pliku „Anuluj” (prawdziwy wątek):
    szuflada mówi „2 do dokończenia”, a kolumna podglądu po przyłożeniu pokazuje WYŁĄCZNIE dwa
    oczekujące wpisy - zapisanej klatki w niej nie ma. Falsyfikator: podgląd przykładany razem ze
    zbiorem pusty (`_podglad_przy_przylozeniu` = `{}` w `_after_commit`, AR-250)."""
    view, con, _pliki = trzy
    _staging_makra(view)
    stary = view.model._preview
    assert len(stary) == 3
    brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
    QTest.mouseClick(view.drawer.btn_commit, Qt.LeftButton)
    _anuluj_w_biegu(view, brama, doszlo, stary)
    assert view._pending_count() == 2
    oczekujace = {w["frame_id"] for w in queries.pending_cards_for_run(con, view._run_id)}
    assert len(oczekujace) == 2 and set(view.model._preview) == oczekujace
    assert not view.table.isColumnHidden(view.model._preview_col())
    assert view.drawer.result.text().endswith(i18n.t("grid.wb.interrupted", n=2))


def test_zmiana_nazw_przerwana_anulowaniem_podglad_pozostalych(trzy, monkeypatch):
    """To samo dla nazw: staging trzech nazw, „Zatwierdź”, „Anuluj” po pierwszym pliku - podgląd
    „nazwa →” wyłącznie dwóch nazw, które czekają. Falsyfikator: podgląd przykładany razem ze zbiorem
    pusty (`_podglad_przy_przylozeniu` = `{}` w `_after_commit_rename`, AR-250)."""
    view, con, _pliki = trzy
    view._on_rename_stage(_POL)
    stary = view.model._preview
    assert len(stary) == 3 and view._rename_pending_count() == 3
    brama, doszlo = _brama_po_pierwszym_pliku(monkeypatch)
    QTest.mouseClick(view.drawer.btn_commit, Qt.LeftButton)
    _anuluj_w_biegu(view, brama, doszlo, stary)
    assert view._rename_pending_count() == 2
    oczekujace = {w["frame_id"] for w in queries.pending_renames_for_run(con, view._rename_run_id)}
    assert len(oczekujace) == 2 and set(view.model._preview) == oczekujace
    assert all(p["op"] == "rename" for p in view.model._preview.values())
    assert view.model._preview_label == i18n.t("grid.preview.name")
    assert not view.table.isColumnHidden(view.model._preview_col())


def test_oczekujace_nazwy_przebiegu_tylko_pending_tego_przebiegu(qapp, tmp_path):
    """`queries.pending_renames_for_run`: wiersze `pending` BIEŻĄCEGO przebiegu z klatką pod lokacją -
    bez zapisanych i bez cudzego przebiegu."""
    from horreum import repo
    _path, con, pliki = _baza_z_plikami(tmp_path, 3)
    lok = [r["id"] for r in con.execute("SELECT id FROM location ORDER BY id")]
    for i, lid in enumerate(lok):
        repo.stage_rename(con, run_id="A" if i < 2 else "B", location_id=lid, old_path=str(pliki[i]),
                          new_path=str(pliki[i]) + ".nowa", expected_mtime=None)
    con.execute("UPDATE pending_renames SET status = 'applied' WHERE location_id = ?", (lok[0],))
    con.commit()
    wiersze = queries.pending_renames_for_run(con, "A")
    fid = con.execute("SELECT frame_id FROM location WHERE id = ?", (lok[1],)).fetchone()[0]
    assert [(w["frame_id"], w["new_path"]) for w in wiersze] == [(fid, str(pliki[1]) + ".nowa")]
    con.close()


# ============================================================ AR-221 - ścieżka łamana w malowaniu


_SCIEZKA = (r"X:\ObiektyGlebokiegoNieba\NGC7000Pelikan\Noc20240315"
            r"\masterLight_BIN-1_6248x4176_EXPOSURE-120.00s_FILTER-NoFilter_RGB_OBJ-23_fastIntegration.xisf")
_ZDANIE = f"BŁĄD: plik zajęty przez inny program ({_SCIEZKA})"


def test_pole_zdania_lamie_sciezke_w_malowaniu(qapp):
    """Ścieżka z segmentem DŁUŻSZYM od pola (wzór najszerszych segmentów archiwum - z `-` w środku)
    mieści się w polu łamana po `\\` (miejsca łamania wyłącznie w tekście malowanym), a `text()`,
    podpowiedź i nazwa dostępności są bez znaku łamania. Szerokość pola z TREŚCI: krótsza od nazwy
    pliku, szersza od najdłuższego kawałka między miejscami łamania. Falsyfikator: tekst malowany
    bez U+200B - blok szerszy od pola."""
    pole = EtykietaBledu("")
    pole.setWordWrap(True)
    pole.ustaw(_ZDANIE, _tip())
    malowany = QLabel.text(pole)
    assert pole.text() == _ZDANIE and _LAMANIE not in pole.toolTip() + pole.accessibleName()
    assert malowany.count("\\" + _LAMANIE) == _SCIEZKA.count("\\")
    fm = QFontMetrics(pole.font())
    plik = _SCIEZKA.rsplit("\\", 1)[1]
    # Najdłuższy kawałek nazwy, którego Qt nie łamie (`-` przed cyfrą wiąże) - pole o włos szersze.
    szer = fm.horizontalAdvance("masterLight_BIN-1_6248x4176_EXPOSURE-120.00s_FILTER-") + 4
    assert fm.horizontalAdvance(plik) > szer                      # segment dłuższy od pola
    flagi = int(Qt.TextWordWrap)
    assert fm.boundingRect(QRect(0, 0, szer, 10 ** 5), flagi, _ZDANIE).width() > szer   # bez łamania
    assert fm.boundingRect(QRect(0, 0, szer, 10 ** 5), flagi, malowany).width() <= szer


def test_kopia_pola_zaznaczalnego_bez_znaku_lamania(qapp):
    """Pole zaznaczalne ze ścieżką (status okien kart, notki żniw): Ctrl+C (prawdziwy klawisz) i menu
    prawego kliku - także BEZ szczegółu, gdzie menu Qt kopiowałoby znak łamania - kopiują zdanie
    bez U+200B. Falsyfikatory: bez `keyPressEvent`; `selectedText` bez czyszczenia; menu domyślne."""
    pole = EtykietaBledu("")
    pole.setWordWrap(True)
    pole.setTextInteractionFlags(Qt.TextSelectableByMouse)
    pole.resize(300, 120)
    pole.show()
    try:
        pole.ustaw(_ZDANIE)
        pole.setSelection(0, len(QLabel.text(pole)))
        pole.setFocus()
        QGuiApplication.clipboard().setText("")
        QTest.keyClick(pole, Qt.Key_C, Qt.ControlModifier)
        assert QGuiApplication.clipboard().text() == _ZDANIE
        prawy_klik(pole)
        pozycje = menu_pola_otwarte(pole)
        assert list(pozycje) == [i18n.t("wb.copy_selection"), i18n.t("wb.copy_sentence")]
        pozycje[i18n.t("wb.copy_selection")].trigger()
        assert QGuiApplication.clipboard().text() == _ZDANIE
        pozycje[i18n.t("wb.copy_sentence")].trigger()
        assert QGuiApplication.clipboard().text() == _ZDANIE
        pole._menu.hide()
        pole.ustaw(_ZDANIE, _tip())
        prawy_klik(pole)
        assert list(menu_pola_otwarte(pole))[-1] == i18n.t("wb.copy_detail")
        pole._menu.hide()
    finally:
        pole.close()


# ============================================================ AR-227 - zdania paska bez żargonu


def _formy(wpis):
    return list(wpis.values()) if isinstance(wpis, dict) else [wpis]


def test_zdania_paska_bez_zargonu():
    """Bramka katalogu: żadna wartość PL nie zaczyna się od „Writeback”/„Undo”/„Rename”, żadna EN od
    „Writeback:”/„Undo:”/„Undo names:”/„Rename:” (EN „Undo …” jako czasownik przycisku zostaje).
    Falsyfikator: jeden z ośmiu kluczy wraca do żargonu."""
    zle = []
    for klucz, wpis in CATALOG.items():
        if not isinstance(wpis, dict):
            continue
        for s in _formy(wpis.get("pl")):
            if isinstance(s, str) and s.lstrip().startswith(("Writeback", "Undo", "Rename")):
                zle.append((klucz, s))
        for s in _formy(wpis.get("en")):
            if isinstance(s, str) and s.lstrip().startswith(("Writeback:", "Undo:", "Undo names:", "Rename:")):
                zle.append((klucz, s))
        # Człony zdań szuflady i paska (separator powodu, przerwanie) - myślnik zwykły, nie pauza.
        if klucz.startswith(("grid.wb.", "grid.rename.", "grid.macro.", "wb.")):
            zle += [(klucz, s) for s in _formy(wpis.get("pl")) + _formy(wpis.get("en"))
                    if isinstance(s, str) and set(s) & {"\N{EN DASH}", "\N{EM DASH}"}]
    assert zle == []


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_pasek_po_zapisie_i_cofnieciu_mowi_zdaniem_gestu(qapp, tmp_path, jezyk, lang):
    """Prawdziwy zapis i „Cofnij” w szufladzie (kliki) oraz zmiana nazw i jej cofnięcie: zdanie paska
    zaczyna się podmiotem operacji z „zakończony”, bez żargonu. Falsyfikator: stary klucz z „Writeback:”."""
    jezyk(lang)
    _path, con, _pliki = _baza_z_plikami(tmp_path, 2)
    from horreum.gui.grid import FramesView
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    v.resize(1400, 800)
    v.show()
    zdania = _komunikaty(v)
    try:
        for start, klucz in ((lambda: _staging_makra(v), "grid.wb.status"),
                             (None, "grid.wb.undo_status"),
                             (lambda: v._on_rename_stage(_POL), "grid.rename.status_summary"),
                             (None, "grid.rename.undo_status")):
            if start is not None:
                start()
                QTest.mouseClick(v.drawer.btn_commit, Qt.LeftButton)
            else:
                QTest.mouseClick(v._undo_btn, Qt.LeftButton)
            glowa = i18n.t(klucz, summary="", msg="")
            _czekaj(lambda: not v._zbior_w_drodze() and zdania and zdania[-1].startswith(glowa),
                    f"{klucz}: {zdania[-1:]}")
            assert "Writeback" not in zdania[-1], zdania[-1]
            assert not zdania[-1].startswith(("Undo:", "Undo names:", "Rename:", "Undo nazw")), zdania[-1]
            if lang == "en":
                assert not set(glowa) & _POLSKIE, glowa
    finally:
        v.close()
        con.close()


# ============================================================ AR-226 - odmiana liczby zmian


_ODMIANA_PL = {
    "grid.rename.staged": ("Do stagingu nazw: {} zmiana", "Do stagingu nazw: {} zmiany",
                           "Do stagingu nazw: {} zmian"),
    "grid.macro.staged": ("Do stagingu: {} zmiana", "Do stagingu: {} zmiany", "Do stagingu: {} zmian"),
    "grid.wb.rejected": ("Odrzucono {} zmianę", "Odrzucono {} zmiany", "Odrzucono {} zmian"),
    "grid.rename.rejected": ("Odrzucono {} zmianę nazwy", "Odrzucono {} zmiany nazw",
                             "Odrzucono {} zmian nazw"),
    "grid.wb.renamed": ("{} przemianowany", "{} przemianowane", "{} przemianowanych"),
}
_ODMIANA_EN = {
    "grid.rename.staged": ("To name staging: {} change", "To name staging: {} changes"),
    "grid.macro.staged": ("To staging: {} change", "To staging: {} changes"),
    "grid.wb.rejected": ("Discarded {} change", "Discarded {} changes"),
    "grid.rename.rejected": ("Discarded {} name change", "Discarded {} name changes"),
    "grid.wb.renamed": ("{} renamed", "{} renamed"),
}


@pytest.mark.parametrize("klucz", sorted(_ODMIANA_PL))
def test_odmiana_liczby_zmian(jezyk, klucz):
    """Pięć wpisów mnogich rodziny szuflady: PL 1 / 2 / 5 / 12 / 22 (jeden, kilka, wiele, -naście,
    dwadzieścia kilka), EN 1 / 2; EN bez polskich liter. Falsyfikator: wpis prosty („1 zmian”)."""
    one, few, many = _ODMIANA_PL[klucz]
    for n, forma in ((1, one), (2, few), (5, many), (12, many), (22, few)):
        assert i18n.t_plural(klucz, n, s=0, target="cel").startswith(forma.format(n)), (klucz, n)
    jezyk("en")
    for n, forma in zip((1, 2), _ODMIANA_EN[klucz]):
        tekst = i18n.t_plural(klucz, n, s=0, target="t")
        assert tekst.startswith(forma.format(n)) and not set(tekst) & _POLSKIE, (klucz, n)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_staging_i_odrzucenie_jednej_zmiany_mowia_liczbe_pojedyncza(qapp, tmp_path, jezyk, lang):
    """Prawdziwy staging nazw na JEDNEJ zaznaczonej klatce (klik w komórkę), „Odrzuć” w szufladzie,
    staging makra na jednej klatce i „Odrzuć”: zdania mówią „1 zmiana” / „1 zmianę” (EN „1 change”).
    Falsyfikator: wołający przez `i18n.t` (wpis mnogi oddaje klucz)."""
    jezyk(lang)
    _path, con, _pliki = _baza_z_plikami(tmp_path, 2)
    from horreum.gui.grid import FramesView
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    v.resize(1400, 800)
    v.show()
    zdania = _komunikaty(v)
    try:
        _klik_komorki(v, v._frame_ids[0], 1)
        v._on_rename_stage(_POL)
        assert zdania[-1].startswith(_ODMIANA_PL["grid.rename.staged"][0].format(1) if lang == "pl"
                                     else _ODMIANA_EN["grid.rename.staged"][0].format(1)), zdania[-1]
        QTest.mouseClick(v.drawer.btn_reject, Qt.LeftButton)
        assert zdania[-1].startswith(_ODMIANA_PL["grid.rename.rejected"][0].format(1) if lang == "pl"
                                     else _ODMIANA_EN["grid.rename.rejected"][0].format(1)), zdania[-1]
    finally:
        v.close()
        con.close()
    view2, con2, _p = _widok_nad(qapp, tmp_path)                 # jedna klatka (`wb.fits`, `wb.db`)
    zdania2 = _komunikaty(view2)
    try:
        view2.show()
        _staging_makra(view2)
        assert zdania2[-1].startswith(_ODMIANA_PL["grid.macro.staged"][0].format(1) if lang == "pl"
                                      else _ODMIANA_EN["grid.macro.staged"][0].format(1)), zdania2[-1]
        QTest.mouseClick(view2.drawer.btn_reject, Qt.LeftButton)
        assert zdania2[-1].startswith(_ODMIANA_PL["grid.wb.rejected"][0].format(1) if lang == "pl"
                                      else _ODMIANA_EN["grid.wb.rejected"][0].format(1)), zdania2[-1]
    finally:
        view2.close()
        con2.close()


def test_zdanie_wyniku_nazw_odmienia_przemianowane(qapp):
    """`grid.wb.renamed` przez `zdanie_wyniku_zapisu` (wpis mnogi wybiera `t_plural` sam): „1
    przemianowany”, „2 przemianowane”. Falsyfikator: wpis prosty („1 przemianowanych”)."""
    from horreum.gui.wb_worker import zdanie_wyniku_zapisu
    for n, forma in ((1, "1 przemianowany"), (2, "2 przemianowane"), (5, "5 przemianowanych")):
        applied = [writeback.FileResult(i, rf"X:\L\{i}.fits", "applied", None) for i in range(n)]
        assert zdanie_wyniku_zapisu(writeback.CommitResult("r", None, applied, [], [], []),
                                    "grid.wb.renamed") == forma
    assert podpowiedz_kart(writeback.CommitResult("r", None, [], [], [], [])) == ""


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_naglowek_okna_naprawy_odmienia_klatki_i_foldery(jezyk, lang):
    """Nagłówek „Napraw nagłówek…”: liczba klatek i liczba folderów odmienione (PL 1 / 2 / 5 / 12 / 22,
    EN one / other) - było „1 klatek w 1 folderach”; EN bez polskich znaków (było „„Resolve””).
    Falsyfikator: wpis prosty z `{frames}`/`{groups}`."""
    jezyk(lang)
    oczek = {"pl": {1: "1 klatka w 1 folderze", 2: "2 klatki w 2 folderach", 5: "5 klatek w 5 folderach",
                    12: "12 klatek w 12 folderach", 22: "22 klatki w 22 folderach"},
             "en": {1: "1 frame in 1 folder", 2: "2 frames in 2 folders", 5: "5 frames in 5 folders"}}[lang]
    for n, poczatek in oczek.items():
        zdanie = i18n.t_plural("repair.head", n, groups=i18n.t_plural("repair.head_groups", n))
        assert zdanie.startswith(poczatek + ". "), zdanie
        if lang == "en":
            assert not set(zdanie) & _POLSKIE, zdanie


def test_okno_naprawy_mowi_naglowkiem_z_odmiana(qapp, tmp_path):
    """Prawdziwe okno „Napraw nagłówek…” nad jedną klatką w jednym folderze: nagłówek „1 klatka
    w 1 folderze”. Falsyfikator: wołający przez `i18n.t` z `frames`/`groups`."""
    from test_gui_object_change import _lighty, _okno_naprawy
    con = db.open_db(str(tmp_path / "naprawa.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=7)
    dlg = _okno_naprawy(con)
    try:
        teksty = [w.text() for w in dlg.findChildren(QLabel)]
        assert any(t.startswith("1 klatka w 1 folderze. ") for t in teksty), teksty
    finally:
        dlg.reject()
        con.close()


# ============================================================ AR-218 - zdanie awarii po zakończonym etapie


def test_awaria_miedzy_etapami_dostawy_mowi_nazwa_biegu(qapp, tmp_path, monkeypatch, pola_inline):
    """Skan Dostawy się UDAJE, a pada praca łańcucha przed następnym etapem (kandydaci faktów kopii,
    przed `on_start`): zdanie awarii nazywa bieg („Przyjmij nowe”), nie skan, który się już udał.
    Falsyfikator: nazwa etapu nie schodzi po `stage_done` (`_zakoncz_etap` bez `_etap = None`)."""
    from horreum.gui import pipeline as pipeline_mod
    prawdziwy = scan.copy_facts_candidates

    def _pada(con, root=None, **kw):
        """Pada wyłącznie wołanie łańcucha (z korzeniem przebiegu); liczniki okien bez korzenia - jak były."""
        if root is None:
            return prawdziwy(con, **kw)
        raise OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)
    monkeypatch.setattr(scan, "copy_facts_candidates", _pada)
    path = tmp_path / "d.db"
    db.open_db(str(path)).close()
    win = MainWindow(str(path))
    try:
        win.show()
        win._show_view(NAV_DOSTAWA)
        pv = win.pipeline_view
        odebrane = _komunikaty(pv)
        assert pv.run_all_on(_drzewo(tmp_path)) is None
        _czekaj(lambda: pv._thread is None and pv.last_run["failed"], "bieg Dostawy")
        zdanie = next(z for z in odebrane if isinstance(z, ZdanieZeSzczegolem))
        assert pipeline_mod._stage_label("all") == i18n.t("pipeline.receive")
        assert zdanie == i18n.t("pipeline.stage_failed_status", stage=i18n.t("pipeline.receive"))
        assert pipeline_mod._stage_label("scan") not in zdanie
    finally:
        win.close()


def test_okno_sciezki_udane_ponowienie_nie_niesie_starej_awarii(sciezka_karty, monkeypatch):
    """„Zatwierdź ze ścieżki…”: pierwszy klik „Zatwierdź” - zapis kart pada (`OSError` 5), drugi klik po
    przywróceniu rdzenia - zapis się udaje; po zamknięciu okna pasek mówi wynik bez dawnej awarii,
    a pole błędu jest puste. Falsyfikator: `_on_confirm` bez zdjęcia błędu poprzedniej próby."""
    from horreum.gui import app as app_mod
    v, _con, _pliki, _fid = sciezka_karty
    prawdziwy = WritebackWorker._OPS["commit"]

    def _odmowa(*_a, **_k):
        raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)
    okna = []

    def _exec(dlg):
        okna.append(dlg)
        dlg._runner.async_ok = False
        dlg.show()
        WritebackWorker._OPS["commit"] = _odmowa
        try:
            QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton)
        finally:
            WritebackWorker._OPS["commit"] = prawdziwy
        assert dlg.error.text() and dlg.confirm_btn.isEnabled()
        QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton)
        return QDialog.Accepted
    monkeypatch.setattr(app_mod.ConfirmPathObjectsDialog, "exec", _exec)
    v.resize(1200, 800)
    v.show()
    wiersz = next(r for r in range(v.review.count())
                  if v.review.item(r).data(app_mod._REVIEW_PAYLOAD) == app_mod.PATH_STACKS_PAYLOAD)
    v.review.setCurrentRow(wiersz)
    zdania = _komunikaty(v)
    QTest.mouseClick(v.confirm_path_btn, Qt.LeftButton)
    dlg = okna[-1]
    assert dlg.error.text() == "" and dlg.error.szczegol() == ""
    assert zdania[-1] == dlg.status.text() + _czlon_cofniecia(dlg._commit_id)
    assert _tip() not in szczegol_zdania(zdania[-1])


# ============================================================ AR-235, AR-243 - pole zdania: tekst zwykły, menu

import re  # noqa: E402

from horreum.gui.app import NAV_PORZADKI  # noqa: E402

from test_gui_app_object import NOW_PD, _nameless_tree, _select_review_tag, repair  # noqa: E402,F401

_ZNACZNIK = r"BŁĄD: plik zajęty przez inny program (X:\L\<a>.fits)"


def test_pole_zdania_tekst_zwykly_nazwa_w_ksztalcie_znacznika(qapp):
    """AR-235: zdanie z nazwą pliku w kształcie znacznika HTML (`<a>.fits`) - pole pokazuje je
    całe: zaznaczenie całości to całe zdanie, render pola bez zawijania nie węższy od zdania. Klasa
    i podklasa szuflady (`_ZdanieWyniku`) w formacie tekstu zwykłego. Falsyfikator: `AutoText`
    (domyślny `QLabel`) - Qt bierze `<a>` za znacznik: zaznaczenie puste, render krótszy o `<a>`
    (zmierzone natywnie: 247 px zamiast 270 px)."""
    from horreum.gui.grid_selection import _ZdanieWyniku
    assert EtykietaBledu("").textFormat() == Qt.PlainText == _ZdanieWyniku("").textFormat()
    pole = EtykietaBledu("")
    pole.setWordWrap(True)
    pole.setTextInteractionFlags(Qt.TextSelectableByMouse)
    pole.resize(900, 60)
    pole.show()
    pasek = EtykietaBledu("")
    try:
        pole.ustaw(_ZNACZNIK)
        pole.setSelection(0, len(QLabel.text(pole)))
        assert pole.selectedText() == _ZNACZNIK
        pasek.ustaw(_ZNACZNIK)
        assert pasek.sizeHint().width() >= pasek.fontMetrics().horizontalAdvance(_ZNACZNIK)
    finally:
        pole.close()


def test_pole_bledu_okna_zapisu_bez_szczegolu_prawy_klik_kopiuje_sciezke(repair, monkeypatch):
    """AR-243 (wizytacja natywna): prawdziwe okno „Napraw nagłówek…”, klik „Zapisz karty”,
    plik zajęty przez inny program (kod 32 - poza klasami, więc BEZ szczegółu, a ścieżka w zdaniu):
    pole błędu jest niezaznaczalne, a prawdziwy prawy klik otwiera na nim menu „Kopiuj zdanie”,
    które kopiuje zdanie ze ścieżką bez znaku łamania. Falsyfikator: menu własne tylko na polu
    zaznaczalnym (warunek sprzed AR-243) - prawy klik bez menu, ścieżki nie ma czym skopiować."""
    _v, _con, _files, _open = repair

    def _zajety(*_a, **_k):
        raise OSError(None, "Proces nie może uzyskać dostępu do pliku.", r"X:\L\a.fits", 32)
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _zajety)
    dlg = _open()
    dlg.show()
    try:
        QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        assert r"X:\L\a.fits" in dlg.error.text() and dlg.error.szczegol() == ""
        assert not dlg.error.textInteractionFlags() & Qt.TextSelectableByMouse
        assert _LAMANIE in QLabel.text(dlg.error)
        prawy_klik(dlg.error)
        pozycje = menu_pola_otwarte(dlg.error)
        assert list(pozycje) == [i18n.t("wb.copy_sentence")]
        QGuiApplication.clipboard().setText("")
        pozycje[i18n.t("wb.copy_sentence")].trigger()
        assert QGuiApplication.clipboard().text() == dlg.error.text()
        dlg.error._menu.hide()
    finally:
        dlg.reject()


def test_raport_paska_bez_sciezki_i_szczegolu_prawy_klik_kopiuje_cale_zdanie(qapp):
    """AR-243, wariant szeroki: KAŻDE niepuste pole niezaznaczalne ma „Kopiuj zdanie” - także raport
    paska gospodarza bez ścieżki i bez szczegółu, ucięty elizją do zapasu paska: kopia to PEŁNE
    zdanie. Pole puste menu własnego nie dostaje. Falsyfikator: menu własne tylko przy ścieżce albo
    szczególe (wariant wąski) - raport bez obu zostaje bez drogi do schowka."""
    win = MainWindow()
    try:
        win.resize(700, 400)
        win.show()
        QApplication.processEvents()
        dlugie = "Wciągnięto 3 mastery z wyjścia WBPP; " * 8
        win._flash(dlugie)
        assert win.report_label.text().endswith("…") and _LAMANIE not in QLabel.text(win.report_label)
        prawy_klik(win.report_label)
        pozycje = menu_pola_otwarte(win.report_label)
        assert list(pozycje) == [i18n.t("wb.copy_sentence")]
        pozycje[i18n.t("wb.copy_sentence")].trigger()
        assert QGuiApplication.clipboard().text() == dlugie
        win.report_label._menu.hide()
        menu = win.report_label._menu
        win._wygas_raport()
        prawy_klik(win.report_label)
        assert win.report_label._menu is menu                        # puste pole - nowe menu nie powstaje
    finally:
        win.close()


# ============================================================ AR-236 - raport ze szczegółem bez wygasania


def _czekaj_ms(ms):
    """Prawdziwy zegar: pętla zdarzeń przez `ms` milisekund (`processEvents` + `sleep`)."""
    koniec = time.monotonic() + ms / 1000
    while time.monotonic() < koniec:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.005)


def _okno_na_zbiorach(tmp_path):
    path, con, _pliki = _baza_z_plikami(tmp_path, 1)
    con.close()
    win = MainWindow(str(path))
    win.show()
    win._show_view(NAV_ZBIORY)
    _czekaj(lambda: not win.grid_view._zbior_w_drodze() and win.grid_view._frame_ids, "zbiór startu")
    QApplication.processEvents()
    return win


def test_raport_ze_szczegolem_nie_gasnie_zegarem_i_gasnie_z_miejscem(qapp, tmp_path, pola_inline):
    """AR-236, prawdziwy zegar (czas życia skrócony do 50 ms): raport ze szczegółem stoi po 300 ms
    i jest związany z bieżącą stroną, zdanie bez szczegółu gaśnie zegarem jak dawniej; raport ze
    szczegółem bez miejsca od wołającego gaśnie przy wejściu na Dom; raport z tła z JAWNYM brakiem
    wiązania (`_flash_dostawy` poza Dostawą) przeżywa nawigację i zegar - gaśnie dopiero następny
    raport. Falsyfikatory: `ms` raportu ze szczegółem bez zmiany (gaśnie po 50 ms); pominięte miejsce
    bez wiązania (przeżywa wejście na Dom); jawne `None` wiązane z bieżącą stroną (gaśnie z nią)."""
    win = _okno_na_zbiorach(tmp_path)
    try:
        win._flash(ZdanieZeSzczegolem("awaria zapisu", _tip()), ms=50)
        _czekaj_ms(300)
        assert win.report_label.text() == "awaria zapisu" and win.report_label.szczegol() == _tip()
        assert win._miejsce_komunikatu == STRONA_ZBIORY and not win._zegar_raportu.isActive()
        win._flash("zdanie bez szczegółu", ms=50)
        _czekaj(lambda: win.report_label.text() == "", "zdanie bez szczegółu gaśnie zegarem", s=5)
        win._flash(ZdanieZeSzczegolem("bez miejsca", _tip()))
        win._show_view(NAV_DOM)
        assert win.report_label.text() == "" and win.report_label.szczegol() == ""
        assert win.statusBar().toolTip() == ""
        win._flash_dostawy(ZdanieZeSzczegolem("awaria etapu z tła", _tip()))
        assert win._miejsce_komunikatu is None and not win._zegar_raportu.isActive()
        win._show_view(NAV_ZBIORY)
        _czekaj_ms(100)
        assert win.report_label.text() == "awaria etapu z tła" and win.report_label.szczegol() == _tip()
        win._flash("następny raport")
        assert win.report_label.szczegol() == ""
    finally:
        win.close()


def test_raport_ze_szczegolem_ustepuje_zdaniu_etapu_po_oknie_priorytetu(qapp, tmp_path, pola_inline):
    """AR-236 × AR-97: zdanie etapu Dostawy, które nadeszło w oknie priorytetu raportu ze szczegółem,
    czeka do końca okna i wtedy zastępuje raport (okno skrócone do 100 ms, prawdziwy zegar) - raport
    ze szczegółem nie wstrzymuje stanu etapu dłużej niż raport zwykły. Falsyfikator: zdanie etapu
    czekające do zgaśnięcia raportu ze szczegółem (zmiana AR-97 bez decyzji)."""
    win = _okno_na_zbiorach(tmp_path)
    try:
        win._zegar_priorytetu.setInterval(100)
        win._flash(ZdanieZeSzczegolem("awaria zapisu", _tip()))
        win._raport_etapu("Grupowanie: gotowe.")
        assert win.report_label.text() == "awaria zapisu"
        _czekaj(lambda: win.report_label.text() == "Grupowanie: gotowe.", "zdanie etapu po oknie", s=5)
        assert win.report_label.szczegol() == "" and win.statusBar().toolTip() == "Grupowanie: gotowe."
    finally:
        win.close()


def _naprawa_reka_testu(monkeypatch, akcja):
    """`RepairHeaderDialog.exec` prowadzony ręką testu: zapis inline, `akcja(dlg)` (prawdziwe kliki),
    zamknięcie. Zwraca listę otwartych okien."""
    from horreum.gui import app as app_mod
    okna = []

    def _exec(dlg):
        okna.append(dlg)
        dlg._runner.async_ok = False
        dlg.show()
        akcja(dlg)
        return QDialog.Rejected
    monkeypatch.setattr(app_mod.RepairHeaderDialog, "exec", _exec)
    return okna


def _odmowa_zapisu(*_a, **_k):
    raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)


def test_okno_naprawy_po_zamknieciu_wynik_na_pasku(repair, monkeypatch):
    """AR-236: prawdziwy klik „Napraw nagłówek…” na kubełku bezimiennych i klik „Zapisz karty”:
    zapis pada `OSError` 5 - po zamknięciu okna widok osi emituje zdanie pola błędu ze szczegółem
    (plik, który padł); okno zamknięte bez biegu nie mówi nic; udany zapis - zdanie wyniku.
    Falsyfikatory: `_on_repair` bez emisji; emisja bez warunku biegu; zdanie bez nośnika szczegółu."""
    v, _con, _files, _open = repair
    v.resize(1200, 800)
    v.show()
    zdania = _komunikaty(v)
    blad = i18n.t("grid.wb.error", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _odmowa_zapisu)
    okna = _naprawa_reka_testu(monkeypatch, lambda dlg: QTest.mouseClick(dlg.save_btn, Qt.LeftButton))
    _select_review_tag(v, "nameless")
    QTest.mouseClick(v.repair_btn, Qt.LeftButton)
    assert okna and zdania[-1] == blad and szczegol_zdania(zdania[-1]) == _tip()
    ile = len(zdania)
    _naprawa_reka_testu(monkeypatch, lambda dlg: None)
    _select_review_tag(v, "nameless")
    QTest.mouseClick(v.repair_btn, Qt.LeftButton)
    assert len(zdania) == ile                                        # bez biegu - cisza
    monkeypatch.undo()
    okna = _naprawa_reka_testu(monkeypatch, lambda dlg: QTest.mouseClick(dlg.save_btn, Qt.LeftButton))
    zdania.clear()
    _select_review_tag(v, "nameless")
    QTest.mouseClick(v.repair_btn, Qt.LeftButton)
    dlg = okna[-1]
    assert zdania == [dlg.status.text() + _czlon_cofniecia(dlg._commit_id)] and "commit" in zdania[0]
    assert szczegol_zdania(zdania[0]) == _szczegol_polecenia(_con, dlg._commit_id)     # AR-283


def test_wynik_okna_naprawy_na_pasku_przezywa_nawigacje_i_zegar(qapp, tmp_path, monkeypatch, pola_inline):
    """AR-236, gospodarz: wynik „Napraw nagłówek…” z awarią zapisu idzie drogą wyniku gestu osi
    (`_raport_miejsca(wiaz=False)` - jak „Zatwierdź ze ścieżki…”): stoi na pasku ze szczegółem, bez
    zegara i bez wiązania - przejście na Dom go nie zdejmuje, zdejmuje go następny raport.
    Falsyfikatory: wiązanie jawnego `None` z bieżącą stroną (gaśnie przy przejściu); zegar 5 s."""
    path = tmp_path / "naprawa.db"
    con = db.open_db(str(path))
    for p in _nameless_tree(tmp_path):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD,
                           summary=scan.ScanSummary())
    con.close()
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _odmowa_zapisu)
    _naprawa_reka_testu(monkeypatch, lambda dlg: QTest.mouseClick(dlg.save_btn, Qt.LeftButton))
    win = MainWindow(str(path))
    try:
        win.resize(1400, 900)
        win.show()
        win._show_view(NAV_PORZADKI)
        from horreum.gui import tasks as tasks_mod
        win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_OBJECTS)
        os_ = win.object_view
        os_.refresh()
        QApplication.processEvents()
        _select_review_tag(os_, "nameless")
        QTest.mouseClick(os_.repair_btn, Qt.LeftButton)
        blad = i18n.t("grid.wb.error", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
        assert win._pelny_komunikat == blad and win.report_label.szczegol() == _tip()
        assert win._miejsce_komunikatu is None and not win._zegar_raportu.isActive()
        win._show_view(NAV_DOM)
        QApplication.processEvents()
        assert win.report_label.text() == blad and win.report_label.szczegol() == _tip()
        assert win.statusBar().toolTip() == blad + "\n" + _tip()
        win._flash("następny raport")
        assert win.report_label.szczegol() == ""
    finally:
        win.close()


# ============================================================ AR-237 - miejsce w kodzie błędu programu

_DYSK = re.compile(r"[A-Za-z]:[\\/]")


def _miejsce(detail):
    """`(plik, linia)` z końcówki ` @ horreum/<plik>.py:<linia>` szczegółu albo None."""
    m = re.search(r" @ (horreum/[\w/]+\.py):(\d+)$", detail)
    return (m.group(1), int(m.group(2))) if m else None


def _linia_pakietu(plik, nr):
    import horreum
    return (pathlib.Path(horreum.__file__).parent.parent / plik).read_text(encoding="utf-8").splitlines()[nr - 1]


def test_blad_programu_miejsce_w_kodzie_z_najglebszej_ramki_pakietu(qapp, tmp_path, monkeypatch):
    """AR-237: prawdziwy błąd biblioteki (`json` na uszkodzonym assecie planera) wołanej z kodu
    pakietu - szczegół techniczny kończy się miejscem w `horreum` (linia `targets.py`, która wołała
    `json.loads`), względnym, z ukośnikiem `/`; zdanie bez zmian. Falsyfikatory: ostatnia ramka śladu
    bez filtra pakietu (`[-1]` - plik `json` ze ścieżką instalacji Pythona); ścieżka absolutna."""
    from horreum import targets
    zly = tmp_path / "targets_zly.json"
    zly.write_text("{", encoding="utf-8")
    monkeypatch.setattr(targets, "_asset_file", lambda layer: zly)
    try:
        targets.load_targets()
    except ValueError as exc:
        wyjatek = exc
    else:
        raise AssertionError("uszkodzony asset nie rzucił")
    powod = powod_okna(wyjatek)
    detail = dict(powod.params)["detail"]
    assert str(powod) == CATALOG["objchg.item.prog_error"]["pl"]
    assert detail.startswith(f"{type(wyjatek).__name__}: {wyjatek} @ ")
    plik, nr = _miejsce(detail)
    assert plik == "horreum/targets.py" and "json.loads" in _linia_pakietu(plik, nr)
    assert not _DYSK.search(detail) and "\\" not in detail.rsplit(" @ ", 1)[1]


def _rzut_z_pliku(nazwa):
    """Wyjątek rzucony z kodu skompilowanego pod nazwą pliku `nazwa` (ramka śladu z tą nazwą)."""
    przestrzen = {}
    exec(compile("def f():\n    raise KeyError('x')\n", nazwa, "exec"), przestrzen)
    try:
        przestrzen["f"]()
    except KeyError as exc:
        return exc
    raise AssertionError(nazwa)


def test_blad_programu_miejsce_z_ramki_exe_i_spoza_pakietu():
    """AR-237: ramka w formie exe PyInstallera (`co_filename` względny od pakietu,
    `horreum\\gui\\…` - zmierzone w PYZ wydania) daje miejsce `horreum/gui/zamrozony.py:2`; ramka
    spoza katalogu pakietu (ten sam dysk, segment `horreum` w ścieżce), z innego dysku i forma
    względna, która wychodzi spod `horreum` (`..`, człon z dyskiem, oba ukośniki) - szczegół bez
    miejsca, nigdy ścieżka absolutna. Falsyfikatory: bez gałęzi ścieżki względnej (exe bez
    miejsca); dopasowanie po segmencie `horreum` zamiast po katalogu pakietu; forma względna
    sprawdzana tylko pierwszym członem (`horreum/../obcy.py` przechodzi)."""
    import horreum
    detail = dict(powod_okna(_rzut_z_pliku("horreum\\gui\\zamrozony.py")).params)["detail"]
    assert _miejsce(detail) == ("horreum/gui/zamrozony.py", 2), detail
    obok = str(pathlib.Path(horreum.__file__).resolve().parent.parent / "obcy" / "horreum" / "x.py")
    for nazwa in (obok, r"X:\inne\horreum\gui\obcy.py", "horreum/../obcy.py", "horreum\\..\\obcy.py",
                  "horreum/C:/Users/x.py", "horreum\\C:\\Users\\x.py", "horreum/./gui/x.py", "horreum"):
        detail = dict(powod_okna(_rzut_z_pliku(nazwa)).params)["detail"]
        assert detail == "KeyError: 'x'", (nazwa, detail)


# Moduł pakietu w formie exe (nazwa pliku względna od `horreum`) z łańcuchami wyjątków; numery linii
# to część testu: 2 = źródło (`wewn`), 7/12/17 = przepakowanie w handlerze, 19 = przepakowanie cudzej
# przyczyny.
_LANCUCH = ("def wewn():\n"
            "    raise KeyError('x')\n"
            "def jawny():\n"
            "    try:\n"
            "        wewn()\n"
            "    except KeyError as e:\n"
            "        raise ValueError('y') from e\n"
            "def niejawny():\n"
            "    try:\n"
            "        wewn()\n"
            "    except KeyError:\n"
            "        raise ValueError('y')\n"
            "def wyciszony():\n"
            "    try:\n"
            "        wewn()\n"
            "    except KeyError:\n"
            "        raise ValueError('y') from None\n"
            "def przepakuj(e):\n"
            "    raise ValueError('y') from e\n")


def _rzucony(f, *args):
    try:
        f(*args)
    except Exception as exc:                       # noqa: BLE001 - test zbiera dowolny wyjątek
        return exc
    raise AssertionError(f)


def test_blad_programu_miejsce_z_przyczyny_zrodlowej_lancucha():
    """AR-237, łańcuch wyjątków: miejsce w kodzie to źródło błędu, nie przepakowanie - jawny łańcuch
    (`raise … from e`) i niejawny (wyjątek w handlerze) wskazują linię `wewn`, wyjątek zewnętrzny
    UTWORZONY z przyczyną (bez własnego śladu) też; kontekst wyciszony (`from None`) - linia
    przepakowania; przyczyna bez ramki pakietu (rzucona poza nim) - linia ogniwa zewnętrznego; cykl
    w łańcuchu nie wiesza reguły. Falsyfikatory: sam ślad wyjątku zewnętrznego (7, 12, brak miejsca);
    kontekst wyciszony brany mimo `from None` (2 zamiast 17); bez powrotu do ogniwa zewnętrznego
    (brak miejsca zamiast 19)."""
    ns = {}
    exec(compile(_LANCUCH, "horreum\\gui\\lancuch.py", "exec"), ns)

    def _linia(exc):
        detail = dict(powod_okna(exc).params)["detail"]
        assert detail.startswith(f"{type(exc).__name__}: {exc}"), detail
        return _miejsce(detail)
    zrodlo = ("horreum/gui/lancuch.py", 2)
    assert _linia(_rzucony(ns["jawny"])) == zrodlo
    assert _linia(_rzucony(ns["niejawny"])) == zrodlo
    zewnetrzny = ValueError("y")
    zewnetrzny.__cause__ = _rzucony(ns["wewn"])
    assert zewnetrzny.__traceback__ is None and _linia(zewnetrzny) == zrodlo
    assert _linia(_rzucony(ns["wyciszony"])) == ("horreum/gui/lancuch.py", 17)
    obca = _rzucony(lambda: {}["z"])
    assert _linia(_rzucony(ns["przepakuj"], obca)) == ("horreum/gui/lancuch.py", 19)
    a, b = ValueError("a"), KeyError("b")
    a.__context__, b.__context__ = b, a
    assert _linia(a) is None


def test_blad_programu_z_watku_tla_niesie_miejsce_w_kodzie(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-237: rachunek planera w PRAWDZIWYM wątku tła pada błędem programu - szczegół pod
    nagłówkiem nocy niesie miejsce w kodzie pakietu (linia planera, która wołała rdzeń): powód liczy
    się w handlerze wątku, więc ślad jest pełny, a do okna jedzie gotowy tekst. Falsyfikator:
    `detail` bez miejsca."""
    from horreum import targets
    from horreum.gui.planner import PlannerView
    from test_gui_planner import _seed
    path = str(tmp_path / "planer_watek.db")
    con = _seed(path)

    def _rdzen_pada(*_a, **_k):
        raise KeyError("lights")
    monkeypatch.setattr(targets, "plan", _rdzen_pada)
    v = PlannerView(con, db_path=path)
    try:
        v.replan()
        assert v._thread is not None                                  # bieg w wątku tła
        _czekaj(lambda: v._thread is None and v.night_label.szczegol(), "błąd rachunku z wątku")
        glowa = i18n.t("objchg.st.detail_tip", detail="KeyError: 'lights'")
        assert v.night_label.szczegol().startswith(glowa + " @ ")
        plik, nr = _miejsce(v.night_label.szczegol())
        assert plik == "horreum/gui/planner.py" and "targets.plan(" in _linia_pakietu(plik, nr)
    finally:
        _czekaj(lambda: v._thread is None, "wątek planera")
        v.close()
        con.close()


# ============================================================ AR-236 - pasek po zamknięciu okna bez martwych przycisków


def _tylko_do_odczytu(pliki, tak):
    for p in pliki:
        os.chmod(p, stat.S_IREAD if tak else stat.S_IREAD | stat.S_IWRITE)


def test_naprawa_cofniecie_niedokonczone_pasek_po_zamknieciu_bez_przycisku_cofnij(repair, monkeypatch):
    """AR-236: „Napraw nagłówek…” - prawdziwy zapis kart, pliki tylko do odczytu, prawdziwy klik
    „Cofnij”: cofnięcie niedokończone, okno mówi „„Cofnij” ponowi…”. Po zamknięciu okna przycisku
    nie ma - zdanie paska to ten sam ogon z KRÓTKIM poleceniem CLI ponowienia tego commitu w miejscu
    etykiety przycisku, pełne polecenie ze ścieżką bazy w szczególe (AR-272). Falsyfikatory: pasek ze
    zdaniem pola okna (obietnica martwego „Cofnij”); wariant bez numeru commitu; ścieżka bazy
    w zdaniu."""
    v, con, files, _open = repair
    v.resize(1200, 800)
    v.show()
    zdania = _komunikaty(v)
    cofnij = "„" + i18n.t("grid.action.undo") + "”"

    def _zapis_i_cofniecie(dlg):
        QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        assert dlg._commit_id is not None
        _tylko_do_odczytu(files, True)
        try:
            QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        finally:
            _tylko_do_odczytu(files, False)
    okna = _naprawa_reka_testu(monkeypatch, _zapis_i_cofniecie)
    _select_review_tag(v, "nameless")
    QTest.mouseClick(v.repair_btn, Qt.LeftButton)
    dlg = okna[-1]
    assert cofnij in dlg.status.text() and not dlg.undo_btn.isHidden()      # okno: „Cofnij” zostaje
    polecenie = i18n.t("wb.undo_cli_short", id=dlg._commit_id)
    assert zdania[-1] == dlg.status.text().replace(cofnij, f"„{polecenie}”")
    assert cofnij not in zdania[-1] and f"--undo {dlg._commit_id}" in zdania[-1]
    assert queries.db_path_of(con) not in zdania[-1]                                   # AR-272
    assert szczegol_zdania(zdania[-1]).endswith(_szczegol_polecenia(con, dlg._commit_id))


@pytest.mark.parametrize("niedokonczone", [True, False])
def test_sciezka_cofniecie_kart_pasek_po_zamknieciu_bez_martwych_przyciskow(sciezka_karty, monkeypatch,
                                                                            niedokonczone):
    """AR-236: „Zatwierdź ze ścieżki…” - prawdziwe zatwierdzenie z kartą w pliku, potem „Cofnij karty”:
    plik tylko do odczytu - cofnięcie niedokończone, pasek po zamknięciu mówi polecenie CLI zamiast
    „Cofnij karty”; cofnięcie domknięte - okno mówi „„Zatwierdź” dopisze karty ponownie”, pasek sam
    stan, bez obietnicy przycisku. Falsyfikator: pasek ze zdaniem pola okna."""
    from horreum.gui import app as app_mod
    v, con, pliki, _fid = sciezka_karty
    okna = []

    def _exec(dlg):
        okna.append(dlg)
        dlg._runner.async_ok = False
        dlg.show()
        QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton)
        assert dlg._commit_id is not None
        _tylko_do_odczytu([pliki["zapis"]], niedokonczone)
        try:
            QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        finally:
            _tylko_do_odczytu([pliki["zapis"]], False)
        return QDialog.Accepted
    monkeypatch.setattr(app_mod.ConfirmPathObjectsDialog, "exec", _exec)
    v.resize(1200, 800)
    v.show()
    wiersz = next(r for r in range(v.review.count())
                  if v.review.item(r).data(app_mod._REVIEW_PAYLOAD) == app_mod.PATH_STACKS_PAYLOAD)
    v.review.setCurrentRow(wiersz)
    zdania = _komunikaty(v)
    QTest.mouseClick(v.confirm_path_btn, Qt.LeftButton)
    dlg = okna[-1]
    if niedokonczone:
        przycisk = "„" + i18n.t("path.undo_cards_btn") + "”"
        assert przycisk in dlg.status.text()
        polecenie = i18n.t("wb.undo_cli_short", id=dlg._commit_id)
        assert zdania[-1] == dlg.status.text().replace(przycisk, f"„{polecenie}”")
        assert queries.db_path_of(con) not in zdania[-1]                               # AR-272
        assert szczegol_zdania(zdania[-1]).endswith(_szczegol_polecenia(con, dlg._commit_id))
    else:
        nota_okna = i18n.t("path.cards_restored_note")
        assert dlg.status.text().endswith(nota_okna)
        assert zdania[-1] == dlg.status.text().replace(nota_okna, i18n.t("path.cards_restored_closed_note"))
        assert nota_okna not in zdania[-1]


# ============================================================ AR-283, AR-272 - pasek po oknach kart: commit i polecenie


def _czlon_cofniecia(commit_id):
    """Krótki człon cofnięcia w zdaniu paska po udanym zapisie kart (bez ścieżki bazy)."""
    return i18n.t("wb.undo_short", cmd=i18n.t("wb.undo_cli_short", id=commit_id))


def _szczegol_polecenia(con, commit_id):
    """Szczegół paska: pełne polecenie CLI cofnięcia commitu ze ścieżką bazy."""
    return i18n.t("wb.undo_cli_tip", id=commit_id,
                  cli=i18n.t("wb.undo_cli", db=queries.db_path_of(con), id=commit_id))


def test_udany_zapis_naprawy_zdanie_trwa_a_polecenie_kopiuje_sie_ze_szczegolu(qapp, tmp_path, monkeypatch,
                                                                              pola_inline):
    """AR-283, gospodarz: prawdziwy zapis kart w „Napraw nagłówek…” i zamknięcie okna - zdanie paska
    niesie numer commitu i krótkie polecenie cofnięcia, pełne polecenie ze ścieżką bazy stoi w szczególe,
    raport NIE gaśnie zegarem (do następnego raportu), a prawy klik → „Kopiuj szczegół” daje polecenie.
    Falsyfikatory: wariant paska bez szczegółu (zegar 5 s, jak przed AR-283); zdanie z pełną ścieżką."""
    path = tmp_path / "naprawa.db"
    con = db.open_db(str(path))
    for p in _nameless_tree(tmp_path):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW_PD,
                           summary=scan.ScanSummary())
    con.close()
    okna = _naprawa_reka_testu(monkeypatch, lambda dlg: QTest.mouseClick(dlg.save_btn, Qt.LeftButton))
    win = MainWindow(str(path))
    try:
        win.resize(1400, 900)
        win.show()
        win._show_view(NAV_PORZADKI)
        from horreum.gui import tasks as tasks_mod
        win.tasks_view.pages.setCurrentIndex(tasks_mod._PAGE_OBJECTS)
        os_ = win.object_view
        os_.refresh()
        QApplication.processEvents()
        _select_review_tag(os_, "nameless")
        QTest.mouseClick(os_.repair_btn, Qt.LeftButton)
        dlg = okna[-1]
        assert dlg._commit_id is not None
        assert win._pelny_komunikat == dlg.status.text() + _czlon_cofniecia(dlg._commit_id)
        assert queries.db_path_of(win.con) not in win._pelny_komunikat
        assert win.report_label.szczegol() == _szczegol_polecenia(win.con, dlg._commit_id)
        assert not win._zegar_raportu.isActive() and win._miejsce_komunikatu is None
        prawy_klik(win.report_label)
        pozycje = menu_pola_otwarte(win.report_label)
        pozycje[i18n.t("wb.copy_detail")].trigger()
        schowek = QGuiApplication.clipboard().text()
        assert schowek.endswith(i18n.t("wb.undo_cli", db=queries.db_path_of(win.con), id=dlg._commit_id))
        win.report_label._menu.hide()
    finally:
        win.close()


def _okno_sciezki_reka(monkeypatch, akcja):
    """`ConfirmPathObjectsDialog.exec` prowadzony ręką testu (zapis inline) - lista okien."""
    from horreum.gui import app as app_mod
    okna = []

    def _exec(dlg):
        okna.append(dlg)
        dlg._runner.async_ok = False
        dlg.show()
        akcja(dlg)
        return QDialog.Accepted
    monkeypatch.setattr(app_mod.ConfirmPathObjectsDialog, "exec", _exec)
    return okna


def _klik_okna_sciezki(v):
    from horreum.gui import app as app_mod
    wiersz = next(r for r in range(v.review.count())
                  if v.review.item(r).data(app_mod._REVIEW_PAYLOAD) == app_mod.PATH_STACKS_PAYLOAD)
    v.review.setCurrentRow(wiersz)
    QTest.mouseClick(v.confirm_path_btn, Qt.LeftButton)


def test_wynik_okna_sciezki_po_odswiezeniu_nie_ginie_pod_pusta_biblioteka(sciezka_karty, monkeypatch):
    """AR-283: biblioteka osi z aktywnym filtrem, który nie wpuszcza nazwanego obiektu - odświeżenie po
    zamknięciu okna mówi „brak obiektów”, a wynik zapisu kart z numerem commitu i poleceniem stoi PO nim
    (ostatnie słowo paska). Falsyfikator: zdanie wyniku przed odświeżeniem (kolejność sprzed AR-283)."""
    v, con, _pliki, _fid = sciezka_karty
    v.resize(1200, 800)
    v.show()
    v.combo_filter.addItem("OIII", "OIII")              # filtr bez klatek obiektu propozycji
    v.combo_filter.setCurrentIndex(v.combo_filter.count() - 1)
    okna = _okno_sciezki_reka(monkeypatch, lambda dlg: QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton))
    zdania = _komunikaty(v)
    _klik_okna_sciezki(v)
    dlg = okna[-1]
    assert dlg._commit_id is not None and v.objects.rowCount() == 0
    assert i18n.t("object.empty_status") in zdania
    assert zdania[-1] == dlg.status.text() + _czlon_cofniecia(dlg._commit_id)
    assert szczegol_zdania(zdania[-1]).endswith(_szczegol_polecenia(con, dlg._commit_id))


def test_bieg_okna_sciezki_bez_przypisan_mowi_na_pasku(sciezka_karty, monkeypatch):
    """AR-283: bieg w oknie „Zatwierdź ze ścieżki…”, który nie przypisał nic (klinga odmawia pierwszej
    pozycji - konflikt aliasu), po zamknięciu okna mówi na pasku zdanie wyniku i powód odmowy; dawniej
    pasek mówił tylko przy `assigned` > 0 i odmowa znikała z oknem. Okno bez biegu dalej milczy.
    Falsyfikator: warunek emisji samo `dlg.assigned`."""
    from horreum import repo
    v, _con, _pliki, _fid = sciezka_karty
    v.resize(1200, 800)
    v.show()

    def _konflikt(*_a, **_k):
        raise ValueError("alias „x” należy już do innego obiektu")
    monkeypatch.setattr(repo, "user_assign_object", _konflikt)
    okna = _okno_sciezki_reka(monkeypatch, lambda dlg: QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton))
    zdania = _komunikaty(v)
    _klik_okna_sciezki(v)
    dlg = okna[-1]
    assert dlg.assigned == 0 and dlg.error.text()
    assert zdania and zdania[-1] == dlg.status.text() + " - " + dlg.error.text()
    ile = len(zdania)
    _okno_sciezki_reka(monkeypatch, lambda dlg: None)
    _klik_okna_sciezki(v)
    assert len(zdania) == ile                                            # bez biegu - cisza


def test_bieg_okna_sciezki_bez_przypisan_nie_rusza_zaznaczenia_biblioteki(sciezka_karty, monkeypatch):
    """AR-283: biblioteka osi z obiektem, bez zaznaczonego wiersza; bieg w oknie „Zatwierdź ze
    ścieżki…” bez przypisań (odmowa klingi) odświeża bibliotekę przed zdaniem, ale zaznaczenia nie
    stawia - nic się w bibliotece nie zmieniło. Falsyfikator: odświeżenie z `select_first=True` także
    przy `assigned` = 0 (pierwszy wiersz zaznaczony za człowieka)."""
    from horreum import repo
    v, con, _pliki, fid = sciezka_karty
    repo.user_assign_object(con, alias_norm=None, canon="M42", catalog="M", kind="deep_sky",
                            frame_ids=[fid["raw"]], now=NOW, object_source="user")
    v.resize(1200, 800)
    v.show()
    v.refresh()
    v.objects.clearSelection()
    assert v.objects.rowCount() == 1 and not v.objects.selectionModel().selectedRows()

    def _konflikt(*_a, **_k):
        raise ValueError("alias „x” należy już do innego obiektu")
    monkeypatch.setattr(repo, "user_assign_object", _konflikt)
    okna = _okno_sciezki_reka(monkeypatch, lambda dlg: QTest.mouseClick(dlg.confirm_btn, Qt.LeftButton))
    zdania = _komunikaty(v)
    _klik_okna_sciezki(v)
    assert okna[-1].assigned == 0 and zdania
    assert not v.objects.selectionModel().selectedRows()
