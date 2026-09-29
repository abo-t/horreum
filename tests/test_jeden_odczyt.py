"""JEDEN pełny odczyt pliku na zapis w miejscu (AR-24): kontrola danych dokończenia (sha1 pliku
z podstawionym starym regionem == kotwica sprzed zapisu) liczona w TYM SAMYM przebiegu co re-sync
(`writeback._skan_kontrolny` → `scan.scan_file(substitute=)` → `hashing.sha1_of_span`), a nie osobnym
odczytem całego pliku. Przy wsadzie po SMB drugi odczyt to drugie tyle czasu pod blokadą pliku.

Licznik pełnych odczytów: uchwyt otwarty zwykłym `open` w `hashing`/`scan`/`writeback` liczy się tyle
razy, ile razy przeczytał rozmiar pliku, a pełny odczyt uchwytu blokady (`writeback._sha1_uchwytu`)
- raz na wywołanie. Pliki są po 2 MiB danych, więc próbki pisarza (3 × 64 KiB) i odczyty nagłówka
nie składają się w pełny odczyt.

Kontrakt kontroli się nie poluzował: werdykt dla pliku zgodnego, dryfu danych poza nagłówkiem, pliku
uciętego (za regionem i w regionie) i regionu przesuniętego (przebudowa z innym rozmiarem nagłówka)
jest ten sam co werdykt wzorcowy liczony osobnym odczytem - sha1 bajtów pliku z regionem nałożonym
WYŁĄCZNIE na bajty, które plik ma. Zwykły skan (bez `substitute`) woła hasze jak dotąd."""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import os
import struct

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, hashing, repo, scan, writeback

NOW = "2026-09-29T00:00:00+00:00"
KOMENTARZ = "Name of the object of interest"
_DANE = 1024                                   # bok obrazu: 1024 × 1024 × int16 = 2 MiB


_DRUGI = 512                                  # drugi HDU / obraz: 512 × 512 × int16 = 512 KiB
_W_DRUGIM = 300 * 1024                         # bajt drugiej części tyle przed końcem pliku: poza
                                               # `sha1_data` i poza próbkami pisarza (64 KiB)


def _fits(path, *, seed=0, obj="NGC6992", extra=()):
    """FITS: HDU główne 2 MiB (tożsamość `sha1_data`) + rozszerzenie 512 KiB (poza tożsamością)."""
    dane = ((np.arange(_DANE * _DANE, dtype=np.int32) * 7 + seed) % 30000).astype(np.int16)
    hdu = fits.PrimaryHDU(data=dane.reshape(_DANE, _DANE))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = (obj, KOMENTARZ)
    for k, v in extra:
        hdu.header.append((k, v))
    ext = fits.ImageHDU(data=np.full((_DRUGI, _DRUGI), 3, dtype=np.int16), name="DRUGI")
    fits.HDUList([hdu, ext]).writeto(path, overwrite=True)
    return path


def _xisf(path, *, obj="'NGC6992'", pad=64, seed=0):
    """Monolityczny XISF: XML (karty pod pierwszym obrazem) + rezerwa `pad` + obraz 2 MiB + drugi
    obraz 512 KiB bez kart (offsety na stałej szerokości)."""
    p1 = bytes((i + seed) & 0xFF for i in range(256)) * (_DANE * _DANE * 2 // 256)
    p2 = bytes(range(256)) * (_DRUGI * _DRUGI * 2 // 256)

    def body(s1, s2):
        kw = (f'<FITSKeyword name="IMAGETYP" value="\'Light\'" comment=""/>'
              f'<FITSKeyword name="OBJECT" value="{obj}" comment="nazwa obiektu"/>')
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="{_DANE}:{_DANE}:1" sampleFormat="UInt16" '
                f'location="attachment:{s1:08d}:{len(p1)}">{kw}</Image>'
                f'<Image id="drugi" geometry="{_DRUGI}:{_DRUGI}:1" sampleFormat="UInt16" '
                f'location="attachment:{s2:08d}:{len(p2)}"/></xisf>').encode("utf-8")
    s1 = scan.XISF_XML_OFFSET + len(body(0, 0)) + pad
    xml = body(s1, s1 + len(p1))
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml
                 + b"\x00" * pad + p1 + p2)
    return path


def _plik(tmp_path, fmt, nazwa="a"):
    return (_fits(tmp_path / f"{nazwa}.fits") if fmt == "fits"
            else _xisf(tmp_path / f"{nazwa}.xisf"))


def _baza_z_plikiem(tmp_path, plik, run="R"):
    con = db.open_db(str(tmp_path / "h.db"))
    scan.ingest_record(con, scan.scan_file(str(plik)), volume="V", now=NOW,
                       summary=scan.ScanSummary())
    loc = con.execute("SELECT id, header_hash, frame_id FROM location WHERE path = ?",
                      (str(plik),)).fetchone()
    repo.stage_pending(con, run_id=run, location_id=loc["id"], keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value="NGC 6992", new_type="str", new_comment=None,
                       expected_header_hash=loc["header_hash"])
    return con, loc


class _Uchwyt:
    """Uchwyt odczytu liczący bajty; przy zamknięciu dopisuje licznikowi `bajty // rozmiar`."""

    def __init__(self, f, licznik):
        self._f, self._licznik, self._bajty = f, licznik, 0
        self._rozmiar = os.fstat(f.fileno()).st_size

    def read(self, n=-1):
        b = self._f.read(n)
        self._bajty += len(b)
        return b

    def close(self):
        if not self._f.closed:
            if self._rozmiar:
                self._licznik.pelne += self._bajty // self._rozmiar
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __getattr__(self, nazwa):
        return getattr(self._f, nazwa)


class _Licznik:
    """Pełne odczyty pliku `cel` (zob. docstring modułu)."""

    def __init__(self, monkeypatch, cel):
        self.cel = os.path.normcase(os.path.abspath(str(cel)))
        self.pelne = 0
        for mod in (hashing, scan, writeback):
            monkeypatch.setattr(mod, "open", self._open, raising=False)
        prawdziwy = writeback._sha1_uchwytu

        def _uchwyt_blokady(fh):
            self.pelne += 1
            return prawdziwy(fh)
        monkeypatch.setattr(writeback, "_sha1_uchwytu", _uchwyt_blokady)

    def _open(self, plik, mode="r", *a, **kw):
        f = builtins.open(plik, mode, *a, **kw)
        if (isinstance(plik, (str, os.PathLike)) and "r" in mode and "+" not in mode
                and os.path.normcase(os.path.abspath(str(plik))) == self.cel):
            return _Uchwyt(f, self)
        return f


def _psuj_bajt_przy_fsync(monkeypatch, offset):
    """Usterka zapisu poza regionem nagłówka: po `fsync` bajt pod `offset` zmienia się NASZYM
    deskryptorem (pod blokadą nikt inny nie pisze)."""
    prawdziwy = os.fsync

    def _fsync(fd):
        prawdziwy(fd)
        os.lseek(fd, offset, os.SEEK_SET)
        b = os.read(fd, 1)
        os.lseek(fd, offset, os.SEEK_SET)
        os.write(fd, bytes([b[0] ^ 0xFF]))
    monkeypatch.setattr(writeback.os, "fsync", _fsync)


# ============================================================ LICZBA PEŁNYCH ODCZYTÓW


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_commit_i_undo_w_miejscu_czytaja_plik_w_calosci_raz(tmp_path, monkeypatch, fmt):
    """Commit w miejscu (kotwica bazy zgodna z `mtime`) i undo w miejscu: po JEDNYM pełnym odczycie
    - re-sync dokończenia liczy hasze pliku, danych i pliku z podstawionym regionem naraz.

    Falsyfikator: w `_resync` zwykły `scan.scan_file(path)` + osobny pełny odczyt pod kontrolę
    (kod sprzed AR-24) → 2 zamiast 1, dla commitu i dla undo."""
    p = _plik(tmp_path, fmt)
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    with monkeypatch.context() as m:
        licz = _Licznik(m, p)
        res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1 and not res.failed, res
    assert licz.pelne == 1
    with monkeypatch.context() as m:
        licz = _Licznik(m, p)
        u = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u.restored) == 1 and not u.failed, u
    assert licz.pelne == 1
    assert p.read_bytes() == przed
    assert [o["phase"] for o in con.execute("SELECT phase FROM inplace_op ORDER BY id")] == [
        "synced", "synced"]
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_kontrola_w_jednym_odczycie_lapie_bajt_poza_naglowkiem(tmp_path, monkeypatch, fmt):
    """Ten sam jeden odczyt nadal jest PEŁNYM dowodem: bajt drugiego HDU / obrazu (poza `sha1_data`
    i poza próbkami pisarza) zmieniony przy zapisie → 'failed' „POZA regionem", operacja `written`,
    baza nie wciąga pliku.

    Falsyfikator: `_kontrola_danych` porównuje z kotwicą `rec.file_sha1` zamiast
    `rec.file_sha1_substituted` → każdy commit w miejscu 'failed', test wyżej czerwienieje;
    pominięcie porównania → tu 'applied'."""
    p = _plik(tmp_path, fmt)
    con, loc = _baza_z_plikiem(tmp_path, p)
    with monkeypatch.context() as m:
        _psuj_bajt_przy_fsync(m, os.path.getsize(p) - _W_DRUGIM)
        licz = _Licznik(m, p)
        res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert not res.applied and len(res.failed) == 1, res
    assert "POZA regionem" in res.failed[0].reason, res.failed[0].reason
    assert licz.pelne == 1
    assert [o["phase"] for o in con.execute("SELECT phase FROM inplace_op")] == ["written"]
    assert con.execute("SELECT header_hash FROM location").fetchone()[0] == loc["header_hash"]
    con.close()


def test_tryb_scisly_placi_wylacznie_za_kotwice_przed_zapisem(tmp_path, monkeypatch):
    """Tryb pilotażu (`fallback=False`): pełny odczyt uchwytu blokady przed zapisem (kotwica) + jeden
    odczyt re-syncu z kontrolą = 2 (dawniej 3)."""
    p = _fits(tmp_path / "s.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    with monkeypatch.context() as m:
        licz = _Licznik(m, p)
        res = writeback.commit(con, "R", now=NOW, inplace=True, fallback=False)
    assert len(res.in_place) == 1, res
    assert licz.pelne == 2
    con.close()


def test_zwykly_skan_bez_trzeciego_hasha(tmp_path, monkeypatch):
    """Skan bez `substitute`: `sha1_of_span(ścieżka, wycinek)` bez słowa kluczowego (ta sama pętla
    co przed AR-24), jeden pełny odczyt, `file_sha1_substituted` None. Podstawienie nie zmienia
    żadnego innego pola rekordu.

    Falsyfikator: `scan_file` woła hasz zawsze z `substitute=` → lista wywołań ma słowo kluczowe."""
    p = _xisf(tmp_path / "z.xisf")
    wywolania = []
    prawdziwy = scan.sha1_of_span

    def _szpieg(*a, **kw):
        wywolania.append((len(a), kw))
        return prawdziwy(*a, **kw)
    with monkeypatch.context() as m:
        m.setattr(scan, "sha1_of_span", _szpieg)
        licz = _Licznik(m, p)
        rec = scan.scan_file(str(p))
    assert wywolania == [(2, {})] and licz.pelne == 1
    assert rec.file_sha1_substituted is None
    z_podstawieniem = scan.scan_file(str(p), substitute=(0, b"XISF0100"))
    assert dataclasses.replace(z_podstawieniem, file_sha1_substituted=None) == rec
    assert z_podstawieniem.file_sha1_substituted == rec.file_sha1


# ============================================================ KONTRAKT KONTROLI (werdykt)


def _wzorcowy_podstawiony(path, offset, region):
    """Wyrocznia: sha1 bajtów pliku z regionem nałożonym WYŁĄCZNIE na bajty, które plik ma - osobny
    pełny odczyt, jak kontrola sprzed AR-24."""
    with open(path, "rb") as fh:
        b = bytearray(fh.read())
    koniec = min(len(b), offset + len(region))
    if offset < koniec:
        b[offset:koniec] = region[:koniec - offset]
    return hashlib.sha1(bytes(b)).hexdigest()


def _werdykt_wzorcowy(path, expect_sha1_data, k):
    """Kontrola sprzed AR-24 (zwykły skan + osobny odczyt z podstawieniem) sprowadzona do klasy
    werdyktu."""
    rec = scan.scan_file(path)
    if expect_sha1_data is not None and rec.sha1_data != expect_sha1_data:
        return "sha1_data"
    if rec.header_hash != k.header_hash:
        return "header_hash"
    if k.anchor_sha1 is None:
        return "brak kotwicy"
    if _wzorcowy_podstawiony(path, k.offset, k.old_region) != k.anchor_sha1:
        return "POZA regionem"
    return None


def _klasa(werdykt):
    if werdykt is None:
        return None
    for znacznik in ("sha1_data", "header_hash", "brak kotwicy", "POZA regionem"):
        if znacznik in werdykt:
            return znacznik
    raise AssertionError(f"nieznany werdykt: {werdykt}")


def _po_commicie(tmp_path, fmt):
    """Plik po commicie w miejscu, kontrola dokładnie taka, jaką buduje dokończenie commitu, bajty
    sprzed commitu i `sha1_data` klatki."""
    p = _plik(tmp_path, fmt)
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1, res
    op = con.execute("SELECT * FROM inplace_op").fetchone()
    spec = writeback._spec_z_operacji(op)
    k = writeback._KontrolaDanych(spec.region_offset, spec.old_region,
                                  writeback._kotwica_operacji(con, op, writeback._location(
                                      con, loc["id"])), spec.post_hash)
    sha1_data = con.execute("SELECT sha1_data FROM frame").fetchone()[0]
    con.close()
    assert k.anchor_sha1 == hashlib.sha1(przed).hexdigest()
    return p, przed, k, sha1_data


def _przebuduj(p, fmt):
    """Region przesunięty: plik przebudowany z nagłówkiem innego rozmiaru (FITS: +1 blok kart,
    XISF: XML dłuższy i załącznik dalej), wartość `OBJECT` jak po zapisie."""
    if fmt == "fits":
        _fits(p, obj="NGC 6992", extra=[(f"K{i:03d}", i) for i in range(40)])
    else:
        _xisf(p, obj="'NGC 6992'", pad=64 + 2880)


def _przypadki(po, k):
    """(nazwa, bajty pliku albo None dla przebudowy) - `po` = bajty pliku po zapisie."""
    def _dryf(offset):
        b = bytearray(po)
        b[offset] ^= 0xFF
        return bytes(b)
    return [
        ("zgodny", po),
        ("dryf w danych tożsamości", _dryf(k.offset + len(k.old_region) + 4096)),
        ("dryf w drugiej części", _dryf(len(po) - _W_DRUGIM)),
        ("dryf w ostatnim bajcie", _dryf(len(po) - 1)),
        ("ucięty za regionem", po[:-2880]),
        ("ucięty w regionie", po[:k.offset + len(k.old_region) // 2]),
        ("region przesunięty", None),
    ]


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_werdykt_kontroli_ten_sam_co_osobnym_odczytem(tmp_path, fmt):
    """Dla każdego przypadku: sha1 z podstawionym regionem z JEDNEGO odczytu == wyrocznia na bajtach,
    a werdykt `_kontrola_danych` (z tożsamością danych i bez niej, a dla przebudowy także z nagłówkiem
    udającym zapisany) == werdykt kontroli sprzed AR-24. Plik zgodny przechodzi, każdy inny odpada.

    Falsyfikator: podstawienie liczone na pliku bez przycięcia do EOF (region dopisany za końcem)
    → „ucięty w regionie" rozjeżdża się z wyrocznią; brak porównania z kotwicą → dryfy przechodzą."""
    p, przed, k, sha1_data = _po_commicie(tmp_path, fmt)
    assert p.read_bytes() != przed
    for nazwa, bajty in _przypadki(p.read_bytes(), k):
        if bajty is None:
            _przebuduj(p, fmt)
        else:
            p.write_bytes(bajty)
        rec = writeback._skan_kontrolny(str(p), k)
        assert rec.file_sha1_substituted == _wzorcowy_podstawiony(str(p), k.offset, k.old_region), \
            nazwa
        kontrole = [k, dataclasses.replace(k, header_hash=rec.header_hash)]
        for kk in kontrole:
            for expect in (None, sha1_data):
                nowy = _klasa(writeback._kontrola_danych(writeback._skan_kontrolny(str(p), kk),
                                                         expect, kk))
                assert nowy == _werdykt_wzorcowy(str(p), expect, kk), (nazwa, expect)
        werdykt = _klasa(writeback._kontrola_danych(rec, sha1_data, k))
        assert (werdykt is None) == (nazwa == "zgodny"), (nazwa, werdykt)
        if nazwa != "zgodny":                  # sam dowód bajtów (bez tożsamości i nagłówka) też
            bez_naglowka = dataclasses.replace(k, header_hash=rec.header_hash)
            assert _klasa(writeback._kontrola_danych(rec, None, bez_naglowka)) == \
                "POZA regionem", nazwa


def test_skompresowany_fits_liczy_podstawienie_tym_samym_przebiegiem(tmp_path):
    """CompImageHDU (zapis w miejscu go nie dotyczy, ale kontrakt `substitute` jest jeden): `file_sha1`
    ten sam co bez podstawienia, trzeci hash == wyrocznia."""
    p = tmp_path / "c.fits"
    dane = (np.arange(256 * 256) % 3000).astype(np.int16).reshape(256, 256)
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(data=dane)]).writeto(p)
    zwykly = scan.scan_file(str(p))
    assert zwykly.compressed
    region = b"X" * 100
    rec = scan.scan_file(str(p), substitute=(2880, region))
    assert (rec.file_sha1, rec.sha1_data) == (zwykly.file_sha1, zwykly.sha1_data)
    assert rec.file_sha1_substituted == _wzorcowy_podstawiony(str(p), 2880, region)


def test_rekord_bez_podstawienia_to_blad_wolajacego_nie_werdykt(tmp_path):
    """Rekord zwykłego skanu podany do kontroli z kotwicą → `ValueError` (EXPECT), nie „zgodny" ani
    „POZA regionem" - werdykt o pliku bez przeczytanego dowodu byłby zgadywaniem.

    Falsyfikator: usuń w `_kontrola_danych` warunek `rec.file_sha1_substituted is None` → wraca tekst
    „POZA regionem" zamiast wyjątku."""
    p = _fits(tmp_path / "e.fits")
    rec = scan.scan_file(str(p))
    k = writeback._KontrolaDanych(0, b"", hashlib.sha1(p.read_bytes()).hexdigest(),
                                  rec.header_hash)
    with pytest.raises(ValueError, match="_skan_kontrolny"):
        writeback._kontrola_danych(rec, None, k)
    assert writeback._kontrola_danych(writeback._skan_kontrolny(str(p), k), None, k) is None
