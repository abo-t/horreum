"""Agregat portfela naświetleń (F7, PLAN_ux_redesign §8) — Qt-WOLNY (wzorzec `queries`/`facet_model`;
egzekwuje rglob `test_gui_isolation` + jawna asercja). JEDYNY właściciel formatowania godzin (SPOT):
`grid.py`/`facets.py` nie liczą ani nie formatują — wołają tu.

Wejście = płaskie wiersze `queries.object_exposure` (object_id, filter_canon, secs, n_null; dict lub
sqlite3.Row — dostęp po kluczu). Wyjście = per obiekt dict + gotowe stringi sufiksu/tooltipa listwy.
JAWNE-NULL: `secs=NULL` (grupa cała bez exptime) liczony jak 0 sekund; `n_null` wyświetlane
„(+n bez exptime)"; `filter_canon=None` → etykieta „(bez filtra)". `exptime=0` = wartość (0 s), NIE n_null.
"""

from __future__ import annotations

from horreum.gui import i18n

_NO_FILTER = "portfolio.no_filter"   # KLUCZ i18n — rozwiązywany w USE-site (nie zamrażać PL przy imporcie)


def summarize(rows) -> dict:
    """Płaskie wiersze (obiekt, filtr) → per obiekt:
    `{obj_id: {"total_secs": float, "n_null": int, "per_filter": [(filter_canon|None, secs, n_null)…]}}`.
    `per_filter` zachowuje kolejność z SQL (secs DESC). `secs=NULL` → 0 s (grupa cała bez exptime)."""
    out: dict = {}
    for r in rows:
        oid = r["object_id"]
        entry = out.get(oid)
        if entry is None:
            entry = out[oid] = {"total_secs": 0.0, "n_null": 0, "per_filter": []}
        secs = r["secs"] or 0.0
        n_null = r["n_null"] or 0
        entry["total_secs"] += secs
        entry["n_null"] += n_null
        entry["per_filter"].append((r["filter_canon"], secs, n_null))
    return out


def format_hours(secs) -> str:
    """Sekundy → godziny z jednym miejscem po przecinku: `3600 → "1.0 h"`, `None/0 → "0.0 h"`."""
    return f"{(secs or 0) / 3600:.1f} h"


def object_suffix(entry) -> str:
    """Sufiks wiersza obiektu: `" · 12.3 h"` + (gdy są lighty bez exptime) `" (+5 bez exptime)"`."""
    s = f" · {format_hours(entry['total_secs'])}"
    if entry["n_null"]:
        s += i18n.t("portfolio.plus_no_exptime", n=entry["n_null"])
    return s


def object_tooltip(entry) -> str:
    """Rozbicie per filtr (to jest „per obiekt × filtr") jako mini-tabela, wiersz per filtr:
    `"Ha: 8.1 h\\nOIII: 4.2 h\\n(bez filtra): 1.0 h\\n+5 klatek bez exptime"`. Nowe linie zamiast
    „·" — skanowalne i odporne na liczbę filtrów (obiekt z >10 filtrami nie rodzi ściany, wiz F7 #F3).
    Filtr `None` → „(bez filtra)"; ogon `n_null` (gdy >0) na końcu."""
    parts = [f"{f or i18n.t(_NO_FILTER)}: {format_hours(secs)}" for f, secs, _n in entry["per_filter"]]
    if entry["n_null"]:
        parts.append(i18n.t("portfolio.frames_no_exptime", n=entry["n_null"]))
    return "\n".join(parts)
