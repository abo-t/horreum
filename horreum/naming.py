"""Rdzeń „Nazwy z faktów" — CZYSTY silnik (wzorzec `macro`/`filter_engine`): ZERO DB, ZERO Qt,
ZERO mutacji plików. Komponuje kanoniczną nazwę pliku z FAKTÓW frame'a (kind/obiekt/filtr/exp/
data-godzina) i prowadzi potok podglądu renamu nad wstrzykiwanymi akcesorami danych.

Dwie warstwy (brief PLAN_nazwy_z_faktow §1/§3):
1. RDZEŃ `compose_name(fakty, dt) → nazwa | problem` — SPOT pod hurtowy rename I przyszły ingest
   świeżej akwizycji (pliki lądują od razu nazwane). Konwencja: **data+godzina NA POCZĄTKU** →
   `YYYYMMDD_HHMMSS_<OBJ>_<KIND>[_<filtr>][_<exp>]_<disc>.<ext>`. Sortuje chronologicznie.
   KIND-AWARE (memory horreum-object-resolution-kind-aware): token obiektu TYLKO dla light/
   master_light — kalibracja ma `object_id=NULL` z DEFINICJI (pominięcie, NIE problem).
2. SILNIK `run_rename(frame_ids, targets_fn=…)` — REUŻYWA POWŁOKI `run_macro` (grupowanie by-frame +
   filtr→compute→preview), ale target-resolution rename-specyficzny: DOPUSZCZA XISF (rename nie tyka
   nagłówka, więc `header_hash NULL` nie przeszkadza — inaczej niż writeback). Zwraca `RenameRun`;
   persist (`pending_renames`) + mutację (`os.rename`) robi WOŁAJĄCY przez `repo`/`writeback`.

DYSKRYMINATOR (D3, rozstrzygnięty R3-P2 #4): prefiks `sha1_data` (12 hex). `frame_id` i licznik-
pozycyjny ODRZUCONE — niedeterministyczne (frame_id nie istnieje przed insertem; licznik zależy od
składu wsadu). `sha1_data` to fakt z bajtów (`hashing.py`), UNIQUE per frame, istnieje PRZED insertem,
przenośny między bazami → nazwa deterministyczna niezależnie od wsadu, kolizja nazw STRUKTURALNIE
niemożliwa (dwie różne klatki → różny prefiks). To domyka SPOT-pod-ingest.

ROZSTRZYGANIE DATY (§2): dwa ekstraktory (`header_dt` z DATE-OBS, `filename_dt` z basename), polityka
`{source, offset_hours}` per homogeniczny wsad. BEZ ZAŁOŻENIA STREFY — pełno-godzinny offset to
prawomocny czas innego stanowiska, nie anomalia. Data-only DATE-OBS → None (zgłoszone jako brak
czasu, NIGDY cicha północ — R3 #10).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# ============================================================ ekstraktory daty-godziny (§2)

# DATE-OBS: ISO z opcjonalnym separatorem T/spacja; ułamek sekund i 'Z' IGNOROWANE (nie przesuwamy
# strefy — offset ustawia user per wsad). Data-only (bez części czasowej) NIE dopasowuje → None
# (brak czasu zgłoszony przez `resolve_dt`, nie cicha północ — R3 #10).
_DTOBS = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})")

# basename: dwa wzorce z REALNYCH danych (§2). Granice `(?<!\d)`/`(?!\d)` bronią przed startem w
# środku dłuższej liczby (fałszywe trafienie regexu — sonda §5b#11).
_FN_PATTERNS = (
    re.compile(r"(\d{4})-(\d{2})-(\d{2})[_-](\d{2})-(\d{2})-(\d{2})"),                # YYYY-MM-DD_HH-MM-SS
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})(?!\d)"),        # YYYYMMDD_HHMMSS
)


def header_dt(date_obs):
    """DATE-OBS (surowy string z kolumny `header.date_obs`, SPOT — R3 #8/#9) → `datetime | None`.
    Znosi 'Z'/ułamki (ignorowane — offset ustawia user). Data-only / śmieć / brak → None."""
    if date_obs is None:
        return None
    m = _DTOBS.match(str(date_obs))
    if m is None:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None                                   # np. 2024-13-40 → nie data


def filename_dt(basename):
    """Basename → `datetime | None` po dwóch wzorcach czasu w nazwie. Pierwszy dopasowany wygrywa."""
    for rex in _FN_PATTERNS:
        m = rex.search(basename or "")
        if m:
            try:
                return datetime(*(int(g) for g in m.groups()))
            except ValueError:
                pass
    return None


def resolve_dt(hdr_dt, fname_dt, *, source, offset_hours):
    """Zwróć `(datetime | None, problem | None)` wg polityki wsadu. `source` ∈ {date_obs, filename};
    `offset_hours` = całkowite przesunięcie (§2 — pełno-godzinne, prawomocny czas innego stanowiska,
    NIE flagowane). Brak wybranego źródła → problem (wołający: D1 fallback albo skip+raport)."""
    base = hdr_dt if source == "date_obs" else fname_dt
    if base is None:
        return None, f"brak źródła czasu '{source}'"
    return base + timedelta(hours=int(offset_hours)), None


# ============================================================ rdzeń compose_name (§1, SPOT)

LIGHT_KINDS = frozenset({"light", "master_light"})     # jedyne z obiektem (kind-aware)
DEFAULT_TEMPLATE = ("datetime", "object", "kind", "filter", "exp", "disc")
_UNSET = "_UNSET"
_DISC_LEN = 12                                         # hex prefiksu sha1_data (kolizja pomijalna)
_UNSAFE = re.compile(r"[^0-9A-Za-z+._-]+")             # spacje/separatory/śmieć → '_'
# Tokeny bez argumentu — WSTECZNIE zgodne z v1 (goły string w liście szablonu).
BARE_TOKENS = frozenset({"datetime", "object", "kind", "filter", "exp", "disc"})


def _sanitize(text):
    """Wartość faktu → segment nazwy pliku bezpieczny na dysku. Spacje i znaki niedozwolone → '_',
    zwielokrotnione '_' zwinięte, brzegowe obcięte. Pusty/None → ''."""
    if text is None:
        return ""
    s = _UNSAFE.sub("_", str(text).strip()).strip("_")
    return s


def _spec_parts(spec):
    """Element szablonu → `(token, args)`. Goły string = token bez argumentu (v1). Dict `{"t":…}` =
    token parametryczny (v2: folder/orig). SPOT normalizacji — reszta rdzenia widzi jedną formę."""
    if isinstance(spec, dict):
        return spec.get("t"), spec
    return spec, {}


def _folder_segment(path, n):
    """Sanitowany basename katalogu `n` poziomów nad plikiem (1 = katalog bezpośredni). Poza korzeniem
    (drive/root) → '' (segment pominięty jak pusty filtr). `path` None → '' (multi/brak już odsiane, ale
    szew broniony — R-v2 potwierdzenia). Token folder MOŻE wciągnąć segment `R:\\ASTRO_` gdy user wskaże
    głęboki `n` — to JEGO wybór, nie auto (§0)."""
    if not path:
        return ""
    d = os.path.dirname(path)
    for _ in range(int(n) - 1):
        parent = os.path.dirname(d)
        if parent == d:                                # korzeń — brak dalszego rodzica
            return ""
        d = parent
    return _sanitize(os.path.basename(d))


def _orig_segment(path, pattern):
    """Fragment ze STAREJ nazwy (basename bez rozszerzenia) po regexie usera. Grupa 1 gdy jest, inaczej
    cały match; sanitowany. Brak trafienia / pusty regex → '' (segment pominięty). NIE-IDEMPOTENTNY
    (R-v2 #5): czyta MUTOWALNY basename → po apply re-ekstrahuje z NOWEJ nazwy; punkt stały należy do
    USERA. Pomyślany do PIERWSZEJ kanonizacji zaimportowanych nazw niosących fakt. Zły regex łapany
    w `run_rename` PRZED przebiegiem (raz, INFORMUJ) — tu defensywnie pomijamy."""
    if not path or not pattern:
        return ""
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        m = re.search(pattern, stem)
    except re.error:
        return ""
    if m is None:
        return ""
    return _sanitize(m.group(1) if m.groups() else m.group(0))


def compose_name(facts, dt, *, template=DEFAULT_TEMPLATE):
    """Komponuj kanoniczną nazwę z faktów frame'a. Zwraca `(nazwa | None, problem | None)`.

    `facts` = dict pól: kind, object_canon, object_raw, filter_canon, exptime, sha1_data, ext
    (`ext` z kropką, np. '.fits'), oraz `path` (pełna ścieżka obecnej kopii — dla tokenów folder/orig).
    `dt` = rozstrzygnięty `datetime` (z `resolve_dt`) albo None. `template` = uporządkowana lista
    SPECYFIKACJI tokenów (DANE — §0 UNIWERSALNOŚĆ): goły string LUB dict `{"t":token, …args}`.

    Tokeny: datetime/object/kind/filter/exp/disc (bez argumentu, v1) + folder(`n`)/orig(`re`) (v2,
    ze ścieżki). INFORMUJ (§0): brak daty (`dt is None`) → problem (NIGDY nazwa bez czasu). Token
    obiektu KIND-AWARE: light/master_light nierozwiązany → `_UNSET`; kalibracja → token pominięty.
    Filtr/exp/folder/orig bez wartości → token pominięty. `disc` (`sha1_data[:12]`) w domyśle gwarantuje
    unikalność (D-I4 — user może zdjąć go w edytorze na własne ryzyko; kolizja łapana w `run_rename`)."""
    tokens: list[str] = []
    ext = facts.get("ext") or ""
    kind = facts.get("kind")
    path = facts.get("path")
    for spec in template:
        tok, args = _spec_parts(spec)
        if tok == "datetime":
            if dt is None:
                return None, "brak rozstrzygniętej daty-godziny"
            tokens.append(dt.strftime("%Y%m%d_%H%M%S"))
        elif tok == "object":
            if kind in LIGHT_KINDS:                    # kalibracja: token pominięty (bez _UNSET)
                obj = _sanitize(facts.get("object_canon")) or _sanitize(facts.get("object_raw"))
                tokens.append(obj or _UNSET)
        elif tok == "kind":
            tokens.append(_sanitize(kind) or "unknown")
        elif tok == "filter":
            fc = _sanitize(facts.get("filter_canon"))
            if fc:
                tokens.append(fc)
        elif tok == "exp":
            expt = facts.get("exptime")
            if expt is not None:
                tokens.append(f"{float(expt):g}s")
        elif tok == "disc":
            sha = facts.get("sha1_data")
            if sha:
                tokens.append(str(sha)[:_DISC_LEN])
        elif tok == "folder":
            seg = _folder_segment(path, args.get("n", 1))
            if seg:
                tokens.append(seg)
        elif tok == "orig":
            seg = _orig_segment(path, args.get("re", ""))
            if seg:
                tokens.append(seg)
        else:
            raise ValueError(f"nieznany token szablonu: {tok!r}")
    return "_".join(t for t in tokens if t) + ext, None


# ============================================================ szablon per typ pliku (§3)


def _pick_template(template, kind, filetype):
    """Wybierz listę specyfikacji dla klatki. `template` = lista (jeden wzór dla WSZYSTKICH — v1) ALBO
    dict per typ. **Precedencja JAWNA: `filetype` > `kind` > `"default"` > DEFAULT_TEMPLATE.** Przestrzenie
    kluczy rozłączne (fits/xisf/raw vs light/master_flat), więc bez kolizji klucza — ale wpis `"fits"`
    PRZYKRYWA `"light"` dla klatki light-fits (filetype wygrywa; udokumentowane, R-v2 #6)."""
    if not isinstance(template, dict):
        return template
    for key in (filetype, kind):
        if key is not None and key in template:
            return template[key]
    return template.get("default", DEFAULT_TEMPLATE)


def validate_template(template):
    """Skompiluj regexy tokenów `orig` w CAŁYM szablonie (lista albo dict per typ) RAZ przed przebiegiem
    (INFORMUJ, R-v2 #5): zły regex → `ValueError` z czytelnym powodem do wołającego (CLI/GUI pokaże),
    nie ciche pominięcie na każdej klatce. TANIA (O(tokenów)) — powierzchnia może ją wołać przed mintem
    run_id, by nie przebiegać dwa razy."""
    lists = template.values() if isinstance(template, dict) else [template]
    for specs in lists:
        for spec in specs:
            tok, args = _spec_parts(spec)
            if tok == "orig":
                try:
                    re.compile(args.get("re", ""))
                except re.error as e:
                    raise ValueError(f"zły regex w tokenie 'orig': {args.get('re')!r} ({e})")


# ============================================================ silnik run_rename (§3)


@dataclass(frozen=True)
class RenamePreview:
    """Jeden podgląd renamu (touched, gdy `problem is None`). `new_path` None przy problemie."""
    frame_id: int
    location_id: int
    old_path: str
    new_path: str | None
    mtime: float | None                                # kotwica anty-stale przy commicie
    problem: str | None = None


@dataclass(frozen=True)
class SkippedRename:
    frame_id: int
    path: str
    reason: str


@dataclass(frozen=True)
class RenameRun:
    run_id: str
    touched: list[RenamePreview] = field(default_factory=list)   # do stagingu (problem is None)
    skipped: list[SkippedRename] = field(default_factory=list)   # frame bez celu / problem compose


def _resolve_target(rows):
    """Z wierszy `rename_frame_targets` JEDNEGO frame'a wybierz OBECNĄ location do renamu albo powód
    pominięcia. RÓŻNICA vs `macro._resolve_target`: `header_hash`/`compressed`/degenerat tożsamości
    NIEISTOTNE — rename nie tyka ANI JEDNEGO bajtu pliku, więc nie ma czego kontrolować odciskiem
    i nie ma jak rozdwoić klatki (D-X-13 dotyczy zapisu). Multi-location skip jawny
    (R3 #7 — jedna nazwa na 2 pliki = kolizja; fan-out poza v1)."""
    present = [r for r in rows if r["location_id"] is not None]
    if not present:
        return None, "brak obecnej kopii do renamu (wszystkie present=0)"
    if len(present) > 1:
        return None, f"wiele obecnych kopii ({len(present)}) -- rename multi-location poza v1"
    return present[0], None


def _facts_of(row):
    """Wiersz targetu → dict faktów dla `compose_name` (klucze jak w §1). `path` niesiony WPROST — tokeny
    folder/orig (v2) go potrzebują; `ext` z niego wyłuskany dla wygody."""
    return {
        "kind": row["kind"],
        "object_canon": row["object_canon"],
        "object_raw": row["object_raw"],
        "filter_canon": row["filter_canon"],
        "exptime": row["exptime"],
        "sha1_data": row["sha1_data"],
        "path": row["path"],
        "ext": os.path.splitext(row["path"])[1],
    }


def run_rename(frame_ids, *, targets_fn, source, offset_hours, template=DEFAULT_TEMPLATE,
               fallback=True, run_id=None):
    """Potok podglądu renamu nad `frame_ids` (widocznymi w gridzie). CZYSTY silnik: dane przez
    wstrzykiwany `targets_fn(ids) -> rows` (`queries.rename_frame_targets`). ZERO zapisu / ZERO
    `os.rename` — zwraca `RenameRun`; staging + mutację robi wołający.

    `template` = lista specyfikacji (jeden wzór — v1) ALBO dict per typ (`_pick_template` wybiera po
    filetype/kind — v2). Regexy `orig` walidowane RAZ na starcie (`ValueError` do wołającego, INFORMUJ).

    Per frame: wybór OBECNEJ location (multi/brak → skip) → `resolve_dt` (D1 fallback: brak źródła →
    drugie źródło z offsetem 0, bo nazwa już lokalna, + flaga; R2 #6) → wzór wg typu → `compose_name` →
    `new_path` w TYM SAMYM katalogu. Nazwa bez zmian → skip (idempotencja). KOLIZJA WEWNĄTRZ WSADU (dwa
    frame'y → ten sam `new_path`) wykryta TU, w podglądzie (R3 #4) — oba lądują w `skipped` z podpowiedzią
    „dodaj token disc" (D-I4: user zdjął disc ze wzoru → warning, poprawia wzór); commit polega na
    nieistnieniu na dysku, NIE na tym przeglądzie."""
    validate_template(template)                        # zły regex orig → ValueError PRZED przebiegiem
    run_id = run_id or "rename"
    ids = sorted(int(i) for i in frame_ids)
    by_frame: dict[int, list] = {}
    for row in targets_fn(ids):
        by_frame.setdefault(int(row["frame_id"]), []).append(row)

    previews: list[RenamePreview] = []
    skipped: list[SkippedRename] = []

    for fid in ids:
        rows = by_frame.get(fid)
        if not rows:
            skipped.append(SkippedRename(fid, "", "frame nieobecny w bazie"))
            continue
        target, reason = _resolve_target(rows)
        if target is None:
            path = next((r["path"] for r in rows if r["path"]), "")
            skipped.append(SkippedRename(fid, path or "", reason or ""))
            continue

        old_path = target["path"]
        basename = os.path.basename(old_path)
        dt, prob = resolve_dt(header_dt(target["date_obs"]), filename_dt(basename),
                              source=source, offset_hours=offset_hours)
        if dt is None and fallback:                    # D1: drugie źródło, offset 0 (nazwa lokalna)
            alt = "filename" if source == "date_obs" else "date_obs"
            dt, prob = resolve_dt(header_dt(target["date_obs"]), filename_dt(basename),
                                  source=alt, offset_hours=0)
            if dt is None:                             # oba źródła puste → powód ŁĄCZNY (wiz #9):
                prob = "brak DATE-OBS ani czasu w nazwie"   # komunikat z fallbacku mylił (drugie źródło)
        if dt is None:
            skipped.append(SkippedRename(fid, old_path, prob or "brak daty"))
            continue

        specs = _pick_template(template, target["kind"], target["filetype"])   # wzór wg typu pliku (§3)
        new_name, prob = compose_name(_facts_of(target), dt, template=specs)
        if new_name is None:
            skipped.append(SkippedRename(fid, old_path, prob or "compose"))
            continue
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if new_path == old_path:
            skipped.append(SkippedRename(fid, old_path, "nazwa bez zmian"))
            continue
        previews.append(RenamePreview(
            frame_id=fid, location_id=int(target["location_id"]),
            old_path=old_path, new_path=new_path, mtime=target["mtime"]))

    # Kolizja WEWNĄTRZ wsadu (R3 #4): dwa różne frame'y → ten sam new_path. Token `disc` (domyśle)
    # czyni to strukturalnie nieosiągalnym dla DISTINCT frame'ów; user, który zdjął disc ze wzoru (D-I4),
    # dostaje tu WARNING i poprawia wzór (kolejka: „warning przy próbie zmiany na duplikaty"). Powtórki
    # skanu (ten sam sha1) też tu lądują. Kolidujące → skipped (oba), reszta → touched.
    counts: dict[str, int] = {}
    for p in previews:
        counts[p.new_path] = counts.get(p.new_path, 0) + 1
    touched: list[RenamePreview] = []
    for p in previews:
        if counts[p.new_path] > 1:
            skipped.append(SkippedRename(
                p.frame_id, p.old_path,
                f"kolizja nazwy w wsadzie: {os.path.basename(p.new_path)} — dodaj token disc lub zmień wzór"))
        else:
            touched.append(p)

    return RenameRun(run_id=run_id, touched=touched, skipped=skipped)
