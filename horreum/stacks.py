"""RODOWÓD GOTOWYCH STOSÓW — co weszło w ten obraz (segment I-2c, paczka P-I). Siostra `lineage`.

`lineage` (C4) odpowiada „czym skalibrowano tę klatkę", ten moduł — „z czego zrobiono ten stos".
Obie osie łączy kształt (Qt-wolne, zapis wyłącznie przez `repo`, SELECT literałem, idempotencja na
UNIQUE, kubełki „czego nie wiemy"), ale różni je ŹRÓDŁO PEWNOŚCI i to jest sedno projektu:

  * kalibrator wylicza się z PRZEPISU, który obie strony niosą w nagłówku — wynik jest faktem;
  * wejścia stosu wylicza OKNO CZASU mastera, a to jest KANDYDAT, nie fakt. Dowieść go potrafi
    tylko `PixInsight:ProcessingHistory` (zeznanie pliku o samym sobie), i to na mniejszości
    plików. Stąd trójstan `asserted_by` (`history` / `window` / `user`) i strażniki niżej.

DLACZEGO NIE DOPASOWUJEMY PO NAZWACH, skoro historia niesie ścieżki wejść: zmierzone 0/36 —
historia wskazuje dysk roboczy i nazwy WBPP, archiwum trzyma nazwy z akwizycji. Historia służy
więc do WERYFIKACJI zbioru wybranego oknem (`resolve.stack.inputs_contained` porównuje wielozbiór
temperatur z nazw WBPP z temperaturami klatek okna), nie do wskazania klatek.

TRZY STRAŻNIKI — każdy gasi konkretną, ZMIERZONĄ nieprawdę (brief P-I §4.2):
  1. **okno zdegenerowane** (`DATE-END ≈ DATE-OBS + EXPTIME`) → ZERO relacji. 23 z 84 masterów
     starszego rocznika opisuje nagłówkiem JEDNĄ klatkę; bez tego strażnika stos dostałby jeden
     sub i wyglądałby wiarygodnie. Cicha nieprawda jest gorsza niż brak odpowiedzi.
  2. **rozjazd z historią** → ZERO relacji. Gdy plik zeznał, z czego powstał, a okno wybrało inny
     zbiór, to okno się MYLI — a nie historia.
  3. **okna nierozłączne** (43 pary tej samej półki, reprocessingi tej samej nocy) → `ambiguous=1`.
     Relacje zostają, ale most do planera (I-2e) MUSI liczyć taki sub raz.

Czas idzie przez `naming.header_dt` (SPOT parser ISO) — NIGDY po stringu: master zapisuje
`…02.608`, klatka `…02.6075262`, więc porządek leksykalny gubi pierwszy sub okna. Filtr i teleskop
porównujemy po OSIACH, nie po surowych napisach nagłówka: `frame.filter_canon` (resolver, oś
kind-agnostyczna — master dostaje ją tak samo jak light) i `telescope_canonical` (kanon po
scaleniach). Inaczej naprawa `ED`→`ED120R` rozspójniłaby rodowód ze wszystkim, co repo wie.

KROK ZBIORCZY PO `group` I `resolve` — tak jak `lineage` idzie po `calibrate`: dobór stoi na osi
obiektu i osi teleskopu, więc puszczony przed nimi widziałby same `no_object`.

ODCZYT PLIKU: historia mieszka w XML-u nagłówka XISF, którego baza nie lustruje (`cards` niosą
karty FITS, nie własności PixInsighta). Ten moduł czyta ją więc z dysku — READ-ONLY, sam nagłówek
(`scan.read_xisf_meta_full`), bez sekcji danych. Plik nieosiągalny nie jest błędem przebiegu:
stos schodzi wtedy na ścieżkę okna i jest to POLICZONE (`history_unread`), nie przemilczane.
"""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import repo
from .hashing import sha1_of_set
from .naming import header_dt
from .resolve import stack as rstack
from .resolve._coerce import _to_float

# Powody, dla których stos NIE dostaje wejść. Wartości = tokeny CHECK-a migracji 0012 (baza jest
# ostatnią bramką słownika, jak przy `target_plan.status`), proza należy do powierzchni.
REASON_DEGENERATE = "degenerate_window"
REASON_MISMATCH = "history_mismatch"
REASON_NO_OBJECT = "no_object"
REASON_NO_WINDOW = "no_window"
REASON_NO_CANDIDATES = "no_candidates"
REASON_TELESCOPE = "telescope_mismatch"
REASON_OFFSET_UNKNOWN = "offset_unknown"

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
    by_assert: dict = field(default_factory=dict)   # 'history'/'window' -> ile integracji
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
    w jakim zegarze liczy ten master"), więc łączymy je bez rozróżnienia."""
    return con.execute(
        "SELECT f.id AS frame_id, f.object_id AS object_id, f.filter_canon AS filter_canon, "
        "h.raw_json AS raw_json, tc.canon_id AS telescope_id, i.utc_offset_min AS utc_offset_min, "
        "(SELECT l.path FROM location l WHERE l.frame_id = f.id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS path "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN integration i ON i.master_frame_id = f.id "
        "WHERE f.kind = 'master_light' AND f.superseded_by IS NULL ORDER BY f.id").fetchall()


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


def propose_offset_minutes(con, master_frame_id):
    """PROPOZYCJA odniesienia czasu dla stosu — `minuty | None`. Czysty odczyt, zero zapisu.

    Świadkiem jest OKNO MASTERA zestawione z materiałem RAW tego samego obiektu: gdy `mm:ss`
    kandydata zgadza się z `mm:ss` początku okna, a różnią się PEŁNE GODZINY, to nie jest zbieg
    okoliczności, tylko dwa zegary tej samej chwili. ZMIERZONE na kopii żywego archiwum (128 stosów,
    po nadaniu obiektu 7 stosom DSLR): propozycja trafia **7 z 7** — sześć razy `+120` (LMC) i raz
    `+60` (IC443) — przy **ZERO** trafieniach wśród pozostałych 121, czyli reguła nie strzela
    w gałąź, której nie dotyczy. Falsyfikatorem był tu drugi człon, nie pierwszy: propozycja, która
    trafia wszędzie, nie jest świadkiem.

    PROPONUJE, NIE ZAPISUJE — i to jest cała jej rola (lustro szczebla ścieżki S2). Zegar aparatu
    jest faktem o SPRZĘCIE, którego archiwum nie zna z definicji; maszyna umie go tylko obstawić
    z kształtu liczb, więc werdykt zostaje przy człowieku, a zapis przy `repo.set_integration_offset`.

    `None` znaczy „nie mam czym obstawić" — brak okna, brak kandydatów RAW albo podpis niejasny
    (dwie różne różnice godzin wśród kandydatów). Milczenie jest tu uczciwsze niż środek: propozycja
    wzięta z niezgodnych świadków byłaby zgadywaniem podanym jako pomiar."""
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
        if t is None or (t.minute, t.second) != (start.minute, start.second):
            continue
        delta = round((t - start).total_seconds() / 60.0)
        # SUFIT ZEGARÓW ŚWIATA odsiewa świadka z INNEJ DOBY (bramka pakietu, zarzut 7): sama
        # podzielność przez 60 przepuszczała np. 1500 minut, czyli klatkę z następnej nocy
        # o trafionym `mm:ss` — jeden przypadkowy zbieg dawał propozycję fałszywą co do doby.
        if delta % 60 == 0 and abs(delta) <= repo.UTC_OFFSET_MAX_MIN:
            roznice.add(delta)
    return roznice.pop() if len(roznice) == 1 else None


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
    """PROPOZYCJA MATERIAŁU dla stosu bez rodowodu — noce z kandydatami. Czysty odczyt, zero zapisu.

    DLACZEGO ISTNIEJE: dobór automatu pyta o OKNO (`DATE-OBS`…`DATE-END`), a 30 stosów archiwum ma
    okno ZDEGENEROWANE — `DATE-END` opisuje jedną klatkę zamiast serii (pułapka 1, `resolve/stack.py`:
    23 z 84 masterów starszego rocznika). Zepsuty jest KONIEC; początek zostaje początkiem pierwszego
    suba. Propozycja bierze więc tę samą oś co okno, tylko zamiast końca stawia NOC.

    OSIE ZGODNOŚCI TE SAME, CO W DOBORZE, i to jest cały warunek uczciwości tej listy: obiekt,
    filtr, teleskop, próg ekspozycji (`exposure_matches`, D-DR-2). Oś, której master NIE ZNA, nie
    zawęża — dokładnie jak w `_in_window`. Luźniejsza reguła bez tych osi nie byłaby propozycją,
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
    nagłówek tego nie mówi — ale umie pokazać, co tej nocy leżało w archiwum.

    NOC MASTERA WCHODZI ZAWSZE, TAKŻE PUSTA, i to jest odpowiedź na POMIAR, nie ozdoba: 5 stosów
    (`no_candidates`) nie ma materiału w swojej nocy, choć obiekt ma go setki w innych nocach
    (NGC3034: 356 lightów w 11 nocach, NGC7635: 339 w 10). Lista bez pustej nocy mastera kazałaby
    człowiekowi zgadywać, czy program w ogóle zrozumiał, o który wieczór pyta.

    KOLEJNOŚĆ = ODLEGŁOŚĆ OD NOCY MASTERA, nie chronologia: sesja przesunięta o dzień jest
    kandydatem znacznie mocniejszym niż ta sprzed roku, a pierwsze pozycje listy czyta się najuważniej.

    KLATKA JUŻ OSĄDZONA NIE WRACA jako propozycja — ani potwierdzona, ani odrzucona. Werdykt
    „to NIE jest materiał tego obrazu" ma zostać werdyktem; lista, która go co chwilę przywraca,
    kazałaby wydawać go w kółko.

    KANDYDAT RAW PRZY NIEZNANYM ODNIESIENIU NIE WCHODZI I NIE PRZEPADA PO CICHU — granica
    przeniesiona z `_in_window` RAZEM Z JEJ DRUGĄ POŁOWĄ (EXIF niesie czas LOKALNY, XISF UTC).
    Bez odniesienia nie da się powiedzieć, do której NOCY taka klatka należy, więc do listy nie
    wchodzi — ale wraca DRUGĄ WARTOŚCIĄ ZWROTU, bo „kandydaci są, tylko liczą w innym zegarze"
    to inna recepta niż „kandydatów nie ma". Bramka pakietu 3a (0808) zmierzyła, ile kosztowało
    przepisanie samego pominięcia bez tej wartości: **6 z 35** obrazów kubełka (6× LMC, po 36
    kandydatów przechodzących KAŻDĄ oś) dostawało pustą listę pod zdaniem „archiwum nie ma ani
    jednej klatki tego obiektu" — twierdzeniem FAŁSZYWYM — a gest odniesienia był dla nich
    strukturalnie nieosiągalny, bo `_plan` kończy na `degenerate_window` PRZED `_in_window`,
    więc powodu `offset_unknown` te stosy nie dostaną nigdy.

    PASMO ±SUFIT Z `_in_window` TU NIE OBOWIĄZUJE — świadomie, nie przez pominięcie. Tam licznik
    pilnował WĄSKIEGO okna (minuty), więc RAW z innej nocy trzeba było odsiać, żeby recepta nie
    wysyłała człowieka do gestu bez prawa zadziałania. Tu pula jest już przycięta obiektem,
    filtrem, teleskopem i progiem ekspozycji, a powierzchnia oddaje WSZYSTKIE noce do wyboru —
    więc każdy taki kandydat realnie pojawi się na liście po wskazaniu odniesienia. Zmierzone:
    wskazanie propozycji rdzenia (`+120`) daje 0 → 36 klatek, sześć razy na sześć.

    Zwraca `(tuple[CandidateNight, …], raw_bez_odniesienia)`; pusta krotka = nie ma czego
    proponować (brak obiektu, brak czasu ekspozycji albo brak `DATE-OBS` — zmierzone: 1 stos z 35)."""
    row = con.execute(
        "SELECT f.id AS frame_id, f.object_id, f.filter_canon, h.raw_json, "
        "       tc.canon_id AS telescope_id, i.id AS integration_id, i.utc_offset_min "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id "
        "LEFT JOIN telescope_canonical tc ON tc.id = c.telescope_id "
        "LEFT JOIN integration i ON i.master_frame_id = f.id "
        "WHERE f.id = ?", (master_frame_id,)).fetchone()
    if row is None or row["object_id"] is None:
        return (), 0
    t = rstack.read_testimony(json.loads(row["raw_json"]) if row["raw_json"] else {}, None)
    exptime = _to_float(t.exptime)
    start = t.window_start
    if start is None or not exptime:
        return (), 0
    osadzone = {int(r[0]) for r in con.execute(
        "SELECT input_frame_id FROM integration_input WHERE integration_id = ?",
        (row["integration_id"],)).fetchall()} if row["integration_id"] else set()
    noc_mastera = _night_key(start)
    wg_nocy = {}
    raw_bez_odniesienia = 0
    for r in _window_candidates(con, object_id=row["object_id"], exptime=exptime):
        if r["frame_id"] in osadzone:
            continue
        if not exposure_matches(r["exptime"], exptime):
            continue                       # SQL dał NADZBIÓR (pas ± sufit) — próg rozstrzyga tu
        if row["filter_canon"] and r["filter_canon"] != row["filter_canon"]:
            continue
        # TELESKOP NIE ODSIEWA TU - rozstrzyga go reguła niżej, po podziale na noce (B3a-2).
        obcy = row["telescope_id"] is not None and r["telescope_id"] != row["telescope_id"]
        czas = header_dt(r["date_obs"])
        if czas is None:
            continue
        if r["filetype"] == "raw":
            # `is None` WYSTARCZA I NIE POTRZEBUJE DRUGIEJ OCHRONY. `integration.utc_offset_min`
            # jest kolumną INTEGER (0016), a jej jedyny pisarz `repo.set_integration_offset`
            # odrzuca wszystko poza `int`/`None` — token `offset_unknown` mieszka w CHECK-u
            # SĄSIEDNIEJ kolumny `unresolved_reason` i tutaj nie ma jak trafić. Pin imienny, bo
            # bramka pakietu 3a (0808) dostała ten sam fałszywy zarzut od DWÓCH silników naraz:
            # oba czytały nazwę tokenu jako wartość offsetu i proponowały strażnika na stan
            # nieosiągalny (lustro pinu przy `exptime is None` w `_window_candidates`).
            if row["utc_offset_min"] is None:
                if not obcy:                  # licznik odsiewa teleskop per klatkę - granica wyżej
                    raw_bez_odniesienia += 1  # NIE `continue` po cichu - patrz docstring
                continue
            czas -= timedelta(minutes=row["utc_offset_min"])
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
    ), raw_bez_odniesienia


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
    """Tekst XML nagłówka XISF spod ścieżki — READ-ONLY, sam nagłówek. Import lokalny, bo `scan`
    ciągnie astropy, a ten moduł bywa wołany tam, gdzie ładowanie astropy jest zbędne.

    Format INNY niż XISF oddaje `None`, a nie wyjątek: historia PixInsighta jest własnością XISF-a
    i jej brak w FITS-ie nie jest awarią odczytu. Bez tego rozdziału stos zapisany jako FITS
    wpadłby do licznika „historia nieodczytana" i kłamał o dostępności pliku (dziś zmierzone
    128/128 stosów to `.xisf`, ale licznik ma mierzyć to, co mierzy)."""
    from .scan import XISF_SUFFIXES, read_xisf_meta_full
    if not str(path).lower().endswith(XISF_SUFFIXES):
        return None
    return read_xisf_meta_full(path).xml_bytes.decode("utf-8", "replace")


def _plan(con, row, *, xml_reader):
    """Materiał decyzji dla JEDNEJ klatki stosu — bez zapisu (czysta faza, testowalna osobno)."""
    header = json.loads(row["raw_json"]) if row["raw_json"] else {}
    xml, unread, brak_lokacji = None, False, False
    if row["path"]:
        try:
            xml = xml_reader(row["path"])
        except Exception:              # plik zniknął/leży na odłączonym dysku — patrz docstring
            unread = True
    else:
        # BRAK OBECNEJ LOKACJI TO TEN SAM STAN dla strażnika, co błąd odczytu: pliku nie ma pod
        # ręką, więc jego zeznania NIE ZNAMY. Dla POWIERZCHNI to jednak dwie różne rzeczy i dwie
        # różne recepty — „podłącz archiwum" jest nieprawdą dla stosu, którego w bibliotece nie ma
        # (skasowany plik roboczy WBPP, stos przeniesiony). Stąd drugi licznik: jeden fakt
        # dla decyzji, dwa dla człowieka.
        unread = brak_lokacji = True
    t = rstack.read_testimony(header, xml)
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
    }
    if row["object_id"] is None:
        plan["reason"] = REASON_NO_OBJECT
        return plan
    if start is None or end is None or t.degenerate:
        # Okno bez końca i okno o długości jednej klatki to ten sam brak: nie ma czym wybierać.
        plan["reason"] = REASON_NO_WINDOW if start is None or end is None else REASON_DEGENERATE
        return plan
    # GUARD ZEZNANIA (R3) STOI WYŻEJ I TO JEST SPRAWDZONE, NIE ZAŁOŻONE: master bez `EXPTIME` nie
    # dochodzi tu wcale, bo `testimony.degenerate` jest wtedy `True` z definicji („brak czasu
    # ekspozycji też jest True — nie mamy wtedy czym ograniczyć doboru", `resolve/stack.py`), więc
    # plan kończy się na `degenerate_window` linijkę wyżej. Własny guard na `exptime is None` był
    # tu przez chwilę i został ZDJĘTY jako martwy — pas nadzbioru wokół `None` nigdy nie powstaje,
    # a kod na nieosiągalny stan udaje ochronę, której nikt nie testuje. Pinuje to test imienny
    # `test_master_bez_ekspozycji_konczy_na_oknie_zdegenerowanym`.
    kand, rozjazd, raw_bez_odniesienia = _in_window(
        _window_candidates(con, object_id=row["object_id"], exptime=exptime),
        start=start, end=end, filter_canon=row["filter_canon"], telescope_id=row["telescope_id"],
        exptime=exptime, utc_offset_min=row["utc_offset_min"])
    plan["telescope_mismatch"] = rozjazd
    # UWAGA OBOK WERDYKTU (G2-1d): RAW-y, których nie da się umieścić w czasie, mówią ZAWSZE -
    # także gdy rodowód domknął się z innego materiału albo werdykt brzmi inaczej. Jedyny wyjątek
    # to werdykt `offset_unknown`, który mówi dokładnie to samo (niżej; CHECK 0020 pilnuje).
    # Zero znaczy „brak uwagi", więc idzie jako NULL - stan bez uwagi ma jedną postać.
    plan["raw_unreferenced"] = raw_bez_odniesienia or None
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
    ok, _poza, _nadwyzka = rstack.inputs_contained(t, [r["ccd_temp"] for r in kand])
    if not ok:
        plan["reason"] = REASON_MISMATCH        # strażnik 2: myli się OKNO, nie zeznanie pliku
        return plan
    plan["inputs"], plan["asserted_by"] = kand, "history"
    return plan


def run_stack_lineage(con, *, now, actor="stacks", xml_reader=None, progress=None):
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
    podają zeznanie wprost, produkcja czyta nagłówek z dysku."""
    s = StackLineageSummary()
    reader = xml_reader if xml_reader is not None else _read_history_xml
    rows = _masters(con)
    s.stacks = len(rows)
    plany = []
    for i, row in enumerate(rows, 1):
        plany.append(_plan(con, row, xml_reader=reader))
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
        if p["history_unread"] and stan is not None:
            tool_v, rows_v = stan["tool"], stan["declared_rows"]
            driz_v, dis_v = stan["drizzle_inputs"], stan["disabled_inputs"]
        else:
            tool_v, rows_v = t.tool, t.rows
            driz_v = sum(1 for x in t.inputs if x.has_drizzle) if t.rows is not None else None
            dis_v = sum(1 for x in t.inputs if not x.enabled) if t.rows is not None else None
        odcisk = stan["integ_hash"] if chroniony else _fingerprint(con, wejscia)
        iid, _ = repo.upsert_integration(
            con, master_frame_id=p["frame_id"], integ_hash=odcisk, tool=tool_v,
            window_start=p["start"].isoformat() if p["start"] else None,
            window_end=p["end"].isoformat() if p["end"] else None,
            declared_rows=rows_v, drizzle_inputs=driz_v, disabled_inputs=dis_v,
            degenerate=int(t.degenerate), ambiguous=int(p["frame_id"] in ambi),
            telescope_mismatch=int(p["telescope_mismatch"]),
            unresolved_reason=p["reason"], raw_unreferenced=p["raw_unreferenced"],
            now=now, actor=actor)
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
        "       i.ambiguous, i.telescope_mismatch "
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

# --- TODO-DŁUG (z kolejki sesji, dieta 2026-08-10; pełne brzmienia: archiwum aa) ---
# TODO-DŁUG(E4-9): 26 stosów history_mismatch (0810). Dawna teza „wejść nie ma w archiwum" jest
#   OBALONA pomiarem niżej - rozjazd bierze się z okna doboru (przeważnie ZA SZEROKIEGO), nie
#   z braku materiału. NIE gasić rozluźnieniem okna; kierunek naprawy czeka na decyzję Zdzinia.
#   POMIAR 2026-09-26 (pf4 read-only, historia 26 plików z R:, 1559 nazw wejść): wynik >0, a TEZA
#   UPADA W OBU CZŁONACH. (a) Nazwa: 12/1559 ma odpowiednik w `location` co do rdzenia nazwy -
#   wszystkie z JEDNEGO stosu (NGC5907 Ha 300s, 12/12; historia niesie tam nazwy archiwum).
#   (b) Pokrycie: 1402/1402 nazw z temperaturą ma odpowiednik w puli obiektu (obiekt+filtr+
#   ekspozycja+teleskop, każda noc) - wejścia LEŻĄ w archiwum; licznością pula pokrywa 1558/1559.
#   (c) Kierunek rozjazdu: 21/26 okno za SZEROKIE (deklarowany zbiór mieści się w oknie, nadwyżka
#   1..34 klatek - WBPP użył podzbioru; okno 1670 wobec 1559 deklarowanych), 4/26 za wąskie
#   (IC405 SII, IC5070 OIII, NGC2237 OIII/SII: 4/5/6/6 wejść poza oknem, obecne w puli), 1/26
#   zgodne z tezą (IC405 Ha 600s: 3 deklarowane, w puli archiwum 2). Rozluźnienie okna dalej NIE
#   jest naprawą - psułoby 21 stosów, żeby łatać 4. Temperatura to słaby świadek (635/1559 nazw
#   ma -10,00), więc (b) to zgodność wielozbioru, nie tożsamość klatki. Wariant rozwojowy do
#   rozstrzygnięcia: dopasowanie PO NAZWIE tam, gdzie historia niesie nazwy archiwum (NGC5907:
#   12 wejść `history` z dowodem), i test PODZBIORU dla okna szerszego od zeznania.
