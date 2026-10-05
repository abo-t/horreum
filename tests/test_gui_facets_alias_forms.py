"""AR-45: podpowiedź trafienia aliasem w szukajce facetu „Obiekt” mówi BRZMIENIEM (mapa
`alias_norm → brzmienie`, ta sama, którą okno „Przypisz obiekt” pokazuje aliasy), a nie kluczem
`alias_norm`. Dopasowanie dalej idzie po kluczu. Falsyfikator: wróć do `alias=hit` w
`FacetRail._filter_objects` - tooltip pokaże `LARGEMAGELLANICCLOUD`."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum.gui import i18n

_ALIASY = {"LMC": {"LARGEMAGELLANICCLOUD", "NUBECULAMAJOR"}}
_FORMY = {"LARGEMAGELLANICCLOUD": "Large Magellanic Cloud"}


@pytest.fixture
def qapp():
    yield QApplication.instance() or QApplication([])


def _rail(qapp, **kw):
    from horreum.gui.facets import FacetRail
    rail = FacetRail()
    rail.resize(260, 500)
    rail.show()
    counts = {"object": [(1, "LMC", 3), (2, "NGC7000", 5)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    rail.set_data(counts, {}, aliases=_ALIASY, **kw)
    qapp.processEvents()
    return rail, counts


def _tip_po_wpisaniu(qapp, rail, fraza):
    rail.search.setText(fraza)
    qapp.processEvents()
    return rail._lists["object"].item(0).toolTip()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_trafienie_aliasem_mowi_brzmieniem_w_obu_jezykach(qapp, lang):
    i18n.set_lang(lang)
    rail, _ = _rail(qapp, alias_forms=_FORMY)
    tip = _tip_po_wpisaniu(qapp, rail, "large magellanic")
    assert tip == i18n.t("facets.tip.alias_hit", alias="Large Magellanic Cloud")
    assert "LARGEMAGELLANICCLOUD" not in tip
    rail.hide()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_klucz_bez_brzmienia_zostaje_kluczem(qapp, lang):
    """`NUBECULAMAJOR` nie ma brzmienia w żadnym źródle - pokazujemy klucz, nie zmyślamy nazwy."""
    i18n.set_lang(lang)
    rail, _ = _rail(qapp, alias_forms=_FORMY)
    assert _tip_po_wpisaniu(qapp, rail, "nubecula") == i18n.t("facets.tip.alias_hit",
                                                              alias="NUBECULAMAJOR")
    rail.hide()


def test_mapa_brzmien_przezywa_przeladowanie_bez_niej(qapp):
    """`alias_forms=None` znaczy „bez zmian” (jak `aliases`): refresh w środku pisania nie może
    cofnąć podpowiedzi do klucza."""
    rail, counts = _rail(qapp, alias_forms=_FORMY)
    rail.search.setText("large magellanic")
    rail.set_data(counts, {})
    qapp.processEvents()
    assert "Large Magellanic Cloud" in rail._lists["object"].item(0).toolTip()
    rail.hide()
