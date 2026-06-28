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


def _to_int(value):
    """str/liczba → int; None / `''` / niekonwertowalny → None (W3). XISF daje stringi (`'100'`,
    bywa `'100.0'`) — `int(float(x))` znosi oba. UWAGA: `0`/`'0'` to POPRAWNA wartość (np. OFFSET=0),
    NIE None — rozróżniaj (nie `if value:`)."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_text(value):
    """liczba/str → str; None lub pusty `''` → None. Pole TEXT „spójnie" niezależnie od formatu:
    `GAIN` jako FITS-int `100` i XISF-string `'100'` dają jednakowo `'100'` (audyt). UWAGA W2:
    pusty `''` (np. FILTER nieobecny) → None; ale `0` → `'0'` (zero to wartość, nie brak)."""
    if value is None:
        return None
    s = str(value)
    return s if s != "" else None
