"""Oś OBIEKT — uniwersalia katalogowe: rozpoznanie oznaczenia + równoważność (NGC-wins).

Trzy czyste funkcje (zero zapisu):
  - `catalog_canon(text)` — rozpoznaj oznaczenie katalogowe i znormalizuj zapis
    (`NGC 4736`→`NGC4736`, `Sh2 131`→`Sh2-131`, zera wiodące precz). None, gdy to NIE oznaczenie
    (nazwa potoczna „Heart Nebula" NIE przechodzi jako kanon — koniec cichego śmieciowego kanonu).
  - `xref(canon)` — równoważność międzykatalogowa (Messier/Caldwell/Sh2 → NGC/IC, polityka NGC-wins),
    DANYMI z `catalog_xref.json` (nie precedencją). Brak wpisu → kanon bez zmian (M45 zostaje M45).
  - `catalog_label(canon)` — etykieta katalogu z formy kanonicznej (NGC|IC|Sh2|Messier|…).

Reguły rozpoznania przeniesione z `custos/resolve/catalog.py` (zamrożony Custos) — formy gramatyk
katalogowych to UNIWERSALIA nieba, nie dane per-archiwum. `catalog_xref.json` = jedyny ASSET danych
(jedzie w wheelu, bramka clone'a); nazwy potoczne mieszkają w `resolve.objects` (kod, §Etap 6).
"""
import functools
import json
import re
from importlib import resources


@functools.lru_cache(maxsize=1)
def load_catalog_xref():
    """Wczytaj catalog_xref.json (cache). Klucze: messier_to_ngc, caldwell_to_ngc,
    sh2_to_ic, cross_to_ngc — wszystkie alias->kanon (NGC-wins)."""
    text = (resources.files("horreum.resolve.data")
            .joinpath("catalog_xref.json").read_text(encoding="utf-8"))
    return json.loads(text)


# Reguły rozpoznania: (regex CAŁEGO tokenu po normalizacji, budowniczy kanonu). Bez fallbacku do
# surowej nazwy — tekst spoza tych gramatyk daje None (nazwa potoczna nie udaje kanonu). Forma bez
# zer wiodących (M82 nie M082; NGC224 nie NGC0224). Messier/Caldwell = alias-only (xref → NGC/IC).
_RULES = [
    (re.compile(r"^(?:M|MESSIER)\s*0*(\d{1,3})$"), lambda m: f"M{int(m.group(1))}"),
    (re.compile(r"^(?:C|CALDWELL)\s*0*(\d{1,3})$"), lambda m: f"C{int(m.group(1))}"),
    (re.compile(r"^(NGC|IC|UGC|PGC)\s*0*(\d{1,5})$"),
     lambda m: f"{m.group(1).upper()}{int(m.group(2))}"),
    (re.compile(r"^SH\s*2?\s*-?\s*0*(\d{1,3})$"), lambda m: f"Sh2-{int(m.group(1))}"),
    (re.compile(r"^(LBN|LDN)\s*0*(\d{1,4})$"),
     lambda m: f"{m.group(1).upper()}{int(m.group(2))}"),
    (re.compile(r"^CTB\s*0*(\d{1,3})$"), lambda m: f"CTB{int(m.group(1))}"),
    (re.compile(r"^(?:B|BARNARD)\s*0*(\d{1,3})$"), lambda m: f"B{int(m.group(1))}"),
    (re.compile(r"^ABELL\s*0*(\d{1,4})$"), lambda m: f"Abell{int(m.group(1))}"),
    (re.compile(r"^(?:VDB|VAN\s*DEN\s*BERGH)\s*0*(\d{1,4})$"), lambda m: f"vdB{int(m.group(1))}"),
    (re.compile(r"^CED(?:ERBLAD)?\s*0*(\d{1,4})$"), lambda m: f"Ced{int(m.group(1))}"),
    (re.compile(r"^(?:CR|COLLINDER)\s*0*(\d{1,4})$"), lambda m: f"Cr{int(m.group(1))}"),
]


def catalog_canon(text):
    """Zwróć formę kanoniczną oznaczenia katalogowego LUB None, gdy tekst nim NIE jest.

    Normalizuje zapis: kolaps białych znaków, upper, zdjęcie zer wiodących (`NGC 4736`→`NGC4736`,
    `Sh2 131`→`Sh2-131`, `M 81`→`M81`). Apostrofy/inne znaki w nazwie potocznej → po prostu brak
    dopasowania (None) — nazwa potoczna należy do `resolve.objects`, nie tu."""
    if not text:
        return None
    key = re.sub(r"\s+", " ", str(text).strip()).upper()
    for rx, build in _RULES:
        m = rx.match(key)
        if m:
            return build(m)
    return None


@functools.lru_cache(maxsize=1)
def _xref_flat():
    """Spłaszcz wszystkie tabele równoważności (messier/caldwell/sh2/cross) w jeden słownik
    {oznaczenie: kanon_preferowany}. Wartości są NGC/IC (NGC-wins zaszyte w danych)."""
    flat = {}
    for table in load_catalog_xref().values():
        if isinstance(table, dict):
            flat.update(table)
    return flat


def xref(canon):
    """Równoważność międzykatalogowa: `canon` → preferowany kanon NGC/IC, gdy istnieje wpis;
    inaczej `canon` bez zmian (M45/M24/M40 nie mają NGC → zostają Messierem). Stosuj na formie z
    `catalog_canon` (M106→NGC4258, Sh2-190→IC1805; NGC4258→NGC4258)."""
    return _xref_flat().get(canon, canon)


# Etykieta katalogu z formy kanonicznej (prefiks). Dłuższe/specyficzne prefiksy PRZED krótszymi
# (Ced/Cr/CTB przed C; vdB przed V; Barnard `B\d` osobno) — pierwsze trafienie wygrywa.
_LABELS = [
    (re.compile(r"^NGC\d"), "NGC"), (re.compile(r"^IC\d"), "IC"), (re.compile(r"^Sh2-\d"), "Sh2"),
    (re.compile(r"^UGC\d"), "UGC"), (re.compile(r"^PGC\d"), "PGC"),
    (re.compile(r"^LBN\d"), "LBN"), (re.compile(r"^LDN\d"), "LDN"),
    (re.compile(r"^Abell\d"), "Abell"), (re.compile(r"^vdB\d"), "vdB"),
    (re.compile(r"^Ced\d"), "Ced"), (re.compile(r"^Cr\d"), "Collinder"),
    (re.compile(r"^CTB\d"), "CTB"), (re.compile(r"^B\d"), "Barnard"),
    (re.compile(r"^M\d"), "Messier"), (re.compile(r"^C\d"), "Caldwell"),
]


def catalog_label(canon):
    """Etykieta katalogu (`object.catalog`) z formy kanonicznej: NGC4258→'NGC', Sh2-131→'Sh2',
    M45→'Messier'. None dla formy nierozpoznanej."""
    if not canon:
        return None
    for rx, label in _LABELS:
        if rx.match(canon):
            return label
    return None
