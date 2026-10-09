"""Okno „Uwagi…” (0032) - prefill, zdanie stanu, stany przycisków i intencje, sterowane realnym
oknem Qt (offscreen). Okno nie dotyka bazy, więc testy nie mają bazy: bieżące uwagi podaje test
tak, jak poda je wołający (`queries.notes_for`).

`importorskip` na poziomie MODUŁU; `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import repo
from horreum.gui import i18n
from horreum.gui.i18n_catalog import CATALOG
from horreum.gui.note_dialog import NoteDialog, NoteIntent

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _okno(current, frame_count):
    return NoteDialog(current=current, frame_count=frame_count)


# ---------------------------------------------------------------- prefill i zdanie stanu

def test_jednolita_uwaga_calego_zaznaczenia_wygasza_zapis_tej_samej_tresci(qapp):
    dlg = _okno({1: "chmury po 2:00", 2: "chmury po 2:00"}, 2)
    assert dlg.edit.text() == "chmury po 2:00"
    assert dlg.state.text() == "Uwagę mają 2 z 2 klatek"
    assert not dlg.save_btn.isEnabled() and dlg.clear_btn.isEnabled()
    dlg.edit.setText("  chmury   po 2:00 ")                     # ta sama treść po normalizacji
    assert not dlg.save_btn.isEnabled()
    dlg.edit.setText("chmury po 3:00")
    assert dlg.save_btn.isEnabled()


def test_ta_sama_uwaga_na_czesci_zaznaczenia_zapis_czynny(qapp):
    """Część klatek bez uwagi: ta sama treść rozszerza uwagę na resztę - prawdziwy zapis."""
    dlg = _okno({1: "flat zmieniony"}, 3)
    assert dlg.edit.text() == "flat zmieniony"
    assert dlg.state.text() == "Uwagę ma 1 z 3 klatek"
    assert dlg.save_btn.isEnabled() and dlg.clear_btn.isEnabled()


def test_rozne_uwagi_pole_puste_i_zdanie_o_zastapieniu(qapp):
    dlg = _okno({1: "a", 2: "b", 3: "b"}, 5)
    assert dlg.edit.text() == ""
    assert dlg.state.text() == "Różne uwagi na 3 z 5 klatkach - zapis zastąpi je jedną"
    assert not dlg.save_btn.isEnabled() and dlg.clear_btn.isEnabled()
    QTest.keyClicks(dlg.edit, "jedna")
    assert dlg.save_btn.isEnabled()


def test_bez_uwag_usun_wygaszone(qapp):
    dlg = _okno({}, 4)
    assert (dlg.edit.text(), dlg.state.text()) == ("", "Żadna z 4 klatek nie ma uwagi")
    assert not dlg.save_btn.isEnabled() and not dlg.clear_btn.isEnabled()
    dlg.edit.setText(" \t ")                                      # same białe znaki = pusto
    assert not dlg.save_btn.isEnabled()


@pytest.mark.parametrize("current, zdanie", [({}, "Klatka nie ma uwagi"),
                                             ({9: "x"}, "Klatka ma uwagę")])
def test_jedna_klatka_mowi_o_klatce(qapp, current, zdanie):
    assert _okno(current, 1).state.text() == zdanie


def test_licznik_liczy_po_normalizacji(qapp):
    """Licznik pokazuje tę samą liczbę, którą sprawdza klinga - znaki PO zwinięciu spacji."""
    dlg = _okno({}, 2)
    assert dlg.counter.text() == f"0 / {repo.NOTE_MAX} znaków"
    dlg.edit.setText("  chmury \n\n  po   2:00  ")
    assert dlg.counter.text() == f"14 / {repo.NOTE_MAX} znaków" and dlg.too_long.text() == ""


def test_wklejka_dluzsza_surowo_a_w_limicie_po_normalizacji_zapisuje_calosc(qapp):
    """Wpis dłuższy od limitu SUROWO, a mieszczący się po zwinięciu białych znaków, nie traci
    końcówki: pole nie przycina, „Zapisz” czynne, intencja niesie całość z ostatnim słowem.
    Falsyfikator: przywróć `setMaxLength(repo.NOTE_MAX)` - końcówka „KONIEC” znika."""
    dlg = _okno({}, 3)
    wklejka = "   ".join(["ab"] * 97) + "   KONIEC"         # 491 znaków, po zwinięciu 297
    tekst = repo.normalize_note(wklejka)
    assert len(wklejka) > repo.NOTE_MAX >= len(tekst) and tekst.endswith("KONIEC")
    dlg.edit.setText(wklejka)
    assert dlg.edit.text() == wklejka                        # pole nie obcięło wpisu
    assert dlg.counter.text() == f"{len(tekst)} / {repo.NOTE_MAX} znaków"
    assert dlg.save_btn.isEnabled() and dlg.too_long.text() == ""
    dlg.save_btn.click()
    assert dlg.intent == NoteIntent("set", tekst)


def test_za_dluga_po_normalizacji_zapis_wygaszony_ze_zdaniem(qapp):
    """Ponad limit PO normalizacji: wpis zostaje w polu w całości (do skrócenia), „Zapisz”
    wygaszone, zdanie mówi, o ile za dużo; strażnik `_on_save` odmawia też drogą mimo przycisku,
    a Enter nic nie zapisuje. Skrócenie do limitu przywraca zapis i gasi zdanie."""
    dlg = _okno({}, 2)
    dlg.edit.setText("x" * (repo.NOTE_MAX + 20))
    assert len(dlg.edit.text()) == repo.NOTE_MAX + 20
    assert not dlg.save_btn.isEnabled()
    assert dlg.too_long.text() == "Uwaga jest za długa o 20 znaków - skróć ją, żeby zapisać"
    assert dlg.counter.text() == f"{repo.NOTE_MAX + 20} / {repo.NOTE_MAX} znaków"
    dlg._on_save()
    assert dlg.intent is None
    _pokaz(dlg)
    QTest.keyClick(dlg.edit, Qt.Key_Return)
    QApplication.processEvents()
    assert dlg.isVisible() and dlg.intent is None
    dlg.edit.setText("x" * (repo.NOTE_MAX + 1))
    assert dlg.too_long.text() == "Uwaga jest za długa o 1 znak - skróć ją, żeby zapisać"
    dlg.edit.setText("x" * repo.NOTE_MAX)
    assert dlg.save_btn.isEnabled() and dlg.too_long.text() == ""
    dlg.close()


@pytest.mark.parametrize("current, frame_count", [({1: "a", 2: "b"}, 1), ({}, 0)])
def test_niespojne_wejscie_to_blad_wolajacego(qapp, current, frame_count):
    with pytest.raises(ValueError):
        _okno(current, frame_count)


# ---------------------------------------------------------------- intencje

def test_zapisz_daje_intencje_ze_znormalizowana_trescia(qapp):
    dlg = _okno({1: "a"}, 2)
    dlg.edit.setText("  księżyc\t 80%  ")
    dlg.save_btn.click()
    assert dlg.result() == QDialog.Accepted
    assert dlg.intent == NoteIntent("set", "księżyc 80%")
    assert (dlg.intent.action, dlg.intent.body) == ("set", "księżyc 80%")


def test_usun_uwagi_daje_intencje_zdjecia(qapp):
    dlg = _okno({1: "a", 2: "b"}, 2)
    dlg.clear_btn.click()
    assert dlg.result() == QDialog.Accepted and dlg.intent == NoteIntent("clear", None)


def test_anuluj_zostawia_brak_intencji(qapp):
    dlg = _okno({1: "a"}, 1)
    dlg.edit.setText("inna")
    dlg.cancel_btn.click()
    assert dlg.result() == QDialog.Rejected and dlg.intent is None


def test_wygaszony_zapis_klikniety_programowo_nic_nie_daje(qapp):
    dlg = _okno({1: "a", 2: "a"}, 2)
    dlg._on_save()
    assert dlg.intent is None and dlg.isVisible() is False and dlg.result() == 0


def _pokaz(dlg):
    dlg.show()
    dlg.activateWindow()
    QTest.qWaitForWindowActive(dlg)
    QApplication.processEvents()
    assert dlg.edit.hasFocus(), "pole uwagi ma mieć fokus od startu"


def test_klawisz_enter_w_polu_zapisuje(qapp):
    """Prawdziwy klawisz przy polu z fokusem (nie wywołanie slotu): wpisanie i Enter = „Zapisz”."""
    dlg = _okno({}, 3)
    _pokaz(dlg)
    QTest.keyClicks(dlg.edit, "zmieniony flat")
    QTest.keyClick(dlg.edit, Qt.Key_Return)
    QApplication.processEvents()
    assert dlg.intent == NoteIntent("set", "zmieniony flat")
    assert dlg.result() == QDialog.Accepted and not dlg.isVisible()


def test_enter_przy_wygaszonym_zapisie_nic_nie_robi_a_escape_anuluje(qapp):
    """Enter przy treści bez skutku nie zamyka okna i nie przeskakuje na „Usuń uwagi”."""
    dlg = _okno({1: "a", 2: "a"}, 2)
    _pokaz(dlg)
    QTest.keyClick(dlg.edit, Qt.Key_Return)
    QApplication.processEvents()
    assert dlg.isVisible() and dlg.intent is None
    QTest.keyClick(dlg.edit, Qt.Key_Escape)
    QApplication.processEvents()
    assert not dlg.isVisible() and dlg.intent is None and dlg.result() == QDialog.Rejected


# ---------------------------------------------------------------- język

def test_okno_po_angielsku(qapp):
    i18n.set_lang("en")
    dlg = _okno({1: "a", 2: "a"}, 5)
    assert dlg.windowTitle() == "Frame notes"
    assert dlg.state.text() == "2 of 5 frames have a note"
    assert [b.text() for b in (dlg.save_btn, dlg.clear_btn, dlg.cancel_btn)] == \
        ["Save", "Remove notes", "Cancel"]
    assert dlg.counter.text() == f"1 / {repo.NOTE_MAX} characters"
    assert _okno({1: "a"}, 5).state.text() == "1 of 5 frames has a note"
    assert _okno({1: "a", 2: "b"}, 2).state.text() == \
        "Different notes on 2 of 2 frames - saving replaces them with one"
    assert _okno({}, 3).state.text() == "None of the 3 frames has a note"
    za_dluga = _okno({}, 1)
    za_dluga.edit.setText("x" * (repo.NOTE_MAX + 2))
    assert za_dluga.too_long.text() == "The note is 2 characters too long - shorten it to save"


@pytest.mark.parametrize("n, forma", [(1, "one"), (2, "few"), (4, "few"), (5, "many"),
                                      (12, "many"), (13, "many"), (14, "many"), (22, "few")])
def test_odmiana_polska_kluczy_uwag(n, forma):
    i18n.set_lang("pl")
    for klucz in ("note.of_frames", "note.state_some", "note.state_none", "note.state_mixed",
                  "note.too_long"):
        oczekiwane = CATALOG[klucz]["pl"][forma].format(n=n, k=3, of="z 30 klatek")
        assert i18n.t_plural(klucz, n, k=3, of="z 30 klatek") == oczekiwane, klucz
    assert i18n.t_plural("note.state_some", n, of="z 30 klatek") == {
        1: "Uwagę ma 1 z 30 klatek", 2: "Uwagę mają 2 z 30 klatek",
        4: "Uwagę mają 4 z 30 klatek", 5: "Uwagę ma 5 z 30 klatek",
        12: "Uwagę ma 12 z 30 klatek", 13: "Uwagę ma 13 z 30 klatek",
        14: "Uwagę ma 14 z 30 klatek", 22: "Uwagę mają 22 z 30 klatek"}[n]
    assert i18n.t_plural("note.of_frames", n) == ("z 1 klatki" if n == 1 else f"z {n} klatek")


def test_zdanie_stanu_w_oknie_odmienia_obie_liczby(qapp):
    """Orzeczenie za klatkami z uwagą, dopełnienie za zaznaczonymi - 22 z 25 i 12 z 21."""
    assert _okno({i: "a" for i in range(22)}, 25).state.text() == "Uwagę mają 22 z 25 klatek"
    assert _okno({i: "a" for i in range(12)}, 21).state.text() == "Uwagę ma 12 z 21 klatek"
    assert _okno({1: "a", 2: "b"}, 22).state.text() == \
        "Różne uwagi na 2 z 22 klatkach - zapis zastąpi je jedną"
