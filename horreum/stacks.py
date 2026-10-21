"""RODOWÓD GOTOWYCH STOSÓW — co weszło w ten obraz (segment I-2c, paczka P-I). Siostra `lineage`.

`lineage` (C4) odpowiada „czym skalibrowano tę klatkę", ten moduł — „z czego zrobiono ten stos".
Obie osie łączy kształt (Qt-wolne, zapis wyłącznie przez `repo`, SELECT literałem, idempotencja na
UNIQUE, kubełki „czego nie wiemy"), ale różni je ŹRÓDŁO PEWNOŚCI i to jest sedno projektu:

  * kalibrator wylicza się z PRZEPISU, który obie strony niosą w nagłówku — wynik jest faktem;
  * wejścia stosu wylicza OKNO CZASU mastera, a to jest KANDYDAT, nie fakt. Dowieść go potrafi
    tylko `PixInsight:ProcessingHistory` (zeznanie pliku o samym sobie), i to na mniejszości
    plików. Stąd trójstan `asserted_by` (`history` / `window` / `user`) i strażniki niżej.

NAZWY NAJPIERW, OKNO POTEM (AR-108, E4-9, D-1011-4). Historia niesie nazwy wejść z CHWILI OBRÓBKI;
wobec nazw bieżących archiwum milczy (0/36 - Custos przemianował pliki po obróbce), ale z dawnymi
nazwami lightów (`light_name_alias`: zapis przenosin Custos i zmiany nazw Horreum) daje pełny zbiór
dla 28 z 33 stosów rangi `history` i 20 z 26 dawnych `history_mismatch` (sonda 2026-10-11, kopia
pf4). Pełny, unikalny zbiór z nazw wskazuje klatki wprost (`lineage_basis='name'`), także poza
oknem nagłówka. Gdzie nazwy milczą, historia WERYFIKUJE zbiór wybrany oknem
(`resolve.stack.inputs_contained`: wielozbiór temperatur z nazw WBPP wobec temperatur klatek okna -
`temp`, albo sam licznik - `count`), a okno szersze od zeznania dostaje werdykt „plik użył N z M
klatek okna” (`used_rows`) zamiast odmowy.

TRZY STRAŻNIKI — każdy gasi konkretną, ZMIERZONĄ nieprawdę (brief P-I §4.2):
  1. **okno zdegenerowane** (`DATE-END ≈ DATE-OBS + EXPTIME`) → ZERO relacji. 23 z 84 masterów
     starszego rocznika opisuje nagłówkiem JEDNĄ klatkę; bez tego strażnika stos dostałby jeden
     sub i wyglądałby wiarygodnie. Cicha nieprawda jest gorsza niż brak odpowiedzi.
  2. **rozjazd z historią** → ZERO relacji. Gdy plik zeznał, z czego powstał, a okno wybrało inny
     zbiór (nie nadzbiór - ten dostaje „N z M”), to okno się MYLI - a nie historia.
  3. **okna nierozłączne** (43 pary tej samej półki, reprocessingi tej samej nocy) → `ambiguous=1`.
     Relacje zostają, ale most do planera (I-2e) MUSI liczyć taki sub raz.

Czas idzie przez `naming.header_dt` (SPOT parser ISO) — NIGDY po stringu: master zapisuje
`…02.608`, klatka `…02.6075262`, więc porządek leksykalny gubi pierwszy sub okna. Filtr i teleskop
porównujemy po OSIACH, nie po surowych napisach nagłówka: `frame.filter_canon` (resolver, oś
kind-agnostyczna — master dostaje ją tak samo jak light) i `telescope_canonical` (kanon po
scaleniach). Inaczej naprawa `ED`→`ED120R` rozspójniłaby rodowód ze wszystkim, co repo wie.

KROK ZBIORCZY PO `group` I `resolve` — tak jak `lineage` idzie po `calibrate`: dobór stoi na osi
obiektu i osi teleskopu, więc puszczony przed nimi widziałby same `no_object`.

HISTORIA Z BAZY (AR-87, 0034): historia mieszka w XML-u nagłówka XISF; skan zapisuje ją przy kopii
(`stack_history`, kotwica = odcisk nagłówka), a uzupełnienie dociąga stosy sprzed migracji. Ten
moduł czyta plik z dysku - READ-ONLY, sam nagłówek (`scan.read_xisf_meta_full`) - wyłącznie, gdy
wiersza brak albo kotwica rozjechała się z nagłówkiem kopii, i wtedy odświeża wiersz
(`history_reads`/`history_refreshed`). Plik nieosiągalny nie jest błędem przebiegu: stos schodzi
na ścieżkę okna i jest to POLICZONE (`history_unread`), nie przemilczane.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import repo
from .hashing import sha1_of_set
from .naming import header_dt
from .resolve import stack as rstack
from .resolve._coerce import _to_float
from .resolve.headers import copy_testimony

# Powody, dla których stos NIE dostaje wejść. Wartości = tokeny CHECK-a migracji 0012 (baza jest
# ostatnią bramką słownika, jak przy `target_plan.status`), proza należy do powierzchni.
REASON_DEGENERATE = "degenerate_window"
REASON_MISMATCH = "history_mismatch"
REASON_NO_OBJECT = "no_object"
REASON_NO_WINDOW = "no_window"
REASON_NO_CANDIDATES = "no_candidates"
REASON_TELESCOPE = "telescope_mismatch"
REASON_OFFSET_UNKNOWN = "offset_unknown"

# PODSTAWA rangi `history` (AR-108, D-1011-4) - tokeny CHECK-a 0034 (`integration.lineage_basis`)
# i JEDYNY zbiór, z którego powierzchnia składa zdanie (`grid.lin.basis.{token}`, parytet w testach
# i18n): `name` - pełny, unikalny zbiór po nazwach wejść historii; `temp` - podzbiór okna potwierdzony
# temperaturami z nazw WBPP; `count` - nazwy bez temperatury, okno równe liczbie wejść.
BASIS_NAME = "name"
BASIS_TEMP = "temp"
BASIS_COUNT = "count"
LINEAGE_BASES = (BASIS_NAME, BASIS_TEMP, BASIS_COUNT)
# Klucz licznika `by_basis` dla werdyktu „plik użył N z M klatek okna” - nie jest podstawą rangi
# `history` (wiersze zostają `window`), więc nie wchodzi do `LINEAGE_BASES` ani do bazy.
BASIS_SUBSET = "subset"

EXP_TOL_FLOOR_S = 0.5
"""Podłoga tolerancji ekspozycji — poniżej niej próg nie schodzi nawet dla krótkich klatek."""

EXP_TOL_FRACTION = 0.02
"""Człon względny progu (2%) — liczony od KRÓTSZEJ z dwóch ekspozycji (patrz `exposure_matches`)."""

EXP_TOL_CEILING_S = 3.0
"""Sufit tolerancji. Bez niego próg względny rósł bez ograniczenia i przy 600 s dawał 12 s, czyli
sklejał 600 z 610 — dwie różne nastawy tej samej nocy (W11)."""


def exposure_matches(a, b):
    """Czy dwie ekspozycje [s] to TA SAMA nastawa — JEDYNY właściciel progu D-DR-2 (SPOT).

    `tol(a,b) = min( max(0,5 s; 2% · min(a,b)); 3,0 s )`, dopasowanie iff `|a−b| <= tol(a,b)`.

    DLACZEGO PRÓG, A NIE RÓWNOŚĆ: dla lustrzanki ekspozycja jest POMIAREM — master IC443 zeznaje
    `90,0`, a jego trzy suby `90,0 / 91,0 / 91,0`, więc równość wpuszcza jedną z trzech i nazywa
    to kompletnym rodowodem. Próg naprawia jednostkę porównania, nie poszerza doboru „na wszelki
    wypadek".

    PRÓG OBOWIĄZUJE WSZYSTKIE FORMATY, NIE TYLKO RAW — i to jest świadome, ale wcześniejszy zapis
    tego zdania sugerował, że dla ASI zostaje równość (bramka pakietu, zarzut 1: docstring
    obiecywał więcej, niż droga dowozi — ta sama klasa co E2-1). Dla ASI ekspozycja jest NASTAWĄ
    i wraca co do setnej, więc próg nie ma tam czego skleić — ale to jest fakt o DANYCH, nie
    gałąź w kodzie. Pokrycie pomiarowe: bramka G2-6 na żywym archiwum zmierzyła **0 nowych
    kandydatów** w gałęzi ASI po wprowadzeniu progu (wejścia `3367 fits` bez ruchu). Gałąź per
    format byłaby drugą regułą do utrzymania tam, gdzie pomiar mówi, że jedna wystarcza.

    TRZY CZŁONY, KAŻDY Z POWODU: **podłoga** trzyma sens dla krótkich klatek (2% z 10 s to 0,2 s,
    czyli mniej niż rozdzielczość zeznania); **`min(a,b)`** zamiast `a` czyni relację choć
    SYMETRYCZNĄ (`tol(a,b) == tol(b,a)`); **sufit** powstrzymuje próg względny przed sklejeniem
    600 z 610 (W11 — v2 briefu obiecywał sufit w prozie, a formuła rosła bez ograniczenia).

    RELACJA NIE JEST PRZECHODNIA I TO JEST WŁAŚCIWOŚĆ, NIE USTERKA — zmierzone: `90~91` ✓,
    `91~92` ✓, a `90~92` ✗. Stąd dwa skutki w kodzie, oba wymuszone, nie wybrane: `exptime`
    WYPADA z klucza półki (`_plan`), bo klucz zakłada równoważność, a `_shelf_ambiguous` porównuje
    PARAMI (W2). Kto doda tu grupowanie po ekspozycji, złamie jedno albo drugie.

    `None` po którejkolwiek stronie → `False`. Brak zeznania nie jest zgodnością: master bez
    `EXPTIME` ma dostać ZERO kandydatów, a nie wszystkich (próg nie ma prawa zamienić braku
    w dopasowanie)."""
    if a is None or b is None:
        return False
    tol = min(max(EXP_TOL_FLOOR_S, EXP_TOL_FRACTION * min(a, b)), EXP_TOL_CEILING_S)
    return abs(a - b) <= tol


@dataclass
class StackLineageSummary:
    """Zliczenia przebiegu (QUIET), tym samym podziałem co `LineageSummary`: `linked` = ile
    integracji MA rodowód, `linked_new` = delta zapisu (idempotentny re-run daje 0), `reasons` =
    kubełki „nie wiem".

    `linked`/`reasons` liczy PLAN, nie zapytanie o stan — i to jest różnica, którą trzeba trzymać
    w głowie przy czytaniu bramki: domykają one populację (`linked + suma(reasons) == stacks`),
    czyli mówią, co automat POTRAFIŁ ustalić w tym przebiegu. Jedyny wyjątek to stos pominięty
    strażnikiem 4 — tam plan jest niewiarygodny, więc źródło bierzemy ze STANU. `inputs` liczymy
    zapytaniem, bo werdykt ręki zmienia tabelę, nie plan."""
    stacks: int = 0
    linked: int = 0            # integracje z co najmniej jednym wejściem
    inputs: int = 0            # STAN: wierszy `integration_input`
    linked_new: int = 0        # delta: realnie zapisane relacje tego przebiegu
    unlinked: int = 0          # delta: relacje zdjęte przez reconcile
    by_assert: dict = field(default_factory=dict)   # źródło (`repo.RANGA_ASSERT`) -> ile integracji
    ambiguous: int = 0         # integracje z oknem nierozłącznym (patrz strażnik 3)
    telescope_mismatch: int = 0    # master zeznaje inny teleskop niż klatki jego okna
    history_unread: int = 0    # plik nieosiągalny/nieczytelny (błąd odczytu ALBO brak lokacji)
    no_location: int = 0       # …z tego: klatka NIE MA obecnej kopii — inna recepta dla człowieka
                               # („puść skan/Obecność") niż odłączone archiwum („podłącz i powtórz")
    kept_no_location: int = 0  # …z POMINIĘTYCH: te bez obecnej kopii. Osobno od `no_location`,
                               # bo tamten liczy CAŁĄ populację — próg na dwóch różnych populacjach
                               # potrafił wskazać receptę stosu, którego wcale nie pominięto
    kept_unread: int = 0       # gotowy rodowód ZOSTAWIONY nietknięty, bo zeznania nie dało się
                               # przeczytać — delta zapisu jest wtedy zerowa Z WYBORU, nie z braku
                               # zmian, i bez tego licznika wyglądałaby jak idempotencja
    kept_proven: int = 0       # …a tu DRUGI powód pominięcia (S2b): plik był czytelny, ale ZAPISANE
                               # zeznanie jest MOCNIEJSZE od tego, co przebieg umiał policzyć teraz.
                               # Osobno od `kept_unread`, bo recepta jest inna: tam „podłącz dysk",
                               # tu „nikt nic nie zgubił — rodowód stoi na dowodzie mocniejszym"
    reasons: dict = field(default_factory=dict)     # powód -> licznik (integracje bez wejść)
    cancelled: bool = False    # przerwane w fazie planu (czytanie nagłówków) - zero zapisów
    # HISTORIA Z BAZY (AR-87): falsyfikatorem jest `history_reads` - druga Dostawa ma czytać ZERO
    # nagłówków stosów z udziału. Odczyt pliku zostaje drogą zapasową (brak wiersza `stack_history`
    # albo rozjazd jego kotwicy z odciskiem kopii); `history_refreshed` = ile wierszy taki odczyt
    # przepisał w bazie (następny przebieg wraca do bazy).
    history_reads: int = 0     # nagłówki stosów przeczytane z dysku w tym przebiegu. GRANICA: kopia
                               # bez odcisku nagłówka (`header_hash` NULL - W1) nie dostaje wiersza
                               # historii, więc jej odczyt zostaje przy KAŻDYM przebiegu; to stan,
                               # nie nieszczelność (pf4 2026-10-11: 0 takich stosów)
    history_refreshed: int = 0
    # PODSTAWA RODOWODU (AR-108, E4-9): na czym stoi plan każdego stosu z wejściami - token
    # `LINEAGE_BASES` dla rangi `history`, `BASIS_SUBSET` dla werdyktu „plik użył N z M klatek okna”
    # (wiersze `window`), `"window"` dla stosu bez historii integracji (wiersze okna bez zeznania
    # pliku); `outside_window` - ile zbiorów z nazw sięga poza okno nagłówka;
    # `names_ambiguous` - ile stosów odmówiło zbioru z nazw, bo nazwa trafia dwie klatki.
    by_basis: dict = field(default_factory=dict)
    outside_window: int = 0
    names_ambiguous: int = 0


def _bump_kept(s, p):
    """Pominięcie rodowodu do WŁAŚCIWEGO kubełka — dwa powody, dwie recepty (S2b).

    Do S2b powód był jeden („nie przeczytałem pliku") i licznik też jeden. Ochrona rangą dokłada
    drugi: plik czytelny, ale zapisane zeznanie MOCNIEJSZE od tego, co przebieg umiał policzyć —
    tam nie ma czego podłączać ani czego naprawiać. Wspólny licznik kazałby człowiekowi szukać
    odłączonego dysku pod stosem, który leży na miejscu."""
    if p["history_unread"]:
        s.kept_unread += 1
        s.kept_no_location += p["no_location"]
    else:
        s.kept_proven += 1


def _bump(d, key):
    d[key] = d.get(key, 0) + 1


def _masters(con):
    """Klatki stosów z materiałem zeznania. `telescope_id` bierzemy z KANONU osi (widok
    `telescope_canonical`), więc scalenie teleskopów przenosi rodowód razem ze sprzętem.

    ZASTĄPIONY MASTER NIE WRACA JAKO STOS (R4, `frame.superseded_by`): jego plik niesie dziś inna
    tożsamość, a policzenie obu dałoby dwa obrazy tam, gdzie na dysku leży jeden. Zmierzona
    populacja dziś: **0** (jedyna zastąpiona klatka archiwum to light, nie master) — klauzula
    wchodzi PRZED pierwszym takim przypadkiem, bo kosztuje jeden warunek, a jej brak wychodzi
    dopiero jako zdublowany obraz w Zbiorach.

    GRANICA NAZWANA, NIE ZAŁATANA: wiersz `integration` zastąpionego mastera ZOSTAJE (jest kluczowany
    `UNIQUE(master_frame_id)`, a tabela jest append-only) i nie dostanie już przepisanej głowy —
    czyli zamarznie w stanie z ostatniego przebiegu. Dopóki populacja jest zerowa, kod na to byłby
    zgadywaniem; przy pierwszym zastąpionym masterze rozstrzygnąć, czy głowa dostaje własny powód
    (`superseded`), czy wiersz idzie do kubełka podmiany razem z klatką.

    ODNIESIENIE CZASU (R2) PRZYCHODZI Z `integration`, nie z klatki — LEFT JOIN, bo stos widziany
    pierwszy raz wiersza integracji jeszcze nie ma (zakłada go ten sam przebieg, niżej). Brak
    wiersza i wiersz z `utc_offset_min IS NULL` znaczą dla doboru DOKŁADNIE to samo („nie wiem,
    w jakim zegarze liczy ten master"), więc łączymy je bez rozróżnienia.

    HISTORIA Z KOPII, KTÓRA DAŁA `header` (AR-22 (3)). Zeznanie stosu to para: karty z `header`
    i XML historii z pliku spod `path`. Obie połowy mają pochodzić z JEDNEJ kopii - inaczej okno
    i obiekt mówiłyby o jednym przebiegu integracji, a `declared_rows` i sygnatura o drugim.
    Gdy kopię wiodącą wskazała ręka (ważna kotwica `repo.hand_lead_location`), historia idzie z NIEJ -
    to jej głos niesie `header`. Bez kotwicy kopia-źródło to ta obecna, której fakty (`hdr_*`, 0021)
    równają się `copy_testimony(header)` -
    ta sama derywacja po obu stronach, co w predykacie „Zeznanie z nieobecnej kopii"
    (`gui.queries.orphan_testimony_copies`). Żadna nie pasuje (fakty nie zebrane, zeznanie
    z kopii nieobecnej) → najstarsza obecna, jak dotąd. Sonda 2026-10-07 na `pf4` `?mode=ro`:
    stosów z dwiema obecnymi kopiami jest 0, więc dziś każdy stos czyta tę samą kopię co przedtem."""
    rows = con.execute(
        "SELECT f.id AS frame_id, f.object_id AS object_id, f.filter_canon AS filter_canon, "
        "h.raw_json AS raw_json, tc.canon_id AS telescope_id, i.utc_offset_min AS utc_offset_min "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN integration i ON i.master_frame_id = f.id "
        "WHERE f.kind = 'master_light' AND f.superseded_by IS NULL ORDER BY f.id").fetchall()
    kopie = {}
    for k in con.execute(
            "SELECT l.id, l.frame_id, l.path, l.header_hash, l.hdr_filter, l.hdr_imagetyp, "
            "       l.hdr_object, l.hdr_telescop, "
            "       l.hdr_instrume, l.hdr_exptime, l.hdr_xbinning, l.hdr_date_obs "
            "FROM location l JOIN frame f ON f.id = l.frame_id "
            "WHERE f.kind = 'master_light' AND f.superseded_by IS NULL AND l.present = 1 "
            "ORDER BY l.frame_id, l.id"):
        kopie.setdefault(k["frame_id"], []).append(k)
    out = []
    for r in rows:
        # KOPIA WYBRANA niesie też `location_id` i `header_hash` (AR-87): historia z bazy
        # (`stack_history`) należy do KOPII i wolno jej użyć tylko przy równości kotwicy z odciskiem
        # nagłówka TEJ kopii, którą wybrała reguła niżej - nie dowolnej kopii klatki.
        obecne = kopie.get(r["frame_id"], [])
        wybrana = obecne[0] if obecne else None
        kotwica = repo.hand_lead_location(con, r["frame_id"]) if len(obecne) > 1 else None
        if kotwica is not None:
            wybrana = next(k for k in obecne if k["id"] == kotwica)
        elif len(obecne) > 1 and r["raw_json"]:
            zeznanie = copy_testimony(json.loads(r["raw_json"]))
            zrodlo = next((k for k in obecne if all(k[p] == v for p, v in zeznanie.items())), None)
            if zrodlo is not None:
                wybrana = zrodlo
        out.append({**dict(r),
                    "path": wybrana["path"] if wybrana is not None else None,
                    "location_id": wybrana["id"] if wybrana is not None else None,
                    "header_hash": wybrana["header_hash"] if wybrana is not None else None})
    return out


def _window_candidates(con, *, object_id, exptime):
    """Lighty tego obiektu o zbliżonej ekspozycji — SUROWY materiał okna (czas/filtr/teleskop/próg
    ekspozycji przycina Python, bo każde z tych porównań ma własną regułę: parser ISO, normalizacja
    filtra, kanon osi, tolerancja D-DR-2).

    `exptime` DAJE W SQL NADZBIÓR, nie werdykt (R3, zmiana wobec stanu sprzed GO-2). Do R3 warunek
    brzmiał `h.exptime = ?` i był jedynym porównaniem będącym zwykłą równością — po wprowadzeniu
    progu to zdanie jest FAŁSZEM i zostało tu przepisane (lekcja E2-1: docstring obiecujący więcej,
    niż droga dowozi, przechodzi przez recenzję jako dowód). SQL zawęża do pasa `± sufit progu`,
    bo tolerancja nigdy nie przekracza `EXP_TOL_CEILING_S` — a rozstrzyga `exposure_matches`,
    dokładnie tak, jak dziś rozstrzyga czas, filtr i teleskop. Indeks robi swoje, decyzja zostaje
    w JEDNEJ funkcji.

    `exptime` mastera `None` TU NIE DOCHODZI — i to jest zapis o SZWIE, nie obietnica łagodnego
    zachowania (bramka pakietu, zarzut 2: poprzednie zdanie mówiło „ZERO kandydatów", a kod
    wywaliłby `TypeError` na `exptime - EXP_TOL_CEILING_S`). Strażnikiem jest `testimony.degenerate`
    z sąsiedniego modułu: brak czasu ekspozycji czyni okno zdegenerowanym z definicji, więc `_plan`
    kończy linijkę wcześniej. Gdyby ten szew kiedyś pękł, wołanie ma wybuchnąć głośno (EXPECT),
    a nie oddać cichą pustkę udającą poprawny wynik.

    `filetype` WYCHODZI Z TEGO ZAPYTANIA dla R2: to ono, a nie stanowisko, rozstrzyga, czy czas
    kandydata wymaga sprowadzenia do odniesienia mastera. Stanowisko ma 97% FITS-ów, więc warunek
    postawiony na nim ruszyłby gałąź ASI — a nosicielem problemu jest FORMAT (EXIF RAW-a niesie
    czas LOKALNY, XISF mastera UTC).

    KLATKA ZASTĄPIONA NIE JEST KANDYDATEM (R4): sierota i jej następczyni to ta sama ekspozycja
    pod tą samą ścieżką, więc bez tego warunku okno policzyłoby ten sub DWA RAZY —
    a `integrated_exposure` deduplikuje po `input_frame_id`, czyli duplikatu by nie zdjęło.

    TEMPERATURA IDZIE Z `ccd_temp` (POMIAR) I TAK MA BYĆ — to wynik pomiaru, nie przeoczenie.
    Nazwa wejścia WBPP niesie temperaturę ZMIERZONĄ, nie nastawę: na 6 stosach z historią test
    tożsamości (`resolve.stack.inputs_contained`) przechodzi na `ccd_temp` 6/6, a na `set_temp`
    0/6 — nastawa jest stała (−10,0), gdy deklarowane wartości rozkładają się −10,1…−9,6.
    Podmiana na `header.set_temp` zamieniłaby wszystkie dowiedzione rodowody w `history_mismatch`.
    (Standing „SET-TEMP jest osią, nie pomiar" dotyczy PRZEPISU KALIBRACJI — innej osi niż ta.)"""
    return con.execute(
        "SELECT f.id AS frame_id, f.filter_canon AS filter_canon, h.date_obs AS date_obs, "
        "h.ccd_temp AS ccd_temp, h.exptime AS exptime, f.filetype AS filetype, "
        "tc.canon_id AS telescope_id "
        "FROM frame f JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "WHERE f.kind = 'light' AND f.object_id = ? AND h.exptime BETWEEN ? AND ? "
        "AND h.date_obs IS NOT NULL AND f.superseded_by IS NULL ORDER BY f.id",
        (object_id, exptime - EXP_TOL_CEILING_S, exptime + EXP_TOL_CEILING_S)).fetchall()


def _in_window(rows, *, start, end, filter_canon, telescope_id, exptime, utc_offset_min):
    """Przytnij kandydatów oknem czasu i osiami → `(wybrane, rozjazd_teleskopu, raw_bez_odniesienia)`.

    Oś, której master NIE ZNA (filtr/teleskop puste — zmierzone: `TELESCOP` w 83 z 85, `FILTER`
    w 84 z 85), NIE zawęża doboru: nieznane nie może udawać warunku.

    TELESKOP ROZSTRZYGA WARUNKOWO — i to jest wniosek z POMIARU, nie z ostrożności. Na realnym
    archiwum (81 niepustych okien) zbiór kandydatów okazał się teleskopowo JEDNORODNY w 81 na 81
    przypadków: ta oś nigdy nie wybierała MIĘDZY klatkami okna, umiała tylko odrzucić wszystkie.
    A odrzucała je w 7 przypadkach, w których master niesie kartę PRZESTARZAŁĄ albo śmieciową
    (`ED` — wartość naprawioną już w archiwum writebackiem; `EQMOD HEQ5/6` — nazwa MONTAŻU).
    Reguła jest więc taka:

      * są kandydaci z teleskopu mastera → bierzemy WYŁĄCZNIE ich (oś rozstrzyga, gdy umie);
      * okno jednorodne, ale z INNEGO teleskopu → bierzemy je i podnosimy `rozjazd`, bo to szew
        dwóch zeznań o tej samej nocy, a nie dwa różne zestawy klatek. Relacja i tak jest
        KANDYDATEM (`asserted_by='window'`), więc nic nie udaje faktu, a powierzchnia dostaje
        materiał do naprawy karty — dokładnie tej, którą archiwum już przeszło;
      * okno MIESZA teleskopy i żaden nie jest masterowy → nie ma czym rozstrzygnąć, zero relacji.

    Wariant „twardy" (odmowa zawsze) kosztowałby dziś 7 rodowodów i nazwałby je `no_candidates`,
    czyli nieprawdą: kandydaci byli, odrzuciła ich oś.

    MASTER, KTÓRY SAM NIE ZNA TELESKOPU, NIE FLAGUJE ROZJAZDU — świadoma granica, nie przeoczenie:
    nie ma czego z czym rozjechać. Okno mieszające wtedy dwa teleskopy weszłoby w całości bez
    ostrzeżenia; zmierzone na realnym archiwum 0/128, więc granica zostaje NAZWANA, a nie obłożona
    kodem na populację zerową. Wraca do rozważenia, gdy pojawi się pierwszy taki przypadek.

    Okno jest PÓŁOTWARTE `[start, end)`: `DATE-END` to koniec ostatniej ekspozycji, więc klatka
    ZACZYNAJĄCA się w tej chwili należy do następnej serii, nie do tej. Zmierzone: 0 wejść na 128
    stosach siada dokładnie na granicy, więc dziś to no-op — i o to chodzi, bo granicę domyka się,
    póki jest pusta, a nie po pierwszym cudzym subie wciągniętym do obrazu.

    ODNIESIENIE CZASU (R2) — PRZESUWAMY KANDYDATA, NIGDY OKNA. Okno mastera (`window_start/end`)
    idzie prosto do `upsert_integration` i ma zostać zapisem tego, co zeznał plik; przesunięcie go
    zamieniłoby fakt o pliku na fakt o naszej interpretacji, a każdy kolejny przebieg przesuwałby
    je ponownie. Kandydat `filetype='raw'` niesie czas LOKALNY (EXIF), master XISF — UTC, więc
    sprowadzamy kandydata do zegara mastera przez ODJĘCIE offsetu (umowa `lokalny = UTC + offset`,
    0016). FITS-y i XISF-y nie są ruszane wcale: to nie jest domysł o ich zegarze, tylko granica
    zmierzona — podpis dwóch odniesień ma dokładnie 7 masterów ze 128 i wszystkie powstały z DNG-ów.

    KANDYDAT RAW PRZY NIEZNANYM ODNIESIENIU NIE WCHODZI I NIE PRZEPADA PO CICHU — wypada z okna
    (nie ma jak umieścić go w czasie), ale wraca trzecią wartością zwrotu, żeby wołający mógł
    powiedzieć `offset_unknown` zamiast `no_candidates`. To rozróżnienie jest całym sensem R2:
    „kandydaci są, tylko liczą w innym zegarze" to inna recepta niż „kandydatów nie ma".

    PULA MIESZANA NIE UCISZA RAW-ÓW (G2-1d): gdy okno domknie się z materiału NIE-RAW, a obok
    stały nieosądzalne RAW-y, trzecia wartość ma czytelnika mimo rodowodu - `_plan` odkłada ją
    jako UWAGĘ obok werdyktu (`integration.raw_unreferenced`, migracja 0020), a panel mówi „a tych
    N nie umiem umieścić w czasie". Werdykt zostaje jednowartościowy; uwaga go nie dubluje
    (CHECK 0020 odbija ją przy `offset_unknown`, który mówi to samo). Zmierzona populacja na żywym
    archiwum: **0** - droga stoi na teście syntetycznej puli mieszanej, nie na żywym stosie.

    TRZECIA WARTOŚĆ LICZY TYLKO RAW-Y, KTÓRE PRZEŻYŁYBY OŚ TELESKOPU po wskazaniu zegara - obrona
    tak szeroka jak źródło faktu, bo ta liczba jest obietnicą gestu (uzasadnienie przy kodzie niżej).
    Przy oknie nie-RAW pustym i RAW-ach mieszających obce teleskopy rozjazd reguły wraca drugą
    wartością, więc werdykt brzmi `telescope_mismatch` zamiast fałszywego `offset_unknown`."""
    okno = []
    raw_bez_zegara = []
    for r in rows:
        if not exposure_matches(r["exptime"], exptime):
            continue                       # SQL dał NADZBIÓR (pas ± sufit) — próg rozstrzyga tu
        if filter_canon and r["filter_canon"] != filter_canon:
            continue
        t = header_dt(r["date_obs"])
        if t is None:
            continue
        if r["filetype"] == "raw":
            if utc_offset_min is None:
                # LICZYMY TYLKO ŚWIADKÓW, KTÓRYCH JAKIKOLWIEK OFFSET MÓGŁBY WCIĄGNĄĆ (bramka
                # pakietu, zarzut 3). Bez tego RAW z INNEJ NOCY o zgodnej ekspozycji i filtrze
                # nabijał licznik, a stos dostawał `offset_unknown` i receptę „wskaż odniesienie",
                # której wykonanie nic by nie dało — bo fizyczny sufit zegarów (±14 h) wykluczał
                # tego świadka z góry. Fałszywa recepta jest gorsza niż `no_candidates`: wysyła
                # człowieka do gestu, który nie ma prawa zadziałać.
                if (start - timedelta(minutes=repo.UTC_OFFSET_MAX_MIN)
                        <= t < end + timedelta(minutes=repo.UTC_OFFSET_MAX_MIN)):
                    raw_bez_zegara.append(r)
                continue
            t -= timedelta(minutes=utc_offset_min)
        if not (start <= t < end):
            continue
        okno.append(r)
    wybrane, rozjazd = _telescope_rule(okno, telescope_id)
    if not raw_bez_zegara:
        return wybrane, rozjazd, 0
    # RAW BEZ ZEGARA LICZY SIĘ TYLKO WTEDY, GDY PRZEŻYŁBY OŚ TELESKOPU - pytamy o DECYZJĘ reguły,
    # nie kopiujemy jej logiki. Licznik zasila receptę „wskaż zegar", więc ma mówić, ile klatek ten
    # gest REALNIE odblokuje: RAW teleskopu B przy kandydacie FITS teleskopu mastera A zostałby po
    # geście odrzucony gałęzią pierwszą, a panel obiecywałby go mimo to.
    #
    # WARIANT ŁĄCZNY (okno + WSZYSTKIE RAW-y bez zegara naraz), nie „każdy RAW osobno z oknem",
    # bo tak liczy przebieg po geście: offset jest jeden dla całego obrazu, więc wszystkie RAW-y
    # wchodzą do okna RAZEM i reguła widzi je jednocześnie. Wariant osobny przepuszczałby RAW
    # teleskopu B obok RAW-u teleskopu A (każdy sam z pustym oknem jest „jednorodny"), a po geście
    # A wypiera B. Granica nazwana: pas ±14 h jest szerszy niż okno, więc RAW, który po geście
    # wypadnie poza okno, i tak głosuje tu o jednorodności - skutek to co najwyżej ostrożniejszy
    # licznik (0 zamiast N) przy mieszance teleskopów w samym paśmie.
    #
    # TEN SAM LICZNIK ZASILA WERDYKT `offset_unknown` i tam też musi pytać regułę: przy pustym
    # oknie nie-RAW i RAW-ach JEDNORODNIE innego teleskopu reguła je przyjmuje (gałąź środkowa),
    # więc werdykt zostaje i jest prawdą - gest dobierze klatki, z flagą rozjazdu. Fałszem był
    # wyłącznie przypadek RAW-ów MIESZAJĄCYCH obce teleskopy: `offset_unknown` obiecywał „klatki się
    # dobiorą", a po geście reguła odrzuciłaby wszystkie. Wtedy rozjazd reguły idzie do wołającego
    # i `_plan` mówi `telescope_mismatch` (kandydaci byli, odrzuciła ich oś), a nie `no_candidates`.
    ids = {id(r) for r in raw_bez_zegara}
    przezyli, rozjazd_z_raw = _telescope_rule(okno + raw_bez_zegara, telescope_id)
    ile = sum(1 for r in przezyli if id(r) in ids)
    if not okno and not ile:
        rozjazd = rozjazd_z_raw
    return wybrane, rozjazd, ile


def _telescope_rule(okno, telescope_id):
    """Reguła TRZYGAŁĘZIOWA osi teleskopu → `(wybrane, rozjazd)` - JEDYNY właściciel (B3a-2).

    Uzasadnienie gałęzi i pomiar stoją w `_in_window`; tu mieszka sam mechanizm, bo woła go też
    `propose_lineage_candidates`. Dwie kopie tej reguły rozjechałyby się przy pierwszej poprawce
    jednej z nich, a rozjazd byłby niewidoczny: panel proponowałby co innego, niż dobrałby automat.

    `okno` = klatki JEDNEJ serii tej samej nocy, już przycięte czasem, filtrem i progiem
    ekspozycji. Master, który sam nie zna teleskopu, i puste okno → bez zmian, bez rozjazdu."""
    if telescope_id is None or not okno:
        return okno, False
    zgodne = [r for r in okno if r["telescope_id"] == telescope_id]
    if zgodne:
        return zgodne, False
    if len({r["telescope_id"] for r in okno}) == 1:
        return okno, True
    return [], True


PROPOSAL_SECONDS_TOL = 2
"""Tolerancja podpisu dwóch zegarów w `propose_offset_minutes` - ile sekund RAW może odstawać od
pełnej godziny względem początku okna stosu. ZMIERZONE na kopii `pf4` (290 integracji, AR-278):
autocrop IC443 startuje 1 s przed oryginałem (zaokrąglenie `DATE-OBS` przy przycięciu), a każda
tolerancja 1-30 s dodaje dokładnie tę jedną propozycję, bez zmiany i bez utraty żadnej innej;
najbliższy RAW, który zrobiłby podpis niejasnym, stoi 41 s od pełnej godziny (LMC). 2 = zmierzona
sekunda + sekunda zapasu."""


def _propozycja_z_okna(con, master_frame_id):
    """Propozycja z OKNA stosu (świadek: RAW obiektu w zgodnym `mm:ss`) - `minuty | None`."""
    row = con.execute(
        "SELECT f.object_id, i.window_start FROM frame f "
        "JOIN integration i ON i.master_frame_id = f.id WHERE f.id = ?",
        (master_frame_id,)).fetchone()
    if row is None or row["window_start"] is None or row["object_id"] is None:
        return None
    start = header_dt(row["window_start"])
    if start is None:
        return None
    roznice = set()
    for r in con.execute(
            "SELECT h.date_obs FROM frame f JOIN header h ON h.frame_id = f.id "
            "WHERE f.kind = 'light' AND f.object_id = ? AND f.filetype = 'raw' "
            "AND f.superseded_by IS NULL AND h.date_obs IS NOT NULL", (row["object_id"],)):
        t = header_dt(r["date_obs"])
        if t is None:
            continue
        sekundy = (t - start).total_seconds()
        godziny = round(sekundy / 3600.0)
        if abs(sekundy - godziny * 3600) > PROPOSAL_SECONDS_TOL:
            continue                                   # `mm:ss` się nie zgadza (± tolerancja)
        delta = godziny * 60
        # SUFIT ZEGARÓW ŚWIATA odsiewa świadka z INNEJ DOBY (bramka pakietu, zarzut 7): sama
        # podzielność przez 60 przepuszczała np. 1500 minut, czyli klatkę z następnej nocy
        # o trafionym `mm:ss` — jeden przypadkowy zbieg dawał propozycję fałszywą co do doby.
        if abs(delta) <= repo.UTC_OFFSET_MAX_MIN:
            roznice.add(delta)
    return roznice.pop() if len(roznice) == 1 else None


def propose_offset_minutes(con, master_frame_id):
    """PROPOZYCJA odniesienia czasu dla stosu - `minuty | None`. Czysty odczyt, zero zapisu.

    WARIANT KADRU DZIEDZICZY PO ORYGINALE (AR-278): autocrop (`stack_variant`, 0035) to ten sam
    materiał co oryginał, więc i ten sam zegar aparatu. Odniesienie WSKAZANE przy oryginale
    (`integration.utc_offset_min`, fakt ręki - także `0` = UTC, `None` = nie wiem) idzie wprost,
    a gdy go nie ma - propozycja z okna oryginału. Dopiero wariant bez oryginału, oryginał bez
    obu albo stos bez relacji pytają własne okno.

    Świadkiem okna jest OKNO MASTERA zestawione z materiałem RAW tego samego obiektu: gdy `mm:ss`
    kandydata zgadza się z `mm:ss` początku okna (± `PROPOSAL_SECONDS_TOL`), a różnią się PEŁNE
    GODZINY, to nie jest zbieg okoliczności, tylko dwa zegary tej samej chwili. ZMIERZONE na kopii
    `pf4` (290 integracji): propozycję dostaje 14 stosów (12 × `+120` LMC z wariantami, `+60` IC443
    i jego autocrop), a żaden spoza materiału DSLR - propozycja, która trafia wszędzie, nie jest
    świadkiem.

    PROPONUJE, NIE ZAPISUJE - i to jest cała jej rola (lustro szczebla ścieżki S2). Zegar aparatu
    jest faktem o SPRZĘCIE, którego archiwum nie zna z definicji; maszyna umie go tylko obstawić
    z kształtu liczb, więc werdykt zostaje przy człowieku, a zapis przy `repo.set_integration_offset`.

    `None` znaczy „nie mam czym obstawić" - brak okna, brak kandydatów RAW albo podpis niejasny
    (dwie różne różnice godzin wśród kandydatów). Milczenie jest tu uczciwsze niż środek: propozycja
    wzięta z niezgodnych świadków byłaby zgadywaniem podanym jako pomiar."""
    para = con.execute("SELECT original_frame_id FROM stack_variant WHERE variant_frame_id = ?",
                       (master_frame_id,)).fetchone()
    if para is not None:
        oryginal = para["original_frame_id"]
        wskazane = con.execute("SELECT utc_offset_min FROM integration WHERE master_frame_id = ?",
                               (oryginal,)).fetchone()
        if wskazane is not None and wskazane["utc_offset_min"] is not None:
            return wskazane["utc_offset_min"]            # `is not None`: `0` (UTC) to werdykt
        z_oryginalu = _propozycja_z_okna(con, oryginal)
        if z_oryginalu is not None:
            return z_oryginalu
    return _propozycja_z_okna(con, master_frame_id)


# ============================================================ KLATKA NOWSZA NIŻ OBRAZ (AR-150, AR-153)
# Jedna reguła, dwa użycia: odcięcie PROPOZYCJI kandydatów (`propose_lineage_candidates`) i fakt
# o wejściu rodowodu ZAPISANEGO (`input_after_integration`, czyta go `gui.queries`). Obie drogi idą
# przez ten sam odczyt chwili zapisu i ten sam normalizator czasu klatki - kopia którejkolwiek
# połowy rozjechałaby panel z propozycją przy pierwszej poprawce strefy albo offsetu.

def integration_moment(creation_time):
    """Chwila zapisu stosu (`integration.creation_time`, `XISF:CreationTime`) jako czas porównania
    z klatką - `datetime` w UTC albo `None`.

    ZEGAR PORÓWNANIA JEST JEDEN - UTC. `creation_time` pisze UTC z sufiksem `Z` (zmierzone: 290 z 290
    wartości, w pliku własność typu `String`; luka do sygnatury integracji ma medianę 11-13 min ZIMĄ
    I LATEM - czas lokalny dałby zimą co najmniej 60, latem 120). Wartość BEZ sufiksu `Z` nie tnie
    niczego: `header_dt` strefę gubi, a czas lokalny przyciąłby w złej osi bez śladu (populacja 0
    z 290). `None` (plik tej chwili nie zna) też nie tnie - oś, której obraz nie zna, nie zawęża."""
    if not (isinstance(creation_time, str) and creation_time.rstrip().endswith("Z")):
        return None
    return header_dt(creation_time)


def moment_klatki(date_obs, filetype, utc_offset_min):
    """Czas klatki w zegarze obrazu (UTC) → `(datetime | None, raw_bez_zegara)` - JEDYNY normalizator
    czasu kandydata propozycji i wejścia rodowodu zapisanego.

    FITS i XISF niosą `DATE-OBS` w UTC (naiwne ISO, bez strefy - inwariant `header.date_obs`), więc
    wchodzą bez zmiany; `header_dt` ucina ułamki sekund. RAW (EXIF) niesie czas LOKALNY aparatu
    i schodzi do UTC przez ODJĘCIE wskazanego odniesienia stosu (umowa 0016 `lokalny = UTC + offset`).
    RAW BEZ ODNIESIENIA → `(None, True)`: nie wiadomo, kiedy powstał, więc nie stoi do porównania -
    wołający liczy go osobno (klatki czekające na zegar). Brak albo śmieć w `date_obs` → `(None, False)`,
    także dla RAW: klatka bez czasu nie czeka na zegar, tylko czasu nie ma."""
    t = header_dt(date_obs)
    if t is None:
        return None, False
    if filetype == "raw":
        # `is None` WYSTARCZA I NIE POTRZEBUJE DRUGIEJ OCHRONY. `integration.utc_offset_min` jest
        # kolumną INTEGER (0016), a jej jedyny pisarz `repo.set_integration_offset` odrzuca wszystko
        # poza `int`/`None` - token `offset_unknown` mieszka w CHECK-u SĄSIEDNIEJ kolumny
        # `unresolved_reason` i tutaj nie ma jak trafić. Pin imienny, bo bramka pakietu 3a (0808)
        # dostała ten sam fałszywy zarzut od DWÓCH silników naraz: oba czytały nazwę tokenu jako
        # wartość offsetu i proponowały strażnika na stan nieosiągalny (lustro pinu przy
        # `exptime is None` w `_window_candidates`).
        if utc_offset_min is None:
            return None, True
        t -= timedelta(minutes=utc_offset_min)
    return t, False


def taken_after_integration(czas, moment):
    """Reguła AR-150: klatka zrobiona PO zapisie stosu nie mogła do niego wejść. Porównanie ostre
    (`>`), po pełnych sekundach - klatka z tej samej sekundy co zapis zostaje. Czas nieznany po
    którejkolwiek stronie → `False`: na niewiedzy nie tniemy."""
    return czas is not None and moment is not None and czas > moment


def input_after_integration(date_obs, filetype, creation_time, utc_offset_min):
    """FAKT o wejściu rodowodu ZAPISANEGO (AR-153): czy klatka powstała po zintegrowaniu obrazu -
    ta sama reguła i ten sam normalizator co odcięcie propozycji. Liczony dla KAŻDEGO źródła
    (`window`, `history`, `harvest`, `user`); co z tym faktem zrobić, rozstrzyga wołający - gest
    odrzucenia dotyczy wyłącznie werdyktów ręki (`gui.queries`), bo tylko tam fakt znaczy pomyłkę
    werdyktu, a nie zegar do sprawdzenia."""
    czas, _ = moment_klatki(date_obs, filetype, utc_offset_min)
    return taken_after_integration(czas, integration_moment(creation_time))


NIGHT_SPLIT_HOUR = 12
"""Godzina, o której tniemy dobę na NOCE OBSERWACYJNE (UTC). Noc przechodzi przez północ, więc
klatka z 01:00 należy do wieczoru dnia poprzedniego; podział o południu jest konwencją astronomiczną
i jedyną, przy której jedna sesja zostaje jedną pozycją listy."""


@dataclass(frozen=True)
class CandidateNight:
    """Jedna noc obserwacyjna z materiałem pod PROPOZYCJĘ rodowodu. `master_night` wyróżnia tę,
    o której mówi sam obraz (`DATE-OBS`) — powierzchnia otwiera się na niej i tylko ona jest
    zeznaniem pliku; pozostałe są ofertą dla oka człowieka.

    `telescope_mismatch` niesie ROZJAZD reguły teleskopu (`_telescope_rule`) - wyłącznie na nocy
    mastera, bo tylko tam klatki innego teleskopu są „drugim zeznaniem o tej samej nocy" (B3a-2).
    Pole z wartością domyślną, żeby konstrukcja z trzech pól (testy, wołający) działała dalej."""
    night: str
    master_night: bool
    frames: tuple
    telescope_mismatch: bool = False


def propose_lineage_candidates(con, master_frame_id):
    """PROPOZYCJA MATERIAŁU dla stosu bez rodowodu - noce z kandydatami. Czysty odczyt, zero zapisu.

    DLACZEGO ISTNIEJE: dobór automatu pyta o OKNO (`DATE-OBS`…`DATE-END`), a 30 stosów archiwum ma
    okno ZDEGENEROWANE - `DATE-END` opisuje jedną klatkę zamiast serii (pułapka 1, `resolve/stack.py`:
    23 z 84 masterów starszego rocznika). Zepsuty jest KONIEC; początek zostaje początkiem pierwszego
    suba. Propozycja bierze więc tę samą oś co okno, tylko zamiast końca stawia NOC.

    OSIE ZGODNOŚCI TE SAME, CO W DOBORZE, i to jest cały warunek uczciwości tej listy: obiekt,
    filtr, teleskop, próg ekspozycji (`exposure_matches`, D-DR-2). Oś, której master NIE ZNA, nie
    zawęża - dokładnie jak w `_in_window`. Luźniejsza reguła bez tych osi nie byłaby propozycją,
    tylko spisem klatek obiektu.

    OŚ TELESKOPU NA NOCY MASTERA IDZIE TĄ SAMĄ REGUŁĄ CO DOBÓR (B3a-2) - `_telescope_rule`, wołana,
    nie kopiowana. Jej gałąź środkowa (seria JEDNORODNA, ale z innego teleskopu → bierz i podnieś
    rozjazd) istnieje po to, by master z kartą przestarzałą albo śmieciową („ED", „EQMOD HEQ5/6" -
    nazwa MONTAŻU) dostał materiał do naprawy; odsiew per klatkę pokazywał takiemu masterowi pustkę
    zamiast wskazać kartę. Rozjazd wraca na `CandidateNight.telescope_mismatch`, a panel mówi go
    tym samym zdaniem, co przy gotowym rodowodzie (`grid.lin.flag.telescope`).
    POZOSTAŁE NOCE ODSIEWAJĄ PER KLATKĘ I TO JEST ŚWIADOME: gałąź środkowa stoi na tym, że klatki
    innego teleskopu to drugie zeznanie o TEJ SAMEJ nocy, co master. Inna noc tej przesłanki nie
    ma - obiekt bywa fotografowany kilkoma teleskopami przez lata, więc reguła puszczona na każdą
    noc zapalałaby „karta do naprawy" nad poprawną kartą każdego mastera z wieloletnim obiektem.
    Zmierzona populacja żywego archiwum z rozjazdem teleskopu: **0** (rozjazdy zamknięto w etapie 3)
    - droga stoi na teście syntetycznym.
    GRANICA NAZWANA: licznik RAW-ów bez zegara odsiewa teleskop PER KLATKĘ (jak przed B3a-2), bo
    klatki bez odniesienia nie da się przypisać do nocy, a tylko na nocy mastera reguła umie
    wpuścić inny teleskop. Master ze śmieciową kartą i materiałem RAW bez zegara policzy więc 0 -
    populacja: 0.

    NIE ZAPISUJE I NIE UDAJE FAKTU (lustro `propose_offset_minutes` i szczebla ścieżki S2): zwraca
    KANDYDATÓW, a rodowód powstaje dopiero werdyktem ręki (`repo.judge_integration_input`,
    `asserted_by='user'`). Maszyna nie ma czym rozstrzygnąć, z czego powstał obraz, którego własny
    nagłówek tego nie mówi - ale umie pokazać, co tej nocy leżało w archiwum.

    NOC MASTERA WCHODZI ZAWSZE, TAKŻE PUSTA, i to jest odpowiedź na POMIAR, nie ozdoba: 5 stosów
    (`no_candidates`) nie ma materiału w swojej nocy, choć obiekt ma go setki w innych nocach
    (NGC3034: 356 lightów w 11 nocach, NGC7635: 339 w 10). Lista bez pustej nocy mastera kazałaby
    człowiekowi zgadywać, czy program w ogóle zrozumiał, o który wieczór pyta.

    KOLEJNOŚĆ = ODLEGŁOŚĆ OD NOCY MASTERA, nie chronologia: sesja przesunięta o dzień jest
    kandydatem znacznie mocniejszym niż ta sprzed roku, a pierwsze pozycje listy czyta się najuważniej.

    KLATKA JUŻ OSĄDZONA NIE WRACA jako propozycja - ani potwierdzona, ani odrzucona. Werdykt
    „to NIE jest materiał tego obrazu" ma zostać werdyktem; lista, która go co chwilę przywraca,
    kazałaby wydawać go w kółko.

    KANDYDAT RAW PRZY NIEZNANYM ODNIESIENIU NIE WCHODZI I NIE PRZEPADA PO CICHU - granica
    przeniesiona z `_in_window` RAZEM Z JEJ DRUGĄ POŁOWĄ (EXIF niesie czas LOKALNY, XISF UTC).
    Bez odniesienia nie da się powiedzieć, do której NOCY taka klatka należy, więc do listy nie
    wchodzi - ale wraca DRUGĄ WARTOŚCIĄ ZWROTU, bo „kandydaci są, tylko liczą w innym zegarze"
    to inna recepta niż „kandydatów nie ma". Bramka pakietu 3a (0808) zmierzyła, ile kosztowało
    przepisanie samego pominięcia bez tej wartości: **6 z 35** obrazów kubełka (6× LMC, po 36
    kandydatów przechodzących KAŻDĄ oś) dostawało pustą listę pod zdaniem „archiwum nie ma ani
    jednej klatki tego obiektu" - twierdzeniem FAŁSZYWYM - a gest odniesienia był dla nich
    strukturalnie nieosiągalny, bo `_plan` kończy na `degenerate_window` PRZED `_in_window`,
    więc powodu `offset_unknown` te stosy nie dostaną nigdy.

    PASMO ±SUFIT Z `_in_window` TU NIE OBOWIĄZUJE - świadomie, nie przez pominięcie. Tam licznik
    pilnował WĄSKIEGO okna (minuty), więc RAW z innej nocy trzeba było odsiać, żeby recepta nie
    wysyłała człowieka do gestu bez prawa zadziałania. Tu pula jest już przycięta obiektem,
    filtrem, teleskopem i progiem ekspozycji, a powierzchnia oddaje WSZYSTKIE noce do wyboru -
    więc każdy taki kandydat realnie pojawi się na liście po wskazaniu odniesienia. Zmierzone:
    wskazanie propozycji rdzenia (`+120`) daje 0 → 36 klatek, sześć razy na sześć.

    KLATKA ZROBIONA PO ZINTEGROWANIU OBRAZU NIE JEST KANDYDATEM (AR-150, decyzja Zdzinia `O1`:
    „rodowód nie może proponować flatów nowszych niż master"). Plik, który powstał po chwili
    zapisu stosu (`integration.creation_time`, `XISF:CreationTime`), nie mógł do niego wejść, więc
    propozycja go pomija - i nie przemilcza: liczba wraca TRZECIĄ WARTOŚCIĄ ZWROTU (wzór licznika
    RAW-ów bez odniesienia), bo „klatki są, tylko powstały później" to inna odpowiedź niż „klatek
    nie ma". Panel bez tej reguły podsuwał noce PO obrazie jak każde inne, a werdykt ręki nie ma
    czym ich odróżnić: zmierzone na kopii żywej bazy - 9 stosów NGC7635 ma 270 wejść potwierdzonych
    ręką, zrobionych po `creation_time` swojego stosu (AR-153 - ta sama reguła orzeka o nich).
    REGUŁA I JEJ ZEGAR MAJĄ JEDNEGO WŁAŚCICIELA: chwila zapisu - `integration_moment` (UTC z `Z`;
    NULL albo wartość bez `Z` nie tnie), czas kandydata - `moment_klatki` (RAW przez wskazane
    odniesienie), porównanie - `taken_after_integration` (ostre `>`, pełne sekundy). RAW BEZ
    ODNIESIENIA nie jest tu ani odcinany, ani liczony: nie wiadomo, kiedy powstał, więc zostaje
    w liczniku klatek czekających na zegar. Licznik odsiewa teleskop PER KLATKĘ (granica licznika
    RAW-ów wyżej): na nocy mastera z kartą-śmieciem klatka obcego teleskopu po zintegrowaniu nie
    zostanie policzona - populacja rozjazdu teleskopu: 0.

    Zwraca `(tuple[CandidateNight, …], raw_bez_odniesienia, po_zintegrowaniu)`; pusta krotka = nie
    ma czego proponować (brak obiektu, brak czasu ekspozycji albo brak `DATE-OBS` - zmierzone: 1 stos
    z 35)."""
    row = con.execute(
        "SELECT f.id AS frame_id, f.object_id, f.filter_canon, h.raw_json, "
        "       tc.canon_id AS telescope_id, i.id AS integration_id, i.utc_offset_min, "
        "       i.creation_time "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN integration i ON i.master_frame_id = f.id "
        "WHERE f.id = ?", (master_frame_id,)).fetchone()
    if row is None or row["object_id"] is None:
        return (), 0, 0
    t = rstack.read_testimony(json.loads(row["raw_json"]) if row["raw_json"] else {}, None)
    exptime = _to_float(t.exptime)
    start = t.window_start
    if start is None or not exptime:
        return (), 0, 0
    osadzone = {int(r[0]) for r in con.execute(
        "SELECT input_frame_id FROM integration_input WHERE integration_id = ?",
        (row["integration_id"],)).fetchall()} if row["integration_id"] else set()
    noc_mastera = _night_key(start)
    zintegrowany = integration_moment(row["creation_time"])   # None nie tnie - patrz docstring
    wg_nocy = {}
    raw_bez_odniesienia = 0
    po_zintegrowaniu = 0
    for r in _window_candidates(con, object_id=row["object_id"], exptime=exptime):
        if r["frame_id"] in osadzone:
            continue
        if not exposure_matches(r["exptime"], exptime):
            continue                       # SQL dał NADZBIÓR (pas ± sufit) - próg rozstrzyga tu
        if row["filter_canon"] and r["filter_canon"] != row["filter_canon"]:
            continue
        # TELESKOP NIE ODSIEWA TU - rozstrzyga go reguła niżej, po podziale na noce (B3a-2).
        obcy = row["telescope_id"] is not None and r["telescope_id"] != row["telescope_id"]
        czas, bez_zegara = moment_klatki(r["date_obs"], r["filetype"], row["utc_offset_min"])
        if bez_zegara:
            if not obcy:                      # licznik odsiewa teleskop per klatkę - granica wyżej
                raw_bez_odniesienia += 1      # NIE `continue` po cichu - patrz docstring
            continue
        if czas is None:
            continue
        if taken_after_integration(czas, zintegrowany):
            # PO ZINTEGROWANIU OBRAZU - nie mogła do niego wejść (AR-150). Odcięcie stoi PRZED
            # podziałem na noce, bo taka klatka nie ma też prawa głosować w regule teleskopu nocy
            # mastera; licznik odsiewa teleskop per klatkę - granica w docstringu.
            if not obcy:
                po_zintegrowaniu += 1
            continue
        wg_nocy.setdefault(_night_key(czas), []).append(r)
    rozjazd_mastera = False
    for n in list(wg_nocy):
        if n == noc_mastera:
            wg_nocy[n], rozjazd_mastera = _telescope_rule(wg_nocy[n], row["telescope_id"])
        elif row["telescope_id"] is not None:
            wg_nocy[n] = [r for r in wg_nocy[n] if r["telescope_id"] == row["telescope_id"]]
        if not wg_nocy[n] and n != noc_mastera:
            del wg_nocy[n]               # noc bez materiału po osi teleskopu nie jest ofertą
    wg_nocy.setdefault(noc_mastera, [])
    return tuple(
        CandidateNight(night=n, master_night=(n == noc_mastera), frames=tuple(wg_nocy[n]),
                       telescope_mismatch=(n == noc_mastera and rozjazd_mastera))
        for n in sorted(wg_nocy, key=lambda n: (n != noc_mastera,
                                                abs((_date(n) - _date(noc_mastera)).days), n))
    ), raw_bez_odniesienia, po_zintegrowaniu


def _night_key(t):
    """Klucz nocy obserwacyjnej dla momentu `t` — data WIECZORU (`YYYY-MM-DD`)."""
    return (t - timedelta(hours=NIGHT_SPLIT_HOUR)).date().isoformat()


def _date(klucz):
    return date.fromisoformat(klucz)


def _shelf_ambiguous(plany):
    """Zbiór klatek mastera, których okno NAKŁADA się na okno innego stosu tej samej PÓŁKI
    (obiekt+filtr+teleskop) PRZY ZGODNEJ EKSPOZYCJI. Fakt 20 briefu: 43 takie pary to reprocessingi
    tej samej nocy (`WBPP` vs `WBPP_nowy`) — ten sam sub wchodzi wtedy do dwóch integracji, więc
    `integration_input` jest POKRYCIEM, nie podziałem. Oznaczamy OBIE strony pary.

    EKSPOZYCJA WYPADŁA Z KLUCZA PÓŁKI I PRZESZŁA DO TESTU PARY (R3) — to jest wymuszenie, nie
    porządki. Klucz słownika zakłada relację RÓWNOWAŻNOŚCI (kto trafia w to samo wiadro, jest
    wzajemnie zgodny), a próg D-DR-2 przechodni NIE JEST: `90~91` ✓, `91~92` ✓, `90~92` ✗.
    Ekspozycja w kluczu rozdzielałaby więc pary zgodne (90 i 91 lądowały w osobnych wiadrach),
    a ekspozycja W KLUCZU PO ZAOKRĄGLENIU sklejałaby niezgodne. Jedyne uczciwe miejsce dla relacji
    nieprzechodniej to porównanie PARAMI — tam, gdzie i tak porównujemy okna (W2)."""
    ambi = set()
    polki = {}
    for p in plany:
        if p["start"] is None or p["end"] is None:
            continue
        polki.setdefault(p["shelf"], []).append(p)
    # GRANICA ZNANA, NIE ZAŁATANA: stos pominięty strażnikiem 4 nie dostaje przepisanej głowy, więc
    # dla pary nierozłącznych okien, w której jedna strona jest pominięta, flaga trafia do bazy
    # TYLKO po jednej stronie — most do planera (I-2e) policzyłby wtedy wspólny sub dwa razy.
    # Warunek wystąpienia jest wąski: obie strony muszą leżeć na TEJ SAMEJ półce, a plik jednej być
    # nieczytelny przy czytelnym drugim. Zmierzona populacja: 0 (jedyne pominięcia na realnym
    # archiwum to 6 stosów historii, każdy na własnej półce). Domknąć przy I-2e, gdy flaga zacznie
    # cokolwiek liczyć — dziś kod na populację zerową byłby zgadywaniem.
    for grupa in polki.values():
        for i, a in enumerate(grupa):
            for b in grupa[i + 1:]:
                if not exposure_matches(a["exptime"], b["exptime"]):
                    continue
                if a["start"] <= b["end"] and b["start"] <= a["end"]:
                    ambi.add(a["frame_id"])
                    ambi.add(b["frame_id"])
    return ambi


def _read_history_xml(path):
    """SUROWE bajty XML nagłówka XISF spod ścieżki - READ-ONLY, sam nagłówek. Import lokalny, bo `scan`
    ciągnie astropy, a ten moduł bywa wołany tam, gdzie ładowanie astropy jest zbędne. Bajty, nie
    tekst: odcisk odświeżenia historii (`_plan`) liczy się z nich tak samo jak `header_hash` kopii
    (sha1 bajtów XML) - tekst po `decode(..., "replace")` nie wraca do tych samych bajtów, gdy nagłówek
    niesie bajt spoza UTF-8. Czytnik wstrzykiwany (testy) może oddać tekst.

    Format INNY niż XISF oddaje `None`, a nie wyjątek: historia PixInsighta jest własnością XISF-a
    i jej brak w FITS-ie nie jest awarią odczytu. Bez tego rozdziału stos zapisany jako FITS
    wpadłby do licznika „historia nieodczytana" i kłamał o dostępności pliku (dziś zmierzone
    128/128 stosów to `.xisf`, ale licznik ma mierzyć to, co mierzy)."""
    from .scan import XISF_SUFFIXES, read_xisf_meta_full
    if not str(path).lower().endswith(XISF_SUFFIXES):
        return None
    return read_xisf_meta_full(path).xml_bytes


def _stored_histories(con):
    """Historia stosów zapisana w bazie (0034) → `{location_id: (hdr_hash, History)}` - DWA
    zapytania na przebieg (wejścia i głowy; wejścia 193 stosów to kilka tysięcy wierszy), nie
    zapytanie per stos."""
    wejscia = {}
    for r in con.execute(
            "SELECT location_id, path, enabled, has_drizzle, temp_c FROM stack_history_input "
            "ORDER BY location_id, seq"):
        wejscia.setdefault(r["location_id"], []).append(rstack.StackInput(
            path=r["path"], enabled=bool(r["enabled"]), has_drizzle=bool(r["has_drizzle"]),
            set_temp_c=r["temp_c"]))
    return {r["location_id"]: (r["hdr_hash"], rstack.History(
                r["declared_rows"], wejscia.get(r["location_id"], ()), r["tool"],
                created=r["creation_time"]))
            for r in con.execute(
                "SELECT location_id, hdr_hash, declared_rows, tool, creation_time FROM stack_history")}


def names_index_pairs(con):
    """Świadectwa NAZW lightów archiwum (AR-108, D-1011-4) → `(biezace, dawne)`, pary `(frame_id,
    rdzeń)`: `biezace` - ścieżki lokacji (obecnych i nieobecnych), `dawne` - dawne ścieżki z dziennika
    zmian nazw Horreum (`location.renamed`, sprzed aliasów) i aliasy `light_name_alias` (zapis
    przenosin Custos, zmiany nazw od 0034). Jeden `raw_stem` po stronie ścieżek; alias jest już
    rdzeniem. Podział idzie do `resolve.stack.NameIndex.build` (luźny rdzeń tylko z dawnych nazw).
    Klatki zastąpione poza indeksem - sierota i następczyni dzielą ścieżkę, więc każda ich nazwa
    byłaby niejednoznaczna (lustro warunku okna w `_window_candidates`). Ten sam materiał liczy
    niejednoznaczność w skrypcie importu aliasów - jedna definicja indeksu dla obu."""
    biezace = [(r[0], rstack.raw_stem(r[1])) for r in con.execute(
        "SELECT l.frame_id, l.path FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE f.kind = 'light' AND f.superseded_by IS NULL")]
    dawne = [(r[0], rstack.raw_stem(r[1])) for r in con.execute(
        "SELECT l.frame_id, json_extract(e.payload, '$.before') FROM event e "
        "JOIN location l ON e.target = 'location:' || l.id JOIN frame f ON f.id = l.frame_id "
        "WHERE e.verb = 'location.renamed' AND f.kind = 'light' AND f.superseded_by IS NULL "
        "AND json_extract(e.payload, '$.before') IS NOT NULL")]
    dawne += [(r[0], r[1]) for r in con.execute(
        "SELECT a.frame_id, a.stem FROM light_name_alias a JOIN frame f ON f.id = a.frame_id "
        "WHERE f.kind = 'light' AND f.superseded_by IS NULL")]
    return biezace, dawne


def _names_index(con):
    """Indeks nazw lightów archiwum dla `_plan` (`names_index_pairs` → `NameIndex`)."""
    biezace, dawne = names_index_pairs(con)
    return rstack.NameIndex.build(biezace, dawne)


def _poza_przedzialem(con, frame_ids, start, end):
    """Czy któraś klatka zbioru z nazw leży POZA SUROWYM przedziałem czasu nagłówka stosu
    (`DATE-OBS`…`DATE-END`) - flaga „poza oknem nagłówka” mówi o CZASIE, nie o doborze okna: klatka
    w czasie okna, którą `_in_window` odsiał innym filtrem albo teleskopem na karcie, w oknie leży.
    Bez przedziału (brak któregoś końca) albo bez `DATE-OBS` klatki - poza. Czas przez
    `naming.header_dt` (SPOT parser ISO), jak w doborze okna."""
    if start is None or end is None:
        return True
    for (date_obs,) in con.execute(
            "SELECT h.date_obs FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.id IN (SELECT value FROM json_each(?))", (json.dumps(list(frame_ids)),)):
        t = header_dt(date_obs)
        if t is None or not (start <= t <= end):
            return True
    return False


def _plan(con, row, *, xml_reader, stored=None, names=None):
    """Materiał decyzji dla JEDNEJ klatki stosu - bez zapisu (czysta faza, testowalna osobno).

    HISTORIA Z BAZY, PLIK ZAPASOWO (AR-87): `stored` (`_stored_histories`) daje historię kopii
    wybranej w `_masters`, gdy kotwica wiersza równa się odciskowi nagłówka tej kopii - wtedy
    pliku nie czytamy. Brak wiersza albo rozjazd kotwicy → odczyt pliku jak dotąd, a gdy odcisk
    PRZECZYTANEGO tekstu (sha1 bajtów XML, ta sama definicja co `header_hash` kopii XISF) równa się
    odciskowi kopii, plan niesie `history_refresh` - przebieg zapisze go w fazie zapisu (atomowo,
    z CAS w klindze). Czytnik wstrzyknięty w testach oddaje tekst, którego odcisk z kopią się nie
    zgadza - wtedy plan nie odświeża niczego.

    KOLEJNOŚĆ ŹRÓDEŁ WEJŚĆ (D-1011-4, E4-9): (a) NAZWY wejść historii w indeksie `names`
    - pełny, unikalny zbiór wygrywa z oknem, także poza nim i przy oknie pustym albo
    zdegenerowanym (`outside_window`); (b) temperatury z nazw WBPP wobec okna (`temp`/`count`);
    (c) podzbiór temperatur okna → wiersze okna z werdyktem „plik użył N z M” (`used_rows`), bez
    powodu; (d) reszta → `history_mismatch`. Ranga `history` dla (a) i (b), `window` dla (c)."""
    header = json.loads(row["raw_json"]) if row["raw_json"] else {}
    xml, unread, brak_lokacji, przeczytany, odswiez = None, False, False, False, None
    zapis = (stored or {}).get(row.get("location_id"))
    historia = None
    if zapis is not None and row.get("header_hash") and zapis[0] == row["header_hash"]:
        historia = zapis[1]
    elif row["path"]:
        surowe = None
        try:
            surowe = xml_reader(row["path"])
            przeczytany = surowe is not None   # FITS: czytnik oddaje None bez I/O - to nie odczyt
        except Exception:              # plik zniknął/leży na odłączonym dysku — patrz docstring
            unread = True
        if surowe is not None:
            # Odcisk z SUROWYCH bajtów (`_read_history_xml`); czytnik tekstowy (testy) - z UTF-8.
            if isinstance(surowe, (bytes, bytearray)):
                xml = bytes(surowe).decode("utf-8", "replace")
            else:
                xml, surowe = surowe, surowe.encode("utf-8")
            if (row.get("location_id") is not None and row.get("header_hash")
                    and hashlib.sha1(surowe).hexdigest() == row["header_hash"]):
                odswiez = (row["location_id"], row["header_hash"], rstack.read_history(xml))
    else:
        # BRAK OBECNEJ LOKACJI TO TEN SAM STAN dla strażnika, co błąd odczytu: pliku nie ma pod
        # ręką, więc jego zeznania NIE ZNAMY. Dla POWIERZCHNI to jednak dwie różne rzeczy i dwie
        # różne recepty — „podłącz archiwum" jest nieprawdą dla stosu, którego w bibliotece nie ma
        # (skasowany plik roboczy WBPP, stos przeniesiony). Stąd drugi licznik: jeden fakt
        # dla decyzji, dwa dla człowieka.
        unread = brak_lokacji = True
    t = rstack.read_testimony(header, xml, history=historia)
    start, end = t.window_start, t.window_end
    # KOERCJA PRZY WEJŚCIU, nie w SQL-u: XISF oddaje KAŻDĄ kartę jako tekst (`_put(header,
    # keyword, value_raw)`), więc `EXPTIME` stosu to `'600.00'`, a `header.exptime` klatki to REAL.
    # Porównanie działałoby i tak — SQLite nakłada powinowactwo kolumny na parametr tekstowy — ale
    # stałoby na regule silnika zamiast na naszej decyzji, a półka grupująca po surowej wartości
    # rozdzieliłaby `'600.00'` od `600.0` bez śladu.
    exptime = _to_float(t.exptime)
    plan = {
        "frame_id": row["frame_id"], "testimony": t, "start": start, "end": end,
        "history_unread": unread, "no_location": brak_lokacji,
        "inputs": [], "asserted_by": None, "reason": None,
        "telescope_mismatch": False, "exptime": exptime, "raw_unreferenced": None,
        # PÓŁKA BEZ EKSPOZYCJI (R3) — zgodność ekspozycji rozstrzyga test PARY w `_shelf_ambiguous`,
        # bo próg D-DR-2 nie jest przechodni, a klucz słownika zakłada równoważność (powód tam).
        "shelf": (row["object_id"], row["filter_canon"], row["telescope_id"]),
        # Podstawa (0034): `basis` - token `LINEAGE_BASES` przy randze `history`, `used_rows` - N
        # werdyktu „N z M”, `outside_window` - zbiór z nazw sięga poza okno; `names_ambiguous` -
        # zbioru z nazw odmówiono, bo nazwa trafia dwie klatki (licznik przebiegu).
        "basis": None, "used_rows": None, "outside_window": False, "names_ambiguous": False,
        "history_read": przeczytany, "history_refresh": odswiez,
    }
    if row["object_id"] is None:
        plan["reason"] = REASON_NO_OBJECT
        return plan
    okno_jest = not (start is None or end is None or t.degenerate)
    kand, rozjazd, raw_bez_odniesienia = [], False, 0
    if okno_jest:
        # GUARD ZEZNANIA (R3) STOI W `okno_jest` I TO JEST SPRAWDZONE, NIE ZAŁOŻONE: master bez
        # `EXPTIME` tu nie wchodzi, bo `testimony.degenerate` jest wtedy `True` z definicji („brak
        # czasu ekspozycji też jest True — nie mamy wtedy czym ograniczyć doboru", `resolve/stack.py`).
        # Własny guard na `exptime is None` był tu przez chwilę i został ZDJĘTY jako martwy - pas
        # nadzbioru wokół `None` nigdy nie powstaje. Pinuje to test imienny
        # `test_master_bez_ekspozycji_konczy_na_oknie_zdegenerowanym`.
        kand, rozjazd, raw_bez_odniesienia = _in_window(
            _window_candidates(con, object_id=row["object_id"], exptime=exptime),
            start=start, end=end, filter_canon=row["filter_canon"],
            telescope_id=row["telescope_id"], exptime=exptime, utc_offset_min=row["utc_offset_min"])
        plan["telescope_mismatch"] = rozjazd
        # UWAGA OBOK WERDYKTU (G2-1d): RAW-y, których nie da się umieścić w czasie, mówią ZAWSZE -
        # także gdy rodowód domknął się z innego materiału albo werdykt brzmi inaczej. Jedyny wyjątek
        # to werdykt `offset_unknown`, który mówi dokładnie to samo (niżej; CHECK 0020 pilnuje).
        # Zero znaczy „brak uwagi", więc idzie jako NULL - stan bez uwagi ma jedną postać.
        plan["raw_unreferenced"] = raw_bez_odniesienia or None
    if t.rows is not None and names is not None:
        # (a) NAZWY PRZED OKNEM (AR-108, E4-9): plik zeznaje, z czego powstał, a nazwy jego wejść
        # trafiają klatki archiwum jedna w jedną - to jest zbiór, nie kandydat. Wygrywa z oknem
        # także wtedy, gdy wychodzi poza nie (4 stosy E4-9 z oknem za wąskim) albo okna nie ma
        # (`no_candidates`, okno zdegenerowane); flaga mówi to człowiekowi. Odmowa (wejście bez
        # trafienia albo nazwa dwóch klatek) schodzi do testu temperatur - nie do wyboru.
        werdykt, po_nazwie = rstack.inputs_by_name(t.inputs, names)
        plan["names_ambiguous"] = werdykt == rstack.NAMES_AMBIGUOUS
        if werdykt == rstack.NAMES_FULL:
            # `telescope_mismatch` i uwaga RAW zostały ustawione wyżej z okna - zostają przy planie.
            plan["inputs"] = [{"frame_id": fid} for fid in po_nazwie]
            plan["asserted_by"], plan["basis"] = "history", BASIS_NAME
            plan["outside_window"] = _poza_przedzialem(con, po_nazwie, start, end)
            return plan
    if not okno_jest:
        # Okno bez końca i okno o długości jednej klatki to ten sam brak: nie ma czym wybierać.
        plan["reason"] = REASON_NO_WINDOW if start is None or end is None else REASON_DEGENERATE
        return plan
    if not kand:
        # KOLEJNOŚĆ POWODÓW = KOLEJNOŚĆ RECEPT, nie hierarchia ważności. Rozjazd teleskopu idzie
        # pierwszy, bo kandydaci BYLI i odrzuciła ich oś — recepta („napraw kartę") jest wtedy
        # konkretniejsza niż „wskaż odniesienie". `offset_unknown` bije `no_candidates`, bo to
        # cała treść R2: milczenie o istniejącym materiale jest nieprawdą, a nie brakiem odpowiedzi.
        if rozjazd:
            plan["reason"] = REASON_TELESCOPE
        elif raw_bez_odniesienia:
            plan["reason"] = REASON_OFFSET_UNKNOWN
            plan["raw_unreferenced"] = None     # werdykt mówi to samo - uwaga byłaby dublem
        else:
            plan["reason"] = REASON_NO_CANDIDATES
        return plan
    if t.rows is None:
        plan["inputs"], plan["asserted_by"] = kand, "window"
        return plan
    ok, poza, nadwyzka = rstack.inputs_contained(t, [r["ccd_temp"] for r in kand])
    if ok:
        # (b) Temperatury z nazw WBPP potwierdzają zbiór okna; bez ani jednej czytelnej temperatury
        # test sprowadza się do licznika (`count`) - podstawa mówi to wprost (D-1011-3).
        plan["inputs"], plan["asserted_by"] = kand, "history"
        plan["basis"] = BASIS_TEMP if t.declared_temps else BASIS_COUNT
        return plan
    if not poza and nadwyzka > t.unreadable_inputs:
        # (c) WBPP użył PODZBIORU okna (21 z 26 stosów E4-9: okno za szerokie o 1..34 klatek).
        # Których klatek - plik bez nazw archiwum nie mówi, więc wiersze zostają kandydatami okna
        # (`window`), a werdykt mówi ile: N z historii, M = wiersze okna. Nie jest to powód odmowy -
        # okno nie myli się co do materiału, tylko jest go więcej, niż weszło.
        plan["inputs"], plan["asserted_by"] = kand, "window"
        plan["used_rows"] = sum(1 for i in t.inputs if i.enabled)
        return plan
    plan["reason"] = REASON_MISMATCH            # (d) strażnik 2: myli się OKNO, nie zeznanie pliku
    return plan


def run_stack_lineage(con, *, now, actor="stacks", xml_reader=None, progress=None,
                      should_cancel=None):
    """Przebieg rodowodu stosów — idempotentny: drugi przebieg na niezmienionych danych daje ZERO
    nowych wierszy i ZERO eventów ZAPISU (`integration.recorded`/`updated`/`linked`/`unlinked`) -
    UNIQUE z 0012 trzyma idempotencję wierszy, porównanie kompletu faktów w klindze - głowy.

    ZDARZENIE ZBIORCZE LECI PRZY KAŻDEJ POWTÓRCE I TO JEST ZAMIERZONE (E2-1): jedno
    `integration.lineage_summary` na przebieg, gdy są stosy bez rodowodu albo pominięte
    (`repo.flag_stack_lineage_summary`). Opisuje STAN po przebiegu, nie deltę, więc powtórka
    je powiela - licznik z dziennika rośnie z liczbą PRZEBIEGÓW. Kto liczy sprawy, liczy STAN
    tabel albo `count(DISTINCT target)`, nigdy `count(event)` (873 zdarzenia na 440 spraw).

    Kolejność faz jest istotna: NAJPIERW plan dla wszystkich stosów (bo nierozłączność okien to
    fakt o PARZE integracji, nie o pojedynczej), POTEM zapis. `xml_reader` wstrzykiwalny — testy
    podają zeznanie wprost, produkcja czyta nagłówek z dysku.

    ANULOWANIE (`should_cancel`) sprawdzane przed KAŻDYM odczytem nagłówka: faza planu czyta pliki
    (zawieszony udział SMB stoi na każdym do timeoutu), a niczego nie zapisuje - przerwanie w niej
    zostawia bazę nietkniętą. Faza zapisu idzie do końca."""
    s = StackLineageSummary()
    reader = xml_reader if xml_reader is not None else _read_history_xml
    rows = _masters(con)
    s.stacks = len(rows)
    # Historia i nazwy RAZ na przebieg (AR-87, AR-108): dwa zapytania zamiast zapytania per stos.
    zapisane = _stored_histories(con)
    nazwy = _names_index(con)
    plany = []
    for i, row in enumerate(rows, 1):
        if should_cancel is not None and should_cancel():
            s.cancelled = True
            return s
        plan = _plan(con, row, xml_reader=reader, stored=zapisane, names=nazwy)
        s.history_reads += plan["history_read"]
        plany.append(plan)
        if progress is not None:
            progress(i, len(rows), row["frame_id"])
    ambi = _shelf_ambiguous(plany)
    # KTÓRE stosy pominięto — nie tylko ILE. „Pominięto 6" bez listy jest receptą bez adresu:
    # z bazy nie da się ich odtworzyć (głowy nietknięte, brak markera), więc jedyną drogą byłoby
    # zgadywanie po gridzie. Lista idzie do TEGO SAMEGO eventu zbiorczego (§6), nie do osobnego.
    pominiete = []

    for p in plany:
        t = p["testimony"]
        s.history_unread += p["history_unread"]
        s.no_location += p["no_location"]
        s.names_ambiguous += p["names_ambiguous"]
        if p["history_refresh"] is not None:
            # Odczyt pliku w planie (brak wiersza historii albo rozjazd kotwicy) zostawia historię
            # w bazie - następny przebieg tego stosu nie czyta udziału. CAS w klindze: nagłówek
            # kopii zmieniony od planu odmawia zapisu i zostaje drogą zapasową.
            loc_id, hdr, historia = p["history_refresh"]
            s.history_refreshed += repo.record_stack_history(
                con, location_id=loc_id, hdr_hash=hdr, history=historia, now=now, actor=actor)
        # STRAŻNIK 4 — decyzja PRZED policzeniem i PRZED zapisem CZEGOKOLWIEK. Reguła brzmi „bez
        # zeznania nie dotykamy tego stosu", więc obejmuje GŁOWĘ integracji tak samo jak wiersze.
        # Guard postawiony za `upsert_integration` chronił tylko wiersze i przez to sam produkował
        # dwa defekty:
        #   * głowa dostawała `unresolved_reason` z planu, którego wiersze właśnie ODMÓWIŁ
        #     zastosować (powód wynika z BAZY — obiekt, okno, kandydaci, teleskop — więc powstaje
        #     i bez pliku), a stare wiersze zostawały → stan łamał inwariant bramki §5.14
        #     „powód wyklucza wejścia automatu";
        #   * `t.rows`/`t.tool` przy nieodczytanym pliku są `None`, więc jeden przebieg offline
        #     KASOWAŁ fakty zeznania (`declared_rows`, `tool`, drizzle) przy wierszach `history`
        #     zachowanych obok — panel mówił „plik zeznał" i nie umiał powiedzieć, ile deklaruje.
        # ZAKRES STRAŻNIKA IDZIE ZA ŹRÓDŁEM FAKTU, nie za jednym bitem „plik nieczytelny". Z PLIKU
        # pochodzą WYŁĄCZNIE `rows`/`inputs`/`tool` (`resolve.stack.read_testimony`); okno,
        # `degenerate`, osie i powód liczy się z BAZY i są tak samo prawdziwe bez pliku. Strażnik
        # zamrażający całą głowę był więc o rząd wielkości za szeroki: na realnym archiwum tylko
        # 6 ze 128 rodowodów stoi na zeznaniu pliku, a odmawiał aktualizacji wszystkim 128 —
        # master po naprawie karty zostawał z relacjami do lightów INNEGO obiektu.
        #
        # Chronimy więc dokładnie to, co bez pliku traci pokrycie:
        #   * WIERSZE rodowodu `history` (plan spadłby na okno i zdegradował dowód do kandydata);
        #   * FAKTY ZEZNANIA w głowie (`tool`, `declared_rows`, drizzle) — `None` z nieodczytanego
        #     pliku skasowałby je, choć nikt ich nie obalił.
        # Reszta głowy jedzie normalnie, bo wynika z bazy.
        # STAN ZAPISANY LICZYMY ZAWSZE, nie tylko przy nieczytelnym pliku (S2b, R26#4). Czytelność
        # pliku rozstrzyga, skąd biorą się FAKTY ZEZNANIA (niżej) — nie rozstrzyga, czy wolno
        # skasować cudzy dowód. Warunek `if p["history_unread"]` mieszał te dwa pytania i zostawiał
        # rodowód `history` bezbronnym dokładnie tam, gdzie plik leżał na miejscu: gest osi obiektu
        # na LIGHCIE (S2b „Cofnij"/„Nazwij") wyjmuje klatkę z okna → `inputs_contained` nie
        # przechodzi → `REASON_MISMATCH` → `_reconcile` KASUJE relacje dowiedzione zeznaniem pliku.
        stan = _zapisany_stan(con, p["frame_id"])
        # CHRONIONY = rodowód ZAPISANY jest MOCNIEJSZY niż to, co przebieg umie ustalić TERAZ.
        # Pytanie o RANGĘ, nie o wyliczankę wartości (`zrodlo not in (None,'window')` gubiło
        # sąsiednie zeznanie przy każdym nowym źródle) i nie o jeden bit „plik nieczytelny".
        # Kanon precedencji ma JEDNEGO właściciela — `repo.RANGA_ASSERT`. Plan Z POWODEM wypowiada
        # się z siłą OKNA, nie „poniżej wszystkiego": powód znaczy „przeliczyłem okno z BAZY i nic
        # w nim nie ma", a bazę przebieg czyta w całości — więc rodowód stojący na samym oknie musi
        # dać się tym powodem obalić. Ranga poniżej najniższej zamrażała rodowód `window` przy
        # naprawie karty stosu (bramka „rodowód z okna aktualizuje się mimo nieczytelnego pliku"
        # zaczerwieniła się natychmiast) — to dokładnie ta nadmiarowa ochrona, przed którą broni
        # człon lustrzany.
        # To ochrona przed DEGRADACJĄ, a NIE zamrożenie: odtworzenie tej samej siły (plan `history`
        # wobec zapisanego `history`) przechodzi normalnie i stos dalej się rekoncyliuje.
        # DECYZJA O ZAPISIE PYTA O MINIMUM (`zrodlo`), LICZNIK O MAKSIMUM (`zrodlo_max`) — dwa
        # pytania, dwie wartości (P4-4, patrz `_zapisany_stan`). Zlanie ich w jedno zamraża stos
        # po jednym geście albo ukrywa rękę w raporcie; oba stany już tu były.
        ranga_planu = repo.RANGA_ASSERT[p["asserted_by"] or "window"]
        ranga_stanu = _ranga(stan["zrodlo"]) if stan is not None and stan["zrodlo"] else -1
        chroniony = ranga_stanu > ranga_planu
        # Kto ten rodowód ustalił: mocniejsze z zapisanego i z planu. Stos, w którym stoi choć jeden
        # werdykt ręki, ma się meldować jako werdykt ręki — także gdy przebieg właśnie liczy resztę
        # jego wierszy od nowa.
        zrodlo_licznika = _mocniejsze(stan["zrodlo_max"] if stan is not None else None,
                                      p["asserted_by"])
        if chroniony and p["reason"]:
            # JEDYNY przypadek, w którym trzeba zostawić stos w spokoju w całości: powodu nie da
            # się zapisać, nie kasując wierszy (inwariant §5.14 „powód wyklucza wejścia automatu"),
            # a kasować ich nie wolno, bo to dowód. Liczniki idą wtedy ze STANU — rodowód istnieje,
            # tylko nie myśmy go w tym przebiegu ustalili.
            _bump_kept(s, p)
            pominiete.append(p["frame_id"])
            s.linked += 1
            _bump(s.by_assert, zrodlo_licznika)
            s.ambiguous += bool(stan["ambiguous"])
            s.telescope_mismatch += bool(stan["telescope_mismatch"])
            # Wyjątek od „w całości": `XISF:CreationTime` z czytelnego pliku (AR-10). To fakt zeznania
            # jak sygnatura, którego nic tu nie obala, a ta gałąź jest jedyną drogą stosu chronionego
            # do daty (obietnica 0026). Wąsko: sama data, i tylko gdy plik ją ma - brak daty
            # w pliku ani plik nieczytelny zapisanej nie kasują.
            if not p["history_unread"] and t.created:
                repo.record_integration_creation_time(
                    con, master_frame_id=p["frame_id"], creation_time=t.created, now=now,
                    actor=actor)
            continue
        if p["reason"]:
            _bump(s.reasons, p["reason"])
        else:
            s.linked += 1
            # Źródło ze STANU, gdy wiersze zostają nietknięte: one naprawdę są `history`, choć plan
            # — bez pliku — umiałby powiedzieć tylko „window". Ta sama wartość niesie werdykt ręki
            # ze stosu MIESZANEGO, którego plan sam z siebie nie zna.
            _bump(s.by_assert, zrodlo_licznika)
        s.ambiguous += p["frame_id"] in ambi
        # ROZJAZD TELESKOPU LICZYMY TYLKO TAM, GDZIE RODOWÓD POWSTAŁ — bo tylko tam jest FLAGĄ
        # („relacje są, ale karta się nie zgadza"). Rozjazd, który skończył się ODMOWĄ, siedzi już
        # w `reasons['telescope_mismatch']`; wspólny licznik meldował go dwa razy i kazał raportowi
        # mówić „karta do naprawy: N" o stosach, przy których nie zapisano niczego.
        if p["telescope_mismatch"] and not p["reason"]:
            s.telescope_mismatch += 1
        wejscia = [r["frame_id"] for r in p["inputs"]]
        # Fakty zeznania: ze STANU, gdy pliku nie przeczytaliśmy (nikt ich nie obalił), z pliku
        # w każdym innym wypadku — i to jest JEDYNE pytanie, które rozstrzyga czytelność pliku
        # (ochronę wierszy rozstrzyga RANGA, wyżej). Warunek na samym `stan is not None` znaczyłby
        # od S2b „mam zapisany rodowód", a nie „nie mam czym zastąpić" — i zamroziłby fakty zeznania
        # przy KAŻDYM stosie, który już raz przez ten przebieg przeszedł.
        # Odcisk chronionego rodowodu też zostaje — to odcisk OSTATNIEGO
        # DOPASOWANIA AUTOMATU (nie zbioru wierszy niewykluczonych: odrzucenie ręką zostawia wiersz
        # w tabeli, a odcisku nie przelicza), więc zastąpienie go odciskiem świeżo policzonego okna
        # byłoby podmianą faktu o przeszłości na fakt o czymś innym.
        # `creation_time` (AR-10) jest takim samym faktem zeznania pliku jak sygnatura.
        if p["history_unread"] and stan is not None:
            tool_v, rows_v = stan["tool"], stan["declared_rows"]
            driz_v, dis_v = stan["drizzle_inputs"], stan["disabled_inputs"]
            created_v = stan["creation_time"]
        else:
            tool_v, rows_v, created_v = t.tool, t.rows, t.created
            if created_v is None and stan is not None:
                # Plik bez daty zapisanej NIE kasuje (AR-50 (4)) - ta sama reguła co w gałęzi
                # chronionej z powodem wyżej: data powstania to fakt o przeszłości, a milczenie
                # pliku go nie obala (zeznanie podmienionej treści to inna klatka).
                created_v = stan["creation_time"]
            driz_v = sum(1 for x in t.inputs if x.has_drizzle) if t.rows is not None else None
            dis_v = sum(1 for x in t.inputs if not x.enabled) if t.rows is not None else None
        odcisk = stan["integ_hash"] if chroniony else _fingerprint(con, wejscia)
        # PODSTAWA idzie za WIERSZAMI, jak odcisk: chroniony rodowód (wiersze nietknięte) zachowuje
        # podstawę, na której te wiersze stanęły; plan, który właśnie pisze wiersze, daje swoją.
        if chroniony:
            basis_v, poza_v, uzyte_v = (stan["lineage_basis"], stan["outside_window"],
                                        stan["used_rows"])
        else:
            basis_v, poza_v, uzyte_v = p["basis"], int(p["outside_window"]), p["used_rows"]
            if not p["reason"]:
                _bump(s.by_basis, p["basis"] or (BASIS_SUBSET if p["used_rows"] is not None
                                                 else p["asserted_by"]))
                s.outside_window += bool(p["outside_window"])
        iid, _ = repo.upsert_integration(
            con, master_frame_id=p["frame_id"], integ_hash=odcisk, tool=tool_v,
            window_start=p["start"].isoformat() if p["start"] else None,
            window_end=p["end"].isoformat() if p["end"] else None,
            declared_rows=rows_v, drizzle_inputs=driz_v, disabled_inputs=dis_v,
            degenerate=int(t.degenerate), ambiguous=int(p["frame_id"] in ambi),
            telescope_mismatch=int(p["telescope_mismatch"]),
            unresolved_reason=p["reason"], raw_unreferenced=p["raw_unreferenced"],
            creation_time=created_v, lineage_basis=basis_v, outside_window=poza_v,
            used_rows=uzyte_v, now=now, actor=actor)
        if chroniony:
            _bump_kept(s, p)            # głowa zaktualizowana, WIERSZE nietknięte
            pominiete.append(p["frame_id"])
        else:
            s.linked_new += _zapisz_wejscia(con, iid, wejscia, p["asserted_by"],
                                            now=now, actor=actor)
            s.unlinked += _reconcile(con, iid, wejscia, now=now, actor=actor)

    # `inputs` liczymy ze STANU, nie z planu (lustro `LineageSummary.linked`): odrzucenie ręką
    # zostawia wiersz w tabeli, ale ten sub w obraz NIE wszedł — plan wciąż widzi go jako kandydata,
    # więc rachunek z planu zawyżałby o każdy werdykt „nie". `linked`/`reasons` zostają Z PLANU,
    # bo to one domykają partycję populacji (człowiek wykluczający WSZYSTKIE wejścia nie zmienia
    # tego, co automat potrafił ustalić — a bramka pyta właśnie o to).
    s.inputs = con.execute(
        "SELECT count(*) FROM integration_input WHERE excluded = 0").fetchone()[0]
    s.reasons = dict(sorted(s.reasons.items()))
    repo.flag_stack_lineage_summary(con, sorted(s.reasons.items()), now, actor=actor,
                                    kept_unread=s.kept_unread, kept_frames=pominiete,
                                    kept_proven=s.kept_proven)
    return s


def _fingerprint(con, frame_ids):
    """Odcisk ZBIORU wejść — po `sha1_data`, nie po `id`: tożsamość treści przeżywa przebudowę
    bazy, a numer wiersza nie. FAKT o bieżącym dopasowaniu (§4.1), nigdy klucz rekordu."""
    if not frame_ids:
        return None
    return sha1_of_set(
        r["sha1_data"] for fid in frame_ids
        for r in con.execute("SELECT sha1_data FROM frame WHERE id = ?", (fid,)))


def _zapisany_stan(con, master_frame_id):
    """ZAPISANY stan rodowodu tego stosu — albo `None`, gdy rodowodu nie ma. Pytanie o STAN, nie
    o plan: rozstrzyga, czego przebiegowi bez zeznania pliku nie wolno ruszyć i czym to policzyć.

    `zrodlo` bierzemy z wierszy NIEWYKLUCZONYCH (`excluded = 0`): stos, z którego człowiek odrzucił
    wszystkie kandydatury, nie ma rodowodu w żadnym sensie, którego broni strażnik — i nie ma prawa
    trafić do `linked`, skoro `inputs` liczone ze stanu go nie widzi.

    DWA ŹRÓDŁA, BO DWA RÓŻNE PYTANIA (P4-4, rozstrzygnięte 0809 dopiero po tym, jak jedna wartość
    okazała się na nie za wąska):

    * `zrodlo` — **MINIMUM rangi**, odpowiada „czego automat dotknie". Wiersze, których przebieg
      nie ma prawa ruszyć, broni klinga PER WIERSZ (`unlink_integration_input` omija `user`,
      `link_integration` nie obniża rangi), więc strażnik STOSU ma sens tylko wtedy, gdy CAŁY
      zapisany rodowód jest mocniejszy od planu. Dla stosu mieszanego (`window` + `user`) najsłabsze
      wiersze są dokładnie tak mocne jak plan — i tak ma zostać: sub, który wypadł z okna (bo ktoś
      poprawił mu `DATE-OBS`), musi dać się odpiąć także wtedy, gdy obok stoi werdykt ręki.
    * `zrodlo_max` — **MAKSIMUM rangi**, odpowiada „kto ten rodowód ustalił". Idzie WYŁĄCZNIE do
      liczników (`by_assert`), bo to była prawdziwa treść P4-4: stos z werdyktem człowieka meldował
      się jako robota automatu i ręki nie było widać w żadnej liczbie.

    PIERWSZA WERSJA TEJ NAPRAWY UŻYWAŁA MAKSIMUM DO OBU PYTAŃ i zamrażała rekoncyliację całego
    stosu po jednym geście — obrona za szeroka, złapana przez
    `test_reconcile_zdejmuje_wypadle_wejscie_ale_nie_rusza_reki`. Zapis zostaje, żeby nikt nie
    „uprościł" tego z powrotem do jednej wartości.

    Minimum i maksimum liczymy W PYTHONIE, bo kanon rangi ma jednego właściciela
    (`repo.RANGA_ASSERT`): `CASE` sklejony z tego słownika byłby SQL-em dynamicznym (meta-tripwir
    AST) albo drugą kopią kanonu.

    Pozostałe pola to FAKTY ZEZNANIA PLIKU plus odcisk — wartości, których przebieg bez pliku nie
    ma czym zastąpić, a `None` z nieodczytanego nagłówka by je skasował.

    DWA PYTANIA, DWA ZAKRESY — i to jest cała subtelność tej funkcji. „Czy są zapisane fakty
    zeznania" (głowa) NIE zależy od tego, czy jakikolwiek wiersz przeżył: stos, z którego człowiek
    odrzucił wszystkie kandydatury, wciąż ma w głowie `declared_rows` z czasu, gdy plik był
    czytelny. Warunek `EXISTS` na wierszach kasował te fakty przez `None` w UPDATE — czyli
    wskrzeszał defekt, który sam ten moduł już raz naprawiał. Głowę czytamy więc BEZ warunku,
    a brak rodowodu sygnalizuje `zrodlo IS NULL`.

    Pytamy po KLATCE MASTERA, bo wołający nie zna jeszcze `integration.id` — i nie ma go poznać,
    skoro właśnie decyduje, czy w ogóle pisać."""
    glowa = con.execute(
        "SELECT i.id, i.tool, i.declared_rows, i.drizzle_inputs, i.disabled_inputs, i.integ_hash, "
        "       i.ambiguous, i.telescope_mismatch, i.creation_time, i.lineage_basis, "
        "       i.outside_window, i.used_rows "
        "FROM integration i WHERE i.master_frame_id = ?",
        (master_frame_id,)).fetchone()
    if glowa is None:
        return None
    zrodla = [r["asserted_by"] for r in con.execute(
        "SELECT DISTINCT asserted_by FROM integration_input "
        "WHERE integration_id = ? AND excluded = 0", (glowa["id"],))]
    stan = {k: glowa[k] for k in glowa.keys()}
    stan["zrodlo"] = min(zrodla, key=_ranga, default=None)
    stan["zrodlo_max"] = max(zrodla, key=_ranga, default=None)
    return stan


def _ranga(zrodlo):
    """Ranga zeznania wg jedynego właściciela kanonu; `None` i wartość nieznana → poniżej najniższej."""
    return repo.RANGA_ASSERT.get(zrodlo, -1)


def _mocniejsze(a, b):
    """To z dwóch zeznań, które waży więcej — do LICZNIKÓW, nigdy do decyzji o zapisie."""
    return a if _ranga(a) >= _ranga(b) else b


def _zapisz_wejscia(con, integration_id, frame_ids, asserted_by, *, now, actor):
    if not frame_ids:
        return 0
    return sum(repo.link_integration(con, integration_id=integration_id, input_frame_id=fid,
                                     asserted_by=asserted_by, now=now, actor=actor)
               for fid in frame_ids)


def _reconcile(con, integration_id, frame_ids, *, now, actor):
    """Zdejmij wejścia, których bieżące dopasowanie już nie wskazuje (§4.2). Relacje `user`
    pomija sama klinga — automat nie cofa rozstrzygnięcia ręki."""
    stare = [r["input_frame_id"] for r in con.execute(
        "SELECT input_frame_id FROM integration_input WHERE integration_id = ?", (integration_id,))]
    zbedne = set(stare) - set(frame_ids)
    return sum(repo.unlink_integration_input(con, integration_id=integration_id, input_frame_id=fid,
                                             now=now, actor=actor)
               for fid in sorted(zbedne))


_ZRODLA_AUTOMATU = ("window", "history")
"""Wiersze, które zbiór dokładny z żniw ZASTĘPUJE: wynik łańcucha (okno, zeznanie pliku dopasowane do
okna). Lustro listy dozwolonych w `repo.unlink_integration_input` - zapis i predykat „czeka” pytają
o ten sam zbiór, inaczej predykat obiecywałby zdjęcie, którego zapis nie wykona (pętla przyjęć)."""


def record_harvest_inputs(con, *, master_sha1_data, input_frame_ids, now, actor="harvest"):
    """RODOWÓD Z ŻNIW - zbiór DOKŁADNY wejść stosu wciągniętego z wydania Horreum (Qt-wolna, zapis
    wyłącznie przez `repo`) → `{reason, linked, upgraded, dropped, kept_user}`.

    PO CO: łańcuch Dostawy daje stosowi wejścia z OKNA CZASU (wszystkie lighty obiektu, filtru,
    teleskopu i ekspozycji między `DATE-OBS` a `DATE-END`), więc klatki odrzucone przez WBPP zostają
    w rodowodzie jako kandydaci - albo, gdy plik zeznaje mniej wejść, niż okno ma klatek, strażnik 2
    gasi rodowód w całości (`history_mismatch`). Żniwa znają zbiór DOKŁADNY (nazwy wejść historii ↔
    nazwy lightów wydania), więc wołający podaje go tu PO łańcuchu: każde wejście → ranga `harvest`
    (`repo.link_integration` podnosi `window` i `history`, nie rusza `user`), wejścia automatu
    (`window`, `history`) spoza zbioru schodzą (`repo.unlink_integration_input`), `user` zostaje
    zawsze, `harvest` spoza zbioru też (klinga go nie zdejmuje - dowód manifestu obala tylko ręka).
    `history` spoza zbioru SCHODZI (Z1, D-1011-2): to wynik łańcucha z oknem równej liczności, a nie
    drugi dowód - przebieg po korekcie `DATE-OBS` lightu ze zbioru dopisywał tak klatkę odrzuconą
    przez WBPP, a ponowne przyjęcie zostawiało ją obok zbioru dokładnego (test bo na scratchu fali 9).

    GŁOWA INTEGRACJI IDZIE ZA WIERSZAMI: powód odmowy z łańcucha (`history_mismatch`, `no_object`…)
    obok wierszy automatu łamałby inwariant bramki akceptacji „powód wyklucza wejścia automatu”
    (`scripts/acceptance_s5.py`), więc głowa
    dostaje `unresolved_reason=None` i odcisk tego zbioru (`_fingerprint`), resztę faktów bez zmian
    (`repo.upsert_integration` - idempotentny, ta sama głowa bez eventu). Następny `run_stack_lineage`
    widzi rodowód `harvest` mocniejszy od każdego planu (`RANGA_ASSERT`; plan umie najwyżej `history`):
    przy powodzie zostawia stos w całości, bez powodu chroni wiersze (`kept_proven` w obu) - ani okna,
    ani zeznania pliku dopasowanego do okna z powrotem nie dokłada.

    Klatka stosu po `sha1_data`; wiersz `integration` MUSI już istnieć (stawia go `run_stack_lineage`
    w łańcuchu) - brak klatki albo wiersza → `reason='no_integration'`, zero zapisu. Wejście, które nie
    jest lightem bazy, albo pusty zbiór → `ValueError` (EXPECT: stos nie wchodzi w stos, a integracja
    bez wejść zawsze niesie powód - ta sama bramka akceptacji). Liczniki: `linked`
    = nowe wiersze, `upgraded` = `window`/`history` → `harvest`, `dropped` = zdjęte `window`/`history`
    spoza zbioru, `kept_user` = wiersze
    ręki nietknięte (w zbiorze i poza nim - to stan, nie delta: przy każdym wołaniu liczy je od nowa).
    Drugie wołanie z tym samym zbiorem: liczniki mutacji (`linked`, `upgraded`, `dropped`) zerowe
    i zero eventów.

    JEDNA TRANSAKCJA (`repo.atomic`) na całe wołanie, z odczytami głowy, lightów i wierszy w środku:
    awaria w połowie zostawiłaby wiersze `history` obok niezdjętego powodu, a odczyt sprzed transakcji
    mógłby opisywać stan, który inny pisarz zdążył zmienić. Kolejność zapisów i tak trzyma inwariant na
    każdym kroku: wiersze `harvest`, potem głowa bez powodu, na końcu zdjęcia automatu."""
    wynik = {"reason": None, "linked": 0, "upgraded": 0, "dropped": 0, "kept_user": 0}
    zbior = sorted({int(i) for i in input_frame_ids})
    with repo.atomic(con):
        glowa = con.execute(
            "SELECT i.id, i.master_frame_id, i.tool, i.window_start, i.window_end, i.declared_rows, "
            "       i.drizzle_inputs, i.disabled_inputs, i.degenerate, i.ambiguous, i.telescope_mismatch, "
            "       i.raw_unreferenced, i.creation_time "
            "FROM frame f JOIN integration i ON i.master_frame_id = f.id WHERE f.sha1_data = ?",
            (master_sha1_data,)).fetchone()
        if glowa is None:
            return {**wynik, "reason": "no_integration"}
        if not zbior:
            raise ValueError(f"rodowód z żniw bez wejść (stos {master_sha1_data}) - głowa bez powodu "
                             "i bez wierszy byłaby cichą pustką")
        lighty = {r[0] for r in con.execute(
            "SELECT id FROM frame WHERE kind = 'light' AND id IN (SELECT value FROM json_each(?))",
            (json.dumps(zbior),))}
        if set(zbior) - lighty:
            raise ValueError(f"wejścia stosu spoza lightów bazy: {sorted(set(zbior) - lighty)}")
        iid = glowa["id"]
        stan = {r["input_frame_id"]: r["asserted_by"] for r in con.execute(
            "SELECT input_frame_id, asserted_by FROM integration_input WHERE integration_id = ?", (iid,))}
        for fid in zbior:
            przed = stan.get(fid)
            if przed == "user":
                wynik["kept_user"] += 1
                continue
            if repo.link_integration(con, integration_id=iid, input_frame_id=fid, asserted_by="harvest",
                                     now=now, actor=actor):
                wynik["linked" if przed is None else "upgraded"] += 1
        repo.upsert_integration(
            con, master_frame_id=glowa["master_frame_id"], integ_hash=_fingerprint(con, zbior),
            tool=glowa["tool"], window_start=glowa["window_start"], window_end=glowa["window_end"],
            declared_rows=glowa["declared_rows"], drizzle_inputs=glowa["drizzle_inputs"],
            disabled_inputs=glowa["disabled_inputs"], degenerate=glowa["degenerate"],
            ambiguous=glowa["ambiguous"], telescope_mismatch=glowa["telescope_mismatch"],
            unresolved_reason=None, raw_unreferenced=glowa["raw_unreferenced"],
            creation_time=glowa["creation_time"], now=now, actor=actor)
        for fid, zrodlo in sorted(stan.items()):
            if fid in zbior:
                continue
            if zrodlo == "user":
                wynik["kept_user"] += 1
            elif zrodlo in _ZRODLA_AUTOMATU and repo.unlink_integration_input(
                    con, integration_id=iid, input_frame_id=fid, now=now, actor=actor):
                wynik["dropped"] += 1
    return wynik


def harvest_lineage_pending(con, *, master_sha1_data, input_frame_ids):
    """READ-ONLY lustro `record_harvest_inputs`: czy baza NIE MA jeszcze rodowodu dokładnego tego
    stosu z żniw - True, gdy łańcuch Dostawy + zapis po nim mają tu coś do zrobienia (AR-104: zbiór
    leży tylko w zeznaniu żniw w folderze wydania, więc folderu nie wolno jeszcze skasować).

    True: klatki stosu baza nie zna (kopia nieprzyjęta), stos bez wiersza integracji (postawi go
    łańcuch), wejście zbioru bez wiersza `harvest`/`user`, jakikolwiek wiersz automatu `window`/`history`
    - w zbiorze zapis go podniesie, poza nim zdejmie (Z1: nadmiar, którego do v33 predykat nie widział),
    głowa z powodem odmowy albo z odciskiem innym niż odcisk zbioru (`_fingerprint` - zapis go
    przepisze; łańcuch odcisku stosu chronionego nie rusza, więc po zapisie nie wraca). False: zapis
    byłby bez mutacji - albo nie ma czego zapisać (klatka wycofana, klatka nie jest stosem, zbiór pusty
    albo z wejściem spoza lightów: tam `record_harvest_inputs` odmawia, więc „czeka” znaczyłoby „czeka
    na zawsze”)."""
    zbior = sorted({int(i) for i in input_frame_ids})
    klatka = con.execute("SELECT id, kind, retired_at FROM frame WHERE sha1_data = ?",
                         (master_sha1_data,)).fetchone()
    if klatka is None:
        return bool(zbior)
    if klatka["retired_at"] is not None or klatka["kind"] != "master_light" or not zbior:
        return False
    lighty = {r[0] for r in con.execute(
        "SELECT id FROM frame WHERE kind = 'light' AND id IN (SELECT value FROM json_each(?))",
        (json.dumps(zbior),))}
    if set(zbior) - lighty:
        return False
    glowa = con.execute("SELECT id, unresolved_reason, integ_hash FROM integration WHERE master_frame_id = ?",
                        (klatka["id"],)).fetchone()
    if (glowa is None or glowa["unresolved_reason"] is not None
            or glowa["integ_hash"] != _fingerprint(con, zbior)):
        return True
    stan = {r["input_frame_id"]: r["asserted_by"] for r in con.execute(
        "SELECT input_frame_id, asserted_by FROM integration_input WHERE integration_id = ?", (glowa["id"],))}
    return (any(z in _ZRODLA_AUTOMATU for z in stan.values())
            or any(stan.get(fid) not in ("harvest", "user") for fid in zbior))


def inputs_of(con, master_frame_id):
    """READ-ONLY „co weszło w ten obraz": wiersze rodowodu stosu ze ścieżką klatki wejściowej
    i źródłem pewności. Materiał pod powierzchnię I-2d i raport CLI — bez zapisu."""
    return con.execute(
        "SELECT ii.input_frame_id AS input_frame_id, ii.asserted_by AS asserted_by, "
        "ii.excluded AS excluded, "
        "(SELECT l.path FROM location l WHERE l.frame_id = ii.input_frame_id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS path "
        "FROM integration_input ii JOIN integration i ON i.id = ii.integration_id "
        "WHERE i.master_frame_id = ? ORDER BY ii.input_frame_id",
        (master_frame_id,)).fetchall()


def release_object_check(con, *, master_sha1_data, object_canon):
    """READ-ONLY: obiekt stosu wobec obiektu WYDANIA, z którego żniwa go wciągnęły (AR-103) → `None`
    (nie ma czego porównać) albo `{verdict, frame_id, stack_object_id, stack_source, stack_cleared_id,
    stack_canon, release_object_id, release_canon}`.

    PO CO: obiekt stosu daje mu po Dostawie nagłówek (`OBJECT` przepisany przez WBPP z lightów)
    - a żniwa wiedzą, dla jakiego obiektu Horreum wydało lighty (manifest wydania). Lighty
    przypisane ręką wbrew nagłówkowi albo nazwa potoczna bez aliasu dają stos z INNYM obiektem
    albo BEZ obiektu, choć rodowód wskazuje lighty wydania. Gospodarz mówi o tym zdaniem
    z gestem; ta funkcja niczego nie zapisuje - cicha podmiana obiektu z nagłówka byłaby
    zamalowaniem faktu z pliku.

    `verdict`: `zgodny` (ten sam obiekt), `inny` (stos ma inny obiekt), `brak` (stos bez obiektu -
    także nagrobek ręki `user_cleared`), `wydanie_poza_baza` (kanonu wydania ta baza nie zna - np.
    karta wydania z innej bazy; porównania nie ma, gestu też nie: `release_object_id` = `None`).
    Porównanie po `object.id` kanonu wydania. `stack_object_id`, `stack_source` i `stack_cleared_id`
    (pamięć nagrobka) to PEŁNY stan, który gest ręki dostaje jako oczekiwany
    (`repo.user_override_object`) - sama para obiekt+źródło przeżywa sekwencję „nagrobek X →
    przypisz Y → zdejmij Y”. `None`: wydanie bez kanonu, klatka stosu nieznana bazie, niebędąca
    stosem, wycofana albo zastąpiona (`retired_at`/`superseded_by` - martwa tożsamość) - gest nie
    miałby celu."""
    if not object_canon:
        return None
    stos = con.execute(
        "SELECT f.id, f.kind, f.retired_at, f.superseded_by, f.object_id, f.object_source, "
        "       f.object_cleared_id, o.canon "
        "FROM frame f LEFT JOIN object o ON o.id = f.object_id WHERE f.sha1_data = ?",
        (master_sha1_data,)).fetchone()
    if (stos is None or stos["kind"] != "master_light" or stos["retired_at"] is not None
            or stos["superseded_by"] is not None):
        return None
    wydanie = con.execute("SELECT id FROM object WHERE canon = ?", (object_canon,)).fetchone()
    if wydanie is None:
        verdict = "wydanie_poza_baza"
    elif stos["object_id"] is None:
        verdict = "brak"
    else:
        verdict = "zgodny" if stos["object_id"] == wydanie["id"] else "inny"
    return {"verdict": verdict, "frame_id": stos["id"], "stack_object_id": stos["object_id"],
            "stack_source": stos["object_source"], "stack_cleared_id": stos["object_cleared_id"],
            "stack_canon": stos["canon"], "release_object_id": None if wydanie is None else wydanie["id"],
            "release_canon": object_canon}

# --- TODO-DŁUG (z kolejki sesji, dieta 2026-08-10; pełne brzmienia: archiwum aa) ---
# TODO-DŁUG(AR-112): reszta E4-9 po dopasowaniu PO NAZWIE i werdykcie „N z M” (D-1011-4).
#   Stan na kopii pf4 po imporcie aliasów Custos (2026-10-11): `history_mismatch` 26 → 1 - 20 stosów
#   dostaje pełny zbiór z nazw (16 podzbiór okna, 4 poza oknem: 16870 16875 16882 16883 z flagą
#   `outside_window`), 5 bez nazw (16847 16849 16852 16901 16903) dostaje werdykt „plik użył N z M
#   klatek okna” na wierszach `window`; `no_candidates` 16865 i 16895 mają zbiór z nazw poza oknem.
#   OTWARTE: (a) tych 5 stoi na kandydatach okna - KTÓRYCH klatek WBPP nie użył, wie tylko człowiek
#   (werdykt ręki w panelu) albo nazwa z czasu obróbki, której zapis przenosin nie niesie; (b) 5
#   stosów rangi `history` bez nazw (16727-16729, 16878 - podstawa `temp`; 16871 - `count`) dalej
#   stoi na temperaturze z nazwy suba albo na liczniku - przypadku konwencji WBPP (D-1011-3),
#   z podstawą widoczną w panelu; (c) 16860 (`history_mismatch`) i 16862 (`no_candidates`) - wejście
#   `…_0000_…` to bliźniak `…_0000a_…` z kolizji Custos bez drugiego świadka (odcisku, lokacji), więc
#   aliasu nie ma; decyzja ręki w panelu albo świadek spoza zapisu przenosin. Rozluźnienie okna dalej
#   NIE jest naprawą (psułoby 21, żeby łatać 4). Wariant rozwojowy: nazwy z czasu obróbki dla tych
#   12 stosów z innego świadka (kopie robocze WBPP, `.xdrz`/`.xnml` obok stosu) - do sondy, nie do
#   zgadywania.
