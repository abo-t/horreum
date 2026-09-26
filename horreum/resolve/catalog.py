"""Oś OBIEKT — uniwersalia katalogowe: rozpoznanie oznaczenia + równoważność (NGC-wins).

Czyste funkcje (zero zapisu):
  - `catalog_canon(text)` — rozpoznaj oznaczenie katalogowe i znormalizuj zapis
    (`NGC 4736`→`NGC4736`, `Sh2 131`→`Sh2-131`, zera wiodące precz). None, gdy to NIE oznaczenie
    (nazwa potoczna „Heart Nebula" NIE przechodzi jako kanon — koniec cichego śmieciowego kanonu).
  - `xref(canon)` — równoważność międzykatalogowa (Messier/Caldwell/Sh2 → NGC/IC, polityka NGC-wins),
    DANYMI z `catalog_xref.json` (nie precedencją). Brak wpisu → kanon bez zmian (M45 zostaje M45).
  - `catalog_label(canon)` — etykieta katalogu z formy kanonicznej (NGC|IC|Sh2|Messier|…).
  - `header_form(canon)` - forma do karty `OBJECT` nagłówka (`NGC7000` → `NGC 7000`), odwracalna
    przez `catalog_canon`; `xref_aliases(canon)` - równoważność czytana wstecz (`NGC4258` → `M106`).

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
    # ── K-1: trzy gramatyki, które ASSET CELÓW JUŻ WYPISUJE, a oś obiektu ich nie znała.
    # Skala jest w teście (`test_K1_kanon_zgadza_sie_z_ASSETEM_celow` liczy ją z assetu, a nie
    # z tego komentarza) — asset rośnie, więc liczba wpisana tutaj byłaby fałszem od pierwszej
    # aktualizacji katalogu.
    #
    # NA DZISIEJSZYM ARCHIWUM TE GRAMATYKI NIE RUSZAJĄ NICZEGO — zmierzone przed scaleniem, bo
    # nowy szczebel drabiny stoi NAD aliasem i nad słownikiem, więc mógłby po cichu przenieść
    # klatki spod nazwy nadanej ręką: 0 ze 74 rozpoznanych `object_raw` i 0 aliasów trafia te
    # kształty, a `resolve` na kopii żywej bazy dał `objects_new=0`, `objects_assigned=0`,
    # `own_alias_conflicts=0` przy `human-facts --baseline` bez ubytków. Wchodzą więc pod PRZYSZŁY
    # materiał i pod most planera, nie pod przemalowanie archiwum.
    #
    # ZERA WIODĄCE ZOSTAJĄ — i to jest ŚWIADOME odstępstwo od reguły „bez zer wiodących" trzy
    # akapity wyżej. Tam liczba jest PORZĄDKOWA (M82 = 82. obiekt Messiera), więc `M082` to ten
    # sam obiekt zapisany inaczej. Tu liczba jest WSPÓŁRZĘDNĄ o stałej szerokości: `G012.2+00.3`
    # znaczy l=12,2° b=+0,3°, a `ESO056-115` to pole 056 i obiekt 115 w tym polu. Zdjęcie zera
    # zmieniłoby identyfikator, nie zapis — i rozjechało kanon z assetem, czyli otworzyło dokładnie
    # ten szew, który ta zmiana zamyka.
    #
    # PUŁAPKA `PN G###.#±##.#` (mgławice planetarne mają oznaczenie o IDENTYCZNYM kształcie
    # liczbowym). Broni przed nią DOPASOWANIE OD POCZĄTKU TOKENU: `_match_rules` woła `rx.match`,
    # więc „PN G012.2+00.3" nie trafia tej reguły i wychodzi jako None, zamiast udawać pozostałość
    # supernowej. Obrona jest więc własnością WOŁAJĄCEGO, nie widocznym warunkiem tutaj — i tym
    # bardziej wymaga pinu: dzień, w którym `_match_rules` przejdzie na `search`, zamieni 286 celów
    # Green w cichy fałsz. Test pinuje oba końce (regex ma `$`, wołający ma `match`).
    (re.compile(r"^G\s*(\d{1,3})\.(\d)\s*([+-])\s*(\d{1,2})\.(\d)$"),
     lambda m: f"G{int(m.group(1)):03d}.{m.group(2)}{m.group(3)}{int(m.group(4)):02d}.{m.group(5)}"),
    (re.compile(r"^ESO\s*(\d{1,3})\s*-\s*(\d{1,3})$"),
     lambda m: f"ESO{int(m.group(1)):03d}-{int(m.group(2)):03d}"),
    (re.compile(r"^HCG\s*(\d{1,3})$"), lambda m: f"HCG{int(m.group(1)):03d}"),
]


def _match_rules(key):
    """Dopasuj znormalizowany `key` do gramatyk katalogowych → kanon albo None (helper)."""
    for rx, build in _RULES:
        m = rx.match(key)
        if m:
            return build(m)
    return None


def catalog_canon(text, *, split=True):
    """Zwróć formę kanoniczną oznaczenia katalogowego LUB None, gdy tekst nim NIE jest.

    Normalizuje zapis: kolaps białych znaków, upper, zdjęcie zer wiodących (`NGC 4736`→`NGC4736`,
    `Sh2 131`→`Sh2-131`, `M 81`→`M81`). Apostrofy/inne znaki w nazwie potocznej → po prostu brak
    dopasowania (None) — nazwa potoczna należy do `resolve.objects`, nie tu.

    Zapis dwuczłonowy (`NGC4631_PGC42637`): gdy całość nie jest oznaczeniem, próbuj PIERWSZY człon
    przed `_` (firsthand: dwa oznaczenia sklejone podkreślnikiem). Rozdzielnik to WYŁĄCZNIE `_` —
    oznaczenia ze spacją wewnętrzną (`Sh 2-184`, `Caldwell 23`) to JEDEN człon i zostają nietknięte.

    `split=False` WYŁĄCZA tę gałąź (D-OW-2 pkt 5a) — wewnętrzny mechanizm dla wołania ze ŚCIEŻKI,
    gdzie autorem stringa nie jest akwizycja, tylko drzewo katalogów: folder SPRZĘTU `C8_2600MC`
    dałby po cięciu `C8` → Caldwell 8, a `C11` → śmieciowy kanon `C11`, który wypływa do facetu,
    do nazw plików (`naming.py`) i do drzewa projekcji. Gołe `C8`/`C11` na pozycji obiektu ZOSTAJE
    przyjęte (`_match_rules` dopasowuje je PRZED gałęzią cięcia) — gwarancję daje POZYCJA w drzewie,
    nie filtrowanie tokenów. Jedynym wołającym z `split=False` jest drabina w trybie `from_path`."""
    if not text:
        return None
    key = re.sub(r"\s+", " ", str(text).strip()).upper()
    canon = _match_rules(key)
    if canon:
        return canon
    if split and "_" in key:
        return _match_rules(key.split("_", 1)[0].strip())
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
    # K-1. `ESO`/`HCG` przed skrótami jednoliterowymi z tej samej litery nie kolidują, ale `G\d`
    # jest KRÓTKIE i stoi tu świadomie po `Ced`/`Cr`/`CTB` — reguła „dłuższe/specyficzne prefiksy
    # przed krótszymi" z nagłówka tej listy. `Green` to nazwa katalogu (jak `Collinder`/`Barnard`),
    # nie skrót — `G` jako etykieta nie powiedziałoby użytkownikowi niczego.
    (re.compile(r"^ESO\d"), "ESO"), (re.compile(r"^HCG\d"), "HCG"),
    (re.compile(r"^G\d"), "Green"),
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


@functools.lru_cache(maxsize=1)
def _xref_reverse():
    """Odwrócona równoważność: kanon preferowany → posortowana krotka oznaczeń, które na niego
    wskazują (`NGC7023` → `('C4', 'LDN1174')`). Liczona raz z `_xref_flat` - to ten sam asset."""
    rev = {}
    for alias, target in _xref_flat().items():
        rev.setdefault(target, []).append(alias)
    return {target: tuple(sorted(aliases)) for target, aliases in rev.items()}


def xref_aliases(canon):
    """Oznaczenia z `catalog_xref.json`, które `xref` sprowadza do `canon` (`NGC4258` → `('M106',)`).
    Pusta krotka, gdy kanon nie jest celem żadnej równoważności. Forma = forma kanoniczna aliasu,
    czyli ta, którą zna gramatyka (`M106`, nie `M 106`)."""
    return _xref_reverse().get(canon, ())


# FORMA NAGŁÓWKA (karta FITS/XISF `OBJECT`) - decyzja usera 2026-09-26: folder i `object.canon`
# są BEZ spacji (`NGC7000`), a nagłówek niesie JEDNĄ formę na obiekt, ZE SPACJĄ między skrótem
# katalogu a numerem (`NGC 7000`). Tabela obejmuje skróty, po których stoi numer PORZĄDKOWY albo
# pole katalogu (ESO/HCG zachowują zera wiodące kanonu K-1 - forma wstawia spację, nie przelicza
# numeru). Poza tabelą ŚWIADOMIE:
#   * `Sh2-131` - dywiz jest częścią oznaczenia, nie separatorem, więc forma = kanon;
#   * `G012.2+00.3` (Green) - `G` nie jest skrótem katalogu stojącym przed numerem, tylko
#     przedrostkiem WSPÓŁRZĘDNEJ galaktycznej (l, b); oznaczenie pisze się łącznie.
# Dłuższe skróty stoją przed krótszymi z tej samej litery (`CTB`/`Ced`/`Cr` przed `C`) - wymóg
# cyfry tuż po skrócie i tak rozstrzyga, ale kolejność czyni to czytelnym bez liczenia nawrotów.
# Test pinuje, że KAŻDA etykieta z `_LABELS` ma tu decyzję (spacja albo świadomy wyjątek), więc
# nowa gramatyka nie przejdzie po cichu z formą nagłówka równą kanonowi.
_HEADER_SPACED = re.compile(
    r"^(NGC|IC|UGC|PGC|LBN|LDN|CTB|Ced|Cr|Abell|vdB|ESO|HCG|M|C|B)(\d.*)$")
_HEADER_UNSPACED_LABELS = frozenset({"Sh2", "Green"})


def header_form(canon):
    """Kanon Horreum → forma do karty `OBJECT` w nagłówku (`NGC7000` → `NGC 7000`, `M45` → `M 45`,
    `Sh2-131` bez zmian). SPOT formy nagłówka dla całego kodu.

    Kanon spoza gramatyk katalogowych (obiekt własny `LMC`, solar `Moon`, region `Veil`, kometa)
    wraca BEZ ZMIAN - takiego kanonu nie ma jak rozbić na skrót i numer, a zgadywanie spacji
    w nazwie własnej zmieniłoby nazwę. O przynależności do gramatyki rozstrzyga `catalog_canon`
    (z `split=False`: kanon ma być oznaczeniem W CAŁOŚCI, nie pierwszym członem sklejki).

    Kontrakt odwracalności: `catalog_canon(header_form(c)) == c` dla każdego kanonu gramatyki -
    nagłówek zapisany tą formą wraca przez drabinę do TEGO SAMEGO kanonu."""
    if not canon or catalog_canon(canon, split=False) != canon:
        return canon
    m = _HEADER_SPACED.match(canon)
    return f"{m.group(1)} {m.group(2)}" if m else canon
