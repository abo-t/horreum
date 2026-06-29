"""`python -m horreum.gui <ścieżka.db>` — uruchom okno osi teleskopu na istniejącej bazie.

Cienki punkt wejścia; cała logika okna w `app.py`. Importuje Qt pośrednio przez `app` — to jeden
z DWÓCH plików warstwy widżetów (obok `app.py`), którym wolno tknąć PySide6 (§4, test izolacji
`tests/test_gui_isolation.py`)."""
from horreum.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
