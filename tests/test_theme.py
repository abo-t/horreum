"""F6 motyw (PLAN_ux_redesign §7) — logika Qt-WOLNA: paleta/kolory jako hex, generator QSS.
Bez `importorskip("PySide6")` — chodzi w izolowanym clone bez `[gui]` (jak `test_gui_isolation`);
dowodzi, że motyw da się przetestować bez Qt (QColor SKŁADANY dopiero w warstwie widżetów)."""
import ast
import pathlib
import re

import pytest

from horreum.gui import theme

_THEMES = ("dark", "light")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX_IN = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")   # kolor GDZIEKOLWIEK w stringu
_SPECS = (theme.palette_spec, theme.grid_colors, theme.facet_colors, theme.accents, theme.map_colors)


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


def test_map_klucze_kanoniczne():
    # `map_view.use_theme` (F8) czyta te klucze; brak któregoś = KeyError w malowaniu mapy.
    assert set(theme.map_colors("dark")) == {
        "bg", "land", "site", "site_selected", "sel_ring", "scale"}


@pytest.mark.parametrize("fn", _SPECS)
def test_nieznany_motyw_valueerror(fn):
    with pytest.raises(ValueError):
        fn("neon")


def test_qss_niesie_secondary_text():
    q = theme.qss("dark")
    assert "secondary" in q
    assert theme.accents("dark")["secondary_text"] in q


@pytest.mark.parametrize("name", _THEMES)
def test_qss_niesie_wszystkie_role(name):
    """P-C: każda rola z `ROLES` ma selektor i kolor w arkuszu — inaczej widżet z `role="error"`
    dostałby zwykły kolor tekstu i porażka etapu wyglądałaby jak zwykły wiersz."""
    q = theme.qss(name)
    a = theme.accents(name)
    for role, key in theme.ROLES.items():
        assert f'QLabel[role="{role}"]' in q, role
        assert a[key] in q, role


def test_theme_jest_jedynym_wlascicielem_kolorow():
    """BRAMKA KLASY (P-C): żaden moduł poza `theme` nie ma prawa nieść koloru w kodzie.

    Cztery sztywne kolory przeżyły F6 i rozjechały się z motywem: `#b00020` w `pipeline`/`app`
    (na ciemnej bazie 1,6:1 — porażka etapu była nieczytelna dokładnie w motywie domyślnym),
    `#b00` w panelu daty, `#d08000`/`#999` na kropce poczekalni (złoto JASNEGO motywu wypalone
    na stałe). Znalezisko jednostkowe podniesione do kontroli, żeby nie wracało.

    AST, nie grep: liczy się STRING W KODZIE, a nie wzmianka w komentarzu czy docstringu —
    komentarz „nie sztywne #b00" opisuje regułę i sam jej nie łamie.

    DWIE DROGI, nie jedna (wizytacja P-C #5): pierwsza wersja bramki liczyła wyłącznie stringi
    i przepuściła `tasks.py: QColor(0x88, 0x88, 0x88)` — jedyny żywy sztywny kolor, jaki wtedy
    został (3,54:1 w motywie jasnym). Bramka obiecująca klasę i puszczająca jej jedyny przypadek
    daje fałszywe poczucie domknięcia, więc liczy się TEŻ `QColor(...)`/`QBrush(...)` na samych
    literałach — składane z `theme.accents(...)` przechodzi, bo argument nie jest literałem."""
    root = pathlib.Path(theme.__file__).resolve().parent.parent      # horreum/
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "theme.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {ast.get_docstring(n, clean=False) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                        ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value not in docstrings and _HEX_IN.search(node.value)):
                offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("QColor", "QBrush") and node.args
                    and all(isinstance(a, ast.Constant) for a in node.args)):
                offenders.append(f"{path.name}:{node.lineno} {node.func.id}(literały)")
    assert not offenders, "kolor poza `theme.py`: " + "; ".join(offenders)


def test_warn_jest_osobny_od_gold():
    """Bursztyn ZNACZENIA (`warn`) nie jest złotem MARKI (`gold`) — złoto w jasnym motywie ma 2,7:1
    i jako tekst nie dochodzi do progu AA (wiz T5 N5). Zlanie tych dwóch kluczy wróciłoby po ten
    sam błąd, tylko z drugiej strony."""
    for name in _THEMES:
        assert theme.accents(name)["warn"] != theme.accents(name)["gold"], name


def test_motyw_faktycznie_rozni_kolory():
    """Skórki nie są identyczne — vanished_bg (pale na jasnym vs ciemny bordo) się różni."""
    assert theme.grid_colors("dark")["vanished_bg"] != theme.grid_colors("light")["vanished_bg"]
    assert theme.palette_spec("dark")["base"] != theme.palette_spec("light")["base"]
