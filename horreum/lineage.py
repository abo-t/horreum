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

**To NIE jest C3.** C3 z planu (`brief/PLAN_kalibracja_lineage.md:45`) to RĘCZNE UZUPEŁNIENIE faktu
przepisu — zapis `source='user'`, `actor=user:local`, przebijający ścieżkę. Tej drogi w repo nie ma
(jedyny wołający `repo.record_calibration_fact` to `calibration.py` z `source='path'`), a odczyt jej
nie tworzy. Dług C3 żyje w kolejce z falsyfikatorem `incomplete > 0`.

Qt-wolne, zapis wyłącznie przez `repo` (DB-KLINGA), SELECT literałem.
"""
import json
from dataclasses import dataclass, field

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
    `linked_new` = delta zapisu (idempotentny re-run daje 0); `reasons` = kubełki luki (per relacja)."""
    lights: int = 0
    linked: dict = field(default_factory=dict)         # relation -> stan (light ma kalibrator)
    linked_new: dict = field(default_factory=dict)     # relation -> realne zapisy tego przebiegu
    reasons: dict = field(default_factory=dict)        # "relation: powód" -> licznik (luki)


def _masters_by_profile(con, profile_id=None):
    """`profile_id -> [(frame_id, datetime|None)]` dla kandydatów `kind LIKE 'master_%'`.
    Master i klatka surowa dzielą profil (C2), więc filtr `master_%` jest KONIECZNY — inaczej
    „czym skalibrować" oddałoby surowego darka jako kalibrator (brief C2 §5).

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
            "WHERE f.calibration_profile_id IS NOT NULL AND f.kind LIKE 'master_%'")
    else:
        cur = con.execute(
            "SELECT f.calibration_profile_id AS pid, f.id AS fid, h.date_obs AS d "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.calibration_profile_id = ? AND f.kind LIKE 'master_%'", (profile_id,))
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


def _decide(row, relation, profiles, masters, light_dt):
    """JEDNA decyzja „czym skalibrować TĘ klatkę w TEJ relacji" → `(master_frame_id, gap_token)`;
    dokładnie jedno z dwojga jest `None`.

    Właściciel predykatu dla OBU wołających: przebieg (`run_lineage`) i odczyt pojedynczej klatki
    (`explain_light`). Bez tego panel odpowiadałby na „dlaczego brak" własną derywacją, która
    rozjeżdża się z przebiegiem po cichu — a rozjazd między tym, co ekran TŁUMACZY, a tym, co
    przebieg ROBI, jest gorszy niż brak tłumaczenia (SIN-DUP)."""
    d = dict(row)
    d["recipe_class"] = relation
    facts = _collect(d, {})                            # stored={} — light nie ma faktów path/user
    if missing_facts(relation, facts):
        return None, "incomplete_recipe"
    pid = profiles.get(profile_key(relation, facts))
    if pid is None:
        return None, "no_profile"
    cand = masters.get(pid)
    if not cand:
        return None, "no_master"
    return _choose(cand, light_dt), None


def run_lineage(con, *, now, actor="lineage"):
    """Przebieg rodowodu — idempotentny jak `calibration`/`grouper`: drugi przebieg na niezmienionych
    danych daje ZERO nowych wierszy `calibration` i ZERO eventów (UNIQUE(light,relation) z 0009 trzyma
    idempotencję, nie kod). Wymaga zapełnionej osi przepisu (po `calibrate`)."""
    s = LineageSummary()
    profiles = {r["profile_key"]: r["id"] for r in con.execute(
        "SELECT id, profile_key FROM calibration_profile")}
    masters = _masters_by_profile(con)

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
            master_id, gap = _decide(d, relation, profiles, masters, light_dt)
            if gap:
                _bump(s.reasons, f"{relation}: {_GAP_PROSE[gap]}")
                continue
            _bump(s.linked, relation)                                # STAN (do domknięcia populacji)
            if repo.link_calibration(con, light_frame_id=row["frame_id"], master_frame_id=master_id,
                                     relation=relation, now=now, actor=actor):
                _bump(s.linked_new, relation)                        # delta realnych zapisów

    s.reasons = dict(sorted(s.reasons.items()))
    repo.flag_calibration_lineage_summary(con, sorted(s.reasons.items()), now, actor=actor)
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

    Zapisu nie ma i mieć nie będzie: panel tłumaczy stan, a zmienia go przebieg (jedna klinga)."""
    row = con.execute(
        "SELECT f.id AS frame_id, f.camera_id AS camera_id, f.filter_canon AS filter_canon, "
        "c.telescope_id AS telescope_id, h.exptime AS exptime, h.set_temp AS set_temp, "
        "h.gain AS gain, h.offset_adu AS offset_adu, h.xbinning AS xbinning, "
        "h.date_obs AS date_obs "
        "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
        "LEFT JOIN config c ON c.id = f.config_id WHERE f.kind = 'light' AND f.id = ?",
        (light_frame_id,)).fetchone()
    if row is None:
        return None
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
    # wciąga ich 128. Panel mówiłby wtedy „przepisy nie są policzone" o bazie z 19 268 powiązaniami
    # i odsyłał do etapu, który niczego nie zmieni.
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
    for relation in relacje:
        s = stan.get(relation)
        if s is not None:
            # DYSTANS CZASU JEST CZĘŚCIĄ ODPOWIEDZI, nie ozdobą. Master dobiera reguła „najbliższy
            # czasowo", więc „dobrane z przepisu" bez liczby brzmi jak pewnik — a zmierzone na
            # żywym archiwum mediany to 139 dni (dark) i 43 dni (flat), z ogonem powyżej trzech lat.
            # Oś stosów w tym samym panelu odróżnia fakt od domysłu; ta ma na to własną miarę.
            mdt = header_dt(s["master_date"])
            dni = None if (mdt is None or light_dt is None) else abs((mdt - light_dt).days)
            out.append({"relation": relation, "master_frame_id": s["master_frame_id"],
                        "master_path": s["master_path"], "confidence": s["confidence"],
                        "asserted_by": s["asserted_by"], "days_apart": dni,
                        "gap": None, "pending": False})
            continue
        master_id, gap = _decide(d, relation, profiles, masters, light_dt)
        if gap == "no_profile" and bez_przepisu:
            gap = "not_calibrated"
        out.append({"relation": relation, "master_frame_id": None, "master_path": None,
                    "confidence": None, "asserted_by": None, "days_apart": None, "gap": gap,
                    "pending": master_id is not None})
    return out


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
        "(SELECT l.path FROM location l WHERE l.frame_id = c.master_frame_id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS master_path "
        "FROM calibration c WHERE c.light_frame_id = ? ORDER BY c.relation",
        (light_frame_id,)).fetchall()
