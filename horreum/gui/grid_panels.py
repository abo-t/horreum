"""Panele klingi widoku „Klatki" - filtr, pola, makro, rename i etykieta z elizją.

`FilterPanel` (builder drzewa filtra), `FieldsPanel` (lista keywordów), `MacroBar` i `RenameBar`
(klingi otwierane z paska zbioru w `_PanelStack`) z edytorem szablonu nazwy, `ElidedLabel`. Warstwa
widżetów; logika filtra, makra i nazw siedzi w Qt-wolnych `filter_engine`, `macro`, `naming`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from horreum import naming
from horreum.gui import i18n, rows
from horreum.gui.facets import RAIL_MIN_W as _FIELDS_MIN_W
from horreum.gui.rows import TwoPartDelegate
from horreum.resolve.headers import FAKTY_NOWSZE, copy_facts_state
from horreum.gui.grid_model import (
    _FLAGI_OBRAZOW, _half_away, _klucz_spec, _NO_VALUE, OPERATORS, _PRESET_LABELS, PRESETS, _set_role,
)


class FilterPanel(QWidget):
    """Minimalny builder drzewa filtra: wiersze [keyword][operator][wartość][×] + selektor AND/OR
    + checkbox „Odwróć" (F1 redesignu: owija drzewo w NOT — `uniwersum − wynik`).
    Emituje `filterApplied(dict|None)` — GUI v1 buduje jednopoziomową grupę (rdzeń wspiera głębiej)."""

    filterApplied = Signal(object)

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        self._rows = []
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.combo_op = QComboBox(); self.combo_op.addItems(["AND", "OR"])
        top.addWidget(QLabel(i18n.t("grid.filter.join"))); top.addWidget(self.combo_op)
        btn_add = QPushButton(i18n.t("grid.filter.add_cond")); btn_add.clicked.connect(self.add_row); top.addWidget(btn_add)
        self.chk_invert = QCheckBox(i18n.t("grid.filter.invert"))
        top.addWidget(self.chk_invert)
        btn_apply = QPushButton(i18n.t("grid.filter.apply")); btn_apply.clicked.connect(self._apply); top.addWidget(btn_apply)
        btn_clear = QPushButton(i18n.t("grid.filter.clear")); btn_clear.clicked.connect(self._clear); top.addWidget(btn_clear)
        top.addStretch(1)
        outer.addLayout(top)
        self._rows_box = QVBoxLayout(); outer.addLayout(self._rows_box)
        self.add_row()   # jeden pusty wiersz domyślnie — pierwszy filtr bez „+ warunek" (P3-4)

    def add_row(self):
        rw = QHBoxLayout()
        kw = QComboBox(); kw.setEditable(True); kw.addItems(self._keywords)
        op = QComboBox()
        for label, _ in OPERATORS:
            op.addItem(i18n.t(label))
        val = QLineEdit()
        val.returnPressed.connect(self._apply)   # Enter w polu wartości = Zastosuj (P3-4)
        rm = QPushButton("×"); rm.setFixedWidth(28)
        rw.addWidget(kw, 2); rw.addWidget(op, 1); rw.addWidget(val, 2); rw.addWidget(rm)
        holder = QWidget(); holder.setLayout(rw)
        self._rows_box.addWidget(holder)
        entry = {"kw": kw, "op": op, "val": val, "holder": holder}
        rm.clicked.connect(lambda: self._remove(entry))
        self._rows.append(entry)

    def set_keywords(self, keywords):
        """Odśwież listę keywordów we WSZYSTKICH combo, także w wierszach już zbudowanych — inaczej wiersz
        domyślny (dodany w `__init__`, zanim `_load_facets` pozna keywordy) zostaje z pustą listą i klik nie
        rozwija pola do wyboru. Editable → zachowaj wpisany tekst. Bliźniacze do `MacroBar.set_keywords`."""
        self._keywords = list(keywords)
        for e in self._rows:
            combo = e["kw"]
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear(); combo.addItems(self._keywords); combo.setCurrentText(cur)
            combo.blockSignals(False)

    def _remove(self, entry):
        entry["holder"].setParent(None)
        self._rows.remove(entry)

    def _clear(self):
        for e in list(self._rows):
            self._remove(e)
        self.chk_invert.setChecked(False)   # „Wyczyść" = pełny reset, także negacji
        self.add_row()   # zostaw pusty wiersz gotowy do następnego filtra
        self.filterApplied.emit(None)

    def set_tree(self, tree):
        """Odtwarza wiersze panelu z drzewa JEDNOPOZIOMOWEGO — synchronizuje panel z filtrem perspektywy
        (P3-3: bez tego preset ustawia filtr, a panel jest pusty → kolejny „Zastosuj" po cichu go nadpisuje).
        Korzeń NOT (F1, R#1 BLOKUJĄCE): zaznacz „Odwróć" i odtwórz DZIECKO płaską logiką — bez tego
        perspektywa z NOT wczytuje się w pusty panel i pierwszy „Zastosuj" po cichu kasuje negację.
        Głębsze zagnieżdżenie (grupa w grupie) niereprezentowalne w płaskim panelu → pusty wiersz. NIE emituje
        `filterApplied` (wołający już odświeża)."""
        for e in list(self._rows):
            self._remove(e)
        invert = (isinstance(tree, dict) and "operator" not in tree
                  and str(tree.get("op", "")).upper() == "NOT")
        self.chk_invert.setChecked(invert)
        if invert:
            children = tree.get("conditions", [])
            tree = children[0] if len(children) == 1 else None   # ≠1 dziecko: defensywnie pusty panel
        if tree is None:
            self.add_row()
            return
        if "operator" in tree:                     # pojedynczy warunek
            op_group, conds = "AND", [tree]
        else:
            op_group = str(tree.get("op", "AND")).upper()
            conds = tree.get("conditions", [])
        self.combo_op.setCurrentText(op_group if op_group in ("AND", "OR") else "AND")
        if not conds or not all("operator" in c for c in conds):
            self.add_row()                         # niereprezentowalne → nie udawaj, że oddajemy filtr
            return
        for c in conds:
            self.add_row()
            e = self._rows[-1]
            e["kw"].setCurrentText(c["keyword"])
            for i, (_, opc) in enumerate(OPERATORS):
                if opc == c["operator"]:
                    e["op"].setCurrentIndex(i)
                    break
            if "value" in c:
                e["val"].setText(str(c["value"]))

    def build_tree(self):
        conds = []
        for e in self._rows:
            kw = e["kw"].currentText().strip()
            if not kw:
                continue
            op = OPERATORS[e["op"].currentIndex()][1]
            if op in _NO_VALUE:
                conds.append({"keyword": kw, "operator": op})
                continue
            val = e["val"].text()
            if val.strip() == "":
                continue   # wiersz niedokończony (edytowalne combo auto-wybiera keyword) — NIE wstrzykuj `eq ''`
            conds.append({"keyword": kw, "operator": op, "value": val})
        if not conds:
            return None   # pusty panel = uniwersum, BEZ owijania w NOT (checkbox bez warunków nie kłamie ∅-em)
        tree = {"op": self.combo_op.currentText(), "conditions": conds}
        if self.chk_invert.isChecked():
            return {"op": "NOT", "conditions": [tree]}
        return tree

    def _apply(self):
        self.filterApplied.emit(self.build_tree())


class FieldsPanel(QWidget):
    """Panel Pól: checkbox kolumny-keyworda + pokrycie inline (ile klatek ma daną kartę). Emituje
    `columnsChanged(list[str])`. Integruje wybór kolumn i pokrycie w JEDNYM panelu (bez modalu Pokrycie).

    Pokrycie idzie w PRAWĄ kolumnę (`rows.TwoPartDelegate`): przy 1200 px splitter 1:4 skąpi lewej
    stronie i liczniki doklejone do keyworda były ucięte (wiz F3 #4). Minimum szerokości jak listwa
    facetów — obie części lewej kolumny mają ten sam próg czytelności."""

    columnsChanged = Signal(object)
    # Kolumna BAZOWA „Obrazy" też ma swój przełącznik - jedyna, której widoczność zależy od
    # perspektywy (`FramesView._uloz_kolumny`). `clicked`, nie `toggled`: emituje wyłącznie ręka,
    # więc odbicie stanu perspektywy (`set_images_checked`) nie udaje wyboru człowieka.
    imagesToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(i18n.t("grid.fields.title"))
        outer.addWidget(self.title)
        self.images = QCheckBox(i18n.t("grid.fields.images", col=i18n.t("grid.col.images")))
        # Nazwy perspektyw z tej samej tabeli, która o widoczności decyduje - zmiana składu albo
        # etykiety przenosi się do podpowiedzi sama.
        self.images.setToolTip(i18n.t("grid.fields.images_tip", perspectives=", ".join(
            i18n.t(_PRESET_LABELS[nazwa]) for nazwa, spec in PRESETS.items()
            if any(spec.get(_klucz_spec(atrybut)) for atrybut in _FLAGI_OBRAZOW))))
        self.images.clicked.connect(self.imagesToggled)
        outer.addWidget(self.images)
        self.list = QListWidget()
        self.list.setItemDelegate(TwoPartDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemChanged.connect(self._on_changed)
        outer.addWidget(self.list)
        self.setMinimumWidth(_FIELDS_MIN_W)
        self._loading = False

    def load(self, facets, checked):
        """facets: wiersze (keyword, n). checked: set[str] zaznaczonych."""
        self._loading = True
        try:
            self.list.clear()
            for f in facets:
                kw, n = f["keyword"], f["n"]
                it = QListWidgetItem(kw)
                it.setData(rows.SECONDARY, f"({n})")     # pokrycie w prawej kolumnie (wiz F3 #4)
                it.setData(Qt.UserRole, kw)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if kw in checked else Qt.Unchecked)
                self.list.addItem(it)
        finally:
            self._loading = False

    def set_stan(self, stan):
        """Stan pokrycia w TYTULE panelu: None = aktualne, "liczy" = liczone w tle, "blad" = nie
        policzone. Lista pod tytułem zostaje z poprzedniego wyniku - czyszczenie jej na czas
        liczenia pokazywałoby pustkę, która wygląda jak archiwum bez pól."""
        if stan == "liczy":
            self.title.setText(i18n.t("grid.fields.title_counting"))
        elif stan == "blad":
            self.title.setText(i18n.t("grid.fields.title_failed"))
        else:
            self.title.setText(i18n.t("grid.fields.title"))

    def set_images_checked(self, on):
        """Odbij widoczność kolumny „Obrazy" - `setChecked` nie emituje `clicked`."""
        self.images.setChecked(bool(on))

    def checked_keywords(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _on_changed(self, _item):
        if not self._loading:
            self.columnsChanged.emit(self.checked_keywords())


def zdanie_kopii_bez_zeznania(kandydaci, *, dest):
    """Podpowiedź kopii bez zeznania - Porządki (wiersze „?” i „N+”) i pusty stan perspektywy kopii
    w Zbiorach mówią TO SAMO zdanie (jeden właściciel). `kandydaci` = wiersze
    `scan.copy_facts_candidates(..., porownywalne=True)`. Kopie z faktami reguły NOWSZEJ niż ta
    binarka (AR-33) też są w liczbie, ale Dostawa tej wersji ich nie uzupełni - zdanie mówi to
    osobno, zamiast obiecywać odpowiedź po Dostawie (AR-50 (3))."""
    zdanie = i18n.t_plural("tasks.copies_unread_tip", len(kandydaci),
                           place=i18n.t("nav.dostawa"), stacks=i18n.t("pipeline.btn.stacks"),
                           check=i18n.t("pipeline.btn.presence"),
                           mark=i18n.t("pipeline.btn.mark_vanished"), dest=dest)
    nowsze = sum(copy_facts_state(r["hdr_hash"], r["hdr_rule"]) == FAKTY_NOWSZE for r in kandydaci)
    if nowsze:
        zdanie += "\n" + i18n.t_plural("tasks.copies_newer_rule_tip", nowsze)
    return zdanie


class MacroBar(QWidget):
    """Panel makra (F3: strona `_PanelStack`, otwierana z paska zbioru „Popraw nagłówki…") — sekcje
    Oblicz/Przypisz. Emituje `preview(dict)` (policz i pokaż w gridzie, BEZ zapisu), `stage(dict)`
    (do szuflady), `cleared()`. Makro operuje na tym, co widać w gridzie (frame_ids wołającego)."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self._keywords = keywords
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        b = QVBoxLayout(self.body); b.setContentsMargins(12, 4, 0, 4)
        # Oblicz (opcjonalny krok pośredni: nazwa = wyrażenie)
        comp = QHBoxLayout()
        comp.addWidget(QLabel(i18n.t("grid.macro.compute")))
        self.comp_name = QLineEdit(); self.comp_name.setPlaceholderText(i18n.t("grid.macro.name_ph"))
        self.comp_name.setFixedWidth(120)
        self.comp_expr = QLineEdit(); self.comp_expr.setPlaceholderText(i18n.t("grid.macro.expr_ph"))
        comp.addWidget(self.comp_name); comp.addWidget(QLabel("=")); comp.addWidget(self.comp_expr, 1)
        b.addLayout(comp)
        # Przypisz (keyword op wartość)
        asg = QHBoxLayout()
        asg.addWidget(QLabel(i18n.t("grid.macro.assign")))
        self.asg_kw = QComboBox(); self.asg_kw.setEditable(True); self.asg_kw.addItems(keywords)
        self.asg_kw.setFixedWidth(160)
        self.asg_op = QComboBox(); self.asg_op.addItems(["set", "add"])
        self.asg_expr = QLineEdit(); self.asg_expr.setPlaceholderText(i18n.t("grid.macro.assign_ph"))
        # Komentarz karty (AR-47): pusty = zastany zostaje; wpisany - zapis razem z nim. Jedyna
        # droga z GUI dla karty FITS, której zastany komentarz nie mieści się przy nowej wartości.
        self.asg_comment = QLineEdit()
        self.asg_comment.setPlaceholderText(i18n.t("grid.macro.comment_ph"))
        self.asg_comment.setToolTip(i18n.t("grid.macro.comment_tip"))
        self.asg_comment.setFixedWidth(180)
        asg.addWidget(self.asg_kw); asg.addWidget(self.asg_op); asg.addWidget(QLabel("=")); asg.addWidget(self.asg_expr, 1)
        asg.addWidget(self.asg_comment)
        b.addLayout(asg)
        # akcje
        act = QHBoxLayout()
        self.btn_prev = QPushButton(i18n.t("grid.action.preview")); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton(i18n.t("grid.action.to_staging")); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton(i18n.t("grid.action.clear_preview")); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    def set_actions_enabled(self, on):
        """Wyłącz Podgląd/Do stagingu, gdy nie ma widocznych klatek (szczery disabled zamiast cichego
        no-op — wizytator #4). `Wyczyść podgląd` zostaje aktywny (zdejmuje ewentualny stary podgląd)."""
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_keywords(self, keywords):
        self._keywords = keywords
        cur = self.asg_kw.currentText()
        self.asg_kw.blockSignals(True)
        self.asg_kw.clear(); self.asg_kw.addItems(keywords); self.asg_kw.setCurrentText(cur)
        self.asg_kw.blockSignals(False)

    def macro_def(self):
        """Zbierz definicję makra z pól (None, gdy brak keyworda/wartości przypisania)."""
        kw = self.asg_kw.currentText().strip()
        expr = self.asg_expr.text().strip()
        if not kw or not expr:
            return None
        md = {"assign": {"keyword": kw, "op": self.asg_op.currentText(), "expr": expr}}
        komentarz = self.asg_comment.text().strip()
        if komentarz:
            md["assign"]["comment"] = komentarz
        cname, cexpr = self.comp_name.text().strip(), self.comp_expr.text().strip()
        if cname and cexpr:
            md["computes"] = [{"name": cname, "expr": cexpr}]
        return md

    def _emit_preview(self):
        md = self.macro_def()
        if md is not None:
            self.preview.emit(md)

    def _emit_stage(self):
        md = self.macro_def()
        if md is not None:
            self.stage.emit(md)


class _TokenRow(QWidget):
    """Jeden rząd edytora wzoru: typ tokenu + argument (folder→poziom, orig→regex, kind→wielkość liter) + ↑↓⊖. `spec()`
    zwraca goły string (token bez argumentu) LUB dict `{"t":…}` (parametryczny) — forma DANE `naming`."""

    changed = Signal()
    removeRequested = Signal(object)
    moveRequested = Signal(object, int)                # (self, -1 w górę / +1 w dół)

    # (klucz-etykiety, tid). Etykieta → i18n.t w budowie combo; tid to DANE `naming`.
    _TOKENS = (("grid.token.datetime", "datetime"), ("grid.token.object", "object"),
               ("grid.token.kind", "kind"), ("grid.token.filter", "filter"),
               ("grid.token.exp", "exp"), ("grid.token.disc", "disc"),
               ("grid.token.folder", "folder"), ("grid.token.orig", "orig"),
               ("grid.token.flatgrp", "flatgrp"), ("grid.token.trail", "trail"))
    # Wielkość liter tokenu kind: (klucz-etykiety, wartość `case`; None = jak w bazie, goły "kind").
    _CASES = (("grid.token.case_keep", None), ("grid.token.case_upper", "upper"),
              ("grid.token.case_lower", "lower"))

    def __init__(self, spec="kind", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox(); self.combo.setFixedWidth(170)     # stała kolumna typu (wiz #2 — bez ragged)
        for lbl, tid in self._TOKENS:
            self.combo.addItem(i18n.t(lbl), tid)
        lay.addWidget(self.combo)
        self.level = QSpinBox(); self.level.setRange(1, 8); self.level.setPrefix(i18n.t("grid.token.level_prefix"))
        lay.addWidget(self.level)
        self.regex = QLineEdit(); self.regex.setPlaceholderText(i18n.t("grid.token.regex_ph"))
        self.regex.setMinimumWidth(160)
        lay.addWidget(self.regex)
        self.case = QComboBox()
        for lbl, val in self._CASES:
            self.case.addItem(i18n.t(lbl), val)
        lay.addWidget(self.case)
        lay.addStretch(1)                                           # wypełniacz → przyciski zawsze przy prawej
        btn_up = QPushButton("↑"); btn_dn = QPushButton("↓"); btn_rm = QPushButton("⊖")
        for b in (btn_up, btn_dn, btn_rm):
            b.setFixedWidth(28); lay.addWidget(b)
        btn_up.clicked.connect(lambda: self.moveRequested.emit(self, -1))
        btn_dn.clicked.connect(lambda: self.moveRequested.emit(self, +1))
        btn_rm.clicked.connect(lambda: self.removeRequested.emit(self))
        self.combo.currentIndexChanged.connect(self._sync_args)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.level.valueChanged.connect(lambda *_: self.changed.emit())
        self.regex.textChanged.connect(lambda *_: self.changed.emit())
        self.case.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.set_spec(spec)

    def _sync_args(self):
        tok = self.combo.currentData()
        self.level.setVisible(tok == "folder")
        self.regex.setVisible(tok == "orig")
        self.case.setVisible(tok == "kind")

    def set_spec(self, spec):
        tok = spec.get("t") if isinstance(spec, dict) else spec
        args = spec if isinstance(spec, dict) else {}
        i = self.combo.findData(tok)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        if tok == "folder":
            self.level.setValue(int(args.get("n", 1)))
        elif tok == "orig":
            self.regex.setText(str(args.get("re", "")))
        elif tok == "kind":
            j = self.case.findData(args.get("case"))
            self.case.setCurrentIndex(j if j >= 0 else 0)
        self._sync_args()

    def opis(self):
        """Token słowami do streszczenia zwiniętego wzoru: etykieta typu i argument, gdy go ma."""
        tok, tekst = self.combo.currentData(), self.combo.currentText()
        if tok == "folder":
            return f"{tekst} {self.level.value()}"
        if tok == "orig" and self.regex.text():
            return f"{tekst} ({self.regex.text()})"
        if tok == "kind" and self.case.currentData() is not None:
            return f"{tekst} ({self.case.currentText()})"
        return tekst

    def spec(self):
        tok = self.combo.currentData()
        if tok == "folder":
            return {"t": "folder", "n": self.level.value()}
        if tok == "orig":
            return {"t": "orig", "re": self.regex.text()}
        if tok == "kind" and self.case.currentData() is not None:
            return {"t": "kind", "case": self.case.currentData()}
        return tok


class _TemplateEditor(QWidget):
    """Edytor wzoru nazwy (§5): lista `_TokenRow` + [+ Token][Przywróć domyślny]. `template()` = lista
    specyfikacji (DANE dla `naming.run_rename`). Domyślny preset = `DEFAULT_TEMPLATE` (Z `disc` — D-I4
    bezpieczny domyśl; czyste nazwy = user RĘCZNIE usuwa rząd `disc`, kolizja → warning+skip).

    ZWIJANY (AR-78): rozwinięty wzór z domyślnymi sześcioma tokenami zabierał tabeli dwie trzecie
    pionu (firsthand: 11 wierszy pod otwartym panelem). Zwinięty zostawia JEDEN wiersz nagłówka ze
    streszczeniem wzoru słowami - widać, jaki wzór pójdzie do podglądu, a edycja jest jeden klik
    dalej. Tokeny w jednym wierszu odpadły: rząd tokenu ma stałą kolumnę typu (170 px), argument
    i trzy przyciski, więc sześć tokenów to ~1600 px przy ~1100 px panelu - wiersz musiałby się
    przewijać w bok albo tracić strzałki kolejności. O tym, kiedy wzór startuje zwinięty, decyduje
    wołający (`set_expanded`, pamięć w `FramesView`); `expandedChanged` niesie wyłącznie gest ręki."""

    changed = Signal()
    expandedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.btn_toggle = QToolButton()
        self.btn_toggle.setText(i18n.t("grid.tmpl.title"))
        self.btn_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_toggle.setAutoRaise(True)
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        self.btn_toggle.setArrowType(Qt.DownArrow)
        self.btn_toggle.setToolTip(i18n.t("grid.tmpl.toggle_tip"))
        head.addWidget(self.btn_toggle)
        # Streszczenie wzoru (pełne w podpowiedzi): puste przy rozwiniętym, ale zawsze w układzie -
        # jest wypełniaczem, który trzyma przyciski przy prawej krawędzi.
        self._summary = ElidedLabel()
        self._summary.setProperty("role", "secondary")
        head.addWidget(self._summary, 1)
        btn_add = QPushButton(i18n.t("grid.tmpl.add_token")); btn_def = QPushButton(i18n.t("grid.tmpl.restore"))
        head.addWidget(btn_add); head.addWidget(btn_def)
        outer.addLayout(head)
        self._empty_hint = QLabel(i18n.t("grid.tmpl.empty_hint")); self._empty_hint.hide()
        self._empty_hint.setProperty("role", "secondary")
        outer.addWidget(self._empty_hint)
        self._host = QWidget()
        self._rows_lay = QVBoxLayout(self._host); self._rows_lay.setContentsMargins(0, 0, 0, 0)
        # Sufit wysokości + scroll (wiz #1): rozbudowany wzór NIE zjada gridu — nadwyżka scrolluje.
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True); self._scroll.setWidget(self._host)
        self._scroll.setFrameShape(QFrame.NoFrame); self._scroll.setMaximumHeight(200)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)
        # „+ Token" przy zwiniętym wzorze najpierw go rozwija: nowy rząd czeka na wybór typu.
        btn_add.clicked.connect(lambda: (self._rozwin_gestem(), self._add_row("kind"), self.changed.emit()))
        btn_def.clicked.connect(lambda: self._restore_default())
        self.btn_toggle.toggled.connect(self._on_toggle)
        self.changed.connect(self._odswiez_streszczenie)
        self.set_template(naming.DEFAULT_TEMPLATE)

    def _rows(self):
        return [self._rows_lay.itemAt(i).widget() for i in range(self._rows_lay.count())]

    def _refresh_empty(self):
        rozwiniety = self.is_expanded()
        self._empty_hint.setVisible(rozwiniety and len(self._rows()) == 0)
        self._scroll.setVisible(rozwiniety)
        self._odswiez_streszczenie()

    # ---- zwijanie (AR-78) ----
    def is_expanded(self):
        return self.btn_toggle.isChecked()

    def set_expanded(self, on):
        """Stan z zewnątrz (pamięć wołającego) - bez `expandedChanged`, to nie jest gest ręki."""
        self.btn_toggle.blockSignals(True)
        self.btn_toggle.setChecked(bool(on))
        self.btn_toggle.blockSignals(False)
        self._pokaz_stan()

    def _on_toggle(self, on):
        self._pokaz_stan()
        self.expandedChanged.emit(bool(on))

    def _rozwin_gestem(self):
        if not self.is_expanded():
            self.btn_toggle.setChecked(True)            # przez `toggled` - to gest, pamięć go zapisze

    def _pokaz_stan(self):
        self.btn_toggle.setArrowType(Qt.DownArrow if self.is_expanded() else Qt.RightArrow)
        self._refresh_empty()

    def _odswiez_streszczenie(self):
        """Wzór słowami przy zwiniętym edytorze, pusty przy rozwiniętym (rzędy mówią same)."""
        opisy = [row.opis() for row in self._rows()]
        tekst = " · ".join(opisy) if opisy else i18n.t("grid.tmpl.summary_empty")
        self._summary.set_full_text("" if self.is_expanded() else tekst)

    def _add_row(self, spec):
        row = _TokenRow(spec)
        row.removeRequested.connect(self._remove)
        row.moveRequested.connect(self._move)
        row.changed.connect(self.changed)
        self._rows_lay.addWidget(row)
        self._refresh_empty()
        return row

    def _remove(self, row):
        self._rows_lay.removeWidget(row); row.deleteLater()
        self._refresh_empty(); self.changed.emit()

    def _move(self, row, direction):
        i = self._rows_lay.indexOf(row); j = i + direction
        if 0 <= j < self._rows_lay.count():
            self._rows_lay.removeWidget(row); self._rows_lay.insertWidget(j, row); self.changed.emit()

    def _restore_default(self):
        self.set_template(naming.DEFAULT_TEMPLATE); self.changed.emit()

    def set_template(self, specs):
        while self._rows_lay.count():
            w = self._rows_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for spec in specs:
            self._add_row(spec)
        self._refresh_empty()

    def template(self):
        return [row.spec() for row in self._rows()]


class RenameBar(QWidget):
    """Panel „Nazwy z faktów" (F3: strona `_PanelStack`, otwierana z paska zbioru „Uporządkuj nazwy
    plików…"; BLIŹNIAK strukturalny `MacroBar`). Trzy strefy: (1) polityka wsadu — Źródło/Offset/
    Fallback + żywa etykieta celu; (2) panel inspekcji daty (G1, G4 — pełne timestampy + Δ + align do
    drugiego źródła); (3) akcje. Emituje `preview(policy)`/`stage(policy)`/`cleared()`/`sourceChanged()`.
    `policy` = {source, offset_hours, fallback} — jeden silnik `naming.run_rename`. Panel daty KARMIONY
    z zewnątrz (`set_echo`) — FramesView zna zaznaczenie i wie, czy panel jest otwarty."""

    preview = Signal(object)
    stage = Signal(object)
    cleared = Signal()
    sourceChanged = Signal()     # zmiana źródła → przelicz etykietę/znak align (R2 #2)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._median = None       # ostatnia mediana Δ wsadu (do przycisku „Wyrównaj")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        b = QVBoxLayout(self.body); b.setContentsMargins(12, 4, 0, 4)

        # (1) polityka wsadu
        pol = QHBoxLayout()
        pol.addWidget(QLabel(i18n.t("grid.rename.source")))
        self.src = QComboBox()
        self.src.addItem("DATE-OBS", "date_obs")          # D2: default DATE-OBS (kw FITS — bez tłumaczenia)
        self.src.addItem(i18n.t("grid.rename.src_filename"), "filename")
        self.src.currentIndexChanged.connect(lambda *_: self.sourceChanged.emit())
        pol.addWidget(self.src)
        pol.addWidget(QLabel(i18n.t("grid.rename.offset")))
        self.offset = QSpinBox(); self.offset.setRange(-24, 24); self.offset.setValue(0)
        self.offset.setSuffix(" h")                       # BEZ założenia strefy (§2): 0 default
        pol.addWidget(self.offset)
        self.fallback = QCheckBox(i18n.t("grid.rename.fallback")); self.fallback.setChecked(True)  # D1
        pol.addWidget(self.fallback)
        pol.addStretch(1)
        self.target_lbl = QLabel("")                      # żywa etykieta celu (R1 #18)
        self.target_lbl.setProperty("role", "secondary")  # tekst drugorzędny z motywu (F6 §7)
        pol.addWidget(self.target_lbl)
        b.addLayout(pol)

        # (2) panel inspekcji daty (G1 — zarezerwowana powierzchnia; G4 — pełne timestampy)
        grid = QGridLayout(); grid.setContentsMargins(0, 2, 0, 2)
        self.lbl_primary = QLabel("—"); self.lbl_secondary = QLabel("—")
        self.lbl_delta = QLabel(""); self.lbl_flag = QLabel("")
        self.lbl_flag.setProperty("role", "error")       # kolor z motywu (P-C), nie sztywne #b00
        self.btn_align = QPushButton(i18n.t("grid.rename.align")); self.btn_align.setEnabled(False)
        self.btn_align.clicked.connect(self._align)
        grid.addWidget(self.lbl_primary, 0, 0); grid.addWidget(self.lbl_secondary, 0, 1)
        grid.addWidget(self.lbl_delta, 1, 0); grid.addWidget(self.lbl_flag, 1, 1)
        b.addLayout(grid)
        align_row = QHBoxLayout()                        # „Wyrównaj" = szerokość treści (pomocnik NIE
        align_row.addWidget(self.btn_align); align_row.addStretch(1)   # dominuje akcji głównych — wiz #5)
        b.addLayout(align_row)

        # (3) edytor wzoru nazwy (v2 §5 — folder/orig/per-token; DANE dla `run_rename`)
        b.addSpacing(10)                                 # oddech od panelu daty (wiz #4)
        self.template_editor = _TemplateEditor()
        b.addWidget(self.template_editor)

        # (4) akcje (bliźniaczo do makra)
        act = QHBoxLayout()
        self.btn_prev = QPushButton(i18n.t("grid.action.preview")); self.btn_prev.clicked.connect(self._emit_preview)
        self.btn_stage = QPushButton(i18n.t("grid.action.to_staging")); self.btn_stage.clicked.connect(self._emit_stage)
        btn_clear = QPushButton(i18n.t("grid.action.clear_preview")); btn_clear.clicked.connect(lambda: self.cleared.emit())
        act.addStretch(1); act.addWidget(self.btn_prev); act.addWidget(self.btn_stage); act.addWidget(btn_clear)
        b.addLayout(act)
        outer.addWidget(self.body)

    # ---- stan / API ----
    def source(self):
        return self.src.currentData()

    def policy(self):
        return {"source": self.src.currentData(), "offset_hours": self.offset.value(),
                "fallback": self.fallback.isChecked(), "template": self.template_editor.template()}

    def set_actions_enabled(self, on):
        self.btn_prev.setEnabled(on)
        self.btn_stage.setEnabled(on)

    def set_target_label(self, text):
        self.target_lbl.setText(text)

    def set_echo(self, primary, secondary, delta, flag, *, flag_role="warn", median=None, spread=None):
        """Wypełnij panel daty (FramesView liczy z zaznaczenia/widocznych). `median` (Δ w godzinach, float
        albo None) uzbraja „Wyrównaj": znak ZALEŻNY od źródła (R2 #2), wartość przez half-away (R2 #5),
        surowa mediana + rozrzut w tooltipie (R1 #16).

        `flag_role` NAZYWA WAGĘ komunikatu (wizytacja P-C #7): „Δ niepełnogodzinna!" to ostrzeżenie
        (`warn`), „brak źródła czasu" to stan informacyjny (`secondary`). Do P-C oba nosiły tę samą
        czerwień co „Etap padł" Dostawy — akcent semantyczny, który krzyczy o wszystkim, nie mówi
        o niczym. Czerwień zostaje wyłącznie dla awarii."""
        self.lbl_primary.setText(primary); self.lbl_secondary.setText(secondary)
        self.lbl_delta.setText(delta); self.lbl_flag.setText(flag)
        _set_role(self.lbl_flag, flag_role)
        self._median = median
        if median is None:
            self.btn_align.setEnabled(False)
            self.btn_align.setText(i18n.t("grid.rename.align"))
            self.btn_align.setToolTip("")
            return
        self.btn_align.setEnabled(True)
        off = self._offset_from_median()
        other = i18n.t("grid.rename.other_fname") if self.source() == "date_obs" else "DATE-OBS"
        self.btn_align.setText(i18n.t("grid.rename.align_to", other=other, off=f"{off:+d}"))
        tip = i18n.t("grid.rename.align_tip", median=repr(median))
        if spread is not None:
            tip += i18n.t("grid.rename.align_tip_spread", spread=f"{spread:g}")
        self.btn_align.setToolTip(tip)

    def _offset_from_median(self):
        """Offset całkowity z mediany Δ (=hdr−nazwa). source=date_obs → −Δ (przesuń nagłówek do nazwy);
        source=filename → +Δ (przesuń nazwę do nagłówka). `resolve_dt` = base+offset (R2 #2)."""
        signed = -self._median if self.source() == "date_obs" else self._median
        return _half_away(signed)

    def _align(self):
        if self._median is not None:
            self.offset.setValue(self._offset_from_median())

    def _emit_preview(self):
        self.preview.emit(self.policy())

    def _emit_stage(self):
        self.stage.emit(self.policy())


class ElidedLabel(QLabel):
    """QLabel z elizją w prawo: pełny tekst przez `set_full_text` (ląduje też w tooltipie), render
    przycinany do bieżącej szerokości — długi opis kryteriów nie rozpycha okna (F3, §4)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def set_full_text(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._update_elide()

    def full_text(self):
        """Tekst PRZED elizją — wołający pyta o treść, nie o to, co się akurat zmieściło
        (`text()` zwraca wersję przyciętą i „czy jest co pokazać" odpowiedziałby na niej fałszem
        przy wąskim panelu)."""
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def _update_elide(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width() - 4)))
