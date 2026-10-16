"""Testy rdzenia żniw (`horreum.harvest`) - Qt-wolne.

Pokrycie: `discover` (prefiksy, rekurencja, stosy bez pochodnych obróbki, FITS poza), `input_stem`
(`_c`, wielkość liter, oba separatory), `read_master` z wstrzykniętymi czytnikami (rodzaj z derywacji
skanu, wejścia włączone, tożsamość nieobliczalna) i na PRAWDZIWYCH plikach XISF z historią (master
flat, stos z ekspozycją), `plan` na syntetycznej bazie z wstrzykniętym czytnikiem (każdy powód
z `REASONS` osobno, `exists` z bazy przed rodzajem i proweniencją, `exists` z dysku, świadek nazwy
z kopii nieobecnej, dedup po `frame_id`, siedziba z bazy pod innym korzeniem, z zestawu rodzeństwa
i złożona, cyfra kolejności, noc najwcześniejsza, manifest-świadek), stosy z wydań Horreum (macierz
negatywna: tożsamość pod `STACKS`, dopasowanie nazw wydania, siedziba z ogona lightów, nagłówek,
nazwa i jej kolizje, kalibracja cudzym masterem), `apply` (kopia przez prawdziwą klingę do
`tmp/CALIBRATION/...` i `tmp/STACKS/...`, anulowanie, `expected_sha1`, manifest `_ZNIWA.json`) oraz
lista wydań z kart celu (`releases`) liczona z dysku i z treści zeznań."""

from __future__ import annotations

import dataclasses
import json
import os
import struct
import types
from datetime import datetime

import pytest

from horreum import db, harvest, hashing, projection, repo, scan, stacks

NOW = "2026-10-10T12:00:00+00:00"
RAW_DIR = r"R:\ASTRO_\CALIBRATION\raw\76EDPH_2600MM\CLS"
DB_ROOT = r"R:\ASTRO_"


# ============================================================ baza syntetyczna


@pytest.fixture
def con(tmp_path):
    """Kamera mono 2600MM (1) i kolor 2600MC (2), teleskopy 76EDPH (1) i RC8 (2), configi 1×1 (id 1),
    1×2 (id 2) i 2×1 (id 3). Profil flatu CLS na 76EDPH+2600MM (`pid`) w `c.pid`."""
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, is_mono, created_at) VALUES ('ASI2600MM', 1, ?)", (NOW,))
    c.execute("INSERT INTO camera(model_canon, is_mono, created_at) VALUES ('ASI2600MC', 0, ?)", (NOW,))
    c.executemany("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, 'proposed', ?)",
                  [("76EDPH", NOW), ("RC8", NOW)])
    c.executemany("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                  "VALUES (?, ?, 'proposed', ?)", [(1, 1, NOW), (1, 2, NOW), (2, 1, NOW)])
    c.commit()
    yield c
    c.close()


def _profile(con, *, filtr="CLS", cam=1, tel=1, xbin=1):
    pid, _ = repo.upsert_calibration_profile(
        con, profile_key=f"flat|cam={cam}|bin={xbin}|tel={tel}|filt={filtr or '~'}", recipe_class="flat",
        camera_id=cam, xbinning=xbin, telescope_id=tel, filter_canon=filtr, now=NOW)
    return pid


def _raw_flat(con, name, *, profile=None, date_obs="2023-05-07T20:40:03", directory=RAW_DIR,
              present=1, sha=None):
    """Surowy flat pod `directory\\name` z nagłówkiem (noc z DATE-OBS) i profilem. Zwraca frame_id."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha or f"raw:{directory}:{name}", kind="flat",
                               filetype="fits", camera_id=1, now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", path=os.path.join(directory, name),
                               mtime="1", now=NOW)
    if not con.execute("SELECT 1 FROM header WHERE frame_id = ?", (fid,)).fetchone():
        repo.record_header(con, frame_id=fid, raw_json="{}", date_obs=date_obs, xbinning=1, now=NOW)
    if profile is not None:
        repo.assign_calibration_profile(con, frame_id=fid, profile_id=profile, now=NOW)
    if not present:
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (lid,))
        con.commit()
    return fid


def _master_in_db(con, path, *, profile, sha):
    """Master flat znany bazie pod `path` (siedziba profilu albo tożsamość `sha`)."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_flat", filetype="xisf", camera_id=1, now=NOW)
    repo.add_location(con, frame_id=fid, volume="V", path=path, mtime="1", now=NOW)
    repo.assign_calibration_profile(con, frame_id=fid, profile_id=profile, now=NOW)
    return fid


def _names(n, *, start=0, filtr="CLS"):
    return [f"2023-05-07_20-40-{i:02d}_{filtr}_-11.90_0.08s_{i:04d}.fits" for i in range(start, start + n)]


def _wbpp_input(raw_name):
    """Nazwa wejścia historii: surowy flat + `_c` + `.xisf` na dysku roboczym WBPP."""
    return f"D:/WBPP/2023-05-07/FLAT/{os.path.splitext(raw_name)[0]}_c.xisf"


# ============================================================ wyjście WBPP i czytnik wstrzykiwany


def _out(tmp_path, name="masterFlat_BIN-1_6248x4176_FILTER-CLS_mono.xisf", data=b"MASTER-DATA",
         sub="master"):
    p = tmp_path / "wbpp" / sub / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


def _testimony(src, *, inputs=(), kind="master_flat", imagetyp="Master Flat", rows=None, sha=None,
               filter_raw="CLS", xbinning=1):
    header = {} if imagetyp is None else {"IMAGETYP": imagetyp}
    return harvest.MasterTestimony(
        path=src, kind=kind, header=header, inputs_enabled=tuple(inputs),
        rows=len(inputs) if rows is None else rows, sha1_data=sha or f"data:{os.path.basename(src)}",
        file_sha1=hashing.sha1_of(src), filter_raw=filter_raw, xbinning=xbinning,
        date_obs="2023-05-07T18:39:22.863")


def _reader(testimonies):
    """`read` dla `plan`: po ścieżce; brak wpisu = błąd testu, nie cichy plik."""
    return lambda p: testimonies[p]


def _plan(con, tmp_path, testimonies, *, archive=None, manifest=None):
    archive = archive or str(tmp_path / "arch")
    return harvest.plan(con, str(tmp_path / "wbpp"), archive_root=archive, manifest=manifest,
                        read=_reader(testimonies))


def _one(p):
    assert len(p.items) == 1, p.items
    return p.items[0]


def _flaty(con, pid, n=3, **kw):
    names = _names(n, **kw)
    ids = [_raw_flat(con, nm, profile=pid) for nm in names]
    return names, ids


# ============================================================ discover / input_stem


def test_discover_prefiksy_rekurencja_stosy_bez_pochodnych_i_fits(tmp_path):
    """Stos `masterLight*` jest kandydatem, wariant `_autocrop` też; produkt obróbki obok
    (`…_starless`, `…_ABE`) i pliki bez prefiksu mastera (`HOS.xisf`) - nie. FITS i `.part` poza."""
    root = tmp_path / "wbpp"
    for rel in ("master/masterFlat_A.xisf", "master/deep/MASTERDARK_B.XISF", "masterBias_C.xisf",
                "master/masterLight_D.xisf", "master/masterFlat_E.fits", "master/flat_F.xisf",
                "master/masterFlat_A.xisf.part", "master/masterLight_D_autocrop.xisf",
                "master/masterLight_D_starless.xisf", "master/masterLight_D_ABE.xisf", "master/HOS.xisf",
                "master/masterLight_D.fits"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    found = [os.path.relpath(p, root).replace("\\", "/") for p in harvest.discover(str(root))]
    assert found == ["masterBias_C.xisf", "master/deep/MASTERDARK_B.XISF", "master/masterFlat_A.xisf",
                     "master/masterLight_D.xisf", "master/masterLight_D_autocrop.xisf"]
    assert harvest.discover(str(tmp_path / "brak")) == []


def test_input_stem_zmierzona_nazwa_i_separatory():
    assert harvest.input_stem("D:/WBPP/2023-05-07/FLAT/2023-05-07_20-40-03_CLS_-11.90_0.08s_0049_c.xisf") \
        == "2023-05-07_20-40-03_cls_-11.90_0.08s_0049"
    assert harvest.raw_stem(r"R:\ASTRO_\raw\2023-05-07_20-40-03_CLS_-11.90_0.08s_0049.fits") \
        == "2023-05-07_20-40-03_cls_-11.90_0.08s_0049"
    assert harvest.input_stem("x/FLAT_GRP-MM20251101_FILTER-H_EXP-16.38s_0000_-9.80C_C.XISF") \
        == "flat_grp-mm20251101_filter-h_exp-16.38s_0000_-9.80c"
    assert harvest.input_stem("a/b_cc.xisf") == "b_cc"             # inne sufiksy WBPP świadomie nie


def test_raw_stem_nie_zdejmuje_c_strony_bazy(con, tmp_path):
    """Surowy flat, którego WŁASNA nazwa kończy się na `_c`, ma w historii wejście `…_c_c.xisf`: strona
    bazy (`raw_stem`) zostawia `_c`, strona historii (`input_stem`) zdejmuje jedno - trafienie."""
    assert harvest.raw_stem(r"R:\raw\flat_0001_c.fits") == "flat_0001_c"
    assert harvest.input_stem("D:/w/flat_0001_c_c.xisf") == "flat_0001_c"
    pid = _profile(con)
    fid = _raw_flat(con, "flat_0001_c.fits", profile=pid)
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=["D:/w/flat_0001_c_c.xisf"])}))
    assert it.status == "would-place" and it.frame_ids == (fid,)


# ============================================================ read_master


def _xml_historii_flat(wejscia, *, wylaczone=()):
    """Nagłówek XISF z `PixInsight:ProcessingHistory` (treść zaescape'owana, jak w realnym pliku),
    tabela `images` z wejściami o nazwach surowych flatów + `imageData` z własnymi wierszami (wariant
    `tests/test_stacks.py::_xml_historii` z nazwami wejść, nie z temperaturami)."""
    wiersze = []
    for p in wejscia:
        on = "false" if p in wylaczone else "true"
        wiersze.append(f'&lt;tr&gt;&lt;td id="enabled" value="{on}"/&gt;&lt;td id="path"&gt;{p}'
                       f'&lt;/td&gt;&lt;/tr&gt;')
    return ('<Property id="PixInsight:ProcessingHistory" type="String">'
            f'&lt;table id="images" rows="{len(wejscia)}"&gt;{"".join(wiersze)}&lt;/table&gt;'
            '&lt;table id="imageData" rows="1"&gt;&lt;tr&gt;&lt;td id="enabled" value="false"/&gt;'
            '&lt;/tr&gt;&lt;/table&gt;</Property>')


def _meta(header, xml):
    return lambda _p: types.SimpleNamespace(header=header, xml_bytes=xml.encode("utf-8"))


def _identity(header, *, sha="d" * 40):
    return lambda p: scan.ScanRecord(path=str(p), size_bytes=1, mtime="t", header=header,
                                     sha1_data=sha, file_sha1="f" * 40)


@pytest.mark.parametrize("imagetyp, kind", [("Master Flat", "master_flat"), ("FLAT", "flat"),
                                            (None, "unknown"), ("Master Dark", "master_dark")])
def test_read_master_rodzaj_z_derywacji_skanu(imagetyp, kind):
    header = {"FILTER": "CLS", "XBINNING": "1", "DATE-OBS": "2023-05-07T18:39:22.863"}
    if imagetyp is not None:
        header["IMAGETYP"] = imagetyp
    wejscia = [_wbpp_input(n) for n in _names(3)]
    t = harvest.read_master(r"C:\w\masterFlat_X.xisf",
                            meta_reader=_meta(header, "<xisf>" + _xml_historii_flat(
                                wejscia, wylaczone=wejscia[1:2]) + "</xisf>"),
                            identity_reader=_identity(header))
    assert t.kind == kind
    assert t.inputs_enabled == (wejscia[0], wejscia[2]) and t.rows == 3
    assert (t.filter_raw, t.xbinning, t.date_obs) == ("CLS", 1, "2023-05-07T18:39:22.863")
    assert (t.sha1_data, t.file_sha1) == ("d" * 40, "f" * 40)


def test_read_master_bez_historii_i_tozsamosc_nieobliczalna():
    header = {"IMAGETYP": "Master Flat"}
    t = harvest.read_master("m.xisf", meta_reader=_meta(header, "<xisf/>"), identity_reader=_identity(header))
    assert t.rows is None and t.inputs_enabled == ()
    with pytest.raises(ValueError, match="nieobliczalna"):
        harvest.read_master("m.xisf", meta_reader=_meta(header, "<xisf/>"),
                            identity_reader=_identity(header, sha=None))


def _write_xisf_master(path, keywords, history_xml, payload=b"\x01\x02" * 16):
    """Minimalny monolityczny XISF z `<FITSKeyword>`, własnością historii i REALNYM attachmentem
    (offset liczony do punktu stałego, jak `tests/test_scan.py::_write_xisf_attach`)."""
    def xml_for(start):
        karty = "".join(f'<FITSKeyword name="{k}" value="{v}" comment=""/>' for k, v in keywords)
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" location="attachment:{start}:{len(payload)}">'
                + karty + '</Image>' + history_xml + '</xisf>').encode("utf-8")
    start = 0
    for _ in range(4):
        nowy = 16 + len(xml_for(start))
        if nowy == start:
            break
        start = nowy
    xml = xml_for(start)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + payload)
    return str(path)


def test_read_master_na_prawdziwym_xisf(tmp_path):
    """Domyślne czytniki (`scan.read_xisf_meta_full` + `scan.scan_file`) na pliku z historią: rodzaj,
    wejścia, karty i tożsamość danych z jednego przebiegu skanu."""
    wejscia = [_wbpp_input(n) for n in _names(2)]
    p = _write_xisf_master(tmp_path / "masterFlat_CLS.xisf",
                           [("IMAGETYP", "'Master Flat'"), ("FILTER", "'CLS'"), ("XBINNING", "1")],
                           _xml_historii_flat(wejscia))
    t = harvest.read_master(p)
    rec = scan.scan_file(p)
    assert t.kind == "master_flat" and t.inputs_enabled == tuple(wejscia) and t.rows == 2
    assert (t.sha1_data, t.file_sha1) == (rec.sha1_data, rec.file_sha1) == (rec.sha1_data, hashing.sha1_of(p))
    assert t.filter_raw == "CLS" and t.xbinning == 1


def test_scan_file_niesie_historie_z_tego_samego_odczytu(tmp_path):
    """`ScanRecord.history` = historia PixInsighta z XML-a, który skan i tak czyta (fala 4: rodzaj
    `AR-96` i rodowód stosów `AR-87` biorą ją stąd, bez drugiego odczytu udziału). Plik bez historii
    daje `rows is None`, a nie brak pola - „brak historii” to fakt, nie niewiedza."""
    wejscia = [_wbpp_input(n) for n in _names(2)]
    p = _write_xisf_master(tmp_path / "masterFlat_CLS.xisf", [("IMAGETYP", "'FLAT'")],
                           _xml_historii_flat(wejscia))
    rows, inputs, _tool = scan.scan_file(p).history
    assert rows == 2 and tuple(i.path for i in inputs if i.enabled) == tuple(wejscia)
    goly = _write_xisf_master(tmp_path / "flat.xisf", [("IMAGETYP", "'FLAT'")], "")
    assert scan.scan_file(goly).history[0] is None


# ============================================================ plan - ścieżka szczęśliwa i siedziba


def test_plan_would_place_siedziba_zlozona_i_fakty(con, tmp_path):
    pid = _profile(con)
    names, ids = _flaty(con, pid)
    src = _out(tmp_path)
    p = _plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])})
    it = _one(p)
    arch = str(tmp_path / "arch")
    assert it.status == "would-place" and it.reason is None
    assert it.profile_id == pid and it.frame_ids == tuple(sorted(ids)) and it.nights == ("2023-05-07",)
    assert it.zestaw == "76EDPH_ASI2600MM" and it.filter_segment == "CLS"
    assert it.name == "MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf"
    assert it.dst == os.path.join(arch, "CALIBRATION", "masters", "flats", "76EDPH_ASI2600MM", "CLS", it.name)
    assert p.wbpp_dir == str(tmp_path / "wbpp") and p.manifest_root is None and it.release is None


def test_plan_archive_root_pusty_valueerror(con, tmp_path):
    with pytest.raises(ValueError, match="archive_root"):
        harvest.plan(con, str(tmp_path), archive_root="", read=_reader({}))


def test_siedziba_z_bazy_pod_innym_korzeniem_idzie_pod_archive_root(con, tmp_path):
    """Katalog profilu z bazy (`R:\\ASTRO_\\CALIBRATION\\...`) + archiwum wskazane ręką w `tmp_path`
    → `dst` pod `tmp_path` z tym samym ogonem od `CALIBRATION`; najliczniejszy katalog wygrywa."""
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    for i in range(2):
        _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\76EDPH_2600MM\CLS\M{i}.xisf",
                      profile=pid, sha=f"m{i}")
    _master_in_db(con, rf"F:\kopia\CALIBRATION\masters\flats\Inny\CLS\M9.xisf", profile=pid, sha="m9")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert os.path.dirname(it.dst) == os.path.join(str(tmp_path / "arch"), "CALIBRATION", "masters",
                                                   "flats", "76EDPH_2600MM", "CLS")


def test_siedziba_ten_sam_ogon_pod_dwoma_korzeniami_sumuje_kopie(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\A\CLS\M0.xisf", profile=pid, sha="m0")
    _master_in_db(con, rf"F:\kopia\CALIBRATION\masters\flats\A\CLS\M1.xisf", profile=pid, sha="m1")
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\B\CLS\M2.xisf", profile=pid, sha="m2")
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\B\CLS\M3.xisf", profile=pid, sha="m3")
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\A\cls\M4.xisf", profile=pid, sha="m4")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert os.path.dirname(it.dst).endswith(os.path.join("flats", "A", "CLS"))   # 3 kopie A > 2 kopie B


def test_siedziba_katalog_bez_calibration_nie_liczy_sie(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    _master_in_db(con, r"E:\robocze\flaty\M0.xisf", profile=pid, sha="m0")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert os.path.dirname(it.dst) == os.path.join(str(tmp_path / "arch"), "CALIBRATION", "masters",
                                                   "flats", "76EDPH_ASI2600MM", "CLS")


def test_siedziba_z_zestawu_rodzenstwa(con, tmp_path):
    """Pierwszy master profilu (CLS) idzie do folderu zestawu, w którym archiwum trzyma mastery tej
    samej optyki innego filtru (`76EDPH_2600MM\\Ha`), nie do równoległego `76EDPH_ASI2600MM`.
    Rodzeństwo z folderem, którego ostatni segment nie jest jego filtrem, nie świadczy."""
    pid = _profile(con)
    ha = _profile(con, filtr="Ha")
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\76EDPH_2600MM\Ha\M0.xisf", profile=ha, sha="m0")
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert os.path.dirname(it.dst) == os.path.join(str(tmp_path / "arch"), "CALIBRATION", "masters",
                                                   "flats", "76EDPH_2600MM", "CLS")


def test_siedziba_rodzenstwo_bez_konwencji_filtru_nie_swiadczy(con, tmp_path):
    pid = _profile(con)
    ha = _profile(con, filtr="Ha")
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\76EDPH_2600MM\wszystkie\M0.xisf",
                  profile=ha, sha="m0")
    other_rig = _profile(con, filtr="OIII", tel=2)                    # inna optyka - nie rodzeństwo
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\RC8_2600MM\OIII\M1.xisf",
                  profile=other_rig, sha="m1")
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert os.path.dirname(it.dst).endswith(os.path.join("flats", "76EDPH_ASI2600MM", "CLS"))


# ============================================================ plan - tożsamość już w archiwum


def test_exists_z_bazy_wyprzedza_rodzaj_i_proweniencje(con, tmp_path):
    """Kopia bajtowa mastera znanego bazie jest „już w archiwum", choć jej wejścia są nieznane
    (stary warsztat), rodzaj nagłówka to `flat` albo plik jest masterdarkiem."""
    pid = _profile(con)
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\X\CLS\M.xisf", profile=pid, sha="znany")
    a = _out(tmp_path, "masterFlat_A.xisf")
    b = _out(tmp_path, "masterFlat_B.xisf")
    c = _out(tmp_path, "masterDark_C.xisf")
    p = _plan(con, tmp_path, {
        a: _testimony(a, inputs=["D:/stary/nieznany_0001_c.xisf"], sha="znany"),
        b: _testimony(b, inputs=[], kind="flat", imagetyp="FLAT", sha="znany"),
        c: _testimony(c, kind="master_dark", imagetyp="Master Dark", sha="znany")})
    assert [(it.status, it.exists_path, it.known_to_db) for it in p.items] == \
        [("exists", rf"{DB_ROOT}\CALIBRATION\masters\flats\X\CLS\M.xisf", True)] * 3


def test_aktywna_klatka_bez_obecnej_kopii_idzie_do_wciagniecia(con, tmp_path):
    """Baza zna te bajty, ale ŻADNA kopia nie leży na dysku: wyjście WBPP bywa jedyną kopią, więc plan
    idzie dalej (`would-place`), zamiast mówić „już w archiwum"."""
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    fid = _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\X\CLS\M.xisf", profile=pid, sha="znany")
    con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (fid,))
    con.commit()
    a = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {a: _testimony(a, inputs=[_wbpp_input(n) for n in names], sha="znany")}))
    assert it.status == "would-place" and it.exists_path is None


def test_klatka_wycofana_to_exists_z_data_wycofania(con, tmp_path):
    pid = _profile(con)
    fid = _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\X\CLS\M.xisf", profile=pid, sha="znany")
    con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (fid,))
    con.commit()
    assert repo.retire_frames(con, frame_ids=[fid], now=NOW).done == 1
    a = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {a: _testimony(a, sha="znany")}))
    assert (it.status, it.exists_path, it.detail) == ("exists", None, f"frame_id={fid} retired_at={NOW}")


def test_exists_z_dysku_te_same_bajty_pod_inna_cyfra(con, tmp_path):
    """Żniwa powtórzone przed Dostawą: w siedzibie leży plik grupy tej nocy i filtru z tymi samymi
    bajtami → `exists` z jego ścieżką, bez nowej nazwy."""
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    seat = tmp_path / "arch" / "CALIBRATION" / "masters" / "flats" / "76EDPH_ASI2600MM" / "CLS"
    seat.mkdir(parents=True)
    (seat / "MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf").write_bytes(b"INNY-MASTER")
    (seat / "MASTERFLAT_FLATGRP_202305073_FILTER_CLS_.xisf").write_bytes(b"MASTER-DATA")
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert it.status == "exists" and it.exists_path == str(seat / "MASTERFLAT_FLATGRP_202305073_FILTER_CLS_.xisf")
    assert it.known_to_db is False                       # wciągnięty, nieprzyjęty: przyjęcie ma czego szukać


# ============================================================ plan - cyfra kolejności


def test_cyfra_zero_zajeta_na_dysku_daje_jeden(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    seat = tmp_path / "arch" / "CALIBRATION" / "masters" / "flats" / "76EDPH_ASI2600MM" / "CLS"
    seat.mkdir(parents=True)
    (seat / "MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf").write_bytes(b"INNY")
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert it.status == "would-place" and it.name == "MASTERFLAT_FLATGRP_202305071_FILTER_CLS_.xisf"


def test_cyfra_zarezerwowana_przez_wczesniejsza_pozycje_planu(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid, n=4)
    a = _out(tmp_path, "masterFlat_A.xisf", data=b"A")
    b = _out(tmp_path, "masterFlat_B.xisf", data=b"B")
    p = _plan(con, tmp_path, {a: _testimony(a, inputs=[_wbpp_input(n) for n in names[:2]]),
                              b: _testimony(b, inputs=[_wbpp_input(n) for n in names[2:]])})
    assert [it.name for it in p.items] == ["MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf",
                                           "MASTERFLAT_FLATGRP_202305071_FILTER_CLS_.xisf"]


def test_dziesiec_zajetych_name_taken(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    seat = tmp_path / "arch" / "CALIBRATION" / "masters" / "flats" / "76EDPH_ASI2600MM" / "CLS"
    seat.mkdir(parents=True)
    for d in range(10):
        (seat / f"MASTERFLAT_FLATGRP_20230507{d}_FILTER_CLS_.xisf").write_bytes(b"x" * (d + 1))
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert (it.status, it.reason, it.reason_n) == ("review", "name_taken", 10)


# ============================================================ plan - świadek nazwy


def test_kopia_nieobecna_swiadczy_i_dedup_po_frame_id(con, tmp_path):
    """Surowy flat skasowany po wydaniu (kopia `present=0`) dalej jest rodzicem; ta sama klatka pod
    dwiema kopiami o jednej nazwie to JEDNO trafienie, nie wieloznaczność."""
    pid = _profile(con)
    names = _names(2)
    f0 = _raw_flat(con, names[0], profile=pid, present=0)
    f1 = _raw_flat(con, names[1], profile=pid, sha="raw:jeden")
    _raw_flat(con, names[1], profile=pid, sha="raw:jeden", directory=r"F:\kopia\raw")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert it.status == "would-place" and it.frame_ids == tuple(sorted((f0, f1)))


def test_noc_najwczesniejsza_przy_dwoch_nocach(con, tmp_path):
    pid = _profile(con)
    a = _raw_flat(con, "2023-05-08_20-00-00_CLS_0000.fits", profile=pid, date_obs="2023-05-08T21:00:00")
    b = _raw_flat(con, "2023-05-07_20-00-00_CLS_0000.fits", profile=pid, date_obs="2023-05-08T05:00:00")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[
        _wbpp_input("2023-05-08_20-00-00_CLS_0000.fits"), _wbpp_input("2023-05-07_20-00-00_CLS_0000.fits")])}))
    assert it.frame_ids == tuple(sorted((a, b)))
    assert it.nights == ("2023-05-07", "2023-05-08")                  # 05:00 należy do nocy poprzedniej
    assert it.name == "MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf"


# ============================================================ plan - każdy powód z REASONS


def test_unreadable_z_trescia_wyjatku(con, tmp_path):
    src = _out(tmp_path)

    def zly(_p):
        raise ValueError("nie XISF monolithic")
    it = _one(harvest.plan(con, str(tmp_path / "wbpp"), archive_root="A", read=zly))
    assert (it.status, it.reason, it.kind) == ("review", "unreadable", "unknown")
    assert "ValueError" in it.detail and "nie XISF" in it.detail


@pytest.mark.parametrize("name, kind, imagetyp", [("masterDark_X.xisf", "master_dark", "Master Dark"),
                                                  ("masterBias_X.xisf", "unknown", "Master Bias"),
                                                  ("masterFlat_X.xisf", "master_dark", "Master Dark")])
def test_no_raw_darks(con, tmp_path, name, kind, imagetyp):
    src = _out(tmp_path, name)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, kind=kind, imagetyp=imagetyp)}))
    assert (it.status, it.reason) == ("review", "no_raw_darks")


@pytest.mark.parametrize("kind, imagetyp", [("flat", "FLAT"), ("unknown", None)])
def test_header_mismatch_rodzaj_skanu_inny_niz_master_flat(con, tmp_path, kind, imagetyp):
    """Plik `masterFlat*`, któremu skan nada `flat` albo `unknown`, nie jest wciągany: wpisany do bazy
    jako surowy flat wróciłby do wydań jako wejście WBPP."""
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names],
                                                    kind=kind, imagetyp=imagetyp)}))
    assert (it.status, it.reason) == ("review", "header_mismatch")
    assert it.detail == f"IMAGETYP={imagetyp!r} -> {kind}"


def test_no_history_i_no_inputs(con, tmp_path):
    a = _out(tmp_path, "masterFlat_A.xisf")
    b = _out(tmp_path, "masterFlat_B.xisf")
    p = _plan(con, tmp_path, {a: dataclasses.replace(_testimony(a), rows=None),
                              b: _testimony(b, inputs=[], rows=4)})
    assert [(it.status, it.reason) for it in p.items] == [("review", "no_history"), ("review", "no_inputs")]


def test_inputs_unknown_liczy_i_cytuje_trzy_nazwy(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid, n=1)
    obce = [f"D:/w/obcy_{i}_c.xisf" for i in range(5)]
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(names[0]), *obce])}))
    assert (it.status, it.reason, it.reason_n) == ("review", "inputs_unknown", 5)
    assert it.detail == "obcy_0_c.xisf, obcy_1_c.xisf, obcy_2_c.xisf"


def test_inputs_ambiguous_dwie_klatki_pod_jedna_nazwa(con, tmp_path):
    pid = _profile(con)
    name = _names(1)[0]
    _raw_flat(con, name, profile=pid)
    _raw_flat(con, name, profile=pid, directory=r"R:\ASTRO_\CALIBRATION\raw\inny")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(name)])}))
    assert (it.status, it.reason, it.reason_n) == ("review", "inputs_ambiguous", 1)


def test_no_profile_i_mixed_profile(con, tmp_path):
    cls, ha = _profile(con), _profile(con, filtr="Ha")
    bez = _raw_flat(con, "bez_profilu_0001.fits")
    a = _raw_flat(con, "a_0001.fits", profile=cls)
    b = _raw_flat(con, "b_0001.fits", profile=ha)
    assert bez and a and b
    s1 = _out(tmp_path, "masterFlat_1.xisf")
    s2 = _out(tmp_path, "masterFlat_2.xisf")
    p = _plan(con, tmp_path, {
        s1: _testimony(s1, inputs=[_wbpp_input("bez_profilu_0001.fits"), _wbpp_input("a_0001.fits")]),
        s2: _testimony(s2, inputs=[_wbpp_input("a_0001.fits"), _wbpp_input("b_0001.fits")])})
    assert [(it.reason, it.reason_n) for it in p.items] == [("no_profile", 1), ("mixed_profile", 2)]
    assert p.items[1].detail == f"{cls}, {ha}"


def test_no_night(con, tmp_path):
    pid = _profile(con)
    _raw_flat(con, "bez_daty_0001.fits", profile=pid, date_obs=None)
    _raw_flat(con, "z_data_0001.fits", profile=pid)
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input("bez_daty_0001.fits"),
                                                                 _wbpp_input("z_data_0001.fits")])}))
    assert (it.status, it.reason, it.reason_n) == ("review", "no_night", 1)


@pytest.mark.parametrize("zmiana, fragment", [({"filter_raw": "H"}, "FILTER"),
                                              ({"xbinning": 2}, "XBINNING"),
                                              ({"xbinning": None}, "XBINNING")])
def test_header_mismatch_filtr_albo_binning(con, tmp_path, zmiana, fragment):
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    t = dataclasses.replace(_testimony(src, inputs=[_wbpp_input(n) for n in names]), **zmiana)
    it = _one(_plan(con, tmp_path, {src: t}))
    assert (it.status, it.reason) == ("review", "header_mismatch") and fragment in it.detail


def test_filtr_surowy_h_kanonizowany_zgadza_sie_z_ha(con, tmp_path):
    """`FILTER='H'` mastera (forma surowa) to kanon `Ha` - zgodny z profilem, nie odmowa."""
    pid = _profile(con, filtr="Ha")
    names, _ = _flaty(con, pid, filtr="H")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names],
                                                    filter_raw="H")}))
    assert it.status == "would-place" and it.filter_segment == "Ha"


def test_osc_bez_filtra_folder_osc(con, tmp_path):
    pid = _profile(con, filtr=None, cam=2)
    names, _ = _flaty(con, pid, filtr="OSC")
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names],
                                                    filter_raw=None)}))
    assert it.status == "would-place" and it.filter_segment == "OSC"
    assert it.dst.endswith(os.path.join("76EDPH_ASI2600MC", "OSC", "MASTERFLAT_FLATGRP_202305070_FILTER_OSC_.xisf"))


def test_no_config_brak_configu_i_brak_filtra_na_mono(con, tmp_path):
    con.execute("INSERT INTO camera(model_canon, is_mono, created_at) VALUES ('ASI294MM', 1, ?)", (NOW,))
    con.commit()
    bez_configu = _profile(con, cam=3)                                # para 76EDPH × ASI294MM nie ma configu
    mono_bez_filtra = _profile(con, filtr=None)
    _raw_flat(con, "a_0001.fits", profile=bez_configu)
    _raw_flat(con, "b_0001.fits", profile=mono_bez_filtra)
    s1 = _out(tmp_path, "masterFlat_1.xisf")
    s2 = _out(tmp_path, "masterFlat_2.xisf")
    p = _plan(con, tmp_path, {s1: _testimony(s1, inputs=[_wbpp_input("a_0001.fits")]),
                              s2: _testimony(s2, inputs=[_wbpp_input("b_0001.fits")], filter_raw=None)})
    assert [(it.status, it.reason) for it in p.items] == [("review", "no_config"), ("review", "no_config")]
    assert p.items[0].detail.endswith("config_id=None") and "filter_canon=None" in p.items[1].detail


def test_manifest_swiadek_release_i_outside_release(con, tmp_path):
    pid = _profile(con)
    names, ids = _flaty(con, pid, n=4)
    a = _out(tmp_path, "masterFlat_A.xisf", data=b"A")
    b = _out(tmp_path, "masterFlat_B.xisf", data=b"B")
    manifest = {"layout": projection.OBJECT_LAYOUT, "object_canon": "Cr464", "root": r"R:\_WBPP\OBJECTS\Cr464",
                "zestawy": {"76EDPH_ASI2600MM": {"flat_raw": ids[:2]}, "RC8_ASI2600MM": {"flat_raw": []}}}
    p = _plan(con, tmp_path, {a: _testimony(a, inputs=[_wbpp_input(n) for n in names[:2]]),
                              b: _testimony(b, inputs=[_wbpp_input(n) for n in names[1:3]])},
              manifest=manifest)
    assert p.manifest_root == r"R:\_WBPP\OBJECTS\Cr464"
    assert (p.items[0].status, p.items[0].release) == ("would-place", ("Cr464", "76EDPH_ASI2600MM"))
    assert (p.items[1].status, p.items[1].reason) == ("review", "outside_release")


def test_manifest_innego_ukladu_nie_jest_swiadkiem(con, tmp_path):
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    p = _plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])},
              manifest={"layout": "wbpp-feed", "root": "X", "zestawy": {}})
    assert _one(p).status == "would-place" and _one(p).release is None and p.manifest_root is None


def test_segment_filtru_odrzucony_przez_nazwe_to_no_config_nie_wyjatek_planu(con, tmp_path):
    """Filtr verbatim ze spacją (`normalize_filter` nie zna `Duo Band`) daje segment `Duo_Band`, którego
    `master_flat_name` nie przyjmie: pozycja `no_config` z danymi, a reszta planu się liczy."""
    lpro = _profile(con, filtr="Duo Band")
    cls = _profile(con)
    _raw_flat(con, "lpro_0001.fits", profile=lpro)
    names, _ = _flaty(con, cls)
    a = _out(tmp_path, "masterFlat_A.xisf", data=b"A")
    b = _out(tmp_path, "masterFlat_B.xisf", data=b"B")
    p = _plan(con, tmp_path, {a: _testimony(a, inputs=[_wbpp_input("lpro_0001.fits")], filter_raw="Duo Band"),
                              b: _testimony(b, inputs=[_wbpp_input(n) for n in names])})
    assert [(it.status, it.reason) for it in p.items] == [("review", "no_config"), ("would-place", None)]
    assert p.items[0].detail == "master_flat_name: night8='20230507' filter_segment='Duo_Band'"


def test_profil_spoza_profili_flatu_to_no_profile_nie_keyerror(con, tmp_path):
    dark, _ = repo.upsert_calibration_profile(
        con, profile_key="dark|cam=1|bin=1|exp=300.000|t=-10|g=100|o=21", recipe_class="dark",
        camera_id=1, xbinning=1, exptime=300.0, set_temp_c=-10, gain=100, offset_adu=21, now=NOW)
    _raw_flat(con, "x_0001.fits", profile=dark)
    src = _out(tmp_path)
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input("x_0001.fits")])}))
    assert (it.status, it.reason, it.detail) == ("review", "no_profile", f"profile_id={dark}")


@pytest.mark.parametrize("pod", [("CALIBRATION",), ("calibration", "masters")])
def test_archive_root_z_segmentem_calibration_bez_podwojenia(con, tmp_path, pod):
    """Wskazanie `…\\CALIBRATION` (albo głębiej) jako archiwum: korzeń to część przed segmentem, więc
    siedziba nie dostaje `CALIBRATION\\CALIBRATION` - ani złożona, ani z ogona katalogu z bazy."""
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    arch = str(tmp_path.joinpath("arch", *pod))
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}, archive=arch))
    assert os.path.dirname(it.dst) == os.path.join(str(tmp_path / "arch"), "CALIBRATION", "masters", "flats",
                                                   "76EDPH_ASI2600MM", "CLS")
    _master_in_db(con, rf"{DB_ROOT}\CALIBRATION\masters\flats\76EDPH_2600MM\CLS\M.xisf", profile=pid, sha="m0")
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}, archive=arch))
    assert os.path.dirname(it.dst) == os.path.join(str(tmp_path / "arch"), "CALIBRATION", "masters", "flats",
                                                   "76EDPH_2600MM", "CLS")


@pytest.mark.parametrize("wskazane, korzen", [
    (r"R:\ASTRO_\STACKS", r"R:\ASTRO_"),
    (r"R:\ASTRO_\stacks\X", r"R:\ASTRO_"),
    (r"R:\ASTRO_\CALIBRATION", r"R:\ASTRO_"),
    (r"R:\ASTRO_\CALIBRATION\masters\STACKS", r"R:\ASTRO_"),                # pierwszy od korzenia
    (r"R:\ASTRO_", r"R:\ASTRO_"),
])
def test_library_root_tnie_przed_calibration_albo_stacks(wskazane, korzen):
    """Archiwum wskazane na bibliotekę (`…\\STACKS` - podpowiedź okna, `…\\CALIBRATION`) albo głębiej:
    korzeń to część przed PIERWSZYM takim segmentem; ścieżka bez segmentu wraca bez zmian."""
    assert harvest.library_root(wskazane) == korzen


@pytest.mark.parametrize("wskazane", ["STACKS", os.path.join("stacks", "X"), "CALIBRATION"])
def test_library_root_bez_korzenia_przed_biblioteka_valueerror(wskazane):
    with pytest.raises(ValueError, match="bez korzenia przed"):
        harvest.library_root(wskazane)


def test_archiwum_wskazane_na_stacks_bez_podwojenia_dla_stosu_i_mastera(con, tmp_path):
    """Wskazanie `<archiwum>\\STACKS`: stos idzie do `<archiwum>\\STACKS\\<obiekt>\\…` (nie
    `STACKS\\STACKS`), master flat do `<archiwum>\\CALIBRATION\\…` (nie `STACKS\\CALIBRATION`)."""
    pid = _profile(con)
    flaty, flat_ids = _flaty(con, pid)
    master = _out(tmp_path, "masterFlat_A.xisf", data=b"FLAT")
    src, names, ids, t = _stos_z_wydania(con, tmp_path)
    manifest = _wydanie(tmp_path, {ZESTAW: (names, ids)})
    manifest["zestawy"][ZESTAW]["flat_raw"] = flat_ids
    p = _plan(con, tmp_path, {master: _testimony(master, inputs=[_wbpp_input(n) for n in flaty]), src: t},
              archive=str(tmp_path / "arch" / "STACKS"), manifest=manifest)
    assert p.archive_root == str(tmp_path / "arch")
    flat, stos = p.items
    assert stos.dst == os.path.join(_seat(tmp_path), NAZWA_STOSU)
    assert os.path.dirname(flat.dst) == os.path.join(str(tmp_path / "arch"), "CALIBRATION", "masters", "flats",
                                                     "76EDPH_ASI2600MM", "CLS")


def test_porzucony_part_zajmuje_nazwe(con, tmp_path):
    """`.part` po przerwanej kopii zajmuje cyfrę: plan bierze następną, zamiast dać klindze wieczny
    `conflict`."""
    pid = _profile(con)
    names, _ = _flaty(con, pid)
    src = _out(tmp_path)
    seat = tmp_path / "arch" / "CALIBRATION" / "masters" / "flats" / "76EDPH_ASI2600MM" / "CLS"
    seat.mkdir(parents=True)
    (seat / ("MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf" + projection.PART_SUFFIX)).write_bytes(b"PRZERWANA")
    it = _one(_plan(con, tmp_path, {src: _testimony(src, inputs=[_wbpp_input(n) for n in names])}))
    assert it.status == "would-place" and it.name == "MASTERFLAT_FLATGRP_202305071_FILTER_CLS_.xisf"


def test_anulowanie_sondy_discover_i_plan_bez_planu_czesciowego(con, tmp_path):
    a = _out(tmp_path, "masterFlat_A.xisf")
    b = _out(tmp_path, "masterFlat_B.xisf")
    with pytest.raises(harvest.HarvestCancelled):
        harvest.discover(str(tmp_path / "wbpp"), should_cancel=lambda: True)
    czytane, flaga = [], []

    def read(p):
        czytane.append(p)
        flaga.append(True)                                 # anulowanie przychodzi w trakcie pierwszego pliku
        return _testimony(p)
    with pytest.raises(harvest.HarvestCancelled):
        harvest.plan(con, str(tmp_path / "wbpp"), archive_root=str(tmp_path / "arch"), read=read,
                     should_cancel=lambda: bool(flaga))
    assert czytane == [a] and b not in czytane


def test_archive_root_from_db_najliczniejszy_prefiks_przed_calibration(con):
    assert harvest.archive_root_from_db(con) is None
    pid = _profile(con)
    for i in range(2):
        _master_in_db(con, rf"R:\ASTRO_\CALIBRATION\masters\flats\A\CLS\M{i}.xisf", profile=pid, sha=f"r{i}")
    _master_in_db(con, r"r:\astro_\calibration\masters\flats\B\CLS\M2.xisf", profile=pid, sha="r2")
    _master_in_db(con, r"F:\kopia\CALIBRATION\masters\flats\A\CLS\M3.xisf", profile=pid, sha="f3")
    for i in range(5):
        _master_in_db(con, rf"E:\robocze\flaty\M{i}.xisf", profile=pid, sha=f"e{i}")   # bez CALIBRATION
    assert harvest.archive_root_from_db(con) == r"R:\ASTRO_"
    for i in range(2):
        _master_in_db(con, rf"F:\kopia\CALIBRATION\masters\flats\A\CLS\N{i}.xisf", profile=pid, sha=f"f{i}x")
    assert harvest.archive_root_from_db(con) == r"F:\kopia"           # remis 3:3 → alfabetycznie


# ============================================================ plan - stosy z wydań Horreum

LIGHTS_HA = rf"{DB_ROOT}\LIGHTS\IC1795\76EDPH_2600MM\Ha"
ZESTAW = "76EDPH_ASI2600MM"
STOS_WBPP = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-H_mono.xisf"
NAZWA_STOSU = "IC1795_2025-12-16_76EDPH_2600MM_Ha_600s_mono.xisf"


def _kopia(con, fid, path, present=1):
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, ?)",
                (fid, path, present))
    con.commit()


def _light(con, name, *, directory=LIGHTS_HA, config_id=1, camera_id=1, filter_canon="Ha", exptime=600.0,
           kind="light"):
    """Light pod `directory\\name` (obecna kopia) z osią filtru, configu, kamery i ekspozycją."""
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, filter_canon, first_seen_at) "
        "VALUES (?, ?, 'fits', ?, ?, ?, ?)",
        (f"light:{directory}:{name}", kind, camera_id, config_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime) VALUES (?, '{}', ?, ?)",
                (fid, "2025-12-16T17:27:54", exptime))
    con.commit()
    _kopia(con, fid, os.path.join(directory, name))
    return fid


def _lighty(con, n=3, *, start=0, **kw):
    names = [f"20251216_1727{i:02d}_IC1795_LIGHT_Ha_600s_{i:012x}.fits" for i in range(start, start + n)]
    return names, [_light(con, nm, **kw) for nm in names]


def _wejscie(light_name, kroki="_c_r"):
    """Wejście historii stosu: nazwa lightu wydania + `_c` + kroki WBPP na dysku roboczym WBPP."""
    return f"C:/WBPP/registered/{os.path.splitext(light_name)[0]}{kroki}.xisf"


def _wydanie(tmp_path, zestawy, *, object_canon="IC1795"):
    """Manifest wydania obiektu; `zestawy` = `{seg: (names | None, ids)}` - `None` = manifest zapisany
    przed polem `names`."""
    z = {}
    for seg, (names, ids) in zestawy.items():
        z[seg] = {"lights": list(ids)}
        if names is not None:
            z[seg]["names"] = dict(zip(names, ids))
    return {"layout": projection.OBJECT_LAYOUT, "object_canon": object_canon,
            "root": str(tmp_path / "_WBPP" / "OBJECTS" / object_canon), "zestawy": z}


def _stos(src, inputs, *, sha=None, filter_raw="H", exptime=600.0, telescop="76EDPH",
          instrume="ZWO ASI2600MM Pro", date_obs="2025-12-16T17:27:54", rows=None):
    """Zeznanie stosu WBPP (`IMAGETYP='Master Light'`) z kartami, które plan porównuje z lightami."""
    header = {"IMAGETYP": "Master Light", "FILTER": filter_raw, "TELESCOP": telescop, "INSTRUME": instrume,
              "DATE-OBS": date_obs, "EXPTIME": None if exptime is None else f"{exptime:.3f}"}
    return harvest.MasterTestimony(
        path=src, kind="master_light", header={k: v for k, v in header.items() if v is not None},
        inputs_enabled=tuple(inputs), rows=len(inputs) if rows is None else rows,
        sha1_data=sha or f"stos:{os.path.basename(src)}", file_sha1=hashing.sha1_of(src),
        filter_raw=filter_raw, xbinning=1, date_obs=date_obs, exptime=exptime)


def _seat(tmp_path, *ogon):
    return str(tmp_path.joinpath("arch", "STACKS", *(ogon or ("IC1795", "76EDPH_2600MM", "Ha"))))


def _stos_z_wydania(con, tmp_path, *, n=3, data=b"STOS-HA", name=STOS_WBPP, **kw):
    """Stos z wydania IC1795: `n` lightów w archiwum, historia = wszystkie ich nazwy + `_c_r`."""
    names, ids = _lighty(con, n)
    src = _out(tmp_path, name, data=data)
    return src, names, ids, _stos(src, [_wejscie(nm) for nm in names], **kw)


def test_stos_z_wydania_would_place_do_stacks_po_ogonie_lightow(con, tmp_path):
    """Ścieżka szczęśliwa: wejścia = nazwy lightów wydania + `_c_r` (WBPP odrzucił jeden light - zbiór
    DOKŁADNY to dwa), siedziba = ogon lightów pod `STACKS` archiwum, nazwa z konwencji archiwum."""
    names, ids = _lighty(con, 3)
    src = _out(tmp_path, STOS_WBPP, data=b"STOS-HA")
    p = _plan(con, tmp_path, {src: _stos(src, [_wejscie(nm) for nm in names[:2]])},
              manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)}))
    it = _one(p)
    assert (it.status, it.kind, it.reason) == ("would-place", "master_light", None)
    assert it.frame_ids == tuple(sorted(ids[:2])) and it.release == ("IC1795", ZESTAW) and it.zestaw == ZESTAW
    assert it.dst == os.path.join(_seat(tmp_path), NAZWA_STOSU) and it.name == NAZWA_STOSU
    assert it.filter_segment == "Ha" and it.known_to_db is True
    assert p.archive_root == str(tmp_path / "arch")


def test_stos_znany_bazie_z_kopia_poza_archiwum_idzie_do_wciagniecia(con, tmp_path):
    """Stos wciągnięty drogą „Stosy” z drzewa obróbki jest znany bazie, ale w `STACKS` archiwum go nie
    ma → `would-place`. Obecna kopia pod `<archiwum>\\STACKS` → `exists` z jej ścieżką."""
    src, names, ids, t = _stos_z_wydania(con, tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data=t.sha1_data, kind="master_light", filetype="xisf",
                               camera_id=1, now=NOW)
    _kopia(con, fid, os.path.join(r"C:\WBPP\obrobka\master", STOS_WBPP))
    manifest = _wydanie(tmp_path, {ZESTAW: (names, ids)})
    it = _one(_plan(con, tmp_path, {src: t}, manifest=manifest))
    assert (it.status, it.exists_path) == ("would-place", None)
    w_archiwum = os.path.join(_seat(tmp_path), NAZWA_STOSU)
    _kopia(con, fid, w_archiwum)
    it = _one(_plan(con, tmp_path, {src: t}, manifest=manifest))
    assert (it.status, it.exists_path, it.known_to_db) == ("exists", w_archiwum, True)


def test_stos_klatka_wycofana_exists(con, tmp_path):
    src, names, ids, t = _stos_z_wydania(con, tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data=t.sha1_data, kind="master_light", filetype="xisf",
                               camera_id=1, now=NOW)
    _kopia(con, fid, os.path.join(_seat(tmp_path), NAZWA_STOSU), present=0)
    assert repo.retire_frames(con, frame_ids=[fid], now=NOW).done == 1
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert (it.status, it.exists_path, it.detail) == ("exists", None, f"frame_id={fid} retired_at={NOW}")


def test_stos_drugi_plan_po_apply_bez_dostawy_exists_bez_nowych_plikow(con, tmp_path):
    """Żniwa powtórzone przed Dostawą: te same bajty w siedzibie → `exists`, zero nowych plików.
    Baza tej kopii nie zna (`known_to_db=False`), więc przyjęcie ma czego szukać, choć bieg nie
    położył nic nowego - drugi `apply` nie ma `placed`."""
    src, names, ids, t = _stos_z_wydania(con, tmp_path)
    manifest = _wydanie(tmp_path, {ZESTAW: (names, ids)})
    r = harvest.apply(_plan(con, tmp_path, {src: t}, manifest=manifest), now=NOW)
    assert [it.status for it in r.items] == ["placed"] and r.placed_dirs == [_seat(tmp_path)]
    drugi = _plan(con, tmp_path, {src: t}, manifest=manifest)
    it = _one(drugi)
    assert (it.status, it.exists_path, it.known_to_db) == ("exists", os.path.join(_seat(tmp_path), NAZWA_STOSU),
                                                           False)
    r2 = harvest.apply(drugi, now=NOW, copy=lambda *a, **k: pytest.fail("kopia bez pozycji would-place"))
    assert r2.placed_dirs == [] and os.listdir(_seat(tmp_path)) == [NAZWA_STOSU]
    zeznanie = json.load(open(r2.manifest_path, encoding="utf-8"))
    assert zeznanie["items"][0]["known_to_db"] is False and zeznanie["archive_root"] == str(tmp_path / "arch")


def test_stos_wejscie_crop_nie_trafia_w_light(con, tmp_path):
    """`<light>_crop_c_r` nie jest wejściem lightu `<light>`: po `_c` stoi `r`, nie `_` - prefiks nazwy
    nie wystarcza."""
    names, ids = _lighty(con, 1)
    src = _out(tmp_path, STOS_WBPP)
    obce = _wejscie(names[0], "_crop_c_r")
    it = _one(_plan(con, tmp_path, {src: _stos(src, [obce])},
                    manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert (it.status, it.reason, it.reason_n, it.detail) == \
        ("review", "outside_release", 1, os.path.basename(obce))


def test_stos_wejscie_inna_wielkosc_liter_trafia(con, tmp_path):
    names, ids = _lighty(con, 2)
    src = _out(tmp_path, STOS_WBPP)
    wejscia = [_wejscie(nm).upper() for nm in names]
    it = _one(_plan(con, tmp_path, {src: _stos(src, wejscia)},
                    manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert it.status == "would-place" and it.frame_ids == tuple(sorted(ids))


def test_stos_remis_dwoch_lightow_inputs_ambiguous(con, tmp_path):
    """Wejście `a_c_c_r` pasuje do lightu `a` (kroki `_c_r`) i do lightu `a_c` (krok `_r`) - remis to
    odmowa, nie wybór; nazwa dwóch klatek w manifeście (`None`) też."""
    a = _light(con, "a.fits")
    ac = _light(con, "a_c.fits")
    src = _out(tmp_path, STOS_WBPP)
    it = _one(_plan(con, tmp_path, {src: _stos(src, ["C:/WBPP/registered/a_c_c_r.xisf"])},
                    manifest=_wydanie(tmp_path, {ZESTAW: (["a.fits", "a_c.fits"], [a, ac])})))
    assert (it.status, it.reason, it.reason_n) == ("review", "inputs_ambiguous", 1)
    kolizja = _wydanie(tmp_path, {ZESTAW: (["a.fits"], [a])})
    kolizja["zestawy"][ZESTAW]["names"]["a.fits"] = None
    it = _one(_plan(con, tmp_path, {src: _stos(src, [_wejscie("a.fits")])}, manifest=kolizja))
    assert (it.status, it.reason) == ("review", "inputs_ambiguous")


def test_stos_rename_lightu_po_wydaniu_z_names_trafia_bez_names_outside_release(con, tmp_path):
    """Nazwa lightu w bazie zmieniła się po wydaniu: manifest z `names` (nazwy, pod którymi WBPP dostał
    klatki) dalej trafia; manifest sprzed tego pola bierze nazwy z bazy i nazwy historii już nie zna."""
    names, ids = _lighty(con, 2)
    con.execute("UPDATE location SET path = ? WHERE frame_id = ?",
                (os.path.join(LIGHTS_HA, "20251216_172700_IC1795_LIGHT_Ha_600s_przemianowany.fits"), ids[0]))
    con.commit()
    src = _out(tmp_path, STOS_WBPP)
    t = _stos(src, [_wejscie(nm) for nm in names])
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert it.status == "would-place" and it.frame_ids == tuple(sorted(ids))
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {ZESTAW: (None, ids)})))
    assert (it.status, it.reason, it.reason_n) == ("review", "outside_release", 1)
    assert it.detail == os.path.basename(_wejscie(names[0]))


def test_stos_kamera_kolorowa_osc_do_nofilter(con, tmp_path):
    """`LIGHTS\\…\\OSC` ↔ `STACKS\\…\\NoFilter` - jedyna translacja ogona; filtr i nazwa `NoFilter`."""
    osc = rf"{DB_ROOT}\LIGHTS\IC5068\76EDPH_2600MC\OSC"
    names = [f"20230821_2100{i:02d}_IC5068_LIGHT_60s_{i:012x}.fits" for i in range(2)]
    ids = [_light(con, nm, directory=osc, config_id=2, camera_id=2, filter_canon=None, exptime=60.0)
           for nm in names]
    src = _out(tmp_path, "masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter_RGB.xisf")
    t = _stos(src, [_wejscie(nm, "_c_d_r") for nm in names], filter_raw="NoFilter", exptime=60.0,
              instrume="ZWO ASI2600MC Pro", date_obs="2023-08-21T21:00:00")
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {"76EDPH_ASI2600MC": (names, ids)},
                                                               object_canon="IC5068")))
    assert it.status == "would-place" and it.filter_segment == "NoFilter"
    assert it.dst == os.path.join(_seat(tmp_path, "IC5068", "76EDPH_2600MC", "NoFilter"),
                                  "IC5068_2023-08-21_76EDPH_2600MC_NoFilter_60s_RGB.xisf")


@pytest.mark.parametrize("nazwa, koncowka", [
    ("masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter__R.xisf", "_NoFilter_60s_R.xisf"),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter_RGB.xisf", "_NoFilter_60s_RGB.xisf"),
    ("masterLight_BIN-1_6248x4176_EXPOSURE-60.00s_FILTER-NoFilter_RGB_drizzle_1x.xisf",
     "_NoFilter_60s_RGB_drizzle_1x.xisf"),
])
def test_stos_kanal_rgb_i_drizzle_w_nazwie(con, tmp_path, nazwa, koncowka):
    osc = rf"{DB_ROOT}\LIGHTS\IC5068\76EDPH_2600MC\OSC"
    names = ["20230821_210000_IC5068_LIGHT_60s_a.fits"]
    ids = [_light(con, names[0], directory=osc, config_id=2, camera_id=2, filter_canon=None, exptime=60.0)]
    src = _out(tmp_path, nazwa)
    t = _stos(src, [_wejscie(names[0], "_c_d_r")], filter_raw="NoFilter", exptime=60.0,
              instrume="ZWO ASI2600MC Pro", date_obs="2023-08-21T21:00:00")
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {"76EDPH_ASI2600MC": (names, ids)})))
    assert it.status == "would-place" and it.name == "IC5068_2023-08-21_76EDPH_2600MC" + koncowka


@pytest.mark.parametrize("zmiana, os_naglowka", [
    ({"telescop": "RC8"}, "TELESCOP"),
    ({"telescop": None}, "TELESCOP"),
    ({"instrume": "ZWO ASI2600MC Pro"}, "INSTRUME"),
    ({"filter_raw": "O"}, "FILTER"),
    ({"exptime": 300.0}, "EXPTIME"),
    ({"exptime": None}, "EXPTIME"),
    ({"date_obs": "2025-12-16"}, "DATE-OBS"),
])
def test_stos_naglowek_niezgodny_z_lightami_header_mismatch(con, tmp_path, zmiana, os_naglowka):
    """`TELESCOP` (jak w grupowaniu), `INSTRUME` (`normalize_camera`), `FILTER` (kanon) i ekspozycja
    (próg) wobec lightów wejść; `DATE-OBS` bez czasu nie daje daty nazwy. Oś stoi w `detail`."""
    src, names, ids, t = _stos_z_wydania(con, tmp_path, **zmiana)
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert (it.status, it.reason) == ("review", "header_mismatch") and it.detail.startswith(os_naglowka)


def test_stos_naglowek_zgodny_mimo_nazwy_potocznej_i_formy_karty(con, tmp_path):
    """`OBJECT` potoczny nie jest porównywany; `FILTER='H'` to kanon `Ha`, `EXPTIME` w progu."""
    src, names, ids, t = _stos_z_wydania(con, tmp_path, exptime=600.4)
    t = dataclasses.replace(t, header={**t.header, "OBJECT": "Heart of the Soul Nebula"})
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert it.status == "would-place" and it.name == NAZWA_STOSU.replace("_600s_", "_600.4s_")


@pytest.mark.parametrize("katalogi, n", [
    ([rf"{DB_ROOT}\LIGHTS\_COMETS\21P\76EDPH_2600MM\Ha"], 1),
    ([LIGHTS_HA, rf"{DB_ROOT}\LIGHTS\IC1795\76EDPH_2600MM\Ha_stare"], 2),
    ([r"C:\WBPP\import\IC1795"], 0),
    ([rf"{DB_ROOT}\LIGHTS\IC1795\76EDPH_2600MM"], 1),
])
def test_stos_bez_siedziby_kategoria_dwa_ogony_brak_kopii(con, tmp_path, katalogi, n):
    """Ogon `<obiekt>\\<zestaw>\\<filtr>` jeden dla wszystkich kopii pod `LIGHTS` - kategoria
    (`_COMETS`), dwa ogony, brak kopii pod `LIGHTS` i inna głębokość to `no_light_seat` (świadomy koszt)."""
    names = [f"20251216_17270{i}_IC1795_LIGHT_Ha_600s_x{i}.fits" for i in range(len(katalogi))]
    ids = [_light(con, nm, directory=k) for nm, k in zip(names, katalogi)]
    src = _out(tmp_path, STOS_WBPP)
    it = _one(_plan(con, tmp_path, {src: _stos(src, [_wejscie(nm) for nm in names])},
                    manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert (it.status, it.reason, it.reason_n) == ("review", "no_light_seat", n)
    if katalogi[0].count("_COMETS"):
        assert it.detail == r"_COMETS\21P\76EDPH_2600MM\Ha"


def test_stos_pierwsza_kopia_poza_archiwum_druga_pod_lights(con, tmp_path):
    """Siedzibę daje KAŻDA obecna kopia lightu, nie pierwsza: kopia spoza archiwum nie głosuje."""
    names = ["20251216_172700_IC1795_LIGHT_Ha_600s_a.fits"]
    fid = _light(con, names[0], directory=r"C:\WBPP\import")
    _kopia(con, fid, os.path.join(LIGHTS_HA, names[0]))
    src = _out(tmp_path, STOS_WBPP)
    it = _one(_plan(con, tmp_path, {src: _stos(src, [_wejscie(names[0])])},
                    manifest=_wydanie(tmp_path, {ZESTAW: (names, [fid])})))
    assert it.status == "would-place" and os.path.dirname(it.dst) == _seat(tmp_path)


def test_stos_bez_wydania_no_release_z_biblioteka_stacks(con, tmp_path):
    """Stos spoza wydania Horreum: przegląd, a `detail` niesie bibliotekę `STACKS`, do której człowiek
    kopiuje go ręką (Dostawa go weźmie)."""
    src, names, ids, t = _stos_z_wydania(con, tmp_path)
    for manifest in (None, {"layout": "wbpp-feed", "zestawy": {}}):
        it = _one(_plan(con, tmp_path, {src: t}, manifest=manifest))
        assert (it.status, it.reason, it.detail) == ("review", "no_release", str(tmp_path / "arch" / "STACKS"))


def test_stos_bez_historii_i_bez_wejsc(con, tmp_path):
    names, ids = _lighty(con, 1)
    a = _out(tmp_path, "masterLight_A_mono.xisf", data=b"A")
    b = _out(tmp_path, "masterLight_B_mono.xisf", data=b"B")
    p = _plan(con, tmp_path, {a: dataclasses.replace(_stos(a, []), rows=None), b: _stos(b, [], rows=4)},
              manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)}))
    assert [(it.status, it.reason) for it in p.items] == [("review", "no_history"), ("review", "no_inputs")]


def test_stos_wejscia_z_dwoch_zestawow_outside_release(con, tmp_path):
    """Stos z lightów dwóch zestawów jednego wydania (WBPP bez `TELESCOP` w grupowaniu) nie jest
    stosem JEDNEGO zestawu: wejścia spoza zestawu większości liczone i cytowane."""
    names, ids = _lighty(con, 3)
    src = _out(tmp_path, STOS_WBPP)
    it = _one(_plan(con, tmp_path, {src: _stos(src, [_wejscie(nm) for nm in names])},
                    manifest=_wydanie(tmp_path, {ZESTAW: (names[:2], ids[:2]),
                                                 "RC8_ASI2600MM": (names[2:], ids[2:])})))
    assert (it.status, it.reason, it.reason_n, it.detail) == \
        ("review", "outside_release", 1, os.path.basename(_wejscie(names[2])))


def test_stos_light_z_manifestu_nieznany_bazie_inputs_unknown(con, tmp_path):
    src = _out(tmp_path, STOS_WBPP)
    it = _one(_plan(con, tmp_path, {src: _stos(src, [_wejscie("obcy.fits")])},
                    manifest=_wydanie(tmp_path, {ZESTAW: (["obcy.fits"], [9999])})))
    assert (it.status, it.reason, it.reason_n, it.detail) == ("review", "inputs_unknown", 1, "9999")


def test_stos_kolor_nieczytelny_color_unknown(con, tmp_path):
    nazwa = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-H.xisf"
    src, names, ids, t = _stos_z_wydania(con, tmp_path, name=nazwa)
    it = _one(_plan(con, tmp_path, {src: t}, manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)})))
    assert (it.status, it.reason, it.detail) == ("review", "color_unknown", nazwa)


def test_stos_nazwa_zajeta_dysk_baza_plan_sufiks_wbpp_i_name_taken(con, tmp_path):
    """Nazwa zajęta na dysku (inne bajty), w bazie (lokacja bez pliku) albo przez wcześniejszą pozycję
    planu → sufiks `WBPP_<YYYYMMDD mtime źródła>`, dalej `_2`..`_9`; dziesięć zajętych → `name_taken`.
    Druga integracja tego samego materiału z tokenem `OBIEKT-<x>` w nazwie WBPP dostaje sufiks, nie token."""
    names, ids = _lighty(con, 2)
    manifest = _wydanie(tmp_path, {ZESTAW: (names, ids)})
    a = _out(tmp_path, STOS_WBPP, data=b"STOS-A")
    b = _out(tmp_path, STOS_WBPP.replace("_mono", "_mono_OBIEKT-IC1795"), data=b"STOS-B")
    chwila = datetime(2026, 1, 24, 12, 0).timestamp()
    for s in (a, b):
        os.utime(s, (chwila, chwila))
    dzien = datetime.fromtimestamp(chwila).strftime("%Y%m%d")
    seat = _seat(tmp_path)
    os.makedirs(seat)
    open(os.path.join(seat, NAZWA_STOSU), "wb").write(b"INNY-STOS")
    lokacja = repo.upsert_frame(con, sha1_data="inny", kind="master_light", filetype="xisf", camera_id=1,
                                now=NOW)[0]
    _kopia(con, lokacja, os.path.join(seat, NAZWA_STOSU.replace(".xisf", f"_WBPP_{dzien}.xisf")).upper(), 0)
    wejscia = [_wejscie(nm) for nm in names]
    p = _plan(con, tmp_path, {a: _stos(a, wejscia, sha="a"), b: _stos(b, wejscia, sha="b")}, manifest=manifest)
    assert [(it.status, it.name) for it in p.items] == [
        ("would-place", NAZWA_STOSU.replace(".xisf", f"_WBPP_{dzien}_2.xisf")),
        ("would-place", NAZWA_STOSU.replace(".xisf", f"_WBPP_{dzien}_3.xisf"))]
    for k in range(2, 10):                                # `_3` jako porzucony `.part`
        nazwa = NAZWA_STOSU.replace(".xisf", f"_WBPP_{dzien}_{k}.xisf") + (".part" if k == 3 else "")
        open(os.path.join(seat, nazwa), "wb").write(b"x")
    p = _plan(con, tmp_path, {a: _stos(a, wejscia, sha="a"), b: _stos(b, wejscia, sha="b")}, manifest=manifest)
    assert [(it.status, it.reason, it.reason_n) for it in p.items] == [("review", "name_taken", 10)] * 2


def test_stos_prawdziwy_xisf_read_master_plan_apply(con, tmp_path):
    """Domyślne czytniki na PRAWDZIWYM stosie XISF (karty jako tekst, `EXPTIME='600.000'`, historia
    z nazwami wejść), plan i kopia przez prawdziwą klingę do `STACKS`."""
    names, ids = _lighty(con, 3)
    src = tmp_path / "wbpp" / "master" / STOS_WBPP
    src.parent.mkdir(parents=True)
    _write_xisf_master(src, [("IMAGETYP", "'Master Light'"), ("FILTER", "'H'"), ("EXPTIME", "600.000"),
                             ("TELESCOP", "'76EDPH'"), ("INSTRUME", "'ZWO ASI2600MM Pro'"),
                             ("DATE-OBS", "'2025-12-16T17:27:54'"), ("XBINNING", "1")],
                       _xml_historii_flat([_wejscie(nm) for nm in names[:2]]))
    t = harvest.read_master(str(src))
    assert (t.kind, t.exptime, t.rows) == ("master_light", 600.0, 2)
    p = harvest.plan(con, str(tmp_path / "wbpp"), archive_root=str(tmp_path / "arch" / "CALIBRATION"),
                     manifest=_wydanie(tmp_path, {ZESTAW: (names, ids)}))
    it = _one(p)
    assert it.status == "would-place" and it.frame_ids == tuple(sorted(ids[:2]))
    r = harvest.apply(p, now=NOW)
    assert [x.status for x in r.items] == ["placed"] and r.placed_dirs == [_seat(tmp_path)]
    assert open(it.dst, "rb").read() == src.read_bytes()


# ============================================================ kalibracja cudzym masterem


def _kalibrowana(path, *, filtr, exp, flat, dark, flat_on="true"):
    """Klatka skalibrowana przez WBPP (`…_c.xisf`): karty grupy i historia `ImageCalibration`
    z pełnymi ścieżkami masterów (`/`, jak zapisuje WBPP), treść zaescape'owana jak w realnym pliku."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    hist = ('<Property id="PixInsight:ProcessingHistory" type="String">'
            '&lt;instance class="ImageCalibration"&gt;'
            '&lt;parameter id="masterBiasEnabled" value="false"/&gt;'
            '&lt;parameter id="masterBiasPath"&gt;&lt;/parameter&gt;'
            '&lt;parameter id="masterDarkEnabled" value="true"/&gt;'
            f'&lt;parameter id="masterDarkPath"&gt;{dark}&lt;/parameter&gt;'
            f'&lt;parameter id="masterFlatEnabled" value="{flat_on}"/&gt;'
            f'&lt;parameter id="masterFlatPath"&gt;{flat}&lt;/parameter&gt;'
            '&lt;/instance&gt;</Property>')
    return _write_xisf_master(path, [("IMAGETYP", "'LIGHT'"), ("FILTER", f"'{filtr}'"), ("EXPTIME", exp)], hist)


def _sesja_dwoch_wydan(tmp_path):
    """Dwa wydania (IC1795 na A140R, Cr464 na 76EDPH) wrzucone do JEDNEJ sesji WBPP z wyjściem
    w wydaniu IC1795: grupa IC1795 skalibrowana flatem z wydania Cr464, grupa Cr464 darkiem IC1795."""
    obj = tmp_path / "_WBPP" / "OBJECTS"
    ic_seg, cr_seg = "A140R_ASI2600MM", ZESTAW
    ic = {"layout": projection.OBJECT_LAYOUT, "object_canon": "IC1795", "root": str(obj / "IC1795"),
          "zestawy": {ic_seg: {"lights": [1, 2], "names": {"IC1795_H_0000.fits": 1, "IC1795_H_0001.fits": 2}}}}
    cr = {"layout": projection.OBJECT_LAYOUT, "object_canon": "Cr464", "root": str(obj / "Cr464"),
          "zestawy": {cr_seg: {"lights": [7], "names": {"Cr464_B_0000.fits": 7}}}}
    out = obj / "IC1795" / "out"
    flat_cr = (obj / "Cr464" / cr_seg / "MASTER" / "flat" / "masterFlat_B.xisf").as_posix()
    dark_ic = (obj / "IC1795" / ic_seg / "MASTER" / "dark" / "masterDark_600s.xisf").as_posix()
    dark_ic15 = (obj / "IC1795" / ic_seg / "MASTER" / "dark" / "masterDark_15s.xisf").as_posix()
    _kalibrowana(out / "calibrated" / "Light_FILTER-H_mono" / "IC1795_H_0000_c.xisf", filtr="H", exp="600.0",
                 flat=flat_cr, dark=dark_ic)
    _kalibrowana(out / "calibrated" / "Light_FILTER-H_mono" / "IC1795_H_0001_c.xisf", filtr="H", exp="600.0",
                 flat=(out / "master" / "masterFlat_H.xisf").as_posix(), dark=dark_ic)
    _kalibrowana(out / "calibrated" / "Light_FILTER-B_mono" / "Cr464_B_0000_c.xisf", filtr="B", exp="15.0",
                 flat=(out / "master" / "masterFlat_B.xisf").as_posix(), dark=dark_ic15)
    return out, ic, cr, flat_cr, dark_ic15


def test_kalibracja_cudzym_masterem_dwa_wydania_jednej_sesji_wbpp(con, tmp_path):
    """Przypadek z odbioru wydania obiektu: IC1795 skalibrowany flatem z drzewa wydania Cr464, Cr464
    darkiem IC1795. Audyt czyta PIERWSZĄ klatkę `…_c.xisf` grupy i sprawdza ścieżki LEKSYKALNIE; stos
    tej grupy zostaje w przeglądzie z cudzą ścieżką w `detail`."""
    out, ic, cr, flat_cr, dark_ic15 = _sesja_dwoch_wydan(tmp_path)
    assert harvest.audit_calibration(str(out), ic) == {
        ("A140R_ASI2600MM", "Ha", 600.0): harvest.Finding("flat", flat_cr)}
    assert harvest.audit_calibration(str(out), cr) == {(ZESTAW, "B", 15.0): harvest.Finding("dark", dark_ic15)}

    names = ["IC1795_H_0000.fits", "IC1795_H_0001.fits"]
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES ('A140R', 'proposed', ?)",
                (NOW,))
    con.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) VALUES (3, 1, 'proposed', ?)",
                (NOW,))
    con.commit()
    ids = [_light(con, nm, directory=rf"{DB_ROOT}\LIGHTS\IC1795\A140R_2600MM\Ha", config_id=4) for nm in names]
    ic["zestawy"]["A140R_ASI2600MM"].update(lights=ids, names=dict(zip(names, ids)))
    src = out / "master" / STOS_WBPP
    src.parent.mkdir(parents=True)
    src.write_bytes(b"STOS-IC1795")
    p = harvest.plan(con, str(out), archive_root=str(tmp_path / "arch"), manifest=ic,
                     read=_reader({str(src): _stos(str(src), [_wejscie(nm) for nm in names], telescop="A140R")}))
    it = _one(p)
    assert (it.status, it.reason, it.detail) == ("review", "foreign_calibration", f"flat={flat_cr}")


def test_audyt_kalibracji_bez_werdyktu_nie_jest_odmowa(tmp_path):
    """Bez `out\\calibrated`, bez manifestu wydania, manifest bez `names` (bez bazy nazwy nie świadczą),
    flat z `out\\master` i master wyłączony - brak `Finding`, nie odmowa."""
    out, ic, cr, _flat, _dark = _sesja_dwoch_wydan(tmp_path)
    assert harvest.audit_calibration(str(tmp_path / "brak"), ic) == {}
    assert harvest.audit_calibration(str(out), None) == {}
    bez_names = json.loads(json.dumps(ic))
    del bez_names["zestawy"]["A140R_ASI2600MM"]["names"]
    assert harvest.audit_calibration(str(out), bez_names) == {}
    wlasne = tmp_path / "wlasne" / "out"
    dark = (tmp_path / "_WBPP" / "OBJECTS" / "IC1795" / "A140R_ASI2600MM" / "MASTER" / "d.xisf").as_posix()
    _kalibrowana(wlasne / "calibrated" / "g" / "IC1795_H_0000_c.xisf", filtr="H", exp="600.0",
                 flat=(wlasne / "master" / "masterFlat_H.xisf").as_posix(), dark=dark)
    _kalibrowana(wlasne / "calibrated" / "h" / "IC1795_H_0001_c.xisf", filtr="H", exp="300.0",
                 flat=(tmp_path / "obcy" / "masterFlat.xisf").as_posix(), flat_on="false", dark=dark)
    assert harvest.audit_calibration(str(wlasne), ic) == {}


def test_siedziba_na_zerwanym_udziale_to_przeglad_nie_do_wciagniecia(con, tmp_path, monkeypatch):
    """Odczyt folderu siedziby pada zerwanym udziałem (WinError 53 - CPython daje `FileNotFoundError`,
    a folder istnieje) albo odmową dostępu (5) → pozycja `review` z powodem `"seat_unreadable"`
    i błędem systemu klasą w `detail`, nie „do wciągnięcia” na udział, którego nie widać. Folderu
    naprawdę nie ma - dalej „do wciągnięcia”. Falsyfikator: `except FileNotFoundError: return None`."""
    pid = _profile(con)
    names, _ = _flaty(con, pid, n=2)
    s = _out(tmp_path, "masterFlat_0.xisf", data=b"MASTER-0")
    t = {s: _testimony(s, inputs=[_wbpp_input(nm) for nm in names])}
    it = _one(_plan(con, tmp_path, t))
    assert it.status == "would-place"                            # siedziby nie ma - do wciągnięcia
    seat = os.path.dirname(it.dst)
    oryg = os.listdir
    for kod, klasa in ((53, "os_share_lost"), (5, "os_denied")):
        def listdir(k, kod=kod):
            if os.path.normcase(str(k)) == os.path.normcase(seat):
                raise OSError(None, "Komunikat systemu", str(k), kod)
            return oryg(k)
        monkeypatch.setattr(harvest.os, "listdir", listdir)
        it = _one(_plan(con, tmp_path, t))
        assert (it.status, it.reason, it.dst) == ("review", "seat_unreadable", None), it
        assert it.detail.code == klasa and dict(it.detail.params)["os_code"] == f"WinError {kod}"
    monkeypatch.undo()
    # stos z wydania: ta sama reguła siedziby pod `STACKS` (`_stack_on_disk`)
    nazwy, ids = _lighty(con, 2)
    src = _out(tmp_path, STOS_WBPP, data=b"STOS-HA")
    stos = {src: _stos(src, [_wejscie(nm) for nm in nazwy])}
    wydanie = _wydanie(tmp_path, {ZESTAW: (nazwy, ids)})
    stos_it = next(i for i in _plan(con, tmp_path, {**t, **stos}, manifest=wydanie).items if i.src == src)
    assert stos_it.status == "would-place"

    def listdir_stosu(k):
        if os.path.normcase(str(k)) == os.path.normcase(_seat(tmp_path)):
            raise OSError(None, "Komunikat systemu", str(k), 67)
        return oryg(k)
    monkeypatch.setattr(harvest.os, "listdir", listdir_stosu)
    stos_it = next(i for i in _plan(con, tmp_path, {**t, **stos}, manifest=wydanie).items if i.src == src)
    assert (stos_it.status, stos_it.reason) == ("review", "seat_unreadable"), stos_it
    assert stos_it.detail.code == "os_share_lost"


def test_kazdy_powod_ma_test():
    """Lista powodów jest zamknięta; nowy token bez testu w tym pliku przewraca ten test."""
    zrodlo = open(__file__, encoding="utf-8").read()
    assert all(f'"{r}"' in zrodlo.split("def test_kazdy_powod_ma_test")[0] for r in harvest.REASONS)


# ============================================================ apply


def _would_place(con, tmp_path, n=2):
    pid = _profile(con)
    names, _ = _flaty(con, pid, n=n * 2)
    t = {}
    for i in range(n):
        s = _out(tmp_path, f"masterFlat_{i}.xisf", data=f"MASTER-{i}".encode())
        t[s] = _testimony(s, inputs=[_wbpp_input(nm) for nm in names[2 * i:2 * i + 2]])
    p = _plan(con, tmp_path, t)
    assert [it.status for it in p.items] == ["would-place"] * n
    return p


def test_apply_kopiuje_prawdziwa_klinga_i_pisze_manifest(con, tmp_path):
    p = _would_place(con, tmp_path)
    postep = []
    r = harvest.apply(p, now=NOW, progress=lambda *a: postep.append(a))
    assert [it.status for it in r.items] == ["placed", "placed"] and not r.cancelled
    seat = os.path.dirname(p.items[0].dst)
    assert r.placed_dirs == [seat] and os.path.join("CALIBRATION", "masters", "flats") in seat
    for it in r.items:
        assert open(it.dst, "rb").read() == open(it.src, "rb").read()
        assert not os.path.exists(it.dst + ".part")
    assert [a[:2] for a in postep] == [(1, 2), (2, 2)] and postep[-1][3] == "placed"
    assert r.manifest_error is None and os.path.dirname(r.manifest_path) == p.wbpp_dir
    zeznanie = json.load(open(r.manifest_path, encoding="utf-8"))
    assert zeznanie["counts"] == {"placed": 2} and zeznanie["ts"] == NOW
    assert [i["status"] for i in zeznanie["items"]] == ["placed", "placed"]
    assert zeznanie["items"][0]["frame_ids"] == list(p.items[0].frame_ids)


def test_apply_anulowanie_po_pierwszej_pozycji(con, tmp_path):
    p = _would_place(con, tmp_path)
    pytania = []

    def anuluj():
        pytania.append(1)
        return len(pytania) > 1
    r = harvest.apply(p, now=NOW, should_cancel=anuluj)
    assert [it.status for it in r.items] == ["placed", "cancelled"] and r.cancelled
    assert not os.path.exists(p.items[1].dst) and not os.path.exists(p.items[1].dst + ".part")
    zeznanie = json.load(open(r.manifest_path, encoding="utf-8"))
    assert zeznanie["cancelled"] is True and zeznanie["counts"] == {"cancelled": 1, "placed": 1}


def test_apply_przekazuje_expected_sha1_i_niesie_powod_klingi(con, tmp_path):
    p = _would_place(con, tmp_path)
    wolania = []

    def kopia(src, dst, *, expected_sha1, library_root):
        wolania.append((src, dst, expected_sha1, library_root))
        return ("verify_bad", "sha1 inny") if len(wolania) == 1 else ("conflict", "cel istnieje")
    r = harvest.apply(p, now=NOW, copy=kopia)
    assert wolania == [(it.src, it.dst, it.file_sha1, str(tmp_path / "arch")) for it in p.items]
    assert p.archive_root == str(tmp_path / "arch")
    assert [(it.status, it.reason, it.detail) for it in r.items] == \
        [("verify_bad", None, "sha1 inny"), ("conflict", None, "cel istnieje")]
    assert r.placed_dirs == [] and [it.status for it in p.items] == ["would-place"] * 2   # plan nietknięty


def test_apply_bez_placed_tez_pisze_zeznanie_i_przepuszcza_review(con, tmp_path):
    src = _out(tmp_path, "masterDark_X.xisf")
    p = _plan(con, tmp_path, {src: _testimony(src, kind="master_dark", imagetyp="Master Dark")})
    r = harvest.apply(p, now=NOW, copy=lambda *a, **k: pytest.fail("kopia bez pozycji would-place"))
    assert r.items == p.items and r.placed_dirs == []
    zeznanie = json.load(open(r.manifest_path, encoding="utf-8"))
    assert zeznanie["items"][0]["reason"] == "no_raw_darks"


def test_apply_plan_bez_wbpp_dir_valueerror():
    with pytest.raises(ValueError, match="wbpp_dir"):
        harvest.apply(harvest.HarvestPlan(items=[], manifest_root=None), now=NOW)


def test_apply_wyjatek_klingi_to_error_pozycji_a_petla_idzie_dalej(con, tmp_path):
    """Wyjątek `copy` spoza katalogu statusów (np. `ValueError` guardu) nie zabiera wyniku kopii już
    zrobionych: pozycja `error` z treścią, następne kopiowane, zeznanie zapisane."""
    p = _would_place(con, tmp_path)

    def kopia(src, dst, *, expected_sha1, library_root):
        if src == p.items[0].src:
            raise ValueError("cel poza CALIBRATION")
        return projection.copy_master(src, dst, expected_sha1=expected_sha1, library_root=library_root)
    r = harvest.apply(p, now=NOW, copy=kopia)
    assert [(it.status, it.detail) for it in r.items] == [("error", "ValueError: cel poza CALIBRATION"),
                                                          ("placed", None)]
    assert r.manifest_error is None and os.path.exists(r.manifest_path)


def test_apply_blad_zapisu_zeznania_wraca_w_wyniku(con, tmp_path, monkeypatch):
    p = _would_place(con, tmp_path)

    def pelny_dysk(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(projection, "write_harvest_manifest", pelny_dysk)
    r = harvest.apply(p, now=NOW)
    assert [it.status for it in r.items] == ["placed", "placed"] and len(r.placed_dirs) == 1
    assert r.manifest_path is None and r.manifest_error.code == "os_no_space"   # klasą (AR-184)
    assert dict(r.manifest_error.params)["detail"] == "OSError: [Errno 28] No space left on device"


def test_apply_przerwanie_zapisuje_zeznanie_wyniku_czesciowego(con, tmp_path):
    p = _would_place(con, tmp_path)

    def kopia(src, dst, *, expected_sha1, library_root):
        if src == p.items[1].src:
            raise KeyboardInterrupt
        return projection.copy_master(src, dst, expected_sha1=expected_sha1, library_root=library_root)
    with pytest.raises(KeyboardInterrupt):
        harvest.apply(p, now=NOW, copy=kopia)
    [plik] = [f for f in os.listdir(p.wbpp_dir) if f.startswith(projection.HARVEST_MANIFEST_PREFIX)]
    zeznanie = json.load(open(os.path.join(p.wbpp_dir, plik), encoding="utf-8"))
    assert [i["status"] for i in zeznanie["items"]] == ["placed", "would-place"]


def test_apply_kazdy_bieg_wlasnym_zeznaniem(con, tmp_path):
    """Drugi bieg nad tym samym wyjściem nie nadpisuje zeznania pierwszego (ta sama sekunda → `_2`)."""
    p = _would_place(con, tmp_path, n=1)
    r1 = harvest.apply(p, now=NOW)
    r2 = harvest.apply(p, now=NOW, copy=lambda *a, **k: ("conflict", "x"))
    assert os.path.basename(r1.manifest_path) == "_ZNIWA_20261010-120000.json"
    assert os.path.basename(r2.manifest_path) == "_ZNIWA_20261010-120000_2.json"
    assert json.load(open(r1.manifest_path, encoding="utf-8"))["counts"] == {"placed": 1}
    assert json.load(open(r2.manifest_path, encoding="utf-8"))["counts"] == {"conflict": 1}


def test_statusy_jeden_wlasciciel_i_klinga_w_katalogu():
    """`STATUSES` to komplet: statusy planu, `cancelled` z `apply` i KAŻDY status, który zwraca klinga
    `copy_master` (literał pierwszego członu krotki `return`) - nowy status klingi bez wpisu tutaj
    przewraca test parytetu po stronie dialogu, więc łapiemy go już w rdzeniu."""
    import ast
    import inspect
    assert harvest.STATUSES == ("would-place", "exists", "review", "placed", "verify_bad", "conflict",
                                "error", "cancelled")
    drzewo = ast.parse(inspect.getsource(projection.copy_master))
    klinga = {n.value.elts[0].value for n in ast.walk(drzewo)
              if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)}
    assert klinga == {"placed", "conflict", "verify_bad", "error"} and klinga <= set(harvest.STATUSES)


def test_powody_stosow_doszly_na_koncu_listy():
    """Parytet z dialogiem stoi na `REASONS`: powody stosów dochodzą na końcu, stare tokeny bez zmian
    pozycji (literalna mapa dialogu i katalog i18n idą za nimi)."""
    assert harvest.REASONS[:13] == ("no_raw_darks", "unreadable", "no_history", "no_inputs", "inputs_unknown",
                                    "inputs_ambiguous", "mixed_profile", "no_profile", "no_night",
                                    "header_mismatch", "outside_release", "no_config", "name_taken")
    assert harvest.REASONS[13:] == ("no_release", "no_light_seat", "color_unknown", "foreign_calibration",
                                    "seat_unreadable")              # siedziba nieczytelna (AR-183)
    assert len(set(harvest.REASONS)) == len(harvest.REASONS)


# ============================================================ lista wydań (`releases`)

TS = "2026-10-10T12:00:00+00:00"
PRZED, PO = datetime.fromisoformat(TS).timestamp() - 3600, datetime.fromisoformat(TS).timestamp() + 3600


def _wydanie_na_dysku(tmp_path, obiekt="IC1795", *, ts="2026-10-09T10:00:00+00:00", karta="_WBPP",
                      layout=projection.OBJECT_LAYOUT):
    root = tmp_path / karta / projection.OBJECT_NAMESPACE / obiekt
    root.mkdir(parents=True)
    (root / projection.MANIFEST_NAME).write_text(json.dumps(
        {"layout": layout, "object_canon": obiekt, "ts": ts, "zestawy": {}}), encoding="utf-8")
    return root


def _wynik_wbpp(root, name, *, mtime=PRZED, sub="master"):
    p = root / projection.OUTPUT_DIR / sub / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(name.encode())
    os.utime(p, (mtime, mtime))
    return str(p)


def _zeznanie_zniw(katalog, statusy, *, ts=TS):
    """Zeznanie biegu żniw przez klingę `write_harvest_manifest`: `statusy` = `{src: status}`."""
    payload = {"ts": ts, "items": [{"src": s, "status": st} for s, st in statusy.items()]}
    return projection.write_harvest_manifest(str(katalog), payload, now=ts)


def test_missing_roots_tylko_karty_bez_folderu_raz_na_pisownie(tmp_path):
    """AR-147: karta bez folderu na dysku jest brakiem, karta istniejąca bez `OBJECTS` - nie (to karta
    bez wydań); ta sama karta pod dwiema pisowniami liczy się raz, kolejność jak w `roots`."""
    pusta = tmp_path / "_WBPP"
    pusta.mkdir()
    brak = tmp_path / "F" / "_WBPP"
    drugi = tmp_path / "G"
    assert harvest.missing_roots([str(pusta), str(brak), str(brak).upper(), str(drugi)]) == (str(brak), str(drugi))
    assert harvest.missing_roots([str(pusta)]) == ()


def test_releases_bez_wyjscia_czeka_na_wbpp(tmp_path):
    root = _wydanie_na_dysku(tmp_path)
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert row == harvest.ReleaseRow(root=str(tmp_path / "_WBPP"), object_root=str(root), object_canon="IC1795",
                                     ts="2026-10-09T10:00:00+00:00", out_dir=str(root / "out"),
                                     pending=0, done=0, review=0)


def test_releases_wciagniete_wedlug_tresci_zeznania(tmp_path):
    root = _wydanie_na_dysku(tmp_path)
    a = _wynik_wbpp(root, "masterLight_A_mono.xisf")
    b = _wynik_wbpp(root, "masterFlat_B.xisf")
    _wynik_wbpp(root, "HOS.xisf")                                     # produkt obróbki - nie kandydat
    _zeznanie_zniw(root / "out", {a: "placed", b: "exists"})
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review) == (0, 2, 0)


def test_releases_zeznanie_przerwane_czesciowe_review_konflikt_nie_sa_wciagniete(tmp_path):
    """Bieg przerwany (`cancelled`, nieruszone `would-place`), konflikt i błąd klingi - do wciągnięcia;
    `review` to osobny stan; wciągnięte wyłącznie `placed`/`exists`."""
    root = _wydanie_na_dysku(tmp_path)
    pliki = {s: _wynik_wbpp(root, f"masterLight_{s}_mono.xisf")
             for s in ("placed", "cancelled", "would-place", "review", "conflict", "error")}
    _zeznanie_zniw(root / "out", {p: s for s, p in pliki.items()})
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review) == (4, 1, 1)


def test_releases_nowy_przebieg_wbpp_po_zniwach_do_wciagniecia(tmp_path):
    """Plik nowszy od zeznania (WBPP nadpisał wynik pod tą samą nazwą) nie jest wciągnięty ani
    przejrzany - zeznanie mówi o poprzednich bajtach."""
    root = _wydanie_na_dysku(tmp_path)
    a = _wynik_wbpp(root, "masterLight_A_mono.xisf", mtime=PO)
    b = _wynik_wbpp(root, "masterLight_B_mono.xisf", mtime=PO)
    _zeznanie_zniw(root / "out", {a: "placed", b: "review"})
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review) == (2, 0, 0)


def test_releases_najnowsze_zeznanie_wymieniajace_plik_rozstrzyga(tmp_path):
    """Zeznania do dwóch poziomów pod `out` (bieg wskazany na `out\\master`); o pliku mówi najnowsze
    zeznanie, które go wymienia - bieg nad podkatalogiem nie kasuje wiedzy o reszcie."""
    root = _wydanie_na_dysku(tmp_path)
    a = _wynik_wbpp(root, "masterLight_A_mono.xisf")
    b = _wynik_wbpp(root, "masterFlat_B.xisf", sub="inne")
    _zeznanie_zniw(root / "out", {a: "placed", b: "placed"}, ts="2026-10-10T11:00:00+00:00")
    _zeznanie_zniw(root / "out" / "master", {a.upper(): "review"})
    zly = root / "out" / "master" / "_ZNIWA_20261010-130000.json"
    zly.write_text("{nie json", encoding="utf-8")
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review) == (0, 1, 1)


def test_releases_kolejnosc_ts_jedna_karta_dwiema_pisowniami_i_obce_katalogi(tmp_path):
    """Od najnowszego wydania; ta sama karta pod dwiema pisowniami liczy wydanie raz; karta bez
    `OBJECTS`, folder bez manifestu i manifest innego układu - nic."""
    stare = _wydanie_na_dysku(tmp_path, "M42", ts="2026-10-01T10:00:00+00:00")
    nowe = _wydanie_na_dysku(tmp_path, "IC1795", ts="2026-10-09T10:00:00+00:00")
    (tmp_path / "_WBPP" / "OBJECTS" / "pusty").mkdir()
    _wydanie_na_dysku(tmp_path, "kolumny", layout="po-obiektach")
    (tmp_path / "karta_bez_objects").mkdir()
    karta = str(tmp_path / "_WBPP")
    rows = harvest.releases([karta, karta.upper() + os.sep, str(tmp_path / "karta_bez_objects"),
                             str(tmp_path / "brak")])
    assert [r.object_root for r in rows] == [str(nowe), str(stare)]
    assert harvest.releases([]) == []


def test_releases_plik_zmieniony_miedzy_planem_a_apply_nie_jest_wciagniety(con, tmp_path):
    """`apply` przenosi `exists` z planu bez audytu: plik nadpisany przez WBPP po planie, a przed
    `apply`, ma czas starszy od zeznania. Wciągnięty jest tylko plik z TYM SAMYM `st_mtime_ns`, który
    plan zapisał przy pozycji (`src_mtime_ns` w zeznaniu); niezmieniony - wciągnięty."""
    root = _wydanie_na_dysku(tmp_path)
    names, ids = _lighty(con, 2)
    a = _wynik_wbpp(root, STOS_WBPP)
    b = _wynik_wbpp(root, STOS_WBPP.replace("_mono", "_mono_autocrop"))
    wejscia = [_wejscie(nm) for nm in names]
    czytnik = _reader({a: _stos(a, wejscia, sha="a"), b: _stos(b, wejscia, sha="b")})
    manifest = _wydanie(tmp_path, {ZESTAW: (names, ids)})
    plan = lambda: harvest.plan(con, str(root / "out"), archive_root=str(tmp_path / "arch"),   # noqa: E731
                                manifest=manifest, read=czytnik)
    assert [it.status for it in harvest.apply(plan(), now=TS).items] == ["placed", "placed"]
    drugi = plan()
    assert [(it.status, it.src_mtime_ns) for it in drugi.items] == \
        [("exists", os.stat(a).st_mtime_ns), ("exists", os.stat(b).st_mtime_ns)]
    with open(b, "r+b") as fh:                                       # WBPP nadpisuje wynik po planie
        fh.write(b"X")
    os.utime(b, (PRZED + 10, PRZED + 10))
    r = harvest.apply(drugi, now="2026-10-10T13:00:00+00:00")
    zeznanie = json.load(open(r.manifest_path, encoding="utf-8"))
    assert [i["src_mtime_ns"] for i in zeznanie["items"]] == [it.src_mtime_ns for it in drugi.items]
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review) == (1, 1, 0)


def test_releases_zeznanie_z_czasem_planu_rozstrzyga_rownoscia_bez_pola_regula_ts(tmp_path):
    """Pozycja z `src_mtime_ns`: wciągnięta wyłącznie przy równym czasie pliku (także, gdy plik jest
    młodszy od `ts` zeznania); pozycja bez pola (zeznanie sprzed niego) - plik nie młodszy niż `ts`."""
    root = _wydanie_na_dysku(tmp_path)
    rowny = _wynik_wbpp(root, "masterLight_A_mono.xisf", mtime=PO)
    inny = _wynik_wbpp(root, "masterLight_B_mono.xisf", mtime=PRZED)
    stary_ok = _wynik_wbpp(root, "masterLight_C_mono.xisf", mtime=PRZED)
    stary_mlody = _wynik_wbpp(root, "masterLight_D_mono.xisf", mtime=PO)
    payload = {"ts": TS, "items": [
        {"src": rowny, "status": "exists", "src_mtime_ns": os.stat(rowny).st_mtime_ns},
        {"src": inny, "status": "placed", "src_mtime_ns": os.stat(inny).st_mtime_ns - 1},
        {"src": stary_ok, "status": "placed"}, {"src": stary_mlody, "status": "placed"}]}
    projection.write_harvest_manifest(str(root / "out"), payload, now=TS)
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review) == (2, 2, 0)


def test_releases_ponowne_wydanie_przed_nowym_wbpp_czeka_na_wbpp(tmp_path):
    """Obiekt wydany ponownie (nowe lighty), a w `out` leżą wyniki poprzedniego przebiegu: liczniki
    dalej je opisują, `awaiting_wbpp` mówi, że to nie są wyniki ostatniego wydania. Nowy wynik WBPP po
    wydaniu gasi pole; puste wyjście go nie zapala (zera same mówią „czeka na WBPP”)."""
    root = _wydanie_na_dysku(tmp_path, ts="2026-10-09T10:00:00+00:00")
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review, row.awaiting_wbpp) == (0, 0, 0, False)
    a = _wynik_wbpp(root, "masterLight_A_mono.xisf", mtime=PRZED)
    _zeznanie_zniw(root / "out", {a: "placed"})
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.done, row.awaiting_wbpp) == (1, False)
    manifest = json.loads((root / projection.MANIFEST_NAME).read_text(encoding="utf-8"))
    (root / projection.MANIFEST_NAME).write_text(json.dumps({**manifest, "ts": "2026-10-10T12:30:00+00:00"}),
                                                 encoding="utf-8")
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.review, row.awaiting_wbpp) == (0, 1, 0, True)
    _wynik_wbpp(root, "masterLight_B_mono.xisf", mtime=PO)
    [row] = harvest.releases([str(tmp_path / "_WBPP")])
    assert (row.pending, row.done, row.awaiting_wbpp) == (1, 1, False)


def test_releases_swiadcza_tylko_zeznania_biegow_do_archiwum_okna(tmp_path):
    """AR-105: zeznanie biegu do INNEGO archiwum nie świadczy o archiwum okna - plik wciągnięty do kopii
    archiwum w scratchu jest w archiwum okna „do sprawdzenia”, nie „wciągnięty”; zeznanie bez pola
    `archive_root` też nie świadczy, gdy archiwum podano. Wskazanie biblioteki (`…\\CALIBRATION`) i inna
    pisownia porównują się korzeniem; bez `archive_root` świadczą wszystkie zeznania."""
    root = _wydanie_na_dysku(tmp_path)
    arch, scratch = tmp_path / "ARCH", tmp_path / "SCRATCH"
    a = _wynik_wbpp(root, "masterFlat_A.xisf")
    b = _wynik_wbpp(root, "masterFlat_B.xisf", sub="inne")
    c = _wynik_wbpp(root, "masterFlat_C.xisf", sub="stare")
    for katalog, src, archiwum in ((root / "out" / "master", a, arch), (root / "out" / "inne", b, scratch)):
        projection.write_harvest_manifest(str(katalog), {"ts": TS, "archive_root": str(archiwum), "items": [
            {"src": src, "status": "placed"}]}, now=TS)
    _zeznanie_zniw(root / "out" / "stare", {c: "placed"})                 # zeznanie sprzed pola `archive_root`
    karta = [str(tmp_path / "_WBPP")]
    stan = lambda **kw: [(r.pending, r.done) for r in harvest.releases(karta, **kw)]   # noqa: E731
    assert stan() == [(0, 3)]
    assert stan(archive_root=str(arch)) == [(2, 1)]
    assert stan(archive_root=str(arch / "CALIBRATION")) == [(2, 1)]
    assert stan(archive_root=str(arch).upper() + os.sep) == [(2, 1)]
    assert stan(archive_root=str(scratch)) == [(2, 1)]


def _stos_po_dostawie(con, sha1, path):
    """Dostawa po zwykłym „Zamknij”: klatka stosu z obecną kopią pod `STACKS` i integracja z okna czasu,
    które rozjechało się z historią pliku (`history_mismatch`, zero wierszy)."""
    cur = con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
                      "first_seen_at) VALUES (?, 'master_light', 'xisf', 1, 1, 'Ha', ?)", (sha1, NOW))
    _kopia(con, cur.lastrowid, path)
    repo.upsert_integration(
        con, master_frame_id=cur.lastrowid, integ_hash=None, tool=None, window_start="2025-12-16T17:00:00",
        window_end="2025-12-16T19:00:00", declared_rows=2, drizzle_inputs=None, disabled_inputs=None,
        degenerate=0, ambiguous=0, telescope_mismatch=0, unresolved_reason="history_mismatch", now=NOW)
    return cur.lastrowid


def test_releases_stos_bez_rodowodu_dokladnego_czeka_az_do_zapisu(con, tmp_path):
    """AR-104 w rdzeniu listy: stos wciągnięty (zeznanie `placed` ze zbiorem wejść), którego baza nie
    zna - `lineage` z kopią z zeznania; po Dostawie (klatka znana, rodowód okna rozjechany z historią) -
    dalej `lineage`, z kopią znaną bazie; bieg nad stosem już w archiwum zeznaje `exists` BEZ zbioru,
    a zbiór bierze się ze starszego zeznania; po `record_harvest_inputs` - pusto, a wiersz dalej
    „wciągnięty”. Bez bazy albo bez archiwum `lineage` nie liczy się wcale; kopia z zeznania, której już
    nie ma, a której baza nie zna, nie czeka (nie ma czego przyjmować)."""
    root = _wydanie_na_dysku(tmp_path)
    names, ids = _lighty(con, 3)
    a = _wynik_wbpp(root, STOS_WBPP)
    czytnik = _reader({a: _stos(a, [_wejscie(nm) for nm in names[:2]], sha="stos-a")})
    manifest = _wydanie(tmp_path, {ZESTAW: (names, ids)})
    arch = str(tmp_path / "arch")
    plan = lambda: harvest.plan(con, str(root / "out"), archive_root=arch,    # noqa: E731
                                manifest=manifest, read=czytnik)
    [placed] = harvest.apply(plan(), now=TS).items
    assert placed.status == "placed" and placed.frame_ids == tuple(ids[:2])
    karta = [str(tmp_path / "_WBPP")]
    assert harvest.releases(karta, archive_root=arch)[0].lineage == ()
    assert harvest.releases(karta, con=con)[0].lineage == ()
    [row] = harvest.releases(karta, archive_root=arch, con=con)
    # czwarty człon = kanon obiektu wydania z pozycji zeznania (AR-103: gospodarz porówna go z obiektem stosu)
    assert placed.release_canon == "IC1795"
    assert (row.done, row.lineage) == (1, (("stos-a", tuple(ids[:2]), placed.dst, "IC1795"),))

    _stos_po_dostawie(con, "stos-a", placed.dst)
    [drugi] = harvest.apply(plan(), now="2026-10-10T13:00:00+00:00").items
    assert (drugi.status, drugi.frame_ids, drugi.release_canon) == ("exists", (), None)
    [row] = harvest.releases(karta, archive_root=arch, con=con)
    # kanon ze starszego zeznania - tego, które niesie zbiór, nie z biegu `exists` bez wydania
    assert (row.done, row.lineage) == (1, (("stos-a", tuple(ids[:2]), placed.dst, "IC1795"),))

    stacks.record_harvest_inputs(con, master_sha1_data="stos-a", input_frame_ids=ids[:2], now=TS)
    [row] = harvest.releases(karta, archive_root=arch, con=con)
    assert (row.pending, row.done, row.lineage) == (0, 1, ())

    con.execute("DELETE FROM integration_input")
    con.execute("DELETE FROM location WHERE path = ?", (placed.dst,))
    con.commit()
    os.remove(placed.dst)                                                # kopii nie ma ani w bazie, ani na dysku
    assert harvest.releases(karta, archive_root=arch, con=con)[0].lineage == ()


@pytest.mark.parametrize("status, czeka", [("placed", True), ("exists", True), ("review", False)])
def test_releases_zbior_z_pozycji_review_nie_swiadczy(con, tmp_path, status, czeka):
    """Bramka `sol` Z1: `_plan_stack` ustawia `frame_ids` PRZED odmową nagłówka i kalibracji, więc
    zeznanie niesie zbiór także przy pozycji `review` - to zbiór stosu, którego żniwa nie przyjęły.
    Gdy ten sam stos trafi do `STACKS` inną drogą, a nowszy bieg zeznaje go `exists` bez zbioru, lista
    NIE bierze zbioru z `review`; ze starszego `placed`/`exists` - bierze."""
    root = _wydanie_na_dysku(tmp_path)
    _names, ids = _lighty(con, 2)
    a = _wynik_wbpp(root, STOS_WBPP)
    arch = tmp_path / "arch"
    kopia = arch / "STACKS" / "IC1795" / "76EDPH_2600MM" / "Ha" / NAZWA_STOSU
    kopia.parent.mkdir(parents=True)
    kopia.write_bytes(b"STOS")
    _stos_po_dostawie(con, "stos-a", str(kopia))
    pozycja = {"src": a, "kind": "master_light", "sha1_data": "stos-a", "src_mtime_ns": os.stat(a).st_mtime_ns}
    for ts, poz in (("2026-10-10T11:00:00+00:00", {**pozycja, "status": status, "frame_ids": ids}),
                    ("2026-10-10T12:00:00+00:00", {**pozycja, "status": "exists", "frame_ids": []})):
        projection.write_harvest_manifest(str(root / "out"), {"ts": ts, "archive_root": str(arch),
                                                               "items": [poz]}, now=ts)
    [row] = harvest.releases([str(tmp_path / "_WBPP")], archive_root=str(arch), con=con)
    assert row.done == 1
    assert row.lineage == ((("stos-a", tuple(ids), str(kopia), None),) if czeka else ())   # pozycja bez `release`
