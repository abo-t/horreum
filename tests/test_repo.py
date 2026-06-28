"""Jedna klinga w działaniu: zapis + emisja event w TEJ SAMEJ transakcji."""
import json

from horreum import db, repo
from horreum.resolve.cameras import camera_identity

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


def test_camera_identity_zasila_upsert_camera(tmp_path):
    """Wertykał §4.3 (bez warstwy frame): zeznanie nagłówka → camera_identity → upsert_camera.
    Pola tożsamości wpadają 1:1; powstaje kamera + event."""
    con = _fresh(tmp_path)
    ident = camera_identity({"INSTRUME": "ZWO ASI2600MM Pro", "XPIXSZ": 3.76})
    cam_id, created = repo.upsert_camera(
        con, model_canon=ident.model_canon, pixel_um=ident.pixel_um,
        is_mono=ident.is_mono, is_mono_source=ident.is_mono_source,
        raw_instrume=ident.raw_instrume, now=NOW)
    assert created is True
    row = con.execute(
        "SELECT model_canon, pixel_um, is_mono, is_mono_source FROM camera WHERE id=?",
        (cam_id,)).fetchone()
    assert (row["model_canon"], row["pixel_um"], row["is_mono"], row["is_mono_source"]) \
        == ("ASI2600MM", 3.76, 1, "model")
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.upserted'").fetchone()[0] == 1
    con.close()


def test_dwa_warianty_294_scalaja_sie_w_jedna_kamere(tmp_path):
    """Reguła B + upsert (§5.3): 'ASI294' (OSC bez sufiksu) i 'ZWO ASI294MC Pro' — oba 4.63 RGGB —
    dają ten sam model_canon 'ASI294MC' → JEDNA kamera po upsercie. Odwrotność testu 3 kamer 2600:
    dwa różne stringi wejściowe → jedna oś (a nie rozbicie ASI294/ASI294MC na dwie)."""
    con = _fresh(tmp_path)
    for instrume in ("ASI294", "ZWO ASI294MC Pro"):
        ident = camera_identity({"INSTRUME": instrume, "XPIXSZ": 4.63, "BAYERPAT": "RGGB"})
        assert ident.model_canon == "ASI294MC"
        repo.upsert_camera(
            con, model_canon=ident.model_canon, pixel_um=ident.pixel_um,
            is_mono=ident.is_mono, is_mono_source=ident.is_mono_source,
            raw_instrume=ident.raw_instrume, now=NOW)
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.upserted'").fetchone()[0] == 1
    con.close()
