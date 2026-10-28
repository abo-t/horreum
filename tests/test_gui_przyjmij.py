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
    assert strona.lbl_objects.text() == "Obiekty: IC1795 ×1 (5 min)"   # 300 s: minuty (AR-75)
    assert strona.lbl_cal.text() == "Kalibracja nowych lightów: bez flatu 4 · bez darka 4"
    assert strona.lbl_unresolved.text() == "Nie rozpoznałem: 3 klatki"
    assert strona.lbl_unresolved.property("role") == "warn"          # robota czeka - rola ostrzeżenia
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
    assert strona.lbl_unresolved.property("role") == "ok"            # komplet - rola ok, po geście też
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
    assert strona.lbl_objects.text() == "Obiekty: NGC7000 ×1 (5 min)"     # TA dostawa (AR-75)
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


# ---------------------------------------------------------------- AR-99: log przebiegu po geście

def test_log_przebiegu_po_gescie_dostaje_podpis_czasu_a_bez_gestu_nie(strona, tmp_path,
                                                                     monkeypatch):
    """AR-99: po „Przypisz obiekt…” panel liczy się ze stanu („Wszystko rozpoznane”), a log etapów
    pod nim dalej mówi o nierozpoznanej nazwie - log dostaje podpis „Przebieg z HH:MM (stan sprzed
    Twoich zmian)” z godziną startu przebiegu. Samo przeliczenie raportu (wejście na stronę) bez
    zmiany stanu podpisu nie stawia; nowy przebieg go zdejmuje; zapis INNYM połączeniem (wątek
    zapisu, inny widok) też jest zmianą po przebiegu.

    Falsyfikator: podpis przy każdym przeliczeniu raportu → pierwsze `odswiez_raport()` go stawia."""
    i18n.set_lang("pl")
    pv = strona.pipeline_view
    tree = _drzewo(tmp_path, "d1", [(1, PLAMA), (2, PLAMA)])
    zapis = _przebieg(pv, lambda: pv.run_all_on(tree))
    assert "Plama Zdzicha" in pv.lbl_summary.text() and pv.lbl_summary_head.isHidden()
    strona.odswiez_raport()                             # wejście na stronę, stan bez zmian
    assert pv.lbl_summary_head.isHidden()
    monkeypatch.setattr(przyjmij_mod, "AssignObjectDialog", _OknoPrzypisania)
    _wiersze(strona)[0].btn.click()
    assert strona.lbl_unresolved.text() == "Wszystko rozpoznane"
    assert not pv.lbl_summary_head.isHidden()
    assert pv.lbl_summary_head.text() == (
        f"Przebieg z {godzina_dostawy(zapis['since'])} (stan sprzed Twoich zmian)")
    _przebieg(pv, lambda: pv.run_all_on(tree))          # log znów jest stanem z tej chwili
    assert pv.lbl_summary_head.isHidden()
    strona.odswiez_raport()
    assert pv.lbl_summary_head.isHidden()
    ids = [fid for (fid,) in strona.con.execute(
        "SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id WHERE h.object_raw = ?",
        (PLAMA,))]
    inne = db.connect(str(tmp_path / "przyjmij.db"))
    try:
        repo.clear_object_assignment(inne, frame_ids=ids, now="2026-10-10T13:00:00+00:00")
    finally:
        inne.close()
    strona.odswiez_raport()
    assert not pv.lbl_summary_head.isHidden()


def test_log_bez_gestu_po_przebiegu_zostaje_bez_podpisu_w_oknie(qapp, tmp_path):
    """AR-99 w oknie aplikacji: odświeżenie widoków po przebiegu i wędrówka między stronami (Dom,
    Porządki, Zbiory, powrót na Dostawę) nie są gestem - log zostaje bez podpisu. Gest w Zbiorach
    (połączenie okna) przy powrocie na Dostawę podpis stawia.

    Falsyfikator: odcisk stanu wzięty przed odświeżeniem widoków gospodarza albo widok, który pisze
    przy odczycie → podpis po samym powrocie na Dostawę."""
    from horreum.gui.app import NAV_PORZADKI, NAV_ZBIORY
    i18n.set_lang("pl")
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        pv = win.pipeline_view
        tree = _drzewo(tmp_path, "d1", [(1, PLAMA), (2, None)])
        win._show_view(NAV_DOSTAWA)
        _przebieg(pv, lambda: pv.run_all_on(tree))
        for nav in (NAV_DOM, NAV_PORZADKI, NAV_ZBIORY, NAV_DOSTAWA, NAV_DOM, NAV_DOSTAWA):
            win._show_view(nav)
            qapp.processEvents()
        assert pv.lbl_summary_head.isHidden()
        ids = [fid for (fid,) in win.con.execute(
            "SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id WHERE h.object_raw = ?",
            (PLAMA,))]
        win._show_view(NAV_ZBIORY)
        g = repo.user_assign_object(win.con, alias_norm=None, canon="NGC7000", catalog="NGC",
                                    kind="deep_sky", frame_ids=ids, now="2026-10-10T13:00:00+00:00")
        assert g.assigned == 1
        win._show_view(NAV_DOSTAWA)
        assert not pv.lbl_summary_head.isHidden()
    finally:
        win.close()


def test_przebieg_ktory_nie_ruszyl_nie_dostaje_podpisu_po_gescie(strona, tmp_path):
    """Z3: przebieg odmówiony przed pierwszym plikiem (źródło niedostępne) ma log „NIE WYKONANO”,
    który nie opisuje żadnego stanu - gest po nim nie stawia nad nim „Przebieg z HH:MM (stan
    sprzed Twoich zmian)”, a podpis po wcześniejszym przebiegu gaśnie razem z tamtym logiem.

    Falsyfikator: odcisk stanu brany także przy `refused` → po geście podpis nad „nie wykonano”."""
    i18n.set_lang("pl")
    pv = strona.pipeline_view
    _przebieg(pv, lambda: pv.run_all_on(_drzewo(tmp_path, "d1", [(1, PLAMA)])))
    ids = [fid for (fid,) in strona.con.execute(
        "SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id WHERE h.object_raw = ?",
        (PLAMA,))]

    def gest(zmiana):
        inne = db.connect(str(tmp_path / "przyjmij.db"))
        try:
            zmiana(inne)
        finally:
            inne.close()
        strona.odswiez_raport()

    gest(lambda c: repo.user_assign_object(c, alias_norm=None, canon="NGC7000", catalog="NGC",
                                           kind="deep_sky", frame_ids=ids,
                                           now="2026-10-10T13:00:00+00:00"))
    assert not pv.lbl_summary_head.isHidden()            # gest po przebiegu, który ruszył
    zapis = _przebieg(pv, lambda: pv.run_all_on(str(tmp_path / "odlaczony_udzial")))
    assert zapis["refused"] and "[skan] NIE WYKONANO - " in pv.lbl_summary.text()
    assert pv.lbl_summary_head.isHidden()
    gest(lambda c: repo.clear_object_assignment(c, frame_ids=ids, now="2026-10-10T13:01:00+00:00"))
    assert pv.lbl_summary_head.isHidden()


def test_wciagnij_z_domu_w_biegu_albo_przy_zapisie_nie_otwiera_okna(qapp, tmp_path, ustawienia,
                                                                   monkeypatch):
    """Z6: „Wciągnij z WBPP…” z menu „Więcej…” Domu w trakcie biegu Dostawy albo zapisu nagłówków
    otwierało okno żniw, a „Zamknij i przyjmij” kończyło się odmową łańcucha - rodowód dokładny
    wciągniętych stosów zostawał tylko w folderze wydania. Bramka `powod_odmowy_biegu` stoi PRZED
    oknem (odmowa na pasku), a pozycja menu gaśnie w biegu z podpowiedzią - zdaniem odmowy.

    Falsyfikator: bramka dopiero przy `run_all_on` → okno otwiera się w biegu (`okna` niepuste)."""
    import sys
    import types
    from horreum.gui import home as home_mod
    i18n.set_lang("pl")
    okna = []

    class _OknoZniw:
        def __init__(self, con, **_kw):
            okna.append(con)
            self.summary, self.harvested_root, self.harvested_stacks = "", None, []

        def exec(self):
            return QDialog.Accepted

    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)
    brama = threading.Event()                     # bieg trzymany na sondzie źródła, jak w teście mutexu
    prawdziwa_sonda = PipelineWorker._zrodlo

    def sonda_za_brama(self, *a, **k):
        brama.wait(10)
        return prawdziwa_sonda(self, *a, **k)

    monkeypatch.setattr(PipelineWorker, "_zrodlo", sonda_za_brama)
    tree = _drzewo(tmp_path, "d1", [(1, PLAMA)])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    from test_gui_gospodarz import _stan_pozycji_zniw   # stan pozycji z chwili otwarcia menu (AR-354)
    try:
        pv = win.pipeline_view
        win._zegar_priorytetu.setInterval(60000)
        w_biegu = i18n.t("pipeline.refuse.delivery_running")
        assert _stan_pozycji_zniw(win)[0]

        def start():
            assert pv.run_all_on(tree) is None
            assert _stan_pozycji_zniw(win) == (False, w_biegu)
            win._on_wiecej_domu(home_mod.WIECEJ_ZNIWA)            # wejście wprost, mimo wygaszenia
            assert okna == [] and win.report_label.text() == w_biegu
            brama.set()

        _przebieg(pv, start)
        assert _stan_pozycji_zniw(win)[0]
        win._on_writeback_busy(True)
        win._on_wiecej_domu(home_mod.WIECEJ_ZNIWA)
        assert okna == [] and win.report_label.text() == i18n.t("pipeline.refuse.writeback")
        win._on_writeback_busy(False)
        win._on_wiecej_domu(home_mod.WIECEJ_ZNIWA)
        assert okna == [win.con]
    finally:
        brama.set()
        win.close()


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
        # Okno przypisania z tego wiersza mówi po angielsku angielskim cudzysłowem (dawniej „…”).
        teksty = []

        def zamknij(dlg):
            teksty.append(dlg.head.text())
            dlg.reject()

        stan = _prowadz_dialog(zamknij)
        _wiersze(widok)[0].btn.click()
        assert stan["widziane"], "okno przypisania się nie pokazało"
        assert teksty[0].startswith("Group “Plama Zdzicha” - 3 frames.")
        polskie = [k for k, w in i18n.CATALOG.items()
                   if (k.startswith("assign.") or k == "object.alias_no_alnum")
                   and any("„" in s for s in (w["en"].values() if isinstance(w["en"], dict)
                                                   else [w["en"]]))]
        assert polskie == [], polskie
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
        assert len(wolane) == 2 and win.report_label.text() == "powód odmowy"
    finally:
        win.close()


def test_wciagnij_mastery_otwiera_okno_zniw_i_przyjmuje_korzen(qapp, tmp_path, ustawienia,
                                                               monkeypatch):
    """„Wciągnij z WBPP…” w Dostawie → okno żniw nad połączeniem okna. Archiwum najpierw z bazy
    (`harvest.archive_root_from_db`), bez niego ostatnie źródło Dostawy - ono bywa podkatalogiem
    nocy. Po oknie łańcuch Dostawy na korzeniu wciągniętych kopii (`run_all_on`, bieg ma jednego
    właściciela), a zdanie wyniku i odmowa łańcucha idą JEDNYM komunikatem: odmowa nie zastępuje
    wiadomości o położonych masterach. Okno, które nic nie wciągnęło, łańcucha nie uruchamia.
    Moduł okna podstawiony w `sys.modules` - gospodarz importuje go leniwie.

    Okno dostaje też folder roboczy WBPP (`_WBPP` złożony z `work/root`) i korzenie wszystkich
    zapamiętanych kart wydań.

    Falsyfikatory: archiwum wprost z ustawień → pierwsze okno dostaje „X:/archiwum/2024-03-01”;
    odmowa osobnym `_flash` → na pasku samo zdanie odmowy; folder roboczy bez `_WBPP` → okno
    szukałoby wydań w katalogu, który wskazał człowiek, a nie w tym, który zakłada wydanie."""
    import sys
    import types
    from horreum import harvest
    from horreum.gui import projection_dialog
    i18n.set_lang("pl")
    ustawienia.setValue("pipeline/last_source", "X:/archiwum/2024-03-01")
    ustawienia.setValue("work/root", "X:/praca")
    praca = os.path.normpath("X:/praca/_WBPP")
    projection_dialog.remember_target("Folder roboczy", praca)
    projection_dialog.remember_target("Stół", "X:/inna/_Review", select=False)
    okna, biegi, parametry = [], [], []
    z_bazy = ["X:/archiwum", None, None]
    wyniki = [("Wciągnięto 1", "X:/archiwum/CALIBRATION/masters/flats"), ("", None),
              ("Wciągnięto 2", "X:/archiwum/CALIBRATION/masters/flats")]
    odmowy = [None, "dostawa w biegu"]

    class _OknoZniw:
        def __init__(self, con, *, now_fn, archive_root, work_root=None, release_roots=(),
                     parent=None):
            okna.append((con, archive_root, parent))
            parametry.append((work_root, list(release_roots)))
            self.summary, self.harvested_root = wyniki.pop(0)
            self.harvested_stacks = []

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
        assert parametry[0] == (praca, [praca, os.path.normpath("X:/inna/_Review")])
        assert biegi == ["X:/archiwum/CALIBRATION/masters/flats"]
        assert win.report_label.text() == "Wciągnięto 1"
        win.pipeline_view.btn_harvest.click()                          # nic nie wciągnięto
        assert okna[1][1] == "X:/archiwum/2024-03-01"                  # bez bazy: ostatnie źródło
        assert biegi == ["X:/archiwum/CALIBRATION/masters/flats"]
        win.pipeline_view.btn_harvest.click()                          # łańcuch odmówił
        assert len(biegi) == 2
        assert win.report_label.text() == "Wciągnięto 2 - dostawa w biegu"
        assert parametry == [parametry[0]] * 3                         # każde otwarcie: te same wejścia
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
        from test_gui_mainwindow import _zapis_paska
        pv, przyjmij = win.pipeline_view, win.przyjmij_view
        odmowa = i18n.t("pipeline.refuse.delivery_running")
        # AR-97: okno priorytetu wydłużone na czas testu - bieg trwa tu milisekundy, ale wolna
        # maszyna nie może zamienić asercji o oknie w wyścig z zegarem.
        win._zegar_priorytetu.setInterval(60000)
        pasek = _zapis_paska(win)

        def start():
            win.home_view.tile_przyjmij.click()
            watek = pv._thread
            assert watek is not None, "kafel uruchomił dostawę"
            win._show_view(NAV_DOM)
            win.home_view.tile_przyjmij.click()             # drugi klik w biegu
            assert pv._thread is watek
            assert win.report_label.text() == odmowa
            assert win.stack.currentIndex() == STRONA_DOSTAWA
            # odmowa także w treści strony - pasek żyje sekundy, strona z postępem do końca biegu
            assert not przyjmij.lbl_odmowa.isHidden()
            assert przyjmij.lbl_odmowa.text() == odmowa
            brama.set()

        _przebieg(pv, lambda: start())
        assert przyjmij.lbl_odmowa.isHidden(), "odmowa gaśnie z końcem biegu, który ją spowodował"
        # AR-97: „<etap>: gotowe.” łańcucha nie wyparło odmowy kafla - czeka na koniec okna.
        po_odmowie = pasek[len(pasek) - 1 - pasek[::-1].index(odmowa):]
        assert not any(m.endswith(": gotowe.") for m in po_odmowie), po_odmowie
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


# --- rodowód stosów z żniw: zapis PO przebiegu Dostawy, jednorazowy nasłuch ---

ZNACZNIK_BIEGU = "2026-10-10T12:00:00+00:00"      # `last_run["since"]` przebiegu uruchomionego po żniwach


def _zniwa_ze_stosami(monkeypatch, stosy, odmowa=None, podsumowanie=None):
    """Okno żniw podstawione w `sys.modules`: oddaje `stosy` jako wciągnięte w oknie i korzeń do
    przyjęcia; `run_all_on` bez wątku (zwraca `odmowa`, `None` = łańcuch ruszył). Zwraca rejestr
    wywołań `stacks.record_harvest_inputs` (podmienionego na atrapę: stos o sha1 `zly` rzuca
    `ValueError`, `brak` oddaje `no_integration`, reszta przechodzi)."""
    import sys
    import types
    from horreum import stacks
    wolane = []

    class _OknoZniw:
        def __init__(self, con, *, now_fn, archive_root, work_root=None, release_roots=(),
                     parent=None):
            # `podsumowanie` (wołane przy otwarciu okna, w bieżącym języku) - zdanie okna z katalogu;
            # bez niego stały znacznik testów rodowodu
            self.summary = podsumowanie() if podsumowanie is not None else "Wciągnięto stosy"
            self.harvested_root = "X:/archiwum"
            # `(sha1_data, wejścia, kanon wydania)`; para bez kanonu = stos bez wydania (porównanie
            # obiektu z wydaniem milczy - te testy mówią o rodowodzie)
            self.harvested_stacks = [s if len(s) == 3 else (*s, None) for s in stosy]

        def exec(self):
            return QDialog.Accepted

    def _zapis(con, *, master_sha1_data, input_frame_ids, now, actor="harvest"):
        wolane.append((con, master_sha1_data, list(input_frame_ids), now))
        if master_sha1_data == "zly":
            raise ValueError("wejście spoza lightów")
        reason = "no_integration" if master_sha1_data == "brak" else None
        return {"reason": reason, "linked": 2, "upgraded": 0, "dropped": 0, "kept_user": 0}

    modul = types.ModuleType("horreum.gui.harvest_dialog")
    modul.HarvestDialog = _OknoZniw
    monkeypatch.setitem(sys.modules, "horreum.gui.harvest_dialog", modul)

    def _run_all_on(self, root):
        if odmowa is None:
            self.last_run["since"] = ZNACZNIK_BIEGU       # `_start_stage` robi to synchronicznie
        return odmowa

    monkeypatch.setattr(PipelineView, "run_all_on", _run_all_on)
    monkeypatch.setattr(stacks, "record_harvest_inputs", _zapis)
    return wolane


def _zapis_przebiegu(**pola):
    """Zapis końca przebiegu w kształcie `PipelineView.last_run` (kopia emitowana przez
    `run_finished`)."""
    return {**PipelineView._pusty_zapis_przebiegu(), "stage": "all", "since": ZNACZNIK_BIEGU, **pola}


def test_rodowod_ze_zniw_zapisuje_sie_po_przebiegu_bez_przerwania_i_tylko_raz(
        qapp, tmp_path, ustawienia, monkeypatch):
    """Stos wciągnięty w oknie żniw dostaje rodowód z HISTORII pliku dopiero po łańcuchu Dostawy
    (wiersz integracji stawia łańcuch): do końca przebiegu `record_harvest_inputs` nie jest wołane,
    po przebiegu bez przerwania leci per stos na połączeniu okna, a zdanie na pasku liczy osobno
    stosy z historii i te, które zostają z rodowodem okna czasu (odmowa zapisu: `ValueError`,
    `no_integration`) - strata nazwana, nie ukryta. Nasłuch jest JEDNORAZOWY: kolejny przebieg
    Dostawy niczego nie zapisuje.

    Falsyfikatory: zapis w slocie `_on_open_harvest` → rejestr niepusty przed `run_finished`;
    nasłuch bez rozłączenia → drugi `run_finished` powiela zapis."""
    i18n.set_lang("pl")
    wolane = _zniwa_ze_stosami(
        monkeypatch, [("a", [1, 2]), ("zly", [3]), ("brak", [4]), ("b", [5, 6, 7])])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        odswiezenia = _szpieg_odswiezen(win)
        win.pipeline_view.btn_harvest.click()
        assert wolane == [] and odswiezenia == []             # przed końcem przebiegu nic nie jedzie
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert [(s, w) for _c, s, w, _n in wolane] == [
            ("a", [1, 2]), ("zly", [3]), ("brak", [4]), ("b", [5, 6, 7])]
        assert all(c is win.con and n for c, _s, _w, n in wolane)       # połączenie okna, zegar okna
        # trzy człony naraz: z historii · okno czasu (ValueError) · bez rodowodu (no_integration);
        # zdanie DOKLEJA się do podsumowania okna żniw, nie zastępuje go
        assert win._pelny_komunikat == (
            "Wciągnięto stosy - rodowód: 2 stosy z historii żniw; "
            "1 stos zostaje z rodowodem okna czasu; "
            "1 stos bez rodowodu - Dostawa nie ujęła go jako stosu; "
            "uruchom „Przyjmij nowe” na archiwum")
        assert odswiezenia == ["widoki", "panel"]             # po zapisie, tą drogą co po przebiegu
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())         # następny przebieg Dostawy
        assert len(wolane) == 4 and len(odswiezenia) == 2
    finally:
        win.close()


@pytest.mark.parametrize("pola", [
    {"cancelled": "scan"}, {"refused": "źródło niedostępne"}, {"failed": "[group] błąd"}])
def test_rodowod_ze_zniw_nie_zapisuje_po_przebiegu_przerwanym_odmowionym_ani_z_bledem(
        qapp, tmp_path, ustawienia, monkeypatch, pola):
    """Przebieg przerwany, odmówiony albo zakończony błędem nie zapisuje niczego (stos zostaje
    z rodowodem okna, jak bez żniw) - a nasłuch i tak znika po pierwszym wywołaniu, więc
    późniejszy, udany przebieg Dostawy też niczego nie dopisuje. Pasek mówi, że rodowód dokładny
    NIE został zapisany i folderu wydania nie wolno kasować (bramka `kimi` Z7, AR-104)."""
    i18n.set_lang("pl")
    wolane = _zniwa_ze_stosami(monkeypatch, [("a", [1])])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        win.pipeline_view.btn_harvest.click()
        win.pipeline_view.run_finished.emit(_zapis_przebiegu(**pola))
        utrata = ("rodowód dokładny stosów (1) NIE zapisany - Dostawa nie doszła do końca; folderu wydania "
                  "nie kasuj, otwórz ponownie „Wciągnij z WBPP…” i „Zamknij i przyjmij do archiwum”")
        # Instrukcja ratunku na początku, za nią wiersz awarii albo powód odmowy i podsumowanie okna
        # żniw - zdanie zastępuje oba raporty, więc niesie je (AR-218).
        przyczyna = [pola[k] for k in ("failed", "refused") if k in pola]
        assert win._pelny_komunikat == " - ".join([utrata, *przyczyna, "Wciągnięto stosy"])
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert wolane == []
    finally:
        win.close()


def test_rodowod_ze_zniw_bez_nasluchu_gdy_lancuch_odmowil_albo_nie_ma_stosow(
        qapp, tmp_path, ustawienia, monkeypatch):
    """Odmowa łańcucha (`run_all_on` oddaje powód) = brak przebiegu, na który można czekać - pasek
    po powodzie mówi, że rodowód dokładny stosów nie został zapisany (bramka `kimi` Z7); okno,
    które wciągnęło same mastery (pusta lista stosów), też nie podpina nasłuchu."""
    i18n.set_lang("pl")
    wolane = _zniwa_ze_stosami(monkeypatch, [("a", [1]), ("b", [2])], odmowa="dostawa w biegu")
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        win.pipeline_view.btn_harvest.click()
        assert win._pelny_komunikat == (
            "Wciągnięto stosy - dostawa w biegu - rodowód dokładny stosów (2) NIE zapisany - Dostawa nie "
            "doszła do końca; folderu wydania nie kasuj, otwórz ponownie „Wciągnij z WBPP…” i „Zamknij "
            "i przyjmij do archiwum”")
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert wolane == []
    finally:
        win.close()
    wolane = _zniwa_ze_stosami(monkeypatch, [])
    (tmp_path / "bez_stosow").mkdir()
    win = MainWindow(_baza(tmp_path / "bez_stosow"), now_fn=_Zegar())
    try:
        win.pipeline_view.btn_harvest.click()
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert wolane == []
    finally:
        win.close()


def test_rodowod_ze_zniw_nie_zapisuje_na_innej_bazie(qapp, tmp_path, ustawienia, monkeypatch):
    """Zmiana bazy w trakcie przebiegu: okno ma już inne połączenie, więc rodowód stosów z poprzedniej
    bazy nie jedzie na nową (stosy tam nie istnieją)."""
    wolane = _zniwa_ze_stosami(monkeypatch, [("a", [1])])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        widok, prawdziwe = win.pipeline_view, win.con
        widok.btn_harvest.click()
        win.con = object()                                    # inna baza otwarta w trakcie biegu
        przed = win._pelny_komunikat
        widok.run_finished.emit(_zapis_przebiegu(failed="[scan] błąd"))
        assert wolane == [] and win._pelny_komunikat == przed  # zdanie o stosach nie dotyczy bazy na ekranie
    finally:
        win.con = prawdziwe
        win.close()


@pytest.mark.parametrize("n, pl, en", [
    (1, "rodowód: 1 stos z historii żniw", "lineage: 1 stack from harvest history"),
    (2, "rodowód: 2 stosy z historii żniw", "lineage: 2 stacks from harvest history"),
    (4, "rodowód: 4 stosy z historii żniw", "lineage: 4 stacks from harvest history"),
    (5, "rodowód: 5 stosów z historii żniw", "lineage: 5 stacks from harvest history"),
    (12, "rodowód: 12 stosów z historii żniw", "lineage: 12 stacks from harvest history"),
    (14, "rodowód: 14 stosów z historii żniw", "lineage: 14 stacks from harvest history"),
    (22, "rodowód: 22 stosy z historii żniw", "lineage: 22 stacks from harvest history"),
])
def test_zdanie_rodowodu_odmiana_liczebnika(qapp, n, pl, en):
    """Odmiana przez mechanizm katalogu (`t_plural`): 1 · 2-4 · 5 · 12-14 · 22."""
    for jezyk, oczekiwane in (("pl", pl), ("en", en)):
        i18n.set_lang(jezyk)
        assert i18n.t_plural("status.harvest_lineage", n) == oczekiwane


@pytest.mark.parametrize("n, pl", [
    (1, "1 stos zostaje z rodowodem okna czasu"),
    (3, "3 stosy zostają z rodowodem okna czasu"),
    (5, "5 stosów zostaje z rodowodem okna czasu"),
    (13, "13 stosów zostaje z rodowodem okna czasu"),
    (22, "22 stosy zostają z rodowodem okna czasu"),
])
def test_zdanie_stosow_bez_rodowodu_z_historii_odmiana_liczebnika(qapp, n, pl):
    i18n.set_lang("pl")
    assert i18n.t_plural("status.harvest_lineage_window", n) == pl


def _szpieg_odswiezen(win):
    """Rejestr odświeżeń widoków wołanych przez gospodarza po przebiegu: pełne odświeżenie
    (`_odswiez_widoki_po_przebiegu`) i panel rodowodu gridu. Podmiana na instancji okna."""
    wolane = []
    win._odswiez_widoki_po_przebiegu = lambda: wolane.append("widoki")
    win.grid_view.refresh_lineage_panel = lambda: wolane.append("panel")
    return wolane


def test_rodowod_ze_zniw_ignoruje_cudzy_run_finished_i_czeka_na_wlasciwy(
        qapp, tmp_path, ustawienia, monkeypatch):
    """Okno żniw mogło się otworzyć w fazie odświeżania po POPRZEDNIM biegu, zanim ten wyemitował
    `run_finished`: sygnał z cudzym znacznikiem startu nie zapisuje niczego i NIE rozłącza nasłuchu
    (zapis z nim wyczerpałby jednorazowość i rodowód przepadłby). Właściwy przebieg zapisuje raz.

    Falsyfikator: brak porównania znaczników → pierwszy (cudzy) sygnał zapisuje rodowód przed
    łańcuchem żniw, gdy wiersza integracji jeszcze nie ma."""
    wolane = _zniwa_ze_stosami(monkeypatch, [("a", [1])])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        odswiezenia = _szpieg_odswiezen(win)
        win.pipeline_view.btn_harvest.click()
        win.pipeline_view.run_finished.emit(
            _zapis_przebiegu(since="2026-10-10T11:00:00+00:00"))        # poprzedni bieg
        assert wolane == [] and odswiezenia == []
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())          # właściwy
        assert [s for _c, s, _w, _n in wolane] == ["a"]
        win.pipeline_view.run_finished.emit(
            _zapis_przebiegu(since="2026-10-10T13:00:00+00:00"))        # nasłuch już zdjęty
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert len(wolane) == 1
    finally:
        win.close()


def test_rodowod_ze_zniw_odswieza_widoki_takze_gdy_zapis_rzuci(qapp, tmp_path, ustawienia,
                                                                monkeypatch):
    """Zapis idzie PO odświeżeniu widoków przez gospodarza, więc widoki muszą dostać drugie, także
    gdy zapis rzuci wyjątek inny niż `ValueError` (ten leci dalej - slot Qt wypisuje go do
    `sys.excepthook` - a pasek nie dostaje zdania z połowy pracy)."""
    import sys
    wolane = _zniwa_ze_stosami(monkeypatch, [("a", [1]), ("boom", [2])])
    from horreum import stacks
    atrapa = stacks.record_harvest_inputs

    def _rzuca(con, **kw):
        if kw["master_sha1_data"] == "boom":
            raise RuntimeError("baza zablokowana")
        return atrapa(con, **kw)

    monkeypatch.setattr(stacks, "record_harvest_inputs", _rzuca)
    zlapane = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, w, tb: zlapane.append(typ))
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        odswiezenia = _szpieg_odswiezen(win)
        win.pipeline_view.btn_harvest.click()
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert [s for _c, s, _w, _n in wolane] == ["a"]       # drugi stos nie doszedł do atrapy
        assert odswiezenia == ["widoki", "panel"]
        assert zlapane == [RuntimeError]
        assert win._pelny_komunikat == "Wciągnięto stosy"     # zdanie z połowy pracy nie wychodzi na pasek
    finally:
        win.close()


def test_rodowod_ze_zniw_pusty_rodowod_nie_flashuje_drugi_raz(qapp, tmp_path, ustawienia,
                                                               monkeypatch):
    """Zdanie rodowodu dokleja się do podsumowania okna; gdy rodowód nie ma żadnego członu, pasek
    zostaje przy samym podsumowaniu (nic nie jest flashowane ponownie)."""
    _zniwa_ze_stosami(monkeypatch, [("a", [1])])
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        _szpieg_odswiezen(win)
        assert win._zdanie_rodowodu(win.con, []) == ""
        monkeypatch.setattr(win, "_zdanie_rodowodu", lambda con, stosy: "")
        win.pipeline_view.btn_harvest.click()
        flash = []
        prawdziwy_flash = win._flash
        win._flash = lambda msg, *a, **k: (flash.append(msg), prawdziwy_flash(msg, *a, **k))
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert flash == []
        assert win._pelny_komunikat == "Wciągnięto stosy"
    finally:
        win.close()


@pytest.mark.parametrize("n, pl, en", [
    (1, "1 stos bez rodowodu - Dostawa nie ujęła go jako stosu; uruchom „Przyjmij nowe” na archiwum",
     "1 stack without lineage - Intake did not take it in as a stack; run Receive new on the archive"),
    (2, "2 stosy bez rodowodu - Dostawa nie ujęła ich jako stosów; uruchom „Przyjmij nowe” na archiwum",
     "2 stacks without lineage - Intake did not take them in as stacks; run Receive new on the archive"),
    (5, "5 stosów bez rodowodu - Dostawa nie ujęła ich jako stosów; uruchom „Przyjmij nowe” na archiwum",
     "5 stacks without lineage - Intake did not take them in as stacks; run Receive new on the archive"),
    (12, "12 stosów bez rodowodu - Dostawa nie ujęła ich jako stosów; uruchom „Przyjmij nowe” na archiwum",
     "12 stacks without lineage - Intake did not take them in as stacks; run Receive new on the archive"),
    (22, "22 stosy bez rodowodu - Dostawa nie ujęła ich jako stosów; uruchom „Przyjmij nowe” na archiwum",
     "22 stacks without lineage - Intake did not take them in as stacks; run Receive new on the archive"),
])
def test_zdanie_stosow_bez_rodowodu_odmiana_liczebnika(qapp, n, pl, en):
    for jezyk, oczekiwane in (("pl", pl), ("en", en)):
        i18n.set_lang(jezyk)
        assert i18n.t_plural("status.harvest_lineage_none", n) == oczekiwane


# --- obiekt stosu wobec obiektu wydania (AR-103): zdanie + gest „Przypisz obiekt wydania” na pasku ---


def _baza_ze_stosem(tmp_path, raw_stosu="IC 1795", dalsze=()):
    """Baza okna ze stosem `stos-ic` (id 1; obiekt z nagłówka stawia resolver - zwykła droga Dostawy)
    i obiektem wydania NGC7000; `dalsze` = kolejne stosy `[(id, sha1_data, OBJECT)]`. Przygotowana
    PRZED oknem: okno otwiera własne połączenie."""
    from horreum import resolver
    path = _baza(tmp_path)
    con = db.open_db(path)
    for fid, sha, raw in ((1, "stos-ic", raw_stosu), *dalsze):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                    "VALUES (?, 'master_light', 'xisf', ?, ?)", (fid, sha, ZNACZNIK_BIEGU))
        con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (?, ?, '{}')", (fid, raw))
    con.commit()
    resolver.run_resolver(con, now=ZNACZNIK_BIEGU)
    repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=ZNACZNIK_BIEGU)
    con.close()
    return path


def _obiekt_stosu(win):
    r = win.con.execute("SELECT o.canon, f.object_source FROM frame f LEFT JOIN object o ON o.id = f.object_id "
                        "WHERE f.id = 1").fetchone()
    return r[0], r[1]


def _zdarzenia(win):
    return win.con.execute("SELECT count(*) FROM event").fetchone()[0]


def _zniwa_i_przebieg(win):
    """„Wciągnij z WBPP…” (okno żniw podstawione) i koniec przebiegu Dostawy, który ono uruchomiło."""
    win.pipeline_view.btn_harvest.click()
    win.pipeline_view.run_finished.emit(_zapis_przebiegu())


def _klik_recepty(win):
    """Prawdziwy klik myszą w przycisk recepty na pasku - po odstępie dwukliku poprzedniego gestu
    (blokada Z5 trzyma przycisk wygaszony; pętla zdarzeń bez `qWait`)."""
    import time
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    koniec = time.monotonic() + QApplication.doubleClickInterval() / 1000 + 2
    while not win.recipe_label.isEnabled():
        assert time.monotonic() < koniec, "recepta nie wróciła po odstępie dwukliku"
        QApplication.processEvents()
        time.sleep(0.02)
    QTest.mouseClick(win.recipe_label, Qt.LeftButton)


def test_obiekt_stosu_inny_niz_wydanie_zdanie_gest_cofniecie_i_drugi_bieg(qapp, tmp_path, ustawienia,
                                                                         monkeypatch):
    """Po łańcuchu żniw stos z obiektem z nagłówka innym niż obiekt wydania: zdanie NA POCZĄTKU raportu
    mówi, co się nie zgadza, przycisk na pasku - co zrobi gest; do kliku baza stoi (nigdy cicha
    podmiana). Klik zapisuje obiekt wydania ręką, recepta zmienia się w „Cofnij” (wygaszone przez odstęp
    dwukliku - drugi klik tego samego ruchu nie cofa), klik „Cofnij” przywraca obiekt z nagłówka.
    Ponowne żniwa: rozjazd wraca, gest drugi raz; trzecie żniwa - stos zgodny, zdanie i przycisk milczą,
    dziennik stoi. Bilans osi §5.9 zielony.

    Falsyfikatory: `_rozjazdy_obiektu_wydania` zwraca `[]` → brak zdania i przycisku; klinga bez
    zapisu → stos dalej IC1795 po kliku; cofnięcie bez `before` → stos zostaje NGC7000."""
    i18n.set_lang("pl")
    _zniwa_ze_stosami(monkeypatch, [("stos-ic", [7], "NGC7000")])
    win = MainWindow(_baza_ze_stosem(tmp_path), now_fn=_Zegar())
    try:
        win.show()
        _zniwa_i_przebieg(win)
        assert win._pelny_komunikat == ("1 stos ma inny obiekt niż wydanie (stos: IC1795, wydanie: NGC7000) - "
                                        "Wciągnięto stosy - rodowód: 1 stos z historii żniw")
        assert _obiekt_stosu(win) == ("IC1795", "header")
        assert win.recipe_label.isVisible() and win.recipe_label.text() == "Przypisz obiekt wydania"

        _klik_recepty(win)
        assert _obiekt_stosu(win) == ("NGC7000", "user")
        assert win._pelny_komunikat == "Obiekt wydania przypisany ręką: 1 stos (NGC7000)"
        assert win.recipe_label.text() == "Cofnij" and not win.recipe_label.isEnabled()

        _klik_recepty(win)
        assert _obiekt_stosu(win) == ("IC1795", "header")
        assert win._pelny_komunikat == "Cofnięto: 1 stos wrócił do poprzedniego obiektu"
        assert not win.recipe_label.isVisible()

        _zniwa_i_przebieg(win)
        assert win.recipe_label.text() == "Przypisz obiekt wydania"
        _klik_recepty(win)
        assert _obiekt_stosu(win) == ("NGC7000", "user")
        przed = _zdarzenia(win)
        _zniwa_i_przebieg(win)
        assert win._pelny_komunikat == "Wciągnięto stosy - rodowód: 1 stos z historii żniw"
        assert not win.recipe_label.isVisible() and _zdarzenia(win) == przed
        [osi] = [p for p in audit.entity_event_parity(win.con) if p.name == "frame.object_id"]
        assert osi.ok
    finally:
        win.close()


def test_stos_bez_obiektu_zdanie_po_angielsku_a_dryf_przed_klikiem_nic_nie_zapisuje(
        qapp, tmp_path, ustawienia, monkeypatch):
    """Stos BEZ obiektu (nazwa potoczna bez aliasu) - zdanie „brak” (tu po angielsku). Między zdaniem
    a klikiem stos dostał obiekt inną drogą: gest pomija go i to mówi, bez zapisu i bez „Cofnij”.
    Podsumowanie okna żniw z katalogu w bieżącym języku - cały raport EN, bez polskiego członu."""
    import re
    _zniwa_ze_stosami(monkeypatch, [("stos-ic", [7], "NGC7000")],
                      podsumowanie=lambda: i18n.t_plural("harvest.close_placed", 1))
    win = MainWindow(_baza_ze_stosem(tmp_path, raw_stosu="Mglawica Zdzicha"), now_fn=_Zegar())
    try:
        i18n.set_lang("en")
        win.show()
        assert _obiekt_stosu(win) == (None, None)
        _zniwa_i_przebieg(win)
        assert win._pelny_komunikat == ("1 stack has no object, the release says NGC7000 - Took 1 file "
                                        "into the archive - lineage: 1 stack from harvest history")
        assert not re.search(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]|Wciągnięto|stos\b|wydanie", win._pelny_komunikat)
        assert win.recipe_label.text() == "Assign release object"
        repo.user_assign_object(win.con, alias_norm=None, canon="IC1795", catalog="IC", kind="deep_sky",
                                frame_ids=[1], now=ZNACZNIK_BIEGU)
        przed = _zdarzenia(win)
        _klik_recepty(win)
        assert _obiekt_stosu(win) == ("IC1795", "user") and _zdarzenia(win) == przed
        assert win._pelny_komunikat == "1 stack skipped - its object changed since the harvest, nothing saved"
        assert not win.recipe_label.isVisible()
    finally:
        i18n.set_lang("pl")
        win.close()


def test_gest_wydania_przezywa_wczytanie_i_recepte_gridu_w_Zbiorach(qapp, tmp_path, ustawienia, monkeypatch):
    """User przeszedł do Zbiorów, zanim przebieg Dostawy się skończył: gest pada w Zbiorach, a spóźnione
    przeładowanie gridu (raport wczytania + recepta gridu, w produkcji z wątku tła) NIE zdejmuje ani
    „Przypisz obiekt wydania”, ani zdania; po kliku to samo dla „Cofnij” - i „Cofnij” dalej działa.

    Falsyfikator: zdejmij `_gest_wydania_aktywny` z `_raport_wczytania_gridu`/`_recepta_gridu` → po
    `grid.refresh()` przycisk recepty niesie receptę gridu albo znika."""
    from horreum.gui.app import NAV_ZBIORY
    i18n.set_lang("pl")
    _zniwa_ze_stosami(monkeypatch, [("stos-ic", [7], "NGC7000")])
    win = MainWindow(_baza_ze_stosem(tmp_path), now_fn=_Zegar())
    try:
        win.show()
        win.pipeline_view.btn_harvest.click()
        win._show_view(NAV_ZBIORY)
        win.pipeline_view.run_finished.emit(_zapis_przebiegu())
        zdanie = win._pelny_komunikat
        assert zdanie.startswith("1 stos ma inny obiekt niż wydanie")
        win.grid_view.refresh()
        assert win.recipe_label.isVisible() and win.recipe_label.text() == "Przypisz obiekt wydania"
        assert win._pelny_komunikat == zdanie

        _klik_recepty(win)
        assert _obiekt_stosu(win) == ("NGC7000", "user")
        win.grid_view.refresh()
        assert win.recipe_label.isVisible() and win.recipe_label.text() == "Cofnij"
        assert win._pelny_komunikat == "Obiekt wydania przypisany ręką: 1 stos (NGC7000)"
        _klik_recepty(win)
        assert _obiekt_stosu(win) == ("IC1795", "header")
    finally:
        win.close()


def test_gest_wydania_z_Dostawy_gasnie_z_raportem_przy_wejsciu_w_Zbiory(qapp, tmp_path, ustawienia,
                                                                        monkeypatch):
    """Gest padł w Dostawie (raport związany z nią). Wejście w Zbiory gasi raport - i gest razem z nim:
    przycisk „Przypisz obiekt wydania” nie stoi nad Zbiorami bez swojego zdania, a recepta Zbiorów
    może wejść na jego miejsce.

    Falsyfikator: zdejmij gaszenie gestu wydania w `_on_nav_changed` → po wejściu w Zbiory przycisk
    niesie „Przypisz obiekt wydania” przy pustym raporcie."""
    from horreum.gui.app import NAV_ZBIORY
    i18n.set_lang("pl")
    _zniwa_ze_stosami(monkeypatch, [("stos-ic", [7], "NGC7000")])
    win = MainWindow(_baza_ze_stosem(tmp_path), now_fn=_Zegar())
    try:
        win.show()
        _zniwa_i_przebieg(win)
        zdanie = win._pelny_komunikat
        assert zdanie.startswith("1 stos ma inny obiekt niż wydanie")
        assert win.recipe_label.isVisible() and win.recipe_label.text() == "Przypisz obiekt wydania"
        win._show_view(NAV_ZBIORY)
        assert win._pelny_komunikat != zdanie               # na pasku raport Zbiorów, nie zdanie gestu
        assert not win._gest_wydania_aktywny()
        assert win.recipe_label.text() != "Przypisz obiekt wydania"
    finally:
        win.close()


def test_odmowa_kafla_przy_zapisie_naglowkow_gasnie_z_koncem_zapisu(qapp, tmp_path):
    """Zapis nagłówków nie kończy się przebiegiem Dostawy - odmowa kafla „zapis trwa” w treści strony
    gaśnie z końcem zapisu, nie czeka na następny przebieg. Odmowa w biegu zostaje, dopóki bieg trwa."""
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        przyjmij = win.przyjmij_view
        przyjmij.set_writeback_busy(True)
        przyjmij.pokaz_odmowe("zapis nagłówków w toku")
        assert not przyjmij.lbl_odmowa.isHidden()
        przyjmij.set_writeback_busy(False)
        assert przyjmij.lbl_odmowa.isHidden()

        przyjmij.set_busy(True)
        przyjmij.pokaz_odmowe("Dostawa w biegu")
        przyjmij.set_writeback_busy(False)
        assert not przyjmij.lbl_odmowa.isHidden(), "bieg trwa - odmowa zgasła za wcześnie"
        przyjmij.set_busy(False)
        assert przyjmij.lbl_odmowa.isHidden()
    finally:
        win.close()


def test_kanon_wydania_spoza_bazy_mowi_zdaniem_bez_gestu(qapp, tmp_path, ustawienia, monkeypatch):
    """Wydanie, którego obiektu ta baza nie zna (karta wydania z innej bazy): porównania nie ma i ekran
    to MÓWI - zdanie bez przycisku gestu, baza nietknięta (wcześniej: cisza, jakby było zgodnie)."""
    i18n.set_lang("pl")
    _zniwa_ze_stosami(monkeypatch, [("stos-ic", [7], "NGC9999")])
    win = MainWindow(_baza_ze_stosem(tmp_path), now_fn=_Zegar())
    try:
        win.show()
        przed = _zdarzenia(win)
        _zniwa_i_przebieg(win)
        assert win._pelny_komunikat == ("1 stos bez porównania - obiektu wydania NGC9999 nie ma w tej bazie - "
                                        "Wciągnięto stosy - rodowód: 1 stos z historii żniw")
        assert not win.recipe_label.isVisible()
        assert _obiekt_stosu(win) == ("IC1795", "header") and _zdarzenia(win) == przed
    finally:
        win.close()


def test_cofniecie_mowi_do_czego_wrocil_kazdy_stos(qapp, tmp_path, ustawienia, monkeypatch):
    """Zestaw mieszany: stos z obiektem z nagłówka, stos bez obiektu i stos z nagrobkiem ręki. Gest
    przypisuje wszystkim trzem; „Cofnij” mówi osobno: poprzedni obiekt / znów bez obiektu / znów bez
    obiektu z decyzji ręki - a stan każdego wraca dokładnie do `before`."""
    i18n.set_lang("pl")
    _zniwa_ze_stosami(monkeypatch, [("stos-ic", [7], "NGC7000"), ("stos-pusty", [8], "NGC7000"),
                                    ("stos-nagrobek", [9], "NGC7000")])
    win = MainWindow(_baza_ze_stosem(tmp_path, dalsze=[(2, "stos-pusty", None), (3, "stos-nagrobek", None)]),
                     now_fn=_Zegar())
    try:
        win.show()
        repo.user_assign_object(win.con, alias_norm=None, canon="M31", catalog="M", kind="deep_sky",
                                frame_ids=[3], now=ZNACZNIK_BIEGU)
        repo.clear_object_assignment(win.con, frame_ids=[3], now=ZNACZNIK_BIEGU)
        stan = lambda: [tuple(r) for r in win.con.execute(                          # noqa: E731
            "SELECT o.canon, f.object_source, c.canon FROM frame f LEFT JOIN object o ON o.id = f.object_id "
            "LEFT JOIN object c ON c.id = f.object_cleared_id ORDER BY f.id")]
        przed = stan()
        assert przed == [("IC1795", "header", None), (None, None, None), (None, "user_cleared", "M31")]
        _zniwa_i_przebieg(win)
        assert win._pelny_komunikat.startswith(
            "1 stos ma inny obiekt niż wydanie (stos: IC1795, wydanie: NGC7000); "
            "2 stosy bez obiektu, a wydanie mówi NGC7000 - ")
        _klik_recepty(win)
        assert win._pelny_komunikat == "Obiekt wydania przypisany ręką: 3 stosy (NGC7000)"
        assert {s[:2] for s in stan()} == {("NGC7000", "user")}
        _klik_recepty(win)
        assert win._pelny_komunikat == ("Cofnięto: 1 stos wrócił do poprzedniego obiektu, 1 stos znów bez "
                                        "obiektu, 1 stos znów bez obiektu z decyzji ręki")
        assert stan() == przed
    finally:
        win.close()


# ---------------------------------------------------------------- AR-198: awaria etapu ze szczegółem

@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_przyjecia_klasa_w_jezyku_UI_szczegol_w_podpowiedzi(strona, tmp_path, monkeypatch, lang):
    """Przyjmij nowe (przebieg „all” w prawdziwym wątku) pada zerwanym udziałem: wiersz błędu strony
    to ten sam wiersz co pod przyciskami Dostawy, klasą w języku UI, a surowy komunikat systemu
    w szczególe podpowiedzi; zapis odmowy zdejmuje go z pola. Falsyfikator: `_render` z `setText`
    bez szczegółu albo pole jako zwykły `QLabel`."""
    from horreum.gui import pipeline as pipeline_mod

    def _pada(*_a, **_k):
        raise OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64)
    i18n.set_lang(lang)
    try:
        monkeypatch.setattr(pipeline_mod, "scan_tree", _pada)
        tree = _drzewo(tmp_path, "d_blad", [(1, PLAMA)])
        zapis = _przebieg(strona.pipeline_view, lambda: strona.pipeline_view.run_all_on(tree))
        klasa = i18n.t("objchg.item.os_share_lost", os_code="WinError 64")
        szczegol = i18n.t("wb.os_detail_tip", detail=r"OSError: [WinError 64] Komunikat systemu: 'X:\L\a.fits'")
        assert klasa in zapis["failed"] and zapis["failed_tip"] == szczegol
        zdanie = i18n.t("intake.failed", line=zapis["failed"])
        assert strona.lbl_error.text() == zdanie and not strona.lbl_error.isHidden()
        assert strona.lbl_error.toolTip() == zdanie + "\n" + szczegol
        if lang == "en":
            assert not set(zdanie) & set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"), zdanie
        strona.pipeline_view.run_finished.emit(_zapis_przebiegu(refused="źródło niedostępne"))
        assert strona.lbl_error.isHidden() and strona.lbl_error.szczegol() == ""
        assert strona.lbl_error.text() == ""
        # Ta sama awaria, potem bieg bez awarii - pole gaśnie razem ze szczegółem.
        strona.pipeline_view.run_finished.emit(_zapis_przebiegu(failed=zapis["failed"],
                                                                failed_tip=szczegol))
        assert strona.lbl_error.szczegol() == szczegol
        strona.pipeline_view.run_finished.emit(_zapis_przebiegu())
        assert strona.lbl_error.isHidden() and strona.lbl_error.szczegol() == ""
    finally:
        i18n.set_lang("pl")


# --- AR-241: zdanie po przebiegu żniw niesie podsumowanie okna jako nośnik, nie `str(...)` ---

from horreum.gui.wb_worker import ZdanieZeSzczegolem, szczegol_zdania, wiersz_systemu  # noqa: E402
from horreum.item_reasons import blad_systemu  # noqa: E402


@pytest.mark.parametrize("przebieg", ["failed", "cancelled", "refused", "ok"])
def test_rodowod_ze_zniw_zdanie_po_przebiegu_niesie_szczegoly_podsumowania(qapp, tmp_path, ustawienia,
                                                                         monkeypatch, przebieg):
    """Podsumowanie okna żniw z niezapisanym zeznaniem i szczegółem systemu (nośnik
    `ZdanieZeSzczegolem`, jak zostawia je prawdziwe okno) jedzie do zdania po przebiegu Dostawy
    w każdej gałęzi: przerwany, odmówiony, z błędem i udany. Zdanie = instrukcja ratunku, przyczyna,
    podsumowanie (udany: podsumowanie i rodowód); szczegół - wiersz awarii etapu PRZED wierszem
    zeznania, każdy osobno. Falsyfikatory: `str(dlg.summary)` przy przekazaniu do
    `_zapisz_rodowod_po_przebiegu`; `str(podsumowanie)` w złożeniu zdania; wiersz awarii bez
    `failed_tip`; zamieniona kolejność przyczyny i podsumowania."""
    i18n.set_lang("pl")
    zeznanie = blad_systemu(OSError(None, "Komunikat systemu", r"X:\L\a.fits", 64))
    zdanie_zniw = (i18n.t_plural("harvest.status_placed", 1, root=r"X:\ARCH")
                   + " · " + i18n.t("harvest.manifest_error", err=i18n.t("objchg.item.os_share_lost",
                                                                         os_code="WinError 64")))
    szczegol_zniw = wiersz_systemu(zeznanie)
    assert szczegol_zniw
    _zniwa_ze_stosami(monkeypatch, [("a", [1])],
                      podsumowanie=lambda: ZdanieZeSzczegolem(zdanie_zniw, szczegol_zniw))
    wiersz = i18n.t("pipeline.stage_failed_line", stage="Grupowanie",
                    msg=i18n.t("objchg.item.os_denied", os_code="WinError 5"))
    tip_awarii = wiersz_systemu(blad_systemu(OSError(None, "Odmowa dostępu.", r"X:\L\b.fits", 5)))
    pola = {"failed": {"failed": wiersz, "failed_tip": tip_awarii}, "cancelled": {"cancelled": "scan"},
            "refused": {"refused": "źródło niedostępne"}, "ok": {}}[przebieg]
    win = MainWindow(_baza(tmp_path), now_fn=_Zegar())
    try:
        _szpieg_odswiezen(win)
        win.pipeline_view.btn_harvest.click()
        win.pipeline_view.run_finished.emit(_zapis_przebiegu(**pola))
        utrata = i18n.t("status.harvest_lineage_lost", n=1)
        czlony = {"failed": [utrata, wiersz, zdanie_zniw], "cancelled": [utrata, zdanie_zniw],
                  "refused": [utrata, "źródło niedostępne", zdanie_zniw],
                  "ok": [zdanie_zniw, i18n.t_plural("status.harvest_lineage", 1)]}[przebieg]
        szczegoly = [tip_awarii, szczegol_zniw] if przebieg == "failed" else [szczegol_zniw]
        assert win._pelny_komunikat == " - ".join(czlony)
        assert szczegol_zdania(win._pelny_komunikat).split("\n") == szczegoly
        assert win.report_label.szczegol() == "\n".join(szczegoly)
        assert win.statusBar().toolTip() == " - ".join(czlony) + "\n" + "\n".join(szczegoly)
    finally:
        win.close()
