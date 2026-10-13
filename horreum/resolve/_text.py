"""Normalizacja tekstu do porównań - przeniesione z `custos/resolve/maps.py`; `norm_ascii` składa
tu dodatkowo `ł` (AR-126), reszta 1:1."""
import re
import unicodedata


def norm(s):
    """Znormalizuj token do porównań: upper, pojedyncze spacje, bez skrajnych spacji."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip()).upper()


#: Litery bez rozkładu NFKD: dla Unicode „ł" jest osobną literą, nie „l z kreską", więc
#: `unicodedata.normalize` jej nie rusza, a `encode("ascii", "ignore")` ją wycina („Słońce" →
#: `SONCE`). Jedyna taka litera alfabetu polskiego (AR-126).
LITERY_BEZ_ROZKLADU = str.maketrans({"ł": "l", "Ł": "L"})


def norm_ascii(s):
    """Jak `norm`, ale najpierw fold diakrytyków do ASCII (NFKD, a `ł` tablicą wyżej):
    `Księżyc`→`KSIEZYC`, `Słońce`→`SLONCE`. Do dopasowań, gdzie zeznanie nagłówka bywa z ogonkami
    (solar `resolve/__init__`)."""
    if s is None:
        return ""
    rozlozone = unicodedata.normalize("NFKD", str(s).translate(LITERY_BEZ_ROZKLADU))
    return norm(rozlozone.encode("ascii", "ignore").decode("ascii"))


def norm_alnum(s):
    """Mocniejsza normalizacja: tylko alfanumeryki (do dopasowań aliasów/obiektów)."""
    return re.sub(r"[^A-Z0-9]+", "", norm(s))


#: Rozdzielnik segmentów ścieżki — `\` i `/` naraz, JEDEN właściciel dla wszystkich osi czytających
#: drzewo (rodzaj klatki, obiekt ze ścieżki). `Path().parts` tej roboty nie wykona: poza Windows nie
#: uzna `\` za rozdzielnik, więc jedna oś milczałaby tam, gdzie druga mówi (R-S0-12).
_SEP = re.compile(r"[\\/]+")


def path_segments(path):
    """Ścieżka → krotka segmentów (puste odsiane). Ta sama odpowiedź na każdym systemie."""
    return tuple(s for s in _SEP.split(path or "") if s)
