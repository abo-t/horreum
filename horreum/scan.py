"""Skan drzewa FITS + XISF — primitivy read-only + pętla płaska skanu (PLAN §4; §Etap 1/§Etap 4).

Per plik produkuje TOŻSAMOŚĆ + ZEZNANIE nagłówka, niczego nie zapisując:
  - odciski (przejście fitsmirror, brief §2 — port z dawcy `fits_io.py`):
      * `sha1_data` = sha1 sekcji DANYCH wybranego HDU (FITS) / bajtów attachmentu (XISF) —
        TOŻSAMOŚĆ frame'a (schemat v2): przeżywa edycję nagłówka/rename/move/writeback;
        nieobliczalny → degeneracja (sha1 całego pliku + flaga `sha1_data_uncomputable`),
      * `file_sha1` = sha1 całego pliku (fakt KOPII na location — detekcja zmiany bajtów);
        dla pliku nieskompresowanego OBA hasze liczone JEDNYM przebiegiem (`sha1_of_span` —
        pozycje sekcji z nagłówków przed odczytem treści),
      * `header_hash` = odcisk nagłówka (kontrola writeback/undo): FITS — sha1 tekstu nagłówka,
        XISF — sha1 bajtów XML (P6a),
      * `cards` = pełne lustro nagłówka (EAV: keyword/idx/value_raw/value_num/value_type/comment)
        — FITS z astropy, XISF z `<FITSKeyword>` (P6a; `value_type` zawsze `'str'`).
  - `read_header` (dyspozytor) = pełny nagłówek jako JSON-owalny dict:
      * FITS (.fits/.fit/.fts) → astropy, read-only,
      * XISF (.xisf) → lekki czytnik stdlib (`struct` + `xml.etree`), bez nowej zależności.
    To przyszłe `header.raw_json` + materiał dla pól gorących (§3.3/§3.5) — wyłuskanie należy do
    warstwy upsertu (krok §4.2). UWAGA W3: XISF zwraca wartości jako STRINGI; rzut na typ robią
    dopiero pola gorące (§Etap 2), nie ten moduł.
  - `header_dict_from_cards` (odwrotność `_parse_cards`) = synteza dict-a zeznania z kart —
    kontrakt IDENTYCZNY z `read_fits_header`; na niej stoi import z dawcy (PF-3, brief §4.2).

DOKTRYNA `.data` (R1#14): sięgnięcie po `hdul[i].data` (dekompresja pikseli) jest dozwolone
WYŁĄCZNIE dla CompImageHDU na potrzeby hasza tożsamości (`compressed_data_sha1`) — surowe bajty
sekcji danych mastera to skompresowana tabela kafelkowa, nieporównywalna między ustawieniami
kompresji. Każde inne użycie `.data` w tym module = błąd (nagłówki czytamy bez pikseli).

Żaden zapis nie idzie z tego modułu wprost: primitywy (`iter_*`/`read_*`/`scan_file`) są read-only,
a pętla `scan_tree` (§Etap 4) deleguje WSZYSTKIE zapisy do `repo` (jedna klinga) — scan.py nie
wykonuje żadnego DML (meta-tripwir AST to potwierdza). Nie zapisuje też na dysk usera (inwariant
append-only, PLAN §6): pliki otwierane WYŁĄCZNIE do odczytu. FITS przez astropy
`memmap=False` i bez sięgania po `.data`; XISF czyta tylko nagłówek (sygnatura + XML, bez bloków
danych) — więc na Windowsie nie zostaje uchwyt blokujący plik. `astropy` jest PIERWSZĄ zależnością
runtime Horreum (dochodzi z czytnikiem FITS); XISF korzysta wyłącznie ze stdlib.

Miękkie lądowanie (W1): `read_*` MOGĄ rzucać dla pliku nieczytelnego/nierozpoznanego — łapie to
`scan_file` (zwraca `ScanRecord(header=None, error=...)`, tożsamość degeneruje do `file_sha1`),
nie pętla ani użytkownik. Nierozstrzygalność trafia do `event(*.review)` w warstwie upsertu.

TOŻSAMOŚĆ ŚCIEŻEK = FORMA LITEROWA (brief §0, ŚWIĘTE od R2): ZAKAZ `os.path.realpath`/
`Path.resolve` w torze tożsamości — na zamapowanym `R:` rozwiązują do UNC (`\\\\NAS\\...`), co
rozdwaja lokacje przy tym samym `volume_serial`. Kanonizacja roota = jawna sekwencja
`canonize_root` (R3-a1); guard UNC odmawia rootów `\\\\host\\share` (R3-a2).
"""
import ctypes
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.io import fits

from . import exif, repo
from .hashing import sha1_of, sha1_of_span
from .resolve.cameras import camera_identity
from .resolve.frames import kind_from_path, normalize_kind
from .resolve.paths import STACK_KIND, STACKS_DIR
from .resolve.headers import copy_testimony, extract_header

# Rozszerzenia nagłówkonośne (PLAN §1.1: jeden mechanizm, format = opakowanie). DSLR/RAW
# (.dng/.arw/.cr2, czytnik EXIF `exif.py`) DOŁĄCZONY do JEDNEGO passa skanu (#2, D-R-3 —
# ratyfikacja Zdzinia 2026-07-23; ODWRACA dawne „drugi przebieg" z PLAN §1.5): osobny MODUŁ
# czytnika, ale WSPÓLNY `ingest_record`/tożsamość/brama przyrostowa/wykluczenia (anty-SIN-DUP).
# Dyspozycja po SUFIKSIE (`read_header`/`scan_file`/`_filetype`).
FITS_SUFFIXES = (".fits", ".fit", ".fts")
XISF_SUFFIXES = (".xisf",)
HEADER_SUFFIXES = FITS_SUFFIXES + XISF_SUFFIXES + exif.RAW_SUFFIXES

# Słowa-klucze nagłówkowe powtarzalne (komentarze/historia/puste) — akumulujemy w listę, żeby
# zeznanie było 1:1 (nie gubimy powtórzeń przez kolizję klucza w dict). Wspólne FITS↔XISF.
_MULTI_KEYWORDS = ("COMMENT", "HISTORY", "")

# SPECYFIKACJA: „XISF 1.0 Specification", Revision 1 (dokument 1.01, wrzesień 2026; poprzednie
# wydanie 1.00 z 17.04.2017). Rewizja NIE zmienia wersji formatu - sygnatura dalej `XISF0100`,
# a każdy plik zgodny z wydaniem 2017 zostaje zgodny. Nowości: kodeki zstd (§10.6.9-10), sekcja
# zgodności (§7: nieobsługiwany obiekt ma być niedostępny, reszta pliku dostępna), karty FITS bez
# dopełniania spacjami (§11.6), reguły podpisu XML (§9.5), doprecyzowane bloki skompresowane
# (§10.6.1).
# POMIAR ARCHIWUM 2026-09-26 (550 obecnych plików XISF, PixInsight 1.8.9..1.9.4, moduł XISF
# 1.0.13..1.1.3): sygnatura i reserved zgodne w 550/550, wolne miejsce zerowe w 549/549
# sprawdzalnych; nagłówek XML poprawny
# w 549/550 (jeden z bajtem sterującym - `xml_parsable`); ZERO kompresji, sum kontrolnych, podpisów
# XML i obrazów poza `attachment:`. Tego czytnik ŚWIADOMIE nie obsługuje, bo archiwum tego nie ma:
# kompresja bloku (§10.6) i `checksum` (§10.5) zmieniłyby tożsamość bez słowa, podpis XML (§9.5)
# i pozycja zapisana nie dziesiętnie (§8.3.2) spychają plik do W1, obraz `embedded` (§10.3) jest
# pomijany przy tożsamości. Populacja > 0 którejkolwiek z tych cech = sygnał do przeglądu.
_XISF_SIGNATURE = b"XISF0100"        # monolithic XISF 1.0 (§9.2); po nim uint32 LE = długość XML
_XISF_LENGTH_LEN = 4                 # uint32 LE - długość nagłówka XML
_XISF_RESERVED_LEN = 4               # 4 B reserved (§9.2: MUSZĄ być zerowe; kopiowane verbatim -
                                     # pisarz nie naprawia cudzej niezgodności)

# Bajt, na którym ZACZYNA SIĘ nagłówek XML. WYLICZONY, nigdy literał (P6/§0): pomyłka o 4 B przy
# zapisie nadpisuje pierwszy blok danych mastera. JEDNO źródło dla czytnika i pisarza XISF.
XISF_XML_OFFSET = len(_XISF_SIGNATURE) + _XISF_LENGTH_LEN + _XISF_RESERVED_LEN     # == 16

# Znaki, których XML 1.0 zabrania w treści dokumentu (wszystko poniżej spacji poza \t \n \r).
# Klasa BAJTOWA, nie znakowa, i to jest warunek poprawności: w UTF-8 żaden z tych bajtów nie
# występuje jako część sekwencji wielobajtowej (te używają 0x80-0xBF i 0xC2+), więc podmiana
# bajt-za-bajt nie tknie polskiego znaku ani nie zepsuje kodowania.
_XML_ILLEGAL_BYTES = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def xml_parsable(xml_bytes):
    """Nagłówek XISF w postaci, którą PRZYJMIE parser — znak nielegalny w XML 1.0 na spację,
    BAJT ZA BAJT. Zwraca bajty; oryginał zostaje nietknięty u wołającego.

    DLACZEGO ISTNIEJE - zdarza się plik, którego nagłówek NIE JEST poprawnym XML-em, choć spec XISF
    1.0 tego wymaga (§9.5), a zeznanie niesie zdrowe. Neutralizacja jest TOLERANCJĄ czytnika wobec
    błędu kodera, nie uznaniem pliku za zgodny ze specyfikacją. PixInsight zapisuje w nagłówku
    historię przetwarzania, a w niej ścieżki źródłowe; gdy katalog na dysku ma w nazwie bajt
    sterujący, trafia on do nagłówka WPROST i `ET.fromstring` odmawia
    całości. Zmierzone na żywym archiwum (2026-08-09): `MASTERFLAT_FLATGRP_202509210_FILTER_OIII_`
    niósł **100× U+0007** w jednej ścieżce (`…/CTB1_zbiera␇O3/…`, raz na każdą skalibrowaną klatkę)
    i był JEDYNĄ z 16 770 klatek bez nagłówka — a po neutralizacji czyta się w całości: 26 kart,
    `IMAGETYP='Master Flat'`, `FILTER='O'`, `TELESCOP='A140R'`. Odmowa opisywała nasz parser,
    nie plik, a użytkownik dostawał „kopia nieczytelna" o pliku zdrowym.

    PODMIANA JEST 1:1 CO DO DŁUGOŚCI i to nie jest kosmetyka, tylko warunek, pod którym wolno jej
    użyć w torze ŁATY: `locate_value_span` wylicza offsety bajtowe wartości i wraca z nimi do
    SUROWEGO nagłówka. Gdyby czyszczenie skracało tekst, span pokazywałby w bok o liczbę usuniętych
    bajtów i pisarz nadpisałby cudzą wartość. Spacja ma dokładnie jeden bajt — dlatego spacja.

    NEUTRALIZUJEMY WYŁĄCZNIE NA CZAS PARSOWANIA. `xml_bytes`, `header_hash` (sha1 SUROWYCH bajtów)
    i arytmetyka pisarza zostają na oryginale — inaczej tożsamość nagłówka zmieniałaby się od
    samego czytania, a plik po łacie różniłby się od siebie sprzed niej w miejscach, których nikt
    nie prosił o zmianę.

    ⚠ GRANICA, KTÓRĄ TRZEBA NAZWAĆ, BO PROZA WYŻEJ OBIECUJE WIĘCEJ, NIŻ DAJE (bramka 3a 0809,
    zarzut `kimi`): nietknięte zostają BAJTY, nie ZEZNANIE. Dict nagłówka i karty (`cards`) powstają
    z drzewa PO neutralizacji, więc wartość, która sama niosła bajt sterujący, trafi do bazy ze
    spacją w jego miejscu. W zmierzonym pliku bajty siedzą w ścieżkach historii przetwarzania, a nie
    w kartach FITS, więc dziś nie dotyczy to ani jednej wartości zeznania — ale łata szukająca
    KIEDYŚ wartości z bazy w surowych bajtach nie trafi i ma o tym wiedzieć stąd, nie z debugowania.
    Rozszerzenie (parsowanie wartości z surowych bajtów) byłoby dziś kodem na populację zero."""
    return _XML_ILLEGAL_BYTES.sub(b" ", xml_bytes)

# Katalogi-drzewa robocze wykluczane ze skanu (doktryna README §„baza = autorytet": projekcje WBPP
# to wyjście z bazy, nie wejście). JAWNA LISTA, nie konwencja `_*` — firsthand na realnym drzewie pokazał
# realne `_COMETS`/`_SOLAR` pod LIGHTS\ (1197 lightów), które konwencja porzuciłaby. Dopasowanie
# NIEWRAŻLIWE na wielkość (NTFS; realne nazwy to `_WBPP`/`_REVIEW`). Trzymamy w lowercase.
EXCLUDED_DIR_NAMES = frozenset({"_wbpp", "_review"})

# ── droga „Stosy" (I-2b, P-I / D-P-I-1 wariant A) ────────────────────────────────────────────────
# Gotowe obrazy po integracji leżą w drzewie OBRÓBKI, jawnie poza zakresem skanu archiwum
# (`horreum-scan-scope-canonical-tree`). Horreum wciąga je WŁASNĄ komendą ze wskazanym korzeniem —
# `scan_tree` i standing-op doskanu zostają NIETKNIĘTE. Odrzucone świadomie: rozszerzenie skanu
# (wciągnęłoby setki plików pośrednich obróbki, które nie są klatkami).
STACK_NAME_PREFIX = "masterlight"       # konwencja WBPP; porównanie na `name.lower()`

# Znaczniki PLIKU POCHODNEGO obróbki — granica §5 briefu P-I. Od 0810 (E4-1 wariant A+) obowiązują
# w DWÓCH drogach: w „Stosach" (całe wskazane drzewo) i w zwykłym skanie (wyłącznie poddrzewo
# `STACKS`), więc mają JEDNEGO właściciela — `is_derived_name`.
#
# TOKENY, NIE SUBSTRINGI — i to jest naprawa pułapki utajonej, nie kosmetyka. Dawne dopasowanie
# `"_abe" in name` łapie `_Abell 2151`, a `Abell` jest u nas KATALOGIEM rozpoznawanym
# (`resolve/catalog.py`). W planie przenosin 0802 Abella nie ma (0/193), więc pułapka nigdy nie
# wystrzeliła — ale sito wchodzi właśnie do drogi, którą jedzie CAŁE archiwum, a tam nazwa obiektu
# jest normalna. Token = maksymalny ciąg alfanumeryczny nazwy; `_Abell 2151` daje `abell`, `2151`
# i nie trafia w `abe`.
DERIVED_NAME_TOKENS = frozenset({"autocrop", "abe", "dbe", "spcc", "starless", "stars"})
_NAME_TOKEN_SPLIT = re.compile(r"[^0-9a-z]+")

# Próg, od którego znacznik wolno dopasować jako PRZEDROSTEK tokenu, nie tylko jako cały token.
# Wymuszony pomiarem, nie gustem (0810, 11 346 plików XISF obu drzew): PixInsight skleja kolejne
# kroki bez separatora — `SPCCBXTc`, `StarsBack`, `starsSTR` — więc sama równość tokenu przepuszcza
# 6 realnych pochodnych. Zarazem znaczniki TRZYLITEROWE (`abe`, `dbe`) są przedrostkiem prawdziwych
# słów: `Abell` to KATALOG (`resolve/catalog.py`), a odsianie klatki Abella byłoby cichą utratą
# pozycji archiwum — czyli błędem cięższym niż wciągnięcie pliku pochodnego, który i tak jest
# widoczny w siatce. Stąd asymetria: krótkie znaczniki tylko jako całe tokeny, dłuższe także jako
# przedrostek.
_DERIVED_PREFIX_MIN = 4
# Znacznik KRÓTKI z sufiksem CYFROWYM (`_ABE2`, `_DBE3`) — druga iteracja tego samego kroku
# obróbki, typowy nawyk przy powtórnym przejściu tła. Sam próg prefiksu go nie łapie (token
# `abe2` nie jest równy `abe` i jest krótszy niż próg), a `SPCC2` odsiewa — czyli sito było
# niespójne między znacznikami (bramka pakietu 3a, zarzut 7). Cyfry są bezpieczne tam, gdzie
# litery nie są: `abell` to nazwa katalogu, `abe2` nie jest niczyją nazwą.
_DERIVED_DIGIT_SUFFIX = re.compile(r"\d+\Z")


def is_derived_name(name):
    """Czy nazwa pliku niesie znacznik POCHODNEJ OBRÓBKI (`…_ABE`, `…_autocrop`, `…StarsBack`).

    JEDEN WŁAŚCICIEL granicy §5 briefu P-I — woła go droga „Stosy" (`iter_stacks`) i zwykły skan
    w poddrzewie `STACKS` (`scan_tree`). Druga kopia tej reguły znaczyłaby dwie definicje tego,
    co jest klatką, na jednym woluminie — dokładnie stan, przed którym broni rozstrzygnięcie E4-1.

    DOPASOWANIE PO TOKENIE, NIE PO SUBSTRINGU — naprawa pułapki utajonej (E4-1 pkt 2). Dawne
    `"_abe" in name` łapało `_Abell 2151`; w drzewie stosów Abella nie było (0/193 w planie 0802),
    ale sito wchodzi teraz do drogi, którą jedzie CAŁE archiwum, a tam nazwa obiektu jest normalna.
    Rozszerzenie odcinamy przed tokenizacją, żeby `.xisf` nie wnosiło własnego tokenu.

    Asymetria progu `_DERIVED_PREFIX_MIN` jest ZMIERZONA — powód i liczby przy stałej."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    for token in _NAME_TOKEN_SPLIT.split(stem.lower()):
        if not token:
            continue
        if token in DERIVED_NAME_TOKENS:
            return True
        for m in DERIVED_NAME_TOKENS:
            if not token.startswith(m) or token == m:
                continue
            reszta = token[len(m):]
            if len(m) >= _DERIVED_PREFIX_MIN or _DERIVED_DIGIT_SUFFIX.match(reszta):
                return True
    return False


# Katalog archiwum, do którego trafiają GOTOWE OBRAZY po konsolidacji (etap 4). Rozpoznawany
# WYŁĄCZNIE bezpośrednio pod korzeniem skanu — nie jako dowolny segment o tej nazwie, bo
# `…\LIGHTS\NGC7000\stacks\` to czyjś folder roboczy, a nie archiwum stosów.
#
# NAZWA KATALOGU i RODZAJ stosu mają JEDNEGO właściciela: `resolve.paths` (`STACKS_DIR`,
# `STACK_KIND` - jedyny rodzaj, który droga „Stosy" wpuszcza do bazy; zeznanie `IMAGETYP`, nie
# nazwa), bo o to samo drzewo pyta świadek ścieżki na osi obiektu. Tutaj żyje tylko
# reguła POŁOŻENIA sita (prefiks pod korzeniem skanu) - świadek ścieżki kotwiczy na pierwszym
# segmencie `STACKS` od korzenia, bo pyta wyłącznie o `master_light`, który do bazy wpuszcza
# właśnie to sito; dwie reguły położenia to dwa różne pytania, nie kopia jednej odpowiedzi.


def _stacks_prefix(root):
    """Prefiks poddrzewa `STACKS` dla TEGO korzenia — zawsze string, także gdy katalogu nie ma.

    Zwracamy PREFIKS ŚCIEŻKI, nie samą nazwę, bo kontrakt E4-1 brzmi „bezpośrednio pod korzeniem
    skanu". Dopasowanie po nazwie segmentu obejmowałoby każdy `stacks` w drzewie, a taki folder
    bywa czyimś katalogiem roboczym przy obiekcie — sito odsiewałoby wtedy pliki, których nikt
    nie prosił o odsianie, i to bez śladu w konfiguracji.

    Istnienia katalogu NIE SPRAWDZAMY i nie ma po co: gdy go nie ma, żadna ścieżka z przejścia nie
    zacznie się tym prefiksem i sito nie ma czego odsiać. Guard na `None` byłby ochroną stanu
    nieosiągalnego (bramka pakietu 3a, zarzut 5 — docstring obiecywał `None`, kod go nie zwracał).

    ŚCIEŻKI W KODZIE NIE MA I BYĆ NIE MOŻE (repo publiczne, `git-workflow §6`): korzeń przychodzi
    od wołającego, my dokładamy do niego jeden segment ze stałej."""
    return os.path.join(str(root), STACKS_DIR) + os.sep


def _under(path, prefix):
    """Czy `path` leży pod prefiksem. `casefold`, bo NTFS nie rozróżnia wielkości liter, a `root`
    przychodzi po `canonize_root` (casing z dysku) — porównanie wrażliwe na wielkość gubiłoby
    `STACKS` zapisane inaczej niż w stałej."""
    return path.casefold().startswith(prefix.casefold())


@dataclass(frozen=True)
class Card:
    """Pojedyncza karta nagłówka w postaci wierszowej (jak wiersz tabeli `cards`; port 1:1 z dawcy
    `fits_io.Card`). `idx` = kolejność wystąpienia danego keyworda w HDU (wiernie zachowuje
    duplikaty: COMMENT/HISTORY i powtórzone keywordy). `value_num` tylko dla int/float —
    porównania numeryczne idą po nim, tekstowe po `value_raw`."""
    keyword: str
    idx: int
    value_raw: object                 # str | None
    value_num: object                 # float | None
    value_type: str                   # int | float | str | bool | undefined
    comment: object                   # str | None


@dataclass(frozen=True)
class ScanRecord:
    """Wynik skanu jednego pliku (read-only). Materiał wejściowy dla upsertu frame/location/header
    (krok §4.2) — sam w sobie nie jest zapisem domenowym.

    `header is None` + `error` ustawione = plik nieczytelny/nierozpoznany (miękkie lądowanie W1):
    namiary (`path`/`size`/`mtime`) i `file_sha1` są, lecz nagłówka/odcisków sekcji brak →
    degeneracja tożsamości + review wyżej. `error_kind` (P4-2) mówi, KTÓRA to niemożność: `'io'`
    (system nie oddał bajtów) albo `'parse'` (parser nagłówka odmówił) - klasyfikowany tu, bo tylko
    tu żyje obiekt wyjątku; wyżej zostaje już sam tekst, a z tekstu rodzaju się nie zgaduje.

    Odciski (brief §2):
      - `sha1_data`: sha1 sekcji DANYCH HDU (FITS) / bajtów attachmentu (XISF) — TOŻSAMOŚĆ
        frame'a; None = nieobliczalne (brak sekcji danych / zepsuty kafelek / W1) → degeneracja
        w `ingest_record` (sha1 pliku + flaga `sha1_data_uncomputable`);
      - `file_sha1`: sha1 całego pliku (fakt KOPII na location — detekcja zmiany bajtów);
      - `header_hash`: odcisk nagłówka (kontrola writeback/undo) — FITS: sha1 tekstu nagłówka,
        XISF: sha1 bajtów XML (P6a/D-X-3); None przy W1;
      - `hdu_index`/`compressed`: fakty kopii FITS; None dla XISF (D-X-7 — pojęcia obce formatowi)
        i przy W1;
      - `cards`: pełne lustro nagłówka (lista `Card`) — FITS z astropy, XISF z `<FITSKeyword>`
        (P6a/D-X-4); None przy W1;
      - `image_roles`: role wszystkich obrazów kopii (0021, `XisfMeta.image_roles`) - tylko XISF;
        None dla FITS/RAW (liczba HDU wymagałaby dodatkowego I/O) i przy W1.
    """
    path: str                         # ścieżka bezwzględna (str — spójnie z sha1_of/repo)
    size_bytes: int                   # fakt kopii (→ location.size_bytes; R2#6)
    mtime: str                        # ISO-8601 UTC (brama przyrostowa)
    header: dict = field(default_factory=dict)   # pełny nagłówek, JSON-owalny; None gdy error
    error: object = None              # None gdy OK; tekst "Typ: opis" gdy nagłówek nieczytelny (W1)
    error_kind: object = None         # None gdy OK; 'io' | 'parse' obok `error` (P4-2, `unreadable_kind_of`)
    sha1_data: object = None          # tożsamość frame'a; None = nieobliczalne (degeneracja wyżej)
    file_sha1: object = None          # sha1 całego pliku (fakt kopii)
    header_hash: object = None        # odcisk nagłówka (FITS: tekst, XISF: bajty XML); None przy W1
    hdu_index: object = None          # HDU naukowe; None dla XISF/W1
    compressed: object = None         # 0/1 (CompImageHDU); None dla XISF/W1
    cards: object = None              # list[Card] - lustro nagłówka (FITS i XISF); None przy W1
    image_roles: object = None        # tuple ról obrazów (XISF, 0021); None dla FITS/RAW i przy W1


def _iter_suffixes(root, suffixes, excluded_out=None, errors_out=None):
    """Przejdź drzewo `root` i wydaj POSORTOWANE ścieżki plików o danych rozszerzeniach
    (case-insensitive). Zwraca `Path`; pomija katalogi i inne rozszerzenia. Czysty odczyt katalogu.

    WYKLUCZANIE DRZEW ROBOCZYCH (doktryna README §„baza = autorytet"): podkatalog o nazwie z JAWNEJ
    listy `EXCLUDED_DIR_NAMES` (`_WBPP`, `_Review`; niewrażliwie na wielkość) jest ODCINANY — skaner
    do niego NIE SCHODZI (a nie tylko filtruje pliki). To egzekwuje regułę „drzewa WBPP to jednorazowe
    projekcje z bazy, nie wejście skanu". NIE konwencja `_*`: firsthand pokazał realne `_COMETS`/
    `_SOLAR` (lighty), które konwencja porzuciłaby. WYJĄTEK: jawnie wskazany root (`os.walk` zaczyna
    OD niego, filtr `dirnames` nie tyka punktu startu) — gdy user świadomie wskaże `…\\_WBPP`, skanujemy
    go normalnie. `os.walk` domyślnie NIE podąża za symlinkami (`followlinks=False`) — drugi wektor
    wciągania projekcji odcięty.

    `excluded_out` (opcjonalna lista): jeśli podana, dopisujemy do niej ŚCIEŻKI wykluczonych
    katalogów — nie chowamy faktu wykluczenia za samym licznikiem (diagnostyka: user widzi, czego
    skan nie wciągnął). `os.walk` daje kolejność systemową → finalne `sorted(...)` trzyma kontrakt
    „POSORTOWANE" (jak dawne `rglob`+`sorted`).

    `errors_out` (opcjonalna lista, P5/D-V-11): ścieżki katalogów, których `os.walk` NIE PRZECZYTAŁ
    (brak uprawnień, zerwany SMB). Domyślnie `os.walk` POŁYKA te błędy — dla SKANU to łagodne (pliki
    wejdą następnym razem), ale dla passa obecności KORUMPUJĄCE: każdy wiersz DB pod nieprzeczytanym
    katalogiem wyglądałby na zniknięty. Wołający, który podaje tę listę, MUSI traktować poddrzewa
    z błędem dokładnie jak prune (poza oceną), nie jak brak plików."""
    root = Path(root)
    out = []

    def _on_error(exc):                                    # os.walk woła z OSError (ma .filename)
        if errors_out is not None:
            errors_out.append(getattr(exc, "filename", None) or str(exc))

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error):   # followlinks=False — bez symlinków
        excl = [d for d in dirnames if d.lower() in EXCLUDED_DIR_NAMES]
        if excluded_out is not None:
            excluded_out.extend(str(Path(dirpath) / d) for d in excl)
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in EXCLUDED_DIR_NAMES)  # prune + determinizm
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in suffixes:
                out.append(p)
    return sorted(out)                                     # kontrakt: POSORTOWANE po ścieżce


def iter_fits(root):
    """Posortowane ścieżki plików FITS (.fits/.fit/.fts, case-insensitive) w drzewie `root`.
    Prymityw FITS-only; pełny skan pierwszego przebiegu używa `iter_headers` (FITS + XISF)."""
    return _iter_suffixes(root, FITS_SUFFIXES)


def iter_headers(root, excluded_out=None, errors_out=None):
    """Posortowane ścieżki WSZYSTKICH plików nagłówkonośnych pierwszego przebiegu (FITS + XISF,
    case-insensitive) w drzewie `root`. Wejście pętli płaskiej skanu (§Etap 4) I passa obecności
    (P5): jeden mechanizm, format = opakowanie (PLAN §1.1). Podkatalogi z `EXCLUDED_DIR_NAMES`
    odcięte (patrz `_iter_suffixes`); `excluded_out` zbiera ich ścieżki do telemetrii skanu,
    `errors_out` — katalogi NIEPRZECZYTANE (D-V-11; pass obecności traktuje je jak prune)."""
    return _iter_suffixes(root, HEADER_SUFFIXES, excluded_out=excluded_out, errors_out=errors_out)


def iter_stacks(root, derived_out=None, errors_out=None):
    """Posortowane ścieżki KANDYDATÓW drogi „Stosy" (I-2b, P-I): pliki XISF, których nazwa zaczyna
    się od `masterLight` i NIE niesie znacznika pochodnej obróbki. Wejście `scan_stacks`.

    DWA SITA, bo mają dwa różne zadania:
      1. `STACK_NAME_PREFIX` — konwencja WBPP dla produktu integracji. Sito TANIE: zawęża
         7383 plików XISF drzewa obróbki do 259 bez otwierania choćby jednego.
      2. `is_derived_name` — granica §5 briefu P-I („nie wciągamy plików pochodnych
         obróbki"). `masterLight…_autocrop` to ten sam stack po kadrowaniu, `…_ABE`/`…_starless`
         to kolejne kroki obróbki — obrazy, nie klatki archiwum. Zmierzone na realnym drzewie
         2026-08-01: 259 nazw pasuje sicie 1, z tego 131 niesie znacznik pochodnej → **128
         kandydatów** (kotwica D-P-I-6; 85 to liczba INTEGRACJI, nie plików). Od 0810 to sito
         ma drugiego wołającego (`scan_tree` w poddrzewie `STACKS`) i wspólnego właściciela.

    Nazwa NIE jest jednak dowodem, że plik jest stackiem — rozstrzyga ZEZNANIE (`IMAGETYP`),
    które sprawdza dopiero `scan_stacks`. To sito wyznacza ZAKRES (§5), tamta bramka TOŻSAMOŚĆ.

    WYKLUCZENIA DRZEW ROBOCZYCH obowiązują TAK SAMO (`_iter_suffixes` → `EXCLUDED_DIR_NAMES`):
    `_WBPP`/`_Review` to katalogi, do których Horreum sam WYDAJE projekcje, więc wciąganie ich
    z powrotem byłoby zapętleniem niezależnie od tego, którą drogą się tam wchodzi. Na realnym
    drzewie to dziś NO-OP i jest to zmierzone, nie założone: `rglob` bez żadnych wykluczeń
    i `iter_stacks` dają tę samą liczbę 128 (katalogi WBPP obróbki nazywają się `WBPP`/`WBPP2`,
    bez podkreślnika, więc lista ich nie dotyczy).

    `derived_out` (opcjonalna lista): ścieżki odrzucone sitem 2 — wykluczenie ma być WIDOCZNE,
    nie schowane w różnicy liczników (ta sama zasada, co `excluded_dirs` w skanie).
    `errors_out` — katalogi NIEPRZECZYTANE (jak w `iter_headers`)."""
    out = []
    for p in _iter_suffixes(root, XISF_SUFFIXES, errors_out=errors_out):
        name = p.name.lower()
        if not name.startswith(STACK_NAME_PREFIX):
            continue
        if is_derived_name(name):
            if derived_out is not None:
                derived_out.append(str(p))
            continue
        out.append(p)
    return out                                             # `_iter_suffixes` już posortowało


def _jsonable(value):
    """Sprowadź wartość karty FITS do typu JSON-owalnego. astropy zwraca bool/int/float/str
    oraz `Undefined` dla kart bez wartości — to ostatnie mapujemy na None."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, fits.Undefined):
        return None
    return str(value)                 # cokolwiek egzotycznego (np. complex) → tekst, byle wiernie


def _put(out, keyword, value):
    """Dołóż kartę do dict zeznania (wspólna derywacja FITS↔XISF). COMMENT/HISTORY/puste akumuluj
    w listę (1:1, bez gubienia powtórzeń przez kolizję klucza); resztę zapisz wprost."""
    if keyword in _MULTI_KEYWORDS:
        out.setdefault(keyword or "_BLANK", []).append(value)
    else:
        out[keyword] = value


def _select_hdu(hdul):
    """Wybierz HDU niosące metadane akwizycji: pierwszy HDU z `NAXIS`>0 — zwykle PrimaryHDU;
    dla skompresowanych masterów (CompImageHDU) primary bywa pusty (NAXIS=0) — wtedy pierwsze
    HDU z obrazem; gdy żadnego (degeneracja) → Primary. Czytamy tylko nagłówki (NAXIS), nie
    ładując pikseli. Zwraca `(index, hdu)` — index idzie do `hdu_index`/`fileinfo` (port 1:1
    z dawcy `fits_io._select_hdu`)."""
    for i, hdu in enumerate(hdul):
        if hdu.header.get("NAXIS", 0):
            return i, hdu
    return 0, hdul[0]                 # awaryjnie: primary, choćby bez danych


def _header_to_dict(hdr):
    """Nagłówek astropy → JSON-owalny dict (zeznanie 1:1). Powtarzalne COMMENT/HISTORY/puste
    akumulowane w listę, by nie zgubić wierszy przez kolizję klucza."""
    out = {}
    for card in hdr.cards:
        kw = card.keyword
        value = str(card.value) if kw in _MULTI_KEYWORDS else _jsonable(card.value)
        _put(out, kw, value)
    return out


def _classify(value):
    """`(value_type, value_raw, value_num)` karty — port 1:1 z dawcy `fits_io._classify`.
    bool sprawdzany PRZED int (w Pythonie bool < int). int: `value_raw=str(v)` (bezstratnie,
    dowolna precyzja), float: `value_raw=repr(v)` (round-trip); `value_num` tylko dla liczb."""
    if value is None or isinstance(value, fits.Undefined):
        return "undefined", None, None
    if isinstance(value, bool):
        return "bool", ("T" if value else "F"), None
    if isinstance(value, int):
        return "int", str(value), float(value)
    if isinstance(value, float):
        return "float", repr(value), float(value)
    if isinstance(value, str):
        return "str", value, None
    return "str", str(value), None    # complex i inne egzotyki → tekst


def _parse_cards(hdr):
    """Nagłówek astropy → lista `Card` (pełne lustro EAV; port 1:1 z dawcy `fits_io._parse_cards`).
    `idx` numeruje wystąpienia KAŻDEGO keyworda od 0 — duplikaty (COMMENT/HISTORY i powtórzone
    keywordy zwykłe) zachowane wiernie."""
    counts = {}
    out = []
    for card in hdr.cards:
        kw = card.keyword
        idx = counts.get(kw, 0)
        counts[kw] = idx + 1
        vtype, vraw, vnum = _classify(card.value)
        out.append(Card(kw, idx, vraw, vnum, vtype, card.comment or None))
    return out


def _card_value(card):
    """Wartość natywna karty z postaci wierszowej — odwrotność `_classify` (brief §4.2):
    int z `value_raw` (BEZSTRATNIE — `value_num` REAL gubi wielkie inty, R1#8), float z
    `value_num`, bool `'T'`→True, undefined→None, str verbatim."""
    if card.value_type == "int":
        return int(card.value_raw)
    if card.value_type == "float":
        return card.value_num
    if card.value_type == "bool":
        return card.value_raw == "T"
    if card.value_type == "undefined":
        return None
    return card.value_raw


def header_dict_from_cards(cards):
    """Synteza dict-a zeznania z kart (odwrotność `_parse_cards`) — kontrakt IDENTYCZNY z
    `read_fits_header` tego samego nagłówka (na tym stoi import z dawcy, PF-3 / brief §4.2):
    COMMENT/HISTORY/puste keywordy po `idx` w listy (`_BLANK` dla pustych — przez wspólny `_put`),
    powtórzony keyword nie-multi → wygrywa NAJWYŻSZY idx (kontrakt `_put`: ostatni nadpisuje,
    R2#10). Kolejność dokumentowa kart NIE jest potrzebna: sort po `idx` ustawia listy i zwycięzcę
    per keyword, a dict nie zależy od przeplotu keywordów."""
    out = {}
    for c in sorted(cards, key=lambda c: c.idx):
        value = _card_value(c)
        _put(out, c.keyword, str(value) if c.keyword in _MULTI_KEYWORDS else value)
    return out


def _header_hash(hdr):
    """sha1 tekstu nagłówka (port 1:1 z dawcy `fits_io._header_hash`). Nagłówek FITS jest ASCII
    (wielokrotność 2880 znaków); latin-1 nigdy nie rzuca."""
    return hashlib.sha1(hdr.tostring().encode("latin-1", "replace")).hexdigest()


@dataclass(frozen=True)
class FitsMeta:
    """Komplet zeznania + odcisków nagłówka z JEDNEGO otwarcia astropy (`read_fits_meta`).
    `datloc`/`datspan` = pozycja/rozmiar sekcji danych wybranego HDU (z `fileinfo`, bez pikseli) —
    wejście `sha1_of_span` (hash danych i pliku jednym przebiegiem)."""
    header: dict
    cards: list
    header_hash: str
    hdu_index: int
    compressed: int                   # 0/1 (CompImageHDU)
    datloc: int
    datspan: int


def read_fits_meta(path):
    """Odczytaj z pliku FITS komplet: dict zeznania + karty + `header_hash` + `hdu_index` +
    `compressed` + pozycję sekcji danych — JEDNO otwarcie astropy, read-only, bez ładowania
    pikseli, bez pozostawiania uchwytu (Windows). Podnosi wyjątek dla pliku, który nie jest
    FITS — faza skanu nie zgaduje (nierozstrzygalność → `event(*.review)` w warstwie upsertu)."""
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        index, hdu = _select_hdu(hdul)
        hdr = hdu.header
        info = hdul.fileinfo(index)
        return FitsMeta(
            header=_header_to_dict(hdr), cards=_parse_cards(hdr), header_hash=_header_hash(hdr),
            hdu_index=index, compressed=1 if isinstance(hdu, fits.CompImageHDU) else 0,
            datloc=info["datLoc"], datspan=info["datSpan"])


def read_fits_header(path):
    """Odczytaj nagłówek FITS jako JSON-owalny dict (kontrakt sprzed PF-1 bez zmian; dziś
    cienka nakładka na `read_fits_meta`)."""
    return read_fits_meta(path).header


def compressed_data_sha1(path, hdu_index):
    """sha1 SUROWYCH zdekompresowanych pikseli skompresowanego mastera (CompImageHDU) — port 1:1
    z dawcy `fits_io.compressed_data_sha1`.

    Po co osobno od hasza sekcji danych: sekcja danych mastera na dysku to skompresowana tabela
    kafelkowa — różna przy różnej kompresji nawet dla identycznych pikseli. Żeby master wszedł do
    grupowania po danych, hashujemy ZDEKOMPRESOWANĄ tablicę (jedyne sankcjonowane `.data` — patrz
    doktryna w nagłówku modułu, R1#14).

    Kontrakt postaci kanonicznej (deterministyczny między uruchomieniami i maszynami):
    `b"compdata|" + dtype.str(big-endian) + b"|" + "x".join(shape) + b"|" + bajty`, gdzie bajty to
    `ascontiguousarray(data.astype(big-endian))` (astype PIERW → realna zamiana bajtów, potem
    C-order). Otwieramy z `do_not_scale_image_data=True`: hash liczony na SUROWYCH stored pikselach
    (BZERO/BSCALE NIE stosowane) → niezależny od nagłówka i bez ryzyka MaskedArray od `BLANK`.
    Prefiks `compdata|` namespace'uje hash mastera — strukturalnie nie zderzy się z haszem sekcji.

    GRANICA: NIEporównywalny z haszem sekcji danych pliku nieskompresowanego (różne postaci) —
    grupowanie działa master-z-masterem, cross-format poza zakresem.

    Read-only, bez locków (`memmap=False`). `hdu_index` MUSI być tym wybranym przez `_select_hdu`.
    None gdy HDU nie ma danych; wyjątek uszkodzonego kafelka propaguje (soft-landing u wołającego)."""
    with fits.open(path, mode="readonly", memmap=False, do_not_scale_image_data=True) as hdul:
        data = hdul[hdu_index].data   # leniwe → dostęp WYZWALA dekompresję
        if data is None:
            return None
        be = np.ascontiguousarray(data.astype(data.dtype.newbyteorder(">")))
        prefix = (
            b"compdata|" + be.dtype.str.encode("ascii") + b"|"
            + "x".join(map(str, be.shape)).encode("ascii") + b"|"
        )
        digest = hashlib.sha1(prefix + be.tobytes()).hexdigest()
    return digest


def _local_name(tag):
    """Lokalna nazwa znacznika XML bez przestrzeni nazw (`{ns}FITSKeyword` → `FITSKeyword`).
    PixInsight osadza nagłówek w `xmlns='http://www.pixinsight.com/xisf'`; dopasowanie po nazwie
    lokalnej jest odporne na obecność/wariant namespace (xml.etree przykleja `{ns}` do tagu)."""
    return tag.rsplit("}", 1)[-1]


def _unquote_fits(value):
    """Zdejmij FITS-owe cudzysłowy z wartości stringowej XISF (firsthand: PixInsight zapisuje karty
    stringowe jak FITS — `'ZWO ASI2600MC Pro'`). Apostrofy obejmujące zdejmowane, `''`→`'` (escape
    FITS), końcowe spacje → rstrip (nieznaczący pad FITS). Dzięki temu dict jest 1:1 z
    `read_fits_header` (astropy też zwraca string bez apostrofów). Liczby/bool (bez apostrofów)
    zostają NIETKNIĘTE — rzut na typ i tak robi `_to_float` (pola gorące, W3)."""
    if isinstance(value, str) and len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'").rstrip()
    return value


def quote_fits(value, original):
    """Zakoduj wartość karty XISF do BAJTÓW łaty — odwrotność `_unquote_fits` (P6/D-X-6; w briefie
    `_quote_fits`). Konwencji NIE wymyślamy: przejmujemy ją z ORYGINAŁU (`original` = surowe bajty
    wartości sprzed zmiany, BEZ cudzysłowów XML).

    Zmierzone na 37 187 kartach z 331 realnych plików (sonda #4, 2026-07-22): apostrofy FITS
    w 4765 wartościach, 32 422 gołe, ZERO paddingu spacjami, ZERO podwojonych apostrofów, ZERO
    escape'ów XML, atrybut zawsze w cudzysłowie `"`. Stąd reguła: było w apostrofach → piszemy
    w apostrofach (z podwojeniem apostrofu wewnątrz — escape FITS); było gołe → piszemy gołe.
    **Paddingu spacjami NIE dokładamy** — w tym archiwum go nie ma, a dokładanie łamałoby zapis
    tożsamościowy (kryterium §6 pkt 1: przepisanie wartości AKTUALNEJ nie zmienia ani bajtu).
    Zgodne ze spec od Revision 1 (§11.6): nazw się nie dopełnia, dopełnianie wartości jest
    odradzane. Apostrofu nie escape'ujemy, bo atrybut stoi w `"` (zmierzone) - przy atrybucie w apostrofach
    łata złamałaby XML.

    Escape XML: `&` `<` `"`. **`>` zostaje surowy** — jest legalny wewnątrz wartości atrybutu,
    a escape'owanie go zmieniłoby bajty pliku, który go niesie."""
    text = str(value)
    if len(original) >= 2 and original.startswith(b"'") and original.endswith(b"'"):
        text = "'" + text.replace("'", "''") + "'"
    return _escape_xml(text, attribute=True).encode("utf-8")


def encode_xisf_value(value, xml_bytes, span):
    """Zakoduj SUROWĄ wartość do bajtów łaty — dla wycinków, które NIE są wartością karty:
    `<Property>` (D-X-10) i atrybut `comment` (D-X-12). Sam escape XML, BEZ konwencji FITS:
    apostrofy obejmujące to cecha KART (`quote_fits`), własność ich nie nosi.

    Kontekst escape'u czytany z bajtu PRZED wycinkiem — `locate_value_span` zwraca albo wnętrze
    cudzysłowu atrybutu, albo tekst elementu po `>`, więc trzeciej możliwości nie ma. Dzięki temu
    wołający nie może podać kontekstu SPRZECZNEGO z wycinkiem (a `"` escape'ujemy wyłącznie
    w atrybucie — w tekście elementu jest legalny surowy i escape zmieniłby bajty)."""
    in_attribute = xml_bytes[span[0] - 1:span[0]] in (b'"', b"'")
    return _escape_xml(str(value), attribute=in_attribute).encode("utf-8")


def _escape_xml(text, *, attribute):
    """Escape XML dla wartości wstawianej do łaty. `&` MUSI iść pierwszy (inaczej podwójny escape).
    `"` tylko w atrybucie (w tekście elementu jest legalny surowy, a escape zmieniłby bajty).

    Znaków sterujących tu NIE MA czym zakodować - XML 1.0 zabrania ich nawet jako referencji
    (`&#7;`), więc escape ich nie legalizuje. Odmawia ich wcześniej pisarz (`writeback.card_violation`,
    reguły karty FITS 4.0), zanim wartość dojdzie do łaty."""
    out = text.replace("&", "&amp;").replace("<", "&lt;")
    return out.replace('"', "&quot;") if attribute else out


def _unescape_xml(text):
    """Odwrotność `_escape_xml` — do GUARDA zgodności z parserem, nie do zeznania. `&amp;` na
    KOŃCU (inaczej `&amp;lt;` rozwinąłby się dwa razy). Referencji liczbowych (`&#10;`) świadomie
    NIE rozwijamy: w archiwum jest ich zero (sonda #4), a gdyby się pojawiły, guard ma KRZYCZEĆ
    niezgodnością, nie zgadywać."""
    for ent, ch in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(ent, ch)
    return text.replace("&amp;", "&")


_XISF_TAG_NAME = re.compile(rb"<\s*/?\s*([A-Za-z_:][\w:.\-]*)")
_XISF_ATTR = re.compile(rb"""([A-Za-z_:][\w:.\-]*)\s*=\s*("[^"]*"|'[^']*')""")


def _iter_xml_tags(xml_bytes):
    """Kolejne znaczniki `<…>` jako `(start, end)` — skan RESPEKTUJĄCY CUDZYSŁOWY: `>` wewnątrz
    wartości atrybutu jest legalny i NIE kończy znacznika, więc `find(b'>')` tu nie wystarcza
    (P6/#13). Komentarze i CDATA przeskakiwane po ich własnych terminatorach — one też mogą
    nieść `>`. Znacznik bez domknięcia → `ValueError` (EXPECT: nie zgadujemy granicy)."""
    i, n = 0, len(xml_bytes)
    while True:
        i = xml_bytes.find(b"<", i)
        if i < 0:
            return
        for opener, closer in ((b"<!--", b"-->"), (b"<![CDATA[", b"]]>")):
            if xml_bytes.startswith(opener, i):
                end = xml_bytes.find(closer, i + len(opener))
                if end < 0:
                    raise ValueError(f"XISF: niedomknięte {opener.decode()} w nagłówku")
                i = end + len(closer)
                break
        else:
            j, quote = i + 1, None
            while j < n:
                c = xml_bytes[j:j + 1]
                if quote is not None:
                    if c == quote:
                        quote = None
                elif c in (b'"', b"'"):
                    quote = c
                elif c == b">":
                    break
                j += 1
            if j >= n:
                raise ValueError("XISF: znacznik bez domknięcia '>'")
            yield i, j + 1
            i = j + 1


def _tag_attrs(tag_bytes):
    """Atrybuty znacznika jako `nazwa_lokalna -> (start, end)` bajtów WARTOŚCI (bez cudzysłowów),
    liczone względem początku znacznika."""
    out = {}
    for m in _XISF_ATTR.finditer(tag_bytes):
        start, end = m.span(2)
        out.setdefault(m.group(1).rsplit(b":", 1)[-1], (start + 1, end - 1))
    return out


class XisfTargetMissing(ValueError):
    """Adresu NIE MA w nagłówku (karta / atrybut / własność). Osobny typ, bo wołający reaguje na to
    RÓŻNIE zależnie od adresu: brak KARTY do zapisu = odmowa (dokładanie kart to D-X-12), brak
    zmapowanej WŁASNOŚCI = świadome pominięcie (D-X-10 — plik, który jej nigdy nie miał, nie jest
    sam ze sobą sprzeczny). Rozróżnianie po treści komunikatu byłoby kruche."""


class XisfValueUnreachable(ValueError):
    """Adres ISTNIEJE, ale jego wartość nie leży w nagłówku do przepisania: `location=`
    (inline/attachment) albo element pusty. Wołający mapuje na `blocked` — cel jest realny, więc
    ciche pominięcie zostawiłoby plik SPRZECZNY, a łata nagłówka nie ma tu czego chwycić."""


def locate_value_span(xml_bytes, *, keyword=None, idx=0, property_id=None, attr="value"):
    """Wycinek `[start, end)` bajtów WARTOŚCI w nagłówku XISF — materiał łaty (P6/§5).

    Adresowanie: `keyword`+`idx` (karta `<FITSKeyword>`, `idx` = numer wystąpienia keyworda
    w kolejności dokumentu) ALBO `property_id` (`<Property id=…>`). Dokładnie jedno z dwojga.
    `attr` wybiera atrybut karty — `value` (domyślnie) albo `comment` (D-X-12: komentarz łatamy
    TĄ SAMĄ techniką); przy adresowaniu własności nie ma sensu i jest odrzucany.

    Trzy postaci wartości (D-X-10, zmierzone na 7/7 celach): atrybut `value=` · TEKST elementu
    (`>ED<`) · `location=` (inline/attachment) → **`XisfValueUnreachable`**. Adres nieobecny →
    **`XisfTargetMissing`**. Oba są `ValueError` — wołający łapiący szeroko nic nie traci.

    GUARD EXPECT: wyłuskane bajty po odescape'owaniu MUSZĄ się zgadzać z wartością, którą z tego
    samego nagłówka wyjmuje parser XML. To CELOWO druga, niezależna derywacja — skan bajtowy
    i `ElementTree` liczą to samo dwiema drogami i muszą się spotkać. Rozejście → `ValueError`,
    NIGDY cichy zgadunek (łata trafiłaby w niewłaściwe bajty)."""
    if (keyword is None) == (property_id is None):
        raise ValueError("locate_value_span: podaj DOKŁADNIE jedno z keyword / property_id")
    if property_id is not None and attr != "value":
        raise ValueError("locate_value_span: `attr` dotyczy wyłącznie kart (<FITSKeyword>)")

    want = keyword.strip().upper() if keyword is not None else None
    want_attr = attr.encode("ascii")
    seen = 0
    for start, end in _iter_xml_tags(xml_bytes):
        tag = xml_bytes[start:end]
        m = _XISF_TAG_NAME.match(tag)
        if m is None or tag.startswith(b"</"):
            continue
        local = m.group(1).rsplit(b":", 1)[-1]
        attrs = _tag_attrs(tag)

        if want is not None:
            if local != b"FITSKeyword" or b"name" not in attrs:
                continue
            ns, ne = attrs[b"name"]
            name = _unescape_xml(tag[ns:ne].decode("utf-8"))
            if not name or name.strip().upper() != want:
                continue
            if seen != idx:
                seen += 1
                continue
            if want_attr not in attrs:
                raise XisfTargetMissing(f"XISF: karta {want}[{idx}] bez atrybutu {attr}=")
            vs, ve = attrs[want_attr]
            span = (start + vs, start + ve)
            break

        if local != b"Property" or b"id" not in attrs:
            continue
        ids, ide = attrs[b"id"]
        if _unescape_xml(tag[ids:ide].decode("utf-8")) != property_id:
            continue
        if b"location" in attrs:
            raise XisfValueUnreachable(
                f"XISF: własność {property_id} trzyma wartość w location= — poza nagłówkiem")
        if b"value" in attrs:
            vs, ve = attrs[b"value"]
            span = (start + vs, start + ve)
            break
        if tag.rstrip().endswith(b"/>"):
            raise XisfValueUnreachable(
                f"XISF: własność {property_id} pusta (element samozamykający)")
        text_end = xml_bytes.find(b"<", end)
        if text_end < 0:
            raise ValueError(f"XISF: własność {property_id} bez domknięcia elementu")
        span = (end, text_end)
        break
    else:
        cel = f"karta {want}[{idx}]" if want is not None else f"własność {property_id}"
        raise XisfTargetMissing(f"XISF: {cel} nieobecna w nagłówku")

    _assert_span_zgodny_z_parserem(xml_bytes, span, keyword=want, idx=idx,
                                   property_id=property_id, attr=attr)
    return span


_KEYWORD_ATTRS_ZNANE = frozenset((b"name", b"value", b"comment"))


def build_fits_keyword_element(xml_bytes, *, keyword, value, comment=None):
    """Wstawka NOWEJ karty `<FITSKeyword>` jako `(offset, bajty)` — domknięcie D-X-12 (P6d).

    D-X-12 odmawiało dopisania karty z DWÓCH powodów: nie było wiadomo, GDZIE wstawić element
    i jakim prefiksem namespace go nazwać, a `quote_fits` nie miał ORYGINAŁU, z którego przejmuje
    konwencję cudzysłowu. Oba znikają, gdy nowej karty nie SKŁADAMY, tylko KOPIUJEMY sąsiada
    z tego samego pliku i podmieniamy w nim trzy wartości: pisownia znacznika, prefiks, kolejność
    i cudzysłowy atrybutów są wtedy takie same z KONSTRUKCJI, nie z obietnicy.

    Wzorzec = ostatnia karta, której wartość jest w apostrofach FITS — bo nową kartę zakładamy
    TEKSTOWĄ, a apostrofy są konwencją wartości tekstowych. Brak takiej karty → odmowa: konwencji
    tego pliku nie znamy, a zgadnięta zmieniłaby semantykę wartości. Zmierzone na 22 realnych
    stosach bez karty `OBJECT` (2026-08-02): każdy ma ≥1 kartę w apostrofach, zero plików bez
    kart, zero z wieloma `<Image>` niosącymi karty.

    MIEJSCE to koniec bloku kart (za OSTATNIM `<FITSKeyword>` w kolejności dokumentu), a nie za
    wzorcem — wzorzec daje styl, nie pozycję. Wcięcie kopiujemy z białych znaków poprzedzających
    ostatnią kartę, więc nowy element siada w tej samej kolumnie.

    Atrybuty wzorca spoza `name`/`value`/`comment` → odmowa (EXPECT): skopiowalibyśmy do nowej
    karty cudzą wartość, nie wiedząc, co znaczy. `comment` wzorca ZAWSZE nadpisujemy (pustym
    tekstem, gdy wołający nie podał) — przepisany komentarz sąsiada byłby cichym fałszem o nowej
    karcie.

    Zwraca `(offset, blob)` do wycinka ZEROWEJ długości `(offset, offset, blob)`; mieszczenie się
    w rezerwie liczy `build_xisf_header_region`, tak samo jak dla łaty podmieniającej."""
    ostatnia = None
    wzorzec = None
    for start, end in _iter_xml_tags(xml_bytes):
        tag = xml_bytes[start:end]
        m = _XISF_TAG_NAME.match(tag)
        if m is None or tag.startswith(b"</"):
            continue
        if m.group(1).rsplit(b":", 1)[-1] != b"FITSKeyword":
            continue
        ostatnia = (start, end)
        attrs = _tag_attrs(tag)
        if b"value" in attrs:
            vs, ve = attrs[b"value"]
            surowa = tag[vs:ve]
            if len(surowa) >= 2 and surowa.startswith(b"'") and surowa.endswith(b"'"):
                wzorzec = (start, end)
    if ostatnia is None:
        raise XisfTargetMissing(
            "XISF: nagłówek nie ma ani jednej karty <FITSKeyword> — nie ma z czego przejąć "
            "konwencji zapisu nowej")
    if wzorzec is None:
        raise ValueError(
            "XISF: żadna karta tego pliku nie trzyma wartości w apostrofach FITS — konwencji "
            "wartości tekstowej NIE ZNAM, więc nowej karty nie składam")

    tmpl = xml_bytes[wzorzec[0]:wzorzec[1]]
    attrs = _tag_attrs(tmpl)
    obce = set(attrs) - _KEYWORD_ATTRS_ZNANE
    if obce:
        nazwy = ", ".join(sorted(a.decode("ascii", "replace") for a in obce))
        raise ValueError(f"XISF: wzorzec karty ma nieznane atrybuty ({nazwy}) — kopiowanie "
                         "przeniosłoby do nowej karty wartość, której nie rozumiem")
    if b"name" not in attrs or b"value" not in attrs:
        raise ValueError("XISF: wzorzec karty bez atrybutu name= albo value= — nie ma czego podmienić")

    podmiany = [(attrs[b"name"], _escape_xml(str(keyword).strip().upper(),
                                             attribute=True).encode("utf-8")),
                (attrs[b"value"], quote_fits(value, tmpl[attrs[b"value"][0]:attrs[b"value"][1]]))]
    if b"comment" in attrs:
        podmiany.append((attrs[b"comment"],
                         _escape_xml(str(comment or ""), attribute=True).encode("utf-8")))
    elif comment:
        raise ValueError("XISF: wzorzec karty nie ma atrybutu comment= — dopisanie atrybutu "
                         "jest poza P6d")

    out, last = [], 0
    for (s, e), blob in sorted(podmiany):
        out.append(tmpl[last:s])
        out.append(blob)
        last = e
    out.append(tmpl[last:])
    element = b"".join(out)

    biale = xml_bytes[:ostatnia[0]]
    sep = biale[len(biale.rstrip()):]          # wcięcie sprzed ostatniej karty — ta sama kolumna
    return ostatnia[1], sep + element


def _assert_span_zgodny_z_parserem(xml_bytes, span, *, keyword, idx, property_id, attr="value"):
    """GUARD do `locate_value_span`: to samo pytanie zadane `ElementTree`. Dwie derywacje muszą dać
    ten sam tekst — inaczej łata pisałaby w niewłaściwe miejsce.

    Neutralizacja jak w czytniku (`xml_parsable`) i z tego samego powodu: guard ma sprawdzać, czy
    OBIE derywacje widzą tę samą wartość, a nie odmawiać pliku, który czytnik już przepuścił.
    Wolno tu, bo podmiana jest 1:1 co do długości, więc `span` liczony na surowych bajtach dalej
    wskazuje ten sam wycinek.

    ⛔ NEUTRALIZUJEMY OBIE STRONY PORÓWNANIA, nie samą lewą (bramka 3a 0809, zarzut `sol`a). Wartość
    z parsera przychodzi już oczyszczona, a `xml_bytes[span]` jest surowy — gdyby ŁATANA wartość
    sama niosła bajt sterujący, guard porównywałby spację ze znakiem sterującym i wywracał zapis,
    którego czytnik przed chwilą nie miał za co odrzucić. Kierunek był bezpieczny (odmowa, nie
    skorumpowany plik), ale guard przestawał zadawać TO SAMO pytanie dwa razy — a tylko po to
    istnieje."""
    root = ET.fromstring(xml_parsable(xml_bytes))
    expected = None
    if keyword is not None:
        seen = 0
        for elem in root.iter():
            if _local_name(elem.tag) != "FITSKeyword":
                continue
            name = elem.get("name")
            if not name or name.strip().upper() != keyword:
                continue
            if seen == idx:
                expected = elem.get(attr, "")
                break
            seen += 1
    else:
        for elem in root.iter():
            if _local_name(elem.tag) == "Property" and elem.get("id") == property_id:
                expected = elem.get("value") if elem.get("value") is not None else (elem.text or "")
                break
    actual = _unescape_xml(xml_parsable(xml_bytes[span[0]:span[1]]).decode("utf-8"))
    if actual != expected:
        cel = f"karta {keyword}[{idx}]" if keyword is not None else f"własność {property_id}"
        raise ValueError(
            f"XISF: skan bajtowy i parser rozeszły się na {cel} ({actual!r} != {expected!r})")


def _xisf_value_num(text):
    """`value_num` karty XISF = PROJEKCJA liczbowa tekstu (D-X-4), nie zmiana typu: `value_type`
    zostaje `'str'`, więc `_card_value` i tak odda `value_raw` i kontrakt z `read_xisf_header`
    stoi. Dzięki projekcji porównania liczbowe działają na XISF tak jak na FITS. Nieskończoności
    i NaN odrzucamy — nie są wartością do porównywania."""
    try:
        num = float(text)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def xisf_cards(root):
    """Karty `<FITSKeyword>` z drzewa nagłówka XISF, w kolejności dokumentu - JEDYNA derywacja kart
    XISF (D-X-4/4a). Pytają ją czytnik (`read_xisf_meta_full`) i weryfikacja pisarza po łacie
    (`writeback._xisf_verify`), więc „karty, które zobaczy skan" i „karty, które pisarz sprawdził
    przed zapisem" to z konstrukcji to samo zdanie. `root` = drzewo PO `xml_parsable`.

    `value_type` ZAWSZE `'str'` (XISF trzyma wartości jako tekst), `value_num` to projekcja liczbowa
    (D-X-4); `comment` z atrybutu `comment` (D-X-5 - COMMENT/HISTORY mają `value=""`, treść siedzi
    w komentarzu). Karta bez nazwy nie ma adresu, więc jej nie ma."""
    cards, counts = [], {}
    for elem in root.iter():
        if _local_name(elem.tag) != "FITSKeyword":
            continue
        name = elem.get("name")
        if not name:
            continue
        keyword = name.strip().upper()
        value_raw = _unquote_fits(elem.get("value", ""))
        idx = counts.get(keyword, 0)
        counts[keyword] = idx + 1
        cards.append(Card(keyword, idx, value_raw, _xisf_value_num(value_raw), "str",
                          elem.get("comment") or None))
    return cards


@dataclass(frozen=True)
class XisfMeta:
    """Komplet zeznania + odcisków + MATERIAŁU ŁATY z jednego otwarcia pliku XISF (P6a).

    `xml_bytes` = nagłówek 1:1 (materiał łaty i backupu undo); `padding` = bajty między końcem XML
    a pierwszym blokiem danych, `reserved` = 4 B [12,16) — OBA kopiowane verbatim przy zapisie
    (D-X-1: wypełnienie jest zerowe w 330/330 plików, ale kopia nie kosztuje nic i nie zakłada
    niczego). `first_attachment` = MIN pozycji po WSZYSTKICH blokach `attachment:` (D-X-2) — sufit
    nagłówka; `image_span` = attachment PIERWSZEGO `<Image>` Z LOKALIZACJĄ `attachment:`
    w kolejności dokumentu, czyli TOŻSAMOŚĆ klatki (`sha1_data`). To DWA różne fakty: sufit bierze
    minimum ze wszystkiego, tożsamość bierze pierwszy obraz.

    „PIERWSZY = OBRAZ GŁÓWNY" TO KONWENCJA WBPP, NIE GWARANCJA FORMATU: spec nie zna obrazu głównego
    ani nie nadaje kolejności znaczenia (§11.5), a rolę obrazu niesie opcjonalny `imageType`
    (§11.5.1). Zmierzone 2026-09-26: w 230/230 plikach wieloobrazowych pierwszy jest integracją
    (`integration` + `rejection_low`/`rejection_high` ×222, `integration` + `weightImage` ×6).
    Obraz `embedded` (dozwolony, §10.3) jest pomijany - tożsamością zostałby blok NASTĘPNEGO obrazu;
    populacja 0."""
    header: dict
    cards: list
    header_hash: str
    xml_bytes: bytes
    padding: bytes
    reserved: bytes
    first_attachment: object          # int | None — brak bloku attachment (degenerat, D-X-13)
    image_span: object                # (start, size) | None — wejście sha1_data
    keyword_images: int               # ile <Image> NIESIE karty — >1 = cel niejednoznaczny (D-X-11)
    # Role WSZYSTKICH `<Image>` w kolejności dokumentu (0021): `imageType`, a gdy brak - `id`, a gdy
    # i tego brak - None. Długość krotki = liczba obrazów kopii. Fakt KOPII, nie klatki: tożsamość
    # bierze pierwszy obraz, więc dwie kopie jednej klatki mogą nieść różną liczbę obrazów.
    image_roles: tuple = ()

    @property
    def padding_complete(self):
        """Czy bajty między nagłówkiem a pierwszym blokiem danych są KOMPLETNE — BRAMKA PISARZA.

        `False` znaczy, że plik przeczy sam sobie (deklarowany blok wchodzi w nagłówek albo pliku
        brakuje przed blokiem). Odczyt to przeżywa (zeznanie i tożsamość są całe), ale łata NIE
        MA PRAWA ruszyć: pisarz składa plik z `xml + padding + ogon`, więc niekompletne wypełnienie
        przesunęłoby bloki danych. Trzymamy tę arytmetykę TU, żeby pisarz nie liczył jej po raz
        drugi — pomyłka o 4 B przy `XISF_XML_OFFSET` nadpisuje pierwszy blok mastera (§0)."""
        if self.first_attachment is None:
            return False
        return len(self.padding) == self.first_attachment - XISF_XML_OFFSET - len(self.xml_bytes)


def read_xisf_meta_full(path):
    """Odczytaj nagłówek XISF (monolithic) jako `XisfMeta` — jedno przejście, wszystkie fakty.

    Karty (D-X-4/4a) wyłuskuje `xisf_cards` - ta sama funkcja, którą pisarz sprawdza nagłówek po
    łacie - a dict zeznania powstaje Z TYCH KART, więc lustro 1:1 nie jest tu obietnicą, tylko
    konstrukcją: rozjazd wymagałby drugiej derywacji, a jest jedna. Komentarz karty (D-X-5 -
    COMMENT/HISTORY mają `value=""`, treść siedzi w komentarzu) trafia do kart, dict zeznania
    zostaje bez niego, jak dotąd.

    `header_hash` = sha1 bajtów `[16, 16+hlen)`, BEZ wypełnienia (D-X-3) — odpowiednik
    `sha1(hdr.tostring())` z FITS.

    Read-only. Podnosi wyjątek przy złej sygnaturze / uciętym nagłówku / niepoprawnym XML — łapie
    to `scan_file` (miękkie lądowanie W1), nie użytkownik."""
    with open(path, "rb") as fh:
        signature = fh.read(len(_XISF_SIGNATURE))
        if signature != _XISF_SIGNATURE:
            raise ValueError(f"nie XISF monolithic (sygnatura {signature!r})")
        length_bytes = fh.read(_XISF_LENGTH_LEN)
        if len(length_bytes) < _XISF_LENGTH_LEN:
            raise ValueError("XISF: brak pola długości nagłówka")
        (header_len,) = struct.unpack("<I", length_bytes)
        reserved = fh.read(_XISF_RESERVED_LEN)
        if len(reserved) < _XISF_RESERVED_LEN:
            raise ValueError("XISF: brak pola reserved")
        xml_bytes = fh.read(header_len)
        if len(xml_bytes) < header_len:
            raise ValueError(f"XISF: nagłówek XML ucięty ({len(xml_bytes)}/{header_len} B)")

        # Neutralizacja znaków nielegalnych w XML 1.0 (`xml_parsable`) — `xml_bytes` ZOSTAJĄ surowe,
        # bo z nich liczy się `header_hash` i z nich pisze pisarz. ParseError na tym, czego nawet to
        # nie ratuje → łapie `scan_file` (miękkie lądowanie W1).
        root = ET.fromstring(xml_parsable(xml_bytes))
        cards = xisf_cards(root)
        header = {}
        for card in cards:                # dict zeznania Z KART - lustro 1:1 z konstrukcji
            _put(header, card.keyword, card.value_raw)
        image_span = None
        first_attachment = None
        for elem in root.iter():
            loc = (elem.get("location") or "").split(":")
            if len(loc) == 3 and loc[0] == "attachment":
                pos = int(loc[1])
                # sufit nagłówka = MIN po WSZYSTKICH blokach (D-X-2); kolejność dokumentu pokrywa
                # się dziś z bajtową w 330/330 plików, ale to POMIAR, nie gwarancja formatu.
                first_attachment = pos if first_attachment is None else min(first_attachment, pos)
                if _local_name(elem.tag) == "Image" and image_span is None:
                    image_span = (pos, int(loc[2]))

        # Wypełnienie czytamy BEST-EFFORT i NIGDY nie wywracamy na nim odczytu: bajty LEŻĄCE ZA
        # nagłówkiem nie mogą unieważnić samego nagłówka. Plik z deklaracją bloku wchodzącą
        # w nagłówek albo ucięty przed blokiem ma nadal czytelne zeznanie i tożsamość — gdyby
        # czytnik tu rzucał, `scan_file` zdegradowałby go do W1 (`header=None`) i klatka straciłaby
        # kamerę/kind. Sprzeczność jest faktem o ZAPISIE i tam ma zatrzymać robotę: bramką jest
        # `padding_complete`, którą pisarz sprawdza przed łatą (D-X-2).
        padding = b""
        pad_len = (first_attachment - (XISF_XML_OFFSET + header_len)
                   if first_attachment is not None else 0)
        if pad_len > 0:
            padding = fh.read(pad_len)

    # Ile obrazów NIESIE karty (D-X-11) — osobne przejście, bo to pytanie o RODZICA keyworda,
    # a płaski `root.iter()` rodzica nie zna. Dziś 0 plików ma >1 (sonda #5 na 330 realnych), więc
    # to asercja EXPECT na przyszłość: przy dwóch obrazach z kartami „TELESCOP klatki" przestaje
    # mieć jedną odpowiedź i pisarz musi odmówić, zamiast wybrać za usera.
    keyword_images = sum(1 for e in root.iter() if _local_name(e.tag) == "Image"
                         and any(_local_name(k.tag) == "FITSKeyword" for k in e.iter()))
    # Role obrazów (0021) - każdy `<Image>`, nie tylko ten z attachmentem: pytanie brzmi „ile obrazów
    # niesie TA kopia", a obraz `inline`/`embedded` też jest obrazem. Rola wg specyfikacji to
    # `imageType` (§11.5.1, opcjonalny); gdy go brak, `id` (tak nazywa obrazy WBPP: `integration`,
    # `rejection_low`…). Zmierzone 2026-09-26: 248 z 550 plików ma pojedynczy obraz bez obu - None.
    image_roles = tuple(e.get("imageType") or e.get("id") or None
                        for e in root.iter() if _local_name(e.tag) == "Image")

    return XisfMeta(header=header, cards=cards,
                    header_hash=hashlib.sha1(xml_bytes).hexdigest(),
                    xml_bytes=xml_bytes, padding=padding, reserved=reserved,
                    first_attachment=first_attachment, image_span=image_span,
                    keyword_images=keyword_images, image_roles=image_roles)


def build_xisf_header_region(meta, new_xml):
    """Bajty `[0, first_attachment)` po podmianie nagłówka XML — JEDYNE miejsce, gdzie liczy się
    arytmetykę offsetów przy zapisie XISF (§0: pomyłka o 4 B nadpisuje pierwszy blok mastera,
    a pisarz nie ma prawa przeliczać jej po raz drugi).

    Składa: sygnatura + NOWA długość + `reserved` verbatim + `new_xml` + wypełnienie. Region ma
    STAŁY ROZMIAR — offsety bloków danych są bezwzględne i zapisane w XML-u, więc dane się NIE
    RUSZAJĄ, a wypełnienie kurczy się/rośnie dokładnie o deltę długości nagłówka. Zmiana dzieje się
    na POCZĄTKU wypełnienia (tam, gdzie XML w nie wchodzi); ogon — ten stykający się z nieruchomym
    blokiem danych — zostaje verbatim (D-X-1). Skrócenie dokłada ZERA: bajtów, które nadpisał
    dłuższy nagłówek, nie da się wskrzesić, a wolne miejsce MA być zerowe (spec §9.2; zmierzone:
    zerowe w 549/549 sprawdzalnych plików, 2026-09-26). Bloki się nie ruszają, więc ich `checksum` (§10.5)
    zostałby ważny; łata UNIEWAŻNIA natomiast podpis XML (§9.5) - dziś plik podpisany nie przechodzi
    czytnika (W1), a gdy czytnik nauczy się go czytać, pisarz musi dostać bramkę odmowy.

    `ValueError` (wołający → `blocked`) gdy: brak bloku attachment (nie wiadomo, gdzie kończy się
    nagłówek), plik przeczy sam sobie (`padding_complete`), nagłówek nie mieści się w rezerwie
    (D-X-2). Trzeciej drogi nie ma — dane nie ustępują nagłówkowi."""
    if meta.first_attachment is None:
        raise ValueError("XISF: brak bloku attachment — nie wiadomo, gdzie kończy się nagłówek")
    if not meta.padding_complete:
        raise ValueError("XISF: wypełnienie nagłówka niekompletne — plik przeczy sam sobie")
    room = meta.first_attachment - XISF_XML_OFFSET
    if len(new_xml) > room:
        raise ValueError(
            f"XISF: nagłówek nie mieści się w rezerwie ({len(new_xml)} B > {room} B) — "
            f"attachmenty się nie ruszają")
    delta = len(new_xml) - len(meta.xml_bytes)
    padding = meta.padding[delta:] if delta > 0 else b"\x00" * -delta + meta.padding
    return _XISF_SIGNATURE + struct.pack("<I", len(new_xml)) + meta.reserved + new_xml + padding


def read_xisf_meta(path):
    """Odczytaj nagłówek XISF (monolithic) jako `(dict, span)`: dict zeznania — TEN SAM kontrakt
    co `read_fits_header` (klucze FITS wielkimi literami; COMMENT/HISTORY w listach), z jedną
    różnicą: wartości są STRINGAMI (XISF tak je trzyma; rzut na typ robią pola gorące — W3/§Etap 2).
    Wartości stringowe ODCUDZYSŁAWIANE z konwencji FITS (`_unquote_fits`, firsthand) — inaczej dict
    NIE byłby 1:1 z `read_fits_header` (astropy zwraca string bez apostrofów).

    `span` = `(start, size)` bajtów attachmentu PIERWSZEGO `<Image location="attachment:s:n">`
    w porządku dokumentu — dla masterów WBPP to obraz `integration` (właściwy stack; kolejne to
    rejection_low/high/slope_map). Wejście `sha1_of_span` → `sha1_data` XISF = sha1 bajtów
    attachmentu W POSTACI PRZECHOWYWANEJ (brief §2; wzorzec `integ_hash` Custosa). Decyzja D-B
    każe przejść na postać kanoniczną PRZY WYKRYTEJ KOMPRESJI - tej gałęzi NIE MA: atrybutu
    `compression` (§10.6) nikt nie czyta, a archiwum ma 0 bloków skompresowanych (550/550 plików,
    2026-09-26). Blok skompresowany dałby odcisk zależny od kodeka, nie od pikseli. None gdy brak
    obrazu-attachmentu (tożsamość nieobliczalna → degeneracja).

    Format (spec §9.2): sygnatura `XISF0100` (8 B) · uint32 LE długość nagłówka XML (4 B) ·
    4 B reserved (zera) · nagłówek XML UTF-8 od bajtu 16 · opcjonalne wolne miejsce (zera) · bloki
    `attachment:` w dowolnej kolejności, pozycje liczone od początku pliku. Czytamy WYŁĄCZNIE
    nagłówek (nie dotykamy bloków danych) → na Windowsie bez uchwytu blokującego (inwariant
    append-only, jak przy FITS).

    Wyłuskuje wszystkie `<FITSKeyword name= value=>` - warstwę zgodności z FITS (§11.6), nie
    komplet kart 1:1: geometrię obrazu trzyma obowiązkowy atrybut `geometry` (§11.5.1), a karty
    NAXIS* niesie tylko część plików (26 z 545 klatek XISF z kartami, 2026-09-26). Dopasowanie po
    nazwie lokalnej - odporne na namespace. `<Property>` (metadane natywne XISF) świadomie POMIJAMY w pierwszym
    przebiegu — pola gorące mieszkają w FITSKeyword.

    Podnosi wyjątek przy złej sygnaturze / uciętym nagłówku / niepoprawnym XML — skan nie zgaduje;
    łapie to `scan_file` (miękkie lądowanie W1), nie użytkownik.

    Od P6a to NAKŁADKA na `read_xisf_meta_full` (SPOT — jedna derywacja zeznania dla obu wejść);
    kontrakt `(dict, span)` bez zmian, `span` to nadal PIERWSZY `<Image>` w kolejności dokumentu.
    """
    meta = read_xisf_meta_full(path)
    return meta.header, meta.image_span


def read_xisf_header(path):
    """Odczytaj nagłówek XISF jako JSON-owalny dict (kontrakt sprzed PF-1 bez zmian; dziś
    cienka nakładka na `read_xisf_meta`)."""
    return read_xisf_meta(path)[0]


def read_header(path):
    """Dyspozytor czytnika nagłówka po rozszerzeniu (case-insensitive): `.xisf` → `read_xisf_header`,
    RAW (`.dng/.arw/.cr2`) → `exif.read_exif_header` (#2), pozostałe (FITS) → `read_fits_header`.
    Jeden punkt wejścia dla `scan_file` i pętli §Etap 4."""
    suffix = Path(path).suffix.lower()
    if suffix in XISF_SUFFIXES:
        return read_xisf_header(path)
    if suffix in exif.RAW_SUFFIXES:
        return exif.read_exif_header(path)
    return read_fits_header(path)


def _mtime_iso(st):
    """mtime ze `stat` jako ISO-8601 UTC — JEDNA derywacja dla `scan_file` (zapis do `location.mtime`)
    i bramy przyrostowej (`_already_scanned`, porównanie). MUSI być identyczna w obu miejscach: brama
    porównuje string znak-w-znak, więc każda rozbieżność formatu = wieczne PUDŁO (re-skan czyta
    wszystko). Sygnał zmiany pliku = WYŁĄCZNIE mtime (rozmiar NIE jest dyskryminatorem w astro)."""
    return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()


def unreadable_kind_of(exc):
    """Rodzaj niemożności odczytu (P4-2) z OBIEKTU wyjątku - jedyny właściciel tej klasyfikacji
    (miękkie lądowanie `scan_file` i blok odczytu backstopu `scan_tree`); wyżej zostaje już sam
    tekst, a z tekstu rodzaju się nie zgaduje.

    - `'io'` = system operacyjny nie oddał bajtów: `OSError` Z KODEM SYSTEMU (`errno` - brak
      dostępu, plik znikł między listowaniem a odczytem, timeout SMB, katalog zamiast pliku).
      `errno` to atrybut obiektu ustawiany wyłącznie przy błędzie zgłoszonym przez system, nie
      wniosek z komunikatu.
    - `None` = GOŁY `OSError("komunikat")` bez kodu systemu - rodzaj NIEROZSTRZYGNIĘTY. Nie jest
      dowodem treści: astropy tak odmawia zepsutego FITS-a („Empty or corrupt FITS file", „Header
      missing END card", „No SIMPLE card found" - sonda na `.venv-build` 2026-09-26), ale tym
      samym zdaniem potrafi WYPRAĆ przejściowy błąd I/O. Na strumieniu gzip `_File.read` zamienia
      `OSError` odczytu w koniec pliku (`astropy/io/fits/file.py:313-324`, astropy 8.0.0), a parser
      nagłówka odmawia potem gołym `OSError("Header missing END card.")` (`header.py:612-615`).
      Nie jest też dowodem dysku: prawdziwy błąd systemu niesie `errno`, a tu go nie ma - albo
      zginął w praniu, albo nie było go wcale. Z samego wyjątku nie wiadomo, więc klasyfikator
      nie zgaduje; rozstrzyga świadek spoza wyjątku - `scan_file` podnosi rodzaj do `'parse'`,
      gdy bajty pliku DAŁO SIĘ przeczytać.
    - `'db'` = `sqlite3.Error` - błąd bazy po NASZEJ stronie (brama przyrostowa siedzi w bloku
      odczytu backstopu); o pliku nie mówi nic.
    - `'parse'` = każdy inny wyjątek: bajty przyszły, a parser odmówił (XISF: `ParseError`/
      `ValueError`, `struct.error`, `UnicodeDecodeError`…)."""
    if isinstance(exc, sqlite3.Error):
        return "db"
    if isinstance(exc, OSError):
        return "io" if exc.errno is not None else None
    return "parse"


def unreadable_reason_of(exc):
    """Diagnoza „Typ: opis" z OBIEKTU wyjątku (P4-2) - jedyny właściciel składania tego tekstu dla
    miękkiego lądowania `scan_file` i backstopu `scan_tree`. Idzie do `location.unreadable_reason`
    i, z prefiksem, do `event.reason`.

    `OSError` Z KODEM SYSTEMU dostaje kod i opis BEZ ścieżki: `str()` takiego wyjątku dokleja nazwę
    pliku, a ścieżkę niosą już kolumna „Ścieżka", payload zdarzenia i tooltip. Powtórzona w powodzie
    była szumem, który na realnym archiwum rozpychał komórkę „Powód" poza panel (pomiar przy
    `ObjectAxisView._show_copies`). Reszta wyjątków zostaje przy `str()`: komunikat parsera bywa
    jedynym opisem tego, czego nie przyjął."""
    if isinstance(exc, OSError) and exc.errno is not None:
        return f"{type(exc).__name__}: [Errno {exc.errno}] {exc.strerror}"
    return f"{type(exc).__name__}: {exc}"


def scan_file(path):
    """Zeskanuj jeden plik (FITS lub XISF) → `ScanRecord` (odciski + stat + nagłówek + karty).
    Czysty odczyt.

    Miękkie lądowanie (W1): nagłówek nieczytelny/nierozpoznany NIE przerywa skanu — czytnik meta
    rzuca, my łapiemy i zwracamy `ScanRecord(header=None, error="Typ: opis", error_kind='io'|'parse')`;
    odciski sekcji (`sha1_data`/`header_hash`/`cards`) wtedy None, ale `file_sha1` i namiary są
    wypełnione (degeneracja tożsamości + frame/location powstaną; review nagłówka - wyżej).

    Hasze (brief §2): plik NIEskompresowany → `file_sha1` i `sha1_data` JEDNYM przebiegiem
    (`sha1_of_span`; pozycje sekcji z nagłówków przed odczytem treści); CompImageHDU →
    `file_sha1` strumieniem + `sha1_data` z dekompresji (`compressed_data_sha1`); XISF →
    `sha1_data` = sha1 bajtów attachmentu (ten sam jeden przebieg). Błąd I/O w fazie haszy
    propaguje (jak dawne `sha1_of`) — backstop to `scan_tree`, nie W1."""
    p = Path(path)
    st = p.stat()
    mtime = _mtime_iso(st)
    spath = str(p)
    header = None
    cards = header_hash = hdu_index = compressed = span = image_roles = None
    try:
        header, cards, header_hash, hdu_index, compressed, span, image_roles = _read_meta(
            spath, st.st_size)
        error = error_kind = None
    except Exception as exc:              # W1: dowolny błąd czytnika → review, nie crash pętli
        error = unreadable_reason_of(exc)
        error_kind = unreadable_kind_of(exc)   # P4-2: rodzaj TERAZ, póki żyje obiekt wyjątku
    if compressed:
        file_sha1 = sha1_of(spath)
        try:
            sha1_data = compressed_data_sha1(spath, hdu_index)
        except Exception:                 # zepsuty kafelek → tożsamość nieobliczalna (degeneracja:
            sha1_data = None              # sha1 pliku + flaga — składa ingest_record)
    else:
        file_sha1, sha1_data = sha1_of_span(spath, span)
    if error is not None and error_kind is None:
        # ŚWIADEK BAJTÓW (P4-2): goły `OSError` czytnika nie mówi, czy zawiodła treść, czy wyprany
        # błąd I/O (`unreadable_kind_of`). Hasz wyżej przeczytał właśnie CAŁY plik bez błędu, więc
        # bajty SĄ czytelne, a parser mimo to odmówił - to `'parse'`. Wyścig zostaje: udział mógł
        # wrócić między odczytem nagłówka a haszem i wtedy etykieta kłamie, ale żyje jeden skan -
        # marker `unreadable_since` wyłącza oznaczoną kopię z pominięcia przez bramę przyrostową,
        # więc następny skan czyta ją od nowa. Gdy hasz sam rzuca, rekord nie powstaje: wyjątek
        # idzie do backstopu `scan_tree` i tam klasyfikuje się od nowa, bez dowodu bajtów (goły
        # `OSError` zostaje `None`).
        error_kind = "parse"
    return ScanRecord(
        path=spath, size_bytes=st.st_size, mtime=mtime,
        header=header, error=error, error_kind=error_kind,
        sha1_data=sha1_data, file_sha1=file_sha1,
        header_hash=header_hash, hdu_index=hdu_index, compressed=compressed, cards=cards,
        image_roles=image_roles,
    )


def _read_meta(spath, size):
    """JEDNA dyspozycja czytnika nagłówka po sufiksie - dla `scan_file` i dla uzupełnienia faktów
    kopii (`backfill_copy_facts`), które czyta SAM nagłówek, bez haszowania pliku. Dwie kopie tej
    dyspozycji rozjechałyby się przy pierwszym nowym formacie: skan widziałby go, a uzupełnienie nie.

    Zwraca krotkę `(header, cards, header_hash, hdu_index, compressed, span, image_roles)`;
    wyjątek czytnika propaguje (miękkie lądowanie robi wołający). `size` = rozmiar pliku ze `stat`
    (span RAW-a: D-R-1, tożsamość RAW = sha1 CAŁEGO pliku → `sha1_data == file_sha1`)."""
    suffix = Path(spath).suffix.lower()
    if suffix in exif.RAW_SUFFIXES:
        emeta = exif.read_exif_meta(spath)
        cards = [Card(*row) for row in emeta.card_rows]   # opakuj krotki (unikamy cyklu importu)
        return emeta.header, cards, emeta.header_hash, None, None, (0, size), None
    if suffix in XISF_SUFFIXES:
        # `hdu_index`/`compressed` zostają None (D-X-7: pojęcia obce formatowi)
        xmeta = read_xisf_meta_full(spath)
        return (xmeta.header, xmeta.cards, xmeta.header_hash, None, None, xmeta.image_span,
                xmeta.image_roles)
    meta = read_fits_meta(spath)
    return (meta.header, meta.cards, meta.header_hash, meta.hdu_index, meta.compressed,
            (meta.datloc, meta.datspan), None)


def copy_header_facts(header, header_hash, image_roles):
    """Fakty KOPII z jej nagłówka (0021) → słownik pod klingę kopii (klucze `repo.COPY_FACTS`).

    Kotwica `hdr_hash` = odcisk tego nagłówka. Bez nagłówka (W1) albo bez odcisku (import z dawcy
    bez `header_hash`) faktów nie ma czym zakotwiczyć, więc wszystkie są NULL - CHECK 0021 i tak nie
    przyjąłby faktu bez kotwicy. Role jadą jako lista JSON w kolejności dokumentu (`ensure_ascii`
    wyłączone, `json.dumps` deterministyczny), więc porównanie dwóch kopii to porównanie tekstu."""
    if header is None or header_hash is None:
        return dict.fromkeys(repo.COPY_FACTS)
    facts = copy_testimony(header)
    facts["image_count"] = None if image_roles is None else len(image_roles)
    facts["image_roles"] = (None if image_roles is None
                            else json.dumps(list(image_roles), ensure_ascii=False))
    facts["hdr_hash"] = header_hash
    return facts


@dataclass
class ScanSummary:
    """Zliczenia jednego przebiegu `scan_tree` — do firsthand-weryfikacji integralności."""
    files: int = 0
    derived_skipped: int = 0  # pliki pochodne obróbki odsiane w poddrzewie STACKS (E4-1 wariant A+)
    derived_paths: list = field(default_factory=list)   # ich ścieżki — wykluczenie WIDOCZNE, nie cichy licznik
    frames_new: int = 0
    frames_existing: int = 0
    locations_new: int = 0
    locations_refreshed: int = 0   # znana ścieżka, fakty kopii odświeżone (mtime/hash/rozmiar — §2)
    headers_refreshed: int = 0     # zeznanie odświeżone po zmianie header_hash (writeback — §2)
    locations_rebound: int = 0     # podmiana treści pod znaną ścieżką → location przepięta (§2)
    supersede_cleared: int = 0     # treść WRÓCIŁA pod oznaczoną tożsamość → ogniwo zgaszone (R4)
    headers: int = 0
    frame_review: int = 0
    camera_review: int = 0
    kind_unmapped: int = 0
    skipped: int = 0          # pliki POMINIĘTE bramą przyrostową (NIEczytane — bez sha1/nagłówka/DML)
    isolated: int = 0         # kopie IZOLOWANE po przerwanym zapisie w miejscu (0022) - NIEczytane
    isolated_paths: list = field(default_factory=list)   # ich ścieżki - wykluczenie widoczne
    vanished: int = 0         # kopie znikłe MIĘDZY listowaniem a odczytem (backstop D-V-8; nie pass)
    dirs_excluded: int = 0    # podkatalogi z listy odcięte (drzewa robocze: _WBPP/_Review — nie schodzone)
    excluded_dirs: list = field(default_factory=list)   # ich ścieżki (diagnostyka — nie cichy licznik)
    cancelled: bool = False   # skan przerwany kooperatywnie (should_cancel) na granicy pliku
    unreadable_dirs: list = field(default_factory=list)
    """Katalogi, których `os.walk` NIE PRZECZYTAŁ (E4-6). Do 0810 `iter_headers` przyjmowało
    `errors_out`, ale ze wszystkich trzech wołających podawał go WYŁĄCZNIE pass obecności — droga
    GŁÓWNA (16 711 lokacji) szła bez listy, więc zerwany SMB w połowie drzewa dawał przebieg
    z zaniżonymi liczbami i ani słowa o niekompletności. Czyta ją `incomplete`."""

    @property
    def incomplete(self):
        """Czy przebieg NIE zobaczył całego drzewa — nieprzeczytany katalog albo anulowanie.

        Osobno od `frame_review`: tam plik był widziany i nie dał się przeczytać (fakt o PLIKU,
        z markerem `unreadable_since` i własną drogą naprawy), tu całego poddrzewa nie było
        w listingu (fakt o ZAKRESIE — nie ma czego markować, bo nie wiadomo, co tam leży).

        CO WOLNO NA NIEKOMPLETNYM PRZEJŚCIU (rozstrzygnięcie E4-6 — łańcuch NIE jest przerywany):
        przebieg wciąga to, co zobaczył, a etapy po nim (group/resolve/calibrate/lineage/delta)
        liczą ze STANU BAZY i tylko DOPISUJĄ wiedzę o klatkach widzianych — żaden z nich nie
        orzeka o NIEOBECNOŚCI, więc luka w listingu ich nie fałszuje, a jedynie odracza. Brama
        przyrostowa jest per plik (`volume, path, mtime`), nie per przebieg, więc następny skan
        dobiera pominięte bez żadnego gestu — niekompletność jest samonaprawialna.
        JEDYNY etap, który z listingu wyprowadza NIEOBECNOŚĆ, to pass obecności — i on ma własne
        `errors_out` oraz traktuje takie poddrzewa jak prune (`presence.check`, bariery liczone
        z `excluded_dirs + unreadable_dirs`; D-V-11), więc zerwany share nie zamienia się
        w zniknięcia. Dlatego `incomplete` nie blokuje niczego
        w bazie; jego jedyną robotą jest ODEBRANIE PRZEBIEGOWI POZORU KOMPLETU — w raporcie
        (GUI + CLI) i w kodzie wyjścia, żeby bramka etapu 4 („po przenosinach skan widzi 128
        nowych lokacji") nie wzięła zaniżonego przejścia za dowód."""
        return bool(self.unreadable_dirs) or self.cancelled


def _filetype(path):
    """Format pliku z rozszerzenia: `raw` (.dng/.arw/.cr2, #2) | `xisf` | `fits` (fit/fts też FITS).
    Vendor niesie już `INSTRUME` — spłaszczamy do `'raw'` (schemat 0002:16 przewidywał per-vendor,
    ale dyspozycja idzie po SUFIKSIE, nie po `filetype`; D-R-3/znal.7)."""
    suffix = Path(path).suffix.lower()
    if suffix in exif.RAW_SUFFIXES:
        return "raw"
    return "xisf" if suffix in XISF_SUFFIXES else "fits"


def path_gone(path):
    """DOWÓD NIEOBECNOŚCI pliku (P5/D-V-12) — TRÓJSTANOWY, bo „nie ma" i „nie wolno spojrzeć" to
    dwie różne odpowiedzi, a tylko pierwsza uprawnia do zdjęcia obecności (`present=0`):

      `True`  — system mówi NIE MA: `FileNotFoundError` (ENOENT) albo `NotADirectoryError`
                (ENOTDIR — komponent ścieżki przestał być katalogiem);
      `False` — plik jest;
      `None`  — NIE WIEM: każdy inny `OSError` (brak uprawnień, zerwany SMB, timeout, ELOOP).

    `os.path.exists` jest tu ZAKAZANY: zwraca `False` w OBU złych przypadkach, więc awaria sieci
    albo odebrane uprawnienia wyglądałyby jak skasowany plik. Wołający MUSI rozróżniać `is True`
    od falsy — `None` idzie do kubełka `undecided` (raport, ZERO zapisu).

    `os.stat` (nie `lstat`) — pytamy o plik, który byśmy PRZECZYTALI, więc podążamy za dowiązaniem;
    zerwane dowiązanie = treści nie ma. Hardlinki projekcji (`projection.py`) statują normalnie."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return None
    return False


def _already_scanned(con, volume, path, mtime):
    """Brama przyrostowa (§3.B / PLAN_skan §7.9): czy plik pod tą `(volume, path)` i `mtime` jest już
    w bazie I CZYTELNY — TANIA detekcja (`stat`) PRZED drogim `sha1_of` (pełny odczyt). Czysta funkcja
    `con→bool`, testowalna bez Qt.

    STAŁY literał SELECT + bind `?` (f-string wysadziłby bramkę AST §8.1 — `_first_sql_verb`=None dla
    nie-literału = offender poza repo.py/db.py). `UNIQUE(volume, path)` → ≤1 wiersz; `mtime`
    rozstrzyga „niezmieniony".

    GUARD MARKERA (#13): `unreadable_since IS NULL` — kopia OZNACZONA jako nieczytelna jest ZAWSZE
    re-czytana na każdym skanie (marker ją wyklucza z pominięcia), aż UDANY odczyt zgasi marker. Bez
    tego marker po transient awarii przy NIEZMIENIONYM mtime nigdy by nie zgasł: brama pomijałaby plik
    w nieskończoność, a kopia zostałaby wiecznie „nieczytelna" w stanie mimo faktycznego wyzdrowienia.

    GUARD ZMARTWYCHWSTANIA (P5/D-V-6): `present = 1` — kopia oznaczona jako zniknięta jest ZAWSZE
    re-czytana, gdy plik znów pojawi się na dysku. Bez tego powrót pliku o NIEZMIENIONYM `mtime`
    zostałby pominięty przez bramę i wiersz zostałby `present=0` na zawsze (pass zniknięć byłby
    drzwiami jednokierunkowymi). Koszt zerowy: bramę pytamy wyłącznie o pliki, które walk WIDZI
    na dysku, więc warunek dotyka tylko realnych powrotów. Obecność przywraca dopiero UDANY odczyt
    (`repo.refresh_location(present=1)`) — brama sama niczego nie zapisuje."""
    row = con.execute(
        "SELECT 1 FROM location WHERE volume=? AND path=? AND mtime=? "
        "AND unreadable_since IS NULL AND present = 1",
        (volume, path, mtime),
    ).fetchone()
    return row is not None


def _isolated(con, path, volume=None):
    """IZOLACJA PO ZAPISIE W MIEJSCU (0022, Q8): czy kopia pod `path` (na `volume`, gdy podany) ma
    operację `inplace_op` w fazie IZOLUJĄCEJ (`repo.INPLACE_ISOLATING_PHASES`): otwartej (nagłówek
    mógł zostać rozdarty) albo `written` (plik zapisany, ale kontrola danych i re-sync bazy jeszcze
    się nie udały - astra 2026-09-27; dawniej izolacja znikała przed re-synciem). Skan uznałby taką
    kopię za podmianę treści i rozdwoił klatkę, a marker `unreadable_*` wymusiłby ponowny odczyt.
    Wszystkie drogi czytające pliki kopii (skan drzewa, skan stosów, uzupełnienia faktów, przejęcie
    zeznania) pomijają ją BEZWARUNKOWO - także przy wyłączonej bramie przyrostowej - aż do
    dokończenia (`writeback.finish_inplace`), odzysku (`writeback.recover_torn`) albo jawnego
    zwolnienia (`repo.release_inplace_op`). Czysta funkcja `con→bool`, stały literał SELECT."""
    row = con.execute(
        "SELECT 1 FROM location l JOIN inplace_op o ON o.location_id = l.id "
        "WHERE l.path = ? AND (? IS NULL OR l.volume = ?) "
        "AND o.phase IN (SELECT value FROM json_each(?)) LIMIT 1",
        (path, volume, volume, json.dumps(list(repo.INPLACE_ISOLATING_PHASES)))).fetchone()
    return row is not None


def _record_testimony_and_flags(con, rec, *, frame_id, sha1_data, readable, ident, kind,
                                now, summary, actor="scan"):
    """Zeznanie + flagi dla ŚWIEŻO powstałego frame'a (wspólne dla ścieżki nowej i przepiętej):
    czytelny → `record_header` (1:1, z cards) + ewentualne `flag_camera_review`/`flag_kind_unmapped`;
    nieczytelny → `flag_frame_review` (frame-SZKIELET bez headera)."""
    if not readable:                                   # W1: frame-szkielet bez headera → review
        repo.flag_frame_review(con, sha1=sha1_data, path=rec.path, reason=rec.error, now=now,
                               actor=actor)
        summary.frame_review += 1
        return
    repo.record_header(
        con, frame_id=frame_id, raw_json=json.dumps(rec.header, ensure_ascii=False),
        cards=rec.cards, now=now, actor=actor, **extract_header(rec.header))
    summary.headers += 1
    if ident is None:
        repo.flag_camera_review(
            con, frame_id=frame_id, reason="brak osi KAMERA (INSTRUME)", now=now, actor=actor)
        summary.camera_review += 1
    imagetyp = rec.header.get("IMAGETYP")
    if kind == "unknown" and imagetyp and str(imagetyp).strip():
        repo.flag_kind_unmapped(con, frame_id=frame_id, imagetyp=imagetyp, now=now, actor=actor)
        summary.kind_unmapped += 1


def _derive_kind(rec, *, readable, is_raw):
    """Rodzaj klatki + PROWIENIENCJA (#2, D-R-4). RAW nie ma IMAGETYP w EXIF → rodzaj z FOLDERU
    (`kind_source='path'`, precedens C1: ścieżka jako źródło faktu — wąski, jawny); FITS/XISF z
    IMAGETYP zeznania (`source='header'`); nieczytelny (W1) → `unknown`/None (brak zeznania)."""
    if not readable:
        return "unknown", None
    if is_raw:
        return kind_from_path(rec.path), "path"
    return normalize_kind(rec.header.get("IMAGETYP")), "header"


def _derive_axes(con, rec, *, now, actor):
    """Pochodne klatki z rekordu - `(kind, kind_source, ident, camera_id)` - JEDNA derywacja dla
    wjazdu (`ingest_record`) i przejęcia zeznania (`adopt_orphan_testimony`): dwie kopie rozjechałyby
    się przy pierwszej zmianie reguły rodzaju albo kamery i ta sama treść dostawałaby inne pochodne
    zależnie od drogi. Oś kamery powołuje `repo.upsert_camera` (idempotentny) - stąd `con`.

    `kind` WYPRZEDZA oś kamery (kolejność zmieniona 2026-08-02, I-2b): `camera_identity` bierze go
    do bramki `NO_PIXEL_KINDS` - gotowy stack powołuje kamerę, ale nie wnosi `XPIXSZ`. Derywacja
    rodzaju od kamery NIE zależy (`_derive_kind` czyta rekord i format), więc zamiana jest bezpieczna.
    Nieczytelny nagłówek (W1) → `unknown`/None, bez kamery."""
    readable = rec.header is not None
    is_raw = _filetype(rec.path) == "raw"          # #2: FAKT formatu (→ raw_format, kind z folderu)
    kind, kind_source = _derive_kind(rec, readable=readable, is_raw=is_raw)
    ident = camera_identity(rec.header, raw_format=is_raw, kind=kind) if readable else None
    camera_id = None
    if ident is not None:
        camera_id, _ = repo.upsert_camera(
            con, model_canon=ident.model_canon, pixel_um=ident.pixel_um,
            is_mono=ident.is_mono, is_mono_source=ident.is_mono_source,
            raw_instrume=ident.raw_instrume, now=now, actor=actor)
    return kind, kind_source, ident, camera_id


def _record_identity(rec):
    """Tożsamość klatki z rekordu - `(sha1_data, uncomputable)`: odcisk sekcji danych, a gdy
    nieobliczalny, DEGENERACJA (sha1 całego pliku + flaga). Jedna reguła dla wjazdu i dla sprawdzenia
    tożsamości przy przejęciu zeznania - inna reguła po jednej stronie kazałaby uznać plik za cudzą
    klatkę albo, gorzej, cudzą klatkę za tę samą."""
    if rec.sha1_data is not None:
        return rec.sha1_data, 0
    return rec.file_sha1, 1


def ingest_record(con, rec, *, volume="?", drive_letter=None, tier=None, now, summary,
                  actor="scan", inplace_gen=None):
    """Wciągnij JEDEN `ScanRecord` przez jedną klingę (`repo`) — JĄDRO wspólne dla skanu drzewa
    (`scan_tree`) i importu z dawcy (rekord pochodzi z nagłówka pliku ALBO z cache'owanego
    źródła). Mutuje `summary`; zapis WYŁĄCZNIE przez `repo` (zero DML tutaj). `actor` idzie do
    KAŻDEGO eventu tej ścieżki (import z dawcy podaje `import:fitsmirror`, brief §4.2).

    TOŻSAMOŚĆ (brief §2): frame po `sha1_data` (odcisk sekcji danych); nieobliczalny →
    DEGENERACJA (sha1 całego pliku + `sha1_data_uncomputable=1`) — legalna WYŁĄCZNIE dla ścieżki
    NIEZNANEJ (R3-b1). Fakty kopii (file_sha1/header_hash/hdu_index/compressed/size_bytes) idą
    na location.

    ŚCIEŻKA NIEZNANA (brak wiersza `location(volume,path)`):
      - oś KAMERA (`camera_identity`→`upsert_camera`) i `normalize_kind` tylko dla CZYTELNEGO
        nagłówka; nieczytelny (W1) → `kind='unknown'`, `camera_id=None`;
      - `upsert_frame` + `add_location` (idempotentnie). NOWY frame → zeznanie/flagi
        (`_record_testimony_and_flags`); ISTNIEJĄCY sha1_data → tylko nowa `location`
        (multi-location); zeznanie z PIERWSZEGO wystąpienia (reguła N-lokacji, §2).

    ŚCIEŻKA ZNANA — kontrakt świeżości §2 (domyka dług „mtime nieaktualizowany"):
      - plik NIECZYTELNY, bajty NIEZMIENIONE → `refresh_location_unreadable` (mtime + MARKER
        `unreadable_since` + frame.review, ZERO nowych frame'ów; #13). Wołane BEZWARUNKOWO — cichy
        no-op idempotentnego re-skanu rozstrzyga repo (zwraca False, gdy powtórna awaria niczego nie
        zmienia); `summary.frame_review` rośnie TYLKO gdy repo zwróciło True;
      - PODMIANA TREŚCI (świeża tożsamość ≠ tożsamość frame'a lokacji — WBPP re-generuje master
        pod tą samą nazwą): `upsert_frame` (ew. degenerat) + `rebind_location` + świeże fakty
        kopii; stary frame ZOSTAJE (append-only) — BEZ żadnej lokacji, więc pass zniknięć (oparty
        na lokacjach) go NIE podchwyci; ślad niesie `location.rebound` (P5, `repo.rebind_location`);
      - ta sama tożsamość → `refresh_location`: fakty kopii + (przy zmianie `header_hash`)
        odświeżenie zeznania i pochodnych frame'a (last-read-wins). Udany odczyt GASI marker
        `unreadable_since` (kopia wyzdrowiała; #13), degeneracja go zakłada/trzyma.

    OBECNOŚĆ (P5/D-V-6): każda ścieżka docierająca tutaj została ODCZYTANA (`scan_file`) albo
    ZESTATOWANA (preflight importu odsiewa braki do `skipped`), więc obie gałęzie `refresh_location`
    podają `present=1` — to DOWÓD obecności, nie domysł. Kopia wracająca po zniknięciu wraca tą
    drogą (brama jej nie pomija, D-V-6) i dostaje `location.refreshed` z `{present:{0→1}}`.

    FAKTY KOPII Z JEJ NAGŁÓWKA (0021) idą do klingi KOPII w każdej gałęzi, która pisze fakty kopii
    (`add_location`, obie gałęzie `refresh_location`): liczba/role obrazów i zeznanie pól osi TEGO
    pliku - także przy drugiej kopii istniejącej klatki, dla której zeznania `header` celowo NIE
    nagrywamy (reguła N-lokacji). Dzięki temu rozjazd kopii jest wyliczalny ze stanu, a `header`
    klatki zostaje przy swojej regule (pierwsza kopia, potem ta, której odcisk zmienił się ostatnio).

    GENERACJA ZAPISU W MIEJSCU (`inplace_gen`, astra 2026-09-27): skan czyta generację dziennika
    (`repo.inplace_generation`) PRZED bramką izolacji, bo bramka i odczyt pliku to osobne chwile -
    zapis w miejscu mógł zacząć się po bramce. Znana lokacja z operacją o większym `id` →
    `repo.StaleScanRecord` PRZED jakimkolwiek zapisem tej ścieżki (także przed nową klatką gałęzi
    podmiany), a klinga faktów kopii sprawdza to samo w transakcji zapisu (wąskie okno między tym
    sprawdzeniem a zapisem). Wołający liczy to jak izolację, bez markera nieczytelności. `None` =
    wołający nie jest skanem (re-sync pisarza `writeback._resync`, import) - bez sprawdzenia.

    NIE łapie wyjątków — backstop bez tożsamości (sha1 nieznany → `frame.review`, sha1='?') należy
    do wołającego (`scan_tree` / import), bo to on wie, jak zidentyfikować rekord do review."""
    readable = rec.header is not None
    copy_facts = copy_header_facts(rec.header, rec.header_hash, rec.image_roles)
    kind, kind_source, ident, camera_id = _derive_axes(con, rec, now=now, actor=actor)
    sha1_data, uncomputable = _record_identity(rec)

    loc = con.execute(
        # `present` dołożone dla R4: gałąź „ta sama tożsamość" musi wiedzieć, czy kopia WŁAŚNIE
        # odżyła (0 → 1), żeby zgasić ogniwo zastąpienia bez dopłacania zapytania per plik.
        "SELECT id, frame_id, mtime, file_sha1, unreadable_since, present "
        "FROM location WHERE volume = ? AND path = ?",
        (volume, rec.path)).fetchone()

    if loc is None:                                    # ścieżka NIEZNANA — dotychczasowy tor
        frame_id, created = repo.upsert_frame(
            con, sha1_data=sha1_data, sha1_data_uncomputable=uncomputable,
            kind=kind, kind_source=kind_source, filetype=_filetype(rec.path),
            camera_id=camera_id, now=now, actor=actor)
        if created:
            summary.frames_new += 1
        else:
            summary.frames_existing += 1
        _, loc_created = repo.add_location(
            con, frame_id=frame_id, volume=volume, drive_letter=drive_letter,
            path=rec.path, tier=tier, mtime=rec.mtime,
            file_sha1=rec.file_sha1, header_hash=rec.header_hash, hdu_index=rec.hdu_index,
            compressed=rec.compressed, size_bytes=rec.size_bytes, copy_facts=copy_facts,
            now=now, actor=actor)
        if loc_created:
            summary.locations_new += 1
        if created:                                    # header 1:1 z frame → tylko dla nowego
            _record_testimony_and_flags(
                con, rec, frame_id=frame_id, sha1_data=sha1_data, readable=readable,
                ident=ident, kind=kind, now=now, summary=summary, actor=actor)
        return

    # ── ścieżka ZNANA: kontrakt świeżości §2 ──
    if inplace_gen is not None and repo.newer_inplace_op(con, location_id=loc["id"],
                                                         op_id=inplace_gen):
        raise repo.StaleScanRecord(f"location:{loc['id']} ma operację zapisu w miejscu nowszą "
                                   f"niż odczyt skanu (generacja {inplace_gen})")
    frame_row = con.execute(
        "SELECT sha1_data FROM frame WHERE id = ?", (loc["frame_id"],)).fetchone()

    if not readable and rec.file_sha1 == loc["file_sha1"]:
        # R3-b1 (#13): znana kopia nieczytelna, bajty bez zmian → refresh mtime + MARKER
        # `unreadable_since` (znacznik czytelności w STANIE) + review; ZERO nowych frame'ów
        # (degeneracja tożsamości legalna wyłącznie dla ścieżki nieznanej). Marker trzyma alarm i
        # wymusza re-odczyt przez bramę aż do wyzdrowienia; `refresh_location_unreadable` zwraca
        # False przy powtórnej awarii bez zmiany (QUIET) → wtedy licznik review milczy.
        summary.frames_existing += 1
        if repo.refresh_location_unreadable(
                con, location_id=loc["id"], sha1_data=frame_row["sha1_data"], path=rec.path,
                mtime=rec.mtime, reason=rec.error, kind=rec.error_kind, now=now, actor=actor,
                inplace_gen=inplace_gen):
            summary.frame_review += 1
        return

    frame_id = loc["frame_id"]
    # Marker czytelności kopii (#13) dla OBU gałęzi refresh_location: udany odczyt (readable) gasi
    # marker (None); rekord nieczytelny wpadający tu przez DEGENERACJĘ (podmiana treści na
    # nieczytelną) trzyma/zakłada marker (istniejący timestamp albo `now`) — marker ma zostać, nie zgasnąć.
    # Rodzaj i powód (P4-2) idą za markerem: udany odczyt podaje None/None (potwierdzenie, że nie ma
    # czego tłumaczyć), degeneracja - rodzaj i diagnozę TEJ próby z rekordu.
    unreadable_after = None if readable else (loc["unreadable_since"] or now)
    kind_after = None if readable else rec.error_kind
    reason_after = None if readable else rec.error
    if sha1_data != frame_row["sha1_data"]:            # PODMIANA TREŚCI pod znaną ścieżką
        frame_id, created = repo.upsert_frame(
            con, sha1_data=sha1_data, sha1_data_uncomputable=uncomputable,
            kind=kind, kind_source=kind_source, filetype=_filetype(rec.path),
            camera_id=camera_id, now=now, actor=actor)
        if created:
            summary.frames_new += 1
        else:
            summary.frames_existing += 1
        repo.rebind_location(con, location_id=loc["id"], frame_after=frame_id, now=now,
                             actor=actor, inplace_gen=inplace_gen)
        summary.locations_rebound += 1
        if not created and repo.clear_superseded(con, frame_id=frame_id, now=now, actor=actor):
            # POWRÓT TREŚCI (#DR2/R4, D-DR-4): pod tą ścieżką znów leży tożsamość, którą wcześniej
            # oznaczono jako zastąpioną — cofnięcie edycji w programie graficznym jest zwykłym
            # gestem człowieka. Gasi je DOWÓD Z DYSKU (ten odczyt), nie upływ czasu i nie pass:
            # dziennik mówi, co się działo, dysk mówi, co JEST. `created` odsiewa 99,99%
            # przebiegów bez zapytania do bazy — świeża tożsamość nie mogła być oznaczona.
            # Kierunek ODWROTNY (oznaczanie) tu NIE wchodzi: wymaga znajomości CAŁEJ mapy
            # następczyń (cykl, dwie ścieżki, żywotność) — to robota passu `supersede.backfill`.
            summary.supersede_cleared += 1
        if created:
            _record_testimony_and_flags(
                con, rec, frame_id=frame_id, sha1_data=sha1_data, readable=readable,
                ident=ident, kind=kind, now=now, summary=summary, actor=actor)
        # świeże fakty kopii BEZ odświeżania zeznania (zeznanie nowego frame'a właśnie nagrane,
        # a cudzemu — istniejącemu sha1_data — nie nadpisujemy: reguła N-lokacji)
        refreshed = repo.refresh_location(
            con, location_id=loc["id"], frame_id=frame_id, mtime=rec.mtime,
            file_sha1=rec.file_sha1, header_hash=rec.header_hash, hdu_index=rec.hdu_index,
            compressed=rec.compressed, size_bytes=rec.size_bytes, unreadable_since=unreadable_after,
            unreadable_kind=kind_after, unreadable_reason=reason_after,
            present=1, now=now, actor=actor, copy_facts=copy_facts, inplace_gen=inplace_gen)
        summary.locations_refreshed += refreshed["facts"]
        return

    # ta sama tożsamość pod znaną ścieżką → refresh faktów (+ zeznania przy zmianie header_hash)
    summary.frames_existing += 1
    refreshed = repo.refresh_location(
        con, location_id=loc["id"], frame_id=frame_id, mtime=rec.mtime,
        file_sha1=rec.file_sha1, header_hash=rec.header_hash, hdu_index=rec.hdu_index,
        compressed=rec.compressed, size_bytes=rec.size_bytes, unreadable_since=unreadable_after,
        unreadable_kind=kind_after, unreadable_reason=reason_after,
        present=1, now=now, actor=actor,
        raw_json=json.dumps(rec.header, ensure_ascii=False) if readable else None,
        cards=rec.cards, hot_fields=extract_header(rec.header) if readable else None,
        camera_id=camera_id, kind=kind, copy_facts=copy_facts, inplace_gen=inplace_gen)
    summary.locations_refreshed += refreshed["facts"]
    summary.headers_refreshed += refreshed["header"]
    if loc["present"] == 0 and repo.clear_superseded(con, frame_id=frame_id, now=now, actor=actor):
        # DRUGA DROGA POWROTU TREŚCI (R4): kopia była nieobecna (`present=0`) i właśnie odżyła —
        # bez przepięcia, bo `sha1_data` się zgadza. Tożsamość oznaczona jako zastąpiona ma znów
        # swój plik, więc oznaczenie przestało być prawdą; inwariant `zastapiona_z_obecna_kopia`
        # zaczerwieniłby się na stałe, a godziny tej klatki wypadałyby z rachunku.
        # `loc["present"] == 0` odsiewa BEZ ZAPYTANIA DO BAZY — wiersz lokacji już mamy w ręku,
        # a ożywanie kopii jest rzadkie, więc zwykły przebieg nie płaci tu ani jednej transakcji.
        summary.supersede_cleared += 1


def canonize_root(root):
    """Kanonizacja ROOTA skanu — jawna SEKWENCJA (brief §0, R3-a1) zamiast `realpath`/`resolve`
    (te na zamapowanym `R:` rozwiązują do UNC — ŚWIĘTY zakaz w torze tożsamości ścieżek):

      1. `str(Path(root))` — separatory `/`→`\\`, zdjęcie trailing separatora;
      2. `os.path.abspath` — LEKSYKALNE ukotwiczenie (NIE rozwiązuje SMB/symlinków);
      3. **guard UNC (R3-a2):** root `\\\\host\\share` → odmowa „zamapuj literę dysku"
         (tożsamość `location.path` jest LITEROWA; UNC dublowałby lokacje przy tym samym
         `volume_serial` i brama by pudłowała);
      4. `GetLongPathNameW` — casing/długa forma Z DYSKU (zachowuje literę dysku — skill
         `windows-mapped-drive-path-identity`); zwrot 0 = root nie istnieje → **abort** (EXPECT);
      5. wielka litera dysku.

    Komponenty PONIŻEJ roota niesie `os.walk` (readdir — casing z dysku, jak u dawcy).
    Poza Windows: kroki 4–5 nieczynne (brak API i liter dysków) — zostaje 1–3."""
    s = os.path.abspath(str(Path(root)))
    if s.startswith("\\\\"):
        raise ValueError(
            f"root UNC ({s!r}) poza torem tożsamości — zamapuj literę dysku i skanuj przez nią")
    if sys.platform == "win32":
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(s, buf, 32768)
        if n == 0:                        # EXPECT: root nie istnieje / niedostępny → abort
            raise FileNotFoundError(f"root skanu nie istnieje albo niedostępny: {s}")
        s = buf.value
        if len(s) >= 2 and s[1] == ":":
            s = s[0].upper() + s[1:]
    return s


@dataclass
class BackfillSummary:
    """Zliczenia jednego przebiegu `backfill_xisf_headers` — kotwica idempotencji jest w `remaining`."""
    rows: int = 0             # lokacje wybrane sterownikiem (kandydaci)
    read: int = 0             # realnie odczytane z dysku (scan_file nie rzucił)
    failed: int = 0           # odczyt/`stat` padł → ZERO zapisu dla tej lokacji
    remaining: int = 0        # kandydaci PO przebiegu (0 = komplet; >0 = pliki nie do przeczytania)
    failed_paths: list = field(default_factory=list)
    scan: ScanSummary = field(default_factory=ScanSummary)   # eventy/odświeżenia z `ingest_record`


def _xisf_backfill_rows(con):
    """Kandydaci backfillu (D-X-8): lokacje XISF BEZ `header_hash`, obecne. STAŁY literał SELECT —
    ten sam, którym mierzymy `remaining`, więc „pusto po przebiegu" znaczy dokładnie to samo, co
    „nie ma czego backfillować" (jedno pytanie, nie dwa)."""
    return con.execute(
        "SELECT l.id, l.volume, l.path FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE f.filetype = 'xisf' AND l.header_hash IS NULL AND l.present = 1 ORDER BY l.id"
    ).fetchall()


def backfill_xisf_headers(con, *, now, progress=None):
    """STEROWNIK CELOWANY (P6/D-X-8): dociągnij `cards` + `header_hash` do lokacji XISF, które
    powstały PRZED P6a (skan zwracał dla XISF `None`). Zwraca `BackfillSummary`.

    DLACZEGO nie `scan_tree --force`: globalny re-skan czytałby 839 GB i nie miałby kotwicy
    „skończone". Sterownik pyta bazę o DOKŁADNIE te lokacje, których dotyczy brak
    (`filetype='xisf' AND header_hash IS NULL AND present=1`), i po przebiegu ten sam SELECT jest
    pusty — idempotencja za darmo (`remaining`). Ponowne wywołanie = no-op bez czytania dysku.

    JEDNA ŚCIEŻKA ZAPISU (SPOT): `scan_file` → `ingest_record` — ta sama, którą chodzi skan i import.
    `volume` bierzemy Z WIERSZA (pominięcie dałoby 331 NOWYCH lokacji pod `volume='?'`).
    `ORDER BY l.id` = determinizm dla 5 klatek o dwóch kopiach: obie lokacje są kandydatami, zeznanie
    zostaje po OSTATNIEJ przeczytanej (świadome, jednorazowe last-read-wins wbrew regule „zeznanie
    z pierwszego wystąpienia" — bajty attachmentu są identyczne, więc różni je najwyżej nagłówek).

    SKUTKI ŚWIADOME (D-X-8a/8b): `header_hash` NULL→wartość jest zmianą faktu kopii, więc
    `refresh_location` odświeża zeznanie i wstawia karty — event PARAMI, nie tylko dla klatek z GPS.
    Zmierzone na żywej `horreum_pf4.db` 2026-07-22: 330 `location.refreshed` + 330 `header.refreshed`
    + 1 `frame.review`, wszystkie z `actor='backfill:xisf'` (dziennik ma je odróżniać od skanu).
    Karty SITELAT/SITELONG stają się widoczne dla `resolver.resolve_observatory`, więc NASTĘPNY
    `resolve` przypisze XISF-om stanowisko — to jest zamierzone, nie efekt uboczny.

    Plik nieczytelny (`scan_file` rzuca) → `failed` + ścieżka do raportu, ZERO zapisu: backfill nie
    jest passem obecności ani skanem, więc nie stawia markerów i nie zdejmuje obecności — od tego
    są `scan_tree` i `presence`. Plik czytelny, ale bez parsowalnego nagłówka (XISF z `ParseError`)
    idzie normalną ścieżką `ingest_record` (marker `unreadable_since` — kopia FAKTYCZNIE nieczytelna)
    i zostaje w `remaining`."""
    rows = _xisf_backfill_rows(con)
    s = BackfillSummary(rows=len(rows))
    total = len(rows)
    for i, row in enumerate(rows, 1):
        path = row["path"]
        try:
            if _isolated(con, path):
                raise OSError("kopia izolowana po przerwanym zapisie w miejscu (0022)")
            rec = scan_file(path)
        except Exception as exc:               # brak pliku / I/O — raport, nie zapis (patrz docstring)
            s.failed += 1
            s.failed_paths.append(f"{path}: {type(exc).__name__}: {exc}")
        else:
            s.read += 1
            ingest_record(con, rec, volume=row["volume"], now=now, summary=s.scan,
                          actor="backfill:xisf")
        if progress is not None:
            progress(i, total, path)
    s.remaining = len(_xisf_backfill_rows(con))
    return s


@dataclass
class CopyFactsSummary:
    """Zliczenia jednego przebiegu `backfill_copy_facts` - kotwica idempotencji w `remaining`.

    Każdy licznik ODMOWY niesie ścieżki: „uzupełniono 540 z 550" bez „10 zmieniło się na dysku"
    byłoby raportem, który zataja, dlaczego reszta czeka."""
    rows: int = 0             # kopie wybrane sterownikiem (kandydaci pod korzeniem)
    read: int = 0             # nagłówek przeczytany
    written: int = 0          # fakty zapisane (`repo.record_copy_facts` → True)
    stale: int = 0            # nagłówek na dysku ≠ znany odcisk kopii → ZERO zapisu (dogoni skan)
    missing: int = 0          # pliku nie ma w ISTNIEJĄCYM katalogu (skasowany) → ZERO zapisu;
                              # robota passa obecności („Oznacz zniknięte"), nie „nieczytelne"
    failed: int = 0           # odczyt nagłówka padł (albo nie ma całego katalogu) → ZERO zapisu
    remaining: int = 0        # kandydaci PO przebiegu (0 = komplet)
    cancelled: bool = False
    failed_paths: list = field(default_factory=list)
    stale_paths: list = field(default_factory=list)
    missing_paths: list = field(default_factory=list)


def copy_facts_candidates(con, root=None):
    """Kandydaci uzupełnienia faktów kopii (0021): kopie OBECNE, o znanym odcisku nagłówka, bez
    zebranych faktów (`hdr_hash IS NULL`) - XISF wszystkie (liczba i role obrazów żyją tylko tam)
    plus KAŻDA kopia klatki, która ma >1 lokację OGÓŁEM (tylko tam jest z czym porównywać zeznanie).
    Reszta archiwum dostaje fakty przy najbliższym odczycie skanem - uzupełnienie nie czyta 15 tys.
    FITS-ów po to, żeby zapisać fakty, których nikt nie porówna.

    OGÓŁEM, nie „obecne": ocalała kopia klatki, której siostra zniknęła, porównuje się z zeznaniem
    `header`, które mogło przyjść ze skasowanego pliku. Warunek „>1 OBECNA" wykluczał dokładnie ją -
    predykat zeznania z nieobecnej kopii (`queries.orphan_testimony_copies`) milczał przy kopii bez
    faktów na zawsze, a plan ujednolicenia karty `OBJECT` nie miał czym sprawdzić, czy karty klatki
    są jej kartami. Koszt: sama obecna kopia jest czytana (nagłówek), nie jej nieobecne siostry.

    `header_hash IS NOT NULL` odcina kopie nieczytelne (W1): bez odcisku nie ma kotwicy, a sterownik
    wracałby do nich przy każdej dostawie. STAŁY literał SELECT - ten sam liczy `remaining`, więc
    „pusto po przebiegu" znaczy dokładnie „nie ma czego uzupełniać" (wzorzec `_xisf_backfill_rows`).

    `root` (opcjonalny) zawęża do kopii pod korzeniem - jak każdy etap Dostawy, który dotyka dysku:
    „Przetwórz wszystko" na wskazanym katalogu nie ma prawa czytać plików spoza niego. Porównanie
    przez `canonize_root` + `_under`, ta sama forma literowa, którą skan zapisał `location.path`."""
    rows = con.execute(
        "SELECT l.id, l.path, l.header_hash FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE l.present = 1 AND l.header_hash IS NOT NULL AND l.hdr_hash IS NULL "
        "  AND (f.filetype = 'xisf' OR l.frame_id IN ("
        "       SELECT frame_id FROM location GROUP BY frame_id HAVING COUNT(*) > 1)) "
        "ORDER BY l.id").fetchall()
    if root is None:
        return rows
    prefix = canonize_root(root).rstrip("\\/") + os.sep
    return [r for r in rows if _under(r["path"], prefix)]


def backfill_copy_facts(con, *, now, root=None, progress=None, should_cancel=None,
                        actor="backfill:copies"):
    """STEROWNIK CELOWANY (0021): dociągnij liczbę/role obrazów i zeznanie nagłówka do kopii, które
    powstały PRZED migracją. Zwraca `CopyFactsSummary`. Wzorzec `backfill_xisf_headers` (pyta bazę
    o dokładnie te wiersze, których dotyczy brak; po przebiegu ten sam SELECT jest pusty - drugie
    wywołanie to no-op BEZ czytania dysku), z jedną różnicą, która jest całą jego ceną:

    CZYTA SAM NAGŁÓWEK, NIE HASZUJE PLIKU. `scan_file` liczy sha1 całej treści (tożsamość + odcisk
    kopii), a 550 plików XISF archiwum to 108,9 GB (zmierzone 2026-09-26) - nagłówki tych samych
    plików czytają się po SMB w sekundy. Ceną braku hasza jest brak dowodu, że treść się nie
    zmieniła - i tego dowodu nie potrzebujemy: fakty kopii pochodzą z NAGŁÓWKA, a tożsamość nagłówka
    niesie jego odcisk. Zapis idzie więc wyłącznie wtedy, gdy odcisk przeczytanego nagłówka równa się
    `location.header_hash` (kotwica w `repo.record_copy_facts`, CAS). Inny odcisk = kopia zmieniła się
    od ostatniego skanu → `stale`, ZERO zapisu: należy do skanu, który odświeży razem z faktami kopii
    także `header` klatki, `cards` i pochodne.

    ZEZNANIA KLATKI NIE RUSZA. W odróżnieniu od `backfill_xisf_headers` (które szło przez
    `ingest_record` i przełączało `header` na OSTATNIĄ przeczytaną kopię - świadomie, raz) ten
    sterownik pisze wyłącznie kolumny 0021 na `location`: które zeznanie trzyma `header`, zostaje
    rozstrzygnięte tak, jak było.

    Plik nieczytelny / nieosiągalny → `failed` + ścieżka, ZERO zapisu (nie stawiamy markerów, nie
    zdejmujemy obecności - od tego są `scan_tree` i `presence`); zostaje w `remaining`.

    Pliku BRAK (`FileNotFoundError`), a jego katalog istnieje → `missing` + ścieżka, też ZERO zapisu:
    kopię skasowano z dysku, a baza jeszcze o tym nie wie. To nie jest fakt o czytelności pliku, tylko
    robota passa obecności - raport nazywa ją osobno, żeby „nieczytelne 2" nie wysyłało człowieka do
    pliku, którego nie ma. Nie ma CAŁEGO katalogu (zerwany udział, przemianowany folder) → zostaje
    `failed`: brak katalogu nie dowodzi skasowania, a „Oznacz zniknięte" i tak zweryfikuje zakres sam.

    Hooki `progress(done, total, path, summary)` / `should_cancel()` - kontrakt jak w `scan_tree`
    (anulowanie na GRANICY PLIKU; przerwany przebieg zostawia bazę spójną, bo każda kopia to osobna
    transakcja, a następny przebieg dobiera resztę)."""
    rows = copy_facts_candidates(con, root)
    s = CopyFactsSummary(rows=len(rows))
    total = len(rows)
    for i, row in enumerate(rows, 1):
        if should_cancel is not None and should_cancel():
            s.cancelled = True
            break
        path = row["path"]
        try:
            if _isolated(con, path):
                raise OSError("kopia izolowana po przerwanym zapisie w miejscu (0022)")
            header, _cards, header_hash, _hdu, _comp, _span, image_roles = _read_meta(
                path, os.stat(path).st_size)
        except FileNotFoundError as exc:       # skasowany albo nieosiągalny katalog (docstring)
            if os.path.isdir(os.path.dirname(path)):
                s.missing += 1
                s.missing_paths.append(path)
            else:
                s.failed += 1
                s.failed_paths.append(f"{path}: {type(exc).__name__}: {exc}")
        except Exception as exc:               # I/O albo parser - raport, nie zapis (docstring)
            s.failed += 1
            s.failed_paths.append(f"{path}: {type(exc).__name__}: {exc}")
        else:
            s.read += 1
            facts = copy_header_facts(header, header_hash, image_roles)
            if header_hash != row["header_hash"] or not repo.record_copy_facts(
                    con, location_id=row["id"], copy_facts=facts, now=now, actor=actor):
                s.stale += 1
                s.stale_paths.append(path)
            else:
                s.written += 1
        if progress is not None:
            progress(i, total, path, s)
    s.remaining = len(copy_facts_candidates(con, root))
    return s


@dataclass
class AdoptSummary:
    """Zliczenia jednego przebiegu `adopt_orphan_testimony` - kotwica idempotencji w `remaining`.
    Każdy licznik ODMOWY niesie ścieżki (wzorzec `CopyFactsSummary`): „przejęto 1 z 3" bez
    przyczyny reszty zatajałoby, dlaczego dwie klatki dalej mówią głosem nieobecnej kopii."""
    rows: int = 0             # kandydaci: klatki predykatu o JEDNEJ obecnej kopii pod korzeniem
    read: int = 0             # plik ocalałej kopii przeczytany (nagłówek + tożsamość)
    adopted: int = 0          # zeznanie przejęte (`repo.adopt_testimony` → 'adopted')
    identity: int = 0         # plik niesie INNĄ tożsamość danych niż klatka → ZERO zapisu
    stale: int = 0            # odcisk nagłówka pliku ≠ znany (kopia zmieniona od skanu) → ZERO zapisu
    raced: int = 0            # stan w bazie zmienił się między odczytem a zapisem (równoległy skan,
                              # gest ręki, druga kopia) albo zeznanie już przejęte → ZERO zapisu;
                              # bez ścieżek - to nie jest fakt o pliku, następna dostawa zapyta od nowa
    failed: int = 0           # odczyt padł albo nagłówek nieczytelny → ZERO zapisu
    remaining: int = 0        # kandydaci PO przebiegu (0 = komplet)
    cancelled: bool = False
    identity_paths: list = field(default_factory=list)
    stale_paths: list = field(default_factory=list)
    failed_paths: list = field(default_factory=list)


def adopt_candidates(con, root=None):
    """Kandydaci przejęcia zeznania: połowa „dla etapu" podziału `queries.orphan_testimony_routes`
    (jeden właściciel) - klatki o DOKŁADNIE JEDNEJ obecnej kopii, których zeznania NIE napisała ręka.
    Przy dwóch i więcej kopiach albo zeznaniu z ręki wybiera człowiek (AR-4) i etap ich nie dotyka.
    Lista `(frame_id, kopia)`, kopia = wiersz z `location_id`, `path`, `header_hash`.

    `root` (opcjonalny) zawęża do kopii pod korzeniem - jak każdy etap Dostawy, który dotyka dysku
    (wzorzec `copy_facts_candidates`: `canonize_root` + `_under`, forma literowa skanu).

    Import `gui.queries` LENIWY: moduł jest Qt-wolny, ale ciągnie resolver/stacks/grouper, a rdzeń
    skanu importują oni sami albo ich sąsiedzi - wiązanie na górze pliku otwierałoby drogę cyklowi
    przy pierwszym imporcie `scan` z tamtej strony (precedens `stacks.py`, import `scan` w funkcji)."""
    from .gui import queries
    dla_etapu, _czlowiek = queries.orphan_testimony_routes(con)
    rows = sorted(dla_etapu.items())
    if root is None:
        return rows
    prefix = canonize_root(root).rstrip("\\/") + os.sep
    return [(fid, k) for fid, k in rows if _under(k["path"], prefix)]


def adopt_orphan_testimony(con, *, now, root=None, progress=None, should_cancel=None,
                           actor="adopt:testimony"):
    """ETAP STEROWANY STANEM (AR-5): klatka, której zeznanie pochodzi z kopii już nieobecnej,
    a jedyna obecna kopia mówi co innego, przejmuje zeznanie tej kopii - o ile bieżącego zeznania nie
    napisała ręka (wtedy pyta człowiek, `queries.orphan_testimony_routes`). Zwraca `AdoptSummary`.

    DLACZEGO ETAP, A NIE ZDARZENIE „kopia zniknęła": pass obecności oznacza zniknięcie jednym
    gestem, skan mija ocalałą kopię (mtime bez zmian), a `header` zostaje przy głosie pliku, którego
    nie ma. Etap pyta STAN (`adopt_candidates`) - więc naprawia także zaległości sprzed tej zmiany
    i nie zależy od tego, czy ktoś widział moment zniknięcia. Po przebiegu ten sam predykat jest
    pusty dla przejętych klatek: drugie wywołanie to no-op BEZ czytania dysku.

    ODCZYT = `scan_file` (pełny: nagłówek + tożsamość danych). Tańszej drogi z `sha1_data` nie ma:
    tożsamość wymaga przeczytania treści, a kandydatów jest tyle, ile skasowanych kopii - nie
    archiwum. Dla każdego kandydata:
      * wyjątek odczytu albo nagłówek nieczytelny (W1) → `failed`, ZERO zapisu (nie stawiamy markerów
        i nie zdejmujemy obecności - od tego są `scan_tree` i `presence`);
      * tożsamość danych pliku (reguła `_record_identity`) ≠ tożsamość klatki → `identity`, ZERO
        zapisu: pod tą ścieżką leży INNA treść, a to jest robota skanu (przepięcie lokacji), nie
        przejęcia;
      * odcisk nagłówka pliku ≠ `location.header_hash` → `stale`, ZERO zapisu: kopia zmieniła się od
        skanu, a skan odświeży zeznanie sam (`refresh_location`, zmiana odcisku);
      * inaczej → pochodne tą samą derywacją co wjazd (`_derive_axes`) i klinga
        `repo.adopt_testimony` (header + cards + camera/kind + `header.adopted`). Drift klingi
        (równoległy skan przestawił kopię) i zeznanie już identyczne liczą się jako `raced`.
    Przed zapisem kandydat jest pytany ponownie, czy nadal należy do etapu: odczyt pliku trwa,
    a w tym czasie równoległy skan mógł dołożyć drugą kopię albo ręka poprawić nagłówek - wtedy
    wybór należy do człowieka (AR-4), nie do etapu (`raced`). Okno między tym pytaniem a zapisem
    zostaje, ale nie produkuje nieprawdy: zapisane zeznanie jest zeznaniem obecnej kopii o tej samej
    tożsamości.

    Hooki `progress(done, total, path, summary)` / `should_cancel()` - kontrakt `backfill_copy_facts`
    (anulowanie na GRANICY PLIKU; każda klatka to osobna transakcja, więc przerwany przebieg zostawia
    bazę spójną, a następny dobiera resztę)."""
    rows = adopt_candidates(con, root)
    s = AdoptSummary(rows=len(rows))
    total = len(rows)
    for i, (frame_id, kopia) in enumerate(rows, 1):
        if should_cancel is not None and should_cancel():
            s.cancelled = True
            break
        path = kopia["path"]
        try:
            if _isolated(con, path):
                raise OSError("kopia izolowana po przerwanym zapisie w miejscu (0022)")
            rec = scan_file(path)
        except Exception as exc:               # I/O - raport, nie zapis (docstring)
            s.failed += 1
            s.failed_paths.append(f"{path}: {type(exc).__name__}: {exc}")
        else:
            s.read += 1
            werdykt = _adopt_one(con, frame_id, kopia, rec, now=now, actor=actor)
            if werdykt == "adopted":
                s.adopted += 1
            elif werdykt == "failed":
                s.failed += 1
                s.failed_paths.append(f"{path}: {rec.error}")
            elif werdykt == "identity":
                s.identity += 1
                s.identity_paths.append(path)
            elif werdykt == "stale":
                s.stale += 1
                s.stale_paths.append(path)
            else:                              # 'raced' / klinga: 'drift' / 'unchanged' - bez zapisu
                s.raced += 1
        if progress is not None:
            progress(i, total, path, s)
    s.remaining = len(adopt_candidates(con, root))
    return s


def _adopt_one(con, frame_id, kopia, rec, *, now, actor):
    """Werdykt i zapis jednego kandydata `adopt_orphan_testimony` - kolejność bramek z docstringu
    etapu. Zwraca `'adopted'` | `'failed'` | `'identity'` | `'stale'` | `'raced'` (albo werdykt
    klingi `'drift'` / `'unchanged'`)."""
    if rec.header is None:
        return "failed"
    sha1_data, _ = _record_identity(rec)
    frame_sha1 = con.execute("SELECT sha1_data FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if frame_sha1 is None or frame_sha1[0] != sha1_data:
        return "identity"
    if rec.header_hash != kopia["header_hash"]:
        return "stale"
    teraz = dict(adopt_candidates(con)).get(frame_id)    # stan pod nami mógł się zmienić (docstring)
    if teraz is None or teraz["location_id"] != kopia["location_id"]:
        return "raced"
    kind, _kind_source, _ident, camera_id = _derive_axes(con, rec, now=now, actor=actor)
    return repo.adopt_testimony(
        con, location_id=kopia["location_id"], sha1_data=sha1_data, header_hash=rec.header_hash,
        raw_json=json.dumps(rec.header, ensure_ascii=False), cards=rec.cards,
        hot_fields=extract_header(rec.header), camera_id=camera_id, kind=kind, now=now,
        actor=actor)


@dataclass
class StackScanSummary:
    """Zliczenia jednego przebiegu `scan_stacks`. Kształt wzorowany na `BackfillSummary` (sterownik
    celowany trzyma własne liczniki i ZAGNIEŻDŻA `ScanSummary` z `ingest_record`) — nie na
    `ScanSummary`, bo droga „Stosy" ma pytania, których skan drzewa nie zna: ile nazw odpadło jako
    pochodne obróbki i ile plików ZEZNAŁO, że stackiem nie jest.

    KAŻDY licznik odrzucenia niesie też ścieżki: droga wpuszczająca 128 ze 259 plików musi umieć
    powiedzieć, co zostawiła i dlaczego — inaczej „wciągnięto 128" jest nieweryfikowalne."""
    candidates: int = 0        # nazwy, które przeszły OBA sita `iter_stacks`
    derived_skipped: int = 0   # `masterLight…` ze znacznikiem pochodnej (§5 — poza zakresem)
    ingested: int = 0          # zeznanie potwierdziło `master_light` → poszło przez `ingest_record`
    skipped: int = 0           # brama przyrostowa (znane `(volume, path, mtime)`) — ZERO odczytu
    rejected_kind: int = 0     # przeczytane, ale `IMAGETYP` mówi co innego → ZERO zapisu
    rejected_unreadable: int = 0   # nagłówek nieczytelny → nie da się potwierdzić → ZERO zapisu
    failed: int = 0            # `scan_file` rzucił (I/O) → ZERO zapisu
    kinds_rejected: dict = field(default_factory=dict)     # jaki kind zeznały odrzucone (diagnostyka)
    derived_paths: list = field(default_factory=list)
    rejected_paths: list = field(default_factory=list)
    failed_paths: list = field(default_factory=list)
    unreadable_dirs: list = field(default_factory=list)
    """Katalogi, których `os.walk` NIE PRZECZYTAŁ (E4-1 pkt 4). Do 0810 `iter_stacks` przyjmowało
    `errors_out`, ale `scan_stacks` go nie podawało, więc zerwany SMB w połowie drzewa dawał ciche
    „0 kandydatów" — raport nie do odróżnienia od „nic tam nie ma". Ta lista jest jedyną różnicą
    między tymi dwoma zdaniami; czyta ją `incomplete`."""
    cancelled: bool = False
    scan: ScanSummary = field(default_factory=ScanSummary)  # eventy/odświeżenia z `ingest_record`

    @property
    def incomplete(self):
        """Czy przebieg NIE zobaczył całego drzewa — nieprzeczytany katalog albo anulowanie.

        Osobno od `failed`: tam plik był widziany i nie dał się przeczytać (fakt o PLIKU), tu
        całego poddrzewa nie było w listingu (fakt o ZAKRESIE). Konsument liczy na tym kod wyjścia,
        bo „wciągnięto 0" po zerwanym share'ze nie ma prawa wyglądać na sukces."""
        return bool(self.unreadable_dirs) or self.cancelled


def scan_stacks(con, root, *, volume="?", drive_letter=None, tier=None, now,
                progress=None, should_cancel=None):
    """DROGA „STOSY" (I-2b, P-I / D-P-I-1 wariant A): wciągnij GOTOWE OBRAZY PO INTEGRACJI ze
    wskazanego korzenia drzewa obróbki. Zwraca `StackScanSummary`.

    DLACZEGO OSOBNA KOMENDA, a nie rozszerzenie skanu: drzewo obróbki nie jest archiwum. Leży
    poza `R:\\ASTRO_`, żyje własnym rytmem i niesie setki plików pośrednich (`_starless`, `_SPCC`,
    `ABE`), które klatkami nie są. Skan archiwum i standing-op doskanu zostają NIETKNIĘTE — user
    wskazuje korzeń stosów świadomie, osobnym gestem.

    DWIE BRAMKI, każda o innym zadaniu — i to jest sedno tej drogi:
      * **zakres** — `iter_stacks` (nazwa `masterLight…` bez znacznika pochodnej, §5 briefu);
      * **tożsamość** — `IMAGETYP` przez `normalize_kind` musi dać `STACK_KIND`. Nazwa NIE
        wystarcza: gdyby user wskazał korzeń z plikiem nazwanym po WBPP, ale będącym czymkolwiek
        innym, droga wciągnęłaby go jako stack. Plik, który nie zeznaje `master_light`, jest
        ODRZUCANY z policzonym `kind` — nie wciągany „na wszelki wypadek".
    Zmierzone na realnym drzewie 2026-08-01: 128/128 kandydatów zeznało `master_light`, zero
    odrzuceń — bramka tożsamości nie odsiewa dziś niczego i ma tak zostać. Jej rolą jest ODMOWA
    w dniu, w którym konwencja nazw przestanie się zgadzać z zawartością.

    **ZERO ZAPISU przy każdej odmowie** (odrzucenie, nieczytelność, I/O) — powód ten sam, co
    w `backfill_xisf_headers`: to sterownik celowany, NIE skan i NIE pass obecności. Nie stawia
    markera `unreadable_since`, nie zdejmuje `present`, nie zakłada frame'ów-szkieletów. Drzewo
    obróbki jest ŻYWE i nieuporządkowane (brief §6 pkt 4) — droga, która zapisywałaby po każdym
    potknięciu, zaśmieciłaby kolejkę przeglądu przy pierwszym przestawieniu folderów.

    IDEMPOTENCJA stoi na tej samej bramie przyrostowej, co skan (`_already_scanned`,
    `(volume, path, mtime)`) — drugi przebieg na niezmienionym drzewie to `skipped == candidates`
    i zero DML. Brama wymaga REALNEGO serialu; `volume='?'` ją wyłącza (jak w `scan_tree`).

    ZAPIS wyłącznie przez `ingest_record` (jedna klinga, ta sama, którą idzie skan i import) —
    `actor='stacks'`, żeby dziennik odróżniał tę drogę od doskanu archiwum. Bajtów NIE RUSZAMY:
    pliki otwierane read-only, jak wszędzie w tym module.

    Hooki `progress`/`should_cancel` — kontrakt jak w `scan_tree` (anulowanie na GRANICY PLIKU)."""
    s = StackScanSummary()
    derived = []
    root = canonize_root(root)
    paths = iter_stacks(root, derived_out=derived, errors_out=s.unreadable_dirs)
    s.derived_paths = derived
    s.derived_skipped = len(derived)
    s.candidates = len(paths)
    total = len(paths)
    gate_on = volume != "?"
    for i, path in enumerate(paths, 1):
        if should_cancel is not None and should_cancel():
            s.cancelled = True
            break
        spath = str(path)
        try:
            # Generacja PRZED bramką izolacji (jak w `scan_tree`): zapis w miejscu zaczęty po
            # bramce odrzuca ingest (`repo.StaleScanRecord`) - liczony niżej jak pominięcie.
            gen = repo.inplace_generation(con)
            if _isolated(con, spath, volume if gate_on else None) or (
                    gate_on and _already_scanned(con, volume, spath, _mtime_iso(path.stat()))):
                s.skipped += 1                        # izolowana (0022) albo bez zmian
            else:
                rec = scan_file(spath)
                if rec.header is None:                     # W1: nie ma czym potwierdzić tożsamości
                    s.rejected_unreadable += 1
                    s.rejected_paths.append(f"{spath}: nagłówek nieczytelny ({rec.error})")
                elif normalize_kind(rec.header.get("IMAGETYP")) != STACK_KIND:
                    kind = normalize_kind(rec.header.get("IMAGETYP"))
                    s.rejected_kind += 1
                    s.kinds_rejected[kind] = s.kinds_rejected.get(kind, 0) + 1
                    s.rejected_paths.append(f"{spath}: zeznaje '{kind}', nie {STACK_KIND}")
                else:
                    ingest_record(con, rec, volume=volume, drive_letter=drive_letter, tier=tier,
                                  now=now, summary=s.scan, actor="stacks", inplace_gen=gen)
                    s.ingested += 1
        except repo.StaleScanRecord:                       # zapis w miejscu po bramce - izolacja
            s.skipped += 1
        except Exception as exc:                           # I/O — raport, NIGDY zapis (patrz docstring)
            s.failed += 1
            s.failed_paths.append(f"{spath}: {type(exc).__name__}: {exc}")
        if progress is not None:
            progress(i, total, spath, s)
    return s


def scan_tree(con, root, *, volume="?", drive_letter=None, tier=None, now,
              progress=None, should_cancel=None):
    """Pętla PŁASKA: każdy plik nagłówkonośny w `root` oceniany RAZ i wciągany przez jedną klingę
    (`repo`). Jeden plik = jedno dotknięcie (§1.2). Zapis WYŁĄCZNIE przez `repo` (zero DML tutaj).

    Per plik: brama przyrostowa → `scan_file` (read-only) → `ingest_record` (jądro). Backstop W1:
    dowolny nieoczekiwany wyjątek per-plik NIE wywala całości — skan leci dalej. Rozstrzygnięcie
    zależy od tego, czy ścieżka jest ZNANA (#13): ZNANA → `refresh_location_unreadable` (marker
    `unreadable_since`, idempotentnie — powtórna awaria to cichy no-op, nie spam review); NIEZNANA →
    `flag_frame_review(sha1='?')` (backstop bez tożsamości — brak kotwicy UNIQUE, może się powtórzyć).
    Rodzaj awarii (P4-2) strony odczytu nadaje klasyfikator z obiektu wyjątku; wyjątek z
    `ingest_record` dostaje `'db'`, bo jest faktem o nas, nie o pliku.
    `now` jawny (ISO-8601) — deterministyczne testy. Zwraca `ScanSummary`.

    BRAMA PRZYROSTOWA (§3.B) — aktywna ⟺ `volume != '?'`. Gdy znamy trwały serial woluminu,
    plik o znanym `(volume, path, mtime)` jest POMIJANY bez `sha1_of` (drogi pełny odczyt) i bez DML
    (`summary.skipped += 1`). `volume='?'` (serial nieustalony) → brama OFF → pełny skan (zero
    fałszywych pominięć — `volume` to nie tożsamość frame'a, §7.5).

    HOOKI GUI (Qt-WOLNE; rdzeń nic nie wie o Qt):
      - `should_cancel: ()->bool` — sprawdzane na GÓRZE pętli, PRZED plikiem; `True` ⇒ `break` +
        `cancelled=True`. Anulowanie na GRANICY PLIKU: bieżący plik albo cały wciągnięty, albo
        nietknięty (bezpieczeństwo z `break` przed `scan_file`, NIE z commitu per-call).
      - `progress: (done, total, path, summary)->None` — wołane po KAŻDYM pliku (też pominiętym),
        `total=len(paths)` (lista zmaterializowana → darmowe). Snapshot/emisja sygnału Qt to robota
        callbacku GUI; rdzeń woła synchronicznie.
    """
    summary = ScanSummary()
    excluded = []
    root = canonize_root(root)                             # forma literowa + casing z dysku; UNC → odmowa (§0)
    # `errors_out` (E4-6): katalogi NIEPRZECZYTANE przez `os.walk` (zerwany SMB, odebrane prawa).
    # Bez tej listy przebieg po zerwanym share'ie jest nie do odróżnienia od przebiegu po drzewie,
    # w którym po prostu nic nie przybyło — a to droga główna, nie boczna. Semantyka → `incomplete`.
    paths = iter_headers(root, excluded_out=excluded,      # drzewa robocze odcięte (EXCLUDED_DIR_NAMES: _WBPP/_Review)
                         errors_out=summary.unreadable_dirs)
    summary.excluded_dirs = excluded
    summary.dirs_excluded = len(excluded)
    stacks_prefix = _stacks_prefix(root)
    total = len(paths)
    gate_on = volume != "?"
    for i, path in enumerate(paths, 1):
        if should_cancel is not None and should_cancel():
            summary.cancelled = True
            break
        spath = str(path)
        if _under(spath, stacks_prefix) and is_derived_name(path.name):
            summary.derived_skipped += 1
            summary.derived_paths.append(spath)
            # POSTĘP LICZY PRZEJŚCIE, NIE WCIĄGNIĘCIE (bramka pakietu 3a, zarzut 6). Docstring
            # obiecuje wołanie po KAŻDYM pliku, a `gui.progress.should_emit` domyka pasek dopiero
            # przy `done == total` — `continue` przed tą linią zostawiał pasek na wieczne 99%
            # w każdym drzewie z choćby jedną pochodną pod `STACKS`.
            if progress is not None:
                progress(i, total, spath, summary)
            continue
        summary.files += 1
        # DWA BLOKI, BO RODZAJ MÓWI, GDZIE SZUKAĆ WINY (P4-2). Wyjątek z ODCZYTU (`stat`, brama,
        # `scan_file`) klasyfikuje `unreadable_kind_of` z obiektu: kod systemu → `'io'`,
        # `sqlite3.Error` z bramy przyrostowej → `'db'`, goły `OSError` z haszowania (bez dowodu
        # bajtów, którym `scan_file` rozstrzyga goły `OSError` czytnika) → `None`. Wyjątek z ZAPISU
        # (`ingest_record`: błąd bazy, bug w naszym kodzie) przychodzi PO udanym odczycie, więc jest
        # faktem o NAS, nie o pliku - rodzaj `'db'` ZAWSZE, bez klasyfikatora. Jeden `try` na oba
        # kroki dawał mu `'parse'`, czyli „nagłówek nie przechodzi parsera", i user zgłaszał zdrowy
        # plik. Marker przy nieudanym zapisie i tak stawiamy: wymusza re-odczyt przez bramę, więc
        # zapis ponawia się sam przy następnym skanie, zamiast utknąć pod pominięciem.
        blad = kind = rec = gen = None
        stary = False
        try:
            # GENERACJA PRZED BRAMKĄ (astra, 2026-09-27): bramka izolacji i odczyt pliku to dwie
            # chwile, a zapis w miejscu może zacząć się między nimi. Operacja o `id` większym niż
            # ta generacja odrzuca zapis rekordu w klindze (`repo.StaleScanRecord`) - liczymy to
            # jak izolację, bez markera nieczytelności.
            gen = repo.inplace_generation(con)
            if _isolated(con, spath, volume if gate_on else None):   # 0022: rozdarty zapis
                summary.isolated += 1
                summary.isolated_paths.append(spath)
                skip = True
            else:
                skip = gate_on and _already_scanned(con, volume, spath, _mtime_iso(path.stat()))
                if skip:
                    summary.skipped += 1
            if not skip:
                rec = scan_file(spath)
        except Exception as exc:                           # backstop W1, strona ODCZYTU
            blad, kind = exc, unreadable_kind_of(exc)
        if rec is not None:
            try:
                ingest_record(con, rec, volume=volume, drive_letter=drive_letter, tier=tier,
                              now=now, summary=summary, inplace_gen=gen)
            except repo.StaleScanRecord:                   # zapis w miejscu po bramce - izolacja
                stary = True
            except Exception as exc:                       # backstop W1, strona ZAPISU - fakt o nas
                blad, kind = exc, "db"
        if blad is not None:                               # backstop W1: pojedynczy plik nie wywala skanu
            # Błąd I/O w scan_file (hasze są POZA try W1 — otwarcie/odczyt pliku propaguje) na ZNANEJ
            # ścieżce: oznacz marker `unreadable_since` przez klingę (#13) zamiast flagować sha1='?'
            # co skan. Bez tego marker znosi bramę → plik, który przestał się OTWIERAĆ, generowałby
            # +1 event/skan w nieskończoność. `mtime` bierzemy Z BAZY (bez zmiany) → powtórka to cichy
            # no-op (QUIET). Ścieżka NIEZNANA (brak location) → backstop bez tożsamości: sha1='?'.
            #
            # ROZGAŁĘZIENIE PO DOWODZIE (P5/D-V-8): plik mógł ZNIKNĄĆ między listowaniem a odczytem
            # (walk go widział, `stat`/otwarcie już nie). Marker znaczy „kopia JEST nieczytelna,
            # przeczytaj ją ponownie" — dla nieistniejącego pliku to kłamstwo bez wyjścia, a przy
            # `present=0` byłoby hybrydą zakazaną przez inwariant D-V-5. Rozstrzyga `_gone` (lstat +
            # errno), nie domysł; zniknięcie idzie do `mark_location_vanished` (ta sama klinga).
            #
            # RODZAJ (P4-2) nadany wyżej, przy obiekcie wyjątku; diagnozę składa ten sam właściciel,
            # co w `scan_file` (`unreadable_reason_of`), więc obie drogi mówią jednym formatem.
            reason = unreadable_reason_of(blad)
            row = con.execute(
                "SELECT l.id, l.mtime, f.sha1_data FROM location l JOIN frame f ON f.id = l.frame_id "
                "WHERE l.volume = ? AND l.path = ?",
                (volume, spath)).fetchone()
            if row is not None and path_gone(spath) is True:
                if repo.mark_location_vanished(
                        con, location_id=row["id"], expected_path=spath, root=root, run_id=None,
                        now=now, actor="scan"):
                    summary.vanished += 1
            elif row is not None:
                try:
                    if repo.refresh_location_unreadable(
                            con, location_id=row["id"], sha1_data=row["sha1_data"], path=spath,
                            mtime=row["mtime"], reason=reason, kind=kind, now=now,
                            inplace_gen=gen):
                        summary.frame_review += 1
                except repo.StaleScanRecord:               # odczyt padł w trakcie zapisu w miejscu
                    stary = True
            else:
                repo.flag_frame_review(con, sha1="?", path=spath, reason=reason, now=now)
                summary.frame_review += 1
        if stary:
            summary.isolated += 1
            summary.isolated_paths.append(spath)
        if progress is not None:
            # `i`, nie `summary.files`: do 0810 były równe (jeden plik = jeden przyrost), ale odsiew
            # pochodnych rozdzielił te dwie liczby. `total` to długość PRZEJŚCIA, więc licznikiem
            # postępu musi być indeks przejścia — inaczej pasek nie domyka się do 100%.
            progress(i, total, spath, summary)
    return summary
