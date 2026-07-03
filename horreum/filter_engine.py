"""Silnik filtra: drzewo predykatów → zbiór `frame_id` przez ALGEBRĘ ZBIORÓW (PLAN_gui_grid §3).

PARYTET SEMANTYKI z dawcą `fitsmirror/core/query.py`, ale INNY mechanizm wykonania: dawca składał
jeden dynamiczny `WHERE`; tu każdy predykat-liść to OSOBNY literał SELECT (w `gui/queries.py`), a
drzewo AND/OR łączymy w Pythonie (∩ dla AND, ∪ dla OR). Dzięki temu ZERO dynamicznego SQL — bramka
„jedna klinga" (`test_repo_safety.py`) czysta, cały silnik Qt-wolny. Ten moduł NIE dotyka DB (ZERO
`execute` — root-moduł objęty meta-testem AST): rozwiązanie liścia i uniwersum wstrzykiwane jako
`leaf_fn`/`universe_fn` (z `gui/queries.py`), więc silnik jest testowalny w izolacji.

Drzewo (JSON-serializowalne):
- warunek: {"keyword": str, "operator": str, "value": ...}
- grupa:   {"op": "AND"|"OR", "conditions": [ <warunek|grupa> ]}

Operatory: eq ne gt lt ge le contains startswith exists not_exists (regex POMINIĘTY w v1 — D-F).
- gt/lt/ge/le po `value_num`; keyword mieszany → wiersze bez `value_num` (NULL) wypadają same.
- eq/ne: bool → 'T'/'F'; operand liczbo-podobny trafia value_raw ORAZ value_num (pole tekstowe '800'
  i numeryczne 800 nie ginie); czysty tekst → value_raw. `ne` = EXISTS(karta ∧ value≠?) — NIE trafia
  klatek bez keyworda (parytet dawcy; UI dokumentuje, osobne „brak wartości" = not_exists).
- exists/not_exists po istnieniu karty. `not_exists` = UNIWERSUM − {frame z kartą} (uniwersum =
  WSZYSTKIE frame, w tym XISF bez cards i zniknięte — F1). `filter=None` → uniwersum.

`leaf_fn(kind, kw, p1, p2) -> set[int]` — jeden literał SELECT per `kind` w `gui/queries.py`.
`universe_fn() -> set[int]` — `SELECT id FROM frame` (wszystkie frame).
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Charset/długość keyworda FITS jak w dawcy (query._KW_RE, pivot._KW_RE): do 68 znaków, spacje/kropki
# odrzucane. Keyword i tak idzie do SELECT jako parametr `?`, ale walidacja defensywna odrzuca śmieci.
_KW_RE = re.compile(r"^[A-Za-z0-9_\-]{1,68}$")

_NUMERIC_KIND = {"gt": "num_gt", "lt": "num_lt", "ge": "num_ge", "le": "num_le"}

LeafFn = Callable[[str, str, object, object], "set[int]"]
UniverseFn = Callable[[], "set[int]"]


def validate_keyword(name) -> str:
    if not isinstance(name, str) or not _KW_RE.match(name):
        raise ValueError(f"niedozwolony keyword: {name!r}")
    return name


def _as_number(value) -> float | None:
    """Operand jako float, gdy liczba LUB tekst parsowalny liczbowo; inaczej None. Bool NIE jest liczbą."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_condition(node: dict) -> bool:
    return "operator" in node


def _eval_condition(node: dict, leaf_fn: LeafFn, universe_fn: UniverseFn) -> set[int]:
    kw = validate_keyword(node["keyword"])
    op = node["operator"]
    value = node.get("value")

    if op == "exists":
        return leaf_fn("exists", kw, None, None)
    if op == "not_exists":
        return universe_fn() - leaf_fn("exists", kw, None, None)
    if op in _NUMERIC_KIND:
        return leaf_fn(_NUMERIC_KIND[op], kw, float(value), None)
    if op in ("eq", "ne"):
        if isinstance(value, bool):
            return leaf_fn("eq_raw" if op == "eq" else "ne_raw", kw, "T" if value else "F", None)
        text = str(value)
        num = _as_number(value)
        if num is None:  # operand czysto tekstowy → tylko value_raw
            return leaf_fn("eq_raw" if op == "eq" else "ne_raw", kw, text, None)
        # Operand liczbo-podobny: trafiaj kartę TEKSTOWĄ (value_raw='800') i NUMERYCZNĄ (value_num=800).
        return leaf_fn("eq_rawnum" if op == "eq" else "ne_rawnum", kw, text, num)
    if op == "contains":
        return leaf_fn("like", kw, "%" + _like_escape(str(value)) + "%", None)
    if op == "startswith":
        return leaf_fn("like", kw, _like_escape(str(value)) + "%", None)
    if op == "regex":
        raise ValueError("operator regex pominięty w v1 (D-F) — użyj contains/startswith")
    raise ValueError(f"nieznany operator: {op!r}")


def _eval(node: dict, leaf_fn: LeafFn, universe_fn: UniverseFn) -> set[int]:
    if _is_condition(node):
        return _eval_condition(node, leaf_fn, universe_fn)
    op = str(node.get("op", "AND")).upper()
    if op not in ("AND", "OR"):
        raise ValueError(f"nieznana grupa: {op!r}")
    children = node.get("conditions", [])
    if not children:
        return universe_fn()  # pusta grupa → WSZYSTKO (parytet dawcy `build_where` → '1', F6)
    sets = [_eval(child, leaf_fn, universe_fn) for child in children]
    result = sets[0]
    for s in sets[1:]:
        result = result & s if op == "AND" else result | s
    return result


def run(filter_tree: dict | None, *, leaf_fn: LeafFn, universe_fn: UniverseFn) -> set[int]:
    """Wykonuje filtr → zbiór frame_id. `None`/pusty filtr → uniwersum (wszystkie frame)."""
    if filter_tree is None:
        return universe_fn()
    return _eval(filter_tree, leaf_fn, universe_fn)
