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

JEDNA REGUŁA PLIKU: suma kontrolna (FITS 4.0, dodatek J). Zmiana bajtu nagłówka unieważnia
`CHECKSUM`, a pisarz jej nie przelicza, więc odmawia FITS z kartą `CHECKSUM`/`DATASUM` na OBU
drogach zapisu (`writeback._odmowa_sumy`, z nazwami kart z pliku). Tę samą odmowę przed zapisem
przewiduje z faktów bazy `bramka_sumy` - jedno zdanie (`BRAMKA_SUMY`) dla podglądu makra, edycji
komórki, planu naprawy nagłówków i bramki okien kart (`gui.queries.fits_checksum_gate`, AR-167).
"""

from __future__ import annotations

import dataclasses
import math
import re

from .item_reasons import PowodPozycji     # powód z kodem (AR-158) - liść bez astropy

_FITS_NAME = re.compile(r"[A-Z0-9_-]{1,8}")   # §4.1.2.1: do 8 znaków z tego zbioru
FITS_STRING_MAX = 68      # tekst w apostrofach w JEDNYM rekordzie: 80 - nazwa 8 - "= " 2 - apostrofy 2
FITS_RECORD = 80
_FITS_VALUE_START = 10    # nazwa (8) + wskaźnik wartości "= " (2)
_FITS_FIXED_FIELD = 20    # stały format (§4.2): pole wartości zajmuje co najmniej kolumny 11-30
_FITS_COMMENT_SEP = 3     # " / "

# Bramka sumy kontrolnej z faktów bazy (AR-166, AR-167): baza wie TYLKO, że klatka ma kartę sumy
# (`n_sum`), nie którą - stąd „CHECKSUM/DATASUM”; pisarz, który widzi plik, mówi nazwy kart.
BRAMKA_SUMY = PowodPozycji("FITS z sumą kontrolną (CHECKSUM/DATASUM)", "fits_checksum")


def bramka_sumy(filetype, n_sum):
    """`BRAMKA_SUMY`, gdy FITS ma kartę `CHECKSUM`/`DATASUM` (`n_sum` - liczba albo prawdziwość
    z read-modelu), inaczej None. XISF nie odpada: pisarz XISF sumy FITS nie pilnuje."""
    return BRAMKA_SUMY if filetype == "fits" and n_sum else None


@dataclasses.dataclass(frozen=True)
class CardViolation:
    """Naruszenie reguł karty wniesione przez łatę. `reason` idzie do raportu pisarza i do powodu
    pominięcia w podglądzie makra - zdanie PL jak dotąd, a od AR-158 `PowodPozycji` z kodem
    (`card_*`), więc okno zapisu mówi je w języku UI (`writeback._ops_violation`). Parametry
    naruszenia jako pola - dla powierzchni, które mówią własnym językiem (i18n dialogu naprawy
    nagłówka): `kind` ('name' | 'chars' | 'length'), `field` - które pole karty łamie regułę
    ('name' | 'value' | 'comment'), `char` - pierwszy znak spoza zbioru, `length`/`limit`."""
    kind: str
    reason: str
    length: int | None = None
    limit: int | None = None
    field: str | None = None
    char: str | None = None


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
            "name", PowodPozycji(f"nazwa karty {repr(name)} łamie reguły FITS 4.0 - do 8 znaków "
                                 f"spośród A-Z, 0-9, '_' i '-'", "card_name", name=repr(name)),
            field="name")
    text = str(value)
    znak = _first_illegal(text)
    if znak is not None:
        return CardViolation(
            "chars", PowodPozycji(f"wartość karty {name} ma znak {repr(znak)} spoza drukowalnego "
                                  f"ASCII - karta FITS go nie przyjmie, a w nagłówku XISF łamie "
                                  f"XML 1.0", "card_value_chars", keyword=name, char=repr(znak)),
            field="value", char=znak)
    znak = _first_illegal(comment) if comment is not None else None
    if znak is not None:
        return CardViolation(
            "chars", PowodPozycji(f"komentarz karty {name} ma znak {repr(znak)} spoza drukowalnego "
                                  f"ASCII - karta FITS go nie przyjmie, a w nagłówku XISF łamie "
                                  f"XML 1.0", "card_comment_chars", keyword=name, char=repr(znak)),
            field="comment", char=znak)
    pole_wartosci = len(text.replace("'", "''"))
    if pole_wartosci > FITS_STRING_MAX:
        return CardViolation(
            "length", PowodPozycji(f"wartość karty {name} ma {pole_wartosci} znaków, a jeden rekord "
                                   f"FITS mieści {FITS_STRING_MAX}", "card_value_long",
                                   keyword=name, length=pole_wartosci, limit=FITS_STRING_MAX),
            length=pole_wartosci, limit=FITS_STRING_MAX, field="value")
    if comment:
        limit = (FITS_RECORD - _FITS_VALUE_START - _FITS_COMMENT_SEP
                 - max(pole_wartosci + 2, _FITS_FIXED_FIELD))
        if len(comment) > limit:
            return CardViolation(
                "length", PowodPozycji(f"komentarz karty {name} ma {len(comment)} znaków, a przy tej "
                                       f"wartości rekord FITS mieści {max(limit, 0)}",
                                       "card_comment_long", keyword=name, length=len(comment),
                                       limit=max(limit, 0)),
                length=len(comment), limit=max(limit, 0), field="comment")
    return None


# ============================================================ LICZBA KARTY (AR-269)
# Dwie reguły wartości LICZBOWEJ, z jednym zdaniem dla podglądu makra (`macro`) i pisarza
# (`writeback._apply_op`, `_xisf_patches`):
# 1. Liczba NIESKOŃCZONA (`nan`, `inf`, `1e400`) - standard karty FITS jej nie zna (§4.2.4), astropy
#    odmawia angielskim `ValueError` (dawniej 'failed' prozą), a pisarz XISF wpisywał ją tekstem.
#    Sprawdzana na TEKŚCIE, zanim typ int zrobi z niej `macro_type_mismatch` - ta sama kolejność
#    w podglądzie i w pisarzu.
# 2. Liczba, której POLE karty FITS nie odtworzy: astropy układa float zmienionej karty w polu
#    20 znaków (`astropy/io/fits/card.py` `_format_float`: `str(v)` z wielką literą wykładnika,
#    dłuższe - ucięta mantysa), więc `-0.0012345678901234567` wraca jako inna liczba
#    `-0.00123456789012345`. „Ta sama liczba” = ten sam double po odczycie pola. Podgląd liczy to
#    lustrem (`pole_float_fits`, bez astropy), pisarz - prawdą astropy (obraz karty po łacie); test
#    pilnuje, że lustro i astropy mówią to samo. Wyłącznie FITS: pisarz XISF wpisuje tekst wartości.

FITS_FLOAT_FIELD = _FITS_FIXED_FIELD    # pole liczby karty FITS: 20 znaków (kolumny 11-30)
# Karty KOMENTARZOWE (zbiór jak astropy `Card._commentary_keywords` bez `END`): wartość to tekst od
# kolumny 9, bez pola liczby - astropy zapisuje liczbę jako `str` w pełnych cyfrach, więc reguła 2
# ich nie dotyczy (odczyt daje tekst, który nigdy nie równa się liczbie).
KARTY_KOMENTARZOWE = frozenset({"", "COMMENT", "HISTORY"})


def liczba_violation(keyword, value) -> PowodPozycji | None:
    """Powód `card_value_nonfinite`, gdy `value` (tekst stagingu albo liczba) czyta się jako liczba
    nieskończona, inaczej `None` - także dla tekstu, który liczbą nie jest (to reguła typu, nie
    tej funkcji). Wołający pyta wyłącznie dla wartości LICZBOWEJ: tekst `nan` w karcie tekstowej
    jest legalnym tekstem."""
    try:
        liczba = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isfinite(liczba):
        return None
    # Liczba po odczycie (`nan`, `inf`, `-inf`), nie tekst wejścia: `NaN` i `1e400` z pisarza mówią to
    # samo co wartość, którą podgląd już przeczytał jako liczbę.
    name, tekst = str(keyword).strip().upper(), str(liczba)
    return PowodPozycji(f"wartość karty {name} ({tekst}) nie jest liczbą skończoną - standard karty "
                        f"FITS (także w XISF) jej nie dopuszcza", "card_value_nonfinite",
                        keyword=name, value=tekst)


def pole_float_fits(value: float) -> str:
    """Tekst pola liczby, które astropy postawi w karcie FITS dla `value` - lustro `_format_float`
    (astropy 8.0): `str` z wielką literą wykładnika, dłuższy niż pole - mantysa ucięta tak, żeby
    wykładnik został; bez wykładnika - ucięcie do pola."""
    tekst = str(float(value)).replace("e", "E")
    if len(tekst) > FITS_FLOAT_FIELD:
        e = tekst.find("E")
        tekst = (tekst[:FITS_FLOAT_FIELD] if e < 0
                 else tekst[:FITS_FLOAT_FIELD - (len(tekst) - e)] + tekst[e:])
    return tekst


def powod_cyfr(keyword, value: float) -> PowodPozycji:
    """Zdanie `card_value_digits` - jedno dla podglądu i pisarza FITS: liczba i to, co da pole."""
    name, tekst, pole = str(keyword).strip().upper(), repr(float(value)), pole_float_fits(value)
    return PowodPozycji(f"wartość karty {name} {tekst} nie mieści się w polu liczby karty FITS "
                        f"(20 znaków) - zapis dałby {pole}, inną liczbę; zaokrąglij wartość",
                        "card_value_digits", keyword=name, value=tekst, derived=pole)


def cyfry_violation(keyword, value: float, zastana_typ=None, zastana_raw=None) -> PowodPozycji | None:
    """PODGLĄD reguły 2 dla karty FITS typu float: `powod_cyfr`, gdy pole nie odtworzy `value`.
    `zastana_*` = typ i tekst wartości wystąpienia, które zapis zmienia (`None` przy `add`): float
    równy zastanemu floatowi astropy zostawia w zastanym formacie (karty nie przekłada), więc
    liczba nie ginie - jak w pisarzu, który pyta obraz karty. Karta komentarzowa - poza regułą."""
    if str(keyword).strip().upper() in KARTY_KOMENTARZOWE:
        return None
    if zastana_typ == "float" and zastana_raw is not None:
        try:
            if float(zastana_raw) == float(value):
                return None
        except (TypeError, ValueError):
            pass
    if float(pole_float_fits(value)) == float(value):
        return None
    return powod_cyfr(keyword, value)
