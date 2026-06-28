"""Liczenie SHA1 pliku — tożsamość frame'a (przeżywa rename/move).

Przeniesione 1:1 z `custos/hashing.py` (zamrożony Custos-Messium). Plik otwierany
WYŁĄCZNIE do odczytu binarnego ('rb') — faza skanu Horreum niczego nie zapisuje na
dysk usera (inwariant append-only, PLAN §6).
"""
import hashlib


def sha1_of(path, buf=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
