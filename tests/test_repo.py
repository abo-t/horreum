"""Jedna klinga w działaniu: zapis + emisja event w TEJ SAMEJ transakcji."""
import json

from horreum import db, repo

NOW = "2026-06-28T12:00:00"


def _fresh(tmp_path):
    return db.open_db(str(tmp_path / "h.db"))


def test_upsert_camera_tworzy_i_emituje_event(tmp_path):
    con = _fresh(tmp_path)
    cam_id, created = repo.upsert_camera(
        con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
        is_mono_source="model", raw_instrume="ZWO ASI2600MM Pro", now=NOW)
    assert created is True
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 1

    ev = con.execute("SELECT actor, verb, target, payload FROM event").fetchall()
    assert len(ev) == 1
    assert ev[0]["verb"] == "camera.upserted"
    assert ev[0]["target"] == f"camera:{cam_id}"
    assert json.loads(ev[0]["payload"])["model_canon"] == "ASI2600MM"
    con.close()


def test_upsert_camera_idempotentny_bez_duplikatu_i_bez_eventu(tmp_path):
    con = _fresh(tmp_path)
    id1, c1 = repo.upsert_camera(
        con, model_canon="ASI2600MC", pixel_um=3.76, is_mono=0,
        is_mono_source="bayerpat", raw_instrume="ZWO ASI2600MC Pro", now=NOW)
    id2, c2 = repo.upsert_camera(
        con, model_canon="ASI2600MC", pixel_um=3.76, is_mono=0,
        is_mono_source="bayerpat", raw_instrume="ZWO ASI2600MC Pro", now=NOW)
    assert (c1, c2) == (True, False) and id1 == id2
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == 1   # brak eventu na no-op
    con.close()


def test_trzy_kamery_2600_rozne_model_canon(tmp_path):
    """MM/MC/MD przy tym samym pixel_um=3.76 → trzy osobne kamery (model_canon rozróżnia
    warianty w obrębie modelu; firsthand: dokładnie 3 kamery 2600, §5.3)."""
    con = _fresh(tmp_path)
    for mc, mono, src in [("ASI2600MM", 1, "model"), ("ASI2600MC", 0, "bayerpat"),
                          ("ASI2600MD", 1, "model")]:
        repo.upsert_camera(con, model_canon=mc, pixel_um=3.76, is_mono=mono,
                           is_mono_source=src, raw_instrume="x", now=NOW)
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.upserted'").fetchone()[0] == 3
    con.close()
