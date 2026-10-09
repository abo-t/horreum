"""Okno „Uwagi…” - jedna krótka uwaga człowieka na zaznaczonych klatkach (0032).

Okno NIE DOTYKA BAZY, nawet do odczytu: bieżące uwagi zaznaczenia podaje wołający
(`queries.notes_for`), a wynikiem jest INTENCJA (`self.intent`), którą wołający wykonuje klingą
(`repo.set_frame_note` / `repo.clear_frame_note`) i ubiera w receptę cofnięcia. Zaznaczenie bywa
mieszane, a „co dziś stoi” ma policzyć ten sam odczyt, z którego potem wołający składa gest - drugi
odczyt tutaj mógłby zobaczyć inny stan niż ten, który gest zastąpi.

Treść oceniana tą samą normalizacją co w klindze (`repo.normalize_note`): pole z samymi spacjami
albo dłuższe niż `repo.NOTE_MAX` PO zwinięciu białych znaków wygasza „Zapisz” dokładnie wtedy, gdy
klinga by je odrzuciła. Pole NIE MA `maxLength`: limit klingi dotyczy tekstu po normalizacji, więc
przycięcie surowego tekstu odcinałoby po cichu końcówkę wklejonego wpisu, który po zwinięciu spacji
mieścił się w limicie. Za długi wpis zostaje w polu w całości, a okno mówi, o ile go skrócić.
"""
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout

from horreum import repo
from horreum.gui import i18n


class NoteIntent(NamedTuple):
    """Decyzja z okna: `("set", treść)` albo `("clear", None)`. Treść jest JUŻ znormalizowana -
    to dokładnie ten tekst, który zapisze klinga, więc wołający może nim porównywać bieżącą uwagę
    (życie recepty cofnięcia) bez drugiej kopii reguły normalizacji."""
    action: str
    body: str | None


class NoteDialog(QDialog):
    """Uwaga dla zaznaczenia `frame_count` klatek, z których `current` (`{frame_id: treść}`) ma już
    uwagę. Po `exec()`: `self.intent` = `None` (anulowano) albo `NoteIntent`.

    Prefill: gdy wszystkie klatki z uwagą mają tę samą treść - ta treść; przy różnych - pole puste,
    a zdanie stanu mówi, że zapis zastąpi je jedną. „Zapisz” jest wygaszone przy pustym polu i przy
    treści, której zapis nic by nie zmienił - czyli tylko wtedy, gdy CAŁE zaznaczenie ma już tę
    uwagę. Przy części klatek bez uwagi ta sama treść rozszerza ją na resztę i to jest prawdziwy
    zapis, więc przycisk zostaje czynny."""

    def __init__(self, *, current, frame_count, parent=None):
        super().__init__(parent)
        biezace = dict(current)
        if frame_count < 1 or len(biezace) > frame_count:
            raise ValueError(f"uwagi: {len(biezace)} klatek z uwagą na {frame_count} zaznaczonych")
        self.intent = None
        tresci = set(biezace.values())
        jedna = next(iter(tresci)) if len(tresci) == 1 else None
        self._jednolita = jedna if len(biezace) == frame_count else None
        self.setWindowTitle(i18n.t("note.title"))
        lay = QVBoxLayout(self)

        self.state = QLabel(_zdanie_stanu(len(biezace), frame_count, len(tresci)))
        self.state.setWordWrap(True)
        lay.addWidget(self.state)

        self.edit = QLineEdit(jedna or "")
        self.edit.setPlaceholderText(i18n.t("note.placeholder"))
        self.edit.setMinimumWidth(self.fontMetrics().averageCharWidth() * 60)
        lay.addWidget(self.edit)
        self.counter = QLabel()
        self.counter.setAlignment(Qt.AlignRight)
        self.counter.setProperty("role", "secondary")   # tekst drugorzędny z motywu, nie hex
        lay.addWidget(self.counter)
        self.too_long = QLabel("")
        self.too_long.setProperty("role", "error")      # kolor z motywu, nie sztywny hex
        self.too_long.setWordWrap(True)
        lay.addWidget(self.too_long)

        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton(i18n.t("note.save"), QDialogButtonBox.AcceptRole)
        self.clear_btn = buttons.addButton(i18n.t("note.clear"), QDialogButtonBox.DestructiveRole)
        self.cancel_btn = buttons.addButton(i18n.t("note.cancel"), QDialogButtonBox.RejectRole)
        # Enter w polu = „Zapisz”; wygaszony domyślny przycisk Enter po prostu połyka (QDialog nie
        # przechodzi wtedy do następnego przycisku), więc klawisz nie zapisze uwagi bez skutku.
        self.save_btn.setDefault(True)
        self.clear_btn.setEnabled(bool(biezace))
        self.save_btn.clicked.connect(self._on_save)
        self.clear_btn.clicked.connect(self._on_clear)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.edit.textChanged.connect(self._sync)
        self._sync()
        self.edit.setFocus()

    def _tresc(self):
        return repo.normalize_note(self.edit.text())

    def _do_zapisu(self, tekst):
        """Czy ten (znormalizowany) tekst jest zapisem, który klinga przyjmie i który coś zmieni -
        JEDEN warunek dla wygaszenia „Zapisz” i dla strażnika `_on_save`."""
        return bool(tekst) and len(tekst) <= repo.NOTE_MAX and tekst != self._jednolita

    def _sync(self):
        """Licznik, zdanie o nadmiarze i stan „Zapisz” po każdej zmianie pola. Licznik liczy znaki
        PO normalizacji - to jest liczba, którą sprawdza klinga, a nie liczba znaków w polu."""
        tekst = self._tresc()
        self.counter.setText(i18n.t("note.counter", n=len(tekst), max=repo.NOTE_MAX))
        nadmiar = len(tekst) - repo.NOTE_MAX
        self.too_long.setText(i18n.t_plural("note.too_long", nadmiar) if nadmiar > 0 else "")
        self.save_btn.setEnabled(self._do_zapisu(tekst))

    def _on_save(self):
        tekst = self._tresc()
        if not self._do_zapisu(tekst):           # strażnik obok wygaszenia (droga mimo przycisku)
            return
        self.intent = NoteIntent("set", tekst)
        self.accept()

    def _on_clear(self):
        self.intent = NoteIntent("clear", None)
        self.accept()


def _zdanie_stanu(z_uwaga, zaznaczone, roznych):
    """Zdanie nad polem: ile zaznaczonych klatek ma już uwagę i czy tę samą. Dwie liczby, dwie
    odmiany - orzeczenie idzie za klatkami Z UWAGĄ („ma” / „mają”), dopełnienie za zaznaczonymi
    („z 1 klatki” / „z 5 klatek”)."""
    if roznych > 1:
        return i18n.t_plural("note.state_mixed", zaznaczone, k=z_uwaga)
    if z_uwaga == 0:
        return i18n.t_plural("note.state_none", zaznaczone)
    if zaznaczone == 1:
        return i18n.t("note.state_single")
    return i18n.t_plural("note.state_some", z_uwaga,
                         of=i18n.t_plural("note.of_frames", zaznaczone))
