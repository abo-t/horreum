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
1. bramki celu (kolejność): FORMAT (RAW → skip zawsze; XISF+`add` → skip, D-PD-5); 0 obecnych kopii → skip;
   >1 obecna kopia → skip (D-W1(0), fan-out poza v1); skompresowany master → skip (T6);
   nagłówek niekontrolowalny (header_hash NULL) → skip; FITS z kartą `CHECKSUM`/`DATASUM` → skip
   (`card_rules.bramka_sumy` - pisarz odmówi na obu drogach, AR-166);
2. `env` z kart frame'a (keyword → `value_num` gdy liczbowa, inaczej `value_raw`; brak → poza env),
3. kroki `compute` (`horreum.expr`) → do `env`; policz `assign` → operacja `set`/`add`.

Plik bez operandu / z błędem obliczenia / łamiący regułę operacji → POMINIĘTY z jawnym powodem
(zebrany w `MacroRun.skipped`). Reguły operacji: `set` wymaga istniejącej karty (keyword
kardynalności >1 wymaga jawnego `idx`); `add` wymaga braku karty. Operand `0` to WARTOSC, nie brak.
Zmiana łamiąca reguły karty FITS 4.0 (`card_rules.card_violation` - ten sam właściciel, którego
pyta pisarz) też jest pominięciem z powodem już w PODGLĄDZIE, a nie 'blocked' przy commicie (AR-9).
Silnik nie importuje astropy: reguły mieszkają w `card_rules` (ujednolicenie karty OBJECT, które
przewidywało tu drogę zapisu pisarzem, przejął gest „Uzgodnij” - `object_change`, AR-157).
Makra są JSON-serializowalne (`to_dict`/`from_dict`), ale **NIE SĄ NIGDZIE UTRWALANE** — definicja
powstaje w pasku (`gui.grid.MacroBar.macro_def`) na czas jednego przebiegu i ginie z zamknięciem okna.
Tabela `macros` (migracja 0003) stoi PUSTA i taka zostaje: **decyzja Zdzinia 2026-08-01 (D-P-I-4,
wariant B)** — naprawy nagłówka w tym archiwum okazały się operacjami jednorazowymi na konkretnej
porcji plików (`ED`→`ED120R`, IC1795, dopisanie kart `OBJECT`), a nie przepisami, po które się wraca,
więc biblioteka przepisów byłaby funkcją dla nikogo. Wcześniejsze zdanie w tym miejscu („zapisywane
w tabeli `macros`") opisywało zamiar, nie stan, i wprowadzało w błąd. Wskrzeszenie = jeden pisarz
w `repo` + lista w pasku; szkielet tabeli czeka gotowy. Ślad: `brief/PLAN_pi_martwe_tabele.md` §3/§4.3.

Przykłady akceptacyjne:
- A: filter FOCRATIO>20 ; compute new=FOCALLEN/FOCRATIO ; assign FOCRATIO=round(new,2)
- B: filter TELESCOP contains 'EQ6' ; assign TELESCOP='<wartosc>'
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import card_rules, expr
from .resolve import paths as _paths
from .resolve._coerce import _to_text as _tekst
from .resolve._text import norm as _norm, path_segments as _path_segments
from .resolve.filters import classify_filter_token, normalize_filter
from .resolve.frames import HISTORY_MASTER_KINDS, MASTER_IMAGETYP, normalize_kind


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

    naruszenie = card_rules.card_violation(kw, new_value, md.assign.comment,
                                           new_card=md.assign.op == "add")
    if naruszenie is not None:                       # AR-9: powód w podglądzie, nie przy commicie
        return None, naruszenie.reason

    change = {
        "keyword": kw, "idx": idx, "op": md.assign.op, "old_value": old_value,
        "new_value": new_value, "new_type": value_type, "comment": md.assign.comment,
    }
    return change, None


def resolve_target(rows) -> tuple[dict | None, str | None]:
    """Z wierszy `writeback_frame_targets` JEDNEGO frame'a wybierz cel writebacku (JEDNA obecna
    location, kontrolowalna) albo powod pominiecia. Kolejnosc bramek = brief §6/D-W1/T6/D-X-13.

    BRAMKA FORMATU (P-D/D-PD-5) jest PIERWSZA i patrzy na `filetype` ('raw'|'xisf'|'fits',
    `scan.py`): RAW jest dla Horreum READ-ONLY (pisarz odmawia — `writeback._is_raw`). Bez niej
    user dostawal 'blocked' PO commicie zamiast czystego pominiecia PRZED nim. Nieznany/NULL
    `filetype` przechodzi (baza sprzed kolumny).

    XISF NIE JEST odsiewany w calosci (P6c dal mu pisarza — D-W2 domkniete); przed backfillem kart
    odcinala go i tak bramka `header_hash IS NULL`, bo bez odcisku nie ma kontroli zapisu.

    ODSIEW `xisf`+`add` ZDJETY 2026-08-02 (P6d, D-0802-1): pisarz umie juz dopisac karte, kopiujac
    konwencje z sasiedniej karty tego samego pliku (`scan.build_fits_keyword_element`). `op` zostaje
    w sygnaturze — bramki dopisania sa teraz w pisarzu i sa WEZSZE niz format (karta juz istnieje,
    wlasnosc bez karty, brak wzorca w apostrofach), wiec ich miejsce jest tam, gdzie widac bajty.

    `rows` to >=1 wiersz per frame (LEFT JOIN present-location); frame bez obecnej kopii ma jeden
    wiersz z `location_id IS NULL`. Zwraca (wiersz_celu | None, powod | None)."""
    filetype = rows[0]["filetype"]
    if filetype == "raw":
        return None, "plik RAW (DSLR) -- Horreum go NIE zapisuje (read-only)"
    present = [r for r in rows if r["location_id"] is not None]
    if not present:
        return None, "brak obecnej kopii do zapisu (wszystkie present=0)"
    if len(present) > 1:
        return None, f"wiele obecnych kopii ({len(present)}) -- writeback poza v1 (D-W1)"
    target = present[0]
    if target["compressed"]:
        return None, "skompresowany master -- edycja poza krokiem 4 (T6)"
    if rows[0]["sha1_data_uncomputable"]:
        # D-X-13: zapis zmienia `file_sha1`, a przy degeneracie `sha1_data == file_sha1`, wiec
        # re-sync zobaczylby PODMIANE TRESCI -> nowy frame + `rebind_location`, a stary zostalby
        # sierota z zeznaniem i `object_id`. Bramka ma blizniaka w pisarzu (`_xisf_gates` patrzy
        # na brak obrazu-attachmentu) -- ta czyta baze, tamta plik.
        return None, "tozsamosc nieobliczalna (degenerat) -- zapis rozdwoilby klatke (D-X-13)"
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
    `skipped` z powodem, potok leci dalej. Po bramkach celu - bramka sumy kontrolnej z faktu
    `n_sum` wiersza celu (AR-166): FITS z `CHECKSUM`/`DATASUM` pisarz odmowi, wiec podglad mowi to
    przed stagingiem (powod z kodem, `card_rules.BRAMKA_SUMY`)."""
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
        target, reason = resolve_target(rows)
        if target is None:
            path = next((r["path"] for r in rows if r["path"]), "")
            skipped.append(SkippedFrame(fid, path or "", reason or ""))
            continue
        suma = card_rules.bramka_sumy(target["filetype"], target["n_sum"])   # AR-166
        if suma is not None:                     # pisarz odmówi - pominięcie w podglądzie
            skipped.append(SkippedFrame(fid, target["path"], suma))
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
    comment: str | None = None  # None = karta zachowuje zastany komentarz (jak pole `MacroBar`)


def evaluate_manual_change(cards, keyword: str, new_text: str,
                           comment: str | None = None) -> ManualResult:
    """Reczna edycja JEDNEJ komorki (grid) -> opis zmiany (te same reguly co makro). CZYSTA funkcja:
    `cards` = karty frame'a stojacego pod edytowana location (`queries.location_cards`); zapis wpisu
    robi wolajacy przez `repo.stage_pending`. `set` gdy karta istnieje (zachowuje typ+komentarz), `add`
    gdy brak. Keyword z wieloma `idx` (COMMENT/HISTORY/duplikat) -> odrzucony (nie zgadujemy wystapienia).
    Int + wynik ulamkowy / wartosc niepasujaca do typu -> odrzucone z powodem (bez cichej utraty).

    `comment` ma znaczenie pola komentarza w `MacroBar` (AR-47): pusty albo None - karta zachowuje
    zastany komentarz; wpisany - zapis razem z nim i reguly karty licza go tak samo jak w makrze."""
    comment = (comment or "").strip() or None
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
    naruszenie = card_rules.card_violation(keyword, new_value, comment, new_card=op == "add")
    if naruszenie is not None:                       # AR-9: te same reguły co pisarz
        return ManualResult(False, naruszenie.reason)

    return ManualResult(
        True, op=op, idx=idx, old_value=old_value, new_value=new_value, new_type=value_type,
        comment=comment)


def plan_manual_change(rows, keyword: str, new_text: str, *, cards_fn,
                       comment: str | None = None) -> tuple[PendingPreview | None, str | None]:
    """Edycja JEDNEJ komorki gridu -> wpis podgladu w ksztalcie makra albo powod odmowy. CZYSTA
    funkcja (zero zapisu), wolajacy stage'uje przez `repo.stage_pending_replacing`.

    Te same dwie bramki co makro, w tej samej kolejnosci: najpierw CEL (`resolve_target` na wierszach
    `queries.writeback_frame_targets` JEDNEJ klatki - RAW, brak/wiele obecnych kopii, kompresja,
    degenerat tozsamosci, brak `header_hash`, suma kontrolna FITS - AR-166), potem ZMIANA
    (`evaluate_manual_change` na kartach tej kopii, `cards_fn(location_id)` =
    `queries.location_cards`). Komorka edytowalna w gridzie
    nie obiecuje wiec niczego, czego makro na tej samej klatce by nie zrobilo.

    Zwraca `(PendingPreview, None)` albo `(None, powod)`; pusta lista wierszy (klatka zniknela
    z bazy miedzy edycja a zapisem) to powod, nie wyjatek - ten sam, co w `run_macro`."""
    if not rows:
        return None, "frame nieobecny w bazie"
    target, reason = resolve_target(rows)
    if target is None:
        return None, reason
    suma = card_rules.bramka_sumy(target["filetype"], target["n_sum"])       # AR-166
    if suma is not None:
        return None, suma
    res = evaluate_manual_change(cards_fn(int(target["location_id"])), keyword, new_text,
                                 comment=comment)
    if not res.ok:
        return None, res.reason
    return PendingPreview(
        location_id=int(target["location_id"]), path=target["path"], keyword=keyword,
        idx=res.idx, op=res.op, old_value=res.old_value, new_value=res.new_value,
        new_type=res.new_type, comment=res.comment,
        expected_header_hash=target["header_hash"]), None


# ============================================================ naprawa nagłówków IMAGETYP i FILTER

#: Folder na pozycji filtra, który mówi „bez filtra" ponad żetony osi filtra: kamera kolorowa (`OSC`)
#: to konwencja drzewa, nie karty - w kartach `FILTER` archiwum `OSC` nie występuje.
_FOLDER_BEZ_FILTRA = frozenset({"OSC"})

#: Rodzaje, którym plan proponuje kartę `FILTER` z folderu: oba końce przepisu kalibracji (flat
#: i master flat po jednej stronie, light po drugiej). Stosy mają własne drzewo - poza planem.
FILTER_FIX_KINDS = frozenset({"flat", "master_flat", "light"})

#: Forma zapisu karty `FILTER` - DOMYŚLNIE forma folderu, z którego pochodzi świadek (dziś foldery
#: `L-Pro`/`L-eXtreme` pokrywają się z kanonem osi). Wybór innej formy (np. NINA `LPRO`/`LEXT`) należy
#: do człowieka: `plan_header_fix(filter_forms={kanon: forma})`, w CLI `--filter-form KANON=FORMA`.
#: Forma musi wracać do tego samego kanonu (`classify_filter_token`) - inaczej karta zmieniłaby filtr.
FILTER_FORM_DEFAULT = "folder"


def _token_filtra(token):
    """`classify_filter_token` + `OSC` jako „bez filtra" (konwencja drzewa)."""
    if _norm(token) in _FOLDER_BEZ_FILTRA:
        return "bez_filtra", None
    return classify_filter_token(token)


def folder_filter(path, kind):
    """Świadek FILTRA z folderu kopii → `(stan, forma, kanon)`: `("filtr", segment, kanon)` - segment
    na pozycji filtra jest nazwą ze słownika osi filtra (forma = segment tak, jak stoi na dysku, kanon
    do porównań); `("bez_filtra", segment, None)` - segment mówi „bez filtra" (`OSC`, `NoFilter`);
    `(None, None, None)` - pozycja pusta albo segment nie jest filtrem.

    Pozycja: flat i master flat - `paths.filter_folder_from_path` (marker flatów + dwa katalogi);
    light - DOKŁADNIE dwa katalogi pod folderem obiektu (`LIGHTS\\<obiekt>\\<zestaw>\\<filtr>\\plik`,
    `paths.object_folder` z kategoriami `_SOLAR`/`_COMETS`). Zestaw bez folderu filtra (jeden
    katalog pod obiektem) milczy, bo pozycja filtra byłaby tam zgadywaniem.

    Dopasowanie DOKŁADNE do słownika filtrów (`classify_filter_token`): folder o dowolnej nazwie
    na tej pozycji (`A140R_2600MC` pod `_SOLAR\\Moon`) filtrem nie zostaje."""
    if kind in ("flat", "master_flat"):
        seg = _paths.filter_folder_from_path(path)
    elif kind == "light":
        obj = _paths.object_folder(path, "light")
        seg = None
        if obj is not None:
            pod = _path_segments(path)[len(_path_segments(obj)):-1]
            seg = pod[1] if len(pod) == 2 else None
    else:
        seg = None
    if seg is None:
        return None, None, None
    stan, canon = _token_filtra(seg)
    return (stan, seg, canon) if stan is not None else (None, None, None)


def filename_filter(path):
    """Świadek FILTRA z nazwy pliku - wyłącznie do wykrycia SPRZECZNOŚCI, nie źródło karty. Kanon,
    `""` (nazwa mówi „bez filtra") albo None (milczy). Żeton po `FILTER` (szablon nazw Horreum
    `..._FILTER_LPRO_...`), a bez niego żetony co najmniej trzyznakowe (nazwy NINA `..._CLS_-11.90...`)
    - krótsze (`L`, `R`, `B`) trafiałyby w przypadkowe człony nazwy."""
    toks = [_norm(t) for t in _paths.filename_tokens(path)]
    if "FILTER" in toks:
        i = toks.index("FILTER")
        kandydaci = toks[i + 1:i + 2]
    else:
        kandydaci = [t for t in toks if len(t) >= 3]
    for t in kandydaci:
        stan, canon = _token_filtra(t)
        if stan == "bez_filtra":
            return ""
        if stan == "filtr":
            return canon
    return None


@dataclass(frozen=True)
class HeaderFixPlan:
    """Plan naprawy nagłówków w miejscu = podgląd przed stagingiem. `run` ma kształt makra
    (`touched` → `repo.stage_pending_many` → `writeback.commit(..., inplace=True)`, `skipped` =
    zmiany potrzebne, których plan NIE zapisze, z powodem), `changes` = `(keyword, stara, nowa,
    liczba kart)` malejąco, `conflicts` = pary `(klatka, karta)` do ręki: świadectwa kopii mówią
    więcej niż jeden kanon. `copies` = liczba RÓŻNYCH kopii (plików) w `touched` - kart bywa więcej."""
    run: MacroRun
    changes: list[tuple[str, str | None, str, int]]
    conflicts: list[SkippedFrame]

    @property
    def copies(self):
        return len({p.location_id for p in self.run.touched})


def _bramka_celu(row):
    """Powód, dla którego kopii nie zapisujemy w miejscu, albo None - bramki `resolve_target`
    dla planu naprawy nagłówka (`plan_header_fix`), PER KOPIA: plan nie odmawia
    klatce z kilkoma kopiami, każda kopia ma własną kotwicę `header_hash`. Suma kontrolna - jedno
    zdanie z kodem dla wszystkich bramek (`card_rules.bramka_sumy`, AR-167)."""
    if row["filetype"] == "raw":
        return "plik RAW (DSLR) - Horreum go nie zapisuje"
    if row["compressed"]:
        return "skompresowany master"
    if row["degen"]:
        return "tożsamość nieobliczalna (degenerat) - zapis rozdwoiłby klatkę"
    if row["header_hash"] is None:
        return "brak header_hash - brak kontroli zapisu"
    if row["unreadable_since"] is not None:
        return "kopia oznaczona jako nieczytelna"
    return card_rules.bramka_sumy(row["filetype"], row["n_sum"])   # jedno zdanie bramki (AR-167)


def _wlasna_wartosc(row, keyword, karta):
    """`(wartość karty TEJ kopii, znana?)`. Karty w `cards` należą do KLATKI (mogły przyjść z innej
    kopii): fakty kopii zebrane dla bieżącego nagłówka (`facts_current`) mówią za kopię; bez nich
    za kopię mówi klatka tylko wtedy, gdy klatka ma jedną lokację."""
    if row["facts_current"]:
        return _tekst(row[f"hdr_{keyword.lower()}"]), True
    if row["n_loc"] == 1:
        return (_tekst(karta["value_raw"]) if karta is not None else None), True
    return None, False


def _kanon_karty(keyword, wartosc, kind):
    """Kanon wartości karty do porównań świadectw: `FILTER` przez oś filtra (`normalize_filter`;
    żeton braku = `""`), `IMAGETYP` przez rodzaj, z subem podniesionym do mastera klatki, gdy reguła
    historii łączy tę parę (klatkę przeliczono z historii, karta mówi jeszcze sub)."""
    if keyword == "FILTER":
        c = normalize_filter(wartosc)
        return c if c is not None else ""
    k = normalize_kind(wartosc)
    return kind if HISTORY_MASTER_KINDS.get(k) == kind else k


def _para(kopie, keyword, filter_forms):
    """Rozstrzygnięcie pary `(klatka, keyword)` ze WSZYSTKICH świadectw wszystkich obecnych kopii:
    karta klatki, wartość każdej kopii (fakty kopii), a dla `FILTER` także folder i nazwa pliku.
    Zwraca `(propozycje, sprzecznosc)`: `propozycje` = `[(row, (op, stara, nowa, typ), powód)]`,
    `sprzecznosc` = `(ścieżka, opis)` albo None. Więcej niż jeden kanon = sprzeczność całej pary -
    nic z niej nie idzie do stagingu (kopia z kartą `CLS` blokuje dopisanie `L-Pro` drugiej)."""
    r0 = kopie[0]
    kind = r0["kind"]
    if keyword == "IMAGETYP" and kind not in MASTER_IMAGETYP:
        return [], None
    if keyword == "FILTER" and kind not in FILTER_FIX_KINDS:
        return [], None
    karty = r0["cards"].get(keyword, ())
    if len(karty) > 1:
        return [], (r0["path"], f"wiele kart {keyword} ({len(karty)})")
    karta = karty[0] if karty else None
    swiadectwa = []                                   # (źródło, kanon)
    if karta is not None and _tekst(karta["value_raw"]) is not None:
        swiadectwa.append(("karta klatki", _kanon_karty(keyword, _tekst(karta["value_raw"]), kind)))
    stany = []
    for r in kopie:
        wlasna, znana = _wlasna_wartosc(r, keyword, karta)
        folder = folder_filter(r["path"], kind) if keyword == "FILTER" else (None, None, None)
        if znana and wlasna is not None:
            swiadectwa.append((f"kopia {r['location_id']}", _kanon_karty(keyword, wlasna, kind)))
        if folder[0] is not None:
            swiadectwa.append((f"folder {folder[1]}", folder[2] if folder[0] == "filtr" else ""))
        if keyword == "FILTER":
            z_nazwy = filename_filter(r["path"])
            if z_nazwy is not None:
                swiadectwa.append(("nazwa pliku", z_nazwy))
        stany.append((r, wlasna, znana, folder))
    kanony = sorted({k for _z, k in swiadectwa})
    if len(kanony) > 1:
        opis = ", ".join(f"{z}: {k or 'bez filtra'}" for z, k in swiadectwa)
        return [], (r0["path"], f"świadectwa mówią różnie ({opis})")
    propozycje = []
    for r, wlasna, znana, folder in stany:
        if znana and wlasna is not None:
            if keyword == "IMAGETYP" and normalize_kind(wlasna) != kind:
                nowa = MASTER_IMAGETYP[kind]          # karta mówi sub, klatka jest masterem
            else:
                continue                              # karta mówi już to, co świadectwa
        elif keyword == "FILTER" and folder[0] == "filtr":
            nowa = filter_forms.get(folder[2], folder[1])
        else:
            continue                                  # brak karty i brak świadka wartości
        powod = None if znana else "kopia bez zebranych faktów przy klatce z kilkoma kopiami"
        op = "set" if (znana and wlasna is not None) or (r["n_loc"] == 1 and karta is not None) else "add"
        typ = (karta["value_type"] if karta is not None else None) or "str"
        propozycje.append((r, (op, wlasna, nowa, typ, karta["comment"] if karta else None), powod))
    return propozycje, None


def plan_header_fix(rows, *, keywords=("IMAGETYP", "FILTER"), filter_forms=None,
                    run_id=None) -> HeaderFixPlan:
    """Wiersze kopii (jeden na obecną lokację aktywnej klatki, kontrakt `cli._header_fix_rows`) →
    `HeaderFixPlan`. CZYSTA funkcja: zero DB, zero zapisu, plik nieczytany.

    Dwie karty, dwa predykaty (AR-96, AR-111):
      * `IMAGETYP` - klatka już z rodzajem mastera (`MASTER_IMAGETYP`, po przeliczeniu rodzaju z
        historii), której kopia mówi sub tej klasy (`HISTORY_MASTER_KINDS`) → `set` na formę mastera;
        klatka jeszcze nieprzeliczona do planu nie wchodzi (najpierw `rederive-kind --apply`);
      * `FILTER` - flat, master flat albo light, którego kopia NIE ma karty `FILTER`, a folder kopii
        nazywa filtr ze słownika (`folder_filter`) → `add` (albo `set` pustej karty). Wartość =
        forma folderu albo forma z `filter_forms` (`{kanon: forma}`, `FILTER_FORM_DEFAULT`).

    ŚWIADECTWA NAJPIERW, ROZSTRZYGNIĘCIE POTEM (`_para`): każda para `(klatka, keyword)` zbiera
    kartę klatki, wartość każdej obecnej kopii, folder i nazwę pliku - także wtedy, gdy zmiana nie
    jest potrzebna - i więcej niż jeden kanon to `conflicts` (cała para do ręki). PER KOPIA, nie per
    klatka: każda obecna kopia dostaje własny wpis z kotwicą `header_hash` TEJ kopii (makro odmawia
    klatce z kilkoma kopiami - tu odmowa byłaby pozorna, bo pisarz i tak pisze jeden plik). Bramka
    celu albo reguły karty - `run.skipped` z powodem. Drugi plan po udanym wykonaniu jest pusty
    z konstrukcji predykatów. `writeback` (astropy) importowany leniwie, wyłącznie dla `set` karty
    FITS z komentarzem."""
    filter_forms = dict(filter_forms or {})
    for canon, forma in filter_forms.items():
        if _token_filtra(forma) != ("filtr", canon):
            raise ValueError(f"forma {forma!r} nie wraca do kanonu {canon!r} - karta zmieniłaby filtr")
    run_id = run_id or uuid.uuid4().hex
    touched: list[PendingPreview] = []
    skipped: list[SkippedFrame] = []
    conflicts: list[SkippedFrame] = []
    changes: Counter = Counter()
    by_frame: dict[int, list] = defaultdict(list)
    for r in rows:
        by_frame[int(r["frame_id"])].append(r)
    for fid in sorted(by_frame):
        for keyword in keywords:
            propozycje, sprzecznosc = _para(by_frame[fid], keyword, filter_forms)
            if sprzecznosc is not None:
                conflicts.append(SkippedFrame(fid, sprzecznosc[0], f"{keyword}: {sprzecznosc[1]}"))
                continue
            for r, (op, stara, nowa, typ, komentarz), powod in propozycje:
                powod = _bramka_celu(r) or powod
                if powod is None:
                    naruszenie = card_rules.card_violation(keyword, nowa, komentarz,
                                                           new_card=op == "add")
                    powod = naruszenie.reason if naruszenie is not None else None
                if powod is None and op == "set" and komentarz and r["filetype"] == "fits":
                    from . import writeback
                    powod = writeback.comment_loss_route(r["filetype"], keyword, nowa, komentarz)
                if powod is not None:
                    skipped.append(SkippedFrame(fid, r["path"], f"{keyword}: {powod}"))
                    continue
                touched.append(PendingPreview(
                    location_id=int(r["location_id"]), path=r["path"], keyword=keyword,
                    idx=0 if op == "set" else None, op=op, old_value=stara, new_value=nowa,
                    new_type=typ, comment=None, expected_header_hash=r["header_hash"]))
                changes[(keyword, stara, nowa)] += 1
    return HeaderFixPlan(
        run=MacroRun(run_id=run_id, touched=touched, skipped=skipped),
        changes=[(k, s, n, c) for (k, s, n), c in
                 sorted(changes.items(), key=lambda kv: (-kv[1], kv[0][0], str(kv[0][1]), kv[0][2]))],
        conflicts=conflicts)
