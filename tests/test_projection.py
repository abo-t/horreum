"""Testy TRZECIEJ KLINGI — `horreum.projection` (KROK 6 scalenia, brief PLAN_projekcje).

Pokrycie: `plan` (źródło linku `present_locations` R#1 / multi-present D-P5 / skipped-kwarantanna /
segmenty layoutu + `_UNSET` + sanityzacja + anty-traversal), guard `_assert_excluded_segment` (§0),
prymitywy `_link_to`/`_verify_content`/`_same_content` na PRAWDZIWYCH plikach (`os.link` na
`tmp_path`; w trybie kopii kopia z wydania = `exists`: rozmiar + czas + prefiks), pełny `apply`
DRY vs realny (hardlink + manifest + copy-mode + conflict-bez-nadpisania + idempotencja + skipped),
TWARDY ABORT sondy pierwszego linku (`ProjectionAbort`), klinga kopii mastera żniw (`copy_master`:
publikacja bez `.part`, `verify_bad`, `conflict` bez nadpisania, wyścig przed publikacją, leżący `.part`,
`fsync` przed audytem, rodzic celu będący plikiem, źródło tylko-do-odczytu, guard segmentu `CALIBRATION`)
i `write_harvest_manifest` (plik na bieg, bez nadpisania), oraz zielony meta-test bramki (projekcja jako
DOOR pominięta, `os.link` obecny). Rdzeń Qt-wolny — bez PySide6."""

from __future__ import annotations

import json
import os

import pytest

from horreum import db, hashing, projection, repo
from horreum.scan import EXCLUDED_DIR_NAMES

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


def _kopia(tmp_path, nazwa, dane):
    """Źródło + jego kopia `shutil.copy2` (bajty i czas modyfikacji) - stan celu po wydaniu kopią."""
    import shutil

    src = tmp_path / "lib" / nazwa
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(dane)
    dst = tmp_path / "_WBPP" / nazwa
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return src, dst


def _przesun_mtime(path, o_sekund):
    st = os.stat(str(path))
    os.utime(str(path), ns=(st.st_atime_ns, st.st_mtime_ns + int(o_sekund * 1_000_000_000)))


def test_link_to_kopia_z_wydania_to_exists_w_trybie_kopii(tmp_path):
    """Kopia `copy2` (inny i-węzeł, ten sam rozmiar, czas i treść) w trybie kopii = `exists`, w DRY
    i przy wydaniu, i NIC nie jest nadpisane. Tryb hardlinków bez zmian: ta sama kopia to obcy plik
    (`conflict`). Czas różny o mniej niż ziarno FAT/exFAT (2 s) dalej jest tą samą kopią."""
    src, dst = _kopia(tmp_path, "k.fits", b"NAGLOWEK" + b"X" * 100_000)
    assert os.stat(str(src)).st_ino != os.stat(str(dst)).st_ino
    assert projection._link_to(str(src), str(dst), do_apply=False, copy=True) == ("exists", None)
    assert projection._link_to(str(src), str(dst), do_apply=True, copy=True) == ("exists", None)
    st, reason = projection._link_to(str(src), str(dst), do_apply=False, copy=False)
    assert st == "conflict" and "i-węzłem" in reason             # hardlinki: bez zmian
    _przesun_mtime(dst, 1.5)                                       # ziarno FAT: zaokrąglony czas
    assert projection._link_to(str(src), str(dst), do_apply=False, copy=True) == ("exists", None)


def test_link_to_kopia_rowny_rozmiar_inny_prefiks_to_conflict(tmp_path):
    """Równy rozmiar i czas, ale inny nagłówek (np. kopia sprzed writebacku nagłówka) = `conflict`:
    nieaktualna kopia nazwana, nie nadpisana i nie udająca kompletu."""
    src, dst = _kopia(tmp_path, "p.fits", b"NAGLOWEK-NOWY" + b"X" * 1000)
    st = os.stat(str(dst))
    dst.write_bytes(b"NAGLOWEK-STAR" + b"X" * 1000)               # ten sam rozmiar, inny prefiks
    os.utime(str(dst), ns=(st.st_atime_ns, st.st_mtime_ns))      # czas jak u kopii
    status, reason = projection._link_to(str(src), str(dst), do_apply=True, copy=True)
    assert status == "conflict" and "nie jest kopią" in reason
    assert dst.read_bytes().startswith(b"NAGLOWEK-STAR")          # nietknięty


def test_link_to_kopia_rowny_rozmiar_i_prefiks_czas_poza_granica_to_conflict(tmp_path):
    """Rozmiar i prefiks zgodne, ale czas modyfikacji dalej niż 2 s od źródła = `conflict`: to nie
    jest kopia, którą zrobiło wydanie (`copy2` przenosi czas), tylko plik o zbieżnym początku."""
    src, dst = _kopia(tmp_path, "t.fits", b"TRESC" * 200)
    _przesun_mtime(dst, 3)
    assert projection._link_to(str(src), str(dst), do_apply=False, copy=True)[0] == "conflict"
    _przesun_mtime(dst, -6)                                        # w drugą stronę też
    assert projection._link_to(str(src), str(dst), do_apply=False, copy=True)[0] == "conflict"


def test_same_content_wspolna_sonda_rozmiar_i_prefiks(tmp_path):
    """Jedna sonda treści dla obu pytań klingi: różny rozmiar rozstrzyga bez odczytu, zgodny prefiks
    przy równym rozmiarze to `True` niezależnie od i-węzła (warunek i-węzła dokłada `_verify_content`)."""
    a = tmp_path / "a.fits"
    a.write_bytes(b"A" * 70_000)
    b = tmp_path / "b.fits"
    b.write_bytes(b"A" * 70_000)
    c = tmp_path / "c.fits"
    c.write_bytes(b"A" * 69_999)
    sa, sb, sc = (os.stat(str(p)) for p in (a, b, c))
    assert projection._same_content(str(a), str(b), sa, sb) is True
    assert projection._same_content(str(a), str(c), sa, sc) is False
    assert projection._verify_content(str(a), str(b)) is False    # treść ta sama, i-węzeł nie


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


def test_ponowne_dry_w_trybie_kopii_zero_do_skopiowania(tmp_path):
    """Powtórne wydanie kopią: DRY po wydaniu = 0 do skopiowania, wszystko `exists`, zero konfliktów;
    nowa klatka w planie = DOKŁADNIE jedna do skopiowania, a ponowne wydanie kopiuje tylko ją
    (stare kopie nietknięte - ten sam i-węzeł i czas)."""
    con = db.open_db(str(tmp_path / "kp.db"))
    f1, _ = _seed_file(con, tmp_path, "n1.fits", filter_canon="Ha", data=b"N1" * 50)
    f2, _ = _seed_file(con, tmp_path, "n2.fits", filter_canon="Ha", data=b"N2" * 50)
    root = str(tmp_path / "_WBPP" / "kopie")
    first = projection.apply(projection.plan(con, [f1, f2], "po-obiektach"), root, do_apply=True,
                             copy=True, now=NOW)
    assert first.counts == {"linked": 2}
    dry = projection.apply(projection.plan(con, [f1, f2], "po-obiektach"), root, do_apply=False,
                           copy=True)
    assert dry.counts == {"exists": 2}

    f3, _ = _seed_file(con, tmp_path, "n3.fits", filter_canon="Ha", data=b"N3" * 50)
    stara = os.path.join(root, "_UNSET", "Ha", "n1.fits")
    przed = os.stat(stara)
    plan = projection.plan(con, [f1, f2, f3], "po-obiektach")
    assert projection.apply(plan, root, do_apply=False, copy=True).counts == {"exists": 2,
                                                                               "would-link": 1}
    again = projection.apply(plan, root, do_apply=True, copy=True, now=NOW)
    assert again.counts == {"exists": 2, "linked": 1}
    po = os.stat(stara)
    assert (po.st_ino, po.st_mtime_ns) == (przed.st_ino, przed.st_mtime_ns)
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


def _bez_names(zestawy):
    return {seg: {k: v for k, v in z.items() if k != "names"} for seg, z in zestawy.items()}


def test_object_manifest_kopia_info_i_odmowa_dla_perspektywy(obiekt):
    """Manifest obiektu = treść `info` (listy id) + `names` lightów per zestaw, jako KOPIA - wołający
    dokłada etykietę bez ruszania planu. Plan perspektywy nie ma `info` → odmowa, nie pusty manifest."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    man = projection.object_manifest(p)
    assert {**man, "zestawy": _bez_names(man["zestawy"])} == p.info and man is not p.info
    assert all("names" not in z for z in p.info["zestawy"].values())
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
    assert _bez_names(_bez_ts(payload["zestawy"])) == p.info["zestawy"]
    assert payload["object_canon"] == "NGC 6992"
    assert os.path.isdir(os.path.join(root, projection.OUTPUT_DIR))     # wyjście WBPP wydania
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
    dalej leży w korzeniu obiektu. Stary wpis zostaje ze SWOIM `ts`. Zeznanie INNEGO obiektu w tym
    korzeniu nie jest ani scalane, ani nadpisywane (AR-234): krok manifestu odmawia
    `proj_manifest_foreign` (`object_id`), bajty starego manifestu bez zmian."""
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
    assert _bez_names(_bez_ts(payload["zestawy"]))["A140R_ASI2600MM"] == \
        pierwszy.info["zestawy"]["A140R_ASI2600MM"]
    # Nazwy lightów starego zestawu przeżywają scalenie razem z jego wpisem.
    assert payload["zestawy"]["A140R_ASI2600MM"]["names"] == {
        "la1.fits": i["la1"], "la2.fits": i["la2"], "la3.fits": i["la3"], "la4.fits": i["la4"]}
    assert payload["zestawy"]["RC8_ASI2600MM"]["names"] == {"lb1.fits": i["lb1"]}

    # Obce zeznanie w tym korzeniu (inny obiekt) - odmowa, nie cichy nadpis.
    obcy = dict(payload, object_id=999, zestawy={"OBCY": {"lights": [1], "ts": "T0"}})
    with open(os.path.join(root, projection.MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(obcy, fh)
    przed = _bajty(root)
    res = projection.apply(drugi, root, do_apply=True, now="T3", manifest=projection.object_manifest(drugi))
    assert (res.error.code, dict(res.error.params)) == ("proj_manifest_foreign", {"detail": "object_id"})
    assert _bajty(root) == przed


def _drugie_wydanie_zestawu(con, tmp_path, i):
    """Między wydaniami zestawu A: `la1` wycofany (jego plik zostaje w folderze wydania), `la6` nowy,
    `la2` wycofany, a NOWA klatka nosi nazwę `la2.fits` (inny folder filtru) - dwie klatki pod jedną
    nazwą. Zwraca id `la6`."""
    con.execute("UPDATE frame SET retired_at = ? WHERE id IN (?, ?)", (NOW, i["la1"], i["la2"]))
    con.commit()
    la6 = _klatka(con, tmp_path, "la6.fits", kind="light", config_id=10, object_id=1, filter_canon="Ha")
    _klatka(con, tmp_path, "la2.fits", kind="light", config_id=10, object_id=1, filter_canon="OIII", sub="inny")
    return la6


def test_manifest_obiektu_sumuje_nazwy_zestawu_wydanego_ponownie(obiekt, tmp_path):
    """Ponowne wydanie TEGO SAMEGO zestawu: pliki poprzedniego zostają w folderze, więc ich nazwy
    zostają w `names` (suma map); ta sama nazwa dwóch różnych klatek → `None`. Listy id - bez utraty
    (AR-213): wycofane `la1`, `la2` zostają w `lights` (bez świadków drzewa niepewne, a niepewny zostaje).
    Reszta wpisu - z wydania bieżącego."""
    con, i = obiekt
    cel = str(tmp_path / "_WBPP" / "karta")
    pierwszy = projection.plan_object(con, 1, config_id=10)
    root = projection.object_root(cel, pierwszy)
    projection.apply(pierwszy, root, do_apply=True, now="T1", manifest=projection.object_manifest(pierwszy))
    la6 = _drugie_wydanie_zestawu(con, tmp_path, i)
    drugi = projection.plan_object(con, 1, config_id=10)
    projection.apply(drugi, root, do_apply=True, now="T2", manifest=projection.object_manifest(drugi))
    zestaw = _manifest(root)["zestawy"]["A140R_ASI2600MM"]
    assert zestaw["names"] == {"la1.fits": i["la1"], "la2.fits": None, "la3.fits": i["la3"],
                               "la4.fits": i["la4"], "la6.fits": la6}
    assert zestaw["ts"] == "T2" and zestaw["lights"] == sorted(
        set(drugi.info["zestawy"]["A140R_ASI2600MM"]["lights"]) | {i["la1"], i["la2"]})
    assert "la1.fits" not in projection.object_manifest(drugi)["zestawy"]["A140R_ASI2600MM"]["names"]


def test_manifest_obiektu_anulowane_wydanie_tez_wnosi_nazwy(obiekt, tmp_path):
    """Wydanie anulowane po którejkolwiek stronie wnosi swoje nazwy do sumy: zostawia na dysku część
    plików, a nazwa pliku, którego nie ma, niczego w historii WBPP nie dopasuje."""
    con, i = obiekt
    cel = str(tmp_path / "_WBPP" / "karta")
    pierwszy = projection.plan_object(con, 1, config_id=10)
    root = projection.object_root(cel, pierwszy)
    done = []
    projection.apply(pierwszy, root, do_apply=True, now="T1", manifest=projection.object_manifest(pierwszy),
                     progress=lambda *a: done.append(a), should_cancel=lambda: len(done) >= 1)
    la6 = _drugie_wydanie_zestawu(con, tmp_path, i)
    drugi = projection.plan_object(con, 1, config_id=10)
    projection.apply(drugi, root, do_apply=True, now="T2", manifest=projection.object_manifest(drugi),
                     should_cancel=lambda: True)
    zestaw = _manifest(root)["zestawy"]["A140R_ASI2600MM"]
    assert zestaw["cancelled"] is True and zestaw["names"] == {
        "la1.fits": i["la1"], "la2.fits": None, "la3.fits": i["la3"], "la4.fits": i["la4"], "la6.fits": la6}


def test_merge_names_suma_i_kolizje():
    stare = {"a": 1, "b": 2, "c": None, "d": 4}
    nowe = {"b": 2, "c": 3, "d": 5, "e": None, "f": 6}
    assert projection._merge_names(stare, nowe) == {"a": 1, "b": 2, "c": None, "d": None, "e": None, "f": 6}
    assert stare == {"a": 1, "b": 2, "c": None, "d": 4}                  # nowa mapa, wejście nietknięte


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


def test_apply_obiektu_zaklada_wyjscie_wbpp_tylko_przy_apply(obiekt, tmp_path):
    """`<korzeń wydania>\\out` powstaje razem z wydaniem (`apply`), nie w DRY i nie dla układów
    kolumnowych - okno żniw szuka tam wyników WBPP tego wydania."""
    con, i = obiekt
    p = projection.plan_object(con, 1)
    root = projection.object_root(str(tmp_path / "_WBPP" / "karta"), p)
    projection.apply(p, root, do_apply=False)
    assert not os.path.exists(root)
    projection.apply(p, root, do_apply=True, now=NOW, manifest=projection.object_manifest(p))
    assert os.path.isdir(os.path.join(root, projection.OUTPUT_DIR)) and projection.OUTPUT_DIR == "out"
    kolumnowy = str(tmp_path / "_WBPP" / "kolumny")
    projection.apply(projection.plan(con, [i["la1"]], "po-obiektach"), kolumnowy, do_apply=True, now=NOW)
    assert not os.path.exists(os.path.join(kolumnowy, projection.OUTPUT_DIR))


def test_object_manifest_nazwy_lightow_wydania_i_kolizja_nazwy(obiekt, tmp_path):
    """`names` = nazwy plików, pod którymi WBPP dostał lighty TEGO wydania (bez pominiętych bez kopii
    i bez masterów/surowych flatów); ta sama nazwa dwóch klatek w zestawie to `None`, nie wybór."""
    con, i = obiekt
    drugi = _klatka(con, tmp_path, "la1.fits", kind="light", config_id=10, object_id=1,
                    filter_canon="OIII", sub="inny")
    man = projection.object_manifest(projection.plan_object(con, 1))
    assert man["zestawy"]["A140R_ASI2600MM"]["names"] == {
        "la1.fits": None, "la2.fits": i["la2"], "la3.fits": i["la3"], "la4.fits": i["la4"]}
    assert man["zestawy"]["A140R_ASI2600MC"]["names"] == {"lc1.fits": i["lc1"]}
    assert drugi not in man["zestawy"]["A140R_ASI2600MM"]["names"].values()


@pytest.mark.parametrize("wskazany, korzen", [
    (r"R:\ASTRO_\_WBPP\OBJECTS", r"R:\ASTRO_\_WBPP"),
    (r"R:\ASTRO_", r"R:\ASTRO_\_WBPP"),
    (r"R:\ASTRO_\_Review", r"R:\ASTRO_\_Review\_WBPP"),
    ("R:/ASTRO_/_wbpp/OBJECTS/IC1795/", r"R:\ASTRO_\_wbpp"),
])
def test_work_wbpp_root_pierwszy_segment_wbpp_albo_dopisany(wskazany, korzen):
    """Folder roboczy WBPP: pierwszy segment `_WBPP` (bez wielkości liter) wskazanej ścieżki włącznie,
    inaczej `<wskazany>\\_WBPP` - także pod innym segmentem wykluczonym (`_Review`)."""
    assert projection.work_wbpp_root(wskazany) == korzen
    assert projection.WBPP_DIR.lower() in EXCLUDED_DIR_NAMES


def test_work_wbpp_root_nie_dotyka_dysku(tmp_path):
    wskazany = tmp_path / "ASTRO_"
    assert projection.work_wbpp_root(str(wskazany)) == str(wskazany / "_WBPP")
    assert not wskazany.exists()


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


# ============================================================ kopia mastera (żniwa)


def _master_src(tmp_path, data=b"MASTER-BAJTY" * 100):
    src = tmp_path / "wbpp" / "master" / "masterFlat_X.xisf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(data)
    return str(src)


def _master_dst(tmp_path, name="MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf"):
    return str(tmp_path / "arch" / "CALIBRATION" / "masters" / "flats" / "Z" / "CLS" / name)


def _lib(tmp_path):
    """Korzeń archiwum klingi (`library_root`): biblioteki `CALIBRATION` i `STACKS` leżą pod nim."""
    return str(tmp_path / "arch")


def test_copy_master_publikuje_bez_part_i_z_czasem_zrodla(tmp_path):
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    assert projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                  library_root=_lib(tmp_path)) == ("placed", None)
    assert open(dst, "rb").read() == open(src, "rb").read()
    assert not os.path.exists(dst + ".part")
    assert abs(os.stat(dst).st_mtime_ns - os.stat(src).st_mtime_ns) < 1_000_000


def test_copy_master_verify_bad_zdejmuje_part_i_nie_tyka_celu(tmp_path):
    """Oczekiwany sha1 to bajty zaakceptowane w planie, nie bieżące źródło: źródło zmienione po
    sondzie daje `verify_bad`, a w bibliotece nie zostaje ani cel, ani `.part`."""
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    plan_sha = hashing.sha1_of(src)
    open(src, "ab").write(b"zmiana-po-sondzie")
    status, why = projection.copy_master(src, dst, expected_sha1=plan_sha, library_root=_lib(tmp_path))
    assert status == "verify_bad" and plan_sha in why
    assert not os.path.exists(dst) and not os.path.exists(dst + ".part")


def test_copy_master_cel_istnieje_conflict_bez_nadpisania(tmp_path):
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    os.makedirs(os.path.dirname(dst))
    open(dst, "wb").write(b"CUDZY")
    assert projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                  library_root=_lib(tmp_path))[0] == "conflict"
    assert open(dst, "rb").read() == b"CUDZY" and not os.path.exists(dst + ".part")


def test_copy_master_wyscig_cel_powstal_przed_publikacja(tmp_path):
    """Cel powstaje między kopią a publikacją (wstrzyknięty `sha1_fn`): `os.rename` na Windows nie
    nadpisuje → `conflict`, `.part` zdjęty, plik ręki nietknięty."""
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)

    def sha1_z_wyscigiem(part):
        open(dst, "wb").write(b"RECZNY")
        return hashing.sha1_of(part)
    status, why = projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                         library_root=_lib(tmp_path), sha1_fn=sha1_z_wyscigiem)
    assert (status, why) == ("conflict", f"{dst} (rename: FileExistsError)")
    assert open(dst, "rb").read() == b"RECZNY" and not os.path.exists(dst + ".part")


def test_copy_master_lezacy_part_to_conflict_nie_nadpisanie(tmp_path):
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    os.makedirs(os.path.dirname(dst))
    open(dst + ".part", "wb").write(b"PRZERWANA")
    status, why = projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                         library_root=_lib(tmp_path))
    assert (status, why) == ("conflict", dst + projection.PART_SUFFIX)
    assert open(dst + ".part", "rb").read() == b"PRZERWANA" and not os.path.exists(dst)


def test_copy_master_brak_zrodla_error_bez_part(tmp_path):
    dst = _master_dst(tmp_path)
    status, why = projection.copy_master(str(tmp_path / "brak.xisf"), dst, expected_sha1="x",
                                         library_root=_lib(tmp_path))
    assert status == "error" and why.code == "os_missing"                # błąd systemu klasą (AR-184)
    assert "FileNotFoundError" in dict(why.params)["detail"]
    assert not os.path.exists(dst) and not os.path.exists(dst + ".part")


@pytest.mark.parametrize("cel", [os.path.join("arch", "LIGHTS", "M.xisf"),
                                 os.path.join("arch", "CALIBRATION", "..", "LIGHTS", "M.xisf"),
                                 os.path.join("arch", "LIGHTS", "CALIBRATION"),
                                 os.path.join("arch", "LIGHTS", "X", "stacks", "M.xisf"),
                                 os.path.join("arch", "STACKS", "..", "LIGHTS", "M.xisf"),
                                 os.path.join("arch", "STACKS.xisf"),
                                 os.path.join("inne", "STACKS", "X", "M.xisf"),
                                 os.path.join("arch", "inne", "CALIBRATION", "M.xisf")])
def test_copy_master_guard_biblioteki_pod_korzeniem_archiwum(tmp_path, cel):
    """Cel MUSI leżeć pod `<library_root>\\CALIBRATION` albo `<library_root>\\STACKS` - segment
    BEZPOŚREDNIO pod korzeniem, po normalizacji: `…\\LIGHTS\\X\\stacks\\` to folder roboczy przy
    obiekcie, `STACKS\\..\\LIGHTS` pisze do lightów, a `STACKS` pod innym korzeniem to nie archiwum."""
    src = _master_src(tmp_path)
    with pytest.raises(ValueError, match="CALIBRATION albo STACKS"):
        projection.copy_master(src, str(tmp_path / cel), expected_sha1=hashing.sha1_of(src),
                               library_root=_lib(tmp_path))
    assert not os.path.exists(tmp_path / "arch") and not os.path.exists(tmp_path / "inne")


@pytest.mark.parametrize("pod", [("STACKS", "IC1795", "A140R_2600MM", "Ha"), ("stacks", "X"),
                                 ("calibration", "masters", "flats", "Z", "CLS")])
def test_copy_master_do_bibliotek_archiwum_bez_wielkosci_liter(tmp_path, pod):
    src = _master_src(tmp_path)
    dst = str(tmp_path.joinpath("arch", *pod, "M.xisf"))
    assert projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                  library_root=str(tmp_path / "ARCH" / ".")) == ("placed", None)


def test_copy_master_bez_korzenia_archiwum_odmawia(tmp_path):
    src = _master_src(tmp_path)
    with pytest.raises(ValueError, match="library_root"):
        projection.copy_master(src, _master_dst(tmp_path), expected_sha1=hashing.sha1_of(src),
                               library_root=None)
    assert not os.path.exists(tmp_path / "arch")


def test_copy_master_fsync_part_przed_audytem_i_publikacja(tmp_path, monkeypatch):
    """`.part` utrwalony (`flush` + `os.fsync`) ZANIM audyt go przeczyta i zanim pójdzie publikacja -
    jak bliźnie klingi `raport.py` i `writeback.py`; wyjście WBPP bywa jedyną kopią."""
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    zdarzenia, prawdziwy_fsync, prawdziwy_rename = [], os.fsync, os.rename

    def fsync(fd):
        zdarzenia.append(("fsync", os.fstat(fd).st_size))
        prawdziwy_fsync(fd)

    def rename(a, b):
        zdarzenia.append(("rename", a))
        prawdziwy_rename(a, b)

    def sha1(part):
        zdarzenia.append(("sha1", part))
        return hashing.sha1_of(part)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "rename", rename)
    assert projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src), library_root=_lib(tmp_path),
                                  sha1_fn=sha1)[0] == "placed"
    part = dst + projection.PART_SUFFIX
    assert zdarzenia == [("fsync", os.path.getsize(src)), ("sha1", part), ("rename", part)]


def test_copy_master_rodzic_celu_jest_plikiem_to_error_nie_conflict_part(tmp_path):
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    os.makedirs(os.path.dirname(os.path.dirname(dst)))
    open(os.path.dirname(dst), "wb").write(b"PLIK-ZAMIAST-KATALOGU")
    status, why = projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                         library_root=_lib(tmp_path))
    assert status == "error" and why.startswith("FileExistsError")


def test_copy_master_zrodlo_tylko_do_odczytu_i_wyscig_nie_zostawia_part(tmp_path):
    """Źródło tylko-do-odczytu: na `.part` idą wyłącznie czasy (`os.utime`), nie atrybuty, więc po
    przegranym wyścigu `.part` daje się zdjąć; po sukcesie cel jest zapisywalny, a czas jak źródło."""
    import stat
    src, dst = _master_src(tmp_path), _master_dst(tmp_path)
    os.chmod(src, stat.S_IREAD)
    try:
        def sha1_z_wyscigiem(part):
            open(dst, "wb").write(b"RECZNY")
            return hashing.sha1_of(part)
        status, _ = projection.copy_master(src, dst, expected_sha1=hashing.sha1_of(src),
                                           library_root=_lib(tmp_path), sha1_fn=sha1_z_wyscigiem)
        assert status == "conflict" and not os.path.exists(dst + projection.PART_SUFFIX)
        drugi = _master_dst(tmp_path, "MASTERFLAT_FLATGRP_202305071_FILTER_CLS_.xisf")
        assert projection.copy_master(src, drugi, expected_sha1=hashing.sha1_of(src),
                                      library_root=_lib(tmp_path))[0] == "placed"
        assert os.access(drugi, os.W_OK)
        assert abs(os.stat(drugi).st_mtime_ns - os.stat(src).st_mtime_ns) < 1_000_000
    finally:
        os.chmod(src, stat.S_IREAD | stat.S_IWRITE)


def test_write_harvest_manifest_plik_na_bieg_bez_nadpisania(tmp_path):
    """Każdy bieg własnym plikiem `_ZNIWA_<YYYYMMDD-HHMMSS>.json` (znacznik z `now`), otwartym `x`:
    poprzednie zeznanie nietknięte, kolizja w tej samej sekundzie → `_2`, `_3`."""
    p1 = {"ts": NOW, "items": [{"src": "masterFlat_Ł.xisf", "status": "placed"}]}
    p2 = {"ts": NOW, "items": []}
    a = projection.write_harvest_manifest(str(tmp_path), p1, now=NOW)
    b = projection.write_harvest_manifest(str(tmp_path), p2, now=NOW)
    c = projection.write_harvest_manifest(str(tmp_path), p2, now="2026-07-04T00:00:01.5+00:00")
    assert [os.path.basename(x) for x in (a, b, c)] == [
        f"{projection.HARVEST_MANIFEST_PREFIX}_20260704-000000.json", "_ZNIWA_20260704-000000_2.json",
        "_ZNIWA_20260704-000001.json"]
    tekst = open(a, encoding="utf-8").read()
    assert tekst == json.dumps(p1, ensure_ascii=False, indent=2) and "Ł" in tekst


# ============================================================ meta-test bramki zielony


def test_meta_test_klingi_przepuszcza_projekcje():
    """Bramka mutacji plików zielona z DWIEMA klingami: `projection.py` (DOOR) pominięty, reszta rdzenia
    czysta; `os.link` REALNIE w projekcji, `os.replace` w writebacku (klingi mają ostrza)."""
    import test_writeback_safety as wbs

    wbs.test_mutacja_plikow_tylko_w_writeback()
    wbs.test_klinga_projekcji_istnieje()
    wbs.test_klinga_plikow_istnieje()


# ============================================================ AR-197, AR-200: kroki wydania, odmowy z kodem


def _zerwany(sciezka=r"X:\L\a.fits"):
    return OSError(None, "Komunikat systemu", sciezka, 64)


def _plan_trzech(tmp_path):
    con = db.open_db(str(tmp_path / "k.db"))
    ids = [_seed_file(con, tmp_path, f"k{i}.fits", filter_canon="Ha", data=b"DANE-%d" % i)[0]
           for i in range(3)]
    return con, projection.plan(con, ids, "po-obiektach")


def _inner(res):
    return dict(res.error.params)["inner"]


def test_apply_korzen_nie_powstaje_wynik_z_powodem(tmp_path, monkeypatch):
    """Korzeń wydania: `os.makedirs` korzenia pada zerwanym udziałem - `apply` oddaje wynik z powodem
    `proj_root_failed` (klasa w `inner`), nie wyjątek; nic nie powstało, manifestu nie ma.
    Falsyfikator: `os.makedirs` korzenia poza `try` - `OSError` wylatuje."""
    con, plan = _plan_trzech(tmp_path)
    root = str(tmp_path / "_WBPP" / "feed")
    prawdziwy = os.makedirs

    def makedirs(p, *a, **k):
        if os.path.normcase(str(p)) == os.path.normcase(root):
            raise _zerwany(root)
        return prawdziwy(p, *a, **k)
    monkeypatch.setattr(projection.os, "makedirs", makedirs)
    res = projection.apply(plan, root, do_apply=True, now=NOW)
    assert res.error.code == "proj_root_failed" and _inner(res).code == "os_share_lost", res.error
    assert res.counts == {} and not os.path.exists(root)
    con.close()


def test_apply_wyjscie_wbpp_nie_powstaje_korzen_zostaje(obiekt, tmp_path, monkeypatch):
    """Wyjście WBPP: korzeń wydania obiektu powstał, `out` pada - powód `proj_out_failed` mówi, że folder
    wydania jest założony; korzeń stoi na dysku, linków brak, kwarantanna planu w wyniku."""
    con, _i = obiekt
    p = projection.plan_object(con, 1)
    root = projection.object_root(str(tmp_path / "_WBPP" / "karta"), p)
    prawdziwy = os.makedirs

    def makedirs(sciezka, *a, **k):
        if os.path.basename(str(sciezka)) == projection.OUTPUT_DIR:
            raise _zerwany(str(sciezka))
        return prawdziwy(sciezka, *a, **k)
    monkeypatch.setattr(projection.os, "makedirs", makedirs)
    res = projection.apply(p, root, do_apply=True, now=NOW, manifest=projection.object_manifest(p))
    assert res.error.code == "proj_out_failed" and _inner(res).code == "os_share_lost", res.error
    assert "założony" in res.error
    assert os.path.isdir(root) and os.listdir(root) == []
    assert res.counts == {"skipped": len(p.skipped)}


def test_apply_sonda_pierwszego_linku_nie_czyta_pozycja_niezweryfikowana(tmp_path, monkeypatch):
    """Sonda pierwszego linku: link POWSTAŁ, sonda nie przeczytała plików - pozycja `unverified` z powodem
    `proj_verify_failed` (nie `error`: plik leży), postęp jak przy każdej pozycji, masa nie rusza
    (dwie pozostałe nietknięte), manifestu brak. Falsyfikator: sonda poza `try`."""
    con, plan = _plan_trzech(tmp_path)
    root = str(tmp_path / "_WBPP" / "feed")

    def verify(*_a, **_k):
        raise _zerwany()
    monkeypatch.setattr(projection, "_verify_content", verify)
    postep = []
    res = projection.apply(plan, root, do_apply=True, now=NOW,
                           progress=lambda *a: postep.append(a))
    assert res.error.code == "proj_verify_failed" and _inner(res).code == "os_share_lost", res.error
    assert res.counts == {"unverified": 1}
    (pierwsza,) = res.results
    assert pierwsza.reason is res.error and pierwsza.status == "unverified"
    assert os.stat(pierwsza.dst).st_ino == os.stat(pierwsza.src).st_ino      # link leży na dysku
    assert postep == [(1, 3, pierwsza.dst, "unverified")]
    nietkniete = [it for it in plan.items[1:]
                  if os.path.exists(os.path.join(root, *it.segments, it.basename))]
    assert nietkniete == [] and len(plan.items) - len(res.results) == 2
    assert not os.path.exists(os.path.join(root, projection.MANIFEST_NAME))
    con.close()


def test_apply_manifest_pada_w_polowie_stary_przezywa_bajt_w_bajt(tmp_path, monkeypatch):
    """Manifest i publikacja atomowa: poprawny manifest poprzedniego wydania leży, zapis nowego pada
    zerwanym udziałem W POŁOWIE treści - wynik z powodem `proj_manifest_failed` (pliki wydane), stary
    manifest bajt w bajt, żadnego `.part`. Falsyfikator: `open(manifest, "w")` wprost - plik ucięty."""
    con, plan = _plan_trzech(tmp_path)
    root = str(tmp_path / "_WBPP" / "feed")
    assert projection.apply(plan, root, do_apply=True, now=NOW).error is None
    manifest = os.path.join(root, projection.MANIFEST_NAME)
    przed = open(manifest, "rb").read()
    assert json.loads(przed)["counts"] == {"linked": 3}

    def dump(obj, fh, **kw):
        fh.write('{"layout": "po-ob')
        fh.flush()
        raise _zerwany(manifest)
    monkeypatch.setattr(projection.json, "dump", dump)
    res = projection.apply(plan, root, do_apply=True, now="T2")
    monkeypatch.undo()
    assert res.error.code == "proj_manifest_failed" and _inner(res).code == "os_share_lost", res.error
    assert res.counts == {"exists": 3}
    assert open(manifest, "rb").read() == przed
    assert sorted(os.listdir(root)) == sorted(["_UNSET", projection.MANIFEST_NAME])   # bez `.part`
    con.close()


def test_odmowy_wydania_niosa_kod_a_tekst_PL_bez_zmian(tmp_path, monkeypatch):
    """AR-200: odmowa strażnika korzenia to `OdmowaZPowodem` (dalej `ValueError`) z kodem
    `proj_root_not_excluded` i zdaniem PL jak dotąd; abort sondy pierwszego linku niesie powód
    `proj_first_link` (bez pauzy) - także w wyniku częściowym (`error`)."""
    from horreum.item_reasons import OdmowaZPowodem
    korzen = r"R:\ASTRO_\LIGHTS"
    with pytest.raises(ValueError) as odmowa:
        projection._assert_excluded_segment(korzen)
    nazwy = " / ".join(sorted(n.upper() for n in EXCLUDED_DIR_NAMES))
    assert isinstance(odmowa.value, OdmowaZPowodem)
    assert odmowa.value.powod.code == "proj_root_not_excluded"
    assert dict(odmowa.value.powod.params) == {"dir": korzen, "name": nazwy}
    assert str(odmowa.value) == (f"korzeń projekcji {korzen} nie zawiera segmentu wykluczonego "
                                 f"({nazwy}) - projekcja poza wykluczeniem wróciłaby jako wejście skanu")
    con, plan = _plan_trzech(tmp_path)
    monkeypatch.setattr(projection, "_verify_content", lambda *a, **k: False)
    with pytest.raises(projection.ProjectionAbort) as abort:
        projection.apply(plan, str(tmp_path / "_WBPP" / "feed"), do_apply=True, now=NOW)
    assert abort.value.powod.code == "proj_first_link" and "—" not in str(abort.value)
    assert abort.value.result.error is abort.value.powod
    con.close()


# ============================================================ AR-213: naprawa manifestu i scalenie bez utraty

def _migawka(root):
    """Drzewo wydania bez manifestu: katalog → `"dir"`, plik → (i-węzeł, rozmiar, `mtime_ns`)."""
    out = {}
    for dp, dn, fn in os.walk(root):
        for n in dn:
            out[os.path.join(dp, n)] = "dir"
        for n in fn:
            if n != projection.MANIFEST_NAME:
                st = os.stat(os.path.join(dp, n))
                out[os.path.join(dp, n)] = (st.st_ino, st.st_size, st.st_mtime_ns)
    return out


def _wydany(con, tmp_path, *, config_id=20, now="T1"):
    """Wydanie zestawu PRAWDZIWĄ klingą; RC8 (config 20) nie ma klatek bez kopii."""
    p = projection.plan_object(con, 1, config_id=config_id)
    root = projection.object_root(str(tmp_path / "_WBPP" / "karta"), p)
    projection.apply(p, root, do_apply=True, now=now, manifest=projection.object_manifest(p))
    return p, root


def _napraw(con, p, root, *, now="T2", **kw):
    return projection.repair_manifest(con, p, root, copy=False, now=now,
                                      manifest=projection.object_manifest(p), **kw)


def _zapisz(root, payload):
    with open(os.path.join(root, projection.MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _bajty(root):
    with open(os.path.join(root, projection.MANIFEST_NAME), "rb") as fh:
        return fh.read()


def test_repair_manifest_brak_zapisuje_tresc_bez_mutacji_drzewa(obiekt, tmp_path, monkeypatch):
    """Manifest skasowany po wydaniu (zegar T1): sonda (`do_write=False`) mówi `would-write`/`missing`
    i niczego nie pisze; zapis zegarem T2 kładzie treść wydania - te same klucze, listy, mastery,
    nazwy z drzewa - a czasu wydania bez dowodu NIE zmyśla: bez dowodu z drzewa (`_czas_z_drzewa`
    None - nośnik bez czasu założenia, AR-240) `ts` None, `repaired_at` T2. Drzewo (ścieżki, i-węzły,
    rozmiary, czasy) bez zmian, `out` nie wraca, `.part` nie zostaje; z `ts=T1` (czas nieudanej
    próby) - `ts` T1. Drugie wołanie: `current`. Falsyfikator: zapis z `ts=now`, `makedirs` w naprawie."""
    import shutil
    monkeypatch.setattr(projection, "_czas_z_drzewa", lambda *_a: None)
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    shutil.rmtree(os.path.join(root, projection.OUTPUT_DIR))
    przed = _migawka(root)
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.stan) == ("would-write", "missing")
    assert not os.path.exists(os.path.join(root, projection.MANIFEST_NAME))
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.stan, wynik.kept, wynik.dropped) == ("written", "missing", 0, 0)
    nowy = _manifest(root)
    assert nowy == wynik.payload and _migawka(root) == przed
    assert not os.path.exists(os.path.join(root, projection.OUTPUT_DIR))
    assert not os.path.exists(os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX))
    assert set(nowy) == set(stary) | {"repaired_at"}
    assert (nowy["ts"], nowy["repaired_at"], nowy["counts"]) == (None, "T2", {"exists": len(p.items)})
    pomin = {"ts", "repaired_at", "counts", "zestawy"}
    assert {k: v for k, v in nowy.items() if k not in pomin} == {k: v for k, v in stary.items() if k not in pomin}
    assert _bez_ts(nowy["zestawy"]) == _bez_ts(stary["zestawy"])
    assert {z["ts"] for z in nowy["zestawy"].values()} == {None}
    assert _napraw(con, p, root).status == "current"
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    z_proba = _napraw(con, p, root, do_write=True, ts="T1")
    assert z_proba.payload["ts"] == "T1" and "repaired_at" not in z_proba.payload
    assert {z["ts"] for z in _manifest(root)["zestawy"].values()} == {"T1"}


def test_repair_manifest_stary_zachowuje_ts_nadmiar_z_drzewa_i_nazwy(obiekt, tmp_path):
    """Stary manifest sprzed pola `names` (kształt realnych wydań) z `flat_raw` wcześniejszego wydania:
    surowy flat, którego hardlink leży w `FLAT_RAW`, zostaje (`kept`); surowy flat, którego pliku nie
    ma ani pod i-węzłem, ani pod nazwą, schodzi (`dropped` - dowód nieobecności); `names` z drzewa przy
    pełnym mapowaniu; `ts` nagłówka i wpisu zestawu - stare (T1), mimo zegara T2; etykieta i klucz
    obcy starego manifestu przeniesione. Falsyfikator: lista planu zamiast sumy (F-C1)."""
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    z = stary["zestawy"]["RC8_ASI2600MM"]
    del z["names"]
    z["flat_raw"] = sorted([i["f1"], i["f2"]])
    stary.update(etykieta="NGC 6992 / RC8", obcy_klucz=7)
    flat = os.path.join(root, "RC8_ASI2600MM", "FLAT_RAW", "OIII", "f1.fits")
    os.makedirs(os.path.dirname(flat))
    os.link(str(tmp_path / "lib" / "f1.fits"), flat)
    _zapisz(root, stary)
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.stan, wynik.kept, wynik.dropped) == ("written", "stale", 1, 1)
    nowy = _manifest(root)["zestawy"]["RC8_ASI2600MM"]
    assert nowy["flat_raw"] == [i["f1"]] and nowy["names"] == {"lb1.fits": i["lb1"]}
    assert nowy["ts"] == "T1" and _manifest(root)["ts"] == "T1"
    assert "repaired_at" not in _manifest(root)
    assert (_manifest(root)["etykieta"], _manifest(root)["obcy_klucz"]) == ("NGC 6992 / RC8", 7)


@pytest.mark.parametrize("przypadek", ["bez_kopii", "inny_plik_pod_nazwa"])
def test_repair_manifest_nadmiar_niepewny_zostaje_jak_w_wydaniu(obiekt, tmp_path, przypadek):
    """Id wcześniejszego wydania bez dowodu w żadną stronę - klatka bez obecnej kopii (`la5`) albo
    w roli leży INNY plik pod jej nazwą (kopia sprzed zapisu nagłówka) - ZOSTAJE w manifeście, jak
    w scaleniu wydania (AR-240: jedna polityka), a wynik niesie jego liczbę (`niepewne`), nie odmowę;
    `kept` liczy wyłącznie id z dowodem. Falsyfikator: naprawa odrzucająca niepewne (dawne
    `zachowaj_niepewne=False`)."""
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    fid = i["la5"] if przypadek == "bez_kopii" else i["f1"]
    stary["zestawy"]["RC8_ASI2600MM"]["flat_raw"] = [fid]
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]                 # zapis ma co dopisać
    if przypadek != "bez_kopii":
        obcy = os.path.join(root, "RC8_ASI2600MM", "FLAT_RAW", "OIII", "f1.fits")
        os.makedirs(os.path.dirname(obcy))
        with open(obcy, "wb") as fh:
            fh.write(b"inna tresc")
    _zapisz(root, stary)
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.niepewne, sonda.kept, sonda.dropped) == ("would-write", 1, 0, 0), sonda
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.niepewne, wynik.kept) == ("written", 1, 0), wynik
    assert _manifest(root)["zestawy"]["RC8_ASI2600MM"]["flat_raw"] == [fid]
    assert not os.path.exists(os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX))


def test_repair_manifest_skipped_pisze_jak_wydanie_niekomplet_odmowa(obiekt, tmp_path):
    """Plan z klatką bez obecnej kopii (A140R, `la5`): manifest, który leży po wydaniu, to `current`
    (sonda nie straszy nad dobrym manifestem); skasowany - naprawa pisze TO, CO WYDANIE (AR-240):
    listy zestawów (z `la5`) i nazwy jak w manifeście wydania tego samego planu, `bez_kopii` 1, bez
    odmowy. Cel pozycji skasowany z drzewa - `proj_manifest_incomplete` (`n`), bajty bez zmian.
    Falsyfikatory: odmowa przy `projection.skipped`; nazwy z drzewa liczone po `lights` z klatką bez
    kopii (mapowanie niepełne - `names` znika, wydanie je ma)."""
    con, i = obiekt
    p, root = _wydany(con, tmp_path, config_id=10)
    wydanie = _manifest(root)
    assert p.skipped and _napraw(con, p, root).status == "current"
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.stan, wynik.bez_kopii, wynik.niepewne) == ("written", "missing", 1, 0)
    naprawa = _manifest(root)["zestawy"]["A140R_ASI2600MM"]
    assert i["la5"] in naprawa["lights"]
    assert _bez_ts(_manifest(root)["zestawy"]) == _bez_ts(wydanie["zestawy"])
    p2, root2 = _wydany(con, tmp_path / "drugi")
    przed = _bajty(root2)
    os.remove(os.path.join(root2, "RC8_ASI2600MM", "LIGHT", "Ha", "lb1.fits"))
    wynik = _napraw(con, p2, root2, do_write=True)
    assert (wynik.status, wynik.powod.code, dict(wynik.powod.params)) == (
        "refused", "proj_manifest_incomplete", {"n": 1, "dir": root2})
    assert _bajty(root2) == przed


@pytest.mark.parametrize("bajty_albo_zmiana, kod, pole", [
    (b"\xff\xfe\x00smieci", "proj_manifest_damaged", "UTF-8"),
    (b"{", "proj_manifest_damaged", "JSON"),
    (b"[1]", "proj_manifest_damaged", "manifest"),
    ({"zestawy": []}, "proj_manifest_damaged", "zestawy"),
    ({"lights": "x"}, "proj_manifest_damaged", "zestawy.RC8_ASI2600MM.lights"),
    ({"names": ["a"]}, "proj_manifest_damaged", "zestawy.RC8_ASI2600MM.names"),
    ({"lights": None}, "proj_manifest_damaged", "zestawy.RC8_ASI2600MM.lights"),
    ({"flat_raw": None}, "proj_manifest_damaged", "zestawy.RC8_ASI2600MM.flat_raw"),
    ({"masters": None}, "proj_manifest_damaged", "zestawy.RC8_ASI2600MM.masters"),
    ({"names": None}, "proj_manifest_damaged", "zestawy.RC8_ASI2600MM.names"),
    ({"segments": None}, "proj_manifest_damaged", "segments"),
    ({"object_id": 999}, "proj_manifest_foreign", "object_id"),
    ({"root": r"X:\inna\karta"}, "proj_manifest_foreign", "root"),
    ({"segments": [["inny"]]}, "proj_manifest_foreign", "segments"),
])
def test_repair_manifest_uszkodzony_obcy_zly_typ_odmowa(obiekt, tmp_path, bajty_albo_zmiana, kod, pole):
    """Manifest, który JEST, ale nie jest poprawnym zeznaniem tego wydania - śmieci, nie-UTF-8, zły
    kształt pola (także jawne `null` listy, słownika albo `segments` - obecny klucz bez swojego typu,
    nie brak klucza), sprzeczne zeznanie (obiekt, korzeń, kształt drzewa) - to odmowa z polem
    w `detail` i radą w zdaniu, nie „brak”: bajty przed = po. Falsyfikator: tolerancyjny
    `read_manifest` (uszkodzony jako brak) w naprawie; `get(pole) is not None` w walidacji."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    if isinstance(bajty_albo_zmiana, bytes):
        with open(os.path.join(root, projection.MANIFEST_NAME), "wb") as fh:
            fh.write(bajty_albo_zmiana)
    else:
        stary = _manifest(root)
        zmiana = dict(bajty_albo_zmiana)
        for pole_zestawu in ("lights", "flat_raw", "masters", "names"):
            if pole_zestawu in zmiana:
                stary["zestawy"]["RC8_ASI2600MM"][pole_zestawu] = zmiana.pop(pole_zestawu)
        stary.update(zmiana)
        _zapisz(root, stary)
    przed = _bajty(root)
    wynik = _napraw(con, p, root, do_write=True)
    # Uszkodzony niesie też ścieżkę manifestu (szczegół okna, AR-234) - zdanie bez zmian.
    sciezka = {"path": os.path.join(root, projection.MANIFEST_NAME)} if kod == "proj_manifest_damaged" else {}
    assert (wynik.status, wynik.powod.code, dict(wynik.powod.params)) == (
        "refused", kod, {"detail": pole, **sciezka})
    assert "usuń ręcznie" in str(wynik.powod) and _bajty(root) == przed


def test_repair_manifest_brak_segments_to_nie_rozjazd(obiekt, tmp_path):
    """Manifest sprzed pola `segments` (jak `manifest_drift`: brak zeznania to nie rozjazd) - nie
    obcy; brak `names` czyni go nieaktualnym, a naprawa dopisuje oba pola."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    del stary["segments"], stary["zestawy"]["RC8_ASI2600MM"]["names"]
    _zapisz(root, stary)
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.stan) == ("written", "stale")
    assert _manifest(root)["segments"] == [["zestaw"], ["rola"], ["filtr", "relacja"]]


@pytest.mark.parametrize("stan", ["obecny", "brak"])
def test_repair_manifest_cas_podmiana_miedzy_odczytem_a_publikacja(obiekt, tmp_path, monkeypatch, stan):
    """Drugi pisarz kładzie swój manifest (wersja B) między odczytem świadka a publikacją - naprawa
    odmawia (`proj_manifest_changed`), B zostaje bajt w bajt, `.part` zdjęty. Przy braku manifestu
    drugi `os.stat` przed `os.rename` łapie plik, który powstał; gdyby i on się spóźnił, `os.rename`
    na Windows rzuca `FileExistsError` - też odmowa. Falsyfikator: publikacja bez drugiego odczytu."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    path = os.path.join(root, projection.MANIFEST_NAME)
    stary = _manifest(root)
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]                 # naprawa ma co pisać
    _zapisz(root, stary)
    if stan == "brak":
        os.remove(path)
    prawdziwy = projection.json.dump

    def _drugi_pisarz(payload, fh, **kw):
        with open(path, "wb") as b:
            b.write(b'{"wersja": "B"}')
        return prawdziwy(payload, fh, **kw)
    monkeypatch.setattr(projection.json, "dump", _drugi_pisarz)
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.powod.code) == ("refused", "proj_manifest_changed")
    assert _bajty(root) == b'{"wersja": "B"}'
    assert not os.path.exists(path + projection.PART_SUFFIX)
    if stan == "brak":
        # Serwer o semantyce zastępowania (`rename` nadpisuje cel - SMB bywa taki): wersję B
        # ratuje WYŁĄCZNIE drugi `os.stat` przed publikacją.
        os.remove(path)
        with monkeypatch.context() as m:
            m.setattr(projection.os, "rename", os.replace)
            wynik = _napraw(con, p, root, do_write=True)
        assert (wynik.status, wynik.powod.code) == ("refused", "proj_manifest_changed")
        assert _bajty(root) == b'{"wersja": "B"}' and not os.path.exists(path + projection.PART_SUFFIX)
        os.remove(path)
        monkeypatch.setattr(projection.os.path, "lexists", lambda _p: False)
        wynik = _napraw(con, p, root, do_write=True)
        assert (wynik.status, wynik.powod.code) == ("refused", "proj_manifest_changed")
        assert _bajty(root) == b'{"wersja": "B"}' and not os.path.exists(path + projection.PART_SUFFIX)


def test_repair_manifest_cudzy_part_i_blad_zapisu(obiekt, tmp_path, monkeypatch):
    """Cudzy `.part` obok manifestu - odmowa `proj_manifest_busy` ze ścieżką i radą, `.part`
    nietknięty; `os.replace` pada zerwanym udziałem - `error` z `proj_manifest_failed` (klasa
    systemu w `inner`), stary manifest bajt w bajt, własny `.part` zdjęty."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    path = os.path.join(root, projection.MANIFEST_NAME)
    stary = _manifest(root)
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]
    _zapisz(root, stary)
    przed = _bajty(root)
    with open(path + projection.PART_SUFFIX, "wb") as fh:
        fh.write(b"cudzy")
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.powod.code) == ("refused", "proj_manifest_busy")
    assert dict(wynik.powod.params) == {"path": path + projection.PART_SUFFIX}
    assert "skasuj go ręcznie" in str(wynik.powod)
    with open(path + projection.PART_SUFFIX, "rb") as fh:
        assert fh.read() == b"cudzy"
    os.remove(path + projection.PART_SUFFIX)

    def _zerwany(*_a, **_k):
        raise OSError(None, "Komunikat systemu", path, 64)
    monkeypatch.setattr(projection.os, "replace", _zerwany)
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.powod.code) == ("error", "proj_manifest_failed")
    assert dict(wynik.powod.params)["inner"].code == "os_share_lost"
    assert _bajty(root) == przed and not os.path.exists(path + projection.PART_SUFFIX)


def test_repair_manifest_nazwy_tylko_przy_pelnym_mapowaniu(obiekt, tmp_path):
    """Plik w `LIGHT`, który nie jest żadną klatką zestawu - mapa z drzewa niepełna: naprawa bierze
    regułę wydania (`_nazwy_scalone`) - nazwy PLANU (jego pliki leżą), bo lighty nie wychodzą poza plan;
    ze starym lightem spoza planu bez nazw (niepewny, zostaje) częściowej mapy NIE pisze (wyłączyłaby
    żniwom spadek na bazę) - manifest bez `names` z kompletnymi listami to `current`. Bez obcego pliku -
    `names` z drzewa."""
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]
    _zapisz(root, stary)
    obcy = os.path.join(root, "RC8_ASI2600MM", "LIGHT", "Ha", "obcy.fits")
    with open(obcy, "wb") as fh:
        fh.write(b"nie klatka")
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.roznice) == ("would-write", ("names",))
    assert sonda.payload["zestawy"]["RC8_ASI2600MM"]["names"] == {"lb1.fits": i["lb1"]}
    stary["zestawy"]["RC8_ASI2600MM"]["lights"] = sorted([i["lb1"], i["la5"]])     # la5: bez kopii
    _zapisz(root, stary)
    assert _napraw(con, p, root).status == "current"
    os.remove(obcy)
    _zapisz(root, dict(stary, zestawy={**stary["zestawy"], "RC8_ASI2600MM": {
        **stary["zestawy"]["RC8_ASI2600MM"], "lights": [i["lb1"]]}}))
    assert _napraw(con, p, root, do_write=True).status == "written"
    assert _manifest(root)["zestawy"]["RC8_ASI2600MM"]["names"] == {"lb1.fits": i["lb1"]}


def test_ten_sam_plik_hardlink_i_kopia_z_wydania(tmp_path):
    """Jedna reguła „to ten sam plik” (`_link_to`, sonda kompletu, świadek drzewa): ten sam i-węzeł
    zawsze; kopia `copy2` tylko w trybie kopii; obcy plik nigdy."""
    import shutil
    src = tmp_path / "src.fits"
    src.write_bytes(b"DANE" * 10)
    link, kopia, obcy = tmp_path / "l.fits", tmp_path / "k.fits", tmp_path / "o.fits"
    os.link(src, link)
    shutil.copy2(src, kopia)
    obcy.write_bytes(b"INNE" * 10)
    ss = os.stat(src)
    for dst, z_kopia, bez_kopii in ((link, True, True), (kopia, True, False), (obcy, False, False)):
        ds = os.stat(dst)
        assert projection._ten_sam_plik(str(src), str(dst), ss, ds, copy=True) is z_kopia, dst
        assert bool(projection._ten_sam_plik(str(src), str(dst), ss, ds, copy=False)) is bez_kopii, dst


def test_wydanie_scala_bez_utraty_dowodnie_nieobecny_schodzi_niepewny_zostaje(obiekt, tmp_path):
    """F-C1 w drodze WYDANIA: ponowne wydanie zestawu po wycofaniu `la1`, `la2` - ich pliki zostają
    w drzewie, więc id zostają w `lights`. Ze świadkami (`extra_sources = manifest_sources`) id
    `la2`, którego pliku dowodnie nie ma (skasowany z drzewa), schodzi i liczy się w
    `ApplyResult.dropped`; bez świadków (wołający bez bazy) - niepewny, ZOSTAJE (nic nie ginie).
    Falsyfikator: lista planu zamiast sumy; ślepa suma przy świadkach."""
    con, i = obiekt
    p1, root = _wydany(con, tmp_path, config_id=10)
    os.remove(os.path.join(root, "A140R_ASI2600MM", "LIGHT", "Ha", "la2.fits"))
    con.execute("UPDATE frame SET retired_at = ? WHERE id IN (?, ?)", (NOW, i["la1"], i["la2"]))
    con.commit()
    p2 = projection.plan_object(con, 1, config_id=10)
    zrodla = projection.manifest_sources(con, root)
    assert {i["la1"], i["la2"]} <= set(zrodla)
    res = projection.apply(p2, root, do_apply=True, now="T2", manifest=projection.object_manifest(p2),
                           extra_sources=zrodla)
    lights = _manifest(root)["zestawy"]["A140R_ASI2600MM"]["lights"]
    assert res.dropped == 1 and i["la1"] in lights and i["la2"] not in lights
    stary = _manifest(root)
    stary["zestawy"]["A140R_ASI2600MM"]["lights"].append(i["la2"])
    _zapisz(root, stary)
    res = projection.apply(p2, root, do_apply=True, now="T3", manifest=projection.object_manifest(p2))
    assert res.dropped == 0 and i["la2"] in _manifest(root)["zestawy"]["A140R_ASI2600MM"]["lights"]


def _stat_przez(monkeypatch, zmien):
    """`os.stat` widziany przez klingę: `zmien(ścieżka, prawdziwy stat)` - podmiana albo rzut."""
    prawdziwy = os.stat

    def _stat(sciezka, *a, **k):
        return zmien(os.fspath(sciezka), prawdziwy(sciezka, *a, **k))
    monkeypatch.setattr(projection.os, "stat", _stat)


def _odmowa_dostepu(cel):
    def zmien(sciezka, st):
        if os.path.normcase(sciezka) == os.path.normcase(cel):
            raise OSError(None, "Odmowa dostępu", cel, 5)
        return st
    return zmien


def _id_zestawu(z):
    return len(z["lights"]) + len(z["flat_raw"]) + sum(len(v) for v in z["masters"].values())


@pytest.mark.parametrize("stan", ["odmowa_dostepu", "skasowany"])
def test_zestaw_spoza_planu_schodzi_tylko_z_dowodem_nieobecnosci(obiekt, tmp_path, monkeypatch, stan):
    """Manifest zna dwa zestawy, naprawa i wydanie dotyczą jednego (RC8). Folder drugiego (A140R)
    nieczytelny (odmowa dostępu) - naprawa i wydanie zostawiają jego wpis bez zmian (jedna polityka,
    AR-240), naprawa liczy jego id w `niepewne`; folder skasowany (dowód nieobecności) - naprawa
    i wydanie zdejmują wpis, a jego id liczą się w `dropped`. Falsyfikator: `os.path.isdir` zamiast
    odczytu klasyfikującego (wpis znika bez śladu przy odmowie dostępu)."""
    import shutil
    con, _i = obiekt
    _pa, root = _wydany(con, tmp_path, config_id=10)
    p, _root = _wydany(con, tmp_path)
    stary = _manifest(root)
    assert set(stary["zestawy"]) == {"A140R_ASI2600MM", "RC8_ASI2600MM"}
    n_a = _id_zestawu(stary["zestawy"]["A140R_ASI2600MM"])
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]                 # naprawa ma co pisać
    _zapisz(root, stary)
    folder = os.path.join(root, "A140R_ASI2600MM")
    if stan == "skasowany":
        shutil.rmtree(folder)
    else:
        # Odmowa dostępu widziana każdą drogą odczytu: `os.stat` rzuca, a `os.path.isdir` - jak
        # prawdziwy przy błędzie systemu - mówi „nie ma folderu”.
        _stat_przez(monkeypatch, _odmowa_dostepu(folder))
        prawdziwy_isdir = os.path.isdir
        monkeypatch.setattr(projection.os.path, "isdir", lambda s: False if os.path.normcase(
            os.fspath(s)) == os.path.normcase(folder) else prawdziwy_isdir(s))
    przed = _bajty(root)
    wynik = _napraw(con, p, root, do_write=True)
    if stan == "skasowany":
        assert (wynik.status, wynik.dropped) == ("written", n_a)
        assert set(_manifest(root)["zestawy"]) == {"RC8_ASI2600MM"}
    else:
        assert (wynik.status, wynik.niepewne, wynik.dropped) == ("written", n_a, 0), wynik
        assert _manifest(root)["zestawy"]["A140R_ASI2600MM"] == stary["zestawy"]["A140R_ASI2600MM"]
        assert _bajty(root) != przed                                   # RC8 dostał nazwy z drzewa
    _zapisz(root, stary)
    res = projection.apply(p, root, do_apply=True, now="T3", manifest=projection.object_manifest(p),
                           extra_sources=projection.manifest_sources(con, root))
    zestawy = _manifest(root)["zestawy"]
    assert res.error is None
    if stan == "skasowany":
        assert "A140R_ASI2600MM" not in zestawy and res.dropped == n_a
    else:
        assert zestawy["A140R_ASI2600MM"] == stary["zestawy"]["A140R_ASI2600MM"] and res.dropped == 0


def test_wydanie_i_naprawa_jeden_protokol_part(obiekt, tmp_path, monkeypatch):
    """Przeplot PRAWDZIWYCH pisarzy manifestu (AR-213): wydanie w trakcie zapisu naprawy (naprawa
    trzyma `.part` od odczytu starego manifestu) - krok manifestu wydania odmawia
    `proj_manifest_busy` ze ścieżką, pliki leżą, a naprawa publikuje SWOJĄ treść (plik roboczy
    nietknięty); naprawa w trakcie kroku manifestu wydania - `proj_manifest_busy` w zapisie i w samej
    diagnozie, wydanie publikuje swoją. Falsyfikator: `_write_manifest` z `open(part, "w")`."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    part = os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX)
    stary = _manifest(root)
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]
    _zapisz(root, stary)
    prawdziwe_kopie = projection._obecne_kopie
    wydania = []

    def _wydanie_w_trakcie_naprawy(con_, ids):
        if not wydania:
            assert os.path.exists(part)
            wydania.append(projection.apply(p, root, do_apply=True, now="T3",
                                            manifest=projection.object_manifest(p)))
        return prawdziwe_kopie(con_, ids)
    with monkeypatch.context() as m:
        m.setattr(projection, "_obecne_kopie", _wydanie_w_trakcie_naprawy)
        wynik = _napraw(con, p, root, do_write=True)
    (res,) = wydania
    assert (res.error.code, dict(res.error.params)) == ("proj_manifest_busy", {"path": part})
    assert res.counts == {"exists": len(p.items)}
    assert wynik.status == "written" and _manifest(root) == wynik.payload
    assert not os.path.exists(part)
    _zapisz(root, stary)
    prawdziwe_scalenie = projection._merge_object_manifest
    naprawy = []

    def _naprawa_w_trakcie_wydania(*a, **k):
        naprawy.append((_napraw(con, p, root), _napraw(con, p, root, do_write=True)))
        return prawdziwe_scalenie(*a, **k)
    monkeypatch.setattr(projection, "_merge_object_manifest", _naprawa_w_trakcie_wydania)
    res = projection.apply(p, root, do_apply=True, now="T4", manifest=projection.object_manifest(p))
    ((sonda, zapis),) = naprawy
    assert sonda.powod.code == zapis.powod.code == "proj_manifest_busy", (sonda, zapis)
    assert res.error is None and _manifest(root)["ts"] == "T4" and not os.path.exists(part)


def test_wydanie_przy_cudzym_part_odmawia_busy(obiekt, tmp_path):
    """Cudzy `.part` obok manifestu (zapis w toku albo resztka) - krok manifestu wydania nie ucina go
    i nie scala: `proj_manifest_busy` ze ścieżką, pliki wydania leżą, stary manifest i plik roboczy
    bajt w bajt. Dawniej resztka była nadpisywana."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    part = os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX)
    przed = _bajty(root)
    with open(part, "wb") as fh:
        fh.write(b"cudzy")
    res = projection.apply(p, root, do_apply=True, now="T2", manifest=projection.object_manifest(p))
    assert (res.error.code, dict(res.error.params)) == ("proj_manifest_busy", {"path": part})
    assert res.counts["exists"] == len(p.items) and _bajty(root) == przed
    with open(part, "rb") as fh:
        assert fh.read() == b"cudzy"


@pytest.mark.parametrize("obcy_plik", [False, True])
def test_wydanie_nazwy_z_drzewa_albo_wcale(obiekt, tmp_path, obcy_plik):
    """Stary wpis bez `names` (kształt realnych wydań), zachowany light wcześniejszego wydania
    (wycofany `la1`, plik leży) i nowy light tego wydania (`la6`, starego zeznania nie ma): wydanie
    ze świadkami nazywa scalone lighty z DRZEWA - komplet lightów z kopią (`la5` bez kopii poza
    mapą). Obcy plik w `LIGHT` - mapowanie niepełne, `names` schodzi: częściowa mapa wyłączyłaby
    żniwom spadek na bazę dla `la1`. Falsyfikator: `names` samego bieżącego wydania obok
    zachowanego `la1`; świadek bez źródeł pozycji planu (`la6` bez kopii w świadku)."""
    con, i = obiekt
    _p1, root = _wydany(con, tmp_path, config_id=10)
    stary = _manifest(root)
    del stary["zestawy"]["A140R_ASI2600MM"]["names"]
    _zapisz(root, stary)
    con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, i["la1"]))
    con.commit()
    i["la6"] = _klatka(con, tmp_path, "la6.fits", kind="light", config_id=10, object_id=1,
                       filter_canon="Ha")
    if obcy_plik:
        with open(os.path.join(root, "A140R_ASI2600MM", "LIGHT", "Ha", "obcy.fits"), "wb") as fh:
            fh.write(b"nie klatka")
    p2 = projection.plan_object(con, 1, config_id=10)
    assert i["la1"] not in {it.frame_id for it in p2.items}
    res = projection.apply(p2, root, do_apply=True, now="T2", manifest=projection.object_manifest(p2),
                           extra_sources=projection.manifest_sources(con, root))
    z = _manifest(root)["zestawy"]["A140R_ASI2600MM"]
    assert res.error is None and i["la1"] in z["lights"]
    if obcy_plik:
        assert "names" not in z, z
    else:
        assert z["names"] == {f"{n}.fits": i[n] for n in ("la1", "la2", "la3", "la4", "la6")}


def test_tozsamosc_pliku_niezerowa_para_urzadzenie_wezel(tmp_path):
    """Tożsamość węzła = NIEZEROWA para `(st_dev, st_ino)`. Dwa zera nie są dowodem - rozstrzyga
    porównanie kopii także w trybie hardlinków (hardlink zgodny, obcy plik nie); równy i-węzeł
    z innego urządzenia to inny plik (tryb hardlinków - nie, tryb kopii - porównanie treści)."""
    from types import SimpleNamespace
    src = tmp_path / "src.fits"
    src.write_bytes(b"DANE" * 10)
    link, obcy = tmp_path / "l.fits", tmp_path / "o.fits"
    os.link(src, link)
    obcy.write_bytes(b"INNE" * 10)

    def st(sciezka, *, ino, dev=1):
        s = os.stat(sciezka)
        return SimpleNamespace(st_ino=ino, st_dev=dev, st_size=s.st_size, st_mtime_ns=s.st_mtime_ns)
    w = projection._ten_sam_wezel
    assert w(st(src, ino=7), st(link, ino=7)) and not w(st(src, ino=0), st(link, ino=0))
    assert not w(st(src, ino=7), st(link, ino=7, dev=2))
    sam = projection._ten_sam_plik
    for copy in (False, True):
        assert sam(str(src), str(link), st(src, ino=0), st(link, ino=0), copy=copy) is True
        assert sam(str(src), str(obcy), st(src, ino=0), st(obcy, ino=0), copy=copy) is False
    assert sam(str(src), str(link), st(src, ino=7), st(link, ino=7, dev=2), copy=False) is False
    assert sam(str(src), str(link), st(src, ino=7), st(link, ino=7, dev=2), copy=True) is True


def test_swiadek_przy_zerowych_wezlach_porownuje_kopie(obiekt, tmp_path, monkeypatch):
    """Zerowe i-węzły (nośnik bez i-węzłów, część udziałów SMB): w `FLAT_RAW` leży hardlink surowego
    flatu pod nazwą sprzed zmiany nazwy źródła - świadek rozpoznaje go porównaniem kopii (czas,
    rozmiar, prefiks), więc id zostaje (`kept`), a nie schodzi jako „dowodnie nieobecny”.
    Falsyfikator: druga pętla świadka pomija pary o równym (zerowym) i-węźle."""
    from types import SimpleNamespace
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    stary["zestawy"]["RC8_ASI2600MM"]["flat_raw"] = [i["f1"]]
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]                 # naprawa ma co pisać
    _zapisz(root, stary)
    flat = os.path.join(root, "RC8_ASI2600MM", "FLAT_RAW", "OIII", "f1_przed_zmiana_nazwy.fits")
    os.makedirs(os.path.dirname(flat))
    os.link(str(tmp_path / "lib" / "f1.fits"), flat)
    _stat_przez(monkeypatch, lambda _s, st: SimpleNamespace(
        st_mode=st.st_mode, st_ino=0, st_dev=st.st_dev, st_size=st.st_size, st_mtime_ns=st.st_mtime_ns,
        st_mtime=st.st_mtime))
    wynik = _napraw(con, p, root, do_write=True)
    assert (wynik.status, wynik.kept, wynik.dropped) == ("written", 1, 0), wynik
    nowy = _manifest(root)["zestawy"]["RC8_ASI2600MM"]
    assert nowy["flat_raw"] == [i["f1"]] and nowy["names"] == {"lb1.fits": i["lb1"]}


def test_repair_manifest_nowszy_czas_proby_to_zapis_nie_current(obiekt, tmp_path):
    """Ponowne wydanie tych samych pozycji padło na kroku manifestu - leży manifest T1, który
    listami i nazwami opisuje komplet. Naprawa z czasem tej próby (`ts=T2`) to zapis (`roznice` =
    `ts`), nie `current`: żniwa liczą datę wydania z nagłówka. Ten sam czas albo brak - `current`;
    `ts` wpisu zestawu zostaje stary. Falsyfikator: `current` z samych list i nazw."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    assert _napraw(con, p, root, ts="T1").status == _napraw(con, p, root).status == "current"
    sonda = _napraw(con, p, root, ts="T2")
    assert (sonda.status, sonda.stan, sonda.roznice) == ("would-write", "stale", ("ts",))
    assert _napraw(con, p, root, ts="T2", do_write=True).status == "written"
    assert _manifest(root)["ts"] == "T2" and _manifest(root)["zestawy"]["RC8_ASI2600MM"]["ts"] == "T1"


@pytest.mark.parametrize("krok", ["stat", "odczyt"])
def test_repair_manifest_blad_odczytu_to_kod_odczytu(obiekt, tmp_path, monkeypatch, krok):
    """Manifest, którego nie da się odczytać (odmowa dostępu przy `stat` albo przy odczycie bajtów),
    to `error` z `proj_manifest_unreadable` i klasą systemu w `inner` - w diagnozie i w zapisie; nie
    „nie zapisano manifestu”, bo nikt nie próbował pisać. Bajty i brak `.part` po zapisie."""
    import builtins
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    path = os.path.join(root, projection.MANIFEST_NAME)
    przed = _bajty(root)
    if krok == "stat":
        _stat_przez(monkeypatch, _odmowa_dostepu(path))
    else:
        prawdziwy = builtins.open

        def _open(plik, tryb="r", *a, **k):
            if os.path.normcase(os.fspath(plik)) == os.path.normcase(path) and tryb == "rb":
                raise OSError(None, "Odmowa dostępu", path, 5)
            return prawdziwy(plik, tryb, *a, **k)
        monkeypatch.setattr(projection, "open", _open, raising=False)
    for wynik in (_napraw(con, p, root), _napraw(con, p, root, do_write=True)):
        assert (wynik.status, wynik.powod.code) == ("error", "proj_manifest_unreadable"), wynik
        assert dict(wynik.powod.params)["inner"].code == "os_denied"
    monkeypatch.undo()
    assert _bajty(root) == przed and not os.path.exists(path + projection.PART_SUFFIX)


def test_repair_manifest_foldery_korzenia_bez_zeznania(obiekt, tmp_path):
    """Manifest skasowany, w korzeniu obok zestawu planu leży folder, którego ani plan, ani stary
    manifest nie znają - diagnoza nazywa go (`obce_foldery`, bez `out`): zapis opisze tylko zestaw
    planu. Stary zestaw z manifestu jest opisany - nie trafia do listy."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    for folder in ("INNY_ZESTAW", "STARY_ZESTAW"):
        os.makedirs(os.path.join(root, folder))
    stary = _manifest(root)
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]
    stary["zestawy"]["STARY_ZESTAW"] = {"lights": [], "flat_raw": [], "masters": {}}
    _zapisz(root, stary)
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.obce_foldery) == ("would-write", ("INNY_ZESTAW",))
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.obce_foldery) == ("would-write", ("INNY_ZESTAW", "STARY_ZESTAW"))


def test_repair_manifest_tani_skrot_i_anulowanie(obiekt, tmp_path, monkeypatch):
    """Diagnoza przy każdej sondzie okna: dobry manifest to `current` BEZ świadka drzewa (skrót).
    Drugi hardlink `lb1` pod inną nazwą w `LIGHT` - skrót milknie, a pełna droga widzi brakującą
    nazwę (`roznice` = `names`). `should_cancel` przed świadkiem i w świadku - `cancelled`; zapis
    anulowany zostawia bajty i zdejmuje własny `.part`. Falsyfikator: skrót bez listingu `LIGHT`."""
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    part = os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX)
    with monkeypatch.context() as m:
        m.setattr(projection, "_SwiadekDrzewa", lambda *a, **k: pytest.fail("świadek mimo skrótu"))
        assert _napraw(con, p, root).status == "current"
        # Anulowanie przed skrótem: nie `current` z tańszej drogi, tylko `cancelled`.
        assert _napraw(con, p, root, should_cancel=lambda: True).status == "cancelled"
    # Świadek sam słucha anulowania - przed każdym folderem roli i każdą klatką.
    swiadek = projection._SwiadekDrzewa(root, {i["lb1"]: [str(tmp_path / "lib" / "lb1.fits")]},
                                        should_cancel=lambda: True)
    for krok in (lambda: swiadek._pliki("RC8_ASI2600MM", "LIGHT"), lambda: swiadek._kopie(i["lb1"])):
        with pytest.raises(projection._Przerwano):
            krok()
    os.link(str(tmp_path / "lib" / "lb1.fits"),
            os.path.join(root, "RC8_ASI2600MM", "LIGHT", "Ha", "lb1_druga_nazwa.fits"))
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.roznice) == ("would-write", ("names",))
    assert sonda.payload["zestawy"]["RC8_ASI2600MM"]["names"] == {
        "lb1.fits": i["lb1"], "lb1_druga_nazwa.fits": i["lb1"]}
    przed = _bajty(root)
    assert _napraw(con, p, root, should_cancel=lambda: True).status == "cancelled"
    wywolania = iter([False, False])
    assert _napraw(con, p, root, should_cancel=lambda: next(wywolania, True)).status == "cancelled"
    assert _napraw(con, p, root, do_write=True, should_cancel=lambda: True).status == "cancelled"
    assert _bajty(root) == przed and not os.path.exists(part)


def test_repair_manifest_cudzy_part_w_diagnozie(obiekt, tmp_path):
    """Cudzy `.part` w samej diagnozie: przy `current` nie przeszkadza (nic do zapisu), przy
    werdykcie zapisu - odmowa `proj_manifest_busy` już w sondzie, nie dopiero po kliknięciu."""
    con, _i = obiekt
    p, root = _wydany(con, tmp_path)
    with open(os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX), "wb") as fh:
        fh.write(b"cudzy")
    assert _napraw(con, p, root).status == "current"
    stary = _manifest(root)
    del stary["zestawy"]["RC8_ASI2600MM"]["names"]
    _zapisz(root, stary)
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.powod.code) == ("refused", "proj_manifest_busy")


# ============================================================ AR-234 / AR-240 / AR-245: odczyt ścisły, naprawa jak wydanie

def _open_pada(monkeypatch, sciezka, exc):
    """`open` widziany przez `projection` rzuca `exc` dla `sciezka`; reszta jak zwykle (kształt
    prawdziwej odmowy odczytu danych - `icacls /deny RD`: `os.stat` przechodzi, pada otwarcie)."""
    import builtins
    prawdziwy = builtins.open
    klucz = os.path.normcase(str(sciezka))

    def _open(p, *a, **kw):
        if isinstance(p, (str, os.PathLike)) and os.path.normcase(os.fspath(p)) == klucz:
            raise exc
        return prawdziwy(p, *a, **kw)
    monkeypatch.setattr(projection, "open", _open, raising=False)


def _odmowa_odczytu(sciezka):
    """Odmowa odczytu tak, jak ją daje `open` CRT: errno 13 BEZ `winerror` (zmierzone na prawdziwym ACL)."""
    import errno
    return PermissionError(errno.EACCES, "Permission denied", str(sciezka))


def test_read_manifest_errors_out_tylko_dla_pliku_ktory_lezy(tmp_path, monkeypatch):
    """AR-234: `read_manifest` z listą `errors_out` mówi o manifeście, który LEŻY, a nie da się go
    przeczytać - odmowa (errno 13 po udanym `stat`) klasą `os_denied`, plik uszkodzony
    `proj_manifest_damaged` z polem i ścieżką; brak pliku (ENOENT) to brak, nie błąd. Wynik zawsze
    None, bez listy - jak dotąd. Falsyfikator: zgłoszenie bez filtra `os_missing` (brak = błąd)."""
    import errno
    root = tmp_path / "_WBPP" / "OBJECTS" / "X"
    root.mkdir(parents=True)
    sciezka = root / projection.MANIFEST_NAME
    sciezka.write_bytes(b"{")
    bledy = []
    assert projection.read_manifest(str(root), errors_out=bledy) is None
    assert [(p, w.code, dict(w.params)) for p, w in bledy] == [
        (str(sciezka), "proj_manifest_damaged", {"detail": "JSON", "path": str(sciezka)})]
    assert projection.read_manifest(str(root)) is None
    with monkeypatch.context() as m:
        _open_pada(m, sciezka, _odmowa_odczytu(sciezka))
        bledy = []
        assert projection.read_manifest(str(root), errors_out=bledy) is None
        assert [(p, w.code) for p, w in bledy] == [(str(sciezka), "os_denied")]
        _open_pada(m, sciezka, FileNotFoundError(errno.ENOENT, "No such file", str(sciezka)))
        bledy = []
        assert projection.read_manifest(str(root), errors_out=bledy) is None and bledy == []


@pytest.mark.parametrize("stan", ["nieczytelny", "uszkodzony"])
def test_krok_manifestu_wydania_nie_nadpisuje_starego_nieczytelnego_ani_uszkodzonego(
        obiekt, tmp_path, monkeypatch, stan):
    """AR-234 (pomiar na prawdziwym ACL: tolerancyjny odczyt brał „nie wiem” za „nie ma” i trzecie
    wydanie RC8 zgubiło z manifestu zestaw A140R): stary manifest dwóch wydań, którego otwarcie pada
    odmową (errno 13), daje krok `proj_manifest_failed` z klasą `os_denied`; uszkodzony (JSON) -
    odmowę `proj_manifest_damaged` z polem i ścieżką. Pliki wydania leżą (liczby jak zwykle), bajty
    starego manifestu przed = po, `.part` zdjęty. Falsyfikator: `_write_manifest` z tolerancyjnym
    `read_manifest(root)` - manifest bez A140R."""
    con, _i = obiekt
    _wydany(con, tmp_path, config_id=10)
    p, root = _wydany(con, tmp_path)
    sciezka = os.path.join(root, projection.MANIFEST_NAME)
    assert set(_manifest(root)["zestawy"]) == {"A140R_ASI2600MM", "RC8_ASI2600MM"}
    if stan == "uszkodzony":
        with open(sciezka, "wb") as fh:
            fh.write(b'{"layout": "wbpp-obiekt", "zestawy"')
    else:
        _open_pada(monkeypatch, sciezka, _odmowa_odczytu(sciezka))
    przed = _bajty(root) if stan == "uszkodzony" else open(sciezka, "rb").read()
    res = projection.apply(p, root, do_apply=True, now="T3", manifest=projection.object_manifest(p),
                           extra_sources=projection.manifest_sources(con, root))
    assert res.counts == {"exists": len(p.items)}
    if stan == "uszkodzony":
        assert (res.error.code, dict(res.error.params)) == (
            "proj_manifest_damaged", {"detail": "JSON", "path": sciezka})
        assert _bajty(root) == przed
    else:
        inner = dict(res.error.params)["inner"]
        assert (res.error.code, inner.code) == ("proj_manifest_failed", "os_denied")
        monkeypatch.undo()
        assert _bajty(root) == przed and set(_manifest(root)["zestawy"]) == {"A140R_ASI2600MM",
                                                                            "RC8_ASI2600MM"}
    assert not os.path.exists(sciezka + projection.PART_SUFFIX)


def _wydanie_dwoch_zestawow_bez_manifestu(con, tmp_path):
    """A140R (T1), potem cały obiekt (T2) do jednego korzenia - folder A140R starszy od reszty -
    manifest skasowany → `(plan całego obiektu, korzeń)`."""
    _wydany(con, tmp_path, config_id=10, now="T1")
    p, root = _wydany(con, tmp_path, config_id=None, now="T2")
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    return p, root


def test_naprawa_bierze_ts_z_drzewa_z_kluczem_zrodla(obiekt, tmp_path, monkeypatch):
    """AR-240: naprawa bez czasu próby i bez starego `ts` bierze datę z DRZEWA - czas założenia
    folderu zestawu (`st_birthtime`): nagłówek = późniejszy z folderów, wpis zestawu = czas SWOJEGO
    folderu, `ts_source: "tree"`, `repaired_at` = chwila naprawy. Czas próby z sesji okna (`ts=`) -
    bez `ts_source`, także gdy stary manifest go niósł; bez dowodu z drzewa - `ts` None jak przed
    AR-240. Stary manifest bez daty nie dostaje taniego skrótu `current` - dostaje ofertę z datą.
    Falsyfikatory: nagłówek `None` mimo dowodu; `ts_source` przeniesiony przy czasie z sesji; skrót
    `_skrot_aktualny` nad manifestem bez daty. Właściwość z PRAWDZIWYCH folderów zestawów (nie z
    katalogu roboczego); równe czasy dopuszczone - wybór najpóźniejszego sprawdza osobny test."""
    con, _i = obiekt
    p, root = _wydanie_dwoch_zestawow_bez_manifestu(con, tmp_path)
    czasy = {s: projection._czas_z_drzewa(root, s) for s in p.info["zestawy"]}
    if None in czasy.values():
        pytest.skip("wolumen folderów zestawów bez czasu założenia (`st_birthtime`)")
    assert czasy["A140R_ASI2600MM"] <= czasy["RC8_ASI2600MM"]
    wynik = _napraw(con, p, root, now="T5", do_write=True)
    nowy = _manifest(root)
    assert wynik.status == "written", wynik
    assert (nowy["ts"], nowy["ts_source"], nowy["repaired_at"]) == (
        max(czasy.values()), projection.TS_SOURCE_TREE, "T5")
    assert {s: z["ts"] for s, z in nowy["zestawy"].items()} == czasy
    assert _napraw(con, p, root, now="T6").status == "current"
    # Czas próby z sesji okna wygrywa i zdejmuje źródło daty starego manifestu.
    z_proba = _napraw(con, p, root, now="T7", ts="T9", do_write=True)
    assert z_proba.payload["ts"] == "T9" and "ts_source" not in z_proba.payload
    assert "repaired_at" not in z_proba.payload
    # Manifest bez daty (naprawa sprzed AR-240) - pełna droga, oferta daty z drzewa.
    bez_daty = dict(_manifest(root), ts=None, repaired_at="T0")
    bez_daty.pop("ts_source", None)
    _zapisz(root, bez_daty)
    sonda = _napraw(con, p, root, now="T8")
    assert (sonda.status, sonda.roznice, sonda.payload["ts_source"]) == (
        "would-write", ("ts",), projection.TS_SOURCE_TREE)
    monkeypatch.setattr(projection, "_czas_z_drzewa", lambda *_a: None)
    assert _napraw(con, p, root, now="T8").status == "current"
    os.remove(os.path.join(root, projection.MANIFEST_NAME))
    bez_dowodu = _napraw(con, p, root, now="T8", do_write=True).payload
    assert (bez_dowodu["ts"], bez_dowodu["repaired_at"]) == (None, "T8") and "ts_source" not in bez_dowodu


def test_werdykt_liczy_pary_dopisywane_osobno_od_zapominanych(obiekt, tmp_path):
    """AR-245: `dodane` = pary (zestaw, lista, id), których stary manifest nie miał - stary bez
    lightu planu daje 1; stary z surowym flatem, którego pliku nie ma (dowód nieobecności), daje
    `dropped` 1 i `dodane` 0 - okno nie obieca wtedy dopisania. Falsyfikator: `dodane` zawsze 0."""
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    stary["zestawy"]["RC8_ASI2600MM"]["lights"] = []
    _zapisz(root, stary)
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.dodane, sonda.dropped) == ("would-write", 1, 0), sonda
    stary = _manifest(root)
    stary["zestawy"]["RC8_ASI2600MM"]["lights"] = [i["lb1"]]
    stary["zestawy"]["RC8_ASI2600MM"]["flat_raw"] = [i["f2"]]
    _zapisz(root, stary)
    sonda = _napraw(con, p, root)
    assert (sonda.status, sonda.dodane, sonda.dropped, sonda.roznice) == ("would-write", 0, 1, ("ids",))


def test_naprawa_ts_z_drzewa_najpozniejszy_folder_na_kontrolowanych_czasach(obiekt, tmp_path, monkeypatch):
    """AR-240: data z drzewa na kontrolowanych czasach założenia folderów (bez zależności od wolumenu):
    nagłówek = NAJPÓŹNIEJSZY znany czas folderu zestawu planu, wpis zestawu = czas SWOJEGO folderu,
    a zestaw bez czasu - nagłówka. Falsyfikator: najwcześniejszy zamiast najpóźniejszego."""
    con, _i = obiekt
    p, root = _wydanie_dwoch_zestawow_bez_manifestu(con, tmp_path)
    czasy = {"A140R_ASI2600MM": "2026-01-03T00:00:00+00:00", "RC8_ASI2600MM": "2026-01-01T00:00:00+00:00"}
    monkeypatch.setattr(projection, "_czas_z_drzewa", lambda _root, seg: czasy.get(seg))
    payload = _napraw(con, p, root, now="T5").payload
    assert (payload["ts"], payload["ts_source"]) == ("2026-01-03T00:00:00+00:00", projection.TS_SOURCE_TREE)
    assert {s: z["ts"] for s, z in payload["zestawy"].items()} == {
        s: czasy.get(s, "2026-01-03T00:00:00+00:00") for s in p.info["zestawy"]}


def _manifest_dwoch_wydan(con, tmp_path):
    """A140R, potem RC8 do jednego korzenia → `(plan RC8, korzeń)`; manifest zna oba zestawy."""
    _wydany(con, tmp_path, config_id=10, now="T1")
    return _wydany(con, tmp_path, now="T2")


@pytest.mark.parametrize("przypadek, kod, pole", [
    ("object_id_napisem", "proj_manifest_damaged", "object_id"),
    ("zestaw_nie_slownik", "proj_manifest_damaged", "zestawy.A140R_ASI2600MM"),
    ("lista_nie_id", "proj_manifest_damaged", "zestawy.A140R_ASI2600MM.lights"),
    ("inny_obiekt", "proj_manifest_foreign", "object_id"),
])
def test_krok_manifestu_i_naprawa_jednym_walidatorem_starego_zeznania(obiekt, tmp_path, przypadek, kod, pole):
    """AR-234: stary manifest - POPRAWNY JSON, ale zeznanie wydania obiektu ze złą strukturą (nagłówek,
    zestaw, lista id) albo zeznanie INNEGO obiektu - krok manifestu wydania odmawia tym samym kodem
    i polem co naprawa (`_odmowa_starego`), zamiast pominąć je w scaleniu i nadpisać: pliki wydania
    leżą, bajty starego manifestu przed = po, własny `.part` zdjęty. Falsyfikator: scalenie
    tolerancyjne (sam test „czy słownik”) - stary zestaw A140R znika z manifestu."""
    con, _i = obiekt
    p, root = _manifest_dwoch_wydan(con, tmp_path)
    stary = _manifest(root)
    if przypadek == "object_id_napisem":
        stary["object_id"] = str(stary["object_id"])
    elif przypadek == "zestaw_nie_slownik":
        stary["zestawy"]["A140R_ASI2600MM"] = [1, 2]
    elif przypadek == "lista_nie_id":
        stary["zestawy"]["A140R_ASI2600MM"]["lights"] = "la1"
    else:
        stary["object_id"] = 999
    _zapisz(root, stary)
    przed = _bajty(root)
    res = projection.apply(p, root, do_apply=True, now="T3", manifest=projection.object_manifest(p),
                           extra_sources=projection.manifest_sources(con, root))
    sciezka = {"path": os.path.join(root, projection.MANIFEST_NAME)} if kod == "proj_manifest_damaged" else {}
    assert (res.error.code, dict(res.error.params)) == (kod, {"detail": pole, **sciezka})
    assert res.counts == {"exists": len(p.items)} and _bajty(root) == przed
    assert not os.path.exists(os.path.join(root, projection.MANIFEST_NAME + projection.PART_SUFFIX))
    naprawa = _napraw(con, p, root, do_write=True)
    assert (naprawa.status, naprawa.powod.code, dict(naprawa.powod.params)) == (
        "refused", kod, {"detail": pole, **sciezka})
    assert _bajty(root) == przed


def test_krok_manifestu_nie_zastepuje_zeznania_obiektu_innym_ukladem(obiekt, tmp_path):
    """AR-234: wydanie perspektywy (układ kolumnowy) do folderu wydania obiektu nie zastępuje jego
    manifestu - odmowa `proj_manifest_foreign` (`layout`), stary plik bajt w bajt; stary manifest
    układu kolumnowego zastępuje się jak dotąd. Falsyfikator: kontrola starego tylko w wydaniu obiektu."""
    con, i = obiekt
    _p, root = _wydany(con, tmp_path)
    przed = _bajty(root)
    kolumnowy = projection.plan(con, [i["la1"]], "po-obiektach")
    res = projection.apply(kolumnowy, root, do_apply=True, now="T3", manifest={"perspektywa": "x"})
    assert (res.error.code, dict(res.error.params)) == ("proj_manifest_foreign", {"detail": "layout"})
    assert _bajty(root) == przed
    root2 = str(tmp_path / "_WBPP" / "kolumny")
    assert projection.apply(kolumnowy, root2, do_apply=True, now="T1").error is None
    res = projection.apply(projection.plan(con, [i["la1"]], "wbpp-feed"), root2, do_apply=True, now="T2")
    assert res.error is None and _manifest(root2)["layout"] == "wbpp-feed"


def test_naprawa_zachowuje_nazwy_nowego_lightu_obok_niepewnego_jak_wydanie(obiekt, tmp_path):
    """AR-240 (jedna reguła `names`): stary wpis RC8 zna light bez obecnej kopii (`la5` - niepewny,
    zostaje) z jego nazwą, a plan dokłada `lb1`, którego plik leży; mapa z drzewa jest niepełna (brak
    pliku `la5`). Naprawa i wydanie piszą TĘ SAMĄ mapę - sumę starej i planu - więc żniwa rozpoznają
    obie nazwy. Falsyfikator: naprawa biorąca same stare nazwy (`lb1` znika z rozpoznania)."""
    from horreum import harvest
    con, i = obiekt
    p, root = _wydany(con, tmp_path)
    stary = _manifest(root)
    stary["zestawy"]["RC8_ASI2600MM"].update(lights=[i["la5"]], names={"la5.fits": i["la5"]})
    _zapisz(root, stary)
    naprawa = _napraw(con, p, root, do_write=True)
    assert (naprawa.status, naprawa.niepewne) == ("written", 1), naprawa
    z_naprawy = _manifest(root)
    _zapisz(root, stary)
    projection.apply(p, root, do_apply=True, now="T3", manifest=projection.object_manifest(p),
                     extra_sources=projection.manifest_sources(con, root))
    z_wydania = _manifest(root)
    oczekiwane = {"la5.fits": i["la5"], "lb1.fits": i["lb1"]}
    assert z_naprawy["zestawy"]["RC8_ASI2600MM"]["names"] == z_wydania["zestawy"]["RC8_ASI2600MM"]["names"] \
        == oczekiwane
    indeks = harvest._names_index(harvest._object_witness(z_naprawy))
    assert indeks.hits("lb1_c.xisf") == {("RC8_ASI2600MM", i["lb1"])}
    assert indeks.hits("la5_c.xisf") == {("RC8_ASI2600MM", i["la5"])}
