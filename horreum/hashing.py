"""Liczenie SHA1 pliku — tożsamość frame'a (przeżywa rename/move).

`sha1_of` przeniesione 1:1 z `custos/hashing.py` (zamrożony Custos-Messium).
`sha1_of_span` (PF-1 przejścia fitsmirror, brief §2): sha1 CAŁEGO pliku + sha1 wycinka
bajtów (sekcja DANYCH HDU / attachment XISF) w JEDNYM przebiegu strumieniowym — pozycje
wycinka znane z nagłówka PRZED odczytem treści, więc jeden odczyt aktualizuje oba hasze.
Pliki otwierane WYŁĄCZNIE do odczytu binarnego ('rb') — faza skanu Horreum niczego nie
zapisuje na dysk usera (inwariant append-only, PLAN §6).
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


def sha1_of_span(path, span, buf=1 << 20):
    """(sha1 całego pliku, sha1 wycinka `[start, start+size)`) JEDNYM przebiegiem.

    `span` = `(start, size)` albo `None`. Hash wycinka jest `None`, gdy `span is None`
    lub `size == 0` (HDU bez sekcji danych — kontrakt jak `data_sha1` dawcy). Wycinek
    wystający poza EOF hashuje to, co jest (parytet z dawcą: plik krótszy niż deklaracja
    → hash niepełny = mismatch, nie wyjątek)."""
    h_file = hashlib.sha1()
    h_span = hashlib.sha1() if span is not None and span[1] > 0 else None
    pos = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            if h_span is not None:
                start = max(span[0], pos)
                end = min(span[0] + span[1], pos + len(b))
                if start < end:
                    h_span.update(b[start - pos:end - pos])
            h_file.update(b)
            pos += len(b)
    return h_file.hexdigest(), (h_span.hexdigest() if h_span is not None else None)
