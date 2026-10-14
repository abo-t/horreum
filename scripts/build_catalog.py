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
# Taksonomia typów ORAZ kontrakt rekordu mają JEDNEGO właściciela — `horreum.targets` (T3 §3,
# D-OW-1/E′). Skrypt je IMPORTUJE: gdyby trzymał kopię, producent i konsument assetu mogliby się
# rozjechać po cichu - plik przechodziłby budowę i padał przy wczytaniu. Tak samo status
# katalogowy rekordu (pole `s`, K-3): jego słownik zna czytelnik assetu.
from horreum.targets import (CATALOG_STATUSES, DARK_TYPES, GALAXY_TYPES,  # noqa: E402
                            NEBULA_TYPES, TARGET_FIELDS, target_fields_present)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_ROOT, "horreum", "data")
# PLIK CZŁOWIEKA — ścieżka JAWNA, świadomie NIE pochodna od `--out` (D-OW-1/E′). Gdy siedział
# w katalogu wyjściowym, każdy przebieg z innym `--out` czytał go jako nieobecny i po cichu
# wyłączał bramkę unikalności kanonów W SUMIE PLIKÓW — a to jedyna kontrola kolizji między
# rekordami ręcznymi a generowanymi. Brak pliku jest odtąd BŁĘDEM, nie pustą listą.
OWN_PATH = os.path.join(_ROOT, "horreum", "resolve", "data", "objects_own.json")
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
#
# Mgławice planetarne Le Du 2022 (K-3) wchodzą do grupy WYŁĄCZNIE jawną decyzją (`PN_DECYZJE`),
# więc szczebel rozstrzyga tylko w grupach z decyzją „merge”. PN potwierdzona widmem (`pn`) stoi nad
# Sharplessem: typ Sh2/LBN/vdB to typ Z DEFINICJI katalogu, a tu jest klasyfikacja zmierzona.
# Kanon i tak zostaje formą gramatyki - PN z nazwą HASH znaną gramatyce bierze ją za oznaczenie
# (`parse_pn`, jak nazwany Green). Kandydatka i mimika są na końcu: nie wygrywają z niczym.
PRIO = {"ngc": 0, "green_named": 1, "pn": 2, "sh2": 3, "green": 4, "vdb": 5, "lbn": 6, "ldn": 7,
        "pn_cand": 8, "pn_mimic": 9}

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
    status: str | None = None                      # status katalogowy rekordu (K-3, `s`)
    pn_name: str | None = None                     # nazwa z tabeli Le Du - klucz `PN_DECYZJE`


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
    """Wiersze tabeli `asu-tsv`: komentarze `#`, potem nagłówek, jednostki i linia myślników.
    Dane zaczynają się PO linii myślników, nie od stałego indeksu: tabela bez jednostek (VII/192,
    same nazwy) ma linię jednostek z samych tabulatorów, filtr pustych linii ją zdejmuje, a stały
    indeks połykał wtedy pierwszy wiersz danych."""
    lines = [l for l in (x.rstrip("\n") for x in io.StringIO(text)) if l.strip() and not l.startswith("#")]
    hdr = lines[0].split("\t")
    start = next(i for i, l in enumerate(lines) if i and set(l) <= set("-\t ")) + 1
    return [{h: v.strip() for h, v in zip(hdr, l.split("\t"))} for l in lines[start:]
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


# ──────────────────────────────────────── K-3: mgławice planetarne Le Du+ 2022 (J/A+A/666/A152)
# Trzy tabele publikacji, TRZY STATUSY katalogowe (pole `s` rekordu, `targets.CATALOG_STATUSES`):
# table1 = PN potwierdzone widmem (HASH T/L/P), table2 = kandydatki bez widma, table3 = MIMIKI
# (zgłoszone jako PN, okazały się czymś innym). Status jest OSOBNO od typu, bo typ steruje kanałami
# planera, a „PN” na kandydatce byłoby twierdzeniem, którego źródło nie stawia.
PN_STATUS = {"pn": "confirmed", "pn_cand": "candidate", "pn_mimic": "mimic"}
# ZAKRES - JEDNO miejsce filtra po tabeli źródła (decyzja `Q7`: 132 obiekty ≥3′ ze wszystkich trzech
# tabel; zawężenie - np. do samych potwierdzonych - to wykreślenie kluczy stąd).
PN_ZAKRES = ("pn", "pn_cand", "pn_mimic")
# TYP MIMIKI Z PUBLIKACJI: kolumna `Status` table3 niesie typ obiektu wg HASH (skróty SIMBAD:
# `HII` obszar HII, `SNR` pozostałość, `SR?` kandydatka na pozostałość, `iISM` zjonizowana materia
# międzygwiazdowa, `Em*` gwiazda emisyjna, `ooun` obiekt nieznanej natury, `cir` kod HASH bez
# odpowiednika w taksonomii). Klasa planera = ten typ, a gdzie taksonomia go nie zna - `Neb`
# (mgławica bez klasy): kanały wąskopasmowe, bez udawania obszaru HII. Kod spoza tabeli przy obiekcie
# nad podłogą = twardy błąd budowy - nowe dane nie wejdą z typem zgadniętym.
PN_MIMIKA_TYP = {"HII": "HII", "SNR": "SNR", "SR?": "SNR", "iISM": "EmN", "Em*": "Neb",
                 "ooun": "Neb", "cir": "Neb"}
# JAWNE DECYZJE SCALENIA K-3: wiersz Le Du nie skleja się z niczym bez wpisu tutaj - kolizja wg
# KTÓREGOKOLWIEK klucza (kanon, alias, pozycja) bez decyzji jest twardym falsyfikatorem budowy, a wpis,
# którego żadna kolizja nie użyła, też (dane się zmieniły - decyzję trzeba obejrzeć od nowa).
# Klucz: (nazwa z tabeli Le Du, kanon drugiego wiersza). Wartość: (decyzja, dowód tożsamości).
PN_DECYZJE = {
    ("StDr 17", "Sh2-123"): (
        "merge", "HASH (kolumna HName table1) nazywa StDr 17 `Sh2-123`; środki 4,5' przy osiach "
                 "15'x13' i 13' - jeden obiekt, typ PN z widma zastępuje typ Sh2 z definicji katalogu"),
    ("StDr 17", "LBN414"): (
        "no-merge", "zbieżność wyłącznie pozycyjna (4,1'), bez nazwy wspólnej w żadnym źródle; "
                    "Sh2-123 i LBN414 są w assecie osobnymi rekordami, a scalenie skleiłoby je "
                    "tranzytywnie przez StDr 17"),
    ("MoMi 2", "LBN340"): (
        "no-merge", "mimika o nieznanej naturze (HASH `ooun`), zbieżność wyłącznie pozycyjna (0,9') "
                    "bez nazwy wspólnej w żadnym źródle"),
    ("Ou 4", "LBN453"): (
        "no-merge", "zbieżność wyłącznie pozycyjna (29,2' przy osi LBN453 100'); LBN453 należy do "
                    "grupy Sh2-129, a Ou 4 leży w jej środku (1,6') jako osobny cel - bramka "
                    "proporcji 69'/140' rozdziela je z Sh2-129, scalenie przez LBN453 zrobiłoby "
                    "z Ou 4 alias Sh2-129"),
}
_PN_LICZBA = re.compile(r"\d+(?:\.\d*)?")


def parse_pn(text, key):
    """Wiersze jednej tabeli Le Du. `Size` w minutach łuku (ReadMe: `Size ... min`), forma `9`,
    `15 x 13`, `12.0 x 7.`, `9.5 x 12` (mniejsza oś bywa pierwsza) - osie z liczb, większa = `a`.

    OZNACZENIE: nazwa HASH (`HName`, tylko table1), gdy zna ją gramatyka katalogowa (`Sh2-123` przy
    StDr 17) - kanon zostaje formą gramatyki, jak u nazwanego Greena; inaczej nazwa z tabeli
    (`StDr 61`, poza gramatyką z definicji). Nazwy do szukania (`common`, verbatim): nazwa z tabeli,
    nazwa HASH i `PN G…` - oznaczenie PNG WYŁĄCZNIE z przedrostkiem `PN`, bo gołe `G…` gramatyka
    czyta jako pozostałość Greena (`test_catalog`, pułapka K-1)."""
    out = []
    for r in _vizier_rows(text):
        name = r["Name"]
        ra, dec = _fnum(r["_RAJ2000"]), _fnum(r["_DEJ2000"])
        osie = sorted(float(x) for x in _PN_LICZBA.findall(r["Size"] or ""))
        if not name or ra is None or dec is None or not osie:
            continue
        if key == "pn_mimic":
            typ = PN_MIMIKA_TYP.get(r["Status"])
            if typ is None:
                if osie[-1] >= FLOOR_ARCMIN:
                    raise SystemExit(f"BLAD: mimika {name} ma typ HASH {r['Status']!r} spoza "
                                     f"PN_MIMIKA_TYP -> dopisz decyzje typu")
                typ = "?"                              # pod podłogą - i tak nie wejdzie do puli
        else:
            typ = "PN"
        hname = (r.get("HName") or "").strip()
        named = hname if hname and catalog_canon(hname, split=False) else None
        common = [n for n in (name if named else None, hname if not named else None,
                              f"PN G{r['PNG']}" if r["PNG"] else None) if n]
        out.append(Row(ident=named or name, src=key, typ=typ, ra=ra, dec=dec, major=osie[-1],
                       minor=osie[0] if len(osie) > 1 else None, names=common, common=common,
                       status=PN_STATUS[key], pn_name=name))
    return out


# ──────────────────────────────────────── K-2: Arp (VII/192) - WYŁĄCZNIE aliasy istniejących celów
# `Size` atlasu Arpa to bok ZDJĘCIA, nie średnica galaktyki (ReadMe VII/192 „Note on Size”), więc
# Arp nie wnosi rekordów, pozycji ani rozmiarów: numer Arpa staje się nazwą celu, który już jest.
# Arp wielu składników dostaje alias na PIERWSZYM składniku z nazwy (decyzja `Q7`: Arp 244 → NGC4038).
_ARP_PIERWSZY = re.compile(r"^(NGC|IC|UGC|PGC|MESSIER)\s*(\d+)\s*([A-Z])?$")
_ARP_ESO = re.compile(r"^ESO\s*(\d{1,3})\s*-\s*[A-Z]{0,2}\s*(\d{1,3})$")
_ARP_NUMER = re.compile(r"^(\d+)\s*([A-Z])?$")
_ARP_LITERA = re.compile(r"^([A-Z])$")
_ARP_DOPISEK = re.compile(r"\s+(GROUP|FIELD)$")
# Nazwy potoczne atlasu (pole `Name` ucięte do 15 znaków) - wyłącznie tożsamości pewne z literatury:
# Kwintet Stephana = HCG 92 (Hickson 1982), Holmberg II = UGC 4305. Reszta nazw potocznych zostaje
# bez celu i trafia do licznika pominiętych, zamiast zgadywania składnika.
ARP_NAZWY_POTOCZNE = {"STEPHAN'S QUINT": "HCG 92", "HOLMBERG II": "UGC 4305"}


def _arp_skladnik(kat, num, litera):
    """Składnik z nazwy Arpa → forma kanonu assetu. Bez litery - forma gramatyki (`NGC 0772` →
    `NGC772`, `MESSIER 65` → `M65`). Z literą gramatyka składnika nie zna (`resolve.catalog`: NGC/IC
    to same cyfry), a OpenNGC pisze go z numerem na czterech cyfrach (`NGC6365A`, `IC0359A`) i taki
    jest kanon rekordu - więc tę formę składamy jawnie."""
    if litera is None:
        return catalog_canon(f"{'M' if kat == 'MESSIER' else kat} {num}")
    if kat in ("NGC", "IC"):
        return f"{kat}{int(num):04d}{litera}"
    return f"{kat}{int(num)}{litera}"


def parse_arp_name(name):
    """Pole `Name` atlasu Arpa → krotka składników w formie kanonu assetu (kolejność z nazwy) albo
    pusta krotka, gdy nazwy nie da się rozwinąć bez zgadywania. Gramatyka zapisu:

      * pierwszy człon: pełne oznaczenie (`NGC 6621`, `IC 0018`, `UGC 00212`, `MESSIER 65`,
        `NGC 6365A`, `ESO 547-G002`), dopiski `Group`/`Field` i nawias (`NGC 7757(56?)` -
        niepewny sąsiad) odpadają;
      * człony po `+` albo `&`: sama liczba to ten sam katalog z cyframi uzupełnionymi z przodu
        z poprzedniego numeru (`NGC 4615+13+14` → 4613, 4614; `NGC 0772 + 770` → 770), sama litera
        to składnik poprzedniego numeru (`NGC 6365A + B` → NGC6365B), pełne oznaczenie zmienia
        bazę (`NGC 5829+IC4526`), `comp` (towarzysz bez nazwy) odpada;
      * ESO: numer w polu ESO (`ESO 547-G002&3` → ESO547-002, ESO547-003).

    Nazwa potoczna - wyłącznie z `ARP_NAZWY_POTOCZNE`. Wszystko inne (`MCG…`, `CGCG…`, `VV…`,
    `IC 029  8`) → `()`."""
    s = re.sub(r"\s+", " ", (name or "").strip().upper())
    if s in ARP_NAZWY_POTOCZNE:
        c = catalog_canon(ARP_NAZWY_POTOCZNE[s])
        return (c,) if c else ()
    s = _ARP_DOPISEK.sub("", re.sub(r"\(.*?\)", "", s)).strip()
    czlony = [c.strip() for c in re.split(r"[+&]", s)]
    if not czlony or not czlony[0]:
        return ()
    m = _ARP_ESO.match(czlony[0])
    if m:
        pole, num = m.group(1), m.group(2)
        out = [catalog_canon(f"ESO {pole}-{num}")]
        for c in czlony[1:]:
            mn = re.fullmatch(r"\d{1,3}", c)
            if not mn:
                return ()
            out.append(catalog_canon(f"ESO {pole}-{c}"))
        return tuple(out) if all(out) else ()
    m = _ARP_PIERWSZY.match(czlony[0])
    if not m:
        return ()
    kat, baza, litera = m.group(1), m.group(2), m.group(3)
    out = [_arp_skladnik(kat, baza, litera)]
    for c in czlony[1:]:
        if c == "COMP":
            continue
        if (m := _ARP_PIERWSZY.match(c)) is not None:
            kat, baza, litera = m.group(1), m.group(2), m.group(3)
            out.append(_arp_skladnik(kat, baza, litera))
        elif (m := _ARP_NUMER.match(c)) is not None:
            num = m.group(1)
            if len(num) < len(baza):
                num = baza[:len(baza) - len(num)] + num
            out.append(_arp_skladnik(kat, num, m.group(2)))
        elif (m := _ARP_LITERA.match(c)) is not None:
            out.append(_arp_skladnik(kat, baza, m.group(1)))
        else:
            return ()
    return tuple(out) if all(out) else ()


def parse_arp(text):
    """Wiersze `VII/192/arpord` → lista `(numer Arpa, Name)`."""
    return [(int(r["Arp"]), r["Name"]) for r in _vizier_rows(text) if r["Arp"].strip()]


def attach_arp_aliases(records, arp):
    """Alias `Arp N` na rekordzie PIERWSZEGO składnika nazwy - wyłącznie rekordy istniejące (zero
    nowych, zero pozycji i rozmiarów). Rekord szukany po kanonie i po aliasach katalogowych (forma
    po `xref`), tak jak pokrycie planera; składnik bez rekordu, rekord dwuznaczny i nazwa bez
    rozwinięcia są POMINIĘTE z licznikiem (raport budowy, `PROVENANCE.md`). Zwraca liczniki."""
    idx = {}
    for r in records:
        idx.setdefault(r["c"], set()).add(id(r))
        # Kanon także w formie po `xref` - ten sam klucz, którym szukany jest składnik (`M65` →
        # `NGC3623`); bez tego rekord o kanonie-kluczu pary chybiałby lookup po celu pary.
        idx.setdefault(xref(r["c"]), set()).add(id(r))
        for a in r.get("n", ()):
            c = catalog_canon(a)
            if c:
                idx.setdefault(xref(c), set()).add(id(r))
    by_id = {id(r): r for r in records}
    stat = {"rows": len(arp), "attached": 0, "no_target": 0, "unparsed": 0, "ambiguous": 0}
    for numer, name in arp:
        skladniki = parse_arp_name(name)
        if not skladniki:
            stat["unparsed"] += 1
            continue
        pierwszy = skladniki[0]
        trafione = idx.get(xref(pierwszy) if catalog_canon(pierwszy) == pierwszy else pierwszy,
                           set())
        if not trafione:
            stat["no_target"] += 1
            continue
        if len(trafione) > 1:
            stat["ambiguous"] += 1
            continue
        rec = by_id[next(iter(trafione))]
        rec["n"] = sorted(set(rec.get("n", ())) | {f"Arp {numer}"})
        stat["attached"] += 1
    return stat


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
    # K-2: źródło ALIASÓW, nie rekordów - `load_all` oddaje je osobno (`attach_arp_aliases`).
    ("arp", "Arp Atlas of Peculiar Galaxies (VII/192, arpord)",
     _VIZIER.format(cat="VII/192/arpord", cols="Arp,Name"), "arp.tsv", 330, "CDS/VizieR"),
] + [s for s in (
    # K-3: trzy tabele Le Du+ 2022, każda z własnym statusem (`PN_STATUS`); zakres = `PN_ZAKRES`.
    ("pn", "PN potwierdzone Le Du+ 2022 (J/A+A/666/A152, table1)",
     _VIZIER.format(cat="J/A+A/666/A152/table1", cols="Name,HName,PNG,Size,Status")
     + "&-out.add=_RAJ2000,_DEJ2000", "pn_ledu_t1.tsv", 150, "CDS/VizieR"),
    ("pn_cand", "Kandydatki PN Le Du+ 2022 (J/A+A/666/A152, table2)",
     _VIZIER.format(cat="J/A+A/666/A152/table2", cols="Name,PNG,Size,Status")
     + "&-out.add=_RAJ2000,_DEJ2000", "pn_ledu_t2.tsv", 400, "CDS/VizieR"),
    ("pn_mimic", "Mimiki PN Le Du+ 2022 (J/A+A/666/A152, table3)",
     _VIZIER.format(cat="J/A+A/666/A152/table3", cols="Name,PNG,Size,Status")
     + "&-out.add=_RAJ2000,_DEJ2000", "pn_ledu_t3.tsv", 60, "CDS/VizieR"),
) if s[0] in PN_ZAKRES]


def load_all(cache_dir, offline):
    """Pobierz i sparsuj wszystkie źródła. Widełki PER ŹRÓDŁO — urwane pobranie musi paść tutaj,
    a nie przejść niezauważone w sumie. Zwraca `(wiersze, meta, arp)` - Arp jest źródłem aliasów,
    nie wierszy puli (K-2)."""
    rows, meta, arp = [], [], []
    for key, title, url, cache_name, min_rows, lic in SOURCES:
        text = fetch(url, cache_dir, cache_name, offline)
        if key == "ngc":
            got, _ = parse_openngc(text, key)
        elif key == "ngc_add":
            got, _ = parse_openngc(text, key)
        elif key == "arp":
            got = parse_arp(text)
        elif key in PN_STATUS:
            got = parse_pn(text, key)
        else:
            got = {"sh2": parse_sh2, "lbn": parse_lbn, "ldn": parse_ldn,
                   "vdb": parse_vdb, "green": parse_green}[key](text)
        if len(got) < min_rows:
            raise SystemExit(f"BLAD: zrodlo {key} oddalo {len(got)} wierszy, "
                             f"minimum {min_rows} -> pobranie urwane albo katalog sie zmienil")
        if key == "arp":
            arp = got
        else:
            rows += got
        meta.append({"key": key, "title": title, "url": url, "rows": len(got), "license": lic})
        print(f"  {key:<8} {len(got):>6} wierszy" + ("" if key == "arp" else " z pozycja i rozmiarem"))
    return rows, meta, arp


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


def _pn(o):
    """Wiersz z tabel Le Du (K-3) - scala się wyłącznie decyzją `PN_DECYZJE`."""
    return o.src in PN_STATUS


def merge(items):
    """Union-find po trzech kluczach (nagłówek modułu). Zwraca `(grupy, licznik scaleń, raport PN)`.

    Domknięcie TRANZYTYWNE jest zamierzone: `NGC1499 + Sh2-220 + LBN752 + LBN756` to jeden cel,
    choć dwa ostatnie są z tego samego katalogu i same nigdy by się nie połączyły. Grupy
    wielokrotne z jednego katalogu RAPORTUJEMY - mają być widziane, nie ciche.

    WIERSZ LE DU (K-3) NIE SKLEJA SIĘ AUTOMATEM: każde połączenie, które któryś klucz chciałby
    zrobić z jego udziałem, przechodzi przez `PN_DECYZJE` - „merge” łączy, „no-merge” zostawia dwa
    rekordy, brak decyzji trafia do raportu (`undecided`) i jest twardym falsyfikatorem, tak samo
    jak decyzja, której żadna kolizja nie użyła (`unused`). Union-find wybiera JEDNEGO zwycięzcę
    i JEDEN typ grupy, więc ciche sklejenie zgubiłoby klasę obiektu. Trzy tabele Le Du to jeden
    katalog: między sobą nie scalają się pozycją (jak wiersze jednego źródła)."""
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    stat = {"canon": 0, "alias": 0, "position": 0}
    uzyte, nierozstrzygniete = set(), set()

    def union(i, j, key):
        oi, oj = items[i], items[j]
        if _pn(oi) or _pn(oj):
            pn, inny = (oi, oj) if _pn(oi) else (oj, oi)
            klucz = (pn.pn_name, inny.pn_name if _pn(inny) else canon_of(inny))
            decyzja = PN_DECYZJE.get(klucz)
            if decyzja is None:
                nierozstrzygniete.add((*klucz, key))
                return
            uzyte.add(klucz)
            if decyzja[0] != "merge":
                return
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
                if a.src == b.src or (_pn(a) and _pn(b)):
                    continue                       # w jednym katalogu zagnieżdżenie to STRUKTURA
                lo, hi = sorted((a.major, b.major))
                if lo / hi < MERGE_RATIO_MIN:
                    continue                       # BRAMKA PROPORCJI
                if separation(a, b) * 60 <= max(2.0, MERGE_TOL_FACTOR * hi):
                    union(i, j, "position")

    groups = {}
    for i, o in enumerate(items):
        groups.setdefault(find(i), []).append(o)
    pn = {"merge": sorted(k for k in uzyte if PN_DECYZJE[k][0] == "merge"),
          "no_merge": sorted(k for k in uzyte if PN_DECYZJE[k][0] != "merge"),
          "undecided": sorted(nierozstrzygniete), "unused": sorted(set(PN_DECYZJE) - uzyte)}
    return list(groups.values()), stat, pn


def build_record(group):
    """Rekord assetu z grupy. Zwycięzca wg PRIO (remis -> większa oś); przegrani NIE giną —
    ich kanony wchodzą do aliasów ZAWSZE (to klucze tożsamości, więc filtr gramatyki ich nie
    dotyczy: `catalog_canon('G074.0-08.5')` jest z definicji None). Status katalogowy (`s`, K-3)
    idzie za zwycięzcą - jak typ, którego dotyczy."""
    win = sorted(group, key=lambda o: (PRIO[o.src], -o.major))[0]
    own = canon_of(win)
    # Oznaczenie ŹRÓDŁOWE wchodzi obok kanonu — w formie SPRZED `xref`: `Sh2-184` kanonizuje się
    # na `NGC281`, więc bez tego przegrany zniknąłby bez śladu i użytkownik nie znalazłby celu pod
    # nazwą, której realnie używa. Bierzemy `catalog_canon`, nie surowy string, żeby nie wsypać
    # do aliasów zapisu z zerami wiodącymi (`IC0410` obok `IC410`).
    alias = {canon_of(o) for o in group} | {catalog_canon(o.ident) or o.ident for o in group}
    for o in group:
        # Ta sama reguła dla oznaczeń z `names` (Identifiers OpenNGC, numer Messiera z kolumny M):
        # forma SPRZED `xref` i forma PO nim. Sama forma po `xref` zjadała Messiera - `M27` ma parę,
        # więc zamieniał się w kanon rekordu i wypadał jako „własny” (`discard` niżej). Przy pełnej
        # tabeli Messiera (D-1013-1) przebudowa gubiła wszystkie numery Messiera z pola `n`.
        for a in o.names:
            c = catalog_canon(a)
            if c:
                alias.update((c, xref(c)))
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
    if win.status:
        rec["s"] = win.status
    rec["_layer"] = "cirrus" if win.src in CIRRUS_SRC else "core"
    return rec


def _licz_statusy(records):
    """Liczność rekordów per status katalogowy (raport budowy, K-3)."""
    out = {}
    for r in records:
        if "s" in r:
            out[r["s"]] = out.get(r["s"], 0) + 1
    return out


# ──────────────────────────────────────────────────────────────── falsyfikatory

def _find(records, canon):
    return next((r for r in records if r["c"] == canon), None)


def falsifiers(records, curated, groups, items, pn=None):
    """Twarde bramki budowy. Każda kotwica ZMIERZONA (brief §7), nie założona. `pn` = raport
    scalania wierszy Le Du z `merge` (K-3): kolizja bez decyzji i decyzja bez kolizji padają tu."""
    bad = []
    for kto, inny, klucz in (pn or {}).get("undecided", ()):
        bad.append(f"PN {kto} koliduje z {inny} (klucz {klucz}) bez decyzji w PN_DECYZJE")
    for kto, inny in (pn or {}).get("unused", ()):
        bad.append(f"decyzja PN_DECYZJE ({kto}, {inny}) bez kolizji -> dane sie zmienily")
    for r in records:
        if "s" in r and r["s"] not in CATALOG_STATUSES:
            bad.append(f"rekord {r['c']} ma status {r['s']!r} spoza CATALOG_STATUSES")
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

    # Pozycja i rozmiar dotyczą REKORDÓW-CELÓW. Plik człowieka niesie też rekordy-NAZWY (sam kanon
    # z nazwami potocznymi — obiekt, którego planer nie planuje); sięganie po `r["r"]` wprost dawało
    # na nich `KeyError`, czyli crash zamiast raportu. Rekord NIEPEŁNY nie jest trzecią klasą — to
    # błąd pliku i ma się zgłosić jako falsyfikator, a nie przejść bokiem.
    for r in records + curated:
        have = target_fields_present(r)
        if have == 0:
            continue                                     # rekord-NAZWA: nie jest celem
        if have != len(TARGET_FIELDS):
            miss = sorted(k for k in TARGET_FIELDS if r.get(k) is None)
            bad.append(f"rekord {r['c']} ma czesc pol celu, brak {miss} -> ani cel, ani nazwa")
            continue
        if not (0 <= r["r"] < 360) or not (-90 <= r["d"] <= 90) or r["a"] <= 0:
            bad.append(f"rekord {r['c']} ma pozycje/rozmiar poza zakresem")

    if not 1400 <= len(core) <= 1800:
        bad.append(f"rdzen ma {len(core)} rekordow, spodziewane 1400-1800")
    if not 1800 <= len(cirrus) <= 2300:
        bad.append(f"cirrus ma {len(cirrus)} rekordow, spodziewane 1800-2300")

    wielo = [sorted(canon_of(o) for o in g) for g in groups
             if len({o.src for o in g}) < len(g) and len(g) > 1]
    return bad, wielo


def read_own_records(path=OWN_PATH):
    """Rekordy pliku CZŁOWIEKA albo twarde wyjście. Wydzielone z `main`, żeby bramka §4/5 dała się
    uruchomić baterią: reguła „brak pliku jest błędem, nie pustą listą" siedząca wyłącznie w pętli
    głównej skryptu sieciowego jest regułą, której nikt nigdy nie sprawdzi (EXPECT)."""
    if not os.path.exists(path):
        raise SystemExit(f"BLAD: brak pliku czlowieka {path} -> kontrola kolizji kanonow "
                         f"bylaby liczona na samych rekordach generowanych")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["targets"]


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
    rows, src_meta, arp = load_all(args.cache, args.offline)
    items = pool(rows)
    print(f"[2/4] pula: {len(items)} z {len(rows)} wierszy "
          f"(podloga {FLOOR_ARCMIN}' / ciemna {FLOOR_DARK_ARCMIN}', bez filtru magnitudo)")

    groups, stat, pn = merge(items)
    records = [build_record(g) for g in groups]
    print(f"[3/4] scalanie: {len(items)} -> {len(records)} rekordow "
          f"(kanon {stat['canon']}, alias {stat['alias']}, pozycja {stat['position']})")
    print(f"       PN Le Du: decyzje merge {pn['merge']}, no-merge {pn['no_merge']}; "
          f"statusy {dict(sorted(_licz_statusy(records).items()))}")
    arp_stat = attach_arp_aliases(records, arp) if arp else None
    if arp_stat:
        src_meta = [dict(s, aliases=arp_stat) if s["key"] == "arp" else s for s in src_meta]
        print(f"       Arp (VII/192): {arp_stat['attached']} aliasow na istniejacych celach; "
              f"pominiete: bez celu {arp_stat['no_target']}, bez rozwiniecia nazwy "
              f"{arp_stat['unparsed']}, dwuznaczne {arp_stat['ambiguous']}")

    # Plik człowieka jest OBOWIĄZKOWY (D-OW-1/E′): to on wnosi rekordy, których żadne źródło sieciowe
    # nie zna, i to na sumie z nim liczy się kontrola kolizji kanonów. Cicha degradacja do pustej
    # listy zdejmowała tę kontrolę bez jednego słowa w raporcie — EXPECT, nie `curated=[]`.
    curated = read_own_records()
    _cele = sum(1 for r in curated if target_fields_present(r) == len(TARGET_FIELDS))
    print(f"       objects_own.json: {len(curated)} wpisow ({_cele} celow, "
          f"{len(curated) - _cele} nazw) - plik czlowieka, tylko walidowany")

    bad, wielo = falsifiers(records, curated, groups, items, pn)
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
                      "keys": ["canon", "alias", "position"], "merged": stat,
                      "pn_decisions": {f"{a} / {b}": {"decision": PN_DECYZJE[(a, b)][0],
                                                      "evidence": PN_DECYZJE[(a, b)][1]}
                                       for a, b in pn["merge"] + pn["no_merge"]}},
            "notes": ["pozycje J2000 w stopniach; epoki zrodel znormalizowane po stronie VizieR",
                      "rozmiar LDN = kolo rownowazne z pola Area (katalog nie podaje srednicy)",
                      "typ zrodel bez wlasnej typologii przypisany z definicji katalogu",
                      "status s (confirmed/candidate/mimic) tylko przy PN Le Du+ 2022 - typ t "
                      "to klasa obiektu, status to twierdzenie zrodla",
                      "scalenie PN z decyzji (merge.pn_decisions): zwyciezca PN wnosi typ, pozycje "
                      "i rozmiar (Sh2-123: 15'x13' z Le Du zamiast 13' Sharplessa), przegrany "
                      "zostaje w n",
                      "Arp (VII/192) wylacznie jako alias pierwszego skladnika nazwy",
                      "dane pochodne z OpenNGC (CC-BY-SA-4.0) - patrz PROVENANCE.md"],
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
