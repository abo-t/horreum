"""Oś OBSERWATORIUM (PLAN_os_obserwatorium) — czyste funkcje GPS/haversine, kotwica idempotencji
ANCHOR-PROXIMITY (zwrot member-id, seed zamrożony), port osi (merge 4-gwardy + unmerge + label),
integracja z `run_resolver` (KIND-AGNOSTYCZNA: light I kalibracja z GPS dostają stanowisko; brak GPS →
NULL cicho; śmieć → review_summary). Ground-truth: 24 pary GPS o topologii §8 (długość ZANONIMIZOWANA
+100° do repo publicznego, szerokość bez zmian → wszystkie dystanse zachowane) → 11 stanowisk, dom↔praca 4.385 km."""
import json
import math

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo
from horreum.gui import queries
from horreum.resolve.observatory import (
    THRESH_KM, haversine_km, nearest_site, parse_coord, site_coords,
)
from horreum.resolver import run_resolver
from horreum.scan import scan_tree

NOW = "2026-07-03T12:00:00"

# 24 pary (SITELAT, SITELONG) o TOPOLOGII §8 z horreum_pf4.db (24 distinct → 11 stanowisk). Współrzędne
# ZANONIMIZOWANE do repo publicznego: DŁUGOŚĆ przesunięta o +100° (szerokość bez zmian). Pod czystym
# przesunięciem długości WSZYSTKIE dystanse haversine są zachowane co do metra (Δlat, Δlon i szerokości
# niezmienione), więc klaster 24→11 i dom↔praca 4.385 km trzymają się identycznie. Dwa formaty: dziesiętny
# i DMS ze spacją. Greedy ≤ THRESH_KM → 11 (dom↔praca OSOBNE przy 4 km). Realny firsthand = scratch (poza repo).
PF4_GPS_PAIRS = [
    ("53.3885883333333", "114.4427616666667"), ("53.3883333333333", "114.4430555555556"),
    ("53.388555", "114.44247"), ("53.4080555555556", "114.5002777777778"),
    ("53.3883083", "114.4435983"), ("+53 23 18.930", "+114 26 32.742"),
    ("42.6930555555556", "124.7480555555556"), ("53.4083333333333", "114.5016666666667"),
    ("42.5111111111111", "124.7305555555556"), ("42.1541666666667", "123.7833333333333"),
    ("50.2702777777778", "116.6505555555556"), ("+43 23 32.790", "+122 35 09.690"),
    ("42.1625", "123.7872222222222"), ("53.4081683333333", "114.5013483333333"),
    ("37.9902", "138.768"), ("53.3883333333333", "114.4425"),
    ("40.0762333333333", "109.40086333333333"), ("53.3889883333333", "114.4423566666667"),
    ("53.38845167", "114.44177333"), ("39.5307033", "109.50443"),
    ("53.3886111111111", "114.4425"), ("53.3885716666667", "114.4425"),
    ("+53 24 29.334", "+114 30 04.638"), ("53.4233333333333", "114.5627777777778"),
]


def _fresh(tmp_path):
    return db.open_db(str(tmp_path / "h.db"))


def _events(con, verb=None):
    if verb is None:
        return con.execute("SELECT count(*) FROM event").fetchone()[0]
    return con.execute("SELECT count(*) FROM event WHERE verb=?", (verb,)).fetchone()[0]


# ============================================================ czyste funkcje: parse_coord

@pytest.mark.parametrize("raw, expected", [
    ("50.1234567", 50.1234567),                       # dziesiętny (wartości syntetyczne — nie realne site)
    ("+41 12 30.500", 41.0 + 12 / 60 + 30.500 / 3600),  # DMS ze spacją, znak +
    ("-41 12 30.500", -(41.0 + 12 / 60 + 30.500 / 3600)),  # znak − (półkula S / dł. W)
    ("+38 45 15.250", 38.0 + 45 / 60 + 15.250 / 3600),
    ("  62.5000  ", 62.5),                            # białe znaki obcięte
    (62.5, 62.5),                                     # nie-string też przechodzi (defensywnie)
])
def test_parse_coord_ok(raw, expected):
    assert parse_coord(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [
    None, "", "   ", "nan", "inf", "-inf", "NaN",     # nan/inf ubite (isfinite)
    "32.7.9", "18.9.30",                              # dwie kropki → DMS-try zwraca None, nie crash
    "abc", "12:34:56",                                # dwukropek NIE jest separatorem DMS (sonda: 0 „:")
])
def test_parse_coord_none(raw):
    assert parse_coord(raw) is None


# ============================================================ czyste funkcje: site_coords

def test_site_coords_both_or_null():
    assert site_coords("53.4", "114.4") == (53.4, 114.4)
    assert site_coords("53.4", None) is None          # reguła „oba albo NULL"
    assert site_coords(None, "114.4") is None
    assert site_coords("garbage", "114.4") is None     # jedna nieparsowalna → cała para None


def test_site_coords_range_and_0_360_norm():
    assert site_coords("91", "10") is None             # lat poza [-90, 90]
    assert site_coords("45", "270") == (45.0, -90.0)    # 0-360 → [-180, 180] (270°→-90°)
    assert site_coords("45", "541") is None            # >180 nawet po normalizacji → poza zakresem


# ============================================================ czyste funkcje: haversine

def test_haversine_zero_i_symetria():
    assert haversine_km((53.4, 114.4), (53.4, 114.4)) == pytest.approx(0.0)
    a, b = (53.388, 114.442), (42.15, 123.78)
    assert haversine_km(a, b) == pytest.approx(haversine_km(b, a))


def test_haversine_antypodalny_bez_valueerror():
    """Klamp `asin` do 1.0: punkty ~antypodalne (arg √ >1 po zaokrągleniu) nie wysadzają `math.asin`."""
    assert haversine_km((0.0, 0.0), (0.0, 180.0)) == pytest.approx(math.pi * 6371.0, rel=1e-6)


def test_haversine_dom_praca_4385m():
    """Ground truth Zdzinia: dom-seed ↔ praca-seed = 4.385 km (> THRESH_KM 4.0 → OSOBNE, margines 0.385)."""
    dom = site_coords(*PF4_GPS_PAIRS[0])
    praca = site_coords(*PF4_GPS_PAIRS[3])
    assert haversine_km(dom, praca) == pytest.approx(4.385, abs=0.01)
    assert haversine_km(dom, praca) > THRESH_KM


# ============================================================ nearest_site + klaster 24→11

def test_nearest_site_prog_i_tiebreak():
    sites = [(1, 53.4, 114.4), (2, 42.1, 123.7)]
    assert nearest_site((53.4001, 114.4001), sites) == 1       # w progu → najbliższy
    assert nearest_site((10.0, 10.0), sites) is None           # żaden ≤ próg → None
    # tie-break (dist, id): dwa równo odległe (±0.02°≈2.2km, w progu) → mniejsze id
    two = [(5, 0.0, 0.02), (3, 0.0, -0.02)]
    assert nearest_site((0.0, 0.0), two) == 3


def test_klaster_24_pkt_11_stanowisk_grount_truth():
    """§8: 24 realne punkty GPS → 11 stanowisk. Greedy jak produkcja: seed ZAMROŻONY przy utworzeniu
    (pierwszy punkt regionu), dopasowanie do najbliższego ≤ THRESH_KM. dom↔praca 4.385 km → OSOBNE."""
    pts = [site_coords(a, b) for a, b in PF4_GPS_PAIRS]
    assert all(p is not None for p in pts)             # wszystkie 24 parsowalne (oba formaty)
    seeds = []                                          # (id, lat, lon) — rosną greedy
    for p in pts:
        if nearest_site(p, seeds) is None:
            seeds.append((len(seeds), p[0], p[1]))
    assert len(seeds) == 11
    # jitter domu (<0.1 km) zlany: pierwszy klaster ma >1 członka, wszystkie <THRESH od seeda
    dom = pts[0]
    domlike = [p for p in pts if haversine_km(dom, p) < THRESH_KM]
    assert len(domlike) >= 8 and max(haversine_km(dom, p) for p in domlike) < 0.1


# ============================================================ repo: propose_observatory (ANCHOR-PROXIMITY)

def test_propose_seed_zamrozony_i_idempotentny(tmp_path):
    """Kotwica GEOMETRYCZNA: pierwszy punkt → INSERT seed + event; jitter <THRESH → to SAMO stanowisko
    (id, False) bez eventu, seed NIEZMIENIONY (zamrożony przy utworzeniu — nie „przeliczany", §2b/D4)."""
    con = _fresh(tmp_path)
    id1, created1 = repo.propose_observatory(con, lat=53.3885883, lon=114.4427616, now=NOW)
    assert created1 is True
    id2, created2 = repo.propose_observatory(con, lat=53.3883333, lon=114.4430555, now=NOW)   # jitter
    assert (id2, created2) == (id1, False)
    row = con.execute("SELECT lat, lon FROM observatory WHERE id=?", (id1,)).fetchone()
    assert (row["lat"], row["lon"]) == (53.3885883, 114.4427616)   # seed = PIERWSZY punkt, nie drugi
    assert _events(con, "observatory.proposed") == 1              # zero nowych eventów przy dopasowaniu
    con.close()


def test_propose_ponad_prog_to_nowe_stanowisko(tmp_path):
    con = _fresh(tmp_path)
    id1, _ = repo.propose_observatory(con, lat=53.3885883, lon=114.4427616, now=NOW)  # dom
    id2, created = repo.propose_observatory(con, lat=53.4080555, lon=114.5002777, now=NOW)  # praca >4km
    assert created is True and id2 != id1
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 2
    con.close()


def test_propose_zwraca_member_id_nie_kanon(tmp_path):
    """P1 (sedno rewizji): propose zwraca id DOPASOWANEGO wiersza (członka), NIGDY kanonu — inaczej
    kolaps-do-kanonu łamałby `unmerge` i robił churn. Po scaleniu praca→dom, punkt przy seedzie pracy
    zwraca CZŁONKA (praca), nie kanon (dom)."""
    con = _fresh(tmp_path)
    dom, _ = repo.propose_observatory(con, lat=53.3885883, lon=114.4427616, now=NOW)
    praca, _ = repo.propose_observatory(con, lat=53.4080555, lon=114.5002777, now=NOW)
    repo.merge_observatory(con, source_id=praca, target_id=dom, now=NOW)   # user scala (jego decyzja)
    hit, created = repo.propose_observatory(con, lat=53.4081683, lon=114.5013483, now=NOW)  # jitter pracy
    assert (hit, created) == (praca, False)                # członek, nie kanon dom
    con.close()


def test_assign_observatory_idempotentny(tmp_path):
    con = _fresh(tmp_path)
    oid, _ = repo.propose_observatory(con, lat=53.4, lon=114.4, now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="s1", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    assert repo.assign_observatory(con, frame_id=fid, observatory_id=oid, now=NOW) is True
    assert repo.assign_observatory(con, frame_id=fid, observatory_id=oid, now=NOW) is False  # idempotent
    assert _events(con, "observatory.assigned") == 1
    con.close()


# ============================================================ repo: port osi (label/merge/unmerge)

def _obs(con, lat, lon):
    oid, _ = repo.propose_observatory(con, lat=lat, lon=lon, now=NOW)
    return oid


def test_label_observatory_named_before_after(tmp_path):
    con = _fresh(tmp_path)
    o = _obs(con, 53.4, 114.4)
    assert repo.label_observatory(con, observatory_id=o, name="Dom", now=NOW) is True
    assert repo.label_observatory(con, observatory_id=o, name="Dom", now=NOW) is False          # idempotent
    assert repo.label_observatory(con, observatory_id=o, name="  Dom  ", now=NOW) is False       # po strip
    ev = con.execute("SELECT actor, payload FROM event WHERE verb='observatory.named'").fetchone()
    assert ev["actor"] == "user:local"
    assert json.loads(ev["payload"]) == {"before": None, "after": "Dom"}
    assert _events(con, "observatory.named") == 1
    con.close()


def test_label_pusty_to_ValueError(tmp_path):
    con = _fresh(tmp_path)
    o = _obs(con, 53.4, 114.4)
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            repo.label_observatory(con, observatory_id=o, name=bad, now=NOW)
    assert _events(con, "observatory.named") == 0
    con.close()


def test_merge_legalny_i_idempotentny(tmp_path):
    con = _fresh(tmp_path)
    a, b = _obs(con, 53.4, 114.4), _obs(con, 42.1, 123.7)
    assert repo.merge_observatory(con, source_id=a, target_id=b, now=NOW) is True
    assert con.execute("SELECT merged_into FROM observatory WHERE id=?", (a,)).fetchone()[0] == b
    assert repo.merge_observatory(con, source_id=a, target_id=b, now=NOW) is False   # idempotent
    ev = con.execute("SELECT target, payload FROM event WHERE verb='observatory.merged'").fetchone()
    assert ev["target"] == f"observatory:{a}" and json.loads(ev["payload"]) == {"source": a, "target": b}
    con.close()


def test_merge_cztery_gwardy(tmp_path):
    """4 gwardy jak `merge_telescope`: self / target nie-kanon / source nie-kanon / source z członkami."""
    con = _fresh(tmp_path)
    a, b, c = _obs(con, 53.4, 114.4), _obs(con, 42.1, 123.7), _obs(con, 37.9, 138.7)
    with pytest.raises(ValueError):                                   # (1) self-merge
        repo.merge_observatory(con, source_id=a, target_id=a, now=NOW)
    repo.merge_observatory(con, source_id=b, target_id=c, now=NOW)    # b scalony w c
    with pytest.raises(ValueError):                                   # (2) target b nie-kanon
        repo.merge_observatory(con, source_id=a, target_id=b, now=NOW)
    with pytest.raises(ValueError):                                   # (3) source b nie-kanon
        repo.merge_observatory(con, source_id=b, target_id=a, now=NOW)
    # (4) source z członkami: c ma członka b → c→a niedozwolone (łańcuch głęb. 2)
    with pytest.raises(ValueError):
        repo.merge_observatory(con, source_id=c, target_id=a, now=NOW)
    assert _events(con, "observatory.merged") == 1
    con.close()


def test_unmerge_cofa_i_event(tmp_path):
    con = _fresh(tmp_path)
    a, b = _obs(con, 53.4, 114.4), _obs(con, 42.1, 123.7)
    repo.merge_observatory(con, source_id=a, target_id=b, now=NOW)
    assert repo.unmerge_observatory(con, observatory_id=a, now=NOW) is True
    assert con.execute("SELECT merged_into FROM observatory WHERE id=?", (a,)).fetchone()[0] is None
    assert repo.unmerge_observatory(con, observatory_id=a, now=NOW) is False   # już kanoniczne
    ev = con.execute("SELECT payload FROM event WHERE verb='observatory.unmerged'").fetchone()
    assert json.loads(ev["payload"]) == {"before": b, "after": None}
    con.close()


def test_nieistniejace_obserwatorium_to_ValueError(tmp_path):
    con = _fresh(tmp_path)
    for call in (lambda: repo.label_observatory(con, observatory_id=999, name="X", now=NOW),
                 lambda: repo.unmerge_observatory(con, observatory_id=999, now=NOW),
                 lambda: repo.merge_observatory(con, source_id=999, target_id=998, now=NOW)):
        with pytest.raises(ValueError):
            call()
    con.close()


def test_canonical_view_glebokosc_1(tmp_path):
    """Widok observatory_canonical roluje scalone pod kanon (kopia telescope_canonical); po unmerge
    członek wraca jako własny canon (brak sieroty, głębokość ≤ 1)."""
    con = _fresh(tmp_path)
    a, b, c = _obs(con, 53.4, 114.4), _obs(con, 42.1, 123.7), _obs(con, 37.9, 138.7)
    repo.merge_observatory(con, source_id=a, target_id=c, now=NOW)
    repo.merge_observatory(con, source_id=b, target_id=c, now=NOW)
    rows = dict(con.execute("SELECT id, canon_id FROM observatory_canonical").fetchall())
    assert rows == {a: c, b: c, c: c}
    repo.unmerge_observatory(con, observatory_id=a, now=NOW)
    assert dict(con.execute("SELECT id, canon_id FROM observatory_canonical").fetchall()) == {a: a, b: c, c: c}
    con.close()


# ============================================================ integracja: run_resolver (KIND-AGNOSTIC)

def _fits(path, cards, n=0):
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    for kw, val in cards:
        hdu.header[kw] = val
    fits.HDUList([hdu]).writeto(str(path))
    return path


def _tree_with_gps(tmp_path):
    """Drzewo: 2 lighty DOM (jitter → 1 stanowisko), 1 light PRACA (>4km → 2. stanowisko), 1 light
    BEZ GPS (→ NULL cicho), 1 FLAT z GPS DOM (KIND-AGNOSTIC → dostaje stanowisko), 1 light ze ŚMIECIOWYM
    GPS (→ NULL + review_summary). DOM = seed pierwszego lightu; DMS testuje drugi format."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)]
    dom1 = [("SITELAT", 53.3885883), ("SITELONG", 114.4427616)]
    dom2 = [("SITELAT", "+53 23 18.930"), ("SITELONG", "+114 26 32.742")]  # DMS, ten sam DOM
    praca = [("SITELAT", 53.4080555), ("SITELONG", 114.5002777)]
    _fits(tree / "l1.fits", cam + dom1 + [("IMAGETYP", "LIGHT"), ("OBJECT", "NGC 6888")], n=1)
    _fits(tree / "l2.fits", cam + dom2 + [("IMAGETYP", "LIGHT"), ("OBJECT", "NGC 6888")], n=2)
    _fits(tree / "l3.fits", cam + praca + [("IMAGETYP", "LIGHT"), ("OBJECT", "M31")], n=3)
    _fits(tree / "l4.fits", cam + [("IMAGETYP", "LIGHT"), ("OBJECT", "M31")], n=4)          # bez GPS
    _fits(tree / "flat.fits", cam + dom1 + [("IMAGETYP", "FLAT")], n=5)                      # kalibracja z GPS
    _fits(tree / "bad.fits", cam + [("SITELAT", "xx"), ("SITELONG", "yy"),
                                    ("IMAGETYP", "LIGHT"), ("OBJECT", "M31")], n=6)          # śmieć
    scan_tree(con, tree, now=NOW)
    return con


def test_resolver_oś_obserwatorium_kind_agnostic(tmp_path):
    con = _tree_with_gps(tmp_path)
    s = run_resolver(con, now=NOW)
    # 2 stanowiska (DOM + PRACA); 4 przypisania (2 lighty DOM + 1 PRACA + 1 FLAT DOM); 1 śmieć
    assert (s.observatories_new, s.observatories_assigned, s.gps_unparseable) == (2, 4, 1)
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 2
    # KIND-AGNOSTIC: FLAT z GPS DOSTAJE stanowisko (kontrast do osi OBIEKT, gdzie kalibracja=NULL)
    flat_obs = con.execute("SELECT observatory_id FROM frame WHERE kind='flat'").fetchone()[0]
    assert flat_obs is not None
    # light BEZ GPS → observatory_id NULL i ZERO review (świadomy brak, jak XISF)
    no_gps = con.execute(
        "SELECT f.observatory_id FROM frame f JOIN header h ON h.frame_id=f.id "
        "WHERE h.object_raw='M31' AND NOT EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id "
        "AND c.keyword='SITELAT')").fetchone()[0]
    assert no_gps is None
    # śmieciowy GPS → 1 zbiorczy observatory.review_summary (frames=1)
    summ = con.execute("SELECT payload FROM event WHERE verb='observatory.review_summary'").fetchall()
    assert len(summ) == 1 and json.loads(summ[0]["payload"])["frames"] == 1
    con.close()


def test_resolver_obserwatorium_idempotentny(tmp_path):
    """Re-run: anchor stabilny → te same id, zero nowych proposed/assigned (kluczowe dla zero-churn)."""
    con = _tree_with_gps(tmp_path)
    run_resolver(con, now=NOW)
    proposed_before = _events(con, "observatory.proposed")
    assigned_before = _events(con, "observatory.assigned")
    s2 = run_resolver(con, now=NOW)
    assert (s2.observatories_new, s2.observatories_assigned) == (0, 0)
    assert _events(con, "observatory.proposed") == proposed_before == 2
    assert _events(con, "observatory.assigned") == assigned_before == 4
    con.close()


# ============================================================ read-model (GUI, Qt-free)

def test_active_observatories_licznik_rolowany_pod_kanon(tmp_path):
    """§3: `active_observatories` liczy klatki ścieżką `observatory_canonical → frame.observatory_id`
    BEZPOŚREDNIO (bez configu). Po scaleniu klatki członka rolują się pod kanon; unmerge rozdziela.
    Scalony NIE wycieka jako osobny wiersz (JAWNY `WHERE merged_into IS NULL`)."""
    con = _fresh(tmp_path)
    a, b = _obs(con, 53.4, 114.4), _obs(con, 42.1, 123.7)
    for i, oid in enumerate([a, a, b]):                 # 2 klatki pod a, 1 pod b
        fid, _ = repo.upsert_frame(con, sha1_data=f"s{i}", kind="light", filetype="fits",
                                   camera_id=None, now=NOW)
        repo.assign_observatory(con, frame_id=fid, observatory_id=oid, now=NOW)
    before = {r["id"]: r["frame_count"] for r in queries.active_observatories(con)}
    assert before == {a: 2, b: 1}

    repo.merge_observatory(con, source_id=b, target_id=a, now=NOW)
    after = {r["id"]: r["frame_count"] for r in queries.active_observatories(con)}
    assert after == {a: 3}                              # b nie wycieka; klatki b rolują pod a

    repo.unmerge_observatory(con, observatory_id=b, now=NOW)
    assert {r["id"]: r["frame_count"] for r in queries.active_observatories(con)} == {a: 2, b: 1}
    # merged_under widzi członka po scaleniu; audyt osi łapie proposed/merged/unmerged
    repo.merge_observatory(con, source_id=b, target_id=a, now=NOW)
    assert [m["id"] for m in queries.merged_under_observatory(con, a)] == [b]
    verbs = {e["verb"] for e in queries.observatory_axis_events(con, observatory_id=b)}
    assert {"observatory.proposed", "observatory.merged", "observatory.unmerged"} <= verbs
    con.close()
