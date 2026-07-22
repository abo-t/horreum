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
"""
from dataclasses import dataclass

from . import repo

# Rodzaje BEZ osi teleskopu (kind-scoping config — zob. nagłówek). Jedyny właściciel faktu (SPOT);
# `resolver.review_state` konsumuje tę samą stałą, żeby kolejka przeglądu nie rozjechała się z osią.
NO_TELESCOPE_KINDS = frozenset({"dark", "bias", "master_dark", "master_bias"})


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


def run_grouper(con, now):
    """Po skanie: (1) wyłoń teleskopy z DISTINCT `TELESCOP.strip()`; (2) config iloczyn
    (telescope×camera) + link `frame.config_id`. Brak/pusty TELESCOP lub brak kamery →
    `config.review` (W4, zero cichego NULL; kolejka ze STANU `config_id IS NULL`). Zwraca
    `GroupSummary`. Idempotentny (propose_* i assign_config sprawdzają stan przed zapisem).

    `NO_TELESCOPE_KINDS` (dark/bias) omija OBIE fazy: nie wnosi zeznania na oś teleskopu i nie
    trafia do configu ani do `config.review` — jego `config_id IS NULL` to POPRAWNY STAN, nie delta
    (jak `object_id NULL` dla kalibracji w resolverze). Dane sprzed kind-scopingu mają takie klatki
    PRZYPISANE do cudzego configu, więc przebieg je AKTYWNIE ODPINA (`repo.unassign_config`) —
    grouper sam się leczy, a oś teleskopu przestaje liczyć darki pod cudzą optyką."""
    s = GroupSummary()

    rows = con.execute(
        "SELECT f.id AS fid, f.camera_id AS cam, f.kind AS kind, f.config_id AS cfg, "
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
        canon = (r["tel"] or "").strip()
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
