"""Oś FILTR — `normalize_filter(filter_raw)` → kanon (PLAN §3.5/§Etap 6).

Czysta funkcja mapująca wariant nagłówkowego `FILTER` na kanon. `filter_raw` (header) zachowany
1:1; `filter_canon` (frame) = wynik. BEZ kanału review (W2): pusty/brak/none-token → None (świadomy
brak filtra, np. OSC bez koła), nie luka. Slot numeryczny koła (`1`–`7`) bez mapy per-rig →
nienormalizowalny → None. Nieznany niepusty → zachowany verbatim (zeznanie; mapa rośnie po firsthand).

Mapa = uniwersalia sprzętu jako KOD (`resolve/__init__`), formy z `custos/resolve/data/filters.json`
(zamrożony Custos, przeniesione). Wąskopasmowe/RGB/L oraz broadband (clip-in: L-Pro/L-eXtreme/… —
OSOBNA przestrzeń, NIE luminancja).
"""
from ._coerce import _to_text
from ._text import norm

# Wariant (po `norm`: upper, pojedyncze spacje) → kanon. Wąskopasmowe + RGB + L i broadband razem
# (rozłączne klucze). Kanon broadbandu zachowuje „ładną" pisownię (L-Pro/L-eXtreme).
_CANON = {
    "H": "Ha", "HA": "Ha", "H-ALPHA": "Ha", "HALPHA": "Ha", "HYDROGEN": "Ha",
    "HA3NM": "Ha", "HA-3NM": "Ha", "HA 3NM": "Ha",
    "S": "SII", "S2": "SII", "SII": "SII", "S-II": "SII", "SULFUR": "SII", "SULPHUR": "SII",
    "O": "OIII", "O3": "OIII", "OIII": "OIII", "O-III": "OIII", "OXYGEN": "OIII",
    "L": "L", "LUM": "L", "LUMINANCE": "L", "LUMINANCIA": "L",
    "R": "R", "RED": "R", "G": "G", "GREEN": "G", "B": "B", "BLUE": "B",
    "L-PRO": "L-Pro", "LPRO": "L-Pro", "L PRO": "L-Pro",
    "L-EXTREME": "L-eXtreme", "L-EX": "L-eXtreme", "LEXTREME": "L-eXtreme", "L-EX3": "L-eXtreme",
    "L-ENHANCE": "L-eNhance", "LENHANCE": "L-eNhance", "L-ENH": "L-eNhance",
    "L-ULTIMATE": "L-Ultimate", "LULTIMATE": "L-Ultimate",
    "CLS": "CLS", "CLS-CCD": "CLS",
}

# Tokeny „brak filtra" (świadomy None, nie review). „C" = clear (Custos: none_token).
_NONE = {"NOFILTER", "NONE", "NO FILTER", "CLEAR", "C", "EMPTY"}


def normalize_filter(filter_raw):
    """`FILTER` (str/None) → kanon (`Ha`/`OIII`/`L-Pro`/…) albo None. None gdy: brak/pusty/none-token
    (świadomy brak, W2) lub slot numeryczny bez mapy. Nieznany niepusty → zachowany verbatim
    (`filter_raw.strip()` — nie zgadujemy, firsthand domknie mapę)."""
    raw = _to_text(filter_raw)
    if raw is None:
        return None
    key = norm(raw)
    if key in _NONE:
        return None
    if key in _CANON:
        return _CANON[key]
    if key.isdigit():            # slot koła (1..7) bez mapy per-rig → nienormalizowalny
        return None
    return raw.strip()           # nieznany niepusty → zeznanie verbatim
