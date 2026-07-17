"""Model stanu listwy facetów + SKŁADACZ drzewa (F4, PLAN_ux_redesign §5). Qt-WOLNY — wzorzec
`queries`/`progress` (testowalny bez PySide6; egzekwuje rglob `test_gui_isolation` + jawna asercja).

Stan = JSON-serializowalny dict `{facet: {"in": [[value,label]…], "ex": [[value,label]…]}}` —
serializowany w perspektywie OSOBNO od drzewa panelu zaawansowanego (nota R2: złożone drzewo nigdy
nie idzie w płaski `FilterPanel.set_tree`). Puste grupy są USUWANE ze stanu (normalizacja — pusty
stan to `{}`, `sibling_state` i porównania trywialne).

Interakcja = CYKL na wartości: none→in→ex→none (`cycle`). Składanie (`compose`):
`AND( OR(in-wartości facetu)…, NOT(ex-wartość)…, drzewo-zaawansowane )` — OR WEWNĄTRZ facetu
(frame ma DOKŁADNIE jeden object_id/kind/noc; AND dwóch wartości = zawsze ∅ = UI kłamałoby ∅-em),
AND między facetami (zawężanie), wykluczenie = NOT per wartość (≡ NOT(OR(…)) przez De Morgana;
per-wartość czytelniejsze w `describe`). Advanced doklejane jako OSTATNIE dziecko, NIEPRZEZROCZYSTE.

`sibling_state(state, facet)` = stan bez CAŁEJ grupy facetu (in+ex) — zbiór bazowy LICZNIKÓW tego
facetu (F4R#1: liczniki na w pełni złożonym zbiorze samo-zawężają facet i OR-wewnątrz byłby
nieosiągalny; dla facetu bez aktywnego wyboru sibling == stan pełny, D-UX-3(a) zachowana).
"""

from __future__ import annotations

# Stała kolejność facetów: deterministyczne drzewo (testy, describe) i kolejność grup w listwie.
FACETS = ("object", "filter", "kind", "telescope", "night")


def empty_state() -> dict:
    return {}


def _find(entries, value):
    return next((i for i, (v, _l) in enumerate(entries) if v == value), None)


def selection(state: dict, facet: str, value) -> str | None:
    """Stan wartości w facecie: 'in' | 'ex' | None."""
    grp = state.get(facet) or {}
    if _find(grp.get("in") or [], value) is not None:
        return "in"
    if _find(grp.get("ex") or [], value) is not None:
        return "ex"
    return None


def cycle(state: dict, facet: str, value, label=None) -> dict:
    """NOWY stan po kliku wartości: none→in→ex→none. Nie mutuje wejścia (stan trzyma FramesView;
    widżet emituje wynik). Nieznany facet → ValueError (EXPECT)."""
    if facet not in FACETS:
        raise ValueError(f"nieznany facet: {facet!r}")
    out = {f: {k: [list(e) for e in v] for k, v in g.items()} for f, g in state.items()}
    grp = out.setdefault(facet, {})
    ins, exs = grp.setdefault("in", []), grp.setdefault("ex", [])
    i = _find(ins, value)
    if i is not None:
        exs.append(ins.pop(i))          # in → ex (zachowaj label z wyboru)
    else:
        j = _find(exs, value)
        if j is not None:
            exs.pop(j)                  # ex → none
        else:
            ins.append([value, label])  # none → in
    # normalizacja: puste listy i puste grupy znikają (pusty stan == {})
    for k in ("in", "ex"):
        if not grp[k]:
            del grp[k]
    if not grp:
        del out[facet]
    return out


def sibling_state(state: dict, facet: str) -> dict:
    """Stan bez CAŁEJ grupy facetu (in+ex) — baza liczników tego facetu (F4R#1)."""
    return {f: g for f, g in state.items() if f != facet}


def compose(state: dict, advanced) -> dict | None:
    """Stan facetów + drzewo zaawansowane → JEDNO drzewo dla `filter_engine.run` (SPOT — zero drugiej
    ścieżki filtrowania). Pusty stan → samo advanced (albo None); jedno dziecko → bez opakowania AND."""
    conds = []
    for facet in FACETS:
        grp = state.get(facet) or {}
        leaves = [{"facet": facet, "value": v, "label": l} for v, l in (grp.get("in") or [])]
        if len(leaves) == 1:
            conds.append(leaves[0])
        elif leaves:
            conds.append({"op": "OR", "conditions": leaves})
        for v, l in (grp.get("ex") or []):
            conds.append({"op": "NOT", "conditions": [{"facet": facet, "value": v, "label": l}]})
    if advanced is not None:
        conds.append(advanced)
    if not conds:
        return None
    if len(conds) == 1:
        return conds[0]
    return {"op": "AND", "conditions": conds}
