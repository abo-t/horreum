"""Runtime-tripwir append-only plików: snapshot przed, weryfikacja po (read-only)."""
from horreum.safety import snapshot_paths, verify_no_overwrite


def test_mkdir_only_czysto(tmp_path):
    """Istniejące pliki nietknięte + nowe puste katalogi → zero naruszeń."""
    existing = tmp_path / "keep.fits"
    existing.write_bytes(b"DANE" * 100)
    pre = snapshot_paths([existing, tmp_path / "new_dir"])
    (tmp_path / "new_dir").mkdir()                       # tylko utworzenie pustego katalogu
    assert verify_no_overwrite(pre) == []


def test_nadpisanie_pliku_wykryte(tmp_path):
    existing = tmp_path / "keep.fits"
    existing.write_bytes(b"ORYGINAL")
    pre = snapshot_paths([existing])
    existing.write_bytes(b"OVERWRITTEN")
    violations = verify_no_overwrite(pre)
    assert len(violations) == 1 and "ISTNIEJĄCY PLIK zmieniony" in violations[0]


def test_katalog_zmienil_typ_wykryty(tmp_path):
    d = tmp_path / "as_dir"
    d.mkdir()
    pre = snapshot_paths([d])
    d.rmdir()
    (tmp_path / "as_dir").write_bytes(b"teraz plik")     # katalog -> plik
    violations = verify_no_overwrite(pre)
    assert len(violations) == 1 and "katalog zmienił typ" in violations[0]
