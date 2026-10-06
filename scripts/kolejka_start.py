#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kolejka_start.py - GENEROWANY blok `⏭ START TUTAJ` kolejki sesji z rejestru długów.

Rejestr (`rejestr_dlugow.md`, obok kolejki, oba pliki poza gitem) jest JEDYNĄ siedzibą treści
długów i decyzji oraz bloku stanu sesji; blok START w `kolejka_sesji.md` jest jego WIDOKIEM
(skill `kolejka-sesji`, niezmiennik 10: bloku generowanego nie piszesz ręcznie - zmieniasz
źródło i generujesz). Skrypt jest dev-owy: bateria mierzy go na fiksturach, nigdy na plikach
prywatnych.

Podkomendy:
  sprawdz              schemat rejestru + kompletność: każde `TODO-DŁUG(<ID>)` w `horreum/**/*.py`
                       ma OTWARTY blok w rejestrze, żadne ID nie stoi dwa razy.
  start                wypisuje generat na stdout.
  start --sprawdz      porównuje blok w kolejce z generatem BAJT W BAJT (puste linie ogona bloku
                       to układ strony, nie treść - zdjęte po obu stronach); meldunek = numer
                       pierwszej różnej linii kolejki, nie cały blok.
  start --zapisz       podmienia blok w kolejce atomowo; drugi przebieg zostawia plik bajt w bajt.
  tory [--fala N] [--pokaz]
                       szwy torów: zbiór plików toru = backtickowane ścieżki z `siedziba:` jego
                       otwartych ID (i z `tor-bez-id:`). FAIL, gdy dwa tory JEDNEJ fali dzielą plik
                       spoza `DOZWOLONE_WSPOLNE`, oraz „szew nieznany”, gdy otwarte ID nie ma
                       w `siedziba:` żadnej ścieżki pliku. `--pokaz` wypisuje skład torów.
Wspólne flagi: --rejestr, --kolejka, --kod (domyślnie względem korzenia repo).

Kody wyjścia: 0 OK (cisza) | 1 błąd schematu, rozjazd, budżet STARTU przekroczony, kolizja szwów
w fali, szew nieznany - plik NIETKNIĘTY | 2 nie da się zmierzyć (brak pliku, brak markera,
mieszane końce wiersza, zły UTF-8, fala spoza STAN).

FORMAT REJESTRU. Blok zaczyna nagłówek `## ` w pierwszej kolumnie (poza płotkiem kodu):
  `## STAN`              pola sesji: sesja, stan, nastepny-krok, model-nastepnej, nie-wracac,
                         tory (każde raz) oraz powtarzalne tripwir, tor-bez-id i fala.
                         `tory:` = dziedzina torów w kolejności indeksu (`decyzja` dopisuje
                         generator); `tor-bez-id: <tor> <opis> [| <siedziba>]` = pozycje bez
                         własnego ID (opis idzie do indeksu, siedziba tylko do `tory`);
                         `fala: <nr> <nazwa> | <tory fali> | <ID decyzji PRZED falą albo ->`.
  `## <ID> · <tytuł>`    dług albo decyzja: pola stan, waga (wymagane), tor (wymagane w bloku
                         otwartym i zaparkowanym), paczka (pole HISTORYCZNE - wyłącznie w bloku
                         zamkniętym), kiedy, siedziba, zamkniete (opcjonalne); pola ZARAZ pod
                         nagłówkiem, potem pusta linia i proza.
  `## <cokolwiek innego>` sekcja prozy - bez pól.
Nieznane pole, zła dziedzina, duplikat ID albo niezamknięty płotek = błąd schematu; z rejestru,
który oblewa schemat, START się nie generuje.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

KORZEN = Path(__file__).resolve().parent.parent
REJESTR = KORZEN / "rejestr_dlugow.md"
KOLEJKA = KORZEN / "kolejka_sesji.md"
KOD = KORZEN / "horreum"

# Budżet bloku START liczony w LINIACH generatu (z pustymi). Pomiar 2026-09-26 na rejestrze
# z migracji paczki `K`: 39 linii przy 52 otwartych ID (indeks ID zajmuje 7 linii, ~8 ID na linię).
# Limit 45 = najbliższa okrągła wartość z zapasem 6 linii (~40 nowych ID albo trzy tripwiry);
# skill `kolejka-sesji` celuje w ~30, brief paczki `K` postawił sufit 45. Przekroczenie = FAIL
# „krok zbyt szeroki", NIGDY ciche obcięcie: obcięcie skasowałoby instrukcję, FAIL każe
# skrócić pola STAN albo domknąć ID. Pomiar 2026-10-05 po przejściu na indeks wg fal i torów:
# 45 linii przy 63 otwartych ID (indeks 8 linii) - zapas ZERO, następny przyrost każe ciąć STAN.
LIMIT_LINII_STARTU = 45
LIMIT_ZNAKOW = {"nastepny-krok": 900, "model-nastepnej": 250}
SZEROKOSC = 120

# ID: wielka litera na początku, człony po dywizie, opcjonalny ogon po `/` - i co najmniej jeden
# dywiz ALBO cyfra (`FH-6`, `D-OW-3/R1`, `P-J`, `C3`); goły wyraz (`STAN`, `Grupy`) ID nie jest.
ID_RE = re.compile(r"(?=\S*[-0-9])[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*(?:/[A-Za-z0-9]+)*")
NAGLOWEK_RE = re.compile(r"^## (.*)$")
WCIETY_NAGLOWEK_RE = re.compile(r"^ {1,3}## ")
POLE_RE = re.compile(r"^([a-z][a-z-]*):(.*)$")
TODO_RE = re.compile(r"TODO-DŁUG\(([^)\s]+)\)")
KOD_W_BACKTICKU = re.compile(r"`([^`]+)`")

POLA_STANU = ("sesja", "stan", "nastepny-krok", "model-nastepnej", "nie-wracac", "tory")
POLA_STANU_WIELE = ("tripwir", "tor-bez-id", "fala")
POLA_ID_WYMAGANE = ("stan", "waga")
POLA_ID_OPCJONALNE = ("tor", "paczka", "kiedy", "siedziba", "zamkniete")
STANY = ("otwarty", "zaparkowany", "zamkniety")
STANY_OTWARTE = ("otwarty", "zaparkowany")
WAGI = {"-": "", "zolta": "🟡", "czerwona": "🔴"}
TOR_DECYZJA = "decyzja"
TOR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]*")
# Paczki z planu 2026-08-16 (al) - dziedzina ZAMROŻONA: pole `paczka:` żyje już tylko w blokach
# zamkniętych jako ślad historyczny (otwarte niosą `tor:`), więc nowa paczka nie powstanie.
PACZKI_HISTORYCZNE = tuple("ABCDEFGHIJKLMNOPQ") + ("poza", "decyzja")

# Pliki, które dwa tory jednej fali MOGĄ dzielić. Katalog i18n: każdy tor dopisuje własne klucze,
# konflikt to scalenie sąsiednich linii słownika. `grid.py`: dozwolony, bo tabela fal w kolejce
# NAZYWA rejon każdego toru (fala 2: `_flash` / kolumny+QSettings / model komórki) - plik bez
# nazwanego rejonu do tej listy nie wchodzi. Rejony z decyzji Zdzinia 2026-10-06 (`Q4`):
# `app.py` fala 2 - T3 `_flash` i paski recept / T6 `ObjectAxisView`; `planner.py` fala 2 -
# T3 droga komunikatu i pusty stan / T6 chip; `pipeline.py` fala 3 - T10 `_adopt_and_derive`
# i `_run_all` / T5 `_on_pick_dir` i `_set_root`.
DOZWOLONE_WSPOLNE = ("horreum/gui/i18n_catalog.py", "horreum/gui/grid.py", "horreum/gui/app.py",
                     "horreum/gui/planner.py", "horreum/gui/pipeline.py")
# Ścieżka pliku na POCZĄTKU backticku; sufiks funkcji/linii w tym samym backticku (`plik.py:45`,
# `plik.py _f`, `plik.py::f`) odpada. Kropka bez znanego rozszerzenia (`tasks.copies_unread_tip`)
# to symbol, nie plik.
PLIK_RE = re.compile(r"[A-Za-z0-9_./\\-]+?\.(?:py|md|json|sql|ps1|toml|txt|nsi|spec|cfg|ini)"
                     r"(?![A-Za-z0-9_])")

MARKER = "## ⏭ START TUTAJ"


class BladPomiaru(Exception):
    """Kod 2 - nie da się zmierzyć (plik, marker, końce wiersza, kodowanie)."""


class BladBudzetu(Exception):
    """Kod 1 - generat szerszy niż budżet STARTU."""


@dataclass
class Blok:
    ident: str
    tytul: str
    nr: int
    pola: dict = field(default_factory=dict)
    proza: list = field(default_factory=list)


@dataclass
class Fala:
    nr: int
    nazwa: str
    tory: list
    przed: list                         # ID decyzji, które zapadają PRZED falą


@dataclass
class BezId:
    tor: str
    opis: str
    siedziba: str


@dataclass
class Rejestr:
    stan: dict | None = None            # nazwa -> lista wartości (pola jednokrotne mają jedną)
    bloki: list = field(default_factory=list)
    bledy: list = field(default_factory=list)
    fale: list = field(default_factory=list)
    bez_id: list = field(default_factory=list)

    def otwarte(self):
        return [b for b in self.bloki if b.pola.get("stan") in STANY_OTWARTE]

    def tory(self):
        return tuple((self.stan or {}).get("tory", [""])[0].split()) + (TOR_DECYZJA,)


# --- odczyt ----------------------------------------------------------------------------------

def czytaj_tekst(sciezka: Path) -> str:
    try:
        return sciezka.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise BladPomiaru(f"nie ma pliku {sciezka}")
    except UnicodeDecodeError as e:
        raise BladPomiaru(f"{sciezka}: to nie jest UTF-8 ({e})")


def plotek(linia: str) -> bool:
    """Płotek kodu markdown: do trzech spacji wcięcia i obie postacie znacznika."""
    goly = linia.lstrip(" ")
    return len(linia) - len(goly) <= 3 and (goly.startswith("```") or goly.startswith("~~~"))


def _higiena(tekst: str, bledy: list) -> None:
    if tekst.startswith("\ufeff"):
        bledy.append("linia 1: rejestr ma BOM - zapis ma być UTF-8 bez BOM")
    if "\r" in tekst:
        nr = tekst[:tekst.index("\r")].count("\n") + 1
        bledy.append(f"linia {nr}: znak CR - rejestr trzymamy w czystym LF")
    if not tekst.endswith("\n"):
        bledy.append("koniec pliku: brak końcowego LF")
    elif tekst.endswith("\n\n"):
        bledy.append("koniec pliku: więcej niż jeden końcowy LF")


def rozbierz(tekst: str) -> Rejestr:
    """Tekst rejestru -> `Rejestr` z listą błędów schematu. Płotki kodu są POMIJANE (przykład
    bloku w dokumentacji nie jest drugim ID), a płotek bez zamknięcia jest BŁĘDEM: po cichu
    zrobiłby prozą całą resztę rejestru przy kodzie 0."""
    rej = Rejestr()
    _higiena(tekst, rej.bledy)
    linie = tekst.split("\n")
    sekcje = []                                    # (rodzaj, nr, ident, tytul, linie ciała)
    w_plotku, plotek_od = False, 0
    for nr, linia in enumerate(linie, start=1):
        if plotek(linia):
            w_plotku = not w_plotku
            plotek_od = nr if w_plotku else 0
        elif not w_plotku:
            m = NAGLOWEK_RE.match(linia)
            if m:
                sekcje.append([m.group(1).strip(), nr, []])
                continue
            if WCIETY_NAGLOWEK_RE.match(linia):
                # Markdown renderuje `## ` wcięty o 1-3 spacje jako nagłówek, a parser widzi prozę -
                # blok wpadłby do poprzedniego i jego ID zniknęłoby z generatu bez sygnału. Cztery
                # spacje albo tabulator to już blok kodu, czyli legalna proza.
                rej.bledy.append(f"linia {nr}: nagłówek `## ` wcięty - zacznij go od kolumny 0, "
                                 "inaczej wpis znika z rejestru")
        if sekcje:
            sekcje[-1][2].append((nr, linia, w_plotku or plotek(linia)))
    if w_plotku:
        rej.bledy.append(f"linia {plotek_od}: płotek kodu bez zamknięcia - reszta pliku byłaby "
                         "prozą, a jej ID zniknęłyby z rejestru")

    widziane = {}
    for tytul_calosc, nr, cialo in sekcje:
        pola, reszta = _pola(cialo)
        if tytul_calosc == "STAN":
            if rej.stan is not None:
                rej.bledy.append(f"linia {nr}: drugi blok `## STAN`")
                continue
            rej.stan = _sprawdz_stan(pola, reszta, nr, rej.bledy)
            continue
        ident, sep, tytul = tytul_calosc.partition(" · ")
        if not sep:
            if ID_RE.fullmatch(tytul_calosc.split(" ")[0]):
                rej.bledy.append(f"linia {nr}: nagłówek wygląda na ID, ale nie ma separatora "
                                 f"` · ` - `{tytul_calosc[:60]}`")
            if pola:
                rej.bledy.append(f"linia {nr}: sekcja prozy `{tytul_calosc[:40]}` niesie pola "
                                 "- blok ID potrzebuje nagłówka `## <ID> · <tytuł>`")
            continue
        if not ID_RE.fullmatch(ident):
            rej.bledy.append(f"linia {nr}: `{ident}` nie jest identyfikatorem")
            continue
        if not tytul.strip():
            rej.bledy.append(f"linia {nr}: {ident}: pusty tytuł")
        if ident in widziane:
            rej.bledy.append(f"linia {nr}: {ident}: duplikat ID (pierwszy w linii {widziane[ident]})")
            continue
        widziane[ident] = nr
        blok = Blok(ident, tytul.strip(), nr)
        _sprawdz_blok(blok, pola, reszta, rej.bledy)
        rej.bloki.append(blok)

    if rej.stan is None:
        rej.bledy.append("brak bloku `## STAN` - nie ma z czego złożyć STARTU")
    else:
        dziedzina = rej.tory()
        for b in rej.otwarte():
            t = b.pola.get("tor")
            if t is not None and t not in dziedzina:
                rej.bledy.append(f"linia {b.nr}: {b.ident}: tor `{t}` spoza dziedziny "
                                 f"{' '.join(dziedzina)}")
        for wartosc in rej.stan.get("tor-bez-id", []):
            tor, _, reszta = wartosc.partition(" ")
            opis, _, siedziba = reszta.partition(" | ")
            if tor not in dziedzina:
                rej.bledy.append(f"STAN: tor-bez-id `{tor}` spoza dziedziny")
            if not opis.strip():
                rej.bledy.append(f"STAN: tor-bez-id `{tor}` bez opisu")
            if any(ID_RE.fullmatch(t) for t in KOD_W_BACKTICKU.findall(opis)):
                rej.bledy.append(f"STAN: tor-bez-id `{tor}` niesie identyfikator - ID "
                                 "dostaje własny blok, inaczej zniknie z kontroli kompletności")
            rej.bez_id.append(BezId(tor, opis.strip(), siedziba.strip()))
        rej.fale = _sprawdz_fale(rej)
    return rej


def _sprawdz_fale(rej: Rejestr) -> list:
    """`fala: <nr> <nazwa> | <tory> | <decyzje przed albo ->` -> lista `Fala`. Tor należy do
    najwyżej jednej fali (inaczej `tory` liczyłby jego szew dwa razy w dwóch składach), a decyzja
    PRZED falą musi być otwartym ID - zamknięta albo literówka nie wstrzymuje niczego."""
    fale, numery, tor_w_fali = [], set(), {}
    dziedzina = set(rej.tory()) - {TOR_DECYZJA}
    otwarte = {b.ident for b in rej.otwarte()}
    for wartosc in rej.stan.get("fala", []):
        czesci = [c.strip() for c in wartosc.split("|")]
        if len(czesci) != 3:
            rej.bledy.append(f"STAN: fala `{wartosc[:40]}` - format `<nr> <nazwa> | <tory> | "
                             "<decyzje przed albo ->`")
            continue
        glowa, tory, przed = czesci
        nr_txt, _, nazwa = glowa.partition(" ")
        if not nr_txt.isdigit():
            rej.bledy.append(f"STAN: fala `{glowa[:40]}` - numer fali to liczba")
            continue
        nr = int(nr_txt)
        if nr in numery:
            rej.bledy.append(f"STAN: fala {nr} powtórzona")
            continue
        numery.add(nr)
        tory = tory.split()
        if not tory:
            rej.bledy.append(f"STAN: fala {nr} bez torów")
        for t in tory:
            if t not in dziedzina:
                rej.bledy.append(f"STAN: fala {nr}: tor `{t}` spoza dziedziny "
                                 f"{' '.join(sorted(dziedzina))}")
            elif t in tor_w_fali:
                rej.bledy.append(f"STAN: fala {nr}: tor `{t}` stoi już w fali {tor_w_fali[t]}")
            else:
                tor_w_fali[t] = nr
        przed = [] if przed == "-" else przed.split()
        for p in przed:
            if p not in otwarte:
                rej.bledy.append(f"STAN: fala {nr}: decyzja przed falą `{p}` nie jest otwartym ID")
        fale.append(Fala(nr, nazwa.strip(), tory, przed))
    return sorted(fale, key=lambda f: f.nr)


def _pola(cialo):
    """Pola = linie `nazwa: wartość` ZARAZ pod nagłówkiem. Zwraca (pola, reszta ciała)."""
    pola = []
    i = 0
    while i < len(cialo):
        nr, linia, w_plotku = cialo[i]
        m = None if w_plotku else POLE_RE.match(linia)
        if not m:
            break
        pola.append((m.group(1), m.group(2).strip(), nr))
        i += 1
    return pola, cialo[i:]


def _zbierz(pola, znane, wiele, etykieta, bledy):
    wynik = {}
    for nazwa, wartosc, nr in pola:
        if nazwa not in znane and nazwa not in wiele:
            bledy.append(f"linia {nr}: {etykieta}: nieznane pole `{nazwa}:`")
            continue
        if not wartosc:
            bledy.append(f"linia {nr}: {etykieta}: pole `{nazwa}:` puste")
            continue
        if nazwa in wynik and nazwa not in wiele:
            bledy.append(f"linia {nr}: {etykieta}: pole `{nazwa}:` powtórzone")
            continue
        wynik.setdefault(nazwa, []).append(wartosc)
    return wynik


def _proza_po_polach(reszta, znane, etykieta, bledy):
    if reszta and not reszta[0][2] and reszta[0][1].strip():
        bledy.append(f"linia {reszta[0][0]}: {etykieta}: po polach musi stać pusta linia "
                     "(albo to pole z literówką)")
    for nr, linia, w_plotku in reszta:
        m = None if w_plotku else POLE_RE.match(linia)
        if m and m.group(1) in znane:
            bledy.append(f"linia {nr}: {etykieta}: pole `{m.group(1)}:` po pustej linii nie jest "
                         "polem - nikt go nie czyta")


def _sprawdz_stan(pola, reszta, nr, bledy):
    stan = _zbierz(pola, POLA_STANU, POLA_STANU_WIELE, "STAN", bledy)
    for nazwa in POLA_STANU:
        if nazwa not in stan:
            bledy.append(f"linia {nr}: STAN: brak pola `{nazwa}:`")
    for nazwa, limit in LIMIT_ZNAKOW.items():
        dl = len(stan.get(nazwa, [""])[0])
        if dl > limit:
            bledy.append(f"STAN: FAIL: krok zbyt szeroki - `{nazwa}:` ma {dl} znaków, limit {limit}")
    tory = stan.get("tory", [""])[0].split()
    if len(set(tory)) != len(tory) or TOR_DECYZJA in tory:
        bledy.append(f"linia {nr}: STAN: `tory:` z powtórzeniem albo z członem `{TOR_DECYZJA}` "
                     "(ten jest stały, dopisuje go generator)")
    # Etykieta toru stoi w indeksie GOŁA, nie w backtickach - `T1` wygląda jak ID, a kontrola
    # kompletności generatu czyta ID wyłącznie z backticków. Znak spoza nazwy (backtick, gwiazdka)
    # rozbiłby tę granicę.
    zle = [t for t in tory if not TOR_RE.fullmatch(t)]
    if zle:
        bledy.append(f"linia {nr}: STAN: nazwa toru spoza [A-Za-z0-9_] ({' '.join(zle)})")
    if any(l.strip() for _, l, _ in reszta):
        bledy.append(f"linia {nr}: STAN nie niesie prozy - treść idzie w pola")
    return stan


def _sprawdz_blok(blok, pola, reszta, bledy):
    znane = POLA_ID_WYMAGANE + POLA_ID_OPCJONALNE
    if not pola:
        bledy.append(f"linia {blok.nr}: {blok.ident}: blok ID bez pól - pola stoją ZARAZ pod "
                     "nagłówkiem, bez pustej linii")
    zebrane = _zbierz(pola, znane, (), blok.ident, bledy)
    blok.pola = {k: v[0] for k, v in zebrane.items()}
    for nazwa in POLA_ID_WYMAGANE:
        if pola and nazwa not in blok.pola:
            bledy.append(f"linia {blok.nr}: {blok.ident}: brak pola `{nazwa}:`")
    stan, waga = blok.pola.get("stan"), blok.pola.get("waga")
    if stan is not None and stan not in STANY:
        bledy.append(f"linia {blok.nr}: {blok.ident}: stan `{stan}` spoza {'/'.join(STANY)}")
    if waga is not None and waga not in WAGI:
        bledy.append(f"linia {blok.nr}: {blok.ident}: waga `{waga}` spoza {'/'.join(WAGI)}")
    if (stan == "zamkniety") != ("zamkniete" in blok.pola):
        bledy.append(f"linia {blok.nr}: {blok.ident}: `stan: zamkniety` i pole `zamkniete:` "
                     "chodzą w parze (data i czym zamknięto)")
    if stan in STANY_OTWARTE:
        if pola and "tor" not in blok.pola:
            bledy.append(f"linia {blok.nr}: {blok.ident}: brak pola `tor:` (blok otwarty "
                         "i zaparkowany należy do toru albo do `decyzja`)")
        if "paczka" in blok.pola:
            bledy.append(f"linia {blok.nr}: {blok.ident}: `paczka:` to pole historyczne bloku "
                         "zamkniętego - otwarty niesie `tor:`")
    paczka = blok.pola.get("paczka")
    if paczka is not None and paczka not in PACZKI_HISTORYCZNE:
        bledy.append(f"linia {blok.nr}: {blok.ident}: paczka `{paczka}` spoza dziedziny "
                     f"historycznej {' '.join(PACZKI_HISTORYCZNE)}")
    _proza_po_polach(reszta, znane, blok.ident, bledy)
    blok.proza = [l for _, l, _ in reszta]


def todo_w_kodzie(kod: Path) -> dict:
    """`TODO-DŁUG(<ID>)` w `kod/**/*.py` -> {ID: pierwsze `plik:linia`}."""
    if not kod.is_dir():
        raise BladPomiaru(f"nie ma katalogu kodu {kod}")
    wynik = {}
    for sciezka in sorted(kod.rglob("*.py")):
        for nr, linia in enumerate(czytaj_tekst(sciezka).split("\n"), start=1):
            for ident in TODO_RE.findall(linia):
                wynik.setdefault(ident, f"{sciezka.relative_to(kod.parent).as_posix()}:{nr}")
    return wynik


def sprawdz_kompletnosc(rej: Rejestr, kod: Path) -> None:
    """Niezmiennik 10 skilla: równość bajtowa bloku NIE dowodzi kompletności - ID zgubione
    w kodzie (TODO-DŁUG bez bloku) i ID zamknięte w rejestrze, a żywe w kodzie, to błędy."""
    bloki = {b.ident: b for b in rej.bloki}
    for ident, gdzie in todo_w_kodzie(kod).items():
        if ident not in bloki:
            rej.bledy.append(f"{gdzie}: TODO-DŁUG({ident}) nie ma bloku w rejestrze - ID zgubione")
        elif bloki[ident].pola.get("stan") == "zamkniety":
            rej.bledy.append(f"{gdzie}: TODO-DŁUG({ident}) żyje w kodzie, a blok jest zamknięty")


# --- generat ---------------------------------------------------------------------------------

def _zly_poczatek(slowo: str) -> bool:
    """Słowo, które na początku linii zmieniłoby strukturę markdown (lista, nagłówek, cytat)."""
    return slowo in ("-", "+", "*") or slowo[:1] in ("#", ">") or bool(re.fullmatch(r"\d+[.)]", slowo))


def zawin(tekst: str, pierwszy: str = "", dalszy: str = "", szer: int = SZEROKOSC) -> list:
    """Zachłanne zawijanie po spacjach do `szer` punktów kodowych. Linia kontynuacji nie może
    zaczynać się słowem, które markdown czyta jako strukturę (`-` zrobiłby z dywizu punkt listy) -
    wtedy spada razem z nim poprzednie słowo."""
    linie, biezaca = [], []
    for slowo in tekst.split(" "):
        prefiks = pierwszy if not linie else dalszy
        kandydat = prefiks + " ".join(biezaca + [slowo])
        if biezaca and len(kandydat) > szer:
            nowa = [slowo]
            if _zly_poczatek(slowo) and len(biezaca) > 1:
                nowa = [biezaca.pop(), slowo]
            linie.append(prefiks + " ".join(biezaca))
            biezaca = nowa
        else:
            biezaca.append(slowo)
    linie.append((pierwszy if not linie else dalszy) + " ".join(biezaca))
    return linie


def _znacznik(b: Blok) -> str:
    return WAGI[b.pola["waga"]] + ("🅿" if b.pola["stan"] == "zaparkowany" else "")


def indeks(rej: Rejestr) -> tuple:
    """Jednolinijkowy indeks otwartych ID wg fal i torów: fale w kolejności numerów (tory w kolejności
    pola `fala:`), potem tory spoza fal (kolejność `tory:`), na końcu decyzje bez toru. Etykiety
    torów są gołe (pogrubienie 16 etykiet kosztowało linię budżetu), nigdy w backtickach - backtick
    w indeksie znaczy wyłącznie ID. Zwraca (tekst, liczba ID)."""
    otwarte = rej.otwarte()
    bez_id = {}
    for p in rej.bez_id:
        bez_id.setdefault(p.tor, []).append(p.opis)

    def czlon(tor):
        ids = [f"`{b.ident}`{_znacznik(b)}" for b in otwarte if b.pola["tor"] == tor]
        opisy = bez_id.get(tor, [])
        if not ids and not opisy:
            return None
        c = ["**decyzje**" if tor == TOR_DECYZJA else tor] + ids
        c += [("+ " if (ids or i) else "") + o for i, o in enumerate(opisy)]
        return " ".join(c)

    czesci, w_falach = [], set()
    for f in rej.fale:
        w_falach.update(f.tory)
        cz = [c for c in map(czlon, f.tory) if c]
        if cz:
            czesci.append(f"**fala {f.nr}:** " + " · ".join(cz))
    reszta = [c for c in map(czlon, [t for t in rej.tory()[:-1] if t not in w_falach]) if c]
    if reszta:
        czesci.append("**poza falami:** " + " · ".join(reszta))
    decyzje = czlon(TOR_DECYZJA)
    if decyzje:
        czesci.append(decyzje)
    tekst = (f"**Otwarte ID wg fal i torów ({len(otwarte)}; 🟡/🔴 = decyzja nie/blokująca, "
             f"🅿 = zaparkowane):** " + " · ".join(czesci))
    # ⛔ Druga kontrola, niezależna od filtra wyżej: ID odczytane Z WYPISANEGO TEKSTU mają dać
    # dokładnie zbiór bloków otwartych/zaparkowanych. Filtr, który zgubi tor albo stan,
    # zgodziłby się ze sobą przy równości bajtowej - ta asercja nie (niezmiennik 10 skilla).
    wypisane = [t for t in KOD_W_BACKTICKU.findall(tekst) if ID_RE.fullmatch(t)]
    oczekiwane = sorted(b.ident for b in otwarte)
    if sorted(wypisane) != oczekiwane:
        raise RuntimeError(f"generat zgubił albo zdublował ID: wypisane {sorted(wypisane)}, "
                           f"otwarte w rejestrze {oczekiwane}")
    return tekst, len(otwarte)


def generuj_start(rej: Rejestr) -> list:
    """Rejestr BEZ błędów schematu -> linie bloku START. Zero zegara: ten sam rejestr daje ten
    sam bajt w każdym procesie, inaczej porównanie bajt w bajt nie znaczyłoby nic."""
    if rej.bledy:
        raise ValueError("rejestr oblewa schemat - START się nie generuje")
    s = {k: v[0] for k, v in rej.stan.items() if k in POLA_STANU}
    linie = [MARKER, ""]
    linie += zawin("BLOK GENEROWANY (`python scripts/kolejka_start.py start --zapisz`) - nie "
                   "edytuj ręcznie; treść w `rejestr_dlugow.md`.", "> ", "> ")
    linie += [""] + zawin(f"**Stan (sesja {s['sesja']}):** {s['stan']}")
    linie += [""] + zawin(f"**Następny krok:** {s['nastepny-krok']}")
    linie += [""] + zawin(f"**⚙ Następna sesja:** {s['model-nastepnej']}")
    czerwone = [b for b in rej.otwarte() if b.pola["waga"] == "czerwona"]
    if czerwone:
        linie += ["", "**Decyzje BLOKUJĄCE (🔴) - treść w rejestrze, tytuł tutaj:**"]
        for b in czerwone:
            linie += zawin(f"`{b.ident}` {b.tytul}", "- ", "  ")
    tekst_indeksu, _ = indeks(rej)
    linie += [""] + zawin(tekst_indeksu)
    linie += [""] + zawin(f"**ZAMKNIĘTE - NIE WRACAĆ:** {s['nie-wracac']}")
    tripwiry = rej.stan.get("tripwir", [])
    if tripwiry:
        linie += ["", "**Tripwiry:**"]
        for t in tripwiry:
            linie += zawin(t, "- ", "  ")
    linie += [""] + zawin("Treść ID: `rejestr_dlugow.md` (`grep -n \"^## <ID> ·\"`) · schemat i "
                          "kompletność: `sprawdz` · zgodność: `start --sprawdz`.")
    if len(linie) > LIMIT_LINII_STARTU:
        raise BladBudzetu(f"FAIL: krok zbyt szeroki - START ma {len(linie)} linii, limit "
                          f"{LIMIT_LINII_STARTU}; skróć pola STAN albo domknij ID (bez obcinania)")
    return linie


# --- szwy torów ------------------------------------------------------------------------------

def pliki_siedziby(tekst: str, korzen: Path, cache: dict | None = None) -> tuple:
    """Backtickowane ścieżki plików z pola `siedziba:` -> (zbiór ścieżek względem korzenia repo,
    lista goły-plik-niejednoznaczny). Goła nazwa (`resolver.py`) dostaje ścieżkę, gdy w `horreum/`,
    `scripts/` i `tests/` jest DOKŁADNIE jeden taki plik - inaczej ta sama jednostka pod dwiema
    pisowniami minęłaby się w porównaniu szwów. Zero trafień = plik planowany, zostaje jak stoi."""
    cache = {} if cache is None else cache
    pliki, niejednoznaczne = set(), []
    for token in KOD_W_BACKTICKU.findall(tekst):
        m = PLIK_RE.match(token.strip())
        if not m:
            continue
        sciezka = m.group(0).replace("\\", "/").removeprefix("./")
        if "/" not in sciezka:
            if sciezka not in cache:
                trafienia = sorted({p.relative_to(korzen).as_posix()
                                    for kat in ("horreum", "scripts", "tests")
                                    if (korzen / kat).is_dir()
                                    for p in (korzen / kat).rglob(sciezka)
                                    if "__pycache__" not in p.parts})
                cache[sciezka] = trafienia
            trafienia = cache[sciezka]
            if len(trafienia) == 1:
                sciezka = trafienia[0]
            elif trafienia:
                niejednoznaczne.append(f"{sciezka} ({len(trafienia)} trafień)")
        pliki.add(sciezka)
    return pliki, niejednoznaczne


def szwy(rej: Rejestr, korzen: Path, tory_zakres) -> tuple:
    """Skład szwów torów z zakresu -> ({tor: {plik: [kto]}}, [meldunki szwu nieznanego])."""
    sklad, nieznane, cache = {t: {} for t in tory_zakres}, [], {}

    def dopisz(tor, kto, siedziba):
        pliki, niejednoznaczne = pliki_siedziby(siedziba or "", korzen, cache)
        for n in niejednoznaczne:
            nieznane.append(f"SZEW NIEZNANY {tor}: {kto} - goła nazwa {n}, podaj ścieżkę")
        if not pliki:
            powod = "brak `siedziba:`" if not siedziba else "siedziba bez ścieżki pliku"
            nieznane.append(f"SZEW NIEZNANY {tor}: {kto} ({powod})")
        for p in pliki:
            sklad[tor].setdefault(p, []).append(kto)

    for b in rej.otwarte():
        if b.pola["tor"] in sklad:
            dopisz(b.pola["tor"], b.ident, b.pola.get("siedziba"))
    for p in rej.bez_id:
        if p.tor in sklad:
            dopisz(p.tor, p.opis, p.siedziba)
    return sklad, nieznane


def kolizje(fala: Fala, sklad: dict) -> list:
    """Pary torów jednej fali dzielące plik spoza `DOZWOLONE_WSPOLNE` -> meldunki FAIL."""
    wynik = []
    for i, a in enumerate(fala.tory):
        for b in fala.tory[i + 1:]:
            for plik in sorted(set(sklad[a]) & set(sklad[b]) - set(DOZWOLONE_WSPOLNE)):
                wynik.append(f"FAIL fala {fala.nr}: {a} × {b} · {plik} "
                             f"({a}: {' '.join(sklad[a][plik])}; {b}: {' '.join(sklad[b][plik])})")
    return wynik


# --- kolejka ---------------------------------------------------------------------------------

def znajdz_start(linie: list) -> tuple:
    """Granice bloku START: (a, b) = linie[a:b]. Reguła właściciela `domknij.py:znajdz_start`
    (skill `kolejka-sesji`) odtworzona tutaj, bo skrypt repo musi być hermetyczny; jego kontrakt
    przypięty jest przypadkami w `tests/test_kolejka_start.py`. Marker musi ZACZYNAĆ linię:
    `## ⏭` (koniec: najbliższe `## `) albo `> ⏭` (koniec: pierwsza linia niepusta bez `>`)."""
    a = styl = None
    for i, ln in enumerate(linie):
        if ln.lstrip().startswith("## ⏭"):
            a, styl = i, "naglowek"
            break
        if ln.startswith("> ⏭"):
            a, styl = i, "blockquote"
            break
    if a is None:
        raise BladPomiaru("nie ma markera STARTU - linia zaczynająca się od '## ' albo '> ' "
                          "ze znakiem U+23ED tuż za nim")
    b = len(linie)
    for i in range(a + 1, len(linie)):
        if styl == "naglowek" and linie[i].startswith("## "):
            b = i
            break
        if styl == "blockquote" and not linie[i].startswith(">") and linie[i].strip() != "":
            b = i
            break
    return a, b


def _konce(tekst: str) -> str:
    """Jednolity koniec wiersza kolejki albo BladPomiaru. CRLF w całości jest dozwolony
    i ZACHOWANY przy zapisie - porównanie idzie po liniach, więc nie daje fałszywego rozjazdu."""
    crlf, cr, lf = tekst.count("\r\n"), tekst.count("\r"), tekst.count("\n")
    if cr != crlf or (crlf and crlf != lf):
        raise BladPomiaru("kolejka ma MIESZANE końce wiersza (LF/CRLF/CR) - ujednolić ręcznie")
    return "\r\n" if crlf else "\n"


def _bez_ogona(linie: list) -> list:
    koniec = len(linie)
    while koniec and not linie[koniec - 1].strip():
        koniec -= 1
    return linie[:koniec]


def porownaj(tekst_kolejki: str, generat: list):
    """None przy zgodności, inaczej (nr linii kolejki 1-based, linia kolejki, linia generatu)."""
    nl = _konce(tekst_kolejki)
    linie = tekst_kolejki.split(nl)
    a, b = znajdz_start(linie)
    blok = _bez_ogona(linie[a:b])
    for i in range(max(len(blok), len(generat))):
        stara = blok[i] if i < len(blok) else None
        nowa = generat[i] if i < len(generat) else None
        if stara != nowa:
            return a + i + 1, stara, nowa
    return None


def wstaw(tekst_kolejki: str, generat: list) -> str:
    """Kolejka z podmienionym blokiem. Puste linie ogona zostają, jakie były - generator
    wymienia treść, nie układ pliku."""
    nl = _konce(tekst_kolejki)
    linie = tekst_kolejki.split(nl)
    a, b = znajdz_start(linie)
    ogon = (b - a) - len(_bez_ogona(linie[a:b]))
    return nl.join(linie[:a] + generat + [""] * ogon + linie[b:])


def zapisz_atomowo(sciezka: Path, tekst: str) -> None:
    tmp = sciezka.with_name(sciezka.name + ".tmp-kolejka-start")
    tmp.write_bytes(tekst.encode("utf-8"))
    os.replace(tmp, sciezka)


# --- CLI -------------------------------------------------------------------------------------

def _wczytaj_rejestr(args) -> Rejestr:
    rej = rozbierz(czytaj_tekst(Path(args.rejestr)))
    sprawdz_kompletnosc(rej, Path(args.kod))
    return rej


def _meldunek_bledow(rej: Rejestr) -> int:
    print(f"FAIL: rejestr oblewa schemat ({len(rej.bledy)}):")
    for b in rej.bledy:
        print("  " + b)
    return 1


def cmd_sprawdz(args) -> int:
    rej = _wczytaj_rejestr(args)
    return _meldunek_bledow(rej) if rej.bledy else 0


def cmd_start(args) -> int:
    rej = _wczytaj_rejestr(args)
    if rej.bledy:
        return _meldunek_bledow(rej)
    try:
        generat = generuj_start(rej)
    except BladBudzetu as e:
        print(e)
        return 1
    if not (args.sprawdz or args.zapisz):
        sys.stdout.write("\n".join(generat) + "\n")
        return 0
    sciezka = Path(args.kolejka)
    tekst = czytaj_tekst(sciezka)
    roznica = porownaj(tekst, generat)
    if args.sprawdz:
        if roznica is None:
            return 0
        nr, stara, nowa = roznica
        print(f"ROZJAZD: START w kolejce różni się od generatu od linii {nr} kolejki")
        print(f"  kolejka: {'(koniec bloku)' if stara is None else stara[:SZEROKOSC]}")
        print(f"  generat: {'(koniec generatu)' if nowa is None else nowa[:SZEROKOSC]}")
        print("  naprawa: zmień rejestr, potem `python scripts/kolejka_start.py start --zapisz`")
        return 1
    if roznica is not None:
        zapisz_atomowo(sciezka, wstaw(tekst, generat))
    return 0


def cmd_tory(args) -> int:
    rej = _wczytaj_rejestr(args)
    if rej.bledy:
        return _meldunek_bledow(rej)
    fale = rej.fale
    if args.fala is not None:
        fale = [f for f in fale if f.nr == args.fala]
        if not fale:
            raise BladPomiaru(f"nie ma fali {args.fala} w STAN (`fala:`)")
        zakres = [t for f in fale for t in f.tory]
    else:
        zakres = list(rej.tory())
    sklad, nieznane = szwy(rej, Path(args.kod).resolve().parent, zakres)
    meldunki = [m for f in fale for m in kolizje(f, sklad)] + nieznane
    if args.pokaz:
        w_falach = set()
        for f in fale:
            w_falach.update(f.tory)
            print(f"fala {f.nr} {f.nazwa} (przed: {' '.join(f.przed) or '-'})")
            for t in f.tory:
                print(f"  {t}: {' '.join(sorted(sklad[t])) or '-'}")
        reszta = [t for t in zakres if t not in w_falach]
        if reszta:
            print("poza falami")
            for t in reszta:
                print(f"  {t}: {' '.join(sorted(sklad[t])) or '-'}")
    for m in meldunki:
        print(m)
    return 1 if meldunki else 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="kolejka_start.py", description=__doc__.split("\n")[0])
    p.add_argument("--rejestr", default=str(REJESTR))
    p.add_argument("--kolejka", default=str(KOLEJKA))
    p.add_argument("--kod", default=str(KOD))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sprawdz")
    s = sub.add_parser("start")
    tryb = s.add_mutually_exclusive_group()
    tryb.add_argument("--sprawdz", action="store_true")
    tryb.add_argument("--zapisz", action="store_true")
    t = sub.add_parser("tory")
    t.add_argument("--fala", type=int)
    t.add_argument("--pokaz", action="store_true")
    args = p.parse_args(argv)
    try:
        return {"sprawdz": cmd_sprawdz, "start": cmd_start, "tory": cmd_tory}[args.cmd](args)
    except BladPomiaru as e:
        print(f"BŁĄD (nie da się zmierzyć): {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
