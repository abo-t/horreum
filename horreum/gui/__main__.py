"""`python -m horreum.gui [ścieżka.db]` — uruchom aplikację Horreum (okno `MainWindow`). Z argumentem
otwiera bazę od razu; bez argumentu okno startuje puste (Otwórz/Nowa baza z menu Plik).

Cienki punkt wejścia; cała logika okna w `app.py`. Importuje Qt pośrednio przez `app` - sam PySide6
nie importuje, więc wpisu w `QT_WIDGET_FILES` (`tests/test_gui_isolation.py`) nie ma."""
from horreum.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
