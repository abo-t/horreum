r"""Okno „Przypisz zestaw…" — oś SPRZĘTU wskazana ręką (R1, #DR2).

Wydzielone z `gui.app` od pierwszej linii, wzorem `assign_dialog`: to okno pyta o INNĄ oś niż
cała reszta ekranu „Przegląd obiektów" (sprzęt, nie obiekt), a jego kontrakt — „teleskop wskazuje
ręka, kamerę zna plik" — jest inwariantem DDL (`config.camera_id == frame.camera_id`), więc ma
mieszkać przy oknie, a nie u wołającego.

JEDNOSTKĄ JEST FOLDER × KAMERA (D-DR-3), nie klatka i nie folder. Zmierzone na archiwum: 425 RAW-ów
w 36 folderach (mediana 5,5 · max 100), z czego **2 foldery mają dwa korpusy** — grupa „folder"
obiecywałaby jeden gest tam, gdzie muszą powstać dwa zestawy.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from horreum import repo
from horreum.gui import i18n, queries, rows
from horreum.gui.kolko import kolko                # kółko myszy przestawia pole wyłącznie z fokusem (AR-349)

# Tryb ogniskowej (AR-128): rola wiersza niosąca słownik grupy, wartownik pozycji „Dopisz nowy…"
# w liście teleskopów i wartownik nie wybranego parku (`None` w `itemData` znaczy „nic nie
# powiedziano" - to legalna wartość parku, więc „nie wybrano" potrzebuje własnego znaku).
GROUP_ROLE = rows.ROLA_GRUPY
NEW_TELESCOPE = "__nowy__"
PARK_UNPICKED = "__wybierz__"
_PARK_KEYS = {1: "cfg.park_yes", 0: "cfg.park_no", None: "cfg.park_unsaid"}

# ---------------------------------------------------------------------------------------------
# LISTA FOLDERÓW OKIEN GESTU RĘKI - wspólne dla tego okna i `observatory_dialog` (jedna konwencja
# okien gestu ręki). Zmierzone na żywej bazie (okno stanowiska): start 333 × 589 px, widać 10 ze
# 178 folderów, ścieżka ucięta PRZED licznikiem, folder LMC to 50. wiersz - wskazanie jednego
# folderu kosztowało 9-10 interakcji. Trzy środki, każdy na inną część tego kosztu:
#  * okno startuje SZERSZE i wyższe (`default_dialog_size`), w jednostkach fontu, nie pikselach;
#  * pole FILTRA nad listą (`FolderFilter`) - wzorzec szukajki facetu „Obiekt”: chowa wiersze
#    niepasujące, czyści się natywnym „×”, Enter bierze pierwsze trafienie;
#  * elizja ŚRODKA ścieżki (`FolderRowDelegate`) - początek i KONIEC ścieżki (nazwa folderu)
#    zostają, ogon wiersza z licznikiem klatek zostaje cały.
# ---------------------------------------------------------------------------------------------

# Folder wiersza (człon elidowany środkiem). `UserRole` niesie frame_ids, `+1` - camera_id.
FOLDER_ROLE = rows.ROLA_FOLDERU_GRUPY
CAMERA_ROLE = rows.ROLA_KAMERY_GRUPY
_SIZE_CHARS = 120          # szerokość domyślna okna w średnich znakach fontu
_SIZE_LINES = 46           # wysokość domyślna w wierszach fontu
_SCREEN_FRAC = 0.85        # sufit: część dostępnego ekranu


def default_dialog_size(widget):
    """Rozmiar startowy okna gestu ręki: ~120 znaków × ~46 wierszy fontu okna, nie mniej niż
    `sizeHint` i nie więcej niż 85 % dostępnego ekranu. Jednostki fontu, bo skalują się z DPI
    i rozmiarem czcionki - stała w pikselach byłaby za mała na 4K i za duża na laptopie."""
    fm = widget.fontMetrics()
    hint = widget.sizeHint()
    w = max(fm.averageCharWidth() * _SIZE_CHARS, hint.width())
    h = max(fm.lineSpacing() * _SIZE_LINES, hint.height())
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        w = min(w, int(avail.width() * _SCREEN_FRAC))
        h = min(h, int(avail.height() * _SCREEN_FRAC))
    return QSize(w, h)


def dopasuj_wysokosc(okno):
    """Okno ROŚNIE (tylko w górę) do wysokości, której treść potrzebuje przy BIEŻĄCEJ szerokości -
    etykiety zawijają zdania (nagłówek, zdanie na żywo, status wyniku z receptą, błąd), więc ich
    wysokość zależy od szerokości (`heightForWidth`). Bez tego okno zostawało przy rozmiarze
    z otwarcia, a ostatni wiersz zdania był ucięty w pół (wizytacja natywna: etykieta 24 px przy
    potrzebnych 32; status „Napraw nagłówek…” 44 px przy 64, AR-176). JEDEN pomocnik dla okien
    wyboru obiektu, ścieżki i naprawy nagłówka - wołany po każdej zmianie tych zdań i przy
    pokazaniu okna; okno niepokazane nie ma jeszcze szerokości."""
    if not okno.isVisible():
        return
    lay = okno.layout()
    lay.activate()
    potrzeba = (lay.totalHeightForWidth(okno.width()) if lay.hasHeightForWidth()
                else lay.totalSizeHint().height())
    if potrzeba > okno.height():
        okno.resize(okno.width(), potrzeba)


def folder_hit(needle, text):
    """Czy wiersz `text` pasuje do frazy filtra? KAŻDE słowo frazy musi wystąpić w wierszu,
    wielkość liter bez znaczenia (`LMC 2024` trafia `R:\\...\\LMC\\2024-01-05`). Pusta fraza
    pasuje zawsze. Logika bez Qt - testowalna wprost."""
    hay = text.casefold()
    return all(word in hay for word in needle.casefold().split())


def elide_head_keep_tail(fm, head, tail, width):
    """`head + tail` zmieszczone w `width` px: `head` (ścieżka) traci ŚRODEK, `tail` (licznik
    klatek, rodzaje, świadek) zostaje cały. Gdy na `head` nie zostaje miejsca, wraca sam `tail` -
    dalsze ucięcie od prawej robi już delegat Qt."""
    if fm.horizontalAdvance(head + tail) <= width:
        return head + tail
    room = width - fm.horizontalAdvance(tail)
    return (fm.elidedText(head, Qt.ElideMiddle, room) if room > 0 else "") + tail


class FolderRowDelegate(QStyledItemDelegate):
    """Wiersz listy folderów z elizją ŚRODKA ścieżki. Tekst wiersza (`DisplayRole`) zostaje pełny -
    kopiuje się, testuje i trafia w tooltip bez zmian; delegat skraca wyłącznie to, co MALUJE.
    Ścieżka ucięta od prawej gubiła dokładnie to, co ją wyróżnia (ostatni człon) i licznik za nią;
    `Qt.ElideMiddle` na całym wierszu ciąłby środek WIERSZA, czyli koniec ścieżki."""

    def initStyleOption(self, opt, index):
        super().initStyleOption(opt, index)
        folder = index.data(FOLDER_ROLE)
        if not folder or not opt.text.startswith(folder) or opt.rect.width() <= 0:
            return
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        # Qt maluje tekst z marginesem `PM_FocusFrameHMargin + 1` z każdej strony.
        margin = 2 * (style.pixelMetric(QStyle.PM_FocusFrameHMargin, None, widget) + 1)
        opt.text = elide_head_keep_tail(QFontMetrics(opt.font), folder, opt.text[len(folder):],
                                        rect.width() - margin)


def folder_list(items):
    """Ustaw listę folderów okna gestu: delegat elizji środka, bez poziomego paska (inaczej Qt
    rozciąga wiersz pod pełną ścieżkę i elizja nie dochodzi do głosu)."""
    items.setItemDelegate(FolderRowDelegate(items))
    items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


def folder_item(text, folder):
    """Wiersz listy: pełny tekst, folder w `FOLDER_ROLE` (dla elizji), pełny tekst w tooltipie -
    elidowana ścieżka ma drogę powrotu."""
    it = QListWidgetItem(text)
    it.setData(FOLDER_ROLE, folder)
    it.setToolTip(text)
    return it


class FolderFilter(QLineEdit):
    """Pole filtra listy folderów - wzorzec szukajki facetu „Obiekt” (`facets.FacetRail`).

    * KONTRAKT „CO WIDAĆ, TO SIĘ ZAPISZE”: przy niepustej frazie wiersz niepasujący jest UKRYTY
      bez względu na zaznaczenie, a zapis i licznik na przycisku biorą WYŁĄCZNIE wiersze widoczne
      i zaznaczone (`visible_rows`). Lista nie chowa więc niczego, co gest zapisze. Zaznaczenie
      ukrytego wiersza ZOSTAJE (bez cichego odznaczania): wyczyszczenie frazy przywraca pełną
      listę z zaznaczeniami sprzed filtra. Wcześniejsza reguła „zaznaczony widoczny zawsze”
      unieważniała filtr w oknie zestawu, gdzie grupy startują zaznaczone - fraza nie chowała nic.
    * Widoczność zależy WYŁĄCZNIE od frazy, więc zmiana zaznaczenia jej nie rusza i nie wymaga
      przeliczenia - wystarcza `textChanged`.
    * Fraza bez trafień ma własne zdanie (`self.empty`), nie pustą listę.
    * Enter ZAZNACZA kolejne pasujące, jeszcze niezaznaczone wiersze (pierwszy Enter - pierwsze
      trafienie) i NIE przechodzi do okna: domyślny przycisk zapisałby gest w pół wyboru.
    `on_change` woła się po każdym przefiltrowaniu - okno synchronizuje przełącznik całości
    i licznik na przycisku zapisu."""

    def __init__(self, items, on_change, parent=None):
        super().__init__(parent)
        self._items = items
        self._on_change = on_change
        self.setPlaceholderText(i18n.t("handlist.filter_ph"))
        self.setToolTip(i18n.t("handlist.filter_tip"))
        self.setClearButtonEnabled(True)
        self.empty = QLabel("")
        self.empty.setWordWrap(True)
        self.empty.setVisible(False)
        self.textChanged.connect(self.apply)

    def apply(self, *_):
        needle = self.text()
        trafione = 0
        for i in range(self._items.count()):
            it = self._items.item(i)
            hit = folder_hit(needle, it.text())
            trafione += hit
            it.setHidden(not hit)
        pusto = bool(needle.strip()) and trafione == 0
        self.empty.setText(i18n.t("handlist.filter_empty", q=needle.strip()) if pusto else "")
        self.empty.setVisible(pusto)
        self._on_change()

    def check_next_hit(self):
        """Zaznacz pierwszy pasujący, niezaznaczony wiersz; zwraca jego indeks albo `None`.
        Pusta fraza nie zaznacza niczego - „nic nie wpisano" nie jest wskazaniem."""
        needle = self.text()
        if not needle.strip():
            return None
        for i in range(self._items.count()):
            it = self._items.item(i)
            if it.checkState() != Qt.Checked and folder_hit(needle, it.text()):
                it.setCheckState(Qt.Checked)
                return i
        return None

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.check_next_hit()
            ev.accept()
            return
        super().keyPressEvent(ev)


def visible_rows(items):
    """Wiersze widoczne po filtrze - zakres przełącznika całości ORAZ zapisu (bez frazy:
    wszystkie). Kontrakt w `FolderFilter`."""
    return [items.item(i) for i in range(items.count()) if not items.item(i).isHidden()]


class AssignConfigDialog(QDialog):
    """Wskazanie TELESKOPU dla grup, które o sprzęcie nie zeznają.

    Bez wolnego tekstu na nazwę teleskopu — świadomie, tak samo jak `AssignObjectDialog` nie
    pozwala wpisać dowolnego kanonu obiektu: oś teleskopu wyłania się z archiwum (`grouper`) albo
    z jawnego gestu w parku (`horreum park`), a trzecia droga tworzyłaby wiersze, których nic nie
    sprząta. Nowy teleskop powołuje się więc TAM, a to okno wybiera z istniejących.

    PARK NA GÓRZE, bo to on odpowiada na pytanie „czym dziś fotografuję" (D-0731-12) — a właśnie
    czymś z parku zrobiono RAW-a, którego nagłówek milczy. Kolejność bierzemy od jedynego
    właściciela przeglądu parku (`queries.park_overview`), nie z własnego SELECT-a.

    ZEZNANIE NAGŁÓWKA STOI PRZY GRUPIE, i to nie jest ozdoba: dla RAW-a z lustrzanki nagłówek albo
    MILCZY (zdjęcie przez teleskop — luka strukturalna formatu), albo niesie nazwę OBIEKTYWU (E3-3,
    zdjęcie przez obiektyw). Pierwsze znaczy „wskaż teleskop", drugie „automat już coś wie, ale to
    nie teleskop" — a użytkownik ma tę różnicę widzieć PRZED gestem, nie po nim.

    DWA TRYBY, JEDNO OKNO (`change`): **nadanie** (grupy z kubełka „bez zestawu") i **zmiana**
    (grupy, którym zestaw nadała już ręka). Różnią się nagłówkiem, etykietą wiersza — bo w trybie
    zmiany user musi widzieć, CO tam dziś stoi — i tym, że zapis idzie z `overwrite=True`.
    Drugiego okna nie ma świadomie: pytanie jest jedno („czym to fotografowano"), a dwie
    powierzchnie dla jednego pytania rozjeżdżają się przy pierwszej zmianie kontraktu.

    TRZECI TRYB - OGNISKOWA (`focal`, AR-128, D-1012-2 `Q8`): grupy z kubełka „ogniskowa niezgodna
    z teleskopem" (folder × kamera × ogniskowa pliku × teleskop źródłowy). Teleskop w Horreum to
    fizyczny teleskop z ogniskową, potwierdzony ręką - więc lista NIE jest całym parkiem, tylko
    teleskopami, których ogniskowa mieści się w tolerancji od ogniskowej KAŻDEJ zaznaczonej grupy
    (`queries.telescopes_near_focal`), plus pozycja „Dopisz nowy…". ODWRACA to zakaz wolnego tekstu
    z akapitu wyżej - świadomie, decyzją Zdzinia: nowy teleskop powstaje razem z przypisaniem klatek
    w jednej transakcji (`repo.user_assign_config_new_telescope`), więc wiersza bez klatek nie ma.
    Pole „w parku" startuje wartością teleskopu źródłowego zaznaczonych grup (D-1012-2 `Q11`);
    przy źródłach o różnym parku wyboru nie zgadujemy - trzeba go wskazać.

    `self.selected` = `(telescope_id, telescope_label, frame_ids)` albo `None`; przy „Dopisz nowy…"
    `telescope_id` = `None`, a `self.new_telescope` = `{name, focal_mm, f_ratio, in_park,
    source_telescope_id}`."""

    def __init__(self, con, *, groups, change=False, focal=False, parent=None):
        super().__init__(parent)
        self.con = con
        self.groups = list(groups)
        self.change = change
        self.focal = focal
        self.selected = None
        self.new_telescope = None
        self.setWindowTitle(i18n.t("cfg.title_focal" if focal else
                                   "cfg.title_change" if change else "cfg.title"))
        lay = QVBoxLayout(self)

        klatek = sum(g["n_frames"] for g in self.groups)
        head = QLabel(i18n.t("cfg.head_focal" if focal else
                             "cfg.head_change" if change else "cfg.head",
                             folders=i18n.t_plural("dlg.n_groups", len(self.groups)),
                             frames=i18n.t_plural("dlg.n_frames", klatek)))
        head.setWordWrap(True)
        lay.addWidget(head)

        # PRZEŁĄCZNIK CAŁOŚCI (firsthand Zdzinia 0808): lista wchodzi ZAZNACZONA, bo przypadkiem
        # typowym jest jedna sesja zdjęciowa = jeden teleskop na wszystko. Ale przypadek DRUGI CO
        # DO CZĘSTOŚCI — „chcę nadać jednemu folderowi" — kosztował 38 kliknięć odznaczania przy
        # 39 grupach. Odwrócenie domyślnego stanu byłoby lekiem gorszym od choroby (wtedy masowy
        # gest kosztuje 39 kliknięć), więc domyślny stan ZOSTAJE, a dochodzi droga na skróty
        # w OBIE strony. Stan pośredni (`PartiallyChecked`) jest tylko WYŚWIETLANY — klik zawsze
        # rozstrzyga w jedną stronę, bo „częściowo" nie jest poleceniem, które da się wykonać.
        self.items = QListWidget()
        folder_list(self.items)
        # Filtr NAD przełącznikiem całości: pierwszy w kolejności Tab i z fokusem na starcie -
        # okno otwiera się gotowe do wpisania fragmentu ścieżki.
        self.filter = FolderFilter(self.items, self._on_filter)
        lay.addWidget(self.filter)
        lay.addWidget(self.filter.empty)

        self.check_all = QCheckBox(i18n.t("cfg.check_all"))
        self.check_all.setTristate(True)
        self.check_all.clicked.connect(self._on_check_all)
        lay.addWidget(self.check_all)

        for g in self.groups:
            folder = g["folder"] or i18n.t("cfg.no_folder")
            kamera = g["camera_model"] or i18n.t("cfg.no_camera")
            # W trybie ZMIANY świadkiem jest to, CO DZIŚ STOI na osi (wskazanie ręki), a nie co
            # mówi nagłówek: user wraca tu właśnie po to, żeby zobaczyć własny poprzedni wybór.
            if focal:
                # dzisiejsza ogniskowa źródła stoi przy grupie - powód niezgodności widać (N21)
                swiadek = i18n.t("cfg.focal_item", focal=g["focal_mm"],
                                 telescope=g["telescope_label"] or "-",
                                 source_focal=("-" if g["source_focal"] is None
                                               else f"{g['source_focal']:g}"),
                                 park=i18n.t(_PARK_KEYS[g["source_in_park"]]))
            elif change:
                swiadek = i18n.t("cfg.now_set", telescope=g["telescope_label"] or "—")
            else:
                swiadek = (i18n.t("cfg.header_says", telescop=g["telescop"]) if g["telescop"]
                           else i18n.t("cfg.header_silent"))
            # RODZAJ ODBIEGAJĄCY OD ŚWIATŁA MÓWI SIĘ PRZED GESTEM (R1-3). Kubełek sprzętu odsiewa
            # wyłącznie dark/bias, więc siedzi w nim też np. masterflat z niezmapowanym `IMAGETYP`
            # — gest go przyjmie (oś opisuje optykę, nie rodzaj klatki) i to jest w porządku, ale
            # user ma wiedzieć, że nie patrzy na RAW-a z lustrzanki. Token surowy, dokładnie taki,
            # jak w facecie „Rodzaj" — druga warstwa nazewnicza dałaby dwa słowniki na jeden fakt.
            rodzaje = ""
            if g["other_kinds"]:
                rodzaje = i18n.t("cfg.item_kinds", kinds=", ".join(
                    i18n.t("cfg.kind_count", kind=k, n=n) for k, n in g["other_kinds"]))
            it = folder_item(
                i18n.t("cfg.item", folder=folder, camera=kamera,
                       frames=i18n.t_plural("dlg.n_frames", g["n_frames"]))
                + rodzaje + f"   [{swiadek}]", folder)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            # DWIE GRUPY WCHODZĄ ODZNACZONE, każda z innego powodu:
            #  * BEZ KAMERY — nie ma z czego złożyć zestawu (inwariant DDL §1); klinga i tak by ją
            #    pominęła, a zaznaczenie obiecywałoby zapis, którego nie będzie;
            #  * BEZ KOPII NA DYSKU — to jedyna grupa, której klucz NIE JEST FOLDEREM (bramka
            #    pakietu 3a, zarzut 3): wpadają do niej WSZYSTKIE klatki bez obecnej kopii z całego
            #    archiwum — sieroty po podmianie i klatki, których plik zniknął. Łączy je brak
            #    ścieżki, a nie wspólny sprzęt, więc domyślne zaznaczenie kazałoby jednym gestem
            #    ostemplować jednym teleskopem zbiór, o którym nikt nic nie twierdzi.
            # Oba wiersze ZOSTAJĄ widoczne — kubełek je liczy, więc lista nie ma prawa udawać,
            # że ich nie ma; user może je zaznaczyć świadomie.
            # TRYB ZMIANY wchodzi w całości ODZNACZONY — to nie kosmetyka: domyślne zaznaczenie
            # znaczyłoby „przestempluj wszystko, co kiedykolwiek wskazałeś", czyli gest naprawy
            # jednego folderu kasowałby przy okazji wszystkie pozostałe wskazania.
            slabe = g["camera_id"] is None or g["folder"] is None or change
            it.setCheckState(Qt.Unchecked if slabe else Qt.Checked)
            it.setData(Qt.UserRole, g["frame_ids"])
            it.setData(CAMERA_ROLE, g["camera_id"])
            it.setData(GROUP_ROLE, g)
            self.items.addItem(it)
        self.items.itemChanged.connect(lambda _it: self._sync_check_all())
        self._sync_check_all()
        lay.addWidget(self.items, 1)                 # przyrost wysokości okna idzie w listę

        bez_kamery = sum(g["n_frames"] for g in self.groups if g["camera_id"] is None)
        if bez_kamery:
            nota = QLabel(i18n.t("cfg.no_camera_warning",
                                 skipped=i18n.t_plural("cfg.no_camera_skipped", bez_kamery)))
            nota.setWordWrap(True)
            lay.addWidget(nota)

        lay.addWidget(QLabel(i18n.t("cfg.telescope")))
        self.combo = kolko(QComboBox())
        lay.addWidget(self.combo)
        self._focal_dotkniete = False       # user zmienił ogniskową nowego teleskopu - nie nadpisujemy
        self._parki_ostatnie = None         # zbiór parków źródeł przy ostatniej przebudowie pola parku
        self._fill_combo()
        if focal:
            lay.addWidget(self._build_new_form())
            self._on_combo_changed()

        self.error = QLabel("")
        self.error.setProperty("role", "error")     # kolor z motywu (P-C), nie sztywny hex
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.accept_btn = buttons.button(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("cfg.cancel_btn"))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.items.itemChanged.connect(lambda _it: self._sync_wyboru())
        self.combo.currentIndexChanged.connect(self._sync_accept_enabled)
        self._sync_accept_enabled()
        self.resize(default_dialog_size(self))
        self.filter.setFocus()

    def _sync_wyboru(self):
        """JEDYNY synchronizator stanu zależnego od ZBIORU zaznaczonych grup (bramka kodu N3): lista
        teleskopów w tolerancji, wartości startowe „Dopisz nowy…", licznik i dostępność przycisku.
        Wołają go WSZYSTKIE drogi zmiany zbioru - klik w wiersz, „zaznacz wszystkie" (który blokuje
        sygnały wierszy, więc `itemChanged` nie przychodzi) i filtr (zmienia zbiór widocznych)."""
        if self.focal:
            self._fill_combo()
        self._sync_accept_enabled()

    def _fill_combo(self):
        """Lista teleskopów: park na górze (`queries.park_overview`, jedyny właściciel kolejności).
        W trybie ogniskowej tylko teleskopy w tolerancji od ogniskowej KAŻDEJ zaznaczonej grupy -
        teleskop spoza niej zostawiłby klatkę w kubełku po geście - i na końcu „Dopisz nowy…".
        Filtr 5 % ma jednego właściciela: `queries.telescopes_near_focal` (N13). Wybór sprzed
        przebudowy zostaje, jeśli dalej jest na liście."""
        poprzedni = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(i18n.t("cfg.pick_telescope"), None)
        wiersze = queries.park_overview(self.con)
        if self.focal:
            ogniskowe = {g["focal_mm"] for g in self._zaznaczone_grupy()}
            pasujace = None
            for f in ogniskowe:
                ids = {r["id"] for r in queries.telescopes_near_focal(self.con, f)}
                pasujace = ids if pasujace is None else pasujace & ids
            wiersze = [r for r in wiersze if pasujace and r["id"] in pasujace]
        park = [r for r in wiersze if r["in_park"] == 1]
        reszta = [r for r in wiersze if r["in_park"] != 1]
        for r in park + reszta:
            nazwa = queries.telescope_label(r)
            if self.focal:
                nazwa += f"  · {queries.telescope_focal(r):g} mm"
            if r["in_park"] == 1:
                nazwa += f"  ({i18n.t('cfg.park_badge')})"
            self.combo.addItem(nazwa, (r["id"], queries.telescope_label(r)))
        if self.focal:
            self.combo.addItem(i18n.t("cfg.add_new"), NEW_TELESCOPE)
        idx = next((i for i in range(self.combo.count())
                    if poprzedni is not None and self.combo.itemData(i) == poprzedni), 0)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self._on_combo_changed()

    def _build_new_form(self):
        """Pola „Dopisz nowy…" (D-1012-2 `Q8`/`Q11`): nazwa, ogniskowa (start = ogniskowa pliku
        zaznaczonych grup), f/ (pusta - f/ w pliku opisuje stary teleskop), park (start = park
        teleskopu źródłowego, gdy wszystkie zaznaczone grupy mają ten sam)."""
        self.new_form = QWidget()
        form = QFormLayout(self.new_form)
        self.new_name = QLineEdit()
        self.new_focal = QLineEdit()
        self.new_f_ratio = QLineEdit()
        self.new_f_ratio.setPlaceholderText(i18n.t("cfg.new_f_ratio_hint"))
        self.new_park = kolko(QComboBox())
        form.addRow(i18n.t("cfg.new_name"), self.new_name)
        form.addRow(i18n.t("cfg.new_focal"), self.new_focal)
        form.addRow(i18n.t("cfg.new_f_ratio"), self.new_f_ratio)
        form.addRow(i18n.t("cfg.new_park"), self.new_park)
        self.new_form.setVisible(False)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.new_focal.textEdited.connect(self._on_focal_edited)
        return self.new_form

    def _on_focal_edited(self, _tekst):
        """Ogniskowa nowego teleskopu wpisana przez usera - odtąd zmiana zbioru jej nie nadpisuje (N6)."""
        self._focal_dotkniete = True

    def _zaznaczone_grupy(self):
        return [it.data(GROUP_ROLE) for it in visible_rows(self.items)
                if it.checkState() == Qt.Checked and it.data(CAMERA_ROLE) is not None]

    def _on_combo_changed(self, *_):
        """„Dopisz nowy…" wybrany → pola nowego teleskopu z wartościami startowymi zaznaczonych
        grup (N6/N7):
          * ogniskowa = najczęstsza ogniskowa pliku wśród zaznaczonych klatek, odświeżana przy
            każdej zmianie zbioru, DOPÓKI user jej nie dotknął;
          * park przebudowywany WYŁĄCZNIE, gdy zmienił się zbiór parków źródeł - legalny wybór usera
            zostaje. Przy źródłach o różnym parku pierwsza pozycja to „wybierz", którą trzeba zmienić."""
        if not self.focal or not hasattr(self, "new_form"):
            return
        nowy = self.combo.currentData() == NEW_TELESCOPE
        self.new_form.setVisible(nowy)
        grupy = self._zaznaczone_grupy()
        if not self._focal_dotkniete:
            wagi = {}
            for g in grupy:
                if g["focal_mm"] is not None:
                    wagi[g["focal_mm"]] = wagi.get(g["focal_mm"], 0) + g["n_frames"]
            self.new_focal.setText(
                str(max(sorted(wagi), key=lambda f: wagi[f])) if wagi else "")
        parki = frozenset(g["source_in_park"] for g in grupy)
        if parki == self._parki_ostatnie:
            return
        self._parki_ostatnie = parki
        self.new_park.blockSignals(True)
        self.new_park.clear()
        if len(parki) != 1:
            self.new_park.addItem(i18n.t("cfg.new_park_pick"), PARK_UNPICKED)
        for wartosc in (1, 0, None):
            self.new_park.addItem(i18n.t(_PARK_KEYS[wartosc]), wartosc)
        cel = next(iter(parki)) if len(parki) == 1 else PARK_UNPICKED
        self.new_park.setCurrentIndex(next(i for i in range(self.new_park.count())
                                           if self.new_park.itemData(i) == cel))
        self.new_park.blockSignals(False)

    def pokaz_odmowe(self, powod):
        """Klinga odmówiła po zamknięciu okna (N16) - okno wraca z polami, które user wpisał,
        i z powodem na etykiecie błędu; gospodarz woła `exec()` ponownie."""
        self.selected = None
        self.new_telescope = None
        self.error.setText(powod)

    def _on_check_all(self):
        """Klik w przełącznik całości — ustaw KAŻDY wiersz na jedno albo drugie.

        Kierunek bierzemy ze stanu przełącznika PO kliknięciu Qt (`isChecked`), a nie z liczenia
        wierszy: `setTristate` sprawia, że Qt sam cyklicznie przechodzi przez trzy stany, a my
        chcemy tylko dwóch odpowiedzi — „wszystkie" albo „żadna". Stan pośredni jest wyłącznie
        RAPORTEM (patrz `_sync_check_all`), więc gdy user kliknie w niego, sprowadzamy go do
        pełnego zaznaczenia: „częściowo" nie jest poleceniem, które da się wykonać.

        WIERSZE SŁABE ZAZNACZAMY TAK SAMO — świadomie. Grupa bez kamery i grupa bez kopii na dysku
        wchodzą odznaczone (powód przy `setCheckState`), ale to jest DOMYŚLNY stan ostrożności, nie
        zakaz: skoro user jawnie prosi „zaznacz wszystkie", odmowa akurat tym wierszom byłaby
        cichym nadpisaniem jego decyzji.

        DWIE SŁABE GRUPY KOŃCZĄ RÓŻNIE i to trzeba czytać dokładnie (bramka pakietu, zarzut 4 —
        wcześniejsze zdanie obiecywało jedno dla obu): **bez kamery** zapis POMIJA (`_zaznaczone`
        odsiewa po `camera_id`, bo bez niej nie ma z czego złożyć configu — inwariant DDL §1);
        **bez kopii na dysku** zapis PRZECHODZI i tak ma być, bo brak pliku nie unieważnia wiedzy
        o sprzęcie. Licznik na przycisku mówi prawdę o obu, bo liczy dokładnie to, co pójdzie
        do klingi.

        ZAKRES = WIERSZE WIDOCZNE PO FILTRZE (`visible_rows`). Bez frazy to cała lista, czyli
        zachowanie sprzed filtra; z frazą „zaznacz wszystkie" znaczy „wszystkie, które widzę" -
        ukryty wiersz zaznaczony w ciemno zapisałby gest, którego user nie oglądał."""
        stan = Qt.Checked if self.check_all.checkState() != Qt.Unchecked else Qt.Unchecked
        self.items.blockSignals(True)                # jeden przebieg synchronizacji, nie N
        for it in visible_rows(self.items):
            it.setCheckState(stan)
        self.items.blockSignals(False)
        self._sync_check_all()
        self._sync_wyboru()                          # sygnały wierszy były zablokowane (N3)

    def _sync_check_all(self):
        """Przełącznik CAŁOŚCI odbija stan listy: wszystkie / żadna / częściowo.

        Sygnały blokujemy, bo `setCheckState` nie budzi wprawdzie `clicked` (ten leci wyłącznie
        z interakcji człowieka), ale budzi `stateChanged` — a blokada trzyma tę funkcję
        jednokierunkową (lista → przełącznik) i zamyka drogę do pętli zwrotnej. Liczy wiersze
        WIDOCZNE po filtrze - ten sam zakres, na którym działa klik (`_on_check_all`)."""
        widoczne = visible_rows(self.items)
        n = len(widoczne)
        zazn = sum(1 for it in widoczne if it.checkState() == Qt.Checked)
        self.check_all.blockSignals(True)
        self.check_all.setCheckState(
            Qt.Checked if zazn == n and n else Qt.Unchecked if zazn == 0 else Qt.PartiallyChecked)
        self.check_all.blockSignals(False)

    def _on_filter(self):
        """Fraza filtra zmieniła zakres widocznych wierszy - a z nim zakres zapisu, licznik i (tryb
        ogniskowej) listę teleskopów w tolerancji (N3)."""
        self._sync_check_all()
        self._sync_wyboru()

    def _zaznaczone(self):
        """Klatki z zaznaczonych grup — POMIJAJĄC grupy bez kamery (klinga i tak je odmówi).

        Liczba na przycisku ma mówić, ile klatek gest REALNIE ruszy, a nie ile ich jest w liście
        (ta sama lekcja, co `frame_count = namable` w oknie przypisania obiektu). Liczą się
        wyłącznie wiersze WIDOCZNE po filtrze - „co widać, to się zapisze” (`FolderFilter`)."""
        out = []
        for it in visible_rows(self.items):
            if it.checkState() == Qt.Checked and it.data(CAMERA_ROLE) is not None:
                out.extend(it.data(Qt.UserRole))
        return out

    def _sync_accept_enabled(self):
        """Akcja wymaga DWÓCH jawnych rzeczy: celu i teleskopu. Etykieta niesie liczbę klatek."""
        ids = self._zaznaczone()
        self.accept_btn.setText(i18n.t("cfg.assign_btn", n=len(ids)))
        self.accept_btn.setEnabled(bool(ids) and self.combo.currentData() is not None)

    def _validate_and_accept(self):
        ids = self._zaznaczone()
        if not ids:
            self.error.setText(i18n.t("cfg.err_nothing"))
            return
        wybor = self.combo.currentData()
        if wybor is None:
            self.error.setText(i18n.t("cfg.err_no_telescope"))
            return
        if wybor == NEW_TELESCOPE:
            nowy = self._new_telescope_spec()
            if nowy is None:
                return
            self.new_telescope = nowy
            self.selected = (None, nowy["name"], ids)
            self.accept()
            return
        if self.focal:
            # PONOWNA WERYFIKACJA na BIEŻĄCYM zbiorze (N3): lista mogła nie nadążyć za zmianą
            # zaznaczenia; zapis poza tolerancją przypiąłby klatki na stałe do złej ogniskowej.
            wiersz = next((r for r in queries.park_overview(self.con) if r["id"] == wybor[0]), None)
            odstajaca = self._grupa_poza_tolerancja(
                None if wiersz is None else queries.telescope_focal(wiersz))
            if odstajaca is not None:
                self.error.setText(odstajaca)
                return
        self.selected = (wybor[0], wybor[1], ids)
        self.accept()

    def _grupa_poza_tolerancja(self, ogniskowa):
        """Zdanie o PIERWSZEJ zaznaczonej grupie, której ogniskowa pliku nie mieści się w tolerancji
        od `ogniskowa` (teleskopu z listy albo nowego) - albo `None`. Ta sama reguła co lista
        (`queries.within_tolerance`) i predykat kubełka (N3/N6)."""
        for g in self._zaznaczone_grupy():
            if not queries.within_tolerance(g["focal_mm"], ogniskowa):
                return i18n.t("cfg.err_group_focal", folder=g["folder"] or i18n.t("cfg.no_folder"),
                              focal=g["focal_mm"],
                              telescope="-" if ogniskowa is None else f"{ogniskowa:g}")
        return None

    def _new_telescope_spec(self):
        """Pola „Dopisz nowy…" → słownik dla klingi albo `None` z powodem na etykiecie błędu.
        Walidacja to TE SAME funkcje, których użyje klinga (`repo.valid_telescope_*`) - okno nie ma
        własnej kopii zakresów; tu tylko wcześniej mówi, co klinga i tak by odrzuciła."""
        def liczba(pole):
            tekst = pole.text().strip().replace(",", ".")
            if not tekst:
                return None
            try:
                return float(tekst)
            except ValueError:
                raise ValueError(i18n.t("axis.tel.optics_not_number", text=tekst)) from None
        try:
            nazwa = repo.valid_telescope_name(self.con, self.new_name.text())
            ogn = liczba(self.new_focal)
            if ogn is None:
                raise ValueError(i18n.t("cfg.err_new_focal"))
            ogn = repo.valid_telescope_focal(ogn)
            f = liczba(self.new_f_ratio)
            f = None if f is None else repo.valid_telescope_f_ratio(f)
            park = self.new_park.currentData()
            if park == PARK_UNPICKED:
                raise ValueError(i18n.t("cfg.err_new_park"))
            odstajaca = self._grupa_poza_tolerancja(ogn)       # ta sama bramka co lista (N6)
            if odstajaca is not None:
                raise ValueError(odstajaca)
        except ValueError as e:
            self.error.setText(str(e))
            return None
        zrodla = {g["source_id"] for g in self._zaznaczone_grupy()}
        return {"name": nazwa, "focal_mm": ogn, "f_ratio": f, "in_park": park,
                "source_telescope_id": next(iter(zrodla)) if len(zrodla) == 1 else None}
