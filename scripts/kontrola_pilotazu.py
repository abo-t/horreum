"""Kontrola NIEZALEŻNA pilotażu zapisu w miejscu (O5) - poza pisarzem, poza bazą (astra Z9/Z16).

Weryfikacja pisarza (`writeback._verify_inplace`) to odczyt KLIENTA: osobny uchwyt tej samej
maszyny, który może przyjść z pamięci podręcznej systemu. Ten skrypt daje kontrolę, której pisarz
dać nie może: pełną kopię lokalną każdego pliku pilotażu sprzed zapisu i porównanie CAŁEGO pliku po
zapisie z PLANEM. Niezależność od pamięci podręcznej daje dopiero uruchomienie `po` z drugiego
komputera albo po restarcie - sam skrypt tego nie dowodzi.

Kontrola nie woła funkcji pisarza, które składają kartę albo region - oczekiwany wynik wyznacza
sama z kopii i planu. Z `writeback` bierze wyłącznie blokadę (`_exclusive`) do trybu `blokada`.

Tryby (pliki pilotażu czytane WYŁĄCZNIE do odczytu):

  przed KATALOG_KOPII PLAN.json
      PLAN.json = lista pozycji `{"plik", "po"?, "keyword", "value", "comment", "op"}` (AR-156):
      `op` = `set` (podmiana istniejącej karty `keyword`), `add` (dopisanie karty, której kopia NIE
      MA) albo `none` (plik bez zmiany treści: po zapisie CAŁY plik bajt w bajt jak kopia - RAW
      albo karta już w formie); `comment` null = bez komentarza, a przy `set` - komentarz zastany.
      Skrót sprzed AR-156: `{"plik", "object": X}` ≡ `OBJECT` `set` X bez komentarza, `"object":
      null` ≡ `none`; pozycja z oboma kształtami naraz to odmowa. Klucze kształtu są obowiązkowe -
      brak to literówka planu, nie „bez karty”. Keyword: FITS - dowolna karta tekstowa (`OBJECT`
      gestu „Zmień obiekt…”, `FILTER` naprawy `header-fix`); XISF - wyłącznie `OBJECT` `set` bez
      komentarza (model regionu XML niżej). `add` przy kopii, która kartę już ma, i `set` przy kopii
      bez karty → odmowa, zanim powstanie jakakolwiek kopia. Opcjonalne `"po": ścieżka` - PARA
      ŚCIEŻEK gestu „Zmień obiekt…” (AR-17 krok 3): `plik` = ścieżka przed przeniesieniem, `po` =
      ścieżka po nim (jeden `os.rename` zmienia folder i nazwę). Pełna kopia
      każdego pliku do KATALOG_KOPII (lokalny dysk, NIE udział z oryginałami), tworzona wyłącznie
      jako NOWY plik; sha1 oryginału i kopii (muszą być równe), rozmiar, `st_ino`, granice
      nagłówka, karty i pełny kształt pozycji → manifest.json, zapisany atomowo dopiero po
      skopiowaniu i sprawdzeniu wszystkich plików. Katalog z manifestem albo z plikiem kopii
      (`NNNN.*`) → odmowa: kopie sprzed zapisu są jedynym materiałem porównania i nie wolno ich
      nadpisać.
  po KATALOG_KOPII
      dla każdego pliku (przy parze: pod ścieżką `po`, a pod starą nie ma już nic - rename zachowuje
      `st_ino`, zmierzone na `R:`): kopia nietknięta (sha1), rozmiar i `st_ino` bez zmian (inny
      `st_ino` przy `add` = plik przepisany w całości drogą atomową, nie dopisany w miejscu), a CAŁY
      plik równy plikowi oczekiwanemu, wyznaczonemu z kopii i planu:
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
          kopii; reszta regionu jak w kopii. Kopia bez obu zapasów → NIE (pisarz nie dopisze
          w miejscu).
        XISF - bajty od `first_attachment` do końca identyczne z kopią; w regionie
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
      Niezależnie od różnic: czytnik skanu widzi po zapisie `keyword[0]` = wartość z planu,
      z komentarzem z planu (przy `set` z komentarzem null - sprzed), a przy `add` karty przed
      zapisem nie było - brak wykonania zmiany to NIE, nie „zero różnic".
      Kod wyjścia 1 przy którymkolwiek NIE.
  po-undo KATALOG_KOPII
      po cofnięciu pilotażu: sha1 CAŁEGO pliku == sha1 sprzed pilotażu, ten sam rozmiar i ten sam
      `st_ino` - pod ścieżką `plik` (przed); przy parze pod ścieżką `po` nie ma już nic.
  blokada KATALOG_TESTOWY
      pomiar blokady `writeback._exclusive` na udziale: tworzy WŁASNE pliki testowe (unikalna nazwa,
      tworzenie wyłączne `xb`), trzyma blokadę i sprawdza, że zapis z INNEGO procesu, drugie
      otwarcie do zapisu, usunięcie i `os.replace` na plik są odrzucane, a odczyt działa; sprząta
      wyłącznie swoje pliki. Odmawia drzewa archiwum `R:\\ASTRO_`.

Wynik na stdout (ASCII), manifest i raport JSON w KATALOG_KOPII."""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import uuid
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from horreum import scan, writeback  # noqa: E402

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
    `none` (stare manifesty czyta tą samą drogą). `ValueError` z powodem: oba kształty naraz,
    brak klucza kształtu, nieznana operacja, typ spoza kontraktu - literówka planu nie przechodzi
    jako „bez karty”."""
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


def _pozycja_planu(p):
    """`(plik, po, kształt)` pozycji planu - schemat ZAMKNIĘTY: obiekt JSON z kluczami dokładnie
    jednego kształtu (+ opcjonalne `po`), `plik` niepustym tekstem, `po` tekstem albo null. Obcy
    klucz (literówka `coment`, `poo`) → `ValueError` z jego nazwą, nie cicha wartość domyślna."""
    if not isinstance(p, dict):
        raise ValueError(f"pozycja nie jest obiektem JSON ({type(p).__name__})")
    obce = sorted(set(p) - _KLUCZE_STARE - _KLUCZE_NOWE - {_KLUCZ_PARY})
    if obce:
        raise ValueError(f"obce klucze {', '.join(map(repr, obce))}")
    if not isinstance(p.get("plik"), str) or not p["plik"]:
        raise ValueError("'plik' nie jest niepustym tekstem")
    po = p.get(_KLUCZ_PARY)
    if po is not None and (not isinstance(po, str) or not po):
        raise ValueError("'po' nie jest niepustym tekstem ani null")
    return os.path.abspath(p["plik"]), os.path.abspath(po) if po else None, _pozycja(p)


# Bramka kwalifikacji zapisu w miejscu - WŁASNY kod kontroli, nie import z pisarza (niezależność):
# karta, której pisarz w miejscu nie zapisze, nie może dostać od kontroli TAK. Karty specjalne
# (bez wartości albo z układem innym niż `keyword = 'tekst' / komentarz`), układu danych (zmiana
# zmieniłaby znaczenie bajtów danych) i sumy kontrolne (zmiana nagłówka unieważnia `CHECKSUM`).
_FITS_SPECJALNE = frozenset({"", "COMMENT", "HISTORY", "CONTINUE", "END"})
_FITS_UKLAD = frozenset({"SIMPLE", "XTENSION", "BITPIX", "NAXIS", "EXTEND", "PCOUNT", "GCOUNT",
                         "GROUPS", "BZERO", "BSCALE", "BLANK"})
_FITS_NAXIS_N = re.compile(r"NAXIS\d+")
_FITS_SUMY = ("CHECKSUM", "DATASUM")


def _karty_naglowka(path):
    """`[(keyword, wartość)]` nagłówka (wybrane HDU FITS / karty XISF) - sam odczyt nagłówka, bez
    haszy całego pliku (bramka planu przed kopiowaniem)."""
    if _jest_xisf(path):
        return [(c.keyword, c.value_raw) for c in scan.read_xisf_meta_full(path).cards]
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        _, hdu = scan._select_hdu(hdul)
        return [(c.keyword, c.value) for c in hdu.header.cards]


def _odmowa_pozycji(path, poz):
    """Powód, dla którego kontrola nie umie sprawdzić tej pozycji na tym pliku, albo `None`."""
    if poz["op"] == "none":
        return None
    kw = poz["keyword"]
    xisf = _jest_xisf(path)
    if xisf:
        # Pisarz XISF dopisuje kartę w miejscu (`_xisf_add_patch`), ale model regionu XML tej
        # kontroli zna wyłącznie podmianę wartości karty OBJECT (i jej własności).
        if (kw, poz["op"], poz["comment"]) != ("OBJECT", "set", None):
            return (f"XISF: kontrola zna wylacznie 'set' karty OBJECT bez komentarza, plan chce "
                    f"'{poz['op']}' karty {kw}")
    elif not _FITS_NAZWA.fullmatch(kw):
        return f"nazwa karty FITS {kw!r} spoza 8 znakow A-Z 0-9 _ -"
    elif kw in _FITS_SPECJALNE or kw in _FITS_UKLAD or _FITS_NAXIS_N.fullmatch(kw):
        return f"karta {kw} specjalna albo ukladu danych - pisarz nie zapisze jej w miejscu"
    karty = _karty_naglowka(path)
    if not xisf:
        sumy = [s for s in _FITS_SUMY if any(k == s for k, _ in karty)]
        if sumy:
            return (f"FITS z suma kontrolna ({', '.join(sumy)}) - zmiana naglowka ja uniewazni, "
                    f"pisarz odmawia")
    wartosci = [v for k, v in karty if k == kw]
    if poz["op"] == "add" and wartosci:
        return f"op 'add', a kopia ma juz karte {kw} - zmiana wartosci idzie przez 'set'"
    if poz["op"] == "set" and not wartosci:
        return f"op 'set', a kopia nie ma karty {kw} - dopisanie idzie przez 'add'"
    if poz["op"] == "set" and not xisf:
        if len(wartosci) != 1:
            return f"op 'set', a karta {kw} wystepuje {len(wartosci)} razy - pisarz wymaga jednej"
        if not isinstance(wartosci[0], str):
            return f"op 'set', a zastana wartosc {kw} nie jest tekstem ({_a(repr(wartosci[0]))})"
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


def przed(katalog, plan_json):
    katalog = Path(katalog)
    zajety = _katalog_zajety(katalog)
    if zajety is not None:
        raise SystemExit(f"odmowa: {_a(katalog)} zawiera juz {_a(zajety)} - kopie sprzed zapisu "
                         f"nie moga byc nadpisane; podaj nowy katalog")
    try:
        plan = json.loads(Path(plan_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"odmowa: plan nieczytelny: {_a(exc)}") from exc
    if not isinstance(plan, list) or not plan:
        raise SystemExit("odmowa: plan nie jest niepusta lista pozycji")
    sciezki, pary, pozycje = [], [], []
    for i, pozycja in enumerate(plan):
        p = None
        try:
            p, po, poz = _pozycja_planu(pozycja)
            powod = _odmowa_pozycji(p, poz)
            if powod is None and os.stat(p).st_ino == 0:
                # Zapis atomowy rozpoznajemy po zmianie `st_ino` - zero to brak tożsamości pliku.
                powod = "st_ino == 0 - brak tozsamosci pliku, zapisu w miejscu nie da sie odroznic"
        except Exception as exc:  # noqa: BLE001 - każda porażka bramki planu to odmowa, nie wyjątek
            powod = f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc)
        if powod is not None:
            gdzie = f" ({_a(p)})" if p is not None else ""
            raise SystemExit(f"odmowa: pozycja {i}{gdzie}: {_a(powod)}")
        sciezki.append(p)
        pary.append(po)
        pozycje.append(poz)
    if len(set(map(os.path.normcase, sciezki))) != len(sciezki):
        raise SystemExit("odmowa: plan z powtorzonym plikiem")
    cele = [po for po in pary if po is not None]
    if len(set(map(os.path.normcase, cele))) != len(cele):
        raise SystemExit("odmowa: dwa pliki planu z ta sama sciezka 'po'")
    for p, po in zip(sciezki, pary):
        if po is not None and os.path.normcase(po) != os.path.normcase(p) and os.path.exists(po):
            raise SystemExit(f"odmowa: sciezka 'po' juz istnieje przed zapisem: {_a(po)}")
    katalog.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (p, poz, po) in enumerate(zip(sciezki, pozycje, pary)):
        kopia = katalog / f"{i:04d}{os.path.splitext(p)[1]}"
        st = os.stat(p)
        _kopiuj(p, kopia)
        karty, _ = _karty(p)
        # Plik bez zmiany treści (RAW, karta już w formie) nie potrzebuje granic nagłówka -
        # porównanie obejmuje cały plik, a RAW nie otworzy się czytnikiem FITS.
        granice = [0, 0] if poz["op"] == "none" else list(_granice(p))
        wpis = {"plik": p, "po": po, "kopia": str(kopia), "sha1": _sha1(p),
                "sha1_kopii": _sha1(kopia), "rozmiar": st.st_size, "ino": st.st_ino,
                "granice": granice, **poz, "karty": karty}
        st_po = os.stat(p)
        if wpis["sha1"] != wpis["sha1_kopii"] or os.path.getsize(kopia) != st.st_size:
            raise SystemExit(f"KOPIA NIEZGODNA: {_a(p)}")
        if (st_po.st_size, st_po.st_mtime_ns, st_po.st_ino) != (st.st_size, st.st_mtime_ns,
                                                                  st.st_ino):
            raise SystemExit(f"PLIK ZMIENIL SIE W TRAKCIE KOPII: {_a(p)}")
        manifest.append(wpis)
        print(f"przed OK {_a(p)} sha1={wpis['sha1']}")
    tmp = katalog / (MANIFEST + ".tmp")                  # manifest atomowo, po wszystkich kopiach
    with open(tmp, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, indent=1))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, katalog / MANIFEST)


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


# ============================================================ po


def _przeniesiony(w):
    """Ścieżka `po` pary, gdy różni się od `plik` (manifest sprzed trybu pary jej nie ma) albo None."""
    po = w.get("po")
    return po if po is not None and os.path.normcase(po) != os.path.normcase(w["plik"]) else None


def _problemy_pliku(w):
    """Lista problemów jednego pliku pilotażu (pusta = OK). Przy parze ścieżek plik po zapisie
    czytany pod ścieżką `po`, a pod starą nie ma już nic."""
    problemy = []
    if _sha1(w["kopia"]) != w["sha1"]:
        return ["kopia sprzed zapisu zmieniona - brak materialu porownania"]
    poz = _pozycja(w)                                    # manifest sprzed AR-156: skrót `object`
    po = _przeniesiony(w)
    plik = po or w["plik"]
    if po is not None and os.path.exists(w["plik"]):
        problemy.append("pod sciezka sprzed przeniesienia nadal lezy plik")
    st = os.stat(plik)
    if st.st_size != w["rozmiar"]:
        problemy.append("rozmiar pliku zmieniony")
    if st.st_ino != w["ino"]:
        problemy.append("st_ino zmieniony - przepisany w calosci, nie w miejscu"
                        if poz["op"] == "add" else
                        "st_ino zmieniony - plik podmieniony, nie zapisany w miejscu ani przeniesiony")
    if poz["op"] == "none":
        if not _porownaj_poza(plik, w["kopia"], 0, 0):
            problemy.append("karta bez zmiany w planie, a bajty pliku rozne od kopii")
        return problemy
    a, b = w["granice"]
    if _jest_xisf(plik):
        problemy += _xisf_problemy(plik, w["kopia"], b, poz["value"])
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


_KLUCZE_MANIFESTU = frozenset({"plik", "kopia", "sha1", "sha1_kopii", "rozmiar", "ino", "granice",
                               "karty"})


def _manifest(katalog):
    """`(manifest, None)` albo `(None, problem)` - manifest pusty, niepełny albo rozjechany z kopiami
    to NIE, nie „zero pozycji = zero problemów”. Wymagane: niepusta lista wpisów z pełnym schematem
    (`po` opcjonalne - manifest sprzed pary ścieżek; kształt pozycji pełny albo skrót `object`, bez
    obcych kluczy), kopia każdego wpisu w TYM katalogu pod numerem `NNNN` = jego pozycji (ciągła
    numeracja od 0), a zbiór plików kopii katalogu == zbiór kopii manifestu (osierocona kopia albo
    pozycja → NIE)."""
    try:
        manifest = json.loads((katalog / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"manifest nieczytelny: {type(exc).__name__}: {exc}"
    if not isinstance(manifest, list) or not manifest:
        return None, "manifest pusty albo nie jest lista wpisow"
    nazwy = []
    for i, w in enumerate(manifest):
        if not isinstance(w, dict):
            return None, f"wpis {i} nie jest obiektem"
        brak = sorted(_KLUCZE_MANIFESTU - set(w))
        obce = sorted(set(w) - _KLUCZE_MANIFESTU - {_KLUCZ_PARY, "object", *_KSZTALT})
        if brak or obce:
            return None, f"wpis {i}: brak kluczy {brak}, obce klucze {obce}"
        try:
            _pozycja(w)
        except ValueError as exc:
            return None, f"wpis {i}: {exc}"
        kopia = Path(w["kopia"])
        if (not re.fullmatch(rf"{i:04d}\.[^.]*", kopia.name)
                or os.path.normcase(kopia.resolve().parent) != os.path.normcase(katalog.resolve())):
            return None, f"wpis {i}: kopia {kopia.name} poza numeracja albo poza katalogiem kopii"
        nazwy.append(kopia.name)
    kopie = sorted(x.name for x in katalog.iterdir() if _KOPIA.match(x.name))
    if kopie != sorted(nazwy):
        return None, (f"kopie w katalogu ({', '.join(kopie)}) inne niz pozycje manifestu "
                      f"({', '.join(nazwy)})")
    return manifest, None


def po(katalog):
    katalog = Path(katalog)
    manifest, problem = _manifest(katalog)
    if problem is not None:
        print(f"po NIE manifest | {_a(problem)}")
        (katalog / "raport_po.json").write_text(json.dumps(
            [{"plik": None, "ok": False, "problemy": [problem]}], indent=1, ensure_ascii=False),
            encoding="utf-8")
        return 1
    raport, zle = [], 0
    for w in manifest:
        try:
            problemy = _problemy_pliku(w)
        except (OSError, ValueError) as exc:
            problemy = [f"kontrola padla: {type(exc).__name__}: {_a(exc)}"]
        zle += bool(problemy)
        plik = _przeniesiony(w) or w["plik"]
        raport.append({"plik": plik, "ok": not problemy, "problemy": problemy})
        print(f"po {'OK ' if not problemy else 'NIE'} {_a(plik)}"
              + (f" | {'; '.join(problemy)}" if problemy else ""))
    (katalog / "raport_po.json").write_text(json.dumps(raport, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    return 1 if zle else 0


def po_undo(katalog):
    manifest, problem = _manifest(Path(katalog))
    if problem is not None:
        print(f"po-undo NIE manifest | {_a(problem)}")
        return 1
    zle = 0
    for w in manifest:
        po = _przeniesiony(w)
        try:
            st = os.stat(w["plik"])
            ok = (_sha1(w["plik"]) == w["sha1"] and st.st_ino == w["ino"]
                  and st.st_size == w["rozmiar"] and (po is None or not os.path.exists(po)))
        except OSError:                                    # pod ścieżką sprzed nie ma pliku
            ok = False
        zle += not ok
        print(f"po-undo {'OK ' if ok else 'NIE'} {_a(w['plik'])}")
    return 1 if zle else 0


# ============================================================ blokada


_INNY_PROCES = ("import sys\n"
                "try:\n"
                "    open(sys.argv[1], 'r+b').write(b'X')\n"
                "    print('NIE odrzucone')\n"
                "except PermissionError:\n"
                "    print('odrzucone')\n")


def blokada(katalog):
    """Pomiar blokady na udziale testowym. Zwraca dict wyników z kluczem `kod` (0 = wszystko OK)."""
    katalog = os.path.abspath(katalog)
    if os.path.normcase(katalog).startswith(os.path.normcase(ARCHIWUM)):
        raise SystemExit(f"odmowa: {ARCHIWUM} to drzewo archiwum - pomiar tylko poza nim")
    znacznik = f"{os.getpid()}_{uuid.uuid4().hex}"
    p = Path(katalog) / f"horreum_proba_blokady_{znacznik}.bin"
    zapas = Path(katalog) / f"horreum_proba_podmiany_{znacznik}.bin"
    moje = []
    wyniki = {}
    try:
        for plik, bajt in ((p, b"\x00"), (zapas, b"\x01")):
            with open(plik, "xb") as fh:                   # wyłącznie NOWY plik - nie cudzy
                fh.write(bajt * 8192)
            moje.append(plik)
        ino = os.stat(p).st_ino
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
    finally:
        for plik in moje:                                  # sprzątanie WYŁĄCZNIE własnych plików
            if plik.exists():
                os.remove(plik)
    dobre = {"odrzucone", "dziala", "tak"}
    wyniki["kod"] = 0 if all(v in dobre for v in wyniki.values()) else 1
    for k, v in wyniki.items():
        print(f"blokada {k}: {v}")
    return wyniki


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    tryb = sys.argv[1]
    if tryb == "przed" and len(sys.argv) == 4:
        przed(sys.argv[2], sys.argv[3])
    elif tryb == "po":
        sys.exit(po(sys.argv[2]))
    elif tryb == "po-undo":
        sys.exit(po_undo(sys.argv[2]))
    elif tryb == "blokada":
        sys.exit(blokada(sys.argv[2])["kod"])
    else:
        raise SystemExit(__doc__)
