"""Żniwa masterów - które pliki z wyjścia WBPP wciągnąć do biblioteki kalibracji, dokąd i jak nazwane.

Wydanie obiektu (`projection.plan_object`) oddaje WBPP lighty, gotowe mastery i surowe flaty; WBPP
buduje z surowych flatów nowe masterflaty, które dziś zostają w warsztacie. Ten moduł odpowiada,
które z nich archiwum jeszcze nie ma i gdzie mają leżeć. Plików NIE mutuje i do bazy NIE pisze
(bramki `test_writeback_safety` i `test_repo_safety`): `plan` czyta bazę i dysk, `apply` woła klingę
`projection.copy_master` (kopia `.part`, audyt bajtów, publikacja bez nadpisania) oraz
`projection.write_harvest_manifest`. O nowym masterze baza dowie się zwykłym łańcuchem Dostawy
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
wejść). `masterLight*` należą do drogi „Stosy". Wyłącznie XISF: format wyjścia WBPP i 112/112
masterów archiwum; FITS historii nie niesie.

„JUŻ W ARCHIWUM" PRZED PROWENIENCJĄ. Plik, którego `sha1_data` baza zna, jest w archiwum niezależnie
od rodzaju i od tego, czy jego wejścia da się dziś rozstrzygnąć - zmierzone: 75/75 archiwalnych
masterflatów ma w historii wejścia ze starych warsztatów, z których żadne nie trafia w nazwę
surowego flatu bazy, więc kolejność odwrotna nazwałaby kopię bajtową „nieznanymi wejściami".
"""

from __future__ import annotations

import dataclasses
import os
import re
from collections import Counter
from collections.abc import Callable

from . import hashing, naming, projection, scan
from .gui import queries
from .resolve._coerce import _to_int
from .resolve.filters import normalize_filter
from .resolve.stack import read_testimony

# Konwencja archiwum (Custos): `CALIBRATION\masters\flats\<zestaw>\<filtr>`. Folder, a nie tabela,
# bo silnik go nie potrzebuje - skan klasyfikuje po `IMAGETYP`, kalibracja czyta nagłówek, a `FLATGRP`
# czyta nazwę. Folder jest dla człowieka i Eksploratora; żniwa trzymają się go, żeby wciągnięty master
# leżał tam, gdzie człowiek szuka reszty.
MASTERS_SUBDIR = (projection.CALIBRATION_SEGMENT, "masters", "flats")

_FLAT_PREFIX = "masterflat"
_DARK_PREFIXES = ("masterdark", "masterbias")
_PREFIXES = (_FLAT_PREFIX, *_DARK_PREFIXES)            # `masterlight` świadomie poza (droga „Stosy")
_SEQ_DIGITS = 10                                        # cyfra kolejności grupy flatu: 0..9
_DETAIL_NAMES = 3                                       # ile nazw wejść cytuje powód odmowy

# Powody `review` - JEDYNY właściciel listy. Dialog ma literalną mapę token → klucz i18n i test
# parytetu z tą krotką (bramka i18n nie widzi kluczy składanych dynamicznie).
REASONS = ("no_raw_darks", "unreadable", "no_history", "no_inputs", "inputs_unknown",
           "inputs_ambiguous", "mixed_profile", "no_profile", "no_night", "header_mismatch",
           "outside_release", "no_config", "name_taken")
# Statusy pozycji - JEDYNY właściciel listy (dialog: literalna mapa na klucze i18n + test parytetu).
# Trzy pierwsze daje plan, reszta to wynik kopii po `apply`.
STATUSES = ("would-place", "exists", "review", "placed", "verify_bad", "conflict", "error", "cancelled")


class HarvestCancelled(Exception):
    """Sonda żniw przerwana na żądanie wołającego (`should_cancel` w `discover`/`plan`). Planu
    częściowego nie ma: pozycje policzone przed przerwaniem nie są obrazem wyjścia WBPP, więc wołający
    porzuca wynik, zamiast pokazać połowę katalogu jako całość."""


def discover(wbpp_dir, *, should_cancel=None):
    """Kandydaci żniw w drzewie wyjścia WBPP: pliki XISF (`scan.XISF_SUFFIXES`), rekurencyjnie, których
    nazwa (bez wielkości liter) zaczyna się od `masterflat`, `masterdark` albo `masterbias`.
    `masterLight*` pominięte (stosy mają własną drogę), FITS też (historii w nim nie ma). Brak
    katalogu = pusta lista. Posortowane po pełnej ścieżce - kolejność planu i nazw. `should_cancel()`
    sprawdzane przy każdym katalogu (drzewo warsztatu po SMB bywa duże) → `HarvestCancelled`."""
    out = []
    for dirpath, _dirnames, filenames in os.walk(wbpp_dir):
        if should_cancel is not None and should_cancel():
            raise HarvestCancelled(wbpp_dir)
        for name in filenames:
            low = name.lower()
            if os.path.splitext(low)[1] in scan.XISF_SUFFIXES and low.startswith(_PREFIXES):
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
    danych do pytania bazy i sha1 całego pliku - bajty, których apply wymaga od kopii."""
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
        date_obs=h.get("DATE-OBS"))


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
    siedziby - folder archiwum (`76EDPH_2600MM`) niesie `dst`."""
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


@dataclasses.dataclass(frozen=True)
class HarvestPlan:
    """Wynik `plan`: pozycje w kolejności nazw plików. `manifest_root` = korzeń wydania z manifestu-
    świadka (`None` bez manifestu); `wbpp_dir` = katalog wyjścia, w którym `apply` zostawi zeznanie
    biegu `_ZNIWA_<znacznik>.json`."""
    items: list
    manifest_root: str | None
    wbpp_dir: str | None = None


def _split_at_calibration(path):
    """`(korzeń przed segmentem CALIBRATION, ogon od niego włącznie)` dla PIERWSZEGO wystąpienia od
    korzenia (bez wielkości liter, ścieżka znormalizowana, separatory `\\` i `/`) albo `None`, gdy
    segmentu nie ma. Jedno cięcie dla obu pytań: siedziby (ogon) i korzenia archiwum (prefiks)."""
    cur, wstecz = os.path.normpath(str(path)), []
    while True:
        head, tail = os.path.split(cur)
        if not tail:
            break
        wstecz.append((head, tail))
        cur = head
    segmenty = list(reversed(wstecz))                    # od korzenia
    for i, (head, tail) in enumerate(segmenty):
        if tail.lower() == projection.CALIBRATION_SEGMENT.lower():
            return head, tuple(t for _h, t in segmenty[i:])
    return None


def _calibration_tail(katalog):
    """Ogon ścieżki od segmentu `CALIBRATION` włącznie albo `None` (`_split_at_calibration`)."""
    ciecie = _split_at_calibration(katalog)
    return None if ciecie is None else ciecie[1]


def _library_root(archive_root):
    """Korzeń archiwum, pod którym leży biblioteka `CALIBRATION`: część `archive_root` PRZED pierwszym
    segmentem `CALIBRATION`, gdy go ma (wskazanie `R:\\ASTRO_\\CALIBRATION` dawałoby inaczej
    `…\\CALIBRATION\\CALIBRATION\\…`); bez segmentu - `archive_root` bez zmian. Pusty korzeń po cięciu
    (ścieżka względna zaczynająca się od `CALIBRATION`) → `ValueError` (EXPECT)."""
    ciecie = _split_at_calibration(archive_root)
    if ciecie is None:
        return archive_root
    if not ciecie[0]:
        raise ValueError(f"archiwum bez korzenia przed CALIBRATION: {archive_root!r}")
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


def plan(con, wbpp_dir, *, archive_root, manifest=None, read=read_master, should_cancel=None):
    """Plan żniw (odczyt bazy i dysku, ZERO zapisu) → `HarvestPlan`. Dla każdego pliku z `discover`,
    w kolejności nazw, pierwsza odmowa kończy rozstrzyganie pozycji:

    1. odczyt (`read`); wyjątek → `review` `unreadable` z treścią wyjątku;
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
    11. siedziba: korzeń archiwum (`_library_root`) + ogon katalogu, w którym archiwum trzyma mastery
        profilu (`_seat`); inaczej katalog zestawu rodzeństwa + segment filtru (`_rig_tails`); inaczej
        `<korzeń>/CALIBRATION/masters/flats/<zestaw>/<filtr>`; bez configu → `no_config`;
    12. te same bajty w siedzibie → `exists` (`_on_disk`);
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
    root = _library_root(archive_root)
    witness = (manifest if isinstance(manifest, dict)
               and manifest.get("layout") == projection.OBJECT_LAYOUT else None)
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
            t = read(src)
        except Exception as exc:                          # czytnik nie umiera za cały plan
            items.append(HarvestItem(src, "unknown", "review", "unreadable",
                                     detail=f"{type(exc).__name__}: {exc}"))
            continue
        item = HarvestItem(src, t.kind, "review", sha1_data=t.sha1_data, file_sha1=t.file_sha1)
        items.append(item)
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
            item.status, item.exists_path = "exists", na_dysku
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
    return HarvestPlan(items=items, manifest_root=manifest_root, wbpp_dir=str(wbpp_dir))


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
        "cancelled": cancelled, "counts": dict(sorted(counts.items())),
        "items": [{
            "src": it.src, "dst": it.dst, "kind": it.kind, "status": it.status, "reason": it.reason,
            "reason_n": it.reason_n, "detail": it.detail, "sha1_data": it.sha1_data,
            "file_sha1": it.file_sha1, "frame_ids": list(it.frame_ids), "nights": list(it.nights),
            "profile_id": it.profile_id, "release": list(it.release) if it.release else None,
            "exists_path": it.exists_path, "ts": now} for it in items],
    }


def apply(harvest_plan, *, now,
          progress: Callable[[int, int, str, str], None] | None = None,
          should_cancel: Callable[[], bool] | None = None,
          copy=projection.copy_master) -> HarvestResult:
    """Wciągnij pozycje `would-place` po kolei: `should_cancel()` PRZED plikiem (ta i dalsze →
    `cancelled`), `copy(src, dst, expected_sha1=file_sha1)` → status i `detail` z klingi,
    `progress(done, total, dst, status)` po każdym skopiowanym pliku. Pozycje planu z innym statusem
    przechodzą bez zmian. Plan bez `wbpp_dir` → `ValueError` (przed jakąkolwiek kopią).

    NIE RZUCA PO SKUTKACH UBOCZNYCH: kopie poprzednich pozycji już leżą w archiwum, więc wyjątek
    zgubiłby wynik, który gospodarz ma przekazać do skanu. Wyjątek `copy` spoza katalogu statusów
    (`ValueError` guardu) → pozycja `error` z treścią i pętla idzie dalej; błąd zapisu zeznania →
    `manifest_error`. Zeznanie biegu (`projection.write_harvest_manifest`, nowy plik na bieg) pisze się
    zawsze, także bez `placed` i także przy `BaseException` (przerwanie z klawiatury) - wtedy z wyniku
    częściowego (pozycje nieruszone zostają `would-place`), a wyjątek leci dalej."""
    if not harvest_plan.wbpp_dir:
        raise ValueError("plan żniw bez wbpp_dir - nie ma gdzie zapisać zeznania żniw")
    total = sum(1 for it in harvest_plan.items if it.status == "would-place")
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
                status, why = copy(it.src, it.dst, expected_sha1=it.file_sha1)
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
