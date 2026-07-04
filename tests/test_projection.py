"""Testy TRZECIEJ KLINGI — `horreum.projection` (KROK 6 scalenia, brief PLAN_projekcje).

Pokrycie: `plan` (źródło linku `present_locations` R#1 / multi-present D-P5 / skipped-kwarantanna /
segmenty layoutu + `_UNSET` + sanityzacja + anty-traversal), guard `_assert_excluded_segment` (§0),
prymitywy `_link_to`/`_verify_content` na PRAWDZIWYCH plikach (`os.link` na `tmp_path`), pełny `apply`
DRY vs realny (hardlink + manifest + copy-mode + conflict-bez-nadpisania + idempotencja + skipped),
TWARDY ABORT sondy pierwszego linku (`ProjectionAbort`), oraz zielony meta-test bramki (projekcja jako
DOOR pominięta, `os.link` obecny). Rdzeń Qt-wolny — bez PySide6."""

from __future__ import annotations

import json
import os

import pytest

from horreum import db, projection, repo

NOW = "2026-07-04T00:00:00+00:00"


# ============================================================ seed (frame + location + fakty)


def _seed(con, path, *, volume="V", drive_letter="V:", present=1, filter_canon=None):
    """Frame (light) + location na `path`. `filter_canon`/`present` ustawiane bezpośrednio (pass
    zniknięć poza v1 — jak fixture_s8). Zwraca (frame_id, location_id)."""
    fid, _ = repo.upsert_frame(con, sha1_data="s:" + str(path), kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume=volume, drive_letter=drive_letter,
                               path=str(path), mtime="111", now=NOW)
    if filter_canon is not None:
        con.execute("UPDATE frame SET filter_canon=? WHERE id=?", (filter_canon, fid))
    if not present:
        con.execute("UPDATE location SET present=0 WHERE id=?", (lid,))
    con.commit()
    return fid, lid


def _seed_file(con, tmp_path, name, *, filter_canon=None, data=b"DATA"):
    """PRAWDZIWY plik w `tmp_path/lib` + frame/location nań (do testów `apply` z realnym `os.link`)."""
    src = tmp_path / "lib" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(data)
    fid, _ = _seed(con, str(src), filter_canon=filter_canon)
    return fid, str(src)


# ============================================================ plan (czysty odczyt DB)


def test_plan_present_i_skipped(tmp_path):
    """Źródło linku = OBECNA location; frame bez obecnej kopii → `skipped` (kwarantanna, nie item)."""
    con = db.open_db(str(tmp_path / "p.db"))
    fid_ok, _ = _seed(con, r"R:\A\ok.fits")
    fid_gone, _ = _seed(con, r"R:\A\gone.fits", present=0)
    proj = projection.plan(con, [fid_ok, fid_gone], "po-obiektach")
    assert [it.frame_id for it in proj.items] == [fid_ok]
    assert proj.items[0].src == r"R:\A\ok.fits" and proj.items[0].basename == "ok.fits"
    assert len(proj.skipped) == 1 and proj.skipped[0][0] == fid_gone
    con.close()


def test_plan_multi_present_pierwsza(tmp_path):
    """D-P5: frame z >1 obecną kopią → JEDEN link (pierwsza, MIN location.id), `multi_present++`."""
    con = db.open_db(str(tmp_path / "m.db"))
    fid, _ = _seed(con, r"R:\A\one.fits")
    repo.add_location(con, frame_id=fid, volume="V", path=r"R:\B\one.fits", mtime="111", now=NOW)
    proj = projection.plan(con, [fid], "po-obiektach")
    assert proj.multi_present == 1 and len(proj.items) == 1
    assert proj.items[0].src == r"R:\A\one.fits"          # pierwsza obecna
    con.close()


def test_plan_segmenty_filter_i_unset(tmp_path):
    """Segmenty layoutu z `base_rows`: object_canon NULL → `_UNSET`; filter_canon → segment."""
    con = db.open_db(str(tmp_path / "s.db"))
    fid, _ = _seed(con, r"R:\A\x.fits", filter_canon="Ha")
    proj = projection.plan(con, [fid], "po-obiektach")    # (object_canon, filter_canon)
    assert proj.items[0].segments == ("_UNSET", "Ha")
    con.close()


def test_plan_layout_wbpp_feed(tmp_path):
    """Preset „wbpp-feed" = (object_canon, telescope_label, filter_canon); brak teleskopu → _UNSET."""
    con = db.open_db(str(tmp_path / "w.db"))
    fid, _ = _seed(con, r"R:\A\y.fits", filter_canon="OIII")
    proj = projection.plan(con, [fid], "wbpp-feed")
    assert proj.items[0].segments == ("_UNSET", "_UNSET", "OIII")
    con.close()


def test_plan_nieznany_layout(tmp_path):
    con = db.open_db(str(tmp_path / "n.db"))
    fid, _ = _seed(con, r"R:\A\z.fits")
    with pytest.raises(ValueError, match="nieznany layout"):
        projection.plan(con, [fid], "wymyslony")
    con.close()


# ============================================================ _segment (sanityzacja + anty-traversal)


def test_segment_sanityzacja_unset_traversal():
    """SPOT `naming._sanitize` (spacje→'_'); pusty/None/brak-wiersza → `_UNSET`; `.`/`..` → `_UNSET`
    (anty-traversal — segment nie może wyjść poza korzeń projekcji)."""
    assert projection._segment({"c": "Heart of the Soul"}, "c") == "Heart_of_the_Soul"
    assert projection._segment({"c": None}, "c") == "_UNSET"
    assert projection._segment({"c": ""}, "c") == "_UNSET"
    assert projection._segment({"c": ".."}, "c") == "_UNSET"
    assert projection._segment({"c": "."}, "c") == "_UNSET"
    assert projection._segment(None, "c") == "_UNSET"


# ============================================================ guard §0 (cel pod wykluczeniem)


def test_guard_wykluczenia_przepuszcza():
    projection._assert_excluded_segment(r"R:\ASTRO_\_WBPP\feed")
    projection._assert_excluded_segment(r"R:\ASTRO_\_Review")      # case-insensitive
    projection._assert_excluded_segment("/mnt/astro/_wbpp/x")      # POSIX separator


def test_guard_wykluczenia_odrzuca():
    with pytest.raises(ValueError, match="wykluczonego"):
        projection._assert_excluded_segment(r"R:\ASTRO_\LIGHTS")


# ============================================================ prymitywy filesystemu (realne pliki)


def test_link_to_would_linked_exists_conflict(tmp_path):
    """DRY→would-link (nic nie tworzy); realny→linked (hardlink, ten sam i-węzeł); powtórka→exists;
    cel zajęty OBCYM plikiem→conflict (NIE nadpisany)."""
    src = tmp_path / "src.fits"
    src.write_bytes(b"DATA-A")
    dst = tmp_path / "out" / "src.fits"
    assert projection._link_to(str(src), str(dst), do_apply=False, copy=False) == ("would-link", None)
    assert not dst.exists()                                       # DRY nic nie tworzy
    st, reason = projection._link_to(str(src), str(dst), do_apply=True, copy=False)
    assert st == "linked" and reason is None and dst.exists()
    assert os.stat(str(src)).st_ino == os.stat(str(dst)).st_ino  # prawdziwy hardlink
    assert projection._link_to(str(src), str(dst), do_apply=True, copy=False) == ("exists", None)
    foreign = tmp_path / "out2" / "src.fits"
    foreign.parent.mkdir()
    foreign.write_bytes(b"OBCY")
    st, _ = projection._link_to(str(src), str(foreign), do_apply=True, copy=False)
    assert st == "conflict" and foreign.read_bytes() == b"OBCY"   # nietknięty


def test_verify_content_dobry_zly(tmp_path):
    """Sonda: prawdziwy hardlink → True; osobny plik (inny i-węzeł, choćby ta sama treść) → False."""
    src = tmp_path / "v.fits"
    src.write_bytes(b"HELLO" * 100)
    good = tmp_path / "good.fits"
    os.link(str(src), str(good))
    assert projection._verify_content(str(src), str(good)) is True
    bad = tmp_path / "bad.fits"
    bad.write_bytes(b"HELLO" * 100)                              # osobny i-węzeł
    assert projection._verify_content(str(src), str(bad)) is False


# ============================================================ apply (DRY / realny / manifest)


def test_apply_dry_nie_tworzy(tmp_path):
    con = db.open_db(str(tmp_path / "d.db"))
    fid, _ = _seed_file(con, tmp_path, "a.fits", filter_canon="Ha")
    proj = projection.plan(con, [fid], "po-obiektach")
    root = str(tmp_path / "_WBPP" / "feed")
    res = projection.apply(proj, root, do_apply=False)
    assert res.counts.get("would-link") == 1 and res.do_apply is False
    assert not os.path.exists(root)                              # DRY: zero tworzenia
    con.close()


def test_apply_realny_hardlink_i_manifest(tmp_path):
    con = db.open_db(str(tmp_path / "r.db"))
    fid, src = _seed_file(con, tmp_path, "b.fits", filter_canon="Ha", data=b"REAL" * 50)
    proj = projection.plan(con, [fid], "po-obiektach")
    root = str(tmp_path / "_WBPP" / "feed")
    res = projection.apply(proj, root, do_apply=True, now=NOW,
                           manifest={"perspektywa": "test", "volume": "V"})
    assert res.counts.get("linked") == 1
    dst = os.path.join(root, "_UNSET", "Ha", "b.fits")
    assert os.path.exists(dst)
    assert os.stat(src).st_ino == os.stat(dst).st_ino           # prawdziwy hardlink
    man = os.path.join(root, projection.MANIFEST_NAME)
    payload = json.loads(open(man, encoding="utf-8").read())
    assert payload["layout"] == "po-obiektach" and payload["counts"]["linked"] == 1
    assert payload["perspektywa"] == "test" and payload["ts"] == NOW and payload["volume"] == "V"
    con.close()


def test_apply_copy_mode(tmp_path):
    """Tryb kopii (D-P2): `shutil.copy2` — plik istnieje, INNY i-węzeł (kopia), status linked, ZERO abortu."""
    con = db.open_db(str(tmp_path / "c.db"))
    fid, src = _seed_file(con, tmp_path, "c.fits", data=b"COPYME")
    proj = projection.plan(con, [fid], "po-obiektach")
    root = str(tmp_path / "_Review" / "copies")
    res = projection.apply(proj, root, do_apply=True, copy=True, now=NOW)
    assert res.counts.get("linked") == 1
    dst = os.path.join(root, "_UNSET", "_UNSET", "c.fits")
    assert os.path.exists(dst) and open(dst, "rb").read() == b"COPYME"
    assert os.stat(src).st_ino != os.stat(dst).st_ino          # kopia, nie hardlink
    con.close()


def test_apply_root_bez_wykluczenia_raises(tmp_path):
    con = db.open_db(str(tmp_path / "x.db"))
    fid, _ = _seed_file(con, tmp_path, "d.fits")
    proj = projection.plan(con, [fid], "po-obiektach")
    with pytest.raises(ValueError, match="wykluczonego"):
        projection.apply(proj, str(tmp_path / "LIGHTS"), do_apply=True, now=NOW)
    con.close()


def test_apply_skipped_frame(tmp_path):
    con = db.open_db(str(tmp_path / "s.db"))
    fid, _ = _seed(con, r"R:\A\gone.fits", present=0)
    proj = projection.plan(con, [fid], "po-obiektach")
    res = projection.apply(proj, str(tmp_path / "_WBPP"), do_apply=True, now=NOW)
    assert res.counts.get("skipped") == 1 and res.counts.get("linked") is None
    con.close()


def test_apply_idempotentny(tmp_path):
    con = db.open_db(str(tmp_path / "i.db"))
    fid, _ = _seed_file(con, tmp_path, "e.fits", filter_canon="Ha")
    proj = projection.plan(con, [fid], "po-obiektach")
    root = str(tmp_path / "_WBPP" / "feed")
    projection.apply(proj, root, do_apply=True, now=NOW)
    res2 = projection.apply(proj, root, do_apply=True, now=NOW)
    assert res2.counts.get("exists") == 1 and "linked" not in res2.counts
    con.close()


def test_apply_conflict_nie_nadpisuje(tmp_path):
    con = db.open_db(str(tmp_path / "cf.db"))
    fid, _ = _seed_file(con, tmp_path, "f.fits", filter_canon="Ha", data=b"REAL")
    proj = projection.plan(con, [fid], "po-obiektach")
    root = str(tmp_path / "_WBPP" / "feed")
    dst = os.path.join(root, "_UNSET", "Ha", "f.fits")
    os.makedirs(os.path.dirname(dst))
    with open(dst, "wb") as fh:
        fh.write(b"OBCY-NIE-RUSZAC")
    res = projection.apply(proj, root, do_apply=True, now=NOW)
    assert res.counts.get("conflict") == 1
    assert open(dst, "rb").read() == b"OBCY-NIE-RUSZAC"         # cel nietknięty
    con.close()


def test_apply_abort_sonda_pierwszego_linku(monkeypatch, tmp_path):
    """Sonda pierwszego linku False (symulacja: SMB dał kopię) → `ProjectionAbort`, częściowy wynik
    z 1 `verify_bad`, manifest NIE zapisany."""
    con = db.open_db(str(tmp_path / "ab.db"))
    fid, _ = _seed_file(con, tmp_path, "g.fits", filter_canon="Ha")
    proj = projection.plan(con, [fid], "po-obiektach")
    monkeypatch.setattr(projection, "_verify_content", lambda *a, **k: False)
    root = str(tmp_path / "_WBPP" / "feed")
    with pytest.raises(projection.ProjectionAbort) as ei:
        projection.apply(proj, root, do_apply=True, now=NOW)
    assert ei.value.result.counts.get("verify_bad") == 1
    assert not os.path.exists(os.path.join(root, projection.MANIFEST_NAME))  # abort przed manifestem
    con.close()


# ============================================================ meta-test bramki zielony


def test_meta_test_klingi_przepuszcza_projekcje():
    """Bramka mutacji plików zielona z DWIEMA klingami: `projection.py` (DOOR) pominięty, reszta rdzenia
    czysta; `os.link` REALNIE w projekcji, `os.replace` w writebacku (klingi mają ostrza)."""
    import test_writeback_safety as wbs

    wbs.test_mutacja_plikow_tylko_w_writeback()
    wbs.test_klinga_projekcji_istnieje()
    wbs.test_klinga_plikow_istnieje()
