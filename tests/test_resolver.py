"""Resolver obiektu + filtra — integracja po skanie (§Etap 6).

SEDNO (firsthand-korekta): OBIEKT jest KIND-AWARE. Kalibracja (flat) z OBJECT='FlatWizard' →
object_id=NULL bez review (poprawny stan — flat nie ma obiektu z definicji). Tylko light/master_light
trafiają do delty. FILTR jest kind-AGNOSTYCZNY (flat też ma filtr → filter_canon ustawiony)."""
import numpy as np
from astropy.io import fits

from horreum import db, repo
from horreum.grouper import run_grouper
from horreum.resolver import delta_report, run_resolver
from horreum.scan import scan_tree

NOW = "2026-06-28T12:00:00"


def _fits(path, cards, n=0):
    """`n` różnicuje PIKSELE — po PF-2 tożsamość = sha1_data, więc identyczne dane zlałyby
    osobne klatki w jeden frame (multi-location)."""
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    for kw, val in cards:
        hdu.header[kw] = val
    fits.HDUList([hdu]).writeto(str(path))
    return path


def _scanned_tree(tmp_path):
    """4 light'y (NGC4258, M106→NGC4258, Rosette→NGC2237, Snapshot=delta) + 1 flat (FlatWizard).
    Wszystkie ASI2600MM. Zwraca otwarte połączenie po skanie."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    _fits(tree / "l1.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "NGC 4258"), ("FILTER", "Ha")], n=1)
    _fits(tree / "l2.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "M106"), ("FILTER", "Ha")], n=2)
    _fits(tree / "l3.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "Rosette Nebula"), ("FILTER", "OIII")], n=3)
    _fits(tree / "l4.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "Snapshot"), ("FILTER", "L")], n=4)
    _fits(tree / "flat.fits", cam + [("IMAGETYP", "FLAT"), ("OBJECT", "FlatWizard"), ("FILTER", "Ha")], n=5)
    scan_tree(con, tree, now=NOW)
    return con


def test_kalibracja_nie_idzie_do_review_ale_lights_tak(tmp_path):
    """SEDNO: flat 'FlatWizard' → object_id=NULL bez żadnego review; tylko light 'Snapshot' = delta.
    Bez kind-awareness FlatWizard byłby fałszywym 'nierozwiązanym'."""
    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)
    # flat: object_id NULL, ale NIE w review (poprawny stan kalibracji)
    flat_obj = con.execute("SELECT object_id FROM frame WHERE kind='flat'").fetchone()["object_id"]
    assert flat_obj is None
    # jedyny kanał delty obiektu = zbiorczy summary; per-frame object.review NIE istnieje
    assert con.execute("SELECT count(*) FROM event WHERE verb='object.review'").fetchone()[0] == 0
    summ = con.execute("SELECT payload FROM event WHERE verb='object.review_summary'").fetchall()
    assert len(summ) == 1
    import json
    items = {raw for raw, _ in json.loads(summ[0]["payload"])["items"]}
    assert items == {"Snapshot"}                       # FlatWizard NIE jest w delcie
    con.close()


def test_lights_rozwiazane_i_xref_scala_obiekt(tmp_path):
    """NGC4258 (header) i M106 (catalog_xref) → JEDEN obiekt; Rosette (common_name) → drugi.
    3 light'y przypisane, 2 obiekty, alias zachowuje formy surowe."""
    con = _scanned_tree(tmp_path)
    s = run_resolver(con, now=NOW)
    assert (s.objects_new, s.objects_assigned, s.objects_review) == (2, 3, 1)
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 2
    # M106 i NGC 4258 → ten sam object_id (xref NGC-wins)
    ids = [r[0] for r in con.execute(
        "SELECT f.object_id FROM frame f JOIN header h ON h.frame_id=f.id "
        "WHERE h.object_raw IN ('M106','NGC 4258')")]
    assert len(ids) == 2 and ids[0] == ids[1] is not None
    # object_source rozróżnia ścieżkę rozwiązania
    src = {r["object_raw"]: r["object_source"] for r in con.execute(
        "SELECT h.object_raw, f.object_source FROM frame f JOIN header h ON h.frame_id=f.id "
        "WHERE f.object_source IS NOT NULL")}
    assert src == {"NGC 4258": "header", "M106": "catalog_xref", "Rosette Nebula": "common_name"}
    # alias: NGC4258 ma dwa (NGC4258 header + M106 catalog_xref)
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 3
    con.close()


def test_filter_kind_agnostyczny_takze_flat(tmp_path):
    """FILTR ustawiany dla WSZYSTKICH kind (flat też ma filtr): 5 frame'ów → 5 filter_canon."""
    con = _scanned_tree(tmp_path)
    s = run_resolver(con, now=NOW)
    assert s.filters_set == 5
    assert con.execute("SELECT filter_canon FROM frame WHERE kind='flat'").fetchone()[0] == "Ha"
    canons = sorted(r[0] for r in con.execute("SELECT filter_canon FROM frame"))
    assert canons == ["Ha", "Ha", "Ha", "L", "OIII"]   # l1/l2/flat=Ha, l3=OIII, l4=L
    # jeden zbiorczy event filter.backfilled (nie per-frame)
    assert con.execute("SELECT count(*) FROM event WHERE verb='filter.backfilled'").fetchone()[0] == 1
    con.close()


def test_filter_backfill_nie_mnozy_eventow_przy_powtornym_resolve(tmp_path):
    """D-0722-1 (zmierzone na `horreum_pf4.db`: 7× identyczny `count: 12582` przy zerze zmian):
    powtórny `run_resolver` bez nowych plików NIE dokłada eventu `filter.backfilled`. `filters_set`
    ZOSTAJE 5 — to licznik STANU (frame'y z niepustym kanonem), nie skutku przebiegu; te dwie
    liczby są różnymi faktami i test trzyma oba końce."""
    con = _scanned_tree(tmp_path)
    assert run_resolver(con, now=NOW).filters_set == 5
    ev1 = con.execute("SELECT count(*) FROM event WHERE verb='filter.backfilled'").fetchone()[0]

    assert run_resolver(con, now=NOW).filters_set == 5      # stan bez zmian
    ev2 = con.execute("SELECT count(*) FROM event WHERE verb='filter.backfilled'").fetchone()[0]
    assert (ev1, ev2) == (1, 1)                             # dziennik bez szumu
    con.close()


def test_delta_report_procent_na_lightach(tmp_path):
    """% obiektu liczone NA light/master_light (kalibracja nie zaniża): 3/4 = 75%, delta=Snapshot."""
    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)
    rep = delta_report(con)
    assert (rep.object_resolved, rep.object_unresolved, rep.object_pct) == (3, 1, 75.0)
    assert rep.object_delta == [("Snapshot", 1)]       # FlatWizard NIE w delcie
    assert rep.filters_canon == 5
    con.close()


# --- kolejka przeglądu ze STANU, nie ze zliczania eventów (#12) ---

def test_review_ze_stanu_nie_rosnie_przy_powtornej_dostawie(tmp_path):
    """SEDNO #12: `flag_config_review` emituje BEZWARUNKOWO co przebieg, więc `count(event)` rósł
    liniowo przy powtórnej dostawie bez żadnej realnej zmiany. Ten test trzyma OBA końce: eventy
    mnożą się (dowód, że licznik ich NIE liczy), a stan stoi w miejscu."""
    con = _scanned_tree(tmp_path)
    run_grouper(con, now=NOW)
    run_resolver(con, now=NOW)
    pierwszy = delta_report(con).review
    ev1 = con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0]

    run_grouper(con, now=NOW)                          # powtórna dostawa: ZERO nowych plików
    run_resolver(con, now=NOW)
    drugi = delta_report(con).review
    ev2 = con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0]

    assert ev1 > 0 and ev2 == 2 * ev1                  # eventy się MNOŻĄ — dawne źródło licznika
    assert drugi == pierwszy                           # stan jest idempotentny
    assert pierwszy.total == 5                         # drzewo bez TELESCOP: 5 klatek czeka na config
    con.close()


def test_review_kubelki_zachodza_a_total_jest_distinct(tmp_path):
    """Klatka bez INSTRUME nie ma kamery, więc grouper nie złoży jej configu — liczy się w OBU
    kubełkach. `total` to DISTINCT klatek, NIGDY suma pól (inaczej raport zawyżyłby kolejkę)."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    _fits(tree / "pelna.fits", [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                                ("TELESCOP", "A140R"), ("IMAGETYP", "LIGHT"), ("OBJECT", "M31")], n=1)
    _fits(tree / "bez_kamery.fits", [("TELESCOP", "A140R"), ("IMAGETYP", "LIGHT"),
                                     ("OBJECT", "M31")], n=2)
    scan_tree(con, tree, now=NOW)
    run_grouper(con, now=NOW)
    st = delta_report(con).review
    assert (st.no_camera, st.no_config) == (1, 1)      # TA SAMA klatka w obu kubełkach
    assert st.total == 1                               # distinct, nie 2
    con.close()


def test_review_rodzaj_nieznany_lapie_cichy_null(tmp_path):
    """Zeznanie JEST, IMAGETYP brak → event `kind.unmapped` NIE powstaje (wymagał NIEPUSTEGO
    IMAGETYP), a rodzaju i tak nie znamy. Świadome poszerzenie kontraktu #12: stan pokazuje to,
    co event przemilczał — zero cichego NULL."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    _fits(tree / "bez_imagetyp.fits", [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                                       ("TELESCOP", "A140R"), ("OBJECT", "M31")], n=1)
    scan_tree(con, tree, now=NOW)
    run_grouper(con, now=NOW)
    assert con.execute("SELECT count(*) FROM event WHERE verb='kind.unmapped'").fetchone()[0] == 0
    st = delta_report(con).review
    assert st.kind_unknown == 1 and st.headerless == 0  # rodzaj nieznany, ale zeznanie JEST
    assert st.total == 1
    con.close()


def test_review_unreadable_ze_stanu_i_total_distinct(tmp_path):
    """#13: kubełek `unreadable` liczy klatki z ≥1 kopią nieczytelną ZE STANU; `total` obejmuje taką
    klatkę (trzeci dyzjunkt) i NIE liczy jej podwójnie, gdy ta sama klatka jest już w innym kubełku
    (DISTINCT). Stan idempotentny: powtórna awaria bez zmiany mtime niczego nie zawyża."""
    from horreum import repo
    from horreum.resolver import review_state
    con = db.open_db(str(tmp_path / "h.db"))
    # light z zeznaniem, ale bez kamery i configu → kubełki no_camera + no_config (klatka już „w kolejce")
    fid, _ = repo.upsert_frame(con, sha1_data="d1", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw="M31", now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", path="x.fits", mtime="t1",
                               file_sha1="f1", now=NOW)
    st0 = review_state(con)
    assert (st0.unreadable, st0.no_config, st0.no_camera, st0.total) == (0, 1, 1, 1)
    # kopia staje się nieczytelna → marker w STANIE
    repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                     mtime="t2", reason="OSError", now=NOW)
    st1 = review_state(con)
    assert st1.unreadable == 1                          # kubełek liczy ze STANU
    assert (st1.no_config, st1.no_camera) == (1, 1)     # klatka nadal w tamtych kubełkach
    assert st1.total == 1                               # DISTINCT — ta sama klatka, nie 3
    # powtórna awaria (marker stoi, ten sam mtime) → stan stabilny (idempotencja)
    repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                     mtime="t2", reason="OSError", now=NOW)
    st2 = review_state(con)
    assert (st2.unreadable, st2.total) == (1, 1)
    con.close()


def test_review_unreadable_distinct_po_kopiach(tmp_path):
    """#13: klatka z DWIEMA nieczytelnymi kopiami liczy się w `unreadable` RAZ (count(DISTINCT f.id)) —
    marker to fakt o KOPII, ale kubełek zlicza po klatkach (spójność z resztą liczników)."""
    from horreum import repo
    from horreum.resolver import review_state
    con = db.open_db(str(tmp_path / "h.db"))
    fid, _ = repo.upsert_frame(con, sha1_data="d1", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    l1, _ = repo.add_location(con, frame_id=fid, volume="V1", path="a.fits", mtime="t1",
                              file_sha1="f1", now=NOW)
    l2, _ = repo.add_location(con, frame_id=fid, volume="V2", path="b.fits", mtime="t1",
                              file_sha1="f1", now=NOW)
    repo.refresh_location_unreadable(con, location_id=l1, sha1_data="d1", path="a.fits",
                                     mtime="t2", reason="e", now=NOW)
    repo.refresh_location_unreadable(con, location_id=l2, sha1_data="d1", path="b.fits",
                                     mtime="t2", reason="e", now=NOW)
    assert review_state(con).unreadable == 1            # DWIE kopie, JEDNA klatka
    con.close()


def test_review_no_config_kind_aware_kalibracja_poza_kolejka(tmp_path):
    """Kind-scoping config (wariant B, 2026-07-22): masterdark/bias z `config_id IS NULL` NIE jest
    deltą — nie ma osi teleskopu, więc NULL to stan docelowy. Light z tym samym brakiem JEST deltą.
    Predykat czerpie zbiór z `grouper.NO_TELESCOPE_KINDS` (jeden właściciel), więc kolejka GUI
    i raport dostawy nie mogą się rozjechać z osią."""
    from horreum import repo
    from horreum.resolver import review_state
    con = db.open_db(str(tmp_path / "h.db"))
    cam, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                is_mono_source="model", raw_instrume="ZWO ASI2600MM Pro", now=NOW)
    for i, kind in enumerate(("master_dark", "bias", "light")):
        fid, _ = repo.upsert_frame(con, sha1_data=f"d{i}", kind=kind, filetype="xisf",
                                   camera_id=cam, now=NOW)
        repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW)
    st = review_state(con)
    assert st.no_config == 1                            # TYLKO light; dark i bias poza kolejką
    assert (st.no_camera, st.headerless) == (0, 0)
    assert st.total == 1                                # `total` używa tego samego wyłączenia
    con.close()


def _solar_tree(tmp_path):
    """3 light'y solar/kometa (Jupiter, C/2023 A3, Lemmon) + 1 light prywatny (Mur, delta) +
    1 flat OBJECT='Moon' (kind-aware: kalibracja NIE dostaje obiektu). Wszystkie ASI2600MM."""
    con = db.open_db(str(tmp_path / "s.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    _fits(tree / "s1.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "Jupiter")], n=1)
    _fits(tree / "s2.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "C/2023 A3 (Tsuchinshan-ATLAS)")], n=2)
    _fits(tree / "s3.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "Lemmon")], n=3)
    _fits(tree / "s4.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "Mur")], n=4)
    _fits(tree / "flat.fits", cam + [("IMAGETYP", "FLAT"), ("OBJECT", "Moon")], n=5)
    scan_tree(con, tree, now=NOW)
    return con


def test_solar_komety_rozwiazane_kind_aware(tmp_path):
    """Krok 5a: Jupiter→ciało, C/2023 A3 i Lemmon→komety (2 różne); flat 'Moon'→NULL bez review
    (kind-aware); 'Mur' (prywatna) zostaje w delcie. 3 obiekty solar, flat NIE rozwiązany."""
    con = _solar_tree(tmp_path)
    s = run_resolver(con, now=NOW)
    # 3 light'y solar/kometa przypisane; 'Mur' = delta (1 review); flat pominięty
    assert s.objects_assigned == 3
    objs = {r["canon"]: r["kind"] for r in con.execute("SELECT canon, kind FROM object")}
    assert objs == {"Jupiter": "solar_system",
                    "C/2023 A3 (Tsuchinshan-ATLAS)": "comet",
                    "C/2025 A6 (Lemmon)": "comet"}
    # flat OBJECT='Moon' → object_id NULL, ale NIE w review (kalibracja nie ma obiektu)
    assert con.execute("SELECT object_id FROM frame WHERE kind='flat'").fetchone()[0] is None
    # delta = tylko 'Mur' (prywatna); solar/komety zeszły z delty
    rep = delta_report(con)
    assert rep.object_delta == [("Mur", 1)]
    assert rep.object_resolved == 3
    # object_source niesie ścieżkę solar/comet
    src = sorted({r[0] for r in con.execute(
        "SELECT object_source FROM frame WHERE object_source IS NOT NULL")})
    assert src == ["comet", "solar"]
    con.close()


def test_solar_idempotentny(tmp_path):
    """Drugi przebieg nie tworzy nowych obiektów solar ani nie przepina."""
    con = _solar_tree(tmp_path)
    run_resolver(con, now=NOW)
    s2 = run_resolver(con, now=NOW)
    assert (s2.objects_new, s2.objects_assigned) == (0, 0)
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 3
    con.close()


def test_resolver_idempotentny(tmp_path):
    """Drugi przebieg nie tworzy nowych obiektów/aliasów ani nie przepina (assign idempotentny)."""
    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)
    s2 = run_resolver(con, now=NOW)
    assert (s2.objects_new, s2.objects_assigned) == (0, 0)
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 3
    con.close()


# --- P4 (#8): szczebel ALIASU, precedencja `user`, D5 (delta ze stanu) ---

def _p4_tree(tmp_path):
    """2 light'y 'HotS' (nazwa NIEROZWIĄZYWALNA katalogowo): h1 BEZ koordów, h2 WEWNĄTRZ regionu
    Veil (RA/DEC środka). Pod testy kolejności szczebli alias/region i zapamiętania aliasu."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    _fits(tree / "h1.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "HotS")], n=1)
    _fits(tree / "h2.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "HotS"),
                                   ("RA", 312.75), ("DEC", 30.67)], n=2)   # środek Veil (P3)
    scan_tree(con, tree, now=NOW)
    return con


def test_p4_bez_aliasu_region_dalej_ostatnim_szczeblem(tmp_path):
    """Kontrola P3 po wstawieniu szczebla aliasu: klatka z koordami w Veil trafia REGIONEM,
    bez koordów — do review. Kolejność drabiny bez aliasu niezmieniona."""
    con = _p4_tree(tmp_path)
    s = run_resolver(con, now=NOW)
    assert (s.objects_by_region, s.objects_by_alias, s.objects_review) == (1, 0, 1)
    assert con.execute(
        "SELECT object_source FROM frame WHERE object_id IS NOT NULL").fetchone()[0] == "region"
    con.close()


def test_p4_alias_bije_region(tmp_path):
    """R2/D-P4-1: alias (jawna wiedza o NAZWIE) PRZED regionem (inferencja z geometrii) — klatka
    'HotS' z koordami WEWNĄTRZ Veil i tak trafia aliasem (object_source='alias'), nie regionem."""
    con = _p4_tree(tmp_path)
    oid, _ = repo.upsert_object(con, canon="IC1795", catalog="IC", kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="HOTS", object_id=oid, source="user", now=NOW)
    s = run_resolver(con, now=NOW)
    assert (s.objects_by_alias, s.objects_by_region, s.objects_review) == (2, 0, 0)
    assert con.execute("SELECT count(*) FROM frame WHERE object_source='alias'").fetchone()[0] == 2
    # trafienie aliasu NIE pisze nowego aliasu ani nowego obiektu
    assert con.execute("SELECT count(*) FROM object_alias").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 1
    con.close()


def test_p4_katalog_bije_alias(tmp_path):
    """R2/header-primary: nazwa rozwiązywalna katalogowo NIGDY nie idzie szczeblem aliasu — alias
    'M42' wskazujący INNY obiekt istnieje, a klatka 'M 42' trafia katalogiem (M42→NGC1976)."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    _fits(tree / "m.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "M 42")], n=1)
    scan_tree(con, tree, now=NOW)
    oid_trap, _ = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="M42", object_id=oid_trap, source="user", now=NOW)
    s = run_resolver(con, now=NOW)
    assert s.objects_by_alias == 0
    row = con.execute(
        "SELECT f.object_id AS oid, f.object_source AS osrc FROM frame f "
        "JOIN header h ON h.frame_id=f.id WHERE h.object_raw='M 42'").fetchone()
    assert row["oid"] != oid_trap and row["osrc"] != "alias"
    assert con.execute(
        "SELECT canon FROM object WHERE id=?", (row["oid"],)).fetchone()[0] == "NGC1976"
    con.close()


def test_p4_pusty_klucz_aliasu_pomijany(tmp_path):
    """R2/D-P4-2: nazwa czysto symboliczna ('---') → `norm_alnum` daje '' → lookup aliasu
    POMINIĘTY (alias '' łapałby KAŻDĄ niealfanumeryczną nazwę — tu zasiano go obok klingi,
    jako symulację stanu awaryjnego; `repo.user_assign_object` pusty klucz odrzuca)."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    _fits(tree / "d.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "---")], n=1)
    scan_tree(con, tree, now=NOW)
    oid, _ = repo.upsert_object(con, canon="IC1795", catalog="IC", kind="deep_sky", now=NOW)
    with con:
        con.execute(
            "INSERT INTO object_alias(alias_norm, object_id, source) VALUES ('', ?, 'user')", (oid,))
    s = run_resolver(con, now=NOW)
    assert (s.objects_by_alias, s.objects_review) == (0, 1)
    assert con.execute("SELECT object_id FROM frame").fetchone()[0] is None
    con.close()


def test_p4_precedencja_user_na_cala_drabine(tmp_path):
    """R1/P4: `object_source='user'` pomija CAŁĄ drabinę — klatka z nagłówkiem rozwiązywalnym
    katalogowo ('M 42'), koordami w Veil I aliasem-pułapką na inny obiekt zachowuje obiekt usera:
    zero nowych `object.assigned`, poza `object.review_summary` (D5)."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    _fits(tree / "u.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "M 42"),
                                  ("RA", 312.75), ("DEC", 30.67)], n=1)
    scan_tree(con, tree, now=NOW)
    fid = con.execute("SELECT id FROM frame").fetchone()[0]
    # pułapka: alias 'M42' na INNY obiekt — gdyby user nie miał precedencji, resolver przepiąłby
    oid_trap, _ = repo.upsert_object(con, canon="IC1795", catalog="IC", kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="M42", object_id=oid_trap, source="user", now=NOW)
    assigned, _ = repo.user_assign_object(
        con, alias_norm="M42RECZNE", canon="NGC7000", catalog="NGC", kind="deep_sky",
        frame_ids=[fid], now=NOW)
    assert assigned == 1
    s = run_resolver(con, now=NOW)
    assert (s.objects_assigned, s.objects_by_alias, s.objects_by_region,
            s.objects_review) == (0, 0, 0, 0)
    row = con.execute("SELECT object_id, object_source FROM frame WHERE id=?", (fid,)).fetchone()
    assert row["object_source"] == "user"
    assert con.execute("SELECT canon FROM object WHERE id=?",
                       (row["object_id"],)).fetchone()[0] == "NGC7000"
    # jedyny object.assigned = ten od usera; review_summary pusty (D5 — przypisany nie wraca)
    assert con.execute("SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0] == 1
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='object.review_summary'").fetchone()[0] == 0
    con.close()


def test_p4_user_assign_zapamietuje_alias_dla_nowych_klatek(tmp_path):
    """R3/D-P4-1: ręczne przypisanie grupy 'HotS' zapamiętuje ALIAS — NOWA klatka z tym samym
    `object_raw` rozwiązuje się szczeblem aliasu (`object_source='alias'`). Kolejność drabiny
    w re-derywacji: klatka wcześniej zREGIONowana z nazwą 'HotS' PRZEPINA SIĘ na obiekt aliasu
    (alias = wiedza o nazwie > region = inferencja z geometrii; oba szczeble re-derywowalne,
    `assign_object` świadomie przepina przy innej parze — `repo.py:527-540`). Zamrożona jest
    WYŁĄCZNIE klatka 'user'. Delta ze stanu pusta (D5)."""
    con = _p4_tree(tmp_path)
    s = run_resolver(con, now=NOW)
    assert (s.objects_by_region, s.objects_review) == (1, 1)   # h2→Veil, h1→review
    # user przypisuje nierozwiązaną h1 do nowego obiektu IC1795 (alias HOTS zapamiętany)
    fids = [r[0] for r in con.execute(
        "SELECT f.id FROM frame f JOIN header h ON h.frame_id=f.id "
        "WHERE h.object_raw='HotS' AND f.object_id IS NULL")]
    assert repo.user_assign_object(
        con, alias_norm="HOTS", canon="IC1795", catalog="IC", kind="deep_sky",
        frame_ids=fids, now=NOW) == (1, 0)
    # re-resolve: h1 zamrożona ('user'), h2 RE-DERYWUJE się aliasem (Veil → IC1795) — precedencja
    # aliasu nad regionem obowiązuje też przy powtórnym przebiegu; delta pusta (D5)
    s2 = run_resolver(con, now=NOW)
    assert (s2.objects_assigned, s2.objects_by_alias, s2.objects_review) == (1, 1, 0)
    assert delta_report(con).object_unresolved == 0
    # NOWA klatka z tą samą nazwą → szczebel ALIASU
    _fits(tmp_path / "t" / "h3.fits",
          [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
           ("IMAGETYP", "LIGHT"), ("OBJECT", "HotS")], n=3)
    scan_tree(con, tmp_path / "t", now=NOW)
    s3 = run_resolver(con, now=NOW)
    assert (s3.objects_assigned, s3.objects_by_alias) == (1, 1)
    src = {r["object_source"]: r["n"] for r in con.execute(
        "SELECT object_source, count(*) AS n FROM frame GROUP BY object_source")}
    assert src == {"user": 1, "alias": 2}                    # h1 user; h2 (przepięta) + h3 alias
    # alias ani obiekt nie zduplikowane przez trafienia
    assert con.execute("SELECT count(*) FROM object_alias WHERE alias_norm='HOTS'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 2     # Veil + IC1795
    # replay: szczebel aliasu idempotentny (R8 — zero nowych object.assigned)
    s4 = run_resolver(con, now=NOW)
    assert (s4.objects_assigned, s4.objects_by_alias) == (0, 0)
    con.close()
