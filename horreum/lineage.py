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

Qt-wolne, zapis wyłącznie przez `repo` (DB-KLINGA), SELECT literałem.
"""
from dataclasses import dataclass, field

from . import repo
from .calibration import _collect, missing_facts, profile_key
from .naming import header_dt

# Klasy, które light realnie potrzebuje. `bias` pominięty świadomie: 0 masterbiasów w archiwum
# (skan ich nie produkuje), a bias jest zwykle złożony w masterdarku — CHECK 0009 dopuszcza go
# dla ręki/przyszłości, ale derywacja rodowodu go nie składa.
_RELATIONS = ("dark", "flat")


@dataclass
class LineageSummary:
    """Zliczenia przebiegu (QUIET). `linked` = STAN (lighty z kalibratorem, do domknięcia populacji);
    `linked_new` = delta zapisu (idempotentny re-run daje 0); `reasons` = kubełki luki (per relacja)."""
    lights: int = 0
    linked: dict = field(default_factory=dict)         # relation -> stan (light ma kalibrator)
    linked_new: dict = field(default_factory=dict)     # relation -> realne zapisy tego przebiegu
    reasons: dict = field(default_factory=dict)        # "relation: powód" -> licznik (luki)


def _masters_by_profile(con):
    """`profile_id -> [(frame_id, datetime|None)]` dla kandydatów `kind LIKE 'master_%'`.
    Master i klatka surowa dzielą profil (C2), więc filtr `master_%` jest KONIECZNY — inaczej
    „czym skalibrować" oddałoby surowego darka jako kalibrator (brief C2 §5)."""
    out = {}
    for r in con.execute(
            "SELECT f.calibration_profile_id AS pid, f.id AS fid, h.date_obs AS d "
            "FROM frame f LEFT JOIN header h ON h.frame_id = f.id "
            "WHERE f.calibration_profile_id IS NOT NULL AND f.kind LIKE 'master_%'"):
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
            d["recipe_class"] = relation
            facts = _collect(d, {})                        # stored={} — light nie ma faktów path/user
            if missing_facts(relation, facts):
                _bump(s.reasons, f"{relation}: niekompletny przepis lightu")
                continue
            pid = profiles.get(profile_key(relation, facts))
            if pid is None:
                _bump(s.reasons, f"{relation}: brak przepisu w archiwum")
                continue
            cand = masters.get(pid)
            if not cand:
                _bump(s.reasons, f"{relation}: brak mastera (są tylko surowe)")
                continue
            master_id = _choose(cand, light_dt)
            s.linked[relation] = s.linked.get(relation, 0) + 1       # STAN (do domknięcia populacji)
            if repo.link_calibration(con, light_frame_id=row["frame_id"], master_frame_id=master_id,
                                     relation=relation, now=now, actor=actor):
                s.linked_new[relation] = s.linked_new.get(relation, 0) + 1

    s.reasons = dict(sorted(s.reasons.items()))
    repo.flag_calibration_lineage_summary(con, sorted(s.reasons.items()), now, actor=actor)
    return s


def calibrators_for(con, light_frame_id):
    """READ-ONLY „czym to skalibrować": wiersze rodowodu dla lightu z nazwą kalibratora (ścieżka
    mastera) i klasą. Dane pod perspektywę GUI (dokłada się z C3) i raport CLI — bez zapisu."""
    return con.execute(
        "SELECT c.relation AS relation, c.master_frame_id AS master_frame_id, "
        "c.confidence AS confidence, "
        "(SELECT l.path FROM location l WHERE l.frame_id = c.master_frame_id AND l.present = 1 "
        " ORDER BY l.id LIMIT 1) AS master_path "
        "FROM calibration c WHERE c.light_frame_id = ? ORDER BY c.relation",
        (light_frame_id,)).fetchall()
