"""Oś KALIBRACJI — RODOWÓD light↔master po przepisie (segment C4, Issue #6). Siostra `calibration`.

Dla każdej klatki nieba (`kind='light'`) składamy dark-key i flat-key TĄ SAMĄ derywacją co C2
(`calibration._collect` + `profile_key` — SPOT, nie druga asemblacja), dopasowujemy EXACT do
`calibration_profile`, a wśród kandydatów `kind LIKE 'master_%'` w tym profilu wybieramy egzemplarz
regułą „najbliższy czasowo". Light nie jest w `KIND_RECIPE` (nie dostaje profilu — to klatka nieba)
i nie ma faktów `path`/`user` (`stored={}`), więc `_collect` czyta jego `header`+`config` wprost.

CZAS liczymy na `naming.header_dt` (SPOT parser ISO, naive datetime) — NIGDY `julianday`/porównanie
tekstowe na `date_obs`: kolumna niesie 'Z'/ułamki/spację, a string-ordering ≠ wartość bezwzględna
różnicy. Kalibrator to WYŁĄCZNIE `master_%` (filtr w zapytaniu `_masters_by_profile`, nie w komentarzu).

Druga strona monety — „czego brakuje" — to trzy rozłączne kubełki luki per relacja (brak przepisu /
brak mastera / niekompletny przepis lightu); z „linked" domykają populację lightów (bramka §5.12).

STRONA ODCZYTU (C4b, Issue #6): `explain_light` odpowiada za JEDNĄ klatkę — powiązania bierze ze
STANU (`calibrators_for`), a powód braku z tej samej derywacji, którą liczy przebieg (`_decide`).
Bez wspólnego predykatu ekran tłumaczyłby brak inaczej, niż przebieg go tworzy.

SUROWE FLATY (`raw_flats_for`) to TRZECIA, osobna droga - tylko do odczytu, pod wydanie obiektu do
WBPP. `calibration` wiąże lighty wyłącznie z masterami i tak zostaje: wybór surowych niczego nie
zapisuje, bo WBPP sam złoży z nich master, a stan bazy ma mówić, czym skalibrowano, nie czym dałoby
się. Profil flatu lighta bierze się z TEJ SAMEJ derywacji co przebieg (`_profile_for`), a noc z tej
samej definicji co facet Noc (`date(date_obs, '-12 hours')` w SQL), żeby wydanie nie miało własnej
wersji żadnego z tych faktów.

**To NIE jest C3.** C3 z planu (`brief/PLAN_kalibracja_lineage.md:45`) to RĘCZNE UZUPEŁNIENIE faktu
przepisu — zapis `source='user'`, `actor=user:local`, przebijający ścieżkę. Tej drogi w repo nie ma
(jedyny wołający `repo.record_calibration_fact` to `calibration.py` z `source='path'`), a odczyt jej
nie tworzy. Dług C3 żyje w kolejce z falsyfikatorem `incomplete > 0`.

Qt-wolne, zapis wyłącznie przez `repo` (DB-KLINGA), SELECT literałem.
"""
import json
from dataclasses import dataclass, field
from datetime import date

from . import repo
from .calibration import KIND_RECIPE, _collect, missing_facts, profile_key
from .naming import header_dt

# Klasy, które light realnie potrzebuje. `bias` pominięty świadomie: 0 masterbiasów w archiwum
# (skan ich nie produkuje), a bias jest zwykle złożony w masterdarku — CHECK 0009 dopuszcza go
# dla ręki/przyszłości, ale derywacja rodowodu go nie składa.
_RELATIONS = ("dark", "flat")

# Powód luki jedzie z derywacji jako TOKEN, a zdanie składa się dopiero u wołającego: raport
# przebiegu bierze prozę stąd (kotwice §5.12 bramki stoją na tych właśnie ciągach), panel GUI
# bierze swoją z katalogu i18n. Bez tego rozdziału polskie zdanie rdzenia wyciekłoby do wersji EN
# — ta sama granica co przy `unresolved_reason` rodowodu stosów i `ProjectionAbort`.
_GAP_PROSE = {
    "incomplete_recipe": "niekompletny przepis lightu",
    "no_profile": "brak przepisu w archiwum",
    "no_master": "brak mastera (są tylko surowe)",
}


@dataclass
class LineageSummary:
    """Zliczenia przebiegu (QUIET). `linked` = STAN (lighty z kalibratorem, do domknięcia populacji);
    `linked_new` = delta zapisu (idempotentny re-run daje 0); `unlinked` = ogniwa automatu zdjęte,
    bo derywacja nie ma już dla nich kandydata (AR-81; drugi przebieg daje 0); `reasons` = kubełki
    luki (per relacja)."""
    lights: int = 0
    linked: dict = field(default_factory=dict)         # relation -> stan (light ma kalibrator)
    linked_new: dict = field(default_factory=dict)     # relation -> realne zapisy tego przebiegu
    unlinked: dict = field(default_factory=dict)       # relation -> zdjęte ogniwa automatu (AR-81)
    # relation -> wskazania RĘKI na masterze nieaktywnym (wycofany, zastąpiony, bez obecnej kopii).
    # Przebieg ich NIE rusza (ręka nietykalna) - liczy, żeby stan „wskaż inny” miał głos w raporcie.
    hand_inactive: dict = field(default_factory=dict)
    reasons: dict = field(default_factory=dict)        # "relation: powód" -> licznik (luki)


def _masters_by_profile(con, profile_id=None):
    """`profile_id -> [(frame_id, datetime|None)]` dla kandydatów `kind LIKE 'master_%'`.
    Master i klatka surowa dzielą profil (C2), więc filtr `master_%` jest KONIECZNY — inaczej
    „czym skalibrować" oddałoby surowego darka jako kalibrator (brief C2 §5).

    Kandydat jest AKTYWNY (bez `retired_at`/`superseded_by`) - ta sama granica co surowe flaty
    (`raw_flats_for`): master wycofany ręką albo zastąpiony nową treścią pod ścieżką nie ma prawa
    wrócić do doboru z przepisu, a bez filtra przebieg przepinał na niego lighty po cichu.

    `profile_id` ZAWĘŻA do jednego przepisu — odczyt pojedynczej klatki (panel) nie ma powodu
    czytać wszystkich masterów archiwum. Dwa PEŁNE literały zamiast sklejania: bramka
    `test_repo_safety` czyta pierwszy argument `execute` jako stałą, więc `PREFIX + warunek`
    byłaby dla niej SQL-em dynamicznym poza `repo.py`/`db.py`. Powtórzona lista kolumn jest
    kosztem tej bramki, świadomym."""
    out = {}
    if profile_id is None:
        cur = con.execute(
            "SELECT f.calibration_profile_id AS pid, f.id AS fid, h.date_obs AS d "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.calibration_profile_id IS NOT NULL AND f.kind LIKE 'master_%' "
            "AND f.retired_at IS NULL AND f.superseded_by IS NULL")
    else:
        cur = con.execute(
            "SELECT f.calibration_profile_id AS pid, f.id AS fid, h.date_obs AS d "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.calibration_profile_id = ? AND f.kind LIKE 'master_%' "
            "AND f.retired_at IS NULL AND f.superseded_by IS NULL", (profile_id,))
    for r in cur:
        out.setdefault(r["pid"], []).append((r["fid"], header_dt(r["d"])))
    return out


def _choose(masters, light_dt):
    """Najbliższy czasowo master (min |Δ|); remis albo brak czasu → MIN frame.id — deterministycznie
    i JAWNIE, nie crash. Wszystkie mastery mają `date_obs` (sonda), więc `inf` to tylko guard;
    light bez czasu (0 na żywej pf4) degeneruje do najniższego id w profilu."""
    if light_dt is None:
        return min(masters, key=lambda m: m[0])[0]

    def _key(m):
        fid, mdt = m
        delta = abs((mdt - light_dt).total_seconds()) if mdt is not None else float("inf")
        return (delta, fid)
    return min(masters, key=_key)[0]


def _bump(d, key):
    d[key] = d.get(key, 0) + 1


def _profile_for(row, relation, profiles):
    """Przepis lightu w TEJ relacji → `(profile_id, gap_token)`; dokładnie jedno z dwojga jest `None`.

    Pierwsza połowa `_decide`, wydzielona, bo surowe flaty (`raw_flats_for`) pytają o ten sam profil,
    ale kandydatów szukają gdzie indziej. Druga kopia klucza w wydaniu rozjechałaby się z przebiegiem
    przy pierwszym nowym fakcie przepisu - a wtedy wydanie wiązałoby surowe flaty z INNYM przepisem,
    niż ten, z którego rodowód szuka mastera."""
    d = dict(row)
    d["recipe_class"] = relation
    facts = _collect(d, {})                            # stored={} — light nie ma faktów path/user
    if missing_facts(relation, facts):
        return None, "incomplete_recipe"
    pid = profiles.get(profile_key(relation, facts))
    if pid is None:
        return None, "no_profile"
    return pid, None


def _decide(row, relation, profiles, masters, light_dt):
    """JEDNA decyzja „czym skalibrować TĘ klatkę w TEJ relacji" → `(master_frame_id, gap_token)`;
    dokładnie jedno z dwojga jest `None`.

    Właściciel predykatu dla OBU wołających: przebieg (`run_lineage`) i odczyt pojedynczej klatki
    (`explain_light`). Bez tego panel odpowiadałby na „dlaczego brak" własną derywacją, która
    rozjeżdża się z przebiegiem po cichu - a rozjazd między tym, co ekran TŁUMACZY, a tym, co
    przebieg ROBI, jest gorszy niż brak tłumaczenia (SIN-DUP)."""
    pid, gap = _profile_for(row, relation, profiles)
    if gap is not None:
        return None, gap
    cand = masters.get(pid)
    if not cand:
        return None, "no_master"
    return _choose(cand, light_dt), None


def run_lineage(con, *, now, actor="lineage"):
    """Przebieg rodowodu — idempotentny jak `calibration`/`grouper`: drugi przebieg na niezmienionych
    danych daje ZERO nowych wierszy `calibration` i ZERO eventów (UNIQUE(light,relation) z 0009 trzyma
    idempotencję, nie kod). Wymaga zapełnionej osi przepisu (po `calibrate`).

    REKONCYLIACJA LUKI (AR-81): ogniwo AUTOMATU, dla którego derywacja daje dziś lukę (filtr lighta
    wyzerowany, master wycofany, przepis zniknął), znika przez `repo.unlink_calibration` z tokenem
    luki - inaczej panel i rename pokazywały kalibrator, którego przepis już nie wskazuje. Ogniwo
    ręki zostaje: lista dozwolonych źródeł to `repo.CALIBRATION_AUTO_SOURCES`.

    Stan ogniw czytamy RAZ na początku i klingę wołamy tylko tam, gdzie zapis może coś zmienić -
    klinga bierze blokadę zapisu na każde wywołanie, a niezmienione ogniwo to tysiące pustych
    transakcji na przebieg. Decyzję i tak podejmuje klinga pod blokadą: odczyt jest filtrem kosztu,
    nie guardem.

    DRUGA PĘTLA REKONCYLIACJI: ogniwo automatu klatki, która PRZESTAŁA być lightem (przeliczony
    rodzaj, zeznanie `IMAGETYP`), znika z tokenem `not_light` - pętla po lightach nigdy by go nie
    zobaczyła, a kalibrator flata albo darka to zdanie bez treści. Ogniwo ręki zostaje.

    Wskazanie ręki na masterze NIEAKTYWNYM (wycofany, zastąpiony, bez obecnej kopii) zostaje
    nietknięte i liczy się do `hand_inactive` - panel prosi wtedy o wskazanie innego."""
    s = LineageSummary()
    profiles = {r["profile_key"]: r["id"] for r in con.execute(
        "SELECT id, profile_key FROM calibration_profile")}
    masters = _masters_by_profile(con)
    stan = {(r["light_frame_id"], r["relation"]): (r["master_frame_id"], r["asserted_by"])
            for r in con.execute(
                "SELECT light_frame_id, relation, master_frame_id, asserted_by FROM calibration")}
    nieaktywne = {r[0] for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.id IN (SELECT master_frame_id FROM calibration "
        "WHERE asserted_by = 'user') AND (f.retired_at IS NOT NULL OR f.superseded_by IS NOT NULL "
        "OR NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1))")}

    # Populacja pinowana WPROST do `kind='light'` — `master_light` to inny DAG (integration), a
    # wciągnięty do rachunku rozsypałby domknięcie i wyglądał jak bug rozkładu.
    rows = con.execute(
        "SELECT f.id AS frame_id, f.camera_id AS camera_id, f.filter_canon AS filter_canon, "
        "c.telescope_id AS telescope_id, h.exptime AS exptime, h.set_temp AS set_temp, "
        "h.gain AS gain, h.offset_adu AS offset_adu, h.xbinning AS xbinning, "
        "h.date_obs AS date_obs "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id WHERE f.kind = 'light' ORDER BY f.id").fetchall()

    for row in rows:
        s.lights += 1
        light_dt = header_dt(row["date_obs"])
        d = {k: row[k] for k in row.keys()}
        for relation in _RELATIONS:
            zapisane = stan.get((row["frame_id"], relation))
            if zapisane is not None and zapisane[1] == "user":
                # RĘKA ROZSTRZYGNĘŁA (E4-5): light MA kalibrator, także gdy przepis dziś milczy -
                # wskazanie spoza przepisu jest dozwolone właśnie dla lightów bez profilu. Liczony
                # do stanu, nie do luki: kubełek „brak przepisu” o skalibrowanej klatce kłamałby.
                _bump(s.linked, relation)
                if zapisane[0] in nieaktywne:
                    _bump(s.hand_inactive, relation)
                continue
            master_id, gap = _decide(d, relation, profiles, masters, light_dt)
            if gap:
                _bump(s.reasons, f"{relation}: {_GAP_PROSE[gap]}")
                if (zapisane is not None and zapisane[1] in repo.CALIBRATION_AUTO_SOURCES
                        and repo.unlink_calibration(
                            con, light_frame_id=row["frame_id"], relation=relation,
                            allowed=repo.CALIBRATION_AUTO_SOURCES, reason=gap, now=now,
                            actor=actor)):
                    _bump(s.unlinked, relation)                      # AR-81: luka zdjęła automat
                continue
            _bump(s.linked, relation)                                # STAN (do domknięcia populacji)
            if zapisane == (master_id, "horreum"):
                continue                                             # klinga i tak by odmówiła
            if repo.link_calibration(con, light_frame_id=row["frame_id"], master_frame_id=master_id,
                                     relation=relation, now=now, actor=actor):
                _bump(s.linked_new, relation)                        # delta realnych zapisów

    lighty = {row["frame_id"] for row in rows}
    for (light_id, relation), (_master, zrodlo) in sorted(stan.items()):
        if (light_id not in lighty and zrodlo in repo.CALIBRATION_AUTO_SOURCES
                and repo.unlink_calibration(con, light_frame_id=light_id, relation=relation,
                                            allowed=repo.CALIBRATION_AUTO_SOURCES,
                                            reason="not_light", now=now, actor=actor)):
            _bump(s.unlinked, relation)                              # klatka przestała być lightem

    s.reasons = dict(sorted(s.reasons.items()))
    repo.flag_calibration_lineage_summary(con, sorted(s.reasons.items()), now, actor=actor,
                                          unlinked=s.unlinked, hand_inactive=s.hand_inactive)
    return s


class _LazyMasters:
    """Leniwy nośnik kandydatów pod odczyt POJEDYNCZEJ klatki — `.get(pid)` sięga do bazy dopiero
    dla przepisu, który realnie wyszedł z derywacji. Interfejs `.get` jest tu po to, żeby `_decide`
    NIE musiał wiedzieć, czy woła go przebieg (słownik wszystkich masterów), czy panel (jeden
    przepis): predykat zostaje jeden, a koszt odczytu nie rośnie do rozmiaru archiwum."""

    def __init__(self, con):
        self._con = con
        self._cache = {}

    def get(self, pid):
        if pid not in self._cache:
            self._cache[pid] = _masters_by_profile(self._con, pid).get(pid, [])
        return self._cache[pid]


def _light_rows(con, light_ids):
    """Przepis lightów (te same kolumny co przebieg `run_lineage`) dla ZBIORU id - wspólne źródło
    panelu jednej klatki (`explain_light`) i wyboru surowych flatów (`raw_flats_for`).

    Jeden literał na dwóch wołających, bo bramka `test_obie_drogi_czytaja_TE_SAME_kolumny_przepisu`
    pilnuje DOKŁADNIE dwóch list kolumn przepisu (przebieg i odczyt) - trzecia, osobna kopia dla
    wydania przeszłaby obok niej i mogła rozjechać się po cichu. Zbiór id przez `json_each` (idiom
    `calibration.run_calibration`), więc literał zostaje stały. Klatka, która nie jest lightem,
    w wyniku się nie pojawia."""
    return con.execute(
        "SELECT f.id AS frame_id, f.camera_id AS camera_id, f.filter_canon AS filter_canon, "
        "c.telescope_id AS telescope_id, h.exptime AS exptime, h.set_temp AS set_temp, "
        "h.gain AS gain, h.offset_adu AS offset_adu, h.xbinning AS xbinning, "
        "h.date_obs AS date_obs "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id WHERE f.kind = 'light' "
        "AND f.id IN (SELECT value FROM json_each(?)) ORDER BY f.id",
        (json.dumps([int(i) for i in light_ids]),)).fetchall()


def explain_light(con, light_frame_id):
    """READ-ONLY odpowiedź na pytanie ekranu: „czym skalibrowano tę klatkę — a jeśli niczym, to
    DLACZEGO". Zwraca listę dictów (po jednym na relację `dark`/`flat`) albo `None`, gdy klatka
    nie jest lightem (kalibratory ma z definicji tylko klatka nieba — ta sama figura kind-aware
    co przy osi teleskopu).

    TRZY STANY, ROZŁĄCZNE — i trzeci jest tu sednem, nie ozdobą:

    - **powiązana** (`master_frame_id`): wiersz `calibration` ISTNIEJE. Bierzemy STAN z tabeli,
      nigdy ponownej derywacji — powierzchnia pokazuje to, co zapisano, a nie to, co wyszłoby
      dziś (REVIEW-ZE-STANU).
    - **luka** (`gap`): wiersza nie ma i derywacja mówi, czego brakuje (token → zdanie u wołającego).
    - **nieliczona** (`pending`): wiersza nie ma, ale derywacja WSKAZUJE mastera. To nie luka
      archiwum, tylko nieprzebiegnięty (albo stęchły) etap „Rodowód" — i użytkownik ma usłyszeć
      dwie różne rzeczy, bo jedna wymaga zakupu klatek, a druga jednego kliknięcia w Dostawie.

    Zapisu tu nie ma: panel tłumaczy stan, a zmienia go przebieg albo gest ręki (jedna klinga).

    `candidates` każdej relacji to materiał gestu „Wskaż kalibrator…” (E4-5): aktywne mastery tej
    klasy i TEJ SAMEJ kamery, najpierw z przepisu lightu (`in_recipe`), potem spoza niego - ręka
    może wskazać każdy z nich (`_candidates`)."""
    rows = _light_rows(con, [light_frame_id])
    if not rows:
        return None
    row = rows[0]
    stan = {r["relation"]: r for r in calibrators_for(con, light_frame_id)}
    profiles = {r["profile_key"]: r["id"] for r in con.execute(
        "SELECT id, profile_key FROM calibration_profile")}
    # OŚ PRZEPISU TEŻ BYWA NIEPOLICZONA — i to jest stan świeżej bazy, nie przypadek brzegowy.
    # Bez tego pytania `no_profile` mówiłoby „brak w archiwum czegokolwiek o tej nastawie" o bazie
    # PO SKANIE, ale przed etapem „Kalibracja", gdzie mastery leżą, tylko nikt im nie policzył
    # przepisu — czyli zdanie fałszywe dla KAŻDEGO lightu naraz.
    #
    # PYTAMY O KLATKI, KTÓRE PRZEPIS MIEĆ MOGĄ (`KIND_RECIPE` — SPOT z osią przepisu), nie o „każdy
    # master". `master_light` to gotowy obraz po integracji: profilu nie ma i mieć nie będzie, bo
    # `KIND_RECIPE` go nie zna. Wzorzec `LIKE 'master_%'` łapał go razem z kalibracyjnymi, więc
    # JEDEN wciągnięty stos wystarczał, żeby to zdanie zapaliło się na stałe — a droga „Stosy"
    # wciąga ich setki. Panel mówiłby wtedy „przepisy nie są policzone" o bazie z dziesiątkami
    # tysięcy powiązań i odsyłał do etapu, który niczego nie zmieni.
    # Wiązanie listy klas przez `json_each` — idiom `calibration.run_calibration`: literał SQL
    # zostaje STAŁY (bramka `test_repo_safety`), a lista klas ma jedno źródło.
    bez_przepisu = con.execute(
        "SELECT EXISTS(SELECT 1 FROM frame WHERE calibration_profile_id IS NULL "
        "AND kind IN (SELECT value FROM json_each(?)))",
        (json.dumps(tuple(KIND_RECIPE)),)).fetchone()[0]
    masters = _LazyMasters(con)
    light_dt = header_dt(row["date_obs"])
    d = {k: row[k] for k in row.keys()}
    out = []
    # Relacje ze STANU obok stałej: `0009` dopuszcza `bias` i wpisy ręki/WBPP, a panel iterujący
    # samą stałą byłby ślepy na wiersz, który w bazie JEST (kłamałby o stanie, którego nie zna).
    relacje = list(_RELATIONS) + [r for r in stan if r not in _RELATIONS]
    kandydaci = _candidates(con, d, relacje, profiles, light_dt)
    for relation in relacje:
        s = stan.get(relation)
        if s is not None:
            # DYSTANS CZASU JEST CZĘŚCIĄ ODPOWIEDZI, nie ozdobą. Master dobiera reguła „najbliższy
            # czasowo", więc „dobrane z przepisu" bez liczby brzmi jak pewnik — a zmierzone na
            # żywym archiwum mediany to 139 dni (dark) i 43 dni (flat), z ogonem powyżej trzech lat.
            # Oś stosów w tym samym panelu odróżnia fakt od domysłu; ta ma na to własną miarę.
            mdt = header_dt(s["master_date"])
            # PEŁNE DOBY z wartości bezwzględnej, nie `abs(timedelta.days)`: `days` ujemnej różnicy
            # zaokrągla w dół (master 2 doby i 2 h PRZED lightem dawał „Δ 3”), a lista kandydatów
            # gestu liczy pełne doby - ten sam master miał w jednym panelu dwie różne odległości.
            dni = (None if (mdt is None or light_dt is None)
                   else int(abs((mdt - light_dt).total_seconds()) // 86400))
            out.append({"relation": relation, "master_frame_id": s["master_frame_id"],
                        "master_path": s["master_path"], "confidence": s["confidence"],
                        "asserted_by": s["asserted_by"], "days_apart": dni,
                        # AKTYWNY = bez nagrobka I z obecną kopią. Ogniwo automatu do nieaktywnego
                        # mastera przeliczy przebieg; wskazanie ręki zostaje i to panel ma poprosić
                        # o inne - inaczej „jest” mówiłoby o kalibratorze, którym nie da się kalibrować.
                        "master_active": bool(s["master_alive"]) and s["master_path"] is not None,
                        "gap": None, "pending": False, "candidates": kandydaci[relation]})
            continue
        master_id, gap = _decide(d, relation, profiles, masters, light_dt)
        if gap == "no_profile" and bez_przepisu:
            gap = "not_calibrated"
        out.append({"relation": relation, "master_frame_id": None, "master_path": None,
                    "confidence": None, "asserted_by": None, "days_apart": None,
                    "master_active": None, "gap": gap,
                    "pending": master_id is not None, "candidates": kandydaci[relation]})
    return out


def _candidates(con, light, relations, profiles, light_dt):
    """Kandydaci gestu ręki per relacja → `{relation: [dict, ...]}` (materiał `explain_light`).

    Kandydat = master klasy relacji (`master_<relation>`), AKTYWNY (bez nagrobka - ta sama granica
    co `_masters_by_profile` i walidacja klingi) i z TEJ SAMEJ kamery co light: dark z innej matrycy
    nie ma czego odjąć, więc lista nie podsuwa wyboru, którego klinga i tak odmówi
    (`repo.link_calibration`, token `camera`). Light bez kamery nie ma kandydatów.

    NIEZGODNOŚĆ NASTAWY (`mismatch`): kandydat spoza przepisu niesie listę faktów przepisu, którymi
    różni się od lightu (`_niezgodnosc`: filtr / teleskop / binning flatu, ekspozycja / temperatura
    / gain / offset darka) - `[]` dla kandydata z przepisu, `None`, gdy master nie ma profilu (nastawa
    nieznana). Ręka ma prawo wybrać flat OIII dla lightu Ha, ale lista ma to NAZWAĆ, zanim wybierze.

    Kolejność: najpierw z przepisu lightu (`in_recipe` - ten sam profil, z którego przebieg wybiera
    master), potem spoza przepisu od NAJMNIEJ niezgodnych (nastawa nieznana na końcu); w każdej
    grupie rosnąco odległością w czasie, remis → niższe id. Pierwszy kandydat z przepisu jest więc
    tym, którego wybrałby automat, a zaraz za przepisem stoją mastery zgodne co do filtra."""
    out = {r: [] for r in relations}
    if light["camera_id"] is None:
        return out
    pids = {r: _profile_for(light, r, profiles)[0] for r in relations}
    pola_lightu = {r: _pola_lightu(light, r) for r in relations}
    rodzaje = {f"master_{r}": r for r in relations}
    for m in con.execute(
            "SELECT f.id AS fid, f.kind AS kind, f.calibration_profile_id AS profile_id, "
            "h.date_obs AS d, cp.profile_key AS profile_key, "
            "(SELECT l.path FROM location l WHERE l.frame_id = f.id AND l.present = 1 "
            " ORDER BY l.id LIMIT 1) AS path "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "LEFT JOIN calibration_profile cp ON cp.id = f.calibration_profile_id "
            "WHERE f.camera_id = ? AND f.kind IN (SELECT value FROM json_each(?)) "
            "AND f.retired_at IS NULL AND f.superseded_by IS NULL ORDER BY f.id",
            (light["camera_id"], json.dumps(sorted(rodzaje)))):
        relation = rodzaje[m["kind"]]
        mdt = header_dt(m["d"])
        sekundy = (abs((mdt - light_dt).total_seconds())
                   if mdt is not None and light_dt is not None else None)
        w_przepisie = pids[relation] is not None and m["profile_id"] == pids[relation]
        out[relation].append({
            "master_frame_id": m["fid"], "master_path": m["path"],
            "in_recipe": w_przepisie,
            "mismatch": ([] if w_przepisie
                         else _niezgodnosc(relation, pola_lightu[relation], m["profile_key"])),
            "days_apart": None if sekundy is None else int(sekundy // 86400),
            "_s": float("inf") if sekundy is None else sekundy})
    for relation, lista in out.items():
        # Filtr pierwszy wśród różnic: flat innego filtra jest dla lightu najgorszym wyborem, więc
        # zgodni co do filtra stoją przed resztą, potem mniej różnic przed więcej, nieznana nastawa
        # na końcu.
        lista.sort(key=lambda c: (not c["in_recipe"], c["mismatch"] is None,
                                  any(m["fact"] == "filt" for m in c["mismatch"] or ()),
                                  len(c["mismatch"] or ()), c["_s"], c["master_frame_id"]))
        for c in lista:
            del c["_s"]
    return out


# Fakty przepisu, które lista kandydatów porównuje - w kolejności ważności dla człowieka. Nazwy
# pól to człony `calibration.profile_key` (jedno źródło formatu: klucz przepisu, nie druga kopia).
_POLA_PRZEPISU = {"dark": ("exp", "t", "g", "o", "bin"), "bias": ("t", "g", "o", "bin"),
                  "flat": ("filt", "tel", "bin")}


def _pola_lightu(light, relation):
    """Fakty przepisu LIGHTU w formacie członów `profile_key` - ta sama derywacja (`_collect`) i ten
    sam zapis liczb, więc porównanie z kluczem mastera jest porównaniem napisów. Brak faktu = `None`
    (nie wiadomo - nie zgłaszamy niezgodności, której nie umiemy stwierdzić)."""
    if relation not in _POLA_PRZEPISU:
        return {}
    d = dict(light)
    d["recipe_class"] = relation
    f = _collect(d, {})
    pola = {"bin": f.get("xbinning")}
    if relation == "dark":
        pola["exp"] = None if f.get("exptime") is None else f"{f['exptime']:.3f}"
    if relation in ("dark", "bias"):
        pola.update(t=f.get("set_temp_c"), g=f.get("gain"), o=f.get("offset_adu"))
    if relation == "flat":
        pola.update(tel=f.get("telescope_id"), filt=f.get("filter_canon") or "~")
    return {k: None if v is None else str(v) for k, v in pola.items()}


def _niezgodnosc(relation, pola_lightu, profile_key_mastera):
    """Fakty przepisu, którymi master różni się od lightu → `[{"fact", "master", "light"}]`;
    `None`, gdy master nie ma profilu (nastawy nie znamy) albo klasa nie ma przepisu."""
    if profile_key_mastera is None or relation not in _POLA_PRZEPISU:
        return None
    mastera = dict(p.split("=", 1) for p in profile_key_mastera.split("|")[1:] if "=" in p)
    return [{"fact": k, "master": mastera[k], "light": pola_lightu[k]}
            for k in _POLA_PRZEPISU[relation]
            if pola_lightu.get(k) is not None and k in mastera and mastera[k] != pola_lightu[k]]


def calibrators_for(con, light_frame_id):
    """READ-ONLY „czym to skalibrować": wiersze rodowodu dla lightu z nazwą kalibratora (ścieżka
    mastera) i klasą. Dane pod perspektywę GUI (`explain_light`) i raport CLI — bez zapisu.

    `asserted_by` JEST tu potrzebne, choć długo go nie było: migracja `0009` zapowiada wpisy ręki
    i WBPP przebijające derywację, a w DRUGIEJ osi tego samego panelu źródło pewności jest sednem
    („plik zeznał" vs „wynika z czasu"). Panel, który dla stosów pyta „skąd to wiemy", a dla
    kalibracji nie, uczyłby, że pewność bywa nieważna."""
    return con.execute(
        "SELECT c.relation AS relation, c.master_frame_id AS master_frame_id, "
        "c.confidence AS confidence, c.asserted_by AS asserted_by, "
        "(SELECT h.date_obs FROM header h WHERE h.frame_id = c.master_frame_id) AS master_date, "
        "(SELECT m.retired_at IS NULL AND m.superseded_by IS NULL FROM frame m "
        " WHERE m.id = c.master_frame_id) AS master_alive, "
        "(SELECT l.path FROM location l WHERE l.frame_id = c.master_frame_id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS master_path "
        "FROM calibration c WHERE c.light_frame_id = ? ORDER BY c.relation",
        (light_frame_id,)).fetchall()


# --- SUROWE FLATY POD WYDANIE (tylko odczyt; `calibration` zostaje przy masterach) ---

# Domyślne okno nocy surowych flatów - jedno źródło dla odczytu, planu wydania i ich wołających.
RAW_FLAT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class RawFlatPick:
    """Wybór surowych flatów dla JEDNEGO lightu bez master flatu w stanie - albo powód braku.

    Dokładnie jedno z dwojga jest ustawione: `frame_ids` (niepuste) albo `gap`. `night` i `days_apart`
    niosą najbliższą noc surowych także przy `out_of_window` - „są, ale 45 dni obok" to inna
    rozmowa niż „nie ma żadnych", a samo słowo „poza oknem" bez liczby nie pozwala jej podjąć.
    `profile_id` jest `None` tylko tam, gdzie przepisu nie dało się złożyć albo dopasować."""
    frame_ids: tuple
    profile_id: int | None
    night: str | None
    days_apart: int | None
    gap: str | None


def raw_flats_for(con, light_ids, *, window_days=RAW_FLAT_WINDOW_DAYS):
    """READ-ONLY: dla każdego lightu z `light_ids` BEZ wiersza `calibration` relacji `flat` - surowe
    flaty jego przepisu z najbliższej nocy albo token luki. Lighty z master flatem w stanie (i klatki,
    które nie są lightem) w wyniku się nie pojawiają: dla nich wołający bierze mastera ze stanu.

    Tokeny luki: `incomplete_recipe` / `no_profile` (przepis lightu, ta sama derywacja co przebieg),
    `pending` (przepis wskazuje MASTERA, a stanu nie ma - rodowód nie przeliczony; wydanie nie zgaduje
    za przebieg, tylko odsyła do Dostawy - i dlatego wołający NIE liczy go jako „bez flatu": zakup
    klatek i jedno kliknięcie w Dostawie to dwie różne wiadomości, jak w `explain_light`), `no_raw`
    (przepis jest, surowych z obecną kopią nie ma), `out_of_window` (najbliższa noc surowych dalej niż
    `window_days`), `no_time` (light bez `date_obs` - nie zna nocy; na żywej bazie 0, ale gałąź musi
    istnieć, inaczej wybór zgadywałby sesję).

    Kandydat = `kind='flat'` tego samego profilu, aktywny (bez `retired_at`/`superseded_by`), z OBECNĄ
    kopią i z NOCĄ (`date()` nie-NULL: brak `date_obs` i napis, którego SQLite nie rozpozna jako czasu,
    to ten sam brak nocy - samo `IS NOT NULL` przepuściłoby śmieć do arytmetyki dni). Wybór: noc o najmniejszej odległości w dniach od nocy
    lightu, remis → wcześniejsza (deterministycznie); w oknie → WSZYSTKIE klatki profilu z tej nocy,
    bo WBPP składa master z kompletu sesji, a nie z jednej klatki. Noc liczy SQL (`date(date_obs,
    '-12 hours')`, D-UX-1 facetu Noc) - Python tylko odejmuje gotowe daty.

    Koszt stały w liczbie zapytań (stan lightów, przepis, profile, mastery, kandydaci), nie N:
    kandydaci przychodzą jednym zapytaniem po zbiorze profili i grupują się w Pythonie."""
    arg = json.dumps(sorted({int(i) for i in light_ids}))
    bez_mastera = {}
    for r in con.execute(
            "SELECT f.id AS light_id, date(h.date_obs, '-12 hours') AS night "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.kind = 'light' AND f.id IN (SELECT value FROM json_each(?)) "
            "AND NOT EXISTS (SELECT 1 FROM calibration c "
            "                WHERE c.light_frame_id = f.id AND c.relation = 'flat')", (arg,)):
        bez_mastera[r["light_id"]] = r["night"]
    if not bez_mastera:
        return {}

    profiles = {r["profile_key"]: r["id"] for r in con.execute(
        "SELECT id, profile_key FROM calibration_profile")}
    # Mastery tym samym predykatem, z którego przebieg wybiera kalibrator (`_masters_by_profile`) -
    # „pending" ma znaczyć dokładnie to, co `_decide` nazwałby powiązaniem, nie przybliżenie.
    masters = _masters_by_profile(con)
    przepis = {}
    for row in _light_rows(con, sorted(bez_mastera)):
        pid, gap = _profile_for({k: row[k] for k in row.keys()}, "flat", profiles)
        if gap is None and masters.get(pid):
            gap = "pending"
        przepis[row["frame_id"]] = (pid, gap)

    noce = {}                                          # profile_id -> {noc: [flat id, ...]}
    pids = sorted({pid for pid, gap in przepis.values() if gap is None})
    for r in con.execute(
            "SELECT f.calibration_profile_id AS profile_id, f.id AS flat_id, "
            "date(h.date_obs, '-12 hours') AS night "
            "FROM frame f JOIN header h ON h.frame_id = f.id "
            "WHERE f.kind = 'flat' AND date(h.date_obs, '-12 hours') IS NOT NULL "
            "AND f.calibration_profile_id IN (SELECT value FROM json_each(?)) "
            "AND f.retired_at IS NULL AND f.superseded_by IS NULL "
            "AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1) "
            "ORDER BY f.id", (json.dumps(pids),)):
        noce.setdefault(r["profile_id"], {}).setdefault(r["night"], []).append(r["flat_id"])

    out = {}
    for lid, (pid, gap) in przepis.items():
        noc_lightu = bez_mastera[lid]
        if gap is None and not noce.get(pid):
            gap = "no_raw"
        if gap is None and noc_lightu is None:
            gap = "no_time"
        if gap is not None:
            out[lid] = RawFlatPick((), pid, None, None, gap)
            continue
        dzien = date.fromisoformat(noc_lightu)
        odleglosc = {n: abs((date.fromisoformat(n) - dzien).days) for n in noce[pid]}
        noc = min(odleglosc, key=lambda n: (odleglosc[n], n))       # ISO: leksykalnie = chronologicznie
        if odleglosc[noc] <= window_days:
            out[lid] = RawFlatPick(tuple(sorted(noce[pid][noc])), pid, noc, odleglosc[noc], None)
        else:
            out[lid] = RawFlatPick((), pid, noc, odleglosc[noc], "out_of_window")
    return out
