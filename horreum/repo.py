"""JEDNA KLINGA — jedyne drzwi do zapisu domenowego (PLAN §2).

Wzorzec przeniesiony z `custos/commit/mover.py` (jedyny obramkowany dom dla destrukcyjnego
ostrza) i przełożony na ZAPIS DO BAZY: każdy INSERT/UPDATE encji domenowej przechodzi przez
ten moduł, który **w tej samej transakcji** emituje wpis do `event`. Żaden inny moduł nie
wykonuje DML na tabelach domenowych — pilnuje tego statyczny meta-tripwir AST
(`tests/test_repo_safety.py`) od commitu zero (odpowiednik zakazu `os.rename` poza mover.py).

Zasady:
- Tożsamość zmian, nie destrukcja: zmiana stanu = APPEND `event` + zapis wskaźnika, nigdy
  kasacja historii (PLAN §6).
- Zero cichych porażek: nierozstrzygalny config/obiekt → `event(*.review)` (warstwa skanu),
  nigdy ciche zgadywanie.
- `now` podawany jawnie (ISO-8601) — deterministyczne testy, jak `now_fn` w Custosie.
"""
import json


def emit_event(con, *, actor, verb, target, now, payload=None, reason=None):
    """Dopisz zdarzenie do append-only `event`. Wołane WYŁĄCZNIE z tego modułu, w tej samej
    transakcji co zapis, który opisuje."""
    con.execute(
        "INSERT INTO event(ts, actor, verb, target, payload, reason) VALUES (?, ?, ?, ?, ?, ?)",
        (now, actor, verb, target,
         json.dumps(payload, ensure_ascii=False) if payload is not None else None,
         reason),
    )


def upsert_camera(con, *, model_canon, pixel_um, is_mono, is_mono_source,
                  raw_instrume, now, actor="scan"):
    """Wyłoń kamerę (oś) ze skanu. Tożsamość = (model_canon, pixel_um) — UNIQUE.

    Istnieje → zwróć (id, False), bez eventu (brak zmiany stanu). Nowa → INSERT + emisja
    `camera.upserted` W TEJ SAMEJ TRANSAKCJI; zwróć (id, True). Encje kamer wyłaniają się
    ze skanu (PLAN §3.6), nie są wymyślane a priori.
    """
    row = con.execute(
        "SELECT id FROM camera WHERE model_canon = ? AND pixel_um = ?",
        (model_canon, pixel_um),
    ).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT camera + INSERT event (albo żadne — rollback)
        cur = con.execute(
            "INSERT INTO camera(model_canon, pixel_um, is_mono, is_mono_source, "
            "raw_instrume, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (model_canon, pixel_um, is_mono, is_mono_source, raw_instrume, now),
        )
        camera_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="camera.upserted", target=f"camera:{camera_id}",
            now=now,
            payload={"model_canon": model_canon, "pixel_um": pixel_um,
                     "is_mono": is_mono, "is_mono_source": is_mono_source},
        )
    return camera_id, True
