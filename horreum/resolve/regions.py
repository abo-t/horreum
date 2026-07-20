"""Oś OBIEKT — kompleksy nieba rozpoznawane po WSPÓŁRZĘDNYCH (zgłoszenie #5, paczka P3).

Domyka oś OBIEKT o obiekty ROZCIĄGŁE, które nie mapują się na jedno oznaczenie katalogowe
(Veil = Cygnus Loop: NGC6960 + NGC6979 + NGC6992 + NGC6995). Czysta funkcja
`resolve_region(ra_deg, dec_deg)` → `ObjectIdentity` albo None — wzorzec `resolve.solar`.

OSTATNI SZCZEBEL DRABINY (orkiestracja `resolver.py`): wołany dopiero gdy `resolve_solar`
i `resolve_object` zwrócą None. Zeznanie nagłówka ZAWSZE wygrywa (header-primary). Waga tej
kolejności jest zmierzona, nie teoretyczna: **547 klatek z `OBJECT='NGC6992'` leży WEWNĄTRZ
promienia regionu Veil** (1,29–1,36° od środka) — chroni je wyłącznie to, że `resolve_object`
trafia pierwsze. Odwrócenie kolejności przerzuciłoby je wszystkie na `Veil`.

KONSERWATYWNIE (#5): region przypisuje NAZWĘ KOMPLEKSU, nigdy pojedynczego NGC/IC. Klatka
celowana w pojedynczy obiekt, ale bez zeznania w nagłówku, zostaje w przeglądzie — nie dostaje
zgadywanego oznaczenia katalogowego (dowód firsthand: 25 takich klatek NGC7635/NGC3034/NGC1491/
NGC1528 świadomie NIE jest łapanych).

REGION NIE ALIASUJE (`alias_norm=None`): rozpoznanie nie pochodzi z nazwy, więc nie ma czego
zapisać jako równoważność. Gdyby aliasować surowy string, ten sam `object_raw` przy INNYCH
współrzędnych mógłby należeć do innego kompleksu — a `object_alias.alias_norm` jest UNIQUE
i `repo.add_object_alias` zwraca istniejący wiersz BEZ sprawdzenia `object_id` (`repo.py:510`),
więc przegrany ginąłby cicho, bez eventu. `resolver` pomija zapis aliasu, gdy `alias_norm` puste.

Definicje regionów = DANE (`data/regions.json`), nie kod — nowy kompleks wchodzi bez zmiany kodu
(jak `catalog_xref.json`). Casing kanonu pochodzi WYŁĄCZNIE z JSON-a: `object.canon` nie ma
`COLLATE NOCASE` (`0002_initial.sql:137`), więc `Veil` i `veil` byłyby dwoma wierszami.
UWAGA: edycja `regions.json` na ISTNIEJĄCEJ bazie to operacja MIGRACYJNA, nie zwykły re-run —
zmiana środka/promienia może przerzucić klatkę między obiektami.
"""
import functools
import json
import math
from importlib import resources

from .objects import ObjectIdentity


@functools.lru_cache(maxsize=1)
def load_regions():
    """Wczytaj `regions.json` (cache jak `catalog.load_catalog_xref` — inaczej plik parsowałby się
    raz na klatkę). Zwraca krotkę definicji: `canon`, `ra_deg`, `dec_deg`, `radius_deg`, `note`."""
    text = (resources.files("horreum.resolve.data")
            .joinpath("regions.json").read_text(encoding="utf-8"))
    return tuple(json.loads(text)["regions"])


def angular_sep_deg(ra1, dec1, ra2, dec2):
    """Odległość kątowa (STOPNIE) między dwoma punktami sfery niebieskiej — wzór wielkiego koła.

    SFERYCZNA, nie euklidesowa: stopnie RA kurczą się o `cos(dec)`, więc naiwna różnica myli się
    o 14% przy DEC 31° i o 52% przy DEC 61°. Klamp `asin` do 1.0 — zaokrąglenie zmiennoprzecinkowe
    daje argument >1 dla punktów niemal antypodalnych (`ValueError` bez klampu).

    Siostrzana `observatory.haversine_km` (`observatory.py:67`) liczy TEN SAM wzór, ale mnoży przez
    promień Ziemi i niesie politykę progu stanowisk (`THRESH_KM`). Import tamtej tylko po to, by
    wydzielić z niej promień Ziemi, sprzęgałby niebo z geografią mocniej, niż kosztuje sześć linii
    wzoru (MINIMAL bije ABSTRACT — ekstrakcja wspólnego prymitywu przy TRZECIM wołającym)."""
    p = math.pi / 180
    x = (math.sin((dec2 - dec1) * p / 2) ** 2
         + math.cos(dec1 * p) * math.cos(dec2 * p) * math.sin((ra2 - ra1) * p / 2) ** 2)
    return 2 * math.asin(min(1.0, math.sqrt(x))) / p


def resolve_region(ra_deg, dec_deg):
    """Współrzędne nagłówka → `ObjectIdentity` kompleksu albo None. Czysta funkcja.

    Decyzja WYŁĄCZNIE ze współrzędnych — funkcja nie widzi `object_raw` i nie może go zobaczyć
    (patrz „REGION NIE ALIASUJE" w nagłówku modułu). Brak którejkolwiek współrzędnej → None:
    porównanie przez `is None`, NIE przez falsy, bo **0.0 to realna wartość** deklinacji/rektascensji
    (`headers.py:38` „0 = wartość"; `test_headers.py` pinuje odczyt `ra_deg == 0.0`).

    Przy zachodzących regionach wygrywa NAJBLIŻSZY; remis rozstrzyga `canon` (klucz `(dist, canon)`
    jak `observatory.nearest_site:85`) — inaczej o wyniku decydowałaby kolejność wpisów w JSON-ie."""
    if ra_deg is None or dec_deg is None:
        return None

    best = None                                     # (dystans, canon) najbliższego trafionego
    for reg in load_regions():
        d = angular_sep_deg(ra_deg, dec_deg, reg["ra_deg"], reg["dec_deg"])
        if d <= reg["radius_deg"] and (best is None or (d, reg["canon"]) < best):
            best = (d, reg["canon"])
    if best is None:
        return None

    # catalog/kind USTAWIANE WPROST (jak solar.py:80) — `catalog_label` zwraca None dla gołego
    # słowa, a `catalog` jest kolumną renderowaną w gridzie (`gui/queries.py:151`).
    return ObjectIdentity(canon=best[1], catalog="region", kind="region",
                          source="region", alias_norm=None)
