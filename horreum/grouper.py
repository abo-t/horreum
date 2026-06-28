"""Krok ZBIORCZY po skanie — grouper teleskopów + config (PLAN §Etap 5).

To jedyna część, której nie widać w pojedynczym pliku: sygnatura grupy mieszka w rozkładzie
CAŁOŚCI. Czyta przez SELECT (meta-test AST dopuszcza SELECT poza repo), normalizuje FOCRATIO,
klastruje sygnatury, wyłania teleskopy/configi i linkuje `frame.config_id` — WSZYSTKIE zapisy idą
przez `repo` (jedna klinga); ten moduł nie wykonuje żadnego DML.
"""
from dataclasses import dataclass

from . import repo
from .resolve.telescopes import cluster_signatures, normalize_focratio


@dataclass
class GroupSummary:
    """Zliczenia jednego przebiegu `run_grouper` — do firsthand-weryfikacji."""
    headers: int = 0
    focratio_ok: int = 0
    focratio_recovered: int = 0
    focratio_review: int = 0
    telescopes_proposed: int = 0
    telescopes_suspect: int = 0
    configs_proposed: int = 0
    configs_assigned: int = 0
    config_review: int = 0


def run_grouper(con, now):
    """Po skanie: (1) backfill `focratio_norm`; (2) sklej teleskopy z DISTINCT sygnatur (klaster);
    (3) config iloczyn (telescope×camera) + link `frame.config_id`. Mastery bez FOCRATIO / brak
    kamery → `config.review` (W4, zero cichego NULL). Zwraca `GroupSummary`. Idempotentny
    (propose_* i assign_config sprawdzają stan przed zapisem)."""
    s = GroupSummary()

    # (1) backfill focratio_norm per header — osobna faza pochodna (nie przez record_header)
    rows = con.execute("SELECT frame_id, focratio_raw, focallen FROM header").fetchall()
    s.headers = len(rows)
    items = []
    for r in rows:
        norm, src = normalize_focratio(r["focratio_raw"], r["focallen"])
        items.append((r["frame_id"], norm, src))
        s.focratio_ok += (src == "ok")
        s.focratio_recovered += (src == "recovered")
        s.focratio_review += (src == "review")
    if items:
        repo.backfill_focratio_norm(con, items, now=now)

    # (2) klaster teleskopów z DISTINCT (focratio_norm, focallen) — sygnatura mieszka w rozkładzie
    sig_rows = con.execute(
        "SELECT DISTINCT focratio_norm, focallen FROM header "
        "WHERE focratio_norm IS NOT NULL AND focallen IS NOT NULL").fetchall()
    clusters = cluster_signatures([(r["focratio_norm"], r["focallen"]) for r in sig_rows])

    # reprezentatywny surowy TELESCOP per sygnatura (audyt → telescop_hint)
    hint_map = {}
    for r in con.execute("SELECT focratio_norm, focallen, telescop FROM header "
                         "WHERE focratio_norm IS NOT NULL AND telescop IS NOT NULL"):
        hint_map.setdefault((r["focratio_norm"], r["focallen"]), r["telescop"])

    sig_to_tel = {}
    for cl in clusters:
        hint = next((hint_map[m] for m in cl["members"] if m in hint_map), None)
        tel_id, created = repo.propose_telescope(
            con, f_ratio_nominal=cl["f_ratio_nominal"], focal_nominal=cl["focal_nominal"],
            telescop_hint=hint, member_count=len(cl["members"]), now=now)
        s.telescopes_proposed += created
        if cl["suspect"]:
            repo.flag_telescope_review(
                con, telescope_id=tel_id,
                reason=f"rozpiętość klastra > tolerancja ({len(cl['members'])} sygnatur)", now=now)
            s.telescopes_suspect += 1
        for m in cl["members"]:
            sig_to_tel[m] = tel_id

    # (3) config iloczyn + link frame.config_id (inwariant: config.camera_id == frame.camera_id)
    frames = con.execute(
        "SELECT f.id AS fid, f.camera_id AS cam, h.focratio_norm AS fn, h.focallen AS fl "
        "FROM frame f JOIN header h ON h.frame_id = f.id").fetchall()
    for fr in frames:
        tel_id = sig_to_tel.get((fr["fn"], fr["fl"])) if fr["fn"] is not None else None
        if tel_id is None or fr["cam"] is None:
            repo.flag_config_review(
                con, frame_id=fr["fid"],
                reason="brak osi do config (focratio/teleskop lub kamera)", now=now)
            s.config_review += 1
            continue
        cfg_id, created = repo.propose_config(con, telescope_id=tel_id, camera_id=fr["cam"], now=now)
        s.configs_proposed += created
        if repo.assign_config(con, frame_id=fr["fid"], config_id=cfg_id, now=now):
            s.configs_assigned += 1
    return s
