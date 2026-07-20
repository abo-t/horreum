"""Horreum — menedżer biblioteki astrofoto deep-sky.

Baza = autorytet, pliki = append-only zimny magazyn, sha1 = tożsamość.
Zapis domenowy WYŁĄCZNIE przez `horreum.repo` (jedna klinga → event); pilnuje tego
statyczny meta-tripwir AST (`tests/test_repo_safety.py`) od commitu zero.
"""

__version__ = "0.3.2"
