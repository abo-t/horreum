"""Oś OBSERWATORIUM — punkt GPS z nagłówka → stanowisko (PLAN_os_obserwatorium §1/§2/§7).

Czyste funkcje wiedzy geometrycznej (jak `resolve/solar.py`), ZERO DB/Qt — przechodzą bramkę
izolowanego clone'a. Parser GPS SPOT (`parse_coord`) obsługuje DWA formaty nagłówka:
dziesiętny (`50.1234567`) i DMS ze spacją (`+41 12 30.500`) — separator DMS to ZAWSZE spacja
(0 dwukropków w danych), znak `+`/`-` obsłużony (półkula S / długość W).

Tożsamość osi jest GEOMETRYCZNA, nie stringowa (GPS nie ma stabilnego klucza — jitter <0.1 km):
`nearest_site` to prymitywa dopasowania „punkt → istniejące stanowisko ≤ próg", współdzielona przez
`repo.propose_observatory` (produkcja: kotwica idempotencji ANCHOR-PROXIMITY, §2b) i walidację greedy
offline (§2) — JEDNA ścieżka, SPOT. Próg `THRESH_KM` = 4 km: ground-truth Zdzinia dom↔praca = 4.385 km
(rozdzielone z marginesem 0.385 km), a jitter <0.1 km zlewa się.

Nierozstrzygalny GPS (None / nan / inf / śmieć) → None, NIGDY crash resolvera (KIND-AGNOSTIC §0).
"""
import math
import re

from ._coerce import _to_text

# Próg klastra: ≤ THRESH_KM od seeda = to samo stanowisko (Zdzin; sonda 24 pkt→11 stanowisk). Stała
# nazwana, nie literał (UNIWERSALNOŚĆ §0) — inny user tunuje przez config, gdy jego stanowiska są bliżej.
THRESH_KM = 4.0

# DMS: znak? + stopnie + SPACJA + minuty + SPACJA + sekundy (zakotwiczony $). Sonda: separator=SPACJA,
# 0 dwukropków → regex bez `:` (SIN-PRECRUFT ścięty). Dziesiętny NIE przechodzi tędy (łapie go float()).
_DMS = re.compile(r"([+-]?)(\d+) +(\d+) +([\d.]+)$")


def parse_coord(raw):
    """SITELAT/SITELONG (`value_raw` z `cards`) → stopnie dziesiętne (skończone) | None. Dwa formaty:
    `'50.123'` (dziesiętny) i `'+41 12 30.5'` (DMS). Nieparsowalny/`nan`/`inf` → None (klatka poza
    osią, NIGDY crash resolvera — KIND-AGNOSTIC §0). `value_raw` jest stringiem dla OBU typów kart
    (sonda: float-karta niesie i `value_raw='37.9902'`, i `value_num`; DMS ma `value_num=NULL`)."""
    s = _to_text(raw)
    if s is None:
        return None
    s = s.strip()
    val = None
    try:
        val = float(s)                                  # dziesiętny (`float` sam zdejmuje białe znaki)
    except ValueError:
        m = _DMS.match(s)
        if m:
            sign = -1 if m.group(1) == "-" else 1
            try:                                        # DMS wewnątrz try — `'18.9.30'` nie wysadza
                val = sign * (float(m.group(2)) + float(m.group(3)) / 60 + float(m.group(4)) / 3600)
            except ValueError:
                return None
    return val if (val is not None and math.isfinite(val)) else None   # ubija nan/inf


def site_coords(lat_raw, lon_raw):
    """(lat, lon) w zakresie albo None — reguła „oba albo NULL" (§1). UNIWERSALNOŚĆ: znormalizuj
    konwencję 0-360° długości do [-180, 180] PRZED sprawdzeniem zakresu (dane dziś 9.4-38.8, ale
    soft bywa różny).

    Sentinel (0, 0) „null island" → None (#2, §4): EXIF DSLR zapisuje (0,0) gdy aparat nie miał
    fixa GPS — to „unset", nie pozycja (zmierzone: 12/12 Canonów w archiwum). Filtr jest KONIUNKCJĄ
    `lat==0 AND lon==0`: sam równik (`lat=0`) czy sam południk Greenwich (`lon=0`) to WARTOŚCI, nie
    sentinel. SPOT — reguła żyje tu, przy walidacji zakresu, nie rozproszona w czytniku EXIF."""
    lat, lon = parse_coord(lat_raw), parse_coord(lon_raw)
    if lat is None or lon is None:
        return None
    if lon > 180:
        lon -= 360                                      # 0-360 → [-180, 180] (270°→-90°)
    if lat == 0 and lon == 0:                           # null island — „brak fixa", nie pozycja
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return (lat, lon)


def haversine_km(a, b):
    """Dystans wielkiego koła (km) między (lat, lon) w stopniach. Klamp `asin` do 1.0 — zaokrąglenie
    zmiennoprzecinkowe może dać argument >1 dla punktów niemal antypodalnych (`ValueError` bez klampu)."""
    (la1, lo1), (la2, lo2) = a, b
    R, p = 6371.0, math.pi / 180
    x = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * R * math.asin(min(1.0, math.sqrt(x)))


def nearest_site(pt, sites, thresh=THRESH_KM):
    """`pt` = (lat, lon); `sites` = iterowalne `(id, lat, lon)`. Zwróć id NAJBLIŻSZEGO stanowiska
    w promieniu ≤ `thresh` (tie-break: mniejszy dystans, potem mniejsze id) albo None gdy żadne ≤ próg.
    Dystans DO seeda każdego stanowiska (nie tranzytywnie — unika łańcuchów, §2). Współdzielona przez
    `repo.propose_observatory` (produkcja, §2b) i greedy-walidację offline (§2) — SPOT."""
    best = None                                         # (dist, id) najlepszego dopasowania
    for sid, slat, slon in sites:
        d = haversine_km(pt, (slat, slon))
        if d <= thresh and (best is None or (d, sid) < best):
            best = (d, sid)
    return best[1] if best is not None else None
