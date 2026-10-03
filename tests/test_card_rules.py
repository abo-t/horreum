"""Szew reguł karty: wstawka karty XISF (AR-6), utrata zastanego komentarza FITS na drodze atomowej
(AR-7) i reguły karty FITS 4.0 w PODGLĄDZIE makra i edycji w siatce (AR-9).

Pliki powstają w `tmp_path`: FITS przez astropy, XISF składany bajt po bajcie (sygnatura + nagłówek
XML + rezerwa + attachment), żeby test panował nad POSTACIĄ elementu `<FITSKeyword>` - samozamykającą
albo z zamknięciem - bo od niej zależy, gdzie kończy się karta."""

from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from astropy.io import fits

from horreum import card_rules, macro, scan, writeback

_SAMOZAMYKAJACA = '<FITSKeyword name="{n}" value="{v}" comment="{c}"/>'
_Z_ZAMKNIECIEM = '<FITSKeyword name="{n}" value="{v}" comment="{c}"></FITSKeyword>'


def _karty_xml(karty, postac):
    return "".join("\n    " + postac.format(n=n, v=v, c=c) for n, v, c in karty)


def _xisf(tmp_path, name, karty_xml, *, pad=512, payload=b"\x07" * 32):
    """Monolityczny XISF z kartami podanymi jako GOTOWY XML (postać elementu wybiera test). Offset
    attachmentu na stałej szerokości - długość XML nie zależy od własnej wartości offsetu."""
    def body(start):
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{start:08d}:{len(payload)}">{karty_xml}\n  </Image>'
                '</xisf>').encode("utf-8")

    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    path = tmp_path / name
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4
                 + xml + b"\x00" * pad + payload)
    return path


def _sha(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _rodzice_kart(xml_bytes):
    """Nazwa lokalna RODZICA każdej karty `<FITSKeyword>`, w kolejności dokumentu."""
    root = ET.fromstring(scan.xml_parsable(xml_bytes))
    return [scan._local_name(rodzic.tag) for rodzic in root.iter() for dziecko in rodzic
            if scan._local_name(dziecko.tag) == "FITSKeyword"]


_KARTY = [("TELESCOP", "'ED'", "optyka"), ("FOCALLEN", "796", "")]


# ============================================================ AR-6: wstawka za końcem ELEMENTU


@pytest.mark.parametrize("postac", [_SAMOZAMYKAJACA, _Z_ZAMKNIECIEM], ids=["samozamykajaca",
                                                                            "z_zamknieciem"])
def test_wstawka_siada_za_koncem_elementu_ostatniej_karty(postac):
    """Wstawka idzie za KONIEC elementu ostatniej karty - przy postaci z zamknięciem za
    `</FITSKeyword>`. Dawniej szła za znacznik otwierający, więc nowa karta lądowała WEWNĄTRZ starej.
    Nowa karta ma postać sąsiada (wzorzec z zamknięciem kopiowany cały) i rodzica `<Image>`."""
    xml = ('<xisf><Image>' + _karty_xml(_KARTY, postac) + '</Image></xisf>').encode("utf-8")
    offset, blob = scan.build_fits_keyword_element(xml, keyword="OBJECT", value="NGC 7000")
    ostatnia = postac.format(n="FOCALLEN", v="796", c="").encode("utf-8")
    assert offset == xml.index(ostatnia) + len(ostatnia)
    assert blob == b"\n    " + postac.format(n="OBJECT", v="'NGC 7000'", c="").encode("utf-8")
    nowy = xml[:offset] + blob + xml[offset:]
    assert _rodzice_kart(nowy) == ["Image"] * 3


@pytest.mark.parametrize("postac", [_SAMOZAMYKAJACA, _Z_ZAMKNIECIEM], ids=["samozamykajaca",
                                                                            "z_zamknieciem"])
def test_pisarz_dopisuje_karte_obok_nie_wewnatrz(tmp_path, postac):
    """Pełna droga pisarza na obu postaciach elementu: 'applied', karta na końcu bloku, każda karta
    jest dzieckiem `<Image>`, dane nietknięte."""
    p = _xisf(tmp_path, "a.xisf", _karty_xml(_KARTY, postac))
    przed = scan.read_xisf_meta_full(str(p))
    res = writeback.write_xisf_changes(
        str(p), [writeback.WriteOp("OBJECT", "add", "NGC 7000", "str")], przed.header_hash)
    assert res.status == "applied", res.reason
    po = scan.read_xisf_meta_full(str(p))
    assert [(c.keyword, c.value_raw) for c in po.cards] == [
        ("TELESCOP", "ED"), ("FOCALLEN", "796"), ("OBJECT", "NGC 7000")]
    assert _rodzice_kart(po.xml_bytes) == ["Image"] * 3


def test_postac_mieszana_nie_zagniezdza_po_cichu(tmp_path):
    """Przypadek, który dawniej przechodził CICHO ('applied'): wzorzec samozamykający (karta
    tekstowa), a ostatnia karta z zamknięciem. Wstawka za jej znacznikiem otwierającym dawała
    poprawny XML i te same karty w round-tripie - z nową kartą wewnątrz `FOCALLEN`."""
    karty = (_SAMOZAMYKAJACA.format(n="TELESCOP", v="'ED'", c="optyka")
             + _Z_ZAMKNIECIEM.format(n="FOCALLEN", v="796", c=""))
    p = _xisf(tmp_path, "m.xisf", karty)
    res = writeback.write_xisf_changes(
        str(p), [writeback.WriteOp("OBJECT", "add", "NGC 7000", "str")], None)
    assert res.status == "applied", res.reason
    po = scan.read_xisf_meta_full(str(p))
    assert [c.keyword for c in po.cards] == ["TELESCOP", "FOCALLEN", "OBJECT"]
    assert _rodzice_kart(po.xml_bytes) == ["Image"] * 3


@pytest.mark.parametrize("karty_xml, fragment", [
    ('<FITSKeyword name="TELESCOP" value="\'ED\'" comment="">'
     '<FITSKeyword name="FOCALLEN" value="796" comment=""/></FITSKeyword>', "zagnieżdżona"),
    ('<FITSKeyword name="TELESCOP" value="\'ED\'" comment="">tekst</FITSKeyword>', "treść elementu"),
], ids=["zagniezdzona_zastana", "tresc_elementu"])
def test_struktura_kart_niezrozumiala_to_odmowa(tmp_path, karty_xml, fragment):
    """Karta zagnieżdżona już w pliku albo element karty z treścią → odmowa ('blocked', plik
    bajtowo nietknięty): takiej struktury nie kopiujemy dalej."""
    p = _xisf(tmp_path, "b.xisf", karty_xml)
    przed = _sha(p)
    res = writeback.write_xisf_changes(
        str(p), [writeback.WriteOp("OBJECT", "add", "NGC 7000", "str")], None)
    assert res.status == "blocked" and fragment in res.reason, res
    assert _sha(p) == przed


@pytest.mark.parametrize("postac", [_SAMOZAMYKAJACA, _Z_ZAMKNIECIEM], ids=["samozamykajaca",
                                                                            "z_zamknieciem"])
def test_weryfikacja_odmawia_lacie_zagniezdzajacej_karte(tmp_path, monkeypatch, postac):
    """Warunek w `_xisf_verify`: karta wstawiona do WNĘTRZA innej przechodzi round-trip kart
    (`xisf_cards` chodzi po całym drzewie), więc łapie ją osobne pytanie - `FITSKeyword` nie jest
    dzieckiem `FITSKeyword`. Wstawkę za znacznikiem otwierającym (dawny defekt) podstawiamy wprost;
    przy postaci samozamykającej ta sama wstawka jest legalna i ma przejść."""
    p = _xisf(tmp_path, "c.xisf", _karty_xml(_KARTY, postac))
    przed = _sha(p)

    def stara_wstawka(xml_bytes, *, keyword, value, comment=None):
        otw = xml_bytes.rindex(b"<FITSKeyword")
        koniec = xml_bytes.index(b">", otw) + 1
        return koniec, f'<FITSKeyword name="{keyword}" value="\'{value}\'" comment=""/>'.encode()
    monkeypatch.setattr(scan, "build_fits_keyword_element", stara_wstawka)
    res = writeback.write_xisf_changes(
        str(p), [writeback.WriteOp("OBJECT", "add", "NGC 7000", "str")], None)
    if postac is _SAMOZAMYKAJACA:
        assert res.status == "applied", res.reason
        return
    assert res.status == "failed" and "zagnieżdża <FITSKeyword>" in res.reason, res
    assert _sha(p) == przed and res.backup_text is None


# ============================================================ AR-7: komentarz na drodze atomowej

_KOMENTARZ_62 = ("komentarz programu akwizycji " * 3)[:62]      # kończy się literą, nie spacją


def _fits_z_komentarzem(path, wartosc="M42", komentarz=_KOMENTARZ_62):
    """FITS z kartą OBJECT w WOLNYM formacie (komentarz tuż za wartością) - tak, jak zapisują ją
    programy akwizycji; astropy po zmianie wartości przełoży ją na format stały."""
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header.append(fits.Card.fromstring(f"OBJECT  = '{wartosc}' / {komentarz}"))
    hdu.header["TELESCOP"] = ("RC8", "teleskop")
    hdu.writeto(path, overwrite=True)
    return path


def test_zmiana_ucinajaca_zastany_komentarz_to_odmowa(tmp_path):
    """Dawniej: 'applied', komentarz 62 → 47 znaków po cichu. Teraz 'blocked' z powodem, który mówi,
    ile się mieści i co zrobić; plik bajtowo nietknięty."""
    p = _fits_z_komentarzem(tmp_path / "a.fits")
    assert len(fits.getheader(str(p)).comments["OBJECT"]) == 62
    przed = _sha(p)
    res = writeback.write_changes(str(p), [writeback.WriteOp("OBJECT", "set", "NGC 7000", "str")],
                                  None)
    assert res.status == "blocked", res
    assert "z 62 do 47 znaków" in res.reason and "skróconym do 47" in res.reason
    assert _sha(p) == przed and res.backup_text is None


def test_zapis_tozsamosciowy_nie_jest_odmowa(tmp_path):
    """Zapis wartości aktualnej nie przekłada karty, więc niczego nie ucina - przechodzi, a komentarz
    zostaje cały."""
    p = _fits_z_komentarzem(tmp_path / "b.fits")
    res = writeback.write_changes(str(p), [writeback.WriteOp("OBJECT", "set", "M42", "str")], None)
    assert res.status == "applied", res.reason
    assert fits.getheader(str(p)).comments["OBJECT"] == _KOMENTARZ_62


@pytest.mark.parametrize("ops, komentarz", [
    ([writeback.WriteOp("TELESCOP", "set", "ED120R", "str")], "teleskop"),
    ([writeback.WriteOp("OBJECT", "set", "NGC 7000", "str", comment="krotki")], "krotki"),
], ids=["komentarz_miesci_sie", "lata_wnosi_komentarz"])
def test_zmiana_bez_utraty_komentarza_przechodzi_jak_dawniej(tmp_path, ops, komentarz):
    """Bez regresji: komentarz, który mieści się w formacie stałym, i komentarz wniesiony przez łatę
    przechodzą jak przed AR-7."""
    p = _fits_z_komentarzem(tmp_path / "c.fits")
    res = writeback.write_changes(str(p), ops, None)
    assert res.status == "applied", res.reason
    hdr = fits.getheader(str(p))
    assert hdr.comments[ops[0].keyword] == komentarz and hdr[ops[0].keyword] == ops[0].value


def test_zapis_w_miejscu_spada_i_droga_atomowa_odmawia(tmp_path):
    """Ten sam przypadek wchodzi przez zapis w miejscu: karta z zastanym komentarzem się nie mieści
    (`Fallback`), a droga atomowa, na którą spada, teraz odmawia zamiast ciąć."""
    p = _fits_z_komentarzem(tmp_path / "d.fits")
    ops = [writeback.WriteOp("OBJECT", "set", "NGC 7000", "str")]
    assert isinstance(writeback.write_changes_inplace(str(p), ops, None), writeback.Fallback)
    assert writeback.write_changes(str(p), ops, None).status == "blocked"


# ============================================================ AR-9: reguły w podglądzie


def test_silnik_makr_i_reguly_nie_ciagna_astropy():
    """`card_rules` i `macro` importują się bez astropy i numpy - makro to czysty silnik, a reguły
    karty pyta w podglądzie. Świeży proces, bo w procesie testów astropy już siedzi.
    Falsyfikator: wróć z `from . import writeback` na górę `macro` - astropy wraca."""
    kod = ("import sys, horreum.card_rules, horreum.macro; "
           "print(sorted(m for m in ('astropy', 'numpy', 'horreum.writeback', 'horreum.scan') "
           "if m in sys.modules))")
    wynik = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True, check=True)
    assert wynik.stdout.strip() == "[]", wynik.stdout + wynik.stderr


def test_writeback_reeksportuje_tego_samego_wlasciciela():
    """`gui/app.py` i testy pisarza wołają `writeback.card_violation` - to ma być TA SAMA funkcja."""
    assert writeback.card_violation is card_rules.card_violation
    assert writeback.FITS_STRING_MAX == card_rules.FITS_STRING_MAX


def _cel(fid=1):
    return {"frame_id": fid, "filetype": "fits", "location_id": 10 + fid, "path": f"R:/{fid}.fits",
            "compressed": 0, "sha1_data_uncomputable": 0, "header_hash": "h"}


def _karta(keyword, raw):
    return {"keyword": keyword, "idx": 0, "value_raw": raw, "value_num": None, "value_type": "str",
            "comment": None}


def _makro(assign):
    return macro.run_macro({"assign": assign}, [1], targets_fn=lambda ids: [_cel()],
                           cards_fn=lambda fid: [_karta("TELESCOP", "RC8")])


@pytest.mark.parametrize("assign, fragment", [
    ({"keyword": "TELESCOP", "op": "set", "expr": "X" * 69}, "rekord FITS"),
    ({"keyword": "TELESCOP", "op": "set", "expr": "Zażółć"}, "spoza drukowalnego ASCII"),
    ({"keyword": "TELESCOP", "op": "set", "expr": "ED120R", "comment": "c" * 48}, "rekord FITS"),
    ({"keyword": "OBJECTNAM", "op": "add", "expr": "x"}, "nazwa karty"),
], ids=["wartosc_za_dluga", "nie_ascii", "komentarz_za_dlugi", "zla_nazwa_add"])
def test_podglad_makra_pomija_zmiane_lamiaca_reguly(assign, fragment):
    """Łamiąca zmiana dostaje w PODGLĄDZIE pominięcie z powodem (kształt `skipped` jak każda inna
    bramka makra), zamiast trafić do stagingu i dowiedzieć się o tym przy commicie."""
    run = _makro(assign)
    assert run.touched == [] and len(run.skipped) == 1
    assert fragment in run.skipped[0].reason and run.skipped[0].path == "R:/1.fits"


def test_podglad_makra_przepuszcza_zmiane_na_styk():
    """Bez regresji: wartość na styk rekordu przechodzi do `touched`."""
    run = _makro({"keyword": "TELESCOP", "op": "set", "expr": "X" * card_rules.FITS_STRING_MAX})
    assert run.skipped == [] and run.touched[0].new_value == "X" * card_rules.FITS_STRING_MAX


def test_powod_w_podgladzie_to_powod_pisarza(tmp_path):
    """Jeden właściciel: powód pominięcia w podglądzie jest tym samym zdaniem, które pisarz dałby
    przy commicie jako 'blocked'."""
    p = tmp_path / "e.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"
    hdu.writeto(p)
    wartosc = "X" * 69
    pisarz = writeback.write_changes(str(p), [writeback.WriteOp("TELESCOP", "set", wartosc, "str")],
                                     None)
    run = _makro({"keyword": "TELESCOP", "op": "set", "expr": wartosc})
    assert pisarz.status == "blocked" and run.skipped[0].reason == pisarz.reason


def test_edycja_w_siatce_pyta_tych_samych_regul():
    """`evaluate_manual_change` (edycja jednej komórki) odrzuca łamiącą wartość z powodem reguły,
    a legalną przepuszcza jak dawniej."""
    karty = [_karta("TELESCOP", "RC8")]
    zla = macro.evaluate_manual_change(karty, "TELESCOP", "X" * 69)
    assert not zla.ok and "rekord FITS" in zla.reason
    dobra = macro.evaluate_manual_change(karty, "TELESCOP", "ED120R")
    assert dobra.ok and dobra.op == "set" and dobra.new_value == "ED120R"
