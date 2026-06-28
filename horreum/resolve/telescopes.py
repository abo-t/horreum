"""Oś TELESKOP — normalizacja FOCRATIO + klastrowanie sygnatur (PLAN §3.3/§3.4/§Etap 5).

To JEDYNA cecha, której nie widać w pojedynczym pliku: sygnatura grupy mieszka w rozkładzie
całości. Stąd dwie czyste funkcje (bez zapisu): `normalize_focratio` (na floatach, po rzutowaniu
W3) i `cluster_signatures` (single-linkage). Sam zapis (propose_telescope/config) = `repo`, a
orkiestracja (SELECT distinct → klaster → propose → link) = `horreum.grouper`.
"""


def normalize_focratio(focratio_raw, focallen):
    """FOCRATIO → (f_ratio_norm, src). Na FLOATACH (po `_to_float`). src ∈ {ok|recovered|review}.

    - brak FOCRATIO (np. master XISF) → `(None, 'review')` — jawnie, nie crash (W4);
    - `2 ≤ f ≤ 16` → `(f, 'ok')` (realny stosunek ogniskowej);
    - `f > 16` i jest focallen → `(focallen / f, 'recovered')` — FOCRATIO bywa APERTURĄ (mm),
      odzyskujemy stosunek z ogniskowej (firsthand: >16 = apertura {120/150/200});
    - inaczej (f < 2, lub f > 16 bez focallen) → `(None, 'review')` — nie zgadujemy.
    """
    if focratio_raw is None:
        return None, "review"
    f = focratio_raw
    if 2 <= f <= 16:
        return f, "ok"
    if f > 16 and focallen:
        return focallen / f, "recovered"
    return None, "review"


def cluster_signatures(signatures, *, f_tol=0.3, focal_tol=15):
    """Sklej sygnatury teleskopów (single-linkage). `signatures` = lista `(f_ratio, focal)` (floaty,
    f_ratio != None). Dwie sygnatury w jednym klastrze, gdy `|Δf/| ≤ f_tol` ORAZ `|Δfocal| ≤ focal_tol`
    (przechodnio). f/ PIERWSZORZĘDNY: różne f/ → różne teleskopy mimo nakładających się ogniskowych
    (A140R f/5.6 ↮ ED120 f/6.4); ogniskowa rozdziela tylko w obrębie tego samego f/ (bo przy
    `|Δf/| > f_tol` linku i tak nie ma). §3.4/F9.

    Zwraca listę klastrów: `{f_ratio_nominal, focal_nominal (centroidy), members, suspect}`.
    `suspect=True` gdy rozpiętość wewnętrzna > tolerancja (chaining single-linkage) → log/review.
    """
    n = len(signatures)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]          # ścieżkowa kompresja
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        fi, foi = signatures[i]
        for j in range(i + 1, n):
            fj, foj = signatures[j]
            if abs(fi - fj) <= f_tol and abs(foi - foj) <= focal_tol:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(signatures[i])

    clusters = []
    for members in groups.values():
        fs = [m[0] for m in members]
        focals = [m[1] for m in members]
        clusters.append({
            "f_ratio_nominal": round(sum(fs) / len(fs), 2),     # centroid f/
            "focal_nominal": round(sum(focals) / len(focals)),  # centroid ogniskowej (INTEGER)
            "members": members,
            "suspect": (max(fs) - min(fs) > f_tol) or (max(focals) - min(focals) > focal_tol),
        })
    return clusters
