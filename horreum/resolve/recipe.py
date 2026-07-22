"""Oś KALIBRACJI — fakty przepisu odczytane ze ŚCIEŻKI mastera (segment C1, Issue #6).

Czysta funkcja `parse_master_path(path)` → dict faktów (klucze = nazwy pól przepisu), zero DB,
zero Qt, zero dostępu do plików — wzorzec `resolve.regions`/`resolve.solar`.

DLACZEGO ŚCIEŻKA, skoro kanon jest header-primary: master po integracji w PixInsight NIE NIESIE
nastaw. Zmierzone na archiwum (2026-07-22): `SET-TEMP`/`GAIN`/`OFFSET` = **0 na 111 masterów**,
podczas gdy klatki surowe mają je w nagłówku. Wyjątek jest więc DOWODOWY (header prowadnie milczy),
WĄSKI (wyłącznie masterdarki — masterflat ma cały przepis w nagłówku: TELESCOP/FILTER/INSTRUME/
XBINNING 73/73) i JAWNY (`source='path'` w zapisie faktu). `EGAIN`, jedyny kandydat na drugie
źródło w nagłówku, został SPRAWDZONY I ODRZUCONY: ta sama kamera `ASI2600MM Pro` ma `EGAIN=0,2429`
i `EGAIN=1,0056` przy tym samym `GAIN=100`, więc odwzorowanie jest niejednoznaczne.

NASTAWY SIĘ NIE WYLICZA — ODCZYTUJE SIĘ JĄ (D-C-2, słowo Zdzinia 2026-07-22): brak wzorca w ścieżce
to PUSTY dict, nigdy wartość domyślna. Jedyna interpretacja to znak temperatury (człon niesie moduł,
chłodzenie daje minus) i mieszka JAWNIE w assecie jako `temp_sign`, nie w kodzie.

Rzuty typów idą przez `_coerce` — TĘ SAMĄ derywację, której używa `extract_header` dla nagłówka.
Bez tego `gain` ze ścieżki (`100`) i z nagłówka (`'100'`/`100.0`) dałyby DWA przepisy jednej nastawy.
"""
import functools
import json
import re
from importlib import resources

from ._coerce import _to_float, _to_int

_TEMP_SIGN = {"negative": -1, "positive": 1}


@functools.lru_cache(maxsize=1)
def load_patterns():
    """Wczytaj `master_paths.json` (cache jak `regions.load_regions` — inaczej plik i kompilacja
    regexów szłyby raz na klatkę). Zwraca krotkę `(name, recipe_class, compiled_regex, sign)`."""
    text = (resources.files("horreum.resolve.data")
            .joinpath("master_paths.json").read_text(encoding="utf-8"))
    out = []
    for p in json.loads(text)["patterns"]:
        out.append((p["name"], p["recipe_class"], re.compile(p["regex"], re.IGNORECASE),
                    _TEMP_SIGN[p.get("temp_sign", "negative")]))
    return tuple(out)


def parse_master_path(path):
    """Ścieżka mastera → dict faktów przepisu; `{}` gdy ŻADEN wzorzec nie pasuje (zero faktów,
    nigdy zgadywanie). Klucze: `recipe_class`, `gain`, `offset_adu`, `set_temp_c`, `exptime_path`,
    `pattern` (nazwa wzorca — ślad do raportu i do `source='path'`).

    `exptime_path` NIE jest faktem do zapisania: czas naświetlania mastera niesie nagłówek (38/38).
    Wracamy z nim po to, by falsyfikator konwencji („czas ze ścieżki == `header.exptime`") był
    wykonywalny w kodzie, a nie tylko w sondzie — konwencja nazewnicza może się zmieniać w czasie
    (mastery z lat 2022–2026), a rozjazd choćby jednego pliku znaczy, że wzorzec opisuje co innego.

    Pierwszy pasujący wzorzec wygrywa (kolejność z assetu) — przy DRUGIM wzorcu w pliku ta reguła
    staje się decyzją, więc nowy wzorzec dokładaj na koniec listy i sprawdź na realnych ścieżkach."""
    for name, recipe_class, rx, sign in load_patterns():
        m = rx.search(path or "")
        if m is None:
            continue
        g = m.groupdict()
        facts = {"recipe_class": recipe_class, "pattern": name}
        if g.get("gain") is not None:
            facts["gain"] = _to_int(g["gain"])
        if g.get("offset_adu") is not None:
            facts["offset_adu"] = _to_int(g["offset_adu"])
        if g.get("temp_module") is not None:
            module = _to_int(g["temp_module"])
            facts["set_temp_c"] = None if module is None else sign * module
        if g.get("exptime") is not None:
            facts["exptime_path"] = _to_float(g["exptime"])
        return facts
    return {}
