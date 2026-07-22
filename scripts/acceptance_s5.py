"""Kryteria akceptacji PF-5 (brief/PLAN_przejscie_fits.md §5) — read-only walidacja realnego pipeline'u.

Re-baseline PF-5: baseline = DAWCA LIVE (`fitsmirror.db`), koniec custos.db. Świeżą bazę
Horreum buduje wprost z dawcy przez REALNY import (`import_fitsmirror.run_import`) — ten sam
pipeline co PF-3 (jedna klinga: `ingest_record` → grouper → resolver, z bramkami §4.6 w środku).
Skrypt dokłada kryteria §5 na wynikowej bazie i (opcjonalnie) odtwarza pełny stan PF-4 doskanem
XISF. Zero prywatnych ścieżek w kodzie — wszystko z argumentów.

Tryb HYBRYDOWY (odpowiednik replay+subset ze skilla `pipeline-replay-validation`):
  (I) IMPORT  — `run_import(dawca LIVE → świeża work.db)`. Cache'owane zeznania dawcy przez
      DOKŁADNIE ten sam `ingest_record`+grouper+resolver co realny skan; §4.6 gate'y w środku
      (abort = twarde złamanie). Baseline FITS (8 teleskopów, 5 kamer), w minuty, zero 839 GB.
  (X) XISF-DOSKAN (opcja `--xisf-root DIR`) — po imporcie realny `scan_tree` po drzewie z XISF
      (volume z `volume_serial`), potem grouper+resolver. Odtwarza PF-4: FITS gate'owane mtime
      (skip, zero re-odczytu), XISF wciągane → 9. teleskop ED, pełne kotwice §5. Pełne `<xisf-root>`
      → pełny stan pf4 (czyta tylko ~331 nagłówków XISF, reszta stat-skip).
  (C) KRYTERIA — stage-aware (import vs full po obecności XISF): zestawia aktualia z EXP_* PF-3+PF-4.
  (S) SUBSET (opcja `--subset DIR`) — realny `scan_tree` małego katalogu do OSOBNEJ work.db:
      dowód, że czytniki astropy/XISF + sha1 działają na realnych bajtach; tu (i tylko tu) realny
      no-split FITS-float ↔ XISF-string, gdy katalog ma oba formaty.

§8.1 (meta-tripwir AST jednej klingi) i bramka izolowanego clone'a są OSOBNE — pytest
(`tests/test_repo_safety.py`) i procedura clone→venv→non-editable→pytest; ten skrypt je przypomina.

Użycie:
  python scripts/acceptance_s5.py --donor fitsmirror.db [--xisf-root <xisf-root>]
                                  [--subset PATH\\maly_real_dir] [--work PATH\\horreum_s5.db] [--keep]
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

# pakiet horreum z korzenia repo (skrypt leży w scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from horreum import db                                              # noqa: E402
from horreum.grouper import NO_TELESCOPE_KINDS, run_grouper       # noqa: E402
from horreum.import_fitsmirror import ImportAbort, open_donor, run_import  # noqa: E402
from horreum.resolver import delta_report, run_resolver           # noqa: E402
from horreum.scan import canonize_root, scan_tree                 # noqa: E402
from horreum.volumes import volume_serial                         # noqa: E402

# ── Kotwice EXP_* PF-3 (dawca) + PF-4 (doskan XISF), z horreum_pf4.db 2026-07-02 ─────────────────
# 5 kamer: (pixel_um, is_mono). Po naprawie nagłówków INSTRUME 100% — brak review kamer.
EXP_CAMERAS = {
    "ASI2600MM": (3.76, 1), "ASI2600MD": (3.76, 1), "ASI2600MC": (3.76, 0),
    "ASI294MC": (4.63, 0), "SONYA7RM3": (4.86, 0),
}
EXP_TELESCOPES_IMPORT = 8      # dawca FITS (§1): A140R/RC8/76EDPH/ED120R/RC6/N800/Sony135/ED120
# Po naprawie ED na realnym R: (2026-07-22, brief PLAN_p6_xisf_writeback §8) etykieta `ED` nie ma już
# nosiciela na osi: 7 masterflatów XISF dostało `ED120R`+789, a masterdarki z `TELESCOP='ED'` są POZA
# osią (kind-scoping, wariant B). Świeża baza nie powołuje 9. teleskopu — dług PF-4 spłacony.
EXP_TELESCOPES_FULL = 8        # jak IMPORT: naprawa zdjęła jedynego nosiciela etykiety `ED`
EXP_OBJECT_PCT_MIN = 85.0      # % obiektu na light/master_light (pf4=87.5; próg z zapasem)
# Stan PF-4 (pełny, po doskanie XISF) — XISF wnoszą dług review i degenerat:
EXP_UNCOMPUTABLE_FULL = 1      # masterflat OIII: bajt \x07 w XML → sha1_data nieobliczalne (degenerat)
EXP_FRAME_REVIEW_FULL = 1      # ten sam masterflat (kopia nieczytelna → review)
# Po kind-scopingu config (wariant B, 2026-07-22) dark/bias są POZA osią teleskopu: ich `config_id
# IS NULL` to stan docelowy, nie delta, więc `config.review` ich nie dotyczy. Zostaje 1 realna sprawa
# — masterflat Sony A7R3 o rodzaju `unknown` (ten sam degenerat, co §5.2). Było 7 (6 masterdarków + on).
EXP_CONFIG_REVIEW_FULL = 1     # `unknown` masterflat A7R3 — rodzaj wymaga decyzji, nie optyka
EXP_XISF_KINDS = {"flat": 11, "light": 202, "master_dark": 38, "master_flat": 73, "unknown": 2}
# Oś OBSERWATORIUM (PLAN_os_obserwatorium §8) — RE-BASELINE P6b (D-X-8a), świadomy i zmierzony:
# do P6a karty XISF NIE POWSTAWAŁY, więc GPS był de facto FITS-only. Od P6a skan wypełnia karty
# także dla XISF, a backfill (`horreum backfill-xisf`) dociąga je do lokacji sprzed P6a — 202 klatki
# XISF niosą SITELAT+SITELONG i wchodzą na oś. Wszystkie 202 mają JEDNĄ parę współrzędnych, 52 m od
# stanowiska „Szczecin, Będargowo" → ZERO nowych stanowisk (EXP_OBSERVATORIES bez ruchu), rusza się
# wyłącznie populacja. Kotwica jest STAGE-AWARE: etap IMPORT (dawca FITS, zero XISF) zostaje na
# 15 409 — gdyby liczba tam drgnęła, znaczyłoby to zmianę w torze FITS, nie skutek P6.
EXP_OBSERVATORIES = 11         # klaster 4 km: 24 distinct pary → 11 stanowisk (dom↔praca 4.385 km OSOBNE)
EXP_GPS_FRAMES_IMPORT = 15409  # dawca FITS: klatki z SITELAT+SITELONG (97.0%)
EXP_GPS_FRAMES_FULL = 15611    # + 202 XISF z GPS w kartach (P6b; wszystkie do stanowiska #5)
EXP_NO_GPS_FULL = 274          # bez GPS w FULL: 150 fits + 124 xisf (326 − 202 z GPS)


def _ok(cond):
    return "PASS" if cond else "FAIL"


# ── (I) IMPORT: dawca LIVE → świeża baza przez realny pipeline PF-3 ───────────────────────────────
def build_import(donor_path, work_path, now, out):
    """Zbuduj świeżą horreum.db z dawcy LIVE przez `run_import` (jedna klinga; §4.6 gate'y w środku).
    Dawca RO (`open_donor`). Zwraca (con, ImportSummary). Twarde złamanie → ImportAbort propaguje."""
    if os.path.exists(work_path):
        os.remove(work_path)
    out(f"== (I) IMPORT: {donor_path} -> {work_path} ==")
    donor = open_donor(donor_path)
    try:
        con = db.open_db(work_path)
        con.execute("PRAGMA synchronous=OFF")          # baza JEDNORAZOWA — wolno przyspieszyć
        summary = run_import(donor, con, now=now)
    finally:
        donor.close()
    pf = summary.preflight
    out(f"  pre-flight: root {pf.root} volume {pf.volume}; dawca {pf.files_total} plikow; "
        f"nadwyzka dysku {pf.surplus}; falsyfikator OK ({len(pf.verified)} plikow)")
    for note in pf.notes:
        out(f"    {note}")
    out(f"  import: {summary.imported}/{summary.files_total} "
        f"(skipped {summary.skipped}, przeliczone z dysku {summary.recomputed})")
    out(f"  grouper: {summary.group}")
    out(f"  resolver: {summary.resolve}")
    out(f"  bramki §4.6: {'WSZYSTKIE PASS' if not summary.gate_failures else summary.gate_failures}")
    return con, summary


# ── (X) XISF-DOSKAN: realny scan_tree po drzewie z XISF (odtwarza PF-4) ──────────────────────────
def doskan_xisf(con, xisf_root, now, out):
    """Po imporcie dołóż XISF realnym skanem (jak PF-4). FITS gate'owane mtime (skip), XISF wciągane;
    potem grouper+resolver. Volume z `volume_serial` (brama musi trafiać znane FITS)."""
    out("")
    out(f"== (X) XISF-DOSKAN: scan_tree {xisf_root} ==")
    root = canonize_root(xisf_root)
    volume = volume_serial(root)
    if volume is None:
        raise RuntimeError(f"volume_serial({root!r}) nieustalony — zamontuj wolumin XISF-roota")
    s = scan_tree(con, root, volume=volume, drive_letter=(os.path.splitdrive(root)[0] or None),
                  tier=None, now=now)
    out(f"  scan: files={s.files} frames_new={s.frames_new} skipped(mtime)={s.skipped} "
        f"frame_review={s.frame_review} dirs_excluded={s.dirs_excluded}")
    gs = run_grouper(con, now=now)
    rs = run_resolver(con, now=now)
    out(f"  grouper: {gs}")
    out(f"  resolver: {rs}")


# ── (C) KRYTERIA §5 na bazie zbudowanej z dawcy (stage-aware: import vs full) ─────────────────────
def check_criteria(con, summary, out):
    results = []                                    # (etykieta, PASS/FAIL)

    def crit(label, cond):
        results.append((label, bool(cond)))
        out(f"  [{_ok(cond)}] {label}")

    n_xisf = con.execute("SELECT count(*) FROM frame WHERE filetype='xisf'").fetchone()[0]
    full = n_xisf > 0
    stage = "FULL (import + doskan XISF = PF-4)" if full else "IMPORT (dawca FITS = PF-3)"
    exp_tel = EXP_TELESCOPES_FULL if full else EXP_TELESCOPES_IMPORT
    out("")
    out(f"== (C) KRYTERIA §5 — stan: {stage} ==")

    # §5.1 tożsamość: sha1_data 100% (każdy frame ma odcisk danych; degenerat = flaga)
    n_frame = con.execute("SELECT count(*) FROM frame").fetchone()[0]
    n_sha = con.execute(
        "SELECT count(*) FROM frame WHERE sha1_data IS NOT NULL AND sha1_data!=''").fetchone()[0]
    uncomp = con.execute("SELECT count(*) FROM frame WHERE sha1_data_uncomputable=1").fetchone()[0]
    out(f"\n§5.1 tożsamość: frame={n_frame} z sha1_data={n_sha} (degenerat uncomputable={uncomp})")
    crit("§5.1 sha1_data 100% (każdy frame ma odcisk danych)", n_sha == n_frame and n_frame > 0)
    if full:
        crit(f"§5.1 degenerat XISF ~{EXP_UNCOMPUTABLE_FULL} (OIII masterflat, bajt \\x07)",
             uncomp == EXP_UNCOMPUTABLE_FULL)
    else:
        crit("§5.1 zero degeneratów w imporcie FITS (nagłówki naprawione)", uncomp == 0)

    # frame == location − dedupy treścią (import: 1:1; full: 5 dedupów XISF w pf4)
    n_loc = con.execute("SELECT count(*) FROM location").fetchone()[0]
    if not full:
        crit(f"§4.6 frame == location == dawca−skipped ({summary.imported})",
             n_frame == summary.imported and n_loc == summary.imported)
    else:
        out(f"  (full) frame={n_frame} location={n_loc} — dedupy treścią = {n_loc - n_frame}")
        crit("§4.6 location >= frame (dedup sha1_data łączy byte-identyczne mastery)", n_loc >= n_frame)

    # §5.3/§5.8 kamery: 5 form, piksel, mono, ZERO rozbić modelu (no-split)
    out("\n§5.3/§5.8 kamery (model, pixel, is_mono, src):")
    cams = {r[0]: r for r in con.execute(
        "SELECT model_canon, pixel_um, is_mono, is_mono_source, pixel_conflict FROM camera")}
    for mc in sorted(cams):
        _, px, mono, msrc, pc = cams[mc]
        out(f"    {mc:12s} px={px} is_mono={mono} src={msrc} pixel_conflict={pc}")
    cams_ok = set(cams) == set(EXP_CAMERAS)
    px_mono_ok = all(mc in cams and cams[mc][1] == EXP_CAMERAS[mc][0]
                     and cams[mc][2] == EXP_CAMERAS[mc][1] for mc in EXP_CAMERAS)
    crit("§5.3 5 kamer, piksel+mono zgodne (MM/MD mono, MC/294/Sony kolor)", cams_ok and px_mono_ok)
    distinct_models = con.execute("SELECT count(DISTINCT model_canon) FROM camera").fetchone()[0]
    n_cam_rows = con.execute("SELECT count(*) FROM camera").fetchone()[0]
    crit("§5.8 zero rozbić modelu (distinct model_canon == wierszy camera)",
         distinct_models == n_cam_rows == len(EXP_CAMERAS))
    pconf = con.execute("SELECT count(*) FROM camera WHERE pixel_conflict=1").fetchone()[0]
    crit("§5.3 pixel_conflict == 0 (brak rozjazdu piksela)", pconf == 0)

    # §5.4 teleskopy: liczność (import 8 / full 9) + suspect=0 (verb telescope.review MARTWY po PF-2)
    out("\n§5.4 teleskopy (canon, f/, focal, #frames):")
    tels = con.execute(
        "SELECT t.telescop_canon, t.f_ratio_nominal, t.focal_nominal, "
        "  (SELECT count(*) FROM frame f JOIN config c ON c.id=f.config_id WHERE c.telescope_id=t.id) "
        "FROM telescope t ORDER BY 4 DESC").fetchall()
    for tc, fr_, fl, nfr in tels:
        out(f"    {tc:10s} f/{str(fr_):<5} focal={str(fl):<6} frames={nfr}")
    crit(f"§5.4 liczba teleskopów == {exp_tel} (akt={len(tels)})", len(tels) == exp_tel)
    suspect = con.execute("SELECT count(*) FROM event WHERE verb='telescope.review'").fetchone()[0]
    crit(f"§5.4 telescope.review MARTWY po PF-2 (akt={suspect})", suspect == 0)

    # §5.6 config bez cichego NULL: frame z headerem bez config_id ⟺ ma config.review.
    # KIND-AWARE (wariant B): dark/bias są poza osią teleskopu, więc ich NULL nie jest „cichy" —
    # jest docelowy. Predykat czerpie zbiór z `grouper.NO_TELESCOPE_KINDS` (jeden właściciel, SPOT),
    # ten sam, którego używa `resolver.review_state`; osobno raportujemy, ile klatek tak wyłączono.
    cfg = con.execute("SELECT count(*) FROM config").fetchone()[0]
    cfg_review = con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0]
    off_axis = json.dumps(sorted(NO_TELESCOPE_KINDS))
    no_cfg_hdr = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.kind NOT IN (SELECT value FROM json_each(?)) "
        "AND EXISTS(SELECT 1 FROM header h WHERE h.frame_id=f.id)", (off_axis,)).fetchone()[0]
    calib_null = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.kind IN (SELECT value FROM json_each(?))", (off_axis,)).fetchone()[0]
    unassigned = con.execute(
        "SELECT count(*) FROM event WHERE verb='config.unassigned'").fetchone()[0]
    out(f"\n§5.6 config={cfg} config.review={cfg_review} frame-bez-config-z-headerem={no_cfg_hdr} "
        f"(kalibracja poza osią={calib_null}, odpięte={unassigned})")
    crit("§5.6 zero cichego NULL (frame z headerem bez config == config.review)",
         no_cfg_hdr == cfg_review)
    crit("§5.6 kalibracja bez osi NIE ma config.assigned (kind-scoping)",
         con.execute(
             "SELECT count(*) FROM frame WHERE config_id IS NOT NULL "
             "AND kind IN (SELECT value FROM json_each(?))", (off_axis,)).fetchone()[0] == 0)
    if full:
        crit(f"§5.6 config.review ~{EXP_CONFIG_REVIEW_FULL} (`unknown` masterflat A7R3)",
             cfg_review == EXP_CONFIG_REVIEW_FULL)
    else:
        crit("§5.6 config.review == 0 w imporcie FITS (nagłówki naprawione)", cfg_review == 0)

    # §5.7 obiekt — % na light/master_light przez REALNY delta_report (kalibracja świadomie poza)
    rep = delta_report(con, top=40)
    out(f"\n§5.7 obiekt: {rep.object_resolved}/{rep.object_resolved+rep.object_unresolved} "
        f"= {rep.object_pct}% (delta {rep.object_unresolved} w {len(rep.object_delta)} distinct)")
    for raw, n in rep.object_delta[:12]:
        out(f"    {n:5d}  {raw}")
    crit(f"§5.7 object_pct >= {EXP_OBJECT_PCT_MIN}% (akt={rep.object_pct}%)",
         rep.object_pct >= EXP_OBJECT_PCT_MIN)

    # §5.8 (full) — kinds XISF (dowód, że doskan wciągnął to co PF-4)
    if full:
        xk = dict(con.execute(
            "SELECT kind, count(*) FROM frame WHERE filetype='xisf' GROUP BY kind").fetchall())
        out(f"\n§5.8 kinds XISF: {xk}")
        crit(f"§5.8 kinds XISF == PF-4 {EXP_XISF_KINDS}", xk == EXP_XISF_KINDS)
        frev = con.execute("SELECT count(*) FROM event WHERE verb='frame.review'").fetchone()[0]
        crit(f"§5.8 frame.review ~{EXP_FRAME_REVIEW_FULL} (OIII masterflat)",
             frev == EXP_FRAME_REVIEW_FULL)

    # §5.9 encje == eventy (co do sztuki) — audyt jednej klingi kompletny
    out("\n§5.9 encje == eventy:")
    pairs = [
        ("camera", "camera.upserted"), ("frame", "frame.observed"),
        ("location", "location.added"), ("header", "header.recorded"),
        ("telescope", "telescope.proposed"), ("config", "config.proposed"),
        ("object", "object.upserted"), ("object_alias", "object.aliased"),
        ("observatory", "observatory.proposed"),
    ]
    all_match = True
    for ent, verb in pairs:
        ne = con.execute(f"SELECT count(*) FROM {ent}").fetchone()[0]
        nv = con.execute("SELECT count(*) FROM event WHERE verb=?", (verb,)).fetchone()[0]
        ok = ne == nv
        all_match &= ok
        out(f"    {ent:13s} {ne:6d} == {verb:20s} {nv:6d}  [{_ok(ok)}]")
    fa = con.execute("SELECT count(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    va = con.execute("SELECT count(*) FROM event WHERE verb='config.assigned'").fetchone()[0]
    oa = con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0]
    vo = con.execute("SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0]
    sa = con.execute("SELECT count(*) FROM frame WHERE observatory_id IS NOT NULL").fetchone()[0]
    vs = con.execute("SELECT count(*) FROM event WHERE verb='observatory.assigned'").fetchone()[0]
    out(f"    frame.config_id {fa} == config.assigned {va}  [{_ok(fa == va)}]")
    out(f"    frame.object_id {oa} == object.assigned {vo}  [{_ok(oa == vo)}]")
    out(f"    frame.observatory_id {sa} == observatory.assigned {vs}  [{_ok(sa == vs)}]")
    all_match &= (fa == va) and (oa == vo) and (sa == vs)
    crit("§5.9 encje == eventy (co do sztuki, łącznie z przypisaniami)", all_match)

    # §5.10 oś OBSERWATORIUM — 11 stanowisk (§8 klaster), populacje domykają, zero nieparsowalnego GPS
    n_obs = con.execute("SELECT count(*) FROM observatory").fetchone()[0]
    gps_cards = con.execute(
        "SELECT count(*) FROM frame f "
        "WHERE EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELAT') "
        "AND EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELONG')").fetchone()[0]
    gps_null = con.execute(
        "SELECT count(*) FROM frame f WHERE f.observatory_id IS NULL "
        "AND EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELAT') "
        "AND EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELONG')").fetchone()[0]
    no_obs = con.execute("SELECT count(*) FROM frame WHERE observatory_id IS NULL").fetchone()[0]
    pops = con.execute(
        "SELECT o.id, o.lat, o.lon, COUNT(fr.id) AS n FROM observatory o "
        "LEFT JOIN observatory_canonical oc ON oc.canon_id=o.id "
        "LEFT JOIN frame fr ON fr.observatory_id=oc.id "
        "WHERE o.merged_into IS NULL GROUP BY o.id ORDER BY n DESC").fetchall()
    out(f"\n§5.10 oś obserwatorium: {n_obs} stanowisk, {sa} przypisanych, {gps_cards} z GPS-kartami, "
        f"{no_obs} bez stanowiska:")
    for oid, la, lo, n in pops:
        out(f"    #{oid:<3} {la:>10.5f}, {lo:>10.5f}  frames={n}")
    exp_gps = EXP_GPS_FRAMES_FULL if full else EXP_GPS_FRAMES_IMPORT
    crit(f"§5.10 {EXP_OBSERVATORIES} stanowisk (klaster 4 km, §8)", n_obs == EXP_OBSERVATORIES)
    crit(f"§5.10 GPS-karty == {exp_gps} (§8; FULL niesie +202 XISF po P6b)", gps_cards == exp_gps)
    crit("§5.10 zero nieparsowalnego GPS (sonda: formaty czyste, 0 śmieci)", gps_null == 0)
    # Twarda brama na CZĘŚCIOWY/śmieciowy GPS (rec.#11): `gps_null` widzi tylko klatki z OBIEMA kartami,
    # więc lone-coord (jedna współrzędna → site_coords None → review) by mu umknął. review_summary łapie
    # OBA (śmieć i lone-coord); jego BRAK dowodzi zero cichego review. Pusta lista → event nie powstaje.
    obs_review = con.execute(
        "SELECT count(*) FROM event WHERE verb='observatory.review_summary'").fetchone()[0]
    crit("§5.10 zero cichego review (brak observatory.review_summary: śmieć/lone-coord)", obs_review == 0)
    crit("§5.10 populacje stanowisk domykają do przypisanych", sum(p[3] for p in pops) == sa)
    crit("§5.10 przypisane == GPS-karty (wszystkie sparsowane)", sa == gps_cards)
    if full:
        crit(f"§5.10 bez GPS == {EXP_NO_GPS_FULL} (150 fits + 124 xisf bez SITELAT/SITELONG)",
             no_obs == EXP_NO_GPS_FULL)

    return results


# ── (S) SUBSET: realny skan małego katalogu (czytniki + sha1 na realnych bajtach) ────────────────
def run_subset(subset_dirs, now, out):
    out("")
    out(f"== (S) SUBSET — realny scan_tree ({len(subset_dirs)} kat.) ==")
    sub_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_subset_s5.db")
    if os.path.exists(sub_db):
        os.remove(sub_db)
    con = db.open_db(sub_db)
    frame_review = 0
    for d in subset_dirs:
        s = scan_tree(con, d, volume="subset", now=now)
        frame_review += s.frame_review
        out(f"  skan {d}: files={s.files} frames_new={s.frames_new} headers={s.headers} "
            f"frame_review={s.frame_review}")

    # no-split §5.8 na realnych typach: ten sam model z FITS i XISF → 1 wiersz (float↔string)
    cams = con.execute(
        "SELECT c.model_canon, c.pixel_um, "
        "  SUM(f.filetype='fits') AS n_fits, SUM(f.filetype='xisf') AS n_xisf "
        "FROM camera c JOIN frame f ON f.camera_id=c.id GROUP BY c.id").fetchall()
    out("  kamery w subsecie (model, pixel, #fits, #xisf):")
    for mc, px, nf, nx in cams:
        flag = "  <- z OBU formatow = JEDEN wiersz (no-split realny)" if nf and nx else ""
        out(f"    {mc:12s} px={px} fits={nf} xisf={nx}{flag}")
    distinct_models = con.execute("SELECT count(DISTINCT model_canon) FROM camera").fetchone()[0]
    n_cam_rows = con.execute("SELECT count(*) FROM camera").fetchone()[0]
    split_ok = distinct_models == n_cam_rows
    out(f"  model_canon distinct={distinct_models} wierszy camera={n_cam_rows}  "
        f"[{_ok(split_ok)} — zero rozbić modelu]")
    out(f"  frame_review łącznie={frame_review} (oczekiwane 0 — realne pliki czytelne)  "
        f"[{_ok(frame_review == 0)}]")
    con.close()
    os.remove(sub_db)
    return split_ok and (frame_review == 0)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="Kryteria akceptacji PF-5 (read-only): import z dawcy LIVE + kryteria §5")
    ap.add_argument("--donor", required=True, help="ścieżka dawcy fitsmirror.db (LIVE, otwierany read-only)")
    ap.add_argument("--xisf-root", default=None,
                    help="drzewo z XISF do doskanu (np. <xisf-root>) — odtwarza pełny stan PF-4")
    ap.add_argument("--subset", default=None,
                    help="mały realny katalog (lub kilka po przecinku) do krzyż-czeku czytników/sha1")
    ap.add_argument("--work", default=None, help="ścieżka jednorazowej horreum.db (domyślnie obok skryptu)")
    ap.add_argument("--keep", action="store_true", help="nie usuwaj bazy roboczej po zakończeniu")
    args = ap.parse_args(argv)

    out = print
    now = datetime.now(timezone.utc).isoformat()
    work = args.work or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_horreum_s5.db")

    try:
        con, summary = build_import(args.donor, work, now, out)
    except ImportAbort as exc:
        out(f"\nACCEPTANCE ABORT (import z dawcy nie przeszedł): {exc}")
        return 1

    if args.xisf_root:
        doskan_xisf(con, args.xisf_root, now, out)

    results = check_criteria(con, summary, out)
    con.close()

    subset_ok = True
    if args.subset:
        dirs = [d.strip() for d in args.subset.split(",") if d.strip()]
        subset_ok = run_subset(dirs, now, out)

    if not args.keep and os.path.exists(work):
        os.remove(work)

    out("")
    out("== PODSUMOWANIE ==")
    failed = [lab for lab, ok in results if not ok]
    for lab in failed:
        out(f"  FAIL: {lab}")
    out("  §8.1 (AST jednej klingi) i bramka clone'a — OSOBNE: pytest + procedura clone.")
    hard_ok = not failed and subset_ok
    out(f"  WYNIK: {'WSZYSTKO PASS' if hard_ok else f'{len(failed)} FAIL' + ('' if subset_ok else ' + subset')}")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
