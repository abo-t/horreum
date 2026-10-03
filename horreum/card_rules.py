"""REGUŁY KARTY FITS 4.0 - jeden właściciel, bez astropy.

Treść, którą ŁATA wnosi do nagłówka, spełnia reguły karty FITS 4.0 (§4.1-4.2) - w OBU formatach:
XISF przejmuje je wprost (spec XISF 1.0 Rev. 1 §11.6: dane `<FITSKeyword>` spełniają wymagania
FITS 4.0 dla kart). Właściciel jest JEDEN - `card_violation`: pyta go pisarz FITS i pisarz XISF
(`writeback`), dialog naprawy nagłówka (`gui/app.py`) przed stagingiem oraz silnik makr
(`macro._evaluate_change`) w PODGLĄDZIE - łamiąca zmiana dostaje powód pominięcia, zanim trafi do
stagingu, a nie dopiero 'blocked' przy commicie (AR-9).

Dlaczego osobny moduł: `macro` to czysty silnik (zero DB, zero Qt) i jego import nie ma ciągnąć
astropy ani numpy, a `writeback` ładuje astropy na górze. Reguły są czystą arytmetyką na tekście,
więc mieszkają tu, a `writeback` je stąd importuje (i re-eksportuje nazwy wołane spoza niego).

Dlaczego reguły w ogóle, a nie astropy czy czytnik - zmierzone na astropy 8.0.0: znak sterujący
i nie-ASCII odrzuca już przypisanie karty, ale angielskim `ValueError`, czyli dawniej 'failed'
(„coś się zepsuło") zamiast odmowy; wartość dłuższa niż rekord przechodzi po cichu jako CONTINUE,
za długi komentarz jest po cichu UCINANY, a zła nazwa przy `add` zakłada kartę HIERARCH. Przy XISF
nie odmawiał nikt: znak sterujący szedł do nagłówka surowo, a nagłówek przestawał być poprawnym
XML 1.0 (spec §9.5 - PixInsight takiego pliku nie otworzy). Czytnik Horreum ten znak neutralizuje
(`scan.xml_parsable`), więc odczyt po zapisie tego nie widział.

Reguły pilnują TREŚCI ŁATY, nie pliku: zastana nielegalna treść (w archiwum jest plik z bajtem
0x07 w historii przetwarzania) nie blokuje łaty legalnej wartości. Nazwę sprawdzamy tylko wtedy,
gdy łata ją WNOSI (nowa karta) - `set` na istniejącej karcie jej nazwy nie zmienia.
"""

from __future__ import annotations

import dataclasses
import re

_FITS_NAME = re.compile(r"[A-Z0-9_-]{1,8}")   # §4.1.2.1: do 8 znaków z tego zbioru
FITS_STRING_MAX = 68      # tekst w apostrofach w JEDNYM rekordzie: 80 - nazwa 8 - "= " 2 - apostrofy 2
FITS_RECORD = 80
_FITS_VALUE_START = 10    # nazwa (8) + wskaźnik wartości "= " (2)
_FITS_FIXED_FIELD = 20    # stały format (§4.2): pole wartości zajmuje co najmniej kolumny 11-30
_FITS_COMMENT_SEP = 3     # " / "


@dataclasses.dataclass(frozen=True)
class CardViolation:
    """Naruszenie reguł karty wniesione przez łatę. `reason` idzie do raportu pisarza i do powodu
    pominięcia w podglądzie makra; `kind` ('name' | 'chars' | 'length') oraz `length`/`limit`
    służą powierzchniom, które mówią własnym językiem (i18n dialogu naprawy nagłówka)."""
    kind: str
    reason: str
    length: int | None = None
    limit: int | None = None


def _first_illegal(text):
    """Pierwszy znak spoza drukowalnego ASCII (0x20-0x7E) albo `None`. FITS 4.0 dopuszcza w wartości
    tekstowej (§4.2.1.1) i w komentarzu (§4.1.2.3) wyłącznie ten zbiór; XML 1.0 jest od niego
    szerszy, więc zbiór FITS domyka też legalność nagłówka XISF."""
    return next((ch for ch in text if not " " <= ch <= "~"), None)


def card_violation(keyword, value, comment=None, *, new_card=False) -> CardViolation | None:
    """Czy karta `keyword = value / comment` łamie reguły FITS 4.0 → `CardViolation` albo `None`.

    Trzy reguły, w tej kolejności:
    1. **Nazwa** (tylko `new_card=True`, bo tylko nowa karta wnosi nazwę): po `strip().upper()` -
       tak ją zapisują oba pisarze - do 8 znaków `A-Z 0-9 _ -`.
    2. **Znaki** wartości i komentarza: drukowalne ASCII 0x20-0x7E. Znak sterujący w XISF łamie też
       XML 1.0, i to bez ratunku: nie ma go jak zakodować (`scan._escape_xml`).
    3. **Długość** - karta mieści się w JEDNYM rekordzie 80 znaków. Wartość liczona jak tekst
       w apostrofach z podwojonym apostrofem wewnątrz (tak ją zapisuje FITS i `scan.quote_fits`),
       limit `FITS_STRING_MAX`; dla liczby limit jest o dwa znaki luźniejszy, a liczba tej długości
       nie istnieje, więc reguła jest jedna. Dłuższa wartość wymagałaby kontynuacji CONTINUE (astropy
       robi ją po cichu), a XISF-owy `<FITSKeyword>` nie ma rekordów, na które mógłby się rozpaść.
       Komentarz mieści się w reszcie rekordu po ` / ` przy polu wartości STAŁEGO formatu
       (co najmniej 20 znaków) - tak kartę układa astropy, więc dla FITS reguła jest dokładna
       (poza nią astropy ucina komentarz po cichu), a dla XISF ostrożna. Liczymy komentarz
       WNOSZONY przez łatę; zastany komentarz karty przy `set` bez komentarza zostaje poza regułą
       treści - XISF go nie rusza, a utratę zastanego komentarza przy przełożeniu karty FITS
       łapie sam pisarz FITS na złożonej karcie (`writeback._fits_comment_loss`, AR-7).

    Wartość sprawdzamy w postaci TEKSTOWEJ (`str(value)`) - dokładnie tej, która stoi w stagingu
    i którą pisarz XISF wstawia do pliku."""
    name = str(keyword).strip().upper()
    comment = None if comment is None else str(comment)
    if new_card and not _FITS_NAME.fullmatch(name):
        return CardViolation(
            "name", f"nazwa karty {name!r} łamie reguły FITS 4.0 - do 8 znaków spośród A-Z, 0-9, "
                    f"'_' i '-'")
    text = str(value)
    for pole, tresc in (("wartość", text), ("komentarz", comment)):
        znak = _first_illegal(tresc) if tresc is not None else None
        if znak is not None:
            return CardViolation(
                "chars", f"{pole} karty {name} ma znak {znak!r} spoza drukowalnego ASCII - karta "
                         f"FITS go nie przyjmie, a w nagłówku XISF łamie XML 1.0")
    pole_wartosci = len(text.replace("'", "''"))
    if pole_wartosci > FITS_STRING_MAX:
        return CardViolation(
            "length", f"wartość karty {name} ma {pole_wartosci} znaków, a jeden rekord FITS mieści "
                      f"{FITS_STRING_MAX}", length=pole_wartosci, limit=FITS_STRING_MAX)
    if comment:
        limit = (FITS_RECORD - _FITS_VALUE_START - _FITS_COMMENT_SEP
                 - max(pole_wartosci + 2, _FITS_FIXED_FIELD))
        if len(comment) > limit:
            return CardViolation(
                "length", f"komentarz karty {name} ma {len(comment)} znaków, a przy tej wartości "
                          f"rekord FITS mieści {max(limit, 0)}", length=len(comment),
                limit=max(limit, 0))
    return None
