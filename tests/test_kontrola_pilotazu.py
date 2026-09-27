"""Testy NIEZALEŻNEJ kontroli pilotażu zapisu w miejscu (`scripts/kontrola_pilotazu.py`).

Pliki FITS/XISF SYNTETYCZNE w `tmp_path`. Zapis poprawny robi PRAWDZIWY pisarz
(`writeback.write_changes_inplace`) - kontrola nie może odrzucić tego, co pisarz zapisuje zgodnie
z planem (FITS; XISF z wydłużeniem i ze skróceniem XML-a, z własnością obiektu i bez, z zerowym
i niezerowym wypełnieniem). Zapisy niedozwolone to bajty zmienione W MIEJSCU po poprawnym zapisie
(ten sam `st_ino` i rozmiar), więc kontrola musi je złapać porównaniem treści, nie metadanych."""

from __future__ import annotations

import importlib.util
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import scan, writeback

KOMENTARZ = "Name of the object of interest"
WLASNOSC_ATR = '<Property id="Observation:Object:Name" type="String" value="{}"/>'
WLASNOSC_TEKST = '<Property id="Observation:Object:Name" type="String">{}</Property>'


def _skrypt():
    sciezka = Path(__file__).resolve().parents[1] / "scripts" / "kontrola_pilotazu.py"
    spec = importlib.util.spec_from_file_location("kontrola_pilotazu_testy", sciezka)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _skrypt()


def _fits(path, *, obj="NGC6992", comment=KOMENTARZ):
    hdu = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = (obj, comment)
    hdu.header["TELESCOP"] = ("A140R", "teleskop")
    hdu.header["FILTER"] = ("Ha", "filtr")
    hdu.writeto(path, overwrite=True)
    return path


def _xisf(path, *, obj="'NGC6992'", comment="nazwa obiektu", pad=64, payload=b"\x07" * 32,
          props="", wypelnienie=b"\x00"):
    """Monolityczny XISF: XML + rezerwa `pad` + attachment (offset na stałej szerokości)."""
    def body(start):
        kw = (f'<FITSKeyword name="IMAGETYP" value="\'Light\'" comment=""/>'
              f'<FITSKeyword name="OBJECT" value="{obj}" comment="{comment}"/>')
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">' + props
                + f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                  f'location="attachment:{start:08d}:{len(payload)}">{kw}</Image></xisf>'
                ).encode("utf-8")
    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml
                 + wypelnienie * pad + payload)
    return path


def _przed(tmp_path, plik, forma):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(plik), "object": forma}]), encoding="utf-8")
    kopie = tmp_path / "kopie"
    K.przed(str(kopie), str(plan))
    return kopie


def _zapisz(plik, forma):
    """Zapis w miejscu PRAWDZIWYM pisarzem - ma przejść kontrolę."""
    ops = [writeback.WriteOp("OBJECT", "set", forma, "str", idx=0)]
    wynik = writeback.write_changes_inplace(str(plik), ops, scan.scan_file(str(plik)).header_hash)
    assert wynik.status == "applied", wynik


def _w_miejscu(plik, offset, bajty):
    """Obca zmiana bajtów W MIEJSCU: ten sam plik (`st_ino`), ten sam rozmiar."""
    with open(plik, "r+b") as fh:
        fh.seek(offset)
        fh.write(bajty)


def _zamien(plik, stare, nowe):
    assert len(stare) == len(nowe)
    dane = Path(plik).read_bytes()
    assert dane.count(stare) == 1, (stare, dane.count(stare))
    _w_miejscu(plik, dane.index(stare), nowe)


def _raport(kopie):
    return json.loads((kopie / "raport_po.json").read_text(encoding="utf-8"))[0]


# ============================================================ FITS


def test_fits_zapis_pisarza_przechodzi(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    assert K.po(str(kopie)) == 0, _raport(kopie)


def test_fits_brak_wykonania_zmiany_to_NIE(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    assert K.po(str(kopie)) == 1
    assert any("OBJECT[0] po zapisie" in x for x in _raport(kopie)["problemy"])


def _fits_zamiana_kolejnosci(p):
    dane = Path(p).read_bytes()
    i, j = dane.index(b"TELESCOP= "), dane.index(b"FILTER  = ")
    ti, tj = dane[i:i + 80], dane[j:j + 80]
    _w_miejscu(p, i, tj)
    _w_miejscu(p, j, ti)


def _fits_wypelnienie_po_end(p):
    dane = Path(p).read_bytes()
    koniec = next(i for i in range(0, 2880, 80) if dane[i:i + 80] == b"END" + b" " * 77)
    assert dane[koniec + 80:koniec + 81] == b" "
    _w_miejscu(p, koniec + 80, b"A")


def _fits_komentarz(p):
    dane = Path(p).read_bytes()
    i = dane.index(b"OBJECT  = ")
    _w_miejscu(p, i, fits.Card("OBJECT", "NGC 6992", "inny komentarz").image.encode("ascii"))


def _fits_zla_forma(p):
    dane = Path(p).read_bytes()
    i = dane.index(b"OBJECT  = ")
    _w_miejscu(p, i, fits.Card("OBJECT", "NGC 6960", KOMENTARZ).image.encode("ascii"))


def _fits_bajt_danych(p):
    dane = Path(p).read_bytes()
    _w_miejscu(p, len(dane) - 1, bytes([dane[-1] ^ 0xFF]))


@pytest.mark.parametrize("psuj", [
    _fits_zamiana_kolejnosci,
    _fits_wypelnienie_po_end,
    lambda p: _zamien(p, b"'Light   '", b"'Dark    '"),                       # inna karta
    _fits_komentarz,
    _fits_zla_forma,
    _fits_bajt_danych,
], ids=["kolejnosc_kart", "wypelnienie_po_END", "inna_karta", "komentarz_OBJECT",
        "zla_forma", "bajt_danych"])
def test_fits_zmiana_ponad_plan_to_NIE(tmp_path, psuj):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    assert K.po(str(kopie)) == 0
    psuj(p)
    assert K.po(str(kopie)) == 1, _raport(kopie)


def test_fits_obca_zmiana_przez_astropy_to_NIE(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    with fits.open(str(p), mode="update") as hdul:
        hdul[0].header["IMAGETYP"] = "Dark"
    assert K.po(str(kopie)) == 1


def test_fits_podmiana_pliku_zamiast_zapisu_w_miejscu_to_NIE(tmp_path):
    """Treść poprawna, ale plik PODMIENIONY (inny `st_ino`) - to nie jest zapis w miejscu."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    tmp = tmp_path / "a.tmp"
    tmp.write_bytes(p.read_bytes())
    os.replace(tmp, p)
    assert K.po(str(kopie)) == 1
    assert any("st_ino" in x for x in _raport(kopie)["problemy"])


# ============================================================ XISF - zapis poprawny


@pytest.mark.parametrize("obj,forma,props,wypelnienie", [
    ("'NGC6992'", "NGC 6992", "", b"\x00"),                                        # wydłużenie
    ("'Veil Nebula East'", "NGC 6992", "", b"\x00"),                               # skrócenie
    ("'NGC6992'", "NGC 6992", WLASNOSC_ATR.format("NGC6992"), b"\x00"),
    ("'Veil Nebula East'", "NGC 6992", WLASNOSC_TEKST.format("Veil Nebula East"), b"\x00"),
    ("'NGC6992'", "NGC 6992 East Veil", "", b"\x05"),                              # niezerowe
    ("'Veil Nebula East'", "NGC 6992", WLASNOSC_ATR.format("Veil Nebula East"), b"\x05"),
], ids=["wydluzenie", "skrocenie", "wydluzenie_wlasnosc_atr", "skrocenie_wlasnosc_tekst",
        "wydluzenie_wypelnienie_5", "skrocenie_wypelnienie_5_wlasnosc"])
def test_xisf_zapis_pisarza_przechodzi(tmp_path, obj, forma, props, wypelnienie):
    p = _xisf(tmp_path / "s.xisf", obj=obj, props=props, wypelnienie=wypelnienie)
    dlugosc_przed = struct.unpack("<I", p.read_bytes()[8:12])[0]
    kopie = _przed(tmp_path, p, forma)
    _zapisz(p, forma)
    assert struct.unpack("<I", p.read_bytes()[8:12])[0] != dlugosc_przed   # XML zmienił długość
    assert K.po(str(kopie)) == 0, _raport(kopie)


def test_xisf_brak_wykonania_zmiany_to_NIE(tmp_path):
    p = _xisf(tmp_path / "s.xisf", props=WLASNOSC_ATR.format("NGC6992"))
    kopie = _przed(tmp_path, p, "NGC 6992")
    assert K.po(str(kopie)) == 1


# ============================================================ XISF - zmiany ponad plan


def _xisf_bajt_wypelnienia(pierwszy):
    def psuj(p):
        dane = p.read_bytes()
        (dlugosc,) = struct.unpack("<I", dane[8:12])
        fa = scan.read_xisf_meta_full(str(p)).first_attachment
        i = 16 + dlugosc if pierwszy else fa - 1
        _w_miejscu(p, i, bytes([dane[i] ^ 0x01]))
    return psuj


def _xisf_pole_dlugosci(p):
    (dlugosc,) = struct.unpack("<I", p.read_bytes()[8:12])
    _w_miejscu(p, 8, struct.pack("<I", dlugosc + 1))


def _xisf_bajt_danych(p):
    dane = p.read_bytes()
    _w_miejscu(p, len(dane) - 1, bytes([dane[-1] ^ 0xFF]))


@pytest.mark.parametrize("psuj", [
    lambda p: _zamien(p, b'geometry="4:4:1"', b'geometry="4:4:2"'),
    lambda p: _zamien(p, b'geometry="4:4:1" sampleFormat="UInt16"',
                      b'sampleFormat="UInt16" geometry="4:4:1"'),
    lambda p: _zamien(p, b"value=\"'Light'\"", b"value=\"'Dark!'\""),
    lambda p: _zamien(p, b'comment="nazwa obiektu"', b'comment="nazwa obiektX"'),
    lambda p: _zamien(p, b'value="NGC 6992"', b'value="NGC 6993"'),
    lambda p: _zamien(p, b"value=\"'NGC 6992'\"", b"value=\"'NGC 6993'\""),
    _xisf_bajt_wypelnienia(pierwszy=True),
    _xisf_bajt_wypelnienia(pierwszy=False),
    _xisf_pole_dlugosci,
    _xisf_bajt_danych,
], ids=["geometry", "kolejnosc_atrybutow", "inna_karta", "komentarz_OBJECT",
        "wlasnosc_inna_niz_forma", "karta_inna_niz_forma", "wypelnienie_poczatek",
        "wypelnienie_koniec", "pole_dlugosci", "bajt_danych"])
def test_xisf_zmiana_ponad_plan_to_NIE(tmp_path, psuj):
    p = _xisf(tmp_path / "s.xisf", props=WLASNOSC_ATR.format("NGC6992"))
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    assert K.po(str(kopie)) == 0
    psuj(p)
    assert K.po(str(kopie)) == 1, _raport(kopie)


def test_xisf_skrocenie_bez_zer_na_poczatku_wypelnienia_to_NIE(tmp_path):
    """Skrócenie XML-a MA dołożyć zera przed wypełnieniem kopii - bajt kopii w ich miejscu to NIE."""
    p = _xisf(tmp_path / "s.xisf", obj="'Veil Nebula East'", wypelnienie=b"\x05")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    (dlugosc,) = struct.unpack("<I", p.read_bytes()[8:12])
    assert p.read_bytes()[16 + dlugosc] == 0
    _w_miejscu(p, 16 + dlugosc, b"\x05")
    assert K.po(str(kopie)) == 1


def test_xisf_komentarz_xml_wstawiony_w_miejsce_bialych_znakow_to_NIE(tmp_path):
    """Zmiana niewidoczna dla drzewa bez komentarzy: kontrola bajtowa XML-a ją łapie."""
    p = _xisf(tmp_path / "s.xisf", props="          ")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    _zamien(p, b"          ", b"<!--xx-->\n")
    assert K.po(str(kopie)) == 1


def test_xisf_warstwa_drzewa_lapie_zmiane_przepuszczona_przez_lokalizator(tmp_path, monkeypatch):
    """Druga droga porównania XML-a nie jest martwa: gdy lokalizator wycinków pomyli się i zamaskuje
    obcy atrybut (`geometry`), porównanie drzewa i tak zna tylko dwie dozwolone wartości."""
    xml0 = (b'<xisf><Image geometry="4:4:1"><FITSKeyword name="OBJECT" value="\'NGC6992\'" '
            b'comment="k"/></Image></xisf>')
    xml1 = xml0.replace(b"4:4:1", b"4:4:2").replace(b"'NGC6992'", b"'NGC 6992'")
    assert K._xml_problemy(xml0, xml1, "NGC 6992")                 # lokalizator łapie sam

    prawdziwy = K._dozwolone_wycinki

    def za_szeroki(xml):
        s = xml.index(b"geometry=") + len(b'geometry="')
        return {**prawdziwy(xml), "obcy": (s, s + 5)}
    monkeypatch.setattr(K, "_dozwolone_wycinki", za_szeroki)
    problemy = K._xml_problemy(xml0, xml1, "NGC 6992")
    assert problemy and "element" in problemy[0]


# ============================================================ przed / po-undo


def test_przed_odmawia_katalogu_z_manifestem_i_nie_nadpisuje_kopii(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    manifest = (kopie / "manifest.json").read_bytes()
    kopia = (kopie / "0000.fits").read_bytes()
    assert not (kopie / "manifest.json.tmp").exists()
    _zapisz(p, "NGC 6992")                               # oryginał już inny niż kopia
    with pytest.raises(SystemExit):
        K.przed(str(kopie), str(tmp_path / "plan.json"))
    assert (kopie / "manifest.json").read_bytes() == manifest
    assert (kopie / "0000.fits").read_bytes() == kopia


def test_przed_odmawia_katalogu_z_plikiem_kopii_bez_manifestu(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = tmp_path / "kopie"
    kopie.mkdir()
    (kopie / "0000.fits").write_bytes(b"stara kopia")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(p), "object": "NGC 6992"}]), encoding="utf-8")
    with pytest.raises(SystemExit):
        K.przed(str(kopie), str(plan))
    assert (kopie / "0000.fits").read_bytes() == b"stara kopia"
    assert sorted(x.name for x in kopie.iterdir()) == ["0000.fits"]


def test_po_undo_wymaga_bajtow_sprzed(tmp_path):
    p = _xisf(tmp_path / "s.xisf", props=WLASNOSC_ATR.format("NGC6992"))
    kopie = _przed(tmp_path, p, "NGC 6992")
    przed = p.read_bytes()
    _zapisz(p, "NGC 6992")
    assert K.po_undo(str(kopie)) == 1
    _w_miejscu(p, 0, przed)                                # cofnięcie w miejscu
    assert K.po_undo(str(kopie)) == 0
    with open(p, "ab") as fh:
        fh.write(b"\x00")
    assert K.po_undo(str(kopie)) == 1
