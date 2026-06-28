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


# --- frame / location / header (§Etap 4) ---

def test_upsert_frame_tworzy_i_emituje(tmp_path):
    con = _fresh(tmp_path)
    fid, created = repo.upsert_frame(con, sha1="abc123", kind="light", filetype="fits",
                                     size_bytes=1000, camera_id=None, now=NOW)
    assert created is True
    row = con.execute("SELECT kind, filetype, size_bytes FROM frame WHERE id=?", (fid,)).fetchone()
    assert (row["kind"], row["filetype"], row["size_bytes"]) == ("light", "fits", 1000)
    ev = con.execute("SELECT verb, target FROM event WHERE verb='frame.observed'").fetchone()
    assert ev["target"] == f"frame:{fid}"
    con.close()


def test_upsert_frame_idempotentny_po_sha1_bez_zmiany_tozsamosci(tmp_path):
    """Drugie wystąpienie sha1 → (id, False), kind ORYGINALNY zachowany (multi-location obsłuży
    add_location); bez drugiego eventu frame.observed."""
    con = _fresh(tmp_path)
    id1, c1 = repo.upsert_frame(con, sha1="abc", kind="light", filetype="fits",
                                size_bytes=1, camera_id=None, now=NOW)
    id2, c2 = repo.upsert_frame(con, sha1="abc", kind="flat", filetype="xisf",
                                size_bytes=2, camera_id=None, now=NOW)
    assert (c1, c2) == (True, False) and id1 == id2
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    assert con.execute("SELECT kind FROM frame WHERE id=?", (id1,)).fetchone()["kind"] == "light"
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.observed'").fetchone()[0] == 1
    con.close()


def test_add_location_multi_location_1N(tmp_path):
    """frame 1:N location (SYNTETYCZNY — 0 naturalnych duplikatów sha1): jeden frame, dwie różne
    ścieżki → dwie location; dwa eventy location.added."""
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1="abc", kind="light", filetype="fits",
                               size_bytes=1, camera_id=None, now=NOW)
    l1, c1 = repo.add_location(con, frame_id=fid, volume="?", path="A/x.fits", mtime=NOW, now=NOW)
    l2, c2 = repo.add_location(con, frame_id=fid, volume="?", path="B/x.fits", mtime=NOW, now=NOW)
    assert (c1, c2) == (True, True) and l1 != l2
    assert con.execute("SELECT count(*) FROM location WHERE frame_id=?", (fid,)).fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM event WHERE verb='location.added'").fetchone()[0] == 2
    con.close()


def test_add_location_idempotentna_po_volume_path(tmp_path):
    """Ta sama (volume, path) → (id, False), bez duplikatu i bez drugiego eventu (idempotencja skanu)."""
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1="abc", kind="light", filetype="fits",
                               size_bytes=1, camera_id=None, now=NOW)
    l1, c1 = repo.add_location(con, frame_id=fid, volume="V", path="x.fits", now=NOW)
    l2, c2 = repo.add_location(con, frame_id=fid, volume="V", path="x.fits", now=NOW)
    assert (c1, c2) == (True, False) and l1 == l2
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM event WHERE verb='location.added'").fetchone()[0] == 1
    con.close()


def test_record_header_pola_gorace_raw_json_i_event(tmp_path):
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1="abc", kind="light", filetype="fits",
                               size_bytes=1, camera_id=None, now=NOW)
    repo.record_header(con, frame_id=fid, raw_json='{"INSTRUME": "x"}', now=NOW,
                       xpixsz=3.76, exptime=300.0, gain="100", offset_adu=0,
                       instrume="ZWO ASI2600MM Pro", filter_raw=None)
    row = con.execute("SELECT raw_json, xpixsz, exptime, gain, offset_adu, instrume, filter_raw, "
                      "focratio_norm FROM header WHERE frame_id=?", (fid,)).fetchone()
    assert (row["xpixsz"], row["exptime"]) == (3.76, 300.0)
    assert (row["gain"], row["offset_adu"]) == ("100", 0)            # gain TEXT; offset 0 zachowane
    assert row["instrume"] == "ZWO ASI2600MM Pro" and row["filter_raw"] is None
    assert row["raw_json"] == '{"INSTRUME": "x"}' and row["focratio_norm"] is None  # backfill §Etap 5
    assert con.execute("SELECT count(*) FROM event WHERE verb='header.recorded'").fetchone()[0] == 1
    con.close()


def test_flagi_review_emituja_eventy_bez_zmiany_stanu(tmp_path):
    """Trzy kanały sygnałów: frame.review (brak frame → target sha1), camera.review i kind.unmapped
    (frame jest → target frame:id). Żaden nie tworzy/zmienia encji — tylko event."""
    con = _fresh(tmp_path)
    repo.flag_frame_review(con, sha1="deadbeef", path="C/bad.fits",
                           reason="ValueError: nie XISF monolithic", now=NOW)
    fid, _ = repo.upsert_frame(con, sha1="abc", kind="unknown", filetype="fits",
                               size_bytes=1, camera_id=None, now=NOW)
    repo.flag_camera_review(con, frame_id=fid, reason="brak osi KAMERA (INSTRUME/XPIXSZ)", now=NOW)
    repo.flag_kind_unmapped(con, frame_id=fid, imagetyp="FlatWizard", now=NOW)

    fr = con.execute("SELECT target, reason FROM event WHERE verb='frame.review'").fetchone()
    assert fr["target"] == "sha1:deadbeef" and "monolithic" in fr["reason"]
    cr = con.execute("SELECT target FROM event WHERE verb='camera.review'").fetchone()
    assert cr["target"] == f"frame:{fid}"
    ku = con.execute("SELECT payload FROM event WHERE verb='kind.unmapped'").fetchone()
    assert json.loads(ku["payload"])["imagetyp"] == "FlatWizard"
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1   # flagi nie tworzą encji
    con.close()
