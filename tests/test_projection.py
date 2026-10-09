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
    """Preset „wbpp-feed" = (object_canon, teleskop, filter_canon); BRAK teleskopu → _UNSET."""
    con = db.open_db(str(tmp_path / "w.db"))
    fid, _ = _seed(con, r"R:\A\y.fits", filter_canon="OIII")
    proj = projection.plan(con, [fid], "wbpp-feed")
    assert proj.items[0].segments == ("_UNSET", "_UNSET", "OIII")
    con.close()


def test_plan_wbpp_feed_teleskop_coalesce_label_canon(tmp_path):
    """P2 (coalesce): teleskop NIENAZWANY (`label` NULL — stan 100% żywej bazy) → segment bierze
    `telescop_canon`, nie `_UNSET`; nazwany teleskop dalej wygrywa etykietą (ta sama reguła co
    `gui.queries.telescope_label`)."""
    con = db.open_db(str(tmp_path / "wc.db"))
    fid_a, _ = _seed(con, r"R:\A\a.fits", filter_canon="Ha")
    fid_b, _ = _seed(con, r"R:\A\b.fits", filter_canon="Ha")
    # Oś teleskopu wchodzi przez config (frame→config→telescope_canonical→telescope) — jak base_rows.
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) "
                "VALUES (1, 'SW 72ED', NULL, 'proposed', ?)", (NOW,))     # nienazwany — stan żywej bazy
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) "
                "VALUES (2, 'TS 130', 'Duzy 130', 'approved', ?)", (NOW,))
    con.execute("INSERT INTO camera (id, model_canon, created_at) VALUES (1, 'ASI', ?)", (NOW,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) "
                "VALUES (10, 1, 1, 'proposed', ?), (20, 2, 1, 'proposed', ?)", (NOW, NOW))
    con.execute("UPDATE frame SET config_id=10 WHERE id=?", (fid_a,))
    con.execute("UPDATE frame SET config_id=20 WHERE id=?", (fid_b,))
    con.commit()
    proj = projection.plan(con, [fid_a, fid_b], "wbpp-feed")
    segs = {it.frame_id: it.segments for it in proj.items}
    assert segs[fid_a] == ("_UNSET", "SW_72ED", "Ha")     # canon jako etykieta zastępcza
    assert segs[fid_b] == ("_UNSET", "Duzy_130", "Ha")    # nazwany → label
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


def test_segment_coalesce_pierwsza_niepusta_kolumna():
    """Spec-krotka = coalesce: pierwsza kolumna dająca NIEPUSTY segment wygrywa; dopiero wyczerpanie
    wszystkich daje `_UNSET` (P2 — `telescope_label`→`telescop_canon`)."""
    assert projection._segment({"a": "Duzy", "b": "SW 72ED"}, ("a", "b")) == "Duzy"
    assert projection._segment({"a": None, "b": "SW 72ED"}, ("a", "b")) == "SW_72ED"
    assert projection._segment({"a": "", "b": ".."}, ("a", "b")) == "_UNSET"   # ".." nie ratuje (anty-traversal)
    assert projection._segment(None, ("a", "b")) == "_UNSET"


# ============================================================ guard §0 (cel pod wykluczeniem)


def test_guard_wykluczenia_przepuszcza():
    projection._assert_excluded_segment(r"R:\ASTRO_\_WBPP\feed")
    projection._assert_excluded_segment(r"R:\ASTRO_\_Review")      # case-insensitive
    projection._assert_excluded_segment("/mnt/astro/_wbpp/x")      # POSIX separator


def test_guard_wykluczenia_odrzuca():
    with pytest.raises(ValueError, match="wykluczonego"):
        projection._assert_excluded_segment(r"R:\ASTRO_\LIGHTS")


def test_guard_wykluczenia_po_normalizacji_sciezki(tmp_path):
    """`..` za segmentem wykluczonym wyprowadza zapis poza wykluczenie - w surowym napisie `_WBPP`
    stoi, a system plików pisze do `LIGHTS`, czyli do wejścia skanu. Guard patrzy na ścieżkę po
    `normpath`; `..` wewnątrz wykluczenia (bez wyjścia z niego) dalej przechodzi. Apply odmawia
    PRZED utworzeniem czegokolwiek."""
    with pytest.raises(ValueError, match="wykluczonego"):
        projection._assert_excluded_segment(r"R:\ASTRO_\_WBPP\..\LIGHTS")
    zly = str(tmp_path / "_WBPP" / ".." / "LIGHTS")
    with pytest.raises(ValueError, match="wykluczonego"):
        projection._assert_excluded_segment(zly)
    projection._assert_excluded_segment(str(tmp_path / "_WBPP" / "a" / ".." / "b"))

    con = db.open_db(str(tmp_path / "g.db"))
    fid, _ = _seed_file(con, tmp_path, "g.fits", filter_canon="Ha")
    with pytest.raises(ValueError, match="wykluczonego"):
        projection.apply(projection.plan(con, [fid], "po-obiektach"), zly, do_apply=True, now=NOW)
    assert not (tmp_path / "LIGHTS").exists()
    con.close()


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


def test_apply_abort_niesie_kwarantanne_planu(monkeypatch, tmp_path):
    """Wynik CZĘŚCIOWY abortu niesie też `skipped` z planu — inaczej raport zawsze głosi
    „pominięto: 0", choćby plan miał klatki bez obecnej kopii."""
    con = db.open_db(str(tmp_path / "abs.db"))
    fid, _ = _seed_file(con, tmp_path, "h.fits", filter_canon="Ha")
    _seed(con, r"R:\A\gone.fits", present=0)                      # kwarantanna: brak obecnej kopii
    proj = projection.plan(con, [fid, fid + 1], "po-obiektach")
    monkeypatch.setattr(projection, "_verify_content", lambda *a, **k: False)
    with pytest.raises(projection.ProjectionAbort) as ei:
        projection.apply(proj, str(tmp_path / "_WBPP" / "feed"), do_apply=True, now=NOW)
    assert ei.value.result.counts.get("verify_bad") == 1
    assert ei.value.result.counts.get("skipped") == 1
    con.close()


def test_manifest_niesie_zestaw_segmentow(tmp_path):
    """Manifest zapisuje SEGMENTY, nie samą nazwę presetu: definicja layoutu (P2 coalesce) albo
    nazwanie teleskopu przez usera przesuwa katalogi — ponowne wydanie do tego samego korzenia
    zbudowałoby DRUGIE drzewo obok starego (te same i-węzły → WBPP liczyłby klatki dwa razy)."""
    con = db.open_db(str(tmp_path / "ms.db"))
    fid, _ = _seed_file(con, tmp_path, "i.fits", filter_canon="Ha")
    proj = projection.plan(con, [fid], "wbpp-feed")
    root = str(tmp_path / "_WBPP" / "feed")
    projection.apply(proj, root, do_apply=True, now=NOW)
    payload = json.loads(open(os.path.join(root, projection.MANIFEST_NAME), encoding="utf-8").read())
    assert payload["layout"] == "wbpp-feed"
    assert payload["segments"] == [["object_canon"], ["telescope_label", "telescop_canon"],
                                   ["filter_canon"]]
    con.close()


def test_dry_ostrzega_gdy_korzen_niesie_inny_uklad(tmp_path):
    """Resztka z recenzji P2: manifest niósł `segments` od pierwszego dnia, ale NIKT ich nie czytał.
    Sonda (DRY) ma ostrzec, że w korzeniu stoi drzewo o INNYM kształcie — ponowne wydanie dołoży
    drugie obok niego. Stare pozycje nie są `conflict` (leżą pod inną ścieżką), więc bez tego
    cross-checku liczniki wyglądają czysto. Ostrzeżenie, NIE blokada: `would-link` stoi."""
    con = db.open_db(str(tmp_path / "dr.db"))
    fid, _ = _seed_file(con, tmp_path, "d.fits", filter_canon="Ha")
    root = str(tmp_path / "_WBPP" / "drift")
    projection.apply(projection.plan(con, [fid], "wbpp-feed"), root, do_apply=True, now=NOW)

    proj = projection.plan(con, [fid], "po-obiektach")            # INNY układ do tego samego korzenia
    res = projection.apply(proj, root, do_apply=False, now=NOW)
    assert res.drift == "wbpp-feed: object_canon/telescope_label|telescop_canon/filter_canon"
    assert res.counts.get("would-link") == 1                     # ostrzega, nie blokuje

    # Ten sam układ = cisza; brak/uszkodzony manifest też (efemeryczny — user kasuje w Eksploratorze).
    same = projection.apply(projection.plan(con, [fid], "wbpp-feed"), root, do_apply=False, now=NOW)
    assert same.drift is None
    with open(os.path.join(root, projection.MANIFEST_NAME), "w", encoding="utf-8") as fh:
        fh.write("{niepoprawny json")
    assert projection.manifest_drift(root, "po-obiektach") is None
    assert projection.read_manifest(str(tmp_path / "_WBPP" / "nie-ma")) is None
    con.close()


# ============================================================ wydanie obiektu (`plan_object`)


def _osie(con):
    """Osie pod wydanie obiektu: dwie kamery mono/kolor + jedna nierozstrzygnięta, dwa teleskopy,
    trzy zestawy (config 10 A140R x mono, 20 RC8 x mono, 30 A140R x kolor), obiekt ze spacją
    w kanonie (segment przez `naming._sanitize`) i obiekt obcy."""
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) VALUES "
                "(1, 'ASI2600MM', 1, ?), (2, 'ASI2600MC', 0, ?), (3, 'ASIX', NULL, ?)", (NOW, NOW, NOW))
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) VALUES "
                "(1, 'A140R', NULL, 'proposed', ?), (2, 'RC8', NULL, 'proposed', ?)", (NOW, NOW))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES "
                "(10, 1, 1, 'proposed', ?), (20, 2, 1, 'proposed', ?), (30, 1, 2, 'proposed', ?)",
                (NOW, NOW, NOW))
    con.execute("INSERT INTO object (id, canon) VALUES (1, 'NGC 6992'), (2, 'M42')")
    con.commit()


def _klatka(con, tmp_path, name, *, kind, config_id=None, camera_id=1, object_id=None,
            filter_canon=None, date_obs="2024-03-01T23:00:00", exptime=300.0, present=True, sub="lib"):
    """PRAWDZIWY plik (`tmp_path/<sub>/<name>`, treść = nazwa → osobny i-węzeł) + frame + header +
    location. `present=False` = kopia zniknęła (kwarantanna planu)."""
    src = tmp_path / sub / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(f"{sub}/{name}".encode())
    cur = con.execute(
        "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, object_id, filter_canon, "
        "first_seen_at) VALUES (?, ?, 'fits', ?, ?, ?, ?, ?)",
        (f"{sub}/{name}", kind, camera_id, config_id, object_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning) "
                "VALUES (?, '{}', ?, ?, 1)", (fid, date_obs, exptime))
    con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, ?)",
                (fid, str(src), int(present)))
    con.commit()
    return fid


def _stan(con, light, master, relation):
    """Wiersz rodowodu wprost (STAN, nie derywacja - plan czyta `calibration`, nie liczy go)."""
    con.execute("INSERT INTO calibration (light_frame_id, master_frame_id, relation, asserted_by, "
                "confidence) VALUES (?, ?, ?, 'horreum', 'recipe')", (light, master, relation))
    con.commit()


@pytest.fixture
def obiekt(tmp_path):
    """Obiekt w czterech zestawach. A (cfg 10, mono): Ha z master flatem i darkiem, Ha bez darka,
    OIII bez mastera z surowymi z tej samej nocy (+ jeden surowy z odległej nocy), mono bez filtra
    (luka), Ha bez obecnej kopii. B (cfg 20): ten sam master dark co A (dark nie zależy od optyki).
    C (cfg 30, kolor): bez filtra, surowe OSC. Bez configu: kamera nierozstrzygnięta. Poza populacją:
    light wycofany, light zastąpiony, light obcego obiektu."""
    from horreum.calibration import run_calibration
    con = db.open_db(str(tmp_path / "obj.db"))
    _osie(con)
    k = lambda name, **kw: _klatka(con, tmp_path, name, **kw)          # noqa: E731
    ids = {
        "md1": k("md1.xisf", kind="master_dark"),
        "mf1": k("mf1.xisf", kind="master_flat", config_id=10, filter_canon="Ha"),
        "mf2": k("mf2.xisf", kind="master_flat", config_id=20, filter_canon="Ha", camera_id=1),
        "la1": k("la1.fits", kind="light", config_id=10, object_id=1, filter_canon="Ha"),
        "la2": k("la2.fits", kind="light", config_id=10, object_id=1, filter_canon="Ha"),
        "la3": k("la3.fits", kind="light", config_id=10, object_id=1, filter_canon="OIII"),
        "la4": k("la4.fits", kind="light", config_id=10, object_id=1),
        "la5": k("la5.fits", kind="light", config_id=10, object_id=1, filter_canon="Ha", present=False),
        "lb1": k("lb1.fits", kind="light", config_id=20, object_id=1, filter_canon="Ha"),
        "lc1": k("lc1.fits", kind="light", config_id=30, camera_id=2, object_id=1),
        "lx": k("lx.fits", kind="light", camera_id=3, object_id=1),
        "f1": k("f1.fits", kind="flat", config_id=10, filter_canon="OIII", date_obs="2024-03-02T05:30:00"),
        "f2": k("f2.fits", kind="flat", config_id=10, filter_canon="OIII", date_obs="2024-03-02T05:31:00"),
        "f_daleko": k("f_daleko.fits", kind="flat", config_id=10, filter_canon="OIII",
                      date_obs="2023-01-01T22:00:00"),
        "fc1": k("fc1.fits", kind="flat", config_id=30, camera_id=2, date_obs="2024-03-01T21:00:00"),
        "l_wycofany": k("lw.fits", kind="light", config_id=10, object_id=1, filter_canon="Ha"),
        "l_zastapiony": k("lz.fits", kind="light", config_id=10, object_id=1, filter_canon="Ha"),
        "l_obcy": k("lo.fits", kind="light", config_id=10, object_id=2, filter_canon="Ha"),
    }
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, ids["l_wycofany"]))
    con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (ids["la1"], ids["l_zastapiony"]))
    con.commit()
    run_calibration(con, now=NOW)                  # profile flatów: surowe OIII/OSC i mastery Ha
    for light in ("la1", "la2", "la5"):
        _stan(con, ids[light], ids["mf1"], "flat")
    _stan(con, ids["la1"], ids["md1"], "dark")
    _stan(con, ids["lb1"], ids["mf2"], "flat")
    _stan(con, ids["lb1"], ids["md1"], "dark")
    yield con, ids
    con.close()


def test_plan_object_drzewo_zestawy_role_filtry(obiekt):
    """Rozdział ZESTAWEM (WBPP grupuje po filtrze, nie po optyce - wspólny folder zmieszałby kamery),
    role LIGHT/MASTER/FLAT_RAW, filtr: `OSC` dla koloru bez filtra, `_UNSET` dla mono i kamery
    nierozstrzygniętej; master dark wspólny dla A i B stoi w OBU zestawach, w każdym raz."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    assert p.layout == projection.OBJECT_LAYOUT == "wbpp-obiekt"
    # Segmenty WZGLĘDEM korzenia obiektu - obiekt siedzi w `object_root`, nie w pozycji.
    pozycje = sorted((it.segments, it.frame_id) for it in p.items)
    oczekiwane = sorted([
        (("A140R_ASI2600MM", "LIGHT", "Ha"), i["la1"]),
        (("A140R_ASI2600MM", "LIGHT", "Ha"), i["la2"]),
        (("A140R_ASI2600MM", "LIGHT", "OIII"), i["la3"]),
        (("A140R_ASI2600MM", "LIGHT", "_UNSET"), i["la4"]),
        (("A140R_ASI2600MM", "MASTER", "dark"), i["md1"]),
        (("A140R_ASI2600MM", "MASTER", "flat"), i["mf1"]),
        (("A140R_ASI2600MM", "FLAT_RAW", "OIII"), i["f1"]),
        (("A140R_ASI2600MM", "FLAT_RAW", "OIII"), i["f2"]),
        (("RC8_ASI2600MM", "LIGHT", "Ha"), i["lb1"]),
        (("RC8_ASI2600MM", "MASTER", "dark"), i["md1"]),
        (("RC8_ASI2600MM", "MASTER", "flat"), i["mf2"]),
        (("A140R_ASI2600MC", "LIGHT", "OSC"), i["lc1"]),
        (("A140R_ASI2600MC", "FLAT_RAW", "OSC"), i["fc1"]),
        (("_UNSET", "LIGHT", "_UNSET"), i["lx"]),
    ])
    assert pozycje == oczekiwane
    # Przestrzeń OBJECTS: `po-obiektach` na tej samej karcie kładzie `<karta>/NGC_6992/<filtr>`, więc
    # wspólny folder obiektu dałby WBPP każdy light dwa razy (te same i-węzły, różne ścieżki).
    assert projection.object_root(r"R:\_WBPP\karta", p) == os.path.join(r"R:\_WBPP\karta", "OBJECTS", "NGC_6992")
    # Light bez obecnej kopii → kwarantanna (jak `plan()`); wycofany, zastąpiony i obcy - poza populacją.
    assert p.skipped == [(i["la5"], "brak obecnej kopii (wszystkie present=0)")]
    assert i["f_daleko"] not in {it.frame_id for it in p.items}   # inna noc, poza wyborem


def test_plan_object_info_per_zestaw(obiekt):
    """`info` = proweniencja dla żniw i treść podglądu: populacja per zestaw, godziny, mastery ze
    STANU, surowe z nocą, „bez flatu" (ani master, ani wybór surowych) z tokenami luki i „bez darka"."""
    con, i = obiekt
    info = projection.plan_object(con, 1).info
    assert (info["object_id"], info["object_canon"], info["config_id"], info["window_days"]) == \
        (1, "NGC 6992", None, 30)
    assert sorted(info["zestawy"]) == ["A140R_ASI2600MC", "A140R_ASI2600MM", "RC8_ASI2600MM", "_UNSET"]
    a = info["zestawy"]["A140R_ASI2600MM"]
    assert a == {
        "config_id": 10, "config_ids": [10], "lights": [i["la1"], i["la2"], i["la3"], i["la4"], i["la5"]],
        "hours": 0.42, "masters": {"dark": [i["md1"]], "flat": [i["mf1"]]},
        "flat_raw": [i["f1"], i["f2"]], "flat_raw_nights": ["2024-03-01"],
        "bez_flatu": [i["la4"]], "bez_darka": [i["la2"], i["la3"], i["la4"], i["la5"]],
        "pending": [], "flat_gaps": {"no_profile": 1}}
    b = info["zestawy"]["RC8_ASI2600MM"]
    assert (b["masters"], b["bez_flatu"], b["bez_darka"]) == ({"dark": [i["md1"]], "flat": [i["mf2"]]}, [], [])
    c = info["zestawy"]["A140R_ASI2600MC"]
    assert (c["flat_raw"], c["bez_flatu"], c["bez_darka"]) == ([i["fc1"]], [], [i["lc1"]])
    x = info["zestawy"]["_UNSET"]
    assert (x["config_id"], x["bez_flatu"], x["flat_gaps"]) == (None, [i["lx"]], {"incomplete_recipe": 1})
    for z in info["zestawy"].values():             # tokeny domykają „bez flatu" co do sztuki
        assert sum(z["flat_gaps"].values()) == len(z["bez_flatu"])
    json.dumps(info)                               # manifest: musi przejść przez JSON bez adaptera


def test_plan_object_pending_osobno_nie_bez_flatu(obiekt):
    """`pending` (master flat JEST w przepisie, rodowód go nie przeliczył) to osobna lista, nie
    „bez flatu": jedno kliknięcie w Dostawie to inna wiadomość niż zakup klatek. Light obiektu M42
    leży w profilu Ha z masterem `mf1`, a wiersza `calibration` nie ma."""
    con, i = obiekt
    z = projection.plan_object(con, 2).info["zestawy"]["A140R_ASI2600MM"]
    assert z["lights"] == [i["l_obcy"]] and z["pending"] == [i["l_obcy"]]
    assert (z["bez_flatu"], z["flat_gaps"], z["flat_raw"]) == ([], {}, [])
    assert z["bez_darka"] == [i["l_obcy"]]                  # dark to osobna oś - tu nadal brak


def test_plan_object_jeden_zestaw_i_okno(obiekt):
    """`config_id` zawęża populację do jednego zestawu; `window_days` dochodzi do wyboru surowych
    (okno 0 = tylko ta sama noc - noc świtowych flatów nadal JEST tą samą nocą)."""
    con, i = obiekt
    p = projection.plan_object(con, 1, config_id=20)
    assert list(p.info["zestawy"]) == ["RC8_ASI2600MM"] and p.info["config_id"] == 20
    assert {it.frame_id for it in p.items} == {i["lb1"], i["md1"], i["mf2"]}
    zero = projection.plan_object(con, 1, config_id=10, window_days=0)
    assert zero.info["zestawy"]["A140R_ASI2600MM"]["flat_raw"] == [i["f1"], i["f2"]]


def _teleskop_scalony_z_a140r(con):
    """Teleskop 3 scalony do A140R (1) + config 40 na tej samej kamerze co config 10: ta sama
    TOŻSAMOŚĆ zestawu (teleskop kanoniczny, kamera) pod innym `config_id` - stan z żywej bazy
    (`ED` scalony do `ED120R`)."""
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, merged_into, created_at) "
                "VALUES (3, 'A140R-bis', NULL, 'proposed', 1, ?)", (NOW,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) "
                "VALUES (40, 3, 1, 'proposed', ?)", (NOW,))
    con.commit()


def test_plan_object_ta_sama_tozsamosc_zestawu_jeden_folder(obiekt):
    """Config teleskopu scalonego z A140R przy tej samej kamerze to TEN SAM fizyczny zestaw: jeden
    folder (dwa dałyby w WBPP dwie integracje jednej optyki), `config_ids` niesie oba configi,
    `config_id` = reprezentant (najmniejszy id). Config tej tożsamości BEZ lightów nazwy nie zmienia;
    filtr `config_id` drugiego configu wydaje CAŁY zestaw, nie jego część."""
    con, i = obiekt
    _teleskop_scalony_z_a140r(con)
    przed = projection.plan_object(con, 1).info["zestawy"]
    assert "A140R_ASI2600MM" in przed and przed["A140R_ASI2600MM"]["config_ids"] == [10]

    con.execute("UPDATE frame SET config_id = 40 WHERE id = ?", (i["la2"],))
    con.commit()
    p = projection.plan_object(con, 1)
    z = p.info["zestawy"]["A140R_ASI2600MM"]
    assert (z["config_id"], z["config_ids"]) == (10, [10, 40])
    assert z["lights"] == [i["la1"], i["la2"], i["la3"], i["la4"], i["la5"]]
    assert not any("_cfg" in seg for seg in p.info["zestawy"])

    przez_40 = projection.plan_object(con, 1, config_id=40).info["zestawy"]
    assert list(przez_40) == ["A140R_ASI2600MM"] and przez_40["A140R_ASI2600MM"]["lights"] == z["lights"]


def test_plan_object_kolizja_etykiet_roznych_tozsamosci(obiekt):
    """Dwie RÓŻNE tożsamości o tej samej etykiecie (nazwa usera `A140R` na innym, nie scalonym
    teleskopie) NIE zlewają się w jeden folder: obie dostają `_cfg<reprezentant>`. Kolizję liczy
    tabela `config`, nie klatki - przyrostek stoi także wtedy, gdy drugi zestaw nie ma lightów,
    więc wycofanie ich nie przemianowuje folderu wydanego wcześniej. Reszta bez przyrostka."""
    con, i = obiekt
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) "
                "VALUES (4, 'A140R-ES', 'A140R', 'approved', ?)", (NOW,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) "
                "VALUES (50, 4, 1, 'proposed', ?)", (NOW,))
    con.commit()
    bez_lightow = projection.plan_object(con, 1).info["zestawy"]
    assert "A140R_ASI2600MM_cfg10" in bez_lightow and "RC8_ASI2600MM" in bez_lightow

    con.execute("UPDATE frame SET config_id = 50 WHERE id = ?", (i["la4"],))
    con.commit()
    zestawy = projection.plan_object(con, 1).info["zestawy"]
    assert zestawy["A140R_ASI2600MM_cfg10"]["config_ids"] == [10]
    assert (zestawy["A140R_ASI2600MM_cfg50"]["config_id"], zestawy["A140R_ASI2600MM_cfg50"]["lights"]) == \
        (50, [i["la4"]])
    assert "A140R_ASI2600MM" not in zestawy


def test_plan_object_kolizja_folderu_obiektu(obiekt):
    """`_segment` nie jest różnowartościowy (`NGC 6992` i `NGC_6992` → `NGC_6992`), a NTFS nie
    odróżnia wielkości liter (`M42` i `m42`) - drugi obiekt wydałby się do folderu pierwszego.
    Kolidujący segment dostaje `_obj<id>`, liczony po całej tabeli `object`; `object_root` czyta go
    z planu. Bez kolizji folder zostaje gołą nazwą."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    assert p.info["object_segment"] == "NGC_6992"
    con.execute("INSERT INTO object (id, canon) VALUES (3, 'NGC_6992'), (4, 'm42')")
    con.commit()
    p1, p2, p3 = (projection.plan_object(con, oid) for oid in (1, 2, 3))
    assert (p1.info["object_segment"], p2.info["object_segment"], p3.info["object_segment"]) == \
        ("NGC_6992_obj1", "M42_obj2", "NGC_6992_obj3")
    assert projection.object_root("K", p1) == os.path.join("K", "OBJECTS", "NGC_6992_obj1")
    assert projection.object_manifest(p1)["object_segment"] == "NGC_6992_obj1"


def test_plan_object_nieznany_obiekt_i_plan_nie_zna_ukladu_obiektu(obiekt):
    """EXPECT: nieznany obiekt to błąd, nie pusty plan. `wbpp-obiekt` nie jest układem kolumnowym -
    `plan()` dalej go odrzuca, a `LAYOUTS` go nie zna."""
    con, i = obiekt
    with pytest.raises(ValueError, match="nieznany obiekt"):
        projection.plan_object(con, 999)
    with pytest.raises(ValueError, match="nieznany layout"):
        projection.plan(con, [i["la1"]], "wbpp-obiekt")
    assert "wbpp-obiekt" not in projection.LAYOUTS


def test_object_manifest_kopia_info_i_odmowa_dla_perspektywy(obiekt):
    """Manifest obiektu = treść `info` (listy id), jako KOPIA - wołający dokłada etykietę bez ruszania
    planu. Plan perspektywy nie ma `info` → odmowa, nie pusty manifest."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    man = projection.object_manifest(p)
    assert man == p.info and man is not p.info
    man["zestawy"]["_UNSET"]["lights"].append(-1)
    man["etykieta"] = "test"
    assert -1 not in p.info["zestawy"]["_UNSET"]["lights"] and "etykieta" not in p.info
    with pytest.raises(ValueError, match="manifest obiektu"):
        projection.object_manifest(projection.plan(con, [i["la1"]], "po-obiektach"))


def _manifest(root):
    return json.loads(open(os.path.join(root, projection.MANIFEST_NAME), encoding="utf-8").read())


def _bez_ts(zestawy):
    return {seg: {k: v for k, v in z.items() if k != "ts"} for seg, z in zestawy.items()}


def test_apply_obiektu_drzewo_manifest_i_drift(obiekt, tmp_path):
    """Realne wydanie przez TĘ SAMĄ klingę (`apply`) do `object_root`: wspólny master dark jest
    hardlinkiem w obu zestawach, manifest leży w folderze obiektu i niesie kształt `wbpp-obiekt`
    oraz treść `object_manifest` (+ `ts` przy każdym zestawie). Ponowna sonda tym samym układem
    milczy; układ kolumnowy do tego samego korzenia dostaje ostrzeżenie (i odwrotnie)."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    root = projection.object_root(str(tmp_path / "_WBPP" / "karta"), p)
    res = projection.apply(p, root, do_apply=True, now=NOW, manifest=projection.object_manifest(p))
    assert res.counts == {"linked": len(p.items), "skipped": 1}
    md1 = os.path.join(str(tmp_path / "lib"), "md1.xisf")
    for zestaw in ("A140R_ASI2600MM", "RC8_ASI2600MM"):
        dst = os.path.join(str(tmp_path / "_WBPP" / "karta"), "OBJECTS", "NGC_6992", zestaw, "MASTER", "dark", "md1.xisf")
        assert os.stat(dst).st_ino == os.stat(md1).st_ino
    payload = _manifest(root)
    assert payload["layout"] == "wbpp-obiekt"
    assert payload["segments"] == [["zestaw"], ["rola"], ["filtr", "relacja"]]
    assert _bez_ts(payload["zestawy"]) == p.info["zestawy"] and payload["object_canon"] == "NGC 6992"
    assert {z["ts"] for z in payload["zestawy"].values()} == {NOW}

    assert projection.apply(p, root, do_apply=False).drift is None
    kolumnowy = projection.plan(con, [i["la1"]], "po-obiektach")
    assert projection.apply(kolumnowy, root, do_apply=False).drift == "wbpp-obiekt: zestaw/rola/filtr|relacja"

    root2 = str(tmp_path / "_WBPP" / "kolumny")
    projection.apply(kolumnowy, root2, do_apply=True, now=NOW)
    assert projection.manifest_drift(root2, "wbpp-obiekt") == "po-obiektach: object_canon/filter_canon"


def test_dwa_obiekty_na_jedna_karte_celu_dwa_manifesty(obiekt, tmp_path):
    """Obiekt B wydany na tę samą kartę celu co A nie nadpisuje proweniencji A: każdy ma korzeń
    `<cel>/<obiekt>` i własny, czytelny manifest."""
    con, i = obiekt
    cel = str(tmp_path / "_WBPP" / "karta")
    for oid in (1, 2):
        p = projection.plan_object(con, oid)
        projection.apply(p, projection.object_root(cel, p), do_apply=True, now=NOW,
                         manifest=projection.object_manifest(p))
    a, b = _manifest(os.path.join(cel, "OBJECTS", "NGC_6992")), _manifest(os.path.join(cel, "OBJECTS", "M42"))
    assert (a["object_id"], b["object_id"]) == (1, 2)
    assert "RC8_ASI2600MM" in a["zestawy"] and list(b["zestawy"]) == ["A140R_ASI2600MM"]
    assert not os.path.exists(os.path.join(cel, projection.MANIFEST_NAME))   # nic na poziomie karty


def test_manifest_obiektu_scala_zestawy_kolejnych_wydan(obiekt, tmp_path):
    """Wydanie TYLKO jednego zestawu nie kasuje proweniencji zestawu wydanego wcześniej - jego drzewo
    dalej leży w korzeniu obiektu. Stary wpis zostaje ze SWOIM `ts`; obcy obiekt w tym korzeniu
    (albo inny układ) jest nadpisywany jak dotąd."""
    con, i = obiekt
    cel = str(tmp_path / "_WBPP" / "karta")
    pierwszy = projection.plan_object(con, 1, config_id=10)
    root = projection.object_root(cel, pierwszy)
    projection.apply(pierwszy, root, do_apply=True, now="T1", manifest=projection.object_manifest(pierwszy))
    drugi = projection.plan_object(con, 1, config_id=20)
    projection.apply(drugi, root, do_apply=True, now="T2", manifest=projection.object_manifest(drugi))

    payload = _manifest(root)
    assert sorted(payload["zestawy"]) == ["A140R_ASI2600MM", "RC8_ASI2600MM"]
    assert payload["zestawy"]["A140R_ASI2600MM"]["ts"] == "T1"
    assert payload["zestawy"]["RC8_ASI2600MM"]["ts"] == "T2"
    assert (payload["ts"], payload["config_id"]) == ("T2", 20)       # nagłówek = bieżące wydanie
    assert _bez_ts(payload["zestawy"])["A140R_ASI2600MM"] == pierwszy.info["zestawy"]["A140R_ASI2600MM"]

    # Obce zeznanie w tym korzeniu (inny obiekt) nie jest scalane - nadpisanie jak dla każdego układu.
    obcy = dict(payload, object_id=999, zestawy={"OBCY": {"lights": [1], "ts": "T0"}})
    with open(os.path.join(root, projection.MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(obcy, fh)
    projection.apply(drugi, root, do_apply=True, now="T3", manifest=projection.object_manifest(drugi))
    assert list(_manifest(root)["zestawy"]) == ["RC8_ASI2600MM"]


def test_manifest_obiektu_zapomina_zestaw_skasowany_z_dysku(obiekt, tmp_path):
    """Stary wpis przeżywa scalenie TYLKO, gdy jego folder zestawu dalej stoi: user kasuje wydanie
    w Eksploratorze, a manifest pamiętający skasowane drzewo zeznawałby o linkach, których nie ma."""
    import shutil
    con, i = obiekt
    pierwszy = projection.plan_object(con, 1, config_id=10)
    root = projection.object_root(str(tmp_path / "_WBPP" / "karta"), pierwszy)
    projection.apply(pierwszy, root, do_apply=True, now="T1", manifest=projection.object_manifest(pierwszy))
    shutil.rmtree(os.path.join(root, "A140R_ASI2600MM"))
    drugi = projection.plan_object(con, 1, config_id=20)
    projection.apply(drugi, root, do_apply=True, now="T2", manifest=projection.object_manifest(drugi))
    assert list(_manifest(root)["zestawy"]) == ["RC8_ASI2600MM"]


def test_manifest_obiektu_po_anulowaniu_mowi_cancelled(obiekt, tmp_path):
    """Anulowane wydanie zostawia w drzewie część pozycji, a manifest niesie pełne listy planu - więc
    wpisy bieżącego wydania dostają `"cancelled": true` (i nadal `ts`). Wydanie domknięte tego klucza
    nie ma, a powtórka zestawu zdejmuje flagę. Układy kolumnowe po anulowaniu: bez nowego klucza."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    root = projection.object_root(str(tmp_path / "_WBPP" / "karta"), p)
    done = []
    res = projection.apply(p, root, do_apply=True, now="T1", manifest=projection.object_manifest(p),
                           progress=lambda *a: done.append(a), should_cancel=lambda: len(done) >= 1)
    assert res.cancelled and res.counts.get("linked") == 1
    zestawy = _manifest(root)["zestawy"]
    assert all(z["cancelled"] is True and z["ts"] == "T1" for z in zestawy.values())

    projection.apply(p, root, do_apply=True, now="T2", manifest=projection.object_manifest(p))
    assert not any("cancelled" in z for z in _manifest(root)["zestawy"].values())

    kolumnowy = projection.plan(con, [i["la1"], i["la2"]], "po-obiektach")
    root2 = str(tmp_path / "_WBPP" / "kolumny")
    res2 = projection.apply(kolumnowy, root2, do_apply=True, now=NOW, should_cancel=lambda: True)
    assert res2.cancelled
    assert list(_manifest(root2)) == ["layout", "segments", "root", "copy", "ts", "n_items", "counts"]


def test_apply_obiektu_kolizja_nazwy_pliku_daje_conflict(obiekt, tmp_path):
    """Dwie RÓŻNE klatki o tej samej nazwie pliku w jednym folderze: druga to `conflict` (jak
    w `wbpp-feed`) - klinga nie nadpisuje i nie zgaduje drugiej nazwy."""
    con, i = obiekt
    drugi = _klatka(con, tmp_path, "la1.fits", kind="light", config_id=10, object_id=1,
                    filter_canon="Ha", sub="inny")
    _stan(con, drugi, i["mf1"], "flat")
    p = projection.plan_object(con, 1, config_id=10)
    res = projection.apply(p, str(tmp_path / "_WBPP" / "kolizja"), do_apply=True, now=NOW)
    statusy = {r.frame_id: r.status for r in res.results}
    assert (statusy[i["la1"]], statusy[drugi]) == ("linked", "conflict")


def test_manifest_starych_ukladow_bajt_w_bajt(tmp_path):
    """Kształt manifestu układów kolumnowych bez zmian po wejściu `layout_segments`: ten sam zestaw
    kluczy w tej samej kolejności i ten sam tekst JSON co przed wydaniem obiektu."""
    con = db.open_db(str(tmp_path / "bb.db"))
    fid, _ = _seed_file(con, tmp_path, "bb.fits", filter_canon="Ha")
    for layout, segs in (("po-obiektach", [["object_canon"], ["filter_canon"]]),
                         ("wbpp-feed", [["object_canon"], ["telescope_label", "telescop_canon"],
                                        ["filter_canon"]])):
        root = str(tmp_path / "_WBPP" / layout)
        res = projection.apply(projection.plan(con, [fid], layout), root, do_apply=True, now=NOW)
        oczekiwany = {"layout": layout, "segments": segs, "root": root, "copy": False, "ts": NOW,
                      "n_items": 1, "counts": res.counts}
        tekst = open(os.path.join(root, projection.MANIFEST_NAME), encoding="utf-8").read()
        assert tekst == json.dumps(oczekiwany, ensure_ascii=False, indent=2)
    assert projection.layout_segments("po-obiektach") is projection.LAYOUTS["po-obiektach"]
    with pytest.raises(ValueError, match="nieznany layout"):
        projection.layout_segments("wymyslony")
    con.close()


# ============================================================ meta-test bramki zielony


def test_meta_test_klingi_przepuszcza_projekcje():
    """Bramka mutacji plików zielona z DWIEMA klingami: `projection.py` (DOOR) pominięty, reszta rdzenia
    czysta; `os.link` REALNIE w projekcji, `os.replace` w writebacku (klingi mają ostrza)."""
    import test_writeback_safety as wbs

    wbs.test_mutacja_plikow_tylko_w_writeback()
    wbs.test_klinga_projekcji_istnieje()
    wbs.test_klinga_plikow_istnieje()
