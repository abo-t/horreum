"""Dialog „Projekcja z tej perspektywy" (KROK 6 scalenia — warstwa widżetów; PLAN_projekcje §4).

Modal TYLKO na potwierdzenie eksportu (doktryna §5: grid = centrum, minimum modali). Dwa kroki:
(1) „Podgląd (DRY)" — `projection.plan` + `apply(do_apply=False)`: sonduje stan celu (would-link/
exists/conflict), ZERO tworzenia → raport w polu tekstowym; (2) „Utwórz…" — `apply(do_apply=True)`:
materializuje drzewo linków/kopii SYNCHRONICZNIE z wait-cursorem (wzorzec commitu gridu — projekcja
`apply` nie pisze do DB, więc bez workera QThread; duże materializacje → CLI z pulsem).

Cała logika (plan/link/sonda/guard) w Qt-wolnej klindze `horreum.projection`; tu SAMA glue widżetów.
Plik na whiteliście `test_gui_isolation` (warstwa widżetów — import PySide6 uprawniony). Każda zmiana
parametru (układ/korzeń/kopia) UNIEWAŻNIA „Utwórz" → wymusza świeży DRY pod dokładnie te parametry,
którymi zadziała materializacja (bez rozjazdu podgląd↔wykonanie)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from horreum import projection

_TREE_CAP = 30                        # ile folderów kategorii pokazać w raporcie dialogu


class ProjectionDialog(QDialog):
    """Podgląd DRY + materializacja projekcji WIDOCZNEJ perspektywy. `frame_ids` = klatki gridu (cel);
    `now_fn` = zegar (ts manifestu); `perspektywa` = etykieta do manifestu `_PROJEKCJA.json`."""

    def __init__(self, con, frame_ids, *, now_fn, perspektywa="perspektywa", parent=None):
        super().__init__(parent)
        self.con = con
        self._frame_ids = list(frame_ids)
        self._now = now_fn
        self._perspektywa = perspektywa
        self._plan = None                # ostatni udany plan DRY (uzbraja „Utwórz" pod TE parametry)
        self.setWindowTitle("Projekcja z tej perspektywy")
        self.setModal(True)
        self.resize(600, 460)
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Klatek w perspektywie: {len(self._frame_ids)}"))

        row_l = QHBoxLayout()
        row_l.addWidget(QLabel("Układ:"))
        self.combo_layout = QComboBox()
        self.combo_layout.addItem("po obiektach  (obiekt / filtr)", "po-obiektach")
        self.combo_layout.addItem("WBPP feed  (obiekt / teleskop / filtr)", "wbpp-feed")
        self.combo_layout.currentIndexChanged.connect(self._invalidate)
        row_l.addWidget(self.combo_layout)
        row_l.addStretch(1)
        v.addLayout(row_l)

        row_r = QHBoxLayout()
        row_r.addWidget(QLabel("Korzeń:"))
        self.edit_root = QLineEdit()
        self.edit_root.setPlaceholderText("…\\_WBPP\\feed  — MUSI zawierać segment _WBPP lub _Review")
        self.edit_root.textChanged.connect(self._invalidate)
        btn_pick = QPushButton("Wskaż…")
        btn_pick.setAutoDefault(False)               # Enter NIE otwiera wyboru folderu (akcja gł. = DRY, #1)
        btn_pick.clicked.connect(self._pick_root)
        row_r.addWidget(self.edit_root, 1)
        row_r.addWidget(btn_pick)
        v.addLayout(row_r)

        hint = QLabel("Korzeń musi zawierać segment _WBPP lub _Review (drzewo wykluczone ze skanu).")
        hint.setStyleSheet("color: #777;")           # trwała reguła korzenia (dyskoverowalna przed błędem, #2)
        v.addWidget(hint)

        self.chk_copy = QCheckBox("Kopiuj bajty zamiast hardlinka (cross-wolumen / brak wsparcia linków)")
        self.chk_copy.toggled.connect(self._invalidate)
        v.addWidget(self.chk_copy)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))   # monospace: słupki liczb/drzewo (#7)
        self.report.setPlaceholderText("Kliknij „Podgląd (DRY)”, by zobaczyć plan bez zmian na dysku.")
        v.addWidget(self.report, 1)

        act = QHBoxLayout()
        self.btn_dry = QPushButton("Podgląd (DRY)")
        self.btn_dry.setDefault(True)                # akcja główna: akcent natywny + Enter (wizytator #1)
        self.btn_dry.clicked.connect(self._on_dry)
        self.btn_apply = QPushButton("Utwórz…")
        self.btn_apply.setEnabled(False)             # dopiero po udanym DRY (materializacja = ruch na dysku)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_close = QPushButton("Zamknij")
        btn_close.clicked.connect(self.reject)
        act.addStretch(1)
        act.addWidget(self.btn_dry)
        act.addWidget(self.btn_apply)
        act.addWidget(btn_close)
        v.addLayout(act)

    # ---- stan ----
    def _invalidate(self, *_):
        """Zmiana parametru (układ/korzeń/kopia) unieważnia poprzedni DRY — „Utwórz" wymaga świeżego
        podglądu pod DOKŁADNIE te parametry (bez rozjazdu podgląd↔wykonanie)."""
        self._plan = None
        self.btn_apply.setEnabled(False)

    def _pick_root(self):
        path = QFileDialog.getExistingDirectory(self, "Wskaż korzeń projekcji (pod _WBPP/_Review)")
        if path:
            self.edit_root.setText(path)

    # ---- akcje ----
    def _on_dry(self):
        root = self.edit_root.text().strip()
        if not root:
            self.report.setPlainText("Podaj korzeń projekcji (musi zawierać segment _WBPP lub _Review).")
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            plan = projection.plan(self.con, self._frame_ids, self.combo_layout.currentData())
            res = projection.apply(plan, root, do_apply=False, copy=self.chk_copy.isChecked(),
                                   now=self._now())
        except ValueError as exc:                    # korzeń bez segmentu wykluczonego (§0 guard)
            self._plan = None
            self.btn_apply.setEnabled(False)
            self.report.setPlainText(f"Nie można: {exc}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._plan = plan
        self.report.setPlainText(self._format(res, plan, dry=True))
        self.btn_apply.setEnabled(True)              # DRY OK → „Utwórz" odblokowane pod te parametry

    def _on_apply(self):
        root = self.edit_root.text().strip()
        if self._plan is None or not root:
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = projection.apply(
                self._plan, root, do_apply=True, copy=self.chk_copy.isChecked(), now=self._now(),
                manifest={"perspektywa": self._perspektywa, "n_frames": len(self._frame_ids)})
        except projection.ProjectionAbort as exc:    # sonda pierwszego linku padła (SMB kopia?)
            self.report.setPlainText(
                f"ABORT: {exc}\n\n" + self._format(exc.result, self._plan, dry=False, partial=True))
            self.btn_apply.setEnabled(False)
            return
        except (ValueError, OSError) as exc:
            self.report.setPlainText(f"Błąd: {exc}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.report.setPlainText(self._format(res, self._plan, dry=False))
        self.btn_apply.setEnabled(False)             # zrobione — kolejny „Utwórz" wymaga nowego DRY

    def _format(self, res, plan, *, dry, partial=False):
        c = res.counts
        lines = []
        if dry:
            lines.append(f"DRY — bez zmian na dysku (układ {res.layout}):")
            lines.append(f"  do zlinkowania: {c.get('would-link', 0)}   istnieje: {c.get('exists', 0)}   "
                         f"konflikty: {c.get('conflict', 0)}   pominięto: {c.get('skipped', 0)}")
        else:
            head = "Wynik częściowy" if partial else "Utworzono"   # abort → nie „Utworzono" (wizytator #6)
            lines.append(f"{head} (układ {res.layout}{', kopie' if res.copy else ''}):")
            lines.append(f"  zlinkowano: {c.get('linked', 0)}   istniało: {c.get('exists', 0)}   "
                         f"konflikty: {c.get('conflict', 0)}   verify_bad: {c.get('verify_bad', 0)}   "
                         f"błędy: {c.get('error', 0)}   pominięto: {c.get('skipped', 0)}")
        if plan.multi_present:
            lines.append(f"  wiele obecnych kopii: {plan.multi_present} (zlinkowano pierwszą)")
        folders: dict = {}
        for it in plan.items:
            key = "/".join(it.segments)
            folders[key] = folders.get(key, 0) + 1
        lines.append(f"  drzewo: {len(folders)} folderów kategorii")
        for key, n in sorted(folders.items(), key=lambda kv: (-kv[1], kv[0]))[:_TREE_CAP]:
            lines.append(f"    {key}: {n}")
        if len(folders) > _TREE_CAP:
            lines.append(f"    … (+{len(folders) - _TREE_CAP} folderów)")
        return "\n".join(lines)
