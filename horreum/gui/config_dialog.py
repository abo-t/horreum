r"""Okno „Przypisz zestaw…" — oś SPRZĘTU wskazana ręką (R1, #DR2).

Wydzielone z `gui.app` od pierwszej linii, wzorem `assign_dialog`: to okno pyta o INNĄ oś niż
cała reszta ekranu „Przegląd obiektów" (sprzęt, nie obiekt), a jego kontrakt — „teleskop wskazuje
ręka, kamerę zna plik" — jest inwariantem DDL (`config.camera_id == frame.camera_id`), więc ma
mieszkać przy oknie, a nie u wołającego.

JEDNOSTKĄ JEST FOLDER × KAMERA (D-DR-3), nie klatka i nie folder. Zmierzone na archiwum: 425 RAW-ów
w 36 folderach (mediana 5,5 · max 100), z czego **2 foldery mają dwa korpusy** — grupa „folder"
obiecywałaby jeden gest tam, gdzie muszą powstać dwa zestawy.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
)

from horreum.gui import i18n, queries


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

    `self.selected` = `(telescope_id, telescope_label, frame_ids)` albo `None`."""

    def __init__(self, con, *, groups, parent=None):
        super().__init__(parent)
        self.con = con
        self.groups = list(groups)
        self.selected = None
        self.setWindowTitle(i18n.t("cfg.title"))
        lay = QVBoxLayout(self)

        klatek = sum(g["n_frames"] for g in self.groups)
        head = QLabel(i18n.t("cfg.head", folders=len(self.groups), frames=klatek))
        head.setWordWrap(True)
        lay.addWidget(head)

        self.items = QListWidget()
        for g in self.groups:
            folder = g["folder"] or i18n.t("cfg.no_folder")
            kamera = g["camera_model"] or i18n.t("cfg.no_camera")
            swiadek = (i18n.t("cfg.header_says", telescop=g["telescop"]) if g["telescop"]
                       else i18n.t("cfg.header_silent"))
            it = QListWidgetItem(
                i18n.t("cfg.item", folder=folder, camera=kamera, n=g["n_frames"]) + f"   [{swiadek}]")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            # Grupa BEZ KAMERY nie ma z czego złożyć zestawu (inwariant DDL §1), więc wchodzi
            # ODZNACZONA: klinga i tak by ją pominęła, a zaznaczenie obiecywałoby zapis, którego
            # nie będzie. Wiersz zostaje widoczny — kubełek ją liczy, więc lista nie ma prawa
            # udawać, że jej nie ma.
            it.setCheckState(Qt.Unchecked if g["camera_id"] is None else Qt.Checked)
            it.setData(Qt.UserRole, g["frame_ids"])
            it.setData(Qt.UserRole + 1, g["camera_id"])
            self.items.addItem(it)
        lay.addWidget(self.items)

        bez_kamery = sum(g["n_frames"] for g in self.groups if g["camera_id"] is None)
        if bez_kamery:
            nota = QLabel(i18n.t("cfg.no_camera_warning", n=bez_kamery))
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

    def _zaznaczone(self):
        """Klatki z zaznaczonych grup — POMIJAJĄC grupy bez kamery (klinga i tak je odmówi).

        Liczba na przycisku ma mówić, ile klatek gest REALNIE ruszy, a nie ile ich jest w liście
        (ta sama lekcja, co `frame_count = namable` w oknie przypisania obiektu)."""
        out = []
        for i in range(self.items.count()):
            it = self.items.item(i)
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
