"""Rzutowanie wartości nagłówka na typ pola gorącego (W3, PLAN §2).

XISF zwraca wartości jako STRINGI (`'3.76'`, `'1600'`), FITS jako liczby. Pole gorące
(pixel_um, focratio, ogniskowa…) MUSI mieć typ jednolity — inaczej oś tożsamości rozbije się
FITS-vs-XISF (pixel `'3.76'` ≠ `3.76` → dwie kamery). `raw_json` zostaje gdzie indziej 1:1
surowy (zeznanie, jak przyszło); TU rzutujemy WYŁĄCZNIE pola gorące.

Nierozstrzygalne (None / pusty / niekonwertowalny) → None — review w warstwie wyżej, NIGDY crash.
"""


def _to_float(value):
    """str/liczba → float; None / `''` / niefloat → None (W3). `float()` sam zdejmuje białe znaki."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
