"""Bramka i napis gestu Dostawy bez budowy strony (`horreum.gui.dostawa_bramka`, AR-335, AR-337) - BEZ PySide6.

Moduł czytają gospodarz (powód odmowy biegu przy niezbudowanej Dostawie), widok Dostawy (ta sama reguła na własnym
stanie) i Porządki (napis gestu w podpowiedzi wiersza bajtów). Ten plik nie robi `importorskip` - biega też w `.venv`
bez Qt; Qt-wolność modułu przypina PRZECHODNIO (podproces), a bramka AST pilnuje, że lista Porządków (`tasks.py`)
nie importuje modułu Dostawy. Każdy test nazywa mutanta, który go czerwieni."""
import ast
import subprocess
import sys
from pathlib import Path

import horreum
from horreum import scan
from horreum.gui import dostawa_bramka, i18n

PKG = Path(horreum.__file__).parent


def test_powod_odmowy_biegu_kolejnosc_i_brak():
    """Kolejność = ważność: brak bazy wygrywa nad biegiem i zapisem, bieg nad zapisem; bez żadnego z nich `None`.
    Falsyfikator: zamiana gałęzi biegu i zapisu (przy obu naraz pada zdanie zapisu)."""
    t = dostawa_bramka.powod_odmowy_biegu
    assert t(baza=False, bieg=True, zapis=True) == i18n.t("pipeline.refuse.no_db")
    assert t(baza=True, bieg=True, zapis=True) == i18n.t("pipeline.refuse.delivery_running")
    assert t(baza=True, bieg=False, zapis=True) == i18n.t("pipeline.refuse.writeback")
    assert t(baza=True, bieg=False, zapis=False) is None


def test_etykieta_gestu_kopii_trzy_napisy():
    """Fakty i bajty naraz - napis obu robót; same bajty - „Sprawdź bajty…”; same fakty - „Zbierz fakty…”.
    Falsyfikator: gałąź samych bajtów przed gałęzią obu robót (fakty giną z napisu)."""
    t = dostawa_bramka.etykieta_gestu_kopii
    assert t(scan.CopyFactsWaiting(facts=2, bytes=3, copies=4)) == i18n.t("pipeline.btn.copy_both", fakty=2, bajty=3)
    assert t(scan.CopyFactsWaiting(bytes=5, copies=5)) == i18n.t("pipeline.btn.copy_bytes", n=5)
    assert t(scan.CopyFactsWaiting(facts=7, copies=7)) == i18n.t("pipeline.btn.copy_facts", n=7)


def test_modul_bramki_bez_qt_przechodnio():
    """Import modułu w świeżym procesie nie wciąga ŻADNEGO modułu `PySide6` - także przez importy modułów, które sam
    importuje (`tests/test_gui_isolation.py` widzi tylko importy wprost). Falsyfikator: import modułu Dostawy albo
    PySide6 w `dostawa_bramka.py`."""
    kod = ("import sys; sys.path.insert(0, sys.argv[1]); import horreum.gui.dostawa_bramka; "
           "print(sorted(m for m in sys.modules if m.split('.')[0] == 'PySide6'))")
    wynik = subprocess.run([sys.executable, "-I", "-c", kod, str(PKG.parent)], capture_output=True, text=True,
                           timeout=120)
    assert wynik.returncode == 0, wynik.stderr
    assert wynik.stdout.strip() == "[]", wynik.stdout


def _importy_modulow(drzewo):
    """Nazwy modułów importowanych w drzewie AST - także leniwie w funkcjach: `import a.b`, `from a import b`
    (jako `a.b` i `a`), `from a.b import c` (jako `a.b`)."""
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, ast.Import):
            for a in wezel.names:
                yield a.name
        elif isinstance(wezel, ast.ImportFrom) and wezel.module:
            yield wezel.module
            for a in wezel.names:
                yield f"{wezel.module}.{a.name}"


def test_porzadki_nie_importuja_modulu_dostawy():
    """AR-337: `tasks.py` (lista Porządków) nie importuje `horreum.gui.pipeline` w żadnej postaci - napis gestu idzie
    z modułu bez Qt, więc wynik liczników z tła nie ładuje modułu Dostawy na wątku GUI. Falsyfikator: przywrócony import
    leniwy `from horreum.gui.pipeline import …` w `_przyloz_liczniki`."""
    drzewo = ast.parse((PKG / "gui" / "tasks.py").read_text(encoding="utf-8"))
    assert "horreum.gui.pipeline" not in set(_importy_modulow(drzewo))
    assert "horreum.gui.dostawa_bramka" in set(_importy_modulow(drzewo))      # predykat nie oślepł
