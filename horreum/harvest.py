"""Żniwa z wyjścia WBPP - które mastery i stosy wciągnąć do archiwum, dokąd i jak nazwane.

Wydanie obiektu (`projection.plan_object`) oddaje WBPP lighty, gotowe mastery i surowe flaty; WBPP
buduje z surowych flatów nowe masterflaty, a z lightów stosy, które dziś zostają w warsztacie. Ten
moduł odpowiada, które z nich archiwum jeszcze nie ma i gdzie mają leżeć. Plików NIE mutuje i do
bazy NIE pisze (bramki `test_writeback_safety` i `test_repo_safety`): `plan` czyta bazę i dysk,
`apply` woła klingę `projection.copy_master` (kopia `.part`, audyt bajtów, publikacja bez
nadpisania) oraz `projection.write_harvest_manifest`. O nowym masterze baza dowie się zwykłym łańcuchem Dostawy
(`scan → … → calibrate → lineage`) na katalogach, które zwraca `apply` - rodzaj, profil i powiązania
z lightami liczy silnik z NAGŁÓWKA kopii, więc żniwa niczego w `calibration` nie zapisują.

ŚWIADEK PROWENIENCJI = NAZWA WEJŚCIA rozstrzygana BAZĄ. Historia PixInsighta (`ProcessingHistory`)
niesie wyłącznie ścieżki wejść, a wejściem masterflatu jest klatka już skalibrowana przez WBPP (inne
bajty niż surowy flat), więc tożsamości bajtowej nie ma czym dowieść. Zmierzone 2026-10-10 na żywej
`pf4`: nazwy surowych flatów są w archiwum unikalne (2 257 nazw na 2 257 kopii), a nazwa wejścia to
nazwa surowego flatu + `_c` + `.xisf`. Nazwa → klatka → profil → noc; nazwa dwóch klatek to odmowa,
nigdy zgadywanie. Manifest wydania (`_PROJEKCJA.json`) nad wyjściem jest DRUGIM świadkiem (nazywa
wydanie i zestaw), nie warunkiem. Ryzyko szczątkowe nazwane: plik podstawiony ręką pod nazwą klatki
z bazy przejdzie jako jej potomek.

RODZAJ = TEN, KTÓRY NADA SKAN KOPII (`scan._derive_kind`, ta sama funkcja, którą skan rozstrzyga
rodzaj XISF-a), nie prefiks nazwy. Zmierzone na żywej `pf4`: 11 starych masterów z `IMAGETYP='FLAT'`
baza liczy jako SUROWE flaty, a jeden z nich trafił do `FLAT_RAW` realnego wydania - master wpisany
jako surowy flat wraca do wydań jako wejście WBPP. Wciągnąć wolno wyłącznie plik, któremu skan nada
`master_flat`; `masterFlat*` z innym rodzajem idzie do przeglądu (`header_mismatch`).

MASTERY FLAT, NIE DARKI. Masterdarki archiwum nie niosą historii, a surowych darków w archiwum nie ma
(wydanie daje darki wyłącznie jako gotowe mastery), więc WBPP z wydania Horreum nie zbuduje masterdarka,
którego proweniencję dałoby się dowieść. `masterDark*`/`masterBias*` idą do przeglądu z powodem
`no_raw_darks` - droga powstanie, gdy w archiwum pojawią się surowe darki (ta sama bijekcja po nazwach
wejść). Wyłącznie XISF: format wyjścia WBPP i 112/112 masterów archiwum; FITS historii nie niesie.

STOSY (`masterLight*`) WYŁĄCZNIE Z WYDANIA HORREUM. Stos idzie do `<archiwum>\\STACKS\\<obiekt>\\<zestaw>\\
<filtr>` - ten sam ogon, pod którym archiwum trzyma lighty jego wejść (`LIGHTS\\<obiekt>\\<zestaw>\\
<filtr>`, zmierzone 2026-10-10 w obu drzewach; jedyna translacja to `OSC` → `NoFilter`). Świadkiem są
NAZWY: wejście historii stosu to nazwa lightu wydania + `_c` + kroki WBPP (`_c_r`, kolor `_c_d_r`),
a manifest wydania niesie nazwy plików, pod którymi WBPP dostał lighty (`names`), więc rename w bazie
po wydaniu dopasowania nie psuje. Stos bez manifestu wydania albo z wejściem spoza niego to przegląd:
taki plik człowiek kopiuje do `STACKS` ręką, a Dostawa go weźmie. Stos z drzewa obróbki wchodzi dalej
drogą „Stosy” (indeks w miejscu); żniwa biorą go dopiero, gdy jego bajtów nie ma w `STACKS` archiwum.
Stos z grupy skalibrowanej masterem spoza swojego zestawu (dwa wydania w jednej sesji WBPP grupowanej
bez `TELESCOP`) zostaje w przeglądzie (`audit_calibration`). Rodowód stosu zapisuje łańcuch Dostawy
oknem czasu; zbiór DOKŁADNY wejść wraca w `HarvestItem.frame_ids`, a do bazy wnosi go
`stacks.record_harvest_inputs` po łańcuchu - nie ten moduł.

„JUŻ W ARCHIWUM" PRZED PROWENIENCJĄ. Plik, którego `sha1_data` baza zna, jest w archiwum niezależnie
od rodzaju i od tego, czy jego wejścia da się dziś rozstrzygnąć - zmierzone: 75/75 archiwalnych
masterflatów ma w historii wejścia ze starych warsztatów, z których żadne nie trafia w nazwę
surowego flatu bazy, więc kolejność odwrotna nazwałaby kopię bajtową „nieznanymi wejściami".
"""

from __future__ import annotations

import dataclasses
import html
import json
import os
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from . import hashing, naming, projection, scan, stacks
from .gui import queries
from .resolve._coerce import _to_float, _to_int, _to_text
from .resolve.cameras import normalize_camera
from .resolve.filters import normalize_filter
from .resolve.frames import kind_dir_segments
from .resolve.paths import CATEGORY_DIRS, STACKS_DIR
from .resolve.stack import read_testimony

# Konwencja archiwum (Custos): `CALIBRATION\masters\flats\<zestaw>\<filtr>`. Folder, a nie tabela,
# bo silnik go nie potrzebuje - skan klasyfikuje po `IMAGETYP`, kalibracja czyta nagłówek, a `FLATGRP`
# czyta nazwę. Folder jest dla człowieka i Eksploratora; żniwa trzymają się go, żeby wciągnięty master
# leżał tam, gdzie człowiek szuka reszty.
MASTERS_SUBDIR = (projection.CALIBRATION_SEGMENT, "masters", "flats")
# Biblioteka stosów archiwum: nazwa ma jednego właściciela (`resolve.paths.STACKS_DIR`, porównanie bez
# wielkości liter), a segment składany na dysku pisze się wielkimi literami jak `CALIBRATION` i `LIGHTS`.
STACKS_SEGMENT = STACKS_DIR.upper()
_NOFILTER = "NoFilter"         # folder stosów kamery kolorowej (`LIGHTS\…\OSC` ↔ `STACKS\…\NoFilter`)
_RELEASE_MASTER = "MASTER"     # rola folderu masterów w wydaniu obiektu (`projection.plan_object`)
_WBPP_MASTER = "master"        # katalog masterów w wyjściu WBPP
CALIBRATED_DIR = "calibrated"  # katalog klatek skalibrowanych w wyjściu WBPP (`audit_calibration`)

_FLAT_PREFIX = "masterflat"
_DARK_PREFIXES = ("masterdark", "masterbias")
_LIGHT_PREFIX = "masterlight"
_PREFIXES = (_FLAT_PREFIX, *_DARK_PREFIXES, _LIGHT_PREFIX)
_SEQ_DIGITS = 10                                        # cyfra kolejności grupy flatu: 0..9
_STACK_SUFFIXES = 10                                    # nazwa stosu: goła, `WBPP_<data>`, `_2`..`_9`
_DETAIL_NAMES = 3                                       # ile nazw wejść cytuje powód odmowy
_TESTIMONY_DEPTH = 2                                    # ile poziomów pod wyjściem szuka zeznań żniw

# Powody `review` - JEDYNY właściciel listy. Dialog ma literalną mapę token → klucz i18n i test
# parytetu z tą krotką (bramka i18n nie widzi kluczy składanych dynamicznie).
REASONS = ("no_raw_darks", "unreadable", "no_history", "no_inputs", "inputs_unknown",
           "inputs_ambiguous", "mixed_profile", "no_profile", "no_night", "header_mismatch",
           "outside_release", "no_config", "name_taken", "no_release", "no_light_seat",
           "color_unknown", "foreign_calibration")
# Statusy pozycji - JEDYNY właściciel listy (dialog: literalna mapa na klucze i18n + test parytetu).
# Trzy pierwsze daje plan, reszta to wynik kopii po `apply`.
STATUSES = ("would-place", "exists", "review", "placed", "verify_bad", "conflict", "error", "cancelled")


class HarvestCancelled(Exception):
    """Sonda żniw przerwana na żądanie wołającego (`should_cancel` w `discover`/`plan`). Planu
    częściowego nie ma: pozycje policzone przed przerwaniem nie są obrazem wyjścia WBPP, więc wołający
    porzuca wynik, zamiast pokazać połowę katalogu jako całość."""


def discover(wbpp_dir, *, should_cancel=None):
    """Kandydaci żniw w drzewie wyjścia WBPP: pliki XISF (`scan.XISF_SUFFIXES`), rekurencyjnie, których
    nazwa (bez wielkości liter) zaczyna się od `masterflat`, `masterdark`, `masterbias` albo
    `masterlight`. Stos wyłącznie bez znacznika pochodnej obróbki (`scan.is_derived_name` - ten sam
    właściciel granicy, co sito skanu): `…_starless.xisf` obok stosu to produkt obróbki, nie stos, a
    `…_autocrop.xisf` jest wariantem obrazu i wchodzi. FITS pominięte (historii w nim nie ma). Brak
    katalogu = pusta lista. Posortowane po pełnej ścieżce - kolejność planu i nazw. `should_cancel()`
    sprawdzane przy każdym katalogu (drzewo warsztatu po SMB bywa duże) → `HarvestCancelled`."""
    out = []
    for dirpath, _dirnames, filenames in os.walk(wbpp_dir):
        if should_cancel is not None and should_cancel():
            raise HarvestCancelled(wbpp_dir)
        for name in filenames:
            low = name.lower()
            if os.path.splitext(low)[1] not in scan.XISF_SUFFIXES or not low.startswith(_PREFIXES):
                continue
            if low.startswith(_LIGHT_PREFIX) and scan.is_derived_name(name):
                continue
            out.append(os.path.join(dirpath, name))
    return sorted(out)


def raw_stem(path):
    """Rdzeń nazwy surowego flatu z BAZY: basename bez rozszerzenia, małymi literami, nic więcej.
    Separatory `/` i `\\` oba. Strona bazy NIE zdejmuje `_c`: nazwa surowego flatu nigdy nie niesie
    dopisku WBPP, więc surowy `…_c.fits` jest własną nazwą klatki, a jego wejście w historii to
    `…_c_c.xisf` (`input_stem` zdejmie jedno `_c` i trafi)."""
    return os.path.splitext(re.split(r"[\\/]", str(path))[-1])[0].lower()


def input_stem(path):
    """Rdzeń nazwy wejścia z HISTORII mastera: `raw_stem` bez KOŃCOWEGO sufiksu `_c`. Asymetria wobec
    `raw_stem` jest celowa: dopisek `_c` stawia WBPP po kalibracji, więc zdejmuje go wyłącznie strona
    historii.

    Zmierzona nazwa wejścia masterflatu: `D:/WBPP/2023-05-07/FLAT/2023-05-07_20-40-03_CLS_-11.90_
    0.08s_0049_c.xisf` - nazwa surowego flatu z bazy + `_c` (klatka skalibrowana przez WBPP)
    + `.xisf`. Inne sufiksy WBPP (`_cc`, `_d`, `_r`) świadomie nie: do masterflatu wchodzą klatki
    prosto po kalibracji, a nietrafiona nazwa kończy się `inputs_unknown`, nie zgadywaniem."""
    stem = raw_stem(path)
    return stem[:-2] if stem.endswith("_c") else stem


# ============================================================ zeznanie pliku mastera


@dataclasses.dataclass(frozen=True)
class MasterTestimony:
    """Co plik mastera mówi o sobie. `kind` = rodzaj, który nada mu skan kopii (nie prefiks nazwy).
    `inputs_enabled` = ścieżki włączonych wejść historii; `rows` = ile wejść deklaruje historia
    (`None` = historii brak). `sha1_data` i `file_sha1` z JEDNEGO przebiegu `scan_file`: tożsamość
    danych do pytania bazy i sha1 całego pliku - bajty, których apply wymaga od kopii. `exptime` =
    `EXPTIME` jako liczba (XISF niesie tekst `600.000`), brak = `None` - stos porównuje go z lightami
    wejść progiem `stacks.exposure_matches` i niesie w nazwie."""
    path: str
    kind: str
    header: dict
    inputs_enabled: tuple
    rows: object
    sha1_data: str
    file_sha1: str
    filter_raw: object
    xbinning: object
    date_obs: object
    exptime: object = None


def read_master(path, *, meta_reader=scan.read_xisf_meta_full, identity_reader=scan.scan_file):
    """Zeznanie pliku mastera z XISF. Nagłówek i tekst XML z `meta_reader` (historia - tekst jak
    w `stacks._read_history_xml`), tożsamość i rodzaj z rekordu `identity_reader` - ten sam rekord,
    z którego skan wyprowadzi klatkę (`scan._derive_kind`), więc żniwa nie mają własnej mapy rodzaju.
    Wyjątek czytnika i nieobliczalna tożsamość danych lecą do wołającego (`plan` kładzie pozycję
    `review` `unreadable` z treścią wyjątku)."""
    meta = meta_reader(path)
    header = dict(meta.header or {})
    testimony = read_testimony(header, meta.xml_bytes.decode("utf-8", "replace"))
    rec = identity_reader(path)
    if rec.sha1_data is None:
        raise ValueError(f"tożsamość danych nieobliczalna ({rec.error or 'brak bloku danych'})")
    kind, _source = scan._derive_kind(rec, readable=rec.header is not None,
                                      is_raw=scan._filetype(rec.path) == "raw")
    h = {str(k).upper(): v for k, v in header.items()}
    return MasterTestimony(
        path=str(path), kind=kind, header=header,
        inputs_enabled=tuple(i.path for i in testimony.inputs if i.enabled),
        rows=testimony.rows, sha1_data=rec.sha1_data, file_sha1=rec.file_sha1,
        filter_raw=testimony.filter_raw, xbinning=_to_int(h.get("XBINNING")),
        date_obs=h.get("DATE-OBS"), exptime=_to_float(h.get("EXPTIME")))


# ============================================================ PLAN (odczyt bazy i dysku)


@dataclasses.dataclass
class HarvestItem:
    """Jeden plik wyjścia WBPP. Statusy planu: `would-place` · `exists` · `review`; po `apply`:
    `placed` · `verify_bad` · `conflict` · `error` · `cancelled`. `reason` = token z `REASONS`
    (wyłącznie `review`), `reason_n` = liczność powodu (ile wejść, ile profili, ile nocy),
    `detail` = treść dla człowieka (wyjątek czytnika, pierwsze nazwy wejść, co się nie zgadza, powód
    klingi po `apply`). `release` = `(object_canon, zestaw)` z manifestu-świadka albo `None`;
    `exists_path` = gdzie archiwum już ma te bajty (baza albo dysk siedziby; `None` przy klatce bez
    obecnej kopii). `zestaw` = segment zestawu Horreum (jak w wydaniu, `76EDPH_ASI2600MM`), nie folder
    siedziby - folder archiwum (`76EDPH_2600MM`) niesie `dst`. Stos (`kind='master_light'`) niesie
    w `frame_ids` DOKŁADNY zbiór lightów wejść (nazwy historii ↔ nazwy wydania), który po łańcuchu
    Dostawy zapisuje `stacks.record_harvest_inputs`.

    `known_to_db` mówi coś wyłącznie przy `exists`: `False`, gdy te bajty leżą w siedzibie archiwum,
    a baza nie zna TEJ kopii (`exists_path` nie jest obecną lokacją klatki o tym `sha1_data` - kopia
    wciągnięta, nieprzyjęta). Przyjęcie ma wtedy czego szukać, choć bieg nie położył nic nowego.
    Każda inna pozycja zostaje przy `True` (nie ma czego przyjmować).

    `src_mtime_ns` = `st_mtime_ns` pliku wyjścia w chwili planu (stat PRZED odczytem; `None`, gdy pliku
    już nie ma). Jedzie do zeznania biegu: `releases` uznaje plik za wciągnięty tylko wtedy, gdy dziś
    ma ten sam czas - `apply` przenosi `exists` z planu bez ponownego audytu, więc plik nadpisany przez
    WBPP między planem a `apply` nie może wyglądać na wciągnięty."""
    src: str
    kind: str
    status: str
    reason: str | None = None
    reason_n: int | None = None
    dst: str | None = None
    name: str | None = None
    profile_id: int | None = None
    frame_ids: tuple = ()
    nights: tuple = ()
    zestaw: str | None = None
    filter_segment: str | None = None
    sha1_data: str | None = None
    file_sha1: str | None = None
    exists_path: str | None = None
    release: tuple | None = None
    detail: str | None = None
    known_to_db: bool = True
    src_mtime_ns: int | None = None


@dataclasses.dataclass(frozen=True)
class HarvestPlan:
    """Wynik `plan`: pozycje w kolejności nazw plików. `manifest_root` = korzeń wydania z manifestu-
    świadka (`None` bez manifestu); `wbpp_dir` = katalog wyjścia, w którym `apply` zostawi zeznanie
    biegu `_ZNIWA_<znacznik>.json`. `archive_root` = korzeń archiwum, pod którym leżą biblioteki
    `CALIBRATION` i `STACKS` (wskazanie `…\\CALIBRATION` daje korzeń przed segmentem, `library_root`)
    - jedyna podstawa guardu kopii (`projection.copy_master(..., library_root=...)`)."""
    items: list
    manifest_root: str | None
    wbpp_dir: str | None = None
    archive_root: str | None = None


def _split_at(path, nazwy):
    """`(korzeń przed segmentem, ogon od niego włącznie)` dla PIERWSZEGO od korzenia segmentu z `nazwy`
    (bez wielkości liter, ścieżka znormalizowana, separatory `\\` i `/`) albo `None`, gdy żadnego nie ma."""
    cur, wstecz = os.path.normpath(str(path)), []
    while True:
        head, tail = os.path.split(cur)
        if not tail:
            break
        wstecz.append((head, tail))
        cur = head
    segmenty = list(reversed(wstecz))                    # od korzenia
    szukane = {n.lower() for n in nazwy}
    for i, (head, tail) in enumerate(segmenty):
        if tail.lower() in szukane:
            return head, tuple(t for _h, t in segmenty[i:])
    return None


def _split_at_calibration(path):
    """`_split_at` na segmencie `CALIBRATION` - pytania o MASTERY: ogon siedziby masterflatu i korzeń
    archiwum, który pamięta baza (`archive_root_from_db`). Mastery leżą wyłącznie pod `CALIBRATION`,
    więc `STACKS` tu nie tnie."""
    return _split_at(path, (projection.CALIBRATION_SEGMENT,))


def _calibration_tail(katalog):
    """Ogon ścieżki od segmentu `CALIBRATION` włącznie albo `None` (`_split_at_calibration`)."""
    ciecie = _split_at_calibration(katalog)
    return None if ciecie is None else ciecie[1]


def library_root(archive_root):
    """Korzeń archiwum, pod którym leżą biblioteki `CALIBRATION` i `STACKS`: część `archive_root` PRZED
    pierwszym segmentem `CALIBRATION` albo `STACKS` (nazwa stosów z `resolve.paths.STACKS_DIR`, bez
    wielkości liter), gdy go ma - wskazanie `R:\\ASTRO_\\CALIBRATION` albo `R:\\ASTRO_\\STACKS` dawałoby
    inaczej `…\\CALIBRATION\\CALIBRATION\\…` i `…\\STACKS\\STACKS\\…`; bez segmentu - `archive_root` bez
    zmian. Pusty korzeń po cięciu (ścieżka względna zaczynająca się od biblioteki) → `ValueError`
    (EXPECT)."""
    ciecie = _split_at(archive_root, (projection.CALIBRATION_SEGMENT, STACKS_DIR))
    if ciecie is None:
        return archive_root
    if not ciecie[0]:
        raise ValueError(f"archiwum bez korzenia przed {ciecie[1][0]}: {archive_root!r}")
    return ciecie[0]


def archive_root_from_db(con):
    """Korzeń archiwum, który pamięta baza: najliczniejszy prefiks PRZED pierwszym segmentem
    `CALIBRATION` wśród katalogów obecnych kopii aktywnych masterflatów
    (`queries.master_flat_dirs_by_profile`, liczności sumowane, bez wielkości liter, remis
    alfabetycznie); brak takich kopii → `None`. Gospodarz podaje go jako domyślne archiwum żniw, a dialog
    ostrzega, gdy wskazane ręką różni się od niego - archiwum wskazane ręką zostaje jedynym celem
    zapisu."""
    licznik, forma = Counter(), {}
    for katalogi in queries.master_flat_dirs_by_profile(con).values():
        for katalog, n in katalogi:
            ciecie = _split_at_calibration(katalog)
            if ciecie is None or not ciecie[0]:
                continue
            klucz = ciecie[0].lower()
            licznik[klucz] += n
            forma.setdefault(klucz, ciecie[0])
    if not licznik:
        return None
    return forma[min(licznik, key=lambda k: (-licznik[k], k))]


def _own_tails(katalogi):
    """`[(ogon, liczba kopii)]` katalogów, w których archiwum trzyma mastery TEGO profilu."""
    return [(ogon, n) for katalog, n in katalogi if (ogon := _calibration_tail(katalog)) is not None]


def _rig_tails(profile_id, facts, facts_by_profile, dirs_by_profile, filter_segment):
    """`[(ogon, liczba kopii)]` siedziby złożonej z katalogu ZESTAWU rodzeństwa: profile tego samego
    configu (teleskop kanoniczny + kamera), innego filtru. Rodzeństwo świadczy wyłącznie wtedy, gdy
    ostatni segment jego katalogu to jego własny segment filtru - wtedy konwencja `<zestaw>\\<filtr>`
    jest dowiedziona i ogon tego profilu to katalog zestawu + jego segment filtru.

    Po co: nazwy folderów zestawu w archiwum to konwencja Custosa (`76EDPH_2600MM`), a segment
    zestawu Horreum (`zestawy_configow`) to `76EDPH_ASI2600MM` - zmierzone na żywej `pf4` 2026-10-10:
    33/33 profile flatu z masterem mają folder inny niż ścieżka złożona. Pierwszy master profilu
    (5 profili ma dziś surowe flaty i żadnego mastera) bez tego szczebla założyłby równoległe drzewo
    obok folderu, w którym człowiek trzyma resztę masterów tej optyki."""
    if facts["config_id"] is None:
        return []
    out = []
    for pid, katalogi in dirs_by_profile.items():
        f = facts_by_profile.get(pid)
        if pid == profile_id or f is None or f["config_id"] != facts["config_id"]:
            continue
        filtr = projection._filter_segment(f["filter_canon"], f["is_mono"]).lower()
        for ogon, n in _own_tails(katalogi):
            if len(ogon) > 1 and ogon[-1].lower() == filtr:
                out.append((ogon[:-1] + (filter_segment,), n))
    return out


def _seat(archive_root, ogony):
    """Siedziba = `archive_root` + najliczniejszy OGON (ścieżka od segmentu `CALIBRATION`). Archiwum
    wskazane ręką jest jedynym celem zapisu - ekran pokazuje ten korzeń, więc kopia nie może iść do
    korzenia, który pamięta baza (wizytacja na kopii archiwum w scratchu napisałaby inaczej na `R:`).
    Przy `archive_root` równym korzeniowi bazy wynik jest katalogiem z bazy. Liczność po ogonach (ten
    sam ogon pod dwoma korzeniami sumuje kopie, bez wielkości liter), remis alfabetycznie. Brak
    kandydata → `None`."""
    licznik, forma = Counter(), {}
    for ogon, n in ogony:
        klucz = tuple(s.lower() for s in ogon)
        licznik[klucz] += n
        forma.setdefault(klucz, ogon)
    if not licznik:
        return None
    klucz = min(licznik, key=lambda k: (-licznik[k], k))
    return os.path.join(archive_root, *forma[klucz])


def _on_disk(seat, night8, filter_segment, src, file_sha1):
    """Te same bajty już leżą w siedzibie (idempotencja BEZ skanu: żniwa powtórzone przed Dostawą)?
    Kandydaci = pliki grupy tej nocy i filtru (`MASTERFLAT_FLATGRP_<noc>?_FILTER_<filtr>_.xisf`)
    o rozmiarze źródła; dopiero ich sha1 całego pliku porównujemy z `file_sha1`. Siedziby jeszcze
    nie ma → `None`."""
    sufiksy = "|".join(re.escape(s) for s in scan.XISF_SUFFIXES)
    rx = re.compile(rf"MASTERFLAT_FLATGRP_{night8}[0-9]_FILTER_{re.escape(filter_segment)}_(?:{sufiksy})",
                    re.IGNORECASE)
    try:
        names = sorted(os.listdir(seat))
    except FileNotFoundError:
        return None
    size = os.path.getsize(src)
    for name in names:
        p = os.path.join(seat, name)
        if rx.fullmatch(name) and os.path.getsize(p) == size and hashing.sha1_of(p) == file_sha1:
            return p
    return None


def _release(witness, frame_ids):
    """Zestaw wydania, którego `flat_raw` obejmuje wszystkie wejścia → `(object_canon, zestaw)`;
    żaden → `None`. Manifest zna wejścia wyłącznie jako listy id pod tymi samymi nazwami, więc
    tożsamości nie dokłada - nazywa wydanie."""
    zestawy = witness.get("zestawy")
    if not isinstance(zestawy, dict):
        return None
    ids = set(frame_ids)
    for seg in sorted(zestawy):
        z = zestawy[seg]
        if isinstance(z, dict) and ids <= set(z.get("flat_raw") or ()):
            return (witness.get("object_canon"), seg)
    return None


def _names(paths):
    """Pierwsze nazwy wejść do zdania odmowy (basename w kolejności historii)."""
    return ", ".join(re.split(r"[\\/]", str(p))[-1] for p in paths[:_DETAIL_NAMES])


def _review(item, reason, n=None, detail=None):
    """Odmowa pozycji planu: status `review`, token z `REASONS`, liczność i treść dla człowieka."""
    assert reason in REASONS, reason
    item.status, item.reason, item.reason_n, item.detail = "review", reason, n, detail


# ============================================================ stosy: świadek nazwy i siedziba


def _path_key(path):
    """Klucz porównania ścieżek bez wielkości liter i separatorów (NTFS): `normcase(normpath)`."""
    return os.path.normcase(os.path.normpath(str(path)))


def _under(path, directory):
    """Czy `path` leży pod `directory` (leksykalnie, bez dotykania dysku)."""
    return _path_key(path).startswith(_path_key(directory) + os.sep)


def _object_witness(manifest):
    """Manifest wydania obiektu albo `None` (inny układ, brak, nie-dict) - jedno pytanie dla planu
    i dla audytu kalibracji."""
    if isinstance(manifest, dict) and manifest.get("layout") == projection.OBJECT_LAYOUT:
        return manifest
    return None


def _names_index(witness, copies=None):
    """Rdzeń nazwy lightu (`raw_stem`) → `{(zestaw, frame_id)}` ze zbioru wydania. Nazwy z manifestu
    (`names` - pod tymi nazwami WBPP dostał lighty); zestaw zapisany przed tym polem bierze nazwy
    obecnych kopii swoich lightów z bazy (`copies`, `queries.light_copies`), a bez bazy (`copies=None`,
    audyt kalibracji) nie świadczy. `frame_id` `None` = nazwa dwóch klatek w zestawie (manifest)."""
    index = {}
    zestawy = witness.get("zestawy") if witness is not None else None
    if not isinstance(zestawy, dict):
        return index
    for seg in sorted(zestawy):
        z = zestawy[seg]
        if not isinstance(z, dict):
            continue
        if isinstance(z.get("names"), dict):
            pary = list(z["names"].items())
        elif copies is not None:
            ids = [i for i in (z.get("lights") or ()) if isinstance(i, int)]
            pary = [(p, fid) for fid, paths in copies(ids).items() for p in paths]
        else:
            continue
        for name, fid in pary:
            index.setdefault(raw_stem(name), set()).add((seg, fid))
    return index


def _match_stem(stem, index):
    """Trafienia rdzenia wejścia w nazwy wydania: lighty `L`, dla których
    `re.fullmatch(re.escape(L) + r"_c(?:_.*)?", stem)` - wejście to nazwa lightu + `_c` (kalibracja WBPP)
    i dalsze kroki po `_` (`_c_r`, `_c_d_r`). Liczone po pozycjach `_c` w rdzeniu wejścia, nie po
    wszystkich nazwach wydania: `L` jest prefiksem rdzenia ucięciem tuż przed takim `_c`. Wejście
    `a_crop_c_r` NIE trafia w light `a` (po `_c` stoi `r`, nie `_`)."""
    hits = set()
    for i in range(len(stem) - 1):
        if stem[i:i + 2] == "_c" and (i + 2 == len(stem) or stem[i + 2] == "_"):
            hits |= index.get(stem[:i], set())
    return hits


def _light_tail(path):
    """Katalogi po PIERWSZYM segmencie lightów (`LIGHTS` - marker rodzaju `light` z
    `resolve.frames.kind_dir_segments`, ten sam, który nadał klatce rodzaj) od korzenia, bez nazwy
    pliku; brak markera → `None`. Dowolny korzeń, jak `_split_at_calibration`: archiwum na `R:` i jego
    kopia w scratchu dają ten sam ogon."""
    dirs = [s for s in re.split(r"[\\/]+", os.path.normpath(str(path))) if s][:-1]
    markers = kind_dir_segments()
    for i, seg in enumerate(dirs):
        if markers.get(seg.strip().lower()) == "light":
            return tuple(dirs[i + 1:])
    return None


def _stack_on_disk(seat, src, file_sha1):
    """Te same bajty już leżą w siedzibie stosu (idempotencja BEZ skanu: żniwa powtórzone przed
    Dostawą)? Kandydaci = `.xisf` siedziby o rozmiarze źródła; prefiks treści (`projection._same_content`)
    odsiewa inne stosy tej samej geometrii przed pełnym sha1 (stos to setki MB, często po SMB).
    Siedziby jeszcze nie ma → `None`."""
    try:
        names = sorted(os.listdir(seat))
    except (FileNotFoundError, NotADirectoryError):
        return None
    ss = os.stat(src)
    for name in names:
        p = os.path.join(seat, name)
        if not name.lower().endswith(scan.XISF_SUFFIXES) or not os.path.isfile(p):
            continue
        ds = os.stat(p)
        if projection._same_content(src, p, ss, ds) and hashing.sha1_of(p) == file_sha1:
            return p
    return None


def _stack_header_mismatch(t, fakty):
    """Pierwsza oś nagłówka stosu niezgodna z lightami wejść → opis osi do `detail` (DANE), zgodny →
    `None`. Filtr kanonem (`normalize_filter`), ekspozycja progiem (`stacks.exposure_matches` - jedyny
    właściciel), `TELESCOP` jak w grupowaniu (`strip`, wobec `telescop_canon` configu lightów),
    `INSTRUME` przez `normalize_camera` (wobec modelu kamery lightów). `OBJECT` nie jest porównywany:
    WBPP przepisuje kartę lightu, a ta bywa potoczna (`Heart of the Soul Nebula`) - obiekt sprawdza
    oś obiektu po Dostawie. `DATE-OBS` waliduje nazwa (`naming.stack_name`)."""
    h = {str(k).upper(): v for k, v in t.header.items()}
    fakty = list(fakty)
    filtr = normalize_filter(t.filter_raw)
    filtry = sorted({f["filter_canon"] for f in fakty}, key=str)
    if filtry != [filtr]:
        return f"FILTER {t.filter_raw!r} -> {filtr!r} != {filtry!r}"
    if not all(stacks.exposure_matches(t.exptime, f["exptime"]) for f in fakty):
        return f"EXPTIME {t.exptime!r} != {sorted({f['exptime'] for f in fakty}, key=str)!r}"
    teleskop = (_to_text(h.get("TELESCOP")) or "").strip() or None
    teleskopy = sorted({f["telescope_canon"] for f in fakty}, key=str)
    if teleskop not in teleskopy:
        return f"TELESCOP {teleskop!r} not in {teleskopy!r}"
    kamera = normalize_camera(_to_text(h.get("INSTRUME")))
    kamery = sorted({f["camera_canon"] for f in fakty}, key=str)
    if kamera not in kamery:
        return f"INSTRUME {h.get('INSTRUME')!r} -> {kamera!r} not in {kamery!r}"
    return None


@dataclasses.dataclass
class _StackContext:
    """Materiał planu wspólny dla stosów jednego wyjścia (liczony raz, przy pierwszym stosie)."""
    stacks_root: str
    witness: dict | None
    names: dict
    findings: dict


def _plan_stack(con, item, t, ctx, reserved):
    """Rozstrzygnij pozycję stosu (`kind='master_light'`) - kroki w kolejności, pierwsza odmowa kończy:

    1. tożsamość: klatka wycofana → `exists`; aktywna z obecną kopią pod `<archiwum>\\STACKS` →
       `exists`; aktywna bez takiej kopii (wciągnięta drogą „Stosy” z drzewa obróbki) → dalej;
    2. manifest wydania obiektu wymagany → inaczej `no_release` (`detail` = biblioteka `STACKS`, do
       której człowiek kopiuje taki stos ręką);
    3. historia: brak → `no_history`, zero włączonych wejść → `no_inputs`;
    4. wejścia ↔ nazwy wydania (`_match_stem`): wejście trafiające w dwie klatki → `inputs_ambiguous`,
       bez trafienia → `outside_release`, wejścia z kilku zestawów → `outside_release` (wejścia spoza
       zestawu większości); jeden zestaw → `release`, `frame_ids`;
    5. lighty z manifestu, których baza nie zna jako lightów → `inputs_unknown`; nagłówek wobec lightów
       (`_stack_header_mismatch`) → `header_mismatch` z osią w `detail`;
    6. kalibracja cudzym masterem (`audit_calibration`) → `foreign_calibration` z jego ścieżką;
    7. siedziba z ogona lightów (`_light_tail` każdej obecnej kopii każdego lightu): jeden wspólny ogon
       `<obiekt>\\<zestaw>\\<filtr>` bez kategorii (`CATEGORY_DIRS`) → `<archiwum>\\STACKS\\<ogon>`
       z `OSC` → `NoFilter`; brak kopii pod `LIGHTS`, dwa ogony, kategoria albo inna głębokość →
       `no_light_seat` (świadomy koszt - stos bez siedziby człowiek kładzie ręką);
    8. te same bajty w siedzibie → `exists` (`known_to_db`: czy baza zna tę kopię);
    9. nazwa (`naming.stack_name`): `DATE-OBS` nieczytelne → `header_mismatch`, kolor nieczytelny
       z nazwy WBPP → `color_unknown`; nazwa zajęta (dysk, `.part`, baza, wcześniejsza pozycja planu)
       → sufiks `WBPP_<YYYYMMDD mtime źródła>`, dalej `_2`..`_9`, potem `name_taken`."""
    hit = queries.frame_by_sha1_data(con, t.sha1_data)
    obecne = queries.present_paths_by_sha1_data(con, t.sha1_data) if hit is not None else []
    if hit is not None:
        frame_id, present_path, retired_at = hit
        if retired_at is not None:
            item.status, item.exists_path = "exists", present_path
            item.detail = f"frame_id={frame_id} retired_at={retired_at}"
            return
        w_archiwum = [p for p in obecne if _under(p, ctx.stacks_root)]
        if w_archiwum:
            item.status, item.exists_path = "exists", w_archiwum[0]
            return
    if ctx.witness is None:
        _review(item, "no_release", detail=ctx.stacks_root)
        return
    if t.rows is None:
        _review(item, "no_history")
        return
    if not t.inputs_enabled:
        _review(item, "no_inputs")
        return

    wiele, poza, pary = [], [], []
    for p in t.inputs_enabled:
        hits = _match_stem(raw_stem(p), ctx.names)
        if len(hits) > 1 or any(fid is None for _seg, fid in hits):
            wiele.append(p)
        elif not hits:
            poza.append(p)
        else:
            (seg, fid), = hits
            pary.append((p, seg, fid))
    if wiele:
        _review(item, "inputs_ambiguous", len(wiele), _names(wiele))
        return
    if poza:
        _review(item, "outside_release", len(poza), _names(poza))
        return
    licznik = Counter(seg for _p, seg, _f in pary)
    seg = min(licznik, key=lambda s: (-licznik[s], s))
    obce = [p for p, s, _f in pary if s != seg]
    if obce:
        _review(item, "outside_release", len(obce), _names(obce))
        return
    item.frame_ids = tuple(sorted({fid for _p, _s, fid in pary}))
    item.zestaw, item.release = seg, (ctx.witness.get("object_canon"), seg)

    fakty = queries.light_facts(con, item.frame_ids)
    nieznane = [fid for fid in item.frame_ids if (fakty.get(fid) or {}).get("kind") != "light"]
    if nieznane:
        _review(item, "inputs_unknown", len(nieznane),
                ", ".join(str(f) for f in nieznane[:_DETAIL_NAMES]))
        return
    os_naglowka = _stack_header_mismatch(t, fakty.values())
    if os_naglowka is not None:
        _review(item, "header_mismatch", detail=os_naglowka)
        return
    filtr = normalize_filter(t.filter_raw)
    for (f_seg, f_filtr, f_exp), finding in sorted(ctx.findings.items(), key=lambda kv: str(kv[0])):
        if f_seg == seg and f_filtr == filtr and stacks.exposure_matches(f_exp, t.exptime):
            _review(item, "foreign_calibration", detail=f"{finding.kind}={finding.path}")
            return

    ogony = {}
    for paths in queries.light_copies(con, item.frame_ids).values():
        for p in paths:
            ogon = _light_tail(p)
            if ogon is not None:
                ogony.setdefault(tuple(s.lower() for s in ogon), ogon)
    if len(ogony) != 1:
        _review(item, "no_light_seat", len(ogony),
                " | ".join("\\".join(o) for _k, o in sorted(ogony.items())) or None)
        return
    (ogon,) = ogony.values()
    if len(ogon) != 3 or ogon[0].upper() in CATEGORY_DIRS:
        _review(item, "no_light_seat", 1, "\\".join(ogon))
        return
    obiekt, zestaw_dir, filtr_dir = ogon
    if filtr_dir.lower() == projection._OSC.lower():
        filtr_dir = _NOFILTER
    item.filter_segment = filtr_dir
    seat = os.path.join(ctx.stacks_root, obiekt, zestaw_dir, filtr_dir)

    na_dysku = _stack_on_disk(seat, item.src, t.file_sha1)
    if na_dysku is not None:
        item.status, item.exists_path = "exists", na_dysku
        item.known_to_db = any(_path_key(p) == _path_key(na_dysku) for p in obecne)
        return

    if naming.header_dt(t.date_obs) is None:
        _review(item, "header_mismatch", detail=f"DATE-OBS {t.date_obs!r}")
        return
    nazwa_wbpp = os.path.basename(item.src)
    kolor = naming.wbpp_stack_color(nazwa_wbpp)
    if kolor is None:
        _review(item, "color_unknown", detail=nazwa_wbpp)
        return
    warianty = naming.wbpp_stack_variants(nazwa_wbpp)
    dzien = datetime.fromtimestamp(os.path.getmtime(item.src)).strftime("%Y%m%d")
    sufiksy = [None, f"WBPP_{dzien}", *(f"WBPP_{dzien}_{k}" for k in range(2, _STACK_SUFFIXES))]
    try:
        nazwy = [naming.stack_name(obiekt, t.date_obs, zestaw_dir, filtr_dir, t.exptime, kolor,
                                   variants=warianty, suffix=sufiks) for sufiks in sufiksy]
    except ValueError as exc:                             # segment siedziby pusty po `_sanitize`
        _review(item, "no_light_seat", 1, str(exc))
        return
    w_bazie = {_path_key(p) for p in queries.location_paths_in_dir(con, seat)}
    for name in nazwy:
        dst = os.path.join(seat, name)
        klucz = _path_key(dst)
        if (klucz not in reserved and klucz not in w_bazie and not os.path.lexists(dst)
                and not os.path.lexists(dst + projection.PART_SUFFIX)):
            reserved.add(klucz)
            item.status, item.name, item.dst = "would-place", name, dst
            return
    _review(item, "name_taken", len(nazwy))


def plan(con, wbpp_dir, *, archive_root, manifest=None, read=read_master, should_cancel=None):
    """Plan żniw (odczyt bazy i dysku, ZERO zapisu) → `HarvestPlan`. Dla każdego pliku z `discover`,
    w kolejności nazw, pierwsza odmowa kończy rozstrzyganie pozycji:

    1. odczyt (`read`); wyjątek → `review` `unreadable` z treścią wyjątku; rodzaj `master_light`
       (stos) idzie własną drogą od tego miejsca (`_plan_stack`), reszta niżej;
    2. tożsamość w bazie (`sha1_data`) → `exists` - „już w archiwum" wyprzedza rodzaj i proweniencję;
       klatka wycofana też (`detail` z `retired_at`), ale klatka AKTYWNA bez żadnej obecnej kopii
       idzie dalej: wyjście WBPP bywa wtedy jedyną kopią, a skan przypnie ją z powrotem do tej klatki;
    3. rodzaj: prefiks `masterdark`/`masterbias` albo rodzaj `master_dark` → `no_raw_darks`; plik
       `masterflat`, któremu skan nada inny rodzaj niż `master_flat` → `header_mismatch`;
    4. historia: brak → `no_history`, zero włączonych wejść → `no_inputs`;
    5. rdzenie wejść (`input_stem`) → klatki (`queries.flat_locations` po `raw_stem`, dedup po
       `frame_id`): nietrafione → `inputs_unknown`, rdzeń z więcej niż jedną klatką → `inputs_ambiguous`;
    6. profil: klatka bez profilu albo profil spoza profili flatu → `no_profile`, więcej niż jeden →
       `mixed_profile`;
    7. noc: którakolwiek NULL → `no_night`; nazwa bierze najwcześniejszą, więcej nocy to fakt
       raportu (`nights`), nie odmowa - WBPP grupuje flaty po filtrze, nie po nocy;
    8. nagłówek mastera a profil: filtr (`normalize_filter`) albo `XBINNING` inne → `header_mismatch`
       (`INSTRUME`/`TELESCOP` nie, bo teleskop i kamera profilu pochodzą z tych samych klatek);
    9. manifest-świadek (`layout` wydania obiektu): zestaw obejmujący wejścia → `release`, żaden →
       `outside_release`;
    10. segment filtru i nazwy (`naming.master_flat_name` - jedyny właściciel reguły nazwy; jej
        odmowa → `no_config` z danymi w `detail`, nie wyjątek całego planu);
    11. siedziba: korzeń archiwum (`library_root`) + ogon katalogu, w którym archiwum trzyma mastery
        profilu (`_seat`); inaczej katalog zestawu rodzeństwa + segment filtru (`_rig_tails`); inaczej
        `<korzeń>/CALIBRATION/masters/flats/<zestaw>/<filtr>`; bez configu → `no_config`;
    12. te same bajty w siedzibie → `exists` (`_on_disk`, `known_to_db=False`: baza tej kopii nie zna,
        bo klatka bez obecnej kopii doszła tu z kroku 2);
    13. nazwa: najmniejsza cyfra kolejności, której nazwa nie leży na dysku (ani jako plik, ani jako
        porzucony `.part` - wieczny `conflict` klingi) i nie została zarezerwowana przez wcześniejszą
        pozycję tego planu; dziesięć zajętych → `name_taken`; inaczej `would-place` z `dst`.

    `detail` to DANE, nie zdanie (ekran EN pokazuje je dosłownie). `archive_root` pusty → `ValueError`
    (EXPECT): ścieżka złożona bez korzenia pisałaby względem katalogu bieżącego. Manifest-świadka szuka
    wołający (`projection.read_manifest` w `wbpp_dir` i do 4 poziomów w górę) i podaje gotowy dict
    albo `None`. `should_cancel()` sprawdzane w `discover` i przed odczytem każdego pliku →
    `HarvestCancelled`, bez planu częściowego."""
    if not archive_root:
        raise ValueError("plan żniw wymaga archiwum (archive_root) - celu kopii masterów")
    root = library_root(archive_root)
    witness = _object_witness(manifest)
    stack_ctx = None                                      # materiał stosów - przy pierwszym stosie
    by_stem = {}                                          # rdzeń → {frame_id: wiersz}
    for r in queries.flat_locations(con):
        by_stem.setdefault(raw_stem(r["path"]), {}).setdefault(r["frame_id"], r)
    dirs_by_profile = queries.master_flat_dirs_by_profile(con)
    facts_by_profile = queries.flat_profile_facts(con, list(dirs_by_profile))
    zestawy = projection.zestawy_configow(con)
    reserved = set()
    items = []

    for src in discover(wbpp_dir, should_cancel=should_cancel):
        if should_cancel is not None and should_cancel():
            raise HarvestCancelled(wbpp_dir)
        prefix = next(p for p in _PREFIXES if os.path.basename(src).lower().startswith(p))
        try:
            src_mtime_ns = os.stat(src).st_mtime_ns          # PRZED odczytem: zmiana w trakcie = inny czas
        except OSError:
            src_mtime_ns = None
        try:
            t = read(src)
        except Exception as exc:                          # czytnik nie umiera za cały plan
            items.append(HarvestItem(src, "unknown", "review", "unreadable",
                                     detail=f"{type(exc).__name__}: {exc}", src_mtime_ns=src_mtime_ns))
            continue
        item = HarvestItem(src, t.kind, "review", sha1_data=t.sha1_data, file_sha1=t.file_sha1,
                           src_mtime_ns=src_mtime_ns)
        items.append(item)
        if t.kind == "master_light":
            if stack_ctx is None:
                stack_ctx = _StackContext(
                    stacks_root=os.path.join(root, STACKS_SEGMENT), witness=witness,
                    names=_names_index(witness, lambda ids: queries.light_copies(con, ids)),
                    findings=audit_calibration(wbpp_dir, witness) if witness is not None else {})
            _plan_stack(con, item, t, stack_ctx, reserved)
            continue
        hit = queries.frame_by_sha1_data(con, t.sha1_data)
        if hit is not None:
            frame_id, present_path, retired_at = hit
            if retired_at is not None:
                item.status, item.exists_path = "exists", present_path
                item.detail = f"frame_id={frame_id} retired_at={retired_at}"
                continue
            if present_path is not None:
                item.status, item.exists_path = "exists", present_path
                continue
        if prefix in _DARK_PREFIXES or t.kind == "master_dark":
            _review(item, "no_raw_darks")
            continue
        if t.kind != "master_flat":
            imagetyp = {str(k).upper(): v for k, v in t.header.items()}.get("IMAGETYP")
            _review(item, "header_mismatch", detail=f"IMAGETYP={imagetyp!r} -> {t.kind}")
            continue
        if t.rows is None:
            _review(item, "no_history")
            continue
        if not t.inputs_enabled:
            _review(item, "no_inputs")
            continue

        unknown, ambiguous, frames = [], [], {}
        for p in t.inputs_enabled:
            hits = by_stem.get(input_stem(p))
            if not hits:
                unknown.append(p)
            elif len(hits) > 1:
                ambiguous.append(p)
            else:
                frames.update(hits)
        if unknown:
            _review(item, "inputs_unknown", len(unknown), _names(unknown))
            continue
        if ambiguous:
            _review(item, "inputs_ambiguous", len(ambiguous), _names(ambiguous))
            continue
        item.frame_ids = tuple(sorted(frames))
        rows = list(frames.values())

        bez_profilu = sum(1 for r in rows if r["calibration_profile_id"] is None)
        if bez_profilu:
            _review(item, "no_profile", bez_profilu)
            continue
        profiles = sorted({r["calibration_profile_id"] for r in rows})
        if len(profiles) > 1:
            _review(item, "mixed_profile", len(profiles), ", ".join(str(p) for p in profiles))
            continue
        item.profile_id = profiles[0]

        bez_nocy = sum(1 for r in rows if r["night"] is None)
        item.nights = tuple(sorted({r["night"] for r in rows if r["night"] is not None}))
        if bez_nocy:
            _review(item, "no_night", bez_nocy)
            continue
        night8 = item.nights[0].replace("-", "")

        if item.profile_id not in facts_by_profile:
            facts_by_profile.update(queries.flat_profile_facts(con, [item.profile_id]))
        facts = facts_by_profile.get(item.profile_id)
        if facts is None:                                 # profil klatki spoza klasy `flat`
            _review(item, "no_profile", detail=f"profile_id={item.profile_id}")
            continue
        filtr = normalize_filter(t.filter_raw)
        if filtr != facts["filter_canon"]:
            _review(item, "header_mismatch",
                    detail=f"FILTER {t.filter_raw!r} -> {filtr!r} != {facts['filter_canon']!r}")
            continue
        if t.xbinning != facts["xbinning"]:
            _review(item, "header_mismatch", detail=f"XBINNING {t.xbinning!r} != {facts['xbinning']!r}")
            continue

        if witness is not None:
            item.release = _release(witness, item.frame_ids)
            if item.release is None:
                _review(item, "outside_release")
                continue

        if facts["config_id"] is not None and facts["config_id"] in zestawy:
            item.zestaw = zestawy[facts["config_id"]][0]
        item.filter_segment = projection._filter_segment(facts["filter_canon"], facts["is_mono"])
        if item.filter_segment == projection._UNSET:
            _review(item, "no_config", detail=f"profile_id={item.profile_id} filter_canon=None "
                                              f"is_mono={facts['is_mono']}")
            continue
        try:
            names = [naming.master_flat_name(night8, item.filter_segment, seq) for seq in range(_SEQ_DIGITS)]
        except ValueError:
            _review(item, "no_config", detail=f"master_flat_name: night8={night8!r} "
                                              f"filter_segment={item.filter_segment!r}")
            continue
        seat = (_seat(root, _own_tails(dirs_by_profile.get(item.profile_id, ())))
                or _seat(root, _rig_tails(item.profile_id, facts, facts_by_profile,
                                          dirs_by_profile, item.filter_segment)))
        if seat is None:
            if item.zestaw is None:
                _review(item, "no_config", detail=f"profile_id={item.profile_id} config_id={facts['config_id']}")
                continue
            seat = os.path.join(root, *MASTERS_SUBDIR, item.zestaw, item.filter_segment)

        na_dysku = _on_disk(seat, night8, item.filter_segment, src, t.file_sha1)
        if na_dysku is not None:
            item.status, item.exists_path, item.known_to_db = "exists", na_dysku, False
            continue

        for name in names:
            dst = os.path.join(seat, name)
            klucz = os.path.normcase(os.path.normpath(dst))
            if (klucz not in reserved and not os.path.lexists(dst)
                    and not os.path.lexists(dst + projection.PART_SUFFIX)):
                reserved.add(klucz)
                item.status, item.name, item.dst = "would-place", name, dst
                break
        else:
            _review(item, "name_taken", _SEQ_DIGITS)

    manifest_root = witness.get("root") if witness is not None else None
    return HarvestPlan(items=items, manifest_root=manifest_root, wbpp_dir=str(wbpp_dir), archive_root=root)


# ============================================================ APPLY (kopia przez klingę)


@dataclasses.dataclass(frozen=True)
class HarvestResult:
    """Wynik `apply`: wszystkie pozycje planu (kopiowane ze statusem po kopii, reszta bez zmian),
    `placed_dirs` = katalogi z co najmniej jednym `placed` (ich wspólny rodzic to korzeń skanu po
    żniwach), `cancelled` = przerwano przed końcem. `manifest_path` = zapisane zeznanie biegu;
    `manifest_error` = treść błędu jego zapisu (`None` przy sukcesie) - kopie już leżą, więc wynik
    wraca, zamiast zginąć w wyjątku."""
    items: list
    placed_dirs: list
    cancelled: bool
    manifest_path: str | None = None
    manifest_error: str | None = None


def _manifest_payload(harvest_plan, items, cancelled, now):
    """Treść zeznania biegu: cały przebieg, także pozycje, które nie weszły (z powodem)."""
    counts = Counter(it.status for it in items)
    return {
        "wbpp_dir": harvest_plan.wbpp_dir, "manifest_root": harvest_plan.manifest_root, "ts": now,
        "archive_root": harvest_plan.archive_root,
        "cancelled": cancelled, "counts": dict(sorted(counts.items())),
        "items": [{
            "src": it.src, "dst": it.dst, "kind": it.kind, "status": it.status, "reason": it.reason,
            "reason_n": it.reason_n, "detail": it.detail, "sha1_data": it.sha1_data,
            "file_sha1": it.file_sha1, "frame_ids": list(it.frame_ids), "nights": list(it.nights),
            "profile_id": it.profile_id, "release": list(it.release) if it.release else None,
            "exists_path": it.exists_path, "known_to_db": it.known_to_db,
            "src_mtime_ns": it.src_mtime_ns, "ts": now} for it in items],
    }


def apply(harvest_plan, *, now,
          progress: Callable[[int, int, str, str], None] | None = None,
          should_cancel: Callable[[], bool] | None = None,
          copy=projection.copy_master) -> HarvestResult:
    """Wciągnij pozycje `would-place` po kolei: `should_cancel()` PRZED plikiem (ta i dalsze →
    `cancelled`), `copy(src, dst, expected_sha1=file_sha1, library_root=archive_root planu)` → status
    i `detail` z klingi, `progress(done, total, dst, status)` po każdym skopiowanym pliku. Pozycje
    planu z innym statusem przechodzą bez zmian. Plan bez `wbpp_dir` albo - gdy jest co kopiować -
    bez `archive_root` → `ValueError` (przed jakąkolwiek kopią).

    NIE RZUCA PO SKUTKACH UBOCZNYCH: kopie poprzednich pozycji już leżą w archiwum, więc wyjątek
    zgubiłby wynik, który gospodarz ma przekazać do skanu. Wyjątek `copy` spoza katalogu statusów
    (`ValueError` guardu) → pozycja `error` z treścią i pętla idzie dalej; błąd zapisu zeznania →
    `manifest_error`. Zeznanie biegu (`projection.write_harvest_manifest`, nowy plik na bieg) pisze się
    zawsze, także bez `placed` i także przy `BaseException` (przerwanie z klawiatury) - wtedy z wyniku
    częściowego (pozycje nieruszone zostają `would-place`), a wyjątek leci dalej."""
    if not harvest_plan.wbpp_dir:
        raise ValueError("plan żniw bez wbpp_dir - nie ma gdzie zapisać zeznania żniw")
    total = sum(1 for it in harvest_plan.items if it.status == "would-place")
    if total and not harvest_plan.archive_root:
        raise ValueError("plan żniw bez archive_root - kopia nie ma biblioteki archiwum do sprawdzenia")
    done, cancelled = 0, False
    out, placed_dirs = [], set()
    try:
        for it in harvest_plan.items:
            if it.status != "would-place":
                out.append(it)
                continue
            if cancelled or (should_cancel is not None and should_cancel()):
                cancelled = True
                out.append(dataclasses.replace(it, status="cancelled"))
                continue
            try:
                status, why = copy(it.src, it.dst, expected_sha1=it.file_sha1,
                                   library_root=harvest_plan.archive_root)
            except Exception as exc:
                status, why = "error", f"{type(exc).__name__}: {exc}"
            out.append(dataclasses.replace(it, status=status, detail=why))
            if status == "placed":
                placed_dirs.add(os.path.dirname(it.dst))
            done += 1
            if progress is not None:
                progress(done, total, it.dst, status)
    finally:
        items = out + list(harvest_plan.items[len(out):])
        manifest_path = manifest_error = None
        try:
            manifest_path = projection.write_harvest_manifest(
                harvest_plan.wbpp_dir, _manifest_payload(harvest_plan, items, cancelled, now), now=now)
        except OSError as exc:
            manifest_error = f"{type(exc).__name__}: {exc}"
    return HarvestResult(items=items, placed_dirs=sorted(placed_dirs), cancelled=cancelled,
                         manifest_path=manifest_path, manifest_error=manifest_error)


# ============================================================ AUDYT KALIBRACJI (odczyt wyjścia WBPP)

_MASTER_ENABLED_RX = re.compile(r'<parameter id="master(Flat|Dark)Enabled" value="(true|false)"')
_MASTER_PATH_RX = re.compile(r'<parameter id="master(Flat|Dark)Path">([^<]*)</parameter>')
_CALIBRATED_SUFFIXES = tuple("_c" + s for s in scan.XISF_SUFFIXES)   # klatka po kalibracji WBPP


@dataclasses.dataclass(frozen=True)
class Finding:
    """Master spoza zestawu użyty do kalibracji grupy lightów: `kind` = `flat` albo `dark`,
    `path` = ścieżka mastera tak, jak zapisał ją WBPP w historii skalibrowanej klatki."""
    kind: str
    path: str


def _calibration_masters(xml_text):
    """`{"flat"|"dark": ścieżka}` masterów WŁĄCZONYCH w `ImageCalibration` z historii skalibrowanej
    klatki (`PixInsight:ProcessingHistory`, treść zaescape'owana: `masterFlatEnabled` + `masterFlatPath`,
    to samo dla darka; zmierzone 2026-10-10 na realnej klatce `…_c.xisf`). Master wyłączony albo
    z pustą ścieżką nie wchodzi - nie ma czego sprawdzać."""
    hist = html.unescape(xml_text or "")
    wlaczone = {}
    for m in _MASTER_ENABLED_RX.finditer(hist):
        wlaczone.setdefault(m.group(1).lower(), m.group(2) == "true")
    out = {}
    for m in _MASTER_PATH_RX.finditer(hist):
        kind, path = m.group(1).lower(), m.group(2).strip()
        if path and wlaczone.get(kind) and kind not in out:
            out[kind] = path
    return out


def audit_calibration(out_dir, manifest):
    """Tripwire kalibracji cudzym masterem - CZYSTY ODCZYT wyjścia WBPP → `{(zestaw, filtr, exp):
    Finding}` wyłącznie dla grup z cudzym masterem.

    PO CO: dwa wydania w jednej sesji WBPP grupowanej bez `TELESCOP` dostają mastery na krzyż
    (zmierzone przy odbiorze wydania obiektu: masterflaty jednego teleskopu i cudzy dark 15 s dla
    lightów drugiego). Stos takiej grupy wygląda poprawnie i ma poprawne wejścia; zdradza go wyłącznie
    historia klatek skalibrowanych, która niesie pełne ścieżki użytych masterów.

    Dla każdego katalogu pod `<out_dir>\\calibrated` czyta nagłówek PIERWSZEGO `*_c.xisf` (WBPP kalibruje
    grupę jednym kompletem masterów), przypisuje go do zestawu manifestu po nazwie lightu (ta sama
    reguła co wejścia stosu, `_match_stem`; nazwy wyłącznie z manifestu - bez bazy zestaw zapisany przed
    polem `names` nie świadczy) i sprawdza LEKSYKALNIE: master flat ma leżeć pod `<wydanie>\\<zestaw>\\
    MASTER\\` (master z wydania) albo `<out_dir>\\master\\` (zbudowany w tej sesji z surowych flatów
    wydania), master dark pod `<wydanie>\\<zestaw>\\MASTER\\` (darki wydanie daje wyłącznie jako
    mastery). `<wydanie>` = `root` manifestu (gdy brak - katalog nad `out_dir`). Klucz grupy z nagłówka
    klatki: zestaw, filtr kanonem (`normalize_filter`), ekspozycja liczbą. Pierwszy werdykt grupy wygrywa
    (flat przed darkiem).

    BRAK WERDYKTU TO NIE ODMOWA: nie ma `calibrated` (wyjście bez klatek pośrednich), klatki nie da się
    przypisać do zestawu, nagłówka nie da się przeczytać - grupa po prostu nie ma `Finding`."""
    witness = _object_witness(manifest)
    korzen = os.path.join(str(out_dir), CALIBRATED_DIR)
    if witness is None or not os.path.isdir(korzen):
        return {}
    index = _names_index(witness)
    wydanie = witness.get("root") or os.path.dirname(os.path.normpath(str(out_dir)))
    out = {}
    for dirpath, dirnames, filenames in os.walk(korzen):
        dirnames.sort()
        kalibrowane = sorted(n for n in filenames if n.lower().endswith(_CALIBRATED_SUFFIXES))
        if not kalibrowane:
            continue
        hits = _match_stem(raw_stem(kalibrowane[0]), index)
        if len(hits) != 1:
            continue
        ((seg, fid),) = hits
        if fid is None:
            continue
        try:
            meta = scan.read_xisf_meta_full(os.path.join(dirpath, kalibrowane[0]))
        except Exception:                                 # nagłówek nieczytelny: brak werdyktu grupy
            continue
        h = {str(k).upper(): v for k, v in (meta.header or {}).items()}
        klucz = (seg, normalize_filter(h.get("FILTER")), _to_float(h.get("EXPTIME")))
        mastery = _calibration_masters(meta.xml_bytes.decode("utf-8", "replace"))
        swoje = os.path.join(wydanie, seg, _RELEASE_MASTER)
        finding = None
        if "flat" in mastery and not (_under(mastery["flat"], swoje)
                                      or _under(mastery["flat"], os.path.join(str(out_dir), _WBPP_MASTER))):
            finding = Finding("flat", mastery["flat"])
        elif "dark" in mastery and not _under(mastery["dark"], swoje):
            finding = Finding("dark", mastery["dark"])
        if finding is not None:
            out.setdefault(klucz, finding)
    return out


# ============================================================ LISTA WYDAŃ (odczyt kart celu)


@dataclasses.dataclass(frozen=True)
class ReleaseRow:
    """Jedno wydanie obiektu na karcie celu i stan jego wyjścia WBPP. `root` = korzeń karty, z której
    przyszło; `object_root` = `<root>\\OBJECTS\\<obiekt>`; `object_canon` i `ts` (ostatnie wydanie) z jego
    manifestu; `out_dir` = `<object_root>\\out`. `pending` · `done` · `review` = LICZBY kandydatów żniw
    w `out_dir` (`discover`): do wciągnięcia, wciągnięte (zeznanie mówi `placed`/`exists` o pliku
    niezmienionym od tego biegu), do przeglądu (zeznanie mówi `review`). Brak kandydatów = WBPP jeszcze
    nic nie oddał.

    `awaiting_wbpp` = w `out_dir` SĄ kandydaci, ale ostatnie wydanie (`ts` manifestu) jest nowsze niż
    najnowszy z nich: obiekt wydano ponownie (nowe lighty), a WBPP po tym wydaniu jeszcze nie liczył.
    Liczniki dalej opisują wyniki leżące w `out_dir`; to pole mówi, że nie są wynikami OSTATNIEGO
    wydania. Brak kandydatów albo nieczytelny `ts` → `False` (stan „czeka na WBPP” niosą wtedy zera).

    `lineage` = stosy wciągnięte z tego wyjścia, których rodowodu DOKŁADNEGO baza jeszcze nie ma
    (`stacks.harvest_lineage_pending`): `(sha1_data, frame_ids, ścieżka kopii pod STACKS)` - zbiór wejść
    leży wtedy tylko w zeznaniu żniw w tym folderze (AR-104). Liczone wyłącznie z bazą i archiwum
    (`releases(..., archive_root=, con=)`); bez nich puste."""
    root: str
    object_root: str
    object_canon: str | None
    ts: str | None
    out_dir: str
    pending: int
    done: int
    review: int
    awaiting_wbpp: bool = False
    lineage: tuple = ()


def _iso_timestamp(value):
    """Znacznik czasu ISO → sekundy epoki albo `None` (brak, śmieć) - bez zgadywania formatu.
    Zeznanie żniw i manifest wydania niosą ISO ZE STREFĄ (pisarzem jest `now` okna: UTC `+00:00`);
    znacznik naiwny, bez strefy, `datetime.timestamp` liczy jako czas LOKALNY tej maszyny."""
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _harvest_testimonies(out_dir):
    """Zeznania żniw (`_ZNIWA_*.json`) w `out_dir` i do `_TESTIMONY_DEPTH` poziomów pod nim (okno żniw
    zapisuje zeznanie tam, gdzie człowiek wskazał wyjście: `out` albo `out\\master`), PARSOWANE:
    `[(ts, archiwum, {klucz ścieżki src: pozycja})]` od najnowszego. `archiwum` = klucz ścieżki
    (`_path_key`) korzenia archiwum biegu albo `None` (zeznanie bez tego pola); `pozycja` = dict pozycji
    zeznania (`status`, `src_mtime_ns`, `kind`, `sha1_data`, `frame_ids`, `dst`, `exists_path`…). Plik
    nieczytelny, bez `ts` albo bez listy pozycji nie świadczy."""
    pliki, poziom = [], [str(out_dir)]
    for _ in range(_TESTIMONY_DEPTH + 1):
        nastepny = []
        for katalog in poziom:
            try:
                wpisy = sorted(os.scandir(katalog), key=lambda e: e.name)
            except OSError:
                continue
            for e in wpisy:
                if e.is_dir():
                    nastepny.append(e.path)
                elif (e.name.startswith(projection.HARVEST_MANIFEST_PREFIX + "_")
                      and e.name.lower().endswith(".json")):
                    pliki.append(e.path)
        poziom = nastepny
    zeznania = []
    for p in pliki:
        try:
            with open(p, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            continue
        ts = _iso_timestamp(payload.get("ts")) if isinstance(payload, dict) else None
        if ts is None or not isinstance(payload.get("items"), list):
            continue
        archiwum = payload.get("archive_root")
        pozycje = {_path_key(i["src"]): i for i in payload["items"] if isinstance(i, dict) and i.get("src")}
        zeznania.append((ts, p, _path_key(archiwum) if archiwum else None, pozycje))
    zeznania.sort(key=lambda z: (z[0], z[1]), reverse=True)
    return [(ts, archiwum, pozycje) for ts, _p, archiwum, pozycje in zeznania]


def _src_mtime_ns(pozycja):
    """`src_mtime_ns` pozycji zeznania albo `None` (zeznanie sprzed tego pola, śmieć)."""
    v = pozycja.get("src_mtime_ns")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _pending_stack(con, klucz, mtime_ns, zeznania, stacks_root):
    """Stos pliku `klucz`, którego rodowodu DOKŁADNEGO baza jeszcze nie ma → `(sha1_data, frame_ids,
    kopia)` albo `None` (AR-104). Zbiór wejść bierze NAJNOWSZE zeznanie, które go niesie dla pliku
    niezmienionego od SWOJEGO planu, przy pozycji `placed`/`exists`: bieg nad stosem, który baza już
    zna, zeznaje `exists` bez zbioru - zbiór zna starsze zeznanie wciągnięcia. Pozycja `review` też
    bywa ze zbiorem (`_plan_stack` ustawia `frame_ids` przed odmową nagłówka i kalibracji), ale to
    zbiór stosu, którego żniwa NIE przyjęły - nie świadczy. Kopia = obecna kopia znana bazie pod
    `STACKS` archiwum, bez niej - plik z zeznania, który dalej leży pod `STACKS`; bez żadnej nie ma
    czego przyjmować."""
    for _ts, _a, pozycje in zeznania:
        p = pozycje.get(klucz)
        ids = p.get("frame_ids") if p is not None else None
        if (p is not None and p.get("status") in ("placed", "exists") and p.get("kind") == "master_light"
                and p.get("sha1_data") and ids and isinstance(ids, list)
                and all(isinstance(i, int) for i in ids) and _src_mtime_ns(p) == mtime_ns):
            break
    else:
        return None
    sha1, ids = p["sha1_data"], tuple(sorted(set(ids)))
    if not stacks.harvest_lineage_pending(con, master_sha1_data=sha1, input_frame_ids=ids):
        return None
    znane = [x for x in queries.present_paths_by_sha1_data(con, sha1) if _under(x, stacks_root)]
    zeznana = p.get("dst") or p.get("exists_path")
    if znane:
        return sha1, ids, znane[0]
    if zeznana and _under(zeznana, stacks_root) and os.path.isfile(zeznana):
        return sha1, ids, zeznana
    return None


def _release_state(out_dir, release_ts, *, archive_root=None, con=None):
    """`(pending, done, review, awaiting_wbpp, lineage)` kandydatów żniw w `out_dir`. Stan kandydata mówi
    NAJNOWSZE zeznanie, które go wymienia (bieg nad `out\\master` nie zna plików spoza tego katalogu):
    `placed`/`exists` przy pliku niezmienionym od planu tego biegu = wciągnięty, `review` tak samo = do
    przeglądu, cała reszta - bieg przerwany (`would-place`, `cancelled`), konflikt, błąd, plik bez
    zeznania albo zmieniony od niego (nowy przebieg WBPP) - do wciągnięcia.

    „NIEZMIENIONY” = dzisiejszy `st_mtime_ns` równy temu, który plan zapisał przy pozycji
    (`src_mtime_ns`); zeznanie sprzed tego pola - plik nie młodszy niż `ts` zeznania. Równość czasu
    planu, nie porównanie z chwilą biegu: `apply` przenosi `exists` z planu bez audytu, więc plik
    nadpisany przez WBPP między planem a `apply` ma czas starszy od zeznania, a bajty inne niż archiwum.

    ARCHIWUM (AR-105): z `archive_root` świadczą WYŁĄCZNIE zeznania biegów do tego archiwum (`archive_root`
    zeznania = korzeń przed `CALIBRATION`/`STACKS`, porównanie `_path_key`; zeznanie bez tego pola nie
    świadczy) - plik wciągnięty do innego archiwum w tym archiwum nie leży. Bez `archive_root` świadczą
    wszystkie. `lineage` (`_pending_stack`) liczy się tylko z bazą (`con`) i archiwum.

    `awaiting_wbpp` = są kandydaci, a `release_ts` (sekundy, ostatnie wydanie) jest nowszy od najnowszego
    z nich. Ekran liczy to z dysku i z treści zeznań, nie z pamięci okna ani z samego zegara."""
    zeznania = _harvest_testimonies(out_dir)
    stacks_root = None
    if archive_root:
        lib = library_root(archive_root)
        zeznania = [z for z in zeznania if z[1] == _path_key(lib)]
        stacks_root = os.path.join(lib, STACKS_SEGMENT)
    pending = done = review = 0
    najnowszy = None
    lineage = {}
    for src in discover(out_dir):
        try:
            st = os.stat(src)
        except OSError:                                   # plik zniknął między listą a odczytem
            continue
        najnowszy = st.st_mtime if najnowszy is None else max(najnowszy, st.st_mtime)
        klucz = _path_key(src)
        werdykt = next(((ts, z[klucz]) for ts, _a, z in zeznania if klucz in z), None)
        if werdykt is None:
            pending += 1
            continue
        ts, pozycja = werdykt
        status, zapisany_ns = pozycja.get("status"), _src_mtime_ns(pozycja)
        niezmieniony = st.st_mtime_ns == zapisany_ns if zapisany_ns is not None else st.st_mtime <= ts
        if niezmieniony and status in ("placed", "exists"):
            done += 1
            stos = (_pending_stack(con, klucz, st.st_mtime_ns, zeznania, stacks_root)
                    if con is not None and stacks_root is not None else None)
            if stos is not None:
                lineage.setdefault(stos[0], stos)
        elif niezmieniony and status == "review":
            review += 1
        else:
            pending += 1
    awaiting = najnowszy is not None and release_ts is not None and release_ts > najnowszy
    return pending, done, review, awaiting, tuple(lineage.values())


def releases(roots, *, archive_root=None, con=None):
    """Lista wydań obiektu z kart celu (odczyt dysku; z `con` - też bazy) → `[ReleaseRow]` od
    najnowszego wydania (`ts` manifestu malejąco; nieczytelny `ts` na końcu). `roots` = korzenie kart
    (folder roboczy WBPP i karty celu wydania); pod każdym podkatalogi `<root>\\OBJECTS\\*` z manifestem
    układu `wbpp-obiekt`. Karta bez `OBJECTS` nie daje nic; ten sam folder obiektu pod dwiema pisowniami
    karty liczy się raz. Stan wyjścia - `_release_state` (`archive_root` = archiwum okna żniw, `con` =
    baza do rodowodu stosów). Czas zeznań i wydań: ISO ze strefą (UTC od okna), naiwny znacznik liczony
    lokalnie (`_iso_timestamp`) - porównanie z `mtime` pliku jest wtedy poprawne tylko w strefie czasu,
    w której go zapisano."""
    rows, widziane = [], set()
    for root in roots:
        przestrzen = os.path.join(str(root), projection.OBJECT_NAMESPACE)
        try:
            nazwy = sorted(os.listdir(przestrzen))
        except OSError:
            continue
        for nazwa in nazwy:
            object_root = os.path.join(przestrzen, nazwa)
            klucz = os.path.normcase(os.path.normpath(os.path.abspath(object_root)))
            if klucz in widziane or not os.path.isdir(object_root):
                continue
            manifest = _object_witness(projection.read_manifest(object_root))
            if manifest is None:
                continue
            widziane.add(klucz)
            out_dir = os.path.join(object_root, projection.OUTPUT_DIR)
            pending, done, review, awaiting, lineage = _release_state(
                out_dir, _iso_timestamp(manifest.get("ts")), archive_root=archive_root, con=con)
            rows.append(ReleaseRow(root=str(root), object_root=object_root,
                                   object_canon=manifest.get("object_canon"), ts=manifest.get("ts"),
                                   out_dir=out_dir, pending=pending, done=done, review=review,
                                   awaiting_wbpp=awaiting, lineage=lineage))
    rows.sort(key=lambda r: (_iso_timestamp(r.ts) is not None, _iso_timestamp(r.ts) or 0.0,
                             str(r.ts), r.object_root), reverse=True)
    return rows
