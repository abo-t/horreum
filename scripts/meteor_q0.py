#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meteor_q0.py - bramka metrologiczna Q0 paczki Q (brief/PLAN_meteory.md §3): czy detektor śladów widzi
meteor na subach o danym czasie naświetlania, ile daje fałszywych alarmów i jak wyrównanie sąsiadów
zmienia jedno i drugie. Skrypt dev-owy, NIE kod produktu: archiwum tylko czyta, pisze wyłącznie do `--out`;
`--out` w katalogu któregokolwiek pliku wejścia (albo pod nim) albo pod korzeniem archiwum `R:\\ASTRO_` = odmowa.

Metoda (Gural 2008 przeniesiony z wideo na suby):
  reszta   = sub - mediana ±N_NB sąsiadów (wyrównanych korelacją fazową) - tło grube; σ z MAD
  wykrycie = próg k·σ + Hough + scalanie współliniowych segmentów
  czułość  = ślady WSTRZYKIWANE w resztę (liniowość: bin(sub + ślad) = bin(sub) + bin(ślad)) z jasnością
             w elektronach na piksel natywny w osi śladu; trzy rodzaje: meteor (zwężenie, końce w kadrze),
             meteor przez kadr, satelita (stały, ostre końce)
  alarmy   = kontrola negatywna: ta sama detekcja na -reszcie; prawdziwe ślady są tylko dodatnie,
             a resztki gwiazd i szum są symetryczne
  jasność  = punkt zerowy z ASTAP (`-extract2`) + Gaia DR3 (VizieR); magnitudo meteoru przy prędkości
             kątowej 10°/s; przeliczenie na inną: m(ω) = m(10) - 2,5·log10(ω/10) - szybszy meteor krócej
             naświetla piksel, więc przy tym samym progu e⁻/px musi być jaśniejszy (mniejsze magnitudo)

Użycie:
  meteor_q0.py inject --db <baza> --config 9 --exptime 60 --filter R --date 2026-04-22 --n 24 --out <katalog>
  meteor_q0.py inject --folder <katalog> --start 0 --n 40 --out <katalog>
  meteor_q0.py links --csv <detections.csv prototypu> --out <katalog> [--max-dist 5]
Wspólne: --bin 4 (w `links`: skala współrzędnych CSV prototypu), --seed 1.
`inject`: --align int|sub|both (domyślnie both), --k-sigma 4, --min-len 80 (px natywne),
--astap <ścieżka astap_cli.exe> (brak = bez jasności w magnitudo).
`links`: --max-dist = odległość końca śladu od prostej poprzednika w px natywnych (plan §2: 5).
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import io
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
from astropy.io import fits

AMPS_E = (3, 6, 12, 25, 50, 100, 200)          # jasność w osi śladu, e⁻ na piksel natywny
KINDS = ("meteor", "meteor_edge", "satellite")
OMEGA_REF = 10.0                               # °/s, prędkość kątowa meteoru do przeliczenia na magnitudo
N_NB = 2                                       # sąsiedzi z każdej strony klatki; mediana z 2·N_NB klatek
ARCHIVE_ROOT = r"R:\ASTRO_"                    # korzeń archiwum: `--out` pod nim = odmowa, niezależnie od wejścia


# ---------------------------------------------------------------- wejście i wyjście

def refuse_out_near_inputs(out, files):
    """Odmowa, gdy `out` leży w katalogu któregoś pliku wejścia albo pod nim, albo pod korzeniem archiwum.
    Porównanie po `normcase(abspath)`: na Windows wielkość liter nie rozróżnia ścieżek, a surowe `startswith`
    myli `R:\\A` z `R:\\AB`. `abspath`, nie `realpath` - ten zamienia dysk mapowany na UNC i rozjeżdża porównanie."""
    def norm(p):
        return os.path.normcase(os.path.abspath(p))
    o = norm(out)
    for root in sorted({norm(os.path.dirname(f)) for f in files} | {norm(ARCHIVE_ROOT)}):
        try:
            under = os.path.commonpath([o, root]) == root
        except ValueError:                     # różne dyski - `out` nie może leżeć pod `root`
            under = False
        if under:
            sys.exit(f"--out {out} leży w {root} albo pod nim - odmowa")


def write_atomic(path, text):
    """Zapis przez `.tmp` + `os.replace`: błąd kodowania nie zostawia uciętego pliku docelowego."""
    data = text.encode("utf-8")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def load(path):
    with fits.open(path, memmap=False) as hd:
        prim = hd[0].header
        for h in hd:
            if h.data is not None and getattr(h.data, "ndim", 0) == 2:
                hdr = fits.Header(prim)
                hdr.update(h.header)
                return h.data.astype(np.float32), hdr   # astropy stosuje BSCALE/BZERO
    raise ValueError(f"brak obrazu 2D: {path}")


def binmean(a, b):
    ny, nx = a.shape[0] // b * b, a.shape[1] // b * b
    return a[:ny, :nx].reshape(ny // b, b, nx // b, b).mean(axis=(1, 3))


def files_from_db(db, config, exptime, filt, date, n):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT h.date_obs, (SELECT l.path FROM location l WHERE l.frame_id = f.id AND l.present = 1 "
        "ORDER BY l.id LIMIT 1) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.filetype = 'fits' AND f.retired_at IS NULL AND f.config_id = ? "
        "AND round(h.exptime) = ? AND f.filter_canon = ? AND substr(h.date_obs, 1, 10) = ? "
        "ORDER BY h.date_obs", (config, exptime, filt, date)).fetchall()
    return [r[1] for r in rows if r[1]][:n]


# ---------------------------------------------------------------- wyrównanie i reszta

def _clip(a):
    a = a - np.median(a)
    return np.clip(a, 0, np.percentile(a, 99.9))


def phase_shift(ref, img, sub):
    A, B = np.fft.rfft2(_clip(ref)), np.fft.rfft2(_clip(img))
    F = A * np.conj(B)
    cc = np.fft.irfft2(F / (np.abs(F) + 1e-9), s=ref.shape)
    py, px = np.unravel_index(int(cc.argmax()), cc.shape)
    dy, dx = float(py), float(px)
    if sub:
        def para(m1, c, p1):
            den = m1 - 2 * c + p1
            return 0.0 if den == 0 else 0.5 * (m1 - p1) / den
        ny, nx = cc.shape
        dy += para(cc[(py - 1) % ny, px], cc[py, px], cc[(py + 1) % ny, px])
        dx += para(cc[py, (px - 1) % nx], cc[py, px], cc[py, (px + 1) % nx])
    if dy > ref.shape[0] / 2:
        dy -= ref.shape[0]
    if dx > ref.shape[1] / 2:
        dx -= ref.shape[1]
    return dy, dx


def apply_shift(img, dy, dx, sub):
    if not sub:
        return np.roll(np.roll(img, int(round(dy)), 0), int(round(dx)), 1)
    F = np.fft.rfft2(img)
    ky = np.fft.fftfreq(img.shape[0])[:, None]
    kx = np.fft.rfftfreq(img.shape[1])[None, :]
    return np.fft.irfft2(F * np.exp(-2j * np.pi * (ky * dy + kx * dx)), s=img.shape).astype(np.float32)


def coarse_bg(r, cell=64):
    ny, nx = r.shape
    gy, gx = ny // cell, nx // cell
    g = np.median(r[:gy * cell, :gx * cell].reshape(gy, cell, gx, cell), axis=(1, 3))
    g = np.repeat(np.repeat(g, cell, 0), cell, 1)
    out = np.empty_like(r)
    out[:g.shape[0], :g.shape[1]] = g
    out[g.shape[0]:, :g.shape[1]] = g[-1:, :]
    out[:, g.shape[1]:] = out[:, g.shape[1] - 1:g.shape[1]]
    return out


def dilate(m, k=2):
    out = m.copy()
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def residual(imgs, i, sub):
    """Reszta klatki i względem mediany ±N_NB sąsiadów; None gdy sąsiadów mniej niż 2·N_NB."""
    nb = [j for j in range(i - N_NB, i + N_NB + 1) if j != i and 0 <= j < len(imgs)]
    if len(nb) < 2 * N_NB:
        return None
    shifts = [phase_shift(imgs[i], imgs[j], sub) for j in nb]
    stack = [apply_shift(imgs[j], dy, dx, sub) for j, (dy, dx) in zip(nb, shifts)]
    med = np.median(np.stack(stack), axis=0)
    r = imgs[i] - med
    r -= coarse_bg(r)
    sig = 1.4826 * float(np.median(np.abs(r - np.median(r))))
    bgm = med - coarse_bg(med)
    stars = dilate(bgm > 8 * sig, 2)
    margin = int(math.ceil(max(max(abs(dy), abs(dx)) for dy, dx in shifts))) + 8
    return dict(r=r, sig=sig, stars=stars, margin=margin, shifts=shifts)


# ---------------------------------------------------------------- detekcja

def hough(ys, xs, shape, min_len, max_lines=6):
    found = []
    ys, xs = ys.astype(np.float32), xs.astype(np.float32)
    th = np.deg2rad(np.arange(0, 180, 0.5)).astype(np.float32)
    c, s = np.cos(th), np.sin(th)
    diag = int(math.hypot(*shape)) + 2
    rb = 2.0
    nr = int(2 * diag / rb) + 1
    alive = np.ones(len(xs), bool)
    for _ in range(max_lines):
        idx = np.nonzero(alive)[0]
        if len(idx) < min_len:
            break
        x, y = xs[idx], ys[idx]
        ri = ((np.outer(x, c) + np.outer(y, s) + diag) / rb).astype(np.int32)
        acc = np.bincount((ri * len(th) + np.arange(len(th))).ravel(), minlength=nr * len(th))
        best = int(acc.argmax())
        if acc[best] < min_len:
            break
        r0, t0 = divmod(best, len(th))
        rho0 = r0 * rb - diag + rb / 2
        near = np.abs(x * c[t0] + y * s[t0] - rho0) <= 2.5
        t = (-x * s[t0] + y * c[t0])[near]
        order = np.sort(t)
        gaps = np.nonzero(np.diff(order) > 12)[0]
        starts, ends = np.r_[0, gaps + 1], np.r_[gaps, len(order) - 1]
        k = int(np.argmax(order[ends] - order[starts]))
        ta, tb = float(order[starts[k]]), float(order[ends[k]])
        npts = int(ends[k] - starts[k] + 1)
        alive[idx[near]] = False
        if tb - ta < min_len or npts / max(tb - ta, 1) < 0.7:
            continue
        found.append((float(th[t0]), rho0, ta, tb))
    return found


def seg_points(th, rho, ta, tb):
    c, s = math.cos(th), math.sin(th)
    return (rho * c - ta * s, rho * s + ta * c), (rho * c - tb * s, rho * s + tb * c)


def merge(segs):
    """Scalanie współliniowych segmentów jednej klatki (Z8): |Δθ| ≤ 1°, ta sama prosta ±3 px binowane
    (kosz rho Hougha ma 2 px, więc ±2 rozcinało jeden ślad), przerwa ≤ 10 % sumy długości albo nakładka."""
    segs = sorted(segs, key=lambda q: -(q[3] - q[2]))
    out = []
    for th, rho, ta, tb in segs:
        for m in out:
            dth = abs((math.degrees(th - m[0]) + 90) % 180 - 90)
            if dth <= 1.0:
                p0, p1 = seg_points(th, rho, ta, tb)
                c, s = math.cos(m[0]), math.sin(m[0])
                if all(abs(p[0] * c + p[1] * s - m[1]) <= 3.0 for p in (p0, p1)):
                    t0, t1 = sorted((-p0[0] * s + p0[1] * c, -p1[0] * s + p1[1] * c))
                    gap = max(t0 - m[3], m[2] - t1, 0)
                    if gap <= 0.1 * ((m[3] - m[2]) + (t1 - t0)):
                        m[2], m[3] = min(m[2], t0), max(m[3], t1)
                        break
        else:
            out.append([th, rho, ta, tb])
    return out


def measure(seg, r, sig, stars, bin_, edge_margin):
    th, rho, ta, tb = seg
    (x0, y0), (x1, y1) = seg_points(th, rho, ta, tb)
    n = max(int(tb - ta) + 1, 2)
    xs, ys = np.linspace(x0, x1, n), np.linspace(y0, y1, n)
    nx, ny = math.cos(th), math.sin(th)
    H, W = r.shape

    def sample(off):
        xi = np.clip(np.round(xs + off * nx).astype(int), 0, W - 1)
        yi = np.clip(np.round(ys + off * ny).astype(int), 0, H - 1)
        return r[yi, xi], stars[yi, xi]

    core = np.zeros(n)
    masked = np.zeros(n, bool)
    for off in (-1, 0, 1):
        v, m = sample(off)
        core += v
        masked |= m
    prof = core / (3 * sig)
    ok = ~masked
    p = prof[ok] if ok.sum() >= 5 else prof
    q = max(len(p) // 10, 1)
    mid = float(np.median(p[q:-q])) if len(p) > 2 * q else float(np.median(p))
    margin = edge_margin + 3          # detekcja nie widzi marginesu wyrównania - tam jest „krawędź”

    def inside(x, y):
        return margin < x < W - 1 - margin and margin < y < H - 1 - margin
    ends = []
    for x, y, part in ((x0, y0, p[:q]), (x1, y1, p[-q:])):
        ends.append(round(float(np.mean(part)) / max(mid, 1e-6), 3) if inside(x, y) else None)
    return dict(x0=x0 * bin_ + (bin_ - 1) / 2, y0=y0 * bin_ + (bin_ - 1) / 2,
                x1=x1 * bin_ + (bin_ - 1) / 2, y1=y1 * bin_ + (bin_ - 1) / 2,
                length=(tb - ta) * bin_, theta=math.degrees(th), snr=round(mid, 2),
                cv=round(float(p.std() / max(abs(p.mean()), 1e-6)), 3), end0=ends[0], end1=ends[1],
                edge_ends=sum(e is None for e in ends), masked_frac=round(float(masked.mean()), 3))


def detect(res, sign, k_sigma, min_len_native, bin_, inj=None):
    r = res["r"] if inj is None else res["r"] + inj
    x = sign * r
    x = np.where(res["stars"], 0, x)
    m = x > k_sigma * res["sig"]
    nbc = sum(np.roll(np.roll(m, dy, 0), dx, 1).astype(np.int8)
              for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - m
    m &= nbc >= 2
    g = res["margin"]
    m[:g, :] = m[-g:, :] = False
    m[:, :g] = m[:, -g:] = False
    ys, xs = np.nonzero(m)
    min_len = max(int(round(min_len_native / bin_)), 5)
    if len(xs) < min_len:
        return []
    if len(xs) > 80000:
        return [dict(overflow=len(xs))]
    segs = merge(hough(ys, xs, r.shape, min_len))
    return [measure(s, sign * r, res["sig"], res["stars"], bin_, g) for s in segs]


# ---------------------------------------------------------------- wstrzykiwanie

def render(shape_b, bin_, p0, p1, peak_adu, sigma, lc):
    """Ślad w pikselach natywnych (środki pikseli w liczbach całkowitych), zbinowany średnią do shape_b."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = int(L / 0.5) + 2
    t = np.linspace(0, 1, n)
    xs = p0[0] + (p1[0] - p0[0]) * t
    ys = p0[1] + (p1[1] - p0[1]) * t
    w = peak_adu * math.sqrt(2 * math.pi) * sigma * lc(t) * (L / (n - 1))
    out = np.zeros(shape_b, np.float32)
    H, W = shape_b[0] * bin_, shape_b[1] * bin_
    rad = int(math.ceil(3 * sigma))
    fx, fy = np.floor(xs).astype(int), np.floor(ys).astype(int)
    for oy in range(-rad, rad + 2):
        for ox in range(-rad, rad + 2):
            X, Y = fx + ox, fy + oy
            g = np.exp(-((X - xs) ** 2 + (Y - ys) ** 2) / (2 * sigma ** 2)) / (2 * math.pi * sigma ** 2)
            ok = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
            np.add.at(out, (Y[ok] // bin_, X[ok] // bin_), (w[ok] * g[ok]) / bin_ ** 2)
    return out


def geometry(kind, rng, W, H):
    if kind == "meteor_edge":
        cx, cy = rng.uniform(0.3 * W, 0.7 * W), rng.uniform(0.3 * H, 0.7 * H)
        a = rng.uniform(0, math.pi)
        dx, dy = math.cos(a), math.sin(a)
        ts = []
        for t in ((0 - cx) / dx if dx else None, (W - 1 - cx) / dx if dx else None,
                  (0 - cy) / dy if dy else None, (H - 1 - cy) / dy if dy else None):
            if t is not None:
                x, y = cx + t * dx, cy + t * dy
                if -1e-6 <= x <= W - 1 + 1e-6 and -1e-6 <= y <= H - 1 + 1e-6:
                    ts.append(t)
        ta, tb = min(ts), max(ts)
        return (cx + ta * dx, cy + ta * dy), (cx + tb * dx, cy + tb * dy)
    L = rng.uniform(800, 2500)
    a = rng.uniform(0, math.pi)
    dx, dy = math.cos(a) * L / 2, math.sin(a) * L / 2
    cx = rng.uniform(abs(dx) + 200, W - abs(dx) - 200)
    cy = rng.uniform(abs(dy) + 200, H - abs(dy) - 200)
    return (cx - dx, cy - dy), (cx + dx, cy + dy)


LIGHT = {
    "meteor": lambda t: np.sin(np.pi * t) ** 1.2,
    "meteor_edge": lambda t: 0.7 + 0.3 * np.sin(np.pi * (0.8 * t + 0.1)),
    "satellite": lambda t: np.ones_like(t),
}


def coverage(dets, p0, p1):
    """Część wstrzykniętego śladu pokryta sumą pasujących odcinków (0 = nie wykryty). Trafieniem jest
    KAŻDY odcinek na tej prostej - długi ślad bywa pocięty szumem, a o wykryciu zdarzenia rozstrzyga
    obecność, nie ciągłość; pokrycie raportowane osobno."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    iv = []
    for d in dets:
        if matches(d, p0, p1):
            t = sorted(((d["x0"] - p0[0]) * ux + (d["y0"] - p0[1]) * uy,
                        (d["x1"] - p0[0]) * ux + (d["y1"] - p0[1]) * uy))
            iv.append((max(t[0], 0.0), min(t[1], L)))
    tot, end = 0.0, -1e9
    for a_, b_ in sorted(iv):
        if b_ > end:
            tot += b_ - max(a_, end)
            end = b_
    return tot / L


def matches(det, p0, p1):
    """Odcinek leży na prostej wstrzykniętego śladu (kąt ≤ 1,5°, środek ≤ 8 px natywnych od prostej)
    i przynajmniej częściowo w jego zakresie."""
    if "overflow" in det:
        return False
    ang_i = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    ang_d = math.degrees(math.atan2(det["y1"] - det["y0"], det["x1"] - det["x0"]))
    if abs((ang_i - ang_d + 90) % 180 - 90) > 1.5:
        return False
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    mx, my = (det["x0"] + det["x1"]) / 2, (det["y0"] + det["y1"]) / 2
    if abs((mx - p0[0]) * uy - (my - p0[1]) * ux) > 8:
        return False
    t = sorted(((det["x0"] - p0[0]) * ux + (det["y0"] - p0[1]) * uy,
                (det["x1"] - p0[0]) * ux + (det["y1"] - p0[1]) * uy))
    return min(t[1], L) - max(t[0], 0.0) > 0


# ---------------------------------------------------------------- fotometria (ASTAP + Gaia)

def zero_point(path, hdr, out, astap):
    """ZP (G, ADU/s) i HFD gwiazd [px natywne] z kopii klatki w `out` - oryginału ASTAP nie dotyka."""
    if not astap:
        return None
    work = os.path.join(out, "astap")
    os.makedirs(work, exist_ok=True)
    cp = os.path.join(work, "solve.fits")
    # produkty poprzedniego wywołania: nieudane rozwiązanie tej klatki zostawiłoby cudzy katalog gwiazd jako wynik
    for ext in (".csv", ".wcs", ".ini"):
        stale = os.path.join(work, "solve" + ext)
        if os.path.exists(stale):
            os.remove(stale)
    shutil.copyfile(path, cp)
    fov = hdr["NAXIS2"] * float(hdr.get("XPIXSZ", 3.76)) * hdr.get("XBINNING", 1) / float(hdr["FOCALLEN"]) * 206.265 / 3600
    started = time.time()
    proc = subprocess.run([astap, "-f", cp, "-r", "10", "-fov", f"{fov:.3f}", "-extract2", "10"],
                          capture_output=True, timeout=600)
    if proc.returncode != 0:
        print(f"ASTAP: kod wyjścia {proc.returncode} dla {os.path.basename(path)} - bez punktu zerowego",
              file=sys.stderr)
        return None
    csvp = os.path.join(work, "solve.csv")
    if not os.path.exists(csvp) or os.path.getmtime(csvp) < started:
        print(f"ASTAP: brak solve.csv z tego wywołania dla {os.path.basename(path)} - bez punktu zerowego",
              file=sys.stderr)
        return None
    stars = list(csv.DictReader(open(csvp, encoding="utf-8")))
    if len(stars) < 20:
        return None
    ra = np.array([float(s["ra[0..360]"]) for s in stars])
    de = np.array([float(s["dec[0..360]"]) for s in stars])
    fl = np.array([float(s["flux"]) for s in stars])
    hfd = float(np.median([float(s["hfd"]) for s in stars]))
    url = ("https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=I/355/gaiadr3&-out=RA_ICRS,DE_ICRS,Gmag"
           f"&-c={np.median(ra):.4f}%20{np.median(de):+.4f}&-c.rd=0.8&Gmag=%3C16&-out.max=30000")
    cat = []
    for line in urllib.request.urlopen(url, timeout=120).read().decode("utf-8", "replace").splitlines():
        f = line.split("\t")
        try:
            cat.append((float(f[0]), float(f[1]), float(f[2])))
        except (ValueError, IndexError):
            pass
    cat = np.array(cat)
    exptime = float(hdr["EXPTIME"])
    zp = []
    for a, d, f in zip(ra, de, fl):
        if f <= 0:
            continue
        dist = np.hypot((cat[:, 0] - a) * math.cos(math.radians(d)), cat[:, 1] - d) * 3600
        k = int(dist.argmin())
        if dist[k] < 2.0 and np.sort(dist)[1] > 8.0:
            zp.append(cat[k, 2] + 2.5 * math.log10(f / exptime))
    if len(zp) < 20:
        return None
    zp = np.array(zp)
    return dict(zp=round(float(np.median(zp)), 3), zp_mad=round(float(np.median(abs(zp - np.median(zp)))), 3),
                n_pairs=len(zp), hfd=round(hfd, 2))


def meteor_mag(e_peak, zp, egain, sigma, pixscale):
    """Magnitudo G meteoru dającego `e_peak` e⁻ w osi śladu przy ω = OMEGA_REF °/s."""
    dwell = pixscale / (OMEGA_REF * 3600.0)
    return zp + 2.5 * math.log10(egain * dwell / (math.sqrt(2 * math.pi) * sigma) / e_peak)


# ---------------------------------------------------------------- przebieg „inject”

def run_inject(a):
    t0 = time.time()
    if a.folder:
        files = sorted(glob.glob(os.path.join(a.folder, "*.fit*")))[a.start:a.start + a.n]
    else:
        files = files_from_db(a.db, a.config, a.exptime, a.filter, a.date, a.n)
    refuse_out_near_inputs(a.out, files)
    if len(files) < 2 * N_NB + 1:
        sys.exit(f"za mało plików: {len(files)}")
    os.makedirs(a.out, exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        loaded = list(ex.map(load, files))
    order = sorted(range(len(files)), key=lambda k: loaded[k][1].get("DATE-OBS", ""))
    files = [files[k] for k in order]
    hdrs = [loaded[k][1] for k in order]
    imgs = [binmean(loaded[k][0], a.bin) for k in order]
    native_shape = loaded[order[0]][0].shape
    del loaded
    h0 = hdrs[0]
    egain = float(h0.get("EGAIN", 0) or 0)
    if egain <= 0:
        sys.exit("brak EGAIN - jasności w elektronach nie da się ustalić")
    pixscale = float(h0.get("XPIXSZ", 3.76)) * h0.get("XBINNING", 1) / float(h0["FOCALLEN"]) * 206.265
    phot = zero_point(files[len(files) // 2], hdrs[len(files) // 2], a.out, a.astap)
    fwhm = phot["hfd"] if phot else 3.5
    sigma_psf = fwhm / 2.355
    H, W = native_shape
    modes = ("int", "sub") if a.align == "both" else (a.align,)
    # tożsamość wejścia = ścieżka + mtime (zmiana pliku pod tą samą ścieżką zmienia hash); rozmiar NIE jest
    # dyskryminatorem - wszystkie klatki jednej kamery mają ten sam rozmiar
    stamps = sorted(f"{p}\t{os.stat(p).st_mtime_ns}" for p in files)
    manifest = dict(
        files_sha1=hashlib.sha1("\n".join(files).encode()).hexdigest(), n_files=len(files),
        inputs_sha1=hashlib.sha1("\n".join(stamps).encode()).hexdigest(),
        code_sha1=hashlib.sha1(open(__file__, "rb").read()).hexdigest(),
        numpy=np.__version__, astropy=__import__("astropy").__version__,
        k_sigma=a.k_sigma, min_len_native=a.min_len, bin=a.bin, n_neighbours=N_NB, align_modes=modes,
        seed=a.seed, amps_e=AMPS_E, kinds=KINDS,
        exptime=float(h0["EXPTIME"]), filter=h0.get("FILTER"), egain=egain, pixscale=round(pixscale, 4),
        fwhm_px=fwhm, photometry=phot, first=files[0], last=files[-1], omega_ref=OMEGA_REF)
    summary = dict(manifest=manifest, align={})
    rows = []
    for mode in modes:
        sub = mode == "sub"
        targets = list(range(N_NB, len(imgs) - N_NB))

        def one(i):
            res = residual(imgs, i, sub)
            rng = np.random.default_rng(a.seed * 100003 + i)
            neg = detect(res, -1, a.k_sigma, a.min_len, a.bin)
            pos = detect(res, +1, a.k_sigma, a.min_len, a.bin)
            sig_e = res["sig"] * egain * a.bin        # σ reszty w e⁻ na piksel natywny (średnia z bin²)
            out = []
            for kind in KINDS:
                for amp in AMPS_E:
                    p0, p1 = geometry(kind, rng, W, H)
                    inj = render(imgs[i].shape, a.bin, p0, p1, amp / egain, sigma_psf, LIGHT[kind])
                    dets = detect(res, +1, a.k_sigma, a.min_len, a.bin, inj)
                    on_line = [d for d in dets if matches(d, p0, p1)]
                    hit = max(on_line, key=lambda d: d["length"]) if on_line else None
                    out.append(dict(mode=mode, frame=i, kind=kind, amp_e=amp, hit=int(hit is not None),
                                    cov=round(coverage(dets, p0, p1), 3), fragments=len(on_line),
                                    **({k: hit[k] for k in ("snr", "cv", "end0", "end1", "edge_ends",
                                                            "masked_frac", "length")} if hit else {})))
            return i, len(neg), len(pos), sig_e, res["shifts"], out

        with ThreadPoolExecutor(a.workers) as ex:
            got = list(ex.map(one, targets))
        neg_total = sum(g[1] for g in got)
        pos_total = sum(g[2] for g in got)
        for g in got:
            rows.extend(g[5])
        rec = {}
        for kind in KINDS:
            rec[kind] = {amp: round(float(np.mean([r["hit"] for r in rows if r["mode"] == mode and
                                                   r["kind"] == kind and r["amp_e"] == amp])), 3) for amp in AMPS_E}
        e50 = {}
        for kind in KINDS:
            xs = [math.log10(x) for x in AMPS_E]
            ys = [rec[kind][x] for x in AMPS_E]
            e50[kind] = None
            for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
                if y0 < 0.5 <= y1:
                    e50[kind] = round(10 ** (x0 + (0.5 - y0) * (x1 - x0) / (y1 - y0)), 2)
                    break
            if ys[0] >= 0.5:
                e50[kind] = f"<{AMPS_E[0]}"
        mag50 = {k: (round(meteor_mag(v, phot["zp"], egain, sigma_psf, pixscale), 2)
                     if phot and isinstance(v, float) else None) for k, v in e50.items()}
        shifts = [abs(s) for g in got for sh in g[4] for s in sh]
        summary["align"][mode] = dict(
            frames=len(targets), false_alarms_neg=neg_total,
            false_alarms_per_1000=round(1000 * neg_total / len(targets), 1),
            positive_segments=pos_total, sigma_e_native_median=round(float(np.median([g[3] for g in got])), 2),
            max_shift_binned=round(max(shifts), 2) if shifts else 0, recall=rec, e50=e50, mag50_at_10deg_s=mag50)
    summary["seconds"] = round(time.time() - t0, 1)
    buf = io.StringIO()
    keys = ["mode", "frame", "kind", "amp_e", "hit", "cov", "fragments", "snr", "cv", "end0", "end1", "edge_ends", "masked_frac", "length"]
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
    write_atomic(os.path.join(a.out, "injections.csv"), buf.getvalue())
    write_atomic(os.path.join(a.out, "summary.json"),
                 json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n")
    print(json.dumps({m: {k: v for k, v in s.items() if k != "recall"} for m, s in summary["align"].items()},
                     ensure_ascii=False, default=str))


# ---------------------------------------------------------------- przebieg „links”

def link_tracks(segs, times, cadence, max_dist):
    """Tory: kolejne klatki, Δt ≤ 3·kadencja, |Δθ| ≤ 3°, koniec ≤ `max_dist` px natywnych od prostej
    poprzednika, przypisanie 1:1. Współrzędne `segs` są już natywne - próg nie przechodzi przez binning."""
    by_frame = {}
    for s in segs:
        by_frame.setdefault(s["frame"], []).append(s)
    frames = sorted(by_frame)
    # 1:1 PER STRONA: ślad ma najwyżej jednego następnika i jednego poprzednika - wspólny zbiór „użytych”
    # blokował następnika przed zostaniem poprzednikiem i rwał tor 36-40 na pary (pomiar Q0 2026-09-28)
    has_next, has_prev, links = set(), set(), []
    for fa, fb in zip(frames, frames[1:]):
        dt = (times[fb] - times[fa]).total_seconds()
        if dt > 3 * cadence:
            continue
        cands = []
        for i, s in enumerate(by_frame[fa]):
            for j, t in enumerate(by_frame[fb]):
                dth = abs((s["theta"] - t["theta"] + 90) % 180 - 90)
                if dth > 3:
                    continue
                th = math.radians(s["theta"])
                c, sn = math.cos(th), math.sin(th)
                rho = s["x0"] * c + s["y0"] * sn
                d = min(abs(t["x0"] * c + t["y0"] * sn - rho), abs(t["x1"] * c + t["y1"] * sn - rho))
                if d <= max_dist:
                    cands.append((dth + d / max_dist, (fa, i), (fb, j)))
        for _, a_, b_ in sorted(cands):
            if a_ in has_next or b_ in has_prev:
                continue
            has_next.add(a_)
            has_prev.add(b_)
            links.append((a_, b_))
    return links


def run_links(a):
    def native(v):                   # CSV prototypu: współrzędne binowane → natywne, ta sama konwencja co `measure`
        return float(v) * a.bin + (a.bin - 1) / 2
    with open(a.csv, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["status"].startswith("ok")]
    segs = [dict(frame=int(r["idx"]), theta=float(r["theta"]),
                 x0=native(r["x0"]), y0=native(r["y0"]), x1=native(r["x1"]), y1=native(r["y1"]),
                 time=datetime.fromisoformat(r["time"])) for r in rows]
    frames = sorted({s["frame"] for s in segs})
    times = {s["frame"]: s["time"] for s in segs}
    real = link_tracks(segs, times, 7.0, a.max_dist)
    rng = np.random.default_rng(a.seed)
    false = []
    all_idx = sorted({s["frame"] for s in segs})
    for _ in range(2000):
        perm = rng.permutation(len(all_idx))
        remap = {f: all_idx[p] for f, p in zip(all_idx, perm)}
        ps = [dict(s, frame=remap[s["frame"]]) for s in segs]
        # permutacja rozrywa ciągłość czasu: klatki stają się „kolejne” przypadkowo; Δt z indeksu
        pt = {f: datetime.fromtimestamp(f * 7.0) for f in all_idx}
        false.append(len(link_tracks(ps, pt, 7.0, a.max_dist)))
    # model zerowy: każde ogniwo po permutacji jest fałszywe, więc średnia to E[fałszywych ogniw] na noc,
    # NIE precision (brak etykiet TP/FP); precision przybliżona jako 1 - E[fałszywe] / realne
    mean_false = float(np.mean(false))
    res = dict(segments=len(segs), frames=len(frames), bin=a.bin, max_dist_native=a.max_dist,
               real_links=[(x[0][0], x[1][0]) for x in real], real_links_n=len(real),
               null_false_links_mean=round(mean_false, 3), null_false_links_p95=float(np.percentile(false, 95)),
               precision_approx=round(1 - mean_false / len(real), 3) if real else None)
    os.makedirs(a.out, exist_ok=True)
    write_atomic(os.path.join(a.out, "links.json"), json.dumps(res, indent=1) + "\n")
    print(json.dumps(res))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = p.add_subparsers(dest="cmd", required=True)
    pi = sp.add_parser("inject")
    pi.add_argument("--db")
    pi.add_argument("--config", type=int)
    pi.add_argument("--exptime", type=float)
    pi.add_argument("--filter")
    pi.add_argument("--date")
    pi.add_argument("--folder")
    pi.add_argument("--start", type=int, default=0)
    pi.add_argument("--n", type=int, default=24)
    pi.add_argument("--out", required=True)
    pi.add_argument("--align", choices=("int", "sub", "both"), default="both")
    pi.add_argument("--k-sigma", type=float, default=4.0)
    pi.add_argument("--min-len", type=float, default=80.0)
    pi.add_argument("--bin", type=int, default=4)
    pi.add_argument("--seed", type=int, default=1)
    pi.add_argument("--workers", type=int, default=8)
    pi.add_argument("--astap", default=None)
    pl = sp.add_parser("links")
    pl.add_argument("--csv", required=True)
    pl.add_argument("--out", required=True)
    pl.add_argument("--seed", type=int, default=1)
    pl.add_argument("--bin", type=int, default=4)
    pl.add_argument("--max-dist", type=float, default=5.0)
    a = p.parse_args()
    (run_inject if a.cmd == "inject" else run_links)(a)


if __name__ == "__main__":
    main()
