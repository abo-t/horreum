"""Widżet osi OBIEKT (`horreum.gui.app.ObjectAxisView`, PLAN_gui_object §4) — testy STERUJĄCE
realnym oknem Qt (offscreen) na bazie §8 rozszerzonej o oś obiektu (`seed_object_axis`). Sprawdzają
glue widget↔read-model: biblioteka odbija obiekty, filtr zmienia listę, zaznaczenie obiektu pokazuje
klatki, kolejka przeglądu drąży do nierozwiązanych klatek, present=0 widoczny, render nie pusty.
Widok READ-ONLY: ZERO akcji zapisu (żaden event nie przyrasta od interakcji).

`importorskip` na poziomie MODUŁU (PLAN_gui §4): bez PySide6 cały plik się pomija. `QT_QPA_PLATFORM=
offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db
from horreum.gui.app import ObjectAxisView, OBJ_COL_CANON, OBJ_COL_FRAMES

from fixture_s8 import seed_object_axis

from PySide6.QtWidgets import QApplication

UROLE = 0x0100   # Qt.UserRole


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "s8_obj.db"))
    ids = seed_object_axis(con)
    v = ObjectAxisView(con)
    yield v, con, ids
    v.close()
    con.close()


def _obj_rows(v):
    return {v.objects.item(r, OBJ_COL_CANON).text():
            int(v.objects.item(r, OBJ_COL_FRAMES).text())
            for r in range(v.objects.rowCount())}


def _select_object_canon(v, canon):
    for r in range(v.objects.rowCount()):
        if v.objects.item(r, OBJ_COL_CANON).text() == canon:
            v.objects.selectRow(r)
            return
    raise AssertionError(f"obiekt {canon} nie ma w bibliotece")


def _frame_shas(v):
    return {v.frames.item(r, 0).text() for r in range(v.frames.rowCount())}


def _events(con):
    return con.execute("SELECT count(*) FROM event").fetchone()[0]


# --- biblioteka: stan widoczny bez klikania ---

def test_biblioteka_obiekty_z_licznoscia(view):
    v, con, ids = view
    assert _obj_rows(v) == {"M42": 3, "NGC7000": 5}


def test_facety_wypelnione(view):
    v, con, ids = view
    # placeholder (wszystkie) + 4 teleskopy kanoniczne
    assert v.combo_tel.count() == 1 + 4
    assert v.combo_tel.itemData(0) is None
    # placeholder + Ha + OIII
    assert [v.combo_filter.itemText(i) for i in range(v.combo_filter.count())] == \
        ["(wszystkie)", "Ha", "OIII"]


# --- filtr zmienia listę ---

def test_filtr_teleskop_zaweza(view):
    v, con, ids = view
    # ustaw filtr na teleskop A (index: 0=placeholder, kolejność facetów po id → A pierwszy)
    for i in range(v.combo_tel.count()):
        if v.combo_tel.itemData(i) == ids["A"]:
            v.combo_tel.setCurrentIndex(i)
            break
    assert _obj_rows(v) == {"NGC7000": 2}      # tylko a1,a2 pod A


def test_filtr_powrot_do_wszystkich(view):
    v, con, ids = view
    for i in range(v.combo_filter.count()):
        if v.combo_filter.itemText(i) == "Ha":
            v.combo_filter.setCurrentIndex(i)
            break
    assert _obj_rows(v) == {"NGC7000": 2}      # Ha tylko na a1,a2
    v.combo_filter.setCurrentIndex(0)          # (wszystkie)
    assert _obj_rows(v) == {"M42": 3, "NGC7000": 5}


# --- zaznaczenie obiektu → klatki ---

def test_zaznaczenie_obiektu_pokazuje_klatki(view):
    v, con, ids = view
    _select_object_canon(v, "NGC7000")
    # 5 klatek (a1,a2,c1,c2,present0), każda raz mimo 1:N location
    assert v.frames.rowCount() == 5


def test_present0_widoczny_jako_nie(view):
    v, con, ids = view
    _select_object_canon(v, "NGC7000")
    presents = {v.frames.item(r, 5).text() for r in range(v.frames.rowCount())}
    assert "nie" in presents                   # present0 pokazany, nie odsiany (R#7)


def test_kolumna_teleskop_fallback_canon(view):
    """Wizytator P1 #1 (po PF-2): teleskopy nienazwane (label=NULL) → kolumna Teleskop pokazuje
    `telescop_canon` (nazwę z nagłówka), nie pustkę. a1,a2 pod teleskopem A ('A140R')."""
    v, con, ids = view
    _select_object_canon(v, "NGC7000")
    tels = {v.frames.item(r, 1).text() for r in range(v.frames.rowCount())}
    assert "A140R" in tels                     # A (a1,a2) — canon zamiast pustki
    assert "RC8" in tels                       # C (c1,c2)
    assert "" in tels                          # present0 (config NULL) — brak teleskopu = puste


def test_pusty_stan_nota_widoczna_w_widoku(view):
    """Wizytator P1 #2: filtr bez trafień → nota pustego stanu WIDOCZNA w obszarze biblioteki (nie
    tylko ulotny flash na statusbarze); tabela obiektów schowana."""
    # offscreen bez .show(): isVisible() zawsze False (okno nie pokazane) → sprawdzamy isHidden()
    # (jawna flaga setVisible, niezależna od pokazania rodzica).
    v, con, ids = view
    assert v.lib_empty.isHidden()              # są obiekty → nota schowana
    for i in range(v.combo_tel.count()):
        if v.combo_tel.itemData(i) == ids["D"]:    # teleskop D bez obiektów
            v.combo_tel.setCurrentIndex(i)
            break
    assert not v.lib_empty.isHidden()          # pusty filtr → nota odkrywalna w widoku
    assert v.objects.isHidden()                # tabela schowana (nie myli pustymi nagłówkami)


# --- kolejka przeglądu drąży do klatek ---

def test_kolejka_review_drazenie(view):
    v, con, ids = view
    # pozycja obiekt-review „FlatWizard" (UserRole=object_raw)
    target = None
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == "FlatWizard":
            target = r
            break
    assert target is not None
    v.review.setCurrentRow(target)
    shas = _frame_shas(v)
    assert "sha-objrev1"[:12] in shas and "sha-objrev2"[:12] in shas
    # zaznaczenie review wyczyściło zaznaczenie obiektu (źródła klatek wzajemnie wykluczające)
    assert not v.objects.selectedItems()


def test_kolejka_liczniki_informacyjne(view):
    v, con, ids = view
    texts = [v.review.item(r).text() for r in range(v.review.count())]
    assert any("config-review: 4" in t and "bez nagłówka: 1" in t for t in texts)


# --- read-only: render i brak zapisu ---

def test_render_nie_pusty(view):
    v, con, ids = view
    img = v.grab()
    assert not img.isNull() and img.width() > 0


def test_interakcje_nie_emituja_eventow(view):
    """Widok READ-ONLY: filtrowanie, zaznaczanie obiektów i drążenie review NIE dokładają eventów."""
    v, con, ids = view
    before = _events(con)
    _select_object_canon(v, "NGC7000")
    _select_object_canon(v, "M42")
    v.combo_filter.setCurrentIndex(1)
    v.combo_filter.setCurrentIndex(0)
    after = _events(con)
    assert before == after


def test_pusty_filtr_nie_wybucha(view):
    """Filtr bez trafień (teleskop D bez obiektów) → biblioteka pusta, klatki puste, komunikat — bez
    wyjątku."""
    v, con, ids = view
    msgs = []
    v.status_message.connect(msgs.append)
    for i in range(v.combo_tel.count()):
        if v.combo_tel.itemData(i) == ids["D"]:
            v.combo_tel.setCurrentIndex(i)
            break
    assert v.objects.rowCount() == 0
    assert v.frames.rowCount() == 0
    assert msgs                                # pusty stan ma komunikat
