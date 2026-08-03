"""Oś OBIEKT — rozwiązanie `object_raw` → kanon (PLAN §3.5/§Etap 6).

Czysta funkcja `resolve_object(object_raw)` → `ObjectIdentity` albo None. Drabina (pierwsze
trafienie wygrywa):
  1. oznaczenie katalogowe (`catalog_canon`) + równoważność (`xref`, NGC-wins) — `source='header'`
     gdy kanon bez zmian, `source='catalog_xref'` gdy zmapowany (M106→NGC4258, Sh2-190→IC1805);
  2. nazwa potoczna (`_COMMON`, uniwersalia nieba) → kanon — `source='common_name'`;
  3. SŁOWNIK OBIEKTÓW WŁASNYCH (`data/objects_own.json`) — kanon SAMO-KANONICZNY dla obiektu spoza
     gramatyki katalogowej (`LMC`, `WR134`) — `source='curated'`;
  4. nic pewnego → None (warstwa wyżej rozstrzyga, czy to delta — TYLKO dla light/master_light;
     kalibracja nie ma obiektu z definicji).

DLACZEGO SŁOWNIK JEST OSOBNYM SZCZEBLEM, A NIE WPISEM W `_COMMON` (D-OW-1): `_COMMON` mapuje nazwę
potoczną na OZNACZENIE KATALOGOWE i ta niezmienniczość niesie go dalej przez `xref` i
`catalog_label`. Wpis samo-kanoniczny („LMC" → „LMC") ją łamie, a prowieniencja wpisu nie ma
w kodzie gdzie mieszkać. Klasa „obiekt bez numeru katalogowego" jest więc DANĄ, na wzór
`regions.json` — z tym samym ostrzeżeniem: edycja assetu na istniejącej bazie to operacja
MIGRACYJNA, nie zwykły re-run.

KIND-AWARENESS mieszka w orkiestracji (`horreum.resolver`), nie tu: ta funkcja ocenia sam string.
Solar/komety (Lemmon/Księżyc/planety) rozwiązuje `resolve.solar` (krok 5a), wołany PRZED `resolve_object`
w orkiestracji — ta funkcja pozostaje deep-sky-only. `kind='deep_sky'` dla wszystkiego, co wychodzi
z gramatyki katalogowej i z `_COMMON`; szczebel SŁOWNIKA zwraca `own` (obiekt spoza katalogów bierze
rodzaj z wpisu, `OBJECT_KINDS`).

`_COMMON` = uniwersalia (wiedza o niebie jako KOD, jak deklaruje `resolve/__init__`) — NIE dane
per-archiwum. Rośnie po firsthand; seed = przypadki nazwane w spec §3.5 + potwierdzone firsthand
(Elephant's Trunk, Pelican, Bode's Galaxy). Nazwy potoczne dopuszczają sufiks deskryptora
(„Rosette Nebula", „Bode's Galaxy") — zdejmowany przed dopasowaniem.
"""
import functools
import json
import re
from dataclasses import dataclass
from importlib import resources

from ._coerce import _to_text
from ._text import norm, norm_alnum
from .catalog import catalog_canon, catalog_label, xref

# ────────────────────────────────────── enum źródeł osi OBIEKT (JEDEN właściciel — S1, D-OW-1)
# Dotąd ten fakt mieszkał w TRZECH miejscach i wszystkie trzy się rozjeżdżały: komentarz DDL
# `frame.object_source` (0002:20) wymieniał `header|alias|catalog_xref|review|user`, choć żywa baza
# niesie także `common_name` (1386 klatek), `solar` (782), `comet` (415) i `region` (250) — cztery
# wartości spoza komentarza, przy dwóch wymienionych, których nie ma ani razu. Komentarz
# `object_alias.source` (0002:146) i docstring `repo.add_object_alias` różniły się o `review`.
# Odtąd fakt jest TU, a tamte miejsca się do niego odwołują.
#
# `region` NIE występuje wśród źródeł ALIASU świadomie: kompleks rozpoznaje się ze WSPÓŁRZĘDNYCH,
# więc nie ma nazwy do zapisania jako równoważność (zob. `resolve/regions.py`).
# `review` nie ma dziś ani jednego pisarza w kodzie — zostaje jako wartość zarezerwowana DDL-em,
# wymieniona tu jawnie, żeby audyt enumu nie czerwienił się na zastanej bazie.
ALIAS_SOURCES = frozenset({"header", "catalog_xref", "common_name", "curated", "solar", "comet",
                           "review", "user"})
# Źródła na KLATCE = źródła aliasu + szczeble, które nazwy nie zapisują (`region`, `path`), + `alias`
# (trafienie zapisanej wcześniej równoważności) i `user` (gest człowieka, pomija całą drabinę).
#
# `path` (S2, D-OW-2/B) NIE występuje wśród źródeł ALIASU z tego samego powodu co `region`: segment
# ścieżki nie trafi żadnego przyszłego `object_raw`, więc nie ma nazwy do zapisania jako
# równoważność. Klatka nosi je po POTWIERDZENIU propozycji ręką — świadkiem pozostaje ścieżka,
# więc źródło ma to mówić, zamiast udawać wskazanie palcem (`user`).
#
# `user_cleared` (S2b, D-OW-6) to NAGROBEK, a nie rozpoznanie: klatka ma `object_id IS NULL`, a to
# pole niesie jedyny ślad, że pustka jest WERDYKTEM ręki, nie brakiem zeznania. Bez niego kolejny
# `Rozwiąż` przypisywałby ją z powrotem tym samym szczeblem, który człowiek właśnie odrzucił —
# a cofnięcie, które cofa się samo przy najbliższym przebiegu, nie jest cofnięciem.
OBJECT_SOURCES = ALIAS_SOURCES | {"alias", "region", "path", "user_cleared"}

# Źródła, które POMIJAJĄ CAŁĄ drabinę — jeden właściciel dla przebiegu, klingi i read-modelu.
# Wspólny mianownik: oba są ZEZNANIEM CZŁOWIEKA o tej konkretnej klatce, a przebieg nie ma prawa
# przegłosować ręki. Różni je tylko kierunek werdyktu (wskazał obiekt / zdjął obiekt).
STICKY_OBJECT_SOURCES = frozenset({"user", "user_cleared"})

# Źródła SŁABE — rozpoznania, które „Nazwij zaznaczenie" wolno NADPISAĆ (S2b). Świadkiem jest tu
# ścieżka, czyli zeznanie o pliku, a nie o niebie: folder mógł zostać nazwany byle jak i to jest
# dokładnie ta klasa pomyłki, którą gest ręki ma naprawiać. Nagłówek, xref i region ZOSTAJĄ poza —
# ich nadpisanie byłoby cichym zamalowaniem faktu z pliku albo z geometrii.
WEAK_OBJECT_SOURCES = frozenset({"path"})

# Źródła, które „Cofnij przypisanie" wolno ZDJĄĆ (S2b) — postawiła je ręka albo ścieżka, więc
# cofnięcie naprawia POMYŁKĘ CZŁOWIEKA, a nie kasuje faktu z pliku ani z geometrii. Stała powstała
# przy adjudykacji recenzji S2b: zbiór żył jako literał `("path","user")` w DWÓCH miejscach — klindze
# (`repo.clear_object_assignment`) i read-modelu wygaszającym kontrolkę (`gui.queries`) — a to jedno
# pytanie z dwiema siedzibami. Pierwsze rozszerzenie rozjechałoby przycisk z klingą: aktywny gest,
# który milczy, albo wygaszony przy robocie do zrobienia.
CLEARABLE_OBJECT_SOURCES = WEAK_OBJECT_SOURCES | {"user"}

# …i TA SAMA reguła dla `object.kind`, bo segment domykający rozjazd źródeł wprowadził własny na
# rodzaju: szczebel słownika zwraca `own`, którego DDL nie znał. Wartość spoza tej stałej znaczy,
# że ktoś dopisał rodzaj bez powiedzenia o tym drugiej stronie.
OBJECT_KINDS = frozenset({"deep_sky", "solar_system", "comet", "region", "own"})

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
    kind: str            # ∈ OBJECT_KINDS: deep_sky | own (solar/comet poza pierwszym przebiegiem)
    source: str          # header | catalog_xref | common_name | solar | comet | region
    alias_norm: object   # znormalizowana forma surowa (klucz object_alias); None gdy rozpoznanie
                         # NIE pochodzi z nazwy (region — ze współrzędnych) → resolver pomija alias


def _common_canon(raw):
    """Nazwa potoczna → oznaczenie katalogowe (przed xref) albo None. Zdejmuje „the"/deskryptor,
    porównuje przez `norm_alnum`."""
    key = _THE.sub("", norm(raw))
    key = _DESCRIPTOR.sub("", key)
    return _COMMON.get(norm_alnum(key))


def _own_stamp():
    """`mtime_ns` słownika jako klucz cache'u — bez niego edycja assetu NIE ODSŁANIA SIĘ w żywej
    sesji, a to jest dokładnie funkcja, dla której ten plik powstał („edycja = operacja
    migracyjna"). Wzorzec i uzasadnienie: `targets._asset_stamp` — DRUGI czytelnik TEGO SAMEGO
    pliku stempluje od dawna, więc bez tego jedna sesja pokazywałaby planerowi nową treść, a
    resolverowi starą. Asset spoza systemu plików nie ma `stat` → `None` (cache jak przed zmianą)."""
    try:
        return (resources.files("horreum.resolve.data")
                .joinpath("objects_own.json").stat().st_mtime_ns)
    except (OSError, AttributeError, NotImplementedError):
        return None


def load_own_objects():
    """Wczytaj `objects_own.json`. Zwraca krotkę surowych rekordów — mutowalna lista pozwoliłaby
    wołającemu zmutować cache.

    Plik jest WSPÓLNY z planerem (D-OW-1/E′): tam czyta go `targets._load_stamped`, filtrując do
    rekordów-celów. Rdzeń bierze z niego NAZWY i nie pyta o pola celu — obiekt bez rozmiaru jest
    dla resolvera pełnoprawny, dla planera nie istnieje."""
    return _load_own_stamped(_own_stamp())


@functools.lru_cache(maxsize=2)
def _load_own_stamped(_stamp):
    """`_stamp` uczestniczy WYŁĄCZNIE w kluczu cache'u (stąd podkreślenie) — jak `targets`."""
    text = (resources.files("horreum.resolve.data")
            .joinpath("objects_own.json").read_text(encoding="utf-8"))
    return tuple(json.loads(text)["targets"])


def _own_index():
    """Indeks nazw → tożsamość, przeliczany po zmianie pliku (stempel jak wyżej)."""
    return _own_index_stamped(_own_stamp())


@functools.lru_cache(maxsize=2)
def _own_index_stamped(_stamp):
    """`norm_alnum(nazwa)` → `(kanon, catalog, kind)`, dla kanonu ORAZ każdej nazwy potocznej `n`.
    Indeks liczony raz: drabina pyta o niego per klatka, a plik ma rosnąć.

    KOLIZJA W PLIKU JEST BŁĘDEM, NIE PIERWSZEŃSTWEM (EXPECT): dwa rekordy pod jednym kluczem znaczą,
    że człowiek wpisał tę samą nazwę dwa razy, a ciche „wygrywa ostatni" ukryłoby to na zawsze —
    unikalność KANONÓW pilnuje producent assetu, ale nazwy `n` widzi dopiero ten indeks."""
    idx = {}
    for rec in load_own_objects():
        canon = _to_text(rec.get("c"))
        if canon is None:
            raise ValueError("objects_own.json: rekord bez kanonu `c`")
        kind = rec.get("kind") or "own"
        if kind not in OBJECT_KINDS:
            raise ValueError(f"objects_own.json: rekord {canon!r} ma rodzaj {kind!r} spoza "
                             f"OBJECT_KINDS — pole leci wprost do `object.kind`")
        entry = (canon, rec.get("catalog"), kind)
        for name in (canon, *(rec.get("n") or ())):
            key = norm_alnum(name)
            if not key:
                continue
            if idx.get(key, entry)[0] != canon:
                raise ValueError(f"objects_own.json: nazwa {name!r} wskazuje dwa rekordy "
                                 f"({idx[key][0]!r} i {canon!r})")
            idx[key] = entry
    return idx


def resolve_object(object_raw, *, split=True):
    """`object_raw` (zeznanie nagłówka) → `ObjectIdentity` albo None (nierozpoznane). Czysta funkcja.

    Brak/pusty → None (nie ma czego rozwiązywać). Oznaczenie katalogowe → kanon + xref; nazwa
    potoczna → kanon przez `_COMMON` + xref; nazwa ze SŁOWNIKA obiektów własnych → kanon wprost.
    None ⇒ warstwa wyżej decyduje o delcie (zależnie od `kind` — kalibracja nie ma obiektu, więc
    jej None to poprawny stan, nie delta).

    `split` przewleczone do `catalog_canon` (D-OW-2 pkt 5a): wołanie ze ŚCIEŻKI idzie bez gałęzi
    cięcia po `_`. Kwarg musi przejść TĘDY, a nie tylko przez `catalog_canon` — inaczej wołający
    ze ścieżki miałby do wyboru dwie regresje: globalne `split=False` wywala `NGC4631_PGC42637`
    na całej osi nagłówka (13,5 tys. klatek), globalne `True` wpuszcza folder sprzętu."""
    raw = _to_text(object_raw)
    if raw is None:
        return None

    cc = catalog_canon(raw, split=split)
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

    # SŁOWNIK OBIEKTÓW WŁASNYCH — ostatni szczebel tej funkcji (S1, D-OW-1/E′). Stoi PO `_COMMON`,
    # bo `_COMMON` mapuje nazwę potoczną na OZNACZENIE KATALOGOWE i tę niezmienniczość zachowuje;
    # słownik jest dla kanonów, których gramatyka katalogowa nie zna i znać nie ma (`LMC`), więc
    # wpis SAMO-KANONICZNY mieszka tu, a nie tam.
    #
    # BEZ `xref`: kanon jest tu ostateczny z definicji klasy — nie ma oznaczenia katalogowego,
    # na które można by go zmapować.
    own = _own_index().get(norm_alnum(raw))
    if own is not None:
        canon, catalog, kind = own
        return ObjectIdentity(canon=canon, catalog=catalog, kind=kind,
                              source="curated", alias_norm=norm_alnum(raw))

    return None
