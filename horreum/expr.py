"""Bezpieczny ewaluator wyrazen (AST, biala lista wezlow) — modul gleboki.

Zmienne = wartosci keywordow danego pliku (plus nazwane wyniki krokow `compute`).
Dozwolone: arytmetyka (+ - * / // %), unarne +/-, oraz funkcje round/abs/min/max/
int/float/str/len. NIGDY eval()/exec(): parsujemy `ast` w trybie 'eval', chodzimy po
drzewie i wpuszczamy wylacznie wezly z bialej listy. Wyrazenie z niedozwolonym wezlem
(atrybut, indeks, lambda, walrus, wywolanie spoza whitelisty...) -> `ExprError` JUZ przy
kompilacji.

Brak operandu (keyword bez karty / puste `value_num`) i blad obliczenia (dzielenie przez
zero, typ) NIE wysadzaja potoku makra: `eval_for` zwraca `EvalResult(ok=False, reason=...)`,
a makro pomija taki plik z powodem. Operand `0` to WARTOSC, nie brak (sprawdzamy
`is None`, nie `if value`).

Pow (`**`) celowo poza biala lista — `10**10**10` to tani atak na pamiec/CPU, a przyklady
Fazy 1 go nie potrzebuja.

Przyklad A: new = FOCALLEN / FOCRATIO ; round(new, 2)
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass

# Funkcje wpuszczone do wyrazen. Nazwy sa malymi literami — keywordy FITS sa wielkimi
# (<=8 znakow), wiec nie ma kolizji `min` (funkcja) vs `MIN` (keyword).
_ALLOWED_FUNCS = {
    "round": round,
    "abs": abs,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
    "str": str,
    "len": len,
}

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Wezly strukturalne dozwolone "przezroczyscie" (bez wlasnej obslugi w walidacji).
_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    *_BINOPS.keys(),
    *_UNARYOPS.keys(),
)


class ExprError(Exception):
    """Wyrazenie odrzucone przy kompilacji (niedozwolony element / skladnia)."""


class _MissingOperand(Exception):
    """Odwolanie do keyworda bez wartosci (brak karty / puste value_num)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass(frozen=True)
class Expr:
    text: str
    node: ast.Expression
    names: frozenset[str]  # zmienne (keywordy / wyniki compute), bez nazw funkcji


@dataclass(frozen=True)
class EvalResult:
    ok: bool
    value: object  # wynik gdy ok; None gdy pominiety
    reason: str | None  # powod pominiecia gdy not ok
    # True gdy powodem jest ODWOLANIE DO NIEISTNIEJACEJ NAZWY (brak operandu). Makro uzywa
    # tego, by odroznic "to nie bylo wyrazenie, tylko literal tekstowy" (np. assign 'RC8')
    # od realnego bledu obliczenia (dzielenie przez zero, typ) — literal fallback tylko dla
    # braku operandu, nie dla zepsutej arytmetyki.
    missing_operand: bool = False


def _validate(tree: ast.Expression) -> set[str]:
    """Chodzi po drzewie, odrzuca wezly spoza bialej listy, zwraca zbior nazw zmiennych."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str, bool)):
                raise ExprError(f"niedozwolona stala: {node.value!r}")
        elif isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load):
                raise ExprError("przypisanie w wyrazeniu niedozwolone")
            if node.id not in _ALLOWED_FUNCS:  # nazwa funkcji to nie zmienna z env
                names.add(node.id)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise ExprError("dozwolone tylko wywolania z bialej listy funkcji")
            if node.keywords:
                raise ExprError("argumenty nazwane niedozwolone")
            if any(isinstance(a, ast.Starred) for a in node.args):
                raise ExprError("rozpakowanie argumentow niedozwolone")
        elif not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"niedozwolony element wyrazenia: {type(node).__name__}")
    return names


def compile_expr(text: str) -> Expr:
    """Parsuje i waliduje wyrazenie. Rzuca `ExprError` dla niedozwolonej skladni/wezla."""
    if not isinstance(text, str) or not text.strip():
        raise ExprError("puste wyrazenie")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"blad skladni: {exc}") from exc
    names = _validate(tree)
    return Expr(text=text, node=tree, names=frozenset(names))


def _eval(node: ast.AST, env: dict[str, object]) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        # is None = brak operandu; 0 / "" to WARTOSCI (nie sprawdzamy `if value`).
        if node.id not in env or env[node.id] is None:
            raise _MissingOperand(node.id)
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        return _UNARYOPS[type(node.op)](_eval(node.operand, env))
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Call):
        func = _ALLOWED_FUNCS[node.func.id]  # type: ignore[attr-defined]  # walidacja gwarantuje Name
        return func(*[_eval(a, env) for a in node.args])
    raise ExprError(f"niedozwolony element wyrazenia: {type(node).__name__}")


def eval_for(expr: Expr, env: dict[str, object]) -> EvalResult:
    """Liczy wyrazenie w srodowisku `env` (nazwa -> wartosc). Brak operandu / blad ->
    `EvalResult(ok=False, reason=...)`, nigdy wyjatek wysadzajacy potok."""
    try:
        value = _eval(expr.node.body, env)
    except _MissingOperand as exc:
        return EvalResult(
            ok=False, value=None, reason=f"brak operandu: {exc.name}", missing_operand=True
        )
    except ZeroDivisionError:
        return EvalResult(ok=False, value=None, reason="dzielenie przez zero")
    except ExprError as exc:
        return EvalResult(ok=False, value=None, reason=str(exc))
    except (TypeError, ValueError, OverflowError) as exc:
        return EvalResult(ok=False, value=None, reason=f"{type(exc).__name__}: {exc}")
    return EvalResult(ok=True, value=value, reason=None)
