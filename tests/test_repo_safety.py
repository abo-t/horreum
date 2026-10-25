"""META-TRIPWIR (statyczny, AST) - jedna klinga zapisu domenowego (PLAN §2, §5.10).

Odpowiednik zakazu `os.rename` poza `mover.py` w Custosie, przełożony na ZAPIS DO BAZY:
żaden moduł pakietu `horreum` POZA `repo.py` nie wykonuje DML (INSERT/UPDATE/DELETE/REPLACE)
na bazie. `db.py` to drugi sankcjonowany dom - INFRA (DDL migracji + PRAGMA + dynamiczny
executescript), ale również BEZ DML domenowego (osobna asercja niżej).

AST, nie regex - by docstringi opisujące te operacje (jak ten) nie dawały fałszywych trafień.
Łapie SQL-literał z czasownikiem DML oraz SQL DYNAMICZNY (nie-literał) poza sankcjonowanymi
domami (dynamiczny = nieweryfikowalny → traktowany jak potencjalny zapis)."""
import ast
import re
from pathlib import Path

import pytest

import horreum

PKG = Path(horreum.__file__).parent

EXEC_METHODS = {"execute", "executemany", "executescript"}
WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "UPSERT")
DOOR = "repo.py"                      # jedyny dom DML domenowego (+ emisji event)
INFRA = "db.py"                       # drugi dom: DDL/PRAGMA/dynamiczny executescript, ZERO DML
# JEDYNY DML infrastruktury (AR-320): wiersz dziennika migracji (`migration_log`, 0047) - jak `user_version`
# należy do migracji, wchodzi w jej transakcji (`db._apply_migration`) i nie jest zapisem domenowym (bez
# `event`, `0047_migration_log.sql`). Wyjątek wąski: wyłącznie `db.py`, wyłącznie ta tabela (nazwa dokładna,
# z granicą słowa), jedna instrukcja w literale, dokładnie jedna taka instrukcja w module.
DML_INFRA = re.compile(r"INSERT\s+INTO\s+migration_log\b", re.IGNORECASE)


def _literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _instrukcje(sql):
    """Instrukcje literału SQL: części między `;`, bez pustych (średnik w cudzysłowie SQL też tnie -
    bramka za ostra, nie za lekka)."""
    return [s.strip() for s in sql.split(";") if s.strip()]


def _dml_infra(name, node):
    """Czy wywołanie to sankcjonowany wpis dziennika migracji: literał w `db.py` z JEDNĄ instrukcją
    (brak `;` z dalszą treścią) `INSERT INTO migration_log` (dokładna nazwa tabeli)."""
    return (name == INFRA and _literal(node) and len(_instrukcje(node.value)) == 1
            and DML_INFRA.match(node.value.strip()) is not None)


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
                # SQL dynamiczny (zmienna/f-string) - nieweryfikowalny. Dozwolony tylko w domach.
                if name not in (DOOR, INFRA):
                    offenders.append(f"{name}: {method}(<dynamiczny SQL>) poza repo.py/db.py")
            elif verb in WRITE_VERBS and name != DOOR and not _dml_infra(name, arg0):
                offenders.append(f"{name}: {method}('{verb} ...') poza repo.py")
    assert not offenders, f"zapis do bazy poza jedną klingą: {offenders}"


def test_klinga_istnieje_w_repo():
    """Pozytywna asercja zakresu: DML REALNIE występuje w repo.py (klinga istnieje i ma ostrze).
    Gdyby ktoś usunął zapisy z repo.py, warstwa byłaby martwa - ten test to złapie."""
    repo = PKG / "repo.py"
    tree = ast.parse(repo.read_text(encoding="utf-8"))
    verbs = {_first_sql_verb(a) for _, a in _exec_calls(tree)}
    assert verbs & set(WRITE_VERBS), "repo.py nie zawiera żadnego INSERT/UPDATE/DELETE - klinga martwa"


def _dml_db(tree):
    """`(DML domenowy, wpisy dziennika migracji)` drzewa `db.py`: literały z czasownikiem DML poza
    sankcjonowanym wpisem oraz INSTRUKCJE `INSERT INTO migration_log` we wszystkich literałach (instrukcja
    za `;` też się liczy - liczba instrukcji, nie wywołań)."""
    bad = [v for _, a in _exec_calls(tree)
           if (v := _first_sql_verb(a)) in WRITE_VERBS and not _dml_infra(INFRA, a)]
    wpisy = [s for _, a in _exec_calls(tree) if _literal(a)
             for s in _instrukcje(a.value) if DML_INFRA.match(s)]
    return bad, wpisy


def _dynamiczny_db(tree):
    """Wywołania `db.py` z f-stringiem SQL, którego części stałe niosą czasownik DML (tokeny słów, więc
    `BEGIN;DELETE` też), albo z SQL-em, który nie jest ani literałem, ani f-stringiem."""
    zle = []
    for method, arg0 in _exec_calls(tree):
        if isinstance(arg0, ast.JoinedStr):
            stale = " ".join(c.value for c in arg0.values if _literal(c))
            slowa = {s.upper() for s in re.findall(r"[A-Za-z_]+", stale)}
            if slowa & set(WRITE_VERBS):
                zle.append(f"{method}(f'...{sorted(slowa & set(WRITE_VERBS))}...')")
        elif not _literal(arg0):
            zle.append(f"{method}(<{type(arg0).__name__}>)")
    return zle


def test_db_infra_bez_dml_domenowego():
    """db.py to INFRA: wolno DDL (CREATE) + PRAGMA + dynamiczny executescript migracji, ale ZERO
    DML domenowego. Strażnik, by infra nie stała się cichą furtką zapisu z pominięciem event."""
    bad, wpisy = _dml_db(ast.parse((PKG / INFRA).read_text(encoding="utf-8")))
    assert not bad, f"db.py zawiera DML domenowy (powinno być tylko DDL/PRAGMA): {bad}"
    assert len(wpisy) == 1, f"wpis dziennika migracji w db.py ma stać instrukcją dokładnie raz: {wpisy}"


def test_db_dynamiczny_sql_bez_dml():
    """f-string SQL w `db.py` (skrypt migracji, `PRAGMA user_version`) nie niesie DML w częściach stałych -
    DML sklejony w f-stringu byłby dla obu bramek literałów niewidoczny (AR-320: wpis dziennika jechał tak
    w skrypcie `executescript`). Zmienna przekazana jako SQL w `db.py` - też odmowa: nie da się jej obejrzeć."""
    zle = _dynamiczny_db(ast.parse((PKG / INFRA).read_text(encoding="utf-8")))
    assert not zle, f"db.py: SQL dynamiczny z DML albo nieczytelny: {zle}"


_WPIS = 'con.execute("INSERT INTO migration_log (version, applied_at) SELECT value, 1 FROM json_each(?)", x)\n'


@pytest.mark.parametrize("zrodlo, bramka", [
    ('con.execute("INSERT INTO migration_log_other (version, applied_at) VALUES (?, ?)", x)\n', "dml"),
    ('con.executescript("INSERT INTO migration_log (version, applied_at) VALUES (1, 2); '
     'DELETE FROM frame;")\n', "dml"),
    (_WPIS + 'con.executescript("PRAGMA foreign_keys = ON; INSERT INTO migration_log (version) VALUES (9)")\n',
     "wpisy"),
    (_WPIS + 'con.executescript(f"BEGIN;DELETE FROM frame WHERE id = {n}")\n', "dynamiczny"),
], ids=["tabela_z_przedrostkiem", "druga_instrukcja_po_sredniku", "drugi_wpis_za_srednikiem",
        "fstring_bez_spacji_po_sredniku"])
def test_bramki_db_lapia_obejscia(zrodlo, bramka):
    """Źródło syntetyczne `db.py` z obejściem wąskiego wyjątku: tabela o nazwie z przedrostkiem
    `migration_log`, DML za `;` w literale wpisu, drugi wpis dziennika za `;` w literale bez DML na
    początku, DML w f-stringu sklejony ze średnikiem - każde łapie wskazana bramka; wzorcowy wpis sam
    przechodzi wszystkie trzy."""
    bad, wpisy = _dml_db(ast.parse(_WPIS))
    assert (bad, len(wpisy), _dynamiczny_db(ast.parse(_WPIS))) == ([], 1, [])
    tree = ast.parse(zrodlo)
    bad, wpisy = _dml_db(tree)
    wynik = {"dml": bool(bad), "wpisy": len(wpisy) != 1, "dynamiczny": bool(_dynamiczny_db(tree))}
    assert wynik[bramka], (bramka, bad, wpisy)
