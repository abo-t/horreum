"""Skan drzewa FITS — primitivy read-only (PLAN §4 krok 1): sha1 + nagłówek + stat.

Buduje REALNE pliki FITS przez astropy (pierwsza zależność runtime) i czyta je z powrotem.
"""
import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import db
from horreum.scan import (
    ScanRecord, ScanSummary, _already_scanned, ingest_record, iter_fits, iter_headers,
    read_fits_header, read_header, read_xisf_header, scan_file, scan_tree,
)

NOW = "2026-06-28T12:00:00"


def _write_fits(path, cards=(), data=None, extra_hdus=()):
    """Zapisz minimalny FITS z podanymi kartami nagłówka. `cards` = iterable (klucz, wartość)."""
    hdu = fits.PrimaryHDU(data=data)
    for kw, val in cards:
        hdu.header[kw] = val
    hdus = fits.HDUList([hdu, *extra_hdus])
    hdus.writeto(str(path))
    return path


def test_scan_file_sha1_i_stat(tmp_path):
    """sha1 == hashlib na bajtach pliku; size_bytes/mtime/path wypełnione."""
    f = _write_fits(tmp_path / "light.fits",
                    cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)],
                    data=np.zeros((4, 4), dtype=np.uint16))
    rec = scan_file(str(f))
    assert rec.sha1 == hashlib.sha1(f.read_bytes()).hexdigest()
    assert rec.size_bytes == f.stat().st_size
    assert rec.path == str(f)
    assert rec.mtime and "T" in rec.mtime          # ISO-8601


def test_naglowek_wyluskany_i_jsonowalny(tmp_path):
    """Karty gorące czytane wiernie; cały dict serializowalny do JSON (przyszły raw_json)."""
    f = _write_fits(tmp_path / "h.fits", cards=[
        ("INSTRUME", "ZWO ASI2600MM Pro"),
        ("XPIXSZ", 3.76),
        ("FOCALLEN", 784),
        ("FOCRATIO", 5.6),
        ("OBJECT", "NGC 4258"),
        ("FILTER", "Ha"),
    ])
    hdr = read_fits_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI2600MM Pro"
    assert hdr["XPIXSZ"] == 3.76
    assert hdr["FOCALLEN"] == 784
    assert hdr["OBJECT"] == "NGC 4258"
    json.dumps(hdr)                                # nie rzuca → JSON-owalne


def test_iter_fits_rekursywnie_i_filtruje(tmp_path):
    """Zbiera .fits/.fit/.fts (case-insensitive) rekursywnie; pomija nie-FITS; posortowane."""
    (tmp_path / "sub").mkdir()
    _write_fits(tmp_path / "a.fits")
    _write_fits(tmp_path / "b.FIT")
    _write_fits(tmp_path / "sub" / "c.fts")
    (tmp_path / "notes.txt").write_text("nie fits")
    (tmp_path / "img.xisf").write_bytes(b"XISF0")   # XISF łapie iter_headers, nie iter_fits
    got = [p.name for p in iter_fits(tmp_path)]
    assert got == sorted(["a.fits", "b.FIT", "c.fts"])


def test_comment_history_zachowane_jako_lista(tmp_path):
    """Powtarzalne COMMENT/HISTORY nie gubią wierszy (zeznanie 1:1) — lądują w liście."""
    hdu = fits.PrimaryHDU()
    hdu.header["HISTORY"] = "krok 1"
    hdu.header["HISTORY"] = "krok 2"
    hdu.header.add_comment("uwaga A")
    hdu.header.add_comment("uwaga B")
    f = tmp_path / "log.fits"
    fits.HDUList([hdu]).writeto(str(f))
    hdr = read_fits_header(str(f))
    assert hdr["HISTORY"] == ["krok 1", "krok 2"]
    assert hdr["COMMENT"] == ["uwaga A", "uwaga B"]


def test_naglowek_z_skompresowanego_hdu(tmp_path):
    """Master skompresowany: primary pusty (NAXIS=0), metadane w CompImageHDU — bierzemy je."""
    primary = fits.PrimaryHDU()                     # NAXIS=0
    comp = fits.CompImageHDU(data=np.zeros((4, 4), dtype=np.float32))
    comp.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    f = tmp_path / "master.fits"
    fits.HDUList([primary, comp]).writeto(str(f))
    hdr = read_fits_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI2600MM Pro"


def test_nie_fits_podnosi_wyjatek(tmp_path):
    """Plik, który nie jest FITS → wyjątek (skan nie zgaduje; review należy do upsertu)."""
    bad = tmp_path / "broken.fits"
    bad.write_bytes(b"to nie jest naglowek FITS")
    with pytest.raises(Exception):
        read_fits_header(str(bad))


def test_scan_nie_modyfikuje_pliku(tmp_path):
    """Inwariant append-only: skan to czysty odczyt — bajty i mtime pliku bez zmian."""
    f = _write_fits(tmp_path / "ro.fits", cards=[("OBJECT", "M31")],
                    data=np.zeros((4, 4), dtype=np.uint16))
    before = f.read_bytes()
    before_mtime = f.stat().st_mtime
    scan_file(str(f))
    assert f.read_bytes() == before
    assert f.stat().st_mtime == before_mtime


# --- XISF: czytnik nagłówka stdlib (§Etap 1) ---

def _write_xisf(path, keywords=(), *, namespace=True, trailing_data=True):
    """Zapisz minimalny monolityczny XISF z podanymi `<FITSKeyword>` (odwzorowanie tego, co
    osadza PixInsight). `keywords` = iterable (name, value[, comment]). namespace=True → root z
    xmlns PixInsight (realny wariant; sprawdza odporność czytnika na namespace). SYNTETYK —
    realny output PixInsighta weryfikuje firsthand-test Zdzinia przed Etapem 3."""
    ns = ' xmlns="http://www.pixinsight.com/xisf"' if namespace else ""
    parts = []
    for kw in keywords:
        name, value = kw[0], kw[1]
        comment = kw[2] if len(kw) > 2 else ""
        parts.append(f'<FITSKeyword name="{name}" value="{value}" comment="{comment}"/>')
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<xisf version="1.0"{ns}>'
        '<Image geometry="4:4:1" sampleFormat="UInt16" location="attachment:0:32">'
        + "".join(parts) +
        '</Image></xisf>'
    ).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(b"XISF0100")
        fh.write(struct.pack("<I", len(xml)))
        fh.write(b"\x00\x00\x00\x00")           # reserved
        fh.write(xml)
        if trailing_data:
            fh.write(b"\x00" * 32)              # atrapa bloku danych (czytnik go NIE tyka)
    return path


def test_read_xisf_header_klucze_jako_string(tmp_path):
    """XISF: `<FITSKeyword>` wyłuskane; wartości jako STRINGI (W3 — rzut na typ to pola gorące).
    Realistyczny wzorzec PixInsighta: karty stringowe w apostrofach FITS (odcudzysławiane →
    kontrakt 1:1 z FITS), liczby bez apostrofów. JSON-owalne (przyszły raw_json)."""
    f = _write_xisf(tmp_path / "m.xisf", keywords=[
        ("INSTRUME", "'ZWO ASI2600MC Pro'"),    # string FITS → w apostrofach (jak realny PixInsight)
        ("XPIXSZ", "3.76"),                      # liczba → bez apostrofów
        ("FOCALLEN", "1600"),
        ("BAYERPAT", "'RGGB'"),
        ("OBJECT", "'NGC 4258'"),
    ])
    hdr = read_xisf_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI2600MC Pro"   # odcudzysłowione → 1:1 z read_fits_header
    assert hdr["XPIXSZ"] == "3.76"              # STRING (nie 3.76) — kluczowy fakt W3
    assert isinstance(hdr["FOCALLEN"], str)
    assert hdr["BAYERPAT"] == "RGGB"
    assert hdr["OBJECT"] == "NGC 4258"
    json.dumps(hdr)                             # JSON-owalne → nie rzuca


def test_read_xisf_odcudzyslawia_wartosci_fits(tmp_path):
    """FIRSTHAND (poprawka Etapu 1): PixInsight zapisuje karty stringowe jak FITS — w apostrofach.
    Czytnik je zdejmuje (kontrakt 1:1 z read_fits_header): obejmujące `'` precz, `''`→`'` (escape
    FITS), końcowy pad → rstrip. Liczby (bez apostrofów) NIETKNIĘTE — rzut robi _to_float."""
    f = _write_xisf(tmp_path / "q.xisf", keywords=[
        ("INSTRUME", "'ZWO ASI2600MC Pro'"),
        ("IMAGETYP", "'FLAT'"),
        ("XPIXSZ", "3.76"),                      # liczba — bez apostrofów
        ("OBJECT", "'Bode''s Galaxy'"),          # escape FITS '' → '
        ("FILTER", "'L       '"),                # nieznaczący pad FITS → rstrip
    ])
    hdr = read_xisf_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI2600MC Pro"
    assert hdr["IMAGETYP"] == "FLAT"
    assert hdr["XPIXSZ"] == "3.76"               # liczba nietknięta
    assert hdr["OBJECT"] == "Bode's Galaxy"      # '' → '
    assert hdr["FILTER"] == "L"                  # pad zdjęty


@pytest.mark.parametrize("namespace", [True, False])
def test_read_xisf_header_odporny_na_namespace(tmp_path, namespace):
    """Realny PixInsight osadza xmlns; czytnik dopasowuje FITSKeyword po nazwie LOKALNEJ, więc
    działa z namespace I bez (najwyższe ryzyko Etapu 1 — parser binarny spoza Custosa/astropy)."""
    f = _write_xisf(tmp_path / f"ns_{namespace}.xisf",
                    keywords=[("INSTRUME", "ZWO ASI294MC Pro"), ("XPIXSZ", "4.63")],
                    namespace=namespace)
    hdr = read_xisf_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI294MC Pro"
    assert hdr["XPIXSZ"] == "4.63"


def test_read_xisf_klucz_malymi_literami_normalizowany(tmp_path):
    """Nazwa FITSKeyword sprowadzona do wielkich liter (kontrakt z FITS: `header.get('INSTRUME')`)."""
    f = _write_xisf(tmp_path / "lc.xisf", keywords=[("instrume", "ZWO ASI2600MM Pro")])
    assert read_xisf_header(str(f))["INSTRUME"] == "ZWO ASI2600MM Pro"


def test_read_xisf_comment_history_listy(tmp_path):
    """Powtarzalne COMMENT/HISTORY z XISF (PixInsight zachowuje karty FITS) → listy, jak w FITS."""
    f = _write_xisf(tmp_path / "log.xisf", keywords=[
        ("HISTORY", "krok 1"), ("HISTORY", "krok 2"),
        ("COMMENT", "uwaga A"), ("COMMENT", "uwaga B"),
        ("INSTRUME", "ZWO ASI2600MM Pro"),
    ])
    hdr = read_xisf_header(str(f))
    assert hdr["HISTORY"] == ["krok 1", "krok 2"]
    assert hdr["COMMENT"] == ["uwaga A", "uwaga B"]
    assert hdr["INSTRUME"] == "ZWO ASI2600MM Pro"


def test_read_xisf_zla_sygnatura_rzuca(tmp_path):
    """Zła sygnatura → wyjątek (czytnik nie zgaduje; miękkie lądowanie należy do scan_file)."""
    bad = tmp_path / "fake.xisf"
    bad.write_bytes(b"NOTXISF!" + b"\x00" * 20)
    with pytest.raises(Exception):
        read_xisf_header(str(bad))


def test_iter_headers_lapie_fits_i_xisf(tmp_path):
    """iter_headers zbiera 4 rozszerzenia (.fits/.fit/.fts/.xisf, case-insensitive), pomija inne,
    posortowane. iter_fits pozostaje FITS-only (XISF łapie tylko iter_headers)."""
    (tmp_path / "sub").mkdir()
    _write_fits(tmp_path / "a.fits")
    _write_fits(tmp_path / "b.FIT")
    _write_xisf(tmp_path / "sub" / "c.xisf", keywords=[("INSTRUME", "x")])
    _write_xisf(tmp_path / "d.XISF", keywords=[("INSTRUME", "y")])
    (tmp_path / "notes.txt").write_text("nie nagłówek")
    paths = iter_headers(tmp_path)
    assert {p.name for p in paths} == {"a.fits", "b.FIT", "c.xisf", "d.XISF"}   # 4 ext, .txt pominięty, rekursja
    assert paths == sorted(paths)                                   # deterministycznie posortowane po ścieżce
    assert "d.XISF" not in [p.name for p in iter_fits(tmp_path)]    # FITS-only nie łapie xisf


def test_iter_headers_prune_drzew_roboczych_z_listy(tmp_path):
    """Katalog z JAWNEJ listy (`_WBPP`/`_Review`, niewrażliwie na wielkość) jest ODCINANY — skaner do
    niego nie schodzi. Rodzeństwo skanowane normalnie. `excluded_out` zbiera ścieżki wykluczonych."""
    (tmp_path / "_WBPP").mkdir()
    (tmp_path / "_REVIEW").mkdir()                           # wielkie litery — NTFS case-insensitive
    (tmp_path / "LIGHTS").mkdir()
    _write_fits(tmp_path / "LIGHTS" / "keep.fits")
    _write_fits(tmp_path / "_WBPP" / "hardlink.fits")        # treść robocza — NIE wciągamy
    _write_fits(tmp_path / "_REVIEW" / "whatever.fits")
    excluded = []
    paths = iter_headers(tmp_path, excluded_out=excluded)
    assert {p.name for p in paths} == {"keep.fits"}          # tylko poddrzewo spoza listy
    assert {Path(d).name for d in excluded} == {"_WBPP", "_REVIEW"}   # nazwy wykluczonych, nie sam licznik


def test_iter_headers_underscore_spoza_listy_zostaje(tmp_path):
    """REGRESJA (firsthand realnym drzewie): katalog z prefiksem `_` ALE SPOZA listy — np. `_COMETS`/
    `_SOLAR` (realne lighty pod LIGHTS\\) — NIE jest wykluczany. Lista, nie konwencja `_*`."""
    (tmp_path / "LIGHTS" / "_COMETS").mkdir(parents=True)
    (tmp_path / "LIGHTS" / "_SOLAR").mkdir()
    _write_fits(tmp_path / "LIGHTS" / "_COMETS" / "comet.fits")
    _write_fits(tmp_path / "LIGHTS" / "_SOLAR" / "jup.fits")
    excluded = []
    paths = iter_headers(tmp_path, excluded_out=excluded)
    assert {p.name for p in paths} == {"comet.fits", "jup.fits"}   # realne dane zachowane
    assert excluded == []


def test_iter_headers_root_z_listy_jednak_skanowany(tmp_path):
    """WYJĄTEK root: gdy user JAWNIE wskaże `…\\_WBPP` jako katalog startowy, skanujemy go (lista tyka
    tylko podkatalogi odkryte w trakcie chodzenia, nie punkt startu) — inaczej „wskaż _WBPP → zero
    plików" kłamałoby."""
    root = tmp_path / "_WBPP"
    root.mkdir()
    _write_fits(root / "a.fits")
    assert {p.name for p in iter_headers(root)} == {"a.fits"}


def test_iter_headers_prune_zagniezdzony_i_gleboki(tmp_path):
    """Prune odcina CAŁE poddrzewo `_WBPP` (z zawartością głębiej), ale nie tyka rodzeństwa.
    `a/keep.fits` zostaje, `a/_WBPP/deep/c.fits` znika (odcięty na `_WBPP`)."""
    (tmp_path / "a" / "_WBPP" / "deep").mkdir(parents=True)
    _write_fits(tmp_path / "a" / "keep.fits")
    _write_fits(tmp_path / "a" / "_WBPP" / "deep" / "c.fits")
    excluded = []
    paths = iter_headers(tmp_path, excluded_out=excluded)
    assert {p.name for p in paths} == {"keep.fits"}
    assert [Path(d).name for d in excluded] == ["_WBPP"]


def test_scan_tree_telemetria_wykluczonych(tmp_path):
    """`scan_tree` wypełnia `dirs_excluded` (licznik) i `excluded_dirs` (ścieżki) — pliki w `_`-drzewie
    nie powstają jako frame'y (skaner tam nie schodzi)."""
    con = db.open_db(str(tmp_path / "s.db"))
    (tmp_path / "_WBPP").mkdir()
    (tmp_path / "LIGHTS").mkdir()
    _write_fits(tmp_path / "LIGHTS" / "keep.fits", cards=[("INSTRUME", "x"), ("XPIXSZ", 3.76)])
    _write_fits(tmp_path / "_WBPP" / "skip.fits", cards=[("INSTRUME", "x"), ("XPIXSZ", 3.76)])
    s = scan_tree(con, str(tmp_path), now=NOW)
    assert s.files == 1 and s.frames_new == 1                # tylko keep.fits wciągnięty
    assert s.dirs_excluded == 1
    assert [Path(d).name for d in s.excluded_dirs] == ["_WBPP"]


def test_read_header_dyspozytor_po_rozszerzeniu(tmp_path):
    """read_header kieruje .xisf → czytnik XISF (wartość STRING), .fits → astropy (typ natywny)."""
    xf = _write_xisf(tmp_path / "x.xisf", keywords=[("XPIXSZ", "3.76")])
    ff = _write_fits(tmp_path / "x.fits", cards=[("XPIXSZ", 3.76)])
    assert read_header(str(xf))["XPIXSZ"] == "3.76"        # string (XISF)
    assert read_header(str(ff))["XPIXSZ"] == 3.76          # float (FITS)


def test_scan_file_xisf_pelny_rekord(tmp_path):
    """scan_file na XISF → ScanRecord z sha1/stat + nagłówkiem (string), error None."""
    f = _write_xisf(tmp_path / "frame.xisf",
                    keywords=[("INSTRUME", "ZWO ASI2600MC Pro"), ("XPIXSZ", "3.76")])
    rec = scan_file(str(f))
    assert rec.sha1 == hashlib.sha1(f.read_bytes()).hexdigest()
    assert rec.error is None
    assert rec.header["INSTRUME"] == "ZWO ASI2600MC Pro"


def test_scan_file_miekkie_ladowanie_W1(tmp_path):
    """W1: plik o rozpoznanym rozszerzeniu, ale nieczytelnym nagłówku → scan_file NIE rzuca;
    zwraca header=None + error, a tożsamość (sha1) i namiary są wypełnione (frame/location powstaną)."""
    bad = tmp_path / "broken.xisf"
    bad.write_bytes(b"NOTXISF!" + b"\x00" * 20)
    rec = scan_file(str(bad))
    assert rec.header is None
    assert rec.error and "XISF" in rec.error
    assert rec.sha1 == hashlib.sha1(bad.read_bytes()).hexdigest()   # tożsamość przeżywa brak nagłówka
    assert rec.size_bytes == bad.stat().st_size


def test_scan_nie_modyfikuje_xisf(tmp_path):
    """Inwariant append-only także dla XISF: skan czyta sam nagłówek — bajty i mtime bez zmian."""
    f = _write_xisf(tmp_path / "ro.xisf", keywords=[("OBJECT", "M31")])
    before = f.read_bytes()
    before_mtime = f.stat().st_mtime
    scan_file(str(f))
    assert f.read_bytes() == before
    assert f.stat().st_mtime == before_mtime


# --- scan_tree: pętla płaska, pierwsze realne zapisy przez jedną klingę (§Etap 4) ---

def _db(tmp_path):
    return db.open_db(str(tmp_path / "h.db"))


def test_scan_tree_fits_xisf_frame_location_header(tmp_path):
    """Mieszane drzewo FITS+XISF → frame+location+header dla obu; kind z IMAGETYP (light + master_flat)."""
    con = _db(tmp_path)
    tree = tmp_path / "tree"; tree.mkdir()
    _write_fits(tree / "light.fits",
                cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT")],
                data=np.zeros((4, 4), np.uint16))
    _write_xisf(tree / "master.xisf",
                keywords=[("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                          ("IMAGETYP", "'Master Flat'"), ("BAYERPAT", "'RGGB'")])
    s = scan_tree(con, tree, volume="VOL1", now=NOW)
    assert (s.files, s.frames_new, s.locations_new, s.headers) == (2, 2, 2, 2)
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM header").fetchone()[0] == 2
    assert {r[0] for r in con.execute("SELECT kind FROM frame")} == {"light", "master_flat"}
    con.close()


def test_scan_tree_W3_jedna_kamera_fits_sub_xisf_master(tmp_path):
    """SEDNO W3: ASI2600MC z suba-FITS (XPIXSZ float 3.76) i mastera-XISF (XPIXSZ string '3.76')
    → JEDNA kamera (nierozbita po typie). To sedno całego planu skanu."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _write_fits(tree / "sub.fits",
                cards=[("INSTRUME", "ZWO ASI2600MC Pro"), ("XPIXSZ", 3.76),
                       ("BAYERPAT", "RGGB"), ("IMAGETYP", "LIGHT")],
                data=np.zeros((4, 4), np.uint16))
    _write_xisf(tree / "master.xisf",
                keywords=[("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                          ("BAYERPAT", "'RGGB'"), ("IMAGETYP", "'Master Flat'")])
    scan_tree(con, tree, now=NOW)
    assert con.execute("SELECT count(*) FROM camera WHERE model_canon='ASI2600MC'").fetchone()[0] == 1
    cam_ids = {r[0] for r in con.execute("SELECT camera_id FROM frame")}
    assert cam_ids != {None} and len(cam_ids) == 1   # oba frame'y → ta sama, niepusta kamera
    con.close()


def test_scan_tree_multi_location_synthetic(tmp_path):
    """1:N location SYNTETYCZNY (0 naturalnych duplikatów sha1): ten sam plik w 2 ścieżkach →
    JEDEN frame (sha1), DWIE location, JEDEN header (1:1)."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    (tree / "a").mkdir(); (tree / "b").mkdir()
    src = _write_fits(tree / "a" / "x.fits",
                      cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT")],
                      data=np.zeros((4, 4), np.uint16))
    shutil.copy(str(src), str(tree / "b" / "x.fits"))
    s = scan_tree(con, tree, now=NOW)
    assert (s.files, s.frames_new, s.frames_existing, s.locations_new) == (2, 1, 1, 2)
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM header").fetchone()[0] == 1
    con.close()


def test_scan_tree_header_none_frame_szkielet_D1(tmp_path):
    """D1 „baza zna wszystkie pliki": nieczytelny nagłówek (W1) → frame-SZKIELET (kind='unknown',
    camera_id=NULL) + location + event(frame.review), ale BEZ headera (raw_json nieczytelny)."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    (tree / "broken.xisf").write_bytes(b"NOTXISF!" + b"\x00" * 20)
    s = scan_tree(con, tree, now=NOW)
    assert (s.files, s.frame_review, s.frames_new, s.locations_new, s.headers) == (1, 1, 1, 1, 0)
    row = con.execute("SELECT kind, camera_id, filetype FROM frame").fetchone()
    assert (row["kind"], row["camera_id"], row["filetype"]) == ("unknown", None, "xisf")
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM header").fetchone()[0] == 0      # brak czytelnego headera
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.review'").fetchone()[0] == 1
    con.close()


def test_scan_tree_szkielet_re_skan_idempotentny_D1(tmp_path):
    """D1: re-skan tego samego nieczytelnego pliku NIE duplikuje frame'a ani frame.review (sha1
    UNIQUE = kotwica idempotencji, której event-only frame.review wcześniej nie miał)."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    (tree / "broken.xisf").write_bytes(b"NOTXISF!" + b"\x00" * 20)
    scan_tree(con, tree, now=NOW)
    s2 = scan_tree(con, tree, now=NOW)                       # drugi przebieg
    assert (s2.frames_new, s2.frames_existing, s2.frame_review) == (0, 1, 0)
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.review'").fetchone()[0] == 1
    con.close()


def test_scan_tree_camera_review_frame_jednak_powstaje(tmp_path):
    """camera_identity=None (brak INSTRUME) → event(camera.review), ALE frame+location+header
    powstają (tożsamość sha1 jest), camera_id=NULL."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _write_fits(tree / "noinstr.fits",
                cards=[("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT")], data=np.zeros((4, 4), np.uint16))
    s = scan_tree(con, tree, now=NOW)
    assert (s.frames_new, s.camera_review, s.headers) == (1, 1, 1)
    assert con.execute("SELECT camera_id FROM frame").fetchone()["camera_id"] is None
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.review'").fetchone()[0] == 1
    con.close()


def test_scan_tree_kind_unmapped(tmp_path):
    """IMAGETYP niepuste a niezmapowane → kind=unknown + event(kind.unmapped); frame i tak powstaje."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _write_fits(tree / "fw.fits",
                cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "FlatWizard")],
                data=np.zeros((4, 4), np.uint16))
    s = scan_tree(con, tree, now=NOW)
    assert s.kind_unmapped == 1
    assert con.execute("SELECT kind FROM frame").fetchone()[0] == "unknown"
    assert con.execute("SELECT count(*) FROM event WHERE verb='kind.unmapped'").fetchone()[0] == 1
    con.close()


def test_scan_tree_jedna_klinga_kazdy_zapis_ma_event(tmp_path):
    """Jedna klinga w działaniu: liczność każdej encji == liczność jej eventu (frame/location/
    header/camera). To inwariant „baza = autorytet" zweryfikowany na realnym przebiegu."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _write_fits(tree / "l.fits",
                cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT")],
                data=np.zeros((4, 4), np.uint16))
    _write_xisf(tree / "m.xisf",
                keywords=[("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                          ("BAYERPAT", "'RGGB'"), ("IMAGETYP", "'Master Flat'")])
    scan_tree(con, tree, now=NOW)
    for entity, verb in [("frame", "frame.observed"), ("location", "location.added"),
                         ("header", "header.recorded"), ("camera", "camera.upserted")]:
        n_entity = con.execute(f"SELECT count(*) FROM {entity}").fetchone()[0]
        n_event = con.execute("SELECT count(*) FROM event WHERE verb=?", (verb,)).fetchone()[0]
        assert n_entity == n_event, f"{entity}: {n_entity} encji vs {n_event} eventów"
    con.close()


# ---------------------------------------------------------------------------------------------------
# Skan przyrostowy (brama §3.B) + hooki progresu/anulowania (PLAN_gui_pipeline §3) — R3/R6/R7.
# FS = tmp_path (logika lookupu). Firsthand na realnym FS (USB/NAS, precyzja st_mtime) = Etap 4.
# ---------------------------------------------------------------------------------------------------

def _light(path, n=0):
    """Czytelny light-FITS o UNIKALNEJ treści (data=n) → unikalny sha1 (różne frame'y)."""
    return _write_fits(path, cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                                    ("IMAGETYP", "LIGHT")], data=np.full((4, 4), n, np.uint16))


def test_already_scanned_lookup_czysta_funkcja(tmp_path):
    """R7: czysta funkcja con→bool — trafia DOKŁADNIE po (volume, path, mtime); pudło na innym
    mtime / ścieżce / wolumenie. Lookup jest sercem bramy, testowany bez Qt."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _light(tree / "l.fits")
    scan_tree(con, tree, volume="VOL1", now=NOW)
    row = con.execute("SELECT path, mtime FROM location").fetchone()
    assert _already_scanned(con, "VOL1", row["path"], row["mtime"]) is True
    assert _already_scanned(con, "VOL1", row["path"], "2000-01-01T00:00:00+00:00") is False
    assert _already_scanned(con, "VOL1", row["path"] + "x", row["mtime"]) is False
    assert _already_scanned(con, "OTHER", row["path"], row["mtime"]) is False
    con.close()


def test_brama_re_skan_all_skip_zero_eventow(tmp_path):
    """R7a: skan z realnym wolumenem → re-skan = WSZYSTKO skipped, 0 frames_new, 0 NOWYCH eventów."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _light(tree / "a.fits", 1)
    _write_xisf(tree / "m.xisf", keywords=[("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                                           ("BAYERPAT", "'RGGB'"), ("IMAGETYP", "'Master Flat'")])
    s1 = scan_tree(con, tree, volume="VOL1", now=NOW)
    assert (s1.files, s1.frames_new, s1.skipped) == (2, 2, 0)
    ev1 = con.execute("SELECT count(*) FROM event").fetchone()[0]
    s2 = scan_tree(con, tree, volume="VOL1", now=NOW)
    assert (s2.files, s2.skipped, s2.frames_new, s2.frames_existing) == (2, 2, 0, 0)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == ev1   # brama nie pisze nic
    con.close()


def test_brama_skan_nadrzednego_czesciowy(tmp_path):
    """R7b: skan podfolderu, potem skan NADRZĘDNEGO → stary plik skipped, tylko nowy czytany."""
    con = _db(tmp_path)
    root = tmp_path / "root"; sub = root / "sub"; sub.mkdir(parents=True)
    _light(sub / "a.fits", 1)
    scan_tree(con, sub, volume="VOL1", now=NOW)
    _light(root / "b.fits", 2)                                  # nowy plik wyżej w drzewie
    s = scan_tree(con, root, volume="VOL1", now=NOW)            # skan nadrzędnego obejmuje oba
    assert (s.files, s.skipped, s.frames_new) == (2, 1, 1)      # a skipped, b nowy
    con.close()


def test_brama_zmiana_mtime_re_read(tmp_path):
    """R7c: zmiana mtime → PUDŁO → ponowny odczyt; treść ta sama → sha1 znany (frames_existing)."""
    import os
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    f = _light(tree / "l.fits", 1)
    scan_tree(con, tree, volume="VOL1", now=NOW)
    st = f.stat()
    os.utime(f, (st.st_atime, st.st_mtime + 100))              # przesuń mtime (treść bez zmian)
    s = scan_tree(con, tree, volume="VOL1", now=NOW)
    assert (s.skipped, s.frames_new, s.frames_existing) == (0, 0, 1)
    con.close()


def test_brama_move_dedup_bez_duplikatu(tmp_path):
    """R7d: plik PRZENIESIONY → pudło (nowa ścieżka) → odczyt → sha1 znany → frames_existing+1,
    NOWA location, BEZ duplikatu frame'a."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    f = _light(tree / "a.fits", 1)
    scan_tree(con, tree, volume="VOL1", now=NOW)
    shutil.move(str(f), str(tree / "b.fits"))                  # ta sama treść, inna ścieżka
    s = scan_tree(con, tree, volume="VOL1", now=NOW)
    assert (s.frames_new, s.frames_existing, s.skipped) == (0, 1, 0)
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1     # bez duplikatu
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 2  # a (stara) + b (nowa)
    con.close()


def test_brama_off_gdy_volume_placeholder(tmp_path):
    """R7e: volume='?' (serial nieustalony) → brama OFF → pełny skan; re-skan czyta PONOWNIE
    (frames_existing), NIC nie jest skipped (zero fałszywych pominięć)."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _light(tree / "l.fits", 1)
    scan_tree(con, tree, now=NOW)                              # volume domyślnie '?'
    s = scan_tree(con, tree, now=NOW)
    assert (s.skipped, s.frames_new, s.frames_existing) == (0, 0, 1)
    con.close()


def test_anulowanie_spojne_i_re_skan_dokancza(tmp_path):
    """R3: should_cancel→True po 1. pliku → break + cancelled=True; w bazie TYLKO w pełni przetworzone;
    re-skan (bez anulowania) dokańcza do sumy skanu nieprzerwanego, a 1. plik jest już skipped."""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    for i in range(3):
        _light(tree / f"l{i}.fits", i + 1)
    seen = {"done": 0}
    s = scan_tree(con, tree, volume="VOL1", now=NOW,
                  should_cancel=lambda: seen["done"] >= 1,          # anuluj PO pierwszym pliku
                  progress=lambda d, t, p, su: seen.__setitem__("done", d))
    assert s.cancelled is True and s.files == 1                     # granica pliku: tylko 1 dotknięty
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1   # tylko w pełni przetworzony
    s2 = scan_tree(con, tree, volume="VOL1", now=NOW)              # re-skan dokańcza
    assert s2.cancelled is False
    assert (s2.frames_new, s2.skipped) == (2, 1)                   # 2 dokończone, 1 już znany
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 3
    con.close()


def test_progress_wolany_per_plik_z_total(tmp_path):
    """R6: progress wołany po KAŻDYM pliku (też pominiętym), `done` rośnie 1..N, `total`=len(iter_headers)
    stały. (Snapshot/throttle/emisja sygnału Qt = warstwa GUI, testowana osobno bez rdzenia.)"""
    con = _db(tmp_path)
    tree = tmp_path / "t"; tree.mkdir()
    _light(tree / "a.fits", 1)
    _light(tree / "b.fits", 2)
    calls = []
    scan_tree(con, tree, volume="VOL1", now=NOW,
              progress=lambda d, t, p, su: calls.append((d, t)))
    assert calls == [(1, 2), (2, 2)]                              # total stały, done rośnie po każdym pliku
    con.close()


def test_ingest_record_replay_z_cache_bez_pliku(tmp_path):
    """`ingest_record` jako JĄDRO replayu: `ScanRecord` zbudowany z cache'owanego źródła (BEZ
    realnego pliku — nagłówek string-only, jak z `header_json`) → frame+location+header+event przez
    jedną klingę, pola gorące zrzutowane ze stringów (W3). To kontrakt, na którym stoi skrypt
    akceptacji §5 (replay custos.db header_json przez REALNY pipeline, nie atrapę)."""
    con = _db(tmp_path)
    rec = ScanRecord(
        path=r"X:\cache\NGC4258\sub.fits", sha1="a" * 40, size_bytes=123,
        mtime="2026-01-01T00:00:00+00:00",
        header={"INSTRUME": "ZWO ASI2600MM Pro", "XPIXSZ": "3.76", "IMAGETYP": "LIGHT",
                "OBJECT": "M106", "FOCALLEN": "784", "FOCRATIO": "5.6"})
    s = ScanSummary()
    ingest_record(con, rec, volume="VOL", now=NOW, summary=s)
    assert (s.frames_new, s.locations_new, s.headers) == (1, 1, 1)
    fid = con.execute("SELECT id FROM frame WHERE sha1=?", ("a" * 40,)).fetchone()[0]
    obj, focallen = con.execute(
        "SELECT object_raw, focallen FROM header WHERE frame_id=?", (fid,)).fetchone()
    assert obj == "M106" and focallen == 784.0          # string -> float (W3), jak w replayu
    for verb in ("frame.observed", "location.added", "header.recorded", "camera.upserted"):
        assert con.execute("SELECT count(*) FROM event WHERE verb=?", (verb,)).fetchone()[0] == 1
    con.close()
