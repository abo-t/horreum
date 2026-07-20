"""Resolver obiektu + filtra — integracja po skanie (§Etap 6).

SEDNO (firsthand-korekta): OBIEKT jest KIND-AWARE. Kalibracja (flat) z OBJECT='FlatWizard' →
object_id=NULL bez review (poprawny stan — flat nie ma obiektu z definicji). Tylko light/master_light
trafiają do delty. FILTR jest kind-AGNOSTYCZNY (flat też ma filtr → filter_canon ustawiony)."""
import numpy as np
from astropy.io import fits

from horreum import db
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
