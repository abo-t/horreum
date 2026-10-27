"""AR-359: okna kart („Napraw nagłówek…”, „Zatwierdź ze ścieżki…”) biorą „Cofnij” z FAKTÓW wykonawcy
(`wb_worker.CzescZapisu.zakres` - te same klasy rdzenia co szuflada Zbiorów), nie z samego `CommitResult.commit_id`:
przerwany zapis w miejscu (`unverified`) nie dostaje „Cofnij”, które zawsze odmówi `undo_open_op` (zdanie mówi drogę
odzysku, pasek po zamknięciu nie stawia recepty), a podmiana niepotwierdzona (`replace_unconfirmed`) dostaje „Cofnij”
z członem „do sprawdzenia”, którego dawniej nie było. Fakty nieznane (odczyt wykonawcy padł) - okno bez „Cofnij” i
zdanie, że stanu nie udało się odczytać. Jedna migawka odczytu faktów.

Kliki prawdziwe (`QTest.mouseClick`) na pokazanym oknie; okno zamykane `reject()` w `finally`. Pliki FITS w `tmp_path`."""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, writeback
from horreum.gui import i18n
from horreum.gui.app import RepairHeaderDialog
from horreum.gui.wb_worker import CzescZapisu, WritebackWorker, commit_do_cofniecia, czlony_niepewnych

from test_gui_app_object import _karta_object, _okno_sciezki, qapp, repair, sciezka_karty  # noqa: F401
from test_gui_app_object import _select_review_tag
from test_gui_grid_recepty import _okno_naprawy
from test_writeback_cofniecie_przebiegu import NOW, _BarieraOdczytu, _baza, _makro


def _czekaj(warunek, opis, s=30):
    koniec = time.monotonic() + s
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"bezpiecznik {s} s: {opis}")
        QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.005)


def _rozjazd(monkeypatch):
    """Weryfikacja zapisu w miejscu po podmianie mówi rozjazd - faza `unverified`, lokacja izolowana (wzór
    `test_writeback_cofniecie_przebiegu._jeden_zapis`)."""
    prawdziwa = writeback._verify_inplace

    def _r(plan, size, probka, backup_text):
        prawdziwa(plan, size, probka, backup_text)
        return writeback.WriteResult("failed", writeback.PowodPozycji("rozjazd odczytu", "inplace_verify_mismatch"),
                                     plan.post_hash, backup_text, in_place=True)
    monkeypatch.setattr(writeback, "_verify_inplace", _r)


def _niepotwierdzona(monkeypatch):
    """Spadek na drogę atomową i wyjątek przy samej podmianie - backup niepotwierdzony (`replace_unconfirmed`)."""
    monkeypatch.setattr(writeback, "write_changes_inplace", lambda *a, **k: writeback.Fallback("test: atomowo"))
    monkeypatch.setattr(writeback, "_replace_file_w",
                        lambda path, tmp, kopia: (_ for _ in ()).throw(OSError(None, "awaria podmiany", None, 87)))


def _okno(ktore, request):
    """`(okno, przycisk zapisu, etykieta „Cofnij”, pliki pisane, liczba plików karty)` - okno pokazane, tryb inline."""
    if ktore == "sciezka":
        v, con, pliki, _fid = request.getfixturevalue("sciezka_karty")
        dlg = _okno_sciezki(v, con)
        dlg.show()
        return dlg, dlg.confirm_btn, i18n.t("path.undo_cards_btn"), [pliki["zapis"]]
    v, con, files, _open = request.getfixturevalue("repair")
    dlg = _open()
    dlg.show()
    return dlg, dlg.save_btn, i18n.t("grid.action.undo"), list(files)


OKNA = pytest.mark.parametrize("ktore", ["sciezka", "naprawa"])


@OKNA
def test_zapis_nieweryfikowany_okno_bez_Cofnij_z_droga_odzysku(ktore, request, monkeypatch):
    """Zapis w miejscu z rozjazdem weryfikacji (`unverified`): „Cofnij” ukryte, `commit_po_zamknieciu` None (bez
    recepty paska), zdanie z członem przerwanego zapisu w miejscu i drogą „Przywróć nagłówek…”, bez kotwicy commitu
    (cofnięcie i tak odmówi), przycisk zapisu milczy (lokacja izolowana). Dawniej: „Cofnij” i recepta w pętli
    `undo_open_op` bez wyjścia. Falsyfikatory: „Cofnij” z `CommitResult.commit_id`; okno bez faktów (`on_partial`)."""
    dlg, zapis, _etykieta, pliki = _okno(ktore, request)
    try:
        with monkeypatch.context() as m:
            _rozjazd(m)
            QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        assert dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu is None, tekst
        assert czlony_niepewnych(0, len(pliki), przycisk="-") in tekst, tekst
        assert i18n.t("grid.wb.commit_id", id=1) not in tekst, tekst
        assert not zapis.isEnabled()
        assert dlg.po_zamknieciu is None
    finally:
        dlg.reject()


@OKNA
def test_podmiana_niepotwierdzona_okno_daje_Cofnij_do_sprawdzenia(ktore, request, monkeypatch):
    """Wyjątek przy samej podmianie drogi atomowej: backup niepotwierdzony, `CommitResult.commit_id` None - okno
    i tak daje „Cofnij” (commit z faktów) z członem „do sprawdzenia - „Cofnij” je sprawdzi” i kotwicą; klik „Cofnij”
    rozstrzyga backup z dyskiem (plik nietknięty - „nie ma czego cofać”), przycisk znika, bajty bez zmian. Dawniej
    okno milczało o „Cofnij”, a szuflada w tym stanie je dawała. Falsyfikator: „Cofnij” z `commit_id` wyniku."""
    dlg, zapis, etykieta, pliki = _okno(ktore, request)
    przed = [p.read_bytes() for p in pliki]
    try:
        with monkeypatch.context() as m:
            _niepotwierdzona(m)
            QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        assert not dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu == 1, tekst
        assert czlony_niepewnych(len(pliki), 0, przycisk=etykieta) in tekst, tekst
        assert tekst.endswith(i18n.t("grid.wb.commit_id", id=1)), tekst
        assert [p.read_bytes() for p in pliki] == przed
        QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        assert dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu is None, dlg.status.text()
        assert [p.read_bytes() for p in pliki] == przed
    finally:
        dlg.reject()


@OKNA
def test_fakty_nieznane_okno_bez_Cofnij_ze_zdaniem(ktore, request, monkeypatch):
    """Odczyt faktów wykonawcy padł (klasy przebiegu rzucają) przy zapisie, który plik podmienił: okno nie obiecuje
    „Cofnij”, którego stanu nie zna - zdanie mówi, że stanu nie udało się odczytać, kotwica commitu rdzenia zostaje
    (droga CLI), zapis milczy. Falsyfikator: zastępstwo `CommitResult.commit_id` przy faktach jawnie nieznanych."""
    dlg, zapis, _etykieta, pliki = _okno(ktore, request)
    try:
        with monkeypatch.context() as m:
            m.setattr(writeback, "zakresy_cofniecia",
                      lambda *a, **k: (_ for _ in ()).throw(RuntimeError("odczyt klas padł")))
            QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        assert all(_karta_object(p) is not None for p in pliki)
        assert dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu is None, tekst
        assert (i18n.t("wb.write_facts_unknown") + i18n.t("grid.wb.commit_id", id=1)) in tekst, tekst
        assert not zapis.isEnabled()
    finally:
        dlg.reject()


@OKNA
def test_zapis_udany_z_faktow_jak_dotad(ktore, request):
    """Zapis udany: z faktów ta sama decyzja co dawniej - „Cofnij”, kotwica, zdanie bez członów niepewnych, a wariant
    paska po zamknięciu z poleceniem CLI. Falsyfikator: człony niepewnych przy samych zatwierdzonych."""
    dlg, zapis, etykieta, pliki = _okno(ktore, request)
    try:
        QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        assert not dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu == 1, tekst
        assert czlony_niepewnych(len(pliki), 0, przycisk=etykieta) not in tekst, tekst
        assert czlony_niepewnych(0, len(pliki), przycisk=etykieta) not in tekst, tekst
        assert tekst.endswith(i18n.t("grid.wb.commit_id", id=1)), tekst
        assert dlg.po_zamknieciu is not None and dlg.po_zamknieciu[1].endswith(
            i18n.t("wb.undo_short", cmd=i18n.t("wb.undo_cli_short", id=1))), dlg.po_zamknieciu
        QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
    finally:
        dlg.reject()


def test_pasek_po_zamknieciu_czlon_nazywa_polecenie_CLI(repair, monkeypatch):
    """Podmiana niepotwierdzona: zdanie okna nazywa przycisk „Cofnij”, a wariant paska po zamknięciu - polecenie CLI
    (przycisku po zamknięciu nie ma). Falsyfikator: pasek z członem „„Cofnij” je sprawdzi”."""
    _v, _con, files, _open = repair
    dlg = _open()
    dlg.show()
    try:
        with monkeypatch.context() as m:
            _niepotwierdzona(m)
            QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        cli = i18n.t("wb.undo_cli_short", id=1)
        okno, pasek, _szczegol, _polecenie = dlg.po_zamknieciu
        assert okno == dlg.status.text()
        assert czlony_niepewnych(len(files), 0, przycisk=cli) in pasek, pasek
        assert czlony_niepewnych(len(files), 0, przycisk=i18n.t("grid.action.undo")) not in pasek, pasek
    finally:
        dlg.reject()


def test_fakty_w_watku_tla_przychodza_przed_zdaniem(repair, monkeypatch):
    """Prawdziwy `QThread` wykonawcy (`async_ok`): fakty zapisu przychodzą kolejką do METODY okna przed `done` - ta
    sama decyzja co inline (zapis nieweryfikowany: bez „Cofnij”, człon otwartego zapisu). Falsyfikator: odbiorca faktów
    jako goły obiekt wywoływalny (Qt woła go w wątku workera) albo fakty po zdaniu."""
    _v, _con, files, _open = repair
    dlg = _open()
    dlg._runner.async_ok = True
    dlg.show()
    try:
        _rozjazd(monkeypatch)
        QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        _czekaj(lambda: not dlg._runner.is_busy and not dlg.bar.isVisible(), "koniec zapisu w wątku tła")
        tekst = dlg.status.text()
        assert dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu is None, tekst
        assert czlony_niepewnych(0, len(files), przycisk="-") in tekst, tekst
    finally:
        dlg.reject()


def test_po_zamknieciu_okna_bez_recepty_gdy_nic_do_cofniecia(qapp, tmp_path, monkeypatch):
    """Gospodarz (`MainWindow`, prawdziwe `exec()` okna „Napraw nagłówek…”): zapis nieweryfikowany, zamknięcie okna -
    oś nie stawia recepty „Cofnij zapis (commit N)” (zero emisji `status_recipe`), pasek mówi zdanie okna z drogą
    odzysku. Dawniej recepta stała i każdy klik odmawiał `undo_open_op`. Falsyfikator: recepta z `commit_id` wyniku."""
    win, _path, pliki = _okno_naprawy(tmp_path, n=1)
    ov = win.object_view
    recepty, zdania = [], []
    ov.status_recipe.connect(recepty.append)
    ov.status_message.connect(zdania.append)
    _rozjazd(monkeypatch)
    _select_review_tag(ov, "nameless")
    stan = {"krok": 0}

    def _krok():
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, RepairHeaderDialog):
            return
        if stan["krok"] == 0:
            stan["krok"] = 1
            QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        elif stan["krok"] == 1 and not dlg._runner.is_busy and not dlg.bar.isVisible():
            stan["krok"] = 2
            QTest.mouseClick(dlg._close_btn, Qt.LeftButton)

    def _bezpiecznik():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            dlg.reject()
    zegar, bezpiecznik = QTimer(), QTimer()
    zegar.timeout.connect(_krok)
    bezpiecznik.setSingleShot(True)
    bezpiecznik.timeout.connect(_bezpiecznik)
    zegar.start(20)
    bezpiecznik.start(60000)
    try:
        QTest.mouseClick(ov.repair_btn, Qt.LeftButton)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert stan["krok"] == 2, stan
        assert recepty == [], recepty
        assert zdania and czlony_niepewnych(0, 1, przycisk="-") in zdania[-1], zdania
    finally:
        zegar.stop()
        bezpiecznik.stop()
        win.close()


@OKNA
def test_fakty_porazki_nie_wisza_do_nastepnego_zapisu(ktore, request, monkeypatch):
    """Wyjątek wykonawcy w operacji zapisu (klik zapisu): fakty tej operacji przychodzą przed porażką (`_na_czesc`),
    a obsługa porażki je zdejmuje - nie czekają na następne `_after_commit`, które wzięłoby z nich „Cofnij”.
    Falsyfikator: `_on_failed` bez zdjęcia faktów (`_czesc` z poprzedniej operacji w oknie)."""
    przyszly = []

    def _pada(con, t, now, pr, sc):
        raise RuntimeError("zapis padł")
    dlg, zapis, _etykieta, _pliki = _okno(ktore, request)
    prawdziwe = dlg._na_czesc
    monkeypatch.setattr(dlg, "_na_czesc", lambda op, czesc: (przyszly.append(czesc), prawdziwe(op, czesc)))
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "commit", _pada)
            QTest.mouseClick(zapis, Qt.LeftButton)
        assert przyszly and isinstance(przyszly[0], CzescZapisu), przyszly
        assert dlg._czesc is None and dlg.error.text(), dlg.error.text()
    finally:
        dlg.reject()


# ============================================================ reguła i migawka faktów


def test_regula_commit_do_cofniecia_z_faktow_i_bez():
    """Bez faktów (szuflada Zbiorów - trzy wołania bez `czesc`) - dokładnie dzisiejsza reguła `CommitResult.commit_id`;
    z faktami: zakres z „Cofnij” → jego commit, zakres bez „Cofnij” (sam otwarty zapis) i brak zakresu → None, fakty
    jawnie nieznane → None. Falsyfikator: zastępstwo `commit_id` przy faktach nieznanych."""
    res7 = writeback.CommitResult("r", 7, [], [], [], [])
    res_bez = writeback.CommitResult("r", None, [], [], [], [])
    assert commit_do_cofniecia(res7) == 7 and commit_do_cofniecia(res_bez) is None
    otwarty = writeback.ZakresCofniecia((7,), 0, 0, 1)
    niepewny = writeback.ZakresCofniecia((7,), 0, 1, 0)
    assert commit_do_cofniecia(res7, CzescZapisu((), zakres=otwarty, zakres_znany=True)) is None
    assert commit_do_cofniecia(res_bez, CzescZapisu((), zakres=niepewny, zakres_znany=True)) == 7
    assert commit_do_cofniecia(res7, CzescZapisu((), zakres=None, zakres_znany=True)) is None
    assert commit_do_cofniecia(res7, CzescZapisu((), zakres_znany=False)) is None


def test_czesc_zapisu_czyta_jedna_migawke(qapp, tmp_path):
    """Drugie połączenie cofa przebieg MIĘDZY odczytem commitów a klasami (bariera przed drugim SELECT-em): fakty
    z migawki sprzed - zakres z oboma plikami zatwierdzonymi - nie para „commit nowy, zakres pusty”, która nigdy nie
    istniała; połączenie po wyjściu bez transakcji. Falsyfikator: trzy odczyty bez `BEGIN`."""
    con, _pliki = _baza(tmp_path, 2)
    _makro(con, "R", "EQ6")
    worker = WritebackWorker(str(tmp_path / "p.db"), "commit", "R", now_fn=lambda: NOW)
    przed = worker._przed_operacja(con)
    assert writeback.commit(con, "R", now=NOW, inplace=True).commit_id == 1
    con2 = db.connect(str(tmp_path / "p.db"))
    try:
        bariera = _BarieraOdczytu(con, 2, lambda: writeback.undo_run(con2, (1,), now=NOW))
        czesc = worker._czesc_zapisu(bariera, przed)
        assert czesc.zakres_znany and czesc.zakres == writeback.ZakresCofniecia((1,), 2, 0, 0), czesc
        assert czesc.zapisane == 2 and not con.in_transaction, czesc
        assert writeback.przebieg_do_cofniecia(con, "R") is None
    finally:
        con2.close()
        con.close()


# ============================================================ AR-388, AR-384 - okna kart po przerwanym zapisie

from astropy.io import fits  # noqa: E402

from horreum.gui.wb_worker import _zapis_kart, tekst_powodu  # noqa: E402
from horreum.item_reasons import powod_okna  # noqa: E402

_BLAD_PO_PODMIANIE = RuntimeError("wyjątek po podmianie")


def _zapisz_i_pada(con, t, now, pr, sc):
    """Prawdziwy zapis kart (pliki podmienione), potem wyjątek wykonawcy - fakty przychodzą przed porażką."""
    _zapis_kart(con, t, now, pr, sc)
    raise _BLAD_PO_PODMIANIE


def _msg(exc):
    """Zdanie wykonawcy po wyjątku - to, które dostaje odbiorca porażki (`WritebackWorker.run`)."""
    return tekst_powodu(powod_okna(exc))


@OKNA
def test_cofniecie_podmiany_niepotwierdzonej_mowi_bez_wersji_zapisu(ktore, request, monkeypatch):
    """AR-388: „Cofnij” po podmianie niepotwierdzonej (plik nietknięty) - zdanie mówi stan teraz („N nie niesie
    wersji z tego zapisu - nie ma czego cofać”), nie „N już cofnięte”; „Cofnij” znika, bajty sprzed zapisu.
    Falsyfikator: `zdanie_undo_kart` liczy całe `already` członem „już cofnięte”."""
    dlg, zapis, _etykieta, pliki = _okno(ktore, request)
    przed = [p.read_bytes() for p in pliki]
    try:
        with monkeypatch.context() as m:
            _niepotwierdzona(m)
            QTest.mouseClick(zapis, Qt.LeftButton)
        QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        tekst = dlg.status.text()
        assert i18n.t_plural("wb.undo_not_replaced", len(pliki)) in tekst, tekst
        assert i18n.t_plural("wb.undo_already", len(pliki)) not in tekst, tekst
        assert dlg.undo_btn.isHidden() and [p.read_bytes() for p in pliki] == przed
    finally:
        dlg.reject()


@OKNA
def test_trzecia_wersja_przed_cofnieciem_mowi_bez_wersji_zapisu(ktore, request, monkeypatch):
    """AR-388: po podmianie niepotwierdzonej plik zmieniony poza programem (trzecia wersja nagłówka), potem „Cofnij”:
    rekoncyliacja daje zamiar `kept` - zdanie mówi ten sam stan teraz (prawdziwy także tu, „bez zmian” i „commit nie
    podmienił - na dysku nagłówek sprzed commitu” byłyby fałszem), plik trzeciej wersji nietknięty."""
    dlg, zapis, _etykieta, pliki = _okno(ktore, request)
    try:
        with monkeypatch.context() as m:
            _niepotwierdzona(m)
            QTest.mouseClick(zapis, Qt.LeftButton)
        for p in pliki:
            fits.setval(str(p), "TELESCOP", value="Inny")
        trzecia = [p.read_bytes() for p in pliki]
        QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        tekst = dlg.status.text()
        assert i18n.t_plural("wb.undo_not_replaced", len(pliki)) in tekst, tekst
        assert i18n.t_plural("wb.undo_already", len(pliki)) not in tekst, tekst
        assert [p.read_bytes() for p in pliki] == trzecia
        assert {r[0] for r in dlg.con.execute("SELECT outcome FROM replace_intent")} == {"kept"}
    finally:
        dlg.reject()


@OKNA
def test_zdanie_zapisu_okna_bez_nazwy_klasy_a_szczegol_z_klasa(ktore, request, monkeypatch):
    """AR-388: błąd systemu spoza klas rdzenia (WinError 87) w zdaniu ZAPISU okna - numer i komunikat systemu bez
    nazwy klasy Pythona, surowy tekst z klasą pod kursorem zdania. Falsyfikatory: `czytelny_powod` bez zdjęcia klasy;
    `_surowy_systemu` bez węzła tekstowego (szczegół pusty)."""
    dlg, zapis, _etykieta, _pliki = _okno(ktore, request)
    try:
        with monkeypatch.context() as m:
            _niepotwierdzona(m)
            QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        assert "OSError" not in tekst and "[WinError 87] awaria podmiany" in tekst, tekst
        assert i18n.t("wb.os_detail_tip", detail="OSError: [WinError 87] awaria podmiany") in dlg.status.szczegol()
    finally:
        dlg.reject()


@OKNA
def test_porazka_operacji_okna_bez_nazwy_klasy(ktore, request, monkeypatch):
    """AR-388: wyjątek całej operacji (WinError 87, przed pierwszym plikiem) - zdanie błędu okna bez nazwy klasy,
    szczegół z klasą (wykonawca: `wiersz_systemu` surowego wyjątku)."""
    def _pada(con, t, now, pr, sc):
        raise OSError(None, "awaria operacji", None, 87)
    dlg, zapis, _etykieta, _pliki = _okno(ktore, request)
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "commit", _pada)
            QTest.mouseClick(zapis, Qt.LeftButton)
        assert dlg.error.text() == i18n.t("grid.wb.error", msg="[WinError 87] awaria operacji"), dlg.error.text()
        assert dlg.error.szczegol() == i18n.t("wb.os_detail_tip", detail="OSError: [WinError 87] awaria operacji")
    finally:
        dlg.reject()


@OKNA
def test_wyjatek_po_podmianie_okno_daje_Cofnij_i_milczy_zapis(ktore, request, monkeypatch):
    """AR-384: wyjątek wykonawcy PO podmianie plików - okno mówi jak szuflada („N z M zapisane, potem błąd: … -
    „Cofnij” cofa zapisane (commit 1)”), stawia „Cofnij” z faktów, przycisk zapisu milczy (karty stoją w plikach),
    wariant paska po zamknięciu nazywa polecenie CLI; klik „Cofnij” przywraca bajty i oddaje zapis. Dawniej: samo
    „BŁĄD: …”, bez „Cofnij”, zapis czynny przy plikach już z kartą. Falsyfikatory: `_on_failed` bez ogona;
    bez milczenia zapisu; bez kotwicy; bez wariantu paska."""
    dlg, zapis, etykieta, pliki = _okno(ktore, request)
    przed = [p.read_bytes() for p in pliki]
    n = len(pliki)
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
            QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        glowa = i18n.t_plural("grid.wb.partial_commit", n, m=n, msg=_msg(_BLAD_PO_PODMIANIE))
        assert tekst.endswith(glowa + i18n.t("grid.wb.partial_undo", undo=etykieta)
                              + i18n.t("grid.wb.commit_id", id=1)), tekst
        assert not dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu == 1, tekst
        assert not zapis.isEnabled() and dlg._czesc is None and dlg.error.text() == "", dlg.error.text()
        assert [p.read_bytes() for p in pliki] != przed
        cli = i18n.t("wb.undo_cli_short", id=1)
        okno, pasek, _szczegol, polecenie = dlg.po_zamknieciu
        # pasek kończy się tym samym członem polecenia co po udanym zapisie (`_after_commit`)
        assert okno == tekst and pasek.endswith(
            glowa + i18n.t("grid.wb.partial_undo", undo=cli) + i18n.t("grid.wb.commit_id", id=1)
            + i18n.t("wb.undo_short", cmd=cli)), pasek
        assert polecenie.endswith("--undo 1"), polecenie
        QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        assert [p.read_bytes() for p in pliki] == przed, dlg.status.text()
        assert dlg.undo_btn.isHidden() and zapis.isEnabled(), dlg.status.text()
    finally:
        dlg.reject()


def test_wyjatek_po_pierwszym_pliku_okno_nie_mowi_do_dokonczenia(repair, monkeypatch):
    """AR-384: wyjątek po PIERWSZYM z dwóch plików (z postępu - `writeback.commit` go nie łapie) - okno zdejmuje
    staging, więc reguła ignoruje czekające wpisy: „1 z 2 zapisany, potem błąd: … - „Cofnij” cofa zapisane”, bez
    „do dokończenia”, „Cofnij” stoi, czekający wpis zdjęty. Falsyfikator: reguła szuflady (`czesc.czeka`)."""
    _v, con, _files, _open = repair
    dlg = _open()
    dlg.show()
    blad = RuntimeError("po pierwszym pliku")

    def _pada_po_pierwszym(c, t, now, pr, sc):
        def _postep(*a):
            pr(*a)
            raise blad
        return _zapis_kart(c, t, now, _postep, sc)
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "commit", _pada_po_pierwszym)
            QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        tekst = dlg.status.text()
        assert tekst == (i18n.t_plural("grid.wb.partial_commit", 1, m=2, msg=_msg(blad))
                         + i18n.t("grid.wb.partial_undo", undo=i18n.t("grid.action.undo"))
                         + i18n.t("grid.wb.commit_id", id=1)), tekst
        assert not dlg.undo_btn.isHidden() and not dlg.save_btn.isEnabled(), tekst
        assert con.execute("SELECT count(*) FROM pending_changes WHERE status = 'pending'").fetchone()[0] == 0
    finally:
        dlg.reject()


@OKNA
def test_wyjatek_po_podmianie_fakty_nieznane_bez_Cofnij_zapis_milczy(ktore, request, monkeypatch):
    """AR-384: odczyt klas rdzenia padł po wyjątku po podmianie - zdanie „co najmniej N z M zapisane …” z członem
    faktów nieznanych, bez „Cofnij” i bez recepty, zapis milczy (postęp zna podmienione pliki - analog `commit_id`
    sukcesu). Falsyfikator: zapis czynny przy faktach nieznanych."""
    dlg, zapis, _etykieta, pliki = _okno(ktore, request)
    n = len(pliki)
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
            m.setattr(writeback, "zakresy_cofniecia",
                      lambda *a, **k: (_ for _ in ()).throw(RuntimeError("odczyt klas padł")))
            QTest.mouseClick(zapis, Qt.LeftButton)
        tekst = dlg.status.text()
        assert tekst.endswith(i18n.t_plural("grid.wb.partial_commit_min", n, m=n, msg=_msg(_BLAD_PO_PODMIANIE))
                              + i18n.t("wb.write_facts_unknown")), tekst
        assert dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu is None and dlg.po_zamknieciu is None
        assert not zapis.isEnabled()
    finally:
        dlg.reject()


@OKNA
def test_porazka_cofniecia_po_wyjatku_zapisu_mowi_blad(ktore, request, monkeypatch):
    """AR-384: ten sam odbiorca łapie porażkę COFNIĘCIA - wyjątek „Cofnij” po scenie wyjątku po podmianie mówi
    „BŁĄD: …” w polu błędu, „Cofnij” zostaje przy tym samym commicie, zdanie zapisu w `status` bez zmian."""
    dlg, zapis, _etykieta, _pliki = _okno(ktore, request)
    blad = RuntimeError("cofnięcie padło")
    try:
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
            QTest.mouseClick(zapis, Qt.LeftButton)
        status = dlg.status.text()

        def _undo_pada(*a):
            raise blad
        with monkeypatch.context() as m:
            m.setitem(WritebackWorker._OPS, "undo", _undo_pada)
            QTest.mouseClick(dlg.undo_btn, Qt.LeftButton)
        assert dlg.error.text() == i18n.t("grid.wb.error", msg=_msg(blad)), dlg.error.text()
        assert not dlg.undo_btn.isHidden() and dlg.commit_po_zamknieciu == 1 and dlg.status.text() == status
        assert not zapis.isEnabled()
    finally:
        dlg.reject()


def test_po_zamknieciu_okna_po_wyjatku_recepta_paska(qapp, tmp_path, monkeypatch):
    """AR-384, gospodarz (`MainWindow`, prawdziwe `exec()` „Napraw nagłówek…”): wyjątek po podmianie, zamknięcie
    okna - recepta „Cofnij zapis (commit 1)” raz, zdanie paska z poleceniem CLI zamiast przycisku okna. Dawniej:
    zero recept, zdanie „BŁĄD: …”. Falsyfikator: `commit_po_zamknieciu` None po porażce."""
    win, _path, _pliki = _okno_naprawy(tmp_path, n=1)
    ov = win.object_view
    recepty, zdania = [], []
    ov.status_recipe.connect(recepty.append)
    ov.status_message.connect(zdania.append)
    monkeypatch.setitem(WritebackWorker._OPS, "commit", _zapisz_i_pada)
    _select_review_tag(ov, "nameless")
    stan = {"krok": 0}

    def _krok():
        dlg = QApplication.activeModalWidget()
        if not isinstance(dlg, RepairHeaderDialog):
            return
        if stan["krok"] == 0:
            stan["krok"] = 1
            QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
        elif stan["krok"] == 1 and not dlg._runner.is_busy and not dlg.bar.isVisible():
            stan["krok"] = 2
            QTest.mouseClick(dlg._close_btn, Qt.LeftButton)

    def _bezpiecznik():
        dlg = QApplication.activeModalWidget()
        if dlg is not None:
            dlg.reject()
    zegar, bezpiecznik = QTimer(), QTimer()
    zegar.timeout.connect(_krok)
    bezpiecznik.setSingleShot(True)
    bezpiecznik.timeout.connect(_bezpiecznik)
    zegar.start(20)
    bezpiecznik.start(60000)
    try:
        QTest.mouseClick(ov.repair_btn, Qt.LeftButton)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert stan["krok"] == 2, stan
        assert len(recepty) == 1 and i18n.t("wb.undo_recipe", id=1) in str(recepty[0]), recepty
        cli = i18n.t("wb.undo_cli_short", id=1)
        assert zdania and i18n.t("grid.wb.partial_undo", undo=cli) in str(zdania[-1]), zdania
    finally:
        zegar.stop()
        bezpiecznik.stop()
        win.close()
