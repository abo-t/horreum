"""BUDOWNICZY KATALOGU CELÓW — jedyne miejsce w repozytorium, które wychodzi do sieci (T2).

Produkt: `horreum/data/targets_core.json` + `targets_cirrus.json` — pula celów deep-sky
z pozycją, rozmiarem i aliasami. Aplikacja NIGDY nie woła sieci (D-0731-3): katalog odświeża się
PODMIANĄ PLIKU, a nie zapytaniem w terenie. Ten skrypt jest dev-owy i żyje poza pakietem.

TRZY KLUCZE TOŻSAMOŚCI, w tej kolejności (brief §4) — ten sam obłok siedzi w kilku katalogach:
  1. KANON — `xref(catalog_canon(a)) == xref(catalog_canon(b))` => scal BEZWARUNKOWO. To resolver
     mówi, że to jeden obiekt (Sh2-190 == IC1805 mimo rozmiarów 150' vs 60'); geometria nie ma tu
     głosu, a bramka proporcji zablokowałaby scalenie i wyprodukowała DWA rekordy o jednym kanonie.
  2. ALIAS KATALOGU — alias rekordu A rozwiązujący się na kanon rekordu B => scal. OpenNGC stwierdza
     `IC63 == LBN 622`; asercja katalogu jest mocniejsza niż odległość środków.
  3. POZYCJA — tylko MIĘDZY katalogami, tolerancja od WIĘKSZEJ osi (środek rozległej powłoki każdy
     katalog podaje gdzie indziej: NGC6960 i G074.0-08.5 dzieli 65'), z BRAMKĄ PROPORCJI 0,5:
     IC1396 (14') leży 0,4' od środka Sh2-131 (170') i jest OSOBNYM celem, nie duplikatem.

EPOKI SĄ RÓŻNE I NIE PRECESUJEMY ICH SAMI: Sh2 niesie B1900, LBN/LDN B1950, vdB/Green J2000.
VizieR liczy kolumny `_RAJ2000`/`_DEJ2000` i `_RA.icrs`/`_DE.icrs` po swojej stronie — bierzemy JE.
Surowe `RA1900`/`RA1950` leżą w tym samym pliku obok; pomyłka o jedną kolumnę to 0,5-1,2 stopnia
błędu, więc każdy z dwóch torów epokowych ma własną kotwicę w falsyfikatorach.

FALSYFIKATORY BIEGNĄ PRZY BUDOWIE, nie tylko w baterii — asset częściowy wygląda poprawnie i nie
zostałby zauważony. Twardy falsyfikator = wyjście z kodem != 0 (EXPECT). Widełki liczone PER
ŹRÓDŁO, bo domyślny limit VizieR (bez `-out.max=unlimited`) oddaje 50 wierszy i przeszedłby każdą
bramkę liczoną na sumie.

Użycie:
  python scripts/build_catalog.py                        # pobierz -> zbuduj -> zapisz
  python scripts/build_catalog.py --cache DIR            # pobrania trzymaj/czytaj z DIR
  python scripts/build_catalog.py --offline --cache DIR  # ZERO sieci; pada, gdy cache niepelny
  python scripts/build_catalog.py --dry-run              # policz i pokaz raport, nie zapisuj
  python scripts/build_catalog.py --archive-canons p.txt # + miekki falsyfikator pokrycia archiwum

Raport ASCII-safe (konsola Windows to cp1250). Licencje i proweniencja: `horreum/data/PROVENANCE.md`.
"""
import argparse
import csv
import io
import json
import math
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import date

# pakiet horreum z korzenia repo (skrypt leży w scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from horreum.resolve.catalog import catalog_canon, xref  # noqa: E402
# Taksonomia typów ma JEDNEGO właściciela — `horreum.targets` (T3 §3). Skrypt ją IMPORTUJE:
# gdyby trzymał kopię, filtr planera i podłoga assetu mogłyby się rozjechać po cichu.
from horreum.targets import DARK_TYPES, GALAXY_TYPES, NEBULA_TYPES  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "horreum", "data")
TIMEOUT_S = 90

# Podłoga TECHNICZNA puli — nie „wykonalność". Progi typo-zależne (6'/15'/mag 13) są suwakami
# w T3 (D-0731-10), a najniższe położenie suwaka to 4'/10'; asset trzyma jeden krok zapasu pod nim.
FLOOR_ARCMIN = 3.0
FLOOR_DARK_ARCMIN = 8.0

# Klasy typów OpenNGC — WŁAŚCICIELEM jest `horreum.targets` (import wyżej). Gromady BEZ mgławicy
# odrzucone świadomie („nie interesują mnie gromady"), `Cl+N` ZOSTAJE — gromada z mgławicą to cel
# fotograficzny.
GALAXY, NEBULA, DARK = GALAXY_TYPES, NEBULA_TYPES, DARK_TYPES

# Warstwa „cirrus" (D-0731-9): LBN/LDN to 2017 z 3579 rekordów i domyślnie ich nie widać.
CIRRUS_SRC = {"lbn", "ldn"}

# Kolejność zwycięzcy grupy. Green rozpada się na DWA szczeble, bo tylko 5 z 295 SNR ma oznaczenie,
# które zna gramatyka katalogowa: nienazwany `G078.2+02.1` nie ma prawa wygrać z `Sh2-108`,
# a nazwany `CTB1` musi wygrać ze wszystkim.
PRIO = {"ngc": 0, "green_named": 1, "sh2": 2, "green": 3, "vdb": 4, "lbn": 5, "ldn": 6}

MERGE_TOL_FACTOR = 0.35        # tolerancja pozycji = ten czynnik * WIĘKSZA oś (min. 2')
MERGE_RATIO_MIN = 0.50         # bramka proporcji: mniejszy obiekt w wielkim to NIE duplikat

_VIZIER = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source={cat}&-out.max=unlimited&-out={cols}"
_OPENNGC = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/{name}"

# Identyfikatory-śmieci z OpenNGC `Identifiers` odsiewa reguła „musi przejść catalog_canon";
# nazwy potoczne przechodzą osobną ścieżką (verbatim), bo to nimi użytkownik szuka.
_NED_COMPONENT = re.compile(r"\sNED\d+$")


@dataclass
class Row:
    """Wiersz źródłowy po normalizacji: pozycja J2000 w stopniach, rozmiary w minutach łuku."""
    ident: str                     # oznaczenie ŹRÓDŁOWE (przed kanonizacją)
    src: str                       # ngc|sh2|lbn|ldn|vdb|green
    typ: str
    ra: float
    dec: float
    major: float
    minor: float | None = None
    mag: float | None = None
    mag_from_b: bool = False
    names: list = field(default_factory=list)      # Identifiers + Common names (surowe)
    common: list = field(default_factory=list)     # same nazwy potoczne (verbatim)


# ──────────────────────────────────────────────────────────────── pobranie i parsowanie

def fetch(url, cache_dir, cache_name, offline):
    """Pobierz albo odczytaj z cache. `--cache` to POWTARZALNOŚĆ, nie optymalizacja: ten sam
    materiał musi dać się przemielić bez pytania CDS o zdanie po raz drugi."""
    path = os.path.join(cache_dir, cache_name) if cache_dir else None
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    if offline:
        raise SystemExit(f"BLAD: --offline, a w cache brakuje {cache_name}")
    print(f"  pobieram {cache_name} ...")
    text = urllib.request.urlopen(url, timeout=TIMEOUT_S).read().decode("utf-8", "replace")
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return text


def _fnum(s):
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _hms(s):
    """'02:32:41.51' albo '02 32 41.5' -> stopnie (RA). Puste -> None."""
    p = [x for x in re.split(r"[:\s]+", (s or "").strip()) if x]
    if not p:
        return None
    v = float(p[0]) + (float(p[1]) / 60 if len(p) > 1 else 0) + (float(p[2]) / 3600 if len(p) > 2 else 0)
    return v * 15.0


def _dms(s):
    """'+61:27:24.8' -> stopnie. Znak z PIERWSZEGO członu (minuty i sekundy są bezznakowe)."""
    raw = (s or "").strip()
    p = [x for x in re.split(r"[:\s]+", raw) if x]
    if not p:
        return None
    sign = -1 if p[0].startswith("-") else 1
    v = abs(float(p[0])) + (float(p[1]) / 60 if len(p) > 1 else 0) + (float(p[2]) / 3600 if len(p) > 2 else 0)
    return sign * v


def _vizier_rows(text):
    """Wiersze tabeli `asu-tsv`: komentarze `#`, potem nagłówek, jednostki i linia myślników."""
    lines = [l for l in (x.rstrip("\n") for x in io.StringIO(text)) if l.strip() and not l.startswith("#")]
    hdr = lines[0].split("\t")
    return [{h: v.strip() for h, v in zip(hdr, l.split("\t"))} for l in lines[3:]
            if len(l.split("\t")) == len(hdr)]


def parse_openngc(text, source_name):
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        name = r["Name"].strip()
        if _NED_COMPONENT.search(name):
            continue                       # komponenty NED to sub-wpisy obiektu, nie cele
        ra, dec = _hms(r["RA"]), _dms(r["Dec"])
        if ra is None or dec is None:
            continue
        v, b = _fnum(r["V-Mag"]), _fnum(r["B-Mag"])
        ident = [x.strip() for x in (r["Identifiers"] or "").split(",") if x.strip()]
        if r["M"].strip():
            ident.append(f"M{int(r['M'])}")
        common = [x.strip() for x in (r["Common names"] or "").split(",") if x.strip()]
        out.append(Row(ident=name, src="ngc", typ=r["Type"].strip(), ra=ra, dec=dec,
                       major=_fnum(r["MajAx"]), minor=_fnum(r["MinAx"]),
                       mag=v if v is not None else b, mag_from_b=v is None and b is not None,
                       names=ident + common, common=common))
    return [o for o in out if o.major], source_name


def parse_sh2(text):
    out = []
    for r in _vizier_rows(text):
        ra, dec, d = _fnum(r["_RAJ2000"]), _fnum(r["_DEJ2000"]), _fnum(r["Diam"])
        if ra is None or dec is None or not d:
            continue
        out.append(Row(ident=f"Sh2-{int(r['Sh2'])}", src="sh2", typ="HII", ra=ra, dec=dec, major=d))
    return out


def parse_lbn(text):
    out = []
    for r in _vizier_rows(text):
        if not r["Seq"].strip():
            continue
        ra, dec = _hms(r["_RA.icrs"]), _dms(r["_DE.icrs"])
        ds = sorted(x for x in (_fnum(r["Diam1"]), _fnum(r["Diam2"])) if x)
        if ra is None or dec is None or not ds:
            continue
        out.append(Row(ident=f"LBN{int(r['Seq'])}", src="lbn", typ="EmN", ra=ra, dec=dec,
                       major=ds[-1], minor=ds[0] if len(ds) > 1 else None))
    return out


def parse_ldn(text):
    """Rozmiar LDN to KOŁO RÓWNOWAŻNE z pola `Area` — katalog nie podaje średnicy. Dla filamentu
    to przybliżenie zawyżające zwartość; fakt jedzie do `_meta.sources`, żeby T3 nie brał go
    za pomiar."""
    out = []
    for r in _vizier_rows(text):
        if not r["LDN"].strip():
            continue
        ra, dec, a = _hms(r["_RA.icrs"]), _dms(r["_DE.icrs"]), _fnum(r["Area"])
        if ra is None or dec is None or not a:
            continue
        out.append(Row(ident=f"LDN{int(r['LDN'])}", src="ldn", typ="DrkN", ra=ra, dec=dec,
                       major=2 * math.sqrt(a / math.pi) * 60))
    return out


def parse_vdb(text):
    out = []
    for r in _vizier_rows(text):
        if not r["VdB"].strip():
            continue
        ra, dec, rad = _fnum(r["_RA"]), _fnum(r["_DE"]), _fnum(r["BRadMax"])
        if ra is None or dec is None or not rad:
            continue
        out.append(Row(ident=f"vdB{int(r['VdB'])}", src="vdb", typ="RfN", ra=ra, dec=dec,
                       major=2 * rad, mag=_fnum(r["Vmag"])))
    return out


def parse_green(text):
    """Katalog RADIOWY: nie niesie jasności optycznej, za to niesie SNR bez numeru NGC/IC —
    m.in. `G116.9+00.2` = CTB1, największy projekt archiwum. Kanon bierzemy z pola `Names`,
    gdy gramatyka katalogowa je zna; inaczej zostaje oznaczenie galaktyczne."""
    out = []
    for r in _vizier_rows(text):
        ra, dec, d = _hms(r["RAJ2000"]), _dms(r["DEJ2000"]), _fnum(r["MajDiam"])
        if ra is None or dec is None or not d:
            continue
        names = [x.strip() for x in (r["Names"] or "").split(",") if x.strip()]
        named = next((n for n in names if catalog_canon(n)), None)
        out.append(Row(ident=named or r["SNR"].strip(), src="green_named" if named else "green",
                       typ="SNR", ra=ra, dec=dec, major=d, minor=_fnum(r["MinDiam"]),
                       names=names + ([r["SNR"].strip()] if named else [])))
    return out


SOURCES = [
    ("ngc", "OpenNGC NGC.csv", _OPENNGC.format(name="NGC.csv"), "NGC.csv", 11000, "CC-BY-SA-4.0"),
    ("ngc_add", "OpenNGC addendum.csv", _OPENNGC.format(name="addendum.csv"), "addendum.csv", 55,
     "CC-BY-SA-4.0"),
    ("sh2", "Sharpless HII (VII/20)",
     _VIZIER.format(cat="VII/20", cols="Sh2,Diam") + "&-out.add=_RAJ2000,_DEJ2000", "sh2.tsv", 310,
     "CDS/VizieR"),
    ("lbn", "Lynds Bright Nebulae (VII/9)",
     _VIZIER.format(cat="VII/9", cols="Seq,Diam1,Diam2,_RA.icrs,_DE.icrs"), "lbn.tsv", 1000,
     "CDS/VizieR"),
    ("ldn", "Lynds Dark Nebulae (VII/7A)",
     _VIZIER.format(cat="VII/7A", cols="LDN,Area,_RA.icrs,_DE.icrs"), "ldn.tsv", 1750, "CDS/VizieR"),
    ("vdb", "van den Bergh reflection (VII/21)",
     _VIZIER.format(cat="VII/21", cols="VdB,BRadMax,Vmag,_RA,_DE"), "vdb.tsv", 155, "CDS/VizieR"),
    ("green", "Green Galactic SNR (VII/278)",
     _VIZIER.format(cat="VII/278", cols="SNR,RAJ2000,DEJ2000,MajDiam,MinDiam,Names"),
     "snr_green.tsv", 290, "CDS/VizieR"),
]


def load_all(cache_dir, offline):
    """Pobierz i sparsuj wszystkie źródła. Widełki PER ŹRÓDŁO — urwane pobranie musi paść tutaj,
    a nie przejść niezauważone w sumie."""
    rows, meta = [], []
    for key, title, url, cache_name, min_rows, lic in SOURCES:
        text = fetch(url, cache_dir, cache_name, offline)
        if key == "ngc":
            got, _ = parse_openngc(text, key)
        elif key == "ngc_add":
            got, _ = parse_openngc(text, key)
        else:
            got = {"sh2": parse_sh2, "lbn": parse_lbn, "ldn": parse_ldn,
                   "vdb": parse_vdb, "green": parse_green}[key](text)
        if len(got) < min_rows:
            raise SystemExit(f"BLAD: zrodlo {key} oddalo {len(got)} wierszy z rozmiarem, "
                             f"minimum {min_rows} -> pobranie urwane albo katalog sie zmienil")
        rows += got
        meta.append({"key": key, "title": title, "url": url, "rows": len(got), "license": lic})
        print(f"  {key:<8} {len(got):>6} wierszy z pozycja i rozmiarem")
    return rows, meta


# ──────────────────────────────────────────────────────────────── pula, scalanie, rekordy

def klasa(typ):
    return ("galaxy" if typ in GALAXY else "nebula" if typ in NEBULA
            else "dark" if typ in DARK else None)


def pool(rows):
    """Typ dopuszczony + rozmiar nad podłogą. Magnitudo NIE filtruje — to kryterium typo-zależne
    (dla mgławicy emisyjnej kłamie) i należy do T3."""
    out = []
    for o in rows:
        k = klasa(o.typ)
        if k and o.major >= (FLOOR_DARK_ARCMIN if k == "dark" else FLOOR_ARCMIN):
            out.append(o)
    return out


def canon_of(row):
    """Kanon TĄ SAMĄ funkcją co resolver; poza gramatyką (291 `G...` Greena, 33 lettered/ESO)
    zostaje oznaczenie źródłowe — resolver też by dla nich kanonu nie wyprodukował, więc udawanie
    sklejenia z archiwum byłoby kłamstwem."""
    c = catalog_canon(row.ident)
    return xref(c) if c else row.ident


def separation(a, b):
    ra1, d1, ra2, d2 = map(math.radians, (a.ra, a.dec, b.ra, b.dec))
    return math.degrees(math.acos(max(-1.0, min(1.0, math.sin(d1) * math.sin(d2)
                                                + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)))))


def merge(items):
    """Union-find po trzech kluczach (nagłówek modułu). Zwraca listę grup + licznik scaleń.

    Domknięcie TRANZYTYWNE jest zamierzone: `NGC1499 + Sh2-220 + LBN752 + LBN756` to jeden cel,
    choć dwa ostatnie są z tego samego katalogu i same nigdy by się nie połączyły. Grupy
    wielokrotne z jednego katalogu RAPORTUJEMY — mają być widziane, nie ciche."""
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    stat = {"canon": 0, "alias": 0, "position": 0}

    def union(i, j, key):
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a
            stat[key] += 1

    by_canon = {}
    for i, o in enumerate(items):
        by_canon.setdefault(canon_of(o), []).append(i)
    for idxs in by_canon.values():                                   # klucz 1: KANON
        for j in idxs[1:]:
            union(idxs[0], j, "canon")
    for i, o in enumerate(items):                                    # klucz 2: ALIAS KATALOGU
        own = canon_of(o)
        for a in o.names:
            c = catalog_canon(a)
            if c and xref(c) != own and xref(c) in by_canon:
                union(i, by_canon[xref(c)][0], "alias")

    buckets = {}                                                     # klucz 3: POZYCJA
    for i, o in enumerate(items):
        buckets.setdefault((int(o.ra // 2), int((o.dec + 90) // 2)), []).append(i)
    for (bx, by), idxs in buckets.items():
        near = [k for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                for k in buckets.get((bx + dx, by + dy), ())]
        for i in idxs:
            for j in near:
                if j <= i:
                    continue
                a, b = items[i], items[j]
                if a.src == b.src:
                    continue                       # w jednym katalogu zagnieżdżenie to STRUKTURA
                lo, hi = sorted((a.major, b.major))
                if lo / hi < MERGE_RATIO_MIN:
                    continue                       # BRAMKA PROPORCJI
                if separation(a, b) * 60 <= max(2.0, MERGE_TOL_FACTOR * hi):
                    union(i, j, "position")

    groups = {}
    for i, o in enumerate(items):
        groups.setdefault(find(i), []).append(o)
    return list(groups.values()), stat


def build_record(group):
    """Rekord assetu z grupy. Zwycięzca wg PRIO (remis -> większa oś); przegrani NIE giną —
    ich kanony wchodzą do aliasów ZAWSZE (to klucze tożsamości, więc filtr gramatyki ich nie
    dotyczy: `catalog_canon('G074.0-08.5')` jest z definicji None)."""
    win = sorted(group, key=lambda o: (PRIO[o.src], -o.major))[0]
    own = canon_of(win)
    # Oznaczenie ŹRÓDŁOWE wchodzi obok kanonu — w formie SPRZED `xref`: `Sh2-184` kanonizuje się
    # na `NGC281`, więc bez tego przegrany zniknąłby bez śladu i użytkownik nie znalazłby celu pod
    # nazwą, której realnie używa. Bierzemy `catalog_canon`, nie surowy string, żeby nie wsypać
    # do aliasów zapisu z zerami wiodącymi (`IC0410` obok `IC410`).
    alias = {canon_of(o) for o in group} | {catalog_canon(o.ident) or o.ident for o in group}
    for o in group:
        alias.update(xref(catalog_canon(a)) for a in o.names if catalog_canon(a))
        alias.update(o.common)
    alias.discard(own)
    rec = {"c": own, "t": win.typ, "r": round(win.ra, 4), "d": round(win.dec, 4),
           "a": round(win.major, 1)}
    if win.minor:
        rec["b"] = round(win.minor, 1)
    if win.mag is not None:
        rec["m"] = round(win.mag, 2)
        if win.mag_from_b:
            rec["mb"] = True          # B-V galaktyk to +0,7..1,0 mag — prog T3 musi to wiedzieć
    if alias:
        rec["n"] = sorted(alias)
    rec["_layer"] = "cirrus" if win.src in CIRRUS_SRC else "core"
    return rec


# ──────────────────────────────────────────────────────────────── falsyfikatory

def _find(records, canon):
    return next((r for r in records if r["c"] == canon), None)


def falsifiers(records, curated, groups, items):
    """Twarde bramki budowy. Każda kotwica ZMIERZONA (brief §7), nie założona."""
    bad = []
    core = [r for r in records if r["_layer"] == "core"]
    cirrus = [r for r in records if r["_layer"] == "cirrus"]

    ctb = _find(records, "CTB1")
    if not ctb or abs(ctb["a"] - 34.0) > 0.5 or ctb["t"] != "SNR":
        bad.append("CTB1 nieobecny albo o innym rozmiarze/typie -> kanon Greena z pola Names padl")

    # DWA TORY EPOKOWE, każdy z własną kotwicą: Sh2 = B1900, LBN/LDN = B1950. Mierzymy na PULI,
    # nie na rekordach: para scalona nie ma już dwóch pozycji, a para sklejona po KANONIE
    # (Sh2-184 -> NGC281) scaliłaby się nawet przy pozycji przesuniętej o stopień — więc jako
    # falsyfikator epoki byłaby ślepa. Dlatego kotwicą jest para łączona wyłącznie POZYCYJNIE.
    # klucz po formie kanonicznej — OpenNGC zeznaje `IC0410`, nie `IC410`
    by_ident = {(catalog_canon(o.ident) or o.ident): o for o in items}
    for a, b, tol, tor in (("Sh2-236", "IC410", 5.0, "B1900 (Sh2)"),
                           ("LBN654", "IC1805", 25.0, "B1950 (LBN/LDN)")):
        oa, ob = by_ident.get(a), by_ident.get(b)
        if oa is None or ob is None:
            bad.append(f"kotwica epoki {tor}: brak {a} albo {b} w puli")
        elif separation(oa, ob) * 60 > tol:
            bad.append(f"kotwica epoki {tor}: {a} i {b} dzieli {separation(oa, ob) * 60:.1f}' "
                       f"(prog {tol}') -> wzieta surowa kolumna zamiast J2000/ICRS")

    veil = _find(records, "NGC6960")
    if not veil or "G074.0-08.5" not in (veil.get("n") or []):
        bad.append("NGC6960 bez G074.0-08.5 w aliasach -> tolerancja pozycji za ciasna")

    if _find(records, "IC1396") is None or _find(records, "Sh2-131") is None:
        bad.append("IC1396 i Sh2-131 nie sa DWOMA rekordami -> bramka proporcji zdjeta")

    seen = {}
    for r in records + curated:
        if r["c"] in seen:
            bad.append(f"kanon {r['c']} wystepuje dwa razy (suma plikow)")
        seen[r["c"]] = r
    for r in records:
        for a in r.get("n", ()):
            c = catalog_canon(a)
            if c and xref(c) in seen and xref(c) != r["c"]:
                bad.append(f"alias {a} rekordu {r['c']} wskazuje na kanon innego rekordu")

    for r in records + curated:
        if not (0 <= r["r"] < 360) or not (-90 <= r["d"] <= 90) or r["a"] <= 0:
            bad.append(f"rekord {r['c']} ma pozycje/rozmiar poza zakresem")

    if not 1400 <= len(core) <= 1800:
        bad.append(f"rdzen ma {len(core)} rekordow, spodziewane 1400-1800")
    if not 1800 <= len(cirrus) <= 2300:
        bad.append(f"cirrus ma {len(cirrus)} rekordow, spodziewane 1800-2300")

    wielo = [sorted(canon_of(o) for o in g) for g in groups
             if len({o.src for o in g}) < len(g) and len(g) > 1]
    return bad, wielo


def check_coverage(records, curated, path):
    """MIĘKKI falsyfikator: ile kanonow archiwum trafia w asset. Lista jest wlasnoscia ARCHIWUM,
    nie skryptu — repo jest publiczne, wiec sciezka do bazy nie ma tu prawa siedziec (§0)."""
    with open(path, encoding="utf-8") as fh:
        want = [x.strip() for x in fh if x.strip() and not x.startswith("#")]
    idx = set()
    for r in records + curated:
        idx.add(r["c"])
        idx.update(xref(catalog_canon(a)) for a in r.get("n", ()) if catalog_canon(a))
    hit = [c for c in want if c in idx]
    return hit, [c for c in want if c not in idx]


# ──────────────────────────────────────────────────────────────── zapis

def dump(path, meta, records):
    """Jeden rekord = jedna linia (czytelny diff podmiany katalogu), plik zostaje legalnym JSON-em.
    Sortowanie po kanonie => dwa przebiegi z tego samego materialu daja BAJTOWO ten sam plik."""
    body = ",\n".join(json.dumps({k: v for k, v in r.items() if k != "_layer"},
                                 ensure_ascii=False, separators=(",", ":"))
                      for r in sorted(records, key=lambda x: x["c"]))
    text = ('{"_meta":' + json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True)
            + ',\n"targets":[\n' + body + "\n]}\n")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Buduj asset katalogu celow planera (T2).")
    ap.add_argument("--cache", help="katalog na surowe pobrania (powtarzalnosc)")
    ap.add_argument("--offline", action="store_true", help="zero sieci; wymaga pelnego --cache")
    ap.add_argument("--out", default=OUT_DIR, help=f"katalog wyjsciowy (domyslnie {OUT_DIR})")
    ap.add_argument("--dry-run", action="store_true", help="policz i pokaz raport, nie zapisuj")
    ap.add_argument("--archive-canons", help="plik z kanonami archiwum (miekki falsyfikator)")
    args = ap.parse_args(argv)

    print("[1/4] zrodla")
    rows, src_meta = load_all(args.cache, args.offline)
    items = pool(rows)
    print(f"[2/4] pula: {len(items)} z {len(rows)} wierszy "
          f"(podloga {FLOOR_ARCMIN}' / ciemna {FLOOR_DARK_ARCMIN}', bez filtru magnitudo)")

    groups, stat = merge(items)
    records = [build_record(g) for g in groups]
    print(f"[3/4] scalanie: {len(items)} -> {len(records)} rekordow "
          f"(kanon {stat['canon']}, alias {stat['alias']}, pozycja {stat['position']})")

    curated_path = os.path.join(args.out, "curated.json")
    curated = []
    if os.path.exists(curated_path):
        with open(curated_path, encoding="utf-8") as fh:
            curated = json.load(fh)["targets"]
        print(f"       curated.json: {len(curated)} wpisow (plik czlowieka - tylko walidowany)")

    bad, wielo = falsifiers(records, curated, groups, items)
    if wielo:
        print(f"       RAPORT: {len(wielo)} grup ma >1 rekord z tego samego katalogu "
              f"(domkniecie tranzytywne), np. {wielo[0]}")
    if args.archive_canons:
        hit, miss = check_coverage(records, curated, args.archive_canons)
        print(f"       pokrycie archiwum: {len(hit)}/{len(hit) + len(miss)}; nietrafione: {miss}")
    if bad:
        for b in bad:
            print(f"  FALSYFIKATOR: {b}")
        raise SystemExit(f"BLAD: {len(bad)} twardych falsyfikatorow -> asset NIE zapisany")

    core = [r for r in records if r["_layer"] == "core"]
    cirrus = [r for r in records if r["_layer"] == "cirrus"]
    meta = {"built": date.today().isoformat(), "sources": src_meta,
            "floor_arcmin": FLOOR_ARCMIN, "floor_dark_arcmin": FLOOR_DARK_ARCMIN,
            "merge": {"tol_factor_major": MERGE_TOL_FACTOR, "ratio_min": MERGE_RATIO_MIN,
                      "keys": ["canon", "alias", "position"], "merged": stat},
            "notes": ["pozycje J2000 w stopniach; epoki zrodel znormalizowane po stronie VizieR",
                      "rozmiar LDN = kolo rownowazne z pola Area (katalog nie podaje srednicy)",
                      "typ zrodel bez wlasnej typologii przypisany z definicji katalogu",
                      "dane pochodne z OpenNGC (CC-BY-SA-4.0) — patrz PROVENANCE.md"],
            "license": "CC-BY-SA-4.0 (dane); kod repozytorium: MIT"}

    if args.dry_run:
        print(f"[4/4] --dry-run: rdzen {len(core)}, cirrus {len(cirrus)} - nic nie zapisano")
        return 0
    os.makedirs(args.out, exist_ok=True)
    n1 = dump(os.path.join(args.out, "targets_core.json"), dict(meta, layer="core"), core)
    n2 = dump(os.path.join(args.out, "targets_cirrus.json"), dict(meta, layer="cirrus"), cirrus)
    print(f"[4/4] zapisano: targets_core.json {len(core)} rek. / {n1 // 1024} KB, "
          f"targets_cirrus.json {len(cirrus)} rek. / {n2 // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
