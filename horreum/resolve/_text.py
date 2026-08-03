"""Normalizacja tekstu do porównań — przeniesione 1:1 z `custos/resolve/maps.py`."""
import re
import unicodedata


def norm(s):
    """Znormalizuj token do porównań: upper, pojedyncze spacje, bez skrajnych spacji."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip()).upper()


def norm_ascii(s):
    """Jak `norm`, ale najpierw fold diakrytyków do ASCII (NFKD): `Księżyc`→`KSIEZYC`. Do
    dopasowań, gdzie zeznanie nagłówka bywa z ogonkami (solar `resolve/__init__`)."""
    if s is None:
        return ""
    folded = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return norm(folded)


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
