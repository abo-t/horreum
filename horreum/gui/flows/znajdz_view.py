"""Strona Znajdź - kontener nad TYM SAMYM `FramesView`, którym są Zbiory klasyczne.

Znajdź nie jest drugim gridem: stan zbioru, staging, busy i mutex zostają w `FramesView`, a ta strona
dokłada nad nim pasek zapytania i przełącza prezentację. Dwie drogi nawigacji (Znajdź, Zbiory klasyczne)
prowadzą na tę samą stronę stosu - różni je prezentacja, nie dane.

Zapytanie rozumie Qt-wolny `flows.znajdz` (parser + rozwiązanie na składniki stanu widoku); tutaj
zostaje widżet: pole z Enterem, zdanie „nie znam: …" i rząd chipów AKTYWNEGO stanu. Chipy nie są
drugim interfejsem facetów (listwa jest nim już) - pokazują każdy składnik zawężenia z „×", także
te, których prezentacja nie ma gdzie pokazać: w klasycznej rząd stoi wyłącznie dla tekstu uwag, bo
ten jeden nie ma tam własnej kontrolki, a zbiór nie może być zawężony niewidocznie.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from horreum.gui import i18n
from horreum.gui.flows import znajdz
from horreum.gui.grid import PREZENTACJA_KLASYCZNA, PREZENTACJA_ZNAJDZ

__all__ = ["ZnajdzView", "PREZENTACJA_ZNAJDZ", "PREZENTACJA_KLASYCZNA"]


class ZnajdzView(QWidget):
    """Kontener strony zbiorów: pasek Znajdź nad `frames_view`. `show_find`/`show_classic` to jedyne
    wejścia nawigacji; zapytanie podane przy wejściu stosuje się do stanu `frames_view`.

    `prezentacja_zmieniona(str)` pada przy każdej ZMIANIE prezentacji - także tej z wnętrza strony
    (czasownik „Zbiory klasyczne"), o której gospodarz nawigacji inaczej by nie wiedział."""

    prezentacja_zmieniona = Signal(str)

    def __init__(self, frames_view, parent=None):
        super().__init__(parent)
        self.frames_view = frames_view
        self.prezentacja = PREZENTACJA_KLASYCZNA
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # Pasek zapytania - wyłącznie w prezentacji Znajdź.
        self.pasek = QWidget()
        pl = QVBoxLayout(self.pasek)
        pl.setContentsMargins(8, 6, 8, 2)
        self.pole = QLineEdit()
        self.pole.setPlaceholderText(i18n.t("find.placeholder"))
        self.pole.setClearButtonEnabled(True)
        self.pole.returnPressed.connect(self._on_enter)
        self.pole.textEdited.connect(self._on_edycja)
        pl.addWidget(self.pole)
        self.zdanie = QLabel()
        self.zdanie.setProperty("role", "warn")
        self.zdanie.setWordWrap(True)
        self.zdanie.setVisible(False)
        self._niezrozumiale = ()        # `unmatched` ostatniego zapytania - zdanie pada z jego zbiorem
        self._tekst_zapytania = None    # tekst, który postawił przyłożony zbiór (pole go opisuje)
        self._nic = False               # ostatnie zapytanie nic nie rozpoznało - zbiór bez zmian
        pl.addWidget(self.zdanie)
        self.pasek.setVisible(False)
        lay.addWidget(self.pasek)

        # Rząd chipów - PULA przycisków tworzona raz i dokładana, nigdy kasowana: chip klikany
        # przeładowuje zbiór, a przeładowanie odbudowuje rząd - kasowanie przycisku w trakcie jego
        # własnego `clicked` to klasa awarii, którą repo zna z puli menu obiektu.
        # RZĄD W POZIOMYM PRZEWIJANIU, z polityką `Ignored`: chipy nie mają prawa podnosić minimalnej
        # szerokości strony - zmierzone natywnie: chip na każdą noc roku rozpychał okno do ~9000 px
        # na ekranie 2560, a okno zostawało szerokie po kolejnym zapytaniu.
        self._chipy_wnetrze = QWidget()
        self._chipy_lay = QHBoxLayout(self._chipy_wnetrze)
        self._chipy_lay.setContentsMargins(8, 0, 8, 2)
        self._chipy_lay.addStretch(1)
        self._pula = []
        self.chipy = QScrollArea()
        self.chipy.setWidget(self._chipy_wnetrze)
        self.chipy.setWidgetResizable(True)
        self.chipy.setFrameShape(QFrame.NoFrame)
        self.chipy.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chipy.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chipy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.chipy.setVisible(False)
        lay.addWidget(self.chipy)

        lay.addWidget(frames_view, 1)
        frames_view.stan_zbioru_zmieniony.connect(self._odbuduj_chipy)
        frames_view.classic_requested.connect(self.show_classic)

    def show_find(self, query=None):
        """Prezentacja Znajdź; `query` (gdy podane) zastępuje bieżący zbiór wynikiem zapytania.
        Fokus w polu - wejście z Domu albo z menu jest pytaniem, które człowiek zaraz wpisze."""
        self._ustaw_prezentacje(PREZENTACJA_ZNAJDZ)
        if query is not None:
            self.pole.setText(query)
            self._zastosuj(query)
        self.pole.setFocus()

    def show_classic(self):
        """Prezentacja klasyczna - dzisiejszy ekran Zbiorów, ten sam stan zbioru."""
        self._ustaw_prezentacje(PREZENTACJA_KLASYCZNA)

    def _ustaw_prezentacje(self, prezentacja):
        zmiana = prezentacja != self.prezentacja
        self.prezentacja = prezentacja
        self.frames_view.set_presentation(prezentacja)
        self.pasek.setVisible(prezentacja == PREZENTACJA_ZNAJDZ)
        self._odbuduj_chipy()
        if zmiana:
            self.prezentacja_zmieniona.emit(prezentacja)

    def _on_enter(self):
        self._zastosuj(self.pole.text())

    def _zastosuj(self, tekst):
        """Zapytanie → nowy zbiór widoku. Słownik archiwum czytany przy każdym zapytaniu: nazwy,
        noce i zestawy zmieniają się z każdą Dostawą, a pytanie zadaje się raz na Enter.

        Zdanie „nie znam: …" mówi „reszta zapytania działa", więc pada dopiero razem ze zbiorem
        tego zapytania (`_odbuduj_chipy` po przyłożeniu) - przy składzie w tle tabela pokazuje
        jeszcze poprzedni zbiór, a pasek stanu mówi „Wczytuję…".

        ZAPYTANIE, KTÓRE NIC NIE ROZPOZNAŁO, NIE ZASTĘPUJE ZBIORU: pusty stan po zastąpieniu znaczy
        „całe archiwum", więc `bzdura:xyz` pokazywało 16 901 klatek pod zdaniem „reszta zapytania
        działa". Zbiór zostaje, a zdanie mówi to wprost."""
        stan = znajdz.resolve(znajdz.parse(tekst), znajdz.catalog_from_db(self.frames_view.con))
        if stan.unmatched and not stan.recognized:
            self._nic = True
            self.zdanie.setText(i18n.t("find.nothing_matched", items=", ".join(stan.unmatched)))
            self.zdanie.setVisible(True)
            return
        self._nic = False
        self._tekst_zapytania = tekst
        self._niezrozumiale = stan.unmatched
        self.zdanie.setVisible(False)
        self.frames_view.apply_find(facets=stan.facets, filter_tree=stan.filter_tree,
                                    note_query=stan.note_query, terms=stan.terms)

    def _on_edycja(self, _tekst):
        """Człowiek pisze nowe zapytanie - zdanie o nierozpoznanym poprzednim schodzi."""
        if self._nic:
            self._nic = False
            self.zdanie.setVisible(False)

    def _pokaz_zdanie(self):
        """Zdanie „nie znam: …" i pole zapytania wobec PRZYŁOŻONEGO zbioru.

        POLE NIE UDAJE OPISU STANU: gdy zbiór przestał być tym, który postawiło zapytanie (chip,
        klik w listwie, perspektywa, „× Wyczyść zbiór"), pole się czyści, a zdanie o nim schodzi.
        Czyszczenie, nie przepisanie: stan bywa zmieniony kontrolkami, które nie mają zapisu
        w gramatyce pola (wykluczenie w listwie, filtr drzewiasty), a stan i tak mówią chipy.
        Pole, które człowiek właśnie edytuje (tekst inny niż przyłożone zapytanie), zostaje."""
        if self._nic or self.frames_view.zbior_w_drodze():
            return                       # zapytanie w toku - zdanie przyjdzie z jego zbiorem
        if self._tekst_zapytania is not None and not self.frames_view.zapytanie_aktualne():
            if self.pole.text() == self._tekst_zapytania:
                self.pole.clear()
            self._tekst_zapytania = None
            self._niezrozumiale = ()
        self.zdanie.setText(i18n.t("find.unmatched", items=", ".join(self._niezrozumiale))
                            if self._niezrozumiale else "")
        self.zdanie.setVisible(bool(self._niezrozumiale))

    def _odbuduj_chipy(self):
        """Rząd chipów z migawki PRZYŁOŻONEGO zbioru (`FramesView.skladniki_stanu`) - w Znajdź
        jeden chip na wpisany termin i na każdy składnik spoza zapytania, w klasycznej wyłącznie
        te bez własnej kontrolki."""
        self._pokaz_zdanie()
        skladniki = self.frames_view.skladniki_stanu(
            tylko_bez_kontrolki=self.prezentacja != PREZENTACJA_ZNAJDZ)
        while len(self._pula) < len(skladniki):
            chip = QPushButton(self._chipy_wnetrze)
            chip.setFlat(True)
            chip.setToolTip(i18n.t("find.chip.remove_tip"))
            chip.klucz = None
            chip.clicked.connect(lambda _c=False, b=chip: self._zdejmij(b))
            self._chipy_lay.insertWidget(len(self._pula), chip)
            self._pula.append(chip)
        for chip, skladnik in zip(self._pula, skladniki + [None] * len(self._pula)):
            if skladnik is None:
                chip.klucz = None
                chip.setVisible(False)
                continue
            chip.klucz, etykieta = skladnik
            chip.setText(f"{etykieta}  ×")
            chip.setVisible(True)
        # Wysokość rzędu = chip + pasek przewijania: przewijanie w poziomie nie może zjadać chipu.
        self.chipy.setFixedHeight(self._chipy_wnetrze.sizeHint().height()
                                  + self.chipy.horizontalScrollBar().sizeHint().height())
        self.chipy.setVisible(bool(skladniki))

    def _zdejmij(self, chip):
        if chip.klucz is not None:
            self.frames_view.zdejmij_skladnik(chip.klucz)
