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
      PLAN.json = lista `{"plik": ścieżka, "object": oczekiwana forma karty OBJECT}`. Pełna kopia
      każdego pliku do KATALOG_KOPII (lokalny dysk, NIE udział z oryginałami), tworzona wyłącznie
      jako NOWY plik; sha1 oryginału i kopii (muszą być równe), rozmiar, `st_ino`, granice
      nagłówka, karty → manifest.json, zapisany atomowo dopiero po skopiowaniu i sprawdzeniu
      wszystkich plików. Katalog z manifestem albo z plikiem kopii (`NNNN.*`) → odmowa: kopie
      sprzed zapisu są jedynym materiałem porównania i nie wolno ich nadpisać.
  po KATALOG_KOPII
      dla każdego pliku: kopia nietknięta (sha1), rozmiar i `st_ino` bez zmian, a CAŁY plik równy
      plikowi oczekiwanemu, wyznaczonemu z kopii i planu:
        FITS - wszystkie bajty identyczne z kopią poza jednym 80-bajtowym rekordem karty
          `OBJECT[0]` w jej położeniu z kopii (pierwszy rekord `OBJECT` w regionie
          `[hdrLoc, datLoc)` wybranego HDU); ten rekord to karta `OBJECT` o wartości = forma
          z planu i komentarzu = komentarz z kopii.
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
      Niezależnie od różnic: czytnik skanu widzi po zapisie `OBJECT[0]` = forma z planu,
      z komentarzem sprzed - brak wykonania zmiany to NIE, nie „zero różnic".
      Kod wyjścia 1 przy którymkolwiek NIE.
  po-undo KATALOG_KOPII
      po cofnięciu pilotażu: sha1 CAŁEGO pliku == sha1 sprzed pilotażu, ten sam rozmiar i ten sam
      `st_ino`.
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
    plan = json.loads(Path(plan_json).read_text(encoding="utf-8"))
    sciezki = [os.path.abspath(p["plik"]) for p in plan]
    if not plan or len(set(sciezki)) != len(sciezki) or any(
            not isinstance(p.get("object"), str) for p in plan):
        raise SystemExit("odmowa: plan pusty, z powtorzonym plikiem albo bez formy 'object'")
    katalog.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (p, pozycja) in enumerate(zip(sciezki, plan)):
        kopia = katalog / f"{i:04d}{os.path.splitext(p)[1]}"
        st = os.stat(p)
        _kopiuj(p, kopia)
        karty, _ = _karty(p)
        wpis = {"plik": p, "kopia": str(kopia), "sha1": _sha1(p), "sha1_kopii": _sha1(kopia), "rozmiar": st.st_size,
                "ino": st.st_ino, "granice": list(_granice(p)), "object": pozycja["object"],
                "karty": karty}
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


def _fits_problemy(plik, kopia, a, b, forma):
    """Plik oczekiwany = kopia z podmienionym WYŁĄCZNIE rekordem `OBJECT[0]` (położenie z kopii)."""
    region = _czytaj(kopia, a, b)
    pozycja = None
    for i in range(0, len(region), _FITS_REKORD):
        rekord = region[i:i + _FITS_REKORD]
        if rekord == _FITS_END:
            break
        if rekord[:8] == b"OBJECT  ":
            pozycja = a + i
            break
    if pozycja is None:
        return ["kopia bez karty OBJECT w regionie naglowka"]
    problemy = []
    if not _porownaj_poza(plik, kopia, pozycja, pozycja + _FITS_REKORD):
        problemy.append("bajty poza rekordem OBJECT[0] rozne od kopii")
    stara = _karta_fits(region[pozycja - a:pozycja - a + _FITS_REKORD])
    nowa = _karta_fits(_czytaj(plik, pozycja, pozycja + _FITS_REKORD))
    if stara is None or nowa is None:
        return problemy + ["rekord OBJECT[0] nieparsowalny (kopia albo plik)"]
    if nowa[0] != "OBJECT":
        problemy.append(f"rekord OBJECT[0] ma po zapisie keyword {_a(repr(nowa[0]))}")
    if not isinstance(nowa[1], str) or nowa[1] != forma.rstrip():
        problemy.append(f"OBJECT[0] po zapisie = {_a(repr(nowa[1]))}, plan = {_a(repr(forma))}")
    if nowa[2] != stara[2]:
        problemy.append(f"komentarz OBJECT[0] zmieniony: {_a(repr(stara[2]))} -> "
                        f"{_a(repr(nowa[2]))}")
    return problemy


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


def _problemy_pliku(w):
    """Lista problemów jednego pliku pilotażu (pusta = OK)."""
    problemy = []
    if _sha1(w["kopia"]) != w["sha1"]:
        return ["kopia sprzed zapisu zmieniona - brak materialu porownania"]
    st = os.stat(w["plik"])
    if st.st_size != w["rozmiar"]:
        problemy.append("rozmiar pliku zmieniony")
    if st.st_ino != w["ino"]:
        problemy.append("st_ino zmieniony - plik podmieniony, nie zapisany w miejscu")
    a, b = w["granice"]
    if _jest_xisf(w["plik"]):
        problemy += _xisf_problemy(w["plik"], w["kopia"], b, w["object"])
    else:
        problemy += _fits_problemy(w["plik"], w["kopia"], a, b, w["object"])
    # Czytnik skanu - druga derywacja: OBJECT[0] = forma z planu, komentarz sprzed.
    karty_po, blad = _karty(w["plik"])
    if blad is not None:
        problemy.append(f"naglowek nieczytelny dla skanu: {_a(blad)}")
    przed_obj, po_obj = w["karty"].get("OBJECT[0]"), karty_po.get("OBJECT[0]")
    if przed_obj is None or po_obj is None:
        problemy.append("skan: brak karty OBJECT[0] przed albo po zapisie")
    else:
        if po_obj[0] != w["object"].rstrip():
            problemy.append(f"skan: OBJECT[0] = {_a(repr(po_obj[0]))}, plan = "
                            f"{_a(repr(w['object']))}")
        if po_obj[1] != przed_obj[1]:
            problemy.append("skan: komentarz OBJECT[0] zmieniony")
    return problemy


def po(katalog):
    katalog = Path(katalog)
    manifest = json.loads((katalog / MANIFEST).read_text(encoding="utf-8"))
    raport, zle = [], 0
    for w in manifest:
        try:
            problemy = _problemy_pliku(w)
        except (OSError, ValueError) as exc:
            problemy = [f"kontrola padla: {type(exc).__name__}: {_a(exc)}"]
        zle += bool(problemy)
        raport.append({"plik": w["plik"], "ok": not problemy, "problemy": problemy})
        print(f"po {'OK ' if not problemy else 'NIE'} {_a(w['plik'])}"
              + (f" | {'; '.join(problemy)}" if problemy else ""))
    (katalog / "raport_po.json").write_text(json.dumps(raport, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    return 1 if zle else 0


def po_undo(katalog):
    manifest = json.loads((Path(katalog) / MANIFEST).read_text(encoding="utf-8"))
    zle = 0
    for w in manifest:
        st = os.stat(w["plik"])
        ok = (_sha1(w["plik"]) == w["sha1"] and st.st_ino == w["ino"]
              and st.st_size == w["rozmiar"])
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
