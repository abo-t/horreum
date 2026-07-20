"""Jedna klinga w działaniu: zapis + emisja event w TEJ SAMEJ transakcji (schemat v2 po PF-2)."""
import json

import pytest

from horreum import db, repo
from horreum.resolve.cameras import camera_identity
from horreum.scan import Card

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
    """MM/MC/MD przy tym samym pixel_um=3.76 → trzy osobne kamery (model_canon = tożsamość;
    firsthand: dokładnie 3 kamery 2600)."""
    con = _fresh(tmp_path)
    for mc, mono, src in [("ASI2600MM", 1, "model"), ("ASI2600MC", 0, "bayerpat"),
                          ("ASI2600MD", 1, "model")]:
        repo.upsert_camera(con, model_canon=mc, pixel_um=3.76, is_mono=mono,
                           is_mono_source=src, raw_instrume="x", now=NOW)
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.upserted'").fetchone()[0] == 3
    con.close()


def test_upsert_camera_uzupelnia_piksel_cas(tmp_path):
    """PF-2 (R2#4/R3-c1): kamera powstała BEZ piksela (Sony masterflat bez XPIXSZ) → kolejne
    zeznanie z wartością UZUPEŁNIA pixel_um (CAS) + event(camera.pixel_set); trzecie z tą samą
    wartością = no-op bez eventu."""
    con = _fresh(tmp_path)
    cam_id, _ = repo.upsert_camera(con, model_canon="SONYA7RM3", pixel_um=None, is_mono=None,
                                   is_mono_source="review", raw_instrume="Sony", now=NOW)
    assert con.execute("SELECT pixel_um FROM camera WHERE id=?", (cam_id,)).fetchone()[0] is None
    id2, c2 = repo.upsert_camera(con, model_canon="SONYA7RM3", pixel_um=4.86, is_mono=None,
                                 is_mono_source="review", raw_instrume="Sony", now=NOW)
    assert (id2, c2) == (cam_id, False)
    assert con.execute("SELECT pixel_um FROM camera WHERE id=?", (cam_id,)).fetchone()[0] == 4.86
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.pixel_set'").fetchone()[0] == 1
    repo.upsert_camera(con, model_canon="SONYA7RM3", pixel_um=4.86, is_mono=None,
                       is_mono_source="review", raw_instrume="Sony", now=NOW)
    assert con.execute("SELECT count(*) FROM event WHERE verb='camera.pixel_set'").fetchone()[0] == 1
    con.close()


def test_upsert_camera_rozjazd_piksela_stan_pixel_conflict(tmp_path):
    """PF-2 (R3-c3): rozjazd wartości piksela → STAN pixel_conflict=1 (kolejka ze stanu) +
    event(camera.pixel_conflict) target camera: (RAZ, na przejściu 0→1 — re-skan nie mnoży);
    istniejąca wartość NIE jest nadpisywana."""
    con = _fresh(tmp_path)
    cam_id, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                   is_mono_source="model", raw_instrume="x", now=NOW)
    for _ in range(2):                                    # drugi przebieg nie mnoży eventów
        repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=9.99, is_mono=1,
                           is_mono_source="model", raw_instrume="x", now=NOW)
    row = con.execute("SELECT pixel_um, pixel_conflict FROM camera WHERE id=?", (cam_id,)).fetchone()
    assert (row["pixel_um"], row["pixel_conflict"]) == (3.76, 1)      # wartość nietknięta, stan=1
    ev = con.execute("SELECT target, payload FROM event WHERE verb='camera.pixel_conflict'").fetchall()
    assert len(ev) == 1 and ev[0]["target"] == f"camera:{cam_id}"
    payload = json.loads(ev[0]["payload"])
    assert (payload["pixel_existing"], payload["pixel_new"]) == (3.76, 9.99)
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
    """Reguła B + upsert: 'ASI294' (OSC bez sufiksu) i 'ZWO ASI294MC Pro' — oba 4.63 RGGB —
    dają ten sam model_canon 'ASI294MC' → JEDNA kamera po upsercie."""
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


# --- frame / location / header ---

def test_upsert_frame_tworzy_i_emituje(tmp_path):
    con = _fresh(tmp_path)
    fid, created = repo.upsert_frame(con, sha1_data="abc123", kind="light", filetype="fits",
                                     camera_id=None, now=NOW)
    assert created is True
    row = con.execute("SELECT sha1_data, sha1_data_uncomputable, kind, filetype "
                      "FROM frame WHERE id=?", (fid,)).fetchone()
    assert (row["sha1_data"], row["sha1_data_uncomputable"]) == ("abc123", 0)
    assert (row["kind"], row["filetype"]) == ("light", "fits")
    ev = con.execute("SELECT verb, target FROM event WHERE verb='frame.observed'").fetchone()
    assert ev["target"] == f"frame:{fid}"
    con.close()


def test_upsert_frame_degeneracja_flagowana(tmp_path):
    """Tożsamość nieobliczalna → sha1 pliku + sha1_data_uncomputable=1 (lekcja v3 dawcy)."""
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data="filehash", sha1_data_uncomputable=1,
                               kind="unknown", filetype="xisf", camera_id=None, now=NOW)
    row = con.execute("SELECT sha1_data_uncomputable FROM frame WHERE id=?", (fid,)).fetchone()
    assert row[0] == 1
    payload = json.loads(con.execute(
        "SELECT payload FROM event WHERE verb='frame.observed'").fetchone()[0])
    assert payload["uncomputable"] == 1
    con.close()


def test_upsert_frame_idempotentny_po_sha1_data_bez_zmiany_tozsamosci(tmp_path):
    """Drugie wystąpienie sha1_data → (id, False), kind ORYGINALNY zachowany (multi-location
    obsłuży add_location); bez drugiego eventu frame.observed."""
    con = _fresh(tmp_path)
    id1, c1 = repo.upsert_frame(con, sha1_data="abc", kind="light", filetype="fits",
                                camera_id=None, now=NOW)
    id2, c2 = repo.upsert_frame(con, sha1_data="abc", kind="flat", filetype="xisf",
                                camera_id=None, now=NOW)
    assert (c1, c2) == (True, False) and id1 == id2
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    assert con.execute("SELECT kind FROM frame WHERE id=?", (id1,)).fetchone()["kind"] == "light"
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.observed'").fetchone()[0] == 1
    con.close()


def test_add_location_multi_location_1N_z_faktami_kopii(tmp_path):
    """frame 1:N location: jeden frame, dwie różne ścieżki → dwie location z WŁASNYMI faktami
    kopii (file_sha1/size — writeback zmienia kopię, nie tożsamość); dwa eventy location.added."""
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data="abc", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    l1, c1 = repo.add_location(con, frame_id=fid, volume="?", path="A/x.fits", mtime=NOW,
                               file_sha1="f1", header_hash="h1", hdu_index=0, compressed=0,
                               size_bytes=100, now=NOW)
    l2, c2 = repo.add_location(con, frame_id=fid, volume="?", path="B/x.fits", mtime=NOW,
                               file_sha1="f2", header_hash="h2", hdu_index=0, compressed=0,
                               size_bytes=103, now=NOW)
    assert (c1, c2) == (True, True) and l1 != l2
    assert con.execute("SELECT count(*) FROM location WHERE frame_id=?", (fid,)).fetchone()[0] == 2
    rows = {r["path"]: r for r in con.execute(
        "SELECT path, file_sha1, size_bytes FROM location ORDER BY id")}
    assert rows["A/x.fits"]["file_sha1"] == "f1" and rows["B/x.fits"]["size_bytes"] == 103
    assert con.execute("SELECT count(*) FROM event WHERE verb='location.added'").fetchone()[0] == 2
    con.close()


def test_add_location_idempotentna_po_volume_path(tmp_path):
    """Ta sama (volume, path) → (id, False), bez duplikatu i bez drugiego eventu (idempotencja skanu)."""
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data="abc", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    l1, c1 = repo.add_location(con, frame_id=fid, volume="V", path="x.fits", now=NOW)
    l2, c2 = repo.add_location(con, frame_id=fid, volume="V", path="x.fits", now=NOW)
    assert (c1, c2) == (True, False) and l1 == l2
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM event WHERE verb='location.added'").fetchone()[0] == 1
    con.close()


def test_record_header_pola_gorace_cards_i_jeden_event(tmp_path):
    """Zeznanie = header + cards + JEDEN event w tej samej transakcji (brief §4.5)."""
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data="abc", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    cards = [Card("INSTRUME", 0, "ZWO ASI2600MM Pro", None, "str", None),
             Card("GAIN", 0, "100", 100.0, "int", "e/ADU"),
             Card("COMMENT", 0, "uwaga A", None, "str", None),
             Card("COMMENT", 1, "uwaga B", None, "str", None)]
    repo.record_header(con, frame_id=fid, raw_json='{"INSTRUME": "x"}', now=NOW, cards=cards,
                       xpixsz=3.76, exptime=300.0, gain="100", offset_adu=0,
                       instrume="ZWO ASI2600MM Pro", filter_raw=None)
    row = con.execute("SELECT raw_json, xpixsz, exptime, gain, offset_adu, instrume, filter_raw "
                      "FROM header WHERE frame_id=?", (fid,)).fetchone()
    assert (row["xpixsz"], row["exptime"]) == (3.76, 300.0)
    assert (row["gain"], row["offset_adu"]) == ("100", 0)            # gain TEXT; offset 0 zachowane
    assert row["instrume"] == "ZWO ASI2600MM Pro" and row["filter_raw"] is None
    assert row["raw_json"] == '{"INSTRUME": "x"}'
    assert con.execute("SELECT count(*) FROM cards WHERE frame_id=?", (fid,)).fetchone()[0] == 4
    c = con.execute("SELECT value_raw, value_num, value_type, comment FROM cards "
                    "WHERE frame_id=? AND keyword='GAIN'", (fid,)).fetchone()
    assert (c["value_raw"], c["value_num"], c["value_type"], c["comment"]) \
        == ("100", 100.0, "int", "e/ADU")
    assert sorted(r[0] for r in con.execute(
        "SELECT idx FROM cards WHERE frame_id=? AND keyword='COMMENT'", (fid,))) == [0, 1]
    assert con.execute("SELECT count(*) FROM event WHERE verb='header.recorded'").fetchone()[0] == 1
    con.close()


def test_flagi_review_emituja_eventy_bez_zmiany_stanu(tmp_path):
    """Trzy kanały sygnałów: frame.review (target sha1), camera.review i kind.unmapped
    (frame jest → target frame:id). Żaden nie tworzy/zmienia encji — tylko event."""
    con = _fresh(tmp_path)
    repo.flag_frame_review(con, sha1="deadbeef", path="C/bad.fits",
                           reason="ValueError: nie XISF monolithic", now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="abc", kind="unknown", filetype="fits",
                               camera_id=None, now=NOW)
    repo.flag_camera_review(con, frame_id=fid, reason="brak osi KAMERA (INSTRUME)", now=NOW)
    repo.flag_kind_unmapped(con, frame_id=fid, imagetyp="FlatWizard", now=NOW)

    fr = con.execute("SELECT target, reason FROM event WHERE verb='frame.review'").fetchone()
    assert fr["target"] == "sha1:deadbeef" and "monolithic" in fr["reason"]
    cr = con.execute("SELECT target FROM event WHERE verb='camera.review'").fetchone()
    assert cr["target"] == f"frame:{fid}"
    ku = con.execute("SELECT payload FROM event WHERE verb='kind.unmapped'").fetchone()
    assert json.loads(ku["payload"])["imagetyp"] == "FlatWizard"
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1   # flagi nie tworzą encji
    con.close()


# --- świeżość zeznania: refresh_location / rebind_location (brief §2) ---

def _frame_with_location(con, *, sha="d1", path="x.fits", header_hash="h1"):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume="V", path=path, mtime="t1",
                               file_sha1="f1", header_hash=header_hash, hdu_index=0,
                               compressed=0, size_bytes=100, now=NOW)
    return fid, lid


def test_refresh_location_bez_zmian_zero_eventow(tmp_path):
    con = _fresh(tmp_path)
    fid, lid = _frame_with_location(con)
    before = con.execute("SELECT count(*) FROM event").fetchone()[0]
    out = repo.refresh_location(con, location_id=lid, frame_id=fid, mtime="t1",
                                file_sha1="f1", header_hash="h1", hdu_index=0, compressed=0,
                                size_bytes=100, unreadable_since=None, now=NOW)
    assert out == {"facts": False, "header": False, "rederived": False}
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == before
    con.close()


def test_refresh_location_mtime_dlug_domkniety(tmp_path):
    """Dług „mtime po re-odczycie nieaktualizowany" (R2#7): zmiana mtime → UPDATE + JEDEN
    event(location.refreshed) z {before,after} TYLKO pól zmienionych."""
    con = _fresh(tmp_path)
    fid, lid = _frame_with_location(con)
    out = repo.refresh_location(con, location_id=lid, frame_id=fid, mtime="t2",
                                file_sha1="f1", header_hash="h1", hdu_index=0, compressed=0,
                                size_bytes=100, unreadable_since=None, now=NOW)
    assert out["facts"] is True and out["header"] is False
    assert con.execute("SELECT mtime FROM location WHERE id=?", (lid,)).fetchone()[0] == "t2"
    ev = con.execute("SELECT payload FROM event WHERE verb='location.refreshed'").fetchall()
    assert len(ev) == 1
    payload = json.loads(ev[0]["payload"])
    assert payload == {"mtime": {"before": "t1", "after": "t2"}}      # tylko pole zmienione
    con.close()


def test_refresh_location_header_hash_odswieza_zeznanie_i_pochodne(tmp_path):
    """R2#2 + R3-b2/b4 (writeback fitsmirror): zmiana header_hash → pełny re-record zeznania
    (raw_json + pola gorące + WYMIANA cards) + event(header.refreshed) ORAZ przeliczenie
    pochodnych frame'a (camera_id/kind) + event(frame.rederived). Last-read-wins."""
    con = _fresh(tmp_path)
    fid, lid = _frame_with_location(con)
    repo.record_header(con, frame_id=fid, raw_json='{"OBJECT": "M31"}', now=NOW,
                       cards=[Card("OBJECT", 0, "M31", None, "str", None)],
                       object_raw="M31", instrume=None)
    cam_id, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                   is_mono_source="model", raw_instrume="x", now=NOW)
    out = repo.refresh_location(
        con, location_id=lid, frame_id=fid, mtime="t2", file_sha1="f2", header_hash="h2",
        hdu_index=0, compressed=0, size_bytes=102, unreadable_since=None, now=NOW,
        raw_json='{"OBJECT": "M33"}',
        cards=[Card("OBJECT", 0, "M33", None, "str", None),
               Card("FILTER", 0, "Ha", None, "str", None)],
        hot_fields={"object_raw": "M33", "instrume": "ZWO ASI2600MM Pro", "filter_raw": "Ha"},
        camera_id=cam_id, kind="light")
    assert out == {"facts": True, "header": True, "rederived": True}
    h = con.execute("SELECT raw_json, object_raw, filter_raw FROM header WHERE frame_id=?",
                    (fid,)).fetchone()
    assert h["raw_json"] == '{"OBJECT": "M33"}' and h["object_raw"] == "M33"
    kws = sorted(r[0] for r in con.execute(
        "SELECT keyword FROM cards WHERE frame_id=?", (fid,)))
    assert kws == ["FILTER", "OBJECT"]                     # stare lustro WYMIENIONE, nie dopisane
    assert con.execute("SELECT value_raw FROM cards WHERE frame_id=? AND keyword='OBJECT'",
                       (fid,)).fetchone()[0] == "M33"
    hr = json.loads(con.execute(
        "SELECT payload FROM event WHERE verb='header.refreshed'").fetchone()[0])
    assert (hr["header_hash_before"], hr["header_hash_after"]) == ("h1", "h2")
    fr = con.execute("SELECT camera_id, kind FROM frame WHERE id=?", (fid,)).fetchone()
    assert (fr["camera_id"], fr["kind"]) == (cam_id, "light")
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.rederived'").fetchone()[0] == 1
    con.close()


def test_rebind_location_przepina_i_zostawia_stary_frame(tmp_path):
    """R3-b1 (podmiana treści): location przepięta na nową tożsamość + event(location.rebound)
    {frame_before, frame_after}; stary frame ZOSTAJE (append-only); idempotencja."""
    con = _fresh(tmp_path)
    fid1, lid = _frame_with_location(con)
    fid2, _ = repo.upsert_frame(con, sha1_data="d2", kind="master_light", filetype="xisf",
                                camera_id=None, now=NOW)
    assert repo.rebind_location(con, location_id=lid, frame_after=fid2, now=NOW) is True
    assert repo.rebind_location(con, location_id=lid, frame_after=fid2, now=NOW) is False
    assert con.execute("SELECT frame_id FROM location WHERE id=?", (lid,)).fetchone()[0] == fid2
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 2   # stary frame żyje
    ev = con.execute("SELECT target, payload FROM event WHERE verb='location.rebound'").fetchall()
    assert len(ev) == 1 and ev[0]["target"] == f"location:{lid}"
    assert json.loads(ev[0]["payload"]) == {"frame_before": fid1, "frame_after": fid2}
    con.close()


def test_refresh_location_unreadable_mtime_marker_i_review(tmp_path):
    """R3-b1 (#13): znana kopia nieczytelna (bajty bez zmian) → refresh mtime + MARKER
    `unreadable_since` (znacznik czytelności w STANIE) + event(frame.review „kopia nieczytelna");
    zwraca True; zero nowych frame'ów."""
    con = _fresh(tmp_path)
    fid, lid = _frame_with_location(con)
    assert repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                            mtime="t9", reason="OSError: NAS timeout", now=NOW) is True
    row = con.execute("SELECT mtime, unreadable_since FROM location WHERE id=?", (lid,)).fetchone()
    assert row["mtime"] == "t9" and row["unreadable_since"] == NOW      # marker = timestamp awarii
    ev = con.execute("SELECT target, reason FROM event WHERE verb='frame.review'").fetchone()
    assert ev["target"] == "sha1:d1" and "kopia nieczytelna" in ev["reason"]
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    con.close()


def test_refresh_location_unreadable_powtorka_cichy_noop(tmp_path):
    """D2/QUIET (#13): powtórna awaria bez zmiany mtime (marker już stoi) → `False`, BEZ drugiego
    eventu; marker trzyma PIERWSZY timestamp (idempotencja przez COALESCE — stan już alarmuje)."""
    con = _fresh(tmp_path)
    fid, lid = _frame_with_location(con)   # mtime="t1"
    assert repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                            mtime="t9", reason="OSError", now="n1") is True
    # druga awaria z TYM SAMYM mtime "t9" (już w bazie) → marker stoi → cichy no-op
    assert repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                            mtime="t9", reason="OSError", now="n2") is False
    assert con.execute("SELECT unreadable_since FROM location WHERE id=?",
                       (lid,)).fetchone()[0] == "n1"                    # PIERWSZY timestamp trzyma
    assert con.execute("SELECT count(*) FROM event WHERE verb='frame.review'").fetchone()[0] == 1
    con.close()


def test_refresh_location_udany_odczyt_gasi_marker(tmp_path):
    """#13: udany odczyt GASI marker `unreadable_since` NAWET gdy pozostałe fakty kopii identyczne
    (przejście markera jest w `_LOCATION_FACTS`, więc samo w sobie jest zmianą — inaczej early-return
    `not changed` nigdy by go nie zgasił). Ślad wyzdrowienia w payloadzie `location.refreshed`."""
    con = _fresh(tmp_path)
    fid, lid = _frame_with_location(con)   # mtime="t1", file_sha1="f1", header_hash="h1", ...
    # oznacz kopię nieczytelną (mtime bez zmiany "t1", ale marker był NULL → change; marker=NOW)
    repo.refresh_location_unreadable(con, location_id=lid, sha1_data="d1", path="x.fits",
                                     mtime="t1", reason="OSError", now=NOW)
    assert con.execute("SELECT unreadable_since FROM location WHERE id=?", (lid,)).fetchone()[0] == NOW
    # udany odczyt: unreadable_since=None, WSZYSTKIE inne fakty IDENTYCZNE jak przy add_location
    out = repo.refresh_location(con, location_id=lid, frame_id=fid, mtime="t1", file_sha1="f1",
                                header_hash="h1", hdu_index=0, compressed=0, size_bytes=100,
                                now="t2", unreadable_since=None)
    assert out["facts"] is True                                        # przejście markera = zmiana faktu
    assert con.execute("SELECT unreadable_since FROM location WHERE id=?", (lid,)).fetchone()[0] is None
    ev = con.execute("SELECT payload FROM event WHERE verb='location.refreshed'").fetchall()
    assert len(ev) == 1
    assert json.loads(ev[0]["payload"]) == {"unreadable_since": {"before": NOW, "after": None}}
    con.close()


# --- telescope / config ---

def test_propose_telescope_idempotentny_po_canonie_nocase(tmp_path):
    """Tożsamość = telescop_canon; idempotencja przez UNIQUE COLLATE NOCASE ('RC8' ≡ 'rc8' —
    JEDEN mechanizm foldowania, R2#8); casing wyświetlany = pierwszego wystąpienia."""
    con = _fresh(tmp_path)
    t1, c1 = repo.propose_telescope(con, telescop_canon="RC8", f_ratio_nominal=8.0,
                                    focal_nominal=1600, now=NOW)
    t2, c2 = repo.propose_telescope(con, telescop_canon="rc8", now=NOW)
    t3, c3 = repo.propose_telescope(con, telescop_canon="  RC8  ", now=NOW)   # strip w repo
    assert (c1, c2, c3) == (True, False, False) and t1 == t2 == t3
    row = con.execute("SELECT telescop_canon, status, label, f_ratio_nominal, focal_nominal "
                      "FROM telescope WHERE id=?", (t1,)).fetchone()
    assert row["telescop_canon"] == "RC8"                  # casing pierwszego wystąpienia
    assert (row["status"], row["label"]) == ("proposed", None)
    assert (row["f_ratio_nominal"], row["focal_nominal"]) == (8.0, 1600)
    assert con.execute("SELECT count(*) FROM event WHERE verb='telescope.proposed'").fetchone()[0] == 1
    con.close()


def test_propose_telescope_pusty_canon_ValueError(tmp_path):
    con = _fresh(tmp_path)
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            repo.propose_telescope(con, telescop_canon=bad, now=NOW)
    con.close()


def test_propose_config_i_assign_link_z_inwariantem(tmp_path):
    """propose_config idempotentny po UNIQUE(telescope,camera); assign_config linkuje frame.config_id
    (idempotentnie) i utrzymuje INWARIANT §1: config.camera_id == frame.camera_id."""
    con = _fresh(tmp_path)
    cam, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                is_mono_source="model", raw_instrume="x", now=NOW)
    tel, _ = repo.propose_telescope(con, telescop_canon="A140R", f_ratio_nominal=5.6,
                                    focal_nominal=784, now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="abc", kind="light", filetype="fits",
                               camera_id=cam, now=NOW)
    cfg1, cc1 = repo.propose_config(con, telescope_id=tel, camera_id=cam, now=NOW)
    cfg2, cc2 = repo.propose_config(con, telescope_id=tel, camera_id=cam, now=NOW)
    assert (cc1, cc2) == (True, False) and cfg1 == cfg2               # UNIQUE → jeden config
    assert repo.assign_config(con, frame_id=fid, config_id=cfg1, now=NOW) is True
    assert repo.assign_config(con, frame_id=fid, config_id=cfg1, now=NOW) is False   # idempotent no-op
    inv = con.execute("SELECT f.camera_id fcam, c.camera_id ccam FROM frame f "
                      "JOIN config c ON c.id = f.config_id WHERE f.id=?", (fid,)).fetchone()
    assert inv["fcam"] == inv["ccam"]                                 # INWARIANT §1
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.proposed'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.assigned'").fetchone()[0] == 1
    con.close()


def test_flag_config_review(tmp_path):
    con = _fresh(tmp_path)
    fid, _ = repo.upsert_frame(con, sha1_data="a", kind="master_flat", filetype="xisf",
                               camera_id=None, now=NOW)
    repo.flag_config_review(con, frame_id=fid, reason="brak osi do config (TELESCOP lub kamera)",
                            now=NOW)
    cr = con.execute("SELECT target, reason FROM event WHERE verb='config.review'").fetchone()
    assert cr["target"] == f"frame:{fid}" and "TELESCOP" in cr["reason"]
    con.close()


# --- obiekt / alias / filtr ---

def test_upsert_object_idempotentny_i_event(tmp_path):
    con = _fresh(tmp_path)
    o1, c1 = repo.upsert_object(con, canon="NGC4258", catalog="NGC", kind="deep_sky", now=NOW)
    o2, c2 = repo.upsert_object(con, canon="NGC4258", catalog="NGC", kind="deep_sky", now=NOW)
    assert (c1, c2) == (True, False) and o1 == o2
    assert con.execute("SELECT count(*) FROM object").fetchone()[0] == 1
    row = con.execute("SELECT canon, catalog, kind FROM object WHERE id=?", (o1,)).fetchone()
    assert (row["canon"], row["catalog"], row["kind"]) == ("NGC4258", "NGC", "deep_sky")
    assert con.execute("SELECT count(*) FROM event WHERE verb='object.upserted'").fetchone()[0] == 1
    con.close()


def test_add_object_alias_idempotentny_i_event(tmp_path):
    """Dwie formy surowe (NGC4258, M106) → ten sam obiekt; alias_norm UNIQUE, idempotentny."""
    con = _fresh(tmp_path)
    oid, _ = repo.upsert_object(con, canon="NGC4258", catalog="NGC", kind="deep_sky", now=NOW)
    a1, ac1 = repo.add_object_alias(con, alias_norm="M106", object_id=oid, source="catalog_xref", now=NOW)
    a2, ac2 = repo.add_object_alias(con, alias_norm="M106", object_id=oid, source="catalog_xref", now=NOW)
    repo.add_object_alias(con, alias_norm="NGC4258", object_id=oid, source="header", now=NOW)
    assert (ac1, ac2) == (True, False) and a1 == a2
    assert con.execute("SELECT count(*) FROM object_alias WHERE object_id=?", (oid,)).fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM event WHERE verb='object.aliased'").fetchone()[0] == 2
    con.close()


def test_assign_object_linkuje_i_idempotentny(tmp_path):
    con = _fresh(tmp_path)
    oid, _ = repo.upsert_object(con, canon="NGC4258", catalog="NGC", kind="deep_sky", now=NOW)
    fid, _ = repo.upsert_frame(con, sha1_data="a", kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    assert repo.assign_object(con, frame_id=fid, object_id=oid, object_source="catalog_xref", now=NOW) is True
    assert repo.assign_object(con, frame_id=fid, object_id=oid, object_source="catalog_xref", now=NOW) is False
    row = con.execute("SELECT object_id, object_source FROM frame WHERE id=?", (fid,)).fetchone()
    assert (row["object_id"], row["object_source"]) == (oid, "catalog_xref")
    assert con.execute("SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0] == 1
    con.close()


def test_flag_object_review_summary_jeden_event_z_licznoscia(tmp_path):
    """Delta obiektu ZBIORCZO: jeden event z licznością per object_raw (nie per-frame). Pusta → no-op."""
    con = _fresh(tmp_path)
    repo.flag_object_review_summary(con, [], now=NOW)                      # pusto → bez eventu
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == 0
    repo.flag_object_review_summary(con, [("Snapshot", 189), ("Mur", 207)], now=NOW)
    ev = con.execute("SELECT target, payload FROM event WHERE verb='object.review_summary'").fetchall()
    assert len(ev) == 1 and ev[0]["target"] == "frame:*"
    payload = json.loads(ev[0]["payload"])
    assert payload["distinct"] == 2 and payload["frames"] == 396
    assert ["Mur", 207] in payload["items"]
    con.close()


def test_backfill_filter_canon_bulk_jeden_event(tmp_path):
    """Backfill pochodnej filter_canon — jedna transakcja, JEDEN event zbiorczy; pusta → no-op."""
    con = _fresh(tmp_path)
    f1, _ = repo.upsert_frame(con, sha1_data="a", kind="light", filetype="fits",
                              camera_id=None, now=NOW)
    f2, _ = repo.upsert_frame(con, sha1_data="b", kind="light", filetype="fits",
                              camera_id=None, now=NOW)
    repo.backfill_filter_canon(con, [], now=NOW)                           # pusto → bez eventu
    assert con.execute("SELECT count(*) FROM event WHERE verb='filter.backfilled'").fetchone()[0] == 0
    repo.backfill_filter_canon(con, [(f1, "Ha"), (f2, "OIII")], now=NOW)
    assert con.execute("SELECT filter_canon FROM frame WHERE id=?", (f1,)).fetchone()[0] == "Ha"
    assert con.execute("SELECT filter_canon FROM frame WHERE id=?", (f2,)).fetchone()[0] == "OIII"
    ev = con.execute("SELECT payload FROM event WHERE verb='filter.backfilled'").fetchall()
    assert len(ev) == 1 and json.loads(ev[0]["payload"]) == {"count": 2}
    con.close()
