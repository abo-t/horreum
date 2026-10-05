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
    for p in sorted(GUI.glob("*.py")) + _RDZEN_Z_I18N:
        used |= _collect_t_keys(p)
    unknown = used - set(CATALOG)
    assert not unknown, f"klucze i18n spoza katalogu: {sorted(unknown)}"
    assert "grid.frames" in used, "kolektor nic nie złapał — bramka byłaby ślepa"
    for p in _RDZEN_Z_I18N:
        assert _collect_t_keys(p), f"{p.name}: kolektor nic nie złapał - bramka byłaby ślepa"


# Moduły spoza `gui/`, które mówią do UI przez katalog (FH-13: opis drzewa filtra na pasku zbioru).
_RDZEN_Z_I18N = [PKG / "filter_engine.py"]


def test_parytet_nazw_facetow_opisu_filtra_z_katalogiem():
    """Nazwy facetów w opisie drzewa filtra jadą mapą `filter_engine._FACET_KEYS` - kolektor
    literałów jej nie widzi. Każdy facet, który silnik umie wykonać, ma nazwę w katalogu (FH-13)."""
    from horreum import filter_engine

    assert set(filter_engine._FACET_KEYS) == set(filter_engine._FACET_KIND) | {"night"}
    braki = [k for k in filter_engine._FACET_KEYS.values() if k not in CATALOG]
    assert not braki, f"facet bez nazwy w katalogu: {braki}"


def test_parytet_tokenow_dynamicznych_z_katalogiem():
    """BRAMKA NA KLUCZE SKŁADANE W LOCIE. `test_klucze_call_site_podzbior_katalogu` zbiera wyłącznie
    LITERAŁY, więc `i18n.t(f"grid.lin.cal.gap.{token}")` jest dla niej niewidzialny — a literówka
    w tokenie rdzenia albo nowa wartość w bazie renderują użytkownikowi SUROWY KLUCZ.

    Pilnujemy parytetu w jedną stronę: każdy token, który rdzeń UMIE wyprodukować, ma zdanie
    w katalogu. Odwrotnie nie — katalog wolno mieć bogatszy (`bias`, źródła z migracji `0009`
    zapowiedziane, zanim je ktoś zapisze)."""
    from horreum import lineage
    from horreum.gui.i18n_catalog import CATALOG

    braki = []
    for token in lineage._GAP_PROSE:
        if f"grid.lin.cal.gap.{token}" not in CATALOG:
            braki.append(f"grid.lin.cal.gap.{token}")
    braki += [f"grid.lin.cal.gap.{t}" for t in ("not_calibrated",)
              if f"grid.lin.cal.gap.{t}" not in CATALOG]        # token składany na powierzchni
    for relation in lineage._RELATIONS:
        if f"grid.lin.cal.rel.{relation}" not in CATALOG:
            braki.append(f"grid.lin.cal.rel.{relation}")
    assert not braki, f"rdzeń produkuje tokeny bez zdania w katalogu: {braki}"


def test_parytet_stanow_kolumny_obiektu_z_katalogiem():
    """DRUGA BRAMKA NA KLUCZE SKŁADANE (R-S3-4). Tooltip kolumny „Obiekt" jedzie mapą
    `grid._OBJECT_STATE_TIPS`, więc kolektor literałów go NIE WIDZI — literówka w kluczu
    renderowałaby użytkownikowi surowe `grid.cell.object_…` pod kursorem.

    Parytet trzymamy w OBIE strony, bo tu obie znaczą defekt: klucz bez zdania w katalogu to surowy
    tekst na ekranie, a stan bez klucza to komórka, która nie umie się wytłumaczyć. Zbiór stanów
    bierzemy od WŁAŚCICIELA polityki (`queries.OBJECT_CELL_STATES`), nie z listy przepisanej tutaj.

    `canon` jest jedynym stanem BEZ tooltipa i to jest treść, nie wyjątek: nazwa mówi wtedy sama
    za siebie, a zdanie pod kursorem na każdej komórce kolumny byłoby szumem."""
    from horreum.gui.grid import _OBJECT_STATE_TIPS
    from horreum.gui.queries import OBJECT_CELL_STATES

    assert set(_OBJECT_STATE_TIPS) == set(OBJECT_CELL_STATES) - {"canon"}
    braki = [k for k in _OBJECT_STATE_TIPS.values() if k not in CATALOG]
    assert not braki, f"stany kolumny bez zdania w katalogu: {braki}"


def test_parytet_zrodel_pewnosci_obu_osi_panelu():
    """Oba źródła pewności panelu rodowodu mają komplet zdań: oś stosów (`asserted_by` wejścia)
    i oś kalibracji (`asserted_by` powiązania). Wartości bierzemy z CHECK-ów migracji, żeby bramka
    szła za schematem, a nie za listą przepisaną do testu."""
    from horreum.gui.i18n_catalog import CATALOG

    braki = [f"grid.lin.{rodzina}.{w}"
             for rodzina, wartosci in (("src", ("history", "window", "user")),
                                       ("cal.src", ("horreum", "user", "wbpp")))
             for w in wartosci if f"grid.lin.{rodzina}.{w}" not in CATALOG]
    assert not braki, f"źródło pewności bez zdania: {braki}"
