"""Oś KALIBRACJI — przepis klatki sprzętowej (segment C2, Issue #6). Siostra `grouper`.

Klatka sprzętowa dostaje PRZEPIS: zestaw nastaw, które ją fizycznie determinują. Master i klatka
surowa o tych samych nastawach trafiają do TEGO SAMEGO przepisu (przedrostek `master_` schodzi
do `recipe_class`) — inaczej rodowód (C4) nie miałby czego z czym łączyć.

ŹRÓDŁA I PRECEDENCJA (D-C-1): `user` > `header` > `path`. Człowiek pomija drabinę, dokładnie jak
`frame.object_source='user'` na osi obiektu. Nagłówek jest zeznaniem aparatury. Ścieżka jest
ostatnia, jawna (`source='path'`) i WĄSKA — wyłącznie masterdarki, bo tylko tam header milczy
(`SET-TEMP`/`GAIN`/`OFFSET` = 0 na 111 masterów; masterflat ma komplet w nagłówku, 73/73).

NASTAWY SIĘ NIE WYLICZA — ODCZYTUJE SIĘ JĄ (D-C-2): brak faktu zostawia klatkę BEZ przepisu
i w zbiorczym `calibration.review_summary`, nigdy nie dokłada wartości domyślnej. Dlatego
`profile_key` nie zna NULL-i: sentinel w kluczu zlewałby DWA mastery o RÓŻNYCH, nieznanych
nastawach w jeden przepis, a UNIQUE by tego nie złapał.

Qt-wolne, zapis wyłącznie przez `repo` (DB-KLINGA), SELECT literałem.
"""
import json
from dataclasses import dataclass, field

from . import repo
from .resolve._coerce import _to_float, _to_int
from .resolve.recipe import parse_master_path

# JEDYNY właściciel dwóch faktów naraz: „ten rodzaj ma przepis" ORAZ „ten rodzaj jest na osi
# teleskopu". `grouper.NO_TELESCOPE_KINDS` wyprowadza się STĄD, nie żyje obok — inaczej dołożenie
# rodzaju (np. dark-flatów) wpisałoby go do jednego zbioru i pominęło w drugim, a dark wszedłby
# na oś teleskopu i zaczął budować configi pod cudzą optyką.
KIND_RECIPE = {
    "dark":        ("dark", False),
    "bias":        ("bias", False),
    "master_dark": ("dark", False),
    "master_bias": ("bias", False),
    "flat":        ("flat", True),      # flat ZOSTAJE na osi teleskopu — zależność od optyki realna
    "master_flat": ("flat", True),
}

# Fakty wymagane per klasa przepisu (komplet = warunek istnienia profilu).
# `filter_canon` CELOWO poza wymaganymi: jego brak na kamerze KOLOROWEJ to fakt, nie luka
# (zmierzone: 798 flatów bez filtra to w 100 % OSC — ASI2600MC 698 + SONY 100; mono ma filtr 100 %).
REQUIRED = {
    "dark": ("exptime", "set_temp_c", "gain", "offset_adu"),
    "bias": ("set_temp_c", "gain", "offset_adu"),
    "flat": ("telescope_id",),
}
_FACT_TYPE = {"exptime": _to_float, "set_temp_c": _to_int, "gain": _to_int,
              "offset_adu": _to_int, "xbinning": _to_int, "telescope_id": _to_int}


@dataclass
class CalibrationSummary:
    """Zliczenia przebiegu (QUIET: cisza przy sukcesie, liczby na żądanie)."""
    frames: int = 0                    # klatki kalibracyjne w ogóle
    profiles_proposed: int = 0         # nowe wiersze `calibration_profile`
    profiles_assigned: int = 0         # realne przypisania (idempotentny re-run daje 0)
    facts_recorded: int = 0            # fakty zapisane ze ścieżki
    incomplete: int = 0                # klatki bez kompletu → review
    reasons: dict = field(default_factory=dict)


def profile_key(recipe_class, facts):
    """Deterministyczny klucz tożsamości przepisu. Pola w STAŁEJ kolejności, liczby przez tę samą
    derywację co nagłówek — bez tego `gain=100` ze ścieżki i `'100'` z nagłówka (kolumna TEXT!)
    dałyby DWA przepisy jednej nastawy (W3).

    Wołaj TYLKO na komplecie (`missing_facts` puste) — klucz nie ma reprezentacji dla braku."""
    parts = [recipe_class, f"cam={facts['camera_id']}", f"bin={facts['xbinning']}"]
    if recipe_class == "dark":
        parts.append(f"exp={facts['exptime']:.3f}")
    if recipe_class in ("dark", "bias"):
        parts += [f"t={facts['set_temp_c']}", f"g={facts['gain']}", f"o={facts['offset_adu']}"]
    if recipe_class == "flat":
        # brak filtra (kamera kolorowa) ma STAŁĄ reprezentację — to fakt, nie brak faktu
        parts += [f"tel={facts['telescope_id']}", f"filt={facts.get('filter_canon') or '~'}"]
    return "|".join(parts)


def missing_facts(recipe_class, facts):
    """Czego brakuje do kompletu (posortowane — powód trafia do `review_summary`)."""
    need = ("camera_id", "xbinning") + REQUIRED[recipe_class]
    return tuple(k for k in need if facts.get(k) is None)


def _collect(row, stored):
    """Fakty klatki wg precedencji `user` > `header` > `path`. Nagłówek czytany WPROST z kolumn
    (`set_temp` to kolumna generowana z `raw_json` — odczyt zeznania, nie kopia)."""
    facts = {"camera_id": row["camera_id"], "xbinning": _to_int(row["xbinning"])}
    if row["recipe_class"] in ("dark", "bias"):
        facts["exptime"] = _to_float(row["exptime"])
        facts["set_temp_c"] = _to_int(row["set_temp"])
        facts["gain"] = _to_int(row["gain"])               # header.gain jest TEXT — rzut konieczny
        facts["offset_adu"] = _to_int(row["offset_adu"])
    else:
        facts["telescope_id"] = row["telescope_id"]
        facts["filter_canon"] = row["filter_canon"]
    for key, (value, source) in stored.items():            # path uzupełnia, user nadpisuje
        cast = _FACT_TYPE.get(key)
        val = cast(value) if cast is not None else value
        if source == "user" or facts.get(key) is None:
            facts[key] = val
    return facts


def run_calibration(con, *, now, actor="calibration"):
    """Przebieg osi kalibracji — idempotentny jak `grouper`: drugi przebieg na niezmienionych
    danych daje ZERO nowych wierszy i ZERO eventów.

    Kolejność jest wymuszona: fakt ze ścieżki zapisujemy PRZED złożeniem przepisu i tylko wtedy,
    gdy nagłówek milczy — dzięki temu rename mastera (który usuwa `_G100_O21_10_` ze ścieżki) nie
    przepnie klatki do innego przepisu, bo fakt jest już w bazie."""
    s = CalibrationSummary()
    kinds = tuple(KIND_RECIPE)
    rows = con.execute(
        "SELECT f.id AS frame_id, f.kind AS kind, f.camera_id AS camera_id, "
        "f.filter_canon AS filter_canon, c.telescope_id AS telescope_id, "
        "h.exptime AS exptime, h.set_temp AS set_temp, h.gain AS gain, "
        "h.offset_adu AS offset_adu, h.xbinning AS xbinning, "
        "(SELECT l.path FROM location l WHERE l.frame_id = f.id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS path "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "WHERE f.kind IN (SELECT value FROM json_each(?)) ORDER BY f.id",
        (json.dumps(kinds),)).fetchall()

    incomplete = {}
    for row in rows:
        s.frames += 1
        recipe_class = KIND_RECIPE[row["kind"]][0]
        stored = {r["key"]: (r["value"], r["source"]) for r in con.execute(
            "SELECT key, value, source FROM calibration_fact WHERE frame_id = ?",
            (row["frame_id"],))}
        facts = _collect(_row_with(row, recipe_class), stored)

        if missing_facts(recipe_class, facts) and row["path"]:      # header milczy → pytamy ścieżkę
            for key, value in _from_path(row["path"], recipe_class).items():
                if facts.get(key) is None and stored.get(key) is None:
                    if repo.record_calibration_fact(
                            con, frame_id=row["frame_id"], key=key, value=value,
                            source="path", now=now, actor=actor):
                        s.facts_recorded += 1
                    facts[key] = _FACT_TYPE[key](value)

        gaps = missing_facts(recipe_class, facts)
        if gaps:
            s.incomplete += 1
            reason = f"{recipe_class}: brak {', '.join(gaps)}"
            incomplete[reason] = incomplete.get(reason, 0) + 1
            continue

        pid, created = repo.upsert_calibration_profile(
            con, profile_key=profile_key(recipe_class, facts), recipe_class=recipe_class,
            camera_id=facts["camera_id"], xbinning=facts["xbinning"],
            exptime=facts.get("exptime"), set_temp_c=facts.get("set_temp_c"),
            gain=facts.get("gain"), offset_adu=facts.get("offset_adu"),
            telescope_id=facts.get("telescope_id"), filter_canon=facts.get("filter_canon"),
            now=now, actor=actor)
        s.profiles_proposed += int(created)
        if repo.assign_calibration_profile(con, frame_id=row["frame_id"], profile_id=pid,
                                           now=now, actor=actor):
            s.profiles_assigned += 1

    s.reasons = dict(sorted(incomplete.items()))
    repo.flag_calibration_review_summary(con, sorted(incomplete.items()), now, actor=actor)
    return s


def _row_with(row, recipe_class):
    """Wiersz SELECT-a + klasa przepisu jako zwykły dict (sqlite3.Row jest niemutowalny)."""
    d = {k: row[k] for k in row.keys()}
    d["recipe_class"] = recipe_class
    return d


def _from_path(path, recipe_class):
    """Fakty ze ŚCIEŻKI — wyłącznie dla klas, których nagłówek nie niesie (dark/bias).
    `exptime_path` NIE wchodzi do przepisu: czas mastera niesie nagłówek (38/38), a wartość ze
    ścieżki służy falsyfikatorowi konwencji, nie zapisowi."""
    if recipe_class not in ("dark", "bias"):
        return {}
    facts = parse_master_path(path)
    return {k: facts[k] for k in ("gain", "offset_adu", "set_temp_c") if facts.get(k) is not None}
