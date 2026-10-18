"""Okno „Zmień obiekt…”/„Uzgodnij pliki…” i jego wejścia (AR-17 krok 3, D-1011-5) oraz karta w miejscu
okien kart (AR-117).

Rdzeń gestu (planer, read-model, staging, sterownik i cofnięcie) ma własne testy w torach planera
i zapisu. Tu pinujemy POWIERZCHNIĘ: okno pokazuje dokładnie plan (lista, liczby, pominięcia,
ostrzeżenia), wykonanie to JEDNA operacja uchwytu po stagingu tego samego planu, „Cofnij” idzie
`undo_object_change` po `run_id`, przerwanie daje „Dokończ” bez drugiego stagingu, zamknięcie w biegu
jest żądaniem anulowania, a plan liczy się poza wątkiem okna. Rdzeń podmieniamy w module, który go
CZYTA (`queries`, `object_change`, `repo`, `writeback` - okno i uchwyt wołają je przez moduł).

Qt offscreen; okno z `off_thread=False` liczy plan i pisze inline (ten sam rdzeń, bez QThread)."""
import dataclasses
import os
import time

# Platforma PRZED importem Qt (AR-170): plik puszczony sam biegł natywnie - geometria okien zależała
# od maszyny (styl, ekran, DPR), w baterii platformę stawiał moduł zebrany wcześniej.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from horreum import db, object_change as oc, repo, resolver, writeback
from horreum.gui import i18n, queries
from horreum.gui import grid as grid_mod
from horreum.gui.i18n_catalog import CATALOG

NOW = "2026-10-11T12:00:00+00:00"
KORZEN = r"R:\ASTRO_"
STARY = KORZEN + r"\LIGHTS\NGC3034\RC6_2600MC\OSC"
NOWY = KORZEN + r"\LIGHTS\NGC2632\RC6_2600MC\OSC"
CEL = oc.ObjectTarget(canon="NGC2632", catalog="NGC", kind="deep_sky", alias_norm=None,
                      card_form="NGC 2632")


@pytest.fixture
def qapp():
    yield QApplication.instance() or QApplication([])


# Wynik sterownika atrap - PRAWDZIWY typ rdzenia, nie kopia jego pól: zmiana kontraktu po tamtej
# stronie ma przewrócić te testy, a nie przejść obok nich.
_Wynik = writeback.ObjectChangeResult


def _fr(lid, status, reason=None, code=None):
    return writeback.FileResult(lid, rf"{NOWY}\f{lid}.fits", status, reason, code=code)


def _pozycja(fid, *, nowa=True, karta=True, katalogi=True, stara_karta="NGC 3034"):
    return oc.ObjectChangeItem(
        frame_id=fid, location_id=10 + fid, old_path=rf"{STARY}\f{fid}.fits",
        new_path=rf"{NOWY}\f{fid}.fits" if nowa else None,
        mkdirs=(KORZEN + r"\LIGHTS\NGC2632", KORZEN + r"\LIGHTS\NGC2632\RC6_2600MC", NOWY)
        if katalogi and nowa else (),
        card_op="set" if karta else None, card_old=stara_karta,
        card_new="NGC 2632" if karta else None, expected_header_hash=f"h{fid}" if karta else None,
        expected_mtime=f"m{fid}", expected_object=(7, "header", None), object_change=True)


def _plan(run_id="run-1", *, items=None, skipped=None, warnings=(), target=CEL):
    if items is None:
        items = (_pozycja(1), _pozycja(2), _pozycja(3, nowa=False, karta=False, stara_karta=None))
    if skipped is None:
        skipped = (oc.ObjectChangeSkip(4, rf"{STARY}\dark4.fits", "kalibracja nie ma obiektu"),
                   oc.ObjectChangeSkip(5, rf"{STARY}\dark5.fits", "kalibracja nie ma obiektu"),
                   oc.ObjectChangeSkip(6, rf"{STARY}\f6.fits", "dwie obecne kopie"))
    return oc.ObjectChangePlan(run_id=run_id, target=target, items=items, skipped=skipped,
                               warnings=warnings)


class _Rdzen:
    """Rejestr wywołań atrap rdzenia + to, co mają zwrócić."""

    def __init__(self):
        self.plany = []          # kolejne plany; pusta lista = `_plan(run-N)`
        self.n_planow = 0
        self.wiersze = []        # (frame_ids, target) każdego czytania read-modelu
        self.staging = []        # plany oddane do `repo.stage_object_change`
        self.commity = []        # run_id każdego startu sterownika
        self.cofniecia = []      # run_id każdego cofnięcia
        self.wynik_commitu = None
        self.wynik_cofniecia = None
        self.opoznienie = 0.0


@pytest.fixture
def rdzen(monkeypatch):
    r = _Rdzen()

    def wiersze(con, frame_ids, *, target=None):
        r.wiersze.append((list(frame_ids), target))
        return []

    def planuj(rows, *, target, library_root, location_at, run_id=None):
        assert library_root == KORZEN and callable(location_at)
        time.sleep(r.opoznienie)
        r.n_planow += 1
        if r.plany:
            return r.plany.pop(0)
        return _plan(f"run-{r.n_planow}", target=target)

    def stage(con, *, plan, now):
        r.staging.append(plan)

    def commit(con, run_id, *, now, progress=None, should_cancel=None):
        r.commity.append(run_id)
        if progress is not None:
            progress(1, 3, rf"{NOWY}\f1.fits", "applied")
        return r.wynik_commitu or _Wynik(run_id, applied=[_fr(11, "applied"), _fr(12, "applied")],
                                         blocked=[], failed=[], skipped=[], commit_ids=(5,),
                                         dirs_created=3)

    def undo(con, run_id, *, now, progress=None, should_cancel=None):
        r.cofniecia.append(run_id)
        return r.wynik_cofniecia or _Wynik(run_id, applied=[_fr(11, "restored"), _fr(12, "restored")],
                                           blocked=[], failed=[], skipped=[], dirs_removed=3)

    monkeypatch.setattr(queries, "object_change_rows", wiersze)
    # Staging atrapy nie pisze do bazy, więc stan przebiegu po wyjątku workera też jest atrapą:
    # przebieg `staged` (sterownik domyka go wyłącznie na końcu listy), nic nie czeka.
    monkeypatch.setattr(queries, "object_change_run_view",
                        lambda con, run_id: {"pending": 0, "can_finish": True})
    monkeypatch.setattr(resolver, "library_root_from_db", lambda con: KORZEN)
    monkeypatch.setattr(oc, "plan_object_change", planuj)
    monkeypatch.setattr(repo, "stage_object_change", stage)
    monkeypatch.setattr(writeback, "commit_object_change", commit)
    monkeypatch.setattr(writeback, "undo_object_change", undo)
    return r


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "oc.db"))
    yield c
    c.close()


def _okno(qapp, con, target=CEL, *, off_thread=False, frame_ids=(1, 2, 3, 4, 5, 6),
          now_fn=lambda: NOW):
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    return ObjectChangeDialog(con, frame_ids=list(frame_ids), target=target, now_fn=now_fn,
                              off_thread=off_thread)


def _teksty(tree):
    """Teksty WIDOCZNYCH kolumn - kolumna statusu jest w podglądzie schowana."""
    kolumny = [c for c in range(tree.columnCount()) if not tree.isColumnHidden(c)]
    return [[tree.topLevelItem(i).text(c) for c in kolumny]
            for i in range(tree.topLevelItemCount())]


# ═══════════════════════════════════════════════ okno: podgląd = plan


def test_okno_pokazuje_DOKLADNIE_plan_lista_liczby_pominiecia_ostrzezenia(qapp, con, rdzen):
    """Lista „plik dziś → po zmianie · karta stara → nowa” pod korzeniem archiwum, liczby z planu
    (katalog liczony raz na ścieżkę), pominięcia pogrupowane po powodzie (najliczniejszy na górze,
    pliki pod spodem), ostrzeżenie rdzenia widoczne, przycisk z liczbą pozycji do zrobienia."""
    rdzen.plany = [_plan(warnings=(oc.ObjectChangeWarning((1,), "stos M44_stack: 1 z 2 wejść"),))]
    dlg = _okno(qapp, con)
    assert rdzen.wiersze == [([1, 2, 3, 4, 5, 6], CEL)]     # read-model dostał cel (forma karty)
    wiersze = _teksty(dlg.items_tree)
    assert wiersze[0] == [r"LIGHTS\NGC3034\RC6_2600MC\OSC\f1.fits",
                          r"LIGHTS\NGC2632\RC6_2600MC\OSC\f1.fits", "'NGC 3034' → 'NGC 2632'"]
    assert wiersze[2] == [r"LIGHTS\NGC3034\RC6_2600MC\OSC\f3.fits", i18n.t("objchg.no_move"),
                          i18n.t("objchg.card_none")]
    # pełna ścieżka w podpowiedzi, katalogi do założenia też
    assert dlg.items_tree.topLevelItem(0).toolTip(0) == rf"{STARY}\f1.fits"
    assert NOWY in dlg.items_tree.topLevelItem(0).toolTip(1)
    assert dlg.counts.text() == i18n.t("objchg.counts", robota=3, folder=2, nazwa=0, karty=2,
                                       katalogi=3, usunie=0, obiekt=3, bez_zmian=0, pominie=3)
    grupy = _teksty(dlg.skipped_tree)
    assert grupy == [["kalibracja nie ma obiektu", "2"], ["dwie obecne kopie", "1"]]
    assert dlg.skipped_tree.topLevelItem(0).childCount() == 2
    assert not dlg.warnings.isHidden() and "M44_stack" in dlg.warnings.text()
    assert dlg.action_btn.text() == i18n.t("objchg.action_change", n=3)
    assert dlg.action_btn.isEnabled() and dlg.undo_btn.isHidden()
    dlg.reject()


def test_uzgodnij_ma_wlasne_zdania_i_przycisk(qapp, con, rdzen):
    dlg = _okno(qapp, con, target=None)
    assert rdzen.wiersze[0][1] is None
    assert dlg.windowTitle() == i18n.t("objchg.title_align")
    assert dlg.head.text() == i18n.t_plural("objchg.head_align", 6)
    assert dlg.action_btn.text() == i18n.t("objchg.action_align", n=3)
    dlg.reject()


def test_cel_bez_formy_karty_NIE_otwiera_okna(qapp, con, rdzen):
    """EXPECT: odmowę mówi wołający przed planem (`grid._on_object_change`); okno z takim celem to
    błąd kolejności, a nie plan, który obiecywałby kartę bez formy."""
    with pytest.raises(AssertionError):
        _okno(qapp, con, target=dataclasses.replace(CEL, card_form=None))
    assert rdzen.n_planow == 0


def test_lista_pominiec_HUGGUJE_wiersze_i_rosnie_po_rozwinieciu(qapp, con, rdzen):
    """Jeden powód to jeden wiersz, nie domyślne ~190 px drzewa, które zabierało liście pozycji
    pion; rozwinięty powód pokazuje swoje pliki (wysokość rośnie, sufit zostaje). Bez twardych
    pikseli: porównania względne i sufit."""
    from horreum.gui.object_change_dialog import _POMINIECIA_MAX_PX
    dlg = _okno(qapp, con)
    dlg.show()
    QCoreApplication.processEvents()
    zwiniete = dlg.skipped_tree.height()
    assert zwiniete < dlg.items_tree.height()
    dlg.skipped_tree.topLevelItem(0).setExpanded(True)    # dwa pliki pod najliczniejszym powodem
    QCoreApplication.processEvents()
    assert zwiniete < dlg.skipped_tree.height() <= _POMINIECIA_MAX_PX
    dlg.reject()


def test_liczby_ROZDZIELAJA_folder_od_nowej_nazwy_a_dopisanie_karty_FITS_jest_oznaczone(
        qapp, con, rdzen):
    """Przeniesienie do innego folderu i nowa nazwa w TYM SAMYM folderze to dwie liczby (folder
    porównany fizycznie - bez wielkości liter, jak `R:`). Dopisanie karty do FITS jest w podglądzie
    oznaczone prawdą o wszystkich wynikach (AR-118): w miejscu, gdy plik na to pozwala (zapas
    nagłówka), inaczej cały plik przepisany albo odmowa z powodem przy pozycji - zapas nie jest
    jedynym warunkiem (skompresowany HDU idzie atomowo, `CHECKSUM`/`DATASUM` odmawia). XISF
    dopisuje w miejscu, więc bez oznaczenia.

    Układ (AR-118, pomiar natywny): w KOMÓRCE krótki znacznik, pełne zdanie w jej podpowiedzi i RAZ
    pod listą - pełne zdanie w każdym wierszu FITS zabierało kolumnie ścieżek szerokość."""
    nazwa = dataclasses.replace(_pozycja(1), new_path=STARY.lower() + r"\nowa1.fits", mkdirs=())
    fits_add = dataclasses.replace(_pozycja(2), card_op="add", card_old=None)
    xisf_add = dataclasses.replace(_pozycja(3), old_path=rf"{STARY}\f3.xisf",
                                   new_path=rf"{NOWY}\f3.xisf", card_op="add", card_old=None)
    # Katalog źródłowy pusty po planie - dwa razy w różnej pisowni to ten sam katalog na `R:`.
    rdzen.plany = [dataclasses.replace(_plan(items=(nazwa, fits_add, xisf_add), skipped=()),
                                       rmdirs=(STARY, STARY.upper()))]
    dlg = _okno(qapp, con)
    assert dlg.counts.text() == i18n.t("objchg.counts", robota=3, folder=2, nazwa=1, karty=3,
                                       katalogi=3, usunie=1, obiekt=3, bez_zmian=0, pominie=0)
    assert STARY in dlg.counts.toolTip()
    wiersze = [dlg.items_tree.topLevelItem(i) for i in range(3)]
    znacznik, zdanie = i18n.t("objchg.card_add_fits_short"), i18n.t("objchg.card_add_fits")
    assert [w.text(2).endswith(znacznik) for w in wiersze] == [False, True, False]
    assert not any(zdanie in w.text(2) for w in wiersze)              # komórka bez pełnego zdania
    assert [zdanie in w.toolTip(2) for w in wiersze] == [False, True, False]
    assert wiersze[1].text(2) in wiersze[1].toolTip(2)
    assert dlg.card_note.text() == zdanie and not dlg.card_note.isHidden()
    dlg.reject()


def test_kolumna_karty_NIE_ZJADA_sciezek_sufit_wzgledny_do_okna(qapp, con, rdzen):
    """AR-118 (pomiar natywny): kolumna karty była `ResizeToContents` i z pełnym zdaniem dopisania
    zabierała 869 z 1100 px - ścieżki spadały do ~100 px, status po zapisie do ~70 px. Teraz kolumna
    jest `Interactive` z szerokością z treści i sufitem względnym do okna - bez pikseli platformy:
    karta dłuższa niż sufit staje na suficie, ścieżki zostają `Stretch`. Plan bez dopisania do FITS
    nie pokazuje zdania pod listą.

    Falsyfikator: `ResizeToContents` z powrotem albo bez sufitu → asercje trybu i szerokości."""
    from PySide6.QtWidgets import QHeaderView
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    dluga = dataclasses.replace(_pozycja(1), card_op="add", card_old=None, card_new="N" * 68)
    rdzen.plany = [_plan(items=(dluga, _pozycja(2)), skipped=()), _plan(items=(_pozycja(3),),
                                                                       skipped=())]
    dlg = _okno(qapp, con)
    hdr = dlg.items_tree.header()
    assert hdr.sectionResizeMode(2) == QHeaderView.Interactive
    assert [hdr.sectionResizeMode(c) for c in (0, 1)] == [QHeaderView.Stretch] * 2
    sufit = int(dlg.width() * ObjectChangeDialog._KARTA_MAX_UDZIAL)
    assert dlg.items_tree.columnWidth(2) == sufit                     # długa karta: na suficie
    assert not dlg.card_note.isHidden()
    dlg._licz_plan()                                                  # plan bez dopisania do FITS
    assert 0 < dlg.items_tree.columnWidth(2) < sufit and dlg.card_note.isHidden()
    dlg.reject()
    pl, en = CATALOG["objchg.card_add_fits"]["pl"], CATALOG["objchg.card_add_fits"]["en"]
    assert all(s in pl for s in ("w miejscu", "zapas w nagłówku", "cały plik przepisany", "odmowa"))
    assert all(s in en for s in ("in place", "room in the header", "rewritten", "refused"))
    assert not set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ") & set(en)


def test_zdanie_wyniku_liczy_spadek_UWAGI_i_numer_przebiegu():
    """Pozycje `applied` z powodem: przy zapisie spadek karty na drogę atomową (KOD rdzenia
    `CODE_INPLACE_FALLBACK`) i uwagi osobno - powód o tym samym brzmieniu bez kodu jest uwagą; przy
    cofnięciu każdy powód to uwaga. Numer przebiegu zawsze - po zamknięciu okna uchwyt CLI
    (`horreum object-change finish|undo`) i wiersz Porządków."""
    from horreum.gui.object_change_dialog import zdanie_wyniku_zmiany
    prefiks = writeback.PREFIKS_DROGI_ATOMOWEJ
    res = _Wynik("przebieg-7", applied=[
        _fr(1, "applied"), _fr(2, "applied", f"{prefiks}: operacja add/str na OBJECT",
                               code=writeback.CODE_INPLACE_FALLBACK),
        _fr(3, "applied", "zapis potwierdzony z dysku")], blocked=[], failed=[], skipped=[])
    z = zdanie_wyniku_zmiany(res)
    # Spadek mówi zdaniem człowieka, bez żargonu rdzenia (szczegół niesie podpowiedź wiersza).
    assert i18n.t("wb.inplace_fallback", n=1) in z
    assert "operacja add/str" not in z and prefiks not in z
    assert i18n.t("objchg.res.notes", n=1, note="zapis potwierdzony z dysku") in z
    bez_kodu = zdanie_wyniku_zmiany(_Wynik("p", applied=[_fr(2, "applied", f"{prefiks}: x")],
                                           blocked=[], failed=[], skipped=[]))
    assert i18n.t("wb.inplace_fallback", n=1) not in bez_kodu and i18n.t(
        "objchg.res.notes", n=1, note=f"{prefiks}: x") in bez_kodu
    assert i18n.t("objchg.res.run", run_id="przebieg-7") in z
    cof = zdanie_wyniku_zmiany(_Wynik("przebieg-7", applied=[
        _fr(1, "restored", "baza: nowsza decyzja")], blocked=[], failed=[], skipped=[]),
        cofniecie=True)
    assert i18n.t("objchg.res.notes", n=1, note="baza: nowsza decyzja") in cof
    assert i18n.t("wb.inplace_fallback", n=1) not in cof


def test_blokada_pliku_zmienionego_od_skanu_MA_recepte(tmp_path):
    """Odmowę pliku zmienionego od skanu bierzemy od PRAWDZIWEGO pisarza w miejscu (kotwica sha1
    niezgodna) - okno rozpoznaje ją po KODZIE (`CODE_CHANGED_SINCE_SCAN`) i podaje drogę: skan
    w Dostawie, potem gest. Samo zdanie bez kodu recepty nie dostaje."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    from horreum.gui.object_change_dialog import zdanie_wyniku_zmiany
    p = tmp_path / "x.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["OBJECT"] = "NGC 3034"
    hdu.writeto(str(p))
    wynik = writeback.write_changes_inplace(
        str(p), [writeback.WriteOp("OBJECT", "set", "NGC 2632", "str", idx=0)],
        scan.scan_file(str(p)).header_hash, anchor=writeback.FileAnchor("0" * 40, "2000-01-01"))
    assert (wynik.status, wynik.code) == ("blocked", writeback.CODE_CHANGED_SINCE_SCAN)
    res = _Wynik("R", applied=[], failed=[], skipped=[],
                 blocked=[_fr(1, "blocked", f"karta odbita bez zapisu: {wynik.reason}",
                              code=wynik.code)])
    assert i18n.t_plural("objchg.res.rescan", 1) in zdanie_wyniku_zmiany(res)
    bez_kodu = _Wynik("R", applied=[], failed=[], skipped=[],
                      blocked=[_fr(1, "blocked", f"karta odbita bez zapisu: {wynik.reason}")])
    assert i18n.t_plural("objchg.res.rescan", 1) not in zdanie_wyniku_zmiany(bez_kodu)


def test_Cofnij_tylko_gdy_cos_ruszono_katalogi_netto():
    from horreum.gui.object_change_dialog import ruszyl_cokolwiek
    puste = dict(applied=[], blocked=[], failed=[], skipped=[])
    assert not ruszyl_cokolwiek(_Wynik("R", dirs_created=2, dirs_removed=2, **puste))
    assert ruszyl_cokolwiek(_Wynik("R", dirs_created=3, dirs_removed=2, **puste))


def test_po_etapie_Dostawy_plan_liczy_sie_od_nowa_ale_nie_przy_przebiegu(qapp, con, rdzen):
    dlg = _okno(qapp, con)
    dlg.set_pipeline_busy(True)
    assert not dlg.action_btn.isEnabled() and rdzen.n_planow == 1
    dlg.set_pipeline_busy(False)
    assert rdzen.n_planow == 2 and dlg.action_btn.isEnabled()
    dlg.action_btn.click()                                # przebieg w oknie - plan zostaje
    dlg.set_pipeline_busy(True)
    dlg.set_pipeline_busy(False)
    assert rdzen.n_planow == 2
    dlg.reject()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_blad_bazy_przy_stagingu_ZOSTAWIA_okno_z_powodem(qapp, con, rdzen, monkeypatch, lang):
    """Baza zajęta przez drugi zapis (blokada trzymana drugim połączeniem do tego samego pliku):
    PRAWDZIWY `repo.stage_object_change` pada na `BEGIN IMMEDIATE`, okno mówi klasą błędu bazy
    w języku UI (`item_reasons.blad_systemu`), surowy tekst SQLite stoi pod kursorem, akcja zostaje
    do ponowienia, zero commitu. Falsyfikator: `_on_action` sklejający `Typ: opis` w zdaniu."""
    import sqlite3
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from horreum.gui.wb_worker import tekst_powodu, wiersz_systemu
    from horreum.item_reasons import blad_systemu
    bledy = []

    def staging_prawdziwy(con_, *, plan, now):
        try:
            return _STAGING_PRAWDZIWY(con_, plan=plan, now=now)
        except sqlite3.Error as exc:
            bledy.append(exc)
            raise
    monkeypatch.setattr(repo, "stage_object_change", staging_prawdziwy)
    con.execute("PRAGMA busy_timeout = 0")               # sam timeout połączenia - test bez 5 s czekania
    blokada = sqlite3.connect(queries.db_path_of(con), isolation_level=None)
    blokada.execute("BEGIN IMMEDIATE")
    try:
        i18n.set_lang(lang)
        dlg = _okno(qapp, con)
        dlg.show()
        QTest.mouseClick(dlg.action_btn, Qt.LeftButton)
        (exc,) = bledy
        assert exc.sqlite_errorname == "SQLITE_BUSY", exc
        powod = blad_systemu(exc)
        assert getattr(powod, "code", None) == "db_busy", powod
        zdanie = dlg.error.text()
        assert zdanie == i18n.t("objchg.err.stage", msg=tekst_powodu(powod)), zdanie
        # Surowy tekst SQLite (`detail` klasy, „OperationalError: database is locked”) nie wchodzi do
        # zdania - stoi w podpowiedzi; zdanie klasy samo może mówić „the database is locked”.
        surowy = dict(powod.params)["detail"]
        assert surowy not in zdanie and "OperationalError" not in zdanie and wiersz_systemu(powod), zdanie
        assert dlg.error.toolTip() == zdanie + "\n" + wiersz_systemu(powod), dlg.error.toolTip()
        if lang == "en":
            assert not set(zdanie) & set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"), zdanie
        assert rdzen.commity == [] and dlg.action_btn.isEnabled()
        dlg.reject()
    finally:
        blokada.execute("ROLLBACK")
        blokada.close()
        i18n.set_lang("pl")


def test_Enter_NIE_uruchamia_gestu_prawdziwym_klawiszem(qapp, con, rdzen):
    """Zapis do plików wyłącznie świadomym kliknięciem: Enter na przycisku akcji (fokus po
    kliknięciu w listę albo Tab) idzie do przycisku domyślnego - „Zamknij”."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dlg = _okno(qapp, con)
    dlg.show()
    QCoreApplication.processEvents()
    dlg.action_btn.setFocus()
    QTest.keyClick(dlg.action_btn, Qt.Key_Return)
    QCoreApplication.processEvents()
    assert rdzen.staging == [] and rdzen.commity == []
    assert not dlg.isVisible() and dlg.result() == QDialog.Rejected


def test_plan_bez_roboty_gasi_akcje_z_powodem(qapp, con, rdzen):
    rdzen.plany = [_plan(items=())]
    dlg = _okno(qapp, con)
    assert not dlg.action_btn.isEnabled()
    assert dlg.action_btn.toolTip() == i18n.t("objchg.nothing_tip")
    dlg.reject()


def test_etap_Dostawy_gasi_akcje_okna(qapp, con, rdzen):
    dlg = _okno(qapp, con)
    dlg.set_pipeline_busy(True)
    assert not dlg.action_btn.isEnabled()
    dlg.set_pipeline_busy(False)
    assert dlg.action_btn.isEnabled()
    dlg.reject()


def test_linijka_reguly_nazwy_zamiast_wzoru_paska(qapp, con, rdzen):
    """D-1011-6 `O2`: okno mówi jedną linijką, że w nazwie zmienia się wyłącznie człon obiektu -
    bez wzoru i daty paska „Nazwy” (planer ich nie dostaje: atrapa ma sygnaturę bez nich), bez
    ostrzeżenia, bo reguła żadnej nazwy nie wymienia w całości."""
    dlg = _okno(qapp, con)
    assert dlg.name_rule.text() == i18n.t("objchg.name_rule")
    assert dlg.name_rule.property("role") == "secondary"
    assert not hasattr(dlg, "template_line")
    dlg.reject()


def test_okno_na_PRAWDZIWYM_planerze_i_read_modelu_staguje_plan(qapp, tmp_path, monkeypatch):
    """Bez atrapy planu i read-modelu (atrapa wyłącznie dla sterownika zapisu): okno woła planer
    z KOMPLETEM argumentów (`location_at`), pokazuje nazwę z wymienionym członem obiektu
    (D-1011-6 `O2`), a „Zmień obiekt” staguje ten plan prawdziwą klingą repo."""
    from horreum.resolve.catalog import catalog_label
    from horreum.scan import Card
    korzen = tmp_path / "ASTRO_"
    c = db.open_db(str(tmp_path / "real.db"))

    def klatka(rel, kind, sha, canon, karta):
        fid, _ = repo.upsert_frame(c, sha1_data=sha, kind=kind, filetype="fits", camera_id=None,
                                   now=NOW)
        repo.record_header(c, frame_id=fid, raw_json="{}", now=NOW, date_obs="2022-03-26T21:30:12",
                           cards=[Card("OBJECT", 0, karta, None, "str", "Name of the object")],
                           object_raw=karta)
        sciezka = korzen / rel
        sciezka.parent.mkdir(parents=True, exist_ok=True)
        sciezka.write_bytes(b"")
        repo.add_location(c, frame_id=fid, volume="VOL", path=str(sciezka), mtime="m1",
                          header_hash="h1", now=NOW)
        oid, _ = repo.upsert_object(c, canon=canon, catalog=catalog_label(canon), kind="deep_sky",
                                    now=NOW)
        repo.assign_object(c, frame_id=fid, object_id=oid, object_source="header", now=NOW)
        return fid

    fid = klatka(r"LIGHTS\NGC3034\RC6_2600MC\OSC\NGC3034_a.fits", "light", "s1", "NGC3034",
                 "NGC 3034")
    klatka(r"STACKS\NGC3034\RC6\NGC3034_stack.fits", "master_light", "s2", "NGC3034", "NGC 3034")
    cel = queries.object_target(c, "M 44")
    starty = []
    monkeypatch.setattr(writeback, "commit_object_change",
                        lambda con_, run_id, **k: starty.append(run_id) or _Wynik(
                            run_id, applied=[_fr(1, "applied")], blocked=[], failed=[],
                            skipped=[]))
    dlg = _okno(qapp, c, target=cel, frame_ids=[fid])
    assert dlg.error.text() == "", dlg.error.text()
    assert _teksty(dlg.items_tree) == [[
        r"LIGHTS\NGC3034\RC6_2600MC\OSC\NGC3034_a.fits",
        r"LIGHTS\NGC2632\RC6_2600MC\OSC\NGC2632_a.fits",
        "'NGC 3034' → 'NGC 2632'"]]
    run_id = dlg._plan.run_id
    dlg.action_btn.click()
    assert starty == [run_id]
    assert c.execute("SELECT count(*) FROM pending_object_change WHERE run_id = ?",
                     (run_id,)).fetchone()[0] == 1
    dlg.reject()
    c.close()


class _Archiwum:
    """Prawdziwe FITS-y w `tmp_path/ASTRO_` wciągnięte skanem do bazy w pliku, z obiektem
    przypisanym jak po przebiegu (źródło `header`) - dla planera, stagingu i sterownika bez atrap."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "ASTRO_"
        self.db_path = str(tmp_path / "arch.db")
        self.con = db.open_db(self.db_path)

    def fits(self, rel, *, obj=None, date="2022-03-26T21:30:12", seed=0, canon="NGC3034",
             bez_zapasu=False):
        """`bez_zapasu` - `END` na ostatnim rekordzie bloku 2880 B, bez pustych kart: dopisanie
        karty nie ma w nagłówku miejsca i rdzeń spada na drogę atomową (AR-118)."""
        import numpy as np
        from astropy.io import fits
        from horreum import scan
        from horreum.resolve.catalog import catalog_label
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + seed)
        hdu.header["IMAGETYP"] = "Light"
        hdu.header["DATE-OBS"] = date
        if obj is not None:
            hdu.header["OBJECT"] = obj
        i = 0
        while bez_zapasu and (len(hdu.header) + 1) % 36:
            hdu.header[f"PAD{i}"] = i
            i += 1
        hdu.writeto(str(p))
        scan.ingest_record(self.con, scan.scan_file(str(p)), volume="VOL", now=NOW,
                           summary=scan.ScanSummary())
        fid = self.con.execute("SELECT frame_id FROM location WHERE path = ?",
                               (str(p),)).fetchone()[0]
        oid, _ = repo.upsert_object(self.con, canon=canon, catalog=catalog_label(canon),
                                    kind="deep_sky", now=NOW)
        repo.assign_object(self.con, frame_id=fid, object_id=oid, object_source="header", now=NOW)
        return fid, p


def _sha1(p):
    import hashlib
    return hashlib.sha1(p.read_bytes()).hexdigest()


@pytest.fixture
def archiwum(tmp_path):
    a = _Archiwum(tmp_path)
    yield a
    a.con.close()


def test_CYKL_na_PRAWDZIWYM_sterowniku_lista_wynik_Cofnij_bajty_jak_przed(qapp, archiwum):
    """Bez atrapy rdzenia: FITS z kartą (podmiana w miejscu), FITS bez karty z zapasem nagłówka
    (dopisanie W MIEJSCU, AR-118) i FITS bez karty bez zapasu (`END` na ostatnim rekordzie bloku -
    spadek na drogę atomową). Podgląd mówi o obu drogach dopisania przed kliknięciem, wynik liczy
    jeden spadek, zapis w miejscu zostawia plik tym samym plikiem (`st_ino`), a „Cofnij” przywraca
    pliki pod stare ścieżki co do bajtu."""
    from astropy.io import fits
    a = archiwum
    fa, pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a_FLATGRP_NOFLAT_OSC.fits", obj="NGC 3034",
                    seed=1)
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", date="2022-03-26T21:31:00", seed=2)
    fc, pc = a.fits(r"LIGHTS\NGC3034\RC6\OSC\c.fits", date="2022-03-26T21:32:00", seed=3,
                    bez_zapasu=True)
    przed = {pa: _sha1(pa), pb: _sha1(pb), pc: _sha1(pc)}
    ino = {p: os.stat(p).st_ino for p in (pa, pb, pc)}
    cel = queries.object_target(a.con, "M 44")
    dlg = _okno(qapp, a.con, target=cel, frame_ids=[fa, fb, fc])
    karty = [dlg.items_tree.topLevelItem(i).text(2) for i in range(3)]
    assert karty[0] == "'NGC 3034' → 'NGC 2632'"
    # Drogę dopisania podgląd przewiduje PER POZYCJA z lustra kart (AR-155): zapas - w miejscu,
    # pełny blok bez pustej karty - cały plik; zdania ogólnego „zależy od pliku” nie ma po co mówić.
    assert karty[1].endswith(i18n.t("objchg.card_add_fits_inplace_short"))
    assert karty[2].endswith(i18n.t("objchg.card_add_fits_rewrite_short"))
    assert dlg.card_note.isHidden()
    dlg.action_btn.click()
    nowe = [a.root / r"LIGHTS\NGC2632\RC6\OSC\NGC2632_a_FLATGRP_NOFLAT_OSC.fits",   # człon obiektu
            a.root / r"LIGHTS\NGC2632\RC6\OSC\b.fits",                       # nazwa bez obiektu
            a.root / r"LIGHTS\NGC2632\RC6\OSC\c.fits"]
    assert all(p.exists() for p in nowe) and not any(p.exists() for p in (pa, pb, pc))
    assert [fits.getheader(str(p))["OBJECT"] for p in nowe] == ["NGC 2632"] * 3
    assert [os.stat(n).st_ino == ino[s] for n, s in zip(nowe, (pa, pb, pc))] == [True, True, False]
    assert dlg.status.text().startswith(i18n.t("objchg.res.applied", n=3))
    assert dlg.card_note.isHidden()                  # po biegu drogę pliku mówi jego status
    assert i18n.t("wb.inplace_fallback", n=1) in dlg.status.text()     # tylko plik bez zapasu
    assert not dlg.undo_btn.isHidden()
    dlg.undo_btn.click()
    assert {p: _sha1(p) for p in (pa, pb, pc)} == przed
    assert not (a.root / "LIGHTS" / "NGC2632").exists()   # katalogi gestu zdjęte
    assert dlg.undo_btn.isHidden()
    dlg.reject()


def test_Dom_na_PRAWDZIWYCH_zdarzeniach_gestu_mowi_przeniesiono_do_folderu_obiektu(
        qapp, archiwum):
    """Gest przez prawdziwy sterownik → dziennik → `queries.last_hand_gesture` → zdanie Domu. Dwa
    pliki zmieniają folder - Dom ma powiedzieć „przeniesiono 2 pliki do folderu obiektu”, nie
    „przemianowano” ani „N zmian”. Po „Cofnij” (osobny gest - własny znacznik czasu) - że wróciły.

    Wymaga `relocated_dirs` w read-modelu (relokacje ze zmianą katalogu); bez niego Dom mówi
    zdaniem ogólnym, bo z samego powodu nie wie, czy folder się zmienił."""
    from horreum.gui.home import zdanie_gestu
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\a.fits", obj="NGC 3034", seed=1)
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", obj="NGC 3034", seed=2,
                   date="2022-03-26T21:31:00")
    zegar = iter(f"2026-10-11T12:{m:02d}:00+00:00" for m in range(1, 60))
    dlg = _okno(qapp, a.con, target=queries.object_target(a.con, "M 44"), frame_ids=[fa, fb],
                now_fn=lambda: next(zegar))
    dlg.action_btn.click()
    assert zdanie_gestu(queries.last_hand_gesture(a.con)) == i18n.t_plural(
        "home.gest.object_relocated", 2)
    dlg.undo_btn.click()
    assert zdanie_gestu(queries.last_hand_gesture(a.con)) == i18n.t_plural(
        "home.gest.object_relocated_back", 2)
    dlg.reject()


def test_pominiecie_BEZ_ZMIAN_planera_liczy_sie_w_bez_zmian_nie_w_pominie(qapp, archiwum):
    """Planer oddaje pozycję, która nic nie zmienia, jako pominięcie z kodem `SKIP_UNCHANGED` -
    okno liczy ją w „bez zmian”, a lista pominięć niesie wyłącznie odmowy. Prawdziwy planer:
    dyskryminatorem jest kod, nie zdanie (AR-121 (4))."""
    a = archiwum
    zgodny, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_20220326_213012.fits", obj="NGC 3034")
    obcy, _ = a.fits(r"LIGHTS\NGC3031\RC6\OSC\x.fits", obj="NGC 3034", seed=3,
                     date="2022-03-26T22:00:00")
    dlg = _okno(qapp, a.con, target=None, frame_ids=[zgodny, obcy])
    assert dlg.error.text() == "", dlg.error.text()
    assert [s.code for s in dlg._plan.skipped] == [oc.SKIP_UNCHANGED]
    from horreum.gui.object_change_dialog import liczby_planu
    liczby = liczby_planu(dlg._plan)
    assert (liczby["bez_zmian"], liczby["pominie"], liczby["folder"]) == (1, 0, 1)
    assert dlg.skipped_tree.isHidden() and dlg.skipped_tree.topLevelItemCount() == 0
    dlg.reject()


def test_wyjatek_zapisu_Dokoncz_liczy_oczekujace_Z_BAZY_a_wyjatek_cofniecia_zeruje(
        qapp, archiwum, monkeypatch):
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\a.fits", obj="NGC 3034", seed=1)
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", obj="NGC 3034", seed=2,
                   date="2022-03-26T21:31:00")

    def padnij(*a_, **k):
        raise OSError("udział zniknął")
    monkeypatch.setattr(writeback, "commit_object_change", padnij)
    dlg = _okno(qapp, a.con, target=queries.object_target(a.con, "M 44"), frame_ids=[fa, fb])
    dlg.action_btn.click()                                # staging prawdziwy, sterownik pada
    assert dlg.action_btn.text() == i18n.t("objchg.finish_btn", n=2) and dlg.action_btn.isEnabled()
    monkeypatch.setattr(writeback, "undo_object_change", padnij)
    dlg.undo_btn.click()
    assert dlg._pozostalo == 0 and not dlg.undo_btn.isHidden()
    assert dlg.action_btn.text() == i18n.t("objchg.action_change_bare")
    dlg.reject()


def test_CLI_finish_i_undo_przebiegu_po_numerze(archiwum, capsys):
    """Po zamknięciu okna przebieg dokańcza i cofa CLI po numerze ze zdania wyniku - tym samym
    sterownikiem; nieznany przebieg to kod 2 z powodem."""
    from horreum import cli
    from horreum.gui.object_change_dialog import policz_plan
    a = archiwum
    fa, pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\a.fits", obj="NGC 3034", seed=1)
    przed = _sha1(pa)
    plan, _ = policz_plan(a.con, [fa], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    assert cli.main(["object-change", "finish", a.db_path, plan.run_id]) == 0
    assert not pa.exists() and "zmienione 1" in capsys.readouterr().out
    assert cli.main(["object-change", "undo", a.db_path, plan.run_id]) == 0
    assert _sha1(pa) == przed and "cofniete 1" in capsys.readouterr().out
    assert cli.main(["object-change", "finish", a.db_path, "nie-ma-takiego"]) == 2
    assert "odmowa" in capsys.readouterr().out


# ═══════════════════════════════════════════════ wykonanie, cofnięcie, przerwanie


def test_wykonanie_to_staging_TEGO_planu_i_JEDNA_operacja_uchwytu(qapp, con, rdzen):
    dlg = _okno(qapp, con)
    plan = dlg._plan
    zajetosc, zmiany = [], []
    dlg.busy_changed.connect(zajetosc.append)
    dlg.changed.connect(lambda: zmiany.append(1))
    dlg.action_btn.click()
    assert rdzen.staging == [plan]                       # podgląd = zapis: ten sam obiekt planu
    assert rdzen.commity == [plan.run_id]                # jedna operacja, cel = run_id
    assert zajetosc == [True, False] and zmiany == [1]
    assert dlg.summary == dlg.status.text()
    assert dlg.summary.startswith(i18n.t("objchg.res.applied", n=2))
    assert i18n.t("objchg.res.dirs", created=3, removed=0) in dlg.summary
    assert i18n.t("objchg.res.run", run_id=plan.run_id) in dlg.summary   # uchwyt po zamknięciu
    assert not dlg.undo_btn.isHidden() and dlg.undo_btn.isEnabled()
    assert not dlg.action_btn.isEnabled()                # drugi zapis nie ma czego robić
    assert dlg.action_btn.text() == i18n.t("objchg.action_change_bare")
    dlg.reject()


def test_cofnij_idzie_po_run_id_a_plan_liczy_sie_OD_NOWA(qapp, con, rdzen):
    """„Cofnij” → `undo_object_change(run_id)`; po pełnym cofnięciu przebieg jest zużyty: lista
    zostaje z wynikiem cofnięcia, akcja proponuje świeży plan (nowy `run_id`), a „ponownie” to
    świeży staging."""
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    dlg.undo_btn.click()
    assert rdzen.cofniecia == ["run-1"]
    assert rdzen.n_planow == 1                           # wynik cofnięcia na liście, nie nowy plan
    assert dlg.undo_btn.isHidden() and dlg.action_btn.isEnabled()
    assert dlg.action_btn.text() == i18n.t("objchg.replan_btn")
    assert dlg.status.text().startswith(i18n.t("objchg.res.undone", n=2))
    dlg.action_btn.click()                               # świeży plan
    assert rdzen.n_planow == 2 and dlg._plan.run_id == "run-2"
    dlg.action_btn.click()                               # ponownie - nowy przebieg
    assert [p.run_id for p in rdzen.staging] == ["run-1", "run-2"]
    assert rdzen.commity == ["run-1", "run-2"]
    dlg.reject()


def test_lista_PO_BIEGU_mowi_Bylo_Jest_i_status_per_wiersz_takze_po_Cofnij(qapp, con, rdzen):
    """Po zapisie lista opisuje, co SIĘ STAŁO: „Było” / „Jest” (ścieżka z wyniku rdzenia),
    status per wiersz po `location_id` (zrobione / zablokowane z powodem / nie ruszone), liczby
    podglądu (czas przyszły) schowane. Po „Cofnij” to samo w drugą stronę."""
    rdzen.wynik_commitu = _Wynik("run-1", applied=[_fr(11, "applied")], failed=[], skipped=[],
                                 blocked=[writeback.FileResult(12, rf"{STARY}\f2.fits", "blocked",
                                                               "karta odbita bez zapisu: X")])
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    h = dlg.items_tree.headerItem()
    assert [h.text(c) for c in range(4)] == [i18n.t("objchg.col.was"), i18n.t("objchg.col.is"),
                                              i18n.t("objchg.col.card"), i18n.t("objchg.col.status")]
    assert not dlg.items_tree.isColumnHidden(3)
    wiersze = _teksty(dlg.items_tree)
    assert wiersze[0][:2] == [r"LIGHTS\NGC3034\RC6_2600MC\OSC\f1.fits",
                              r"LIGHTS\NGC2632\RC6_2600MC\OSC\f11.fits"]
    assert wiersze[0][3] == i18n.t("objchg.st.done")
    assert wiersze[1][1] == r"LIGHTS\NGC3034\RC6_2600MC\OSC\f2.fits"
    assert wiersze[1][3] == i18n.t("objchg.st.blocked") + i18n.t("objchg.st.reason",
                                                                  reason="karta odbita bez zapisu: X")
    assert wiersze[2][3] == i18n.t("objchg.st.untouched")
    assert dlg.counts.isHidden()
    rdzen.wynik_cofniecia = _Wynik("run-1", applied=[writeback.FileResult(
        11, rf"{STARY}\f1.fits", "restored")], blocked=[], failed=[], skipped=[])
    dlg.undo_btn.click()
    wiersze = _teksty(dlg.items_tree)
    assert wiersze[0][:2] == [r"LIGHTS\NGC2632\RC6_2600MC\OSC\f11.fits",
                              r"LIGHTS\NGC3034\RC6_2600MC\OSC\f1.fits"]
    assert wiersze[0][3] == i18n.t("objchg.st.undone")
    dlg.reject()


def test_cofniecie_z_blokada_zostawia_Cofnij_do_ponowienia(qapp, con, rdzen):
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    rdzen.wynik_cofniecia = _Wynik("run-1", applied=[_fr(11, "restored")],
                                   blocked=[_fr(12, "blocked", "plik zmieniony po geście")],
                                   failed=[], skipped=[])
    dlg.undo_btn.click()
    assert rdzen.n_planow == 1                           # przebieg nie zużyty - bez nowego planu
    assert not dlg.undo_btn.isHidden() and dlg.undo_btn.isEnabled()
    assert "plik zmieniony po geście" in dlg.status.text()
    dlg.reject()


def test_przerwanie_daje_Dokoncz_TEGO_przebiegu_bez_drugiego_stagingu(qapp, con, rdzen):
    rdzen.wynik_commitu = _Wynik("run-1", applied=[_fr(11, "applied")], blocked=[], failed=[],
                                 skipped=[], commit_ids=(5,), cancelled=True)
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    assert dlg.action_btn.text() == i18n.t("objchg.finish_btn", n=2)
    assert dlg.action_btn.isEnabled() and not dlg.undo_btn.isHidden()
    assert i18n.t("wb.cancelled_note") in dlg.status.text()
    rdzen.wynik_commitu = None                            # druga runda dochodzi do końca
    dlg.action_btn.click()
    assert len(rdzen.staging) == 1 and rdzen.commity == ["run-1", "run-1"]
    assert not dlg.action_btn.isEnabled()
    dlg.reject()


def test_przebieg_BEZ_zmian_liczy_plan_od_nowa_zamiast_martwego_przycisku(qapp, con, rdzen):
    rdzen.wynik_commitu = _Wynik("run-1", applied=[], failed=[], skipped=[],
                                 blocked=[_fr(11, "blocked", "header_hash zmieniony"),
                                          _fr(12, "blocked", "header_hash zmieniony")])
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    assert dlg.undo_btn.isHidden()                        # nic do cofnięcia
    assert "header_hash zmieniony" in dlg.status.text()
    assert "header_hash zmieniony" in _teksty(dlg.items_tree)[0][3]   # powód przy wierszu
    assert dlg.action_btn.text() == i18n.t("objchg.replan_btn") and dlg.action_btn.isEnabled()
    dlg.action_btn.click()
    assert rdzen.n_planow == 2 and dlg.items_tree.isColumnHidden(3)
    dlg.reject()


def test_blad_workera_zostawia_Cofnij_bo_przebieg_jest_w_bazie(qapp, con, rdzen, monkeypatch):
    def padnij(*a, **k):
        raise OSError("udział zniknął")
    monkeypatch.setattr(writeback, "commit_object_change", padnij)
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    assert "udział zniknął" in dlg.error.text()
    assert i18n.t("objchg.res.run", run_id="run-1") in dlg.error.text()
    assert not dlg.undo_btn.isHidden()
    dlg.reject()


class _WorkerWBiegu:
    """Atrapa workera w locie: `WritebackRunner.is_busy` patrzy na `_thread`, `cancel()` na
    `_worker.request_cancel()` - więcej stanu straż zamknięcia nie czyta."""

    def __init__(self):
        self.anulowano = False

    def request_cancel(self):
        self.anulowano = True


def test_zamkniecie_w_biegu_to_ZADANIE_ANULOWANIA_okno_zostaje(qapp, con, rdzen):
    dlg = _okno(qapp, con)
    dlg.show()
    w = _WorkerWBiegu()
    dlg._runner._worker, dlg._runner._thread = w, object()
    dlg.reject()
    assert w.anulowano and dlg.isVisible()
    assert dlg.error.text() == i18n.t("wb.close_refused")
    dlg._runner._worker = dlg._runner._thread = None
    dlg.reject()
    assert not dlg.isVisible()


# ═══════════════════════════════════════════════ plan poza wątkiem okna i szerokość


def _czekaj(warunek, limit=10.0):
    """Pętla zdarzeń bez `QTest.qWait` (trzyma GIL przy wątku tła)."""
    koniec = time.monotonic() + limit
    while not warunek() and time.monotonic() < koniec:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return warunek()


def test_plan_liczy_sie_W_TLE_okno_nie_czeka(qapp, con, rdzen):
    """Plan czyta dysk (SMB) - przy planie 0,5 s konstruktor wraca od razu, okno mówi, że liczy,
    a akcja czeka; wynik przychodzi sygnałem. Falsyfikator: plan inline → konstruktor ≥ 0,5 s."""
    rdzen.opoznienie = 0.5
    t0 = time.monotonic()
    dlg = _okno(qapp, con, off_thread=True)
    assert time.monotonic() - t0 < 0.3
    assert dlg.counts.text() == i18n.t("objchg.planning") and not dlg.action_btn.isEnabled()
    assert _czekaj(lambda: dlg._plan is not None and dlg._plan_thread is None)
    assert dlg.items_tree.topLevelItemCount() == 3 and dlg.action_btn.isEnabled()
    dlg.reject()


def test_zamkniecie_w_trakcie_planu_NIE_czeka_okno_znika_a_zamyka_sie_po_planie(qapp, con, rdzen):
    """Zamknięcie w trakcie planu nie czeka na wątek (odczyt katalogów po SMB bez limitu zamroziłby
    okno): okno znika od razu, a zamyka się, gdy plan skończy - wynik spóźnionego planu do kosza.
    Falsyfikator: `wait()` w `done` → zamknięcie trwa tyle, co plan (0,6 s)."""
    rdzen.opoznienie = 0.6
    dlg = _okno(qapp, con, off_thread=True)
    dlg.show()
    zamkniete = []
    dlg.finished.connect(zamkniete.append)
    t0 = time.monotonic()
    dlg.reject()
    assert time.monotonic() - t0 < 0.3
    assert not dlg.isVisible() and zamkniete == [] and dlg._plan_thread.isRunning()
    assert _czekaj(lambda: dlg._plan_thread is None)
    assert zamkniete == [QDialog.Rejected]
    assert dlg._plan is None                              # wynik spóźniony poszedł do kosza


def test_exec_zamkniety_w_trakcie_planu_NIE_kasuje_okna_z_zywym_watkiem(qapp, con, rdzen):
    """zamknięcie w trakcie planu chowa okno, a schowanie modalnego okna
    kończy `exec` przy ŻYWYM wątku planu; kasacja w `exec` niszczyła dziecko `QThread` w biegu
    (`qFatal`). PRAWDZIWY `exec`: po powrocie okno żyje, dopóki żyje wątek; po końcu wątku -
    skasowane. Falsyfikator: `deleteLater` bezwarunkowo w `exec` → okno ginie w pierwszym
    `DeferredDelete` z wątkiem w biegu."""
    import shiboken6
    from PySide6.QtCore import QTimer
    rdzen.opoznienie = 0.6
    dlg = _okno(qapp, con, off_thread=True)
    QTimer.singleShot(0, dlg.reject)
    dlg.exec()
    watek = dlg._plan_thread
    assert watek is not None and watek.isRunning()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert shiboken6.isValid(dlg)                                # wątek w biegu trzyma okno
    assert _czekaj(lambda: dlg._plan_thread is None)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not shiboken6.isValid(dlg)                            # wątek skończył - okno skasowane


def test_zatrzymaj_pola_zbiera_watek_planu_zamknietego_okna(qapp, con, rdzen):
    """Okno po `exec` z wątkiem planu w biegu żyje pod gospodarzem; przy wyjściu z aplikacji
    gospodarz woła `zatrzymaj_pola` (`MainWindow._zatrzymaj_watki_widokow`): czeka do końca wątku,
    zbiera go i wraca - idempotentnie, a spóźniony wynik planu nie dotyka okna."""
    from PySide6.QtCore import QTimer
    rdzen.opoznienie = 0.4
    dlg = _okno(qapp, con, off_thread=True)
    QTimer.singleShot(0, dlg.reject)
    dlg.exec()
    watek = dlg._plan_thread
    assert watek is not None and watek.isRunning()
    dlg.zatrzymaj_pola()
    assert dlg._plan_thread is None and not watek.isRunning()
    dlg.zatrzymaj_pola()
    QCoreApplication.processEvents()
    assert dlg._plan is None


def test_dlugie_sciezki_NIE_rozpychaja_okna_ponad_kanon_1920(qapp, con, rdzen):
    """Kanon minimalnego ekranu: 1920×1080 logicznych. Ścieżka dłuższa niż ekran jest elidowana
    w środku (pełna w podpowiedzi), a nie zawijana ani rozpychająca okno."""
    dlugi = KORZEN + "\\LIGHTS\\" + "\\".join(["Bardzo_dlugi_katalog_konfiguracji"] * 12)
    item = dataclasses.replace(_pozycja(1), old_path=dlugi + r"\f1.fits", new_path=dlugi + r"\g1.fits")
    rdzen.plany = [_plan(items=(item,), skipped=(oc.ObjectChangeSkip(9, dlugi, "powód " * 60),),
                         warnings=(oc.ObjectChangeWarning((1,), "ostrzeżenie " * 80),))]
    dlg = _okno(qapp, con)
    dlg.show()
    QCoreApplication.processEvents()
    assert dlg.minimumSizeHint().width() <= 1920
    assert dlg.sizeHint().width() <= 1920
    assert dlg.width() <= 1920
    assert dlg.items_tree.topLevelItem(0).toolTip(0) == dlugi + r"\f1.fits"
    dlg.reject()


# ═══════════════════════════════════════════════ zdania i klucze składane w locie


def test_klucze_skladane_w_locie_sa_w_katalogu():
    """Klucze, które idą do `i18n.t` zmienną (zdanie wyniku przez `zdanie_wyniku_zapisu`, liczby
    planu), bramka literałów nie widzi - pinujemy je tu."""
    for k in ("objchg.res.applied", "objchg.res.undone", "objchg.counts", "wb.inplace_fallback",
              "grid.sel.object_change_tip_only", "home.gest.object_relocated",
              "home.gest.object_relocated_back", "home.gest.object_files", "objchg.st.done",
              "objchg.st.undone", "objchg.st.blocked", "objchg.st.failed", "objchg.st.skipped"):
        assert k in CATALOG, k


def test_zdanie_wyniku_mowi_katalogi_niepewne_i_ostrzezenia():
    from horreum.gui.object_change_dialog import zdanie_wyniku_zmiany
    z = zdanie_wyniku_zmiany(_Wynik("r", applied=[_fr(1, "applied")], blocked=[], failed=[],
                                    skipped=[], dirs_created=2, dirs_uncertain=1,
                                    warnings=("katalog C zostaje do oka",)))
    assert i18n.t("objchg.res.dirs", created=2, removed=0) in z
    assert i18n.t_plural("objchg.res.dirs_uncertain", 1) in z
    assert z.endswith("\nkatalog C zostaje do oka")


# ═══════════════════════════════════════════════ uchwyt zapisu: `_OPS`


def test_OPS_prowadza_gest_i_karte_w_miejscu_do_rdzenia(monkeypatch):
    from horreum.gui.wb_worker import WritebackWorker
    wolania = []
    monkeypatch.setattr(writeback, "commit",
                        lambda con, t, **k: wolania.append(("commit", t, k.get("inplace"))))
    monkeypatch.setattr(writeback, "commit_object_change",
                        lambda con, t, **k: wolania.append(("object_change", t)))
    monkeypatch.setattr(writeback, "undo_object_change",
                        lambda con, t, **k: wolania.append(("undo_object_change", t)))
    for op in ("commit_inplace", "object_change", "undo_object_change", "commit"):
        WritebackWorker._OPS[op](None, "r1", NOW, lambda *a: None, lambda: False)
    assert wolania == [("commit", "r1", True), ("object_change", "r1"),
                       ("undo_object_change", "r1"), ("commit", "r1", None)]


def test_zdanie_drogi_zapisu_mowi_TYLKO_o_spadku_na_atomowa():
    from horreum.gui.wb_worker import zdanie_commitu_kart, zdanie_drogi_zapisu
    a = _fr(1, "applied")
    b = _fr(2, "applied", f"{writeback.PREFIKS_DROGI_ATOMOWEJ}: karta się nie mieści w nagłówku",
            code=writeback.CODE_INPLACE_FALLBACK)
    wszystko_w_miejscu = writeback.CommitResult("r", 3, [a], [], [], [], in_place=[a])
    assert zdanie_drogi_zapisu(wszystko_w_miejscu) == ""
    spadek = writeback.CommitResult("r", 3, [a, b], [], [], [], in_place=[a])
    assert zdanie_drogi_zapisu(spadek) == i18n.t("wb.inplace_fallback", n=1)    # bez żargonu
    # zapis potwierdzony z dysku po przerwanym commicie: poza `in_place`, ale niczego nie
    # przepisano - to nie spadek na drogę atomową
    potwierdzony = _fr(3, "applied", "zapis potwierdzony z dysku po przerwanym commicie 4 - nic "
                                     "do zapisania")
    assert zdanie_drogi_zapisu(writeback.CommitResult("r", 3, [a, potwierdzony], [], [], [],
                                                      in_place=[a])) == ""
    # zwykły commit (atomowy z założenia) nie dostaje członu o „spadku”; zapis w miejscu mówi
    # o spadku zdaniem człowieka - szczegół rdzenia nie wchodzi do zdania (podpowiedź okna)
    czlon = i18n.t("wb.inplace_fallback", n=1)
    assert czlon not in zdanie_commitu_kart(spadek, "grid.wb.applied")[0]
    w_miejscu = zdanie_commitu_kart(spadek, "grid.wb.applied", w_miejscu=True)[0]
    assert czlon in w_miejscu and "karta się nie mieści" not in w_miejscu


# ═══════════════════════════════════════════════ pasek Zbiorów: „Zmień obiekt…” i `changeable`


def test_kontrolka_zyje_przy_SAMYM_changeable_a_powod_bazy_zostaje(qapp):
    from horreum.gui.grid import SelectionBar
    bar = SelectionBar()
    bar.set_object_actions(namable=0, clearable=0, changeable=3, reason="grid.sel.object_tip_header")
    assert bar.btn_object.isEnabled() and bar.act_change.isEnabled()
    assert not bar.act_name.isEnabled() and not bar.act_clear.isEnabled()
    assert bar.btn_object.toolTip() == (i18n.t("grid.sel.object_tip_header") + "\n"
                                        + i18n.t_plural("grid.sel.object_change_tip_only", 3))
    bar.set_object_actions(namable=0, clearable=0, changeable=0, reason="grid.sel.object_tip_header")
    assert not bar.btn_object.isEnabled() and not bar.act_change.isEnabled()
    bar.close()


def test_set_object_actions_BEZ_changeable_pada_wywolaniem(qapp):
    """Parametr bez domyślnej: wołający, który o nim zapomni, pada, a nie gasi pozycji po cichu."""
    from horreum.gui.grid import SelectionBar
    bar = SelectionBar()
    with pytest.raises(TypeError):
        bar.set_object_actions(namable=1, clearable=0)
    bar.close()


@pytest.fixture
def widok(qapp, tmp_path):
    """FramesView: 2 lighty ze ścieżki, 1 z nagłówka (wszystkie z obecną kopią), 1 dark, 1 light
    bez obecnej kopii."""
    from horreum.gui.grid import FramesView
    c = db.open_db(str(tmp_path / "g.db"))
    c.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (5,'NGC3034','NGC','deep_sky')")
    for i, (kind, src, obecna) in enumerate([("light", "path", 1), ("light", "path", 1),
                                             ("light", "header", 1), ("dark", None, 1),
                                             ("light", "header", 0)], start=1):
        c.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
                  "object_source) VALUES (?,?, 'fits', ?, ?, ?, ?)",
                  (i, kind, f"sha{i}", NOW, 5 if src else None, src))
        c.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (i,))
        c.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?,'V',?,?)",
                  (i, rf"{STARY}\f{i}.fits", obecna))
    # Klatka 6: light z DWIEMA obecnymi kopiami - planer jej nie przeniesie (której kopii?).
    c.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
              "object_source) VALUES (6, 'light', 'fits', 'sha6', ?, 5, 'path')", (NOW,))
    c.execute("INSERT INTO header(frame_id, raw_json) VALUES (6, '{}')")
    for kopia in ("a", "b"):
        c.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (6,'V',?,1)",
                  (rf"{STARY}\f6{kopia}.fits",))
    c.commit()
    v = FramesView(c, now_fn=lambda: NOW)
    v._writeback_async = False
    yield v, c
    if not any(t.isRunning() for t in v.findChildren(QThread)):
        v.close()
        v.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    c.close()


def _zaznacz(view, frame_ids):
    from PySide6.QtCore import QItemSelectionModel
    sm = view.table.selectionModel()
    sm.clearSelection()
    for i, row in enumerate(view.model._rows):
        if isinstance(row, dict) and row.get("frame_id") in set(frame_ids):
            sm.select(view.model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    view._update_count()


def test_changeable_liczy_klatki_nieba_z_OBECNA_kopia(widok):
    v, _ = widok
    _zaznacz(v, [3])                                      # nagłówek - Przypisz milczy, Zmień żyje
    assert v.sel_bar.act_change.isEnabled() and not v.sel_bar.act_name.isEnabled()
    _zaznacz(v, [4])                                      # dark - kalibracja obiektu nie ma
    assert not v.sel_bar.act_change.isEnabled()
    _zaznacz(v, [5])                                      # bez obecnej kopii - nie ma czego przenieść
    assert not v.sel_bar.act_change.isEnabled()
    _zaznacz(v, [6])                                      # dwie obecne kopie - planer nie przeniesie
    assert not v.sel_bar.act_change.isEnabled()
    _zaznacz(v, [1, 3, 6])                                # liczba w tooltipie: do sprawdzenia w podglądzie
    assert i18n.t("grid.sel.object_change_tip", n=2) in v.sel_bar.btn_object.toolTip()


class _OknoAtrapa:
    """Atrapa `ObjectChangeDialog` w module, który ją CZYTA (`grid`): zapamiętuje argumenty,
    `exec` woła scenariusz testu."""
    ostatnie = None
    scenariusz = None

    def __init__(self, con, **kw):
        from PySide6.QtCore import QObject, Signal

        class _Sygnaly(QObject):
            changed = Signal()
            busy_changed = Signal(bool)
        self._s = _Sygnaly()
        self.changed, self.busy_changed = self._s.changed, self._s.busy_changed
        self.kw = kw
        self.summary = "zdanie wyniku"
        self.zajetosc = []
        # Klatki okna: z zaznaczenia albo - przy wejściu na przebieg - z bazy (tu: stałe).
        self.frame_ids = tuple(kw.get("frame_ids") or (1, 2))
        _OknoAtrapa.ostatnie = self

    def set_pipeline_busy(self, busy):
        self.zajetosc.append(busy)

    def exec(self):
        if _OknoAtrapa.scenariusz is not None:
            _OknoAtrapa.scenariusz(self)
        return QDialog.Rejected


class _WyborAtrapa:
    """Atrapa okna wyboru celu: zwraca wybór bez zapisu, jak prawdziwe okno przypisania - z kluczem
    aliasu policzonym TĄ SAMĄ regułą co okno (`alias_key`: kanon z gramatyki → brak klucza)."""
    from horreum.gui.assign_dialog import alias_key as _alias_key
    wybor = ("NGC2632", "NGC", None, _alias_key(None, "NGC2632"))
    ostatnie = None

    def __init__(self, con, **kw):
        from PySide6.QtWidgets import QLabel, QPushButton
        self.kw = kw
        self.head, self.accept_btn = QLabel(), QPushButton()
        self.tytul = None
        self.selected = None
        _WyborAtrapa.ostatnie = self

    def setWindowTitle(self, t):
        self.tytul = t

    def exec(self):
        self.selected = _WyborAtrapa.wybor
        return QDialog.Accepted


@pytest.fixture
def gest(monkeypatch):
    _OknoAtrapa.ostatnie = _OknoAtrapa.scenariusz = None
    _WyborAtrapa.ostatnie = None
    monkeypatch.setattr(grid_mod, "ObjectChangeDialog", _OknoAtrapa)
    monkeypatch.setattr(grid_mod, "AssignObjectDialog", _WyborAtrapa)
    cele = []

    def cel(con, text, *, alias_norm=None):
        cele.append((text, alias_norm))
        return dataclasses.replace(CEL, alias_norm=alias_norm)
    monkeypatch.setattr(queries, "object_target", cel)
    return cele


def test_Zmien_obiekt_wybor_BEZ_zapisu_potem_okno_z_celem_i_zaznaczeniem(widok, gest):
    v, c = widok
    _zaznacz(v, [1, 3])
    przed = c.execute("SELECT count(*) FROM event").fetchone()[0]
    statusy = []
    v.status_message.connect(statusy.append)
    v.sel_bar.act_change.trigger()
    w = _WyborAtrapa.ostatnie
    assert w.tytul == i18n.t("grid.sel.object_change_pick_title")
    assert w.head.text() == i18n.t_plural("grid.sel.object_change_pick_head", 2)
    assert w.accept_btn.text() == i18n.t("grid.sel.object_change_pick_ok")
    assert gest == [("NGC2632", None)]                    # klucz aliasu z okna jedzie w celu
    okno = _OknoAtrapa.ostatnie
    assert sorted(okno.kw["frame_ids"]) == [1, 3] and okno.kw["target"].canon == "NGC2632"
    assert okno.kw["target"].alias_norm is None
    # Nazwa nie zależy od paska „Nazwy” (D-1011-6 `O2`) - okno nie dostaje jego polityki.
    assert set(okno.kw) == {"frame_ids", "target", "now_fn", "db_path", "off_thread", "parent"}
    assert okno.kw["off_thread"] is False                 # seam testowy widoku idzie do okna
    assert c.execute("SELECT count(*) FROM event").fetchone()[0] == przed   # wybór nic nie pisze
    assert statusy[-1] == "zdanie wyniku"                 # zdanie okna trafia na pasek


def test_cel_BEZ_formy_karty_odmowa_PRZED_oknem(widok, gest, monkeypatch):
    v, _ = widok
    monkeypatch.setattr(queries, "object_target",
                        lambda con, text, *, alias_norm=None: dataclasses.replace(CEL, card_form=None))
    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: ostrzezenia.append(a[2]))
    _zaznacz(v, [1])
    v._on_object_change()
    assert ostrzezenia == [i18n.t("grid.sel.object_change_no_card", canon="NGC2632")]
    assert _OknoAtrapa.ostatnie is None


def test_zmiana_w_oknie_odswieza_zbior_ZACHOWUJE_zaznaczenie_i_mutex(widok, gest):
    v, c = widok
    _zaznacz(v, [1, 2])
    sygnaly = {"os": 0, "porzadki": 0, "mutex": []}
    v.object_axis_changed.connect(lambda: sygnaly.__setitem__("os", sygnaly["os"] + 1))
    v.stan_porzadkow_changed.connect(lambda: sygnaly.__setitem__("porzadki", sygnaly["porzadki"] + 1))
    v.writeback_busy.connect(sygnaly["mutex"].append)

    def scenariusz(okno):
        okno.busy_changed.emit(True)
        c.execute("UPDATE location SET path = ? WHERE frame_id = 1", (rf"{NOWY}\f1.fits",))
        c.commit()
        okno.busy_changed.emit(False)
        okno.changed.emit()
        v.set_busy(True)                                  # etap Dostawy przy otwartym oknie
        v.set_busy(False)
    _OknoAtrapa.scenariusz = scenariusz
    v._on_object_change()
    assert sygnaly["os"] == 1 and sygnaly["porzadki"] == 1 and sygnaly["mutex"] == [True, False]
    assert _OknoAtrapa.ostatnie.zajetosc == [True, False]
    assert {r["frame_id"] for r in v._selected_data_rows()} == {1, 2}
    sciezki = {r["frame_id"]: r["path"] for r in v.model._rows if isinstance(r, dict) and "path" in r}
    assert sciezki[1] == rf"{NOWY}\f1.fits"
    assert v._okno_zmiany_obiektu is None


def test_przebieg_z_Porzadkow_otwiera_okno_na_run_id_z_mutexem_i_odswiezeniem(widok, gest):
    """Wejście z Porządków (AR-121): okno dostaje WYŁĄCZNIE `run_id` (klatki i cel bierze z bazy),
    zapis w nim idzie przez mutex gospodarza, a po zmianie zbiór zaznacza klatki przebiegu."""
    v, _ = widok
    sygnaly = {"porzadki": 0, "mutex": []}
    v.stan_porzadkow_changed.connect(lambda: sygnaly.__setitem__("porzadki", sygnaly["porzadki"] + 1))
    v.writeback_busy.connect(sygnaly["mutex"].append)

    def scenariusz(okno):
        okno.busy_changed.emit(True)
        okno.busy_changed.emit(False)
        okno.changed.emit()
    _OknoAtrapa.scenariusz = scenariusz
    v.otworz_przebieg_zmiany_obiektu("przebieg-9")
    okno = _OknoAtrapa.ostatnie
    assert okno.kw["run_id"] == "przebieg-9" and "frame_ids" not in okno.kw
    assert "target" not in okno.kw
    assert sygnaly == {"porzadki": 1, "mutex": [True, False]}
    assert {r["frame_id"] for r in v._selected_data_rows()} == {1, 2}
    assert v._okno_zmiany_obiektu is None


def test_przebieg_z_Porzadkow_przy_zajetym_widoku_ODMAWIA_przed_oknem(widok, gest):
    """Bramka Z3 (kimi): ta sama straż zajętości co wejścia z zaznaczenia - w biegu etapu
    Dostawy okno przebiegu z czynnym „Dokończ” byłoby drugim pisarzem obok etapu."""
    v, _ = widok
    statusy = []
    v.status_message.connect(statusy.append)
    v.set_busy(True)
    v.otworz_przebieg_zmiany_obiektu("przebieg-9")
    v.set_busy(False)
    assert statusy == [i18n.t("grid.inplace.busy_stage")] and _OknoAtrapa.ostatnie is None


def test_zajety_widok_ODMAWIA_gestu_przed_wyborem(widok, gest):
    v, _ = widok
    _zaznacz(v, [1])
    statusy = []
    v.status_message.connect(statusy.append)
    v.set_busy(True)
    v._on_object_change()
    v._on_align_files()
    assert statusy == [i18n.t("grid.inplace.busy_stage")] * 2
    assert _WyborAtrapa.ostatnie is None and _OknoAtrapa.ostatnie is None
    v.set_busy(False)


# ═══════════════════════════════════════════════ Porządki → perspektywa → „Uzgodnij pliki…”


def test_perspektywa_tnie_predykatem_i_podaje_RECEPTE_gestu(widok, monkeypatch):
    v, _ = widok
    monkeypatch.setattr(queries, "file_object_mismatch_frame_ids", lambda con: {1, 3})
    recepty = []
    v.status_recipe.connect(recepty.append)
    v.apply_perspective(grid_mod.PRESET_FILE_OBJECT_MISMATCH)
    widoczne = {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}
    assert widoczne == {1, 3}
    assert recepty and i18n.t("grid.sel.object_change_align") in recepty[-1]


def test_Uzgodnij_pliki_w_menu_perspektywy_otwiera_okno_BEZ_celu(widok, gest, monkeypatch):
    v, _ = widok
    monkeypatch.setattr(queries, "file_object_mismatch_frame_ids", lambda con: {1, 3})
    v.apply_perspective(grid_mod.PRESET_FILE_OBJECT_MISMATCH)
    v.show()
    QCoreApplication.processEvents()
    _zaznacz(v, [1, 3])
    v._on_table_menu(v.table.visualRect(v.model.index(0, 0)).center())
    assert v.act_align_files.isVisible() and v.act_align_files.isEnabled()
    assert v.act_align_files.toolTip() == i18n.t_plural("grid.sel.object_change_align_tip", 2)
    v._menu_tabeli.hide()
    v.act_align_files.trigger()
    okno = _OknoAtrapa.ostatnie
    assert okno.kw["target"] is None and sorted(okno.kw["frame_ids"]) == [1, 3]
    assert _WyborAtrapa.ostatnie is None                  # „Uzgodnij” nie pyta o cel
    v.hide()


def test_poza_perspektywa_menu_tabeli_NIE_ma_Uzgodnij(widok, gest):
    """Menu innej perspektywy (tu „Wersje stosów” - menu pokazuje się zawsze) nie niesie gestu."""
    from PySide6.QtCore import QPoint
    v, _ = widok
    v.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    v.show()
    QCoreApplication.processEvents()
    v._on_table_menu(QPoint(1, 1))
    assert v.act_keep_all_versions.isVisible() and not v.act_align_files.isVisible()
    v._menu_tabeli.hide()
    v.hide()


def test_wiersz_Porzadkow_liczy_predykat_i_prowadzi_do_perspektywy(qapp, con, monkeypatch):
    from horreum.gui.tasks import TasksView
    monkeypatch.setattr(queries, "file_object_mismatch_frame_ids", lambda c: [7, 8, 9])
    t = TasksView(con, now_fn=lambda: NOW)
    t.refresh_counts()
    from horreum.gui import rows as rows_mod
    from PySide6.QtCore import Qt
    it = next(t.tasks.item(i) for i in range(t.tasks.count())
              if t.tasks.item(i).data(Qt.UserRole) == "file_object_mismatch_frames")
    assert it.text() == i18n.t("tasks.file_object_mismatch_frames")
    assert it.data(rows_mod.SECONDARY) == "3  ›" and it.data(rows_mod.STRONG)
    assert i18n.t("grid.sel.object_change_align") in it.toolTip()
    cele = []
    t.open_collection.connect(cele.append)
    t._on_task_clicked(it)
    assert cele == [grid_mod.PRESET_FILE_OBJECT_MISMATCH]
    t.close()


def test_wiersz_przerwanych_zmian_liczy_przebiegi_i_otwiera_NAJSTARSZY(qapp, con, monkeypatch):
    """AR-121: wiersz liczy przebiegi z `queries.interrupted_object_change_runs` (robota - pogrubiony,
    w plakietce), klik emituje `run_id` najstarszego; przy zerze szary i klik niczego nie otwiera."""
    from PySide6.QtCore import Qt
    from horreum.gui import rows as rows_mod
    from horreum.gui.tasks import TasksView
    przebiegi = ["stary", "nowy"]
    monkeypatch.setattr(queries, "interrupted_object_change_runs", lambda c: list(przebiegi))
    t = TasksView(con, now_fn=lambda: NOW)
    plakietki = []
    t.counts_changed.connect(plakietki.append)
    t.refresh_counts()
    it = next(t.tasks.item(i) for i in range(t.tasks.count())
              if t.tasks.item(i).data(Qt.UserRole) == "object_change_interrupted")
    assert it.text() == i18n.t("tasks.object_change_interrupted")
    assert it.data(rows_mod.SECONDARY) == "2  ›" and it.data(rows_mod.STRONG)
    assert it.toolTip() == i18n.t("tasks.object_change_interrupted_tip")
    otwarte = []
    t.open_object_change_run.connect(otwarte.append)
    t._on_task_clicked(it)
    assert otwarte == ["stary"]
    przebiegi.clear()
    t.refresh_counts()
    assert it.data(rows_mod.SECONDARY) == "0  ›" and not it.data(rows_mod.STRONG)
    assert it.toolTip() == ""
    t._on_task_clicked(it)
    assert otwarte == ["stary"]
    assert plakietki[0] == plakietki[1] + 1
    t.close()


def test_przerwany_przebieg_z_bazy_lista_Dokoncz_potem_Cofnij_bajty_jak_przed(qapp, archiwum):
    """AR-121 na PRAWDZIWYM rdzeniu: staging bez sterownika (awaria procesu po stagingu) - przebieg
    jest na liście przerwanych; okno z `run_id` bierze klatki i cel z bazy, pokazuje pozycje
    „czeka na zapis → <cel>” z kartą ze stagingu i „Dokończ (2)”; klik dokańcza tym samym
    sterownikiem (przebieg schodzi z listy, nagłówek przestaje mówić „Przerwany”, martwego
    przycisku nie ma), „Cofnij” wraca do bajtów sprzed gestu, a okno proponuje świeży plan
    zwykłym nagłówkiem gestu (wizytacja W1)."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog, policz_plan
    a = archiwum
    fa, pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_b.fits", obj="NGC 3034", seed=2,
                    date="2022-03-26T21:31:00")
    przed = {pa: _sha1(pa), pb: _sha1(pb)}
    plan, _ = policz_plan(a.con, [fa, fb], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    assert queries.interrupted_object_change_runs(a.con) == [plan.run_id]
    widok = queries.object_change_run_view(a.con, plan.run_id)
    assert (widok["pending"], widok["can_finish"]) == (2, True)

    dlg = ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
    assert dlg.frame_ids == (fa, fb)
    assert dlg.head.text() == i18n.t_plural("objchg.head_resume_change", 2, canon="NGC2632",
                                            card="NGC 2632")
    # 32-znakowy numer przebiegu nie stoi w nagłówku - niesie go wiersz stanu (do skopiowania)
    assert plan.run_id not in dlg.head.text() and plan.run_id in dlg.status.text()
    assert dlg.opis.text() == i18n.t("objchg.explain_resume")
    nowe = a.root / r"LIGHTS\NGC2632\RC6\OSC"            # baza bez korzenia: pełne ścieżki

    def czeka(p):
        return i18n.t("objchg.st.pending_to", path=str(p))
    assert _teksty(dlg.items_tree) == [
        [str(pa), str(pa), "'NGC 3034' → 'NGC 2632'", czeka(nowe / "NGC2632_a.fits")],
        [str(pb), str(pb), "'NGC 3034' → 'NGC 2632'", czeka(nowe / "NGC2632_b.fits")]]
    assert dlg.action_btn.text() == i18n.t("objchg.finish_btn", n=2) and dlg.action_btn.isEnabled()
    assert not dlg.undo_btn.isHidden()
    dlg.action_btn.click()
    assert (nowe / "NGC2632_a.fits").exists() and (nowe / "NGC2632_b.fits").exists()
    assert queries.interrupted_object_change_runs(a.con) == []
    assert dlg.status.text().startswith(i18n.t("objchg.res.applied", n=2))
    assert dlg.head.text() == i18n.t_plural("objchg.head_change", 2, canon="NGC2632",
                                            card="NGC 2632")
    assert dlg.action_btn.isHidden() and not dlg.undo_btn.isHidden()
    dlg.undo_btn.click()
    assert {p: _sha1(p) for p in (pa, pb)} == przed
    assert a.con.execute("SELECT status FROM object_change_run WHERE run_id = ?",
                         (plan.run_id,)).fetchone()[0] == "undone"
    assert dlg.action_btn.text() == i18n.t("objchg.replan_btn")   # świeży plan na klatkach przebiegu
    assert not dlg.action_btn.isHidden() and dlg.opis.text() == i18n.t("objchg.explain_change")
    dlg.reject()


def test_przebieg_staged_BEZ_czekajacych_Dokoncz_domyka_zamiast_samego_Cofnij(qapp, archiwum):
    """Bramka Z1 (sol, kimi): awaria po ostatniej pozycji, przed domknięciem przebiegu, zostawia
    `staged` bez pozycji `pending`. Okno z Porządków daje „Dokończ” (bez liczby) - sterownik
    domyka przebieg i schodzi on z listy przerwanych; poprawnie zapisane pliki zostają."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog, policz_plan
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    plan, _ = policz_plan(a.con, [fa], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    writeback.commit_object_change(a.con, plan.run_id, now=NOW)
    a.con.execute("UPDATE object_change_run SET status = 'staged' WHERE run_id = ?", (plan.run_id,))
    a.con.commit()
    widok = queries.object_change_run_view(a.con, plan.run_id)
    assert (widok["pending"], widok["can_finish"]) == (0, True)
    nowy = a.root / r"LIGHTS\NGC2632\RC6\OSC\NGC2632_a.fits"
    dlg = ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
    assert dlg.action_btn.text() == i18n.t("objchg.finish_btn_bare") and dlg.action_btn.isEnabled()
    dlg.action_btn.click()
    assert queries.interrupted_object_change_runs(a.con) == [] and nowy.exists()
    assert _teksty(dlg.items_tree)[0][3] == i18n.t("objchg.st.done")   # nie „nie ruszone”
    dlg.reject()


def test_Dokoncz_zostawia_status_pozycji_zapisanych_PRZED_przerwaniem(qapp, archiwum):
    """Bramka Z4 (kimi): wynik „Dokończ” niesie wyłącznie pozycje, które czekały - pozycja zapisana
    przed przerwaniem zachowuje status z bazy („zrobione”), zamiast „nie ruszone”."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog, policz_plan
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_b.fits", obj="NGC 3034", seed=2,
                   date="2022-03-26T21:31:00")
    plan, _ = policz_plan(a.con, [fa, fb], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    licznik = iter([False, True])                         # przerwanie przed drugą pozycją
    wynik = writeback.commit_object_change(a.con, plan.run_id, now=NOW,
                                           should_cancel=lambda: next(licznik))
    assert wynik.cancelled and len(wynik.applied) == 1
    dlg = ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
    assert dlg.action_btn.text() == i18n.t("objchg.finish_btn", n=1)
    dlg.action_btn.click()
    assert [w[3] for w in _teksty(dlg.items_tree)] == [i18n.t("objchg.st.done")] * 2
    dlg.reject()


def test_cofanie_przerwane_i_pozycja_z_bledem_opis_mowi_droge_bez_martwego_przycisku(
        qapp, archiwum):
    """Bramka Z8 (wizytacja W2): `undoing` - opis mówi, że „Cofnij” dokończy cofanie; `applied`
    z pozycją `failed` - że „Cofnij” cofa cały przebieg. W obu przycisku akcji nie ma (nie ma
    czego dokańczać), „Cofnij” jest."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog, policz_plan
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    plan, _ = policz_plan(a.con, [fa], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    for status, pozycja, opis in (("undoing", "applied", "objchg.explain_resume_undoing"),
                                  ("applied", "failed", "objchg.explain_resume_failed")):
        a.con.execute("UPDATE object_change_run SET status = ? WHERE run_id = ?",
                      (status, plan.run_id))
        a.con.execute("UPDATE pending_object_change SET status = ? WHERE run_id = ?",
                      (pozycja, plan.run_id))
        a.con.commit()
        dlg = ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
        assert dlg.opis.text() == i18n.t(opis)
        assert dlg.head.text() == i18n.t_plural("objchg.head_resume_change", 1,
                                                run_id=plan.run_id, canon="NGC2632",
                                                card="NGC 2632")
        assert dlg.action_btn.isHidden() and not dlg.undo_btn.isHidden()
        dlg.reject()


def test_lista_przerwanych_cofanie_w_toku_i_zapisany_z_bledem_pozycji(archiwum):
    """Przerwane = `staged`, `undoing` albo `applied` z pozycją `failed`; `applied` bez `failed`
    i `undone` - nie. „Dokończ” liczy pozycje wyłącznie przy `staged` (cofanie zapisu nie wznawia)."""
    from horreum.gui.object_change_dialog import policz_plan
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    plan, _ = policz_plan(a.con, [fa], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    run = plan.run_id

    def stan(status, pozycja="pending"):
        a.con.execute("UPDATE object_change_run SET status = ? WHERE run_id = ?", (status, run))
        a.con.execute("UPDATE pending_object_change SET status = ? WHERE run_id = ?",
                      (pozycja, run))
        a.con.commit()
        widok = queries.object_change_run_view(a.con, run)
        return queries.interrupted_object_change_runs(a.con), widok["pending"], widok["can_finish"]
    assert stan("undoing", "applied") == ([run], 0, False)
    assert stan("applied", "failed") == ([run], 0, False)
    assert stan("applied", "blocked") == ([], 0, False)
    assert queries.object_change_run_view(a.con, "nie-ma") is None


# ═══════════════════════════════════════════════ Dom: przeniesienie, nie przemianowanie


def test_Dom_mowi_o_przeniesieniu_do_folderu_obiektu_gdy_relokacja_ma_powod_gestu():
    from horreum.gui.home import POWOD_COFNIECIA_ZMIANY, POWOD_ZMIANY_OBIEKTU, zdanie_gestu
    # powody - te, które klinga zapisu dokłada do ładunku `location.renamed`
    assert (POWOD_ZMIANY_OBIEKTU, POWOD_COFNIECIA_ZMIANY) == ("object_change", "object_change_undo")
    # Gest zapisu: 4 relokacje gestu, 1 powrót pliku z kartą odbitą (ten sam ts) - netto 3; z nich
    # folder zmieniły 2 (trzecia to nowa nazwa w tym samym folderze), więc „przeniesiono” mówi o 2.
    gest = {"verbs": {"location.renamed": 5, "object.assigned": 3, "header.refreshed": 3}, "n": 11,
            "reasons": {"location.renamed": {POWOD_ZMIANY_OBIEKTU: 4, POWOD_COFNIECIA_ZMIANY: 1}},
            "relocated_dirs": {POWOD_ZMIANY_OBIEKTU: 3, POWOD_COFNIECIA_ZMIANY: 1}}
    assert zdanie_gestu(gest) == i18n.t_plural("home.gest.object_relocated", 2)
    # same nowe nazwy w tym samym folderze - bez „przeniesiono”
    tylko_nazwy = dict(gest, relocated_dirs={})
    assert zdanie_gestu(tylko_nazwy) == i18n.t_plural("home.gest.object_files", 3)
    # read-model bez rozróżnienia katalogu - zdanie ogólne, nie „przeniesiono”
    bez_katalogow = {k: v for k, v in gest.items() if k != "relocated_dirs"}
    assert zdanie_gestu(bez_katalogow) == i18n.t_plural("home.gest.object_files", 3)
    cofniecie = {"verbs": {"location.renamed": 2, "object.restored": 2}, "n": 4,
                 "reasons": {"location.renamed": {POWOD_COFNIECIA_ZMIANY: 2}},
                 "relocated_dirs": {POWOD_COFNIECIA_ZMIANY: 2}}
    assert zdanie_gestu(cofniecie) == i18n.t_plural("home.gest.object_relocated_back", 2)
    # zwykły rename z panelu „Nazwy” zostaje przemianowaniem
    assert zdanie_gestu({"verbs": {"location.renamed": 2}, "n": 2, "reasons": {}}) == \
        i18n.t_plural("home.gest.location_renamed", 2)
    # read-model bez powodów (sprzed fali) - zdanie jak dotąd
    assert zdanie_gestu({"verbs": {"location.renamed": 2}, "n": 2}) == \
        i18n.t_plural("home.gest.location_renamed", 2)


# ═══════════════════════════════════════════════ wybierak „Zmień obiekt…”: pusty wynik szukania

def _obiekt_z_klatka(con, canon, sha):
    """Obiekt biblioteki z jedną klatką light (lista wybieraka = `library_objects`, `JOIN frame`)."""
    from horreum.resolve.catalog import catalog_label
    oid, _ = repo.upsert_object(con, canon=canon, catalog=catalog_label(canon), kind="deep_sky",
                                now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits", camera_id=None,
                               now=NOW)
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source="header", now=NOW)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wybierak_pusty_wynik_PROWADZI_do_pola_nazwy_i_mowi_ze_zalozy_obiekt(qapp, con, lang):
    """Wizytacja bv: „M 44” (NGC2632 - biblioteka go nie ma) dawało listę „(żaden obiekt nie
    pasuje…)” i milczące pole nazwy niżej - Zdzin utknął. Fraza bez trafień przechodzi do pola
    nazwy, zdanie pod listą mówi gdzie, zdanie na żywo - że zapis ZAŁOŻY obiekt, a akcja się
    zapala. Fraza znów z trafieniami oddaje pole; wpisu usera okno nie nadpisuje (mówi, gdzie
    wpisać). Pisanie w polu - prawdziwymi klawiszami (`textEdited`)."""
    from PySide6.QtTest import QTest
    from horreum.gui.assign_dialog import AssignObjectDialog
    i18n.set_lang(lang)
    _obiekt_z_klatka(con, "NGC3034", "sha-w-1")
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=2)
    assert dlg.search_hint.isHidden()
    dlg.search.setText("M 44")
    assert dlg.combo.count() == 1 and dlg.combo.itemData(0) is None       # lista pusta
    assert dlg.designation.text() == "M 44"
    assert not dlg.search_hint.isHidden()
    assert dlg.search_hint.text() == i18n.t("assign.search_moved")
    assert dlg.canon_preview.text() == (
        i18n.t("assign.canon_preview", text="M 44", canon="NGC2632", header="NGC 2632")
        + i18n.t("assign.creates_object"))
    assert dlg.accept_btn.isEnabled()
    dlg._validate_and_accept()
    assert dlg.selected[0] == "NGC2632"

    dlg = AssignObjectDialog(con, object_raw=None, frame_count=2)
    dlg.search.setText("M 44")
    dlg.search.setText("NGC 3034")                     # znów trafia - pole oddane
    assert dlg.designation.text() == "" and dlg.search_hint.isHidden()
    assert dlg.combo.currentData()[1] == "NGC3034"    # jedno trafienie = preselekcja (AR-98)
    QTest.keyClicks(dlg.designation, "NGC 3034")       # obiekt ISTNIEJĄCY - bez noty o założeniu
    assert dlg.canon_preview.text() == i18n.t("assign.canon_preview", text="NGC 3034",
                                              canon="NGC3034", header="NGC 3034")
    dlg.search.setText("M 44")                         # wpis usera zostaje
    assert dlg.designation.text() == "NGC 3034"
    assert dlg.search_hint.text() == i18n.t("assign.search_to_field")
    dlg.reject()


def test_Enter_w_szukajce_po_przeniesieniu_NIE_zaklada_obiektu_prawdziwym_klawiszem(qapp, con):
    """Zmierzone natywnie: „NGC 1952” + Enter → 43 klatki przypisane, obiekt założony.
    Fraza przeniesiona do pola nazwy, która ZAŁOŻY obiekt: Enter w szukajce przenosi
    fokus do pola nazwy z zaznaczoną treścią - zero zapisu; przycisk mówi, że założy obiekt; Enter
    w polu nazwy zatwierdza. Jedno trafienie listy + Enter (AR-98) zatwierdza jak dotąd."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from horreum.gui.assign_dialog import AssignObjectDialog
    _obiekt_z_klatka(con, "NGC3034", "sha-e-1")
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=2)
    akcja = dlg.accept_btn.text()
    dlg.show()
    dlg.search.setFocus()
    QTest.keyClicks(dlg.search, "M 44")
    assert dlg.designation.text() == "M 44"
    assert dlg.accept_btn.text() == i18n.t("assign.create_btn", canon="NGC2632", action=akcja)
    QTest.keyClick(dlg.search, Qt.Key_Return)
    assert dlg.result() != QDialog.Accepted and dlg.selected is None and dlg.isVisible()
    assert dlg.focusWidget() is dlg.designation and dlg.designation.selectedText() == "M 44"
    QTest.keyClick(dlg.designation, Qt.Key_Return)
    assert dlg.result() == QDialog.Accepted and dlg.selected[0] == "NGC2632"
    dlg.close()

    dlg = AssignObjectDialog(con, object_raw=None, frame_count=2)
    dlg.show()
    dlg.search.setFocus()
    QTest.keyClicks(dlg.search, "M 44")
    QTest.keyClick(dlg.search, Qt.Key_Backspace)        # „M 4” - bez trafień, dalej przeniesiona
    dlg.search.clear()                                  # pole oddane - napis przycisku wraca
    assert dlg.designation.text() == "" and dlg.accept_btn.text() == akcja
    QTest.keyClicks(dlg.search, "NGC 3034")             # AR-98: jedno trafienie + Enter
    QTest.keyClick(dlg.search, Qt.Key_Return)
    assert dlg.result() == QDialog.Accepted and dlg.selected[0] == "NGC3034"
    dlg.close()


def test_pelne_oznaczenie_bez_trafienia_DOKLADNEGO_przechodzi_do_pola_nazwy(qapp, con):
    """„M 1” trafiało prefiksem cudzy obiekt (alias M106 przy NGC4258), fraza
    nie szła do pola, a jedno trafienie stawało się preselekcją - wybór obiektu, którego nikt nie
    nazwał. Pełne oznaczenie bez trafienia dokładnego: zdanie „nie ma na liście”, fraza w polu
    nazwy, trafienia prefiksem zostają na liście BEZ wyboru; wybór z listy ręką oddaje pole."""
    from horreum.gui.assign_dialog import AssignObjectDialog
    _obiekt_z_klatka(con, "NGC4258", "sha-p-1")
    dlg = AssignObjectDialog(con, object_raw=None, frame_count=2)
    dlg.search.setText("M 1")
    assert [dlg.combo.itemData(i)[1] for i in range(1, dlg.combo.count())] == ["NGC4258"]
    assert dlg.combo.currentIndex() == 0                       # prefiks bez preselekcji
    assert dlg.designation.text() == "M 1" and not dlg.search_hint.isHidden()
    assert dlg.search_hint.text() == i18n.t("assign.search_moved")
    assert dlg.canon_preview.text().endswith(i18n.t("assign.creates_object"))
    dlg.combo.setCurrentIndex(1)
    dlg.combo.activated.emit(1)                                # wybór ręką z listy
    assert dlg.designation.text() == "" and dlg.combo.currentData()[1] == "NGC4258"
    dlg.search.setText("M 106")                                # trafienie dokładne - bez przeniesienia
    assert dlg.designation.text() == "" and dlg.search_hint.isHidden()
    assert dlg.combo.currentData()[1] == "NGC4258"
    dlg.reject()


# ═══════════════════════════════════════════════ elizja listy: rozróżnialna część zostaje

# Realne ścieżki z kopii żywej bazy (v36, 2026-10-13): mediana długości lightów pod LIGHTS to 99
# znaków, maksimum 135 (kometa). Pary różnią się sekundą w nazwie (Cr464) albo minutą (kometa).
_CR464 = [r"R:\ASTRO_\LIGHTS\Cr464\76EDPH_2600MM\CLS\Cr464_20230507_224301_LIGHT_CLS_5s_FLATGRP_"
          r"202305070_.fits",
          r"R:\ASTRO_\LIGHTS\Cr464\76EDPH_2600MM\CLS\Cr464_20230507_224307_LIGHT_CLS_5s_FLATGRP_"
          r"202305070_.fits"]
_KOMETA = [r"R:\ASTRO_\LIGHTS\_COMETS\C2023A3_Tsuchinshan-ATLAS\ASI2600MM\C2023A3_Tsuchinshan-"
           r"ATLAS_20241025_164324_LIGHT_R_60s_FLATGRP_NOFLAT_.fits",
           r"R:\ASTRO_\LIGHTS\_COMETS\C2023A3_Tsuchinshan-ATLAS\ASI2600MM\C2023A3_Tsuchinshan-"
           r"ATLAS_20241025_164435_LIGHT_R_60s_FLATGRP_NOFLAT_.fits"]
_APARAT = [r"R:\ASTRO_\LIGHTS\_COMETS\21P_Giacobini-Zinner\NOCONFIG\20181011_dsc3322.dng",
           r"R:\ASTRO_\LIGHTS\_COMETS\21P_Giacobini-Zinner\NOCONFIG\20181011_dsc3324.dng"]


def _pokazane(paths):
    from horreum.gui.object_change_dialog import glowa_sciezki, sciezka_pod_korzeniem
    return [(sciezka_pod_korzeniem(p, KORZEN), glowa_sciezki(p, KORZEN)) for p in paths]


def test_elizja_zostawia_czlon_obiektu_i_czas_z_nazwy_a_srodek_ginie(qapp):
    """Wizytacja bs/bt: `Qt.ElideMiddle` dawało identyczne wiersze („Cr464…202305070_.fits”) i ciął
    człon obiektu („NGC30…GHT_OSC”). Elizja rozróżniająca na szerokości, w której mieści się
    początek nazwy do sekundy: wiersze różne, „Plik dziś” różny od „Po zmianie”, człon obiektu
    widać. Falsyfikator: ta sama szerokość z `ElideMiddle` - wiersze identyczne."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics
    from horreum.gui.object_change_dialog import elizja_sciezki
    fm = QFontMetrics(QApplication.font())
    (a, ga), (b, gb) = _pokazane(_CR464)
    assert a[:ga] == r"LIGHTS\Cr464"                   # głowa = kategoria + folder obiektu
    szer = fm.horizontalAdvance("…\\Cr464_20230507_224301…") + 2
    assert fm.elidedText(a, Qt.ElideMiddle, szer) == fm.elidedText(b, Qt.ElideMiddle, szer)
    ea, eb = elizja_sciezki(fm, a, szer, ga), elizja_sciezki(fm, b, szer, gb)
    assert ea != eb and "224301" in ea and "224307" in eb
    assert fm.horizontalAdvance(ea) <= szer and fm.horizontalAdvance(eb) <= szer
    nowa = a.replace("Cr464", "NGC2632")
    from horreum.gui.object_change_dialog import glowa_sciezki
    en = elizja_sciezki(fm, nowa, szer, glowa_sciezki(KORZEN + "\\" + nowa, KORZEN))
    assert en != ea and "NGC2632" in en and "Cr464" in ea
    # szerzej: głowa wraca do kadru, ginie środek drzewa (zestaw, filtr)
    szer = fm.horizontalAdvance(a[:ga] + "\\…\\" + a.rsplit("\\", 1)[1]) + 2
    ea = elizja_sciezki(fm, a, szer, ga)
    assert ea.startswith(r"LIGHTS\Cr464" + "\\") and ea.endswith(a.rsplit("\\", 1)[1])
    assert "76EDPH" not in ea
    # kometa (najdłuższa ścieżka archiwum): pod kategorią, minuta w nazwie
    (k1, g1), (k2, g2) = _pokazane(_KOMETA)
    assert k1[:g1] == r"LIGHTS\_COMETS\C2023A3_Tsuchinshan-ATLAS"
    szer = fm.horizontalAdvance("…\\C2023A3_Tsuchinshan-ATLAS_20241025_1643…") + 2
    assert elizja_sciezki(fm, k1, szer, g1) != elizja_sciezki(fm, k2, szer, g2)
    # nazwa z aparatu nie niesie obiektu - głowa zostaje w kadrze
    (d1, h1), (d2, h2) = _pokazane(_APARAT)
    szer = fm.horizontalAdvance(d1[:h1] + "\\…\\20181011_dsc3322.dng") + 2
    e1, e2 = elizja_sciezki(fm, d1, szer, h1), elizja_sciezki(fm, d2, szer, h2)
    assert e1 != e2 and "21P_Giacobini-Zinner" in e1 and "dsc3322" in e1
    # węziej: kategoria ustępuje, folder obiektu zostaje (zrzut natywny 760 px gubił go cały)
    szer = fm.horizontalAdvance("…\\21P_Giacobini-Zinner\\…\\20181011_dsc3322.dng") + 2
    e1 = elizja_sciezki(fm, d1, szer, h1)
    assert e1.startswith("…\\21P_Giacobini-Zinner\\") and "LIGHTS" not in e1 and "dsc3322" in e1
    # mieści się - bez zmian
    assert elizja_sciezki(fm, a, fm.horizontalAdvance(a) + 1, ga) == a


def test_lista_przy_760px_rozroznia_wiersze_a_Po_zmianie_bez_przeniesien_jest_waska(
        qapp, con, rdzen):
    """Okno 760 px na realnych ścieżkach: tekst malowany przez delegata (`tekst_w_komorce`
    w prostokącie komórki) jest RÓŻNY w wierszach różniących się sekundą (Cr464, mediana długości
    archiwum) i między kolumnami każdego wiersza, a człon obiektu widać w obu kolumnach (także
    w najdłuższej ścieżce archiwum - kometa). Plan bez ani jednego przeniesienia („bez
    przeniesienia” w każdym wierszu) nie oddaje połowy szerokości kolumnie bez treści - „Po
    zmianie” bierze szerokość swojej treści."""
    from PySide6.QtWidgets import QHeaderView, QStyleOptionViewItem
    from horreum.gui.object_change_dialog import _GLOWA_ROLE, _COL_NOWA, _COL_STARA
    stare = _CR464 + _KOMETA
    nowe = ([p.replace("\\Cr464\\", "\\NGC2632\\").replace("\\Cr464_", "\\NGC2632_")
             for p in _CR464]
            + [p.replace("\\_COMETS\\C2023A3_Tsuchinshan-ATLAS\\", "\\NGC2632\\")
               .replace("\\C2023A3_Tsuchinshan-ATLAS_", "\\NGC2632_") for p in _KOMETA])
    items = tuple(dataclasses.replace(_pozycja(i + 1), old_path=s, new_path=n, mkdirs=())
                  for i, (s, n) in enumerate(zip(stare, nowe)))
    rdzen.plany = [_plan(items=items, skipped=())]
    dlg = _okno(qapp, con, frame_ids=range(1, 5))
    # 760 px wizytacji natywnej = 127 średnich znaków Segoe UI 9 pt (zmierzone 2026-10-13: średni
    # znak 6 px natywnie, 12 px offscreen) - okno w jednostkach fontu, nie w pikselach.
    dlg.resize(127 * dlg.fontMetrics().averageCharWidth(), 640)
    dlg.show()
    QCoreApplication.processEvents()
    tree = dlg.items_tree

    def malowane(wiersz, kolumna):
        index = tree.model().index(wiersz, kolumna)
        opt = QStyleOptionViewItem()
        opt.initFrom(tree)
        dlg._elizja.initStyleOption(opt, index)
        opt.rect = tree.visualRect(index)
        return dlg._elizja.tekst_w_komorce(opt, index.data(_GLOWA_ROLE))

    teksty = [[malowane(r, k) for k in (_COL_STARA, _COL_NOWA)] for r in range(4)]
    assert all(t != tree.topLevelItem(r).text(k)              # szerokość realnie wymusiła elizję
               for r, w in enumerate(teksty) for k, t in zip((_COL_STARA, _COL_NOWA), w))
    (s1, n1), (s2, n2), (k1, kn1), (k2, kn2) = teksty
    assert len({s1, n1, s2, n2}) == 4, teksty                  # wiersze i kolumny różne
    assert "Cr464" in s1 and "NGC2632" in n1 and all(s != n for s, n in teksty)
    assert "C2023A3" in k1 and "C2023A3" in k2 and "NGC2632" in kn1 and "NGC2632" in kn2
    dlg.reject()
    rdzen.plany = [_plan(items=tuple(dataclasses.replace(it, new_path=None) for it in items),
                         skipped=())]
    dlg = _okno(qapp, con, frame_ids=range(1, 5))
    hdr = dlg.items_tree.header()
    assert hdr.sectionResizeMode(_COL_NOWA) == QHeaderView.ResizeToContents
    assert hdr.sectionResizeMode(_COL_STARA) == QHeaderView.Stretch
    dlg.reject()


# ═══════════════════════════════════════════════ okno przebiegu: jeden język człowieka

@pytest.mark.parametrize("lang", ["pl", "en"])
def test_status_spadku_mowi_JEZYKIEM_CZLOWIEKA_a_szczegol_rdzenia_w_podpowiedzi(
        qapp, con, rdzen, lang):
    """Wizytacja bt: status wiersza mówił żargonem rdzenia („droga dotychczasowa: operacja
    add/str…”), a zdanie wyniku „drogą atomową” - dwa języki na jeden fakt. Teraz status i zdanie
    mówią „cały plik przepisany”, szczegół rdzenia jest w podpowiedzi, a uwaga dopisana przez
    rdzeń za spadkiem (`; …`) zostaje w statusie."""
    i18n.set_lang(lang)
    prefiks = writeback.PREFIKS_DROGI_ATOMOWEJ
    rdzen.wynik_commitu = _Wynik(
        "run-1", applied=[
            _fr(11, "applied", f"{prefiks}: operacja add/str na OBJECT - układ karty zostaje przy "
                               f"astropy; nagrobek ręki został", code=writeback.CODE_INPLACE_FALLBACK),
            _fr(12, "applied")], blocked=[], failed=[], skipped=[], commit_ids=(5,))
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    w = dlg.items_tree.topLevelItem(0)
    assert w.text(3) == (i18n.t("objchg.st.done") + i18n.t(
        "objchg.st.reason", reason=i18n.t("objchg.st.rewritten") + "; nagrobek ręki został"))
    assert prefiks not in w.text(3) and "add/str" not in w.text(3)
    assert i18n.t("objchg.st.detail_tip",
                  detail="operacja add/str na OBJECT - układ karty zostaje przy astropy") \
        in w.toolTip(3)
    assert i18n.t("wb.inplace_fallback", n=1) in dlg.status.text()
    # uwaga rdzenia za spadkiem zostaje w zdaniu (Z27, jeden podział z oknami kart)
    assert i18n.t("objchg.res.notes", n=1, note="nagrobek ręki został") in dlg.status.text()
    assert prefiks not in dlg.status.text() and "add/str" not in dlg.status.text()
    dlg.reject()


def test_status_spadku_z_BAZY_rozpoznaje_prefiks_rdzenia():
    """Wiersz przebiegu z bazy (wejście z Porządków) nie niesie kodu wyniku - spadek rozpoznaje
    prefiks rdzenia; wynik biegu bez kodu zostaje uwagą (jak zdanie wyniku)."""
    from horreum.gui.wb_worker import status_pozycji
    prefiks = writeback.PREFIKS_DROGI_ATOMOWEJ
    stan = i18n.t("objchg.st.done")
    status, tip = status_pozycji(stan, f"{prefiks}: karta OBJECT występuje 2 razy", z_bazy=True)
    assert status == stan + i18n.t("objchg.st.reason", reason=i18n.t("objchg.st.rewritten"))
    assert "występuje 2 razy" in tip
    status, tip = status_pozycji(stan, f"{prefiks}: x")
    assert status == tip == stan + i18n.t("objchg.st.reason", reason=f"{prefiks}: x")
    assert status_pozycji(stan, None) == (stan, stan)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_status_spadku_po_KODZIE_powodu_szczegol_z_parametru_a_uwagi_w_jezyku_UI(lang):
    """AR-141: powód z kodem `inplace_fallback` (wynik biegu i wiersz bazy po 0041) rozpoznaje spadek
    po KODZIE, bez prefiksu prozy; szczegół to parametr `detail` (także ze średnikiem w środku -
    dawny podział prozy ciął go na pół), uwagi to lista `notes` w języku UI."""
    from horreum.gui.wb_worker import status_pozycji
    from horreum.item_reasons import PowodPozycji, dopisz
    i18n.set_lang(lang)
    szczegol = "karta OBJECT występuje 2 razy; druga w HDU 1"
    powod = dopisz(PowodPozycji(f"{writeback.PREFIKS_DROGI_ATOMOWEJ}: {szczegol}",
                                "inplace_fallback", detail=szczegol),
                   PowodPozycji("nowsza decyzja ręki o obiekcie klatki zostaje", "hand_newer"))
    stan = i18n.t("objchg.st.done")
    oczekiwany = stan + i18n.t("objchg.st.reason", reason=i18n.t("objchg.st.rewritten") + "; "
                               + i18n.t("objchg.item.hand_newer"))
    for z_bazy in (True, False):
        status, tip = status_pozycji(stan, powod, z_bazy=z_bazy)
        assert status == oczekiwany
        assert tip == status + "\n" + i18n.t("objchg.st.detail_tip", detail=szczegol)
    if lang == "en":
        assert not set(oczekiwany) & set("„ąćęłńóśźż"), oczekiwany


_PROZA_ZAPASU = "zdanie rdzenia zachowane w bazie; druga część"


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("kod, args", [
    ("busy", '{"winerror": 32}'),                                  # brak pola `tries`
    ("inplace_fallback", "{}"),                                    # brak `detail`
    ("inplace_fallback", '{"detail": 7}'),                         # `detail` nie-tekst
    ("inplace_fallback", '{"detail": "x", "notes": "nie-lista"}'),  # uwagi nie-lista
    ("copy_gone", '{"notes": 5}'),                                 # uwagi nie-lista
    ("copy_gone", '{"notes": [{"foo": 1}]}'),                      # uwaga obcego kształtu
    ("copy_gone", '{"notes": [7]}'),                               # uwaga nie-powód
    ("db_refused", '{"inner": {"foo": 1}}'),                       # zagnieżdżenie obcego kształtu
    ("db_refused", '{"inner": {"text": 1, "code": "x", "args": {}}}'),  # tekst nie-tekst
    ("db_refused", '{"inner": {"text": "t", "code": "copy_gone", "args": []}}'),  # args nie-obiekt
    ("unreachable", '{"detail": [1, 2]}'),                         # parametr złego typu
    ("copies", '{"n": "dwa"}'),                                    # `n` wpisu mnogiego nie-liczbą
    ("copies", '{"n": true}'),
    ("copy_gone", "[1]"),                                          # JSON nie-obiekt
    ("copy_gone", "{zly"),                                         # JSON uszkodzony
    ("kod_spoza_zbioru", "{}"),                                    # kod nieznany
])
def test_powod_z_BAZY_spoza_kodeka_mowi_zachowana_proza_bez_wyjatku(kod, args, lang):
    """AR-141 (S1, K2): odczyt i zdanie powodu z bazy są TOTALNE. Wiersz, który przeszedł CHECK 0041
    (albo jego kopia zapisana serwisowo / innym programem na tym samym numerze schematu), z
    parametrami, które nie wypełniają wpisu katalogu, mówi zachowaną prozą `reason` - zdanie okna,
    status listy i podział spadku bez `KeyError`. Falsyfikator: render bez sprawdzenia pól -
    `KeyError: 'tries'`/`'detail'` w oknie."""
    from horreum import item_reasons
    from horreum.gui.wb_worker import podziel_powod_spadku, status_pozycji, tekst_powodu
    i18n.set_lang(lang)
    powod = item_reasons.z_bazy(_PROZA_ZAPASU, kod, args)
    assert str(powod) == _PROZA_ZAPASU
    assert tekst_powodu(powod) == czytelny(_PROZA_ZAPASU)
    stan = i18n.t("objchg.st.blocked")
    status, _ = status_pozycji(stan, powod, z_bazy=True)
    assert status == stan + i18n.t("objchg.st.reason", reason=czytelny(_PROZA_ZAPASU))
    assert podziel_powod_spadku(powod) == ("zdanie rdzenia zachowane w bazie", "druga część")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_okno_z_PORZADKOW_na_wierszu_spoza_kodeka_mowi_proza(qapp, archiwum, lang):
    """S1 na prawdziwej bazie: pozycje z kodem i parametrami, które przeszły CHECK 0041, ale nie
    wypełniają wpisu (`busy` bez `tries`, `inplace_fallback` bez `detail`) - okno z Porządków się
    otwiera, a status mówi zachowaną prozą rdzenia (zamiast `KeyError` w konstruktorze okna)."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog, policz_plan
    a = archiwum
    i18n.set_lang(lang)
    fa, pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_b.fits", obj="NGC 3034", seed=2,
                    date="2022-03-26T21:31:00")
    plan, _ = policz_plan(a.con, [fa, fb], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    for p, kod, args in ((pa, "busy", '{"winerror": 32}'), (pb, "inplace_fallback", "{}")):
        a.con.execute("UPDATE pending_object_change SET status = 'blocked', reason = ?, "
                      "reason_code = ?, reason_args = ? WHERE old_path = ?",
                      (f"proza {p.name}", kod, args, str(p)))
    a.con.commit()
    dlg = ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
    status = {r[0]: r[3] for r in _teksty(dlg.items_tree)}
    zablok = i18n.t("objchg.st.blocked")
    for p in (pa, pb):
        assert status[str(p)] == zablok + i18n.t("objchg.st.reason", reason=f"proza {p.name}")
    dlg.reject()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_okno_z_PORZADKOW_mowi_powod_pozycji_z_BAZY_w_jezyku_UI(qapp, archiwum, lang):
    """AR-141 na PRAWDZIWYM sterowniku: powód pozycji leży w bazie z kodem (0041), więc okno
    otwarte na przebiegu z Porządków mówi go w języku UI - plik zmieniony od skanu, cel zajęty
    na dysku (powód warstwy renamu), karta dopisana drogą atomową - plik bez zapasu nagłówka,
    AR-118 (spadek po kodzie, szczegół w podpowiedzi). ZŁOTE PL: zdanie okna ==
    `czytelny_powod(proza rdzenia)` znak w znak. Wiersz bez kodu (sprzed 0041) mówi prozą jak
    dotąd. Falsyfikator: `status_pozycji` bez gałęzi kodu - EN po polsku."""
    import os as _os
    from horreum.gui.object_change_dialog import ObjectChangeDialog, policz_plan
    from horreum.gui.wb_worker import status_pozycji
    a = archiwum
    i18n.set_lang(lang)
    fa, pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", date="2022-03-26T21:31:00", seed=2,
                    bez_zapasu=True)
    fc, pc = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_c.fits", obj="NGC 3034", seed=3,
                    date="2022-03-26T21:32:00")
    plan, _ = policz_plan(a.con, [fa, fb, fc], target=queries.object_target(a.con, "M 44"))
    repo.stage_object_change(a.con, plan=plan, now=NOW)
    st = _os.stat(pa)
    _os.utime(pa, (st.st_atime, st.st_mtime + 10))              # zmiana pliku po skanie
    cel_c = next(it.new_path for it in plan.items if it.frame_id == fc)
    _os.makedirs(_os.path.dirname(cel_c), exist_ok=True)
    with open(cel_c, "wb") as f:                                 # cel zajęty na dysku
        f.write(b"obcy")
    writeback.commit_object_change(a.con, plan.run_id, now=NOW)
    wiersze = {r["old_path"]: r for r in a.con.execute(
        "SELECT old_path, status, reason, reason_code FROM pending_object_change")}
    assert {(wiersze[str(p)]["status"], wiersze[str(p)]["reason_code"]) for p in (pa, pb, pc)} == {
        ("blocked", "changed_since_scan"), ("applied", "inplace_fallback"), ("blocked", "dst_exists")}
    dlg = ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
    status = {r[0]: r[3] for r in _teksty(dlg.items_tree)}
    tip = {dlg.items_tree.topLevelItem(i).text(0): dlg.items_tree.topLevelItem(i).toolTip(3)
           for i in range(dlg.items_tree.topLevelItemCount())}
    zablok = i18n.t("objchg.st.blocked")
    assert status[str(pa)] == zablok + i18n.t("objchg.st.reason",
                                              reason=i18n.t("objchg.item.changed_since_scan"))
    assert status[str(pc)] == zablok + i18n.t("objchg.st.reason",
                                              reason=i18n.t("objchg.item.dst_exists"))
    assert status[str(pb)] == i18n.t("objchg.st.done") + i18n.t(
        "objchg.st.reason", reason=i18n.t("objchg.st.rewritten"))
    assert i18n.t("objchg.st.detail_tip", detail="").rstrip() in tip[str(pb)]
    if lang == "pl":                                             # złote: PL okna = proza rdzenia
        for p in (pa, pc):
            assert status[str(p)] == zablok + i18n.t(
                "objchg.st.reason", reason=czytelny(wiersze[str(p)]["reason"]))
    else:
        assert not any(set(s) & set("ąćęłńóśźż") for s in status.values()), status
    dlg.reject()
    # wiersz bez kodu (sprzed 0041) - proza jak dotąd
    a.con.execute("UPDATE pending_object_change SET reason_code = NULL, reason_args = NULL "
                  "WHERE old_path = ?", (str(pa),))
    a.con.commit()
    widok = queries.object_change_run_view(a.con, plan.run_id)
    (bez_kodu,) = [it for it in widok["items"] if it["old_path"] == str(pa)]
    assert type(bez_kodu["reason"]) is str
    assert status_pozycji(zablok, bez_kodu["reason"], z_bazy=True)[0] == zablok + i18n.t(
        "objchg.st.reason", reason=czytelny(wiersze[str(pa)]["reason"]))


def _blad_os(klasa, winerror, komunikat, sciezka=None):
    """Powód tak, jak składa go rdzeń z wyjątku systemu (`f"{type(exc).__name__}: {exc}"`)."""
    exc = klasa(None, komunikat, sciezka, winerror)
    return f"{type(exc).__name__}: {exc}"


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_czytelny_powod_plik_zajety_slowami_a_sciezki_bez_podwojnych_ukosnikow(lang):
    """Wizytacja bt/bv: surowy `PermissionError: [WinError 32]` z podwojonymi ukośnikami w zdaniu
    i statusie. Po AR-125 przeniesienie mówi już „plik zajęty przez inny program”, ale zapis karty
    w pliku zajętym dalej oddawał surowy wyjątek (sonda na prawdziwym rdzeniu). Plik zajęty -
    zdaniem okna, ścieżka zajętego pliku w nawiasie; ścieżka z `repr` - bez podwojeń; reszta
    zdania (` · przebieg …`, ` - przerwano na żądanie`) nietknięta - komunikat systemu kończy
    kropka (`ctypes.WinError`) albo ścieżka (`str(OSError)`), nie najbliższy separator (Z28)."""
    from horreum.gui.wb_worker import czytelny_powod
    i18n.set_lang(lang)
    zajety_txt = i18n.t("objchg.reason.busy")
    zajety = _blad_os(PermissionError, 32, "Proces nie może uzyskać dostępu do pliku, ponieważ jest "
                                           "on używany przez inny proces", r"R:\ASTRO_\LIGHTS\a.fits")
    assert "\\\\" in zajety and "[WinError 32]" in zajety           # surowy zapis z rdzenia
    zdanie = f"karta odbita bez zapisu: {zajety} · przebieg abc"
    assert czytelny_powod(zdanie) == (f"karta odbita bez zapisu: {zajety_txt} "
                                      f"(R:\\ASTRO_\\LIGHTS\\a.fits) · przebieg abc")
    # forma `ctypes.WinError` (rdzeń: podmiana pliku) - bez ścieżki, komunikat kończy kropka
    ctypes_ = "PermissionError: [WinError 32] Proces nie może uzyskać dostępu do pliku."
    assert czytelny_powod(f"{ctypes_} - przerwano na żądanie") == (
        f"{zajety_txt} - przerwano na żądanie")
    bez_sciezki = _blad_os(PermissionError, 33, "Proces nie ma dostępu do pliku")
    assert czytelny_powod(f"{bez_sciezki}; dalej") == f"{zajety_txt}; dalej"
    assert czytelny_powod(f"{bez_sciezki} - przerwano na żądanie") == (
        f"{zajety_txt} - przerwano na żądanie")
    inny = _blad_os(FileNotFoundError, 2, "Nie można odnaleźć określonego pliku",
                    r"R:\ASTRO_\LIGHTS\b.fits")
    assert czytelny_powod(inny) == inny.replace("\\\\", "\\")
    assert "\\\\" not in czytelny_powod(inny)
    assert czytelny_powod("karta OBJECT = 'NGC 2632'") == "karta OBJECT = 'NGC 2632'"
    assert czytelny_powod(None) is None


@pytest.mark.skipif(not hasattr(__import__("ctypes"), "WinDLL"), reason="blokada pliku - Windows")
def test_plik_ZAJETY_przy_zapisie_karty_mowi_zdaniem_okna_na_PRAWDZIWYM_rdzeniu(qapp, archiwum):
    """Sonda: „Uzgodnij” z samą kartą (plik w folderze obiektu), plik otwarty przez inny
    program bez współdzielenia - rdzeń odbija kartę surowym `PermissionError: [WinError 32]`
    (przeniesienie mówi już po ludzku od AR-125). Status wiersza i zdanie wyniku mówią zdaniem
    okna; surowego wyjątku na ekranie nie ma."""
    import ctypes
    a = archiwum
    fid, p = a.fits(r"LIGHTS\NGC3031\RC6\OSC\NGC3031_20220326_220000_LIGHT_OSC_30s.fits",
                    obj="NGC 3034", canon="NGC3031")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    uchwyt = k32.CreateFileW(str(p), 0x80000000, 0, None, 3, 0x80, None)   # odczyt, bez współdzielenia
    try:
        dlg = _okno(qapp, a.con, target=None, frame_ids=[fid])
        dlg.action_btn.click()
        status = dlg.items_tree.topLevelItem(0).text(3)
        assert i18n.t("objchg.reason.busy") in status, status
        assert "PermissionError" not in status and "WinError" not in status
        assert "PermissionError" not in dlg.status.text()
        dlg.reject()
    finally:
        k32.CloseHandle(ctypes.c_void_p(uchwyt))


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_naglowek_Uzgodnij_NAZYWA_obiekty_klatek(qapp, archiwum, lang):
    """Wizytacja bt: nagłówek „Uzgodnij” mówił „z obiektem, który już mają”, nie mówiąc z jakim.
    Obiekty z bazy, alfabetycznie; ponad trzy - reszta liczbą."""
    from horreum.gui.object_change_dialog import lista_obiektow
    i18n.set_lang(lang)
    a = archiwum
    fa, _ = a.fits(r"LIGHTS\NGC3031\RC6\OSC\x.fits", obj="NGC 3034", canon="NGC3034", seed=1)
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\y.fits", obj="NGC 3031", canon="NGC3031", seed=2,
                   date="2022-03-26T21:31:00")
    dlg = _okno(qapp, a.con, target=None, frame_ids=[fa, fb])
    assert dlg.head.text() == (i18n.t_plural("objchg.head_align", 2)
                               + i18n.t_plural("objchg.head_objects", 2,
                                               objects="NGC3031, NGC3034"))
    dlg.reject()
    dlg = _okno(qapp, a.con, target=None, frame_ids=[fa])
    assert dlg.head.text().endswith(i18n.t_plural("objchg.head_objects", 1, objects="NGC3034"))
    dlg.reject()
    assert lista_obiektow(["Sh2-229", "IC405", "NGC3034", "M1x", "Cr464"]) == (
        "Cr464, IC405, M1x" + i18n.t_plural("objchg.head_objects_more", 2))


def test_odmiana_kluczy_naglowka_i_liczby_wyniku_PL_i_EN():
    """Odmiana przez `t_plural` (1, 2-4, 5, 12-14, 22) w kluczach nagłówka; liczba wyniku w formie
    „etykieta: N” - bez odmiany, więc poprawna dla każdego N (wspólna gramatyka zdania wyniku
    składa ten człon przez `t`)."""
    i18n.set_lang("pl")
    assert [i18n.t_plural("objchg.head_objects_more", n) for n in (1, 2, 5, 12, 22)] == [
        " i 1 inny", " i 2 inne", " i 5 innych", " i 12 innych", " i 22 inne"]
    assert [i18n.t_plural("objchg.head_objects", n, objects="X") for n in (1, 2, 5)] == [
        " Obiekt w bazie: X.", " Obiekty w bazie (2): X.", " Obiekty w bazie (5): X."]
    assert [i18n.t("objchg.res.applied", n=n) for n in (1, 2, 5, 12, 22)] == [
        f"zmienione pozycje: {n}" for n in (1, 2, 5, 12, 22)]
    assert i18n.t("objchg.res.undone", n=1) == "cofnięte pozycje: 1"
    i18n.set_lang("en")
    assert [i18n.t_plural("objchg.head_objects_more", n) for n in (1, 2, 22)] == [
        " and 1 more", " and 2 more", " and 22 more"]
    assert i18n.t_plural("objchg.head_objects", 1, objects="X") == " Object in the database: X."
    assert i18n.t("objchg.res.applied", n=1) == "items changed: 1"
    assert i18n.t("objchg.res.undone", n=2) == "items undone: 2"
    # EN bez polskich znaków cudzysłowu i słów w nowych kluczach okna
    for k in ("objchg.st.rewritten", "objchg.st.detail_tip", "objchg.reason.busy",
              "wb.inplace_fallback", "assign.search_moved", "assign.search_to_field",
              "assign.creates_object", "objchg.head_resume_change", "objchg.head_resume_align"):
        tekst = str(CATALOG[k]["en"])
        assert not set(tekst) & set("„ąćęłńóśźż"), k


_ODMIANA_WB = {   # n → (PL zapisane, zablokowane, błędy, pominięte, przywrócone)
    1: ("1 zapisany", "1 zablokowany", "1 błąd", "1 pominięty", "1 przywrócony"),
    2: ("2 zapisane", "2 zablokowane", "2 błędy", "2 pominięte", "2 przywrócone"),
    5: ("5 zapisanych", "5 zablokowanych", "5 błędów", "5 pominiętych", "5 przywróconych"),
    12: ("12 zapisanych", "12 zablokowanych", "12 błędów", "12 pominiętych", "12 przywróconych"),
    22: ("22 zapisane", "22 zablokowane", "22 błędy", "22 pominięte", "22 przywrócone")}


@pytest.mark.parametrize("n", sorted(_ODMIANA_WB))
def test_zdanie_wyniku_zapisu_ODMIENIA_liczby_PL_i_EN(n):
    """„1 zapisanych · 1 zablokowanych · 1 błędów” - wspólna gramatyka zdania wyniku
    (`wb_worker.zdanie_wyniku_zapisu`, `zdanie_undo_kart`) składała człony przez `t`. Teraz wpisy
    mnogie idą przez `t_plural` (`_liczba`), na PRAWDZIWYM zdaniu, 1, 2-4, 5, 12-14 i 22; prosty
    klucz (`objchg.res.applied`, „etykieta: N”) dalej przez `t`."""
    from horreum.gui.wb_worker import zdanie_undo_kart, zdanie_wyniku_zapisu
    pliki = [_fr(i, "applied") for i in range(n)]
    commit = writeback.CommitResult("r", 3, pliki, pliki, pliki, pliki)
    cofniecie = writeback.UndoResult(3, pliki, [], [])
    i18n.set_lang("pl")
    zapisane, zablokowane, bledy, pominiete, przywrocone = _ODMIANA_WB[n]
    assert zdanie_wyniku_zapisu(commit, "grid.wb.applied") == " · ".join(
        (zapisane, zablokowane, bledy, pominiete))
    assert zdanie_undo_kart(cofniecie) == przywrocone
    assert zdanie_wyniku_zapisu(commit, "objchg.res.applied").startswith(
        f"zmienione pozycje: {n} · ")
    i18n.set_lang("en")
    s = "" if n == 1 else "s"
    assert zdanie_wyniku_zapisu(commit, "grid.wb.applied") == (
        f"{n} applied · {n} blocked · {n} error{s} · {n} skipped")
    assert zdanie_undo_kart(cofniecie) == f"{n} restored"


# ═══════════════════════════════════════════════ powody pominięć w języku UI (kody planera)

def _wywolania_odmowy():
    """Kod → zbiór nazw parametrów z KAŻDEGO `_Odmowa(...)` w `object_change.py` (AST)."""
    import ast
    import inspect
    drzewo = ast.parse(inspect.getsource(oc))
    out = {}
    for w in ast.walk(drzewo):
        if (isinstance(w, ast.Call) and isinstance(w.func, ast.Name) and w.func.id == "_Odmowa"
                and w.args):
            a = w.args[0]
            kod = (a.value if isinstance(a, ast.Constant)
                   else oc.SKIP_UNCHANGED if isinstance(a, ast.Name) and a.id == "SKIP_UNCHANGED"
                   else None)
            assert kod is not None, ast.dump(a)
            out.setdefault(kod, set()).update(k.arg for k in w.keywords)
    return out


def test_KAZDY_kod_pominiecia_ma_zdanie_PL_i_EN_z_parametrami_planera():
    """Mapa kodów: każde `_Odmowa` planera niesie kod z `SKIP_CODES` (i każdy kod jest użyty), każdy
    kod ma `objchg.skip.<kod>` w obu językach z tymi samymi polami, a pola zdania to parametry,
    które planer podaje. Bramka dla kodów, których fixture nie zbuduje (izolacja, `bad_target`,
    `card_comment`, `variant_name`, `unchanged`)."""
    import string
    uzyte = _wywolania_odmowy()
    assert set(uzyte) == oc.SKIP_CODES
    for kod, parametry in uzyte.items():
        wpis = CATALOG[f"objchg.skip.{kod}"]
        pola = {j: {f for _, f, _, _ in string.Formatter().parse(wpis[j]) if f}
                for j in ("pl", "en")}
        assert pola["pl"] == pola["en"], kod
        assert pola["pl"] <= parametry, (kod, pola["pl"], parametry)
        assert not set(wpis["en"]) & set("„ąćęłńóśźż"), kod


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_powody_pominiec_w_jezyku_UI_na_PRAWDZIWYM_planerze_i_w_oknie(qapp, tmp_path, monkeypatch,
                                                                     lang):
    """Powody pominięć były tylko po polsku w UI EN. Prawdziwy planer na fixture
    planera: każdy rodzaj pominięcia, który da się zbudować, mówi zdaniem `objchg.skip.<kod>`
    w języku UI z parametrami planera (para stosu - z pominiętą połową też w języku UI); szczegół
    błędu systemu bez podwojonych ukośników. W oknie - lista pominięć tym samym zdaniem."""
    from test_object_change_plan import _Archiwum as _ArchPlanu, _stos
    from horreum.gui.object_change_dialog import ObjectChangeDialog, tekst_pominiecia
    from horreum.scan import Card
    a = _ArchPlanu(tmp_path)
    i18n.set_lang(lang)
    plany = []
    # stan klatki (tryb „Uzgodnij”)
    bez_mtime = a.klatka(r"LIGHTS\X\cam\1.fits", canon="NGC224", mtime=None)
    dwie = a.klatka(r"LIGHTS\X\cam\2.fits", canon="NGC224")
    repo.add_location(a.con, frame_id=dwie, volume="VOL", path=a.sciezka(r"LIGHTS\Y\c\2.fits"),
                      mtime="m", now=NOW)
    dark = a.klatka(r"CALIBRATION\darks\d.fits", kind="dark")
    wycofana = a.klatka(r"LIGHTS\X\cam\3.fits", canon="NGC224")
    a.con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, wycofana))
    zastapiona = a.klatka(r"LIGHTS\X\cam\6.fits", canon="NGC224")
    a.con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (wycofana, zastapiona))
    bez = a.klatka(r"LIGHTS\X\cam\4.fits")
    poza = a.klatka(r"Inne\X\cam\5.fits", canon="NGC224")
    znikla = a.klatka(r"LIGHTS\X\cam\7.fits", canon="NGC224")
    a.con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (znikla,))
    stan = [bez_mtime, dwie, dark, wycofana, zastapiona, bez, poza, znikla]
    plany.append(a.plan(stan))
    # folder komety o nazwie innego obiektu
    a.obiekt("C/2025 A6 (Foo_Bar)", "comet")
    plany.append(a.plan([a.klatka(r"LIGHTS\_COMETS\X\cam\1.ARW", canon="C/2025 A6 (Foo Bar)",
                                  okind="comet", filetype="raw", source="comet")]))
    # karta odbita bramką bazy
    suma = a.klatka(r"LIGHTS\S\cam\1.fits", canon="NGC224", card="M 31",
                    extra_cards=[Card("CHECKSUM", 0, "abc", None, "str", None)])
    plany.append(a.plan([suma], target=queries.object_target(a.con, "M45")))
    # kolizje: we wsadzie, na dysku, w bazie
    k1 = a.klatka(r"LIGHTS\A\cam\1.fits", canon="NGC224")
    k2 = a.klatka(r"LIGHTS\B\cam\1.fits", canon="NGC224")
    plany.append(a.plan([k1, k2], target=queries.object_target(a.con, "NGC1")))
    os.makedirs(a.sciezka(r"LIGHTS\NGC2\cam"))
    open(a.sciezka(r"LIGHTS\NGC2\cam\ngc2_x.FITS"), "wb").close()
    c = a.klatka(r"LIGHTS\C\cam\NGC224_x.fits", canon="NGC224")
    plany.append(a.plan([c], target=queries.object_target(a.con, "NGC2")))
    d = a.klatka(r"LIGHTS\D\cam\NGC224_y.fits", canon="NGC224")
    duch = a.klatka(r"LIGHTS\NGC3\cam\NGC3_y.fits", canon="NGC3", plik=False)
    a.con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (duch,))
    plany.append(a.plan([d], target=queries.object_target(a.con, "NGC3")))
    # plik w miejscu katalogu celu; katalog celu nieczytelny (błąd systemu ze ścieżką w `repr`)
    open(a.sciezka(r"LIGHTS\NGC4"), "wb").close()
    e = a.klatka(r"LIGHTS\E\cam\NGC224_z.fits", canon="NGC224")
    plany.append(a.plan([e], target=queries.object_target(a.con, "NGC4")))
    # rodzaj błędu katalogu to fakt (AR-138): odmowa dostępu i brak katalogu mają własne zdania,
    # inny błąd systemu zostaje szczegółem zdania - także zajętość (WinError 32, `PermissionError`):
    # klasa błędu systemu ją pomija, bo to nie odmowa dostępu (AR-183)
    bledy = {"NGC5": PermissionError(13, "Odmowa dostępu"),
             "NGC6": FileNotFoundError(2, "Nie można odnaleźć ścieżki"),
             "NGC7": OSError(22, "Nieprawidłowy argument"),
             "NGC8": OSError(None, "Proces nie może uzyskać dostępu do pliku", None, 32)}
    for i, cel in enumerate(bledy):
        os.makedirs(a.sciezka(rf"LIGHTS\{cel}\cam"))
        f = a.klatka(rf"LIGHTS\F{i}\cam\NGC224_w.fits", canon="NGC224")

        def listdir(katalog, cel=cel):
            if cel in katalog:
                blad = bledy[cel]
                kod_win = () if blad.winerror is None else (blad.winerror,)
                raise type(blad)(blad.errno, blad.strerror, katalog, *kod_win)
            return os.listdir(katalog)
        plany.append(a.plan([f], target=queries.object_target(a.con, cel), listdir=listdir))
    assert [p.skipped[0].code for p in plany[-len(bledy):]] == [
        "dir_denied", "dir_missing", "dir_unreadable", "dir_unreadable"]
    # para stosu: wersja w innym katalogu → obie połowy
    o = _stos(a, r"STACKS\IC405\A140R\Ha\IC405_2025-08-23_A140R_Ha_60s_mono.xisf")
    v = _stos(a, r"STACKS\IC405\A140R\OIII\IC405_2025-08-23_A140R_Ha_60s_mono_autocrop.xisf")
    repo.link_stack_variant(a.con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                            source="user", now=NOW)
    plany.append(a.plan([o], target=queries.object_target(a.con, "IC1848")))

    pominiete = [s for p in plany for s in p.skipped]
    assert {s.code for s in pominiete} >= {
        "no_mtime", "many_copies", "kind_not_light", "retired", "superseded", "no_object",
        "off_position", "no_present_copy", "folder_twins", "card_skip", "batch_collision",
        "target_on_disk", "target_in_db", "file_in_dir_place", "dir_unreadable", "dir_denied",
        "dir_missing", "variant_dir", "pair"}
    for s in pominiete:
        tekst = tekst_pominiecia(s.code, s.params, s.reason)
        p = dict(s.params)
        if s.code == "pair":                           # pominięta połowa też w języku UI
            wewn = tekst_pominiecia(p["inner_code"], p["inner_params"], p["inner"])
            assert tekst == i18n.t("objchg.skip.pair", inner=wewn), tekst
            assert (wewn != p["inner"]) == (lang == "en"), wewn
        else:
            if s.code == "card_skip":                  # szczegół bramki karty w języku UI
                bramka = p.pop("gate")
                rodzina = "gate" if f"objchg.gate.{bramka}" in CATALOG else "item"   # suma (AR-167)
                p["detail"] = i18n.t(f"objchg.{rodzina}.{bramka}", **dict(p.pop("gate_params")))
            assert tekst == czytelny(i18n.t(f"objchg.skip.{s.code}", **p)), (s.code, tekst)
        assert "\\\\" not in tekst, tekst
        if lang == "en" and s.code != "dir_unreadable":        # szczegół z komunikatu systemu
            assert not set(tekst) & set("„ąćęłńóśźż"), (s.code, tekst)
        if lang == "pl":
            assert tekst == czytelny(s.reason) or s.code in ("folder_twins",), (s.code, tekst)

    # okno: lista pominięć mówi tym samym zdaniem (plan stanu klatek, tryb „Uzgodnij”)
    monkeypatch.setattr(resolver, "library_root_from_db", lambda con: str(a.root))
    dlg = ObjectChangeDialog(a.con, frame_ids=stan, target=None, now_fn=lambda: NOW,
                             off_thread=False)
    grupy = {dlg.skipped_tree.topLevelItem(i).text(0)
             for i in range(dlg.skipped_tree.topLevelItemCount())}
    assert grupy == {tekst_pominiecia(s.code, s.params, s.reason) for s in plany[0].skipped}
    assert i18n.t("objchg.skip.no_mtime") in grupy
    dlg.reject()
    a.con.close()


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_szczegol_odmowy_karty_i_celu_to_FAKTY_rdzenia_w_jezyku_UI(tmp_path, lang):
    """AR-138: przy karcie i celu parametrem zdania była proza rdzenia (`detail`), więc zdanie EN
    zostawało częściowo polskie. Prawdziwy planer: reguła karty FITS 4.0 (długość, znaki), długości
    komentarza przed i po układzie karty astropy oraz kanon folderu, którego system plików nie
    przyjmie, idą kodem z parametrami - zdanie w całości w języku UI. Falsyfikator: `detail` z prozą
    rdzenia w EN → polskie znaki w zdaniu."""
    from test_object_change_plan import _Archiwum as _ArchPlanu
    from horreum.gui.object_change_dialog import tekst_pominiecia
    a = _ArchPlanu(tmp_path)
    i18n.set_lang(lang)

    def cel(canon, forma):
        return oc.ObjectTarget(canon=canon, catalog=None, kind="deep_sky", alias_norm=None,
                               card_form=forma)
    dluga = a.klatka(r"LIGHTS\A\cam\NGC224_a.fits", canon="NGC224")
    znak = a.klatka(r"LIGHTS\B\cam\NGC224_b.fits", canon="NGC224")
    komentarz = a.klatka(r"LIGHTS\C\cam\NGC224_c.fits", canon="NGC224")
    a.con.execute("UPDATE cards SET comment = ? WHERE frame_id = ? AND keyword = 'OBJECT'",
                  ("k" * 70, komentarz))
    urzadzenie = a.klatka(r"LIGHTS\D\cam\NGC224_d.fits", canon="NGC224")
    pominiete = {}
    for fid, target in ((dluga, cel("NGC2632", "X" * 70)), (znak, cel("NGC2632", "NGC 2632 ±")),
                        (komentarz, cel("NGC2632", "NGC 2632")), (urzadzenie, cel("CON", "CON"))):
        plan = a.plan([fid], target=target)
        assert not plan.items, plan.items
        pominiete[fid] = plan.skipped[0]
    strata = writeback.comment_loss_lengths("fits", "OBJECT", "NGC 2632", "k" * 70)
    assert strata is not None and strata[0] == 70 > strata[1]
    # AR-141: `bad_target` niesie regułę formy folderu kodem (`rule`), a zdanie obu języków -
    # szczegół reguły z katalogu (`objchg.folder.<kod>`); proza rdzenia (`detail`) to zapas.
    regula = "kanon obiektu nie może być nazwą katalogu: 'CON'"
    oczekiwane = {dluga: ("card_too_long", {"value": "X" * 70, "length": 70, "limit": 68}),
                  znak: ("card_chars", {"value": "NGC 2632 ±"}),
                  komentarz: ("card_comment", {"before": strata[0], "after": strata[1]}),
                  urzadzenie: ("bad_target", {"canon": "CON", "detail": regula,
                                              "rule": "device_name",
                                              "rule_params": (("name", "CON"),)})}
    zdania = {"bad_target": {"canon": "CON",
                             "detail": i18n.t("objchg.folder.device_name", name="CON")}}
    for fid, (kod, params) in oczekiwane.items():
        s = pominiete[fid]
        assert (s.code, dict(s.params)) == (kod, params), s
        tekst = tekst_pominiecia(s.code, s.params, s.reason)
        assert tekst == czytelny(i18n.t(f"objchg.skip.{kod}", **zdania.get(kod, params)))
        if lang == "en":
            assert not set(tekst) & set("„ąćęłńóśźż"), (kod, tekst)
    # zdanie rdzenia (zapas okna, PL) mówi te same fakty
    assert f"z {strata[0]} do {strata[1]} znaków" in pominiete[komentarz].reason
    assert writeback.comment_loss_route("fits", "OBJECT", "NGC 2632", "k" * 70).startswith(
        f"zmiana wartości karty OBJECT ucięłaby zastany komentarz z {strata[0]} do {strata[1]} ")
    a.con.close()


def test_KAZDY_powod_bramki_karty_ma_zdanie_PL_i_EN_a_PL_to_zdanie_bramki():
    """AR-138: szczegół `card_skip` był prozą bramki (`queries.object_card_gate`) - w EN po polsku.
    Każdy powód bramki to `ZdanieRdzenia` z kodem: `objchg.gate.<kod>` w obu językach z tymi samymi
    polami, pola to parametry bramki, a PL to zdanie bramki znak w znak (PL okna bez zmian)."""
    import ast
    import inspect
    import string
    kody = {}
    # Bramka sumy kontrolnej ma własną funkcję (AR-163, wspólna z oknem naprawy) - `object_card_gate`
    # ją woła, więc jej powód jest powodem bramki karty. Osiągalność: `object_card_gate` ZWRACA jej
    # wynik (bez tego zbiór kodów byłby pełny, a bramka martwa).
    assert any(isinstance(w, ast.Return) and isinstance(w.value, ast.Call)
               and isinstance(w.value.func, ast.Name) and w.value.func.id == "fits_checksum_gate"
               for w in ast.walk(ast.parse(inspect.getsource(queries.object_card_gate))))
    for funkcja in (queries.object_card_gate, queries.fits_checksum_gate):
        for w in ast.walk(ast.parse(inspect.getsource(funkcja))):
            if (isinstance(w, ast.Call) and isinstance(w.func, ast.Name)
                    and w.func.id == "ZdanieRdzenia"):
                zdanie, kod = w.args
                kody[kod.value] = (zdanie, {k.arg for k in w.keywords})
    assert len(kody) == 13
    for kod, (zdanie, parametry) in kody.items():
        wpis = CATALOG[f"objchg.gate.{kod}"]
        pola = {j: {f for _, f, _, _ in string.Formatter().parse(wpis[j]) if f}
                for j in ("pl", "en")}
        assert pola["pl"] == pola["en"] and pola["pl"] <= parametry, kod
        assert not set(wpis["en"]) & set("„ąćęłńóśźż"), kod
        if isinstance(zdanie, ast.Constant):
            assert wpis["pl"] == zdanie.value, kod
        elif isinstance(zdanie, ast.Name):
            assert wpis["pl"] == getattr(queries, zdanie.id), kod


def _zdanie_pl_z_fstringa(w, modul):
    """Zdanie PL wywołania `PowodPozycji(zdanie, kod, **p)` jako WZÓR katalogu: literał wprost,
    f-string z każdym `{wyrażenie}` zamienionym na `{nazwa}` parametru o TYM SAMYM wyrażeniu (AST),
    stała modułu - jej wartością; nazwa (zdanie = parametr) → `{nazwa}`; `", ".join(lista)` →
    `{nazwa}` parametru-listy `lista` (AR-148: okno składa listę po `, `, jak rdzeń). Wyrażenie bez
    parametru = AssertionError: zdanie PL mówiłoby coś, czego okno nie ma z czego złożyć."""
    import ast
    zdanie = w.args[0]
    parametry = {ast.dump(k.value): k.arg for k in w.keywords}

    def _pole(v):
        if ast.dump(v) in parametry:
            return "{" + parametry[ast.dump(v)] + "}"
        if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "join"
                and isinstance(v.func.value, ast.Constant) and v.func.value.value == ", "
                and len(v.args) == 1 and ast.dump(v.args[0]) in parametry):
            return "{" + parametry[ast.dump(v.args[0])] + "}"
        assert isinstance(v, ast.Name) and isinstance(getattr(modul, v.id, None), str), ast.dump(v)
        return getattr(modul, v.id)
    if isinstance(zdanie, ast.Constant):
        return zdanie.value
    if isinstance(zdanie, ast.JoinedStr):
        czesci = []
        for c in zdanie.values:
            if isinstance(c, ast.Constant):
                czesci.append(c.value)
            else:
                assert c.conversion == -1 and c.format_spec is None, ast.dump(c)
                czesci.append(_pole(c.value))
        return "".join(czesci)
    return _pole(zdanie)


def _powody_pozycji():
    """`kod → [(wzór PL, nazwy parametrów)]` z KAŻDEGO `PowodPozycji(...)` w `writeback` i `repo`
    oraz w modułach, w których zdanie odmowy rodzi się z kodem (AR-158): czytnik XISF `scan`
    i reguły karty `card_rules`, bramki makra i wyrażenia (`macro`, `expr`, AR-181, AR-194), podgląd
    i wzór nazw (`naming`, AR-193), wydanie obiektu (`projection`, AR-197) i właściciele błędów
    systemu i bazy klasą (`item_reasons.powod_systemu`, `powod_bazy`, AR-184, AR-198) z regułą
    wyjątku okna (`powod_okna`, błąd programu, AR-214) - z modułu tylko te funkcje: reszta kodeka
    składa powód z kodu odczytanego, nie z literału."""
    import ast
    import inspect
    from horreum import card_rules, expr, item_reasons, macro, naming, projection, scan
    from horreum import repo as repo_mod
    out = {}
    zrodla = [(m, inspect.getsource(m)) for m in (writeback, repo_mod, scan, card_rules, macro, expr,
                                                  naming, projection)]
    zrodla += [(item_reasons, inspect.getsource(f))
               for f in (item_reasons.powod_systemu, item_reasons.powod_bazy,
                         item_reasons.powod_okna)]
    for modul, zrodlo in zrodla:
        for w in ast.walk(ast.parse(zrodlo)):
            if not (isinstance(w, ast.Call) and isinstance(w.func, ast.Name)
                    and w.func.id == "PowodPozycji"):
                continue
            assert isinstance(w.args[1], ast.Constant), ast.dump(w)
            out.setdefault(w.args[1].value, []).append(
                (_zdanie_pl_z_fstringa(w, modul), {k.arg for k in w.keywords}))
    return out


def test_KAZDY_kod_powodu_pozycji_ma_zdanie_PL_i_EN_a_PL_to_zdanie_rdzenia():
    """AR-141: powody pozycji leżały w bazie po polsku. Każdy `PowodPozycji` sterownika zapisu
    i klingi (AST) ma kod z `ITEM_REASON_CODES` (komplet - bez martwych kluczy), `objchg.item.<kod>`
    w obu językach z tymi samymi polami (wpis mnogi: każda forma), pola ⊆ parametry rdzenia, EN bez
    polskich znaków, a PL = zdanie rdzenia z polami zamiast wyrażeń - okno PL mówi znak w znak to,
    co CLI i log. To samo dla reguł formy folderu (`objchg.folder.<kod>`)."""
    import string
    from horreum.item_reasons import ITEM_REASON_CODES, PARAM_KINDS
    from horreum.resolve.catalog import FOLDER_RULE_CODES
    kody = _powody_pozycji()
    assert set(kody) == ITEM_REASON_CODES, set(kody) ^ ITEM_REASON_CODES

    def pola(tekst):
        return {f for _, f, _, _ in string.Formatter().parse(tekst) if f}
    for kod, miejsca in kody.items():
        wpis = CATALOG[f"objchg.item.{kod}"]
        formy = {j: (list(wpis[j].values()) if isinstance(wpis[j], dict) else [wpis[j]])
                 for j in ("pl", "en")}
        pola_pl = {frozenset(pola(f)) for f in formy["pl"]}
        assert len(pola_pl) == 1 and pola_pl == {frozenset(pola(f)) for f in formy["en"]}, kod
        for wzor, parametry in miejsca:
            assert wzor in formy["pl"], (kod, wzor)
            assert set(next(iter(pola_pl))) <= parametry, (kod, parametry)
            assert parametry <= set(PARAM_KINDS), (kod, parametry - set(PARAM_KINDS))  # S1
        assert not any(set(f) & set("„ąćęłńóśźż") for f in formy["en"]), kod
    assert {k.split(".", 2)[2] for k in CATALOG if k.startswith("objchg.item.")} == \
        ITEM_REASON_CODES
    assert {k.split(".", 2)[2] for k in CATALOG if k.startswith("objchg.folder.")} == \
        FOLDER_RULE_CODES
    for kod in FOLDER_RULE_CODES:
        wpis = CATALOG[f"objchg.folder.{kod}"]
        assert pola(wpis["pl"]) == pola(wpis["en"]), kod
        assert not set(wpis["en"]) & set("„ąćęłńóśźż"), kod


def test_ZLOTE_powody_dynamiczne_PL_okna_to_proza_rdzenia_a_EN_bez_polskiego(tmp_path, monkeypatch):
    """AR-141 (Z8): złote zdania DYNAMICZNYCH powodów - z prawdziwych dróg rdzenia, nie z literałów
    AST: izolacja (obie drogi naprawy), plik zajęty przy przeniesieniu, odmowa klingi zagnieżdżona
    (konflikt aliasu), plik, który nie wrócił (odmowa karty + powód renamu), zeznanie wstrzymane
    z odmianą liczby kopii (1 i 2) i głosem klatki. PL okna == `czytelny_powod(proza rdzenia)` znak
    w znak; EN bez polskich liter poza prozą warstwy bez kodu (pisarz karty - granica)."""
    import shutil
    from test_object_change_write import _Scena
    from horreum.gui.wb_worker import czytelny_powod, tekst_powodu
    from horreum.item_reasons import PowodPozycji
    powody = [writeback._powod_izolacji({"id": 7, "kind": "commit", "phase": faza})
              for faza in ("writing", "written")]
    assert [p.code for p in powody] == ["isolated_recover", "isolated_finish"]
    zajety = OSError(None, "Proces nie może uzyskać dostępu do pliku", None, 32)
    powody.append(writeback._powod_bledu_renamu(zajety, 3))
    s = _Scena(tmp_path / "a")
    m42, _ = repo.upsert_object(s.con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
    repo.add_object_alias(s.con, alias_norm="flamingstar", object_id=m42, source="user", now=NOW)
    plan = s.plan(pozycje=[s.pozycja(0)])
    plan = oc.ObjectChangePlan(plan.run_id, oc.ObjectTarget("IC405", "IC", "deep_sky",
                                                            "flamingstar", "IC 405"), plan.items, ())
    repo.stage_object_change(s.con, plan=plan, now=NOW)
    powody += [fr.reason for fr in writeback.commit_object_change(s.con, plan.run_id,
                                                                  now=NOW).blocked]
    s2 = _Scena(tmp_path / "b")
    zla = oc.ObjectChangeItem(**{**s2.pozycja(0).__dict__, "card_new": "IC 405ł"})
    run = s2.stage(s2.plan(pozycje=[zla]))
    monkeypatch.setattr(writeback, "_przenies_wstecz", lambda *a, **kw: writeback.RenameFileResult(
        "blocked", PowodPozycji("plik nie stoi na ścieżce z przebiegu", "not_on_run_path")))
    powody += [fr.reason for fr in writeback.commit_object_change(s2.con, run, now=NOW).failed]
    monkeypatch.undo()
    lok = s.con.execute("SELECT id FROM location WHERE path = ?", (str(s.stare[1]),)).fetchone()[0]
    powody.append(repo.withheld_reason(s.con, location_id=lok, commit_id=5))
    kopia = tmp_path / "a" / "INNE" / s.stare[1].name
    kopia.parent.mkdir()
    shutil.copyfile(s.stare[1], kopia)
    from horreum import scan
    scan.ingest_record(s.con, scan.scan_file(str(kopia)), volume="V", now=NOW,
                       summary=scan.ScanSummary())
    powody.append(repo.withheld_reason(s.con, location_id=lok, commit_id=5, undo=True))
    assert [p.code for p in powody[2:]] == ["busy", "db_refused", "file_not_back",
                                            "testimony_withheld", "testimony_withheld_undo"]
    assert [dict(p.params)["copies"].params for p in powody[-2:]] == [(("n", 1),), (("n", 2),)]
    for lang in ("pl", "en"):
        i18n.set_lang(lang)
        for p in powody:
            zdanie = tekst_powodu(p)
            if lang == "pl":
                assert zdanie == czytelny_powod(str(p)), (zdanie, str(p))
            elif p.code != "file_not_back":              # odmowa karty cytuje znak 'ł' wartości
                assert not set(zdanie) & set("„ąćęłńóśźż"), zdanie
    i18n.set_lang("en")
    assert "1 present copy" in tekst_powodu(powody[-2]) and "2 present copies" in tekst_powodu(
        powody[-1])
    s.con.close()
    s2.con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_stale_modulowe_powodow_maja_zdanie_w_jezyku_UI(lang):
    """AR-141 (K3): powody-stałe modułów (`repo._POWOD_NOWSZEJ_REKI`, `_BAZA_NOWSZA_*`,
    `writeback._ZAMIAR_OTWARTY`…) - zbierane z OBIEKTÓW modułu w czasie biegu, nie z AST: każda ma
    wpis katalogu, w PL mówi znak w znak prozą rdzenia, w EN bez polskich liter."""
    from horreum import repo as repo_mod
    from horreum.gui.wb_worker import czytelny_powod, tekst_powodu
    from horreum.item_reasons import PowodPozycji
    i18n.set_lang(lang)
    stale = {f"{m.__name__}.{n}": v for m in (repo_mod, writeback) for n, v in vars(m).items()
             if isinstance(v, PowodPozycji)}
    assert {"horreum.repo._POWOD_NOWSZEJ_REKI", "horreum.repo._POWOD_REKI_NIEZNANEJ",
            "horreum.repo._BAZA_NOWSZA_W_BIEGU", "horreum.repo._BAZA_NOWSZA_PRZY_COFNIECIU",
            "horreum.writeback._ZAMIAR_OTWARTY"} <= set(stale), set(stale)
    for nazwa, p in stale.items():
        assert f"objchg.item.{p.code}" in CATALOG, nazwa
        zdanie = tekst_powodu(p)
        if lang == "pl":
            assert zdanie == czytelny_powod(str(p)), nazwa
        else:
            assert not set(zdanie) & set("„ąćęłńóśźż"), (nazwa, zdanie)


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("n, en", [(0, "0 present copies"), (1, "1 present copy"),
                                   (2, "2 present copies"), (5, "5 present copies"),
                                   (12, "12 present copies"), (22, "22 present copies")])
def test_liczba_kopii_odmienia_sie_w_obu_jezykach(n, en, lang):
    """K3: fragment liczby kopii zeznania wstrzymanego (`repo._kopie`) - PL odmiana rdzenia
    (1 / 2-4 / 5+ / -naście) == wpis mnogi katalogu dla tych samych `n`, EN z formy `one`/`other`."""
    from horreum import repo as repo_mod
    from horreum.gui.wb_worker import tekst_powodu
    i18n.set_lang(lang)
    fragment = repo_mod._kopie(n)
    assert fragment.code == "copies" and dict(fragment.params) == {"n": n}
    assert tekst_powodu(fragment) == (str(fragment) if lang == "pl" else en)
    assert str(fragment) == {0: "0 obecnych kopii", 1: "1 obecną kopię", 2: "2 obecne kopie",
                             5: "5 obecnych kopii", 12: "12 obecnych kopii",
                             22: "22 obecne kopie"}[n]


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("canon, regula, params", [
    ("", "empty", {}), (" NGC1", "edge_space", {}), ("Foo/Bar", "slash_outside_comet", {}),
    ("..", "reserved_dot", {}), ("NGC<1", "forbidden_char", {"char": "'<'"}),
    ("nul.txt", "device_name", {"name": "nul.txt"}), ("NGC1.", "trailing_dot_space", {}),
    ("X" * 256, "too_long", {"n": 256, "limit": 255})])
def test_regula_folderu_ma_kod_a_komunikat_bez_zmian(canon, regula, params, lang):
    """AR-141: `folder_form` odmawia `FolderFormError` (`ValueError` - wołający łapią jak dotąd)
    z KODEM reguły i parametrami; zdanie reguły w języku UI z tych parametrów."""
    from horreum.resolve.catalog import FolderFormError, folder_form
    i18n.set_lang(lang)
    with pytest.raises(FolderFormError) as odmowa:
        folder_form(canon)
    assert isinstance(odmowa.value, ValueError)
    assert (odmowa.value.code, dict(odmowa.value.params)) == (regula, params)
    assert str(odmowa.value).startswith(("kanon obiektu nie może być nazwą katalogu: ",
                                         "kanon z '/' spoza gramatyki komety: "))
    zdanie = i18n.t(f"objchg.folder.{regula}", **params)
    if lang == "en":
        assert not set(zdanie) & set("„ąćęłńóśźż"), zdanie


# ═══════════════════════════════════════════════ ostrzeżenia planera i sterownika w języku UI

def _kody_ostrzezen():
    """`(kod → nazwy parametrów, kody planera)` z KAŻDEGO ostrzeżenia z kodem (AST): planer
    `ObjectChangeWarning(..., code=…, params=((nazwa, …), …))` i sterownik zapisu
    `ZdanieRdzenia(zdanie, kod, **params)`."""
    import ast
    import inspect
    out, planer = {}, set()
    for modul in (oc, writeback):
        for w in ast.walk(ast.parse(inspect.getsource(modul))):
            if not (isinstance(w, ast.Call) and isinstance(w.func, ast.Name)):
                continue
            if w.func.id == "ObjectChangeWarning":
                kw = {k.arg: k.value for k in w.keywords}
                assert isinstance(kw["code"], ast.Constant), ast.dump(w)
                kod, nazwy = kw["code"].value, {e.elts[0].value for e in kw["params"].elts}
                planer.add(kod)
            elif w.func.id == "ZdanieRdzenia":
                assert isinstance(w.args[1], ast.Constant), ast.dump(w)
                kod, nazwy = w.args[1].value, {k.arg for k in w.keywords}
            else:
                continue
            out.setdefault(kod, set()).update(nazwy)
    return out, planer


def test_KAZDY_kod_ostrzezenia_ma_zdanie_PL_i_EN_z_parametrami_rdzenia():
    """AR-138: ostrzeżenia planera (`ObjectChangeWarning`) i sterownika zapisu (`ZdanieRdzenia`
    w `writeback`) mówiły wyłącznie po polsku. Każde ostrzeżenie z kodem (planer: komplet
    `WARNING_CODES`) ma `objchg.warn.<kod>` w obu językach z tymi samymi polami (wpis mnogi: każda
    forma), a pola zdania to parametry, które rdzeń podaje. Bramka dla kodów, których fixture nie
    zbuduje."""
    import string
    kody, planer = _kody_ostrzezen()
    assert planer == oc.WARNING_CODES
    assert {"stack_split", "dir_not_removed", "dir_uncertain"} <= set(kody)
    for kod, parametry in kody.items():
        wpis = CATALOG[f"objchg.warn.{kod}"]
        pola = {}
        for j in ("pl", "en"):
            formy = list(wpis[j].values()) if isinstance(wpis[j], dict) else [wpis[j]]
            zbiory = [{f for _, f, _, _ in string.Formatter().parse(forma) if f} for forma in formy]
            assert all(z == zbiory[0] for z in zbiory), (kod, j)
            pola[j] = zbiory[0]
            if j == "en":
                assert not any(set(forma) & set("„ąćęłńóśźż") for forma in formy), kod
        assert pola["pl"] == pola["en"], kod
        assert pola["pl"] <= parametry, (kod, pola["pl"], parametry)


_FOLDERY = {1: ("folder", "folder"), 2: ("foldery", "folders"), 4: ("foldery", "folders"),
            5: ("folderów", "folders"), 12: ("folderów", "folders"), 14: ("folderów", "folders"),
            22: ("foldery", "folders")}


@pytest.mark.parametrize("n", sorted(_FOLDERY))
def test_ostrzezenie_stosu_ODMIENIA_liczbe_folderow_PL_i_EN(n):
    """Rdzeń mówił „rozejdą się na 2 folderów” - teraz zdanie okna odmienia liczbę folderów
    (`t_plural`, parametr `n`): 1, 2-4, 5, -naście, 22."""
    from horreum.gui.object_change_dialog import tekst_ostrzezenia
    params = (("stack", "M31_2022-03-21_cam_L_60s_mono.xisf"), ("moved", 2), ("inputs", 3),
              ("n", n))
    pl, en = _FOLDERY[n]
    i18n.set_lang("pl")
    assert f"przeniesie 2 z 3 jego wejść - wejścia rozejdą się na {n} {pl}, a żniwa" in (
        tekst_ostrzezenia("stack_split", params, "zapas"))
    i18n.set_lang("en")
    assert f"moves 2 of its 3 inputs - the inputs will split across {n} {en}, and" in (
        tekst_ostrzezenia("stack_split", params, "zapas"))
    # kod bez zdania w katalogu i ostrzeżenie bez kodu - zdanie rdzenia
    assert tekst_ostrzezenia("nieznany", params, "zapas") == "zapas"
    assert tekst_ostrzezenia(None, (), "zdanie rdzenia") == "zdanie rdzenia"


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_ostrzezenie_PRAWDZIWEGO_planera_w_oknie_w_jezyku_UI(qapp, tmp_path, monkeypatch, lang):
    """Przeniesienie części wejść stosu: planer daje kod `stack_split` z parametrami, okno pokazuje
    zdanie w języku UI (EN bez polskiego), zdanie rdzenia zostaje zapasem."""
    from test_object_change_plan import _Archiwum as _ArchPlanu, _stos
    from horreum.gui.object_change_dialog import ObjectChangeDialog, tekst_ostrzezenia
    a = _ArchPlanu(tmp_path)
    i18n.set_lang(lang)
    lights = [a.klatka(rf"LIGHTS\M31\cam\L\{i}.fits", canon="NGC224",
                       date_obs=f"2022-03-2{i}T20:00:00") for i in range(1, 4)]
    stos = _stos(a, r"STACKS\M31\cam\L\M31_2022-03-21_cam_L_60s_mono.xisf", canon="NGC224")
    iid, _ = repo.upsert_integration(
        a.con, master_frame_id=stos, integ_hash=None, tool=None, window_start=None, window_end=None,
        declared_rows=None, drizzle_inputs=None, disabled_inputs=None, degenerate=0, ambiguous=0,
        telescope_mismatch=0, unresolved_reason=None, now=NOW)
    for f in lights:
        repo.link_integration(a.con, integration_id=iid, input_frame_id=f, asserted_by="user",
                              now=NOW)
    cel = queries.object_target(a.con, "M45")
    w, = a.plan(lights[:2], target=cel).warnings
    assert (w.code, dict(w.params)) == ("stack_split", {
        "stack": "M31_2022-03-21_cam_L_60s_mono.xisf", "moved": 2, "inputs": 3, "n": 2})
    zdanie = tekst_ostrzezenia(w.code, w.params, w.text)
    assert ("across 2 folders" if lang == "en" else "na 2 foldery") in zdanie
    if lang == "en":
        assert not set(zdanie) & set("„ąćęłńóśźż"), zdanie
    monkeypatch.setattr(resolver, "library_root_from_db", lambda con: str(a.root))
    dlg = ObjectChangeDialog(a.con, frame_ids=lights[:2], target=cel, now_fn=lambda: NOW,
                             off_thread=False)
    assert not dlg.warnings.isHidden() and dlg.warnings.text() == zdanie
    # po biegu (i po cofnięciu) ostrzeżenie w czasie przyszłym znika razem z liczbami podglądu
    from types import SimpleNamespace
    pusty = SimpleNamespace(applied=[], blocked=[], failed=[], skipped=[], withheld=[])
    dlg._pokaz_wynik(pusty, cofniecie=True)
    assert dlg.warnings.isHidden()
    dlg.reject()
    a.con.close()


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_ostrzezenia_STEROWNIKA_niosa_kod_i_mowia_w_jezyku_UI(tmp_path, monkeypatch, lang):
    """AR-138: ostrzeżenia sterownika zapisu gestu (katalog źródła nie usunięty, katalog o niepewnej
    własności) były wyłącznie polską prozą. Prawdziwy `commit_object_change`: ostrzeżenie to
    `ZdanieRdzenia` - zdanie PL dla CLI i logu, kod z parametrami dla okna; zdanie wyniku okna mówi
    je w języku UI. Ostrzeżenie bez kodu (zwykły `str` rdzenia) zostaje zdaniem rdzenia."""
    from test_object_change_write import _Scena, _Smierc, _smierc_po
    from horreum.gui.object_change_dialog import zdanie_wyniku_zmiany
    i18n.set_lang(lang)
    # katalog źródła opróżniony przez gest, którego system nie da usunąć
    s = _Scena(tmp_path / "a")
    run = s.stage(s.plan())

    def _odmowa(sciezka, *a, **kw):
        raise PermissionError(13, "Odmowa dostępu", sciezka)
    monkeypatch.setattr(writeback.os, "rmdir", _odmowa)
    wynik = writeback.commit_object_change(s.con, run, now=NOW)
    monkeypatch.undo()
    uwaga, = [w for w in wynik.warnings if getattr(w, "code", None) == "dir_not_removed"]
    assert dict(uwaga.params)["dir"] == str(s.zrodlo)
    assert dict(uwaga.params)["detail"].code == "os_denied"           # błąd systemu klasą (AR-168)
    assert uwaga.startswith(f"katalog {s.zrodlo} nie usunięty (odmowa dostępu do pliku "
                            f"(Errno 13))")                                       # zdanie PL
    s.con.close()
    # katalog założony bez potwierdzenia (śmierć po `mkdir`) - własność niepewna
    s = _Scena(tmp_path / "b")
    run = s.stage(s.plan(pozycje=[s.pozycja(0)]))
    _smierc_po(monkeypatch, writeback.os, "mkdir")
    with pytest.raises(_Smierc):
        writeback.commit_object_change(s.con, run, now=NOW)
    monkeypatch.undo()
    drugi = writeback.commit_object_change(s.con, run, now=NOW)
    niepewna, = [w for w in drugi.warnings if getattr(w, "code", None) == "dir_uncertain"]
    assert dict(niepewna.params) == {"dir": str(tmp_path / "b" / "LIGHTS" / "IC405")}
    s.con.close()

    wynik = dataclasses.replace(wynik, warnings=(uwaga, niepewna, "zdanie rdzenia bez kodu"))
    zdanie = zdanie_wyniku_zmiany(wynik)
    from horreum.gui.wb_worker import tekst_powodu
    for w in (uwaga, niepewna):
        p = {k: tekst_powodu(v) if hasattr(v, "code") else v for k, v in w.params}
        assert czytelny(i18n.t(f"objchg.warn.{w.code}", **p)) in zdanie
    assert zdanie.endswith("\nzdanie rdzenia bez kodu")
    if lang == "en":
        assert "nie usunięty" not in zdanie and "własność niepewna" not in zdanie
        assert "not removed (access to the file denied (Errno 13))" in zdanie
        assert "ownership uncertain" in zdanie


def czytelny(tekst):
    from horreum.gui.wb_worker import czytelny_powod
    return czytelny_powod(tekst)


# ═══════════════════════════════════════════════ okna kasowane po `exec`

def _okno_do_exec(ktore, con, host):
    from horreum.gui.app import ConfirmPathObjectsDialog, RepairHeaderDialog
    from horreum.gui.assign_dialog import AssignObjectDialog
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    if ktore == "zmiana":
        return ObjectChangeDialog(con, frame_ids=[1, 2], target=CEL, now_fn=lambda: NOW,
                                  off_thread=False, parent=host)
    if ktore == "wybierak":
        return AssignObjectDialog(con, object_raw=None, frame_count=1, parent=host)
    if ktore == "naprawa":
        return RepairHeaderDialog(con, rows=[], db_path=queries.db_path_of(con),
                                  now_fn=lambda: NOW, parent=host)
    return ConfirmPathObjectsDialog(con, proposals=[], now_fn=lambda: NOW, parent=host)


@pytest.mark.parametrize("ktore", ["zmiana", "wybierak", "naprawa", "sciezka"])
def test_okno_KASUJE_sie_po_exec_a_gospodarz_czyta_je_jeszcze_po_powrocie(
        qapp, con, rdzen, ktore):
    """Okno nie było kasowane po `exec` - każde zamknięte zostawało dzieckiem
    gospodarza do końca sesji. Po `exec` okno żyje do pętli zdarzeń gospodarza (gospodarz czyta
    `summary`/`selected`/zdanie stanu), potem znika. Falsyfikator: bez kasacji w `exec` okno
    zostaje dzieckiem gospodarza po `DeferredDelete`."""
    import shiboken6
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QWidget
    host = QWidget()
    dlg = _okno_do_exec(ktore, con, host)
    klasa = type(dlg)
    QTimer.singleShot(0, dlg.reject)
    dlg.exec()
    assert shiboken6.isValid(dlg) and dlg.windowTitle()          # gospodarz czyta po `exec`
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not shiboken6.isValid(dlg)
    assert host.findChildren(klasa) == []
    host.deleteLater()


# ═══════════════════════════════════════════════ „Napraw nagłówek…”: rozmiar od treści, powód

def _bezimienne(root, con, foldery, *, bez_zapasu=()):
    """Po dwa FITS-y lightów BEZ karty OBJECT w każdym folderze obiektu, wciągnięte skanem - kubełek
    „Napraw nagłówek…” (propozycja nazwy z dwóch zgodnych świadków ścieżki). Foldery z `bez_zapasu`
    mają `END` na ostatnim rekordzie bloku 2880 B: dopisanie karty nie ma w nagłówku miejsca, więc
    rdzeń spada na drogę atomową (AR-118)."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    for g, folder in enumerate(foldery):
        for k in range(2):
            p = (root / "LIGHTS" / folder / "RC8_2600MC" / "OSC"
                 / f"{folder}_20230103_2000{k:02d}_LIGHT_OSC_300s_FLATGRP_NOFLAT_.fits")
            p.parent.mkdir(parents=True, exist_ok=True)
            hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + 10 * g + k)
            hdu.header["IMAGETYP"] = "Light"
            hdu.header["DATE-OBS"] = f"2023-01-03T20:00:{k:02d}"
            i = 0
            while folder in bez_zapasu and (len(hdu.header) + 1) % 36:
                hdu.header[f"PAD{i}"] = i
                i += 1
            hdu.writeto(str(p))
            scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                               summary=scan.ScanSummary())


def test_Napraw_naglowek_Enter_w_polu_grupy_NIE_pisze_kart_prawdziwym_klawiszem(qapp, tmp_path):
    """„Zapisz karty (N)” był przyciskiem domyślnym, więc Enter
    w polu nazwy grupy pisał karty do PLIKÓW. Domyślny jest „Zamknij” (wzór okna zmiany obiektu):
    Enter w polu grupy nie startuje zapisu. Falsyfikator: `autoDefault` zapisu → `start` wołany."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from horreum.gui.app import RepairHeaderDialog
    con = db.open_db(str(tmp_path / "z.db"))
    _bezimienne(tmp_path / "ASTRO_", con, ["NGC7635"])
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    starty = []
    dlg._runner.start = lambda op, *a, **k: starty.append(op)
    dlg.show()
    pole = dlg._groups[0]["edit"]
    pole.setFocus()
    assert dlg.save_btn.isEnabled() and not dlg.save_btn.isDefault()
    assert dlg._close_btn.isDefault()
    QTest.keyClick(pole, Qt.Key_Return)
    assert starty == [] and dlg.result() == QDialog.Rejected
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_etykieta_grupy_OD_FOLDERU_OBIEKTU_i_odmieniona_liczba(qapp, tmp_path,
                                                                             lang):
    """Zrzut natywny: cztery grupy „OSC · 2 klatek” - etykietą był rodzic pliku (filtr),
    jednakowy dla każdego obiektu, a liczba bez odmiany. Etykieta od folderu obiektu
    (`object_folder`), liczba przez `t_plural` (1, 2-4, 5, 12-14, 22); błąd grupy mówi tą samą
    etykietą."""
    from horreum.gui.app import RepairHeaderDialog
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "e.db"))
    _bezimienne(tmp_path / "ASTRO_", con, ["NGC7635", "IC405"])
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    etykiety = sorted(g["check"].text() for g in dlg._groups)
    assert etykiety == sorted(i18n.t_plural("repair.group", 2, folder=f"{o}\\RC8_2600MC\\OSC")
                              for o in ("NGC7635", "IC405"))
    g = dlg._groups[0]
    g["edit"].setText("")                                # pusta nazwa - błąd mówi etykietą grupy
    assert dlg.error.text().startswith(g["label"] + ":"), dlg.error.text()
    dlg.reject()
    con.close()
    oczek = {"pl": ["1 klatka", "2 klatki", "5 klatek", "12 klatek", "22 klatki"],
             "en": ["1 frame", "2 frames", "5 frames", "12 frames", "22 frames"]}[lang]
    assert [i18n.t_plural("repair.group", n, folder="X") for n in (1, 2, 5, 12, 22)] == [
        f"X  ·  {o}" for o in oczek]


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_rozmiar_OD_TRESCI_a_zapis_nie_rozpycha_okna(qapp, tmp_path, lang):
    """Wizytacja bs (W11): okno otwierało się 256×220 (wiersze grup za suwakiem). Teraz: szerokość
    mieści całe wiersze grup (najdłuższy realny folder obiektu archiwum - kometa) bez poziomego
    suwaka, wysokość wszystkie grupy, a zapis nie rozpycha okna (przyciski „Cofnij”/„Rozwiąż teraz”
    policzone z góry); sufit - część ekranu. Zdanie o spadku na drogę atomową i szczegół rdzenia
    w podpowiedzi - osobny test bez geometrii
    (`test_Napraw_naglowek_szczegol_spadku_w_podpowiedzi_w_jezyku_UI`).

    AR-159: do AR-170 ten plik nie stawiał `QT_QPA_PLATFORM=offscreen`, więc puszczony sam biegł na
    platformie natywnej (Windows: styl `windows11`, dwa ekrany, DPR 1,5), a w baterii - offscreen
    (`fusion`, ekran 800×800), bo platformę stawiał moduł testów zebrany wcześniej. Asercja `isHidden()` suwaka
    poziomego zależała od stylu: `windows11` trzyma suwak niechowany przy zakresie 0 (zmierzone:
    zakres 0, viewport 788 px ≥ treść 776 px, a `isHidden()` False). Reguła „wiersze się mieszczą”
    to ZAKRES suwaka 0 - nic do przewinięcia w poziomie - niezależnie od stylu. Sufit liczony
    z ekranu, z którego okno liczyło rozmiar (przed `show`): menedżer okien kładzie okno na
    innym ekranie."""
    from horreum.gui.app import RepairHeaderDialog
    from horreum.gui.config_dialog import _SCREEN_FRAC
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "n.db"))
    _bezimienne(tmp_path / "ASTRO_", con,
                ["NGC7635", "C2023A3_Tsuchinshan-ATLAS", "Sh2-229", "IC405"],
                bez_zapasu=("Sh2-229",))
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    dlg._runner.async_ok = False
    ekran = dlg.screen().availableGeometry()
    sufit_w, sufit_h = int(ekran.width() * _SCREEN_FRAC), int(ekran.height() * _SCREEN_FRAC)
    dlg.show()
    QCoreApplication.processEvents()
    tresc = dlg._area.widget().sizeHint()
    if dlg.width() < sufit_w:
        assert dlg._area.horizontalScrollBar().maximum() == 0      # wiersze grup się mieszczą
        assert dlg._area.viewport().width() >= tresc.width()
    else:
        assert dlg.width() == sufit_w
    if dlg.height() < sufit_h:
        assert dlg._area.viewport().height() >= tresc.height()
    przed = dlg.size()
    dlg._on_save()
    QCoreApplication.processEvents()
    assert not dlg.undo_btn.isHidden() and not dlg.resolve_btn.isHidden()
    assert dlg.size() == przed                                 # zapis nie rozpycha okna
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_szczegol_spadku_w_podpowiedzi_w_jezyku_UI(qapp, tmp_path, lang):
    """Karta idzie W MIEJSCU tam, gdzie nagłówek ma zapas (AR-118); o plikach bez zapasu zdanie mówi
    „cały plik przepisany” językiem człowieka, a szczegół rdzenia (brak miejsca, z odmienioną liczbą
    rekordów) jest w podpowiedzi zdania - w języku UI. Bez `show()` i geometrii okna: asercje
    rozmiaru (test obok) zależą od ekranu i nie zasłaniają tych."""
    from horreum.gui.app import RepairHeaderDialog
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "n.db"))
    _bezimienne(tmp_path / "ASTRO_", con,
                ["NGC7635", "C2023A3_Tsuchinshan-ATLAS", "Sh2-229", "IC405"],
                bez_zapasu=("Sh2-229",))
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    dlg._runner.async_ok = False
    dlg._on_save()
    QCoreApplication.processEvents()
    assert i18n.t("wb.inplace_fallback", n=2) in dlg.status.text()    # dwa pliki bez zapasu
    assert writeback.PREFIKS_DROGI_ATOMOWEJ not in dlg.status.text()
    szczegol = {"pl": "potrzebuje 1 wolnego rekordu",                 # szczegół w języku UI
                "en": "needs 1 free record"}[lang]
    assert szczegol not in dlg.status.text()
    assert szczegol in dlg.status.toolTip(), dlg.status.toolTip()
    dlg._on_undo()
    # Protokół pola (AR-204): szczegół zapisu schodzi z cofnięciem, podpowiedź = samo zdanie.
    assert dlg.status.szczegol() == "" and dlg.status.toolTip() == dlg.status.text()
    dlg.reject()
    con.close()


# ═══════════════════════════════════════════════ „Napraw nagłówek…”: ogon cofnięcia (AR-160), sumy
# kontrolne w podglądzie (AR-163), zdanie wyniku przy różnych powodach (AR-162)

_ZNAKI_PL = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _lighty(root, con, folder, n, *, baza, suma=False):
    """`n` FITS-ów lightów bez karty OBJECT w folderze obiektu (jak `_bezimienne`), z kartami
    `CHECKSUM`/`DATASUM`, gdy `suma` (astropy `checksum=True` - pisarz ich odmówi). `baza` rozdziela
    dane pliku (tożsamość klatki), nazwa niesie folder - propozycja ze ścieżki."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    pliki = []
    for k in range(n):
        p = (root / "LIGHTS" / folder / "RC8_2600MC" / "OSC"
             / f"{folder}_20230104_21{baza:02d}{k:02d}_LIGHT_OSC_300s_FLATGRP_NOFLAT_.fits")
        p.parent.mkdir(parents=True, exist_ok=True)
        hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + 100 * baza + k)
        hdu.header["IMAGETYP"] = "Light"
        hdu.header["DATE-OBS"] = f"2023-01-04T21:{baza:02d}:{k:02d}"
        hdu.writeto(str(p), checksum=suma)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
        pliki.append(p)
    return pliki


def _okno_naprawy(con):
    from horreum.gui.app import RepairHeaderDialog
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    dlg._runner.async_ok = False
    return dlg


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_FITS_z_suma_kontrolna_POMINIETY_przed_zapisem_z_folderem(qapp, tmp_path,
                                                                                lang):
    """AR-163: folder mieszany (4 bez sumy, 2 z `CHECKSUM`/`DATASUM`) - podgląd liczy 4 do zapisu,
    przycisk „Zapisz karty (4)”, a 2 stoją na liście pominiętych z folderem i powodem w języku UI;
    folder z samymi takimi plikami mówi „cały folder”. Zapis nie dotyka plików z sumą i nie kończy
    się „2 zablokowane”. Falsyfikator: zdejmij `fits_checksum_gate` z `_split_rows` → (6)."""
    from horreum.gui.wb_worker import _liczba
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "s.db"))
    root = tmp_path / "ASTRO_"
    _lighty(root, con, "NGC7635", 4, baza=1)
    sumy = _lighty(root, con, "NGC7635", 2, baza=2, suma=True)
    sumy += _lighty(root, con, "IC405", 2, baza=3, suma=True)
    przed = {p: p.read_bytes() for p in sumy}
    dlg = _okno_naprawy(con)
    assert [len(g["rows"]) for g in dlg._groups] == [4]
    assert dlg.save_btn.text() == i18n.t("repair.save_btn_n", n=4) and dlg.save_btn.isEnabled()
    powod = i18n.t("objchg.item.fits_checksum")         # powód rdzenia bramki sumy (AR-167)
    pozycje = sorted(dlg.skipped_list.item(i).text() for i in range(dlg.skipped_list.count()))
    assert pozycje == sorted([
        i18n.t_plural("repair.skip.checksum", 2, folder="NGC7635\\RC8_2600MC\\OSC", reason=powod),
        i18n.t_plural("repair.skip.checksum_all", 2, folder="IC405\\RC8_2600MC\\OSC",
                      reason=powod)]), pozycje
    dlg._on_save()
    assert dlg.status.text().startswith(_liczba("grid.wb.applied", 4)), dlg.status.text()
    assert _liczba("grid.wb.blocked", 2) not in dlg.status.text(), dlg.status.text()
    assert all(p.read_bytes() == b for p, b in przed.items())
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_folder_TYLKO_z_suma_mowi_wprost_i_nie_ma_czego_zapisac(qapp, tmp_path,
                                                                              lang):
    """AR-163: okno nad samymi plikami z sumą - zero grup, przycisk bez liczby i wygaszony, lista
    pominiętych mówi „cały folder pominięty” z odmienioną liczbą (1, 2-4, 5)."""
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "t.db"))
    _lighty(tmp_path / "ASTRO_", con, "IC405", 5, baza=4, suma=True)
    dlg = _okno_naprawy(con)
    assert dlg._groups == []
    assert dlg.save_btn.text() == i18n.t("repair.save_btn") and not dlg.save_btn.isEnabled()
    assert [dlg.skipped_list.item(i).text() for i in range(dlg.skipped_list.count())] == [
        i18n.t_plural("repair.skip.checksum_all", 5, folder="IC405\\RC8_2600MC\\OSC",
                      reason=i18n.t("objchg.item.fits_checksum"))]
    dlg.reject()
    con.close()
    caly = {"pl": "X: cały folder pominięty ({}) - r", "en": "X: whole folder skipped ({}) - r"}
    oczek = {"pl": ["1 plik", "2 pliki", "5 plików", "12 plików", "22 pliki"],
             "en": ["1 file", "2 files", "5 files", "12 files", "22 files"]}[lang]
    assert [i18n.t_plural("repair.skip.checksum_all", n, folder="X", reason="r")
            for n in (1, 2, 5, 12, 22)] == [caly[lang].format(o) for o in oczek]
    assert [i18n.t_plural("repair.skip.checksum", n, folder="X", reason="r")
            for n in (1, 2, 5, 12, 22)] == {
        "pl": ["X: 1 plik pominięty - r", "X: 2 pliki pominięte - r", "X: 5 plików pominiętych - r",
               "X: 12 plików pominiętych - r", "X: 22 pliki pominięte - r"],
        "en": ["X: 1 file skipped - r", "X: 2 files skipped - r", "X: 5 files skipped - r",
               "X: 12 files skipped - r", "X: 22 files skipped - r"]}[lang]


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_cofniecie_z_BLEDEM_mowi_powod_w_jezyku_UI_i_zostawia_Cofnij(
        qapp, tmp_path, monkeypatch, lang):
    """AR-160: cofnięcie, którego re-sync pada (czkawka udziału), kończy się `failed` z receptą
    rdzenia „ponowne undo dokończy”. Dawniej okno mówiło same liczniki i chowało „Cofnij” - z nim
    jedyny uchwyt ponowienia. Teraz zdanie niesie powód w języku UI i receptę, „Cofnij” zostaje
    przy tym samym commicie, zapis milczy, a drugi klik kończy cofnięcie i dopiero on chowa
    przycisk. Falsyfikator: bezwarunkowe `undo_btn.setVisible(False)` w `_after_undo`."""
    from astropy.io import fits
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "c.db"))
    pliki = _lighty(tmp_path / "ASTRO_", con, "NGC7635", 2, baza=5)
    dlg = _okno_naprawy(con)
    dlg._on_save()
    commit_id = dlg._commit_id
    assert commit_id is not None and dlg.undo_btn.isVisibleTo(dlg)
    with monkeypatch.context() as m:
        m.setattr(writeback.scan, "scan_file",
                  lambda path, **kw: (_ for _ in ()).throw(OSError(64, "broken share")))
        dlg._on_undo()
    tekst = dlg.status.text()
    assert "broken share" in tekst, tekst
    assert i18n.t("grid.wb.undo_retry", undo=i18n.t("grid.action.undo")) in tekst, tekst
    if lang == "en":
        assert not set(tekst) & _ZNAKI_PL, tekst
    assert dlg.undo_btn.isVisibleTo(dlg) and dlg._commit_id == commit_id
    assert not dlg.save_btn.isEnabled()
    dlg._on_undo()                                       # ponowienie kończy cofnięcie
    assert not dlg.undo_btn.isVisibleTo(dlg) and dlg._commit_id is None
    assert dlg.save_btn.isEnabled()
    assert all(fits.getheader(str(p)).get("OBJECT") is None for p in pliki)
    dlg.reject()
    con.close()


def test_Napraw_naglowek_cofniecie_PRZERWANE_zostawia_Cofnij_a_ponowienie_konczy(
        qapp, tmp_path, monkeypatch):
    """AR-160 (cancelled): anulowanie przerywa pętlę rdzenia PRZED kolejnymi backupami - jeden plik
    wrócił, drugi nie (`restored` + `cancelled`), więc commit nie jest cofnięty. „Cofnij” zostaje,
    zdanie mówi o przerwaniu i o plikach do sprawdzenia, bez obietnicy wyniku; ponowienie kończy i chowa
    przycisk. Falsyfikator: reguła „Cofnij zostaje” tylko przy `failed`."""
    from astropy.io import fits
    from horreum.gui.wb_worker import WritebackWorker, _liczba
    con = db.open_db(str(tmp_path / "p.db"))
    pliki = _lighty(tmp_path / "ASTRO_", con, "NGC7635", 2, baza=6)
    dlg = _okno_naprawy(con)
    dlg._on_save()
    commit_id = dlg._commit_id
    pytania = []

    def _po_pierwszym():
        pytania.append(1)
        return len(pytania) > 1

    with monkeypatch.context() as m:
        m.setitem(WritebackWorker._OPS, "undo", lambda c, t, now, pr, sc: writeback.undo(
            c, t, now=now, progress=pr, should_cancel=_po_pierwszym))
        dlg._on_undo()
    tekst = dlg.status.text()
    assert _liczba("grid.wb.restored", 1) in tekst, tekst
    # Rdzeń zna resztę (AR-176): 1 nieprzetworzony plik wymaga sprawdzenia - bez obietnicy.
    assert i18n.t_plural("wb.undo_cancelled_check", 1, undo=i18n.t("grid.action.undo")) in tekst, \
        tekst
    assert dlg.undo_btn.isVisibleTo(dlg) and dlg._commit_id == commit_id
    assert not dlg.save_btn.isEnabled()
    assert sorted(fits.getheader(str(p)).get("OBJECT") is None for p in pliki) == [False, True]
    dlg._on_undo()
    assert not dlg.undo_btn.isVisibleTo(dlg) and dlg._commit_id is None
    assert all(fits.getheader(str(p)).get("OBJECT") is None for p in pliki)
    dlg.reject()
    con.close()


def test_Napraw_naglowek_cofniecie_ZABLOKOWANE_bez_juz_cofnietego_zostawia_Cofnij_i_zapis_milczy(
        qapp, tmp_path):
    """AR-160 (domknięcie z rdzenia): plik zmieniony od commitu - blokada cofnięcia, karta zostaje.
    Dawniej okno chowało „Cofnij”, zerowało commit i oddawało „Zapisz karty” nad plikiem z kartą.
    Teraz uchwyt zostaje, zapis milczy; ponowienie, w którym drugi plik jest już „już cofnięty”
    (`UndoResult.already`), a pierwszy dalej zablokowany - nadal niedomknięte.
    Falsyfikator: reguła ogona `failed or cancelled` → asercja widoczności."""
    from astropy.io import fits
    con = db.open_db(str(tmp_path / "b.db"))
    pliki = _lighty(tmp_path / "ASTRO_", con, "NGC7635", 2, baza=7)
    dlg = _okno_naprawy(con)
    dlg._on_save()
    commit_id = dlg._commit_id
    fits.setval(str(pliki[0]), "TELESCOP", value="Inny")           # cudza zmiana po commicie
    dlg._on_undo()
    assert dlg.undo_btn.isVisibleTo(dlg) and dlg._commit_id == commit_id
    assert not dlg.save_btn.isEnabled()
    assert i18n.t("grid.wb.undo_retry", undo=i18n.t("grid.action.undo")) in dlg.status.text()
    assert fits.getheader(str(pliki[0])).get("OBJECT") is not None
    assert fits.getheader(str(pliki[1])).get("OBJECT") is None
    dlg._on_undo()                                       # drugi plik „już cofnięty”, pierwszy nie
    assert dlg.undo_btn.isVisibleTo(dlg) and not dlg.save_btn.isEnabled()
    dlg.reject()
    con.close()


def _czekaj_na_uchwyt(dlg, limit_s=20.0):
    """Bieg w PRAWDZIWYM wątku: pętla zdarzeń, aż uchwyt zgłosi koniec (`busy_changed(False)`)."""
    koniec = time.monotonic() + limit_s
    while dlg._runner.is_busy:
        assert time.monotonic() < koniec, "uchwyt nie skończył biegu"
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()


def test_Napraw_naglowek_po_udanym_cofnieciu_W_WATKU_zapis_aktywny_bez_klikniec(qapp, tmp_path):
    """Wizytacja W1 (P1): po udanym cofnięciu „Zapisz karty (N)” zostawał wygaszony - ogon cofnięcia
    przychodzi, gdy uchwyt jest jeszcze zajęty (wątek sprząta się po `done`), a końca biegu nikt
    nie przeliczał. Prawdziwy `QThread` (bez `async_ok=False`): zapis, cofnięcie, koniec biegu -
    przycisk aktywny z liczbą. Falsyfikator: zdejmij przeliczenie po `busy_changed(False)`."""
    con = db.open_db(str(tmp_path / "w1.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 2, baza=8)
    from horreum.gui.app import RepairHeaderDialog
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    assert dlg._runner.async_ok
    dlg._on_save()
    _czekaj_na_uchwyt(dlg)
    assert dlg._commit_id is not None and not dlg.save_btn.isEnabled()
    dlg._on_undo()
    _czekaj_na_uchwyt(dlg)
    assert dlg._commit_id is None
    assert dlg.save_btn.isEnabled() and dlg.save_btn.text() == i18n.t("repair.save_btn_n", n=2)
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_rozne_powody_stoja_w_podpowiedzi_a_zdanie_do_niej_odsyla(qapp, tmp_path,
                                                                                lang):
    """Wizytacja W3: okno bez listy pozycji mówiło „pierwszy z 2 różnych powodów: …”, a drugiego
    powodu nie było nigdzie. Teraz zdanie odsyła do podpowiedzi, a ta niesie każdy różny powód
    w języku UI z plikiem, który go dostał. Jeden powód - bez odsyłacza i bez listy.
    Falsyfikator: `podpowiedz_kart` bez `podpowiedz_powodow` → drugi powód nigdzie."""
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import PowodPozycji
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "w3.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 2, baza=9)
    dlg = _okno_naprawy(con)
    zmieniony = PowodPozycji("header_hash mismatch", "header_hash_mismatch")
    juz = PowodPozycji("już cofnięte - cały plik i baza opisują stan sprzed commitu",
                       "undo_already")
    b1 = writeback.FileResult(1, "X:/L/a.fits", "blocked", zmieniony)
    b2 = writeback.FileResult(2, "X:/L/b.fits", "blocked", juz)
    dlg._after_commit("commit_inplace", writeback.CommitResult("r", None, [], [b1, b2], [], []))
    assert dlg.status.text().endswith(i18n.t("wb.reasons_tip")), dlg.status.text()
    # Protokół pola (AR-204): szczegół = wiersze powodów, podpowiedź = zdanie + szczegół.
    assert dlg.status.szczegol().splitlines() == [
        i18n.t("wb.reason_line", file="a.fits", reason=tekst_powodu(zmieniony)),
        i18n.t("wb.reason_line", file="b.fits", reason=tekst_powodu(juz))]
    assert dlg.status.toolTip() == dlg.status.text() + "\n" + dlg.status.szczegol()
    dlg._after_commit("commit_inplace", writeback.CommitResult("r", None, [], [b1], [], []))
    assert i18n.t("wb.reasons_tip") not in dlg.status.text() and dlg.status.szczegol() == ""
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zdanie_cofniecia_liczy_JUZ_COFNIETE_osobno_a_nie_jako_blokady(lang):
    """Wizytacja W4: dokończone ponowienie brzmiało jak porażka („1 przywrócony · 33 zablokowane -
    już cofnięte”). Pliki z `UndoResult.already` mają własny człon (odmiana 1, 2-4, 5, 12-14, 22),
    a powód ogona pomija „już cofnięte” (człon mówi to samo); blokada spoza `already` zostaje
    blokadą z powodem. Bez `already` zdanie znak w znak jak dotąd.
    Falsyfikator: `zdanie_undo_kart` liczy `blocked` w całości → „zablokowane” w pierwszej asercji."""
    from horreum.gui.wb_worker import _liczba, ogon_cofniecia, zdanie_undo_kart
    i18n.set_lang(lang)
    wrocil = writeback.FileResult(1, "X:/L/a.fits", "restored")
    juz = [writeback.FileResult(10 + i, f"X:/L/j{i}.fits", "blocked", "już cofnięte")
           for i in range(33)]
    zmieniony = writeback.FileResult(9, "X:/L/z.fits", "blocked", "header_hash mismatch")
    dokonczone = writeback.UndoResult(1, [wrocil], juz, [], already=juz)
    msg, ponow = ogon_cofniecia(dokonczone, "Cofnij")
    assert msg == _liczba("grid.wb.restored", 1) + " · " + _liczba("wb.undo_already", 33), msg
    assert not ponow
    mieszane = writeback.UndoResult(1, [wrocil], juz + [zmieniony], [], already=juz)
    msg, ponow = ogon_cofniecia(mieszane, "Cofnij")
    assert (_liczba("wb.undo_already", 33) + " · " + _liczba("grid.wb.blocked", 1)) in msg, msg
    assert "z.fits" in msg and ponow
    bez = writeback.UndoResult(1, [wrocil], [zmieniony], [])
    assert zdanie_undo_kart(bez) == _liczba("grid.wb.restored", 1) + " · " + _liczba(
        "grid.wb.blocked", 1)
    oczek = {"pl": ["1 już cofnięty", "2 już cofnięte", "5 już cofniętych", "12 już cofniętych",
                    "22 już cofnięte"],
             "en": ["1 already undone", "2 already undone", "5 already undone",
                    "12 already undone", "22 already undone"]}[lang]
    assert [_liczba("wb.undo_already", n) for n in (1, 2, 5, 12, 22)] == oczek


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zdanie_wyniku_przy_ROZNYCH_powodach_mowi_pierwszy_z_N_a_przy_jednym_bez_zmian(lang):
    """AR-162: „2 zablokowane - plik zmieniony od skanu” przy dwóch RÓŻNYCH powodach brzmiało jak
    powód wspólny. Różne kody (albo teksty bez kodu) → „pierwszy z N różnych powodów: …”; ten sam
    kod z innymi parametrami albo ten sam tekst → zdanie znak w znak jak dotąd. To samo zdanie mówi
    „Zmień obiekt…” (`zdanie_wyniku_zmiany` woła wspólną funkcję).
    Falsyfikator: `rozne` liczone zawsze jako 1 → pierwsza asercja."""
    from horreum.gui.object_change_dialog import zdanie_wyniku_zmiany
    from horreum.gui.wb_worker import _liczba, tekst_powodu, zdanie_wyniku_zapisu
    from horreum.item_reasons import PowodPozycji
    i18n.set_lang(lang)

    def _zdanie(*powody):
        zablokowane = [writeback.FileResult(i, f"X:/L/{i}.fits", "blocked", p)
                       for i, p in enumerate(powody)]
        return zdanie_wyniku_zapisu(writeback.CommitResult("r", None, [], zablokowane, [], []),
                                    "grid.wb.applied")

    def _oczek(n, detail):
        return (_liczba("grid.wb.applied", 0) + " · " + _liczba("grid.wb.blocked", n)
                + i18n.t("grid.wb.detail_sep", detail=detail))

    zmieniony = PowodPozycji("header_hash mismatch", "header_hash_mismatch")
    juz = PowodPozycji("już cofnięte - cały plik i baza opisują stan sprzed commitu",
                       "undo_already")
    suma1 = PowodPozycji("FITS z sumą kontrolną (CHECKSUM) - zapis nagłówka unieważniłby ją, a "
                         "pisarz jej nie przelicza", "checksum_present", sums=["CHECKSUM"])
    suma2 = PowodPozycji("FITS z sumą kontrolną (CHECKSUM, DATASUM) - zapis nagłówka unieważniłby "
                         "ją, a pisarz jej nie przelicza", "checksum_present",
                         sums=["CHECKSUM", "DATASUM"])
    rozne = i18n.t("wb.reasons_first", n=2, detail=tekst_powodu(zmieniony))
    assert _zdanie(zmieniony, juz) == _oczek(2, rozne)
    assert _zdanie(zmieniony, juz, zmieniony) == _oczek(3, rozne)       # liczy RÓŻNE, nie pozycje
    assert _zdanie(suma1, suma2) == _oczek(2, tekst_powodu(suma1))      # ten sam kod - bez zmian
    assert _zdanie(zmieniony) == _oczek(1, tekst_powodu(zmieniony))
    assert _zdanie("cel zajęty", "plik zmieniony") == _oczek(
        2, i18n.t("wb.reasons_first", n=2, detail=tekst_powodu("cel zajęty")))
    assert _zdanie("cel zajęty", "cel zajęty") == _oczek(2, tekst_powodu("cel zajęty"))
    zmiana = zdanie_wyniku_zmiany(_Wynik("r", applied=[], blocked=[
        _fr(1, "blocked", zmieniony), _fr(2, "blocked", juz)], failed=[], skipped=[]))
    assert rozne in zmiana, zmiana


# ═══════════════════════════════════════════════ AR-155: droga dopisania karty FITS per pozycja


def _lid(con, fid):
    return con.execute("SELECT id FROM location WHERE frame_id = ? AND present = 1",
                       (fid,)).fetchone()[0]


def test_podglad_mowi_droge_dopisania_FITS_PER_POZYCJA_a_pisarz_ja_potwierdza(qapp, archiwum):
    """AR-155: podgląd mówił ogólnie „karta dopisana w miejscu, gdy plik na to pozwala; inaczej
    cały plik przepisany albo odmowa” przy KAŻDYM dopisaniu do FITS. Teraz z lustra kart obecnej
    kopii per pozycja: zapas za `END` - „w miejscu”, pełny ostatni blok bez pustej karty - „cały
    plik przepisany” z powodem pisarza w podpowiedzi; zdanie ogólne pod listą znika, bo żadna
    pozycja nie „zależy od pliku”. Zapis na PRAWDZIWYM sterowniku potwierdza obie prognozy: plik
    z zapasem zostaje tym samym plikiem (`st_ino`), plik bez zapasu nie.
    Falsyfikator: prognoza zawsze „zależy od pliku” (dawne zachowanie) → asercje znaczników."""
    from horreum.gui.wb_worker import tekst_powodu
    a = archiwum
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", seed=2)
    fc, pc = a.fits(r"LIGHTS\NGC3034\RC6\OSC\c.fits", date="2022-03-26T21:32:00", seed=3,
                    bez_zapasu=True)
    ino = {pb: os.stat(pb).st_ino, pc: os.stat(pc).st_ino}
    dlg = _okno(qapp, a.con, target=queries.object_target(a.con, "M 44"), frame_ids=[fb, fc])
    w = [dlg.items_tree.topLevelItem(i) for i in range(2)]
    zmiana = i18n.t("objchg.card_change", old=i18n.t("objchg.card_absent"), new="'NGC 2632'")
    assert w[0].text(2) == zmiana + i18n.t("objchg.card_add_fits_inplace_short")
    assert w[1].text(2) == zmiana + i18n.t("objchg.card_add_fits_rewrite_short")
    assert dlg._drogi[_lid(a.con, fb)] is None
    powod = dlg._drogi[_lid(a.con, fc)]
    assert (powod.code, dict(powod.params)["free"]) == ("fb_no_room", 0)
    assert w[0].toolTip(2) == f"{w[0].text(2)}\n{i18n.t('objchg.card_add_fits_inplace')}"
    assert w[1].toolTip(2) == (f"{w[1].text(2)}\n"
                               f"{i18n.t('objchg.card_add_fits_rewrite', reason=tekst_powodu(powod))}")
    assert dlg.card_note.isHidden()
    dlg.action_btn.click()
    nowe = a.root / r"LIGHTS\NGC2632\RC6\OSC"
    assert [os.stat(nowe / n).st_ino == ino[s] for n, s in (("b.fits", pb), ("c.fits", pc))] \
        == [True, False]
    assert i18n.t("wb.inplace_fallback", n=1) in dlg.status.text()     # spadek tylko pliku c
    dlg.reject()


def test_podglad_BEZ_lustra_kopii_mowi_zalezy_od_pliku_zdaniem_pod_lista(qapp, archiwum):
    """Pozycja, której lustro kart nie opisuje obecnej kopii (tu: klatka bez wierszy `cards`),
    dostaje dzisiejszy znacznik ogólny i zdanie „zależy od pliku” pod listą i w podpowiedzi;
    sąsiednia pozycja z lustrem mówi swoją drogę. Zdanie ogólne stoi tylko dla takich pozycji."""
    a = archiwum
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", seed=2)
    fd, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\d.fits", date="2022-03-26T21:33:00", seed=4)
    a.con.execute("DELETE FROM cards WHERE frame_id = ?", (fd,))
    a.con.commit()
    dlg = _okno(qapp, a.con, target=queries.object_target(a.con, "M 44"), frame_ids=[fb, fd])
    w = [dlg.items_tree.topLevelItem(i) for i in range(2)]
    assert w[0].text(2).endswith(i18n.t("objchg.card_add_fits_inplace_short"))
    assert w[1].text(2).endswith(i18n.t("objchg.card_add_fits_short"))
    assert dlg._drogi[_lid(a.con, fd)].code == "route_depends"
    assert [i18n.t("objchg.card_add_fits") in x.toolTip(2) for x in w] == [False, True]
    assert dlg.card_note.text() == i18n.t("objchg.card_add_fits") and not dlg.card_note.isHidden()
    dlg.reject()


def test_przerwany_przebieg_z_bazy_mowi_stan_HISTORYCZNY_nie_prognoze(qapp, archiwum, monkeypatch):
    """AR-155: okno otwarte na przebiegu z Porządków (`run_id`) renderuje pozycje z
    `queries.object_change_run_view` - bez faktów prognozy. Tam stoi dzisiejsze zdanie ogólne
    (znacznik „dopisanie karty”, podpowiedź „zależy od pliku”), choć plik ma zapas i świeży podgląd
    powiedziałby „w miejscu”; prognozy ta ścieżka nie liczy wcale."""
    from horreum.gui import object_change_dialog as ocd
    a = archiwum
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", seed=2)
    plan, _ = ocd.policz_plan(a.con, [fb], target=queries.object_target(a.con, "M 44"))
    assert ocd.drogi_dopisania(a.con, plan) == {_lid(a.con, fb): None}     # świeża prognoza
    repo.stage_object_change(a.con, plan=plan, now=NOW)

    def _nie_wolno(*_a, **_k):
        raise AssertionError("ścieżka przebiegu z bazy nie liczy prognozy drogi")
    monkeypatch.setattr(ocd, "drogi_dopisania", _nie_wolno)
    dlg = ocd.ObjectChangeDialog(a.con, run_id=plan.run_id, now_fn=lambda: NOW, off_thread=False)
    w = dlg.items_tree.topLevelItem(0)
    assert w.text(2) == (i18n.t("objchg.card_change", old=i18n.t("objchg.card_absent"),
                                new="'NGC 2632'") + i18n.t("objchg.card_add_fits_short"))
    assert w.toolTip(2) == f"{w.text(2)}\n{i18n.t('objchg.card_add_fits')}"
    dlg.reject()


def test_lustro_kart_obecnej_kopii_tylko_gdy_opisuje_JEJ_naglowek(archiwum):
    """`queries.present_copy_card_mirror`: `cards` należą do klatki, nie do kopii. Lustro wraca,
    gdy każda kopia klatki ma jeden `header_hash` i nie czeka zapis z zeznaniem wstrzymanym; inna
    kopia z innym nagłówkiem (także nieobecna), kopia bez `header_hash` i otwarty `withheld_write`
    dają `None` (podgląd: „zależy od pliku”). Klatka nieznana też `None`."""
    import collections
    from astropy.io import fits
    from horreum import scan
    a = archiwum
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", seed=2)
    with fits.open(str(pb)) as h:
        oczekiwane = [(c.keyword, c.value_raw, c.value_type, c.comment)
                      for c in scan._parse_cards(h[0].header)]
    lustro = queries.present_copy_card_mirror(a.con, [fb, 999])
    assert collections.Counter(lustro[fb]) == collections.Counter(oczekiwane)
    assert lustro[999] is None
    hh = a.con.execute("SELECT header_hash FROM location WHERE frame_id = ?", (fb,)).fetchone()[0]
    for naglowek, oczekiwany in (("inny", None), (None, None), (hh, "lustro")):
        a.con.execute("DELETE FROM location WHERE frame_id = ? AND present = 0", (fb,))
        a.con.execute("INSERT INTO location(frame_id, volume, path, present, header_hash) "
                      "VALUES (?, 'VOL', 'X:\\L\\stara.fits', 0, ?)", (fb, naglowek))
        wynik = queries.present_copy_card_mirror(a.con, [fb])[fb]
        assert (wynik is None) == (oczekiwany is None), naglowek
    a.con.execute("INSERT INTO commits(id, run_id) VALUES (77, 'r-wstrzymany')")
    a.con.execute("INSERT INTO withheld_write(kind, location_id, frame_id, commit_id, header_hash, "
                  "object_written, reason, actor, opened_at) "
                  "VALUES ('commit', ?, ?, 77, ?, 0, 'test', 'user:local', ?)",
                  (_lid(a.con, fb), fb, hh, NOW))
    assert queries.present_copy_card_mirror(a.con, [fb])[fb] is None
    a.con.execute("UPDATE withheld_write SET settled_at = ?, settled_how = 'completed'", (NOW,))
    assert queries.present_copy_card_mirror(a.con, [fb])[fb] is not None


# ═══════════════════════════════════════════════ AR-177: okno na obiekcie-regionie (Veil)


def _niebo(con, root, rel, *, obj=None, ra=312.75, dec=30.67, seed=0):
    """Light FITS pod `root/rel` z kartą `obj` (None = bez karty) i współrzędnymi (`ra` None = bez)
    wciągnięty skanem; zwraca `frame_id`. Domyślne współrzędne = środek regionu Veil."""
    import numpy as np
    from astropy.io import fits
    from horreum import scan
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + seed)
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["DATE-OBS"] = f"2023-08-22T20:{seed:02d}:00"
    if obj is not None:
        hdu.header["OBJECT"] = obj
    if ra is not None:
        hdu.header["RA"], hdu.header["DEC"] = ra, dec
    hdu.writeto(str(p))
    scan.ingest_record(con, scan.scan_file(str(p)), volume="VOL", now=NOW,
                       summary=scan.ScanSummary())
    return con.execute("SELECT frame_id FROM location WHERE path = ?", (str(p),)).fetchone()[0]


def _pominiecia(dlg):
    return [dlg.skipped_tree.topLevelItem(i).text(0)
            for i in range(dlg.skipped_tree.topLevelItemCount())]


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Zmien_obiekt_na_Veil_otwiera_okno_a_klatka_spoza_regionu_mowi_powod(qapp, tmp_path, lang):
    """AR-177: cel Veil (obiekt-region) ma formę karty, więc okno „Zmień obiekt…” się otwiera
    (dawniej odmowa przed oknem) na PRAWDZIWYM read-modelu i planerze: klatka w regionie jedzie
    z kartą, klatka spoza regionu stoi w pominięciach ze zdaniem bramki `region_outside` w języku
    UI. Falsyfikator: brak wpisu katalogu w danym języku - zdanie rdzenia PL albo `KeyError`."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "veil.db"))
    root = tmp_path / "ASTRO_"
    w = _niebo(con, root, r"LIGHTS\NGC6992\cam\NGC6992_1.fits", obj="NGC6992", seed=1)
    poza = _niebo(con, root, r"LIGHTS\M31\cam\M31_2.fits", obj="M 31", ra=10.68, dec=41.27, seed=2)
    _niebo(con, root, r"LIGHTS\Veil\cam\Veil_3.fits", seed=3)            # obiekt Veil z regionu
    resolver.run_resolver(con, NOW)
    cel = queries.object_target(con, "Veil")
    assert cel is not None and cel.card_form == "Veil"
    dlg = ObjectChangeDialog(con, frame_ids=[w, poza], target=cel, now_fn=lambda: NOW,
                             off_thread=False)
    assert dlg.error.text() == "" and dlg.items_tree.topLevelItemCount() == 1
    (powod,) = _pominiecia(dlg)
    assert CATALOG["objchg.gate.region_outside"][lang] in powod, powod
    if lang == "en":
        assert not set(powod) & set("ąćęłńóśźż"), powod
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Uzgodnij_forma_regionu_prowadzaca_do_innego_obiektu_mowi_prawdziwy_powod(qapp, tmp_path,
                                                                                lang):
    """AR-177: forma karty None ma po AR-177 drugą przyczynę - forma obiektu-regionu, którą drabina
    nazw oddaje INNEMU obiektowi (tu alias `VEIL` przy NGC6992). Zdanie bramki mówi przyczynę
    ogólnie („nie prowadzi z powrotem do tego obiektu”), nie „kanon znany tylko z aliasu”.
    Klatka z ręką przy Veil w „Uzgodnij” zostaje z tym powodem w języku UI, a „Zmień obiekt…”
    odmawia celu zdaniem `grid.sel.object_change_no_card`, też bez „aliasu”.
    Falsyfikator: dawne zdanie `form_not_canon` albo `object_change_no_card` (o aliasie) w katalogu."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "veil.db"))
    root = tmp_path / "ASTRO_"
    _niebo(con, root, r"LIGHTS\NGC6992\cam\NGC6992_1.fits", obj="NGC6992", seed=1)
    _niebo(con, root, r"LIGHTS\Veil\cam\Veil_2.fits", seed=2)              # obiekt Veil z regionu
    reka = _niebo(con, root, r"LIGHTS\Veil\cam\Veil_3.fits", ra=None, seed=3)
    resolver.run_resolver(con, NOW)
    repo.user_assign_object(con, alias_norm=None, canon="Veil", catalog="region", kind="region",
                            frame_ids=[reka], now=NOW)
    ngc = con.execute("SELECT id FROM object WHERE canon = 'NGC6992'").fetchone()[0]
    repo.add_object_alias(con, alias_norm="VEIL", object_id=ngc, source="user", now=NOW)
    assert resolver.forma_karty_object(con, "Veil") is None
    # „Zmień obiekt…” na taki cel odmawia przed oknem tym samym uogólnionym zdaniem.
    assert queries.object_target(con, "Veil").card_form is None
    odmowa = i18n.t("grid.sel.object_change_no_card", canon="Veil")
    assert "alias" not in odmowa.lower() and odmowa == CATALOG[
        "grid.sel.object_change_no_card"][lang].format(canon="Veil")
    dlg = ObjectChangeDialog(con, frame_ids=[reka], target=None, now_fn=lambda: NOW,
                             off_thread=False)
    assert dlg.items_tree.topLevelItemCount() == 0
    (powod,) = _pominiecia(dlg)
    assert CATALOG["objchg.gate.form_not_canon"][lang] in powod, powod
    assert "alias" not in powod.lower(), powod
    dlg.reject()
    con.close()


def test_Zatwierdz_ze_sciezki_pomija_karte_regionu_z_powodem(tmp_path):
    """AR-177: forma obiektu-regionu wraca tylko klatkom w regionie, a „Zatwierdź
    ze ścieżki…” (`app.plan_kart_sciezki`) nie pyta per klatka - karta regionu odpada tam z tym samym
    powodem co forma None (`path.card_skip.no_roundtrip`), dla każdej klatki, także tej w regionie.
    Kanon spoza regionów idzie dalej do silnika makr (kontrola). Falsyfikator: bramka bez warunku
    `kanony_regionow` - klatka spoza regionu dostaje kartę `Veil` w `touched`."""
    from horreum.gui import app as app_mod
    con = db.open_db(str(tmp_path / "veil.db"))
    root = tmp_path / "ASTRO_"
    w = _niebo(con, root, r"LIGHTS\Veil\cam\Veil_1.fits", seed=1)
    poza = _niebo(con, root, r"LIGHTS\Veil\cam\Veil_2.fits", ra=10.68, dec=41.27, seed=2)
    resolver.run_resolver(con, NOW)
    value, touched, skipped = app_mod.plan_kart_sciezki(con, "Veil", [w, poza])
    assert value == resolver.forma_karty_object(con, "Veil") == "Veil" and touched == []
    powod = i18n.t("path.card_skip.no_roundtrip", value="Veil", canon="Veil")
    assert skipped == [(w, "", powod), (poza, "", powod)]
    _value, touched, _skipped = app_mod.plan_kart_sciezki(con, "NGC7000", [poza])
    assert [t.new_value for t in touched] == ["NGC 7000"]
    con.close()


# ═══════════════════════════════════════════════ „Napraw nagłówek…”: status nie ucina zdania (AR-176)

@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_status_nie_ucina_zdania_wyniku(qapp, tmp_path, lang):
    """AR-176 (zmierzone natywnie): przy JEDNEJ grupie okno ma pion tylko na listę i rząd przycisków,
    a zdanie cofnięcia z błędem, blokadą, przerwaniem i receptą zawija się w kilka wierszy - etykieta
    statusu dostawała 44 px przy potrzebnych 64, okno nie rosło. Okno rośnie (tylko w górę) do
    zawiniętego zdania wspólnym pomocnikiem okien (`config_dialog.dopasuj_wysokosc`); reguła, nie
    piksele: etykieta ma co najmniej wysokość, której jej tekst potrzebuje przy jej szerokości.

    Falsyfikator: zdejmij `dopasuj_wysokosc(self)` z `RepairHeaderDialog._after_undo` → etykieta
    niższa niż `heightForWidth` (offscreen: 56 px przy 70)."""
    from horreum.gui.app import RepairHeaderDialog
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "n.db"))
    _bezimienne(tmp_path / "ASTRO_", con, ["NGC7635"])
    dlg = RepairHeaderDialog(con, rows=queries.nameless_frames(con),
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    dlg._runner.async_ok = False
    try:
        dlg.show()
        QCoreApplication.processEvents()
        wysokosc = dlg.height()
        sciezka = str(tmp_path / "NGC7635_20230103_200000_LIGHT_OSC_300s_FLATGRP_NOFLAT_.fits")
        dlugi = ("kopia nagłówka sprzed zapisu nie zgadza się z plikiem na dysku, a baza opisuje "
                 "jeszcze inny stan tej lokacji - ponowne cofnięcie sprawdzi plik raz jeszcze "
                 "i dokończy samą synchronizację bazy")
        res = writeback.UndoResult(
            4711, [writeback.FileResult(1, sciezka, "restored")],
            [writeback.FileResult(2, sciezka, "blocked", "plik zmieniony od commitu")],
            [writeback.FileResult(3, sciezka, "failed", dlugi)], cancelled=True)
        dlg._commit_id = res.commit_id
        dlg.undo_btn.setVisible(True)
        dlg.resolve_btn.setVisible(True)
        dlg._after_undo("undo", res)
        QCoreApplication.processEvents()
        s = dlg.status
        assert dlugi[:40] in s.text(), s.text()
        assert s.height() >= s.heightForWidth(s.width()), (s.height(), s.heightForWidth(s.width()))
        assert dlg.height() >= wysokosc                  # tylko w górę
    finally:
        dlg.reject()
        con.close()


# ═══════════════════════════════════════════════ AR-157: „Uzgodnij” przejmuje ujednolicenie karty


def test_drogi_i_suma_drog_zapisu_kart_klasyfikacja(con):
    """AR-157 krok (1): suma dróg zapisu kart planu - `None` w miejscu, `route_depends` i brak
    prognozy „zależy od pliku”, każdy inny powód pisarza (`fb_no_room`, `fb_card_too_long`) cały
    plik przepisany; pozycja bez karty się nie liczy. `drogi_kart` daje prognozę każdej karcie:
    XISF (podmiana i dopisanie) w miejscu, podmiana FITS bez lustra kopii - „zależy od pliku”.
    Falsyfikatory: powód pisarza liczony jako „zależy”, `drogi_kart` bez gałęzi XISF."""
    from horreum.gui import object_change_dialog as ocd
    from horreum.item_reasons import PowodPozycji
    plan = _plan(items=tuple(_pozycja(i) for i in range(1, 6)) + (_pozycja(6, karta=False),),
                 skipped=())
    drogi = {11: None, 12: PowodPozycji("x", "fb_no_room"), 13: PowodPozycji("x", "fb_card_too_long"),
             14: PowodPozycji("x", "route_depends")}
    assert ocd.sumy_drog(plan, drogi) == {"inplace": 1, "rewrite": 2, "depends": 2}
    xisf = dataclasses.replace(_pozycja(7), old_path=rf"{STARY}\f7.xisf")
    dodaj = dataclasses.replace(_pozycja(8), old_path=rf"{STARY}\f8.xisf", card_op="add")
    plan = _plan(items=(xisf, dodaj, _pozycja(9)), skipped=())
    drogi = ocd.drogi_kart(con, plan)
    assert drogi == {17: None, 18: None, 19: ocd._DROGA_NIEZNANA}
    assert ocd.sumy_drog(plan, drogi) == {"inplace": 2, "rewrite": 0, "depends": 1}


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_okno_mowi_sume_drog_zapisu_na_PRAWDZIWYM_planerze(qapp, archiwum, lang):
    """AR-157 krok (1): podgląd mówi SUMĘ dróg zapisu kart przed kliknięciem - dopisanie FITS
    z zapasem i podmiana karty FITS w miejscu, dopisanie bez zapasu - cały plik przepisany (dawny
    `in_place`/`fallback` martwego planu ujednolicenia). Po biegu suma się chowa - drogę pliku
    mówi jego status. Falsyfikator: `drogi_kart` bez gałęzi podmiany (podmiana „zależy od pliku”)."""
    from horreum.gui import object_change_dialog as ocd
    i18n.set_lang(lang)
    a = archiwum
    fb, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", seed=2)
    fc, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\c.fits", date="2022-03-26T21:32:00", seed=3,
                   bez_zapasu=True)
    fd, _ = a.fits(r"LIGHTS\NGC3034\RC6\OSC\d.fits", obj="NGC3034", date="2022-03-26T21:33:00",
                   seed=4)
    dlg = _okno(qapp, a.con, target=queries.object_target(a.con, "M 44"), frame_ids=[fb, fc, fd])
    assert sorted(it.card_op for it in dlg._plan.items) == ["add", "add", "set"]
    assert ocd.sumy_drog(dlg._plan, dlg._drogi) == {"inplace": 2, "rewrite": 1, "depends": 0}
    assert dlg.routes.text() == i18n.t("objchg.routes", inplace=2, rewrite=1, depends=0)
    assert not dlg.routes.isHidden()
    if lang == "en":
        assert not set(dlg.routes.text()) & set("ąćęłńóśźż"), dlg.routes.text()
    dlg.action_btn.click()
    assert dlg.routes.isHidden()
    dlg.reject()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Uzgodnij_klatka_z_kilkoma_kopiami_jest_w_wierszu_i_mowi_powod(qapp, tmp_path, lang):
    """AR-157 krok (2): klatka z dwiema obecnymi kopiami (jedna w złym folderze) jest w wierszu
    „Plik nie zgadza się z obiektem”, a okno „Uzgodnij” na PRAWDZIWYM read-modelu i planerze mówi
    jej powód (`objchg.skip.many_copies`) w języku UI i niczego nie pisze. Do AR-157 wiersz gubił
    ją po cichu. Falsyfikator: brak wpisu katalogu w danym języku."""
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "kopie.db"))
    root = tmp_path / "ASTRO_"
    fid = _niebo(con, root, r"LIGHTS\NGC6992\cam\NGC6992_1.fits", obj="NGC 6992", ra=None, seed=1)
    repo.add_location(con, frame_id=fid, volume="VOL", path=str(root / r"LIGHTS\Zly\cam\x.fits"),
                      mtime="m", now=NOW)
    resolver.run_resolver(con, NOW)
    assert fid in queries.file_object_mismatch_frame_ids(con)
    dlg = ObjectChangeDialog(con, frame_ids=[fid], target=None, now_fn=lambda: NOW,
                             off_thread=False)
    assert dlg.items_tree.topLevelItemCount() == 0
    (powod,) = _pominiecia(dlg)
    assert CATALOG["objchg.skip.many_copies"][lang].format(n=2) in powod, powod
    if lang == "en":
        assert not set(powod) & set("ąćęłńóśźż"), powod
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_recepta_kopii_ta_sama_w_wierszu_Duplikaty_i_w_oknie_Uzgodnij(qapp, tmp_path, lang):
    """AR-157 krok (2): droga od klatki z kilkoma obecnymi kopiami do jednej to JEDNA recepta -
    podpowiedź wiersza Porządków „Duplikaty” i zdanie okna „Uzgodnij” pod pominięciem
    `many_copies` niosą ten sam tekst, w obu językach; nazwy w recepcie to te, które UI pokazuje
    (perspektywa, strona Dostawy, przyciski sprawdzenia obecności i oznaczenia zniknięć - z katalogu).
    Falsyfikatory: brak wpisu wiersza w `_PODPOWIEDZI_OSI` (pusta podpowiedź), zdanie okna bez
    recepty, zdanie okna niewidoczne, brak wpisu EN."""
    from horreum.gui import rows
    from horreum.gui import tasks as tasks_mod
    from horreum.gui.object_change_dialog import ObjectChangeDialog
    from PySide6.QtCore import Qt
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "kopie.db"))
    root = tmp_path / "ASTRO_"
    fid = _niebo(con, root, r"LIGHTS\NGC6992\cam\NGC6992_1.fits", obj="NGC 6992", ra=None, seed=1)
    repo.add_location(con, frame_id=fid, volume="VOL", path=str(root / r"LIGHTS\Zly\cam\x.fits"),
                      mtime="m", now=NOW)
    resolver.run_resolver(con, NOW)
    tv = tasks_mod.TasksView(con)
    try:
        tv.refresh_counts()
        wiersz = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                      if tv.tasks.item(i).data(Qt.UserRole) == "dup_frames")
        assert wiersz.data(rows.SECONDARY).startswith("1")
        recepta = wiersz.toolTip()
    finally:
        tv.close()
    for nazwa in ("perspective.dups", "nav.dostawa", "pipeline.btn.presence",
                  "pipeline.btn.mark_vanished"):
        assert i18n.t(nazwa) in recepta, (nazwa, recepta)
    dlg = ObjectChangeDialog(con, frame_ids=[fid], target=None, now_fn=lambda: NOW,
                             off_thread=False)
    assert not dlg.copies_hint.isHidden()
    assert dlg.copies_hint.text() == i18n.t("objchg.many_copies_hint", recipe=recepta)
    assert recepta in dlg.copies_hint.text()
    if lang == "en":
        assert not set(dlg.copies_hint.text()) & set("ąćęłńóśźż"), dlg.copies_hint.text()
    dlg.reject()
    con.close()


# ═══════════════════════════════════════════════ odmowa stagingu w języku UI (AR-200)

# PRAWDZIWY staging zapamiętany przy imporcie modułu - fikstura `rdzen` podmienia go atrapą.
_STAGING_PRAWDZIWY = repo.stage_object_change
_POLSKIE_LITERY = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _klik_akcji(dlg):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dlg.show()
    QTest.mouseClick(dlg.action_btn, Qt.LeftButton)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_staging_odmowa_klingi_z_powodem_mowi_w_jezyku_UI(qapp, con, rdzen, monkeypatch, lang):
    """Odmowa klingi z kodem (`OdmowaZPowodem` - tu prawdziwa odmowa konfliktu aliasu z `repo`)
    uciekająca ze stagingu mówi zdaniem kodu w języku UI, nie `ValueError: <proza PL>`; podpowiedź
    = samo zdanie (odmowa nie niesie szczegółu systemu). Falsyfikator: gałąź powodu w
    `zdanie_odmowy_stagingu` usunięta → proza PL w zdaniu EN."""
    from horreum.gui.wb_worker import tekst_powodu
    m42, _ = repo.upsert_object(con, canon="M42", catalog="M", kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="flamingstar", object_id=m42, source="user", now=NOW)
    odmowy = []

    def odmowa_klingi(con_, *, plan, now):
        try:
            repo._object_target(con_, "IC405", "flamingstar")
        except ValueError as exc:
            odmowy.append(exc)
            raise
    monkeypatch.setattr(repo, "stage_object_change", odmowa_klingi)
    try:
        i18n.set_lang(lang)
        dlg = _okno(qapp, con)
        _klik_akcji(dlg)
        (exc,) = odmowy
        assert exc.powod.code == "alias_conflict", exc
        zdanie = dlg.error.text()
        assert zdanie == i18n.t("objchg.err.stage", msg=tekst_powodu(exc.powod)), zdanie
        assert "ValueError" not in zdanie and dlg.error.toolTip() in ("", zdanie), dlg.error.toolTip()
        if lang == "en":
            assert not set(zdanie) & _POLSKIE_LITERY, zdanie
        assert rdzen.commity == [] and dlg.action_btn.isEnabled()
        dlg.reject()
    finally:
        i18n.set_lang("pl")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_staging_niespojny_plan_mowi_w_jezyku_UI_a_inwariant_w_szczegole(qapp, con, rdzen, monkeypatch,
                                                                        lang):
    """Plan łamiący inwariant stagingu (CAS ręki nie-trójką) - PRAWDZIWY `repo.stage_object_change`
    odmawia gołym `ValueError` (EXPECT, błąd programu): zdanie okna w języku UI
    (`objchg.err.stage_plan`), surowy tekst inwariantu z typem wyłącznie w szczególe technicznym pod
    kursorem (błąd programu `prog_error`, ta sama reguła co wyjątek planu). Falsyfikator: gałąź
    EXPECT mówiąca `tekst_powodu(powod)` → zdanie `prog_error` zamiast zdania stagingu."""
    import dataclasses
    rdzen.plany = [_plan(items=(dataclasses.replace(_pozycja(1), expected_object=(7, "header")),))]
    monkeypatch.setattr(repo, "stage_object_change", _STAGING_PRAWDZIWY)
    try:
        i18n.set_lang(lang)
        dlg = _okno(qapp, con)
        _klik_akcji(dlg)
        zdanie = dlg.error.text()
        assert zdanie == i18n.t("objchg.err.stage", msg=i18n.t("objchg.err.stage_plan")), zdanie
        szczegol = i18n.t("objchg.st.detail_tip",
                          detail="ValueError: frame:1: CAS ręki to trójca (object_id, object_source, "
                                 "object_cleared_id)")
        assert dlg.error.toolTip() == zdanie + "\n" + szczegol, dlg.error.toolTip()
        if lang == "en":
            assert not set(zdanie) & _POLSKIE_LITERY, zdanie
        assert con.execute("SELECT COUNT(*) FROM object_change_run").fetchone()[0] == 0
        assert rdzen.commity == [] and dlg.action_btn.isEnabled()
        dlg.reject()
    finally:
        i18n.set_lang("pl")


# ═══════════════════════════════════════════════ AR-209: EXPECT planera zmiany obiektu w języku UI

def _szpieg_reguly_okna(monkeypatch):
    """Wyjątki, które dotarły do reguły wyjątku okna (`powod_okna`) - dowód, że pole błędu mówi
    o wyjątku PRAWDZIWEGO rdzenia. Reguła działa dalej bez zmian."""
    from horreum.gui import object_change_dialog as ocd
    wyjatki, regula = [], ocd.powod_okna
    monkeypatch.setattr(ocd, "powod_okna", lambda exc: wyjatki.append(exc) or regula(exc))
    return wyjatki


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_plan_zmiany_obiektu_EXPECT_rdzenia_zdanie_w_jezyku_UI(qapp, con, monkeypatch, lang):
    """PRAWDZIWY read-model planu (`queries.object_change_rows`) rzuca goły `ValueError` „frame nie
    istnieje” (EXPECT: klatki nie znikają z bazy, wołający podał zły id) - pole błędu: „Plan się
    nie policzył:” ze zdaniem błędu programu w języku UI, proza rdzenia z typem wyłącznie
    w szczególe technicznym. Falsyfikator: `PlanWorker.run` z `blad_systemu(exc)` - `ValueError:
    <proza PL>` w zdaniu, także w UI EN."""
    wyjatki = _szpieg_reguly_okna(monkeypatch)
    try:
        i18n.set_lang(lang)
        dlg = _okno(qapp, con, target=None, frame_ids=[999])
        (exc,) = wyjatki
        assert type(exc) is ValueError and "999" in str(exc), exc
        zdanie = i18n.t("objchg.err.plan", msg=i18n.t("objchg.item.prog_error"))
        assert dlg.error.text() == zdanie, dlg.error.text()
        assert dlg.error.szczegol() == i18n.t("objchg.st.detail_tip", detail=f"ValueError: {exc}")
        if lang == "en":
            assert not set(zdanie) & _POLSKIE_LITERY, zdanie
        dlg.reject()
    finally:
        i18n.set_lang("pl")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_plan_zmiany_obiektu_wyjatek_z_callbacku_kolizji_mowi_bledem_programu(qapp, archiwum,
                                                                              monkeypatch, lang):
    """Wyjątek z callbacku, który planer woła przy kolizji celu w bazie (`location_at` z
    `queries.location_lookup`, `KeyError`) - ta sama reguła wyjątku okna: zdanie błędu programu
    w języku UI, `Typ: opis` w szczególe. Falsyfikator: `PlanWorker.run` bez `powod_okna`."""
    a = archiwum
    fa, _pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a.fits", obj="NGC 3034", seed=1)
    monkeypatch.setattr(queries, "location_lookup",
                        lambda _con: (lambda _volume, _path: {}["kolizja"]))
    wyjatki = _szpieg_reguly_okna(monkeypatch)
    try:
        i18n.set_lang(lang)
        dlg = _okno(qapp, a.con, target=queries.object_target(a.con, "M 44"), frame_ids=[fa])
        (exc,) = wyjatki
        assert type(exc) is KeyError, exc
        zdanie = i18n.t("objchg.err.plan", msg=i18n.t("objchg.item.prog_error"))
        assert dlg.error.text() == zdanie, dlg.error.text()
        assert dlg.error.szczegol() == i18n.t("objchg.st.detail_tip", detail="KeyError: 'kolizja'")
        if lang == "en":
            assert not set(zdanie) & _POLSKIE_LITERY, zdanie
        dlg.reject()
    finally:
        i18n.set_lang("pl")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_staging_blad_programu_spoza_inwariantu_nie_ucieka_ze_slotu(qapp, con, rdzen, monkeypatch, lang):
    """Staging pada błędem programu, który NIE jest inwariantem planu (`TypeError`): wyjątek nie
    ucieka ze slotu akcji, pole błędu mówi zdaniem błędu programu w języku UI (bez obietnicy
    „plan niespójny z regułami zapisu”), `Typ: opis` w szczególe technicznym, zero zapisu i akcja
    gotowa do ponowienia. Falsyfikator: `except (ValueError, sqlite3.Error)` w `_on_action`."""
    def _zly(_con, *, plan, now):
        raise TypeError("zły argument stagingu")
    monkeypatch.setattr(repo, "stage_object_change", _zly)
    try:
        i18n.set_lang(lang)
        dlg = _okno(qapp, con)
        _klik_akcji(dlg)
        zdanie = dlg.error.text()
        assert zdanie == i18n.t("objchg.err.stage", msg=i18n.t("objchg.item.prog_error")), zdanie
        assert dlg.error.szczegol() == i18n.t("objchg.st.detail_tip",
                                              detail="TypeError: zły argument stagingu")
        if lang == "en":
            assert not set(zdanie) & _POLSKIE_LITERY, zdanie
        assert rdzen.commity == [] and dlg.action_btn.isEnabled()
        dlg.reject()
    finally:
        i18n.set_lang("pl")
