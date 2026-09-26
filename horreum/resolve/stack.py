"""Zeznanie GOTOWEGO STACKU (`master_light`) — czysta funkcja nad nagłówkiem XISF (segment I‑2a, P‑I).

Czyta to, co plik po integracji mówi SAM O SOBIE: fakty nagłówka (obiekt/filtr/czas/teleskop),
OKNO CZASU stacku (`DATE-OBS`…`DATE-END`) oraz — gdy jest — listę wejść z własności
`PixInsight:ProcessingHistory`. Zero DB, zero Qt, zero dostępu do plików (wzorzec `resolve.recipe`):
wołający podaje słownik nagłówka i tekst XML, dopasowanie do klatek archiwum robi warstwa wyżej.

DLACZEGO OKNO, skoro kanon dopasowuje po faktach: nazwy w historii wskazują dysk roboczy i konwencję
WBPP (`CTB 1_LIGHT_GRP-MM20250823_FILTER-H_600.00s_0012_…_c_r.xisf`), a archiwum trzyma nazwy
z akwizycji — dopasowanie po nazwie zmierzone na realnym stacku daje **0/36**. Zeznaniem, które
przeżyło obie konwencje, jest CZAS: `DATE-OBS` mastera to początek pierwszego suba, `DATE-END`
koniec ostatniego (zgadza się co do milisekundy).

TRZY PUŁAPKI, KAŻDA ZMIERZONA NA REALNYCH PLIKACH — i dlatego zakodowane, nie opisane:

1. **Okno bywa ZDEGENEROWANE** (`DATE-END == DATE-OBS + EXPTIME`, czyli nagłówek opisuje JEDNĄ
   klatkę, nie stack) — **23 z 84** masterów starszego rocznika obróbki. Bez `degenerate` okno
   wybrałoby jeden sub zamiast kilkudziesięciu i wyglądałoby wiarygodnie. Cicha nieprawda jest
   gorsza niż brak odpowiedzi (D‑P‑I‑2), więc taki stack ma NIE dostać relacji.
2. **Historia ma DWIE tabele `<tr>`** — `images` (wejścia) i `imageData` (wagi, odrzucone piksele).
   Parser MUSI zawęzić się do `images`; sonda, która tego nie zrobiła, naliczyła 36 nieistniejących
   „klatek odrzuconych".
3. **Nazwy WBPP mają DWA warianty** — z temperaturą (`_0012_2.98_0.56_-10.00C_c_r`) i bez niej
   (`_1008_c_r`). Temperatura jest jedynym atrybutem różnicującym, jakim da się sprawdzić TOŻSAMOŚĆ
   zbioru (a nie sam licznik), więc nazwy nieczytelne liczymy osobno — patrz `inputs_contained`.

Rodzaj klatki rozpoznaje `resolve.frames` (IMAGETYP `Master Light` → `master_light`, zmierzone
85/85); ten moduł go NIE dubluje.
"""
import html
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
_IMAGES_TABLE_RX = re.compile(r'<table id="images" rows="(\d+)"')
_ROW_RX = re.compile(r"<tr>(.*?)</tr>", re.S)
_PATH_RX = re.compile(r'<td id="path">([^<]*)</td>')
_DRIZZLE_RX = re.compile(r'<td id="drizzlePath">([^<]*)</td>')
_ENABLED_RX = re.compile(r'<td id="enabled" value="(true|false)"')
# Nazwa WBPP: `…_<indeks>_<HFR>_<ekscentryczność>_<temperatura>C_c_r.xisf` (wariant pełny).
_WBPP_TEMP_RX = re.compile(r"_(\d{3,5})_[\d.]+_[\d.]+_(-?[\d.]+)C_")


@dataclass(frozen=True)
class StackInput:
    """Jedno wejście deklarowane przez historię. `path` jest MARTWA dla dopasowania po nazwie
    (dysk roboczy) — niesiemy ją jako ślad dowodowy, nie jako klucz."""
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


def read_testimony(header, xml_text=None):
    """Słownik nagłówka (klucze jak karty FITS) + tekst XML → `StackTestimony`.

    `header` przychodzi z `scan.header_dict_from_cards` — ten moduł nie czyta plików. Czas idzie
    przez `naming.header_dt` (SPOT), NIGDY przez porównywanie stringów: master zapisuje
    `…02.608`, a klatka `…02.6075262`, więc porządek leksykalny gubi pierwszy sub okna."""
    h = {str(k).upper(): v for k, v in (header or {}).items()}
    rows, inputs, tool = parse_history(xml_text)
    return StackTestimony(
        object_raw=h.get("OBJECT"), filter_raw=h.get("FILTER"),
        telescop=h.get("TELESCOP"), instrume=h.get("INSTRUME"),
        exptime=h.get("EXPTIME"),
        window_start=header_dt(h.get("DATE-OBS")), window_end=header_dt(h.get("DATE-END")),
        rows=rows, inputs=inputs, tool=tool,
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
