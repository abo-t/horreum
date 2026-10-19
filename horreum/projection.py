"""TRZECIA KLINGA — jedyny obramkowany dom MUTACJI PLIKÓW przez LINK/KOPIĘ/KATALOG (KROK 6 scalenia,
brief PLAN_projekcje). Materializuje bieżącą PERSPEKTYWĘ (zbiór frame'ów filtra) w drzewo folderów
HARDLINKÓW (albo kopii) pod wykluczonym korzeniem (`_WBPP`/`_Review`) — „Projekcja → drzewo po
obiektach", „→ WBPP feed". Pętla scalenia domyka się: projekcja trafia pod `EXCLUDED_DIR_NAMES`
(`scan.py`) → nie wraca jako wejście skanu.

Dawca-WZORZEC: Custos `tools/wbpp_feed.py` (sonda hardlinka, DRY-default, plan→apply). Rdzeń Qt-wolny
(jak `writeback.py`): czyste `plan(...)`/`apply(...)` z callbackami `progress`/`should_cancel` (GUI
podaje je z wątku roboczego). Meta-tripwir AST (`tests/test_writeback_safety.py`) pilnuje, że
`os.link`/`os.makedirs`/`shutil.copy2` żyją WYŁĄCZNIE tu i w `writeback.py` (DOORS).

Twarde ramy (brief §0):
- **ZERO zapisu domenowego** — projekcja EFEMERYCZNA (kasowalna w Eksploratorze, poza skanem): NIE
  emituje eventu ani nie pisze do bazy (JEDNA-KLINGA nietknięta — brak `repo`). Obok korzenia zostaje
  manifest `_PROJEKCJA.json` (PLIK, nie DB).
- **ZERO nadpisania** - cel istnieje z INNYM i-węzłem → `conflict` (NIE clobber); ten sam i-węzeł →
  `exists` (idempotentnie pomiń). W trybie kopii `exists` to także kopia, którą zrobiło wydanie
  (rozmiar + czas + nagłówek, `_link_to`). Read-only wobec drzewa źródłowego.
- **CEL-POD-WYKLUCZENIEM** — `root` MUSI zawierać segment z `EXCLUDED_DIR_NAMES`. Hardlink = duplikat
  i-węzła; `os.walk followlinks=False` NIE odróżni go od oryginału → dla hardlinków chroni WYŁĄCZNIE
  prune `dirnames` po nazwie (`_assert_excluded_segment` PRZED masą).
- **DRY domyślnie** — `do_apply=False`: tylko sonduje stan celu (would-link/exists/conflict), ZERO
  tworzenia. Pierwszy realny hardlink SONDOWANY pełnym `_verify_content` (i-węzeł+rozmiar+treść — SMB
  potrafi dać kopię zamiast linka) → rozjazd = `ProjectionAbort` PRZED masą (wzorzec `ImportAbort`).

Podział koncernów (COHESION): `plan(con, ...)` = czysty ODCZYT DB (źródło linku `present_locations`
R#1 + segmenty `base_rows`); `apply(plan, root, ...)` = czysta MUTACJA filesystemu (zna korzeń). Import
`gui.queries` jest Qt-wolny (`gui/__init__.py` pusty) — pilnuje tego `test_gui_isolation`.

WYDANIE OBIEKTU (`plan_object`) to drugi planista nad tym samym `apply`: nie perspektywa gridu, tylko
komplet pod WBPP dla jednego obiektu - lighty, mastery ze STANU `calibration` i surowe flaty z odczytu
`lineage.raw_flats_for`, rozdzielone ZESTAWEM (teleskop + kamera), bo WBPP grupuje po filtrze,
ekspozycji i binningu, a nie po optyce - wspólny folder zmieszałby kamery. Korzeń wydania to
`<cel>/<obiekt>` (`object_root`), więc każdy obiekt ma własny manifest. Układ `wbpp-obiekt` nie
jest kolumnowy, więc nie wchodzi do `LAYOUTS`; jego kształt dla manifestu niesie `OBJECT_SEGMENTS`,
a oba źródła kształtu czyta jedna funkcja `layout_segments`.

NAPRAWA MANIFESTU (`repair_manifest`, AR-213) zapisuje `_PROJEKCJA.json` nad drzewem wydania obiektu,
które JUŻ leży w celu (manifest niezapisany po udanych linkach, skasowany, nieopisujący kompletu) - bez
wejścia do `apply`. Treść to ta sama `object_manifest`, a listy zestawów scala się BEZ UTRATY ze starym
manifestem: id wcześniejszych wydań zostają, gdy świadek drzewa (`_SwiadekDrzewa` - plik roli będący tym
samym plikiem co obecna kopia klatki) je potwierdza; to samo scalenie robi wydanie (`apply(...,
extra_sources=)`). Obaj pisarze manifestu (krok manifestu wydania i naprawa) trzymają plik roboczy
`.part` wyłącznie (`x`) od odczytu starego manifestu do publikacji - cudzy `.part` to odmowa
`proj_manifest_busy`.
"""

from __future__ import annotations

import copy as _copy
import dataclasses
import json
import os
import re
import shutil
import stat
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone

from . import hashing, lineage, naming
from .gui import queries
from .item_reasons import (   # błąd systemu klasą - jeden właściciel (AR-184); odmowy z kodem (AR-200)
    OdmowaZPowodem, PowodPozycji, blad_systemu, powod_systemu)
from .resolve.paths import STACKS_DIR
from .scan import EXCLUDED_DIR_NAMES

_UNSET = "_UNSET"                      # segment layoutu pusty/None — nie gubimy klatki po cichu (§1)
MANIFEST_NAME = "_PROJEKCJA.json"
HARVEST_MANIFEST_PREFIX = "_ZNIWA"     # zeznanie biegu żniw obok wyjścia WBPP (`write_harvest_manifest`)
CALIBRATION_SEGMENT = "CALIBRATION"    # biblioteka kalibracji archiwum - cel kopii mastera
PART_SUFFIX = ".part"                  # plik w drodze; nie nagłówkonośny, więc skan go nie weźmie
# Folder roboczy WBPP: segment wykluczony ze skanu (`scan.EXCLUDED_DIR_NAMES`), więc wydania pod nim
# nie wracają jako wejście skanu. `work_wbpp_root` składa go z katalogu, który wskazał człowiek.
WBPP_DIR = "_WBPP"
# Wyjście WBPP w korzeniu wydania obiektu (`<cel>/OBJECTS/<obiekt>/out`): zakłada je `apply` wydania,
# żeby okno żniw miało jedno miejsce, w którym szuka wyników tego wydania.
OUTPUT_DIR = "out"

# Presety layoutu = KOD (uniwersalia, jak słowniki solar 5a; D-P1 rekomendacja (a)). Kolumny bazowe
# z `base_rows`. JSON dojdzie, gdy user zażąda własnych layoutów (MINIMAL). Spec segmentu = nazwa
# kolumny ALBO krotka KOLUMN-KANDYDATÓW (pierwsza niepusta wygrywa — `_segment`).
#
# `telescope_label` → `telescop_canon` (P2, coalesce): na żywej bazie `label` jest NULL dla WSZYSTKICH
# teleskopów (sonda DRY 2026-07-16: `_UNSET` w 100% ze 189 folderów), więc segment teleskopu w feedzie
# nie niósł ŻADNEJ informacji. `telescop_canon` jest wypełniony i to nim GUI opisuje nienazwany
# teleskop (ta sama reguła co `gui.queries.telescope_label` — label→canon) → feed mówi to samo,
# co reszta aplikacji.
LAYOUTS = {
    "po-obiektach": ("object_canon", "filter_canon"),
    "wbpp-feed": ("object_canon", ("telescope_label", "telescop_canon"), "filter_canon"),
}

# Wydanie obiektu: korzeń `<cel>/OBJECTS/<obiekt>` (`object_root`), pod nim `<zestaw>/<rola>/<filtr
# albo relacja>/plik`. Obiekt siedzi w KORZENIU, nie w segmencie pozycji: manifest leży wtedy w folderze
# obiektu i wydanie obiektu B do tej samej karty celu nie nadpisuje proweniencji obiektu A. Osobna
# przestrzeń `OBJECTS`, bo układy kolumnowe na tej samej karcie kładą obiekt jako PIERWSZY segment
# (`po-obiektach`: `<cel>/<obiekt>/<filtr>`) - wydanie obiektu w `<cel>/<obiekt>` stanęłoby obok
# drzewa perspektywy z tymi samymi i-węzłami, a WBPP („Add Directory" rekurencyjnie) policzyłby
# każdy light dwa razy; ścieżki różne, więc ani `conflict`, ani `manifest_drift` by tego nie złapały. Ostatni
# segment zależy od roli (LIGHT i FLAT_RAW - filtr klatki, MASTER - relacja z `calibration`), stąd
# krotka w zapisie kształtu, czytana przez `_shape` jako „jedno z dwojga". Nazwy segmentów to opis
# drzewa dla manifestu i `manifest_drift`, nie kolumny `base_rows`.
OBJECT_LAYOUT = "wbpp-obiekt"
OBJECT_SEGMENTS = ("zestaw", "rola", ("filtr", "relacja"))
OBJECT_NAMESPACE = "OBJECTS"           # token dysku jak LIGHT/MASTER/FLAT_RAW - neutralny językowo
_OSC = "OSC"                           # konwencja archiwum: `CALIBRATION\masters\flats\<zestaw>\OSC`
_SKIP_NO_COPY = "brak obecnej kopii (wszystkie present=0)"


def _segments_from_root(path):
    """`[(rodzic, segment)]` ścieżki znormalizowanej (`normpath`), od korzenia - jedno cięcie dla pytań
    „gdzie stoi pierwszy segment o tej nazwie” (oba separatory, bez dotykania dysku)."""
    cur, wstecz = os.path.normpath(str(path)), []
    while True:
        head, tail = os.path.split(cur)
        if not tail:
            break
        wstecz.append((head, tail))
        cur = head
    return list(reversed(wstecz))


def work_wbpp_root(root):
    """Korzeń folderu roboczego WBPP dla katalogu wskazanego przez człowieka (czysta funkcja, zero
    dysku). Ścieżka znormalizowana; gdy któryś jej segment to `_WBPP` (bez wielkości liter) - ścieżka
    do PIERWSZEGO takiego segmentu włącznie (wskazanie `…\\_WBPP\\OBJECTS` nie zakłada drugiego
    `_WBPP` w środku); inaczej `<root>\\_WBPP`, także pod `…\\_Review` (inny segment wykluczony to
    inne drzewo robocze, nie folder WBPP)."""
    for head, tail in _segments_from_root(root):
        if tail.lower() == WBPP_DIR.lower():
            return os.path.join(head, tail)
    return os.path.join(os.path.normpath(str(root)), WBPP_DIR)


def layout_segments(layout):
    """Kształt układu (spec segmentów) - JEDYNE wejście `_shape`, `manifest_drift` i `_write_manifest`.
    Układy kolumnowe z `LAYOUTS`, wydanie obiektu z `OBJECT_SEGMENTS`; nieznana nazwa → `ValueError`
    (EXPECT), nigdy cichy pusty kształt, który manifest zapisałby jako prawdę."""
    if layout in LAYOUTS:
        return LAYOUTS[layout]
    if layout == OBJECT_LAYOUT:
        return OBJECT_SEGMENTS
    raise ValueError(f"nieznany layout: {layout!r} (dostępne: {sorted([*LAYOUTS, OBJECT_LAYOUT])})")


# ============================================================ PLAN (czysty ODCZYT DB)


@dataclasses.dataclass(frozen=True)
class PlanItem:
    """Jedna klatka → jeden zamierzony link. `src` = pierwsza OBECNA location (R#1). `segments` =
    już-zsanityzowane katalogi layoutu (z `_UNSET`). `dst` liczy `apply` (zna korzeń)."""
    frame_id: int
    src: str
    segments: tuple
    basename: str


@dataclasses.dataclass(frozen=True)
class Projection:
    """Wynik `plan()`: pozycje do zlinkowania + pominięte (brak obecnej kopii — kwarantanna) +
    `multi_present` (ile frame'ów miało >1 obecną kopię; zlinkowano pierwszą, D-P5).
    `info` niesie tylko wydanie obiektu (`plan_object`): proweniencję i liczby per zestaw dla
    podglądu i manifestu; perspektywa gridu go nie ma (`None`)."""
    layout: str
    items: list                       # list[PlanItem]
    skipped: list                     # list[(frame_id, reason)]
    multi_present: int = 0
    info: dict | None = None


def _segment(row, spec):
    """Wartość kolumny bazowej → nazwa katalogu bezpieczna na dysku (SPOT: `naming._sanitize` — ta
    sama konwencja slug co nazwy plików). Pusty/None/brak wiersza oraz `.`/`..` (anty-traversal) →
    `_UNSET`; nie gubimy klatki po cichu ani nie wychodzimy poza korzeń (brief §1/§0). `spec` =
    nazwa kolumny ALBO krotka kandydatów: pierwsza dająca NIEPUSTY segment wygrywa (coalesce
    label→canon), dopiero wyczerpanie wszystkich daje `_UNSET`."""
    cols = spec if isinstance(spec, tuple) else (spec,)
    for col in cols:
        value = row[col] if row is not None else None
        seg = naming._sanitize(value)
        if seg not in ("", ".", ".."):
            return seg
    return _UNSET


def plan(con, frame_ids, layout="po-obiektach"):
    """Zbuduj PLAN projekcji (czysty odczyt DB, ZERO filesystemu). Dla każdego frame'a: ŹRÓDŁO linku =
    pierwsza OBECNA location (`present_locations`, R#1 - NIE `base_rows`: od D-V-9 preferuje ono
    kopię obecną, ale gałęzią powrotu potrafi oddać `present=0`, i wciąż nie zna `volume`)
    + SEGMENTY layoutu z `base_rows` (tylko do kategorii). Frame bez obecnej kopii
    → `skipped` (kwarantanna, raport). Wiele obecnych → pierwsza, `multi_present++`. `layout` ∈ LAYOUTS."""
    if layout not in LAYOUTS:
        raise ValueError(f"nieznany layout: {layout!r} (dostępne: {sorted(LAYOUTS)})")
    cols = LAYOUTS[layout]
    ids = sorted(int(i) for i in frame_ids)

    sources = _sources(con, ids)
    seg_by_frame = {int(r["frame_id"]): r for r in queries.base_rows(con, ids)}

    items: list[PlanItem] = []
    skipped: list[tuple] = []
    multi = 0
    for fid in ids:
        src = sources.get(fid)
        if src is None:
            skipped.append((fid, _SKIP_NO_COPY))
            continue
        path, n_present = src
        multi += n_present > 1
        seg_row = seg_by_frame.get(fid)
        segments = tuple(_segment(seg_row, c) for c in cols)
        items.append(PlanItem(frame_id=fid, src=path, segments=segments,
                              basename=os.path.basename(path)))
    return Projection(layout=layout, items=items, skipped=skipped, multi_present=multi)


def _sources(con, ids):
    """Reguła wyboru ŹRÓDŁA linku w jednym miejscu dla obu planistów: `frame_id -> (ścieżka pierwszej
    OBECNEJ kopii, liczba obecnych kopii)` z `present_locations` (R#1, D-P5: pierwsza w porządku
    `location_id`). Klatka bez obecnej kopii w słowniku się nie pojawia - wołający kładzie ją do
    `skipped`. `projection_dialog.chosen_present` lustruje tę regułę dla decyzji wolumenowej.
    Kopie klatki - `_obecne_kopie` (te same, które świadczą w drzewie wydania)."""
    return {fid: (sciezki[0], len(sciezki)) for fid, sciezki in _obecne_kopie(con, ids).items()}


def _filter_segment(filter_canon, is_mono):
    """Segment filtra klatki w wydaniu obiektu. Pusty filtr na kamerze KOLOROWEJ to fakt, nie luka
    (`calibration.REQUIRED` mówi to samo o przepisie flatu) - dostaje nazwę z konwencji archiwum `OSC`.
    Pusty filtr na mono albo na kamerze nierozstrzygniętej (`is_mono` NULL) to prawdziwa luka →
    `_UNSET`, żeby WBPP nie dostał lightów mono bez filtra udających kolor."""
    if not naming._sanitize(filter_canon) and is_mono == 0:
        return _OSC
    return _segment({"filtr": filter_canon}, "filtr")


def plan_object(con, object_id, *, config_id=None, window_days=lineage.RAW_FLAT_WINDOW_DAYS):
    """Plan WYDANIA OBIEKTU do WBPP (czysty odczyt DB, ZERO filesystemu) → `Projection` z układem
    `wbpp-obiekt` i wypełnionym `info`.

    Populacja: aktywne lighty obiektu (`kind='light'`, bez `retired_at`/`superseded_by`), opcjonalnie
    jeden zestaw (`config_id`). Do każdego zestawu dochodzą mastery ze STANU `calibration` (DISTINCT
    w zestawie; master służący dwóm zestawom stoi w obu, bo każdy folder zestawu ma być kompletnym
    wejściem WBPP) oraz surowe flaty z `lineage.raw_flats_for` dla lightów bez master flatu. Źródło
    i kwarantanna jak w `plan()` (`_sources`): pozycja bez obecnej kopii → `skipped`.

    Drzewo WZGLĘDEM korzenia obiektu (`object_root`): `<zestaw>/LIGHT/<filtr>`,
    `<zestaw>/MASTER/<relacja>`, `<zestaw>/FLAT_RAW/<filtr>`. Zestaw = `<teleskop>_<kamera>`
    (teleskop regułą `queries.telescope_label`, kamera configu), klatka bez configu → `_UNSET`;
    nazwę folderu zestawu i folderu obiektu niesie `zestawy_configow` i `_object_segment`. W `info`
    zestaw niesie `config_id` (reprezentant tożsamości) i `config_ids` (configi z lightami w tym
    wydaniu). Nieznany obiekt → `ValueError` (EXPECT)."""
    obj = con.execute("SELECT id, canon FROM object WHERE id = ?", (object_id,)).fetchone()
    if obj is None:
        raise ValueError(f"nieznany obiekt: {object_id!r}")
    rows = con.execute(
        "SELECT f.id AS frame_id, f.config_id AS config_id, f.filter_canon AS filter_canon, "
        "h.exptime AS exptime, cam.is_mono AS is_mono "
        "FROM frame f "
        "LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN camera cam ON cam.id = f.camera_id "
        "WHERE f.kind = 'light' AND f.object_id = ? "
        "AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "ORDER BY f.id", (obj["id"],)).fetchall()
    zestaw_configu = zestawy_configow(con)

    # Filtr `config_id` wybiera CAŁY zestaw tego configu (wszystkie configi tej samej tożsamości),
    # nie jego część - inaczej wydanie jednego configu scalonego teleskopu zostawiałoby folder
    # zestawu niekompletny, a manifest twierdziłby, że to cały zestaw.
    cel = zestaw_configu.get(config_id) if config_id is not None else None
    lights = [r for r in rows
              if config_id is None or (cel is not None and zestaw_configu.get(r["config_id"]) == cel)]
    light_ids = [r["frame_id"] for r in lights]
    stan = {}                                          # light -> {relacja: master}
    for r in con.execute(
            "SELECT light_frame_id, relation, master_frame_id FROM calibration "
            "WHERE light_frame_id IN (SELECT value FROM json_each(?))", (json.dumps(light_ids),)):
        stan.setdefault(r["light_frame_id"], {})[r["relation"]] = r["master_frame_id"]
    surowe = lineage.raw_flats_for(con, light_ids, window_days=window_days)

    zestawy = {}
    for r in lights:
        fid = r["frame_id"]
        seg, rep = zestaw_configu.get(r["config_id"], (_UNSET, None))
        z = zestawy.setdefault(seg, {
            "config_id": rep, "config_ids": set(), "lights": [], "hours": 0.0, "masters": {},
            "flat_raw": set(), "flat_raw_nights": set(), "bez_flatu": [], "bez_darka": [], "pending": [],
            "flat_gaps": {}, "_filtr": {}})
        if r["config_id"] is not None:
            z["config_ids"].add(r["config_id"])
        z["lights"].append(fid)
        z["_filtr"][fid] = _filter_segment(r["filter_canon"], r["is_mono"])
        z["hours"] += float(r["exptime"] or 0.0) / 3600.0
        rel = stan.get(fid, {})
        for relacja, mid in rel.items():
            z["masters"].setdefault(relacja, set()).add(mid)
        if "flat" not in rel:
            pick = surowe[fid]                         # inwariant: light bez flatu w stanie ma wybór
            if pick.frame_ids:
                z["flat_raw"].update(pick.frame_ids)
                z["flat_raw_nights"].add(pick.night)
            elif pick.gap == "pending":
                # Master JEST, tylko rodowód go nie przeliczył - to jedno kliknięcie w Dostawie, nie
                # brak flatu do kupienia; „bez flatu" mówiłoby nieprawdę o archiwum.
                z["pending"].append(fid)
            else:
                z["bez_flatu"].append(fid)
                z["flat_gaps"][pick.gap] = z["flat_gaps"].get(pick.gap, 0) + 1
        if "dark" not in rel:
            z["bez_darka"].append(fid)                 # darki WYŁĄCZNIE mastery - surowych w archiwum nie ma

    flat_ids = sorted({f for z in zestawy.values() for f in z["flat_raw"]})
    flat_facts = {r["frame_id"]: r for r in con.execute(
        "SELECT f.id AS frame_id, f.filter_canon AS filter_canon, cam.is_mono AS is_mono "
        "FROM frame f LEFT JOIN camera cam ON cam.id = f.camera_id "
        "WHERE f.id IN (SELECT value FROM json_each(?))", (json.dumps(flat_ids),))}
    master_ids = {m for z in zestawy.values() for ms in z["masters"].values() for m in ms}
    sources = _sources(con, sorted(set(light_ids) | master_ids | set(flat_ids)))

    items: list[PlanItem] = []
    skipped: list[tuple] = []
    multi = set()

    def _pozycja(fid, *segments):
        src = sources.get(fid)
        if src is None:
            skipped.append((fid, _SKIP_NO_COPY))
            return
        path, n_present = src
        if n_present > 1:
            multi.add(fid)
        items.append(PlanItem(frame_id=fid, src=path, segments=segments,
                              basename=os.path.basename(path)))

    info_zestawy = {}
    for seg in sorted(zestawy):
        z = zestawy[seg]
        for fid in z["lights"]:
            _pozycja(fid, seg, "LIGHT", z["_filtr"][fid])
        for relacja in sorted(z["masters"]):
            for mid in sorted(z["masters"][relacja]):
                _pozycja(mid, seg, "MASTER", _segment({"relacja": relacja}, "relacja"))
        for fid in sorted(z["flat_raw"]):
            f = flat_facts[fid]
            _pozycja(fid, seg, "FLAT_RAW", _filter_segment(f["filter_canon"], f["is_mono"]))
        info_zestawy[seg] = {
            "config_id": z["config_id"], "config_ids": sorted(z["config_ids"]),
            "lights": z["lights"], "hours": round(z["hours"], 2),
            "masters": {k: sorted(v) for k, v in sorted(z["masters"].items())},
            "flat_raw": sorted(z["flat_raw"]), "flat_raw_nights": sorted(z["flat_raw_nights"]),
            "bez_flatu": z["bez_flatu"], "bez_darka": z["bez_darka"], "pending": z["pending"],
            "flat_gaps": dict(sorted(z["flat_gaps"].items()))}

    info = {"object_id": obj["id"], "object_canon": obj["canon"],
            "object_segment": _object_segment(con, obj["id"], obj["canon"]), "config_id": config_id,
            "window_days": window_days, "zestawy": info_zestawy}
    return Projection(layout=OBJECT_LAYOUT, items=items, skipped=skipped,
                      multi_present=len(multi), info=info)


def zestawy_configow(con):
    """`config_id -> (nazwa folderu zestawu, reprezentant)` dla WSZYSTKICH configów bazy.

    TOŻSAMOŚĆ zestawu = (teleskop KANONICZNY przez `telescope_canonical`, kamera configu) - brief
    „zestaw = teleskop + kamera". Config teleskopu scalonego z innym przy tej samej kamerze to ten
    sam fizyczny zestaw: dostaje TEN SAM folder, bo dwa foldery dałyby w WBPP dwie integracje jednej
    optyki. Reprezentant = najmniejszy `config_id` tożsamości (id rosną, więc stały).

    Etykieta `<teleskop>_<kamera>` (teleskop regułą `queries.telescope_label`) po `_segment`. Kolizja
    etykiet RÓŻNYCH tożsamości (nazwa usera powtórzona na dwóch teleskopach, sanityzacja zlewająca
    znaki) liczona po całej tabeli `config`, nie po klatkach - nazwa folderu nie może zależeć od
    tego, co akurat ma aktywne lighty. W kolizji obie tożsamości dostają `_cfg<reprezentant>`;
    bez kolizji etykieta zostaje gołą nazwą. Porównanie bez wielkości liter, jak nazwy folderów NTFS."""
    tozsamosc, etykieta, reprezentant = {}, {}, {}
    for r in con.execute(
            "SELECT c.id AS config_id, tc.canon_id AS telescope_id, c.camera_id AS camera_id, "
            "t.label AS telescope_label, t.telescop_canon AS telescop_canon, "
            "cam.model_canon AS camera_model "
            "FROM config c "
            "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
            "LEFT JOIN telescope t ON t.id = tc.canon_id "
            "LEFT JOIN camera cam ON cam.id = c.camera_id "
            "ORDER BY c.id"):
        klucz = (r["telescope_id"], r["camera_id"])
        tozsamosc[r["config_id"]] = klucz
        if klucz not in etykieta:                      # ORDER BY c.id: pierwszy = najmniejszy id
            etykieta[klucz] = _segment(
                {"zestaw": f"{queries.telescope_label(r)}_{r['camera_model'] or ''}"}, "zestaw")
            reprezentant[klucz] = r["config_id"]
    wiele = {e for e, n in Counter(e.lower() for e in etykieta.values()).items() if n > 1}
    folder = {k: (f"{e}_cfg{reprezentant[k]}" if e.lower() in wiele else e) for k, e in etykieta.items()}
    return {cid: (folder[k], reprezentant[k]) for cid, k in tozsamosc.items()}


def _object_segment(con, object_id, canon):
    """Nazwa folderu obiektu pod kartą celu. `_segment` nie jest różnowartościowy („Heart & Soul"
    i „Heart / Soul" dają ten sam napis, NTFS nie odróżnia też wielkości liter), więc dwa obiekty
    mogłyby wydać się do JEDNEGO folderu: drugi nadpisałby manifest pierwszego i zmieszał pliki.
    Gdy segment koliduje z segmentem dowolnego INNEGO kanonu w tabeli `object`, dostaje przyrostek
    `_obj<id>` - liczony po całej tabeli, więc stały niezależnie od tego, co akurat ma klatki."""
    seg = _segment({"obiekt": canon}, "obiekt")
    for r in con.execute("SELECT canon FROM object WHERE id <> ?", (object_id,)):
        if _segment({"obiekt": r["canon"]}, "obiekt").lower() == seg.lower():
            return f"{seg}_obj{object_id}"
    return seg


def object_root(target_root, projection):
    """Korzeń wydania obiektu = `<cel>/OBJECTS/<obiekt>` - JEDYNE miejsce składania tej ścieżki (CLI
    i GUI podają wynik do `apply`). Obiekt w korzeniu, nie w segmencie pozycji: manifest ląduje w folderze
    obiektu, więc obiekt B wydany na tę samą kartę celu nie nadpisuje proweniencji obiektu A. Przestrzeń
    `OBJECT_NAMESPACE` oddziela wydania obiektu od perspektyw na tej samej karcie (`po-obiektach` kładzie
    `<cel>/<obiekt>/<filtr>` - wspólny folder obiektu dałby WBPP każdy light dwa razy). Nazwę
    folderu liczy plan (`info["object_segment"]`, `_object_segment` - sanityzacja + rozstrzygnięcie
    kolizji), tu tylko się ją składa. Plan bez `info` (perspektywa gridu) → `ValueError`: perspektywa
    nie ma obiektu, do którego mogłaby się zawęzić."""
    if projection.layout != OBJECT_LAYOUT or projection.info is None:
        raise ValueError(f"korzeń obiektu wymaga planu {OBJECT_LAYOUT!r} z info "
                         f"(jest {projection.layout!r})")
    return os.path.join(target_root, OBJECT_NAMESPACE, projection.info["object_segment"])


def object_manifest(projection):
    """JEDYNE źródło treści manifestu wydania obiektu - CLI i GUI podają wynik jako `manifest=` do
    `apply`, więc dwie powierzchnie nie składają dwóch wersji tego samego zeznania. Listy id, nie
    ścieżki: ścieżki zna drzewo obok, a id przeżywają przeprowadzkę plików (żniwa czytają rodowód
    po id). Kopia głęboka - wołający dokłada swoje klucze (etykieta) bez ruszania `info` planu.
    Plan bez `info` (perspektywa gridu) → `ValueError`: manifest obiektu z niczego byłby kłamstwem.

    Do `info` dochodzi per zestaw `names: {nazwa pliku: frame_id}` lightów TEGO wydania
    (`PlanItem.basename` - nazwa, pod którą WBPP dostał klatkę). Historia stosu WBPP niesie nazwy wejść,
    a nazwa w bazie może się zmienić między wydaniem a żniwami (rename); żniwa dopasowują wejścia do
    nazw z wydania, nie do bieżących. Ta sama nazwa dwóch RÓŻNYCH klatek w jednym zestawie to `None` -
    nazwa, która nie wskazuje jednej klatki, nie jest świadkiem."""
    if projection.layout != OBJECT_LAYOUT or projection.info is None:
        raise ValueError(f"manifest obiektu wymaga planu {OBJECT_LAYOUT!r} z info "
                         f"(jest {projection.layout!r})")
    manifest = _copy.deepcopy(projection.info)
    for z in manifest["zestawy"].values():
        z["names"] = {}
    for item in projection.items:
        seg, rola = item.segments[0], item.segments[1]
        if rola != "LIGHT":
            continue
        names = manifest["zestawy"][seg]["names"]
        names[item.basename] = item.frame_id if names.get(item.basename, item.frame_id) == item.frame_id else None
    return manifest


# ============================================================ prymitywy filesystemu (KLINGA)

# Prefiks treści czytany przez obie sondy (`_same_content`): obejmuje nagłówek FITS/XISF, więc
# zmiana nagłówka po writebacku go rusza, a odczyt zostaje mały nawet po SMB.
_PROBE_BYTES = 65536
# Granica zgodności czasu modyfikacji kopii ze źródłem: `shutil.copy2` przenosi czas, ale FAT/exFAT
# zapisują go z ziarnem 2 s, więc kopia na takim nośniku różni się od źródła o ułamek tego ziarna.
_MTIME_TOLERANCE_NS = 2_000_000_000


class ProjectionAbort(Exception):
    """Sonda pierwszego linku wykazała rozjazd (wolumen nie daje hardlinków — SMB dał kopię) → abort
    PRZED masą. Niesie CZĘŚCIOWY `ApplyResult` (co najwyżej 1 utworzony link) do raportu wołającego —
    wzorzec `import_fitsmirror.ImportAbort` (cli.py łapie i raportuje). `message` to powód z kodem
    (`PowodPozycji`, AR-200): `str` wyjątku = zdanie PL dla CLI, `powod` - zdanie okna w języku UI
    (`item_reasons.powod_wyjatku`)."""
    def __init__(self, message, result):
        super().__init__(message)
        self.powod = message
        self.result = result


def _assert_excluded_segment(root):
    """Guard §0 CEL-POD-WYKLUCZENIEM: `root` MUSI mieć segment z `EXCLUDED_DIR_NAMES` (case-insensitive
    SET — NIE pojedynczy literał jak dawca). Hardlink = duplikat i-węzła, nieodróżnialny przez `os.walk`
    → dla hardlinków chroni WYŁĄCZNIE prune `dirnames` po nazwie. Brak segmentu → projekcja wróciłaby
    jako wejście skanu (sieroty). Split po OBU separatorach (`/`+`\\`) - przenośne (Windows/POSIX).

    Sprawdzamy ścieżkę ZNORMALIZOWANĄ (`abspath` + `normpath`), nie surowy tekst: `R:/ASTRO_/_WBPP/../LIGHTS`
    ma segment `_WBPP` w napisie, a system plików rozwiązuje `..` i pisze do `LIGHTS` - czyli do
    wejścia skanu. Wołający dalej używa `root` tak, jak go podał (Win32 rozwiązuje `..` tak samo),
    więc ścieżki w wyniku i manifeście się nie zmieniają.

    Odmowa to `OdmowaZPowodem` (podklasa `ValueError` - każdy `except ValueError` czyta zdanie PL jak
    dotąd) z kodem `proj_root_not_excluded`: okno wydania mówi ją w języku UI (AR-200)."""
    korzen = str(root)
    parts = [p for p in re.split(r"[\\/]+", os.path.normpath(os.path.abspath(korzen))) if p]
    if not any(p.lower() in EXCLUDED_DIR_NAMES for p in parts):
        names = " / ".join(sorted(n.upper() for n in EXCLUDED_DIR_NAMES))   # czytelne, wprost z setu (SPOT)
        raise OdmowaZPowodem(PowodPozycji(
            f"korzeń projekcji {korzen} nie zawiera segmentu wykluczonego ({names}) - "
            "projekcja poza wykluczeniem wróciłaby jako wejście skanu", "proj_root_not_excluded",
            dir=korzen, name=names))


def _link_to(src, dst, *, do_apply, copy):
    """Status src→KONKRETNY dst, ZERO nadpisania (§0). Zwraca `(status, reason|None)`:
    `would-link` (DRY, cel wolny) · `linked` (utworzony) · `exists` (ten sam i-węzeł, idempotentnie
    pomiń) · `conflict` (cel z INNYM i-węzłem - NIE clobber) · `verify_bad` (po `os.link` inny i-węzeł
    = SMB kopia) · `error` (I/O, np. EXDEV cross-wolumen → rada `--copy`; powód = błąd systemu klasą
    bez ścieżki, surowy tekst w `detail`, albo tekst systemu - `item_reasons.blad_systemu`, AR-184:
    `str(exc)` dawnego powodu niósł `'źródło' -> 'cel'`, a CLI dokleja nazwę trzeci raz). Odczyty stanu celu
    (`exists`/`stat`, w trybie kopii także prefiks treści) działają też w DRY (raport nad
    istniejącym drzewem).

    KOPIA Z WYDANIA TO `exists`, NIE `conflict`. Kopia ma z definicji inny i-węzeł, więc samo
    kryterium i-węzła nazywało konfliktem każdą kopię zrobioną przez poprzednie wydanie: ponowne
    wydanie obiektu po nowej nocy pokazywało setki konfliktów i stan „komplet" był w trybie kopii
    nieosiągalny. W trybie kopii cel z innym i-węzłem jest `exists` wtedy i tylko wtedy, gdy ma
    równy rozmiar, czas modyfikacji w granicy `_MTIME_TOLERANCE_NS` od źródła (`shutil.copy2`
    przenosi czas; tolerancja na ziarno 2 s FAT/exFAT) i zgodny prefiks treści (`_same_content`).
    To znaczy „to jest kopia, którą zrobiło wydanie", nie audyt integralności bajtów: pełne
    porównanie albo hash każdej pozycji biegłby przy każdym auto-DRY (sonda startuje na każdą zmianę
    parametru okna), a samo IC1795 w trybie kopii to ~17 GB odczytu po SMB.
    Prefiks obejmuje nagłówek FITS/XISF, więc kopia sprzed writebacku nagłówka zostaje
    `conflict` - nieaktualna kopia nazwana, nie nadpisana. Tryb hardlinków bez zmian: tam inny
    i-węzeł zawsze znaczy obcy plik."""
    try:
        if os.path.exists(dst):
            ss, ds = os.stat(src), os.stat(dst)
            if _ten_sam_plik(src, dst, ss, ds, copy=copy):
                return "exists", None
            if not copy:
                return "conflict", "cel istnieje z innym i-węzłem (nie nadpisuję)"
            return "conflict", "cel istnieje i nie jest kopią źródła (rozmiar/czas/treść; nie nadpisuję)"
        if not do_apply:
            return "would-link", None
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if copy:
            shutil.copy2(src, dst)                 # kopia bajtów (cross-wolumen; EXDEV omijamy)
        else:
            os.link(src, dst)                      # ten sam wolumen, zero bajtów
            if os.stat(src).st_ino != os.stat(dst).st_ino:
                return "verify_bad", "cel po os.link ma inny i-węzeł (SMB kopia?)"
        return "linked", None
    except OSError as exc:                         # EXDEV / brak uprawnień / znikłe źródło
        return "error", blad_systemu(exc)


def _verify_content(src, dst, nbytes=_PROBE_BYTES):
    """PEŁNA sonda tożsamości linku (port `wbpp_feed.py:268`): i-węzeł + rozmiar + prefiks treści.
    Sam `st_ino` za słaby - SMB potrafi zwrócić kopię o tym samym/zerowym ino; odczyt `nbytes` bajtów
    rozstrzyga. `True` = prawdziwy hardlink (ta sama treść pod tym samym i-węzłem)."""
    ss, ds = os.stat(src), os.stat(dst)
    return ss.st_ino == ds.st_ino and _same_content(src, dst, ss, ds, nbytes)


def _same_content(src, dst, ss, ds, nbytes=_PROBE_BYTES):
    """Rozmiar + prefiks treści - JEDNA sonda porównania treści dla obu pytań klingi: „czy ten
    hardlink jest prawdziwy" (`_verify_content`, z warunkiem i-węzła) i „czy ten cel jest kopią
    z wydania" (`_link_to` w trybie kopii, bez niego). `ss`/`ds` to `os.stat` wołającego - drugi
    `stat` po SMB nic by nie dodał. Rozmiar przed odczytem: różny rozmiar rozstrzyga bez otwierania."""
    if ss.st_size != ds.st_size:
        return False
    with open(src, "rb") as a, open(dst, "rb") as b:
        return a.read(nbytes) == b.read(nbytes)


def _ten_sam_wezel(ss, ds):
    """Ten sam plik na dysku - ta sama NIEZEROWA para `(st_dev, st_ino)` (AR-213). Zerowy i-węzeł
    (nośnik bez i-węzłów, część udziałów SMB) niczego nie dowodzi, a równy i-węzeł z innego
    urządzenia to inny plik."""
    return bool(ss.st_ino) and ss.st_ino == ds.st_ino and ss.st_dev == ds.st_dev


def _ten_sam_plik(src, dst, ss, ds, *, copy):
    """Czy plik `dst` jest TYM SAMYM plikiem co źródło `src` - JEDNA reguła dla „cel już stoi”
    wydania (`_link_to`), sondy kompletu naprawy manifestu i świadka drzewa (`_SwiadekDrzewa`): ten
    sam węzeł (`_ten_sam_wezel`) albo kopia z wydania - czas w `_MTIME_TOLERANCE_NS` i zgodny rozmiar
    z prefiksem treści (`_same_content`). Kopię z wydania sprawdza tryb kopii, a w trybie hardlinków
    także para z zerowym i-węzłem - tam węzeł nie rozstrzyga, a dwa zera nie są dowodem tożsamości.
    Tanie warunki przed odczytem: czas porównuje się bez otwierania plików, a rozmiar sprawdza
    `_same_content`, zanim przeczyta prefiks. Odczyt prefiksu może rzucić `OSError` - rozstrzyga
    wołający."""
    if _ten_sam_wezel(ss, ds):
        return True
    if not copy and ss.st_ino and ds.st_ino:
        return False
    return (abs(ss.st_mtime_ns - ds.st_mtime_ns) <= _MTIME_TOLERANCE_NS
            and _same_content(src, dst, ss, ds))


# ============================================================ APPLY (czysta MUTACJA filesystemu)


@dataclasses.dataclass(frozen=True)
class LinkResult:
    frame_id: int
    src: str
    dst: str
    # would-link|linked|exists|conflict|verify_bad|error|skipped|unverified (link utworzony, sonda
    # pierwszego linku nie przeczytała plików - AR-197)
    status: str
    reason: str | None = None


def _shape(layout, segments):
    """Kształt drzewa jako JEDEN maszynowy string: `wbpp-feed: object_canon/telescope_label|telescop_canon
    /filter_canon`. Language-neutral (nazwy kolumn), więc rdzeń może go oddać powierzchniom, a każda
    ubierze go własną prozą — inaczej polski komunikat rdzenia wyciekłby do wersji EN."""
    parts = []
    for spec in segments:
        cols = spec if isinstance(spec, (tuple, list)) else (spec,)
        parts.append("|".join(str(c) for c in cols))
    return f"{layout}: {'/'.join(parts)}"


def _manifest_z_pliku(root):
    """`(manifest albo None, uszkodzenie albo None)` z `_PROJEKCJA.json` w `root` - jeden odczyt dla
    tolerancyjnego `read_manifest` i kroku manifestu wydania (`_write_manifest`, AR-234). Brak pliku
    (klasa `os_missing`) → `(None, None)`; bajty spoza UTF-8, JSON nieczytelny albo nie-słownik →
    `(None, "UTF-8" | "JSON" | "manifest")` (nazwy pól jak w `_odczyt_scisly`). Inny błąd systemu -
    odmowa, zerwany udział, także po udanym `stat` - RZUCA `OSError`: to „nie wiem”, nie „nie ma”."""
    try:
        with open(os.path.join(root, MANIFEST_NAME), "rb") as fh:
            dane = fh.read()
    except OSError as exc:
        if getattr(powod_systemu(exc), "code", None) == "os_missing":
            return None, None
        raise
    try:
        payload = json.loads(dane.decode("utf-8"))
    except UnicodeDecodeError:
        return None, "UTF-8"
    except ValueError:
        return None, "JSON"
    return (payload, None) if isinstance(payload, dict) else (None, "manifest")


def read_manifest(root, *, errors_out=None):
    """`_PROJEKCJA.json` z korzenia → dict albo None. TOLERANCYJNY z rozmysłem: manifest jest
    efemeryczny i user może go skasować w Eksploratorze razem z drzewem, więc brak pliku, uszkodzony
    JSON i brak uprawnień dają None - nigdy wyjątek w środku sondy.

    `errors_out` (lista, AR-234): manifest, który LEŻY, a którego nie da się przeczytać - błąd systemu
    spoza `os_missing` (powód klasą, `blad_systemu`) albo plik uszkodzony (`proj_manifest_damaged` z polem
    w `detail` i ścieżką: bajty, JSON, a w zeznaniu wydania obiektu także zła struktura - TEN SAM
    walidator co krok manifestu wydania i naprawa, `_odmowa_starego`) - `(ścieżka manifestu, powód)`;
    wynik None. Żniwa mówią wtedy o wydaniu, zamiast zgubić je z listy jak brak manifestu, i nigdy nie
    uznają folderu za wciągnięty nad manifestem, który okno wydania odrzuca. Bez listy - jak dotąd."""
    sciezka = os.path.join(root, MANIFEST_NAME)
    try:
        payload, uszkodzenie = _manifest_z_pliku(root)
    except OSError as exc:
        if errors_out is not None:
            errors_out.append((sciezka, blad_systemu(exc)))
        return None
    if errors_out is None:
        return payload
    odmowa = (_odmowa_uszkodzonego(uszkodzenie, sciezka) if uszkodzenie is not None
              else _odmowa_starego(payload, sciezka, layout=OBJECT_LAYOUT) if payload is not None else None)
    if odmowa is not None:
        errors_out.append((sciezka, odmowa))
        return None
    return payload


def manifest_drift(root, layout):
    """Kształt drzewa, KTÓRY W TYM KORZENIU JUŻ STOI, jeśli różni się od bieżącego — inaczej None.

    Manifest niósł `segments` od pierwszego dnia, ale NIKT ich nie czytał (resztka z recenzji P2).
    Rozjazd jest cichy i kosztowny: zmiana definicji layoutu (P2: `telescope_label` → coalesce
    z `telescop_canon`) albo nazwanie teleskopu przez usera przesuwa katalogi, więc ponowne wydanie
    do TEGO SAMEGO korzenia buduje DRUGIE drzewo obok starego — te same i-węzły, a WBPP policzy
    klatki dwa razy. Stare pozycje nie są `conflict` (leżą pod inną ścieżką), więc raport bez tego
    cross-checku wygląda na czysty.

    Manifest bez `segments` (zapisany przed tym polem) → milczymy: brak zeznania to nie rozjazd."""
    payload = read_manifest(root)
    if not payload or not payload.get("segments"):
        return None
    was = _shape(payload.get("layout"), payload["segments"])
    return None if was == _shape(layout, layout_segments(layout)) else was


@dataclasses.dataclass(frozen=True)
class ApplyResult:
    root: str
    layout: str
    do_apply: bool
    copy: bool
    results: list                     # list[LinkResult] — pełny per-frame (items + skipped z planu)
    cancelled: bool = False
    # Kształt drzewa, które w korzeniu JUŻ stało, gdy różni się od bieżącego (`manifest_drift`).
    # Ostrzeżenie, NIE blokada: rozstrzygnięcie („inny korzeń czy świadome dołożenie") należy do
    # człowieka, a projekcja jest kasowalna w Eksploratorze.
    drift: str | None = None
    # Wydanie przerwane przed końcem (AR-197): krok z błędem systemu (`proj_root_failed`,
    # `proj_out_failed`, `proj_verify_failed`, `proj_manifest_failed` - klasa systemu w `inner`, także
    # stary manifest, którego nie da się przeczytać - AR-234), manifest zajęty cudzym plikiem roboczym
    # (`proj_manifest_busy`, AR-213), stary manifest uszkodzony (`proj_manifest_damaged`, AR-234) albo
    # werdykt sondy pierwszego linku (`proj_first_link`, wynik częściowy `ProjectionAbort`). `None` =
    # wydanie doszło do końca; manifest leży wtedy i tylko wtedy, gdy `do_apply` i `error is None`.
    error: object = None
    # Ile id wcześniejszych wydań manifest ZAPOMNIAŁ, bo ich plików dowodnie nie ma w drzewie
    # (scalenie bez utraty, AR-213: `_merge_object_manifest` ze świadkiem `extra_sources`).
    dropped: int = 0

    @property
    def counts(self) -> dict:
        c: dict = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c


def apply(projection, root, *, do_apply, copy=False, now=None, manifest=None, extra_sources=None,
          progress: Callable[[int, int, str, str], None] | None = None,
          should_cancel: Callable[[], bool] | None = None) -> ApplyResult:
    """Zmaterializuj PLAN w drzewo `<root>/<segmenty>/<basename>`. `do_apply=False` = DRY (sonduje stan
    celu, ZERO tworzenia). `do_apply=True` = realne linki/kopie. Guard §0 (`_assert_excluded_segment`)
    PRZED czymkolwiek. Pierwszy realny hardlink (nie `copy`) sondowany PEŁNYM `_verify_content` → rozjazd
    = `ProjectionAbort` (częściowy wynik: 1 link). `progress(done,total,dst,status)` po KAŻDYM frame'ie
    (Qt-wolne). `should_cancel` PRZED frame'em (anulowanie na granicy pliku). Przy `do_apply` pisze
    `_PROJEKCJA.json` obok korzenia (PLIK, nie DB), a wydanie obiektu zakłada też `<root>/out`
    (`OUTPUT_DIR`, wyjście WBPP). Pominięte z planu dochodzą jako `skipped`.

    BŁĄD SYSTEMU W KROKU WYDANIA (AR-197) to wynik z powodem (`ApplyResult.error`), nie wyjątek:
    korzeń (nic nie powstało), wyjście WBPP (korzeń już stoi), sonda pierwszego linku, która nie
    przeczytała plików (link powstał - pozycja `unverified`, masa nie rusza), manifest (pliki
    wydania leżą, poprzedni manifest nietknięty). Dawniej `OSError` z tych kroków wychodził z CLI
    `project` śladem stosu.

    `extra_sources` (`manifest_sources` wołającego - wydanie obiektu): obecne kopie klatek, które
    wymienia manifest JUŻ leżący w korzeniu - świadkowie scalenia bez utraty (AR-213). Bez nich id
    wcześniejszych wydań spoza tego planu zostają w manifeście (niepewne - nic nie ginie); z nimi
    id, którego pliku dowodnie nie ma w drzewie, schodzi z manifestu (`ApplyResult.dropped`)."""
    _assert_excluded_segment(root)
    # PRZED czymkolwiek: `_write_manifest` nadpisze zeznanie starego drzewa, więc po masie nie byłoby
    # już czego czytać. DRY sonduje ten sam fakt, bo to właśnie DRY ma ostrzec PRZED wydaniem.
    drift = manifest_drift(root, projection.layout)
    if do_apply:
        try:
            os.makedirs(root, exist_ok=True)       # korzeń istnieje dla linków I manifestu (KLINGA)
        except OSError as exc:
            inner = blad_systemu(exc)
            return ApplyResult(root, projection.layout, do_apply, copy, _z_kwarantanna([], projection),
                               False, drift, PowodPozycji(
                                   f"nie założono folderu wydania: {inner}", "proj_root_failed",
                                   inner=inner))
        if projection.layout == OBJECT_LAYOUT:
            # Wyjście WBPP wydania obiektu powstaje razem z wydaniem, nie przy wyborze folderu
            # roboczego: slot GUI nie dotyka dysku, a DRY niczego nie zakłada.
            try:
                os.makedirs(os.path.join(root, OUTPUT_DIR), exist_ok=True)
            except OSError as exc:
                inner = blad_systemu(exc)
                return ApplyResult(root, projection.layout, do_apply, copy,
                                   _z_kwarantanna([], projection), False, drift, PowodPozycji(
                                       f"folder wydania założony, ale folder wyjścia WBPP ({OUTPUT_DIR}) "
                                       f"nie powstał: {inner}", "proj_out_failed", inner=inner))

    results: list[LinkResult] = []
    cancelled = False
    first_hardlink_checked = False
    total = len(projection.items)
    done = 0

    for item in projection.items:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        dst = os.path.join(root, *item.segments, item.basename)
        status, reason = _link_to(item.src, dst, do_apply=do_apply, copy=copy)

        # Sonda PIERWSZEGO realnie utworzonego hardlinka (nie `copy`): rozjazd = TWARDY ABORT przed
        # masą (§0). „Realnie utworzony" = `linked` (i-węzeł ok w `_link_to`) LUB `verify_bad`
        # (szybki i-węzeł już padł). Bez tego SMB-kopia zlinkowałaby całą masę zamiast abortować.
        if do_apply and not copy and status in ("linked", "verify_bad") and not first_hardlink_checked:
            first_hardlink_checked = True
            try:
                zly = status == "verify_bad" or not _verify_content(item.src, dst)
            except OSError as exc:
                # Link POWSTAŁ (`_link_to`), a sonda nie przeczytała plików: tożsamości nie
                # dowiedziono, więc masa nie rusza. Pozycja mówi „utworzony, niezweryfikowany”
                # (`unverified`) i liczy się do postępu jak każda inna.
                inner = blad_systemu(exc)
                powod = PowodPozycji(
                    f"link utworzony, ale sonda pierwszego linku nie odczytała plików - wydanie "
                    f"zatrzymane przed masą: {inner}", "proj_verify_failed", inner=inner)
                results.append(LinkResult(item.frame_id, item.src, dst, "unverified", powod))
                done += 1
                if progress is not None:
                    progress(done, total, dst, "unverified")
                return ApplyResult(root, projection.layout, do_apply, copy,
                                   _z_kwarantanna(results, projection), cancelled, drift, powod)
            if zly:
                results.append(LinkResult(item.frame_id, item.src, dst, "verify_bad",
                                          reason or "sonda pierwszego linku: cel nie jest hardlinkiem (i-węzeł/treść)"))
                abort = PowodPozycji(
                    "pierwszy link nie przeszedł sondy tożsamości (i-węzeł/rozmiar/treść) - "
                    "wolumen nie wspiera hardlinków? włącz tryb kopii", "proj_first_link")
                partial = ApplyResult(root, projection.layout, do_apply, copy,
                                      _z_kwarantanna(results, projection), cancelled, drift, abort)
                raise ProjectionAbort(abort, partial)

        results.append(LinkResult(item.frame_id, item.src, dst, status, reason))
        done += 1
        if progress is not None:
            progress(done, total, dst, status)

    result = ApplyResult(root, projection.layout, do_apply, copy, _z_kwarantanna(results, projection),
                         cancelled, drift)
    if do_apply:
        try:
            dropped = _write_manifest(root, result, now=now, manifest=manifest,
                                      extra_sources=extra_sources)
        except _PartZajety as exc:
            return dataclasses.replace(result, error=_odmowa_zajetego(exc.part))
        except _OdmowaStarego as exc:
            return dataclasses.replace(result, error=exc.powod)
        except OSError as exc:
            return dataclasses.replace(result, error=_powod_manifestu(blad_systemu(exc)))
        if dropped:
            return dataclasses.replace(result, dropped=dropped)
    return result


def _powod_manifestu(inner):
    """Powód „manifestu nie zapisano” (`proj_manifest_failed`) - jedno zdanie dla kroku manifestu
    wydania i dla naprawy manifestu (`repair_manifest`). Mówi, CZEGO brakuje i PO CO: z manifestu
    żniwa rozpoznają obiekt wydania (`harvest`, okno żniw), a strażnik rozjazdu układu
    (`manifest_drift`) czyta z niego kształt drzewa. Zapis atomowy zostawia manifest POPRZEDNI, gdy
    był - zdanie nie obiecuje więc ani braku rozpoznania, ani braku ostrzeżenia, tylko to, że manifest
    tych plików nie opisuje. `inner` - błąd systemu klasą albo tekst systemu (`blad_systemu`)."""
    return PowodPozycji(
        f"nie zapisano manifestu wydania ({MANIFEST_NAME}) - pliki tego wydania leżą w celu, "
        f"ale manifest ich nie opisuje (brak go albo został poprzedni), więc rozpoznanie "
        f"obiektu przy wciąganiu wyników WBPP i kontrola układu drzewa przy następnym "
        f"wydaniu mogą być niepełne: {inner}",
        "proj_manifest_failed", inner=inner)


class _PartZajety(Exception):
    """Plik roboczy manifestu (`.part`) już leży - zapis innego pisarza w toku albo jego resztka.
    Nie `OSError`: krok manifestu wydania mówi wtedy odmową `proj_manifest_busy`, nie błędem systemu."""

    def __init__(self, part):
        super().__init__(part)
        self.part = part


class _OdmowaStarego(Exception):
    """Stary manifest w korzeniu, którego krok manifestu wydania nie wolno zastąpić (AR-234,
    `_odmowa_starego`): uszkodzony (`proj_manifest_damaged`) albo zeznanie wydania obiektu, które
    zastąpiłby inny układ albo wydanie innego obiektu (`proj_manifest_foreign`) - `powod`, jak w naprawie.
    Nadpis gubiłby jedyne zeznanie wcześniejszych wydań, z którego żniwa rozpoznają ich pliki."""

    def __init__(self, powod):
        super().__init__(powod)
        self.powod = powod


def _odmowa_zajetego(part):
    """Powód „plik roboczy manifestu zajęty” (`proj_manifest_busy`) - jedno zdanie dla kroku
    manifestu wydania i dla naprawy manifestu: obaj pisarze zakładają `.part` wyłącznie (`x`),
    więc cudzy `.part` znaczy zapis w toku albo resztkę po przerwanym. Zdanie mówi fakt i radę
    wspólną dla każdej powierzchni; gest ponowienia dokłada powierzchnia (okno - przyciski, CLI -
    polecenie, AR-251)."""
    return PowodPozycji(
        f"obok manifestu leży plik roboczy innego zapisu ({part}) - gdy żaden zapis nie trwa, skasuj "
        f"go ręcznie", "proj_manifest_busy", path=part)


def _powod_odczytu(inner):
    """Powód „manifestu nie da się odczytać” (`proj_manifest_unreadable`) - ścisły odczyt naprawy
    (`_odczyt_scisly`) padł błędem systemu innym niż brak pliku; naprawa niczego wtedy nie zapisuje."""
    return PowodPozycji(
        f"manifestu wydania ({MANIFEST_NAME}) nie da się odczytać - nie nadpisuję go: {inner}",
        "proj_manifest_unreadable", inner=inner)


def _z_kwarantanna(results, projection):
    """Pozycje wydania + kwarantanna planu (`skipped`) - JEDNA reguła dla wyniku pełnego i każdego
    przerwanego (abort sondy, krok z błędem systemu): bez niej raport przerwanego wydania głosił
    „pominięto: 0”, choćby plan miał klatki bez obecnej kopii (R#6)."""
    return results + [LinkResult(fid, "", "", "skipped", why) for fid, why in projection.skipped]


def _write_manifest(root, result: ApplyResult, *, now, manifest, extra_sources=None):
    """Zapisz `_PROJEKCJA.json` obok korzenia (PLIK, nie DB — projekcja efemeryczna, JEDNA-KLINGA
    nietknięta; brief §3). Snapshot: layout/korzeń/tryb/ts/liczności + `manifest` wołającego
    (perspektywa/filtr/wolumen). `open(part, "x")` żyje w tej klindze (DOOR meta-testu). Wydanie obiektu
    scala `zestawy` ze starym manifestem tego samego obiektu (`_merge_object_manifest`, świadek drzewa
    z `extra_sources`); układy kolumnowe piszą dokładnie to, co pisały. Zwraca liczbę id zdjętych
    z manifestu (dowodnie nieobecnych w drzewie) - 0 poza wydaniem obiektu.

    Publikacja ATOMOWA (AR-197): treść idzie do `.part` obok, `fsync`, potem `os.replace` na manifest.
    Dawny `open(manifest, "w")` ucinał plik przy awarii w połowie zapisu i niszczył zeznanie
    poprzedniego wydania, z którego żniwa rozpoznają pliki.

    WYŁĄCZNOŚĆ `.part` (AR-213) - jeden protokół z naprawą manifestu (`repair_manifest`): `.part`
    zakładany `x` PRZED odczytem starego manifestu i trzymany do publikacji, więc dwóch pisarzy
    (wydanie z CLI i naprawa z okna) nie pisze w jeden plik roboczy ani nie scala z manifestem,
    który drugi właśnie podmienia. Cudzy `.part` → `_PartZajety` (krok manifestu mówi
    `proj_manifest_busy`, nic nie ruszone); przy błędzie zdejmowany jest wyłącznie własny `.part`.

    Świadek scalenia zna obecne kopie klatek starego manifestu (`extra_sources`) i źródła pozycji
    tego wydania - te drugie dla pełności nazw zestawu (`_merge_object_manifest`).

    STARY MANIFEST CZYTANY ŚCIŚLE przed KAŻDĄ publikacją, w każdym układzie (AR-234,
    `_manifest_z_pliku`): brak - scalenia nie ma; błąd systemu odczytu (odmowa, zerwany udział - także
    po udanym `stat`) wychodzi `OSError` (krok mówi `proj_manifest_failed` z klasą); plik uszkodzony
    albo zeznanie, którego ten zapis nie może zastąpić (`_odmowa_starego`: zła struktura manifestu
    obiektu, manifest obiektu zastępowany innym układem albo wydaniem innego obiektu) - `_OdmowaStarego`.
    Za każdym razem `.part` zdjęty, a stary manifest nietknięty: tolerancyjny odczyt brał „nie wiem”
    za „nie ma” i zapis gubił zestawy wcześniejszych wydań (zmierzone na prawdziwym ACL), a wydanie
    perspektywy z CLI do folderu obiektu zastępowało jego zeznanie bez słowa."""
    # `segments` obok `layout`: sama NAZWA presetu nie identyfikuje drzewa — zmiana definicji layoutu
    # (P2: `telescope_label`→coalesce z `telescop_canon`) albo nazwanie teleskopu przez usera przesuwa
    # katalogi, a ponowne wydanie do tego samego korzenia zbudowałoby DRUGIE drzewo obok starego
    # (te same i-węzły → WBPP policzyłby klatki dwa razy). Manifest niesie zestaw, którym drzewo powstało.
    payload = {
        "layout": result.layout,
        "segments": [list(s) if isinstance(s, tuple) else [s] for s in layout_segments(result.layout)],
        "root": root,
        "copy": result.copy,
        "ts": now,
        "n_items": len(result.results),
        "counts": result.counts,
    }
    path = os.path.join(root, MANIFEST_NAME)
    part = path + PART_SUFFIX
    try:
        fh = open(part, "x", encoding="utf-8")
    except FileExistsError:
        raise _PartZajety(part) from None
    dropped = 0
    try:
        with fh:
            stary, uszkodzenie = _manifest_z_pliku(root)
            odmowa = (_odmowa_uszkodzonego(uszkodzenie, path) if uszkodzenie is not None
                      else _odmowa_starego(stary, path, layout=result.layout,
                                           object_id=(manifest or {}).get("object_id"))
                      if stary is not None else None)
            if odmowa is not None:
                raise _OdmowaStarego(odmowa)
            if manifest:
                if result.layout == OBJECT_LAYOUT and "zestawy" in manifest:
                    zrodla = {fid: list(p) for fid, p in (extra_sources or {}).items()}
                    for r in result.results:
                        if r.src and r.src not in zrodla.setdefault(r.frame_id, []):
                            zrodla[r.frame_id].append(r.src)
                    manifest, dropped = _merge_object_manifest(
                        stary, manifest, now=now, root=root, cancelled=result.cancelled,
                        swiadek=_SwiadekDrzewa(root, zrodla),
                        pominiete={r.frame_id for r in result.results if r.status == "skipped"})
                payload.update(manifest)
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(part, path)
    except BaseException:
        _drop_part(part)
        raise
    return dropped


def _merge_object_manifest(old, manifest, *, now, root, cancelled, swiadek, pominiete=frozenset()):
    """Proweniencja zestawów przeżywa wydanie INNEGO zestawu tego samego obiektu: drzewo zestawu
    wydanego wczoraj dalej leży w korzeniu obiektu, więc manifest, który by go zapomniał, kłamałby
    żniwom o tym, skąd te linki są. Wpisy bieżącego wydania dostają `ts` tej chwili; wpisy starego
    manifestu, których bieżące wydanie nie dotyka, zostają ze SWOIM `ts` (zapisanym przy nich albo -
    gdy go nie było - z nagłówka starego manifestu). Inny układ albo inny obiekt w tym korzeniu =
    nadpisanie jak dla każdego układu: obce zeznanie nie należy do tego drzewa. `old` ze ścisłego
    odczytu kroku manifestu (`_manifest_z_pliku`) - brak pliku to brak scalenia; plik nieczytelny albo
    uszkodzony do scalenia nie dochodzi, krok manifestu odmawia wcześniej (AR-234).

    Stary wpis zestawu spoza wydania schodzi TYLKO z dowodem, że jego folderu w korzeniu nie ma
    (`_stan_folderu` - sam odczyt; jego id liczą się do zwrotu): user kasuje wydanie w Eksploratorze,
    a manifest, który pamiętałby skasowane drzewo, zeznawałby o linkach, których nie ma. Folder,
    którego stanu nie da się odczytać (odmowa dostępu, zerwany udział), zostawia wpis bez zmian -
    `os.path.isdir` brał taki błąd za brak i gubił zeznanie (AR-213). Wydanie ANULOWANE
    (`cancelled`) zostawia w drzewie tylko część pozycji, więc jego wpisy dostają
    `"cancelled": true` - listy id mówią wtedy, co wydanie zamierzało, nie co leży na dysku. Wpis
    bez tego klucza to wydanie domknięte.

    NAZWY ZESTAWU WYDANEGO PONOWNIE SIĘ SUMUJĄ (`_merge_names`), a LISTY ID BEZ UTRATY (F-C1, AR-213):
    pliki poprzedniego wydania zostają w folderze zestawu (klinga nie kasuje), więc WBPP je dostanie,
    a żniwa muszą je dalej rozpoznać - po nazwie i po listach (`flat_raw` nazywa wydanie surowych
    flatów). Id starego wpisu spoza listy bieżącego wydania zostaje, chyba że świadek drzewa
    (`swiadek`) DOWODZI, że jego pliku w roli zestawu nie ma - wtedy schodzi i liczy się do zwrotu;
    niepewny (świadek bez kopii klatki, plik nieczytelny) ZOSTAJE: wydanie nie pada na historii,
    a zachowanie niczego nie zmyśla. Pozostała część wpisu - z bieżącego wydania. Wpis anulowany po
    którejkolwiek stronie też wnosi swoje nazwy - część jego plików leży na dysku, a nazwa pliku,
    którego nie ma, niczego w historii WBPP nie dopasuje.

    NAZWY BEZ CZĘŚCIOWEJ MAPY (AR-213): stary wpis bez `names` z zachowanymi lightami spoza tego
    wydania dostaje nazwy z DRZEWA (`_SwiadekDrzewa.nazwy`) dla scalonych lightów (bez klatek
    planu bez kopii - `pominiete`) wyłącznie przy pełnym mapowaniu; inaczej `names` schodzi.
    Mapa samego bieżącego wydania obok zachowanych lightów wyłączyłaby żniwom spadek na bazę dla
    starszych klatek. Zwraca `(manifest, zdjęte id)`."""
    stempel = {"ts": now, "cancelled": True} if cancelled else {"ts": now}
    zestawy = {seg: {**z, **stempel} for seg, z in manifest["zestawy"].items()}
    dropped = 0
    if (old and old.get("layout") == OBJECT_LAYOUT and old.get("object_id") == manifest.get("object_id")
            and isinstance(old.get("zestawy"), dict)):
        for seg, z in old["zestawy"].items():
            if not isinstance(z, dict):
                continue
            if seg not in zestawy:
                stan = _stan_folderu(os.path.join(root, seg))
                if stan == _NIE_MA:
                    dropped += len(_id_wpisu(z))
                elif stan == _NIEPEWNY:
                    zestawy[seg] = {**z, "ts": z.get("ts", old.get("ts"))}
                else:
                    listy, _kept, zdjete, _niepewne = _listy_bez_utraty(seg, {}, z, swiadek)
                    zestawy[seg] = {**z, **listy, "ts": z.get("ts", old.get("ts"))}
                    dropped += zdjete
                continue
            plan_lights = set(_ids(zestawy[seg].get("lights")))
            listy, _kept, zdjete, _niepewne = _listy_bez_utraty(seg, zestawy[seg], z, swiadek)
            zestawy[seg].update(listy)
            dropped += zdjete
            nazwy = _nazwy_scalone(
                zestawy[seg].get("names"), z.get("names"), bool(set(listy["lights"]) - plan_lights),
                lambda seg=seg, lights=listy["lights"]: swiadek.nazwy(seg, sorted(set(lights) - set(pominiete))))
            if nazwy is None:
                zestawy[seg].pop("names", None)
            else:
                zestawy[seg]["names"] = nazwy
    return {**manifest, "zestawy": dict(sorted(zestawy.items()))}, dropped


def _nazwy_scalone(nowe, stare, nadmiar, z_drzewa):
    """Mapa `names` zestawu po scaleniu starego wpisu z bieżącym albo None (klucz schodzi) - JEDNA
    reguła wydania (`_merge_object_manifest`) i naprawy (`_tresc_naprawy`, gdy drzewo nie daje pełnej
    mapy), AR-213, AR-240. `nowe` - nazwy planu (pod nimi WBPP dostał lighty tego wydania), `stare` -
    nazwy starego wpisu, `nadmiar` - scalone `lights` wychodzą poza plan, `z_drzewa` - funkcja → pełna
    mapa z drzewa albo None (woła ją wyłącznie gałąź, która jej potrzebuje: świadek czyta folder
    `LIGHT`). Stara i nowa - suma (`_merge_names`), więc nazwy nowych lightów przeżywają niepewny stary
    light; sama stara - stara; bez starej przy lightach spoza planu - mapa z drzewa (scalona z nową)
    albo None, bo mapa samego planu obok zachowanych lightów wyłączyłaby żniwom spadek na bazę dla
    starszych klatek; inaczej nowa."""
    nowe = nowe if isinstance(nowe, dict) else None
    if isinstance(stare, dict):
        return _merge_names(stare, nowe) if nowe is not None else stare
    if nadmiar:
        pelna = z_drzewa()
        return pelna if pelna is None or nowe is None else _merge_names(pelna, nowe)
    return nowe


def _merge_names(stare, nowe):
    """Suma map `{nazwa pliku: frame_id}` dwóch wydań jednego zestawu - nowa mapa. Ta sama nazwa
    z innym `frame_id` albo z `None` po którejkolwiek stronie to `None`: nazwa, która nie wskazuje
    jednej klatki, nie jest świadkiem (ta sama reguła co kolizja w `object_manifest`)."""
    out = dict(stare)
    for name, fid in nowe.items():
        if name in out and (out[name] is None or fid is None or out[name] != fid):
            out[name] = None
        else:
            out[name] = fid
    return out


# ============================================================ ŚWIADEK DRZEWA I NAPRAWA MANIFESTU (AR-213)

# Listy id zestawu manifestu → folder ich roli w drzewie wydania (`plan_object`); mastery - osobno,
# bo to słownik relacji, a wszystkie relacje leżą pod `MASTER`.
_ROLE_LIST = (("lights", "LIGHT"), ("flat_raw", "FLAT_RAW"))
_ROLA_MASTEROW = "MASTER"
_JEST, _NIE_MA, _NIEPEWNY = "jest", "nie_ma", "niepewny"


class _Przerwano(Exception):
    """Diagnoza naprawy przerwana na żądanie wołającego (`should_cancel`) - wynik `cancelled`."""


def _ids(wartosc):
    """Lista id z pola manifestu - tolerancyjnie (droga wydania czyta manifest `read_manifest`):
    nie-lista albo element nie-int (bool to nie id) odpada."""
    if not isinstance(wartosc, list):
        return []
    return [v for v in wartosc if isinstance(v, int) and not isinstance(v, bool)]


def _id_wpisu(z):
    """Id list jednego wpisu zestawu (`lights`, `flat_raw`, relacje `masters`) - każda lista bez
    powtórzeń, tolerancyjnie; rozliczenie wpisu zdjętego albo niepewnego w całości (`_stan_folderu`)."""
    out = []
    for pole, _rola in _ROLE_LIST:
        out.extend(sorted(set(_ids(z.get(pole)))))
    mastery = z.get("masters")
    for _rel, ids in (sorted(mastery.items()) if isinstance(mastery, dict) else ()):
        out.extend(sorted(set(_ids(ids))))
    return out


def _stan_folderu(path):
    """`jest` | `nie_ma` | `niepewny` - folder zestawu w korzeniu wydania (AR-213). `nie_ma` WYŁĄCZNIE
    z dowodem: klasa `os_missing` (`powod_systemu`) albo plik w miejscu folderu; inny błąd systemu
    (odmowa dostępu, zerwany udział) to `niepewny` - `os.path.isdir` brał go za brak folderu."""
    try:
        st = os.stat(path)
    except OSError as exc:
        klasa = powod_systemu(exc)
        return _NIE_MA if klasa is not None and klasa.code == "os_missing" else _NIEPEWNY
    return _JEST if stat.S_ISDIR(st.st_mode) else _NIE_MA


def _ids_manifestu(payload):
    """Wszystkie id, które manifest wydania obiektu wymienia w listach zestawów (tolerancyjnie)."""
    out = set()
    zestawy = payload.get("zestawy") if isinstance(payload, dict) else None
    for z in (zestawy.values() if isinstance(zestawy, dict) else ()):
        if not isinstance(z, dict):
            continue
        for pole, _rola in _ROLE_LIST:
            out.update(_ids(z.get(pole)))
        mastery = z.get("masters")
        for ids in (mastery.values() if isinstance(mastery, dict) else ()):
            out.update(_ids(ids))
    return out


def _obecne_kopie(con, ids):
    """`frame_id -> [ścieżki obecnych kopii]` w porządku `location_id` (`present_locations`, R#1) -
    jedno źródło dla wyboru źródła linku (`_sources`: pierwsza) i dla świadka drzewa (każda)."""
    out = {}
    for r in queries.present_locations(con, sorted(ids)):
        if r["location_id"] is not None:
            out.setdefault(int(r["frame_id"]), []).append(r["path"])
    return out


def manifest_sources(con, root):
    """Obecne kopie (`_obecne_kopie`) każdej klatki, którą wymienia manifest JUŻ leżący w korzeniu
    wydania obiektu (`read_manifest`, tolerancyjnie) - `extra_sources` dla `apply`: świadkowie
    scalenia bez utraty (AR-213). Brak manifestu → `{}`. Odczyt bazy i manifestu, zero zapisu."""
    return _obecne_kopie(con, _ids_manifestu(read_manifest(root)))


class _SwiadekDrzewa:
    """Czy klatka LEŻY w drzewie wydania obiektu - w folderze swojej roli (`<root>/<zestaw>/<LIGHT|
    MASTER|FLAT_RAW>/**`) - ustalane z plików, nie z manifestu. Świadkiem jest plik, który jest TYM
    SAMYM plikiem co któraś obecna kopia klatki (`sources`, `_obecne_kopie`): ten sam węzeł
    (`_ten_sam_wezel` - niezerowa para urządzenie/i-węzeł) albo kopia z wydania (`_ten_sam_plik`
    w trybie kopii - także przy zerowych i-węzłach).

    Werdykt (`werdykt`): `jest`; `nie_ma` - DOWÓD nieobecności: każda obecna kopia czytelna, folder
    roli przeczytany (brak folderu to pusty folder), a w nim ani tego pliku, ani pliku o nazwie
    którejś kopii; `niepewny` - klatka bez kopii w `sources`, kopia albo folder nieczytelne, a w roli
    INNY plik pod jej nazwą (np. kopia sprzed zapisu nagłówka). Sam odczyt; folder roli czytany raz.
    `sources=None` (wołający bez bazy) - każdy werdykt `niepewny`. `should_cancel` (diagnoza okna)
    sprawdzany przed każdym folderem i każdą klatką - prawda → `_Przerwano`."""

    def __init__(self, root, sources, should_cancel=None):
        self._root = root
        self._zrodla = sources or {}
        self._anuluj = should_cancel
        self._role = {}
        self._kopie_klatek = {}

    def _stop(self):
        if self._anuluj is not None and self._anuluj():
            raise _Przerwano

    def _pliki(self, seg, rola):
        """`([(ścieżka, stat)], czy odczyt niepełny)` plików roli zestawu (rekurencyjnie)."""
        klucz = (seg, rola)
        if klucz not in self._role:
            bledy, pliki = [], []

            def _blad(exc):
                powod = powod_systemu(exc)
                if powod is None or powod.code != "os_missing":   # brak folderu = pusty folder
                    bledy.append(exc)
            for dp, _dn, fn in os.walk(os.path.join(self._root, seg, rola), onerror=_blad):
                self._stop()
                for n in fn:
                    p = os.path.join(dp, n)
                    try:
                        pliki.append((p, os.stat(p)))
                    except OSError:
                        bledy.append(p)
            self._role[klucz] = (pliki, bool(bledy))
        return self._role[klucz]

    def _kopie(self, fid):
        """`([(ścieżka, stat)] czytelnych obecnych kopii, czy któraś nieczytelna)`."""
        if fid not in self._kopie_klatek:
            self._stop()
            kopie, blad = [], False
            for src in self._zrodla.get(fid) or ():
                try:
                    kopie.append((src, os.stat(src)))
                except OSError:
                    blad = True
            self._kopie_klatek[fid] = (kopie, blad)
        return self._kopie_klatek[fid]

    def _plik_klatki(self, pliki, fid):
        """`(plik roli będący tą samą treścią co kopia klatki albo None, czy porównanie niepełne)` -
        najpierw tanio po węźle (`_ten_sam_wezel`), potem kopia z wydania (czas, rozmiar, prefiks)."""
        kopie, _ = self._kopie(fid)
        for _src, ss in kopie:
            for p, ds in pliki:
                if _ten_sam_wezel(ss, ds):
                    return p, False
        blad = False
        for src, ss in kopie:
            for p, ds in pliki:
                try:
                    if _ten_sam_plik(src, p, ss, ds, copy=True):
                        return p, False
                except OSError:
                    blad = True
        return None, blad

    def werdykt(self, seg, rola, fid):
        """`jest` | `nie_ma` | `niepewny` - klatka `fid` w roli `rola` zestawu `seg` (opis klasy)."""
        if not self._zrodla.get(fid):
            return _NIEPEWNY
        pliki, blad_roli = self._pliki(seg, rola)
        plik, blad_tresci = self._plik_klatki(pliki, fid)
        if plik is not None:
            return _JEST
        kopie, blad_kopii = self._kopie(fid)
        if blad_roli or blad_tresci or blad_kopii or not kopie:
            return _NIEPEWNY
        nazwy = {os.path.basename(src).casefold() for src in self._zrodla[fid]}
        if any(os.path.basename(p).casefold() in nazwy for p, _ in pliki):
            return _NIEPEWNY
        return _NIE_MA

    def nazwy(self, seg, ids):
        """`{nazwa pliku: frame_id}` plików `LIGHT` zestawu (nazwa dwóch klatek → `None`, reguła
        `_merge_names`) albo `None`, gdy mapowanie NIE jest pełne: plik bez klatki spośród `ids`,
        klatka `ids` bez pliku, odczyt niepełny. Nazwy z DRZEWA: pod nimi WBPP dostał lighty."""
        pliki, blad = self._pliki(seg, "LIGHT")
        if blad:
            return None
        po_wezle = {}
        for fid in ids:
            for _src, ss in self._kopie(fid)[0]:
                if ss.st_ino:
                    po_wezle.setdefault((ss.st_dev, ss.st_ino), fid)
        out, pokryte = {}, set()
        for p, ds in pliki:
            fid = po_wezle.get((ds.st_dev, ds.st_ino)) if ds.st_ino else None
            if fid is None:
                fid = next((f for f in ids if self._plik_klatki([(p, ds)], f) == (p, False)), None)
            if fid is None:
                return None
            nazwa = os.path.basename(p)
            out[nazwa] = fid if out.get(nazwa, fid) == fid else None
            pokryte.add(fid)
        return out if pokryte >= set(ids) else None


def _listy_bez_utraty(seg, nowy, stary, swiadek):
    """Listy id zestawu (`lights`, `flat_raw`, `masters`) = lista wpisu `nowy` ∪ id wpisu `stary`
    spoza niej, którym świadek drzewa nie dowodzi nieobecności. Dowodnie nieobecne (`nie_ma`) schodzą;
    niepewne ZOSTAJĄ - zachowanie niczego nie zmyśla, a wydanie nie pada na historii. JEDNA polityka
    wydania i naprawy manifestu (AR-240): naprawa pisze to, co napisałoby wydanie. Zwraca `(listy,
    zachowane z dowodem, zdjęte, niepewne zachowane)` - niepewne osobno, bo okno naprawy mówi ich liczbę."""
    listy, kept, dropped, niepewne = {}, 0, 0, []

    def _dolacz(cel, fid, rola):
        nonlocal kept, dropped
        werdykt = swiadek.werdykt(seg, rola, fid)
        if werdykt == _NIE_MA:
            dropped += 1
            return
        cel.add(fid)
        if werdykt == _JEST:
            kept += 1
        else:
            niepewne.append(fid)
    for pole, rola in _ROLE_LIST:
        cel = set(_ids(nowy.get(pole)))
        for fid in sorted(set(_ids(stary.get(pole))) - cel):
            _dolacz(cel, fid, rola)
        listy[pole] = sorted(cel)
    mastery = {rel: set(_ids(ids)) for rel, ids in (nowy.get("masters") or {}).items()}
    stare = stary.get("masters")
    for rel, ids in (sorted(stare.items()) if isinstance(stare, dict) else ()):
        cel = mastery.setdefault(rel, set())
        for fid in sorted(set(_ids(ids)) - cel):
            _dolacz(cel, fid, _ROLA_MASTEROW)
    listy["masters"] = {rel: sorted(ids) for rel, ids in sorted(mastery.items()) if ids}
    return listy, kept, dropped, niepewne


@dataclasses.dataclass(frozen=True)
class ManifestRepair:
    """Wynik `repair_manifest`: `current` (manifest już opisuje komplet - nic do zapisu) ·
    `would-write` (sonda: zapis wolny, `payload` gotowy) · `written` · `refused` (odmowa z kodem,
    `powod`; bajty manifestu i drzewa nietknięte) · `error` (błąd systemu - `proj_manifest_failed`,
    `proj_manifest_unreadable`) · `cancelled` (diagnoza przerwana na żądanie wołającego).
    `stan` - z czym rozjechał się manifest: `missing` (nie było go) albo `stale` (nie opisywał
    kompletu); `kept` / `dropped` - id wcześniejszych wydań zachowane z dowodem w drzewie i zdjęte
    (pliku nie ma). `roznice` - czym zapis różni się od starego manifestu (`_roznice`: `sets`, `ids`,
    `names`, `cancelled`, `ts`; pusto przy `missing`); `obce_foldery` - foldery w korzeniu, których
    manifest nie opisze (ani w planie, ani w starym zeznaniu; bez `out`), `None` - korzenia nie odczytano.
    Polityka wydania (AR-240) - liczby dla okna zamiast odmowy: `bez_kopii` - klatki planu bez obecnej
    kopii (manifest wymienia je jak wydanie, ich plików w drzewie nie ma), `niepewne` - id wcześniejszych
    wydań bez dowodu w żadną stronę (zostają), `dodane` - pary (zestaw, lista, id), których stary
    manifest nie miał (0 przy `missing`)."""
    status: str
    powod: object = None
    stan: str | None = None
    payload: dict | None = None
    kept: int = 0
    dropped: int = 0
    roznice: tuple = ()
    obce_foldery: tuple | None = ()
    bez_kopii: int = 0
    niepewne: int = 0
    dodane: int = 0


def _klucz_sciezki(sciezka):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(sciezka))))


def _lista_id(wartosc):
    return isinstance(wartosc, list) and all(
        isinstance(v, int) and not isinstance(v, bool) for v in wartosc)


def _zly_ksztalt(m):
    """Nazwa pierwszego pola manifestu wydania obiektu o złym kształcie albo None - pola, które
    czytają scalenie i żniwa (nagłówek, zestawy, listy id, mastery, nazwy, `ts`). Klucz listy albo
    słownika może nie istnieć (manifest sprzed tego pola), ale obecny musi mieć swój typ - jawne
    `null` to uszkodzenie, nie brak (AR-213). `null` wolno wyłącznie w `ts` (wydanie bez daty)."""
    if not isinstance(m, dict):
        return "manifest"
    for pole in ("layout", "root", "object_canon"):
        if not isinstance(m.get(pole), str):
            return pole
    if not isinstance(m.get("object_id"), int) or isinstance(m.get("object_id"), bool):
        return "object_id"
    if m.get("ts") is not None and not isinstance(m["ts"], str):
        return "ts"
    if "segments" in m and not isinstance(m["segments"], list):
        return "segments"
    zestawy = m.get("zestawy")
    if not isinstance(zestawy, dict):
        return "zestawy"
    for seg, z in zestawy.items():
        if not isinstance(z, dict):
            return f"zestawy.{seg}"
        for pole, _rola in _ROLE_LIST:
            if pole in z and not _lista_id(z[pole]):
                return f"zestawy.{seg}.{pole}"
        mastery = z.get("masters")
        if "masters" in z and not (isinstance(mastery, dict) and all(
                isinstance(rel, str) and _lista_id(ids) for rel, ids in mastery.items())):
            return f"zestawy.{seg}.masters"
        nazwy = z.get("names")
        if "names" in z and not (isinstance(nazwy, dict) and all(
                isinstance(n, str) and (f is None or (isinstance(f, int) and not isinstance(f, bool)))
                for n, f in nazwy.items())):
            return f"zestawy.{seg}.names"
        if z.get("ts") is not None and not isinstance(z["ts"], str):
            return f"zestawy.{seg}.ts"
    return None


def _obce_pole(stary, manifest, root):
    """Pole, w którym poprawny manifest zeznaje SPRZECZNIE z tym wydaniem (inny układ, obiekt,
    kanon, korzeń, kształt drzewa) albo None. Brak `segments` (manifest sprzed tego pola) to nie
    rozjazd - jak `manifest_drift`."""
    if stary["layout"] != OBJECT_LAYOUT:
        return "layout"
    if stary["object_id"] != manifest.get("object_id"):
        return "object_id"
    if stary["object_canon"] != manifest.get("object_canon"):
        return "object_canon"
    if _klucz_sciezki(stary["root"]) != _klucz_sciezki(root):
        return "root"
    if stary.get("segments") and (_shape(OBJECT_LAYOUT, stary["segments"])
                                  != _shape(OBJECT_LAYOUT, OBJECT_SEGMENTS)):
        return "segments"
    return None


def _odmowa_obcego(pole):
    """Odmowa nad manifestem, który zeznaje o INNYM wydaniu (`proj_manifest_foreign`, sprzeczne pole
    w `detail`) - jedno zdanie dla naprawy (`_obce_pole`) i kroku manifestu wydania (`_odmowa_starego`).
    Fakt i rada wspólna; gest ponowienia dokłada powierzchnia (AR-251)."""
    return PowodPozycji(
        f"manifest wydania ({MANIFEST_NAME}) w folderze należy do innego wydania (sprzeczne pole: "
        f"{pole}) - nie nadpisuję go; sprawdź go albo usuń ręcznie", "proj_manifest_foreign", detail=pole)


def _odmowa_starego(stary, path, *, layout, object_id=None):
    """Odmowa zastąpienia starego manifestu `stary` (przeczytanego, JSON) zapisem manifestu układu
    `layout` (wydania obiektu `object_id`) albo None, gdy zastąpienie wolno - JEDEN walidator dla
    kroku manifestu wydania (`_write_manifest`, każdy układ) i naprawy (`_odczyt_scisly`), AR-234.
    Nie-słownik albo nagłówek bez napisu `layout` - uszkodzony (`proj_manifest_damaged`). Zeznanie
    wydania obiektu: zła struktura (`_zly_ksztalt` - nagłówek, zestawy, listy id, nazwy) - uszkodzony;
    zastępowane manifestem INNEGO układu albo wydania INNEGO obiektu - obce (`proj_manifest_foreign`,
    pole `layout` / `object_id`). Tolerancyjne scalenie wydania pomijało takie zeznanie, a publikacja je
    nadpisywała; folder obiektu nie należy do żadnego innego wydania (`object_root`, `_object_segment`
    rozstrzyga kolizje nazw), więc legalnej drogi takiego nadpisu nie ma. Stary manifest układu
    kolumnowego zastępuje się jak dotąd (strażnik `manifest_drift` ostrzega o rozjeździe)."""
    if not isinstance(stary, dict) or not isinstance(stary.get("layout"), str):
        return _odmowa_uszkodzonego("manifest" if not isinstance(stary, dict) else "layout", path)
    if stary["layout"] != OBJECT_LAYOUT:
        return None
    pole = _zly_ksztalt(stary)
    if pole is not None:
        return _odmowa_uszkodzonego(pole, path)
    if layout != OBJECT_LAYOUT:
        return _odmowa_obcego("layout")
    if object_id is not None and stary["object_id"] != object_id:
        return _odmowa_obcego("object_id")
    return None


def _podpis(path):
    """Podpis świadka CAS - `(bajty, st_size, st_mtime_ns)` pliku albo None (nie ma go, nieczytelny) -
    ten sam kształt, który zapamiętuje `_odczyt_scisly` przy pierwszym odczycie."""
    try:
        st = os.stat(path)
        with open(path, "rb") as fh:
            dane = fh.read()
    except OSError:
        return None
    return dane, st.st_size, st.st_mtime_ns


def _odczyt_scisly(path):
    """Ścisły świadek naprawy → `(stary manifest albo None, podpis albo None, odmowa albo None)`.
    „Nie ma” WYŁĄCZNIE przy klasie `os_missing` (`powod_systemu` - WinError 2/3, ENOENT); zerwany
    udział (53/67 - `FileNotFoundError` w CPythonie, AR-211) i odmowa dostępu to błąd, nie brak.
    Błąd systemu odczytu - `error` z `proj_manifest_unreadable` (odczyt, nie zapis). Bajty spoza
    UTF-8 albo JSON nieczytelny - odmowa `proj_manifest_damaged`; dalej walidator wspólny z krokiem
    manifestu wydania (`_odmowa_starego`: zła struktura - `proj_manifest_damaged`, zeznanie innego
    układu - `proj_manifest_foreign`); plik nietknięty. Tolerancyjny `read_manifest` zostaje dla żniw
    i strażnika rozjazdu - naprawa nie może brać „nie wiem” za „nie ma”."""
    try:
        st = os.stat(path)
    except OSError as exc:
        klasa = powod_systemu(exc)
        if klasa is not None and klasa.code == "os_missing":
            return None, None, None
        return None, None, ManifestRepair("error", _powod_odczytu(blad_systemu(exc)))
    try:
        with open(path, "rb") as fh:
            dane = fh.read()
    except OSError as exc:
        return None, None, ManifestRepair("error", _powod_odczytu(blad_systemu(exc)))
    podpis = (dane, st.st_size, st.st_mtime_ns)
    try:
        stary = json.loads(dane.decode("utf-8"))
    except UnicodeDecodeError:
        return None, None, ManifestRepair("refused", _odmowa_uszkodzonego("UTF-8", path))
    except ValueError:
        return None, None, ManifestRepair("refused", _odmowa_uszkodzonego("JSON", path))
    odmowa = _odmowa_starego(stary, path, layout=OBJECT_LAYOUT)
    if odmowa is not None:
        return None, None, ManifestRepair("refused", odmowa)
    return stary, podpis, None


def _odmowa_uszkodzonego(detail, path):
    """Odmowa nad manifestem uszkodzonym (`proj_manifest_damaged`) - jedno zdanie dla naprawy
    (`_odczyt_scisly`), kroku manifestu wydania (`_write_manifest`, AR-234) i żniw (`read_manifest`
    z `errors_out`). `detail` - pole albo warstwa, która padła; `path` - ścieżka manifestu (szczegół
    okna, nie zdanie). Fakt i rada wspólna; gest ponowienia dokłada powierzchnia (AR-251)."""
    return PowodPozycji(
        f"manifest wydania ({MANIFEST_NAME}) leży w folderze, ale nie jest poprawnym zeznaniem "
        f"({detail}) - nie nadpisuję go; sprawdź go albo usuń ręcznie", "proj_manifest_damaged",
        detail=detail, path=path)


def _sonda_kompletu(projection, root, copy, sonda):
    """`(pozycje planu bez potwierdzonego celu, czy każdy cel to hardlink źródła)`. Cel pozycji =
    `<root>/<segmenty>/<basename>` będący TYM SAMYM plikiem co źródło (`_ten_sam_plik`). `sonda` -
    wynik DRY wołającego (statusy `exists`), wyłącznie przy samej diagnozie."""
    if sonda is not None:
        brak = sum(1 for r in sonda.results if r.status not in ("exists", "skipped"))
        return brak, not sonda.copy
    brak, hardlinki = 0, True
    for item in projection.items:
        dst = os.path.join(root, *item.segments, item.basename)
        try:
            ss, ds = os.stat(item.src), os.stat(dst)
            if not _ten_sam_plik(item.src, dst, ss, ds, copy=copy):
                brak += 1
                continue
        except OSError:
            brak += 1
            continue
        hardlinki = hardlinki and _ten_sam_wezel(ss, ds)
    return brak, hardlinki


def _listy_wpisu(z):
    """Listy id wpisu zestawu w postaci porównywalnej: posortowane listy ról i niepuste relacje
    masterów - jedna postać dla starego manifestu, planu i treści naprawy."""
    mastery = z.get("masters")
    return ([sorted(_ids(z.get(pole))) for pole, _rola in _ROLE_LIST],
            {rel: sorted(_ids(ids)) for rel, ids in sorted(mastery.items()) if _ids(ids)}
            if isinstance(mastery, dict) else {})


def _roznice(stary, payload):
    """Czym `payload` różni się od starego manifestu w tym, co czytają konsumenci (żniwa, scalenie,
    strażnik rozjazdu) - krotka tokenów w stałym porządku: `sets` (inne zestawy), `ids` (listy id
    albo mastery wspólnego zestawu), `names` (nazwy plików), `cancelled` (stary wpis anulowany),
    `ts` (czas nagłówka - z niego żniwa liczą datę wydania). Pusta = stary manifest mówi to samo
    (`current`); `stary=None` - pusta, stan mówi `missing`. Pola informacyjne się nie liczą."""
    if stary is None:
        return ()
    out = []
    wspolne = sorted(set(stary["zestawy"]) & set(payload["zestawy"]))
    if set(stary["zestawy"]) != set(payload["zestawy"]):
        out.append("sets")
    if any(_listy_wpisu(stary["zestawy"][s]) != _listy_wpisu(payload["zestawy"][s]) for s in wspolne):
        out.append("ids")
    if any(stary["zestawy"][s].get("names") != payload["zestawy"][s].get("names") for s in wspolne):
        out.append("names")
    if any(stary["zestawy"][s].get("cancelled") for s in wspolne):
        out.append("cancelled")
    if stary.get("ts") != payload.get("ts"):
        out.append("ts")
    return tuple(out)


def _pary_id(m):
    """Pary `(zestaw, lista, id)` list manifestu - `lights`, `flat_raw` i relacje masterów
    (`_listy_wpisu`) - do liczby id, które zapis naprawy DOPISZE do starego manifestu (AR-245)."""
    out = set()
    zestawy = m.get("zestawy") if isinstance(m, dict) else None
    for seg, z in (zestawy.items() if isinstance(zestawy, dict) else ()):
        if not isinstance(z, dict):
            continue
        role, mastery = _listy_wpisu(z)
        for (pole, _rola), ids in zip(_ROLE_LIST, role):
            out.update((seg, pole, fid) for fid in ids)
        for rel, ids in mastery.items():
            out.update((seg, f"masters.{rel}", fid) for fid in ids)
    return out


# Źródło daty nagłówka manifestu spoza wydania (`ts_source`, AR-240) - token dysku, nie zdanie. Brak
# klucza = `ts` z wydania albo z próby wydania w sesji okna.
TS_SOURCE_TREE = "tree"


def _czas_z_drzewa(root, seg):
    """Czas założenia folderu zestawu `<root>/<seg>` jako ISO UTC (format `now` okna) albo None -
    DOWÓD czasu wydania z drzewa dla naprawy bez czasu próby i bez starego `ts` (AR-240). `apply`
    zakłada folder zestawu przy jego PIERWSZYM wydaniu, chwilę po `now` (zmierzone na dwóch
    realnych wydaniach na udziale SMB: +0,09 s i +0,12 s), więc przy zestawie wydanym kilka razy to
    czas pierwszego wydania - nie późniejszy od prawdziwego. `mtime` folderów tego nie daje (drzewo
    ruszane po wydaniu). `st_birthtime` jest na Windows od Pythona 3.12; bez niego albo przy błędzie
    odczytu - None (naprawa zapisze wydanie bez daty, jak przed AR-240)."""
    try:
        urodzony = getattr(os.stat(os.path.join(root, seg)), "st_birthtime", None)
    except OSError:
        return None
    return datetime.fromtimestamp(urodzony, timezone.utc).isoformat() if urodzony else None


def _skrot_aktualny(stary, manifest, root, ts):
    """Tani dowód `current` BEZ świadka drzewa (diagnoza okna przy każdej sondzie): stary manifest
    wymienia dokładnie zestawy, listy id i nazwy planu, żaden wpis nie jest anulowany, czas próby
    (`ts`) nie jest nowszy, a w folderze `LIGHT` każdego zestawu leżą wyłącznie pliki o nazwach
    planu (sam listing, bez `stat`). Pełna droga dałaby wtedy ten sam werdykt: list nie ma czym
    poszerzyć, a nazwy z drzewa to nazwy planu. Komplet celu sprawdza wołający przed skrótem.
    Stary manifest BEZ daty (`ts: null`) skrótu nie dostaje: pełna droga szuka daty w drzewie
    (`_czas_z_drzewa`, AR-240), a znaleziona to różnica `ts`."""
    if stary is None or set(stary["zestawy"]) != set(manifest["zestawy"]):
        return False
    if not isinstance(stary.get("ts"), str):
        return False
    if ts is not None and stary.get("ts") != ts:
        return False
    for seg, z in manifest["zestawy"].items():
        s = stary["zestawy"][seg]
        if s.get("cancelled") or not isinstance(z.get("names"), dict) or s.get("names") != z["names"]:
            return False
        if _listy_wpisu(s) != _listy_wpisu(z):
            return False
        bledy, nazwy = [], []
        for _dp, _dn, fn in os.walk(os.path.join(root, seg, "LIGHT"), onerror=bledy.append):
            nazwy.extend(fn)
        if bledy or sorted(nazwy) != sorted(z["names"]):
            return False
    return True


def _tresc_naprawy(projection, root, stary, manifest, swiadek, *, ts, now, hardlinki):
    """Treść naprawionego manifestu → `(payload, zachowane, zdjęte, niepewne)`. Nagłówek jak
    w `_write_manifest`, treść = głęboka kopia `manifest` wołającego (`object_manifest` + etykieta
    okna - jedno źródło z wydaniem), zestawy scalone bez utraty (`_listy_bez_utraty`), a klucze
    starego manifestu spoza tego zbioru przeniesione (etykieta starego wydania, gdy wołający nie
    podał swojej). Zestaw spoza planu (`_stan_folderu`): folder stoi - scalany jak zestaw planu;
    dowodnie go nie ma - wpis schodzi, jego id liczą się do zdjętych; stanu nie da się odczytać -
    wpis zostaje bez zmian, a jego id liczą się do niepewnych (zostają - polityka wydania, AR-240).

    `ts` nagłówka: czas nieudanej próby wołającego (`ts`), inaczej `ts` starego manifestu (z jego
    `ts_source`), inaczej DOWÓD Z DRZEWA (AR-240, `_czas_z_drzewa`): najpóźniejszy czas założenia
    folderu zestawu planu, z `ts_source: "tree"` - to czas PIERWSZEGO wydania zestawu, więc nigdy nie
    mówi fałszywie „czeka na WBPP”; bez dowodu `None` - data wydania bez dowodu nie istnieje (żniwa:
    wydanie bez daty, bez „czeka na WBPP”). `repaired_at` (chwila naprawy) przy dacie z drzewa i bez daty.
    `ts` wpisu zestawu - ze starego wpisu, a dla zestawu bez starego zeznania - czas założenia JEGO
    folderu (data z drzewa) albo nagłówka. `names` zestawu z drzewa (`_SwiadekDrzewa.nazwy`)
    WYŁĄCZNIE przy pełnym mapowaniu `lights` zestawu BEZ klatek planu bez kopii (jak wydanie,
    `_merge_object_manifest` - ich plików w drzewie nie ma), scalone ze starymi; inaczej reguła
    wydania (`_nazwy_scalone`): nazwy planu scalone ze starymi, a bez starych przy lightach spoza planu -
    brak (częściowe `names` wyłączyłoby żniwom spadek na bazę). `cancelled` schodzi - drzewo to komplet.
    `copy` - z drzewa (każdy cel to hardlink źródła → `false`)."""
    pominiete = {fid for fid, _why in projection.skipped}
    czas_zestawu = {}
    if ts is not None:
        ts_naglowka, zrodlo = ts, None
    elif stary is not None and isinstance(stary.get("ts"), str):
        ts_naglowka, zrodlo = stary["ts"], stary.get("ts_source")
    else:
        czas_zestawu = {seg: _czas_z_drzewa(root, seg) for seg in manifest["zestawy"]}
        znane = [c for c in czas_zestawu.values() if c is not None]
        ts_naglowka, zrodlo = (max(znane), TS_SOURCE_TREE) if znane else (None, None)
    payload = {
        "layout": OBJECT_LAYOUT,
        "segments": [list(s) if isinstance(s, tuple) else [s] for s in OBJECT_SEGMENTS],
        "root": root,
        "copy": not hardlinki,
        "ts": ts_naglowka,
        "n_items": len(projection.items),
        "counts": {"exists": len(projection.items)},
    }
    payload.update(_copy.deepcopy(manifest))
    for klucz, wartosc in (stary or {}).items():
        payload.setdefault(klucz, wartosc)
    if ts_naglowka is None or zrodlo == TS_SOURCE_TREE:
        payload["repaired_at"] = now
    else:
        payload.pop("repaired_at", None)
    if zrodlo is None:
        payload.pop("ts_source", None)
    else:
        payload["ts_source"] = zrodlo
    nowe, stare = manifest["zestawy"], (stary or {}).get("zestawy") or {}
    zestawy, kept, dropped, niepewne = {}, 0, 0, []
    for seg in sorted(set(nowe) | set(stare)):
        zn, zs = nowe.get(seg), stare.get(seg)
        if zn is None:
            stan = _stan_folderu(os.path.join(root, seg))
            if stan == _NIE_MA:
                dropped += len(_id_wpisu(zs))
                continue
            if stan == _NIEPEWNY:
                niepewne += _id_wpisu(zs)
                zestawy[seg] = _copy.deepcopy(zs)        # zeznanie bez zmian - nic nie ginie
                continue
        listy, k, d, n = _listy_bez_utraty(seg, zn or {}, zs or {}, swiadek)
        kept, dropped, niepewne = kept + k, dropped + d, niepewne + n
        wpis = {**(zs or {}), **_copy.deepcopy(zn or {}), **listy}
        wpis.pop("cancelled", None)
        wpis["ts"] = (zs["ts"] if zs is not None and isinstance(zs.get("ts"), str)
                      else czas_zestawu.get(seg) or ts_naglowka)
        z_drzewa = swiadek.nazwy(seg, sorted(set(wpis["lights"]) - pominiete))
        stare_nazwy = zs.get("names") if zs is not None and isinstance(zs.get("names"), dict) else None
        if z_drzewa is not None:
            wpis["names"] = _merge_names(stare_nazwy, z_drzewa) if stare_nazwy else z_drzewa
        else:
            # Mapa z drzewa niepełna (niepewny stary light, plik spoza klatek): reguła wydania - nazwy
            # planu (jego pliki leżą, sprawdza to sonda kompletu) scalone ze starymi.
            nazwy = _nazwy_scalone((zn or {}).get("names"), stare_nazwy,
                                   bool(set(wpis["lights"]) - set(_ids((zn or {}).get("lights")))),
                                   lambda: None)
            if nazwy is None:
                wpis.pop("names", None)
            else:
                wpis["names"] = nazwy
        zestawy[seg] = wpis
    payload["zestawy"] = zestawy
    return payload, kept, dropped, niepewne


def _obce_foldery(root, payload):
    """Foldery w korzeniu wydania, których zapis nie opisze (ani zestaw planu, ani zestaw starego
    zeznania; bez wyjścia WBPP `out`) - krotka nazw albo `None`, gdy korzenia nie odczytano. Sam
    listing; okno mówi z niego, że manifest opisze tylko zestawy planu."""
    try:
        with os.scandir(root) as it:
            foldery = sorted(e.name for e in it if e.is_dir())
    except OSError:
        return None
    return tuple(f for f in foldery if f not in payload["zestawy"] and f != OUTPUT_DIR)


def _werdykt_naprawy(con, projection, root, path, *, copy, now, manifest, ts, sonda, should_cancel,
                     part_cudzy):
    """Diagnoza `repair_manifest` bez publikacji → `(ManifestRepair, podpis starego manifestu)`.
    `part_cudzy` - ścieżka `.part`, której obecność przy werdykcie zapisu znaczy `busy` (sama
    diagnoza; zapis trzyma własny `.part` i podaje `None`). `should_cancel` - prawda → `_Przerwano`."""
    def _stop():
        if should_cancel is not None and should_cancel():
            raise _Przerwano
    stary, podpis, odmowa = _odczyt_scisly(path)
    if odmowa is not None:
        return odmowa, None
    pole = _obce_pole(stary, manifest, root) if stary is not None else None
    if pole is not None:
        return ManifestRepair("refused", _odmowa_obcego(pole)), None
    _stop()
    n, hardlinki = _sonda_kompletu(projection, root, copy, sonda)
    if n:
        return ManifestRepair("refused", PowodPozycji(
            f"drzewo wydania nie jest kompletne - pozycji planu bez pliku w celu: {n}; manifest zapisuje "
            f"się wyłącznie nad kompletem - najpierw wydaj brakujące pozycje", "proj_manifest_incomplete",
            n=n, dir=root)), None
    _stop()
    if _skrot_aktualny(stary, manifest, root, ts):
        return ManifestRepair("current"), podpis
    ids = _ids_manifestu(stary) | {it.frame_id for it in projection.items}
    swiadek = _SwiadekDrzewa(root, _obecne_kopie(con, ids), should_cancel)
    payload, kept, dropped, niepewne = _tresc_naprawy(projection, root, stary, manifest, swiadek,
                                                      ts=ts, now=now, hardlinki=hardlinki)
    roznice = _roznice(stary, payload)
    # Manifest, który JUŻ opisuje komplet, nie jest luką - także przy klatkach planu bez kopii i przy
    # id bez dowodu (zostają, jak w wydaniu). Nowszy czas próby (`ts`) albo data z drzewa nad manifestem
    # bez daty to różnica (`ts` w `roznice`) - żniwa liczą z nagłówka datę wydania.
    if stary is not None and not roznice:
        return ManifestRepair("current"), podpis
    if part_cudzy is not None and os.path.lexists(part_cudzy):
        return ManifestRepair("refused", _odmowa_zajetego(part_cudzy)), None
    # Polityka wydania (AR-240): klatki planu bez kopii i id bez dowodu nie są odmową - manifest
    # mówi o nich to, co napisałoby wydanie, a okno podaje ich liczby przed kliknięciem.
    return ManifestRepair("would-write", stan="missing" if stary is None else "stale", payload=payload,
                          kept=kept, dropped=dropped, roznice=roznice,
                          obce_foldery=_obce_foldery(root, payload),
                          bez_kopii=len({fid for fid, _why in projection.skipped}),
                          niepewne=len(niepewne),
                          dodane=len(_pary_id(payload) - _pary_id(stary)) if stary is not None else 0), podpis


def repair_manifest(con, projection, root, *, copy, now, manifest, ts=None, do_write=False,
                    sonda=None, should_cancel=None) -> ManifestRepair:
    """NAPRAWA MANIFESTU WYDANIA OBIEKTU (AR-213): zapis `_PROJEKCJA.json` nad drzewem, które JUŻ
    leży w celu - BEZ wejścia do `apply` (zero `makedirs`, zero `_link_to`, zero linków). Baza tylko
    do odczytu (`_obecne_kopie`); pisze wyłącznie manifest przez `.part`. `do_write=False` - sonda
    (`current` / `would-write` / odmowa / `cancelled`); `do_write=True` - wszystko od nowa
    i publikacja. `sonda` (wynik DRY wołającego) wolno podać wyłącznie bez zapisu - przy zapisie
    sonda kompletu jest świeża. `should_cancel` (diagnoza okna) - przerwanie między krokami i w
    świadku drzewa, wynik `cancelled`.

    Kolejność (każda odmowa zostawia bajty manifestu i drzewa nietknięte): świadek ścisły
    (`_odczyt_scisly`: uszkodzony - `proj_manifest_damaged`, nieczytelny - `error` z
    `proj_manifest_unreadable`); zeznanie obce (`_obce_pole` - `proj_manifest_foreign`); cel
    pozycji planu, który nie jest tym samym plikiem co źródło (`proj_manifest_incomplete`); tani
    skrót do `current` (`_skrot_aktualny` - bez świadka drzewa); treść (`_tresc_naprawy`) - gdy
    stary manifest mówi konsumentom to samo (`_roznice` puste, także `ts`), wynik `current`; w samej
    diagnozie cudzy `.part` (`proj_manifest_busy`). Id DOWODNIE nieobecne schodzą (`dropped`).

    NAPRAWA PISZE TO, CO WYDANIE (AR-240): klatki planu bez obecnej kopii (`object_manifest` wymienia
    je w listach) i id wcześniejszych wydań bez dowodu w żadną stronę ZOSTAJĄ, jak w scaleniu wydania
    (`_listy_bez_utraty`) - wynik niesie ich liczby (`bez_kopii`, `niepewne`), nie odmowę. Dawniej
    naprawa była ostrzejsza od wydania i obiekt z klatką bez kopii nie odzyskiwał manifestu z okna.
    Czas wydania bez próby z sesji i bez starego `ts` - z drzewa (`_tresc_naprawy`, `ts_source`).

    WYŁĄCZNOŚĆ `.part` - jeden protokół z krokiem manifestu wydania (`_write_manifest`): zapis
    zakłada `.part` trybem `x` PRZED odczytem starego manifestu i trzyma go do publikacji (leży
    cudzy - `proj_manifest_busy`, nietknięty); werdykt inny niż zapis zdejmuje własny `.part`.
    PUBLIKACJA Z CAS: `fsync`, tuż przed publikacją drugi odczyt świadka: manifest zmienił się od
    odczytu (podpis: bajty, rozmiar, `mtime_ns`) albo - przy braku - powstał w międzyczasie
    (`os.path.lexists`, potem `os.rename`, które na Windows rzuca `FileExistsError`, gdy cel już
    stoi) → `proj_manifest_changed`, `.part` zdjęty, wersja drugiego pisarza zostaje. Okno
    resztkowe między drugim odczytem a `os.replace` (Win32 nie ma atomowego porównaj-i-zamień poza
    `ReplaceFileW`) zostaje - mikrosekundy wobec sekund sondy; pisarz spoza protokołu `.part`
    (ręka, stara wersja) mieści się tylko w nim. Błąd systemu przy zapisie → `error`
    z `proj_manifest_failed`, `.part` zdjęty."""
    if do_write and sonda is not None:
        raise ValueError("repair_manifest: wynik DRY (`sonda`) wolno podać wyłącznie bez zapisu")
    _assert_excluded_segment(root)
    if projection.layout != OBJECT_LAYOUT or projection.info is None:
        raise ValueError(f"naprawa manifestu wymaga planu {OBJECT_LAYOUT!r} z info "
                         f"(jest {projection.layout!r})")
    path = os.path.join(root, MANIFEST_NAME)
    part = path + PART_SUFFIX
    argumenty = dict(copy=copy, now=now, manifest=manifest, ts=ts, sonda=sonda,
                     should_cancel=should_cancel)
    if not do_write:
        try:
            return _werdykt_naprawy(con, projection, root, path, part_cudzy=part, **argumenty)[0]
        except _Przerwano:
            return ManifestRepair("cancelled")
    try:
        fh = open(part, "x", encoding="utf-8")
    except FileExistsError:
        return ManifestRepair("refused", _odmowa_zajetego(part))
    except OSError as exc:
        return ManifestRepair("error", _powod_manifestu(blad_systemu(exc)))
    zmiana = PowodPozycji(
        f"manifest wydania ({MANIFEST_NAME}) zmienił się w trakcie zapisu - inny zapis był szybszy; "
        f"nic nie zapisano, odśwież podgląd", "proj_manifest_changed")
    try:
        with fh:
            wynik, podpis = _werdykt_naprawy(con, projection, root, path, part_cudzy=None, **argumenty)
            if wynik.status == "would-write":
                json.dump(wynik.payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
        if wynik.status != "would-write":
            _drop_part(part)
            return wynik
        if podpis is None:
            if os.path.lexists(path):
                _drop_part(part)
                return ManifestRepair("refused", zmiana)
            os.rename(part, path)
        else:
            if _podpis(path) != podpis:
                _drop_part(part)
                return ManifestRepair("refused", zmiana)
            os.replace(part, path)
    except _Przerwano:
        _drop_part(part)
        return ManifestRepair("cancelled")
    except FileExistsError:
        _drop_part(part)
        return ManifestRepair("refused", zmiana)
    except OSError as exc:
        _drop_part(part)
        return ManifestRepair("error", _powod_manifestu(blad_systemu(exc)))
    except BaseException:
        _drop_part(part)
        raise
    return dataclasses.replace(wynik, status="written")


# ============================================================ KOPIA MASTERA (żniwa, `horreum/harvest.py`)

_COPY_BUF = 1 << 20


def _assert_archive_library(dst, library_root):
    """Guard żniw: katalog celu MUSI leżeć pod `<library_root>\\CALIBRATION` albo
    `<library_root>\\STACKS` - segment BEZPOŚREDNIO pod korzeniem archiwum, bez wielkości liter. Żniwa
    piszą wyłącznie do bibliotek archiwum (mastery kalibracji, gotowe stosy), nigdy do drzewa lightów
    ani do warsztatu. Sam segment `CALIBRATION`/`STACKS` gdziekolwiek nie wystarcza:
    `…\\LIGHTS\\NGC7000\\stacks\\` to czyjś folder roboczy przy obiekcie (`scan._stacks_prefix` - to
    samo rozstrzygnięcie dla sita skanu). Obie ścieżki ZNORMALIZOWANE (`abspath` + `normpath`), jak
    w `_assert_excluded_segment`: `…\\STACKS\\..\\LIGHTS` ma segment w napisie, a system plików pisze do
    `LIGHTS`. Pusty `library_root` albo cel poza biblioteką → `ValueError` (EXPECT) przed czymkolwiek."""
    if not library_root:
        raise ValueError(f"kopia do archiwum bez korzenia archiwum (library_root={library_root!r})")

    def _segmenty(sciezka):
        return [p for p in re.split(r"[\\/]+", os.path.normpath(os.path.abspath(str(sciezka)))) if p]
    katalog = [p.lower() for p in _segmenty(dst)[:-1]]
    korzen = [p.lower() for p in _segmenty(library_root)]
    biblioteki = {CALIBRATION_SEGMENT.lower(), STACKS_DIR.lower()}
    if not (len(katalog) > len(korzen) and katalog[:len(korzen)] == korzen
            and katalog[len(korzen)] in biblioteki):
        raise ValueError(f"cel kopii {dst} leży poza biblioteką archiwum {library_root} "
                         f"({CALIBRATION_SEGMENT} albo {STACKS_DIR.upper()} bezpośrednio pod korzeniem)")


def _drop_part(part):
    """Zdejmij `.part`, który ta klinga sama przed chwilą utworzyła. Błąd zdjęcia nie przykrywa
    błędu, który do sprzątania doprowadził - wołający raportuje tamten."""
    try:
        os.remove(part)
    except OSError:
        pass


def copy_master(src, dst, *, expected_sha1, library_root, sha1_fn=hashing.sha1_of):
    """Skopiuj master albo stos z wyjścia WBPP pod `dst` w bibliotece archiwum (`<library_root>\\
    CALIBRATION` albo `<library_root>\\STACKS`), BEZ nadpisania. Zwraca `(status, reason | None)`:
    `placed` · `conflict` (cel albo `.part` już leży - plan nadał nazwę wolną, więc to wyścig z ręką)
    · `verify_bad` (bajty kopii ≠ `expected_sha1`) · `error` (I/O). `library_root` = korzeń archiwum
    planu żniw (`HarvestPlan.archive_root`), jedyna podstawa guardu `_assert_archive_library`.

    Droga: guard biblioteki → cel istnieje? → katalog celu (błąd, także rodzic będący plikiem → `error`)
    → kopia do `dst + ".part"` (otwarte `xb`: istniejący `.part` to `conflict`, cudzego pliku nie
    nadpisujemy ani nie usuwamy - wzorzec `raport._zapisz_plik`) → `flush` + `os.fsync` (jak bliźnie
    klingi `raport.py` i `writeback.py`: wyjście WBPP bywa jedyną kopią, a audyt czytający bufor
    systemu nie dowodzi bajtów na dysku) → sha1 CAŁEGO `.part` == `expected_sha1` → czasy źródła
    (wyłącznie czasy, `os.utime`: atrybut tylko-do-odczytu przeniesiony `copystat` blokowałby zdjęcie
    `.part` po przegranym wyścigu) → publikacja.

    `expected_sha1` to bajty, które zaakceptował plan (DRY), nie „bieżące źródło": plik w warsztacie
    mógł się zmienić między sondą a kopią, a scratch WBPP bywa jedyną kopią mastera. Master to
    pojedynczy plik ~100 MB, więc pełny audyt bajtów jest tani. Rozjazd → `.part` zdjęty, `dst`
    nietknięty.

    Publikacja przez `os.rename`, NIGDY `os.replace`: `replace` kasuje plik stojący pod celem
    (`writeback.py` dokumentuje to samo), a `os.rename` na Windows rzuca `FileExistsError`, gdy cel
    powstał między sprawdzeniem a publikacją - to drugi `conflict`, `.part` zdjęty. Poza Windows
    `rename` zastępuje cel; Horreum chodzi na Windows i tę semantykę zakłada. `.part` nie jest
    sufiksem nagłówkonośnym (`scan.HEADER_SUFFIXES`), więc przerwanie w połowie nie zostawia
    półproduktu, który skan wziąłby za mastera. `sha1_fn` to szew testu wyścigu.

    Powód to DANE, nie zdanie (ekran EN pokazuje go dosłownie, a co się stało, mówi status): ścieżka
    celu albo `.part`, `sha1 <kopia> != <plan>`. Przy `error` - błąd systemu klasą (`PowodPozycji`
    `os_*`, okno mówi go w języku UI, surowy tekst w `detail`) albo tekst systemu spoza klas
    (`item_reasons.blad_systemu`, AR-184)."""
    _assert_archive_library(dst, library_root)
    if os.path.lexists(dst):
        return "conflict", str(dst)
    part = dst + PART_SUFFIX
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    except OSError as exc:                     # także `FileExistsError`: rodzic celu jest plikiem
        return "error", blad_systemu(exc)
    try:
        fh = open(part, "xb")
    except FileExistsError:
        return "conflict", str(part)
    except OSError as exc:
        return "error", blad_systemu(exc)
    try:
        with fh, open(src, "rb") as zrodlo:
            shutil.copyfileobj(zrodlo, fh, _COPY_BUF)
            fh.flush()
            os.fsync(fh.fileno())
        got = sha1_fn(part)
        if got != expected_sha1:
            _drop_part(part)
            return "verify_bad", f"sha1 {got} != {expected_sha1}"
        st = os.stat(src)
        os.utime(part, ns=(st.st_atime_ns, st.st_mtime_ns))
        try:
            os.rename(part, dst)
        except FileExistsError:
            _drop_part(part)
            return "conflict", f"{dst} (rename: FileExistsError)"
    except OSError as exc:
        _drop_part(part)
        return "error", blad_systemu(exc)
    except BaseException:
        _drop_part(part)
        raise
    return "placed", None


def write_harvest_manifest(wbpp_dir, payload, *, now):
    """Zapisz zeznanie biegu żniw w katalogu wyjścia WBPP (PLIK, nie DB - jak `_PROJEKCJA.json` przy
    wydaniu): co wciągnięto, dokąd, z jakich wejść i dlaczego reszta została. Baza dowie się
    o masterze zwykłym skanem, a jego historia jedzie w jego nagłówku; proweniencja decyzji żniw
    zostaje przy wyjściu. Zwraca ścieżkę zapisanego pliku.

    KAŻDY BIEG WŁASNYM PLIKIEM `_ZNIWA_<YYYYMMDD-HHMMSS>.json` (znacznik z `now` wołającego), otwieranym
    `x`: drugi bieg nad tym samym wyjściem nie nadpisuje zeznania pierwszego, więc proweniencja
    masterów wciągniętych wcześniej zostaje. Dwa biegi w tej samej sekundzie → `_2`, `_3`… Zapis
    `open(..., 'x')` żyje w tej klindze (DOOR meta-testu)."""
    chwila = now if isinstance(now, datetime) else datetime.fromisoformat(str(now))
    stem = f"{HARVEST_MANIFEST_PREFIX}_{chwila.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while True:
        path = os.path.join(wbpp_dir, f"{stem}.json" if n == 1 else f"{stem}_{n}.json")
        try:
            fh = open(path, "x", encoding="utf-8")
        except FileExistsError:
            n += 1
            continue
        with fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return path


# ============================================================ WARIANT KADRU STOSU (`horreum/stack_variants.py`)

# Zeznanie pary wariant-oryginał leży OBOK kopii wariantu w `STACKS`: `_WARIANT_<nazwa kopii bez
# rozszerzenia>.json`. Plik, nie wiersz bazy: kopię robi ręka Zdzinia (`stack-versions --apply`),
# a bazę o niej informuje dopiero skan - konsument (`stack_variants.link_from_testimonies`) czyta
# zeznanie po wjeździe obu klatek, także po restarcie programu między kopią a Dostawą. JSON nie jest
# sufiksem nagłówkonośnym, więc skan go nie bierze.
VARIANT_TESTIMONY_PREFIX = "_WARIANT"
VARIANT_TESTIMONY_KIND = "horreum.stack_variant"


def variant_testimony_path(copy_path):
    """Ścieżka zeznania wariantu dla kopii `copy_path` (konwencja przy `VARIANT_TESTIMONY_PREFIX`)."""
    katalog, nazwa = os.path.split(str(copy_path))
    return os.path.join(katalog, f"{VARIANT_TESTIMONY_PREFIX}_{os.path.splitext(nazwa)[0]}.json")


def read_variant_testimony(path):
    """Zeznanie wariantu jako dict albo None (brak pliku, JSON nieczytelny, inny `kind`). Odczyt -
    pisze wyłącznie `write_variant_testimony`, czyta konsument relacji i ponowienie zapisu."""
    try:
        with open(path, encoding="utf-8") as fh:
            dane = json.load(fh)
    except (OSError, ValueError):
        return None
    return dane if isinstance(dane, dict) and dane.get("kind") == VARIANT_TESTIMONY_KIND else None


def _assert_stacks_library(dst, library_root):
    """Strażnik wariantu: cel MUSI leżeć pod `<library_root>\\STACKS` (`_assert_archive_library`
    dopuszcza też `CALIBRATION`, a wariant kadru jest gotowym obrazem, nie masterem kalibracji)."""
    _assert_archive_library(dst, library_root)
    korzen = os.path.normpath(os.path.abspath(str(library_root)))
    cel = os.path.normpath(os.path.abspath(str(dst)))
    if not cel.lower().startswith(os.path.join(korzen, STACKS_DIR).lower() + os.sep):
        raise ValueError(f"cel wariantu {dst} leży poza biblioteką stosów {korzen}")


def copy_stack_variant(src, dst, *, expected_sha1, library_root, sha1_fn=hashing.sha1_of):
    """Kopia autocropu do biblioteki `STACKS` - obok kopii oryginału (wariant pary) albo na miejsce
    kanoniczne bez pary (samodzielny, `stack_variants.apply_standalone`) - `(status, reason)`.

    Ta sama klinga no-clobber z audytem bajtów co kopia stosu żniw (`copy_master`: `.part`, `fsync`,
    sha1 całego pliku == `expected_sha1`, publikacja `os.rename`), ten sam strażnik segmentu
    biblioteki, zawężony do `STACKS`. Jedna różnica i to jest PONOWIENIE: cel, pod którym leżą już
    TE SAME bajty (sha1 całego pliku), to `exists` - przerwany bieg (kopia zrobiona, zeznanie nie)
    dokańcza się drugim `--apply`. Inne bajty pod celem → `conflict`, nic nie nadpisujemy.

    Statusy: `placed` · `exists` · `conflict` · `verify_bad` · `error` (`copy_master`). Źródło
    w starym drzewie zostaje nietknięte - kasacja starego drzewa to osobna decyzja (Custos/ręka)."""
    _assert_stacks_library(dst, library_root)
    if os.path.lexists(dst):
        if os.path.isfile(dst) and sha1_fn(dst) == expected_sha1:
            return "exists", None
        return "conflict", str(dst)
    return copy_master(src, dst, expected_sha1=expected_sha1, library_root=library_root,
                       sha1_fn=sha1_fn)


def write_variant_testimony(copy_path, payload, *, replace=None):
    """Zapisz zeznanie wariantu obok kopii `copy_path` - `(status, ścieżka)`:
    `written` (nowe zeznanie) · `replaced` (podmienione zeznanie `replace`) · `exists` (leży zeznanie
    tej samej pary z tym samym świadkiem - `pair_id`, `source`; ponowienie) · `conflict` (leży inne
    zeznanie, którego wołający nie kazał podmienić, albo
    zmieniło się od chwili, gdy je przeczytał) · `part_exists` (pod `.part` leży cudzy plik roboczy).

    `replace` = treść zeznania, które wołający przeczytał i POSTANOWIŁ podmienić (ten sam autocrop,
    mocniejszy świadek oryginału - polityka mieszka u wołającego, `stack_variants.apply`). Podmiana
    jest CAS-em: tuż przed publikacją plik jest czytany ponownie i musi równać się `replace`.

    Atomowo i bez nadpisywania cudzego: `.part` otwierany `x` (istniejący `.part` = czyjś bieg w toku
    albo jego resztka - `part_exists`, nic nie ruszamy), `fsync`, publikacja `os.rename` dla nowego
    zeznania (cel, który powstał w międzyczasie, to `conflict`) i `os.replace` WYŁĄCZNIE dla podmiany
    po CAS-ie. Przerwanie w połowie nie zostawia uciętego JSON-u pod nazwą zeznania."""
    path = variant_testimony_path(copy_path)
    if os.path.lexists(path):
        stare = read_variant_testimony(path)
        if stare is not None and all(stare.get(k) == payload.get(k) for k in ("pair_id", "source")):
            return "exists", path
        if replace is None or stare != replace:
            return "conflict", path
    part = path + PART_SUFFIX
    try:
        fh = open(part, "x", encoding="utf-8")
    except FileExistsError:
        return "part_exists", path
    try:
        with fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        if replace is not None and os.path.lexists(path):
            if read_variant_testimony(path) != replace:
                _drop_part(part)
                return "conflict", path
            os.replace(part, path)
            return "replaced", path
        os.rename(part, path)
    except FileExistsError:
        _drop_part(part)
        return "conflict", path
    except BaseException:
        _drop_part(part)
        raise
    return "written", path
