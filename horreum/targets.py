"""PLANER CELÓW — katalog × sprzęt × noc × archiwum (segment T3).

Odpowiada na pytanie użytkownika w jednym przebiegu: „co dziś mam na niebie, w odpowiedniej
wielkości i odpowiednich filtrach". Cztery fakty składane w jeden wiersz: czy cel jest DOSTĘPNY
(`sky.visibility_window`), czy się MIEŚCI (`sky.framing` w bieżących configach), czego mu BRAKUJE
(godziny z archiwum per kanał) i ile dziś KOSZTUJE Księżyc (`sky.moon_state` per paleta).

WYKONALNOŚĆ JEST TYPO-ZALEŻNA (D-0731-10): galaktyka potrzebuje rozmiaru I magnitudo, mgławica
emisyjna wyłącznie rozmiaru (Sh2 bywa „mag 20" i świetnie wychodzi w Ha — filtr po jasności wyciął
by rdzeń archiwum), ciemna ma własny, wyższy próg rozmiaru. Typ spoza taksonomii ODPADA jawnie:
`t` w pliku człowieka pisze człowiek, a cicha przynależność do klasy emisyjnej dałaby mu przepustkę
bez żadnego kryterium. Progi są ARGUMENTAMI — asset jest pulą, nie decyzją.

SUFITU ROZMIARU NIE MA (D-0731-8): cel większy od kadru dostaje LICZBĘ PANELI. „Nie mieści się"
to parametr kadrowania, nie powód do ukrycia celu.

FILTR KADRU JEST NA ŻĄDANIE (dług T5 „podłoga optyki", PL-1, PL-2): `min_fill` (cel za mały dla
optyki) i `max_panels` (bez mozaik na jedną noc) są DOMYŚLNIE WYŁĄCZONE, jak próg kosztu
(D-0731-14) - bez nich odpowiedź planera jest ta sama co przed filtrem. Włączone tną PULĘ przed
oknem widoczności, z kwantyfikatorem LUB po parku („mam czym to zrobić"), a `best_rig` wybierany
jest wtedy spośród zestawów, które filtr przepuszczają. `max_panels` nie łamie D-0731-8: tamto
zakazuje sufitu narzuconego, to jest sufit, o który użytkownik prosi wprost.

POKRYCIE KLEI SIĘ PO KANONIE I ALIASACH KATALOGOWYCH, NIGDY PO NAZWIE POTOCZNEJ: „Eastern Veil"
wskazuje jednocześnie NGC6992 i NGC6995 (5 takich kolizji w assecie), więc nazwa potoczna ma głos
wyłącznie w `find`. Kanon archiwum, który nie trafi w żaden rekord (region `Veil`, komety), idzie
do JAWNEJ RESZTY z godzinami — cicho zgubione godziny czyniłyby rachunek pokrycia fałszywie
zielonym.

POKRYCIE MA DWIE LICZBY GODZIN (I-2e): zebrane (wszystkie lighty) i ZINTEGROWANE (to, co weszło
w gotowy obraz — rodowód stosów P-I). Druga liczy każdy sub RAZ, choć `integration_input` jest
N:M: reprocessing tej samej nocy i warianty tego samego obrazu (`_ast`, `_drizzle_1x`) dzielą
wejścia, więc suma po relacjach rosłaby od samego przeliczania archiwum. Luki i rada stoją na
liczbie ZEBRANEJ — „nie zestackowałem" nie jest brakiem materiału.

KSIĘŻYC WYCENIA, NIE WYCINA (D-0731-14): koszt jest kolumną i członem klucza sortowania, próg
domyślnie wyłączony. Sortowanie ma TRZY człony przed kosztem-i-nazwą, bo każdy pojedynczy zawodzi:
cel pod horyzontem ma uczciwe `cost=1,00`, a przy nowiu KAŻDY cel ma 1,00 i ranking zdegenerowałby
się do alfabetu. Tuż przed kosztem stoi KUBEŁEK KADRU (PL-1): dobry jeden kadr, mozaika, cel za
mały - kropka w kadrze nie wyprzedza celu, który optyka zrobi dobrze.

Qt-wolne, READ-ONLY (zero DML, zero eventów, zero migracji — moduł nie jest klingą), SELECT
literałem, zero sieci.
"""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from importlib import resources

from . import sky
from .gui.queries import (all_frame_ids, integrated_exposure, object_exposure,
                          stack_locations)
from .resolve._coerce import _to_float, _to_text
from .resolve.catalog import catalog_canon, xref

# ─────────────────────────────────────────────────────── taksonomia (JEDEN właściciel — T3 §3)
# Tokeny typu OpenNGC. `scripts/build_catalog.py` IMPORTUJE te zbiory zamiast trzymać kopię.
GALAXY_TYPES = frozenset({"G", "GPair", "GTrpl", "GGroup"})
DARK_TYPES = frozenset({"DrkN"})
NEBULA_TYPES = frozenset({"Neb", "EmN", "HII", "RfN", "Cl+N", "SNR", "PN"})
# Odrzucane wprost przy budowie assetu: OCl|GCl|*|**|*Ass|Dup|NonEx|Other|Nova („nie interesują
# mnie gromady bez mgławicy"). Tu nie wymieniamy ich z nazwy — wszystko spoza trzech zbiorów wyżej
# odpada jako `unknown_type`.

# Domyślnie widać RDZEŃ; cirrus (LBN/LDN, 2017 rekordów = 77% katalogu) na żądanie — D-0731-9.
# `curated` doklejany BEZWARUNKOWO do każdej kombinacji (D-0731-11: kurowany jest obowiązkowy,
# nie opcją — inaczej `--layers cirrus` gubi WR134).
DEFAULT_LAYERS = ("core",)
ALL_LAYERS = ("core", "cirrus")
# Warstwa `curated` czyta plik CZŁOWIEKA — po E′ (D-OW-1) jest nim `resolve/data/objects_own.json`,
# wspólny z resolverem: jedna klasa „obiekt bez numeru katalogowego" ma jednego właściciela. Nazwa
# warstwy zostaje `curated`, bo „curated wygrywa" stoi na LITERALE (`coverage_index` niżej).
_ASSET = {"core": ("horreum.data", "targets_core.json"),
          "cirrus": ("horreum.data", "targets_cirrus.json"),
          "curated": ("horreum.resolve.data", "objects_own.json")}

# ─────────────────────────────────────────── kontrakt rekordu assetu (JEDEN właściciel — D-OW-1/E′)
# Plik człowieka niesie DWIE klasy rekordów: rekord-CEL (komplet pól niżej) i rekord-NAZWĘ (żadnego
# z nich — sam kanon z nazwami potocznymi, dla obiektu, którego planer nie umie zaplanować: LMC nie
# wschodzi ze Szczecina, `Orion` to pole gwiazdozbioru, nie obiekt o rozmiarze).
#
# PLANER DOSTAJE WYŁĄCZNIE REKORDY-CELE — z MECHANIZMU (filtr w loaderze), nie z ostrożności
# wołającego. Rekord-nazwa wpuszczony do puli planera kosztowałby trzy awarie zmierzone w kodzie:
# `--find` pomija `feasible` i przedcięcie, więc `ra_deg=None` szłoby wprost do `sky.visibility_window`
# (wpisanie „LMC" w szukajkę wywala planer); `coverage_index` przejąłby kanon bez tworzenia wiersza,
# więc godziny archiwum zniknęłyby i z `rows`, i z JAWNEJ RESZTY; a `_target` i tak by go odrzucił.
# Dlatego rekord-nazwa NIE dociera do `_target` — jego koercja i tripwir zostają NIETKNIĘTE.
#
# Rekord NIEPEŁNY (część pól celu) NIE jest trzecią klasą — to błąd pliku i ma wybuchnąć na
# `_target`, przy kanonie, a nie pół planera dalej (EXPECT).
TARGET_FIELDS = ("t", "r", "d", "a")


def target_fields_present(raw):
    """Ile pól CELU niesie surowy rekord assetu: `0` = rekord-nazwa, `len(TARGET_FIELDS)` = rekord-cel,
    pomiędzy = plik niepełny. Predykat jest wspólny dla loadera i dla `scripts/build_catalog.py`:
    gdyby producent i konsument miały własne kopie, asset przechodziłby budowę i padał przy
    wczytaniu (albo odwrotnie)."""
    return sum(1 for k in TARGET_FIELDS if raw.get(k) is not None)

# B−V galaktyk to +0,7…1,0 mag; bez korekty próg „mag ≤ 13" po cichu odrzuciłby galaktyki realnie
# jaśniejsze od progu. HEURYSTYKA (jedna liczba na klasę), nie pomiar per obiekt.
B_TO_V = 0.8
# Margines przedcięcia deklinacją: asset trzyma J2000, rachunek jedzie na datę, precesja daje do
# 0,15° na dzisiejszą epokę. Cięcie 3× szersze od błędu.
_CUT_MARGIN = 0.5
# Granica „dobrego kadru" w rankingu (PL-1, R2): jeden kadr wypełniony co najmniej w tej części
# (`sky.Framing.frame_fill`) stoi przed mozaiką i przed celem za małym. Ta sama liczba jest
# domyślną wartością progu „Min. wypełnienie" w GUI - próg i ranking mówią jednym głosem.
RANK_MIN_FILL = 0.3

# ─────────────────────────────────────────────────────── palety i kanały (T3 §6)
# Kanał = to, czego brak użytkownik nazywa luką („Ha bez OIII / HOO bez SII"). Broadband jest
# JEDNYM kanałem, bo OSC dostarcza RGB jednym strzałem — rozbicie na R/G/B dałoby kamerze kolorowej
# trzy fałszywe luki. Duoband zasila Ha ORAZ OIII, bo dokładnie to fizycznie zbiera.
RGB = "RGB"
NARROW_CHANNELS = ("Ha", "OIII", "SII")
PALETTE_OF_CHANNEL = {RGB: "broadband", "Ha": "narrowband", "OIII": "narrowband",
                      "SII": "narrowband"}
_BROADBAND_FILTERS = frozenset({"L", "R", "G", "B", "L-Pro", "CLS"})
_DUOBAND_FILTERS = frozenset({"L-eXtreme", "L-eNhance", "L-Ultimate"})
_NARROWBAND_FILTERS = frozenset({"Ha", "OIII", "SII"})


@dataclass(frozen=True)
class Target:
    """Rekord assetu po walidacji i koercji. Plik człowieka pisze CZŁOWIEK, więc `"a": "15"` musi
    zachować się jak `15.0` (kanon W3) — koercja jest tu regułą, nie ozdobą."""
    canon: str
    type: str
    ra_deg: float
    dec_deg: float
    major_arcmin: float
    minor_arcmin: float | None
    mag: float | None
    mag_from_b: bool
    aliases: tuple
    layer: str
    why: str | None
    size_source: str | None

    @property
    def catalog_aliases(self):
        """Aliasy przechodzące gramatykę katalogową, w formie kanonicznej resolvera. TYLKO one
        niosą pokrycie — nazwa potoczna wskazuje bywa na dwa rekordy naraz."""
        out = []
        for a in self.aliases:
            c = catalog_canon(a)
            if c:
                out.append(xref(c))
        return tuple(out)


@dataclass(frozen=True)
class Coverage:
    """Pokrycie celu w archiwum. `hours_by_channel` niesie kanały (§6), `archive_canons` mówi, POD
    JAKĄ NAZWĄ użytkownik ma klatki — `LBN807` na wierszu `IC410` (D-T2-d).

    DWIE RÓŻNE LICZBY GODZIN, ŚWIADOMIE OBOK SIEBIE (I-2e): `hours_*` to CO ZEBRANO (wszystkie
    lighty), `integrated_*` to CO WESZŁO w gotowy obraz (rodowód stosów, sub liczony raz). Luki
    i rada liczą się z pierwszej — cel z 8 h w Ha ma ten kanał zrobiony, niezależnie od tego, czy
    zdążył go zestackować. Druga jest odpowiedzią na inne pytanie („ile z tego jest obrazem")
    i domyka most, którego planer nie miał. Baza bez rodowodu stosów daje po prostu zera —
    nie brak faktu, tylko fakt „nic jeszcze nie zintegrowano"."""
    hours_by_filter: dict
    hours_by_channel: dict
    gaps: tuple
    archive_canons: tuple
    frames_no_exptime: int
    integrated_by_filter: dict = field(default_factory=dict)
    integrated_by_channel: dict = field(default_factory=dict)
    stacks: tuple = ()             # (frame_id, ścieżka|None) gotowych obrazów tego celu

    @property
    def total_hours(self):
        return sum(self.hours_by_filter.values())

    @property
    def integrated_hours(self):
        return sum(self.integrated_by_filter.values())

    @property
    def known(self):
        return bool(self.archive_canons)


@dataclass(frozen=True)
class RigSet:
    """Zestaw = (teleskop, pole widzenia), NIE config: trzy kamery na jednej optyce dają to samo
    kadrowanie. Kamery jadą jednak w wyniku, bo paleta jest własnością KAMERY — rada „rób SII"
    jest niewykonalna zestawem z matrycą kolorową."""
    config_id: int
    telescope: str
    cameras: tuple
    mono: bool
    fov_x_arcmin: float | None
    fov_y_arcmin: float | None
    lights: int
    reason: str | None
    # Etykieta dla człowieka, nadawana przez `rig_sets` (jedyne miejsce, które widzi wszystkie
    # zestawy naraz): przy DRUGIM zestawie na tej samej optyce (inna kamera = inne pole widzenia)
    # sama nazwa teleskopu nie mówi, który kadr masz przed oczami. `None` = nazwa teleskopu.
    label: str | None = None

    @property
    def name(self):
        """Nazwa zestawu na powierzchniach (chip, komórka, CLI): teleskop, a przy dwóch zestawach
        jednego teleskopu teleskop z kamerami. W obrębie jednego `PlanResult.rigs` - unikalna."""
        return self.label or self.telescope


@dataclass(frozen=True)
class TargetRow:
    target: Target
    window: object                 # sky.Window
    framing: dict                  # RigSet.config_id -> sky.Framing (czytaj przez `framing_in`)
    best_rig: RigSet | None
    coverage: Coverage
    cost: dict                     # paleta -> ile razy dłużej dla tego samego S/N
    recommend: str | None          # kanał do zrobienia dziś
    recommend_reason: str | None   # no_gap|rig_cannot|no_rig
    # Kuratela (T4) — `None` znaczy „użytkownik tego celu nie tknął", nie „odrzucił".
    plan_status: str | None = None      # planned|active|done|skip
    priority: int | None = None         # mniejsza = pilniejsza
    note: str | None = None

    def framing_in(self, rig):
        """Kadrowanie celu w zestawie `rig`; `None` = brak zestawu albo zestaw bez FOV.

        Słownik jest kluczowany TOŻSAMOŚCIĄ ZESTAWU (`config_id` jego reprezentanta), nie nazwą
        teleskopu: jedna optyka z dwiema kamerami daje dwa zestawy o różnym polu widzenia, a klucz
        po teleskopie oddawał kadrowanie zestawu iterowanego później - przy filtrze kadru ekran
        chował cel pod „najlepszym dopasowaniem", a CLI drukował cudze wypełnienie. Jedna droga
        odczytu dla rdzenia, CLI i ekranu."""
        return None if rig is None else self.framing.get(rig.config_id)


@dataclass(frozen=True)
class PlanResult:
    rows: tuple
    night_date: date
    site: object                   # sky.Site
    night: object                  # sky.NightWindow
    moon: object                   # sky.MoonState w ŚRODKU ciemności (nagłówek, nie per cel)
    rigs: tuple
    skipped_rigs: tuple
    unmatched: dict                # kanon archiwum bez rekordu w katalogu -> godziny
    counts: dict
    unfiltered_mono: int
    hidden: int                    # ile wierszy ucięto limitem (ZERO cichych sufitów)
    # Park (T4): CZYM liczono i SKĄD to wiadomo — „ile mam zestawów" bez tego jest liczbą
    # bez zeznania. `park_without_rigs` = teleskopy oznaczone, które nie dały ANI JEDNEGO zestawu
    # (0 lightów) — cichy ubytek zestawu to ta sama kategoria błędu co cichy sufit listy.
    park: tuple = ()
    park_source: str = "none"      # arg (jawne wołanie) | db (telescope.in_park) | none
    park_without_rigs: tuple = ()
    # Oznaczenia kurateli, których lista NIE POKAŻE (R-S0-7) — `{kanon: (stan, wiersz, gdzie)}`.
    # Stoją OBOK `rows`, a nie w nich: wiersz planera niesie okno, kadrowanie i koszt liczone
    # z rekordu katalogu, a sierota rekordu nie ma. Pusty słownik = wszystko widać.
    orphan_marks: dict = field(default_factory=dict)
    # Filtr kadru (`min_fill`/`max_panels`) - progi Z WOŁANIA i STAN, w którym zadziałały:
    # `off` (nie proszono) · `on` (tnie pulę) · `no_park` (park nieustawiony: liczenie po wszystkich
    # teleskopach bazy, także historycznych, nie odcięłoby uczciwie niczego) · `no_rigs` (park nie
    # dał zestawu z FOV) · `find` (tryb szukania pomija progi). Powierzchnie czytają progi STĄD -
    # soczewka ekranu nie ma własnej kopii.
    min_fill: float | None = None
    max_panels: int | None = None
    rig_filter: str = "off"


# ─────────────────────────────────────────────────────── asset

def load_targets(layers=DEFAULT_LAYERS):
    """Wczytaj asset (krotka — wynik jest cache'owany, lista pozwoliłaby wołającemu zmutować cache).

    `curated` doklejany ZAWSZE (D-0731-11: asset kurowany jest obowiązkowy, nie opcją) — bez tego
    `--layers cirrus` gubiłby `WR134`, cel bez numeru katalogowego.

    CACHE ZNA STEMPEL PLIKÓW: klucz niesie `mtime_ns` każdej wczytywanej warstwy, więc podmiana
    assetu w trakcie sesji (`scripts/build_catalog.py` obok działającego okna) odsłania się przy
    następnym wołaniu, zamiast czekać na restart. Sygnałem zmiany jest MTIME, nigdy rozmiar —
    reguła repo jest w tym jednoznaczna [memory: `horreum-file-size-not-discriminator`]."""
    return _load_stamped(tuple(layers), _asset_stamp(layers))


def _asset_file(layer):
    """Traversable warstwy. Pakiet jest CZĘŚCIĄ mapy `_ASSET`, nie stałą wpisaną w wołających:
    plik człowieka mieszka w assetach resolvera, generowane katalogi w `horreum/data`."""
    package, name = _ASSET[layer]
    return resources.files(package).joinpath(name)


def _asset_stamp(layers):
    """`mtime_ns` warstw jako klucz cache'u. Asset spoza systemu plików (hipotetyczny zip-import)
    nie ma `stat` — wtedy stempel jest `None` i cache zachowuje się jak przed zmianą (jedno
    wczytanie na proces). Frozen onefile rozpakowuje oba katalogi assetów do realnych plików, więc
    w wydaniu stempel JEST."""
    stamps = []
    for layer in tuple(layers) + ("curated",):
        try:
            stamps.append(_asset_file(layer).stat().st_mtime_ns)
        except (OSError, AttributeError, NotImplementedError):
            stamps.append(None)
    return tuple(stamps)


@functools.lru_cache(maxsize=8)
def _load_stamped(layers, _stamp):
    """Właściwe wczytanie — `_stamp` uczestniczy WYŁĄCZNIE w kluczu cache'u (stąd podkreślenie).

    REKORDY-NAZWY ODPADAJĄ TU (D-OW-1/E′): planer widzi wyłącznie rekordy z kompletem pól celu.
    Filtr stoi PRZED `_target`, więc koercja i jej tripwir nie muszą wiedzieć o drugiej klasie
    rekordu — rekord niepełny nadal na nich wybucha."""
    out = []
    for layer in layers + ("curated",):
        text = _asset_file(layer).read_text(encoding="utf-8")
        for raw in json.loads(text)["targets"]:
            if target_fields_present(raw) == 0:
                continue                      # rekord-NAZWA: zna go resolver, planer nie
            out.append(_target(raw, layer))
    return tuple(out)


def _target(raw, layer):
    """Rekord → `Target` z koercją. Pola OBOWIĄZKOWE (`c`/`t`/`r`/`d`/`a`) po koercji nie mogą być
    puste — plik człowieka pisze człowiek, a cel bez rozmiaru albo bez typu przeszedłby przez pół
    planera i wysypał się dopiero na kadrowaniu, daleko od przyczyny (EXPECT)."""
    fields = {"canon": _to_text(raw.get("c")), "type": _to_text(raw.get("t")),
              "ra_deg": _to_float(raw.get("r")), "dec_deg": _to_float(raw.get("d")),
              "major_arcmin": _to_float(raw.get("a"))}
    missing = sorted(k for k, v in fields.items() if v is None)
    if missing:
        raise ValueError(f"targets: rekord warstwy {layer!r} bez pól {missing} "
                         f"(kanon={raw.get('c')!r}) — asset jest niepełny")
    return Target(minor_arcmin=_to_float(raw.get("b")), mag=_to_float(raw.get("m")),
                  mag_from_b=bool(raw.get("mb")), aliases=tuple(raw.get("n") or ()),
                  layer=layer, why=raw.get("why"), size_source=raw.get("size_source"), **fields)


def feasible(t, rigs=(), *, min_size=6.0, min_dark=15.0, max_mag=13.0, min_fill=None,
             max_panels=None, overlap=0.10):
    """Czy cel jest WYKONALNY wg progów typo-zależnych (D-0731-10) i, na żądanie, TWOIM SPRZĘTEM.

    Galaktyka bez magnitudo odpada (dla galaktyki jasność JEST kryterium), mgławica bez magnitudo
    przechodzi (dla niej magnitudo kłamie). Typ spoza taksonomii odpada - patrz `GALAXY_TYPES`.

    FILTR KADRU (dług T5, PL-1, PL-2): przy niepustym `rigs` i choć jednym z progów `min_fill`/
    `max_panels` cel przechodzi, gdy JAKIKOLWIEK zestaw parku spełnia OBA progi naraz (`rig_fits`):
    kwantyfikator LUB: „mam czym to zrobić", nie „zrobi to najsłabsza optyka". Ten sam zestaw musi
    spełnić oba, bo „wypełnia 50 % w mozaice RC8" i „jeden kadr w A140R przy 8 %" nie składają się
    w cel wykonalny jednym kadrem przy 30 %. `rigs=()` (domyślnie) = brak odsiewu sprzętowego."""
    if t.major_arcmin is None:
        return False
    if t.type in DARK_TYPES:
        ok = t.major_arcmin >= min_dark
    elif t.type not in GALAXY_TYPES and t.type not in NEBULA_TYPES:
        return False                                     # unknown_type — jawnie, nie po cichu
    elif t.major_arcmin < min_size:
        return False
    elif t.type in GALAXY_TYPES:
        ok = t.mag is not None and (t.mag - B_TO_V if t.mag_from_b else t.mag) <= max_mag
    else:
        ok = True
    if not ok or not rigs or (min_fill is None and max_panels is None):
        return ok
    return any(rig_fits(_frame(t, rig, overlap), min_fill=min_fill, max_panels=max_panels)
               for rig in rigs)


def rig_fits(framing, *, min_fill=None, max_panels=None):
    """JEDYNY predykat filtra kadru: woła go pula rdzenia (`feasible`), wybór `best_rig`
    (`_framing_for`) i soczewka ekranu (`planner_model`). Brak kadrowania (zestaw bez FOV) nie
    przechodzi: „nie wiem" nie jest „mieści się". Próg `None` nie tnie."""
    if framing is None:
        return False
    if min_fill is not None and framing.frame_fill < min_fill:
        return False
    return max_panels is None or framing.panels <= max_panels


def resolve_plan_canon(needle, layers=ALL_LAYERS):
    """Wejście użytkownika → KANON KATALOGU dla kuratelii. Zwraca `(kanon, kandydaci)`.

    Trzy drogi w kolejności pewności: kanon (bez względu na wielkość liter) → alias KATALOGOWY przez
    gramatykę resolvera (`M42` → `NGC1976`) → nazwa potoczna. Nazwa potoczna bywa DWUZNACZNA
    (zmierzone w T3: „Eastern Veil" wskazuje NGC6992 **i** NGC6995), więc kolizja zwraca
    `(None, kandydaci)` — zapis kuratelii na losowym z dwóch rekordów byłby cichym wyborem za
    użytkownika. Nic nie trafione → `(None, najbliżsi po podciągu)`, żeby literówka dostała
    odpowiedź, a nie ciszę.

    Szukamy we WSZYSTKICH warstwach: cel z cirrusu wolno oznaczyć, mając wczytany rdzeń."""
    pool = load_targets(tuple(layers))
    n = str(needle or "").strip()
    if not n:
        return None, ()
    fold = n.casefold()
    hits = [t for t in pool if t.canon.casefold() == fold]
    if not hits:
        cc = catalog_canon(n)
        key = xref(cc) if cc else None
        if key:
            hits = [t for t in pool if t.canon == key or key in t.catalog_aliases]
    if not hits:
        hits = [t for t in pool if any(a.casefold() == fold for a in t.aliases)]
    canons = sorted({t.canon for t in hits})
    if len(canons) == 1:
        return canons[0], ()
    if canons:
        return None, tuple(canons)
    near = sorted({t.canon for t in pool if fold in t.canon.casefold()
                   or any(fold in a.casefold() for a in t.aliases)})
    return None, tuple(near[:5])


def plan_marks(con):
    """Kuratela z bazy: `kanon → wiersz target_plan`. JEDEN literał i JEDEN odczyt na przebieg —
    zapytanie per cel dałoby 777 zapytań na listę, którą i tak trzymamy w pamięci."""
    return {r["canon"]: r for r in con.execute(
        "SELECT canon, status, priority, note FROM target_plan").fetchall()}


# Stany oznaczenia, którego planer NIE POKAŻE — nazwane, bo każdy ma INNĄ naprawę (R-S0-7).
ORPHAN_UNKNOWN = "unknown"   # pełny katalog tej nazwy nie zna wcale → jedyna akcja: zdejmij
ORPHAN_MOVED = "moved"       # kanon żyje dziś jako alias katalogowy rekordu X → przenieś na X


def orphan_marks(con):
    """Oznaczenia kurateli, których planer nie ma jak pokazać — `{kanon: (stan, wiersz, gdzie)}`.

    JEDEN WŁAŚCICIEL PREDYKATU dla obu powierzchni (`cli._cmd_target` liczył go dotąd inline,
    w warstwie prezentacji). `plan` dokleja kuratelę przez `marks.get(t.canon)`, więc wiersz
    `target_plan` na kanonie, którego asset nie zna, jest po cichu porzucany — niewidoczny
    i nieusuwalny z GUI.

    DWA STANY, BO DWIE RÓŻNE NAPRAWY, i to jest sedno tego długu. Przebudowa assetu
    (`scripts/build_catalog.py`) nie tylko USUWA kanony — częściej je PRZENOSI: nazwa, która była
    kanonem rekordu, staje się jego `catalog_alias` albo aliasem katalogowym rekordu SĄSIEDNIEGO.
    Oznaczenie jest wtedy niewidoczne dokładnie tak samo, ale CEL ŻYJE — a sekcja, która oferuje
    w tym stanie samą kasację, namawia do utraty cudzej decyzji w jedynym realnym scenariuszu,
    który ten stan tworzy. `gdzie` niesie kanon nowego właściciela dla `moved`, `None` dla
    `unknown`.

    `ALL_LAYERS`, nie wczytane warstwy: „nie ma celu w katalogu" to co innego niż „nie wczytałem
    warstwy, w której leży" (ta sama granica, co przy `PlanResult.unmatched` — `LDN1152` siedzi
    w cirrusie i przy domyślnym rdzeniu wyglądałby na sierotę).

    Klucz `target_plan` to ZAWSZE kanon rekordu: jedyna droga zapisu prowadzi przez
    `resolve_plan_canon`, który zwraca wyłącznie `t.canon`, a `repo.set_target_plan` niczego nie
    normalizuje. Dlatego `unknown` liczy się wobec zbioru KANONÓW, a `moved` dobiera właściciela
    z `coverage_index` (kanon + aliasy katalogowe, z rozstrzygnięciem kolizji `curated`)."""
    pool = load_targets(ALL_LAYERS)
    canons = {t.canon for t in pool}
    owner = coverage_index(pool)
    out = {}
    for canon, row in plan_marks(con).items():
        if canon in canons:
            continue
        t = owner.get(canon)
        if t is None:
            out[canon] = (ORPHAN_UNKNOWN, row, None)
        else:
            out[canon] = (ORPHAN_MOVED, row, t.canon)
    return out


def coverage_index(targets):
    """Indeks „kanon archiwum → rekord katalogu": kanon rekordu + aliasy KATALOGOWE (§5).

    Kolizja w warstwach GENEROWANYCH to złamany asset (bramka T2 §7) → `AssertionError`.
    Kolizja z `curated` → curated WYGRYWA (T2 §9): plik pisze człowiek i crash byłby karą za
    edycję własnego pliku."""
    idx = {}
    for t in targets:
        for key in (t.canon,) + t.catalog_aliases:
            prev = idx.get(key)
            if prev is None or prev is t:
                idx[key] = t
                continue
            if t.layer == "curated":
                idx[key] = t
            elif prev.layer != "curated":
                raise AssertionError(
                    f"targets: kanon {key!r} w dwóch rekordach warstw generowanych "
                    f"({prev.canon}/{prev.layer} vs {t.canon}/{t.layer}) — asset złamał bramkę T2")
    return idx


# ─────────────────────────────────────────────────────── zestawy

def rig_sets(con, park=None):
    """Configi → zestawy `(teleskop, FOV)`; zwraca `(w planie, pominięte)`.

    Config z `Rig.reason` ma `fov=None`, więc NIE MA klucza grupowania — idzie do pominiętych
    z kodem powodu, nigdy do planu z domyślną matrycą („brak faktu nie jest zerem"). Reprezentanta
    remisu rozstrzyga `(-lights, config_id)`, żeby dwa przebiegi dały ten sam wynik."""
    groups, skipped = {}, []
    for r in sorted(sky.rigs(con, only=park), key=lambda r: (-r.lights, r.config_id)):
        if r.reason or r.fov_x_arcmin is None or r.fov_y_arcmin is None:
            skipped.append(RigSet(config_id=r.config_id, telescope=r.telescope,
                                  cameras=(r.camera,), mono=False, fov_x_arcmin=None,
                                  fov_y_arcmin=None, lights=r.lights,
                                  reason=r.reason or "no_fov"))
            continue
        key = (r.telescope, round(r.fov_x_arcmin, 2), round(r.fov_y_arcmin, 2))
        groups.setdefault(key, []).append(r)
    out = []
    mono = _mono_cameras(con)
    for (telescope, _fov_x, _fov_y), members in groups.items():
        head = members[0]
        cams = tuple(sorted({m.camera for m in members}))
        out.append(RigSet(config_id=head.config_id, telescope=telescope, cameras=cams,
                          mono=any(c in mono for c in cams), fov_x_arcmin=head.fov_x_arcmin,
                          fov_y_arcmin=head.fov_y_arcmin,
                          lights=sum(m.lights for m in members), reason=None))
    out.sort(key=lambda s: (-s.lights, s.telescope))
    # Dwa zestawy jednej optyki (kamery o innej matrycy) dostają etykietę z kamerami. Zbiory kamer
    # są rozłączne z konstrukcji: config to `UNIQUE(telescope_id, camera_id)` i każdy config siedzi
    # w dokładnie jednej grupie FOV - więc nazwa jest unikalna, a powierzchnie mogą nią wskazywać.
    per_telescope = {}
    for s in out:
        per_telescope[s.telescope] = per_telescope.get(s.telescope, 0) + 1
    out = [replace(s, label=f"{s.telescope} ({'/'.join(s.cameras)})")
           if per_telescope[s.telescope] > 1 else s for s in out]
    assert len({s.name for s in out}) == len(out), \
        f"targets: nazwy zestawów nie są unikalne: {[s.name for s in out]}"
    return tuple(out), tuple(skipped)


def _mono_cameras(con):
    return {r["model_canon"] for r in
            con.execute("SELECT model_canon FROM camera WHERE is_mono = 1").fetchall()}


def _frame(t, rig, overlap):
    """Kadrowanie celu `t` w zestawie `rig`: JEDNA droga do `sky.framing` dla rankingu i progu
    (SIN-DUP: filtr kadru nie liczy wypełnienia po swojemu)."""
    return sky.framing(t.major_arcmin, _rig_shim(rig), overlap=overlap,
                       minor_arcmin=t.minor_arcmin)


def _framing_for(t, rigs, overlap, *, min_fill=None, max_panels=None):
    """Kadrowanie we wszystkich zestawach + rekomendacja: jeden kadr o największym wypełnieniu,
    a gdy cel nie mieści się nigdzie - najmniejsza mozaika (D-0731-8: cel ZOSTAJE).

    Włączony filtr kadru zawęża KANDYDATÓW do `best_rig` (nie słownik `framing`: soczewka ekranu
    nadal widzi każdy zestaw). Cel przeszedł pulę, bo spełnia go któryś zestaw, więc rekomendacja
    wskazuje właśnie taki, a nie optykę, której próg nie przepuścił. Bez progów - bez zmian.

    Klucz słownika to `config_id` ZESTAWU (`TargetRow.framing_in`): teleskop z dwiema kamerami
    to dwa zestawy i dwa różne kadrowania."""
    framing, candidates = {}, []
    for rig in rigs:
        f = _frame(t, rig, overlap)
        if f is None:
            continue
        framing[rig.config_id] = f
        if (min_fill is not None or max_panels is not None) and \
                not rig_fits(f, min_fill=min_fill, max_panels=max_panels):
            continue
        candidates.append(((f.panels, -f.fill, rig.config_id), rig))
    if not candidates:
        return framing, None
    return framing, min(candidates, key=lambda p: p[0])[1]


class _rig_shim:
    """`sky.framing` czyta `fov_x_arcmin`/`fov_y_arcmin` — `RigSet` je ma, ale jako pola, nie
    właściwości `Rig`. Cienka przejściówka zamiast duplikowania arytmetyki FOV (SPOT)."""

    def __init__(self, rigset):
        self.fov_x_arcmin = rigset.fov_x_arcmin
        self.fov_y_arcmin = rigset.fov_y_arcmin


# ─────────────────────────────────────────────────────── pokrycie

def archive_coverage(con):
    """Godziny per (kanon obiektu, filtr) z archiwum + licznik lightów bez filtra na kamerze MONO.

    REUŻYWA `queries.object_exposure` (jeden właściciel faktu „SUM(exptime) per obiekt×filtr
    + jawne NULL-e") na `queries.all_frame_ids` — `object_exposure` sam filtruje `kind='light'`,
    więc drugiego literału „uniwersum lightów" nie piszemy. Grupa całkiem bez `exptime` zwraca
    `secs=NULL` → `or 0.0`.

    DRUGA OŚ FAKTU (I-2e): `queries.integrated_exposure` dokłada godziny, które weszły w gotowe
    obrazy (sub liczony RAZ mimo N:M), a `queries.stack_locations` — gdzie te obrazy leżą. Kanon
    stosu bez ANI JEDNEGO lighta zakłada WŁASNY wpis zamiast wypaść po cichu: „obraz jest, subów
    w archiwum nie ma" to znalezisko, nie szum (klatki poza biblioteką, skasowane suby), a cichy
    ubytek celu to ta sama klasa błędu co cichy sufit listy.

    Licznik `unfiltered_mono` jest STRAŻNIKIEM, nie agregatem: brak filtra na matrycy kolorowej to
    broadband (OSC zbiera RGB jednym strzałem), ale brak filtra na mono znaczy „nie wiadomo co",
    i wtedy kubełek RGB byłby zanieczyszczony. Zmierzone dziś: 0."""
    objs = {r["id"]: r["canon"] for r in con.execute("SELECT id, canon FROM object").fetchall()}
    per = {}

    def _entry(object_id):
        canon = objs.get(object_id)
        return None if canon is None else per.setdefault(
            canon, {"by_filter": {}, "n_null": 0, "integrated": {}, "stacks": []})

    for r in object_exposure(con, all_frame_ids(con)):
        entry = _entry(r["object_id"])
        if entry is None:
            continue
        key = r["filter_canon"]
        entry["by_filter"][key] = entry["by_filter"].get(key, 0.0) + (r["secs"] or 0.0) / 3600.0
        entry["n_null"] += r["n_null"] or 0
    for r in integrated_exposure(con):
        entry = _entry(r["object_id"])
        if entry is None:
            continue
        key = r["filter_canon"]
        entry["integrated"][key] = entry["integrated"].get(key, 0.0) + (r["secs"] or 0.0) / 3600.0
    for r in stack_locations(con):
        entry = _entry(r["object_id"])
        if entry is not None:
            entry["stacks"].append((r["frame_id"], r["path"]))
    unfiltered_mono = con.execute(
        "SELECT COUNT(*) FROM frame f JOIN camera c ON c.id = f.camera_id "
        "WHERE f.kind = 'light' AND f.filter_canon IS NULL AND c.is_mono = 1").fetchone()[0]
    return per, unfiltered_mono


def channel_hours(hours_by_filter):
    """Filtry → kanały. Duoband zasila Ha ORAZ OIII (dokładnie to zbiera), brak filtra idzie do
    RGB (dziś wyłącznie OSC — strażnik `unfiltered_mono`), nieznany filtr do `other` i do żadnego
    kanału: cicha przynależność do broadbandu przypisałaby celowi pokrycie, którego nie ma."""
    out = {RGB: 0.0, "Ha": 0.0, "OIII": 0.0, "SII": 0.0, "other": 0.0}
    for name, hours in hours_by_filter.items():
        if name is None or name in _BROADBAND_FILTERS:
            out[RGB] += hours
        elif name in _NARROWBAND_FILTERS:
            out[name] += hours
        elif name in _DUOBAND_FILTERS:
            out["Ha"] += hours
            out["OIII"] += hours
        else:
            out["other"] += hours
    return out


def required_channels(target_type):
    """Kanały, których brak jest LUKĄ — typo-zależnie. Galaktyka nie ma „luki w Ha"."""
    if target_type in NEBULA_TYPES and target_type != "RfN":
        return (RGB,) + NARROW_CHANNELS
    return (RGB,)


def _coverage_for(t, index_hits, min_hours):
    """Złóż `Coverage` z dopasowanych kanonów archiwum (dopasowanie jest WIELE→JEDEN: archiwum może
    mieć jednocześnie `IC410` i `LBN807`, więc godziny sumujemy, a oba kanony zostają widoczne).

    Godziny zintegrowane sumują się tą samą drogą i jest to bezpieczne dokładnie dlatego, że
    `integrated_exposure` zdjęła N:M PRZED agregacją: tu dodajemy rozłączne kanony archiwum
    (`IC410` + `LBN807`), a nie wielokrotne relacje tego samego suba.

    LUKI I RADA ZOSTAJĄ NA GODZINACH ZEBRANYCH — świadomie. „Nie zestackowałem" nie jest luką
    w materiale i nie ma prawa wysłać użytkownika po kolejne 8 h Ha, których już ma."""
    by_filter, integrated, stacks, n_null = {}, {}, [], 0
    for entry in index_hits.values():
        for name, hours in entry["by_filter"].items():
            by_filter[name] = by_filter.get(name, 0.0) + hours
        for name, hours in entry.get("integrated", {}).items():
            integrated[name] = integrated.get(name, 0.0) + hours
        stacks.extend(entry.get("stacks", ()))
        n_null += entry["n_null"]
    channels = channel_hours(by_filter)
    gaps = tuple(ch for ch in required_channels(t.type) if channels.get(ch, 0.0) < min_hours)
    return Coverage(hours_by_filter=by_filter, hours_by_channel=channels, gaps=gaps,
                    archive_canons=tuple(sorted(index_hits)), frames_no_exptime=n_null,
                    integrated_by_filter=integrated,
                    integrated_by_channel=channel_hours(integrated),
                    stacks=tuple(sorted(stacks)))


# ─────────────────────────────────────────────────────── Księżyc, rada, kolejność

def palette_costs(window):
    """Koszt czasu per paleta. `Window.moon is None` (brak nocy żeglarskiej) ⇒ 1,00 dla każdej
    palety — Księżyc naprawdę nie szkodzi, gdy nocy nie ma; `AttributeError` byłby awarią planera
    na kole podbiegunowym w czerwcu."""
    moon = getattr(window, "moon", None)
    if moon is None:
        return {name: 1.0 for name in sky.BANDS}
    return {name: moon.cost(band) for name, band in sky.BANDS.items()}


def recommend_channel(coverage, cost, rig):
    """Najtańszy dziś kanał, w którym cel ma LUKĘ i który REKOMENDOWANY ZESTAW umie zrobić.

    Zestaw mono robi kanały wąskie osobno; zestaw z matrycą kolorową może domknąć Ha/OIII wyłącznie
    duobandem (jednym strzałem), a SII jest dla niego niewykonalne. Zwraca `(kanał, powód)`."""
    if not coverage.gaps:
        return None, "no_gap"
    if rig is None:
        return None, "no_rig"
    candidates = []
    for ch in coverage.gaps:
        if ch == RGB:
            candidates.append((cost["broadband"], 0, ch))
        elif rig.mono:
            candidates.append((cost["narrowband"], 1, ch))
        elif ch in ("Ha", "OIII"):
            candidates.append((cost["duoband"], 2, ch))
    if not candidates:
        return None, "rig_cannot"
    return min(candidates)[2], None


def _fill_bucket(framing):
    """Kubełek kadru do rankingu (PL-1, wariant R2): 0 = jeden kadr wypełniony co najmniej
    w `RANK_MIN_FILL`, 1 = mozaika, 2 = jeden kadr za mały, 3 = brak kadrowania.

    Miara to `sky.Framing.frame_fill` - ta sama, którą pokazuje kolumna „Wypełn." i tnie próg
    `min_fill` (SIN-DUP: surowe `fill` przy jednym kadrze bywa > 1, bo liczy się do krótszego boku).
    Mozaika stoi PRZED celem za małym: D-0731-8 trzyma ją w wynikach jako cel wykonalny (kilka
    nocy, obraz wypełniony), a kropka w kadrze daje obraz, którego optyka nie uniesie żadną liczbą
    nocy - planer zaczyna od tego, co zestaw zrobi dobrze. Brak kadrowania idzie na koniec, jak
    w sorcie soczewki: „nie wiem" nie wygrywa z odpowiedzią."""
    if framing is None:
        return 3
    if framing.panels > 1:
        return 1
    return 0 if framing.frame_fill >= RANK_MIN_FILL else 2


def _sort_key(row):
    """(widoczny, ma-lukę, KUBEŁEK KADRU, koszt, dłuższe okno, WYŻEJ NA NIEBIE, kanon) - każdy
    człon broni się osobno. Dwa ostatnie przed kanonem są odpowiedzią na FIRSTHAND: cel pod
    horyzontem ma uczciwe `cost=1,00` (pułapka T1), ale przy NOWIU wszystkie koszty są 1,00, luki
    ma prawie każdy cel nigdy nie fotografowany, a okno bywa równe dla setek celów okołobiegunowych
    - bez wysokości kulminacji lista degenerowała się do porządku ALFABETYCZNEGO (zmierzone: 1555
    wierszy zaczynało się od bezimiennych `G0…` Greena). Kanon zostaje ostatni, żeby dwa przebiegi
    dały ten sam plik.

    KUBEŁEK KADRU (PL-1, R2, `_fill_bucket`) stoi po luce, przed kosztem: zgłoszenie Zdzinia
    2026-09-27 - `Sh2-85` (ok. 9 % kadru A140R) stał w szóstce, bo wypełnienie nie wchodziło do
    klucza. Liczony dla `best_rig` (jak kolumna „Wypełn."), nie dla soczewki ekranu: jeden klucz
    rdzenia daje tę samą kolejność w `horreum plan` i w GUI. Kubełki, nie ciągła miara - wewnątrz
    kubełka nadal rządzi Księżyc i niebo, wypełnienie nie wypycha tańszej nocy.

    Cel domknięty nie ma prawa wygrywać z czekającym - bez rekomendacji bierzemy MAKSIMUM kosztu."""
    if row.recommend is not None:
        cost_key = row.cost[PALETTE_OF_CHANNEL[row.recommend]]
    else:
        cost_key = max(row.cost.values())
    return (not row.window.visible, 0 if row.coverage.gaps else 1,
            _fill_bucket(row.framing_in(row.best_rig)), cost_key,
            -row.window.hours_above, -row.window.max_alt_deg, row.target.canon)


# ─────────────────────────────────────────────────────── noc

def default_night(site, *, now=None, step_min=5):
    """Wieczór, który ma sens TERAZ. Doba lokalna liczona z DŁUGOŚCI GEOGRAFICZNEJ stanowiska
    (`now_utc + lon/15 h`), nie ze strefy maszyny — maszyna w UTC przesunęłaby plan o dobę.

    Gdy ciemność wieczoru D−1 jeszcze trwa, planujemy TĘ noc (o 02:00 użytkownik siedzi przy
    teleskopie, nie planuje jutra); inaczej dzisiejszy wieczór."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = now + timedelta(hours=site.lon_deg / 15.0)
    today = local.date()
    prev = sky.night_window(site, today - timedelta(days=1), step_min=step_min)
    if prev.dark_end is not None and prev.dark_end > now:
        return today - timedelta(days=1)
    return today


# ─────────────────────────────────────────────────────── plan

def plan(con, *, night=None, site=None, park=None, layers=DEFAULT_LAYERS,
         min_size=6.0, min_dark=15.0, max_mag=13.0, min_alt=30.0, min_hours=1.0,
         max_cost=None, overlap=0.10, v_zen=sky.V_ZEN_DEFAULT, k_ext=sky.K_EXT_DEFAULT,
         only_gaps=False, only_new=False, status=None, find=None, limit=None, step_min=5,
         min_fill=None, max_panels=None):
    """Pełna odpowiedź planera dla jednej nocy (READ-ONLY).

    KOLEJNOŚĆ JEST KOLEJNOŚCIĄ KOSZTU: progi typo-zależne (arytmetyka) → filtr kadru na żądanie
    (arytmetyka, `min_fill`/`max_panels`) → przedcięcie deklinacją → okno widoczności (jedyny drogi
    krok, po jednej siatce Słońca na całą noc) → kadrowanie → pokrycie → koszt → sortowanie.

    FILTR KADRU zmienia ZNACZENIE licznika `counts['feasible']` z „wykonalne w ogóle" na
    „wykonalne twoim sprzętem" (powierzchnie zmieniają napis razem z nim, `rig_filter == 'on'`),
    a `counts['hidden_by_rig']` mówi, ile celów schował - odsiew nie ma prawa wyglądać jak ubogi
    katalog. Klucz istnieje WYŁĄCZNIE przy włączonym filtrze: domyślna odpowiedź zostaje bit
    w bit ta sama. Filtr kurczy pulę, porządku nie zmienia: kubełek kadru w `_sort_key` (PL-1)
    działa zawsze, z progami i bez nich, dla `best_rig`.

    `find` ma semantykę WYSZUKIWANIA, nie filtra wyniku: pomija progi i przedcięcie (pytasz
    o konkretny obiekt — masz dostać jego okno, nawet gdy nigdy nie wschodzi) i dopasowuje po
    kanonie ORAZ po WSZYSTKICH aliasach, także potocznych. To jedyne miejsce, gdzie nazwa potoczna
    ma głos: „Eagle Nebula" zwróci OBA rekordy, które ją noszą.

    KURATELA (T4): `park=None` bierze park z bazy (`sky.park`); jawna lista go BIJE, bo wołanie
    jest silniejsze niż stan trwały. Cel oznaczony `skip` znika z listy Z LICZNIKIEM
    (`counts['hidden_by_status']`) — ale nie znika przed `find` ani przed jawnym `status='skip'`:
    własne skreślenie nie ma prawa zasłonić odpowiedzi na pytanie wprost. `done` NIE ukrywa —
    cel domknięty w Ha może mieć lukę w SII i planer ma prawo to pokazać."""
    site = site or sky.default_site(con)
    if site is None:
        raise ValueError("targets: baza nie ma stanowiska z pozycją GPS — planer bez pozycji "
                         "obserwatora nie ma czego liczyć (podstawienie 'środka Polski' byłoby "
                         "kłamstwem)")
    night_date = night or default_night(site, step_min=step_min)
    nw = sky.night_window(site, night_date, step_min=step_min)

    targets = load_targets(tuple(layers))
    owner = coverage_index(targets)          # kanon -> rekord WŁAŚCICIEL (curated wygrywa)
    per_canon, unfiltered_mono = archive_coverage(con)
    marks = plan_marks(con)

    # Park: jawny argument BIJE bazę; brak oznaczeń w bazie => wszystkie teleskopy (zachowanie
    # sprzed T4) i `park_source='none'`, żeby powierzchnia mogła to powiedzieć wprost.
    park_source = "arg" if park is not None else "none"
    if park is None:
        park = sky.park(con)
        park_source = "db" if park else "none"
    rigs, skipped = rig_sets(con, park=park)
    known_rigs = {r.telescope for r in rigs} | {r.telescope for r in skipped}
    park_without_rigs = tuple(sorted(c for c in (park or ()) if c not in known_rigs))

    # Filtr kadru działa WYŁĄCZNIE na parku wypowiedzianym przez użytkownika i z realnym zestawem:
    # park nieustawiony = wszystkie teleskopy bazy, także historyczne, a „mam czym" po sprzęcie,
    # którego dawno nie ma, nie odcięłoby uczciwie niczego. `find` pomija progi, więc i ten.
    if min_fill is None and max_panels is None:
        rig_filter = "off"
    elif find:
        rig_filter = "find"
    elif park_source == "none":
        rig_filter = "no_park"
    elif not rigs:
        rig_filter = "no_rigs"
    else:
        rig_filter = "on"
    fit = {"min_fill": min_fill, "max_panels": max_panels} if rig_filter == "on" else {}

    if find:
        needle = find.casefold()
        pool = [t for t in targets
                if needle in t.canon.casefold()
                or any(needle in a.casefold() for a in t.aliases)]
        after_thresholds = len(pool)
    else:
        pool = [t for t in targets
                if feasible(t, min_size=min_size, min_dark=min_dark, max_mag=max_mag)]
        after_type = len(pool)
        if fit:
            pool = [t for t in pool
                    if feasible(t, rigs, min_size=min_size, min_dark=min_dark, max_mag=max_mag,
                                overlap=overlap, **fit)]
        after_thresholds = len(pool)
        pool = [t for t in pool
                if 90.0 - abs(site.lat_deg - t.dec_deg) >= min_alt - _CUT_MARGIN]

    rows, hidden_by_status = [], 0
    for t in pool:
        # Kuratela ROZSTRZYGA PRZED rachunkiem nieba (najdroższym krokiem): cel skreślony nie ma
        # po co przechodzić przez siatkę Słońca. `find` i jawny `status` przebijają ukrycie.
        mark = marks.get(t.canon)
        mark_status = mark["status"] if mark is not None else None
        if status is not None:
            if mark_status != status:
                continue
        elif mark_status == "skip" and not find:
            hidden_by_status += 1
            continue
        window = sky.visibility_window(t.ra_deg, t.dec_deg, site, night_date, min_alt=min_alt,
                                       step_min=step_min, v_zen=v_zen, k_ext=k_ext, night=nw)
        # WŁAŚCICIEL kanonu bierze godziny: gdy `curated` przejmie klucz rekordu generowanego,
        # te same klatki nie mają prawa policzyć się w dwóch wierszach
        hits = {c: per_canon[c] for c in (t.canon,) + t.catalog_aliases
                if c in per_canon and owner.get(c) is t}
        coverage = _coverage_for(t, hits, min_hours)
        if only_gaps and not coverage.gaps:
            continue
        if only_new and coverage.known:
            continue
        framing, best = _framing_for(t, rigs, overlap, **fit)
        cost = palette_costs(window)
        channel, reason = recommend_channel(coverage, cost, best)
        if max_cost is not None and channel is not None and \
                cost[PALETTE_OF_CHANNEL[channel]] > max_cost:
            continue
        rows.append(TargetRow(target=t, window=window, framing=framing, best_rig=best,
                              coverage=coverage, cost=cost, recommend=channel,
                              recommend_reason=reason, plan_status=mark_status,
                              priority=mark["priority"] if mark is not None else None,
                              note=mark["note"] if mark is not None else None))
    # Priorytet użytkownika NIE wchodzi do klucza sortowania (D-T4-c ROZSTRZYGNIĘTE 2026-07-31,
    # GO Zdzinia - domyślna utrzymana): człony `_sort_key` wywalczył firsthand T3 (kubełek kadru
    # dołożyła decyzja PL-1 R2), a priorytet
    # przed „widoczny" postawiłby na czele cel pod horyzontem. Priorytet zostaje kolumną i filtrem;
    # ewentualny przełącznik porządku to sort WTÓRNY w widoku, nie zmiana tego klucza.
    rows.sort(key=_sort_key)
    # liczniki opisują NOC, nie wyświetloną listę — dlatego przed limitem (firsthand: „12 widocznych"
    # przy `--limit 12` opisywało długość ekranu, nie niebo)
    counts = {"pool": len(targets), "feasible": after_thresholds, "above_horizon": len(pool),
              "matched": sum(1 for r in rows if r.coverage.known),
              "visible": sum(1 for r in rows if r.window.visible), "rows": len(rows),
              "marked": sum(1 for r in rows if r.plan_status is not None),
              "hidden_by_status": hidden_by_status}
    if fit:
        counts["hidden_by_rig"] = after_type - after_thresholds
    hidden = 0
    if limit is not None and len(rows) > limit:
        hidden = len(rows) - limit
        rows = rows[:limit]

    # RESZTA liczy się wobec CAŁEGO katalogu, nie wobec wczytanych warstw: „nie ma celu w katalogu"
    # to co innego niż „nie wczytałem warstwy, w której leży" (LDN1152 siedzi w cirrusie, a przy
    # domyślnym rdzeniu trafiłby do reszty i wyglądał na godziny bez celu)
    matched = set()
    for t in load_targets(ALL_LAYERS):
        matched.update(c for c in (t.canon,) + t.catalog_aliases if c in per_canon)
    unmatched = {c: sum(e["by_filter"].values()) for c, e in per_canon.items() if c not in matched}

    return PlanResult(rows=tuple(rows), night_date=night_date, site=site, night=nw,
                      moon=_night_moon(site, nw, v_zen=v_zen, k_ext=k_ext),
                      rigs=rigs, skipped_rigs=skipped, unmatched=unmatched, counts=counts,
                      unfiltered_mono=unfiltered_mono, hidden=hidden,
                      park=tuple(park or ()), park_source=park_source,
                      park_without_rigs=park_without_rigs,
                      orphan_marks=orphan_marks(con),
                      min_fill=min_fill, max_panels=max_panels, rig_filter=rig_filter)


def _night_moon(site, nw, *, v_zen, k_ext):
    """Księżyc dla NAGŁÓWKA (fazę i wysokość ma sam Księżyc, niezależnie od celu) w środku
    ciemności. `moon_state` wymaga celu, więc podajemy kierunek zenitu — z wyniku czytamy WYŁĄCZNIE
    `illumination` i `alt_deg`; separacja i koszt opisywałyby wtedy zenit, nie cel, i do nagłówka
    nie wchodzą. Nagłówek nie może pochodzić z pierwszego wiersza: przy pustej liście nie byłoby
    z czego go wypisać."""
    idx = nw.dark_idx[len(nw.dark_idx) // 2] if nw.dark_idx else len(nw.samples) // 2
    return sky.moon_state(0.0, site.lat_deg, site, nw.samples[idx], v_zen=v_zen, k_ext=k_ext)
