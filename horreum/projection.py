"""TRZECIA KLINGA — jedyny obramkowany dom MUTACJI PLIKÓW przez LINK/KOPIĘ/KATALOG (KROK 6 scalenia,
brief PLAN_projekcje). Materializuje bieżącą PERSPEKTYWĘ (zbiór frame'ów filtra) w drzewo folderów
HARDLINKÓW (albo kopii) pod wykluczonym korzeniem (`_WBPP`/`_Review`) — „Projekcja → drzewo po
obiektach", „→ WBPP feed". Pętla scalenia domyka się: projekcja trafia pod `EXCLUDED_DIR_NAMES`
(`scan.py`) → nie wraca jako wejście skanu.

Dawca-WZORZEC: Custos `tools/wbpp_feed.py` (sonda hardlinka, DRY-default, plan→apply). Rdzeń Qt-wolny
(jak `writeback.py`): czyste `plan(...)`/`apply(...)` z callbackami `progress`/`should_cancel` (GUI
podaje je z wątku roboczego). Meta-tripwir AST (`tests/test_writeback_safety.py`) pilnuje, że
`os.link`/`os.makedirs`/`shutil.copy2` żyją WYŁĄCZNIE tu i w `writeback.py` (DOORS).

Twarde ramy (brief §0):
- **ZERO zapisu domenowego** — projekcja EFEMERYCZNA (kasowalna w Eksploratorze, poza skanem): NIE
  emituje eventu ani nie pisze do bazy (JEDNA-KLINGA nietknięta — brak `repo`). Obok korzenia zostaje
  manifest `_PROJEKCJA.json` (PLIK, nie DB).
- **ZERO nadpisania** — cel istnieje z INNYM i-węzłem → `conflict` (NIE clobber); ten sam i-węzeł →
  `exists` (idempotentnie pomiń). Read-only wobec drzewa źródłowego.
- **CEL-POD-WYKLUCZENIEM** — `root` MUSI zawierać segment z `EXCLUDED_DIR_NAMES`. Hardlink = duplikat
  i-węzła; `os.walk followlinks=False` NIE odróżni go od oryginału → dla hardlinków chroni WYŁĄCZNIE
  prune `dirnames` po nazwie (`_assert_excluded_segment` PRZED masą).
- **DRY domyślnie** — `do_apply=False`: tylko sonduje stan celu (would-link/exists/conflict), ZERO
  tworzenia. Pierwszy realny hardlink SONDOWANY pełnym `_verify_content` (i-węzeł+rozmiar+treść — SMB
  potrafi dać kopię zamiast linka) → rozjazd = `ProjectionAbort` PRZED masą (wzorzec `ImportAbort`).

Podział koncernów (COHESION): `plan(con, ...)` = czysty ODCZYT DB (źródło linku `present_locations`
R#1 + segmenty `base_rows`); `apply(plan, root, ...)` = czysta MUTACJA filesystemu (zna korzeń). Import
`gui.queries` jest Qt-wolny (`gui/__init__.py` pusty) — pilnuje tego `test_gui_isolation`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
from collections.abc import Callable

from . import naming
from .gui import queries
from .scan import EXCLUDED_DIR_NAMES

_UNSET = "_UNSET"                      # segment layoutu pusty/None — nie gubimy klatki po cichu (§1)
MANIFEST_NAME = "_PROJEKCJA.json"

# Presety layoutu = KOD (uniwersalia, jak słowniki solar 5a; D-P1 rekomendacja (a)). Kolumny bazowe
# z `base_rows`. JSON dojdzie, gdy user zażąda własnych layoutów (MINIMAL).
LAYOUTS = {
    "po-obiektach": ("object_canon", "filter_canon"),
    "wbpp-feed": ("object_canon", "telescope_label", "filter_canon"),
}


# ============================================================ PLAN (czysty ODCZYT DB)


@dataclasses.dataclass(frozen=True)
class PlanItem:
    """Jedna klatka → jeden zamierzony link. `src` = pierwsza OBECNA location (R#1). `segments` =
    już-zsanityzowane katalogi layoutu (z `_UNSET`). `dst` liczy `apply` (zna korzeń)."""
    frame_id: int
    src: str
    segments: tuple
    basename: str


@dataclasses.dataclass(frozen=True)
class Projection:
    """Wynik `plan()`: pozycje do zlinkowania + pominięte (brak obecnej kopii — kwarantanna) +
    `multi_present` (ile frame'ów miało >1 obecną kopię; zlinkowano pierwszą, D-P5)."""
    layout: str
    items: list                       # list[PlanItem]
    skipped: list                     # list[(frame_id, reason)]
    multi_present: int = 0


def _segment(row, col):
    """Wartość kolumny bazowej → nazwa katalogu bezpieczna na dysku (SPOT: `naming._sanitize` — ta
    sama konwencja slug co nazwy plików). Pusty/None/brak wiersza oraz `.`/`..` (anty-traversal) →
    `_UNSET`; nie gubimy klatki po cichu ani nie wychodzimy poza korzeń (brief §1/§0)."""
    value = row[col] if row is not None else None
    seg = naming._sanitize(value)
    return _UNSET if seg in ("", ".", "..") else seg


def plan(con, frame_ids, layout="po-obiektach"):
    """Zbuduj PLAN projekcji (czysty odczyt DB, ZERO filesystemu). Dla każdego frame'a: ŹRÓDŁO linku =
    pierwsza OBECNA location (`present_locations`, R#1 — NIE `base_rows`, które daje `MIN(id)` bez
    `present`/`volume`) + SEGMENTY layoutu z `base_rows` (tylko do kategorii). Frame bez obecnej kopii
    → `skipped` (kwarantanna, raport). Wiele obecnych → pierwsza, `multi_present++`. `layout` ∈ LAYOUTS."""
    if layout not in LAYOUTS:
        raise ValueError(f"nieznany layout: {layout!r} (dostępne: {sorted(LAYOUTS)})")
    cols = LAYOUTS[layout]
    ids = sorted(int(i) for i in frame_ids)

    src_by_frame: dict[int, list] = {}
    for r in queries.present_locations(con, ids):
        src_by_frame.setdefault(int(r["frame_id"]), []).append(r)
    seg_by_frame = {int(r["frame_id"]): r for r in queries.base_rows(con, ids)}

    items: list[PlanItem] = []
    skipped: list[tuple] = []
    multi = 0
    for fid in ids:
        present = [r for r in src_by_frame.get(fid, []) if r["location_id"] is not None]
        if not present:
            skipped.append((fid, "brak obecnej kopii (wszystkie present=0)"))
            continue
        if len(present) > 1:
            multi += 1
        src = present[0]["path"]
        seg_row = seg_by_frame.get(fid)
        segments = tuple(_segment(seg_row, c) for c in cols)
        items.append(PlanItem(frame_id=fid, src=src, segments=segments,
                              basename=os.path.basename(src)))
    return Projection(layout=layout, items=items, skipped=skipped, multi_present=multi)


# ============================================================ prymitywy filesystemu (KLINGA)


class ProjectionAbort(Exception):
    """Sonda pierwszego linku wykazała rozjazd (wolumen nie daje hardlinków — SMB dał kopię) → abort
    PRZED masą. Niesie CZĘŚCIOWY `ApplyResult` (co najwyżej 1 utworzony link) do raportu wołającego —
    wzorzec `import_fitsmirror.ImportAbort` (cli.py łapie i raportuje)."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def _assert_excluded_segment(root):
    """Guard §0 CEL-POD-WYKLUCZENIEM: `root` MUSI mieć segment z `EXCLUDED_DIR_NAMES` (case-insensitive
    SET — NIE pojedynczy literał jak dawca). Hardlink = duplikat i-węzła, nieodróżnialny przez `os.walk`
    → dla hardlinków chroni WYŁĄCZNIE prune `dirnames` po nazwie. Brak segmentu → projekcja wróciłaby
    jako wejście skanu (sieroty). Split po OBU separatorach (`/`+`\\`) — przenośne (Windows/POSIX)."""
    parts = [p for p in re.split(r"[\\/]+", str(root)) if p]
    if not any(p.lower() in EXCLUDED_DIR_NAMES for p in parts):
        names = " / ".join(sorted(n.upper() for n in EXCLUDED_DIR_NAMES))   # czytelne, wprost z setu (SPOT)
        raise ValueError(
            f"korzeń projekcji {root} nie zawiera segmentu wykluczonego ({names}) — "
            "projekcja poza wykluczeniem wróciłaby jako wejście skanu")


def _link_to(src, dst, *, do_apply, copy):
    """Status src→KONKRETNY dst, ZERO nadpisania (§0). Zwraca `(status, reason|None)`:
    `would-link` (DRY, cel wolny) · `linked` (utworzony) · `exists` (ten sam i-węzeł, idempotentnie
    pomiń) · `conflict` (cel z INNYM i-węzłem — NIE clobber) · `verify_bad` (po `os.link` inny i-węzeł
    = SMB kopia) · `error` (I/O, np. EXDEV cross-wolumen → rada `--copy`). Odczyty stanu celu
    (`exists`/`stat`) działają też w DRY (raport nad istniejącym drzewem)."""
    try:
        if os.path.exists(dst):
            if os.stat(dst).st_ino == os.stat(src).st_ino:
                return "exists", None
            return "conflict", "cel istnieje z innym i-węzłem (nie nadpisuję)"
        if not do_apply:
            return "would-link", None
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if copy:
            shutil.copy2(src, dst)                 # kopia bajtów (cross-wolumen; EXDEV omijamy)
        else:
            os.link(src, dst)                      # ten sam wolumen, zero bajtów
            if os.stat(src).st_ino != os.stat(dst).st_ino:
                return "verify_bad", "cel po os.link ma inny i-węzeł (SMB kopia?)"
        return "linked", None
    except OSError as exc:                         # EXDEV / brak uprawnień / znikłe źródło
        return "error", f"{type(exc).__name__}: {exc}"


def _verify_content(src, dst, nbytes=65536):
    """PEŁNA sonda tożsamości linku (port `wbpp_feed.py:268`): i-węzeł + rozmiar + prefiks treści.
    Sam `st_ino` za słaby — SMB potrafi zwrócić kopię o tym samym/zerowym ino; odczyt `nbytes` bajtów
    rozstrzyga. `True` = prawdziwy hardlink (ta sama treść pod tym samym i-węzłem)."""
    ss, ds = os.stat(src), os.stat(dst)
    if ss.st_ino != ds.st_ino or ss.st_size != ds.st_size:
        return False
    with open(src, "rb") as a, open(dst, "rb") as b:
        return a.read(nbytes) == b.read(nbytes)


# ============================================================ APPLY (czysta MUTACJA filesystemu)


@dataclasses.dataclass(frozen=True)
class LinkResult:
    frame_id: int
    src: str
    dst: str
    status: str                       # would-link|linked|exists|conflict|verify_bad|error|skipped
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class ApplyResult:
    root: str
    layout: str
    do_apply: bool
    copy: bool
    results: list                     # list[LinkResult] — pełny per-frame (items + skipped z planu)
    cancelled: bool = False

    @property
    def counts(self) -> dict:
        c: dict = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c


def apply(projection, root, *, do_apply, copy=False, now=None, manifest=None,
          progress: Callable[[int, int, str, str], None] | None = None,
          should_cancel: Callable[[], bool] | None = None) -> ApplyResult:
    """Zmaterializuj PLAN w drzewo `<root>/<segmenty>/<basename>`. `do_apply=False` = DRY (sonduje stan
    celu, ZERO tworzenia). `do_apply=True` = realne linki/kopie. Guard §0 (`_assert_excluded_segment`)
    PRZED czymkolwiek. Pierwszy realny hardlink (nie `copy`) sondowany PEŁNYM `_verify_content` → rozjazd
    = `ProjectionAbort` (częściowy wynik: 1 link). `progress(done,total,dst,status)` po KAŻDYM frame'ie
    (Qt-wolne). `should_cancel` PRZED frame'em (anulowanie na granicy pliku). Przy `do_apply` pisze
    `_PROJEKCJA.json` obok korzenia (PLIK, nie DB). Pominięte z planu dochodzą jako `skipped`."""
    _assert_excluded_segment(root)
    if do_apply:
        os.makedirs(root, exist_ok=True)           # korzeń istnieje dla linków I manifestu (KLINGA)

    results: list[LinkResult] = []
    cancelled = False
    first_hardlink_checked = False
    total = len(projection.items)
    done = 0

    for item in projection.items:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        dst = os.path.join(root, *item.segments, item.basename)
        status, reason = _link_to(item.src, dst, do_apply=do_apply, copy=copy)

        # Sonda PIERWSZEGO realnie utworzonego hardlinka (nie `copy`): rozjazd = TWARDY ABORT przed
        # masą (§0). „Realnie utworzony" = `linked` (i-węzeł ok w `_link_to`) LUB `verify_bad`
        # (szybki i-węzeł już padł). Bez tego SMB-kopia zlinkowałaby całą masę zamiast abortować.
        if do_apply and not copy and status in ("linked", "verify_bad") and not first_hardlink_checked:
            first_hardlink_checked = True
            if status == "verify_bad" or not _verify_content(item.src, dst):
                results.append(LinkResult(item.frame_id, item.src, dst, "verify_bad",
                                          reason or "sonda pierwszego linku: cel nie jest hardlinkiem (i-węzeł/treść)"))
                partial = ApplyResult(root, projection.layout, do_apply, copy, results, cancelled)
                raise ProjectionAbort(
                    "pierwszy link nie przeszedł sondy tożsamości (i-węzeł/rozmiar/treść) — "
                    "wolumen nie wspiera hardlinków? włącz tryb kopii", partial)

        results.append(LinkResult(item.frame_id, item.src, dst, status, reason))
        done += 1
        if progress is not None:
            progress(done, total, dst, status)

    for fid, reason in projection.skipped:         # kwarantanna z planu → wynik
        results.append(LinkResult(fid, "", "", "skipped", reason))

    result = ApplyResult(root, projection.layout, do_apply, copy, results, cancelled)
    if do_apply:
        _write_manifest(root, result, now=now, manifest=manifest)
    return result


def _write_manifest(root, result: ApplyResult, *, now, manifest):
    """Zapisz `_PROJEKCJA.json` obok korzenia (PLIK, nie DB — projekcja efemeryczna, JEDNA-KLINGA
    nietknięta; brief §3). Snapshot: layout/korzeń/tryb/ts/liczności + `manifest` wołającego
    (perspektywa/filtr/wolumen). `open(...,'w')` żyje w tej klindze (DOOR meta-testu)."""
    payload = {
        "layout": result.layout,
        "root": root,
        "copy": result.copy,
        "ts": now,
        "n_items": len(result.results),
        "counts": result.counts,
    }
    if manifest:
        payload.update(manifest)
    path = os.path.join(root, MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
