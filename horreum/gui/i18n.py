"""i18n GUI (#1) — LEKKI SŁOWNIK, Qt-WOLNY. Warstwa widoku (`horreum/gui/`) woła `t`/`t_plural`;
rdzeń i read-model milczą UI-tekstem (zwiad briefu). Ten plik NIE importuje PySide6 (test izolacji
`test_gui_isolation`, wzorzec `theme.py`): stan języka to MODUŁOWY `_LANG`, ustawiany przez WIDOK
(`app.main`) z `QSettings ui/lang` PRZED budową okna — i18n QSettings nie czyta (to Qt).

Katalog = DANE (`i18n_catalog.py`, SPOT). Wpis prosty (dla `t`) = `{"pl": str, "en": str}`; wpis liczby
mnogiej (dla `t_plural`) = `{"pl": {"one","few","many"}, "en": {"one","other"}}`. Brakujący klucz/język →
fallback: zwróć KLUCZ + log dev (raz na klucz), NIGDY pusty ekran. Interpolacja przez `str.format`
(pola `{n}`/`{name}`) — pokrywa f-stringi statusów i raportów.

D-L1 = RESTART po zmianie (v1): `_LANG` nie mutuje w trakcie sesji, więc raport liczony off-thread
(`pipeline`) jest spójny językowo (R-i18n #6). Przełącznik zapisuje `ui/lang` i stosuje się przy starcie."""
from __future__ import annotations

import logging

from horreum.gui.i18n_catalog import CATALOG

_LOG = logging.getLogger(__name__)

DEFAULT = "pl"
# (kod, endonim) — endonimu NIE tłumaczymy ("Polski" zostaje "Polski" w EN UI). Kolejność = menu.
_LANGS = [("pl", "Polski"), ("en", "English")]
_LANG = DEFAULT
_missing = set()   # klucze już zalogowane jako brak — log raz, nie zalewaj konsoli


def normalize(lang):
    """Kod języka z QSettings/locale → znany kod (nieznany/None → DEFAULT). Granica łagodna
    (wzorzec `theme.normalize`)."""
    return lang if any(code == lang for code, _ in _LANGS) else DEFAULT


def set_lang(lang):
    """Ustaw język procesu (widok woła z `QSettings ui/lang` przed budową okna). Nieznany → DEFAULT."""
    global _LANG
    _LANG = normalize(lang)


def current_lang():
    return _LANG


def available_langs():
    """[(kod, endonim)] dla menu wyboru — kopia, by wołający nie mutował stanu modułu."""
    return list(_LANGS)


def _warn_missing(key):
    if key not in _missing:
        _missing.add(key)
        _LOG.warning("i18n: brak klucza %r (język %r) — renderuję klucz", key, _LANG)


def t(key, **kw):
    """Etykieta UI dla bieżącego języka. Brak klucza / zły kształt (wpis mnogi) → klucz + log dev.
    Brak bieżącego języka → spadek na PL, potem na klucz. Interpolacja `str.format(**kw)`."""
    forms = CATALOG.get(key)
    if not isinstance(forms, dict) or isinstance(forms.get(_LANG, forms.get(DEFAULT)), dict):
        _warn_missing(key)
        return key
    text = forms.get(_LANG) or forms.get(DEFAULT) or key
    return text.format(**kw) if kw else text


def _plural_cat(lang, n):
    """Kategoria formy dla `n`. PL: one/few/many (12–14 zawsze many). Reszta (EN): one/other."""
    if lang == "pl":
        if n == 1:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    return "one" if n == 1 else "other"


def t_plural(key, n, **kw):
    """Fraza odmieniona przez `n` (FRAZA, nie słowo — PL odmienia przymiotnik, EN rzeczownik, więc
    forma = pełna fraza per język). Wstrzykuje `n=n` (+ `kw`) przez `str.format`. Zły kształt/brak →
    klucz + log dev."""
    forms = CATALOG.get(key)
    lang_forms = forms.get(_LANG) if isinstance(forms, dict) else None
    if not isinstance(lang_forms, dict):
        lang_forms = forms.get(DEFAULT) if isinstance(forms, dict) else None
    if not isinstance(lang_forms, dict):
        _warn_missing(key)
        return key
    cat = _plural_cat(_LANG if isinstance(forms.get(_LANG), dict) else DEFAULT, n)
    tmpl = lang_forms.get(cat) or lang_forms.get("other") or lang_forms.get("many") or key
    return tmpl.format(n=n, **kw)
