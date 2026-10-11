"""Import aliasów nazw lightów z zapisu przenosin Custos - jednorazowy, DRY domyślnie (AR-108).

PO CO: historia stosu (`PixInsight:ProcessingHistory`) zapisuje nazwy lightów z CHWILI OBRÓBKI,
a Custos po obróbce przemianował 23 637 plików (zmierzone 2026-10-11 na depozycie). Bieżąca nazwa
lokacji milczy więc wobec 33/33 stosów z historią, a dawna nazwa z zapisu przenosin trafia pełny
zbiór wejść w większości z nich. Ten skrypt przenosi dawne nazwy do bazy (`light_name_alias`, źródło
`custos`), zanim depozyt dawcy zniknie - rodowód stosów czyta potem wyłącznie bazę, nie zip.

ŁAŃCUCH, NIE PARA: plik bywał przenoszony kilka razy (stare drzewo → `R:\\ASTRO_` → poprawka nazwy),
więc od BIEŻĄCEJ ścieżki lokacji idziemy wstecz po krawędziach `moves(old_path → new_path)` ze
wszystkich manifestów depozytu, a każda napotkana dawna nazwa daje alias tej klatki. Drugi świadek
tej samej klatki: ruch, którego odcisk (`sha_pre`/`sha_post`) równa się `file_sha1` kopii,
niezależnie od ścieżki (kopie między woluminami, ścieżki zapisane inną literą dysku).

KRAWĘDŹ BEZ DOWODU WYKONANIA POTRZEBUJE DRUGIEGO ŚWIADKA. Ruch `done`/`verified` (albo z manifestu
bez kolumny stanu) wchodzi do łańcucha wprost. Ruch `planned`/`collision`/`error`/`review` mógł się
nie wykonać: jego `new_path` bywa cudzym plikiem, a krawędź przypięłaby dawną nazwę obcej klatce -
odmowa czytelnika (rdzeń dwóch klatek) chroni tylko wtedy, gdy plik spod `old_path` dalej żyje,
a nie, gdy skasowano go poza regułą A1. Taka krawędź wchodzi więc wyłącznie z drugim świadkiem:
odcisk ruchu (`sha_pre`/`sha_post`) równy `file_sha1` tej kopii albo `old_path` znany bazie (ścieżka
lokacji lub dawna ścieżka z `location.renamed`). Koszt świadomy: bliźniak `…_0000_…` stosów
16860/16862 (kolizja z duplikatem `…_0000a_…`, bez odcisku i bez lokacji w bazie) aliasu nie dostaje.

NIEJEDNOZNACZNOŚĆ LICZONA NA PEŁNYM INDEKSIE CZYTELNIKA (`stacks.names_index_pairs`: lokacje,
`location.renamed`, aliasy już w bazie) plus aliasy z tego planu - ta sama definicja co w rodowodzie
stosów, więc „0” w raporcie znaczy „żaden nowy alias nie zderza się z niczym, co czytelnik widzi”.

BAZA: SELECT-y read-only wprost (lokacje, dziennik, aliasy); ZAPIS wyłącznie klingą `repo`.

RDZEŃ NAZWY = `resolve.stack.raw_stem` - ta sama reguła, którą rodowód i żniwa czytają nazwy
wejść (SPOT). Zapis wyłącznie klingą `repo.record_light_name_aliases` (EXPECT na źródle i lightach,
idempotencja na `UNIQUE(stem, frame_id)`), więc ponowny `--apply` dopisuje zero wierszy. Rdzeń przy
dwóch klatkach skrypt zapisuje i RAPORTUJE: czytelnik traktuje go jako nazwę niejednoznaczną
i odmawia zbioru z nazw, zamiast wybierać.

ODCZYT: zip depozytu tylko do odczytu, manifesty rozpakowane do katalogu tymczasowego i otwierane
`?immutable=1`; baza w DRY przez `?mode=ro`. Wydruk ASCII (konsola Windows - cp1250/cp852).

Użycie:
  python scripts/import_aliasow_custos.py --db <horreum.db> --zip <Custos-Messium-RRRRMMDD.zip>
  python scripts/import_aliasow_custos.py --db <horreum.db> --zip <...zip> --apply
"""
import argparse
import os
import sqlite3
import sys
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

# pakiet horreum z korzenia repo (skrypt leży w scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from horreum import db, repo, stacks                              # noqa: E402
from horreum.resolve.stack import NameIndex, raw_stem, wbpp_core  # noqa: E402

ACTOR = "import:custos"
STANY_WYKONANE = ("done", "verified", None)   # None = manifest bez kolumny stanu


@dataclass(frozen=True)
class Ruch:
    """Jedna krawędź zapisu przenosin. `stan` None = manifest bez kolumny stanu."""
    old_path: str
    new_path: str
    stan: object = None
    sha_pre: object = None
    sha_post: object = None


@dataclass
class PlanAliasow:
    """Wynik planu: pary `(frame_id, stem)` + liczby do raportu."""
    ruchy: int = 0
    lighty: int = 0                  # lokacje lightów w bazie (wszystkie, z nieobecnymi)
    z_aliasem: int = 0               # klatki, którym łańcuch dał co najmniej jedną dawną nazwę
    pary: list = field(default_factory=list)
    niejednoznaczne: int = 0         # rdzenie aliasu przy >1 klatce w pełnym indeksie (odmowa)


def _norm(path):
    return os.path.normcase(os.path.normpath(str(path)))


def read_moves(zip_path):
    """Wszystkie ruchy z manifestów `*.sqlite` w zipie depozytu → lista `Ruch`. Manifest bez
    tabeli `moves` pomijany; kolumny stanu i odcisków bywają nieobecne (starsze manifesty)."""
    ruchy = []
    with zipfile.ZipFile(zip_path) as z, \
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        for name in sorted(n for n in z.namelist() if n.lower().endswith(".sqlite")):
            plik = z.extract(name, td)
            con = sqlite3.connect(f"file:{plik}?immutable=1", uri=True)
            try:
                kolumny = {r[1] for r in con.execute("PRAGMA table_info(moves)")}
                if not kolumny:
                    continue
                stan = "state" if "state" in kolumny else "NULL"
                pre = "sha_pre" if "sha_pre" in kolumny else "NULL"
                post = "sha_post" if "sha_post" in kolumny else "NULL"
                for old, new, s, a, b in con.execute(
                        f"SELECT old_path, new_path, {stan}, {pre}, {post} FROM moves"):
                    if old and new:
                        ruchy.append(Ruch(old, new, s, a, b))
            finally:
                con.close()
    return ruchy


def plan_aliases(con, ruchy):
    """Czysty plan (bez zapisu): od bieżącej ścieżki każdej lokacji lightu wstecz po łańcuchu
    ruchów → dawne rdzenie nazw tej klatki (patrz docstring modułu)."""
    plan = PlanAliasow(ruchy=len(ruchy))
    wstecz = defaultdict(list)
    po_odcisku = defaultdict(list)
    for r in ruchy:
        wstecz[_norm(r.new_path)].append(r)
        for sha in (r.sha_pre, r.sha_post):
            if sha:
                po_odcisku[sha].append(r)
    znane = {_norm(r[0]) for r in con.execute("SELECT path FROM location")}
    znane |= {_norm(r[0]) for r in con.execute(
        "SELECT json_extract(payload, '$.before') FROM event WHERE verb = 'location.renamed' "
        "AND json_extract(payload, '$.before') IS NOT NULL")}

    def wykonany(r, file_sha1):
        """Krawędź do łańcucha: ruch wykonany albo drugi świadek (docstring modułu)."""
        return (r.stan in STANY_WYKONANE
                or (file_sha1 and file_sha1 in (r.sha_pre, r.sha_post))
                or _norm(r.old_path) in znane)

    aliasy = defaultdict(set)
    bierzace = defaultdict(set)
    lokacje = con.execute(
        "SELECT l.frame_id, l.path, l.file_sha1 FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE f.kind = 'light' AND f.superseded_by IS NULL ORDER BY l.id").fetchall()
    plan.lighty = len(lokacje)
    for frame_id, path, file_sha1 in lokacje:
        bierzace[frame_id].add(raw_stem(path))
        dawne = set()
        widziane = {_norm(path)}
        kolejka = [_norm(path)]
        for r in po_odcisku.get(file_sha1, ()) if file_sha1 else ():
            dawne.add(r.old_path)                # odcisk tej kopii JEST drugim świadkiem
            if _norm(r.old_path) not in widziane:
                widziane.add(_norm(r.old_path))
                kolejka.append(_norm(r.old_path))
        while kolejka:
            for r in wstecz.get(kolejka.pop(), ()):
                if not wykonany(r, file_sha1):
                    continue
                dawne.add(r.old_path)
                n = _norm(r.old_path)
                if n not in widziane:
                    widziane.add(n)
                    kolejka.append(n)
        aliasy[frame_id] |= {raw_stem(p) for p in dawne}
    for frame_id, stemy in aliasy.items():
        stemy -= bierzace[frame_id]
        stemy.discard("")
        if stemy:
            plan.z_aliasem += 1
        plan.pary.extend((frame_id, s) for s in stemy)
    plan.pary.sort()
    # Niejednoznaczność na PEŁNYM indeksie czytelnika (docstring modułu): rdzeń aliasu albo jego
    # luźny rdzeń przy więcej niż jednej klatce.
    biezace, dawne_bazy = stacks.names_index_pairs(con)
    indeks = NameIndex.build(biezace, list(dawne_bazy) + plan.pary)
    plan.niejednoznaczne = len({s for _f, s in plan.pary
                                if len(indeks.by_stem.get(s, ())) > 1
                                or len(indeks.by_core.get(wbpp_core(s), ())) > 1})
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, help="baza Horreum (schemat >= 34)")
    ap.add_argument("--zip", required=True, help="zip depozytu Custos z manifest*.sqlite")
    ap.add_argument("--apply", action="store_true", help="zapisz aliasy (domyślnie DRY)")
    args = ap.parse_args(argv)

    ruchy = read_moves(args.zip)
    if args.apply:
        con = db.open_db(args.db)
    else:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        wersja = con.execute("PRAGMA user_version").fetchone()[0]
        if wersja < 34:
            raise SystemExit(f"baza w schemacie {wersja} < 34 - otworz ja raz Horreum (migracja), "
                             "potem DRY")
    try:
        plan = plan_aliases(con, ruchy)
        istniejace = {(r[0], r[1]) for r in con.execute(
            "SELECT frame_id, stem FROM light_name_alias")}
        nowe = [p for p in plan.pary if p not in istniejace]
        print(f"ruchy Custos: {plan.ruchy}; lokacje lightow: {plan.lighty}; klatki z dawna nazwa: "
              f"{plan.z_aliasem}")
        print(f"aliasy: {len(plan.pary)} (nowe {len(nowe)}, juz w bazie "
              f"{len(plan.pary) - len(nowe)}); rdzenie przy >1 klatce: {plan.niejednoznaczne}")
        if not args.apply:
            print("DRY - nic nie zapisano; zapis: dopisz --apply")
            return 0
        dodane = repo.record_light_name_aliases(
            con, aliases=plan.pary, source="custos",
            now=datetime.now(timezone.utc).isoformat(), actor=ACTOR)
        print(f"zapisano aliasow: {dodane}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
