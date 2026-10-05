"""`horreum streaks --folder --out` (plan meteorów §3 Q1): raport przez drzwi `raport.py`, korzenie
chronione z `--folder` i `--archive-root`, wydruk ASCII (konsola cp1250/cp852), źródło nietknięte."""
import hashlib
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pytest
from astropy.io import fits

from horreum import cli


def _sub(path, k, t):
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(k)
    data = 1000 + rng.normal(0, 10, (320, 320))
    yy, xx = np.mgrid[0:320, 0:320]
    for x, y in ((30, 280), (290, 40), (280, 290), (20, 20), (160, 300)):   # gwiazdy: kotwice wyrównania
        data += 3000 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.0 ** 2))
    if k == 3:                                   # jasny ślad 200 px natywnych w klatce 3
        for i in range(200):
            data[100 + i // 2, 60 + i] += 400
    hdu = fits.PrimaryHDU(np.clip(data, 0, 65535).astype(np.uint16))
    hdu.header["IMAGETYP"] = "Light Frame"
    hdu.header["DATE-OBS"] = t.isoformat(timespec="milliseconds")
    hdu.header["EXPTIME"] = 3.0
    hdu.header["FILTER"] = "L"
    hdu.writeto(path)
    return str(path)


def _odcisk(root):
    out = {}
    for d, _, fs in os.walk(root):
        for n in fs:
            p = os.path.join(d, n)
            with open(p, "rb") as fh:
                out[p] = (hashlib.sha1(fh.read()).hexdigest(), os.stat(p).st_mtime_ns)
    return out


@pytest.fixture
def noc(tmp_path):
    root = tmp_path / "akwizycja" / "noc"
    t0 = datetime(2026, 8, 12, 22, 0, 0)
    for k in range(7):
        _sub(root / f"sub_{k:04d}.fits", k, t0 + timedelta(seconds=7 * k))
    archiwum = tmp_path / "archiwum"
    archiwum.mkdir()
    return root, archiwum


def test_raport_w_nowym_katalogu_i_wydruk_ascii(tmp_path, noc, capsys):
    root, archiwum = noc
    przed = _odcisk(root)
    out = tmp_path / "raporty" / "noc"
    kod = cli.main(["streaks", "--folder", str(root), "--out", str(out), "--archive-root", str(archiwum),
                    "--workers", "2"])
    wydruk = capsys.readouterr()
    assert kod == 0
    assert wydruk.out.isascii() and wydruk.err.isascii(), (wydruk.out, wydruk.err)
    assert "slady: 1" in wydruk.out and "klatki 7/7" in wydruk.err
    nazwy = sorted(os.listdir(out))
    assert nazwy == ["crops", "frames.csv", "manifest.json", "mosaic.png", "streaks.csv", "summary.json"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["k_sigma"], manifest["min_len_native"], manifest["workers"]) == (4.0, 80.0, 2)
    assert _odcisk(root) == przed and os.listdir(archiwum) == []


def test_parametry_trafiaja_do_manifestu(tmp_path, noc):
    root, archiwum = noc
    out = tmp_path / "r"
    assert cli.main(["streaks", "--folder", str(root), "--out", str(out), "--archive-root", str(archiwum),
                     "--k-sigma", "5", "--min-len", "120"]) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["k_sigma"], manifest["min_len_native"]) == (5.0, 120.0)


@pytest.mark.parametrize("gdzie", ["folder", "archiwum"])
def test_odmowa_pod_korzeniem_chronionym_nic_nie_liczy_ani_nie_zapisuje(tmp_path, noc, capsys, gdzie):
    root, archiwum = noc
    out = (root if gdzie == "folder" else archiwum) / "raport"
    przed = _odcisk(tmp_path)
    kod = cli.main(["streaks", "--folder", str(root), "--out", str(out), "--archive-root", str(archiwum)])
    assert kod == 2 and "ODMOWA" in capsys.readouterr().out
    assert not out.exists() and _odcisk(tmp_path) == przed


def test_zly_folder(tmp_path, noc, capsys):
    kod = cli.main(["streaks", "--folder", str(tmp_path / "brak"), "--out", str(tmp_path / "r"),
                    "--archive-root", str(noc[1])])
    assert kod == 2 and not (tmp_path / "r").exists()


@pytest.mark.parametrize("argi", [
    [],                                              # bez --archive-root: korzeń archiwum obowiązkowy
    ["--archive-root", "A", "--k-sigma", "0"],
    ["--archive-root", "A", "--min-len", "nan"],
    ["--archive-root", "A", "--workers", "0"],
])
def test_argumenty_odrzucone_przy_parsowaniu(tmp_path, argi):
    with pytest.raises(SystemExit) as exc:
        cli.main(["streaks", "--folder", str(tmp_path), "--out", str(tmp_path / "r"), *argi])
    assert exc.value.code == 2 and not (tmp_path / "r").exists()


def test_nieczytelny_sub_to_status_a_raport_powstaje(tmp_path, noc, monkeypatch, capsys):
    from horreum import streaks
    root, archiwum = noc
    zly = str(root / "sub_0001.fits")
    prawdziwy = streaks.read_binned
    monkeypatch.setattr(streaks, "read_binned", lambda p, bin=4: (_ for _ in ()).throw(
        PermissionError(13, "Odmowa", p)) if p == zly else prawdziwy(p, bin))
    out = tmp_path / "r"
    assert cli.main(["streaks", "--folder", str(root), "--out", str(out), "--archive-root", str(archiwum)]) == 0
    assert "error:io 1" in capsys.readouterr().out
    assert (out / "manifest.json").exists()


def test_blad_zapisu_raportu_to_kod_2_ascii_bez_tracebacku(tmp_path, noc, monkeypatch, capsys):
    """`--out` bez prawa zapisu / brak miejsca (bramka kimi K3): krótki komunikat ASCII, kod 2,
    raport bez manifestu, przypięcie zwolnione (katalog da się przemianować)."""
    from horreum import raport
    root, archiwum = noc
    out = tmp_path / "r"

    def odmowa_zapisu(cel, kawalki):
        raise PermissionError(13, "Odmowa dostepu", cel)

    monkeypatch.setattr(raport, "_zapisz_plik", odmowa_zapisu)
    kod = cli.main(["streaks", "--folder", str(root), "--out", str(out), "--archive-root", str(archiwum)])
    wydruk = capsys.readouterr().out
    assert kod == 2 and "BLAD I/O raportu -- PermissionError errno=13" in wydruk and wydruk.isascii()
    assert not (out / "manifest.json").exists()
    os.rename(out, tmp_path / "r_stary")


def test_odmowa_drzwi_w_trakcie_zapisu_to_kod_2(tmp_path, noc, monkeypatch, capsys):
    from horreum import raport
    root, archiwum = noc

    def odmowa(self, nazwa, dane):
        raise raport.RaportOdmowa("plik raportu juz istnieje - drzwi nie nadpisuja")

    monkeypatch.setattr(raport.Raport, "zapisz_bajty", odmowa)
    kod = cli.main(["streaks", "--folder", str(root), "--out", str(tmp_path / "r"), "--archive-root", str(archiwum)])
    assert kod == 2 and "ODMOWA" in capsys.readouterr().out
