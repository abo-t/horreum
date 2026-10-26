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


# Szum SQL zdejmowany przed szukaniem czasownika: komentarze `--` i `/* */`, napisy `'...'` (z `''` w środku)
# oraz akcja klucza obcego `ON DELETE`/`ON UPDATE` w DDL (`REFERENCES x ON DELETE CASCADE` to nie zapis).
_SQL_SZUM = re.compile(r"--[^\n]*|/\*.*?(?:\*/|\Z)|'(?:[^']|'')*'?|\bON\s+(?:DELETE|UPDATE)\b",
                       re.DOTALL | re.IGNORECASE)
# `REPLACE(` to funkcja SQL (`SELECT replace(path, ...)`), nie zapis.
_SQL_CZASOWNIK = re.compile(r"\b(INSERT|UPDATE|DELETE|UPSERT|REPLACE(?!\s*\())\b", re.IGNORECASE)


def _czasowniki_sql(node):
    """Czasowniki DML WSZYSTKICH instrukcji literału SQL (UPPER, w kolejności) albo None, gdy arg nie jest
    literałem stringa. AR-328: czasownik to słowo w KAŻDEJ instrukcji po zdjęciu szumu, nie pierwszy token
    pierwszej linii - DML za `PRAGMA ...;`, prefiks CTE (`WITH x AS (...) DELETE`) i komentarz blokowy przed
    `DELETE` nie są ucieczką (sonda 2026-10-26: 889 literałów pakietu, werdykt bez zmian)."""
    if not _literal(node):
        return None
    return [m.group(1).upper() for m in _SQL_CZASOWNIK.finditer(_SQL_SZUM.sub(" ", node.value))]


def _exec_calls(tree):
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in EXEC_METHODS:
            arg0 = call.args[0] if call.args else None
            yield f.attr, arg0


def _naruszenia(name, tree):
    """Naruszenia jednej klingi w drzewie modułu `name` (nazwa pliku): DML w literale poza repo.py (poza
    sankcjonowanym wpisem dziennika migracji w db.py) i SQL dynamiczny poza repo.py/db.py. Osobna funkcja,
    żeby falsyfikator syntetyczny szedł tą samą drogą co pliki pakietu."""
    zle = []
    for method, arg0 in _exec_calls(tree):
        verbs = _czasowniki_sql(arg0)
        if verbs is None:
            # SQL dynamiczny (zmienna/f-string) - nieweryfikowalny. Dozwolony tylko w domach.
            if name not in (DOOR, INFRA):
                zle.append(f"{name}: {method}(<dynamiczny SQL>) poza repo.py/db.py")
        elif verbs and name != DOOR and not _dml_infra(name, arg0):
            zle.append(f"{name}: {method}('{verbs[0]} ...') poza repo.py")
    return zle


def test_brak_dml_domenowego_poza_repo():
    """Statyczny meta-tripwir: DML (INSERT/UPDATE/DELETE/REPLACE) tylko w repo.py; SQL dynamiczny
    tylko w repo.py/db.py. Gwarancja: żaden moduł nie zapisze do bazy z pominięciem warstwy repo
    (a więc z pominięciem emisji `event`)."""
    offenders = []
    for src in _py_files():
        offenders += _naruszenia(src.name, ast.parse(src.read_text(encoding="utf-8")))
    assert not offenders, f"zapis do bazy poza jedną klingą: {offenders}"


def test_klinga_istnieje_w_repo():
    """Pozytywna asercja zakresu: DML REALNIE występuje w repo.py (klinga istnieje i ma ostrze).
    Gdyby ktoś usunął zapisy z repo.py, warstwa byłaby martwa - ten test to złapie."""
    repo = PKG / "repo.py"
    tree = ast.parse(repo.read_text(encoding="utf-8"))
    verbs = {v for _, a in _exec_calls(tree) for v in (_czasowniki_sql(a) or ())}
    assert verbs & set(WRITE_VERBS), "repo.py nie zawiera żadnego INSERT/UPDATE/DELETE - klinga martwa"


def _dml_db(tree):
    """`(DML domenowy, wpisy dziennika migracji)` drzewa `db.py`: literały z czasownikiem DML poza
    sankcjonowanym wpisem oraz INSTRUKCJE `INSERT INTO migration_log` we wszystkich literałach (instrukcja
    za `;` też się liczy - liczba instrukcji, nie wywołań)."""
    bad = [vs[0] for _, a in _exec_calls(tree)
           if (vs := _czasowniki_sql(a)) and not _dml_infra(INFRA, a)]
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


@pytest.mark.parametrize("sql", [
    "PRAGMA foreign_keys = ON; DELETE FROM frame",
    "CREATE TABLE t(x); UPDATE frame SET kind = 'x'",
    "SELECT 1; -- k\nDELETE FROM frame",
    "WITH x AS (SELECT 1) DELETE FROM frame",
    "/* k */ DELETE FROM frame",
    "select 1;\n  insert or replace into frame (id) values (1)",
], ids=["dml_za_pragma", "dml_za_ddl", "dml_za_komentarzem_liniowym", "prefiks_cte", "komentarz_blokowy",
        "male_litery_w_drugiej_instrukcji"])
def test_bramka_modulu_lapie_dml_poza_pierwsza_instrukcja(sql):
    """AR-328: literał, którego pierwsza instrukcja nie jest zapisem, a dalsza (albo główna po CTE czy
    komentarzu) jest - bramka modułu spoza repo.py i bramka DML `db.py` łapią go tak samo jak gołe DELETE."""
    tree = ast.parse(f"con.executescript({sql!r})\n")
    assert _naruszenia("scan.py", tree), sql
    assert _dml_db(tree)[0], sql
    assert not _naruszenia(DOOR, tree)


@pytest.mark.parametrize("sql", [
    "SELECT replace(path, 'a', 'b') FROM location",
    "SELECT 'a;b' FROM location",
    "SELECT id FROM location WHERE note = 'DELETE FROM frame'",
    "SELECT id FROM frame -- DELETE FROM frame",
    "SELECT id /* DELETE FROM frame; */ FROM frame",
    "CREATE TABLE t (a INTEGER REFERENCES frame(id) ON DELETE CASCADE ON UPDATE NO ACTION)",
    "SELECT updated_at, deleted FROM location",
], ids=["funkcja_replace", "srednik_w_napisie", "dml_w_napisie", "dml_w_komentarzu", "dml_w_komentarzu_blokowym",
        "akcja_klucza_obcego", "slowa_z_przedrostkiem"])
def test_bramka_modulu_bez_falszywego_alarmu(sql):
    """Kontrola fałszywego alarmu tokenizera AR-328: funkcja `replace()`, napis i komentarz z tekstem DML,
    średnik w napisie, akcja klucza obcego w DDL i kolumny o nazwach z czasownikiem nie są zapisem."""
    tree = ast.parse(f"con.execute({sql!r})\n")
    assert not _naruszenia("scan.py", tree), sql
    assert not _dml_db(tree)[0], sql
