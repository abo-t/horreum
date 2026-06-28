"""catalog_xref — asset ładuje się przez importlib.resources (jedzie w wheelu, bramka clone'a)."""
from horreum.resolve.catalog import load_catalog_xref


def test_catalog_xref_laduje_sie():
    x = load_catalog_xref()
    assert {"messier_to_ngc", "caldwell_to_ngc", "sh2_to_ic", "cross_to_ngc"} <= set(x)


def test_ngc_wins_forma():
    """Messier/Caldwell = alias-only -> rozwiązują się do klucza NGC/IC (polityka NGC-wins)."""
    x = load_catalog_xref()
    assert x["messier_to_ngc"]["M106"] == "NGC4258"
    assert x["caldwell_to_ngc"]["C23"] == "NGC891"
    assert x["sh2_to_ic"]["Sh2-190"] == "IC1805"
