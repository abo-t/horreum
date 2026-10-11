"""Plan naprawy nagłówków w miejscu: `IMAGETYP` mastera z historii (AR-96) i `FILTER` z folderu filtra
(AR-111) - świadkowie (`filters.classify_filter_token`, `macro.folder_filter`, `macro.filename_filter`),
czysty planer (`macro.plan_header_fix`: wszystkie świadectwa każdej kopii przed rozstrzygnięciem,
sprzeczność całej pary do ręki, per kopia z kotwicą `header_hash`, bramki celu, forma karty) oraz
`horreum header-fix` na PRAWDZIWYCH plikach w `tmp_path` (DRY z trwałym planem → `--apply --plan`
drogą `writeback.commit(inplace=True)` + pochodne → drugi DRY pusty → `--undo` + pochodne; rozjazd
z planem = odmowa w całości)."""

from __future__ import annotations

import json
import os
import re

import numpy as np
import pytest
from astropy.io import fits

from horreum import cli, db, macro, scan
from horreum.resolve.filters import classify_filter_token
from test_rederive_kind import WEJSCIA, _historia, _xisf

NOW = "2026-10-11T12:00:00+00:00"
FLATS = r"R:\ASTRO_\CALIBRATION\masters\flats\RC8_2600MC"
RAW_FLATS = r"R:\ASTRO_\CALIBRATION\raw\flats\RC8_2600MC"
LIGHTS = r"R:\ASTRO_\LIGHTS"


# ============================================================ świadkowie


@pytest.mark.parametrize("token, wynik", [
    ("L-Pro", ("filtr", "L-Pro")), ("LPRO", ("filtr", "L-Pro")), ("lext", ("filtr", "L-eXtreme")),
    ("NoFilter", ("bez_filtra", None)), ("A140R_2600MC", (None, None)), ("OSC", (None, None)),
])
def test_classify_filter_token_dokladny_slownik(token, wynik):
    """Publiczna klasyfikacja tokenu osi filtra: bez wariantu verbatim `normalize_filter`. `OSC`
    to konwencja drzewa (dokłada ją `macro`), nie żeton osi."""
    assert classify_filter_token(token) == wynik


@pytest.mark.parametrize("path, kind, wynik", [
    (FLATS + r"\L-Pro\MASTERFLAT_X.xisf", "master_flat", ("filtr", "L-Pro", "L-Pro")),
    (FLATS + r"\LPRO\MASTERFLAT_X.xisf", "master_flat", ("filtr", "LPRO", "L-Pro")),   # forma != kanon
    (FLATS + r"\L-eXtreme\MASTERFLAT_X.xisf", "flat", ("filtr", "L-eXtreme", "L-eXtreme")),
    (RAW_FLATS + r"\L-Pro\2022-04-21_20-15-19__14.70_7.85s_0041-RMS0.00.fits", "flat",
     ("filtr", "L-Pro", "L-Pro")),
    (RAW_FLATS + r"\OSC\2022-04-19_06-28-05__-12.90_0.93s_0077.fits", "flat", ("bez_filtra", "OSC", None)),
    (FLATS + r"\NoFilter\M.xisf", "master_flat", ("bez_filtra", "NoFilter", None)),
    (FLATS + r"\Inny\M.xisf", "master_flat", (None, None, None)),     # segment spoza słownika filtrów
    (LIGHTS + r"\NGC3034\RC8_2600MC\L-eXtreme\NGC3034_1_.fits", "light", ("filtr", "L-eXtreme", "L-eXtreme")),
    (LIGHTS + r"\NGC3034\RC8_2600MC\OSC\NGC3034_1_.fits", "light", ("bez_filtra", "OSC", None)),
    (LIGHTS + r"\NGC5194\portable\M51 20181013_dsc3386.dng", "light", (None, None, None)),   # 1 katalog
    (LIGHTS + r"\_SOLAR\Moon\A140R_2600MC\Moon_1_.fits", "light", (None, None, None)),       # kategoria
    (LIGHTS + r"\_SOLAR\Moon\A140R_2600MC\L-Pro\Moon_1_.fits", "light", ("filtr", "L-Pro", "L-Pro")),
    (LIGHTS + r"\NGC3034\RC8_2600MC\L-Pro\x\NGC3034_1_.fits", "light", (None, None, None)),  # za głęboko
    (r"R:\ASTRO_\CALIBRATION\masters\darks\X\L-Pro\D.xisf", "master_dark", (None, None, None)),
])
def test_folder_filter(path, kind, wynik):
    assert macro.folder_filter(path, kind) == wynik


@pytest.mark.parametrize("name, wynik", [
    ("NGC3034_20220421_201245_LIGHT_FILTER_LPRO_300s_FLATGRP_202204210_.fits", "L-Pro"),
    ("NGC1976_20211110_003558_LIGHT_OSC_60s_FLATGRP_NOFLAT_.fit", ""),
    ("2023-05-07_20-40-03_CLS_-11.90_0.08s_0000.fits", "CLS"),
    ("MASTERFLAT_FLATGRP_202204210_FILTER_LEXT_.xisf", "L-eXtreme"),
    ("2022-04-21_20-15-19__14.70_7.85s_0041-RMS0.00.fits", None),
    ("M51 20181013_dsc3386.dng", None),
    ("X_FILTER_B_1.fits", "B"),                                         # po FILTER także krótki
    ("X_B_1.fits", None),                                               # bez FILTER krótki milczy
])
def test_filename_filter(name, wynik):
    assert macro.filename_filter(rf"R:\x\{name}") == wynik


# ============================================================ planer (czysty)


def _row(fid=1, lid=None, *, path=LIGHTS + r"\NGC3034\RC8_2600MC\L-Pro\NGC3034_1_.fits", kind="light",
         filetype="fits", hh=None, cards=None, facts=True, hdr_filter=None, hdr_imagetyp="Light",
         n_loc=1, **kw):
    r = {"frame_id": fid, "location_id": lid or fid * 10, "path": path, "filetype": filetype,
         "kind": kind, "header_hash": hh or f"h{lid or fid * 10}", "compressed": 0, "degen": 0,
         "unreadable_since": None, "n_sum": 0, "n_loc": n_loc, "facts_current": facts,
         "hdr_imagetyp": hdr_imagetyp, "hdr_filter": hdr_filter,
         "cards": cards if cards is not None else {"IMAGETYP": [_card("Light")]}}
    r.update(kw)
    return r


def _card(value, vtype="str", comment=None):
    return {"value_raw": value, "value_type": vtype, "comment": comment}


def test_plan_filter_z_folderu_add_z_kotwica_kopii():
    p = macro.plan_header_fix([_row()])
    (t,) = p.run.touched
    assert (t.location_id, t.keyword, t.op, t.idx, t.old_value, t.new_value, t.new_type) == \
        (10, "FILTER", "add", None, None, "L-Pro", "str")
    assert t.expected_header_hash == "h10" and t.comment is None and p.copies == 1
    assert p.changes == [("FILTER", None, "L-Pro", 1)] and p.conflicts == [] and p.run.skipped == []


def test_plan_forma_karty_folderu_domyslnie_a_parametr_przestawia():
    """wartość karty = forma folderu (`LPRO` z folderu `LPRO`), kanon tylko do porównań;
    `filter_forms` przestawia formę jawnie, a forma spoza kanonu to błąd wołającego."""
    r = _row(path=LIGHTS + r"\A\R\LPRO\x.fits")
    assert [t.new_value for t in macro.plan_header_fix([r]).run.touched] == ["LPRO"]
    assert macro.FILTER_FORM_DEFAULT == "folder"
    assert [t.new_value for t in macro.plan_header_fix(
        [r], filter_forms={"L-Pro": "L-Pro"}).run.touched] == ["L-Pro"]
    with pytest.raises(ValueError, match="nie wraca do kanonu"):
        macro.plan_header_fix([r], filter_forms={"L-Pro": "CLS"})


def test_plan_karta_zgodna_z_folderem_nic_do_zrobienia():
    zgodna = _row(cards={"FILTER": [_card("LPRO")]}, hdr_filter="LPRO")
    p = macro.plan_header_fix([zgodna])
    assert (p.run.touched, p.run.skipped, p.conflicts) == ([], [], [])


@pytest.mark.parametrize("zmiana, fragment", [
    ({"cards": {"FILTER": [_card("CLS")]}, "hdr_filter": "CLS"}, "karta klatki: CLS"),
    ({"path": LIGHTS + r"\N\R\L-Pro\N_LIGHT_FILTER_LEXT_300s_.fits"}, "nazwa pliku: L-eXtreme"),
    ({"path": LIGHTS + r"\N\R\OSC\x.fits", "cards": {"FILTER": [_card("CLS")]}, "hdr_filter": "CLS"},
     "folder OSC: bez filtra"),                                     # zmiana zbędna, sprzeczność jest
    ({"path": LIGHTS + r"\N\R\OSC\N_FILTER_LPRO_.fits"}, "nazwa pliku: L-Pro"),
])
def test_plan_kazde_swiadectwo_klasyfikowane_sprzecznosc_do_reki(zmiana, fragment):
    r = _row()
    r.update(zmiana)
    p = macro.plan_header_fix([r])
    assert p.run.touched == [] and p.run.skipped == []
    (c,) = p.conflicts
    assert c.reason.startswith("FILTER: świadectwa mówią różnie (") and fragment in c.reason


def test_plan_kopia_z_karta_cls_blokuje_dopisanie_drugiej_kopii():
    """kopia A ma kartę `CLS`, kopia B (bez karty) leży w folderze `L-Pro` - dawniej plan dopisałby
    `L-Pro` kopii B; teraz cała para `(klatka, FILTER)` idzie do ręki."""
    a = _row(lid=11, n_loc=2, path=FLATS + r"\CLS\M.xisf", kind="master_flat", filetype="xisf",
             hdr_filter="CLS", cards={"FILTER": [_card("CLS")]})
    b = _row(lid=12, n_loc=2, path=FLATS + r"\L-Pro\M.xisf", kind="master_flat", filetype="xisf",
             hdr_filter=None, cards={"FILTER": [_card("CLS")]})
    p = macro.plan_header_fix([a, b], keywords=("FILTER",))
    assert p.run.touched == [] and len(p.conflicts) == 1


def test_plan_kopie_w_folderach_roznych_filtrow_do_reki():
    """kopie jednej klatki w folderach dwóch filtrów (przypadek 15645) - nic do stagingu."""
    a = _row(lid=11, path=FLATS + r"\CLS\M.xisf", kind="flat", filetype="xisf", n_loc=2,
             cards={}, hdr_imagetyp="FLAT")
    b = _row(lid=12, path=FLATS + r"\L-Pro\M.xisf", kind="flat", filetype="xisf", n_loc=2,
             cards={}, hdr_imagetyp="FLAT")
    p = macro.plan_header_fix([a, b])
    assert p.run.touched == []
    assert [c.reason for c in p.conflicts] == [
        "FILTER: świadectwa mówią różnie (folder CLS: CLS, folder L-Pro: L-Pro)"]


def test_plan_dwie_kopie_ten_sam_folder_dwa_wpisy_kazdy_z_wlasna_kotwica():
    """plan per `location_id` - makro odmawia klatce z kilkoma kopiami, plan nie."""
    a = _row(lid=11, n_loc=2, path=LIGHTS + r"\A\R\L-Pro\x.fits")
    b = _row(lid=12, n_loc=2, path=r"F:\kopia\LIGHTS\A\R\L-Pro\x.fits")
    p = macro.plan_header_fix([a, b])
    assert [(t.location_id, t.expected_header_hash) for t in p.run.touched] == [(11, "h11"), (12, "h12")]
    assert p.copies == 2


@pytest.mark.parametrize("zmiana, powod", [
    ({"filetype": "raw"}, "plik RAW"),
    ({"compressed": 1}, "skompresowany"),
    ({"degen": 1}, "degenerat"),
    ({"header_hash": None}, "brak header_hash"),
    ({"unreadable_since": "t"}, "nieczytelna"),
    ({"n_sum": 1}, "CHECKSUM"),
    ({"facts_current": False, "n_loc": 2}, "kopia bez zebranych faktów"),
])
def test_plan_bramki_celu_pomijaja_z_powodem(zmiana, powod):
    r = _row()
    r.update(zmiana)
    p = macro.plan_header_fix([r])
    assert p.run.touched == [] and p.conflicts == []
    (s,) = p.run.skipped
    assert s.reason.startswith("FILTER: ") and powod in s.reason


def test_plan_bez_faktow_kopii_przy_jednej_lokacji_rozstrzyga_klatka():
    p = macro.plan_header_fix([_row(facts=False, hdr_filter="CLS")])
    assert [t.new_value for t in p.run.touched] == ["L-Pro"]


def test_plan_folder_bez_filtra_i_milczacy_nic_nie_proponuja():
    rows = [_row(1, path=LIGHTS + r"\A\R\OSC\x.fits"), _row(2, path=LIGHTS + r"\A\R\x.fits"),
            _row(3, path=LIGHTS + r"\A\R\L-Pro\x.fits", kind="master_light")]
    p = macro.plan_header_fix(rows)
    assert (p.run.touched, p.run.skipped, p.conflicts) == ([], [], [])


@pytest.mark.parametrize("kind, karta, oczekiwane", [
    ("master_flat", "FLAT", [("set", 0, "FLAT", "Master Flat")]),     # przeliczony z historii
    ("flat", "FLAT", []),                                             # jeszcze nieprzeliczony
    ("master_flat", "Master Flat", []),                               # karta już mówi master
    ("master_dark", "DARK", []),                                      # para spoza reguły
])
def test_plan_imagetyp_mastera(kind, karta, oczekiwane):
    r = _row(path=FLATS + r"\CLS\M.xisf", kind=kind, filetype="xisf", hdr_imagetyp=karta,
             hdr_filter="CLS", cards={"IMAGETYP": [_card(karta)], "FILTER": [_card("CLS")]})
    p = macro.plan_header_fix([r])
    assert [(t.op, t.idx, t.old_value, t.new_value) for t in p.run.touched] == oczekiwane


def test_plan_imagetyp_kopie_mowiace_rozne_rodzaje_do_reki():
    a = _row(lid=11, n_loc=2, path=FLATS + r"\CLS\M.xisf", kind="master_flat", filetype="xisf",
             hdr_imagetyp="FLAT", cards={"IMAGETYP": [_card("FLAT")]})
    b = _row(lid=12, n_loc=2, path=r"F:\k\M.xisf", kind="master_flat", filetype="xisf",
             hdr_imagetyp="LIGHT", cards={"IMAGETYP": [_card("FLAT")]})
    p = macro.plan_header_fix([a, b], keywords=("IMAGETYP",))
    assert p.run.touched == [] and len(p.conflicts) == 1


def test_plan_keywords_zaweza():
    r = _row(path=FLATS + r"\L-Pro\M.xisf", kind="master_flat", filetype="xisf", hdr_imagetyp="FLAT",
             cards={"IMAGETYP": [_card("FLAT")]})
    assert {t.keyword for t in macro.plan_header_fix([r]).run.touched} == {"IMAGETYP", "FILTER"}
    assert {t.keyword for t in macro.plan_header_fix([r], keywords=("FILTER",)).run.touched} == {"FILTER"}


# ============================================================ horreum header-fix na plikach

KARTY_RIGU = [("TELESCOP", "'RC8'"), ("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XBINNING", "1"),
              ("XPIXSZ", "3.76"), ("BAYERPAT", "'RGGB'")]


def _light_fits(path, *, seed=0, date="2022-04-21T22:00:00"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    hdu = fits.PrimaryHDU(data=(np.arange(64, dtype=np.int16).reshape(8, 8) + seed).astype(np.int16))
    for k, v in (("IMAGETYP", "Light"), ("TELESCOP", "RC8"), ("INSTRUME", "ZWO ASI2600MC Pro"),
                 ("XBINNING", 1), ("XPIXSZ", 3.76), ("BAYERPAT", "RGGB"), ("DATE-OBS", date),
                 ("EXPTIME", 300.0)):
        hdu.header[k] = v
    hdu.writeto(path)
    return str(path)


def _karty(path):
    return scan.scan_file(path).header


def _cli(capsys, *argv):
    kod = cli.main(list(argv))
    return kod, capsys.readouterr().out


def _plan(out):
    return re.search(r'--plan "([^"]+)"', out).group(1)


def _archiwum(tmp_path):
    root = tmp_path / "ASTRO_"
    master = _xisf(root / "CALIBRATION" / "masters" / "flats" / "RC8_2600MC" / "L-Pro" / "MF.xisf",
                   [("IMAGETYP", "'FLAT'"), *KARTY_RIGU, ("DATE-OBS", "'2022-04-21T20:00:00'")],
                   _historia(WEJSCIA))
    light = _light_fits(root / "LIGHTS" / "NGC3034" / "RC8_2600MC" / "L-Pro" / "L1.fits")
    osc = _light_fits(root / "LIGHTS" / "NGC3034" / "RC8_2600MC" / "OSC" / "L2.fits", seed=1)
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    for p in (master, light, osc):
        scan.ingest_record(con, scan.scan_file(p), volume="V", now=NOW, summary=scan.ScanSummary())
    cli._pochodne(con, NOW, [])                                 # stan „po Dostawie" przed naprawą
    con.close()
    return dbp, master, light, osc


def _stan(dbp, master, light):
    """`(filter_raw, filter_canon)` mastera i lightu, filtr przepisu mastera, master rodowodu lightu."""
    con = db.open_db(dbp)
    fid = {p: con.execute("SELECT frame_id FROM location WHERE path = ?", (p,)).fetchone()[0]
           for p in (master, light)}
    q = lambda p: tuple(con.execute(
        "SELECT h.filter_raw, f.filter_canon FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.id = ?", (fid[p],)).fetchone())
    profil = con.execute("SELECT p.filter_canon FROM frame f JOIN calibration_profile p "
                         "ON p.id = f.calibration_profile_id WHERE f.id = ?", (fid[master],)).fetchone()
    rodowod = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id = ? "
                          "AND relation = 'flat'", (fid[light],)).fetchone()
    stan = (q(master), q(light), profil[0] if profil else "brak", rodowod[0] if rodowod else None,
            fid[master])
    con.close()
    return stan


def test_cli_header_fix_plan_apply_drugi_dry_pusty_undo_z_pochodnymi(tmp_path, capsys):
    """DRY (3 karty w 2 kopiach, trwały plan) → `--apply --plan` → pliki, zeznanie, filtr klatki,
    przepis i rodowód po nowej karcie → drugi DRY pusty → `--undo` → pliki i WSZYSTKIE pochodne
    z powrotem."""
    dbp, master, light, osc = _archiwum(tmp_path)
    bajty = {p: open(p, "rb").read() for p in (master, light, osc)}
    przed = _stan(dbp, master, light)
    assert przed[:3] == ((None, None), (None, None), None) and przed[3] == przed[4]

    kod, out = _cli(capsys, "header-fix", dbp)
    assert kod == 0 and "zmiany 3 kart w 2 kopiach (plikach), pominiete 0, sprzecznosci do reki 0" in out
    assert "IMAGETYP: FLAT -> Master Flat: 1" in out and "FILTER: (brak karty) -> L-Pro: 2" in out
    assert all(open(p, "rb").read() == b for p, b in bajty.items())          # DRY nie pisze plików
    plik = _plan(out)
    assert len(json.load(open(plik, encoding="utf-8"))["items"]) == 3

    kod, out = _cli(capsys, "header-fix", dbp, "--apply", "--plan", plik)
    assert kod == 0 and "zapisane 2" in out and "pochodne przeliczone" in out, out
    commit = re.search(r"--undo (\d+)", out).group(1)
    assert _karty(master)["IMAGETYP"] == "Master Flat" and _karty(master)["FILTER"] == "L-Pro"
    assert _karty(light)["FILTER"] == "L-Pro" and "FILTER" not in _karty(osc)
    po = _stan(dbp, master, light)
    assert po[:3] == (("L-Pro", "L-Pro"), ("L-Pro", "L-Pro"), "L-Pro") and po[3] == po[4]

    kod, out = _cli(capsys, "header-fix", dbp)
    assert kod == 0 and "zmiany 0 kart" in out and "--apply" not in out

    kod, out = _cli(capsys, "header-fix", dbp, "--undo", commit)
    assert kod == 0 and "przywrocone 2" in out and "pochodne przeliczone" in out, out
    assert _karty(master)["IMAGETYP"] == "FLAT" and "FILTER" not in _karty(master)
    assert "FILTER" not in _karty(light)
    assert _stan(dbp, master, light) == przed


@pytest.mark.parametrize("zmiana", ["nowa_kopia", "nowa_karta"])
def test_cli_header_fix_rozjazd_z_planem_odmowa_w_calosci(tmp_path, capsys, zmiana):
    """między DRY a `--apply` doszła kopia klatki z planu albo plik dostał kartę - plan liczony
    teraz nie jest planem z DRY: odmowa w całości, pliki nietknięte."""
    dbp, master, light, osc = _archiwum(tmp_path)
    _kod, out = _cli(capsys, "header-fix", dbp, "--keyword", "FILTER")
    plik = _plan(out)
    if zmiana == "nowa_kopia":
        kopia = tmp_path / "F" / "LIGHTS" / "NGC3034" / "RC8_2600MC" / "L-Pro" / "L1.fits"
        os.makedirs(kopia.parent)
        with open(light, "rb") as a, open(kopia, "wb") as b:
            b.write(a.read())
        con = db.open_db(dbp)
        scan.ingest_record(con, scan.scan_file(str(kopia)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
        con.close()
    else:
        with fits.open(light, mode="update") as h:
            h[0].header["FILTER"] = "LPRO"
        con = db.open_db(dbp)
        scan.ingest_record(con, scan.scan_file(light), volume="V", now=NOW, summary=scan.ScanSummary())
        con.close()
    bajty = {p: open(p, "rb").read() for p in (master, light)}
    kod, out = _cli(capsys, "header-fix", dbp, "--apply", "--plan", plik)
    assert kod == 1 and "ODMOWA w calosci, zero zapisu" in out
    assert all(open(p, "rb").read() == b for p, b in bajty.items())


def test_cli_header_fix_bez_planu_odmawia_a_frames_i_keyword_zawezaja(tmp_path, capsys):
    root = tmp_path / "ASTRO_"
    a = _light_fits(root / "LIGHTS" / "A" / "R" / "L-Pro" / "a.fits")
    b = _light_fits(root / "LIGHTS" / "A" / "R" / "L-Pro" / "b.fits", seed=2)
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    for p in (a, b):
        scan.ingest_record(con, scan.scan_file(p), volume="V", now=NOW, summary=scan.ScanSummary())
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (a,)).fetchone()[0]
    con.close()
    kod, out = _cli(capsys, "header-fix", dbp, "--apply")
    assert kod == 2 and "wymaga --plan" in out
    kod, out = _cli(capsys, "header-fix", dbp, "--keyword", "FILTER", "--frames", str(fid),
                    "--filter-form", "L-Pro=LPRO")
    assert kod == 0 and "zmiany 1 kart w 1 kopiach" in out and "-> LPRO: 1" in out
    plan = json.load(open(_plan(out), encoding="utf-8"))
    assert plan["frames"] == [fid] and plan["filter_forms"] == {"L-Pro": "LPRO"}
    kod, out = _cli(capsys, "header-fix", dbp, "--keyword", "IMAGETYP")
    assert kod == 0 and "zmiany 0 kart" in out
