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

from . import lineage, naming
from .gui import queries
from .scan import EXCLUDED_DIR_NAMES

_UNSET = "_UNSET"                      # segment layoutu pusty/None — nie gubimy klatki po cichu (§1)
MANIFEST_NAME = "_PROJEKCJA.json"

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
    Plan bez `info` (perspektywa gridu) → `ValueError`: manifest obiektu z niczego byłby kłamstwem."""
    if projection.layout != OBJECT_LAYOUT or projection.info is None:
        raise ValueError(f"manifest obiektu wymaga planu {OBJECT_LAYOUT!r} z info "
                         f"(jest {projection.layout!r})")
    return _copy.deepcopy(projection.info)


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
    wzorzec `import_fitsmirror.ImportAbort` (cli.py łapie i raportuje)."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def _assert_excluded_segment(root):
    """Guard §0 CEL-POD-WYKLUCZENIEM: `root` MUSI mieć segment z `EXCLUDED_DIR_NAMES` (case-insensitive
    SET — NIE pojedynczy literał jak dawca). Hardlink = duplikat i-węzła, nieodróżnialny przez `os.walk`
    → dla hardlinków chroni WYŁĄCZNIE prune `dirnames` po nazwie. Brak segmentu → projekcja wróciłaby
    jako wejście skanu (sieroty). Split po OBU separatorach (`/`+`\\`) - przenośne (Windows/POSIX).

    Sprawdzamy ścieżkę ZNORMALIZOWANĄ (`abspath` + `normpath`), nie surowy tekst: `R:/ASTRO_/_WBPP/../LIGHTS`
    ma segment `_WBPP` w napisie, a system plików rozwiązuje `..` i pisze do `LIGHTS` - czyli do
    wejścia skanu. Wołający dalej używa `root` tak, jak go podał (Win32 rozwiązuje `..` tak samo),
    więc ścieżki w wyniku i manifeście się nie zmieniają."""
    parts = [p for p in re.split(r"[\\/]+", os.path.normpath(os.path.abspath(str(root)))) if p]
    if not any(p.lower() in EXCLUDED_DIR_NAMES for p in parts):
        names = " / ".join(sorted(n.upper() for n in EXCLUDED_DIR_NAMES))   # czytelne, wprost z setu (SPOT)
        raise ValueError(
            f"korzeń projekcji {root} nie zawiera segmentu wykluczonego ({names}) - "
            "projekcja poza wykluczeniem wróciłaby jako wejście skanu")


def _link_to(src, dst, *, do_apply, copy):
    """Status src→KONKRETNY dst, ZERO nadpisania (§0). Zwraca `(status, reason|None)`:
    `would-link` (DRY, cel wolny) · `linked` (utworzony) · `exists` (ten sam i-węzeł, idempotentnie
    pomiń) · `conflict` (cel z INNYM i-węzłem - NIE clobber) · `verify_bad` (po `os.link` inny i-węzeł
    = SMB kopia) · `error` (I/O, np. EXDEV cross-wolumen → rada `--copy`). Odczyty stanu celu
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
        return "error", f"{type(exc).__name__}: {exc}"


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
    status: str                       # would-link|linked|exists|conflict|verify_bad|error|skipped
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
    `_PROJEKCJA.json` obok korzenia (PLIK, nie DB). Pominięte z planu dochodzą jako `skipped`."""
    _assert_excluded_segment(root)
    # PRZED czymkolwiek: `_write_manifest` nadpisze zeznanie starego drzewa, więc po masie nie byłoby
    # już czego czytać. DRY sonduje ten sam fakt, bo to właśnie DRY ma ostrzec PRZED wydaniem.
    drift = manifest_drift(root, projection.layout)
    if do_apply:
        os.makedirs(root, exist_ok=True)           # korzeń istnieje dla linków I manifestu (KLINGA)

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
            if status == "verify_bad" or not _verify_content(item.src, dst):
                results.append(LinkResult(item.frame_id, item.src, dst, "verify_bad",
                                          reason or "sonda pierwszego linku: cel nie jest hardlinkiem (i-węzeł/treść)"))
                # Kwarantanna planu dochodzi TAKŻE do wyniku częściowego — inaczej raport abortu
                # zawsze głosi „pominięto: 0", choćby plan miał klatki bez obecnej kopii (R#6).
                partial_results = results + [LinkResult(fid, "", "", "skipped", why)
                                             for fid, why in projection.skipped]
                partial = ApplyResult(root, projection.layout, do_apply, copy, partial_results,
                                      cancelled, drift)
                raise ProjectionAbort(
                    "pierwszy link nie przeszedł sondy tożsamości (i-węzeł/rozmiar/treść) — "
                    "wolumen nie wspiera hardlinków? włącz tryb kopii", partial)

        results.append(LinkResult(item.frame_id, item.src, dst, status, reason))
        done += 1
        if progress is not None:
            progress(done, total, dst, status)

    for fid, reason in projection.skipped:         # kwarantanna z planu → wynik
        results.append(LinkResult(fid, "", "", "skipped", reason))

    result = ApplyResult(root, projection.layout, do_apply, copy, results, cancelled, drift)
    if do_apply:
        _write_manifest(root, result, now=now, manifest=manifest)
    return result


def _write_manifest(root, result: ApplyResult, *, now, manifest):
    """Zapisz `_PROJEKCJA.json` obok korzenia (PLIK, nie DB — projekcja efemeryczna, JEDNA-KLINGA
    nietknięta; brief §3). Snapshot: layout/korzeń/tryb/ts/liczności + `manifest` wołającego
    (perspektywa/filtr/wolumen). `open(...,'w')` żyje w tej klindze (DOOR meta-testu). Wydanie obiektu
    scala `zestawy` ze starym manifestem tego samego obiektu (`_merge_object_manifest`); układy
    kolumnowe piszą dokładnie to, co pisały."""
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
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


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
    zamierzało, nie co leży na dysku. Wpis bez tego klucza to wydanie domknięte."""
    stempel = {"ts": now, "cancelled": True} if cancelled else {"ts": now}
    zestawy = {seg: {**z, **stempel} for seg, z in manifest["zestawy"].items()}
    if (old and old.get("layout") == OBJECT_LAYOUT and old.get("object_id") == manifest.get("object_id")
            and isinstance(old.get("zestawy"), dict)):
        for seg, z in old["zestawy"].items():
            if seg not in zestawy and isinstance(z, dict) and os.path.isdir(os.path.join(root, seg)):
                zestawy[seg] = {**z, "ts": z.get("ts", old.get("ts"))}
    return {**manifest, "zestawy": dict(sorted(zestawy.items()))}
