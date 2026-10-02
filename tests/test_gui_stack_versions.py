"""Perspektywa „Wersje stosów" - read-model grup bliźniaków, preset z flagą, wiersz Porządków i gest
„Zostaw tę wersję" (schowek + zdanie na pasku).

Ten sam materiał zintegrowany kilka razy: inne piksele, więc „Duplikaty" go nie widzą. Read-model
rozstrzyga PARAMI, czy dwa stosy tej samej grupy (obiekt, kamera, filtr, ekspozycja, okno) to
odrębne integracje, pochodne jednej, czy baza tego nie wie - wyłącznie ze świadków z bazy
(`declared_rows`, sygnatura `tool`, pomiary szumu i PSF w nagłówku), nigdy z nazwy pliku.

Część czysta (klasyfikacja, koercja, read-model na syntetycznej bazie) biegnie bez Qt; testy widoku
biorą `qapp`, który pomija się bez PySide6 - pełny pytest bez Qt zostaje prawdziwy."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from horreum import db
from horreum.gui import i18n, queries
from horreum.gui.i18n_catalog import CATALOG
from horreum.resolve.stack import signature_timestamp

NOW = "2026-09-26T10:00:00"
SYG_NOWA = "process=ImageIntegration,version=1.7.1,timestamp=2026-02-21T12:43:42.945Z"
SYG_STARA = "process=ImageIntegration,version=1.7.1,timestamp=2026-01-24T06:41:48.928Z"


def _pomiary(szum, kanaly=1):
    """Karty pomiaru jak w nagłówku XISF - wartości TEKSTEM, plus etykiety algorytmu (nie liczby)."""
    karty = {"NOISEA00": "MRS", "PSFSGTYP": "Moffat4"}
    for k in range(kanaly):
        karty[f"NOISE{k:02d}"] = f"{szum + k:.4e}"
        karty[f"PSFSGN{k:02d}"] = str(8000 + int(szum * 1e6) + k)
    return karty


def _czlonek(fid, *, tool=None, declared=None, pomiary=None):
    """Członek grupy w kształcie wejścia `classify_stack_versions` (koercja jak w read-modelu)."""
    p = queries._pomiary_obrazu(json.dumps(pomiary or {}))
    return {"frame_id": fid, "tool": tool, "declared": declared, "pomiary": p,
            "kanaly": queries._kanaly(p)}


# ═════════════════════════ część czysta: sygnatura, pomiary, klasyfikacja


def test_sygnatura_niesie_chwile_integracji_a_brak_nie_udaje_faktu():
    assert signature_timestamp(SYG_NOWA) == "2026-02-21T12:43:42.945Z"
    assert signature_timestamp("process=ImageIntegration,version=1.7.1") is None
    assert signature_timestamp(None) is None and signature_timestamp("") is None


def test_pomiary_koercja_przy_wejsciu_i_bez_etykiet_algorytmu():
    """Pułapka tekstu: nagłówek XISF niesie liczby napisami, więc ten sam pomiar zapisany inną drogą
    (`1403.5` wobec `'1.4035e+03'`) jako słownik napisów rozjechałby się w „różne pomiary"."""
    tekst = queries._pomiary_obrazu(json.dumps({"NOISE00": "1.4035e+03", "NOISEA00": "MRS",
                                                "PSFSGTYP": "Moffat4", "OBJECT": "IC1795"}))
    liczba = queries._pomiary_obrazu(json.dumps({"NOISE00": 1403.5}))
    assert tekst == liczba == {"NOISE00": 1403.5}
    assert queries._pomiary_obrazu("{zepsuty") == {} and queries._pomiary_obrazu(None) == {}
    assert queries._kanaly(queries._pomiary_obrazu(json.dumps(_pomiary(1e-4, kanaly=3)))) == {
        "00", "01", "02"}


def test_mono_rozna_historia_albo_sygnatura_to_inna_integracja():
    """IC1795 Ha: 33 wejścia wobec 31 - dwie integracje. Sama sygnatura też wystarcza na kamerze
    mono, bo kanałem jest filtr, a filtr stoi w kluczu grupy."""
    wynik = queries.classify_stack_versions(
        [_czlonek(1, tool=SYG_NOWA, declared=33), _czlonek(2, tool=SYG_STARA, declared=31)], mono=True)
    assert wynik == {1: (queries.WERSJA_INNA, queries.SWIADEK_HISTORIA),
                     2: (queries.WERSJA_INNA, queries.SWIADEK_HISTORIA)}
    wynik = queries.classify_stack_versions(
        [_czlonek(1, tool=SYG_NOWA), _czlonek(2, tool=SYG_STARA)], mono=True)
    assert wynik[1] == (queries.WERSJA_INNA, queries.SWIADEK_SYGNATURA)


def test_kolor_rozne_sygnatury_kanalow_jednej_sesji_to_NIE_wersje():
    """NGC4826 (zmierzone): WBPP na kamerze kolorowej integruje `R`, `G`, `B` osobno - trzy różne
    sygnatury w odstępie dwóch minut, ta sama liczba wejść (190). Nagłówek nie mówi, który kanał
    jest który, więc różna sygnatura NIE dowodzi wersji. Falsyfikator: zdejmij warunek
    `_ten_sam_kanal` z `_para_odrebna` - kanały jednej sesji staną się „inną integracją"."""
    wynik = queries.classify_stack_versions(
        [_czlonek(1, tool=SYG_NOWA, declared=190, pomiary=_pomiary(1e-4)),
         _czlonek(2, tool=SYG_STARA, declared=190, pomiary=_pomiary(2e-4))], mono=False)
    assert {r for r, _s in wynik.values()} == {queries.WERSJA_NIEUSTALONA}


def test_kolor_obrazy_pelnokolorowe_o_roznych_pomiarach_to_wersje():
    """Veil (zmierzone): dwa obrazy RGB zmierzone na trzech kanałach, różne pomiary - na kamerze
    kolorowej to jedyny przypadek, w którym wiemy, że oba przedstawiają ten sam „kanał"."""
    wynik = queries.classify_stack_versions(
        [_czlonek(1, pomiary=_pomiary(1e-4, kanaly=3)), _czlonek(2, pomiary=_pomiary(2e-4, kanaly=3)),
         _czlonek(3)], mono=False)
    assert wynik[1] == wynik[2] == (queries.WERSJA_INNA, queries.SWIADEK_POMIARY)
    assert wynik[3] == (queries.WERSJA_NIEUSTALONA, None), "drizzle bez pomiarów - bez świadka"


def test_identyczne_pomiary_to_pochodna_i_bija_odrebnosc():
    """LMC (zmierzone): `combined_RGB` dziedziczy karty kanału `R` znak w znak. Pochodzenie bije
    odrębność - nawet przy sprzecznej historii nie wolno podsunąć pochodnej do skasowania."""
    wynik = queries.classify_stack_versions(
        [_czlonek(1, pomiary=_pomiary(1e-4)), _czlonek(2, pomiary=_pomiary(1e-4)),
         _czlonek(3, pomiary=_pomiary(3e-4))], mono=False)
    assert wynik[1] == wynik[2] == (queries.WERSJA_POCHODNA, queries.SWIADEK_TE_SAME_POMIARY)
    assert wynik[3] == (queries.WERSJA_NIEUSTALONA, None)
    wynik = queries.classify_stack_versions(
        [_czlonek(1, declared=10, pomiary=_pomiary(1e-4)),
         _czlonek(2, declared=12, pomiary=_pomiary(1e-4))], mono=True)
    assert wynik[1][0] == queries.WERSJA_POCHODNA


def test_ta_sama_sygnatura_to_pochodna_a_brak_swiadka_nieustalone():
    wynik = queries.classify_stack_versions(
        [_czlonek(1, tool=SYG_NOWA), _czlonek(2, tool=SYG_NOWA)], mono=True)
    assert wynik[1] == (queries.WERSJA_POCHODNA, queries.SWIADEK_TA_SAMA_SYGNATURA)
    wynik = queries.classify_stack_versions([_czlonek(1), _czlonek(2)], mono=True)
    assert wynik == {1: (queries.WERSJA_NIEUSTALONA, None), 2: (queries.WERSJA_NIEUSTALONA, None)}


def test_pulapka_tekstu_ekspozycji_nie_rozbija_grupy(monkeypatch):
    """`'600.00'` z nagłówka XISF i `600.0` z kolumny muszą dać JEDEN klucz. SQLite maskuje to
    w porównaniu z kolumną REAL, słownik Pythona - nie; koercja stoi przy wejściu."""
    wiersz = {"object_id": 1, "object_canon": "IC1795", "camera_id": 2, "is_mono": 1,
              "camera_model": "ASI2600MM", "telescope_id": 1, "telescope_label": None,
              "telescop_canon": "A140R",
              "filter_canon": "Ha", "raw_json": "{}", "window_start": "2025-12-16T17:27:54",
              "window_end": "2026-01-21T20:15:51", "tool": None, "declared_rows": None}
    monkeypatch.setattr(queries, "_stack_version_rows", lambda con: [
        {**wiersz, "frame_id": 1, "exptime": "600.00"},
        {**wiersz, "frame_id": 2, "exptime": 600.0},
        {**wiersz, "frame_id": 3, "exptime": 600, "window_end": "2026-01-21T20:15:51.831"}])
    grupy = queries._grupy_wersji(None)
    assert len(grupy) == 1 and {c["frame_id"] for c in grupy[0][3]} == {1, 2, 3}, (
        "napis, liczba i okno z ułamkiem sekundy to ten sam klucz")


def test_kazdy_rodzaj_i_swiadek_ma_zdanie_w_katalogu():
    """Klucze składane w locie (`grid.version.kind.<rodzaj>`, `grid.version.why.<świadek>`) są dla
    kolektora literałów i18n niewidzialne - parytet z tokenami read-modelu pinujemy wprost."""
    for rodzaj in (queries.WERSJA_INNA, queries.WERSJA_POCHODNA, queries.WERSJA_NIEUSTALONA):
        assert f"grid.version.kind.{rodzaj}" in CATALOG
    for swiadek in queries.VERSION_WITNESSES + ("none",):
        assert f"grid.version.why.{swiadek}" in CATALOG
    for swiadek in queries.VERSION_WITNESSES:
        assert f"grid.version.short.{swiadek}" in CATALOG, 'skrót świadka do komórki „Wersja"'


# ═════════════════════════ read-model na syntetycznej bazie


_BEZ_CONFIGU = object()


def _stos(con, fid, *, kamera, obiekt, filtr, exp, okno, tool=None, declared=None, pomiary=None,
          sciezki=None, martwe=(), wycofana=None, config=None):
    """Gotowy obraz z integracją: frame + header + integration + lokacje (obecne i martwe).
    Config domyślnie = id kamery (zestaw A140R z tą kamerą, `_seed_wersje`); `_BEZ_CONFIGU` → NULL."""
    cfg = None if config is _BEZ_CONFIGU else (config if config is not None else kamera)
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at, camera_id, "
                "object_id, filter_canon, retired_at, config_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fid, f"d{fid}", "master_light", "xisf", NOW, kamera, obiekt, filtr, wycofana, cfg))
    con.execute("INSERT INTO header (frame_id, raw_json, exptime) VALUES (?,?,?)",
                (fid, json.dumps(pomiary or {}), exp))
    con.execute("INSERT INTO integration (master_frame_id, created_at, tool, window_start, "
                "window_end, declared_rows) VALUES (?,?,?,?,?,?)",
                (fid, NOW, tool, okno[0], okno[1], declared))
    for p in (sciezki if sciezki is not None else [f"/st/{fid}.xisf"]):
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,1)",
                    (fid, "V", p))
    for p in martwe:
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,0)",
                    (fid, "V", p))


W_A = ("2025-12-16T17:27:54", "2026-01-21T20:15:51")
W_B = ("2023-03-23T07:48:22", "2023-03-23T07:50:23")


def _seed_wersje(con):
    """Pięć sytuacji z żywego archiwum, każda na swoim kluczu:
      A (IC1795, mono)  - dwie integracje (historia 33/31) + stos bez świadka: WERSJE;
      B (LMC, kolor)    - `R` i `combined_RGB` z identycznymi pomiarami, `B`, drizzle: POCHODNA;
      C (M31, mono)     - dwa stosy bez żadnego świadka: NIEUSTALONE;
      D (M42, mono)     - druga wersja wycofana ręką: grupy NIE MA (jeden żywy stos);
      E (Veil, kolor)   - dwa obrazy RGB o różnych pomiarach: WERSJE;
    plus stos samotny (bez bliźniaka)."""
    con.executemany("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES (?,?,?,?)",
                    [(1, "ASI2600MC", 0, NOW), (2, "ASI2600MM", 1, NOW)])
    # Zestawy: config 1/2 = A140R z kamerą 1/2; config 3 = drugi teleskop (76EDPH) z kamerą
    # TEGO SAMEGO MODELU co config 2 - zestaw podwójny tej samej nocy (`_grupy_wersji`).
    con.executemany("INSERT INTO telescope (id, telescop_canon, status, created_at) VALUES (?,?,?,?)",
                    [(1, "A140R", "approved", NOW), (2, "76EDPH", "approved", NOW)])
    con.executemany("INSERT INTO config (id, telescope_id, camera_id, status, created_at) "
                    "VALUES (?,?,?,?,?)",
                    [(1, 1, 1, "approved", NOW), (2, 1, 2, "approved", NOW),
                     (3, 2, 2, "approved", NOW)])
    con.executemany("INSERT INTO object (id, canon) VALUES (?,?)",
                    [(1, "IC1795"), (2, "LMC"), (3, "M31"), (4, "M42"), (5, "Veil"), (6, "M51")])
    a = dict(kamera=2, obiekt=1, filtr="Ha", exp=600.0, okno=W_A)
    _stos(con, 101, tool=SYG_NOWA, declared=33, pomiary=_pomiary(5e-5),
          sciezki=["/st/IC1795/Ha/nowa.xisf"], **a)
    _stos(con, 102, tool=SYG_STARA, declared=31, pomiary=_pomiary(6e-5),
          sciezki=["/st/IC1795/Ha/stara.xisf", "/kopia/stara.xisf"], martwe=["/dawne/stara.xisf"], **a)
    _stos(con, 103, sciezki=["/st/IC1795/Ha/bez_swiadka.xisf"], **a)
    b = dict(kamera=1, obiekt=2, filtr=None, exp=121.0, okno=W_B)
    _stos(con, 201, pomiary=_pomiary(1e-4), **b)
    _stos(con, 202, pomiary=_pomiary(1e-4), **b)
    _stos(con, 203, pomiary=_pomiary(2e-4), **b)
    _stos(con, 204, **b)
    c = dict(kamera=2, obiekt=3, filtr="L", exp=300.0, okno=("2024-01-01T20:00:00", "2024-01-02T02:00:00"))
    _stos(con, 301, **c)
    _stos(con, 302, **c)
    d = dict(kamera=2, obiekt=4, filtr="Ha", exp=60.0, okno=("2024-02-01T20:00:00", "2024-02-01T23:00:00"))
    _stos(con, 401, pomiary=_pomiary(1e-5), **d)
    _stos(con, 402, pomiary=_pomiary(2e-5), wycofana=NOW, sciezki=[], martwe=["/st/M42/x.xisf"], **d)
    e = dict(kamera=1, obiekt=5, filtr=None, exp=300.0, okno=("2023-08-22T18:43:24", "2023-08-23T02:03:02"))
    _stos(con, 601, pomiary=_pomiary(3e-5, kanaly=3), **e)
    _stos(con, 602, pomiary=_pomiary(4e-5, kanaly=3), **e)
    _stos(con, 701, kamera=2, obiekt=6, filtr="L", exp=60.0,
          okno=("2024-03-01T20:00:00", "2024-03-01T22:00:00"), pomiary=_pomiary(7e-5))
    # jedna karta, żeby widok miał kolumnę-keyword (pozycja kolumny „Wersja" względem keywordów)
    con.executemany("INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) "
                    "VALUES (?,?,?,?,?,?)",
                    [(101, "OBJECT", 0, "IC1795 nowa", None, "str"),
                     (102, "OBJECT", 0, "IC1795 stara", None, "str")])
    con.commit()


@pytest.fixture
def wcon(tmp_path):
    con = db.open_db(str(tmp_path / "wersje.db"))
    _seed_wersje(con)
    yield con
    con.close()


def test_grupy_rodzaje_i_zbior_perspektywy(wcon):
    grupy = queries.stack_version_groups(wcon)
    assert [(g["object_canon"], g["kind"]) for g in grupy] == [
        ("IC1795", queries.WERSJA_INNA), ("LMC", queries.WERSJA_POCHODNA),
        ("M31", queries.WERSJA_NIEUSTALONA), ("Veil", queries.WERSJA_INNA)], (
        "M42 znika: druga wersja wycofana, żywy został jeden stos; M51 nie ma bliźniaka")
    ic = grupy[0]
    fakty = {m["frame_id"]: m for m in ic["members"]}
    assert fakty[101]["timestamp"] == "2026-02-21T12:43:42.945Z" and fakty[101]["declared_rows"] == 33
    assert fakty[103]["kind"] == queries.WERSJA_NIEUSTALONA
    # perspektywa: WSZYSCY członkowie grup wersji (także ten bez świadka), nic z pochodnych
    assert queries.stack_version_frame_ids(wcon) == {101, 102, 103, 601, 602}
    assert queries.tasks_state(wcon)["stack_versions"] == 5, "wiersz liczy to samo, co lista"


def test_wersja_usunieta_poza_programem_zdejmuje_grupe_z_listy(wcon):
    """Po skasowaniu pliku i skanie klatka traci ostatnią kopię - grupa ma zniknąć z listy roboty.
    Falsyfikator: zdejmij `EXISTS(present = 1)` z `_stack_version_rows` - grupa zostanie."""
    wcon.execute("UPDATE location SET present = 0 WHERE frame_id = 102")
    wcon.execute("UPDATE location SET present = 0 WHERE frame_id = 103")
    wcon.commit()
    assert queries.stack_version_frame_ids(wcon) == {601, 602}


def test_plan_zostaw_te_wersje(wcon):
    """Do schowka: WSZYSTKIE obecne kopie pozostałych wersji (dwie kopie `stara`, bez martwej),
    nic z członka bez dowodu względem zostawianego - ten jest policzony osobno."""
    assert queries.keep_version_plan(wcon, 101) == {
        "paths": ["/st/IC1795/Ha/stara.xisf", "/kopia/stara.xisf"], "stacks": 1,
        "derived": 0, "unknown": 1}
    assert queries.keep_version_plan(wcon, 102)["paths"] == ["/st/IC1795/Ha/nowa.xisf"]
    assert queries.keep_version_plan(wcon, 103) == {"paths": [], "stacks": 0, "derived": 0,
                                                    "unknown": 2}
    assert queries.keep_version_plan(wcon, 201) == {"paths": [], "stacks": 0, "derived": 1,
                                                    "unknown": 2}
    assert queries.keep_version_plan(wcon, 701) is None, "stos bez bliźniaka nie ma planu"


# ═════════════════════════ widok: preset, kolumna, grupowanie, gest, Porządki


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp, wcon, monkeypatch):
    from horreum.gui.grid import FramesView
    v = FramesView(wcon, now_fn=lambda: NOW)
    v._writeback_async = False
    v.komunikaty = []
    v.status_message.connect(v.komunikaty.append)
    yield v


def _zaznacz(view, frame_ids):
    from PySide6.QtCore import QItemSelectionModel
    sm = view.table.selectionModel()
    sm.clearSelection()
    for i, row in enumerate(view.model._rows):
        if isinstance(row, dict) and row.get("frame_id") in set(frame_ids):
            sm.select(view.model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


def _komorka_wersji(view, frame_id, rola):
    from PySide6.QtCore import Qt
    r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == frame_id)
    return view.model.data(view.model.index(r, view.model._version_col()), getattr(Qt, rola))


def test_perspektywa_ustawia_wersje_obok_siebie_z_faktami(view):
    from PySide6.QtCore import Qt
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    assert sorted(view._frame_ids) == [101, 102, 103, 601, 602]
    assert view.combo_group.currentData() == grid_mod._GRUPA_WERSJI
    assert i18n.t("grid.criteria.only_stack_versions") in view.sel_bar.criteria_label.toolTip()
    kol = view.model._version_col()
    assert view.model.headerData(kol, Qt.Horizontal) == "Wersja"
    # OBOK SIEBIE: pod każdą belką stoją wyłącznie stosy jej grupy, a grupa nie jest rozcięta
    belki, pod_belka = [], {}
    for row in view.model._rows:
        if "_group" in row:
            belki.append(row["_group"])
            continue
        pod_belka.setdefault(belki[-1], []).append(row["frame_id"])
        assert row["_wersja_etykieta"] == belki[-1]
    assert len(belki) == 2 and sorted(map(sorted, pod_belka.values())) == [[101, 102, 103], [601, 602]]
    assert belki[0].startswith("IC1795 · Ha · 600 s · okno 2025-12-16 17:27:54 - 2026-01-21 20:15:51")
    assert "zestaw" not in belki[0], "rozróżnik zestawu tylko przy kolizji opisów"
    assert (_komorka_wersji(view, 101, "DisplayRole")
            == "inna integracja · historia · 2026-02-21 12:43 · 33 wejścia")
    assert (_komorka_wersji(view, 102, "DisplayRole")
            == "inna integracja · historia · 2026-01-24 06:41 · 31 wejść")
    assert _komorka_wersji(view, 601, "DisplayRole") == "inna integracja · szum i PSF", (
        "jedyny powód werdyktu - pomiary - stoi w komórce, nie tylko pod kursorem")
    assert _komorka_wersji(view, 103, "DisplayRole") == "nieustalone"
    assert "historia pliku" in _komorka_wersji(view, 101, "ToolTipRole")
    assert "baza nie ma świadka" in _komorka_wersji(view, 103, "ToolTipRole")


def test_kolumna_wersji_stoi_przed_keywordami_i_nie_przesuwa_ich_tresci(view):
    """Kolumna „Wersja" stoi zaraz po bazowych - za keywordami lądowała poza krawędzią okna
    (zrzut offscreen na kopii żywej bazy). Keywordy przesuwają się o nią BEZ zmiany treści, sort
    po niej jest chronologiczny, a podgląd klingi zostaje ostatnią kolumną."""
    from PySide6.QtCore import Qt
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    m = view.model
    baza = len(grid_mod.BASE_COLS)
    assert m._version_col() == baza
    assert m.headerData(baza + 1, Qt.Horizontal) == "OBJECT"

    def _nr(fid):
        return next(i for i, row in enumerate(m._rows) if row.get("frame_id") == fid)

    assert m.data(m.index(_nr(101), baza + 1), Qt.DisplayRole) == "IC1795 nowa"
    m.sort(baza, Qt.AscendingOrder)
    assert _nr(102) < _nr(101), "wersja ze stycznia przed wersją z lutego"
    m.set_preview({101: {"keyword": "OBJECT", "old": "a", "new": "b", "op": "set"}})
    try:
        assert m._preview_col() == m.columnCount() - 1 == baza + 1 + len(m._keywords)
        assert m.data(m.index(_nr(101), m._preview_col()), Qt.DisplayRole) == "a → b"
        assert m.data(m.index(_nr(101), baza + 1), Qt.DisplayRole) == "IC1795 nowa"
    finally:
        m.set_preview({})


def test_kolumna_wersji_tylko_w_swojej_perspektywie(view):
    """Regresja pozostałych perspektyw: bez kolumny, bez grupowania wersji, bez read-modelu."""
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    with_col = view.model.columnCount()
    for nazwa in grid_mod.PRESETS:
        if nazwa == grid_mod.PRESET_STACK_VERSIONS:
            continue
        view.apply_perspective(nazwa)
        assert view.model._version_col() is None, nazwa
        assert view.model.columnCount() == with_col - 1, nazwa
        assert not view._potrzebne_wersje(), nazwa


def test_grupowanie_wersja_stosu_dziala_tez_poza_perspektywa(view):
    from horreum.gui import grid as grid_mod
    view.apply_perspective("Przegląd")
    view.combo_group.setCurrentIndex(view.combo_group.findData(grid_mod._GRUPA_WERSJI))
    belki = [row["_group"] for row in view.model._rows if "_group" in row]
    assert "(brak)" in belki, "stos bez bliźniaka i klatki spoza stosów lądują w „(brak)"
    assert sum(1 for b in belki if b.startswith("LMC")) == 1, "pochodne też mają belkę grupy"
    assert view.model._version_col() is None, "kolumna należy do perspektywy, nie do grupowania"


def test_gest_zostaw_te_wersje_kopiuje_sciezki_i_mowi_ile(view):
    from PySide6.QtWidgets import QApplication
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    stan_przed = view.con.execute("SELECT COUNT(*), SUM(present) FROM location").fetchone()[:]
    zdarzen_przed = view.con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    _zaznacz(view, [101])
    view._sync_menu_wersji()
    assert view.act_keep_version.isEnabled()
    assert view.act_keep_version.toolTip().startswith("Kopiuje do schowka 2 ścieżki")
    view._on_keep_version()
    assert QApplication.clipboard().text().split("\n") == ["/st/IC1795/Ha/stara.xisf",
                                                            "/kopia/stara.xisf"]
    zdanie = view.komunikaty[-1]
    assert zdanie.startswith("Skopiowano do schowka 2 ścieżki (pozostała wersja: 1 stos)")
    assert "bez dowodu wersji pominięty 1 stos" in zdanie and "niczego nie usuwa" in zdanie
    # gest NIE pisze do bazy: ani stanu lokacji, ani dziennika
    assert view.con.execute("SELECT COUNT(*), SUM(present) FROM location").fetchone()[:] == stan_przed
    assert view.con.execute("SELECT COUNT(*) FROM event").fetchone()[0] == zdarzen_przed


def test_gest_bez_dowodu_albo_na_kilku_stosach_nie_rusza_schowka(view):
    from PySide6.QtWidgets import QApplication
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    QApplication.clipboard().setText("nietknięte")
    _zaznacz(view, [103])
    view._sync_menu_wersji()
    assert not view.act_keep_version.isEnabled()
    assert view.act_keep_version.toolTip() == i18n.t("grid.version.nothing")
    view._on_keep_version()
    assert view.komunikaty[-1] == i18n.t("grid.version.nothing")
    _zaznacz(view, [101, 102])
    view._sync_menu_wersji()
    assert not view.act_keep_version.isEnabled()
    assert view.act_keep_version.toolTip() == i18n.t("grid.version.select_one")
    view._on_keep_version()
    assert view.komunikaty[-1] == i18n.t("grid.version.select_one")
    assert QApplication.clipboard().text() == "nietknięte"


def test_menu_kontekstowe_tylko_w_perspektywie_wersji_i_poza_paskiem_zbioru(view):
    """Gest mieszka w menu tabeli, nie na `sel_bar` - pasek zbioru (mierzona podłoga okna) nie
    dostaje kontrolki dla gestu jednej perspektywy. Poza nią prawy klik nie pokazuje niczego.
    Menu idzie `popup`, nie `exec` - blokujące `exec` zawiesiło pierwszą wersję tego testu."""
    from PySide6.QtCore import QPoint
    from horreum.gui import grid as grid_mod
    view.apply_perspective("Przegląd")
    view._on_table_menu(QPoint(5, 5))
    assert not view._menu_tabeli.isVisible()
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    view._on_table_menu(QPoint(5, 5))
    try:
        assert view._menu_tabeli.isVisible()
        assert view.act_keep_version in view._menu_tabeli.actions()
        assert view.act_keep_version.isVisible()
        # sekcja izolacji zapisu tylko nad kopią izolowaną - tu jej nie ma
        assert not view.act_finish_write.isVisible()
    finally:
        view._menu_tabeli.hide()
    assert view.act_keep_version not in view.sel_bar.findChildren(type(view.act_keep_version))


def test_wiersz_porzadkow_otwiera_perspektywe_i_nie_swieci_plakietki(view, wcon):
    """„Zostawiam obie" to prawowita decyzja bez werdyktu w bazie - wiersz liczony do plakietki
    świeciłby wiecznie. Falsyfikator: wyjmij `stack_versions` z `tasks._BEZ_ROBOTY`."""
    from PySide6.QtCore import Qt
    from horreum.gui import rows, tasks as tasks_mod
    tv = tasks_mod.TasksView(wcon)
    tv.open_collection.connect(view.apply_perspective)
    try:
        przed = tv.refresh_counts()
        it = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                  if tv.tasks.item(i).data(Qt.UserRole) == "stack_versions")
        assert it.text() == "Wersje stosów" and it.data(rows.SECONDARY) == "5  ›"
        assert it.data(rows.STRONG) is False
        wcon.execute("UPDATE location SET present = 0 WHERE frame_id IN (102, 103, 602)")
        wcon.commit()
        assert tv.refresh_counts() == przed, "zmiana liczby wersji nie rusza plakietki"
        assert it.data(rows.SECONDARY) == "0  ›"
        wcon.execute("UPDATE location SET present = 1")
        wcon.commit()
        tv.refresh_counts()
        tv._on_task_clicked(it)
        assert sorted(view._frame_ids) == [101, 102, 103, 601, 602]
    finally:
        tv.close()


def test_zapisana_perspektywa_nie_psuje_sie_od_nowej_flagi(view, wcon, monkeypatch):
    """Stary zapis (bez klucza `only_stack_versions`) stosuje się z flagą wyłączoną; nowy zapis
    niesie ją pod kluczem spec-a, a ten build go zna - bez ostrzeżenia o nieznanych warunkach."""
    from PySide6.QtWidgets import QInputDialog
    from horreum import repo
    from horreum.gui import grid as grid_mod
    repo.save_perspective(wcon, name="stary", spec={"filter": None, "group_by": None,
                                                     "only_dups": False}, now=NOW)
    view._load_facets()
    view.apply_perspective("stary")
    assert not view._perspektywa_wersji() and view.model._version_col() is None
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("moje wersje", True)))
    view._save_perspective()
    zapis = dict(queries.perspectives(wcon))["moje wersje"]
    assert zapis["only_stack_versions"] is True and zapis["group_by"] == grid_mod._GRUPA_WERSJI
    assert grid_mod._nieznane_warunki(zapis) == []
    view.apply_perspective("Przegląd")
    view.apply_perspective("moje wersje")
    assert view._perspektywa_wersji() and sorted(view._frame_ids) == [101, 102, 103, 601, 602]


# ═════════════════════════ zestaw podwójny, kopia martwa, sort, odmiana, układ perspektywy


def _zestaw_podwojny(con):
    """NGC3034 B tej samej nocy na dwóch zestawach z kamerą TEGO SAMEGO MODELU (config 2: A140R,
    config 3: 76EDPH) - po dwie integracje na zestaw - plus stos bez configu na tym samym kluczu."""
    con.execute("INSERT INTO object (id, canon) VALUES (7, 'NGC3034')")
    w = dict(kamera=2, obiekt=7, filtr="B", exp=180.0,
             okno=("2024-04-01T20:00:00", "2024-04-02T01:00:00"))
    _stos(con, 801, declared=20, config=2, **w)
    _stos(con, 802, declared=18, config=2, **w)
    _stos(con, 811, declared=40, config=3, **w)
    _stos(con, 812, declared=41, config=3, **w)
    _stos(con, 821, declared=7, config=_BEZ_CONFIGU, **w)
    con.commit()


def test_zestaw_podwojny_z_kamera_tego_samego_modelu_to_dwie_grupy(wcon):
    """`camera` jest per MODEL, więc kamera nie rozcina zestawu podwójnego - rozcina go teleskop
    kanoniczny z configu. Stos bez configu nie orzeka wspólnego materiału i nie wchodzi do grupy.
    Falsyfikator: zdejmij teleskop z klucza `_grupy_wersji` - pięć stosów zleje się w jedną grupę,
    a „Zostaw tę wersję" podsunie do skasowania stosy z drugiego teleskopu."""
    _zestaw_podwojny(wcon)
    grupy = [g for g in queries.stack_version_groups(wcon) if g["object_canon"] == "NGC3034"]
    assert sorted(sorted(m["frame_id"] for m in g["members"]) for g in grupy) == [[801, 802],
                                                                                 [811, 812]]
    assert {g["telescope"] for g in grupy} == {"A140R", "76EDPH"}
    assert {g["camera"] for g in grupy} == {"ASI2600MM"}
    assert len({g["group_id"] for g in grupy}) == 2
    assert ([g["group_id"] for g in queries.stack_version_groups(wcon)]
            == [g["group_id"] for g in queries.stack_version_groups(wcon)]), (
        "identyfikator stabilny między przeładowaniami")
    assert 821 not in queries.stack_version_frame_ids(wcon)
    assert queries.keep_version_plan(wcon, 801)["paths"] == ["/st/802.xisf"], (
        "plan nie sięga po stosy z drugiego zestawu")
    assert queries.keep_version_plan(wcon, 821) is None


def test_scalony_teleskop_nie_rozcina_grupy(wcon):
    """Teleskop przez `telescope_canonical`: scalenie 76EDPH pod A140R zlewa oba zestawy w jeden
    materiał (ten sam kanon i ta sama kamera)."""
    _zestaw_podwojny(wcon)
    wcon.execute("UPDATE telescope SET merged_into = 1 WHERE id = 2")
    wcon.commit()
    grupy = [g for g in queries.stack_version_groups(wcon) if g["object_canon"] == "NGC3034"]
    assert [sorted(m["frame_id"] for m in g["members"]) for g in grupy] == [[801, 802, 811, 812]]


def test_belki_dwoch_zestawow_rozne_i_grupowane_po_identyfikatorze(view, wcon):
    """Ten sam opis (obiekt · filtr · ekspozycja · okno) na dwóch zestawach: dwie belki, każda
    z rozróżnikiem zestawu, a pod każdą wyłącznie jej stosy. Falsyfikator: grupuj po podpisie
    bez rozróżnika - cztery stosy wylądują pod jedną belką."""
    from horreum.gui import grid as grid_mod
    _zestaw_podwojny(wcon)
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    pod_belka, belka = {}, None
    for row in view.model._rows:
        if "_group" in row:
            belka = row["_group"]
            continue
        pod_belka.setdefault(belka, []).append(row["frame_id"])
    ngc = {b: sorted(f) for b, f in pod_belka.items() if b.startswith("NGC3034")}
    assert sorted(ngc.values()) == [[801, 802], [811, 812]]
    assert {b.split(" · zestaw ")[1] for b in ngc} == {"A140R + ASI2600MM", "76EDPH + ASI2600MM"}


def test_wiersz_z_martwej_kopii_nie_zeznaje_liczby_obrazow(wcon):
    """Klatka bez obecnej kopii pokazuje adres martwej, ale nie jej `image_count` - plik, którego
    nie ma, nie mówi o stanie dysku. Falsyfikator: wróć do gołego `loc.image_count`."""
    for fid in (401, 402):
        wcon.execute("UPDATE location SET header_hash = 'hh', hdr_hash = 'hh', image_count = 1, "
                     "image_roles = '[\"integration\"]' WHERE frame_id = ?", (fid,))
    wcon.commit()
    wiersze = {r["frame_id"]: r for r in queries.base_rows(wcon, [401, 402])}
    assert wiersze[402]["present"] == 0 and wiersze[402]["path"] == "/st/M42/x.xisf"
    assert wiersze[402]["image_count"] is None
    assert wiersze[401]["image_count"] == 1, "obecna kopia zeznaje dalej"


def test_sort_wersji_braki_na_koncu_w_obu_kierunkach(view):
    """Stos bez chwili integracji i stos bez liczby wejść stają ZA znanymi wartościami - rosnąco
    i malejąco. Falsyfikator: wróć do `timestamp or ""` / `declared_rows or 0`."""
    from PySide6.QtCore import Qt
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    m = view.model
    fakty = {r["frame_id"]: r["_wersja"] for r in m._data_rows}
    fakty[103]["declared_rows"] = 5                 # bez chwili, z liczbą wejść
    fakty[102]["declared_rows"] = None              # z chwilą, bez liczby wejść
    fakty[601]["timestamp"] = fakty[602]["timestamp"] = fakty[101]["timestamp"]
    fakty[601]["declared_rows"] = 10                # ta sama chwila: znana liczba przed brakiem

    def _kolejnosc():
        return [r["frame_id"] for r in m._rows if "_group" not in r]

    m.set_group_by(None)
    m.sort(m._version_col(), Qt.AscendingOrder)
    k = _kolejnosc()
    assert k.index(102) < k.index(101) < k.index(103), "brak chwili na końcu rosnąco"
    assert k.index(601) < k.index(602), "brak liczby wejść za znaną przy tej samej chwili"
    m.sort(m._version_col(), Qt.DescendingOrder)
    k = _kolejnosc()
    assert k.index(101) < k.index(102) < k.index(103), "brak chwili na końcu także malejąco"
    assert k.index(601) < k.index(602), "brak liczby wejść na końcu także malejąco"


def test_odmiana_zdania_gestu():
    """„pozostała wersja: 1 stos" / „pozostałe wersje: 2 stosy"; „pominięty 1 stos" /
    „pominięte 3 stosy" / „pominiętych 12 stosów" - forma idzie za liczbą."""
    assert i18n.t_plural("grid.version.copied_stacks", 1) == " (pozostała wersja: 1 stos)"
    assert i18n.t_plural("grid.version.copied_stacks", 2) == " (pozostałe wersje: 2 stosy)"
    assert i18n.t_plural("grid.version.copied_stacks", 5) == " (pozostałe wersje: 5 stosów)"
    assert i18n.t_plural("grid.version.skipped_unknown", 1).endswith("pominięty 1 stos")
    assert i18n.t_plural("grid.version.skipped_unknown", 3).endswith("pominięte 3 stosy")
    assert i18n.t_plural("grid.version.skipped_unknown", 12).endswith("pominiętych 12 stosów")


def test_belka_grupy_na_cala_szerokosc_takze_po_sorcie(view):
    """Belka grupy obejmuje wszystkie kolumny (span) przy KAŻDYM grupowaniu, wiersze danych nie.
    Spany są własnością widoku i reset modelu ich nie zdejmuje, więc po sorcie muszą przejść za
    belkami, a bez grupowania - zniknąć. Falsyfikator: zdejmij `clearSpans` z
    `_uloz_belki_i_wersje`."""
    from PySide6.QtCore import Qt
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    m, t = view.model, view.table

    def _spany():
        return [("_group" in r, t.columnSpan(i, 0)) for i, r in enumerate(m._rows)]

    def _sprawdz():
        assert any(b for b, _s in _spany())
        for belka, span in _spany():
            assert span == (m.columnCount() if belka else 1)

    _sprawdz()
    m.sort(m._version_col(), Qt.DescendingOrder)
    _sprawdz()
    m.set_preview({101: {"keyword": "OBJECT", "old": "a", "new": "b", "op": "set"}})
    try:
        _sprawdz()                                   # kolumna podglądu też pod belką
    finally:
        m.set_preview({})
    view.apply_perspective("Przegląd")
    assert all(span == 1 for _b, span in _spany()), "bez grupowania zero spanów"
    view.combo_group.setCurrentIndex(view.combo_group.findData("_object"))
    assert m._group_by == "_object"
    _sprawdz()                                       # grupowanie po Obiekcie też rozpina belki
    m.sort(0, Qt.DescendingOrder)
    _sprawdz()
    view.combo_group.setCurrentIndex(0)              # „bez grupowania" - pierwsza pozycja
    assert m._group_by is None and all(span == 1 for _b, span in _spany())


def test_wersja_stoi_wizualnie_za_sciezka(view):
    """Kolumna „Wersja" widoczna zaraz za „Ścieżką" (przesunięcie w nagłówku), a jej indeks
    logiczny - ten, który liczą sort i podgląd - zostaje za bazowymi. Po wyjściu z perspektywy
    nagłówek wraca do porządku logicznego."""
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    m, h = view.model, view.table.horizontalHeader()
    assert m._version_col() == len(grid_mod.BASE_COLS)
    assert h.logicalIndex(0) == 0 and h.logicalIndex(1) == m._version_col()
    m.set_preview({101: {"keyword": "OBJECT", "old": "a", "new": "b", "op": "set"}})
    try:
        assert h.logicalIndex(1) == m._version_col(), "zmiana liczby kolumn nie gubi układu"
    finally:
        m.set_preview({})
    view.apply_perspective("Przegląd")
    assert [h.logicalIndex(i) for i in range(h.count())] == list(range(h.count()))


def test_sciezka_w_wersjach_elidowana_w_srodku(view):
    """Wersje pary różnią się OGONEM nazwy (`…_mono.xisf` wobec `…_mono_OBIEKT-…_WBPP_20260124.xisf`,
    zmierzone na kopii archiwum), więc ścieżka w tej perspektywie traci środek, nie koniec - wspólny
    mechanizm kolumn z treści (`kolumna_z_tresci`). Poza perspektywą elizja wraca do domyślnej."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QStyleOptionViewItem
    from horreum.gui import grid as grid_mod
    view.apply_perspective(grid_mod.PRESET_STACK_VERSIONS)
    m = view.model
    kol = m.base_col("path")
    delegat = view.table.itemDelegateForColumn(kol)
    assert delegat is not None
    wiersz = next(i for i, r in enumerate(m._rows) if "_group" not in r)
    opcja = QStyleOptionViewItem()
    delegat.initStyleOption(opcja, m.index(wiersz, kol))
    assert opcja.textElideMode == Qt.ElideMiddle
    assert view.table.columnWidth(kol) <= grid_mod._SUFIT_KOLUMNY_Z_TRESCI
    view.apply_perspective("Przegląd")
    assert view.table.itemDelegateForColumn(m.base_col("path")) is None
