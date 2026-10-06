r"""Okno „Wskaż stanowisko…" - oś OBSERWATORIUM wskazana ręką (0027).

Bliźniak `config_dialog` w konwencji (lista grup z przełącznikiem całości, licznik na przycisku,
błąd w oknie, `self.selected` po akceptacji) - jedna konwencja okien gestu ręki. Różnice są
domenowe, nie kosmetyczne:

* JEDNOSTKĄ JEST FOLDER, nie folder × kamera: stanowisko nie zależy od korpusu, a sesja zdjęciowa
  leży w jednym folderze (LMC: 36 DNG w jednym katalogu).
* LISTA WCHODZI ODZNACZONA w każdym trybie. Kubełek „bez stanowiska" to archiwum z wielu miejsc
  (RAW-y z wyjazdów, kalibracja sprzed GPS) - domyślne zaznaczenie stemplowałoby jednym miejscem
  całość. Przy zestawie domyślne „wszystko" ma sens (jedna sesja = jeden teleskop), tu nie.
* CEL ma dwie drogi: istniejące stanowisko z listy ALBO nowe ze współrzędnych. Współrzędne waliduje
  ta sama reguła co klinga (`resolve.observatory.user_site_coords`), więc odmowa w oknie i odmowa
  klingi nie mogą się rozjechać. Punkt w promieniu `THRESH_KM` od istniejącego trafia W NIE (klinga).
* TRZY TRYBY, jedno okno: `assign` (klatki bez stanowiska), `change` (wskazane ręką - zapis
  z `overwrite=True`), `clear` (wskazane ręką - cofnięcie, bez wyboru celu).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QListWidget, QRadioButton, QVBoxLayout,
)

from horreum.gui import i18n, queries
from horreum.gui.config_dialog import (
    FolderFilter, default_dialog_size, folder_item, folder_list, visible_rows,
)
from horreum.resolve.observatory import THRESH_KM, user_site_coords

MODES = ("assign", "change", "clear")


def _liczba(tekst):
    """Pole tekstowe → wartość dla walidatora: pusty napis = brak, przecinek dziesiętny = kropka
    (klawiatura PL). Sama konwersja zostaje walidatorowi - jedna reguła, jeden komunikat."""
    t = tekst.strip().replace(",", ".")
    return t or None


class AssignObservatoryDialog(QDialog):
    """Wskazanie STANOWISKA dla grup folderów (albo cofnięcie wskazania).

    `self.selected` po akceptacji = `{"frame_ids": [...], "observatory_id": id | None, "lat": …,
    "lon": …, "name": …, "elev": …, "label": etykieta celu do komunikatu}`; w trybie `clear` tylko
    `frame_ids`. `None` = anulowano."""

    def __init__(self, con, *, groups, mode="assign", parent=None):
        super().__init__(parent)
        if mode not in MODES:
            raise ValueError(f"tryb {mode!r} spoza {MODES}")
        self.con = con
        self.groups = list(groups)
        self.mode = mode
        self.selected = None
        tytul = {"assign": "obshand.title", "change": "obshand.title_change",
                 "clear": "obshand.title_clear"}[mode]
        naglowek = {"assign": "obshand.head", "change": "obshand.head_change",
                    "clear": "obshand.head_clear"}[mode]
        self.setWindowTitle(i18n.t(tytul))
        lay = QVBoxLayout(self)

        head = QLabel(i18n.t(naglowek,
                             folders=i18n.t_plural("dlg.n_folders", len(self.groups)),
                             frames=i18n.t_plural("dlg.n_frames",
                                                  sum(g["n_frames"] for g in self.groups))))
        head.setWordWrap(True)
        lay.addWidget(head)

        # Lista folderów wspólna z oknem zestawu (`config_dialog`): filtr nad listą z fokusem na
        # starcie, elizja środka ścieżki, okno szersze. Zmierzone przed: 10 ze 178 folderów
        # w kadrze, LMC na 50. wierszu, 9-10 interakcji do wskazania folderu.
        self.items = QListWidget()
        folder_list(self.items)
        self.filter = FolderFilter(self.items, self._on_filter)
        lay.addWidget(self.filter)
        lay.addWidget(self.filter.empty)

        self.check_all = QCheckBox(i18n.t("obshand.check_all"))
        self.check_all.setTristate(True)
        self.check_all.clicked.connect(self._on_check_all)
        lay.addWidget(self.check_all)

        for g in self.groups:
            folder = g["folder"] or i18n.t("obshand.no_folder")
            rodzaje = ", ".join(i18n.t("obshand.kind_count", kind=k, n=n) for k, n in g["kinds"])
            tekst = i18n.t("obshand.item", folder=folder,
                           frames=i18n.t_plural("dlg.n_frames", g["n_frames"]), kinds=rodzaje)
            if mode != "assign":           # świadek zmiany: CO DZIŚ STOI (własny poprzedni wybór)
                swiadek = (i18n.t("obshand.now_set", site=g["observatory_label"])
                           if g["observatory_label"] else i18n.t("obshand.now_mixed"))
                tekst += f"   [{swiadek}]"
            it = folder_item(tekst, folder)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, g["frame_ids"])
            self.items.addItem(it)
        self.items.itemChanged.connect(lambda _it: self._sync_check_all())
        self._sync_check_all()
        lay.addWidget(self.items, 1)                 # przyrost wysokości okna idzie w listę

        self.combo = None
        if mode != "clear":
            self._build_target(lay)

        self.error = QLabel("")
        self.error.setProperty("role", "error")     # kolor z motywu, nie sztywny hex
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.accept_btn = buttons.button(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("obshand.cancel_btn"))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.items.itemChanged.connect(self._sync_accept_enabled)
        self._sync_accept_enabled()
        self.resize(default_dialog_size(self))
        self.filter.setFocus()

    def _build_target(self, lay):
        """Cel gestu: istniejące stanowisko ALBO nowe ze współrzędnych - przełącznik radiowy, bo to
        DWA RÓŻNE twierdzenia („to jest TO miejsce" vs „to jest TU"), nie dwa pola jednego."""
        self.radio_existing = QRadioButton(i18n.t("obshand.pick_existing"))
        self.radio_new = QRadioButton(i18n.t("obshand.pick_new"))
        grupa = QButtonGroup(self)
        grupa.addButton(self.radio_existing)
        grupa.addButton(self.radio_new)
        lay.addWidget(self.radio_existing)
        self.combo = QComboBox()
        self.combo.addItem(i18n.t("obshand.pick_site"), None)
        for o in queries.active_observatories(self.con):
            etykieta = o["name"] or f'{o["lat"]:.4f}, {o["lon"]:.4f}'
            self.combo.addItem(f'#{o["id"]}  {etykieta}', (o["id"], etykieta))
        lay.addWidget(self.combo)
        lay.addWidget(self.radio_new)
        form = QFormLayout()
        self.lat = QLineEdit()
        self.lon = QLineEdit()
        self.name = QLineEdit()
        self.elev = QLineEdit()
        form.addRow(i18n.t("obshand.lat"), self.lat)
        form.addRow(i18n.t("obshand.lon"), self.lon)
        form.addRow(i18n.t("obshand.name"), self.name)
        form.addRow(i18n.t("obshand.elev"), self.elev)
        lay.addLayout(form)
        nota = QLabel(i18n.t("obshand.near_note", km=f"{THRESH_KM:g}"))
        nota.setWordWrap(True)
        lay.addWidget(nota)
        # Lista pusta (świeża oś) - jedyną drogą są współrzędne, więc to ona startuje wybrana.
        (self.radio_existing if self.combo.count() > 1 else self.radio_new).setChecked(True)
        self.radio_existing.setEnabled(self.combo.count() > 1)
        # Dotknięcie pola przełącza tryb - user nie ma szukać radia, żeby wpisać liczbę.
        self.combo.activated.connect(lambda _i: self.radio_existing.setChecked(True))
        for pole in (self.lat, self.lon, self.name, self.elev):
            pole.textEdited.connect(lambda _t: self.radio_new.setChecked(True))
            pole.textEdited.connect(lambda _t: self.error.setText(""))
        for sygnal in (self.combo.currentIndexChanged, self.radio_new.toggled,
                       self.lat.textChanged, self.lon.textChanged):
            sygnal.connect(lambda *_a: self._sync_accept_enabled())

    def _on_check_all(self):
        """Klik w przełącznik całości - każdy wiersz na jedno albo drugie (stan pośredni to raport,
        nie polecenie; ta sama reguła co w `AssignConfigDialog._on_check_all`). Zakres = wiersze
        widoczne po filtrze, jak tam."""
        stan = Qt.Checked if self.check_all.checkState() != Qt.Unchecked else Qt.Unchecked
        self.items.blockSignals(True)
        for it in visible_rows(self.items):
            it.setCheckState(stan)
        self.items.blockSignals(False)
        self._sync_check_all()
        self._sync_accept_enabled()

    def _sync_check_all(self):
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
        """Klatki z zaznaczonych wierszy WIDOCZNYCH po filtrze - „co widać, to się zapisze”
        (kontrakt w `config_dialog.FolderFilter`)."""
        out = []
        for it in visible_rows(self.items):
            if it.checkState() == Qt.Checked:
                out.extend(it.data(Qt.UserRole))
        return out

    def _cel_gotowy(self):
        """Czy cel jest WSKAZANY (nie: poprawny - poprawność mówi walidator przy akceptacji, z powodem)."""
        if self.combo is None:
            return True
        if self.radio_existing.isChecked():
            return self.combo.currentData() is not None
        return bool(self.lat.text().strip() and self.lon.text().strip())

    def _sync_accept_enabled(self):
        ids = self._zaznaczone()
        klucz = "obshand.clear_btn" if self.mode == "clear" else "obshand.assign_btn"
        self.accept_btn.setText(i18n.t(klucz, n=len(ids)))
        self.accept_btn.setEnabled(bool(ids) and self._cel_gotowy())

    def _validate_and_accept(self):
        ids = self._zaznaczone()
        if not ids:
            self.error.setText(i18n.t("obshand.err_nothing"))
            return
        if self.mode == "clear":
            self.selected = {"frame_ids": ids}
            self.accept()
            return
        if self.radio_existing.isChecked():
            wybor = self.combo.currentData()
            if wybor is None:
                self.error.setText(i18n.t("obshand.err_no_site"))
                return
            self.selected = {"frame_ids": ids, "observatory_id": wybor[0], "lat": None,
                             "lon": None, "name": None, "elev": None, "label": wybor[1]}
            self.accept()
            return
        try:
            la, lo, el = user_site_coords(_liczba(self.lat.text()), _liczba(self.lon.text()),
                                          _liczba(self.elev.text()))
        except ValueError as e:
            self.error.setText(i18n.t("obshand.err_coords", e=e))
            return
        nazwa = self.name.text().strip() or None
        self.selected = {"frame_ids": ids, "observatory_id": None, "lat": la, "lon": lo,
                         "name": nazwa, "elev": el, "label": nazwa or f"{la:.4f}, {lo:.4f}"}
        self.accept()
