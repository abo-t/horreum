"""Read-model raportu „co przyszło” (`queries.delivery_report`, `queries.flat_states`) - Qt-wolny.

Raport liczy klatki dostawy ze STANU bazy od znacznika `since` przebiegu, a populacje „nie
rozpoznałem” mają być ZNAK W ZNAK kubełkami Porządków zawężonymi do dostawy - predykaty są
powtórzone po stronie Pythona, więc równość z drążeniami pinują testy tutaj. Kalibracja nowych
lightów idzie wspólną derywacją z teczkami wydania (`flat_states`). Baza syntetyczna bez plików:
read-model pyta o flagę `present`, nie o dysk."""
import pytest

from horreum import db
from horreum.gui import queries
from horreum.lineage import RawFlatPick

STARE = "2026-10-01T10:00:00+00:00"       # archiwum sprzed dostawy
SINCE = "2026-10-10T12:00:00+00:00"       # start przebiegu (zegar okna)
NOWE = "2026-10-10T12:00:05+00:00"        # `first_seen_at` klatek tej dostawy
UNTIL = "2026-10-10T12:30:00+00:00"       # koniec przebiegu
PO = "2026-10-10T13:00:00+00:00"          # klatka NASTĘPNEGO przebiegu (droga „Stosy”)
PLAMA = "Plama Zdzicha"


def _baza(tmp_path):
    """Jedna nastawa (A140R x ASI2600MM, config 10), master flat Ha i master dark w archiwum, dwa
    surowe flaty OIII z nocy 2024-03-01; dostawa niesie lighty o czterech stanach flatu, nazwę
    spoza katalogu (lighty, stos, nagrobek), trzy kubełki bez nazwy, klatki nieaktywne i klatkę
    następnego przebiegu. Zwraca (con, ids)."""
    from horreum.calibration import run_calibration

    con = db.open_db(str(tmp_path / "dostawa.db"))
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES "
                "(1, 'ASI2600MM', 1, ?)", (STARE,))
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) VALUES "
                "(1, 'A140R', NULL, 'proposed', ?)", (STARE,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES "
                "(10, 1, 1, 'proposed', ?)", (STARE,))
    con.execute("INSERT INTO object (id, canon) VALUES (1, 'IC1795'), (2, 'NGC7000')")
    ids = {}

    def k(name, *, kind, seen=NOWE, object_id=None, filtr=None, filetype="fits", raw=None,
          source=None, header=True, date_obs="2024-03-01T23:00:00", exptime=300.0):
        fid = con.execute(
            "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_id, "
            "object_source, filter_canon, first_seen_at) VALUES (?, ?, ?, 1, 10, ?, ?, ?, ?)",
            (name, kind, filetype, object_id, source, filtr, seen)).lastrowid
        if header:
            con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning, "
                        "object_raw) VALUES (?, '{}', ?, ?, 1, ?)", (fid, date_obs, exptime, raw))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, f"X:\\lib\\{name}.fits"))
        ids[name] = fid

    # archiwum
    k("md", kind="master_dark", seen=STARE)
    k("mf", kind="master_flat", filtr="Ha", seen=STARE)
    k("f1", kind="flat", filtr="OIII", seen=STARE, date_obs="2024-03-02T05:30:00")
    k("f2", kind="flat", filtr="OIII", seen=STARE, date_obs="2024-03-02T05:31:00")
    k("stara_plama", kind="light", raw=PLAMA, seen=STARE)                  # liczy się do `total`
    k("stara_plama_nagrobek", kind="light", raw=PLAMA, seen=STARE, source="user_cleared")
    k("granica_przed", kind="light", object_id=1, filtr="Ha", seen="2026-10-10T11:59:59+00:00")
    # dostawa
    k("granica", kind="light", object_id=1, filtr="Ha", seen=SINCE, exptime=600.0)
    k("g2", kind="light", object_id=1, filtr="Ha", exptime=600.0)
    k("a_surowy", kind="light", object_id=2, filtr="OIII")
    k("a_bez", kind="light", object_id=2, filtr="SII")
    k("a_pending", kind="light", object_id=2, filtr="Ha")
    k("u1", kind="light", raw=PLAMA)
    k("u2", kind="light", raw=PLAMA)
    k("u_stos", kind="master_light", raw=PLAMA)
    k("u_nagrobek", kind="light", raw=PLAMA, source="user_cleared")
    k("mur", kind="light", raw="Mur")
    k("n1", kind="light")
    k("n_raw", kind="light", filetype="raw")
    k("n_stos", kind="master_light")
    k("bez_naglowka", kind="light", header=False)
    k("nowy_flat", kind="flat", filtr="L", date_obs="2024-03-05T05:00:00")
    k("nowy_mf", kind="master_flat", filtr="L", date_obs="2024-03-05T05:00:00")
    k("nowy_unknown", kind="unknown")
    k("wycofany", kind="light", object_id=1, filtr="Ha", exptime=9000.0)
    k("zastapiony", kind="light", object_id=1, filtr="Ha", exptime=9000.0)
    k("nastepny", kind="light", object_id=2, filtr="OIII", seen=PO)
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOWE, ids["wycofany"]))
    con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (ids["g2"], ids["zastapiony"]))
    con.commit()
    run_calibration(con, now=STARE)               # profile: surowe OIII i L, mastery Ha i L
    for light in ("granica", "g2"):
        for master, rel in (("mf", "flat"), ("md", "dark")):
            con.execute("INSERT INTO calibration (light_frame_id, master_frame_id, relation, "
                        "asserted_by, confidence) VALUES (?, ?, ?, 'horreum', 'recipe')",
                        (ids[light], ids[master], rel))
    con.commit()
    return con, ids


def _dostawa(con, ids, since=SINCE, until=UNTIL):
    """Id klatek dostawy wg definicji raportu - do porównań z drążeniami Porządków."""
    return {fid for (fid,) in con.execute(
        "SELECT id FROM frame WHERE first_seen_at >= ? AND first_seen_at <= ? "
        "AND retired_at IS NULL AND superseded_by IS NULL", (since, until))}


def test_granica_okna_since_i_until(tmp_path):
    """Dolna granica włącznie (klatka ze znacznikiem równym `since` jest w dostawie, sekundę
    wcześniej - nie); górna `until` odcina klatkę następnego przebiegu, a `until=None` jej nie
    odcina. Wycofana i zastąpiona nie liczą się nigdzie."""
    con, ids = _baza(tmp_path)
    r = queries.delivery_report(con, SINCE, until=UNTIL)
    assert r["frames"] == 17
    assert r["by_kind"] == {"light": 12, "master_light": 2, "flat": 1, "master_flat": 1,
                            "unknown": 1}
    otwarte = queries.delivery_report(con, SINCE)
    assert otwarte["frames"] == 18 and otwarte["by_kind"]["light"] == 13      # + „nastepny”
    assert r["frames"] == len(_dostawa(con, ids))
    con.close()


def test_rodzaje_mastery_stosy_i_godziny(tmp_path):
    """Lighty, godziny lightów (exptime), mastery flat/dark i stosy ze stanu - jedno źródło
    dla nagłówka i jego rozbicia."""
    con, _ids = _baza(tmp_path)
    r = queries.delivery_report(con, SINCE, until=UNTIL)
    assert r["lights"] == 12
    assert r["hours"] == pytest.approx((2 * 600 + 9 * 300) / 3600)      # bez nagłówka = bez czasu
    assert r["masters"] == {"flat": 1, "dark": 0}
    assert r["stacks"] == 2
    con.close()


def test_obiekty_z_godzinami_malejaco(tmp_path):
    """Obiekty nowych lightów z liczbą i godzinami, GODZINAMI malejąco: IC1795 ma mniej klatek,
    ale więcej godzin, więc stoi pierwszy. Lighty bez obiektu i klatki nieaktywne nie wchodzą."""
    con, _ids = _baza(tmp_path)
    r = queries.delivery_report(con, SINCE, until=UNTIL)
    assert r["objects"] == [("IC1795", 2, pytest.approx(1200 / 3600)),
                            ("NGC7000", 3, pytest.approx(900 / 3600))]
    con.close()


def test_nierozpoznane_z_total_i_nagrobkiem_poza(tmp_path):
    """Nazwa spoza katalogu: `n` = lighty i stosy tej dostawy, `total` = cała populacja gestu
    w archiwum (z klatką sprzed dostawy). Klatka z nagrobkiem nie liczy się ani tu, ani tam.
    Kolejność: n malejąco. Falsyfikator: zdejmij warunek nagrobka → n=4, total=6."""
    con, ids = _baza(tmp_path)
    r = queries.delivery_report(con, SINCE, until=UNTIL)
    assert r["unresolved"] == [(PLAMA, 3, 4), ("Mur", 1, 1)]
    dostawa = _dostawa(con, ids)
    for raw, n, total in r["unresolved"]:
        populacja = {row["frame_id"] for row in queries.object_review_frames(con, raw)}
        assert total == len(populacja), raw                     # ta sama populacja, co gest
        assert n == len(populacja & dostawa), raw
    con.close()


def test_bezimienne_trzech_rodzajow_rowne_drazeniom_porzadkow(tmp_path):
    """Trzy kubełki bez nazwy - te same predykaty, co drążenia Porządków (wariant bez nagrobka),
    zawężone do dostawy. Klatka bez wiersza `header` nie należy do żadnego (drążenia idą JOIN)."""
    con, ids = _baza(tmp_path)
    r = queries.delivery_report(con, SINCE, until=UNTIL)
    assert (r["nameless"], r["nameless_raw"], r["nameless_stacks"]) == (1, 1, 1)
    dostawa = _dostawa(con, ids)
    for pole, drazenie in (("nameless", queries.nameless_frames),
                           ("nameless_raw", queries.nameless_raw_frames),
                           ("nameless_stacks", queries.nameless_stack_frames)):
        assert r[pole] == len({row["frame_id"] for row in drazenie(con)} & dostawa), pole
    con.close()


def test_odpiete_reka_liczone_osobno_rowne_polowkom_cofnietym(tmp_path):
    """Light i stos dostawy bez obiektu Z DECYZJI RĘKI (nagrobek „Cofnij przypisanie”) nie wracają
    do kolejki napraw, ale raport liczy je osobno (`cleared`) - inaczej ogłosiłby „Wszystko
    rozpoznane” nad klatką, której obiekt człowiek zdjął. Populacja = suma połówek „cofnięte”
    kubełków Porządków, zawężona do dostawy; nagrobek sprzed dostawy się nie liczy."""
    con, ids = _baza(tmp_path)
    fid = con.execute(
        "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_source, "
        "first_seen_at) VALUES ('stos_nagrobek', 'master_light', 'xisf', 1, 10, 'user_cleared', ?)",
        (NOWE,)).lastrowid
    con.execute("INSERT INTO header (frame_id, raw_json) VALUES (?, '{}')", (fid,))
    con.commit()
    r = queries.delivery_report(con, SINCE, until=UNTIL)
    assert r["cleared"] == 2                                   # light z nazwą + stos bez nazwy
    polowki = set()
    for (raw,) in con.execute("SELECT DISTINCT object_raw FROM header WHERE object_raw IS NOT NULL"):
        polowki |= {row["frame_id"] for row in queries.object_review_frames(con, raw, cleared=True)}
    for drazenie in (queries.nameless_frames, queries.nameless_raw_frames,
                     queries.nameless_stack_frames):
        polowki |= {row["frame_id"] for row in drazenie(con, cleared=True)}
    assert r["cleared"] == len(polowki & _dostawa(con, ids))
    assert r["unresolved"] == [(PLAMA, 3, 4), ("Mur", 1, 1)] and r["nameless_stacks"] == 1
    con.close()


def test_kalibracja_nowych_lightow(tmp_path):
    """Kalibracja dla NOWYCH lightów: master flat ze stanu `calibration` (dwa), surowy flat
    i „do przeliczenia” z `lineage.raw_flats_for` (po jednym), reszta bez flatu; dark ze stanu."""
    con, _ids = _baza(tmp_path)
    c = queries.delivery_report(con, SINCE, until=UNTIL)["cal"]
    assert c == {"master_flat": 2, "raw_flat": 1, "pending": 1, "no_flat": 8,
                 "master_dark": 2, "no_dark": 10}
    con.close()


def test_kalibracja_ta_sama_derywacja_co_teczki_wydania(tmp_path):
    """Szew dwóch powierzchni jednego dnia: lighty z obiektem są w tej bazie WYŁĄCZNIE nowe, więc
    sumy teczek wydania po stanach flatu i darka muszą się równać kalibracji raportu policzonej
    na tych samych lightach. Rozjazd = dwie derywacje jednego faktu."""
    con, ids = _baza(tmp_path)
    for poza in ("granica_przed", "nastepny"):       # lighty z obiektem spoza okna dostawy
        con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOWE, ids[poza]))
    con.execute("DELETE FROM header WHERE frame_id IN (SELECT id FROM frame WHERE object_id IS NULL "
                "AND kind = 'light')")
    con.execute("UPDATE frame SET kind = 'unknown' WHERE object_id IS NULL AND kind = 'light'")
    con.commit()
    c = queries.delivery_report(con, SINCE, until=UNTIL)["cal"]
    teczki = queries.release_readiness(con)
    assert c["master_flat"] == sum(t["n_master_flat"] for t in teczki) == 2
    assert c["raw_flat"] == sum(t["n_raw_flat"] for t in teczki) == 1
    assert c["pending"] == sum(t["n_pending"] for t in teczki) == 1
    assert c["master_dark"] == sum(t["n_master_dark"] for t in teczki) == 2
    assert sum(c[k] for k in ("master_flat", "raw_flat", "pending", "no_flat")) \
        == sum(t["lights"] for t in teczki) == 5
    con.close()


def test_pusta_dostawa(tmp_path):
    """Przebieg, który nic nie przyniósł: same zera i puste listy - nie wyjątek i nie archiwum."""
    con, _ids = _baza(tmp_path)
    r = queries.delivery_report(con, "2026-10-11T00:00:00+00:00")
    assert (r["frames"], r["lights"], r["hours"], r["stacks"]) == (0, 0, 0.0, 0)
    assert r["by_kind"] == {} and r["objects"] == [] and r["unresolved"] == []
    assert (r["nameless"], r["nameless_raw"], r["nameless_stacks"], r["cleared"]) == (0, 0, 0, 0)
    assert set(r["cal"].values()) == {0} and r["masters"] == {"flat": 0, "dark": 0}
    con.close()


def test_flat_states_klasyfikuje_jak_teczki(monkeypatch):
    """Stan flatu lightu: master ze stanu bije wszystko; bez mastera surowe flaty → `raw`, luka
    `pending` → `pending`, każda inna luka i brak wyboru → `none`. `raw_flats_for` dostaje
    WYŁĄCZNIE lighty bez mastera (jedno wywołanie)."""
    wolane = []

    def picks(_con, light_ids, *, window_days):
        wolane.append((sorted(light_ids), window_days))
        return {2: RawFlatPick((7, 8), 5, "2024-03-01", 0, None),
                3: RawFlatPick((), 5, None, None, "pending"),
                4: RawFlatPick((), 5, "2024-01-01", 60, "out_of_window")}

    monkeypatch.setattr(queries, "raw_flats_for", picks)
    rows = [{"frame_id": i, "master_flat": i == 1} for i in (1, 2, 3, 4, 5)]
    assert queries.flat_states(None, rows, window_days=30) == {
        1: queries.FLAT_MASTER, 2: queries.FLAT_RAW, 3: queries.FLAT_PENDING,
        4: queries.FLAT_NONE, 5: queries.FLAT_NONE}
    assert wolane == [([2, 3, 4, 5], 30)]
