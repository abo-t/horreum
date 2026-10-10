"""Droga Przyjmij (`horreum.gui.flows.przyjmij.PrzyjmijView` + gospodarz `MainWindow`): kafel Domu
uruchamia dostawę, a nad TYM SAMYM widokiem Dostawy staje raport „Co przyszło” z gestem
„Przypisz obiekt…” przy nierozpoznanej nazwie.

Raport jest liczony po PRAWDZIWYM przebiegu „all” w `QThread` z pętlą zdarzeń na drzewie FITS
w `tmp_path` (astropy) - czekamy na sygnał końca przebiegu, nie na jeden obrót pętli. Zegar okna
przesuwa się o sekundę na wywołanie: stały zegar zrównałby `since` drugiej dostawy
z `first_seen_at` pierwszej, a raport liczy się właśnie z tych dwóch znaczników.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija. `QT_QPA_PLATFORM=offscreen` PRZED
importem Qt."""
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from astropy.io import fits

from horreum import audit, db, repo
from horreum.gui import i18n, queries
from horreum.gui.app import NAV_DOM, NAV_DOSTAWA, STRONA_DOSTAWA, STRONA_PORZADKI, MainWindow
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.flows import przyjmij as przyjmij_mod
from horreum.gui.flows.przyjmij import PrzyjmijView, godzina_dostawy
from horreum.gui.pipeline import PipelineView, PipelineWorker

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog

PLAMA = "Plama Zdzicha"            # nazwa spoza katalogu - żaden szczebel drabiny jej nie zna


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _pola_inline(monkeypatch):
    """Pokrycie pól i skład zbioru Zbiorów INLINE (seam okna) - wynik z wątku tła doręczony
    w nieznanej chwili dokładałby przeładowanie w środku asercji o raporcie."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


class _Zegar:
    """Zegar okna w teście: każde wywołanie o sekundę później, ISO UTC ze strefą (jak
    `pipeline._utc_now_iso`). Woła go też wątek tła, stąd zamek."""

    def __init__(self):
        self._t = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self._t += timedelta(seconds=1)
            return self._t.isoformat()


def _fits(path, n, obj=None):
    """Light FITS o unikalnej treści (`data=n` → unikalny `sha1_data`), z kartą `OBJECT`, gdy
    podana - bez niej klatka trafia do kubełka „bez nazwy w nagłówku”."""
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["XPIXSZ"] = 3.76
    hdu.header["IMAGETYP"] = "LIGHT"
    hdu.header["DATE-OBS"] = "2024-03-01T22:00:00"
    hdu.header["EXPTIME"] = 300.0
    if obj is not None:
        hdu.header["OBJECT"] = obj
    fits.HDUList([hdu]).writeto(str(path))


def _drzewo(tmp_path, nazwa, klatki):
    """Katalog dostawy: `klatki` = [(n, OBJECT albo None), …]."""
    d = tmp_path / nazwa
    d.mkdir()
    for n, obj in klatki:
        _fits(d / f"l{n}.fits", n, obj)
    return str(d)


def _baza(tmp_path):
    path = str(tmp_path / "przyjmij.db")
    db.open_db(path).close()                  # utwórz + zmigruj; worker otworzy własne połączenie
    return path


@pytest.fixture
def strona(qapp, tmp_path):
    """Strona Dostawy bez okna: `PrzyjmijView` nad `PipelineView` na świeżej bazie."""
    db_path = _baza(tmp_path)
    con = db.open_db(db_path)
    zegar = _Zegar()
    widok = PrzyjmijView(con, PipelineView(db_path, now_fn=zegar), now_fn=zegar)
    widok.komunikaty = []
    widok.status_message.connect(widok.komunikaty.append)
    yield widok
    con.close()


def _przebieg(pipeline, start, limit_ms=30000):
    """Uruchom przebieg i czekaj na `run_finished` (słuchacz raportu podpięty wcześniej, więc po
    powrocie raport już stoi). Zwraca zapis przebiegu."""
    zapisy = []
    loop = QEventLoop()

    def koniec(zapis):
        zapisy.append(zapis)
        loop.quit()

    pipeline.run_finished.connect(koniec)
    QTimer.singleShot(limit_ms, loop.quit)
    try:
        assert start() is None
        loop.exec()
    finally:
        pipeline.run_finished.disconnect(koniec)
    assert zapisy, "przebieg nie skończył się w limicie"
    return zapisy[0]


def _wiersze(widok):
    return [w for w in widok._wiersze_nazw if not w.isHidden()]


def _prowadz_dialog(akcja, limit_ms=10000):
    """Poprowadź modalne okno przypisania z jego WŁASNEJ pętli zdarzeń (`exec`). Zwraca słownik,
    w którym `widziane` mówi, czy okno w ogóle się pokazało."""
    stan = {"widziane": False}
    koniec = datetime.now() + timedelta(milliseconds=limit_ms)

    def krok():
        dlg = QApplication.activeModalWidget()
        if isinstance(dlg, AssignObjectDialog):
            stan["widziane"] = True
            akcja(dlg)
        elif datetime.now() < koniec:
            QTimer.singleShot(20, krok)

    QTimer.singleShot(0, krok)
    return stan


class _OknoPrzypisania:
    """Okno przypisania zatwierdzone na NGC7000 z aliasem nazwy - bez modalnej pętli."""
    utworzone = []

    def __init__(self, con, *, object_raw, frame_count, parent=None):
        _OknoPrzypisania.utworzone.append((object_raw, frame_count))
        self.selected = ("NGC7000", "NGC", "deep_sky", "PLAMAZDZICHA")

    def exec(self):
        return QDialog.Accepted


# ---------------------------------------------------------------- raport po prawdziwym przebiegu

def test_panel_ukryty_do_pierwszego_przebiegu_potem_raport(strona, tmp_path):
    """Przed pierwszą dostawą w sesji panelu nie ma (pusty raport udawałby dostawę bez klatek).
    Po przebiegu „all”: nagłówek z godziną startu i rozbiciem po rodzajach, obiekty z godzinami,
    kalibracja nowych lightów, „Nie rozpoznałem” z wierszem nazwy (obie liczby) i kubełkiem bez
    nazwy."""
    i18n.set_lang("pl")
    assert strona.panel.isHidden()
    tree = _drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA), (3, "IC 1795"), (4, None)])
    zapis = _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(tree))
    assert zapis["stage"] == "all" and not zapis["refused"]
    assert not strona.panel.isHidden()
    assert strona.lbl_head.text() == (
        f"Dostawa z {godzina_dostawy(zapis['since'])}: 4 nowe klatki (lighty 4)")
    assert strona.lbl_objects.text() == "Obiekty: IC1795 ×1 (0.1 h)"
    assert strona.lbl_cal.text() == "Kalibracja nowych lightów: bez flatu 4 · bez darka 4"
    assert strona.lbl_unresolved.text() == "Nie rozpoznałem: 3 klatki"
    wiersze = _wiersze(strona)
    assert [w.lbl.text() for w in wiersze] == ["„Plama Zdzicha” ×2 w tej dostawie"]
    assert wiersze[0].btn.isEnabled() and wiersze[0].btn.text() == "Przypisz obiekt…"
    assert not strona.row_nameless.isHidden()
    assert strona.row_nameless.lbl.text() == "bez nazwy w nagłówku 1"
    assert strona.row_nameless_raw.isHidden() and strona.row_nameless_stacks.isHidden()
    assert strona.lbl_warn.isHidden() and strona.lbl_error.isHidden()


def test_gest_przypisz_obiekt_z_raportu_zapamietuje_nazwe(strona, tmp_path):
    """„Przypisz obiekt…” przy wierszu nazwy → PRAWDZIWE okno przypisania (nazwa wpisana, Enter
    walidacji) → alias `source='user'` w bazie, zdanie „Zapamiętałem…”, wiersz znika, obiekt
    rośnie w „Obiekty”, `object_axis_changed` pada raz. Wiersz nazywał obie liczby, więc okno
    dostaje całą populację gestu."""
    i18n.set_lang("pl")
    tree = _drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA)])
    _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(tree))
    osie = []
    strona.object_axis_changed.connect(lambda: osie.append(1))

    def zatwierdz(dlg):
        assert dlg.accept_btn.text() == "Przypisz 2 klatki"
        dlg.designation.setText("NGC 7000")
        dlg._validate_and_accept()

    stan = _prowadz_dialog(zatwierdz)
    _wiersze(strona)[0].btn.click()
    assert stan["widziane"], "okno przypisania się nie pokazało"
    alias = strona.con.execute(
        "SELECT o.canon, a.source FROM object_alias a JOIN object o ON o.id = a.object_id "
        "WHERE a.alias_norm = 'PLAMAZDZICHA'").fetchone()
    assert tuple(alias) == ("NGC7000", "user")
    assert strona.komunikaty[-1] == (
        "Zapamiętałem: „Plama Zdzicha” = NGC7000 - następne dostawy rozpoznają same")
    assert osie == [1]
    assert _wiersze(strona) == []
    assert strona.lbl_unresolved.text() == "Wszystko rozpoznane"
    assert strona.lbl_objects.text() == "Obiekty: NGC7000 ×2 (0.2 h)"


def test_nazwa_bez_znakow_alfanumerycznych_ostrzega_bez_okna(strona, tmp_path, monkeypatch):
    """Nazwa „---” dałaby pusty klucz aliasu (łapałby każdą taką nazwę), a okno przypisania
    asertuje ten kontrakt - bramka stoi PRZED oknem, jak w osi obiektu: ostrzeżenie, zero okna,
    zero zapisu."""
    i18n.set_lang("pl")
    tree = _drzewo(tmp_path, "d1", [(1, "---")])
    _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(tree))
    ostrzezenia = []
    monkeypatch.setattr(przyjmij_mod.QMessageBox, "warning",
                        staticmethod(lambda _p, tytul, tekst: ostrzezenia.append((tytul, tekst))))
    _OknoPrzypisania.utworzone = []
    monkeypatch.setattr(przyjmij_mod, "AssignObjectDialog", _OknoPrzypisania)
    zdarzenia = strona.con.execute("SELECT count(*) FROM event").fetchone()[0]
    [wiersz] = _wiersze(strona)
    assert wiersz.lbl.text() == "„---” ×1 w tej dostawie"
    wiersz.btn.click()
    assert ostrzezenia == [(i18n.t("assign.title"), i18n.t("object.alias_no_alnum", name="---"))]
    assert _OknoPrzypisania.utworzone == []
    assert strona.con.execute("SELECT count(*) FROM event").fetchone()[0] == zdarzenia


def test_druga_dostawa_rozpoznana_aliasem_reka_nie_ubywa(strona, tmp_path, monkeypatch):
    """Gest na miejscu uczy nazwy na przyszłość: druga dostawa z tą samą nazwą rozpoznaje się
    szczeblem aliasu (`object_source='alias'`) i raport nie ma wiersza „nie rozpoznałem”. Spis
    faktów ręki (`human-facts`): `object_hand` rośnie po geście i nie spada po drugim przebiegu."""
    i18n.set_lang("pl")
    _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(
        _drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA)])))
    przed = audit.human_facts_census(strona.con)
    _OknoPrzypisania.utworzone = []
    monkeypatch.setattr(przyjmij_mod, "AssignObjectDialog", _OknoPrzypisania)
    _wiersze(strona)[0].btn.click()
    assert _OknoPrzypisania.utworzone == [(PLAMA, 2)]
    po_gescie = audit.human_facts_census(strona.con)
    assert po_gescie.object_hand == przed.object_hand + 2

    _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(
        _drzewo(tmp_path, "d2", [(3, PLAMA)])))
    plamy = strona.con.execute(
        "SELECT f.object_source, o.canon FROM frame f JOIN header h ON h.frame_id = f.id "
        "JOIN object o ON o.id = f.object_id WHERE h.object_raw = ? ORDER BY f.id",
        (PLAMA,)).fetchall()
    assert [tuple(r) for r in plamy] == [("user", "NGC7000"), ("user", "NGC7000"),
                                         ("alias", "NGC7000")]
    assert _wiersze(strona) == [] and strona.lbl_unresolved.text() == "Wszystko rozpoznane"
    assert strona.lbl_objects.text() == "Obiekty: NGC7000 ×1 (0.1 h)"     # TA dostawa
    po_drugiej = audit.human_facts_census(strona.con)
    assert po_drugiej.spadki(po_gescie) == {}
    assert po_drugiej.object_hand >= po_gescie.object_hand


def test_kopie_znanych_klatek_z_licznika_skanu_nie_z_roznicy(strona, tmp_path):
    """Druga dostawa: dwie kopie znanych klatek pod nowymi ścieżkami i podmiana treści pod znaną
    ścieżką (nowa klatka bez nowej lokacji). „Kopie znanych klatek” mówi licznik skanu „nowa
    ścieżka znanej tożsamości” - 2. Falsyfikator: `locations_new - frames_new` → „… 1”."""
    i18n.set_lang("pl")
    pv = strona.pipeline_view
    tree = _drzewo(tmp_path, "d1", [(1, "IC 1795"), (2, "IC 1795"), (3, "IC 1795")])
    _przebieg(pv, lambda: pv.run_all_on(tree))
    d = tmp_path / "d1"
    (d / "kopie").mkdir()
    for nazwa in ("l1.fits", "l2.fits"):
        shutil.copy(str(d / nazwa), str(d / "kopie" / nazwa))
    podmiana = d / "l3.fits"
    mtime = podmiana.stat().st_mtime
    podmiana.unlink()
    _fits(podmiana, 4, "IC 1795")                    # inna treść pod tą samą nazwą
    os.utime(podmiana, (mtime + 100, mtime + 100))
    zapis = _przebieg(pv, lambda: pv.run_all_on(tree))
    assert zapis["results"]["scan"].locations_rebound == 1
    assert strona.lbl_head.text() == (
        f"Dostawa z {godzina_dostawy(zapis['since'])}: 1 nowa klatka (lighty 1)"
        " · kopie znanych klatek 2 · bez zmian 2")


def test_odpiete_reka_to_nie_wszystko_rozpoznane(strona, tmp_path, monkeypatch):
    """Klatki tej dostawy, którym ręka zdjęła obiekt („Cofnij przypisanie”, nagrobek), nie są
    robotą do naprawy, ale nie są też rozpoznane: zamiast „Wszystko rozpoznane” stoi osobne zdanie
    z liczbą, bez gestu. Falsyfikator: wyłącz nagrobek z raportu po cichu → „Wszystko
    rozpoznane”."""
    i18n.set_lang("pl")
    pv = strona.pipeline_view
    _przebieg(pv, lambda: pv.run_all_on(_drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA)])))
    monkeypatch.setattr(przyjmij_mod, "AssignObjectDialog", _OknoPrzypisania)
    _wiersze(strona)[0].btn.click()
    assert strona.lbl_unresolved.text() == "Wszystko rozpoznane" and strona.lbl_cleared.isHidden()
    ids = [fid for (fid,) in strona.con.execute(
        "SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id WHERE h.object_raw = ?",
        (PLAMA,))]
    repo.clear_object_assignment(strona.con, frame_ids=ids, now="2026-10-10T13:00:00+00:00")
    strona.odswiez_raport()
    assert strona.lbl_unresolved.isHidden()
    assert not strona.lbl_cleared.isHidden()
    assert strona.lbl_cleared.text() == "Bez obiektu z decyzji ręki: 2 klatki"
    assert _wiersze(strona) == []


# ---------------------------------------------------------------- przebiegi bez pełnej dostawy

def test_przebieg_anulowany_mowi_przerwana_i_to_co_weszlo(strona, tmp_path, monkeypatch):
    """Anulowanie po pierwszym pliku: zdanie „przerwana w etapie …” PRZED liczbami i raport z tego,
    co zdążyło wejść - zero klatek po przerwaniu nie udaje pustej dostawy, a jedna nie udaje
    pełnej."""
    i18n.set_lang("pl")
    prawdziwy = PipelineWorker._on_progress

    def po_pierwszym(self, done, total, path, summary):
        self.request_cancel()                          # wątek tła: anuluj na granicy pliku
        prawdziwy(self, done, total, path, summary)

    monkeypatch.setattr(PipelineWorker, "_on_progress", po_pierwszym)
    tree = _drzewo(tmp_path, "d1", [(1, "M 42"), (2, "M 42"), (3, "M 42")])
    zapis = _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(tree))
    assert zapis["cancelled"] == "scan"
    assert not strona.lbl_warn.isHidden()
    assert strona.lbl_warn.text() == "Dostawa przerwana w etapie „Skan” - niżej to, co zdążyło wejść"
    assert ": 1 nowa klatka (lighty 1)" in strona.lbl_head.text()


def test_odmowa_startu_mowi_nie_ruszyla_i_nic_wiecej(strona, tmp_path):
    """Źródło nieosiągalne: przebieg nie ruszył, więc raport mówi WYŁĄCZNIE to - bez nagłówka
    „Dostawa z …”, który z zerem klatek czytałby się jak pusta dostawa."""
    i18n.set_lang("pl")
    brak = str(tmp_path / "nie-ma")
    zapis = _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(brak))
    assert zapis["refused"]
    assert not strona.panel.isHidden() and not strona.lbl_warn.isHidden()
    assert strona.lbl_warn.text() == i18n.t("intake.refused", reason=zapis["refused"])
    assert strona.lbl_head.isHidden() and strona.lbl_unresolved.isHidden()
    assert _wiersze(strona) == [] and strona.row_nameless.isHidden()


def test_gest_wygaszony_w_biegu_i_przy_zapisie_naglowkow(strona, tmp_path, monkeypatch):
    """Przycisk gestu gaśnie w biegu Dostawy i przy zapisie nagłówków do plików, a podpowiedź
    mówi dlaczego; po obu wraca z liczbą klatek, które gest ruszy. Slot wołany wprost przy
    wygaszeniu odmawia z powodem i nie otwiera okna."""
    i18n.set_lang("pl")
    tree = _drzewo(tmp_path, "d1", [(1, PLAMA)])
    _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(tree))
    btn = _wiersze(strona)[0].btn
    assert btn.isEnabled() and btn.toolTip() == i18n.t_plural("intake.assign_tip", 1)
    strona.set_writeback_busy(True)
    assert not btn.isEnabled() and btn.toolTip() == i18n.t("intake.assign_writeback_tip")
    _OknoPrzypisania.utworzone = []
    monkeypatch.setattr(przyjmij_mod, "AssignObjectDialog", _OknoPrzypisania)
    strona._on_assign(PLAMA)
    assert _OknoPrzypisania.utworzone == []
    assert strona.komunikaty[-1] == i18n.t("intake.assign_writeback_tip")
    strona.set_writeback_busy(False)
    strona.set_busy(True)
    assert not btn.isEnabled() and btn.toolTip() == i18n.t("intake.assign_busy_tip")
    strona.set_busy(False)
    assert btn.isEnabled()


def test_raport_po_angielsku(qapp, tmp_path):
    """EN: nagłówek, kalibracja i wiersz nazwy z katalogu (język ustawiony PRZED budową widoku,
    jak w aplikacji)."""
    i18n.set_lang("en")
    db_path = _baza(tmp_path)
    con = db.open_db(db_path)
    zegar = _Zegar()
    widok = PrzyjmijView(con, PipelineView(db_path, now_fn=zegar), now_fn=zegar)
    try:
        tree = _drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA), (3, PLAMA)])
        zapis = _przebieg(widok.pipeline_view, lambda: widok.pipeline_view.run_all_on(tree))
        assert widok.lbl_title.text() == "What came in"
        assert widok.lbl_head.text() == (
            f"Intake at {godzina_dostawy(zapis['since'])}: 3 new frames (lights 3)")
        assert widok.lbl_cal.text() == "Calibration of new lights: no flat 3 · no dark 3"
        assert widok.lbl_unresolved.text() == "Not recognized: 3 frames"
        assert [w.lbl.text() for w in _wiersze(widok)] == ["“Plama Zdzicha” ×3 in this intake"]
        assert _wiersze(widok)[0].btn.text() == "Assign object…"
    finally:
        con.close()


@pytest.mark.parametrize("n, nowe, naglowek, inne", [
    (1, "1 nowa klatka", "Nie rozpoznałem: 1 klatka", "i 1 inny"),
    (2, "2 nowe klatki", "Nie rozpoznałem: 2 klatki", "i 2 inne"),
    (5, "5 nowych klatek", "Nie rozpoznałem: 5 klatek", "i 5 innych"),
    (12, "12 nowych klatek", "Nie rozpoznałem: 12 klatek", "i 12 innych"),
    (14, "14 nowych klatek", "Nie rozpoznałem: 14 klatek", "i 14 innych"),
    (22, "22 nowe klatki", "Nie rozpoznałem: 22 klatki", "i 22 inne"),
])
def test_odmiana_liczebnikow_raportu(n, nowe, naglowek, inne):
    """Liczebniki raportu odmieniane helperem katalogu (`t_plural`): 1 · 2-4 · 5+ · 12-14 (zawsze
    „many”) · 22 (znów „few”)."""
    i18n.set_lang("pl")
    assert i18n.t_plural("intake.new", n) == nowe
    assert i18n.t_plural("intake.unresolved_head", n) == naglowek
    assert i18n.t_plural("intake.objects_more", n) == inne
    assert i18n.t_plural("intake.cleared", n) == naglowek.replace(
        "Nie rozpoznałem", "Bez obiektu z decyzji ręki")
    # Zdanie zajętości gestu „Przypisz obiekt…” (wspólne z gestami Zbiorów i osi): „3 klatek” to
    # błąd odmiany, który widać na pasku w trakcie zapisu.
    forma = naglowek.split(": ", 1)[1].replace("klatka", "klatkę")
    assert i18n.t_plural("busy.saving_frames", n) == f"Zapisuję {forma}…"


# ---------------------------------------------------------------- gospodarz: okno aplikacji

def test_kafel_przyjmij_to_jedna_interakcja_do_dostawy(qapp, tmp_path, monkeypatch):
    """Kafel Przyjmij na Domu = JEDNO kliknięcie: strona Dostawy (kontener raportu nad TYM SAMYM
    widokiem Dostawy) i złota akcja `receive()`. Odmowa wraca zdaniem na pasek."""
    i18n.set_lang("pl")
    wolane = []
    odpowiedzi = [None, "powód odmowy"]
    monkeypatch.setattr(PipelineView, "receive",
                        lambda self: (wolane.append(self), odpowiedzi.pop(0))[1])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        win.home_view.tile_przyjmij.click()
        assert wolane == [win.pipeline_view]
        assert win.stack.currentIndex() == STRONA_DOSTAWA
        assert win.stack.currentWidget() is win.przyjmij_view
        assert win.przyjmij_view.pipeline_view is win.pipeline_view
        assert win.pipeline_view.parent() is win.przyjmij_view
        win._show_view(NAV_DOM)
        win.home_view.tile_przyjmij.click()
        assert len(wolane) == 2 and win.statusBar().currentMessage() == "powód odmowy"
    finally:
        win.close()


def test_wciagnij_mastery_otwiera_okno_zniw_i_przyjmuje_korzen(qapp, tmp_path, ustawienia,
                                                               monkeypatch):
    """„Wciągnij mastery…” w Dostawie → okno żniw nad połączeniem okna. Archiwum najpierw z bazy
    (`harvest.archive_root_from_db`), bez niego ostatnie źródło Dostawy - ono bywa podkatalogiem
    nocy. Po oknie łańcuch Dostawy na korzeniu wciągniętych kopii (`run_all_on`, bieg ma jednego
    właściciela), a zdanie wyniku i odmowa łańcucha idą JEDNYM komunikatem: odmowa nie zastępuje
    wiadomości o położonych masterach. Okno, które nic nie wciągnęło, łańcucha nie uruchamia.
    Moduł okna podstawiony w `sys.modules` - gospodarz importuje go leniwie.

    Falsyfikatory: archiwum wprost z ustawień → pierwsze okno dostaje „X:/archiwum/2024-03-01”;
    odmowa osobnym `_flash` → na pasku samo zdanie odmowy."""
    import sys
    import types
    from horreum import harvest
    i18n.set_lang("pl")
    ustawienia.setValue("pipeline/last_source", "X:/archiwum/2024-03-01")
    okna, biegi = [], []
    z_bazy = ["X:/archiwum", None, None]
    wyniki = [("Wciągnięto 1", "X:/archiwum/CALIBRATION/masters/flats"), ("", None),
              ("Wciągnięto 2", "X:/archiwum/CALIBRATION/masters/flats")]
    odmowy = [None, "dostawa w biegu"]

    class _OknoZniw:
        def __init__(self, con, *, now_fn, archive_root, parent=None):
            okna.append((con, archive_root, parent))
            self.summary, self.harvested_root = wyniki.pop(0)

        def exec(self):
            return QDialog.Accepted

    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    monkeypatch.setattr(harvest, "archive_root_from_db", lambda con: z_bazy.pop(0),
                        raising=False)
    monkeypatch.setattr(PipelineView, "run_all_on",
                        lambda self, root: (biegi.append(root), odmowy.pop(0))[1])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        win.pipeline_view.btn_harvest.click()
        assert okna == [(win.con, "X:/archiwum", win)]                # archiwum z bazy
        assert biegi == ["X:/archiwum/CALIBRATION/masters/flats"]
        assert win.statusBar().currentMessage() == "Wciągnięto 1"
        win.pipeline_view.btn_harvest.click()                          # nic nie wciągnięto
        assert okna[1][1] == "X:/archiwum/2024-03-01"                  # bez bazy: ostatnie źródło
        assert biegi == ["X:/archiwum/CALIBRATION/masters/flats"]
        win.pipeline_view.btn_harvest.click()                          # łańcuch odmówił
        assert len(biegi) == 2
        assert win.statusBar().currentMessage() == "Wciągnięto 2 - dostawa w biegu"
    finally:
        win.close()


def test_okno_bieg_mutex_porzadki_i_powrot(qapp, tmp_path, ustawienia, monkeypatch):
    """Gospodarz end-to-end na prawdziwym przebiegu z zapamiętanym źródłem:
    - kafel w biegu nie startuje drugiego biegu (ten sam wątek, odmowa na pasku);
    - gest raportu gaśnie przy zapisie nagłówków z OBU powierzchni writebacku i w biegu;
    - wiersz „bez nazwy” prowadzi do Porządków ze wskazanym kubełkiem (cel wskazany, nie lista);
    - nazwa nadana poza raportem znika z niego przy powrocie na stronę Dostawy."""
    i18n.set_lang("pl")
    tree = _drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA), (3, None)])
    ustawienia.setValue("pipeline/last_source", tree)
    # Bieg trzymany na sondzie źródła, dopóki test nie kliknie drugi raz: mały przebieg kończy
    # się w milisekundach, a odczyt Domu doręcza zdarzenia - bez bramy „drugi klik w biegu”
    # trafiałby czasem w bieg już zakończony.
    brama = threading.Event()
    prawdziwa_sonda = PipelineWorker._zrodlo

    def sonda_za_brama(self, *a, **k):
        brama.wait(10)
        return prawdziwa_sonda(self, *a, **k)

    monkeypatch.setattr(PipelineWorker, "_zrodlo", sonda_za_brama)
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        pv, przyjmij = win.pipeline_view, win.przyjmij_view

        def start():
            win.home_view.tile_przyjmij.click()
            watek = pv._thread
            assert watek is not None, "kafel uruchomił dostawę"
            win._show_view(NAV_DOM)
            win.home_view.tile_przyjmij.click()             # drugi klik w biegu
            assert pv._thread is watek
            assert win.statusBar().currentMessage() == i18n.t("pipeline.refuse.delivery_running")
            assert win.stack.currentIndex() == STRONA_DOSTAWA
            brama.set()

        _przebieg(pv, lambda: start())
        [wiersz] = _wiersze(przyjmij)
        for zrodlo in (win.grid_view.writeback_busy, win.object_view.writeback_busy):
            zrodlo.emit(True)
            assert not wiersz.btn.isEnabled()
            assert wiersz.btn.toolTip() == i18n.t("intake.assign_writeback_tip")
            zrodlo.emit(False)
            assert wiersz.btn.isEnabled()
        win._on_pipeline_running(True)
        assert not wiersz.btn.isEnabled()
        win._on_pipeline_running(False)
        assert wiersz.btn.isEnabled()

        przyjmij.row_nameless.btn.click()
        from horreum.gui import tasks as tasks_mod
        assert win.stack.currentIndex() == STRONA_PORZADKI
        assert win.tasks_view.pages.currentIndex() == tasks_mod._PAGE_OBJECTS
        assert win.object_view.review.currentItem().data(tasks_mod._REVIEW_TAG) == "nameless"

        ids = [r["frame_id"] for r in queries.object_review_frames(win.con, PLAMA)]
        repo.user_assign_object(win.con, alias_norm="PLAMAZDZICHA", canon="NGC7000",
                                catalog="NGC", kind="deep_sky", frame_ids=ids,
                                now="2026-10-10T13:00:00+00:00")
        assert len(_wiersze(przyjmij)) == 1                 # raport sprzed gestu w Porządkach
        win._show_view(NAV_DOSTAWA)
        assert _wiersze(przyjmij) == []
        assert przyjmij.lbl_unresolved.text() == "Nie rozpoznałem: 1 klatka"   # bez nazwy zostaje
    finally:
        win.close()
