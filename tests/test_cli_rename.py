"""CLI `horreum rename` (PLAN_wejscia_nazw §2/§3) — DRY (zero mutacji), --apply/--undo round-trip na
SYNTETYCZNYCH plikach w `tmp_path`, --filter-json zawęża wsad (SPOT z gridem), raport ASCII-safe.
Realny R: NIGDY nie dotykany — pliki żyją w `tmp_path`."""
from __future__ import annotations

import re

import numpy as np
import pytest
from astropy.io import fits

from horreum import cli, db, scan

NOW = "2026-07-04T00:00:00+00:00"


def _write_fits(path, *, fill=0, **cards):
    # `fill` RÓŻNI DANE między plikami: tożsamość frame = sha1 DANYCH (content-hash), więc identyczne
    # piksele = JEDEN frame z wieloma lokacjami (→ skip multi-location). Fixture musi wariować dane.
    hdu = fits.PrimaryHDU(data=np.full((4, 4), fill, dtype=np.int16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(str(path), overwrite=True)


def _seed(tmp_path):
    """Baza + 2 syntetyczne FITS (różne obiekty/DATE-OBS/DANE). Zwraca (db_path, [pliki])."""
    dbp = tmp_path / "cli.db"
    con = db.open_db(str(dbp))
    files = []
    for i, (obj, dobs) in enumerate([("NGC7000", "2024-03-15T21:30:45"),
                                     ("M42", "2024-03-16T22:00:00")]):
        p = tmp_path / f"raw{i}.fits"
        _write_fits(p, fill=i + 1, IMAGETYP="Light", OBJECT=obj, FILTER="Ha",
                    **{"DATE-OBS": dobs, "EXPTIME": 300.0})
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
        files.append(p)
    con.close()
    return dbp, files


def test_cli_rename_dry_zero_mutacji(tmp_path, capsys):
    dbp, files = _seed(tmp_path)
    snap = {f: f.read_bytes() for f in files}
    rc = cli.main(["rename", str(dbp), "--source", "date-obs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY" in out and "->" in out
    assert "do zmiany: 2" in out
    # DRY: pliki NIETKNIĘTE (nazwa i bajty) — kontrakt „zero mutacji"
    for f in files:
        assert f.exists() and f.read_bytes() == snap[f]


def test_cli_rename_apply_undo_roundtrip(tmp_path, capsys):
    dbp, files = _seed(tmp_path)
    rc = cli.main(["rename", str(dbp), "--apply"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "przemianowano: 2" in out
    m = re.search(r"run_id: (\w+)", out)
    assert m, out
    run_id = m.group(1)
    assert not any(f.exists() for f in files)          # stare nazwy zniknęły z dysku

    rc = cli.main(["rename", str(dbp), "--undo", run_id])
    assert rc == 0
    out2 = capsys.readouterr().out
    assert "przywrocono: 2" in out2
    assert all(f.exists() for f in files)              # oryginalne nazwy wróciły


def test_cli_rename_filter_json_zawezenie(tmp_path, capsys):
    """--filter-json = to samo drzewo co grid (goły warunek OK) → zawęża wsad do jednego obiektu."""
    dbp, _ = _seed(tmp_path)
    tree = '{"keyword": "OBJECT", "operator": "eq", "value": "NGC7000"}'
    rc = cli.main(["rename", str(dbp), "--filter-json", tree])
    assert rc == 0
    assert "do zmiany: 1" in capsys.readouterr().out   # tylko NGC7000


def test_cli_rename_raport_ascii_safe(tmp_path, capsys):
    """Warstwa strukturalna raportu bez glifów spoza ASCII (`->`, nie `→`/`Δ` — konsola cp1250)."""
    dbp, _ = _seed(tmp_path)
    cli.main(["rename", str(dbp)])
    out = capsys.readouterr().out
    assert "→" not in out and "Δ" not in out
