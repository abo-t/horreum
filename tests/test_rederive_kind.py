"""Rodzaj mastera z historii integracji i jego przeliczenie w bazie (AR-96).

Pokrycie: reguła w skanie na PRAWDZIWYCH plikach XISF (master zapisany jako `FLAT` z historią →
`master_flat`; bez historii, z historią bez wejść włączonych i FITS → `flat`), żniwa tą samą drogą
(`header_mismatch` znika), klinga `repo.rederive_frame_kind` (para spoza reguły, odmowy dryfu,
event, idempotencja) i sterownik `horreum rederive-kind` (DRY bez zapisu → `--apply` → drugi DRY
pusty; kopia zmieniona od skanu i kopie zeznające różne rodzaje = odmowa z kodem 1).
Pliki syntetyczne w `tmp_path`; baza w stanie sprzed reguły = rodzaj cofnięty na `flat` w teście."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sqlite3
import struct

import pytest

from horreum import cli, db, harvest, repo, scan
from horreum.import_fitsmirror import import_fitsmirror
from horreum.resolve.stack import parse_history
from test_import_fitsmirror import SPECS, _mk_donor

NOW = "2026-10-11T12:00:00+00:00"


def _historia(wejscia, *, wylaczone=()):
    """Własność `PixInsight:ProcessingHistory` z tabelą `images` (treść zaescape'owana jak w pliku)."""
    wiersze = "".join(
        f'&lt;tr&gt;&lt;td id="enabled" value="{"false" if p in wylaczone else "true"}"/&gt;'
        f'&lt;td id="path"&gt;{p}&lt;/td&gt;&lt;/tr&gt;' for p in wejscia)
    return ('<Property id="PixInsight:ProcessingHistory" type="String">'
            f'&lt;table id="images" rows="{len(wejscia)}"&gt;{wiersze}&lt;/table&gt;</Property>')


def _xisf(path, keywords, history_xml="", *, payload=b"\x01\x02" * 16, pad=64):
    """Monolityczny XISF: karty, historia, REZERWA `pad` przed attachmentem (zapis w miejscu)."""
    def body(start):
        karty = "".join(f'<FITSKeyword name="{k}" value="{v}" comment=""/>' for k, v in keywords)
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{start:08d}:{len(payload)}">' + karty + '</Image>'
                + history_xml + '</xisf>').encode("utf-8")
    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + b"\x00" * pad
                 + payload)
    return str(path)


WEJSCIA = [f"D:/WBPP/FLAT/2023-05-07_20-40-{i:02d}_CLS_0.08s_{i:04d}_c.xisf" for i in range(3)]


def _master_jako_flat(tmp_path, name="MASTERFLAT_A.xisf", sub="CLS", history=None, payload=None):
    p = tmp_path / "CALIBRATION" / "masters" / "flats" / "RC8_2600MC" / sub / name
    return _xisf(p, [("IMAGETYP", "'FLAT'"), ("INSTRUME", "'ZWO ASI2600MC Pro'")],
                 _historia(WEJSCIA) if history is None else history,
                 payload=payload or b"\x01\x02" * 16)


def _wjazd(con, path):
    scan.ingest_record(con, scan.scan_file(path), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)
    return con.execute("SELECT frame_id FROM location WHERE path = ?", (path,)).fetchone()[0]


def _jak_przed_regula(con, fid):
    """Baza sprzed reguły historii: ten sam plik skan nadał wtedy `flat` (stary `_derive_kind`)."""
    con.execute("UPDATE frame SET kind = 'flat' WHERE id = ?", (fid,))
    con.commit()


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    yield c
    c.close()


def _kind(con, fid):
    return con.execute("SELECT kind FROM frame WHERE id = ?", (fid,)).fetchone()[0]


def _rederived(con):
    return [json.loads(r[0]) for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'frame.rederived' ORDER BY id")]


# ============================================================ reguła w skanie i w żniwach


def test_skan_master_zapisany_jako_flat_z_historia_to_master_flat(con, tmp_path):
    fid = _wjazd(con, _master_jako_flat(tmp_path))
    assert _kind(con, fid) == "master_flat"


@pytest.mark.parametrize("history", [
    "",                                                      # bez historii integracji
    _historia(WEJSCIA, wylaczone=WEJSCIA),                   # historia bez wejść włączonych
])
def test_skan_flat_bez_dowodu_historii_zostaje_flat(con, tmp_path, history):
    fid = _wjazd(con, _master_jako_flat(tmp_path, history=history))
    assert _kind(con, fid) == "flat"


def test_derive_kind_fits_z_polem_historii_bierze_sama_karte():
    """Historia jest faktem XISF-a: rekord FITS z wypełnionym polem (wołający spoza skanu) nie
    przechodzi w mastera - reguła patrzy na format, nie na samą obecność pola."""
    rec = scan.ScanRecord(path=r"R:\x\flat.fits", size_bytes=1, mtime="t", header={"IMAGETYP": "FLAT"},
                          history=parse_history(_historia(WEJSCIA)))
    assert scan._derive_kind(dataclasses.replace(rec, path=r"R:\x\flat.xisf"), readable=True,
                             is_raw=False) == ("master_flat", "header")   # ten sam rekord jako XISF
    assert scan._derive_kind(rec, readable=True, is_raw=False) == ("flat", "header")


def test_zniwa_master_jako_flat_z_historia_ma_rodzaj_master_flat(tmp_path):
    """`harvest.read_master` bierze rodzaj z tej samej derywacji co skan: plik `masterFlat*`
    z kartą `FLAT` i historią przestaje być odmową `header_mismatch` (rodzaj `master_flat`)."""
    p = _xisf(tmp_path / "wbpp" / "master" / "masterFlat_BIN-1_FILTER-CLS_mono.xisf",
              [("IMAGETYP", "'FLAT'"), ("FILTER", "'CLS'"), ("XBINNING", "1")], _historia(WEJSCIA))
    t = harvest.read_master(p)
    assert t.kind == "master_flat" and t.inputs_enabled == tuple(WEJSCIA)


def test_zniwa_plan_master_jako_flat_nie_jest_header_mismatch(con, tmp_path):
    """Plan żniw z domyślnym czytnikiem na prawdziwym pliku: pozycja idzie dalej niż krok rodzaju
    (tu: wejścia nieznane bazie), a nie kończy się na `header_mismatch`."""
    _xisf(tmp_path / "wbpp" / "master" / "masterFlat_BIN-1_FILTER-CLS_mono.xisf",
          [("IMAGETYP", "'FLAT'"), ("FILTER", "'CLS'"), ("XBINNING", "1")], _historia(WEJSCIA))
    p = harvest.plan(con, str(tmp_path / "wbpp"), archive_root=str(tmp_path / "arch"))
    (it,) = p.items
    assert it.kind == "master_flat" and it.reason == "inputs_unknown"


# ============================================================ klinga repo.rederive_frame_kind


def _baza_flat(con, tmp_path):
    path = _master_jako_flat(tmp_path)
    fid = _wjazd(con, path)
    _jak_przed_regula(con, fid)
    loc = con.execute("SELECT id, header_hash FROM location WHERE frame_id = ?", (fid,)).fetchone()
    return fid, loc["id"], loc["header_hash"]


def test_klinga_przelicza_rodzaj_z_eventem_i_jest_idempotentna(con, tmp_path):
    fid, lid, hh = _baza_flat(con, tmp_path)
    cam = con.execute("SELECT camera_id FROM frame WHERE id = ?", (fid,)).fetchone()[0]
    header = con.execute("SELECT raw_json FROM header WHERE frame_id = ?", (fid,)).fetchone()[0]
    assert repo.rederive_frame_kind(con, frame_id=fid, expected_kind="flat", kind="master_flat",
                                    witnesses=[(lid, hh)], now=NOW) is True
    assert _kind(con, fid) == "master_flat"
    assert _rederived(con) == [{"before": {"camera_id": cam, "kind": "flat"},
                                "after": {"camera_id": cam, "kind": "master_flat"}, "locations": [lid]}]
    # bez zmiany odcisku: zeznanie i kopia nietknięte
    assert con.execute("SELECT raw_json FROM header WHERE frame_id = ?", (fid,)).fetchone()[0] == header
    assert con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0] == hh
    assert repo.rederive_frame_kind(con, frame_id=fid, expected_kind="flat", kind="master_flat",
                                    witnesses=[(lid, hh)], now=NOW) is False
    assert len(_rederived(con)) == 1


@pytest.mark.parametrize("expected, kind", [("light", "master_light"), ("flat", "master_dark"),
                                            ("master_flat", "flat"), ("dark", "master_dark")])
def test_klinga_para_spoza_reguly_historii_to_blad_wolajacego(con, tmp_path, expected, kind):
    fid, lid, hh = _baza_flat(con, tmp_path)
    with pytest.raises(ValueError, match="poza regułą"):
        repo.rederive_frame_kind(con, frame_id=fid, expected_kind=expected, kind=kind,
                                 witnesses=[(lid, hh)], now=NOW)
    assert _kind(con, fid) == "flat" and _rederived(con) == []


def test_klinga_bez_swiadka_to_blad_wolajacego(con, tmp_path):
    fid, _lid, _hh = _baza_flat(con, tmp_path)
    with pytest.raises(ValueError, match="świadka"):
        repo.rederive_frame_kind(con, frame_id=fid, expected_kind="flat", kind="master_flat",
                                 witnesses=[], now=NOW)


@pytest.mark.parametrize("dryf", ["odcisk", "nieobecna", "cudza", "rodzaj", "nowa_kopia"])
def test_klinga_odmawia_przy_dryfie_bez_zapisu(con, tmp_path, dryf):
    fid, lid, hh = _baza_flat(con, tmp_path)
    if dryf == "odcisk":
        hh = "inny-odcisk"
    elif dryf == "nieobecna":
        con.execute("UPDATE location SET present = 0 WHERE id = ?", (lid,))
    elif dryf == "cudza":
        lid = _wjazd(con, _master_jako_flat(tmp_path, name="B.xisf", payload=b"\x09" * 32))
        hh = con.execute("SELECT header_hash FROM location WHERE frame_id = ?", (lid,)).fetchone()[0]
        lid = con.execute("SELECT id FROM location WHERE frame_id = ?", (lid,)).fetchone()[0]
    elif dryf == "nowa_kopia":                        # komplet obecnych kopii != świadkowie
        kopia = tmp_path / "kopia" / "MASTERFLAT_A.xisf"
        os.makedirs(kopia.parent)
        src = con.execute("SELECT path FROM location WHERE id = ?", (lid,)).fetchone()[0]
        with open(src, "rb") as a, open(kopia, "wb") as b:
            b.write(a.read())
        assert _wjazd(con, str(kopia)) == fid
    else:
        con.execute("UPDATE frame SET kind = 'unknown' WHERE id = ?", (fid,))
    con.commit()
    przed = _kind(con, fid)
    with pytest.raises(repo.KindWitnessStale):
        repo.rederive_frame_kind(con, frame_id=fid, expected_kind="flat", kind="master_flat",
                                 witnesses=[(lid, hh)], now=NOW)
    assert _kind(con, fid) == przed and _rederived(con) == []


# ============================================================ sterownik horreum rederive-kind


def _cli(capsys, *argv):
    kod = cli.main(list(argv))
    return kod, capsys.readouterr().out


def _plan(out):
    """Ścieżka planu z wydruku DRY (wiersz polecenia `--apply --plan "..."`)."""
    return re.search(r'--plan "([^"]+)"', out).group(1)


def test_cli_dry_zapisuje_plan_apply_wykonuje_plan_drugi_dry_pusty(tmp_path, capsys):
    """syntetyczny XISF `FLAT` z historią w bazie jako `flat` → DRY 1 (bez
    zapisu w bazie, plan na dysku z kompletem świadków) → `--apply --plan` → `master_flat` i pochodne
    → drugi DRY 0 zmian i bez planu."""
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    fid, lid, hh = _baza_flat(con, tmp_path)
    con.close()

    kod, out = _cli(capsys, "rederive-kind", dbp, "--plan-dir", str(tmp_path / "plany"))
    assert kod == 0 and "zmiana rodzaju 1, bez zmiany 0, odmowy 0" in out
    assert f"frame {fid}: flat -> master_flat" in out
    plik = _plan(out)
    plan = json.load(open(plik, encoding="utf-8"))
    assert plan["polecenie"] == "rederive-kind" and plan["items"] == [
        {"frame_id": fid, "before": "flat", "after": "master_flat", "witnesses": [[lid, hh]]}]
    assert os.path.dirname(os.path.dirname(plik)) == str(tmp_path / "plany")
    con = db.open_db(dbp)
    assert _kind(con, fid) == "flat" and _rederived(con) == []           # DRY nie pisze bazy
    con.close()

    kod, out = _cli(capsys, "rederive-kind", dbp, "--apply", "--plan", plik)
    assert kod == 0 and "zapisane: 1" in out and "pochodne przeliczone: group, resolve" in out
    con = db.open_db(dbp)
    assert _kind(con, fid) == "master_flat" and len(_rederived(con)) == 1
    con.close()

    kod, out = _cli(capsys, "rederive-kind", dbp)
    assert kod == 0 and "zmiana rodzaju 0" in out and "--apply" not in out


def test_cli_apply_bez_planu_albo_z_planem_innej_bazy_odmawia(tmp_path, capsys):
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    fid, _lid, _hh = _baza_flat(con, tmp_path)
    con.close()
    kod, out = _cli(capsys, "rederive-kind", dbp, "--apply")
    assert kod == 2 and "wymaga --plan" in out
    _kod, out = _cli(capsys, "rederive-kind", dbp)
    plik = _plan(out)
    inna = str(tmp_path / "inna.db")
    db.open_db(inna).close()
    kod, out = _cli(capsys, "rederive-kind", inna, "--apply", "--plan", plik)
    assert kod == 2 and "dotyczy bazy" in out
    con = db.open_db(dbp)
    assert _kind(con, fid) == "flat"
    con.close()


def test_cli_flat_bez_historii_bez_zmiany(tmp_path, capsys):
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    _wjazd(con, _master_jako_flat(tmp_path, history=""))
    con.close()
    kod, out = _cli(capsys, "rederive-kind", dbp)
    assert kod == 0 and "zmiana rodzaju 0, bez zmiany 1, odmowy 0" in out and "plan:" not in out


@pytest.mark.parametrize("zmiana", ["naglowek", "mtime", "nowa_kopia"])
def test_cli_stan_rozjechany_z_planem_odmowa_w_calosci(tmp_path, capsys, zmiana):
    """Plan z DRY, potem świat się zmienia: plik przepisany (inny nagłówek), sam `mtime` (brama
    przyrostowa przeczyta plik od nowa) albo nowa kopia klatki wjechała skanem. `--apply` liczy plan
    od nowa, widzi rozjazd i odmawia w całości - kod 1, zero zapisu."""
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    fid, _lid, _hh = _baza_flat(con, tmp_path)
    path = con.execute("SELECT path FROM location WHERE frame_id = ?", (fid,)).fetchone()[0]
    con.close()
    _kod, out = _cli(capsys, "rederive-kind", dbp)
    plik = _plan(out)
    if zmiana == "naglowek":
        _xisf(path, [("IMAGETYP", "'FLAT'"), ("OBJECT", "'X'")], _historia(WEJSCIA))
    if zmiana in ("naglowek", "mtime"):
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    else:
        kopia = tmp_path / "kopia" / "MASTERFLAT_A.xisf"
        os.makedirs(kopia.parent)
        with open(path, "rb") as src, open(kopia, "wb") as dst:
            dst.write(src.read())
        con = db.open_db(dbp)
        assert _wjazd(con, str(kopia)) == fid
        con.close()
    kod, out = _cli(capsys, "rederive-kind", dbp, "--apply", "--plan", plik)
    assert kod == 1 and "ODMOWA w calosci, zero zapisu" in out and f"frame {fid}" in out
    con = db.open_db(dbp)
    assert _kind(con, fid) == "flat" and _rederived(con) == []
    con.close()


def test_cli_dwie_kopie_obie_swiadkami(tmp_path, capsys):
    """Klatka z dwiema obecnymi kopiami (te same bajty pod dwoma folderami): każda czytana sama,
    obie idą do planu i do klingi jako komplet świadków."""
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    a = _master_jako_flat(tmp_path, sub="CLS")
    b = tmp_path / "kopia" / "CALIBRATION" / "masters" / "flats" / "RC8_2600MC" / "CLS" / "MASTERFLAT_A.xisf"
    os.makedirs(b.parent)
    with open(a, "rb") as src, open(b, "wb") as dst:
        dst.write(src.read())
    fid = _wjazd(con, a)
    assert _wjazd(con, str(b)) == fid
    _jak_przed_regula(con, fid)
    lids = sorted(r[0] for r in con.execute("SELECT id FROM location WHERE frame_id = ?", (fid,)))
    con.close()
    _kod, out = _cli(capsys, "rederive-kind", dbp)
    assert "(+1 kop.)" in out
    kod, out = _cli(capsys, "rederive-kind", dbp, "--apply", "--plan", _plan(out))
    assert kod == 0 and "zapisane: 1" in out
    con = db.open_db(dbp)
    assert _rederived(con)[0]["locations"] == lids
    con.close()


def test_cli_kopie_zeznajace_rozne_rodzaje_to_odmowa(tmp_path, capsys):
    """Ta sama treść danych, nagłówki różne: jedna kopia z historią (master), druga bez - klatki
    nie przeliczamy automatem (do ręki); DRY z kodem 1 i bez planu."""
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    fid = _wjazd(con, _master_jako_flat(tmp_path, sub="CLS"))
    assert _wjazd(con, _master_jako_flat(tmp_path, sub="L-Pro", history="")) == fid
    _jak_przed_regula(con, fid)
    con.close()
    kod, out = _cli(capsys, "rederive-kind", dbp)
    assert kod == 1 and "kopie zeznaja rozne rodzaje: flat, master_flat" in out and "plan:" not in out
    con = db.open_db(dbp)
    assert _kind(con, fid) == "flat"
    con.close()


# ============================================================ import dawcy


def test_import_dawcy_master_jako_flat_z_historia_to_master_flat(tmp_path):
    """Import syntetyzuje `ScanRecord` z cache dawcy BEZ historii - reguła rodzaju działa tam przez
    `scan.rederive_kinds` po wjeździe, przed pochodnymi: master flat zapisany jako `FLAT` wychodzi
    z importu jako `master_flat` (z eventem `frame.rederived`); inne klatki dawcy bez przeliczenia."""
    donor_path, _files = _mk_donor(tmp_path, SPECS)
    p = _xisf(tmp_path / "astro" / "CALIBRATION" / "masters" / "flats" / "RC8_2600MM" / "Ha" / "MF.xisf",
              [("IMAGETYP", "'FLAT'"), ("TELESCOP", "'RC8'"), ("INSTRUME", "'ZWO ASI2600MM Pro'"),
               ("XPIXSZ", "3.76"), ("FILTER", "'Ha'")], _historia(WEJSCIA))
    rec = scan.scan_file(p)                         # wiersz dawcy XISF (fitsmirror: compressed 0)
    dcon = sqlite3.connect(str(donor_path))
    fid_d = dcon.execute(
        "INSERT INTO files(path, filename, ext, size, mtime, hdu_index, compressed, header_hash, "
        "sha1_file, sha1_data, status, scanned_at) VALUES (?, ?, '.xisf', ?, ?, NULL, 0, ?, ?, ?, 'ok', ?)",
        (rec.path, os.path.basename(p), rec.size_bytes, os.stat(p).st_mtime, rec.header_hash,
         rec.file_sha1, rec.sha1_data, NOW)).lastrowid
    dcon.executemany(
        "INSERT INTO cards(file_id, keyword, idx, value_raw, value_num, value_type, comment) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(fid_d, c.keyword, c.idx, c.value_raw, c.value_num, c.value_type, c.comment) for c in rec.cards])
    dcon.commit()
    dcon.close()
    s = import_fitsmirror(str(donor_path), str(tmp_path / "horreum.db"), now=NOW, rng_seed=1)
    assert s.kind_rederive.changed == 1 and s.kind_rederive.refused == []
    con = db.open_db(str(tmp_path / "horreum.db"))
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (p,)).fetchone()[0]
    assert _kind(con, fid) == "master_flat" and len(_rederived(con)) == 1   # jedna klatka, nic więcej
    con.close()
