"""KÓŁKO MYSZY PRZESTAWIA POLE WARTOŚCI WYŁĄCZNIE Z FOKUSEM (AR-349) - jeden właściciel reguły dla pól,
które kółko zmienia (`QComboBox`, `QAbstractSpinBox` i pochodne), w całej warstwie widżetów.

Dawniej kółko nad polem bez kliknięcia przestawiało wartość i od razu ją zapisywało: próg Planera
`planner/min_size` 6 → 8 bez gestu człowieka (przy 8′ Planer chował 147 z 854 celów), a combo okna „Park…”
emitowało `activated` → `repo.set_telescope_park` (zdarzenie `telescope.parked`). Pole zmienia wartość
bez pytania o fokus: `QAbstractSpinBox::wheelEvent` zawsze, `QComboBox::wheelEvent` - gdy styl pozwala
przewijać kółkiem (`SH_ComboBox_AllowWheelScrolling`) i lista jest zamknięta (Qt 6.9.2).

DWIE POŁOWY, OBIE POTRZEBNE (źródło Qt 6.9.2, `QApplication::notify`, gałąź `QEvent::Wheel`):

* `Qt.StrongFocus` zamiast domyślnego `WheelFocus` - zdarzenie spontaniczne nadaje fokus wg polityki
  (`giveFocusAccordingToFocusPolicy`) PRZED doręczeniem do filtrów, więc sam filtr widziałby pole już
  z fokusem. `StrongFocus` to Tab i klik, bez bitu kółka;
* filtr: kółko nad polem bez fokusu `ignore()` + `True` - pętla doręczenia przerywa się dopiero na
  widżecie, który zdarzenie obsłużył I przyjął, więc kółko idzie do rodzica (lista Planera, tabela parku,
  przewijany wzór nazwy). Sam `StrongFocus` nie wystarczy - pole zmienia wartość bez fokusu.

Zmierzone sondą na gołych polach (spinbox, combo, combo edytowalne, data; 2026-10-26): sam filtr i sam
`StrongFocus` przepuszczają zmianę wartości, oba razem trzymają wartość, a pasek przewijania rodzica rusza.

`kolko(pole)` owija KONSTRUKTOR (`self.x = kolko(QComboBox())`): bramka AST `tests/test_gui_kolko_bramka.py`
pilnuje, że każde pole wartości budowane w `horreum/gui` tędy przechodzi. Z fokusem (klik, Tab) pole działa
jak dawniej. `setEditable(True)` po `kolko` jest bezpieczne na Windows - Qt przestawia politykę combo
edytowalnego wyłącznie na macOS.

Filtr jest jeden na proces: rodzic `QApplication` trzyma obiekt Qt, referencja modułu - opakowanie Pythona
(obiekt Qt bez właściciela po stronie Pythona PySide6 zbiera GC i filtr znika po cichu)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication


class _FiltrKolka(QObject):
    """Kółko nad polem bez fokusu nie dochodzi do pola - idzie do rodzica (patrz nagłówek modułu)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()               # nieprzyjęte = pętla doręczenia Qt idzie do rodzica
            return True
        return super().eventFilter(obj, event)


_filtr = None


def kolko(pole):
    """Pole wartości reaguje na kółko wyłącznie z fokusem. Zwraca TO SAMO pole - owija konstruktor."""
    global _filtr
    if _filtr is None:
        _filtr = _FiltrKolka(QApplication.instance())
    pole.setFocusPolicy(Qt.StrongFocus)
    pole.installEventFilter(_filtr)
    return pole
