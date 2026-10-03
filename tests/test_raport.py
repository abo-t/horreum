"""Czwarte drzwi zapisu (`horreum/raport.py`, dług `MT-2`): katalog raportu śladów poza każdym
źródłem i zapis wyłącznie pod nim. Klatki syntetyczne na `tmp_path` - bez archiwum, bez bazy."""
import hashlib
import json
import os
import sys

import numpy as np
import pytest
from astropy.io import fits

from horreum import raport, streaks

WINDOWS = sys.platform == "win32"


def _klatka(path, seed=0):
    """Mała klatka FITS 16-bit (jak suby w testach `streaks`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.random.default_rng(seed).normal(1000, 10, (64, 96)).astype(np.uint16)
    fits.PrimaryHDU(data).writeto(path)
    return str(path)


def _odcisk(path):
    st = os.stat(path)
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest(), st.st_mtime_ns, st.st_size


def _drzewo(root):
    """Wszystkie ścieżki pod `root` (względne) - dowód, że odmowa nie zostawiła śladu."""
    return sorted(os.path.relpath(os.path.join(d, n), root)
                  for d, ds, fs in os.walk(root) for n in ds + fs)


def _dowiazanie_katalogu(link, cel):
    """Junction na Windows (bez uprawnień administratora), dowiązanie symboliczne gdzie indziej."""
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(cel), str(link))
    else:
        os.symlink(cel, link, target_is_directory=True)


@pytest.fixture
def noc(tmp_path):
    """Katalog nocy z dwiema klatkami w podkatalogu i jedną w korzeniu."""
    root = tmp_path / "noc"
    pliki = [_klatka(root / "L" / "sub_0001.fits", 1), _klatka(root / "L" / "sub_0002.fits", 2),
             _klatka(root / "sub_0001.fits", 3)]
    return root, pliki


# ---------------------------------------------------------------- katalog raportu

def test_raport_w_nowym_katalogu_obok_zrodla(tmp_path, noc):
    root, pliki = noc
    przed = {p: _odcisk(p) for p in pliki}
    out = tmp_path / "raport" / "perseidy"
    r = raport.otworz(str(out), pliki, chronione=[str(root)])
    csv_path = r.zapisz_tekst("slady.csv", "plik;x0\nsub_0001.fits;12,5\n")
    json_path = r.zapisz_tekst("manifest.json", json.dumps({"k_sigma": streaks.K_SIGMA}))
    png_path = r.zapisz_bajty("wycinki/0001.png", b"\x89PNG\r\n\x1a\n")
    assert sorted(_drzewo(out)) == sorted(["slady.csv", "manifest.json", "wycinki",
                                           os.path.join("wycinki", "0001.png")])
    assert open(csv_path, encoding="utf-8").read() == "plik;x0\nsub_0001.fits;12,5\n"
    assert json.load(open(json_path, encoding="utf-8")) == {"k_sigma": streaks.K_SIGMA}
    assert open(png_path, "rb").read() == b"\x89PNG\r\n\x1a\n"
    assert {p: _odcisk(p) for p in pliki} == przed
    assert sorted(os.listdir(root)) == ["L", "sub_0001.fits"]


def test_istniejacy_pusty_katalog_jest_przyjety(tmp_path, noc):
    out = tmp_path / "pusty"
    out.mkdir()
    r = raport.otworz(str(out), noc[1], chronione=[str(noc[0])])
    r.zapisz_tekst("a.csv", "x")
    assert _drzewo(out) == ["a.csv"]


@pytest.mark.parametrize("przygotuj", ["niepusty", "plik"])
def test_odmowa_katalogu_zajetego(tmp_path, noc, przygotuj):
    out = tmp_path / "zajety"
    if przygotuj == "niepusty":
        out.mkdir()
        (out / "cudzy.txt").write_text("nie ruszac")
    else:
        out.write_text("plik, nie katalog")
    przed = _drzewo(tmp_path)
    with pytest.raises(raport.RaportOdmowa):
        raport.otworz(str(out), noc[1], chronione=[str(noc[0])])
    assert _drzewo(tmp_path) == przed


@pytest.mark.parametrize("gdzie", [
    "L",                      # katalog plików wejścia
    "L/raport",               # pod katalogiem wejścia
    "L/a/b/raport",           # głęboko pod katalogiem wejścia
    ".",                      # korzeń nocy (katalog trzeciego pliku)
    "raport",                 # pod korzeniem nocy
])
def test_odmowa_w_katalogu_wejscia_albo_pod_nim(tmp_path, noc, gdzie):
    root, pliki = noc
    przed = _drzewo(tmp_path)
    with pytest.raises(raport.RaportOdmowa, match="leży w"):
        raport.otworz(str(root / gdzie), pliki, chronione=())   # same katalogi wejścia wystarczą
    assert _drzewo(tmp_path) == przed


def test_odmowa_pod_korzeniem_chronionym(tmp_path, noc):
    """Korzeń archiwum (i katalog `--folder`) chroni wołający: raport pod nim = odmowa, nawet gdy
    żaden plik wejścia tam nie leży."""
    archiwum = tmp_path / "archiwum"
    archiwum.mkdir()
    with pytest.raises(raport.RaportOdmowa, match="leży w"):
        raport.otworz(str(archiwum / "LIGHTS" / "raport"), noc[1], chronione=[str(archiwum)])
    assert _drzewo(archiwum) == []


def test_odmowa_pod_folderem_wejsciowym_bez_plikow(tmp_path):
    """Katalog `--folder` bez plików w korzeniu: raport w jego innym podkatalogu i tak jest pod
    źródłem (plan §0: `--out` wewnątrz katalogu źródłowego = odmowa)."""
    root = tmp_path / "noc"
    pliki = [_klatka(root / "L" / "a.fits")]
    przed = _drzewo(tmp_path)
    for out in (root / "raport", root / "inny" / "raport"):
        with pytest.raises(raport.RaportOdmowa, match="leży w"):
            raport.otworz(str(out), pliki, chronione=[str(root)])
        with pytest.raises(raport.RaportOdmowa, match="leży w"):
            raport.otworz(str(out), [], chronione=[str(root)])
    assert _drzewo(tmp_path) == przed


def test_korzen_chroniony_jest_obowiazkowy(tmp_path):
    """Wołający, który zapomni podać `--folder`, nie dostaje cicho raportu wewnątrz źródła: bez
    `chronione` drzwi nie ruszają (błąd wywołania, nic na dysku). Pusta krotka zostaje dozwolona,
    ale musi paść jawnie."""
    root = tmp_path / "noc"
    pliki = [_klatka(root / "L" / "a.fits")]
    przed = _drzewo(tmp_path)
    with pytest.raises(TypeError):
        raport.otworz(str(root / "raport"), pliki)
    with pytest.raises(TypeError):
        raport.odmowa_katalogu(str(root / "raport"), pliki)
    with pytest.raises(TypeError):
        raport.otworz(str(root / "raport"), pliki, [str(root)])     # tylko po nazwie
    assert _drzewo(tmp_path) == przed


def test_rodzenstwo_o_wspolnym_przedrostku_nie_lezy_pod_zrodlem(tmp_path, noc):
    """`noc_raport` nie leży pod `noc` - granica katalogu, nie `startswith`."""
    root, pliki = noc
    r = raport.otworz(str(tmp_path / "noc_raport"), pliki, chronione=[str(root)])
    assert os.path.isdir(r.katalog)


@pytest.mark.skipif(not WINDOWS, reason="wielkość liter rozróżnia ścieżki poza Windows")
def test_odmowa_niezalezna_od_wielkosci_liter(tmp_path, noc):
    root, pliki = noc
    with pytest.raises(raport.RaportOdmowa):
        raport.otworz(str(root / "l" / "RAPORT").upper(), pliki, chronione=())


def test_odmowa_przez_dowiazanie_do_zrodla(tmp_path, noc):
    """`--out` przez junction/dowiązanie prowadzące do katalogu wejścia = odmowa (forma `realpath`)."""
    root, pliki = noc
    link = tmp_path / "skrot"
    _dowiazanie_katalogu(link, root / "L")
    przed = _drzewo(root)
    with pytest.raises(raport.RaportOdmowa, match="leży w"):
        raport.otworz(str(link / "raport"), pliki, chronione=())
    assert _drzewo(root) == przed


# ---------------------------------------------------------------- nazwy plików pod raportem

@pytest.fixture
def otwarty(tmp_path, noc):
    return raport.otworz(str(tmp_path / "raport"), noc[1], chronione=[str(noc[0])])


@pytest.mark.parametrize("nazwa", [
    "../poza.csv",
    "..\\poza.csv",
    "wycinki/../../poza.csv",
    "./slady.csv",
    "wycinki//a.png",
    "",
    "   ",
    "slady.csv:strumien",
])
def test_nazwa_nie_wychodzi_poza_raport(tmp_path, otwarty, nazwa):
    przed = _drzewo(tmp_path)
    with pytest.raises(raport.RaportOdmowa):
        otwarty.zapisz_tekst(nazwa, "x")
    assert _drzewo(tmp_path) == przed


def test_nazwa_bezwzgledna_odrzucona(tmp_path, otwarty):
    for nazwa in (str(tmp_path / "poza.csv"), "/poza.csv", "\\poza.csv") + (("C:poza.csv",) if WINDOWS else ()):
        with pytest.raises(raport.RaportOdmowa):
            otwarty.zapisz_tekst(nazwa, "x")
    assert not (tmp_path / "poza.csv").exists()
    assert _drzewo(otwarty.katalog) == []


def test_dowiazanie_wewnatrz_raportu_nie_wyprowadza_na_zewnatrz(tmp_path, otwarty):
    zewnatrz = tmp_path / "zewnatrz"
    zewnatrz.mkdir()
    _dowiazanie_katalogu(os.path.join(otwarty.katalog, "wyj"), zewnatrz)
    with pytest.raises(raport.RaportOdmowa, match="poza katalog raportu"):
        otwarty.zapisz_tekst("wyj/slady.csv", "x")
    with pytest.raises(raport.RaportOdmowa):
        otwarty.zapisz_tekst("wyj/glebiej/slady.csv", "x")
    assert _drzewo(zewnatrz) == []


def test_drzwi_nie_nadpisuja(otwarty):
    path = otwarty.zapisz_tekst("slady.csv", "pierwszy")
    with pytest.raises(raport.RaportOdmowa, match="nie nadpisują"):
        otwarty.zapisz_tekst("slady.csv", "drugi")
    assert open(path, encoding="utf-8").read() == "pierwszy"
    assert _drzewo(otwarty.katalog) == ["slady.csv"]


def test_przerwany_zapis_nie_zostawia_pliku(otwarty):
    def kawalki():
        yield b"poczatek"
        raise RuntimeError("przerwane")
    with pytest.raises(RuntimeError):
        raport._zapisz_plik(os.path.join(otwarty.katalog, "slady.csv"), kawalki())
    assert _drzewo(otwarty.katalog) == []


@pytest.mark.skipif(not WINDOWS, reason="`os.rename` zastępuje cel poza Windows")
def test_cel_zapisany_w_trakcie_przez_drugi_proces_nie_jest_nadpisany(otwarty):
    """Drugi proces w tym samym `--out` publikuje `cel` między kontrolą `_cel` a publikacją naszego
    `.tmp`: drzwi odmawiają, cudzy wynik zostaje, nasz `.tmp` jest sprzątnięty."""
    cel = os.path.join(otwarty.katalog, "slady.csv")

    def kawalki():
        yield b"nasz"
        with open(cel, "wb") as fh:          # symulacja drugiego procesu
            fh.write(b"cudzy")
    with pytest.raises(raport.RaportOdmowa, match="nie nadpisują"):
        raport._zapisz_plik(cel, kawalki())
    assert open(cel, "rb").read() == b"cudzy"
    assert _drzewo(otwarty.katalog) == ["slady.csv"]


def test_cudzy_plik_tymczasowy_zostaje(otwarty):
    """`.tmp` istniejący przed zapisem nie jest nasz: drzwi odmawiają i go nie usuwają."""
    cel = os.path.join(otwarty.katalog, "slady.csv")
    with open(cel + ".tmp", "wb") as fh:
        fh.write(b"cudzy")
    with pytest.raises(raport.RaportOdmowa):
        otwarty.zapisz_tekst("slady.csv", "x")
    with pytest.raises(FileExistsError):
        raport._zapisz_plik(cel, [b"x"])
    assert open(cel + ".tmp", "rb").read() == b"cudzy" and not os.path.exists(cel)


# ---------------------------------------------------------------- kopia klatki dla ASTAP

def test_kopia_dla_astap_lezy_w_raporcie_a_zrodlo_nietkniete(noc, otwarty):
    root, pliki = noc
    przed = {p: _odcisk(p) for p in pliki}
    kopie = [otwarty.kopia_dla_astap(p) for p in pliki]
    assert [os.path.relpath(k, otwarty.katalog) for k in kopie] == [
        os.path.join("astap", "sub_0001.fits"), os.path.join("astap", "sub_0002.fits"),
        os.path.join("astap", "sub_0001_2.fits")]            # ta sama nazwa z dwóch katalogów
    for p, k in zip(pliki, kopie):
        assert _odcisk(k)[0] == przed[p][0]
    assert {p: _odcisk(p) for p in pliki} == przed
    assert sorted(os.listdir(root / "L")) == ["sub_0001.fits", "sub_0002.fits"]
    # kopia jest czytelna dla rdzenia jak oryginał
    assert streaks.read_binned(kopie[0]).status == "ok"


def test_kopia_tylko_ze_zgloszonych_wejsc(tmp_path, otwarty):
    obcy = _klatka(tmp_path / "inne" / "obcy.fits")
    with pytest.raises(raport.RaportOdmowa, match="nie jest wejściem"):
        otwarty.kopia_dla_astap(obcy)
    assert _drzewo(otwarty.katalog) == []
