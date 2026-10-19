"""Kontrola NIEZALEŻNA pilotażu zapisu w miejscu (O5) - poza pisarzem, poza bazą (astra Z9/Z16).

Weryfikacja pisarza (`writeback._verify_inplace`) to odczyt KLIENTA: osobny uchwyt tej samej
maszyny, który może przyjść z pamięci podręcznej systemu. Ten skrypt daje kontrolę, której pisarz
dać nie może: pełną kopię lokalną każdego pliku pilotażu sprzed zapisu i porównanie CAŁEGO pliku po
zapisie z PLANEM. Niezależność od pamięci podręcznej daje dopiero uruchomienie `po` z drugiego
komputera albo po restarcie - sam skrypt tego nie dowodzi.

Kontrola nie woła funkcji pisarza, które składają kartę albo region - oczekiwany wynik wyznacza
sama z kopii i planu. Z `writeback` bierze wyłącznie blokadę (`_exclusive`) do pomiaru `blokada`.

Tryby (pliki pilotażu czytane WYŁĄCZNIE do odczytu):

  przed KATALOG_KOPII PLAN.json KATALOG_TESTOWY
      PLAN.json = lista pozycji `{"plik", "po"?, "keyword", "value", "comment", "op"}` (AR-156):
      `op` = `set` (podmiana istniejącej karty `keyword`), `add` (dopisanie karty, której kopia NIE
      MA) albo `none` (plik bez zmiany treści: po zapisie CAŁY plik bajt w bajt jak kopia - RAW
      albo karta już w formie); `comment` null = bez komentarza, a przy `set` - komentarz zastany.
      Skrót PLANU sprzed AR-156: `{"plik", "object": X}` ≡ `OBJECT` `set` X bez komentarza,
      `"object": null` ≡ `none`; pozycja z oboma kształtami naraz to odmowa (manifest skrótu nie
      zna - jego wpis ma zawsze pełny kształt). Klucze kształtu są obowiązkowe - brak to literówka
      planu, nie „bez karty”. Ścieżki `plik` i `po` BEZWZGLĘDNE - plan czyta ponownie `po`, w innym
      procesie i innym katalogu bieżącym (AR-165). Keyword: FITS - dowolna karta tekstowa (`OBJECT`
      gestu „Zmień obiekt…”, `FILTER` naprawy `header-fix`); karta liczbowa i logiczna - JAWNIE poza
      pilotażem (plan niesie wartość tekstem, `set` na niej → odmowa); XISF - `set` wyłącznie
      `OBJECT` bez komentarza (model wycinków XML niżej), `add` dowolnej karty, z komentarzem albo
      bez (model wstawki niżej). `add` przy kopii, która kartę już ma, `set` przy kopii bez karty,
      `set`, który niczego nie zmienia (ta sama wartość i komentarz - pilotaż nic by nie sprawdził;
      od tego jest `none`), `add` karty `OBJECT` klatce kalibracyjnej (`IMAGETYP` dark/flat/bias
      i mastery),
      XISF bez obrazu-attachmentu albo z niekompletnym wypełnieniem, karta XISF spoza drukowalnego
      ASCII albo dłuższa niż jeden rekord 80 znaków i `add`, którego model niżej nie umie dopisać
      W MIEJSCU (brak zapasu za `END`, brak rezerwy nagłówka XISF, brak wzorca karty) → odmowa,
      zanim powstanie jakakolwiek kopia. Opcjonalne `"po": ścieżka` - PARA
      ŚCIEŻEK gestu „Zmień obiekt…” (AR-17 krok 3): `plik` = ścieżka przed przeniesieniem, `po` =
      ścieżka po nim (jeden `os.rename` zmienia folder i nazwę). Opcjonalne `"wydanie": ścieżka`
      (AR-189) - DOWIĄZANIE TWARDE pliku w wydaniu (`_WBPP`): ścieżka bezwzględna, inna niż `plik`
      i `po` (`normcase`), z tą samą tożsamością z uchwytu co `plik` - inaczej odmowa. Liczby dowiązań
      udział SMB nie podaje (1 także dla pliku z dowiązaniem - zmierzone 584/584 na `R:`), więc
      dowodem jest tożsamość. Tożsamość każdego pliku z UCHWYTU
      (`GetFileInformationByHandle`: wolumin + indeks pliku, AR-165; poza Windows odmowa) - zero
      w woluminie, indeksie albo `st_ino` → odmowa. Przed pierwszą kopią pomiar `blokada` (niżej) na
      KATALOG_TESTOWY - katalogu testowym udziału pilotażu, poza archiwum, z WYŁĄCZNIE plikami
      `horreum_proba_*`: cudzy plik, którykolwiek wynik „NIE”, inny korzeń ścieżki (litera dysku albo
      `\\\\serwer\\udział`) albo wolumin niż plików planu → odmowa (blokadę mierzymy tam, gdzie pisze
      pisarz). Pełna kopia każdego pliku do KATALOG_KOPII (lokalny dysk; katalog na woluminie plików
      planu → odmowa), tworzona wyłącznie jako NOWY plik; manifest.json w schemacie 3 (zamkniętym;
      schemat 2 = 3 bez `wydanie`):
      kotwica planu (ścieżka i sha1 pliku PLAN.json), środowisko (`sys.version`, nazwa komputera),
      wynik pomiaru blokady, a per pozycja sha1 oryginału i kopii (muszą
      być równe), rozmiar, `st_ino`, tożsamość z uchwytu, granice nagłówka, karty, pełny kształt
      pozycji i ścieżka wydania (albo null) - zapisany atomowo dopiero po skopiowaniu i sprawdzeniu
      wszystkich plików. Katalog
      z manifestem albo z plikiem kopii (`NNNN.*`) → odmowa: kopie sprzed zapisu są jedynym
      materiałem porównania i nie wolno ich nadpisać.
  po KATALOG_KOPII PLAN.json
      manifest w schemacie 3 albo 2 - każdy własnym zamkniętym zbiorem kluczy, wpis schematu 2 to
      pozycja bez wydania (manifest sprzed AR-165 → NIE z powodem - kontrola nie zgaduje), obcy
      albo brakujący klucz i typ spoza schematu → NIE; KOTWICA LICZBY POZYCJI poza manifestem =
      plik planu: sha1 PLAN.json równy zapisanemu przy `przed`, pozycje planu = wpisy manifestu
      (liczba, kolejność, ścieżki, kształt), kopie w katalogu = wpisy. Potem dla każdego pliku (przy
      parze: pod ścieżką `po`, a pod starą nie ma już nic - rename zachowuje tożsamość, zmierzone na
      `R:`): kopia nietknięta (sha1), rozmiar, `st_ino` i tożsamość z uchwytu bez zmian (inna przy
      `add` = plik przepisany w całości drogą atomową, nie dopisany w miejscu; `st_ino` porównany
      tylko w tym samym Pythonie co `przed`, inaczej obie wartości w uwagach raportu), a CAŁY plik
      równy plikowi oczekiwanemu, wyznaczonemu z kopii i planu:
        FITS `set` - wszystkie bajty identyczne z kopią poza jednym 80-bajtowym rekordem karty
          `keyword[0]` w jej położeniu z kopii (pierwszy rekord tej karty w regionie
          `[hdrLoc, datLoc)` wybranego HDU); ten rekord to karta `keyword` o wartości z planu
          i komentarzu z planu (null = komentarz z kopii).
        FITS `add` - bajty poza regionem identyczne z kopią, a region = region kopii po dopisaniu
          wg reguły pisarza, wyznaczony WŁASNYM modelem na rekordach kopii (bez `Header` astropy):
          karty kopii do ostatniej karty zwykłej bez zmian, potem rekord nowej karty (wartość
          i komentarz z planu, null = bez komentarza), potem końcowy blok kart komentarzowych
          (COMMENT/HISTORY/nazwa pusta) kopii przesunięty o rekord; pusta karta z końca zużyta
          (`END` na miejscu), a gdy jej nie ma - `END` o rekord niżej, w wolny rekord za `END`
          kopii; reszta regionu jak w kopii. Plik bez obu zapasów odpada już w `przed` (ten sam
          model, AR-165); kopia bez nich w `po` → NIE (pisarz nie dopisze w miejscu).
        XISF `set` - bajty od `first_attachment` do końca identyczne z kopią; w regionie
          `[0, first_attachment)`: sygnatura i `reserved` z kopii, pole długości wskazuje XML
          mieszczący się w regionie, XML równy XML-owi kopii poza DWIEMA wartościami, które
          pisarz ma prawo zmienić (niżej), a wypełnienie od końca XML-a do `first_attachment`
          dokładnie takie, jakie składa pisarz: wydłużenie XML-a o d bajtów zjada pierwsze
          d bajtów wypełnienia kopii, skrócenie o d dokłada d zer przed wypełnieniem kopii.
          XML porównany dwiema drogami: bajtowo poza wycinkami dwóch dozwolonych wartości
          (łapie kolejność atrybutów, cudzysłowy, białe znaki w znacznikach, komentarze XML)
          i strukturalnie (drzewo elementów z komentarzami, atrybuty, tekst, kolejność).
          Dozwolone wartości: atrybut `value` pierwszego `<FITSKeyword name="OBJECT">` (ma dać
          formę z planu po zdjęciu apostrofów FITS) oraz wartość własności
          `<Property id="Observation:Object:Name">` (atrybut `value` albo tekst elementu) -
          pisarz ją łata razem z kartą, gdy plik ją ma, żeby plik nie przeczył sam sobie; gdy
          kopia ją ma, po zapisie MUSI być równa formie. Komentarz karty zmienić się nie może.
        XISF `add` - bajty od `first_attachment` do końca identyczne z kopią, a region
          `[0, first_attachment)` = region kopii po dopisaniu wg reguły pisarza, wyznaczony WŁASNYM
          modelem na bajtach XML-a kopii (AR-165): nowa karta = kopia CAŁEGO elementu wzorca
          (ostatnia karta z wartością w apostrofach FITS, z zamknięciem, jeśli je ma) z podmienionymi
          `name` (karta z planu), `value` (wartość z planu w apostrofach, apostrof wewnątrz
          podwojony, escape `&` `<` `"`) i `comment` (komentarz z planu, null = pusty), wstawiona za
          KOŃCEM elementu OSTATNIEJ karty kopii, poprzedzona jej wcięciem (białe znaki tuż przed
          nią); pole długości wskazuje nowy XML, sygnatura i `reserved` z kopii, wypełnienie wg
          reguły pisarza jak przy `set`. Druga droga, bez modelu bajtowego: drzewo XML po zapisie =
          drzewo kopii + jeden element karty z planu, rodzeństwo ostatniej karty, zaraz za nią.
      Niezależnie od różnic: czytnik skanu widzi po zapisie `keyword[0]` = wartość z planu,
      z komentarzem z planu (przy `set` z komentarzem null - sprzed), a przy `add` karty przed
      zapisem nie było - brak wykonania zmiany to NIE, nie „zero różnic". Pozycja z wydaniem:
      tożsamość z uchwytu ścieżki wydania == tożsamość pliku po zapisie, inaczej NIE „dowiązanie
      wydania zerwane” (plik przepisany w całości ma nowy węzeł, wydanie zostaje przy starej treści).
      Kod wyjścia 1 przy którymkolwiek NIE.
  po-undo KATALOG_KOPII PLAN.json
      manifest i kotwica planu jak w `po`; po cofnięciu pilotażu: sha1 CAŁEGO pliku == sha1 sprzed
      pilotażu, ten sam rozmiar, `st_ino` i tożsamość z uchwytu - pod ścieżką `plik` (przed); przy
      parze pod ścieżką `po` nie ma już nic; wydanie - ta sama tożsamość co `plik`.
  blokada KATALOG_TESTOWY
      pomiar blokady `writeback._exclusive` na udziale: tworzy WŁASNE pliki testowe (unikalna nazwa,
      tworzenie wyłączne `xb`), trzyma blokadę i sprawdza, że zapis z INNEGO procesu, drugie
      otwarcie do zapisu, usunięcie i `os.replace` na plik są odrzucane, a odczyt działa; że
      tożsamość z uchwytu jest stabilna, a `os.replace` na świeżej parze własnych plików ją
      ZMIENIA (tym `po` rozpoznaje drogę atomową - AR-165; do 3 prób co 0,5 s przy odmowie
      dostępu, każda próba w wynikach); sprząta wyłącznie swoje pliki. Odmawia drzewa archiwum
      `R:\\ASTRO_`.

Wynik na stdout (ASCII), manifest i raport JSON w KATALOG_KOPII."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import struct
import subprocess
import sys
import time
import uuid
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from horreum import scan, writeback  # noqa: E402
from horreum.item_reasons import blad_windows  # noqa: E402
from horreum.resolve.frames import LIGHT_KINDS, normalize_kind  # noqa: E402

ARCHIWUM = "R:\\ASTRO_"
MANIFEST = "manifest.json"
_KOPIA = re.compile(r"^\d{4}\.")                     # nazwa pliku kopii: numer pozycji planu

_FITS_REKORD = 80
_FITS_END = b"END" + b" " * 77
_FITS_PUSTY = b" " * _FITS_REKORD                     # pusta karta albo wolny rekord za END
# Karty komentarzowe (nazwa COMMENT, HISTORY albo pusta): za nimi dopisywana karta NIE staje.
_FITS_KOMENTARZOWE = (b"COMMENT ", b"HISTORY ", b" " * 8)
_FITS_NAZWA = re.compile(r"[A-Z0-9_-]{1,8}")
_XISF_SYGNATURA = b"XISF0100"
_XISF_XML = 16                                       # sygnatura 8 B + długość 4 B + reserved 4 B
_WLASNOSC_OBIEKTU = "Observation:Object:Name"

# Znaczniki XML jako tokeny: komentarz, CDATA i instrukcja/deklaracja w całości (ich treść nie jest
# znacznikiem), a znacznik elementu z atrybutami w cudzysłowach - `>` w wartości nie kończy znacznika.
_ZNACZNIK = re.compile(
    rb"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<[?!].*?>"
    rb"|<(/?)([A-Za-z_:][\w:.\-]*)((?:\s+[A-Za-z_:][\w:.\-]*\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>",
    re.S)
_ATRYBUT = re.compile(rb"([A-Za-z_:][\w:.\-]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")


def _a(tekst):
    """Tekst do wyjścia ASCII (konsola Windows) - znaki spoza ASCII jako sekwencje `\\x..`."""
    return str(tekst).encode("ascii", "backslashreplace").decode("ascii")


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for kawalek in iter(lambda: fh.read(1 << 20), b""):
            h.update(kawalek)
    return h.hexdigest()


def _jest_xisf(path):
    return os.path.splitext(path)[1].lower() in scan.XISF_SUFFIXES


def _tozsamosc(path):
    """Tożsamość pliku z UCHWYTU (AR-165): `{"wolumin", "indeks"}` z `GetFileInformationByHandle` -
    `dwVolumeSerialNumber` i `nFileIndexHigh/Low` struktury `BY_HANDLE_FILE_INFORMATION`; numer
    woluminu z identyfikatorem pliku jednoznacznie wskazują plik na jednym komputerze (dokumentacja
    Microsoft). Uchwyt WYŁĄCZNIE do odczytu atrybutów (`FILE_READ_ATTRIBUTES`) z pełnym
    współdzieleniem - treści nie czyta, a tryb współdzielenia nie dotyczy dostępu do atrybutów,
    więc nie koliduje z blokadą pisarza (zmierzone na NTFS w obie strony). Także katalog
    (`FILE_FLAG_BACKUP_SEMANTICS`) - wolumin katalogu kopii.

    Własny odczyt, nie `st_ino`: skąd `os.stat` bierze `st_ino`, to szczegół CPython (3.12 przeszło
    na identyfikator 128-bitowy `FileIdInfo`), a woluminu `st_ino` nie niesie. Przez sieć API może
    oddać informację niepełną - zero sprawdza wołający. Poza Windows `OSError`: jawna odmowa, nie
    cichy spadek na `st_ino`."""
    if sys.platform != "win32":
        raise OSError("tozsamosc pliku z uchwytu wymaga Windows (GetFileInformationByHandle) - "
                      "kontrola nie spada po cichu na st_ino")
    import ctypes
    from ctypes import wintypes

    class _Informacja(ctypes.Structure):        # BY_HANDLE_FILE_INFORMATION, kolejność z fileapi.h
        _fields_ = [("dwFileAttributes", wintypes.DWORD), ("ftCreationTime", wintypes.FILETIME),
                    ("ftLastAccessTime", wintypes.FILETIME), ("ftLastWriteTime", wintypes.FILETIME),
                    ("dwVolumeSerialNumber", wintypes.DWORD), ("nFileSizeHigh", wintypes.DWORD),
                    ("nFileSizeLow", wintypes.DWORD), ("nNumberOfLinks", wintypes.DWORD),
                    ("nFileIndexHigh", wintypes.DWORD), ("nFileIndexLow", wintypes.DWORD)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k32.GetFileInformationByHandle.restype = wintypes.BOOL
    k32.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Informacja))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    czytaj_atrybuty, wspoldziel_wszystko, otworz_istniejacy = 0x80, 0x7, 3
    takze_katalog = 0x02000000                               # FILE_FLAG_BACKUP_SEMANTICS
    uchwyt = k32.CreateFileW(os.fspath(path), czytaj_atrybuty, wspoldziel_wszystko, None,
                             otworz_istniejacy, takze_katalog, None)
    # Błąd z kodem Windows i ŚCIEŻKĄ (`blad_windows`, AR-259) - `ctypes.WinError` jej nie niósł.
    if uchwyt in (None, wintypes.HANDLE(-1).value):
        raise blad_windows(ctypes.get_last_error(), os.fspath(path))
    try:
        info = _Informacja()
        if not k32.GetFileInformationByHandle(uchwyt, ctypes.byref(info)):
            raise blad_windows(ctypes.get_last_error(), os.fspath(path))
    finally:
        k32.CloseHandle(uchwyt)
    return {"wolumin": info.dwVolumeSerialNumber,
            "indeks": (info.nFileIndexHigh << 32) | info.nFileIndexLow}


def _granice(path):
    """(początek, koniec) regionu nagłówka, który wolno zmienić: FITS `[hdrLoc, datLoc)` wybranego
    HDU, XISF `[0, first_attachment)`."""
    if _jest_xisf(path):
        return 0, scan.read_xisf_meta_full(path).first_attachment
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        index, _ = scan._select_hdu(hdul)
        info = hdul.fileinfo(index)
        return info["hdrLoc"], info["datLoc"]


def _karty(path):
    rec = scan.scan_file(path)
    return {f"{c.keyword}[{c.idx}]": [c.value_raw, c.comment] for c in (rec.cards or [])}, rec.error


# ============================================================ kształt pozycji (AR-156)


_OPERACJE = ("set", "add", "none")
_KSZTALT = ("keyword", "value", "comment", "op")


def _pozycja(p):
    """Pozycja planu albo wpis manifestu w pełnym kształcie `{keyword, value, comment, op}`.

    Skrót sprzed AR-156: `"object": X` ≡ `OBJECT` `set` X bez komentarza, `"object": null` ≡
    `none` - wyłącznie w PLANIE; wpis manifestu ma klucz `object` za obcy (schemat zamknięty
    `_manifest`, AR-165), więc tu dociera zawsze w pełnym kształcie. `ValueError` z powodem: oba
    kształty naraz, brak klucza kształtu, nieznana operacja, typ spoza kontraktu - literówka planu
    nie przechodzi jako „bez karty”."""
    stary, nowe = "object" in p, [k for k in _KSZTALT if k in p]
    if stary and nowe:
        raise ValueError(f"pozycja ma naraz 'object' i pelny ksztalt ({', '.join(nowe)})")
    if stary:
        forma = p["object"]
        if forma is None:
            return {"keyword": None, "value": None, "comment": None, "op": "none"}
        if not isinstance(forma, str):
            raise ValueError("'object' nie jest tekstem ani null")
        return {"keyword": "OBJECT", "value": forma, "comment": None, "op": "set"}
    if len(nowe) != len(_KSZTALT):
        brak = sorted(set(_KSZTALT) - set(nowe))
        raise ValueError(f"brak kluczy {', '.join(brak)} (ani skrotu 'object')")
    if p["op"] not in _OPERACJE:
        raise ValueError(f"op {p['op']!r} spoza {'/'.join(_OPERACJE)}")
    if p["op"] == "none":
        return {"keyword": None, "value": None, "comment": None, "op": "none"}
    kw, wartosc, komentarz = p["keyword"], p["value"], p["comment"]
    if not (isinstance(kw, str) and kw.strip() and isinstance(wartosc, str)
            and (komentarz is None or isinstance(komentarz, str))):
        raise ValueError("keyword i value musza byc tekstem, comment tekstem albo null")
    return {"keyword": kw.strip().upper(), "value": wartosc, "comment": komentarz, "op": p["op"]}


_KLUCZE_STARE = frozenset({"plik", "object"})          # skrót sprzed AR-156
_KLUCZE_NOWE = frozenset({"plik", *_KSZTALT})
_KLUCZ_PARY = "po"                                     # opcjonalny w obu kształtach
_KLUCZ_WYDANIA = "wydanie"                             # opcjonalny w obu kształtach (AR-189)


def _pozycja_planu(p):
    """`(plik, po, wydanie, kształt)` pozycji planu - schemat ZAMKNIĘTY: obiekt JSON z kluczami
    dokładnie jednego kształtu (+ opcjonalne `po` i `wydanie`), `plik` niepustym tekstem, `po`
    i `wydanie` tekstem albo null. Obcy klucz (literówka `coment`, `poo`) → `ValueError` z jego
    nazwą, nie cicha wartość domyślna. Ścieżka względna → `ValueError`: plan czyta też `po` (kotwica
    pozycji, AR-165), w innym procesie i katalogu bieżącym - ta sama względna ścieżka wskazałaby tam
    inny plik. `wydanie` (AR-189) = dowiązanie twarde pliku w wydaniu - ścieżka INNA niż `plik` i `po`
    (`normcase`): wydanie równe plikowi porównałoby po zapisie plik z nim samym i nie złapałoby
    zerwania."""
    if not isinstance(p, dict):
        raise ValueError(f"pozycja nie jest obiektem JSON ({type(p).__name__})")
    obce = sorted(set(p) - _KLUCZE_STARE - _KLUCZE_NOWE - {_KLUCZ_PARY, _KLUCZ_WYDANIA})
    if obce:
        raise ValueError(f"obce klucze {', '.join(map(repr, obce))}")
    if not isinstance(p.get("plik"), str) or not p["plik"]:
        raise ValueError("'plik' nie jest niepustym tekstem")
    for klucz in (_KLUCZ_PARY, _KLUCZ_WYDANIA):
        if p.get(klucz) is not None and (not isinstance(p[klucz], str) or not p[klucz]):
            raise ValueError(f"'{klucz}' nie jest niepustym tekstem ani null")
    wzgledne = [k for k in ("plik", _KLUCZ_PARY, _KLUCZ_WYDANIA)
                if p.get(k) and not os.path.isabs(p[k])]
    if wzgledne:
        raise ValueError(f"sciezka wzgledna w {', '.join(map(repr, wzgledne))} - plan nosi sciezki "
                         f"bezwzgledne (po czyta go w innym procesie i katalogu biezacym)")
    po, wydanie = p.get(_KLUCZ_PARY), p.get(_KLUCZ_WYDANIA)
    if wydanie and os.path.normcase(os.path.abspath(wydanie)) in {
            os.path.normcase(os.path.abspath(s)) for s in (p["plik"], po) if s}:
        raise ValueError("'wydanie' wskazuje ten sam plik co 'plik' albo 'po' - podaj sciezke "
                         "dowiazania w wydaniu (_WBPP), nie pliku archiwum")
    return (os.path.abspath(p["plik"]), os.path.abspath(po) if po else None,
            os.path.abspath(wydanie) if wydanie else None, _pozycja(p))


# Bramka kwalifikacji zapisu w miejscu - WŁASNY kod kontroli, nie import z pisarza (niezależność):
# karta, której pisarz w miejscu nie zapisze, nie może dostać od kontroli TAK. Karty specjalne
# (bez wartości albo z układem innym niż `keyword = 'tekst' / komentarz`), układu danych (zmiana
# zmieniłaby znaczenie bajtów danych) i sumy kontrolne (zmiana nagłówka unieważnia `CHECKSUM`).
_FITS_SPECJALNE = frozenset({"", "COMMENT", "HISTORY", "CONTINUE", "END"})
_FITS_UKLAD = frozenset({"SIMPLE", "XTENSION", "BITPIX", "NAXIS", "EXTEND", "PCOUNT", "GCOUNT",
                         "GROUPS", "BZERO", "BSCALE", "BLANK"})
_FITS_NAXIS_N = re.compile(r"NAXIS\d+")
_FITS_SUMY = ("CHECKSUM", "DATASUM")
# Karta XISF, którą PixInsight trzyma podwójnie - także jako `<Property>` (D-X-10). Plik z własnością,
# a bez karty: pisarz `add` MUSI odmówić (dopisana karta mogłaby własności zaprzeczyć). Własna kopia
# mapy pisarza - celowo, jak `_FITS_UKLAD`: kontrola nie bierze reguł od tego, kogo sprawdza.
_XISF_WLASNOSCI = {"OBJECT": "Observation:Object:Name", "TELESCOP": "Instrument:Telescope:Name",
                   "FOCALLEN": "Instrument:Telescope:FocalLength"}


def _karty_naglowka(path):
    """`[(keyword, wartość, komentarz)]` nagłówka (wybrane HDU FITS / karty XISF) - sam odczyt
    nagłówka, bez haszy całego pliku (bramka planu przed kopiowaniem)."""
    if _jest_xisf(path):
        return [(c.keyword, c.value_raw, c.comment) for c in scan.read_xisf_meta_full(path).cards]
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        _, hdu = scan._select_hdu(hdul)
        return [(c.keyword, c.value, c.comment) for c in hdu.header.cards]


def _karta_w_rekordzie(kw, wartosc, komentarz):
    """Powód, gdy karta z planu łamie reguły karty FITS 4.0, których pisarz pilnuje w OBU formatach
    (XISF przejmuje je wprost), albo `None`: znak spoza drukowalnego ASCII 0x20-0x7E w wartości albo
    komentarzu; karta nie mieści się w JEDNYM rekordzie 80 znaków - obraz `fits.Card` dłuższy niż
    rekord (wartość poszła w CONTINUE) albo karta odczytana z obrazu inna niż plan (za długi
    komentarz astropy ucina po cichu). Własny kod - reguł pisarza kontrola nie importuje."""
    for pole, tekst in (("wartosc", wartosc), ("komentarz", komentarz or "")):
        znak = next((ch for ch in tekst if not " " <= ch <= "~"), None)
        if znak is not None:
            return (f"{pole} karty {kw} ma znak {_a(repr(znak))} spoza drukowalnego ASCII - pisarz "
                    f"odmowi")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        obraz = fits.Card(kw, wartosc, komentarz or "").image
        karta = fits.Card.fromstring(obraz) if len(obraz) == _FITS_REKORD else None
    if (karta is None or karta.value != wartosc.rstrip()
            or karta.comment != (komentarz or "")):
        return f"karta {kw} z planu nie miesci sie w jednym rekordzie 80 znakow - pisarz odmowi"
    return None


def _xisf_odmowa(path, poz):
    """Bramka XISF przed kopią - to, czego pisarz XISF MUSI odmówić (bliźniaki `_xisf_gates`,
    `build_xisf_header_region` i drugiej bramki `_xisf_add_patch`), liczone własnym kodem: brak
    obrazu-attachmentu (tożsamość klatki nieobliczalna; obejmuje też plik bez żadnego bloku
    `attachment:`, którego granicy nagłówka nie ma - bez tej odmowy `po` padałby na granicy None),
    wypełnienie nagłówka niekompletne (plik przeczy sam sobie), karty pod więcej niż jednym
    `<Image>` (cel zapisu niejednoznaczny), `add` karty z `_XISF_WLASNOSCI`, gdy plik ma już jej
    własność. Powód albo `None`."""
    meta = scan.read_xisf_meta_full(path)
    if meta.image_span is None:
        return "XISF bez obrazu-attachmentu - tozsamosc klatki nieobliczalna, pisarz odmawia"
    if not meta.padding_complete:
        return "XISF z niekompletnym wypelnieniem naglowka - plik przeczy sam sobie, pisarz odmawia"
    korzen = ET.fromstring(scan.xml_parsable(meta.xml_bytes))
    obrazy = sum(1 for e in korzen.iter() if _lokalna(e.tag) == "Image"
                 and any(_lokalna(k.tag) == "FITSKeyword" for k in e.iter()))
    if obrazy > 1:
        return (f"XISF: karty pod {obrazy} elementami <Image> - cel zapisu niejednoznaczny, "
                f"pisarz odmawia")
    wlasnosc = _XISF_WLASNOSCI.get(poz["keyword"])
    if poz["op"] == "add" and wlasnosc is not None and any(
            _lokalna(e.tag) == "Property" and e.get("id") == wlasnosc for e in korzen.iter()):
        return (f"XISF: plik ma wlasnosc {wlasnosc}, a nie ma karty {poz['keyword']} - dopisana "
                f"karta moglaby jej zaprzeczyc, pisarz odmawia")
    return None


def _odmowa_pozycji(path, poz):
    """Powód, dla którego kontrola nie umie sprawdzić tej pozycji na tym pliku, albo `None`."""
    if poz["op"] == "none":
        return None
    kw = poz["keyword"]
    xisf = _jest_xisf(path)
    if xisf and poz["op"] == "set" and (kw, poz["comment"]) != ("OBJECT", None):
        # Model regionu XML przy `set` zna wyłącznie podmianę wartości karty OBJECT (i jej własności).
        return (f"XISF: kontrola zna 'set' wylacznie karty OBJECT bez komentarza, plan chce "
                f"'set' karty {kw}" + ("" if poz["comment"] is None else " z komentarzem"))
    if not xisf or poz["op"] == "add":
        # Nazwa nowej karty (XISF `add`) i każdej karty FITS. Przy XISF bramka ŚWIADOMIE węższa od
        # pisarza: kart specjalnych i układu danych kontrola w XISF nie modeluje (COMMENT/HISTORY
        # mają tam `value=""`, geometrię niesie atrybut `<Image>`).
        if not _FITS_NAZWA.fullmatch(kw):
            return f"nazwa karty FITS {kw!r} spoza 8 znakow A-Z 0-9 _ -"
        if kw in _FITS_SPECJALNE or kw in _FITS_UKLAD or _FITS_NAXIS_N.fullmatch(kw):
            return (f"karta {kw} specjalna albo ukladu danych - poza modelem kontroli (FITS: pisarz "
                    f"nie zapisze jej w miejscu)")
    if xisf:
        powod = _xisf_odmowa(path, poz) or _karta_w_rekordzie(kw, poz["value"], poz["comment"])
        if powod is not None:
            return powod
    karty = _karty_naglowka(path)
    if not xisf:
        sumy = [s for s in _FITS_SUMY if any(k == s for k, _, _ in karty)]
        if sumy:
            return (f"FITS z suma kontrolna ({', '.join(sumy)}) - zmiana naglowka ja uniewazni, "
                    f"pisarz odmawia")
    zastane = [(v, c) for k, v, c in karty if k == kw]
    wartosci = [v for v, _ in zastane]
    if poz["op"] == "add" and wartosci:
        return f"op 'add', a kopia ma juz karte {kw} - zmiana wartosci idzie przez 'set'"
    if poz["op"] == "set" and not wartosci:
        return f"op 'set', a kopia nie ma karty {kw} - dopisanie idzie przez 'add'"
    if poz["op"] == "set" and not xisf:
        if len(wartosci) != 1:
            return f"op 'set', a karta {kw} wystepuje {len(wartosci)} razy - pisarz wymaga jednej"
        if not isinstance(wartosci[0], str):
            # Karta liczbowa i logiczna (pisarz pisze ją w miejscu od AR-261) jest JAWNIE poza
            # pilotażem: plan niesie wartość tekstem, a model rekordu zna wyłącznie kartę tekstową.
            return (f"op 'set', a zastana wartosc {kw} nie jest tekstem ({_a(repr(wartosci[0]))}) - "
                    f"karta liczbowa i logiczna sa poza modelem kontroli (pilotaz wylacznie kart "
                    f"tekstowych)")
    if poz["op"] == "set":
        # Pozycja, która niczego nie zmienia, przeszłaby `po` bez żadnego zapisu - plik równy
        # kopii JEST plikiem oczekiwanym; „brak wykonania zmiany to NIE” wymaga zmiany w planie.
        wartosc, komentarz = zastane[0]
        if (isinstance(wartosc, str) and wartosc.rstrip() == poz["value"].rstrip()
                and poz["comment"] in (None, komentarz)):
            return (f"pozycja bez zmiany (karta {kw} ma juz te wartosc i komentarz) - pilotaz "
                    f"niczego nie sprawdzi; uzyj op 'none'")
    if poz["op"] == "add" and kw == "OBJECT":
        # Kalibracja nie ma obiektu nieba (oś rodzaju repo, `resolve.frames`): dopisany OBJECT
        # przypisałby masterowi dark/flat/bias obiekt, którego nie ma.
        imagetyp = next((v for k, v, _ in karty if k == "IMAGETYP"), None)
        rodzaj = normalize_kind(imagetyp)
        if rodzaj not in LIGHT_KINDS and rodzaj != "unknown":
            return (f"IMAGETYP {_a(repr(imagetyp))} = klatka kalibracyjna ({rodzaj}) - karty "
                    f"OBJECT kalibracji nie dopisujemy")
    if poz["op"] == "add":
        # Model dopisania (ten sam, którym `po` wyznacza plik oczekiwany) na nagłówku pliku przed
        # zapisem: brak zapasu, rezerwy albo wzorca karty = pisarz nie dopisze w miejscu (AR-165).
        region = _czytaj(path, *_granice(path))
        model = (_xisf_region_po_dopisaniu(region, poz) if xisf
                 else _fits_po_dopisaniu(region, poz))
        if model[0] is None:
            return f"model dopisania: {model[1]}"
    return None


# ============================================================ przed


def _katalog_zajety(katalog):
    """Nazwa pliku, przez który katalog NIE nadaje się na kopie (manifest, jego plik tymczasowy albo
    plik kopii), albo `None`."""
    if not katalog.exists():
        return None
    for x in sorted(katalog.iterdir()):
        if x.name in (MANIFEST, MANIFEST + ".tmp") or _KOPIA.match(x.name):
            return x.name
    return None


def _kopiuj(zrodlo, cel):
    """Kopia wyłącznie do NOWEGO pliku (`xb`) - istniejący plik to błąd, nie nadpisanie."""
    with open(zrodlo, "rb") as src, open(cel, "xb") as dst:
        for kawalek in iter(lambda: src.read(1 << 20), b""):
            dst.write(kawalek)
        dst.flush()
        os.fsync(dst.fileno())


def _tozsamosc_planu(p):
    """Powód odmowy, gdy plik nie ma tożsamości, po której `po` odróżni zapis w miejscu od
    atomowego, albo `None`. Dwie derywacje (AR-165): `st_ino` (`os.stat`) i tożsamość z uchwytu -
    zero w którejkolwiek to brak tożsamości (przez sieć API może oddać informację niepełną)."""
    if os.stat(p).st_ino == 0:
        return "st_ino == 0 - brak tozsamosci pliku, zapisu w miejscu nie da sie odroznic"
    t = _tozsamosc(p)
    if not (t["wolumin"] and t["indeks"]):
        return (f"tozsamosc z uchwytu niepelna (wolumin {t['wolumin']}, indeks {t['indeks']}) - "
                f"udzial nie podaje trwalego identyfikatora, zapisu w miejscu nie da sie odroznic")
    return None


def _odmowa_wydania(p, wydanie):
    """Powód odmowy pozycji z wydaniem (AR-189) albo `None`: wydanie ma być DOWIĄZANIEM TWARDYM pliku -
    ta sama tożsamość z uchwytu (wolumin + indeks). Liczba dowiązań tego nie rozstrzyga: udział SMB
    podaje 1 także dla pliku z dowiązaniem (zmierzone 584/584 na `R:`). Kopia zamiast dowiązania ma
    inną tożsamość - `po` nie miałoby czego porównać, więc odmowa przed pierwszą kopią."""
    if wydanie is None:
        return None
    if _tozsamosc(wydanie) != _tozsamosc(p):
        return (f"wydanie {_a(wydanie)} nie jest dowiazaniem twardym pliku (inna tozsamosc "
                f"z uchwytu: wolumin, indeks) - po nie sprawdzi, czy dowiazanie przezylo zapis")
    return None


def _wydanie_zerwane(w, plik):
    """Problem `po`/`po-undo` (AR-189) albo `None`: wydanie pozycji ma po zapisie tożsamość pliku
    `plik` - inna = plik przepisany w całości dostał nowy węzeł, a wydanie zostało przy starej treści."""
    if w["wydanie"] is None or _tozsamosc(w["wydanie"]) == _tozsamosc(plik):
        return None
    return (f"dowiazanie wydania zerwane - wydanie {_a(w['wydanie'])} zostalo przy starej tresci "
            f"(inna tozsamosc z uchwytu niz plik)")


_PROBA_PLIK = "horreum_proba_"                 # prefiks plików pomiaru `blokada`


def _korzen(sciezka):
    """Korzeń ścieżki bezwzględnej - litera dysku albo `\\\\serwer\\udział` - po `normcase`."""
    return os.path.normcase(os.path.splitdrive(os.path.abspath(sciezka))[0])


def _blokada_udzialu(katalog, pliki):
    """Pomiar `blokada` w katalogu testowym udziału pilotażu → wpis manifestu `{katalog, wolumin,
    kod, wyniki}` (w `wyniki` WYŁĄCZNIE wyniki tekstowe) albo odmowa (`SystemExit`).

    Katalog testowy zawiera wyłącznie pliki pomiaru (`horreum_proba_*`, także resztki biegu
    przerwanego) - cudzy plik, zwłaszcza FITS/XISF, to znak, że wskazano nie ten katalog. Porównujemy
    dwa fakty katalogu testowego z KAŻDYM plikiem planu: korzeń ścieżki (litera dysku albo
    `\\\\serwer\\udział`) i wolumin pliku testowego z uchwytu. Numer woluminu podaje serwer
    (udziały jednego serwera mogą go dzielić), a litera dysku sama nie mówi, dokąd prowadzi - razem
    wiążą pomiar z udziałem pilotażu tak mocno, jak te dwa fakty pozwalają, nie mocniej."""
    try:
        obce = sorted(x.name for x in Path(katalog).iterdir() if not x.name.startswith(_PROBA_PLIK))
    except OSError as exc:
        raise SystemExit(f"odmowa: katalog testowy {_a(katalog)} nieczytelny: "
                         f"{type(exc).__name__}: {_a(exc)}") from exc
    if obce:
        raise SystemExit(f"odmowa: katalog testowy {_a(katalog)} zawiera {len(obce)} cudzych "
                         f"plikow ({_a(', '.join(obce[:3]))}) - pomiar tylko w katalogu wylacznie "
                         f"na pliki {_PROBA_PLIK}*")
    inne = sorted({_korzen(p) for p in pliki} - {_korzen(katalog)})
    if inne:
        raise SystemExit(f"odmowa: katalog testowy na korzeniu {_a(_korzen(katalog))}, a pliki "
                         f"planu na {_a(', '.join(inne))} - zmierz blokade na udziale pilotazu")
    try:
        wyniki = dict(blokada(katalog))
    except OSError as exc:
        raise SystemExit(f"odmowa: pomiar blokady w {_a(katalog)} padl: {type(exc).__name__}: "
                         f"{_a(exc)}") from exc
    kod, wolumin = wyniki.pop("kod"), wyniki.pop("wolumin")
    if kod != 0:
        zle = [f"{k} = {v}" for k, v in wyniki.items()
               if _blokada_liczy(k) and v not in _BLOKADA_DOBRE]
        raise SystemExit(f"odmowa: blokada na udziale NIE dziala ({_a('; '.join(zle))}) - zapisu "
                         f"w miejscu tam nie sprawdzimy")
    inne = sorted({_tozsamosc(p)["wolumin"] for p in pliki} - {wolumin})
    if inne:
        raise SystemExit(f"odmowa: blokade zmierzono na woluminie {wolumin:#x}, a pliki planu leza "
                         f"na {', '.join(f'{v:#x}' for v in inne)} - zmierz ja na udziale pilotazu")
    return {"katalog": os.path.abspath(katalog), "wolumin": wolumin, "kod": kod, "wyniki": wyniki}


def _wolumin_katalogu(katalog):
    """Wolumin (tożsamość z uchwytu) najbliższego ISTNIEJĄCEGO przodka `katalog` - katalog kopii
    przed `przed` zwykle jeszcze nie istnieje."""
    k = Path(katalog)
    while not k.exists() and k.parent != k:
        k = k.parent
    return _tozsamosc(k)["wolumin"]


def przed(katalog, plan_json, katalog_blokady):
    katalog = Path(os.path.abspath(katalog))
    zajety = _katalog_zajety(katalog)
    if zajety is not None:
        raise SystemExit(f"odmowa: {_a(katalog)} zawiera juz {_a(zajety)} - kopie sprzed zapisu "
                         f"nie moga byc nadpisane; podaj nowy katalog")
    try:
        surowy = Path(plan_json).read_bytes()          # sha1 tych bajtów = kotwica planu (AR-165)
        plan = json.loads(surowy.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"odmowa: plan nieczytelny: {_a(exc)}") from exc
    if not isinstance(plan, list) or not plan:
        raise SystemExit("odmowa: plan nie jest niepusta lista pozycji")
    sciezki, pary, wydania, pozycje = [], [], [], []
    for i, pozycja in enumerate(plan):
        p = None
        try:
            p, po, wydanie, poz = _pozycja_planu(pozycja)
            # Tożsamość najpierw: zapis atomowy `po` rozpoznaje po jej zmianie, więc plik bez niej
            # (i każdy plik poza Windows) odpada, zanim cokolwiek przeczytamy z treści.
            powod = (_tozsamosc_planu(p) or _odmowa_wydania(p, wydanie)
                     or _odmowa_pozycji(p, poz))
        except Exception as exc:  # noqa: BLE001 - każda porażka bramki planu to odmowa, nie wyjątek
            powod = f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc)
        if powod is not None:
            gdzie = f" ({_a(p)})" if p is not None else ""
            raise SystemExit(f"odmowa: pozycja {i}{gdzie}: {_a(powod)}")
        sciezki.append(p)
        pary.append(po)
        wydania.append(wydanie)
        pozycje.append(poz)
    if len(set(map(os.path.normcase, sciezki))) != len(sciezki):
        raise SystemExit("odmowa: plan z powtorzonym plikiem")
    cele = [po for po in pary if po is not None]
    if len(set(map(os.path.normcase, cele))) != len(cele):
        raise SystemExit("odmowa: dwa pliki planu z ta sama sciezka 'po'")
    for p, po in zip(sciezki, pary):
        if po is not None and os.path.normcase(po) != os.path.normcase(p) and os.path.exists(po):
            raise SystemExit(f"odmowa: sciezka 'po' juz istnieje przed zapisem: {_a(po)}")
    if _wolumin_katalogu(katalog) in {_tozsamosc(p)["wolumin"] for p in sciezki}:
        # Kopie pod udziałem archiwum skan wziąłby za drugie lokalizacje klatek - i nie byłyby
        # niezależne od udziału, który sprawdzają.
        raise SystemExit(f"odmowa: katalog kopii {_a(katalog)} na woluminie plikow planu - kopie "
                         f"na dysk lokalny, nie na udzial z oryginalami")
    pomiar = _blokada_udzialu(katalog_blokady, sciezki)
    katalog.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (p, poz, po, wydanie) in enumerate(zip(sciezki, pozycje, pary, wydania)):
        kopia = katalog / f"{i:04d}{os.path.splitext(p)[1]}"
        st = os.stat(p)
        tozsamosc = _tozsamosc(p)
        _kopiuj(p, kopia)
        karty, _ = _karty(p)
        # Plik bez zmiany treści (RAW, karta już w formie) nie potrzebuje granic nagłówka -
        # porównanie obejmuje cały plik, a RAW nie otworzy się czytnikiem FITS.
        granice = [0, 0] if poz["op"] == "none" else list(_granice(p))
        wpis = {"plik": p, "po": po, "wydanie": wydanie, "kopia": str(kopia), "sha1": _sha1(p),
                "sha1_kopii": _sha1(kopia), "rozmiar": st.st_size, "ino": st.st_ino,
                "tozsamosc": tozsamosc, "granice": granice, **poz, "karty": karty}
        st_po = os.stat(p)
        if wpis["sha1"] != wpis["sha1_kopii"] or os.path.getsize(kopia) != st.st_size:
            raise SystemExit(f"KOPIA NIEZGODNA: {_a(p)}")
        if ((st_po.st_size, st_po.st_mtime_ns, st_po.st_ino) != (st.st_size, st.st_mtime_ns,
                                                                   st.st_ino)
                or _tozsamosc(p) != tozsamosc):
            raise SystemExit(f"PLIK ZMIENIL SIE W TRAKCIE KOPII: {_a(p)}")
        manifest.append(wpis)
        print(f"przed OK {_a(p)} sha1={wpis['sha1']} "
              f"tozsamosc={tozsamosc['wolumin']:#x}:{tozsamosc['indeks']}"
              + (f" wydanie={_a(wydanie)}" if wydanie else ""))
    tresc = {"schemat": _SCHEMAT,
             "plan": {"sciezka": os.path.abspath(plan_json),
                      "sha1": hashlib.sha1(surowy).hexdigest()},
             "srodowisko": {"python": sys.version, "komputer": platform.node()},
             "blokada": pomiar, "pozycje": manifest}
    tmp = katalog / (MANIFEST + ".tmp")                  # manifest atomowo, po wszystkich kopiach
    with open(tmp, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(tresc, indent=1))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, katalog / MANIFEST)
    # Liczba pozycji i sha1 planu także w wyjściu - log sterownika to trzecie miejsce kotwicy.
    print(f"przed KONIEC pozycji={len(manifest)} plan_sha1={tresc['plan']['sha1']} "
          f"blokada={pomiar['kod']} wolumin={pomiar['wolumin']:#x}")


# ============================================================ po - wspólne


def _porownaj_poza(plik, kopia, a, b):
    """Czy bajty pliku poza [a, b) są identyczne z kopią (cały plik, strumieniowo, ta sama długość)."""
    with open(plik, "rb") as f1, open(kopia, "rb") as f2:
        pozycja = 0
        while True:
            x, y = f1.read(1 << 20), f2.read(1 << 20)
            if not x and not y:
                return True
            if len(x) != len(y):
                return False
            if x != y:
                for k in range(len(x)):
                    if x[k] != y[k] and not (a <= pozycja + k < b):
                        return False
            pozycja += len(x)


def _czytaj(path, start, koniec):
    with open(path, "rb") as fh:
        fh.seek(start)
        return fh.read(koniec - start)


# ============================================================ po - FITS


def _karta_fits(rekord):
    """`(keyword, value, comment)` z 80-bajtowego rekordu albo `None`, gdy się nie parsuje."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            karta = fits.Card.fromstring(rekord.decode("ascii"))
            return karta.keyword, karta.value, karta.comment
    except Exception:  # noqa: BLE001 - rekord nieczytelny to werdykt kontroli, nie awaria
        return None


def _karta_wg_planu(karta, poz, komentarz):
    """Problemy karty `(keyword, value, comment)` przeczytanej z pliku wobec planu i komentarza
    oczekiwanego (`komentarz`)."""
    kw = poz["keyword"]
    problemy = []
    if karta[0] != kw:
        problemy.append(f"rekord {kw}[0] ma po zapisie keyword {_a(repr(karta[0]))}")
    if not isinstance(karta[1], str) or karta[1] != poz["value"].rstrip():
        problemy.append(f"{kw}[0] po zapisie = {_a(repr(karta[1]))}, plan = "
                        f"{_a(repr(poz['value']))}")
    if karta[2] != komentarz:
        problemy.append(f"komentarz {kw}[0] = {_a(repr(karta[2]))}, oczekiwany "
                        f"{_a(repr(komentarz))}")
    return problemy


def _fits_set_problemy(plik, kopia, a, b, poz):
    """Plik oczekiwany = kopia z podmienionym WYŁĄCZNIE rekordem `keyword[0]` (położenie z kopii);
    komentarz z planu, a przy `comment` null - komentarz kopii."""
    kw = poz["keyword"]
    nazwa = kw.ljust(8).encode("ascii")
    region = _czytaj(kopia, a, b)
    pozycja = None
    for i in range(0, len(region), _FITS_REKORD):
        rekord = region[i:i + _FITS_REKORD]
        if rekord == _FITS_END:
            break
        if rekord[:8] == nazwa:
            pozycja = a + i
            break
    if pozycja is None:
        return [f"kopia bez karty {kw} w regionie naglowka"]
    problemy = []
    if not _porownaj_poza(plik, kopia, pozycja, pozycja + _FITS_REKORD):
        problemy.append(f"bajty poza rekordem {kw}[0] rozne od kopii")
    stara = _karta_fits(region[pozycja - a:pozycja - a + _FITS_REKORD])
    nowa = _karta_fits(_czytaj(plik, pozycja, pozycja + _FITS_REKORD))
    if stara is None or nowa is None:
        return problemy + [f"rekord {kw}[0] nieparsowalny (kopia albo plik)"]
    return problemy + _karta_wg_planu(
        nowa, poz, stara[2] if poz["comment"] is None else poz["comment"])


def _fits_po_dopisaniu(region, poz):
    """Region nagłówka FITS po dopisaniu karty W MIEJSCU - WŁASNY model reguły pisarza na rekordach
    kopii (pisarz układa kolejność astropy `Header.append`: za ostatnią kartą zwykłą, przed końcowym
    blokiem kart komentarzowych i pustych, z zużyciem pustej karty z końca). Bez `Header` astropy
    i bez funkcji pisarza; `fits.Card` składa wyłącznie obraz nowej karty.

    Zwraca `(region oczekiwany, indeks rekordu nowej karty, indeks rekordu END)` albo `(None,
    powód)`, gdy kopia nie ma zapasu na dopisanie w miejscu."""
    rekordy = [region[i:i + _FITS_REKORD] for i in range(0, len(region), _FITS_REKORD)]
    if _FITS_END not in rekordy:
        return None, "kopia bez rekordu END w regionie naglowka"
    koniec = rekordy.index(_FITS_END)
    karty = []                                       # karta = jej rekordy (z kontynuacjami)
    for i, rekord in enumerate(rekordy[:koniec]):
        if i and rekord[:8] == b"CONTINUE":
            karty[-1].append(rekord)
        else:
            karty.append([rekord])
    miejsce = len(karty)
    while miejsce and karty[miejsce - 1] == [_FITS_PUSTY]:
        miejsce -= 1
    while miejsce and karty[miejsce - 1][0][:8] in _FITS_KOMENTARZOWE:
        miejsce -= 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nowa = fits.Card(poz["keyword"], poz["value"], poz["comment"] or "").image
    if len(nowa) != _FITS_REKORD:
        return None, f"karta {poz['keyword']} z planu nie miesci sie w jednym rekordzie"
    po = karty[:miejsce] + [[nowa.encode("ascii")]] + karty[miejsce:]
    if po[-1] == [_FITS_PUSTY]:
        po.pop()                                     # pusta karta z końca zużyta - END na miejscu
    nowe = b"".join(r for karta in po for r in karta)
    przyrost = len(nowe) // _FITS_REKORD - koniec
    if przyrost and rekordy[koniec + 1:koniec + 2] != [_FITS_PUSTY]:
        return None, ("kopia bez pustej karty na koncu i bez wolnego rekordu za END - dopisanie "
                      "w miejscu niemozliwe")
    oczekiwany = nowe + _FITS_END + region[(koniec + 1 + przyrost) * _FITS_REKORD:]
    return oczekiwany, sum(len(k) for k in karty[:miejsce]), koniec + przyrost


def _fits_add_problemy(plik, kopia, a, b, poz):
    """Plik oczekiwany = kopia z regionem nagłówka po dopisaniu (`_fits_po_dopisaniu`)."""
    kw = poz["keyword"]
    model = _fits_po_dopisaniu(_czytaj(kopia, a, b), poz)
    if model[0] is None:
        return [model[1]]
    oczekiwany, i_karty, i_end = model
    problemy = []
    if not _porownaj_poza(plik, kopia, a, b):
        problemy.append("bajty poza regionem naglowka rozne od kopii")
    region = _czytaj(plik, a, b)
    rozne = [i for i in range(0, len(oczekiwany), _FITS_REKORD)
             if region[i:i + _FITS_REKORD] != oczekiwany[i:i + _FITS_REKORD]]
    if rozne:
        i = rozne[0] // _FITS_REKORD
        rodzaj = ("nowa karta " + kw if i == i_karty else "END" if i == i_end
                  else "karta kopii" if i < i_end else "wypelnienie za END")
        problemy.append(f"region naglowka rozny od oczekiwanego w {len(rozne)} rekordach, "
                        f"pierwszy: rekord {i} (oczekiwany: {_a(rodzaj)})")
    karta = _karta_fits(region[i_karty * _FITS_REKORD:(i_karty + 1) * _FITS_REKORD])
    if karta is None:
        return problemy + [f"rekord nowej karty {kw} (rekord {i_karty}) nieparsowalny"]
    return problemy + _karta_wg_planu(karta, poz, poz["comment"] or "")


# ============================================================ po - XISF


def _odescapuj(tekst):
    for encja, znak in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        tekst = tekst.replace(encja, znak)
    return tekst.replace("&amp;", "&")


def _dozwolone_wycinki(xml):
    """Wycinki bajtów WARTOŚCI, które pisarz ma prawo zmienić: `karta` = atrybut `value` pierwszego
    `<FITSKeyword name="OBJECT">`, `wlasnosc` = wartość pierwszej `<Property id="Observation:Object:
    Name">` (atrybut `value` albo tekst elementu). Własny lokalizator - nie ten, którym celuje
    pisarz - więc jego pomyłka nie przepuszcza tej samej pomyłki pisarza."""
    wynik, karta_byla, wlasnosc_byla = {}, False, False
    for m in _ZNACZNIK.finditer(xml):
        if m.group(2) is None or m.group(1):          # komentarz, CDATA, instrukcja, zamknięcie
            continue
        lokalna = m.group(2).rsplit(b":", 1)[-1]
        baza = m.start(3)
        atrybuty = {}
        for at in _ATRYBUT.finditer(m.group(3)):
            grupa = 2 if at.group(2) is not None else 3
            atrybuty.setdefault(at.group(1).rsplit(b":", 1)[-1],
                                (baza + at.start(grupa), baza + at.end(grupa)))

        def tekst(nazwa):
            s, e = atrybuty[nazwa]
            return _odescapuj(xml[s:e].decode("utf-8", "replace"))
        if lokalna == b"FITSKeyword" and not karta_byla and b"name" in atrybuty \
                and tekst(b"name").strip().upper() == "OBJECT":
            karta_byla = True
            if b"value" in atrybuty:
                wynik["karta"] = atrybuty[b"value"]
        elif lokalna == b"Property" and not wlasnosc_byla and b"id" in atrybuty \
                and tekst(b"id") == _WLASNOSC_OBIEKTU:
            wlasnosc_byla = True
            if b"value" in atrybuty:
                wynik["wlasnosc"] = atrybuty[b"value"]
            elif not m.group(4):
                koniec = xml.find(b"<", m.end())
                wynik["wlasnosc"] = (m.end(), koniec if koniec >= 0 else len(xml))
    return wynik


def _poza_wycinkami(xml, wycinki):
    kawalki, ostatni = [], 0
    for s, e in sorted(wycinki.values()):
        kawalki.append(xml[ostatni:s])
        ostatni = e
    kawalki.append(xml[ostatni:])
    return kawalki


def _elementy(xml):
    """Elementy drzewa XML w kolejności dokumentu, z komentarzami i instrukcjami przetwarzania."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    parser.feed(scan.xml_parsable(xml))
    return list(parser.close().iter())


def _lokalna(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else None


def _bez_apostrofow(wartosc):
    if wartosc is not None and len(wartosc) >= 2 and wartosc[0] == wartosc[-1] == "'":
        wartosc = wartosc[1:-1].replace("''", "'")
    return None if wartosc is None else wartosc.rstrip()


def _xml_problemy(xml0, xml1, forma):
    """XML po zapisie wobec XML-a kopii: jedyne różnice to dwie dozwolone wartości, a te niosą formę."""
    w0, w1 = _dozwolone_wycinki(xml0), _dozwolone_wycinki(xml1)
    if set(w0) != set(w1) or _poza_wycinkami(xml0, w0) != _poza_wycinkami(xml1, w1):
        return ["XML rozny od kopii poza wartoscia karty OBJECT i wlasnosci obiektu"]
    try:
        e0, e1 = _elementy(xml0), _elementy(xml1)
    except ET.ParseError as exc:
        return [f"XML nieparsowalny: {_a(exc)}"]
    if len(e0) != len(e1):
        return ["XML: inna liczba elementow niz w kopii"]
    ik = next((i for i, e in enumerate(e0) if _lokalna(e.tag) == "FITSKeyword"
               and (e.get("name") or "").strip().upper() == "OBJECT"), None)
    ip = next((i for i, e in enumerate(e0) if _lokalna(e.tag) == "Property"
               and e.get("id") == _WLASNOSC_OBIEKTU), None)
    for i, (x, y) in enumerate(zip(e0, e1)):
        wolna_wartosc = i in (ik, ip)
        wolny_tekst = i == ip and "value" not in x.attrib
        if (x.tag != y.tag or set(x.attrib) != set(y.attrib) or x.tail != y.tail
                or len(x) != len(y) or (not wolny_tekst and x.text != y.text)
                or any(x.get(k) != y.get(k) for k in x.attrib
                       if not (wolna_wartosc and k == "value"))):
            return [f"XML: element {i} ({_a(_lokalna(x.tag))}) rozny od kopii"]
    if ik is None or "value" not in e0[ik].attrib:
        return ["kopia bez karty OBJECT z atrybutem value"]
    problemy = []
    nowa = _bez_apostrofow(e1[ik].get("value"))
    if nowa != forma.rstrip():
        problemy.append(f"OBJECT[0] po zapisie = {_a(repr(nowa))}, plan = {_a(repr(forma))}")
    if ip is not None:
        wlasnosc = e1[ip].get("value") if "value" in e1[ip].attrib else e1[ip].text
        if wlasnosc != forma:
            problemy.append(f"{_WLASNOSC_OBIEKTU} po zapisie = {_a(repr(wlasnosc))}, "
                            f"plan = {_a(repr(forma))}")
    return problemy


def _xisf_czesci(region):
    """`(sygnatura, reserved, xml, wypełnienie)` regionu `[0, first_attachment)` albo `None`, gdy
    pole długości wskazuje XML wychodzący poza region."""
    if len(region) < _XISF_XML:
        return None
    (dlugosc,) = struct.unpack("<I", region[8:12])
    if _XISF_XML + dlugosc > len(region):
        return None
    return (region[:8], region[12:16], region[_XISF_XML:_XISF_XML + dlugosc],
            region[_XISF_XML + dlugosc:])


def _xisf_problemy(plik, kopia, fa, forma):
    problemy = []
    if not _porownaj_poza(plik, kopia, 0, fa):
        problemy.append("bajty od first_attachment do konca rozne od kopii")
    stare, nowe = _xisf_czesci(_czytaj(kopia, 0, fa)), _xisf_czesci(_czytaj(plik, 0, fa))
    if stare is None or nowe is None:
        return problemy + ["pole dlugosci XML wychodzi poza region naglowka (kopia albo plik)"]
    (syg0, res0, xml0, pad0), (syg1, res1, xml1, pad1) = stare, nowe
    if syg1 != _XISF_SYGNATURA or syg1 != syg0:
        problemy.append("sygnatura XISF zmieniona")
    if res1 != res0:
        problemy.append("pole reserved zmienione")
    # Wypełnienie wg reguły pisarza: region ma stały rozmiar, zmiana dzieje się na POCZĄTKU
    # wypełnienia - wydłużenie zjada jego pierwsze bajty, skrócenie dokłada zera.
    d = len(xml1) - len(xml0)
    oczekiwane = pad0[d:] if d > 0 else b"\x00" * -d + pad0
    if pad1 != oczekiwane:
        problemy.append(f"wypelnienie po XML niezgodne z regula pisarza (delta XML {d:+d} B)")
    return problemy + _xml_problemy(xml0, xml1, forma)


# ============================================================ po - XISF `add` (AR-165)

_XML_BIALE = b" \t\r\n"                                # białe znaki XML 1.0 (produkcja S)
_KARTA_ATRYBUTY = frozenset({b"name", b"value", b"comment"})


def _xml_atrybut(tekst):
    """Wartość atrybutu w cudzysłowie `"` - escape `&` (pierwszy), `<`, `"`; `>` zostaje surowy
    (legalny w atrybucie, a escape zmieniłby bajty)."""
    return tekst.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;").encode("utf-8")


def _tekstowa(xml, atrybuty):
    """Czy karta trzyma wartość w apostrofach FITS (surowe bajty atrybutu `value`)."""
    if b"value" not in atrybuty:
        return False
    s, e = atrybuty[b"value"]
    return e - s >= 2 and xml[s:s + 1] == b"'" == xml[e - 1:e]


def _xisf_po_dopisaniu(xml, poz):
    """XML nagłówka XISF po dopisaniu karty W MIEJSCU - WŁASNY model reguły pisarza
    (`writeback._xisf_add_patch` → `scan.build_fits_keyword_element`, czytane, nie wołane) na
    tokenizerze tej kontroli: nowa karta = kopia CAŁEGO elementu wzorca (OSTATNIA karta z wartością
    w apostrofach FITS; z zamknięciem, jeśli je ma) z podmienionymi `name` (karta z planu), `value`
    (wartość z planu w apostrofach, apostrof wewnątrz podwojony, escape XML) i `comment` (komentarz
    z planu, null = pusty), wstawiona za KOŃCEM elementu OSTATNIEJ karty (nie wzorca), poprzedzona
    jej wcięciem - białymi znakami tuż przed nią. Wzorzec daje styl, ostatnia karta - miejsce.

    Zwraca `(nowy XML, (początek, koniec) wstawki)` albo `(None, powód)`, gdy pisarz nie ma czego
    dopisać: brak kart, brak wzorca, wzorzec z obcymi atrybutami albo bez `comment=` przy komentarzu
    z planu, karta z treścią, zagnieżdżona albo niedomknięta."""
    ostatnia = wzorzec = otwarta = None     # (początek, koniec) / (początek, koniec, atrybuty)
    for m in _ZNACZNIK.finditer(xml):
        if m.group(2) is None or m.group(2).rsplit(b":", 1)[-1] != b"FITSKeyword":
            continue
        if m.group(1):                                     # </FITSKeyword>
            if otwarta is None:
                return None, "</FITSKeyword> bez otwarcia"
            start, koniec_otwarcia, atrybuty = otwarta
            if xml[koniec_otwarcia:m.start()].strip(_XML_BIALE):
                return None, "karta z trescia elementu"
            ostatnia, otwarta = (start, m.end()), None
            if _tekstowa(xml, atrybuty):
                wzorzec = (start, m.end(), atrybuty)
            continue
        if otwarta is not None:
            return None, "karta zagniezdzona w innej karcie"
        atrybuty = {}
        for at in _ATRYBUT.finditer(m.group(3)):
            grupa = 2 if at.group(2) is not None else 3
            atrybuty.setdefault(at.group(1).rsplit(b":", 1)[-1],
                                (m.start(3) + at.start(grupa), m.start(3) + at.end(grupa)))
        if m.group(4):                                     # <FITSKeyword …/>
            ostatnia = (m.start(), m.end())
            if _tekstowa(xml, atrybuty):
                wzorzec = (m.start(), m.end(), atrybuty)
        else:
            otwarta = (m.start(), m.end(), atrybuty)
    if otwarta is not None:
        return None, "karta bez zamkniecia"
    if ostatnia is None:
        return None, "XML bez kart <FITSKeyword> - nie ma wzorca nowej karty"
    if wzorzec is None:
        return None, "zadna karta nie trzyma wartosci w apostrofach FITS - brak wzorca karty"
    w0, w1, atrybuty = wzorzec
    obce = sorted(a.decode("ascii", "replace") for a in set(atrybuty) - _KARTA_ATRYBUTY)
    if obce or b"name" not in atrybuty or b"value" not in atrybuty:
        return None, f"wzorzec karty z obcymi atrybutami ({', '.join(obce)}) albo bez name/value"
    if poz["comment"] and b"comment" not in atrybuty:
        return None, "komentarz w planie, a wzorzec karty bez atrybutu comment"
    podmiany = {b"name": _xml_atrybut(poz["keyword"]),
                b"value": _xml_atrybut("'" + poz["value"].replace("'", "''") + "'"),
                b"comment": _xml_atrybut(poz["comment"] or "")}
    kawalki, ostatni = [], w0
    for nazwa, (s, e) in sorted(atrybuty.items(), key=lambda x: x[1]):
        kawalki += [xml[ostatni:s], podmiany[nazwa]]
        ostatni = e
    kawalki.append(xml[ostatni:w1])
    przed_karta = xml[:ostatnia[0]]
    wstawka = przed_karta[len(przed_karta.rstrip(_XML_BIALE)):] + b"".join(kawalki)
    return (xml[:ostatnia[1]] + wstawka + xml[ostatnia[1]:],
            (ostatnia[1], ostatnia[1] + len(wstawka)))


def _xisf_region_po_dopisaniu(region, poz):
    """Region `[0, first_attachment)` po dopisaniu → `(region, (początek, koniec) wstawki w regionie)`
    albo `(None, powód)`: sygnatura i `reserved` z kopii, pole długości = nowy XML, wypełnienie wg
    reguły pisarza (wydłużenie zjada jego początek); nowy XML musi się zmieścić w regionie - bloki
    danych się nie ruszają, więc innej drogi dopisania w miejscu nie ma."""
    czesci = _xisf_czesci(region)
    if czesci is None:
        return None, "pole dlugosci XML wychodzi poza region naglowka"
    syg, res, xml, pad = czesci
    nowy, wstawka = _xisf_po_dopisaniu(xml, poz)
    if nowy is None:
        return None, f"XISF: {wstawka}"
    if _XISF_XML + len(nowy) > len(region):
        return None, (f"XISF: naglowek z nowa karta ({len(nowy)} B) nie miesci sie w rezerwie "
                      f"({len(region) - _XISF_XML} B) - dopisanie w miejscu niemozliwe")
    return (syg + struct.pack("<I", len(nowy)) + res + nowy + pad[len(nowy) - len(xml):],
            (_XISF_XML + wstawka[0], _XISF_XML + wstawka[1]))


def _xisf_drzewo_po_dopisaniu(xml0, xml1, poz):
    """Druga derywacja wstawki, bez modelu bajtowego: drzewo XML po zapisie = drzewo kopii + JEDEN
    element `<FITSKeyword>` - bez dzieci i treści, rodzeństwo ostatniej karty kopii, zaraz za nią -
    z kartą, wartością (w apostrofach FITS) i komentarzem z planu. Reszta drzewa bez zmian (tag,
    atrybuty, tekst, ogon, liczba dzieci), poza dwiema rzeczami, które wstawka zmienia z konstrukcji:
    rodzic ma o jedno dziecko więcej, a ogon ostatniej karty kopii przechodzi na nową kartę (jej
    własny to same białe znaki - wcięcie). Łapie wspólną pomyłkę modelu bajtowego i pisarza, której
    porównanie bajtów nie widzi, bo obie strony się zgadzają."""
    try:
        e0, e1 = _elementy(xml0), _elementy(xml1)
    except ET.ParseError as exc:
        return [f"XML po zapisie nieparsowalny: {_a(exc)}"]
    karty0 = [i for i, e in enumerate(e0) if _lokalna(e.tag) == "FITSKeyword"]
    if not karty0 or len(e1) != len(e0) + 1:
        return [f"XML: {len(e1)} elementow po zapisie, oczekiwane {len(e0) + 1} (kopia + karta)"]
    j = karty0[-1]
    nowa = e1[j + 1]
    rodzic = {dziecko: r for r in e1 for dziecko in r}
    if (_lokalna(nowa.tag) != "FITSKeyword" or len(nowa) or (nowa.text or "").strip()
            or rodzic.get(nowa) is not rodzic.get(e1[j])):
        return ["XML: za ostatnia karta kopii nie stoi nowa karta bez tresci, rodzenstwo ostatniej"]
    problemy = []
    atrybuty = {_lokalna(k): v for k, v in nowa.attrib.items()}
    wartosc = atrybuty.get("value") or ""
    if (set(atrybuty) - {"name", "value", "comment"}
            or (atrybuty.get("name") or "").strip().upper() != poz["keyword"]
            or not (len(wartosc) >= 2 and wartosc[0] == wartosc[-1] == "'")
            or _bez_apostrofow(wartosc) != poz["value"].rstrip()
            or atrybuty.get("comment", "") != (poz["comment"] or "")):
        problemy.append(f"XML: nowa karta {_a(atrybuty)} inna niz plan")
    rodzic_nowej = rodzic.get(nowa)
    for i, (x, y) in enumerate(zip(e0, e1[:j + 1] + e1[j + 2:])):
        dzieci = len(y) - (1 if y is rodzic_nowej else 0)
        ogon = (x.tail == y.tail if i != j
                else nowa.tail == x.tail and not (y.tail or "").strip())
        if (x.tag != y.tag or x.attrib != y.attrib or x.text != y.text or not ogon
                or len(x) != dzieci):
            return problemy + [f"XML: element {i} ({_a(_lokalna(x.tag))}) rozny od kopii poza nowa "
                               f"karta"]
    return problemy


def _xisf_add_problemy(plik, kopia, fa, poz):
    """Plik oczekiwany = kopia z regionem `[0, first_attachment)` po dopisaniu
    (`_xisf_region_po_dopisaniu`); pierwszy rozjazd nazwany częścią regionu. Druga droga - drzewo
    XML (`_xisf_drzewo_po_dopisaniu`)."""
    region0 = _czytaj(kopia, 0, fa)
    model = _xisf_region_po_dopisaniu(region0, poz)
    if model[0] is None:
        return [model[1]]
    oczekiwany, (w0, w1) = model
    problemy = []
    if not _porownaj_poza(plik, kopia, 0, fa):
        problemy.append("bajty od first_attachment do konca rozne od kopii")
    region = _czytaj(plik, 0, fa)
    if region != oczekiwany:
        i = next((k for k, (x, y) in enumerate(zip(region, oczekiwany)) if x != y),
                 min(len(region), len(oczekiwany)))
        koniec_xml = _XISF_XML + struct.unpack("<I", oczekiwany[8:12])[0]
        rodzaj = next(nazwa for granica, nazwa in (
            (8, "sygnatura"), (12, "pole dlugosci XML"), (_XISF_XML, "reserved"),
            (w0, "XML kopii przed nowa karta"), (w1, f"nowa karta {poz['keyword']}"),
            (koniec_xml, "XML kopii za nowa karta"), (len(oczekiwany) + 1, "wypelnienie"))
            if i < granica)
        problemy.append(f"region naglowka XISF rozny od oczekiwanego od bajtu {i} "
                        f"(oczekiwany: {_a(rodzaj)})")
    czesci = _xisf_czesci(region)
    if czesci is None:
        return problemy + ["pole dlugosci XML wychodzi poza region naglowka"]
    return problemy + _xisf_drzewo_po_dopisaniu(_xisf_czesci(region0)[2], czesci[2], poz)


# ============================================================ po


def _przeniesiony(w):
    """Ścieżka `po` pary, gdy różni się od `plik` (null = pozycja bez pary) albo None."""
    po = w["po"]
    return po if po is not None and os.path.normcase(po) != os.path.normcase(w["plik"]) else None


def _ino_uwaga(w, st_ino):
    """Uwaga do raportu, gdy `st_ino` nie jest porównywalny: `po` w innym Pythonie niż `przed` -
    skąd `os.stat` bierze `st_ino`, to szczegół CPython (3.12 zmieniło źródło), więc obie wartości
    idą do raportu, a o tożsamości rozstrzyga ta z uchwytu."""
    return (f"st_ino nieporownany - inny Python niz przy przed: przed {w['ino']}, po {st_ino}; "
            f"rozstrzyga tozsamosc z uchwytu")


def _problemy_pliku(w, ten_sam_python, uwagi):
    """Lista problemów jednego pliku pilotażu (pusta = OK). Przy parze ścieżek plik po zapisie
    czytany pod ścieżką `po`, a pod starą nie ma już nic. `ten_sam_python` - `po` w tym samym
    Pythonie co `przed` (manifest, AR-165): tylko wtedy `st_ino` jest porównywany, inaczej obie
    wartości trafiają do `uwagi` (informacja raportu, nie problem)."""
    problemy = []
    if _sha1(w["kopia"]) != w["sha1"]:
        return ["kopia sprzed zapisu zmieniona - brak materialu porownania"]
    poz = _pozycja(w)
    po = _przeniesiony(w)
    plik = po or w["plik"]
    if po is not None and os.path.exists(w["plik"]):
        problemy.append("pod sciezka sprzed przeniesienia nadal lezy plik")
    st = os.stat(plik)
    if st.st_size != w["rozmiar"]:
        problemy.append("rozmiar pliku zmieniony")
    skutek = ("przepisany w calosci, nie w miejscu" if poz["op"] == "add" else
              "plik podmieniony, nie zapisany w miejscu ani przeniesiony")
    if not ten_sam_python:
        uwagi.append(_ino_uwaga(w, st.st_ino))
    elif st.st_ino != w["ino"]:
        problemy.append(f"st_ino zmieniony - {skutek}")
    # Druga derywacja tożsamości (AR-165) - z uchwytu, z woluminem; poza Windows `OSError`, czyli NIE
    # z powodem, a nie cichy wynik z samego `st_ino`.
    if _tozsamosc(plik) != w["tozsamosc"]:
        problemy.append(f"tozsamosc z uchwytu (wolumin, indeks) zmieniona - {skutek}")
    zerwane = _wydanie_zerwane(w, plik)             # dowiązanie w wydaniu przeżyło zapis (AR-189)
    if zerwane is not None:
        problemy.append(zerwane)
    if poz["op"] == "none":
        if not _porownaj_poza(plik, w["kopia"], 0, 0):
            problemy.append("karta bez zmiany w planie, a bajty pliku rozne od kopii")
        return problemy
    a, b = w["granice"]
    if _jest_xisf(plik):
        problemy += (_xisf_add_problemy(plik, w["kopia"], b, poz) if poz["op"] == "add"
                     else _xisf_problemy(plik, w["kopia"], b, poz["value"]))
    elif poz["op"] == "add":
        problemy += _fits_add_problemy(plik, w["kopia"], a, b, poz)
    else:
        problemy += _fits_set_problemy(plik, w["kopia"], a, b, poz)
    # Czytnik skanu - druga derywacja: `keyword[0]` = wartość z planu, komentarz z planu (`set`
    # z komentarzem null - sprzed); przy `add` karty przed zapisem nie było.
    kw = poz["keyword"]
    karty_po, blad = _karty(plik)
    if blad is not None:
        problemy.append(f"naglowek nieczytelny dla skanu: {_a(blad)}")
    przed_k, po_k = w["karty"].get(f"{kw}[0]"), karty_po.get(f"{kw}[0]")
    if poz["op"] == "add":
        if przed_k is not None:
            problemy.append(f"skan: karta {kw}[0] byla juz przed zapisem")
        komentarz = poz["comment"] or None
    elif przed_k is None:
        return problemy + [f"skan: brak karty {kw}[0] przed zapisem"]
    else:
        komentarz = przed_k[1] if poz["comment"] is None else (poz["comment"] or None)
    if po_k is None:
        problemy.append(f"skan: brak karty {kw}[0] po zapisie")
    else:
        if po_k[0] != poz["value"].rstrip():
            problemy.append(f"skan: {kw}[0] = {_a(repr(po_k[0]))}, plan = "
                            f"{_a(repr(poz['value']))}")
        if po_k[1] != komentarz:
            problemy.append(f"skan: komentarz {kw}[0] = {_a(repr(po_k[1]))}, oczekiwany "
                            f"{_a(repr(komentarz))}")
    return problemy


# Manifest AR-165 (kotwica planu, tożsamość z uchwytu, pomiar blokady) = schemat 2; schemat 3 dokłada
# ścieżkę wydania pozycji (AR-189). `przed` pisze 3, `po` i `po-undo` czytają oba - każdy własnym
# ZAMKNIĘTYM zbiorem kluczy wpisu, wpis schematu 2 to pozycja bez wydania (pilotaż zaczęty przed AR-189).
_SCHEMAT = 3
_KLUCZE_MANIFESTU = frozenset({"schemat", "plan", "srodowisko", "blokada", "pozycje"})
_KLUCZE_PLANU = frozenset({"sciezka", "sha1"})
_KLUCZE_SRODOWISKA = frozenset({"python", "komputer"})
_KLUCZE_BLOKADY = frozenset({"katalog", "wolumin", "kod", "wyniki"})
_KLUCZE_TOZSAMOSCI = frozenset({"wolumin", "indeks"})
_KLUCZE_WPISU_2 = frozenset({"plik", "po", "kopia", "sha1", "sha1_kopii", "rozmiar", "ino",
                             "tozsamosc", "granice", "karty", *_KSZTALT})
_KLUCZE_WPISU = {2: _KLUCZE_WPISU_2, 3: _KLUCZE_WPISU_2 | {_KLUCZ_WYDANIA}}


def _klucze(obiekt, wymagane, gdzie):
    """Problem schematu ZAMKNIĘTEGO (obiekt z kluczami dokładnie `wymagane`) albo `None`."""
    if not isinstance(obiekt, dict):
        return f"{gdzie} nie jest obiektem"
    brak, obce = sorted(wymagane - set(obiekt)), sorted(set(obiekt) - wymagane)
    return f"{gdzie}: brak kluczy {brak}, obce klucze {obce}" if brak or obce else None


def _liczba(x, *, dodatnia=False):
    return isinstance(x, int) and not isinstance(x, bool) and (x > 0 or not dodatnia)


def _typy_wpisu(w):
    """Czy pola wpisu mają typy schematu - typ spoza niego to NIE, nie wyjątek w środku `po`."""
    return (all(isinstance(w[k], str) for k in ("plik", "kopia", "sha1", "sha1_kopii"))
            and all(w[k] is None or isinstance(w[k], str) for k in ("po", _KLUCZ_WYDANIA))
            and _liczba(w["rozmiar"]) and _liczba(w["ino"]) and isinstance(w["karty"], dict)
            and all(isinstance(k, str) and isinstance(v, list) and len(v) == 2
                    for k, v in w["karty"].items())
            and isinstance(w["granice"], list) and len(w["granice"]) == 2
            and all(map(_liczba, w["granice"]))
            and all(_liczba(v, dodatnia=True) for v in w["tozsamosc"].values()))


def _manifest(katalog, plan_json):
    """`(manifest, None)` albo `(None, problem)` - manifest pusty, niepełny, rozjechany z planem
    albo z kopiami to NIE, nie „zero pozycji = zero problemów”. Schemat 3 albo 2 ZAMKNIĘTY (AR-165,
    AR-189 - wpis schematu 3 niesie `wydanie`, wpis schematu 2 czyta się jako pozycję bez wydania;
    zwrócony manifest ma `wydanie` w każdym wpisie): obiekt
    `{schemat, plan, srodowisko, blokada, pozycje}`, w nim `plan {sciezka, sha1}` i `srodowisko
    {python, komputer}` (tekst), `blokada {katalog, wolumin, kod, wyniki}` - wyniki tekstowe,
    a `kod` PRZELICZONY z wyników (nie przyjęty na wiarę) równy zapisanemu i równy 0; wpisy
    z pełnym kształtem pozycji (skrót `object` to obcy klucz - zna go wyłącznie PLAN), `po`
    obowiązkowe (null bez pary), tożsamość z uchwytu `{wolumin, indeks}` dodatnia, `karty` jako
    `{tekst: [wartość, komentarz]}`, typy pól jak w `przed`; brak albo obcy klucz → NIE z nazwą.
    Manifest sprzed AR-165 (lista wpisów) → NIE z powodem - kontrola nie zgaduje, co by w nim było.

    KOTWICA LICZBY POZYCJI poza manifestem = plik planu: sha1 jego bajtów == zapisany przy `przed`,
    a pozycje planu (`_pozycja_planu`) == wpisy manifestu co do liczby, kolejności, ścieżek `plik`
    i `po` oraz kształtu. Usunięty wpis RAZEM z kopią, katalog kopii z innego biegu albo plan
    podmieniony po `przed` → NIE. Dalej jak dotąd: kopia każdego wpisu w TYM katalogu pod numerem
    `NNNN` = jego pozycji (ciągła numeracja od 0), a zbiór plików kopii katalogu == zbiór kopii
    manifestu (osierocona kopia albo pozycja → NIE)."""
    try:
        manifest = json.loads((katalog / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"manifest nieczytelny: {type(exc).__name__}: {exc}"
    if isinstance(manifest, list):
        return None, ("manifest w schemacie sprzed AR-165 (lista wpisow bez kotwicy planu, "
                      "tozsamosci z uchwytu i pomiaru blokady) - kontrola nie zgaduje; dokoncz "
                      "pilotaz kontrola, ktora go zaczela, albo zrob przed od nowa")
    problem = _klucze(manifest, _KLUCZE_MANIFESTU, "manifest")
    schemat = None if problem is not None else manifest["schemat"]
    if problem is None and not (type(schemat) is int and schemat in _KLUCZE_WPISU):
        problem = (f"manifest w schemacie {manifest['schemat']!r}, kontrola zna "
                   f"{' i '.join(map(str, sorted(_KLUCZE_WPISU)))}")
    problem = (problem or _klucze(manifest["plan"], _KLUCZE_PLANU, "plan manifestu")
               or _klucze(manifest["srodowisko"], _KLUCZE_SRODOWISKA, "srodowisko manifestu")
               or _klucze(manifest["blokada"], _KLUCZE_BLOKADY, "blokada manifestu"))
    if problem is not None:
        return None, problem
    teksty = (*manifest["plan"].values(), *manifest["srodowisko"].values(),
              manifest["blokada"]["katalog"])
    if not all(isinstance(t, str) for t in teksty):
        return None, "plan, srodowisko albo katalog blokady manifestu: pole nie jest tekstem"
    blok = manifest["blokada"]
    if (not _liczba(blok["wolumin"], dodatnia=True) or not isinstance(blok["wyniki"], dict)
            or not all(isinstance(k, str) and isinstance(v, str)
                       for k, v in blok["wyniki"].items())):
        return None, "blokada manifestu: wolumin nie jest dodatni albo wyniki nie sa tekstem"
    if not (blok["kod"] == _kod_blokady(blok["wyniki"]) == 0):
        return None, (f"blokada manifestu: kod zapisany {blok['kod']!r}, z wynikow "
                      f"{_kod_blokady(blok['wyniki'])} - blokada nie zmierzona jako dzialajaca")
    wpisy = manifest["pozycje"]
    if not isinstance(wpisy, list) or not wpisy:
        return None, "manifest bez pozycji (pusta albo nie lista)"
    try:
        surowy = Path(plan_json).read_bytes()
        plan = json.loads(surowy.decode("utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"plan nieczytelny: {type(exc).__name__}: {exc}"
    if hashlib.sha1(surowy).hexdigest() != manifest["plan"]["sha1"]:
        return None, "plan inny niz przy przed (sha1 pliku planu) - zmieniony albo plan innego biegu"
    if not isinstance(plan, list) or len(plan) != len(wpisy):
        return None, (f"plan ma {len(plan) if isinstance(plan, list) else '?'} pozycji, manifest "
                      f"{len(wpisy)} - pozycja manifestu usunieta albo dopisana")
    nazwy, czytane = [], []
    for i, (w, pozycja) in enumerate(zip(wpisy, plan)):
        problem = (_klucze(w, _KLUCZE_WPISU[schemat], f"wpis {i}")
                   or _klucze(w["tozsamosc"], _KLUCZE_TOZSAMOSCI, f"wpis {i} tozsamosc"))
        if problem is not None:
            return None, problem
        w = {_KLUCZ_WYDANIA: None, **w}                  # schemat 2: pozycja bez wydania
        if not _typy_wpisu(w):
            return None, f"wpis {i}: typ pola spoza schematu"
        try:
            poz = _pozycja(w)
            plik, po, wydanie, poz_planu = _pozycja_planu(pozycja)
        except ValueError as exc:
            return None, f"wpis {i}: {exc}"
        if ((os.path.normcase(plik), os.path.normcase(po or ""), os.path.normcase(wydanie or ""),
             poz_planu)
                != (os.path.normcase(w["plik"]), os.path.normcase(w["po"] or ""),
                    os.path.normcase(w[_KLUCZ_WYDANIA] or ""), poz)):
            return None, f"wpis {i} inny niz pozycja {i} planu (plik, po, wydanie albo ksztalt)"
        czytane.append(w)
        kopia = Path(w["kopia"])
        if (not re.fullmatch(rf"{i:04d}\.[^.]*", kopia.name)
                or os.path.normcase(kopia.resolve().parent) != os.path.normcase(katalog.resolve())):
            return None, f"wpis {i}: kopia {kopia.name} poza numeracja albo poza katalogiem kopii"
        nazwy.append(kopia.name)
    kopie = sorted(x.name for x in katalog.iterdir() if _KOPIA.match(x.name))
    if kopie != sorted(nazwy):
        return None, (f"kopie w katalogu ({', '.join(kopie)}) inne niz pozycje manifestu "
                      f"({', '.join(nazwy)})")
    return {**manifest, "pozycje": czytane}, None


def po(katalog, plan_json):
    katalog = Path(os.path.abspath(katalog))
    manifest, problem = _manifest(katalog, plan_json)
    if problem is not None:
        print(f"po NIE manifest | {_a(problem)}")
        (katalog / "raport_po.json").write_text(json.dumps(
            [{"plik": None, "ok": False, "problemy": [problem]}], indent=1, ensure_ascii=False),
            encoding="utf-8")
        return 1
    ten_sam_python = manifest["srodowisko"]["python"] == sys.version
    raport, zle = [], 0
    for w in manifest["pozycje"]:
        uwagi = []
        try:
            problemy = _problemy_pliku(w, ten_sam_python, uwagi)
        except (OSError, ValueError) as exc:
            problemy = [f"kontrola padla: {type(exc).__name__}: {_a(exc)}"]
        zle += bool(problemy)
        plik = _przeniesiony(w) or w["plik"]
        raport.append({"plik": plik, "ok": not problemy, "problemy": problemy, "uwagi": uwagi})
        # Cały wiersz przez `_a` (wyjście ASCII, nagłówek modułu) - problemy i uwagi niosą ścieżki.
        print(_a(f"po {'OK ' if not problemy else 'NIE'} {plik}"
                 + (f" | {'; '.join(problemy)}" if problemy else "")
                 + (f" | uwaga: {'; '.join(uwagi)}" if uwagi else "")))
    (katalog / "raport_po.json").write_text(json.dumps(raport, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    return 1 if zle else 0


def po_undo(katalog, plan_json):
    manifest, problem = _manifest(Path(os.path.abspath(katalog)), plan_json)
    if problem is not None:
        print(f"po-undo NIE manifest | {_a(problem)}")
        return 1
    ten_sam_python = manifest["srodowisko"]["python"] == sys.version
    zle = 0
    for w in manifest["pozycje"]:
        po = _przeniesiony(w)
        uwaga = ""
        try:
            st = os.stat(w["plik"])
            if not ten_sam_python:
                uwaga = f" | uwaga: {_ino_uwaga(w, st.st_ino)}"
            ok = (_sha1(w["plik"]) == w["sha1"]
                  and (not ten_sam_python or st.st_ino == w["ino"])
                  and _tozsamosc(w["plik"]) == w["tozsamosc"]
                  and st.st_size == w["rozmiar"] and (po is None or not os.path.exists(po)))
            zerwane = _wydanie_zerwane(w, w["plik"])  # cofnięcie podmianą też rwie wydanie (AR-189)
            if zerwane is not None:
                ok = False
                uwaga += f" | {zerwane}"
        except OSError:                    # pod ścieżką sprzed nie ma pliku albo poza Windows
            ok = False
        zle += not ok
        print(_a(f"po-undo {'OK ' if ok else 'NIE'} {w['plik']}{uwaga}"))
    return 1 if zle else 0


# ============================================================ blokada


_INNY_PROCES = ("import sys\n"
                "try:\n"
                "    open(sys.argv[1], 'r+b').write(b'X')\n"
                "    print('NIE odrzucone')\n"
                "except PermissionError:\n"
                "    print('odrzucone')\n")


_BLOKADA_DOBRE = frozenset({"odrzucone", "dziala", "tak"})
_PROBA_PODMIANY = "os.replace proba "        # zapis każdej próby podmiany - informacja, poza `kod`
_PODMIANA_PROBY = 3
_PODMIANA_PAUZA = 0.5                        # s między próbami po `PermissionError`


def _blokada_liczy(klucz):
    """Czy wynik `klucz` pomiaru `blokada` wchodzi do `kod` - zapis pojedynczej próby podmiany nie."""
    return not klucz.startswith(_PROBA_PODMIANY)


def _kod_blokady(wyniki):
    """`kod` pomiaru z jego wyników tekstowych: 0 = każdy liczony wynik z `_BLOKADA_DOBRE`. Jedna
    reguła dla `blokada` i dla `_manifest` (manifest nie bierze zapisanego `kod` na wiarę)."""
    return 0 if all(v in _BLOKADA_DOBRE for k, v in wyniki.items() if _blokada_liczy(k)) else 1


def _podmiana_zmienia_tozsamosc(c, d, wyniki):
    """Czy `os.replace(D, C)` zmienia tożsamość z uchwytu pod nazwą C - na tę pliku D. Para świeża,
    własna, nietknięta blokadą ani odczytem treści. Zmierzone 2026-10-16 na udziale SMB archiwum:
    podmiana pliku tuż po zamknięciu jego uchwytów (blokada, odczyt) dostała `PermissionError`
    [WinError 5], a usunięcie chwilę później przeszło - stąd do `_PODMIANA_PROBY` prób co
    `_PODMIANA_PAUZA` s przy `PermissionError`, każda próba z wynikiem w `wyniki` (tekst).

    Zwraca wynik pomiaru: `tak`, `NIE` (podmiana wykonana, a tożsamość pod C nie jest tożsamością D)
    albo `NIE zmierzone - …` z numerem błędu ostatniej próby, gdy wszystkie padły."""
    przed_c, zastepujacy = _tozsamosc(c), _tozsamosc(d)
    for proba in range(1, _PODMIANA_PROBY + 1):
        try:
            os.replace(d, c)
        except PermissionError as exc:
            blad = f"{type(exc).__name__} [WinError {exc.winerror}]"
            wyniki[f"{_PROBA_PODMIANY}{proba}"] = f"odmowa {blad}"
            if proba < _PODMIANA_PROBY:
                time.sleep(_PODMIANA_PAUZA)
            continue
        wyniki[f"{_PROBA_PODMIANY}{proba}"] = "wykonana"
        po_podmianie = _tozsamosc(c)
        return "tak" if po_podmianie != przed_c and po_podmianie == zastepujacy else "NIE"
    return f"NIE zmierzone - {blad} w {_PODMIANA_PROBY} probach"


def blokada(katalog):
    """Pomiar blokady na udziale testowym. Zwraca dict: wyniki tekstowe (każdy liczony do `kod`
    z `_BLOKADA_DOBRE` = OK), `kod` (0 = wszystkie OK) i `wolumin` pliku testowego (tożsamość
    z uchwytu) - `przed` porównuje go z woluminem plików planu (AR-165).

    Poza blokadą dwa pomiary tożsamości z uchwytu, bo na niej `po` opiera rozpoznanie drogi
    atomowej: tożsamość własnego pliku stabilna (przed blokadą i po zapisie własnym uchwytem,
    niezerowa) oraz `os.replace` ZMIENIA tożsamość pod nazwą pliku podmienianego
    (`_podmiana_zmienia_tozsamosc`) - udział, który po podmianie oddaje starą tożsamość,
    przepuściłby przepisanie pliku w całości jako zapis w miejscu."""
    katalog = os.path.abspath(katalog)
    if os.path.normcase(katalog).startswith(os.path.normcase(ARCHIWUM)):
        raise SystemExit(f"odmowa: {ARCHIWUM} to drzewo archiwum - pomiar tylko poza nim")
    znacznik = f"{os.getpid()}_{uuid.uuid4().hex}"
    p = Path(katalog) / f"{_PROBA_PLIK}blokady_{znacznik}.bin"
    zapas = Path(katalog) / f"{_PROBA_PLIK}podmiany_{znacznik}.bin"
    moje = []
    wyniki = {}
    try:
        for plik, bajt in ((p, b"\x00"), (zapas, b"\x01")):
            with open(plik, "xb") as fh:                   # wyłącznie NOWY plik - nie cudzy
                fh.write(bajt * 8192)
            moje.append(plik)
        ino = os.stat(p).st_ino
        tozsamosc = _tozsamosc(p)
        with writeback._exclusive(str(p)) as fh:
            for nazwa, proba in (("drugie otwarcie do zapisu", lambda: open(p, "r+b").close()),
                                 ("usuniecie", lambda: os.remove(p)),
                                 ("os.replace na plik", lambda: os.replace(zapas, p))):
                try:
                    proba()
                    wyniki[nazwa] = "NIE odrzucone - blokada NIE dziala"
                except PermissionError:
                    wyniki[nazwa] = "odrzucone"
            wyniki["zapis z INNEGO procesu"] = subprocess.run(
                [sys.executable, "-c", _INNY_PROCES, str(p)], capture_output=True,
                text=True).stdout.strip()
            wyniki["odczyt osobnym uchwytem"] = "dziala" if p.read_bytes()[:1] == b"\x00" \
                else "NIE dziala"
            fh.seek(0)
            fh.write(b"\x02")
            fh.flush()
            os.fsync(fh.fileno())
        wyniki["zapis wlasnym uchwytem"] = "dziala" if p.read_bytes()[:1] == b"\x02" \
            else "NIE dziala"
        wyniki["st_ino stabilny"] = "tak" if os.stat(p).st_ino == ino and ino else "NIE"
        wyniki["tozsamosc z uchwytu stabilna"] = (
            "tak" if _tozsamosc(p) == tozsamosc and all(tozsamosc.values()) else "NIE")
        c = Path(katalog) / f"{_PROBA_PLIK}tozsamosci_{znacznik}.bin"
        d = Path(katalog) / f"{_PROBA_PLIK}zastepujacy_{znacznik}.bin"
        for plik, bajt in ((c, b"\x03"), (d, b"\x04")):  # świeża para - bez blokady i odczytu
            with open(plik, "xb") as fh:
                fh.write(bajt * 8192)
            moje.append(plik)
        try:
            podmiana = _podmiana_zmienia_tozsamosc(c, d, wyniki)
        except OSError as exc:                             # jak każda próba tu: wynik, nie wyjątek
            podmiana = f"NIE zmierzone - {type(exc).__name__} [WinError {exc.winerror}]"
        wyniki["os.replace zmienia tozsamosc z uchwytu"] = podmiana
    finally:
        for plik in moje:                                  # sprzątanie WYŁĄCZNIE własnych plików
            if plik.exists():
                os.remove(plik)
    wyniki["kod"] = _kod_blokady(wyniki)
    wyniki["wolumin"] = tozsamosc["wolumin"]               # po `kod` - liczba, nie wynik pomiaru
    for k, v in wyniki.items():
        print(_a(f"blokada {k}: {v}"))
    return wyniki


if __name__ == "__main__":
    tryb, argumenty = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else (None, [])
    if tryb == "przed" and len(argumenty) == 3:
        przed(*argumenty)
    elif tryb == "po" and len(argumenty) == 2:
        sys.exit(po(*argumenty))
    elif tryb == "po-undo" and len(argumenty) == 2:
        sys.exit(po_undo(*argumenty))
    elif tryb == "blokada" and len(argumenty) == 1:
        sys.exit(blokada(argumenty[0])["kod"])
    else:
        raise SystemExit(__doc__)
