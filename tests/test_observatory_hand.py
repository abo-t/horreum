"""STANOWISKO Z RĘKI (0027) - klinga `user_assign_observatory` / `clear_observatory_assignment`,
lepkość wobec przebiegu (także przy GPS w nagłówku), bilans zdarzeń i oś w `horreum human-facts`.

Populacja wzorcowa: RAW z lustrzanki bez modułu GPS (LMC, wyjazdy) - DNG jest read-only, więc fakt
żyje wyłącznie w bazie. Współrzędne w testach SYNTETYCZNE (repo publiczne - pamięć osi obserwatorium)."""
import json

import numpy as np
import pytest
from astropy.io import fits

from horreum import audit, db, repo
from horreum.resolve.observatory import THRESH_KM, user_site_coords
from horreum.resolver import run_resolver
from horreum.scan import scan_tree

NOW = "2026-10-04T12:00:00+00:00"
LATER = "2026-10-04T13:00:00+00:00"

# Syntetyczne stanowiska: „dom" z GPS w nagłówku i „wyjazd" na półkuli południowej (bez GPS w plikach).
DOM = (53.40, 114.40)
WYJAZD = (-30.25, 170.70)


def _baza(tmp_path):
    return db.open_db(str(tmp_path / "h.db"))


def _klatki(con, n, kind="light", prefix="r"):
    """Klatki BEZ nagłówka i bez GPS - jak DNG z lustrzanki bez modułu GPS."""
    out = []
    for i in range(n):
        fid, _ = repo.upsert_frame(con, sha1_data=f"{prefix}{i}", kind=kind, filetype="raw",
                                   camera_id=None, now=NOW)
        out.append(fid)
    return out


def _ile(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _stan(con, fid):
    r = con.execute("SELECT observatory_id, observatory_source FROM frame WHERE id = ?",
                    (fid,)).fetchone()
    return r["observatory_id"], r["observatory_source"]


def _fits(path, cards, n=0):
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
    for kw, val in cards:
        hdu.header[kw] = val
    fits.HDUList([hdu]).writeto(str(path))


def _drzewo_z_gps(tmp_path):
    """Dwa lighty z GPS „dom" (resolver da im stanowisko) - materiał na „ręka vs GPS"."""
    con = _baza(tmp_path)
    tree = tmp_path / "t"
    tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT"),
           ("OBJECT", "M31"), ("SITELAT", DOM[0]), ("SITELONG", DOM[1])]
    _fits(tree / "a.fits", cam, n=1)
    _fits(tree / "b.fits", cam, n=2)
    scan_tree(con, tree, now=NOW)
    run_resolver(con, now=NOW)
    ids = [r[0] for r in con.execute("SELECT id FROM frame ORDER BY id").fetchall()]
    return con, ids


# ============================================================ słownik źródeł (lustro DDL)

def test_zrodla_lustrem_checka_0027(tmp_path):
    """`OBSERVATORY_SOURCES` == lista w CHECK-u migracji 0027 - dwie siedziby jednego słownika."""
    con = _baza(tmp_path)
    fid = _klatki(con, 1)[0]
    oid, _ = repo.propose_observatory(con, lat=DOM[0], lon=DOM[1], now=NOW)
    for zrodlo in repo.OBSERVATORY_SOURCES:
        con.execute("UPDATE frame SET observatory_id = ?, observatory_source = ? WHERE id = ?",
                    (oid, zrodlo, fid))
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE frame SET observatory_source = 'resolver' WHERE id = ?", (fid,))
    con.rollback()
    assert repo.STICKY_OBSERVATORY_SOURCES == repo.OBSERVATORY_SOURCES


# ============================================================ walidacja współrzędnych

@pytest.mark.parametrize("lat, lon", [
    (91, 10), (-91, 10), (10, 181), (10, -180.5), (0, 0), ("x", 1), (float("nan"), 1),
    (1, float("inf")),
])
def test_wspolrzedne_spoza_zakresu_odmowa(lat, lon):
    with pytest.raises(ValueError):
        user_site_coords(lat, lon)


def test_wspolrzedne_poprawne_bez_normalizacji():
    assert user_site_coords("-30.25", 170.7, "1200") == (-30.25, 170.7, 1200.0)
    assert user_site_coords(0, 12.5) == (0.0, 12.5, None)          # sam równik to wartość


# ============================================================ klinga: nadanie

def test_nowe_stanowisko_z_reki_powolane_i_przypisane(tmp_path):
    con = _baza(tmp_path)
    ids = _klatki(con, 3)
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1],
                                     name="Wyjazd", elev=900, now=NOW)
    assert (g.assigned, g.occupied, g.unchanged, g.created) == (3, 0, 0, True)
    row = con.execute("SELECT name, lat, lon, elev FROM observatory WHERE id = ?",
                      (g.observatory_id,)).fetchone()
    assert tuple(row) == ("Wyjazd", WYJAZD[0], WYJAZD[1], 900.0)
    assert all(_stan(con, f) == (g.observatory_id, "user") for f in ids)
    zd = con.execute("SELECT actor, payload FROM event WHERE verb = 'observatory.assigned'").fetchall()
    assert len(zd) == 3 and {z["actor"] for z in zd} == {"user:local"}
    assert json.loads(zd[0]["payload"])["observatory_source"] == "user"
    assert _ile(con, "observatory.proposed") == 1


def test_punkt_w_promieniu_trafia_w_istniejace_stanowisko(tmp_path):
    """Ta sama kotwica geometryczna co `propose_observatory` - ręka nie mnoży duplikatów."""
    con = _baza(tmp_path)
    istniejace, _ = repo.propose_observatory(con, lat=DOM[0], lon=DOM[1], now=NOW)
    ids = _klatki(con, 2)
    blisko = DOM[1] + (THRESH_KM / 2) / 111.0 / 0.6          # ~2 km na wschód (cos 53° ≈ 0.6)
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=DOM[0], lon=blisko, name="Dom",
                                     now=NOW)
    assert (g.observatory_id, g.created, g.named) == (istniejace, False, True)
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 1
    assert con.execute("SELECT name FROM observatory").fetchone()[0] == "Dom"
    # stanowisko nazwane inaczej NIE traci nazwy - zmiana nazwy ma własny gest
    nowe = _klatki(con, 1, prefix="n")
    g2 = repo.user_assign_observatory(con, frame_ids=nowe, lat=DOM[0], lon=DOM[1], name="Inna",
                                      now=NOW)
    assert (g2.named, g2.name_kept) == (False, "Dom")


def test_wskazanie_po_id_i_bledy_wolania(tmp_path):
    con = _baza(tmp_path)
    oid, _ = repo.propose_observatory(con, lat=DOM[0], lon=DOM[1], now=NOW)
    ids = _klatki(con, 2)
    assert repo.user_assign_observatory(con, frame_ids=ids, observatory_id=oid,
                                        now=NOW).assigned == 2
    with pytest.raises(ValueError):
        repo.user_assign_observatory(con, frame_ids=ids, observatory_id=999, now=NOW)
    with pytest.raises(ValueError):
        repo.user_assign_observatory(con, frame_ids=ids, observatory_id=oid, lat=1, lon=2, now=NOW)
    with pytest.raises(ValueError):
        repo.user_assign_observatory(con, frame_ids=ids, now=NOW)


def test_klatka_nieistniejaca_wycofuje_cala_grupe(tmp_path):
    """Zero zapisu - także nowego stanowiska, które powołał już pierwszy wiersz grupy."""
    con = _baza(tmp_path)
    ids = _klatki(con, 2)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    with pytest.raises(ValueError):
        repo.user_assign_observatory(con, frame_ids=ids + [999], lat=WYJAZD[0], lon=WYJAZD[1],
                                     now=NOW)
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    assert all(_stan(con, f) == (None, None) for f in ids)


def test_idempotencja_powtorzony_gest_bez_zapisu(tmp_path):
    con = _baza(tmp_path)
    ids = _klatki(con, 2)
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    g2 = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=LATER)
    assert (g2.assigned, g2.unchanged, g2.created, g2.observatory_id) == (0, 2, False,
                                                                          g.observatory_id)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_gest_bez_zapisu_nie_zostawia_sieroty_w_osi(tmp_path):
    """Wszystkie klatki zajęte, overwrite nie poproszony → nowe stanowisko NIE powstaje."""
    con = _baza(tmp_path)
    oid, _ = repo.propose_observatory(con, lat=DOM[0], lon=DOM[1], now=NOW)
    ids = _klatki(con, 2)
    for f in ids:
        repo.assign_observatory(con, frame_id=f, observatory_id=oid, now=NOW)
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW)
    assert (g.assigned, g.occupied, g.created) == (0, 2, False)
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 1


def test_nadpisanie_tylko_jawne_i_emituje_pare(tmp_path):
    con, ids = _drzewo_z_gps(tmp_path)
    gps_oid = _stan(con, ids[0])[0]
    assert gps_oid is not None
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW)
    assert (g.assigned, g.occupied) == (0, 2)                         # bez overwrite - odmowa
    przed_un = _ile(con, "observatory.unassigned")
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW,
                                     overwrite=True)
    assert g.assigned == 2
    assert _ile(con, "observatory.unassigned") == przed_un + 2        # PARA przy przepięciu
    zdjete = [json.loads(r[0]) for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'observatory.unassigned'").fetchall()]
    assert {z["observatory_id"] for z in zdjete} == {gps_oid}
    assert {p.name: p.ok for p in audit.entity_event_parity(con)}["frame.observatory_id"]


def test_dry_liczy_to_samo_bez_zapisu(tmp_path):
    con = _baza(tmp_path)
    ids = _klatki(con, 3)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    g = repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW,
                                     dry=True)
    assert (g.assigned, g.created, g.observatory_id) == (3, True, None)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 0
    assert not con.in_transaction


# ============================================================ lepkość wobec przebiegu

def test_resolver_nie_rusza_reki_takze_przy_gps(tmp_path):
    """Nagłówek nie przegłosowuje ręki - a rozjazd jest LICZONY w podsumowaniu przebiegu."""
    con, ids = _drzewo_z_gps(tmp_path)
    g = repo.user_assign_observatory(con, frame_ids=[ids[0]], lat=WYJAZD[0], lon=WYJAZD[1],
                                     now=NOW, overwrite=True)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    s = run_resolver(con, now=LATER)
    assert _stan(con, ids[0]) == (g.observatory_id, "user")
    assert (s.observatories_hand, s.observatories_hand_vs_gps) == (1, 1)
    assert s.observatories_assigned == 0
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    # guard stoi TAKŻE w klindze automatu, nie tylko w pętli przebiegu
    assert repo.assign_observatory(con, frame_id=ids[0], observatory_id=_stan(con, ids[1])[0],
                                   now=LATER) is False


def test_reka_zgodna_z_gps_nie_jest_rozjazdem(tmp_path):
    con, ids = _drzewo_z_gps(tmp_path)
    gps_oid = _stan(con, ids[0])[0]
    repo.user_assign_observatory(con, frame_ids=[ids[0]], observatory_id=gps_oid, now=NOW,
                                 overwrite=True)
    s = run_resolver(con, now=LATER)
    assert (s.observatories_hand, s.observatories_hand_vs_gps) == (1, 0)


# ============================================================ cofnięcie

def test_cofniecie_oddaje_os_automatowi(tmp_path):
    """Bez GPS - wraca NULL; z GPS - najbliższy `Rozwiąż` przywraca stanowisko z pliku."""
    con, ids = _drzewo_z_gps(tmp_path)
    gps_oid = _stan(con, ids[0])[0]
    bez_gps = _klatki(con, 1)
    repo.user_assign_observatory(con, frame_ids=[ids[0]] + bez_gps, lat=WYJAZD[0],
                                 lon=WYJAZD[1], now=NOW, overwrite=True)
    c = repo.clear_observatory_assignment(con, frame_ids=[ids[0], ids[1]] + bez_gps, now=LATER)
    assert (c.cleared, c.not_hand, c.nothing) == (2, 1, 0)           # ids[1] ma GPS - nie ręka
    assert _stan(con, bez_gps[0]) == (None, None)
    assert _stan(con, ids[0]) == (None, None)
    run_resolver(con, now=LATER)
    assert _stan(con, ids[0]) == (gps_oid, None)
    assert {p.name: p.ok for p in audit.entity_event_parity(con)}["frame.observatory_id"]
    c2 = repo.clear_observatory_assignment(con, frame_ids=bez_gps, now=LATER)
    assert (c2.cleared, c2.nothing) == (0, 1)                        # idempotencja


def test_cofniecie_dry_bez_zapisu(tmp_path):
    con = _baza(tmp_path)
    ids = _klatki(con, 2)
    repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    c = repo.clear_observatory_assignment(con, frame_ids=ids, now=NOW, dry=True)
    assert c.cleared == 2
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    assert all(_stan(con, f)[1] == "user" for f in ids)


# ============================================================ human-facts

def test_human_facts_liczy_os_i_wykrywa_ubytek(tmp_path):
    con = _baza(tmp_path)
    ids = _klatki(con, 3)
    przed = audit.human_facts_census(con)
    repo.user_assign_observatory(con, frame_ids=ids, lat=WYJAZD[0], lon=WYJAZD[1], now=NOW)
    po = audit.human_facts_census(con)
    assert (przed.observatory_hand, po.observatory_hand) == (0, 3)
    assert po.spadki(przed) == {}                                     # wzrost to nie ubytek
    run_resolver(con, now=LATER)
    assert audit.human_facts_census(con).spadki(po) == {}             # przebieg ręki nie zdjął
    repo.clear_observatory_assignment(con, frame_ids=ids[:1], now=LATER)
    assert audit.human_facts_census(con).spadki(po) == {"observatory_hand": (3, 2)}


def test_human_facts_na_bazie_sprzed_0027(tmp_path):
    """Spis NIE migruje mierzonej bazy - na bazie v26 oś liczy się jako 0 zamiast wywracać spis."""
    path = str(tmp_path / "v26.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 26:
            db._apply_migration(con, version, db._migration_sql(filename))
    assert audit.human_facts_census(con).observatory_hand == 0
    con.close()


# ============================================================ podmiana pliku (supersede / transfer)

def _zastapiona_z_reka(con, *, nastepczyni_obs=None):
    """Para (stara, nowa): stara ze stanowiskiem z ręki jako JEDYNYM faktem człowieka, plik podmieniony."""
    from horreum import supersede  # noqa: F401  (import modułu kubełka przy teście)
    a, b = _klatki(con, 1, prefix="a")[0], _klatki(con, 1, prefix="b")[0]
    lid, _ = repo.add_location(con, frame_id=a, volume="V", path=r"X:\LMC\r.dng", now=NOW)
    g = repo.user_assign_observatory(con, frame_ids=[a], lat=WYJAZD[0], lon=WYJAZD[1], now=NOW)
    if nastepczyni_obs is not None:
        repo.assign_observatory(con, frame_id=b, observatory_id=nastepczyni_obs, now=NOW)
    repo.rebind_location(con, location_id=lid, frame_after=b, now=NOW)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    return a, b, g.observatory_id


def test_transfer_przenosi_stanowisko_z_reki_na_nastepczynie(tmp_path):
    from horreum import supersede
    con = _baza(tmp_path)
    a, b, oid = _zastapiona_z_reka(con)
    assert supersede.pending_transfer(con) == [(a, b, "stanowisko")]
    przed = audit.human_facts_census(con)
    t = repo.transfer_human_facts(con, frame_id=a, now=LATER)
    assert (t.observatory_moved, t.skipped) == (True, "")
    assert _stan(con, b) == (oid, "user") and _stan(con, a) == (oid, "user")   # stara nietknięta
    assert supersede.pending_transfer(con) == []
    assert audit.human_facts_census(con).spadki(przed) == {}
    assert {p.name: p.ok for p in audit.entity_event_parity(con)}["frame.observatory_id"]
    # idempotencja: drugi gest trafia w guard (następczyni ma swoje)
    assert repo.transfer_human_facts(con, frame_id=a, now=LATER).skipped == \
        "nastepczyni ma wlasne zrodlo"


def test_transfer_nie_nadpisuje_stanowiska_z_gps_nastepczyni(tmp_path):
    """Guard lustrzany do configu: oś następczyni NIEPUSTA (jej GPS) - przemówiła sama."""
    from horreum import supersede
    con = _baza(tmp_path)
    dom, _ = repo.propose_observatory(con, lat=DOM[0], lon=DOM[1], now=NOW)
    a, b, _oid = _zastapiona_z_reka(con, nastepczyni_obs=dom)
    assert supersede.pending_transfer(con) == []
    t = repo.transfer_human_facts(con, frame_id=a, now=LATER)
    assert (t.observatory_moved, t.skipped) == (False, "nastepczyni ma wlasne zrodlo")
    assert _stan(con, b) == (dom, None)


def test_wysokosc_z_gestu_jak_nazwa(tmp_path):
    """Trafienie w istniejące: wysokość dopisana tylko stanowisku bez wysokości, cudza zostaje."""
    con = _baza(tmp_path)
    oid, _ = repo.propose_observatory(con, lat=DOM[0], lon=DOM[1], now=NOW)
    ids = _klatki(con, 3)
    g = repo.user_assign_observatory(con, frame_ids=ids[:1], lat=DOM[0], lon=DOM[1], elev=120,
                                     now=NOW)
    assert (g.elev_set, g.elev_kept) == (120.0, None)
    assert con.execute("SELECT elev FROM observatory WHERE id = ?", (oid,)).fetchone()[0] == 120.0
    assert _ile(con, "observatory.elevation_set") == 1
    g2 = repo.user_assign_observatory(con, frame_ids=ids[1:2], lat=DOM[0], lon=DOM[1], elev=300,
                                      now=NOW)
    assert (g2.elev_set, g2.elev_kept) == (None, 120.0)
    assert con.execute("SELECT elev FROM observatory WHERE id = ?", (oid,)).fetchone()[0] == 120.0
    # gest bez zapisu nie dopisuje wysokości („zero zmian, gdy nic nie zapisano")
    con2 = db.open_db(":memory:")
    o2, _ = repo.propose_observatory(con2, lat=DOM[0], lon=DOM[1], now=NOW)
    f = _klatki(con2, 1)[0]
    repo.assign_observatory(con2, frame_id=f, observatory_id=o2, now=NOW)
    g3 = repo.user_assign_observatory(con2, frame_ids=[f], lat=DOM[0], lon=DOM[1], elev=50, now=NOW)
    assert (g3.assigned, g3.elev_set) == (0, None)


def test_cofniecie_raportuje_gps_i_stanowiska_zrodlowe(tmp_path):
    con, ids = _drzewo_z_gps(tmp_path)
    bez = _klatki(con, 1)
    g = repo.user_assign_observatory(con, frame_ids=[ids[0]] + bez, lat=WYJAZD[0], lon=WYJAZD[1],
                                     now=NOW, overwrite=True)
    c = repo.clear_observatory_assignment(con, frame_ids=[ids[0]] + bez, now=LATER)
    assert (c.cleared, c.cleared_gps, c.cleared_from) == (2, 1, (g.observatory_id,))
