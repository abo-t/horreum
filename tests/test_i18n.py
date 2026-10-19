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
    # `gui/flows/` (drogi: Znajdź) mówi do UI tym samym katalogiem - bez niej bramka byłaby ślepa
    # na każdy klucz strony Znajdź.
    for p in sorted(GUI.glob("*.py")) + sorted(GUI.glob("flows/*.py")) + _RDZEN_Z_I18N:
        used |= _collect_t_keys(p)
    unknown = used - set(CATALOG)
    assert not unknown, f"klucze i18n spoza katalogu: {sorted(unknown)}"
    assert "grid.frames" in used, "kolektor nic nie złapał — bramka byłaby ślepa"
    for p in _RDZEN_Z_I18N:
        assert _collect_t_keys(p), f"{p.name}: kolektor nic nie złapał - bramka byłaby ślepa"


# Moduły spoza `gui/`, które mówią do UI przez katalog (FH-13: opis drzewa filtra na pasku zbioru).
_RDZEN_Z_I18N = [PKG / "filter_engine.py", PKG / "supersede.py"]


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
    # Źródło wejścia stosu (`grid._lineage_item_text`): każda ranga kanonu, także `harvest` (AR-102).
    from horreum import repo
    braki += [f"grid.lin.src.{z}" for z in repo.RANGA_ASSERT if f"grid.lin.src.{z}" not in CATALOG]
    # Odmowa gestu ręki osi kalibracji (`repo.KalibratorOdrzucony.token`) i stan klasy w nagłówku
    # panelu (`grid_lineage._calibration_head_text`) - oba składane w locie.
    braki += [f"grid.lin.cal.refused.{t}" for t in repo.CALIBRATION_REFUSALS
              if f"grid.lin.cal.refused.{t}" not in CATALOG]
    braki += [f"grid.lin.cal.mis.{p}" for pola in lineage._POLA_PRZEPISU.values() for p in pola
              if f"grid.lin.cal.mis.{p}" not in CATALOG]
    braki += [f"grid.lin.cal.head.{s}" for s in ("linked", "linked_inactive", "linked_mismatch",
                                                 "pending", "gap")
              if f"grid.lin.cal.head.{s}" not in CATALOG]
    # AR-128 (bramka kodu T24, N14/N15): powód braku kadru zestawu na panelu Osi teleskopu i powód
    # odmowy gestu „Popraw f/ w plikach…" - oba składane w locie z tokenów właściciela.
    from horreum import sky
    from horreum.gui import queries
    braki += [f"axis.tel.rig_reason.{r}" for r in sky.RIG_REASONS
              if f"axis.tel.rig_reason.{r}" not in CATALOG]
    braki += [f"grid.optics.refused.{r}" for r in queries.FIX_REFUSALS
              if f"grid.optics.refused.{r}" not in CATALOG]
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


def test_parytet_podstawy_rodowodu_stosu_w_obie_strony():
    """Podstawa rodowodu stosu (`integration.lineage_basis`, 0034) - klucz składany w locie
    (`grid_lineage._lineage_basis_text`: `grid.lin.basis.{token}`), więc kolektor literałów go nie
    widzi. Parytet w OBIE strony z jedynym zbiorem tokenów rdzenia (`stacks.LINEAGE_BASES`): token
    bez zdania to surowy klucz na ekranie, zdanie bez tokenu - martwy wpis, który udaje podstawę,
    której rdzeń nie umie wyprodukować.

    Falsyfikator: dopisz token do `LINEAGE_BASES` bez wpisu w katalogu (albo wpis bez tokenu) - test
    czerwienieje."""
    from horreum import stacks

    tokeny = {f"grid.lin.basis.{t}" for t in stacks.LINEAGE_BASES}
    katalog = {k for k in CATALOG if k.startswith("grid.lin.basis.")}
    assert katalog == tokeny, f"rozjazd podstaw: bez zdania {tokeny - katalog}, bez tokenu {katalog - tokeny}"


# ---- odmiana i słowa (paczki D/E, P, wizytacje) --------------------------------------------------

def _forma(lang, klucz, n, **kw):
    i18n.set_lang(lang)
    return i18n.t_plural(klucz, n, **kw)


def test_licznik_propozycji_ze_sciezki_odmienia_nazwy_w_obu_jezykach():
    """„1 nazw / 1 klatek" - wiersz kolejki przeglądu szedł jedną formą. Odmiana po nazwach, człon
    klatek podaje wołający odmieniony (`object.review_count`).

    Falsyfikator: wróć do wpisu prostego `{names} nazw / {frames} klatek` - formy padają."""
    klatki = lambda lang, n: _forma(lang, "object.review_count", n)
    for n, pl in ((1, "1 nazwa"), (3, "3 nazwy"), (5, "5 nazw"), (12, "12 nazw"), (22, "22 nazwy")):
        assert _forma("pl", "object.path_proposed_count", n, frames=klatki("pl", 1)) == \
            f"{pl} / 1 klatka"
    assert _forma("en", "object.path_proposed_count", 1, frames=klatki("en", 1)) == "1 name / 1 frame"
    assert _forma("en", "object.path_proposed_count", 3, frames=klatki("en", 707)) == \
        "3 names / 707 frames"


def test_panel_rodowodu_mowi_o_zestawie_w_liczbie_pojedynczej():
    """„ma jeszcze 1 inna wersja obrazu" i „zestaw … mają" - podmiotem jest zestaw (liczba
    pojedyncza), liczba wersji stoi w bierniku."""
    oczekiwane = {1: "ma jeszcze 1 inną wersję obrazu", 3: "ma jeszcze 3 inne wersje obrazu",
                  5: "ma jeszcze 5 innych wersji obrazu", 12: "ma jeszcze 12 innych wersji obrazu",
                  22: "ma jeszcze 22 inne wersje obrazu"}
    for n, koniec in oczekiwane.items():
        assert _forma("pl", "grid.lin.flag.twins", n) == f"ten sam zestaw klatek {koniec}"
    assert _forma("en", "grid.lin.flag.twins", 1) == "1 other version of the image uses the same set of frames"
    assert _forma("en", "grid.lin.flag.twins", 2) == "2 other versions of the image use the same set of frames"


def test_jeden_zbior_rodowodu_ma_jedna_nazwe_na_trzech_powierzchniach():
    """Wiersz Porządków mówił „Obrazy bez rodowodu", perspektywa, którą otwiera - „Rodowód do
    potwierdzenia", a pasek kryteriów - „tylko obrazy bez rodowodu". To jeden zbiór
    (`queries.lineage_pending_frame_ids`); „bez rodowodu" znaczy gdzie indziej stos, którego Dostawa
    nie ujęła (`status.harvest_lineage_none`).

    Falsyfikator: wpisz w `tasks.stacks_lineage` inną nazwę niż w `perspective.lineage`."""
    for lang in ("pl", "en"):
        i18n.set_lang(lang)
        nazwa = i18n.t("perspective.lineage")
        assert i18n.t("tasks.stacks_lineage") == nazwa, lang
        assert nazwa.lower() in i18n.t("grid.criteria.only_lineage").lower(), lang


def test_zbior_w_drodze_mowi_jednym_czasownikiem_z_faza_paska():
    """„Czytam klatki…" na pasku i „Wczytuję zbiór…" w odmowie i podpowiedzi - jeden stan (zbiór
    w drodze), dwa czasowniki. Odmowa i podpowiedź zaczynają się frazą fazy paska."""
    for lang in ("pl", "en"):
        i18n.set_lang(lang)
        faza = i18n.t("busy.read_frames").rstrip("…")
        assert i18n.t("grid.sel.loading_refused").startswith(faza), lang
        assert i18n.t("grid.sel.loading_tip").startswith(faza), lang


def test_EN_recepty_i_pusty_stan_perspektywy_jednym_rodzajem_cudzyslowu():
    """EN pasek i pusty stan mówiły prostym `"Review"` obok drukarskiego `“Lineage to confirm”`
    z Dostawy. Zdania recepty, pustego stanu i panelu rodowodu - wyłącznie cudzysłów drukarski."""
    klucze = ("grid.empty_persp_action", "grid.sel.out_of_view_set", "grid.sel.out_of_view_persp",
              "grid.lin.cal.pending")
    proste = [k for k in klucze if '"' in CATALOG[k]["en"]]
    assert not proste, f"prosty cudzysłów w EN: {proste}"
    assert all("“" in CATALOG[k]["en"] for k in klucze)
    for forma in CATALOG["grid.sel.reveal_target"]["en"].values():
        assert '"' not in forma


# ---- BRAMKA: cudzysłów EN (AR-255) ------------------------------------------------------------------

_CUDZYSLOW_OBCY_EN = "„«»"      # polski „, francuskie/niemieckie « »


def _wartosci_en(wartosc):
    """Teksty wpisu EN - prosty `str` i formy mnogie (słownik form), rekurencyjnie."""
    if isinstance(wartosc, str):
        yield wartosc
    elif isinstance(wartosc, dict):
        for forma in wartosc.values():
            yield from _wartosci_en(forma)


def _pary_angielskie(tekst):
    """Każde U+201C zamyka U+201D, zanim otworzy się następne, i żadne U+201D nie stoi bez otwarcia."""
    otwarty = False
    for znak in tekst:
        if znak == "“":
            if otwarty:
                return False
            otwarty = True
        elif znak == "”":
            if not otwarty:
                return False
            otwarty = False
    return not otwarty


def test_EN_cudzyslow_wylacznie_angielski_w_parach():
    """EN `path.cards_restored_note` mówił „Confirm” polskim cudzysłowem (AR-255) - i nie on jeden:
    predykat znalazł 9 takich wpisów EN (`„…”` otwiera U+201E, a zamyka U+201D, więc w EN zamknięcie
    wisi bez otwarcia). Bramka idzie po WARTOŚCIACH katalogu (komentarze i wzmianki w źródle nie są
    wejściem): w żadnej wartości EN, także w formach mnogich, nie ma U+201E, U+00AB ani U+00BB, a U+201C
    i U+201D stoją parami. Falsyfikator: jeden wpis EN z `„…”` - czerwień z nazwą klucza."""
    obce, bez_pary = [], []
    for klucz, wpis in CATALOG.items():
        for tekst in _wartosci_en(wpis["en"]):
            if set(tekst) & set(_CUDZYSLOW_OBCY_EN):
                obce.append(klucz)
            if not _pary_angielskie(tekst):
                bez_pary.append(klucz)
    assert not obce, f"cudzysłów spoza EN w wartości EN: {sorted(set(obce))}"
    assert not bez_pary, f"cudzysłów EN bez pary: {sorted(set(bez_pary))}"
