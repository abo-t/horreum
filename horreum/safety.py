"""Runtime-tripwir append-only plików — czyste funkcje, BEZ Qt (testowalne wszędzie).

Przeniesione 1:1 z `custos/tree/safety.py` (zamrożony Custos), przełożone na inwariant
Horreum (PLAN §6): faza skanu = TYLKO odczyt, zero zapisu na dysk usera. Statyczny tripwir
(meta-test AST) pilnuje KODU; ten moduł działa W RUNTIME — odcisk (sha1+mtime+size) ścieżek
PRZED operacją, weryfikacja PO. Gdyby skan kiedykolwiek nadpisał istniejący plik (realny
zapis, nie tylko wzorzec w kodzie), porównanie to wyłapie. Wyłącznie ODCZYT (stat + open 'rb').

Bez PySide6 — by przeszły bramkę izolowanego clone'a (§5.11), gdzie GUI nie jest instalowane.
"""
import hashlib
from pathlib import Path


def _file_fingerprint(p):
    """Odcisk pliku: (sha1, mtime_ns, size). Read-only ('rb' = odczyt, nie łamie inwariantu)."""
    st = p.stat()
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return (h.hexdigest(), st.st_mtime_ns, st.st_size)


def snapshot_paths(paths):
    """Odcisk istniejących ścieżek (katalog → 'dir', plik → fingerprint). Read-only; ścieżki
    nieistniejące pomijane."""
    snap = {}
    for p in paths:
        p = Path(p)
        try:
            if p.exists():
                snap[str(p)] = "dir" if p.is_dir() else _file_fingerprint(p)
        except OSError:
            pass
    return snap


def verify_no_overwrite(pre):
    """Sprawdź, że żaden zapamiętany PLIK nie został zmieniony, a katalog nie zmienił typu.
    Zwróć listę naruszeń (pusta = czysto). Read-only."""
    violations = []
    for sp, fp in pre.items():
        p = Path(sp)
        if fp == "dir":
            if not p.is_dir():
                violations.append(f"{sp}: katalog zmienił typ")
        else:
            try:
                changed = (not p.is_file()) or _file_fingerprint(p) != fp
            except OSError:
                changed = True
            if changed:
                violations.append(f"{sp}: ISTNIEJĄCY PLIK zmieniony — skan nie wolno nadpisywać")
    return violations
