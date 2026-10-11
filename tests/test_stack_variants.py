r"""Wariant kadru stosu (AR-54), kotwica drzewa stosów (E5-3), planer celu (AR-17).

Trzy pytania, które ten plik zadaje kodowi:
  * czy para autocrop + oryginał przechodzi całą drogę: plan (DRY) → kopia z zeznaniem → skan
    `STACKS` → relacja z kolejki zeznań → dziedziczenie obiektu i zestawu (także zejście do NULL) -
    po restarcie programu między kopią a Dostawą, przy dryfie oryginału i przy mocniejszym świadku,
    i czy powtórka każdego kroku jest ciszą;
  * czy relacja trzyma rangę świadka (`window` < `location` < `user`) i guardy (rodzaj, aktywność,
    obecna kopia, głębokość, jeden wariant na oryginał, CHECK-i domen) oraz czy para nie świeci
    w grupach „wersji stosów”;
  * czy świadek ścieżki stosu kotwiczy na bibliotece archiwum (bez korzenia milczy), a planer celu
    zmienia WYŁĄCZNIE segment obiektu.

Pliki XISF są prawdziwe (attachment z danymi) - kopia, audyt bajtów i tożsamość `sha1_data` mają
działać na tym, na czym działają w archiwum. Wszystko w `tmp_path`."""
import json
import os
import sqlite3

import pytest

from horreum import db, grouper, naming, projection, repo, resolver, scan, stack_variants
from horreum.gui import queries
from horreum.resolve.paths import (STACK_KIND, object_folder, object_from_path,
                                   path_after_object_change)
from test_scan import _write_xisf_attach

NOW = "2026-10-11T12:00:00Z"
R = "R:\\ASTRO_"
STARA = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-Ha_mono.xisf"
AUTOCROP = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-Ha_mono_autocrop.xisf"
CEL = "M31_2025-12-16_RC8_2600MM_Ha_600s_mono_autocrop.xisf"
OKNO = [("IMAGETYP", "'Master Light'"), ("INSTRUME", "'ZWO ASI2600MM Pro'"),
        ("DATE-OBS", "'2025-12-16T20:00:00.000'"), ("DATE-END", "'2025-12-17T03:00:00.000'"),
        ("FILTER", "'Ha'"), ("EXPTIME", "600.00")]
ORYGINAL_KARTY = OKNO + [("TELESCOP", "'RC8'"), ("OBJECT", "'M31'")]


def _xisf(katalog, nazwa, dane, karty):
    katalog.mkdir(parents=True, exist_ok=True)
    return _write_xisf_attach(katalog, nazwa, dane, keywords=karty)


@pytest.fixture
def archiwum(tmp_path):
    """Archiwum z oryginałem w `STACKS` i stare drzewo z autocropem; dawna lokacja oryginału (ta
    sama nazwa bez `_autocrop` w katalogu autocropu) zostaje w bazie jako `present=0` - dokładnie
    tak, jak po przenosinach Custosa."""
    arch = tmp_path / "ARCH"
    stary = tmp_path / "OLD" / "M31_2025" / "master"
    oryg = _xisf(arch / "STACKS" / "M31" / "RC8_2600MM" / "Ha",
                 "M31_2025-12-16_RC8_2600MM_Ha_600s_mono.xisf", b"\x01" * 64, ORYGINAL_KARTY)
    crop = _xisf(stary, AUTOCROP, b"\x02" * 48, OKNO)
    path_db = str(tmp_path / "h.db")
    con = db.open_db(path_db)
    s = scan.scan_tree(con, str(arch), now=NOW)
    assert s.frames_new == 1
    fid = con.execute("SELECT frame_id FROM location").fetchone()[0]
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 0)",
                (fid, str(stary / STARA)))
    con.commit()
    return {"con": con, "db": path_db, "arch": arch, "old": tmp_path / "OLD", "orig": oryg,
            "crop": crop, "fid": fid, "tmp": tmp_path, "stary": stary}


def _ev(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _plan(a, con=None):
    return stack_variants.plan(con or a["con"], str(a["old"]), library_root=str(a["arch"]))


def _apply(a, con=None):
    p = _plan(a, con)
    return p, stack_variants.apply(p, con=con or a["con"], now=NOW)


def _wariant(con):
    r = con.execute("SELECT l.frame_id FROM location l WHERE l.present = 1 "
                    "AND l.path LIKE '%mono_autocrop.xisf'").fetchone()
    return None if r is None else r[0]


def _dostawa(con, a):
    scan.scan_tree(con, str(a["arch"]), now=NOW)
    return grouper.run_grouper(con, NOW), resolver.run_resolver(con, NOW)


def _relacja(con):
    r = con.execute("SELECT variant_frame_id, original_frame_id, source FROM stack_variant").fetchall()
    return [tuple(x) for x in r]


# ═══════════════════════════════════════════════════════════════════ plan (DRY)


def test_plan_oryginal_z_dawnej_lokacji_cel_obok_kopii_w_STACKS(archiwum):
    a = archiwum
    p = _plan(a)
    (it,) = p.items
    assert it.status == "ready" and it.applicable
    o = it.original
    assert (o.frame_id, o.source, o.status) == (a["fid"], "location", "present")
    assert o.src == o.dst == o.stacks_path == str(a["orig"])
    assert it.target_dir == str(a["orig"].parent)
    assert (it.autocrop.dst, it.autocrop.status) == (str(a["orig"].parent / CEL), "to_copy")
    assert it.window_frame_ids == (a["fid"],) and it.window_agrees
    assert not os.path.exists(it.autocrop.dst), "DRY nie kopiuje"
    c = stack_variants.plan_counts(p)
    assert (c["all"], c["location"], c["location_window_agrees"], c["applicable"]) == (1, 1, 1, 1)


def test_plan_okno_tylko_gdy_lokacja_milczy(archiwum):
    a = archiwum
    a["con"].execute("DELETE FROM location WHERE present = 0")
    a["con"].commit()
    (it,) = _plan(a).items
    assert (it.status, it.original.source) == ("ready", "window")


def test_okno_rozroznia_drizzle(archiwum):
    """Stos drizzle i zwykły stos tych samych subów mają to samo okno - świadek okna wiąże autocrop
    wyłącznie z oryginałem o tym samym wariancie skali."""
    a = archiwum
    a["con"].execute("DELETE FROM location WHERE present = 0")
    a["con"].commit()
    _xisf(a["arch"] / "STACKS" / "M31" / "RC8_2600MM" / "Ha",
          "M31_2025-12-16_RC8_2600MM_Ha_600s_mono_drizzle_2x.xisf", b"\x09" * 64, ORYGINAL_KARTY)
    scan.scan_tree(a["con"], str(a["arch"]), now=NOW)
    drizzle = a["con"].execute(
        "SELECT frame_id FROM location WHERE path LIKE '%mono_drizzle_2x.xisf'").fetchone()[0]
    _xisf(a["old"] / "dz", AUTOCROP.replace("_mono_", "_mono_drizzle_2x_"), b"\x0a" * 48, OKNO)
    stat = {os.path.basename(i.autocrop.src): (i.status, i.original.frame_id) for i in _plan(a).items}
    assert stat[AUTOCROP] == ("ready", a["fid"])
    assert stat[AUTOCROP.replace("_mono_", "_mono_drizzle_2x_")] == ("ready", drizzle)


def test_kopie_oryginalu_o_roznych_nazwach_w_STACKS_to_konflikt(archiwum):
    """Wariant skali i nazwa wariantu z SIEDZIBY: dwie obecne kopie oryginału pod różnymi nazwami
    (zwykła i drizzle) blokują pozycję i wycofują klatkę z kandydatów okna."""
    a = archiwum
    druga = a["orig"].parent / "M31_2025-12-16_RC8_2600MM_Ha_600s_mono_drizzle_2x.xisf"
    a["con"].execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 1)",
                     (a["fid"], str(druga)))
    a["con"].commit()
    (it,) = _plan(a).items
    assert it.status == "original_name_conflict" and it.window_frame_ids == ()


def test_plan_okno_niejednoznaczne_i_brak_oryginalu_blokuja(archiwum):
    a = archiwum
    a["con"].execute("DELETE FROM location WHERE present = 0")
    a["con"].commit()
    _xisf(a["arch"] / "STACKS" / "M31" / "RC8_2600MM" / "Ha", "drugi.xisf", b"\x03" * 64,
          ORYGINAL_KARTY)
    scan.scan_tree(a["con"], str(a["arch"]), now=NOW)
    (it,) = _plan(a).items
    assert it.status == "window_ambiguous" and not it.applicable and len(it.window_frame_ids) == 2
    inne = OKNO[:-2] + [("FILTER", "'OIII'"), ("EXPTIME", "600.00")]
    _xisf(a["old"] / "inny", AUTOCROP.replace("Ha", "OIII"), b"\x04" * 48, inne)
    stat = {i.autocrop.src: i.status for i in _plan(a).items}
    assert stat[str(a["old"] / "inny" / AUTOCROP.replace("Ha", "OIII"))] == "no_original"


def test_plan_oryginal_poza_STACKS_obie_strony_i_wspolny_katalog_zablokowane(archiwum):
    """Oryginał bez kopii w bibliotece: pozycja niesie OBIE strony (źródło, cel, status) i wspólny
    katalog docelowy z osi bazy - i zostaje zablokowana do decyzji ręki."""
    a = archiwum
    grouper.run_grouper(a["con"], NOW)
    resolver.run_resolver(a["con"], NOW)                         # obiekt i zestaw oryginału
    poza = str(a["tmp"] / "INNE" / "masterLight_X_600.00s_FILTER-Ha_mono.xisf")
    a["con"].execute("UPDATE location SET path = ? WHERE present = 1", (poza,))
    a["con"].commit()
    (it,) = _plan(a).items
    assert it.status == "original_outside_stacks" and not it.applicable
    o, v = it.original, it.autocrop
    assert (o.status, o.src, o.other_paths) == ("to_copy", poza, (poza,))
    assert it.target_dir and it.target_dir.startswith(str(a["arch"] / "STACKS" / "NGC224"))
    assert os.path.dirname(o.dst) == os.path.dirname(v.dst) == it.target_dir
    assert (v.src, v.status) == (str(a["crop"]), "to_copy")
    assert os.path.basename(v.dst) == naming.variant_stack_name(os.path.basename(o.dst))
    assert stack_variants.apply(_plan(a), con=a["con"], now=NOW)[0].status == "skipped"


def test_plan_pomija_pochodne_i_pliki_juz_w_STACKS(archiwum):
    a = archiwum
    _xisf(a["stary"], AUTOCROP.replace("_autocrop", "_autocrop_DBE"), b"\x05" * 8, OKNO)
    _xisf(a["arch"] / "STACKS" / "M31" / "RC8_2600MM" / "Ha", AUTOCROP, b"\x06" * 8, OKNO)
    assert [i.autocrop.src for i in stack_variants.plan(
        a["con"], str(a["tmp"]), library_root=str(a["arch"])).items] == [str(a["crop"])]


def test_plan_ta_sama_nazwa_celu_dwa_razy_to_name_taken(archiwum):
    a = archiwum
    drugi = a["old"] / "kopia" / "master"
    _xisf(drugi, AUTOCROP, b"\x07" * 48, OKNO)
    a["con"].execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 0)",
                     (a["fid"], str(drugi / STARA)))
    a["con"].commit()
    assert sorted(i.status for i in _plan(a).items) == ["name_taken", "ready"]


def test_rezerwacja_nazwy_mocniejszy_swiadek_wygrywa(archiwum):
    """Ta sama kopia autocropu w dwóch katalogach: jedna trafia oryginał przez dawną lokację, druga
    tylko oknem - cel bierze świadek `location`, choć ścieżka okna sortuje się wcześniej."""
    a = archiwum
    _xisf(a["old"] / "A_okno", AUTOCROP, b"\x02" * 48, OKNO)
    stat = {i.autocrop.src: (i.status, i.original.source) for i in _plan(a).items}
    assert stat[str(a["old"] / "A_okno" / AUTOCROP)] == ("name_taken", "window")
    assert stat[str(a["crop"])] == ("ready", "location")


def test_nazwa_wariantu_z_nazwy_archiwalnej_oryginalu():
    """Człon wariantu zaraz po kolorze, rozbiór od końca: sufiks przebiegu, drizzle i `combined_RGB`
    oryginału zostają, a token `300s` w zestawie nie jest ekspozycją."""
    n = naming.variant_stack_name
    assert n("NGC3034_2023-04-21_76EDPH_2600MM_B_180s_mono_WBPP.xisf") == \
        "NGC3034_2023-04-21_76EDPH_2600MM_B_180s_mono_autocrop_WBPP.xisf"
    assert n("NGC3034_2023-04-21_76EDPH_2600MM_B_180s_mono_WBPP_nowy.xisf") == \
        "NGC3034_2023-04-21_76EDPH_2600MM_B_180s_mono_autocrop_WBPP_nowy.xisf"
    assert n("NGC4258_2023-05-08_76EDPH_2600MM_B_20s_mono_drizzle_2x_wbpp.xisf") == \
        "NGC4258_2023-05-08_76EDPH_2600MM_B_20s_mono_autocrop_drizzle_2x_wbpp.xisf"
    assert n("LMC_2023-03-23_105mm_A7R3_NoFilter_121s_combined_RGB.xisf") == \
        "LMC_2023-03-23_105mm_A7R3_NoFilter_121s_combined_RGB_autocrop.xisf"
    assert n("M31_2025-01-01_Rig_300s_R_600s_mono_WBPP.xisf") == \
        "M31_2025-01-01_Rig_300s_R_600s_mono_autocrop_WBPP.xisf", "zestaw z tokenem 300s"
    for zla in ("masterLight_BIN-1_EXPOSURE-600.00s_FILTER-Ha.xisf",          # brak koloru
                "M31_2025-12-16_RC8_Ha_mono.xisf",                               # brak ekspozycji
                "M31_2025-12-16_RC8_Ha_600s.xisf",                               # brak koloru
                "M31_2025-12-16_RC8_Ha_600s_mono_autocrop.xisf"):                # już wariant
        assert n(zla) is None, zla
    with pytest.raises(ValueError):
        n("M31_2025-12-16_RC8_Ha_600s_mono.xisf", "kadr")


def test_plan_bez_korzenia_archiwum_to_blad():
    with pytest.raises(ValueError):
        stack_variants.plan(None, "X", library_root="")


# ═══════════════════════════════════════════ apply → restart → Dostawa → relacja → dziedziczenie


def test_apply_kopiuje_z_zeznaniem_i_kolejka_a_powtorka_jest_cisza(archiwum):
    a = archiwum
    p, (w,) = _apply(a)
    dst = p.items[0].autocrop.dst
    assert (w.status, w.testimony) == ("placed", "written")
    assert open(dst, "rb").read() == a["crop"].read_bytes()
    assert a["crop"].exists(), "źródło w starym drzewie zostaje"
    sciezka = projection.variant_testimony_path(dst)
    z = projection.read_variant_testimony(sciezka)
    rec = scan.scan_file(str(a["crop"]))
    orig_sha = a["con"].execute("SELECT sha1_data FROM frame WHERE id = ?", (a["fid"],)).fetchone()[0]
    assert z["copy"]["sha1_data"] == rec.sha1_data and z["original"]["sha1_data"] == orig_sha
    assert (z["copy"]["status"], z["original"]["status"], z["source"]) == ("placed", "present", "location")
    assert z["pair_id"] == stack_variants.pair_id(orig_sha, rec.sha1_data)
    kolejka = a["con"].execute("SELECT path, consumed_fingerprint FROM stack_variant_testimony").fetchall()
    assert [tuple(k) for k in kolejka] == [(sciezka, None)]
    assert _relacja(a["con"]) == [], "apply relacji nie zapisuje"
    przed = a["con"].execute("SELECT count(*) FROM event").fetchone()[0]
    p2, (w2,) = _apply(a)
    assert p2.items[0].status == "dst_exists" and (w2.status, w2.testimony) == ("exists", "exists")
    assert a["con"].execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_cli_DRY_nie_kopiuje_a_apply_kopiuje(archiwum, capsys):
    from horreum import cli
    a = archiwum
    argv = ["stack-versions", str(a["old"]), a["db"], "--archive", str(a["arch"])]
    assert cli.main(argv) == 0
    wyjscie = capsys.readouterr().out
    assert "DRY" in wyjscie and "do wykonania: 1" in wyjscie
    cel = a["orig"].parent / CEL
    assert not cel.exists()
    assert cli.main(argv + ["--apply"]) == 0
    assert cel.read_bytes() == a["crop"].read_bytes()
    assert "'placed': 1" in capsys.readouterr().out


def test_apply_inne_bajty_pod_celem_to_konflikt_bez_nadpisania(archiwum):
    a = archiwum
    p = _plan(a)
    dst = p.items[0].autocrop.dst
    with open(dst, "wb") as fh:
        fh.write(b"cudzy plik")
    (w,) = stack_variants.apply(p, con=a["con"], now=NOW)
    assert w.status == "conflict" and open(dst, "rb").read() == b"cudzy plik"
    assert not os.path.exists(projection.variant_testimony_path(dst))


def test_cudzy_part_zeznania_zostaje_nietkniety(archiwum):
    a = archiwum
    dst = _plan(a).items[0].autocrop.dst
    part = projection.variant_testimony_path(dst) + projection.PART_SUFFIX
    with open(part, "w", encoding="utf-8") as fh:
        fh.write("cudzy bieg")
    _p, (w,) = _apply(a)
    assert (w.status, w.testimony) == ("placed", "part_exists")
    assert open(part, encoding="utf-8").read() == "cudzy bieg"
    assert not os.path.exists(projection.variant_testimony_path(dst))
    assert a["con"].execute("SELECT count(*) FROM stack_variant_testimony").fetchone()[0] == 0


@pytest.mark.parametrize("dryf", ["retired", "absent", "identity"])
def test_dryf_oryginalu_miedzy_planem_a_apply_to_odmowa(archiwum, dryf):
    a = archiwum
    p = _plan(a)
    zapytanie = {"retired": "UPDATE frame SET retired_at = 't' WHERE id = ?",
                 "absent": "UPDATE location SET present = 0 WHERE frame_id = ?",
                 "identity": "UPDATE frame SET sha1_data = 'inna' WHERE id = ?"}[dryf]
    a["con"].execute(zapytanie, (a["fid"],))
    a["con"].commit()
    (w,) = stack_variants.apply(p, con=a["con"], now=NOW)
    assert w.status == "original_drift" and not os.path.exists(p.items[0].autocrop.dst)


def test_oryginal_zastapiony_miedzy_apply_a_Dostawa_to_odmowa_klingi(archiwum):
    a = archiwum
    _apply(a)
    con = a["con"]
    nowy = con.execute("INSERT INTO frame(kind, filetype, sha1_data, first_seen_at) "
                       "VALUES ('master_light', 'xisf', 'nastepca', ?)", (NOW,)).lastrowid
    con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (nowy, a["fid"]))
    con.commit()
    g, _r = _dostawa(con, a)
    assert (g.variants.refused, g.variants.linked) == (1, 0) and _relacja(con) == []
    wynik = con.execute("SELECT outcome FROM stack_variant_testimony").fetchone()[0]
    assert wynik.startswith("refused:")


def test_kopia_oryginalu_z_zeznania_musi_byc_obecna(archiwum):
    """Zeznanie stawia parę przy KONKRETNEJ kopii oryginału w `STACKS`; gdy pod tą ścieżką kopii
    już nie ma (oryginał przeniesiony), klinga odmawia, zamiast wiązać parę z innym miejscem."""
    a = archiwum
    p, _ = _apply(a)
    con = a["con"]
    con.execute("UPDATE location SET path = ? WHERE frame_id = ? AND present = 1",
                (str(a["arch"] / "STACKS" / "INNY" / "x" / "Ha" / "o.xisf"), a["fid"]))
    con.commit()
    scan.ingest_record(con, scan.scan_file(p.items[0].autocrop.dst), volume="?", now=NOW,
                       summary=scan.ScanSummary())               # wjazd samego wariantu
    s = stack_variants.link_from_testimonies(con, NOW)
    assert (s.refused, s.linked) == (1, 0) and _relacja(con) == []


def test_restart_miedzy_apply_a_Dostawa_relacja_z_zeznania_i_dziedziczenie(archiwum):
    """Kopia w jednym procesie, Dostawa w następnym: zeznanie w kolejce bazy niesie parę."""
    a = archiwum
    _apply(a)
    a["con"].close()
    con = db.open_db(a["db"])                                   # restart programu
    g, r = _dostawa(con, a)
    vfid = _wariant(con)
    assert (g.variants.candidates, g.variants.linked) == (1, 1)
    assert _relacja(con) == [(vfid, a["fid"], "location")]
    cfg = con.execute("SELECT config_id, config_source FROM frame WHERE id IN (?, ?) ORDER BY id",
                      (a["fid"], vfid)).fetchall()
    assert cfg[0][0] is not None and cfg[1][0] == cfg[0][0] and cfg[1][1] is None
    assert g.configs_by_twin == 1 and r.objects_by_twin == 1
    assert tuple(con.execute("SELECT o.canon, f.object_source FROM frame f JOIN object o "
                             "ON o.id = f.object_id WHERE f.id = ?", (vfid,)).fetchone()) == ("NGC224", "twin")
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    g2, _r2 = _dostawa(con, a)
    assert g2.variants.candidates == 0
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    con.close()


def test_konsument_nie_czyta_udzialu(archiwum, monkeypatch):
    a = archiwum
    _apply(a)
    con = a["con"]
    scan.scan_tree(con, str(a["arch"]), now=NOW)

    def _zakaz(*_a, **_k):
        raise AssertionError("konsument czyta plik zeznania")
    monkeypatch.setattr(projection, "read_variant_testimony", _zakaz)
    assert grouper.run_grouper(con, NOW).variants.linked == 1
    assert grouper.run_grouper(con, NOW).variants.candidates == 0


def test_skan_wpisuje_zeznanie_do_kolejki_innej_bazy(archiwum):
    """Kopia zrobiona przy innej bazie: skan `STACKS` sam znajduje zeznanie obok wjeżdżającej kopii."""
    a = archiwum
    druga = sqlite3.connect(str(a["tmp"] / "druga.db"))
    a["con"].backup(druga)
    druga.close()
    _apply(a)
    con2 = db.open_db(str(a["tmp"] / "druga.db"))
    assert con2.execute("SELECT count(*) FROM stack_variant_testimony").fetchone()[0] == 0
    g, _r = _dostawa(con2, a)
    assert g.variants.linked == 1 and _relacja(con2)[0][1:] == (a["fid"], "location")
    con2.close()


def test_mocniejszy_swiadek_podnosi_relacje_przez_zeznanie(archiwum):
    """Precedencja w torze zeznań: para z okna, potem ta sama para z dawnej lokacji - zeznanie
    podmienione CAS-em, kolejka widzi nowy odcisk, konsument podnosi relację do `location`."""
    a = archiwum
    con = a["con"]
    stara = con.execute("SELECT path FROM location WHERE present = 0").fetchone()[0]
    con.execute("DELETE FROM location WHERE present = 0")
    con.commit()
    _p, (w,) = _apply(a)
    assert (w.status, w.testimony) == ("placed", "written")
    _dostawa(con, a)
    vfid = _wariant(con)
    assert _relacja(con) == [(vfid, a["fid"], "window")]
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 0)",
                (a["fid"], stara))
    con.commit()
    p2, (w2,) = _apply(a)
    assert p2.items[0].original.source == "location" and (w2.status, w2.testimony) == ("exists", "replaced")
    assert projection.read_variant_testimony(
        projection.variant_testimony_path(p2.items[0].autocrop.dst))["source"] == "location"
    g, _r = _dostawa(con, a)
    assert g.variants.linked == 1 and _relacja(con) == [(vfid, a["fid"], "location")]
    _p3, (w3,) = _apply(a)                                      # słabszy świadek już nie podmienia
    assert w3.testimony == "exists"


def test_konsument_czeka_na_skan_i_odrzuca_obce_bajty(archiwum):
    a = archiwum
    p, _ = _apply(a)
    con = a["con"]
    s = stack_variants.link_from_testimonies(con, NOW)
    assert (s.waiting, s.linked) == (1, 0)
    assert con.execute("SELECT consumed_fingerprint FROM stack_variant_testimony").fetchone()[0] is None
    dst = p.items[0].autocrop.dst
    os.remove(dst)
    _xisf(a["orig"].parent, os.path.basename(dst), b"\x0b" * 48, OKNO)   # inne dane pod nazwą kopii
    scan.scan_tree(con, str(a["arch"]), now=NOW)
    s2 = stack_variants.link_from_testimonies(con, NOW)
    assert s2.mismatch == 1 and _relacja(con) == []
    assert con.execute("SELECT outcome FROM stack_variant_testimony").fetchone()[0] == "mismatch"


def _po_dostawie(a):
    _apply(a)
    con = a["con"]
    _dostawa(con, a)
    return con, _wariant(con)


def test_obiekt_blizniaka_idzie_za_oryginalem_A_B_i_A_NULL(archiwum):
    a = archiwum
    con, vfid = _po_dostawie(a)
    oid, _ = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    repo.assign_object(con, frame_id=a["fid"], object_id=oid, object_source="user", now=NOW)
    resolver.run_resolver(con, NOW)
    obiekt = lambda: tuple(con.execute(                                      # noqa: E731
        "SELECT object_id, object_source FROM frame WHERE id = ?", (vfid,)).fetchone())
    assert obiekt() == (oid, "twin")
    repo.clear_object_assignment(con, frame_ids=[a["fid"]], now=NOW)        # oryginał bez obiektu
    resolver.run_resolver(con, NOW)
    assert obiekt() == (None, None)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    resolver.run_resolver(con, NOW)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_nagrobek_wariantu_nietkniety(archiwum):
    a = archiwum
    con, vfid = _po_dostawie(a)
    con.execute("UPDATE frame SET object_id = NULL, object_source = 'user_cleared' WHERE id = ?",
                (vfid,))
    con.commit()
    resolver.run_resolver(con, NOW)
    assert tuple(con.execute("SELECT object_id, object_source FROM frame WHERE id = ?",
                             (vfid,)).fetchone()) == (None, "user_cleared")


@pytest.mark.parametrize("reka", [False, True])
def test_zestaw_blizniaka_schodzi_z_oryginalem_a_reczny_zostaje(archiwum, reka):
    a = archiwum
    con, vfid = _po_dostawie(a)
    cfg = con.execute("SELECT config_id FROM frame WHERE id = ?", (vfid,)).fetchone()[0]
    assert cfg is not None
    if reka:
        con.execute("UPDATE frame SET config_source = 'user' WHERE id = ?", (vfid,))
    con.execute("UPDATE header SET telescop = NULL WHERE frame_id = ?", (a["fid"],))
    con.execute("UPDATE frame SET config_id = NULL WHERE id = ?", (a["fid"],))   # oryginał bez zestawu
    con.commit()
    grouper.run_grouper(con, NOW)
    po = tuple(con.execute("SELECT config_id, config_source FROM frame WHERE id = ?", (vfid,)).fetchone())
    assert po == ((cfg, "user") if reka else (None, None))


# ═══════════════════════════════════════════════════════════ klinga relacji + migracja 0035


def _klatki(con, *kinds):
    for i, k in enumerate(kinds, start=1):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                    "VALUES (?, ?, 'xisf', ?, ?)", (i, k, f"sha{i}", NOW))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 1)",
                    (i, rf"{R}\STACKS\O\cfg\Ha\k{i}.xisf"))
    con.commit()


@pytest.fixture
def con():
    c = db.connect(":memory:")
    db.migrate(c)
    return c


def test_klinga_ranga_swiadka_i_cisza_powtorki(con):
    _klatki(con, "master_light", "master_light", "master_light")
    link = lambda src, orig=1: repo.link_stack_variant(  # noqa: E731
        con, variant_frame_id=2, original_frame_id=orig, variant="autocrop", source=src, now=NOW)
    assert link("window") and _ev(con, "stack_variant.linked") == 1
    assert not link("window") and _ev(con, "stack_variant.linked") == 1, "ta sama wartość = cisza"
    assert link("location")                                      # świadek podniesiony
    assert link("user", orig=3)                                  # ręka przepina
    assert not link("location") and not link("window", orig=1), "automat nie degraduje ręki"
    assert tuple(con.execute("SELECT original_frame_id, source FROM stack_variant").fetchone()) == (3, "user")
    ostatni = json.loads(con.execute("SELECT payload FROM event WHERE verb = 'stack_variant.linked' "
                                     "ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert ostatni["before"] == {"original_frame_id": 1, "variant": "autocrop", "source": "location"}


def test_klinga_guardy_rodzaju_stanu_glebokosci_i_slownikow(con):
    _klatki(con, "master_light", "master_light", "master_light", "light", "master_light")
    kw = dict(variant="autocrop", source="location", now=NOW)
    zle = [dict(variant_frame_id=4, original_frame_id=1, **kw),                  # light
           dict(variant_frame_id=1, original_frame_id=1, **kw),                  # sam ze sobą
           dict(variant_frame_id=2, original_frame_id=1, variant="drizzle_2x", source="location",
                now=NOW),
           dict(variant_frame_id=2, original_frame_id=1, variant="autocrop", source="twin", now=NOW),
           dict(variant_frame_id=2, original_frame_id=1, original_path=rf"{R}\inna.xisf", **kw)]
    for argumenty in zle:
        with pytest.raises(ValueError):
            repo.link_stack_variant(con, **argumenty)
    assert repo.link_stack_variant(con, variant_frame_id=2, original_frame_id=1,
                                   original_path=rf"{R}\STACKS\O\cfg\Ha\k1.xisf", **kw)
    for argumenty in (dict(variant_frame_id=3, original_frame_id=2),            # oryginał jest wariantem
                      dict(variant_frame_id=1, original_frame_id=3),            # wariant jest oryginałem
                      dict(variant_frame_id=5, original_frame_id=1)):           # drugi autocrop oryginału
        with pytest.raises(ValueError):
            repo.link_stack_variant(con, **argumenty, **kw)
    assert con.execute("SELECT count(*) FROM stack_variant").fetchone()[0] == 1


@pytest.mark.parametrize("stan", ["UPDATE frame SET retired_at = 't' WHERE id = 1",
                                  "UPDATE frame SET superseded_by = 3 WHERE id = 1",
                                  "UPDATE location SET present = 0 WHERE frame_id = 1"])
def test_klinga_odmawia_oryginalowi_bez_zycia(con, stan):
    _klatki(con, "master_light", "master_light", "master_light")
    con.execute(stan)
    con.commit()
    with pytest.raises(ValueError):
        repo.link_stack_variant(con, variant_frame_id=2, original_frame_id=1, variant="autocrop",
                                source="location", now=NOW)


def test_migracja_0035_CHECK_i_UNIQUE(con):
    _klatki(con, "master_light", "master_light", "master_light")
    for wiersz in ((1, 1, "autocrop", "window"), (2, 1, "", "window"), (2, 1, "autocrop", "twin")):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO stack_variant(variant_frame_id, original_frame_id, variant, "
                        "source, linked_at) VALUES (?, ?, ?, ?, 't')", wiersz)
    con.execute("INSERT INTO stack_variant VALUES (2, 1, 'autocrop', 'window', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO stack_variant VALUES (3, 1, 'autocrop', 'window', 't')")
    assert set(repo.RANGA_WARIANTU) == {"window", "location", "user"}
    assert repo.STACK_VARIANTS == frozenset({"autocrop"})


def test_kolejka_zeznan_odcisk_i_CAS_rozstrzygniecia(con):
    zapisz = lambda odcisk: repo.record_variant_testimony(  # noqa: E731
        con, path=r"R:\A\_WARIANT_x.json", fingerprint=odcisk, payload="{}", now=NOW)
    assert zapisz("a") and not zapisz("a")
    assert repo.settle_variant_testimony(con, path=r"r:\a\_wariant_x.json", fingerprint="a",
                                         outcome="linked", now=NOW)
    assert not repo.settle_variant_testimony(con, path=r"R:\A\_WARIANT_x.json", fingerprint="b",
                                             outcome="linked", now=NOW)
    assert zapisz("b")                                            # nowy odcisk zeruje rozstrzygnięcie
    assert con.execute("SELECT consumed_fingerprint FROM stack_variant_testimony").fetchone()[0] is None


def test_grupy_wersji_nie_widza_wariantu_z_relacja(archiwum):
    """Para autocrop + oryginał bez relacji wpada do grupy bliźniaków (to samo okno); z relacją
    wariant nie jest kandydatem - Porządki nie podsuwają przyciętego kadru do skasowania."""
    a = archiwum
    _apply(a)
    con = a["con"]
    scan.scan_tree(con, str(a["arch"]), now=NOW)
    for fid in (r[0] for r in con.execute("SELECT id FROM frame").fetchall()):
        con.execute("INSERT INTO integration(master_frame_id, created_at) VALUES (?, 't')", (fid,))
    con.commit()
    stacks_w_grupach = lambda: {c["frame_id"] for g in queries.stack_version_groups(con)  # noqa: E731
                                for c in g["members"]}
    grouper.run_grouper(con, NOW)          # relacja z zeznania + zestaw bliźniaka
    resolver.run_resolver(con, NOW)
    assert stacks_w_grupach() == set()
    con.execute("DELETE FROM stack_variant")
    con.commit()
    assert stacks_w_grupach() == {r[0] for r in con.execute("SELECT id FROM frame").fetchall()}


# ═══════════════════════════════════════════════════════════════════ E5-3: kotwica `STACKS`


def test_kotwica_tylko_STACKS_pod_korzeniem_a_bez_korzenia_milczenie():
    zagniezdzony = rf"{R}\work\STACKS\M31\x\y.xisf"            # BEZ LIGHTS/CALIBRATION
    assert object_from_path(zagniezdzony, kind=STACK_KIND) is None
    assert object_from_path(zagniezdzony, kind=STACK_KIND, library_root=R) is None
    assert object_from_path(rf"{R}\STACKS\M31\cfg\Ha\y.xisf", kind=STACK_KIND) is None
    assert object_from_path(rf"{R}\STACKS\M31\cfg\Ha\y.xisf", kind=STACK_KIND,
                            library_root="r:\\astro_\\") == "M31"
    assert object_folder(rf"{R}\STACKS\M31\cfg\Ha\y.xisf", kind=STACK_KIND,
                         library_root=R) == rf"{R}\STACKS\M31"
    assert queries.stack_folder(rf"{R}\STACKS\M31\cfg\Ha\y.xisf") is None, "filtr nie udaje obiektu"
    assert queries.stack_folder(rf"{R}\STACKS\M31\cfg\Ha\y.xisf", R) == "M31"
    assert queries.hint_from_stacks_tree(rf"{R}\STACKS\M31\cfg\Ha\y.xisf", R)


def _stos(con, sha, path, kind="master_light"):
    cur = con.execute("INSERT INTO frame(kind, filetype, sha1_data, first_seen_at) "
                      "VALUES (?, 'xisf', ?, ?)", (kind, sha, NOW))
    con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (cur.lastrowid,))
    con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'VOL', ?, 1)",
                (cur.lastrowid, path))
    return cur.lastrowid


def test_korzen_z_rodzenstwa_bibliotek_bez_CALIBRATION(con):
    """Korzeń archiwum z obecnych kopii: `STACKS` + `LIGHTS` pod jednym rodzicem (bez biblioteki
    kalibracji). Zagnieżdżony `STACKS` bez markera nie podsuwa obiektu; sama biblioteka `STACKS` bez
    rodzeństwa nie daje korzenia - świadek milczy."""
    zly = _stos(con, "s1", rf"{R}\work\STACKS\M31\cfg\Ha\a.xisf")
    dobry = _stos(con, "s2", rf"{R}\STACKS\NGC7000\cfg\Ha\b.xisf")
    con.commit()
    assert resolver.library_root_from_db(con) is None
    assert resolver.path_proposals(con) == ()
    _stos(con, "l1", rf"{R}\LIGHTS\NGC7000\RC8\Ha\l.fit", kind="light")
    con.commit()
    assert resolver.library_root_from_db(con) == R
    prop = resolver.path_proposals(con)
    assert [(p.canon, p.frame_ids) for p in prop] == [("NGC7000", (dobry,))]
    assert zly not in {f for p in prop for f in p.frame_ids}
    assert resolver.path_proposal(con, rf"{R}\work\STACKS\M31\cfg\Ha\M31_a.xisf", kind=STACK_KIND) is None
    wiersze = {r["frame_id"]: r for r in queries.base_rows(con, [zly, dobry])}
    assert queries.object_cell(dict(wiersze[dobry]))[0].endswith("NGC7000" + queries.HINT_MARK[1])
    assert queries.object_cell(dict(wiersze[zly])) == ("", "canon")


def test_pamiec_korzenia_drugi_base_rows_nie_liczy_a_zmiana_lokacji_uniewaznia(tmp_path, monkeypatch):
    """Korzeń liczony raz na stan bazy: drugie `base_rows` bez zmian nie przelicza; nowa lokacja
    (własne połączenie - `total_changes`) i zapis INNEGO połączenia (`data_version`) unieważniają."""
    sciezka = str(tmp_path / "k.db")
    con = db.open_db(sciezka)
    dobry = _stos(con, "s1", rf"{R}\STACKS\NGC7000\cfg\Ha\b.xisf")
    con.commit()
    liczenia = []
    prawdziwa = resolver.library_root_candidates
    monkeypatch.setattr(resolver, "library_root_candidates",
                        lambda paths: liczenia.append(1) or prawdziwa(paths))
    assert queries.base_rows(con, [dobry])[0]["library_root"] is None
    queries.base_rows(con, [dobry])
    assert len(liczenia) == 1, "drugie base_rows bez zmian nie liczy korzenia"
    repo.add_location(con, frame_id=dobry, volume="VOL", now=NOW, path=rf"{R}\LIGHTS\x\l.fit")
    assert queries.base_rows(con, [dobry])[0]["library_root"] == R and len(liczenia) == 2
    inne = db.open_db(sciezka)
    inne.execute("UPDATE location SET present = 0 WHERE path LIKE '%LIGHTS%'")
    inne.commit()
    inne.close()
    assert queries.base_rows(con, [dobry])[0]["library_root"] is None and len(liczenia) == 3
    queries.base_rows(con, [dobry])
    assert len(liczenia) == 3
    con.close()


# ═══════════════════════════════════════════════════════════════════ AR-17: planer celu


def test_planer_celu_zmienia_wylacznie_segment_obiektu():
    ds = {"object_kind": "deep_sky"}
    assert path_after_object_change(rf"{R}\LIGHTS\NGC 7635\RC8\Ha\x.fit", "NGC7635", **ds) == \
        rf"{R}\LIGHTS\NGC7635\RC8\Ha\x.fit"
    assert path_after_object_change(rf"{R}\LIGHTS\_COMETS\12P\cam\x.fit", "C2023A3",
                                    object_kind="comet") == rf"{R}\LIGHTS\_COMETS\C2023A3\cam\x.fit"
    assert path_after_object_change(rf"{R}\LIGHTS\LMC\A7R3_105\OSC\_7R38821.ARW", "NGC2070",
                                    **ds) == rf"{R}\LIGHTS\NGC2070\A7R3_105\OSC\_7R38821.ARW"
    assert path_after_object_change(rf"{R}\STACKS\Veil\cfg\Ha\v.xisf", "NGC6992", kind=STACK_KIND,
                                    library_root=R, **ds) == rf"{R}\STACKS\NGC6992\cfg\Ha\v.xisf"
    assert path_after_object_change("/mnt/a/LIGHTS/M31//cfg/x.fit", "NGC224", **ds) == \
        "/mnt/a/LIGHTS/NGC224//cfg/x.fit", "separatory zostają"


def test_planer_celu_milczy_poza_pozycja_obiektu_i_odmawia_zlego_kanonu():
    ds = {"object_kind": "deep_sky"}
    assert path_after_object_change(rf"{R}\CALIBRATION\darks\d.fit", "M31", **ds) is None
    assert path_after_object_change(r"R:\A\LMC\master\m.xisf", "LMC", kind=STACK_KIND, **ds) is None
    assert path_after_object_change(rf"{R}\work\STACKS\M31\c\f\y.xisf", "M33", kind=STACK_KIND,
                                    library_root=R, **ds) is None
    for zly in ("", " M31", "M31 ", "a/b", "a:b", "..", None):
        with pytest.raises(ValueError):
            path_after_object_change(rf"{R}\LIGHTS\M31\c\x.fit", zly, **ds)
    with pytest.raises(ValueError):
        path_after_object_change(rf"{R}\LIGHTS\M31\c\x.fit", "M33", object_kind="galaxy")
