"""Normalizacja tekstu do porównań — przeniesione 1:1 z `custos/resolve/maps.py`."""
import re


def norm(s):
    """Znormalizuj token do porównań: upper, pojedyncze spacje, bez skrajnych spacji."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip()).upper()


def norm_alnum(s):
    """Mocniejsza normalizacja: tylko alfanumeryki (do dopasowań aliasów/obiektów)."""
    return re.sub(r"[^A-Z0-9]+", "", norm(s))
