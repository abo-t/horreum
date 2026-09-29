"""Rdzeń detektora śladów `horreum.streaks` (plan meteorów §2, testy §3 Q1): sekwencje, okno
przesuwne, wyrównanie, detekcja z progiem długości w pikselach natywnych, scalanie, pomiar końców,
tory, radiant na syntetycznym WCS, klasyfikacja.

Klatki syntetyczne: tło + szum gaussowski + gwiazdy w stałych miejscach (poza kołem r=150 px od
środka, żeby maska gwiazd nie cięła śladów testowych) + ślad renderowany w pikselach natywnych
PSF-em gaussowskim i dopiero potem binowany - tak jak prawdziwy ślad trafia do detektora."""
import math
import weakref
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.wcs import WCS

from horreum import streaks

SHAPE = (640, 640)
NOISE = 10.0                       # σ szumu na piksel natywny [ADU]


def _render(p0, p1, amp, sigma=1.8, shape=SHAPE):
    """Ślad o jasności `amp` ADU na piksel natywny w osi, od `p0` do `p1` (x, y)."""
    H, W = shape
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = int(L / 0.25) + 2
    t = np.linspace(0, 1, n)
    xs, ys = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
    w = amp * math.sqrt(2 * math.pi) * sigma * (L / (n - 1))
    out = np.zeros(shape)
    rad = int(math.ceil(3 * sigma))
    fx, fy = np.floor(xs).astype(int), np.floor(ys).astype(int)
    for oy in range(-rad, rad + 2):
        for ox in range(-rad, rad + 2):
            X, Y = fx + ox, fy + oy
            g = np.exp(-((X - xs) ** 2 + (Y - ys) ** 2) / (2 * sigma ** 2)) / (2 * math.pi * sigma ** 2)
            ok = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
            np.add.at(out, (Y[ok], X[ok]), w * g[ok])
    return out


def _star_field():
    rng = np.random.default_rng(99)
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    field = np.zeros(SHAPE)
    placed = 0
    while placed < 60:
        x, y, f = rng.uniform(0, SHAPE[1]), rng.uniform(0, SHAPE[0]), rng.uniform(200, 3000)
        if math.hypot(x - 320, y - 320) < 150:
            continue
        field += f * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8 ** 2))
        placed += 1
    return field


STARS = _star_field()


def _native_frame(k, seed, streak=None, target=2, shift=(0, 0)):
    rng = np.random.default_rng(seed * 1000 + k)
    f = 1000.0 + np.roll(STARS, shift, axis=(0, 1)) + rng.normal(0, NOISE, SHAPE)
    if streak is not None and k == target:
        f = f + _render(*streak)
    return f.astype(np.float32)


def _frames(bin_, streak=None, *, n=5, seed=0, target=2, shifts=None):
    return [streaks._bin_mean(_native_frame(k, seed, streak, target, shifts[k] if shifts else (0, 0)), bin_)
            for k in range(n)]


def _detect(frames, bin_, i=2, **kw):
    return streaks.detect_frame(i, frames[i], streaks.neighbours(i, dict(enumerate(frames))), bin=bin_, **kw)


def _centred(length, angle, amp):
    dx = math.cos(math.radians(angle)) * length / 2
    dy = math.sin(math.radians(angle)) * length / 2
    return (320 - dx, 320 - dy), (320 + dx, 320 + dy), amp


def _coverage(s, p0, p1):
    """Część wstrzykniętego odcinka pokryta wykrytym (kąt ≤ 1,5°, środek ≤ 8 px od prostej)."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    ang = math.degrees(math.atan2(s.y1 - s.y0, s.x1 - s.x0) - math.atan2(uy, ux))
    if abs((ang + 90) % 180 - 90) > 1.5:
        return 0.0
    mx, my = (s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2
    if abs((mx - p0[0]) * uy - (my - p0[1]) * ux) > 8:
        return 0.0
    t = sorted(((s.x0 - p0[0]) * ux + (s.y0 - p0[1]) * uy, (s.x1 - p0[0]) * ux + (s.y1 - p0[1]) * uy))
    return max(0.0, min(t[1], L) - max(t[0], 0.0)) / L


# ---------------------------------------------------------------- sąsiedzi, wyrównanie, okno

def test_neighbour_indices_dopelnia_przy_brzegu():
    assert streaks.neighbour_indices(0, 10) == [1, 2, 3, 4]
    assert streaks.neighbour_indices(5, 10) == [3, 4, 6, 7]
    assert streaks.neighbour_indices(9, 10) == [5, 6, 7, 8]
    assert streaks.neighbour_indices(1, 3) == [0, 2]


def test_phase_shift_calkowity_nakłada_klatke():
    ref = _frames(4, n=1)[0]
    img = np.roll(ref, (3, -5), axis=(0, 1))
    assert streaks.phase_shift(ref, img) == (-3, 5)
    (_, aligned, shift), = streaks.neighbours(0, {0: ref, 1: img}, n=1)
    assert shift == (-3, 5) and np.array_equal(aligned, ref)


def test_dithering_sasiadow_nie_psuje_detekcji():
    """Sąsiedzi przesunięci o 8-16 px natywnych (dithering): wyrównanie zdejmuje gwiazdy z reszty,
    ślad zostaje, a ramka marginesu rośnie o przesunięcie."""
    shifts = [(0, 0), (8, -12), (0, 0), (-16, 4), (12, 8)]
    streak = ((250.0, 260.0), (420.0, 370.0), 60.0)
    res = _detect(_frames(4, streak, shifts=shifts), 4)
    assert res.status == "done" and res.margin == 4 + streaks.ALIGN_MARGIN
    assert len(res.streaks) == 1 and _coverage(res.streaks[0], *streak[:2]) > 0.7


def test_okno_przesuwne_trzyma_najwyzej_2n_plus_1_klatek():
    """Każda klatka czytana raz, a w chwili odczytu żyje najwyżej 2n klatek poprzednich
    (falsyfikator: okno bez usuwania trzyma całą sekwencję)."""
    count, refs, loads, peak = 10, [], [], [0]

    def load(j):
        peak[0] = max(peak[0], sum(r() is not None for r in refs))
        a = streaks._bin_mean(_native_frame(j, 7), 4)
        refs.append(weakref.ref(a))
        loads.append(j)
        return streaks.Binned("ok", a, 4, SHAPE)

    results = list(streaks.scan_sequence(count, load))
    assert sorted(loads) == list(range(count))
    assert peak[0] <= 2 * streaks.N_NEIGHBOURS
    assert [r.status for r in results] == ["done"] * count
    assert all(r.n_neighbours == 4 for r in results)


def test_klatka_nieczytelna_nie_jest_sasiadem():
    def load(j):
        if j == 3:
            return streaks.Binned("skipped:raw")
        return streaks.Binned("ok", streaks._bin_mean(_native_frame(j, 8), 4), 4, SHAPE)

    results = list(streaks.scan_sequence(6, load))
    assert results[3].status == "skipped:raw"
    assert [r.status for i, r in enumerate(results) if i != 3] == ["done"] * 5
    assert results[2].n_neighbours == 3


def test_sekwencja_dwuklatkowa_bez_sasiadow():
    def load(j):
        return streaks.Binned("ok", streaks._bin_mean(_native_frame(j, 9), 4), 4, SHAPE)

    assert [r.status for r in streaks.scan_sequence(2, load)] == ["no_neighbours"] * 2
    assert [r.status for r in streaks.scan_sequence(3, load)] == ["done"] * 3


# ---------------------------------------------------------------- detekcja i pomiar

@pytest.mark.parametrize("bin_", [2, 4])
def test_min_len_80_natywnie_wykrywa_slad_80_px(bin_):
    """`min_len` jest w pikselach NATYWNYCH niezależnie od binningu (Z7). Falsyfikatory: próg brany
    jako binowany (80 px bin = 320 natywnych) gubi ślad 80 px; próg dzielony przez bin dwa razy
    przepuszcza ślad 60 px."""
    for angle in (0, 30, 62, 133):
        hit = _detect(_frames(bin_, _centred(80, angle, 100.0)), bin_, min_len_native=80)
        assert len(hit.streaks) == 1, (bin_, angle)
        miss = _detect(_frames(bin_, _centred(60, angle, 100.0)), bin_, min_len_native=80)
        assert miss.streaks == (), (bin_, angle)


def test_wstrzykniecie_geometria_sparowana_miedzy_jasnosciami():
    """Ta sama geometria i ten sam szum dla całej siatki jasności (zalecenie Z1 bramki Q0): krzywa
    wykrycia jest monotoniczna - wykryty przy jasności a jest wykryty przy każdej większej."""
    p0, p1 = (250.0, 260.0), (420.0, 370.0)
    amps = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
    cover = []
    for amp in amps:
        res = _detect(_frames(4, (p0, p1, amp), seed=5), 4)
        assert res.status == "done"
        cover.append(max((_coverage(s, p0, p1) for s in res.streaks), default=0.0))
    found = [c > 0 for c in cover]
    assert found == sorted(found), cover
    assert not found[0] and found[-1] and cover[-1] >= 0.7, cover


def test_koniec_przy_krawedzi_ma_ostrosc_none():
    """Krawędź kadru tnie ślad jak ekspozycja (Z9): koniec przy krawędzi = None, koniec wewnątrz
    ma liczbę (falsyfikator: bez testu położenia oba końce dostają ostrość)."""
    streak = ((380.0, 300.0), (700.0, 380.0), 80.0)          # wychodzi prawą krawędzią (W = 640)
    res = _detect(_frames(4, streak), 4)
    s = max(res.streaks, key=lambda q: q.length)
    assert s.edge_ends == 1
    inner, outer = ((s.end0, s.end1) if s.x0 < s.x1 else (s.end1, s.end0))
    assert inner is not None and outer is None


def test_satelita_ma_ostre_konce_i_niskie_cv():
    """Stała jasność i końce w kadrze (satelita urwany ekspozycją): końce ≈ środek, CV niskie."""
    res = _detect(_frames(4, ((250.0, 260.0), (420.0, 370.0), 60.0)), 4)
    s, = res.streaks
    assert s.edge_ends == 0 and min(s.end0, s.end1) >= streaks.END_SHARP and s.cv < streaks.CV_SATELLITE
    assert s.width == pytest.approx(4.2, abs=2.5)          # FWHM PSF 4,2 px natywnych, rozdzielczość bin 4


def test_scalanie_wspolliniowych_odcinkow():
    th = math.radians(30.0)
    a = (th, 100.0, 0.0, 100.0)
    near = (th + math.radians(0.4), 100.5, 105.0, 150.0)       # ta sama prosta, przerwa 5 ≤ 10 % z 145
    merged = streaks.merge_segments([a, near])
    assert len(merged) == 1 and merged[0][2] == 0.0 and merged[0][3] == pytest.approx(150.0, abs=1.0)
    skos = (th + math.radians(5.0), 100.0, 105.0, 150.0)
    daleko = (th, 100.0, 200.0, 250.0)                         # przerwa 100 > 15
    obok = (th, 110.0, 0.0, 100.0)                             # równoległa 10 px obok
    assert len(streaks.merge_segments([a, skos])) == 2
    assert len(streaks.merge_segments([a, daleko])) == 2
    assert len(streaks.merge_segments([a, obok])) == 2


# ---------------------------------------------------------------- tory

def _st(x0, y0, x1, y1, theta=None, **over):
    if theta is None:
        theta = (math.degrees(math.atan2(y1 - y0, x1 - x0)) + 90.0) % 180.0
    base = dict(x0=x0, y0=y0, x1=x1, y1=y1, theta=theta, length=math.hypot(x1 - x0, y1 - y0), width=4.0,
                snr=20.0, cv=0.2, end0=0.97, end1=0.96, edge_ends=0, masked_frac=0.0, blink_fap=0.5,
                blink_period=None)
    base.update(over)
    return streaks.Streak(**base)


def _sat(k, speed=100.0, t=None, offset=0.0, x_start=100.0, phi=26.0):
    """Ślad satelity w klatce k: kadencja 7 s, ekspozycja 3 s, prędkość wzdłuż prostej [px/s]."""
    t = 7.0 * k if t is None else t
    ux, uy = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    s0, s1 = speed * t, speed * (t + 3.0)
    nx, ny = -uy, ux
    return (k, t, _st(x_start + s0 * ux + offset * nx, 200 + s0 * uy + offset * ny,
                      x_start + s1 * ux + offset * nx, 200 + s1 * uy + offset * ny))


def test_tor_1_do_1_per_strona():
    """Ślad jest naraz następnikiem i poprzednikiem - wspólny zbiór „użytych" rwał tor na pary."""
    got = streaks.link_tracks([_sat(0), _sat(1), _sat(2)], cadence=7.0)
    assert got.tracks == ((0, 1, 2),) and got.ambiguous == ()


def test_konflikt_przypisania_zostawia_ambiguous():
    items = [_sat(0), _sat(0, offset=2.0), _sat(1)]
    got = streaks.link_tracks(items, cadence=7.0)
    assert len(got.links) == 1 and len(got.tracks) == 1
    loser = ({0, 1} - set(got.tracks[0])).pop()
    assert got.ambiguous == (loser,)


def test_rozrzut_predkosci_w_torze_ponad_20_procent_rwie_ogniwo():
    items = [_sat(0), _sat(1), (2, 14.0, _sat(2, speed=100.0, t=14.0 * 1.5)[2])]
    assert streaks.link_tracks(items, cadence=7.0).tracks == ((0, 1),)
    zgodny = [_sat(0), _sat(1), (2, 14.0, _sat(2, speed=100.0, t=14.0 * 1.1)[2])]
    assert streaks.link_tracks(zgodny, cadence=7.0).tracks == ((0, 1, 2),)


def test_przerwa_ponad_3_kadencje_nie_laczy():
    assert streaks.link_tracks([_sat(0), _sat(4, t=28.0)], cadence=7.0).links == ()


# Noc Perseidów 2026-08-12 (`outall/detections.csv` prototypu): theta, końce w px binowanych ×4, czas
# startu z DATE-OBS. Tory z oględzin: 36-40 i 86-87 oraz 898-899 (satelity).
PERSEIDS = [
    (36, "22:12:22.0738", 53.5, 444.8786, 27.835907, 427.03125, 41.04225),
    (37, "22:12:29.7739", 53.0, 353.81006, 92.747955, 320.10846, 118.143936),
    (38, "22:12:38.5984", 54.5, 251.2742, 168.38438, 218.05609, 192.07863),
    (39, "22:12:46.8465", 54.5, 153.89098, 237.84715, 121.145645, 261.2042),
    (40, "22:12:54.6252", 53.5, 54.93634, 308.91397, 31.299301, 326.40448),
    (86, "22:22:00.2935", 81.0, 1196.9409, 801.6265, 553.0953, 903.6017),
    (86, "22:22:00.2935", 81.5, 1471.1377, 761.92114, 1261.8796, 793.19495),
    (87, "22:22:04.0778", 81.0, 138.0458, 965.28925, -0.13079834, 987.17426),
    (898, "00:28:01.3778", 167.0, 36.737225, 368.06064, -1.5198936, 202.3509),
    (899, "00:28:05.1578", 167.5, 90.0775, 604.9828, 51.2714, 429.93985),
]


def _perseids():
    t0 = datetime(2026, 8, 12, 22, 0, 0)
    items = []
    for frame, hms, theta, *xy in PERSEIDS:
        h, m, s = hms.split(":")
        t = datetime(2026, 8, 12 if int(h) > 12 else 13, int(h), int(m)) + timedelta(seconds=float(s))
        x0, y0, x1, y1 = (v * 4 + 1.5 for v in xy)
        items.append((frame, (t - t0).total_seconds(), _st(x0, y0, x1, y1, theta=theta)))
    return items


def _frames_of(items, tracks):
    return sorted(tuple(items[k][0] for k in t) for t in tracks)


def test_prog_rosnacy_z_ekstrapolacja_na_torach_nocy_perseidow(monkeypatch):
    """Próg odległości rośnie z ekstrapolacją: 86→87 ma 16 px przy ~3000 px ekstrapolacji (0,3°
    błędu kąta z kosza Hougha), a stałe 5 px rwie tor 36-40 i gubi 86-87 (plan §1a, dopisek)."""
    items = _perseids()
    got = streaks.link_tracks(items, cadence=7.0, bin=4)
    assert _frames_of(items, got.tracks) == [(36, 37, 38, 39, 40), (86, 87), (898, 899)]
    monkeypatch.setattr(streaks, "link_tolerance", lambda extrap, bin=4: 5.0)
    stale = streaks.link_tracks(items, cadence=7.0, bin=4)
    assert (36, 37, 38, 39, 40) not in _frames_of(items, stale.tracks)
    assert (86, 87) not in _frames_of(items, stale.tracks)


def test_link_tolerance_rosnie_z_odlegloscia():
    assert streaks.link_tolerance(0.0, 4) == 5.0
    assert streaks.link_tolerance(3000.0, 4) == pytest.approx(4 + 3000 * math.tan(math.radians(0.5)))


# ---------------------------------------------------------------- radiant

PER_NIGHT = datetime(2026, 8, 12, 22, 12, tzinfo=timezone.utc)


def _wcs(ra, dec):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [3124.5, 2088.5]
    w.wcs.cdelt = [-0.000275, 0.000275]                     # ~0,99″/px - A140R + ASI2600MM
    return w


def _great_circle_streak(w, centre, towards, rot_deg=0.0, half=0.3):
    """Ślad przez środek pola wzdłuż koła wielkiego ku punktowi `towards`, obrócony o `rot_deg`."""
    c, r = streaks._unit(*centre), streaks._unit(*towards)
    u = r - (r @ c) * c
    u /= np.linalg.norm(u)
    v = np.cross(c, u)
    rot = math.radians(rot_deg)
    d = math.cos(rot) * u + math.sin(rot) * v
    pts = []
    for t in (-half, half):
        p = math.cos(math.radians(t)) * c + math.sin(math.radians(t)) * d
        ra = math.degrees(math.atan2(p[1], p[0])) % 360
        dec = math.degrees(math.asin(p[2]))
        pts.append(w.all_world2pix([[ra, dec]], 0)[0])
    (x0, y0), (x1, y1) = pts
    return _st(float(x0), float(y0), float(x1), float(y1))


def test_radiant_per_na_kole_wielkim_trafia_poza_nie():
    showers = streaks.load_showers()
    per = next(s for s in showers if s["code"] == "PER")
    lam = streaks.solar_longitude(PER_NIGHT)
    rad = streaks.radiant_at(per, lam)
    centre = (1.0, 67.9)                                     # pole Sh2-171, ~22° od radiantu PER
    w = _wcs(*centre)
    through = streaks.radiant_match(_great_circle_streak(w, centre, rad), w, PER_NIGHT, showers)
    assert through and "PER" in [c for c, _ in through]
    assert dict(through)["PER"] < 0.1
    beside = streaks.radiant_match(_great_circle_streak(w, centre, rad, rot_deg=30.0), w, PER_NIGHT, showers)
    assert "PER" not in [c for c, _ in beside]
    # poza oknem aktywności nie ma trafienia nawet przez radiant przeliczony na tę datę
    marzec = datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc)
    rad_marzec = streaks.radiant_at(per, streaks.solar_longitude(marzec))
    assert "PER" not in [c for c, _ in streaks.radiant_match(_great_circle_streak(w, centre, rad_marzec), w,
                                                            marzec, showers)]


def test_brak_wcs_to_brak_testu():
    assert streaks.radiant_match(_st(0, 0, 100, 100), None, PER_NIGHT, streaks.load_showers()) is None


def test_dryf_szacowany_trzyma_radiant_w_ukladzie_slonca():
    """Rój bez zmierzonego dryfu (COR w liście 2026): λ - λ☉ i β stałe, nie radiant nieruchomy."""
    sh = dict(code="X", los=100.0, ra=191.6, dec=-19.2, dra=None, ddec=None)
    lam0, beta0 = streaks._eq_to_ecl(*streaks.radiant_at(sh, 100.0))
    lam1, beta1 = streaks._eq_to_ecl(*streaks.radiant_at(sh, 110.0))
    assert (lam1 - lam0) % 360 == pytest.approx(10.0, abs=1e-6) and beta1 == pytest.approx(beta0, abs=1e-6)
    zmierzony = dict(sh, dra=1.0, ddec=0.5)
    ra, dec = streaks.radiant_at(zmierzony, 100.0 + streaks.DEG_PER_DAY_SUN * 4)
    assert (ra, dec) == pytest.approx((195.6, -17.2))


def test_dlugosc_slonca_w_nocy_perseidow():
    assert streaks.solar_longitude(PER_NIGHT) == pytest.approx(139.83, abs=0.02)


def test_asset_rojow_ma_kotwice():
    codes = {s["code"]: s for s in streaks.load_showers()}
    assert {"PER", "GEM", "QUA", "ORI", "LYR", "ETA"} <= set(codes)
    assert codes["PER"]["ra"] == pytest.approx(48, abs=5) and codes["PER"]["dec"] == pytest.approx(58, abs=5)


# ---------------------------------------------------------------- klasyfikacja

def test_klasyfikacja_w_kolejnosci_planu():
    assert streaks.classify(_st(0, 0, 100, 0), parallel=True) == "samolot"
    assert streaks.classify(_st(0, 0, 100, 0, blink_fap=1e-6)) == "samolot"
    assert streaks.classify(_st(0, 0, 100, 0, cv=0.5, end0=0.3), track_len=2) == "satelita"
    assert streaks.classify(_st(0, 0, 100, 0)) == "satelita"
    assert streaks.classify(_st(0, 0, 100, 0), showers=[("PER", 1.2)]) == "satelita"   # cechy satelity bija radiant
    assert streaks.classify(_st(0, 0, 100, 0, cv=0.5, end0=0.3), showers=[("PER", 1.2)]) == "meteor:PER"
    assert streaks.classify(_st(0, 0, 100, 0, cv=0.5)) == "meteor?"
    assert streaks.classify(_st(0, 0, 100, 0, end1=0.35)) == "meteor?"
    assert streaks.classify(_st(0, 0, 100, 0, end0=None, end1=None, edge_ends=2, cv=0.3)) == "nieokreslony"


def test_para_rownoleglych_to_samolot():
    pair = [_st(0, 0, 400, 0), _st(10, 15, 380, 15), _st(0, 300, 400, 300)]
    assert streaks.parallel_partners(pair) == {0, 1}


# ---------------------------------------------------------------- sekwencje

def _ff(t, *, exptime=3.0, flt="L", rot=178.47, ref=None):
    return streaks.FrameFacts(ref=ref, time=datetime(2026, 8, 12, 22, 0) + timedelta(seconds=t),
                              exptime=exptime, camera="ASI2600MM", telescope="A140R", filter=flt,
                              width=6248, height=4176, binning=1, rotation=rot)


def test_sekwencje_dithering_nie_tnie_przerwa_tnie():
    frames = [_ff(7 * k) for k in range(20)] + [_ff(7 * 19 + 100 + 7 * k) for k in range(20)]
    assert [len(s) for s in streaks.sequences(frames)] == [40]
    frames += [_ff(7 * 19 + 100 + 7 * 19 + 11 * 60 + 7 * k) for k in range(5)]
    assert [len(s) for s in streaks.sequences(frames)] == [40, 5]


def test_sekwencje_tnie_obrot_i_rozdziela_filtry():
    """Meridian flip (OBJCTROT o 180°) dzieli sekwencję - wyrównanie jest tylko translacyjne."""
    frames = [_ff(60 * k, exptime=60.0) for k in range(6)] + [_ff(60 * k, exptime=60.0, rot=358.5)
                                                             for k in range(6, 10)]
    assert [len(s) for s in streaks.sequences(frames)] == [6, 4]
    mixed = [_ff(60 * k, exptime=60.0, flt="R" if k % 2 else "G") for k in range(10)]
    assert sorted(len(s) for s in streaks.sequences(mixed)) == [5, 5]


def test_sekwencje_rezim_ekspozycji_10_procent():
    frames = [_ff(130 * k, exptime=60.0 if k % 2 else 63.0) for k in range(6)]
    assert [len(s) for s in streaks.sequences(frames)] == [6]
    frames = [_ff(130 * k, exptime=60.0 if k % 2 else 120.0) for k in range(6)]
    assert sorted(len(s) for s in streaks.sequences(frames)) == [3, 3]
