"""AR-341: wiersz edytora wzoru nazwy (`grid_panels._TokenRow`) pokazuje specyfikację wiernie albo mówi, że nie umie -
nigdy nie podmienia jej po cichu. Token spoza słownika, `case` spoza listy wielkości liter, `n` folderu nieliczbowe
albo spoza pola poziomu i `re` niebędące napisem wracają z `spec()` bez zmian, a „Podgląd” odmawia ich drogą rdzenia
(`naming.validate_template`, kody `rename_tpl_*`). Dawniej: `datetime`, „jak w bazie”, przycięte `n`, wyrażenie
„None” albo wyjątek w konstruktorze wiersza. Każdy test nazywa falsyfikator.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum.gui import i18n

from test_gui_grid import rn_view  # noqa: F401 - fikstura widoku nad dwoma FITS z DATE-OBS
from test_gui_powody_pisarza import _klik_w, _komunikaty, _panel_nazw


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def jezyk():
    yield i18n.set_lang
    i18n.set_lang("pl")


def _wiersz(spec):
    from horreum.gui.grid_panels import _TokenRow
    return _TokenRow(spec)


def test_token_spoza_slownika_zostaje_soba(qapp):
    """Token spoza słownika: `spec()` oddaje go bez zmian, combo mówi „nieznany token: 'planeta'”, pola argumentów
    schowane. Falsyfikator: `findData` = -1 zostawia combo na `datetime` (stan sprzed AR-341)."""
    for spec in ("planeta", {"t": "planeta", "n": 2}, {"n": 2}):
        wiersz = _wiersz(spec)
        assert wiersz.spec() == spec, spec
        tok = spec.get("t") if isinstance(spec, dict) else spec
        assert wiersz.combo.currentText() == i18n.t("grid.token.unknown", tok=repr(tok))
        assert wiersz.level.isHidden() and wiersz.regex.isHidden() and wiersz.case.isHidden()


def test_kind_z_nieznana_wielkoscia_liter_zachowuje_case(qapp):
    """`kind` z `case` spoza listy: `spec()` oddaje surowy `case`, pole wielkości liter mówi, że go nie zna; `case`
    pusty i znany - jak dotąd. Falsyfikator: nieznany `case` → indeks 0 („jak w bazie”, goły `kind`)."""
    wiersz = _wiersz({"t": "kind", "case": "title"})
    assert wiersz.spec() == {"t": "kind", "case": "title"}
    assert wiersz.case.currentText() == i18n.t("grid.token.case_unknown", case="'title'")
    assert not wiersz.case.isHidden()
    assert _wiersz("kind").spec() == "kind"
    assert _wiersz({"t": "kind", "case": "upper"}).spec() == {"t": "kind", "case": "upper"}


@pytest.mark.parametrize("n", ["abc", 12, 0, None])
def test_folder_z_argumentem_spoza_pola(qapp, n):
    """`folder` z `n`, którego pole poziomu (1..8) nie pokaże wiernie: konstruktor wiersza bez wyjątku, `spec()` bez
    zmian, combo mówi, że argument jest spoza edytora. Falsyfikatory: `int(n)` bez osłony (`ValueError` w konstruktorze);
    `setValue` przycinające 12 do 8 i 0 do 1."""
    spec = {"t": "folder", "n": n}
    wiersz = _wiersz(spec)
    assert wiersz.spec() == spec
    assert wiersz.combo.currentText() == i18n.t("grid.token.arg_unknown", token=i18n.t("grid.token.folder"),
                                                arg=repr(spec))
    assert _wiersz({"t": "folder", "n": 3}).spec() == {"t": "folder", "n": 3}


def test_orig_z_re_nienapisem(qapp):
    """`orig` z `re` niebędącym napisem wraca bez zmian. Falsyfikator: `str(re)` - `None` jako wyrażenie „None”."""
    spec = {"t": "orig", "re": None}
    assert _wiersz(spec).spec() == spec
    assert _wiersz({"t": "orig", "re": r"gain\d+"}).spec() == {"t": "orig", "re": r"gain\d+"}


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_podglad_odmawia_tokenu_spoza_slownika(rn_view, jezyk, lang):
    """„Podgląd” (klik) na wzorze z tokenem spoza słownika i osobno z nieznanym `case`: odmowa wzoru w języku UI
    (`rename_tpl_unknown_token`, `rename_tpl_bad_case`), zero stagingu. Falsyfikator: edytor podmienia token na
    `datetime` / `case` na „jak w bazie” - wzór przechodzi walidację, podgląd liczy nazwy."""
    jezyk(lang)
    view, _con, _pliki = rn_view
    bar = _panel_nazw(view)
    komunikaty = _komunikaty(view)
    for wzor, kod, wartosc in ((["datetime", "planeta"], "rename_tpl_unknown_token", "'planeta'"),
                               ([{"t": "kind", "case": "title"}, "datetime"], "rename_tpl_bad_case", "'title'")):
        bar.template_editor.set_template(wzor)
        _klik_w(bar.btn_prev)
        zdanie = i18n.t(f"objchg.item.{kod}", value=wartosc)
        assert komunikaty[-1] == i18n.t("grid.rename.error", e=zdanie), komunikaty
    assert view._rename_pending_count() == 0


# ---------------------------------------------------------------- rdzeń: wzór z zewnątrz odmawia kodem

@pytest.mark.parametrize("spec, kod, params", [
    ({"t": "orig", "re": None}, "rename_tpl_bad_regex", {"value": "None", "detail": "NoneType"}),
    ({"t": "orig", "re": 5}, "rename_tpl_bad_regex", {"value": "5", "detail": "int"}),
    ({"t": "folder", "n": "abc"}, "rename_tpl_bad_level", {"value": "'abc'"}),
    ({"t": "folder", "n": None}, "rename_tpl_bad_level", {"value": "None"}),
    ({"t": "folder", "n": float("inf")}, "rename_tpl_bad_level", {"value": "inf"}),
])
def test_walidacja_wzoru_odmawia_kodem_re_nienapisu_i_zlego_poziomu(spec, kod, params):
    """`naming.validate_template`: `re` niebędące napisem i `n` folderu, którego rdzeń nie weźmie przez `int()`,
    odmawiają kodem (`OdmowaZPowodem` - `ValueError`, który łapią wołający). Falsyfikatory: `re.compile(None)`
    (`TypeError` poza `except`); `n="abc"` przepuszczone do `compose_name` (surowy `ValueError` bez kodu)."""
    from horreum import naming
    from horreum.item_reasons import OdmowaZPowodem
    with pytest.raises(OdmowaZPowodem) as info:
        naming.validate_template(["datetime", spec])
    assert info.value.powod.code == kod and dict(info.value.powod.params) == params


@pytest.mark.parametrize("n", [0, 12, "3", -2])
def test_walidacja_wzoru_przepuszcza_poziom_ktory_rdzen_bierze(n):
    """Wartości `n`, które `_folder_segment` bierze przez `int()`, przechodzą - zachowanie rdzenia bez zmian
    (`n` = 0 jak 1, 12 ponad korzeniem = segment pominięty). Falsyfikator: walidacja zakresu pola edytora (1..8)
    przeniesiona do rdzenia."""
    from horreum import naming
    naming.validate_template(["datetime", {"t": "folder", "n": n}])


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_podglad_i_staging_odmawiaja_re_nienapisu_i_zlego_poziomu(rn_view, jezyk, lang, monkeypatch):
    """„Podgląd” i „Do stagingu” (kliki) na wzorze zachowanym przez edytor z `re=None` i osobno z `n="abc"`: zdanie
    odmowy z kodem w języku UI, żaden wyjątek nie ucieka ze slotu, zero stagingu. Falsyfikatory: `validate_template`
    bez gałęzi `re` (`TypeError` ze slotu - straż błędu programu) i bez gałęzi `folder` (surowe zdanie Pythona)."""
    import sys
    jezyk(lang)
    wyjatki = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: wyjatki.append(exc))
    view, _con, _pliki = rn_view
    bar = _panel_nazw(view)
    komunikaty = _komunikaty(view)
    for spec, kod, params in (({"t": "orig", "re": None}, "rename_tpl_bad_regex",
                               {"value": "None", "detail": "NoneType"}),
                              ({"t": "folder", "n": "abc"}, "rename_tpl_bad_level", {"value": "'abc'"})):
        bar.template_editor.set_template(["datetime", spec])
        assert bar.policy()["template"] == ["datetime", spec]
        zdanie = i18n.t("grid.rename.error", e=i18n.t(f"objchg.item.{kod}", **params))
        for przycisk in (bar.btn_prev, bar.btn_stage):
            _klik_w(przycisk)
            QApplication.processEvents()
            assert komunikaty[-1] == zdanie, komunikaty
    assert wyjatki == [], wyjatki
    assert view._rename_pending_count() == 0


# ---------------------------------------------------------------- pozycja obca żyje do pierwszego ruchu człowieka

def _klawisz(combo, klawisz):
    """Prawdziwy klawisz na combo (strzałka = następna/poprzednia pozycja, jak u człowieka z fokusem w polu)."""
    from PySide6.QtTest import QTest
    QTest.keyClick(combo, klawisz)


def test_obcy_case_nie_przezywa_zmiany_typu_tokenu(qapp):
    """Wiersz `kind` z nieznanym `case`: człowiek zmienia typ (strzałka w dół - filtr) i wraca (w górę - rodzaj) -
    `spec()` daje goły `kind` („jak w bazie”), pozycji obcej wielkości liter już nie ma. Falsyfikator: pozycja obca
    bez zdejmowania przy ręcznej zmianie typu (obcy `case` wraca razem z `kind` - zwykły wybór, wzór do odmowy)."""
    from PySide6.QtCore import Qt
    from horreum.gui.grid_panels import _TokenRow
    wiersz = _wiersz({"t": "kind", "case": "title"})
    wiersz.show()
    try:
        assert wiersz.combo.currentData() == "kind" and wiersz.spec() == {"t": "kind", "case": "title"}
        _klawisz(wiersz.combo, Qt.Key_Down)
        assert wiersz.combo.currentData() == "filter"
        _klawisz(wiersz.combo, Qt.Key_Up)
        assert wiersz.combo.currentData() == "kind"
        assert wiersz.spec() == "kind"
        assert wiersz.case.count() == len(_TokenRow._CASES)
    finally:
        wiersz.close()


def test_obcy_case_znika_po_wyborze_innej_wielkosci(qapp):
    """Wiersz `kind` z nieznanym `case` (pozycja ostatnia): strzałka w górę - „małe”, strzałka w dół nie wraca na
    obcy `case`. Falsyfikator: pozycja obca wielkości liter zostaje po opuszczeniu."""
    from PySide6.QtCore import Qt
    from horreum.gui.grid_panels import _TokenRow
    wiersz = _wiersz({"t": "kind", "case": "title"})
    wiersz.show()
    try:
        _klawisz(wiersz.case, Qt.Key_Up)
        assert wiersz.spec() == {"t": "kind", "case": "lower"}
        _klawisz(wiersz.case, Qt.Key_Down)
        assert wiersz.spec() == {"t": "kind", "case": "lower"}
        assert wiersz.case.count() == len(_TokenRow._CASES)
    finally:
        wiersz.close()


@pytest.mark.parametrize("spec", ["planeta", {"t": "folder", "n": "abc"}, {"t": "orig", "re": None}])
def test_obca_pozycja_typu_znika_po_opuszczeniu(qapp, spec):
    """Pozycja obca typu tokenu (token spoza słownika, argument spoza edytora) jest ostatnia: strzałka w górę -
    „końcowe _”, strzałka w dół nie wraca na pozycję obcą, a combo ma znów sam słownik. Falsyfikator: pozycja obca
    zostaje i zwykła nawigacja po typach przywraca spec, którego człowiek właśnie się pozbył."""
    from PySide6.QtCore import Qt
    from horreum.gui.grid_panels import _TokenRow
    wiersz = _wiersz(spec)
    wiersz.show()
    try:
        assert wiersz.spec() == spec
        _klawisz(wiersz.combo, Qt.Key_Up)
        assert wiersz.combo.currentData() == "trail"
        _klawisz(wiersz.combo, Qt.Key_Down)
        assert wiersz.spec() == "trail"
        assert wiersz.combo.count() == len(_TokenRow._TOKENS)
    finally:
        wiersz.close()
