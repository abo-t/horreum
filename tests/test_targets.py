"""PLANER CELÓW (T3): progi typo-zależne, zestawy, pokrycie ze szwem osi OBIEKT, luka per kanał,
koszt Księżyca i kolejność.

Meta-testów NIE kopiujemy — `test_repo_safety`/`test_gui_isolation` chodzą po `rglob` i kryją nowy
moduł same (T1 §7). Tu pinujemy zachowanie, którego one nie widzą.
"""
import json
import os
from datetime import date, datetime, timezone

import pytest

from horreum import db, repo, sky, targets

NOW = "2026-07-31T12:00:00+00:00"
BEDARGOWO = sky.Site(observatory_id=1, name="Będargowo", lat_deg=53.3890, lon_deg=14.4424,
                     frames=13250)


def _t(canon, typ, *, a=10.0, b=None, m=None, mb=False, r=90.0, d=45.0, n=(), layer="core"):
    return targets.Target(canon=canon, type=typ, ra_deg=r, dec_deg=d, major_arcmin=a,
                          minor_arcmin=b, mag=m, mag_from_b=mb, aliases=tuple(n), layer=layer,
                          why=None, size_source=None)


# ─────────────────────────────────────────────────────────────── progi typo-zależne (§3)

def test_progi_sa_typo_zalezne():
    """Mgławica emisyjna „mag 20" PRZECHODZI (dla niej magnitudo kłamie), galaktyka mag 14 odpada,
    ciemna ma własny, wyższy próg rozmiaru."""
    assert targets.feasible(_t("Sh2-1", "HII", a=10.0, m=20.0))
    assert not targets.feasible(_t("NGC1", "G", a=10.0, m=14.0))
    assert targets.feasible(_t("NGC2", "G", a=10.0, m=12.0))
    assert not targets.feasible(_t("LDN1", "DrkN", a=12.0))
    assert targets.feasible(_t("LDN2", "DrkN", a=20.0))


def test_typ_spoza_taksonomii_odpada_jawnie():
    """`t` w pliku człowieka pisze człowiek — gromada nie ma prawa wejść „resztą"."""
    assert not targets.feasible(_t("Cr464", "OCl", a=60.0))
    assert not targets.feasible(_t("X", "cos-nowego", a=60.0))


def test_magnitudo_z_b_dostaje_korekte():
    """B−V galaktyk to +0,7…1,0 mag; bez korekty próg odrzuciłby galaktykę jaśniejszą od progu."""
    assert targets.feasible(_t("NGC3", "G", a=10.0, m=13.5, mb=True))
    assert not targets.feasible(_t("NGC3", "G", a=10.0, m=13.5))


def test_galaktyka_bez_magnitudo_odpada_mglawica_nie():
    assert not targets.feasible(_t("NGC4", "G", a=10.0))
    assert targets.feasible(_t("Sh2-2", "HII", a=10.0))


# ─────────────────────────────────────────────── filtr kadru (dług T5 „podłoga optyki", PL-1, PL-2)

def _rigset(name, fov_x, fov_y, config_id=1):
    return targets.RigSet(config_id=config_id, telescope=name, cameras=("ASI2600MM",), mono=True,
                          fov_x_arcmin=fov_x, fov_y_arcmin=fov_y, lights=10, reason=None)


A140R_SET = _rigset("A140R", 103.0, 69.0, 1)
RC8_SET = _rigset("RC8", 50.5, 33.7, 2)


def test_filtr_kadru_bez_parku_albo_bez_progu_nie_odsiewa():
    """Rozstrzygnięcie ②: domyślne `rigs=()` = brak odsiewu sprzętowego, a park bez progu też
    niczego nie tnie: stare wołania `feasible(t)` dają to samo co przed filtrem."""
    kropka = _t("Sh2-85", "HII", a=6.0)
    assert targets.feasible(kropka, min_fill=0.9, max_panels=1)
    assert targets.feasible(kropka, (A140R_SET,))


def test_filtr_kadru_to_lub_po_parku():
    """Rozstrzygnięcie ①: „mam czym to zrobić". Cel 15' wypełnia A140R w 22 %, RC8 w 45 %; przy
    progu 30 % przechodzi z parkiem {A140R, RC8}, odpada z samym A140R."""
    t = _t("Sh2-112", "HII", a=15.0)
    assert targets.feasible(t, (A140R_SET, RC8_SET), min_fill=0.3)
    assert not targets.feasible(t, (A140R_SET,), min_fill=0.3)


def test_oba_progi_musi_spelnic_ten_sam_zestaw():
    """60'x40' w A140R to jeden kadr przy 58 %, w RC8 mozaika (100 %). Próg 70 % + jeden kadr:
    żaden zestaw nie robi obu naraz, więc cel odpada - choć każdy próg z osobna przepuszcza."""
    t = _t("Sh2-91", "HII", a=60.0, b=40.0)
    rigs = (A140R_SET, RC8_SET)
    assert targets.feasible(t, rigs, min_fill=0.7)
    assert targets.feasible(t, rigs, max_panels=1)
    assert not targets.feasible(t, rigs, min_fill=0.7, max_panels=1)


def test_filtr_kadru_nie_przepuszcza_tego_co_odcielyby_progi_typu():
    """Sprzęt ZAWĘŻA, nigdy nie poszerza: galaktyka bez magnitudo odpada przy dowolnym parku."""
    assert not targets.feasible(_t("NGC4", "G", a=40.0), (A140R_SET,), min_fill=0.1)


def test_predykat_kadru_brak_kadrowania_nie_przechodzi():
    assert not targets.rig_fits(None, min_fill=0.1)
    assert not targets.rig_fits(None)


@pytest.mark.parametrize("maly_pierwszy", [True, False])
def test_dwa_zestawy_jednego_teleskopu_nie_nadpisuja_kadrowania(maly_pierwszy):
    """Optyka z dwiema kamerami to DWA zestawy o różnym polu widzenia. Słownik kadrowania po nazwie
    teleskopu oddawał kadr zestawu iterowanego później - przy filtrze `best_rig` wskazywał mały
    kadr, a odczyt jego wypełnienia trafiał w duży. W obu kolejnościach iteracji odczyt idzie za
    tożsamością zestawu."""
    maly = _rigset("ED120R", 40.0, 30.0, 7)
    duzy = _rigset("ED120R", 200.0, 140.0, 11)
    rigs = (maly, duzy) if maly_pierwszy else (duzy, maly)
    t = _t("Sh2-90", "HII", a=20.0)
    framing, best = targets._framing_for(t, rigs, 0.10, min_fill=0.3, max_panels=1)
    assert best is maly and set(framing) == {7, 11}
    row = targets.TargetRow(target=t, window=None, framing=framing, best_rig=best,
                            coverage=None, cost={}, recommend=None, recommend_reason=None)
    assert row.framing_in(best).frame_fill == pytest.approx(20.0 / 30.0)
    assert row.framing_in(duzy).frame_fill == pytest.approx(20.0 / 140.0)
    assert row.framing_in(None) is None
    assert targets.feasible(t, rigs, min_fill=0.3, max_panels=1)


def test_koercja_pola_pisanego_recznie():
    """Plik człowieka pisze CZŁOWIEK: `"a": "15"` musi zachować się jak `15.0` (kanon W3)."""
    t = targets._target({"c": "WR134", "t": "EmN", "r": "302.55", "d": "36.17", "a": "15"},
                        "curated")
    assert t.major_arcmin == 15.0 and t.ra_deg == pytest.approx(302.55)
    assert targets.feasible(t)


def test_rekord_bez_obowiazkowego_pola_wybucha_od_razu():
    with pytest.raises(ValueError, match="major_arcmin"):
        targets._target({"c": "X", "t": "EmN", "r": 1.0, "d": 2.0}, "curated")


# ─────────────────────────────────────────────────────────────── asset i indeks (§5)

def test_asset_repo_ma_kotwice_i_curated_zawsze():
    """Asset, który LEŻY w repo (to on jedzie w wheelu), plus D-0731-11: curated bezwarunkowo."""
    core = targets.load_targets(("core",))
    canons = {t.canon for t in core}
    assert "CTB1" in canons and "WR134" in canons          # curated doklejony do samego rdzenia
    assert "WR134" in {t.canon for t in targets.load_targets(("cirrus",))}
    ctb = [t for t in core if t.canon == "CTB1"][0]
    assert ctb.type == "SNR" and ctb.major_arcmin == pytest.approx(34.0, abs=0.5)


def test_cache_assetu_widzi_podmiane_pliku(tmp_path, monkeypatch):
    """Dług P-A #6: `lru_cache` na samych warstwach zamrażał katalog na CAŁY proces, więc
    `scripts/build_catalog.py` odpalony obok działającego okna nie odsłaniał się do restartu.
    Kluczem cache'u jest dziś `mtime_ns` — sygnał zmiany pliku wg kanonu repo (NIGDY rozmiar)."""
    import json
    from horreum import targets as T

    data = {"targets": [{"c": "TEST1", "t": "EmN", "r": 10.0, "d": 20.0, "a": 30.0}]}
    asset = tmp_path / "targets_core.json"
    asset.write_text(json.dumps(data), encoding="utf-8")
    # Warstwa `curated` czyta dziś plik człowieka z assetów RESOLVERA (D-OW-1/E′); podmiana
    # `resources.files` ignoruje pakiet, więc obie warstwy jadą z `tmp_path`.
    wlasne = tmp_path / "objects_own.json"
    wlasne.write_text('{"targets": []}', encoding="utf-8")
    monkeypatch.setattr(T.resources, "files", lambda _pkg: tmp_path)

    assert {t.canon for t in T.load_targets(("core",))} == {"TEST1"}
    data["targets"][0]["c"] = "TEST2"
    asset.write_text(json.dumps(data), encoding="utf-8")
    os.utime(asset, ns=(asset.stat().st_atime_ns, asset.stat().st_mtime_ns + 1_000_000_000))
    assert {t.canon for t in T.load_targets(("core",))} == {"TEST2"}


def test_indeks_nie_zawiera_nazw_potocznych():
    """Falsyfikowalny wariant reguły „nazwa potoczna nie niesie pokrycia": „Eastern Veil" nosi
    DWA rekordy (NGC6992/NGC6995), więc jako klucz pokrycia doliczyłaby cudze godziny."""
    idx = targets.coverage_index(targets.load_targets(targets.ALL_LAYERS))
    assert "Eastern Veil" not in idx and "Eagle Nebula" not in idx
    assert "LBN807" in idx and idx["LBN807"].canon == "IC410"     # alias KATALOGOWY niesie


def test_kolizja_warstw_generowanych_wybucha_a_curated_wygrywa():
    a = _t("IC410", "HII", n=("LBN807",))
    b = _t("LBN807", "EmN", layer="cirrus")
    with pytest.raises(AssertionError, match="LBN807"):
        targets.coverage_index([a, b])
    człowiek = _t("LBN807", "EmN", layer="curated")
    assert targets.coverage_index([a, człowiek])["LBN807"] is człowiek
    assert targets.coverage_index([człowiek, a])["LBN807"] is człowiek


# ─────────────────────────────────────────────────────────────── kanały i luka (§6)

def test_luka_liczy_sie_per_kanal_nie_per_paleta():
    """Miara Zdzinia to „Ha bez OIII": 4 h samego Ha to LUKA, choć paleta wąska ma godziny."""
    ch = targets.channel_hours({"Ha": 4.2})
    assert ch["Ha"] == 4.2 and ch["OIII"] == 0.0
    cov = targets._coverage_for(_t("NGC7000", "HII"), {"NGC7000": {"by_filter": {"Ha": 4.2},
                                                                  "n_null": 0}}, 1.0)
    assert "OIII" in cov.gaps and "SII" in cov.gaps and "Ha" not in cov.gaps


def test_duoband_zasila_ha_i_oiii():
    """L-eXtreme fizycznie zbiera Ha+OIII — IC63 z 8,3 h duo nie ma „braku Ha"."""
    ch = targets.channel_hours({"L-eXtreme": 8.3})
    assert ch["Ha"] == 8.3 and ch["OIII"] == 8.3 and ch["SII"] == 0.0


def test_brak_filtra_to_broadband_a_nieznany_filtr_wlasny_kubelek():
    ch = targets.channel_hours({None: 2.5, "L-Pro": 1.0, "DziwnyFiltr": 9.0})
    assert ch[targets.RGB] == 3.5 and ch["other"] == 9.0


def test_galaktyka_nie_ma_luki_w_ha():
    assert targets.required_channels("G") == (targets.RGB,)
    assert set(targets.required_channels("HII")) == {targets.RGB, "Ha", "OIII", "SII"}


def test_godziny_sumuja_sie_po_wszystkich_dopasowanych_kanonach():
    """Dopasowanie jest WIELE→JEDEN: archiwum może mieć i `IC410`, i `LBN807`."""
    cov = targets._coverage_for(_t("IC410", "HII"),
                                {"IC410": {"by_filter": {"Ha": 2.0}, "n_null": 1},
                                 "LBN807": {"by_filter": {"Ha": 0.8}, "n_null": 0}}, 1.0)
    assert cov.hours_by_channel["Ha"] == pytest.approx(2.8)
    assert cov.archive_canons == ("IC410", "LBN807") and cov.frames_no_exptime == 1


# ─────────────────────────────────────────────────────────────── Księżyc i kolejność (§6)

class _W:
    def __init__(self, visible=True, cost=1.0, hours=5.0, alt=60.0, moon=True):
        self.visible, self.hours_above, self.max_alt_deg = visible, hours, alt
        self.moon = _M(cost) if moon else None


class _M:
    def __init__(self, c):
        self._c = c

    def cost(self, band=1.0):
        return 1.0 + (self._c - 1.0) * band


def test_brak_nocy_nie_wywala_wyceny():
    """`Window.moon is None` (brak nocy żeglarskiej — koło podbiegunowe w czerwcu) => 1,00
    dla każdej palety, nigdy AttributeError."""
    assert targets.palette_costs(_W(moon=False)) == {"broadband": 1.0, "duoband": 1.0,
                                                     "narrowband": 1.0}


def test_rada_jest_najtansza_luka_wykonalna_zestawem():
    cov = targets._coverage_for(_t("NGC7000", "HII"),
                                {"NGC7000": {"by_filter": {"Ha": 4.0}, "n_null": 0}}, 1.0)
    cost = {"broadband": 8.1, "duoband": 2.4, "narrowband": 1.3}
    mono = targets.RigSet(config_id=1, telescope="A140R", cameras=("ASI2600MM",), mono=True,
                          fov_x_arcmin=103.0, fov_y_arcmin=68.9, lights=10, reason=None)
    osc = targets.RigSet(config_id=2, telescope="A140R", cameras=("ASI2600MC",), mono=False,
                         fov_x_arcmin=103.0, fov_y_arcmin=68.9, lights=10, reason=None)
    assert targets.recommend_channel(cov, cost, mono)[0] in ("OIII", "SII")
    # OSC nie umie SII — rada musi zostać w tym, co zestaw REALNIE zrobi (duoband)
    channel, reason = targets.recommend_channel(cov, cost, osc)
    assert channel == "OIII" and reason is None
    # jedyna luka = SII: mono ją zrobi, matryca kolorowa NIE — i ma to powiedzieć wprost
    tylko_sii = targets._coverage_for(
        _t("X", "HII"), {"X": {"by_filter": {"Ha": 4.0, "OIII": 4.0, "R": 4.0}, "n_null": 0}}, 1.0)
    assert tylko_sii.gaps == ("SII",)
    assert targets.recommend_channel(tylko_sii, cost, mono) == ("SII", None)
    assert targets.recommend_channel(tylko_sii, cost, osc) == (None, "rig_cannot")


def test_cel_bez_luki_nie_dostaje_rady():
    cov = targets._coverage_for(_t("Sh2-131", "HII"),
                                {"Sh2-131": {"by_filter": {"Ha": 20.0, "OIII": 15.0, "SII": 9.0,
                                                           "R": 4.0}, "n_null": 0}}, 1.0)
    assert cov.gaps == () and targets.recommend_channel(cov, {"broadband": 1.0}, None)[1] == "no_gap"


def _row(canon, *, visible=True, gaps=("RGB",), cost=1.0, hours=5.0, alt=60.0, recommend="RGB"):
    cov = targets.Coverage(hours_by_filter={}, hours_by_channel={}, gaps=tuple(gaps),
                           archive_canons=(), frames_no_exptime=0)
    return targets.TargetRow(target=_t(canon, "HII"), window=_W(visible, hours=hours, alt=alt),
                             framing={}, best_rig=None, coverage=cov,
                             cost={"broadband": cost, "duoband": cost, "narrowband": cost},
                             recommend=recommend, recommend_reason=None)


def test_cel_pod_horyzontem_nie_stoi_przed_widocznym():
    """Pułapka T1 §8a: cel pod horyzontem ma UCZCIWE `cost=1,00` i po samym koszcie byłby pierwszy."""
    pod = _row("POD", visible=False, cost=1.0)
    widoczny = _row("WID", visible=True, cost=6.0)
    assert sorted([pod, widoczny], key=targets._sort_key)[0] is widoczny


def test_cel_bez_luki_nie_stoi_przed_czekajacym():
    domkniety = _row("AAA", gaps=(), recommend=None, cost=1.0)
    z_luka = _row("ZZZ", gaps=("OIII",), recommend="OIII", cost=1.0)
    assert sorted([domkniety, z_luka], key=targets._sort_key)[0] is z_luka


def test_przy_nowiu_kolejnosc_nie_degeneruje_sie_do_alfabetu():
    """Przy nowiu KAŻDY cel kosztuje 1,00, a luki ma prawie każdy — bez wysokości kulminacji
    lista wracała do porządku alfabetycznego (firsthand: 1555 wierszy od bezimiennych `G0…`)."""
    nisko = _row("AAA", cost=1.0, hours=5.0, alt=35.0)
    wysoko = _row("ZZZ", cost=1.0, hours=5.0, alt=80.0)
    assert sorted([nisko, wysoko], key=targets._sort_key)[0] is wysoko


# ─────────────────────────────────────────────────────────────── baza: zestawy, plan (§4, §7)

@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MM', 3.76, 1, ?)", (NOW,))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MC', 3.76, 0, ?)", (NOW,))
    for tel in ("A140R", "RC8"):
        c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, ?, ?)",
                  (tel, "proposed", NOW))
    for tel_id, cam_id in ((1, 1), (1, 2), (2, 1)):        # A140R×MM, A140R×MC, RC8×MM
        c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
                  "VALUES (?, ?, 'proposed', ?)", (tel_id, cam_id, NOW))
    c.execute("INSERT INTO observatory(name, lat, lon, status, created_at) "
              "VALUES ('Będargowo', 53.3890, 14.4424, 'proposed', ?)", (NOW,))
    yield c
    c.close()


def _light(con, *, config_id, sha1, focal, camera_id=1, object_id=None, filter_canon=None,
           exptime=600.0, observatory_id=1):
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
                "filter_canon, observatory_id, first_seen_at) "
                "VALUES (?, 'light', 'fits', ?, ?, ?, ?, ?, ?)",
                (sha1, camera_id, config_id, object_id, filter_canon, observatory_id, NOW))
    fid = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1,)).fetchone()["id"]
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, focallen, xpixsz, exptime) "
                "VALUES (?, ?, '2026-01-02T22:00:00', ?, 3.76, ?)",
                (fid, '{"NAXIS1": 6248, "NAXIS2": 4176}', focal, exptime))
    return fid


def _obiekt(con, canon, kind="deep_sky"):
    con.execute("INSERT INTO object(canon, catalog, kind) VALUES (?, NULL, ?)", (canon, kind))
    return con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()["id"]


def test_zestawy_dedup_po_fov_ale_niosa_kamery(con):
    """Trzy kamery na jednej optyce dają TO SAMO kadrowanie — i inne palety."""
    for i in range(4):
        _light(con, config_id=1, sha1=f"a{i}", focal=784.0, camera_id=1)
        _light(con, config_id=2, sha1=f"b{i}", focal=784.0, camera_id=2)
        _light(con, config_id=3, sha1=f"c{i}", focal=1600.0, camera_id=1)
    rigs, skipped = targets.rig_sets(con)
    assert skipped == ()
    a140 = [r for r in rigs if r.telescope == "A140R"]
    assert len(a140) == 1 and a140[0].cameras == ("ASI2600MC", "ASI2600MM") and a140[0].mono
    assert a140[0].lights == 8
    assert {r.telescope for r in rigs} == {"A140R", "RC8"}


def test_config_bez_fov_idzie_poza_plan_z_powodem(con):
    """`round(None)` byłby TypeError dokładnie tam, gdzie „brak faktu nie jest zerem"."""
    for i in range(6):
        _light(con, config_id=1, sha1=f"d{i}", focal=784.0 if i < 3 else 1200.0)
    rigs, skipped = targets.rig_sets(con)
    assert [r.reason for r in skipped] == ["mixed_optics"] and rigs == ()


def test_pokrycie_po_aliasie_katalogowym_z_zywym_kanonem_uzytkownika(con):
    """D-T2-d na realnym przypadku: archiwum zna `LBN807`, katalog kanonizuje go jako `IC410`."""
    oid = _obiekt(con, "LBN807")
    for i in range(3):
        _light(con, config_id=1, sha1=f"e{i}", focal=784.0, object_id=oid, filter_canon="Ha",
               exptime=1200.0)
    per, unfiltered_mono = targets.archive_coverage(con)
    assert unfiltered_mono == 0 and per["LBN807"]["by_filter"]["Ha"] == pytest.approx(1.0)
    res = targets.plan(con, night=date(2026, 8, 15), find="IC410")
    row = [r for r in res.rows if r.target.canon == "IC410"][0]
    assert row.coverage.archive_canons == ("LBN807",)


def test_reszta_jawna_z_kotwica_domkniecia_godzin(con):
    """Kanon spoza katalogu (region `Veil`) NIE MOŻE zniknąć: bez jawnej reszty rachunek pokrycia
    świeci fałszywie na zielono."""
    veil = _obiekt(con, "Veil", kind="region")
    ctb = _obiekt(con, "CTB1")
    for i in range(2):
        _light(con, config_id=1, sha1=f"v{i}", focal=784.0, object_id=veil, filter_canon="Ha",
               exptime=1800.0)
    _light(con, config_id=1, sha1="ctb", focal=784.0, object_id=ctb, filter_canon="Ha",
           exptime=3600.0)
    res = targets.plan(con, night=date(2026, 8, 15))
    assert res.unmatched == {"Veil": pytest.approx(1.0)}
    per, _ = targets.archive_coverage(con)
    total = sum(sum(e["by_filter"].values()) for e in per.values())
    idx = targets.coverage_index(targets.load_targets(targets.ALL_LAYERS))
    dopasowane = sum(sum(e["by_filter"].values()) for c, e in per.items() if c in idx)
    assert dopasowane + sum(res.unmatched.values()) == pytest.approx(total)


# ───────────────────────────────────────────── most rodowodu stosów do planera (I-2e, paczka P-I)

def _master(con, sha1, object_id, *, path, filter_canon="Ha"):
    """Klatka gotowego obrazu (`master_light`) — materiał `queries.stack_locations`.
    `path=None` znaczy „bez obecnej kopii" (klatka jest w bibliotece, pliku nie ma pod ręką)."""
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, object_id, "
                "filter_canon, first_seen_at) VALUES (?, 'master_light', 'xisf', 1, 1, ?, ?, ?)",
                (sha1, object_id, filter_canon, NOW))
    fid = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1,)).fetchone()["id"]
    if path is not None:
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V1', ?, 1)",
                    (fid, path))
    return fid


def _integracja(con, master_frame_id, wejscia, *, integ_hash="h"):
    from horreum import repo
    con.commit()                # pisarze `repo` biorą `BEGIN IMMEDIATE` — surowe INSERT-y fixture'u
    iid, _ = repo.upsert_integration(
        con, master_frame_id=master_frame_id, integ_hash=integ_hash, tool="WBPP",
        window_start=None, window_end=None, declared_rows=None, drizzle_inputs=None,
        disabled_inputs=None, degenerate=0, ambiguous=0, telescope_mismatch=0,
        unresolved_reason=None, now=NOW)
    for fid in wejscia:
        repo.link_integration(con, integration_id=iid, input_frame_id=fid,
                              asserted_by="window", now=NOW)
    return iid


def test_godziny_zintegrowane_licza_sub_raz_mimo_reprocessingu(con):
    """BRAMKA I-2e: pokrycie NIE ROŚNIE po dołożeniu reprocessingu tej samej nocy.

    `integration_input` jest POKRYCIEM, nie podziałem (fakt 20 briefu: 43 pary tej samej półki mają
    nakładające się okna). Suma po WIERSZACH relacji rosłaby od samego przeliczania archiwum —
    dlatego licznik stoi na `DISTINCT input_frame_id`. Test dokłada DRUGĄ integrację z tych samych
    trzech subów i żąda tej samej liczby godzin."""
    oid = _obiekt(con, "CTB1")
    subs = [_light(con, config_id=1, sha1=f"s{i}", focal=784.0, object_id=oid,
                   filter_canon="Ha", exptime=1200.0) for i in range(3)]
    m1 = _master(con, "m1", oid, path=r"R:\ASTRO_\CTB1\masterLight_a.xisf")
    _integracja(con, m1, subs)
    per, _ = targets.archive_coverage(con)
    assert per["CTB1"]["integrated"]["Ha"] == pytest.approx(1.0)      # 3 × 1200 s = 1 h

    m2 = _master(con, "m2", oid, path=r"R:\ASTRO_\CTB1\masterLight_a_drizzle_1x.xisf")
    _integracja(con, m2, subs, integ_hash="h")                        # ten sam zbiór wejść
    per, _ = targets.archive_coverage(con)
    assert per["CTB1"]["integrated"]["Ha"] == pytest.approx(1.0)      # BEZ ZMIANY — sub liczony raz
    assert len(per["CTB1"]["stacks"]) == 2                            # ale obrazy są DWA


def test_odrzucony_reka_sub_nie_wchodzi_w_godziny_obrazu(con):
    """Werdykt ręki „ta klatka NIE weszła" (I-2d) jest faktem, nie ukryciem wiersza."""
    from horreum import repo
    oid = _obiekt(con, "CTB1")
    subs = [_light(con, config_id=1, sha1=f"x{i}", focal=784.0, object_id=oid,
                   filter_canon="Ha", exptime=1800.0) for i in range(2)]
    m = _master(con, "mx", oid, path=r"R:\ASTRO_\CTB1\masterLight_b.xisf")
    iid = _integracja(con, m, subs)
    repo.judge_integration_input(con, integration_id=iid, input_frame_id=subs[0],
                                 excluded=1, now=NOW)
    per, _ = targets.archive_coverage(con)
    assert per["CTB1"]["integrated"]["Ha"] == pytest.approx(0.5)      # został JEDEN sub


def test_pokrycie_niesie_dwie_rozne_liczby_godzin_a_luki_stoja_na_zebranych(con):
    """Zebrane i zintegrowane to DWA różne fakty. „Nie zestackowałem" NIE jest luką w materiale —
    inaczej planer wysyłałby po kolejne godziny, które użytkownik już ma na dysku."""
    oid = _obiekt(con, "CTB1")
    subs = [_light(con, config_id=1, sha1=f"y{i}", focal=784.0, object_id=oid,
                   filter_canon="Ha", exptime=3600.0) for i in range(4)]
    m = _master(con, "my", oid, path=r"R:\ASTRO_\CTB1\masterLight_c.xisf")
    _integracja(con, m, subs[:1])                                    # zestackowana JEDNA z czterech
    res = targets.plan(con, night=date(2026, 8, 15), find="CTB1")
    row = [r for r in res.rows if r.target.canon == "CTB1"][0]
    assert row.coverage.hours_by_channel["Ha"] == pytest.approx(4.0)
    assert row.coverage.integrated_hours == pytest.approx(1.0)
    assert "Ha" not in row.coverage.gaps                              # 4 h zebrane domykają kanał
    assert row.coverage.stacks == ((m, r"R:\ASTRO_\CTB1\masterLight_c.xisf"),)


def test_stos_bez_lightow_zaklada_wlasny_wpis_zamiast_zniknac(con):
    """„Obraz jest, subów w archiwum nie ma" to ZNALEZISKO, nie szum — cichy ubytek celu byłby tą
    samą klasą błędu co cichy sufit listy."""
    oid = _obiekt(con, "CTB1")
    m = _master(con, "mz", oid, path=None)          # obraz BEZ obecnej kopii i bez subów w bazie
    per, _ = targets.archive_coverage(con)
    assert per["CTB1"]["by_filter"] == {}
    assert per["CTB1"]["stacks"] == [(m, None)]     # `path=None` = „nie mam go pod ręką", nie „nie ma"


def test_reszta_nie_klamie_przy_warstwie_niewczytanej(con):
    """`LDN1152` leży w CIRRUSIE — przy domyślnym rdzeniu nie jest „godzinami bez celu w katalogu",
    tylko celem z warstwy, której użytkownik nie wczytał."""
    oid = _obiekt(con, "LDN1152")
    _light(con, config_id=1, sha1="ldn", focal=784.0, object_id=oid, filter_canon="Ha")
    res = targets.plan(con, night=date(2026, 8, 15), layers=("core",))
    assert "LDN1152" not in res.unmatched


def test_plan_bez_stanowiska_z_gps_wybucha(tmp_path):
    c = db.open_db(str(tmp_path / "puste.db"))
    with pytest.raises(ValueError, match="GPS"):
        targets.plan(c, night=date(2026, 8, 15))
    c.close()


def test_plan_jest_read_only(con):
    """Kotwica §0: planer nie tyka ani schematu, ani danych."""
    for i in range(3):
        _light(con, config_id=1, sha1=f"r{i}", focal=784.0)
    przed = (db._user_version(con),
             con.execute("SELECT COUNT(*) FROM event").fetchone()[0],
             con.execute("SELECT COUNT(*) FROM frame").fetchone()[0])
    targets.plan(con, night=date(2026, 8, 15))
    po = (db._user_version(con),
          con.execute("SELECT COUNT(*) FROM event").fetchone()[0],
          con.execute("SELECT COUNT(*) FROM frame").fetchone()[0])
    assert przed == po


def test_plan_jest_deterministyczny_i_kadruje_bez_sufitu(con):
    for i in range(3):
        _light(con, config_id=1, sha1=f"s{i}", focal=784.0)
    a = targets.plan(con, night=date(2026, 8, 15))
    b = targets.plan(con, night=date(2026, 8, 15))
    assert [r.target.canon for r in a.rows] == [r.target.canon for r in b.rows]
    # D-0731-8: cel większy od kadru ZOSTAJE, z liczbą paneli
    veil = [r for r in a.rows if r.target.canon == "NGC6960"]
    assert veil and all(f.panels > 1 for f in veil[0].framing.values())
    assert veil[0].target.major_arcmin > 200


def test_limit_nie_jest_cichym_sufitem_a_liczniki_opisuja_noc(con):
    for i in range(3):
        _light(con, config_id=1, sha1=f"l{i}", focal=784.0)
    pelny = targets.plan(con, night=date(2026, 8, 15))
    uciety = targets.plan(con, night=date(2026, 8, 15), limit=5)
    assert len(uciety.rows) == 5 and uciety.hidden == len(pelny.rows) - 5
    assert uciety.counts["visible"] == pelny.counts["visible"]     # licznik opisuje NIEBO, nie ekran


def test_filtr_kadru_domyslnie_wylaczony_i_bez_sladu_w_wyniku(con):
    """Kryterium nadrzędne paczki: bez progów odpowiedź ta sama co przed filtrem: licznik
    `hidden_by_rig` nie istnieje, stan `off`."""
    for i in range(3):
        _light(con, config_id=1, sha1=f"f{i}", focal=784.0)
    res = targets.plan(con, night=date(2026, 8, 15), park=["A140R"])
    assert res.rig_filter == "off" and "hidden_by_rig" not in res.counts


def test_filtr_kadru_tnie_pule_przed_oknem_i_liczy_schowanych(con):
    """Rozstrzygnięcia ① i ④: odsiew w rdzeniu, liczony `sky.framing` przez `rig_fits`; licznik
    `feasible` + schowani = pula po progach typu; ranking ocalałych nietknięty (podciąg porządku
    bazowego); `best_rig` każdego wiersza spełnia próg."""
    for i in range(3):
        _light(con, config_id=1, sha1=f"a{i}", focal=784.0)
        _light(con, config_id=3, sha1=f"r{i}", focal=1600.0)
    park = ["A140R", "RC8"]
    base = targets.plan(con, night=date(2026, 8, 15), park=park)
    res = targets.plan(con, night=date(2026, 8, 15), park=park, min_fill=0.3, max_panels=1)
    assert res.rig_filter == "on" and (res.min_fill, res.max_panels) == (0.3, 1)
    assert res.counts["hidden_by_rig"] > 0
    assert res.counts["feasible"] + res.counts["hidden_by_rig"] == base.counts["feasible"]
    kept = [r.target.canon for r in res.rows]
    assert kept and kept == [c for c in (r.target.canon for r in base.rows) if c in set(kept)]
    for row in res.rows:
        fr = row.framing_in(row.best_rig)
        assert targets.rig_fits(fr, min_fill=0.3, max_panels=1)
    assert "NGC6960" not in kept                   # Veil ~210' - mozaika w każdym zestawie


def test_filtr_kadru_bez_parku_i_w_szukaniu_nie_dziala(con):
    """Rozstrzygnięcie ③: park nieustawiony = wszystkie teleskopy bazy, także historyczne, więc filtr
    WYŁĄCZONY i to jawnie (`no_park`). `--find` pomija progi, więc i ten (`find`)."""
    for i in range(3):
        _light(con, config_id=1, sha1=f"n{i}", focal=784.0)
    base = targets.plan(con, night=date(2026, 8, 15))
    res = targets.plan(con, night=date(2026, 8, 15), min_fill=0.9)
    assert res.park_source == "none" and res.rig_filter == "no_park"
    assert [r.target.canon for r in res.rows] == [r.target.canon for r in base.rows]
    found = targets.plan(con, night=date(2026, 8, 15), park=["A140R"], find="NGC6960",
                         max_panels=1)
    assert found.rig_filter == "find" and [r.target.canon for r in found.rows] == ["NGC6960"]


def test_park_zawezaja_zestawy(con):
    for i in range(3):
        _light(con, config_id=1, sha1=f"p{i}", focal=784.0)
        _light(con, config_id=3, sha1=f"q{i}", focal=1600.0)
    assert {r.telescope for r in targets.rig_sets(con)[0]} == {"A140R", "RC8"}
    assert {r.telescope for r in targets.rig_sets(con, park=["RC8"])[0]} == {"RC8"}


def test_przedciecie_deklinacja_nie_gubi_celu_z_pasa_granicznego(con):
    """Sufit kulminacji `90 − |lat − dec|` tnie z marginesem 0,5° — precesja J2000→data daje 0,15°.
    Falsyfikator: żaden cel odcięty nie byłby widoczny w pełnym rachunku."""
    for i in range(3):
        _light(con, config_id=1, sha1=f"g{i}", focal=784.0)
    site = sky.default_site(con)
    nw = sky.night_window(site, date(2026, 8, 15))
    odciete = [t for t in targets.load_targets(targets.ALL_LAYERS)
               if targets.feasible(t) and 90.0 - abs(site.lat_deg - t.dec_deg) < 30.0 - 0.5]
    assert odciete
    for t in odciete[:80]:
        w = sky.visibility_window(t.ra_deg, t.dec_deg, site, date(2026, 8, 15), min_alt=30.0,
                                  night=nw)
        assert not w.visible


# ─────────────────────────────────────────────────────────────── styk z T1 (§4a)

def test_night_window_daje_te_same_granice_co_okno_celu():
    """Wydzielenie ma być PRZENIESIENIEM kodu, nie zmianą zachowania."""
    dzien = date(2026, 8, 15)
    nw = sky.night_window(BEDARGOWO, dzien)
    z_siatka = sky.visibility_window(310.0, 45.0, BEDARGOWO, dzien, night=nw)
    bez = sky.visibility_window(310.0, 45.0, BEDARGOWO, dzien)
    assert z_siatka == bez
    assert nw.dark_start == bez.dark_start and nw.dark_end == bez.dark_end


def test_domyslna_noc_liczy_sie_z_dlugosci_geograficznej_nie_ze_strefy_maszyny():
    """Maszyna w UTC nie ma prawa przesunąć planu o dobę; po zakończeniu ciemności planujemy
    WIECZÓR DZISIEJSZY, w jej trakcie — noc trwającą."""
    w_nocy = datetime(2026, 8, 16, 0, 30, tzinfo=timezone.utc)      # środek nocy 15/16
    assert targets.default_night(BEDARGOWO, now=w_nocy) == date(2026, 8, 15)
    rano = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)
    assert targets.default_night(BEDARGOWO, now=rano) == date(2026, 8, 16)


# ─────────────────────────────────────────────────────────────── CLI (§8)

def test_cli_plan_nie_migruje_i_daje_json(con, tmp_path, capsys):
    from horreum import cli
    for i in range(3):
        _light(con, config_id=1, sha1=f"c{i}", focal=784.0)
    con.commit()
    path = str(tmp_path / "h.db")
    assert cli.main(["plan", path, "--night", "2026-08-15", "--json", "--limit", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["night"] == "2026-08-15" and out["site"]["name"] == "Będargowo"
    assert len(out["rows"]) == 3 and out["hidden"] > 0
    assert out["rigs"][0]["telescope"] == "A140R"


def test_cli_plan_kolumna_wypelnienia_i_filtr_kadru(con, tmp_path, capsys):
    """PL-1/PL-2 w CLI: `fill_pct` w każdym wierszu (miara `frame_fill` zestawu `best_rig`), blok
    `rig_filter` WYŁĄCZNIE przy poproszonym filtrze, napis licznika idzie za semantyką."""
    from horreum import cli
    for i in range(3):
        _light(con, config_id=1, sha1=f"k{i}", focal=784.0)
    con.commit()
    path = str(tmp_path / "h.db")
    assert cli.main(["plan", path, "--night", "2026-08-15", "--json", "--park", "A140R"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "rig_filter" not in out and "hidden_by_rig" not in out["counts"]
    assert all(0 < r["fill_pct"] <= 100 for r in out["rows"])
    assert cli.main(["plan", path, "--night", "2026-08-15", "--json", "--park", "A140R",
                     "--min-fill", "0.3", "--max-panels", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rig_filter"] == {"state": "on", "min_fill": 0.3, "max_panels": 1}
    assert out["counts"]["hidden_by_rig"] > 0
    assert all(r["fill_pct"] >= 30 and r["framing"]["A140R"]["panels"] == 1 for r in out["rows"])
    assert cli.main(["plan", path, "--night", "2026-08-15", "--park", "A140R",
                     "--max-panels", "1"]) == 0
    text = capsys.readouterr().out
    assert "wykonalnych twoim sprzetem" in text and "po progach" not in text
    assert cli.main(["plan", path, "--night", "2026-08-15", "--max-panels", "1"]) == 0
    assert "filtr kadru (maks. paneli 1) WYLACZONY: park nieustawiony" in capsys.readouterr().out


def test_cli_plan_procent_zamiast_ulamka_wybucha_przy_parsowaniu(con, tmp_path, capsys):
    """`--min-fill 30` (procent) przepuszczone odcięłoby cały katalog po cichu."""
    from horreum import cli
    con.commit()
    with pytest.raises(SystemExit):
        cli.main(["plan", str(tmp_path / "h.db"), "--min-fill", "30"])
    assert "0..1" in capsys.readouterr().err


@pytest.mark.parametrize("mm, mc", [(4, 2), (2, 4)])
def test_plan_z_dwiema_kamerami_na_jednej_optyce(con, tmp_path, capsys, mm, mc):
    """A140R z ASI2600MM (784 mm) i z ASI2600MC za reduktorem (400 mm): dwa zestawy, dwie etykiety,
    dwa kadrowania w każdym wierszu. Liczba lightów odwraca kolejność zestawów - wynik nie może od
    niej zależeć. CLI czyta wypełnienie TEGO zestawu, który rdzeń wybrał."""
    from horreum import cli
    for i in range(mm):
        _light(con, config_id=1, sha1=f"m{i}", focal=784.0)
    for i in range(mc):
        _light(con, config_id=2, sha1=f"k{i}", focal=400.0, camera_id=2)
    con.commit()
    rigs, _ = targets.rig_sets(con, park=["A140R"])
    assert sorted(r.name for r in rigs) == ["A140R (ASI2600MC)", "A140R (ASI2600MM)"]
    res = targets.plan(con, night=date(2026, 8, 15), park=["A140R"], min_fill=0.3, max_panels=1)
    assert res.rig_filter == "on" and res.rows
    for row in res.rows:
        assert set(row.framing) == {r.config_id for r in res.rigs}
        assert targets.rig_fits(row.framing_in(row.best_rig), min_fill=0.3, max_panels=1)
    assert any(len({round(f.frame_fill, 4) for f in row.framing.values()}) == 2
               for row in res.rows)
    assert cli.main(["plan", str(tmp_path / "h.db"), "--night", "2026-08-15", "--json", "--all",
                     "--park", "A140R", "--min-fill", "0.3", "--max-panels", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["canon"] for r in out["rows"]] == [row.target.canon for row in res.rows]
    for r_json, row in zip(out["rows"], res.rows):
        assert set(r_json["framing"]) == {r.name for r in res.rigs}
        assert r_json["best_rig"] == row.best_rig.name
        assert r_json["fill_pct"] == round(row.framing_in(row.best_rig).frame_fill * 100, 1)
        assert r_json["fill_pct"] >= 30


# ─────────────────────────────────────────────── złoty wynik: domyślny plan sprzed filtra kadru
# Oczekiwane wartości POLICZONE kodem z HEAD `9b7e522` (sprzed filtra kadru, worktree odłączony,
# import przypięty `sys.path.insert(0, worktree)` + odpięty finder instalacji edytowalnej, wydruk
# `horreum.__file__` wskazywał worktree). Test porównuje bieżący kod BEZ progów kadru z tą stałą,
# nie z samym sobą - dopisane kolumny wypełnienia są jedynym dozwolonym śladem zmiany.

ZLOTY_KATALOG = (
    _t("SYN-HII-8", "HII", a=8.0, r=300.0, d=40.0),
    _t("SYN-HII-25", "HII", a=25.0, b=15.0, r=310.0, d=45.0),
    _t("SYN-SNR-200", "SNR", a=200.0, b=150.0, r=315.0, d=30.0),
    _t("SYN-G-12", "G", a=12.0, m=9.0, r=10.0, d=41.0),
    _t("SYN-G-SLABA", "G", a=10.0, m=14.0, r=20.0, d=40.0),
    _t("SYN-G-B", "G", a=8.0, m=13.6, mb=True, r=190.0, d=60.0),
    _t("SYN-DRK-20", "DrkN", a=20.0, r=330.0, d=55.0),
    _t("SYN-DRK-10", "DrkN", a=10.0, r=330.0, d=56.0),
    _t("SYN-PN-7", "PN", a=7.0, b=5.0, r=283.0, d=33.0),
    _t("SYN-POLUDNIE", "HII", a=30.0, r=270.0, d=-30.0),
    _t("SYN-RFN-15", "RfN", a=15.0, r=60.0, d=25.0),
    _t("SYN-OCL", "OCl", a=30.0, r=100.0, d=20.0),
    _t("SYN-EMN-90", "EmN", a=90.0, b=50.0, r=305.0, d=50.0),
    _t("SYN-SNR-60", "SNR", a=60.0, b=40.0, r=250.0, d=65.0),
)

ZLOTA_PROJEKCJA = {
    "counts": {"pool": 14, "feasible": 11, "above_horizon": 10, "matched": 3, "visible": 9,
               "rows": 9, "marked": 1, "hidden_by_status": 1},
    "hidden": 0,
    "rigs": (("A140R", ("ASI2600MC", "ASI2600MM"), 103.01, 68.85, 8, True),
             ("RC8", ("ASI2600MM",), 50.48, 33.74, 3, True)),
    "unmatched": {"Veil": 0.5},
    "orphans": ("SYN-ZNIKNAL",),
    # (kanon, best_rig, panele w A140R/RC8, rada, powód, luki, widoczny, h nad, kulminacja, plan)
    "rows": (
        ("SYN-RFN-15", "RC8", (1, 1), "RGB", None, ("RGB",), True, 2.58, 51.5, None),
        ("SYN-SNR-60", "A140R", (1, 4), "Ha", None, ("RGB", "Ha", "OIII", "SII"), True, 6.92,
         70.1, None),
        ("SYN-EMN-90", "A140R", (1, 4), "Ha", None, ("RGB", "Ha", "OIII", "SII"), True, 6.92,
         86.7, None),
        ("SYN-HII-25", "RC8", (1, 1), "OIII", None, ("OIII", "SII"), True, 6.92, 81.7, None),
        ("SYN-HII-8", "RC8", (1, 1), "Ha", None, ("RGB", "Ha", "OIII", "SII"), True, 6.92, 76.7,
         None),
        ("SYN-PN-7", "RC8", (1, 1), "Ha", None, ("RGB", "Ha", "OIII", "SII"), True, 5.58, 69.6,
         "planned"),
        ("SYN-SNR-200", "A140R", (9, 25), "SII", None, ("RGB", "SII"), True, 6.92, 66.7, None),
        ("SYN-G-B", "RC8", (1, 1), "RGB", None, ("RGB",), True, 2.58, 43.0, None),
        ("SYN-G-12", "RC8", (1, 1), None, "no_gap", (), True, 6.92, 77.8, None),
    ),
}

# `horreum plan <db> --night 2026-08-24 --park A140R,RC8 --all` z HEAD, ścieżka bazy -> `<db>`.
ZLOTY_TEKST = (
    "Horreum plan <db>: noc 2026-08-24, Będargowo (53.39N 14.44E)",
    "  ciemnosc zeglarska 19:40-02:30 UTC (astronomiczna 20:35-01:35), Ksiezyc 90% alt 6",
    "  cele: 14 -> 11 po progach -> 10 nad horyzontem -> 9 widocznych",
    "  zestaw A140R: kadr 103'x69', kamery ASI2600MC/ASI2600MM",
    "  zestaw RC8: kadr 50'x34', kamery ASI2600MM",
    "  park (z flagi): A140R, RC8",
    "  ukrytych jako 'skip': 1 (`--status skip` pokazuje ktore)",
    "",
    "  cel           typ     rozm  kulm   h>  zestaw           koszt B/D/N   rada  plan      "
    "pokrycie",
    "  SYN-RFN-15    RfN      15'  51.5  2.6  RC8 1 kadr       1.0/1.0/1.0   RGB   -         "
    "nigdy",
    "  SYN-SNR-60    SNR      60'  70.1  6.9  A140R 1 kadr     2.2/1.3/1.1   Ha    -         "
    "nigdy",
    "  SYN-EMN-90    EmN      90'  86.7  6.9  A140R 1 kadr     2.3/1.3/1.1   Ha    -         "
    "nigdy",
    "  SYN-HII-25    HII      25'  81.7  6.9  RC8 1 kadr       2.4/1.4/1.1   OIII  -         "
    "RGB 2.0h, Ha 2.0h, brak OIII/SII",
    "  SYN-HII-8     HII       8'  76.7  6.9  RC8 1 kadr       2.6/1.4/1.1   Ha    -         "
    "nigdy",
    "  SYN-PN-7      PN        7'  69.6  5.6  RC8 1 kadr       2.7/1.4/1.1   Ha    planned 2 "
    "nigdy",
    "  SYN-SNR-200   SNR     200'  66.7  6.9  A140R mozaika 9  2.8/1.5/1.1   SII   -         "
    "Ha 2.0h, OIII 2.0h, brak RGB/SII",
    "  SYN-G-B       G         8'  43.0  2.6  RC8 1 kadr       2.9/1.5/1.1   RGB   -         "
    "nigdy",
    "  SYN-G-12      G        12'  77.8  6.9  RC8 1 kadr       1.0/1.0/1.0   -     -         "
    "RGB 2.0h",
    "  godziny bez celu w katalogu: Veil 0.5h",
)

# sha256 kanonicznego zrzutu (`sort_keys`, UTF-8) wyjścia `--json` tego samego wołania z HEAD.
# Pełny JSON ma ~10 kB; strukturę wiersza pinuje projekcja wyżej, tu - każdy bajt poza `fill_pct`.
ZLOTY_JSON_SHA256 = "cd39af165e7aaa606591da009a783403cce81732c36f8520266e7d470e66a935"


def _zloty_park(con, monkeypatch):
    """Park z dwoma teleskopami (A140R z dwiema kamerami o TYM SAMYM polu widzenia, RC8), pokrycie
    w trzech paletach, reszta jawna i kuratela z sierotą - każdy człon projekcji ma czym się
    wykazać. Katalog syntetyczny podmienia `load_targets`, więc asset repo nie rusza złotej liczby."""
    monkeypatch.setattr(targets, "load_targets",
                        lambda layers=targets.DEFAULT_LAYERS: ZLOTY_KATALOG)
    hii = _obiekt(con, "SYN-HII-25")
    snr = _obiekt(con, "SYN-SNR-200")
    gal = _obiekt(con, "SYN-G-12")
    veil = _obiekt(con, "Veil")
    for i in range(2):
        _light(con, config_id=1, sha1=f"zh{i}", focal=784.0, object_id=hii, filter_canon="Ha",
               exptime=3600.0)
    for i in range(2):
        _light(con, config_id=2, sha1=f"zs{i}", focal=784.0, camera_id=2, object_id=snr,
               filter_canon="L-eXtreme", exptime=3600.0)
    for i in range(2):
        _light(con, config_id=2, sha1=f"zg{i}", focal=784.0, camera_id=2, object_id=gal,
               exptime=3600.0)
        _light(con, config_id=2, sha1=f"zb{i}", focal=784.0, camera_id=2, object_id=hii,
               exptime=3600.0)
    for i in range(3):
        _light(con, config_id=3, sha1=f"zr{i}", focal=1600.0, object_id=veil, filter_canon="Ha")
    con.commit()                         # `set_target_plan` otwiera własną transakcję
    repo.set_target_plan(con, canon="SYN-PN-7", status="planned", priority=2, note="zloty",
                         now=NOW)
    repo.set_target_plan(con, canon="SYN-DRK-20", status="skip", now=NOW)
    repo.set_target_plan(con, canon="SYN-ZNIKNAL", status="done", now=NOW)
    con.commit()


def _projekcja(res):
    fr = [[row.framing_in(r) for r in res.rigs] for row in res.rows]
    return {
        "counts": dict(res.counts), "hidden": res.hidden,
        "rigs": tuple((r.telescope, r.cameras, round(r.fov_x_arcmin, 2),
                       round(r.fov_y_arcmin, 2), r.lights, r.mono) for r in res.rigs),
        "unmatched": {k: round(v, 3) for k, v in sorted(res.unmatched.items())},
        "orphans": tuple(sorted(res.orphan_marks)),
        "rows": tuple((row.target.canon, row.best_rig.telescope if row.best_rig else None,
                       tuple(f.panels if f else None for f in fs), row.recommend,
                       row.recommend_reason, row.coverage.gaps, row.window.visible,
                       round(row.window.hours_above, 2), round(row.window.max_alt_deg, 1),
                       row.plan_status)
                      for row, fs in zip(res.rows, fr)),
    }


def test_zloty_plan_bez_progow_kadru_jak_przed_filtrem(con, monkeypatch):
    """Kryterium nadrzędne paczki filtra kadru: bez `min_fill`/`max_panels` kanony i kolejność,
    liczniki, `best_rig`, panele w każdym zestawie, rada i luki są te same co w HEAD."""
    _zloty_park(con, monkeypatch)
    res = targets.plan(con, night=date(2026, 8, 24), park=["A140R", "RC8"])
    assert res.rig_filter == "off"
    assert _projekcja(res) == ZLOTA_PROJEKCJA


def test_zloty_cli_tekst_i_json_bez_progow_kadru_jak_przed_filtrem(con, tmp_path, monkeypatch,
                                                                    capsys):
    """Ta sama kotwica dla CLI: tekst po wycięciu WYŁĄCZNIE kolumny `wyp` (4 znaki + 2 spacje
    zaraz za kolumną zestawu) i JSON po zdjęciu WYŁĄCZNIE `fill_pct` - bajt w bajt jak w HEAD."""
    import hashlib

    from horreum import cli
    _zloty_park(con, monkeypatch)
    path = str(tmp_path / "h.db")
    argv = ["plan", path, "--night", "2026-08-24", "--park", "A140R,RC8", "--all"]
    assert cli.main(argv) == 0
    lines = capsys.readouterr().out.replace(path, "<db>").splitlines()
    head = next(i for i, line in enumerate(lines) if line.lstrip().startswith("cel "))
    cut = lines[head].index("zestaw") + 17
    assert lines[head][cut:cut + 6] == " wyp  "
    table = [line[:cut] + line[cut + 6:] if i >= head and line.startswith("  ")
             and not line.startswith("  godziny") else line for i, line in enumerate(lines)]
    assert tuple(table) == ZLOTY_TEKST
    assert cli.main(argv + ["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert all("fill_pct" in r for r in out["rows"])
    for r in out["rows"]:
        r.pop("fill_pct")
    dump = json.dumps(out, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(dump).hexdigest() == ZLOTY_JSON_SHA256


def test_cli_plan_odmawia_na_niezgodnym_schemacie(tmp_path, capsys):
    """Read-only komenda nie ma prawa podnieść schematu żywego archiwum (T3 §0)."""
    import sqlite3

    from horreum import cli
    path = str(tmp_path / "stara.db")
    c = sqlite3.connect(path)
    c.execute("PRAGMA user_version = 8")
    c.commit()
    c.close()
    assert cli.main(["plan", path, "--night", "2026-08-15"]) == 2
    assert "nie migruje" in capsys.readouterr().out
    c = sqlite3.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 8
    c.close()
