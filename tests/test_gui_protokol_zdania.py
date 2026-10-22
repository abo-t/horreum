"""Jeden protokół „zdanie + szczegół” pól zdania okien zapisu (AR-204): `EtykietaBledu.ustaw`.

Do AR-204 były trzy drogi - pole błędu okien kart (`setText` + `setToolTip` z samym szczegółem),
notki żniw (`_ustaw_zdanie`) i szuflada Zbiorów (`_podpowiedz_wyniku` + dwie kopie inline) - bez
wskaźnika, że pod kursorem jest więcej, i bez drogi do skopiowania pliku, który padł. Pilnujemy:
`text()` = samo zdanie, podpowiedź = zdanie + szczegół, szczegół należy do zdania (następne go
zdejmuje), wskaźnik i menu „Kopiuj szczegół” wyłącznie przy szczególe, minimum szerokości pola 0,
szuflada wraca do zdania SPRZED gestu razem ze szczegółem, pasek awarii mówi zdaniem operacji,
strażnik `i18n` na powód z kodem w zdaniu UI. Ścieżki syntetyczne (`X:\\L\\…`), pliki w `tmp_path`."""
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # przed importem Qt (klasa AR-170)

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import horreum
from horreum import harvest, writeback
from horreum.gui import grid as grid_mod, i18n
from horreum.gui.i18n_catalog import CATALOG
from horreum.gui.wb_worker import EtykietaBledu, InplaceGestureResult, WritebackWorker, wiersz_systemu
from horreum.item_reasons import blad_systemu
from horreum.lead_copy import LeadCopyResult

from prawy_klik import menu_pola_otwarte, prawy_klik
from test_gui_lead_copy import _po_gescie, _pozycje_kopii, _prawy_klik, _wiersz, widok  # noqa: F401
from test_gui_powody_pisarza import _widok_nad

_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_SUROWY = r"PermissionError: [WinError 5] Odmowa dostępu.: 'X:\L\a.fits'"


def _odmowa_systemu():
    return blad_systemu(OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5))


def _tip():
    return i18n.t("wb.os_detail_tip", detail=_SUROWY)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def jezyk():
    yield i18n.set_lang
    i18n.set_lang("pl")


def _czekaj(warunek, opis, s=30):
    """Pętla zdarzeń do warunku (skład zbioru w tle) - `processEvents` + `sleep`, nie `qWait`."""
    koniec = time.monotonic() + s
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {s} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.005)


# ============================================================ API pola


def test_pole_zdania_tekst_podpowiedz_i_szczegol(qapp):
    """`ustaw(zdanie, szczegół)`: `text()` = samo zdanie, podpowiedź = zdanie + szczegół, `szczegol()`
    = szczegół; następne zdanie - `ustaw` bez szczegółu, `setText`, `clear` - go zdejmuje; szczegół
    bez zdania nie zostaje. Falsyfikator: `setText` bez zdjęcia szczegółu (poprzednia awaria pod
    zdaniem walidacji)."""
    pole = EtykietaBledu("")
    pole.ustaw("awaria", "Szczegół systemu: X")
    assert (pole.text(), pole.toolTip(), pole.szczegol()) == (
        "awaria", "awaria\nSzczegół systemu: X", "Szczegół systemu: X")
    for zmiana, zdanie in ((lambda: pole.ustaw("inne"), "inne"), (lambda: pole.setText("walidacja"),
                                                                   "walidacja"), (pole.clear, "")):
        pole.ustaw("awaria", "Szczegół systemu: X")
        zmiana()
        assert (pole.text(), pole.toolTip(), pole.szczegol()) == (zdanie, zdanie, "")
    pole.ustaw("", "Szczegół systemu: X")
    assert (pole.toolTip(), pole.szczegol()) == ("", "")


def test_pole_zdania_wskaznik_tylko_przy_szczegole(qapp):
    """Wskaźnik szczegółu: wcięcie zdania pod glif `wb.detail_marker` i opis dostępności = szczegół -
    wyłącznie przy szczególe; zdjęcie szczegółu oddaje wcięcie sprzed (`-1` - domyślne Qt). Pole
    maluje się w obu stanach. Falsyfikator: wskaźnik bez warunku na szczegół."""
    pole = EtykietaBledu("zdanie")
    pole.resize(300, 30)
    assert pole.indent() == -1 and pole.accessibleDescription() == ""
    pole.ustaw("zdanie", "Szczegół systemu: X")
    glif = pole.fontMetrics().horizontalAdvance(i18n.t("wb.detail_marker"))
    assert pole.indent() > glif and pole.accessibleDescription() == "Szczegół systemu: X"
    assert not pole.grab().isNull()
    pole.ustaw("zdanie", "Szczegół systemu: Y")                 # drugi szczegół - wcięcie bez zmian
    assert pole.indent() > glif
    pole.setText("bez szczegółu")
    assert pole.indent() == -1 and pole.accessibleDescription() == ""
    assert not pole.grab().isNull()


def test_pole_zdania_minimum_szerokosci_zero(qapp):
    """Zdanie z długą ścieżką bez spacji (plik zajęty 32/33, kod spoza klas) nie dyktuje minimum
    szerokości pola - zawijanie łamie tylko na spacjach (natywnie: okno „Napraw nagłówek…” 596 → 829
    px). Falsyfikator: bez nadpisanego `minimumSizeHint`."""
    pole = EtykietaBledu("")
    pole.setWordWrap(True)
    pole.ustaw("plik zajęty (X:\\" + "\\".join(["ASTRO_LIGHTS_NGC7635_Bubble"] * 8) + ".fits)")
    assert pole.minimumSizeHint().width() == 0


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_kopiuj_szczegol_z_menu_prawego_kliku(qapp, jezyk, lang):
    """PRAWDZIWY prawy klik (`prawy_klik`: mysz przez okno, AR-254) na polu ze szczegółem: menu „Kopiuj
    zdanie” / „Kopiuj szczegół” (+ „Kopiuj zaznaczenie” na polu z zaznaczonym tekstem - zaznaczenie
    zostaje); pozycja kopiuje do schowka (`trigger`, wzór `test_gui_lead_copy`). Bez szczegółu - menu
    własne nie powstaje. Pole stoi w oknie-rodzicu: pole najwyższego poziomu dostaje klik okna także
    wtedy, gdy droga myszy do niego nie prowadzi. Falsyfikatory: menu bez pozycji szczegółu; pole bez
    `contextMenuEvent`; pole przezroczyste dla myszy (syntetyczne zdarzenie menu go nie odróżnia)."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    jezyk(lang)
    okno = QWidget()
    pole = EtykietaBledu("")
    QVBoxLayout(okno).addWidget(pole)
    okno.resize(320, 60)
    okno.show()
    try:
        assert prawy_klik(pole) is None and pole._menu is None
        pole.ustaw("awaria", _tip())
        prawy_klik(pole)
        pozycje = menu_pola_otwarte(pole)
        assert list(pozycje) == [i18n.t("wb.copy_sentence"), i18n.t("wb.copy_detail")]
        pozycje[i18n.t("wb.copy_detail")].trigger()
        assert QGuiApplication.clipboard().text() == _tip()
        pozycje[i18n.t("wb.copy_sentence")].trigger()
        assert QGuiApplication.clipboard().text() == "awaria"
        pole._menu.hide()
        if lang == "en":
            assert not set("".join(pozycje)) & _POLSKIE
        pole.setTextInteractionFlags(Qt.TextSelectableByMouse)        # jak notki żniw
        pole.setSelection(0, 3)
        prawy_klik(pole)
        pozycje = menu_pola_otwarte(pole)
        assert list(pozycje) == [i18n.t("wb.copy_selection"), i18n.t("wb.copy_sentence"),
                                 i18n.t("wb.copy_detail")]
        assert pole.selectedText() == "awa"
        pozycje[i18n.t("wb.copy_selection")].trigger()
        assert QGuiApplication.clipboard().text() == "awa"
        pole._menu.hide()
    finally:
        okno.close()


# ============================================================ okna kart, szuflada, żniwa


def test_pole_bledu_okna_kart_nie_rozpycha_okna(qapp, tmp_path):
    """Okno „Napraw nagłówek…” po awarii całej operacji ze zdaniem z długą ścieżką (plik zajęty -
    `czytelny_powod` zostawia ścieżkę w nawiasie): minimum szerokości okna bez zmian. Falsyfikator:
    `EtykietaBledu` bez minimum 0 (natywnie +233 px przy foncie ×1,0, +435 px przy ×1,6)."""
    from horreum import db
    from horreum.gui.wb_worker import czytelny_powod
    from test_gui_object_change import _lighty, _okno_naprawy
    con = db.open_db(str(tmp_path / "z8.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=7)
    dlg = _okno_naprawy(con)
    dlg.show()
    QApplication.processEvents()
    przed = dlg.minimumSizeHint().width()
    sciezka = "X:\\" + "\\".join(["ASTRO_", "LIGHTS", "NGC7635_Bubble_Nebula_2023", "RC8_2600MC_OSC",
                                  "NGC7635_20230104_210700_LIGHT_OSC_300s_FLATGRP_NOFLAT_FWHM_.fits"])
    surowy = f"PermissionError: [WinError 32] Proces nie może uzyskać dostępu do pliku: '{sciezka}'"
    dlg._on_failed("commit", surowy, "")                     # tekst systemu spoza klas, jak z workera
    QApplication.processEvents()
    dlg.layout().activate()
    assert dlg.error.text() == i18n.t("grid.wb.error", msg=czytelny_powod(surowy))
    assert sciezka in dlg.error.text()
    assert dlg.minimumSizeHint().width() == przed
    dlg.reject()
    con.close()


def test_szuflada_wraca_do_zdania_i_szczegolu_sprzed_gestu(widok):
    """Szuflada niesie zdanie ze szczegółem (np. awaria zapisu przy żywym „Cofnij”), potem gest „Ta
    kopia prowadzi” prawdziwym menu i wątkiem tła, potem zmiana perspektywy: szuflada oddaje zdanie
    SPRZED gestu RAZEM ze szczegółem (wskaźnik, menu, podpowiedź). Falsyfikator: pamięć samego tekstu
    w `_odpal_gest_plikowy` (szczegół ginie, podpowiedź = samo zdanie)."""
    con, v, fid, a, b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    v.drawer.result.ustaw("Zatwierdzono 3", _tip())
    _prawy_klik(v, _wiersz(v, fid))
    _pozycje_kopii(v)[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    assert v.drawer.result.text() != "Zatwierdzono 3"              # wynik gestu w szufladzie
    v.apply_perspective(grid_mod._PRESET_CZYSTY)
    assert v.drawer.result.text() == "Zatwierdzono 3"
    assert v.drawer.result.szczegol() == _tip()
    assert v.drawer.result.toolTip() == "Zatwierdzono 3\n" + _tip()


def test_szuflada_wraca_do_zdania_sprzed_gestu_takze_po_awarii_gestu(widok, monkeypatch):
    """Szuflada niesie zdanie ze szczegółem, gest „Ta kopia prowadzi” pada wyjątkiem CAŁEJ operacji
    (wątek tła, `OSError` 5): szuflada mówi błąd gestu ze szczegółem, a zmiana perspektywy oddaje
    zdanie i szczegół SPRZED gestu - błąd jest wynikiem gestu jak sukces. Falsyfikator: znacznik
    wyniku gestu tylko na drodze sukcesu (`_on_wb_failed` bez `_oznacz_wynik_gestu_zapisu` -
    pamięć schodzi, a błąd zostaje)."""
    con, v, fid, a, b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    v.drawer.result.ustaw("Zatwierdzono 3", _tip())

    def _pada(*_a, **_k):
        raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)
    monkeypatch.setitem(WritebackWorker._OPS, "lead_copy", _pada)
    _prawy_klik(v, _wiersz(v, fid))
    _pozycje_kopii(v)[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    blad = i18n.t("grid.wb.op.lead_copy", msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
    assert v.drawer.result.text() == blad and v.drawer.result.szczegol() == _tip()
    v.apply_perspective(grid_mod._PRESET_CZYSTY)
    assert v.drawer.result.text() == "Zatwierdzono 3"
    assert v.drawer.result.szczegol() == _tip()


def test_szuflada_wraca_po_odmowie_gestu_ze_szczegolem(widok, monkeypatch):
    """Gest „Ta kopia prowadzi” kończy się odmową z błędem systemu klasą (zerwany udział przy odczycie
    kopii): wynik gestu to PARA zdanie + szczegół, więc znacznik musi ją złapać w całości - zmiana
    perspektywy oddaje zdanie sprzed gestu. Falsyfikator: znacznik postawiony przed doklejeniem
    szczegółu (para w szufladzie inna niż znacznik - zdanie sprzed gestu nie wraca)."""
    from horreum import scan
    con, v, fid, a, b = widok
    v.apply_perspective(grid_mod.PRESET_COPY_CONFLICT)
    v.drawer.result.ustaw("Zatwierdzono 3", _tip())

    def zerwany(path, **_k):
        raise OSError(None, "Nazwa sieciowa jest już niedostępna", str(path), 64)
    monkeypatch.setattr(scan, "scan_file", zerwany)
    _prawy_klik(v, _wiersz(v, fid))
    _pozycje_kopii(v)[1].trigger()
    v._menu_tabeli.hide()
    assert _po_gescie(v)
    assert i18n.t("objchg.item.os_share_lost", os_code="WinError 64") in v.drawer.result.text()
    assert v.drawer.result.szczegol()
    v.apply_perspective(grid_mod._PRESET_CZYSTY)
    assert (v.drawer.result.text(), v.drawer.result.szczegol()) == ("Zatwierdzono 3", _tip())


def _ops_widoku():
    """Operacje uchwytu startowane z widoku Zbiorów - predykat: literał pierwszego argumentu
    `_start_writeback` / `_odpal_gest_plikowy` / `_start_gestu_zapisu` w `grid.py`. Tylko te
    dochodzą do `FramesView._on_wb_failed` (okna kart i zmiany obiektu mają własne odbiorniki)."""
    drzewo = ast.parse(Path(grid_mod.__file__).read_text(encoding="utf-8"))
    return {w.args[0].value for w in ast.walk(drzewo)
            if isinstance(w, ast.Call) and isinstance(w.func, ast.Attribute)
            and w.func.attr in ("_start_writeback", "_odpal_gest_plikowy", "_start_gestu_zapisu")
            and w.args and isinstance(w.args[0], ast.Constant) and isinstance(w.args[0].value, str)}


def test_kazda_operacja_widoku_ma_zdanie_porazki_i_zadnej_martwej():
    """Komplet `grid.wb.op.<op>` (PL, EN) dla operacji widoku - i NIC ponad nie (bez martwych par).
    Falsyfikator: nowa operacja w widoku bez zdania (pasek pokazałby klucz) albo klucz bez operacji."""
    ops = _ops_widoku()
    assert ops == {"commit", "undo", "commit_rename", "undo_rename", "lead_copy", "finish_inplace",
                   "recover_torn", "release_inplace"}, ops
    assert ops <= set(WritebackWorker._OPS)
    klucze = {k.removeprefix("grid.wb.op.") for k in CATALOG if k.startswith("grid.wb.op.")}
    assert klucze == ops
    for op in ops:
        wpis = CATALOG[f"grid.wb.op.{op}"]
        assert "{msg}" in wpis["pl"] and "{msg}" in wpis["en"], op
        assert not set(wpis["en"]) & _POLSKIE, wpis["en"]
    assert "grid.wb.failed" not in CATALOG


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_operacji_na_pasku_mowi_zdaniem_operacji(qapp, tmp_path, jezyk, lang, monkeypatch):
    """Awaria całej operacji uchwytu (klik „Zatwierdź” szuflady, `OSError` 5): pasek po przyłożeniu
    zbioru mówi zdaniem operacji z katalogu - bez tokenu `commit` i bez „Writeback”. Każda operacja
    widoku tym samym slotem. Falsyfikator: stary klucz `grid.wb.failed` z `op=op`."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    view.show()
    zdania = []
    view.status_message.connect(zdania.append)
    bar = view.macro_bar
    bar.asg_kw.setCurrentText("TELESCOP")
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText("EQ6")
    bar._emit_stage()

    def _odmowa(*_a, **_k):
        raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _odmowa)
    QTest.mouseClick(view.drawer.btn_commit, Qt.LeftButton)
    klasa = i18n.t("objchg.item.os_denied", os_code="WinError 5")
    oczek = i18n.t("grid.wb.op.commit", msg=klasa)
    _czekaj(lambda: oczek in zdania, f"zdanie awarii na pasku: {zdania[-3:]}")
    assert view.drawer.result.szczegol() == _tip()
    for op in sorted(_ops_widoku() - {"commit"}):
        view._on_wb_failed(op, klasa, "")
        oczek = i18n.t(f"grid.wb.op.{op}", msg=klasa)
        _czekaj(lambda oczek=oczek: oczek in zdania, f"zdanie awarii {op}")
    for z in zdania:
        assert "Writeback" not in z and "lead_copy" not in z and "release_inplace" not in z, z
        if lang == "en":
            assert not set(z) & _POLSKIE, z
    view.close()
    con.close()


def test_cofniecie_w_szufladzie_szczegol_przez_protokol(qapp, tmp_path):
    """Cofnięcie (makro i nazwy) z błędem systemu klasą: szczegół systemu przez protokół pola - stoi
    w `szczegol()` (wskaźnik, menu), nie tylko w surowej podpowiedzi. Falsyfikator: kopia inline
    `setToolTip(text + szczegół)` w `_after_undo` / `_after_undo_rename`."""
    view, con, p = _widok_nad(qapp, tmp_path)
    fr = writeback.FileResult(1, r"X:\L\a.fits", "failed", _odmowa_systemu())
    for slot in (view._after_undo, view._after_undo_rename):
        slot("undo", writeback.UndoResult(1, [], [], [fr]))
        assert view.drawer.result.szczegol() == _tip(), slot.__name__
        assert view.drawer.result.toolTip() == view.drawer.result.text() + "\n" + _tip()
    view.close()
    con.close()


def test_gest_izolacji_niesie_szczegol_systemu(qapp, tmp_path):
    """Gest izolacji („Dokończ zapis”) z błędem systemu klasą: zdanie szuflady mówi klasą w języku
    UI, a surowy tekst systemu stoi w szczególe (dawniej ginął - zdanie gestu nie miało podpowiedzi).
    Czyste funkcje i ogon w widoku. Falsyfikator: `_after_gestu_zapisu` bez szczegółu."""
    from horreum.gui.grid_model import _podpowiedz_gestu_zapisu, _zdanie_gestu_zapisu
    blad = writeback.FileResult(7, r"X:\L\a.fits", "failed", _odmowa_systemu())
    ok = writeback.FileResult(8, r"X:\L\b.fits", "applied")
    res = InplaceGestureResult([ok, blad])
    assert i18n.t("objchg.item.os_denied", os_code="WinError 5") in _zdanie_gestu_zapisu(
        "finish_inplace", res)
    assert _podpowiedz_gestu_zapisu("finish_inplace", res) == _tip()
    assert _podpowiedz_gestu_zapisu("finish_inplace", InplaceGestureResult([ok])) == ""
    view, con, _p = _widok_nad(qapp, tmp_path)
    view._cel_gestu_zapisu, view._wynik_gestu_zapisu = [], None
    view._after_gestu_zapisu("finish_inplace", res)
    assert view.drawer.result.text() == _zdanie_gestu_zapisu("finish_inplace", res)
    assert view.drawer.result.szczegol() == _tip()
    view.close()
    con.close()


def test_notki_zniw_jednym_protokolem(qapp, tmp_path, ustawienia, monkeypatch):
    """Notki okna żniw to pola protokołu: awaria całej operacji - zdanie klasy, szczegół systemu
    (wskaźnik, menu), następna notka go zdejmuje; ostrzeżenie archiwum i notka listy wydań tą samą
    klasą. Falsyfikator: notka przez zwykły `QLabel` (`szczegol()` nie istnieje, menu domyślne)."""
    from test_gui_harvest import _baza, _czytnik, _dlg, _flat_cls, _wyjscie
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    assert all(isinstance(p, EtykietaBledu) for p in (dlg.notice, dlg.rel_notice, dlg.archive_warn))
    dlg._set_output(str(out))

    def _odmowa(*_a, **_k):
        raise OSError(None, "Odmowa dostępu.", r"X:\L\a.fits", 5)
    monkeypatch.setattr(harvest, "apply", _odmowa)
    dlg._on_apply()
    assert dlg.notice.szczegol() == _tip()
    assert dlg.notice.toolTip() == dlg.notice.text() + "\n" + _tip()
    dlg._show_notice("następna notka")
    assert dlg.notice.szczegol() == "" and dlg.notice.toolTip() == "następna notka"
    dlg.reject()
    con.close()


def test_szczegol_bledu_bazy_klasa_w_podpowiedzi(tmp_path):
    """Błąd bazy klasą (`item_reasons.powod_bazy`, AR-198) niesie surowy tekst SQLite w szczególe pola
    tak jak błąd systemu - jeden zbiór kodów z `detail` (`SYSTEM_REASON_CODES`). Prawdziwa blokada:
    druga transakcja na pliku bazy bez czekania. Falsyfikator: `_surowy_systemu` po samych kodach
    systemu (`OS_REASON_CODES`) - szczegół bazy pusty."""
    import sqlite3
    sciezka = str(tmp_path / "zajeta.db")
    pierwsza = sqlite3.connect(sciezka, isolation_level=None)
    pierwsza.execute("CREATE TABLE t (x)")
    pierwsza.execute("BEGIN EXCLUSIVE")
    druga = sqlite3.connect(sciezka, timeout=0)
    try:
        with pytest.raises(sqlite3.OperationalError) as zajeta:
            druga.execute("SELECT * FROM t")
    finally:
        druga.close()
        pierwsza.execute("ROLLBACK")
        pierwsza.close()
    powod = blad_systemu(zajeta.value)
    assert getattr(powod, "code", None) == "db_busy", powod
    assert wiersz_systemu(powod) == i18n.t("wb.os_detail_tip", detail=f"OperationalError: {zajeta.value}")


# ============================================================ strażnik `i18n`


def test_straznik_powodu_w_zdaniu_UI():
    """Bateria (tryb dev, `conftest`): powód z kodem wstawiony surowo w zdanie UI to `TypeError`
    z kluczem i parametrem - w `t` i w `t_plural`; zdanie przez `tekst_powodu` przechodzi.
    Falsyfikator: strażnik zdjęty z `t`/`t_plural`."""
    from horreum.gui.wb_worker import tekst_powodu
    powod = _odmowa_systemu()
    with pytest.raises(TypeError, match="grid.wb.error"):
        i18n.t("grid.wb.error", msg=powod)
    with pytest.raises(TypeError, match="detail"):
        i18n.t_plural("grid.frames", 2, detail=powod)
    assert i18n.t("grid.wb.error", msg=tekst_powodu(powod))


def test_straznik_powodu_w_produkcie_wylaczony():
    """Produkt (import `i18n` bez `conftest`): strażnik wyłączony - powód z kodem w zdaniu mówi
    zdaniem PL, nie wyjątkiem w slocie okna. Falsyfikator: `_STRAZNIK_POWODU = True` w module."""
    kod = ("from horreum.gui import i18n\n"
           "from horreum.item_reasons import blad_systemu\n"
           "p = blad_systemu(OSError(None, 'x', 'X:/a', 5))\n"
           "print(i18n._STRAZNIK_POWODU, bool(i18n.t('grid.wb.error', msg=p)))\n")
    wynik = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True,
                           cwd=str(Path(horreum.__file__).parent.parent), timeout=120)
    assert wynik.returncode == 0, wynik.stderr
    assert wynik.stdout.split() == ["False", "True"], wynik.stdout


def test_kopia_wiodaca_para_zdania_i_szczegolu_pasuje_do_protokolu():
    """Gest „Ta kopia prowadzi” daje parę (zdanie, szczegół) dla adaptera szuflady
    (`_podpowiedz_wyniku`): zdanie jednowierszowe (szuflada elidowana), szczegół = wiersz systemu.
    Falsyfikator: szczegół doklejony do zdania."""
    from horreum.gui.grid_model import _zdanie_kopii_wiodacej
    zdanie, podpowiedz = _zdanie_kopii_wiodacej(
        LeadCopyResult("failed", 1, r"X:\L\a.fits", reason=_odmowa_systemu()))
    assert podpowiedz == wiersz_systemu(_odmowa_systemu()) == _tip()
    assert zdanie and "\n" not in zdanie and _tip() not in zdanie


# ============================================================ AR-254 - pomocnik prawdziwego kliku na starszym Qt


@pytest.mark.parametrize("wersja, wynik", [("6.7.3", pytest.skip.Exception), ("6.9.2", AssertionError)])
def test_prawy_klik_bez_przypiecia_wyzwalacza_pomija_test(qapp, monkeypatch, wersja, wynik):
    """AR-254: PySide6 bez `QStyleHints.setContextMenuTrigger` (Qt < 6.8 - pakiet deklaruje `>=6.5`)
    nie przypnie wyzwalacza menu, więc gest mierzyłby artefakt platformy - pomocnik POMIJA test z powodem
    i nie wykonuje gestu (atrapa `styleHints` bez atrybutu). Rozstrzyga WERSJA Qt: na Qt >= 6.8 brak API
    to błąd testu, nie pominięcie. Falsyfikatory: asercja dostępności API zamiast pominięcia (błąd testu
    na wspieranej konfiguracji); pominięcie po samym braku atrybutu (zmiana nazwy API = cichy SKIP)."""
    from types import SimpleNamespace

    import prawy_klik as pk
    gesty = []
    monkeypatch.setattr(pk, "qVersion", lambda: wersja)
    monkeypatch.setattr(pk, "QGuiApplication", SimpleNamespace(styleHints=lambda: SimpleNamespace()))
    monkeypatch.setattr(pk, "QTest", SimpleNamespace(mouseClick=lambda *a, **k: gesty.append(a)))
    with pytest.raises(BaseException, match="setContextMenuTrigger") as e:     # skip to BaseException
        pk.prawy_klik(EtykietaBledu("zdanie"))
    assert e.type is wynik and gesty == [], (e.type, gesty)
