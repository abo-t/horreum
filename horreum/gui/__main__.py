"""`python -m horreum.gui [ścieżka.db]` — uruchom aplikację Horreum (okno `MainWindow`). Z argumentem
otwiera bazę od razu; bez argumentu okno startuje puste (Otwórz/Nowa baza z menu Plik).

Cienki punkt wejścia; cała logika okna w `app.py`. Importuje Qt pośrednio przez `app` — to jeden
z plików warstwy widżetów, którym wolno tknąć PySide6 (§4, test izolacji
`tests/test_gui_isolation.py`)."""
from horreum.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
