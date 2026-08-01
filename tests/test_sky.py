"""NIEBO (T1): FOV z zeznania, kawałkowanie bez sufitu, okno nocy, Księżyc modelem K&S.

Arbitrem geometrii jest `astropy` — JEDYNE miejsce w repo, gdzie wolno go zawołać dla
`coordinates`: produkcja liczy własną arytmetyką (spec onefile ma `hiddenimports` tylko
`astropy.io.fits`), a test dowodzi, że ta arytmetyka jest prawdziwa, zamiast to obiecywać.
"""
import math
from datetime import date, datetime, timezone

import pytest

from horreum import db, sky

NOW = "2026-07-31T12:00:00+00:00"
BEDARGOWO = sky.Site(observatory_id=1, name="Będargowo", lat_deg=53.3890, lon_deg=14.4424,
                     frames=13250)
# Kotwice z żywego archiwum (kolejka „PLANER CELÓW"): zestaw = (ogniskowa mm, piksel µm, NAXIS)
RC8 = (1600.0, 3.76, (6248, 4176))
A140R = (784.0, 3.76, (6248, 4176))
EDPH76 = (342.0, 3.76, (6248, 4176))


def _rig(spec, **kw):
    focal, pixel, naxis = spec
    base = dict(config_id=1, telescope="T", camera="C", focal_mm=focal, pixel_um=pixel,
                naxis=naxis, lights=100, last_seen=None, mode_share=1.0, reason=None)
    base.update(kw)
    return sky.Rig(**base)


# ─────────────────────────────────────────────────────────────── FOV z zeznania

def test_fov_rc8_kotwica_archiwum():
    """1600 mm × 3,76 µm × 6248×4176 => 33,7' krótszym bokiem, 0,48"/px (liczby z żywej pf4)."""
    r = _rig(RC8)
    assert r.scale_arcsec_px == pytest.approx(0.485, abs=0.005)
    assert r.fov_arcmin == pytest.approx(33.7, abs=0.1)
    assert r.fov_x_arcmin == pytest.approx(50.4, abs=0.1)      # dłuższy bok
    assert _rig(A140R).fov_arcmin == pytest.approx(68.9, abs=0.1)
    assert _rig(EDPH76).fov_arcmin == pytest.approx(157.8, abs=0.1)


def test_fov_nalezy_do_configu_nie_do_teleskopu():
    """Ten sam ED120R: z ASI294MC (4,63 µm, 4144×2822) 56,9', z ASI2600MM 68,4'."""
    stary = _rig((789.0, 4.63, (4144, 2822)))
    nowy = _rig((789.0, 3.76, (6248, 4176)))
    assert stary.fov_arcmin == pytest.approx(56.9, abs=0.2)
    assert nowy.fov_arcmin == pytest.approx(68.4, abs=0.2)


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MM', 3.76, 1, ?)", (NOW,))
    for tel in ("A140R", "ED120R"):
        c.execute("INSERT INTO telescope(telescop_canon, status, created_at) VALUES (?, ?, ?)",
                  (tel, "proposed", NOW))
    c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
              "VALUES (1, 1, 'proposed', ?)", (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, status, created_at) "
              "VALUES (2, 1, 'proposed', ?)", (NOW,))
    yield c
    c.close()


def _light(con, *, config_id, sha1, focal=784.0, pixel=3.76, naxis=(6248, 4176), kind="light",
           date_obs="2026-01-02T22:00:00"):
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, first_seen_at) "
                "VALUES (?, ?, 'fits', 1, ?, ?)", (sha1, kind, config_id, NOW))
    fid = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1,)).fetchone()["id"]
    raw = "{}" if naxis is None else '{"NAXIS1": %d, "NAXIS2": %d}' % naxis
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, focallen, xpixsz) "
                "VALUES (?, ?, ?, ?, ?)", (fid, raw, date_obs, focal, pixel))
    return fid


def test_rigs_liczy_mode_i_pomija_master_light(con):
    """`master_light` jest po integracji PRZYCIĘTY — nie ma prawa wejść do mody NAXIS."""
    for i in range(10):
        _light(con, config_id=1, sha1=f"a{i}")
    _light(con, config_id=1, sha1="stack", naxis=(3000, 2000), kind="master_light")
    r = [x for x in sky.rigs(con) if x.config_id == 1][0]
    assert r.naxis == (6248, 4176)
    assert r.lights == 10 and r.mode_share == 1.0 and r.reason is None


def test_rigs_brak_naxis_nie_rozciencza_mody(con):
    """Klatka bez NAXIS (XISF/RAW) to brak zeznania, nie inna optyka — nie może wywołać
    `mixed_optics` na configu o jednej optyce (regresja: RC8×2600MC, 202 XISF na 2733)."""
    for i in range(10):
        _light(con, config_id=1, sha1=f"b{i}")
    for i in range(5):
        _light(con, config_id=1, sha1=f"x{i}", naxis=None)
    r = [x for x in sky.rigs(con) if x.config_id == 1][0]
    assert r.reason is None and r.mode_share == 1.0
    assert r.fov_arcmin == pytest.approx(68.9, abs=0.1)


def test_rigs_bez_zadnego_naxis_oddaje_powod(con):
    for i in range(4):
        _light(con, config_id=1, sha1=f"c{i}", naxis=None)
    r = [x for x in sky.rigs(con) if x.config_id == 1][0]
    assert r.reason == "no_naxis" and r.fov_arcmin is None


def test_rigs_dwie_optyki_pod_jedna_nazwa_to_mixed_optics(con):
    """Drugi reduktor na tej samej nazwie TELESCOP: cicha większość dałaby FOV nieprawdziwe."""
    for i in range(6):
        _light(con, config_id=1, sha1=f"d{i}", focal=784.0)
    for i in range(4):
        _light(con, config_id=1, sha1=f"e{i}", focal=980.0)
    r = [x for x in sky.rigs(con) if x.config_id == 1][0]
    assert r.reason == "mixed_optics" and r.fov_arcmin is None


def test_rigs_only_to_jawna_lista_nie_max_date_obs(con):
    """ED120R ma klatki NOWSZE, a i tak nie należy do parku — park jest deklaracją użytkownika."""
    _light(con, config_id=1, sha1="p1", date_obs="2020-01-01T22:00:00")
    _light(con, config_id=2, sha1="p2", date_obs="2026-05-10T22:00:00")
    assert {r.telescope for r in sky.rigs(con)} == {"A140R", "ED120R"}
    assert [r.telescope for r in sky.rigs(con, ["A140R"])] == ["A140R"]


def test_rigs_scalony_teleskop_nie_dubluje_zestawu(con):
    """`merged_into` => wariant nazwy roluje się pod kanon, nie wyskakuje jako osobny wiersz."""
    _light(con, config_id=1, sha1="m1")
    _light(con, config_id=2, sha1="m2")
    con.execute("UPDATE telescope SET merged_into = 1 WHERE telescop_canon = 'ED120R'")
    assert [r.telescope for r in sky.rigs(con)] == ["A140R"]


# ─────────────────────────────────────────────────────────────── kadrowanie (D-0731-8)

def test_cel_rowny_kadrowi_to_jeden_panel():
    """Granica: zakładka NIE może być odliczana od pierwszego kadru."""
    r = _rig(EDPH76)
    assert sky.framing(r.fov_arcmin, r).panels == 1
    assert sky.framing(r.fov_arcmin + 1.0, r).panels == 2


def test_veil_na_76edph_to_dwa_panele():
    """Veil 210' w kadrze 236,1'×157,8' — mieści się wzdłuż, wymaga 2 paneli w poprzek."""
    f = sky.framing(210.0, _rig(EDPH76))
    assert (f.panels_x, f.panels_y, f.panels) == (1, 2, 2)


def test_brak_sufitu_wielki_cel_zostaje_z_liczba_paneli():
    """Sh2-109 (1080') nie znika z wyników — dostaje wycenę w panelach (D-0731-8)."""
    f = sky.framing(1080.0, _rig(RC8))
    assert f.panels > 100 and f.fill > 30


def test_cel_wydluzony_liczy_poprzek_z_osi_mniejszej():
    """NGC4565: 16,8'×1,9' w kadrze RC8 — bez `minor_arcmin` byłaby fałszywa mozaika w poprzek."""
    r = _rig((3400.0, 3.76, (6248, 4176)))          # ogniskowa dobrana tak, by 16,8' > FOV_y (15,9')
    bez = sky.framing(16.8, r)
    z_osia = sky.framing(16.8, r, minor_arcmin=1.9)
    assert z_osia.panels_y == 1 and z_osia.panels < bez.panels


def test_framing_bez_fov_oddaje_none():
    assert sky.framing(20.0, _rig(RC8, reason="no_naxis")) is None


# ─────────────────────────────────────────────────────────────── czas i widoczność

def test_naiwny_czas_jest_bledem():
    """Jedyne miejsce, gdzie pomyłka o godzinę wygląda sensownie — EXPECT, nie cicha interpretacja."""
    with pytest.raises(ValueError):
        sky.altitude(350.3, 62.7, 53.4, 14.4, datetime(2026, 1, 1, 0, 0))


def test_kulminacja_ctb1_z_bedargowa():
    """Kulminacja = 90 − |szerokość − deklinacja|; niezależna od pory roku (cel okołobiegunowy
    kulminuje tak samo cały rok — zmienia się GODZINA kulminacji, nie wysokość).

    Z J2000 wychodzi 80,69°, ale model liczy na DATĘ: precesja podnosi deklinację CTB1 o ~0,14°
    do epoki 2026, więc kotwicą jest 80,5° — i to jest wartość ZMIERZONA firsthandem na żywej
    bazie, nie wyliczona na kartce."""
    best = max(sky.altitude(350.3, 62.7, BEDARGOWO.lat_deg, BEDARGOWO.lon_deg,
                            datetime(2026, 1, 1, tzinfo=timezone.utc).replace(hour=h, minute=m))
               for h in range(24) for m in (0, 30))
    assert best == pytest.approx(80.5, abs=0.3)


def test_brak_nocy_astronomicznej_latem_ma_powod():
    """53,4° N: od ~połowy maja do ~końca lipca ☉ nie schodzi poniżej −18°. Okno ŻEGLARSKIE
    istnieje mimo to i to ono jest zakresem rozważań — brak twardej ciemności opisuje jakość
    nieba, nie dostępność celu."""
    w = sky.visibility_window(350.3, 62.7, BEDARGOWO, date(2026, 6, 15))
    assert w.darkness == "nautical" and w.reason == "no_astro_night"
    assert w.astro_start is None and w.dark_start is not None and w.hours_above > 0


def test_okno_to_noc_zeglarska_takze_zima():
    """Zimą noc astronomiczna ISTNIEJE, ale zakresem rozważań pozostaje żeglarska — okno musi
    być SZERSZE od astronomicznego, inaczej cel na skraju nocy zniknąłby bez powodu."""
    w = sky.visibility_window(350.3, 62.7, BEDARGOWO, date(2026, 1, 15))
    assert w.darkness == "astronomical" and w.astro_start is not None
    assert w.dark_start < w.astro_start and w.dark_end > w.astro_end


def test_widoczny_to_maksimum_nocy_zeglarskiej_wobec_suwaka():
    """`visible` = max_alt >= min_alt; próg jest SUWAKIEM, nie stałą (D-0731-10)."""
    w30 = sky.visibility_window(313.0, 31.0, BEDARGOWO, date(2026, 8, 20))
    w80 = sky.visibility_window(313.0, 31.0, BEDARGOWO, date(2026, 8, 20), min_alt=80.0)
    assert w30.visible and not w80.visible
    assert w30.max_alt_deg == pytest.approx(w80.max_alt_deg, abs=0.01)   # miara się nie zmienia


def test_okoloobiegunowy_nie_zachodzi():
    w = sky.visibility_window(0.0, 75.0, BEDARGOWO, date(2026, 1, 15))
    assert w.reason == "circumpolar" and w.hours_above > 5


def test_nigdy_nie_wschodzi():
    w = sky.visibility_window(0.0, -60.0, BEDARGOWO, date(2026, 1, 15))
    assert w.reason == "never_rises" and w.hours_above == 0.0


def test_best_month_zalezy_tylko_od_ra():
    """CTB1 (RA 350°) kulminuje o północy we wrześniu, M106 (RA 184°) w marcu."""
    assert sky.best_month(350.3) == 9
    assert sky.best_month(184.7) == 3
    assert sky.best_month(313.0) == 8                    # Veil


# ─────────────────────────────────────────────────────────────── Księżyc (K&S 1991)

def _moon(k, moon_alt, target_alt, sep):
    """Buduje MoonState wprost z geometrii — test modelu bez zależności od efemerydy."""
    natural = sky._nanolambert(sky.V_ZEN_DEFAULT)
    alpha = math.degrees(math.acos(max(-1.0, min(1.0, 2 * k - 1))))
    i_star = 10 ** (-0.4 * (3.84 + 0.026 * abs(alpha) + 4e-9 * alpha ** 4))
    rho = math.radians(sep)
    f_rho = 10 ** 5.36 * (1.06 + math.cos(rho) ** 2) + 10 ** (6.15 - sep / 40)
    b = 0.0
    if moon_alt > 0:
        b = (f_rho * i_star * 10 ** (-0.4 * sky.K_EXT_DEFAULT * sky._airmass(moon_alt))
             * (1 - 10 ** (-0.4 * sky.K_EXT_DEFAULT * sky._airmass(target_alt))))
    return sky.MoonState(illumination=k, alt_deg=moon_alt, separation_deg=sep,
                         delta_mag=0.0 if b <= 0 else 2.5 * math.log10(1 + b / natural),
                         _sky_nl=b, _natural_nl=natural)


def test_sanity_pelnia_wobec_literatury():
    """Pełnia, Księżyc 40°, cel 60°, separacja 90° => tło ~18,6 mag/arcsec² (literatura 18,5–19,5).
    Kotwica zrywa się przy pomyłce w którymkolwiek wykładniku modelu."""
    m = _moon(1.0, 40.0, 60.0, 90.0)
    assert sky.V_ZEN_DEFAULT - m.delta_mag == pytest.approx(18.6, abs=0.3)


def test_ksiezyc_pod_horyzontem_to_prog_nie_zanik():
    m = _moon(1.0, -5.0, 60.0, 90.0)
    assert all(m.cost(b) == 1.0 for b in sky.BANDS.values())


def test_koszt_rosnie_monotonicznie_z_faza():
    kosz = [_moon(k, 45.0, 60.0, 90.0).cost(1.0) for k in (0.1, 0.25, 0.5, 0.75, 0.9, 1.0)]
    assert kosz == sorted(kosz) and kosz[0] < 1.1 < kosz[-1]


def test_separacja_ma_minimum_okolo_90_stopni():
    """„Im dalej tym lepiej" jest FAŁSZYWE: przy 150° rozpraszanie wsteczne znów podnosi tło.
    Ten test broni krzywej przed „poprawieniem" jej na monotoniczną."""
    koszt = {s: _moon(1.0, 45.0, 60.0, s).cost(1.0) for s in (20, 40, 60, 90, 120, 150)}
    assert min(koszt, key=lambda s: koszt[s]) == 90
    assert koszt[150] > koszt[90] and koszt[20] > koszt[40] > koszt[60] > koszt[90]


def test_paleta_rozstrzyga_czy_noc_jest_stracona():
    """Ta sama pełnia: LRGB ~6,5×, wąskie pasmo ~1,3× — to jest oś decyzji „w jakich filtrach"."""
    m = _moon(1.0, 50.0, 60.0, 110.0)
    assert m.cost(sky.BANDS["broadband"]) == pytest.approx(6.5, rel=0.15)
    assert m.cost(sky.BANDS["duoband"]) == pytest.approx(2.4, rel=0.15)
    assert m.cost(sky.BANDS["narrowband"]) == pytest.approx(1.28, rel=0.15)


def test_moon_state_wymaga_aware_czasu():
    with pytest.raises(ValueError):
        sky.moon_state(350.3, 62.7, BEDARGOWO, datetime(2026, 1, 1, 0, 0))


# ─────────────────────────────────────────────────────────────── arbiter astropy

@pytest.fixture(scope="module")
def astropy_bits():
    ap = pytest.importorskip("astropy", reason="arbiter geometrii — poza baterią bez astropy")
    from astropy.coordinates import FK5, AltAz, EarthLocation, SkyCoord, get_body
    from astropy.time import Time
    from astropy.utils import iers
    iers.conf.auto_download = False          # aplikacja NIGDY nie woła sieci — test też nie
    iers.conf.auto_max_age = None            # bez sieci tabela IERS jest „stara" i astropy rzuca
    iers.conf.iers_degraded_accuracy = "ignore"
    return ap, AltAz, EarthLocation, SkyCoord, get_body, Time, FK5


_PROBY = [(350.3, 62.7), (184.7, 47.3), (313.0, 31.0), (85.0, -5.4), (0.0, 41.3)]
_CHWILE = [datetime(2026, 1, 15, 22, tzinfo=timezone.utc),
           datetime(2026, 4, 2, 1, tzinfo=timezone.utc),
           datetime(2026, 8, 20, 23, 30, tzinfo=timezone.utc),
           datetime(2026, 11, 7, 3, tzinfo=timezone.utc)]


def test_arbiter_wysokosc_celu(astropy_bits):
    """20 par (cel × chwila): własna arytmetyka vs astropy < 0,5°."""
    _, AltAz, EarthLocation, SkyCoord, _, Time, _FK5 = astropy_bits
    loc = EarthLocation(lat=BEDARGOWO.lat_deg, lon=BEDARGOWO.lon_deg, height=0)
    for ra, dec in _PROBY:
        for when in _CHWILE:
            ref = SkyCoord(ra=ra, dec=dec, unit="deg").transform_to(
                AltAz(obstime=Time(when), location=loc)).alt.deg
            mine = sky.altitude(ra, dec, BEDARGOWO.lat_deg, BEDARGOWO.lon_deg, when)
            assert abs(mine - ref) < 0.5, f"cel {ra}/{dec} @ {when}: {mine:.2f} vs {ref:.2f}"


def test_arbiter_slonce_i_ksiezyc(astropy_bits):
    """Arbitrem jest WYSOKOŚĆ nad horyzontem — wielkość, której moduł realnie używa (granice nocy
    i próg „Księżyc pod horyzontem"), a nie RA/Dec: `get_body` oddaje GCRS, więc porównanie
    współrzędnych wprost mierzyłoby precesję, a `transform_to(FK5)` przesunęłoby dla Księżyca
    ORIGIN z geocentrum do barycentrum (błąd rzędu dziesiątek stopni).

    Próg Księżyca 1,5° zamiast 0,5°, bo model jest GEOCENTRYCZNY, a astropy z `location` liczy
    topocentrycznie — paralaksa Księżyca dochodzi do 1°. Dla kary księżycowej to nieistotne
    (koszt zmienia się z wysokością powoli), ISTOTNE tylko przy alt ≈ 0 i tam działa na korzyść:
    model uzna Księżyc za zaszły odrobinę za wcześnie albo za późno o minuty."""
    _, AltAz, EarthLocation, SkyCoord, get_body, Time, _FK5 = astropy_bits
    loc = EarthLocation(lat=BEDARGOWO.lat_deg, lon=BEDARGOWO.lon_deg, height=0)
    for when in _CHWILE:
        t = Time(when)
        jd = sky._jd(when)
        frame = AltAz(obstime=t, location=loc)
        s_ref = get_body("sun", t, location=loc).transform_to(frame).alt.deg
        s_mine = sky._alt_from_jd(*sky._sun_radec(jd), BEDARGOWO.lat_deg, BEDARGOWO.lon_deg, jd,
                                  precess=False)
        assert abs(s_mine - s_ref) < 0.3, f"Słońce @ {when}: {s_mine:.2f} vs {s_ref:.2f}"
        m_ref = get_body("moon", t, location=loc).transform_to(frame).alt.deg
        m_ra, m_dec = sky.moon_position(when)
        m_mine = sky._alt_from_jd(m_ra, m_dec, BEDARGOWO.lat_deg, BEDARGOWO.lon_deg, jd,
                                  precess=False)
        assert abs(m_mine - m_ref) < 1.5, f"Księżyc @ {when}: {m_mine:.2f} vs {m_ref:.2f}"
        # faza: elongacja liczona w JEDNYM układzie (oba ciała w GCRS) => origin się znosi
        sc_s, sc_m = get_body("sun", t), get_body("moon", t)
        elong_ref = sky.separation(sc_s.ra.deg, sc_s.dec.deg, sc_m.ra.deg, sc_m.dec.deg)
        k_ref = (1 - math.cos(math.radians(elong_ref))) / 2
        k_mine = sky.moon_state(0.0, 45.0, BEDARGOWO, when).illumination
        assert abs(k_mine - k_ref) < 0.02, f"faza @ {when}: {k_mine:.3f} vs {k_ref:.3f}"


def test_arbiter_best_month(astropy_bits):
    """`best_month` == miesiąc najwyższej kulminacji o północy wg astropy, dla każdej próby."""
    _, AltAz, EarthLocation, SkyCoord, _, Time, _FK5 = astropy_bits
    loc = EarthLocation(lat=BEDARGOWO.lat_deg, lon=BEDARGOWO.lon_deg, height=0)
    for ra, dec in _PROBY:
        alts = {}
        for m in range(1, 13):
            when = datetime(2026, m, 15, 23, tzinfo=timezone.utc)   # ~północ lokalna zimowa
            alts[m] = SkyCoord(ra=ra, dec=dec, unit="deg").transform_to(
                AltAz(obstime=Time(when), location=loc)).alt.deg
        ref = max(alts, key=lambda m: alts[m])
        assert abs((sky.best_month(ra) - ref + 6) % 12 - 6) <= 1
