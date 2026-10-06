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
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from horreum.gui import i18n, queries

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
FOLDER_ROLE = Qt.UserRole + 10
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

    `self.selected` = `(telescope_id, telescope_label, frame_ids)` albo `None`."""

    def __init__(self, con, *, groups, change=False, parent=None):
        super().__init__(parent)
        self.con = con
        self.groups = list(groups)
        self.change = change
        self.selected = None
        self.setWindowTitle(i18n.t("cfg.title_change" if change else "cfg.title"))
        lay = QVBoxLayout(self)

        klatek = sum(g["n_frames"] for g in self.groups)
        head = QLabel(i18n.t("cfg.head_change" if change else "cfg.head",
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
            if change:
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
            it.setData(Qt.UserRole + 1, g["camera_id"])
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
        self.combo = QComboBox()
        self.combo.addItem(i18n.t("cfg.pick_telescope"), None)
        park = [r for r in queries.park_overview(con) if r["in_park"] == 1]
        reszta = [r for r in queries.park_overview(con) if r["in_park"] != 1]
        for r in park + reszta:
            nazwa = queries.telescope_label(r)
            if r["in_park"] == 1:
                nazwa += f"  ({i18n.t('cfg.park_badge')})"
            self.combo.addItem(nazwa, (r["id"], queries.telescope_label(r)))
        lay.addWidget(self.combo)

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
        self.items.itemChanged.connect(self._sync_accept_enabled)
        self.combo.currentIndexChanged.connect(self._sync_accept_enabled)
        self._sync_accept_enabled()
        self.resize(default_dialog_size(self))
        self.filter.setFocus()

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
        self._sync_accept_enabled()

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
        """Fraza filtra zmieniła zakres widocznych wierszy - a z nim zakres zapisu i licznik."""
        self._sync_check_all()
        self._sync_accept_enabled()

    def _zaznaczone(self):
        """Klatki z zaznaczonych grup — POMIJAJĄC grupy bez kamery (klinga i tak je odmówi).

        Liczba na przycisku ma mówić, ile klatek gest REALNIE ruszy, a nie ile ich jest w liście
        (ta sama lekcja, co `frame_count = namable` w oknie przypisania obiektu). Liczą się
        wyłącznie wiersze WIDOCZNE po filtrze - „co widać, to się zapisze” (`FolderFilter`)."""
        out = []
        for it in visible_rows(self.items):
            if it.checkState() == Qt.Checked and it.data(Qt.UserRole + 1) is not None:
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
        self.selected = (wybor[0], wybor[1], ids)
        self.accept()
