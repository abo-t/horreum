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


# ── AR-63: jeden właściciel formy aliasu (`assign_dialog.forma_aliasu`) ────────────────────────────
@pytest.mark.parametrize("klucz, forma", [
    ("BODESGALAXY", "Bode's Galaxy"),               # deskryptor na końcu klucza
    ("THEPELICANNEBULA", "Pelican Nebula"),         # „the” na początku
    ("ELEPHANTSTRUNK", "Elephant's Trunk Nebula"),  # sam token
    ("KSIEZYC", "Księżyc"),                         # ciało z ogonkami
    ("JOWISZ", "Jowisz"),                           # ciało bez wyjątku
    ("LEMMON", "Lemmon"),                           # token komety - słowo z kanonu komety
    ("TSUCHINSHAN", "Tsuchinshan"),
    ("SH2184", "Sh2-184"),                          # gramatyka katalogowa przed resztą
    ("COLLINDER464", "Cr464"),
    ("MUR", "MUR"),                                 # alias ręki bez zeznania - zostaje kluczem
    ("HEARTOFTHESOULNEBULA", "HEARTOFTHESOULNEBULA"),   # `_COMMON` jej nie zna - nie zmyślamy
])
def test_forma_aliasu_z_wiedzy_w_kodzie(klucz, forma):
    from horreum.gui.assign_dialog import forma_aliasu
    assert forma_aliasu(klucz) == forma


def test_brzmienie_z_pretty_wygrywa_z_wiedza_w_kodzie_ale_nie_z_gramatyka():
    """Karta `OBJECT`/słownik (`pretty`) mówi, jak user podpisał klatki - ma pierwszeństwo przed
    brzmieniem z `_COMMON`; oznaczenie katalogowe zostaje formą gramatyki (jak okno od AR-15)."""
    from horreum.gui.assign_dialog import forma_aliasu
    assert forma_aliasu("BODESGALAXY", {"BODESGALAXY": "Bodes galaxy"}) == "Bodes galaxy"
    assert forma_aliasu("SH2184", {"SH2184": "SH2 184"}) == "Sh2-184"


def test_listwa_i_okno_mowia_ta_sama_forma(tmp_path):
    """Szew AR-63: mapa listwy (`formy_aliasow`) i lista okna (`aliasy_obiektu`) dają tę samą formę
    każdego aliasu. Falsyfikator: `formy_aliasow` bez przejścia przez `forma_aliasu` - listwa
    wraca do `ELEPHANTSTRUNKNEBULA`/`SH2184`, okno mówi brzmieniem."""
    from horreum import db
    from horreum.gui.assign_dialog import aliasy_obiektu, formy_aliasow
    con = db.open_db(str(tmp_path / "h.db"))
    aliasy = {"Sh2-131": [("ELEPHANTSTRUNKNEBULA", "common_name")],
              "Moon": [("KSIEZYC", "solar")],
              "NGC281": [("SH2184", "catalog_xref")],
              "NGC7000": [("MUR", "user")]}
    for canon, wpisy in aliasy.items():
        oid = con.execute("INSERT INTO object(canon, kind) VALUES (?, 'deep_sky')", (canon,)).lastrowid
        con.executemany("INSERT INTO object_alias(alias_norm, object_id, source) VALUES (?, ?, ?)",
                        [(k, oid, s) for k, s in wpisy])
    con.commit()
    mapa = formy_aliasow(con)
    for canon, wpisy in aliasy.items():
        klucze = {k for k, _s in wpisy}
        assert set(aliasy_obiektu(canon, klucze, mapa)) == {mapa[k] for k in klucze}
    assert mapa["ELEPHANTSTRUNKNEBULA"] == "Elephant's Trunk Nebula"
    assert mapa["SH2184"] == "Sh2-184"
    con.close()
