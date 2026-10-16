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


def test_naglowek_bez_FILTER_i_OBJECT_zdejmuje_pochodne_kopii_skasowanej(tmp_path):
    """AR-2 / AR-22 (1): zeznanie przejęte z ocalałej kopii bez kart `FILTER`/`OBJECT` - filtr
    (pochodna bez ręki) idzie za nagłówkiem do NULL w JEDNYM zdarzeniu zbiorczym z listą `cleared`.
    Obiekt ZOSTAJE: nagłówek, który zamilkł, nie odpina obiektu (kontrakt
    `test_path_rung::test_region_NIE_nadpisuje_obiektu_z_naglowka_ktory_zamilkl` - ze stanu nie da
    się odróżnić przejęcia bez karty od karty cofniętej po potwierdzeniu ze ścieżki).
    Falsyfikator: przywróć `if fc is not None` w pętli filtra - `filter_canon` zostanie `Ha`."""
    import json
    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)
    l1, l2 = (con.execute("SELECT f.id FROM frame f JOIN header h ON h.frame_id = f.id "
                          "WHERE h.object_raw = ?", (raw,)).fetchone()[0]
              for raw in ("NGC 4258", "M106"))
    oid = con.execute("SELECT object_id FROM frame WHERE id = ?", (l2,)).fetchone()[0]
    repo.assign_object(con, frame_id=l2, object_id=oid, object_source="user", now=NOW,
                       actor="user:local")
    con.execute("UPDATE header SET filter_raw = NULL, object_raw = NULL "
                "WHERE frame_id IN (?, ?)", (l1, l2))
    con.commit()

    run_resolver(con, now=NOW)
    f1 = con.execute("SELECT filter_canon, object_id, object_source FROM frame WHERE id = ?",
                     (l1,)).fetchone()
    assert tuple(f1) == (None, oid, "header"), "filtr schodzi, obiekt z nagłówka zostaje"
    f2 = con.execute("SELECT filter_canon, object_source FROM frame WHERE id = ?", (l2,)).fetchone()
    assert tuple(f2) == (None, "user"), "filtr jest pochodną bez ręki; obiekt z ręki zostaje"
    ev = json.loads(con.execute("SELECT payload FROM event WHERE verb = 'filter.backfilled' "
                                "ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert ev == {"count": 2, "cleared": [[l1, "Ha"], [l2, "Ha"]]}

    nasze = "SELECT count(*) FROM event WHERE verb IN ('filter.backfilled', 'object.unassigned')"
    ile = con.execute(nasze).fetchone()[0]
    run_resolver(con, now=NOW)
    assert con.execute(nasze).fetchone()[0] == ile, "powtórka bez dziennika"
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


def test_delta_report_procent_nie_maskuje_spadku_klatka_bez_nazwy(tmp_path):
    """Klatka rozwiązana BEZ nazwy w nagłówku (dziś: region) nie wchodzi ANI do licznika, ANI do
    mianownika — procent mierzy ROZPOZNANIE NAZWY i musi stać na jednej populacji po obu stronach.

    Defekt, który to zamyka: licznik brał każdą klatkę z obiektem, a mianownik wymagał `object_raw`.
    Każda klatka rozwiązana regionem była wtedy stałą premią doliczaną do procentu, ale niewidoczną
    w mianowniku — więc napływ klatek NIEROZPOZNANYCH rozcieńczał się o tę premię i bramka
    `object_pct >= min` mogła zostać zielona mimo realnego spadku. Na tej fiksturze stary licznik
    daje **4/5 = 80,0%** zamiast 3/4 = 75,0% — zmierzone przez podmianę zapytania, nie oszacowane
    (pierwsza wersja tego zdania mówiła „4/4 = 100%" i była fałszywa: premia wchodzi do licznika,
    ale mianownik zostaje sumą licznika i delty, więc rośnie razem z nim).

    Populacja nie znika z raportu — ma własne pole `object_resolved_no_raw`."""
    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)
    oid, _ = repo.upsert_object(con, canon="NGC6960", catalog="NGC", kind="deep_sky", now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="bez-nazwy", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW)  # nagłówek JEST, `object_raw` NULL
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source="region", now=NOW)

    rep = delta_report(con)
    assert (rep.object_resolved, rep.object_unresolved, rep.object_pct) == (3, 1, 75.0)
    assert rep.object_resolved_no_raw == 1
    con.close()


# --- kolejka przeglądu ze STANU, nie ze zliczania eventów (#12) ---

def test_review_ze_stanu_nie_rosnie_przy_powtornej_dostawie(tmp_path):
    """SEDNO #12: `flag_config_review` emitowało BEZWARUNKOWO co przebieg, więc `count(event)` rósł
    liniowo przy powtórnej dostawie bez żadnej realnej zmiany. Od AR-88 zdarzenie pada tylko przy
    wejściu klatki do kolejki - test trzyma OBA końce: dziennik nie rośnie bez zmiany danych, a stan
    stoi w miejscu (licznik liczy STAN, nie zdarzenia)."""
    con = _scanned_tree(tmp_path)
    run_grouper(con, now=NOW)
    run_resolver(con, now=NOW)
    pierwszy = delta_report(con).review
    ev1 = con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0]

    run_grouper(con, now=NOW)                          # powtórna dostawa: ZERO nowych plików
    run_resolver(con, now=NOW)
    drugi = delta_report(con).review
    ev2 = con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0]

    assert ev1 > 0 and ev2 == ev1                      # powód zapisany RAZ na epizod (AR-88)
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
                                     mtime="t2", reason="OSError", kind="io", now=NOW)
    st1 = review_state(con)
    assert st1.unreadable == 1                          # kubełek liczy ze STANU
    assert (st1.no_config, st1.no_camera) == (1, 1)     # klatka nadal w tamtych kubełkach
    assert st1.total == 1                               # DISTINCT — ta sama klatka, nie 3
    # powtórna awaria (marker stoi, ten sam mtime) → stan stabilny (idempotencja)
    repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                     mtime="t2", reason="OSError", kind="io", now=NOW)
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
                                     mtime="t2", reason="e", kind="io", now=NOW)
    repo.refresh_location_unreadable(con, location_id=l2, sha1_data="d1", path="b.fits",
                                     mtime="t2", reason="e", kind="parse", now=NOW)
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
    g = repo.user_assign_object(
        con, alias_norm="M42RECZNE", canon="NGC7000", catalog="NGC", kind="deep_sky",
        frame_ids=[fid], now=NOW)
    assert g.assigned == 1
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
        frame_ids=fids, now=NOW).assigned == 1
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


def test_delta_report_widzi_lighty_bez_nazwy_w_naglowku(tmp_path):
    """P-D/D-PD-10 — KOTWICA NAWROTU. Mianownik procentu wymaga `object_raw NOT NULL`, więc light
    z nagłówkiem MILCZĄCYM o obiekcie był dla raportu dostawy NIEWIDZIALNY: bramka akceptacji
    świeciła zielono o klatkach, których nie widzi. `object_nameless` stoi OBOK procentu (nie w nim
    — klatka bez nazwy nie ma jak być „nierozpoznana pod nazwą") i nie rusza żadnej starej liczby."""
    from horreum import repo
    from horreum.resolver import nameless_lights

    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)
    baza = delta_report(con)
    assert baza.object_nameless == 0

    fid, _ = repo.upsert_frame(con, sha1_data="sha-bezimienny", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW)
    rep = delta_report(con)
    assert rep.object_nameless == nameless_lights(con) == 1
    # stare liczby BEZ zmian — nowa klatka nie weszła ani do rozwiązanych, ani do delty
    assert (rep.object_resolved, rep.object_unresolved, rep.object_delta) \
        == (baza.object_resolved, baza.object_unresolved, baza.object_delta)
    con.close()


def test_kotwica_nawrotu_rozdziela_format_bez_karty(tmp_path):
    """Kotwica MUSI rozróżniać dwie populacje pod jednym objawem, bo mają różne drogi naprawy:
    FITS bez `OBJECT` naprawia karta w pliku, RAW — wyłącznie ręka (EXIF nie zna tego pola).

    Falsyfikator zlania ich w jedną liczbę: na realnym archiwum było to 25 + 763 = 788, gdzie
    763 przykrywało każdy ruch w populacji astro — kotwica nie pilnowała już niczego."""
    from horreum import repo
    from horreum.resolver import (NO_OBJECT_CARD_FILETYPES, nameless_lights,
                                  nameless_raw_lights)

    assert "raw" in NO_OBJECT_CARD_FILETYPES        # właściciel faktu, nie literał u wołającego
    con = _scanned_tree(tmp_path)
    run_resolver(con, now=NOW)

    for sha, ft in (("sha-nm-fits", "fits"), ("sha-nm-raw", "raw"), ("sha-nm-raw2", "raw")):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype=ft,
                                   camera_id=None, now=NOW)
        repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=None, now=NOW)

    rep = delta_report(con)
    assert rep.object_nameless == nameless_lights(con) == 1
    assert rep.object_nameless_raw == nameless_raw_lights(con) == 2
    # RAW nie przecieka do procentu ani do delty (nie ma nazwy, pod którą byłby „nierozpoznany")
    assert rep.object_delta == delta_report(con).object_delta
    con.close()


# --- AR-177: forma karty OBJECT obiektu-regionu (Veil) i pytanie „czy karta sama wraca" ---

VEIL_RA, VEIL_DEC = 312.75, 30.67          # środek regionu Veil (`resolve/data/regions.json`)
M31_RA, M31_DEC = 10.68, 41.27             # daleko poza każdym regionem


def _veil_light(root, rel, obj, n, ra=VEIL_RA, dec=VEIL_DEC):
    """Light w drzewie archiwum `root/rel` z kartą `obj` (None = bez karty) i współrzędnymi."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = [("IMAGETYP", "LIGHT")] + ([("OBJECT", obj)] if obj is not None else [])
    if ra is not None:
        cards += [("RA", ra), ("DEC", dec)]
    return _fits(path, cards, n=n)


def _veil_baza(tmp_path, pliki):
    """Baza po skanie i przebiegu z lightów `pliki` = [(rel, karta, n), …] pod `ASTRO_`."""
    con = db.open_db(str(tmp_path / "h.db"))
    root = tmp_path / "ASTRO_"
    for rel, obj, n in pliki:
        _veil_light(root, rel, obj, n)
    scan_tree(con, root, now=NOW)
    run_resolver(con, now=NOW)
    return con, root


def _fid(con, nazwa):
    return con.execute("SELECT frame_id FROM location WHERE path LIKE ?",
                       (f"%{nazwa}",)).fetchone()[0]


def test_forma_regionu_to_karta_kopii_blizniakow_folderu(tmp_path):
    """AR-177 (`D-1016-3`): forma karty obiektu-regionu = tekst, który głosuje
    najwięcej OBECNYCH KOPII klatek obiektu ze źródłem `region` albo `twin`, stojących w folderze
    obiektu, kartą TEJ kopii (`macro._wlasna_wartosc`). Tu `'veil'` 2 głosy (w tym `twin`) wobec
    `'Petla'` 1; nie głosują: kopie bez faktów bieżących klatek z DWIEMA lokacjami (karta klatki
    mogła przyjść z drugiej kopii), kopie spoza folderu obiektu i klatki z ręką - każda z tych grup
    przegłosowałaby `'veil'`, gdyby głosowała.
    Falsyfikatory: bez warunku folderu / jednej lokacji / źródła albo bez głosu `twin` wynik to
    `'Petla'`."""
    from horreum import resolver
    pliki = ([(rf"LIGHTS\Veil\cam\v{i}.fits", "veil", i) for i in (1, 2)]
             + [(r"LIGHTS\Veil\cam\p1.fits", "Petla", 3)]
             + [(rf"LIGHTS\Veil\cam\stara{i}.fits", "Petla", 10 + i) for i in range(3)]
             + [(rf"LIGHTS\Inne\cam\obca{i}.fits", "Petla", 20 + i) for i in range(3)]
             + [(rf"LIGHTS\Veil\cam\reka{i}.fits", "Petla", 30 + i) for i in range(3)])
    con, _ = _veil_baza(tmp_path, pliki)
    assert {r[0] for r in con.execute("SELECT DISTINCT object_source FROM frame")} == {"region"}
    con.execute("UPDATE frame SET object_source = 'twin' WHERE id = ?", (_fid(con, "v2.fits"),))
    # Fakty zebrane przed 0025 (reguła nieznana) - „nie wiem” - przy klatce z drugą lokacją: karta
    # klatki nie jest wtedy kartą tej kopii. Poza klingą: tylko test.
    con.execute("UPDATE location SET hdr_rule = NULL WHERE path LIKE '%stara_.fits'")
    con.commit()
    for i in range(3):
        repo.add_location(con, frame_id=_fid(con, f"stara{i}.fits"), volume="?",
                          path=rf"X:\L\stara{i}_kopia.fits", now=NOW)
    reka = [_fid(con, f"reka{i}.fits") for i in range(3)]
    con.execute("UPDATE frame SET object_source = 'user' WHERE id IN (SELECT value FROM "
                "json_each(?))", (str(reka),))                         # ręka bez klingi - tylko test
    con.commit()
    assert resolver.forma_karty_object(con, "Veil") == "veil"
    con.close()


def test_forma_regionu_glosuja_lighty_bez_faktow_kopii_karta_klatki(tmp_path):
    """AR-177: pojedynczy light FITS faktów kopii nie dostaje, dopóki skan go znów nie przeczyta
    (`scan.copy_facts_candidates`) - na `pf4` 250 z 261 kopii Veil. Klatka z JEDNĄ lokacją głosuje
    wtedy kartą `OBJECT` klatki (to karta tej kopii, `macro._wlasna_wartosc`), więc forma nie spada
    na `header_form` `Veil` - inaczej 169 bliźniaków z `'veil'` weszłoby do Porządków dla samej
    wielkości liter. Falsyfikator: głos wyłącznie z faktów kopii - wynik `Veil`."""
    from horreum import resolver
    con, _ = _veil_baza(tmp_path, [(rf"LIGHTS\Veil\cam\v{i}.fits", "veil", i) for i in (1, 2)]
                        + [(r"LIGHTS\Veil\cam\bez.fits", None, 3)])
    con.execute("UPDATE location SET hdr_filter = NULL, hdr_imagetyp = NULL, hdr_object = NULL, "
                "hdr_telescop = NULL, hdr_instrume = NULL, hdr_exptime = NULL, "
                "hdr_xbinning = NULL, hdr_date_obs = NULL, hdr_hash = NULL, hdr_rule = NULL")
    con.commit()                             # stan sprzed odczytu faktów - poza klingą: tylko test
    assert con.execute("SELECT count(*) FROM location WHERE hdr_hash IS NOT NULL").fetchone()[0] == 0
    assert resolver.forma_karty_object(con, "Veil") == "veil"
    con.close()


def test_forma_regionu_remis_bez_glosow_i_kanon_spoza_regionow(tmp_path, monkeypatch):
    """Bez głosów forma regionu = `header_form` (`Veil`); remis wygrywa `header_form`, potem
    alfabet. Kanon, którego drabina nie zna i którego nie ma w `regions.json`, formy nie ma (jak
    `ZW77`). Falsyfikator: gałąź regionu zwraca None - pierwsza asercja pada."""
    from horreum import resolver
    con, _ = _veil_baza(tmp_path, [(r"LIGHTS\Veil\cam\a.fits", None, 1)])
    assert resolver.forma_karty_object(con, "Veil") == "Veil"
    for i, tekst in enumerate(("veil", "Veil"), start=2):
        _veil_light(tmp_path / "ASTRO_", rf"LIGHTS\Veil\cam\r{i}.fits", tekst, i)
    scan_tree(con, tmp_path / "ASTRO_", now=NOW)
    run_resolver(con, now=NOW)
    assert resolver.forma_karty_object(con, "Veil") == "Veil"           # remis 1:1 - header_form
    monkeypatch.setattr(resolver, "load_regions", lambda: ())
    assert resolver.forma_karty_object(con, "Veil") is None
    con.close()


def test_forma_regionu_nie_prowadzi_do_innego_obiektu(tmp_path):
    """Warunek `D-1016-3`: forma, którą drabina nazw oddałaby INNEMU obiektowi, odpada - i jako
    głos (karta `M 31` na klatce `region` nie wygrywa mimo większości), i jako `header_form`
    (alias `VEIL` innego obiektu → forma None). Falsyfikatory: głosowanie bez filtra drabiny
    (wynik `M 31`), gałąź nazwy bez `else None` (wynik `Veil`)."""
    from horreum import resolver
    from horreum.resolve.catalog import catalog_label
    con, _ = _veil_baza(tmp_path, [(r"LIGHTS\Veil\cam\v.fits", "veil", 1)]
                        + [(rf"LIGHTS\Veil\cam\m{i}.fits", "M 31", 10 + i) for i in range(3)])
    veil = con.execute("SELECT id FROM object WHERE canon = 'Veil'").fetchone()[0]
    for i in range(3):                       # karta M 31 przy obiekcie z regionu - klingą
        repo.assign_object(con, frame_id=_fid(con, f"m{i}.fits"), object_id=veil,
                           object_source="region", now=NOW)
    assert resolver.forma_karty_object(con, "Veil") == "veil"
    oid, _ = repo.upsert_object(con, canon="NGC6992", catalog=catalog_label("NGC6992"),
                                kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="VEIL", object_id=oid, source="user", now=NOW)
    assert resolver.forma_karty_object(con, "Veil") is None
    con.close()


def test_karta_wraca_szczeble_nazwa_blizniak_region():
    """`karta_wraca` - kolejność szczebli `run_resolver`: nazwa rozstrzyga sama (także w środku
    regionu), potem bliźniak (obiekt oryginału wariantu), na końcu region ze współrzędnych; brak
    współrzędnych to brak regionu. Równoważność z prawdziwym przebiegiem pinuje
    `test_object_change_write.py::test_karta_wraca_rownowazna_przebiegowi_po_zdjeciu_reki`.
    Falsyfikator: gałąź regionu zawsze True - asercje „poza" padają."""
    from horreum.resolver import karta_wraca
    nic = lambda _k: None                                       # noqa: E731 - pusta migawka aliasów
    assert karta_wraca(nic, "NGC 7000", "NGC7000", None, None)
    assert not karta_wraca(nic, "NGC 7000", "Veil", VEIL_RA, VEIL_DEC)
    assert karta_wraca(nic, "veil", "Veil", VEIL_RA, VEIL_DEC)
    assert not karta_wraca(nic, "veil", "Veil", M31_RA, M31_DEC)
    assert not karta_wraca(nic, "veil", "Veil", None, None)
    assert karta_wraca(nic, "veil", "Veil", M31_RA, M31_DEC, twin_canon="Veil")
    assert not karta_wraca(nic, "veil", "Veil", VEIL_RA, VEIL_DEC, twin_canon="NGC224")
