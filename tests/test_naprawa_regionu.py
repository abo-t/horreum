"""„Napraw nagłówek…” z nazwą obiektu-REGIONU (AR-180): karta `Veil` wraca klatce wyłącznie wtedy,
gdy przebieg sprowadzi ją szczeblem regionu (współrzędne nagłówka) albo bliźniaka (oryginał wariantu
stosu) - więc bramka pyta PER KLATKA tą samą drabiną (`resolver.karta_wraca`), a nazwa sama w sobie
(`_validate_object_value`) zostaje walidatorem NAZWY. Kartę dostaje tylko klatka, którą karta sama
sprowadzi; reszta grupy zostaje bez karty z liczbą w podglądzie.

Dowody idą przez PRAWDZIWY `run_resolver` po zapisie (nie przez atrapę drabiny): klatki z kartą
lądują w `Veil`, klatki bez karty zostają bez obiektu. Kolejność przebiegu dla wariantów (oryginał
przed wariantem) pinuje macierz oryginałów porównana z przebiegiem."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # przed importem Qt (klasa AR-170)

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, resolver, scan

NOW = "2026-10-16T00:00:00+00:00"
VEIL = (312.75, 30.67)            # środek regionu `Veil` (`regions.json`)
POZA = (10.68, 41.27)             # M31 - daleko od każdego regionu


def _klatka(con, root, rel, *, kind="light", obj=None, wsp=VEIL, seed=0):
    """FITS pod `root/rel` (light albo gotowy stos), z kartą `obj` (None = bez karty)
    i współrzędnymi `wsp` (None = bez), wciągnięty skanem → `(frame_id, ścieżka)`."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + seed)
    hdu.header["IMAGETYP"] = "Master Light" if kind == "master_light" else "Light"
    hdu.header["DATE-OBS"] = f"2023-08-22T20:{seed:02d}:00"
    if obj is not None:
        hdu.header["OBJECT"] = obj
    if wsp is not None:
        hdu.header["RA"], hdu.header["DEC"] = wsp
    hdu.writeto(str(p))
    _wciagnij(con, p)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(p),)).fetchone()[0]
    assert con.execute("SELECT kind FROM frame WHERE id = ?", (fid,)).fetchone()[0] == kind
    return fid, p


def _wciagnij(con, p):
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary(),
                       pochodzenie=repo.ZEWNETRZNE)


def _obiekt(con, fid):
    r = con.execute("SELECT o.canon FROM frame f LEFT JOIN object o ON o.id = f.object_id "
                    "WHERE f.id = ?", (fid,)).fetchone()
    return r[0]


def _karta(p):
    with fits.open(str(p)) as h:
        return h[0].header.get("OBJECT")


# ════════════════════════════════════════════════════════ rdzeń (Qt-wolny)


def test_kanon_regionu_karty_nazywa_region_a_drabina_nazw_bije_region(tmp_path, monkeypatch):
    """Tekst nazywa region kanonem bez wielkości liter i znaków (`Veil`/`veil`/`VEIL`) albo formą
    karty regionu (głos bliźniaków); tekst, który drabina NAZW rozpoznaje, należy do tamtego obiektu
    (alias `veil` nauczony ręką innemu obiektowi bije region), a dowolne słowo regionu nie nazywa.
    Falsyfikatory: zdjęte pytanie drabiny → alias przegrywa z regionem; porównanie formy zdjęte →
    `Cygnus Loop` nie nazywa regionu."""
    con = db.open_db(str(tmp_path / "k.db"))
    for tekst in ("Veil", "veil", "VEIL", " Veil "):
        assert resolver.kanon_regionu_karty(con, tekst) == "Veil", tekst
    for tekst in ("NGC 6992", "xyzzy", "", None):
        assert resolver.kanon_regionu_karty(con, tekst) is None, tekst
    monkeypatch.setattr(resolver, "forma_karty_object",
                        lambda con_, canon, lookup=None: "Cygnus Loop" if canon == "Veil" else None)
    for tekst in ("Cygnus Loop", "cygnus loop", "CYGNUS-LOOP"):    # forma tą samą regułą co kanon
        assert resolver.kanon_regionu_karty(con, tekst) == "Veil", tekst
    assert resolver.kanon_regionu_karty(con, "Cygnus") is None
    monkeypatch.undo()
    oid, _ = repo.upsert_object(con, canon="ZW77", catalog=None, kind="deep_sky", now=NOW)
    repo.add_object_alias(con, alias_norm="VEIL", object_id=oid, source="user", now=NOW)
    assert resolver.kanon_regionu_karty(con, "veil") is None
    con.close()


def test_obiekt_oryginalu_wariantu_jak_PRZEBIEG(tmp_path):
    """`fakty_karty_klatek(...).twin_canon` = obiekt, który `run_resolver` da ORYGINAŁOWI przed
    wariantem - na macierzy oryginałów: bez obiektu w regionie / poza nim, z nazwą w nagłówku
    w regionie, `Veil` z regionu z nagłówkiem zmienionym po ostatnim `Rozwiąż` (nagłówek bije
    region), ręka (zostaje) i nagrobek ręki (zostaje bez obiektu). Wariant bez nazwy, poza regionem
    - po przebiegu ma dokładnie ten obiekt. Falsyfikatory: `twin_canon` ze stanu bazy bez nazwy
    nagłówka → przypadek „nieaktualny”; bez szczebla regionu → „bez obiektu w regionie”."""
    con = db.open_db(str(tmp_path / "o.db"))
    root = tmp_path / "ASTRO_"
    pary, seed = {}, 0

    def _para(nazwa, *, obj=None, wsp=VEIL):
        nonlocal seed
        seed += 2
        o, po = _klatka(con, root, rf"STACKS\{nazwa}\o.fits", kind="master_light", obj=obj, wsp=wsp,
                        seed=seed)
        v, _ = _klatka(con, root, rf"STACKS\{nazwa}\o_autocrop.fits", kind="master_light",
                       wsp=POZA, seed=seed + 1)
        repo.link_stack_variant(con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                                source="user", now=NOW)
        pary[nazwa] = (o, v, po)
    _para("w_regionie")
    _para("poza", wsp=POZA)
    _para("nazwa", obj="NGC 7000")
    _para("nieaktualny")
    _para("reka", wsp=POZA)
    _para("nagrobek", wsp=POZA)
    for kanon, nazwa in (("M42", "reka"), ("M42", "nagrobek")):
        repo.user_assign_object(con, alias_norm=None, canon=kanon, catalog="M", kind="deep_sky",
                                frame_ids=[pary[nazwa][0]], now=NOW)
    repo.clear_object_assignment(con, frame_ids=[pary["nagrobek"][0]], now=NOW)
    warianty = [v for _o, v, _p in pary.values()]
    przed = resolver.fakty_karty_klatek(con, warianty)       # oryginały jeszcze bez przebiegu
    assert {n: przed[v].twin_canon for n, (_o, v, _p) in pary.items()} == {
        "w_regionie": "Veil", "poza": None, "nazwa": "NGC7000", "nieaktualny": "Veil",
        "reka": "M42", "nagrobek": None}
    resolver.run_resolver(con, NOW)
    assert {n: _obiekt(con, o) for n, (o, _v, _p) in pary.items()} == {
        n: przed[v].twin_canon for n, (_o, v, _p) in pary.items()}
    assert _obiekt(con, pary["nieaktualny"][0]) == "Veil"
    fits.setval(str(pary["nieaktualny"][2]), "OBJECT", value="NGC 6992")   # karta po `Rozwiąż`
    _wciagnij(con, pary["nieaktualny"][2])
    fakty = resolver.fakty_karty_klatek(con, warianty)
    oczekiwane = {"w_regionie": "Veil", "poza": None, "nazwa": "NGC7000", "nieaktualny": "NGC6992",
                  "reka": "M42", "nagrobek": None}
    assert {n: fakty[v].twin_canon for n, (_o, v, _p) in pary.items()} == oczekiwane
    resolver.run_resolver(con, NOW)
    assert {n: _obiekt(con, o) for n, (o, _v, _p) in pary.items()} == oczekiwane
    assert {n: _obiekt(con, v) for n, (_o, v, _p) in pary.items()} == oczekiwane
    assert fakty[pary["poza"][1]].original_frame_id == pary["poza"][0]
    assert fakty[pary["poza"][1]].ra_deg == POZA[0]
    con.close()


# ════════════════════════════════════════════════════════ okno (Qt)


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _okno(con, rows):
    from horreum.gui import queries
    from horreum.gui.app import RepairHeaderDialog
    dlg = RepairHeaderDialog(con, rows=rows, db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    dlg._runner.async_ok = False
    dlg.show()
    return dlg


def _wiersze(con, ids):
    return [{"frame_id": f, "kind": k, "path": p} for f, k, p in con.execute(
        "SELECT f.id, f.kind, l.path FROM frame f JOIN location l ON l.frame_id = f.id "
        "WHERE f.id IN (SELECT value FROM json_each(?)) ORDER BY l.path",
        (str(list(ids)),)).fetchall()]


def _wpisz(dlg, tekst):
    """Gest człowieka: zaznacz jedyną grupę (gdy niezaznaczona) i wpisz nazwę z klawiatury."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    (g,) = dlg._groups
    if not g["check"].isChecked():
        QTest.mouseClick(g["check"], Qt.LeftButton)
    g["edit"].clear()
    QTest.keyClicks(g["edit"], tekst)
    return g


def _zapisz(dlg):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(dlg.save_btn, Qt.LeftButton)


def test_Veil_w_regionie_karta_dla_calej_grupy_i_PRZEBIEG_sprowadza(qapp, tmp_path):
    """Grupa bez nazwy w regionie: `Veil` już nie jest „nierozpoznawalna” - podgląd jak przy nazwie,
    „Zapisz karty (2)”, karta w obu plikach, a prawdziwy `run_resolver` sprowadza obie do `Veil`.
    Falsyfikator: `plan_kart_naprawy` bez gałęzi regionu → odmowa grupy, zero zapisu."""
    from horreum.gui import i18n, queries
    con = db.open_db(str(tmp_path / "a.db"))
    root = tmp_path / "ASTRO_"
    ids = [_klatka(con, root, rf"LIGHTS\Veil\cam\v{k}.fits", seed=k)[0] for k in range(2)]
    dlg = _okno(con, queries.nameless_frames(con))
    g = _wpisz(dlg, "Veil")
    assert g["preview"].text() == i18n.t("repair.preview", value="'Veil'")
    assert dlg.save_btn.text() == i18n.t("repair.save_btn_n", n=2) and dlg.error.text() == ""
    _zapisz(dlg)
    assert [_karta(p) for p in sorted((root / "LIGHTS" / "Veil" / "cam").glob("*.fits"))] == \
        ["Veil", "Veil"]
    resolver.run_resolver(con, NOW)
    assert [_obiekt(con, f) for f in ids] == ["Veil", "Veil"]
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_grupa_mieszana_karta_TYLKO_klatkom_ktore_region_sprowadzi(qapp, tmp_path, lang):
    """Folder z klatkami w regionie, poza nim i bez współrzędnych: podgląd „2 z 4 klatek”,
    podpowiedź - 2 bez karty i dlaczego, „Zapisz karty (2)”; karta w 2 plikach, 2 pliki bajtowo
    nietknięte; po `run_resolver` 2 × `Veil`, 2 bez obiektu (bez nazwy, bez regionu). Odmiana
    1/2/5/12/22 obu wpisów. Falsyfikator: zapis wszystkich klatek grupy → plik spoza regionu z kartą."""
    from horreum.gui import i18n, queries
    i18n.set_lang(lang)
    try:
        con = db.open_db(str(tmp_path / "m.db"))
        root = tmp_path / "ASTRO_"
        w = [_klatka(con, root, rf"LIGHTS\Veil\cam\a{k}.fits", seed=k) for k in range(2)]
        poza = _klatka(con, root, r"LIGHTS\Veil\cam\b.fits", wsp=POZA, seed=5)
        bez = _klatka(con, root, r"LIGHTS\Veil\cam\c.fits", wsp=None, seed=6)
        przed = {p: p.read_bytes() for _f, p in (poza, bez)}
        dlg = _okno(con, queries.nameless_frames(con))
        g = _wpisz(dlg, "veil")
        assert g["preview"].text() == i18n.t_plural("repair.preview_part", 4, value="'Veil'", k=2)
        assert g["preview"].toolTip() == i18n.t_plural("repair.region_outside_tip", 2,
                                                       value="'Veil'", canon="Veil")
        assert dlg.save_btn.text() == i18n.t("repair.save_btn_n", n=2)
        _zapisz(dlg)
        assert [_karta(p) for _f, p in w] == ["Veil", "Veil"]
        assert all(p.read_bytes() == b for p, b in przed.items())
        resolver.run_resolver(con, NOW)
        assert [_obiekt(con, f) for f, _p in w + [poza, bez]] == ["Veil", "Veil", None, None]
        dlg.reject()
        con.close()
        odmiana = {"pl": [("1 z 2 klatek", "1 klatka bez karty"), ("2 z 5 klatek", "2 klatki"),
                          ("5 z 12 klatek", "5 klatek"), ("1 z 22 klatek", "12 klatek"),
                          ("1 z 1 klatki", "22 klatki")],
                   "en": [("1 of 2 frames", "1 frame without"), ("2 of 5 frames", "2 frames"),
                          ("5 of 12 frames", "5 frames"), ("1 of 22 frames", "12 frames"),
                          ("1 of 1 frame)", "22 frames")]}[lang]
        for (k, n), bez_karty, (czesc, tip) in zip(((1, 2), (2, 5), (5, 12), (1, 22), (1, 1)),
                                                   (1, 2, 5, 12, 22), odmiana):
            assert czesc in i18n.t_plural("repair.preview_part", n, value="'v'", k=k)
            assert i18n.t_plural("repair.region_outside_tip", bez_karty, value="'v'",
                                 canon="Veil").startswith(tip)
    finally:
        i18n.set_lang("pl")


def test_grupa_poza_regionem_odmowa_z_liczba_i_zero_zapisu(qapp, tmp_path):
    """Folder, którego żadnej klatki region nie obejmuje: błąd grupy mówi, że karta nie sprowadzi
    żadnej z N klatek, przycisk wygaszony, pliki nietknięte. Falsyfikator: `ready` liczony po
    wszystkich klatkach grupy → przycisk aktywny."""
    from horreum.gui import i18n, queries
    con = db.open_db(str(tmp_path / "p.db"))
    root = tmp_path / "ASTRO_"
    pliki = [_klatka(con, root, rf"LIGHTS\Veil\cam\p{k}.fits", wsp=POZA, seed=k)[1] for k in range(2)]
    przed = [p.read_bytes() for p in pliki]
    dlg = _okno(con, queries.nameless_frames(con))
    g = _wpisz(dlg, "Veil")
    powod = i18n.t_plural("repair.err.region_none", 2, value="'Veil'", canon="Veil")
    assert dlg.error.text() == i18n.t("repair.err.group", folder=g["label"], reason=powod)
    assert not dlg.save_btn.isEnabled()
    _zapisz(dlg)
    assert [p.read_bytes() for p in pliki] == przed
    dlg.reject()
    con.close()


def test_wariant_poza_regionem_idzie_za_oryginalem_z_TEGO_zapisu(qapp, tmp_path):
    """Oryginał w regionie z nagrobkiem ręki (bez karty przebieg go pomija - zostaje bez obiektu)
    i jego wariant poza regionem w jednym oknie: karta oryginału gasi nagrobek, przebieg nazywa
    najpierw oryginał (region), potem wariant (bliźniak) - więc OBA dostają kartę, a po prawdziwym
    `run_resolver` oba są `Veil`. Falsyfikator: wariant pytany obiektem oryginału ze stanu bazy
    (nagrobek - bez obiektu) → wariant poza regionem bez karty."""
    con = db.open_db(str(tmp_path / "w.db"))
    root = tmp_path / "ASTRO_"
    o, po = _klatka(con, root, r"STACKS\Veil\Ha\o.fits", kind="master_light", seed=1)
    v, pv = _klatka(con, root, r"STACKS\Veil\Ha\o_autocrop.fits", kind="master_light", wsp=POZA,
                    seed=2)
    repo.link_stack_variant(con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                            source="user", now=NOW)
    repo.user_assign_object(con, alias_norm=None, canon="M42", catalog="M", kind="deep_sky",
                            frame_ids=[o], now=NOW)
    repo.clear_object_assignment(con, frame_ids=[o], now=NOW)
    resolver.run_resolver(con, NOW)
    assert (_obiekt(con, o), _obiekt(con, v)) == (None, None)
    assert resolver.fakty_karty_klatek(con, [v])[v].twin_canon is None
    dlg = _okno(con, _wiersze(con, [o, v]))
    _wpisz(dlg, "Veil")
    assert dlg.save_btn.isEnabled() and dlg.error.text() == ""
    _zapisz(dlg)
    assert [_karta(po), _karta(pv)] == ["Veil", "Veil"]
    resolver.run_resolver(con, NOW)
    assert [_obiekt(con, o), _obiekt(con, v)] == ["Veil", "Veil"]
    dlg.reject()
    con.close()


def test_wariant_za_oryginalem_z_karta_NAZWY_z_TEGO_zapisu_bez_karty_regionu(qapp, tmp_path):
    """Oryginał (poza regionem) dostaje w tym samym oknie kartę NAZWY (`M 42`), a jego wariant
    (w promieniu Veil) leży w osobnej grupie z `Veil`: przebieg nazwie oryginał nazwą, a wariant
    pójdzie za nim bliźniakiem (bliźniak bije region) - więc karta `Veil` wariantu go nie sprowadzi.
    Grupa wariantu mówi powód i blokuje zapis; po jej odznaczeniu zapis idzie dla oryginału, plik
    wariantu nietknięty, a prawdziwy `run_resolver` daje OBU obiekt nazwy. Falsyfikator: grupa nazwy
    bez wpisu do zbioru zapisu (`przyszly`) → wariant pytany regionem, karta `Veil` przechodzi."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from horreum.gui import i18n
    con = db.open_db(str(tmp_path / "z.db"))
    root = tmp_path / "ASTRO_"
    o, po = _klatka(con, root, r"STACKS\Orion\Ha\o.fits", kind="master_light", wsp=POZA, seed=1)
    v, pv = _klatka(con, root, r"STACKS\Veil\Ha\o_autocrop.fits", kind="master_light", seed=2)
    repo.link_stack_variant(con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                            source="user", now=NOW)
    przed = pv.read_bytes()
    dlg = _okno(con, _wiersze(con, [o, v]))
    g_o, g_v = sorted(dlg._groups, key=lambda g: g["rows"][0]["frame_id"] != o)
    for g, tekst in ((g_o, "M 42"), (g_v, "Veil")):
        if not g["check"].isChecked():
            QTest.mouseClick(g["check"], Qt.LeftButton)
        g["edit"].clear()
        QTest.keyClicks(g["edit"], tekst)
    assert g_o["preview"].text() == i18n.t("repair.preview", value="'NGC 1976'")
    powod = i18n.t_plural("repair.err.region_none", 1, value="'Veil'", canon="Veil")
    assert dlg.error.text() == i18n.t("repair.err.group", folder=g_v["label"], reason=powod)
    assert not dlg.save_btn.isEnabled()
    QTest.mouseClick(g_v["check"], Qt.LeftButton)              # człowiek odznacza grupę wariantu
    assert dlg.error.text() == "" and dlg.save_btn.text() == i18n.t("repair.save_btn_n", n=1)
    _zapisz(dlg)
    assert (_karta(po), pv.read_bytes() == przed) == ("NGC 1976", True)
    dlg.reject()
    resolver.run_resolver(con, NOW)
    kanon = resolver.resolve_name(resolver.alias_lookup(con), "M 42")[0].canon
    assert (_obiekt(con, o), _obiekt(con, v)) == (kanon, kanon)
    con.close()


def test_wariant_za_oryginalem_z_nieaktualnym_naglowkiem_odmowa(qapp, tmp_path):
    """Oryginał jest `Veil` z regionu, ale jego nagłówek po ostatnim `Rozwiąż` mówi `NGC 6992` -
    przebieg przepnie oryginał na `NGC 6992` (nagłówek bije region), a wariant pójdzie za nim. Karta
    `Veil` wariantu nie sprowadziłaby go do `Veil`: okno odmawia, plik nietknięty, a prawdziwy
    przebieg potwierdza obiekt, którego bramka się spodziewała. Falsyfikator: obiekt oryginału ze
    stanu bazy (`Veil`) → karta zapisana, wariant po przebiegu w `NGC6992`."""
    from horreum.gui import i18n
    con = db.open_db(str(tmp_path / "n.db"))
    root = tmp_path / "ASTRO_"
    o, po = _klatka(con, root, r"STACKS\Veil\Ha\o.fits", kind="master_light", seed=1)
    v, pv = _klatka(con, root, r"STACKS\Veil\Ha\o_autocrop.fits", kind="master_light", wsp=POZA,
                    seed=2)
    resolver.run_resolver(con, NOW)                     # oryginał `Veil` z regionu, wariant bez
    repo.link_stack_variant(con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                            source="user", now=NOW)
    fits.setval(str(po), "OBJECT", value="NGC 6992")
    _wciagnij(con, po)
    assert (_obiekt(con, o), _obiekt(con, v)) == ("Veil", None)
    przed = pv.read_bytes()
    dlg = _okno(con, _wiersze(con, [v]))
    g = _wpisz(dlg, "Veil")
    powod = i18n.t_plural("repair.err.region_none", 1, value="'Veil'", canon="Veil")
    assert dlg.error.text() == i18n.t("repair.err.group", folder=g["label"], reason=powod)
    _zapisz(dlg)
    assert pv.read_bytes() == przed
    dlg.reject()
    resolver.run_resolver(con, NOW)
    assert (_obiekt(con, o), _obiekt(con, v)) == ("NGC6992", "NGC6992")
    con.close()


def test_nagrobek_reki_karta_Veil_gasi_go_i_PRZEBIEG_sprowadza(qapp, tmp_path):
    """Klatki w regionie, którym człowiek przypisał obiekt ręką i cofnął (nagrobek - drabina je
    pomija): kubełek „cofnięte ręką” → `veil` → karta w plikach gasi nagrobek, a przebieg sprowadza
    klatki do `Veil` szczeblem regionu."""
    from horreum.gui import queries
    con = db.open_db(str(tmp_path / "g.db"))
    root = tmp_path / "ASTRO_"
    ids = [_klatka(con, root, rf"LIGHTS\Veil\cam\g{k}.fits", seed=k)[0] for k in range(2)]
    repo.user_assign_object(con, alias_norm=None, canon="M42", catalog="M", kind="deep_sky",
                            frame_ids=ids, now=NOW)
    repo.clear_object_assignment(con, frame_ids=ids, now=NOW)
    resolver.run_resolver(con, NOW)
    assert [_obiekt(con, f) for f in ids] == [None, None]          # nagrobek trzyma
    dlg = _okno(con, queries.nameless_frames(con, cleared=True))
    _wpisz(dlg, "veil")
    _zapisz(dlg)
    resolver.run_resolver(con, NOW)
    assert [_obiekt(con, f) for f in ids] == ["Veil", "Veil"]
    assert con.execute("SELECT count(*) FROM frame WHERE object_source = 'user_cleared'"
                       ).fetchone()[0] == 0
    dlg.reject()
    con.close()


def test_slowo_spoza_drabiny_w_regionie_dalej_odmowa(qapp, tmp_path):
    """Region przyjąłby każdy tekst, którego drabina nazw nie zna - bramka świadomie nie: karta ma
    NAZYWAĆ obiekt. Słowo spoza drabiny w regionie odmawia jak dotąd, a walidator nazwy odmawia
    także samemu `Veil` (wyjątek regionu żyje wyłącznie w planie grupy). Falsyfikator:
    `kanon_regionu_karty` zwracający region dla każdego tekstu → karta „Wesolinka…” w pliku."""
    from horreum.gui import i18n, queries
    from horreum.gui.app import _validate_object_value
    con = db.open_db(str(tmp_path / "s.db"))
    _klatka(con, tmp_path / "ASTRO_", r"LIGHTS\Veil\cam\s.fits")
    dlg = _okno(con, queries.nameless_frames(con))
    g = _wpisz(dlg, "Wesolinka Kosmiczna 7")
    powod = i18n.t("repair.err.unresolvable", text="Wesolinka Kosmiczna 7")
    assert dlg.error.text() == i18n.t("repair.err.group", folder=g["label"], reason=powod)
    assert not dlg.save_btn.isEnabled()
    assert _validate_object_value(con, "Veil") == (None, i18n.t("repair.err.unresolvable",
                                                                text="Veil"))
    dlg.reject()
    con.close()
