"""Numer seryjny woluminu (`horreum.volumes.volume_serial`) — MINIMALNY wycinek §7.5 pod bramę
przyrostową. Read-only OS call; Qt-free i bez astropy (stdlib+ctypes). Kontrakt: stabilny hex na
realnej ścieżce (Windows), `None` jako bezpieczny fallback (nie-Windows / ścieżka bez litery) →
wołający podstawia '?' → brama OFF → pełny skan."""
import sys

from horreum.volumes import volume_serial


def test_serial_realnej_sciezki_stabilny(tmp_path):
    s = volume_serial(str(tmp_path))
    if sys.platform == "win32":
        assert s is not None and len(s) == 8                 # 8-znakowy hex
        assert all(c in "0123456789ABCDEF" for c in s)
        assert volume_serial(str(tmp_path)) == s             # stabilny w obrębie sesji (ten sam wolumen)
    else:
        assert s is None                                     # fallback poza Windows


def test_sciezka_bez_litery_zwraca_none():
    """Ścieżka względna / bez woluminu → None (bezpieczny fallback, brama OFF)."""
    assert volume_serial("relative/path/no/drive") is None
