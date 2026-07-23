"""i18n (#1) — słownik lekki `t`/`t_plural`, kompletność katalogu i BRAMKA klucz-call-site ⊆ katalog.
Wszystko Qt-wolne (bez `importorskip`): dowodzi, że warstwa tłumaczeń chodzi bez PySide6. Reset `_LANG`
przed każdym testem daje autouse-fixture z `conftest` (R-i18n #4)."""
import ast
from pathlib import Path

import horreum
from horreum.gui import i18n
from horreum.gui.i18n_catalog import CATALOG

PKG = Path(horreum.__file__).parent
GUI = PKG / "gui"
_PL_FORMS = {"one", "few", "many"}
_EN_FORMS = {"one", "other"}


# ---- set_lang / t -------------------------------------------------------------------------------

def test_set_lang_nieznany_pada_na_default():
    i18n.set_lang("de")                       # brak w available_langs → PL
    assert i18n.current_lang() == "pl"
    i18n.set_lang("en")
    assert i18n.current_lang() == "en"


def test_t_pl_i_en():
    i18n.set_lang("pl")
    assert i18n.t("lang.restart_note").startswith("Zmieniono język")
    i18n.set_lang("en")
    assert i18n.t("lang.restart_note").startswith("Language changed")


def test_t_brak_klucza_zwraca_klucz_bez_wyjatku():
    assert i18n.t("nie.ma.takiego.klucza") == "nie.ma.takiego.klucza"


def test_t_interpolacja_nazwana(monkeypatch):
    monkeypatch.setitem(CATALOG, "_test.hello", {"pl": "Cześć {name}", "en": "Hi {name}"})
    i18n.set_lang("pl")
    assert i18n.t("_test.hello", name="Zdziniu") == "Cześć Zdziniu"


# ---- t_plural -----------------------------------------------------------------------------------

def test_t_plural_pl_formy():
    i18n.set_lang("pl")
    assert i18n.t_plural("grid.frames", 1) == "1 klatka"     # one
    assert i18n.t_plural("grid.frames", 3) == "3 klatki"     # few
    assert i18n.t_plural("grid.frames", 5) == "5 klatek"     # many
    assert i18n.t_plural("grid.frames", 13) == "13 klatek"   # 12–14 → many mimo końcówki
    assert i18n.t_plural("grid.frames", 22) == "22 klatki"   # końcówka 2 → few


def test_t_plural_en_formy():
    i18n.set_lang("en")
    assert i18n.t_plural("grid.frames", 1) == "1 frame"      # one
    assert i18n.t_plural("grid.frames", 3) == "3 frames"     # other


def test_t_plural_fraza_pelna():
    """FRAZA, nie słowo: forma niesie całe zdanie z `{n}` (PL odmienia przymiotnik/czasownik)."""
    i18n.set_lang("pl")
    assert i18n.t_plural("pipeline.vanished_still_present", 1) == \
        "Zniknęła 1 kopia — baza wciąż twierdzi, że jest."
    assert i18n.t_plural("pipeline.vanished_still_present", 2).startswith("Zniknęły 2 kopie")


def test_t_plural_brak_klucza_zwraca_klucz():
    assert i18n.t_plural("nie.ma.klucza", 3) == "nie.ma.klucza"


# ---- kompletność katalogu -----------------------------------------------------------------------

def test_katalog_kompletny_pl_i_en():
    """Każdy klucz ma PL i EN; wpis mnogi ma komplet form per język (PL one/few/many, EN one/other);
    wpis prosty jest str po obu stronach (brak = renderowałby klucz na ekranie)."""
    for key, forms in CATALOG.items():
        assert set(forms) >= {"pl", "en"}, f"{key}: brak języka pl/en"
        plural = isinstance(forms["pl"], dict)
        for lang, req in (("pl", _PL_FORMS), ("en", _EN_FORMS)):
            val = forms[lang]
            if plural:
                assert isinstance(val, dict) and set(val) >= req, f"{key}/{lang}: brak form {req}"
            else:
                assert isinstance(val, str), f"{key}/{lang}: prosty wpis musi być str"


# ---- BRAMKA: klucze call-site ⊆ katalog ---------------------------------------------------------

def _collect_t_keys(path):
    """Literalne klucze z wywołań `i18n.t(...)`/`i18n.t_plural(...)` (oraz gołych `t(`/`t_plural(`)
    w jednym pliku. Klucz dynamiczny (zmienna zamiast literału) NIE jest zbierany — to świadomy
    wyjątek pokryty testami wprost."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "i18n":
            name = f.attr
        elif isinstance(f, ast.Name):
            name = f.id
        else:
            continue
        if name not in ("t", "t_plural"):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            keys.add(first.value)
    return keys


def test_klucze_call_site_podzbior_katalogu():
    """Literówka `t('grid.col.paht')` przechodzi kompletność, a renderuje SUROWY klucz na ekranie —
    „klucz + log" to fallback, NIE bramka. Ta bramka pilnuje, by każdy LITERALNY klucz w `gui/`
    istniał w katalogu. Klucze dynamiczne (`proj.create_copies`/`create_links`) pominięte (zmienna)
    — pokryte testami projekcji wprost."""
    used = set()
    for p in sorted(GUI.glob("*.py")):
        used |= _collect_t_keys(p)
    unknown = used - set(CATALOG)
    assert not unknown, f"klucze i18n spoza katalogu: {sorted(unknown)}"
    assert "grid.frames" in used, "kolektor nic nie złapał — bramka byłaby ślepa"
