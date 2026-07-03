"""Wybrane keywordy → kolumny (pivot po stronie Pythona). Port `fitsmirror/core/pivot.py`.

Logika KOMÓRKI 1:1 z dawcą; różnica: dawca wołał `repo.cards_for_pivot` W ŚRODKU, tu wiersze cards
są WSTRZYKIWANE (ZERO `execute` — root-moduł objęty meta-testem AST). SQL (literał `json_each`) mieszka
w `gui/queries.py:cards_pivot`, pivot tylko składa wide. `frame_id` zamiast `file_id` dawcy; bez `path`
(kolumny bazowe idą osobno przez `queries.base_rows`, bo frame 1:N location — PLAN_gui_grid §3).

TRZY stany komórki (rozróżnialne):
- BRAK karty w klatce → sentinel `MISSING` (klatka nie ma tej karty; XISF ma 0 cards → wszystkie MISSING),
- karta z pustą wartością → `PivotCell(raw=None, num=None)`,
- karta z wartością → `PivotCell(raw=..., num=...)`.

`num` (z `value_num`) pozwala GUI sortować numerycznie. Keyword z wieloma `idx` (COMMENT/HISTORY/
duplikat) → pierwsze wystąpienie (najmniejszy `idx`; wiersze MUSZĄ przyjść `ORDER BY frame_id,keyword,idx`).
"""

from __future__ import annotations

import re
from collections import namedtuple
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MISSING = object()  # sentinel: klatka nie ma tej karty (różny od wartości pustej)

PivotCell = namedtuple("PivotCell", "raw num")  # raw: str|None, num: float|None

_KW_RE = re.compile(r"^[A-Za-z0-9_\-]{1,68}$")


@dataclass
class PivotRow:
    frame_id: int
    cells: dict[str, object]  # keyword -> MISSING | PivotCell


@dataclass
class Pivot:
    keywords: list[str]
    rows: list[PivotRow]


def validate_keyword(name) -> bool:
    return isinstance(name, str) and bool(_KW_RE.match(name))


def build_pivot(
    frame_ids: Sequence[int],
    keywords: Sequence[str],
    card_rows: Iterable[Sequence],
) -> Pivot:
    """Składa pivot z JUŻ pobranych wierszy cards. `card_rows`: iterowalne krotek
    `(frame_id, keyword, idx, value_raw, value_num)` posortowanych `ORDER BY frame_id, keyword, idx`.
    Kolejność wierszy wyniku = kolejność `frame_ids` (wołający sortuje wg kolumn bazowych)."""
    keywords = list(keywords)
    for kw in keywords:
        if not validate_keyword(kw):
            raise ValueError(f"niedozwolony keyword kolumny: {kw!r}")

    frame_ids = list(frame_ids)
    cells: dict[int, dict[str, object]] = {
        fid: {kw: MISSING for kw in keywords} for fid in frame_ids
    }
    # ORDER BY ... idx → pierwszy (najmniejszy idx) trafia pierwszy; kolejne pomijamy.
    for row in card_rows:
        fid, kw = int(row[0]), row[1]
        col = cells.get(fid)
        if col is not None and kw in col and col[kw] is MISSING:
            col[kw] = PivotCell(row[3], row[4])

    rows = [PivotRow(fid, cells[fid]) for fid in frame_ids]
    return Pivot(keywords, rows)
