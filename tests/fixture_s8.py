"""Deterministyczna baza testowa §8 (PLAN_gui §8) — wspólna dla testów logiki (5.2) i `wizytator-qt`
(5.3). Same wiersze, BEZ plików na dysku; `now` jawny (stałe ISO) => powtarzalne testy.

Zawartość JAWNIE pod scenariusze §7 (rec. nr 12 — inaczej R3 testuje przypadek trywialny):
  - ≥3 teleskopy `proposed`; w tym **2 do scalenia DZIELĄCE tę samą kamerę** (A,B → cam1) ⇒ dwa
    configi `(A,cam1)`,`(B,cam1)` = kolizja kamery pod canonical (R3/rec. nr 7);
  - po kilka klatek na config (znana suma pod licznik) + **1 frame `config_id IS NULL`** (review —
    poza sumą canonical);
  - teleskop D bez configu/klatek (kontrola `LEFT JOIN`: `frame_count=0`, nie znika z listy).

NIE woła merge/label/approve — stan wyjściowy to czyste `proposed`/kanoniczne; akcje usera wykonują
testy/wizytator, by kontrolować scenariusz. Reuż.: `python tests/fixture_s8.py <ścieżka.db>` zrzuca
gotowy plik dla wizytatora.
"""
import sys
from pathlib import Path

# Plik bywa uruchamiany JAKO SKRYPT (`python tests/fixture_s8.py <db>` — materializacja §8 dla
# wizytatora 5.3): wtedy na sys.path jest tylko `tests/`, więc dołóż korzeń repo, by `import horreum`
# działał. Pod pytest (`__name__ != "__main__"`) korzeń już jest na ścieżce (pythonpath=["."]) —
# guard nieczynny i nie dubluje wpisu.
if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from horreum import db, repo

NOW = "2026-06-29T12:00:00"


def seed(con):
    """Wypełnij świeżo zmigrowane połączenie zawartością §8. Zwraca dict id-ków (klucze: kamery,
    teleskopy, configi, frame'y) — testy odwołują się po nazwie, nie po surowym int."""
    cam1, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                 is_mono_source="model", raw_instrume="ASI2600MM Pro", now=NOW)
    cam2, _ = repo.upsert_camera(con, model_canon="ASI294MC", pixel_um=4.63, is_mono=0,
                                 is_mono_source="model", raw_instrume="ASI294MC Pro", now=NOW)

    # A,B dzielą cam1 (para do scalenia z kolizją kamery); C samodzielny; D bez klatek.
    # Tożsamość = telescop_canon (nagłówkowa nazwa); f//ogniskowa to właściwości (PF-2).
    a, _ = repo.propose_telescope(con, telescop_canon="A140R",
                                  f_ratio_nominal=5.6, focal_nominal=784, now=NOW)
    b, _ = repo.propose_telescope(con, telescop_canon="A140R-bis",
                                  f_ratio_nominal=5.6, focal_nominal=794, now=NOW)
    c, _ = repo.propose_telescope(con, telescop_canon="RC8",
                                  f_ratio_nominal=8.0, focal_nominal=1624, now=NOW)
    d, _ = repo.propose_telescope(con, telescop_canon="76EDPH",
                                  f_ratio_nominal=4.5, focal_nominal=418, now=NOW)

    cfg_a, _ = repo.propose_config(con, telescope_id=a, camera_id=cam1, now=NOW)
    cfg_b, _ = repo.propose_config(con, telescope_id=b, camera_id=cam1, now=NOW)   # ta sama kamera
    cfg_c, _ = repo.propose_config(con, telescope_id=c, camera_id=cam2, now=NOW)

    frames = {}

    def _frame(name, sha, camera_id, cfg):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits",
                                   camera_id=camera_id, now=NOW)
        if cfg is not None:
            repo.assign_config(con, frame_id=fid, config_id=cfg, now=NOW)
        frames[name] = fid

    _frame("a1", "sha-a1", cam1, cfg_a)
    _frame("a2", "sha-a2", cam1, cfg_a)                       # A: 2 klatki
    _frame("b1", "sha-b1", cam1, cfg_b)
    _frame("b2", "sha-b2", cam1, cfg_b)
    _frame("b3", "sha-b3", cam1, cfg_b)                       # B: 3 klatki
    _frame("c1", "sha-c1", cam2, cfg_c)
    _frame("c2", "sha-c2", cam2, cfg_c)                       # C: 2 klatki
    _frame("nullcfg", "sha-nullcfg", cam1, None)              # review: config_id NULL — poza sumą

    return {"cam1": cam1, "cam2": cam2, "A": a, "B": b, "C": c, "D": d,
            "cfg_a": cfg_a, "cfg_b": cfg_b, "cfg_c": cfg_c, "frames": frames}


def seed_object_axis(con):
    """Rozszerzenie §8 pod oś OBIEKT (PLAN_gui_object §8) — woła `seed`, potem DOKŁADA nagłówki,
    obiekty, lokalizacje i klatki review. NIE zmienia configów istniejących klatek A/B/C (telescope
    testy widzą tę samą licznością `{A:2,B:3,C:2,D:0}` — nowe klatki są `config_id NULL` lub kalibracją,
    czyli poza sumą canonical; nagłówki/obiekty na a1..c2 nie ruszają liczników).

    Scenariusze (R#1–R#7): 2 obiekty (NGC7000 spina teleskopy A+C / kamery cam1+cam2; M42 pod B);
    obiekt-review (FlatWizard ×2); headerless (nullcfg, BEZ headera) vs config-review (z headerem);
    kalibracja (flat — poza biblioteką i kolejką obiektu); frame z jedyną lokalizacją present=0
    (wciąż widoczny); a1 z DWIEMA lokalizacjami (dedup MIN(id)). Zwraca dict `seed` + klucze obiektowe."""
    ids = seed(con)
    fr = ids["frames"]
    cam1, cam2 = ids["cam1"], ids["cam2"]

    obj_ngc, _ = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    obj_m42, _ = repo.upsert_object(con, canon="M42", catalog="Messier", kind="deep_sky", now=NOW)

    # nagłówek + przypisanie obiektu na ISTNIEJĄCYCH klatkach z configiem (liczniki teleskopu bez zmian)
    def _hdr_obj(name, object_raw, obj_id, source, filter_canon=None):
        fid = fr[name]
        repo.record_header(con, frame_id=fid, raw_json="{}", object_raw=object_raw, now=NOW)
        repo.assign_object(con, frame_id=fid, object_id=obj_id, object_source=source, now=NOW)
        if filter_canon is not None:
            repo.backfill_filter_canon(con, [(fid, filter_canon)], now=NOW)

    _hdr_obj("a1", "NGC 7000", obj_ngc, "catalog_xref", filter_canon="Ha")
    _hdr_obj("a2", "NGC 7000", obj_ngc, "catalog_xref", filter_canon="Ha")     # A: obj NGC7000, Ha
    _hdr_obj("b1", "M 42", obj_m42, "catalog_xref", filter_canon="OIII")
    _hdr_obj("b2", "M 42", obj_m42, "catalog_xref")
    _hdr_obj("b3", "M 42", obj_m42, "catalog_xref")                            # B: obj M42
    _hdr_obj("c1", "NGC 7000", obj_ngc, "catalog_xref")
    _hdr_obj("c2", "NGC 7000", obj_ngc, "catalog_xref")                        # C: obj NGC7000 (cam2)

    # a1 — DRUGA lokalizacja (R#3: dedup MIN(id), klatka raz mimo 1:N location); obie present=1
    repo.add_location(con, frame_id=fr["a1"], volume="vol1", path="/astro/a1.fits",
                      drive_letter="R:", now=NOW)
    repo.add_location(con, frame_id=fr["a1"], volume="vol2", path="/backup/a1.fits",
                      drive_letter="S:", now=NOW)

    new = {}

    def _frame(name, sha, kind, camera_id):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype="fits",
                                   camera_id=camera_id, now=NOW)
        new[name] = fid
        return fid

    # obiekt-review: light, config NULL, header z object_raw nierozpoznanym, BEZ object_id (×2 — liczność)
    for nm, sha in (("objrev1", "sha-objrev1"), ("objrev2", "sha-objrev2")):
        rid = _frame(nm, sha, "light", cam1)
        repo.record_header(con, frame_id=rid, raw_json="{}", object_raw="FlatWizard", now=NOW)

    # kalibracja: flat z headerem, BEZ obiektu — NIE w bibliotece ani kolejce obiektu (R#1)
    cal = _frame("calib_flat", "sha-calib", "flat", cam1)
    repo.record_header(con, frame_id=cal, raw_json="{}", object_raw=None, now=NOW)

    # present=0: light z obiektem NGC7000, config NULL, JEDYNA lokalizacja present=0 (R#7 — wciąż widoczny)
    p0 = _frame("present0", "sha-present0", "light", cam1)
    repo.record_header(con, frame_id=p0, raw_json="{}", object_raw="NGC 7000", now=NOW)
    repo.assign_object(con, frame_id=p0, object_id=obj_ngc, object_source="catalog_xref", now=NOW)
    loc_p0, _ = repo.add_location(con, frame_id=p0, volume="vol3", path="/astro/present0.fits", now=NOW)
    # Zniknięcie zasiewamy TĄ SAMĄ drogą, którą idzie pass obecności (P5) — nie surowym UPDATE:
    # fixture ma odwzorowywać stan produkowany przez pień (present=0 + event), a nie własny skrót.
    repo.mark_location_vanished(con, location_id=loc_p0, expected_path="/astro/present0.fits",
                                root="/astro", run_id="fixture", now=NOW)

    # nullcfg z `seed` zostaje headerless (light, config NULL, BEZ headera) — kubełek headerless.
    ids["objects"] = {"NGC7000": obj_ngc, "M42": obj_m42}
    ids["frames"].update(new)
    return ids


def build(path, *, object_axis=False):
    """Zmaterializuj bazę §8 do pliku `path` (importowalny builder — dla `wizytator-qt`/podglądu).
    `object_axis=True` → rozszerzenie osi obiektu (`seed_object_axis`). Zwraca dict id-ków."""
    con = db.open_db(str(path))
    try:
        ids = seed_object_axis(con) if object_axis else seed(con)
    finally:
        con.close()
    return ids


if __name__ == "__main__":
    # CLI dla wizytatora/podglądu: `python tests/fixture_s8.py <ścieżka.db> [--object]` zrzuca gotowy
    # plik (§8 lub §8+oś obiektu) i wypisuje id-ki, by `python -m horreum.gui <ścieżka.db>` miał co pokazać.
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    obj = "--object" in sys.argv[1:]
    if len(args) != 1:
        print("Użycie: python tests/fixture_s8.py <ścieżka.db> [--object]")
        raise SystemExit(2)
    out_ids = build(args[0], object_axis=obj)
    print(f"Horreum {'§8+obiekt' if obj else '§8'} -> {args[0]} : {out_ids}")
