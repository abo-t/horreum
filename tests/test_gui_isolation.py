"""§7.2 izolacja Qt od rdzenia (PLAN_gui §4) — STRUKTURALNIE, statycznym AST, BEZ importu PySide6.

Ten plik NIE robi `importorskip` — działa też w izolowanym clone bez `[gui]` (§5.11). To mocniejszy
dowód niż „pełny pytest przechodzi bez Qt": dowodzi, że ŻADEN moduł rdzenia ani read-model nie ma
nawet `import PySide6`, więc `import horreum.db/repo/queries/cli` nie wciągnie Qt niezależnie od tego,
co już siedzi w `sys.modules`. Qt wolno tknąć WYŁĄCZNIE warstwie widżetów (`app.py`, `__main__.py`)."""
import ast
from pathlib import Path

import horreum

PKG = Path(horreum.__file__).parent
# Jedyne pliki, którym wolno importować PySide6. `pipeline.py` (widok Pipeline + worker QThread —
# PLAN_gui_pipeline §5) DOŁĄCZONY w etapie 2: to warstwa widżetów, import Qt uprawniony. Rdzeń,
# read-model (`queries.py`) i logika progresu Qt-wolna (`progress.py`) zostają BEZ Qt.
QT_WIDGET_FILES = {"app.py", "__main__.py", "pipeline.py"}


def _imports_pyside6(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "PySide6" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "PySide6":
                return True
    return False


def test_pyside6_tylko_w_warstwie_widzetow():
    """Cały pakiet `horreum/` poza `gui/app.py` i `gui/__main__.py` jest Qt-free. Gdyby ktoś wstawił
    `import PySide6` w rdzeniu (albo w `queries.py`/`gui/__init__.py`), izolacja §7.2 by padła."""
    offenders = [
        str(p.relative_to(PKG)) for p in sorted(PKG.rglob("*.py"))
        if p.name not in QT_WIDGET_FILES and _imports_pyside6(p)
    ]
    assert not offenders, f"PySide6 zaimportowany poza warstwą widżetów (app/__main__): {offenders}"


def test_widgety_realnie_importuja_qt():
    """Asercja pozytywna: warstwa widżetów REALNIE używa PySide6 (inaczej powyższy test byłby
    pusty — np. po przeniesieniu Qt do innego pliku — i przestałby cokolwiek pilnować)."""
    assert _imports_pyside6(PKG / "gui" / "app.py"), "app.py nie importuje PySide6 — lista plików Qt nieaktualna"


def test_readmodel_i_init_gui_qt_free():
    """Read path (`queries.py`), logika progresu (`progress.py`) i `gui/__init__.py` MUSZĄ być
    Qt-free — `from horreum.gui import queries`/`progress` nie może wciągać Qt (testy logiki
    Qt-wolnej chodzą bez PySide6)."""
    assert not _imports_pyside6(PKG / "gui" / "queries.py")
    assert not _imports_pyside6(PKG / "gui" / "progress.py")
    assert not _imports_pyside6(PKG / "gui" / "__init__.py")
