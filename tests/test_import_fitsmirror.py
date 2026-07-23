"""Import z dawcy fitsmirror (PF-3, brief §4) — pre-flight, falsyfikator, pętla, bramki.

Dawca budowany JAK ŻYWY: realne pliki FITS (astropy) skanowane `scan_file`, zeznania wkładane
do bazy o schemacie dawcy (files/cards/header_backups/commits, user_version=4). Dane PIKSELI
różnicowane per plik — identyczne piksele to JEDEN frame (tożsamość sha1_data), fixture'y
muszą różnicować dane, nie tylko nagłówki.
"""
import json
import os
import sqlite3

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo
from horreum.import_fitsmirror import (
    ACTOR, ImportAbort, import_fitsmirror, open_donor, preflight, read_repaired_registry,
    run_import,
)
from horreum.scan import scan_file

NOW = "2026-07-02T12:00:00+00:00"
SCANNED_AT = "2026-06-30T00:00:00+00:00"

# Schemat dawcy 1:1 z fitsmirror `core/db.py` (v1+v2+v3; v4 = keyword_groups, dla importu obojętne)
_DONOR_DDL = """
CREATE TABLE files (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    filename    TEXT NOT NULL,
    ext         TEXT,
    size        INTEGER,
    mtime       REAL,
    hdu_index   INTEGER,
    compressed  INTEGER NOT NULL DEFAULT 0,
    header_hash TEXT,
    sha1_file   TEXT,
    sha1_data   TEXT,
    status      TEXT NOT NULL DEFAULT 'ok',
    scanned_at  TEXT,
    sha1_data_uncomputable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE cards (
    file_id    INTEGER NOT NULL REFERENCES files (id),
    keyword    TEXT NOT NULL,
    idx        INTEGER NOT NULL DEFAULT 0,
    value_raw  TEXT,
    value_num  REAL,
    value_type TEXT,
    comment    TEXT,
    PRIMARY KEY (file_id, keyword, idx)
);
CREATE TABLE commits (
    id         INTEGER PRIMARY KEY,
    run_id     TEXT NOT NULL,
    applied_at TEXT,
    summary    TEXT
);
CREATE TABLE header_backups (
    id          INTEGER PRIMARY KEY,
    commit_id   INTEGER NOT NULL REFERENCES commits (id),
    file_id     INTEGER NOT NULL REFERENCES files (id),
    hdu_index   INTEGER NOT NULL,
    header_text TEXT NOT NULL,
    post_hash   TEXT NOT NULL,
    UNIQUE (commit_id, file_id)
);
PRAGMA user_version = 4;
"""


def _write_fits(path, cards, seed):
    """Minimalny FITS o UNIKALNYCH danych (sha1_data różny per seed — tożsamość!)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.full((4, 4), seed, dtype=np.uint16))
    for kw, val in cards:
        hdu.header[kw] = val
    fits.HDUList([hdu]).writeto(str(path))
    return path


def _donor_insert(dcon, path):
    """Zeskanuj realny plik i włóż jego zeznanie do dawcy (jak żywy skaner fitsmirror).
    Zwraca file_id."""
    rec = scan_file(str(path))
    assert rec.error is None
    st = os.stat(str(path))
    cur = dcon.execute(
        "INSERT INTO files(path, filename, ext, size, mtime, hdu_index, compressed, "
        "header_hash, sha1_file, sha1_data, status, scanned_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)",
        (rec.path, os.path.basename(rec.path), os.path.splitext(rec.path)[1].lower(),
         rec.size_bytes, st.st_mtime, rec.hdu_index, rec.compressed,
         rec.header_hash, rec.file_sha1, rec.sha1_data, SCANNED_AT))
    fid = cur.lastrowid
    dcon.executemany(
        "INSERT INTO cards(file_id, keyword, idx, value_raw, value_num, value_type, comment) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(fid, c.keyword, c.idx, c.value_raw, c.value_num, c.value_type, c.comment)
         for c in rec.cards])
    dcon.commit()
    return fid


def _mk_donor(tmp_path, specs):
    """Zbuduj drzewo plików + bazę dawcy. `specs` = [(względna_ścieżka, cards, seed)].
    Zwraca (donor_path, {rel: (abs_path, file_id)})."""
    tree = tmp_path / "astro"
    donor_path = tmp_path / "donor.db"
    dcon = sqlite3.connect(str(donor_path))
    dcon.executescript(_DONOR_DDL)
    out = {}
    for rel, cards, seed in specs:
        p = _write_fits(tree / rel, cards, seed)
        out[rel] = (p, _donor_insert(dcon, p))
    dcon.close()
    return donor_path, out

# Nagłówki wzorcowe: dwa teleskopy x dwie kamery (mono ZWO + kolor ZWO), light + flat
L_RC8_MM = [("IMAGETYP", "Light Frame"), ("TELESCOP", "RC8"), ("INSTRUME", "ZWO ASI2600MM Pro"),
            ("XPIXSZ", 3.76), ("FILTER", "Ha"), ("OBJECT", "M31"), ("FOCALLEN", 1600)]
L_A140_MC = [("IMAGETYP", "Light Frame"), ("TELESCOP", "A140R"),
             ("INSTRUME", "ZWO ASI2600MC Pro"), ("XPIXSZ", 3.76), ("BAYERPAT", "RGGB"),
             ("OBJECT", "NGC 7000"), ("FOCALLEN", 784)]
F_RC8_MM = [("IMAGETYP", "Flat Field"), ("TELESCOP", "RC8"), ("INSTRUME", "ZWO ASI2600MM Pro"),
            ("XPIXSZ", 3.76), ("FILTER", "Ha"), ("OBJECT", "FlatWizard")]

SPECS = [
    (os.path.join("LIGHTS", "m31_1.fits"), L_RC8_MM, 1),
    (os.path.join("LIGHTS", "m31_2.fits"), L_RC8_MM, 2),
    (os.path.join("LIGHTS", "ngc7000_1.fits"), L_A140_MC, 3),
    (os.path.join("CALIBRATION", "flat_1.fits"), F_RC8_MM, 4),
]


def _import(tmp_path, donor_path, **kw):
    return import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW,
                             rng_seed=1, **kw)


def test_happy_path_bramki_i_osie(tmp_path):
    """Pełny przebieg: bramki §4.6 przechodzą; frame/location/cards 1:1 z dawcą; osie
    teleskop/kamera/config wyłonione; review sprzętu ze STANU == 0."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    s = _import(tmp_path, donor_path)
    assert s.gate_failures == []
    assert s.files_total == 4 and s.imported == 4 and s.skipped == 0 and s.recomputed == 0
    assert s.gates["frame"] == (4, 4)
    assert s.gates["location"] == (4, 4)
    assert s.gates["telescope"] == (2, 2)
    assert s.gates["camera"] == (2, 2)
    assert s.gates["config"] == (2, 2)
    assert s.gates["cards"][0] == s.gates["cards"][1] > 0
    assert s.gates["frame.camera_id NULL"] == (0, 0)
    assert s.gates["frame.config_id NULL"] == (0, 0)


def test_zeznanie_i_fakty_kopii_1do1_z_dawca(tmp_path):
    """Synteza z cards dawcy == odczyt z dysku: raw_json, pola gorące, fakty kopii na location
    (file_sha1/header_hash/size z dawcy; mtime ze ŚWIEŻEGO stat w derywacji ISO)."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    _import(tmp_path, donor_path)
    con = db.open_db(str(tmp_path / "horreum.db"))
    p, _fid = files[os.path.join("LIGHTS", "m31_1.fits")]
    rec = scan_file(str(p))                             # wzorzec: pełny odczyt z dysku
    row = con.execute(
        "SELECT l.file_sha1, l.header_hash, l.size_bytes, l.mtime, l.volume, "
        "       f.sha1_data, h.raw_json, h.telescop, h.instrume, h.object_raw, f.kind "
        "FROM location l JOIN frame f ON f.id = l.frame_id "
        "JOIN header h ON h.frame_id = f.id WHERE l.path = ?", (str(p),)).fetchone()
    assert row["sha1_data"] == rec.sha1_data
    assert row["file_sha1"] == rec.file_sha1
    assert row["header_hash"] == rec.header_hash
    assert row["size_bytes"] == rec.size_bytes
    assert row["mtime"] == rec.mtime
    assert row["volume"] != "?"                         # serial ustalony (pre-flight)
    assert json.loads(row["raw_json"]) == rec.header    # synteza dict-a 1:1 (PF-1)
    assert row["telescop"] == "RC8"
    assert row["instrume"] == "ZWO ASI2600MM Pro"
    assert row["object_raw"] == "M31"
    assert row["kind"] == "light"
    con.close()


def test_actor_import_na_eventach(tmp_path):
    """Każdy event toru wciągania niesie actor='import:fitsmirror' (brief §4.2); grouper/resolver
    zostają przy własnych aktorach (te same funkcje co pipeline GUI)."""
    donor_path, _ = _mk_donor(tmp_path, SPECS)
    _import(tmp_path, donor_path)
    con = db.open_db(str(tmp_path / "horreum.db"))
    actors = {r[0] for r in con.execute(
        "SELECT DISTINCT actor FROM event WHERE verb IN "
        "('frame.observed', 'location.added', 'header.recorded', 'camera.upserted')")}
    assert actors == {ACTOR}
    grouper_actors = {r[0] for r in con.execute(
        "SELECT DISTINCT actor FROM event WHERE verb = 'telescope.proposed'")}
    assert grouper_actors == {"grouper"}
    con.close()


def test_skipped_nieosiagalny_plik(tmp_path):
    """Plik dawcy zniknięty z dysku → pomijany (soft-landing §4.3): event(frame.review) z kotwicą
    sha1 i aktorem importu; bramki liczone MINUS skipped."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[os.path.join("LIGHTS", "ngc7000_1.fits")]
    dcon = sqlite3.connect(str(donor_path))
    gone_sha = dcon.execute("SELECT sha1_data FROM files WHERE path = ?",
                            (str(p),)).fetchone()[0]
    dcon.close()
    os.remove(str(p))
    s = _import(tmp_path, donor_path)
    assert s.skipped == 1 and s.skipped_paths == [str(p)]
    assert s.gate_failures == []
    assert s.gates["frame"] == (3, 3)
    assert s.gates["telescope"] == (1, 1)               # A140R odpadł ze skipem
    con = db.open_db(str(tmp_path / "horreum.db"))
    ev = con.execute(
        "SELECT actor, target FROM event WHERE verb = 'frame.review'").fetchall()
    assert [(r["actor"], r["target"]) for r in ev] == [(ACTOR, f"sha1:{gone_sha}")]
    con.close()


def test_stop_rozjazd_sha1_data(tmp_path):
    """Falsyfikator kierunku C (R1#6): rozjazd sha1_data dawca↔dysk GDZIEKOLWIEK = STOP przed
    jakimkolwiek zapisem (spadek do pełnego skanu B)."""
    donor_path, _ = _mk_donor(tmp_path, SPECS)
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("UPDATE files SET sha1_data = 'deadbeef' WHERE id = 1")
    dcon.commit()
    dcon.close()
    with pytest.raises(ImportAbort, match="sha1_data"):
        _import(tmp_path, donor_path)
    con = db.open_db(str(tmp_path / "horreum.db"))
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 0   # zero zapisu
    con.close()


def test_recompute_pozno_naprawianych(tmp_path):
    """Fakty kopii stęchłe na pliku naprawianym PO scanned_at → CAŁA podgrupa czytana z dysku:
    do bazy wchodzi zeznanie Z DYSKU (nowy TELESCOP), nie stęchłe z dawcy."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    rel = os.path.join("LIGHTS", "m31_1.fits")
    p, fid = files[rel]
    fits.setval(str(p), "TELESCOP", value="RC8-NEW")    # writeback PO zeznaniu dawcy
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("INSERT INTO commits(run_id, applied_at, summary) VALUES ('r1', ?, 's')",
                 ("2026-07-01T00:00:00+00:00",))        # applied_at > SCANNED_AT
    dcon.execute("INSERT INTO header_backups(commit_id, file_id, hdu_index, header_text, "
                 "post_hash) VALUES (1, ?, 0, 'x', 'y')", (fid,))
    dcon.commit()
    dcon.close()
    s = _import(tmp_path, donor_path)
    assert s.recomputed == 1
    assert s.gate_failures == []
    con = db.open_db(str(tmp_path / "horreum.db"))
    row = con.execute(
        "SELECT h.telescop, l.header_hash FROM location l "
        "JOIN header h ON h.frame_id = l.frame_id WHERE l.path = ?", (str(p),)).fetchone()
    rec = scan_file(str(p))
    assert row["telescop"] == "RC8-NEW"                 # zeznanie z DYSKU, nie z dawcy
    assert row["header_hash"] == rec.header_hash
    assert con.execute("SELECT count(*) FROM telescope WHERE telescop_canon = 'RC8-NEW'"
                       ).fetchone()[0] == 1
    con.close()


def test_abort_rozjazd_faktow_poza_pozno_naprawianymi(tmp_path):
    """Rozjazd file_sha1/header_hash/mtime POZA znanym mechanizmem writebacku = stan
    nieoczekiwany (EXPECT) → abort, zero zapisu."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[os.path.join("LIGHTS", "m31_2.fits")]
    fits.setval(str(p), "TELESCOP", value="RC8-EDIT")   # edycja na dysku BEZ śladu w dawcy
    with pytest.raises(ImportAbort, match="pozno-naprawianymi"):
        _import(tmp_path, donor_path)


def _mk_live_registry(tmp_path, paths):
    """Żywa baza Horreum z rejestrem napraw (`header_backups`→`location`) — materiał
    D-0722-2 wariant A. Wszystko przez `repo` (jedna klinga), jak realny writeback."""
    live = tmp_path / "zywa.db"
    con = db.open_db(str(live))
    commit_id = repo.insert_commit(con, run_id="r1", now=NOW)
    for i, path in enumerate(paths, start=1):
        frame_id, _new = repo.upsert_frame(con, sha1_data=f"sha{i}", kind="light",
                                           filetype="fits", camera_id=None, now=NOW)
        loc_id, _known = repo.add_location(con, frame_id=frame_id, volume="V", path=str(path),
                                           mtime=NOW, size_bytes=1, now=NOW)
        repo.insert_header_backup(con, commit_id=commit_id, location_id=loc_id, hdu_index=0,
                                  header_text="x", post_hash="y")
    con.close()
    return live


def test_rejestr_napraw_horreum_to_nota_nie_abort(tmp_path):
    """D-0722-2 wariant A: plik naprawiony przez HORREUM ma stęchłe fakty kopii u dawcy
    (dawca o naprawie nie wie) — z rejestrem to NOTA, nie abort. Zeznanie dawcy sprzed
    naprawy wchodzi jako baseline (bez przeliczania), tożsamość `sha1_data` przeżywa."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[os.path.join("LIGHTS", "m31_2.fits")]
    fits.setval(str(p), "TELESCOP", value="RC8-EDIT")   # writeback Horreum: dawca nie ma wiersza
    live = _mk_live_registry(tmp_path, [p])

    with pytest.raises(ImportAbort, match="pozno-naprawianymi"):   # bez rejestru: abort (dziś)
        _import(tmp_path, donor_path)
    os.remove(str(tmp_path / "horreum.db"))

    registry = read_repaired_registry(str(live))
    assert registry == frozenset({str(p)})
    donor = open_donor(str(donor_path))
    try:
        pf = preflight(donor, rng_seed=1, repaired_paths=registry)
    finally:
        donor.close()
    assert pf.repaired_registry == frozenset({str(p)})
    assert pf.recompute == frozenset()                  # rejestr NIE ciągnie przeliczania
    assert any("naprawionym przez Horreum" in n for n in pf.notes)


def test_rejestr_napraw_nie_gasi_ostrza_expect(tmp_path):
    """Ostrze EXPECT zostaje: rozjazd faktów kopii POZA rejestrem (i poza późno-naprawianymi
    dawcy) nadal abortuje — rejestr wpisuje ZNANE, nie wycisza nieznanego."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    znany, _ = files[os.path.join("LIGHTS", "m31_1.fits")]
    obcy, _ = files[os.path.join("LIGHTS", "m31_2.fits")]
    fits.setval(str(znany), "TELESCOP", value="RC8-NEW")
    fits.setval(str(obcy), "TELESCOP", value="RC8-OBCY")           # stęchnięcie NIEZNANE
    registry = read_repaired_registry(str(_mk_live_registry(tmp_path, [znany])))
    donor = open_donor(str(donor_path))
    try:
        with pytest.raises(ImportAbort, match="pozno-naprawianymi"):
            preflight(donor, rng_seed=1, repaired_paths=registry)
    finally:
        donor.close()


def test_rejestr_napraw_nie_gasi_rozjazdu_tozsamosci(tmp_path):
    """Tożsamość jest święta także w rejestrze: writeback nie rusza danych, więc rozjazd
    `sha1_data` na pliku z rejestru = STOP (kierunek C pada), nie nota."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, fid = files[os.path.join("LIGHTS", "m31_1.fits")]
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("UPDATE files SET sha1_data = 'deadbeef' WHERE id = ?", (fid,))
    dcon.commit()
    dcon.close()
    registry = read_repaired_registry(str(_mk_live_registry(tmp_path, [p])))
    donor = open_donor(str(donor_path))
    try:
        with pytest.raises(ImportAbort, match="ROZJAZD sha1_data"):
            preflight(donor, rng_seed=1, repaired_paths=registry)
    finally:
        donor.close()


def test_abort_baza_docelowa_niepusta(tmp_path):
    """Rama ŚWIEŻA-BAZA: import zasila wyłącznie świeżą bazę — niepusta → abort."""
    donor_path, _ = _mk_donor(tmp_path, SPECS)
    con = db.open_db(str(tmp_path / "horreum.db"))
    repo.upsert_frame(con, sha1_data="aa", kind="light", filetype="fits", camera_id=None,
                      now=NOW)
    con.close()
    with pytest.raises(ImportAbort, match="swieza"):
        _import(tmp_path, donor_path)


def test_abort_user_version_dawcy(tmp_path):
    """Dawca o innej user_version = inny kontrakt schematu → abort w open_donor."""
    donor_path, _ = _mk_donor(tmp_path, SPECS[:1])
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("PRAGMA user_version = 3")
    dcon.close()
    with pytest.raises(ImportAbort, match="user_version"):
        open_donor(str(donor_path))


def test_abort_dawca_niekompletny(tmp_path):
    """Wiersz 'unreadable'/bez tożsamości w dawcy → import nie ma czego wciągnąć → abort
    z listą (decyzja przy dawcy — doskan fitsmirror, nie zgadywanie tutaj)."""
    donor_path, _ = _mk_donor(tmp_path, SPECS[:2])
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("INSERT INTO files(path, filename, status) "
                 "VALUES ('C:\\x\\zepsuty.fits', 'zepsuty.fits', 'unreadable')")
    dcon.commit()
    dcon.close()
    with pytest.raises(ImportAbort, match="niekompletny"):
        _import(tmp_path, donor_path)


def test_abort_sha1_file_null(tmp_path):
    """Z4: wiersz dawcy z sha1_data OK ale sha1_file NULL → abort niekompletności.
    Plik czytelny ZAWSZE ma odcisk całości → NULL znaczy „nieodczytany"; wpuszczenie go
    dałoby `location.file_sha1 NULL`, co rozbraja marker nieczytelności (#13)."""
    donor_path, files = _mk_donor(tmp_path, SPECS[:2])
    _p, fid = files[os.path.join("LIGHTS", "m31_1.fits")]
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("UPDATE files SET sha1_file = NULL WHERE id = ?", (fid,))
    dcon.commit()
    dcon.close()
    with pytest.raises(ImportAbort, match="niekompletny"):
        _import(tmp_path, donor_path)


# dark FITS: TELESCOP obecny (ślad sesji akwizycji), ale kalibracja NIE jest na osi teleskopu
D_ED_MM = [("IMAGETYP", "Dark Frame"), ("TELESCOP", "ED"), ("INSTRUME", "ZWO ASI2600MM Pro"),
           ("XPIXSZ", 3.76)]


def test_dark_fits_kind_aware_bramki(tmp_path):
    """KIND-ŚLEPA naprawione: FITS-owy dark u dawcy (TELESCOP='ED') NIE wywala importu.
    Grouper pomija go na osi teleskopu (`config_id IS NULL` = STAN DOCELOWY), a bramki §4.6
    są KIND-AWARE — telescope/config/config_id-NULL liczą się z pominięciem dark/bias. Bez
    fixa: 'ED' i (ED,MM) fałszywie w derywacji + config_id NULL=1 → potrójny abort."""
    specs = SPECS + [(os.path.join("CALIBRATION", "dark_1.fits"), D_ED_MM, 7)]
    donor_path, files = _mk_donor(tmp_path, specs)
    s = _import(tmp_path, donor_path)
    assert s.gate_failures == [] and s.imported == 5
    assert s.gates["telescope"] == (2, 2)              # 'ED' (dark-only) NIE powołane na oś
    assert s.gates["config"] == (2, 2)                 # (ED,MM) NIE liczone do configu
    assert s.gates["frame.config_id NULL"] == (0, 0)   # dark: NULL to stan docelowy, nie review
    assert s.gates["frame.camera_id NULL"] == (0, 0)   # dark MA kamerę (oś kamery kind-agnostic)
    con = db.open_db(str(tmp_path / "horreum.db"))
    p, _fid = files[os.path.join("CALIBRATION", "dark_1.fits")]
    row = con.execute(
        "SELECT f.kind, f.config_id, f.camera_id FROM frame f "
        "JOIN location l ON l.frame_id = f.id WHERE l.path = ?", (str(p),)).fetchone()
    assert row["kind"] == "dark" and row["config_id"] is None and row["camera_id"] is not None
    assert con.execute("SELECT count(*) FROM telescope WHERE telescop_canon = 'ED'"
                       ).fetchone()[0] == 0
    con.close()


def test_facade_live_db_przekazuje_rejestr(tmp_path):
    """Dokrętka --live-db: fasada `import_fitsmirror(repaired_db=...)` czyta rejestr napraw
    i przekazuje go do `preflight` — plik naprawiony przez Horreum przechodzi jako NOTA zamiast
    abortu falsyfikatora. Realny import poza `acceptance_s5` trafiłby tę samą loterię (SCOPE
    domknięty: mechanizm był tylko na fladze acceptance, teraz i w fasadzie)."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    p, _fid = files[os.path.join("LIGHTS", "m31_2.fits")]
    fits.setval(str(p), "TELESCOP", value="RC8-EDIT")   # writeback Horreum: dawca nie ma wiersza
    live = _mk_live_registry(tmp_path, [p])
    with pytest.raises(ImportAbort, match="pozno-naprawianymi"):   # bez --live-db: abort
        import_fitsmirror(str(donor_path), str(tmp_path / "h1.db"), now=NOW, rng_seed=1)
    s = import_fitsmirror(str(donor_path), str(tmp_path / "h2.db"), now=NOW, rng_seed=1,
                          repaired_db=str(live))        # z --live-db: rejestr rozbraja falsyfikator
    assert s.gate_failures == []


def test_abort_sciezka_poza_listingiem(tmp_path):
    """Plik dawcy osiągalny na dysku, ale POZA listingiem skanu (katalog wykluczony _WBPP) —
    przyszły skan zdublowałby lokacje → abort (ochrona tożsamości, R3-a3)."""
    specs = SPECS[:2] + [(os.path.join("LIGHTS", "_WBPP", "roboczy.fits"), L_RC8_MM, 9)]
    donor_path, _ = _mk_donor(tmp_path, specs)
    with pytest.raises(ImportAbort, match="listingu"):
        _import(tmp_path, donor_path)


def test_preflight_nadwyzka_to_raport_nie_abort(tmp_path):
    """Nadwyżka listingu (pliki na dysku poza dawcą — przyszłe XISF) = raport, nie blokada."""
    donor_path, files = _mk_donor(tmp_path, SPECS)
    extra = _write_fits(tmp_path / "astro" / "LIGHTS" / "nowy.fits", L_RC8_MM, 11)
    donor = open_donor(str(donor_path))
    pf = preflight(donor, rng_seed=1)
    donor.close()
    assert pf.surplus == 1 and pf.surplus_sample == [str(extra)]
    s = _import(tmp_path, donor_path)
    assert s.gate_failures == []                        # nadwyżka nie psuje bramek


def test_run_import_degeneracja_uncomputable(tmp_path):
    """Wiersz dawcy z sha1_data_uncomputable=1 → degeneracja tożsamości (sha1 pliku + flaga),
    jak w skanie (lekcja v3 dawcy)."""
    donor_path, files = _mk_donor(tmp_path, SPECS[:2])
    rel = os.path.join("LIGHTS", "m31_1.fits")
    p, fid = files[rel]
    dcon = sqlite3.connect(str(donor_path))
    dcon.execute("UPDATE files SET sha1_data = NULL, sha1_data_uncomputable = 1 WHERE id = ?",
                 (fid,))
    dcon.commit()
    dcon.close()
    s = _import(tmp_path, donor_path)
    assert s.gate_failures == []
    con = db.open_db(str(tmp_path / "horreum.db"))
    rec = scan_file(str(p))
    row = con.execute(
        "SELECT f.sha1_data, f.sha1_data_uncomputable FROM frame f "
        "JOIN location l ON l.frame_id = f.id WHERE l.path = ?", (str(p),)).fetchone()
    assert (row["sha1_data"], row["sha1_data_uncomputable"]) == (rec.file_sha1, 1)
    con.close()
