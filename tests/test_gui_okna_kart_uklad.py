"""Okna kart (`ConfirmPathObjectsDialog` „Zatwierdź ze ścieżki…”, `RepairHeaderDialog` „Napraw nagłówek…”) -
UKŁAD i POLE STATUSU (AR-175): zdanie odmowy zamknięcia w biegu schodzi z pola po końcu biegu, lista pominiętych
mieści się przy rozmiarze startowym, a zdanie wyniku z długą ścieżką w powodzie nie poszerza okna.

Ogony „Cofnij” tych okien mają własne testy (`test_gui_object_change.py`, `test_gui_app_object.py`); tu wyłącznie
układ i pole. Relacje zamiast pikseli - offscreen nie ma bazy fontów (`QT_QPA_PLATFORM` przed importem Qt)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtWidgets import QApplication

from horreum import db, writeback
from horreum.gui import i18n

from test_gui_object_change import _lighty, _okno_naprawy

NOW = "2026-10-22T10:00:00+00:00"


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _pompuj(n=10):
    for _ in range(n):
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)


class _WorkerWBiegu:
    """Atrapa workera uchwytu zapisu w biegu (wzór `test_gui_object_change.py`): `refuse_close` widzi bieg
    i woła anulowanie po bieżącym pliku."""

    def request_cancel(self):
        pass


@pytest.mark.parametrize("koniec", ["undo", "commit"])
def test_sciezka_odmowa_zamkniecia_schodzi_po_koncu_biegu(qapp, tmp_path, koniec):
    """AR-175 (wizytacja natywna): zamknięcie „Zatwierdź ze ścieżki…” w biegu zapisu stawia w polu błędu „Zapis do plików
    trwa…”, a koniec biegu (cofnięcie albo zapis) zostawiał je obok wyniku. Teraz schodzi; zdanie spoza
    odmowy zamknięcia (odmowa klingi z tego samego pola) koniec biegu zostawia.
    Mutanty: `_end_progress` bez zdjęcia (odmowa wisi); zdjęcie bezwarunkowe (odmowa klingi znika)."""
    from horreum.gui.app import ConfirmPathObjectsDialog
    con = db.open_db(str(tmp_path / "w7.db"))
    dlg = ConfirmPathObjectsDialog(con, proposals=[], now_fn=lambda: NOW)
    try:
        dlg.show()
        _pompuj()
        dlg._runner._worker, dlg._runner._thread = _WorkerWBiegu(), object()
        dlg.reject()                                   # zamknięcie w biegu - okno zostaje
        assert dlg.error.text() == i18n.t("wb.close_refused")
        dlg._runner._worker, dlg._runner._thread = None, None
        if koniec == "undo":
            dlg._commit_id = 7
            dlg._after_undo("undo", writeback.UndoResult(
                7, [writeback.FileResult(1, "X:\\L\\a.fits", "restored")], [], []))
        else:
            dlg._after_commit("commit", writeback.CommitResult(
                "run-w7", 8, [writeback.FileResult(1, "X:\\L\\a.fits", "applied")], [], [], []))
        assert dlg.error.text() == ""
        dlg.error.setText("odmowa klingi tego kliku")
        dlg._end_progress()
        assert dlg.error.text() == "odmowa klingi tego kliku"
    finally:
        dlg._runner._worker = dlg._runner._thread = None
        dlg.reject()
        _pompuj()
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_lista_pominietych_miesci_sie_przy_starcie(qapp, tmp_path, monkeypatch, lang):
    """AR-175 (wizytacja natywna): rozmiar startowy „Napraw nagłówek…” liczył grupy i przyciski, a lista pominiętych
    (sumy kontrolne w folderach o długich nazwach) była szersza - poziomy suwak przy starcie (zmierzone
    natywnie: wpis 673 px w widoku 541 px). Relacja, nie piksele: przy starcie suwak listy bez zakresu.
    Ekran offscreen ma 800 px, a metryki offscreen są zawyżone - sufit `_SCREEN_FRAC` podniesiony, żeby
    relacja nie stała na suficie ekranu (sufit ma własne bramki okien gestu).
    Mutant: `_rozmiar_startowy` bez listy pominiętych."""
    from horreum.gui import config_dialog
    monkeypatch.setattr(config_dialog, "_SCREEN_FRAC", 20.0)
    i18n.set_lang(lang)
    con = db.open_db(str(tmp_path / "w14.db"))
    try:
        korzen = tmp_path / "ASTRO_"
        _lighty(korzen, con, "NGC7635", 2, baza=2)
        _lighty(korzen, con, "C2023A3_Tsuchinshan-ATLAS_Comet_Great_Pass", 2, baza=4, suma=True)
        _lighty(korzen, con, "Sh2-229_Flaming_Star_Nebula_Mosaic_Panel_Seven", 2, baza=5, suma=True)
        dlg = _okno_naprawy(con)
        try:
            dlg.show()
            _pompuj()
            lst = dlg.skipped_list
            szerszy = max(lst.fontMetrics().horizontalAdvance(lst.item(i).text())
                          for i in range(lst.count()))
            assert szerszy > dlg._area.widget().sizeHint().width(), "fixture: lista nie szersza od grup"
            assert lst.horizontalScrollBar().maximum() == 0, (lst.horizontalScrollBar().maximum(), dlg.width())
        finally:
            dlg.reject()
            _pompuj()
    finally:
        i18n.set_lang("pl")
        con.close()


def test_pole_statusu_okna_kart_ze_sciezka_nie_poszerza_okna(qapp, tmp_path):
    """AR-175 (pomiar wcześniejszy: okno 593 → 643 px po zdaniu ze ścieżką): pole STATUSU okna kart po ogonie
    cofnięcia z długą ścieżką w powodzie systemu nie podnosi minimum szerokości okna - pole łamie ścieżkę
    po `\\` (AR-221), a jego minimum szerokości to 0. Bramka bliźniacza pola błędu
    (`test_gui_protokol_zdania.py`). Mutant: pole statusu bez minimum szerokości 0."""
    con = db.open_db(str(tmp_path / "q7.db"))
    try:
        pliki = _lighty(tmp_path / "ASTRO_", con, "NGC7635", 2, baza=1)
        dlg = _okno_naprawy(con)
        try:
            dlg.show()
            _pompuj()
            dlg.layout().activate()
            przed = dlg.minimumSizeHint().width()
            szer = dlg.width()
            dluga = "X:\\" + "\\".join(["ASTRO_", "LIGHTS", "C2023A3_Tsuchinshan_ATLAS", "76EDPH_2600MC", "OSC",
                                        "C2023A3_Tsuchinshan_ATLAS_20241012_190512_LIGHT_OSC_120s_FLATGRP_.fits"])
            powod = f"[WinError 32] Proces nie może uzyskać dostępu do pliku: '{dluga}'"
            res = writeback.UndoResult(4711, [writeback.FileResult(1, str(pliki[0]), "restored")], [],
                                       [writeback.FileResult(2, dluga, "failed", powod)])
            dlg._commit_id = res.commit_id
            dlg._after_undo("undo", res)
            _pompuj()
            dlg.layout().activate()
            assert dlg.status.text(), "ogon cofnięcia bez zdania - test bez sensu"
            assert dlg.minimumSizeHint().width() == przed
            assert dlg.width() == szer
            assert dlg.status.minimumSizeHint().width() == 0
        finally:
            dlg.reject()
            _pompuj()
    finally:
        con.close()
