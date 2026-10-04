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
"""
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
    byłoby zmianą osi teleskopu przy okazji zmiany osi sprzętu."""
    s = GroupSummary()

    rows = con.execute(
        "SELECT f.id AS fid, f.camera_id AS cam, f.kind AS kind, f.config_id AS cfg, "
        "       f.config_source AS cfg_src, f.filetype AS ft, "
        "       h.telescop AS tel, h.focallen AS fl, h.focratio_raw AS fr "
        "FROM frame f JOIN header h ON h.frame_id = f.id").fetchall()
    s.headers = len(rows)

    # (1) grupy po strip() — reprezentatywne właściwości (f/, ogniskowa) z pierwszego
    # niepustego zeznania grupy (nullable właściwości audytowe, nie klucz — brief §3).
    # Kalibracja bez teleskopu NIE zeznaje: dark z 'ED' w nagłówku nie powołuje teleskopu do życia.
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
        for klucz, czlonkowie in _soczewki_raw(con, canon, members).items():
            split.setdefault(klucz, []).extend(czlonkowie)
    groups = split
    canon_of = {m["fid"]: canon for canon, members in groups.items() for m in members}

    tel_ids = {}
    for canon, members in groups.items():
        focal = next((m["fl"] for m in members if m["fl"] is not None), None)
        fratio = next((m["fr"] for m in members if m["fr"] is not None), None)
        tel_id, created = repo.propose_telescope(
            con, telescop_canon=canon, f_ratio_nominal=fratio,
            focal_nominal=int(round(focal)) if focal is not None else None,
            member_count=len(members), now=now)
        s.telescopes_proposed += created
        tel_ids[canon] = tel_id

    # (2) config iloczyn + link frame.config_id (inwariant: config.camera_id == frame.camera_id)
    for r in rows:
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
    return s
