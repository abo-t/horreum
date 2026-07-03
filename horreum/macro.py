"""Silnik makr — potok: (frame widoczne w gridzie) → oblicz → przypisz → PODGLĄD stagingu.

Port rdzenia dawcy fitsmirror (`core/macro.py`) na model Horreum (frame 1:N location). RÓŻNICA
KLUCZOWA: dawca kluczował plik (`file_id`); Horreum celuje w LOCATION (fizyczny plik — writeback
rusza bajty JEDNEJ kopii, tożsamość `sha1_data` frame'a przeżywa). Cel = OBECNA (`present=1`)
location frame'a.

Ten moduł jest CZYSTYM SILNIKIEM (wzorzec `filter_engine`): ZERO DB, ZERO Qt, ZERO importu gui.
Dane wchodzą przez WSTRZYKIWANE akcesory (`targets_fn`/`cards_fn` z `gui/queries.py`), a wynik
(`MacroRun`) persistuje WOŁAJĄCY przez `repo.stage_pending` (jedna klinga DB — brief §3/T1).
Makro NIE zapisuje.

Krok po kroku dla każdego frame'a z `frame_ids` (już przefiltrowanych przez `filter_engine`):
1. bramki celu (kolejność): XISF → skip (D-W2, krok 4 = FITS-only); 0 obecnych kopii → skip;
   >1 obecna kopia → skip (D-W1(0), fan-out poza v1); skompresowany master → skip (T6);
   nagłówek niekontrolowalny (header_hash NULL) → skip;
2. `env` z kart frame'a (keyword → `value_num` gdy liczbowa, inaczej `value_raw`; brak → poza env),
3. kroki `compute` (`horreum.expr`) → do `env`; policz `assign` → operacja `set`/`add`.

Plik bez operandu / z błędem obliczenia / łamiący regułę operacji → POMINIĘTY z jawnym powodem
(zebrany w `MacroRun.skipped`). Reguły operacji: `set` wymaga istniejącej karty (keyword
kardynalności >1 wymaga jawnego `idx`); `add` wymaga braku karty. Operand `0` to WARTOSC, nie brak.
Makra JSON-serializowalne (`to_dict`/`from_dict`), zapisywane w tabeli `macros`.

Przykłady akceptacyjne:
- A: filter FOCRATIO>20 ; compute new=FOCALLEN/FOCRATIO ; assign FOCRATIO=round(new,2)
- B: filter TELESCOP contains 'EQ6' ; assign TELESCOP='<wartosc>'
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from . import expr


@dataclass(frozen=True)
class ComputeStep:
    name: str
    expr: str


@dataclass(frozen=True)
class Assign:
    keyword: str
    op: str  # 'set' | 'add'
    expr: str
    value_type: str | None = None  # None: set -> typ istniejacej karty; add -> inferowany
    comment: str | None = None
    idx: int | None = None  # wymagany gdy 'set' na keywordzie z wieloma wystapieniami


@dataclass(frozen=True)
class MacroDef:
    assign: Assign
    name: str | None = None
    filter: dict | None = None
    computes: list[ComputeStep] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> MacroDef:
        if not isinstance(d, dict) or "assign" not in d:
            raise ValueError("definicja makra wymaga pola 'assign'")
        a = d["assign"]
        try:
            assign = Assign(
                keyword=a["keyword"],
                op=a["op"],
                expr=a["expr"],
                value_type=a.get("value_type"),
                comment=a.get("comment"),
                idx=a.get("idx"),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"niepoprawne 'assign': {exc}") from exc
        if assign.op not in ("set", "add"):
            raise ValueError(f"niedozwolona operacja: {assign.op!r}")
        computes = [
            ComputeStep(name=c["name"], expr=c["expr"])
            for c in d.get("computes", [])
        ]
        return MacroDef(
            assign=assign,
            name=d.get("name"),
            filter=d.get("filter"),
            computes=computes,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "filter": self.filter,
            "computes": [{"name": c.name, "expr": c.expr} for c in self.computes],
            "assign": {
                "keyword": self.assign.keyword,
                "op": self.assign.op,
                "expr": self.assign.expr,
                "value_type": self.assign.value_type,
                "comment": self.assign.comment,
                "idx": self.assign.idx,
            },
        }


@dataclass(frozen=True)
class PendingPreview:
    location_id: int
    path: str
    keyword: str
    idx: int | None
    op: str
    old_value: str | None
    new_value: str
    new_type: str
    comment: str | None
    expected_header_hash: str | None  # header_hash location w chwili STAGINGU (kotwica, R#7)


@dataclass(frozen=True)
class SkippedFrame:
    frame_id: int
    path: str
    reason: str


@dataclass(frozen=True)
class MacroRun:
    run_id: str
    touched: list[PendingPreview]
    skipped: list[SkippedFrame]


def _infer_type(value: object) -> str:
    if isinstance(value, bool):  # bool przed int (bool < int)
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _to_text(value: object, value_type: str) -> str:
    """Wartosc -> tekst kanoniczny do `pending_changes.new_value` (fits_io._coerce odwroci)."""
    if value_type == "bool":
        b = value if isinstance(value, bool) else str(value).strip().lower() in (
            "t", "true", "1", "yes"
        )
        return "T" if b else "F"
    if value_type == "int":
        return str(int(value))  # type: ignore[arg-type]
    if value_type == "float":
        return repr(float(value))  # type: ignore[arg-type]
    return str(value)


def _build_env(cards) -> tuple[dict[str, object], dict[str, int], dict[str, object]]:
    """Z kart frame'a: (env, licznosc keyworda, pierwsza karta keyworda).

    env: keyword -> `value_num` gdy liczbowa, inaczej `value_raw` (str/bool 'T'/'F');
    undefined (raw i num None) zostaje poza env -> w wyrazeniu = brak operandu.
    `cards` posortowane po (keyword, idx) -> pierwszy widziany to najmniejszy `idx`."""
    env: dict[str, object] = {}
    counts: dict[str, int] = {}
    first: dict[str, object] = {}
    for c in cards:
        kw = c["keyword"]
        counts[kw] = counts.get(kw, 0) + 1
        if kw not in first:
            first[kw] = c
            value = c["value_num"] if c["value_num"] is not None else c["value_raw"]
            if value is not None:
                env[kw] = value
    return env, counts, first


def _coerce_text(text: str) -> object:
    """Operand z pola edycji bez znanego typu -> najwezszy pasujacy typ Pythona (uzywane przy
    'add', gdy nie ma karty wzorcowej). Pusty string zostaje stringiem (wartosc, nie brak)."""
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _coerce_to_type(text: str, value_type: str | None) -> object:
    """Operand celujacy w TYP istniejacej karty (nie najwezszy typ Pythona) — inaczej
    'true' wpisane do keyworda tekstowego trafiloby jako bool i zapisalo 'True' zamiast
    literalu. `str`/`bool` zostaja tekstem (bool-branch `_to_text` sam sparsuje 'T'/'F');
    `int`/`float` parsujemy liczbowo, a nieparsowalne zwracamy jako tekst -> `_to_text`
    rzuci i edycja zostanie odrzucona z powodem 'nie pasuje do typu'."""
    if value_type in ("str", "bool"):
        return text
    if value_type == "int":
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)  # ulamek wylapie guard niecalkowitosci
            except ValueError:
                return text
    if value_type == "float":
        try:
            return float(text)
        except ValueError:
            return text
    return _coerce_text(text)  # typ nieznany -> infer


def _evaluate_change(
    md: MacroDef,
    computes: list[tuple[str, expr.Expr]],
    assign_expr: expr.Expr | None,
    cards,
) -> tuple[dict | None, str | None]:
    """Liczy makro dla jednego frame'a. Zwraca (opis_zmiany | None, powod_pominiecia | None).

    Wartosc assign: NAJPIERW wyrazenie (`round(new, 2)`), a gdy sie nie liczy jako wyrazenie
    (`assign_expr is None` = nie skompilowalo sie, albo obliczenie zwrocilo BRAK OPERANDU) ->
    LITERAL tekstowy wpisany z reki, celowany w typ karty. Realny blad arytmetyki NIE literalizuje
    — to zepsute wyrazenie, plik pomijany z powodem. Port 1:1 z dawcy `_evaluate_file`."""
    env, counts, first = _build_env(cards)
    kw = md.assign.keyword
    cardinality = counts.get(kw, 0)

    if md.assign.op == "set":
        if cardinality == 0:
            return None, f"brak karty '{kw}' do modyfikacji (uzyj add)"
        if cardinality > 1 and md.assign.idx is None:
            return None, f"keyword '{kw}' ma wiele wystapien -- wymagany jawny idx"
        idx = md.assign.idx if md.assign.idx is not None else 0
        existing = first.get(kw)
        old_value = existing["value_raw"] if existing is not None else None
        base_type = md.assign.value_type or (
            existing["value_type"] if existing is not None else None
        )
    else:  # add
        if cardinality > 0:
            return None, f"karta '{kw}' juz istnieje (uzyj set)"
        idx = None
        old_value = None
        base_type = md.assign.value_type

    if assign_expr is None:
        value = _coerce_to_type(md.assign.expr, base_type)  # literal (nie kompiluje sie)
    else:
        for name, compiled in computes:
            cres = expr.eval_for(compiled, env)
            if not cres.ok:
                return None, f"compute {name}: {cres.reason}"
            env[name] = cres.value
        res = expr.eval_for(assign_expr, env)
        if res.ok:
            value = res.value
        elif res.missing_operand:
            value = _coerce_to_type(md.assign.expr, base_type)  # np. 'RC8' -> tekst 'RC8'
        else:
            return None, f"assign: {res.reason}"  # realny blad obliczenia -> pomijamy

    value_type = base_type or _infer_type(value)

    if value_type == "int" and isinstance(value, float) and not value.is_integer():
        return None, f"wynik niecalkowity ({value!r}) dla keyworda '{kw}' typu int"

    try:
        new_value = _to_text(value, value_type)
    except (ValueError, TypeError):
        return None, f"wartosc '{md.assign.expr}' nie pasuje do typu '{value_type}'"

    change = {
        "keyword": kw, "idx": idx, "op": md.assign.op, "old_value": old_value,
        "new_value": new_value, "new_type": value_type, "comment": md.assign.comment,
    }
    return change, None


def _resolve_target(rows) -> tuple[dict | None, str | None]:
    """Z wierszy `writeback_frame_targets` JEDNEGO frame'a wybierz cel writebacku (JEDNA obecna
    location FITS, kontrolowalna) albo powod pominiecia. Kolejnosc bramek = brief §6/D-W1/D-W2/T6.

    `rows` to >=1 wiersz per frame (LEFT JOIN present-location); frame bez obecnej kopii ma jeden
    wiersz z `location_id IS NULL`. Zwraca (wiersz_celu | None, powod | None)."""
    filetype = rows[0]["filetype"]
    if filetype == "xisf":
        return None, "XISF poza krokiem 4 (writeback XISF = pod-etap D-W2)"
    present = [r for r in rows if r["location_id"] is not None]
    if not present:
        return None, "brak obecnej kopii do zapisu (wszystkie present=0)"
    if len(present) > 1:
        return None, f"wiele obecnych kopii ({len(present)}) -- writeback poza v1 (D-W1)"
    target = present[0]
    if target["compressed"]:
        return None, "skompresowany master -- edycja poza krokiem 4 (T6)"
    if target["header_hash"] is None:
        return None, "brak header_hash (plik nieczytelny) -- brak kontroli zapisu"
    return target, None


def run_macro(macro_def, frame_ids, *, targets_fn, cards_fn, run_id=None) -> MacroRun:
    """Uruchamia makro nad `frame_ids` (widocznymi w gridzie). CZYSTY silnik: dane przez wstrzykiwane
    `targets_fn(frame_ids)->rows` (topologia present-location, `queries.writeback_frame_targets`) i
    `cards_fn(frame_id)->rows` (`queries.frame_cards`). ZERO zapisu — zwraca `MacroRun`; persist robi
    wolajacy przez `repo.stage_pending`.

    Blad DEFINICJI makra (skladnia/wezel `expr`) rzuca `ExprError`/`ValueError` JUZ przy kompilacji
    (przed petla) — to blad uzytkownika. Blad DANYCH pojedynczego frame'a / niedostepny cel → frame do
    `skipped` z powodem, potok leci dalej."""
    md = MacroDef.from_dict(macro_def) if isinstance(macro_def, dict) else macro_def
    run_id = run_id or uuid.uuid4().hex

    computes = [(c.name, expr.compile_expr(c.expr)) for c in md.computes]
    # Assign niekompilowalny (np. '76EDPH', 'EQMOD HEQ5/6') NIE jest bledem definicji — realne
    # wartosci naglowkow sa tekstem. assign_expr=None -> tryb LITERALU dla kazdego frame'a.
    try:
        assign_expr: expr.Expr | None = expr.compile_expr(md.assign.expr)
    except expr.ExprError:
        assign_expr = None

    ids = sorted(int(i) for i in frame_ids)
    by_frame: dict[int, list] = defaultdict(list)
    for row in targets_fn(ids):
        by_frame[int(row["frame_id"])].append(row)

    touched: list[PendingPreview] = []
    skipped: list[SkippedFrame] = []

    for fid in ids:
        rows = by_frame.get(fid)
        if not rows:                              # frame zniknal z bazy miedzy filtrem a makrem
            skipped.append(SkippedFrame(fid, "", "frame nieobecny w bazie"))
            continue
        target, reason = _resolve_target(rows)
        if target is None:
            path = next((r["path"] for r in rows if r["path"]), "")
            skipped.append(SkippedFrame(fid, path or "", reason or ""))
            continue
        change, reason = _evaluate_change(md, computes, assign_expr, cards_fn(fid))
        if change is None:
            skipped.append(SkippedFrame(fid, target["path"], reason or ""))
            continue
        touched.append(PendingPreview(
            location_id=int(target["location_id"]), path=target["path"],
            keyword=change["keyword"], idx=change["idx"], op=change["op"],
            old_value=change["old_value"], new_value=change["new_value"],
            new_type=change["new_type"], comment=change["comment"],
            expected_header_hash=target["header_hash"],
        ))

    return MacroRun(run_id=run_id, touched=touched, skipped=skipped)


@dataclass(frozen=True)
class ManualResult:
    ok: bool
    reason: str | None = None
    op: str | None = None  # 'set' | 'add'
    idx: int | None = None
    old_value: str | None = None
    new_value: str | None = None
    new_type: str | None = None


def evaluate_manual_change(cards, keyword: str, new_text: str) -> ManualResult:
    """Reczna edycja JEDNEJ komorki (grid) -> opis zmiany (te same reguly co makro). CZYSTA funkcja:
    `cards` = karty frame'a stojacego pod edytowana location (`queries.location_cards`); zapis wpisu
    robi wolajacy przez `repo.stage_pending`. `set` gdy karta istnieje (zachowuje typ+komentarz), `add`
    gdy brak. Keyword z wieloma `idx` (COMMENT/HISTORY/duplikat) -> odrzucony (nie zgadujemy wystapienia).
    Int + wynik ulamkowy / wartosc niepasujaca do typu -> odrzucone z powodem (bez cichej utraty)."""
    matching = [c for c in cards if c["keyword"] == keyword]

    if not matching:
        op, idx, old_value = "add", None, None
        value = _coerce_text(new_text)  # brak wzorca typu -> infer
        value_type = _infer_type(value)
    else:
        if len(matching) > 1:
            return ManualResult(
                False, f"keyword '{keyword}' ma wiele wystapien -- edycja reczna poza krokiem 4")
        card = matching[0]
        op, idx, old_value = "set", int(card["idx"]), card["value_raw"]
        value_type = card["value_type"]
        value = _coerce_to_type(new_text, value_type)  # celuj w typ karty
        if value_type is None:
            value_type = _infer_type(value)

    if value_type == "int" and isinstance(value, float) and not value.is_integer():
        return ManualResult(False, f"wynik niecalkowity ({value!r}) dla keyworda typu int")
    try:
        new_value = _to_text(value, value_type)
    except (ValueError, TypeError):
        return ManualResult(False, f"wartosc '{new_text}' nie pasuje do typu '{value_type}'")

    return ManualResult(
        True, op=op, idx=idx, old_value=old_value, new_value=new_value, new_type=value_type)
