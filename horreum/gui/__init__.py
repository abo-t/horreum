"""Warstwa GUI Horreum (oś usera) — IZOLOWANA od rdzenia (PLAN_gui §4).

PySide6 to optional extra `[gui]`; rdzeń (`db/repo/scan/grouper/resolver/...`) NIE importuje
gui, a `horreum/__init__.py` NIE ściąga tego pakietu — cały rdzeń + jego testy działają bez
zainstalowanego Qt. Ten plik celowo PUSTY (sam import `horreum.gui.queries` nie może wciągać Qt).

Read path (odczyt) = `queries.py` (czyste funkcje `con → list[Row]`, testowalne bez Qt).
Write path (zapis) = WYŁĄCZNIE funkcje z `horreum.repo` (jedna klinga → event); GUI nie dotyka
SQL zapisu (pilnuje tego meta-tripwir AST `tests/test_repo_safety.py`, skanujący też ten pakiet).
"""
