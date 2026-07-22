"""DRUGA KLINGA — jedyny obramkowany dom MUTACJI PLIKÓW (KROK 4 scalenia, brief PLAN_gui_writeback).

Odpowiednik `repo.py` dla plików: writeback nagłówków FITS to JEDYNY sankcjonowany zapis na dysk
usera (poza nim pliki = zimny magazyn, `safety.py`). Statyczny meta-tripwir AST
(`tests/test_writeback_safety.py`) pilnuje, że `os.replace`/`writeto`/`tempfile`/`os.remove` żyją
WYŁĄCZNIE tutaj (wzorzec `mover.py`/`eraser.py` Custosa, przełożony z zakazu DML poza `repo.py`).

Dwie warstwy:
1. WRITER (port dawcy `fits_io.write_changes`/`write_full_header`): atomowy zapis nagłówka —
   plik tymczasowy w tym samym katalogu + `os.replace` (atomowo na wolumenie). Kontrola
   `header_hash` PRZED zapisem (niezgodny → 'blocked', NIE pisze). Hash PO zapisie liczony z
   ZAPISANEGO pliku przez `scan.read_fits_meta` (astropy normalizuje formatowanie przy `writeto`
   — hash „z pamięci" nie pasowałby do pliku; brief T3, lekcja dawcy `fits_io.py:289`).
2. ORKIESTRACJA (`commit`/`undo`): grupuje `pending_changes` po LOCATION, per plik zapisuje i
   RE-SYNCUJE bazę przez `scan.ingest_record(actor="user:local")` — REUŻYWA znanej-ścieżki skanu
   (SPOT, brief §3/R#2): `refresh_location` odświeża fakty kopii + zeznanie + WYMIANĘ `cards` +
   przelicza `frame.camera_id`/`kind` (`event(frame.rederived)`). Bespoke writer POMINĄŁBY rederive
   → config na stęchłej kamerze. KAŻDY re-sync emituje eventy (fakt domenowy = mutacja pliku);
   staging (backup/status/commit) jest transient, BEZ eventu (brief §3/R#1).

Kolejność PLIK→DB (brief T8): `os.replace` PIERWSZY, potem re-sync DB; crash pomiędzy → plik
zmieniony, DB stęchłe, kotwicą naprawy jest RE-SKAN (`header_hash` mismatch → refresh). Backup undo
zapisany PO udanym `os.replace`. Utrwalanie per plik (funkcje stagingu `repo` commitują od razu),
więc anulowanie na granicy pliku jest bezpieczne: pliki już zapisane zostają 'applied', reszta
'pending' (wznawialne).
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3
import tempfile
from collections.abc import Callable

from astropy.io import fits

from . import repo, scan

# ============================================================ WRITER (port dawcy fits_io)


@dataclasses.dataclass(frozen=True)
class WriteOp:
    """Operacja zapisu karty. `value` jako string + `value_type` (jak w `pending_changes`)."""
    keyword: str
    op: str  # 'set' | 'add'
    value: object
    value_type: str
    idx: int | None = None
    comment: str | None = None


@dataclasses.dataclass(frozen=True)
class WriteResult:
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None
    post_hash: str | None  # header_hash PO zapisie (z ZAPISANEGO pliku) — kontrola undo + kolejny zapis
    backup_text: str | None = None  # pełny nagłówek SPRZED zapisu (undo)


def _coerce(value, value_type: str):
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("t", "true", "1", "yes")
    return str(value)


def _count_keyword(hdr, keyword: str) -> int:
    return sum(1 for c in hdr.cards if c.keyword == keyword)


def _set_nth(hdr, keyword: str, n: int, value, comment: str | None) -> None:
    seen = -1
    for card in hdr.cards:
        if card.keyword == keyword:
            seen += 1
            if seen == n:
                card.value = value
                if comment is not None:
                    card.comment = comment
                return
    raise KeyError(f"{keyword}[{n}] nie istnieje w naglowku")


def _apply_op(hdr, op: WriteOp) -> None:
    value = _coerce(op.value, op.value_type)
    if op.op == "add":
        # Jawne dodanie BRAKUJACEGO keyworda (astropy dopisuje na koniec). Obrona przed wyscigiem:
        # gdy keyword juz jest, `add` nie nadpisuje cicho (to robi `set`).
        if _count_keyword(hdr, op.keyword) > 0:
            raise ValueError(f"add: keyword '{op.keyword}' juz istnieje (uzyj set)")
        hdr[op.keyword] = (value, op.comment) if op.comment is not None else value
        return
    if op.op == "set":
        if (op.idx in (None, 0)) and _count_keyword(hdr, op.keyword) <= 1:
            hdr[op.keyword] = (value, op.comment) if op.comment is not None else value
        else:
            _set_nth(hdr, op.keyword, op.idx or 0, value, op.comment)
        return
    raise ValueError(f"nieznana operacja: {op.op!r}")


def _post_hash(path: str) -> str:
    """header_hash z ZAPISANEGO pliku — LICZONY TĄ SAMĄ formułą co skan (`scan.read_fits_meta` →
    `scan._header_hash`), więc przyszły re-skan i undo-guard dostają identyczny hash (brief T3)."""
    return scan.read_fits_meta(path).header_hash


def write_changes(path, ops: list[WriteOp], expected_hash: str | None) -> WriteResult:
    """Atomowo zapisz zmiany w nagłówku wybranego HDU. Kontrola `header_hash`: nagłówek na dysku ≠
    `expected_hash` → 'blocked', NIE pisze. Po zapisie zwraca `post_hash` z zapisanego pliku +
    `backup_text` (pełny nagłówek sprzed zmian → undo). Port dawcy `fits_io.write_changes`."""
    path = os.fspath(path)
    tmp: str | None = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdul:
            index, hdu = scan._select_hdu(hdul)
            hdr = hdu.header
            current = scan._header_hash(hdr)
            if expected_hash is not None and current != expected_hash:
                return WriteResult("blocked", "header_hash mismatch", None)
            backup_text = hdr.tostring()  # pełny nagłówek SPRZED zmian → undo
            for op in ops:
                _apply_op(hdr, op)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            hdul.writeto(tmp, overwrite=True)
        # Poza `with`: uchwyt oryginału zwolniony (Windows) → podmiana.
        os.replace(tmp, path)
        tmp = None
        post = _post_hash(path)  # T3: hash z ZAPISANEGO pliku, nie z pamięci
    except Exception as exc:  # noqa: BLE001 — raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return WriteResult("applied", None, post, backup_text)


def write_full_header(path, header_text: str, expected_hash: str | None) -> WriteResult:
    """Atomowo przepisz CAŁY nagłówek wybranego HDU z `header_text` (ścieżka undo). Kontrola
    `header_hash` jak w `write_changes` (dysk ≠ `expected_hash` → 'blocked'). `header_text` =
    wcześniejszy `hdr.tostring()`; odtwarzamy przez `Header.fromstring`. Dane nietknięte (zmienia
    się `file_sha1`, `sha1_data` zostaje). Port dawcy `fits_io.write_full_header`."""
    path = os.fspath(path)
    tmp: str | None = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdul:
            index, hdu = scan._select_hdu(hdul)
            current = scan._header_hash(hdu.header)
            if expected_hash is not None and current != expected_hash:
                return WriteResult("blocked", "header_hash mismatch", None)
            hdu.header = fits.Header.fromstring(header_text)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            hdul.writeto(tmp, overwrite=True)
        os.replace(tmp, path)
        tmp = None
        post = _post_hash(path)
    except Exception as exc:  # noqa: BLE001
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return WriteResult("applied", None, post, header_text)


# ============================================================ odczyty stagingu (core — literały)


def pending_for_run(con, run_id):
    """Wpisy stagingu przebiegu (do commitu i do szuflady GUI). Kolejność `id` = kolejność stagingu."""
    return con.execute(
        "SELECT id, location_id, keyword, idx, op, old_value, new_value, new_type, new_comment, "
        "       expected_header_hash, status, reason "
        "FROM pending_changes WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def backups_for_commit(con, commit_id):
    """Backupy nagłówków commitu (do undo)."""
    return con.execute(
        "SELECT id, location_id, hdu_index, header_text, post_hash "
        "FROM header_backups WHERE commit_id = ? ORDER BY id",
        (commit_id,),
    ).fetchall()


def _location(con, location_id):
    """Wiersz location potrzebny do zapisu: path, volume, header_hash, hdu_index, compressed, present."""
    return con.execute(
        "SELECT id, frame_id, volume, path, header_hash, hdu_index, compressed, present "
        "FROM location WHERE id = ?",
        (location_id,),
    ).fetchone()


# ============================================================ ORKIESTRACJA (commit / undo)


@dataclasses.dataclass(frozen=True)
class FileResult:
    location_id: int
    path: str
    status: str  # 'applied' | 'blocked' | 'failed' | 'skipped' | 'restored'
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class CommitResult:
    run_id: str
    commit_id: int | None  # None gdy nic nie zapisano
    applied: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    skipped: list[FileResult]
    cancelled: bool = False


@dataclasses.dataclass(frozen=True)
class UndoResult:
    commit_id: int
    restored: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    cancelled: bool = False


def _group_by_location(rows) -> list[tuple[int, list]]:
    """Grupuj wpisy stagingu po location_id, zachowując kolejność pierwszego wystąpienia."""
    order: list[int] = []
    groups: dict[int, list] = {}
    for r in rows:
        lid = int(r["location_id"])
        if lid not in groups:
            groups[lid] = []
            order.append(lid)
        groups[lid].append(r)
    return [(lid, groups[lid]) for lid in order]


def _resync(con, path, volume, *, now, actor="user:local"):
    """RE-SYNC bazy po mutacji pliku — REUŻYWA znanej-ścieżki skanu (SPOT, R#2). `scan_file`
    (read-only, świeże hasze/nagłówek/karty) → `ingest_record`: `refresh_location` odświeża fakty
    kopii + zeznanie + `cards` + `frame.camera_id/kind` z eventami (actor="user:local"). Wymaga
    BRAKU otwartej transakcji (refresh bierze BEGIN IMMEDIATE) — funkcje stagingu `repo` commitują
    same, więc jest czysto."""
    rec = scan.scan_file(path)
    scan.ingest_record(con, rec, volume=volume, now=now, summary=scan.ScanSummary(), actor=actor)


def commit(con, run_id, *, now, clock=None,
           progress: Callable[[int, int, str, str], None] | None = None,
           should_cancel: Callable[[], bool] | None = None) -> CommitResult:
    """Zapisz `pending_changes` (status 'pending') przebiegu do plików. Grupuje po LOCATION, per plik:
    kontrola `header_hash` (kotwica `expected_header_hash` ze stagingu, R#7) → `write_changes`
    (`os.replace`) → backup + `post_hash` → RE-SYNC (`refresh_location` przez `ingest_record`) →
    status 'applied'. Utrwalanie per plik (funkcje `repo` commitują), więc anulowanie
    (`should_cancel` PRZED plikiem) zostawia zapisane 'applied', resztę 'pending'. `progress(done,
    total, path, status)` po KAŻDYM pliku. Callbacki Qt-wolne (GUI podaje je z wątku roboczego).

    Bramki defensywne (makro już odsiało przy stagingu, ale stan mógł się zmienić): brak location /
    `present=0` / `compressed` → skipped z powodem, wpisy 'skipped'. `clock` = źródło `applied_at`
    commitu (domyślnie `now`).

    PORAŻKA BACKUPU po udanym zapisie (D-X-14) → 'failed' z powodem, NIE wyjątek: plik jest już
    zmieniony, więc pętla musi go domknąć (re-sync + status), a nie zostawić przebiegu w połowie."""
    clock = clock or (lambda: now)
    pending = [r for r in pending_for_run(con, run_id) if r["status"] == "pending"]
    groups = _group_by_location(pending)
    total = len(groups)

    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    commit_id: int | None = None
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    def _mark(rows, status, reason):
        for r in rows:
            repo.set_pending_status(con, pending_id=r["id"], status=status, reason=reason)

    for location_id, rows in groups:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        loc = _location(con, location_id)
        if loc is None:
            _mark(rows, "failed", "brak location w bazie")
            failed.append(FileResult(location_id, "", "failed", "brak location w bazie"))
            _report("", "failed")
            continue
        path = loc["path"]
        if not loc["present"]:
            reason = "kopia zniknęła (present=0)"
            _mark(rows, "skipped", reason)
            skipped.append(FileResult(location_id, path, "skipped", reason))
            _report(path, "skipped")
            continue
        if loc["compressed"]:
            reason = "skompresowany master — edycja poza krokiem 4"
            _mark(rows, "skipped", reason)
            skipped.append(FileResult(location_id, path, "skipped", reason))
            _report(path, "skipped")
            continue

        ops = [WriteOp(keyword=r["keyword"], op=r["op"], value=r["new_value"],
                       value_type=r["new_type"], idx=r["idx"], comment=r["new_comment"])
               for r in rows]
        expected = rows[0]["expected_header_hash"]  # kotwica stagingu (R#7)
        res = write_changes(path, ops, expected)  # tu następuje os.replace

        if res.status == "applied":
            assert res.backup_text and res.post_hash
            if commit_id is None:
                commit_id = repo.insert_commit(con, run_id=run_id, now=clock(),
                                               summary=f"run {run_id}")
            # Backup PO mutacji pliku — jego porażka NIE może wywalić pętli (D-X-14): plik jest już
            # zmieniony, więc wyjątek zostawiłby resztę przebiegu nietkniętą, a TEN plik bez re-syncu
            # i bez statusu. Zamiast tego: re-sync (baza MUSI opisywać bajty, które leżą na dysku)
            # + status 'failed' z powodem — „zapisane, ale nieodwracalne" jest faktem do zobaczenia,
            # nie do zgadnięcia. (`hdu_index` NULL dla XISF już nie wybucha — migracja 0007.)
            backup_error = None
            try:
                repo.insert_header_backup(
                    con, commit_id=commit_id, location_id=location_id, hdu_index=loc["hdu_index"],
                    header_text=res.backup_text, post_hash=res.post_hash)
            except sqlite3.Error as exc:
                backup_error = f"plik ZAPISANY, ale backup do undo NIE powstał: {type(exc).__name__}: {exc}"
            _resync(con, path, loc["volume"], now=now)      # PLIK→DB (T8)
            if backup_error is not None:
                _mark(rows, "failed", backup_error)
                failed.append(FileResult(location_id, path, "failed", backup_error))
                _report(path, "failed")
                continue
            _mark(rows, "applied", None)
            applied.append(FileResult(location_id, path, "applied"))
            _report(path, "applied")
        elif res.status == "blocked":
            _mark(rows, "blocked", res.reason)
            blocked.append(FileResult(location_id, path, "blocked", res.reason))
            _report(path, "blocked")
        else:
            _mark(rows, "failed", res.reason)
            failed.append(FileResult(location_id, path, "failed", res.reason))
            _report(path, "failed")

    return CommitResult(run_id, commit_id, applied, blocked, failed, skipped, cancelled)


# ============================================================ RENAME "Nazwy z faktów" (trzecia operacja)
# Rename PLIKU = mutacja → mieszka w tej klindze (jak os.replace writebacku). Prymityw `os.rename`
# (NIE `os.replace`): na Windows (tor R:/NAS) rzuca `FileExistsError` gdy cel istnieje = twardy backstop.
# Anty-clobber DWUWARSTWOWY (R3 #1/#3): (1) `os.path.exists(new)` — brama PRZENOŚNA (na POSIX `os.rename`
# CICHO nadpisuje, więc rename-fail sam nie wystarcza — R3-P2 #3); (2) `repo.relocate_location` re-sprawdza
# `UNIQUE(volume,new_path)` atomowo. Kolejność commitu: DB/dysk-check → `os.rename` → `relocate_location`
# (UPDATE path + event, T8: plik-first; crash pomiędzy → re-skan naprawia). Wiersz 'applied' sam jest
# rekordem undo. `os.rename` żyje TU (meta-test: `rename` ∈ OS_MUTATORS, DOOR=writeback.py).


@dataclasses.dataclass(frozen=True)
class RenameFileResult:
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None


def rename_file(old_path, new_path) -> RenameFileResult:
    """Prymityw renamu pliku (KLINGA). Brama anty-clobber: źródło istnieje ORAZ cel NIE istnieje na
    dysku (przenośne) → `os.rename` (Windows: `FileExistsError` przy wyścigu = backstop). Rename w tym
    samym katalogu = atomowy na wolumenie. Zwraca status; wołający (`commit_renames`) mapuje na staging."""
    old_path = os.fspath(old_path)
    new_path = os.fspath(new_path)
    try:
        if not os.path.exists(old_path):
            return RenameFileResult("blocked", "źródło nie istnieje na dysku")
        if os.path.exists(new_path):
            return RenameFileResult("blocked", "cel już istnieje na dysku (anty-clobber)")
        os.rename(old_path, new_path)
    except Exception as exc:  # noqa: BLE001 — raport zamiast wyjątku w warstwie zapisu
        return RenameFileResult("failed", f"{type(exc).__name__}: {exc}")
    return RenameFileResult("applied", None)


def renames_for_run(con, run_id):
    """Wpisy stagingu renamu przebiegu (commit + szuflada GUI). Kolejność `id` = kolejność stagingu."""
    return con.execute(
        "SELECT id, location_id, old_path, new_path, expected_mtime, status, reason "
        "FROM pending_renames WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def _location_rename(con, location_id):
    """Wiersz location do renamu: id, volume, path, mtime, present (kotwica anty-stale)."""
    return con.execute(
        "SELECT id, volume, path, mtime, present FROM location WHERE id = ?",
        (location_id,),
    ).fetchone()


def commit_renames(con, run_id, *, now,
                   progress: Callable[[int, int, str, str], None] | None = None,
                   should_cancel: Callable[[], bool] | None = None) -> CommitResult:
    """Zapisz `pending_renames` (status 'pending') przebiegu na dysk. Per wiersz: kotwica (present +
    `mtime`==staged + `path`==`old_path` + brak wiersza `location(volume,new_path)` — R3 #3) →
    `rename_file` (`os.rename`, anty-clobber dyskowy R3 #1) → `repo.relocate_location` (UPDATE + event,
    NIE ingest — R2 #1). Kotwica-mtime niezmienna po renamie (rename nie tyka treści), więc re-commit
    po udanym renamie widzi już `path==new_path` → relocate idempotentny. Utrwalanie per plik (funkcje
    `repo` commitują), więc anulowanie zostawia zrobione 'applied', resztę 'pending'. `progress(done,
    total, path, status)` po KAŻDYM pliku (Qt-wolne). Zwraca `CommitResult` (`commit_id` zawsze None —
    rename bez tabeli commitów; wiersz 'applied' sam jest undo-rekordem)."""
    pending = [r for r in renames_for_run(con, run_id) if r["status"] == "pending"]
    total = len(pending)
    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for r in pending:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        rid, location_id, old_path, new_path = r["id"], r["location_id"], r["old_path"], r["new_path"]
        loc = _location_rename(con, location_id)
        if loc is None:
            repo.set_rename_status(con, rename_id=rid, status="failed", reason="brak location")
            failed.append(FileResult(location_id, old_path, "failed", "brak location"))
            _report(old_path, "failed")
            continue
        if not loc["present"]:
            reason = "kopia zniknęła (present=0)"
            repo.set_rename_status(con, rename_id=rid, status="skipped", reason=reason)
            skipped.append(FileResult(location_id, old_path, "skipped", reason))
            _report(old_path, "skipped")
            continue
        # Kotwica anty-stale: plik nietknięty od podglądu (mtime + ścieżka).
        if loc["mtime"] != r["expected_mtime"] or loc["path"] != old_path:
            reason = "plik zmieniony od podglądu (mtime/ścieżka)"
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue
        # Anty-clobber W BAZIE PRZED renamem (R3 #3): brak INNEGO wiersza z celem (torn-state guard).
        db_clash = con.execute(
            "SELECT id FROM location WHERE volume = ? AND path = ? AND id <> ?",
            (loc["volume"], new_path, location_id)).fetchone()
        if db_clash is not None:
            reason = f"cel zajęty w bazie (location:{db_clash['id']})"
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue

        res = rename_file(old_path, new_path)          # tu następuje os.rename
        if res.status == "applied":
            try:
                repo.relocate_location(con, location_id=location_id, new_path=new_path, now=now)
            except ValueError as exc:                  # wyścig DB po renamie (rzadki torn-state)
                repo.set_rename_status(con, rename_id=rid, status="failed", reason=str(exc))
                failed.append(FileResult(location_id, new_path, "failed", str(exc)))
                _report(new_path, "failed")
                continue
            repo.set_rename_status(con, rename_id=rid, status="applied", reason=None)
            applied.append(FileResult(location_id, new_path, "applied"))
            _report(new_path, "applied")
        elif res.status == "blocked":
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=res.reason)
            blocked.append(FileResult(location_id, old_path, "blocked", res.reason))
            _report(old_path, "blocked")
        else:
            repo.set_rename_status(con, rename_id=rid, status="failed", reason=res.reason)
            failed.append(FileResult(location_id, old_path, "failed", res.reason))
            _report(old_path, "failed")

    return CommitResult(run_id, None, applied, blocked, failed, skipped, cancelled)


def undo_renames(con, run_id, *, now,
                 progress: Callable[[int, int, str, str], None] | None = None,
                 should_cancel: Callable[[], bool] | None = None) -> UndoResult:
    """Cofnij rename przebiegu: dla wierszy 'applied' odwrotny `os.rename` (new→old) pod TĄ SAMĄ bramą
    anty-clobber + `relocate_location` z powrotem na `old_path`. Kolejność odwrotna (jak stos). Gdy plik
    nie stoi na `new_path` (zmieniony od commitu) → 'blocked'. Udany rewert → status 'skipped' (powód
    „cofnięto") — dwukrotne undo pomija (tylko 'applied' cofane). `commit_id` w wyniku = run przebiegu
    (rename bez tabeli commitów). Bramka bezpieczna per plik."""
    applied_rows = [r for r in renames_for_run(con, run_id) if r["status"] == "applied"]
    total = len(applied_rows)
    restored: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for r in reversed(applied_rows):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        rid, location_id, old_path, new_path = r["id"], r["location_id"], r["old_path"], r["new_path"]
        loc = _location_rename(con, location_id)
        if loc is None or loc["path"] != new_path:
            reason = "plik nie stoi na nazwie z commitu"
            blocked.append(FileResult(location_id, new_path, "blocked", reason))
            _report(new_path, "blocked")
            continue
        res = rename_file(new_path, old_path)          # odwrotny os.rename
        if res.status == "applied":
            try:
                repo.relocate_location(con, location_id=location_id, new_path=old_path, now=now)
            except ValueError as exc:
                repo.set_rename_status(con, rename_id=rid, status="failed", reason=str(exc))
                failed.append(FileResult(location_id, old_path, "failed", str(exc)))
                _report(old_path, "failed")
                continue
            repo.set_rename_status(con, rename_id=rid, status="skipped", reason="cofnięto (undo)")
            restored.append(FileResult(location_id, old_path, "restored"))
            _report(old_path, "restored")
        elif res.status == "blocked":
            blocked.append(FileResult(location_id, new_path, "blocked", res.reason))
            _report(new_path, "blocked")
        else:
            failed.append(FileResult(location_id, new_path, "failed", res.reason))
            _report(new_path, "failed")

    return UndoResult(run_id, restored, blocked, failed, cancelled)


def undo(con, commit_id, *, now,
         progress: Callable[[int, int, str, str], None] | None = None,
         should_cancel: Callable[[], bool] | None = None) -> UndoResult:
    """Cofnij commit: przepisz pełne nagłówki z `header_backups` (obsługuje set I add BEZ delete).
    Kontrola `header_hash` = `post_hash` z backupu (plik zmieniony od commitu → 'blocked'; dwukrotne
    undo naturalnie 'blocked'). Po udanym zapisie RE-SYNC bazy (refresh). `progress`/`should_cancel`
    jak w `commit` (per plik, granica bezpieczna)."""
    backups = backups_for_commit(con, commit_id)
    total = len(backups)
    restored: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for b in backups:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        loc = _location(con, int(b["location_id"]))
        if loc is None:
            failed.append(FileResult(int(b["location_id"]), "", "failed", "brak location w bazie"))
            _report("", "failed")
            continue
        path = loc["path"]
        res = write_full_header(path, b["header_text"], b["post_hash"])
        if res.status == "applied":
            _resync(con, path, loc["volume"], now=now)
            restored.append(FileResult(loc["id"], path, "restored"))
            _report(path, "restored")
        elif res.status == "blocked":
            blocked.append(FileResult(loc["id"], path, "blocked", res.reason))
            _report(path, "blocked")
        else:
            failed.append(FileResult(loc["id"], path, "failed", res.reason))
            _report(path, "failed")

    return UndoResult(commit_id, restored, blocked, failed, cancelled)
