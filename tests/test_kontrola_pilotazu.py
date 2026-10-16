"""Testy NIEZALEŻNEJ kontroli pilotażu zapisu w miejscu (`scripts/kontrola_pilotazu.py`).

Pliki FITS/XISF SYNTETYCZNE w `tmp_path`. Zapis poprawny robi PRAWDZIWY pisarz
(`writeback.write_changes_inplace`) - kontrola nie może odrzucić tego, co pisarz zapisuje zgodnie
z planem (FITS; XISF z wydłużeniem i ze skróceniem XML-a, z własnością obiektu i bez, z zerowym
i niezerowym wypełnieniem). Zapisy niedozwolone to bajty zmienione W MIEJSCU po poprawnym zapisie
(ten sam `st_ino` i rozmiar), więc kontrola musi je złapać porównaniem treści, nie metadanych.

Od AR-165 `przed` mierzy blokadę w katalogu testowym (podproces, ok. 0,15 s) - testy dostają pomiar
PRAWDZIWY, ale zrobiony raz na moduł (fikstura `_blokada_raz`); drogę `przed` → `blokada` bez
podstawki sprawdzają testy bloku AR-165. `po`/`po-undo` dostają plik planu (kotwica pozycji)."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import struct
import sys
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
_BLOKADA = K.blokada                                        # prawdziwy pomiar, przed podstawką


@pytest.fixture(scope="module")
def _pomiar_blokady(tmp_path_factory):
    """Pomiar `blokada` raz na moduł - na tym samym woluminie co katalogi `tmp_path` testów."""
    return _BLOKADA(str(tmp_path_factory.mktemp("blokada")))


_WOLUMIN_KATALOGU = K._wolumin_katalogu


@pytest.fixture(autouse=True)
def _blokada_raz(monkeypatch, _pomiar_blokady):
    """`przed` woła `blokada` przy każdym biegu; testy dostają wynik pomiaru z modułu (świeża kopia
    dict - `przed` go rozbiera). Test, który chce drogi prawdziwej, przywraca `_BLOKADA`.

    Kopie i pliki planu leżą w testach w jednym `tmp_path`, czyli na JEDNYM woluminie, a tego
    `przed` odmawia (kopie mają leżeć poza udziałem z oryginałami) - wolumin katalogu kopii testy
    dostają więc zerowy (żaden plik takiego nie ma); prawdziwą drogę sprawdza test odmowy."""
    monkeypatch.setattr(K, "blokada", lambda katalog: dict(_pomiar_blokady))
    monkeypatch.setattr(K, "_wolumin_katalogu", lambda katalog: 0)


def _kb(tmp_path):
    """Katalog testowy blokady - wyłącznie na pliki pomiaru (`przed` odmawia katalogu z cudzymi)."""
    katalog = tmp_path / "blokada"
    katalog.mkdir(exist_ok=True)
    return str(katalog)


def _po(kopie):
    """`po` z planem, który helpery piszą obok katalogu kopii (kotwica pozycji, AR-165)."""
    return K.po(str(kopie), str(kopie.parent / "plan.json"))


def _po_undo(kopie):
    return K.po_undo(str(kopie), str(kopie.parent / "plan.json"))


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
    K.przed(str(kopie), str(plan), _kb(tmp_path))
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
    assert _po(kopie) == 0, _raport(kopie)


def test_fits_brak_wykonania_zmiany_to_NIE(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    assert _po(kopie) == 1
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
    assert _po(kopie) == 0
    psuj(p)
    assert _po(kopie) == 1, _raport(kopie)


def test_fits_obca_zmiana_przez_astropy_to_NIE(tmp_path):
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    with fits.open(str(p), mode="update") as hdul:
        hdul[0].header["IMAGETYP"] = "Dark"
    assert _po(kopie) == 1


def test_fits_podmiana_pliku_zamiast_zapisu_w_miejscu_to_NIE(tmp_path):
    """Treść poprawna, ale plik PODMIENIONY (inny `st_ino`) - to nie jest zapis w miejscu."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    tmp = tmp_path / "a.tmp"
    tmp.write_bytes(p.read_bytes())
    os.replace(tmp, p)
    assert _po(kopie) == 1
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
    assert _po(kopie) == 0, _raport(kopie)


def test_xisf_brak_wykonania_zmiany_to_NIE(tmp_path):
    p = _xisf(tmp_path / "s.xisf", props=WLASNOSC_ATR.format("NGC6992"))
    kopie = _przed(tmp_path, p, "NGC 6992")
    assert _po(kopie) == 1


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
    assert _po(kopie) == 0
    psuj(p)
    assert _po(kopie) == 1, _raport(kopie)


def test_xisf_skrocenie_bez_zer_na_poczatku_wypelnienia_to_NIE(tmp_path):
    """Skrócenie XML-a MA dołożyć zera przed wypełnieniem kopii - bajt kopii w ich miejscu to NIE."""
    p = _xisf(tmp_path / "s.xisf", obj="'Veil Nebula East'", wypelnienie=b"\x05")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    (dlugosc,) = struct.unpack("<I", p.read_bytes()[8:12])
    assert p.read_bytes()[16 + dlugosc] == 0
    _w_miejscu(p, 16 + dlugosc, b"\x05")
    assert _po(kopie) == 1


def test_xisf_komentarz_xml_wstawiony_w_miejsce_bialych_znakow_to_NIE(tmp_path):
    """Zmiana niewidoczna dla drzewa bez komentarzy: kontrola bajtowa XML-a ją łapie."""
    p = _xisf(tmp_path / "s.xisf", props="          ")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    _zamien(p, b"          ", b"<!--xx-->\n")
    assert _po(kopie) == 1


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
        K.przed(str(kopie), str(tmp_path / "plan.json"), _kb(tmp_path))
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
        K.przed(str(kopie), str(plan), _kb(tmp_path))
    assert (kopie / "0000.fits").read_bytes() == b"stara kopia"
    assert sorted(x.name for x in kopie.iterdir()) == ["0000.fits"]


def test_po_undo_wymaga_bajtow_sprzed(tmp_path):
    p = _xisf(tmp_path / "s.xisf", props=WLASNOSC_ATR.format("NGC6992"))
    kopie = _przed(tmp_path, p, "NGC 6992")
    przed = p.read_bytes()
    _zapisz(p, "NGC 6992")
    assert _po_undo(kopie) == 1
    _w_miejscu(p, 0, przed)                                # cofnięcie w miejscu
    assert _po_undo(kopie) == 0
    with open(p, "ab") as fh:
        fh.write(b"\x00")
    assert _po_undo(kopie) == 1


# ============================================================ para ścieżek (zmiana obiektu, AR-17 krok 3)


def _przed_para(tmp_path, plik, po, forma):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(plik), "po": str(po), "object": forma}]),
                    encoding="utf-8")
    kopie = tmp_path / "kopie"
    K.przed(str(kopie), str(plan), _kb(tmp_path))
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
    assert _po(kopie) == 0, _raport(kopie)
    assert _raport(kopie)["plik"] == str(po)
    assert _po_undo(kopie) == 1                        # plik nadal pod nową ścieżką
    _w_miejscu(po, 0, przed)
    os.rename(po, p)
    assert _po_undo(kopie) == 0
    po.write_bytes(p.read_bytes())                            # kopia pod nową ścieżką została
    assert _po_undo(kopie) == 1


def test_para_bez_karty_raw_caly_plik_jak_kopia(tmp_path):
    """`"object": null` (RAW - format bez karty): po przeniesieniu CAŁY plik bajt w bajt jak kopia,
    jeden zmieniony bajt to NIE; RAW nie otwiera się czytnikiem FITS i nie musi."""
    from test_exif import build_raw
    p = tmp_path / "c.dng"
    p.write_bytes(build_raw())
    po = tmp_path / "IC405_c.dng"
    kopie = _przed_para(tmp_path, p, po, None)
    os.rename(p, po)
    assert _po(kopie) == 0, _raport(kopie)
    _w_miejscu(po, len(po.read_bytes()) - 1, b"\x7f")
    assert _po(kopie) == 1
    assert any("bajty pliku rozne od kopii" in x for x in _raport(kopie)["problemy"])


def test_para_kopia_zamiast_przeniesienia_to_NIE(tmp_path):
    """Plik SKOPIOWANY pod nową ścieżkę (inny `st_ino`) i zostawiony pod starą - dwa „NIE”."""
    p = _fits(tmp_path / "a.fits")
    po = tmp_path / "b.fits"
    kopie = _przed_para(tmp_path, p, po, "NGC 6992")
    po.write_bytes(p.read_bytes())
    _zapisz(po, "NGC 6992")
    assert _po(kopie) == 1
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
            K.przed(str(tmp_path / "kopie"), str(plan), _kb(tmp_path))
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
    K.przed(str(kopie), str(plan), _kb(tmp_path))
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
    assert _po(kopie) == 0, _raport(kopie)
    w = json.loads((kopie / "manifest.json").read_text(encoding="utf-8"))["pozycje"][0]
    assert {k: w[k] for k in ("keyword", "value", "comment", "op")} == {
        "keyword": kw, "value": wartosc, "comment": None, "op": "add"}


def test_fits_add_z_komentarzem_planu_przechodzi(tmp_path):
    p = _fits_bez(tmp_path / "a.fits", "OBJECT")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992", "nazwa obiektu")
    _dopisz(p, "OBJECT", "NGC 6992", "nazwa obiektu")
    assert _po(kopie) == 0, _raport(kopie)


def test_fits_add_brak_wykonania_to_NIE(tmp_path):
    p = _fits_bez(tmp_path / "a.fits", "OBJECT")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    assert _po(kopie) == 1
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
    assert _po(kopie) == 0, _raport(kopie)
    psuj(p, kopie / "0000.fits")
    assert _po(kopie) == 1, _raport(kopie)
    assert any(oczekiwany in x for x in _raport(kopie)["problemy"]), _raport(kopie)


def test_fits_add_przepisany_atomowo_to_NIE(tmp_path):
    """Pisarz bez zapisu w miejscu (droga atomowa: cały plik przepisany, nowy `st_ino`) - pilotaż
    `add` sprawdza drogę w miejscu, więc kontrola mówi NIE, choć karta jest."""
    p = _fits_bez(tmp_path / "a.fits", "OBJECT")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    wynik = writeback.write_changes(str(p), [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")],
                                    None)
    assert wynik.status == "applied" and not wynik.in_place, wynik
    assert _po(kopie) == 1
    assert any("przepisany w calosci, nie w miejscu" in x for x in _raport(kopie)["problemy"])


def test_fits_add_bez_zapasu_odmowa_przed_jak_pisarz(tmp_path):
    """Plik bez pustej karty na końcu i bez wolnego rekordu za `END` - model dopisania (ten sam,
    którym `po` liczy plik oczekiwany) mówi, że w miejscu się nie da, więc `przed` odmawia, zanim
    powstanie kopia (AR-165); pisarz na tym pliku spada na drogę atomową (`Fallback`)."""
    p = tmp_path / "pelny.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    while (len(hdu.header) + 1) % 36:                 # karty + END = pełny blok 2880 B
        hdu.header[f"K{len(hdu.header):03d}"] = "v"
    hdu.writeto(p)
    assert len(p.read_bytes()) == 2880 + 2880 and _rekordy(p.read_bytes())[1] == 35
    with pytest.raises(SystemExit) as odmowa:
        _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    assert "dopisanie w miejscu niemozliwe" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()
    assert isinstance(writeback.write_changes_inplace(
        str(p), [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")], None), writeback.Fallback)


def test_po_undo_po_dopisaniu_cofnietym_w_miejscu(tmp_path):
    """Cofnięcie W MIEJSCU prawdziwym pisarzem (`restore_inplace` z backupu regionu) → `po-undo`
    OK (sha1 całego pliku, rozmiar, `st_ino` sprzed); przed cofnięciem NIE."""
    p = _fits_bez(tmp_path / "a.fits", "FILTER", "komentarze")
    kopie = _przed_add(tmp_path, p, "FILTER", "Ha")
    wynik = _dopisz(p, "FILTER", "Ha")
    assert _po_undo(kopie) == 1
    backup = writeback.RegionBackup.decode(wynik.backup_text)
    st = os.stat(p)
    with open(p, "rb") as fh:
        fh.seek(backup.offset)
        region = fh.read(len(backup.region))
    cofniecie = writeback.restore_inplace(str(p), backup, op_new_region=region,
                                          op_file_size=st.st_size, op_file_ino=st.st_ino,
                                          op_post_hash=wynik.post_hash)
    assert cofniecie.status == "applied" and cofniecie.in_place, cofniecie
    assert _po_undo(kopie) == 0


def test_fits_set_innej_karty_z_komentarzem_planu(tmp_path):
    """`set` karty spoza OBJECT (populacja `header-fix` z `FILTER`): komentarz z planu wchodzi do
    karty, komentarz null zostawia zastany; zastany przy planie z komentarzem to NIE."""
    p = _fits(tmp_path / "a.fits")
    kopie = _plan(tmp_path, [{"plik": str(p), "keyword": "FILTER", "value": "OIII",
                              "comment": "filtr waski", "op": "set"}])
    ops = [writeback.WriteOp("FILTER", "set", "OIII", "str", idx=0, comment="filtr waski")]
    assert writeback.write_changes_inplace(str(p), ops, None).status == "applied"
    assert _po(kopie) == 0, _raport(kopie)
    i = p.read_bytes().index(b"FILTER  = ")
    _w_miejscu(p, i, _karta_obraz("FILTER", "OIII", "filtr"))
    assert _po(kopie) == 1
    assert any("komentarz FILTER[0]" in x for x in _raport(kopie)["problemy"])


def _bez_ksztaltu_ze_skrotem(m):
    for w in m["pozycje"]:
        for k in ("keyword", "value", "comment", "op"):
            del w[k]
        w["object"] = "NGC 6992"
    return m


@pytest.mark.parametrize("zmiana, fragment", [
    (lambda m: m["pozycje"], "schemacie sprzed AR-165"),
    (_bez_ksztaltu_ze_skrotem, "obce klucze ['object']"),
    (lambda m: {**m, "schemat": 3}, "schemacie 3"),
    (lambda m: {**m, "obcy": 1}, "obce klucze ['obcy']"),
    (lambda m: {**m, "pozycje": [{k: v for k, v in w.items() if k != "tozsamosc"}
                                 for w in m["pozycje"]]}, "brak kluczy ['tozsamosc']"),
    (lambda m: {**m, "pozycje": [{**w, "granice": None} for w in m["pozycje"]]},
     "typ pola spoza schematu"),
    (lambda m: {**m, "pozycje": [{**w, "tozsamosc": {**w["tozsamosc"], "indeks": 0}}
                                 for w in m["pozycje"]]}, "typ pola spoza schematu"),
    (lambda m: {**m, "blokada": {**m["blokada"], "wyniki": {**m["blokada"]["wyniki"], "kod": 0}}},
     "wyniki nie sa tekstem"),
    (lambda m: {**m, "blokada": {**m["blokada"], "kod": 1}}, "kod zapisany 1, z wynikow 0"),
    (lambda m: {**m, "blokada": {**m["blokada"], "wyniki": {**m["blokada"]["wyniki"],
                                                             "usuniecie": "NIE odrzucone"}}},
     "kod zapisany 0, z wynikow 1"),
    (lambda m: {**m, "pozycje": [{**w, "karty": {"OBJECT[0]": "NGC6992"}} for w in m["pozycje"]]},
     "typ pola spoza schematu"),
    (lambda m: {**m, "plan": {**m["plan"], "sha1": 5}}, "pole nie jest tekstem"),
    (lambda m: {**m, "srodowisko": {"python": "3.13"}}, "brak kluczy ['komputer']"),
], ids=["lista_sprzed_AR165", "skrot_object_we_wpisie", "inny_schemat", "obcy_klucz_glowny",
        "brak_tozsamosci", "granice_null", "indeks_zero", "liczba_w_wynikach_blokady",
        "blokada_kod_1", "kod_0_przy_wyniku_NIE", "karty_nie_para", "sha1_planu_liczba",
        "srodowisko_niepelne"])
def test_manifest_spoza_schematu_2_to_NIE_z_powodem(tmp_path, zmiana, fragment):
    """Schemat manifestu ZAMKNIĘTY (AR-165): manifest sprzed AR-165 (lista wpisów - także ze skrótem
    `object`, który zna już wyłącznie PLAN), obcy albo brakujący klucz i typ spoza schematu to NIE
    z powodem - nie zgadywanie i nie wyjątek w środku `po` (`granice` null dawały `TypeError`).
    `wyniki` blokady niosą wyłącznie tekst - `kod` i `wolumin` stoją piętro wyżej."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    assert _po(kopie) == 0, _raport(kopie)
    _manifest_zmien(kopie, zmiana)
    assert _po(kopie) == 1
    assert fragment in _raport(kopie)["problemy"][0], _raport(kopie)
    assert _po_undo(kopie) == 1


@pytest.mark.parametrize("pozycja, plik", [
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "add"}, "z_karta"),
    ({"keyword": "FILTER", "value": "Ha", "comment": None, "op": "set"}, "bez_filter"),
    ({"object": "X", "keyword": "OBJECT", "value": "X", "comment": None, "op": "set"}, "z_karta"),
    ({"keyword": "OBJECT", "value": "X", "op": "set"}, "z_karta"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "del"}, "z_karta"),
    ({"keyword": "OBJECT", "value": 5, "comment": None, "op": "set"}, "z_karta"),
    ({"keyword": "HIERARCH X", "value": "X", "comment": None, "op": "add"}, "z_karta"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "add"}, "xisf_bez_z_wlasnoscia"),
    ({"keyword": "TELESCOP", "value": "X", "comment": None, "op": "set"}, "xisf"),
    ({"keyword": "OBJECT", "value": "X", "comment": "k", "op": "set"}, "xisf"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "add"}, "xisf_dwa_obrazy"),
    ({"keyword": "HISTORY", "value": "X", "comment": None, "op": "add"}, "xisf_bez"),
    ({"keyword": "NAXIS1", "value": "4", "comment": None, "op": "add"}, "xisf_bez"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "set"}, "xisf_bez_attachmentu"),
    ({"keyword": "OBJECT", "value": "X", "comment": None, "op": "add"}, "xisf_bez_wzorca"),
], ids=["add_przy_karcie", "set_bez_karty", "oba_ksztalty", "brak_comment", "nieznana_op",
        "value_nie_tekst", "nazwa_HIERARCH", "xisf_add_przy_wlasnosci", "xisf_inna_karta",
        "xisf_komentarz", "xisf_add_dwa_obrazy", "xisf_add_HISTORY", "xisf_add_NAXIS1",
        "xisf_bez_attachmentu", "xisf_add_bez_wzorca"])
def test_przed_odmawia_pozycji_spoza_kontraktu_zanim_powstanie_kopia(tmp_path, pozycja, plik):
    """Także bramka XISF (AR-165): `add` przy własności obiektu bez karty, karty pod dwoma `<Image>`,
    brak bloku attachment (dawniej `TypeError` w `po`), brak wzorca karty tekstowej; karty
    specjalne i układu danych w XISF `add` - świadomie węższa od pisarza (kontrola ich nie modeluje)."""
    sciezki = {"z_karta": lambda: _fits(tmp_path / "a.fits"),
               "bez_filter": lambda: _fits_bez(tmp_path / "a.fits", "FILTER"),
               "xisf": lambda: _xisf(tmp_path / "s.xisf"),
               "xisf_bez": lambda: _xisf_bez_object(tmp_path / "s.xisf"),
               "xisf_bez_z_wlasnoscia": lambda: _xisf_bez_object(
                   tmp_path / "s.xisf", props=WLASNOSC_ATR.format("NGC6992")),
               "xisf_dwa_obrazy": lambda: _xisf_dwa_obrazy(tmp_path / "s.xisf"),
               "xisf_bez_attachmentu": lambda: _xisf_bez_attachmentu(tmp_path / "s.xisf"),
               "xisf_bez_wzorca": lambda: _xisf_uklad(tmp_path / "s.xisf", "bez_wzorca")}
    p = sciezki[plik]()
    with pytest.raises(SystemExit) as odmowa:
        _plan(tmp_path, [{"plik": str(p), **pozycja}])
    assert "odmowa: pozycja 0" in str(odmowa.value)
    assert not (tmp_path / "kopie").exists()


def _xisf_bez_object(path, **kw):
    p = _xisf(path, **kw)
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
        K.przed(str(tmp_path / "kopie"), str(sciezka), _kb(tmp_path))
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
        assert _po(kopie) == 0
    else:
        assert _po_undo(kopie) == 0
    return kopie


def _manifest_zmien(kopie, zmiana):
    sciezka = kopie / "manifest.json"
    sciezka.write_text(json.dumps(zmiana(json.loads(sciezka.read_text(encoding="utf-8")))),
                       encoding="utf-8")


def _kopia_obca(kopie):
    (kopie / "0002.fits").write_bytes((kopie / "0000.fits").read_bytes())


def _numeracja(m):
    m["pozycje"][1]["kopia"] = m["pozycje"][1]["kopia"].replace("0001.", "0007.")
    return m


def _wpisy(zmiana):
    """Zmiana listy wpisów manifestu (schemat 2: wpisy pod `pozycje`)."""
    return lambda m: {**m, "pozycje": zmiana(m["pozycje"])}


def _wpis_i_kopia_usuniete(kopie):
    """Manifest spójny SAM ZE SOBĄ: ostatni wpis i jego kopia usunięte - bez kotwicy poza manifestem
    `po` sprawdziłby jeden plik zamiast dwóch i powiedział TAK."""
    _manifest_zmien(kopie, _wpisy(lambda w: w[:1]))
    (kopie / "0001.fits").unlink()


def _plan_zmieniony(kopie):
    plan = kopie.parent / "plan.json"
    plan.write_text(json.dumps(json.loads(plan.read_text(encoding="utf-8"))[:1]), encoding="utf-8")


def _inny_plik_we_wpisie(m):
    m["pozycje"][1]["plik"] = m["pozycje"][0]["plik"]
    return m


@pytest.mark.parametrize("psuj, fragment", [
    (lambda k: _manifest_zmien(k, _wpisy(lambda w: [])), "manifest bez pozycji"),
    (lambda k: _manifest_zmien(k, lambda m: {"x": m}), "brak kluczy"),
    (lambda k: _manifest_zmien(k, _wpisy(lambda w: w[:1])), "pozycji, manifest 1"),
    (lambda k: _manifest_zmien(k, _wpisy(lambda w: w[1:])), "pozycji, manifest 1"),
    (_kopia_obca, "inne niz pozycje manifestu"),
    (lambda k: _manifest_zmien(k, _numeracja), "poza numeracja"),
    (lambda k: _manifest_zmien(k, _wpisy(lambda w: [{**x, "obcy": 1} for x in w])), "obce klucze"),
    (lambda k: _manifest_zmien(k, _wpisy(lambda w: [{x: v for x, v in e.items() if x != "sha1"}
                                                    for e in w])), "brak kluczy"),
    (lambda k: (k / "manifest.json").unlink(), "manifest nieczytelny"),
    (_wpis_i_kopia_usuniete, "pozycji, manifest 1"),
    (_plan_zmieniony, "plan inny niz przy przed"),
    (lambda k: (k.parent / "plan.json").unlink(), "plan nieczytelny"),
    (lambda k: _manifest_zmien(k, _inny_plik_we_wpisie), "inny niz pozycja 1 planu"),
], ids=["pusty", "nie_schemat", "usunieta_pozycja", "pierwsza_usunieta", "osierocona_kopia",
        "dziura_w_numeracji", "obcy_klucz", "brak_klucza", "brak_pliku", "wpis_i_kopia_usuniete",
        "plan_zmieniony", "brak_planu", "inny_plik_we_wpisie"])
@pytest.mark.parametrize("tryb", ["po", "po_undo"])
def test_po_i_po_undo_odmawiaja_pustego_albo_niepelnego_manifestu(tmp_path, psuj, fragment, tryb):
    """Manifest pusty, odchudzony albo rozjechany z kopiami albo z PLANEM to NIE (kod 1) w `po`
    i `po-undo` - pusta pętla nie może dać TAK bez przeczytania pliku. Kotwica liczby pozycji leży
    poza manifestem (AR-165): plik planu, z sha1 zapisanym przy `przed` - wpis usunięty razem
    z kopią, plan podmieniony albo inny plik we wpisie to NIE."""
    kopie = _dwa_pliki(tmp_path, zapis=tryb == "po")
    psuj(kopie)
    if tryb == "po":
        assert _po(kopie) == 1
        assert fragment in _raport(kopie)["problemy"][0], _raport(kopie)
    else:
        assert _po_undo(kopie) == 1


# ============================================================ dopisanie karty XISF w miejscu (AR-165)
# Zapis poprawny robi PRAWDZIWY pisarz (`write_changes_inplace` z `add`); model wstawki w kontroli
# jest własny, więc zgodność bajtowa w każdym układzie kart dowodzi, że obie strony rozumieją regułę
# tak samo. Zmierzone 2026-10-16 na 659 plikach XISF archiwum: wyłącznie układ zwarty (bez białych
# znaków między kartami), ostatnia karta tekstowa w 235, liczbowa w 424; wcięcia i formy
# z zamknięciem nie ma, ale pisarz ma na nie osobne gałęzie, więc model też.

UKLADY_XISF = ("zwarty", "ostatnia_liczbowa", "ostatnia_inna_forma", "wciecia_crlf",
               "z_zamknieciem")
_INNE_KARTY = {   # układy z kartami spoza wspólnego wzoru
    "ostatnia_inna_forma": ('<FITSKeyword name="IMAGETYP" value="\'Light\'" comment="typ klatki"/>'
                            '<FITSKeyword value="300.0" name="EXPTIME"/>'),
    "wzorzec_bez_comment": ('<FITSKeyword name="IMAGETYP" value="\'Light\'"/>'
                            '<FITSKeyword name="TELESCOP" value="\'A140R\'"/>'),
    "wzorzec_obcy_atrybut": '<FITSKeyword name="IMAGETYP" value="\'Light\'" comment="typ" unit="x"/>',
    "master_flat": '<FITSKeyword name="IMAGETYP" value="\'Master Flat\'" comment="typ klatki"/>',
}


def _xisf_uklad(path, uklad, *, pad=256, payload=b"\x07" * 32, props="", wypelnienie=None):
    """Monolityczny XISF BEZ karty OBJECT. `zwarty` - karty bez białych znaków, ostatnia tekstowa
    (wzorzec = ostatnia); `ostatnia_liczbowa` - zwarty, ostatnia karta liczbowa, więc wzorzec stoi
    WCZEŚNIEJ, a wstawka i tak za ostatnią; `ostatnia_inna_forma` - ostatnia karta liczbowa w innej
    formie niż wzorzec (kolejność atrybutów, bez `comment`) - styl nowej karty bierze się z wzorca,
    nie z ostatniej; `wciecia_crlf` - każda karta w nowym wierszu `\\r\\n` + 4 spacje;
    `z_zamknieciem` - karty `<FITSKeyword …></FITSKeyword>` z wcięciem `\\n  `; `bez_wzorca` - same
    karty liczbowe; `wzorzec_bez_comment`, `wzorzec_obcy_atrybut` - wzorzec, z którego pisarz nie
    złoży karty z komentarzem / nie skopiuje cudzego atrybutu. `wypelnienie` - bajty rezerwy
    (domyślnie zera; długość = `pad`)."""
    karty = [("IMAGETYP", "'Light'", "typ klatki"), ("TELESCOP", "'A140R'", "teleskop")]
    if uklad == "ostatnia_liczbowa":
        karty.append(("EXPTIME", "300.0", "czas"))
    elif uklad == "bez_wzorca":
        karty = [("EXPTIME", "300.0", "czas"), ("GAIN", "100", "wzmocnienie")]
    wciecie = {"wciecia_crlf": "\r\n    ", "z_zamknieciem": "\n  "}.get(uklad, "")
    koniec = "></FITSKeyword>" if uklad == "z_zamknieciem" else "/>"
    tresc = _INNE_KARTY.get(uklad) or (
        "".join(f'{wciecie}<FITSKeyword name="{n}" value="{v}" comment="{c}"{koniec}'
                for n, v, c in karty) + {"wciecia_crlf": "\r\n", "z_zamknieciem": "\n"}.get(uklad, ""))
    rezerwa = b"\x00" * pad if wypelnienie is None else wypelnienie
    assert len(rezerwa) == pad

    def body(start):
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">' + props
                + f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                  f'location="attachment:{start:08d}:{len(payload)}">{tresc}</Image></xisf>'
                ).encode("utf-8")
    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + rezerwa + payload)
    return path


def _xisf_dwa_obrazy(path, *, pad=256, payload=b"\x07" * 32):
    """XISF z kartami pod DWOMA `<Image>` - cel zapisu niejednoznaczny, pisarz odmawia."""
    karta = '<FITSKeyword name="IMAGETYP" value="\'Light\'" comment="typ"/>'

    def body(s1, s2):
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{s1:08d}:{len(payload)}">{karta}</Image>'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{s2:08d}:{len(payload)}">{karta}</Image></xisf>'
                ).encode("utf-8")
    start = scan.XISF_XML_OFFSET + len(body(0, 0)) + pad
    xml = body(start, start + len(payload))
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + b"\x00" * pad
                 + payload + payload)
    return path


def _xisf_bez_attachmentu(path):
    """XISF bez żadnego bloku `attachment:` - granica nagłówka nieznana."""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
           '<Image geometry="4:4:1" sampleFormat="UInt16" location="embedded">'
           '<FITSKeyword name="OBJECT" value="\'NGC6992\'" comment="k"/></Image></xisf>'
           ).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml)
    return path


def _xisf_bez_obrazu_attachmentu(path, *, pad=256, payload=b"\x07" * 32):
    """XISF z blokiem `attachment:` wyłącznie pod `<Property>` - obraz `embedded`, więc tożsamość
    klatki (blok pierwszego obrazu) nieobliczalna."""
    def body(start):
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                '<Image geometry="4:4:1" sampleFormat="UInt16" location="embedded">'
                '<FITSKeyword name="IMAGETYP" value="\'Light\'" comment="typ"/></Image>'
                f'<Property id="Dane" type="ByteArray" '
                f'location="attachment:{start:08d}:{len(payload)}"/></xisf>').encode("utf-8")
    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml + b"\x00" * pad
                 + payload)
    return path


def _xisf_uciety(path):
    """XISF ucięty w rezerwie nagłówka - wypełnienie niekompletne, plik przeczy sam sobie."""
    p = _xisf_uklad(path, "zwarty")
    dane = p.read_bytes()
    (dlugosc,) = struct.unpack("<I", dane[8:12])
    p.write_bytes(dane[:scan.XISF_XML_OFFSET + dlugosc + 10])
    return p


WARTOSC_TRUDNA = "M 42 & \"Trap\" <x> Barnard's"               # escape XML i apostrof FITS naraz


@pytest.mark.parametrize("uklad", UKLADY_XISF)
@pytest.mark.parametrize("kw, wartosc, komentarz", [("OBJECT", "NGC 6992", None),
                                                    ("FILTER", WARTOSC_TRUDNA, "filtr z planu")],
                         ids=["OBJECT_bez_komentarza", "FILTER_trudna_z_komentarzem"])
def test_xisf_add_dopisanie_pisarza_przechodzi_w_kazdym_ukladzie(tmp_path, uklad, kw, wartosc,
                                                                 komentarz):
    """Pisarz dopisuje kartę w miejscu - kontrola mówi TAK (zgodność bajtowa własnego modelu
    z pisarzem w każdym układzie); potem jeden bajt w bloku danych (POZA regionem nagłówka) - NIE."""
    p = _xisf_uklad(tmp_path / "s.xisf", uklad)
    dlugosc_przed = struct.unpack("<I", p.read_bytes()[8:12])[0]
    kopie = _przed_add(tmp_path, p, kw, wartosc, komentarz)
    _dopisz(p, kw, wartosc, komentarz)
    assert struct.unpack("<I", p.read_bytes()[8:12])[0] > dlugosc_przed     # fakt pisarza
    assert _po(kopie) == 0, _raport(kopie)
    _xisf_bajt_danych(p)
    assert _po(kopie) == 1
    assert any("bajty od first_attachment" in x for x in _raport(kopie)["problemy"]), _raport(kopie)


def test_xisf_add_wypelnienie_niejednolite_zjedzone_od_poczatku(tmp_path):
    """Pisarz kopiuje wypełnienie verbatim, a wydłużenie XML-a zjada jego POCZĄTEK - przy zerowym
    wypełnieniu początek i koniec wyglądają tak samo, dopiero niejednolite (1..255) odróżnia
    `pad[d:]` od `pad[:-d]`."""
    p = _xisf_uklad(tmp_path / "s.xisf", "zwarty", pad=255, wypelnienie=bytes(range(1, 256)))
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    _dopisz(p, "OBJECT", "NGC 6992")
    assert _po(kopie) == 0, _raport(kopie)


def test_xisf_add_rezerwa_rowna_wstawce_przechodzi(tmp_path):
    """Granica rezerwy: wstawka dokładnie równa wolnemu miejscu - pisarz dopisuje, kontrola TAK;
    o bajt mniej - obie strony odmawiają."""
    poz = {"keyword": "OBJECT", "value": "NGC 6992", "comment": None, "op": "add"}
    wzor = _xisf_uklad(tmp_path / "wzor.xisf", "zwarty")
    (dlugosc,) = struct.unpack("<I", wzor.read_bytes()[8:12])
    xml = wzor.read_bytes()[scan.XISF_XML_OFFSET:scan.XISF_XML_OFFSET + dlugosc]
    _, (s, e) = K._xisf_po_dopisaniu(xml, poz)
    p = _xisf_uklad(tmp_path / "s.xisf", "zwarty", pad=e - s)
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    _dopisz(p, "OBJECT", "NGC 6992")
    assert _po(kopie) == 0, _raport(kopie)
    ciasny = _xisf_uklad(tmp_path / "c.xisf", "zwarty", pad=e - s - 1)
    with pytest.raises(SystemExit) as odmowa:
        _plan(tmp_path, [{"plik": str(ciasny), **poz}], katalog="kopie_ciasny")
    assert "nie miesci sie w rezerwie" in str(odmowa.value), odmowa.value


@pytest.mark.parametrize("psuj, oczekiwany", [
    (_xisf_bajt_wypelnienia(pierwszy=False), "(oczekiwany: wypelnienie)"),
    (lambda p: _zamien(p, b"'NGC 6992'", b"'NGC 6993'"), "(oczekiwany: nowa karta OBJECT)"),
    (lambda p: _zamien(p, b'comment="nazwa obiektu"', b'comment="nazwa obiektX"'),
     "(oczekiwany: nowa karta OBJECT)"),
    (lambda p: _zamien(p, b'    <FITSKeyword name="OBJECT"', b'\t   <FITSKeyword name="OBJECT"'),
     "(oczekiwany: nowa karta OBJECT)"),
    (lambda p: _zamien(p, b"'Light'", b"'Dark!'"), "(oczekiwany: XML kopii przed nowa karta)"),
    (lambda p: _zamien(p, b"</Image></xisf>", b"</Image></xisZ>"),
     "(oczekiwany: XML kopii za nowa karta)"),
    (_xisf_pole_dlugosci, "(oczekiwany: pole dlugosci XML)"),
    (lambda p: _w_miejscu(p, 0, b"Y"), "(oczekiwany: sygnatura)"),
], ids=["wypelnienie_koniec", "wartosc_nowej", "komentarz_nowej", "wciecie_nowej", "inna_karta",
        "XML_za_wstawka", "pole_dlugosci", "sygnatura"])
def test_xisf_add_zmiana_ponad_plan_to_NIE(tmp_path, psuj, oczekiwany):
    """Po poprawnym zapisie bajty zmienione W MIEJSCU (ta sama długość, ta sama tożsamość) - region
    oczekiwany jest wyznaczony co do bajtu, a pierwszy rozjazd nazwany częścią regionu."""
    p = _xisf_uklad(tmp_path / "s.xisf", "wciecia_crlf")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992", "nazwa obiektu")
    _dopisz(p, "OBJECT", "NGC 6992", "nazwa obiektu")
    assert _po(kopie) == 0, _raport(kopie)
    psuj(p)
    assert _po(kopie) == 1
    assert any(oczekiwany in x for x in _raport(kopie)["problemy"]), _raport(kopie)


def _do_wnetrza(prawdziwy):
    """Zepsuty model: nowa karta wstawiona do WNĘTRZA ostatniej karty w formie z zamknięciem (AR-6)."""
    def model(xml, poz):
        nowy, (s, e) = prawdziwy(xml, poz)
        zamkniecie = xml.rindex(b"</FITSKeyword>")
        return xml[:zamkniecie] + nowy[s:e] + xml[zamkniecie:], (zamkniecie, zamkniecie + e - s)
    return model


def _inna_wartosc(prawdziwy):
    """Zepsuty model: karta na właściwym miejscu, ale z wartością spoza planu."""
    return lambda xml, poz: prawdziwy(xml, {**poz, "value": "NGC 6993"})


@pytest.mark.parametrize("zepsuj, oczekiwany", [
    (_do_wnetrza, "za ostatnia karta kopii nie stoi nowa karta"),
    (_inna_wartosc, "inna niz plan"),
], ids=["karta_we_wnetrzu_karty", "inna_wartosc"])
def test_xisf_add_warstwa_drzewa_lapie_to_czego_bajty_nie_widza(tmp_path, monkeypatch, zepsuj,
                                                                oczekiwany):
    """Druga droga (drzewo XML) nie jest martwa: gdy model bajtowy i pisarz pomylą się TAK SAMO,
    bajty pliku zgadzają się z modelem, a drzewo mówi NIE - o miejscu karty (nie rodzeństwo
    ostatniej) i o jej treści (wartość spoza planu)."""
    p = _xisf_uklad(tmp_path / "s.xisf", "z_zamknieciem")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    monkeypatch.setattr(K, "_xisf_po_dopisaniu", zepsuj(K._xisf_po_dopisaniu))
    fa = scan.read_xisf_meta_full(str(p)).first_attachment
    poz = {"keyword": "OBJECT", "value": "NGC 6992", "comment": None, "op": "add"}
    region, _ = K._xisf_region_po_dopisaniu((kopie / "0000.xisf").read_bytes()[:fa], poz)
    _w_miejscu(p, 0, region)
    assert _po(kopie) == 1
    problemy = _raport(kopie)["problemy"]
    assert not any("region naglowka XISF" in x for x in problemy), problemy   # bajty = model
    assert any(oczekiwany in x for x in problemy), problemy


def test_xisf_add_brak_wykonania_to_NIE(tmp_path):
    p = _xisf_uklad(tmp_path / "s.xisf", "zwarty")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    assert _po(kopie) == 1
    assert any("skan: brak karty OBJECT[0] po zapisie" in x for x in _raport(kopie)["problemy"])


def test_xisf_add_przepisany_atomowo_rozpoznaje_wylacznie_tozsamosc(tmp_path):
    """Droga atomowa pisarza XISF (plik tymczasowy + podmiana) daje TE SAME bajty co zapis w miejscu
    - przepisanie w całości rozpoznaje WYŁĄCZNIE tożsamość: `st_ino` i tożsamość z uchwytu."""
    p = _xisf_uklad(tmp_path / "s.xisf", "zwarty")
    kopie = _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    wynik = writeback.write_changes(str(p), [writeback.WriteOp("OBJECT", "add", "NGC 6992", "str")],
                                    None)
    assert wynik.status == "applied" and not wynik.in_place, wynik
    assert _po(kopie) == 1
    problemy = _raport(kopie)["problemy"]
    assert sorted(x.split(" - ")[0] for x in problemy) == [
        "st_ino zmieniony", "tozsamosc z uchwytu (wolumin, indeks) zmieniona"], problemy
    assert all("przepisany w calosci, nie w miejscu" in x for x in problemy), problemy


_ZWARTY = lambda p: _xisf_uklad(p, "zwarty")                    # noqa: E731


@pytest.mark.parametrize("buduj, wartosc, komentarz, kod, fragment", [
    (lambda p: _xisf_bez_object(p, props=WLASNOSC_ATR.format("NGC6992")), "NGC 6992", None,
     "xisf_prop_without_card", "ma wlasnosc"),
    (_xisf_dwa_obrazy, "NGC 6992", None, "xisf_many_images", "elementami <Image>"),
    (lambda p: _xisf_uklad(p, "zwarty", pad=20), "NGC 6992", None, "xisf_no_room", "rezerwie"),
    (lambda p: _xisf_uklad(p, "bez_wzorca"), "NGC 6992", None, "xisf_no_text_template",
     "brak wzorca karty"),
    (lambda p: _xisf_uklad(p, "wzorzec_bez_comment"), "NGC 6992", "nazwa obiektu",
     "xisf_template_no_comment", "wzorzec karty bez atrybutu comment"),
    (lambda p: _xisf_uklad(p, "wzorzec_obcy_atrybut"), "NGC 6992", None, "xisf_template_attrs",
     "obcymi atrybutami (unit)"),
    (_xisf_bez_obrazu_attachmentu, "NGC 6992", None, "xisf_no_identity", "bez obrazu-attachmentu"),
    (_xisf_uciety, "NGC 6992", None, "xisf_padding_broken", "niekompletnym wypelnieniem"),
    (_ZWARTY, "Mgławica", None, "card_value_chars", "spoza drukowalnego ASCII"),
    (_ZWARTY, "X" * 70, None, "card_value_long", "jednym rekordzie 80 znakow"),
    (_ZWARTY, "NGC 6992", "k" * 60, "card_comment_long", "jednym rekordzie 80 znakow"),
], ids=["wlasnosc_bez_karty", "dwa_obrazy", "brak_rezerwy", "brak_wzorca", "wzorzec_bez_comment",
        "wzorzec_obcy_atrybut", "bez_obrazu_attachmentu", "wypelnienie_niekompletne",
        "wartosc_spoza_ASCII", "wartosc_za_dluga", "komentarz_za_dlugi"])
def test_pisarz_xisf_add_odmawia_tego_samego_co_bramka_planu(tmp_path, buduj, wartosc, komentarz,
                                                             kod, fragment):
    """Bramka planu XISF `add` (własny kod kontroli) i pisarz w miejscu odmawiają tych samych plików
    i pozycji - z powodem po stronie kontroli i kodem po stronie pisarza; plik zostaje nietknięty."""
    p = buduj(tmp_path / "s.xisf")
    przed = p.read_bytes()
    with pytest.raises(SystemExit) as odmowa:
        _przed_add(tmp_path, p, "OBJECT", wartosc, komentarz)
    assert "odmowa: pozycja 0" in str(odmowa.value) and fragment in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()
    wynik = writeback.write_changes_inplace(
        str(p), [writeback.WriteOp("OBJECT", "add", wartosc, "str", comment=komentarz)], None)
    assert wynik.status == "blocked" and wynik.reason.code == kod, wynik
    assert p.read_bytes() == przed


@pytest.mark.parametrize("nazwa, buduj", [
    ("a.fits", lambda p: _fits_z_kartami(p, [("IMAGETYP", "Master Dark")])),
    ("a.fits", lambda p: _fits_z_kartami(p, [("IMAGETYP", "BIAS")])),
    ("s.xisf", lambda p: _xisf_uklad(p, "master_flat")),
], ids=["FITS_master_dark", "FITS_bias", "XISF_master_flat"])
def test_przed_odmawia_dopisania_OBJECT_klatce_kalibracyjnej(tmp_path, nazwa, buduj):
    """Kalibracja nie ma obiektu nieba (oś rodzaju repo): `add OBJECT` masterowi albo klatce
    dark/flat/bias to odmowa z powodem, zanim powstanie kopia."""
    p = buduj(tmp_path / nazwa)
    with pytest.raises(SystemExit) as odmowa:
        _przed_add(tmp_path, p, "OBJECT", "NGC 6992")
    assert "klatka kalibracyjna" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


# ============================================================ tożsamość z uchwytu i blokada (AR-165)


def _manifest_json(kopie):
    return json.loads((kopie / "manifest.json").read_text(encoding="utf-8"))


def test_przed_tozsamosc_z_uchwytu_zgodna_z_os_stat(tmp_path):
    """Układ `BY_HANDLE_FILE_INFORMATION` (kolejność pól) ma świadka spoza kontroli - `os.stat`.
    ZAŁOŻENIE ŚRODOWISKA, nie kontrakt API: CPython 3.12+ na Windows bierze `st_ino`
    z identyfikatora pliku, a `st_dev` z numeru woluminu (64-bitowego; jego dolne 32 bity to
    `dwVolumeSerialNumber`) - zmierzone 2026-10-16 na NTFS i na udziale SMB archiwum. Dwa odczyty
    samej kontroli zgadzałyby się także przy zamienionych `nFileIndexHigh`/`Low`, więc bez tego
    świadka zły układ struktury przeszedłby po cichu; gdy założenie się rozjedzie, test powie to
    zdaniem asercji."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    t = _manifest_json(kopie)["pozycje"][0]["tozsamosc"]
    st = os.stat(p)
    assert t["indeks"] >> 32, "warunek swiadka: czesc wysoka identyfikatora NTFS niezerowa"
    assert t["indeks"] == st.st_ino, "zalozenie srodowiska: st_ino = identyfikator pliku z uchwytu"
    assert t["wolumin"] == st.st_dev & 0xFFFFFFFF, "zalozenie srodowiska: st_dev = numer woluminu"


@pytest.mark.parametrize("tryb", ["po", "po_undo"])
def test_tozsamosc_z_uchwytu_inna_przy_tym_samym_st_ino_to_NIE(tmp_path, monkeypatch, tryb):
    """Porównanie tożsamości z uchwytu nie jest martwe obok `st_ino`: inna tożsamość przy tym
    samym `st_ino` to NIE w `po` i w `po-undo`."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    if tryb == "po":
        _zapisz(p, "NGC 6992")
    assert (_po(kopie) if tryb == "po" else _po_undo(kopie)) == 0
    prawdziwa = K._tozsamosc
    monkeypatch.setattr(K, "_tozsamosc",
                        lambda s: {**prawdziwa(s), "indeks": prawdziwa(s)["indeks"] + 1})
    if tryb == "po":
        assert _po(kopie) == 1
        problemy = _raport(kopie)["problemy"]
        assert problemy == ["tozsamosc z uchwytu (wolumin, indeks) zmieniona - plik podmieniony, "
                            "nie zapisany w miejscu ani przeniesiony"], problemy
    else:
        assert _po_undo(kopie) == 1


@pytest.mark.parametrize("pole", ["wolumin", "indeks"])
def test_przed_odmawia_tozsamosci_z_uchwytu_niepelnej(tmp_path, monkeypatch, pole):
    """Przez sieć API może oddać informację niepełną - zero to brak tożsamości, odmowa przed kopią."""
    p = _fits(tmp_path / "a.fits")
    prawdziwa = K._tozsamosc
    monkeypatch.setattr(K, "_tozsamosc", lambda s: {**prawdziwa(s), pole: 0})
    with pytest.raises(SystemExit) as odmowa:
        _przed(tmp_path, p, "NGC 6992")
    assert "tozsamosc z uchwytu niepelna" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_poza_windows_jawna_odmowa_nie_cichy_spadek_na_st_ino(tmp_path, monkeypatch):
    """Poza Windows tożsamości z uchwytu nie ma: `przed` odmawia, `po` i `po-undo` mówią NIE
    z powodem - żaden tryb nie wraca po cichu do samego `st_ino`."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    _zapisz(p, "NGC 6992")
    assert _po(kopie) == 0
    platforma = K.sys.platform
    monkeypatch.setattr(K.sys, "platform", "linux")
    try:
        wynik_po, wynik_undo = _po(kopie), _po_undo(kopie)
        with pytest.raises(SystemExit) as odmowa:
            _plan(tmp_path, [{"plik": str(p), "object": "NGC 6992"}], katalog="kopie2")
    finally:
        monkeypatch.setattr(K.sys, "platform", platforma)
    assert wynik_po == 1 and "wymaga Windows" in _raport(kopie)["problemy"][0], _raport(kopie)
    assert wynik_undo == 1
    assert "wymaga Windows" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie2").exists()


def test_przed_mierzy_blokade_naprawde_i_zapisuje_ja_w_manifescie(tmp_path, monkeypatch):
    """Droga prawdziwa (bez podstawki): `przed` mierzy blokadę w katalogu testowym, zapisuje wynik
    w manifeście (`wyniki` wyłącznie tekstowe, `kod` i `wolumin` piętro wyżej) i sprząta pliki
    pomiaru; wolumin pomiaru = wolumin pliku planu."""
    monkeypatch.setattr(K, "blokada", _BLOKADA)
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    m = _manifest_json(kopie)
    b = m["blokada"]
    assert set(b) == {"katalog", "wolumin", "kod", "wyniki"} and b["kod"] == 0, b
    assert b["katalog"] == os.path.abspath(_kb(tmp_path))
    assert b["wolumin"] == m["pozycje"][0]["tozsamosc"]["wolumin"]
    assert b["wyniki"]["os.replace zmienia tozsamosc z uchwytu"] == "tak", b
    assert b["wyniki"]["tozsamosc z uchwytu stabilna"] == "tak", b
    assert b["wyniki"]["os.replace proba 1"] == "wykonana", b
    assert all(isinstance(v, str) for v in b["wyniki"].values()), b
    assert {v for k, v in b["wyniki"].items()
            if not k.startswith("os.replace proba ")} <= {"odrzucone", "dziala", "tak"}, b
    assert not list(Path(_kb(tmp_path)).iterdir())
    assert m["srodowisko"] == {"python": sys.version, "komputer": platform.node()}
    _zapisz(p, "NGC 6992")
    assert _po(kopie) == 0, _raport(kopie)


@pytest.mark.parametrize("zmiana, fragment", [
    (lambda w: {**w, "kod": 1, "os.replace zmienia tozsamosc z uchwytu": "NIE"},
     "blokada na udziale NIE dziala (os.replace zmienia tozsamosc z uchwytu = NIE)"),
    (lambda w: {**w, "kod": 1, "os.replace proba 3": "odmowa PermissionError [WinError 5]",
                "os.replace zmienia tozsamosc z uchwytu":
                    "NIE zmierzone - PermissionError [WinError 5] w 3 probach"},
     "NIE dziala (os.replace zmienia tozsamosc z uchwytu = NIE zmierzone - PermissionError "
     "[WinError 5] w 3 probach) - zapisu"),
    (lambda w: {**w, "wolumin": w["wolumin"] ^ 1}, "blokade zmierzono na woluminie"),
    (None, "pomiar blokady w"),
], ids=["kod_1", "podmiana_padla_3_razy", "inny_wolumin", "pomiar_padl"])
def test_przed_odmawia_bez_blokady_zmierzonej_na_udziale_planu(tmp_path, monkeypatch,
                                                                 _pomiar_blokady, zmiana, fragment):
    """Blokada, która nie działa, pomiar z innego woluminu niż pliki planu albo pomiar, który padł -
    odmowa przed pierwszą kopią."""
    def pomiar(katalog):
        if zmiana is None:
            raise OSError("udzial niedostepny")
        return zmiana(dict(_pomiar_blokady))
    monkeypatch.setattr(K, "blokada", pomiar)
    p = _fits(tmp_path / "a.fits")
    with pytest.raises(SystemExit) as odmowa:
        _przed(tmp_path, p, "NGC 6992")
    assert fragment in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_blokada_mierzy_tozsamosc_z_uchwytu_i_podmiane(tmp_path):
    """Pomiar `blokada` (prawdziwy): tożsamość własnego pliku stabilna, `os.replace` własnym plikiem
    ją zmienia, `wolumin` = wolumin katalogu pomiaru; po pomiarze katalog pusty."""
    wyniki = _BLOKADA(str(tmp_path))
    assert wyniki["kod"] == 0, wyniki
    assert wyniki["tozsamosc z uchwytu stabilna"] == "tak"
    assert wyniki["os.replace zmienia tozsamosc z uchwytu"] == "tak"
    assert wyniki["os.replace proba 1"] == "wykonana" and "os.replace proba 2" not in wyniki
    assert not list(tmp_path.iterdir())
    swiadek = tmp_path / "swiadek.bin"
    swiadek.write_bytes(b"x")
    assert wyniki["wolumin"] == K._tozsamosc(str(swiadek))["wolumin"]


def test_blokada_odrzuca_udzial_ktory_po_podmianie_oddaje_stara_tozsamosc(tmp_path, monkeypatch):
    """Udział, na którym `os.replace` NIE zmienia tożsamości, przepuściłby przepisanie w całości jako
    zapis w miejscu - pomiar mówi NIE, `kod` 1 (więc `przed` odmówi); pliki pomiaru sprzątnięte."""
    monkeypatch.setattr(K, "_tozsamosc", lambda sciezka: {"wolumin": 7, "indeks": 42})
    wyniki = _BLOKADA(str(tmp_path))
    assert wyniki["tozsamosc z uchwytu stabilna"] == "tak"
    assert wyniki["os.replace zmienia tozsamosc z uchwytu"] == "NIE"
    assert wyniki["kod"] == 1
    assert not list(tmp_path.iterdir())


def test_blokada_odmowa_podmiany_we_wszystkich_probach_to_NIE_z_numerem_bledu(tmp_path,
                                                                              monkeypatch):
    """Zmierzone 2026-10-16 na udziale SMB archiwum (katalog testowy): `os.replace` własnym plikiem
    po zamknięciu uchwytów celu - `PermissionError` [WinError 5]. Pomiar próbuje 3 razy co 0,5 s,
    każdą próbę zapisuje w wynikach, a gdy padną wszystkie - wynik NIE z numerem błędu (`kod` 1,
    więc `przed` odmówi z tym powodem), nie wyjątek bez wyników; pliki pomiaru sprzątnięte."""
    def odmowa(*a, **kw):
        raise PermissionError(13, "Odmowa dostepu", None, 5)
    pauzy = []
    monkeypatch.setattr(K.os, "replace", odmowa)
    monkeypatch.setattr(K.time, "sleep", pauzy.append)
    wyniki = _BLOKADA(str(tmp_path))
    assert wyniki["os.replace na plik"] == "odrzucone"
    assert [wyniki[f"os.replace proba {n}"] for n in (1, 2, 3)] == [
        "odmowa PermissionError [WinError 5]"] * 3, wyniki
    assert wyniki["os.replace zmienia tozsamosc z uchwytu"] == (
        "NIE zmierzone - PermissionError [WinError 5] w 3 probach"), wyniki
    assert pauzy == [0.5, 0.5]
    assert wyniki["kod"] == 1
    assert not list(tmp_path.iterdir())


def test_blokada_podmiana_udana_w_ponowieniu_to_tak(tmp_path, monkeypatch):
    """Odmowa dostępu w dwóch pierwszych próbach, podmiana w trzeciej: próby zapisane w wynikach
    (informacja, poza `kod`), wynik pomiaru `tak`, `kod` 0. Podmienia się świeża para własnych
    plików (`zastepujacy` → `tozsamosci`), nie plik blokady."""
    prawdziwa, odmowy, pauzy = os.replace, [], []

    def podmiana(zrodlo, cel):
        if "horreum_proba_zastepujacy_" in str(zrodlo) and len(odmowy) < 2:
            odmowy.append(cel)
            raise PermissionError(13, "Odmowa dostepu", None, 5)
        return prawdziwa(zrodlo, cel)
    monkeypatch.setattr(K.os, "replace", podmiana)
    monkeypatch.setattr(K.time, "sleep", pauzy.append)
    wyniki = _BLOKADA(str(tmp_path))
    assert [wyniki[f"os.replace proba {n}"] for n in (1, 2, 3)] == [
        "odmowa PermissionError [WinError 5]", "odmowa PermissionError [WinError 5]",
        "wykonana"], wyniki
    assert wyniki["os.replace zmienia tozsamosc z uchwytu"] == "tak", wyniki
    assert wyniki["kod"] == 0, wyniki
    assert pauzy == [0.5, 0.5]
    assert all("horreum_proba_tozsamosci_" in str(cel) for cel in odmowy), odmowy
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("klucz, wzgledna", [("plik", "a.fits"), ("po", "IC405\\a.fits")])
def test_przed_odmawia_sciezki_wzglednej_w_planie(tmp_path, klucz, wzgledna):
    """Plan czyta ponownie `po`, w innym procesie i katalogu bieżącym - ścieżka względna wskazałaby
    tam inny plik, więc `przed` odmawia jej z powodem."""
    p = _fits(tmp_path / "a.fits")
    pozycja = {"plik": str(p), "po": str(tmp_path / "IC405" / "a.fits"), "object": "NGC 6992"}
    pozycja[klucz] = wzgledna
    with pytest.raises(SystemExit) as odmowa:
        _plan(tmp_path, [pozycja])
    assert f"sciezka wzgledna w '{klucz}'" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


# ============================================================ katalogi, środowisko, sens pozycji


def test_przed_odmawia_katalogu_kopii_na_woluminie_plikow_planu(tmp_path, monkeypatch):
    """Kopie pod udziałem z oryginałami skan wziąłby za drugie lokalizacje klatek - katalog kopii
    na woluminie plików planu (prawdziwa tożsamość z uchwytu; tu wszystko w `tmp_path`) to odmowa.
    Wolumin katalogu, którego jeszcze nie ma, to wolumin najbliższego istniejącego przodka."""
    monkeypatch.setattr(K, "_wolumin_katalogu", _WOLUMIN_KATALOGU)
    assert _WOLUMIN_KATALOGU(tmp_path / "nie" / "ma") == K._tozsamosc(str(tmp_path))["wolumin"]
    p = _fits(tmp_path / "a.fits")
    with pytest.raises(SystemExit) as odmowa:
        _przed(tmp_path, p, "NGC 6992")
    assert "na woluminie plikow planu" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_przed_zapisuje_kopie_sciezka_bezwzgledna_przy_katalogu_wzglednym(tmp_path, monkeypatch):
    """Katalog kopii podany względnie: manifest niesie ścieżki bezwzględne, więc `po` z innego
    katalogu bieżącego znajduje te same kopie."""
    p = _fits(tmp_path / "a.fits")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(p), "object": "NGC 6992"}]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    K.przed("kopie", str(plan), _kb(tmp_path))
    (tmp_path / "inny").mkdir()
    monkeypatch.chdir(tmp_path / "inny")
    _zapisz(p, "NGC 6992")
    assert _po(tmp_path / "kopie") == 0, _raport(tmp_path / "kopie")
    assert _manifest_json(tmp_path / "kopie")["pozycje"][0]["kopia"] == str(
        tmp_path / "kopie" / "0000.fits")


@pytest.mark.parametrize("zawartosc, fragment", [
    ({"a.fits": b"SIMPLE"}, "zawiera 1 cudzych plikow (a.fits)"),
    ({"horreum_proba_blokady_x.bin": b"\x00", "notatka.txt": b"x"}, "(notatka.txt)"),
    (None, "nieczytelny"),
], ids=["FITS_w_katalogu_testowym", "obcy_obok_resztki_pomiaru", "brak_katalogu"])
def test_przed_odmawia_katalogu_testowego_z_cudzymi_plikami(tmp_path, zawartosc, fragment):
    """Katalog testowy blokady zawiera wyłącznie pliki pomiaru (`horreum_proba_*`, także resztki
    przerwanego biegu) - cudzy plik, zwłaszcza FITS/XISF, to znak, że wskazano nie ten katalog."""
    p = _fits(tmp_path / "a.fits")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(p), "object": "NGC 6992"}]), encoding="utf-8")
    katalog = tmp_path / "testowy"
    if zawartosc is not None:
        katalog.mkdir()
        for nazwa, bajty in zawartosc.items():
            (katalog / nazwa).write_bytes(bajty)
    with pytest.raises(SystemExit) as odmowa:
        K.przed(str(tmp_path / "kopie"), str(plan), str(katalog))
    assert fragment in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_przed_przyjmuje_resztki_pomiaru_w_katalogu_testowym(tmp_path):
    katalog = Path(_kb(tmp_path))
    (katalog / "horreum_proba_blokady_123_x.bin").write_bytes(b"\x00")
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    assert (kopie / "manifest.json").exists()


def test_przed_odmawia_katalogu_testowego_na_innym_korzeniu_niz_pliki_planu(tmp_path):
    """Obok woluminu porównujemy korzeń ścieżki (litera dysku albo `\\\\serwer\\udział`): ten sam
    katalog podany w innej postaci korzenia (`\\\\?\\C:`) to dla kontroli inny udział - odmowa."""
    p = _fits(tmp_path / "a.fits")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(p), "object": "NGC 6992"}]), encoding="utf-8")
    with pytest.raises(SystemExit) as odmowa:
        K.przed(str(tmp_path / "kopie"), str(plan), "\\\\?\\" + _kb(tmp_path))
    assert "katalog testowy na korzeniu" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


@pytest.mark.parametrize("plik, pozycja", [
    ("fits", {"object": "NGC6992"}),
    ("fits", {"keyword": "OBJECT", "value": "NGC6992", "comment": KOMENTARZ, "op": "set"}),
    ("xisf", {"object": "NGC6992"}),
], ids=["FITS_ta_sama_wartosc", "FITS_ta_sama_wartosc_i_komentarz", "XISF_ta_sama_wartosc"])
def test_przed_odmawia_pozycji_set_bez_zmiany(tmp_path, plik, pozycja):
    """`set` na wartość, którą karta już ma (i komentarz bez zmiany), przeszedłby `po` bez żadnego
    zapisu - plik równy kopii JEST plikiem oczekiwanym; od pliku bez zmiany jest `none`."""
    p = _fits(tmp_path / "a.fits") if plik == "fits" else _xisf(tmp_path / "s.xisf", obj="'NGC6992'")
    with pytest.raises(SystemExit) as odmowa:
        _plan(tmp_path, [{"plik": str(p), **pozycja}])
    assert "pozycja bez zmiany" in str(odmowa.value), odmowa.value
    assert not (tmp_path / "kopie").exists()


def test_przed_przyjmuje_set_samego_komentarza(tmp_path):
    """Ta sama wartość, inny komentarz - to jest zmiana."""
    p = _fits(tmp_path / "a.fits")
    kopie = _plan(tmp_path, [{"plik": str(p), "keyword": "OBJECT", "value": "NGC6992",
                              "comment": "inny komentarz", "op": "set"}])
    assert (kopie / "manifest.json").exists()


@pytest.mark.parametrize("tryb", ["po", "po_undo"])
def test_st_ino_porownany_tylko_w_tym_samym_pythonie(tmp_path, tryb):
    """`st_ino` to szczegół CPython (3.12 zmieniło jego źródło): `po`/`po-undo` w innym Pythonie niż
    `przed` (manifest: `sys.version`) go nie porównuje - obie wartości idą do uwag raportu,
    rozstrzyga tożsamość z uchwytu; w tym samym Pythonie inny `st_ino` to NIE."""
    p = _fits(tmp_path / "a.fits")
    kopie = _przed(tmp_path, p, "NGC 6992")
    if tryb == "po":
        _zapisz(p, "NGC 6992")

    def ino_plus(m):
        m["pozycje"][0]["ino"] += 1
        return m
    _manifest_zmien(kopie, ino_plus)
    sprawdz = _po if tryb == "po" else _po_undo
    assert sprawdz(kopie) == 1
    _manifest_zmien(kopie, lambda m: {**m, "srodowisko": {**m["srodowisko"], "python": "2.7"}})
    assert sprawdz(kopie) == 0
    if tryb == "po":
        raport = _raport(kopie)
        ino = os.stat(p).st_ino
        assert raport["uwagi"] == [f"st_ino nieporownany - inny Python niz przy przed: przed "
                                   f"{ino + 1}, po {ino}; rozstrzyga tozsamosc z uchwytu"], raport
