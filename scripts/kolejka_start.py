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
Wspólne flagi: --rejestr, --kolejka, --kod (domyślnie względem korzenia repo).

Kody wyjścia: 0 OK (cisza) | 1 błąd schematu, rozjazd, budżet STARTU przekroczony - plik
NIETKNIĘTY | 2 nie da się zmierzyć (brak pliku, brak markera, mieszane końce wiersza, zły UTF-8).

FORMAT REJESTRU. Blok zaczyna nagłówek `## ` w pierwszej kolumnie (poza płotkiem kodu):
  `## STAN`              pola sesji: sesja, stan, nastepny-krok, model-nastepnej, nie-wracac,
                         paczki (każde raz) oraz powtarzalne tripwir i paczka-bez-id.
  `## <ID> · <tytuł>`    dług albo decyzja: pola stan, waga, paczka (wymagane), kiedy, siedziba,
                         zamkniete (opcjonalne); pola ZARAZ pod nagłówkiem, potem pusta linia i proza.
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
# skrócić pola STAN albo domknąć ID.
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

POLA_STANU = ("sesja", "stan", "nastepny-krok", "model-nastepnej", "nie-wracac", "paczki")
POLA_STANU_WIELE = ("tripwir", "paczka-bez-id")
POLA_ID_WYMAGANE = ("stan", "waga", "paczka")
POLA_ID_OPCJONALNE = ("kiedy", "siedziba", "zamkniete")
STANY = ("otwarty", "zaparkowany", "zamkniety")
WAGI = {"-": "", "zolta": "🟡", "czerwona": "🔴"}
PACZKI_STALE = ("poza", "decyzja")
ETYKIETY = {"poza": "**poza paczkami**", "decyzja": "**decyzje**"}

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
class Rejestr:
    stan: dict | None = None            # nazwa -> lista wartości (pola jednokrotne mają jedną)
    bloki: list = field(default_factory=list)
    bledy: list = field(default_factory=list)

    def otwarte(self):
        return [b for b in self.bloki if b.pola.get("stan") in ("otwarty", "zaparkowany")]

    def paczki(self):
        return tuple((self.stan or {}).get("paczki", [""])[0].split()) + PACZKI_STALE


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
        dziedzina = rej.paczki()
        for b in rej.bloki:
            p = b.pola.get("paczka")
            if p is not None and p not in dziedzina:
                rej.bledy.append(f"linia {b.nr}: {b.ident}: paczka `{p}` spoza dziedziny "
                                 f"{' '.join(dziedzina)}")
        for wartosc in rej.stan.get("paczka-bez-id", []):
            litera = wartosc.split(" ")[0]
            if litera not in dziedzina:
                rej.bledy.append(f"STAN: paczka-bez-id `{litera}` spoza dziedziny")
            if any(ID_RE.fullmatch(t) for t in KOD_W_BACKTICKU.findall(wartosc)):
                rej.bledy.append(f"STAN: paczka-bez-id `{litera}` niesie identyfikator - ID "
                                 "dostaje własny blok, inaczej zniknie z kontroli kompletności")
    return rej


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
    paczki = stan.get("paczki", [""])[0].split()
    if len(set(paczki)) != len(paczki) or set(paczki) & set(PACZKI_STALE):
        bledy.append(f"linia {nr}: STAN: `paczki:` z powtórzeniem albo z członem "
                     f"{'/'.join(PACZKI_STALE)} (te są stałe, dopisuje je generator)")
    jak_id = [p for p in paczki if ID_RE.fullmatch(p)]
    if jak_id:
        # Etykieta paczki stoi w indeksie w backtickach jak ID, więc `K7` wyglądałby tam na
        # identyfikator i kontrola kompletności generatu pękłaby na zdrowym rejestrze.
        bledy.append(f"linia {nr}: STAN: nazwa paczki wygląda na ID ({' '.join(jak_id)}) - "
                     "paczka to litera albo słowo bez cyfry i dywizu")
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
    """Jednolinijkowy indeks otwartych ID wg paczek. Zwraca (tekst, liczba ID)."""
    otwarte = rej.otwarte()
    bez_id = {}
    for wartosc in rej.stan.get("paczka-bez-id", []):
        litera, _, opis = wartosc.partition(" ")
        bez_id.setdefault(litera, []).append(opis.strip())
    czesci = []
    for p in rej.paczki():
        ids = [f"`{b.ident}`{_znacznik(b)}" for b in otwarte if b.pola["paczka"] == p]
        opisy = bez_id.get(p, [])
        if not ids and not opisy:
            continue
        czlon = [ETYKIETY.get(p, f"`{p}`")] + ids
        czlon += [("+ " if (ids or i) else "") + o for i, o in enumerate(opisy)]
        czesci.append(" ".join(czlon))
    tekst = (f"**Otwarte ID wg paczek ({len(otwarte)}; 🟡 = decyzja nieblokująca, 🔴 = blokująca, "
             f"🅿 = zaparkowane):** " + " · ".join(czesci))
    # ⛔ Druga kontrola, niezależna od filtra wyżej: ID odczytane Z WYPISANEGO TEKSTU mają dać
    # dokładnie zbiór bloków otwartych/zaparkowanych. Filtr, który zgubi paczkę albo stan,
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
    args = p.parse_args(argv)
    try:
        return {"sprawdz": cmd_sprawdz, "start": cmd_start}[args.cmd](args)
    except BladPomiaru as e:
        print(f"BŁĄD (nie da się zmierzyć): {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
