"""Liczenie SHA1 pliku — tożsamość frame'a (przeżywa rename/move).

`sha1_of` przeniesione 1:1 z `custos/hashing.py` (zamrożony Custos-Messium).
`sha1_of_span` (PF-1 przejścia fitsmirror, brief §2): sha1 CAŁEGO pliku + sha1 wycinka
bajtów (sekcja DANYCH HDU / attachment XISF) w JEDNYM przebiegu strumieniowym — pozycje
wycinka znane z nagłówka PRZED odczytem treści, więc jeden odczyt aktualizuje oba hasze.
Na żądanie (`substitute=`, re-sync po zapisie w miejscu) ten sam przebieg liczy trzeci hash:
sha1 pliku z podstawionym starym regionem nagłówka - kontrola danych bez drugiego odczytu (AR-24).
Pliki otwierane WYŁĄCZNIE do odczytu binarnego ('rb') — faza skanu Horreum niczego nie
zapisuje na dysk usera (inwariant append-only, PLAN §6).

`sha1_of_set` NIE dotyka dysku — to odcisk ZBIORU tożsamości (I-2c): materiał do porównania
„czy dopasowanie wyszło tak samo jak poprzednim razem". Mieszka tu, bo pytanie jest to samo
(„czy treść jest ta sama"), tylko przedmiotem jest zbiór, nie plik.
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


def sha1_of_span(path, span, buf=1 << 20, *, substitute=None):
    """(sha1 całego pliku, sha1 wycinka `[start, start+size)`) JEDNYM przebiegiem.

    `span` = `(start, size)` albo `None`. Hash wycinka jest `None`, gdy `span is None`
    lub `size == 0` (HDU bez sekcji danych — kontrakt jak `data_sha1` dawcy). Wycinek
    wystający poza EOF hashuje to, co jest (parytet z dawcą: plik krótszy niż deklaracja
    → hash niepełny = mismatch, nie wyjątek).

    `substitute` = `(offset, region)` (na żądanie, kontrola danych zapisu w miejscu): TRZECI hash
    w tej samej pętli - sha1 pliku, w którym bajty `[offset, offset+len(region))` zastąpiono
    `region`; wynik to wtedy trójka `(plik, wycinek, podstawiony)`. Podstawienie obejmuje wyłącznie
    bajty, które plik ma: region wystający poza EOF niczego nie dopisuje, więc plik ucięty daje hash
    inny niż plik sprzed zapisu. Bez `substitute` - para i pętla jak dotąd (zwykły skan nie płaci za
    trzeci hash)."""
    h_file = hashlib.sha1()
    h_span = hashlib.sha1() if span is not None and span[1] > 0 else None
    h_sub = hashlib.sha1() if substitute is not None else None
    if h_sub is not None:
        sub_start, region = substitute
        sub_end = sub_start + len(region)
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
            if h_sub is not None:
                start, end = max(sub_start, pos), min(sub_end, pos + len(b))
                if start < end:
                    h_sub.update(b[:start - pos] + region[start - sub_start:end - sub_start]
                                 + b[end - pos:])
                else:
                    h_sub.update(b)
            h_file.update(b)
            pos += len(b)
    wynik = (h_file.hexdigest(), (h_span.hexdigest() if h_span is not None else None))
    return wynik if h_sub is None else (*wynik, h_sub.hexdigest())


def sha1_of_set(values):
    """Odcisk ZBIORU tożsamości (I-2c) — `None` dla zbioru pustego.

    Wejście traktujemy jak ZBIÓR: duplikaty znoszone, kolejność bez znaczenia (sort przed
    haszowaniem). Dzięki temu ten sam zestaw wejść dopasowany w innej kolejności daje ten sam
    odcisk, a odcisk zmienia się DOKŁADNIE wtedy, gdy zmienił się skład — po to jest liczony.

    Rozdzielamy elementy bajtem `\\n`, który w sha1 heksowym nie występuje; bez separatora
    ['ab','c'] i ['a','bc'] dałyby jeden odcisk."""
    unikaty = sorted({str(v) for v in values})
    if not unikaty:
        return None
    return hashlib.sha1("\n".join(unikaty).encode("utf-8")).hexdigest()
