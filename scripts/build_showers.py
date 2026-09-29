"""BUDOWNICZY LISTY ROJÓW METEORÓW - `horreum/data/meteor_showers.json` z listy rojów USTALONYCH IAU MDC.

Źródło: IAU Meteor Data Center, „Established meteor showers” (`streamestablisheddata<ROK>.txt`,
`www.ta3.sk/IAUC22DB/MDC2022/Etc/`). Aplikacja NIGDY nie woła sieci (D-0731-3): lista odświeża się
PODMIANĄ PLIKU. Skrypt jest dev-owy i żyje poza pakietem, jak `build_catalog.py`.

Jeden rój ma w MDC kilka zestawów parametrów (różne prace, różne techniki). Wybór - w tej kolejności:
  1. status `s == 1` (rój ustalony) i aktywność roczna (`annual`) - wybuchy jednego roku odpadają;
  2. zestaw z KOMPLETEM zakresu aktywności (LoSb, LoSe); dryf radiantu (dRa, dDe) nie jest warunkiem;
  3. największa liczba członków `N` (najmocniejsza statystyka).
Rój bez zestawu z zakresem aktywności dostaje zakres ±5° wokół LoS i flagę `range_estimated` -
detektor wie wtedy, że okno jest szacowane, a nie zmierzone. Rój, którego wybrany zestaw nie ma dryfu
(`dRa` albo `dDe`), dostaje `dra`/`ddec` = null i flagę `drift_estimated` - brak pomiaru nie udaje
zmierzonego zera; dryf szacuje konsument.

Wiersze danych z mniej niż 29 polami, niepuste pola liczbowe, które nie są skończoną liczbą (w tym
`nan`), i zestawy bez LoS/RA/Dec są liczone i wypisywane (numer linii + kod roju). Wiersz za krótki
odpada; takie pole staje się brakiem (N = 0), a zestaw bez LoS/RA/Dec nie startuje w wyborze.

Radiant i długości ekliptyczne Słońca są J2000 (nagłówek pliku MDC). `dra`/`ddec` to ruch dzienny
radiantu (°/dobę) - przeliczenie na stopień długości Słońca robi konsument (`horreum.streaks`).

FALSYFIKATORY przy budowie (EXPECT, kod != 0): PER, GEM, QUA, ORI, LYR, ETA muszą być w assecie
z radiantem w znanym oknie; liczba rojów w widełkach.

Użycie:
  python scripts/build_showers.py                 # pobierz -> zbuduj -> zapisz
  python scripts/build_showers.py --src PLIK      # zbuduj z pobranego pliku (bez sieci)
  python scripts/build_showers.py --dry-run       # policz i pokaż raport, nie zapisuj
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.request
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "horreum", "data", "meteor_showers.json")
URL = "http://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamestablisheddata{year}.txt"

# kotwice falsyfikatora: kod -> (RA, Dec) radiantu w maksimum z tolerancją 5°
KOTWICE = {"PER": (48, 58), "GEM": (113, 33), "QUA": (230, 49), "ORI": (95, 16), "LYR": (272, 33),
           "ETA": (338, -1)}


# kolumny liczbowe pliku MDC (indeks pola po podziale na `|`); LoS/RA/Dec są wymagane do wyboru zestawu
NUM_COLS = {"los_begin": 8, "los_end": 9, "los": 10, "ra": 11, "dec": 12, "dra": 13, "ddec": 14, "vg": 15, "n": 28}
REQUIRED = ("los", "ra", "dec")


def parse(text):
    """Zestawy parametrów + lista problemów `(klasa, nr linii, kod roju, opis)`. Puste pole opcjonalne to
    brak pomiaru, nie problem; niepuste nieparsowalne pole to uszkodzony rekord i ma być widoczne."""
    rows, problems = [], []
    for no, line in enumerate(text.splitlines(), 1):
        if not line.startswith('"'):
            continue
        f = [c.strip().strip('"').strip() for c in line.split("|")]
        if len(f) < 29:
            problems.append(("wiersz", no, f[3] if len(f) > 3 else "?", f"{len(f)} pól zamiast >= 29"))
            continue
        r = dict(code=f[3], s=f[4], name=f[6], activity=f[7].lower(), ref=re.sub(r"<[^>]+>", "", f[-1]).strip())
        for key, col in NUM_COLS.items():
            r[key] = None
            if f[col]:
                try:
                    v = float(f[col])
                except ValueError:
                    v = None
                # MDC pisze `nan` tam, gdzie pomiaru nie ma; `float` to przyjmuje, a NaN przechodzi test kompletu
                if v is None or not math.isfinite(v):
                    problems.append(("pole", no, f[3], f"{key}={f[col]!r} to nie liczba"))
                else:
                    r[key] = v
        missing = [k for k in REQUIRED if r[k] is None]
        if missing:
            problems.append(("wymagane", no, f[3], "brak " + "/".join(missing)))
        r["n"] = int(r["n"] or 0)
        rows.append(r)
    return rows, problems


def choose(rows):
    by = {}
    for r in rows:
        if r["s"] != "1" or "annual" not in r["activity"] or None in (r["los"], r["ra"], r["dec"]):
            continue
        by.setdefault(r["code"], []).append(r)
    out = []
    for code, rs in sorted(by.items()):
        # komplet = zmierzony ZAKRES aktywności; brak dryfu nie wyklucza zestawu (dostaje null + flagę), bo
        # zestaw z kompletem dryfu i garstką członków potrafi mieć radiant o dziesiątki stopni obok (COR)
        full = [r for r in rs if None not in (r["los_begin"], r["los_end"])]
        best = max(full or rs, key=lambda r: r["n"])
        est = best["los_begin"] is None or best["los_end"] is None
        out.append(dict(code=code, name=best["name"], los=best["los"],
                        los_begin=round((best["los"] - 5) % 360, 2) if est else best["los_begin"],
                        los_end=round((best["los"] + 5) % 360, 2) if est else best["los_end"],
                        range_estimated=est, ra=best["ra"], dec=best["dec"],
                        dra=best["dra"], ddec=best["ddec"], drift_estimated=best["dra"] is None or best["ddec"] is None,
                        vg=best["vg"], n=best["n"], ref=best["ref"]))
    return out


def falsify(showers):
    errs = []
    codes = {s["code"]: s for s in showers}
    for code, (ra, dec) in KOTWICE.items():
        s = codes.get(code)
        if s is None:
            errs.append(f"brak roju {code}")
        elif abs((s["ra"] - ra + 180) % 360 - 180) > 5 or abs(s["dec"] - dec) > 5:
            errs.append(f"{code}: radiant {s['ra']},{s['dec']} poza oknem {ra},{dec}")
    if not 60 <= len(showers) <= 200:
        errs.append(f"liczba rojów {len(showers)} poza widełkami 60-200")
    return errs


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--src", help="lokalny plik MDC zamiast pobierania")
    p.add_argument("--year", type=int, default=date.today().year)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.src:
        text = open(a.src, encoding="utf-8", errors="replace").read()
        source = os.path.basename(a.src)
    else:
        url = URL.format(year=a.year)
        text = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
        source = url
    updated = re.search(r"Last update:\s*([^()\n]+?)\s*\(", text)
    rows, problems = parse(text)
    showers = choose(rows)
    errs = falsify(showers)
    count = {k: sum(p[0] == k for p in problems) for k in ("wiersz", "pole", "wymagane")}
    print(f"roje: {len(showers)}; zakres szacowany: {sum(s['range_estimated'] for s in showers)}; "
          f"dryf szacowany: {sum(s['drift_estimated'] for s in showers)}; odrzucone wiersze: {count['wiersz']}; "
          f"pola nieparsowalne: {count['pole']}; zestawy bez LoS/RA/Dec: {count['wymagane']}")
    for _, no, code, what in problems:
        print(f"  linia {no} {code}: {what}")
    if errs:
        print("FALSYFIKATOR:", *errs, sep="\n  ")
        return 1
    if a.dry_run:
        return 0
    asset = {"_meta": {"built": date.today().isoformat(), "source": source,
                       "source_updated": updated.group(1).strip() if updated else None,
                       "license": "dane IAU MDC - cytowanie: Jenniskens i in. 2020, PSS 182, 104821; "
                                  "Jopek & Kanuchova 2017, PSS 143, 3; kod repozytorium: MIT",
                       "epoch": "J2000", "units": {"los": "deg", "ra": "deg", "dec": "deg",
                                                   "dra": "deg/day; null = brak pomiaru (drift_estimated)",
                                                   "ddec": "deg/day; null = brak pomiaru (drift_estimated)",
                                                   "vg": "km/s"},
                       "selection": "s=1, annual, komplet zakresu, max N; brak zakresu -> LoS±5 "
                                    "(range_estimated); brak dryfu -> dra/ddec null (drift_estimated)"},
             "showers": showers}
    data = (json.dumps(asset, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = OUT + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, OUT)
    print(f"zapisano {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
