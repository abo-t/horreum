"""Widok osi OBIEKT (`horreum.gui.app.ObjectAxisView`, PLAN_gui_object §4 + #8/P4) — testy STERUJĄCE
realnym oknem Qt (offscreen) na bazie §8 rozszerzonej o oś obiektu (`seed_object_axis`). Sprawdzają
glue widget↔read-model: biblioteka odbija obiekty, filtr zmienia listę, zaznaczenie obiektu pokazuje
klatki, kolejka przeglądu drąży do nierozwiązanych klatek (dispatch po string-tagu: `UserRole`=tag,
`UserRole+1`=payload, R#6) i do kopii nieczytelnych (Z6), present=0 widoczny, render nie pusty.
JEDYNA akcja zapisu = „Przypisz obiekt…" (#8/P4, przez `repo.user_assign_object`) — reszta interakcji
READ-ONLY (żaden event nie przyrasta od filtrowania/zaznaczania/drążenia).

`importorskip` na poziomie MODUŁU (PLAN_gui §4): bez PySide6 cały plik się pomija. `QT_QPA_PLATFORM=
offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo
from horreum.gui import queries
from horreum.gui.app import (
    AssignObjectDialog, ObjectAxisView, COPY_HEADERS, FRAME_HEADERS,
    OBJ_COL_CANON, OBJ_COL_FRAMES)

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
    # pozycja obiekt-review: dispatch po string-tagu (R#6) — UserRole=tag, UserRole+1=payload
    target = None
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == "object_raw" \
                and v.review.item(r).data(UROLE + 1) == "FlatWizard":
            target = r
            break
    assert target is not None
    v.review.setCurrentRow(target)
    shas = _frame_shas(v)
    assert "sha-objrev1"[:12] in shas and "sha-objrev2"[:12] in shas
    # zaznaczenie review wyczyściło zaznaczenie obiektu (źródła klatek wzajemnie wykluczające)
    assert not v.objects.selectedItems()


def test_kolejka_liczniki_informacyjne(view):
    """#13/P4: „kopie nieczytelne" to OSOBNA, klikalna pozycja (drążenie Z6); liczniki
    config-review/headerless zostają na pozycji informacyjnej (bez tagu → nieklikana)."""
    v, con, ids = view
    items = [(v.review.item(r).text(), v.review.item(r).data(UROLE))
             for r in range(v.review.count())]
    # fixture §8 nie ma oznaczonych kopii → 0; pozycja klikalna (tag 'unreadable')
    assert ("— kopie nieczytelne: 0", "unreadable") in items
    # nota „rozwiązywanie w przygotowaniu" zawężona do dwóch kanałów bez akcji (R#9)
    assert any("config-review: 4" in t and "bez nagłówka: 1" in t
               and "rozwiązywanie w przygotowaniu" in t and tag is None for t, tag in items)


# --- read-only: render i brak zapisu ---

def test_render_nie_pusty(view):
    v, con, ids = view
    img = v.grab()
    assert not img.isNull() and img.width() > 0


def test_interakcje_nie_emituja_eventow(view):
    """Interakcje READ-ONLY: filtrowanie, zaznaczanie obiektów i drążenie review NIE dokładają
    eventów (jedyna akcja zapisu widoku to „Przypisz obiekt…" — testowana osobno)."""
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


# --- akcja zapisu „Przypisz obiekt…" (#8/P4) ---

def _select_review_tag(v, tag):
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == tag:
            v.review.setCurrentRow(r)
            return r
    raise AssertionError(f"brak pozycji review z tagiem {tag!r}")


def test_przycisk_przypisz_sledzi_tag_i_busy(view):
    """„Przypisz obiekt…" aktywny WYŁĄCZNIE przy pozycji `object_raw` i poza biegiem pipeline
    (szczery disabled — R#10: przycisk śledzi tag, nie to, która lista „ostatnio kliknięta")."""
    v, con, ids = view
    assert not v.assign_btn.isEnabled()                      # start: selekcja na obiekcie, nie review
    _select_review_tag(v, "object_raw")
    assert v.assign_btn.isEnabled()
    _select_review_tag(v, "unreadable")
    assert not v.assign_btn.isEnabled()
    _select_review_tag(v, "object_raw")
    v.set_busy(True)                                         # pipeline w biegu → wygaszony
    assert not v.assign_btn.isEnabled()
    v.set_busy(False)
    assert v.assign_btn.isEnabled()


def test_dialog_domyslny_wybor_istniejacego(view):
    """Dialog (#8): domyślnie zaznacza pierwszy obiekt biblioteki; walidacja → `selected`
    = (canon, catalog, None) — `kind=None`, bo repo nie INSERTuje istniejącego obiektu."""
    v, con, ids = view
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", alias_norm="FLATWIZARD",
                             frame_count=2, parent=v)
    dlg._validate_and_accept()                               # combo bez zmian: M42 (ORDER canon)
    assert dlg.selected == ("M42", "Messier", None)
    dlg.close()


def test_dialog_nowe_oznaczenie_nadpisuje_combo(view):
    """Oznaczenie wpisane ręcznie nadpisuje wybór z listy i parsuje się jak w resolverze
    („IC 1795" → canon IC1795, catalog IC, kind deep_sky)."""
    v, con, ids = view
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", alias_norm="FLATWIZARD",
                             frame_count=2, parent=v)
    dlg.designation.setText("IC 1795")
    dlg._validate_and_accept()
    assert dlg.selected == ("IC1795", "IC", "deep_sky")
    dlg.close()


def test_dialog_nieparsowalne_oznaczenie_odrzuca(view):
    """Oznaczenie nieparsowalne katalogowo → czerwona nota, `selected` zostaje None (dialog by
    został otwarty — bez `accept()`)."""
    v, con, ids = view
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", alias_norm="FLATWIZARD",
                             frame_count=2, parent=v)
    dlg.designation.setText("???")
    dlg._validate_and_accept()
    assert dlg.selected is None
    assert "Nie rozpoznaję" in dlg.error.text()
    dlg.close()


def test_dialog_konflikt_aliasu_odrzuca_pre_check(view):
    """Pre-check UX (R#8/TOCTOU): alias nazwy wskazuje INNY obiekt niż wybrany → nota konfliktu,
    `selected` None; wybór właściwego obiektu przechodzi. Ostateczny guard = `repo` (osobne testy)."""
    v, con, ids = view
    repo.add_object_alias(con, alias_norm="FLATWIZARD", object_id=ids["objects"]["NGC7000"],
                          source="user", now="2026-07-21T12:00:00")
    dlg = AssignObjectDialog(con, object_raw="FlatWizard", alias_norm="FLATWIZARD",
                             frame_count=2, parent=v)
    dlg._validate_and_accept()                               # domyślny wybór M42 ≠ NGC7000 → konflikt
    assert dlg.selected is None
    assert "wskazuje już" in dlg.error.text()
    for i in range(dlg.combo.count()):
        if dlg.combo.itemData(i)[0] == ids["objects"]["NGC7000"]:
            dlg.combo.setCurrentIndex(i)
            break
    dlg._validate_and_accept()
    assert dlg.selected == ("NGC7000", "NGC", None)
    dlg.close()


def test_przypisanie_zmniejsza_kolejke_i_zapisuje_user(view):
    """DoD #8: po przypisaniu grupy (ścieżka repo z `_on_assign`) pozycja review ZNIKA z kolejki,
    klatki widnieją pod obiektem docelowym z `object_source='user'`; biblioteka liczy nowe klatki.
    (Dialog `exec()` jest modalny — ścieżkę widget↔dialog pokrywają testy dialogu powyżej.)"""
    v, con, ids = view
    rows = queries.object_review_frames(con, "FlatWizard")
    assert len(rows) == 2
    assigned, skipped = repo.user_assign_object(
        con, alias_norm="FLATWIZARD", canon="M42", catalog="Messier", kind=None,
        frame_ids=[r["frame_id"] for r in rows], now="2026-07-21T12:00:00")
    assert (assigned, skipped) == (2, 0)
    v.refresh()
    texts = [v.review.item(r).text() for r in range(v.review.count())]
    assert not any("FlatWizard" in t for t in texts)         # nigdy nie wraca do kolejki
    assert _obj_rows(v) == {"M42": 5, "NGC7000": 5}          # M42: 3+2
    for f in ("objrev1", "objrev2"):
        r = con.execute("SELECT object_id, object_source FROM frame WHERE id=?",
                        (ids["frames"][f],)).fetchone()
        assert (r["object_id"], r["object_source"]) == (ids["objects"]["M42"], "user")


# --- drążenie „kopie nieczytelne" (Z6/P4) ---

def test_kopie_nieczytelne_drazenie_do_dokladnych_kopii(view):
    """Z6: klik pozycji „kopie nieczytelne" → prawy panel w trybie „kopie" (COPY_HEADERS, dokładne
    location z markerem); wybór obiektu przywraca tabelę klatek (tryb kopii znika, D-P4-5)."""
    v, con, ids = view
    loc = con.execute("SELECT id FROM location WHERE volume = 'vol2'").fetchone()
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data="sha-a1",
                                     path="/backup/a1.fits", mtime="t2", reason="OSError",
                                     now="2026-07-21T12:00:00")
    v.refresh()
    r = _select_review_tag(v, "unreadable")
    assert "kopie nieczytelne: 1" in v.review.item(r).text()
    hdrs = [v.frames.horizontalHeaderItem(c).text() for c in range(v.frames.columnCount())]
    assert hdrs == COPY_HEADERS
    assert v.frames.rowCount() == 1
    assert v.frames.item(0, 0).text() == "a1.fits"           # basename, pełna ścieżka w tooltipie
    assert v.frames.item(0, 0).toolTip() == "/backup/a1.fits"
    assert v.frames.item(0, 1).text() == "vol2"
    assert v.frames.item(0, 2).text() == "tak"               # kopia nadal obecna
    assert v.frames_label.text() == "Kopie nieczytelne (1)"
    # wybór obiektu → powrót do tabeli klatek (tryb „kopie" znika)
    _select_object_canon(v, "NGC7000")
    hdrs = [v.frames.horizontalHeaderItem(c).text() for c in range(v.frames.columnCount())]
    assert hdrs == FRAME_HEADERS
    assert v.frames.rowCount() == 5
