"""Krok ZBIORCZY po skanie — grouper teleskopów + config (po przejściu fitsmirror, brief §3).

Po naprawie nagłówków u źródła (TELESCOP 100%, 8 nazw × dokładnie 1 ogniskowa) oś TELESKOP
czyta się WPROST z nagłówka: tożsamość = `telescop_canon` = TELESCOP.strip(). Klastrowanie
sygnatur (FOCRATIO/FOCALLEN) było obejściem brudnych nagłówków — MARTWE (zastąpiony
PLAN_osie_korekta.md). Czyta przez SELECT (meta-test AST dopuszcza SELECT poza repo), wyłania
teleskopy/configi i linkuje `frame.config_id` — WSZYSTKIE zapisy idą przez `repo` (jedna klinga);
ten moduł nie wykonuje żadnego DML.

JEDEN mechanizm foldowania (R2#8): grouper grupuje po `strip()` BEZ foldowania wielkości liter
w Pythonie — tożsamość rozstrzyga WYŁĄCZNIE SELECT w `repo.propose_telescope` po kolumnie
`UNIQUE COLLATE NOCASE` (warianty 'RC8'/'rc8' trafiają w ten sam wiersz).

KIND-AWARENESS OSI TELESKOPU (decyzja Zdzinia 2026-07-22, wariant B): dark i bias powstają przy
ZAMKNIĘTEJ migawce — opisuje je kamera + czas + temperatura + wzmocnienie + binning, NIGDY optyka.
TELESCOP w takim nagłówku to ślad sesji akwizycji, nie fakt o klatce, więc nie wnosi zeznania na oś
i nie buduje configu; brak TELESCOP w darku NIE jest deltą do przeglądu. Flat ZOSTAJE na osi —
zależy od optyki i filtra realnie (potwierdzone: 73/73 masterflatów i 2256/2256 flatów ma TELESCOP).
Pliki na dysku pozostają NIETKNIĘTE — to model przestaje czytać pole, które dla darka nic nie znaczy
(wariant A = kasowanie kart writebackiem — odrzucony).

JEDEN WYJĄTEK OD „tożsamość = TELESCOP.strip()" - RAW (D-OW-3/R1): nazwa z EXIF-u jest nazwą
OBIEKTYWU, a nazwa zastępcza adaptera obejmuje kilka szkieł. Gdy klatki RAW jednej nazwy zeznają
co najmniej dwie ogniskowe, oś rozdziela się po `FOCALLEN` (`_soczewki_raw`); teleskop o tej
nazwie zostaje przy ogniskowej, którą już deklaruje. „8 nazw × 1 ogniskowa" dotyczy lightów
i flatów FITS - gotowe obrazy niosą ogniskową z rozwiązania astrometrycznego i dlatego FITS/XISF
rozdziałowi nie podlegają.

TELESKOP = FIZYCZNY TELESKOP Z OGNISKOWĄ, POTWIERDZONY RĘKĄ (D-1012-2): przebieg nigdy nie zakłada
teleskopu po ogniskowej FITS/XISF. Klatka, której ogniskowa odbiega od teleskopu o więcej niż
`OPTICS_TOLERANCE`, czeka w kubełku Porządków na wybór ręki z listy teleskopów mieszczących się w tej
tolerancji albo na „Dopisz nowy…". Wartość osi „z plików" to MODA zeznań (`optics_from_files`),
odświeżana przy każdej Dostawie; wartość ręki (`telescope.*_user`) wygrywa przy odczycie.
"""
from __future__ import annotations       # `int | None` w ciele dataclassy (lustro `sky.py`)

import json
from dataclasses import dataclass

from . import repo
from .calibration import KIND_RECIPE

# Rodzaje BEZ osi teleskopu (kind-scoping config — zob. nagłówek). `resolver.review_state` konsumuje
# tę samą stałą, żeby kolejka przeglądu nie rozjechała się z osią.
#
# WYPROWADZONA z `calibration.KIND_RECIPE` (SPOT, C2), nie wypisana ręcznie: „ten rodzaj ma przepis"
# i „ten rodzaj jest na osi teleskopu" to dwa fakty o TEJ SAMEJ populacji, więc mają jednego
# właściciela. Dwie osobne listy rozjechałyby się przy pierwszym nowym rodzaju (dark-flaty z briefu
# C0 §8): trafiłby do przepisów, a w osi teleskopu zostałby pominięty i zaczął budować configi pod
# cudzą optyką. Wartość dziś == dawny literał {dark, bias, master_dark, master_bias} (test pinuje).
NO_TELESCOPE_KINDS = frozenset(k for k, (_cls, on_axis) in KIND_RECIPE.items() if not on_axis)

# OPTYKA Z PLIKÓW (AR-128, D-1012-2). Trzy przełączniki decyzji właściciela, każdy w JEDNYM miejscu:
#
# `OPTICS_EVIDENCE_KINDS` - kto ZEZNAJE o optyce teleskopu, w kolejności pierwszeństwa: głosuje przy
# wartości z plików (`optics_from_files`) i trafia do kubełka „ogniskowa niezgodna z teleskopem"
# (`resolver.optics_mismatch_frame_ids`; kubełek f/ bierze same lighty). Stosy (`master_light`)
# i mastery flatów są POZA (D-1012-2 `Q15`): ogniskową stosu zapisuje program obróbki, wyliczając ją
# z rozwiązania astrometrycznego i SWOJEGO wpisu rozmiaru piksela - a fałszywy bywa właśnie ten wpis
# (obiektyw 105 mm: XPIXSZ 5,4 zamiast 4,62 µm daje 122 mm), podobnie po drizzlu i przy złożeniu
# zdrizzlowanych masterów. Każdy z 11 rozjazdów stosu na archiwum (> 5 %) to taki wpis, nie inny
# sprzęt. Dopisanie `master_light` włączyłoby stosy.
OPTICS_EVIDENCE_KINDS = ("light", "flat")
# `OPTICS_TOLERANCE` - względna różnica ogniskowej albo f/, od której klatka „nie zgadza się
# z teleskopem" i od której teleskop mieści się na liście wyboru (D-1012-2 `Q8`: 5 %). Zmierzony szum
# tej samej optyki w plikach: ≤ 1,3 % (master flaty A140R 794 przy 784).
OPTICS_TOLERANCE = 0.05
# `RAW_LENS_SPLIT` - wyjątek od zasady „program nigdy nie rozdziela teleskopu sam" (D-1012-2 `Q8`):
# nazwa zastępcza adaptera RAW (`DT 0mm F0 SAM`) dzieli się po ogniskowej z EXIF-u (`_soczewki_raw`).
# Decyzja właściciela `Q14` (D-1012-2): zostaje - etykiety obiektywów nada sam; `False` wyłącza rozdział, a zdjęcia o ogniskowej
# odległej od teleskopu trafiają wtedy do kubełka i okna wyboru jak każde inne.
RAW_LENS_SPLIT = True


@dataclass
class GroupSummary:
    """Zliczenia jednego przebiegu `run_grouper` — do firsthand-weryfikacji (nowy kształt R1#2:
    giną focratio_* i telescopes_suspect, dochodzi telescop_missing)."""
    headers: int = 0
    telescopes_proposed: int = 0
    telescop_missing: int = 0      # klatki z nagłówkiem BEZ TELESCOP (→ config.review, stan)
    configs_proposed: int = 0
    configs_assigned: int = 0
    config_review: int = 0
    calibration_off_axis: int = 0  # dark/bias pominięte na osi teleskopu (kind-scoping, NIE review)
    configs_unassigned: int = 0    # stęchłe przypisania kalibracji zdjęte (dane sprzed kind-scopingu)
    config_by_hand: int = 0        # zestaw wskazany RĘKĄ — przebieg go mija (R1b, NIE review)
    configs_by_twin: int = 0       # wariant kadru bez TELESCOP z zestawem ORYGINAŁU (AR-54)
    optics_refreshed: int = 0      # teleskopy, którym zmieniła się wartość z plików (AR-128)
    variants: object = None        # relacje wariantu z zeznań (`stack_variants.LinkSummary`)


@dataclass(frozen=True)
class FilesOptics:
    """Wartość Z PLIKÓW jednego teleskopu (`optics_from_files`) - moda zeznań z liczbą klatek, które
    ją niosą. `None` = żadna klatka nie zeznała; `lights_without_focal` = lighty bez FOCALLEN."""
    focal: int | None = None
    focal_n: int = 0
    f_ratio: float | None = None
    f_ratio_n: int = 0
    lights: int = 0
    lights_without_focal: int = 0


def _moda(licznik):
    """Moda z remisem rozstrzyganym na rzecz WIĘKSZEJ wartości (jak `sky._rig_from_rows`) - wynik
    nie zależy od kolejności wierszy."""
    return max(sorted(licznik, reverse=True), key=lambda k: licznik[k])


def _optics(rows):
    """Wiersze `(kind, focallen, focratio_raw, reka)` → `FilesOptics`, osobno dla każdego pola:
    moda lightów z zestawem AUTOMATU, bez nich - lightów przypiętych RĘKĄ, potem tak samo flaty
    (kolejność `OPTICS_EVIDENCE_KINDS`).

    DLACZEGO RĘKA NA KOŃCU (bramka kodu T24, N2): odświeżenie idzie teraz za każdym przepięciem klatek,
    a klatka przypięta ręką niesie w pliku ogniskową STAREGO teleskopu (5 klatek RC8 1600 przypiętych
    do A140R 784 przegłosowałoby jego 3 klatki i planer liczyłby kadr z 1600). Teleskop, który ma
    WYŁĄCZNIE klatki ręki (świeżo dopisany), bierze modę z nich - innego świadka nie ma."""
    kolejnosc = [(k, reka) for k in OPTICS_EVIDENCE_KINDS for reka in (False, True)]
    ogn = {k: {} for k in kolejnosc}
    f = {k: {} for k in kolejnosc}
    lights = bez = 0
    for kind, fl, fr, reka in rows:
        klucz = (kind, bool(reka))
        if kind == "light":
            lights += 1
            bez += fl is None
        if fl is not None:
            v = int(round(fl))
            ogn[klucz][v] = ogn[klucz].get(v, 0) + 1
        if fr is not None:
            f[klucz][float(fr)] = f[klucz].get(float(fr), 0) + 1
    wynik = {"lights": lights, "lights_without_focal": bez}
    for pole, liczniki in (("focal", ogn), ("f_ratio", f)):
        for klucz in kolejnosc:
            if liczniki[klucz]:
                m = _moda(liczniki[klucz])
                wynik[pole], wynik[f"{pole}_n"] = m, liczniki[klucz][m]
                break
    return FilesOptics(**wynik)


def optics_from_files(con, telescope_id=None):
    """JEDYNA derywacja wartości Z PLIKÓW (AR-128, bramka planu T24 zarzut 3) - `FilesOptics` jednego
    teleskopu, a bez `telescope_id` słownik `{id korzenia: FilesOptics}` dla wszystkich kanonicznych.

    Populacja = AKTYWNE klatki (`superseded_by`/`retired_at` NULL; klatka bez obecnej kopii głosuje -
    zeznanie nagłówka zostaje prawdziwe) rodzajów `OPTICS_EVIDENCE_KINDS` z zestawów KORZENIA
    i jego członków scalenia (`telescope_canonical`) - czyli po przypisaniach, także ręcznych (te
    głosują na końcu, `_optics`). Głos mają więc klatki, które oś przypisuje temu teleskopowi, nie te,
    które niosą jego nazwę w pliku. Konsumenci: Dostawa (`run_grouper`), krok pomigracyjny 0039,
    gesty przypięcia (`refresh_all_optics`), Oś teleskopu (tooltip „pliki: …"), strażnik gestu
    „Popraw f/", przez kolumnę automatu - planer i kubełki. Read-only, SELECT literałem."""
    kinds = json.dumps(list(OPTICS_EVIDENCE_KINDS))
    if telescope_id is not None:
        rows = con.execute(
            "SELECT f.kind, h.focallen, h.focratio_raw, f.config_source IS NOT NULL "
            "FROM telescope_canonical tc "
            "JOIN config c ON c.telescope_id = tc.id JOIN frame f ON f.config_id = c.id "
            "JOIN header h ON h.frame_id = f.id "
            "WHERE tc.canon_id = ? AND f.superseded_by IS NULL AND f.retired_at IS NULL "
            "AND f.kind IN (SELECT value FROM json_each(?))", (telescope_id, kinds)).fetchall()
        return _optics([tuple(r) for r in rows])
    rows = con.execute(
        "SELECT tc.canon_id, f.kind, h.focallen, h.focratio_raw, f.config_source IS NOT NULL "
        "FROM telescope_canonical tc "
        "JOIN config c ON c.telescope_id = tc.id JOIN frame f ON f.config_id = c.id "
        "JOIN header h ON h.frame_id = f.id "
        "WHERE f.superseded_by IS NULL AND f.retired_at IS NULL "
        "AND f.kind IN (SELECT value FROM json_each(?))", (kinds,)).fetchall()
    per = {}
    for r in rows:
        per.setdefault(r[0], []).append((r[1], r[2], r[3], r[4]))
    return {tid: _optics(w) for tid, w in per.items()}


# Kanon teleskopu wydzielonego z nazwy RAW po ogniskowej. Nazwa bazowa zostaje na czele, żeby
# lista osi sortowała soczewki jednego korpusu obok siebie, a ogniskowa stoi w jednostce - to
# etykieta dla człowieka, póki nie nada własnej (`telescope.label`).
_SOCZEWKA = "{canon} @ {focal}mm"


def _soczewki_raw(con, canon, members):
    """Grupa jednej nazwy `TELESCOP` → `{kanon osi: członkowie}`; bez rozdziału `{canon: members}`.

    POWÓD (D-OW-3/R1): w RAW-ie `TELESCOP` to nazwa OBIEKTYWU z EXIF-u (E3-3), a obiektyw na
    adapterze zeznaje nazwę zastępczą (`DT 0mm F0 SAM` = „nieznane szkło przez przejściówkę") dla
    KAŻDEGO szkła, które się pod nią podepnie. Na żywej `pf4` ta jedna nazwa niosła 50, 70 i 188 mm,
    a teleskop mówił „50" o wszystkich 22 klatkach - kadr 70 mm był nieodróżnialny od 50 mm, choć
    to właśnie kadr odróżnia pas od miecza Oriona. Świadkiem jest `FOCALLEN` z EXIF-u: fakt
    per ujęcie, zapisany przez korpus, nie przez człowieka.

    WĄSKO, trzema warunkami naraz - każdy chroni oś, która dziś jest jednoznaczna:
      * tylko `filetype='raw'`. W FITS/XISF `FOCALLEN` gotowego obrazu bywa WYNIKIEM rozwiązania
        astrometrycznego (A140R zeznaje 66 różnych wartości 784-794 mm), więc rozdział po nim
        rozbiłby jeden tubus na dziesiątki osi. Nazwę FITS nadaje człowiek, a naprawia writeback;
      * tylko nazwa z CO NAJMNIEJ DWIEMA ogniskowymi RAW (zaokrąglonymi do mm). Nazwa o jednej
        ogniskowej - także zoom, dziś zawsze na jednej pozycji - zachowuje kanon, id i wszystko,
        co do niego przypięto. Rozdział zależy od danych, nie od wzorca nazwy: zoom zrobiony na
        dwóch ogniskowych kłamie o kadrze tak samo jak nazwa zastępcza;
      * KOTWICA zostaje na miejscu: ogniskowa, którą teleskop o tej nazwie już deklaruje
        (`focal_nominal`), trzyma gołą nazwę, więc istniejący wiersz zachowuje id, etykietę, park,
        scalenie i configi swoich klatek - wychodzą wyłącznie klatki, o których kłamał. Dla nazwy
        jeszcze nieznanej kotwicą jest ogniskowa, którą `propose_telescope` i tak by zapisał.

    Klatka RAW BEZ `FOCALLEN` i każda klatka FITS/XISF zostają przy gołej nazwie - świadka
    ogniskowej nie ma, a zgadywanie z segmentu folderu (`A7S1_070`) byłoby konwencją jednego
    archiwum udającą fakt (na `pf4` taka klatka i tak nie istnieje). Ręka: klatki ze zestawem
    wskazanym ręką liczą się tu jak inne, bo faza 1 opisuje NAGŁÓWKI, ale faza 2 je mija (R1b) -
    rozdział nie przepina ich nigdy."""
    def mm(m):
        return int(round(m["fl"])) if m["ft"] == "raw" and m["fl"] is not None else None

    ogniskowe = {mm(m) for m in members} - {None}
    if len(ogniskowe) < 2:
        return {canon: members}
    row = con.execute(
        "SELECT t.id, t.focal_nominal, t.merged_into FROM telescope t WHERE t.telescop_canon = ?",
        (canon,)).fetchone()
    # SCALENIE TO FAKT RĘKI: człowiek orzekł, że ta nazwa to ten sam sprzęt co inny teleskop (albo
    # wciągnął pod nią inne nazwy). Automat nie wie, której ogniskowej to orzeczenie dotyczyło, więc
    # nie wyprowadza klatek spod scalenia - nazwa zostaje w całości, aż ręka ją rozscali.
    if row is not None and (row["merged_into"] is not None or con.execute(
            "SELECT 1 FROM telescope WHERE merged_into = ? LIMIT 1", (row["id"],)).fetchone()):
        return {canon: members}
    pierwsza = next((m["fl"] for m in members if m["fl"] is not None), None)
    kandydaci = (row["focal_nominal"] if row is not None else None,
                 int(round(pierwsza)) if pierwsza is not None else None)
    kotwica = next((f for f in kandydaci if f in ogniskowe), min(ogniskowe))
    out = {canon: []}
    for m in members:
        f = mm(m)
        klucz = canon if f is None or f == kotwica else _SOCZEWKA.format(canon=canon, focal=f)
        out.setdefault(klucz, []).append(m)
    return out


def run_grouper(con, now):
    """Po skanie: (1) wyłoń teleskopy z DISTINCT `TELESCOP.strip()` (RAW o kilku ogniskowych -
    per ogniskowa, `_soczewki_raw`); (2) config iloczyn
    (telescope×camera) + link `frame.config_id`. Brak/pusty TELESCOP lub brak kamery →
    `config.review` (W4, zero cichego NULL; kolejka ze STANU `config_id IS NULL`). Zwraca
    `GroupSummary`. Idempotentny (propose_* i assign_config sprawdzają stan przed zapisem).

    `NO_TELESCOPE_KINDS` (dark/bias) omija OBIE fazy: nie wnosi zeznania na oś teleskopu i nie
    trafia do configu ani do `config.review` — jego `config_id IS NULL` to POPRAWNY STAN, nie delta
    (jak `object_id NULL` dla kalibracji w resolverze). Dane sprzed kind-scopingu mają takie klatki
    PRZYPISANE do cudzego configu, więc przebieg je AKTYWNIE ODPINA (`repo.unassign_config`) —
    grouper sam się leczy, a oś teleskopu przestaje liczyć darki pod cudzą optyką.

    `STICKY_CONFIG_SOURCES` (R1b) omija FAZĘ 2: zestaw wskazany ręką jest faktem, którego przebieg
    nie ma prawa ani nadpisać, ani zgłosić do przeglądu. Faza 1 zostaje nietknięta — teleskopy
    wyłaniają się z NAGŁÓWKÓW niezależnie od tego, komu ręka co przypisała, i cofnięcie tego
    byłoby zmianą osi teleskopu przy okazji zmiany osi sprzętu.

    FAZA 0 - RELACJE WARIANTU KADRU (AR-54) z zeznań leżących obok kopii w `STACKS`
    (`stack_variants.link_from_testimonies`). Stoi TUTAJ, bo grouper jest pierwszym etapem pochodnych
    po skanie: relacja ma istnieć, zanim przebieg sprzętu i resolver zapytają o oryginał wariantu.
    Czyta wyłącznie kolejkę zeznań w bazie (`stack_variant_testimony`) - udziału nie dotyka.

    ZESTAW BLIŹNIAKA (AR-54): wariant bez `TELESCOP` z relacją `stack_variant` bierze config
    ORYGINAŁU - automat (`config_source` NULL), więc ręka i nagłówek dalej wygrywają (wariant
    z własnym `TELESCOP` idzie zwykłą drogą). Warunek inwariantu: ta sama kamera co config oryginału
    (`config.camera_id == frame.camera_id`), inaczej przegląd jak dotąd, a zestaw przejęty wcześniej
    od oryginału schodzi (`repo.unassign_config`, wyłącznie automat). Warianty idą na KONIEC
    fazy 2, a config oryginału czytamy w chwili wariantu - oryginał przypisany w tym samym przebiegu
    jest już widoczny.

    KROK (3) - WARTOŚĆ Z PLIKÓW (AR-128): po fazie 2 każdy kanoniczny teleskop dostaje modę zeznań
    klatek, które oś mu przypisała (`optics_from_files`, `repo.refresh_telescope_optics`); dawniej
    zostawała na zawsze wartość PIERWSZEJ klatki grupy. Teleskopu po ogniskowej FITS/XISF przebieg
    NIE zakłada (D-1012-2) - klatka o obcej ogniskowej idzie do kubełka i wyboru ręki."""
    from . import stack_variants              # leniwie: plan wersji ciągnie projekcję i skan
    s = GroupSummary()
    s.variants = stack_variants.link_from_testimonies(con, now)

    rows = con.execute(
        "SELECT f.id AS fid, f.camera_id AS cam, f.kind AS kind, f.config_id AS cfg, "
        "       f.config_source AS cfg_src, f.filetype AS ft, "
        "       h.telescop AS tel, h.focallen AS fl, h.focratio_raw AS fr "
        "FROM frame f JOIN header h ON h.frame_id = f.id").fetchall()
    s.headers = len(rows)
    oryginaly = {r["variant_frame_id"]: r["original_frame_id"] for r in con.execute(
        "SELECT variant_frame_id, original_frame_id FROM stack_variant").fetchall()}

    # (1) grupy po strip() - f/ i ogniskowa to nullable właściwości, nie klucz (brief §3); wartość
    # z plików liczy krok (3). Kalibracja bez teleskopu NIE zeznaje: dark z 'ED' w nagłówku nie powołuje teleskopu do życia.
    groups = {}
    for r in rows:
        if r["kind"] in NO_TELESCOPE_KINDS:
            continue
        canon = (r["tel"] or "").strip()
        if canon:
            groups.setdefault(canon, []).append(r)

    # (1a) ROZDZIAŁ SOCZEWEK RAW - nazwa z EXIF-u, pod którą lustrzanka zeznała kilka ogniskowych,
    # rozpada się na teleskop per ogniskowa (`_soczewki_raw`). Pozostałe grupy przechodzą 1:1.
    # Kanon syntetyczny może zderzyć się z dosłownym `TELESCOP` innej grupy (FITS zeznający
    # `X @ 70mm`) - to ta sama oś, więc listy się ŁĄCZĄ; nadpisanie zgubiłoby klatki grupy.
    split = {}
    for canon, members in groups.items():
        podzial = _soczewki_raw(con, canon, members) if RAW_LENS_SPLIT else {canon: members}
        for klucz, czlonkowie in podzial.items():
            split.setdefault(klucz, []).extend(czlonkowie)
    groups = split
    canon_of = {m["fid"]: canon for canon, members in groups.items() for m in members}

    tel_ids = {}
    for canon, members in groups.items():
        # Wartość startowa NOWEGO wiersza: moda zeznań grupy (AR-128) - dawniej pierwsza klatka.
        # Istniejący wiersz jej nie bierze; jego wartość z plików odświeża koniec przebiegu
        # (`optics_from_files` po fazie 2), bo dopiero wtedy wiadomo, które klatki oś mu przypisała.
        start = _optics([(m["kind"], m["fl"], m["fr"], m["cfg_src"] is not None) for m in members
                         if m["kind"] in OPTICS_EVIDENCE_KINDS])
        tel_id, created = repo.propose_telescope(
            con, telescop_canon=canon, f_ratio_nominal=start.f_ratio,
            focal_nominal=start.focal, member_count=len(members), now=now)
        s.telescopes_proposed += created
        tel_ids[canon] = tel_id

    # (2) config iloczyn + link frame.config_id (inwariant: config.camera_id == frame.camera_id)
    for r in sorted(rows, key=lambda r: r["fid"] in oryginaly):     # warianty na koniec (faza 0)
        if r["kind"] in NO_TELESCOPE_KINDS:
            s.calibration_off_axis += 1
            if r["cfg"] is not None and repo.unassign_config(con, frame_id=r["fid"], now=now):
                s.configs_unassigned += 1
            continue
        # RĘKA ROZSTRZYGNĘŁA — PRZEBIEG MILCZY (R1b). Wyjście z pętli stoi PRZED flagą przeglądu
        # świadomie: `flag_config_review` strzelało dotąd BEZWARUNKOWO przy każdym przebiegu, więc
        # klatka z zestawem od człowieka meldowałaby się do przeglądu w nieskończoność, a licznik
        # kubełka nigdy nie spadał po geście — kolejka roboty mówiłaby o robocie już wykonanej.
        # Drugi powód jest cięższy: dla tej populacji (RAW przez teleskop) automat NIE MA racji
        # z definicji formatu — `TELESCOP` z EXIF-u niesie nazwę OBIEKTYWU (E3-3), więc przypisanie
        # z nagłówka nadpisałoby fakt człowieka wartością WPROST fałszywą. Klinga broni tego samego
        # (`repo.assign_config`); tutaj oszczędzamy jeszcze zdarzenie i zbędne SELECT-y.
        if r["cfg_src"] in repo.STICKY_CONFIG_SOURCES:
            s.config_by_hand += 1
            continue
        canon = canon_of.get(r["fid"], "")
        if not canon:
            s.telescop_missing += 1
        tel_id = tel_ids.get(canon)
        if not canon and r["cam"] is not None and r["fid"] in oryginaly:
            zestaw = con.execute(
                "SELECT c.id, c.camera_id FROM frame f JOIN config c ON c.id = f.config_id "
                "WHERE f.id = ?", (oryginaly[r["fid"]],)).fetchone()
            if zestaw is not None and zestaw["camera_id"] == r["cam"]:
                s.configs_by_twin += 1
                if repo.assign_config(con, frame_id=r["fid"], config_id=zestaw["id"], now=now):
                    s.configs_assigned += 1
                continue
            # Oryginał bez zestawu (albo z inną kamerą): zestaw przejęty od niego schodzi razem
            # z nim - wariant bez `TELESCOP` nie ma innego świadka, a ręczny zestaw przebieg minął
            # już wyżej (`STICKY_CONFIG_SOURCES`). Dalej zwykła droga: przegląd.
            if r["cfg"] is not None and repo.unassign_config(con, frame_id=r["fid"], now=now):
                s.configs_unassigned += 1
        if tel_id is None or r["cam"] is None:
            repo.flag_config_review(
                con, frame_id=r["fid"],
                reason="brak osi do config (TELESCOP lub kamera)", now=now)
            s.config_review += 1
            continue
        cfg_id, created = repo.propose_config(con, telescope_id=tel_id, camera_id=r["cam"], now=now)
        s.configs_proposed += created
        if repo.assign_config(con, frame_id=r["fid"], config_id=cfg_id, now=now):
            s.configs_assigned += 1

    # (3) WARTOŚĆ Z PLIKÓW (AR-128) - PO całej fazie 2, łącznie z wariantami AR-54 i klatkami
    # przypiętymi ręką: jedna derywacja dla kanonicznych korzeni. Ręki nie dotyka (`repo`).
    s.optics_refreshed = refresh_all_optics(con, now)
    return s


def refresh_all_optics(con, now, actor="grouper", telescope_ids=None):
    """Wartość Z PLIKÓW (`*_nominal`) każdego kanonicznego teleskopu albo podanych `telescope_ids`
    (ich korzeni) ← `optics_from_files` - JEDNO miejsce odświeżenia, wołane przez Dostawę (krok 3
    `run_grouper`), krok pomigracyjny 0039 (`db.open_db`) i gesty przypięcia klatek
    (`repo.user_assign_config*`, bramka kodu N2). Ręki nie dotyka; bez zmiany zero zdarzeń. Zwraca
    liczbę teleskopów, którym wartość się zmieniła."""
    if telescope_ids is None:
        korzenie = [r[0] for r in con.execute(
            "SELECT id FROM telescope WHERE merged_into IS NULL").fetchall()]
        pliki = optics_from_files(con)
    else:
        korzenie = sorted({r[0] for r in con.execute(
            "SELECT canon_id FROM telescope_canonical WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(sorted(int(i) for i in telescope_ids)),)).fetchall()})
        pliki = {tid: optics_from_files(con, tid) for tid in korzenie}
    n = 0
    for tid in korzenie:
        o = pliki.get(tid)
        if o is not None and repo.refresh_telescope_optics(
                con, telescope_id=tid, focal=o.focal, f_ratio=o.f_ratio, now=now, actor=actor):
            n += 1
    return n
