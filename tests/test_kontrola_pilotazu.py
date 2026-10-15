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


# ============================================================ para ścieżek (zmiana obiektu, AR-17 krok 3)


def _przed_para(tmp_path, plik, po, forma):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(plik), "po": str(po), "object": forma}]),
                    encoding="utf-8")
    kopie = tmp_path / "kopie"
    K.przed(str(kopie), str(plan))
    return kopie


def test_para_przeniesienie_i_karta_przechodzi_a_cofniecie_wraca_bajt_w_bajt(tmp_path):
    """Gest: jeden `os.rename` do folderu nowego obiektu + karta w miejscu pod nową ścieżką →
    `po` OK (ten sam `st_ino`, bajty poza kartą jak kopia); cofnięcie (karta w miejscu, plik wraca)
    → `po-undo` OK, a plik zostawiony pod nową ścieżką to NIE."""
    (tmp_path / "Sh2-229").mkdir()
    p = _fits(tmp_path / "Sh2-229" / "a.fits")
    po = tmp_path / "IC405" / "IC405_a.fits"
    kopie = _przed_para(tmp_path, p, po, "NGC 6992")
    przed = p.read_bytes()
    po.parent.mkdir()
    os.rename(p, po)
    _zapisz(po, "NGC 6992")
    assert K.po(str(kopie)) == 0, _raport(kopie)
    assert _raport(kopie)["plik"] == str(po)
    assert K.po_undo(str(kopie)) == 1                        # plik nadal pod nową ścieżką
    _w_miejscu(po, 0, przed)
    os.rename(po, p)
    assert K.po_undo(str(kopie)) == 0
    po.write_bytes(p.read_bytes())                            # kopia pod nową ścieżką została
    assert K.po_undo(str(kopie)) == 1


def test_para_bez_karty_raw_caly_plik_jak_kopia(tmp_path):
    """`"object": null` (RAW - format bez karty): po przeniesieniu CAŁY plik bajt w bajt jak kopia,
    jeden zmieniony bajt to NIE; RAW nie otwiera się czytnikiem FITS i nie musi."""
    from test_exif import build_raw
    p = tmp_path / "c.dng"
    p.write_bytes(build_raw())
    po = tmp_path / "IC405_c.dng"
    kopie = _przed_para(tmp_path, p, po, None)
    os.rename(p, po)
    assert K.po(str(kopie)) == 0, _raport(kopie)
    _w_miejscu(po, len(po.read_bytes()) - 1, b"\x7f")
    assert K.po(str(kopie)) == 1
    assert any("bajty pliku rozne od kopii" in x for x in _raport(kopie)["problemy"])


def test_para_kopia_zamiast_przeniesienia_to_NIE(tmp_path):
    """Plik SKOPIOWANY pod nową ścieżkę (inny `st_ino`) i zostawiony pod starą - dwa „NIE”."""
    p = _fits(tmp_path / "a.fits")
    po = tmp_path / "b.fits"
    kopie = _przed_para(tmp_path, p, po, "NGC 6992")
    po.write_bytes(p.read_bytes())
    _zapisz(po, "NGC 6992")
    assert K.po(str(kopie)) == 1
    problemy = _raport(kopie)["problemy"]
    assert any("st_ino" in x for x in problemy)
    assert any("sprzed przeniesienia nadal lezy" in x for x in problemy)


def test_para_przed_odmawia_bez_klucza_object_i_przy_zajetym_celu(tmp_path):
    p = _fits(tmp_path / "a.fits")
    zajety = _fits(tmp_path / "b.fits")
    plan = tmp_path / "plan.json"
    for wpis in ({"plik": str(p), "po": str(tmp_path / "c.fits")},
                 {"plik": str(p), "po": str(zajety), "object": "NGC 6992"}):
        plan.write_text(json.dumps([wpis]), encoding="utf-8")
        with pytest.raises(SystemExit):
            K.przed(str(tmp_path / "kopie"), str(plan))
        assert not (tmp_path / "kopie").exists()


# ============================================================ dopisanie karty FITS w miejscu (AR-156)
# Pełny kształt pozycji planu `{plik, keyword, value, comment, op}`. Zapis poprawny robi PRAWDZIWY
# pisarz (`write_changes_inplace` z `add`) - model reguły w kontroli jest własny, więc zgodność
# z pisarzem w każdym układzie końca nagłówka to dowód, że obie strony rozumieją regułę tak samo.

UKLADY = ("zwykly", "komentarze", "pusta")


def _fits_bez(path, brak, uklad="zwykly"):
    """FITS bez karty `brak`, z wolnymi rekordami za END. Koniec nagłówka wg `uklad`: `zwykly` -
    ostatnia karta zwykła; `komentarze` - blok COMMENT/HISTORY na końcu; `pusta` - pusta karta na
    końcu (pisarz ją zużywa)."""
    hdu = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8))
    hdu.header["IMAGETYP"] = "Light"
    for kw, wartosc in (("OBJECT", ("NGC6992", KOMENTARZ)), ("TELESCOP", ("A140R", "teleskop")),
                        ("FILTER", ("Ha", "filtr"))):
        if kw != brak:
            hdu.header[kw] = wartosc
    if uklad == "komentarze":
        hdu.header.add_comment("komentarz kopii")
        hdu.header.add_history("historia kopii")
    elif uklad == "pusta":
        hdu.header.append()
    hdu.writeto(path, overwrite=True)
    return path


def _rekordy(dane):
    koniec = next(i for i in range(0, 2880, 80) if dane[i:i + 80] == b"END" + b" " * 77) // 80
    return [dane[i:i + 80] for i in range(0, 2880, 80)], koniec


def _plan(tmp_path, pozycje, katalog="kopie"):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(pozycje), encoding="utf-8")
    kopie = tmp_path / katalog
    K.przed(str(kopie), str(plan))
    return kopie


def _przed_add(tmp_path, plik, kw, wartosc, komentarz=None):
    return _plan(tmp_path, [{"plik": str(plik), "keyword": kw, "value": wartosc,
                             "comment": komentarz, "op": "add"}])


def _dopisz(plik, kw, wartosc, komentarz=None):
    """Dopisanie W MIEJSCU prawdziwym pisarzem - ma przejść kontrolę."""
    ops = [writeback.WriteOp(kw, "add", wartosc, "str", comment=komentarz)]
    wynik = writeback.write_changes_inplace(str(plik), ops,
                                            scan.scan_file(str(plik)).header_hash)
    assert isinstance(wynik, writeback.WriteResult) and wynik.status == "applied", wynik
    assert wynik.in_place, wynik
    return wynik


@pytest.mark.parametrize("uklad", UKLADY)
@pytest.mark.parametrize("kw, wartosc", [("OBJECT", "NGC 6992"), ("FILTER", "Ha")])
def test_fits_add_dopisanie_pisarza_przechodzi_w_kazdym_ukladzie(tmp_path, kw, wartosc, uklad):
    """Trzy układy końca nagłówka: (a) bez bloku końcowego i bez pustych kart - `END` o rekord niżej;
    (b) blok COMMENT/HISTORY na końcu - karta PRZED nim, blok przesunięty, `END` niżej; (c) pusta
    karta na końcu - zużyta, `END` na miejscu. Pisarz i własny model kontroli dają te same bajty."""
    p = _fits_bez(tmp_path / "a.fits", kw, uklad)
    stare, koniec = _rekordy(p.read_bytes())
    kopie = _przed_add(tmp_path, p, kw, wartosc)
    _dopisz(p, kw, wartosc)
    nowe, koniec_po = _rekordy(p.read_bytes())
    assert koniec_po == koniec + (uklad != "pusta")                  # fakt pisarza, nie modelu
    i = next(j for j, r in enumerate(nowe) if r[:8] == kw.ljust(8).encode())
    if uklad == "komentarze":
        assert [r[:8] for r in nowe[i + 1:i + 3]] == [b"COMMENT ", b"HISTORY "]
    assert K.po(str(kopie)) == 0, _raport(kopie)
    w = json.loads((kopie / "manifest.json").read_text(encoding="utf-8"))[0]
    assert {k: w[k] for k in ("keyword", "value", "comment", "op")} == {
        "keyword": kw, "value": wartosc, "comment": None, "op": "add"}


def test_fits_add_z_komentarzem_planu_przechodzi(tmp_path):
    p = _fits_bez(tmp_path / "a.fits", "OBJECT")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992", "nazwa obiektu")
    _dopisz(p, "OBJECT", "NGC 6992", "nazwa obiektu")
    assert K.po(str(kopie)) == 0, _raport(kopie)


def test_fits_add_brak_wykonania_to_NIE(tmp_path):
    p = _fits_bez(tmp_path / "a.fits", "OBJECT")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    assert K.po(str(kopie)) == 1
    assert any("skan: brak karty OBJECT[0] po zapisie" in x for x in _raport(kopie)["problemy"])


def _karta_obraz(kw, wartosc, komentarz=""):
    return fits.Card(kw, wartosc, komentarz).image.encode("ascii")


def _add_przestaw(p):
    """Karta pod złą pozycją: nowa karta i jej poprzedniczka zamienione miejscami."""
    rekordy, _ = _rekordy(p.read_bytes())
    i = next(j for j, r in enumerate(rekordy) if r[:8] == b"OBJECT  ")
    _w_miejscu(p, (i - 1) * 80, rekordy[i] + rekordy[i - 1])


def _add_za_end(p, kopia):
    """`END` niezsunięty: plik = kopia z kartą wpisaną w wolny rekord ZA `END` (blok komentarzy
    i `END` na starych miejscach)."""
    dane = kopia.read_bytes()
    _, koniec = _rekordy(dane)
    _w_miejscu(p, 0, dane)
    _w_miejscu(p, (koniec + 1) * 80, _karta_obraz("OBJECT", "NGC 6992"))


def _add_pod_koniec(p, kopia):
    """Karta za blokiem COMMENT/HISTORY (tuż przed `END`, `END` zsunięty) - porządek `bottom`,
    nie reguła pisarza."""
    dane = kopia.read_bytes()
    _, koniec = _rekordy(dane)
    _w_miejscu(p, 0, dane)
    _w_miejscu(p, koniec * 80, _karta_obraz("OBJECT", "NGC 6992") + b"END" + b" " * 77)


def _add_zly_komentarz(p):
    i = p.read_bytes().index(b"OBJECT  = ")
    _w_miejscu(p, i, _karta_obraz("OBJECT", "NGC 6992", "inny"))


def _add_wypelnienie(p):
    """Wypełnienie zjedzone: rekord za nowym `END` nie jest już wolny."""
    _, koniec = _rekordy(p.read_bytes())
    _w_miejscu(p, (koniec + 1) * 80, b"X")


@pytest.mark.parametrize("psuj, oczekiwany", [
    (lambda p, k: _zamien(p, b"'Light   '", b"'Dark    '"), "karta kopii"),
    (lambda p, k: _add_przestaw(p), "region naglowka rozny"),
    (_add_za_end, "nowa karta OBJECT"),
    (_add_pod_koniec, "nowa karta OBJECT"),
    (lambda p, k: _add_zly_komentarz(p), "komentarz OBJECT[0]"),
    (lambda p, k: _add_wypelnienie(p), "wypelnienie za END"),
    (lambda p, k: _fits_bajt_danych(p), "bajty poza regionem"),
], ids=["bajt_przed_karta", "karta_pod_zla_pozycja", "END_niezsuniety", "karta_za_komentarzami",
        "zly_komentarz", "wypelnienie_zjedzone", "dane_zmienione"])
def test_fits_add_zmiana_ponad_plan_to_NIE(tmp_path, psuj, oczekiwany):
    p = _fits_bez(tmp_path / "a.fits", "OBJECT", "komentarze")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    _dopisz(p, "OBJECT", "NGC 6992")
    assert K.po(str(kopie)) == 0, _raport(kopie)
    psuj(p, kopie / "0000.fits")
    assert K.po(str(kopie)) == 1, _raport(kopie)
    assert any(oczekiwany in x for x in _raport(kopie)["problemy"]), _raport(kopie)


def test_fits_add_przepisany_atomowo_to_NIE(tmp_path):
    """Pisarz bez zapisu w miejscu (droga atomowa: cały plik przepisany, nowy `st_ino`) - pilotaż
    `add` sprawdza drogę w miejscu, więc kontrola mówi NIE, choć karta jest."""
    p = _fits_bez(tmp_path / "a.fits", "OBJECT")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    wynik = writeback.write_changes(str(p), [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")],
                                    None)
    assert wynik.status == "applied" and not wynik.in_place, wynik
    assert K.po(str(kopie)) == 1
    assert any("przepisany w calosci, nie w miejscu" in x for x in _raport(kopie)["problemy"])


def test_fits_add_kopia_bez_zapasu_to_NIE_z_powodem(tmp_path):
    """Kopia bez pustej karty na końcu i bez wolnego rekordu za `END` - model mówi, że dopisanie
    w miejscu jest niemożliwe (pisarz spadłby na drogę atomową)."""
    p = tmp_path / "pelny.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    while (len(hdu.header) + 1) % 36:                 # karty + END = pełny blok 2880 B
        hdu.header[f"K{len(hdu.header):03d}"] = "v"
    hdu.writeto(p)
    assert len(p.read_bytes()) == 2880 + 2880 and _rekordy(p.read_bytes())[1] == 35
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    assert isinstance(writeback.write_changes_inplace(
        str(p), [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")], None), writeback.Fallback)
    assert K.po(str(kopie)) == 1
    assert any("dopisanie w miejscu niemozliwe" in x for x in _raport(kopie)["problemy"])


def test_po_undo_po_dopisaniu_cofnietym_w_miejscu(tmp_path):
    """Cofnięcie W MIEJSCU prawdziwym pisarzem (`restore_inplace` z backupu regionu) → `po-undo`
    OK (sha1 całego pliku, rozmiar, `st_ino` sprzed); przed cofnięciem NIE."""
    p = _fits_bez(tmp_path / "a.fits", "FILTER", "komentarze")
    kopie = _przed_add(tmp_path, p, "FILTER", "Ha")
    wynik = _dopisz(p, "FILTER", "Ha")
    assert K.po_undo(str(kopie)) == 1
    backup = writeback.RegionBackup.decode(wynik.backup_text)
    st = os.stat(p)
    with open(p, "rb") as fh:
        fh.seek(backup.offset)
        region = fh.read(len(backup.region))
    cofniecie = writeback.restore_inplace(str(p), backup, op_new_region=region,
                                          op_file_size=st.st_size, op_file_ino=st.st_ino,
                                          op_post_hash=wynik.post_hash)
    assert cofniecie.status == "applied" and cofniecie.in_place, cofniecie
    assert K.po_undo(str(kopie)) == 0


def test_fits_set_innej_karty_z_komentarzem_planu(tmp_path):
    """`set` karty spoza OBJECT (populacja `header-fix` z `FILTER`): komentarz z planu wchodzi do
    karty, komentarz null zostawia zastany; zastany przy planie z komentarzem to NIE."""
    p = _fits(tmp_path / "a.fits")
    kopie = _plan(tmp_path, [{"plik": str(p), "keyword": "FILTER", "value": "OIII",
                              "comment": "filtr waski", "op": "set"}])
    ops = [writeback.WriteOp("FILTER", "set", "OIII", "str", idx=0, comment="filtr waski")]
    assert writeback.write_changes_inplace(str(p), ops, None).status == "applied"
    assert K.po(str(kopie)) == 0, _raport(kopie)
    i = p.read_bytes().index(b"FILTER  = ")
    _w_miejscu(p, i, _karta_obraz("FILTER", "OIII", "filtr"))
    assert K.po(str(kopie)) == 1
    assert any("komentarz FILTER[0]" in x for x in _raport(kopie)["problemy"])


def test_manifest_sprzed_pelnego_ksztaltu_czytany_skrotem_object(tmp_path):
    """Manifest zapisany przed AR-156 (`"object"` zamiast pełnego kształtu) - `po` czyta go jak
    `OBJECT` `set` bez komentarza."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    sciezka = kopie / "manifest.json"
    manifest = json.loads(sciezka.read_text(encoding="utf-8"))
    for w in manifest:
        for k in ("keyword", "value", "comment", "op"):
            del w[k]
        w["object"] = "NGC 6992"
    sciezka.write_text(json.dumps(manifest), encoding="utf-8")
    _zapisz(p, "NGC 6992")
    assert K.po(str(kopie)) == 0, _raport(kopie)


@pytest.mark.parametrize("pozycja, plik", [
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "add"}, "z_karta"),
    ({"keyword": "FILTER", "value": "Ha", "comment": None, "op": "set"}, "bez_filter"),
    ({"object": "X", "keyword": "OBJECT", "value": "X", "comment": None, "op": "set"}, "z_karta"),
    ({"keyword": "OBJECT", "value": "X", "op": "set"}, "z_karta"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "del"}, "z_karta"),
    ({"keyword": "OBJECT", "value": 5, "comment": None, "op": "set"}, "z_karta"),
    ({"keyword": "HIERARCH X", "value": "X", "comment": None, "op": "add"}, "z_karta"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "add"}, "xisf_bez"),
    ({"keyword": "TELESCOP", "value": "X", "comment": None, "op": "set"}, "xisf"),
    ({"keyword": "OBJECT", "value": "X", "comment": "k", "op": "set"}, "xisf"),
], ids=["add_przy_karcie", "set_bez_karty", "oba_ksztalty", "brak_comment", "nieznana_op",
        "value_nie_tekst", "nazwa_HIERARCH", "xisf_add", "xisf_inna_karta", "xisf_komentarz"])
def test_przed_odmawia_pozycji_spoza_kontraktu_zanim_powstanie_kopia(tmp_path, pozycja, plik):
    sciezki = {"z_karta": lambda: _fits(tmp_path / "a.fits"),
               "bez_filter": lambda: _fits_bez(tmp_path / "a.fits", "FILTER"),
               "xisf": lambda: _xisf(tmp_path / "s.xisf"),
               "xisf_bez": lambda: _xisf_bez_object(tmp_path / "s.xisf")}
    p = sciezki[plik]()
    with pytest.raises(SystemExit) as odmowa:
        _plan(tmp_path, [{"plik": str(p), **pozycja}])
    assert "odmowa: pozycja 0" in str(odmowa.value)
    assert not (tmp_path / "kopie").exists()


def _xisf_bez_object(path):
    p = _xisf(path)
    _zamien(p, b'<FITSKeyword name="OBJECT"', b'<FITSKeyword name="OBJEKT"')
    return p


# ============================================================ bramka planu = bramka pisarza (własny kod)


def _fits_z_suma(path):
    """FITS bez OBJECT, z wolnym rekordem za END i POPRAWNYMI sumami CHECKSUM/DATASUM."""
    hdu = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8))
    hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(path, checksum=True)
    with fits.open(path, checksum=True) as hdul:
        assert "CHECKSUM" in hdul[0].header and hdul[0].verify_checksum() == 1
    return path


def _fits_z_kartami(path, karty):
    hdu = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8))
    for kw, wartosc in karty:
        hdu.header.append((kw, wartosc))
    hdu.writeto(path)
    return path


@pytest.mark.parametrize("buduj, pozycja, fragment", [
    (_fits_z_suma, {"keyword": "OBJECT", "value": "NGC 6992", "comment": None, "op": "add"},
     "suma kontrolna (CHECKSUM, DATASUM)"),
    (lambda p: _fits_z_kartami(p, [("EXPTIME", 60)]),
     {"keyword": "EXPTIME", "value": "60", "comment": None, "op": "set"}, "nie jest tekstem"),
    (lambda p: _fits_z_kartami(p, [("IMAGETYP", "Light")]),
     {"keyword": "EXTEND", "value": "F", "comment": None, "op": "set"}, "ukladu danych"),
    (lambda p: _fits_z_kartami(p, [("IMAGETYP", "Light")]),
     {"keyword": "NAXIS1", "value": "9", "comment": None, "op": "set"}, "ukladu danych"),
    (lambda p: _fits_z_kartami(p, [("IMAGETYP", "Light")]),
     {"keyword": "HISTORY", "value": "x", "comment": None, "op": "add"}, "specjalna"),
    (lambda p: _fits_z_kartami(p, [("FILTER", "Ha"), ("FILTER", "OIII")]),
     {"keyword": "FILTER", "value": "SII", "comment": None, "op": "set"}, "wystepuje 2 razy"),
    (_fits, {"keyword": "OBJECT", "value": "X", "comment": None, "coment": "k", "op": "set"},
     "obce klucze 'coment'"),
    (_fits, {"object": "X", "poo": "Y"}, "obce klucze 'poo'"),
    (_fits, {"keyword": "OBJECT", "value": "X", "comment": None, "op": "set", "po": 5},
     "'po' nie jest"),
], ids=["checksum", "set_EXPTIME_liczbowe", "set_EXTEND", "set_NAXIS1", "add_HISTORY",
        "set_dwa_FILTER", "obcy_klucz_coment", "obcy_klucz_poo", "po_nie_tekst"])
def test_przed_odmawia_tego_czego_pisarz_w_miejscu_nie_zapisze(tmp_path, buduj, pozycja,
                                                                fragment):
    """Kontrola nie może mówić TAK o zmianie, której pisarz w miejscu ma obowiązek odmówić: suma
    kontrolna, karta specjalna albo układu danych, `set` na karcie powtórzonej albo nietekstowej.
    Schemat pozycji zamknięty: obcy klucz to odmowa z jego nazwą."""
    p = buduj(tmp_path / "a.fits")
    with pytest.raises(SystemExit) as odmowa:
        _plan(tmp_path, [{"plik": str(p), **pozycja}])
    assert "odmowa: pozycja 0" in str(odmowa.value) and fragment in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_pisarz_odmawia_tego_samego_co_bramka_planu(tmp_path):
    """Bramka planu nie jest ostrzejsza na ślepo: pisarz w miejscu na tych samych plikach odmawia
    (`blocked` sumy) albo spada na drogę atomową (`Fallback`)."""
    ops = {"suma": [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")],
           "dwa": [writeback.WriteOp("FILTER", "set", "SII", "str", idx=0)],
           "liczba": [writeback.WriteOp("EXPTIME", "set", "60", "str", idx=0)]}
    pliki = {"suma": _fits_z_suma(tmp_path / "s.fits"),
             "dwa": _fits_z_kartami(tmp_path / "d.fits", [("FILTER", "Ha"), ("FILTER", "OIII")]),
             "liczba": _fits_z_kartami(tmp_path / "l.fits", [("EXPTIME", 60)])}
    wynik = writeback.write_changes_inplace(str(pliki["suma"]), ops["suma"], None)
    assert wynik.status == "blocked" and wynik.reason.code == "checksum_present", wynik
    for nazwa in ("dwa", "liczba"):
        assert isinstance(writeback.write_changes_inplace(str(pliki[nazwa]), ops[nazwa], None),
                          writeback.Fallback), nazwa


@pytest.mark.parametrize("plan, fragment", [
    ("{to nie json", "plan nieczytelny"),
    ({"plik": "x"}, "nie jest niepusta lista"),
    ([], "nie jest niepusta lista"),
    (["plik"], "nie jest obiektem JSON"),
    ([{"keyword": "OBJECT", "value": "X", "comment": None, "op": "set"}], "'plik'"),
    ([{"plik": ["a"], "object": "X"}], "'plik'"),
], ids=["json_zly", "korzen_obiekt", "lista_pusta", "wpis_nie_obiekt", "brak_plik", "plik_lista"])
def test_przed_schemat_planu_zamkniety_bez_surowego_wyjatku(tmp_path, plan, fragment):
    sciezka = tmp_path / "plan.json"
    sciezka.write_text(plan if isinstance(plan, str) else json.dumps(plan), encoding="utf-8")
    with pytest.raises(SystemExit) as odmowa:
        K.przed(str(tmp_path / "kopie"), str(sciezka))
    assert str(odmowa.value).startswith("odmowa: ") and fragment in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_przed_odmawia_pliku_bez_tozsamosci_st_ino_zero(tmp_path, monkeypatch):
    """Zapis atomowy kontrola rozpoznaje po zmianie `st_ino` - udział, który podaje zero, nie da
    się sprawdzić, więc `przed` odmawia, zanim powstanie kopia."""
    p = _fits(tmp_path / "a.fits")
    prawdziwy = os.stat

    def bez_ino(sciezka, *a, **kw):
        st = prawdziwy(sciezka, *a, **kw)
        if os.path.normcase(os.fspath(sciezka)) != os.path.normcase(str(p)):
            return st
        return os.stat_result((st.st_mode, 0, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                               st.st_size, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
    monkeypatch.setattr(K.os, "stat", bez_ino)
    with pytest.raises(SystemExit) as odmowa:
        _przed(tmp_path, p, "NGC 6992")
    assert "st_ino == 0" in str(odmowa.value)
    monkeypatch.undo()
    assert not (tmp_path / "kopie").exists()


def _dwa_pliki(tmp_path, zapis):
    """Dwa pliki planu; `zapis` - po poprawnym zapisie (`po` = 0), bez niego - stan sprzed
    (`po-undo` = 0). Psucie manifestu ma potem dać NIE tam, gdzie bez niego jest TAK."""
    a, b = _fits(tmp_path / "a.fits"), _fits(tmp_path / "b.fits")
    kopie = _plan(tmp_path, [{"plik": str(a), "object": "NGC 6992"},
                             {"plik": str(b), "object": "NGC 6992"}])
    if zapis:
        _zapisz(a, "NGC 6992")
        _zapisz(b, "NGC 6992")
        assert K.po(str(kopie)) == 0
    else:
        assert K.po_undo(str(kopie)) == 0
    return kopie


def _manifest_zmien(kopie, zmiana):
    sciezka = kopie / "manifest.json"
    sciezka.write_text(json.dumps(zmiana(json.loads(sciezka.read_text(encoding="utf-8")))),
                       encoding="utf-8")


def _kopia_obca(kopie):
    (kopie / "0002.fits").write_bytes((kopie / "0000.fits").read_bytes())


def _numeracja(m):
    m[1]["kopia"] = m[1]["kopia"].replace("0001.", "0007.")
    return m


@pytest.mark.parametrize("psuj, fragment", [
    (lambda k: _manifest_zmien(k, lambda m: []), "manifest pusty"),
    (lambda k: _manifest_zmien(k, lambda m: {"x": m}), "manifest pusty"),
    (lambda k: _manifest_zmien(k, lambda m: m[:1]), "inne niz pozycje manifestu"),
    (lambda k: _manifest_zmien(k, lambda m: m[1:]), "poza numeracja"),
    (_kopia_obca, "inne niz pozycje manifestu"),
    (lambda k: _manifest_zmien(k, _numeracja), "poza numeracja"),
    (lambda k: _manifest_zmien(k, lambda m: [{**w, "obcy": 1} for w in m]), "obce klucze"),
    (lambda k: _manifest_zmien(k, lambda m: [{x: v for x, v in w.items() if x != "sha1"}
                                             for w in m]), "brak kluczy"),
    (lambda k: (k / "manifest.json").unlink(), "manifest nieczytelny"),
], ids=["pusty", "nie_lista", "usunieta_pozycja", "pierwsza_usunieta", "osierocona_kopia",
        "dziura_w_numeracji", "obcy_klucz", "brak_klucza", "brak_pliku"])
@pytest.mark.parametrize("tryb", ["po", "po_undo"])
def test_po_i_po_undo_odmawiaja_pustego_albo_niepelnego_manifestu(tmp_path, psuj, fragment, tryb):
    """Manifest pusty, odchudzony albo rozjechany z kopiami to NIE (kod 1) w `po` i `po-undo` -
    pusta pętla nie może dać TAK bez przeczytania pliku."""
    kopie = _dwa_pliki(tmp_path, zapis=tryb == "po")
    psuj(kopie)
    if tryb == "po":
        assert K.po(str(kopie)) == 1
        assert fragment in _raport(kopie)["problemy"][0], _raport(kopie)
    else:
        assert K.po_undo(str(kopie)) == 1
