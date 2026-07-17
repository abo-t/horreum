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
- negacja: {"op": "NOT", "conditions": [ <dokładnie 1 dziecko> ]} — `uniwersum − eval(dziecko)`
  (F1 redesignu, PLAN_ux_redesign §2). NOT z ≠1 dzieckiem → ValueError (EXPECT). Zagnieżdżenia
  legalne (NOT nad grupą, NOT(NOT(x)) == x). NOT(pusta-grupa) = ∅ — pusta grupa to uniwersum,
  różnica daje zbiór pusty (konsekwencja algebry, nie przypadek do łatania). Zero nowego SQL.
- facet:   {"facet": "object"|"filter"|"kind"|"telescope"|"night", "value": ..., "label": opc.} —
  liść RELACYJNY (F4, PLAN_ux_redesign §5): mapowany na `rel_*` w dispatchu `leaf_frame_ids`
  (object→object_id, filter→filter_canon, kind→kind, telescope→canon_id kanonicznego teleskopu,
  night→zakres na header.date_obs). `label` = CZYSTA prezentacja (describe); `_eval` ignoruje.
  Rozpoznawany PRZED warunkiem (nie ma `operator`) WŁASNĄ gałęzią — nigdy nie spada do
  `_eval_condition` (`validate_keyword` nie widzi None). Nieznany facet → ValueError (EXPECT).
  Noc: `[<D>T12:00:00, <D+1>T12:00:00)` — górna granica ZAWSZE pełnym datetime, nigdy `<=` z gołą
  datą [skill: sqlite-bare-date-upper-bound-trap]; NOT(noc) ZOSTAWIA klatki bez date_obs
  („nieznana data ≠ ta noc" — konsekwencja algebry, jak NOT(pusta-grupa)=∅).

Operatory: eq ne gt lt ge le contains startswith exists not_exists (regex POMINIĘTY w v1 — D-F).
- gt/lt/ge/le po `value_num`; keyword mieszany → wiersze bez `value_num` (NULL) wypadają same.
- eq/ne: bool → 'T'/'F'; operand liczbo-podobny trafia value_raw ORAZ value_num (pole tekstowe '800'
  i numeryczne 800 nie ginie); czysty tekst → value_raw. `ne` = EXISTS(karta ∧ value≠?) — NIE trafia
  klatek bez keyworda (parytet dawcy; UI dokumentuje, osobne „brak wartości" = not_exists).
- exists/not_exists po istnieniu karty. `not_exists` = UNIWERSUM − {frame z kartą} (uniwersum =
  WSZYSTKIE frame, w tym XISF bez cards i zniknięte — F1). `filter=None` → uniwersum.

`leaf_fn(kind, kw, p1, p2) -> set[int]` — jeden literał SELECT per `kind` w `gui/queries.py`.
`universe_fn() -> set[int]` — `SELECT id FROM frame` (wszystkie frame).

`describe(tree)` — drzewo → opis SŁOWAMI dla paska zbioru (F3, PLAN_ux_redesign §4). Czysta
prezentacja: mapa op→słowo mieszka tu (silnik = właściciel gramatyki, SPOT; etykiety combo
`OPERATORS` w grid.py to INNY fakt — glify UI). Nieznany op renderuje się surowo — fail-fast
dotyczy wykonania (`_eval` podnosi ValueError), nie formatera etykiety.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta

# Charset/długość keyworda FITS jak w dawcy (query._KW_RE, pivot._KW_RE): do 68 znaków, spacje/kropki
# odrzucane. Keyword i tak idzie do SELECT jako parametr `?`, ale walidacja defensywna odrzuca śmieci.
_KW_RE = re.compile(r"^[A-Za-z0-9_\-]{1,68}$")

_NUMERIC_KIND = {"gt": "num_gt", "lt": "num_lt", "ge": "num_ge", "le": "num_le"}

# Facet-liść (F4): facet → kind dispatcha `leaf_frame_ids` (rel_night osobno — dwa parametry-granice).
_FACET_KIND = {"object": "rel_object", "filter": "rel_filter", "kind": "rel_kind",
               "telescope": "rel_telescope"}
_NIGHT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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


def _is_facet(node: dict) -> bool:
    return "facet" in node


def night_bounds(night) -> "tuple[str, str]":
    """Granice nocy D (D-UX-1: noc = date(DATE-OBS − 12 h)) jako PEŁNE datetime:
    `[<D>T12:00:00, <D+1>T12:00:00)`. Walidacja formatu (EXPECT) — zła data → ValueError."""
    if not isinstance(night, str) or not _NIGHT_RE.match(night):
        raise ValueError(f"niedozwolona noc (oczekiwane YYYY-MM-DD): {night!r}")
    nxt = (date.fromisoformat(night) + timedelta(days=1)).isoformat()
    return f"{night}T12:00:00", f"{nxt}T12:00:00"


def _eval_facet(node: dict, leaf_fn: LeafFn) -> set[int]:
    facet = node["facet"]
    value = node.get("value")
    if facet == "night":
        p1, p2 = night_bounds(value)
        return leaf_fn("rel_night", None, p1, p2)
    kind = _FACET_KIND.get(facet)
    if kind is None:
        raise ValueError(f"nieznany facet: {facet!r}")
    return leaf_fn(kind, None, value, None)


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
    if _is_facet(node):                       # PRZED warunkiem: facet-liść nie ma `operator` (F4)
        return _eval_facet(node, leaf_fn)
    if _is_condition(node):
        return _eval_condition(node, leaf_fn, universe_fn)
    op = str(node.get("op", "AND")).upper()
    if op == "NOT":
        children = node.get("conditions", [])
        if len(children) != 1:
            raise ValueError(f"NOT wymaga dokładnie 1 dziecka, dostał {len(children)}")
        return universe_fn() - _eval(children[0], leaf_fn, universe_fn)
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


# Mapa op→słowo dla `describe` (exists/not_exists mają własne frazy „ma KW"/„bez KW").
_OP_WORDS = {"eq": "=", "ne": "≠", "gt": ">", "lt": "<", "ge": "≥", "le": "≤",
             "contains": "zawiera", "startswith": "zaczyna się od"}

# Mapa facet→nazwa PL dla `describe` (prezentacja facet-liścia: „Obiekt: NGC7000").
_FACET_WORDS = {"object": "Obiekt", "filter": "Filtr", "kind": "Rodzaj",
                "telescope": "Teleskop", "night": "Noc"}


def _describe_value(value) -> str:
    if isinstance(value, bool):
        return "T" if value else "F"   # parytet semantyki eq (bool → 'T'/'F')
    return str(value)


def describe(tree: dict | None, *, _nested: bool = False) -> str:
    """Drzewo filtra → opis słowami: „EXPTIME = 300 i (FILTER zawiera Ha lub bez FILTER)";
    NOT → „poza (…)"; `None`/pusta grupa → „wszystkie klatki". Grupa zagnieżdżona o >1 dzieciach
    dostaje nawiasy; korzeń idzie bez nich."""
    if tree is None:
        return "wszystkie klatki"
    if _is_facet(tree):
        # PRZED fallbackiem grupy (F4R#7): facet-liść bez `operator`/`conditions` wpadłby w
        # „pusta grupa → wszystkie klatki" = cichy fałsz na pasku zbioru.
        name = _FACET_WORDS.get(tree["facet"], str(tree["facet"]))
        return f"{name}: {tree.get('label') or tree.get('value')}"
    if _is_condition(tree):
        kw = tree.get("keyword")
        op = tree.get("operator")
        if op == "exists":
            return f"ma {kw}"
        if op == "not_exists":
            return f"bez {kw}"
        return f"{kw} {_OP_WORDS.get(op, str(op))} {_describe_value(tree.get('value'))}"
    op = str(tree.get("op", "AND")).upper()
    children = tree.get("conditions", [])
    if op == "NOT":
        # ≠1 dziecko to drzewo, które `_eval` i tak odrzuci — opis renderuje co jest (prezentacja).
        inner = " i ".join(describe(c) for c in children)
        return f"poza ({inner})"
    if not children:
        return "wszystkie klatki"
    text = (" i " if op == "AND" else " lub ").join(describe(c, _nested=True) for c in children)
    return f"({text})" if _nested and len(children) > 1 else text
