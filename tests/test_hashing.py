"""sha1_of / sha1_of_span — tożsamość frame'a i odciski przejścia, read-only ('rb')."""
import hashlib

from horreum.hashing import sha1_of, sha1_of_span


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
