"""Testy rdzenia żniw (`horreum.harvest`) - Qt-wolne.

Pokrycie: `discover` (prefiksy, rekurencja, `masterLight` i FITS poza), `input_stem` (`_c`, wielkość
liter, oba separatory), `read_master` z wstrzykniętymi czytnikami (rodzaj z derywacji skanu, wejścia
włączone, tożsamość nieobliczalna) i raz na PRAWDZIWYM pliku XISF z historią, `plan` na syntetycznej
bazie z wstrzykniętym czytnikiem (każdy powód z `REASONS` osobno, `exists` z bazy przed rodzajem
i proweniencją, `exists` z dysku, świadek nazwy z kopii nieobecnej, dedup po `frame_id`, siedziba
z bazy pod innym korzeniem, z zestawu rodzeństwa i złożona, cyfra kolejności, noc najwcześniejsza,
manifest-świadek), `apply` (kopia przez prawdziwą klingę do `tmp/CALIBRATION/...`, anulowanie,
`expected_sha1`, manifest `_ZNIWA.json`)."""

from __future__ import annotations

import dataclasses
import json
import os
import struct
import types

import pytest

from horreum import db, harvest, hashing, projection, repo, scan

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


def test_discover_prefiksy_rekurencja_bez_masterlight_i_fits(tmp_path):
    root = tmp_path / "wbpp"
    for rel in ("master/masterFlat_A.xisf", "master/deep/MASTERDARK_B.XISF", "masterBias_C.xisf",
                "master/masterLight_D.xisf", "master/masterFlat_E.fits", "master/flat_F.xisf",
                "master/masterFlat_A.xisf.part"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    found = [os.path.relpath(p, root).replace("\\", "/") for p in harvest.discover(str(root))]
    assert found == ["masterBias_C.xisf", "master/deep/MASTERDARK_B.XISF", "master/masterFlat_A.xisf"]
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
    assert [(it.status, it.exists_path) for it in p.items] == \
        [("exists", rf"{DB_ROOT}\CALIBRATION\masters\flats\X\CLS\M.xisf")] * 3


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

    def kopia(src, dst, *, expected_sha1):
        wolania.append((src, dst, expected_sha1))
        return ("verify_bad", "sha1 inny") if len(wolania) == 1 else ("conflict", "cel istnieje")
    r = harvest.apply(p, now=NOW, copy=kopia)
    assert wolania == [(it.src, it.dst, it.file_sha1) for it in p.items]
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

    def kopia(src, dst, *, expected_sha1):
        if src == p.items[0].src:
            raise ValueError("cel poza CALIBRATION")
        return projection.copy_master(src, dst, expected_sha1=expected_sha1)
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
    assert r.manifest_path is None and r.manifest_error == "OSError: [Errno 28] No space left on device"


def test_apply_przerwanie_zapisuje_zeznanie_wyniku_czesciowego(con, tmp_path):
    p = _would_place(con, tmp_path)

    def kopia(src, dst, *, expected_sha1):
        if src == p.items[1].src:
            raise KeyboardInterrupt
        return projection.copy_master(src, dst, expected_sha1=expected_sha1)
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
