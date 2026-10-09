"""Zapytanie Znajdź - tekst z pola → stan zbioru `FramesView`. Qt-WOLNY: parser i rozwiązanie to czyste
funkcje nad DANYMI (`FindCatalog`), testowalne bez bazy i bez PySide6; jedyne zapytania robi
`catalog_from_db`, który te dane zbiera.

Znajdź nie ma własnego silnika zbioru (JEDEN-STAN-EKRANU): wynik `resolve` to składniki, które
`FramesView` już zna - stan facetów listwy, drzewo zaawansowane i `note_query`. Dlatego wszystko, co
zapytanie zawęziło, widać potem tam, gdzie widać każde zawężenie (listwa, pasek kryteriów, chipy).

Gramatyka (prefiksy w obu językach działają zawsze, bez względu na język UI - user wpisuje
to, co pamięta, a nie to, co akurat pokazuje menu):
  * `noc:`/`night:` - prefiks ISO (`2026`, `2026-08`, `2026-08-08`) po nocach archiwum;
  * `filtr:`/`filter:` - równość `norm_alnum` z filtrem (`l-pro` trafia `L-Pro`);
  * `teleskop:`/`telescope:` - równość `norm_alnum`, a gdy żadnej nie ma - prefiks;
  * `zestaw:`/`setup:`/`rig:` - etykieta `<teleskop>_<kamera>`, ta sama co folder zestawu
    w wydaniu (EN UI mówi na zestaw i „setup", i „rig" - działają oba);
  * `uwagi:`/`notes:` - tekst uwagi (przecinek jest tu treścią, nie separatorem: uwaga to proza);
  * słowa bez prefiksu - JEDNA fraza: obiekty przez szukajkę listwy (nazwa, alias, oznaczenie
    katalogowe), a gdy nie trafi żadnego obiektu - tekst uwag.
Wartość w cudzysłowie może mieć spacje. `filtr:Ha,OIII` i powtórzony prefiks = OR w obrębie osi,
różne prefiksy = AND. Prefiks albo wartość, których archiwum nie zna, idą do `unmatched` - ekran mówi
„nie znam: …", a rozpoznane części działają (zapytanie z literówką nie może dać pustego zbioru bez
słowa wyjaśnienia ani udawać, że literówki nie było).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product
from typing import NamedTuple

from horreum.gui import facet_model, i18n, queries
from horreum.repo import normalize_note
from horreum.resolve._text import norm_alnum
from horreum.resolve.catalog import catalog_canon

# Prefiks (bez wielkości liter) → oś zapytania. Oś to nazwa WEWNĘTRZNA, nie facet: `zestaw` i `uwagi`
# facetów listwy nie mają.
PRZEDROSTKI = {
    "noc": "night", "night": "night",
    "filtr": "filter", "filter": "filter",
    "teleskop": "telescope", "telescope": "telescope",
    "zestaw": "rig", "setup": "rig", "rig": "rig",
    "uwagi": "notes", "notes": "notes",
}
# Prefiksem jest wyłącznie słowo z samych liter przed dwukropkiem - `Sh2:131` albo `12:30` zostają
# słowami frazy, a nie „nieznanym prefiksem".
_PRZEDROSTEK_RE = re.compile(r"[^\W\d_]+")
_NOC_RE = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")
# Cudzysłów prosty i polskie „…” (oraz “…”) - user pisze tym, co ma na klawiaturze.
_CUDZYSLOWY = '"„“”'
# Nazwa osi na chipie terminu - te same słowa, którymi listwa podpisuje grupy facetów, a zestaw
# nazwą kolumny prostego zestawu kolumn. Parytet z katalogiem pinuje test.
_NAZWA_OSI = {"night": "facets.group.night", "filter": "facets.group.filter",
              "telescope": "facets.group.telescope", "rig": "find.col.rig",
              "object": "facets.group.object"}


class Term(NamedTuple):
    """Jedna wartość z prefiksem: oś, prefiks w brzmieniu usera (do zdania „nie znam"), wartość
    i numer tokenu, z którego przyszła - `filtr:Ha,OIII` to dwie wartości JEDNEGO wpisanego
    terminu, więc dostają jeden chip (`FindTerm`)."""
    axis: str
    prefix: str
    value: str
    token: int = 0


class FindTerm(NamedTuple):
    """Chip WPISANEGO terminu: etykieta („Noc: 2025-11") i klucze składników stanu, które ten
    termin postawił (format kluczy `FramesView.skladniki_stanu`). Jeden termin bywa wieloma
    składnikami - miesiąc to kilkanaście nocy, fraza kilka obiektów - a człowiek zdejmuje to,
    co wpisał, jednym „×", nie po jednej nocy."""
    label: str
    keys: tuple


@dataclass(frozen=True)
class FindQuery:
    """Wynik `parse`: wartości z prefiksami w kolejności wpisania, fraza ze słów bez prefiksu
    i tokeny z prefiksem, którego gramatyka nie zna."""
    terms: tuple = ()
    phrase: str | None = None
    unknown: tuple = ()


class Rig(NamedTuple):
    """Zestaw ze słownika `zestaw:` (`queries.find_rigs`)."""
    label: str
    telescope_id: int
    telescope_label: str
    camera_id: int
    camera: str


@dataclass(frozen=True)
class FindCatalog:
    """Słownik archiwum dla `resolve` - WARTOŚCI, nie zapytania. `objects` i `telescopes` to pary
    `(id, etykieta)` jak wartości listwy; `aliases` = `canon → {alias_norm}` (szukajka listwy)."""
    objects: tuple = ()
    filters: tuple = ()
    telescopes: tuple = ()
    nights: tuple = ()
    aliases: dict = field(default_factory=dict)
    rigs: tuple = ()


@dataclass(frozen=True)
class FindState:
    """Stan zbioru `FramesView`, który zapytanie ZASTĘPUJE: facety listwy (format `facet_model`),
    drzewo zaawansowane (warunek kamery zestawu), tekst uwag, to, czego zapytanie nie rozpoznało,
    i wpisane terminy z ich składnikami (`FindTerm`, chipy)."""
    facets: dict = field(default_factory=dict)
    filter_tree: dict | None = None
    note_query: str | None = None
    unmatched: tuple = ()
    terms: tuple = ()

    @property
    def recognized(self):
        """Czy zapytanie rozpoznało COKOLWIEK - samo „nie znam" nie zastępuje zbioru."""
        return bool(self.facets) or self.filter_tree is not None or self.note_query is not None


def _tokeny(text):
    """Tekst → tokeny jako listy `(znak, w_cudzysłowie)`. Cudzysłów nie należy do treści, a znak
    w cudzysłowie nie dzieli (spacja, przecinek, dwukropek są wtedy treścią). Niezamknięty
    cudzysłów obejmuje resztę tekstu - lepiej oddać wpisane słowa niż je zgubić."""
    tokeny, biezacy, w_cudz = [], [], False
    for znak in text or "":
        if znak in _CUDZYSLOWY:
            w_cudz = not w_cudz
            continue
        if znak.isspace() and not w_cudz:
            if biezacy:
                tokeny.append(biezacy)
            biezacy = []
            continue
        biezacy.append((znak, w_cudz))
    if biezacy:
        tokeny.append(biezacy)
    return tokeny


def _tekst(znaki):
    return "".join(z for z, _ in znaki)


def _czesci(znaki):
    """Wartość tokenu podzielona na niecytowanych przecinkach (OR w obrębie osi)."""
    czesci, biezaca = [], []
    for z, cyt in znaki:
        if z == "," and not cyt:
            czesci.append(biezaca)
            biezaca = []
        else:
            biezaca.append((z, cyt))
    czesci.append(biezaca)
    return czesci


def parse(text) -> FindQuery:
    """Tekst pola Znajdź → `FindQuery`. Czysta funkcja; nic nie wie o archiwum."""
    terms, slowa, unknown = [], [], []
    for nr, tok in enumerate(_tokeny(text)):
        dwukropek = next((i for i, (z, cyt) in enumerate(tok) if z == ":" and not cyt), None)
        if dwukropek is not None:
            przed = tok[:dwukropek]
            prefiks = _tekst(przed)
            if not any(cyt for _, cyt in przed) and _PRZEDROSTEK_RE.fullmatch(prefiks):
                os_ = PRZEDROSTKI.get(prefiks.casefold())
                if os_ is None:
                    unknown.append(_tekst(tok))
                    continue
                wartosc = tok[dwukropek + 1:]
                czesci = [wartosc] if os_ == "notes" else _czesci(wartosc)
                wartosci = [_tekst(c).strip() for c in czesci]
                wartosci = [w for w in wartosci if w]
                if not wartosci:
                    unknown.append(f"{prefiks}:")
                terms.extend(Term(os_, prefiks, w, nr) for w in wartosci)
                continue
        slowa.append(_tekst(tok))
    fraza = " ".join(slowa).strip()
    return FindQuery(terms=tuple(terms), phrase=fraza or None, unknown=tuple(unknown))


def _noce(wartosc, noce):
    if not _NOC_RE.fullmatch(wartosc):
        return []
    return [n for n in noce if n.startswith(wartosc)]


def _filtry(wartosc, filtry):
    klucz = norm_alnum(wartosc)
    return [f for f in filtry if klucz and norm_alnum(f) == klucz]


def _teleskopy(wartosc, teleskopy):
    """Równość `norm_alnum`, a dopiero bez niej prefiks: `RC8` nie ma prawa wciągnąć `RC8-bis`, gdy
    oba istnieją, ale `askar` ma znaleźć jedyny Askar bez wpisywania pełnej nazwy."""
    klucz = norm_alnum(wartosc)
    if not klucz:
        return []
    rowne = [(tid, et) for tid, et in teleskopy if norm_alnum(et) == klucz]
    return rowne or [(tid, et) for tid, et in teleskopy if norm_alnum(et).startswith(klucz)]


def _zestawy(wartosc, zestawy):
    klucz = norm_alnum(wartosc)
    return [z for z in zestawy if klucz and norm_alnum(z.label) == klucz]


def _obiekty_frazy(fraza, catalog):
    """Obiekty, które trafia fraza - najpierw DOKŁADNIE, dopiero bez dokładnych szukajką listwy.

    Szukajka (`facet_model.search_hit`) trafia też prefiksem i podciągiem, bo służy pisaniu znak po
    znaku (`sh2 13` ma już pokazać Sh2-131). Po Enterze fraza jest pytaniem zamkniętym: `m1` przy
    M1 i M101 to M1, a nie oba. Dokładne = `norm_alnum` frazy (albo jej postaci katalogowej
    `catalog_canon`) równe kanonowi albo jednemu z aliasów obiektu - liczone na całej LIŚCIE, więc
    choć jedno dokładne trafienie wyłącza prefiksowe. Brak dokładnych (`ngc70`) = droga szukajki."""
    klucz = norm_alnum(fraza)
    if not klucz:
        return []          # „żółć": szukajka zna tylko ASCII, pusta igła trafiłaby wszystko
    kanon = catalog_canon(fraza, split=False)
    klucze = {klucz} | ({norm_alnum(kanon)} if kanon else set())
    dokladne = [(oid, canon) for oid, canon in catalog.objects
                if norm_alnum(canon) in klucze or klucze & set(catalog.aliases.get(canon, ()))]
    return dokladne or [(oid, canon) for oid, canon in catalog.objects
                        if facet_model.search_hit(fraza, canon, catalog.aliases) is not None]


def _lisc(facet, value, label):
    return {"facet": facet, "value": value, "label": label}


def _lub(galezie):
    return galezie[0] if len(galezie) == 1 else {"op": "OR", "conditions": galezie}


def _drzewo_zestawow(pary, *, z_teleskopem):
    """Warunek zestawów w drzewie zaawansowanym - DOKŁADNY, nie przybliżony.

    Teleskop stoi w facecie listwy (widać go tam, gdzie każdy teleskop), a tu zostaje kamera. Samo
    „teleskopy OR × kamery OR" przepuszczałoby jednak krzyżówki: `zestaw:A_x,B_y` wpuściłoby klatki
    `A_y`, których user nie wskazał. Gdy iloczyn teleskopów i kamer jest dokładnie zbiorem par, OR
    kamer wystarcza; inaczej (i zawsze, gdy teleskop zawęża osobny token `teleskop:`, więc facet go
    nie niesie) każda para idzie jako AND(teleskop, kamera)."""
    teleskopy = list(dict.fromkeys(z.telescope_id for z in pary))
    kamery = list(dict.fromkeys((z.camera_id, z.camera) for z in pary))
    dokladny = set(product(teleskopy, [c for c, _ in kamery])) == {
        (z.telescope_id, z.camera_id) for z in pary}
    if dokladny and not z_teleskopem:
        return _lub([_lisc("camera", cid, et) for cid, et in kamery])
    return _lub([{"op": "AND", "conditions": [_lisc("telescope", z.telescope_id, z.telescope_label),
                                               _lisc("camera", z.camera_id, z.camera)]}
                 for z in pary])


def resolve(query: FindQuery, catalog: FindCatalog) -> FindState:
    """`FindQuery` + słownik archiwum → `FindState`. Czysta funkcja.

    Każda oś zbiera trafienia wszystkich swoich wartości (OR), osie składają się przez facety
    i drzewo (AND). Wartość bez trafienia nie zeruje osi - idzie do `unmatched`, a reszta zapytania
    działa. Kilka tekstów uwag (powtórzony `uwagi:` albo fraza bez obiektu obok `uwagi:`) składa się
    w JEDEN tekst, tą samą regułą co słowa bez prefiksu w jedną frazę.

    Każdy WPISANY termin (token z prefiksem, fraza, uwagi razem) dostaje `FindTerm` z kluczami
    składników, które postawił - chip „Noc: 2025-11" zdejmuje wszystkie noce miesiąca naraz."""
    facety, niezn, notatki, pary = {}, list(query.unknown), [], []
    teleskop_z_tokenu = False
    # Termin → (oś, wpisane wartości, które trafiły, klucze składników, zestawy terminu).
    terminy = {}

    def dodaj(facet, value, label):
        wybor = facety.setdefault(facet, {"in": []})["in"]
        if all(v != value for v, _ in wybor):
            wybor.append([value, label])
        return ("facet", facet, "in", value)

    for term in query.terms:
        trafione = True
        t = terminy.setdefault(term.token, {"os": term.axis, "wartosci": [], "klucze": [],
                                            "zestawy": []})
        if term.axis == "night":
            noce = _noce(term.value, catalog.nights)
            t["klucze"] += [dodaj("night", n, n) for n in noce]
            trafione = bool(noce)
        elif term.axis == "filter":
            filtry = _filtry(term.value, catalog.filters)
            t["klucze"] += [dodaj("filter", f, f) for f in filtry]
            trafione = bool(filtry)
        elif term.axis == "telescope":
            teleskopy = _teleskopy(term.value, catalog.telescopes)
            t["klucze"] += [dodaj("telescope", tid, et) for tid, et in teleskopy]
            teleskop_z_tokenu = teleskop_z_tokenu or bool(teleskopy)
            trafione = bool(teleskopy)
        elif term.axis == "rig":
            zestawy = _zestawy(term.value, catalog.rigs)
            pary += [z for z in zestawy if z not in pary]
            t["zestawy"] += zestawy
            trafione = bool(zestawy)
        else:
            notatki.append(term.value)
        if trafione and term.axis != "notes":
            t["wartosci"].append(term.value)
        if not trafione:
            niezn.append(f"{term.prefix}:{term.value}")

    if query.phrase is not None:
        if not any(z.isalnum() for z in query.phrase):
            # Sama interpunkcja (Unicode: `str.isalnum`) - to nie jest pytanie ani o obiekt, ani
            # o uwagę.
            niezn.append(query.phrase)
        else:
            # `norm_alnum` zostaje WYŁĄCZNIE do dopasowania obiektów: zna tylko znaki ASCII, więc
            # „żółć" daje pustą igłę, a pusta igła szukajki pasuje do KAŻDEGO obiektu. Fraza bez
            # znaku, który rozumie szukajka, nie trafia żadnego obiektu - idzie do uwag.
            obiekty = _obiekty_frazy(query.phrase, catalog)
            if obiekty:
                terminy["fraza"] = {"os": "object", "wartosci": [query.phrase], "zestawy": [],
                                    "klucze": [dodaj("object", oid, canon) for oid, canon in obiekty]}
            else:
                notatki.append(query.phrase)

    drzewo = None
    if pary:
        for t in terminy.values():
            if t["zestawy"]:
                t["klucze"] = [("filtr",)] + (
                    [] if teleskop_z_tokenu else
                    [dodaj("telescope", z.telescope_id, z.telescope_label) for z in t["zestawy"]])
        drzewo = _drzewo_zestawow(pary, z_teleskopem=teleskop_z_tokenu)
    uwagi = normalize_note(" ".join(notatki)) or None
    chipy = [FindTerm(i18n.t("find.chip.term", name=i18n.t(_NAZWA_OSI[t["os"]]),
                             value=", ".join(t["wartosci"])), tuple(dict.fromkeys(t["klucze"])))
             for t in terminy.values() if t["klucze"]]
    if uwagi is not None:
        # Wszystkie teksty uwag składają się w jeden `note_query`, więc i chip jest jeden.
        chipy.append(FindTerm(i18n.t("find.chip.notes", text=uwagi), (("uwagi",),)))
    return FindState(facets=facety, filter_tree=drzewo, note_query=uwagi,
                     unmatched=tuple(dict.fromkeys(niezn)), terms=tuple(chipy))


def catalog_from_db(con) -> FindCatalog:
    """Słownik `resolve` z CAŁEGO archiwum (zapytanie ZASTĘPUJE zbiór, więc słownikiem nie jest
    zbiór bieżący). Wartości facetów z tych samych read-modeli co listwa - inaczej zapytanie
    i klik w listwie rozumiałyby tę samą nazwę inaczej."""
    ids = queries.all_frame_ids(con)
    return FindCatalog(
        objects=tuple((r["id"], r["canon"]) for r in queries.facet_objects(con, ids)),
        filters=tuple(r["filter_canon"] for r in queries.facet_filters(con, ids)),
        telescopes=tuple((r["id"], queries.telescope_label(r))
                         for r in queries.facet_telescopes(con, ids)),
        nights=tuple(r["night"] for r in queries.facet_nights(con, ids)),
        aliases=queries.object_alias_index(con),
        rigs=tuple(Rig(**r) for r in queries.find_rigs(con)))
