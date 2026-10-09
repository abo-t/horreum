"""CLI `horreum project` (PLAN_projekcje §4) — DRY (zero mutacji, raport pokrycia), --apply tworzy
drzewo HARDLINKÓW pod korzeniem wykluczonym + manifest, --filter-json zawęża (inline LUB plik, SPOT
z gridem), --root WYMAGANY + guard §0 (segment wykluczony), tryb --copy, raport ASCII-safe. Realny R:
NIGDY nie dotykany — pliki żyją w `tmp_path` (ten sam wolumen → realny `os.link`)."""

from __future__ import annotations

import os

import numpy as np
import pytest
from astropy.io import fits

from horreum import cli, db, projection, scan

NOW = "2026-07-04T00:00:00+00:00"


def _write_fits(path, *, fill=0, **cards):
    # `fill` RÓŻNI DANE → różny sha1_data → osobne frame'y (content-hash identity).
    hdu = fits.PrimaryHDU(data=np.full((4, 4), fill, dtype=np.int16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(str(path), overwrite=True)


def _seed(tmp_path):
    """Baza + 2 syntetyczne FITS (różne obiekty/DANE, ten sam wolumen) w `tmp_path/lib`. Bez resolvera
    → object/filter NULL → segmenty `_UNSET` (testujemy plumbing CLI, nie resolver). Zwraca (db, [pliki])."""
    dbp = tmp_path / "cli.db"
    con = db.open_db(str(dbp))
    lib = tmp_path / "lib"
    lib.mkdir()
    files = []
    for i, obj in enumerate(["NGC7000", "M42"]):
        p = lib / f"raw{i}.fits"
        _write_fits(p, fill=i + 1, IMAGETYP="Light", OBJECT=obj, FILTER="Ha",
                    **{"DATE-OBS": "2024-03-15T21:30:45", "EXPTIME": 300.0})
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
        files.append(p)
    con.close()
    return dbp, files


def test_cli_project_dry_zero_mutacji(tmp_path, capsys):
    dbp, files = _seed(tmp_path)
    snap = {f: f.read_bytes() for f in files}
    root = tmp_path / "_WBPP" / "feed"
    rc = cli.main(["project", str(dbp), "--root", str(root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY" in out and "do zlinkowania: 2" in out
    assert not root.exists()                                # DRY: zero tworzenia
    for f in files:                                         # źródła nietknięte
        assert f.exists() and f.read_bytes() == snap[f]


def test_cli_project_apply_hardlinki_i_manifest(tmp_path, capsys):
    dbp, files = _seed(tmp_path)
    root = tmp_path / "_WBPP" / "feed"
    rc = cli.main(["project", str(dbp), "--root", str(root), "--apply"])
    assert rc == 0
    assert "zlinkowano: 2" in capsys.readouterr().out
    linked = list((root / "_UNSET" / "_UNSET").glob("*.fits"))
    assert len(linked) == 2
    for lf in linked:                                       # prawdziwy hardlink: ten sam i-węzeł
        src = tmp_path / "lib" / lf.name
        assert os.stat(str(src)).st_ino == os.stat(str(lf)).st_ino
    assert (root / projection.MANIFEST_NAME).exists()
    assert all(f.exists() for f in files)                  # źródła nietknięte (read-only wobec biblioteki)


def test_cli_project_dry_mowi_o_innym_ukladzie_w_korzeniu(tmp_path, capsys):
    """Sonda ostrzega, gdy korzeń niesie drzewo o INNYM kształcie (resztka z recenzji P2): ponowne
    wydanie dołoży drugie obok starego, a liczniki tego nie pokażą (stare leży pod inną ścieżką)."""
    dbp, _ = _seed(tmp_path)
    root = tmp_path / "_WBPP" / "feed"
    cli.main(["project", str(dbp), "--root", str(root), "--layout", "wbpp-feed", "--apply"])
    capsys.readouterr()
    rc = cli.main(["project", str(dbp), "--root", str(root), "--layout", "po-obiektach"])
    out = capsys.readouterr().out
    assert rc == 0 and "innym ukladzie" in out and "wbpp-feed" in out
    assert "do zlinkowania: 2" in out                        # ostrzega, nie blokuje


def test_cli_project_root_bez_wykluczenia_blad(tmp_path, capsys):
    """Guard §0: korzeń bez segmentu _WBPP/_Review → rc=1, komunikat, ZERO tworzenia (przed masą)."""
    dbp, _ = _seed(tmp_path)
    bad = tmp_path / "LIGHTS"
    rc = cli.main(["project", str(dbp), "--root", str(bad), "--apply"])
    assert rc == 1
    assert "wykluczonego" in capsys.readouterr().out
    assert not bad.exists()


def test_cli_project_filter_json_inline(tmp_path, capsys):
    dbp, _ = _seed(tmp_path)
    tree = '{"keyword": "OBJECT", "operator": "eq", "value": "NGC7000"}'
    root = tmp_path / "_WBPP" / "feed"
    rc = cli.main(["project", str(dbp), "--root", str(root), "--filter-json", tree])
    assert rc == 0
    assert "do zlinkowania: 1" in capsys.readouterr().out   # tylko NGC7000


def test_cli_project_filter_json_z_pliku(tmp_path, capsys):
    dbp, _ = _seed(tmp_path)
    fp = tmp_path / "flt.json"
    fp.write_text('{"keyword": "OBJECT", "operator": "eq", "value": "M42"}', encoding="utf-8")
    root = tmp_path / "_WBPP" / "feed"
    rc = cli.main(["project", str(dbp), "--root", str(root), "--filter-json", str(fp)])
    assert rc == 0
    assert "do zlinkowania: 1" in capsys.readouterr().out


def test_cli_project_copy_mode(tmp_path, capsys):
    dbp, _ = _seed(tmp_path)
    root = tmp_path / "_Review" / "copies"
    rc = cli.main(["project", str(dbp), "--root", str(root), "--apply", "--copy"])
    assert rc == 0
    assert "zlinkowano: 2" in capsys.readouterr().out
    copied = list((root / "_UNSET" / "_UNSET").glob("*.fits"))
    assert len(copied) == 2
    for cf in copied:                                       # kopia → INNY i-węzeł
        src = tmp_path / "lib" / cf.name
        assert os.stat(str(src)).st_ino != os.stat(str(cf)).st_ino


def test_cli_project_root_wymagany(tmp_path):
    dbp, _ = _seed(tmp_path)
    with pytest.raises(SystemExit):                         # argparse: --root required
        cli.main(["project", str(dbp)])


def test_cli_project_kazdy_layout_z_LAYOUTS_przechodzi(tmp_path, capsys):
    """Jeden właściciel listy układów: `projection.LAYOUTS` (layout = DANE, D-P1). Test chodzi po
    KLUCZACH, więc trzeci układ jest pokryty bez dopisywania testu — a CLI, które by go nie znało,
    tu pada. Wcześniej `choices` w parserze duplikowało tę listę ręcznie (SIN-DUP)."""
    dbp, _ = _seed(tmp_path)
    for layout in sorted(projection.LAYOUTS):
        rc = cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), "--layout", layout])
        assert rc == 0, layout
        assert "DRY" in capsys.readouterr().out


def test_cli_project_nieznany_layout_wypisuje_dostepne(tmp_path, capsys):
    """Cisza po literówce byłaby najgorszą odpowiedzią — komunikat NIESIE listę (ASCII: stderr nie
    jest przełączany na UTF-8)."""
    dbp, _ = _seed(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), "--layout", "po-obiektah"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "nieznany uklad" in err
    for layout in projection.LAYOUTS:
        assert layout in err
    assert err.isascii()


def test_cli_project_raport_ascii_safe(tmp_path, capsys):
    """Warstwa strukturalna raportu bez glifów spoza ASCII (`->`, nie `→`/`Δ`/`—` — konsola cp1250)."""
    dbp, _ = _seed(tmp_path)
    cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP")])
    out = capsys.readouterr().out
    assert "→" not in out and "Δ" not in out and "—" not in out


# ============================================================ tryb obiektu (`--object`)


def _seed_obiekt(tmp_path):
    """Baza z obiektem IC1795 w dwóch zestawach (A140R i RC8 na tej samej kamerze mono): Ha z master
    flatem ze STANU, OIII z surowymi flatami z tej samej nocy, Ha w drugim zestawie bez niczego.
    Pliki prawdziwe w `tmp_path/lib` (realny `os.link` przy --apply). Zwraca ścieżkę bazy."""
    from horreum.calibration import run_calibration
    dbp = tmp_path / "obj.db"
    con = db.open_db(str(dbp))
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES (1, 'ASI2600MM', 1, ?)", (NOW,))
    con.execute("INSERT INTO telescope (id, telescop_canon, status, created_at) VALUES "
                "(1, 'A140R', 'proposed', ?), (2, 'RC8', 'proposed', ?)", (NOW, NOW))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES "
                "(10, 1, 1, 'proposed', ?), (20, 2, 1, 'proposed', ?)", (NOW, NOW))
    con.execute("INSERT INTO object (id, canon) VALUES (7, 'IC1795')")
    lib = tmp_path / "lib"
    lib.mkdir()

    def klatka(name, kind, config_id, filter_canon, date_obs="2024-03-01T23:00:00", object_id=None):
        (lib / name).write_bytes(name.encode())
        fid = con.execute(
            "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_id, filter_canon, "
            "first_seen_at) VALUES (?, ?, 'fits', 1, ?, ?, ?, ?)",
            (name, kind, config_id, object_id, filter_canon, NOW)).lastrowid
        con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning) "
                    "VALUES (?, '{}', ?, 600.0, 1)", (fid, date_obs))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, str(lib / name)))
        return fid

    mf = klatka("mf.xisf", "master_flat", 10, "Ha")
    l_ha = klatka("l_ha.fits", "light", 10, "Ha", object_id=7)
    klatka("l_oiii.fits", "light", 10, "OIII", object_id=7)
    klatka("f1.fits", "flat", 10, "OIII", date_obs="2024-03-02T05:30:00")
    klatka("f2.fits", "flat", 10, "OIII", date_obs="2024-03-02T05:31:00")
    klatka("l_rc8.fits", "light", 20, "Ha", object_id=7)
    con.commit()
    run_calibration(con, now=NOW)
    con.execute("INSERT INTO calibration (light_frame_id, master_frame_id, relation, asserted_by, "
                "confidence) VALUES (?, ?, 'flat', 'horreum', 'recipe')", (l_ha, mf))
    con.commit()
    con.close()
    return dbp


def test_cli_project_object_dry_raport_per_zestaw(tmp_path, capsys):
    """`--object` po kanonie BEZ wielkości liter: raport per zestaw (lighty, godziny, mastery, surowe
    z nocą, bez flatu, bez darka), potem raport linków pod korzeniem `<cel>/<obiekt>`. DRY = zero
    tworzenia."""
    dbp = _seed_obiekt(tmp_path)
    root = tmp_path / "_WBPP" / "karta"
    rc = cli.main(["project", str(dbp), "--root", str(root), "--object", "ic1795"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "--object IC1795 (id 7; zestawy: wszystkie; okno surowych flatow: 30 dni)" in out
    assert ("A140R_ASI2600MM (config 10): lighty 2; godz 0.33; mastery flat 1; "
            "surowe flaty 2 (noce: 2024-03-01); bez flatu 0; bez darka 2") in out
    assert "RC8_ASI2600MM (config 20): lighty 1;" in out and "luki flatu: no_profile 1" in out
    assert f"Horreum project {root / 'OBJECTS' / 'IC1795'} (DRY" in out and "layout wbpp-obiekt" in out
    assert "do zlinkowania: 6" in out                      # 3 lighty + 1 master + 2 surowe
    assert "A140R_ASI2600MM/FLAT_RAW/OIII: 2" in out
    assert not root.exists()
    assert "→" not in out and "—" not in out


def test_cli_project_object_po_id_zestaw_i_okno(tmp_path, capsys):
    """Obiekt po id; `--zestaw` zawęża do jednego configu; `--flat-window` dochodzi do wyboru surowych."""
    dbp = _seed_obiekt(tmp_path)
    rc = cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), "--object", "7",
                   "--zestaw", "20", "--flat-window", "0"])
    out = capsys.readouterr().out
    assert rc == 0 and "zestawy: config 20; okno surowych flatow: 0 dni" in out
    assert "RC8_ASI2600MM" in out and "A140R_ASI2600MM" not in out
    assert "do zlinkowania: 1" in out


def test_cli_project_object_apply_drzewo_i_manifest_w_folderze_obiektu(tmp_path, capsys):
    """`--apply`: drzewo i manifest pod `<cel>/<obiekt>`, manifest = treść `object_manifest`."""
    import json
    dbp = _seed_obiekt(tmp_path)
    root = tmp_path / "_WBPP" / "karta"
    rc = cli.main(["project", str(dbp), "--root", str(root), "--object", "IC1795", "--apply"])
    assert rc == 0 and "zlinkowano: 6" in capsys.readouterr().out
    obj_root = root / "OBJECTS" / "IC1795"
    linked = obj_root / "A140R_ASI2600MM" / "FLAT_RAW" / "OIII" / "f1.fits"
    assert os.stat(str(linked)).st_ino == os.stat(str(tmp_path / "lib" / "f1.fits")).st_ino
    payload = json.loads((obj_root / projection.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert payload["layout"] == "wbpp-obiekt" and payload["object_id"] == 7
    assert sorted(payload["zestawy"]) == ["A140R_ASI2600MM", "RC8_ASI2600MM"]


@pytest.mark.parametrize("extra", [
    ["--layout", "po-obiektach"],
    ["--filter-json", '{"keyword": "OBJECT", "operator": "eq", "value": "IC1795"}'],
])
def test_cli_project_object_wyklucza_layout_i_filtr(tmp_path, capsys, extra):
    """Tryb obiektu ma STAŁY układ i własną populację - jawny układ albo filtr obok niego to błąd
    użycia (argparse, kod 2), nie cicha preferencja. Komunikat ASCII (stderr bywa cp1250)."""
    dbp = _seed_obiekt(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), "--object", "IC1795", *extra])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--object wyklucza sie" in err and err.isascii()


@pytest.mark.parametrize("extra", [["--zestaw", "10"], ["--flat-window", "5"]])
def test_cli_project_flagi_obiektu_bez_obiektu(tmp_path, capsys, extra):
    dbp = _seed_obiekt(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), *extra])
    assert exc.value.code == 2 and "tylko z --object" in capsys.readouterr().err


def test_cli_project_object_nieznany_i_ujemne_okno(tmp_path, capsys):
    """Nieznany obiekt → rc=1 z komunikatem (ani kanon, ani id); ujemne okno → błąd użycia."""
    dbp = _seed_obiekt(tmp_path)
    rc = cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), "--object", "M999"])
    assert rc == 1 and "nieznany obiekt 'M999'" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP"), "--object", "7",
                  "--flat-window", "-1"])
    assert exc.value.code == 2
