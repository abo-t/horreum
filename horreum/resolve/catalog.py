"""Oś OBIEKT — loader uniwersaliów katalogowych (catalog_xref, polityka NGC-wins).

Forma przeniesiona z `custos/resolve/data/catalog_xref.json`. W plastrze B udostępniamy
sam loader (zweryfikuje też, że asset jedzie w wheelu — bramka clone'a); pełna rozwiązywanie
object_raw → object/object_alias dochodzi z modułem skanu/resolvera (kolejny krok, §4).
"""
import functools
import json
from importlib import resources


@functools.lru_cache(maxsize=1)
def load_catalog_xref():
    """Wczytaj catalog_xref.json (cache). Klucze: messier_to_ngc, caldwell_to_ngc,
    sh2_to_ic, cross_to_ngc — wszystkie alias->kanon (NGC-wins)."""
    text = (resources.files("horreum.resolve.data")
            .joinpath("catalog_xref.json").read_text(encoding="utf-8"))
    return json.loads(text)
