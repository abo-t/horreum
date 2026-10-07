"""Oś KANAŁU gotowego obrazu (0028, P4-3): `frame.channel` z nazwy kopii, facet „Kanał", grupy wersji.

Kamera kolorowa daje z jednej sesji trzy stosy kanałów (WBPP integruje R, G i B osobno), a `FILTER`
niesie filtr OPTYCZNY albo nic - fakt „który kanał" żyje wyłącznie w nazwie pliku. Pole jest
POCHODNĄ: liczy je resolver z `location.path`, bez ponownego odczytu pliku, jednym eventem na
przebieg. Nazwy w testach to realne nazwy z archiwum (zmierzone `?mode=ro` 2026-10-04)."""
import json
import re
from importlib import resources

import pytest

from horreum import db, filter_engine, repo
from horreum.gui import facet_model, queries
from horreum.resolve.channel import CHANNELS, channel_from_name, frame_channel
from horreum.resolver import derive_channels, run_resolver

NOW = "2026-10-04T10:00:00"


# ═════════════════════════ reguła nazwy (czysta)


@pytest.mark.parametrize("nazwa, kanal", [
    # konwencja WBPP: dwa podkreślniki, jeden (starszy WBPP), ogon `_n`, przycięty wariant
    ("masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter__B.xisf", "B"),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-1800.00s_FILTER-NoFilter__G_n.xisf", "G"),
    ("masterLight_BIN-1_4144x2822_EXPOSURE-60.00s_FILTER-NoFilter_R.xisf", "R"),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-120.00s_FILTER-LPRO__B_autocrop.xisf", "B"),
    # konwencja archiwum stosów: kanał zaraz po ekspozycji, z ogonem albo bez
    ("NGC1976_2021-11-10_ED120R_294MC_NoFilter_60s_B.xisf", "B"),
    ("NGC3034_2022-04-22_RC8_2600MC_NoFilter_600s_R_WBPP2.xisf", "R"),
    ("NGC3034_2022-03-23_RC8_2600MC_NoFilter_1800s_G_n.xisf", "G"),
])
def test_kanal_z_nazwy_obu_konwencji(nazwa, kanal):
    assert channel_from_name(nazwa) == kanal


@pytest.mark.parametrize("nazwa", [
    # MONO z filtrem niebieskim - litera stoi w MIEJSCU filtra, nie kanału. Falsyfikator reguły
    # pozycyjnej: goły token `B` gdziekolwiek w nazwie nadałby im kanał.
    "masterLight_BIN-1_6248x4176_EXPOSURE-180.00s_FILTER-B_mono.xisf",
    "NGC3034_2023-04-21_76EDPH_2600MM_B_180s_mono_WBPP.xisf",
    "masterLight_BIN-1_6248x4176_EXPOSURE-25.00s_FILTER-R_mono_drizzle_2x_autocrop.xisf",
    # obraz pełnokolorowy - kanałem nie jest
    "masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter_RGB.xisf",
    "masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter_combined_RGB.xisf",
    "LMC_2023-03-23_105mm_A7R3_NoFilter_121s_RGB_drizzle_1x.xisf",
    # litera po ekspozycji, a dalej świadek złożenia - pełny kolor, nie kanał
    "NGC3034_2022-04-22_RC8_2600MC_NoFilter_600s_R_combined_RGB.xisf",
    # light i śmieci
    "CTB1_20250823_201114_LIGHT_OIII_900s_FLATGRP_202508230_.fits", "", None,
])
def test_brak_kanalu_w_nazwie(nazwa):
    assert channel_from_name(nazwa) is None


def test_kanal_klatki_z_wielu_kopii():
    """Kopie milczące nie głosują; kopie sprzeczne dają `None` - nie wybór jednej z nich."""
    stara = "masterLight_BIN-1_4144x2822_EXPOSURE-60.00s_FILTER-NoFilter_B.xisf"
    nowa = "NGC1976_2021-11-10_ED120R_294MC_NoFilter_60s_B.xisf"
    assert frame_channel([stara, nowa]) == "B"
    assert frame_channel([nowa, "kopia_bez_konwencji.xisf"]) == "B"
    assert frame_channel([nowa, "NGC1976_2021-11-10_ED120R_294MC_NoFilter_60s_R.xisf"]) is None
    assert frame_channel([]) is None


def test_slownik_kanalu_rowny_CHECK_migracji():
    """Lustro `CHANNELS` ↔ CHECK 0028 - dwie listy jednego faktu rozjechałyby się przy pierwszej
    zmianie jednej z nich."""
    sql = resources.files("horreum.schema.migrations").joinpath(
        "0028_frame_channel.sql").read_text(encoding="utf-8")
    w_ddl = re.search(r"channel IN \(([^)]*)\)", sql).group(1)
    assert tuple(re.findall(r"'([^']+)'", w_ddl)) == CHANNELS


# ═════════════════════════ schemat, klinga, resolver


def _baza(tmp_path):
    return db.open_db(str(tmp_path / "kanal.db"))


def _klatka(con, fid, kind, *sciezki, present=1):
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
                (fid, f"d{fid}", kind, "xisf", NOW))
    con.execute("INSERT INTO header (frame_id, raw_json) VALUES (?, '{}')", (fid,))
    for p in sciezki:
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
                    (fid, "V", p, present))


def test_migracja_dodaje_kolumne_ze_slownikiem(tmp_path):
    """0028 to PRZYROST: kolumna wchodzi pusta, CHECK odrzuca wartość spoza R/G/B."""
    import sqlite3
    con = _baza(tmp_path)
    assert db._user_version(con) >= 28
    _klatka(con, 1, "master_light")
    con.commit()
    assert con.execute("SELECT channel FROM frame WHERE id = 1").fetchone()[0] is None
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE frame SET channel = 'X' WHERE id = 1")
    con.close()


def test_migracja_0028_na_bazie_v27_nie_rusza_wierszy(tmp_path):
    """Baza zatrzymana na v27 z klatką przechodzi 0028 bez utraty wiersza; kanał zostaje NULL do
    przebiegu resolvera (SQL nie zna reguły nazwy)."""
    sciezka = str(tmp_path / "v27.db")
    con = db.connect(sciezka)
    for wersja, plik in db.MIGRATIONS:
        if wersja > 27:
            break
        db._apply_migration(con, wersja, db._migration_sql(plik))
    _klatka(con, 1, "master_light", "/st/x_60s_B.xisf")
    con.commit()
    assert db.migrate(con) == db.SCHEMA_VERSION
    assert [tuple(r) for r in con.execute("SELECT id, channel FROM frame")] == [(1, None)]
    con.close()


def test_klinga_zbiorczo_idempotentnie_jeden_event(tmp_path):
    con = _baza(tmp_path)
    for fid in (1, 2, 3):
        _klatka(con, fid, "master_light")
    con.commit()
    assert repo.backfill_frame_channel(con, [(1, "R"), (2, "G"), (3, None)], now=NOW) == 2
    assert repo.backfill_frame_channel(con, [(1, "R"), (2, "G"), (3, None)], now=NOW) == 0
    ev = con.execute("SELECT payload FROM event WHERE verb = 'channel.backfilled'").fetchall()
    assert len(ev) == 1, "zero zmian = zero eventu (kanon `filter.backfilled`)"
    assert json.loads(ev[0][0]) == {"count": 2, "changes": [[1, None, "R"], [2, None, "G"]]}
    # przeliczenie w drugą stronę: kopia bez kanału zdejmuje fakt, dziennik pamięta stan PRZED
    assert repo.backfill_frame_channel(con, [(1, None)], now=NOW) == 1
    ostatni = con.execute("SELECT payload FROM event WHERE verb = 'channel.backfilled' "
                          "ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert json.loads(ostatni)["changes"] == [[1, "R", None]]
    with pytest.raises(ValueError):
        repo.backfill_frame_channel(con, [(2, "X")], now=NOW)
    assert con.execute("SELECT channel FROM frame WHERE id = 2").fetchone()[0] == "G"
    con.close()


def test_resolver_liczy_kanal_z_nazw_kopii_bez_odczytu_plikow(tmp_path):
    """Pliki nie istnieją na dysku - pochodna liczy się z `location.path`. Kopia nieobecna też
    głosuje (stary plik WBPP po przenosinach mówi to samo, co jego kopia w archiwum stosów).
    Zakres = `master_light`: light z literą w nazwie kanału nie dostaje, mono i RGB też nie."""
    con = _baza(tmp_path)
    _klatka(con, 1, "master_light", "/st/NGC1976_2021-11-10_ED120R_294MC_NoFilter_60s_B.xisf")
    _klatka(con, 2, "master_light",
            "/old/masterLight_BIN-1_8000x5320_EXPOSURE-121.00s_FILTER-NoFilter__G.xisf", present=0)
    _klatka(con, 3, "master_light", "/st/NGC3034_2023-04-21_76EDPH_2600MM_B_180s_mono_WBPP.xisf")
    _klatka(con, 4, "master_light", "/st/IC5068_2023-08-21_76EDPH_2600MC_NoFilter_60s_RGB.xisf")
    _klatka(con, 5, "light", "/l/M42_60s_B.fits")
    con.commit()
    s = run_resolver(con, now=NOW)
    assert (s.channels_known, s.channels_changed) == (2, 2)
    assert dict(con.execute("SELECT id, channel FROM frame ORDER BY id").fetchall()) == {
        1: "B", 2: "G", 3: None, 4: None, 5: None}
    # idempotencja: drugi przebieg nic nie pisze
    ev = con.execute("SELECT count(*) FROM event WHERE verb = 'channel.backfilled'").fetchone()[0]
    assert derive_channels(con, NOW) == (2, 0)
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'channel.backfilled'"
                       ).fetchone()[0] == ev == 1
    con.close()


def test_kamera_mono_nie_dostaje_kanalu_nawet_z_nazwa_w_konwencji(tmp_path):
    """Reguła pozycyjna nie wie, czy kamera ma kanały koloru - wie to `camera.is_mono`. Stos mono
    nazwany po kolorowemu (`FILTER-H__R`) nie może skłamać na facecie „Kanał R"."""
    con = _baza(tmp_path)
    mono, _ = repo.upsert_camera(con, model_canon="2600MM", pixel_um=3.76, is_mono=1,
                                 is_mono_source="model", raw_instrume="ZWO ASI2600MM Pro", now=NOW)
    _klatka(con, 1, "master_light", "/st/masterLight_EXPOSURE-180.00s_FILTER-H__R.xisf")
    con.execute("UPDATE frame SET camera_id = ? WHERE id = 1", (mono,))
    con.commit()
    assert channel_from_name("masterLight_EXPOSURE-180.00s_FILTER-H__R.xisf") == "R"
    assert derive_channels(con, NOW) == (0, 0)
    assert con.execute("SELECT channel FROM frame WHERE id = 1").fetchone()[0] is None
    con.close()


# ═════════════════════════ facet „Kanał"


def _run(con, tree):
    return filter_engine.run(
        tree, leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(con, k, kw, p1, p2),
        universe_fn=lambda: queries.all_frame_ids(con))


def test_facet_kanal_filtruje_i_liczy(tmp_path):
    """„Pokaż kanał B": liść relacyjny po `frame.channel`, kubełki bez NULL w stałym porządku R, G,
    B; wykluczenie zostawia klatki bez kanału (algebra zbiorów, jak ⊖ nocy)."""
    con = _baza(tmp_path)
    for fid, kanal in ((1, "B"), (2, "G"), (3, "B"), (4, "R"), (5, None)):
        _klatka(con, fid, "master_light")
        if kanal:
            repo.backfill_frame_channel(con, [(fid, kanal)], now=NOW)
    con.commit()
    assert "channel" in facet_model.FACETS
    assert _run(con, {"facet": "channel", "value": "B"}) == {1, 3}
    stan = facet_model.cycle(facet_model.empty_state(), "channel", "B", "B")
    assert _run(con, facet_model.compose(stan, None)) == {1, 3}
    stan = facet_model.cycle(stan, "channel", "B", "B")                       # in → ex
    assert _run(con, facet_model.compose(stan, None)) == {2, 4, 5}
    assert [tuple(r) for r in queries.facet_channels(con, [1, 2, 3, 4, 5])] == [
        ("R", 1), ("G", 1), ("B", 2)]
    assert filter_engine.describe({"facet": "channel", "value": "B", "label": "B"}) == "Kanał: B"
    con.close()


# ═════════════════════════ grupy wersji stosów


SYG = "process=ImageIntegration,version=1.7.1,timestamp=2022-04-22T{:02d}:00:00.000Z"
OKNO = ("2022-04-21T20:00:00", "2022-04-22T03:00:00")


def _stos(con, fid, kanal, szum):
    """Stos kamery kolorowej z jednego okna - pomiar JEDNEGO kanału (`NOISE00`), więc sam nagłówek
    nie mówi, który to kanał."""
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at, camera_id, "
                "object_id, config_id, channel) VALUES (?,?,?,?,?,?,?,?,?)",
                (fid, f"d{fid}", "master_light", "xisf", NOW, 1, 1, 1, kanal))
    con.execute("INSERT INTO header (frame_id, raw_json, exptime) VALUES (?,?,?)",
                (fid, json.dumps({"NOISE00": f"{szum:.4e}", "DATE-OBS": OKNO[0],
                                  "DATE-END": OKNO[1]}), 600.0))
    con.execute("INSERT INTO integration (master_frame_id, created_at, tool, window_start, "
                "window_end) VALUES (?,?,?,?,?)", (fid, NOW, SYG.format(fid), *OKNO))
    con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,1)",
                (fid, "V", f"/st/{fid}.xisf"))


@pytest.fixture
def kolor(tmp_path):
    """NGC3034 RC8 600 s (zmierzone na archiwum): trzy kanały przebiegu `WBPP` i trzy kanały
    przebiegu `WBPP2` z tego samego okna, plus `combined_RGB` (bez kanału), który dziedziczy
    pomiary kanału `R` pierwszego przebiegu znak w znak."""
    con = _baza(tmp_path)
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES (1, 'ASI2600MC', 0, ?)",
                (NOW,))
    con.execute("INSERT INTO telescope (id, telescop_canon, status, created_at) "
                "VALUES (1, 'RC8', 'approved', ?)", (NOW,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) "
                "VALUES (1, 1, 1, 'approved', ?)", (NOW,))
    con.execute("INSERT INTO object (id, canon) VALUES (1, 'NGC3034')")
    for i, kanal in enumerate("RGB"):
        _stos(con, 11 + i, kanal, 1e-4 * (i + 1))         # przebieg WBPP
        _stos(con, 21 + i, kanal, 5e-4 * (i + 1))         # przebieg WBPP2
    _stos(con, 10, None, 1e-4)                            # combined_RGB = pomiary kanału R (11)
    con.commit()
    yield con
    con.close()


def test_druga_integracja_tego_samego_kanalu_wychodzi_na_wersje(kolor):
    """Do 0028 pomiar pojedynczego kanału nie mówił, KTÓRY to kanał, więc żadna para kamery
    kolorowej nie miała wspólnego kanału i dowodu odrębności: druga integracja kanału ginęła
    w grupie „pochodna/nieustalone" i nie trafiała na listę roboty. Z kanałem para `R`+`R` ma
    wspólny kanał, różne sygnatury i pomiary - to dwie integracje. Pary RÓŻNYCH kanałów zostają
    bez dowodu, a pochodna (`combined_RGB` ↔ `R`) zachowuje świadka.
    Falsyfikator: zdejmij gałąź `kanal` z `_ten_sam_kanal` - grupa wraca do „pochodna"."""
    grupy = queries.stack_version_groups(kolor)
    assert len(grupy) == 1 and grupy[0]["kind"] == queries.WERSJA_INNA
    rodzaje = {m["frame_id"]: (m["kind"], m["witness"]) for m in grupy[0]["members"]}
    for fid in (11, 12, 13, 21, 22, 23):
        assert rodzaje[fid] == (queries.WERSJA_INNA, queries.SWIADEK_SYGNATURA), fid
    assert rodzaje[10] == (queries.WERSJA_POCHODNA, queries.SWIADEK_TE_SAME_POMIARY)
    assert queries.stack_version_frame_ids(kolor) == {10, 11, 12, 13, 21, 22, 23}
    # gest „Zostaw tę wersję" podsuwa WYŁĄCZNIE drugą integrację TEGO SAMEGO kanału; inne kanały
    # idą do „bez dowodu", pochodna zostawianej wersji - do „pochodnych"
    assert queries.keep_version_plan(kolor, 11) == {
        "paths": ["/st/21.xisf"], "stacks": 1, "derived": 1, "unknown": 4, "kept": False}


def test_bez_kanalu_grupa_jak_przed_0028(kolor):
    """Klatki bez kanału (mono, pełnokolorowe, baza przed przebiegiem resolvera): klucz,
    identyfikator i klasyfikacja grupy jak przed 0028 - kanał nie stoi w kluczu, więc grupy,
    werdykty „zostawiam wszystkie" i świadkowie pochodzenia nie przeskakują."""
    kolor.execute("UPDATE frame SET channel = NULL")
    kolor.commit()
    grupy = queries.stack_version_groups(kolor)
    assert len(grupy) == 1 and grupy[0]["kind"] == queries.WERSJA_POCHODNA
    assert grupy[0]["group_id"].count("|") == 6, "siedem członów klucza, jak przed 0028"
    assert queries.stack_version_frame_ids(kolor) == set()
