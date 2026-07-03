"""Oś OBIEKT — rozwiązanie `object_raw` → kanon (PLAN §3.5/§Etap 6).

Czysta funkcja `resolve_object(object_raw)` → `ObjectIdentity` albo None. Drabina (pierwsze
trafienie wygrywa):
  1. oznaczenie katalogowe (`catalog_canon`) + równoważność (`xref`, NGC-wins) — `source='header'`
     gdy kanon bez zmian, `source='catalog_xref'` gdy zmapowany (M106→NGC4258, Sh2-190→IC1805);
  2. nazwa potoczna (`_COMMON`, uniwersalia nieba) → kanon — `source='common_name'`;
  3. nic pewnego → None (warstwa wyżej rozstrzyga, czy to delta — TYLKO dla light/master_light;
     kalibracja nie ma obiektu z definicji).

KIND-AWARENESS mieszka w orkiestracji (`horreum.resolver`), nie tu: ta funkcja ocenia sam string.
Solar/komety (Lemmon/Księżyc/planety) rozwiązuje `resolve.solar` (krok 5a), wołany PRZED `resolve_object`
w orkiestracji — ta funkcja pozostaje deep-sky-only. `kind='deep_sky'` dla wszystkiego, co tu wychodzi.

`_COMMON` = uniwersalia (wiedza o niebie jako KOD, jak deklaruje `resolve/__init__`) — NIE dane
per-archiwum. Rośnie po firsthand; seed = przypadki nazwane w spec §3.5 + potwierdzone firsthand
(Elephant's Trunk, Pelican, Bode's Galaxy). Nazwy potoczne dopuszczają sufiks deskryptora
(„Rosette Nebula", „Bode's Galaxy") — zdejmowany przed dopasowaniem.
"""
import re
from dataclasses import dataclass

from ._coerce import _to_text
from ._text import norm, norm_alnum
from .catalog import catalog_canon, catalog_label, xref

# Nazwy potoczne → oznaczenie katalogowe (przed xref; np. Heart→IC1805, Bode's Galaxy→M81→NGC3031).
# Klucze dopasowywane przez `norm_alnum` (apostrof/spacja/„the"/deskryptor nieistotne).
_COMMON = {
    "ROSETTE": "NGC2237",          # spec §3.5
    "HEART": "IC1805",
    "SOUL": "IC1848",
    "PELICAN": "IC5070",
    "NORTHAMERICA": "NGC7000",
    "ELEPHANTSTRUNK": "Sh2-131",   # firsthand: realny light w archiwum
    "BODES": "M81",                # „Bode's Galaxy" → M81 → (xref) NGC3031
    # Etap 6.x — braki wykryte firsthand (scalają z rodzeństwem katalogowym, nie rozbijają):
    "CIGAR": "M82",                # „Cigar Galaxy" → M82 → (xref) NGC3034 (scala z „M 82")
    "FLAMINGSTAR": "IC405",        # „Flaming Star Nebula" (folder Sh2-229, brak rodzeństwa katalog.)
    "BUBBLE": "NGC7635",           # „Bubble Nebula" (scala z „NGC 7635")
}

# Deskryptor na końcu nazwy potocznej (zdejmowany przed dopasowaniem) i przedrostek „the".
_DESCRIPTOR = re.compile(r"\s+(NEBULA|GALAXY|CLUSTER|COMPLEX)$")
_THE = re.compile(r"^THE\s+")


@dataclass(frozen=True)
class ObjectIdentity:
    """Rozwiązana oś OBIEKT — wejście dla `repo.upsert_object`/`add_object_alias`/`assign_object`.
    Czysta dana, NIE zapis."""
    canon: str           # NGC4258 | Sh2-131 | M45 …
    catalog: object      # NGC | IC | Sh2 | Messier | … (None gdy nieznany prefiks)
    kind: str            # deep_sky (solar/comet poza pierwszym przebiegiem)
    source: str          # header | catalog_xref | common_name
    alias_norm: str      # znormalizowana forma surowa (klucz object_alias)


def _common_canon(raw):
    """Nazwa potoczna → oznaczenie katalogowe (przed xref) albo None. Zdejmuje „the"/deskryptor,
    porównuje przez `norm_alnum`."""
    key = _THE.sub("", norm(raw))
    key = _DESCRIPTOR.sub("", key)
    return _COMMON.get(norm_alnum(key))


def resolve_object(object_raw):
    """`object_raw` (zeznanie nagłówka) → `ObjectIdentity` albo None (nierozpoznane). Czysta funkcja.

    Brak/pusty → None (nie ma czego rozwiązywać). Oznaczenie katalogowe → kanon + xref; nazwa
    potoczna → kanon przez `_COMMON` + xref. None ⇒ warstwa wyżej decyduje o delcie (zależnie od
    `kind` — kalibracja nie ma obiektu, więc jej None to poprawny stan, nie delta)."""
    raw = _to_text(object_raw)
    if raw is None:
        return None

    cc = catalog_canon(raw)
    if cc:
        final = xref(cc)
        source = "catalog_xref" if final != cc else "header"
        return ObjectIdentity(canon=final, catalog=catalog_label(final), kind="deep_sky",
                              source=source, alias_norm=norm_alnum(raw))

    common = _common_canon(raw)
    if common:
        final = xref(common)
        return ObjectIdentity(canon=final, catalog=catalog_label(final), kind="deep_sky",
                              source="common_name", alias_norm=norm_alnum(raw))

    return None
