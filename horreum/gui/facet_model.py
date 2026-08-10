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

# Jedyny import rdzenia w tym module — i celowy: szukajka MUSI liczyć igłę tą samą
# normalizacją, którą przebieg liczy klucze równoważności (`search_hit`). Moduł
# zostaje Qt-wolny, więc bramka izolacji §7.2 się nie rusza.
from horreum.resolve._text import norm_alnum

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


def toggle_exclude(state: dict, facet: str, value, label=None) -> dict:
    """NOWY stan po WYKLUCZENIU wprost: none/in → ex, ex → none (skrót prawego klika listwy).

    Nie zastępuje `cycle`, tylko skraca do niego drogę: „pokaż wszystko OPRÓCZ tego" kosztowało dwa
    kliki przez stan `in`, a między nimi zbiór zwężał się do JEDNEJ wartości i listwa przeliczała
    liczniki na zbiorze, którego user nigdy nie chciał zobaczyć. Idempotencja jest tu WŁASNOŚCIĄ,
    nie efektem ubocznym: powtórny prawy klik zdejmuje wykluczenie, więc gest ma drogę powrotną.
    Wynik przechodzi przez `cycle`, więc normalizacja pustych grup ma JEDNEGO właściciela (SPOT)."""
    sel = selection(state, facet, value)
    if sel == "ex":
        return cycle(state, facet, value, label)              # ex → none
    if sel == "in":
        return cycle(state, facet, value, label)              # in → ex
    return cycle(cycle(state, facet, value, label), facet, value, label)   # none → in → ex


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


# Trafienie BEZ aliasu — wiersz pasuje własną nazwą albo igła jest pusta. Sentinel, a nie `True`,
# bo wołający rozróżnia trzy stany, nie dwa: „nie pasuje" (chowaj), „pasuje sobą" (pokaż) i „pasuje
# CUDZĄ nazwą" (pokaż i powiedz, którą). Pusty string byłby falsy i skasowałby to rozróżnienie
# przy pierwszym `if hit:` napisanym z rozpędu.
HIT_LABEL = "__label__"


def search_hit(needle: str, label, aliases=None):
    """CZYM wiersz facetu „Obiekt" trafił igłę szukajki — `None` (nie trafił), `HIT_LABEL` (własną
    nazwą) albo znormalizowany ALIAS, którym trafił. S3, obietnica §1 („szukanie po nazwach").

    DO R-S3-9 FUNKCJA ZWRACAŁA `bool` I TO BYŁ CAŁY DEFEKT: wpisujesz „Large Magellanic Cloud",
    dostajesz wiersz `LMC` i nie masz jak się dowiedzieć, dlaczego pasuje — kanon nie ma z tą frazą
    ani jednej wspólnej litery. Predykat wiedział to w chwili dopasowania i wyrzucał.

    Alias wraca w formie ZNORMALIZOWANEJ, bo tylko taka istnieje: `object_alias` przechowuje
    `alias_norm` z chwili zapisu, surowego brzmienia baza nie zna. Dla tooltipa to wystarcza —
    user rozpoznaje własną frazę — a udawanie, że mamy oryginał, byłoby zmyślaniem.

    Trzy fakty w jednym predykacie, i każdy z nich sam by nie wystarczył:

    * **NORMALIZACJA `norm_alnum`** — ta sama, którą przebieg liczy klucze równoważności. Bez niej
      szukajka porównywała surowy tekst do surowej etykiety, więc `M 42` nie znajdowało `M42`,
      a `sh2 155` nie znajdowało `Sh2-155`: user wpisuje nazwę tak, jak ją mówi, a kanon zapisany
      jest tak, jak go dyktuje gramatyka katalogu. Igła i siano MUSZĄ przejść tę samą bramkę.
    * **ALIASY** — kanon `LMC` nie zawiera w sobie ani jednej litery z „Large Magellanic Cloud".
      Nazwa potoczna żyje w `object_alias`, więc bez mapy `canon → {alias_norm}` szukajka jest ślepa
      dokładnie na tę klasę obiektów, dla której powstała cała ta paczka (obiekty własne).
    * **PUSTA IGŁA PASUJE ZAWSZE** — wołający chowa wiersz dopiero po `None`, a „nic nie wpisano"
      nie jest pytaniem.

    Predykat mieszka TU, nie w listwie: `FacetRail` jest głupim widżetem (NARROW), a to jest logika
    — z normalizacją rdzenia i regułą, którą trzeba móc przetestować bez Qt.

    `aliases` = dict `canon → set(alias_norm)`; brak wpisu (albo brak mapy) znaczy „ten obiekt nie
    ma innych nazw", nigdy „nie wiadomo".

    PIERWSZEŃSTWO MA WŁASNA NAZWA: wiersz, który trafia sobą, nie tłumaczy się cudzą nazwą, nawet
    gdy jakiś alias też by pasował. Alias wybieramy DETERMINISTYCZNIE (`sorted`) — zbiór nie ma
    kolejności, a tooltip skaczący między przebiegami byłby własną usterką.
    """
    igla = norm_alnum(needle or "")
    if not igla:
        return HIT_LABEL
    if igla in norm_alnum(str(label)):
        return HIT_LABEL
    return next((a for a in sorted((aliases or {}).get(str(label), ())) if igla in a), None)
