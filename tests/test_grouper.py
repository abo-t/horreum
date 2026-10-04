"""Grouper teleskopów + config — integracja po skanie (po przejściu fitsmirror, brief §3).
Oś TELESKOP czytana WPROST z nagłówka: tożsamość = telescop_canon = TELESCOP.strip();
klastrowanie sygnatur FOCRATIO/FOCALLEN = MARTWE. Warianty wielkości liter foldowane WYŁĄCZNIE
przez collation NOCASE w repo (R2#8). Brak TELESCOP / brak kamery → config.review (W4)."""
import json
import struct

import numpy as np
from astropy.io import fits

from horreum import db, repo
from horreum.grouper import run_grouper
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


def _xisf(path, keywords):
    parts = "".join(f'<FITSKeyword name="{n}" value="{v}" comment=""/>' for n, v in keywords)
    xml = (f'<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
           f'<Image geometry="4:4:1" sampleFormat="UInt16" location="attachment:0:32">'
           f'{parts}</Image></xisf>').encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(b"XISF0100"); fh.write(struct.pack("<I", len(xml))); fh.write(b"\x00" * 4)
        fh.write(xml); fh.write(b"\x00" * 32)
    return path


def _scanned_tree(tmp_path):
    """Drzewo: A140R (784/5.6) ×2 (w tym wariant casingu 'a140r') + ED120R (900/7.5) — ta sama
    kamera ASI2600MM; master flat XISF BEZ TELESCOP (→ config.review). Zwraca połączenie po skanie."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT")]
    _fits(tree / "a140r_1.fits", cam + [("TELESCOP", "A140R"), ("FOCALLEN", 784), ("FOCRATIO", 5.6)],
          n=1)
    _fits(tree / "a140r_2.fits", cam + [("TELESCOP", "a140r"), ("FOCALLEN", 784), ("FOCRATIO", 5.6)],
          n=2)                                                # wariant casingu → TEN SAM teleskop
    _fits(tree / "ed120r.fits", cam + [("TELESCOP", "ED120R"), ("FOCALLEN", 900), ("FOCRATIO", 7.5)],
          n=3)
    _xisf(tree / "mflat.xisf", [("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                                ("BAYERPAT", "'RGGB'"), ("IMAGETYP", "'Master Flat'")])  # bez TELESCOP
    scan_tree(con, tree, now=NOW)
    return con


def test_grouper_telescopy_z_naglowka_nocase_foldowane(tmp_path):
    """SEDNO po przejściu: teleskop = TELESCOP.strip(); 'A140R' i 'a140r' → JEDEN teleskop
    (foldowanie WYŁĄCZNIE przez NOCASE w repo — R2#8); ED120R osobno. Właściwości f//ogniskowa
    wypełnione z zeznań."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert s.headers == 4 and s.telescopes_proposed == 2
    rows = {r["telescop_canon"]: r for r in con.execute(
        "SELECT telescop_canon, f_ratio_nominal, focal_nominal FROM telescope")}
    assert set(rows) == {"A140R", "ED120R"}                    # casing pierwszego wystąpienia
    assert (rows["A140R"]["f_ratio_nominal"], rows["A140R"]["focal_nominal"]) == (5.6, 784)
    assert (rows["ED120R"]["f_ratio_nominal"], rows["ED120R"]["focal_nominal"]) == (7.5, 900)
    con.close()


def test_grouper_config_link_inwariant_i_bez_telescop_review(tmp_path):
    """Lighty → config przypisany (inwariant config.camera_id==frame.camera_id); master BEZ
    TELESCOP → config_id NULL + event(config.review) + telescop_missing. Zero cichego NULL."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert s.configs_proposed == 2 and s.configs_assigned == 3      # 2 configi, 3 lighty przypięte
    assert (s.telescop_missing, s.config_review) == (1, 1)
    linked = con.execute("SELECT count(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    assert linked == 3
    assert con.execute("SELECT config_id FROM frame WHERE kind='master_flat'").fetchone()["config_id"] is None
    bad = con.execute("SELECT count(*) FROM frame f JOIN config c ON c.id=f.config_id "
                      "WHERE c.camera_id != f.camera_id").fetchone()[0]
    assert bad == 0
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0] == 1
    con.close()


def _scanned_z_darkiem(tmp_path):
    """Jak `_scanned_tree`, plus masterdark XISF z TELESCOP='ED' (teleskop, który dark widzi tylko
    dlatego, że akwizycja wpisała pole sesji) — jedyne zeznanie o 'ED' w całym drzewie."""
    con = _scanned_tree(tmp_path)
    _xisf(tmp_path / "t" / "mdark.xisf",
          [("INSTRUME", "'ZWO ASI2600MM Pro'"), ("XPIXSZ", "3.76"), ("TELESCOP", "'ED'"),
           ("EXPTIME", "300.0"), ("IMAGETYP", "'Master Dark'")])
    scan_tree(con, tmp_path / "t", now=NOW)
    return con


def test_grouper_dark_nie_powoluje_teleskopu_ani_configu(tmp_path):
    """KIND-SCOPING (wariant B): masterdark z TELESCOP='ED' NIE tworzy teleskopu 'ED' (dark nie ma
    optyki — pole to ślad sesji), nie dostaje configu I NIE trafia do `config.review`. Jego
    `config_id IS NULL` to stan docelowy, nie delta. Flat/light zostają na osi bez zmian."""
    con = _scanned_z_darkiem(tmp_path)
    s = run_grouper(con, now=NOW)
    assert {r["telescop_canon"] for r in con.execute("SELECT telescop_canon FROM telescope")} \
        == {"A140R", "ED120R"}                                  # 'ED' NIE powstał
    assert s.calibration_off_axis == 1 and s.configs_unassigned == 0
    assert (s.telescop_missing, s.config_review) == (1, 1)      # nadal tylko masterflat bez TELESCOP
    assert con.execute(
        "SELECT config_id FROM frame WHERE kind='master_dark'").fetchone()["config_id"] is None
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0] == 1
    con.close()


def test_grouper_odpina_stechle_przypisanie_kalibracji(tmp_path):
    """Dane SPRZED kind-scopingu: dark przypięty do cudzego configu. Przebieg AKTYWNIE go odpina
    (`config.unassigned`, ślad z poprzednim id), drugi przebieg jest już no-opem — samoleczenie
    idempotentne, bez migracji."""
    con = _scanned_z_darkiem(tmp_path)
    run_grouper(con, now=NOW)
    cfg_id = con.execute("SELECT id FROM config LIMIT 1").fetchone()["id"]
    con.execute("UPDATE frame SET config_id = ? WHERE kind='master_dark'", (cfg_id,))
    con.commit()                                                # symulacja stanu sprzed B

    s = run_grouper(con, now=NOW)
    assert s.configs_unassigned == 1
    assert con.execute(
        "SELECT config_id FROM frame WHERE kind='master_dark'").fetchone()["config_id"] is None
    ev = con.execute("SELECT payload, target FROM event WHERE verb='config.unassigned'").fetchall()
    assert len(ev) == 1 and str(cfg_id) in ev[0]["payload"]
    assert run_grouper(con, now=NOW).configs_unassigned == 0    # idempotencja
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='config.unassigned'").fetchone()[0] == 1
    con.close()


def test_grouper_idempotentny(tmp_path):
    """Drugi przebieg grouper nie tworzy duplikatów teleskopów/configów (propose_* idempotentne)."""
    con = _scanned_tree(tmp_path)
    run_grouper(con, now=NOW)
    s2 = run_grouper(con, now=NOW)
    assert s2.telescopes_proposed == 0 and s2.configs_proposed == 0 and s2.configs_assigned == 0
    assert con.execute("SELECT count(*) FROM telescope").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM config").fetchone()[0] == 2
    con.close()


# ─────────────── D-OW-3/R1: rozdział soczewek RAW + R-S1-5: przepięcie przebiegu emituje PARĘ

ADAPTER = "DT 0mm F0 SAM"        # nazwa zastępcza obiektywu na adapterze - realna z żywej `pf4`


def _baza_raw():
    """Kamera A7S + klatki seedowane klingą (grouper czyta `frame JOIN header`)."""
    con = db.open_db(":memory:")
    cam, _ = repo.upsert_camera(con, model_canon="A7S", pixel_um=8.4, is_mono=0,
                                is_mono_source="bayer", raw_instrume="SONY ILCE-7S", now=NOW)
    return con, cam


def _klatka(con, cam, sha, *, telescop, focallen, filetype="raw", kind="light"):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype=filetype,
                               camera_id=cam, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW, telescop=telescop,
                       focallen=focallen)
    return fid


def _os_klatki(con, fid):
    return con.execute(
        "SELECT t.telescop_canon, t.focal_nominal FROM frame f JOIN config c ON c.id = f.config_id "
        "JOIN telescope t ON t.id = c.telescope_id WHERE f.id = ?", (fid,)).fetchone()


def _stan_przed_rozdzialem(con, cam):
    """Stan żywej bazy sprzed rozdziału: wszystkie trzy szkła pod JEDNYM teleskopem, który mówi 50.
    Odtworzony dawną drogą - jedna ogniskowa w zeznaniu, przebieg, potem doskan dwóch kolejnych
    (`record_header` raz na klatkę, więc druga ogniskowa wchodzi nowymi klatkami, jak na `R:`)."""
    f50 = [_klatka(con, cam, f"a{i}", telescop=ADAPTER, focallen=50.0) for i in range(2)]
    run_grouper(con, now=NOW)
    tel = con.execute("SELECT id, focal_nominal FROM telescope").fetchone()
    assert tel["focal_nominal"] == 50
    con.execute("UPDATE telescope SET in_park = 0, label = 'Sony A-mount' WHERE id = ?",
                (tel["id"],))
    con.commit()                                       # park i etykieta ręki - mają przeżyć
    f70 = [_klatka(con, cam, f"b{i}", telescop=ADAPTER, focallen=70.0) for i in range(3)]
    f188 = [_klatka(con, cam, "c0", telescop=ADAPTER, focallen=188.0)]
    cfg = con.execute("SELECT config_id FROM frame WHERE id = ?", (f50[0],)).fetchone()[0]
    for fid in f70 + f188:                             # tak przypiął je dawny przebieg (config 19)
        repo.assign_config(con, frame_id=fid, config_id=cfg, now=NOW)
    return tel["id"], f50, f70, f188


def test_rozdzial_soczewek_raw_kotwica_zostaje_klamstwo_wychodzi():
    """SEDNO D-OW-3/R1: nazwa zastępcza z EXIF-u niesie trzy ogniskowe. Teleskop, który już mówi
    „50", ZOSTAJE (id, etykieta, park, config) przy klatkach 50 mm; klatki 70 i 188 mm dostają
    własne osi z prawdziwą ogniskową. Falsyfikator: zdejmij `_soczewki_raw` → wszystkie sześć
    klatek pod jednym configiem, a 70 mm opisane jako 50."""
    con, cam = _baza_raw()
    tel_id, f50, f70, f188 = _stan_przed_rozdzialem(con, cam)
    cfg_przed = con.execute("SELECT config_id FROM frame WHERE id = ?", (f50[0],)).fetchone()[0]

    s = run_grouper(con, now=NOW)

    assert s.telescopes_proposed == 2 and s.configs_proposed == 2
    tele = {r["telescop_canon"]: r for r in con.execute("SELECT * FROM telescope")}
    assert set(tele) == {ADAPTER, f"{ADAPTER} @ 70mm", f"{ADAPTER} @ 188mm"}
    kotwica = tele[ADAPTER]
    assert (kotwica["id"], kotwica["focal_nominal"], kotwica["label"], kotwica["in_park"]) == \
        (tel_id, 50, "Sony A-mount", 0)
    assert tele[f"{ADAPTER} @ 70mm"]["focal_nominal"] == 70
    assert tele[f"{ADAPTER} @ 188mm"]["focal_nominal"] == 188
    assert tele[f"{ADAPTER} @ 70mm"]["in_park"] is None          # park nowej osi: nikt nie zeznał
    for fid in f50:
        assert con.execute("SELECT config_id FROM frame WHERE id = ?", (fid,)).fetchone()[0] \
            == cfg_przed
    assert {_os_klatki(con, f)["focal_nominal"] for f in f70} == {70}
    assert _os_klatki(con, f188[0])["focal_nominal"] == 188
    con.close()


def test_scalenie_reka_wstrzymuje_rozdzial_soczewek():
    """Scalenie to fakt ręki: człowiek orzekł, że ta nazwa to ten sam sprzęt co inny teleskop.
    Automat nie wie, której ogniskowej to dotyczyło, więc klatek spod scalenia nie wyprowadza."""
    con, cam = _baza_raw()
    tel_id, f50, f70, f188 = _stan_przed_rozdzialem(con, cam)
    inny, _ = repo.propose_telescope(con, telescop_canon="Sony 50mm", f_ratio_nominal=None,
                                     focal_nominal=50, member_count=0, now=NOW)
    repo.merge_telescope(con, source_id=tel_id, target_id=inny, now=NOW)
    cfg_przed = {f: con.execute("SELECT config_id FROM frame WHERE id = ?", (f,)).fetchone()[0]
                 for f in f50 + f70 + f188}
    s = run_grouper(con, now=NOW)
    assert s.telescopes_proposed == 0
    assert {r[0] for r in con.execute("SELECT telescop_canon FROM telescope")} == {
        ADAPTER, "Sony 50mm"}
    for f, cfg in cfg_przed.items():
        assert con.execute("SELECT config_id FROM frame WHERE id = ?", (f,)).fetchone()[0] == cfg
    con.close()


def test_kanon_soczewki_zderzony_z_doslownym_TELESCOP_laczy_listy():
    """FITS zeznający dosłownie `X @ 70mm` i soczewka 70 mm wydzielona z RAW-ów nazwy `X` to ta
    sama oś: obie populacje lądują pod jednym teleskopem, żadna nie znika z przypisania."""
    con, cam = _baza_raw()
    raw50 = _klatka(con, cam, "r50", telescop=ADAPTER, focallen=50.0)
    raw70 = _klatka(con, cam, "r70", telescop=ADAPTER, focallen=70.0)
    fits = _klatka(con, cam, "f70", telescop=f"{ADAPTER} @ 70mm", focallen=70.0, filetype="fits")
    s = run_grouper(con, now=NOW)
    assert s.config_review == 0
    assert _os_klatki(con, raw70)["telescop_canon"] == _os_klatki(con, fits)["telescop_canon"] \
        == f"{ADAPTER} @ 70mm"
    assert _os_klatki(con, raw50)["telescop_canon"] == ADAPTER
    con.close()


def test_rozdzial_przepina_klinga_z_PARA_verbow_i_parytet_sie_domyka():
    """R-S1-5 na populacji, która go wywołuje: przepięcie przebiegu (stara oś → nowa soczewka)
    emituje `config.unassigned` + `config.assigned`, więc parytet osi configu domyka się bez członu
    historycznego. Falsyfikator: usuń parę z `repo.assign_config` → `legacy == 4` i `ok` zostaje
    zielone tylko dzięki członowi - dlatego pytamy o zero wprost."""
    from horreum import audit
    con, cam = _baza_raw()
    _, f50, f70, f188 = _stan_przed_rozdzialem(con, cam)
    cfg_adaptera = con.execute("SELECT config_id FROM frame WHERE id = ?", (f50[0],)).fetchone()[0]

    s = run_grouper(con, now=NOW)

    assert s.configs_assigned == 4                     # 3×70 + 1×188, klatki 50 mm nietknięte
    for fid in f70 + f188:
        ev = con.execute("SELECT verb, payload, reason FROM event WHERE target = ? "
                         "AND verb LIKE 'config.%' ORDER BY id", (f"frame:{fid}",)).fetchall()
        assert [e["verb"] for e in ev] == ["config.assigned", "config.unassigned",
                                           "config.assigned"]
        assert json.loads(ev[1]["payload"])["config_id"] == cfg_adaptera
        assert ev[1]["reason"]
    for fid in f50:
        assert con.execute("SELECT count(*) FROM event WHERE target = ? AND "
                           "verb = 'config.unassigned'", (f"frame:{fid}",)).fetchone()[0] == 0
    parytet = {p.name: p for p in audit.entity_event_parity(con)}["frame.config_id"]
    assert parytet.ok and parytet.legacy == 0 and parytet.retracted == 4
    assert audit.config_unpaired_reassignments(con) == 0
    con.close()


def test_przepiecie_przebiegu_emituje_pare_verbow():
    """R-S1-5 wprost na klindze: `assign_config` z innym configiem na klatce, która config MA,
    emituje parę, payload odpięcia niesie stan SPRZED. NULL→A zostaje jednym verbem."""
    con, cam = _baza_raw()
    fid = _klatka(con, cam, "x", telescop="A", focallen=50.0)
    t1, _ = repo.propose_telescope(con, telescop_canon="A", now=NOW)
    t2, _ = repo.propose_telescope(con, telescop_canon="B", now=NOW)
    c1, _ = repo.propose_config(con, telescope_id=t1, camera_id=cam, now=NOW)
    c2, _ = repo.propose_config(con, telescope_id=t2, camera_id=cam, now=NOW)
    assert repo.assign_config(con, frame_id=fid, config_id=c1, now=NOW)
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.unassigned'").fetchone()[0] == 0
    assert repo.assign_config(con, frame_id=fid, config_id=c2, now=NOW)
    ev = con.execute("SELECT verb, payload FROM event WHERE target = ? AND verb LIKE 'config.%' "
                     "ORDER BY id", (f"frame:{fid}",)).fetchall()
    assert [e["verb"] for e in ev] == ["config.assigned", "config.unassigned", "config.assigned"]
    assert json.loads(ev[1]["payload"])["config_id"] == c1
    assert not repo.assign_config(con, frame_id=fid, config_id=c2, now=NOW)   # idempotencja
    from horreum import audit
    assert {p.name: p for p in audit.entity_event_parity(con)}["frame.config_id"].ok
    assert audit.config_unpaired_reassignments(con) == 0
    con.close()


def test_parytet_odejmuje_HISTORIE_przepiec_bez_pary_odtworzona_z_dziennika():
    """Żywa baza niesie przepięcia sprzed pary verbów (append-only - historii nie przepisujemy).
    Człon `legacy` jest ODTWORZONY z dziennika, więc równość wraca do zieleni bez kotwicy,
    a `config_unpaired_reassignments` mówi wprost, ile tego jest - akceptacja na świeżej bazie
    wymaga zera. Stan historyczny wstrzykujemy dawną drogą (UPDATE + samo `config.assigned`)."""
    from horreum import audit
    con, cam = _baza_raw()
    fid = _klatka(con, cam, "h", telescop="A", focallen=50.0)
    run_grouper(con, now=NOW)
    t2, _ = repo.propose_telescope(con, telescop_canon="B", now=NOW)
    c2, _ = repo.propose_config(con, telescope_id=t2, camera_id=cam, now=NOW)
    with con:                                          # dawna klinga: przepięcie BEZ partnera
        con.execute("UPDATE frame SET config_id = ? WHERE id = ?", (c2, fid))
        repo.emit_event(con, actor="grouper", verb="config.assigned", target=f"frame:{fid}",
                        now=NOW, payload={"config_id": c2})
    parytet = {p.name: p for p in audit.entity_event_parity(con)}["frame.config_id"]
    assert (parytet.entities, parytet.events, parytet.retracted, parytet.legacy) == (1, 2, 0, 1)
    assert parytet.ok
    assert audit.config_unpaired_reassignments(con) == 1
    con.close()


def test_nazwa_o_JEDNEJ_ogniskowej_i_FITS_nie_rozdzielaja_sie():
    """Wąskość reguły: (a) nazwa RAW o jednej ogniskowej zachowuje kanon (na `pf4`: zoom FE 24-105
    na 48 mm, 265 klatek); (b) FITS z rozjazdem `FOCALLEN` (gotowy obraz po rozwiązaniu
    astrometrycznym: 784 vs 785,6) zostaje jednym teleskopem; (c) RAW bez `FOCALLEN` zostaje przy
    gołej nazwie - świadka ogniskowej nie ma, a folderu nie zgadujemy."""
    con, cam = _baza_raw()
    zoom = [_klatka(con, cam, f"z{i}", telescop="FE 24-105mm F4 G OSS", focallen=48.0)
            for i in range(2)]
    fits_ = [_klatka(con, cam, "f1", telescop="A140R", focallen=784.0, filetype="fits"),
             _klatka(con, cam, "f2", telescop="A140R", focallen=785.61, filetype="fits",
                     kind="master_light")]
    bez = _klatka(con, cam, "n0", telescop=ADAPTER, focallen=None)
    adapter = [_klatka(con, cam, "d50", telescop=ADAPTER, focallen=50.0),
               _klatka(con, cam, "d70", telescop=ADAPTER, focallen=70.0)]
    run_grouper(con, now=NOW)
    assert {r[0] for r in con.execute("SELECT telescop_canon FROM telescope")} == \
        {"FE 24-105mm F4 G OSS", "A140R", ADAPTER, f"{ADAPTER} @ 70mm"}
    assert {_os_klatki(con, f)["telescop_canon"] for f in zoom} == {"FE 24-105mm F4 G OSS"}
    assert {_os_klatki(con, f)["telescop_canon"] for f in fits_} == {"A140R"}
    assert _os_klatki(con, bez)["telescop_canon"] == ADAPTER
    assert _os_klatki(con, adapter[0])["telescop_canon"] == ADAPTER
    assert _os_klatki(con, adapter[1])["telescop_canon"] == f"{ADAPTER} @ 70mm"
    con.close()


def test_kotwica_to_ogniskowa_DEKLAROWANA_nie_pierwsza_w_kolejnosci():
    """Teleskop o tej nazwie już mówi „70" (np. powołany przy pierwszym doskanie), a pierwsza
    klatka w kolejności ma 50 mm. Kotwicą jest deklaracja istniejącego wiersza - inaczej rozdział
    przeniósłby klatki, o których teleskop mówi PRAWDĘ, i zmienił mu treść."""
    con, cam = _baza_raw()
    _klatka(con, cam, "p50", telescop=ADAPTER, focallen=50.0)
    _klatka(con, cam, "p70", telescop=ADAPTER, focallen=70.0)
    repo.propose_telescope(con, telescop_canon=ADAPTER, focal_nominal=70, now=NOW)
    run_grouper(con, now=NOW)
    tele = {r[0]: r[1] for r in con.execute("SELECT telescop_canon, focal_nominal FROM telescope")}
    assert tele == {ADAPTER: 70, f"{ADAPTER} @ 50mm": 50}
    con.close()


def test_reka_NIETYKALNA_przy_rozdziale():
    """Klatka z zestawem wskazanym ręką (`config_source='user'`) nie jest przepinana przez
    rozdział - faza 2 ją mija (R1b), a klinga i tak by odmówiła. Falsyfikator: zdejmij guard
    lepkości z groupera i `assign_config` → klatka 70 mm ręki trafia na nową soczewkę."""
    con, cam = _baza_raw()
    _, f50, f70, _ = _stan_przed_rozdzialem(con, cam)
    t_reka, _ = repo.propose_telescope(con, telescop_canon="RC8R", focal_nominal=1200, now=NOW)
    repo.user_assign_config(con, frame_ids=[f70[0]], telescope_id=t_reka, now=NOW,
                            overwrite=True)            # ręka ZMIENIA zestaw przypięty przebiegiem
    cfg_reki = con.execute("SELECT config_id FROM frame WHERE id = ?", (f70[0],)).fetchone()[0]
    s = run_grouper(con, now=NOW)
    assert s.config_by_hand == 1
    row = con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                      (f70[0],)).fetchone()
    assert (row["config_id"], row["config_source"]) == (cfg_reki, "user")
    assert _os_klatki(con, f70[1])["focal_nominal"] == 70
    s2 = run_grouper(con, now=NOW)                     # idempotencja rozdziału
    assert (s2.telescopes_proposed, s2.configs_proposed, s2.configs_assigned) == (0, 0, 0)
    con.close()
