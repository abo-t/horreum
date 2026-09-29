"""sha1_of / sha1_of_span — tożsamość frame'a i odciski przejścia, read-only ('rb').
`sha1_of_set` (I-2c) nie dotyka dysku: odcisk ZBIORU tożsamości pod porównanie dopasowań."""
import hashlib

import pytest

from horreum.hashing import sha1_of, sha1_of_set, sha1_of_span


def test_sha1_zgodne_z_hashlib(tmp_path):
    payload = bytes((i * 31 + 7) & 0xFF for i in range(5000))
    f = tmp_path / "x.fits"
    f.write_bytes(payload)
    assert sha1_of(str(f)) == hashlib.sha1(payload).hexdigest()


def test_sha1_pusty_plik(tmp_path):
    f = tmp_path / "empty.fits"
    f.write_bytes(b"")
    assert sha1_of(str(f)) == hashlib.sha1(b"").hexdigest()


def test_sha1_wieksze_niz_bufor(tmp_path):
    """Plik > bufor (1 MB) — pętla czytania działa wieloprzebiegowo."""
    payload = b"PHOTON" * 200_000          # ~1.2 MB
    f = tmp_path / "big.fits"
    f.write_bytes(payload)
    assert sha1_of(str(f), buf=4096) == hashlib.sha1(payload).hexdigest()


# --- sha1_of_span: hash pliku + wycinka JEDNYM przebiegiem (PF-1, brief §2) ---

def test_span_oba_hasze_zgodne_z_hashlib(tmp_path):
    """Jeden przebieg daje: sha1 CAŁEGO pliku == hashlib na bajtach ORAZ sha1 wycinka ==
    hashlib na slice — także gdy wycinek przecina granice bufora (buf=64)."""
    payload = bytes((i * 17 + 3) & 0xFF for i in range(1000))
    f = tmp_path / "x.fits"
    f.write_bytes(payload)
    file_h, span_h = sha1_of_span(str(f), (100, 300), buf=64)
    assert file_h == hashlib.sha1(payload).hexdigest()
    assert span_h == hashlib.sha1(payload[100:400]).hexdigest()


def test_span_none_i_zerowy_daja_none(tmp_path):
    """`span=None` (W1/brak sekcji) i `size==0` (HDU bez danych) → hash wycinka None;
    hash pliku liczony normalnie (kontrakt jak `data_sha1` dawcy)."""
    payload = b"DATA" * 100
    f = tmp_path / "y.fits"
    f.write_bytes(payload)
    whole = hashlib.sha1(payload).hexdigest()
    assert sha1_of_span(str(f), None) == (whole, None)
    assert sha1_of_span(str(f), (0, 0)) == (whole, None)


def test_span_wystajacy_poza_eof_hashuje_dostepne(tmp_path):
    """Wycinek dłuższy niż plik → hash tego, co jest (parytet z dawcą: plik krótszy niż
    deklaracja = hash niepełny → mismatch, nie wyjątek)."""
    payload = b"0123456789"
    f = tmp_path / "short.fits"
    f.write_bytes(payload)
    _, span_h = sha1_of_span(str(f), (5, 100))
    assert span_h == hashlib.sha1(payload[5:]).hexdigest()


def test_span_caly_plik_rowny_sha1_of(tmp_path):
    """Wycinek == cały plik → oba hasze identyczne i równe `sha1_of`."""
    payload = bytes(range(256))
    f = tmp_path / "z.fits"
    f.write_bytes(payload)
    file_h, span_h = sha1_of_span(str(f), (0, len(payload)))
    assert file_h == span_h == sha1_of(str(f))


# --- sha1_of_span(substitute=): trzeci hash w TYM SAMYM przebiegu (kontrola danych, AR-24) ---

def _podstawiony(payload, offset, region):
    """Wyrocznia: sha1 bajtów pliku z `region` nałożonym od `offset` WYŁĄCZNIE na bajty, które plik
    ma (region wystający poza EOF niczego nie dopisuje)."""
    b = bytearray(payload)
    koniec = min(len(b), offset + len(region))
    if offset < koniec:
        b[offset:koniec] = region[:koniec - offset]
    return hashlib.sha1(bytes(b)).hexdigest()


@pytest.mark.parametrize("offset, dlugosc", [
    (0, 10), (60, 10), (64, 64), (100, 300), (990, 20), (1000, 5), (5000, 5), (0, 0)])
def test_podstawienie_zgodne_z_wyrocznia_na_granicach_bufora(tmp_path, offset, dlugosc):
    """Trzeci hash == wyrocznia na bajtach dla regionu na początku, przecinającego granice bufora
    (buf=64), obejmującego kilka buforów, wystającego poza EOF, zaczynającego się na EOF i za nim
    oraz pustego; dwa pierwsze hasze - te same co bez podstawienia.

    Falsyfikator: usuń w `sha1_of_span` gałąź `else: h_sub.update(b)` albo przesuń wycinek regionu
    o bajt → wyrocznia się rozjeżdża."""
    payload = bytes((i * 17 + 3) & 0xFF for i in range(1000))
    region = bytes((i * 29 + 101) & 0xFF for i in range(dlugosc))
    f = tmp_path / "x.fits"
    f.write_bytes(payload)
    wynik = sha1_of_span(str(f), (100, 300), buf=64, substitute=(offset, region))
    assert wynik[:2] == sha1_of_span(str(f), (100, 300), buf=64)
    assert wynik[2] == _podstawiony(payload, offset, region)


def test_podstawienie_starego_regionu_odtwarza_sha1_pliku_sprzed_zapisu(tmp_path):
    """Plik po zapisie regionu z PODSTAWIONYM starym regionem ma sha1 pliku sprzed zapisu; bajt
    zmieniony poza regionem i plik ucięty - już nie."""
    przed = bytes((i * 7 + 1) & 0xFF for i in range(4000))
    stary = przed[80:160]
    po = przed[:80] + bytes(80) + przed[160:]
    f = tmp_path / "p.fits"
    f.write_bytes(po)
    kotwica = hashlib.sha1(przed).hexdigest()
    assert sha1_of_span(str(f), None, buf=256, substitute=(80, stary))[2] == kotwica
    dryf = bytearray(po)
    dryf[3000] ^= 0xFF
    f.write_bytes(bytes(dryf))
    assert sha1_of_span(str(f), None, buf=256, substitute=(80, stary))[2] != kotwica
    f.write_bytes(po[:3500])
    assert sha1_of_span(str(f), None, buf=256, substitute=(80, stary))[2] != kotwica


# --- sha1_of_set: odcisk ZBIORU (I-2c, rodowód stosów) ---

def test_set_nie_zalezy_od_kolejnosci_ani_powtorzen():
    """Zbiór, nie lista: ten sam skład w innej kolejności (i z duplikatem) daje TEN SAM odcisk.
    Dzięki temu odcisk zmienia się DOKŁADNIE wtedy, gdy zmienił się skład dopasowania."""
    assert sha1_of_set(["b", "a"]) == sha1_of_set(["a", "b", "a"])
    assert sha1_of_set(["a", "b"]) != sha1_of_set(["a", "c"])


def test_set_pusty_daje_none():
    """Brak wejść to BRAK odcisku, nie odcisk pustki — kolumna ma milczeć, gdy nie ma o czym mówić."""
    assert sha1_of_set([]) is None


def test_set_separator_chroni_przed_sklejeniem():
    """Bez separatora ['ab','c'] i ['a','bc'] dałyby jeden odcisk — kolizja na sklejeniu."""
    assert sha1_of_set(["ab", "c"]) != sha1_of_set(["a", "bc"])
