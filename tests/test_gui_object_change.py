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
import time

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
    oznaczone „cały plik przepisany”; XISF dopisuje w miejscu, więc bez oznaczenia."""
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
    karty = [dlg.items_tree.topLevelItem(i).text(2) for i in range(3)]
    assert not karty[0].endswith(i18n.t("objchg.card_rewrite"))
    assert karty[1].endswith(i18n.t("objchg.card_rewrite"))
    assert not karty[2].endswith(i18n.t("objchg.card_rewrite"))
    dlg.reject()


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
    assert i18n.t("wb.inplace_fallback", n=1, reason="operacja add/str na OBJECT") in z
    assert i18n.t("objchg.res.notes", n=1, note="zapis potwierdzony z dysku") in z
    bez_kodu = zdanie_wyniku_zmiany(_Wynik("p", applied=[_fr(2, "applied", f"{prefiks}: x")],
                                           blocked=[], failed=[], skipped=[]))
    assert "drogą atomową" not in bez_kodu and i18n.t("objchg.res.notes", n=1,
                                                      note=f"{prefiks}: x") in bez_kodu
    assert i18n.t("objchg.res.run", run_id="przebieg-7") in z
    cof = zdanie_wyniku_zmiany(_Wynik("przebieg-7", applied=[
        _fr(1, "restored", "baza: nowsza decyzja")], blocked=[], failed=[], skipped=[]),
        cofniecie=True)
    assert i18n.t("objchg.res.notes", n=1, note="baza: nowsza decyzja") in cof
    assert "drogą atomową" not in cof


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


def test_blad_bazy_przy_stagingu_ZOSTAWIA_okno_z_powodem(qapp, con, rdzen, monkeypatch):
    import sqlite3

    def zajeta(con_, *, plan, now):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(repo, "stage_object_change", zajeta)
    dlg = _okno(qapp, con)
    dlg.action_btn.click()
    assert "OperationalError: database is locked" in dlg.error.text()
    assert rdzen.commity == [] and dlg.action_btn.isEnabled()
    dlg.reject()


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

    def fits(self, rel, *, obj=None, date="2022-03-26T21:30:12", seed=0, canon="NGC3034"):
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
    """Bez atrapy rdzenia: FITS z kartą (podmiana w miejscu) i FITS bez karty (dopisanie - FITS
    w miejscu tego nie umie, spadek na drogę atomową). Podgląd mówi o przepisaniu pliku przed
    kliknięciem, wynik liczy spadek, „Cofnij” przywraca pliki pod stare ścieżki co do bajtu."""
    from astropy.io import fits
    a = archiwum
    fa, pa = a.fits(r"LIGHTS\NGC3034\RC6\OSC\NGC3034_a_FLATGRP_NOFLAT_OSC.fits", obj="NGC 3034",
                    seed=1)
    fb, pb = a.fits(r"LIGHTS\NGC3034\RC6\OSC\b.fits", date="2022-03-26T21:31:00", seed=2)
    przed = {pa: _sha1(pa), pb: _sha1(pb)}
    cel = queries.object_target(a.con, "M 44")
    dlg = _okno(qapp, a.con, target=cel, frame_ids=[fa, fb])
    karty = [dlg.items_tree.topLevelItem(i).text(2) for i in range(2)]
    assert karty[0] == "'NGC 3034' → 'NGC 2632'"
    assert karty[1].endswith(i18n.t("objchg.card_rewrite"))
    dlg.action_btn.click()
    nowe = [a.root / r"LIGHTS\NGC2632\RC6\OSC\NGC2632_a_FLATGRP_NOFLAT_OSC.fits",   # człon obiektu
            a.root / r"LIGHTS\NGC2632\RC6\OSC\b.fits"]                       # nazwa bez obiektu
    assert all(p.exists() for p in nowe) and not pa.exists() and not pb.exists()
    assert [fits.getheader(str(p))["OBJECT"] for p in nowe] == ["NGC 2632", "NGC 2632"]
    assert dlg.status.text().startswith(i18n.t("objchg.res.applied", n=2))
    assert i18n.t("wb.inplace_fallback", n=1, reason="x").split(":")[0] in dlg.status.text()
    assert not dlg.undo_btn.isHidden()
    dlg.undo_btn.click()
    assert {p: _sha1(p) for p in (pa, pb)} == przed
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
    assert zdanie_drogi_zapisu(spadek) == i18n.t(
        "wb.inplace_fallback", n=1, reason="karta się nie mieści w nagłówku")
    # zapis potwierdzony z dysku po przerwanym commicie: poza `in_place`, ale niczego nie
    # przepisano - to nie spadek na drogę atomową
    potwierdzony = _fr(3, "applied", "zapis potwierdzony z dysku po przerwanym commicie 4 - nic "
                                     "do zapisania")
    assert zdanie_drogi_zapisu(writeback.CommitResult("r", 3, [a, potwierdzony], [], [], [],
                                                      in_place=[a])) == ""
    # zwykły commit (atomowy z założenia) nie dostaje członu o „spadku”
    assert "karta się nie mieści" not in zdanie_commitu_kart(spadek, "grid.wb.applied")[0]
    assert "karta się nie mieści" in zdanie_commitu_kart(spadek, "grid.wb.applied",
                                                         w_miejscu=True)[0]


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
    assert dlg.head.text() == i18n.t_plural("objchg.head_resume_change", 2, run_id=plan.run_id,
                                            canon="NGC2632", card="NGC 2632")
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
