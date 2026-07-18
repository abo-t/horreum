"""Motyw GUI (F6, PLAN_ux_redesign §7) — logika Qt-WOLNA: paleta/kolory jako hex-stringi + generator
QSS akcentów. QPalette/QColor SKŁADANE w warstwie widżetów (`app.py`/`grid.py`/`facets.py`) z tych
stałych — ten plik nie importuje PySide6 (test izolacji `test_gui_isolation`, wzorzec `facet_model`).

Dwa motywy: **ciemny (default)** i jasny — oba pełnoprawne, IDENTYCZNY zbiór kluczy (żadna dziura per
motyw; pinowane testem). Kolory stanów gridu (`grid_colors`) i wykluczeń facetów (`facet_colors`) mają
warianty per motyw — pale-tła jasnego byłyby nieczytelne na ciemnej bazie. Granica QSettings łagodna
(`normalize`), silnik fail-fast (`palette_spec`/`grid_colors` podnoszą ValueError na nieznanym motywie)."""
from __future__ import annotations

DEFAULT = "dark"

# QPalette: rola → hex. Klucze = nasze nazwy ról (mapowane na QPalette.ColorRole w `app.py`).
_PALETTE = {
    "dark": {
        "window": "#2B2B2B", "window_text": "#E6E6E6",
        "base": "#1E1E1E", "alt_base": "#262626", "text": "#E6E6E6",
        "button": "#3A3A3A", "button_text": "#E6E6E6", "bright_text": "#FF5555",
        "highlight": "#4A78C8", "highlight_text": "#FFFFFF",
        "tooltip_base": "#3A3A3A", "tooltip_text": "#E6E6E6",
        "link": "#5AA0FF", "placeholder": "#8A8A8A", "disabled_text": "#6E6E6E",
    },
    "light": {
        "window": "#F0F0F0", "window_text": "#1E1E1E",
        "base": "#FFFFFF", "alt_base": "#F6F6F6", "text": "#1E1E1E",
        "button": "#E9E9E9", "button_text": "#1E1E1E", "bright_text": "#B00000",
        "highlight": "#3D7EFF", "highlight_text": "#FFFFFF",
        "tooltip_base": "#FFFFDC", "tooltip_text": "#1E1E1E",
        "link": "#0B61C4", "placeholder": "#9A9A9A", "disabled_text": "#A6A6A6",
    },
}

# Kolory stanów gridu (tła wierszy/nagłówka + szarość braku). Jasny = obecne pale wartości
# (`grid.py` sprzed F6); ciemny = warianty czytelne na bazie #1E1E1E.
_GRID = {
    "dark": {
        # group_bg #3C3C3C: własny akcent belki grupy nad bazą #1E1E1E i odróżnialny od skipped_bg
        # #2C2C2C (wizytator F6 oś B — neutrale zbyt blisko; belka niesie też bold+▸).
        "missing": "#8A8A8A", "vanished_bg": "#4A2A2A", "dup_bg": "#22344A",
        "group_bg": "#3C3C3C", "touched_bg": "#274427", "skipped_bg": "#2C2C2C",
    },
    "light": {
        "missing": "#999999", "vanished_bg": "#FFE5E5", "dup_bg": "#E5F0FF",
        "group_bg": "#E4E4E4", "touched_bg": "#E3F6E3", "skipped_bg": "#F2F2F2",
    },
}

# Czerwień wykluczeń facetów (foreground ⊖). Ciemny = jaśniejsza czerwień, czytelna na dark.
_FACET = {
    "dark": {"exclusion": "#FF6E6E"},
    "light": {"exclusion": "#B00000"},
}

# Akcenty do QSS (złoto spichlerza, zieleń poczekalni-OK, czerwień wykluczeń) i tekst drugorzędny
# (etykiety kryteriów/celu/wyniku — na dark hardcoded #666 byłby nieczytelny, F6 recenzja #3).
_ACCENT = {
    "dark": {"gold": "#E0A030", "ok_green": "#5FB65F", "exclusion_red": "#FF6E6E",
             "secondary_text": "#A8A8A8"},
    "light": {"gold": "#D08000", "ok_green": "#2E7D32", "exclusion_red": "#B00000",
              "secondary_text": "#666666"},
}

# Kolory mapy stanowisk (F8 §9 — QPainter scatter na tle konturów NE). `land` = przygaszony kontur
# (TŁO, nie punkt); `site`/`site_selected` = złoto spichlerza + jaśniejsze wyróżnienie zaznaczenia;
# `scale` = tekst drugorzędny (pasek skali + etykiety stanowisk). Warianty per motyw — kontur na
# jasnym tle musi być ciemniejszy niż na ciemnym. IDENTYCZNY zbiór kluczy (pin test_theme).
_MAP = {
    "dark": {"bg": "#1E1E1E", "land": "#505050", "site": "#E0A030",
             "site_selected": "#FF8C1A", "sel_ring": "#7AB0FF", "scale": "#9A9A9A"},
    "light": {"bg": "#FFFFFF", "land": "#BEBEBE", "site": "#D08000",
              "site_selected": "#E85D00", "sel_ring": "#1E5FCC", "scale": "#808080"},
}


def normalize(name):
    """Nazwa motywu z QSettings → znany motyw (nieznana/None → DEFAULT). Granica łagodna."""
    return name if name in _PALETTE else DEFAULT


def _spec(table, name):
    if name not in table:
        raise ValueError(f"nieznany motyw: {name!r} (znane: {sorted(_PALETTE)})")
    return dict(table[name])


def palette_spec(name):
    """Rola QPalette → hex dla motywu `name`. ValueError na nieznanym (EXPECT — caller normalizuje)."""
    return _spec(_PALETTE, name)


def grid_colors(name):
    """Kolory stanów gridu → hex. Klucze: missing/vanished_bg/dup_bg/group_bg/touched_bg/skipped_bg."""
    return _spec(_GRID, name)


def facet_colors(name):
    """Kolory facetów → hex. Klucz: exclusion (foreground ⊖)."""
    return _spec(_FACET, name)


def accents(name):
    """Akcenty → hex. Klucze: gold/ok_green/exclusion_red/secondary_text."""
    return _spec(_ACCENT, name)


def map_colors(name):
    """Kolory mapy stanowisk → hex. Klucze: bg/land/site/site_selected/sel_ring/scale (F8)."""
    return _spec(_MAP, name)


def qss(name):
    """Arkusz stylów akcentów dla motywu. Tekst drugorzędny przez własność `role="secondary"`
    (etykiety, które w widżetach ustawiają `setProperty("role","secondary")` zamiast inline color)."""
    a = accents(name)
    return f'QLabel[role="secondary"] {{ color: {a["secondary_text"]}; }}'
