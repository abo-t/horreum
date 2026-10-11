r"""Wariant kadru stosu (AR-54) - autocrop jako WERSJA mastera: plan, kopia do `STACKS`, relacja.

Decyzja Zdzinia (2026-10-11): autocropy trafiają do magazynu (`STACKS`) i do bazy
jako wersja mastera - para autocrop i oryginał. Autocrop to OSOBNA klatka (przycięty kadr = inne
dane, inne `sha1_data`) powiązana z oryginałem relacją `stack_variant` (0035). Przycięcie robi
PixInsight po integracji i często gubi przy tym `TELESCOP`/`OBJECT`, więc bez relacji wariant nie
ma zestawu ani obiektu; z relacją dziedziczy oba (`resolver` - obiekt ze źródłem `twin`, `grouper` -
zestaw), a para nie świeci w Porządkach jako „wersja stosu do skasowania” (`gui.queries`).

TRZY KROKI, TRZY WŁAŚCICIELE MUTACJI (DOORS, SILNIK-NIETKNIĘTY):

1. `plan` - CZYSTY odczyt (baza + nagłówki plików), wynik = payload pozycji. Zero zapisu.
2. `apply` - sterownik kopii: bajty i zeznanie pary zapisuje `projection` (`copy_stack_variant`,
   `write_variant_testimony`), odcisk zeznania do kolejki bazy - `repo.record_variant_testimony`;
   ten moduł nie otwiera pliku do zapisu i nie zakłada katalogu. Uruchamia go ręka Zdzinia
   (`horreum stack-versions --apply`) - zapis na `R:` nie jest automatem. Przed kopią sprawdza
   ponownie stan oryginału z planu (aktywny, ta sama tożsamość, obecna kopia w `STACKS`).
3. `link_from_testimonies` - konsument kolejki zeznań (woła go `grouper.run_grouper`, pierwszy
   etap pochodnych Dostawy): relację zapisuje WYŁĄCZNIE `repo.link_stack_variant`, z zeznania, nie
   z ponownego zgadywania. Udziału nie czyta - kolejkę wypełnia `apply` i skan (`note_testimony`:
   kopia wariantu wjechała z zeznaniem obok). Restart programu między kopią a Dostawą niczego nie
   gubi: zeznanie leży w pliku i w bazie.

ORYGINAŁ (kolejność świadków, zmierzona na kopii archiwum 2026-10-11: 78 z 98 przez dawną lokację):
  (a) STARA LOKACJA - ta sama nazwa bez `_autocrop` w TYM SAMYM katalogu co autocrop była kiedyś
      lokacją klatki w bazie (Custos przeniósł oryginał do `STACKS`, przycięcie zostało w starym
      drzewie). Ślad pochodzenia: PixInsight zapisuje przycięcie obok pliku, który przycina;
  (b) OKNO `(DATE-OBS, DATE-END, FILTER)` wśród gotowych obrazów, z tym samym wariantem drizzle
      (`_drizzle`) - wyłącznie gdy (a) milczy i okno wskazuje DOKŁADNIE jedną klatkę. Zbieżność
      czasu, nie ślad pochodzenia, więc ranga niższa;
  (c) brak → pozycja „bez oryginału”, ZABLOKOWANA do decyzji ręki.
Bliźniak po `integ_hash` NIE jest świadkiem: hash liczy rodowód stosów z tych samych subów, więc
autocrop i oryginał mają go równy z konstrukcji - świadek byłby kołowy (`stacks.py`, `_plan`).

POZYCJA MODELUJE OSOBNO ORYGINAŁ I AUTOCROP (`OriginalSide`, `VariantSide`): każda strona ma
własne `src`, `dst` i status kopii, a pozycja - wspólny katalog docelowy (`target_dir`). Oryginał
z obecną kopią w `STACKS` stoi u celu (`present`), autocrop jedzie obok niego. Oryginał tylko poza
`STACKS` dostaje proponowany cel (`<obiekt>\<zestaw>\<filtr>` z osi bazy, nazwa `naming.stack_name`),
autocrop ten sam katalog - ale pozycja jest ZABLOKOWANA (`original_outside_stacks`) do decyzji ręki:
przeniesienie oryginału do biblioteki to inna operacja niż dołożenie wariantu. Nazwa autocropu =
nazwa archiwalna oryginału z członem `autocrop` (`naming.variant_stack_name` - powód tam). Pliki
z drugim znacznikiem pochodnej (`_autocrop_DBE`, `autocropSPCC`) są poza planem
(`scan.is_derived_name`) - to obróbka, nie wariant stosu.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re

from . import hashing, naming, projection, repo, scan
from .resolve.filters import normalize_filter
from .resolve.paths import STACKS_DIR
from .resolve.stack import read_testimony

AUTOCROP = "autocrop"
_AUTOCROP_TOKEN = re.compile(r"_autocrop(?=[._])", re.IGNORECASE)
_NOFILTER = "NoFilter"

#: Statusy pozycji, które `apply` wykonuje. Każdy inny status to blokada z powodem (`BLOCKED`).
APPLICABLE = ("ready", "dst_exists")
#: Powody blokady - pozycja czeka na rękę, `apply` jej nie dotyka.
BLOCKED = ("header_unreadable", "location_ambiguous", "window_ambiguous", "no_original",
           "original_absent", "original_outside_stacks", "original_many_seats",
           "original_name_conflict", "no_seat", "name_invalid", "name_taken")


@dataclasses.dataclass(frozen=True)
class OriginalSide:
    """Oryginał pary. `source` = świadek (`location` | `window`); `src` = kopia, z której oryginał
    jest znany (w `STACKS` albo poza); `dst` = jego miejsce w `STACKS` (dla `present` równe `src`,
    dla `to_copy` - cel proponowany, None, gdy osi bazy brakuje); `status` = `present` | `to_copy`;
    `other_paths` = obecne kopie POZA `STACKS`; `matched_path` = dawna lokacja świadka (a)."""
    frame_id: int
    sha1_data: str
    source: str
    src: str | None = None
    dst: str | None = None
    status: str | None = None
    other_paths: tuple = ()
    matched_path: str | None = None

    @property
    def stacks_path(self):
        """Obecna kopia oryginału w `STACKS` (siedziba pary) albo None."""
        return self.src if self.status == "present" else None


@dataclasses.dataclass(frozen=True)
class VariantSide:
    """Autocrop pary: plik źródłowy w starym drzewie, cel w `STACKS` (None, gdy celu nie da się
    wskazać) i status kopii (`to_copy` | `dst_exists` | None)."""
    src: str
    size: int | None = None
    dst: str | None = None
    status: str | None = None


@dataclasses.dataclass(frozen=True)
class VariantItem:
    """Pozycja planu. `target_dir` = wspólny katalog docelowy pary; `window_frame_ids` = kandydaci
    okna (zawsze liczeni - porównanie świadków), `window_agrees` = okno wskazuje ten sam katalog
    `STACKS` co siedziba pary."""
    status: str
    autocrop: VariantSide
    original: OriginalSide | None = None
    variant: str = AUTOCROP
    target_dir: str | None = None
    window_frame_ids: tuple = ()
    window_agrees: bool = False
    detail: str | None = None

    @property
    def applicable(self):
        return self.status in APPLICABLE


@dataclasses.dataclass(frozen=True)
class VariantPlan:
    root: str
    library_root: str
    items: tuple


def _key(path):
    return os.path.normpath(str(path)).casefold()


def _under(path, directory):
    return _key(path).startswith(_key(directory).rstrip("\\/") + os.sep)


def is_autocrop_master(name):
    """Czy nazwa pliku to gotowy obraz WBPP z wariantem `autocrop` i bez drugiego znacznika pochodnej
    (`scan.is_derived_name`) - populacja planu (98 plików w starym drzewie, 2026-10-11)."""
    return (name.lower().startswith("masterlight") and name.lower().endswith(scan.XISF_SUFFIXES)
            and AUTOCROP in naming.wbpp_stack_variants(name) and not scan.is_derived_name(name))


def discover(root, *, stacks_root):
    """`[(ścieżka, rozmiar)]` autocropów spod `root` w kolejności ścieżek; pliki już pod biblioteką
    `stacks_root` pomija (tam wariant jest u celu). Sam odczyt katalogów."""
    out = []
    for katalog, _dirs, pliki in os.walk(root):
        if _key(katalog) == _key(stacks_root) or _under(katalog, stacks_root):
            continue
        for nazwa in pliki:
            if is_autocrop_master(nazwa):
                p = os.path.join(katalog, nazwa)
                try:
                    out.append((p, os.path.getsize(p)))
                except OSError:
                    out.append((p, None))
    return sorted(out, key=lambda t: _key(t[0]))


def _window_key(header):
    """Klucz okna `(DATE-OBS, DATE-END, filtr kanoniczny)` przez `read_testimony` (czas przez
    `naming.header_dt` - SPOT z rodowodem i grupami wersji) albo None, gdy okna brak."""
    t = read_testimony(header)
    if t.window_start is None or t.window_end is None:
        return None
    return t.window_start, t.window_end, normalize_filter(t.filter_raw)


def _read_header(path):
    return scan.read_xisf_meta_full(path).header


def _drizzle(path):
    """Warianty skali z nazwy pliku (`drizzle_<n>x`) bez `autocrop` - człon klucza okna: stos
    drizzle i zwykły stos tych samych subów mają TO SAMO okno, a różne dane. Zmierzone na kopii
    archiwum 2026-10-11: bez tego członu okno wiązało 4 autocropy zwykłych stosów (207 MB)
    z oryginałem drizzle 2x, którego prawdziwy autocrop ma 830 MB."""
    return frozenset(v for v in naming.wbpp_stack_variants(os.path.basename(str(path)))
                     if v != AUTOCROP)


def _stack_rows(con, stacks_root):
    """Gotowe obrazy bazy: `{frame_id: dict}` z `sha1_data`, aktywnością, oknem, obecnymi kopiami
    i wariantem skali z nazw kopii w `STACKS` (z SIEDZIBY, nie z pierwszej lokacji; kopie o różnych
    wariantach nazwy = `None`, konflikt - taka klatka nie jest kandydatem okna)."""
    klatki = {}
    for r in con.execute(
            "SELECT f.id, f.sha1_data, f.retired_at, f.superseded_by, h.raw_json "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.kind = 'master_light' ORDER BY f.id").fetchall():
        naglowek = json.loads(r["raw_json"]) if r["raw_json"] else {}
        klatki[r["id"]] = {"sha1_data": r["sha1_data"],
                           "active": r["retired_at"] is None and r["superseded_by"] is None,
                           "window": _window_key(naglowek), "header": naglowek, "present": []}
    for r in con.execute(
            "SELECT l.frame_id, l.path FROM location l JOIN frame f ON f.id = l.frame_id "
            "WHERE f.kind = 'master_light' AND l.present = 1 ORDER BY l.frame_id, l.id").fetchall():
        klatki[r["frame_id"]]["present"].append(r["path"])
    warianty = {r["variant_frame_id"] for r in con.execute(
        "SELECT variant_frame_id FROM stack_variant").fetchall()}
    for fid, k in klatki.items():
        k["variant"] = fid in warianty or any(
            AUTOCROP in naming.wbpp_stack_variants(os.path.basename(p)) for p in k["present"])
        nazwy = [p for p in k["present"] if _under(p, stacks_root)] or k["present"]
        skale = {_drizzle(p) for p in nazwy}
        k["drizzle"] = skale.pop() if len(skale) == 1 else (frozenset() if not skale else None)
    return klatki


def _by_old_location(con, src, klatki):
    """Świadek (a): klatki, których lokacja (także dawna, `present=0`) leżała pod nazwą autocropu
    bez `_autocrop` w tym samym katalogu. Porównanie bez wielkości liter (NTFS)."""
    katalog, nazwa = os.path.split(src)
    stara = os.path.join(katalog, _AUTOCROP_TOKEN.sub("", nazwa, count=1))
    ids = sorted({r["frame_id"] for r in con.execute(
        "SELECT frame_id FROM location WHERE path = ? COLLATE NOCASE", (stara,)).fetchall()})
    return stara, [fid for fid in ids if fid in klatki and klatki[fid]["active"]]


def _seat(original, stacks_root):
    """Siedziba pary z obecnych kopii oryginału: `(blokada | None, kopia w STACKS, kopie poza)`.
    Kopie w `STACKS` w dwóch katalogach albo pod dwiema nazwami = konflikt - nazwa wariantu
    i jego miejsce zależałyby od kolejności lokacji."""
    w_stacks = [p for p in original["present"] if _under(p, stacks_root)]
    poza = tuple(p for p in original["present"] if not _under(p, stacks_root))
    if not original["present"]:
        return "original_absent", None, poza
    if not w_stacks:
        return "original_outside_stacks", None, poza
    if len({_key(os.path.dirname(p)) for p in w_stacks}) > 1:
        return "original_many_seats", None, poza
    if len({os.path.basename(p).casefold() for p in w_stacks}) > 1:
        return "original_name_conflict", None, poza
    return None, w_stacks[0], poza


def _proposed_seat(con, fid, k, src_name, stacks_root):
    """Cel oryginału spoza `STACKS`: `(katalog, nazwa)` z osi bazy - obiekt, zestaw
    (`projection.zestawy_configow`), filtr (`NoFilter` dla kamery kolorowej) i `naming.stack_name`;
    `(None, None)`, gdy którejś osi brakuje (do ręki bez propozycji)."""
    r = con.execute(
        "SELECT o.canon, f.config_id, f.filter_canon, cam.is_mono FROM frame f "
        "LEFT JOIN object o ON o.id = f.object_id LEFT JOIN camera cam ON cam.id = f.camera_id "
        "WHERE f.id = ?", (fid,)).fetchone()
    zestaw = projection.zestawy_configow(con).get(r["config_id"]) if r["config_id"] else None
    filtr = r["filter_canon"] or (_NOFILTER if r["is_mono"] == 0 else None)
    if not r["canon"] or zestaw is None or not filtr:
        return None, None
    katalog = os.path.join(stacks_root, r["canon"], zestaw[0], filtr)
    h = {str(x).upper(): v for x, v in k["header"].items()}
    kolor = naming.wbpp_stack_color(src_name)
    try:
        nazwa = naming.stack_name(r["canon"], h.get("DATE-OBS"), zestaw[0], filtr, h.get("EXPTIME"),
                                  kolor, variants=tuple(_drizzle(src_name)))
    except ValueError:
        nazwa = None
    return katalog, nazwa


def _plan_item(con, src, size, klatki, okna, stacks_root, read_header):
    side = VariantSide(src=src, size=size)
    try:
        h = {str(k).upper(): v for k, v in read_header(src).items()}
    except Exception as exc:                       # plik nieczytelny: pozycja do ręki, nie wyjątek planu
        return VariantItem("header_unreadable", side, detail=f"{type(exc).__name__}: {exc}")
    klucz = _window_key(h)
    okno = tuple(okna.get((klucz, _drizzle(src)), ())) if klucz is not None else ()

    stara, z_lokacji = _by_old_location(con, src, klatki)
    if len(z_lokacji) > 1:
        return VariantItem("location_ambiguous", side, window_frame_ids=okno,
                           detail=" ".join(str(f) for f in z_lokacji))
    if z_lokacji:
        fid, zrodlo, trafiona = z_lokacji[0], "location", stara
    elif len(okno) == 1:
        fid, zrodlo, trafiona = okno[0], "window", None
    elif okno:
        return VariantItem("window_ambiguous", side, window_frame_ids=okno,
                           detail=" ".join(str(f) for f in okno))
    else:
        return VariantItem("no_original", side)

    k = klatki[fid]
    blokada, w_stacks, poza = _seat(k, stacks_root)
    kat_okna = {_key(os.path.dirname(p)) for f in okno for p in klatki[f]["present"]
                if _under(p, stacks_root)}
    zgodne = w_stacks is not None and kat_okna == {_key(os.path.dirname(w_stacks))}
    wspolne = {"window_frame_ids": okno, "window_agrees": zgodne}
    oryginal = OriginalSide(frame_id=fid, sha1_data=k["sha1_data"], source=zrodlo,
                            other_paths=poza, matched_path=trafiona)

    if blokada == "original_outside_stacks":
        katalog, nazwa = _proposed_seat(con, fid, k, os.path.basename(poza[0]), stacks_root)
        cel_o = os.path.join(katalog, nazwa) if katalog and nazwa else None
        nazwa_v = naming.variant_stack_name(nazwa) if nazwa else None
        cel_v = os.path.join(katalog, nazwa_v) if katalog and nazwa_v else None
        return VariantItem(blokada, dataclasses.replace(side, dst=cel_v, status="to_copy"),
                           dataclasses.replace(oryginal, src=poza[0], dst=cel_o, status="to_copy"),
                           target_dir=katalog, **wspolne)
    if blokada is not None:
        return VariantItem(blokada, side, oryginal, **wspolne)

    oryginal = dataclasses.replace(oryginal, src=w_stacks, dst=w_stacks, status="present")
    siedziba = os.path.dirname(w_stacks)
    segmenty = [s for s in re.split(r"[\\/]+", os.path.relpath(siedziba, stacks_root)) if s]
    if len(segmenty) != 3 or any(s in (".", "..") for s in segmenty):
        return VariantItem("no_seat", side, oryginal, detail=siedziba, **wspolne)
    nazwa = naming.variant_stack_name(os.path.basename(w_stacks))
    if nazwa is None:
        return VariantItem("name_invalid", side, oryginal, target_dir=siedziba,
                           detail=os.path.basename(w_stacks), **wspolne)
    dst = os.path.join(siedziba, nazwa)
    status = "dst_exists" if os.path.lexists(dst) else "ready"
    return VariantItem(status, dataclasses.replace(side, dst=dst, status=(
        "dst_exists" if status == "dst_exists" else "to_copy")), oryginal, target_dir=siedziba,
        **wspolne)


def _reserve(items):
    """Rezerwacja nazw celu w obrębie planu: dwie pozycje o tym samym celu (np. ta sama kopia
    autocropu w dwóch katalogach starego drzewa) - wygrywa mocniejszy świadek oryginału
    (`location` przed `window`), potem ścieżka; druga dostaje `name_taken` (do ręki)."""
    ranga = {"location": 0, "window": 1}
    kolejnosc = sorted(range(len(items)), key=lambda n: (
        ranga.get(items[n].original.source if items[n].original else None, 2),
        _key(items[n].autocrop.src)))
    zajete, out = set(), list(items)
    for n in kolejnosc:
        it = items[n]
        if not it.applicable:
            continue
        if _key(it.autocrop.dst) in zajete:
            out[n] = dataclasses.replace(it, status="name_taken", detail=it.autocrop.dst,
                                         autocrop=dataclasses.replace(it.autocrop, dst=None,
                                                                      status=None))
        else:
            zajete.add(_key(it.autocrop.dst))
    return tuple(out)


def plan(con, root, *, library_root, read_header=_read_header, should_cancel=None):
    """Plan wersji (DRY): autocropy spod `root` → `VariantPlan`. ZERO zapisu - baza i nagłówki
    plików wyłącznie do odczytu. `library_root` = korzeń archiwum (biblioteka `STACKS` pod nim).

    Pozycja `ready` ma cel wolny, `dst_exists` - pod celem coś leży (`apply` sprawdzi bajty: te same =
    ponowienie, inne = konflikt). Każdy inny status to blokada z `BLOCKED`. Kandydaci okna liczeni
    są dla każdej pozycji z czytelnym nagłówkiem - porównanie świadków (a) i (b) jest częścią raportu."""
    if not library_root:
        raise ValueError("plan wersji bez korzenia archiwum (library_root)")
    stacks_root = os.path.join(str(library_root), STACKS_DIR.upper())
    klatki = _stack_rows(con, stacks_root)
    okna = {}
    for fid, k in klatki.items():
        if (k["active"] and not k["variant"] and k["window"] is not None
                and k["drizzle"] is not None):
            okna.setdefault((k["window"], k["drizzle"]), []).append(fid)
    items = []
    for src, size in discover(root, stacks_root=stacks_root):
        if should_cancel is not None and should_cancel():
            break
        items.append(_plan_item(con, src, size, klatki, okna, stacks_root, read_header))
    return VariantPlan(root=str(root), library_root=str(library_root), items=_reserve(items))


def plan_counts(variant_plan):
    """Liczby raportu: wszystkie, z oryginałem po świadku, zgodność okna przy (a), blokady per powód."""
    items = variant_plan.items
    z_lokacji = [i for i in items if i.original is not None and i.original.source == "location"]
    blokady = {}
    for i in items:
        if not i.applicable:
            blokady[i.status] = blokady.get(i.status, 0) + 1
    return {"all": len(items), "location": len(z_lokacji),
            "location_window_agrees": sum(1 for i in z_lokacji if i.window_agrees),
            "location_window_fails": sum(1 for i in z_lokacji if not i.window_agrees),
            "window": sum(1 for i in items if i.original is not None and i.original.source == "window"),
            "applicable": sum(1 for i in items if i.applicable), "blocked": blokady}


def pair_id(original_sha1_data, variant_sha1_data, variant=AUTOCROP):
    """Identyfikator pary w zeznaniu - deterministyczny z tożsamości obu stron (ponowienie daje ten
    sam, inna treść pod tą samą nazwą - inny). Świadka NIE niesie: ta sama para z mocniejszym
    świadkiem to podmiana zeznania, nie inna para."""
    return hashlib.sha1(f"{variant}|{original_sha1_data}|{variant_sha1_data}".encode()).hexdigest()[:16]


def testimony_payload(item, rec, *, copy_status, now):
    """Zeznanie pary (payload; zapis - `projection.write_variant_testimony`): pełne `sha1_data` obu
    stron, status każdej kopii, świadek pary i identyfikator pary."""
    o = item.original
    return {
        "kind": projection.VARIANT_TESTIMONY_KIND, "version": 1, "written_at": now,
        "pair_id": pair_id(o.sha1_data, rec.sha1_data, item.variant),
        "variant": item.variant, "source": o.source,
        "original": {"frame_id": o.frame_id, "sha1_data": o.sha1_data, "path": o.dst,
                     "status": o.status, "matched_path": o.matched_path},
        "copy": {"sha1_data": rec.sha1_data, "file_sha1": rec.file_sha1, "src": item.autocrop.src,
                 "path": item.autocrop.dst, "status": copy_status},
    }


def _fingerprint(payload):
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _record(con, copy_path, payload, now):
    """Odcisk i treść zeznania do kolejki bazy (`repo.record_variant_testimony`)."""
    return repo.record_variant_testimony(
        con, path=projection.variant_testimony_path(copy_path), fingerprint=_fingerprint(payload),
        payload=json.dumps(payload, ensure_ascii=False, sort_keys=True), now=now)


def note_testimony(con, copy_path, *, now):
    """Skan wciągnął kopię pod `STACKS`: gdy to wariant `autocrop` z zeznaniem obok, wpisz zeznanie do
    kolejki. Jeden odczyt małego JSON-u na WJAZD kopii (brama przyrostowa skanu omija pliki bez
    zmian, więc kolejna Dostawa nie czyta niczego). Brak zeznania / zeznanie nieczytelne → False."""
    if AUTOCROP not in naming.wbpp_stack_variants(os.path.basename(str(copy_path))):
        return False
    zeznanie = projection.read_variant_testimony(projection.variant_testimony_path(copy_path))
    if zeznanie is None:
        return False
    return _record(con, copy_path, zeznanie, now)


def _original_drift(con, item):
    """Powód, dla którego oryginał z planu nie nadaje się już na parę - albo None (przed kopią):
    klatka wycofana, zastąpiona albo o innej tożsamości niż w planie, kopia w `STACKS` nieobecna
    w bazie albo na dysku."""
    o = item.original
    k = con.execute("SELECT sha1_data, retired_at, superseded_by FROM frame WHERE id = ?",
                    (o.frame_id,)).fetchone()
    if k is None or k["sha1_data"] != o.sha1_data:
        return "tożsamość oryginału inna niż w planie"
    if k["retired_at"] is not None or k["superseded_by"] is not None:
        return "oryginał wycofany albo zastąpiony"
    if con.execute("SELECT 1 FROM location WHERE frame_id = ? AND present = 1 AND path = ? "
                   "COLLATE NOCASE", (o.frame_id, o.dst)).fetchone() is None:
        return f"kopia oryginału nieobecna w bazie: {o.dst}"
    if not os.path.isfile(o.dst):
        return f"kopia oryginału nieobecna na dysku: {o.dst}"
    return None


_RANGA_ZEZNANIA = {"window": 0, "location": 1}


@dataclasses.dataclass(frozen=True)
class ApplyRow:
    item: VariantItem
    status: str        # placed | exists | conflict | verify_bad | error | identity | original_drift | skipped
    reason: str | None = None
    testimony: str | None = None  # written | replaced | exists | conflict | part_exists | None


def apply(variant_plan, *, con, now, read=scan.scan_file, sha1_fn=hashing.sha1_of,
          should_cancel=None, progress=None):
    """Wykonaj pozycje `APPLICABLE` planu. Pozycje zablokowane → `skipped`. Zwraca `[ApplyRow]`.

    Kolejność na pozycję: (1) stan oryginału z planu (`_original_drift`) - dryf = `original_drift`,
    nic nie kopiujemy; (2) odczyt autocropu (`read` - `sha1_data` i sha1 całego pliku jednym
    przebiegiem); autocrop o `sha1_data` oryginału albo bez obliczalnego `sha1_data` → `identity`;
    (3) kopia `projection.copy_stack_variant`; (4) zeznanie `projection.write_variant_testimony` -
    zeznanie tej samej pary z SŁABSZYM świadkiem (okno, potem dawna lokacja) jest podmieniane CAS-em,
    z mocniejszym albo równym zostaje; (5) odcisk zeznania do kolejki bazy. Błąd I/O pozycji → `error`
    i następna pozycja (raport, nie przerwany bieg). Relacji NIE zapisuje - zrobi to konsument po
    Dostawie (`link_from_testimonies`), gdy obie klatki będą w bazie."""
    out = []
    for n, item in enumerate(variant_plan.items, 1):
        if should_cancel is not None and should_cancel():
            break
        if not item.applicable:
            out.append(ApplyRow(item, "skipped", item.status))
            continue
        try:
            dryf = _original_drift(con, item)
            if dryf is not None:
                out.append(ApplyRow(item, "original_drift", dryf))
                continue
            rec = read(item.autocrop.src)
            if (rec.header is None or rec.sha1_data is None
                    or rec.sha1_data == item.original.sha1_data):
                out.append(ApplyRow(item, "identity", rec.error or rec.sha1_data))
                continue
            status, reason = projection.copy_stack_variant(
                item.autocrop.src, item.autocrop.dst, expected_sha1=rec.file_sha1,
                library_root=variant_plan.library_root, sha1_fn=sha1_fn)
            zeznanie = None
            if status in ("placed", "exists"):
                payload = testimony_payload(item, rec, copy_status=status, now=now)
                stare = projection.read_variant_testimony(
                    projection.variant_testimony_path(item.autocrop.dst))
                podmien = (stare if stare is not None and stare.get("pair_id") == payload["pair_id"]
                           and _RANGA_ZEZNANIA.get(stare.get("source"), -1)
                           < _RANGA_ZEZNANIA[payload["source"]] else None)
                zeznanie, _sciezka = projection.write_variant_testimony(
                    item.autocrop.dst, payload, replace=podmien)
                if zeznanie in ("written", "replaced"):
                    _record(con, item.autocrop.dst, payload, now)
                elif zeznanie == "exists" and stare is not None:
                    _record(con, item.autocrop.dst, stare, now)
            out.append(ApplyRow(item, status, reason, zeznanie))
        except OSError as exc:
            out.append(ApplyRow(item, "error", f"{type(exc).__name__}: {exc}"))
        if progress is not None:
            progress(n, len(variant_plan.items), item.autocrop.src)
    return out


@dataclasses.dataclass
class LinkSummary:
    """Konsument kolejki zeznań: `candidates` (zeznania nowe albo zmienione), `linked` (relacja
    zapisana albo podniesiona teraz), `unchanged` (relacja już taka), `waiting` (klatka pary jeszcze
    nie w bazie - następna Dostawa), `mismatch` (pod ścieżką kopii leży inna treść niż w zeznaniu),
    `refused` (klinga odmówiła - rodzaj, stan oryginału, głębokość, drugi wariant; powód w
    `refusals`)."""
    candidates: int = 0
    linked: int = 0
    unchanged: int = 0
    waiting: int = 0
    mismatch: int = 0
    refused: int = 0
    refusals: list = dataclasses.field(default_factory=list)


def link_from_testimonies(con, now):
    """Zapisz relacje wariantu z kolejki zeznań - etap Dostawy po skanie (faza 0 `run_grouper`).

    Kandydat = wiersz `stack_variant_testimony`, którego odcisk różni się od skonsumowanego - także
    dla wariantu, który relację już ma: zeznanie przepisane mocniejszym świadkiem podnosi rangę
    (precedencja w klindze). Zero odczytów udziału: treść zeznania jest w wierszu. Para po
    `sha1_data` OBU stron: wariant = klatka obecnej kopii pod ścieżką z zeznania (brak kopii w bazie
    → `waiting`, inna tożsamość → `mismatch`), oryginał = klatka o `sha1_data` z zeznania (brak →
    `waiting`). Zapis klingą `repo.link_stack_variant` z kopią oryginału z zeznania (stan obu klatek
    sprawdzany pod blokadą); rozstrzygnięcie (`linked`/`unchanged`/`mismatch`/`refused: …`) zapisuje
    `repo.settle_variant_testimony` - `waiting` zostaje nierozstrzygnięte i wróci, bez czytania plików."""
    s = LinkSummary()
    for row in con.execute(
            "SELECT path, fingerprint, payload FROM stack_variant_testimony "
            "WHERE consumed_fingerprint IS NULL OR consumed_fingerprint <> fingerprint "
            "ORDER BY path").fetchall():
        s.candidates += 1
        z = json.loads(row["payload"])
        kopia, oryginal = z.get("copy") or {}, z.get("original") or {}
        wariant = con.execute(
            "SELECT f.id, f.sha1_data FROM location l JOIN frame f ON f.id = l.frame_id "
            "WHERE l.present = 1 AND l.path = ? COLLATE NOCASE", (kopia.get("path") or "",)).fetchone()
        o = con.execute("SELECT id FROM frame WHERE sha1_data = ?",
                        (oryginal.get("sha1_data"),)).fetchone()
        if wariant is not None and wariant["sha1_data"] != kopia.get("sha1_data"):
            s.mismatch += 1
            wynik = "mismatch"
        elif wariant is None or o is None:
            s.waiting += 1
            continue
        else:
            try:
                if repo.link_stack_variant(con, variant_frame_id=wariant["id"],
                                           original_frame_id=o["id"], variant=z.get("variant"),
                                           source=z.get("source"), now=now,
                                           original_path=oryginal.get("path")):
                    s.linked += 1
                    wynik = "linked"
                else:
                    s.unchanged += 1
                    wynik = "unchanged"
            except ValueError as exc:
                s.refused += 1
                s.refusals.append(f"frame:{wariant['id']}: {exc}")
                wynik = f"refused: {exc}"
        repo.settle_variant_testimony(con, path=row["path"], fingerprint=row["fingerprint"],
                                      outcome=wynik, now=now)
    return s
