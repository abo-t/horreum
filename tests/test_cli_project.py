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


def test_cli_project_raport_ascii_safe(tmp_path, capsys):
    """Warstwa strukturalna raportu bez glifów spoza ASCII (`->`, nie `→`/`Δ`/`—` — konsola cp1250)."""
    dbp, _ = _seed(tmp_path)
    cli.main(["project", str(dbp), "--root", str(tmp_path / "_WBPP")])
    out = capsys.readouterr().out
    assert "→" not in out and "Δ" not in out and "—" not in out
