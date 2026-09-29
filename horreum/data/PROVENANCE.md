# Proweniencja assetów DANYCH rdzenia (katalog celów planera, lista rojów meteorów)

> Kod repozytorium jest na licencji **MIT**. Pliki w tym katalogu to **DANE** i noszą własne
> licencje — poniżej per źródło. Rozdział jest jawny także w polu `_meta.license` każdego assetu.

## `targets_core.json` + `targets_cirrus.json` — pula celów deep-sky

- **Producent:** `scripts/build_catalog.py` (dev; jedyne miejsce w repo, które wychodzi do sieci).
  Aplikacja **nigdy** nie woła sieci — katalog odświeża się PODMIANĄ pliku (D-0731-3).
- **Rozdział na dwa pliki:** `core` = NGC/IC, Sh2, vdB, Green SNR; `cirrus` = LBN/LDN, warstwa
  domyślnie wyłączona (D-0731-9). Warstwę rozstrzyga źródło ZWYCIĘZCY grupy po scaleniu, więc
  np. `LDN1174` jedzie w rdzeniu jako część `NGC7023`.

### Źródła

| Katalog | Skąd | Licencja / cytowanie |
|---|---|---|
| **OpenNGC** (`NGC.csv`, `addendum.csv`) | `github.com/mattiaverga/OpenNGC`, katalog `database_files` | **CC-BY-SA-4.0**, autor Mattia Verga. DOI `10.21938/y.1ejWUD_MQ6b_eDFoVbbw` |
| **Sharpless HII** `VII/20` | VizieR (CDS), `asu-tsv` | CDS/VizieR — cytowanie: Sharpless S., 1959, ApJS 4, 257 |
| **Lynds Bright Nebulae** `VII/9` | VizieR (CDS) | CDS/VizieR — Lynds B.T., 1965, ApJS 12, 163 |
| **Lynds Dark Nebulae** `VII/7A` | VizieR (CDS) | CDS/VizieR — Lynds B.T., 1962, ApJS 7, 1 |
| **van den Bergh (reflection)** `VII/21` | VizieR (CDS) | CDS/VizieR — van den Bergh S., 1966, AJ 71, 990 |
| **Galactic SNR (Green)** `VII/278` | VizieR (CDS) | CDS/VizieR — Green D.A., Cavendish Laboratory |

**Skutek licencyjny (świadomy):** asset jest utworem pochodnym m.in. od OpenNGC, więc **dane**
w `targets_core.json`/`targets_cirrus.json` rozpowszechniamy na **CC-BY-SA-4.0**. Kod (`horreum/*.py`,
`scripts/*.py`) pozostaje MIT. Korzystanie z VizieR/CDS wymaga podania powyższej atrybucji.

**D-T2-f ✅ ROZSTRZYGNIĘTE 2026-08-04, GO Zdzinia: rozdział ZOSTAJE** — kod MIT, dane CC-BY-SA,
granica jawna tutaj i w polu `_meta.license` każdego assetu. Rozważana alternatywa („bez OpenNGC",
czyli jednolity MIT w całym repo) była **odrzucona świadomie i z policzonym kosztem: 946 rekordów
rdzenia i WSZYSTKIE galaktyki** — populacja, która w archiwum niesie 136,9 h materiału. Ta decyzja
wiąże każdy nowy asset danych: źródło na CC-BY-SA wchodzi z atrybucją do tabeli wyżej, a nie przez
rozmycie granicy.

### Przetworzenie (co skrypt robi z surowymi tabelami)

1. **Epoki** — Sh2 niesie B1900, LBN/LDN B1950, vdB/Green J2000. **Nie precesujemy sami**: bierzemy
   kolumny policzone po stronie VizieR (`_RAJ2000`/`_DEJ2000`, `_RA.icrs`/`_DE.icrs`). Surowe
   `RA1900`/`RA1950` leżą w tym samym pliku obok — pomyłka o kolumnę to 0,5–1,2° błędu, więc każdy
   z dwóch torów epokowych ma własną kotwicę-falsyfikator (`Sh2-184`↔`NGC281`, `LBN654`↔`IC1805`).
2. **Odsianie** — typy `{OCl,GCl,*,**,*Ass,Dup,NonEx,Other,Nova}`, wiersze bez pozycji lub bez
   rozmiaru, komponenty NED (`… NED01`). Podłoga rozmiaru: **3′** (ciemne **8′**) — techniczna,
   z zapasem pod najniższym położeniem suwaka w GUI; **magnitudo NIE filtruje** (dla mgławicy
   emisyjnej kłamie), jedzie jako pole.
3. **Scalanie tożsamości** trzema kluczami: kanon (`xref(catalog_canon(…))`) → alias katalogu →
   pozycja (tylko między katalogami, tolerancja `0,35 × większa oś`, bramka proporcji `≥ 0,50`).
   Przegrani nie giną — ich oznaczenia wchodzą do listy aliasów `n`.
4. **Rozmiar LDN** = koło równoważne z pola `Area` [deg²] (katalog nie podaje średnicy). Dla
   filamentu to przybliżenie zawyżające zwartość — nie brać za pomiar.
5. **Typ** dla źródeł bez własnej typologii przypisany z definicji katalogu (Sh2→`HII`, LBN→`EmN`,
   LDN→`DrkN`, vdB→`RfN`, Green→`SNR`).

### Format

Jeden rekord = jedna linia (czytelny diff przy podmianie katalogu), plik pozostaje legalnym JSON-em.
Klucze: `c` kanon · `t` typ · `r`/`d` RA/Dec J2000 [°] · `a`/`b` oś większa/mniejsza [′] ·
`m` magnitudo (+`mb`, gdy pochodzi z B — B−V galaktyk to +0,7…1,0 mag) · `n` aliasy i nazwy potoczne.

## `../resolve/data/objects_own.json` — obiekty bez wpisu katalogowego

**Plik człowieka** (do 2026-08-03 `horreum/data/curated.json`; przeniesiony przy D-OW-1/E′, bo
czytają go DWIE warstwy — planer bierze z niego cele, resolver same nazwy).
`build_catalog.py` go waliduje (schemat + unikalność kanonu w sumie plików) i **nigdy nie
nadpisuje**; jego BRAK jest błędem budowy, nie pustą listą. Scalanie z automatem należy do loadera
(T3), gdzie warstwa `curated` wygrywa. Każdy wpis niesie `why` (dlaczego automat go nie ma),
`provenance` (skąd pozycja) i — gdy jest celem — `size_source` (`user`, gdy rozmiar jest
oszacowaniem, a nie pomiarem).

**LICENCJA: MIT, jak kod.** Ten plik jest pisany RĘKĄ i nie zawiera danych pochodnych z OpenNGC
ani z żadnego źródła CC-BY-SA — rozdział „kod MIT / dane CC-BY-SA" (D-T2-f) go nie obejmuje.
Wpis, który kiedyś przepisze pozycję z katalogu na tej licencji, musi to odnotować we własnym
polu `provenance` i wtedy dziedziczy jej warunki.

## `meteor_showers.json` - lista rojów meteorów (test radiantu detektora śladów)

- **Producent:** `scripts/build_showers.py --src <plik MDC>` (dev; bez `--src` pobiera plik z sieci).
  Aplikacja **nigdy** nie woła sieci - lista odświeża się PODMIANĄ pliku (D-0731-3). Czyta ją
  `horreum.streaks.load_showers()`.
- **Źródło:** IAU Meteor Data Center, „Established meteor showers” V.2 (plik
  `streamestablisheddata2026.txt`, wzorzec adresu w `URL` skryptu). Nagłówek pliku: „Last update:
  Sep 21, 20:00:00 UTC, 2026, Modified by R. Rudawska, M. Hajdukova and T.J. Jopek”. Kopia lokalna
  z 2026-09-28 (`est2026.txt`, sha1 `b08c7b92afaf0f612b496588d4bef46be22069e7`, 426 134 B).
- **Budowa:** 2026-09-29 (`_meta.built`); **112 rojów**, zakres aktywności szacowany 0, dryf
  radiantu szacowany 1 (COR - zestaw bez `dRa`/`dDe`, `dra`/`ddec` = null). Reguła wyboru zestawu
  w docstringu skryptu i w `_meta.selection`; problemy pliku (4 pola niebędące liczbą, 1 zestaw bez
  RA/Dec) skrypt wypisuje z numerem linii - żaden nie zmienia wyboru poza COR (plan meteorów §1a).
- **Wersja assetu** = para `_meta.built` + `_meta.source_updated`; wchodzi do `config_hash` trybu
  bazy (plan meteorów §2, manifest przebiegu).
- **Licencja:** MDC nie deklaruje licencji danych. Warunkiem użycia, który podaje nagłówek pliku
  („Notes on proper citation of the MDC database”), jest cytowanie: Jenniskens P. i in., 2020,
  Planetary and Space Science 182, 104821; Jopek T.J., Kanuchova Z., 2017, PSS 143, 3-6 (pełna lista
  w nagłówku pliku). Ten sam zapis niesie `_meta.license`; kod repozytorium pozostaje MIT.

## Odczyt w kodzie

`importlib.resources.files("horreum.data")` — wzorzec `horreum.resolve.data` i `horreum.schema.migrations`.
Pakiet jest wnoszony do wheela przez `[tool.setuptools.package-data]`, a do frozen przez
`collect_data_files("horreum", includes=["**/*.json"])` + `hiddenimports` w obu specach.
