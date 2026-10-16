"""Pasek zbioru i szuflada widoku „Klatki" - `SelectionBar`, `_PanelStack`, `StagingDrawer`.

Pasek zbioru (licznik, kryteria słowami, akcje), stos paneli kling z jednym widocznym naraz,
poczekalnia zmian (szuflada stagingu z kropką stanu) i okno zwolnienia klatek `ReleaseDialog`.
Warstwa widżetów.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QSize, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QDialog, QDialogButtonBox,
    QMenu, QStackedWidget, QToolButton, QVBoxLayout,
)

from horreum import stacks
from horreum.gui import i18n
from horreum.gui.grid_model import PREZENTACJA_KLASYCZNA, PREZENTACJA_ZNAJDZ, _set_role
from horreum.gui.grid_panels import ElidedLabel


class SelectionBar(QFrame):
    """Pasek ZBIORU (F3, PLAN_ux_redesign §4): licznik + kryteria słowami + akcje na zbiorze
    [Wydaj na stół…][Popraw nagłówki…][Uporządkuj nazwy plików…][★ Zapisz widok]. Przyciski paneli
    CHECKABLE — który panel otwarty widać bez klikania. Głupi widżet: FramesView łączy kliki i karmi
    etykiety (NARROW). Przyciski-panele ZAWSZE aktywne (gating checkable = pułapka
    disabled-but-checked-open, F3R#2); pusty zbiór gasi tylko „Wydaj na stół…"."""

    _PROJ_TIP = "grid.sel.proj_tip"   # KLUCZ (rozwiązywany i18n.t w use-site — nie zamrożony PL)

    # Skrót „ostatnio użyte" (R-S2b-12) niesie KOMPLET pól klingi, nie sam kanon: `user_assign_object`
    # INSERTuje obiekt, gdy kanon nowy, więc `catalog`/`kind` muszą dojechać razem z nazwą.
    objectRecentPicked = Signal(str, object, object)
    _RECENT_MAX = 5                   # sufit listy skrótu (dług mówi „3-5"); tyle samo pyta read-model

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        # Dwa rzędy w zapasie (AR-77): rząd przycisków i - tylko gdy obok przycisków nie mieści się
        # nawet pierwsze kryterium - rząd samych kryteriów pod nim (`_dopasuj_kryteria`).
        self._zew = QVBoxLayout(self); self._zew.setContentsMargins(8, 4, 8, 4); self._zew.setSpacing(2)
        lay = QHBoxLayout(); lay.setContentsMargins(0, 0, 0, 0)
        self._zew.addLayout(lay)
        self._kryteria_pod = False
        self.count_label = QLabel("")
        f = QFont(); f.setBold(True); self.count_label.setFont(f)
        self.criteria_label = ElidedLabel()
        self.criteria_label.setProperty("role", "secondary")   # kryteria zbioru czytelne na dark (F6 §7)
        self.btn_proj = QPushButton(i18n.t("grid.sel.project"))
        self.btn_proj.setToolTip(i18n.t(self._PROJ_TIP))
        # ZŁOTA AKCJA Zbiorów (wiz F3 #3, dług zamknięty w P-C): jedna akcja na miejsce niesie wagę
        # wizualną — wzorzec „Przyjmij nowe" (`pipeline._build_ui`). Waga = BOLD, nie kolor: złoto
        # motywu ma w jasnej skórce 2,7:1 i jako tekst nie dochodzi do progu czytelności (wiz T5 N5).
        # Bez podnoszenia wysokości — pasek zbioru trzyma pięć przycisków w jednym rzędzie.
        _f = self.btn_proj.font(); _f.setBold(True); self.btn_proj.setFont(_f)
        # „Wydaj obiekt…" obok „Wydaj na stół…": ta sama sprawa (wydanie), inne wejście - nie zbiór
        # gridu, tylko teczka obiektu z okna wyboru. Dlatego ZAWSZE aktywny przy otwartej bazie
        # i bez `set_have_frames`: pusty zbiór niczego tu nie odbiera. Bez pogrubienia - złota akcja
        # paska jest jedna.
        self.btn_obj = QPushButton(i18n.t("grid.sel.release_object"))
        self.btn_obj.setToolTip(i18n.t("grid.sel.release_object_tip"))
        # „× Wyczyść zbiór" (wiz F4 #3): jednoklikowe zdjęcie facetów + filtra — bez niego jedyną
        # drogą było od-cyklowanie każdej wartości (preset „Przegląd" = no-op, gdy już wybrany).
        self.btn_clear = QPushButton(i18n.t("grid.sel.clear_set"))
        self.btn_clear.setToolTip(i18n.t("grid.sel.clear_tip"))
        self.btn_macro = QPushButton(i18n.t("grid.sel.fix_headers")); self.btn_macro.setCheckable(True)
        self.btn_rename = QPushButton(i18n.t("grid.sel.tidy_names")); self.btn_rename.setCheckable(True)
        # Panel rodowodu (I-2d) — trzeci panel stacku. ZAWSZE aktywny, jak pozostałe przyciski-panele
        # (F3R#2: gating checkable = pułapka disabled-but-checked-open); niewłaściwe zaznaczenie
        # tłumaczy sam panel zdaniem, a nie wygaszony przycisk, który nie mówi DLACZEGO.
        self.btn_lineage = QPushButton(i18n.t("grid.sel.lineage")); self.btn_lineage.setCheckable(True)
        self.btn_lineage.setToolTip(i18n.t("grid.sel.lineage_tip"))
        # OŚ OBIEKTU NA ZAZNACZENIU (S2b, D-OW-6) — JEDNA kontrolka z menu, nie dwa przyciski:
        # pasek trzyma już sześć, a siódmy i ósmy przewróciłyby go do drugiego rzędu. Obie pozycje
        # są tą samą sprawą („co to za obiekt"), więc menu jest tu grupowaniem, nie chowaniem.
        self.btn_object = QToolButton()
        # JEDEN CHEVRON, NIE DWA (R-S2b-11): tekst niósł własne „▾", a `InstantPopup` dokłada do
        # tego natywny wskaźnik menu — kontrolka zapowiadała rozwinięcie dwa razy. Strzałkę rysuje
        # styl, więc to ona zostaje: zna platformę i motyw, a literał w stringu nie.
        self.btn_object.setText(i18n.t("grid.sel.object"))
        self.btn_object.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.btn_object)
        self.act_name = menu.addAction(i18n.t("grid.sel.object_name"))
        self.act_clear = menu.addAction(i18n.t("grid.sel.object_clear"))
        # DROGA POWROTU STOI OBOK GESTU, KTÓRY JEJ WYMAGA (R-S2b-3). Pozycja jest WIDOCZNA ZAWSZE,
        # nie tylko gdy ma co robić — inaczej user dowiadywałby się o odwracalności dopiero PO
        # pomyłce, czyli w jedynym momencie, w którym wiedza „to się da cofnąć" jest już spóźniona.
        # Populacja nagrobków jest z natury rzadka, więc ta pozycja bywa wygaszona przez większość
        # czasu; powód niesie tooltip KONTROLKI (menu w tym repo nie pokazuje tooltipów pozycji).
        self.act_restore = menu.addAction(i18n.t("grid.sel.object_restore"))
        # ZMIANA OBIEKTU RAZEM Z PLIKIEM (AR-17 krok 3) za własną kreską: trzy pozycje wyżej piszą
        # wyłącznie bazę, ta przenosi plik do folderu obiektu i pisze kartę `OBJECT` - inna waga
        # gestu, więc nie stoi z nimi w jednym ciągu. Rusza KAŻDE źródło nazwy (także nagłówek),
        # bo to jest jawne przepięcie ręką z podglądem i drogą powrotu, nie nadpisanie słabego.
        menu.addSeparator()
        self.act_change = menu.addAction(i18n.t("grid.sel.object_change"))
        # Pula skrótu „ostatnio użyte" (R-S2b-12) — tworzona RAZ; treść i widoczność ustawia
        # `set_recent_objects`. Powód takiego kształtu, a nie dokładania akcji: patrz jej docstring.
        self._recent_sep = menu.addSeparator()
        self._recent_sep.setVisible(False)
        self._recent_acts = [menu.addAction("") for _ in range(self._RECENT_MAX)]
        for act in self._recent_acts:
            act.setVisible(False)
            act.triggered.connect(lambda _checked=False, a=act: self.objectRecentPicked.emit(*a.data()))
        self.btn_object.setMenu(menu)
        # OŚ ŻYWOTNOŚCI KLATKI (D-OW-3/R2) — druga kontrolka z menu, tym samym argumentem co
        # „Obiekt ▾" (D-OW-6): obie pozycje to jedna sprawa („czy ta klatka jest jeszcze robotą"),
        # a dwa osobne przyciski rozsypałyby pasek. ⛔ Do menu obiektu tego NIE wkładamy: tamto
        # menu ma własny słownik powodów (`_object_gate_reason` → klucze `grid.sel.object_tip_*`),
        # więc wspólna kontrolka kazałaby jednemu tooltipowi tłumaczyć dwie różne osie.
        self.btn_frame = QToolButton()
        self.btn_frame.setText(i18n.t("grid.sel.frame"))
        self.btn_frame.setPopupMode(QToolButton.InstantPopup)
        fmenu = QMenu(self.btn_frame)
        self.act_retire = fmenu.addAction(i18n.t("grid.sel.frame_retire"))
        # DROGA POWROTU STOI OBOK GESTU, KTÓRY JEJ WYMAGA — ta sama reguła, co przy `act_restore`
        # osi obiektu: pozycja widoczna ZAWSZE, także wygaszona, bo o odwracalności trzeba wiedzieć
        # PRZED pomyłką. Tu waży to podwójnie: wycofanie zdejmuje klatkę z oczu, więc bez tej
        # pozycji user nie miałby skąd wiedzieć, że gest w ogóle się cofa.
        self.act_frame_restore = fmenu.addAction(i18n.t("grid.sel.frame_restore"))
        # UWAGI (0032) w klasycznej mieszkają w menu klatki - to fakt ręki o KLATCE, a dziewiąty
        # przycisk paska poszerzałby podłogę okna. W Znajdź ten sam gest ma własny czasownik
        # (`btn_notes`); obie drogi wołają jeden slot.
        fmenu.addSeparator()
        self.act_notes = fmenu.addAction(i18n.t("grid.notes.action"))
        self.btn_frame.setMenu(fmenu)
        # CZASOWNIKI ZNAJDŹ, których klasyczna nie ma - tworzone raz, widoczne tylko w tamtej
        # prezentacji (`set_presentation`). „Kolumny ▾" niesie wyłącznie kolumnę „Wersja" (AR-50):
        # prosty zestaw kolumn Znajdź jest stały, a wybór keywordów zostaje w „Polach" klasycznej.
        # Z RODZICEM od urodzenia: w klasycznej te przyciski nie trafiają do układu, więc nikt ich
        # nie przepina - widżet bez rodzica pokazany przy wejściu w Znajdź byłby oknem najwyższego
        # poziomu i zabierał aktywację oknu głównemu (fokus pola zapytania ginął po obrocie pętli).
        self.btn_notes = QPushButton(i18n.t("grid.notes.action"), self)
        self.btn_columns = QToolButton(self)
        self.btn_columns.setText(i18n.t("find.verb.columns"))
        self.btn_columns.setPopupMode(QToolButton.InstantPopup)
        cmenu = QMenu(self.btn_columns)
        self.act_version_col = cmenu.addAction(i18n.t("grid.col.version"))
        self.act_version_col.setCheckable(True)
        self.btn_columns.setMenu(cmenu)
        self.btn_classic = QPushButton(i18n.t("nav.zbiory"), self)   # nazwa wiersza nawigacji
        self.btn_save = QPushButton(i18n.t("grid.sel.save_view"))
        # RÓWNA WYSOKOŚĆ W RZĘDZIE (R-S2b-11): `QToolButton` liczy `sizeHint` inaczej niż
        # `QPushButton` i wychodził o 1 px niższy od sześciu sąsiadów — jedyny widżet innej klasy
        # w rzędzie wyglądał jak wpadka układu. Wysokość bierzemy z SĄSIADA, nie z liczby: stała
        # rozjechałaby się przy pierwszej zmianie motywu albo skali DPI.
        self.btn_object.setFixedHeight(self.btn_save.sizeHint().height())
        self.btn_frame.setFixedHeight(self.btn_save.sizeHint().height())
        self.btn_columns.setFixedHeight(self.btn_save.sizeHint().height())
        self._lay = lay
        self.prezentacja = PREZENTACJA_KLASYCZNA
        self._uloz()

    # Kolejność i skład rzędu per prezentacja. Klasyczna = dzisiejszy pasek co do widżetu i odstępu
    # (testy go pinują); Znajdź = pasek czasowników w ustalonej kolejności (Wydaj do WBPP ·
    # Popraw nagłówki… · Obiekt ▾ · Rodowód… · Uwagi… · Kolumny ▾ · Zbiory klasyczne). `None` =
    # odstęp 12 px. Widżety spoza listy prezentacji są schowane, nie usunięte - to te same
    # przyciski z tym samym stanem (zaznaczenie paneli, wygaszenie przy zajętości).
    def _rzad(self):
        if self.prezentacja == PREZENTACJA_ZNAJDZ:
            return [self.btn_clear, None, self.btn_obj, self.btn_macro, self.btn_object,
                    self.btn_lineage, self.btn_notes, self.btn_columns, None, self.btn_classic]
        # Złota akcja WYJĘTA z klastra pomocniczych (wizytacja P-C #6): sam bold przegrywał wzrokowo
        # z glifem ★ sąsiada, bo wszystkie pięć stało w jednym ciągu. Odstęp, nie ramka — QSS
        # `border` na QPushButton w Fusion zastępuje CAŁE malowanie ramki i spłaszcza przycisk.
        return [self.btn_clear, None, self.btn_proj, self.btn_obj, None, self.btn_macro,
                self.btn_rename, self.btn_lineage, self.btn_object, self.btn_frame, self.btn_save]

    def _uloz(self):
        lay = self._lay
        while lay.count():
            lay.takeAt(0)            # widżety zostają dziećmi paska; odstępy znikają z elementem
        self._zew.removeWidget(self.criteria_label)
        lay.addWidget(self.count_label); lay.addSpacing(8)
        if self._kryteria_pod:
            lay.addStretch(1)        # przyciski zostają przy prawej krawędzi, jak w jednym rzędzie
            self._zew.addWidget(self.criteria_label)
        else:
            lay.addWidget(self.criteria_label, 1)
        rzad = self._rzad()
        # NAJPIERW UKŁAD, POTEM WIDOCZNOŚĆ: widżet pokazywany jest już na swoim miejscu w pasku.
        for w in rzad:
            if w is None:
                lay.addSpacing(12)
            else:
                lay.addWidget(w)
        for w in (self.btn_clear, self.btn_proj, self.btn_obj, self.btn_macro, self.btn_rename,
                  self.btn_lineage, self.btn_object, self.btn_frame, self.btn_save,
                  self.btn_notes, self.btn_columns, self.btn_classic):
            w.setVisible(w in rzad)

    def set_presentation(self, prezentacja):
        """Pasek w prezentacji `prezentacja`: skład, kolejność i nazwa wydania obiektu. „Wydaj
        obiekt…" i „Wydaj do WBPP" to JEDEN przycisk (`_open_object_release`) - w Znajdź nosi nazwę
        czasownika z Domu, bo tam człowiek mówi, CO chce zrobić, a nie którym oknem."""
        self.prezentacja = prezentacja
        znajdz = prezentacja == PREZENTACJA_ZNAJDZ
        self.btn_obj.setText(i18n.t("find.verb.release" if znajdz else "grid.sel.release_object"))
        self._uloz()

    def set_criteria(self, text):
        self.criteria_label.set_full_text(text)
        self._dopasuj_kryteria()

    # ---- miejsce kryteriów (AR-77) ----
    # KRYTERIA MAJĄ PIERWSZEŃSTWO PRZED PRZYCISKAMI. Przyciski nie maleją poniżej podpowiedzi
    # (tekst przycisku nie podlega elizji), więc w jednym rzędzie kryteria dostawały resztę - przy
    # „1 zaznaczona" licznik urósł i „Obiekt: NGC1976" zwijał się do „Obie…" (firsthand W11, okno
    # przy podłodze). Gdy obok przycisków nie mieści się nawet PIERWSZE kryterium, kryteria schodzą
    # do własnego rzędu na całą szerokość paska. Minimum paska nie rośnie (podłogę okna wiąże
    # `QSplitter` widoku, kanon „MINIMALNY WSPIERANY EKRAN"), a drugi rząd kosztuje wysokość
    # jednej linii tekstu wyłącznie wtedy, gdy bez niego kryteria byłyby nieczytelne.
    _SEPARATOR_KRYTERIOW = " · "     # łącznik `FramesView._describe_criteria`

    def _miejsce_na_kryteria(self):
        """Szerokość, jaką kryteria dostałyby w JEDNYM rzędzie z przyciskami przy bieżącej szerokości
        paska. Liczona z podpowiedzi sąsiadów (przyciski i licznik nie schodzą poniżej nich), nie
        z geometrii etykiety - w trybie dwóch rzędów etykiety w rzędzie nie ma. `QBoxLayout` stawia
        odstęp układu między WIDŻETAMI (licznik, kryteria, przyciski), a nie przy odstępach stałych."""
        rzad = self._rzad()
        przyciski = [w for w in rzad if w is not None]
        m = self._zew.contentsMargins()
        zajete = (m.left() + m.right() + self.count_label.sizeHint().width() + 8
                  + sum(w.sizeHint().width() for w in przyciski)
                  + 12 * (len(rzad) - len(przyciski))
                  + self._lay.spacing() * (len(przyciski) + 1))
        return self.contentsRect().width() - zajete       # bez ramki `StyledPanel`

    def _potrzeba_kryteriow(self):
        """Szerokość pierwszego kryterium razem z „…" (za nim idą kolejne) i z zapasem elizji
        `ElidedLabel` (4 px) - poniżej niej etykieta nie mówi już nawet, CO zawęża zbiór."""
        pierwsze = self.criteria_label.full_text().split(self._SEPARATOR_KRYTERIOW, 1)[0]
        if not pierwsze:
            return 0
        return self.criteria_label.fontMetrics().horizontalAdvance(pierwsze + "…") + 5

    def _dopasuj_kryteria(self):
        """Kryteria w rzędzie przycisków albo pod nim - przełożenie tylko przy zmianie trybu, więc
        `LayoutRequest`, który przełożenie samo wywoła, kończy się tu bez pracy. Niepokazany pasek
        zostaje w jednym rzędzie: jego szerokość nie jest jeszcze szerokością z układu."""
        if not self.isVisible():
            return
        pod = self._miejsce_na_kryteria() < self._potrzeba_kryteriow()
        if pod != self._kryteria_pod:
            self._kryteria_pod = pod
            self._uloz()

    def event(self, e):
        # Licznik zmienia tekst z zewnątrz (`FramesView._update_count` pisze wprost do etykiety),
        # a każda zmiana podpowiedzi sąsiada kończy się `LayoutRequest` na pasku.
        if e.type() == QEvent.LayoutRequest:
            self._dopasuj_kryteria()
        return super().event(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._dopasuj_kryteria()

    def showEvent(self, e):
        super().showEvent(e)
        self._dopasuj_kryteria()

    def set_object_actions(self, *, namable, clearable, changeable, stacks=0, restorable=0,
                           reason=None):
        # `stacks` = ILE GEST RUSZY, nie ile ich jest w zaznaczeniu — parametr karmi wyłącznie
        # zdanie o skutku, więc wołający podaje `stacks_touchable` (bramka pakietu 0810, zarzut 1).
        # `changeable` = klatki nieba (light, master_light) z jedną obecną kopią, z obiektem albo bez -
        # „Zmień obiekt…" rusza każde źródło nazwy, więc ta liczba nie wynika z `namable`. Parametr
        # BEZ domyślnej: wołający, który o nim zapomni, ma paść wywołaniem, a nie gasić pozycję.
        """Uczciwy disabled obu pozycji osi obiektu (S2b, §4/14c-a). Cel gestu to WYŁĄCZNIE
        zaznaczenie, więc przy pustym gaśnie wszystko — fallback „to, co widoczne" jest dla ZAPISU
        osi ZAKAZANY (800 widocznych klatek i jedno chybione kliknięcie to ta sama sekunda).
        Kontrolka zbiorcza zostaje żywa, dopóki cokolwiek da się zrobić: menu, które tłumaczy
        wygaszoną pozycję, mówi WIĘCEJ niż wygaszony przycisk bez powodu.

        `reason` (klucz i18n z `_object_gate_reason`) niesie POWÓD wygaszenia — bez niego szara
        kontrolka odbierała jedyną powierzchnię, która mogła cokolwiek wytłumaczyć (R-S2b-8).
        Przy AKTYWNEJ kontrolce tooltip mówi, ile klatek gest realnie ruszy: to ta sama liczba,
        którą pokaże okno, więc user poznaje ją PRZED kliknięciem, a nie po."""
        self.act_name.setEnabled(bool(namable))
        self.act_clear.setEnabled(bool(clearable))
        self.act_restore.setEnabled(bool(restorable))
        self.act_change.setEnabled(bool(changeable))
        # `restorable` W WARUNKU JAWNIE, choć dziś jest nadmiarowy: każdy nagrobek jest też
        # `namable` (`object_id IS NULL` ⇒ do nazwania), więc kontrolka i tak by żyła. Zależność
        # jest jednak NIEJAWNA i pęknie przy pierwszej zmianie `WEAK_OBJECT_SOURCES` — wtedy
        # kontrolka gasłaby nad żywą pozycją menu, czyli odbierała jedyną drogę do gestu.
        # `changeable` z tego samego powodu: zaznaczenie samych klatek z nagłówka (~95% lightów
        # archiwum) nie ma czego nazwać ani cofnąć, a obiekt da się mu zmienić - kontrolka gasnąca
        # nad żywą „Zmień obiekt…" odbierałaby jedyną drogę do tego gestu.
        baza = bool(namable or clearable or restorable)
        aktywna = baza or bool(changeable)
        self.btn_object.setEnabled(aktywna)
        if not aktywna:
            self.btn_object.setToolTip(i18n.t(reason or "grid.sel.object_tip_empty"))
            return
        if not baza:
            # ŻYWA TYLKO DLA „Zmień obiekt…": powód, dla którego trzy gesty bazy milczą, nie traci
            # się razem z wygaszeniem (R-S2b-8) - stoi pierwszy, a za nim to, co gest z plikiem
            # ruszy. Zdanie „nazwa z nagłówka - poprawia się w pliku" i pozycja, która poprawia ją
            # w pliku, mówią wtedy jedno.
            self.btn_object.setToolTip(
                i18n.t(reason or "grid.sel.object_tip_empty") + "\n"
                + i18n.t_plural("grid.sel.object_change_tip_only", changeable))
            return
        # CZŁON O GOTOWYCH OBRAZACH PRZED GESTEM, nie po nim (R-S3-8). Powód `object_tip_stacks`
        # broni wyłącznie zaznaczenia z SAMYCH stosów — tam gasi kontrolkę. Przy zaznaczeniu
        # MIESZANYM nikt ich nie liczył, więc o tym, że gest ruszył gotowe obrazy (każdy złożony
        # z setek klatek), user dowiadywał się dopiero ze zdania po zapisie. Ten sam klucz, co
        # tamto zdanie — jedna fraza, jeden właściciel. Milczy przy zerze: „w tym gotowe obrazy: 0"
        # mówiłoby o czymś, czego w zaznaczeniu nie ma.
        # ...i liczy WYŁĄCZNIE stosy, które gest ruszy. Zmierzone: 181 ze 193 stosów archiwum ma
        # nazwę ze źródła mocnego, więc człon liczony „ile stosów jest w zaznaczeniu" kłamałby
        # w 94% przypadków — w tooltipie, który powstał po to, żeby powiedzieć prawdę PRZED gestem.
        tip = i18n.t("grid.sel.object_tip_ready", namable=namable, clearable=clearable)
        # TRZECIA DROGA MA BYĆ W TYM SAMYM ZDANIU, co dwie pierwsze — inaczej powtórzyłaby klasę
        # R-S3-8: tooltip zapowiadałby dwie liczby, a menu oferowało trzy akcje. Milczy przy zerze,
        # bo „do przywrócenia: 0" mówiłoby o czymś, czego w zaznaczeniu nie ma.
        if restorable:
            tip += i18n.t("grid.sel.object_tip_restorable", n=restorable)
        if changeable:
            tip += i18n.t("grid.sel.object_change_tip", n=changeable)
        if stacks:
            tip += i18n.t_plural("grid.sel.object_stacks", stacks)
        self.btn_object.setToolTip(tip)

    def set_frame_actions(self, *, retirable, restorable, reason=None, notes=0):
        """Uczciwy disabled osi żywotności klatki (D-OW-3/R2) — wzorzec `set_object_actions`.

        Powód wygaszenia liczy `_frame_gate_reason` i niesie go tooltip KONTROLKI: menu w tym repo
        nie pokazuje tooltipów pozycji, a szara kontrolka bez powodu odbiera jedyną powierzchnię,
        która mogła cokolwiek wytłumaczyć (dług R-S2b-8, zamknięty na sąsiedniej osi).

        Liczby biorą się z WIERSZY, które i tak są na ekranie (`base_rows` niesie `retired_at`,
        `present`, `n_present`, `superseded_by`) — bez nowego zapytania w gorącej pętli zaznaczenia.
        To jest PREZENTACJA, nie prawda: prawdę rozstrzyga klinga wewnątrz transakcji, bo między
        zaznaczeniem a zapisem plik może wrócić na dysk.

        `notes` = ile klatek dostanie uwagę (całe zaznaczenie - uwagę może mieć każda klatka).
        Uwaga trzyma kontrolkę przy życiu także wtedy, gdy oś żywotności nie ma nic do zrobienia;
        powód wygaszenia tamtej osi zostaje wtedy w tooltipie obok liczby, bo pozycja „Wycofaj…"
        dalej jest szara i ktoś zapyta dlaczego."""
        self.act_retire.setEnabled(bool(retirable))
        self.act_frame_restore.setEnabled(bool(restorable))
        self.act_notes.setEnabled(bool(notes))
        self.btn_notes.setEnabled(bool(notes))
        self.btn_notes.setToolTip(i18n.t_plural("grid.notes.tip_ready", notes) if notes
                                  else i18n.t("grid.notes.tip_empty"))
        zywotnosc = bool(retirable or restorable)
        self.btn_frame.setEnabled(zywotnosc or bool(notes))
        if zywotnosc:
            tip = i18n.t("grid.sel.frame_tip_ready", retirable=retirable, restorable=restorable)
        else:
            tip = i18n.t(reason or "grid.sel.frame_tip_empty")
        if notes:
            tip += "\n" + i18n.t_plural("grid.notes.tip_ready", notes)
        self.btn_frame.setToolTip(tip)

    def set_recent_objects(self, obiekty):
        """Skrót „ostatnio użyte" na dole menu obiektu (R-S2b-12) — 5 interakcji spada do 2.

        Najczęstszy gest brzmi „te klatki to ZNOWU NGC6960" i kosztował: Obiekt ▾ · Przypisz… ·
        rozwiń combo · wybierz · Przypisz. Skrót nie jest drugą ścieżką zapisu — kończy w tej samej
        klindze i z tym samym kluczem aliasu (`assign_dialog.alias_key`), pomija wyłącznie WYBÓR.

        Treść odświeża się przy każdym pokazaniu menu: lista jest pochodną dziennika i zmienia się
        po każdym geście, więc zbudowana raz kłamałaby dokładnie tam, gdzie ma pomagać.
        Wygaszone razem z „Przypisz obiekt…" — skrót nie może omijać bramki, którą ta pozycja stoi.

        PULA STAŁA, NIE TWORZENIE-I-USUWANIE — i to jest poprawka po awarii, nie mikrooptymalizacja.
        Pierwsza wersja dokładała `QAction` na każde otwarcie menu; bramka pakietu słusznie wytknęła
        rosnące sieroty (`removeAction` zdejmuje z menu, ale nie zwalnia), a zaproponowane lekarstwo
        — `deleteLater()` — **wywaliło Qt access violation** w losowym późniejszym teście kręcącym
        pętlą zdarzeń: usunięcie jest ODROCZONE, a menu bywa do tego czasu zebrane przez Pythona.
        Zmierzone: pełna bateria kończyła się `Fatal Python error: Aborted`, bez `deleteLater` jest
        czysta. Pula tworzona RAZ w konstruktorze nie ma ani sierot, ani odroczonych usunięć —
        pozycje nadmiarowe po prostu znikają (`setVisible(False)`).

        `_RECENT_MAX` jest sufitem listy: read-model i tak pyta o tyle samo, a menu z dwudziestoma
        pozycjami przestałoby być skrótem."""
        obiekty = list(obiekty)[:self._RECENT_MAX]
        self._recent_sep.setVisible(bool(obiekty))
        for act, o in zip(self._recent_acts, obiekty + [None] * self._RECENT_MAX):
            if o is None:
                act.setVisible(False)
                continue
            act.setText(i18n.t("grid.sel.object_recent", canon=o["canon"]))
            act.setData((o["canon"], o["catalog"], o["kind"]))
            act.setEnabled(self.act_name.isEnabled())
            act.setVisible(True)

    def set_clearable(self, on):
        """Uczciwy disabled „× Wyczyść zbiór": aktywny TYLKO gdy jest co zdjąć (facety/filtr)."""
        self.btn_clear.setEnabled(on)

    def set_have_frames(self, on):
        """Uczciwy disabled TYLKO realnej akcji na zbiorze (F3R#2): pusty zbiór gasi „Wydaj na stół…"
        (guard `_open_projection` zostaje drugą linią); „★ Zapisz widok" i panele zawsze żywe."""
        self.btn_proj.setEnabled(on)
        self.btn_proj.setToolTip(i18n.t(self._PROJ_TIP) if on else i18n.t("grid.sel.proj_tip_empty"))

    def set_active_panel(self, which):
        """Synchronizuj zaznaczenie przycisków-paneli ze stanem stacku (`None`/'macro'/'rename');
        blockSignals — to odbicie stanu, nie klik."""
        for btn, key in ((self.btn_macro, "macro"), (self.btn_rename, "rename"),
                         (self.btn_lineage, "lineage")):
            btn.blockSignals(True)
            btn.setChecked(which == key)
            btn.blockSignals(False)


class _PanelStack(QStackedWidget):
    """Stack paneli kling (F3): sizeHint = BIEŻĄCA strona — goły QStackedWidget bierze max ze stron,
    więc otwarte makro wisiałoby w pasie wysokości renamu [skill: pyside6-desktop-layout-gotchas].

    SAM sizeHint NIE WYSTARCZYŁ i to jest lekcja zmierzona, nie teoria (firsthand 2026-08-02).
    Nadpisane podpowiedzi czyta layout RODZICA, ale wewnętrzny `QStackedLayout` osobno wymusza na
    tym widżecie minimum równe NAJWYŻSZEJ stronie — więc stack i tak nie schodził poniżej 240 px
    (wysokość renamu), a niska strona wisiała w nim WYŚRODKOWANA. Zmierzone na realnym oknie:
    panel rodowodu zajmował 68 px treści, a odbierał tabeli 246 px — 92 px martwego pasa nad
    i 92 pod. Panel makra tracił 6 px, bo jego strona jest bliska maksimum i pasa nie widać.

    Dlatego sufit jest USTAWIANY WPROST z bieżącej strony — przy przełączeniu strony i przy każdej
    zmianie jej treści (`LayoutRequest`), bo panele rosną i maleją w biegu (ostrzeżenie w rodowodzie,
    rzędy tokenów w renamie)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ŹRÓDŁO PUSTKI: `QLayout` z domyślnym `SetDefaultConstraint` wpisuje widżetowi TWARDE
        # `minimumSize` równe maksimum ze stron — i to ono, nie podpowiedzi, trzymało stack na
        # wysokości renamu. Zdejmujemy wymuszanie i czyścimy minimum wpisane przed tą zmianą;
        # od tej pory o wysokości decydują nadpisane niżej podpowiedzi BIEŻĄCEJ strony.
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumHeight(0)
        self.currentChanged.connect(lambda _i: self._sync_ceiling())

    def event(self, e):
        # DWA KROKI SĄ KONIECZNE, każdy leczy co innego (zmierzone osobno):
        # zdjęcie wymuszenia pozwala stackowi ZEJŚĆ do wysokości bieżącej strony, a sufit sprawia,
        # że layout rodzica nie rezerwuje slotu na najwyższą stronę i nie centruje w nim niskiej.
        # Sufit liczymy przy `LayoutRequest`, bo panele rosną i maleją BEZ przełączania strony
        # (ostrzeżenie w rodowodzie, rzędy tokenów w renamie) — i dopiero po zdjęciu wymuszenia
        # podpowiedź strony jest w tym momencie już prawdziwa. Sam sufit obcinał treść o krok.
        if e.type() == QEvent.LayoutRequest:
            self._sync_ceiling()
        return super().event(e)

    def _sync_ceiling(self):
        """Sufit = wysokość BIEŻĄCEJ strony, z JEDNĄ synchroniczną przeliczką rodzica.

        Bez niej sufit był o krok w tyle i OBCINAŁ treść (zmierzone: strona żądała 68 px, stack
        stał na 56, lista traciła 12 px z 40) — `setMaximumHeight` w trakcie `LayoutRequest` trafia
        w przebieg, który rodzic już policzył. Guard równości zamyka pętlę: przeliczka rodzica
        wraca tu `LayoutRequest`-em, ale przy niezmienionym suficie nie robi nic."""
        w = self.currentWidget()
        if w is None:
            return
        h = w.sizeHint().height()
        if self.maximumHeight() != h:
            self.setMaximumHeight(h)
            rodzic = self.parentWidget()
            if rodzic is not None and rodzic.layout() is not None:
                rodzic.layout().activate()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()



class _ZdanieWyniku(QLabel):
    """Zdanie wyniku szuflady: `text()` i podpowiedź niosą PEŁNĄ treść, render jest elidowany
    w prawo do bieżącej szerokości, a minimum szerokości NIE zależy od długości zdania.

    Zwykły `QLabel` bez zawijania zgłasza minimum = szerokość całego tekstu i to minimum idzie
    w górę aż do okna: zdanie porażki gestu (368 znaków, firsthand) podniosło minimum okna do
    2613 px logicznych - 103 px poza ekranem 2560, bez możliwości zwężenia. Zawijanie odpadło, bo
    szuflada jest jednym wierszem, a jej wysokość ruszałaby tabelą przy każdym wyniku. Elizja
    w malowaniu, nie w `setText`: wołający czytają `text()` jako treść wyniku, więc przycięta wersja
    w tym polu mówiłaby mniej, niż gest powiedział."""

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.contentsRect()
        tekst = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        self.style().drawItemText(painter, rect, int(self.alignment()), self.palette(),
                                  self.isEnabled(), tekst, self.foregroundRole())


class StagingDrawer(QFrame):
    """Stała szuflada dolna stagingu (doktryna §5: „N zmian oczekuje · Przejrzyj · Zatwierdź · Odrzuć").
    Postęp i wynik commitu renderują się TU (nie w łańcuchu modali). Emituje `commit()`/`reject()`."""

    commit = Signal()
    reject = Signal()
    cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self); lay.setContentsMargins(8, 4, 8, 4)
        self.dot = QLabel("○")
        self.label = QLabel(i18n.t("grid.drawer.empty"))   # słownik F3 (§4)
        # Wynik i postęp (nazwa pliku) mają dowolną długość - elidowane, pełne w podpowiedzi.
        self.result = _ZdanieWyniku(""); self.result.setProperty("role", "secondary")   # F6 §7
        # Postęp writebacku renderuje się TU (nie w modalu): pasek + „Anuluj" wchodzą w miejsce
        # Zatwierdź/Odrzuć na czas commitu/undo (off-thread — GUI nie zamarza; rdzeń commituje per-plik).
        self.bar = QProgressBar(); self.bar.setVisible(False); self.bar.setMaximumWidth(220); self.bar.setTextVisible(False)
        self.btn_cancel = QPushButton(i18n.t("grid.action.cancel")); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(lambda: self.cancel.emit())
        self.btn_commit = QPushButton(i18n.t("grid.action.commit")); self.btn_commit.clicked.connect(lambda: self.commit.emit())
        self.btn_reject = QPushButton(i18n.t("grid.action.reject")); self.btn_reject.clicked.connect(lambda: self.reject.emit())
        # Klaster licznik+wynik po LEWEJ (dot·label·result), rozpychacz, akcje po prawej — inaczej
        # `result` ze stretch=1 rozrzucał licznik i przyciski na całą szerokość (wizytator D1).
        lay.addWidget(self.dot); lay.addWidget(self.label); lay.addSpacing(8)
        lay.addWidget(self.result); lay.addStretch(1)
        lay.addWidget(self.bar); lay.addWidget(self.btn_cancel)
        lay.addWidget(self.btn_commit); lay.addWidget(self.btn_reject)
        self.set_count(0)

    def begin_progress(self, total):
        """Wejście w tryb postępu (start commitu/undo): pasek + „Anuluj" widoczne, Zatwierdź/Odrzuć
        schowane (nie klikać w biegu). `total=0` → pasek nieokreślony do pierwszego progresu."""
        self.bar.setRange(0, total if total > 0 else 0); self.bar.setValue(0); self.bar.setVisible(True)
        # Wynik poprzedniej operacji nie stoi obok postępu następnej (AR-30 (5)) - do pierwszego
        # progresu pole jest puste, potem niesie „done/total · plik".
        self.result.setText("")
        self.btn_cancel.setVisible(True); self.btn_cancel.setEnabled(True)
        self.btn_commit.setVisible(False); self.btn_reject.setVisible(False)

    def update_progress(self, done, total, path):
        """Slot postępu (główny wątek): pasek done/total + nazwa bieżącego pliku w `result`."""
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        tail = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        self.result.setText(f"{done}/{total} · {tail}")

    def end_progress(self):
        """Wyjście z trybu postępu: schowaj pasek + „Anuluj". Widoczność Zatwierdź/Odrzuć/Cofnij ustawia
        wołający (set_count / set_commit_actions_visible) w post-processingu commitu."""
        self.bar.setVisible(False); self.btn_cancel.setVisible(False)
        self.btn_commit.setVisible(True); self.btn_reject.setVisible(True)

    def set_count(self, n, *, result=None, label=None):
        self._n = n
        if n > 0:
            self.dot.setText("●"); _set_role(self.dot, "warn")   # U+25CF: jest w Segoe UI, paruje z „○" (wiz F3 #2)
            # `label` rozróżnia klingę też przy n>0: „N zmian nazw oczekuje" vs domyślne „N zmian
            # oczekuje" (mikro-zmiana §0; call-sites makra bez label → domyślny tekst, R1 #8).
            self.label.setText(label or i18n.t_plural("grid.drawer.pending", n))
            if result is None:
                self.result.setText("")      # nowy staging: skasuj STALE wynik commitu/odrzucenia (wiz #7)
        else:
            self.dot.setText("○"); _set_role(self.dot, "secondary")
            # `label` nadpisuje domyślny tekst pustego stanu: po commicie „Zatwierdzono…" zamiast
            # pustostanu poczekalni (sprzeczność z wynikiem obok — wizytator D2).
            self.label.setText(label or i18n.t("grid.drawer.empty"))
        self.btn_commit.setEnabled(n > 0)
        self.btn_reject.setEnabled(n > 0)
        # Nowy staging (n>0) → Zatwierdź/Odrzuć znowu widoczne. NIE chowa tu „Cofnij" (osobny przycisk
        # FramesView) — to robi `_dismiss_undo` przy starcie stagingu (recenzent #1/#4, wiz #3).
        if n > 0:
            self.set_commit_actions_visible(True)
        if result is not None:
            self.result.setText(result)

    def set_commit_actions_visible(self, on):
        """Pokaż/ukryj Zatwierdź+Odrzuć. Po commicie chowamy je, bo jedyną sensowną akcją jest
        „Cofnij" (wizytator #5 — nie mieszać żywego Cofnij z wyszarzonym Zatwierdź/Odrzuć)."""
        self.btn_commit.setVisible(on)
        self.btn_reject.setVisible(on)

    def set_result(self, text):
        """Sam wynik operacji plikowej spoza stagingu (gesty izolacji zapisu w miejscu): postęp szedł
        przez tę szufladę, więc wynik zastępuje w niej ostatnią linię postępu. Licznika i etykiety
        poczekalni NIE rusza - gest nie zmienia stagingu, a „Zatwierdzono…" przy żywym „Cofnij"
        musi przeżyć."""
        self.result.setText(text)


class ReleaseDialog(QDialog):
    """Okno gestu „Zwolnij plik do skanu…" (`writeback.release_isolation`): skutek słowami, liczba
    kopii i POWÓD wpisany przez człowieka. Zwolnienie nie zmienia pliku i niczego nie sprawdza - to jego
    rozstrzygnięcie, że plik jest w porządku, więc bez powodu „Zwolnij" jest wygaszone, a powód
    trafia do zdarzenia `location.writeback_released`. Enter nie przejdzie obok bramki: przycisk
    domyślny jest wygaszony, a `accept` sprawdza powód drugi raz (EXPECT)."""

    def __init__(self, n, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("grid.inplace.release"))
        lay = QVBoxLayout(self)
        opis = QLabel(i18n.t_plural("grid.inplace.release_ask", n))
        opis.setWordWrap(True)
        lay.addWidget(opis)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(i18n.t("grid.inplace.release_placeholder"))
        lay.addWidget(self.edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = self.buttons.button(QDialogButtonBox.Ok)
        self.btn_ok.setText(i18n.t("grid.inplace.release_ok"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.edit.textChanged.connect(self._sync_ok)
        self._sync_ok()

    def reason(self):
        """Powód bez białych znaków na brzegach - taki idzie do dziennika."""
        return self.edit.text().strip()

    def _sync_ok(self):
        on = bool(self.reason())
        self.btn_ok.setEnabled(on)
        self.btn_ok.setToolTip("" if on else i18n.t("grid.inplace.release_need_reason"))

    def accept(self):
        if not self.reason():
            return
        super().accept()
