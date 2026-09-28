"""BUDOWNICZY LISTY ROJÓW METEORÓW - `horreum/data/meteor_showers.json` z listy rojów USTALONYCH IAU MDC.

Źródło: IAU Meteor Data Center, „Established meteor showers” (`streamestablisheddata<ROK>.txt`,
`www.ta3.sk/IAUC22DB/MDC2022/Etc/`). Aplikacja NIGDY nie woła sieci (D-0731-3): lista odświeża się
PODMIANĄ PLIKU. Skrypt jest dev-owy i żyje poza pakietem, jak `build_catalog.py`.

Jeden rój ma w MDC kilka zestawów parametrów (różne prace, różne techniki). Wybór - w tej kolejności:
  1. status `s == 1` (rój ustalony) i aktywność roczna (`annual`) - wybuchy jednego roku odpadają;
  2. zestaw z KOMPLETEM: zakres aktywności (LoSb, LoSe) + dryf radiantu (dRa, dDe);
  3. największa liczba członków `N` (najmocniejsza statystyka).
Rój bez zestawu z zakresem aktywności dostaje zakres ±5° wokół LoS i flagę `range_estimated` -
detektor wie wtedy, że okno jest szacowane, a nie zmierzone.

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


def _num(s):
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith('"'):
            continue
        f = [c.strip().strip('"').strip() for c in line.split("|")]
        if len(f) < 29:
            continue
        rows.append(dict(code=f[3], s=f[4].strip(), name=f[6], activity=f[7].lower(),
                         los_begin=_num(f[8]), los_end=_num(f[9]), los=_num(f[10]),
                         ra=_num(f[11]), dec=_num(f[12]), dra=_num(f[13]), ddec=_num(f[14]),
                         vg=_num(f[15]), n=int(_num(f[28]) or 0),
                         ref=re.sub(r"<[^>]+>", "", f[-1]).strip()))
    return rows


def choose(rows):
    by = {}
    for r in rows:
        if r["s"] != "1" or "annual" not in r["activity"] or None in (r["los"], r["ra"], r["dec"]):
            continue
        by.setdefault(r["code"], []).append(r)
    out = []
    for code, rs in sorted(by.items()):
        full = [r for r in rs if None not in (r["los_begin"], r["los_end"], r["dra"], r["ddec"])]
        best = max(full or rs, key=lambda r: r["n"])
        est = best["los_begin"] is None or best["los_end"] is None
        out.append(dict(code=code, name=best["name"], los=best["los"],
                        los_begin=round((best["los"] - 5) % 360, 2) if est else best["los_begin"],
                        los_end=round((best["los"] + 5) % 360, 2) if est else best["los_end"],
                        range_estimated=est, ra=best["ra"], dec=best["dec"],
                        dra=best["dra"] or 0.0, ddec=best["ddec"] or 0.0, vg=best["vg"], n=best["n"],
                        ref=best["ref"]))
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
    showers = choose(parse(text))
    errs = falsify(showers)
    print(f"roje: {len(showers)}; zakres szacowany: {sum(s['range_estimated'] for s in showers)}")
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
                                                   "dra": "deg/day", "ddec": "deg/day", "vg": "km/s"},
                       "selection": "s=1, annual, komplet zakresu i dryfu, max N; brak zakresu -> LoS±5 (range_estimated)"},
             "showers": showers}
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(asset, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"zapisano {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
