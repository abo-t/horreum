"""F6 motyw (PLAN_ux_redesign §7) — logika Qt-WOLNA: paleta/kolory jako hex, generator QSS.
Bez `importorskip("PySide6")` — chodzi w izolowanym clone bez `[gui]` (jak `test_gui_isolation`);
dowodzi, że motyw da się przetestować bez Qt (QColor SKŁADANY dopiero w warstwie widżetów)."""
import re

import pytest

from horreum.gui import theme

_THEMES = ("dark", "light")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SPECS = (theme.palette_spec, theme.grid_colors, theme.facet_colors, theme.accents)


def test_default_ciemny():
    assert theme.DEFAULT == "dark"


def test_normalize():
    assert theme.normalize("dark") == "dark"
    assert theme.normalize("light") == "light"
    assert theme.normalize("neon") == theme.DEFAULT       # nieznana → default
    assert theme.normalize(None) == theme.DEFAULT         # brak w QSettings → default


@pytest.mark.parametrize("name", _THEMES)
@pytest.mark.parametrize("fn", _SPECS)
def test_spec_niepusty_same_hexy(fn, name):
    spec = fn(name)
    assert spec
    for k, v in spec.items():
        assert _HEX.match(v), f"{fn.__name__}[{name}][{k}] = {v!r} nie jest #RRGGBB"


@pytest.mark.parametrize("fn", _SPECS)
def test_klucze_identyczne_miedzy_motywami(fn):
    """Żadna dziura per motyw — dark i light mają ten sam zbiór kluczy (inaczej apply padłby KeyError)."""
    assert set(fn("dark")) == set(fn("light")), fn.__name__


def test_grid_klucze_kanoniczne():
    assert set(theme.grid_colors("dark")) == {
        "missing", "vanished_bg", "dup_bg", "group_bg", "touched_bg", "skipped_bg"}


def test_palette_klucze_kanoniczne():
    # `_build_palette` (app.py) czyta te klucze + disabled_text; brak któregoś = KeyError w apply.
    assert set(theme.palette_spec("dark")) == {
        "window", "window_text", "base", "alt_base", "text", "button", "button_text",
        "bright_text", "highlight", "highlight_text", "tooltip_base", "tooltip_text",
        "link", "placeholder", "disabled_text"}


def test_facet_ma_exclusion():
    assert "exclusion" in theme.facet_colors("dark")


@pytest.mark.parametrize("fn", _SPECS)
def test_nieznany_motyw_valueerror(fn):
    with pytest.raises(ValueError):
        fn("neon")


def test_qss_niesie_secondary_text():
    q = theme.qss("dark")
    assert "secondary" in q
    assert theme.accents("dark")["secondary_text"] in q


def test_motyw_faktycznie_rozni_kolory():
    """Skórki nie są identyczne — vanished_bg (pale na jasnym vs ciemny bordo) się różni."""
    assert theme.grid_colors("dark")["vanished_bg"] != theme.grid_colors("light")["vanished_bg"]
    assert theme.palette_spec("dark")["base"] != theme.palette_spec("light")["base"]
