"""sha1_of — tożsamość frame'a, read-only ('rb')."""
import hashlib

from horreum.hashing import sha1_of


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
