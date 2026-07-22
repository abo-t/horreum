"""Import zasilający z bazy dawcy `fitsmirror.db` — PF-3 przejścia (brief §4).

Świeżą bazę Horreum zasila WPROST z cache'owanych zeznań dawcy (decyzja C Zdzisława 2026-07-02:
import teraz, rytualny pełny skan = końcowy sprawdzian), zamiast czytać 839 GB z NAS. Dawca jest
autorytatywny PO falsyfikatorze kierunku (pre-flight liczy odciski z dysku dla próbki i porównuje).

Przebieg (`run_import`):
  1. PRE-FLIGHT (twarde, EXPECT — każde złamanie = `ImportAbort`, zero zapisu):
     dawca `user_version==4` i komplet zeznań (status='ok', tożsamość obliczalna); baza docelowa
     PUSTA (rama ŚWIEŻA-BAZA — bramki §4.6 liczą od zera); root = commonpath ścieżek dawcy przez
     `canonize_root` (guard UNC, forma literowa — §0); `volume_serial(root)` ustalony (None →
     abort, brama przyrostowa przyszłych skanów musi trafiać); ZBIORY ścieżek: każdy plik dawcy
     osiągalny `os.stat` MUSI być w pełnym listingu `iter_headers` (rozjazd = zatrucie tożsamości:
     casing/wykluczenia → przyszły skan zdublowałby lokacje — abort); braki (stat nieudany) →
     `skipped` §4.3; nadwyżka listingu = nowe pliki (XISF ~331 — domyka PF-4, tylko raport).
  2. FALSYFIKATOR KIERUNKU C (R1#6): 5 losowych + celowana próbka plików naprawianych PO
     `scanned_at` (z `header_backups`×`commits`; gdy pusta — ostatnio naprawiane) → `scan_file`
     liczy z dysku i porównuje z dawcą. Rozjazd `sha1_data` GDZIEKOLWIEK = STOP (spadek do
     pełnego skanu B). Rozjazd samych faktów kopii (file_sha1/header_hash/mtime) na
     późno-naprawianych = odnotuj → CAŁA podgrupa późno-naprawianych czytana z dysku
     (`scan_file`) zamiast syntezy z dawcy; ten sam rozjazd POZA podgrupą = stan nieoczekiwany
     (EXPECT) → abort.
  3. PĘTLA po `files` dawcy (sort po path): karty dawcy → `Card` → `header_dict_from_cards`
     (synteza dict-a, kontrakt 1:1 z `read_fits_header` — PF-1) → `ScanRecord` (`mtime` ze
     ŚWIEŻEGO `os.stat` w derywacji `_mtime_iso`; `file_sha1`/`header_hash`/`size_bytes` dawcy —
     ufamy PO falsyfikatorze) → `ingest_record` z `actor='import:fitsmirror'` (jedna klinga;
     header+cards+event w jednej transakcji — repo.record_header). Plik nieosiągalny → pomiń +
     `event(frame.review)` target `sha1:<sha1_data>` (W1; kotwica stabilna).
  4. Po pętli: `run_grouper` + `run_resolver` — te same funkcje co pipeline GUI.
  5. BRAMKI LICZBOWE (§4.6 — versus dawca W CHWILI importu, ze STANU, MINUS skipped):
     frame/location == files−skipped; cards == cards dawcy nie-skipped (podgrupa przeliczana
     z dysku wchodzi liczbą realnie odczytanych kart); teleskopy/kamery/configi == niezależna
     derywacja z zeznań (strip+fold ASCII jak `COLLATE NOCASE`, `normalize_camera` — TA SAMA
     derywacja co kanon, więc zastrzeżenie R2#11 TRIM≠strip nie powstaje); review sprzętu ze
     STANU: `camera_id NULL`==0, `config_id NULL`==0, `pixel_conflict`==0. Naruszenie →
     `ImportAbort` z pełną listą (summary w wyjątku — liczby nie giną).

Kotwice dawcy 2026-07-02 (§1 briefu): 15 559 plików, 8 teleskopów, 5 kamer, 9 filtrów — bramki
liczone dynamicznie z dawcy, kotwice weryfikuje firsthand Zdzisława w GUI (bramka etapu §5).

Rdzeń Qt-WOLNY (rama IZOLACJA-QT); dawca otwierany WYŁĄCZNIE read-only (`file:...?mode=ro`,
uri=True — rama DAWCA-RO); pliki na `R:` dotykane wyłącznie `os.stat` + odczyt `scan_file`
próbki i podgrupy przeliczanej. Zapis do bazy docelowej WYŁĄCZNIE przez `repo`/`ingest_record`
(jedna klinga); SELECT-y stałymi literałami + `?` (bramka AST §8.1 — także do dawcy).
"""
import os
import random
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import pathname2url

from . import db, repo
from .grouper import run_grouper
from .resolve.cameras import normalize_camera
from .resolver import run_resolver
from .scan import (
    Card, ScanRecord, ScanSummary, canonize_root, header_dict_from_cards, ingest_record,
    iter_headers, scan_file, _mtime_iso,
)
from .volumes import volume_serial

ACTOR = "import:fitsmirror"
DONOR_SCHEMA_VERSION = 4          # user_version dawcy, na którym zbudowany jest ten import (§4.1)
SAMPLE_RANDOM = 5                 # falsyfikator: tylu losowych (R1#6)
SAMPLE_LATE = 12                  # falsyfikator: tylu późno-naprawianych (jak sonda PF-1)


class ImportAbort(RuntimeError):
    """Twarde złamanie pre-flightu/falsyfikatora/bramek (EXPECT — jawny błąd, nie ostrzeżenie).
    `summary` niesie liczby przebiegu, gdy abort padł PO pętli (bramki §4.6) — inaczej None."""

    def __init__(self, message, summary=None):
        super().__init__(message)
        self.summary = summary


@dataclass
class Preflight:
    """Wynik pre-flightu §4.1 — materiał dla pętli i raportu (żadnego zapisu)."""
    root: str                                  # skanonizowany wspólny root ścieżek dawcy
    volume: str                                # serial woluminu (brama przyszłych skanów)
    drive_letter: str                          # litera roota (efemeryczny cache wyświetlania)
    files_total: int = 0                       # wierszy w dawcy
    stats: dict = field(default_factory=dict)  # path -> os.stat_result (jeden pass stat)
    missing: list = field(default_factory=list)      # ścieżki dawcy nieosiągalne → skipped §4.3
    surplus: int = 0                           # listing − dawca (nowe pliki; XISF domyka PF-4)
    surplus_sample: list = field(default_factory=list)   # pierwsze ścieżki nadwyżki (raport)
    verified: list = field(default_factory=list)         # ścieżki sprawdzone falsyfikatorem
    late_repaired: list = field(default_factory=list)    # podgrupa naprawianych po scanned_at
    repaired_registry: frozenset = frozenset()  # naprawione przez HORREUM (D-0722-2), obecne u dawcy
    recompute: frozenset = frozenset()         # ścieżki czytane z dysku zamiast syntezy z dawcy
    notes: list = field(default_factory=list)  # ustalenia raportowane userowi (ASCII)


@dataclass
class ImportSummary:
    """Zliczenia całego przebiegu importu + wyniki bramek §4.6 (`gates` = nazwa →
    (oczekiwane, faktyczne); komplet równości ⇒ `gate_failures` puste)."""
    preflight: Preflight = None
    scan: ScanSummary = None
    group: object = None                       # GroupSummary
    resolve: object = None                     # ResolveSummary
    files_total: int = 0
    imported: int = 0
    skipped: int = 0
    skipped_paths: list = field(default_factory=list)
    recomputed: int = 0                        # pliki podgrupy czytane z dysku (nie z dawcy)
    expected_cards: int = 0                    # suma kart wciągniętych zeznań (bramka `cards`)
    gates: dict = field(default_factory=dict)
    gate_failures: list = field(default_factory=list)


def open_donor(path):
    """Otwórz bazę dawcy WYŁĄCZNIE read-only (URI `mode=ro` — rama DAWCA-RO) i zweryfikuj
    `user_version` (EXPECT: inna wersja = inny kontrakt schematu → abort)."""
    apath = os.path.abspath(str(path))
    if not os.path.isfile(apath):
        raise ImportAbort(f"baza dawcy nie istnieje: {apath}")
    con = sqlite3.connect("file:" + pathname2url(apath) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version != DONOR_SCHEMA_VERSION:
        con.close()
        raise ImportAbort(
            f"dawca ma user_version={version}, import zbudowany na v{DONOR_SCHEMA_VERSION} "
            f"— zweryfikuj schemat dawcy zanim ruszysz")
    return con


def _fold_ascii(s):
    """Fold wielkości liter DOKŁADNIE jak `COLLATE NOCASE` SQLite (tylko ASCII A-Z) — bramka
    teleskopów musi liczyć tą samą równoważnością co UNIQUE kolumny (8 nazw ASCII, świadome)."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def _assert_donor_complete(donor):
    """EXPECT: import stoi na komplecie zeznań dawcy (§1: status='ok' i tożsamość 100%).
    Wiersz 'unreadable' albo bez obliczalnej tożsamości (sha1_data NULL bez degeneracji
    z sha1_file) nie ma czego zaimportować → abort z listą (decyzja przy dawcy, nie tu)."""
    bad = donor.execute(
        "SELECT path, status FROM files WHERE status != 'ok' "
        "OR (sha1_data IS NULL AND (sha1_data_uncomputable = 0 OR sha1_file IS NULL)) "
        "ORDER BY path LIMIT 20").fetchall()
    if bad:
        listing = "; ".join(f"{r['path']} [{r['status']}]" for r in bad)
        raise ImportAbort(
            f"dawca niekompletny ({len(bad)}+ wierszy bez zeznania/tozsamosci): {listing} "
            f"— napraw/doskanuj dawce (fitsmirror), import wymaga kompletu")


def _assert_target_fresh(con):
    """EXPECT (rama ŚWIEŻA-BAZA): bramki §4.6 liczą od zera — niepusta baza docelowa =
    złamanie kontraktu przebiegu (import to zasilenie świeżej bazy, nie dosypka).
    SELECT-y jawnie literałami (bramka AST: SQL ze zmiennej = nieweryfikowalny)."""
    counts = {
        "frame": con.execute("SELECT count(*) FROM frame").fetchone()[0],
        "location": con.execute("SELECT count(*) FROM location").fetchone()[0],
        "event": con.execute("SELECT count(*) FROM event").fetchone()[0],
    }
    for table, n in counts.items():
        if n:
            raise ImportAbort(
                f"baza docelowa nie jest swieza ({table}: {n} wierszy) — import zasila "
                f"WYLACZNIE swieza baze (utworz nowa przez horreum init)")


def _late_repaired(donor):
    """Ścieżki naprawiane PO `scanned_at` (writeback nowszy niż zeznanie dawcy → fakty kopii
    w dawcy potencjalnie stęchłe) + próbka celowana falsyfikatora. Gdy zbiór pusty (dawca
    odświeża zeznanie po writebacku — ustalenie PF-1), celujemy w OSTATNIO naprawiane
    (najświeższy writeback = najpóźniejsza okazja na rozjazd)."""
    rows = donor.execute(
        "SELECT f.path AS path, f.scanned_at AS scanned_at, max(c.applied_at) AS repaired_at "
        "FROM header_backups hb "
        "JOIN commits c ON c.id = hb.commit_id "
        "JOIN files f ON f.id = hb.file_id "
        "GROUP BY f.id ORDER BY repaired_at DESC").fetchall()
    late = [r["path"] for r in rows
            if r["scanned_at"] is not None and r["repaired_at"] is not None
            and r["repaired_at"] > r["scanned_at"]]
    if late:
        return late, late[:SAMPLE_LATE], "naprawiane PO scanned_at"
    return [], [r["path"] for r in rows[:SAMPLE_LATE]], "ostatnio naprawiane (scanned_at nowszy)"


def read_repaired_registry(path):
    """Rejestr napraw HORREUM (D-0722-2 wariant A) — ścieżki lokacji, którym writeback TEJ
    instalacji przepisał nagłówek. Dawca o nich nie wie (jego zeznanie jest sprzed naprawy),
    więc bez rejestru losowa próbka falsyfikatora czytała je jako „dawca stęchły z NIEZNANEGO
    powodu" i abortowała import. Baza otwierana WYŁĄCZNIE read-only (jak dawca — rama DAWCA-RO;
    to cudza żywa baza, import jej nie migruje ani nie tyka)."""
    apath = os.path.abspath(str(path))
    if not os.path.isfile(apath):
        raise ImportAbort(f"baza rejestru napraw nie istnieje: {apath}")
    con = sqlite3.connect("file:" + pathname2url(apath) + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT l.path FROM header_backups hb "
            "JOIN location l ON l.id = hb.location_id").fetchall()
    finally:
        con.close()
    return frozenset(r[0] for r in rows)


def _verify_sample(donor, paths, late_set, registry, notes):
    """Falsyfikator kierunku C (R1#6): dla każdej ścieżki próbki policz odciski Z DYSKU
    (`scan_file`) i porównaj z dawcą. Zwrot: True gdy fakty kopii późno-naprawianych się
    rozjechały (→ podgrupa do przeliczenia z dysku). Rozjazd `sha1_data` = STOP; rozjazd
    faktów POZA późno-naprawianymi I POZA rejestrem napraw Horreum = stan nieoczekiwany
    (EXPECT) → abort.

    DWA rejestry, DWIE dyspozycje (D-0722-2): `late_set` (dawca wie o naprawie, ale jego
    fakty kopii mogą być stęchłe) → przeliczenie CAŁEJ podgrupy z dysku; `registry` (naprawił
    Horreum, dawca nie wie) → sama NOTA, bo zeznanie dawcy jest wtedy spójnym snapshotem
    sprzed naprawy, a to jest baseline tej bramki. Tożsamość (`sha1_data`) sprawdzana tak
    samo w obu — writeback nie rusza danych, więc rozjazd tożsamości zostaje STOPEM."""
    stale_late = False
    for path in paths:
        row = donor.execute(
            "SELECT sha1_file, sha1_data, sha1_data_uncomputable, header_hash, mtime "
            "FROM files WHERE path = ?", (path,)).fetchone()
        rec = scan_file(path)
        if rec.error is not None:
            raise ImportAbort(
                f"falsyfikator: plik probki nieczytelny z dysku: {path} ({rec.error}) "
                f"— sprawdz NAS/plik zanim import ruszy")
        # degenerat (uncomputable) nie ma odcisku danych do porównania — rozstrzyga file_sha1
        if not row["sha1_data_uncomputable"] and rec.sha1_data != row["sha1_data"]:
            raise ImportAbort(
                f"falsyfikator: ROZJAZD sha1_data dawca vs dysk: {path} "
                f"(dawca {row['sha1_data']}, dysk {rec.sha1_data}) — STOP; kierunek C pada, "
                f"spadek do pelnego skanu B (horreum scan)")
        facts_ok = (rec.file_sha1 == row["sha1_file"]
                    and rec.header_hash == row["header_hash"]
                    and _mtime_iso(os.stat(path)) == _mtime_iso_from_epoch(row["mtime"]))
        if facts_ok:
            continue
        if path in late_set:
            stale_late = True
            notes.append(f"fakty kopii stechle na pozno-naprawianym: {path} "
                         f"-> cala podgrupa przeliczana z dysku")
        elif path in registry:
            notes.append(f"fakty kopii stechle na naprawionym przez Horreum: {path} "
                         f"-> zeznanie dawcy sprzed naprawy (baseline), tozsamosc zgodna")
        else:
            raise ImportAbort(
                f"falsyfikator: fakty kopii (file_sha1/header_hash/mtime) rozjechane POZA "
                f"pozno-naprawianymi: {path} — stan nieoczekiwany (dawca stechly szerzej "
                f"niz znany mechanizm writebacku); wyjasnij zanim import ruszy")
    return stale_late


def _mtime_iso_from_epoch(mtime_epoch):
    """mtime dawcy (REAL epoch z `os.stat().st_mtime`) → ISO-8601 UTC — TA SAMA derywacja co
    `_mtime_iso` (porównanie falsyfikatora musi iść znak-w-znak po wspólnym formacie)."""
    class _St:                                 # minimalny nośnik: _mtime_iso czyta .st_mtime
        st_mtime = mtime_epoch
    return _mtime_iso(_St)


def preflight(donor, *, rng_seed=None, repaired_paths=None):
    """Pre-flight §4.1 (twarde, EXPECT; zero zapisu). Zwraca `Preflight` z materiałem pętli
    (stats, missing→skipped, recompute) albo rzuca `ImportAbort`.

    `repaired_paths` = rejestr napraw Horreum (`read_repaired_registry` z ŻYWEJ bazy) — ścieżki,
    dla których stęchłe fakty kopii u dawcy mają ZNANY powód, więc nie są abortem."""
    _assert_donor_complete(donor)

    paths = [r["path"] for r in donor.execute("SELECT path FROM files ORDER BY path")]
    if not paths:
        raise ImportAbort("dawca nie ma zadnych plikow (files puste) — nie ma czego importowac")
    for p in paths:
        if p.startswith("\\\\"):
            raise ImportAbort(
                f"sciezka dawcy w formie UNC ({p!r}) — tozsamosc location.path jest LITEROWA "
                f"(brief §0); dawca musi byc zeskanowany przez litere dysku")

    try:
        common = os.path.commonpath(paths)
    except ValueError as exc:                          # różne dyski/miks form — nie zgadujemy
        raise ImportAbort(f"sciezki dawcy bez wspolnego roota ({exc}) — dawca ma obejmowac "
                          f"jedno drzewo na jednym dysku") from exc
    if os.path.isfile(common):                         # jeden plik → rootem jest jego katalog
        common = os.path.dirname(common)
    root = canonize_root(common)                       # guard UNC + casing z dysku (R3-a1/a2)
    volume = volume_serial(root)
    if volume is None:
        raise ImportAbort(
            f"volume_serial({root!r}) nieustalony — brama przyrostowa przyszlych skanow "
            f"musi trafiac; zamontuj wolumin i powtorz")
    pf = Preflight(root=root, volume=volume, drive_letter=(Path(root).drive or None),
                   files_total=len(paths))

    # jeden pass stat: mtime do pętli + podział osiągalne/braki (braki = skipped §4.3)
    for p in paths:
        try:
            pf.stats[p] = os.stat(p)
        except OSError:
            pf.missing.append(p)

    # zbiory ścieżek (R2#1/R3-a3): stat-OK ⊆ pełny listing — rozjazd zatruwa tożsamość
    # (casing/wykluczenia → przyszły skan dubluje lokacje przy tym samym serialu) → abort
    listing = set(map(str, iter_headers(root)))
    unlisted = sorted(set(pf.stats) - listing)
    if unlisted:
        sample = "; ".join(unlisted[:10])
        raise ImportAbort(
            f"{len(unlisted)} sciezek dawcy osiagalnych na dysku NIE MA w listingu skanu "
            f"(casing albo katalog wykluczony _WBPP/_Review) — przyszly skan zdublowalby "
            f"lokacje; wyjasnij zanim import ruszy. Probka: {sample}")
    surplus = sorted(listing - set(pf.stats) - set(pf.missing))
    pf.surplus = len(surplus)
    pf.surplus_sample = surplus[:10]
    if pf.missing:
        pf.notes.append(f"{len(pf.missing)} sciezek dawcy nieosiagalnych (os.stat) -> skipped")
    if pf.surplus:
        pf.notes.append(f"{pf.surplus} plikow na dysku poza dawca (nowe; XISF domyka PF-4)")

    # falsyfikator kierunku C: 5 losowych + celowana próbka późno-naprawianych
    late, targeted, why = _late_repaired(donor)
    pf.late_repaired = late
    pf.repaired_registry = frozenset(p for p in (repaired_paths or ()) if p in pf.stats)
    if pf.repaired_registry:
        pf.notes.append(f"rejestr napraw Horreum: {len(pf.repaired_registry)} sciezek "
                        f"(znany powod stechlych faktow kopii — nota, nie abort)")
    reachable = sorted(pf.stats)
    rng = random.Random(rng_seed)
    sample = rng.sample(reachable, min(SAMPLE_RANDOM, len(reachable)))
    probe = list(dict.fromkeys(                     # dedup, kolejność: celowane najpierw
        [p for p in targeted if p in pf.stats] + sample))
    pf.notes.append(f"falsyfikator: {len(probe)} plikow (celowane: {why})")
    stale_late = _verify_sample(donor, probe, frozenset(late), pf.repaired_registry, pf.notes)
    pf.verified = probe
    if stale_late:
        pf.recompute = frozenset(p for p in late if p in pf.stats)
    return pf


def _donor_cards(donor, file_id):
    """Karty jednego pliku dawcy jako `Card` (kolumny 1:1 — tabele cards obu baz mają ten sam
    kształt EAV). Sort po (keyword, idx) — `header_dict_from_cards` i tak porządkuje po idx."""
    return [Card(r["keyword"], r["idx"], r["value_raw"], r["value_num"], r["value_type"],
                 r["comment"])
            for r in donor.execute(
                "SELECT keyword, idx, value_raw, value_num, value_type, comment "
                "FROM cards WHERE file_id = ? ORDER BY keyword, idx", (file_id,))]


def _gates(con, summary, axes_seen):
    """Bramki liczbowe §4.6 — versus dawca W CHWILI importu, ze STANU, MINUS skipped.
    `axes_seen` = (telescopes, cameras, configs) zebrane z zeznań w pętli (niezależna derywacja
    Pythonem: strip+fold ASCII jak NOCASE, `normalize_camera` — R2#11 bez TRIM-a SQLite).
    Wypełnia `summary.gates`/`gate_failures`; naruszenie → `ImportAbort` (z summary)."""
    tel_seen, cam_seen, cfg_seen = axes_seen
    expected = {
        "frame": summary.imported,
        "location": summary.imported,
        "cards": summary.expected_cards,
        "telescope": len(tel_seen),
        "camera": len(cam_seen),
        "config": len(cfg_seen),
        "frame.camera_id NULL": 0,             # review sprzętu ze STANU (rama KIND-AWARE/STAN)
        "frame.config_id NULL": 0,
        "camera.pixel_conflict": 0,
    }
    actual = {
        "frame": con.execute("SELECT count(*) FROM frame").fetchone()[0],
        "location": con.execute("SELECT count(*) FROM location").fetchone()[0],
        "cards": con.execute("SELECT count(*) FROM cards").fetchone()[0],
        "telescope": con.execute("SELECT count(*) FROM telescope").fetchone()[0],
        "camera": con.execute("SELECT count(*) FROM camera").fetchone()[0],
        "config": con.execute("SELECT count(*) FROM config").fetchone()[0],
        "frame.camera_id NULL": con.execute(
            "SELECT count(*) FROM frame WHERE camera_id IS NULL").fetchone()[0],
        "frame.config_id NULL": con.execute(
            "SELECT count(*) FROM frame WHERE config_id IS NULL").fetchone()[0],
        "camera.pixel_conflict": con.execute(
            "SELECT count(*) FROM camera WHERE pixel_conflict = 1").fetchone()[0],
    }
    summary.gates = {k: (expected[k], actual[k]) for k in expected}
    summary.gate_failures = [
        f"{k}: oczekiwane {expected[k]}, jest {actual[k]}"
        for k in expected if expected[k] != actual[k]]
    if summary.gate_failures:
        raise ImportAbort(
            "bramki liczbowe importu NIE przeszly: " + "; ".join(summary.gate_failures),
            summary=summary)


def run_import(donor, con, *, now, rng_seed=None, repaired_paths=None, progress=None):
    """Cały przebieg PF-3 na otwartych połączeniach (dawca RO, cel po `db.open_db`): pre-flight →
    pętla → grouper+resolver → bramki. Zwraca `ImportSummary`; twarde złamanie → `ImportAbort`.
    `progress(done, total, path)` wołany po każdym pliku (CLI: heartbeat; Qt tu nie mieszka).
    `repaired_paths` → `preflight` (rejestr napraw Horreum, D-0722-2)."""
    _assert_target_fresh(con)
    pf = preflight(donor, rng_seed=rng_seed, repaired_paths=repaired_paths)

    summary = ImportSummary(preflight=pf, scan=ScanSummary(), files_total=pf.files_total)
    tel_seen, cam_seen, cfg_seen = set(), set(), set()

    rows = donor.execute(
        "SELECT id, path, size, hdu_index, compressed, header_hash, sha1_file, sha1_data, "
        "sha1_data_uncomputable FROM files ORDER BY path").fetchall()
    total = len(rows)
    for done, row in enumerate(rows, start=1):
        path = row["path"]
        st = pf.stats.get(path)
        if st is None:                         # soft-landing §4.3: pomiń + review (kotwica sha1)
            anchor = row["sha1_data"] if row["sha1_data"] is not None else row["sha1_file"]
            repo.flag_frame_review(
                con, sha1=anchor, path=path,
                reason="import: plik dawcy nieosiagalny (os.stat)", now=now, actor=ACTOR)
            summary.skipped += 1
            summary.skipped_paths.append(path)
            if progress is not None:
                progress(done, total, path)
            continue
        if path in pf.recompute:               # podgrupa stęchła: pełne zeznanie z dysku
            rec = scan_file(path)
            summary.recomputed += 1
        else:                                  # tor główny: synteza z zeznania dawcy
            cards = _donor_cards(donor, row["id"])
            rec = ScanRecord(
                path=path, size_bytes=row["size"], mtime=_mtime_iso(st),
                header=header_dict_from_cards(cards), error=None,
                sha1_data=None if row["sha1_data_uncomputable"] else row["sha1_data"],
                file_sha1=row["sha1_file"], header_hash=row["header_hash"],
                hdu_index=row["hdu_index"], compressed=row["compressed"], cards=cards)
        summary.scan.files += 1
        summary.expected_cards += len(rec.cards or ())
        if rec.header is not None:             # niezależna derywacja osi do bramek §4.6
            tel = str(rec.header.get("TELESCOP") or "").strip()
            cam = normalize_camera(rec.header.get("INSTRUME"))
            if tel:
                tel_seen.add(_fold_ascii(tel))
            if cam:
                cam_seen.add(cam)
            if tel and cam:
                cfg_seen.add((_fold_ascii(tel), cam))
        ingest_record(con, rec, volume=pf.volume, drive_letter=pf.drive_letter, tier=None,
                      now=now, summary=summary.scan, actor=ACTOR)
        if progress is not None:
            progress(done, total, path)

    summary.imported = summary.files_total - summary.skipped
    summary.group = run_grouper(con, now=now)          # te same funkcje co pipeline GUI (§4.4)
    summary.resolve = run_resolver(con, now=now)
    _gates(con, summary, (tel_seen, cam_seen, cfg_seen))
    return summary


def import_fitsmirror(donor_path, db_path, *, now, rng_seed=None, progress=None):
    """Wejście CLI: otwórz dawcę (RO) + bazę docelową (utworzy/zmigruje `db.open_db`),
    przeprowadź `run_import`, pozamykaj. Zwraca `ImportSummary` (albo propaguje `ImportAbort`)."""
    donor = open_donor(donor_path)
    try:
        con = db.open_db(db_path)
        try:
            return run_import(donor, con, now=now, rng_seed=rng_seed, progress=progress)
        finally:
            con.close()
    finally:
        donor.close()
