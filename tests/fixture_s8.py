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
    a, _ = repo.propose_telescope(con, f_ratio_nominal=5.6, focal_nominal=784, now=NOW)
    b, _ = repo.propose_telescope(con, f_ratio_nominal=5.6, focal_nominal=794, now=NOW)
    c, _ = repo.propose_telescope(con, f_ratio_nominal=8.0, focal_nominal=1624, now=NOW)
    d, _ = repo.propose_telescope(con, f_ratio_nominal=4.5, focal_nominal=418, now=NOW)

    cfg_a, _ = repo.propose_config(con, telescope_id=a, camera_id=cam1, now=NOW)
    cfg_b, _ = repo.propose_config(con, telescope_id=b, camera_id=cam1, now=NOW)   # ta sama kamera
    cfg_c, _ = repo.propose_config(con, telescope_id=c, camera_id=cam2, now=NOW)

    frames = {}

    def _frame(name, sha, camera_id, cfg):
        fid, _ = repo.upsert_frame(con, sha1=sha, kind="light", filetype="fits", size_bytes=1,
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


def build(path):
    """Zmaterializuj bazę §8 do pliku `path` (importowalny builder — dla `wizytator-qt`/podglądu
    w 5.3). Zwraca dict id-ków."""
    con = db.open_db(str(path))
    try:
        ids = seed(con)
    finally:
        con.close()
    return ids
