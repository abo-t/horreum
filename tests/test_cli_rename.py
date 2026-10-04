"""CLI `horreum rename` (PLAN_wejscia_nazw §2/§3) — DRY (zero mutacji), --apply/--undo round-trip na
SYNTETYCZNYCH plikach w `tmp_path`, --filter-json zawęża wsad (SPOT z gridem), raport ASCII-safe.
Realny R: NIGDY nie dotykany — pliki żyją w `tmp_path`."""
from __future__ import annotations

import re
from pathlib import Path

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


def test_cli_rename_undo_pokazuje_blad_przepiecia_i_komende_ponowienia(tmp_path, capsys, monkeypatch):
    """Cofnięcie przeniosło plik, ale przepięcie bazy padło: rdzeń kompensuje (plik wraca pod nazwę
    z commitu, AR-29) i zwraca `failed` z prawdą „baza nie przyjęła przepięcia… plik wrócił". Dawniej
    raport --undo mówił samo „bledy: 1" - błąd znikał z ekranu. Każdy błąd ma wiersz FAILED z powodem,
    a raport podaje komendę ponowienia (wiersze nieudane zostają w przebiegu); ponowienie domyka.

    Falsyfikator: zdejmij pętlę `res.failed` z `_format_rename_undo` → asercja o „wrócił" pada."""
    import sqlite3
    from horreum import repo
    dbp, files = _seed(tmp_path)
    assert cli.main(["rename", str(dbp), "--apply"]) == 0
    run_id = re.search(r"run_id: (\w+)", capsys.readouterr().out).group(1)
    prawdziwa = repo._apply_relocation
    stan = {"raz": True}

    def _pad_bazy(con, **kw):
        if stan["raz"]:
            stan["raz"] = False
            raise sqlite3.OperationalError("disk I/O error")
        return prawdziwa(con, **kw)
    monkeypatch.setattr(repo, "_apply_relocation", _pad_bazy)
    assert cli.main(["rename", str(dbp), "--undo", run_id]) == 0
    out = capsys.readouterr().out
    assert "przywrocono: 1" in out and "bledy: 1" in out, out
    (wiersz,) = [w for w in out.splitlines() if "FAILED" in w]
    assert "baza nie przyjęła przepięcia" in wiersz and "wrócił" in wiersz, out
    assert f"--undo {run_id}" in out.splitlines()[-1], out
    assert sum(f.exists() for f in files) == 1          # jeden plik cofnięty, drugi pod nazwą z commitu
    assert cli.main(["rename", str(dbp), "--undo", run_id]) == 0
    assert "przywrocono: 1; zablokowane: 0; bledy: 0" in capsys.readouterr().out
    assert all(f.exists() for f in files)


def test_cli_rename_undo_rozdarcie_bez_kompensacji_dokonczy_ponowienie(tmp_path, capsys, monkeypatch):
    """Przepięcie bazy padło i kompensacja `new→old` też nie wyszła: plik zostaje pod starą nazwą
    (cel cofnięcia), baza pod nazwą z commitu, zamiar renamu otwarty. Raport mówi „PRZENIESIONY…
    zamiar renamu zapisany", a ponowienie --undo rekoncyliuje tę samą lokację (wiersz RECONCILED)
    zamiast odsyłać do skanu."""
    import sqlite3
    from horreum import db, repo, writeback
    dbp, files = _seed(tmp_path)
    assert cli.main(["rename", str(dbp), "--apply"]) == 0
    run_id = re.search(r"run_id: (\w+)", capsys.readouterr().out).group(1)
    prawdziwa_rel, prawdziwy_rename = repo._apply_relocation, writeback.rename_file
    stan = {"raz": True}

    def _pad_bazy(con, **kw):
        if stan["raz"]:
            stan["raz"] = False
            raise sqlite3.OperationalError("disk I/O error")
        return prawdziwa_rel(con, **kw)

    def _bez_kompensacji(src, dst):
        if not stan["raz"] and Path(dst).name.startswith("2024"):   # wsteczny ruch na nazwę z commitu
            return writeback.RenameFileResult("failed", "PermissionError: udział zajęty")
        return prawdziwy_rename(src, dst)
    monkeypatch.setattr(repo, "_apply_relocation", _pad_bazy)
    monkeypatch.setattr(writeback, "rename_file", _bez_kompensacji)
    assert cli.main(["rename", str(dbp), "--undo", run_id]) == 0
    out = capsys.readouterr().out
    (wiersz,) = [w for w in out.splitlines() if "FAILED" in w]
    assert "PRZENIESIONY" in wiersz and "zamiar renamu zapisany" in wiersz, out
    monkeypatch.undo()
    assert all(f.exists() for f in files)               # oba pliki pod starymi nazwami na dysku
    con = db.open_db(str(dbp))
    assert len(writeback.open_rename_intents(con)) == 1
    con.close()
    assert cli.main(["rename", str(dbp)]) == 0          # DRY: zero mutacji, ale mówi o zamiarze
    assert "przerwane renamy czekajace na dokonczenie: 1" in capsys.readouterr().out
    assert cli.main(["rename", str(dbp), "--undo", run_id]) == 0
    out2 = capsys.readouterr().out
    assert "dokonczone przerwane renamy: 1; nierozstrzygniete: 0" in out2, out2
    assert "RECONCILED" in out2 and "bledy: 0" in out2, out2
    con = db.open_db(str(dbp))
    assert sorted(r["path"] for r in con.execute("SELECT path FROM location")) == \
        sorted(str(f) for f in files)
    assert not writeback.open_rename_intents(con)
    con.close()


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


def test_cli_rename_template_json_inline(tmp_path, capsys):
    """--template-json inline (lista specyfikacji): wzór bez `disc` → czysta nazwa; folder wciąga katalog."""
    dbp, _ = _seed(tmp_path)
    tmpl = '["datetime", "object", "kind", {"t": "folder", "n": 1}]'
    rc = cli.main(["rename", str(dbp), "--template-json", tmpl])
    assert rc == 0
    out = capsys.readouterr().out
    assert "do zmiany: 2" in out
    assert "abc" not in out                                  # brak dyskryminatora sha1 we wzorze
    # katalog nadrzędny (tmp_path basename) w nowej nazwie:
    assert tmp_path.name in out


def test_cli_rename_template_json_z_pliku_dict_per_typ(tmp_path, capsys):
    """--template-json ze ŚCIEŻKI PLIKU + dict per typ: klatki fits dostają wzór 'fits'."""
    dbp, _ = _seed(tmp_path)
    tf = tmp_path / "wzor.json"
    tf.write_text('{"fits": ["datetime", "kind"], "default": ["datetime", "object", "kind", "disc"]}',
                  encoding="utf-8")
    rc = cli.main(["rename", str(dbp), "--template-json", str(tf)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "do zmiany: 2" in out
    assert "_light.fits" in out and "NGC7000" not in out     # wzór fits: bez obiektu


def test_cli_rename_zly_regex_kod_2(tmp_path, capsys):
    """Zły regex `orig` w szablonie → komunikat błędu + kod 2 (INFORMUJ, zero mutacji)."""
    dbp, files = _seed(tmp_path)
    snap = {f: f.read_bytes() for f in files}
    rc = cli.main(["rename", str(dbp), "--template-json", '[{"t": "orig", "re": "("}]'])
    assert rc == 2
    assert "błąd wzoru" in capsys.readouterr().out
    for f in files:                                          # zero mutacji przy błędzie
        assert f.exists() and f.read_bytes() == snap[f]
