"""META-TRIPWIR (statyczny, AST) — jedna klinga zapisu domenowego (PLAN §2, §5.10).

Odpowiednik zakazu `os.rename` poza `mover.py` w Custosie, przełożony na ZAPIS DO BAZY:
żaden moduł pakietu `horreum` POZA `repo.py` nie wykonuje DML (INSERT/UPDATE/DELETE/REPLACE)
na bazie. `db.py` to drugi sankcjonowany dom — INFRA (DDL migracji + PRAGMA + dynamiczny
executescript), ale również BEZ DML domenowego (osobna asercja niżej).

AST, nie regex — by docstringi opisujące te operacje (jak ten) nie dawały fałszywych trafień.
Łapie SQL-literał z czasownikiem DML oraz SQL DYNAMICZNY (nie-literał) poza sankcjonowanymi
domami (dynamiczny = nieweryfikowalny → traktowany jak potencjalny zapis)."""
import ast
from pathlib import Path

import horreum

PKG = Path(horreum.__file__).parent

EXEC_METHODS = {"execute", "executemany", "executescript"}
WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "UPSERT")
DOOR = "repo.py"                      # jedyny dom DML domenowego (+ emisji event)
INFRA = "db.py"                       # drugi dom: DDL/PRAGMA/dynamiczny executescript, ZERO DML


def _py_files():
    return sorted(PKG.rglob("*.py"))


def _first_sql_verb(node):
    """Pierwszy token SQL z literału (pomijając wiodące białe znaki i komentarze '--').
    Zwraca UPPER token albo None gdy arg nie jest literałem stringa."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return None
    lines = []
    for raw in node.value.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("--"):
            lines.append(stripped)
    if not lines:
        return ""
    return lines[0].split(None, 1)[0].upper()


def _exec_calls(tree):
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in EXEC_METHODS:
            arg0 = call.args[0] if call.args else None
            yield f.attr, arg0


def test_brak_dml_domenowego_poza_repo():
    """Statyczny meta-tripwir: DML (INSERT/UPDATE/DELETE/REPLACE) tylko w repo.py; SQL dynamiczny
    tylko w repo.py/db.py. Gwarancja: żaden moduł nie zapisze do bazy z pominięciem warstwy repo
    (a więc z pominięciem emisji `event`)."""
    offenders = []
    for src in _py_files():
        name = src.name
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for method, arg0 in _exec_calls(tree):
            verb = _first_sql_verb(arg0)
            if verb is None:
                # SQL dynamiczny (zmienna/f-string) — nieweryfikowalny. Dozwolony tylko w domach.
                if name not in (DOOR, INFRA):
                    offenders.append(f"{name}: {method}(<dynamiczny SQL>) poza repo.py/db.py")
            elif verb in WRITE_VERBS and name != DOOR:
                offenders.append(f"{name}: {method}('{verb} ...') poza repo.py")
    assert not offenders, f"zapis do bazy poza jedną klingą: {offenders}"


def test_klinga_istnieje_w_repo():
    """Pozytywna asercja zakresu: DML REALNIE występuje w repo.py (klinga istnieje i ma ostrze).
    Gdyby ktoś usunął zapisy z repo.py, warstwa byłaby martwa — ten test to złapie."""
    repo = PKG / "repo.py"
    tree = ast.parse(repo.read_text(encoding="utf-8"))
    verbs = {_first_sql_verb(a) for _, a in _exec_calls(tree)}
    assert verbs & set(WRITE_VERBS), "repo.py nie zawiera żadnego INSERT/UPDATE/DELETE — klinga martwa"


def test_db_infra_bez_dml_domenowego():
    """db.py to INFRA: wolno DDL (CREATE) + PRAGMA + dynamiczny executescript migracji, ale ZERO
    DML domenowego. Strażnik, by infra nie stała się cichą furtką zapisu z pominięciem event."""
    db_src = PKG / "db.py"
    tree = ast.parse(db_src.read_text(encoding="utf-8"))
    bad = [v for _, a in _exec_calls(tree) if (v := _first_sql_verb(a)) in WRITE_VERBS]
    assert not bad, f"db.py zawiera DML domenowy (powinno być tylko DDL/PRAGMA): {bad}"
