"""Tryb katalogu detektora śladów (`horreum.streaks`, plan meteorów §3 Q1): piksel NaN, porcje
sekwencji na wątkach, fakty z nagłówków, PNG stdlib, wycinki i raport w pamięci.

Klatki syntetyczne jak w `test_streaks.py` (tło + szum + gwiazdy poza środkiem + ślad PSF-em
gaussowskim w pikselach natywnych), zapisywane jako FITS 16-bit w `tmp_path` - bez archiwum i bazy."""
import csv
import io
import json
import math
import os
import struct
import zlib
from datetime import datetime, timedelta

import numpy as np
import pytest
from astropy.io import fits

from horreum import streaks

SHAPE = (640, 640)
NOISE = 10.0


def _render(p0, p1, amp, sigma=1.8):
    """Ślad `amp` ADU na piksel natywny w osi, od `p0` do `p1` (x, y)."""
    H, W = SHAPE
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = int(L / 0.25) + 2
    t = np.linspace(0, 1, n)
    xs, ys = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
    w = amp * math.sqrt(2 * math.pi) * sigma * (L / (n - 1))
    out = np.zeros(SHAPE)
    rad = int(math.ceil(3 * sigma))
    fx, fy = np.floor(xs).astype(int), np.floor(ys).astype(int)
    for oy in range(-rad, rad + 2):
        for ox in range(-rad, rad + 2):
            X, Y = fx + ox, fy + oy
            g = np.exp(-((X - xs) ** 2 + (Y - ys) ** 2) / (2 * sigma ** 2)) / (2 * math.pi * sigma ** 2)
            ok = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
            np.add.at(out, (Y[ok], X[ok]), w * g[ok])
    return out


def _stars():
    rng = np.random.default_rng(99)
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    field, placed = np.zeros(SHAPE), 0
    while placed < 60:
        x, y, f = rng.uniform(0, SHAPE[1]), rng.uniform(0, SHAPE[0]), rng.uniform(200, 3000)
        if math.hypot(x - 320, y - 320) < 150:
            continue
        field += f * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8 ** 2))
        placed += 1
    return field


STARS = _stars()
STREAK = ((250.0, 260.0), (420.0, 370.0), 60.0)       # satelita: końce w kadrze, stała jasność


def _native(k, seed=0, streak=None):
    f = 1000.0 + STARS + np.random.default_rng(seed * 1000 + k).normal(0, NOISE, SHAPE)
    return f + _render(*streak) if streak else f


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


# ---------------------------------------------------------------- piksel NaN (tripwire MT-1)

def _binned_with_nan(k, streak_at=2, nan_all=False):
    a = _native(k, 3, STREAK if k == streak_at else None).astype(np.float32)
    a[:40, 8 * k:8 * k + 30] = np.nan          # brzeg po rejestracji: inne miejsce w każdej klatce
    a[600 + k, 600 + k] = np.inf
    if nan_all:
        a[:] = np.nan
    return streaks.Binned("ok", streaks._bin_mean(a, 4), 4, SHAPE)


def test_nan_w_kazdej_klatce_nie_wylacza_sekwencji():
    """Piksel NaN w każdej klatce: wszystkie klatki `done`, ślad znaleziony tylko w swojej
    (falsyfikator: `np.median` niósł NaN do σ - cała sekwencja `skipped:no_noise`)."""
    results = list(streaks.scan_sequence(6, _binned_with_nan))
    assert [r.status for r in results] == ["done"] * 6
    assert [len(r.streaks) for r in results] == [0, 0, 1, 0, 0, 0]
    assert _coverage(results[2].streaks[0], *STREAK[:2]) > 0.7
    assert all(math.isfinite(r.sigma) for r in results)


def test_klatka_cala_nan_degraduje_tylko_siebie():
    results = list(streaks.scan_sequence(6, lambda j: _binned_with_nan(j, nan_all=(j == 4))))
    assert [r.status for r in results] == ["done"] * 4 + ["skipped:no_noise", "done"]
    assert len(results[2].streaks) == 1


# ---------------------------------------------------------------- porcje sekwencji

def _load(j):
    return streaks.Binned("ok", streaks._bin_mean(_native(j, 4, STREAK if j == 5 else None), 4), 4, SHAPE)


def test_porcja_sekwencji_daje_te_same_wyniki_co_calosc():
    """Sąsiedzi zależą od sekwencji, nie od porcji: sklejone porcje = przebieg całości
    (falsyfikator: okno dosunięte do brzegu porcji zmienia sąsiadów klatek brzegowych)."""
    full = list(streaks.scan_sequence(9, _load))
    parts = [r for lo, hi in ((0, 2), (2, 5), (5, 9)) for r in streaks.scan_sequence(9, _load, start=lo, stop=hi)]
    assert [r.index for r in parts] == list(range(9))
    assert [(r.status, r.streaks, r.sigma, r.margin) for r in parts] == \
        [(r.status, r.streaks, r.sigma, r.margin) for r in full]


# ---------------------------------------------------------------- PNG i wycinek

def _decode_png(data):
    """Minimalny dekoder PNG (filtr 0, 8 bit) - dowód, że plik jest poprawny i niesie te piksele."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        n, = struct.unpack(">I", data[pos:pos + 4])
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        crc, = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])
        assert crc == zlib.crc32(tag + body)
        chunks[tag] = chunks.get(tag, b"") + body
        pos += 12 + n
    w, h, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    ch = {0: 1, 2: 3}[colour]
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(h, 1 + w * ch)
    assert depth == 8 and not raw[:, 0].any()
    return raw[:, 1:].reshape(h, w, ch) if ch == 3 else raw[:, 1:]


def test_png_szarosc_i_rgb():
    g = np.arange(12 * 7, dtype=np.uint8).reshape(7, 12)
    assert np.array_equal(_decode_png(streaks.png_bytes(g)), g)
    rgb = np.random.default_rng(1).integers(0, 256, (5, 9, 3), dtype=np.uint8)
    assert np.array_equal(_decode_png(streaks.png_bytes(rgb)), rgb)
    with pytest.raises(ValueError):
        streaks.png_bytes(np.zeros((0, 3), np.uint8))


def test_wycinek_ma_linie_prowadzace_obok_sladu_nie_na_nim():
    frames = {j: _load(j).data for j in range(9)}
    res = streaks.detect_frame(5, frames[5], streaks.neighbours(5, frames), crops=True)
    crop, = res.crops
    red = (crop[:, :, 0] == 255) & (crop[:, :, 1] == 40)
    assert red.sum() > 50
    # oś śladu (środek wycinka) nie jest zamalowana: linie stoją ±GUIDE_OFFSET od niej
    cy, cx = crop.shape[0] // 2, crop.shape[1] // 2
    assert not red[cy - 1:cy + 2, cx - 1:cx + 2].any()
    assert max(crop.shape[:2]) <= streaks.CROP_MAX


def test_dlugi_wycinek_zmniejszony_do_crop_max():
    res = streaks.Residual(np.zeros((900, 1600), np.float32), 1.0, np.zeros((900, 1600), bool), 8, 4)
    img = streaks.render_crop((math.radians(90.0), 450.0, 0.0, 1500.0), res)
    assert max(img.shape[:2]) <= streaks.CROP_MAX and img.shape[2] == 3


# ---------------------------------------------------------------- fakty z nagłówka

@pytest.mark.parametrize("text, want", [
    ("2026-08-12T22:12:22.0738", datetime(2026, 8, 12, 22, 12, 22, 73800)),
    ("2026-08-12T22:12:22.1234567", datetime(2026, 8, 12, 22, 12, 22, 123456)),
    ("2026-08-12T22:12:22", datetime(2026, 8, 12, 22, 12, 22)),
    ("2026-08-12 22:12:22.5", datetime(2026, 8, 12, 22, 12, 22, 500000)),
    ("2026-08-12", None), ("wczoraj", None), (None, None), ("2026-08-12T22:12:22.x", None),
])
def test_date_obs(text, want):
    assert streaks._date_obs(text) == want


def _write_fits(path, data, *, t, imagetyp="Light Frame", date=True, exptime=3.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(np.clip(data, 0, 65535).astype(np.uint16))
    h = hdu.header
    h["IMAGETYP"] = imagetyp
    if date:
        h["DATE-OBS"] = t.isoformat(timespec="microseconds")
    h["EXPTIME"] = exptime
    h["INSTRUME"] = "ZWO ASI2600MM Pro"
    h["TELESCOP"] = "A140R"
    h["FILTER"] = "L"
    h["XBINNING"] = 1
    h["OBJCTROT"] = 178.47
    hdu.writeto(path)
    return str(path)


T0 = datetime(2026, 8, 12, 22, 0, 0)


@pytest.fixture
def noc(tmp_path):
    """Katalog nocy: 9 lightów (ślad w klatce 5, kadencja 7 s), dark, RAW, light bez DATE-OBS."""
    root = tmp_path / "noc"
    for k in range(9):
        _write_fits(root / "L" / f"sub_{k:04d}.fits", _native(k, 4, STREAK if k == 5 else None),
                    t=T0 + timedelta(seconds=7 * k + 0.25))
    _write_fits(root / "dark_0001.fits", _native(0, 9), t=T0, imagetyp="Dark Frame")
    _write_fits(root / "bez_daty.fits", _native(0, 8), t=T0, date=False)
    (root / "ostatni.dng").write_bytes(b"II*\x00")
    return root


def test_fakty_z_naglowka_i_statusy(noc):
    paths, unread = streaks.folder_inputs(str(noc))
    assert unread == [] and len(paths) == 12
    facts = {os.path.basename(p): streaks.folder_facts(p) for p in paths}
    assert facts["dark_0001.fits"] == (None, "skipped:kind_dark")
    assert facts["bez_daty.fits"] == (None, "skipped:no_date")
    assert facts["ostatni.dng"] == (None, "skipped:raw")
    f, status = facts["sub_0003.fits"]
    assert status is None and (f.width, f.height, f.exptime, f.filter, f.rotation) == (640, 640, 3.0, "L", 178.47)
    assert f.time == T0 + timedelta(seconds=21.25)


def _rows(files, name):
    return list(csv.DictReader(io.StringIO(dict(files)[name].decode("utf-8"))))


def test_raport_katalogu_nie_zalezy_od_workers(noc, monkeypatch):
    """Porcje po 2 klatki na 3 wątkach dają bajt w bajt ten sam raport co jeden wątek (poza
    manifestem, który zapisuje `workers` i czas)."""
    paths, _ = streaks.folder_inputs(str(noc))
    one = streaks.report_files(streaks.scan_folder(str(noc), paths, workers=1), started="a", finished="b")
    monkeypatch.setattr(streaks, "CHUNK_MIN", 2)
    monkeypatch.setattr(streaks, "CHUNK_MAX", 2)
    many = streaks.report_files(streaks.scan_folder(str(noc), paths, workers=3), started="a", finished="b")
    assert [n for n, _ in one] == [n for n, _ in many]
    assert [d for n, d in one if n != "manifest.json"] == [d for n, d in many if n != "manifest.json"]


def test_raport_katalogu_tresc(noc):
    paths, _ = streaks.folder_inputs(str(noc))
    res = streaks.scan_folder(str(noc), paths, workers=2)
    files = streaks.report_files(res, started="2026-10-05T10:00:00+00:00", finished="x")
    names = [n for n, _ in files]
    assert names[0] == "frames.csv" and names[-1] == "manifest.json"
    assert "mosaic.png" in names and "crops/s000_f0005_0.png" in names

    frames = {r["file"]: r for r in _rows(files, "frames.csv")}
    assert frames[os.path.join("L", "sub_0005.fits")]["streaks"] == "1"
    assert frames["dark_0001.fits"]["status"] == "skipped:kind_dark"
    assert frames["ostatni.dng"]["status"] == "skipped:raw"
    assert sum(r["status"] == "done" for r in frames.values()) == 9

    row, = _rows(files, "streaks.csv")
    assert (row["seq"], row["frame"], row["class"], row["crop"]) == ("0", "5", "satelita", "crops/s000_f0005_0.png")
    # piksele NATYWNE: końce leżą przy wstrzykniętych (250, 260) - (420, 370), nie przy binowanych /4
    ends = sorted(((float(row["x0"]), float(row["y0"])), (float(row["x1"]), float(row["y1"]))))
    assert math.dist(ends[0], STREAK[0]) < 12 and math.dist(ends[1], STREAK[1]) < 12
    _decode_png(dict(files)["crops/s000_f0005_0.png"])
    _decode_png(dict(files)["mosaic.png"])

    summary = json.loads(dict(files)["summary.json"])
    assert (summary["files"], summary["streaks"], summary["tracks"], len(summary["sequences"])) == (12, 1, 0, 1)
    assert summary["statuses"]["done"] == 9 and summary["limiting_mag"] is None
    manifest = json.loads(dict(files)["manifest.json"])
    assert manifest["k_sigma"] == streaks.K_SIGMA and manifest["min_len_native"] == streaks.MIN_LEN_NATIVE
    assert manifest["n_files"] == 12 and manifest["wcs"] is None and len(manifest["inputs_sha1"]) == 40
    assert manifest["started"] == "2026-10-05T10:00:00+00:00"


def test_manifest_widzi_zmiane_wejscia(noc):
    """`inputs_sha1` niesie ścieżkę, mtime i rozmiar: dotknięty plik zmienia manifest."""
    paths, _ = streaks.folder_inputs(str(noc))
    a = streaks.scan_folder(str(noc), paths).inputs_sha1
    st = os.stat(paths[0])
    os.utime(paths[0], ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    assert streaks.scan_folder(str(noc), paths).inputs_sha1 != a


def test_blad_io_pojedynczego_pliku_to_status_klatki_nie_przerwanie(noc, monkeypatch):
    """Przejściowy `OSError` (ACL, zerwany SMB, plik zniknął po wylistowaniu) w trybie katalogu =
    status `error:io` tej klatki; reszta nocy liczy się dalej, ślad w klatce 5 jest znaleziony
    (bramka kimi K1: wcześniej wyjątek przerywał cały przebieg)."""
    paths, _ = streaks.folder_inputs(str(noc))
    znikniety = os.path.join(str(noc), "L", "sub_9999.fits")
    zly_odczyt = os.path.join(str(noc), "L", "sub_0002.fits")
    prawdziwy = streaks.read_binned

    def read_binned(path, bin=streaks.BIN):
        if path == zly_odczyt:
            raise PermissionError(13, "Odmowa dostepu", path)
        return prawdziwy(path, bin)

    monkeypatch.setattr(streaks, "read_binned", read_binned)
    res = streaks.scan_folder(str(noc), paths + [znikniety], workers=2)
    status = {os.path.basename(f.path): f.status for f in res.frames}
    assert status["sub_9999.fits"] == "error:io" and status["sub_0002.fits"] == "error:io"
    assert sum(s == "done" for s in status.values()) == 8
    assert [(s.frame.index, s.cls) for s in res.streaks] == [(5, "satelita")]
    streaks.report_files(res, started="a", finished="b")       # raport składa się mimo błędów
