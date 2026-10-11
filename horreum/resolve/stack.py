"""Zeznanie GOTOWEGO STACKU (`master_light`) — czysta funkcja nad nagłówkiem XISF (segment I‑2a, P‑I).

Czyta to, co plik po integracji mówi SAM O SOBIE: fakty nagłówka (obiekt/filtr/czas/teleskop),
OKNO CZASU stacku (`DATE-OBS`…`DATE-END`) oraz — gdy jest — listę wejść z własności
`PixInsight:ProcessingHistory`. Zero DB, zero Qt, zero dostępu do plików (wzorzec `resolve.recipe`):
wołający podaje słownik nagłówka i tekst XML, dopasowanie do klatek archiwum robi warstwa wyżej.

NAZWA PRZED OKNEM, okno jako zapas. Nazwy w historii wskazują dysk roboczy i konwencję WBPP
(`CTB 1_LIGHT_GRP-MM20250823_FILTER-H_600.00s_0012_…_c_r.xisf`): rdzeń przed dopiskami WBPP to nazwa
lightu Z CHWILI OBRÓBKI. Wobec nazw BIEŻĄCYCH archiwum milczy (0/36 - Custos przemianował pliki
po obróbce), ale z dawnymi nazwami (`light_name_alias`, zapis przenosin Custos) daje pełny zbiór
dla 28 z 33 stosów rangi `history`, 28/28 zgodnie ze zbiorem z temperatur (sonda 2026-10-11). Tam,
gdzie nazwy milczą, zeznaniem, które przeżyło obie konwencje, jest CZAS: `DATE-OBS` mastera to
początek pierwszego suba, `DATE-END` koniec ostatniego (zgadza się co do milisekundy). Rdzeń nazwy
(`raw_stem`, `match_stem`, `wbpp_core`) mieszka tutaj, bo pytają o niego dwie drogi - żniwa
(nazwy wydania) i rodowód stosów (nazwy archiwum) - i reguła ma mieć jednego właściciela.

TRZY PUŁAPKI, KAŻDA ZMIERZONA NA REALNYCH PLIKACH — i dlatego zakodowane, nie opisane:

1. **Okno bywa ZDEGENEROWANE** (`DATE-END == DATE-OBS + EXPTIME`, czyli nagłówek opisuje JEDNĄ
   klatkę, nie stack) — **23 z 84** masterów starszego rocznika obróbki. Bez `degenerate` okno
   wybrałoby jeden sub zamiast kilkudziesięciu i wyglądałoby wiarygodnie. Cicha nieprawda jest
   gorsza niż brak odpowiedzi (D‑P‑I‑2), więc taki stack ma NIE dostać relacji.
2. **Historia ma DWIE tabele `<tr>`** — `images` (wejścia) i `imageData` (wagi, odrzucone piksele).
   Parser MUSI zawęzić się do `images`; sonda, która tego nie zrobiła, naliczyła 36 nieistniejących
   „klatek odrzuconych".
3. **Nazwy WBPP mają DWA warianty** — z temperaturą (`_0012_2.98_0.56_-10.00C_c_r`) i bez niej
   (`_1008_c_r`). Gdy nazwy nie trafiają archiwum, temperatura jest jedynym atrybutem różnicującym,
   jakim da się sprawdzić TOŻSAMOŚĆ zbioru (a nie sam licznik), więc nazwy nieczytelne liczymy
   osobno - patrz `inputs_contained`. Temperatura w nazwie suba to przypadek konwencji (D-1011-3),
   dlatego stoi PO nazwie, nie przed nią.

Rodzaj klatki rozpoznaje `resolve.frames` (IMAGETYP `Master Light` → `master_light`, zmierzone
85/85); ten moduł go NIE dubluje.
"""
import html
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from ..naming import header_dt
from ._coerce import _to_float, _to_int

# Okno krótsze niż tyle ekspozycji uznajemy za zeznanie o JEDNEJ klatce, nie o stacku (pułapka 1).
# Dwie, nie jedna: przy dwóch subach realny span == 2× exptime i taki stack też nie niesie
# informacji odróżniającej go od pojedynczej klatki.
DEGENERATE_SPAN_FACTOR = 2

_HISTORY_PROPERTY = "PixInsight:ProcessingHistory"
_SIGNATURE_RX = re.compile(
    r'<Property id="PCL:Signature:Integration"[^>]*>([^<]*)</Property>')
# `XISF:CreationTime` (AR-10): moduł XISF zapisuje go jako `String` w treści elementu (zmierzone
# na 1.0.13 i 1.1.3); typ `TimePoint` trzymałby wartość w atrybucie `value=` - oba kształty łapiemy.
_CREATION_RX = re.compile(
    r'<Property id="XISF:CreationTime"(?:[^>]*?value="([^"]*)"[^>]*/>|[^>]*>([^<]*)</Property>)')
_IMAGES_TABLE_RX = re.compile(r'<table id="images" rows="(\d+)"')
_ROW_RX = re.compile(r"<tr>(.*?)</tr>", re.S)
_PATH_RX = re.compile(r'<td id="path">([^<]*)</td>')
_DRIZZLE_RX = re.compile(r'<td id="drizzlePath">([^<]*)</td>')
_ENABLED_RX = re.compile(r'<td id="enabled" value="(true|false)"')
# Nazwa WBPP: `…_<indeks>_<HFR>_<ekscentryczność>_<temperatura>C_c_r.xisf` (wariant pełny).
_WBPP_TEMP_RX = re.compile(r"_(\d{3,5})_[\d.]+_[\d.]+_(-?[\d.]+)C_")


@dataclass(frozen=True)
class StackInput:
    """Jedno wejście deklarowane przez historię. Katalog z `path` wskazuje dysk roboczy WBPP i jest
    martwy; NAZWA pliku niesie rdzeń nazwy lightu z chwili obróbki - klucz dopasowania po nazwie
    (`inputs_by_name`) wobec nazw archiwum i ich aliasów."""
    path: str
    enabled: bool
    has_drizzle: bool
    set_temp_c: object = None      # z nazwy WBPP; None dla drugiego wariantu nazwy (pułapka 3)


@dataclass(frozen=True)
class StackTestimony:
    """Co stack mówi o sobie. `rows`/`inputs` puste ⇒ plik nie niesie historii (zmierzone: 81 z 85)
    i jedynym materiałem zostaje okno."""
    object_raw: object = None
    filter_raw: object = None
    telescop: object = None
    instrume: object = None
    exptime: object = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    rows: object = None            # ile wejść DEKLARUJE historia; None = historii brak
    inputs: tuple = ()
    tool: object = None            # np. „process=ImageIntegration,version=1.7.1,timestamp=…"
    created: object = None         # `XISF:CreationTime` - chwila zapisu pliku (`creation_time`)

    @property
    def window_span_s(self):
        """Długość okna w sekundach; None, gdy któregokolwiek końca brak."""
        if self.window_start is None or self.window_end is None:
            return None
        return (self.window_end - self.window_start).total_seconds()

    @property
    def degenerate(self):
        """Czy okno opisuje pojedynczą klatkę zamiast stacku (pułapka 1). Brak okna albo brak
        czasu ekspozycji też jest `True` — nie mamy wtedy czym ograniczyć doboru klatek."""
        span, exp = self.window_span_s, _to_float(self.exptime)
        if span is None or not exp:
            return True
        return span <= DEGENERATE_SPAN_FACTOR * exp

    @property
    def declared_temps(self):
        """Wielozbiór temperatur z CZYTELNYCH nazw wejść — materiał testu tożsamości."""
        return [i.set_temp_c for i in self.inputs if i.set_temp_c is not None]

    @property
    def unreadable_inputs(self):
        """Ile nazw wejść nie niesie temperatury (drugi wariant nazwy) — tyle wolno oknu mieć
        NADWYŻKI, żeby zbiory nadal się domykały."""
        return sum(1 for i in self.inputs if i.set_temp_c is None)


def parse_history(xml_text):
    """`(rows, inputs, tool)` z własności `PixInsight:ProcessingHistory`; `(None, (), None)`,
    gdy własności nie ma ALBO trzyma ją blok danych (`location=`, dozwolone dla String, spec XISF
    §11.1.6) - tej postaci parser tekstowy nie czyta; zmierzone 2026-09-26: historia jako tekst
    w 100% plików, które ją niosą. `PixInsight:` to przestrzeń dostawcy, nie spec (standardem jest
    `Processing:History`, §11.5.3.6). Treść jest w XML‑u zaescape'owana — rozpakowujemy ją przed
    parsowaniem.

    Zakres wierszy ZAWĘŻONY do tabeli `images` (pułapka 2): `imageData` niesie własne `<tr>`
    i własne `enabled`, więc parser bez zawężenia melduje odrzucone wejścia, których nie ma."""
    if not xml_text:
        return None, (), None
    i = xml_text.find(_HISTORY_PROPERTY)
    if i < 0:
        return None, (), _signature(xml_text)
    end = xml_text.find("</Property>", i)
    hist = html.unescape(xml_text[i:end if end > 0 else len(xml_text)])
    m = _IMAGES_TABLE_RX.search(hist)
    if m is None:
        return None, (), _signature(xml_text)
    blok = hist[m.end():]
    koniec = blok.find("</table>")
    if koniec >= 0:
        blok = blok[:koniec]
    inputs = []
    for wiersz in _ROW_RX.findall(blok):
        p = _PATH_RX.search(wiersz)
        if p is None:
            continue
        e = _ENABLED_RX.search(wiersz)
        t = _WBPP_TEMP_RX.search(p.group(1))
        inputs.append(StackInput(
            path=p.group(1),
            enabled=(e is None or e.group(1) == "true"),
            has_drizzle=bool(_DRIZZLE_RX.search(wiersz)),
            set_temp_c=_to_float(t.group(2)) if t else None,
        ))
    return _to_int(m.group(1)), tuple(inputs), _signature(xml_text)


def _signature(xml_text):
    m = _SIGNATURE_RX.search(xml_text or "")
    return m.group(1).strip() if m else None


def creation_time(xml_text):
    """`XISF:CreationTime` z nagłówka XML - surowy napis ISO jak w pliku albo `None`.

    Chwila, w której PixInsight ZAPISAŁ plik - dla stosu prosto spod integracji (WBPP zapisuje go
    zaraz po niej: na lokalnych kopiach `CreationTime` stoi ~2 min po sygnaturze integracji). To
    jedyna data stosów sprzed modułu XISF 1.1.2, które sygnatury nie mają (AR-10); własność pisze
    już moduł 1.0.13. Nie jest datą pliku w systemie plików: zapis nagłówka w miejscu przez Horreum
    podmienia wartości kart, a tej własności nie dotyka. Brak własności, pusta wartość albo brak
    tekstu (FITS) → `None` - brak faktu nie udaje faktu."""
    m = _CREATION_RX.search(xml_text or "")
    if m is None:
        return None
    wartosc = html.unescape(m.group(1) if m.group(1) is not None else m.group(2)).strip()
    return wartosc or None


def signature_timestamp(tool):
    """Chwila przebiegu integracji z sygnatury `PCL:Signature:Integration` - albo `None`.

    Ten moduł czyta sygnaturę z pliku (`_signature`), więc tu mieszka też JEJ FORMAT: pary
    `klucz=wartość` rozdzielone przecinkiem (`process=ImageIntegration,version=1.7.1,
    timestamp=2026-02-21T12:43:42.945Z`). Druga siedziba tej wiedzy - perspektywa „Wersje stosów",
    która pokazuje datę integracji obok każdej wersji - rozjechałaby się z pierwszą przy pierwszej
    zmianie formatu u dostawcy.

    Zwraca surowy napis znacznika czasu (ISO, jak w pliku), bez interpretacji strefy: sygnatura
    pisze UTC z sufiksem `Z`, a powierzchnia potrzebuje go do porządku i do pokazania, nie do
    arytmetyki. Sygnatura bez pola `timestamp`, pusta albo `None` → `None` (brak faktu nie udaje
    faktu). Własność zapisuje moduł XISF od 1.1.2 - starsze stosy mają `tool` NULL."""
    if not tool:
        return None
    for czlon in str(tool).split(","):
        klucz, _, wartosc = czlon.partition("=")
        if klucz.strip() == "timestamp" and wartosc.strip():
            return wartosc.strip()
    return None


class History(tuple):
    """Historia stosu z jednego odczytu nagłówka: krotka `(rows, inputs, tool)` jak `parse_history`
    plus atrybut `created` (`XISF:CreationTime`). Krotka, nie nowa klasa danych, bo `ScanRecord.history`
    ma już konsumentów, którzy ją rozpakowują i indeksują (`rows, inputs, tool = rec.history`,
    `rec.history[0]`); data powstania jedzie obok, bo należy do tego samego odczytu, a bez niej
    historia z bazy gubiłaby `integration.creation_time` stosów zeskanowanych po migracji 0034.
    Równość porównuje samą krotkę - data nie jest częścią zeznania o wejściach."""

    def __new__(cls, rows, inputs, tool, created=None):
        self = super().__new__(cls, (rows, tuple(inputs), tool))
        self.created = created
        return self


def read_history(xml_text):
    """`History` z tekstu XML nagłówka: `parse_history` + `creation_time` z TEGO SAMEGO tekstu."""
    return History(*parse_history(xml_text), created=creation_time(xml_text))


def read_testimony(header, xml_text=None, *, history=None):
    """Słownik nagłówka (klucze jak karty FITS) + tekst XML → `StackTestimony`.

    `header` przychodzi z `scan.header_dict_from_cards` — ten moduł nie czyta plików. Czas idzie
    przez `naming.header_dt` (SPOT), NIGDY przez porównywanie stringów: master zapisuje
    `…02.608`, a klatka `…02.6075262`, więc porządek leksykalny gubi pierwszy sub okna.

    `history` (`History`) zastępuje tekst XML, gdy historię zna już baza (`stack_history`, AR-87):
    przebieg rodowodu nie czyta wtedy nagłówka z udziału. Podane oba - wygrywa `history`."""
    h = {str(k).upper(): v for k, v in (header or {}).items()}
    if history is None:
        history = read_history(xml_text)
    rows, inputs, tool = history
    return StackTestimony(
        object_raw=h.get("OBJECT"), filter_raw=h.get("FILTER"),
        telescop=h.get("TELESCOP"), instrume=h.get("INSTRUME"),
        exptime=h.get("EXPTIME"),
        window_start=header_dt(h.get("DATE-OBS")), window_end=header_dt(h.get("DATE-END")),
        rows=rows, inputs=inputs, tool=tool, created=getattr(history, "created", None),
    )


def inputs_contained(testimony, window_temps):
    """BRAMKA TOŻSAMOŚCI (nie licznika) — czy klatki, które stack deklaruje, mieszczą się w zbiorze
    wybranym oknem? `window_temps` = temperatury klatek dobranych z archiwum.

    Zwraca `(ok, poza_oknem, nadwyzka)`. `ok` wymaga DWÓCH rzeczy naraz: żadne deklarowane wejście
    nie leży poza oknem ORAZ nadwyżka okna równa się liczbie nazw nieczytelnych — inaczej okno
    „domyka się" przypadkiem, biorąc obcą klatkę w miejsce właściwej.

    Sam licznik (`rows == len(window)`) tej własności NIE dowodzi i był pierwotną wadą projektu:
    dwa różne zbiory tej samej liczności przechodzą go bez mrugnięcia.

    Temperatury zaokrąglamy do 2 miejsc PO OBU stronach — z nazwy przychodzi `-10.00`, z nagłówka
    `-10.0000001`, a równość floatów bez zaokrąglenia rozjechałaby wielozbiory."""
    dekl = Counter(round(float(t), 2) for t in testimony.declared_temps)
    okno = Counter(round(float(t), 2) for t in window_temps if t is not None)
    poza = dekl - okno
    nadwyzka = sum((okno - dekl).values())
    return (not poza and nadwyzka == testimony.unreadable_inputs), dict(poza), nadwyzka


# ============================================================ tożsamość wejść po NAZWIE (AR-108)

# Końcowe dopiski WBPP po rdzeniu nazwy lightu: `_c` kalibracja, `_cc` korekcja kosmetyczna, `_d`
# debayer, `_r` rejestracja, `_b`/`_g`/`_a` kanały i warianty. Zdejmowane PO OBU stronach (nazwa
# z historii i nazwa z archiwum), więc reguła jest symetryczna; dopiski w środku nazwy zostają.
_WBPP_TAIL_RX = re.compile(r"(?:_(?:c|cc|d|r|b|g|a))+$")


def raw_stem(path):
    """Rdzeń nazwy pliku: basename bez rozszerzenia, małymi literami, nic więcej. Separatory `/`
    i `\\` oba (historia PixInsighta pisze ścieżki z `/`, archiwum z `\\`). Strona ARCHIWUM nie
    zdejmuje `_c`: nazwa surowego pliku nigdy nie niesie dopisku WBPP, więc surowy `…_c.fits` jest
    własną nazwą klatki, a jego wejście w historii to `…_c_c.xisf` (`harvest.input_stem` zdejmie
    jedno `_c` i trafi)."""
    return os.path.splitext(re.split(r"[\\/]", str(path))[-1])[0].lower()


def match_stem(stem, index):
    """Trafienia rdzenia wejścia w nazwy z indeksu: wpisy `L`, dla których
    `re.fullmatch(re.escape(L) + r"_c(?:_.*)?", stem)` - wejście to nazwa lightu + `_c` (kalibracja WBPP)
    i dalsze kroki po `_` (`_c_r`, `_c_d_r`). Liczone po pozycjach `_c` w rdzeniu wejścia, nie po
    wszystkich nazwach indeksu: `L` jest prefiksem rdzenia ucięciem tuż przed takim `_c`. Wejście
    `a_crop_c_r` NIE trafia w light `a` (po `_c` stoi `r`, nie `_`). Wartości indeksu to zbiory
    (dowolnych elementów - żniwa trzymają `(zestaw, frame_id)`, rodowód sam `frame_id`)."""
    hits = set()
    for i in range(len(stem) - 1):
        if stem[i:i + 2] == "_c" and (i + 2 == len(stem) or stem[i + 2] == "_"):
            hits |= index.get(stem[:i], set())
    return hits


def wbpp_core(stem):
    """Rdzeń bez KOŃCOWYCH dopisków WBPP (`_WBPP_TAIL_RX`) - luźniejsza siostra `match_stem` dla
    wejść bez `_c` (stos z lightów nieskalibrowanych: `…_-10.00C_r`). Zmierzone 2026-10-11: dokłada
    3 stosy NGC6992 (18 wejść) do 24 trafionych `match_stem`, zero trafień wielokrotnych."""
    return _WBPP_TAIL_RX.sub("", stem)


@dataclass(frozen=True)
class NameIndex:
    """Indeks nazw lightów → klatki, w dwóch kluczach: `by_stem` (`raw_stem` nazwy, pod `match_stem`)
    i `by_core` (`wbpp_core` rdzenia). Wartości: zbiory (rodowód - `frame_id`, żniwa - `(zestaw,
    frame_id)`); rdzeń przy dwóch wartościach znaczy „nazwa niejednoznaczna” i jest odmową, nie
    wyborem. JEDNA reguła tożsamości wejścia dla rodowodu stosów i żniw (`hits`).

    `by_core` POWSTAJE WYŁĄCZNIE Z NAZW, POD KTÓRYMI WBPP DOSTAŁ LIGHTY (`dawne`: aliasy, dawne
    ścieżki, nazwy z manifestu wydania), nie z bieżących nazw archiwum (`biezace`). Nazwa
    akwizycyjna bywa zakończona tokenem, który `wbpp_core` uznałby za dopisek WBPP (filtr Clear
    `…_C`): ścięta trafiałaby do kubełka sąsiedniej klatki bez tego tokenu, a unia w `hits`
    zamieniałaby dokładne trafienie `match_stem` w fałszywą niejednoznaczność."""
    by_stem: dict
    by_core: dict

    @classmethod
    def build(cls, biezace=(), dawne=()):
        """`biezace`/`dawne` = pary `(wartość, rdzeń)` - rdzeń JUŻ policzony `raw_stem`. Drugi
        `raw_stem` na rdzeniu byłby błędem, nie no-opem: nazwy WBPP niosą kropki
        (`_600.00s_0000_3.10_0.79_-10.00c`), a `splitext` ucięłby je jak rozszerzenie."""
        by_stem, by_core = {}, {}
        for wartosc, s in biezace:
            if s:
                by_stem.setdefault(s, set()).add(wartosc)
        for wartosc, s in dawne:
            if s:
                by_stem.setdefault(s, set()).add(wartosc)
                by_core.setdefault(wbpp_core(s), set()).add(wartosc)
        return cls(by_stem, by_core)

    def hits(self, path):
        """Wartości, w które trafia wejście historii spod `path`: unia `match_stem` i `wbpp_core`.
        Unia, nie pierwsza niepusta: rozjazd obu reguł (każda wskazuje inną klatkę) ma wyjść jako
        trafienie wielokrotne, a nie zostać przykryty pierwszą odpowiedzią."""
        s = raw_stem(path)
        return match_stem(s, self.by_stem) | self.by_core.get(wbpp_core(s), set())


NAMES_FULL = "full"
NAMES_PARTIAL = "partial"
NAMES_AMBIGUOUS = "ambiguous"


def inputs_by_name(inputs, index):
    """Zbiór klatek stosu z NAZW wejść historii → `(werdykt, frame_ids)`.

    Liczą się wejścia WŁĄCZONE (`enabled`): wyłączone w WBPP nie weszły w obraz. Werdykt `full` -
    każde włączone wejście trafia DOKŁADNIE jedną klatkę; `frame_ids` to wtedy posortowany zbiór
    ROZŁĄCZNY (dwa wejścia w jedną klatkę dają jedną klatkę - stos 16860, 3 wejścia w 2 klatki).
    `ambiguous` - któreś wejście trafia więcej niż jedną klatkę (odmowa jak `inputs_ambiguous`
    w żniwach, nie wybór); `partial` - któreś nie trafia nic albo włączonych wejść nie ma. Przy
    odmowie `frame_ids` puste: niepełny zbiór nie jest zbiorem wejść, a jego część nie jest
    dowodem na nic."""
    wlaczone = [i for i in inputs if i.enabled]
    if not wlaczone:
        return NAMES_PARTIAL, ()
    klatki, braki = set(), False
    for wejscie in wlaczone:
        trafione = index.hits(wejscie.path)
        if len(trafione) > 1:
            return NAMES_AMBIGUOUS, ()
        if not trafione:
            braki = True
            continue
        klatki |= trafione
    if braki:
        return NAMES_PARTIAL, ()
    return NAMES_FULL, tuple(sorted(klatki))
