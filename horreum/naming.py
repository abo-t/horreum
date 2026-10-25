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

POWODY Z KODEM (AR-193): powód pominięcia klatki w podglądzie renamu (`SkippedRename.reason`, problem
`compose_name`/`resolve_dt`) i błąd wzoru nazwy (`OdmowaZPowodem` - nadal `ValueError`) to
`item_reasons.PowodPozycji` z kodem `rename_*`: zdanie PL bez zmiany znaku (CLI, testy biorą je jak
tekst), a okno składa z kodu zdanie w języku UI (`gui.wb_worker.tekst_powodu`). Nazwy stosu i mastera
flat (`stack_name`, `master_flat_name`) zostają przy `ValueError` prozą - ich odmowy mapują żniwa na
własne tokeny przeglądu.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .item_reasons import OdmowaZPowodem, PowodPozycji   # powód z kodem (AR-193) - liść bez importów
from .resolve.catalog import folder_form   # forma systemu plików kanonu (token obiektu, D-1011-5)
from .resolve.channel import channel_from_name
from .resolve.frames import LIGHT_KINDS   # jedyne z obiektem (kind-aware) — właściciel w liściu
from .resolve.recipe import parse_master_path   # jedyny właściciel tokenu FLATGRP w nazwie mastera (AR-86)

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
        return None, PowodPozycji(f"brak źródła czasu '{source}'", "rename_no_time_source",
                                  value=source)
    return base + timedelta(hours=int(offset_hours)), None


# ============================================================ rdzeń compose_name (§1, SPOT)

DEFAULT_TEMPLATE = ("datetime", "object", "kind", "filter", "exp", "disc")
_UNSET = "_UNSET"
_DISC_LEN = 12                                         # hex prefiksu sha1_data (kolizja pomijalna)
_UNSAFE = re.compile(r"[^0-9A-Za-z+._-]+")             # spacje/separatory/śmieć → '_'
# Tokeny bez argumentu — WSTECZNIE zgodne z v1 (goły string w liście szablonu).
BARE_TOKENS = frozenset({"datetime", "object", "kind", "filter", "exp", "disc"})
# CAŁY słownik tokenów wzoru (AR-208): bez argumentu, parametryczne (folder/orig) i strukturalne
# (flatgrp/trail). `validate_template` odrzuca token spoza niego PRZED przebiegiem - edytor wzoru podaje
# dokładnie ten zbiór (`grid_panels._TokenRow._TOKENS`, pin w testach).
TOKENS = BARE_TOKENS | frozenset({"folder", "orig", "flatgrp", "trail"})
# Znacznik braku podpiętego flatu - ten sam, który archiwum już niesie w nazwach lightów
# (`FLATGRP_NOFLAT_`). Grupę flatu z nazwy mastera czyta `recipe.parse_master_path` (`_flatgrp_segment`).
_NOFLAT = "NOFLAT"
_KIND_CASES = ("upper", "lower")                       # parametr `case` tokenu kind (brak = jak w bazie)


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


def _flatgrp_segment(facts):
    """Segment `FLATGRP_<grupa>` z nazwy OBECNEJ kopii mastera flat podpiętego w `calibration`. Zwraca
    `(segment, problem)`. Brak podpiętego flatu → `FLATGRP_NOFLAT` (znacznik konwencji archiwum, nie
    dziura). Flat podpięty, ale grupy nie da się odczytać (brak obecnej kopii, nazwa poza wzorcem
    masterflatu, kopie o różnych grupach) → problem: klatka pominięta z powodem, nigdy nazwa z pustym
    segmentem.

    Grupę czyta JEDEN właściciel tokenu (AR-86): wzorzec `masterflat_flatgrp_filter`
    z `resolve/data/master_paths.json` przez `recipe.parse_master_path`, z tym samym wejściem (pełna
    ścieżka kopii), co porównanie kopii jednej klatki (`gui.queries.copy_name_facts`) - jeden plik,
    jedna grupa w obu miejscach. `_sanitize` zostaje: wzorzec to DANE, które inny użytkownik dokłada
    bez Pythona, więc grupa z jego wyrażenia może nieść znak niedozwolony w nazwie pliku."""
    if facts.get("flat_master_id") is None:
        return f"FLATGRP_{_NOFLAT}", None
    paths = facts.get("flat_paths") or []
    if not paths:
        return None, PowodPozycji("flat podpięty, ale master bez obecnej kopii", "rename_flat_no_copy")
    groups = set()
    for p in paths:
        grupa = parse_master_path(p).get("flatgrp")
        if grupa is None:
            return None, PowodPozycji(f"brak FLATGRP w nazwie mastera flat: {os.path.basename(p)}",
                                      "rename_flat_no_group", name=os.path.basename(p))
        grupa = _sanitize(grupa)
        if not grupa:
            return None, PowodPozycji(
                f"pusta grupa FLATGRP w nazwie mastera flat: {os.path.basename(p)}",
                "rename_flat_empty_group", name=os.path.basename(p))
        groups.add(grupa)
    if len(groups) > 1:
        return None, PowodPozycji(f"kopie mastera flat o różnych grupach: {', '.join(sorted(groups))}",
                                  "rename_flat_many_groups", value=", ".join(sorted(groups)))
    return f"FLATGRP_{groups.pop()}", None


_NIGHT8 = re.compile(r"[0-9]{8}")


def master_flat_name(night8, filter_segment, seq):
    """Nazwa NOWEGO mastera flat w konwencji archiwum: `MASTERFLAT_FLATGRP_<noc><cyfra>_FILTER_<filtr>_.xisf`
    (`MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf`). Nie `compose_name`: jej wzór to konwencja
    LIGHTÓW (data i godzina na początku), a nazwę mastera czyta inna reguła - wzorzec
    `masterflat_flatgrp_filter` z `resolve/data/master_paths.json`, przez który idzie także
    `_flatgrp_segment` (grupa flatu w nazwie lighta, AR-86). Grupa = noc `YYYYMMDD` + cyfra
    kolejności grupy tej nocy (zmierzone w archiwum: `202308230` i `202308231` w jednym folderze
    `76EDPH_2600MC\\OSC`). Rozszerzenie STAŁE `.xisf`: żniwa wciągają wyłącznie XISF, a nazwa `.fits`
    na pliku XISF kłamałaby skanowi o formacie.

    EXPECT: `night8` to dokładnie 8 cyfr i prawdziwa data kalendarza, `seq` jedna cyfra `0..9`,
    segment filtru niepusty, równy sobie po `_sanitize` (żadnej cichej poprawki: `CLS_` nie staje się
    `CLS`) i bez `_` oraz `.` - wzorzec czyta filtr jako `[^_\\\\/.]+`, więc taki znak uciąłby filtr
    przy odczycie. Inaczej `ValueError`: nazwa, której archiwum nie przeczyta z powrotem, nie powstaje."""
    night8 = str(night8)
    try:
        if not _NIGHT8.fullmatch(night8):
            raise ValueError
        datetime.strptime(night8, "%Y%m%d")
    except ValueError:
        raise ValueError(f"noc mastera flat musi być datą YYYYMMDD (8 cyfr): {night8!r}") from None
    if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq <= 9:
        raise ValueError(f"cyfra kolejności grupy flatu musi być 0..9: {seq!r}")
    if (not isinstance(filter_segment, str) or not filter_segment
            or _sanitize(filter_segment) != filter_segment or "_" in filter_segment or "." in filter_segment):
        raise ValueError(f"segment filtru nieczytelny dla wzorca nazwy mastera: {filter_segment!r}")
    return f"MASTERFLAT_FLATGRP_{night8}{seq}_FILTER_{filter_segment}_.xisf"


# ============================================================ nazwa STOSU w archiwum (żniwa)

# Kolor stosu w nazwie archiwum: `mono` (kamera mono), `RGB` (stos WBPP kamery kolorowej), `R`/`G`/`B`
# (kanał - właściciel reguły odczytu `resolve.channel`). `combined_RGB` (składanka ręki) z wyjścia WBPP
# nie przychodzi i stosem WBPP nie jest, więc nazwa jej nie składa.
STACK_COLORS = ("mono", "RGB", "R", "G", "B")
_DRIZZLE_VARIANT = re.compile(r"drizzle_([1-9][0-9]*)x")
_AUTOCROP = "autocrop"


def _stem_tokens(name):
    """Człony stemu nazwy pliku (bez katalogu i rozszerzenia) po `_`, małymi literami."""
    stem = re.split(r"[\\/]", str(name))[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return [t.lower() for t in stem.split("_")]


def wbpp_stack_color(name):
    """Kolor stosu z NAZWY pliku WBPP - jedna z `STACK_COLORS` albo `None`.

    Kanał (`…_FILTER-NoFilter__B.xisf`) rozstrzyga `resolve.channel.channel_from_name` - jeden właściciel
    reguły pozycyjnej, bo goły token `B` jest też filtrem mono. Bez kanału kolor niesie token `mono`
    (`…_FILTER-H_mono.xisf`) albo `RGB` (`…_FILTER-NoFilter_RGB.xisf`). Oba naraz, żaden, albo
    `combined_RGB` (składanka ręki, nie stos WBPP) → `None`: kolor zgadnięty byłby nazwą, która kłamie."""
    kanal = channel_from_name(re.split(r"[\\/]", str(name))[-1])
    if kanal is not None:
        return kanal
    tokeny = _stem_tokens(name)
    mono, rgb = "mono" in tokeny, "rgb" in tokeny
    if mono == rgb or (rgb and "combined" in tokeny):
        return None
    return "mono" if mono else "RGB"


def wbpp_stack_variants(name):
    """Warianty obrazu z NAZWY pliku WBPP w stałej kolejności: `autocrop`, potem `drizzle_<n>x`.
    Oba to ten sam stos z tymi samymi subami (`scan.is_derived_name` nie odsiewa ich jako pochodnych),
    więc nazwa archiwum musi je nieść - inaczej `…_autocrop.xisf` i plik bez przycięcia dostałyby jedną
    nazwę. Inne tokeny WBPP (`OBIEKT-<x>`, `fastIntegration`) do nazwy nie przechodzą."""
    tokeny = _stem_tokens(name)
    out = [_AUTOCROP] if _AUTOCROP in tokeny else []
    for i, t in enumerate(tokeny[:-1]):
        if t == "drizzle" and _DRIZZLE_VARIANT.fullmatch(f"drizzle_{tokeny[i + 1]}"):
            out.append(f"drizzle_{tokeny[i + 1]}")
            break
    return tuple(out)


def _variant_order(variant):
    if variant == _AUTOCROP:
        return 0
    if _DRIZZLE_VARIANT.fullmatch(str(variant)):
        return 1
    raise ValueError(f"nieznany wariant stosu: {variant!r} (znane: {_AUTOCROP}, drizzle_<n>x)")


def stack_name(obj_seg, date_obs, rig_seg, filter_seg, exptime, color, *, variants=(), suffix=None):
    """Nazwa STOSU w archiwum `STACKS`: `<obj>_<YYYY-MM-DD>_<rig>_<filtr>_<exp>s_<kolor>[_<wariant>…]
    [_<sufiks>].xisf` - konwencja planu przenosin 0802 (193 nazwy), np.
    `IC1795_2025-12-16_A140R_2600MM_Ha_600s_mono.xisf`. Nie `compose_name`: tamta to konwencja LIGHTÓW
    (data i godzina na początku), a archiwum stosów sortuje się po obiekcie.

    Segmenty przez `_sanitize` (jak nazwy plików). Data = `DATE-OBS` stosu walidowane `header_dt` (FITS
    pisze UTC, więc bez przeliczania strefy), potem sama data. `exp` = `format(float, "g")` (`600.000`
    → `600`). Warianty w stałej kolejności `autocrop`, `drizzle_<n>x`; sufiks (rozróżnienie kolizji,
    `WBPP_<YYYYMMDD>`) na końcu. Token `OBIEKT-<x>` z nazwy WBPP tu nie wchodzi - obiekt stoi już na
    początku nazwy. Rozszerzenie STAŁE `.xisf` (żniwa wciągają wyłącznie XISF).

    EXPECT: brak albo śmieć w `DATE-OBS` → `ValueError` (plan: `header_mismatch`), kolor spoza
    `STACK_COLORS` → `ValueError` (plan: `color_unknown`), brak ekspozycji, segment pusty po
    `_sanitize`, nieznany wariant, pusty sufiks → `ValueError`. Nazwa, której archiwum nie przeczyta
    z powrotem, nie powstaje."""
    dt = header_dt(date_obs)
    if dt is None:
        raise ValueError(f"DATE-OBS stosu nieczytelne: {date_obs!r}")
    if color not in STACK_COLORS:
        raise ValueError(f"kolor stosu spoza {STACK_COLORS}: {color!r}")
    try:
        exp = float(exptime)
    except (TypeError, ValueError):
        raise ValueError(f"ekspozycja stosu nieczytelna: {exptime!r}") from None
    segs = [_sanitize(obj_seg), dt.strftime("%Y-%m-%d"), _sanitize(rig_seg), _sanitize(filter_seg),
            f"{format(exp, 'g')}s", color]
    if not all(segs):
        raise ValueError(f"pusty segment nazwy stosu: {segs!r}")
    segs += sorted(variants, key=_variant_order)
    if suffix is not None:
        if not _sanitize(suffix):
            raise ValueError(f"pusty sufiks nazwy stosu: {suffix!r}")
        segs.append(_sanitize(suffix))
    return "_".join(segs) + ".xisf"


_EXPOSURE_TOKEN = re.compile(r"\d+(?:\.\d+)?s", re.IGNORECASE)


def variant_stack_name(original_name, variant=_AUTOCROP):
    """Nazwa WARIANTU stosu w archiwum z nazwy archiwalnej ORYGINAŁU (`stack_name`) - człon wariantu
    wstawiony zaraz po kolorze, przed drizzle i sufiksem rozróżnienia: ta sama kolejność członów, którą
    składa `stack_name`. Czysta funkcja; None, gdy nazwa nie ma układu `…_<exp>s_<kolor>[…]` albo JUŻ
    niesie ten wariant.

    ROZBIÓR OD KOŃCA: segmenty zestawu i filtra przechodzą przez `_sanitize`, więc mogą nieść `_`
    i token wyglądający jak ekspozycja (zestaw `X_300s`). Kolor to OSTATNI token ze `STACK_COLORS`
    (albo para `combined_RGB`), przed którym stoi token ekspozycji `<n>s` - za nim mogą stać już
    tylko warianty i sufiks, a te koloru ani ekspozycji nie udają.

    DLACZEGO Z NAZWY ORYGINAŁU (pomiar na kopii archiwum 2026-10-11): oryginały w `STACKS` niosą
    sufiksy przebiegu (`_WBPP`, `_WBPP_nowy`, `_WBPP2`), wariant drizzle i `combined_RGB`; nazwa
    złożona z nagłówka autocropu dawała 27 kolizji w obrębie planu i 5 odmów koloru. Nazwa oryginału
    jest w swoim katalogu unikalna, więc wariant dziedziczy tę unikalność."""
    _variant_order(variant)                            # EXPECT: wariant spoza słownika → ValueError
    stem, ext = os.path.splitext(str(original_name))
    tokens = stem.split("_")
    if any(t.lower() == variant for t in tokens):
        return None
    kolory = {c.lower() for c in STACK_COLORS}
    for i in range(len(tokens) - 1, 0, -1):
        t = tokens[i].lower()
        if t not in kolory:
            continue
        exp = i - 2 if (t == "rgb" and tokens[i - 1].lower() == "combined") else i - 1
        if exp >= 0 and _EXPOSURE_TOKEN.fullmatch(tokens[exp]):
            return "_".join(tokens[:i + 1] + [variant] + tokens[i + 1:]) + ext
    return None


def compose_name(facts, dt, *, template=DEFAULT_TEMPLATE):
    """Komponuj kanoniczną nazwę z faktów frame'a. Zwraca `(nazwa | None, problem | None)`.

    `facts` = dict pól: kind, object_canon, object_raw, filter_canon, exptime, sha1_data, ext
    (`ext` z kropką, np. '.fits'), oraz `path` (pełna ścieżka obecnej kopii — dla tokenów folder/orig).
    `dt` = rozstrzygnięty `datetime` (z `resolve_dt`) albo None. `template` = uporządkowana lista
    SPECYFIKACJI tokenów (DANE — §0 UNIWERSALNOŚĆ): goły string LUB dict `{"t":token, …args}`.

    Tokeny: datetime/object/kind/filter/exp/disc (bez argumentu, v1) + folder(`n`)/orig(`re`) (v2,
    ze ścieżki) + flatgrp/trail (bez argumentu) + `kind` z opcjonalnym `case` (upper/lower). INFORMUJ
    (§0): brak daty (`dt is None`) → problem (NIGDY nazwa bez czasu). Token obiektu KIND-AWARE:
    light/master_light nierozwiązany → `_UNSET`; kalibracja → token pominięty. `flatgrp` (`facts`
    `flat_master_id` + `flat_paths`) tylko dla `light` (jedyny rodzaj z ogniwem w `calibration`): brak
    flatu → `FLATGRP_NOFLAT`, grupa nieczytelna → problem; inne rodzaje → pominięty. `trail` = końcowy
    separator `_` przed rozszerzeniem, wyłącznie OSTATNI w wzorze. Filtr/exp/folder/orig bez wartości →
    token pominięty. `disc` (`sha1_data[:12]`) w domyśle gwarantuje unikalność (D-I4 - user może zdjąć
    go w edytorze na własne ryzyko; kolizja łapana w `run_rename`)."""
    tokens: list[str] = []
    ext = facts.get("ext") or ""
    kind = facts.get("kind")
    path = facts.get("path")
    trail = False
    specs = list(template)
    for i, spec in enumerate(specs):
        tok, args = _spec_parts(spec)
        if tok == "datetime":
            if dt is None:
                return None, PowodPozycji("brak rozstrzygniętej daty-godziny", "rename_no_datetime")
            tokens.append(dt.strftime("%Y%m%d_%H%M%S"))
        elif tok == "object":
            if kind in LIGHT_KINDS:                    # kalibracja: token pominięty (bez _UNSET)
                # Token = forma systemu plików kanonu (`folder_form`, D-1011-5 Q5) - ta sama, którą
                # niesie folder obiektu, inaczej nazwa komety przeczyłaby folderowi. Różni się od
                # `_sanitize(kanon)` WYŁĄCZNIE dla kanonu z `/` (kometa); każdy inny kanon idzie
                # bajt w bajt jak dotąd i nie przechodzi przez EXPECT formy katalogu.
                canon = facts.get("object_canon")
                if canon is not None and "/" in str(canon):
                    canon = folder_form(canon)
                obj = _sanitize(canon) or _sanitize(facts.get("object_raw"))
                tokens.append(obj or _UNSET)
        elif tok == "kind":
            seg = _sanitize(kind) or "unknown"
            case = args.get("case")
            if case not in (None, *_KIND_CASES):
                raise OdmowaZPowodem(PowodPozycji(
                    f"nieznana wielkość liter tokenu 'kind': {repr(case)}", "rename_tpl_bad_case",
                    value=repr(case)))
            tokens.append(seg.upper() if case == "upper" else seg.lower() if case == "lower" else seg)
        elif tok == "flatgrp":
            if kind == "light":                        # kalibracja/master_light: brak ogniwa z definicji
                seg, prob = _flatgrp_segment(facts)
                if seg is None:
                    return None, prob
                tokens.append(seg)
        elif tok == "trail":
            if i != len(specs) - 1:
                raise OdmowaZPowodem(PowodPozycji("token 'trail' musi być ostatni we wzorze",
                                                  "rename_tpl_trail_not_last"))
            trail = True
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
            raise OdmowaZPowodem(PowodPozycji(f"nieznany token szablonu: {repr(tok)}",
                                              "rename_tpl_unknown_token", value=repr(tok)))
    return "_".join(t for t in tokens if t) + ("_" if trail else "") + ext, None


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
    nie ciche pominięcie na każdej klatce. Tak samo `trail` nie na końcu wzoru, nieznany `case` tokenu
    kind i token spoza słownika (`TOKENS`, AR-208) - to samo zdanie i kod, które dałby `compose_name`
    w pętli przebiegu, więc żadna odmowa `compose_name` nie zostaje na później. TANIA (O(tokenów)) -
    powierzchnia może ją wołać przed mintem run_id, by nie przebiegać dwa razy."""
    lists = template.values() if isinstance(template, dict) else [template]
    for specs in lists:
        specs = list(specs)
        for i, spec in enumerate(specs):
            tok, args = _spec_parts(spec)
            if tok == "orig":
                try:
                    re.compile(args.get("re", ""))
                except re.error as e:
                    # Tekst `re.error` (język Pythona) jedzie parametrem - jawna granica, jak tekst systemu.
                    raise OdmowaZPowodem(PowodPozycji(
                        f"zły regex w tokenie 'orig': {repr(args.get('re'))} ({str(e)})",
                        "rename_tpl_bad_regex", value=repr(args.get("re")), detail=str(e)))
            elif tok == "trail" and i != len(specs) - 1:
                raise OdmowaZPowodem(PowodPozycji("token 'trail' musi być ostatni we wzorze",
                                                  "rename_tpl_trail_not_last"))
            elif tok == "kind" and args.get("case") not in (None, *_KIND_CASES):
                raise OdmowaZPowodem(PowodPozycji(
                    f"nieznana wielkość liter tokenu 'kind': {repr(args.get('case'))}",
                    "rename_tpl_bad_case", value=repr(args.get("case"))))
            elif not isinstance(tok, str) or tok not in TOKENS:
                # `isinstance` przed `in`: `{"t": [...]}` daje token niehaszowalny, a `TypeError` uciekłby
                # spod `except ValueError` wołających.
                raise OdmowaZPowodem(PowodPozycji(f"nieznany token szablonu: {repr(tok)}",
                                                  "rename_tpl_unknown_token", value=repr(tok)))


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
        return None, PowodPozycji("brak obecnej kopii do renamu (wszystkie present=0)",
                                  "rename_no_present_copy")
    if len(present) > 1:
        return None, PowodPozycji(
            f"wiele obecnych kopii ({len(present)}) -- rename multi-location poza v1",
            "rename_many_copies", n=len(present))
    return present[0], None


def _facts_of(row):
    """Wiersz targetu → dict faktów dla `compose_name` (klucze jak w §1). `path` niesiony WPROST — tokeny
    folder/orig (v2) go potrzebują; `ext` z niego wyłuskany dla wygody. Ogniwo flatu (`flat_master_id`,
    `flat_paths` jako tablica JSON ścieżek obecnych kopii mastera) - dla tokenu flatgrp; wiersz bez tych
    kolumn (inne źródło targetów) = brak flatu."""
    keys = row.keys()
    flat_paths = row["flat_paths"] if "flat_paths" in keys else None
    return {
        "flat_master_id": row["flat_master_id"] if "flat_master_id" in keys else None,
        "flat_paths": json.loads(flat_paths) if flat_paths else [],
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
            skipped.append(SkippedRename(fid, "", PowodPozycji("frame nieobecny w bazie",
                                                               "rename_frame_gone")))
            continue
        # Pominięcie ZAWSZE z powodem (AR-193): `_resolve_target`, `resolve_dt` i `compose_name`
        # oddają brak wyniku wyłącznie z powodem - pusty powód to złamany inwariant (EXPECT), nie
        # zdanie zastępcze bez kodu.
        target, reason = _resolve_target(rows)
        if target is None:
            if not reason:
                raise AssertionError(f"frame {fid}: brak celu renamu bez powodu")
            path = next((r["path"] for r in rows if r["path"]), "")
            skipped.append(SkippedRename(fid, path or "", reason))
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
                # komunikat z fallbacku mylił (drugie źródło)
                prob = PowodPozycji("brak DATE-OBS ani czasu w nazwie", "rename_no_time")
        if dt is None:
            if not prob:
                raise AssertionError(f"frame {fid}: brak daty bez powodu")
            skipped.append(SkippedRename(fid, old_path, prob))
            continue

        specs = _pick_template(template, target["kind"], target["filetype"])   # wzór wg typu pliku (§3)
        new_name, prob = compose_name(_facts_of(target), dt, template=specs)
        if new_name is None:
            if not prob:
                raise AssertionError(f"frame {fid}: nazwa nie złożona bez powodu")
            skipped.append(SkippedRename(fid, old_path, prob))
            continue
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if new_path == old_path:
            skipped.append(SkippedRename(fid, old_path, PowodPozycji("nazwa bez zmian",
                                                                     "rename_unchanged")))
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
            skipped.append(SkippedRename(p.frame_id, p.old_path, PowodPozycji(
                f"kolizja nazwy w wsadzie: {os.path.basename(p.new_path)} - dodaj token disc lub zmień wzór",
                "rename_collision", name=os.path.basename(p.new_path))))
        else:
            touched.append(p)

    return RenameRun(run_id=run_id, touched=touched, skipped=skipped)
