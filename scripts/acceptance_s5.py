"""Kryteria akceptacji §5 (PLAN_horreum_schema.md) — read-only walidacja realnego pipeline'u.

>>> JAWNIE NIEOPERACYJNY do PF-5 (brief/PLAN_przejscie_fits.md §5) <<<
PF-2 zmienił model danych (tożsamość = sha1_data, baseline custos.db OUT) — stare liczby EXP_*
i replay z custos.db są NIEWAŻNE. PF-5 przepisze skrypt na baseline = dawca (fitsmirror.db).
Do tego czasu skrypt odmawia startu (nie jest bramką pośrednią PF-2..PF-4).

NIE test pytest (zależy od zewnętrznego źródła = custos.db, którego clean-clone NIE ma → nie wolno
go zbierać, inaczej padłaby bramka clone'a §5.11). To CLI uruchamiane na żądanie, parametryzowane
(zero prywatnych ścieżek w kodzie).

Tryb HYBRYDOWY (decyzja Zdzinia):
  (R) REPLAY — buduje świeżą horreum.db, wpuszczając cache'owane nagłówki źródła (`header_json`
      + sha1/size/mtime) przez DOKŁADNIE ten sam pipeline co realny skan: `scan.ingest_record`
      (jedna klinga) → `grouper.run_grouper` → `resolver.run_resolver`. Pełne liczby §5.3–5.9 na
      całości (15 890 FITS+XISF), w minuty, zero obciążenia NAS.
  (S) SUBSET — realny `scan.scan_tree` na MAŁYM realnym katalogu: dowód, że czytniki astropy/XISF
      działają na realnych bajtach i sha1 == cache. Tu (i tylko tu) FITS-float ↔ XISF-string są
      RÓŻNYCH typów → jedyny prawdziwy test no-split §5.8 na realnych plikach.
  (C) KRYTERIA — liczy aktualia z bazy REPLAY i zestawia z oczekiwaniami §5 (PASS / ~ / FAIL).

§5.10 (meta-tripwir AST jednej klingi) i §5.11 (bramka izolowanego clone'a) są OSOBNE — pytest
(`tests/test_repo_safety.py`) i procedura clone→venv→non-editable→pytest; ten skrypt je tylko przypomina.

Użycie:
  python scripts/acceptance_s5.py --custos PATH\\custos.db [--subset PATH\\maly_real_dir]
                                  [--work PATH\\horreum_s5.db] [--keep]
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
from horreum.grouper import run_grouper                            # noqa: E402
from horreum.resolver import run_resolver, delta_report           # noqa: E402
from horreum.scan import ScanRecord, ScanSummary, ingest_record, scan_tree  # noqa: E402

# ── Oczekiwania §5 (firsthand na symulacji — brief; tolerancje na „~") ───────────────────────────
EXP_FOCRATIO = {"ok": 12608, "recovered": 2624, "review": 655}    # §5.5
EXP_TELESCOPES = [                                                  # §5.4 (hint, f/, focal, ~frames)
    ("A140R", 5.6, 789, 7331), ("ED120", 6.54, 792, 1159),
    ("RC8", 8.0, 1600, 4771), ("76EDPH", 4.5, 342, 1717),
    ("RC6", 9.13, 1370, 154), ("Sony135", 2.0, 110, 100),
]
EXP_OBJECT_PCT_MIN = 86.0                                           # §5.7 (po Etapie 6.x)
TOL_COUNT = 0.05                                                    # ±5% dla liczności „~"


def _ok(cond):
    return "PASS" if cond else "FAIL"


def _approx(actual, expected, tol=TOL_COUNT):
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= max(1, round(expected * tol))


# ── (R) REPLAY: cache'owane nagłówki źródła → realny pipeline ─────────────────────────────────────
def build_replay(custos_path, work_path, now):
    """Zbuduj świeżą horreum.db z `header_json` źródła przez realny `ingest_record`. Read-only wobec
    custos.db (URI mode=ro). Zwraca (con, ScanSummary, n_source_rows)."""
    if os.path.exists(work_path):
        os.remove(work_path)
    con = db.open_db(work_path)
    con.execute("PRAGMA synchronous=OFF")          # baza JEDNORAZOWA — wolno przyspieszyć
    con.execute("PRAGMA journal_mode=MEMORY")

    src = sqlite3.connect(f"file:{custos_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT path, sha1, size_bytes, mtime, header_json FROM files "
        "WHERE filetype IN ('fits','xisf')").fetchall()
    src.close()

    summary = ScanSummary()
    for r in rows:
        summary.files += 1
        try:
            header = json.loads(r["header_json"]) if r["header_json"] else None
            rec = ScanRecord(
                path=r["path"], sha1=r["sha1"], size_bytes=r["size_bytes"] or 0,
                mtime=str(r["mtime"]), header=header,
                error=None if header is not None else "brak header_json")
            ingest_record(con, rec, volume="custos-replay", now=now, summary=summary)
        except Exception as exc:                    # backstop W1 (jak scan_tree) — rekord nie wywala całości
            from horreum import repo
            repo.flag_frame_review(con, sha1=r["sha1"] or "?", path=r["path"],
                                   reason=f"{type(exc).__name__}: {exc}", now=now)
            summary.frame_review += 1
    return con, summary, len(rows)


# ── (S) SUBSET: realny skan małego katalogu (czytniki + sha1 na realnych bajtach) ────────────────
def run_subset(custos_path, subset_dirs, now, out):
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

    # sha1 realny == cache źródła (dowód, że hashing.sha1_of zgadza się z custos)
    src = sqlite3.connect(f"file:{custos_path}?mode=ro", uri=True)
    paths = [row[0] for row in con.execute("SELECT path FROM location")]
    match = miss = absent = 0
    for p in paths:
        real = con.execute(
            "SELECT f.sha1 FROM frame f JOIN location l ON l.frame_id=f.id WHERE l.path=?",
            (p,)).fetchone()
        cached = src.execute("SELECT sha1 FROM files WHERE path=?", (p,)).fetchone()
        if cached is None:
            absent += 1
        elif real and real[0] == cached[0]:
            match += 1
        else:
            miss += 1
    src.close()
    out(f"  sha1 realny vs cache: match={match} mismatch={miss} brak-w-custos={absent}  "
        f"[{_ok(miss == 0)}]")

    # no-split §5.8 na realnych typach: jeśli ten sam model kamery przyszedł z FITS i XISF → 1 wiersz
    cams = con.execute(
        "SELECT c.model_canon, c.pixel_um, "
        "  SUM(f.filetype='fits') AS n_fits, SUM(f.filetype='xisf') AS n_xisf "
        "FROM camera c JOIN frame f ON f.camera_id=c.id GROUP BY c.id").fetchall()
    out("  kamery w subsecie (model, pixel, #fits, #xisf):")
    split_ok = True
    for mc, px, nf, nx in cams:
        flag = ""
        if nf and nx:
            flag = "  <- z OBU formatow = JEDEN wiersz (no-split realny)"
        out(f"    {mc:12s} px={px} fits={nf} xisf={nx}{flag}")
    # liczba distinct model_canon == liczba wierszy camera (żaden model nie rozbity)
    distinct_models = con.execute("SELECT COUNT(DISTINCT model_canon) FROM camera").fetchone()[0]
    n_cam_rows = con.execute("SELECT COUNT(*) FROM camera").fetchone()[0]
    split_ok = (distinct_models == n_cam_rows)
    out(f"  model_canon distinct={distinct_models} wierszy camera={n_cam_rows}  "
        f"[{_ok(split_ok)} — zero rozbic modelu]")
    out(f"  frame_review łącznie={frame_review} (oczekiwane 0 — realne pliki czytelne)  "
        f"[{_ok(frame_review == 0)}]")
    con.close()
    os.remove(sub_db)
    return (miss == 0) and split_ok and (frame_review == 0)


# ── (C) KRYTERIA §5 na bazie REPLAY ──────────────────────────────────────────────────────────────
def check_criteria(con, src_rows, summary, custos_path, now, out):
    results = []                                    # (etykieta, PASS/FAIL)

    def crit(label, cond):
        results.append((label, bool(cond)))
        out(f"  [{_ok(cond)}] {label}")

    out("")
    out("== (C) KRYTERIA §5 (replay) ==")

    # §5.1 sha1 100%
    n_frame = con.execute("SELECT COUNT(*) FROM frame").fetchone()[0]
    n_sha = con.execute("SELECT COUNT(*) FROM frame WHERE sha1 IS NOT NULL AND sha1!=''").fetchone()[0]
    out(f"\n§5.1 sha1: frame={n_frame} z sha1={n_sha} (źródło FITS+XISF={src_rows})")
    crit("§5.1 sha1 100% (każdy frame ma sha1)", n_sha == n_frame and n_frame > 0)

    # §5.3 + §5.8 kamery
    out("\n§5.3/§5.8 kamery (model, pixel, mono, src):")
    cams = {r[0]: r for r in con.execute(
        "SELECT model_canon, pixel_um, is_mono, is_mono_source FROM camera")}
    for mc in sorted(cams):
        _, px, mono, msrc = cams[mc]
        out(f"    {mc:12s} px={px} is_mono={mono} src={msrc}")
    have_2600 = {f"ASI2600{x}" for x in ("MM", "MC", "MD")} <= set(cams)
    px_ok = all(cams[f"ASI2600{x}"][1] == 3.76 for x in ("MM", "MC", "MD") if f"ASI2600{x}" in cams)
    mono_ok = (cams.get("ASI2600MM", (None,)*4)[2] == 1 and cams.get("ASI2600MD", (None,)*4)[2] == 1
               and cams.get("ASI2600MC", (None,)*4)[2] == 0)
    crit("§5.3 trzy kamery 2600 (MM/MC/MD), pixel 3.76, mono MM/MD MC=kolor", have_2600 and px_ok and mono_ok)
    a294 = [m for m in cams if m.startswith("ASI294")]
    crit("§5.8 ASI294 scalona w JEDNĄ ASI294MC (reguła B, kolor)",
         a294 == ["ASI294MC"] and cams["ASI294MC"][2] == 0)

    # §5.5 FOCRATIO
    fr = dict(con.execute(
        "SELECT focratio_norm_src, COUNT(*) FROM header GROUP BY focratio_norm_src").fetchall())
    out(f"\n§5.5 FOCRATIO src: {fr}")
    for k in ("ok", "recovered", "review"):
        a = fr.get(k, 0)
        crit(f"§5.5 focratio '{k}' ~{EXP_FOCRATIO[k]} (akt={a})", _approx(a, EXP_FOCRATIO[k]))

    # §5.4 teleskopy (frame'y per teleskop przez config) + suspect=0
    out("\n§5.4 teleskopy (f/, focal, hint, #frames):")
    tels = con.execute(
        "SELECT t.id, t.f_ratio_nominal, t.focal_nominal, t.telescop_hint, "
        "  (SELECT COUNT(*) FROM frame f JOIN config c ON c.id=f.config_id WHERE c.telescope_id=t.id) AS nfr "
        "FROM telescope t ORDER BY nfr DESC").fetchall()
    for tid, fr_, fl, hint, nfr in tels:
        out(f"    f/{fr_:<5} focal={fl:<6} hint={hint!r:14} frames={nfr}")
    # dopasuj każdy oczekiwany do realnego po (f/ ±0.2, focal ±30)
    for hint, ef, efl, ecnt in EXP_TELESCOPES:
        m = [t for t in tels if abs((t[1] or -9) - ef) <= 0.2 and abs((t[2] or -9) - efl) <= 30]
        nfr = m[0][4] if m else 0
        crit(f"§5.4 {hint} (f/{ef}, focal~{efl}, ~{ecnt}fr) obecny i liczność ~",
             bool(m) and _approx(nfr, ecnt))
    n_tel = len(tels)
    crit(f"§5.4 liczba teleskopów == {len(EXP_TELESCOPES)} (akt={n_tel})", n_tel == len(EXP_TELESCOPES))
    suspect = con.execute("SELECT COUNT(*) FROM event WHERE verb='telescope.review'").fetchone()[0]
    crit(f"§5.4 suspect=0 (telescope.review, akt={suspect})", suspect == 0)

    # §5.6 config bez cichego NULL
    cfg = con.execute("SELECT COUNT(*) FROM config").fetchone()[0]
    cfg_review = con.execute("SELECT COUNT(*) FROM event WHERE verb='config.review'").fetchone()[0]
    assigned = con.execute("SELECT COUNT(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    # każdy frame BEZ config_id musi mieć config.review (zero cichego NULL)
    no_cfg = con.execute("SELECT COUNT(*) FROM frame WHERE config_id IS NULL").fetchone()[0]
    out(f"\n§5.6 config={cfg} assigned={assigned} bez_config={no_cfg} config.review={cfg_review}")
    crit("§5.6 zero cichego NULL (frame bez config_id == liczba config.review)", no_cfg == cfg_review)
    crit(f"§5.6 config.review ~{EXP_FOCRATIO['review']} (mastery bez focratio)",
         _approx(cfg_review, EXP_FOCRATIO["review"]))

    # §5.7 obiekt — % na lightach + delta (przez REALNY delta_report)
    rep = delta_report(con, top=40)
    out(f"\n§5.7 obiekt: {rep.object_resolved}/{rep.object_resolved+rep.object_unresolved} "
        f"= {rep.object_pct}% (delta {rep.object_unresolved} w {len(rep.object_delta)} distinct)")
    for raw, n in rep.object_delta[:15]:
        out(f"    {n:5d}  {raw}")
    crit(f"§5.7 object_pct >= {EXP_OBJECT_PCT_MIN}% (akt={rep.object_pct}%)",
         rep.object_pct >= EXP_OBJECT_PCT_MIN)

    # §5.9 encje == eventy (co do sztuki)
    out("\n§5.9 encje == eventy:")
    pairs = [
        ("camera", "camera.upserted"), ("frame", "frame.observed"),
        ("location", "location.added"), ("header", "header.recorded"),
        ("telescope", "telescope.proposed"), ("config", "config.proposed"),
        ("object", "object.upserted"), ("object_alias", "object.aliased"),
    ]
    all_match = True
    for ent, verb in pairs:
        ne = con.execute(f"SELECT COUNT(*) FROM {ent}").fetchone()[0]
        nv = con.execute("SELECT COUNT(*) FROM event WHERE verb=?", (verb,)).fetchone()[0]
        ok = ne == nv
        all_match &= ok
        out(f"    {ent:13s} {ne:6d} == {verb:20s} {nv:6d}  [{_ok(ok)}]")
    # przypisania (UPDATE-y) też mają event
    fa = con.execute("SELECT COUNT(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    va = con.execute("SELECT COUNT(*) FROM event WHERE verb='config.assigned'").fetchone()[0]
    oa = con.execute("SELECT COUNT(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0]
    vo = con.execute("SELECT COUNT(*) FROM event WHERE verb='object.assigned'").fetchone()[0]
    out(f"    frame.config_id {fa} == config.assigned {va}  [{_ok(fa == va)}]")
    out(f"    frame.object_id {oa} == object.assigned {vo}  [{_ok(oa == vo)}]")
    all_match &= (fa == va) and (oa == vo)
    crit("§5.9 encje == eventy (co do sztuki, łącznie z przypisaniami)", all_match)

    return results


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # PF-2: model danych zmieniony (sha1_data, custos-baseline OUT) — skrypt czeka na re-baseline
    # PF-5 (baseline = dawca fitsmirror.db). Jawna odmowa zamiast po cichu falszywych liczb.
    print("acceptance_s5: NIEOPERACYJNY do PF-5 (przejscie fitsmirror, brief par. 5) — "
          "re-baseline na dawcy fitsmirror.db nastapi w PF-5.")
    return 2
    ap = argparse.ArgumentParser(description="Kryteria akceptacji §5 (read-only, hybryda replay+subset)")
    ap.add_argument("--custos", required=True, help="ścieżka custos.db (źródło, otwierane read-only)")
    ap.add_argument("--subset", default=None,
                    help="mały realny katalog (lub kilka po przecinku) do krzyż-czeku czytników/sha1")
    ap.add_argument("--work", default=None, help="ścieżka jednorazowej horreum.db (domyślnie obok skryptu)")
    ap.add_argument("--keep", action="store_true", help="nie usuwaj bazy roboczej po zakończeniu")
    args = ap.parse_args(argv)

    out = print
    now = datetime.now(timezone.utc).isoformat()
    work = args.work or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_horreum_s5.db")

    out(f"== (R) REPLAY: {args.custos} -> {work} ==")
    con, summary, src_rows = build_replay(args.custos, work, now)
    out(f"  ingest: {summary}")
    gs = run_grouper(con, now=now)
    out(f"  grouper: {gs}")
    rs = run_resolver(con, now=now)
    out(f"  resolver: {rs}")

    results = check_criteria(con, src_rows, summary, args.custos, now, out)
    con.close()

    subset_ok = True
    if args.subset:
        dirs = [d.strip() for d in args.subset.split(",") if d.strip()]
        subset_ok = run_subset(args.custos, dirs, now, out)

    if not args.keep and os.path.exists(work):
        os.remove(work)

    # podsumowanie
    out("")
    out("== PODSUMOWANIE ==")
    failed = [lab for lab, ok in results if not ok]
    for lab, ok in results:
        if not ok:
            out(f"  FAIL: {lab}")
    out(f"  §5.10 (AST jednej klingi) i §5.11 (clone-gate) — OSOBNE: pytest + procedura clone.")
    hard_ok = not failed and subset_ok
    out(f"  WYNIK: {'WSZYSTKO PASS' if hard_ok else f'{len(failed)} FAIL' + ('' if subset_ok else ' + subset')}")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
