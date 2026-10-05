"""Drzwi raportu wobec podmiany w trakcie (dług `AR-51`, TOCTOU): przypięcie katalogów raportu,
ścieżka końcowa jako ścieżka robocza, tożsamość źródła kopii dla ASTAP. Przypięcie to blokada
współdzielenia Windows - testy podmiany katalogu stoją tylko tam."""
import os
import sys

import numpy as np
import pytest
from astropy.io import fits

from horreum import raport

WINDOWS = sys.platform == "win32"
win_only = pytest.mark.skipif(not WINDOWS, reason="przypięcie = blokada współdzielenia Windows")


def _klatka(path, seed=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(np.random.default_rng(seed).normal(1000, 10, (64, 96)).astype(np.uint16)).writeto(path)
    return str(path)


def _junction(link, cel):
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(cel), str(link))
    else:
        os.symlink(cel, link, target_is_directory=True)


def _drzewo(root):
    return sorted(os.path.relpath(os.path.join(d, n), root) for d, ds, fs in os.walk(root) for n in ds + fs)


@pytest.fixture
def noc(tmp_path):
    root = tmp_path / "noc"
    return root, [_klatka(root / "L" / "sub_0001.fits", 1), _klatka(root / "L" / "sub_0002.fits", 2)]


@win_only
def test_przypiety_katalog_raportu_i_przodek_nie_daja_sie_podmienic(tmp_path, noc):
    """Podmiana `--out` albo jego rodzica na junction wymaga zmiany nazwy - przypięcie jej odmawia
    (falsyfikator: bez uchwytu `os.rename` przechodzi i junction może stanąć w miejscu raportu)."""
    out = tmp_path / "raporty" / "noc1"
    r = raport.otworz(str(out), noc[1], chronione=[str(noc[0])])
    for src in (out, out.parent):
        with pytest.raises(OSError):
            os.rename(src, str(src) + "_stary")
    r.zapisz_bajty("crops/a.png", b"x")
    with pytest.raises(OSError):
        os.rename(out / "crops", out / "crops_stary")
    r.zamknij()
    os.rename(out / "crops", out / "crops_stary")             # po zamknięciu przypięcia już nie ma
    os.rename(out.parent, tmp_path / "raporty_stare")


@win_only
def test_with_zwalnia_przypiecie(tmp_path, noc):
    out = tmp_path / "raport"
    with raport.otworz(str(out), noc[1], chronione=[str(noc[0])]) as r:
        r.zapisz_tekst("a.csv", "x")
    os.rename(out, tmp_path / "raport_stary")


def test_sciezka_robocza_to_sciezka_koncowa_bez_junction(tmp_path, noc):
    """`--out` przez junction przodka: raport pisze w katalogu rzeczywistym, więc przepięcie junction
    na źródło po otwarciu nie kieruje zapisu do źródła (falsyfikator: ścieżka robocza = `abspath`)."""
    root, pliki = noc
    prawdziwy = tmp_path / "dysk"
    prawdziwy.mkdir()
    skrot = tmp_path / "skrot"
    _junction(skrot, prawdziwy)
    r = raport.otworz(str(skrot / "raport"), pliki, chronione=[str(root)])
    assert os.path.normcase(r.katalog) == os.path.normcase(os.path.realpath(prawdziwy / "raport"))
    os.rmdir(skrot)                                          # junction (nie cel) - przypięcie go nie trzyma
    _junction(skrot, root / "L")
    r.zapisz_tekst("slady.csv", "x")
    assert _drzewo(prawdziwy) == ["raport", os.path.join("raport", "slady.csv")]
    assert sorted(os.listdir(root / "L")) == ["sub_0001.fits", "sub_0002.fits"]
    r.zamknij()


def test_katalog_raportu_bedacy_junction_to_odmowa(tmp_path, noc):
    root, pliki = noc
    pusty = tmp_path / "gdzies"
    pusty.mkdir()
    out = tmp_path / "raport"
    _junction(out, pusty)
    with pytest.raises(raport.RaportOdmowa, match="junction"):
        raport.otworz(str(out), pliki, chronione=[str(root)])
    assert os.listdir(pusty) == []


def test_podkatalog_raportu_podmieniony_na_junction_to_odmowa(tmp_path, noc):
    """Junction założony w raporcie w miejscu podkatalogu (drugi proces) - zapis pod nim odmówiony,
    nic nie powstaje w celu junction, także głębszy człon."""
    root, pliki = noc
    r = raport.otworz(str(tmp_path / "raport"), pliki, chronione=[str(root)])
    _junction(os.path.join(r.katalog, "crops"), root / "L")
    for nazwa in ("crops/a.png", "crops/glebiej/a.png"):
        with pytest.raises(raport.RaportOdmowa, match="poza katalog raportu"):
            r.zapisz_bajty(nazwa, b"x")
    assert sorted(os.listdir(root / "L")) == ["sub_0001.fits", "sub_0002.fits"]
    r.zamknij()


def test_kopia_dla_astap_odmawia_podmienionego_zrodla(tmp_path, noc):
    """Źródło podmienione po `otworz` (inny plik pod tą samą ścieżką - jak przepięty junction w jej
    członie): tożsamość z uchwytu ≠ zapisanej, kopia odmówiona, `astap/` bez pliku
    (falsyfikator: kopia po samej ścieżce kopiuje cudzy plik)."""
    root, pliki = noc
    r = raport.otworz(str(tmp_path / "raport"), pliki, chronione=[str(root)])
    obcy = _klatka(tmp_path / "obcy" / "x.fits", 7)
    os.replace(obcy, pliki[0])
    with pytest.raises(raport.RaportOdmowa, match="inny plik"):
        r.kopia_dla_astap(pliki[0])
    assert _drzewo(r.katalog) == []
    assert os.path.basename(r.kopia_dla_astap(pliki[1])) == "sub_0002.fits"
    r.zamknij()


def test_obcy_plik_w_miejscu_podkatalogu_to_odmowa(tmp_path, noc):
    """Plik regularny `crops` włożony do raportu po otwarciu (drugi proces): zapis pod `crops/` to
    `RaportOdmowa`, nie `FileExistsError` z `os.makedirs` (bramka kimi K2); obcy plik nietknięty."""
    root, pliki = noc
    r = raport.otworz(str(tmp_path / "raport"), pliki, chronione=[str(root)])
    with open(os.path.join(r.katalog, "crops"), "wb") as fh:
        fh.write(b"cudzy")
    with pytest.raises(raport.RaportOdmowa, match="nie jest katalogiem"):
        r.zapisz_bajty("crops/a.png", b"x")
    assert open(os.path.join(r.katalog, "crops"), "rb").read() == b"cudzy"
    r.zamknij()


def test_wejscie_nieczytelne_przy_otwarciu_nie_blokuje_raportu_a_kopii_odmawia(tmp_path, noc):
    """Wejście, które zniknęło między wylistowaniem a `otworz`: raport się otwiera (klatka dostanie
    status u wołającego), kopia dla ASTAP odmawia - nie ma tożsamości do porównania."""
    root, pliki = noc
    znikniety = str(root / "L" / "sub_0003.fits")
    r = raport.otworz(str(tmp_path / "raport"), pliki + [znikniety], chronione=[str(root)])
    _klatka(root / "L" / "sub_0003.fits", 5)               # pojawił się później - to nie „ten" plik
    with pytest.raises(raport.RaportOdmowa, match="inny plik"):
        r.kopia_dla_astap(znikniety)
    r.zamknij()
