"""Entry PyInstaller dla CLI Horreum.

`horreum/cli.py` używa importów WZGLĘDNYCH (`from . import db`) — poprawnych dla `python -m
horreum.cli` i console-scriptu `horreum.cli:main`, ale PyInstaller bierze skrypt entry jako goły
`__main__` BEZ kontekstu pakietu → relative import pada. Ten cienki launcher woła `main` importem
ABSOLUTNYM (jak `horreum/gui/__main__.py` dla GUI), nadając kontekst pakietu. Rdzeń nietknięty
(§0 briefu publikacji zamrożony)."""
import sys

from horreum.cli import main

if __name__ == "__main__":
    sys.exit(main())
