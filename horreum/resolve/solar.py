"""Oś OBIEKT — Układ Słoneczny i komety (PLAN krok 5a; port `custos/resolve/solar.py`).

Domyka oś OBIEKT o interpretacje, których pierwszy przebieg deep-sky świadomie NIE robił
(`objects.py:12-13`). Ciała US i komety mają WŁASNE ID (nie katalogi mgławic), więc rozwiązywane
PRZED drabiną katalogową (orkiestracja `resolver.py`). Czysta funkcja `resolve_solar(object_raw)`
→ `ObjectIdentity` albo None. HEADER-PRIMARY: wejście = `object_raw` (zeznanie nagłówka), NIE ścieżka
(dawca skanował `dir_parts` — pień ufa naprawionemu nagłówkowi).

Rozstrzygnięcia (recenzja kroku 5):
  * CIAŁO = dopasowanie EXACT (`object_raw` == token, po fold ASCII/upper) — NIE substring: NGC7009
    „Saturn Nebula" NIE może dać planety Saturn (mgławica planetarna ≠ ciało). „saturn"/„Jupiter"/
    „ksiezyc" (bare) łapią; „Saturn Nebula" spada do drabiny deep-sky (i dalej do delty).
  * KOMETA = oznaczenie IAU (`C/2023 A3`) LUB token (`Lemmon`); token I desig tej samej komety →
    JEDEN `canon` (inaczej dwa wiersze `object` na jedną kometę — `object.canon UNIQUE`).
  * Wejście znormalizowane do UPPER przed regexem IAU (`object_raw` bywa lowercase `c/2023 a3`).

Słowniki = uniwersalia (wiedza o niebie jako KOD, jak `_COMMON`/`_CANON`), rosną firsthand — nie
asset JSON (małe, uniwersalne). `kind='solar_system'|'comet'`, `catalog='solar'|'comet'`,
`source='solar'|'comet'` (ustawiane WPROST — `catalog_label` zwraca None dla `Moon`, nie jest wołany).
"""
import re

from ._coerce import _to_text
from ._text import norm_alnum, norm_ascii
from .objects import ObjectIdentity

# Ciała US: token (UPPER ASCII) → nazwa kanoniczna EN. Dopasowanie EXACT (całe object_raw == token).
_BODIES = {
    "KSIEZYC": "Moon", "MOON": "Moon", "LUNA": "Moon",
    "SLONCE": "Sun", "SUN": "Sun",
    "MERKURY": "Mercury", "MERCURY": "Mercury",
    "WENUS": "Venus", "VENUS": "Venus",
    "MARS": "Mars",
    "JOWISZ": "Jupiter", "JUPITER": "Jupiter",
    "SATURN": "Saturn",
    "URAN": "Uranus", "URANUS": "Uranus",
    "NEPTUN": "Neptune", "NEPTUNE": "Neptune",
}

# Kometa: desig IAU → PEŁNY canon (znane komety archiwum). Nieznany desig → sam desig (canon = desig).
_COMET_CANON = {
    "C/2025 A6": "C/2025 A6 (Lemmon)",
    "C/2023 A3": "C/2023 A3 (Tsuchinshan-ATLAS)",
    "21P": "21P/Giacobini-Zinner",
}
# Token potoczny komety → desig (spina token z oznaczeniem: JEDEN canon na kometę).
_COMET_TOKEN = {"LEMMON": "C/2025 A6", "TSUCHINSHAN": "C/2023 A3", "GIACOBINI": "21P"}

# Oznaczenie IAU: litera typu + rok + kod połowy miesiąca (C/2025 A6, P/2019 Y4). Na UPPER.
_COMET_IAU = re.compile(r"(?<![A-Z0-9])([CPDX])[ /_-]?(\d{4})[ _-]?([A-Z]\d{1,3})\b")


def _comet_identity(canon, raw):
    return ObjectIdentity(canon=canon, catalog="comet", kind="comet",
                          source="comet", alias_norm=norm_alnum(raw))


def resolve_solar(object_raw):
    """`object_raw` (zeznanie nagłówka) → `ObjectIdentity` (Układ Słoneczny/kometa) albo None.
    Czysta funkcja. Kolejność: (1) oznaczenie IAU komety, (2) token komety, (3) ciało EXACT.
    None ⇒ nie solar (warstwa wyżej próbuje drabiny deep-sky, potem delty)."""
    raw = _to_text(object_raw)
    if raw is None:
        return None
    u = norm_ascii(raw)              # UPPER + fold ASCII (Księżyc→KSIEZYC, c/2023 a3→C/2023 A3)

    # (1) oznaczenie IAU komety — canon z mapy znanych, inaczej sam desig
    m = _COMET_IAU.search(u)
    if m:
        desig = f"{m.group(1)}/{m.group(2)} {m.group(3)}"
        return _comet_identity(_COMET_CANON.get(desig, desig), raw)

    # (2) token potoczny komety (Lemmon/Comet Lemmon) — granica słowa, nie substring
    for tok, desig in _COMET_TOKEN.items():
        if re.search(rf"(?<![A-Z]){re.escape(tok)}(?![A-Z])", u):
            return _comet_identity(_COMET_CANON.get(desig, desig), raw)

    # (3) ciało US — EXACT (całe object_raw == token). „Saturn Nebula" tu NIE trafia (bezpiecznik F2)
    if u in _BODIES:
        return ObjectIdentity(canon=_BODIES[u], catalog="solar", kind="solar_system",
                              source="solar", alias_norm=norm_alnum(raw))

    return None
