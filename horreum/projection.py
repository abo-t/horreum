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
"""

from __future__ import annotations

import copy as _copy
import dataclasses
import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from . import hashing, lineage, naming
from .gui import queries
from .item_reasons import (   # błąd systemu klasą - jeden właściciel (AR-184); odmowy z kodem (AR-200)
    OdmowaZPowodem, PowodPozycji, blad_systemu)
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
    `skipped`. `projection_dialog.chosen_present` lustruje tę regułę dla decyzji wolumenowej."""
    out = {}
    for r in queries.present_locations(con, ids):
        if r["location_id"] is None:
            continue
        fid = int(r["frame_id"])
        path, n = out.get(fid, (r["path"], 0))
        out[fid] = (path, n + 1)
    return out


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
            if ds.st_ino == ss.st_ino:
                return "exists", None
            if not copy:
                return "conflict", "cel istnieje z innym i-węzłem (nie nadpisuję)"
            # Tanie warunki przed odczytem: czas porównuje się bez otwierania plików, a rozmiar
            # sprawdza `_same_content`, zanim przeczyta prefiks.
            if (abs(ss.st_mtime_ns - ds.st_mtime_ns) <= _MTIME_TOLERANCE_NS
                    and _same_content(src, dst, ss, ds)):
                return "exists", None
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


def read_manifest(root):
    """`_PROJEKCJA.json` z korzenia → dict albo None. TOLERANCYJNY z rozmysłem: manifest jest
    efemeryczny i user może go skasować w Eksploratorze razem z drzewem, więc brak pliku, uszkodzony
    JSON i brak uprawnień znaczą to samo — „nie wiem, co tu stało", nigdy wyjątek w środku sondy."""
    try:
        with open(os.path.join(root, MANIFEST_NAME), encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


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
    # `proj_out_failed`, `proj_verify_failed`, `proj_manifest_failed` - klasa systemu w `inner`) albo
    # werdykt sondy pierwszego linku (`proj_first_link`, wynik częściowy `ProjectionAbort`). `None` =
    # wydanie doszło do końca; manifest leży wtedy i tylko wtedy, gdy `do_apply` i `error is None`.
    error: object = None

    @property
    def counts(self) -> dict:
        c: dict = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c


def apply(projection, root, *, do_apply, copy=False, now=None, manifest=None,
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
    `project` śladem stosu."""
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
            _write_manifest(root, result, now=now, manifest=manifest)
        except OSError as exc:
            inner = blad_systemu(exc)
            # Zdanie mówi, CZEGO brakuje i PO CO: z manifestu żniwa rozpoznają obiekt wydania
            # (`harvest`, okno żniw), a strażnik rozjazdu układu (`manifest_drift`) czyta z niego
            # kształt drzewa - pliki leżą, więc „odśwież i ponów” niczego by nie dopisało. Zapis
            # atomowy zostawia manifest POPRZEDNIEGO wydania, gdy był - zdanie nie obiecuje więc ani
            # braku rozpoznania, ani braku ostrzeżenia, tylko to, że manifest tych plików nie opisuje.
            return dataclasses.replace(result, error=PowodPozycji(
                f"nie zapisano manifestu wydania ({MANIFEST_NAME}) - pliki tego wydania leżą w celu, "
                f"ale manifest ich nie opisuje (brak go albo został poprzedni), więc rozpoznanie "
                f"obiektu przy wciąganiu wyników WBPP i kontrola układu drzewa przy następnym "
                f"wydaniu mogą być niepełne: {inner}",
                "proj_manifest_failed", inner=inner))
    return result


def _z_kwarantanna(results, projection):
    """Pozycje wydania + kwarantanna planu (`skipped`) - JEDNA reguła dla wyniku pełnego i każdego
    przerwanego (abort sondy, krok z błędem systemu): bez niej raport przerwanego wydania głosił
    „pominięto: 0”, choćby plan miał klatki bez obecnej kopii (R#6)."""
    return results + [LinkResult(fid, "", "", "skipped", why) for fid, why in projection.skipped]


def _write_manifest(root, result: ApplyResult, *, now, manifest):
    """Zapisz `_PROJEKCJA.json` obok korzenia (PLIK, nie DB — projekcja efemeryczna, JEDNA-KLINGA
    nietknięta; brief §3). Snapshot: layout/korzeń/tryb/ts/liczności + `manifest` wołającego
    (perspektywa/filtr/wolumen). `open(...,'w')` żyje w tej klindze (DOOR meta-testu). Wydanie obiektu
    scala `zestawy` ze starym manifestem tego samego obiektu (`_merge_object_manifest`); układy
    kolumnowe piszą dokładnie to, co pisały.

    Publikacja ATOMOWA (AR-197): treść idzie do `.part` obok, `fsync`, potem `os.replace` na manifest.
    Dawny `open(manifest, "w")` ucinał plik przy awarii w połowie zapisu i niszczył zeznanie
    poprzedniego wydania, z którego żniwa rozpoznają pliki. `.part` to plik tej klingi (resztka po
    przerwanym biegu jest nadpisywana); przy błędzie jest zdejmowany, a błąd idzie do wołającego."""
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
    if manifest:
        if result.layout == OBJECT_LAYOUT and "zestawy" in manifest:
            manifest = _merge_object_manifest(read_manifest(root), manifest, now=now, root=root,
                                              cancelled=result.cancelled)
        payload.update(manifest)
    path = os.path.join(root, MANIFEST_NAME)
    part = path + PART_SUFFIX
    try:
        with open(part, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(part, path)
    except BaseException:
        _drop_part(part)
        raise


def _merge_object_manifest(old, manifest, *, now, root, cancelled):
    """Proweniencja zestawów przeżywa wydanie INNEGO zestawu tego samego obiektu: drzewo zestawu
    wydanego wczoraj dalej leży w korzeniu obiektu, więc manifest, który by go zapomniał, kłamałby
    żniwom o tym, skąd te linki są. Wpisy bieżącego wydania dostają `ts` tej chwili; wpisy starego
    manifestu, których bieżące wydanie nie dotyka, zostają ze SWOIM `ts` (zapisanym przy nich albo -
    gdy go nie było - z nagłówka starego manifestu). Inny układ albo inny obiekt w tym korzeniu =
    nadpisanie jak dla każdego układu: obce zeznanie nie należy do tego drzewa. `old` z
    `read_manifest` (tolerancyjnego) - brak, uszkodzony albo obcy plik to po prostu brak scalenia.

    Stary wpis zostaje TYLKO, gdy jego folder zestawu dalej stoi w korzeniu (`os.path.isdir` - sam
    odczyt): user kasuje wydanie w Eksploratorze, a manifest, który pamiętałby skasowane drzewo,
    zeznawałby o linkach, których nie ma. Wydanie ANULOWANE (`cancelled`) zostawia w drzewie tylko
    część pozycji, więc jego wpisy dostają `"cancelled": true` - listy id mówią wtedy, co wydanie
    zamierzało, nie co leży na dysku. Wpis bez tego klucza to wydanie domknięte.

    NAZWY ZESTAWU WYDANEGO PONOWNIE SIĘ SUMUJĄ (`_merge_names`), reszta jego wpisu idzie z bieżącego
    wydania: pliki poprzedniego wydania zostają w folderze zestawu (klinga nie kasuje), więc WBPP je
    dostanie, a żniwa muszą je dalej rozpoznać po nazwie. Wpis anulowany po którejkolwiek stronie też
    wnosi swoje nazwy - część jego plików leży na dysku, a nazwa pliku, którego nie ma, niczego
    w historii WBPP nie dopasuje."""
    stempel = {"ts": now, "cancelled": True} if cancelled else {"ts": now}
    zestawy = {seg: {**z, **stempel} for seg, z in manifest["zestawy"].items()}
    if (old and old.get("layout") == OBJECT_LAYOUT and old.get("object_id") == manifest.get("object_id")
            and isinstance(old.get("zestawy"), dict)):
        for seg, z in old["zestawy"].items():
            if not isinstance(z, dict):
                continue
            if seg not in zestawy:
                if os.path.isdir(os.path.join(root, seg)):
                    zestawy[seg] = {**z, "ts": z.get("ts", old.get("ts"))}
            elif isinstance(z.get("names"), dict) and isinstance(zestawy[seg].get("names"), dict):
                zestawy[seg]["names"] = _merge_names(z["names"], zestawy[seg]["names"])
    return {**manifest, "zestawy": dict(sorted(zestawy.items()))}


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
