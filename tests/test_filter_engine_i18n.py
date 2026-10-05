"""FH-13: opis drzewa filtra (`filter_engine.describe`) mówi językiem UI - pasek zbioru w EN nie może
pokazywać „poza (Rodzaj: light)" ani „wszystkie klatki". Qt-wolne (bez `importorskip`); reset `_LANG`
daje autouse-fixture z `conftest`."""
from horreum import filter_engine
from horreum.gui import i18n

_DRZEWO = {"op": "AND", "conditions": [
    {"op": "NOT", "conditions": [{"facet": "kind", "value": "light", "label": "light"}]},
    {"keyword": "EXPTIME", "operator": "ge", "value": 300},
    {"op": "OR", "conditions": [
        {"keyword": "FILTER", "operator": "contains", "value": "Ha"},
        {"keyword": "OBJECT", "operator": "startswith", "value": "NGC"},
        {"keyword": "GAIN", "operator": "exists"},
        {"keyword": "OFFSET", "operator": "not_exists"},
    ]},
]}


def test_opis_po_polsku():
    i18n.set_lang("pl")
    assert filter_engine.describe(_DRZEWO) == (
        "poza (Rodzaj: light) i EXPTIME ≥ 300 i (FILTER zawiera Ha lub OBJECT zaczyna się od NGC"
        " lub ma GAIN lub bez OFFSET)")
    assert filter_engine.describe(None) == "wszystkie klatki"
    assert filter_engine.describe({"op": "OR", "conditions": []}) == "wszystkie klatki"


def test_opis_po_angielsku_bez_polskich_slow():
    i18n.set_lang("en")
    assert filter_engine.describe(_DRZEWO) == (
        "excluding (Kind: light) and EXPTIME ≥ 300 and (FILTER contains Ha or OBJECT starts with NGC"
        " or has GAIN or without OFFSET)")
    assert filter_engine.describe(None) == "all frames"
    assert filter_engine.describe({"op": "AND", "conditions": []}) == "all frames"


def test_nazwy_wszystkich_facetow_w_obu_jezykach():
    oczekiwane = {"pl": ["Obiekt", "Filtr", "Kanał", "Rodzaj", "Teleskop", "Noc"],
                  "en": ["Object", "Filter", "Channel", "Kind", "Telescope", "Night"]}
    facety = ["object", "filter", "channel", "kind", "telescope", "night"]
    for lang, nazwy in oczekiwane.items():
        i18n.set_lang(lang)
        got = [filter_engine.describe({"facet": f, "value": "x"}) for f in facety]
        assert got == [f"{n}: x" for n in nazwy], lang


def test_nieznany_facet_i_operator_renderuja_sie_surowo_w_en():
    """Formater etykiety nie podnosi (fail-fast dotyczy `_eval`): nieznane renderują się surowo."""
    i18n.set_lang("en")
    assert filter_engine.describe({"facet": "planet", "value": "x"}) == "planet: x"
    assert filter_engine.describe({"keyword": "A", "operator": "regex", "value": "x"}) == "A regex x"
